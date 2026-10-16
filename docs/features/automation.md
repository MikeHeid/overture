# Automation: Delegate, playbooks and triggers

[← Back to README](../../README.md)

Start agent work from anywhere, codify it as a playbook, and let a webhook or the clock fire it.

Everything on this page ends in the same place: owner requests on the
console (a round, a visual, a chat message), which the steward's `watch`
picks up like any request you make by hand. No new kind of agent work is
involved, and nothing here runs code on the console's machine.

## Delegate (0.10)

The **⚑ Delegate** bar sits above the tabs, so you can start work
without opening an item first. Pick what to do:

- **Deliberate (full round)** on an item, with a mode (explore or
  tighten) and a focus;
- **Request a visual** on an item (the brief is required);
- **Chat with the agent** (goes to the Chat thread);
- **Run a playbook**, with **Preview** beside **Run playbook**.

Press `.` to jump to the bar. On an item, **💬 Chat ▾ → Delegate** opens
it with that item already picked. A skipped playbook step is named under
the button, with its reason in words (1.47), such as "it runs only when
the project has at least 1 awaiting you question".

<img src="../screenshots/feature-delegate.png" alt="The Delegate bar open on Run a playbook: the playbook picker, Run playbook and Preview" width="400">

## Playbooks (0.11, 0.20, 1.3)

A playbook is a JSON file, `.overture/playbooks/<name>.json`, in your
project. Its file name is its name: 1 to 64 characters of lowercase
letters, digits, `_` and `-`, starting with a letter or a digit (so never
with `_` or `-`).

    {
      "description": "Before a release: a heads-up while questions wait, a retry diagram, a round once clear.",
      "steps": [
        {"kind": "chat", "text": "Release window opens Monday 09:00. Anything blocking?",
         "when": {"kind": "project_has_state", "state": "awaiting_you", "min": 1}},
        {"kind": "visual", "item": "API-2", "text": "Draw the dead-letter replay path."},
        {"kind": "round", "item": "API-3", "mode": "tighten", "text": "Confirm the v2 cut-over gates.",
         "when": {"kind": "not", "of": {"kind": "project_has_state", "state": "awaiting_you", "min": 1}}}
      ]
    }

- **Steps** (1 to 24) run in order. `round` takes an `item`, a `mode`
  (`explore`, the default, or `tighten`) and an optional `focus`;
  `visual` takes an `item` and a brief in `text`; `chat` goes to the Chat
  thread. A step on an item that is not in your item list is skipped,
  named, and the others still run.
- **`when`** (0.20) makes a step conditional, from a closed set:
  `project_has_state` and `item_has_state` (at least `min` questions in
  `awaiting_you`, `unlocked`, `locked` or `stale`), `item_exists`,
  `has_section` (a section configured in `.overture.json`), and `not`
  around another (nested at most three deep). There is no expression
  language, so a bad condition fails when the file is read, not when it
  fires.
- **Limits.** A file is at most 32 KiB and a description 400
  characters; at most 128 playbooks are read. A malformed file is
  skipped, so one bad playbook never hides the rest.

The **Playbooks** tab (`g y`, under More) lists each playbook with its
description and step count, **Preview** and **Run now**. The command
palette lists them too; Enter runs one.

<img src="../screenshots/feature-playbooks.png" alt="The Playbooks tab: release-triage and weekly-review, each with Preview and Run now" width="400">

**Preview (1.3)** shows, without writing anything, which steps would run
now and why each other one would be skipped, with **Run now** at the
bottom. Since 1.47 each reason is a sentence built from the step's `when`:
"it runs only when the project has fewer than 1 awaiting you question",
"it runs only when item BILL-1 is in the item list", and so on (before, a
`not` read `not(ok)`).

<img src="../screenshots/feature-playbook-preview.png" alt="Preview of release-triage: would run 2 of 3 steps; the round on API-3 would skip on its when condition" width="720">

**Playbooks run from the console, not from a Claude session (1.47).**
Every step (a round, a visual, a chat) is sent as you, and since 1.30.1 a
session may not write as you. So `/overture:playbook <name>`, `agent.py
playbook <name>` and the agent socket's `/playbook` refuse up front,
before any step runs, and say where to go instead:

    not run: release-triage: playbooks run from the console's Playbooks tab, not from a Claude
    session: every step (a round, a visual, a chat) is sent as the owner, and a session may not
    write as the owner. Open the console, choose the Playbooks tab, and press the playbook's Run
    now button.

`agent.py playbook` exits 1. Through 1.46 a session's playbook ran each
step into a refusal and came back with every step skipped.

## Triggers (0.12, 0.15, 0.16, 0.27)

A trigger fires a playbook without you. Triggers live in
`.overture/triggers.json`, read when the server starts (a malformed one
stops the start, named):

    {"triggers": {
      "pr-merged":     {"playbook": "release-triage", "token_sha256": "<sha256 of the token, hex>"},
      "monday-review": {"playbook": "weekly-review",  "cron": "0 9 * * MON"}
    }}

A trigger has a webhook, a schedule, or both.

### Webhook triggers

`agent.py trigger-token` prints a new token and its SHA-256. Put the hash
in `triggers.json` and give the token to the sender, which calls
`POST /api/trigger/<name>` with `Authorization: Bearer <token>` (or
`X-Console-Trigger-Token`). The server keeps only the hash and compares
in constant time. Behind Cloudflare the call first passes Access with a
service token. A trigger fires at most once every 10 seconds; a webhook
call to a schedule-only trigger is refused. GitHub signs its webhooks
with HMAC rather than a bearer token, so it needs a small bridge.

**Sign-in links (1.46).** A console that runs with `--auth link` lets in
only signed-in browsers, so it refuses every external trigger call: a
webhook has no device cookie. Keep webhook triggers on a console behind
Cloudflare. Schedules and Replay still work.

### Scheduled triggers

`cron` is five fields, minute hour day-of-month month day-of-week, with
`*`, `*/n`, ranges, lists and `a-b/n`; `JAN`–`DEC`, `SUN`–`SAT`, and 7 for
Sunday. The server checks each minute and fires each matching trigger
once in that minute, even if the clock jumps back.

### The trigger log and Replay

The **Triggers** tab (`g t`, under More) lists each trigger with its
playbook and kinds, and the most recent firings: when, which trigger,
webhook, cron or replay, how many steps ran and were skipped, and any
error. While triggers exist, a **Triggers** fold on the Inbox tab shows
the same, with **⌕** to preview a trigger's playbook (1.47: only on the
Inbox; the Triggers tab holds the full list, and on the other tabs it was
noise). **↻ Replay** fires a
trigger now; it skips the token and the rate limit, because you are
already signed in, and is logged as `replay`. The server keeps the last
100 firings in memory, so a restart clears the log.

<img src="../screenshots/feature-triggers.png" alt="The Triggers tab: pr-merged (webhook) and monday-review (cron), each with Replay, and the recent firings" width="400">

## Impact graph (0.14, 0.17)

Each item with questions has an **Impact graph** fold beside its Status
flowchart: the item and its parents, its questions and rounds, the
dashboard sections it maps to, and the files its questions cite. Click a
node to highlight everything downstream; a question or item node opens
that card. Drag nodes and zoom with the wheel. Chips above it narrow the
graph by kind (item, question, round, section, file) and by state. It is
drawn in the same sandboxed frame as the charts, from at most 120 nodes.

<img src="../screenshots/feature-impact-graph.png" alt="The impact graph for API-2: Wave 2, the item, its two questions and a cited file, with kind and state chips" width="400">
