/* Le Sentier · étape 16 — « L'allure juste » : allure ajustée à la pente, modèle de Kay (2012) à la place de
 * Minetti (2002) et carte en mode GAP (#227, #228), courbe allure-durée et vitesse critique (#169), cibles en %
 * de cette vitesse et contrôle avec le seuil lactique de la montre, cibles ralenties par la chaleur (#171).
 * Carte, profil et vitesse critique : captures réelles du tableau de bord sur la variante « suite » du workspace
 * fictif (scripts/video_demo_workspace.py --suite : efforts posés dans les séances de seuil, trace fictive sans
 * fond de carte). Les cibles et l'ajustement à la chaleur sont la sortie de `arc_workout_targets.py targets`
 * sur ce même workspace ; les rapports de Kay et Minetti, les formules publiées (docs/gap.md).
 * Moteur : ../engine/engine.js (helpers globaux). Découpage et narration : script.json.
 * Athlète et chiffres fictifs (bible de la série : Camille, mardi 29 septembre 2026). */
"use strict";
(() => {
const BLUE = "#7fb3f0", LILAC = "#b39ddb";
/* Rapport d'allure pente / plat. Kay (2012) : quartique publiée, prolongée par sa tangente hors de
 * [−26,3 % ; +32,1 %] (inutile sur l'axe tracé). Minetti (2002) : coût énergétique / coût à plat (3,6 J/kg/m). */
const kay = m => 1 + 3.639 * m + 17.757 * m * m - 3.1 * m ** 3 - 23.834 * m ** 4;
const minetti = i => (155.4 * i ** 5 - 30.4 * i ** 4 - 43.3 * i ** 3 + 46.3 * i * i + 19.5 * i + 3.6) / 3.6;
/* Les sept meilleurs efforts de l'ajustement CS/D′ (durée s, distance m) : /api/pace-curve, variante « suite ». */
const PTS = [[180, 798.5], [300, 1260.0], [480, 1961.9], [600, 2433.4], [720, 2901.9], [900, 3601.6], [1200, 4768.4]];
const CS = 3.8959, DP = 94.5;

const STR = {
  fr: {
    dec: ",", k1: "01 · LA PENTE", h1: "Une côte vaut un plat.",
    axX: "pente", axY: "allure en pente ÷ allure à plat", flat: "plat",
    kayL: "Kay (2012)", minL: "Minetti (2002)",
    fast: "−10 % : × 0,81 · le plus rapide", up: "+10 % : × 1,54", twice: "−20 % : × 0,50 — deux fois plus vite ?",
    exT: "Exemple", ex: [["Montée à +10 %", "8:40/km"], ["÷ rapport de Kay", "1,54"], ["GAP", "5:38/km"]], exN: "= l'effort d'un plat à 5:38/km",
    src1: "Kay : records de 91 courses de montée et 15 de descente", src2: "Minetti : 10 coureurs sur tapis roulant",
    k2: "02 · LA CARTE", h2: "La trace, colorée par la GAP.",
    m1: "Mode GAP", m2: "même effort, même couleur", m3: "quintiles de la séance", m4: "trace fictive · sans fond de carte",
    p1: "allure brute : 10:00/km en montée", p2: "GAP en pointillés : presque plate", p3: "effort régulier",
    k3: "03 · LA COURBE", h3: "Ses meilleurs efforts, une droite.",
    eq: "distance = CS × t + D′", axT: "durée de l'effort", axD: "distance",
    cs: "CS 4:17/km", dp: "D′ 95 m", q: "qualité bonne · 7 efforts de 3 à 20 min", dpN: "D′ = ordonnée à l'origine",
    k4: "04 · OU RIEN", h4: "Pas assez de données ? Il le dit.",
    refT: "Motifs de refus",
    refs: [["insufficient_points", "moins de 3 durées entre 3 et 20 min"], ["single_source", "tous les efforts viennent d'une seule séance"],
      ["insufficient_span", "durée max / durée min < 3"], ["d_prime_out_of_range", "D′ hors de 30 – 1 000 m : courbe trop plate"],
      ["non_positive_cs", "vitesse critique nulle ou négative"], ["poor_fit", "R² < 0,95 : efforts hétérogènes"]],
    low: "meilleurs efforts d'entraînement, pas un test → CS plutôt basse, jamais flatteuse",
    k5: "05 · LES CIBLES", h5: "En % de la vitesse critique.",
    bands: [["Tempo", "88 – 95 %", "4:30 – 4:52/km"], ["Seuil", "95 – 100 %", "4:17 – 4:30/km"], ["VO2max", "102 – 110 %", "3:53 – 4:12/km"]],
    budget: "VO2max : budget D′ ≈ 4 min cumulées au-dessus de CS",
    sess: "Seuil 3 × 10 min", sessD: "mardi 6 octobre", hr: "Zone 4 · 163 – 172 bpm", csT: "95 – 100 % CS · 4:17 – 4:30/km",
    hrL: "FC", csL: "allure", compl: "en complément de la FC, jamais à sa place",
    lt: "Seuil lactique (montre)", ltV: "4:01/km", csN: "Vitesse critique", csV: "4:17/km", gap: "écart −6,1 %",
    flag: "signalé avec les deux valeurs · aucune n'est préférée",
    k6: "06 · LA CHALEUR", h6: "Plus chaud ? Plus lent, pas plus fort.",
    temp: "29 °C", tempN: "samedi 10 oct. · midi · 60 % d'humidité",
    long: "Sortie longue 2 h 45", rows: [["Durée", "2 h 45", "2 h 45", "inchangée"], ["Allure", "4:34 – 5:03", "5:17 – 5:50", "× 1,155"], ["FC", "146 – 155", "146 – 155", "inchangée"]],
    colB: "prévu", colA: "ajusté", hyd: "≥ 1 L/h · sodium · sudation observée ≈ 0,66 L/h",
    red: "35 °C · 🔴", redS: "Seuil 3 × 10 min", redA: "déplacé, ou allégé en endurance à la FC", redN: "intensité jamais maintenue",
    k7: "07 · LES PAGES", h7: "Deux pages à garder sous la main.",
    pages: [["Allure ajustée à la pente", "modèle de Kay, vérifications, limites", "gap"], ["Vitesse critique", "courbe allure-durée, CS et D′, refus, cibles", "vitesse-critique"]],
  },
  en: {
    dec: ".", k1: "01 · THE SLOPE", h1: "A climb worth a flat.",
    axX: "grade", axY: "pace on the slope ÷ flat pace", flat: "flat",
    kayL: "Kay (2012)", minL: "Minetti (2002)",
    fast: "−10%: × 0.81 · the fastest", up: "+10%: × 1.54", twice: "−20%: × 0.50 — twice as fast?",
    exT: "Example", ex: [["Climb at +10%", "8:40/km"], ["÷ Kay ratio", "1.54"], ["GAP", "5:38/km"]], exN: "= the effort of a flat run at 5:38/km",
    src1: "Kay: records of 91 uphill and 15 downhill races", src2: "Minetti: 10 runners on a treadmill",
    k2: "02 · THE MAP", h2: "The track, coloured by GAP.",
    m1: "GAP mode", m2: "same effort, same colour", m3: "session quintiles", m4: "fictional track · no base map",
    p1: "raw pace: 10:00/km on the climb", p2: "dotted GAP: almost flat", p3: "an even effort",
    k3: "03 · THE CURVE", h3: "Her best efforts, one straight line.",
    eq: "distance = CS × t + D′", axT: "effort duration", axD: "distance",
    cs: "CS 4:17/km", dp: "D′ 95 m", q: "good quality · 7 efforts from 3 to 20 min", dpN: "D′ = the intercept",
    k4: "04 · OR NOTHING", h4: "Not enough data? It says so.",
    refT: "Refusal reasons",
    refs: [["insufficient_points", "fewer than 3 durations between 3 and 20 min"], ["single_source", "every effort comes from a single session"],
      ["insufficient_span", "max duration / min duration < 3"], ["d_prime_out_of_range", "D′ outside 30 – 1,000 m: curve too flat"],
      ["non_positive_cs", "zero or negative critical speed"], ["poor_fit", "R² < 0.95: mixed efforts"]],
    low: "best training efforts, not a test → CS on the low side, never flattering",
    k5: "05 · THE TARGETS", h5: "As a % of critical speed.",
    bands: [["Tempo", "88 – 95%", "4:30 – 4:52/km"], ["Threshold", "95 – 100%", "4:17 – 4:30/km"], ["VO2max", "102 – 110%", "3:53 – 4:12/km"]],
    budget: "VO2max: D′ budget ≈ 4 min in total above CS",
    sess: "Threshold 3 × 10 min", sessD: "Tuesday, October 6", hr: "Zone 4 · 163 – 172 bpm", csT: "95 – 100% CS · 4:17 – 4:30/km",
    hrL: "HR", csL: "pace", compl: "alongside heart rate, never instead of it",
    lt: "Lactate threshold (watch)", ltV: "4:01/km", csN: "Critical speed", csV: "4:17/km", gap: "gap −6.1%",
    flag: "flagged with both values · neither is preferred",
    k6: "06 · THE HEAT", h6: "Hotter? Slower, not harder.",
    temp: "29 °C", tempN: "Sat Oct 10 · midday · 60% humidity",
    long: "Long run 2 h 45", rows: [["Duration", "2 h 45", "2 h 45", "unchanged"], ["Pace", "4:34 – 5:03", "5:17 – 5:50", "× 1.155"], ["HR", "146 – 155", "146 – 155", "unchanged"]],
    colB: "planned", colA: "adjusted", hyd: "≥ 1 L/h · sodium · observed sweat rate ≈ 0.66 L/h",
    red: "35 °C · 🔴", redS: "Threshold 3 × 10 min", redA: "moved, or lightened to endurance by HR", redN: "intensity never kept",
    k7: "07 · THE PAGES", h7: "Two pages to keep at hand.",
    pages: [["Grade adjusted pace", "Kay's model, checks, limits", "gap"], ["Critical speed", "pace-duration curve, CS and D′, refusals, targets", "vitesse-critique"]],
  },
};

/* ------------------------------- dessins locaux ------------------------------- */
function head(k, h, t) { kicker(k, seg(t, 0, 0.4)); headline(h, seg(t, 0.1, 0.7)); fictTag(seg(t, 0.3, 0.8)); }
function cross(x, y, s, col, alpha = 1) {
  line([[x - s, y - s], [x + s, y + s]], col, 3, alpha); line([[x + s, y - s], [x - s, y + s]], col, 3, alpha);
}
function label(s, x, y, k, o = {}) { text(s, x, y, { size: 12, weight: 600, font: MONO, color: o.color ?? C.accent, alpha: k, spacing: "2px", align: o.align }); }

/* ------------------------------ 01 · Kay contre Minetti ------------------------------ */
const KX0 = 100, KX1 = 690, KY0 = 600, KY1 = 196, M0 = -0.25, M1 = 0.25, R0 = 0.4, R1 = 3.0;
const kx = m => KX0 + (m - M0) / (M1 - M0) * (KX1 - KX0);
const ky = r => KY0 - (r - R0) / (R1 - R0) * (KY0 - KY1);
function curve(f) { const p = []; for (let m = M0; m <= M1 + 1e-9; m += 0.005) p.push([kx(m), ky(clamp(f(m), R0, R1))]); return p; }
const KAY = curve(kay), MIN = curve(minetti);
function sKay(t, d, cues) {
  head(S.k1, S.h1, t);
  const a0 = at(cues, 0, 0.6), a1 = at(cues, 1, 6);
  const ka = outCubic(seg(t, 0.3, 0.9));
  // grille
  [0.5, 1, 1.5, 2, 2.5].forEach(r => {
    line([[KX0, ky(r)], [KX1, ky(r)]], C.line, r === 1 ? 1.5 : 1, ka * (r === 1 ? 0.9 : 0.5));
    text(`× ${String(r).replace(".", S.dec)}`, KX0 - 12, ky(r) + 4, { size: 12, font: MONO, color: C.faint, align: "right", alpha: ka });
  });
  [-0.2, -0.1, 0, 0.1, 0.2].forEach(m => {
    line([[kx(m), KY0], [kx(m), KY1]], C.line, 1, ka * (m === 0 ? 0.8 : 0.35));
    text(m === 0 ? S.flat : `${m > 0 ? "+" : "−"}${Math.abs(m * 100)} %`, kx(m), KY0 + 22, { size: 12, font: MONO, color: C.faint, align: "center", alpha: ka });
  });
  text(S.axY, KX0, KY1 - 14, { size: 12, font: MONO, color: C.faint, alpha: ka });
  // Kay, tracé avec la voix
  const kk = seg(t, a0 + 0.6, a0 + 3.4);
  line(partial(KAY, kk), C.accent, 3.5);
  if (kk >= 1) text(S.kayL, kx(0.22), ky(kay(0.22)) - 14, { size: 14, weight: 700, color: C.accent, align: "right" });
  // Minetti, en pointillés rouges : exagère des deux côtés
  const km = seg(t, a1 + 0.3, a1 + 2.6);
  line(partial(MIN, km), C.red, 2.5, 0.9, [7, 6]);
  if (km >= 1) text(S.minL, kx(0.2) - 6, ky(minetti(0.2)) - 10, { size: 14, weight: 700, color: C.red, align: "right" });
  // repères
  const kf = outBack(seg(t, a0 + 3.6, a0 + 4.2));
  if (kf > 0) { dot(kx(-0.1), ky(kay(-0.1)), 6, C.accent, clamp(kf)); callout(S.fast, kx(-0.13), ky(2.55), kx(-0.1), ky(kay(-0.1)), seg(t, a0 + 3.6, a0 + 4.4), { size: 13, font: MONO, textColor: C.accent }); }
  const ku = outBack(seg(t, a0 + 4.4, a0 + 5.0));
  if (ku > 0) { dot(kx(0.1), ky(kay(0.1)), 6, C.accent, clamp(ku)); callout(S.up, kx(0.03), ky(2.2), kx(0.1), ky(kay(0.1)), seg(t, a0 + 4.4, a0 + 5.2), { size: 13, font: MONO, textColor: C.accent }); }
  const kt = outBack(seg(t, a1 + 2.8, a1 + 3.4));
  if (kt > 0) {
    const x = kx(-0.2), y = ky(minetti(-0.2));
    dot(x, y, 6, C.red, clamp(kt)); cross(x, y, 10, C.red, clamp(kt));
    callout(S.twice, kx(-0.1), ky(1.85), x, y, seg(t, a1 + 2.8, a1 + 3.6), { size: 13, font: MONO, color: C.red, textColor: C.red });
  }
  // exemple et sources
  const ke = outCubic(seg(t, a0 + 5.4, a0 + 6.0));
  panel(760, 196, 440, 236, { r: 18, alpha: ke });
  label(S.exT.toUpperCase(), 786, 230, ke);
  S.ex.forEach(([a, b], i) => {
    const k = outCubic(seg(t, a0 + 5.8 + i * 0.6, a0 + 6.3 + i * 0.6)) * ke, y = 272 + i * 44, last = i === 2;
    text(a, 786, y, { size: 17, weight: last ? 700 : 500, color: last ? C.accent : C.soft, alpha: k });
    text(b, 1176, y, { size: last ? 24 : 18, weight: 700, font: MONO, align: "right", color: last ? C.accent : C.ink, alpha: k });
  });
  text(S.exN, 786, 410, { size: 14, font: MONO, color: C.faint, alpha: outCubic(seg(t, a0 + 7.6, a0 + 8.2)) * ke });
  const ks = outCubic(seg(t, a1 + 3.6, a1 + 4.2));
  panel(760, 456, 440, 120, { r: 16, alpha: ks });
  dot(786, 492, 5, C.accent, ks); para(S.src1, 802, 497, 380, { size: 14, color: C.soft, alpha: ks });
  dot(786, 546, 5, C.red, ks); para(S.src2, 802, 551, 380, { size: 14, color: C.soft, alpha: ks });
}

/* ------------------------------ 02 · la carte et le profil (captures réelles) ------------------------------ */
function sMap(t, d, cues) {
  head(S.k2, S.h2, t);
  const a0 = at(cues, 0, 0.6), a1 = at(cues, 1, 6);
  const k0 = outCubic(seg(t, 0.3, 0.9)), sw = outCubic(seg(t, a1 - 0.5, a1 + 0.2));
  if (sw < 1) {
    const a = 480 / (470 - 30);
    const m = shot("gap-carte", 80, 168, 480, 470, { crop: cropTo("gap-carte", "carte", a, 8), alpha: k0 * (1 - sw), url: "127.0.0.1:8765/#/seance" });
    const b = m("bouton-gap");
    if (b) highlight(b[0], b[1], b[2], b[3], seg(t, a0 + 1.2, a0 + 1.8) * (1 - sw));
    const l = m("legende");
    if (l) highlight(l[0], l[1], l[2], l[3], seg(t, a0 + 3.0, a0 + 3.6) * (1 - sw), C.amber);
    const kr = (1 - sw);
    [[S.m1, C.accent, a0 + 1.4], [S.m2, C.ink, a0 + 2.4], [S.m3, C.soft, a0 + 3.4]].forEach(([s, col, a], i) => {
      const k = outCubic(seg(t, a, a + 0.5)) * kr;
      text(s, 610, 236 + i * 56, { size: i ? 20 : 26, weight: i ? 600 : 800, font: i ? INTER : SORA, color: col, alpha: k });
    });
    // l'échelle de la légende, redessinée en grand
    const kl = outCubic(seg(t, a0 + 3.4, a0 + 4.0)) * kr;
    ["#5fb07f", "#9fd17a", "#f0d050", "#f0a050", "#f07a5f"].forEach((c, i) => panel(610 + i * 76, 404, 68, 14, { r: 7, fill: c, stroke: false, alpha: kl }));
    text(S.m4, 610, 600, { size: 13, font: MONO, color: C.faint, alpha: outCubic(seg(t, a0 + 4.4, a0 + 5.0)) * kr });
  }
  if (sw > 0) {
    const crop = [248, 95, 1008, 1008 / (860 / 440)];
    const m = shot("gap-profil", 80, 168, 860, 470, { crop, alpha: sw, url: "127.0.0.1:8765/#/seance" });
    const pace = m([269, 518, 966, 84]), alt = m([269, 140, 966, 175]);
    if (alt) highlight(alt[0] + alt[2] * 0.02, alt[1], alt[2] * 0.5, alt[3], seg(t, a1 + 0.4, a1 + 1.0) * sw * (1 - seg(t, a1 + 2.4, a1 + 2.8)), C.amber);
    if (pace) highlight(pace[0], pace[1], pace[2], pace[3], seg(t, a1 + 2.6, a1 + 3.2) * sw);
    const kp = (s, y, col, a) => { const k = outCubic(seg(t, a, a + 0.5)) * sw; if (k > 0) para(s, 970, y, 230, { size: 17, weight: 600, color: col, alpha: k }); };
    kp(S.p1, 300, BLUE, a1 + 1.0);
    kp(S.p2, 400, LILAC, a1 + 3.0);
    const kc = outBack(seg(t, a1 + 4.6, a1 + 5.2));
    if (kc > 0) pill(S.p3, 970, 520, { size: 15, alpha: clamp(kc) });
  }
}

/* ------------------------------ 03 · courbe allure-durée et vitesse critique ------------------------------ */
function sCurve(t, d, cues) {
  head(S.k3, S.h3, t);
  const a0 = at(cues, 0, 0.6), a1 = at(cues, 1, 6);
  const k0 = outCubic(seg(t, 0.3, 0.9));
  const a = 700 / (450 - 30);
  const z = inOut(seg(t, a1 - 0.6, a1 + 0.4));
  const crop = lerpRect(cropTo("vitesse-critique", "courbe", a, 24), cropTo("vitesse-critique", [248, 70, 1008, 560], a, 0), z);
  const m = shot("vitesse-critique", 80, 168, 700, 450, { crop, alpha: k0, url: "127.0.0.1:8765/#/performance" });
  const v = m("valeur");
  if (v) highlight(v[0], v[1], v[2] * 0.42, v[3], seg(t, a1 + 1.6, a1 + 2.2));
  // la droite distance = CS × t + D′, avec les sept efforts réels
  const kd = outCubic(seg(t, a1 - 0.2, a1 + 0.5));
  const X0 = 850, X1 = 1180, Y0 = 520, Y1 = 236, T1 = 1300, D1 = 5100;
  const px = s => X0 + s / T1 * (X1 - X0), py = m_ => Y0 - m_ / D1 * (Y0 - Y1);
  panel(820, 168, 400, 450, { r: 18, alpha: kd });
  text(S.eq, 1020, 206, { size: 17, weight: 700, font: MONO, color: C.accent, align: "center", alpha: kd });
  line([[X0, Y0], [X1, Y0]], C.line, 1.5, kd); line([[X0, Y0], [X0, Y1]], C.line, 1.5, kd);
  text(S.axT, X1, Y0 + 24, { size: 12, font: MONO, color: C.faint, align: "right", alpha: kd });
  text(S.axD, X0 - 8, Y1 - 10, { size: 12, font: MONO, color: C.faint, alpha: kd });
  const kl = seg(t, a1 + 0.8, a1 + 2.4);
  line(partial([[px(0), py(DP)], [px(T1), py(DP + CS * T1)]], kl), C.accent, 2.5, kd);
  PTS.forEach(([s, dist], i) => { const k = outBack(seg(t, a1 + 0.2 + i * 0.12, a1 + 0.6 + i * 0.12)); if (k > 0) dot(px(s), py(dist), 5.5 * clamp(k, 0, 1.3), C.amber, kd); });
  const kv = outBack(seg(t, a1 + 2.4, a1 + 3.0));
  if (kv > 0) {
    const kk = clamp(kv);
    pill(S.cs, 846, 562, { size: 16, alpha: kk });
    pill(S.dp, 1014, 562, { size: 16, alpha: kk, color: C.amber, fill: "rgba(240,180,60,0.08)", stroke: "rgba(240,180,60,0.45)" });
    callout(S.dpN, 960, 300, px(0), py(DP), seg(t, a1 + 4.4, a1 + 5.2), { color: C.amber, size: 12, font: MONO });
    text(S.q, 846, 600, { size: 12, font: MONO, color: C.faint, alpha: kk });
  }
}

/* ------------------------------ 04 · ou rien : les refus ------------------------------ */
function sRefusal(t, d, cues) {
  head(S.k4, S.h4, t);
  const a0 = at(cues, 0, 0.6), a1 = at(cues, 1, 6);
  const k0 = outCubic(seg(t, 0.3, 0.9));
  panel(80, 168, 1120, 372, { r: 18, alpha: k0 });
  label(S.refT.toUpperCase(), 106, 202, k0);
  S.refs.forEach(([code, why], i) => {
    const a = a0 + 0.4 + i * 0.55, k = outCubic(seg(t, a, a + 0.45)), y = 236 + i * 48;
    if (k <= 0) return;
    const hot = t >= a && t < a + 0.9;
    panel(100, y - 2 + (1 - k) * 8, 1080, 40, { r: 10, fill: hot ? "rgba(240,122,95,0.10)" : "#0a120e", stroke: hot ? C.red : C.line, alpha: k });
    cross(126, y + 18 + (1 - k) * 8, 6, C.red, k);
    text(code, 150, y + 24 + (1 - k) * 8, { size: 15, weight: 700, font: MONO, color: C.red, alpha: k });
    text(why, 470, y + 24 + (1 - k) * 8, { size: 16, color: C.soft, alpha: k });
  });
  const kn = outBack(seg(t, a1 + 0.2, a1 + 0.8));
  if (kn > 0) {
    const kk = clamp(kn);
    panel(80, 562, 1120, 64, { r: 16, fill: "rgba(240,180,60,0.07)", stroke: C.amber, lw: 2, alpha: kk });
    text(S.low, 640, 600, { size: 17, weight: 600, color: C.amber, align: "center", alpha: kk });
  }
}

/* ------------------------------ 05 · cibles en % de CS, contrôle du seuil de la montre ------------------------------ */
function sTargets(t, d, cues) {
  head(S.k5, S.h5, t);
  const a0 = at(cues, 0, 0.6), a1 = at(cues, 1, 7);
  // trois plages, sur un axe de % de CS
  const X = p => 210 + (p - 85) / (112 - 85) * 400;
  const k0 = outCubic(seg(t, 0.3, 0.9));
  line([[X(85), 330], [X(112), 330]], C.line, 2, k0);
  [85, 90, 95, 100, 105, 110].forEach(p => text(`${p} %`, X(p), 356, { size: 12, font: MONO, color: C.faint, align: "center", alpha: k0 }));
  line([[X(100), 196], [X(100), 336]], C.accent, 2, k0, [5, 5]);
  text("CS", X(100), 188, { size: 13, weight: 700, font: MONO, color: C.accent, align: "center", alpha: k0 });
  const rng = [[88, 95, C.teal], [95, 100, C.amber], [102, 110, C.red]];
  S.bands.forEach(([n, pc, pace], i) => {
    const k = outCubic(seg(t, 0.6 + i * 0.3, 1.1 + i * 0.3)), [p0, p1, col] = rng[i], y = 214 + i * 36;
    panel(X(p0), y, (X(p1) - X(p0)) * k, 26, { r: 8, fill: col, stroke: false, alpha: 0.85 * k });
    text(n, 96, y + 18, { size: 14, weight: 700, alpha: k });
    text(pace, X(p1) + 10, y + 18, { size: 13, font: MONO, color: C.soft, alpha: k });
  });
  text(S.budget, 96, 392, { size: 13, font: MONO, color: C.faint, alpha: outCubic(seg(t, 2.0, 2.6)) });
  // la séance : FC d'abord, % de CS en complément
  const ks = outCubic(seg(t, a0 + 0.6, a0 + 1.2));
  panel(80, 420, 620, 200, { r: 18, fill: C.panel2, stroke: C.accent, alpha: ks });
  text(S.sess, 106, 462, { size: 22, weight: 800, font: SORA, alpha: ks });
  text(S.sessD, 674, 462, { size: 13, font: MONO, color: C.faint, align: "right", alpha: ks });
  const r1 = outCubic(seg(t, a0 + 1.6, a0 + 2.1)), r2 = outCubic(seg(t, a0 + 3.2, a0 + 3.7));
  pill(S.hrL, 106, 506, { size: 13, alpha: r1, color: C.red, fill: "rgba(240,122,95,0.08)", stroke: "rgba(240,122,95,0.45)" });
  text(S.hr, 170, 512, { size: 17, weight: 600, alpha: r1 });
  pill(S.csL, 106, 550, { size: 13, alpha: r2, color: C.amber, fill: "rgba(240,180,60,0.08)", stroke: "rgba(240,180,60,0.45)" });
  text(S.csT, 196, 556, { size: 17, weight: 600, color: C.amber, alpha: r2 });
  text(S.compl, 106, 596, { size: 13, font: MONO, color: C.faint, alpha: outCubic(seg(t, a0 + 4.6, a0 + 5.2)) });
  // le seuil de la montre contre la vitesse critique
  const kc = outCubic(seg(t, a1 - 0.2, a1 + 0.5));
  panel(740, 168, 460, 452, { r: 18, alpha: kc });
  const card = (n, v, y, col, a) => {
    const k = outCubic(seg(t, a, a + 0.5)) * kc;
    text(n, 766, y, { size: 15, color: C.soft, alpha: k });
    text(v, 1176, y + 4, { size: 30, weight: 800, font: SORA, color: col, align: "right", alpha: k });
  };
  card(S.lt, S.ltV, 232, C.ink, a1 + 0.4);
  card(S.csN, S.csV, 300, C.accent, a1 + 1.2);
  const kg = outBack(seg(t, a1 + 2.4, a1 + 3.0));
  if (kg > 0) {
    const kk = clamp(kg);
    line([[766, 340], [1176, 340]], C.line, 1, kk);
    pill(S.gap, 970, 380, { size: 18, align: "center", alpha: kk, color: C.amber, fill: "rgba(240,180,60,0.08)", stroke: "rgba(240,180,60,0.5)" });
  }
  // la balance : les deux plateaux restent à égalité
  const kb = outCubic(seg(t, a1 + 4.0, a1 + 4.6)) * kc;
  if (kb > 0) {
    const cx = 970, cy = 470;
    line([[cx, cy + 46], [cx, cy - 10]], C.soft, 3, kb);
    line([[cx - 110, cy - 10], [cx + 110, cy - 10]], C.soft, 3, kb);
    [[-110, S.ltV], [110, S.csV]].forEach(([dx, v]) => {
      line([[cx + dx, cy - 10], [cx + dx - 30, cy + 26], [cx + dx + 30, cy + 26], [cx + dx, cy - 10]], C.soft, 2, kb);
      text(v, cx + dx, cy + 46, { size: 14, weight: 700, font: MONO, color: C.ink, align: "center", alpha: kb });
    });
    para(S.flag, 766, 562, 410, { size: 14, color: C.soft, alpha: outCubic(seg(t, a1 + 5.0, a1 + 5.6)) * kc });
  }
}

/* ------------------------------ 06 · la chaleur ------------------------------ */
function thermo(x, y, k, fill, col) {
  panel(x - 14, y, 28, 150, { r: 14, fill: "#0a120e", stroke: C.line, alpha: k });
  dot(x, y + 168, 24, col, k);
  panel(x - 7, y + 150 - 140 * fill, 14, 140 * fill + 14, { r: 7, fill: col, stroke: false, alpha: k });
}
function sHeat(t, d, cues) {
  head(S.k6, S.h6, t);
  const a0 = at(cues, 0, 0.6), a1 = at(cues, 1, 8);
  const k0 = outCubic(seg(t, 0.3, 0.9)), sw = outCubic(seg(t, a1 - 0.3, a1 + 0.4));
  thermo(130, 196, k0, 0.25 + 0.45 * outCubic(seg(t, 0.6, 2.0)) + 0.25 * sw, sw > 0.5 ? C.red : C.amber);
  text(sw > 0.5 ? "35 °C" : S.temp, 190, 300, { size: 44, weight: 800, font: SORA, color: sw > 0.5 ? C.red : C.amber, alpha: k0 });
  text(S.tempN, 190, 334, { size: 13, font: MONO, color: C.faint, alpha: k0 * (1 - sw) });
  // la sortie longue : durée et FC tenues, allure ralentie
  const kc = outCubic(seg(t, a0 + 0.8, a0 + 1.4)) * (1 - sw * 0.75);
  panel(460, 168, 740, 300, { r: 18, alpha: kc });
  text(S.long, 486, 210, { size: 22, weight: 800, font: SORA, alpha: kc });
  text(S.colB, 800, 210, { size: 12, font: MONO, color: C.faint, align: "center", alpha: kc });
  text(S.colA, 990, 210, { size: 12, font: MONO, color: C.faint, align: "center", alpha: kc });
  const times = [a0 + 1.6, a0 + 3.0, a0 + 5.0];
  S.rows.forEach(([n, b, a, note], i) => {
    const k = outCubic(seg(t, times[i], times[i] + 0.5)) * kc, y = 262 + i * 58, moved = i === 1;
    panel(480, y - 26, 700, 46, { r: 10, fill: moved ? "rgba(240,180,60,0.07)" : "#0a120e", stroke: moved ? C.amber : C.line, alpha: k });
    text(n, 500, y + 3, { size: 16, weight: 600, alpha: k });
    text(b, 800, y + 3, { size: 16, font: MONO, color: C.soft, align: "center", alpha: k });
    arrow(870, y - 3, 912, y - 3, seg(t, times[i] + 0.3, times[i] + 0.7), C.faint, k);
    text(a, 990, y + 3, { size: 16, weight: 700, font: MONO, color: moved ? C.amber : C.ink, align: "center", alpha: k });
    if (moved) text(note, 1160, y + 3, { size: 14, weight: 700, font: MONO, color: C.amber, align: "right", alpha: k });
    else check(1146, y - 3, 10, C.teal, seg(t, times[i] + 0.5, times[i] + 0.9), k);
  });
  text(S.hyd, 486, 444, { size: 13, font: MONO, color: C.faint, alpha: outCubic(seg(t, a0 + 6.4, a0 + 7.0)) * kc });
  // en rouge : jamais d'intensité
  const kr = outBack(seg(t, a1 + 0.2, a1 + 0.9));
  if (kr > 0) {
    const kk = clamp(kr);
    panel(460, 490, 740, 136, { r: 18, fill: "rgba(240,122,95,0.07)", stroke: C.red, lw: 2, alpha: kk });
    text(S.red, 486, 530, { size: 16, weight: 700, font: MONO, color: C.red, alpha: kk });
    text(S.redS, 620, 530, { size: 18, weight: 700, alpha: kk });
    cross(1166, 524, 8, C.red, outCubic(seg(t, a1 + 1.0, a1 + 1.4)));
    text(S.redA, 486, 572, { size: 17, color: C.soft, alpha: outCubic(seg(t, a1 + 1.6, a1 + 2.2)) });
    pill(S.redN, 486, 604, { size: 13, alpha: outCubic(seg(t, a1 + 2.6, a1 + 3.2)), color: C.red, fill: "#0a120e", stroke: C.red });
  }
}

/* ------------------------------ 07 · les pages de documentation ------------------------------ */
function sPages(t, d, cues) {
  head(S.k7, S.h7, t);
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
  n: 16, slug: "allure-juste",
  strings: STR,
  shots: ["gap-carte", "gap-profil", "vitesse-critique"],
  scenes: { kay: sKay, map: sMap, curve: sCurve, refusal: sRefusal, targets: sTargets, heat: sHeat, pages: sPages },
});
})();
