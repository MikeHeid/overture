# Proposal: UX View

**The ask.** Some items are UI/UX work: a component or page being built or
deliberated on, with or without Claude design. Each of those gets a **UX View**
button. The button opens a modal that shows the component with all its
styles. From there the owner can:

- **Generate** a version, or steer one in a chat;
- **Save** a version as the item's component, with the old one kept as a
  backup.

When a UX item is created, it is placed in the right wave, phase and lane on
the dashboard automatically.

Status:

- Decided on 2026-10-11 (D4–D7, with amendments). D13, the Claude Design
  link, took its ★ as an architect default; its URL shape is now pinned from a
  real link. See [OPEN-DECISIONS.md](OPEN-DECISIONS.md).
- Revised the same day after an advisor, a DevOps and a UX review. Their
  findings are folded in; the list is at the end.
- S1 and S2 below took their ★ as *architect defaults* (2026-10-11).
- **Step 1 shipped in 1.32:**
  - `purpose`/`from` on visual requests;
  - the `ux-save` and `ux-link` owner intents, which wake the doorbell and
    are listed in `todo.ux`;
  - the item fields `ux` and `design`;
  - the `/ux-export` read;
  - `agent.py ux-export`, which writes `components/<item>.md` and `.css`
    with hash-named backups, keeping 10;
  - the console-ux skill's save path.

- **Step 2 shipped (the modal):** `◫ UX View` on a UX item (or **Open in UX
  View** on any HTML visual, or `u`); version stepper (`[` `]`); a Mobile /
  Tablet / Desktop / Fit radio group with a scaled, sandboxed preview;
  **Generate ▾** (face, with notes, from design); **Save as component**; a
  Settings panel with the Design link; live status line. Differences from the
  sketch above: "Generate with notes" opens a notes box in the modal rather
  than a Thread tab, and the Scripts switch is left to step 4 (the panel says
  so).

- **Step 3 shipped (Merge from the PR tab):** `head_sha` in the PR snapshot
  (optional; `prs-push` sends it); the reserved `@prs` thread and the owner's
  `pr-merge` intent; the server stores a request only for a PR the steward's
  last push shows open, not draft, passing and still at the commit the owner
  saw, one pending request per PR; the PR tab's **Merge** button with its
  inline two-step confirmation and the states "Merge requested … waiting for
  a session" and the steward's reply; `todo.merge`; and `agent.py pr-merge`,
  which re-reads the PR with the steward's own `gh`, refuses by name (24-hour
  expiry included), merges with `--match-head-commit`, and replies on `@prs`.

- **Step 4 shipped (the Scripts switch):** the owner-only `ux-scripts` intent
  (per visual, `visual_id` + `scripts`); an agent's raw scripted source stored
  write-once beside the visual (`agent.py component-source`, route
  `/component-source`); `/api/component-render`, which serves that source only
  while the owner's newest switch for the visual is on, under
  `COMPONENT_CSP` (sandbox allow-scripts, default-src 'none', connect-src
  'none'); the modal frame with `sandbox="allow-scripts"` and the "⚡ Scripts
  on" badge; `ux-export` landing the source with `scripts: true`. Differences
  from the plan above: the scripted source is a file beside the visual, not a
  new visual record; the switch is per version; and it refuses to turn on
  without a stored source. A browser test runs a hostile component and shows
  it reaches nothing.

  Next: the hosting commands (`server.py daemon|service|status|health`).
- **The design-system picker shipped later (1.33), at the owner's request,
  reversing the reviewers' earlier "don't build".** An agent lists the
  design's artifacts (`agent.py design-inventory`; `designs.py`, route
  `/design-inventory`, at most 300 plain relative paths, kept per design
  link); the owner ticks up to 10 in the modal's Settings, each **inspire**
  or **swap**; Generate carries them as `refs`. The server cross-checks every
  ref against the list for the item's linked design (409 naming what is
  wrong), never reads or opens the design, and draws the list as text. Swap
  makes a new version from that artifact; it never overwrites a saved
  component or the design. The cheap text-path route in "Pointing at
  artifacts" still works beside it.

---

## Two rules this design keeps

1. **The server never writes into the project.** It never writes a file in
   your checkout. Everything reaches the repository the way rulings and
   visuals already do:
   - the steward writes the change in its own worktree;
   - it opens a pull request;
   - you merge it.
2. **The server generates nothing and fetches nothing.**
   - "Generate" becomes an owner message that rings the doorbell.
   - An agent does the work and posts the result back as a **visual**.
   - The server holds no claude.ai login and no GitHub token.

Both rules are why a ruling, a visual or a dashboard change can never come
from a repository or a web page alone.

## What already exists, as it really behaves

| Piece | Today |
|---|---|
| Showing HTML safely | An HTML visual is **sanitized when it is stored** (`server.py` `sanitize_html`, `visuals.py`). Scripts, `style` attributes, `svg` and `form` are removed; `<style>` blocks survive. Since 1.32 (S1), inert controls (`button`, `input`, `select`, `textarea`, `label`, `details`, `dialog`, …), `popover`/`popovertarget` and built-in invoker commands survive too, and CSS in `<style>` is no longer HTML-escaped. It is served under `VISUAL_HTML_CSP`, which carries its own `sandbox` directive, in an `<iframe sandbox="">`. |
| Mermaid | The vendored library runs in its own frame under a per-request nonce (`VISUAL_RENDER_CSP_TMPL`). |
| Asking an agent to draw | **Request a visual…** on an item: an owner `message` with `intent: "visual"`. `agent.py visual` answers it, at most 3 visuals per request (`MAX_VISUALS_PER_REQUEST`). |
| Moving a visual into the repo | `agent.py visual-export --project <worktree>` writes files only; the `console-visual` skill opens the PR. |
| Talking about one item | The item's thread: an owner `message`, answered by `agent.py reply`. |
| Waves, phases and lanes | An item's `section`, e.g. `wave-2/phase-2.2/lane-ui`. `items-push --sync-dashboard` nests the item under it. |
| Versions | Variant chips, "v3 of 7" with Prev and Next across an item's visuals (1.29). |
| Pull requests | `prs-push` stores a snapshot per PR: number, branch name, checks rollup, URL. No head commit id. |

## Which items get UX View

An item is a UX item when either holds:

- its `section` has a UX lane segment. The defaults are `lane-ui` and
  `lane-ux`. A project can add its own lanes in the one lane registry it
  shares with lane colours (D10):

      ".overture.json": {"lanes": {"lane-frontend": {"ux": true, "color": "blue"}}}

  `projectcfg.py` validates the key and refuses unknown fields by name;
- the item sets `ux: true`, a new optional item field.

Dropped after review:

- `kind: "ux"`: `topic` is a structural kind, so an item could not be both.
- `star_by: "ux"`: it names a committee seat, not a tag.
- "already has an HTML visual": it would turn every mock-up into a UX item.

## Where the button lives

The item tools row already wraps at the dock's width, so UX View adds no
seventh button:

- On a UX item, **◫ Request a visual…** becomes **◫ UX View**. The modal
  covers requesting and generating.
- Every HTML visual card gets a quiet **Open in UX View** next to its
  "v3 of 7" chip.
- Shortcut `u` on a UX item, listed in the shortcut sheet.
- Its accessible name is "Open UX View for <item>: preview, versions, save".

## The modal

It is a viewport overlay, not something drawn inside the 480px dock. It uses
the fragment viewer's pattern: fixed, `inset: 0`, width
`min(1100px, 96vw)`, full screen below 768px.

    ┌ UX View · UI-2 Checkout button ───────────────── [✕] ┐
    │ ◂ v4 of 7 ▸  ● not saved     (Mobile|Tablet|Desk|Fit)│
    │ ┌──────────────────────────────┐ ┌ Component ─────┐  │
    │ │                              │ │ Saved: v2      │  │
    │ │   sandboxed preview          │ │ components/…md │  │
    │ │   Desktop · 1280px · 62%     │ │ @ a1b2c3d      │  │
    │ │              ⚡ Scripts on    │ │ ▸ Settings     │  │
    │ └──────────────────────────────┘ │   Scripts [off]│  │
    │  [Preview] [Thread]  (tabs <900) │   Design link  │  │
    │                                  └────────────────┘  │
    │ status: Saved v4 · waiting for PR #231 (live region) │
    ├──────────────────────────────────────────────────────┤
    │ [Generate ▾]                     [Save as component] │
    └──────────────────────────────────────────────────────┘

- **Size.** A radio group: Mobile 375, Tablet 768, Desktop 1280, Fit. The
  frame renders at its true width and is scaled down with
  `transform: scale()`, with the scale shown ("Desktop · 1280px · 62%").
  - The last choice is remembered per viewer, in localStorage wrapped in
    try/catch.
  - The frame's title carries the version and width, e.g. "Checkout button
    v4, 375px".
- **Versions.** The same ◂ v4 of 7 ▸ control as today, with `[` and `]`.
  - It marks which version is saved and which is in a PR.
  - Each change is announced, e.g. "Version 3 of 7, by agent-2, 2 h ago".
- **Component panel.** The saved component's path and commit, read from its
  front matter. The server reads it read-only, jailed the way it reads
  `specs_dir`. A collapsible **Settings** holds the Scripts switch (D4) and
  the Design link (D13).
- **Footer.** One primary action per state, on the right. On the left is
  **Generate ▾**, a split button:
  - its face runs **Generate**;
  - **Generate with notes…** opens the Thread;
  - **Generate from design** is disabled, with the hint "Add a Design link
    first", until a link is set.
- **Thread.** Below 900px it is a tab ("Preview | Thread"); wider, it sits
  beside the preview.
- **Accessibility.**
  - `role="dialog"`, `aria-modal`, `aria-labelledby` the title.
  - The existing `attachDialogAccessibility` provides the focus trap and
    returns focus to the opener. Escape closes.
  - The console panel and the page are made `inert` while the modal is open.
  - Every status line is in an `aria-live="polite"` region.
  - Targets are at least 24px.
  - Scale and spinner animations sit under
    `prefers-reduced-motion: no-preference`.

### States and their copy

| State | Status line | Primary |
|---|---|---|
| Empty | "No version yet. Generate one, or describe what you want." | Generate |
| Generating | "Asked agent-2 · waiting for a session…", then "Drawing v4…" | none (Generate reads "Requested") |
| Unsaved version | "v4 of 4 · not saved · saved component is v2" | Save as component |
| Saved, PR open | "Saved v4 · waiting for PR #231 to merge" | Open PR #231 |
| Merged | "Component: components/checkout-button.md @ a1b2c3d" ("Current" on that version) | none |
| Older version shown | "Viewing v2 · current component is v4" | Save v2 as component |
| Design changed | "Claude Design changed since this was saved." | Regenerate from design (Keep, Unlink secondary) |
| Scripts on | A steady "⚡ Scripts on" badge in the preview header | none |

## The component format

- A component is **one HTML document with a `<style>` block and classes**,
  not inline `style` attributes, because the sanitizer removes those.
- Scripts are off by default. The Scripts switch below turns them on.
- Form controls are a sub-decision, [S1](#open-sub-decisions), because the
  sanitizer drops them today.

## Generating, the agent's side

- **Generate** reuses the visual request: an owner `message` with
  `intent: "visual"` plus a new optional field `purpose: "ux"`.
  - The store, the view, the console and the doorbell already accept
    `visual` requests and their 3-per-request cap, so nothing in that chain
    has to learn a new intent.
  - Generate from design adds `from: "design"`.
- A new skill, `console-ux` (shipped in 1.32, with researched references, a
  worked example and `tools/ux_check.py`), handles visual requests on UX
  items. Today that means a `lane-ui` or `lane-ux` section; `purpose: "ux"`
  joins when the schema intents land (step 1):
  1. It reads the item, its rulings, the current component file, and the
     project's design tokens (the `:root` CSS custom properties).
  2. It writes the component as one HTML document with a `<style>` block.
  3. It posts it with `agent.py visual --format html`.
  4. With a Design link, it reads the design first; see below.

## Saving

**Save** writes no files itself. It records the owner's choice, and the
steward carries it into the repository:

1. The console sends an owner message with `intent: "ux-save"` and
   `visual_id`. The choice is in the audit trail like any other owner act,
   and `ux-save` joins the doorbell's `WAKE_INTENTS`.
2. The steward runs `agent.py ux-export --project <worktree>`. Like
   `visual-export`, it **writes files only**:
   - `components/<item>.md`: front matter (item, visual id, saved by, date,
     and `scripts` and `design` when set), a short description, and the
     component HTML in a fenced block;
   - `components/<item>.css` when the component has a `<style>` block;
   - when a component file already exists **with different content**, it is
     moved to `components/.history/<item>-<sha8>.md` (and `.css`) first.
     That is the backup of the old style. Naming it by content hash keeps
     the command idempotent: running it twice changes nothing.
3. The `console-ux` skill opens the PR on branch `overture/ux/<item>`. It
   replies in the item's thread with the PR's URL, so the modal can show
   "waiting for PR #231".
4. The modal shows "Saved in `<path>`" once the next `prs-push` shows the PR
   merged.

`.history/` keeps the last 10 versions per component; `ux-export` prunes
older ones in the same PR.

## Scripts in components (D4)

The owner decided scripts may be turned on per component. Today's visual
path cannot do that, because scripts are stripped when stored and
`VISUAL_HTML_CSP`'s own `sandbox` directive overrides the iframe. So
scripted components take a separate path:

- **The switch is an owner act.** It sends a `ux-scripts` owner message, so
  `scripts: true` comes only from the owner's record, never from a field an
  agent posts.
  - The preview starts running scripts at once.
  - The steward records `scripts: true` in front matter at the next save.
- **Stored raw, served apart.** A scripted version is stored unsanitized in
  its own file. Only one route serves it: `/api/component-render`, under:

      sandbox allow-scripts; default-src 'none'; script-src 'unsafe-inline';
      style-src 'unsafe-inline'; img-src data:; font-src data:;
      base-uri 'none'; form-action 'none'; frame-ancestors 'self'

- **The frame** is `sandbox="allow-scripts"` only: no `allow-same-origin`,
  `allow-popups`, `allow-top-navigation*` or `allow-forms`. It runs in an
  opaque origin, so it cannot reach the console, its cookies or its
  storage.
- **Messages.** The console's `message` listener must accept messages only
  from its own chart frames. Today it does not check the sender. That fix
  ships first, on its own, because it matters already.
- **What remains open in the browser.** The frame can still navigate itself,
  use WebRTC, or trigger DNS prefetch; CSP cannot block those today. So the
  copy says outbound requests are "blocked where browsers allow", never "no
  network".
- **Copy.** The first time the switch is turned on, an inline note (not a
  modal): "Scripts run in a sealed frame with no access to the console or
  its cookies. Turn on only for components you need to see working." After
  that, only the "⚡ Scripts on" badge.
- **This reverses part of the 1.31 hardening.** It ships last, behind its
  own security review.

## Merging from the PR tab (D7)

- **The button.**
  - **Merge** appears only on the project's **own** PR tab, never on
    Portfolio: a primary reads only counts from its secondaries and cannot
    write to them.
  - It is shown only on PRs that are open, not draft, and passing checks.
    Other open PRs show "Merge when checks pass" as text.
- **Confirming.** Inline, in two steps: "Merge #214 into main? The steward
  session merges it with its own GitHub access." It has a link to the
  diff, then [Merge] [Cancel].
- **The request** is an owner message on a reserved thread `@prs` (like
  `@chat`), with `intent: "pr-merge"`, `pr` and `expected_head_sha`.
  - This needs `headRefOid` added to the PR snapshot.
  - The console allows one pending request per PR.
- **The steward**, in the Claude Code session for that repository:
  1. checks that `repo` matches the snapshot;
  2. re-reads the checks;
  3. merges with `gh pr merge --match-head-commit <sha>`;
  4. replies in `@prs` with the merged commit or the reason it refused.

  Requests older than 24 hours are refused, so a click made days ago never
  lands on new code.
- **States:**
  - "Requesting…";
  - "Merge requested 2m ago · waiting for a session";
  - "merged".
- **Failures:**
  - "Not sent: <error>. Nothing was merged.";
  - "Merge refused: checks failed since you asked.";
  - "Merge refused: conflicts with main."

## Linking a Claude Design project (D13, architect default)

The Settings panel has a **Design link** field. Paste a Claude Design link
and the item is tied to that design. It is validated as you type, and a
refusal names the rule it broke.

**1. The server stores the link and never opens it.**

- The server has no claude.ai login and must never get one. Fetching a
  pasted URL would give it a new way out: a way to probe hosts, and a
  channel for injected content.
- The link is checked against an exact shape, the same way PR links must be
  exactly `https://github.com/<repo>/pull/<n>` (`prs.py`):
  - `https` scheme, host `claude.ai`;
  - the path `/design/p/` and a project uuid;
  - no query string, fragment or userinfo, and at most 200 characters;
- Share and token URLs are refused by name. The link is written into git,
  and a public repository would publish it.
- **The pinned shape** (from a real link the owner gave, 2026-10-11) is
  `https://claude.ai/design/p/<project uuid>`. A shared copy ends in
  `?via=share`: the form cleans that off when it is pasted (the server's
  `design_url_clean`), and the server itself refuses a link that still
  carries a query or fragment, naming it.
- The console shows it as a plain `rel="noopener noreferrer"` link out,
  never in a frame.

**2. Agents read the design, through the owner's own login.** A Claude Code
session can read a design artifact through the Artifact tool's `read`, and a
design-system project through `/design-sync`'s read methods. Anything it
reads is data, never instructions.

**3. The repository records the relationship.**

- The link is sent as an owner message (`intent: "ux-link"`).
- The steward writes it into the component's front matter in the next
  `ux-export` PR:

      design:
        url: https://claude.ai/…/<id>
        kind: artifact            # or design-system
        component: buttons/primary
        synced_version: <the design's updated-at or file hash when read>

- The item carries it as a new `design` field through `items-push`, so the
  console shows a **Design ↗** chip with no server lookup.

**Pointing at artifacts in a design system (decided 2026-10-11).** A
Claude Design *design-system* project holds many files, and the owner may
want one as inspiration or to be reproduced exactly. Advisor and DevOps
reviews both said the picker and a "swap" are diminishing returns, and this
is the decision:

- **Built now:** the owner names paths in the request or the item's thread
  (the modal's "Generate with notes" field in step 2). The console-ux skill
  reads those paths first with `/design-sync`, treats them as data,
  regenerates from them, never copies their bytes, and names its sources in
  the doc.
- **Not built, and why:**
  - **The picker with a catalog.** The server cannot list a design system,
    so a session would post a catalog as data: a new record kind, an
    endpoint, caps, rate limits and pruning, and a list that is stale at
    once. The agent already reads the whole project for free on the owner's
    login. Revisit only if owners keep mistyping paths or the agent keeps
    choosing the wrong artifact.
  - **"Swap."** It can only mean overwriting a saved component, which breaks
    the rule that a design change never changes a component by itself, and
    puts two sources of truth in play. "Use it as it is" through Generate,
    reviewed and saved like any version, gets the same result.
- **If it comes back:** one optional bounded field on `ux-link` (a list of
  paths matching `[A-Za-z0-9._/-]`, at most 10), written to front matter as
  `design.refs`, and nothing else.

**Drift.**

- `synced_version` works like a ruling's `valid_if` anchor. When a session
  finds the design changed, the steward asks: regenerate, keep, or unlink.
- The design changing never changes the component on its own.
- Sending a component back into a design-system project is optional, and
  only when the owner runs `/design-sync`.

## Placing a new UX item on the dashboard

When a UX item is created (from Launch Idea, Branch Out, or the adapter), the
steward:

1. **Picks the section**: the parent's wave and phase, plus the first UX lane
   in the registry (`lane-ui` by default). If the parent has no section, it
   uses the newest open wave and phase.
2. **Sends it through the adapter**, which owns the item list. When the
   adapter can't take it, the steward proposes it as a question.
3. **Updates the board** with
   `items-push --sync-dashboard docs/console/page.html`. You publish the page
   with **Use this page** as usual.

## Schema changes

| Record | New optional fields |
|---|---|
| owner `message` | `purpose` (`ux`), `from` (`design`), `visual_id`, `pr`, `expected_head_sha`, `url`, `scripts` |
| owner intents | `ux-save`, `ux-link`, `ux-scripts`, `pr-merge` |
| reserved thread | `@prs` |
| item | `ux`, `design` |
| PR snapshot | `head_sha` (from `headRefOid`) |
| `.overture.json` | `lanes.<lane>.ux` |

**Rollback.**

- A kit older than these changes refuses a store that holds them, by name
  (`schema.py`). So going back to 1.31 after using UX View leaves that
  project refused.
- The CHANGELOG says so, and says how to restore it: move the new records
  aside, or upgrade again.
- Each step below bumps the version.

## What it takes, in order

0. **The message-sender fix, alone.**
   - The console accepts `message` events only from its own chart frames.
   - `sandbox allow-scripts` is added to the Mermaid render CSP, so the
     render route opened in its own tab is sandboxed too.
1. **Server, schema and agent side.** All of it is testable without the
   console:
   - the new fields and intents;
   - `purpose: "ux"` on visual requests;
   - the doorbell's wake list;
   - the item and lane-registry fields;
   - `ux-export`;
   - the `console-ux` skill.

   Tests: `test_server.py` (schema, owner-only intents), `test_kit.py`
   (`ux-export`), `test_build.py` (the skill ships in the zip).
2. **The console modal and lane placement.** Tests: `test_kit.py`, plus
   `test_browser.py` for the dialog, focus and states.
3. **Merge from the PR tab.** It does not depend on the UX work. Tests: the
   `@prs` thread, one pending request per PR, `head_sha` in the snapshot.
4. **The Scripts switch**, behind its own security review. A
   `test_browser.py` case proves a scripted component cannot reach the
   parent, navigate the top window, or post messages the console accepts.
5. **The Design link**, once D13 is decided.

## Sub-decisions (architect defaults, 2026-10-11)

- **S1. Form controls.** The sanitizer drops `button`, `input`, `select`,
  `label` and `textarea`.
  - **A ★** Add them to the allowlist as inert tags: with no scripts, no
    `form` and `form-action 'none'`, they cannot submit or run anything.
  - **B** Components show controls as styled `div`s.
- **S2. When scripts start.**
  - **A ★** At once, when the owner flips the switch, with "recorded at
    next save" shown underneath.
  - **B** Only after the steward has recorded it.

## What the review changed

| Reviewer | Finding | Where it went |
|---|---|---|
| Advisor | The sanitizer strips styles and form controls | The component format; S1 |
| Advisor, DevOps | The Scripts switch can't work on the visual path | Scripts in components |
| Advisor, DevOps | A `ux-generate` reply would be refused by the store | Generating: `purpose: "ux"` |
| Advisor | Lane keys disagreed; `ux.dir` contradicted D5; `star_by`/`kind` misused | Which items get UX View |
| Advisor | `ux-export` must not open the PR itself; timestamped backups broke idempotency | Saving |
| Advisor, DevOps | `pr-merge` needs a thread, a head SHA, one pending request, and routing | Merging from the PR tab |
| DevOps | The console trusts messages from any frame; the Mermaid CSP lacks `sandbox` | What it takes, step 0 |
| DevOps | Rollback refuses newer stores; tests and packaging unlisted | Schema changes; What it takes |
| DevOps | Design links end up in git | Linking a Claude Design project |
| UX | No seventh button; a viewport modal; one primary action per state | Where the button lives; The modal |
| UX | Merge needs confirmation, states and failure copy | Merging from the PR tab |
