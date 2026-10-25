/* Le Sentier · étape 23 — « La paire suivante » : une paire arrive en fin de vie (suite de l'étape 9) —
 * fiche de caractéristiques sourcée (#298), retours de chaussant (#299), profil d'usage (#300),
 * plages cibles du moteur de règles (#301) et commande /shoes (#302).
 * Chiffres, libellés et règles : docs/shoes.md, docs/skills/shoe-specs.md, shoe-selection.md, shoes.md,
 * scripts/arc_shoes.py, arc_shoe_usage.py et config/shoes/rules.json.
 * Moteur : ../engine/engine.js (helpers globaux). Découpage et narration : script.json.
 * Athlète, modèles et mesures fictifs (bible de la série : Camille, mardi 29 septembre 2026).
 * Tout est dessiné au canvas (aucune capture). */
"use strict";
(() => {
const BLUE = "#6aa7e0";

const STR = {
  fr: {
    k1: "01 · FIN DE VIE", h1: "Une paire arrive au bout.",
    pair: "Crête Pro (bleue)", km: "702 km", thr: "seuil d'alerte 700 km",
    t1: "Seuil franchi", t2: "Inspection : fin de vie", t3: "Retirée dans Garmin", t3b: "retirée immédiatement",
    ask: "Par quoi la remplacer ?",
    k2: "02 · LA FICHE", h2: "Chaque valeur a sa source.",
    file: "gear/specs/crete-pro-2.md",
    cols: ["Caractéristique", "Retenue", "Type", "Autres sources"],
    rows: [
      ["drop", "8,7 mm", "measured", "marque : 6 mm"],
      ["pile du talon", "31 mm", "measured", "marque : 31 mm"],
      ["poids", "265 g", "manufacturer", "—"],
      ["crampons", "5 mm", "manufacturer", "—"],
      ["avant-pied", "standard", "athlete", "—"],
    ],
    types: { measured: "mesuré · labo", manufacturer: "marque", athlete: "vous" },
    wins: "la mesure prime", nb: "Crête Pro 3 (modèle voisin) : 272 g", nbTag: "indice en séance · jamais enregistré",
    valid: "validé ligne à ligne", none: "valeur introuvable = absente",
    k3: "03 · LE CHAUSSANT", h3: "Un retour, puis un bilan.",
    log: "/log Crête Pro : confort 8, rien à signaler", logd: "séance du 27 septembre",
    fb: "shoe_feedback", kinds: ["blister", "toe_box_tight", "heel_slip", "hot_spot", "numbness", "too_soft", "poor_grip"], kindsT: "liste fermée · jamais une devinette",
    verdict: "bilan de retraite", vrows: [["comfort_overall", "8 / 10"], ["would_rebuy", "yes"]], opts: "yes · yes_with_change · no",
    pain: "douleur", sep: "≠ retour de chaussant", sep2: "écrits séparément, jamais l'un cause de l'autre",
    k4: "04 · L'USAGE RÉEL", h4: "Ce que la paire faisait vraiment.",
    cmd4: "arc_index.py shoe-usage --gear crete-pro-2",
    uTitle: "Usage", trail: "trail", road: "route", dplus: "D+ par km", dpv: "62 m", longs: "sorties longues (> 90 min)", longsV: "9 sur 41",
    role: "rôle déduit : trail_long",
    gTitle: "Foulée par tranche d'allure", b1: "6:00–6:30 /km", b1v: "contact 242 ms · 11 séances", b2: "5:30–6:00 /km", b2v: "données insuffisantes · 2 séances",
    min3: "minimum 3 séances par tranche",
    pTitle: "Douleurs ≤ 48 h", ep: "épisodes", noRate: "pas de taux sous 5 épisodes",
    corr: "corrélation, pas causalité",
    k5: "05 · LES BESOINS", h5: "Des plages, jamais une marque.",
    cmd5: "arc_index.py shoe-needs --role trail_long",
    needs: [
      ["drop", "mm", 0, 16, 4, 12, "faible"],
      ["pile du talon", "mm", 20, 45, 25, 37, "approximation du projet"],
      ["crampons", "mm", 0, 10, 4, 6, "approximation du projet"],
    ],
    nSoft: "souplesse de la mousse", nSoftV: "souple · modérée", nSoftE: "faible",
    nToe: "avant-pied", nToeV: "standard (éprouvé)", nToeE: "avis d'experts",
    ev: "preuve", rules: "règles + références : config/shoes/rules.json",
    ach: "antécédent Achille : drop jamais abaissé", achNote: "approximation du projet",
    k6: "06 · /SHOES", h6: "La continuité d'abord.",
    shoes: "/shoes", shoesR: "Rôle : trail_long — Crête Pro 2 (seuil franchi)",
    cmpTitle: "Crête Pro 2 → version actuelle", cmpC: ["", "ancienne", "actuelle"],
    cmpRows: [["drop", "8,7", "8,7"], ["pile du talon", "31", "33"], ["crampons", "5", "5"], ["poids (g)", "265", "272"]],
    chg: "les marques changent d'une version à l'autre",
    elseT: "Sinon : 3 à 5 modèles trouvés en ligne", cand: ["Modèle A", "Modèle B", "Modèle C"], candTags: ["labo", "marque"],
    veto: "veto médical", vetoN: "si l'agent medical est activé",
    k7: "07 · LE CONFORT DÉCIDE", h7: "Puis vos pieds tranchent.",
    c1: "Essayer en magasin", c1b: "le confort décide",
    c2: "Rodage", c2b: "30 à 50 km avant la course",
    c3: "Rotation", c3b: "au moins 2 paires",
    no: ["aucun achat", "aucun prix", "aucun lien d'affiliation", "jamais une prévention de blessure"],
  },
  en: {
    k1: "01 · END OF LIFE", h1: "A pair is nearly done.",
    pair: "Crête Pro (blue)", km: "702 km", thr: "alert threshold 700 km",
    t1: "Threshold crossed", t2: "Inspection: end of life", t3: "Retired in Garmin", t3b: "retired immediately",
    ask: "What replaces it?",
    k2: "02 · THE SPEC SHEET", h2: "Every value has a source.",
    file: "gear/specs/crete-pro-2.md",
    cols: ["Feature", "Kept", "Type", "Other sources"],
    rows: [
      ["drop", "8.7 mm", "measured", "brand: 6 mm"],
      ["heel stack", "31 mm", "measured", "brand: 31 mm"],
      ["weight", "265 g", "manufacturer", "—"],
      ["lugs", "5 mm", "manufacturer", "—"],
      ["toe box", "standard", "athlete", "—"],
    ],
    types: { measured: "measured · lab", manufacturer: "brand", athlete: "you" },
    wins: "measurement wins", nb: "Crête Pro 3 (neighbouring model): 272 g", nbTag: "hint in session · never stored",
    valid: "approved line by line", none: "value not found = absent",
    k3: "03 · THE FIT", h3: "A feedback, then a verdict.",
    log: "/log Crête Pro: comfort 8, nothing to report", logd: "run of September 27",
    fb: "shoe_feedback", kinds: ["blister", "toe_box_tight", "heel_slip", "hot_spot", "numbness", "too_soft", "poor_grip"], kindsT: "closed list · never a guess",
    verdict: "retirement verdict", vrows: [["comfort_overall", "8 / 10"], ["would_rebuy", "yes"]], opts: "yes · yes_with_change · no",
    pain: "pain", sep: "≠ fit feedback", sep2: "written separately, neither is ever the cause of the other",
    k4: "04 · REAL USE", h4: "What the pair really did.",
    cmd4: "arc_index.py shoe-usage --gear crete-pro-2",
    uTitle: "Use", trail: "trail", road: "road", dplus: "climb per km", dpv: "62 m", longs: "long runs (> 90 min)", longsV: "9 of 41",
    role: "inferred role: trail_long",
    gTitle: "Stride by pace band", b1: "6:00–6:30 /km", b1v: "contact 242 ms · 11 runs", b2: "5:30–6:00 /km", b2v: "not enough data · 2 runs",
    min3: "minimum 3 runs per band",
    pTitle: "Pain ≤ 48 h", ep: "episodes", noRate: "no rate under 5 episodes",
    corr: "correlation, not causation",
    k5: "05 · THE NEEDS", h5: "Ranges, never a brand.",
    cmd5: "arc_index.py shoe-needs --role trail_long",
    needs: [
      ["drop", "mm", 0, 16, 4, 12, "low"],
      ["heel stack", "mm", 20, 45, 25, 37, "project approximation"],
      ["lugs", "mm", 0, 10, 4, 6, "project approximation"],
    ],
    nSoft: "foam softness", nSoftV: "soft · moderate", nSoftE: "low",
    nToe: "toe box", nToeV: "standard (proven)", nToeE: "expert opinion",
    ev: "evidence", rules: "rules + references: config/shoes/rules.json",
    ach: "Achilles history: drop never lowered", achNote: "project approximation",
    k6: "06 · /SHOES", h6: "Continuity first.",
    shoes: "/shoes", shoesR: "Role: trail_long — Crête Pro 2 (threshold crossed)",
    cmpTitle: "Crête Pro 2 → current version", cmpC: ["", "old", "current"],
    cmpRows: [["drop", "8.7", "8.7"], ["heel stack", "31", "33"], ["lugs", "5", "5"], ["weight (g)", "265", "272"]],
    chg: "brands change things between versions",
    elseT: "Otherwise: 3 to 5 models found online", cand: ["Model A", "Model B", "Model C"], candTags: ["lab", "brand"],
    veto: "medical veto", vetoN: "if the medical agent is enabled",
    k7: "07 · COMFORT DECIDES", h7: "Then your feet decide.",
    c1: "Try in store", c1b: "comfort decides",
    c2: "Break-in", c2b: "30 to 50 km before the race",
    c3: "Rotation", c3b: "at least 2 pairs",
    no: ["no purchase", "no price", "no affiliate link", "never injury prevention"],
  },
};

const TYPE_COL = { measured: C.teal, manufacturer: C.amber, athlete: C.accent };

/* ------------------------------- dessins locaux ------------------------------- */
function head(k, h, t) { kicker(k, seg(t, 0, 0.4)); headline(h, seg(t, 0.1, 0.7), 132, 40); fictTag(seg(t, 0.3, 0.8)); }
function label(s, x, y, k, col = C.accent) { text(s, x, y, { size: 12, weight: 600, font: MONO, color: col, alpha: k, spacing: "2px" }); }
/* Chaussure vue de profil, stylisée (centre x, sol y, échelle s). */
function shoe(x, y, s, col, alpha = 1, sole = "#0a120e") {
  ctx.save(); ctx.globalAlpha *= alpha; ctx.translate(x - 100 * s, y - 70 * s); ctx.scale(s, s);
  ctx.beginPath();
  ctx.moveTo(8, 60); ctx.lineTo(10, 18); ctx.quadraticCurveTo(12, 6, 30, 8); ctx.lineTo(62, 12);
  ctx.quadraticCurveTo(80, 36, 118, 42); ctx.quadraticCurveTo(176, 48, 196, 62); ctx.lineTo(196, 70); ctx.lineTo(8, 70); ctx.closePath();
  ctx.fillStyle = col; ctx.fill();
  rr(4, 66, 196, 14, 6); ctx.fillStyle = sole; ctx.fill(); ctx.strokeStyle = col; ctx.lineWidth = 2; ctx.stroke();
  for (let i = 0; i < 12; i++) { ctx.fillStyle = col; ctx.fillRect(12 + i * 16, 80, 8, 5); }
  ctx.restore();
}
function cross(x, y, s, col, alpha = 1) {
  line([[x - s, y - s], [x + s, y + s]], col, 3, alpha); line([[x + s, y - s], [x - s, y + s]], col, 3, alpha);
}

/* ------------------------------ 01 · fin de vie ------------------------------ */
function sEnd(t, d, cues) {
  head(S.k1, S.h1, t);
  const a0 = at(cues, 0, 0.6), a1 = at(cues, 1, 6);
  const kp = outBack(seg(t, 0.4, 1.1));
  // la paire
  panel(80, 190, 420, 330, { r: 20, fill: C.pine, stroke: C.accent, lw: 2, alpha: clamp(kp), shadow: true });
  shoe(290, 360, 1.55, BLUE, clamp(kp));
  text(S.pair, 290, 450, { size: 22, weight: 800, font: SORA, align: "center", alpha: clamp(kp) });
  text(S.km + " · " + S.thr, 290, 482, { size: 14, font: MONO, color: C.soft, align: "center", alpha: clamp(kp) });
  // les trois déclencheurs
  const items = [[S.t1, C.amber, null], [S.t2, C.red, null], [S.t3, C.teal, S.t3b]];
  items.forEach(([lab, col, sub], i) => {
    const a = a0 + 0.4 + i * 1.3, k = outCubic(seg(t, a, a + 0.5)), y = 190 + i * 104;
    if (k <= 0) return;
    line(partial([[500, 355], [550, 355], [550, y + 40], [590, y + 40]], k), col, 2);
    panel(590 + (1 - k) * 20, y, 610, 84, { r: 16, fill: C.panel, stroke: col, lw: 2, alpha: k });
    dot(628, y + 42, 12, col, k);
    text(lab, 660, y + (sub ? 38 : 50), { size: 22, weight: 800, font: SORA, alpha: k });
    if (sub) text(sub, 660, y + 66, { size: 15, font: MONO, color: C.soft, alpha: k });
  });
  // la question
  const kq = outBack(seg(t, a1, a1 + 0.6));
  if (kq > 0) {
    pill(S.ask, 640, 566, { size: 22, align: "center", alpha: clamp(kq), padX: 26, font: INTER, weight: 800 });
    shoe(1100, 560, 0.5, C.faint, 0.5 * clamp(kq));
  }
}

/* ------------------------------ 02 · la fiche ------------------------------ */
function sSpecs(t, d, cues) {
  head(S.k2, S.h2, t);
  const a0 = at(cues, 0, 0.6), a1 = at(cues, 1, 6), a2 = at(cues, 2, 10);
  const k0 = outCubic(seg(t, 0.3, 0.9));
  const xs = [112, 400, 590, 860];
  panel(80, 168, 1120, 330, { r: 18, alpha: k0 });
  text(S.file, 112, 200, { size: 13, font: MONO, color: C.faint, alpha: k0 });
  S.cols.forEach((s, i) => label(s.toUpperCase(), xs[i], 232, k0, C.faint));
  line([[100, 244], [1180, 244]], C.line, 1, k0);
  S.rows.forEach(([n, v, ty, alt], i) => {
    const a = a0 + 0.8 + i * 0.7, k = outCubic(seg(t, a, a + 0.5)), y = 282 + i * 44;
    const hot = i === 0;
    if (hot) highlight(98, y - 24, 1084, 36, seg(t, a1 + 0.2, a1 + 0.8) * (1 - seg(t, a2, a2 + 0.5)));
    text(n, xs[0], y, { size: 17, font: MONO, alpha: k });
    text(v, xs[1], y, { size: 17, weight: 800, font: SORA, alpha: k });
    pill(S.types[ty], xs[2], y - 5, { size: 12, alpha: k, color: TYPE_COL[ty], fill: "rgba(255,255,255,0.04)", stroke: TYPE_COL[ty] });
    text(alt, xs[3], y, { size: 14, font: MONO, color: hot ? C.amber : C.faint, alpha: k });
    const kc = seg(t, a2 + 0.5 + i * 0.35, a2 + 0.9 + i * 0.35);
    if (kc > 0) check(1160, y - 6, 14, C.accent, kc);
  });
  // la mesure prime
  const kw = outBack(seg(t, a1 + 0.4, a1 + 1.0));
  if (kw > 0) pill(S.wins, 1176, 200, { align: "right", size: 13, alpha: clamp(kw), color: C.teal, stroke: C.teal, fill: "rgba(95,184,160,0.08)" });
  // le voisin : un indice, jamais écrit
  const kn = outCubic(seg(t, a2, a2 + 0.6));
  if (kn > 0) {
    panel(80, 520, 700, 60, { r: 14, fill: "rgba(240,122,95,0.06)", stroke: C.red, alpha: kn });
    text(S.nb, 104, 548, { size: 16, color: C.soft, alpha: kn });
    text(S.nbTag, 104, 568, { size: 12, font: MONO, color: C.red, alpha: kn });
    const w = measure(S.nb, 16);
    line([[104, 543], [104 + w, 543]], C.red, 2, kn * seg(t, a2 + 0.6, a2 + 1.2));
  }
  const kv = outBack(seg(t, a2 + 2.2, a2 + 2.8));
  if (kv > 0) pill("✓ " + S.valid, 1176, 550, { align: "right", size: 14, alpha: clamp(kv), padX: 18 });
}

/* ------------------------------ 03 · le chaussant ------------------------------ */
function sFit(t, d, cues) {
  head(S.k3, S.h3, t);
  const a0 = at(cues, 0, 0.6), a1 = at(cues, 1, 6), a2 = at(cues, 2, 9);
  const k0 = outCubic(seg(t, 0.3, 0.9));
  // /log
  label(S.logd.toUpperCase(), 80, 188, k0, C.faint);
  const kb = typedK(t, a0 + 0.1, a0 + 1.6);
  bubble(S.log, 80, 204, 560, { side: "me", k: kb, size: 17, alpha: k0 });
  // shoe_feedback
  const kf = outCubic(seg(t, a0 + 1.8, a0 + 2.4));
  panel(80, 270, 560, 262, { r: 18, alpha: kf });
  label(S.fb.toUpperCase(), 104, 304, kf, C.accent);
  text("comfort: 8", 104, 340, { size: 18, font: MONO, alpha: kf });
  text(S.kindsT, 104, 376, { size: 13, font: MONO, color: C.faint, alpha: kf });
  let px = 104, py = 408;
  S.kinds.forEach((s, i) => {
    const w = measure(s, 13, 600, MONO) + 28;
    if (px + w > 620) { px = 104; py += 40; }
    const ki = outBack(seg(t, a0 + 2.6 + i * 0.15, a0 + 3.0 + i * 0.15));
    if (ki > 0) pill(s, px, py, { size: 13, alpha: clamp(ki) * kf, color: i < 2 ? C.amber : C.soft, stroke: i < 2 ? C.amber : C.line, fill: "rgba(255,255,255,0.03)" });
    px += w + 10;
  });
  // bilan de retraite
  const kv = outCubic(seg(t, a1 + 0.1, a1 + 0.7));
  panel(680, 188, 520, 200, { r: 18, alpha: kv });
  label(S.verdict.toUpperCase(), 704, 222, kv, C.teal);
  S.vrows.forEach(([n, v], i) => {
    const ki = outCubic(seg(t, a1 + 0.6 + i * 0.5, a1 + 1.1 + i * 0.5));
    text(n, 704, 266 + i * 40, { size: 18, font: MONO, color: C.soft, alpha: ki * kv });
    text(v, 1176, 266 + i * 40, { size: 20, weight: 800, font: SORA, color: C.accent, align: "right", alpha: ki * kv });
  });
  text(S.opts, 704, 366, { size: 12, font: MONO, color: C.faint, alpha: kv });
  // une douleur reste une douleur
  const kp = outCubic(seg(t, a2, a2 + 0.6));
  if (kp > 0) {
    panel(680, 420, 520, 112, { r: 18, fill: "rgba(240,122,95,0.06)", stroke: C.red, lw: 2, alpha: kp });
    pill("shoe_feedback", 712, 462, { size: 13, alpha: kp, color: C.accent });
    text("≠", 880, 470, { size: 26, weight: 800, font: SORA, color: C.red, align: "center", alpha: kp });
    pill(S.pain, 1000, 462, { size: 14, alpha: kp, color: C.red, stroke: C.red, fill: "rgba(240,122,95,0.08)" });
    para(S.sep2, 712, 510, 460, { size: 14, color: C.soft, alpha: kp });
  }
}
const typedK = (t, a, b) => seg(t, a, b);

/* ------------------------------ 04 · l'usage réel ------------------------------ */
function sUsage(t, d, cues) {
  head(S.k4, S.h4, t);
  const a0 = at(cues, 0, 0.6), a1 = at(cues, 1, 5), a2 = at(cues, 2, 9);
  const k0 = outCubic(seg(t, 0.3, 0.9));
  text(S.cmd4, 80, 180, { size: 13, font: MONO, color: C.faint, alpha: k0 });
  // usage
  const ku = outCubic(seg(t, a0 + 0.1, a0 + 0.7));
  panel(80, 200, 360, 340, { r: 18, alpha: ku });
  label(S.uTitle.toUpperCase(), 104, 234, ku, C.accent);
  const tb = 0.94, kk = inOut(seg(t, a0 + 0.6, a0 + 1.8));
  panel(104, 254, 312, 28, { r: 8, fill: "#22302a", stroke: false, alpha: ku });
  panel(104, 254, 312 * tb * kk, 28, { r: 8, fill: C.accent, stroke: false, alpha: ku });
  text(S.trail + " 94 %", 104, 308, { size: 15, weight: 700, alpha: ku }); text(S.road + " 6 %", 416, 308, { size: 15, color: C.soft, align: "right", alpha: ku });
  const kd = outCubic(seg(t, a0 + 1.6, a0 + 2.2));
  text(S.dpv, 104, 372, { size: 34, weight: 800, font: SORA, color: C.accent, alpha: kd * ku });
  text(S.dplus, 104, 396, { size: 13, font: MONO, color: C.soft, alpha: kd * ku });
  const kl = outCubic(seg(t, a0 + 2.2, a0 + 2.8));
  text(S.longsV, 104, 448, { size: 34, weight: 800, font: SORA, color: C.accent, alpha: kl * ku });
  text(S.longs, 104, 472, { size: 13, font: MONO, color: C.soft, alpha: kl * ku });
  const kr = outBack(seg(t, a0 + 3.2, a0 + 3.8));
  if (kr > 0) pill(S.role, 104, 512, { size: 13, alpha: clamp(kr), color: C.teal, stroke: C.teal, fill: "rgba(95,184,160,0.08)" });
  // foulée par tranche d'allure
  const kg = outCubic(seg(t, a1 + 0.1, a1 + 0.7));
  panel(470, 200, 380, 340, { r: 18, alpha: kg });
  label(S.gTitle.toUpperCase(), 494, 234, kg, C.accent);
  [[S.b1, S.b1v, true], [S.b2, S.b2v, false]].forEach(([b, v, ok], i) => {
    const ki = outCubic(seg(t, a1 + 0.6 + i * 0.8, a1 + 1.2 + i * 0.8)), y = 290 + i * 100;
    panel(494, y - 26, 332, 82, { r: 12, fill: ok ? "rgba(163,230,53,0.06)" : "rgba(255,255,255,0.02)", stroke: ok ? C.accent : C.line, alpha: ki });
    text(b, 514, y, { size: 18, weight: 800, font: MONO, alpha: ki });
    text(v, 514, y + 28, { size: 13, font: MONO, color: ok ? C.accent : C.amber, alpha: ki });
  });
  text(S.min3, 494, 508, { size: 12, font: MONO, color: C.faint, alpha: kg * seg(t, a1 + 2.4, a1 + 3.0) });
  // douleurs
  const kp = outCubic(seg(t, a2 + 0.1, a2 + 0.7));
  panel(880, 200, 320, 340, { r: 18, alpha: kp });
  label(S.pTitle.toUpperCase(), 904, 234, kp, C.amber);
  for (let i = 0; i < 5; i++) {
    const on = i < 3, ki = outBack(seg(t, a2 + 0.6 + i * 0.25, a2 + 1.0 + i * 0.25));
    const cx = 924 + i * 56;
    if (ki > 0) {
      dot(cx, 310, 20 * clamp(ki), on ? C.amber : "#22302a", kp);
      if (!on) ring(cx, 310, 20 * clamp(ki), C.line, 2, kp);
    }
  }
  text("3 / 5 " + S.ep, 904, 372, { size: 26, weight: 800, font: SORA, color: C.amber, alpha: kp * seg(t, a2 + 1.8, a2 + 2.3) });
  const kn = outBack(seg(t, a2 + 2.6, a2 + 3.2));
  if (kn > 0) {
    pill(S.noRate, 904, 424, { size: 13, alpha: clamp(kn), color: C.amber, stroke: C.amber, fill: "rgba(240,180,60,0.08)" });
    pill(S.corr, 904, 468, { size: 13, alpha: clamp(kn), color: C.red, stroke: C.red, fill: "rgba(240,122,95,0.08)" });
  }
}

/* ------------------------------ 05 · les besoins ------------------------------ */
function sNeeds(t, d, cues) {
  head(S.k5, S.h5, t);
  const a0 = at(cues, 0, 0.6), a1 = at(cues, 1, 5), a2 = at(cues, 2, 9);
  const k0 = outCubic(seg(t, 0.3, 0.9));
  text(S.cmd5, 80, 180, { size: 13, font: MONO, color: C.faint, alpha: k0 });
  panel(80, 200, 1120, 340, { r: 18, alpha: k0 });
  const bx = 400, bw = 440, x = (v, lo, hi) => bx + bw * (v - lo) / (hi - lo);
  S.needs.forEach(([n, u, lo, hi, a, b, ev], i) => {
    const ka = outCubic(seg(t, a0 + 0.4 + i * 0.6, a0 + 0.9 + i * 0.6)), y = 266 + i * 54;
    const isDrop = i === 0;
    const lock = isDrop ? inOut(seg(t, a2 + 0.3, a2 + 1.2)) : 0;
    const aa = lerp(a, 8, lock);
    text(n, 112, y + 6, { size: 18, weight: 700, alpha: ka });
    panel(bx, y - 10, bw, 22, { r: 6, fill: "#22302a", stroke: false, alpha: ka });
    panel(x(aa, lo, hi), y - 10, x(b, lo, hi) - x(aa, lo, hi), 22, { r: 6, fill: C.accent, stroke: false, alpha: ka * 0.9 });
    text(`${Math.round(aa)}–${b} ${u}`, bx + bw + 16, y + 6, { size: 15, weight: 700, font: MONO, color: C.ink, alpha: ka });
    const ke = outBack(seg(t, a1 + 0.2 + i * 0.5, a1 + 0.6 + i * 0.5));
    if (ke > 0) pill(ev, 1176, y, { align: "right", size: 12, alpha: clamp(ke), color: ev === "faible" || ev === "low" ? C.amber : C.soft, stroke: C.line, fill: C.deep });
  });
  [[S.nSoft, S.nSoftV, S.nSoftE], [S.nToe, S.nToeV, S.nToeE]].forEach(([n, v, ev], i) => {
    const ka = outCubic(seg(t, a0 + 2.2 + i * 0.5, a0 + 2.7 + i * 0.5)), y = 266 + (3 + i) * 54 - 6;
    text(n, 112, y + 6, { size: 18, weight: 700, alpha: ka });
    pill(v, bx, y, { size: 14, alpha: ka, padX: 16 });
    const ke = outBack(seg(t, a1 + 1.7 + i * 0.5, a1 + 2.1 + i * 0.5));
    if (ke > 0) pill(ev, 1176, y, { align: "right", size: 12, alpha: clamp(ke), color: ev === "faible" || ev === "low" ? C.amber : C.soft, stroke: C.line, fill: C.deep });
  });
  label(S.ev.toUpperCase(), 1176 - 70, 226, k0, C.faint);
  text(S.rules, 112, 524, { size: 12, font: MONO, color: C.faint, alpha: k0 * seg(t, a1 + 2.4, a1 + 3.0) });
  // le garde-fou Achille
  const kg = outBack(seg(t, a2, a2 + 0.6));
  if (kg > 0) {
    panel(80, 556, 760, 48, { r: 14, fill: "rgba(240,122,95,0.07)", stroke: C.red, lw: 2, alpha: clamp(kg) });
    ctx.save(); ctx.globalAlpha *= clamp(kg); ctx.translate(112, 580);
    rr(-8, -2, 16, 12, 3); ctx.fillStyle = C.red; ctx.fill();
    ctx.beginPath(); ctx.arc(0, -3, 6, Math.PI, 0); ctx.strokeStyle = C.red; ctx.lineWidth = 2.5; ctx.stroke(); ctx.restore();
    text(S.ach, 136, 586, { size: 18, weight: 700, font: SORA, alpha: clamp(kg) });
    text(S.achNote, 820, 586, { size: 12, font: MONO, color: C.faint, align: "right", alpha: clamp(kg) });
  }
}

/* ------------------------------ 06 · /shoes ------------------------------ */
function sShoes(t, d, cues) {
  head(S.k6, S.h6, t);
  const a0 = at(cues, 0, 0.6), a1 = at(cues, 1, 7), a2 = at(cues, 2, 11);
  const k0 = outCubic(seg(t, 0.3, 0.9));
  // la commande
  panel(80, 176, 1120, 76, { r: 14, fill: "#0a120e", alpha: k0 });
  text("$ ", 104, 222, { size: 20, font: MONO, color: C.faint, alpha: k0 });
  const ks = seg(t, a0 + 0.1, a0 + 0.7);
  text(typed(S.shoes, ks), 130, 222, { size: 20, weight: 700, font: MONO, color: C.accent, alpha: k0 });
  text(S.shoesR, 260, 222, { size: 15, font: MONO, color: C.soft, alpha: k0 * seg(t, a0 + 0.9, a0 + 1.4) });
  // la continuité : comparaison ligne à ligne
  const kc = outCubic(seg(t, a0 + 1.4, a0 + 2.0));
  panel(80, 272, 560, 290, { r: 18, alpha: kc });
  label(S.cmpTitle.toUpperCase(), 104, 306, kc, C.accent);
  const cx = [104, 410, 540];
  S.cmpC.forEach((s, i) => text(s, cx[i], 340, { size: 13, font: MONO, color: C.faint, align: i ? "right" : "left", alpha: kc }));
  S.cmpRows.forEach(([n, o, c], i) => {
    const ki = outCubic(seg(t, a0 + 2.2 + i * 0.5, a0 + 2.7 + i * 0.5)), y = 382 + i * 40, diff = o !== c;
    if (diff) highlight(96, y - 24, 536, 34, seg(t, a0 + 5.2, a0 + 5.8) * (1 - seg(t, a1 + 0.2, a1 + 0.8)), C.amber);
    text(n, cx[0], y, { size: 17, font: MONO, alpha: ki * kc });
    text(o, cx[1], y, { size: 18, weight: 700, align: "right", color: C.soft, alpha: ki * kc });
    text(c, cx[2], y, { size: 18, weight: 800, align: "right", color: diff ? C.amber : C.accent, alpha: ki * kc });
  });
  const kn = outBack(seg(t, a0 + 5.0, a0 + 5.6));
  if (kn > 0) pill(S.chg, 104, 538, { size: 12, alpha: clamp(kn), color: C.amber, stroke: C.amber, fill: "rgba(240,180,60,0.08)" });
  // sinon : trois à cinq modèles sourcés
  const ke = outCubic(seg(t, a1 + 0.1, a1 + 0.7));
  text(S.elseT, 680, 300, { size: 17, weight: 700, font: SORA, alpha: ke });
  S.cand.forEach((n, i) => {
    const ki = outCubic(seg(t, a1 + 0.5 + i * 0.5, a1 + 1.0 + i * 0.5)), y = 324 + i * 74;
    panel(680, y, 520, 62, { r: 14, alpha: ki });
    shoe(724, y + 38, 0.28, C.faint, ki);
    text(n, 780, y + 38, { size: 18, weight: 700, alpha: ki });
    S.candTags.forEach((g, j) => pill("✓ " + g, 960 + j * 118, y + 31, { size: 12, alpha: ki, color: j ? C.amber : C.teal, stroke: j ? C.amber : C.teal, fill: "rgba(255,255,255,0.03)" }));
    if (i === 2) {
      const kv = seg(t, a2 + 0.2, a2 + 0.8);
      if (kv > 0) {
        panel(680, y, 520, 62, { r: 14, fill: "#2a1b18", stroke: C.red, lw: 2, alpha: kv });
        cross(1160, y + 31, 10, C.red, kv);
        text(n + " · " + S.veto.toUpperCase(), 724, y + 38, { size: 15, weight: 700, font: MONO, color: C.red, alpha: kv });
      }
    }
  });
  const kvn = seg(t, a2 + 0.8, a2 + 1.4);
  text(S.vetoN, 680, 568, { size: 13, font: MONO, color: C.faint, alpha: kvn });
}

/* ------------------------------ 07 · le confort décide ------------------------------ */
function sTry(t, d, cues) {
  head(S.k7, S.h7, t);
  const a0 = at(cues, 0, 0.6), a1 = at(cues, 1, 3), a2 = at(cues, 2, 7);
  // trois cartes
  const cards = [[S.c1, S.c1b], [S.c2, S.c2b], [S.c3, S.c3b]];
  cards.forEach(([h, sub], i) => {
    const a = i === 0 ? a0 : a1 + (i - 1) * 1.6, k = outBack(seg(t, a, a + 0.6)), x = 80 + i * 380;
    if (k <= 0) return;
    panel(x, 180, 360, 250, { r: 20, fill: i === 0 ? C.pine : C.panel, stroke: i === 0 ? C.accent : C.line, lw: i === 0 ? 2 : 1, alpha: clamp(k), shadow: i === 0 });
    text(h, x + 180, 220, { size: 22, weight: 800, font: SORA, align: "center", alpha: clamp(k) });
    text(sub, x + 180, 248, { size: 14, font: MONO, color: C.soft, align: "center", alpha: clamp(k) });
    if (i === 0) { shoe(x + 180, 350, 1.0, BLUE, clamp(k)); }
    if (i === 1) {
      const kb = inOut(seg(t, a + 0.4, a + 1.6));
      panel(x + 40, 320, 280, 18, { r: 9, fill: "#22302a", stroke: false, alpha: clamp(k) });
      panel(x + 40, 320, 280 * kb, 18, { r: 9, fill: C.accent, stroke: false, alpha: clamp(k) });
      ["0", "30", "50 km"].forEach((s, j) => text(s, x + 40 + [0, 168, 280][j], 366, { size: 12, font: MONO, color: C.faint, align: j === 2 ? "right" : "center", alpha: clamp(k) }));
      line([[x + 40 + 168, 312], [x + 40 + 168, 346]], C.amber, 2, clamp(k));
    }
    if (i === 2) {
      shoe(x + 120, 360, 0.55, BLUE, clamp(k)); shoe(x + 250, 360, 0.55, TYPE_COL.manufacturer, clamp(k));
    }
  });
  // ce que le coach ne fait jamais
  S.no.forEach((s, i) => {
    const ki = outBack(seg(t, a2 + 0.2 + i * 0.7, a2 + 0.7 + i * 0.7)), y = 476 + Math.floor(i / 2) * 54, x = 80 + (i % 2) * 560;
    if (ki <= 0) return;
    panel(x, y - 24, 540, 46, { r: 14, fill: "rgba(240,122,95,0.06)", stroke: "rgba(240,122,95,0.5)", alpha: clamp(ki) });
    cross(x + 28, y - 1, 7, C.red, clamp(ki));
    text(s, x + 54, y + 6, { size: 18, weight: 700, alpha: clamp(ki) });
  });
}

ARC.episode({
  n: 23, slug: "paire-suivante",
  strings: STR,
  shots: [],
  scenes: { endlife: sEnd, specs: sSpecs, fit: sFit, usage: sUsage, needs: sNeeds, shoes: sShoes, try: sTry },
});
})();
