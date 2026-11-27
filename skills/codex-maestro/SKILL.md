---
name: codex-maestro
description: Manage a local task queue and dispatch Codex workers in isolated Git worktrees using tmux. Use for task dependencies, worker status, and manual recovery.
---

Use `python3 -B scripts/maestro.py` relative to this skill directory. Read the target
checkout's AGENTS.md during preparation. Record scope and acceptance criteria as
UTF-8 Markdown files and create the task with its GitHub owner/repo. Use
`task --help` for command syntax.

Read `task show TASK-N` before changes and use the observed revision. Mark
prepared tasks ready and use `task ready` to find work whose dependencies are done.

Run `start` to create the detached session. Use
`dispatch TASK-N --checkout PATH --revision N --model MODEL --effort EFFORT`
after confirming the checkout and model settings. Select an explicit local
`--base REF` if origin/HEAD is missing. Dispatch snapshots committed files.

Use `status` and `task show TASK-N` to inspect recovery information. Use
`attach` in an interactive terminal, or resume Codex from the recorded worktree.
If an attempt record is missing after a crash, inspect the claim, tmux windows,
and Git worktrees before deciding whether a worker started. Release the claim
with its token, current revision, and a reason only after execution has stopped.
Move the task through review and record acceptance evidence before marking it done.
