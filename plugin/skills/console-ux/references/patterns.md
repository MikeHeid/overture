# Patterns: how the best systems build each component, with no JavaScript

Material 3 (Expressive), Apple HIG, Fluent 2, Carbon, Polaris, GOV.UK,
Primer, Atlassian, React Aria, Radix, Base UI and shadcn/ui agree on most of
what follows. Where they differ, this file says which to follow.

Each recipe works with **scripts off**. The **+JS** line says what to add
only when the owner has turned Scripts on.

## What the platform gives you without JavaScript (as of October 2026)

| Feature | Status | Use |
|---|---|---|
| `<dialog>` | Widely available | Dialogs. Show its open state with `<dialog open>`. |
| Invoker commands: `<button commandfor="d" command="show-modal">`, `close`, `request-close`, `toggle-popover` | Newly available (Safari 26.2, Dec 2025) | Open and close dialogs and popovers with no script. Built-in commands only. |
| `popover` + `<button popovertarget>` | Newly available (Apr 2024); widely available about now | Menus, dropdowns, toggletips. Light-dismiss and Escape for free. |
| `<details name="group">` | Newly available (Sep 2024) | Exclusive accordions. |
| `:has()` | Widely available | Parent and state styling: `.card:has(:checked)`. |
| Container queries (size) | Widely available | Components that adapt to their slot. Style queries are **not** Baseline. |
| `@layer`, CSS nesting | Widely available | Ordered, readable CSS. |
| `@scope` | Newly available (Dec 2025) | Keep component styles from leaking. |
| `oklch()`, `color-mix()` | Widely available | Perceptual colour, tints and states. |
| `light-dark()`, relative colour | Newly available (2024) | Theme pairs, derived hover and active shades. |
| Anchor positioning | Newly available (Jan 2026) | Position a popover beside its button. Give it a fallback position. |
| `@starting-style`, `transition-behavior: allow-discrete` | Newly available (Aug 2024) | Entry and exit animation of popovers and dialogs. |
| `field-sizing: content` | Newly available (Jun 2026) | Auto-growing `<textarea>` and inputs. |
| `:user-invalid` | Widely available, or close to it | Show errors only after the user has interacted with the field. |
| Same-document view transitions | Newly available (Oct 2025) | Only with script (`startViewTransition`). |
| `appearance: base-select` | **Not Baseline** (Chrome 135+) | Behind `@supports`; a native select is the fallback. |
| Scroll-driven animations | **Not Baseline** | Behind `@supports (animation-timeline: view())` only. |
| `text-wrap: balance` / `pretty` | Balance: Newly available; pretty: not Baseline | Headings: `balance`; body text: `pretty`, as a harmless extra. |

**Rule.**

- Use Widely-available features freely.
- Use Newly-available ones when the fallback still reads well.
- Put anything not Baseline inside `@supports`.

## Recipes

**Button**

- **Do:** `<button type="button" class="btn btn--primary">Save changes</button>`.
  - Hierarchy: primary, secondary, tertiary/ghost, destructive.
  - One primary per view.
  - Height 40–48px, at least 24px.
  - Show loading as a spinner plus "Saving…", without shifting the layout.
- **Disabled:** prefer `aria-disabled="true"` with a reason nearby over
  `disabled`, which can't be focused or explained. Show both in the mock.
- **+JS:** the loading state, and preventing double activation.

**Text field**

- **Do:** a visible `<label for>` above the field, then the hint, then the
  field, then the error.
  - Link the hint and error with `aria-describedby`.
  - Use the right `type` and `inputmode` (`email`, `tel`, `numeric`).
- **Errors:** style with `:user-invalid`. Show an icon and text below the
  field. For several errors, put a summary at the top (GOV.UK).
- **Textarea:** `field-sizing: content` with a `min-block-size`.

**Choice controls**

- **5 or fewer options, all worth seeing:** radios in a `<fieldset>` with a
  `<legend>`.
- **Up to 7 or so:** a native `<select>`. Style the closed control; let the
  list stay native. Add `@supports (appearance: base-select)` for a styled
  list.
- **Many, or searchable:** a combobox. That **needs JS**. With scripts off,
  show `<input list>` with a `<datalist>`, and say so in the doc.
- **Checkbox vs switch:**
  - a checkbox is part of a form, saved later;
  - a switch acts immediately: `<input type="checkbox" role="switch">`.

  Each has a large clickable label.

**Dialog**

- **Do:**
  - `<button commandfor="dlg" command="show-modal">Delete…</button>` opens
    `<dialog id="dlg" aria-labelledby="dlg-title">`.
  - It closes with `<button commandfor="dlg" command="close">`.
  - The title is the question ("Delete 3 files?"), and the primary button
    names the outcome ("Delete files").
- **Rules:** modal only for blocking decisions. Escape closes it, and focus
  returns to the trigger (native).
- **In the mock:** show the dialog open with `<dialog open>` beside the
  trigger, since the preview frame can't keep it open for the screenshot.
- **+JS:** nothing usually; native is enough.

**Popover, menu, dropdown**

- **Do:** `<button popovertarget="m" aria-haspopup="true">Options</button>`
  plus `<div id="m" popover role="menu">…</div>`.
  - Position it with anchor positioning: `position-anchor`,
    `position-area: block-end span-inline-end`, and
    `position-try-fallbacks: flip-block`.
  - Fallback: a static position under the button.
  - **Always anchor it.** An unanchored popover opens in the corner of the
    page, far from its button, which breaks Fitts and continuity:

        .trigger { anchor-name: --more; }
        .menu { position-anchor: --more; position-area: block-end span-inline-start; }
- **Entry animation:** `@starting-style` plus `transition-behavior:
  allow-discrete`, only under `prefers-reduced-motion: no-preference`.
- **+JS:** arrow-key roving focus and typeahead (APG menu pattern).

**Tooltip vs toggletip**

- A tooltip is only extra text, never essential and never interactive. On
  hover and focus it is CSS: `:hover`/`:focus-visible` on the trigger shows
  a sibling. Link it with `aria-describedby`.
- Anything clickable inside it makes it a **toggletip**: a `popover`.

**Tabs**

- **True tabs** need JS for the APG keyboard model (arrows between tabs,
  one tab stop).
- **With scripts off,** either:
  - (a) radio inputs styled as tabs, with panels shown by
    `.tabs:has(#t2:checked) .panel-2`. Say in the doc that it is a
    segmented control, not the APG tabs pattern;
  - (b) or `<details name>` stacked, when the content is long.
- **+JS:** upgrade to `role="tablist"`/`tab`/`tabpanel` with roving tabindex.

**Accordion**

- `<details name="faq"><summary>Question</summary>Answer</details>`.
- `summary` is the button.
- Show a chevron that rotates under `[open]`.

**Toast and status**

- Non-critical only, in `role="status"`. Errors are never toasts that
  disappear: they stay inline.
- Offer **Undo** instead of a confirmation dialog.
- In the mock, show the toast in place.
- **+JS:** a queue, auto-dismiss for success only, pause on hover and focus.

**Card**

- One primary link.
- The whole card is clickable through a stretched `::after` on that link.
  Secondary actions sit above it with `position: relative; z-index: 1`.
- Use the heading level that fits the page.

**Table**

- Always a `<caption>` and `<th scope>`.
- Text left-aligned; numbers right-aligned with
  `font-variant-numeric: tabular-nums`.
- Sticky header.
- Zebra stripes or a hover row.
- On narrow widths: horizontal scroll inside a labelled region
  (`role="region" aria-label tabindex="0"`), or stacked rows.

**Text that follows a choice** (no script)

- Put one `<span class="when when--x">` per option inside the label that
  changes, and show only the matching one:

      .when { display: none; }
      main:has(input[value="x"]:checked) .when--x { display: inline; }

- Hidden spans are left out of the accessible name, so "Continue with
  Organization" is read correctly.
- The worked example in
  [example-plan-picker.html](example-plan-picker.html) uses it for the
  primary button and the dialog title.

**Empty, loading, error states**

- **Empty:** an illustration (a data: image) or an icon, one line on what
  will appear, and one primary action.
- **Loading:** a skeleton matching the final layout, with a shimmer only
  under `prefers-reduced-motion: no-preference`. Below 400ms, show nothing.
- **Error:** what happened, what to do, and a retry.

**Navigation**

- Few items. Mark the current one with `aria-current="page"`.
- A skip link ("Skip to content") as the first focusable element.
- Mobile: `<details>` or a `popover` menu. Never hover-only.

**Stepper and progress**

- `<ol>` with `aria-current="step"`.
- "Step 2 of 4" in text.
- `<progress>` for determinate progress.

**AI-native patterns (emerging, 2025–2026)**

- Streaming text with a visible "thinking" status (`role="status"`).
- Suggestion chips as buttons.
- Inline citations.
- Regenerate and Edit on each answer.
- A clear confirmation before an agent acts.
- These are not settled conventions: follow the project's own lead first.

## When Scripts are on: progressive enhancement

- **Start from a version that works with scripts off.** Script adds; it
  never makes content appear.
- **Write HTML web components:**
  - a small `customElements.define('x-menu', class extends HTMLElement {
    connectedCallback() { … } })`;
  - in light DOM, wrapping the working markup, so the page CSS still
    applies;
  - with no shadow DOM unless isolation is the point.
- **Feature-detect** before using anything new:
  `'commandForElement' in HTMLButtonElement.prototype`, `CSS.supports(…)`.
- **Add only what HTML lacks:**
  - APG keyboard models (tabs, menus, listbox, grid);
  - combobox filtering;
  - toast queues;
  - `document.startViewTransition`.
- **Precedent:** Shopify Polaris moved to framework-agnostic web components
  (stable since API 2025-10), and shadcn/ui made Base UI its default
  primitives (July 2026). Mirror the project's stack in the doc, not in the
  mock.

## Sources

- Popover API: https://web.dev/blog/popover-api
- Invoker commands: https://pawelgrzybek.com/more-invoker-commands-and-more-reasons-not-to-use-javascript-please ; https://open-ui.org/components/invokers.explainer
- Exclusive accordion: https://developer.chrome.com/docs/css-ui/exclusive-accordion
- `@scope` Baseline: https://frontendmasters.com/blog/how-to-scope-css-now-that-its-baseline/
- Anchor positioning: https://web.dev/blog/web-platform-01-2026
- `@starting-style`: https://web.dev/blog/baseline-entry-animations
- `field-sizing`: https://web.dev/blog/web-platform-06-2026
- Customizable select: https://developer.chrome.com/blog/a-customizable-select
- Same-document view transitions: https://web.dev/blog/same-document-view-transitions-are-now-baseline-newly-available
- Polaris web components: https://shopify.dev/changelog/polaris-unified-web-components-are-now-available-early-access
- shadcn/ui and Base UI: https://blog.openreplay.com/shadcn-ui-radix-base-ui-switch/
