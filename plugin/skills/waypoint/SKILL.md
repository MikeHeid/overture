---
name: waypoint
description: Stop at the start of every new lane, phase, wave or major section of work and check with the owner that the project is still on course - post an announcement and recap to the console inbox with the roll-up, the direction map and the execution path, put one lockable on-course question, and open a grill and a breakout before any of the new work is built. Use when the user types /overture:waypoint, and on your own before the first change of a new lane, phase or wave in a project registered for the owner console.
---

# Waypoint: check the course before a new lane starts

A plan was agreed at some point, and work has moved since. **Before the
first change of a new lane, phase, wave or major section, stop and show the
owner where the project actually is**, where it is about to go and how, and
let them push on it. Nothing in the new lane is built until the owner has
answered the on-course question (owner directive, OPEN-DECISIONS "Waypoints"
WP1-WP3).

A waypoint informs and asks; it never decides. It changes no files except the
one waypoint record (step 5), and makes no worktree.

## When to run

- **The start of anything new:** a lane (a branch of work with its own
  claim), a phase, a wave, a release line, or a section the project's plan
  names. Run it before that lane's first commit, and before you ask the
  lane's own design questions: the owner should agree on the direction
  before choosing its details.
- The user typed `/overture:waypoint` (optionally with the lane's name).
- **Not** for a fix inside a lane already under way, a review round, or a
  release of work already agreed. If you are unsure whether something is a
  new lane, it is: say so in one line and run it.

## 0. Set up

As in the console-process skill: `KIT`, `STATE` and `A` come from **the
user's own registry**, never from the repository, and a session that is not
the steward signs its posts (`A` with `--as NAME`). Stop here if this project
is not registered: then give the same announcement in the conversation and
ask the on-course question there (AskUserQuestion, the same options), and say
that it was not posted because the project has no console.

## 1. Gather, read-only

Read what the record says, not what you remember. Every fact you post names
where it came from (a file and its lines, a PR number, a commit).

- **Roll-up: what happened since the last waypoint.** The newest entry in
  the project's waypoint log (step 5) is where to start; with none, the last
  three releases. Collect: releases and their CHANGELOG headings, merged PRs
  (`gh pr list --state merged --limit 20`), owner decisions recorded since
  (the decision log the project names: OPEN-DECISIONS.md here), and every
  known limit, open follow-up or deferred item those name.
- **Direction map: where the plan said we would go, and where we are.** The
  project's plan (STRATEGY.md's waves here, or the spec the project names).
  For each stage: done, in progress, next, or dropped. Then **drift**: what
  was decided differently from the plan, what the plan did not foresee, and
  what a recent finding makes less true (a real run, a review, a measurement).
- **Execution path: what is about to proceed.** The new lane in order: its
  goal in one sentence, what it will touch, the decisions it needs and when,
  and its gates (tests, red checks, a real run, an independent clearer, the
  owner's approve, the release). Name what it postpones.

## 2. Find the questions the course depends on

Two kinds, both from step 1:

- **The on-course question, always.** "Proceed with <lane> as mapped?"
  Options, each with what it costs:
  `a` Proceed as mapped (★ unless step 1 found drift that changes the lane),
  `b` Proceed, with the adjustment you name (only when drift suggests one),
  `c` Re-plan first: a deliberation round on the direction before any build,
  `d` Pause this lane: say what it would wait for.
  Put the ★ where the evidence points, with `star_by: "architect"`, and say
  why in the question text. Anchor it with an excerpt of the plan's lines
  that describe this lane, so the answer goes stale if the plan is edited.
- **Drift questions, only when step 1 found drift that is the owner's to
  settle.** One lockable question each, laid out as the deliberate skill lays
  a decision out (two to four options, costs, a ★). At most three: more than
  three means the lane is not ready, which is option `c`.

## 3. Post it to the inbox

1. **The announcement**, one reply on the lane's item (`A reply ITEM TEXT`;
   the item the lane's questions will belong to, or the plan's own item). Use
   this shape and keep it under 60 lines; link to files rather than pasting
   them:

   ```
   WAYPOINT: entering <lane / phase / wave>  (<date>)

   Recap: <two or three sentences: where we are, in plain words>

   Roll-up since <last waypoint or release>
   - <release or PR>: <what it did>  (<source>)
   - Decided: <id> <decision>  (<source>)
   - Still open: <limit or follow-up>  (<source>)

   Direction map
   - <stage>: done | in progress | next | dropped
   - Drift: <what changed from the plan, and why>  (<source>)

   Execution path for <lane>
   1. <step>  (gate: <what must pass>)
   2. ...
   Postpones: <what waits because of this>

   Your call: <qid> on-course question. Before you answer, push on it:
   💬 Chat ▾ → Grill on <ITEM> stresses the lane (user, failure, scale,
   opportunity cost, evidence); Branch out opens any part of it. Ask for a
   deliberation round and one runs before anything is built.
   ```

2. **The questions**, through the console-ask skill: the on-course question
   first, then any drift questions, on the same item.
3. **Offer the grill.** If the owner asks for one (a `grill` message on the
   item, or "grill" in chat), run the grill-me skill on the lane as pitched
   in the announcement; its questions land on the same item.

## 4. Wait, then go where the answer points

The lane's first change waits for the on-course question to be locked (the
console-process skill folds it). Meanwhile, finish work already under way in
other lanes; do not start this one.

- `a`: start the lane as mapped.
- `b`: amend the execution path as the owner said, reply with the amended
  path on the item, then start.
- `c`: run the deliberate skill (or a roar panel, if the owner asked for one)
  on the direction; the lane starts only after its questions are locked.
- `d`: record what the lane waits for, and stand down its claim.

If the owner answers in the conversation instead, post that answer to the
console as console-ask's steward rule says, so the decision is on the record
either way.

## 5. Record it

Append one entry to the project's waypoint log (`docs/proposals/WAYPOINTS.md`
here; another project keeps it beside its decision log) and commit it with
the lane's first commit: the date, the lane, the qid, the owner's answer, and
a one-line roll-up. The next waypoint's roll-up starts from it.

## What NOT to do

- Do not run a waypoint as a formality after the work has started: its whole
  point is to come first.
- Do not answer, star-and-proceed or lock the on-course question yourself.
  "Defaults" from the owner takes the ★ and records it as an architect
  default, as the deliberation skills do.
- Do not post a roll-up from memory: every line cites its source.
- Do not bury the ask: the on-course question is named in the announcement's
  last lines, where the owner reads it.
