# Owner decisions: one deliberation

Every question still waiting on the owner, in one place. They come from:

- [SERVER-HOSTING.md](SERVER-HOSTING.md): how the server runs;
- [UX-VIEW.md](UX-VIEW.md): the UX View modal;
- the icons and lane-colors plan, which was only in a chat until now;
- the steward-role question raised with the **Master agent name** setting;
- what to build next.

Each decision had lettered options and a ★ recommendation. A ★ the owner
deferred to is recorded as an *architect default*, not as the owner's
decision, so a later review can audit it.

Status: **decided on 2026-10-11.** D13, D14, S1, S2 and F1–F3 were answered "defaults" the same day, so each is an *architect default*. The owner's answers and
amendments are below. The option tables after them are kept as the record of
what was weighed.

| # | Decision | Outcome |
|---|---|---|
| D1 | How the server runs | **A, amended.** One command runs the server in the foreground, detaches it as a daemon, installs or removes it as a service, and reports status and health (see "D1 as decided"). Same command shape as `lean-ctx`. |
| D2 | When macOS gets a service installer | **B.** Right after Linux/WSL, as its own PR. *Shipped in 1.51* (see "D2 as decided"). |
| D3 | One main server for new installs? | **A.** `--all` by default. |
| D4 | What a saved UX component is | **A, amended.** One self-contained HTML document, scripts off by default. A switch turns scripts on for one component (see "D4 as decided"). |
| D5 | Where components are saved | **A.** `components/<item>.md`, with backups in `components/.history/`. |
| D6 | Which items get UX View | **B.** Default lanes, configurable. |
| D7 | How a saved component reaches the repository | **A, amended.** Through the steward and a PR, and the PR can be merged from the console's PR tab (see "D7 as decided"). |
| D8 | Where the icons come from | **A.** A Lucide subset, bundled. |
| D9 | How tabs show icons | **B, amended.** Always icon plus label. The inbox column is always wide enough to show the menus without wrapping. |
| D10 | How lanes get colors | **A.** Automatic, with a named override. *Shipped in 1.32*: when two lane names hash to the same colour, the later one in name order takes the next free colour, so lanes collide only past 8. |
| D11 | A per-machine steward role setting? | **A**, built in 1.33 at the owner's request ("Steward role setting"). It had been **B**, an architect default the owner deferred to. |
| D12 | What to build next | **A.** Icons and status indicators, then lane colors. |
| D13 | How a UX item is tied to a Claude Design project | **A**, *architect default* (2026-10-11): the steward writes the link into front matter; agents read the design; the server never fetches it. The accepted shape is pinned from the owner's real link: `https://claude.ai/design/p/<uuid>` (a `?via=share` suffix is cleaned off when pasted). |
| D14 | Playbooks and Triggers behind More ▾ (made in #131 to keep D9's no-wrap rule at ~515px) | **A**, *architect default*: five tabs in the bar, four under More; `g` shortcuts reach all. |
| S1 | Form controls in UX components (UX-VIEW.md) | **A**, *architect default*: allow `button`, `input`, `select`, `label`, `textarea` as inert tags. |
| S2 | When a component's scripts start (UX-VIEW.md) | **A**, *architect default*: at once, with "recorded at next save" shown. |
| F1 | Asset space full (FEED-ASSETS.md) | **A**, *architect default*: prune the oldest unstarred assets not linked to a PR, noted in the Feed. |
| F2 | The owner attaching images (FEED-ASSETS.md) | **A**, *architect default*: later, in its own PR. |
| F3 | When agents post screenshots (FEED-ASSETS.md) | **A**, *architect default*: a before and an after on every UX-item change and UI fix. |

### D1 as decided

One entry point with five modes, modelled on `lean-ctx`:

    <py> <kit>/server.py --all                     # foreground; Ctrl+C stops it
    <py> <kit>/server.py daemon start|stop         # detached, with a pid file and a log file
    <py> <kit>/server.py service install|uninstall # systemd user unit (Linux, WSL); launchd (macOS, 1.51)
    <py> <kit>/server.py status                    # running? which mode? pid, port per project, last restart
    <py> <kit>/server.py health                    # per project: store lock, tunnel reachable, version skew, linger

- `daemon start` refuses when a service is already installed and running,
  and the reverse. Both name the other mode.
- `status` and `health` read the pid file, the unit state and the agent
  socket. They never start anything.
- Following `lean-ctx doctor`, `health` warns when linger is off, reports
  the restart count, and cleans up a stale pid or socket file left by a dead
  process.
- The SessionStart hook still only reads: when the server is down, it
  prints the one-line `status` hint.

### D2 as decided (architect defaults, 1.51)

The owner chose B and said "Go" on 2026-10-19; these are the lead's
architect defaults for it.

- **A1** Label `overture.console`, file `~/Library/LaunchAgents/overture.console.plist`,
  a per-user LaunchAgent in the `gui/<uid>` domain.
- **A2** Written with `plistlib`, never a text template. `ProgramArguments`
  is an argv array, so a space in a path is fine; a path that is not
  absolute or holds a control character is refused by name. The systemd
  plain-path rule stays systemd's.
- **A3** `RunAtLoad`, `KeepAlive = {SuccessfulExit: false}` (as
  `Restart=on-failure`), `ThrottleInterval` 10 (launchd has no start limit,
  so a failing server is retried every 10 s), stdout and stderr to the
  daemon's log (rotated at install), `WorkingDirectory` the kit, no
  `ProcessType` (Background is throttled), no environment.
- **A4** One `_launchctl` helper. `--start`: boot out a loaded job first (an
  upgrade), then `enable`, then `bootstrap`. Without `--start`, only the
  plist is written. Uninstall boots out and removes. The order is bootout
  (if loaded) → enable → bootstrap, never bootstrap first: a job that was
  once disabled (`launchctl disable`) cannot be bootstrapped until it is
  enabled again.
- **A5** `launchctl print`, matched by line name: not found → `inactive`;
  `running` → `active` with its pid; `spawn scheduled` → `activating`; not
  running → `failed` on a non-zero last exit code, else `inactive`; anything
  else → `unavailable`. No start time.
- **A6** Every hint names this platform's command (`launchctl kickstart -k`,
  `bootout`, `print`) through one helper.
- **A7** No linger on macOS; a LaunchAgent runs while you are logged in.
- **A8** Docker stays optional; native Windows stays unsupported.
- **A9** `deploy/install.sh` and onboarding's per-project units stay
  systemd; `install.sh` refuses on macOS by name. A tunnel on a Mac uses
  `cloudflared service install`.

### D4 as decided

- Components render with scripts **off** by default.
- A **Scripts** switch in the UX View modal turns them on for that component
  only.
- The switch is an owner act: it is sent as a message, so it is in the audit
  trail. The steward records it in the component's front matter as
  `scripts: true`.
- With scripts on, the frame changes from `sandbox=""` to
  `sandbox="allow-scripts"`, never with `allow-same-origin`, so it runs in an
  opaque origin. That is the same arrangement as today's Mermaid frame.
- Its CSP sets `connect-src 'none'` and allows no outside script sources, so
  a component's script can't reach the network, the console or its cookies.

### D7 as decided

- Saving still goes through the steward and a PR.
- The PR tab gets a **Merge** button on a PR whose checks pass.
- The server runs no git and holds no GitHub token, so the button does not
  merge anything itself. It sends an owner message with `intent: "pr-merge"`
  and the PR number, and the doorbell rings.
- The Claude Code session that runs that repository merges the PR with its
  own GitHub access. That session is the steward, or the session for that
  repository when a primary console watches several.
- The PR row shows "merge requested", then "merged" after the next
  `prs-push`.
- If no session for that repository is running, the request waits in its
  inbox, like any other owner message.

## Wave 3: teams (decided 2026-10-14)

Weighed in one deliberation after roles (1.39) and the People tab (1.40).
All six are the owner's own picks, none an architect default.

| # | Decision | Outcome |
|---|---|---|
| W1 | What to build next | **A.** Routing: each question shows who it is for, and a "Mine" filter. Two-key locks and Slack/email notifications need it to know whom to ask. |
| W2 | How a question finds its people | **A.** From member areas: a question on item X is for every member whose areas cover X; administrators cover all. No new question field. |
| W3 | What members and viewers can read | **C, amended.** They read everything, and their Inbox opens on "Mine". A **director** flag on a login makes "Mine" everything: a director sees all by default. The flag widens what is shown, never what may be decided (that stays the role and its areas). |
| W4 | Drafts with several administrators | **A.** Drafts per login, served only to that login. |
| W5 | A record of role changes | **A.** A log beside `roles.json`: who changed which login's role, to what, when; shown in the People tab. Emails stay in the console. |
| W6 | Two-key locks, when built | **A.** Per area, set in roles: a lock in a two-key area needs a second person (an administrator, or a member of that area) to confirm it. |

Weighed and not chosen: B for W1 (two-key first), D for W1 (Wave 2's
solo mode without Cloudflare), B for W3 (members confined to their areas
on every surface, which one forgotten path would leak), C for W6 (every
member's lock confirmed by an administrator).

## Settings (decided 2026-10-15)

The owner asked that config parameters which are a team's or project's
administrative decision be set in the console by a project's directors.
All four are the owner's own picks ("1a 2a 3a 4 yes").

| # | Decision | Outcome |
|---|---|---|
| S1 | Who sets them | **A.** A Settings tab for administrators and directors, two-key areas included. People (role assignment) stays administrator-only. **Amends W3:** the director flag now also lets a login set project settings; it still grants no decision on questions. |
| S2 | Where the values live | **A.** `STATE/settings.json` on the console's machine: overrides the committed defaults, takes effect at once, logged in the role log. The console never writes to the repo. |
| S3 | The first wave | **A.** Two-key areas, chat limits, agents per item, operator short names, lane labels and colours; notification settings as they are built. Folders, the committee seat and next-step skills stay in `.overture.json` for now. |
| S4 | Order | **Yes.** Settings now (1.44), notifications next. |

## Notifications (decided 2026-10-15)

Weighed after Settings (1.44). The owner took every recommendation ("go").

| # | Decision | Outcome |
|---|---|---|
| N1 | Channel | **A.** A Slack-style incoming webhook (Slack, Mattermost, Discord's `/slack` URL). Email can come later behind the same switch. |
| N2 | Who sets the webhook URL | **B.** The owner, in the terminal (`agent.py notify-url`); it is a credential. Settings turns notifications on or off and sets the timing. |
| N3 | What a message says | **A.** Counts, item ids and a link to the console. Never a question's text, never an email. |
| N4 | When | **B.** A digest: at most one message every N minutes (default 30), plus quiet hours. |
| N5 | Who sends | **A.** The console server, to the configured host only: HTTPS, no redirects, timeouts. |

Weighed and not chosen: SMTP email (N1 B), the URL set from Settings (N2 A),
question text in messages (N3 B), a message per question (N4 A), and the
steward session sending (N5 B).

## Agent worktrees (decided 2026-10-16)

The owner asked whether "auto branching to subagents in their own worktree,
and having that support" would help Overture itself. The review found that
visuals and saved UX components already must be written from the agent's own
worktree and land by PR, but each skill tells the agent to make one by hand,
other writing work has no such rule, and the console records which agents
are active on an item but not where they work. The server runs no project
code and starts no git (CONSOLE-kit/Q24), so worktrees are made and pruned on
the agent side; the server only records and shows the branch. Merging stays
with the owner, through the PR tab.

| # | Question | Decision |
|---|---|---|
| W1 | Where an agent's worktree lives | **A** (owner): `~/.overture/worktrees/<project>/<branch>` in the Linux home. Outside the repository, never on `/mnt/c`, one place to list and prune. |
| W2 | Which console requests get one automatically | **A** (owner): anything that changes files: agent work on tickets, visuals, UX saves, playbook steps that write, rounds that change code. Chat, deliberation and grilling stay where they are. |
| W3 | When a worktree is removed | **A** (owner): when its PR merges or closes, by the steward on its next watch cycle. One with no PR for 14 days is listed in the console as stale, never deleted silently. Unpushed commits always block removal. |
| W4 | Two agents' branches on the same item or files | **A** (owner): warn, never block. The item, its tickets and the PR tab show both branches with an overlap warning, and the second agent is told when it starts. |

Weighed and not chosen: next to the repository, or Claude Code's own
subagent isolation (W1 B, C); every request, or only when asked (W2 B, C);
pruning when the PR opens, or only by hand (W3 B, C); blocking the second
agent, or showing branches with no warning (W4 B, C).

## Memory in its own place: area notes (decided 2026-10-20)

The owner asked whether each lane, wave or phase, and each function, should
keep its context in its own place, to keep agents on track and spend fewer
tokens. A three-seat panel (roar) and the advisory board (analyst, advisor,
devops) answered: **per area of code, yes; per phase, only as a release file
that is deleted when the release ships; per lane or wave, no.** Lanes and
waves close when their work ends, so memory kept by them dies with them; they
are tags. The owner said "do recommended" (every ★).

| # | Question | Decision |
|---|---|---|
| M1 | The four memory tiers | **Yes** (owner ★). (1) Area facts: a short `CLAUDE.md` of 5–10 lines in a declared area folder, written as facts with their "why", never orders; loaded when an agent reads there. (2) Release context: one memory file per open release, deleted on ship. (3) Where an agent stopped: on the console item (working mark, claim, HANDOFF). (4) Decisions: rulings and this file only. A note cites a ruling (`ITEM/Qn`) or a lesson and never copies it. |
| M2 | Build phases 0–2 now | **Yes** (owner ★), as 1.53. Phase 0 (measured): a subagent starts at about 19k–22k input tokens, about 40% of it the always-loaded rules and CLAUDE.md files; a long agent's run reaches about 10M, so cutting exploration matters more than the fixed start. |
| M3 | Show area notes in the console | **Wait** (owner ★) until notes have been used for a while; then its own release, read by other agent tools too. |
| M4 | Slim the owner's global always-loaded rules | **Measure first** (owner ★). Measured: under 2% of a long run, so not worth changing the owner's global setup now. |

Board amendments carried into 1.53: area folders are declared in one list,
and `agent.py notes check` fails on a note outside it, on a stale note (its
folder changed since the commit it was checked at), and on memory-index
links to missing files; the check runs agent-side in the steward loop and in
the release recipe (the server starts no git, Q23); area notes stay out of
the release zip; one before-and-after run of a small task, with and without
a note, compares tokens, wrong claims and missed rulings.

### M1-M4 as built (architect defaults, 1.53)

- **N1** The declared folders are the checked repository's own, in
  `.overture.json` `"areas"`, not a list inside the kit: the steward runs the
  check on every registered project, and a kit-held list would call every
  other project's `CLAUDE.md` undeclared. A project without the key is left
  alone; the CLI refuses it by name.
- **N2** The tests live at the repository root, where a `CLAUDE.md` would be
  always loaded, so the test facts sit in the `plugin/kit` note (loaded
  whenever an agent reads the code the tests cover). A nested declared folder
  (`plugin/kit/overture`) does not make its parent stale.
- **N3** Stale counts committed changes only, from the checked commit; when
  that commit is not in the branch's history (a squash merge), from the
  note's own last commit. A note's checked commit therefore needs a commit of
  its own after the code it describes (`notes check --update AREA`).
- **N4** The counts reach `watch.json` only (M3: no console view yet).
  `verify_vendor.py` ignores `CLAUDE.md` both ways.

## Ruling lookup before an agent edits (decided 2026-10-19)

Wave 2's "ruling lookup before an agent acts" (STRATEGY.md, core engine:
"rulings touching this path"). Until 1.52 nothing answered which locked
rulings touch a file: the CI check (1.36) compares a PR's changed files with
the committed rulings after the fact, and the MCP server (1.35) has no
rulings search. The hooks so far read files only and fail open. The server
still starts no git and runs no project code (CONSOLE-kit/Q23, Q24).

| # | Question | Decision |
|---|---|---|
| R1 | Where the lookup reads rulings from | **A** (owner): the running server over the agent socket (the newest locks and re-anchors), falling back to the committed `.overture/locked` files when the server is down. A short timeout; never fails closed. |
| R2 | What an edit of a file a locked ruling covers does | **A** (owner): inform, and warn. The agent sees the rulings for that file before the edit; if the edit would break one (its excerpt or file condition would fail afterwards), it is warned by name, and the edit still goes through. The CI check still blocks the merge. |
| R3 | How agents get it | **A** (owner): a PreToolUse hook on Edit, Write, MultiEdit and NotebookEdit for Claude; `agent.py rulings --path P` for scripts and skills; a `rulings` MCP tool for other agent tools. |
| R4 | Which rulings touch a file | **A** (owner): both, labelled: "holds on this file" (a deciding condition is on it) and "cites this file" (its evidence or source points at it). |

Weighed and not chosen: the committed files only, or the live server only
(R1 B, C); inform only, or blocking a breaking edit (R2 B, C); no automatic
hook, or the hook alone (R3 B, C); the deciding conditions only (R4 B).

### R1-R4 as decided (architect defaults, 1.52)

The lead's architect defaults for the owner's four picks.

- **L1** One stdlib module, `overture/lookup.py`, safe to import from a hook
  (no store or server at import time): `match`, `would_break`,
  `from_export_dir` (rulecheck's reader), and one entry shape for every
  delivery: qid, item, question, answer (short), locked_at, locked_by_name
  (a short name, never an email), label `holds` or `cites`, the deciding
  conditions on the path, `stale`. rulecheck's `conditions` moved there.
- **L2** The server answers on the agent socket only, from the store's
  current rulings built as `fold.py export` builds them: settled rulings
  (withdrawn, kept unchecked, superseded) are left out, stale ones flagged.
  Paths are relative and normalised; `..`, absolute paths and secrets files
  are refused by name; a trailing `/` is a folder. No git, no project code.
  **Changed in building:** the route is `POST /rulings` with `{"paths": [...]}`,
  not `GET /rulings?path=P`, because the one server's `/p/<project>/…`
  admission takes no query string; POST is how the agent door already does
  its other reads (`/ux-export`, `/visual-export`).
- **L3** The file's checkout is the nearest folder holding `.git` (a folder,
  or a worktree's file whose `gitdir:` names the main checkout), found by
  walking up, with no git run. The console is the registry's for that
  checkout, or its main checkout; an unregistered checkout gets nothing.
  **Changed in review (AS1, S1):** never the session's directory (a file in
  another repo got that project's console), and a worktree maps only when
  git's back link `<main>/.git/worktrees/NAME/gitdir` names it again.
- **L4** After-edit text: Write's content; Edit's first replacement (all with
  `replace_all`); MultiEdit's edits in order. An `old_string` not found, a
  NotebookEdit, or a file past `anchors.MAX_READ` is informed only. A
  whole-file hash breaks on any change, and the warning says so. A condition
  that already fails before the edit is not warned again.
- **L5** The hook prints `hookSpecificOutput` with `additionalContext` only,
  never `permissionDecision` (no allow, which skips the owner's prompt; no
  deny, which R2 ruled out). Checked against the Claude Code hooks reference:
  PreToolUse takes `additionalContext`, and a hook with no decision leaves
  the normal permission flow in place.
- **L6** A file's rulings are said once per session, again when the set
  changes; a would-break warning every time. At most 5 rulings, each line at
  most 300 characters, the note at most 2000, then "and N more" with the
  command. Nothing for a file with no rulings.
- **L7** Socket timeout 1.5 s, hook timeout 5 s, fail open and silent. The
  committed rulings answer only when the socket is absent, refuses, times
  out or runs a kit with no lookup, and the note says so.
- **C1 (review, lead):** a 401, 403 or 5xx from the server counts as no answer (Unreachable: the committed rulings answer, with the note); only a 400 naming its `error` is a refusal.
- **C2 (review, lead):** a bad committed ruling file (not plain, too big, not JSON, not valid) is skipped and named in the note ("skipped .overture/locked/X.json: why"), the rest still read; at most 500 files and 16 MiB, "(first N ruling files)".
- **C5 (review, lead):** a would-break is only a condition that holds now and fails after the edit; when the current file cannot be read, there is no would-break check.
- **L8** `agent.py rulings --path P [--path Q] [--json]`, exit 0 unless a
  path is refused (2); an MCP `rulings` tool, `{paths: [...]}`.
- **L9** The writing skills (console-process, console-ux) say once that the
  hook shows rulings before an edit, and to run `rulings --path DIR/` first.

## Sections, pop-outs and a calmer Inbox (decided 2026-10-16)

The owner asked: "do multiple menus (with animation)… configuration and people
should not be in inbox… some of the interface looks very cluttered… fix it all
up", "use the 'dashboard' area to pop out flowcharts and extended material", and
"give more navigation as the 'inbox' can get a little unruly". A two-pass UX
audit, the second pass made against 18 real screenshots, put the questions. The
owner picked from a menu.

| # | Decision | Outcome |
|---|---|---|
| U1 | How the 11 tabs are organised | **A** (owner): a section rail with Work (Inbox, Feed, Tickets, PRs), Automation (Playbooks, Triggers), Projects (Portfolio, Favorite) and Team (People, Chat, Settings), each with sub-tabs. It replaces "More ▾". The `g i` and other shortcuts keep working, and new section shortcuts are added. **Amends D14.** |
| U2 | Phones | **A** (owner): on a phone the console always takes the whole screen, whatever the host page does. The sections sit in a bottom bar and the sub-tabs on top. |
| U3 | Pop-outs on wide screens | **A** (owner): flowcharts, deliberation rounds, long rulings, ticket graphs and the asset viewer open over the dashboard area as a tabbed stack of up to 3. Pin keeps one open, Esc closes and focus returns, and a link can open one. On a phone they open as a full-screen sheet. |
| U4 | When the bugs found ship | **A** (owner): in 1.47, before it is released. The bugs: Operator Shift's layout, the clipped snooze menu, the panel title always reading "Inbox", People in link mode saying "Access policy", the duplicate "locked" pill, the Triggers fold appearing twice, the impact graph cut off, and the Portfolio link. |
| U5 | Inbox grouping | **A** (owner): by lane, in collapsible groups with counts. |
| U6 | Moving through a long Inbox | **A** (owner): a sticky outline of the groups with counts beside the list (a dropdown on phones), `j`/`k` for the next and previous unanswered question, and a sticky Mine toggle (1.41). |
| U7 | Playbooks started from a Claude session | **A** (owner): they stay owner-only (the 1.30.1 security fix). The command says so plainly instead of silently doing nothing, and the docs say so too. Ships in 1.47 with U4. |
| U8 | Labels at the narrowest widths | **A** (owner): below 400px the rail shows icons only, with tooltips and accessible names; labels everywhere else. **Amends D9.** |
| U9 | Smaller points | *Architect default* (the audit's ★): Chat sits in Team; the rail replaces the "More" count; the Triggers tab's nested fold is flattened; the impact graph sizes to its content. Animation is CSS only, 100–180 ms, and off under `prefers-reduced-motion`. A long-poll redraw never animates. |

Weighed and not chosen: two rows of tabs, or a ☰ menu beside five tabs (U1 B,
C); a ☰ menu on phones, or only fixing the clipping (U2 B, C); one pop-out at a
time, or a split screen (U3 B, C); a 1.47.1, or folding the fixes into the
redesign (U4 B, C); grouping by wave, or a switch (U5 B, C); a dropdown only, or
search and keys only (U6 B, C); allowing safe steps, or removing the agent
command (U7 B, C); and labels at every width (U8 B).

---

## Without Cloudflare (decided 2026-10-15)

Wave 2's "install without Cloudflare", on the owner's networks (Tailscale and
ZeroTier). The owner answered "Defaults", so every row is an *architect
default*. L9 (where ZeroTier runs) was a fact, answered before 1.47; L13–L18
(1.47) the owner picked one by one from a menu.

| # | Decision | Outcome |
|---|---|---|
| L1 | What proves who is at the browser | **A**, *architect default*: Overture's own sign-in links. The network (Tailscale, ZeroTier, LAN or loopback) only decides who can reach the console; a local process cannot forge a sign-in. |
| L2 | How sign-in works | **A**, *architect default*: an owner runs `agent.py invite EMAIL` (refused in a Claude Code session). The link works once and expires after 24 hours; the browser stays signed in until revoked. People lists each login's devices with Revoke; invites, sign-ins and revokes go in the role log. Only an owner invites. |
| L3 | HTTPS | **A**, *architect default*: Tailscale through `tailscale serve` (HTTPS, the console stays on 127.0.0.1); ZeroTier on plain HTTP over its encrypted network. |
| L4 | Listening beyond 127.0.0.1 | **A**, *architect default*: `--listen` takes only an address on a Tailscale (100.64/10) or ZeroTier interface; `0.0.0.0` and public addresses are refused. |
| L5 | Cloudflare | **A**, *architect default*: one way in per console, `--auth cloudflare` (the default, unchanged) or `--auth link`. |
| L6 | `server.py --all` | **A**, *architect default*: one mode per server; a sign-in covers every project the login has a role in. *Architect default, security review 2026-10-15:* and the project the link was made from; a project with roles off admits only browsers invited from it (an invite never opens another project to its holder). |
| L7 | Setup | **A**, *architect default*: `onboard.py` asks Cloudflare / Tailscale / ZeroTier / this machine only, and prints the first invite. |
| L8 | Order | **A**, *architect default*: 1.46 sign-in links, devices and a this-machine-only mode; 1.47 `--listen` for Tailscale and ZeroTier, and onboarding; 1.48 the launchd service (D2) and a Dockerfile. |
| L9 | Where ZeroTier runs | **Fact** (owner, 2026-10-15): "inside wsl usually, but also on windows". WSL is in NAT mode; its ZeroTier interface is `zt…` (a 172.22/16 network, beside Docker's 172.17–28 bridges). |
| L13 | Which ZeroTier the console listens on (1.47) | **A** (owner, menu, 2026-10-15): WSL's own ZeroTier node (`--listen <its zt address>`); nothing set up on Windows. Not a Windows portproxy (breaks when WSL's NAT address changes), not mirrored networking. |
| L14 | How `--listen` recognises an allowed address | **A** (owner): by interface: the address must be on a `zt*` (ZeroTier) or `tailscale0` / 100.64/10 (Tailscale) interface; refines L4. |
| L15 | HTTP over the overlay | **A** (owner): Tailscale keeps HTTPS through `tailscale serve`; a ZeroTier console's origin may be `http://<its exact --listen address>[:port]` (ZeroTier encrypts end to end); refines L3. |
| L16 | Starting before ZeroTier is up | **A** (owner): wait for the address up to 2 minutes with one log line, then exit non-zero so the service restarts it. |
| L17 | Another network overlapping the listen network (Docker) | **A** (owner): warn at startup and in onboarding, naming the overlapping interface. |
| L18 | The two 1.46 review LOWs (a percent-encoded token to a wrong path not redacted; invalid UTF-8 in roles.json drops the connection) | **A** (owner): fixed in 1.47. |
| L10 | Directors and the two-key areas | **A**, *architect default*: owners only; directors see them but cannot change them. **Amends S1.** |
| L11 | Notifications through `HTTPS_PROXY` | **A**, *architect default*: honoured, and documented. |
| L12 | The two 1.45 LOWs (a repeated send error not logged again; unsaved Settings text lost on redraw) | **A**, *architect default*: fixed in 1.46. |

Weighed and not chosen: identity from the network itself (L1 B, C), devices
that sign in again every 30 days (L2 B), directors inviting (L2 C), the
console serving its own certificate (L3 B), any listen address (L4 B), both
ways in on one console (L5 B), a mode per project (L6 B), flags only (L7 B),
and one large release (L8 C). For 1.47: Windows' ZeroTier through a portproxy,
mirrored networking or both (L13 B–D), an owner-listed range or any private
address (L14 B, C), HTTPS through a private CA or Tailscale only (L15 B, C),
failing at once or falling back to loopback (L16 B, C), docs only (L17 B), and
leaving the LOWs (L18 B).

---

## Server hosting

### D1. How the server runs

**What depends on it:** whether answers you give from your phone reach
agents when no Claude session is open, and whether the plugin's hooks stay
read-only.

| Option | In this project | Upside | Cost |
|---|---|---|---|
| **A ★** A per-OS user service, plus a read-only session check | `server.py service install` writes the unit. The SessionStart hook prints one line when the server is down. | The console works with the laptop's sessions closed. Restarts and logs are handled. The hooks stay read-only. | About two minutes of setup, once. Three service templates to maintain. |
| B The main Claude session starts the server | The SessionStart hook spawns `server.py --all` if it isn't running. | No setup step. | Answers stop when the session ends. Hooks would then start a network daemon, breaking the README's trust promise. Sessions race for the lock. |
| C Service only, no session check | Today's `install.sh` units. | Nothing new to build. | A server that is down goes unnoticed until you open the console. |

**Why A:** the async loop is the product: agents ask, you answer later,
from anywhere (SERVER-HOSTING.md, "What the server has to do", 1). Only a
service survives the session ending. The check covers the "people get lost
after install" problem without the hook owning a daemon.
**What would change it:** if most users only use the console while a
session is open, and never from a phone, B's zero setup would win.

### D2. When macOS gets a service installer

**What depends on it:** whether Mac users get a one-command install in the
first release of `service install`.

| Option | In this project | Upside | Cost |
|---|---|---|---|
| A With Linux/WSL, in one PR | A launchd plist template next to the systemd units | Every POSIX user gets it at once. | A bigger PR, and launchd can't be tested in CI here. |
| **B ★** Right after Linux/WSL, as its own PR | Same command; macOS added second | Linux ships sooner. The macOS change is small and reviewed on its own. | Mac users wait one release. |
| C Later, when someone asks | — | No work now. | Mac users write their own plist. |

**Why B:** the command and its tests get settled on systemd, which
`install.sh` already uses, and launchd is then a template behind the same
command.
**What would change it:** if you or your first users are on Macs, choose A.

### D3. One main server for new installs?

**What depends on it:** how many processes, units and loopback ports a user
with several projects has to manage.

| Option | In this project | Upside | Cost |
|---|---|---|---|
| **A ★** Yes: new installs use `server.py --all` | `install.sh` writes `overture-console.service`. Each project joins with `server add` ([JOIN.md](../JOIN.md)). | One process and one unit. Adding a project needs no new unit. Upgrades restart once. | A restart is needed to pick up a new project. One crash stops every console. |
| B No: one server per project stays the default | Today's `<name>-console.service` | Projects are isolated; this is what exists. | N units, N restarts, N ports to track. |
| C Ask during install | `onboard.py` asks which mode | Both kinds of user are served. | One more question at install time, and two paths to document and test. |

**Why A:** JOIN.md already documents and tests `--all`, and the server
refuses a project it can't open by name while serving the rest, so one bad
project doesn't take the others down.
**What would change it:** if you need strong isolation between projects (for
example, different clients on one machine), choose B.

---

## UX View

### D4. What a saved UX component is

**What depends on it:** what the modal can safely render, and what an agent
produces when you press Generate.

| Option | In this project | Upside | Cost |
|---|---|---|---|
| **A ★** One self-contained HTML document: inline styles, no scripts | Shown through the existing `/visual` sandbox with scripts off | Uses the sandbox that exists, with no new script surface. Any framework can copy it in. | Interactive behaviour (state, events) can only be described, not shown. |
| B Framework code (React or similar) saved alongside, with HTML as its preview | `components/<item>.jsx` plus the preview HTML | Code that drops straight into the app | Two artifacts to keep in sync. The preview can drift from the code. |
| C Framework code rendered live | A sandboxed iframe with scripts on | True interactivity | A new script-running surface, against the 1.31 hardening. |

**Why A:** UX-VIEW.md's second rule ("the server generates nothing") and the
scripts-off sandbox mean A needs no new trust decision. B can be added later
as an extra file.
**What would change it:** if your UX items are mostly interactive widgets
rather than layouts and styles, B is worth its cost.

### D5. Where components are saved

**What depends on it:** where the steward's PRs write, and where your app
code reads them from.

| Option | In this project | Upside | Cost |
|---|---|---|---|
| **A ★** `components/<item>.md` plus `.css`, with backups in `components/.history/` | As UX-VIEW.md proposes | Easy to find, and the history sits beside the files. | A new top-level folder in every project. |
| B Under `.overture/components/` | Next to `portfolio.json` and the adapter | Overture's files stay in one place. | Hidden from people who don't know Overture. |
| C Configurable in `.overture.json`, default A | `"components_dir": "…"` | Fits projects with their own layout. | One more setting to validate and test. |

**Why A:** components are project artifacts that people browse and import,
not Overture state. If people ask, C can come later without moving anything.
**What would change it:** if your projects already have a `components/`
folder with another meaning, choose C.

### D6. Which items get UX View

**What depends on it:** which items show the button, and where new UX items
are placed in the dashboard.

| Option | In this project | Upside | Cost |
|---|---|---|---|
| A Fixed: `lane-ui`/`lane-ux` sections plus a `ux` tag | As UX-VIEW.md proposes | Simple, with nothing to configure. | Projects that name their lanes differently get no button. |
| **B ★** The A defaults, overridable in `.overture.json` | `"lanes": {"lane-frontend": {"ux": true}}`, the same registry as D10's colours | Works with any naming. | One small setting. |
| C Every item | The button everywhere | Nothing to configure. | Noise on backend items. |

**Why B:** lane names come from each project's adapter, so a fixed list will
miss some. The setting accepts names only, the same as D10's override.
**What would change it:** if every project you run uses `lane-ui`, A is
enough.

### D7. How a saved component reaches the repository

**What depends on it:** the trust model. Today nothing reaches the
repository without a PR you merge.

| Option | In this project | Upside | Cost |
|---|---|---|---|
| **A ★** Through the steward and a PR | `ux-save` → steward → `agent.py ux-export` → PR | Same path as rulings and visuals; the server never writes the project. | Save takes effect at merge, not instantly. |
| B The server writes the file directly | The server writes `components/` | Instant | Breaks "the server never writes into the project", a core promise. |
| C A PR that merges itself when checks pass | Like A, with auto-merge | Close to instant | A web page click lands code with no human looking at the diff. |

**Why A:** rule 1 in UX-VIEW.md, and the README's trust section. The modal
can show "saved, PR #N pending" so the delay is visible.
**What would change it:** nothing short of dropping the trust model.

### D13. How a UX item is tied to a Claude Design project

**What depends on it:**

- whether the tie survives outside the console;
- whether agents can build from the design;
- whether the server gains an outbound door.

The full design is in [UX-VIEW.md](UX-VIEW.md), "Linking a Claude Design
project".

| Option | In this project | Upside | Cost |
|---|---|---|---|
| **A ★** A link stored in the component's front matter by the steward's PR, and shown on the item. Agents read the design; the server never opens it. | `ux-link` intent → `ux-export` writes `design: {url, kind, synced_version}`; an exact-shape URL check like `prs.py` | Visible in the repository and in git history. Drift raises a question, like stale rulings. No new server network access. | Linking takes effect at merge, like Save. |
| B The link kept only in console state | A field on the item in STATE | Instant | Lost outside the console: other tools and a fresh clone never see it. |
| C The server fetches and previews the design | The server calls claude.ai | A live preview in the modal | The server would need a claude.ai login, and it gets an outbound fetch door. Breaks the trust model. |

**Why A:** the server holding no credentials and never fetching what a page
gives it is the same rule that makes PR links exact-shape (`prs.py`). The
repository is where the component lives, so it is where its source belongs.
**What would change it:** if links are only scratch notes and never need to
outlive the console, B is simpler.

---

## Icons and lane colors

### D8. Where the icons come from

**What depends on it:** how the tab bar, menus, palette and status marks
look, and what gets bundled.

| Option | In this project | Upside | Cost |
|---|---|---|---|
| **A ★** About 25 Lucide icons, copied into `console.js` as inline SVG with `currentColor` | Pinned with a license note and a checksum, like the bundled libraries | Familiar and consistent. ISC license. No network requests and no icon font. | Paths to update by hand if Lucide changes. |
| B Draw our own | Same inline SVG | Fully ours | Design time, and the result is likely less polished. |
| C An icon font from a CDN | `<link>` to a CDN | Least work | Breaks the no-outside-resources rule (1.31). |

**Why A:** it keeps the 1.31 rule (no outside resources) at almost no cost.
**What would change it:** if you want a distinct brand look, B.

### D9. How tabs show icons

**What depends on it:** whether tabs clip in the side dock.

| Option | In this project | Upside | Cost |
|---|---|---|---|
| **A ★** Icon plus label when wide, icon only with a tooltip when narrow | A container query on the tab bar | Ends tab clipping for good while staying readable. | Two layouts to test. |
| B Always icon plus label | — | Always readable | Clips in a narrow dock; today the tab bar scrolls. |
| C Icon only | — | Most compact | New users must hover to learn the tabs. |

**Why A:** the dock width is user-set (default 480px), so the tabs must work
at both widths. This was the clipping complaint behind the wider-column fix.
**What would change it:** if nobody uses a narrow dock, B is simpler.

### D10. How lanes get colors

**What depends on it:** the section chips, row edges, project map and
dashboard blocks.

| Option | In this project | Upside | Cost |
|---|---|---|---|
| **A ★** Automatic: a lane's name maps to one of 8 colors that work in both themes. Optional named override in `.overture.json`. | `"lanes": {"lane-api": {"color": "blue", "icon": "server"}}`; palette names only, never raw CSS | Works with no setup, and the same lane always gets the same color. The override can't inject styles. | Two lanes may share a color by chance until overridden. |
| B Config only: lanes without a color stay gray | Same setting, required | Every color is chosen on purpose. | Nothing shows until someone configures it. |
| C No lane colors; icons only | — | Least work | Loses the "where does this belong" view at a glance. |

**Why A:** items already carry `wave-2/phase-2.2/lane-api` in their `section`,
so colors come from data that exists. Color is never the only signal: the
chip's text names the lane.
**What would change it:** if you want a fixed lane legend across projects, B.

---

## The steward

### D11. A per-machine steward role setting?

**What depends on it:** whether a machine can be marked "workers only".

Today the role is per session: `/overture:as <steward name>` makes a session
the master, and any other name makes it a worker. The plugin's **Master agent
name** setting supplies the name.

| Option | In this project | Upside | Cost |
|---|---|---|---|
| A Add `role: steward \| worker` to the plugin settings | A plugin `userConfig` field. With `worker`, `/overture:as <steward>` is refused on that machine. | Enforces "the steward only runs on the home server". | Applies to every session on the machine; one more setting to explain. |
| **B ★** Not now; keep it by session name | Today's behaviour | Nothing new to build or explain. | A laptop session can still name itself the steward. |

**Built (1.33), option A.** The plugin has a **Machine role** setting
(`steward` or `worker`); `agent.py role worker|steward|clear` sets the same
thing in your registry, and if either says `worker`, the machine is a worker.
On a worker, `/overture:as <steward name>` is refused and records nothing, a
session started under the steward's name is told it is not the steward and
may not ask you live, and `watch`, `synced` and the fold refuse even for that
name. `steward` or no setting changes nothing. It is a guardrail between your
own sessions, not a security boundary: anything running as you can edit the
registry. (The plugin setting reaches hooks as `CLAUDE_PLUGIN_OPTION_ROLE`;
the command line reads it if Claude Code exports it there, and always reads
the registry.)

**Why it had been B:** a plugin setting applies machine-wide, so it can't
express "this session is the steward". It only helps if the steward runs on a
separate machine.
**What would change it:** if you run the steward on a home server and only
workers on laptops, A is worth adding.

---

## What next

### D12. What to build next

**What depends on it:** the order of the next PRs. Each one is merged before
the next starts.

| Option | Work | Size |
|---|---|---|
| **A ★** Icons and status indicators, then lane colors (D8–D10) | Two PRs: `console.js`, `console.css`, tests, screenshots | Medium |
| B UX View (D4–D7) | Schema intents, the `console-ux` skill, `ux-export`, the modal | Large |
| C `server.py daemon|service|status|health` and the session check (D1–D3) | `server.py`, `session_start.py`, units, docs | Medium |
| D Logged bugs: the project map lays every item out in one row; a `BrokenPipeError` traceback in `_send_raw` | `chart.py`, `server.py`, tests | Small |

**Why A:** its design is finished, and it changes what every screenshot
shows. Doing it first avoids redoing UX View's screenshots later. D is small
enough to ride along with whichever PR touches `chart.py` or `server.py`.
**What would change it:** if new users still get lost after installing, C
first. If a UX project is waiting, B first.
