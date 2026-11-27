---
name: codex-maestro
description: Manage a local task queue and dispatch Codex workers in isolated Git worktrees using tmux. Use for task dependencies, cross-repository milestones, worker status, and manual recovery.
---

Use `python3 -B scripts/maestro.py` relative to this skill directory. Read the target
checkout's AGENTS.md during preparation. Record scope and acceptance criteria as
UTF-8 Markdown files and create the task with its GitHub owner/repo. Use
`task --help` for command syntax.

Read `task show TASK-N` before changes and use the observed revision. Mark
prepared tasks ready and use `task ready` to find work whose dependencies are done.

For a shared outcome, create one task per independently accepted repository scope.
When a group needs a distinct acceptance decision, create an ordinary task titled
`Milestone: <outcome>` in its owning repository. Assign a coordinator and define
verifiable acceptance. Use `task block MILESTONE --by MEMBER --revision N` for
each required member. Add dependencies on the milestone only for downstream
tasks that need its outcome. A campaign coordination task can depend on its
milestones and any required work outside them.

Milestones can appear in `task ready`. Check task purpose before dispatch and
handle milestones manually. Once the members are done, verify the shared
outcome and transition the milestone through `in_progress` and `review`, then
to `done` with `--evidence`. Use the latest revision at every step.

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
