# Dashboard, project map and lanes

[← Back to README](../../README.md)

Name a session, scaffold your project's dashboard page, colour it by lane, and publish it yourself.

## Name the session, bootstrap the dashboard

**Set the agent id for a Claude session** — in Claude Code:

    /overture:as my-agent-name

The name is recorded against this session in `STATE/sessions.jsonl`. Every
`agent.py` call the session makes signs with it, questions and messages are
attributed to it, and the SessionStart banner knows which session is which.
`OVERTURE_AGENT=my-agent-name` in the shell env is a machine-wide fallback;
`/overture:as` wins for that session.

**Bootstrap the dashboard** — in a terminal on the project's machine:

    # Writes docs/console/page.html with Header / Items / Rollout / Engine / Spec
    # sections and injects a matching board() into .overture/adapter.py.
    agent.py --state <STATE> scaffold-dashboard --project .

    # Insert a <details data-ck-item="X"> stub for every item not yet on the
    # page, nested under its parent. Idempotent; hand-edits inside each node
    # survive re-syncs.
    agent.py --state <STATE> items-push --adapter .overture/adapter.py \
      --sync-dashboard docs/console/page.html

    # Commit, snapshot, press "Use this page" in the console.
    git add -A && git commit -m "dashboard: scaffold + sync"
    agent.py --state <STATE> page-snapshot --path docs/console/page.html

    # Keep the live values fresh:
    agent.py --state <STATE> items-watch --adapter .overture/adapter.py

**Make it more beautiful.** The console inherits CSS custom properties from
the host page's `:root`. Define any of these to re-skin the whole kit (an
unlayered host `:root` beats the kit's `@layer console-fallbacks`):

    :root {
      --c-bg: #...;  --c-surface: #...;  --c-surface-alt: #...;
      --c-fg: #...;  --c-fg-muted: #...;
      --c-border: #...;  --c-border-light: #...;
      --c-accent: #...;  --c-accent-fg: #...;
      --c-open: #...;    --c-open-bg: #...;
      --c-claimed: #...; --c-claimed-bg: #...;
      --c-built: #...;   --c-built-bg: #...;
      --c-blocked: #...; --c-blocked-bg: #...;
      --c-deferred: #...; --c-deferred-bg: #...;
      --radius-sm: 6px;  --radius-md: 10px;
    }
    @media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) { ... } }

The 0.9.11 fallback palette is Primer-aligned (`#0969da` accent on light,
`#58a6ff` on dark) and ships `color-scheme` so native scrollbars match.
Icons are the vendored Lucide set, ISC-licensed. Then:

- Add deep links from the item view to your dashboard by setting
  `sections` in `.overture.json`:
  `{"sections": {"AB-2": ["#features/rollout", "#features/timeline"]}}`.
  The item view renders chips linking to each anchor.
- Add in-place state badges by marking any `<section data-ck-item="X">`
  on the dashboard. The console injects an `X 2 1 3 4` badge, each count
  behind its state's icon (awaiting you, unlocked, stale, locked),
  in-place, updated on every live wake; clicking it opens the panel on X.

## Project map, lanes, and the dashboard

<img src="../screenshots/feature-project-map.png" alt="The project map: every item as a tree, boxed by lane and coloured by state" width="400">

- **Project map** at the top of the Inbox: a tree of every item, parent
  to child, drawn left to right.
  - Each node is coloured by its own questions' roll-up (open > stale >
    answered-but-unlocked > locked), with a short tally.
  - Items are grouped in one box per **lane**, its border in the lane's
    colour.
  - Click an item to open it.
  - A chip row narrows the map to one state; ancestors stay drawn muted,
    so the tree is still a tree.
  - It loads lazily, like the per-item chart.
- **Lane colours.** A lane is the `lane-…` part of an item's section
  (`wave-2/phase-2.2/lane-api`). An item without one inherits its
  parent's.
  - **Where it shows:** a chip coloured by the lane, on inbox and
    Priority rows (with a matching left edge) and as a "Wave 2 › Phase
    2.2 › API" trail at the top of the item.
  - **Automatic.** Drawn from 8 colours that read at 3:1 or better in
    light and dark; two lanes share one only past 8.
  - **To pin a colour or a label,** add it to `.overture.json`:
    `"lanes": {"lane-api": {"color": "blue", "label": "API"}}`. Palette
    names only: blue, teal, green, amber, orange, red, purple or pink.
    `"ux": true` marks a lane's items as UX components for UX View and
    the console-ux skill.
  - **On your dashboard,** each item's `<details>` and each
    `data-ck-item` block gets `data-ck-lane` and `data-ck-lane-color`,
    and console.css publishes `--ck-lane-<colour>`, so your page can
    colour its own lane blocks to match.
- **Your dashboard, published by you.** The console can sit inside your
  project's own dashboard page. An agent stages a page from a merged
  commit (`agent.py page-snapshot`). The console shows it as a proposal
  with its ref, commit, size and a sandboxed preview. It is served only
  after you press **Use this page**. No agent can publish; the "reviewed"
  label is shown as the agent's claim, because the server cannot check it.
  The published page's own `<script>` tags run again under the per-request
  CSP nonce (1.32), **pinned by exact SHA-256**.

## Numbered refs, sections and the items tree

- **Sections (1.4).** An item may carry a `section` like
  `wave-2/phase-2.2/lane-api` (up to 5 slug segments). The dashboard
  scaffold makes each segment a nested `<details data-ck-section>` node,
  and a new item drops into its wave, phase and lane without you editing
  the page. An item whose parent is already on the page nests under the
  parent instead.
- **Numbered refs (1.7, 1.8).** Items get a dotted number like `1.2`,
  one level under their parent's (`1.2` under `1`), which you can use in
  chat and notes. The console assigns missing ones on `items-push`
  (`"items": {"auto_ref": false}` in `.overture.json` turns that off),
  keeps them in `STATE/refs.json`, and never reuses a retired number. The
  ref shows as a pill beside each item's id, and the command palette finds
  an item by its ref (`1` also lists `1.1`, `1.2`, …).
- **The items tree (1.9, 1.12).** A scaffolded page carries
  `<pre data-live="items_tree">`, which the console fills with every item
  by ref, indented two spaces per level. A project that sets `items_tree`
  itself in its adapter's `board()` keeps its own.
- **Rollup counts (1.12).** Each line of the tree ends with a count tail
  of the open questions on that item **and every item under it**:

  ```
  1 Rollout
    1.1 Rollout plan · ?2 !1
    1.2 Deploy script · ~1
  2 Audit
    2.1 Security pass · ?1
  ```

  `?` counts questions awaiting you, `~` answered but not locked, and `!`
  stale. A state with no questions is left out, and an item with nothing
  open under it shows no tail, so a topic says at a glance what waits
  beneath it. Locked, withdrawn and superseded questions are not counted:
  the tree says what needs you now, not what was decided.
- **Moving an item (1.17).** `agent.py item-move AB-5 --to AB-2` (or
  `--to-root`) records that you want AB-5 under AB-2, as a message on the
  item's thread that the steward picks up. Your adapter stays the source
  of truth for parents, the ref stays, and a move that would form a cycle
  is refused by name.

## Portfolio: your other consoles

The **Portfolio** tab shows one card per console: this one, and every
other Overture console you add as a peer, each with its tallies (`2 you`,
`1 unlocked`, `1 stale`, `9 locked`), how long its oldest question has
waited, a peek at the top three questions waiting for you, and a click that
opens it in a new tab. The Priority ribbon at the top of the Inbox draws on
the same peers. With no peers, the tab shows a card pointing here.

<img src="../screenshots/feature-portfolio.png" alt="The Portfolio tab: this console's card with its tallies, and the card on adding another project" width="400">

**Add a peer.** The home console reads each peer's small summary
(counts and timestamps only, never your questions' content) through the
peer's Cloudflare Access, with a service token. On the **home** console's
machine:

1. In Cloudflare Zero Trust, under Access → Service Auth, create a service
   token, and allow it in the **peer** console's Access application.
2. Write its secret to `STATE/portfolio-secrets/<peer>.json` (mode 0600,
   outside every repository): `{"client_secret": "<the secret>"}`.
3. Add the peer to `.overture/portfolio.json` in your project, with the
   token's client id and a hash that binds the secret to the peer's URL.
   `agent.py portfolio-token` prints the exact command to compute it:

```json
{"peers": {"billing": {"url": "https://billing-console.example.com",
                       "client_id": "<id>.access",
                       "token_sha256": "<sha256 of secret, a NUL byte and the url, hex>"}}}
```

The home server makes the calls, so the browser never sees a secret. A
peer URL must be `https://` of a plain host name; loopback, private and
`.local` / `.internal` names are refused, as are redirects, and a secret
that does not match its hash stops that peer, by name. At most 32 peers.
A peer behind sign-in links cannot be reached this way yet: the summary
needs Cloudflare Access on the peer.

**Notifications.** The bell on the Portfolio tab opts in to desktop
notifications, so a peer's new question or stale ruling reaches you while
the tab is in the background; **Snooze 1h** quiets them for an hour.
