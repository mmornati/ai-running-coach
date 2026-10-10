/* Le Sentier · étape 17 — « Avant, après » : projection de charge jusqu'au jour J et affûtage comparé (#172),
 * pénalité d'altitude du plan de course (#185), effet des décisions du coach (#175), recalibrage des
 * coefficients de pacing au débrief (#188).
 * Projection et effets des décisions : captures réelles du tableau de bord sur la variante « suite » du
 * workspace fictif (scripts/video_demo_workspace.py --suite : huit semaines planifiées, décisions passées).
 * Chiffres de l'affûtage : `arc_index.py load-forecast --compare planning/variante_affutage-court.json` sur ce
 * workspace ; altitude : `arc_race_pacing` sur le parcours inventé de l'Ultra des Crêtes (épisode 14), sans
 * acclimatation puis avec 14 jours déclarés ; débrief : `arc_pacing_calibration.render_text` sur la course
 * synthétique des tests (tests/data/test_arc_pacing_calibration.py, nuit réelle 12 % contre 5 % prévus).
 * Moteur : ../engine/engine.js (helpers globaux). Découpage et narration : script.json.
 * Athlète et chiffres fictifs (bible de la série : Camille, mardi 29 septembre 2026). */
"use strict";
(() => {
const NIGHT = "#8f9be8";
/* Profil inventé de l'Ultra des Crêtes (km, m) — scripts/video_demo_workspace.py, ULTRA_PROFILE. */
const PROF = [[0, 1000], [8, 1750], [13, 1450], [22, 2350], [28, 1650], [34, 2150], [41, 1250], [49, 2300], [55, 2000], [60, 2450], [66, 1100]];
function elev(km) {
  for (let i = 1; i < PROF.length; i++) {
    const [k0, e0] = PROF[i - 1], [k1, e1] = PROF[i];
    if (km <= k1) { const u = (km - k0) / (k1 - k0); return e0 + (e1 - e0) * (u * u * (3 - 2 * u) * 0.35 + u * 0.65); }
  }
  return PROF[PROF.length - 1][1];
}
/* Volumes planifiés (h) des quatre dernières semaines : plan actuel / variante « affûtage d'une semaine ». */
const WEEKS = [["26/10", 7.25, 7.25], ["2/11", 6.83, 6.83], ["9/11", 4.92, 7.25], ["16/11", 1.5, 1.5]];

const STR = {
  fr: {
    k1: "01 · PROJECTION", h1: "La forme, jusqu'au jour J.",
    c1: "pointillés = projection", c2: "Forme prévue le jour J : +26,1", c3: "pic de fatigue : sem. du 2 nov.", est: "une estimation à partir du planifié, jamais une mesure",
    k2: "02 · AFFÛTAGE", h2: "Deux semaines calmes ? Les chiffres.",
    cur: "Plan actuel", alt: "Affûtage d'une semaine", wk: "semaine du",
    rows: [["Forme le jour J", "+26,1", "+20,2", "−6,0"], ["Fatigue le jour J", "64,0", "75,3", "+11,4"], ["Pic de fatigue", "sem. 2 nov.", "sem. 9 nov.", ""]],
    verdict: "moins frais avec la variante : on garde deux semaines d'affûtage",
    k3: "03 · ALTITUDE", h3: "Au-dessus de 1 500 m, on ralentit.",
    thr: "seuil 1 500 m", top: "2 450 m",
    src: "Wehrlin & Hallén 2006 : −6,3 % de VO2max par 1 000 m · traduction en vitesse : approximation du projet",
    a1: "non acclimatée (par défaut)", a1v: "+17 min 29 s", a2: "14 jours en altitude déclarés", a2v: "+8 min 36 s", cap: "crédit plafonné à 50 % · jamais à zéro",
    sc: "scénario réaliste", ultra: "Ultra des Crêtes · 66 km · parcours inventé",
    k4: "04 · ENSUITE", h4: "Après chaque décision, la suite.",
    e1: "avant : J-2 → J", e2: "après : J+1 → J+3", fav: "6 allègements évalués · 5 favorables", ref: "1 conseil refusé · suivi d'une dégradation",
    k5: "05 · PRUDENCE", h5: "Corrélation, pas causalité.",
    why: ["sommeil", "météo", "hasard", "retour à la moyenne"], whyT: "Ce qui joue aussi",
    n5: "n < 5 : des comptes, aucune tendance", n1: "1 cas", n5b: "5 cas",
    locks: ["garde-fou « block »", "décision médicale", "verdict rouge"], lockT: "jamais assouplis",
    k6: "06 · LE DÉBRIEF", h6: "Le plan contre le réalisé.",
    race: "Trail des Lucioles · 40 segments d'1 km · départ en soirée", day: "jour", night: "nuit", ratio: "réalisé ÷ prévu",
    lines: ["Recalibrage des coefficients — Trail des Lucioles", "night : estimated — ratio 1.0667 (n = 16/12, confiance high)", "night_penalty_pct : 5.0 -> 8.1111 (poids 0.444)"],
    def: "défaut 5 %", obs: "observé 12 %", prop: "proposé 8,1 %", w: "poids = n / (n + 20) = 16 / 36",
    k7: "07 · UN OUI", h7: "Écrit seulement sur votre accord.",
    ask: "Appliquer ce coefficient ?", yes: "oui", no: "non", file: "config/workspace.user.toml",
    next: "relu par chaque plan de course · les options de la ligne de commande priment", cumul: "le débrief suivant se cumule à celui-ci",
    k8: "08 · LES PAGES", h8: "Trois pages à garder sous la main.",
    pages: [["Projection de charge", "forme prévue, affûtage comparé, garde-fous", "guardrails"], ["Effet des décisions", "/why, ce qui a suivi chaque décision", "skills/why"], ["Stratège de course", "altitude, nuit, technicité, recalibrage", "agents/course-strategist"]],
  },
  en: {
    k1: "01 · FORECAST", h1: "Form, all the way to race day.",
    c1: "dotted = forecast", c2: "Forecast form on race day: +26.1", c3: "peak fatigue: week of Nov 2", est: "an estimate from the plan, never a measurement",
    k2: "02 · TAPER", h2: "Two quiet weeks? The numbers.",
    cur: "Current plan", alt: "One-week taper", wk: "week of",
    rows: [["Form on race day", "+26.1", "+20.2", "−6.0"], ["Fatigue on race day", "64.0", "75.3", "+11.4"], ["Peak fatigue", "wk Nov 2", "wk Nov 9", ""]],
    verdict: "less fresh with the variant: two taper weeks stay",
    k3: "03 · ALTITUDE", h3: "Above 1,500 m, you slow down.",
    thr: "1,500 m threshold", top: "2,450 m",
    src: "Wehrlin & Hallén 2006: −6.3% VO2max per 1,000 m · translating it into speed: a project approximation",
    a1: "not acclimatised (default)", a1v: "+17 min 29 s", a2: "14 days at altitude declared", a2v: "+8 min 36 s", cap: "credit capped at 50% · never zero",
    sc: "realistic scenario", ultra: "Ultra des Crêtes · 66 km · invented course",
    k4: "04 · AFTERWARDS", h4: "After each decision, what followed.",
    e1: "before: D-2 → D", e2: "after: D+1 → D+3", fav: "6 lightened sessions assessed · 5 improved", ref: "1 advice turned down · followed by a decline",
    k5: "05 · CAUTION", h5: "Correlation, not causation.",
    why: ["sleep", "weather", "chance", "regression to the mean"], whyT: "What else plays a part",
    n5: "n < 5: counts only, no trend", n1: "1 case", n5b: "5 cases",
    locks: ["“block” guardrail", "medical decision", "red verdict"], lockT: "never relaxed",
    k6: "06 · THE DEBRIEF", h6: "The plan against reality.",
    race: "Trail des Lucioles · 40 one-km segments · evening start", day: "day", night: "night", ratio: "actual ÷ planned",
    lines: ["Coefficient recalibration — Trail des Lucioles", "night : estimated — ratio 1.0667 (n = 16/12, confidence high)", "night_penalty_pct : 5.0 -> 8.1111 (weight 0.444)"],
    def: "default 5%", obs: "observed 12%", prop: "proposed 8.1%", w: "weight = n / (n + 20) = 16 / 36",
    k7: "07 · A YES", h7: "Written only on your say-so.",
    ask: "Apply this coefficient?", yes: "yes", no: "no", file: "config/workspace.user.toml",
    next: "read by every race plan · command-line options take precedence", cumul: "the next debrief adds up with this one",
    k8: "08 · THE PAGES", h8: "Three pages to keep at hand.",
    pages: [["Load forecast", "forecast form, taper comparison, guardrails", "guardrails"], ["Decision effects", "/why, what followed each decision", "skills/why"], ["Course strategist", "altitude, night, technicity, recalibration", "agents/course-strategist"]],
  },
};

/* ------------------------------- dessins locaux ------------------------------- */
function head(k, h, t) { kicker(k, seg(t, 0, 0.4)); headline(h, seg(t, 0.1, 0.7)); fictTag(seg(t, 0.3, 0.8)); }
function label(s, x, y, k, col = C.accent) { text(s, x, y, { size: 12, weight: 600, font: MONO, color: col, alpha: k, spacing: "2px" }); }
function keyBtn(s, x, y, w, h, on, o = {}) {
  panel(x, y, w, h, { r: 9, fill: on ? C.accent : "#1d3328", stroke: on ? C.accent : "#33463b", alpha: o.alpha ?? 1 });
  text(s, x + w / 2, y + h / 2 + 6, { size: o.size ?? 15, weight: 600, align: "center", color: on ? C.deep : C.ink, alpha: o.alpha ?? 1 });
}
function lock(x, y, k, col = C.accent) {
  if (k <= 0) return;
  ctx.save(); ctx.globalAlpha *= k; ctx.beginPath(); ctx.arc(x, y - 6, 8, Math.PI, 0); ctx.strokeStyle = col; ctx.lineWidth = 3; ctx.stroke(); ctx.restore();
  panel(x - 12, y - 6, 24, 18, { r: 4, fill: col, stroke: false, alpha: k });
}
const FX = 80, FY = 168, FW = 1120, FH = 380, CY = FY + FH + 36;
const cap = (s, x, k, col = C.accent) => { if (k > 0) pill(s, x, CY, { size: 14, alpha: k, color: C.ink, fill: "rgba(15,42,31,0.92)", stroke: col, align: "center" }); };

/* ------------------------------ 01 · projection (capture réelle) ------------------------------ */
function sForecast(t, d, cues) {
  head(S.k1, S.h1, t);
  const a0 = at(cues, 0, 0.6), a1 = at(cues, 1, 6);
  const k0 = outCubic(seg(t, 0.3, 0.9));
  const asp = FW / (FH - 30);
  const z = inOut(seg(t, a1 - 0.6, a1 + 0.4));
  const crop = lerpRect(cropTo("forme-projection", "graphe", asp, 10), [262, 410, 980, 980 / asp], z);
  const m = shot("forme-projection", FX, FY, FW, FH, { crop, alpha: k0, url: "127.0.0.1:8765/#/forme" });
  const g = m("graphe");
  if (g) {
    const px = g[0] + g[2] * 0.735, pw = g[2] * 0.25;
    highlight(px, g[1] + 8, pw, g[3] - 40, seg(t, a0 + 1.6, a0 + 2.2) * (1 - z));
  }
  cap(S.c1, FX + FW * 0.78, outCubic(seg(t, a0 + 2.0, a0 + 2.6)) * (1 - z));
  const fj = m("forme-j"), rp = m("reperes");
  if (fj) highlight(fj[0], fj[1], fj[2], fj[3], seg(t, a1 + 0.6, a1 + 1.2));
  if (rp) highlight(rp[0] + rp[2] * 0.155, rp[1], rp[2] * 0.17, rp[3], seg(t, a1 + 2.4, a1 + 3.0), C.amber);
  const ke = outCubic(seg(t, a1 + 4.0, a1 + 4.6));
  cap(S.est, FX + FW / 2, ke, C.amber);
}

/* ------------------------------ 02 · affûtage comparé ------------------------------ */
function sTaper(t, d, cues) {
  head(S.k2, S.h2, t);
  const a0 = at(cues, 0, 0.6), a1 = at(cues, 1, 5);
  const k0 = outCubic(seg(t, 0.3, 0.9));
  const lines = [{ p: "$ ", s: "arc_index.py load-forecast --compare planning/variante_affutage-court.json", c: C.ink, a: 0.4, b: a0 + 1.6 }];
  terminal(80, 160, 1120, 84, t, lines, { alpha: k0, size: 14, lh: 26 });
  // barres de volume des quatre dernières semaines
  const kb = outCubic(seg(t, a0 + 1.0, a0 + 1.6));
  [[S.cur, 1, C.teal, 100], [S.alt, 2, C.amber, 360]].forEach(([n, j, col, x0]) => {
    text(n, x0, 270, { size: 15, weight: 700, color: col, alpha: kb });
    WEEKS.forEach((w, i) => {
      const v = w[j], hh = 150 * v / 7.5 * outCubic(seg(t, a0 + 1.2 + i * 0.15, a0 + 1.8 + i * 0.15)), x = x0 + i * 58;
      const diff = i === 2 && j === 2;
      panel(x, 450 - hh, 44, hh, { r: 6, fill: diff ? C.amber : col, stroke: false, alpha: (diff ? 1 : 0.75) * kb });
      text(w[0], x + 22, 474, { size: 11, font: MONO, color: diff ? C.amber : C.faint, align: "center", alpha: kb });
    });
  });
  text(S.wk, 100, 500, { size: 11, font: MONO, color: C.faint, alpha: kb });
  // les écarts, sortis de la commande
  const kt = outCubic(seg(t, a1 - 0.3, a1 + 0.4));
  panel(640, 256, 560, 236, { r: 18, alpha: kt });
  text(S.cur, 930, 290, { size: 12, font: MONO, color: C.teal, align: "center", alpha: kt });
  text(S.alt, 1070, 290, { size: 12, font: MONO, color: C.amber, align: "center", alpha: kt });
  S.rows.forEach(([n, a, b, dlt], i) => {
    const k = outCubic(seg(t, a1 + 0.2 + i * 0.7, a1 + 0.7 + i * 0.7)) * kt, y = 336 + i * 50;
    text(n, 664, y, { size: 16, weight: 600, alpha: k });
    text(a, 930, y, { size: 17, weight: 700, font: MONO, align: "center", alpha: k });
    text(b, 1070, y, { size: 17, weight: 700, font: MONO, color: C.amber, align: "center", alpha: k });
    if (dlt) text(dlt, 1180, y, { size: 15, weight: 700, font: MONO, color: C.red, align: "right", alpha: k });
  });
  const kv = outBack(seg(t, a1 + 3.0, a1 + 3.6));
  if (kv > 0) pill(S.verdict, 640, 540, { size: 15, alpha: clamp(kv) });
}

/* ------------------------------ 03 · altitude ------------------------------ */
function sAltitude(t, d, cues) {
  head(S.k3, S.h3, t);
  const a0 = at(cues, 0, 0.6), a1 = at(cues, 1, 8);
  const X0 = 100, X1 = 1180, Y0 = 470, Y1 = 200, E0 = 900, E1 = 2600;
  const px = km => X0 + km / 66 * (X1 - X0), py = e => Y0 - (e - E0) / (E1 - E0) * (Y0 - Y1);
  const pts = []; for (let km = 0; km <= 66; km += 0.25) pts.push([px(km), py(elev(km))]);
  const kp = seg(t, 0.4, a0 + 2.0);
  const k0 = outCubic(seg(t, 0.3, 0.9));
  text(S.ultra, X0, 196, { size: 12, font: MONO, color: C.faint, alpha: k0 });
  // remplissage au-dessus du seuil, révélé avec la voix
  const kf = outCubic(seg(t, a0 + 4.0, a0 + 5.2));
  if (kf > 0) {
    ctx.save(); ctx.globalAlpha *= 0.45 * kf;
    ctx.beginPath(); ctx.rect(X0, Y1 - 10, X1 - X0, py(1500) - Y1 + 10); ctx.clip();
    ctx.beginPath(); ctx.moveTo(X0, py(1500)); pts.forEach(([x, y]) => ctx.lineTo(x, y)); ctx.lineTo(X1, py(1500)); ctx.closePath();
    ctx.fillStyle = C.red; ctx.fill(); ctx.restore();
  }
  line(partial(pts, kp), C.accent, 3);
  const kt = outCubic(seg(t, a0 + 3.4, a0 + 4.0));
  line([[X0, py(1500)], [X1, py(1500)]], C.amber, 2, kt, [8, 6]);
  text(S.thr, X0 + 4, py(1500) + 22, { size: 13, weight: 700, font: MONO, color: C.amber, alpha: kt });
  const kx = outBack(seg(t, a0 + 2.0, a0 + 2.6));
  if (kx > 0) { dot(px(60), py(2450), 6, C.accent, clamp(kx)); text(S.top, px(60), py(2450) - 14, { size: 13, weight: 700, font: MONO, align: "center", alpha: clamp(kx) }); }
  text(S.src, X0, 500, { size: 12, font: MONO, color: C.faint, alpha: outCubic(seg(t, a0 + 6.0, a0 + 6.6)) });
  // deux scénarios d'acclimatation
  const card = (n, v, x, col, a) => {
    const k = outCubic(seg(t, a, a + 0.5));
    if (k <= 0) return;
    panel(x, 530, 540, 92, { r: 16, fill: C.panel, stroke: col, alpha: k });
    text(n, x + 24, 566, { size: 15, color: C.soft, alpha: k });
    text(S.sc, x + 24, 598, { size: 12, font: MONO, color: C.faint, alpha: k });
    text(v, x + 516, 596, { size: 30, weight: 800, font: SORA, color: col, align: "right", alpha: k });
  };
  card(S.a1, S.a1v, 80, C.red, a1 + 0.2);
  card(S.a2, S.a2v, 660, C.teal, a1 + 2.4);
  const kc = outCubic(seg(t, a1 + 4.4, a1 + 5.0));
  if (kc > 0) pill(S.cap, 1200, 196, { size: 13, align: "right", alpha: kc, color: C.teal, fill: "#0a120e", stroke: C.teal });
}

/* ------------------------------ 04 · ce qui s'est passé ensuite (captures réelles) ------------------------------ */
function sEffects(t, d, cues) {
  head(S.k4, S.h4, t);
  const a0 = at(cues, 0, 0.6), a1 = at(cues, 1, 7);
  const k0 = outCubic(seg(t, 0.3, 0.9)), sw = outCubic(seg(t, a1 - 0.5, a1 + 0.2));
  const asp = FW / (FH - 30);
  if (sw < 1) {
    const m = shot("decision-effet", FX, FY, FW, FH, { crop: cropTo("decision-effet", "effet", asp, 8), alpha: k0 * (1 - sw), url: "127.0.0.1:8765/#/decision" });
    const e = m("effet");
    if (e) {
      highlight(e[0] + e[2] * 0.18, e[1] + e[3] * 0.24, e[2] * 0.18, e[3] * 0.4, seg(t, a0 + 3.4, a0 + 4.0) * (1 - sw), C.amber);
      highlight(e[0] + e[2] * 0.38, e[1] + e[3] * 0.24, e[2] * 0.36, e[3] * 0.4, seg(t, a0 + 5.0, a0 + 5.6) * (1 - sw));
    }
    cap(S.e1, FX + FW * 0.3, outCubic(seg(t, a0 + 3.6, a0 + 4.2)) * (1 - sw), C.amber);
    cap(S.e2, FX + FW * 0.7, outCubic(seg(t, a0 + 5.2, a0 + 5.8)) * (1 - sw));
  }
  if (sw > 0) {
    const m = shot("decisions-effets", FX, FY, FW, FH, { crop: cropTo("decisions-effets", "synthese", asp, 10), alpha: sw, url: "127.0.0.1:8765/#/decisions" });
    const f = m("favorable"), r = m("refusees");
    if (f) highlight(f[0], f[1], f[2], f[3], seg(t, a1 + 0.6, a1 + 1.2) * sw);
    if (r) highlight(r[0], r[1], r[2], r[3], seg(t, a1 + 3.2, a1 + 3.8) * sw, C.red);
    cap(S.fav, FX + FW * 0.28, outCubic(seg(t, a1 + 0.8, a1 + 1.4)) * sw);
    cap(S.ref, FX + FW * 0.72, outCubic(seg(t, a1 + 3.4, a1 + 4.0)) * sw, C.red);
  }
}

/* ------------------------------ 05 · prudence ------------------------------ */
function sCaveat(t, d, cues) {
  head(S.k5, S.h5, t);
  const a0 = at(cues, 0, 0.6), a1 = at(cues, 1, 7);
  const k0 = outCubic(seg(t, 0.3, 0.9));
  panel(80, 168, 540, 250, { r: 18, alpha: k0 });
  label(S.whyT.toUpperCase(), 106, 202, k0, C.amber);
  S.why.forEach((w, i) => {
    const k = outCubic(seg(t, a0 + 1.6 + i * 0.5, a0 + 2.1 + i * 0.5));
    dot(116, 240 + i * 44, 5, C.amber, k);
    text(w, 134, 246 + i * 44, { size: 19, weight: 600, alpha: k });
  });
  // un cas contre cinq
  const kn = outCubic(seg(t, a0 + 4.4, a0 + 5.0));
  panel(660, 168, 540, 250, { r: 18, alpha: kn });
  [[S.n1, 1, 700, C.faint], [S.n5b, 5, 940, C.accent]].forEach(([n, c, x, col], j) => {
    for (let i = 0; i < c; i++) dot(x + 30 + i * 40, 280, 13, col, outCubic(seg(t, a0 + 4.8 + j * 0.8 + i * 0.12, a0 + 5.2 + j * 0.8 + i * 0.12)) * kn);
    text(n, x + 30 + (c - 1) * 20, 330, { size: 15, weight: 700, font: MONO, color: col, align: "center", alpha: kn });
  });
  text(S.n5, 686, 388, { size: 15, font: MONO, color: C.soft, alpha: outCubic(seg(t, a0 + 6.2, a0 + 6.8)) });
  // ce qui n'est jamais assoupli
  const kl = outCubic(seg(t, a1 - 0.2, a1 + 0.4));
  panel(80, 442, 1120, 180, { r: 18, fill: "rgba(163,230,53,0.05)", stroke: C.accent, alpha: kl });
  S.locks.forEach((s, i) => {
    const k = outBack(seg(t, a1 + 0.4 + i * 0.7, a1 + 1.0 + i * 0.7)), x = 180 + i * 360;
    lock(x, 514, clamp(k));
    text(s, x + 30, 522, { size: 19, weight: 700, alpha: clamp(k) });
  });
  text(S.lockT, 640, 592, { size: 16, weight: 600, font: MONO, color: C.accent, align: "center", alpha: outCubic(seg(t, a1 + 2.8, a1 + 3.4)) });
}

/* ------------------------------ 06 · le débrief ------------------------------ */
function sDebrief(t, d, cues) {
  head(S.k6, S.h6, t);
  const a0 = at(cues, 0, 0.6), a1 = at(cues, 1, 7);
  const k0 = outCubic(seg(t, 0.3, 0.9));
  text(S.race, 80, 196, { size: 13, font: MONO, color: C.faint, alpha: k0 });
  // 40 segments : réalisé ÷ prévu, la nuit à part (km 18 à 34)
  const X0 = 80, BW = 26, YB = 400, sc = 900;
  const kn = outCubic(seg(t, a0 + 1.6, a0 + 2.4));
  panel(X0 + 18 * 28 - 4, 214, 16 * 28 + 6, 196, { r: 10, fill: "rgba(143,155,232,0.10)", stroke: false, alpha: kn });
  text("☾ " + S.night, X0 + 26 * 28, 236, { size: 13, weight: 700, font: MONO, color: NIGHT, align: "center", alpha: kn });
  line([[X0, YB - 0.0 * sc], [X0 + 40 * 28, YB]], C.line, 1, k0);
  for (let i = 0; i < 40; i++) {
    const n = i >= 18 && i < 34, r = n ? 1.12 / 1.05 : 1.0, k = outCubic(seg(t, 0.6 + i * 0.05, 1.0 + i * 0.05));
    const h = (60 + (r - 1) * sc) * k;
    panel(X0 + i * 28, YB - h, BW - 6, h, { r: 4, fill: n ? NIGHT : C.teal, stroke: false, alpha: 0.85 * k });
  }
  text(S.ratio, X0, 430, { size: 12, font: MONO, color: C.faint, alpha: k0 });
  text("+6,7 %", X0 + 26 * 28, YB - 60 - 0.0667 * sc - 10, { size: 14, weight: 700, font: MONO, color: NIGHT, align: "center", alpha: outCubic(seg(t, a0 + 3.0, a0 + 3.6)) });
  // la sortie du script
  const lines = S.lines.map((s, i) => ({ s, c: i === 2 ? C.accent : i ? NIGHT : C.ink, a: a1 + (i ? 0.8 + i * 1.0 : 0.2) }));
  terminal(80, 450, 640, 176, t, lines, { alpha: outCubic(seg(t, a1 - 0.3, a1 + 0.3)), size: 13, lh: 28, title: "arc_race_debrief.py --calibrate --text" });
  // défaut → observé → proposé
  const kq = outCubic(seg(t, a1 + 2.6, a1 + 3.2));
  const PX = v => 780 + (v - 4) / 9 * 400;
  panel(750, 450, 450, 176, { r: 18, alpha: kq });
  line([[PX(4), 540], [PX(13), 540]], C.line, 2, kq);
  [[5, S.def, C.faint, -1], [12, S.obs, NIGHT, -1], [8.1111, S.prop, C.accent, 1]].forEach(([v, s, col, side], i) => {
    const k = outBack(seg(t, a1 + 3.0 + i * 0.7, a1 + 3.6 + i * 0.7)), kk = clamp(k);
    if (k <= 0) return;
    dot(PX(v), 540, i === 2 ? 9 : 7, col, kk);
    text(s, PX(v), 540 + side * 24 + (side > 0 ? 8 : 0), { size: 13, weight: 700, font: MONO, color: col, align: "center", alpha: kk });
  });
  const ka = seg(t, a1 + 4.6, a1 + 5.6);
  if (ka > 0) arrow(PX(12), 520, PX(8.3), 520, ka, C.accent, 0.9);
  text(S.w, 975, 606, { size: 12, font: MONO, color: C.faint, align: "center", alpha: outCubic(seg(t, a1 + 5.4, a1 + 6.0)) });
}

/* ------------------------------ 07 · un oui ------------------------------ */
function path(t, pts) {
  if (t <= pts[0][0]) return [pts[0][1], pts[0][2]];
  for (let i = 1; i < pts.length; i++) {
    if (t <= pts[i][0]) { const k = inOut(seg(t, pts[i - 1][0], pts[i][0])); return [lerp(pts[i - 1][1], pts[i][1], k), lerp(pts[i - 1][2], pts[i][2], k)]; }
  }
  const p = pts[pts.length - 1]; return [p[1], p[2]];
}
function sApply(t, d, cues) {
  head(S.k7, S.h7, t);
  const a0 = at(cues, 0, 0.6);
  const k0 = outCubic(seg(t, 0.3, 0.9));
  panel(80, 180, 420, 170, { r: 18, fill: C.panel2, stroke: C.accent, lw: 2, alpha: k0 });
  text(S.ask, 106, 224, { size: 20, weight: 800, font: SORA, alpha: k0 });
  text("night_penalty_pct : 5 → 8,1", 106, 256, { size: 14, font: MONO, color: C.soft, alpha: k0 });
  const T = a0 + 1.6, pressed = t >= T + 0.2;
  keyBtn(S.yes, 106, 280, 120, 44, pressed, { alpha: k0 });
  keyBtn(S.no, 242, 280, 120, 44, false, { alpha: k0 });
  const [cx, cy] = path(t, [[T - 1.2, 440, 460], [T, 106 + 72, 280 + 26]]);
  if (t > T - 1.2) cursor(cx, cy, { click: seg(t, T, T + 0.5), alpha: seg(t, T - 1.2, T - 0.8) * (1 - seg(t, T + 1.6, T + 2.2)) });
  // le fichier écrit, puis relu par les plans suivants
  const lines = [
    { s: "[pacing.personal]", c: C.accent, a: T + 0.6 },
    { s: "night_penalty_pct = 8.1111", c: C.ink, a: T + 1.0 },
    { s: 'evidence = ["2026-06-20|trail-des-lucioles|night|16|12.0"]', c: C.soft, a: T + 1.4 },
  ];
  terminal(540, 180, 660, 170, t, lines, { alpha: outCubic(seg(t, T + 0.4, T + 0.9)), size: 14, lh: 30, title: S.file });
  const kr = outCubic(seg(t, T + 2.6, T + 3.2));
  arrow(870, 360, 870, 410, seg(t, T + 2.6, T + 3.2), C.accent, kr);
  panel(540, 420, 660, 76, { r: 16, alpha: kr });
  text("arc_race_pacing.py", 566, 456, { size: 16, weight: 700, font: MONO, color: C.accent, alpha: kr });
  text(S.next, 566, 482, { size: 13, color: C.soft, alpha: kr });
  const kc = outBack(seg(t, T + 4.4, T + 5.0));
  if (kc > 0) pill(S.cumul, 540, 540, { size: 14, alpha: clamp(kc) });
}

/* ------------------------------ 08 · les pages de documentation ------------------------------ */
function sPages(t, d, cues) {
  head(S.k8, S.h8, t);
  const a0 = at(cues, 0, 0.6);
  S.pages.forEach(([title, sub, slug], i) => {
    const a = a0 + 0.8 + i * 1.4, k = outCubic(seg(t, a, a + 0.5)), y = 184 + i * 122;
    const on = t >= a && t < a + 1.4;
    panel(80, y + (1 - k) * 14, 1120, 104, { r: 18, fill: on ? "rgba(163,230,53,0.07)" : C.panel, stroke: on ? C.accent : C.line, lw: on ? 2 : 1, alpha: k });
    text(String(i + 1).padStart(2, "0"), 124, y + 64 + (1 - k) * 14, { size: 32, weight: 800, font: SORA, color: C.accent, align: "center", alpha: k });
    text(title, 176, y + 48 + (1 - k) * 14, { size: 26, weight: 800, font: SORA, alpha: k });
    text(sub, 176, y + 78 + (1 - k) * 14, { size: 15, color: C.soft, alpha: k });
    text(`${slug}/`, 1170, y + 62 + (1 - k) * 14, { size: 18, weight: 600, font: MONO, color: C.accent, align: "right", alpha: k });
  });
}

ARC.episode({
  n: 17, slug: "avant-apres",
  strings: STR,
  shots: ["forme-projection", "decision-effet", "decisions-effets"],
  scenes: { forecast: sForecast, taper: sTaper, altitude: sAltitude, effects: sEffects, caveat: sCaveat, debrief: sDebrief, apply: sApply, pages: sPages },
});
})();
