# The gate: every version passes all of this before it is posted

Fix each failure; don't explain it away in the doc. A box you can't satisfy
(for example a combobox that needs script) is named in the doc's "Open
questions".

## Rules the server enforces (it refuses or strips anything else)

- [ ] One HTML document, under 256 KiB, with styles in a `<style>` block
      and no `style=""` attributes.
- [ ] With Scripts off: no `<script>`, no `on*` attributes, and it still
      works and shows every state.
- [ ] Nothing external: no URLs to fonts, images, stylesheets or scripts.
      Images and fonts are `data:` only.
- [ ] Only allowed elements and attributes (SKILL.md, step 4). There is no
      `<form>`, `<svg>`, `formaction`, `autofocus`, or `type="file"` or
      `"image"`.
- [ ] Nothing that imitates a real company, a login, or a payment page.

## Design

- [ ] The job and its success signal are stated, and the component serves
      them.
- [ ] One primary action. The others are visibly secondary (Hick, Von
      Restorff).
- [ ] Every state is shown:
  - [ ] default, hover, focus-visible, active, disabled;
  - [ ] loading, empty, error, success;
  - [ ] long text and the narrowest width.
- [ ] Uses the project's tokens, or invented three-tier tokens, which the
      doc says were invented.
- [ ] Conventions are followed unless the doc says why not (Jakob).
- [ ] Any trend used is on the "durable" or "use with care" list, with its
      guardrails.

## Accessibility (WCAG 2.2 AA)

- [ ] Text contrast is at least 4.5:1 (3:1 for large text), in light
      **and** dark. The pairs are listed in the doc.
- [ ] Borders, icons and focus rings are at least 3:1.
- [ ] `:focus-visible` ring at least 2px wide, never hidden by sticky
      elements.
- [ ] Targets at least 24×24px; primary touch targets at least 44×44px.
- [ ] Native elements used first; ARIA only where HTML can't say it, and
      used correctly.
- [ ] Every control has a visible label. Hints and errors are linked with
      `aria-describedby`.
- [ ] Errors are text plus an icon, never colour alone.
- [ ] Keyboard: the tab order follows the visual order, and every action
      can be reached and triggered with the keyboard.
- [ ] Reflow at 320px with no horizontal scroll, and container queries
      where the component's slot varies.
- [ ] `prefers-reduced-motion`, `prefers-contrast` and `forced-colors` are
      handled.

## Code

- [ ] Semantic HTML; headings in order; `lang` on `<html>`.
- [ ] CSS is ordered (`@layer` or a clear order), with no `!important`
      except in forced-colours fixes.
- [ ] Features that aren't Baseline sit inside `@supports`, and the
      fallback reads well.
- [ ] Realistic content, including a long name, a big number and an empty
      list.
- [ ] Every popover is anchored to its trigger (`anchor-name` /
      `position-anchor`), never left in the page corner.
- [ ] Labels that name the current choice follow it (`:has(:checked)`
      spans), so the mock never says "Team" while "Organization" is
      picked.
- [ ] `ux_check.py` exits 0: nothing stripped. The screenshots at 375, 768
      and 1280px, light and dark, have been looked at.
- [ ] With Scripts on: it still works with JS disabled; the script is plain
      JavaScript with no network, with storage in try/catch, and never
      posts to the parent.

## The doc

- [ ] It has these sections, in order: What it is, Decisions, States shown,
      Accessibility, Maps to your stack, Open questions.
- [ ] Each open question is also posted with console-ask.
