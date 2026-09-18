---
name: ai-running-coach
description: Documentation et site marketing d'un staff d'entraînement IA pour trail runners, connecté à Garmin.
colors:
  primary: "#1e4d3b"
  primary-deep: "#0f2a1f"
  accent: "#a3e635"
  accent-strong: "#84cc16"
  accent-hover: "#b6f04a"
  white: "#ffffff"
  neutral-bg: "#f6f4ef"
  neutral-bg-2: "#efece3"
  neutral-ink: "#1c2b24"
  neutral-ink-soft: "#4a5a52"
  dark-bg: "#0d1410"
  dark-ink: "#e7ede9"
  dark-ink-soft: "#b8c4bd"
typography:
  display:
    fontFamily: "Sora, Inter, sans-serif"
    fontSize: "clamp(2.4rem, 6vw, 4.4rem)"
    fontWeight: 800
    lineHeight: 1.04
    letterSpacing: "-0.03em"
  headline:
    fontFamily: "Sora, Inter, sans-serif"
    fontSize: "clamp(1.8rem, 3.4vw, 2.6rem)"
    fontWeight: 700
    lineHeight: 1.12
    letterSpacing: "-0.02em"
  title:
    fontFamily: "Sora, Inter, sans-serif"
    fontSize: "1.2rem"
    fontWeight: 700
    lineHeight: 1.3
  lead:
    fontFamily: "Inter, sans-serif"
    fontSize: "clamp(1.05rem, 1.6vw, 1.25rem)"
    fontWeight: 400
    lineHeight: 1.6
  body:
    fontFamily: "Inter, sans-serif"
    fontSize: "1rem"
    fontWeight: 400
    lineHeight: 1.6
  label:
    fontFamily: "Inter, sans-serif"
    fontSize: "0.9rem"
    fontWeight: 400
  mono:
    fontFamily: "JetBrains Mono, monospace"
    fontSize: "0.95rem"
    fontWeight: 400
rounded:
  sm: "0.6rem"
  md: "0.8rem"
  lg: "1.1rem"
  pill: "2rem"
spacing:
  section: "5rem"
  section-mobile: "3.5rem"
  gap: "1.4rem"
components:
  button-primary:
    backgroundColor: "{colors.accent}"
    textColor: "{colors.primary-deep}"
    rounded: "{rounded.pill}"
    padding: "0.85rem 1.7rem"
  button-primary-hover:
    backgroundColor: "#b6f04a"
    textColor: "{colors.primary-deep}"
    rounded: "{rounded.pill}"
    padding: "0.85rem 1.7rem"
  button-secondary:
    backgroundColor: "transparent"
    textColor: "#ffffff"
    rounded: "{rounded.pill}"
    padding: "0.85rem 1.7rem"
  agent-card:
    backgroundColor: "{colors.neutral-bg}"
    rounded: "{rounded.lg}"
    padding: "1.8rem 1.8rem 1.6rem"
  cta-command:
    backgroundColor: "#0a1510"
    textColor: "{colors.accent}"
    rounded: "{rounded.md}"
    padding: "1rem 1.6rem"
---

# Design System: ai-running-coach

## Overview

**Creative North Star: "Le Sentier"** — the docs are a trailhead, not a manual. Every screen opens onto the runner's own world: deep pine forest, warm stone, a lime accent like a trail marker catching dawn light. The system earns attention with real mountain photography and a quiet alpine type system, then gets out of the way so the reader acts: install in five minutes.

The personality is **earned and restrained** — one full-bleed photographic moment per landing, generous whitespace, soft ambient shadows, and a single authored motion moment on load. Density is low; confidence is high. The palette is earth-and-forest (deep pine greens, warm stone neutrals, energetic lime), chosen from the use scene: a francophone trail runner at dawn, not a corporate dashboard at noon.

**Key Characteristics:**
- Full-bleed photographic hero as the first viewport, with a dark scrim for text legibility.
- Earth-and-forest palette: pine greens, warm stone, lime accent.
- Sora display type (tight tracking) over Inter body text.
- One authored motion moment (hero rise on load), exponential ease-out, reduced-motion respected.
- Soft ambient shadows with real offset and blur; never zero-offset halos.
- Generous section rhythm (5rem), tight intra-group gaps (1.4rem).

## Colors

The palette is earth-and-forest: deep pine greens carry structure, warm stone carries content, and a single lime accent marks action. Dark and light schemes are both first-class, tuned from the same hue family.

### Primary
- **Pine** (#1e4d3b): the brand green. Used for links, primary surfaces, and the header. Deep enough to carry white text at 12.15:1 contrast.
- **Pine Deep** (#0f2a1f): the darkest pine. Used for the dark flow section background, footer, and text-on-lime. Carries lime at 10.16:1.

### Secondary
- **Lime** (#a3e635): the single action accent. Used for the primary CTA, trust-marker dots, step numbers, and code text on dark. Its rarity is the point — it marks "act here."
- **Lime Strong** (#84cc16): the accent in light mode (Material `--md-accent-fg-color`), slightly deeper for link hover and focus.

### Neutral
- **Stone** (#f6f4ef): the warm light background. Carries ink at 13.45:1.
- **Stone 2** (#efece3): the tinted surface for the CTA band and quote blocks.
- **Ink** (#1c2b24): primary text on light. A green-tinted near-black, not pure gray.
- **Ink Soft** (#4a5a52): secondary text on light (6.64:1).
- **Dark Ink** (#e7ede9) / **Dark Ink Soft** (#b8c4bd): the slate-scheme equivalents on the dark background (#0d1410).

### Named Rules
**The One Accent Rule.** Lime appears on ≤10% of any screen. It marks action (CTAs, step numbers, trust dots) and nothing else; a second accent color is never introduced.

**The Tinted-Secondary Rule.** Secondary text is tinted from the surface hue (green-tinted ink on stone, green-tinted gray on dark) — never pure gray, which reads as disabled.

## Typography

**Display Font:** Sora (with Inter fallback)
**Body Font:** Inter
**Label/Mono Font:** JetBrains Mono (code, commands, data only)

**Character:** Sora is a quiet alpine display face — geometric, slightly condensed, confident at 800 weight. Paired with Inter's neutral readability, the system reads as "outdoor gear, well made": technical but warm. Mono is reserved for actual code and commands, never as a costume.

### Hierarchy
- **Display** (800, clamp(2.4rem, 6vw, 4.4rem), 1.04, -0.03em): the hero headline only. Max width 15ch. One line break at the natural phrase boundary.
- **Headline** (700, clamp(1.8rem, 3.4vw, 2.6rem), 1.12, -0.02em): section headings. Max width 24ch.
- **Title** (700, 1.2–1.3rem): agent names and step titles.
- **Body** (400, 1rem, 1.6): content text. Max measure 46–58ch in the hero and section intros, 65–75ch in documentation.
- **Label** (400, 0.9rem): trust markers, step numbers, disclaimers.

### Named Rules
**The Tight-Tracking Rule.** Display and headline letter-spacing is negative (-0.02em to -0.03em) and never looser than normal. The alpine character comes from compression, not from spacing out.

**The Mono-Is-Data Rule.** JetBrains Mono appears only for code, commands, and measurements — never to make a label look "technical."

## Layout

The layout is a single-column editorial flow with a full-bleed hero, then centered sections on a 61rem grid (Material's `.md-grid`). Section rhythm is 5rem vertical padding (3.5rem on mobile), with tight 1.4rem gaps inside groups.

- **Hero:** full-bleed image, min-height 88vh (82vh ≤76em, 78vh ≤45em), content left-aligned with 7rem top padding. On mobile the hero aligns content to the bottom.
- **Sections:** `.arc-section` with optional `--dark` (pine-900 background) and `--tint` (stone-2) variants for rhythm.
- **Grids:** team and skills collapse from 2 columns to 1 at 60em; flow from 3 columns to 1 at 60em.
- **Breakpoints:** 76.1875em (hero height), 60em (grid collapse), 44.9375em (mobile hero, stacked CTAs).

## Elevation & Depth

The system is **layered-flat**: surfaces are flat at rest, and depth comes from soft ambient shadows with real offset and blur — never zero-offset halos. Photography carries the hero's depth; shadows carry cards and commands.

### Shadow Vocabulary
- **Ambient Card** (`0 1px 2px rgba(20,40,30,0.06), 0 8px 24px rgba(20,40,30,0.08)`): agent cards on light. A near-invisible contact shadow plus a soft ambient falloff.
- **Ambient Dark** (`0 1px 2px rgba(0,0,0,0.3), 0 8px 24px rgba(0,0,0,0.35)`): cards and the CTA command block on dark surfaces.
- **Header Shadow** (`0 0 0.2rem rgba(0,0,0,0.1), 0 0.2rem 0.4rem rgba(0,0,0,0.3)`): the sticky header once scrolled past the transparent hero.

### Named Rules
**The Offset-Only Rule.** Every shadow carries a vertical offset and a soft blur. A zero-offset colored halo is decoration, not depth, and is never used.

## Shapes

The form language is **gently curved, outdoor-gear rounded**: pills for actions, soft rounded rectangles for surfaces, small radii for inline quotes.

- **Pill** (2rem): all buttons and CTAs.
- **Large** (1.1rem): agent cards.
- **Medium** (0.8rem): the CTA command block.
- **Small** (0.6rem): inline quote blocks.
- **Dots** (0.4rem circles): trust markers and list bullets, in lime.

Borders are used sparingly: a 1px bottom rule separates skill rows; buttons use a 1px border matching their fill (Material's default). No colored border-left/right callouts above 1px.

## Components

### Buttons
- **Shape:** pill (2rem radius), 0.85rem 1.7rem padding, 600 weight, 1rem.
- **Primary:** lime background (#a3e635), pine-deep text (#0f2a1f). Hover lightens to #b6f04a. This is the single action color on the page.
- **Secondary:** transparent background, white text, 0.65-opacity white border. Hover fills to 14% white.
- **Focus:** Material's default focus ring; keyboard focus is always visible.

### Agent Cards
- **Corner Style:** large radius (1.1rem).
- **Background:** stone on light, #16201a on dark.
- **Shadow Strategy:** Ambient Card / Ambient Dark (see Elevation).
- **Internal Padding:** 1.8rem 1.8rem 1.6rem.
- **Content:** emoji icon + name (title), one role paragraph, one example prompt in a stone-2 quote block.

### CTA Command Block
- **Style:** inline-block, JetBrains Mono, lime text on near-black (#0a1510), medium radius (0.8rem), 1rem 1.6rem padding.
- **Shadow:** Ambient Dark.
- **Purpose:** the one-line install command — the single most important copy on the landing.

### Navigation
- **Style:** Material header, transparent over the hero, solid pine with shadow once scrolled.
- **Typography:** Inter, default Material sizing.
- **Mobile:** Material's standard drawer; the hero CTAs stack full-width.

### Hero (Signature Component)
- **Structure:** full-bleed image, dark scrim (linear gradient 0.62 → 0.28 → 0.78 opacity), content left-aligned.
- **Content:** display headline, one lead sentence (46ch max), two CTAs, three trust markers (lime dots).
- **Motion:** the title, lead, and actions rise in sequence (0s / 0.15s / 0.3s) with `cubic-bezier(0.16, 1, 0.3, 1)` over 0.8s — the system's one authored motion moment. Disabled under `prefers-reduced-motion`.

## Do's and Don'ts

### Do:
- **Do** open with the full-bleed photographic hero — the mountain is the promise.
- **Do** use lime only for action: CTAs, step numbers, trust dots.
- **Do** keep display tracking tight (-0.02em to -0.03em) and body measure at 65–75ch in docs.
- **Do** give every shadow an offset and a blur.
- **Do** respect `prefers-reduced-motion` by disabling the hero rise.

### Don't:
- **Don't** add a second accent color; lime is the only one.
- **Don't** use pure gray for secondary text — tint it from the surface hue.
- **Don't** use JetBrains Mono outside code, commands, and data.
- **Don't** add a kicker or eyebrow above a heading; the heading carries its own weight.
- **Don't** use gradient text, glass-as-decoration, or zero-offset colored halos.
- **Don't** add more than one authored motion moment; the hero rise is the only one.