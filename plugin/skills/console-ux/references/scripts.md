# Scripts: progressive enhancement, once the owner's switch ships

**Status: shipped (1.33).** Scripts are always stripped from the visual you
post. A script reaches the owner only as a separate **scripted source** for
that visual, and runs only while the owner's per-version **Scripts** switch
is on (UX View, Settings). Post it after the visual:

    A component-source --visual VISUAL_ID --file scripted.html

It is write-once for that visual (a different source is refused), so a
version the owner switched on cannot change under them. The visual you posted
stays the no-script version; the source is its progressive enhancement and
must contain the same working HTML. The owner turns it on at their end; if
they save with it on, `ux-export` lands the scripted source with `scripts:
true` in the front matter.

## The rule: enhance, never depend

- The HTML and CSS version from SKILL.md step 4 must still work with
  JavaScript disabled. Script only adds what HTML lacks:
  - the WAI-ARIA keyboard models (roving focus in tabs, menus, listboxes,
    grids);
  - combobox filtering;
  - toast queues;
  - `document.startViewTransition`.
- Never make content depend on script to become visible.

## How to write it

- **One `<script>` at the end of `<body>`.** Plain JavaScript: no
  framework, no build step, no imports.
- **Prefer an HTML web component.** A small `customElements.define` class
  in light DOM that wraps markup which already works, wired in
  `connectedCallback`, with event delegation. Shopify Polaris's move to web
  components (stable since API 2025-10) is the precedent.
- **Feature-detect before using anything new:**
  `'commandForElement' in HTMLButtonElement.prototype`, `CSS.supports(…)`.

## The frame is sealed

The component runs in `sandbox="allow-scripts"` with no
`allow-same-origin`, under `default-src 'none'`. Code for that:

- **No network.** Every request fails. Never fetch.
- **No storage.** The origin is opaque, so `localStorage` throws. Wrap any
  use in try/catch.
- **No parent.** Never `postMessage` to `parent`; the console accepts
  messages only from its own chart frames.
- **No popups, top navigation or form submission.** The sandbox doesn't
  allow them.
