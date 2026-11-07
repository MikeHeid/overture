# Proposal: the author in control

**The ask.** Take Overture from a sampler (a check that blocks a pull request
breaking a ruling) to a product: the pipeline that stops at the few moments
where the author's answer changes what gets built, asks the right question
there, batched, never twice, and carries the answer into every later step.
The author decides; the agents build; nothing is lost between them.

Status: proposed 2026-11-06 and reviewed by a three-seat panel the same
day. Open decisions AC1–AC8 below, each with a ★ default that already
carries the panel's corrections; the owner picks or vetoes. The first draft's
"Sequence" and "What makes it one product" are kept as written so the
panel's changes can be read against them; "Sequence, revised" is current.

## Where it stands today

Most of the pieces exist. They are run by hand, one at a time, and nothing
joins them into one path.

| # | Moment | The question the author answers | Today |
|---|---|---|---|
| 0 | A project starts | "What is this, who is it for, what must never happen?" The core idea and the non-negotiables | `grill-me` and `deliberate` skills; nothing makes this the first step |
| 1 | A lane starts | "Here is the plan for this lane. Still the course?" | Waypoints (1.57, WP1–WP3) |
| 2 | Design | The 3–5 decisions this lane rests on, each with options and a ★ default | `deliberate`, `drill`, `roar`, the console committee (`console-fork`); each run by hand |
| 3 | Before every edit | Nothing. The agent reads the rulings that cover this code and follows them | Ruling lookup and edit hooks (1.52, 1.56) |
| 4 | A fork mid-build | "No ruling covers this and it is costly to undo. A or B?" | Agents ask in the console; nothing decides which questions deserve the author |
| 5 | The pull request | "This change touches a ruling; here it is." Blocked if it breaks one | The Action and the PR comment (1.36, 1.61) |
| 6 | After merge | "This ruling's reason no longer holds. Withdraw or keep?" | Staleness, withdraw/keep, lessons (1.33) |
| 7 | The next lane | Nothing. What was ruled and learned is in the next agent's brief | Not built: the lane brief (E5) |

## What makes it one product

- **One pipeline, on by default.** A default playbook (playbooks and
  triggers, 1.59) walks a lane through stages 1–7 and does not let an agent
  pass a stage whose checkpoint is unanswered. The author gets a setting,
  not a process to remember.
- **The brief (stage 7, E5).** Before an agent starts, the console assembles
  a short brief: the core idea (stage 0), the lane's waypoint, the rulings
  for the code it will touch, lessons, area notes. The agent starts knowing
  the decisions, so it asks less.
- **The question filter (the ask ledger, E4, 1.66).** A question an agent
  wants to ask passes three tests before it reaches the author:
  1. A ruling covers it: not asked; the ruling is cited.
  2. Cheap to reverse: the agent takes the ★ default and records it for
     the author's veto later.
  3. Costly, or the agents disagree: asked.
  The ledger counts questions asked, re-asks refused and defaults taken.
  Those counts are the proof the product works.
- **Batching.** Questions collect until a checkpoint (stages 1, 2, 5) and
  reach the author as one short menu with a ★ on each, not as pings.
- **One screen.** "Waiting on you": open questions, waypoints to confirm,
  stale rulings. What is not there is not the author's job.

## Sequence

Each step is one release the size of 1.64.

1. **1.65** CI and `release.py publish` (E2). Keeps everything after it
   from breaking.
2. **1.66** The ask ledger and `lane check` (E4). The filter starts here.
3. **The brief** (E5).
4. **The default pipeline:** one playbook binding stages 1–7, with batching.
5. **Stage 0:** the core-idea round as a new project's first run.
6. **The public door:** a quick start with the Action alone, pointing here.

**How we know it worked.** In one project over one lane: questions that
reach the author, re-asks of settled decisions, and rulings broken at the
pull request all fall, while lanes ship at the same pace. The ledger
measures the first two; the Action's results measure the third.

## Open decisions

The ★ marks the default after the panel's review; where the panel moved it,
the first draft's choice is named as "weighed and not chosen".

| Id | Question | Options (★ = default) |
|---|---|---|
| AC1 | What "cheap to reverse" means, so an agent may take the ★ default instead of asking | **★ b+a. A short list of reversible kinds in `.overture.json` (naming, placeholder copy, test scaffolding), which the author can grow or shrink, plus the veto-after for anything an agent marks reversible beyond the list.** Weighed and not chosen: a alone (the agent decides for itself what is cheap: an honour system); c, everything asked until the author has vetoed fewer than N in a row. |
| AC2 | Where a lane's progress lives | **★ c. Worked out from the store each time**: the lane's waypoint lock and its design-round locks say where it is. No new state. Weighed and not chosen: a, a field on the lane's item (the steward's `items-push` replaces items whole and refuses unknown fields, so the server cannot own one); b, a playbook record (playbooks keep no state). |
| AC3 | When a question reaches the author | **★ c. At once, grouped on screen by lane and in the existing notification digest (N4).** Nothing is held back; single-choice defaults are shown together in one "confirm these" card with one Accept-all, and no question advances by itself. Weighed and not chosen: a, held until the next waypoint (the author's fear is missing something while away, and duplicates would fill the batch); b, hourly. |
| AC4 | What the first run of a new project produces | **★ a′. Two questions, one at a time: "in one sentence, what is this for?" then "what must never happen?"; each answer is locked as a ruling on the project's root item.** Weighed and not chosen: a, a core-idea text on the root item (an item field, see AC2); b, a document in the repository; c, nothing kept. |
| AC5 | Whether an agent may pass a waypoint the author has not answered | **★ a. Never, enforced at the merge**: a waypoint is an exported locked ruling, and `lane check` in CI fails a pull request whose lane has none. While the lane runs, the console shows "waiting on your answer before it can ship". Hooks inform and fail open, so an edit-time block is not promised. Weighed and not chosen: b, after N hours with the defaults; c, the project chooses. |
| AC6 | Whether rulings can be written without the console (the Action-alone door) | **★ a′. Later, with a new marked file shape whose authority is the merge, not the lock fields**: `agent.py rule add` writes it, the author commits it, the lookup reads both shapes. Needs a PROTOCOL.md §13 change and a vector. Weighed and not chosen: a as drafted (the ruling file's `answer_id`, `lock_id`, `by`, `locked_by` come from store records; a file without a lock forges them, and an agent can run the command too); b, an issue template; c, never. |
| AC7 | What the lane summary (the brief) may not contain | **★ a′. Anything agent-written that the author has not confirmed**: open asks, proposals, the agent-written asks file. Lessons (locked) and area notes (checked by `notes check`) stay in. Weighed and not chosen: b, a cap only; c, no limit. |
| AC8 | Whether `covers` (a question naming the ruling it would repeat) is in the protocol | **★ a. In PROTOCOL.md**, so an agent of any vendor can be refused a re-ask. Weighed and not chosen: b, console-only (the public door narrows). |

## What the panel found

Three seats (advisor, architect, UX) read the draft on 2026-11-06 and then
each other; the ★ above are the result. What changed, and why:

- **No new item fields.** `items-push` replaces items whole and refuses a
  field it does not know, so neither a lane's stage (AC2) nor a core-idea
  text (AC4) can live on an item. The stage is worked out from locks; the
  core idea is a locked ruling.
- **The ask log is its own file.** A store record kind an older kit does not
  know makes it refuse the whole store (that is why `refactor.jsonl` is
  separate), so asks go in STATE/asks.jsonl, written by the server through
  the agent door, with a PROTOCOL.md section, a route and vectors.
- **The filter already half exists.** The 1.52 ruling lookup matches locked
  rulings by file path. `POST /question` can run it on the question's
  anchor paths and cite the rulings it finds, since a ruling on a file does
  not settle every question about that file. It refuses only when `covers`
  names a qid that is locked now. `covers` is needed for questions with no
  code path (scope, product, audience). The same question with no path and
  no `covers` still gets through; only the author's veto catches it.
- **Filter before grouping, and nothing held back.** Holding questions until
  a waypoint would fill the batch with duplicates and feed the author's
  fear of missing something. Each question shows at once, grouped by lane.
- **Only the merge can gate.** Hooks inform and fail open, playbooks are
  one-shot owner fan-outs with no state, and WP3's "the lane waits" is skill
  text. The one hard gate is the Action, which reads what is committed at
  the base. So a waypoint must be an exported locked ruling, and `lane
  check` in CI fails a pull request whose lane has none. "The lane waits"
  holds at merge, with a visible nudge in the console meanwhile.
- **Defaults taken are not locks.** Only the owner locks. The agent posts an
  ordinary question with its ★; the ask log gets a "default taken" line
  naming the qid; keep is the owner locking the ★ in one tap, undo is
  picking another option. The "defaults taken" card is the store's questions
  joined with those lines: source, choice, when, undo.
- **The proof is the rate of replaced and withdrawn answers**, not the count
  of questions. Both can be counted from the store today (`supersedes`
  with a reason; withdrawals). The author never sees a rate: they see each
  ruling's origin and each default's undo.
- **One vocabulary:** ruling, waypoint, lane, dashboard, default. "Ask log"
  (not ledger) where the spec needs a name; "lane summary" (not brief);
  "checkpoint" folds into waypoint. The eight stages are internal; the
  author sees one "Your call" list sorted by age and a resting "N waiting"
  count.
- **The wedge is 1.65 and 1.66 together.** The ask log without the CI lane
  check is a log nobody enforces; the lane check without CI has nowhere to
  run.
- **The Action-alone door is reshaped, not killed** (AC6): authority moves
  from forgeable lock fields to the merge the owner approved.

## Sequence, revised

1. **1.65** CI as a required check, and `release.py publish` (E2).
2. **1.66** The ask log (STATE/asks.jsonl, protocol section, `agent.py asks
   --item`); `covers` and the path-cite on `POST /question`; the stage
   worked out from locks; `lane check` in CI; the "Your call" list and the
   "defaults taken" card; the reversible list in `.overture.json` (AC1).
3. **The lane summary** (E5, AC7).
4. **First run:** the two stage-0 questions (AC4).
5. **The public door:** the merge-authored ruling file shape and `rule add`
   (AC6), the quick start, the Marketplace listing.

Not planned any more: a default playbook as a stage machine (nothing in the
server can hold one; the merge gate and the store do the work).
