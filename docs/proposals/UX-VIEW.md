# Proposal: UX View

**The ask.** Some items are UI/UX work: a component or page being built or
deliberated on, with or without Claude design. Each of those gets a **UX View**
button next to it. The button opens a modal that shows the component with all
its styles. The modal's footer has three actions:

- **Save:** store the component as a component `.md` tied to the item, and
  update its style. A previous style, if any, is kept as a backup.
- **Generate component:** an agent makes the component.
- **Generate with input:** a chat opens to steer the component's design and
  behaviour.

When a UX item is created, it is added to the right wave, phase and lane on
the dashboard automatically.

Status: proposal, for the owner to decide.

---

## Two rules this design keeps

1. **The server never writes into the project.** It never writes a file in
   your checkout. Everything reaches the repository the way rulings and
   visuals already do:
   - the steward writes the change in its own worktree;
   - it opens a pull request;
   - you merge it.
2. **The server generates nothing.** "Generate" becomes an owner message that
   rings the doorbell. An agent does the work and posts the result back as a
   **visual**. That is the existing `/visual` route, stored in STATE and shown
   in a sandboxed frame with scripts off for HTML.

Both rules are why a ruling, a visual or a dashboard change can never come
from a repository or a web page alone.

## What already exists

| Piece | Today |
|---|---|
| Showing a component safely | An HTML **visual** (`format: html`) renders in `<iframe sandbox="">` under a strict CSP, with a parser-based sanitizer behind it (1.31). Mermaid renders in its own frame. |
| Asking an agent to draw | **Request a visual…** on an item: an owner `message` with `intent: "visual"`, answered by `agent.py visual` |
| Moving a visual into the repo | `agent.py visual-export --project <worktree>` copies it into `visuals_dir` and rewrites `INDEX.md`; the agent opens a PR |
| Talking about one item | The item's thread: an owner `message`, answered by `agent.py reply` |
| Waves, phases and lanes | An item's `section`, e.g. `wave-2/phase-2.2/lane-ui`; `items-push --sync-dashboard` inserts the item into the dashboard tree |
| Versions | Variant chips, "v3 of 7" with Prev and Next across an item's visuals (1.29) |

UX View is mostly these pieces joined behind one button, plus two new owner
intents.

## The design

### Which items get the button

An item shows **UX View** when any of these holds:

- its `section` has a `lane-ui` or `lane-ux` segment, or any segment the
  project lists under `.overture.json` → `"ux": {"lanes": [...]}`;
- the item or one of its questions is tagged `ux`:
  - an item `kind: "ux"`, a new value beside `topic` and `item`; or
  - a question with `star_by: "ux"`;
- it already has an HTML visual.

### The modal

- **Body:** the item's newest HTML visual in the same sandboxed frame, at
  full width. A size toggle switches between mobile, tablet and desktop
  widths. The light/dark switch is skipped: the frame runs no scripts, so it
  can't react to one. The variant chips step through older versions.
- **Side note:** the current saved component, if any: its path in the
  repository and the commit it came from.
- **Footer:**
  - **Save:** marks this visual as *the* component for the item. See
    "Saving" below.
  - **Generate component:** sends an owner message with
    `intent: "ux-generate"` and no extra text.
  - **Generate with input:** opens a chat pane inside the modal, which is the
    item's thread. What you type goes out as `intent: "ux-generate"` with your
    words. The agent answers in the thread and posts a new visual, which
    appears in the modal as the next version.

### Generating, the agent's side

A new skill, `console-ux`, handles `ux-generate`. It runs the same way the
existing skills handle visual requests:

1. It reads the item, its rulings, the current component file, and the
   project's design tokens (`:root` CSS custom properties, or a configured
   `ux.tokens` file).
2. It writes the component as **one self-contained HTML document**, with
   styles inline and no scripts, so it renders in the sandbox exactly as it
   will look.
3. It posts the document with `agent.py visual --format html`.
4. If Claude design is available in the session, the skill may use it to
   draft. What it posts is still a plain HTML visual.

### Saving

**Save** writes no files itself. It records the owner's choice and lets the
steward carry it into the repository:

1. It sends an owner message with `intent: "ux-save"` and the visual's id.
   The choice is in the audit trail like any other owner act.
2. The steward runs `agent.py ux-export --project <worktree>`, an extension of
   `visual-export`. That command:
   - writes `components/<item>.md`: front matter (item, visual id, source
     commit, saved-by, date), a short description, and the component HTML in
     a fenced block;
   - writes `components/<item>.css` when the component carries a style block;
   - moves a component or CSS file that already exists to
     `components/.history/<item>-<timestamp>.md` (and `.css`) first. **This
     is the backup of the old style.**
   - opens a pull request.
3. The modal shows "Saved, waiting for PR #…", then "Saved in `<path>`" once
   the steward's next `prs-push` shows the PR merged.

The `components/` location can be changed with `.overture.json` →
`"ux": {"dir": "..."}`.

### Placing a new UX item on the dashboard

When a UX item is created (from Launch Idea, Branch Out, or the adapter), the
steward:

1. **Picks the section.** It uses the parent's wave and phase plus
   `lane-ui`. If the parent has no section, it uses the newest open wave and
   phase on the board.
2. **Sends it through the adapter.** The item list belongs to the project's
   adapter, so the steward writes the section there, or proposes it as a
   question when the adapter can't.
3. **Updates the board.** It runs
   `items-push --sync-dashboard docs/console/page.html`. That inserts the
   item's `<details>` under the right wave, phase and lane, and you publish
   the page with **Use this page** as usual.

"Automatically" means without you doing anything, but still by the steward,
reviewed and published by you. The server never edits the dashboard.

## What it takes

| Part | Size |
|---|---|
| The **UX View** button and modal: frame, size toggle, versions, footer | console.js and css, medium |
| `ux-generate` and `ux-save` intents, plus the `kind: "ux"` item kind | schema, small; tests |
| The modal's chat pane, reusing the item thread | console.js, small |
| The `console-ux` skill: generation | skill, medium |
| `agent.py ux-export`: component md and css with a dated backup, then a PR | agent.py, medium; tests |
| Lane placement in the steward's Launch Idea and Branch Out handling | skill and adapter guidance, small |
| README screenshots and GIF | demo script |

This is about two PRs: first the modal, intents and export, then generation
and lane placement.

## Decisions for the owner

1. **Format:** a component is one self-contained HTML document, with inline
   styles and no scripts. Is that right, or do you want framework code
   (React or similar) saved alongside it, with the HTML as its preview?
2. **Where:** `components/<item>.md` plus `.css`, backups under
   `components/.history/`. Or somewhere else?
3. **Which items:** lane `lane-ui`/`lane-ux` plus `ux` tags, as above. Should
   the lanes be configurable per project?
4. **Saving:** through the steward and a PR (recommended, keeps the trust
   model). Or is a faster path that skips the PR worth discussing?
