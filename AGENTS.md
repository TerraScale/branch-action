<!-- shared-rules:start -->

## Shared TerraScale rules

### Shipping code

- No PRs, reviews or merge queue. Push to `main`. Ignore outside contributors' PRs unless asked.
- Fetch `origin` first. Branch from fresh `origin/main` in your own worktree or clone, outside shared checkouts. Commit small changes; no AI attribution.
- Before pushing, build or type-check only the project you changed. Don't run test suites locally: GitHub CI runs them on every push to `main`. Rebase and push again if the push races. Never force-push or delete `main`.
- Deploy only green main. If your push makes main red, fix or revert within about 30 minutes. For a red main you did not cause, wait for its owner's fix and rebase.
- Never run anything on or SSH to mariogk-desktop.
- StorageFormat.cs bumps and production resets need the user's approval; otherwise put `Needs format bump` in the commit message.

### Tests

- Keep tests few. Fast covers only the happy path and critical paths. Slow keeps only heavy critical tests; delete everything else.
- A new feature adds at most one happy-path and one critical-failure test. Refactors, renames, docs and config changes add none. Deleting low-value tests is welcome.
- Fast tests run fully parallel. Each single test finishes in under 10 s, each area's Fast suite in under 30 s, and every CI test job in under 5 minutes. Anything slower is a bug.
- Prove flaky fixes with 5 repeats; benchmarks with 3 measured repeats in `benchmark/bench/`. For page changes, report before/after screenshots.

### Decisions

- Decide and continue. Record `DECISION: <choice>. Reason: <why>` in commits.
- Block only for a user-only secret/login, new paid capacity, or deleting serving infrastructure or unrecoverable data.

### Secrets and hard gates

- Runtime secrets: OCI Vault in gru via instance principal. CI secrets: GitHub Actions. Ask the user for dev secrets.
- Never expose secret values in chat, arguments, history, logs, git or commits. Use stdin or a 0600 file. Credential installs are one-command handoffs the user runs.
- Ask first before new paid capacity, security permissions or credentials.
- ts-auth and ts-dashboard store data in TerraBase through ts-dotnet; keep the SDK current with TerraBase's API.
- Outside the monorepo, never download or run TerraBase binaries in tests, CI or helpers; use HTTP fakes or contract fixtures. Live ts-status API monitoring is allowed. Never publish TerraBase binaries.
- Use GitHub and `gh`; no polling loops.

<!-- shared-rules:end -->

# branch-action

GitHub action that gives each pull request its own copy of a TerraScale database.

## Layout and checks

- `action.yml` is the action interface; `branch.sh` runs the create, reset and delete commands through `ts`; `tests/test_branch.py` holds the preview identity contract fixtures; `examples/` holds workflow examples.
- Fast tests: `python3 -m unittest discover -s tests -v && shellcheck branch.sh`. CI also runs actionlint over `.github/workflows/*.yml` and `examples/*.yml`.

## Rules

- All API operations go through `ts`; never delete by name without an expected id.
- Keep the existing `v1` tag unchanged. The README's publication hold applies: do not tag or publish until the required CLI and guarded server routes are released and verified.
