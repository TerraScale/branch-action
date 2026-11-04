# TerraScale branch action

Give every pull request its own copy of a TerraScale database. The action
branches the database when the pull request opens, hands the branch to later
steps (migrations, tests, preview deploys) and deletes it when the pull
request closes.

It runs the [ts CLI](https://github.com/TerraScale/terrascale/tree/main/sdk/go) on GitHub-hosted
Linux and macOS runners and acts as a TerraScale API key.

> [!IMPORTANT]
> **Unreleased — publication hold.** This README describes the safety contract in
> this source branch. The current `v1` release does not provide this contract,
> including source identity guards, conditional cleanup and reset generations.
> The `@main` example below uses source; pin a full commit SHA for your workflow.
> Source builds a pinned monorepo CLI, without publishing a CLI or action release.
> Keep the existing `v1` tag unchanged. Do not publish this source until the required
> CLI and guarded server routes are released and verified. Update the example to
> `@v2` only after that release exists.

## Usage

1. Create an API key for the project: `ts keys create ci` prints it once.
2. Add it to the repository as the secret `TERRASCALE_API_KEY`.
3. Add `.github/workflows/preview-database.yml`:

```yaml
name: Preview database
on:
  pull_request:
    types: [opened, reopened, synchronize, closed]

permissions:
  contents: read

concurrency: preview-database-${{ github.event.pull_request.number }}

jobs:
  branch:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v5
      - id: db
        uses: TerraScale/branch-action@main
        with:
          api-key: ${{ secrets.TERRASCALE_API_KEY }}
          database: app
      - name: Migrate and test against the branch
        if: github.event.action != 'closed'
        env:
          DATABASE_URL: ${{ steps.db.outputs.connection-url }}
        run: |
          PGDATABASE="$DATABASE_URL" psql -c 'SELECT 1'
```

Pull request 42 gets a database named `pr-42-<namespace hash>`, a copy of `app` with its
SQL tables. New pushes keep the branch and its
data. Closing or merging the pull request conditionally deletes this namespace's
verified previews, including reset generations. New branches expire after seven days by default.

After the job, `ts migrate up app` on the main branch applies the same
migrations to `app`.

## Inputs

| Input | Required | Description |
| --- | --- | --- |
| `api-key` | yes | API key with `databases:read`, `databases:write`, `documents:read` and `documents:write`. `ts keys create` keys have both. |
| `database` | yes | Database to branch. |
| `branch` | no | Namespace label, default `preview`. Must match `^[a-z][a-z0-9_-]{0,62}$`. Even explicit labels receive the repository/PR namespace. |
| `command` | no | `create` keeps the base preview, `reset` creates a fresh generation and retains previous databases, `delete` conditionally removes verified previews. Empty deletes when the pull request closed and creates otherwise. |
| `ttl` | no | Lifetime on creation, default `7d`; whole seconds from `60s` to `365d`. Reuse does not extend expiry. |
| `project` | no | Project id; only organization API keys need it. |

## Outputs

| Output | Description |
| --- | --- |
| `name` | Branch database name. |
| `id` | Branch database id. Empty after delete. |
| `project-id` | Project id. Empty after delete. |
| `connection-url` | Secret Postgres URL with a database-scoped read/write key. Expires within seven days or with the branch. Empty after delete. |
| `api-url` | `https://api.terrascale.tech/v1/projects/<project>/databases/<name>`. Empty after delete. |

The action masks both the scoped key and connection URL before publishing outputs. Keep
`connection-url` in step environments and never print it. Each create/reuse/reset issues
a fresh key; it grants no access to the source. Expired previews must be deleted and recreated.

Use the outputs with any TerraScale SDK, for example as
`TERRASCALE_PROJECT_ID` and the database name of a preview deploy.

## Identity and cleanup contract

Only `pull_request` events are accepted. The action checks the event's base repository
ID and PR number against GitHub's runner identity. The name hashes project/source ULIDs,
repository ID, PR number and label; it never adopts an unnamespaced label. Existing previews must
have a different canonical ULID from the source, the same project, and `branchedFrom`
equal to the currently resolved source ULID. A changed source or mismatched target
observed during preflight fails before deletion. Old `pr-<number>` databases are
never adopted.

Concurrent creation can fail with a name conflict; retry after checking the workflow.
Reuse rechecks identity and lineage. Cleanup sends `-expected-id` and requires the
server's dedicated conditional-delete route; an unsupported route, changed ID or
permission failure fails the step without an unconditional-delete fallback. A name
precheck alone would not protect against concurrent replacement. Serialize workflows
per repository/PR so a close event cannot overlap a new create or reset event. Without that
serialization a later create or reset can survive an earlier close inventory; the
API does not provide a durable closed-PR fence (residual TS-1318).

## Reset creates a generation

`command: reset` copies the source into `g-<namespace hash>-r<run ID>-a<attempt>`.
It confirms the new database ULID, project and source lineage before publishing
outputs. Use `name`, `id` and `api-url` in later steps. Repeating the same run/attempt
reuses its verified generation; a new run or attempt creates another. `create`
continues to select the base `pr-<number>-<hash>` preview, never the latest generation.

Reset never deletes or renames an old database. Its data, ULID, scoped credentials
and descendants remain bound to that old identity. The new generation has a new
name and ULID; old database-scoped credentials do not transfer. This is neither an
atomic swap nor an in-place reset. Prior generations consume quota until cleanup.

Delete preflights the exact base name and every observed name matching the strict
generation grammar above, with positive decimal run/attempt values of up to 20 digits
each and at most 63 characters total. It never sweeps arbitrary prefixes or deletes
descendants outside that namespace. All candidates must pass inventory, project,
source-lineage and current-identity checks before any guarded deletion. Names from
replaced sources, other projects, repositories or labels are outside this namespace;
they require separate reviewed cleanup. A later conditional-delete failure can
leave partial cleanup; inspect and retry.

If copying fails, quota is exhausted, access is revoked, confirmation fails, output
writing fails or the run is cancelled, reset leaves all previous databases intact.
Their use remains subject to existing access. A completed or uncertain copy may
remain without outputs; inspect its deterministic name and retry the same run/attempt
or close cleanup. There is no rollback deletion of an unconfirmed copy. Offline
fixtures prove the action preserves old records and sends guarded commands; live
credential, data-copy and descendant behavior still requires own-resource verification.

Publication hold: keep the released `v1` tag unchanged. Source builds the CLI from
the full monorepo revision pinned in `action.yml`, with `--json`, guarded branch
commands, TTL and scoped-key issuance. Tagging a new action release remains a
separate go-live step.
Branch creation must use
`POST /v1/projects/{project}/databases/{name}/branches/if-id/{sourceId}` so a replaced
source cannot be copied between lookup and mutation. Cleanup must use
`DELETE /v1/projects/{project}/databases/{name}/if-id/{expectedId}`, returning failure
on older servers. Until both are deployed, cleanup fails safely. Offline fixtures:
`nice -n 19 python3 -m unittest discover -s tests -v`.

## License

Apache-2.0
