## Implementation planning

When proposing an implementation plan, recommend **Native Codex** or **Maestro**
and explain why in one sentence. Prefer Native Codex. Recommend Maestro when
independently reviewable work, isolated worktrees, explicit dependencies, or
persistent execution state materially improve delivery.

If recommending Maestro, include a self-contained handoff with the target
checkout paths, intended base refs, key decisions, and acceptance criteria.
Leave native delegation to execution time. Use the `$codex-maestro` skill for
execution only after the user approves the strategy and manually hand off the plan.
