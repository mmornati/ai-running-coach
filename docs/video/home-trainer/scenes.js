/* Le Sentier · étape 19 — « Le home trainer, à votre mesure » : skill `mywhoosh-route`, relation
 * puissance ↔ FC (`arc_index.py power-hr`, scripts/arc_power.py), catalogue MyWhoosh, modèle de temps,
 * nom du parcours dans la séance Garmin, calendrier MyWhoosh proposé, carte « Home trainer » (vue Matériel).
 * Les temps de parcours montrés sont ceux de la vraie commande `mywhoosh_route.py suggest`, calculés pour
 * la calibration fictive de Camille (58 kg, vélo 8,5 kg, Z2 124-138 bpm, cible 141 W) ; les noms, distances
 * et dénivelés des parcours sont ceux du catalogue public MyWhoosh. Tout le reste est dessiné ici.
 * Moteur : ../engine/engine.js (helpers globaux). Découpage et narration : script.json.
 * Chaque scène reçoit (t, d, cues) : temps local, durée, répliques [{s, e, text}] —
 * at(cues, i, repli) cale une animation sur la voix, quelle que soit la langue.
 * Athlète et chiffres fictifs (bible de la série : Camille, mardi 29 septembre 2026). */
"use strict";
(() => {
const STR = {
  fr: {
    k1: "01 · VOS WATTS", h1: "Combien de watts, en zone 2 ?",
    axX: "FC (bpm)", axY: "puissance (W)", z2: "zone 2 · 124–138 bpm",
    winN: "212 fenêtres de 5 min · 9 séances home trainer",
    resT: "Puissance en zone 2", resV: "≈ 141 W", resB: "130–153 W · ±14 W", resN: "estimation, pas un test",
    ftp: "FTP recalculée sur une récup ? ignorée",
    k2: "02 · LES PARCOURS", h2: "116 parcours, récupérés une fois.",
    cols: ["parcours", "monde", "km", "D+", "difficulté", ""],
    loop: "boucle", p2p: "point à point",
    cmd: "mywhoosh_route.py fetch", mail: "E-mail MyWhoosh : camille@exemple.org", pwd: "Mot de passe MyWhoosh : ",
    ok: "OK 116 parcours", never: "mot de passe : jamais dans le chat", token: "jeton gardé en mode 600",
    k3: "03 · LE BON PARCOURS", h3: "70 minutes, à sa puissance.",
    inputs: ["≈ 135 W de moyenne", "58 kg + vélo 8,5 kg", "endurance : difficulté ≤ 2"],
    win: "la séance", out: { short: "trop court", long: "trop long", steep: "trop raide" },
    pick: "Limmat Loop × 2", pickV: "1 h 10", pickB: "1 h 03 – 1 h 17 · ±10 %",
    k4: "04 · SUR LA MONTRE", h4: "La fréquence cardiaque commande.",
    wName: "HT Z2 70min -", wName2: "Limmat Loop x2", wStep: "Z2", wHr: "124–138", wP: "≈ 141 W · repère",
    weekT: "planning/Semaine_2026-09-28.md", over: "FC au-dessus de 138", ease: "→ baisser les watts",
    k5: "05 · LE CALENDRIER", h5: "Proposé, jamais imposé.",
    ask: "Inscrire au calendrier MyWhoosh ?",
    rows: [["Parcours", "Limmat Loop · Switzerland"], ["Quand", "samedi 3 oct. · 10:00"], ["Durée", "70 min"]],
    dry: "simulation d'abord · rien n'est écrit", yes: "oui", no: "non", done: "inscrit, puis relu pour vérifier",
    conf: "mywhoosh_calendar = \"ask\"", headless: "jamais en mode automatique",
    k6: "06 · LE TABLEAU DE BORD", h6: "La carte « Home trainer ».",
    view: "Matériel", card: "Home trainer", eq: "Home trainer connecté · vélo 8,5 kg · MyWhoosh",
    zT: "Puissance par zone FC", extra: "extrapolée",
    recT: "Dernières séances avec puissance",
    rec: [["29 sept.", "Home trainer", "61 min", "138 W"], ["24 sept.", "Home trainer", "45 min", "126 W"], ["19 sept.", "Home trainer", "70 min", "141 W"]],
    note: "estimation · la FC reste la consigne",
    cfgOff: "platform = \"off\"", cfgOn: "platform = \"mywhoosh\"", optin: "désactivé par défaut",
  },
  en: {
    k1: "01 · YOUR WATTS", h1: "How many watts is zone 2?",
    axX: "HR (bpm)", axY: "power (W)", z2: "zone 2 · 124–138 bpm",
    winN: "212 five-minute windows · 9 trainer rides",
    resT: "Zone 2 power", resV: "≈ 141 W", resB: "130–153 W · ±14 W", resN: "an estimate, not a test",
    ftp: "FTP recomputed on a recovery ride? ignored",
    k2: "02 · THE ROUTES", h2: "116 routes, fetched once.",
    cols: ["route", "world", "km", "gain", "difficulty", ""],
    loop: "loop", p2p: "point to point",
    cmd: "mywhoosh_route.py fetch", mail: "E-mail MyWhoosh : camille@example.org", pwd: "Mot de passe MyWhoosh : ",
    ok: "OK 116 parcours", never: "password: never in the chat", token: "token kept with mode 600",
    k3: "03 · THE RIGHT ROUTE", h3: "70 minutes, at her power.",
    inputs: ["≈ 135 W on average", "58 kg + 8.5 kg bike", "endurance: difficulty ≤ 2"],
    win: "the session", out: { short: "too short", long: "too long", steep: "too steep" },
    pick: "Limmat Loop × 2", pickV: "1 h 10", pickB: "1 h 03 – 1 h 17 · ±10 %",
    k4: "04 · ON THE WATCH", h4: "Heart rate is in charge.",
    wName: "HT Z2 70min -", wName2: "Limmat Loop x2", wStep: "Z2", wHr: "124–138", wP: "≈ 141 W · cue",
    weekT: "planning/Semaine_2026-09-28.md", over: "HR above 138", ease: "→ ease off the watts",
    k5: "05 · THE CALENDAR", h5: "Offered, never imposed.",
    ask: "Add it to the MyWhoosh calendar?",
    rows: [["Route", "Limmat Loop · Switzerland"], ["When", "Saturday Oct 3 · 10:00"], ["Duration", "70 min"]],
    dry: "dry run first · nothing is written", yes: "yes", no: "no", done: "added, then read back to check",
    conf: "mywhoosh_calendar = \"ask\"", headless: "never in automatic mode",
    k6: "06 · THE DASHBOARD", h6: "The “Home trainer” card.",
    view: "Gear", card: "Home trainer", eq: "Smart trainer · 8.5 kg bike · MyWhoosh",
    zT: "Power per HR zone", extra: "extrapolated",
    recT: "Latest rides with power",
    rec: [["Sep 29", "Home trainer", "61 min", "138 W"], ["Sep 24", "Home trainer", "45 min", "126 W"], ["Sep 19", "Home trainer", "70 min", "141 W"]],
    note: "an estimate · heart rate stays the target",
    cfgOff: "platform = \"off\"", cfgOn: "platform = \"mywhoosh\"", optin: "off by default",
  },
};

/* Données fictives (Camille) — calibration P = 1,65 · FC − 75 W. */
const FIT = { a: -75, b: 1.65 };
const pw = hr => FIT.a + FIT.b * hr;
const ZONES = [[110, 124, 107, 130, false], [124, 138, 130, 153, false], [138, 152, 153, 176, false],
               [152, 166, 176, 199, true], [166, 180, 199, 222, true]];
/* Catalogue : extrait réel (km, D+, difficulté MyWhoosh, boucle). */
const ROUTES = [
  ["Limmat Loop", "Switzerland", 17.6, 37, 1, true], ["Al Qudra", "Arabia", 12.3, 24, 1, true],
  ["Bruges", "Belgium", 10.6, 1, 1, true], ["Cobbled Classic", "France", 17.4, 116, 2, true],
  ["The Muur", "Belgium", 15.1, 177, 3, true], ["Four Cities", "Arabia", 42.3, 311, 3, true],
  ["Jabel Hafeet", "Arabia", 16.5, 735, 4, false], ["Yas Marina Circuit", "Arabia", 5.2, 18, 1, true],
];
/* Temps prévus (min) pour la séance de 70 min à ≈ 135 W, sortie réelle de `suggest`. */
const BARS = [
  ["Yas Marina Circuit × 3", 31.4, "short"], ["Bruges × 3", 63.0, null], ["Limmat Loop × 2", 70.3, "pick"],
  ["Cobbled Classic × 2", 72.6, null], ["Al Qudra × 3", 73.7, null], ["The Muur × 2", 68.9, "steep"],
  ["Jabel Hafeet", 72.6, "steep"], ["Four Cities", 89.1, "long"],
];

/* ------------------------------- dessins locaux ------------------------------- */
function head(k, h, t) { kicker(k, seg(t, 0, 0.4)); headline(h, seg(t, 0.1, 0.7)); fictTag(seg(t, 0.3, 0.8)); }
function cross(x, y, s, col, alpha = 1) {
  line([[x - s, y - s], [x + s, y + s]], col, 3, alpha); line([[x + s, y - s], [x - s, y + s]], col, 3, alpha);
}
function keyBtn(label, x, y, w, h, on, o = {}) {
  panel(x, y, w, h, { r: 9, fill: on ? C.accent : "#1d3328", stroke: on ? C.accent : "#33463b", alpha: o.alpha ?? 1 });
  text(label, x + w / 2, y + h / 2 + (o.size ?? 13) * 0.36, { size: o.size ?? 13, weight: 600, align: "center", color: on ? C.deep : C.ink, alpha: o.alpha ?? 1 });
}
function diffDots(n, x, y, alpha) {
  for (let i = 0; i < 5; i++) dot(x + i * 13, y, 4.5, i < n ? (n <= 2 ? C.accent : n === 3 ? C.amber : C.red) : "#2b3d33", alpha);
}

/* ------------------------------ 01 · vos watts ------------------------------ */
function sWatts(t, d, cues) {
  head(S.k1, S.h1, t);
  const a0 = at(cues, 0, 0.6), a1 = at(cues, 1, 5.5);
  // repère
  const gx = 80, gy = 190, gw = 700, gh = 400, k0 = outCubic(seg(t, a0, a0 + 0.6));
  const X = hr => gx + (hr - 95) / (165 - 95) * gw, Y = p => gy + gh - (p - 60) / (220 - 60) * gh;
  panel(gx - 20, gy - 20, gw + 40, gh + 60, { r: 18, alpha: k0 });
  line([[gx, gy + gh], [gx + gw, gy + gh]], C.line, 2, k0);
  line([[gx, gy], [gx, gy + gh]], C.line, 2, k0);
  [100, 120, 140, 160].forEach(v => text(String(v), X(v), gy + gh + 24, { size: 12, font: MONO, color: C.faint, align: "center", alpha: k0 }));
  [100, 150, 200].forEach(v => text(String(v), gx - 10, Y(v) + 4, { size: 12, font: MONO, color: C.faint, align: "right", alpha: k0 }));
  text(S.axX, gx + gw, gy + gh + 24, { size: 12, font: MONO, color: C.soft, align: "right", alpha: k0 });
  text(S.axY, gx + 10, gy + 18, { size: 12, font: MONO, color: C.soft, alpha: k0 });
  // fenêtres de 5 min : nuage déterministe autour de la droite
  const R = rng(hash("ht-watts"));
  const pts = Array.from({ length: 64 }, () => { const hr = 100 + R() * 56; return [hr, pw(hr) + (R() + R() + R() - 1.5) * 22]; });
  pts.forEach(([hr, p], i) => {
    const kk = outCubic(seg(t, a1 - 0.6 + i * 0.03, a1 - 0.2 + i * 0.03));
    dot(X(hr), Y(p), 4.5, C.teal, kk * 0.75);
  });
  text(S.winN, gx, gy + gh + 52, { size: 13, font: MONO, color: C.faint, alpha: seg(t, a1 + 0.8, a1 + 1.3) });
  // droite
  const kl = outCubic(seg(t, a1 + 1.6, a1 + 2.6));
  line(partial([[X(98), Y(pw(98))], [X(160), Y(pw(160))]], kl), C.accent, 3, 1);
  // bande zone 2
  const kz = outCubic(seg(t, a1 + 2.8, a1 + 3.5));
  if (kz > 0) {
    ctx.save(); ctx.globalAlpha *= kz * 0.18; ctx.fillStyle = C.accent; ctx.fillRect(X(124), gy, X(138) - X(124), gh); ctx.restore();
    line([[X(124), Y(pw(124))], [gx, Y(pw(124))]], C.accent, 1.5, kz, [5, 5]);
    line([[X(138), Y(pw(138))], [gx, Y(pw(138))]], C.accent, 1.5, kz, [5, 5]);
    text(S.z2, (X(124) + X(138)) / 2, gy + 22, { size: 13, weight: 600, font: MONO, color: C.accent, align: "center", alpha: kz });
  }
  // résultat
  const kr = outBack(seg(t, a1 + 4.0, a1 + 4.7));
  if (kr > 0) {
    const kk = clamp(kr);
    panel(860, 190, 340, 250, { r: 18, fill: C.panel2, stroke: C.accent, lw: 2, alpha: kk });
    text(S.resT.toUpperCase(), 886, 226, { size: 12, weight: 600, font: MONO, color: C.accent, alpha: kk, spacing: "2px" });
    text(S.resV, 886, 300, { size: 58, weight: 800, font: SORA, alpha: kk });
    text(S.resB, 886, 340, { size: 16, font: MONO, color: C.soft, alpha: kk });
    text(S.resN, 886, 400, { size: 15, color: C.amber, alpha: seg(t, a1 + 5.2, a1 + 5.8) });
  }
  const kf = outCubic(seg(t, a1 + 6.0, a1 + 6.6));
  if (kf > 0) {
    panel(860, 466, 340, 64, { r: 14, alpha: kf });
    cross(888, 498, 7, C.red, kf);
    para(S.ftp, 910, 494, 270, { size: 14, color: C.soft, alpha: kf, lh: 18 });
  }
}

/* ------------------------------ 02 · le catalogue ------------------------------ */
function sCatalogue(t, d, cues) {
  head(S.k2, S.h2, t);
  const a0 = at(cues, 0, 0.6), a1 = at(cues, 1, 6);
  const x0 = 80, y0 = 176, cx = [x0 + 20, x0 + 270, x0 + 440, x0 + 520, x0 + 600, x0 + 700];
  const kh = seg(t, a0, a0 + 0.4);
  panel(x0, y0, 860, 344, { r: 16, alpha: kh });
  S.cols.forEach((c, i) => text(c.toUpperCase(), cx[i], y0 + 32, { size: 11, weight: 600, font: MONO, color: C.faint, alpha: kh, align: i >= 2 && i <= 3 ? "right" : "left", spacing: "1px" }));
  ROUTES.forEach(([name, world, km, gain, diff, loop], i) => {
    const kk = outCubic(seg(t, a0 + 0.4 + i * 0.32, a0 + 0.8 + i * 0.32)), y = y0 + 68 + i * 34 + (1 - kk) * 10;
    if (kk <= 0) return;
    if (i) line([[x0 + 16, y - 22], [x0 + 844, y - 22]], C.line, 1, kk * 0.6);
    text(name, cx[0], y, { size: 15, weight: 600, alpha: kk });
    text(world, cx[1], y, { size: 14, color: C.soft, alpha: kk });
    text(km.toFixed(1).replace(".", LANG === "fr" ? "," : "."), cx[2] + 34, y, { size: 14, font: MONO, align: "right", alpha: kk });
    text(`${gain} m`, cx[3] + 40, y, { size: 14, font: MONO, align: "right", alpha: kk });
    diffDots(diff, cx[4], y - 5, kk);
    text(loop ? `↻ ${S.loop}` : `→ ${S.p2p}`, cx[5], y, { size: 13, font: MONO, color: loop ? C.teal : C.faint, alpha: kk });
  });
  // compteur
  const kc = seg(t, a0 + 0.4, a0 + 3.2);
  text(String(Math.round(8 + 108 * outCubic(kc))), 1080, 270, { size: 86, weight: 800, font: SORA, color: C.accent, align: "center", alpha: kh });
  text("MyWhoosh", 1080, 304, { size: 16, font: MONO, color: C.soft, align: "center", alpha: kh });
  // terminal : le mot de passe ne passe que par le terminal
  const T = a1 - 0.2, kt = outCubic(seg(t, T, T + 0.5));
  if (kt > 0) {
    terminal(80, 530, 860, 172, t, [
      { p: "$ ", s: S.cmd, a: T + 0.2, b: T + 1.0 },
      { s: S.mail, a: T + 1.2, b: T + 1.7, c: C.soft },
      { s: S.pwd + "••••••••••", a: T + 1.9, b: T + 2.5, c: C.soft },
      { s: S.ok, a: T + 2.8, c: C.accent, w: 600 },
    ], { alpha: kt, size: 14, lh: 24, title: "terminal" });
    const kn = outBack(seg(t, T + 2.2, T + 2.8));
    if (kn > 0) {
      pill(S.never, 1080, 560, { size: 14, align: "center", alpha: clamp(kn), color: C.amber, fill: "rgba(240,180,60,0.08)", stroke: "rgba(240,180,60,0.45)" });
      pill(S.token, 1080, 610, { size: 13, align: "center", alpha: seg(t, T + 3.0, T + 3.5), color: C.teal, fill: "rgba(95,184,160,0.08)", stroke: "rgba(95,184,160,0.4)" });
    }
  }
}

/* ------------------------------ 03 · le bon parcours ------------------------------ */
function sFit(t, d, cues) {
  head(S.k3, S.h3, t);
  const a0 = at(cues, 0, 0.6), a1 = at(cues, 1, 5.5);
  S.inputs.forEach((s, i) => pill(s, 80 + [0, 220, 450][i], 190, { size: 13, alpha: seg(t, a0 + 0.3 + i * 0.4, a0 + 0.8 + i * 0.4), color: C.ink, fill: C.panel2, stroke: C.line }));
  // axe du temps
  const ax = 330, aw = 760, y0 = 236, rh = 40;
  const X = m => ax + m / 110 * aw;
  const kw = outCubic(seg(t, a0 + 1.2, a0 + 1.8));
  ctx.save(); ctx.globalAlpha *= kw * 0.12; ctx.fillStyle = C.accent; ctx.fillRect(X(59.5), y0 - 6, X(75) - X(59.5), BARS.length * rh + 12); ctx.restore();
  line([[X(70), y0 - 10], [X(70), y0 + BARS.length * rh + 6]], C.accent, 2, kw, [6, 6]);
  text(`${S.win} · 70 min`, X(70), y0 - 18, { size: 12, weight: 600, font: MONO, color: C.accent, align: "center", alpha: kw });
  [0, 30, 60, 90].forEach(m => text(`${m}'`, X(m), y0 + BARS.length * rh + 26, { size: 12, font: MONO, color: C.faint, align: "center", alpha: kw }));
  BARS.forEach(([name, mins, tag], i) => {
    const y = y0 + i * rh, kb = outCubic(seg(t, a0 + 1.6 + i * 0.25, a0 + 2.4 + i * 0.25));
    if (kb <= 0) return;
    const rejected = tag && tag !== "pick", out = rejected ? seg(t, a1 + 0.3 + (tag === "steep" ? 1.2 : 0), a1 + 0.8 + (tag === "steep" ? 1.2 : 0)) : 0;
    const pick = tag === "pick" && t > a1 + 2.6;
    const dim = 1 - 0.65 * out - (t > a1 + 2.6 && !pick && !rejected ? 0.45 : 0);
    text(name, ax - 16, y + 24, { size: 14, weight: pick ? 700 : 500, color: pick ? C.accent : C.ink, align: "right", alpha: kb * dim });
    const w = (X(mins) - ax) * kb;
    // bande ±10 %
    ctx.save(); ctx.globalAlpha *= kb * dim * 0.25; ctx.fillStyle = pick ? C.accent : C.soft; ctx.fillRect(X(mins * 0.9), y + 12, X(mins * 1.1) - X(mins * 0.9), 16); ctx.restore();
    panel(ax, y + 14, Math.max(w, 2), 12, { r: 6, fill: pick ? C.accent : rejected && out > 0 ? C.red : C.teal, stroke: false, alpha: kb * dim });
    text(`${Math.round(mins)}'`, ax + w + 10 + (X(mins * 1.1) - X(mins)), y + 25, { size: 12, font: MONO, color: C.faint, alpha: kb * dim });
    if (out > 0) pill(S.out[tag], 1200, y + 20, { size: 12, align: "right", alpha: out, color: C.red, fill: "rgba(240,122,95,0.08)", stroke: "rgba(240,122,95,0.45)" });
    if (pick) highlight(ax - 210, y + 2, 210 + X(mins * 1.1) - ax + 40, rh - 4, seg(t, a1 + 2.6, a1 + 3.2));
  });
  // le choix
  const kp = outBack(seg(t, a1 + 3.6, a1 + 4.3));
  if (kp > 0) {
    const kk = clamp(kp);
    panel(80, 584, 1120, 88, { r: 16, fill: "rgba(163,230,53,0.07)", stroke: C.accent, lw: 2, alpha: kk });
    text(S.pick, 108, 638, { size: 30, weight: 800, font: SORA, color: C.accent, alpha: kk });
    text(S.pickV, 560, 638, { size: 30, weight: 800, font: SORA, alpha: kk });
    text(S.pickB, 700, 636, { size: 16, font: MONO, color: C.soft, alpha: kk });
  }
}

/* ------------------------------ 04 · sur la montre ------------------------------ */
function sWatch(t, d, cues) {
  head(S.k4, S.h4, t);
  const a0 = at(cues, 0, 0.6), a1 = at(cues, 1, 5);
  // montre
  const cx = 300, cy = 420, r = 170, kw = outBack(seg(t, a0, a0 + 0.8));
  if (kw > 0) {
    const kk = clamp(kw);
    ctx.save(); ctx.globalAlpha *= kk;
    rr(cx - 70, cy - r - 70, 140, 80, 20); ctx.fillStyle = "#1a2520"; ctx.fill();
    rr(cx - 70, cy + r - 10, 140, 80, 20); ctx.fill();
    ctx.restore();
    dot(cx, cy, r + 14, "#2a3a32", kk); dot(cx, cy, r, "#050806", kk);
    ring(cx, cy, r - 8, C.accent, 4, kk * 0.4);
    text(S.wName, cx, cy - 76, { size: 18, weight: 600, font: MONO, color: C.soft, align: "center", alpha: kk });
    text(S.wName2, cx, cy - 46, { size: 22, weight: 800, font: SORA, color: C.accent, align: "center", alpha: kk });
    // FC en direct : monte, puis redescend quand les watts baissent
    const T = a1 + 1.0;
    const hr = 130 + 13 * bump(t, T + 1.2, 1.1) + 2 * Math.sin(t * 2.1);
    const over = hr > 138.5;
    text(S.wStep, cx, cy + 6, { size: 18, weight: 700, font: MONO, color: C.faint, align: "center", alpha: kk });
    text(`${Math.round(hr)}`, cx, cy + 74, { size: 64, weight: 800, font: SORA, color: over ? C.red : C.ink, align: "center", alpha: kk });
    text(`${S.wHr} bpm`, cx, cy + 108, { size: 15, font: MONO, color: C.soft, align: "center", alpha: kk });
    text(S.wP, cx, cy + 134, { size: 13, font: MONO, color: C.faint, align: "center", alpha: kk });
    // alerte
    const ko = seg(t, T + 0.4, T + 0.8) * (1 - seg(t, T + 3.0, T + 3.4));
    if (ko > 0) {
      pill(S.over, 560, 560, { size: 15, alpha: ko, color: C.red, fill: "rgba(240,122,95,0.08)", stroke: "rgba(240,122,95,0.5)" });
      text(S.ease, 560, 606, { size: 18, weight: 700, color: C.amber, alpha: ko });
    }
  }
  // nom de séance Garmin + trace dans la semaine
  const kg = outCubic(seg(t, a0 + 1.4, a0 + 2.0));
  if (kg > 0) {
    panel(560, 190, 640, 92, { r: 16, alpha: kg });
    text("Garmin Connect · workoutName", 584, 224, { size: 12, weight: 600, font: MONO, color: C.faint, alpha: kg });
    text(typed(`${S.wName} ${S.wName2}`, seg(t, a0 + 1.8, a0 + 3.0)), 584, 260, { size: 22, weight: 700, font: MONO, color: C.accent, alpha: kg });
  }
  const kj = outCubic(seg(t, a0 + 3.2, a0 + 3.8));
  if (kj > 0) {
    terminal(560, 300, 640, 220, t, [
      { s: S.weekT, a: a0 + 3.4, c: C.faint },
      { s: "\"virtual_route\": {", a: a0 + 3.6, b: a0 + 4.0 },
      { s: "  \"platform\": \"mywhoosh\", \"route_id\": 120,", a: a0 + 4.0, b: a0 + 4.6, c: C.soft },
      { s: "  \"name\": \"Limmat Loop\", \"laps\": 2,", a: a0 + 4.6, b: a0 + 5.2, c: C.soft },
      { s: "  \"predicted_s\": 4217, \"target_power_w\": 141 }", a: a0 + 5.2, b: a0 + 5.8, c: C.soft },
    ], { alpha: kj, size: 14, lh: 26, title: "arc" });
  }
}

/* ------------------------------ 05 · le calendrier MyWhoosh ------------------------------ */
function sCalendar(t, d, cues) {
  head(S.k5, S.h5, t);
  const a0 = at(cues, 0, 0.6);
  pill(`[home_trainer] ${S.conf}`, 80, 200, { size: 14, alpha: seg(t, a0, a0 + 0.5), color: C.ink, fill: C.panel2, stroke: C.line });
  const k = outCubic(seg(t, a0 + 0.6, a0 + 1.2));
  if (k <= 0) return;
  const x = 340, y = 236 + (1 - k) * 18, w = 600, h = 330;
  panel(x, y, w, h, { r: 18, fill: C.panel2, stroke: C.accent, lw: 2, alpha: k, shadow: true });
  text(S.ask, x + 28, y + 50, { size: 24, weight: 800, font: SORA, alpha: k });
  S.rows.forEach(([l, v], i) => {
    const kk = seg(t, a0 + 1.4 + i * 0.4, a0 + 1.9 + i * 0.4);
    text(l, x + 28, y + 100 + i * 36, { size: 15, color: C.faint, alpha: k * kk });
    text(v, x + 170, y + 100 + i * 36, { size: 16, weight: 600, font: MONO, alpha: k * kk });
  });
  text(S.dry, x + 28, y + 222, { size: 13, font: MONO, color: C.amber, alpha: k * seg(t, a0 + 2.8, a0 + 3.3) });
  const T = a0 + 4.6, pressed = t >= T + 0.2;
  keyBtn(S.yes, x + 28, y + 250, 130, 46, pressed, { alpha: k, size: 16 });
  keyBtn(S.no, x + 172, y + 250, 130, 46, false, { alpha: k, size: 16 });
  const [px, py] = [lerp(1120, x + 28 + 65, inOut(seg(t, T - 1.4, T))), lerp(620, y + 273, inOut(seg(t, T - 1.4, T)))];
  if (t > T - 1.4) cursor(px, py, { click: seg(t, T, T + 0.5), alpha: seg(t, T - 1.4, T - 0.9) * (1 - seg(t, T + 1.6, T + 2.2)) });
  const kd = outCubic(seg(t, T + 0.9, T + 1.5));
  if (kd > 0) { check(x + 340, y + 272, 13, C.teal, kd, kd); text(S.done, x + 362, y + 278, { size: 15, weight: 600, color: C.teal, alpha: kd }); }
  pill(S.headless, 340, 610, { size: 14, alpha: outCubic(seg(t, T + 1.8, T + 2.4)), color: C.amber, fill: "rgba(240,180,60,0.08)", stroke: "rgba(240,180,60,0.45)" });
}

/* ------------------------------ 06 · la carte du tableau de bord ------------------------------ */
function sCard(t, d, cues) {
  head(S.k6, S.h6, t);
  const a0 = at(cues, 0, 0.6), a1 = at(cues, 1, 6.5);
  const k = outCubic(seg(t, a0, a0 + 0.6));
  if (k <= 0) return;
  // cadre de vue
  const x = 80, y = 176 + (1 - k) * 16, w = 820, h = 500;
  panel(x, y, w, h, { r: 18, fill: "#0b130f", alpha: k, shadow: true });
  pill(S.view, x + 24, y + 30, { size: 13, alpha: k });
  panel(x + 24, y + 56, w - 48, h - 80, { r: 14, alpha: k });
  text(S.card, x + 48, y + 98, { size: 24, weight: 800, font: SORA, alpha: k });
  text(S.eq, x + 48, y + 126, { size: 14, color: C.soft, alpha: k });
  // puissance par zone
  const kz = seg(t, a0 + 1.6, a0 + 2.2);
  text(S.zT.toUpperCase(), x + 48, y + 170, { size: 11, weight: 600, font: MONO, color: C.faint, alpha: k * kz, spacing: "1px" });
  ZONES.forEach(([lo, hi, plo, phi, ex], i) => {
    const kk = outCubic(seg(t, a0 + 1.8 + i * 0.25, a0 + 2.3 + i * 0.25)), ry = y + 200 + i * 30;
    if (kk <= 0) return;
    const z2 = i === 1;
    text(`Z${i + 1}`, x + 48, ry, { size: 14, weight: 700, font: MONO, color: z2 ? C.accent : C.ink, alpha: kk });
    text(`${lo}–${hi} bpm`, x + 96, ry, { size: 14, font: MONO, color: C.soft, alpha: kk });
    panel(x + 236, ry - 12, (phi - 90) * 1.6, 12, { r: 6, fill: z2 ? C.accent : C.teal, stroke: false, alpha: kk * (ex ? 0.45 : 0.9) });
    text(`${plo}–${phi} W`, x + 236 + (phi - 90) * 1.6 + 10, ry, { size: 14, font: MONO, alpha: kk });
    if (ex) pill(S.extra, x + 600, ry - 5, { size: 11, alpha: kk, color: C.amber, fill: "rgba(240,180,60,0.08)", stroke: "rgba(240,180,60,0.4)" });
  });
  // dernières séances
  const kr = seg(t, a0 + 3.4, a0 + 4.0);
  text(S.recT.toUpperCase(), x + 48, y + 370, { size: 11, weight: 600, font: MONO, color: C.faint, alpha: k * kr, spacing: "1px" });
  S.rec.forEach(([dt, name, dur, p], i) => {
    const kk = outCubic(seg(t, a0 + 3.6 + i * 0.25, a0 + 4.1 + i * 0.25)), ry = y + 398 + i * 26;
    text(dt, x + 48, ry, { size: 13, font: MONO, color: C.soft, alpha: kk });
    text(name, x + 160, ry, { size: 14, alpha: kk });
    text(dur, x + 420, ry, { size: 13, font: MONO, color: C.soft, alpha: kk, align: "right" });
    text(p, x + 520, ry, { size: 14, weight: 700, font: MONO, color: C.accent, alpha: kk, align: "right" });
  });
  text(S.note, x + w - 48, y + 98, { size: 12, font: MONO, color: C.amber, align: "right", alpha: k * seg(t, a0 + 4.6, a0 + 5.1) });
  // opt-in
  const ko = outCubic(seg(t, a1, a1 + 0.5));
  if (ko > 0) {
    panel(930, 300, 270, 200, { r: 16, alpha: ko });
    text("[home_trainer]", 954, 340, { size: 15, weight: 600, font: MONO, color: C.faint, alpha: ko });
    const on = t > a1 + 1.6;
    text(on ? S.cfgOn : S.cfgOff, 954, 378, { size: 15, weight: 700, font: MONO, color: on ? C.accent : C.ink, alpha: ko });
    if (on) check(1170, 372, 10, C.accent, seg(t, a1 + 1.6, a1 + 2.1));
    pill(S.optin, 954, 440, { size: 13, alpha: ko, color: C.teal, fill: "rgba(95,184,160,0.08)", stroke: "rgba(95,184,160,0.4)" });
  }
}

ARC.episode({
  n: 19, slug: "home-trainer",
  strings: STR,
  shots: [],
  scenes: { watts: sWatts, catalogue: sCatalogue, fit: sFit, watch: sWatch, calendar: sCalendar, card: sCard },
});
})();
