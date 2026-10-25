---
name: ai-running-coach
description: Staff d'entraînement IA pour trail runners — deux surfaces, le site de documentation « Le Sentier » et le tableau de bord « Roadbook » (design par défaut).
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
  roadbook-sheet: "#fdfdfb"
  roadbook-sheet-2: "#f1f0ea"
  roadbook-ink-soft: "#46564e"
  roadbook-ink-faint: "#627169"
  roadbook-line: "#dddad0"
  roadbook-line-strong: "#bdb8a8"
  roadbook-band-soft: "#c9dccf"
  roadbook-ok: "#2f7a4f"
  roadbook-warn: "#8a5a12"
  roadbook-bad: "#b3432f"
  roadbook-focus: "#5a8f1c"
  roadbook-done: "rgba(47, 107, 79, 0.42)"
  roadbook-night-sheet: "#153a2c"
  roadbook-night-sheet-2: "#1a4535"
  roadbook-night-ink-soft: "#c3d1c9"
  roadbook-night-ink-faint: "#a3b8ad"
  roadbook-night-line: "#2a5443"
  roadbook-night-line-strong: "#3f6b58"
  roadbook-night-band: "#0b1f17"
  roadbook-night-top: "#0a1d15"
  roadbook-night-rule: "#7cc39b"
  roadbook-night-warn: "#e0ad4f"
  roadbook-night-ok: "#6fc28f"
  roadbook-night-bad: "#ec7f69"
  roadbook-night-focus: "#b6f04a"
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
  roadbook-verdict:
    fontFamily: "Barlow Condensed, Arial Narrow, system-ui, sans-serif"
    fontSize: "clamp(3.2rem, 13vw, 5.25rem)"
    fontWeight: 700
    lineHeight: 0.88
    letterSpacing: "0.005em"
  roadbook-view-title:
    fontFamily: "Barlow Condensed, Sora, Inter, system-ui, sans-serif"
    fontSize: "2.1rem"
    fontWeight: 700
    lineHeight: 1.05
    letterSpacing: "0.005em"
  roadbook-lead-title:
    fontFamily: "Barlow Condensed, Arial Narrow, system-ui, sans-serif"
    fontSize: "1.55rem"
    fontWeight: 700
    lineHeight: 1.05
    letterSpacing: "0.01em"
  roadbook-sheet-head:
    fontFamily: "Barlow Condensed, Arial Narrow, system-ui, sans-serif"
    fontSize: "1.2rem"
    fontWeight: 600
    lineHeight: 1.15
    letterSpacing: "0.04em"
  roadbook-numeral:
    fontFamily: "Barlow Condensed, Arial Narrow, system-ui, sans-serif"
    fontSize: "1.55rem"
    fontWeight: 600
    lineHeight: 1
    fontFeature: "tnum"
  roadbook-label:
    fontFamily: "Barlow Condensed, Arial Narrow, system-ui, sans-serif"
    fontSize: "0.82rem"
    fontWeight: 600
    lineHeight: 1.2
    letterSpacing: "0.07em"
  roadbook-body:
    fontFamily: "Inter, system-ui, -apple-system, Segoe UI, sans-serif"
    fontSize: "0.9375rem"
    fontWeight: 400
    lineHeight: 1.55
rounded:
  sm: "0.6rem"
  md: "0.8rem"
  lg: "1.1rem"
  pill: "2rem"
  roadbook-sheet: "0.55rem"
  roadbook-sm: "0.4rem"
  roadbook-plate: "0.3rem"
  roadbook-drawer: "1rem 1rem 0 0"
spacing:
  section: "5rem"
  section-mobile: "3.5rem"
  gap: "1.4rem"
  roadbook-sheet-pad: "1rem 1.15rem 1.15rem"
  roadbook-sheet-gap: "1rem"
  roadbook-column-gap: "1.25rem"
  roadbook-top-bar: "3.25rem"
  roadbook-tab-bar: "3.9rem"
  roadbook-rail: "15.5rem"
  roadbook-side-column: "21rem"
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
  roadbook-action:
    backgroundColor: "{colors.accent}"
    textColor: "{colors.primary-deep}"
    rounded: "{rounded.roadbook-sm}"
    padding: "0.62rem 1rem 0.58rem"
  roadbook-action-hover:
    backgroundColor: "{colors.accent-hover}"
    textColor: "{colors.primary-deep}"
    rounded: "{rounded.roadbook-sm}"
    padding: "0.62rem 1rem 0.58rem"
  roadbook-action-ghost:
    backgroundColor: "transparent"
    textColor: "{colors.neutral-ink}"
    rounded: "{rounded.roadbook-sm}"
    padding: "0.62rem 1rem 0.58rem"
  roadbook-sheet-card:
    backgroundColor: "{colors.roadbook-sheet}"
    rounded: "{rounded.roadbook-sheet}"
    padding: "{spacing.roadbook-sheet-pad}"
  roadbook-sheet-head-lead:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.neutral-bg}"
    typography: "{typography.roadbook-lead-title}"
    padding: "0.75rem 1.15rem 0.65rem"
  roadbook-plate-trigger:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.neutral-bg}"
    typography: "{typography.roadbook-label}"
    rounded: "{rounded.roadbook-plate}"
    padding: "0.34rem 0.55rem"
  roadbook-pin-label:
    backgroundColor: "{colors.accent}"
    textColor: "{colors.primary-deep}"
    typography: "{typography.roadbook-label}"
    rounded: "0.25rem"
    padding: "0.2rem 0.45rem"
  roadbook-tab-bar:
    backgroundColor: "{colors.roadbook-sheet}"
    textColor: "{colors.roadbook-ink-faint}"
    height: "{spacing.roadbook-tab-bar}"
  roadbook-week-nav-current:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.neutral-bg}"
    rounded: "0.35rem"
    padding: "0.38rem 0.75rem"
---

# Design System: ai-running-coach

## Overview

Two surfaces share one palette root (pine, deep pine, lime, stone) and keep separate systems. **Le Sentier** is the MkDocs documentation and marketing site (Sora/Inter, photographic hero) and governs every section's first part. **Le Roadbook** is the local dashboard (`web/index.html`, `web/chat.html`, installable PWA), the default dashboard surface since v1.4 behind `[data-design="roadbook"]`; the former dashboard design is deprecated, reachable through `?design=classic` until v1.5 (then deleted); roadbook rules live in each section under *Dashboard roadbook* and apply only under that attribute. A rule from one surface never binds the other unless stated.

### Documentation site — Le Sentier

**Creative North Star: "Le Sentier"** — the docs are a trailhead, not a manual. Every screen opens onto the runner's own world: deep pine forest, warm stone, a lime accent like a trail marker catching dawn light. The system earns attention with real mountain photography and a quiet alpine type system, then gets out of the way so the reader acts: install in five minutes.

The personality is **earned and restrained** — one full-bleed photographic moment per landing, generous whitespace, soft ambient shadows, and a single authored motion moment on load. Density is low; confidence is high. The palette is earth-and-forest (deep pine greens, warm stone neutrals, energetic lime), chosen from the use scene: a francophone trail runner at dawn, not a corporate dashboard at noon.

**Key Characteristics:**
- Full-bleed photographic hero as the first viewport, with a dark scrim for text legibility.
- Earth-and-forest palette: pine greens, warm stone, lime accent.
- Sora display type (tight tracking) over Inter body text.
- One authored motion moment (hero rise on load), exponential ease-out, reduced-motion respected.
- Soft ambient shadows with real offset and blur; never zero-offset halos.
- Generous section rhythm (5rem), tight intra-group gaps (1.4rem).

### Dashboard roadbook

**Creative North Star: "Le Roadbook"** — the dashboard is the athlete's season roadbook: the training block drawn as an elevation profile cut into sections, ending at the race finish flag, and each day an aid-station sheet. Laminated sheets lie on stone by day and on deep pine in the morning dark; ink is pine; lime marks only "vous êtes ici" and the one primary action.

The personality is **operational and legible at a glance**, for a phone in dim light before a run. Density is medium-high but ruled, not boxed: content sits in rows with hairlines and tabular numerals, never in stat tiles or ring gauges. Barlow Condensed carries headings, verdicts and numbers like the lettering of a race barrier; Inter carries reading text.

**Key Characteristics:**
- Season profile ribbon across the top, with week ticks, month marks, section labels, a lime "vous êtes ici" pin and a chequered finish flag.
- Sheet cards with a 2px pine-ruled head; the day's lead sheet carries a solid pine band instead.
- Verdict word at poster size in Barlow Condensed caps, coloured by state and always a word.
- Cut-off rows: label, condensed tabular value, reference, and a state mark that is a shape plus a word.
- Light (stone) and dark (deep pine) schemes are both first-class, following the system preference or an explicit theme.
- One motion moment: the profile unrolls left to right, then the pin drops.

## Colors

### Documentation site — Le Sentier

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

### Dashboard roadbook

The roadbook reuses the shared roots — Pine as band and rule ink, Pine Deep as the top bar and the dark ground, Lime as the pin and primary action, Stone as the light ground, Ink as text — and adds paper and night tones of its own.

**Day (stone):**
- **Laminated Sheet** (roadbook-sheet) / **Sheet Shade** (roadbook-sheet-2): card surface on stone; the shade is hover, current nav item and tape track.
- **Ink Soft** (roadbook-ink-soft) / **Ink Faint** (roadbook-ink-faint): meta text and references, labels and empty states; both green-tinted.
- **Hairline** (roadbook-line) / **Strong Hairline** (roadbook-line-strong): row rules; dashed sub-sheet dividers, plate borders, ghost-action borders.
- **Band Soft** (roadbook-band-soft): meta text on the pine band.
- **Trail Green / Barrier Amber / Barrier Red** (roadbook-ok / roadbook-warn / roadbook-bad): state ink. Amber is darkened on paper so small "à surveiller" labels hold 4.5:1.
- **Focus** (roadbook-focus): keyboard focus ring.
- **Done Fill** (roadbook-done): realised volume on the profile and endurance segments on the tape. The profile area uses pine at 10%, the selected week lime at 30%.

**Night (deep pine):** the ground becomes Pine Deep, sheets **Night Sheet** / **Night Sheet 2**, text Dark Ink with **Night Ink Soft** / **Night Ink Faint**, rules **Night Line** / **Night Line Strong**. The band drops to **Night Band** and the top bar to **Night Top**, both darker than the sheets. Rule ink lightens to **Night Rule** (a pale pine), the pin's stem turns lime, and state inks lighten (night-ok / night-warn / night-bad); focus becomes Lime Hover.

**The You-Are-Here Rule.** Lime appears only as the "vous êtes ici" marker — profile pin and its label, current rail dot, today's dot in week lists, the active tab notch, today's row tint (lime at 7%) and the selected week on the profile — and as the single primary action. A second lime surface on a screen is a defect.

**The Word-and-Shape Rule.** State is never colour alone: every state carries a word ("dans la cible", "à surveiller", "hors cible", "pas de mesure") and a shape (filled circle, triangle, diamond, dash). The verdict colour sits on a verdict word.

## Typography

### Documentation site — Le Sentier

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

### Dashboard roadbook

**Display Font:** Barlow Condensed 500/600/700 (with Arial Narrow, then system-ui)
**Body Font:** Inter (with system-ui)

**Character:** Barlow Condensed is barrier and race-bib lettering: narrow, upright, read at arm's length in caps and numerals. Inter keeps sentences calm. Sora stays loaded only as a fallback in the display stack.

- **Verdict** (roadbook-verdict, uppercase): the day's verdict word only, balanced wrap. With no verdict it drops to clamp(2rem, 8vw, 2.75rem).
- **View title** (roadbook-view-title): the h1 of every view.
- **Lead title** (roadbook-lead-title, sentence case): the date on the day's lead band.
- **Sheet head** (roadbook-sheet-head, uppercase): sheet card headings and all h2s; meta beside it in 500 0.95rem condensed, tabular.
- **Numeral** (roadbook-numeral, tabular): cut-off values (1.55rem), readings (1.45rem), facts (1.7rem), capacity totals (1.15rem); units in a smaller faint `small` (0.6–0.66em).
- **Label** (roadbook-label, uppercase, 0.07–0.08em tracking): rail group titles, column heads, fact terms, tape labels, pin label, trigger plates.
- **Body** (roadbook-body): reading text; the verdict reason runs 1.04rem/1.5 to 56ch, prose to 72ch.

**The Condensed-Caps Rule.** On the roadbook, uppercase condensed text takes positive tracking (0.01em to 0.08em, wider as it gets smaller) and every number that can be compared is tabular. The docs site's Tight-Tracking Rule governs Sora only.

## Layout

### Documentation site — Le Sentier

The layout is a single-column editorial flow with a full-bleed hero, then centered sections on a 61rem grid (Material's `.md-grid`). Section rhythm is 5rem vertical padding (3.5rem on mobile), with tight 1.4rem gaps inside groups.

- **Hero:** full-bleed image, min-height 88vh (82vh ≤76em, 78vh ≤45em), content left-aligned with 7rem top padding. On mobile the hero aligns content to the bottom.
- **Sections:** `.arc-section` with optional `--dark` (pine-900 background) and `--tint` (stone-2) variants for rhythm.
- **Grids:** team and skills collapse from 2 columns to 1 at 60em; flow from 3 columns to 1 at 60em.
- **Breakpoints:** 76.1875em (hero height), 60em (grid collapse), 44.9375em (mobile hero, stacked CTAs).

### Dashboard roadbook

- **Shell:** a deep-pine top bar (roadbook-top-bar min-height, safe-area aware) holding brand, the countdown (J-54 in 700 1.45rem condensed) and the race; below it a sticky grouped rail (roadbook-rail wide) and the main column (max 84rem, padding 1.25rem clamp(1rem, 2.6vw, 2.25rem) 4rem).
- **Main grid:** the season profile spans the top; sheets stack in one column with roadbook-sheet-gap between them. From 72em the grid becomes main + roadbook-side-column (21rem), the side column sticky under the top bar.
- **Phone and tablet (≤63.99em):** the rail disappears and a fixed five-slot bottom tab bar (roadbook-tab-bar tall plus the safe area) takes over; the profile goes full-bleed to the screen edges with a 5.25rem plot (7rem on wide screens).
- **Small phone (≤36em):** cut-off rows reflow into a two-by-two grid (label/value, reference/state), the week sheet drops its header row and status column and places status under each session, sheet padding tightens to 0.9rem 0.95rem 1rem.
- **Rhythm:** sheet bodies 1rem/1.15rem; rows 0.5–0.7rem vertical; sub-sheets open with 1.4rem and a dashed rule.

## Elevation & Depth

### Documentation site — Le Sentier

The system is **layered-flat**: surfaces are flat at rest, and depth comes from soft ambient shadows with real offset and blur — never zero-offset halos. Photography carries the hero's depth; shadows carry cards and commands.

### Shadow Vocabulary
- **Ambient Card** (`0 1px 2px rgba(20,40,30,0.06), 0 8px 24px rgba(20,40,30,0.08)`): agent cards on light. A near-invisible contact shadow plus a soft ambient falloff.
- **Ambient Dark** (`0 1px 2px rgba(0,0,0,0.3), 0 8px 24px rgba(0,0,0,0.35)`): cards and the CTA command block on dark surfaces.
- **Header Shadow** (`0 0 0.2rem rgba(0,0,0,0.1), 0 0.2rem 0.4rem rgba(0,0,0,0.3)`): the sticky header once scrolled past the transparent hero.

### Named Rules
**The Offset-Only Rule.** Every shadow carries a vertical offset and a soft blur. A zero-offset colored halo is decoration, not depth, and is never used.

### Dashboard roadbook

Sheets lie flat on the table: one low paper shadow under every sheet card and the profile, borders do the rest. Rules (2px pine heads, 1px hairlines, dashed dividers) carry hierarchy, not stacking.

- **Paper** (`0 1px 1px rgba(20,40,30,0.05), 0 6px 18px rgba(20,40,30,0.07)`; night `0 1px 1px rgba(3,12,8,0.35), 0 8px 22px rgba(3,12,8,0.32)`): sheet cards, the profile, legacy bands.
- **Action** (`0 1px 1px rgba(15,42,31,0.18), 0 4px 10px rgba(15,42,31,0.12)`): the lime primary action only.
- **Tab bar** (`0 -4px 14px rgba(20,40,30,0.06)`) and **Drawer** (`0 -8px 30px rgba(0,0,0,0.25)` over a `rgba(5,15,10,0.6)` backdrop): surfaces anchored to the bottom edge cast upward.
- **Motion:** the one moment is the profile unroll (clip-path inset from 100% to 0, 900ms) followed by the pin drop (fade and 0.5rem fall, 420ms, 520ms delay), both on `cubic-bezier(0.16, 1, 0.3, 1)`; removed under `prefers-reduced-motion`. Everything else is a 150ms background change at most.

## Shapes

### Documentation site — Le Sentier

The form language is **gently curved, outdoor-gear rounded**: pills for actions, soft rounded rectangles for surfaces, small radii for inline quotes.

- **Pill** (2rem): all buttons and CTAs.
- **Large** (1.1rem): agent cards.
- **Medium** (0.8rem): the CTA command block.
- **Small** (0.6rem): inline quote blocks.
- **Dots** (0.4rem circles): trust markers and list bullets, in lime.

Borders are used sparingly: a 1px bottom rule separates skill rows; buttons use a 1px border matching their fill (Material's default). No colored border-left/right callouts above 1px.

### Dashboard roadbook

Cut sheets, not pills: small, firm corners. Sheets and the profile use roadbook-sheet radius; actions, nav items and buttons roadbook-sm; plates, chips and the tape roadbook-plate; the sections drawer opens with a 1rem top radius. The recurring marks are geometric: a diamond (rotated 0.48rem square) for each session — outline for endurance, filled pine for quality, faint for other, filled green when done; circle, triangle, diamond and dash for states; a lime dot with a deep-pine ring for "here"; a chequered flag for the finish; a 135° amber hatch for volume over target.

## Components

### Documentation site — Le Sentier

#### Buttons
- **Shape:** pill (2rem radius), 0.85rem 1.7rem padding, 600 weight, 1rem.
- **Primary:** lime background (#a3e635), pine-deep text (#0f2a1f). Hover lightens to #b6f04a. This is the single action color on the page.
- **Secondary:** transparent background, white text, 0.65-opacity white border. Hover fills to 14% white.
- **Focus:** Material's default focus ring; keyboard focus is always visible.

#### Agent Cards
- **Corner Style:** large radius (1.1rem).
- **Background:** stone on light, #16201a on dark.
- **Shadow Strategy:** Ambient Card / Ambient Dark (see Elevation).
- **Internal Padding:** 1.8rem 1.8rem 1.6rem.
- **Content:** Material icon in a pine tile (lime glyph), name (title), one role paragraph, one example prompt as a stone-2 chat bubble pinned to the card bottom.

#### CTA Command Block
- **Style:** inline-block, JetBrains Mono, lime text on near-black (#0a1510), medium radius (0.8rem), 1rem 1.6rem padding.
- **Shadow:** Ambient Dark.
- **Purpose:** the one-line install command — the single most important copy on the landing.

#### Navigation
- **Style:** Material header, transparent over the hero, solid pine with shadow once scrolled.
- **Typography:** Inter, default Material sizing.
- **Mobile:** Material's standard drawer; the hero CTAs stack full-width.

#### Hero (Signature Component)
- **Structure:** full-bleed image, dark scrim (linear gradient 0.62 → 0.28 → 0.78 opacity), content left-aligned.
- **Content:** display headline, one lead sentence (46ch max), two CTAs, three trust markers (lime dots).
- **Motion:** the title, lead, and actions rise in sequence (0s / 0.15s / 0.3s) with `cubic-bezier(0.16, 1, 0.3, 1)` over 0.8s — the system's one authored motion moment. Disabled under `prefers-reduced-motion`.

#### Course Profile (Signature Component)
- **Structure:** a dark pine band holding an authored SVG elevation profile (viewBox 1000×180, aspect ratio locked so waypoints stay round), a faint lime area fill, a light stroke line, and five lime waypoints — each centred over one of five equal columns below.
- **Stages:** `Départ → Préparation → Chaque matin → Jour J → Arrivée`, each a Sora lime label, a short title and one paragraph. It is the landing's map of the product, from install to race debrief.
- **Mobile:** the profile stays as a header graphic; stages stack along a dashed lime line with a lime dot per stage.
- **Echo:** the hero photo ends on the same ridge motif (`.arc-hero__ridge`, filled with the page background) instead of a straight edge.

#### Command List and Phone
- **Commands:** the five short commands as rows — a pine-deep pill with the command in lime JetBrains Mono (real commands, so the Mono-Is-Data rule holds), then one sentence. Rows are links with a stone-2 hover.
- **Phone:** a real mobile dashboard capture in a pine-950 frame (2.4rem radius, 0.55rem bezel, soft offset shadow), rotated 2°.

#### Skill Families
- Three columns (Terrain et séances · Garmin et synchronisation · Installation et données), each headed by a Sora title over a 2px pine rule (lime in dark), listing skill links with a one-line description.

#### Dashboard Showcase
- A dark band with Material content tabs restyled as pills (lime when active) over a window frame (near-black, three quiet dots, 0.9rem radius). Each tab shows a real capture cropped to 16:10 from the top-left, so switching never shifts layout.
- Dark bands re-scope Material's colour variables (`--md-default-fg-color`, `--md-typeset-a-color`…) so nested components inherit light-on-pine values.

#### Interior Pages
- H1s carry no emoji; icons, where needed, come from Material's icon set (`:material-*:`).
- Tables: 1px rule, 0.6rem radius, stone-2 header, tabular numerals. Admonitions: 1px border, 0.7rem radius, Sora titles. Grid cards lift with a soft offset shadow on hover.
- Browser surfaces: lime-tinted `::selection`, palette scrollbar, lime-strong focus ring, 0.2em underline offset.

### Dashboard roadbook

#### Sheet Card
- Laminated sheet on Paper shadow, 1px hairline border, roadbook-sheet radius, overflow clipped.
- **Head:** sheet-head title left, condensed tabular meta right, over a 2px rule in rule ink.
- **Lead variant:** the day's first sheet replaces the rule with a solid pine band (night band in the dark), the date in the lead title on stone, meta in band soft.
- Sub-sheets inside a card open with a dashed strong hairline; no box inside a box.

#### Display Verdict
- The verdict word in roadbook-verdict caps, coloured green / amber / red by state (faint when none), followed by one plain sentence of reason at 1.04rem to 56ch.

#### Trigger Plate
- A two-part inline plate (roadbook-plate radius, strong hairline border): the trigger on a pine band ("BILAN MATINAL", "GARDE-FOU"), then the outcome in ink soft ("APPLIQUÉE"). Below it the change reads as the cancelled session struck through, a drawn SVG arrow, and the replacement in 600 ink.

#### Cut-off Rows
- A table of measures: label (30%), condensed tabular value with a faint unit, faint reference, and a right-aligned state mark — 0.72rem SVG shape plus word, 0.86rem 600. On small phones each row becomes a 2×2 grid.

#### Readings Rows
- The same row grammar for form and realised volume: label, right-aligned condensed value, faint right-aligned reference; gains in trail green, losses in amber. Readings are rows, never tiles.

#### Run Rows
- Each session keeps its place; status restyles it in place: cancelled = faint, struck through, diamond at 45% opacity; moved = ink soft; done = green diamond. A status chip (0.3rem radius) sits at the right. On the week sheet the rows become a run sheet table (day, session, duration, status) with a 2px ruled header, dashed rules between sessions of a day and today's row tinted lime at 7%.

#### Capacity Tape
- Two rows (Prévu, Réalisé): condensed caps label, a 1.15rem tape on the sheet shade with 2px gaps — one segment per session sized by duration (done fill for endurance, pine for quality, strong hairline for other), a 2px ink target tick and, past the target, a 135° amber hatch — and a tabular total. A key spells out each fill in words.

#### Season Profile Ribbon (Signature)
- A sheet holding an SVG profile (height = planned volume per week, done fill = realised), dashed line through unplanned weeks, week ticks on the baseline, month marks with a left hairline, section labels (Spécifique, À planifier…) under a strong hairline, and a readout line with legend.
- The lime pin (1rem dot, deep-pine ring, stem) carries a lime "VOUS ÊTES ICI" label; the finish is a 2px ink pole with a chequered flag and the race name and date in condensed caps. Each week is a focusable link to its week sheet.
- Positions arrive as `data-vars` custom properties set through the CSSOM (`--x`, `--a`, `--w`), never as inline style attributes.

#### Navigation
- **Wide:** a grouped rail (Au quotidien, Entraînement, Corps et matériel, Course, Journal) with condensed caps group titles; the current item gets the sheet shade, 600 ink and a lime dot; debt items in amber; a dashed foot with the link back to the current design.
- **Phone and tablet:** a bottom tab bar of five slots — Aujourd'hui, Semaine, Santé, Coach, Sections — with 1.45rem stroked SVG icons (1.75 stroke) over 0.72rem Inter labels; the current tab is ink with a 2rem × 3px lime notch on the top edge. "Sections" opens a native dialog drawer holding the same groups as the rail.
- **Week nav:** Précédente / Cette semaine / Suivante as bordered 0.35rem links; the current week fills with the pine band.

#### Primary Action
- The only lime fill on a page: roadbook-action caps in Barlow Condensed 700 1.05rem with 0.05em tracking, a 1px deep-pine border, the Action shadow and a drawn arrow; hover Lime Hover; focus a 2px ring at 3px offset. The ghost variant is transparent with a strong hairline border.

## Do's and Don'ts

The first two lists apply to the MkDocs documentation site; the roadbook lists apply under `[data-design="roadbook"]`. Each surface keeps exactly one authored motion moment.

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
- **Don't** use emoji as icons or in page titles; use Material's icon set.

### Do (dashboard roadbook):
- **Do** keep lime for "vous êtes ici" and the single primary action; every other emphasis is pine, ink or a state ink.
- **Do** give every state a shape and a word as well as a colour.
- **Do** set comparable numbers in Barlow Condensed with tabular numerals and units in a smaller faint size.
- **Do** pass computed positions through `data-vars` and the CSSOM; the CSP (`style-src 'self'`) refuses inline style attributes.
- **Do** keep every roadbook rule under `[data-design="roadbook"]` so the deprecated classic design (until v1.5) is untouched without the attribute.
- **Do** keep the profile unroll and pin drop as the only motion, removed under `prefers-reduced-motion`.

### Don't (dashboard roadbook):
- **Don't** lay out readings as a grid of stat tiles or ring gauges; use ruled rows.
- **Don't** convey state by colour alone, and never soften a red verdict or a medical decision visually.
- **Don't** write `style=` attributes in injected markup.
- **Don't** add a second lime surface or a lime fill on anything but the primary action and the "here" marks.
- **Don't** nest a bordered box inside a sheet; divide with a dashed rule instead.
