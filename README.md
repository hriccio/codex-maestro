# Codex Maestro

Codex Maestro provides a local SQLite task queue and runs interactive Codex
workers in separate Git worktrees and tmux windows.

## Why I created Maestro

I created Maestro because I wanted more control over how Codex tackles a large
project that spans several technologies. I can break the project into smaller
tasks and choose the model and reasoning effort for each one. A straightforward
change can run with a lighter setup, and a difficult problem can get the extra
reasoning it needs.

The workflow also gave me a local queue that keeps task dependencies and
progress across sessions. Each worker gets its own Git worktree and tmux window,
so I can return to a worker or review its changes independently.

## When to use Maestro

Use Maestro when a project breaks into independently reviewable tasks that
benefit from different models, reasoning effort, or isolated worktrees. For
example, a feature might involve designing an API, implementing a client, and
updating the docs. Give the API design a more capable model and higher reasoning
effort, select a model suited to the client stack for implementation, and use
lower effort for a straightforward docs update. Make client implementation
depend on acceptance of the API contract if it needs that contract to proceed.

You choose `--model` and `--effort` when dispatching each task. For a small,
cohesive change in one checkout, use Native Codex by default.

## Requirements

- Linux or macOS
- Python 3.10+ with the standard-library `sqlite3` module
- Git with worktree support
- tmux
- An authenticated Codex CLI

To dispatch a worker, use a local Git checkout whose GitHub `origin` matches
the repository recorded on the task.

## Install

Install Maestro from the GitHub-backed marketplace:

```sh
codex plugin marketplace add hriccio/codex-maestro
codex plugin add codex-maestro@hriccio-tools
```

Start a new Codex session and invoke `$codex-maestro:codex-maestro` using the
plugin-qualified name. To refresh the catalog and install the latest version:

```sh
codex plugin marketplace upgrade hriccio-tools
codex plugin add codex-maestro@hriccio-tools
```

To remove the plugin, run `codex plugin remove codex-maestro@hriccio-tools`.

### Planning guidance

On a Codex client that loads plugin hooks, review and trust Maestro's
`SessionStart` hook in the hook settings, then start a new session. The hook
supplies [the planning rule](planning.md) as session context.

Codex CLI 0.172.0 did not expose the bundled hook in terminal testing. To opt in
manually, copy the contents of [planning.md](planning.md) into your active
user-level `AGENTS.md` (usually `~/.codex/AGENTS.md`, or
`$CODEX_HOME/AGENTS.md` if set). If you already have the rule there, keep one
copy. Start a new session to load the guidance.

### Standalone install

Download `codex-maestro.zip` from the latest GitHub release and extract it into
`~/.agents/skills/`. From a source checkout, copy `skills/codex-maestro` to the
same directory. Then invoke `$codex-maestro` in Codex. You can also use the
launcher directly:

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

## Cross-repository milestones

Use a task in each repository for independently accepted work. Create an
ordinary task titled `Milestone: <outcome>` in the owning repository when those
tasks share a checkpoint. Set its coordinator with `--owner` and record what
evidence will satisfy acceptance. Make it depend on each required member.
Downstream tasks can depend on that milestone when they need its outcome.
A campaign coordination task can depend on its milestones and any remaining
required tasks directly.

For example, if TASK-2 is the milestone and TASK-3 needs its outcome:

```sh
maestro task block TASK-2 --by TASK-1 --revision 1
maestro task block TASK-3 --by TASK-2 --revision 1
maestro task transition TASK-2 ready --revision 2
```

After TASK-1 is done, TASK-2 can appear in `task ready`. Handle it manually.
Verify the outcome and transition it through `in_progress` and `review`, then
to `done` with `--evidence` and the latest revision. This satisfies TASK-3's
milestone dependency.

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

## License

MIT. The launcher and task store are adapted from WastingNoTime code.
See LICENSE for the copyright notice and terms.
