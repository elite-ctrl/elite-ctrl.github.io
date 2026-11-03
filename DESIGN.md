---
name: LedgerLex Language Studio
description: Near-white field (#FFFFFB) neo-brutalist marketing site for the Hong Kong financial translation desk.
colors:
  paper: "#FFFFFB"
  surface: "#FFFFFF"
  ink: "#000000"
  yellow: "#FFE566"
  accent: "#FF4D1A"
  muted: "#666666"
  white: "#FFFFFF"
  nav-bar: "rgba(255, 255, 251, 0.92)"
  footer-ink: "#181818"
  footer-meta: "#9B9B9B"
typography:
  display:
    fontFamily: "JetBrains Mono, Consolas, Cascadia Code, Menlo, Monaco, Liberation Mono, Courier New, monospace"
    fontSize: "60px"
    fontWeight: 800
    lineHeight: 1.05
    letterSpacing: "-0.03em"
  display-md:
    fontFamily: "JetBrains Mono, Consolas, Cascadia Code, Menlo, Monaco, Liberation Mono, Courier New, monospace"
    fontSize: "48px"
    fontWeight: 800
    lineHeight: 1.05
    letterSpacing: "-0.03em"
  headline:
    fontFamily: "JetBrains Mono, Consolas, Cascadia Code, Menlo, Monaco, Liberation Mono, Courier New, monospace"
    fontSize: "36px"
    fontWeight: 800
    lineHeight: 1.11
    letterSpacing: "-0.02em"
  headline-sm:
    fontFamily: "JetBrains Mono, Consolas, Cascadia Code, Menlo, Monaco, Liberation Mono, Courier New, monospace"
    fontSize: "30px"
    fontWeight: 800
    lineHeight: 1.2
    letterSpacing: "-0.02em"
  title:
    fontFamily: "JetBrains Mono, Consolas, Cascadia Code, Menlo, Monaco, Liberation Mono, Courier New, monospace"
    fontSize: "24px"
    fontWeight: 800
    lineHeight: 1.2
  article-title:
    fontFamily: "JetBrains Mono, Consolas, Cascadia Code, Menlo, Monaco, Liberation Mono, Courier New, monospace"
    fontSize: "20px"
    fontWeight: 800
    lineHeight: 1.2
  body-lg:
    fontFamily: "JetBrains Mono, Consolas, Cascadia Code, Menlo, Monaco, Liberation Mono, Courier New, monospace"
    fontSize: "18px"
    fontWeight: 600
    lineHeight: 1.56
  body:
    fontFamily: "JetBrains Mono, Consolas, Cascadia Code, Menlo, Monaco, Liberation Mono, Courier New, monospace"
    fontSize: "16px"
    fontWeight: 600
    lineHeight: 1.5
  label:
    fontFamily: "JetBrains Mono, Consolas, Cascadia Code, Menlo, Monaco, Liberation Mono, Courier New, monospace"
    fontSize: "14px"
    fontWeight: 700
    lineHeight: 1.43
  eyebrow:
    fontFamily: "JetBrains Mono, Consolas, Cascadia Code, Menlo, Monaco, Liberation Mono, Courier New, monospace"
    fontSize: "12px"
    fontWeight: 700
    lineHeight: 1.33
    letterSpacing: "0.06em"
  numeral:
    fontFamily: "JetBrains Mono, Consolas, Cascadia Code, Menlo, Monaco, Liberation Mono, Courier New, monospace"
    fontSize: "40px"
    fontWeight: 800
    lineHeight: 1
  display-404:
    fontFamily: "JetBrains Mono, Consolas, Cascadia Code, Menlo, Monaco, Liberation Mono, Courier New, monospace"
    fontSize: "72px"
    fontWeight: 800
    lineHeight: 1
rounded:
  sharp: "0px"
  dot: "50%"
spacing:
  step-4: "4px"
  step-8: "8px"
  step-12: "12px"
  step-16: "16px"
  step-24: "24px"
  step-32: "32px"
  step-40: "40px"
  step-48: "48px"
  step-64: "64px"
components:
  button-primary:
    backgroundColor: "{colors.yellow}"
    textColor: "{colors.ink}"
    rounded: "{rounded.sharp}"
    padding: "12px 24px"
    typography: "{typography.label}"
  button-primary-hover:
    backgroundColor: "{colors.yellow}"
    textColor: "{colors.ink}"
    rounded: "{rounded.sharp}"
    padding: "12px 24px"
  button-cream:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    rounded: "{rounded.sharp}"
    padding: "12px 24px"
    typography: "{typography.label}"
  eyebrow:
    backgroundColor: "{colors.yellow}"
    textColor: "{colors.ink}"
    rounded: "{rounded.sharp}"
    padding: "4px 8px"
    typography: "{typography.eyebrow}"
  proof-chip:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    rounded: "{rounded.sharp}"
    padding: "8px 12px"
    typography: "{typography.label}"
  card:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    rounded: "{rounded.sharp}"
    padding: "32px 24px"
---

# Design System: LedgerLex Language Studio

## Overview

**Creative North Star: "Neo-brutalist marketing HTML"**

The public site is sharp type on a near-white field (#FFFFFB). Blocks are rectangles with thick black borders and hard offset shadows that do not blur. Yellow carries the main button, eyebrows, and proof chips. A hot accent is reserved for small stamps, dots, and the focus ring. One monospace face does every job on the public pages.

This file records the CSS the live HTML already ships. It does not restyle those pages. Brand locks override Impeccable skill defaults. Carbon and Hex, recorded under Colors, are house palettes. They are not a license to recolor this site.

Homepage sections are centre-aligned. Journal pages keep a left-aligned reading column under a centred header. The homepage hero is offer-first and creative. It does not open as an HKEX, listings, or filings frame.

**Key Characteristics:**

- Sharp rectangles with a 3px black border
- Hard offset shadows, zero blur
- Near-white field (#FFFFFB), yellow action, hot accent, black ink
- One public face: JetBrains Mono
- Centre-aligned homepage
- Brand locks beat skill defaults

## Colors

The live public pages share one near-white neo-brutalist set. `theme-color` on the home page is the same #FFFFFB as the page field.

### Primary

- **Desk Yellow** (`{colors.yellow}`): Main buttons, eyebrows, yellow bands, and the preferred side of a comparison. It is the action color.

### Secondary

- **Stamp Accent** (`{colors.accent}`): Small stamps, accent dots, and the 3px focus ring. The hero stamp sets white type on this fill. That pairing is in the live CSS and fails a WCAG AA contrast check. This record does not adopt it as the target pairing.

### Neutral

- **Page Field** (`{colors.paper}`): Page field and `theme-color`. This is #FFFFFB, a near-white. It is not Hex paper.
- **Raised Surface** (`{colors.surface}`): Cards, chips, and the secondary button. #FFFFFF so they still lift a hair off the #FFFFFB field.
- **Ink** (`{colors.ink}`): Text, borders, and shadow color.
- **Muted Ink** (`{colors.muted}`): Ledes and secondary lines. Muted type sitting on Desk Yellow is in the live CSS and reads as gray on a colored ground. This record does not adopt that pairing as the target.
- **White** (`{colors.white}`): The “wrong” comparison cell, and the hero stamp’s type.
- **Nav Scrim** (`{colors.nav-bar}`): The sticky nav fill. It is the page field at 92% opacity.
- **Footer Ink** (`{colors.footer-ink}`) and **Footer Meta** (`{colors.footer-meta}`): The 404 footer bar only. Other pages do not use this dark footer.

### House palettes

These tracks are locked house color. They are not the public site’s current CSS. Do not recolor the live pages onto them unless Louis asks.

**Carbon** (desk/dark track; was Smash; Louis 2026-10-30, rename 2026-11-01): field `#111111`, yellow `#FEDA56`, pink `#E83462`, blue `#55B9EA`, white `#FFFFFF`.

**Hex** (paper track): paper `#FFF6D6`, sidebar `#FFF1C2`, accent chips `#FEDA56`, type `#111111`.

### Named Rules

**The Public CSS Rule.** Frontmatter colors are the live public site. Carbon and Hex stay house tracks until Louis asks for a recolor.

## Typography

**Display Font:** JetBrains Mono (Consolas, Cascadia Code, Menlo, Monaco, Liberation Mono, Courier New, monospace)
**Body Font:** the same stack
**Label/Mono Font:** the same stack

**Character:** One heavy monospace voice. Body copy is already semibold (600). Titles are extrabold (800). Nothing on the public pages loads a second family.

Nunito Sans is the house font for the Chrome extension. It is not loaded by these pages. Do not swap the public face to Nunito Sans, or to an Impeccable default, in an unsolicited pass.

The Google Fonts stylesheet on every page is `JetBrains Mono` at weights 500, 600, 700, and 800.

### Hierarchy

- **Display** (800, 60px at 900px and up, line-height 1.05, tracking -0.03em): Homepage and marketing heroes, taglines, and closing titles. The same role is 48px from 640px and 36px below that.
- **Headline** (800, 36px from 768px, 30px below, tracking -0.02em): Section titles.
- **Title** (800, 24px): Panel titles and article subheads. Article titles also use 20px.
- **Body** (600, 16px / 24px): Default reading size. Ledes step up to 18px / 28px from 768px. The body element’s own line-height is 1.5.
- **Label** (700, 14px): Nav links, compact buttons, chips. Eyebrows are 12px, weight 700, tracking 0.06em, uppercase.
- **Numeral** (800, 40px): Step numbers and similar marks. The 404 display title is 48px, then 72px from 768px.

Homepage measure is 680px. Article pages use 700px. The outer container max is 1160px.

The homepage hero title currently clips a left-to-right gradient from ink to muted. That treatment stays until Louis changes the hero. Do not copy it onto other headings.

### Named Rules

**The One Face Rule.** Public pages use the JetBrains Mono stack already in the HTML. Nunito Sans stays on the Chrome extension.

## Layout

Pages sit in a centred column (`max-width: 1160px`) with 16px of side padding, 40px from 768px. Homepage sections are centre-aligned, with 48px of vertical padding, 64px from 768px. The hero is centre-aligned. Comparison hooks and journal body copy that are already left-aligned stay left-aligned.

Breakpoints in the live CSS: 640px, 768px, 800px (the proof-chip row), and 900px (desktop nav and the 60px display size).

**The Centre Homepage Rule.** Homepage sections stay centre-aligned.

## Elevation & Depth

Depth is a stamped offset, not a blur. Shadows are solid ink, zero blur. The scale in the CSS variables is 4px (`--shadow-sm`), 6px (`--shadow`), and 8px (`--shadow-lg`). Smaller presses at 2px and 3px appear on active buttons, eyebrows, and the hero stamp. Buttons lift 2px up and left on hover and grow the shadow to 6px; the active press drops them 2px down and right onto a 2px shadow.

The sticky nav is the one translucent surface: the page field (#FFFFFB) at 92% opacity with a 12px backdrop blur. That blur stays on the nav.

Motion uses `cubic-bezier(0.22, 1, 0.36, 1)`. Most state changes run 300ms. The homepage hero panel fades and rises over 550ms.

### Shadow Vocabulary

- **Small stamp** (`box-shadow: 4px 4px 0 #000`): Buttons, chips, compact controls.
- **Default stamp** (`box-shadow: 6px 6px 0 #000`): Nav bar and hover state of the main button.
- **Large stamp** (`box-shadow: 8px 8px 0 #000`): Large cards.
- **Press** (`box-shadow: 2px 2px 0 #000` and `3px 3px 0 #000`): Active buttons, eyebrows, hero stamp.

### Named Rules

**The Stamp Shadow Rule.** Depth is a hard offset with zero blur. Do not replace it with a soft or glowing shadow.

## Shapes

Blocks, buttons, chips, cards, and the nav are square-cornered. The only radius in the CSS is `50%` on the accent dots. Borders are 3px solid ink on structural blocks and 2px solid ink on eyebrows and dots.

### Named Rules

**The Sharp Block Rule.** Cards, buttons, and the nav stay square-cornered. Circles are the accent dots only.

## Components

### Buttons

- **Shape:** Square corners, 3px ink border, small stamp shadow.
- **Primary:** Desk Yellow fill, ink type. The large action (`.btn--lg`) uses 12px 24px padding at 16px / 700. The compact button uses 8px 12px.
- **Hover / Focus:** Hover translates -2px, -2px and sets a 6px stamp. Active translates 2px, 2px, scales to 0.98, and sets a 2px stamp. Focus is a 3px accent outline, 3px outside the border.
- **Secondary (`.btn--cream`):** Raised Surface fill, same border and shadow, for the secondary action.

### Chips

- **Style:** Eyebrows are Desk Yellow, 2px ink border, 4px 8px padding, 12px uppercase type, 3px stamp. Proof chips are Raised Surface, 3px ink border, small stamp, 14px type (16px from 900px).
- **State:** No separate selected state is defined.

### Cards / Containers

- **Corner Style:** Square.
- **Background:** Raised Surface (#FFFFFF), or the page field (#FFFFFB) for the page and for the default comparison cell. The “wrong” comparison cell is white. The “preferred” cell is Desk Yellow.
- **Shadow Strategy:** Default or large stamp. See Elevation.
- **Border:** 3px solid ink.
- **Internal Padding:** 32px 24px on the case card, 48px 40px from 768px.

### Navigation

- **Style:** Sticky, centred, max 1160px. 3px ink border and default stamp. Brand mark is 36px tall, 32px from 900px.
- **Typography:** 14px / 700 links.
- **Hover:** Desk Yellow fill, 2px ink border.
- **Mobile:** A panel drops under the bar. Desktop links and the bar call-to-action appear at 900px.

### Hero stamp

- **Style:** Accent fill, white type, 3px ink border, 3px stamp, 12px / 800, tracking 0.08em, uppercase. It sits in the homepage hero visual, not in running text.

## Do's and Don'ts

### Do:

- **Do** use the live tokens in the frontmatter for public pages.
- **Do** keep hard offset, zero-blur shadows.
- **Do** keep homepage sections centre-aligned.
- **Do** keep 3px ink borders on blocks and 2px ink borders on eyebrows and dots.
- **Do** leave MotionSites ads, links, and branding out of client deliverable files.

### Don't:

- **Don't** recolor the public pages with Carbon or Hex unless Louis asks.
- **Don't** swap the public face to Nunito Sans or to an Impeccable default face.
- **Don't** introduce pill buttons, blur-glow shadows, or purple gradients.
- **Don't** copy the homepage hero’s ink-to-muted text gradient onto other headings.
- **Don't** treat white-on-accent or muted-on-yellow as the contrast target. Those pairings are in the live CSS; this pass does not restyle them.
- **Don't** put MotionSites branding in deliverables.
