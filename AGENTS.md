# branch-action

GitHub action that gives each pull request its own copy of a TerraScale database.

## Layout and checks

- `action.yml` is the action interface; `branch.sh` runs the create, reset and delete commands through `ts`; `tests/test_branch.py` holds the preview identity contract fixtures; `examples/` holds workflow examples.
- Fast tests: `python3 -m unittest discover -s tests -v && shellcheck branch.sh`. CI also runs actionlint over `.github/workflows/*.yml` and `examples/*.yml`.

## Rules

- All API operations go through `ts`; never delete by name without an expected id.
- Keep the existing `v1` tag unchanged. The README's publication hold applies: do not tag or publish until the required CLI and guarded server routes are released and verified.

Workspace rules (hosting, secrets, models, Cloudflare, GitHub and shipping) are in the **Shipping code** section of the TerraScale workspace AGENTS.md.
