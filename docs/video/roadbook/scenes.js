/* Le Sentier · étape 24 — « Le nouveau roadbook » : le tableau de bord en design roadbook (1.4).
 * Remplace la visite de l'étape 05 (ancien design) pour le nouveau. Captures réelles du tableau de bord
 * (workspace fictif de Camille) : ../shots-roadbook/, écrites par `scripts/video_capture.py --design roadbook`.
 * Faits : docs/dashboard/index.md (« Le design roadbook », « Installer l'application (PWA) », sécurité),
 * web/js/beta.js (profil du bloc, feuille du jour, bilan en lignes de barrière, Semaine à une ligne par séance,
 * rail, barre du bas, feuille « Sections »), web/sw.js (la coque seule est mise en cache : `/api` et `/media`
 * passent toujours par le réseau), web/fonts/ (polices locales), `?design=classic` (jusqu'à la 1.5).
 * Moteur : ../engine/engine.js (helpers globaux). Découpage et narration : script.json.
 * Athlète et chiffres fictifs (bible de la série : Camille, mardi 29 septembre 2026). */
"use strict";
(() => {
const AMBER = "#f0b43c", CORAL = "#f07a5f";
const STR = {
  fr: {
    k1: "01 · LE PROFIL DU BLOC", h1: "La saison, lue comme un roadbook.",
    cH: "hauteur : volume prévu", cF: "plein : réalisé", cP: "phases = sections", cI: "vous êtes ici", cR: "le jour de course",
    cHov: "survol ou clavier : la semaine se raconte", cClick: "un clic l'ouvre",
    k2: "02 · LA FEUILLE DE RAVITO", h2: "Le verdict, en grand.",
    cV: "le verdict du coach", cS: "séance remplacée → la nouvelle", cW: "qui a décidé · « Pourquoi cette décision »",
    k3: "03 · LES LIGNES DE BARRIÈRE", h3: "Valeur, référence, état.",
    cVal: "valeur", cRef: "référence", cSt: "état : forme + mot", cNo: "jamais la couleur seule",
    stA: "▲ sous la bande", stB: "◆ faible",
    k4: "04 · LA SEMAINE", h4: "Prévu et réalisé sur une ligne.",
    cL: "la séance prévue", cAct: "l'activité appariée dessous", cDur: "prévu → réalisé", cStat: "statut",
    stats: ["Faite", "Écourtée", "Allongée", "Manquée"], statsN: "écourtée < 80 % · allongée > 125 % (approximation du projet)",
    k5: "05 · SE DÉPLACER", h5: "Un rail sur ordinateur, une barre sur téléphone.",
    rail: "Rail · ordinateur", railG: ["Au quotidien", "Entraînement", "Corps et matériel", "Course", "Journal"],
    bar: "Barre du bas · téléphone", barI: ["Aujourd'hui", "Semaine", "Santé", "Coach ou Course", "Sections"], sheet: "feuille « Toutes les sections »",
    k6: "06 · UNE APPLICATION", h6: "Installable, sans réseau, sans vos données.",
    home: "écran d'accueil", appName: "AI Running Coach", offline: "hors ligne",
    shell: "la coque", shellI: "pages · styles · scripts · polices · icônes", shellN: "s'ouvre hors ligne",
    data: "les données", dataI: "santé · séances · photos (/api, /media)", dataN: "jamais en cache : lues au serveur",
    k7: "07 · CHEZ VOUS", h7: "Rien ne part, l'ancien design reste là.",
    machine: "votre machine · 127.0.0.1", dash: "tableau de bord", fonts: "web/fonts/ · Inter · Sora · Barlow Condensed", ofl: "licence SIL OFL 1.1",
    gf: "Google Fonts", none: "aucun appel", tiles: "Seule exception : les tuiles du fond de carte (la zone affichée, jamais la trace).",
    oldUrl: "127.0.0.1:8765/?design=classic", oldNote: "« Ancien design (jusqu'à la 1.5) », en bas du menu des sections",
    t14: "1.4 · roadbook par défaut", t15: "1.5 · ancien design retiré",
  },
  en: {
    k1: "01 · THE BLOCK PROFILE", h1: "The season, read like a roadbook.",
    cH: "height: planned volume", cF: "fill: done", cP: "phases = sections", cI: "you are here", cR: "race day",
    cHov: "hover or keyboard: the week tells its story", cClick: "a click opens it",
    k2: "02 · THE AID-STATION SHEET", h2: "The verdict, in large type.",
    cV: "the coach's verdict", cS: "replaced session → the new one", cW: "who decided · “Why this decision”",
    k3: "03 · THE CUT-OFF LINES", h3: "Value, reference, state.",
    cVal: "value", cRef: "reference", cSt: "state: shape + word", cNo: "never colour alone",
    stA: "▲ below the band", stB: "◆ low",
    k4: "04 · THE WEEK", h4: "Planned and done on one line.",
    cL: "the planned session", cAct: "the matched activity below", cDur: "planned → done", cStat: "status",
    stats: ["Done", "Cut short", "Extended", "Missed"], statsN: "cut short < 80% · extended > 125% (project approximation)",
    k5: "05 · GETTING AROUND", h5: "A rail on a computer, a bar on a phone.",
    rail: "Rail · computer", railG: ["Daily", "Training", "Body and gear", "Race", "Journal"],
    bar: "Bottom bar · phone", barI: ["Today", "Week", "Health", "Coach or Race", "Sections"], sheet: "“All sections” sheet",
    k6: "06 · AN APP", h6: "Installable, offline without your data.",
    home: "home screen", appName: "AI Running Coach", offline: "offline",
    shell: "the shell", shellI: "pages · styles · scripts · fonts · icons", shellN: "opens offline",
    data: "the data", dataI: "health · sessions · photos (/api, /media)", dataN: "never cached: read from the server",
    k7: "07 · STAYING HOME", h7: "Nothing leaves, the old design stays.",
    machine: "your machine · 127.0.0.1", dash: "dashboard", fonts: "web/fonts/ · Inter · Sora · Barlow Condensed", ofl: "SIL OFL 1.1 licence",
    gf: "Google Fonts", none: "no call", tiles: "One exception: map background tiles (the area shown, never the track).",
    oldUrl: "127.0.0.1:8765/?design=classic", oldNote: "“Old design (until 1.5)”, at the bottom of the sections menu",
    t14: "1.4 · roadbook by default", t15: "1.5 · old design removed",
  },
};
const S = new Proxy({}, { get: (_, k) => (STR[LANG] && STR[LANG][k]) ?? STR.en[k] });

const FX = 80, FY = 172, FW = 1120, FH = 360, CY = 566;
function head(k, h, t) { kicker(k, seg(t, 0, 0.4)); headline(h, seg(t, 0.1, 0.7), 132, 40); fictTag(seg(t, 0.3, 0.8)); }
function cap(s, x, k, col = C.accent, y = CY) { if (k > 0) pill(s, x, y, { size: 14, alpha: k, color: C.ink, fill: "rgba(15,42,31,0.92)", stroke: col, align: "center" }); }
const asp = FW / (FH - 30);
/* Union de boîtes d'une capture → rectangle [x, y, w, h]. */
function union(n, names) {
  const bs = names.map(b => shotBox(n, b)).filter(Boolean);
  const x0 = Math.min(...bs.map(b => b[0])), y0 = Math.min(...bs.map(b => b[1]));
  const x1 = Math.max(...bs.map(b => b[0] + b[2])), y1 = Math.max(...bs.map(b => b[1] + b[3]));
  return [x0, y0, x1 - x0, y1 - y0];
}
const hl = (r, k, col) => { if (r) highlight(r[0], r[1], r[2], r[3], k, col); };
const URL = "127.0.0.1:8765/";

/* ------------------------------ 01 · le profil du bloc ------------------------------ */
function sProfil(t, d, cues) {
  head(S.k1, S.h1, t);
  const a0 = at(cues, 0, 0.6), a1 = at(cues, 1, 10), a2 = at(cues, 2, 17);
  const k0 = outCubic(seg(t, 0.3, 0.9));
  const n = "rb-profil", wide = union(n, ["profil", "ici", "phases", "lecture"]);
  const z = inOut(seg(t, 0.5, a0 + 3));
  const crop = lerpRect(cropTo(n, [250, 52, 1190, 400], asp, 0), [wide[0] - 14, wide[1] - 8, wide[2] + 28, (wide[2] + 28) / asp], z);
  const m = shot(n, FX, FY, FW, FH, { crop, alpha: k0, url: URL });
  const p = m("profil");
  if (p) {
    const k1 = seg(t, a0 + 5.6, a0 + 6.2);
    hl(m("course") && [m("course")[0], m("course")[1], m("course")[2], m("course")[3]], seg(t, a0 + 5.6, a0 + 6.4) * (1 - seg(t, a1 - 0.2, a1 + 0.3)), C.amber);
    cap(S.cR, m("course") ? m("course")[0] + m("course")[2] / 2 : 1000, k1 * (1 - seg(t, a1 - 0.2, a1 + 0.3)), C.amber);
    // sentence 2 : prévu / réalisé / phases / ici
    hl([p[0], p[1] + 8, p[2], p[3]], seg(t, a1 + 0.3, a1 + 0.9) * (1 - seg(t, a1 + 3.4, a1 + 3.9)));
    const kc = outCubic(seg(t, a1 + 0.8, a1 + 1.4)) * (1 - seg(t, a1 + 3.4, a1 + 3.9));
    cap(S.cH, FX + 300, kc); cap(S.cF, FX + 640, kc);
    hl(m("phases"), seg(t, a1 + 3.0, a1 + 3.6) * (1 - seg(t, a1 + 5.0, a1 + 5.5)), C.teal);
    cap(S.cP, FX + FW / 2, outCubic(seg(t, a1 + 3.2, a1 + 3.8)) * (1 - seg(t, a1 + 5.0, a1 + 5.5)), C.teal);
    hl(m("ici"), seg(t, a1 + 5.0, a1 + 5.6) * (1 - seg(t, a2 - 0.2, a2 + 0.3)), C.accent);
    cap(S.cI, m("ici") ? m("ici")[0] + m("ici")[2] / 2 : 400, outCubic(seg(t, a1 + 5.2, a1 + 5.8)) * (1 - seg(t, a2 - 0.2, a2 + 0.3)));
    // sentence 3 : lecture
    hl(m("lecture"), seg(t, a2 + 0.2, a2 + 0.8), C.amber);
    cap(S.cHov, FX + 330, outCubic(seg(t, a2 + 0.4, a2 + 1.0)), C.amber);
    cap(S.cClick, FX + 860, outCubic(seg(t, a2 + 2.6, a2 + 3.2)), C.amber);
  }
}

/* ------------------------------ 02 · la feuille de ravito ------------------------------ */
function sJour(t, d, cues) {
  head(S.k2, S.h2, t);
  const a0 = at(cues, 0, 0.6), a1 = at(cues, 1, 5.3);
  const k0 = outCubic(seg(t, 0.3, 0.9));
  const n = "rb-aujourdhui";
  const z = inOut(seg(t, 0.5, a0 + 1.5));
  const crop = lerpRect(cropTo(n, [250, 52, 1190, 600], asp, 0), cropTo(n, union(n, ["verdict", "remplacement", "plaque"]), asp, 20), z);
  const m = shot(n, FX, FY, FW, FH, { crop, alpha: k0, url: URL });
  const v = m("verdict"), c = m("remplacement"), w = m("plaque");
  if (v) { hl(v, seg(t, a0 + 1.4, a0 + 2.0) * (1 - seg(t, a1 - 0.2, a1 + 0.3)), AMBER); cap(S.cV, v[0] + v[2] / 2, outCubic(seg(t, a0 + 1.6, a0 + 2.2)) * (1 - seg(t, a1 - 0.2, a1 + 0.3)), AMBER); }
  if (c) { hl(c, seg(t, a1 + 0.4, a1 + 1.0) * (1 - seg(t, a1 + 3.6, a1 + 4.1))); cap(S.cS, c[0] + c[2] / 2, outCubic(seg(t, a1 + 0.6, a1 + 1.2)) * (1 - seg(t, a1 + 3.6, a1 + 4.1))); }
  if (w) { hl(w, seg(t, a1 + 3.8, a1 + 4.4), C.teal); cap(S.cW, w[0] + w[2] / 2 + 150, outCubic(seg(t, a1 + 4.0, a1 + 4.6)), C.teal); }
}

/* ------------------------------ 03 · le bilan en lignes de barrière ------------------------------ */
function sBilan(t, d, cues) {
  head(S.k3, S.h3, t);
  const a0 = at(cues, 0, 0.6), a1 = at(cues, 1, 5.4);
  const k0 = outCubic(seg(t, 0.3, 0.9));
  const n = "rb-bilan", b = shotBox(n, "bilan");
  const crop = [b[0] - 12, b[1] - 12, b[2] + 24, (b[2] + 24) / asp];
  const m = shot(n, FX, FY, FW, FH, { crop, alpha: k0, url: URL + "#/" });
  const r0 = m([b[0], shotBox(n, "hrv")[1], b[2], shotBox(n, "sommeil")[1] + shotBox(n, "sommeil")[3] - shotBox(n, "hrv")[1]]);
  const r = r0;
  if (!r) return;
  hl(r, seg(t, a0 + 0.6, a0 + 1.2) * (1 - seg(t, a1 - 0.2, a1 + 0.3)));
  const kc = outCubic(seg(t, a0 + 1.4, a0 + 2.0));
  const col = (f) => r[0] + r[2] * f;
  const out = 1 - seg(t, a1 - 0.2, a1 + 0.3);
  cap(S.cVal, col(0.30), kc * out); cap(S.cRef, col(0.47), outCubic(seg(t, a0 + 2.0, a0 + 2.6)) * out);
  const e = m("etat");
  if (e) hl(e, seg(t, a1 + 0.3, a1 + 0.9), AMBER);
  const ks = outCubic(seg(t, a1 + 0.6, a1 + 1.2));
  cap(S.stA, FX + 330, ks, AMBER); cap(S.stB, FX + 530, outCubic(seg(t, a1 + 1.2, a1 + 1.8)), CORAL);
  cap(S.cSt, FX + 790, outCubic(seg(t, a1 + 1.8, a1 + 2.4)), C.accent);
  cap(S.cNo, FX + FW - 130, outCubic(seg(t, a1 + 2.8, a1 + 3.4)), C.teal, CY + 44);
}

/* ------------------------------ 04 · la semaine ------------------------------ */
function sSemaine(t, d, cues) {
  head(S.k4, S.h4, t);
  const a0 = at(cues, 0, 0.6), a1 = at(cues, 1, 9);
  const k0 = outCubic(seg(t, 0.3, 0.9));
  const n = "rb-semaine-passee", f = shotBox(n, "feuille");
  const crop = cropTo(n, [f[0], f[1], f[2], 190], asp, 14);
  const m = shot(n, FX, FY, FW, FH, { crop, alpha: k0, url: URL + "#/semaine?debut=2026-09-21" });
  const row = m("ligne"), act = m("reel"), dur = m("duree"), st = m("statut");
  const off = 1 - seg(t, a1 - 0.2, a1 + 0.3);
  if (row) { hl(row, seg(t, a0 + 0.6, a0 + 1.2) * (1 - seg(t, a0 + 2.6, a0 + 3.1)), C.accent); cap(S.cL, row[0] + 330, outCubic(seg(t, a0 + 0.8, a0 + 1.4)) * (1 - seg(t, a0 + 2.6, a0 + 3.1))); }
  if (act) { hl(act, seg(t, a0 + 2.8, a0 + 3.4) * (1 - seg(t, a0 + 5.2, a0 + 5.7)), C.teal); cap(S.cAct, act[0] + act[2] / 2, outCubic(seg(t, a0 + 3.0, a0 + 3.6)) * (1 - seg(t, a0 + 5.2, a0 + 5.7)), C.teal); }
  if (dur) { hl(dur, seg(t, a0 + 5.4, a0 + 6.0) * off, AMBER); cap(S.cDur, dur[0] + dur[2] / 2, outCubic(seg(t, a0 + 5.6, a0 + 6.2)) * off, AMBER); }
  if (st) hl(st, seg(t, a1 + 0.3, a1 + 0.9), C.accent);
  const cols = [C.accent, AMBER, AMBER, CORAL];
  S.stats.forEach((s, i) => cap(s, FX + 250 + i * 210, outCubic(seg(t, a1 + 0.5 + i * 0.7, a1 + 1.1 + i * 0.7)), cols[i]));
  text(S.statsN, FX + FW / 2, CY + 52, { size: 13, font: MONO, color: C.faint, align: "center", alpha: seg(t, a1 + 3.6, a1 + 4.2) });
}

/* ------------------------------ 05 · se déplacer ------------------------------ */
function sNav(t, d, cues) {
  head(S.k5, S.h5, t);
  const a0 = at(cues, 0, 0.6), a1 = at(cues, 1, 3.9);
  const PH = 379, PW = 175, PY = FY - 2;
  const k0 = outCubic(seg(t, 0.3, 0.9)), kp = outCubic(seg(t, a1 - 0.2, a1 + 0.5)), ks = outCubic(seg(t, a1 + 2.4, a1 + 3.1));
  const pan = inOut(seg(t, a0 + 0.8, a0 + 3.2));
  shot("rb-rail", FX, PY, 250, PH, { crop: [0, lerp(52, 52 + 848 - 376, pan), 248, 376], chrome: false, alpha: k0 });
  hl([FX, PY, 250, PH], seg(t, a0 + 0.5, a0 + 1.1) * (1 - seg(t, a1 - 0.2, a1 + 0.3)));
  shot("mobile-rb-barre", FX + 290, PY, PW, PH, { chrome: false, alpha: kp });
  shot("mobile-rb-sections", FX + 290 + PW + 30, PY, PW, PH, { chrome: false, alpha: ks });
  const bar = shotBox("mobile-rb-barre", "barre");
  if (bar) { const sc = PW / 390; hl([FX + 290, PY + bar[1] * sc, PW, bar[3] * sc], seg(t, a1 + 0.8, a1 + 1.4) * (1 - seg(t, a1 + 2.6, a1 + 3.1)), C.teal); }
  // légendes à droite
  const x0 = 80 + 290 + 2 * PW + 90, w0 = FX + FW - x0;
  const kr = outCubic(seg(t, a0 + 0.6, a0 + 1.2));
  panel(x0, FY, w0, 176, { r: 14, alpha: kr, stroke: C.accent });
  text(S.rail.toUpperCase(), x0 + 20, FY + 32, { size: 13, weight: 700, font: MONO, color: C.accent, alpha: kr, spacing: "1px" });
  S.railG.forEach((s, i) => text(s, x0 + 20, FY + 62 + i * 21, { size: 15, color: C.soft, alpha: kr * outCubic(seg(t, a0 + 1.0 + i * 0.3, a0 + 1.5 + i * 0.3)) }));
  const kb = outCubic(seg(t, a1 + 0.2, a1 + 0.8));
  panel(x0, FY + 190, w0, 189, { r: 14, alpha: kb, stroke: C.teal });
  text(S.bar.toUpperCase(), x0 + 20, FY + 222, { size: 13, weight: 700, font: MONO, color: C.teal, alpha: kb, spacing: "1px" });
  S.barI.forEach((s, i) => text(s, x0 + 20, FY + 252 + i * 21, { size: 15, color: C.soft, alpha: kb * outCubic(seg(t, a1 + 0.6 + i * 0.25, a1 + 1.1 + i * 0.25)) }));
  cap(S.sheet, FX + 290 + PW + 30 + PW / 2, outCubic(seg(t, a1 + 3.0, a1 + 3.6)), C.teal, CY + 6);
}

/* ------------------------------ 06 · une application ------------------------------ */
function sPwa(t, d, cues) {
  head(S.k6, S.h6, t);
  const a0 = at(cues, 0, 0.6), a1 = at(cues, 1, 5.3);
  const PX = 140, PW = 230, PH = 400, PY = FY - 6;
  const kp = outCubic(seg(t, 0.3, 0.9));
  phone(PX, PY, PW, PH, (x, y, w, h) => {
    ctx.fillStyle = "#13201a"; ctx.fillRect(x, y, w, h);
    const R = rng(7);
    for (let r = 0; r < 3; r++) for (let c = 0; c < 3; c++) {
      const ix = x + 28 + c * 62, iy = y + 70 + r * 78, isApp = r === 1 && c === 1;
      if (isApp) continue;
      panel(ix, iy, 46, 46, { r: 11, fill: `hsl(${150 + R() * 60}, 18%, ${22 + R() * 8}%)`, stroke: false, shadow: false, alpha: 0.9 });
    }
    // icône de l'application, qui « tombe » à la phrase 1
    const ka = outBack(seg(t, a0 + 0.6, a0 + 1.4)), ix = x + 28 + 62, iy = y + 70 + 78;
    if (ka > 0) {
      ctx.save(); ctx.translate(ix + 23, iy + 23); ctx.scale(clamp(ka, 0, 1.15), clamp(ka, 0, 1.15));
      panel(-23, -23, 46, 46, { r: 11, fill: C.pine, stroke: C.accent, lw: 2, shadow: false });
      logo(0, 2, 0.32, 1);
      ctx.restore();
      text(S.appName, ix + 23, iy + 64, { size: 9.5, weight: 600, color: C.ink, align: "center", alpha: clamp(ka) });
    }
    text(S.home, x + w / 2, y + h - 22, { size: 11, font: MONO, color: C.faint, align: "center" });
  }, { alpha: kp });
  // hors ligne
  const ko = outCubic(seg(t, a1 - 0.2, a1 + 0.5));
  pill("✕ " + S.offline, PX + PW / 2, PY + PH + 30, { size: 14, alpha: ko, color: C.ink, fill: "rgba(15,42,31,0.92)", stroke: AMBER, align: "center" });
  const X0 = 470, W0 = FX + FW - X0;
  const ks = outCubic(seg(t, a1 + 0.4, a1 + 1.0));
  panel(X0, FY, W0, 170, { r: 16, alpha: ks, stroke: C.accent, fill: "rgba(163,230,53,0.06)", lw: 2 });
  text(S.shell.toUpperCase(), X0 + 28, FY + 40, { size: 13, weight: 700, font: MONO, color: C.accent, alpha: ks, spacing: "2px" });
  text(S.shellI, X0 + 28, FY + 82, { size: 20, weight: 600, font: SORA, alpha: ks });
  check(X0 + 36, FY + 128, 22, C.accent, seg(t, a1 + 1.0, a1 + 1.6), 1);
  text(S.shellN, X0 + 66, FY + 136, { size: 18, color: C.soft, alpha: ks });
  const kd = outCubic(seg(t, a1 + 2.4, a1 + 3.0));
  panel(X0, FY + 196, W0, 170, { r: 16, alpha: kd, stroke: CORAL, fill: "rgba(240,122,95,0.06)", lw: 2 });
  text(S.data.toUpperCase(), X0 + 28, FY + 236, { size: 13, weight: 700, font: MONO, color: CORAL, alpha: kd, spacing: "2px" });
  text(S.dataI, X0 + 28, FY + 278, { size: 20, weight: 600, font: SORA, alpha: kd });
  const kx = seg(t, a1 + 3.0, a1 + 3.6);
  if (kx > 0) { line([[X0 + 26, FY + 316], [X0 + 46, FY + 336]], CORAL, 3, clamp(kx * 2)); line([[X0 + 46, FY + 316], [X0 + 26, FY + 336]], CORAL, 3, clamp(kx * 2 - 0.2)); }
  text(S.dataN, X0 + 66, FY + 334, { size: 18, color: C.soft, alpha: kd });
}

/* ------------------------------ 07 · chez vous, l'ancien design ------------------------------ */
function sPrive(t, d, cues) {
  head(S.k7, S.h7, t);
  const a0 = at(cues, 0, 0.6), a1 = at(cues, 1, 5.5);
  const k0 = outCubic(seg(t, 0.3, 0.9));
  panel(FX, FY, 620, 300, { r: 18, alpha: k0, stroke: C.accent, fill: "rgba(163,230,53,0.04)", lw: 2 });
  text(S.machine.toUpperCase(), FX + 24, FY + 38, { size: 13, weight: 700, font: MONO, color: C.accent, alpha: k0, spacing: "1px" });
  const kd = outCubic(seg(t, a0 + 0.3, a0 + 0.9));
  panel(FX + 24, FY + 62, 280, 70, { r: 12, alpha: kd });
  text(S.dash, FX + 44, FY + 105, { size: 22, weight: 800, font: SORA, alpha: kd });
  const kf = outCubic(seg(t, a0 + 1.2, a0 + 1.8));
  panel(FX + 24, FY + 156, 572, 112, { r: 12, alpha: kf, stroke: C.teal });
  text("Aa", FX + 52, FY + 220, { size: 44, weight: 800, font: SORA, color: C.teal, alpha: kf });
  text(S.fonts, FX + 130, FY + 202, { size: 16, font: MONO, color: C.ink, alpha: kf });
  text(S.ofl, FX + 130, FY + 232, { size: 14, font: MONO, color: C.faint, alpha: kf });
  arrow(FX + 304, FY + 97, FX + 304, FY + 156, seg(t, a0 + 1.4, a0 + 2.0), C.teal);
  // dehors : Google Fonts barré
  const kg = outCubic(seg(t, a0 + 2.6, a0 + 3.2));
  panel(FX + 700, FY + 62, 420, 70, { r: 12, alpha: kg, stroke: C.line });
  text(S.gf, FX + 730, FY + 105, { size: 22, weight: 700, font: SORA, color: C.faint, alpha: kg });
  arrow(FX + 304 + 8, FY + 90, FX + 692, FY + 90, seg(t, a0 + 3.0, a0 + 3.8), C.faint, 0.6);
  const kx = seg(t, a0 + 3.6, a0 + 4.1);
  if (kx > 0) { line([[FX + 640, FY + 70], [FX + 666, FY + 110]], CORAL, 4, clamp(kx * 2)); line([[FX + 666, FY + 70], [FX + 640, FY + 110]], CORAL, 4, clamp(kx * 2 - 0.2)); }
  pill(S.none, FX + 910, FY + 166, { size: 14, alpha: outCubic(seg(t, a0 + 3.8, a0 + 4.4)), color: C.ink, fill: "rgba(15,42,31,0.92)", stroke: C.accent, align: "center" });
  para(S.tiles, FX + 700, FY + 224, 420, { size: 13, color: C.faint, font: MONO, alpha: outCubic(seg(t, a0 + 4.4, a0 + 5.0)) });
  // sentence 2 : l'ancien design
  const k2 = outCubic(seg(t, a1 + 0.3, a1 + 0.9));
  panel(FX, FY + 328, FW, 62, { r: 14, alpha: k2, fill: "#0a120e", stroke: "#33463b" });
  text(S.oldUrl, FX + 28, FY + 366, { size: 20, weight: 600, font: MONO, color: C.amber, alpha: k2 });
  text(S.oldNote, FX + FW - 28, FY + 365, { size: 14, color: C.soft, align: "right", alpha: outCubic(seg(t, a1 + 0.9, a1 + 1.5)) });
  // frise 1.4 → 1.5
  const kt = outCubic(seg(t, a1 + 2.0, a1 + 2.6)), ke = seg(t, a1 + 2.2, a1 + 3.8);
  const y = FY + 432, x0 = FX + 40, x1 = FX + FW - 40;
  line([[x0, y], [lerp(x0, x1, ke), y]], C.accent, 3, kt);
  dot(x0, y, 7, C.accent, kt); dot(x1, y, 7, ke >= 1 ? C.red : C.faint, kt);
  text(S.t14, x0, y + 30, { size: 15, weight: 600, font: MONO, color: C.accent, alpha: kt });
  text(S.t15, x1, y + 30, { size: 15, weight: 600, font: MONO, color: C.red, align: "right", alpha: kt });
}

ARC.episode({
  n: 24, slug: "roadbook",
  strings: STR,
  shotsBase: "../shots-roadbook/",
  shots: ["rb-profil", "rb-aujourdhui", "rb-bilan", "rb-semaine-passee", "rb-rail", "mobile-rb-barre", "mobile-rb-sections"],
  scenes: { profil: sProfil, jour: sJour, bilan: sBilan, semaine: sSemaine, nav: sNav, pwa: sPwa, prive: sPrive },
});
})();
