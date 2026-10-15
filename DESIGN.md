# Design — The Floor

The visual world of the trading cockpit, written from the built result.

The product is one trader's decision surface, read in short glances during a
live session beside a broker window and charts. Everything below serves that:
density, one monumental answer, and colour used so sparingly that when it
appears it means something.

## Thesis

A cockpit read in glances is a **quote board**, not a dashboard of cards.

It refuses the two arrangements this category always ships: the grid of
same-size bordered cards with six accent hues (what this app was), and its
predictable opposite, the black-and-neon terminal pastiche.

## The world

The open-outcry exchange as a physical place.

| Material | Role |
|---|---|
| Painted steel board | every surface — flat plates, no shadow, 3px corners |
| Chalk | all text. Warm off-white, never `#fff` |
| Brass | section rules and the session rail. A warm **neutral**, never an accent |
| Enamel | the only saturated marks: valence, and the pit badge |

Dark is primary. That is a use-scene decision, not a category one: one trader,
one desk, a full session under room light, reading for hours. A dark painted
board holds the enamel marks and does not glare at hour six. Light mode is the
same board in daylight — pale pigment, graphite figures — not a white UI.

## Colour

Three disjoint roles. A colour never means two things.

- **VALENCE** — green / red / amber. Market direction, P&L, agent health. Data,
  never decoration. **Zero is neutral**: a flat $0.00 is `ink3`, not green. A
  fresh account showing four green zeroes is four valence marks carrying no
  direction, which is the exact noise this palette exists to remove.
- **IDENTITY** — the pit badge. A narrow cool ramp (hues ~205–195), well clear
  of the valence band, so a badge can never read as up, down or warning. Alpha
  Wolf heads the family at the highest chroma; the pack steps down and cools
  beneath it. This renders the product hierarchy as colour, which is a binding
  product commitment.
- **NEUTRAL** — `ink` → `ink4`, all four body-text legible. `ink4` alone carries
  ~150 text nodes; it is a readable tier, not a wash.

Strategy: **Restrained**, which is the floor for an Operate surface. Identity
lives in a 20px enamel chip, not in a tinted panel plus a coloured border plus a
matching heading — that containment is what lets the rest of the board stay
chalk and brass.

Every value is verified ≥4.5:1 against all four surfaces of its mode, against
its own `*Bg` tint, and against a tint of itself (the `col + "18"` chip
pattern). Green is always lighter than red so the pair survives deuteranopia by
lightness; the ▲/▼ carries the shape cue.

## Type

**Archivo**, one family, worked across its width axis (62.5–125).

An Operate surface does not need a display/body pairing — it needs one
well-tuned face carrying headings, labels, controls, body and data. Archivo is
a signage grotesque with a real `wdth` axis and true tabular lining figures, so
monumental board numerals, UI text and condensed table headers all come out of
one face. It replaced Hanken Grotesk + JetBrains Mono: two voices doing what
one, worked harder, does more cleanly.

Width carries hierarchy that size cannot on a dense screen — condensed headers
buy horizontal room in tables, expanded numerals give the board figure presence
without another 10px of height.

| Token | px | Use |
|---|---|---|
| `board` | 44 | **One element per screen.** The live call |
| `display` | 28 | page title |
| `title` | 20 | a directive that is not an instruction |
| `head` | 16 | block heads |
| `body` | 13.5 | prose |
| `dense` | 12.5 | table data |
| `label` | 11.5 | pills, section heads |
| `micro` | 10.5 | stat labels, captions |

Fixed px, ratio ~1.2. Fluid clamps buy nothing at one desk and one DPI, and
make a sidebar heading shrink for no reason.

Figures are tabular everywhere (`font-variant-numeric` on `body`). Every number
here is a measurement that re-renders on a poll; proportional digits make a
whole price column jitter on each tick.

## Structure

- **Plates, not cards.** Flat, 3px corners, no border, no shadow. Separation
  comes from the plate's own ground and the page gutter. Twelve bordered
  rounded boxes stacked down a page is what made the app read as containers
  first and data second.
- **Rules, not boxes.** A section is a region of the board underscored in
  brass, not another container.
- **The session rail** is solid, with a brass bottom edge. Not frosted glass:
  blur-as-decoration muddied every figure that scrolled beneath it.
- **The ground** is static paint tooth — a 45° hairline hatch at ~2% contrast
  plus a soft vignette. It replaced four animated blurred colour blobs that, in
  dark mode, put the equity figures on a moving cloud.

## Icons

One drawn set, `theme/icons.jsx`: 24-unit grid, 1.6 stroke, round caps and
joins, `currentColor`. The stroke stays 1.6 at every size on purpose — scaling
it with the box is what makes one icon set look like three.

No emoji. Emoji put another illustrator's artwork, in another style and weight,
rendered differently per OS, beside hand-tuned type and a measured palette.

## The pit badge

A two-letter acronym on enamel (`AW`, `WW`, `TG`). It is how a floor identifies
a trader at distance, and it is the device that lets colour stay as contained
as it is: identity is a glyph on a chip, so panels, headings and borders can all
stay neutral.

## What is deliberately kept

- The sidebar collapse animates `width`. The detector flags it; it is the one
  layout animation in the app, user-initiated, running once for 220ms, and
  there is no transform equivalent for a reflow that resizes the main column.
- `T.violet` and `T.mono` keep their key names. `violet` is now the badge
  enamel and `mono` resolves to Archivo; renaming either would touch ~200 call
  sites for no visual gain.
