/* Le Sentier · étape 20 — « Quelle course, et quand ? » : agent `sports-director` (agents/sports-director.md).
 * Rôle dans le staff (quelle course et quand, avant le coach et le stratège), historique réel lu par
 * `arc_index.py history-summary`, faisabilité dite d'emblée puis format de remplacement (même course, même
 * jour, même arrivée), recherche web sourcée (« à confirmer », « non trouvé », course complète jamais en
 * tête), rôles Objectif principal / Préparation / Plaisir, calendrier calculé en Python avec les règles
 * provisoires du projet (récupération et affûtage par km-effort), consultation du médical, valeurs de
 * l'objectif proposées sans jamais écrire `active_objective.md`.
 * Courses, dates et chiffres : fictifs (Camille, Val-d'Orée) ; les jours de la semaine et les écarts sont
 * ceux que renvoie le calcul Python de l'agent pour ces dates. L'Ultra des Crêtes est celui de l'étape 14.
 * Moteur : ../engine/engine.js (helpers globaux). Découpage et narration : script.json.
 * Chaque scène reçoit (t, d, cues) : temps local, durée, répliques [{s, e, text}] —
 * at(cues, i, repli) cale une animation sur la voix, quelle que soit la langue.
 * Athlète et chiffres fictifs (bible de la série : Camille, mardi 29 septembre 2026). */
"use strict";
(() => {
const STR = {
  fr: {
    k1: "01 · LE RÔLE", h1: "Avant le plan : le choix.",
    cards: [
      ["sports-director", "Quelle course, et quand ?", "choisir"],
      ["coach", "Comment s'entraîner", "préparer"],
      ["course-strategist", "Comment la courir", "courir"],
    ],
    neww: "nouveau",
    k2: "02 · OÙ J'EN SUIS", h2: "D'abord, ce que vous avez couru.",
    ask: "Des amis font un trail en juin : 80 km, 1 500 m D+. Tu me trouves ça ?",
    cmd: "python3 scripts/arc_index.py history-summary",
    out: [
      ["plus longue sortie", "31,4 km"],
      ["plus gros D+", "1 650 m"],
      ["volume · 12 sem.", "41 km / sem."],
      ["charge", "à jour · synchro d'hier"],
    ],
    prof: [["zone fragile", "genou gauche"], ["tolérance au risque", "prudente"], ["meilleure course", "28 km"]],
    stale: "rien synchronisé depuis 7 j ? il le dit",
    k3: "03 · FAISABLE ?", h3: "Le verdict d'abord.",
    verdict: "80 km en juin, pour toi, je te le déconseille.",
    facts: ["plus longue sortie : 31 km, soit 2,5 fois moins", "Trail des Crêtes (42 km) pas encore couru", "réaliste : plutôt à l'automne 2027"],
    style: "le style change les mots, jamais ce verdict",
    same: "même course · même jour · même arrivée",
    lanes: [["les amis", "80 km · 1 500 m"], ["Camille", "35 km · 900 m"]],
    arrive: "arrivée",
    once: "1 500 m sur 80 km : ≈ 19 m D+/km, très roulant. Voulu ?",
    onceTag: "une seule fois",
    k4: "04 · DES COURSES SOURCÉES", h4: "Chaque course vient d'une page lue.",
    query: "trail · juin 2027 · ~35 km · autour de Val-d'Orée",
    web: "recherche web · comme vous",
    cols: ["course", "date", "km · D+", "inscriptions"],
    rows: [
      ["Grand Trail du Val-d'Orée", "à confirmer", "35 · 900 m", "pas encore ouvertes", "2026 : sam. 13/06 · site de l'organisateur"],
      ["Trail des Gorges d'Orée", "mer. 16/06 ?", "32 · non trouvé", "inconnu", "tombe un mercredi : à confirmer · (calendrier en ligne)"],
      ["Ronde des Hauts", "sam. 05/06", "30 · 1 100 m", "complètes", "si un dossard se libère"],
      ["Trail du Mont Aigu", "sam. 28/08", "40 · 2 000 m", "ouvertes", "site de l'organisateur ✓"],
    ],
    never: "jamais une course de mémoire", second: "↓ 2ᵉ",
    k5: "05 · LA SAISON", h5: "Un rôle par course, des écarts calculés.",
    roles: { main: "Objectif principal", prep: "Préparation", fun: "Plaisir", now: "objectif actuel" },
    roleSub: { main: "tout le plan, avec affûtage", prep: "sérieux, sans affûtage", fun: "sous l'effort de course" },
    months: ["nov.", "janv.", "mars", "mai", "juil.", "sept.", "nov."],
    races: [["Trail des Crêtes", "dim. 22/11"], ["Val-d'Orée · 35 km", "sam. 12/06"], ["Mont Aigu", "sam. 28/08"], ["Ultra des Crêtes", "sam. 30/10"]],
    recov: "récup. 4 sem.", taper: "affûtage 3 sem.", empty: "aucune course",
    py: [
      "Val-d'Orée : samedi 12/06/2027",
      "Mont Aigu : samedi 28/08/2027",
      "Ultra des Crêtes : samedi 30/10/2027",
      "Val-d'Orée -> Mont Aigu : 77 j, 11.0 sem",
      "Mont Aigu -> Ultra : 63 j, 9.0 sem",
    ],
    rule: "40 km + 2 000 m → 4 sem. de récupération",
    ruleTag: "règle provisoire du projet",
    k6: "06 · LA MAIN AU STAFF", h6: "Il propose. Vous décidez.",
    medT: "medical · consulté", medQ: "66 km, de nuit, longues descentes · genou gauche fragile",
    medA: "à revoir après les Crêtes, selon le genou", wins: "son avis l'emporte",
    file: "planning/active_objective.md", lock: "jamais modifié par l'agent",
    vals: [["Nom", "Ultra des Crêtes"], ["Date", "2027-10-30"], ["Distance", "66 km"], ["Dénivelé positif", "3 600 m"], ["Courses intermédiaires", "Mont Aigu (28/08)"]],
    yours: "valeurs à reporter vous-même",
    nos: ["rien vers la montre", "jamais en automatique", "rien de persisté"],
    next: "→ coach : construire le plan",
  },
  en: {
    k1: "01 · THE ROLE", h1: "Before the plan: the choice.",
    cards: [
      ["sports-director", "Which race, and when?", "choose"],
      ["coach", "How to train", "prepare"],
      ["course-strategist", "How to run it", "race"],
    ],
    neww: "new",
    k2: "02 · WHERE I STAND", h2: "First, what you've actually run.",
    ask: "Some friends are doing a trail race in June: 80 km, 1,500 m gain. Can you find it?",
    cmd: "python3 scripts/arc_index.py history-summary",
    out: [
      ["longest run", "31.4 km"],
      ["biggest climb", "1,650 m"],
      ["volume · 12 wk", "41 km / wk"],
      ["load", "up to date · synced yesterday"],
    ],
    prof: [["fragile area", "left knee"], ["risk tolerance", "cautious"], ["best race", "28 km"]],
    stale: "nothing synced for 7 days? it says so",
    k3: "03 · FEASIBLE?", h3: "The verdict comes first.",
    verdict: "80 km in June, for you, I'd advise against it.",
    facts: ["longest run: 31 km, 2.5 times shorter", "Trail des Crêtes (42 km) not yet run", "realistic: more like autumn 2027"],
    style: "style changes the words, never this verdict",
    same: "same event · same day · same finish line",
    lanes: [["the friends", "80 km · 1,500 m"], ["Camille", "35 km · 900 m"]],
    arrive: "finish",
    once: "1,500 m over 80 km: ≈ 19 m gain/km, very runnable. Intended?",
    onceTag: "asked once",
    k4: "04 · SOURCED RACES", h4: "Every race comes from a page it read.",
    query: "trail · June 2027 · ~35 km · around Val-d'Orée",
    web: "web search · like you would",
    cols: ["race", "date", "km · gain", "registration"],
    rows: [
      ["Grand Trail du Val-d'Orée", "to be confirmed", "35 · 900 m", "not open yet", "2026: Sat Jun 13 · organiser's site"],
      ["Trail des Gorges d'Orée", "Wed Jun 16 ?", "32 · not found", "unknown", "falls on a Wednesday: to be confirmed · (online calendar)"],
      ["Ronde des Hauts", "Sat Jun 5", "30 · 1,100 m", "sold out", "if a bib frees up"],
      ["Trail du Mont Aigu", "Sat Aug 28", "40 · 2,000 m", "open", "organiser's site ✓"],
    ],
    never: "never a race from memory", second: "↓ 2nd",
    k5: "05 · THE SEASON", h5: "One role per race, computed gaps.",
    roles: { main: "Main objective", prep: "Preparation", fun: "Fun", now: "current objective" },
    roleSub: { main: "the whole plan, with a taper", prep: "run seriously, no taper", fun: "below race effort" },
    months: ["Nov", "Jan", "Mar", "May", "Jul", "Sep", "Nov"],
    races: [["Trail des Crêtes", "Sun Nov 22"], ["Val-d'Orée · 35 km", "Sat Jun 12"], ["Mont Aigu", "Sat Aug 28"], ["Ultra des Crêtes", "Sat Oct 30"]],
    recov: "recovery 4 wk", taper: "taper 3 wk", empty: "no race",
    py: [
      "Val-d'Orée : samedi 12/06/2027",
      "Mont Aigu : samedi 28/08/2027",
      "Ultra des Crêtes : samedi 30/10/2027",
      "Val-d'Orée -> Mont Aigu : 77 j, 11.0 sem",
      "Mont Aigu -> Ultra : 63 j, 9.0 sem",
    ],
    rule: "40 km + 2,000 m → 4 weeks of recovery",
    ruleTag: "provisional project rule",
    k6: "06 · BACK TO THE STAFF", h6: "It proposes. You decide.",
    medT: "medical · consulted", medQ: "66 km, at night, long descents · fragile left knee",
    medA: "review after the Crêtes, depending on the knee", wins: "its word wins",
    file: "planning/active_objective.md", lock: "never edited by the agent",
    vals: [["Nom", "Ultra des Crêtes"], ["Date", "2027-10-30"], ["Distance", "66 km"], ["Dénivelé positif", "3 600 m"], ["Courses intermédiaires", "Mont Aigu (28/08)"]],
    yours: "values for you to fill in",
    nos: ["nothing to the watch", "never on autopilot", "nothing persisted"],
    next: "→ coach: build the plan",
  },
};

const RED = { color: C.red, fill: "rgba(240,122,95,0.08)", stroke: "rgba(240,122,95,0.5)" };
const AMBER = { color: C.amber, fill: "rgba(240,180,60,0.08)", stroke: "rgba(240,180,60,0.45)" };
const TEAL = { color: C.teal, fill: "rgba(95,184,160,0.08)", stroke: "rgba(95,184,160,0.4)" };
const ROLE_COL = { main: C.accent, prep: C.teal, fun: C.amber, now: C.soft };

/* ------------------------------- dessins locaux ------------------------------- */
function head(k, h, t) { kicker(k, seg(t, 0, 0.4)); headline(h, seg(t, 0.1, 0.7)); fictTag(seg(t, 0.3, 0.8)); }
function cross(x, y, s, col, alpha = 1) {
  line([[x - s, y - s], [x + s, y + s]], col, 3, alpha); line([[x + s, y - s], [x - s, y + s]], col, 3, alpha);
}
/* Petit drapeau de course (piquet + fanion). */
function flag(x, y, col, k) {
  if (k <= 0) return;
  line([[x, y], [x, y - 34 * k]], C.soft, 2, clamp(k));
  ctx.save(); ctx.globalAlpha *= clamp(k); ctx.beginPath();
  ctx.moveTo(x, y - 34 * k); ctx.lineTo(x + 18 * k, y - 28 * k); ctx.lineTo(x, y - 22 * k); ctx.closePath();
  ctx.fillStyle = col; ctx.fill(); ctx.restore();
}

/* ------------------------------ 01 · le rôle ------------------------------ */
function sStaff(t, d, cues) {
  head(S.k1, S.h1, t);
  const a0 = at(cues, 0, 0.6), a1 = at(cues, 1, 5);
  const cw = 340, ch = 230, gap = 40, y0 = 250;
  // les trois cartes : le directeur sportif glisse en tête à la seconde réplique
  const kIn = outCubic(seg(t, a1, a1 + 0.8));
  S.cards.forEach(([agent, q, verb], i) => {
    const sd = i === 0;
    const k = sd ? kIn : outCubic(seg(t, a0 + 0.2 + i * 0.5, a0 + 0.8 + i * 0.5));
    if (k <= 0) return;
    // avant l'arrivée du directeur sportif, coach et stratège occupent les deux dernières places
    const slot = i, x = 80 + slot * (cw + gap), y = y0 + (1 - k) * (sd ? -40 : 24);
    panel(x, y, cw, ch, { r: 18, fill: sd ? "rgba(163,230,53,0.07)" : C.panel, stroke: sd ? C.accent : C.line, lw: sd ? 2 : 1, alpha: k, shadow: sd });
    text(agent, x + 26, y + 44, { size: 16, weight: 600, font: MONO, color: sd ? C.accent : C.soft, alpha: k });
    para(q, x + 26, y + 104, cw - 52, { size: 28, weight: 800, font: SORA, alpha: k, lh: 34 });
    text(verb.toUpperCase(), x + 26, y + ch - 26, { size: 12, weight: 600, font: MONO, color: C.faint, alpha: k, spacing: "2px" });
    if (sd) pill(S.neww, x + cw - 24, y + 38, { size: 12, align: "right", alpha: seg(t, a1 + 0.6, a1 + 1.1) });
  });
  // flèches choisir → préparer → courir
  for (let i = 0; i < 2; i++) {
    const ka = seg(t, (i ? a0 + 1.4 : a1 + 0.9), (i ? a0 + 1.9 : a1 + 1.4));
    const x = 80 + (i + 1) * (cw + gap) - gap + 6;
    arrow(x, y0 + ch / 2, x + gap - 12, y0 + ch / 2, ka, C.faint);
  }
  highlight(80, y0, cw, ch, seg(t, a1 + 1.4, a1 + 2.0));
}

/* ------------------------------ 02 · l'historique ------------------------------ */
function sHistory(t, d, cues) {
  head(S.k2, S.h2, t);
  const a0 = at(cues, 0, 0.6), a1 = at(cues, 1, 6);
  // la demande de Camille
  const kb = outCubic(seg(t, a0 + 0.2, a0 + 0.8));
  if (kb > 0) bubble(S.ask, 640, 176 + (1 - kb) * 12, 560, { side: "me", size: 17, alpha: kb, k: seg(t, a0 + 0.3, a0 + 2.6) });
  // l'historique réel
  const T = a1 - 0.3, kt = outCubic(seg(t, T, T + 0.5));
  if (kt > 0) {
    terminal(80, 270, 720, 250, t, [
      { p: "$ ", s: S.cmd, a: T + 0.2, b: T + 1.2 },
      ...S.out.map(([l, v], i) => ({ s: `${l.padEnd(20, " ")}${v}`, a: T + 1.5 + i * 0.6, b: T + 1.9 + i * 0.6, c: i < 3 ? C.ink : C.teal })),
    ], { alpha: kt, size: 16, lh: 34, title: "arc" });
    highlight(98, 336, 360, 70, seg(t, T + 3.0, T + 3.6) * (1 - seg(t, T + 5.2, T + 5.8)));
  }
  // le profil : zone fragile, tolérance au risque
  S.prof.forEach(([l, v], i) => {
    const kk = outCubic(seg(t, a1 + 3.6 + i * 0.5, a1 + 4.1 + i * 0.5));
    if (kk <= 0) return;
    const y = 300 + i * 90;
    panel(840, y, 360, 70, { r: 14, fill: i === 0 ? "rgba(240,180,60,0.07)" : C.panel, stroke: i === 0 ? C.amber : C.line, alpha: kk });
    text(l.toUpperCase(), 864, y + 28, { size: 11, weight: 600, font: MONO, color: i === 0 ? C.amber : C.faint, alpha: kk, spacing: "1px" });
    text(v, 864, y + 54, { size: 19, weight: 700, alpha: kk });
  });
  pill(S.stale, 80, 560, { size: 13, alpha: seg(t, a1 + 5.2, a1 + 5.8), ...TEAL });
}

/* ------------------------------ 03 · faisable ? ------------------------------ */
function sVerdict(t, d, cues) {
  head(S.k3, S.h3, t);
  const a0 = at(cues, 0, 0.6), a1 = at(cues, 1, 6);
  // le verdict, d'emblée, faits à l'appui
  const kv = outBack(seg(t, a0 + 0.2, a0 + 0.9));
  if (kv > 0) {
    const k = clamp(kv), fade = 1 - 0.45 * seg(t, a1, a1 + 0.6);
    panel(80, 176, 560, 236, { r: 18, fill: "rgba(240,122,95,0.06)", stroke: C.red, lw: 2, alpha: k * fade });
    cross(112, 214, 9, C.red, k * fade);
    para(S.verdict, 136, 222, 480, { size: 23, weight: 800, font: SORA, alpha: k * fade, lh: 30 });
    S.facts.forEach((f, i) => {
      const kk = seg(t, a0 + 1.4 + i * 0.6, a0 + 1.9 + i * 0.6);
      dot(112, 312 + i * 30, 3.5, i === 2 ? C.teal : C.soft, kk * fade);
      text(f, 128, 318 + i * 30, { size: 15, color: i === 2 ? C.teal : C.soft, alpha: kk * fade });
    });
  }
  pill(S.style, 80, 446, { size: 12, alpha: seg(t, a0 + 3.4, a0 + 3.9) * (1 - 0.5 * seg(t, a1, a1 + 0.6)), ...AMBER });
  // même course, même jour, même arrivée : deux tracés qui se rejoignent
  const T = a1, kr = seg(t, T + 0.2, T + 0.8);
  if (kr > 0) {
    const fx = 1150, fy = 336;
    panel(680, 176, 520, 300, { r: 18, alpha: kr });
    text(S.same, 940, 210, { size: 14, weight: 600, font: MONO, color: C.accent, align: "center", alpha: kr });
    const paths = [
      [[860, 262], [920, 246], [980, 286], [1030, 240], [1080, 282], [1110, 262], [fx, fy]],
      [[860, 432], [940, 418], [1010, 424], [1070, 392], [1110, 366], [fx, fy]],
    ];
    paths.forEach((p, i) => {
      const kp = outCubic(seg(t, T + 0.8 + i * 0.4, T + 2.6 + i * 0.4));
      line(partial(p, kp), i ? C.accent : C.soft, i ? 4 : 2.5, kr, i ? null : [6, 6]);
      const [nm, val] = S.lanes[i];
      const ly = i ? 426 : 256;
      text(nm, 704, ly, { size: 13, weight: 600, font: MONO, color: i ? C.accent : C.soft, alpha: seg(t, T + 1.0 + i * 0.4, T + 1.5 + i * 0.4) });
      text(val, 704, ly + 20, { size: 15, weight: 700, color: i ? C.ink : C.soft, alpha: seg(t, T + 1.0 + i * 0.4, T + 1.5 + i * 0.4) });
    });
    const kf = outBack(seg(t, T + 2.8, T + 3.4));
    if (kf > 0) { flag(fx, fy, C.accent, clamp(kf)); text(S.arrive, fx, fy - 44, { size: 12, font: MONO, color: C.accent, align: "center", alpha: clamp(kf) }); }
  }
  // une seule question sur des chiffres étonnants
  const kq = outCubic(seg(t, a1 + 4.6, a1 + 5.2));
  if (kq > 0) {
    panel(80, 520, 1120, 86, { r: 16, fill: C.panel2, alpha: kq });
    text("?", 112, 576, { size: 34, weight: 800, font: SORA, color: C.amber, alpha: kq });
    text(S.once, 150, 572, { size: 19, weight: 600, alpha: kq });
    pill(S.onceTag, 1176, 563, { size: 12, align: "right", alpha: seg(t, a1 + 5.6, a1 + 6.1), ...AMBER });
  }
}

/* ------------------------------ 04 · la recherche ------------------------------ */
function sSearch(t, d, cues) {
  head(S.k4, S.h4, t);
  const a0 = at(cues, 0, 0.6), a1 = at(cues, 1, 6);
  // champ de recherche
  const ks = outCubic(seg(t, a0, a0 + 0.5));
  panel(80, 168, 760, 52, { r: 26, fill: C.panel2, alpha: ks });
  ring(110, 192, 9, C.soft, 2, ks); line([[117, 199], [124, 206]], C.soft, 2, ks);
  text(typed(S.query, seg(t, a0 + 0.4, a0 + 2.2)), 138, 200, { size: 17, font: MONO, alpha: ks });
  pill(S.web, 1200, 194, { size: 13, align: "right", alpha: seg(t, a0 + 1.6, a0 + 2.1), ...TEAL });
  // tableau des candidates
  const x0 = 80, y0 = 244, cx = [x0 + 24, x0 + 420, x0 + 640, x0 + 860], rh = 86;
  const kh = seg(t, a0 + 2.4, a0 + 2.9);
  S.cols.forEach((c, i) => text(c.toUpperCase(), cx[i], y0 + 12, { size: 11, weight: 600, font: MONO, color: C.faint, alpha: kh, spacing: "1px" }));
  // états mis en évidence sur la seconde réplique : à confirmer, mercredi, non trouvé, complète
  const T = a1;
  S.rows.forEach(([name, date, kmd, reg, note], i) => {
    const kk = outCubic(seg(t, a0 + 2.8 + i * 0.5, a0 + 3.3 + i * 0.5)), y = y0 + 30 + i * rh + (1 - kk) * 10;
    if (kk <= 0) return;
    const full = i === 2, demote = full && t > T + 4.4;
    panel(x0, y, 1120, rh - 12, { r: 14, fill: C.panel, alpha: kk * (demote ? 0.55 : 1) });
    text(name, cx[0], y + 34, { size: 18, weight: 700, alpha: kk * (demote ? 0.6 : 1) });
    text(note, cx[0], y + 60, { size: 13, font: MONO, color: i === 3 ? C.teal : C.faint, alpha: kk * seg(t, T - 0.4 + i * 0.2, T + 0.2 + i * 0.2) });
    const kc = seg(t, T + 0.8, T + 1.3), ki = seg(t, T + 1.8, T + 2.3);
    const dateCol = (i === 0 || i === 1) && kc > 0 ? C.amber : C.ink;
    text(date, cx[1], y + 34, { size: 16, weight: 600, font: MONO, color: dateCol, alpha: kk });
    const kmCol = i === 1 && ki > 0 ? C.amber : C.ink;
    text(kmd, cx[2], y + 34, { size: 16, font: MONO, color: kmCol, alpha: kk });
    const regO = full ? RED : i === 3 ? { color: C.accent } : i === 1 ? { color: C.soft, fill: C.panel2, stroke: C.line } : TEAL;
    pill(reg, cx[3], y + 28, { size: 13, alpha: kk, ...regO });
    if (demote) {
      const kd = seg(t, T + 4.4, T + 4.9);
      pill(S.second, x0 + 1100, y + 28, { size: 12, align: "right", alpha: kd, ...RED });
    }
  });
  // la course recommandée (juin) est une course où l'on peut encore s'inscrire
  highlight(x0, y0 + 30, 1120, rh - 12, seg(t, T + 5.0, T + 5.6));
  pill(S.never, 80, 640, { size: 13, alpha: seg(t, a0 + 4.6, a0 + 5.1), ...AMBER });
}

/* ------------------------------ 05 · la saison ------------------------------ */
function sSeason(t, d, cues) {
  head(S.k5, S.h5, t);
  const a0 = at(cues, 0, 0.6), a1 = at(cues, 1, 4.5);
  // frise : du 1er nov. 2026 au 15 nov. 2027 (380 jours)
  const gx = 100, gw = 1080, gy = 330;
  const X = day => gx + day / 380 * gw;
  const kx = outCubic(seg(t, a0, a0 + 0.6));
  line([[gx, gy], [gx + gw * kx, gy]], C.line, 3, 1);
  S.months.forEach((m, i) => {
    const dd = [0, 61, 120, 181, 242, 304, 365][i];
    text(m, X(dd), gy + 28, { size: 12, font: MONO, color: C.faint, align: "center", alpha: kx });
    line([[X(dd), gy - 5], [X(dd), gy + 5]], C.line, 2, kx);
  });
  text("2027", X(61), gy + 46, { size: 11, font: MONO, color: C.faint, align: "center", alpha: kx });
  // jours depuis le 1er nov. 2026 : 22/11/26 = 21, 12/06/27 = 223, 28/08/27 = 300, 30/10/27 = 363
  const RACES = [[21, "now"], [223, "fun"], [300, "prep"], [363, "main"]];
  // fenêtres : récupération après Mont Aigu (4 sem.) puis affûtage de l'ultra (3 sem.), sans chevauchement
  const kw = outCubic(seg(t, a1 + 2.6, a1 + 3.2));
  if (kw > 0) {
    ctx.save(); ctx.globalAlpha *= kw * 0.22; ctx.fillStyle = C.teal; ctx.fillRect(X(300), gy - 60, X(328) - X(300), 60); ctx.restore();
    ctx.save(); ctx.globalAlpha *= kw * 0.22; ctx.fillStyle = C.accent; ctx.fillRect(X(342), gy - 60, X(363) - X(342), 60); ctx.restore();
    text(S.recov, X(314), gy - 70, { size: 11, font: MONO, color: C.teal, align: "center", alpha: kw });
    text(S.taper, X(352), gy - 86, { size: 11, font: MONO, color: C.accent, align: "center", alpha: kw });
    text(S.empty, X(352), gy - 70, { size: 11, font: MONO, color: C.accent, align: "center", alpha: kw });
  }
  RACES.forEach(([dd, role], i) => {
    const kk = outBack(seg(t, a0 + 0.6 + i * 0.45, a0 + 1.1 + i * 0.45));
    if (kk <= 0) return;
    const col = ROLE_COL[role];
    flag(X(dd), gy, col, clamp(kk));
    dot(X(dd), gy, 6, col, clamp(kk));
    const [nm, dt] = S.races[i], ly = gy + 80;
    const ax = i >= 2 ? "right" : i === 0 ? "left" : "center", lx = X(dd) + (i >= 2 ? 12 : i === 0 ? -12 : 0);
    text(nm, lx, ly, { size: 15, weight: 700, align: ax, alpha: clamp(kk) });
    text(dt, lx, ly + 22, { size: 13, font: MONO, color: C.soft, align: ax, alpha: clamp(kk) });
    pill(S.roles[role], lx, ly + 52, { size: 12, align: ax, alpha: clamp(kk), color: col, fill: C.panel2, stroke: col });
  });
  // signification des rôles, la première fois
  ["main", "prep", "fun"].forEach((r, i) => {
    const kk = seg(t, a0 + 2.8 + i * 0.4, a0 + 3.3 + i * 0.4);
    text(`${S.roles[r]} : ${S.roleSub[r]}`, 100 + i * 370, 196, { size: 14, color: ROLE_COL[r], alpha: kk });
  });
  // le calcul Python, jamais de tête
  const T = a1, kt = outCubic(seg(t, T, T + 0.5));
  if (kt > 0) {
    terminal(80, 510, 640, 166, t, S.py.map((s, i) => ({ s, a: T + 0.4 + i * 0.35, b: T + 0.7 + i * 0.35, c: i < 3 ? C.ink : C.accent })),
      { alpha: kt, size: 13, lh: 22, title: "python3 -c …" });
  }
  const kr = outCubic(seg(t, a1 + 3.6, a1 + 4.2));
  if (kr > 0) {
    panel(760, 530, 440, 120, { r: 16, alpha: kr });
    text(S.rule, 784, 576, { size: 17, weight: 700, alpha: kr });
    pill(S.ruleTag, 784, 616, { size: 12, alpha: kr, ...AMBER });
  }
}

/* ------------------------------ 06 · la main au staff ------------------------------ */
function sHandoff(t, d, cues) {
  head(S.k6, S.h6, t);
  const a0 = at(cues, 0, 0.6), a1 = at(cues, 1, 6);
  // consultation du médical
  const km = outCubic(seg(t, a0 + 0.2, a0 + 0.8));
  if (km > 0) {
    panel(80, 176, 520, 250, { r: 18, alpha: km });
    text(S.medT, 104, 214, { size: 15, weight: 600, font: MONO, color: C.teal, alpha: km });
    para(S.medQ, 104, 254, 470, { size: 16, color: C.soft, alpha: seg(t, a0 + 0.8, a0 + 1.3), lh: 22 });
    const ka = outCubic(seg(t, a0 + 2.4, a0 + 3.0));
    if (ka > 0) {
      bubble(S.medA, 104, 316, 470, { size: 16, alpha: ka, k: seg(t, a0 + 2.6, a0 + 4.0) });
      pill(S.wins, 104, 398, { size: 13, alpha: seg(t, a0 + 4.2, a0 + 4.7), ...TEAL });
    }
  }
  // les valeurs proposées, jamais écrites par l'agent
  const T = a1, kf = outCubic(seg(t, T, T + 0.6));
  if (kf > 0) {
    panel(640, 176, 560, 330, { r: 18, fill: "#0a120e", alpha: kf, shadow: true });
    text(S.file, 664, 212, { size: 14, weight: 600, font: MONO, color: C.faint, alpha: kf });
    // cadenas
    const lx = 1170, ly = 206;
    ctx.save(); ctx.globalAlpha *= kf; ctx.beginPath(); ctx.arc(lx, ly - 6, 7, Math.PI, 0); ctx.strokeStyle = C.amber; ctx.lineWidth = 2.5; ctx.stroke(); ctx.restore();
    panel(lx - 10, ly - 6, 20, 16, { r: 3, fill: C.amber, stroke: false, alpha: kf });
    S.vals.forEach(([l, v], i) => {
      const kk = seg(t, T + 0.6 + i * 0.35, T + 1.0 + i * 0.35), y = 256 + i * 40;
      text(`- **${l}** :`, 664, y, { size: 15, font: MONO, color: C.soft, alpha: kf * kk });
      text(v, 664 + measure(`- **${l}** : `, 15, 400, MONO), y, { size: 15, weight: 700, font: MONO, color: C.accent, alpha: kf * kk });
    });
    pill(S.yours, 664, 474, { size: 13, alpha: kf * seg(t, T + 2.6, T + 3.1), ...AMBER });
    text(S.lock, 1176, 474 + 5, { size: 12, font: MONO, color: C.amber, align: "right", alpha: kf * seg(t, T + 2.8, T + 3.3) });
  }
  // ce qu'il ne fait jamais
  S.nos.forEach((s, i) => {
    const kk = outCubic(seg(t, T + 3.8 + i * 0.4, T + 4.3 + i * 0.4));
    if (kk <= 0) return;
    const x = 80 + i * 280;
    cross(x + 12, 560, 6, C.red, kk);
    text(s, x + 30, 566, { size: 16, alpha: kk });
  });
  const kc = outBack(seg(t, T + 5.8, T + 6.4));
  if (kc > 0) pill(S.next, 1200, 560, { size: 16, align: "right", alpha: clamp(kc) });
  highlight(80, 176, 520, 250, seg(t, a0 + 4.4, a0 + 5.0) * (1 - seg(t, T - 0.4, T)), C.teal);
}

ARC.episode({
  n: 20, slug: "directeur-sportif",
  strings: STR,
  shots: [],
  scenes: { staff: sStaff, history: sHistory, verdict: sVerdict, search: sSearch, season: sSeason, handoff: sHandoff },
});
})();
