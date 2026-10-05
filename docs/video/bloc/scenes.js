/* Le Sentier · étape 15 — « Construire son bloc » : gabarits de périodisation (#189), squelette de bloc
 * `plan-skeleton` (#190), frise du bloc sur le tableau de bord (#193), renforcement par phase (#191) et
 * prévention ciblée (#192). La frise et la semaine montrées sont celles du tableau de bord (captures réelles
 * d'une variante du workspace fictif dont le squelette est écrit par le vrai `plan-skeleton --write`,
 * scripts/video_demo_workspace.py) ; les chiffres du squelette sont ceux de la vraie commande.
 * Moteur : ../engine/engine.js (helpers globaux). Découpage et narration : script.json.
 * Chaque scène reçoit (t, d, cues) : temps local, durée, répliques [{s, e, text}] —
 * at(cues, i, repli) cale une animation sur la voix, quelle que soit la langue.
 * Athlète et chiffres fictifs (bible de la série : Camille, mardi 29 septembre 2026). */
"use strict";
(() => {
/* Teintes des phases : celles de la frise du tableau de bord. */
const PH = { base: "#7fc49a", dev: "#6ea6e3", spec: "#e8a45c", taper: "#b39ddb", rec: "#5fc4c0" };
const STR = {
  fr: {
    k1: "01 · GABARITS", h1: "Un bloc à partir de données.",
    tpl: [["trail_court", "jusqu'à 30 km", "8–16 sem."], ["marathon_trail", "30–60 km", "12–20 sem."], ["ultra_80_100", "60–130 km", "16–24 sem."], ["cent_miles", "130 km et +", "20–29 sem."], ["route_semi", "15–30 km", "8–16 sem."], ["route_marathon", "30–60 km", "12–20 sem."]],
    phases: ["Base", "Développement", "Spécifique", "Affûtage", "Récupération"],
    peakT: "Le pic se déduit", held: "volume tenu", heldV: "4 h 40", fac: "× facteur du gabarit", peakV: "5 h 18", peakN: "jamais plus · jamais inventé",
    guard: "chaque semaine du gabarit vérifiée contre les garde-fous",
    d0: "5 oct.", d1: "28 déc.",
    k2: "02 · LE SQUELETTE", h2: "Une simulation, rien n'est écrit.",
    cmdT: "simulation", dry: "DRY RUN · rien n'est écrit sans --write",
    lines: ["Marathon trail — 12 semaines du 5 oct. au 21 déc.", "Volume tenu : 4 h 40/sem · pic 5 h 18", "Garde-fous : 12 conformes, aucune semaine bloquée"],
    inT: "Entrées", ins: [["Gabarit", "marathon_trail"], ["Date de course", "27 décembre"], ["Volume tenu", "4 h 40 / sem"], ["Disponibilité", "profil de Camille"]],
    fc: "Forme prévue le jour J : −9,5", fcN: "estimation, pas une mesure",
    k3: "03 · HONNÊTE", h3: "Trop court : le coach le dit.",
    sh: ["Marathon trail", "7 semaines → 12 exigées"], shErr: "Squelette indisponible (too_short)", shMin: "aucune compression sous les minima", shEarly: "course au plus tôt la semaine du 21 déc.", shOpts: "options : format plus court · autre date · bloc sans gabarit",
    weeks7: "7 semaines", weeks12: "+ 5 → 12 semaines",
    k4: "04 · UN OUI", h4: "Écrit seulement sur votre accord.",
    ask: "Écrire le squelette ?", yes: "oui", no: "non", written: "écrit", refused: "si un fichier existe : refusé", never: "jamais d'écrasement", validated: "bloc arc validé",
    rwT: "Semaine de course", rw: ["jusqu'à 3 footings", "la veille : libre", "course"], prT: "Après la course", pr: "aucune course à pied pendant 3 jours",
    days: ["L", "M", "M", "J", "V", "S", "D"],
    k5: "05 · LA FRISE", h5: "Le bloc d'un coup d'œil.",
    c1: "phase = teinte", c2: "volume prévu = hauteur", c3: "course", c4: "semaine en cours", c5: "créneaux à habiller",
    k6: "06 · RENFORCEMENT", h6: "La phase décide du programme.",
    prog: [["Base", "force maximale", PH.base], ["Développement", "force-endurance", PH.dev], ["Spécifique", "excentrique, pliométrie", PH.spec], ["Affûtage", "entretien · séries × 0,67", PH.taper], ["Récupération", "mobilité", PH.rec]],
    place: "jamais la veille d'une séance de qualité", noEq: "matériel manquant : repli, dit explicitement",
    pushT: "Pousser vers la montre ?", pushL: ["Renforcement · spécifique", "1 à 2 séances / semaine"], headless: "jamais en mode automatique",
    k7: "07 · PRÉVENTION", h7: "Observer, consulter, ou une routine douce.",
    lane: [
      ["Gêne légère, pas encore confirmée", "observe", "aucun exercice · trois questions : nouvelle ? vive ? gonflée ?", C.amber],
      ["Vive, aggravée, > 7 jours, ≥ 7/10", "consult", "aucun exercice · consulter un professionnel de santé", C.red],
      ["Légère (≤ 3/10), confirmée, stable", "routine douce", "2 séries, sans impact, ni pliométrie ni excentrique", C.teal],
    ],
    nm: "Ce n'est pas un avis médical", nd: "jamais un diagnostic · seules des zones anatomiques sont nommées",
    k8: "08 · LES PAGES", h8: "Deux pages à garder sous la main.",
    pages: [["Gabarits de périodisation", "formats, phases, squelette de bloc, garde-fous", "plans"], ["Renforcement", "bibliothèque, programmes par phase, prévention ciblée", "strength"]],
  },
  en: {
    k1: "01 · TEMPLATES", h1: "A block built from data.",
    tpl: [["trail_court", "up to 30 km", "8–16 wk"], ["marathon_trail", "30–60 km", "12–20 wk"], ["ultra_80_100", "60–130 km", "16–24 wk"], ["cent_miles", "130 km and up", "20–29 wk"], ["route_semi", "15–30 km", "8–16 wk"], ["route_marathon", "30–60 km", "12–20 wk"]],
    phases: ["Base", "Development", "Specific", "Taper", "Recovery"],
    peakT: "The peak is derived", held: "held volume", heldV: "4 h 40", fac: "× template factor", peakV: "5 h 18", peakN: "never more · never invented",
    guard: "every template week checked against the guardrails",
    d0: "Oct 5", d1: "Dec 28",
    k2: "02 · THE SKELETON", h2: "A dry run, nothing is written.",
    cmdT: "dry run", dry: "DRY RUN · nothing is written without --write",
    lines: ["Marathon trail — 12 weeks from Oct 5 to Dec 21", "Held volume: 4 h 40/wk · peak 5 h 18", "Guardrails: 12 compliant, no blocked week"],
    inT: "Inputs", ins: [["Template", "marathon_trail"], ["Race date", "December 27"], ["Held volume", "4 h 40 / wk"], ["Availability", "Camille's profile"]],
    fc: "Forecast form on race day: −9.5", fcN: "an estimate, not a measurement",
    k3: "03 · HONEST", h3: "Too short: the coach says so.",
    sh: ["Marathon trail", "7 weeks → 12 required"], shErr: "Skeleton unavailable (too_short)", shMin: "no squeezing below the minimums", shEarly: "earliest race: week of Dec 21", shOpts: "options: shorter format · another date · block without template",
    weeks7: "7 weeks", weeks12: "+ 5 → 12 weeks",
    k4: "04 · A YES", h4: "Written only on your say-so.",
    ask: "Write the skeleton?", yes: "yes", no: "no", written: "written", refused: "if a file exists: refused", never: "never overwrites", validated: "arc block validated",
    rwT: "Race week", rw: ["up to 3 easy runs", "day before: free", "race"], prT: "After the race", pr: "no running for 3 days",
    days: ["M", "T", "W", "T", "F", "S", "S"],
    k5: "05 · THE TIMELINE", h5: "The block at a glance.",
    c1: "phase = tint", c2: "planned volume = height", c3: "race", c4: "current week", c5: "slots to fill in",
    k6: "06 · STRENGTH", h6: "The phase picks the programme.",
    prog: [["Base", "maximal strength", PH.base], ["Development", "strength endurance", PH.dev], ["Specific", "eccentric, plyometrics", PH.spec], ["Taper", "maintenance · sets × 0.67", PH.taper], ["Recovery", "mobility", PH.rec]],
    place: "never the day before a quality session", noEq: "missing equipment: fallback, said out loud",
    pushT: "Push to the watch?", pushL: ["Strength · specific", "1 to 2 sessions / week"], headless: "never in automatic mode",
    k7: "07 · PREVENTION", h7: "Observe, consult, or a gentle routine.",
    lane: [
      ["Mild niggle, not confirmed yet", "observe", "no exercise · three questions: new? sharp? swollen?", C.amber],
      ["Sharp, worsening, > 7 days, ≥ 7/10", "consult", "no exercise · see a health professional", C.red],
      ["Mild (≤ 3/10), confirmed, stable", "gentle routine", "2 sets, no impact, no plyometrics or eccentric work", C.teal],
    ],
    nm: "This is not medical advice", nd: "never a diagnosis · only anatomical zones are named",
    k8: "08 · THE PAGES", h8: "Two pages to keep at hand.",
    pages: [["Periodisation templates", "formats, phases, block skeleton, guardrails", "plans"], ["Strength", "library, programmes by phase, targeted prevention", "strength"]],
  },
};

/* ------------------------------- dessins locaux ------------------------------- */
function cross(x, y, s, col, alpha = 1) {
  line([[x - s, y - s], [x + s, y + s]], col, 3, alpha); line([[x + s, y - s], [x - s, y + s]], col, 3, alpha);
}
function keyBtn(label, x, y, w, h, on, o = {}) {
  panel(x, y, w, h, { r: 9, fill: on ? C.accent : "#1d3328", stroke: on ? C.accent : "#33463b", alpha: o.alpha ?? 1 });
  text(label, x + w / 2, y + h / 2 + (o.size ?? 13) * 0.36, { size: o.size ?? 13, weight: 600, align: "center", color: on ? C.deep : C.ink, alpha: o.alpha ?? 1 });
}
function path(t, pts) {
  if (t <= pts[0][0]) return [pts[0][1], pts[0][2]];
  for (let i = 1; i < pts.length; i++) {
    if (t <= pts[i][0]) { const k = inOut(seg(t, pts[i - 1][0], pts[i][0])); return [lerp(pts[i - 1][1], pts[i][1], k), lerp(pts[i - 1][2], pts[i][2], k)]; }
  }
  const p = pts[pts.length - 1]; return [p[1], p[2]];
}
function head(k, h, t) { kicker(k, seg(t, 0, 0.4)); headline(h, seg(t, 0.1, 0.7)); fictTag(seg(t, 0.3, 0.8)); }

/* ------------------------------ 01 · les gabarits ------------------------------ */
function sTemplates(t, d, cues) {
  head(S.k1, S.h1, t);
  const a0 = at(cues, 0, 0.6), a1 = at(cues, 1, 5.5);
  // six gabarits
  S.tpl.forEach(([id, dist, wk], i) => {
    const k = outCubic(seg(t, 0.3 + i * 0.15, 0.9 + i * 0.15)), col = i % 3, row = Math.floor(i / 3);
    const x = 80 + col * 262, y = 176 + row * 108 + (1 - k) * 14, hot = i === 1 && t > a0 + 2.6;
    panel(x, y, 246, 94, { r: 16, fill: hot ? "rgba(163,230,53,0.08)" : C.panel, stroke: hot ? C.accent : C.line, lw: hot ? 2 : 1, alpha: k });
    text(id, x + 18, y + 34, { size: 15, weight: 700, font: MONO, color: hot ? C.accent : C.ink, alpha: k });
    text(dist, x + 18, y + 60, { size: 16, weight: 600, alpha: k });
    text(wk, x + 18, y + 82, { size: 13, font: MONO, color: C.faint, alpha: k });
  });
  // cinq phases
  const kp = outCubic(seg(t, a1 - 0.3, a1 + 0.4));
  const cols = [PH.base, PH.dev, PH.spec, PH.taper, PH.rec], wts = [3, 4, 4, 2, 1.4];
  const tot = wts.reduce((a, b) => a + b, 0);
  let px = 80;
  S.phases.forEach((p, i) => {
    const w = 770 * wts[i] / tot, kk = outCubic(seg(t, a1 + i * 0.35, a1 + 0.5 + i * 0.35));
    panel(px, 420, w - 4, 46, { r: 10, fill: cols[i], stroke: false, alpha: kk * 0.9 });
    text(p, px + (w - 4) / 2, 449, { size: w > 100 ? 14 : 10, weight: 700, color: C.deep, align: "center", alpha: kk });
    px += w;
  });
  text(S.guard, 80, 500, { size: 14, font: MONO, color: C.faint, alpha: kp });
  // le pic
  const kq = outCubic(seg(t, a1 + 2.2, a1 + 2.9));
  panel(900, 176, 300, 290, { r: 18, alpha: kq });
  text(S.peakT.toUpperCase(), 924, 212, { size: 12, weight: 600, font: MONO, color: C.accent, alpha: kq, spacing: "2px" });
  text(S.held, 924, 256, { size: 14, color: C.soft, alpha: kq });
  text(S.heldV, 924, 300, { size: 38, weight: 800, font: SORA, alpha: kq });
  text(S.fac, 924, 336, { size: 14, font: MONO, color: C.amber, alpha: seg(t, a1 + 3.2, a1 + 3.8) * kq });
  const kr = outBack(seg(t, a1 + 3.8, a1 + 4.4));
  if (kr > 0) { text(S.peakV, 924, 394, { size: 38, weight: 800, font: SORA, color: C.accent, alpha: clamp(kr) }); text(S.peakN, 924, 428, { size: 12, font: MONO, color: C.faint, alpha: clamp(kr) }); }
}

/* ------------------------------ 02 · le squelette (dry run) ------------------------------ */
function sSkeleton(t, d, cues) {
  head(S.k2, S.h2, t);
  const a0 = at(cues, 0, 0.6), a1 = at(cues, 1, 6);
  const lines = [
    { p: "$ ", s: "arc_index.py plan-skeleton --text", c: C.ink, a: a0 + 1.0, b: a0 + 3.2 },
    { s: S.dry, c: C.amber, a: a0 + 3.6 },
    { s: S.lines[0], c: C.teal, a: a1 + 0.2 },
    { s: S.lines[1], c: C.ink, a: a1 + 1.4 },
    { s: S.lines[2], c: C.accent, a: a1 + 2.6 },
  ];
  terminal(80, 178, 700, 232, t, lines, { alpha: outCubic(seg(t, 0.3, 0.9)), size: 14, lh: 32, title: S.cmdT });
  // les douze semaines, une barre par semaine, teinte de la phase
  const dur = [280, 287, 293, 234, 297, 301, 306, 244, 314, 318, 223, 159, 109];
  const ph = [PH.base, PH.base, PH.base, PH.dev, PH.dev, PH.dev, PH.dev, PH.spec, PH.spec, PH.spec, PH.taper, PH.taper, PH.rec];
  const kb = seg(t, a1 + 0.2, a1 + 3.2);
  dur.forEach((m, i) => {
    const u = clamp(kb * 13 - i, 0, 1); if (u <= 0) return;
    const bh = 120 * m / 318 * outCubic(u), x = 80 + i * 54;
    panel(x, 560 - bh, 44, bh, { r: 7, fill: ph[i], stroke: false, alpha: 0.9 });
  });
  text(S.d0, 80, 590, { size: 12, font: MONO, color: C.faint, alpha: kb > 0 ? 1 : 0 });
  text(S.d1, 80 + 12 * 54, 590, { size: 12, font: MONO, color: C.faint, alpha: kb > 0 ? 1 : 0 });
  // entrées
  const ki = outCubic(seg(t, a0 + 4.0, a0 + 4.6));
  panel(820, 178, 380, 232, { r: 18, alpha: ki });
  text(S.inT.toUpperCase(), 844, 212, { size: 12, weight: 600, font: MONO, color: C.accent, alpha: ki, spacing: "2px" });
  S.ins.forEach(([a, b], i) => {
    const k = outCubic(seg(t, a0 + 4.4 + i * 0.5, a0 + 4.9 + i * 0.5)); if (k <= 0) return;
    const y = 246 + i * 40;
    check(852, y + 4, 9, C.teal, seg(t, a0 + 4.6 + i * 0.5, a0 + 5.1 + i * 0.5), k);
    text(a, 872, y + 10, { size: 14, color: C.soft, alpha: k });
    text(b, 1180, y + 10, { size: 14, weight: 700, font: MONO, align: "right", alpha: k });
  });
  const kf = outBack(seg(t, a1 + 3.6, a1 + 4.2));
  if (kf > 0) { pill(S.fc, 820, 450, { size: 14, alpha: clamp(kf) }); text(S.fcN, 820, 484, { size: 12, font: MONO, color: C.faint, alpha: clamp(kf) }); }
}

/* ------------------------------ 03 · trop court ------------------------------ */
function sShort(t, d, cues) {
  head(S.k3, S.h3, t);
  const a0 = at(cues, 0, 0.6), a1 = at(cues, 1, 5);
  const k0 = outCubic(seg(t, 0.3, 0.9));
  // sept semaines contre douze
  text(S.sh[0], 80, 204, { size: 14, weight: 600, font: MONO, color: C.faint, alpha: k0 });
  for (let i = 0; i < 12; i++) {
    const have = i < 7, k = outCubic(seg(t, 0.5 + i * 0.07, 1.0 + i * 0.07)), x = 80 + i * 62;
    if (have) panel(x, 226, 54, 74, { r: 10, fill: "rgba(163,230,53,0.18)", stroke: C.accent, alpha: k });
    else { const kk = outCubic(seg(t, a0 + 1.0 + (i - 7) * 0.12, a0 + 1.5 + (i - 7) * 0.12)); panel(x, 226, 54, 74, { r: 10, fill: "rgba(240,122,95,0.07)", stroke: C.red, alpha: kk }); }
  }
  const kn = outCubic(seg(t, a0 + 0.4, a0 + 1.0));
  text(S.weeks7, 80 + 3.5 * 62 - 4, 326, { size: 15, weight: 700, font: MONO, color: C.accent, align: "center", alpha: kn });
  text(S.weeks12, 80 + 9.5 * 62 - 4, 326, { size: 15, weight: 700, font: MONO, color: C.red, align: "center", alpha: seg(t, a0 + 1.4, a0 + 2.0) });
  // le refus, dit tel quel
  const kt = outCubic(seg(t, a0 + 2.4, a0 + 3.0));
  const lines = [
    { p: "$ ", s: "arc_index.py plan-skeleton --race-date 2026-11-22", c: C.ink, a: a0 + 2.4, b: a0 + 4.4 },
    { s: S.shErr, c: C.red, w: 700, a: a1 + 0.2 },
    { s: S.sh[1], c: C.amber, a: a1 + 0.2 },
    { s: S.shMin, c: C.ink, a: a1 + 1.2 },
    { s: S.shEarly, c: C.teal, a: a1 + 2.2 },
  ];
  terminal(80, 366, 1120, 218, t, lines, { alpha: kt, size: 15, lh: 30, title: S.cmdT });
  const ko = outCubic(seg(t, a1 + 3.4, a1 + 4.0));
  text(S.shOpts, 80, 622, { size: 14, font: MONO, color: C.faint, alpha: ko });
}

/* ------------------------------ 04 · un oui, une semaine par fichier ------------------------------ */
function sWrite(t, d, cues) {
  head(S.k4, S.h4, t);
  const a0 = at(cues, 0, 0.6), a1 = at(cues, 1, 6);
  const T = a0 + 1.4, pressed = t >= T + 0.2;
  const k0 = outCubic(seg(t, 0.3, 0.9));
  panel(80, 180, 330, 150, { r: 18, fill: C.panel2, stroke: C.accent, lw: 2, alpha: k0 });
  text(S.ask, 106, 224, { size: 20, weight: 800, font: SORA, alpha: k0 });
  keyBtn(S.yes, 106, 254, 120, 44, pressed, { alpha: k0, size: 16 });
  keyBtn(S.no, 242, 254, 120, 44, false, { alpha: k0, size: 16 });
  const [cx, cy] = path(t, [[T - 1.2, 400, 420], [T, 106 + 72, 254 + 26]]);
  if (t > T - 1.2) cursor(cx, cy, { click: seg(t, T, T + 0.5), alpha: seg(t, T - 1.2, T - 0.8) * (1 - seg(t, T + 1.6, T + 2.2)) });
  // une semaine par fichier
  const files = ["Semaine_2026-10-05.md", "Semaine_2026-10-12.md", "Semaine_2026-10-19.md", "…", "Semaine_2026-12-28.md"];
  files.forEach((f, i) => {
    const a = T + 0.6 + i * 0.4, k = outCubic(seg(t, a, a + 0.4)); if (k <= 0) return;
    const y = 352 + i * 46;
    panel(80, y + (1 - k) * 10, 330, 38, { r: 10, alpha: k });
    text("planning/" + f, 98, y + 25 + (1 - k) * 10, { size: 13, font: MONO, color: f === "…" ? C.faint : C.ink, alpha: k });
    if (f !== "…") check(392, y + 20 + (1 - k) * 10, 8, C.teal, seg(t, a + 0.2, a + 0.6), k);
  });
  const ke = outCubic(seg(t, T + 3.0, T + 3.6));
  if (ke > 0) {
    panel(80, 590, 330, 40, { r: 10, fill: "rgba(240,180,60,0.07)", stroke: C.amber, alpha: ke });
    text(S.refused, 98, 615, { size: 13, font: MONO, color: C.amber, alpha: ke });
    text(S.never, 430, 615, { size: 14, weight: 700, font: MONO, color: C.amber, alpha: ke });
  }
  // semaine de course et après
  const kr = outCubic(seg(t, a1 - 0.3, a1 + 0.4));
  panel(470, 180, 730, 230, { r: 18, alpha: kr });
  text(S.rwT.toUpperCase(), 496, 214, { size: 12, weight: 600, font: MONO, color: C.accent, alpha: kr, spacing: "2px" });
  const kinds = ["off", "run", "run", "run", "off", "free", "race"];
  kinds.forEach((kd, i) => {
    const a = a1 + 0.3 + i * 0.25, k = outCubic(seg(t, a, a + 0.4)), x = 496 + i * 98;
    const col = kd === "run" ? C.teal : kd === "race" ? C.accent : kd === "free" ? C.amber : C.line;
    panel(x, 232, 88, 84, { r: 12, fill: "#0a120e", stroke: col, lw: kd === "race" ? 2 : 1, alpha: k * kr });
    text(S.days[i], x + 44, 256, { size: 12, font: MONO, color: C.faint, align: "center", alpha: k * kr });
    if (kd === "race") { line([[x + 30, 300], [x + 30, 266]], C.accent, 2.5, k); line([[x + 30, 266], [x + 56, 276], [x + 30, 286]], C.accent, 2.5, k); }
    else if (kd === "run") text("footing", x + 44, 292, { size: 12, weight: 600, align: "center", color: C.teal, alpha: k * kr });
    else if (kd === "free") text("libre", x + 44, 292, { size: 12, weight: 600, align: "center", color: C.amber, alpha: k * kr });
  });
  para(S.rw[0] + " · " + S.rw[1] + " · " + S.rw[2], 496, 348, 680, { size: 13, font: MONO, color: C.soft, alpha: kr });
  const kp = outCubic(seg(t, a1 + 2.8, a1 + 3.4));
  panel(470, 432, 730, 92, { r: 18, fill: "rgba(95,196,192,0.06)", stroke: PH.rec, alpha: kp });
  text(S.prT.toUpperCase(), 496, 464, { size: 12, weight: 600, font: MONO, color: PH.rec, alpha: kp, spacing: "2px" });
  text(S.pr, 496, 500, { size: 18, weight: 700, alpha: kp });
  [0, 1, 2].forEach(i => { const k = outCubic(seg(t, a1 + 3.4 + i * 0.3, a1 + 3.8 + i * 0.3)); cross(1090 + i * 34, 490, 8, C.red, k); });
}

/* ------------------------------ 05 · la frise (captures réelles) ------------------------------ */
const FX = 80, FY = 170, FW = 1120, FH = 330, CY = FY + FH + 40;
function sFrise(t, d, cues) {
  head(S.k5, S.h5, t);
  const a0 = at(cues, 0, 0.6), a1 = at(cues, 1, 6);
  const k0 = outCubic(seg(t, 0.3, 0.9)), sw = outCubic(seg(t, a1 - 0.4, a1 + 0.3));
  const asp = FW / (FH - 30);
  const cap = (s, x, k, col) => { if (k > 0) pill(s, x, CY, { size: 14, alpha: k, color: C.ink, fill: "rgba(15,42,31,0.92)", stroke: col, align: "center" }); };
  if (sw < 1) {
    const z = inOut(seg(t, 0.5, a0 + 2.0));
    const crop = lerpRect(cropTo("bloc-frise", [248, 120, 1008, 560], asp, 0), cropTo("bloc-frise", "frise", asp, 14), z);
    const m = shot("bloc-frise", FX, FY, FW, FH, { crop, alpha: k0 * (1 - sw), url: "127.0.0.1:8765/#/semaine" });
    const r = m("colonnes");
    if (r) highlight(r[0], r[1], r[2], r[3], seg(t, a0 + 1.6, a0 + 2.2) * (1 - sw));
    const f = m("drapeau");
    if (f && t > a0 + 4.2) callout(S.c3, f[0] + f[2] / 2, CY, f[0] + f[2] / 2, f[1] + f[3] + 2, seg(t, a0 + 4.2, a0 + 4.8) * (1 - sw));
    const kc = outCubic(seg(t, a0 + 2.4, a0 + 3.0)) * (1 - sw);
    cap(S.c1, FX + 190, kc, C.accent); cap(S.c2, FX + 450, kc, C.accent);
  }
  if (sw > 0) {
    const crop = cropTo("bloc-semaine", [248, 470, 1008, 270], asp, 0);
    const m = shot("bloc-semaine", FX, FY, FW, FH, { crop, alpha: sw, url: "127.0.0.1:8765/#/semaine?debut=2026-10-12" });
    const r = m("semaine");
    if (r) highlight(r[0], r[1], r[2], r[3], seg(t, a1 + 0.8, a1 + 1.5) * sw, C.amber);
    cap(S.c5, FX + FW / 2, outCubic(seg(t, a1 + 1.2, a1 + 1.8)) * sw, C.amber);
  }
}

/* ------------------------------ 06 · renforcement par phase ------------------------------ */
function sStrength(t, d, cues) {
  head(S.k6, S.h6, t);
  const a0 = at(cues, 0, 0.6), a1 = at(cues, 1, 6);
  S.prog.forEach(([ph, prog, col], i) => {
    const y = 180 + i * 64, kk = outCubic(seg(t, 0.3 + i * 0.12, 0.9 + i * 0.12));
    panel(80, y + (1 - kk) * 12, 640, 54, { r: 12, alpha: kk });
    panel(80, y + (1 - kk) * 12, 8, 54, { r: 4, fill: col, stroke: false, alpha: kk });
    text(ph, 106, y + 33 + (1 - kk) * 12, { size: 16, weight: 800, font: SORA, alpha: kk });
    text(prog, 700, y + 33 + (1 - kk) * 12, { size: 15, font: MONO, color: col, align: "right", alpha: kk });
  });
  const kp = outCubic(seg(t, a0 + 4.0, a0 + 4.6));
  text(S.place, 80, 536, { size: 14, font: MONO, color: C.faint, alpha: kp });
  text(S.noEq, 80, 566, { size: 14, font: MONO, color: C.faint, alpha: outCubic(seg(t, a0 + 5.2, a0 + 5.8)) });
  // pousser vers la montre
  const k2 = outBack(seg(t, a1 - 0.2, a1 + 0.5));
  if (k2 > 0) {
    const kk = clamp(k2), y = 190 + (1 - kk) * 20;
    panel(780, y, 420, 230, { r: 18, fill: C.panel2, stroke: C.accent, lw: 2, alpha: kk });
    text(S.pushT, 806, y + 46, { size: 22, weight: 800, font: SORA, alpha: kk });
    S.pushL.forEach((s, i) => { dot(812, y + 82 + i * 30 - 5, 4, C.teal, kk); text(s, 828, y + 82 + i * 30, { size: 16, alpha: kk }); });
    const T = a1 + 1.8, pressed = t >= T + 0.2;
    keyBtn(S.yes, 806, y + 150, 120, 44, pressed, { alpha: kk, size: 16 });
    keyBtn(S.no, 942, y + 150, 120, 44, false, { alpha: kk, size: 16 });
    const [cx, cy] = path(t, [[T - 1.4, 1120, 560], [T, 806 + 72, y + 150 + 26]]);
    if (t > T - 1.4) cursor(cx, cy, { click: seg(t, T, T + 0.5), alpha: seg(t, T - 1.4, T - 0.9) * (1 - seg(t, T + 1.6, T + 2.2)) });
    const kh = outCubic(seg(t, T + 1.0, T + 1.6));
    if (kh > 0) { check(806, 458, 11, C.teal, kh, kh); text("Garmin", 830, 464, { size: 15, weight: 700, font: MONO, color: C.teal, alpha: kh }); }
  }
  const kn = outCubic(seg(t, a1 + 4.4, a1 + 5.0));
  pill(S.headless, 780, 520, { size: 14, alpha: kn, color: C.amber, fill: "rgba(240,180,60,0.08)", stroke: "rgba(240,180,60,0.45)" });
}

/* ------------------------------ 07 · prévention ciblée ------------------------------ */
function sPrevention(t, d, cues) {
  head(S.k7, S.h7, t);
  const a0 = at(cues, 0, 0.6), a1 = at(cues, 1, 7);
  const times = [a0 + 1.4, a0 + 5.0, a1 + 0.2];
  S.lane.forEach(([cond, tag, what, col], i) => {
    const k = outCubic(seg(t, times[i], times[i] + 0.5)), y = 178 + i * 118;
    if (k <= 0) return;
    panel(80, y + (1 - k) * 12, 1120, 102, { r: 16, fill: C.panel, stroke: col, lw: 1.5, alpha: k });
    panel(80, y + (1 - k) * 12, 8, 102, { r: 4, fill: col, stroke: false, alpha: k });
    text(cond, 112, y + 40 + (1 - k) * 12, { size: 20, weight: 700, font: SORA, alpha: k });
    para(what, 112, y + 74 + (1 - k) * 12, 700, { size: 15, color: C.soft, alpha: k });
    pill(tag, 1170, y + 52 + (1 - k) * 12, { size: 17, align: "right", alpha: k, color: col, fill: "#0a120e", stroke: col, padX: 18 });
  });
  const kn = outBack(seg(t, a1 + 3.2, a1 + 3.8));
  if (kn > 0) {
    const kk = clamp(kn);
    panel(80, 540, 1120, 96, { r: 16, fill: "rgba(240,180,60,0.07)", stroke: C.amber, lw: 2, alpha: kk });
    text(S.nm, 108, 584, { size: 24, weight: 800, font: SORA, color: C.amber, alpha: kk });
    text(S.nd, 108, 614, { size: 14, font: MONO, color: C.soft, alpha: kk });
  }
}

/* ------------------------------ 08 · les pages de documentation ------------------------------ */
function sPages(t, d, cues) {
  head(S.k8, S.h8, t);
  const a0 = at(cues, 0, 0.6);
  S.pages.forEach(([title, sub, slug], i) => {
    const a = a0 + 0.8 + i * 1.8, k = outCubic(seg(t, a, a + 0.5)), y = 200 + i * 130;
    const on = t >= a && t < a + 1.8;
    panel(80, y + (1 - k) * 14, 1120, 108, { r: 18, fill: on ? "rgba(163,230,53,0.07)" : C.panel, stroke: on ? C.accent : C.line, lw: on ? 2 : 1, alpha: k });
    text(String(i + 1).padStart(2, "0"), 124, y + 66 + (1 - k) * 14, { size: 32, weight: 800, font: SORA, color: C.accent, align: "center", alpha: k });
    text(title, 176, y + 50 + (1 - k) * 14, { size: 26, weight: 800, font: SORA, alpha: k });
    text(sub, 176, y + 80 + (1 - k) * 14, { size: 15, color: C.soft, alpha: k });
    text(`${slug}/`, 1170, y + 64 + (1 - k) * 14, { size: 18, weight: 600, font: MONO, color: C.accent, align: "right", alpha: k });
  });
}

ARC.episode({
  n: 15, slug: "bloc",
  strings: STR,
  shots: ["bloc-frise", "bloc-semaine"],
  scenes: { templates: sTemplates, skeleton: sSkeleton, short: sShort, write: sWrite, frise: sFrise, strength: sStrength, prevention: sPrevention, pages: sPages },
});
})();
