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

Pull request 42 gets the database `pr-42`, a copy of `app` with its
documents, collections and SQL tables. New pushes keep the branch and its
data; set `command: reset` to branch `app` again on every push. Closing or
merging the pull request deletes `pr-42`.

After the job, `ts migrate up app` on the main branch applies the same
migrations to `app`.

## Inputs

| Input | Required | Description |
| --- | --- | --- |
| `api-key` | yes | API key with `databases:read` and `databases:write`. `ts keys create` keys have both. |
| `database` | yes | Database to branch. |
| `branch` | no | Branch name, by default `pr-<number>`. Must match `^[a-z][a-z0-9_-]{0,62}$`. |
| `command` | no | `create` keeps an existing branch, `reset` branches again, `delete` removes it. Empty deletes when the pull request closed and creates otherwise. |
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

## License

Apache-2.0
