# TerraScale branch action

Give every pull request its own copy of a TerraScale database. The action
branches the database when the pull request opens, hands the branch to later
steps (migrations, tests, preview deploys) and deletes it when the pull
request closes.

It runs the [ts CLI](https://github.com/TerraScale/ts-go) on GitHub-hosted
Linux and macOS runners and acts as a TerraScale API key.

## Usage

1. Create an API key for the project: `ts keys create ci` prints it once.
2. Add it to the repository as the secret `TERRASCALE_API_KEY`.
3. Add `.github/workflows/preview-database.yml`:

```yaml
name: Preview database
on:
  pull_request:
    types: [opened, reopened, synchronize, closed]

concurrency: preview-database-${{ github.event.pull_request.number }}

jobs:
  branch:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v5
      - id: db
        uses: TerraScale/branch-action@v1
        with:
          api-key: ${{ secrets.TERRASCALE_API_KEY }}
          database: app
      - name: Migrate and test against the branch
        if: github.event.action != 'closed'
        env:
          TERRASCALE_API_KEY: ${{ secrets.TERRASCALE_API_KEY }}
          DATABASE: ${{ steps.db.outputs.name }}
        run: |
          ts migrate up "$DATABASE"
          ts migrate diff "$DATABASE"
          ts exec "$DATABASE" 'SELECT name FROM users LIMIT 10'
```

Pull request 42 gets a database named `pr-42-<namespace hash>`, a copy of `app` with its
documents, collections and SQL tables. New pushes keep the branch and its
data. Closing or merging the pull request deletes only the verified preview identity.
Reset is temporarily refused until the generation refresh contract is installed.

After the job, `ts migrate up app` on the main branch applies the same
migrations to `app`.

## Inputs

| Input | Required | Description |
| --- | --- | --- |
| `api-key` | yes | API key with `databases:read` and `databases:write`. `ts keys create` keys have both. |
| `database` | yes | Database to branch. |
| `branch` | no | Namespace label, default `preview`. Must match `^[a-z][a-z0-9_-]{0,62}$`. Even explicit labels receive the repository/PR namespace. |
| `command` | no | `create` keeps a verified branch, `delete` conditionally removes it. Empty deletes when the pull request closed and creates otherwise. `reset` is temporarily refused. |
| `project` | no | Project id; only organization API keys need it. |

## Outputs

| Output | Description |
| --- | --- |
| `name` | Branch database name. |
| `id` | Branch database id. Empty after delete. |
| `project-id` | Project id. Empty after delete. |
| `api-url` | `https://api.terrascale.tech/v1/projects/<project>/databases/<name>`. Empty after delete. |

Use the outputs with any TerraScale SDK, for example as
`TERRASCALE_PROJECT_ID` and the database name of a preview deploy.

## Identity and cleanup contract

Only `pull_request` events are accepted. The action checks the event's base repository
ID and PR number against GitHub's runner identity. The name hashes repository ID,
PR number and label; it never adopts an unnamespaced label. Existing previews must
have a different canonical ULID from the source, the same project, and `branchedFrom`
equal to the currently resolved source ULID. A changed source or mismatched target
fails without deleting anything. Old `pr-<number>` databases are never adopted.

Concurrent creation can fail with a name conflict; retry after checking the workflow.
Reuse rechecks identity and lineage. Cleanup sends `-expected-id` and requires the
server's dedicated conditional-delete route; an unsupported route, changed ID or
permission failure fails the step without an unconditional-delete fallback. A name
precheck alone would not protect against concurrent replacement. Serialize workflows
per repository/PR so a close event cannot overlap a new create event.

Publication prerequisite: replace the current CLI 0.0.4 install pin with the released
CLI providing stable `--json` and `-expected-id`. The latter must use
`DELETE /v1/projects/{project}/databases/{name}/if-id/{expectedId}`, returning failure
on older servers. Until both are deployed, cleanup fails safely. Offline fixtures:
`nice -n 19 python3 -m unittest discover -s tests -v`.

## License

Apache-2.0
