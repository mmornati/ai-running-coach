---
version: 1
slug: "web-index-html"
primary_target: "web/index.html"
related_targets: ["web/chat.html"]
---

# Tableau de bord — design bêta « Roadbook »

Scope: the local dashboard (`web/index.html`, `web/chat.html`) rebuilt as an installable PWA, phone first and web second, shipped behind an opt-in "test the new beta design" switch. The current UI stays the default. Visitor mode: **Operate**.

Audience and job: a francophone trail runner opens the app each morning, often on a phone in dim light before running, to answer "what do I do today and why". Less often, at a desk, they review the week, their form, and the race. Constraints: no build step, no npm, stdlib Python server, read-only data, the same `/api/*` endpoints, and the same French copy and units. Medical decisions and red verdicts must never be softened by the visuals. The palette is pinned: pine, deep pine, lime (rare, action and "you are here" only), stone, and the dark slate scheme.

Must fix from the incumbent: 15 sections in a sideways tab strip on mobile; empty right half on wide screens; raw `arc` keys shown to the athlete on Aujourd'hui.

Open decisions: how far the first beta milestone reaches beyond Aujourd'hui, Semaine and the chat (the other views are re-skinned on the roadbook tokens); what the service worker caches behind Authentik.

## Direction contract

THESIS: the app is the athlete's season roadbook, with the training block drawn as an elevation profile cut into sections, ending at the race finish. It refuses the category's stacked card feed with ring gauges.

OWN-WORLD: laminated roadbook sheets on stone (deep pine in the dark scheme), pine ink, section ticks and kilometre-style date marks along a continuous profile line. Lime appears only as the "vous êtes ici" marker and the primary action. Aid-station sheets act as cards: a ruled header band, then cut-off rows set in tabular numerals. Guardrails are drawn as cut-offs ("barrières"), each decision is signed with its trigger plate (trigger and outcome; the decision data records no agent), and session status restyles its row in place.

STORY: the athlete sees where today sits in the block, what the coach decided and why in plain words, and what the next cut-off is. They log, ask the coach, or open the session.

FIRST VIEWPORT: on phone, the block profile is a full-width ribbon at the top (base, development, specific, taper, race day), with the marker on today and J-54 to the right. Below it, today's aid-station sheet shows the verdict at display size, its one-sentence reason, then HRV, resting HR and readiness as cut-off rows, then the session. A bottom bar holds the sections Aujourd'hui, Semaine, Santé, Course and Coach. On web, the profile spans the top, the sheet sits on the left, and the week rail sits on the right.

FORM: race roadbook, position 1 on my ordered list (the pick card), seed key 23cb8da0.

FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance
