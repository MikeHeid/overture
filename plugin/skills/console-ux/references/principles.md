# Principles: what a world-class component gets right

These are rules, not background reading. Each line says what to do in the
component. Researched 2026-10-11. Sources are at the end.

## Accessibility: WCAG 2.2 AA is the floor

WCAG 3 is still a working draft (March 2026), and its contrast method is
undecided. APCA is **not** in it. So contrast is measured with WCAG 2.2
ratios. Use APCA only as an extra check on readability.

| Criterion | What it means in the component |
|---|---|
| 1.4.3 Contrast (text) | 4.5:1 for body text; 3:1 for large text (24px, or 18.66px bold). Check light **and** dark. |
| 1.4.11 Non-text contrast | Input borders, focus rings, icons and switch tracks are 3:1 against their background. |
| 1.4.10 Reflow | Works at 320 CSS px with no sideways scroll. |
| 1.4.12 Text spacing | Survives 1.5 line height, 2× paragraph spacing and wider letter and word spacing. No fixed heights on text. |
| 2.4.7 / 2.4.13 Focus | `:focus-visible` ring at least 2px with 3:1 contrast. Never remove the outline without a replacement. |
| 2.4.11 Focus not obscured | Sticky headers and footers never cover the focused element. Use `scroll-padding`. |
| 2.5.8 Target size | At least 24×24 CSS px, or spaced so a 24px circle around it touches nothing else. Primary actions on touch: 44×44. |
| 2.5.7 Dragging | Anything draggable has a click or tap alternative. |
| 3.3.1 / 3.3.3 Errors | Name the field and the fix. Never use colour alone; add an icon or text. |
| 3.3.7 Redundant entry | Don't ask twice for what the user already gave. |
| 2.3.3 Motion (AAA, still do it) | Animation from interaction can be turned off with `prefers-reduced-motion`. |

**ARIA.**

- Use the native element first. "No ARIA is better than bad ARIA."
- `<button>`, `<dialog>`, `popover`, `<details>` and `<select>` give the
  roles, focus handling and Escape behaviour for free.
- Add ARIA only for what HTML can't say:
  - `aria-describedby` for hints and errors;
  - `aria-current="page"` for the current page;
  - `aria-invalid` for a failed field;
  - `aria-live` for status.
- Follow the WAI-ARIA Authoring Practices pattern for each widget (see
  `patterns.md`).

**User preferences.** Honour all of these:

- `prefers-color-scheme`, via `color-scheme: light dark` and `light-dark()`;
- `prefers-reduced-motion`: swap movement for opacity, or for nothing;
- `prefers-contrast: more`: stronger borders and text;
- `forced-colors: active`:
  - use system colours (`Canvas`, `CanvasText`, `ButtonText`, `Highlight`);
  - give elements a `transparent` border or outline so their edges stay
    visible;
  - never let a background or a box-shadow carry meaning.

## Psychology: the laws of UX, applied

| Law | Apply it like this |
|---|---|
| **Fitts** | The primary action is big and near where the eye and hand already are. Destructive actions are small and away from it. |
| **Hick** | Fewer choices at once. Disclose progressively: an "Advanced" `<details>`, a "More" menu. |
| **Jakob** | People expect your UI to work like the ones they already know. Use conventions (logo top-left, search with a magnifier, ✕ to close) unless there's a measured reason not to. |
| **Miller** | Chunk information into groups of a few related items. It isn't a hard limit of 7. |
| **Doherty threshold** | Respond within 400ms. Otherwise show a skeleton or progress at once. |
| **Tesler** | The system absorbs the complexity: smart defaults, formatting tolerant of input ("4111 1111…" or "41111111…"). |
| **Aesthetic-usability** | Polish makes people forgive more. Use it, but don't let it hide a broken flow. |
| **Von Restorff** | Make the one thing that matters look different (the primary button, the recommended plan). Only one per view. |
| **Serial position** | The most important items go first and last in lists and navigation. |
| **Peak-end** | Design the best moment and the ending: a clear success state, a kind empty state, an undo. |
| **Goal-gradient** | Show progress in multi-step flows ("Step 2 of 3"); people speed up near the end. |
| **Zeigarnik** | Show what's unfinished (checklists, "3 of 5 done") so it pulls people back. |

**Nielsen's 10 heuristics.** Before posting, check the component against
each one:

1. Visibility of system status.
2. Match with the real world.
3. User control and freedom (undo, cancel).
4. Consistency.
5. Error prevention.
6. Recognition over recall.
7. Flexibility (shortcuts).
8. Minimalist design.
9. Help users recover from errors.
10. Help.

**Gestalt.**

- Show grouping with **space first**, then a shared background, then a
  border, and only then a line.
- Similar things look alike.
- Things that act together sit together.

**Cognitive load.**

- Forms are one column.
- Labels sit above their fields.
- Use defaults that are right for most people.
- Ask only for what's needed now.

**Error prevention.**

- Constrain input (`type`, `min`/`max`, `inputmode`) rather than scold.
- Confirm only destructive or irreversible actions, and name the outcome:
  "Delete 3 files?". Better still, offer undo.

## Microcopy

- **Buttons** start with a verb and say the outcome: "Save changes", "Send
  invite". Not "OK" or "Submit".
- **Sentence case** everywhere.
- **Errors** say what happened and how to fix it, without blame: "Enter a
  date after today", not "Invalid date".
- **Labels are always visible.** A placeholder is an example, never the
  label.
- **Empty states** say what will appear here and offer one action to get
  there.
- **Numbers and dates** use the user's format, with units.

## Sources

- WCAG 2.2, what's new: https://www.w3.org/WAI/standards-guidelines/wcag/new-in-22/
- WCAG 3 draft status: https://www.w3.org/WAI/news/2026-03-03/wcag3
- WCAG 3 contrast status: https://adrianroselli.com/2026/04/wcag3-contrast-as-of-april-2026.html
- WAI-ARIA Authoring Practices: https://www.w3.org/WAI/ARIA/apg/patterns/
- Laws of UX: https://lawsofux.com
- Nielsen's 10 heuristics: https://www.nngroup.com/articles/ten-usability-heuristics/
