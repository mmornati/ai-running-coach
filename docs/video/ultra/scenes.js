/* Le Sentier · étape 14 — « La nuit, la roche et le roadbook » : préparer un ultra avec la pénalité de nuit
 * (#184), la correction altimétrique par modèle de terrain (#176), la technicité du terrain (#186) et le
 * roadbook imprimable (#187). Le roadbook montré est celui du tableau de bord (captures réelles du
 * workspace fictif) ; chiffres de nuit et de technicité = ceux du vrai moteur sur l'Ultra des Crêtes
 * (scripts/video_demo_workspace.py, parcours inventé).
 * Moteur : ../engine/engine.js (helpers globaux). Découpage et narration : script.json.
 * Chaque scène reçoit (t, d, cues) : temps local, durée, répliques [{s, e, text}] —
 * at(cues, i, repli) cale une animation sur la voix, quelle que soit la langue.
 * Athlète et chiffres fictifs (bible de la série : Camille, mardi 29 septembre 2026). */
"use strict";
(() => {
const STR = {
  fr: {
    k1: "01 · LA NUIT", h1: "Le soleil, calculé sur place.",
    race: "Ultra des Crêtes · samedi 30 octobre 2027 · départ 16:00",
    tl: [["16:00", "départ"], ["18:25", "coucher du soleil"], ["18:56", "crépuscule civil"], ["03:00 → 02:00", "heure d'hiver"], ["04:08", "arrivée (J+1)"]],
    lamp: "frontale · 10,2 h de nuit", night: "NUIT",
    cards: [["Calcul local", "algorithme NOAA, sans réseau", "approximation de l'ordre de la minute"], ["+5 %", "de temps à pleine nuit", "à plat et en montée"], ["jusqu'à +8 points", "en descente", "0,6 point par % de pente au-delà de 2 %"]],
    none: "Date, heure de départ ou fuseau absents : aucune nuit supposée.",
    k2: "02 · LE RELIEF", h2: "Le dénivelé, corrigé par le terrain.",
    opt: "option · désactivée par défaut", rep: "exemple de rapport", gF: "D+ fichier", gM: "D+ MNT (référence)", gap: "−220 m (−12 %)",
    src: [["France", "RGE ALTI · IGN, pas de 1 m", "Licence Ouverte Etalab 2.0"], ["Ailleurs", "Copernicus GLO-90 via Open-Meteo", "pas de 90 m · CC BY 4.0"]],
    priv: ["coordonnées amincies : un point tous les 50 m", "jamais d'identifiant, de date ni de fréquence cardiaque", "vos séances : seulement si vous le demandez, début et fin rognés"],
    k3: "03 · LE SENTIER", h3: "Un sentier alpin n'est pas une piste.",
    chart: "coefficient de technicité par section · Ultra des Crêtes (km 0 → 66)", base: "terrain habituel = 1,00", axis: "km",
    tag: "sac_scale = alpine_hiking", tag2: "visibilité mauvaise · roche", tagC: "× 1,18",
    kp: [["max", "× 1,19"], ["moyenne", "× 1,04"]], bl: "--technicity-baseline mountain_hiking", blN: "seul l'écart avec votre terrain est compté",
    appr: "table de coefficients : approximation du projet, pas une mesure",
    k4: "04 · LE ROADBOOK", h4: "Une feuille par scénario.",
    cap1: "Profil · nuit hachurée · ravitos R1 à R4", cap2: "Passage à l'heure locale", cap3: "Barrière tendue : marge écrite", cap4: "Ce qu'on prend au ravito",
    k5: "05 · À IMPRIMER", h5: "Cochez, imprimez, partez.",
    st: [["Prêt", "ok"], ["À vérifier", "warn"], ["Jamais utilisé à l'entraînement", "warn"], ["Non retrouvé", "bad"]],
    capGear: "Matériel obligatoire · statut contre l'inventaire", paperT: "Ultra des Crêtes", paperPills: ["A4 portrait", "noir et blanc", "Imprimer / PDF"], absent: "Absent du plan = dit absent",
    k6: "06 · LES PAGES", h6: "Trois pages à garder sous la main.",
    pages: [["Stratège de course", "nuit, technicité, roadbook", "agents/course-strategist/"], ["Correction altimétrique", "modèle de terrain, vie privée", "elevation/"], ["Le roadbook du tableau de bord", "feuille imprimable", "dashboard/views/#roadbook"]],
  },
  en: {
    k1: "01 · THE NIGHT", h1: "The sun, computed locally.",
    race: "Ultra des Crêtes · Saturday October 30, 2027 · 4:00 p.m. start",
    tl: [["16:00", "start"], ["18:25", "sunset"], ["18:56", "civil dusk"], ["03:00 → 02:00", "clocks go back"], ["04:08", "finish (D+1)"]],
    lamp: "headlamp · 10.2 h of night", night: "NIGHT",
    cards: [["Local calculation", "NOAA algorithm, no network", "accurate to about a minute"], ["+5 %", "time in full darkness", "on flats and climbs"], ["up to +8 points", "on descents", "0.6 point per % of grade beyond 2 %"]],
    none: "Date, start time or time zone missing: no night is assumed.",
    k2: "02 · THE TERRAIN", h2: "Elevation gain, corrected by the ground.",
    opt: "option · off by default", rep: "sample report", gF: "File gain", gM: "DEM gain (reference)", gap: "−220 m (−12 %)",
    src: [["France", "RGE ALTI · IGN, 1 m grid", "Open Licence Etalab 2.0"], ["Elsewhere", "Copernicus GLO-90 via Open-Meteo", "90 m grid · CC BY 4.0"]],
    priv: ["thinned coordinates: one point every 50 m", "never an identifier, a date or a heart rate", "your sessions: only if you ask, start and end trimmed"],
    k3: "03 · THE TRAIL", h3: "An alpine trail is not a fire road.",
    chart: "technicality coefficient per section · Ultra des Crêtes (km 0 → 66)", base: "usual terrain = 1.00", axis: "km",
    tag: "sac_scale = alpine_hiking", tag2: "poor visibility · rock", tagC: "× 1.18",
    kp: [["max", "× 1.19"], ["mean", "× 1.04"]], bl: "--technicity-baseline mountain_hiking", blN: "only the gap with your own terrain is counted",
    appr: "coefficient table: a project approximation, not a measurement",
    k4: "04 · THE ROADBOOK", h4: "One sheet per scenario.",
    cap1: "Profile · night hatched · aid stations R1 to R4", cap2: "Passage on the local clock", cap3: "Tight cutoff: margin written out", cap4: "What to take at the aid station",
    k5: "05 · TO PRINT", h5: "Tick, print, go.",
    st: [["Ready", "ok"], ["To check", "warn"], ["Never used in training", "warn"], ["Not found", "bad"]],
    capGear: "Mandatory gear · status against your inventory", paperT: "Ultra des Crêtes", paperPills: ["A4 portrait", "black and white", "Print / PDF"], absent: "Missing from the plan = said missing",
    k6: "06 · THE PAGES", h6: "Three pages to keep handy.",
    pages: [["Race strategist", "night, technicality, roadbook", "agents/course-strategist/"], ["Elevation correction", "terrain model, privacy", "elevation/"], ["The dashboard roadbook", "printable sheet", "dashboard/views/#roadbook"]],
  },
};

const head = (k, h, t) => { kicker(k, seg(t, 0, 0.4)); headline(h, seg(t, 0.1, 0.7)); fictTag(seg(t, 0.3, 0.8)); };

/* ------------------------------ 01 · la nuit ------------------------------ */
function sNight(t, d, cues) {
  head(S.k1, S.h1, t);
  const a0 = at(cues, 0, 0.6), a1 = at(cues, 1, 5), a2 = at(cues, 2, 12);
  const k0 = outCubic(seg(t, 0.3, 0.9));
  text(S.race, 80, 176, { size: 14, font: MONO, color: C.faint, alpha: k0 });
  // axe du temps écoulé (0 → 13,2 h) : l'horloge murale se lit sous chaque repère
  const X0 = 100, X1 = 1180, HMAX = 13.2, x = h => X0 + (h / HMAX) * (X1 - X0), Y = 300;
  const kb = outCubic(seg(t, 0.6, 1.4));
  rr(X0, Y - 26, X1 - X0, 52, 10); ctx.save(); ctx.globalAlpha *= kb; ctx.fillStyle = "#101c16"; ctx.fill(); ctx.strokeStyle = C.line; ctx.stroke(); ctx.restore();
  // la nuit : de 18:56 (2,93 h) à l'arrivée (13,13 h), hachurée comme dans le roadbook
  const kn = outCubic(seg(t, a1 - 0.2, a1 + 1.4)), n0 = x(2.93), n1 = x(2.93 + (13.13 - 2.93) * kn);
  if (kn > 0) {
    ctx.save(); ctx.globalAlpha *= 0.9; rr(n0, Y - 26, n1 - n0, 52, 10); ctx.clip();
    ctx.fillStyle = "rgba(95,184,160,0.16)"; ctx.fillRect(n0, Y - 26, n1 - n0, 52);
    ctx.strokeStyle = "rgba(95,184,160,0.5)"; ctx.lineWidth = 1.5;
    for (let hx = n0 - 60; hx < n1 + 60; hx += 12) { ctx.beginPath(); ctx.moveTo(hx, Y + 26); ctx.lineTo(hx + 52, Y - 26); ctx.stroke(); }
    ctx.restore();
    pill(S.lamp, (n0 + n1) / 2, Y, { size: 14, alpha: seg(t, a1 + 0.8, a1 + 1.4), color: C.ink, fill: "rgba(15,42,31,0.92)", stroke: C.teal });
  }
  // les repères
  const marks = [[0, 0, a0 - 0.4, C.accent, true], [2.42, 1, a0 + 0.4, C.amber, false], [2.93, 2, a1, C.teal, false], [11.0, 3, a2, C.red, false], [13.13, 4, a1 + 1.6, C.accent, true]];
  marks.forEach(([h, i, a, col, big]) => {
    const k = outCubic(seg(t, a, a + 0.5)); if (k <= 0) return;
    const px = x(h), up = i % 2 === 0;
    line([[px, Y - 26], [px, up ? Y - 52 : Y + 60]], col, 2, k);
    dot(px, Y, big ? 7 : 5, col, k);
    const lab = S.tl[i];
    const al = i === 0 ? "left" : i === 4 ? "right" : "center", tx = i === 0 ? px - 8 : i === 4 ? px + 8 : px;
    text(lab[0], tx, up ? Y - 84 : Y + 82, { size: 17, weight: 800, font: MONO, color: col, align: al, alpha: k });
    text(lab[1], tx, up ? Y - 63 : Y + 102, { size: 13, color: C.soft, align: al, alpha: k });
  });
  // les trois règles
  S.cards.forEach(([big, mid, small], i) => {
    const a = a1 + 1.0 + i * 0.9, k = outCubic(seg(t, a, a + 0.5)); if (k <= 0) return;
    const cx = 80 + i * 380, cy = 440 + (1 - k) * 14;
    panel(cx, cy, 360, 118, { r: 16, alpha: k });
    text(big, cx + 24, cy + 46, { size: 26, weight: 800, font: SORA, color: i === 0 ? C.ink : C.accent, alpha: k });
    text(mid, cx + 24, cy + 74, { size: 15, weight: 600, alpha: k });
    text(small, cx + 24, cy + 98, { size: 12, font: MONO, color: C.faint, alpha: k });
  });
  const kc = outCubic(seg(t, a2 + 1.2, a2 + 1.8));
  if (kc > 0) para(S.none, 80, 600, 1120, { size: 14, color: C.soft, alpha: kc });
}

/* ------------------------------ 02 · le relief (modèle de terrain) ------------------------------ */
function sRock(t, d, cues) {
  head(S.k2, S.h2, t);
  const a0 = at(cues, 0, 0.6), a1 = at(cues, 1, 6);
  const k0 = outCubic(seg(t, 0.3, 0.9));
  pill(S.opt, 80, 186, { size: 13, alpha: k0, color: C.amber, fill: "rgba(240,180,60,0.08)", stroke: "rgba(240,180,60,0.45)" });
  // les deux D+
  panel(80, 224, 560, 250, { r: 18, alpha: k0 });
  text(S.rep.toUpperCase(), 106, 256, { size: 12, weight: 600, font: MONO, color: C.faint, spacing: "2px", alpha: k0 });
  const bars = [[S.gF, 1840, C.faint, 0], [S.gM, 1620, C.accent, 1]];
  bars.forEach(([lab, v, col, i]) => {
    const a = a0 + 1.2 + i * 1.6, k = outCubic(seg(t, a, a + 0.9)), y = 282 + i * 88;
    text(lab, 106, y + 18, { size: 15, weight: 600, color: i ? C.accent : C.soft, alpha: k0 });
    rr(106, y + 28, 500, 22, 6); ctx.save(); ctx.globalAlpha *= k0; ctx.fillStyle = "#0a120e"; ctx.fill(); ctx.restore();
    rr(106, y + 28, Math.max(8, 500 * (v / 1840) * k), 22, 6); ctx.save(); ctx.globalAlpha *= k0; ctx.fillStyle = col; ctx.fill(); ctx.restore();
    text(`${Math.round(v * k).toLocaleString("fr-FR").replace(/ /g, " ")} m`, 606, y + 18, { size: 20, weight: 800, font: SORA, align: "right", alpha: k0 });
  });
  const kg = outBack(seg(t, a0 + 4.2, a0 + 4.8));
  if (kg > 0) pill(S.gap, 106, 452, { size: 15, alpha: clamp(kg), color: C.amber, fill: "rgba(240,180,60,0.1)", stroke: "rgba(240,180,60,0.5)" });
  // les deux sources
  S.src.forEach(([zone, name, lic], i) => {
    const a = a0 + 1.0 + i * 1.0, k = outCubic(seg(t, a, a + 0.5)); if (k <= 0) return;
    const y = 224 + i * 130;
    panel(680, y + (1 - k) * 12, 520, 116, { r: 16, alpha: k });
    text(zone.toUpperCase(), 706, y + 36 + (1 - k) * 12, { size: 12, weight: 600, font: MONO, color: C.teal, spacing: "2px", alpha: k });
    text(name, 706, y + 66 + (1 - k) * 12, { size: 18, weight: 700, alpha: k });
    text(lic, 706, y + 92 + (1 - k) * 12, { size: 13, font: MONO, color: C.faint, alpha: k });
  });
  // vie privée
  S.priv.forEach((s, i) => {
    const a = a1 + i * 0.8, k = outCubic(seg(t, a, a + 0.5)); if (k <= 0) return;
    const y = 506 + i * 46;
    panel(80, y + (1 - k) * 10, 1120, 38, { r: 12, alpha: k });
    check(106, y + 20 + (1 - k) * 10, 10, C.teal, seg(t, a + 0.2, a + 0.7), k);
    text(s, 130, y + 25 + (1 - k) * 10, { size: 15, weight: 600, alpha: k });
  });
}

/* ------------------------------ 03 · la technicité ------------------------------ */
const TECH = [[0, 13.7, 1.0], [13.7, 16.8, 1.0], [16.8, 19.8, 1.065], [19.8, 21.3, 1.178], [21.3, 22.8, 1.181], [22.8, 25.9, 1.105],
  [25.9, 42.7, 1.0], [42.7, 45.7, 1.038], [45.7, 47.2, 1.083], [47.2, 48.7, 1.066], [48.7, 50.3, 1.102], [50.3, 53.3, 1.062],
  [53.3, 56.4, 1.0], [56.4, 59.4, 1.142], [59.4, 60.9, 1.189], [60.9, 65.9, 1.0]];
function sTerrain(t, d, cues) {
  head(S.k3, S.h3, t);
  const a0 = at(cues, 0, 0.6), a1 = at(cues, 1, 6);
  const px = 80, pw = 1120, py = 176, ph = 300, k0 = outCubic(seg(t, 0.3, 0.9));
  panel(px, py, pw, ph, { r: 18, alpha: k0 });
  text(S.chart, px + 24, py + 34, { size: 13, font: MONO, color: C.faint, alpha: k0 });
  const X = km => px + 40 + (km / 66) * (pw - 80), by = py + ph - 46, H = 170;
  line([[px + 40, by], [px + pw - 40, by]], C.line, 1.5, k0);
  [0, 10, 20, 30, 40, 50, 60].forEach(km => text(String(km), X(km), by + 22, { size: 12, font: MONO, color: C.faint, align: "center", alpha: k0 }));
  text(S.axis, px + pw - 40, by + 40, { size: 12, font: MONO, color: C.faint, align: "right", alpha: k0 });
  const prog = outCubic(seg(t, a0 + 0.4, a0 + 4.5));
  TECH.forEach(([k1, k2, c]) => {
    if (X(k1) > X(66 * prog)) return;
    const hh = Math.max(3, (c - 1) / 0.2 * H), w = Math.min(X(k2), X(66 * prog)) - X(k1) - 2;
    rr(X(k1), by - hh, w, hh, 4); ctx.save(); ctx.globalAlpha *= k0; ctx.fillStyle = c >= 1.15 ? C.amber : c > 1.0 ? "rgba(240,180,60,0.55)" : "rgba(95,184,160,0.45)"; ctx.fill(); ctx.restore();
  });
  line([[px + 40, by - 3], [px + pw - 40, by - 3]], C.teal, 1.5, k0 * 0.8, [5, 5]);
  text(S.base, px + 44, by - 12, { size: 12, font: MONO, color: C.teal, alpha: k0 });
  // le passage rocheux
  const kc = outBack(seg(t, a0 + 4.4, a0 + 5.0));
  if (kc > 0) {
    const cx = X(21.3);
    callout(S.tag, cx - 90, py + 76, X(20.5), by - (1.178 - 1) / 0.2 * H - 4, clamp(kc), { align: "right", font: MONO, size: 13, color: C.amber });
    text(S.tag2, cx - 90, py + 108, { size: 12, color: C.soft, align: "right", alpha: clamp(kc) });
    pill(S.tagC, cx - 50, py + 76, { size: 16, alpha: clamp(kc), color: C.amber, fill: "rgba(240,180,60,0.1)", stroke: "rgba(240,180,60,0.5)" });
  }
  // maximum, moyenne
  S.kp.forEach(([lab, val], i) => {
    const k = outCubic(seg(t, a1 + 0.2 + i * 0.5, a1 + 0.7 + i * 0.5)); if (k <= 0) return;
    const x = 80 + i * 190;
    panel(x, 500 + (1 - k) * 10, 176, 84, { r: 14, alpha: k });
    text(lab.toUpperCase(), x + 20, 530 + (1 - k) * 10, { size: 12, weight: 600, font: MONO, color: C.faint, spacing: "2px", alpha: k });
    text(val, x + 20, 566 + (1 - k) * 10, { size: 28, weight: 800, font: SORA, color: C.amber, alpha: k });
  });
  const kb = outCubic(seg(t, a1 + 1.4, a1 + 2.0));
  if (kb > 0) {
    panel(470, 500 + (1 - kb) * 10, 730, 84, { r: 14, alpha: kb });
    text(S.bl, 494, 534 + (1 - kb) * 10, { size: 16, weight: 700, font: MONO, color: C.accent, alpha: kb });
    text(S.blN, 494, 564 + (1 - kb) * 10, { size: 15, weight: 600, alpha: kb });
  }
  const ka = outCubic(seg(t, a1 + 3.0, a1 + 3.6));
  if (ka > 0) text(S.appr, 80, 622, { size: 13, font: MONO, color: C.faint, alpha: ka });
}

/* ------------------------------ 04 · le roadbook ------------------------------ */
const FX = 80, FY = 170, FW = 1120, FH = 450;
function sRoadbook(t, d, cues) {
  head(S.k4, S.h4, t);
  const a0 = at(cues, 0, 0.6), a1 = at(cues, 1, 6);
  const k0 = outCubic(seg(t, 0.3, 0.9)), sw = outCubic(seg(t, a1 - 0.4, a1 + 0.3));
  const asp = FW / (FH - 30);
  if (sw < 1) {
    const z = inOut(seg(t, 0.5, a1));
    const crop = lerpRect(cropTo("roadbook", [248, 330, 1008, 440], asp, 0), cropTo("roadbook", "profil", asp, 24), z);
    const m = shot("roadbook", FX, FY, FW, FH, { crop, alpha: k0 * (1 - sw), url: "127.0.0.1:8765/#/roadbook" });
    const r = m("profil");
    if (r) { highlight(r[0], r[1], r[2], r[3], seg(t, a0 + 1.4, a0 + 2.0) * (1 - sw)); }
    const kc = outCubic(seg(t, a0 + 1.8, a0 + 2.4)) * (1 - sw);
    if (kc > 0) pill(S.cap1, FX + FW / 2, FY + FH - 24, { size: 14, alpha: kc, color: C.ink, fill: "rgba(15,42,31,0.92)", stroke: C.accent });
  }
  if (sw > 0) {
    const crop = cropTo("roadbook-sections", [262, 110, 975, 420], asp, 0);
    const m = shot("roadbook-sections", FX, FY, FW, FH, { crop, alpha: sw, url: "127.0.0.1:8765/#/roadbook" });
    [["passage", S.cap2, a1 + 0.8, C.accent, "left"], ["barriere-tendue", S.cap3, a1 + 3.2, C.amber, "left"], ["a-prendre", S.cap4, a1 + 5.6, C.accent, "right"]].forEach(([b, cap, a, col, al]) => {
      const r = m(b), k = seg(t, a, a + 0.6), life = 1 - seg(t, a + 1.8, a + 2.2);
      if (!r) return;
      highlight(r[0], r[1], r[2], r[3], k * life * sw, col);
      if (k > 0 && life > 0) {
        ctx.save(); ctx.globalAlpha *= life;
        pill(cap, clamp(r[0] + r[2] / 2, 260, 1020), FY + FH - 22, { size: 14, alpha: outCubic(k), color: C.ink, fill: "rgba(15,42,31,0.92)", stroke: col, align: "center" });
        ctx.restore();
      }
    });
  }
}

/* ------------------------------ 05 · matériel et impression ------------------------------ */
function sGear(t, d, cues) {
  head(S.k5, S.h5, t);
  const a0 = at(cues, 0, 0.6), a1 = at(cues, 1, 6);
  const k0 = outCubic(seg(t, 0.3, 0.9));
  const SW = 740, SH = 316, asp = SW / (SH - 30);
  const m = shot("roadbook-materiel", 80, 176, SW, SH, { crop: cropTo("roadbook-materiel", [262, 570, 820, 317], asp, 0), alpha: k0, url: "127.0.0.1:8765/#/roadbook" });
  const rm = m("manquant");
  if (rm) highlight(rm[0], rm[1], rm[2], rm[3], seg(t, a0 + 3.8, a0 + 4.4), C.red);
  text(S.capGear, 80, 512, { size: 13, font: MONO, color: C.faint, alpha: k0 });
  // les quatre statuts
  const col = { ok: C.teal, warn: C.amber, bad: C.red };
  let px = 80, py = 546;
  S.st.forEach(([lab, kind], i) => {
    const a = a0 + 0.8 + i * 1.0, k = outCubic(seg(t, a, a + 0.5)); if (k <= 0) return;
    const w = measure(lab, 14, 600, MONO) + 60;
    if (px + w > 820) { px = 80; py += 50; }
    panel(px, py - 20 + (1 - k) * 10, w, 40, { r: 20, fill: "#0a120e", stroke: col[kind], alpha: k });
    if (kind === "ok") check(px + 24, py + (1 - k) * 10, 9, col[kind], seg(t, a + 0.2, a + 0.7), k); else dot(px + 24, py + (1 - k) * 10, 5, col[kind], k);
    text(lab, px + 42, py + 5 + (1 - k) * 10, { size: 14, weight: 600, font: MONO, color: col[kind], alpha: k });
    px += w + 12;
  });
  // la feuille A4 noir et blanc
  const kp = outBack(seg(t, a1 - 0.2, a1 + 0.6));
  if (kp > 0) {
    const k = clamp(kp), sx = 900, sy = 176 + (1 - k) * 24, sw = 270, sh = 382;
    ctx.save(); ctx.globalAlpha *= k; ctx.shadowColor = "rgba(0,0,0,0.5)"; ctx.shadowBlur = 24; rr(sx, sy, sw, sh, 6); ctx.fillStyle = C.paper; ctx.fill(); ctx.restore();
    text(S.paperT, sx + 20, sy + 36, { size: 17, weight: 800, font: SORA, color: C.paperInk, alpha: k });
    line([[sx + 20, sy + 46], [sx + sw - 20, sy + 46]], "#1c2b24", 1.5, k);
    // profil hachuré en noir et blanc
    ctx.save(); ctx.globalAlpha *= k; ctx.beginPath(); ctx.moveTo(sx + 20, sy + 120);
    for (let i = 0; i <= 40; i++) ctx.lineTo(sx + 20 + i * (sw - 40) / 40, sy + 120 - 40 * ridge(i / 40, 1.3));
    ctx.lineTo(sx + sw - 20, sy + 120); ctx.closePath(); ctx.fillStyle = "#cfd3cf"; ctx.fill(); ctx.strokeStyle = "#1c2b24"; ctx.lineWidth = 1.5; ctx.stroke(); ctx.clip();
    ctx.strokeStyle = "#1c2b24"; ctx.lineWidth = 0.8;
    for (let hx = sx + 100; hx < sx + sw; hx += 7) { ctx.beginPath(); ctx.moveTo(hx, sy + 124); ctx.lineTo(hx + 30, sy + 70); ctx.stroke(); }
    ctx.restore();
    for (let i = 0; i < 9; i++) { line([[sx + 20, sy + 150 + i * 16], [sx + sw - 20 - (i % 3) * 30, sy + 150 + i * 16]], "#7d8e85", 3, k * 0.6); }
    for (let i = 0; i < 4; i++) { rr(sx + 20, sy + 304 + i * 16, 9, 9, 2); ctx.save(); ctx.globalAlpha *= k; ctx.strokeStyle = "#1c2b24"; ctx.lineWidth = 1.2; ctx.stroke(); ctx.restore(); line([[sx + 38, sy + 309 + i * 16], [sx + 150 + (i % 2) * 40, sy + 309 + i * 16]], "#7d8e85", 3, k * 0.6); }
    S.paperPills.forEach((s, i) => pill(s, sx + sw / 2, sy + sh + 38 + i * 34 - (i === 0 ? 0 : 0), { size: 13, align: "center", alpha: seg(t, a1 + 0.8 + i * 0.5, a1 + 1.3 + i * 0.5) }));
  }
  const ka = outCubic(seg(t, a1 + 3.4, a1 + 4.0));
  if (ka > 0) para(S.absent, 80, 656, 760, { size: 15, weight: 600, color: C.soft, alpha: ka });
}

/* ------------------------------ 06 · les pages ------------------------------ */
function sPages(t, d, cues) {
  head(S.k6, S.h6, t);
  const a0 = at(cues, 0, 0.6);
  S.pages.forEach(([title, sub, slug], i) => {
    const a = a0 + 1.0 + i * 1.3, k = outCubic(seg(t, a, a + 0.5)), y = 184 + i * 120;
    const on = t >= a && t < a + 1.3;
    panel(80, y + (1 - k) * 14, 1120, 100, { r: 18, fill: on ? "rgba(163,230,53,0.07)" : C.panel, stroke: on ? C.accent : C.line, lw: on ? 2 : 1, alpha: k });
    text(String(i + 1).padStart(2, "0"), 124, y + 62 + (1 - k) * 14, { size: 32, weight: 800, font: SORA, color: C.accent, align: "center", alpha: k });
    text(title, 176, y + 46 + (1 - k) * 14, { size: 24, weight: 800, font: SORA, alpha: k });
    text(sub, 176, y + 76 + (1 - k) * 14, { size: 15, color: C.soft, alpha: k });
    text(slug, 1170, y + 60 + (1 - k) * 14, { size: 16, weight: 600, font: MONO, color: C.accent, align: "right", alpha: k });
  });
}

ARC.episode({
  n: 14, slug: "ultra",
  strings: STR,
  shots: ["roadbook", "roadbook-sections", "roadbook-materiel"],
  scenes: { night: sNight, rock: sRock, terrain: sTerrain, roadbook: sRoadbook, gear: sGear, pages: sPages },
});
})();
