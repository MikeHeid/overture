# Proposal: screenshots and assets in the Feed

**The ask.** When an agent works on an item, its screenshots and recordings
should show up in the **Feed** and on the item, the same way this session's
before-and-after shots were shown while the icons were built. The owner sees
what changed without opening a branch.

Status: proposal. Three small choices are open, F1–F3 at the end.

---

## What exists, and why it doesn't cover this

- **Visuals** are Mermaid or HTML only.
- An agent can post a visual only in reply to an owner's visual request, at
  most 3 per request (`schema.py` `VISUAL_FORMATS`,
  `MAX_VISUALS_PER_REQUEST`).

A screenshot is neither format, and nobody asked for it. So it needs its own
small record type.

## The design

### An `asset` record

An agent posts it on its own, through the agent door with its project token:

    agent.py asset --item UI-2 --file after.png --caption "Tabs with icons, 515px dock" \
        [--kind before|after|screenshot|recording] [--qid UI-2/Q1] [--pr 131] [--ticket T-4]

| Field | Rule |
|---|---|
| `item` | An item the project lists; the record is refused otherwise, like tickets |
| `format` | `png`, `jpeg`, `webp` or `gif`, decided from the file's **magic bytes**, never its name. No SVG: it can carry script. |
| `bytes` | At most 2 MiB for a still image, 8 MiB for a GIF |
| width, height | Read from the header with the standard library; at most 8000 × 8000 |
| `caption` | One line, at most 200 characters |
| `kind` | `before`, `after`, `screenshot` or `recording` |
| links | Optional `qid`, `pr` and `ticket`, each checked to exist |
| `sha256`, `by`, `nonce` | As for visuals |

- The file is stored in STATE (`STATE/assets/<sha256>.<ext>`), never in the
  project.
- The same bytes posted twice are stored once.

### Serving it

`/api/asset?id=…` sends the stored bytes:

- with the `Content-Type` named by the magic bytes, and
  `X-Content-Type-Options: nosniff`;
- under `Content-Security-Policy: sandbox; default-src 'none'`, so opening it
  in its own tab runs nothing;
- with `Cache-Control: private, immutable`, since the id is the content's
  hash.

The console shows assets as `<img>` on the same origin, so nothing outside
the console is loaded.

### In the Feed

- A new **Assets** kind in the Feed's kind filter.
- Each asset is a card:
  - a thumbnail, lazy-loaded, at most 180px tall;
  - the caption;
  - the item chip, and the agent and time;
  - its `before`/`after` label;
  - links to its question, PR or ticket.
- A `before` and an `after` posted together for the same item are shown side
  by side.
- Clicking opens a lightbox, using the fragment viewer's pattern. It steps
  ◂ ▸ through that item's assets and closes on Escape, returning focus to
  the card.
- **Motion.** A GIF starts as a still with a ▶ play button under
  `prefers-reduced-motion: reduce`. Otherwise it plays inline.

### On the item

An **Assets** fold under the item's questions holds a gallery of its assets,
newest first. The fold is shown only when the item has assets.

### Agents posting them

- The `console-*` skills get one line: after changing anything visible,
  post a `before` and an `after` with `agent.py asset`.
- The screenshot harness used here (`docs/demo/screenshots.py`) is how this
  repo makes them. Any Playwright run works.

### Limits

| Limit | Value |
|---|---|
| Per agent | 30 assets in 10 minutes; more is refused by name |
| Per item | 100 assets |
| Per project | 300 MiB in STATE (see F1) |

- `health` (D1) reports how much space assets use.
- Only the owner can delete an asset: an owner route, with CSRF and the
  Access JWT like every owner POST.

## What it takes

1. **Schema and store.**
   - The `asset` record and its checks.
   - Format, size and dimension checks from magic bytes, in the standard
     library only.
   - Tests in `test_server.py`, including a `.png` name on a non-PNG file,
     an SVG, an oversized file and an unknown item.
2. **Routes.**
   - The agent door's `/asset`.
   - The owner's `/api/asset` and `/api/asset-delete`.
   - Tests: headers, owner-only delete, no route for agents to read
     another project's assets.
3. **`agent.py asset`**, and the one line in each `console-*` skill.
4. **The console**: the Feed card and filter, the lightbox, the item's
   Assets fold, and the motion rule. Screenshots and a GIF in the README.

Rollback: an older kit refuses a store with `asset` records, by name. The
CHANGELOG says so.

## Open choices

- **F1. When the project's asset space is full.**
  - **A ★** Delete the oldest assets that are not starred or linked to a
    PR, and record that in the Feed.
  - **B** Refuse new assets until the owner deletes some.
- **F2. The owner attaching images too** (pasting into an item's thread).
  - **A ★** Later, as its own PR.
  - **B** In the same PR.
- **F3. Posting by default.**
  - **A ★** Skills post a before and an after for every change to a UX item
    and for UI fixes.
  - **B** Only when the owner asks.
