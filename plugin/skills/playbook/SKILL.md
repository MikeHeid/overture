---
name: playbook
description: Use when the user asks to run a named playbook (.overture/playbooks/<slug>.json) from this Claude session. A session cannot run one - a playbook's steps are the owner's - so this skill explains that, lists what is available, and points the user to the console's Playbooks tab, where they press Run now themselves.
---

# Playbooks run from the console, not from a session

A playbook is a short JSON file at `.overture/playbooks/<slug>.json`
that lists steps the owner wants fired as one:

- `round` — start a deliberation on an item.
- `visual` — ask the agent to draw a diagram or mock.
- `chat` — a free-text message in the chat thread.

**Every one of those steps is written as the owner.** Since 1.30.1 a
Claude session may not write as the owner (an agent that could author a
playbook file could otherwise forge the owner's rounds and visuals). So
since 1.47 (U7, owner's decision) a session does not run playbooks at
all, and says so instead of silently doing nothing:

- `agent.py playbook <slug>` prints why on stderr, runs nothing, and
  exits 1.
- The agent door's `/playbook` answers 403 with the same sentence,
  before any step runs.

## Flow

1. **Say it plainly.** Tell the user that playbooks run from the
   console's **Playbooks** tab (or the Inbox's **Delegate → Run a
   playbook**), because their steps are the owner's.
2. **Help them find it.** If they named a slug, check that
   `.overture/playbooks/<slug>.json` exists, and say what its steps
   are (count and kinds), so they know what they are about to approve.
   If they did not, list the files under `.overture/playbooks/` with
   each one's `description` (at most 10).
3. **Point at Preview.** The tab's **Preview** shows which steps would
   run now and which would be skipped, with the reason in words (for
   example "skipped: it runs only when API-1 has at least 1 stale
   question (it has 0)").

## What you must never do here

- **Never try another route** to make the steps happen: no
  `agent.py items-push`, no hand-written `message` records, no edits
  to the playbook to make it "agent-runnable". The refusal is the
  security fix working.
- **Never write or edit a playbook file** in session. A playbook is a
  project-code change the owner reviews and commits.

## `when` predicates (for reading a playbook)

A step may carry a `when` (0.20.0) that gates it at run time. The
console evaluates it against the current view and item list; a step
whose `when` is false is skipped with a reason in words, and the rest
still run. The kinds are closed-set:

- `{"kind": "project_has_state", "state": "awaiting_you|unlocked|locked|stale", "min": N}`
- `{"kind": "item_has_state", "item": "<id>", "state": "...", "min": N}`
- `{"kind": "item_exists", "item": "<id>"}`
- `{"kind": "has_section", "name": "<slug>"}`
- `{"kind": "not", "of": {<predicate>}}`

A playbook with a bad `when` is refused when it loads, so a run never
surfaces a schema error.
