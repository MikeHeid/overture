<!-- area: plugin/skills · checked: 69228a3 -->
- One folder per skill, one SKILL.md whose front matter starts `name: <folder>`; roar, refine, drill, deliberate and waypoint ship because the console's rounds lean on them (test_build `SHIPPED_SKILLS`).
- `waypoint` runs before the first change of every new lane (owner, OPEN-DECISIONS WP1–WP3). It only posts and asks until the lock; then its one file, the docs/proposals/WAYPOINTS.md entry, is written in the lane's own worktree and committed with the lane's first commit.
- The owner is never handed a blank question: lettered options, a one-line tradeoff each, and a ★ default (deliberate, drill, refine). "Defaults" takes every ★ and records each as an architect default, not an owner decision.
- Skills that change files start in the agent's own worktree, `agent.py worktree new --kind KIND --item ITEM` (1.50 W2); the deliberation skills change no files and make none (test_kit `WritingSkillWorktreeTests`).
- A fork is done when its `Result:` reply exists; console-fork and console-process state that one rule in the same words, so a change goes into both.
- Every `KIT/<path>` a skill names must exist in the installed kit; test_build installs the plugin by both routes and checks.
- `as` is user-only (`disable-model-invocation: true`): naming a session is the user's act, recorded by the name_session hook.
