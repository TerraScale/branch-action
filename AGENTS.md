# branch-action

GitHub action that gives each pull request its own copy of a TerraScale database.

## Pull requests

- **Start from latest main.** Base every change on the most recent `main`: before starting, `git fetch origin` and branch from `origin/main`, never from a stale local `main`, another feature branch or an old worktree. Before every push, `git fetch origin && git rebase origin/main` again; right before merging, rebase once more and merge only when CI is green on that exact head.
