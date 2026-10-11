# Style: tokens, the visual system, and which trends to use

## Tokens first

**Use the project's tokens.** Look for a W3C design-tokens file (the
Design Tokens Format Module 2025.10, stable since October 2025: JSON with
`$value`, `$type`, and aliases like `"{color.blue.500}"`), Tailwind
`@theme`, or `:root` custom properties.

When there are none, emit three tiers as custom properties, and say in the
doc that you invented them:

1. **Primitive:** raw values. `--blue-600: oklch(0.55 0.2 260)`.
2. **Semantic:** named by purpose, not by value. `--color-bg-surface`,
   `--color-text-muted`, `--color-border-focus`,
   `--color-action-primary-bg`. Dark mode and high contrast override
   **only this tier**.
3. **Component:** local to the component. `--btn-primary-bg:
   var(--color-action-primary-bg)`.

**Naming:** category, property, variant, state. For example
`--color-bg-danger-hover`.

## The visual system

**Type.**

- System stack:
  `font-family: system-ui, -apple-system, "Segoe UI", Roboto, sans-serif`.
- Use a fluid scale via `clamp()`.
- Body 16px at least. Line height 1.5 for body, 1.1–1.25 for headings.
- Measure 45–75 characters.
- `text-wrap: balance` on headings.
- A custom font only as a `data:` URI, and only when the brand needs it:
  it costs file size, against the 256 KiB cap.

**Colour.**

- Define colours in `oklch()`. Derive hover and active shades with relative
  colour or `color-mix()` instead of picking new hexes.
- One accent colour for the primary action (Von Restorff).
- Status colours (success, warning, danger, info) always come with an icon
  or a word.
- Dark mode is first-class: `color-scheme: light dark`, and semantic tokens
  through `light-dark()`. In dark mode:
  - surfaces are dark grey, not pure black;
  - elevation means a lighter surface, not a shadow;
  - accents are desaturated.

**Space and shape.**

- A 4px base grid (4, 8, 12, 16, 24, 32, 48).
- Spacing does the grouping before borders do (Gestalt).
- One radius scale (for example 4 / 8 / 12 / pill), used the same way
  across the component.

**Elevation.** Two or three shadow levels at most, soft and low-contrast. In
forced-colours mode a border takes their place.

**Motion.**

- 150–300ms for UI feedback.
- Ease-out for entering, ease-in for leaving.
- Springy overshoot (M3 Expressive) only on small, playful moments.
- Always inside `@media (prefers-reduced-motion: no-preference)`.
- Motion never carries meaning alone.

## Trends, 2025–2026: use, use with care, avoid

| Look | Verdict | How to use it |
|---|---|---|
| **Bento grids** | Durable | Feature and dashboard sections. CSS grid with `subgrid` and container queries; cards of 2–3 sizes. |
| **Dark mode as first-class** | Durable | Tokens plus `light-dark()`; design both, measure both. |
| **Expressive type** (large display, variable weight) | Durable | Headings and empty states. Material 3 Expressive reports key actions found up to 4× faster with bolder emphasis. Keep body text calm. |
| **Purposeful motion** | Durable | Feedback and continuity; short; reduced-motion safe. |
| **OKLCH gradients** | Use with care | Subtle backgrounds and hero accents. OKLCH avoids the muddy grey middle. Never under body text. |
| **Glass / Liquid Glass** (translucent, blurred chrome) | Use with care | Only on chrome (toolbars, sticky headers) over controlled backgrounds. Check 4.5:1 against the **worst** backdrop. Give a solid fallback under `prefers-reduced-transparency` and `prefers-contrast: more`. Apple's iOS 26 legibility backlash, with contrast measured as low as about 1.5:1, is the warning. |
| **Neo-brutalism** (thick borders, hard shadows) | Accents only | One call-to-action or badge, not a whole page. |
| **Spatial / depth UI** | Niche | Layering for focus (a dialog over a dimmed page) is fine; 3D chrome is not. |
| **AI-native surfaces** | Emerging | Streaming and status, chips, citations, regenerate. Match the product's tone. |

**The tie-breaker.** When a trend fights clarity, clarity wins. Jakob's law:
people spend most of their time in other products. Novelty has to earn its
place.

**Three versions per request.** When the owner hasn't set a direction, use
them to show a real range:

- **Calm:** the conventional, system-aligned version.
- **Expressive:** one durable trend, pushed further.
- **Dense:** for power users and data-heavy screens.

## Sources

- Design Tokens Format Module 2025.10: https://www.w3.org/community/design-tokens/2025/10/28/design-tokens-specification-reaches-first-stable-version/
- Material 3 Expressive: https://www.androidauthority.com/google-material-3-expressive-features-changes-availability-supported-devices-3556392/
- Liquid Glass accessibility: https://infinum.com/blog/apples-ios-26-liquid-glass-sleek-shiny-and-questionably-accessible/
- 2026 trends, a reality check (opinion): https://studiomeyer.io/en/blog/webdesign-trends-2026-reality-check
