# Codex Maestro

Codex Maestro provides a local SQLite task queue and runs interactive Codex
workers in separate Git worktrees and tmux windows.

## Install

On Linux or macOS, install Python 3.10+, Git, tmux, and an authenticated Codex CLI.
Copy the complete `skills/codex-maestro` folder into `~/.agents/skills/`, then
invoke `$codex-maestro` in Codex. You can also use the launcher directly:

```sh
maestro() { python3 -B ~/.agents/skills/codex-maestro/scripts/maestro.py "$@"; }
maestro task create --repository example/project --title "Implement feature" --body-file scope.md --acceptance-file acceptance.md
maestro task transition TASK-1 ready --revision 1
maestro task ready
maestro start
maestro dispatch TASK-1 --checkout ~/src/project --revision 2 --model YOUR_MODEL --effort medium
maestro status
maestro attach
```

Use `task block TASK-2 --by TASK-1 --revision N` to add a dependency. Each task
uses its own latest revision. Dispatch verifies GitHub origin and uses the local
origin/HEAD unless you pass `--base REF`. No fetch is needed to launch.

## Recovery

The queue, snapshots and worktrees are stored under
`~/.local/share/codex-maestro/`. Use `task show` and `status` to locate the
attempt. Resume manually in the retained tmux window or run `codex resume` from
the retained worktree. If the attempt record is missing, inspect the task claim
and Git worktrees before releasing the claim.

After confirming execution stopped, use
`task release TASK-N --revision N --token TOKEN --reason REASON`. Use each new
revision to transition to `review`, then to `done` with `--evidence`.
The launcher allows one dispatch per task. A worker exit does not complete it.

Use `task backup FILE` for a SQLite backup and `task restore FILE` with workers
stopped and the destination database absent. Backups preserve claims and recovery
paths, so check them when restoring elsewhere.

## Release status

Local staging only. The launcher and task store are adapted from WastingNoTime
code, copyright (c) 2026 wastingnotime.org. Written permission to distribute
that code under MIT is pending.
