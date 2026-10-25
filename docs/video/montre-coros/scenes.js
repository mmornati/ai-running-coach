/* Le Sentier · étape 22 — « Une autre montre » : une montre COROS branchée au coach par le MCP officiel
 * de COROS, via un relais local (`install.sh --source coros` / `--coros`, `arc_coros_auth.py login`),
 * le bilan matinal (HRV, FC de repos, « récupération COROS » nommée, jamais convertie), la nuit pas encore
 * calculée, les splits calculés depuis le FIT, l'envoi des séances après un « oui », la fiche Pace Strategy
 * (`arc_coros_workout.py pace-strategy`) et les limites.
 * Faits et libellés : docs/coros.md, docs/skills/coros-workout-scheduling.md, AGENTS.md (sections COROS),
 * scripts/arc_coros_auth.py, scripts/arc_coros_mcp.py, scripts/arc_coros_workout.py.
 * Moteur : ../engine/engine.js (helpers globaux). Découpage et narration : script.json.
 * Athlète et valeurs fictives (bible de la série : Camille, Trail des Crêtes). */
"use strict";
(() => {
const BLUE = "#6ea6e3", PURPLE = "#b39ddb";
const STR = {
  fr: {
    k1: "01 · UNE SEULE CONNEXION", h1: "Pas de compte tiers : le MCP officiel de COROS.",
    cmds: ["./install.sh --source coros", "python3 scripts/arc_coros_auth.py login"],
    cm: ["source de données : COROS", "connexion (interactive)"],
    ais: ["Claude Code", "Copilot", "Cursor", "OpenCode", "Gemini", "Windsurf"],
    ai: "toutes vos IA", relay: "relais local", relayF: "scripts/arc_coros_mcp.py", mcp: "MCP officiel COROS",
    tok: "jetons : ~/.config/ai-running-coach/coros/", tok2: "dossier 700 · fichiers 600 · jamais affichés",
    alone: "--coros : la montre seule, sans changer de source de données",
    k2: "02 · LE MÊME BILAN", h2: "Le triptyque, avec les mots de COROS.",
    cards: [["HRV de la nuit", "58 ms", "querySleepHrv"], ["FC de repos", "52 bpm", "queryRestingHeartRate"], ["récupération COROS", "96 %", "queryRecoveryStatus"]],
    never: ["« Training Readiness »", "seuils Garmin"], neverL: "jamais", provider: "provider_scores · recovery · 0–100",
    k3: "03 · NUIT PAS CALCULÉE", h3: "Le coach le dit. Jamais « tout va bien ».",
    raw: ["Sleep Score: 0", "HRV : No data found", "FC de repos : No data"], raws: "chez COROS, au réveil",
    verdict: "nuit pas encore calculée", noGood: "« tout va bien »",
    file: "medical/…_health.md", fileN: "aucun fichier écrit", retry: "le passage suivant réessaie", headless: "synchronisation sans tête",
    k4: "04 · SPLITS", h4: "Au kilomètre, depuis le FIT.",
    cmd4: "arc_index.py splits c<LabelId>", fit: "FIT", kmCols: ["km", "allure", "FC", "D+"],
    laps: "tours de la montre", lapsN: "repartent à chaque étape de la séance", lapsX: "jamais recopiés dans splits",
    k5: "05 · VERS LA MONTRE", h5: "Un « oui », puis la relecture.",
    wk: [["Mar", "Endurance · 40 min", "137–149 bpm"], ["Jeu", "Côtes · 6 × 30 m D+", "FC cible"], ["Sam", "Sortie longue · 2 h", "FC cible"], ["Dim", "Renfo descentes", "séance type"]],
    steps: ["calendrier COROS lu", "« j'envoie ces séances ? »", "envoi", "relecture : identique"],
    yes: "oui", noHL: "jamais sans tête (headless)", tpl: "créée une fois dans l'app COROS",
    k6: "06 · JOUR DE COURSE", h6: "La fiche Pace Strategy, à recopier.",
    cmd6: "arc_coros_workout.py pace-strategy --plan <plan> --text",
    sheet: "FICHE PACE STRATEGY", race: "Trail des Crêtes · 42 km", target: "Temps cible", targetV: "6 h 05",
    stops: "Arrêts aux ravitos", stopsV: ["km 12", "km 24", "km 33"], stopsT: ["1:30", "2:00", "1:30"],
    segs: "Allure par segment", segsV: [["km 0–12", "7:05"], ["km 12–24", "9:30"], ["km 24–33", "9:50"], ["km 33–42", "8:40"]],
    app: "À saisir dans l'app COROS", appP: "Profil → Pace Strategy", notSent: "pas envoyée : à recopier",
    k7: "07 · LES LIMITES", h7: "Ce que le MCP COROS ne fait pas.",
    lim: [["FC de récupération", "absente du MCP", "omise, jamais inventée"], ["Matériel par séance", "absent du MCP", "chat ou « par défaut »"],
      ["Envoi de parcours", "aucun outil", "dans l'app COROS"], ["Supprimer / déplacer une séance", "aucun outil", "vous le faites dans l'app"]],
  },
  en: {
    k1: "01 · ONE SIGN-IN", h1: "No third-party account: the official COROS MCP.",
    cmds: ["./install.sh --source coros", "python3 scripts/arc_coros_auth.py login"],
    cm: ["data source: COROS", "sign-in (interactive)"],
    ais: ["Claude Code", "Copilot", "Cursor", "OpenCode", "Gemini", "Windsurf"],
    ai: "all your AIs", relay: "local relay", relayF: "scripts/arc_coros_mcp.py", mcp: "official COROS MCP",
    tok: "tokens: ~/.config/ai-running-coach/coros/", tok2: "folder 700 · files 600 · never shown",
    alone: "--coros: the watch alone, keeping your data source",
    k2: "02 · THE SAME CHECK", h2: "The trio, in COROS's own words.",
    cards: [["Overnight HRV", "58 ms", "querySleepHrv"], ["Resting HR", "52 bpm", "queryRestingHeartRate"], ["COROS recovery", "96 %", "queryRecoveryStatus"]],
    never: ["“Training Readiness”", "Garmin thresholds"], neverL: "never", provider: "provider_scores · recovery · 0–100",
    k3: "03 · NIGHT NOT READY", h3: "The coach says so. Never “all good”.",
    raw: ["Sleep Score: 0", "HRV: No data found", "Resting HR: No data"], raws: "at COROS, on waking",
    verdict: "night not computed yet", noGood: "“all good”",
    file: "medical/…_health.md", fileN: "no file written", retry: "the next run tries again", headless: "headless sync",
    k4: "04 · SPLITS", h4: "Per kilometer, from the FIT.",
    cmd4: "arc_index.py splits c<LabelId>", fit: "FIT", kmCols: ["km", "pace", "HR", "D+"],
    laps: "the watch's laps", lapsN: "restart at every workout step", lapsX: "never copied into splits",
    k5: "05 · TO THE WATCH", h5: "A “yes”, then a read-back.",
    wk: [["Tue", "Endurance · 40 min", "137–149 bpm"], ["Thu", "Hills · 6 × 30 m D+", "target HR"], ["Sat", "Long run · 2 h", "target HR"], ["Sun", "Downhill strength", "template"]],
    steps: ["COROS calendar read", "“send these workouts?”", "send", "read back: identical"],
    yes: "yes", noHL: "never headless", tpl: "created once in the COROS app",
    k6: "06 · RACE DAY", h6: "The Pace Strategy sheet, to copy.",
    cmd6: "arc_coros_workout.py pace-strategy --plan <plan> --text",
    sheet: "PACE STRATEGY SHEET", race: "Trail des Crêtes · 42 km", target: "Target time", targetV: "6 h 05",
    stops: "Aid-station stops", stopsV: ["km 12", "km 24", "km 33"], stopsT: ["1:30", "2:00", "1:30"],
    segs: "Pace per segment", segsV: [["km 0–12", "7:05"], ["km 12–24", "9:30"], ["km 24–33", "9:50"], ["km 33–42", "8:40"]],
    app: "To enter in the COROS app", appP: "Profile → Pace Strategy", notSent: "not sent: to copy",
    k7: "07 · THE LIMITS", h7: "What the COROS MCP doesn't do.",
    lim: [["Heart rate recovery", "missing from the MCP", "left out, never invented"], ["Gear per activity", "missing from the MCP", "chat or “default”"],
      ["Course upload", "no tool", "in the COROS app"], ["Delete / move a workout", "no tool", "you do it in the app"]],
  },
};

/* ------------------------------- dessins locaux ------------------------------- */
const nolig = s => s.replace(/=(?=[=>])/g, "= ");
function head(k, h, t) { kicker(k, seg(t, 0, 0.4)); headline(h, seg(t, 0.1, 0.7), 132, 38); fictTag(seg(t, 0.3, 0.8)); }
function label(s, x, y, k, col = C.accent, align = "left") { text(s, x, y, { size: 12, weight: 600, font: MONO, color: col, alpha: k, spacing: "2px", align }); }
function cross(x, y, s, col, k = 1) {
  if (k <= 0) return;
  line(partial([[x - s, y - s], [x + s, y + s]], k), col, 3); line(partial([[x + s, y - s], [x - s, y + s]], k), col, 3);
}
function strike(x, y, w, k, col = C.red) { if (k > 0) line(partial([[x - 6, y], [x + w + 6, y]], k), col, 3); }
function ring2(x, y, r, k, col) { // petit disque + anneau
  dot(x, y, r, col, 0.18 * k); ring(x, y, r, col, 2.5, k);
}

/* ------------------------------ 01 · le relais ------------------------------ */
function sRelay(t, d, cues) {
  head(S.k1, S.h1, t);
  const a0 = at(cues, 0, 0.6), a1 = at(cues, 1, 7), e0 = atEnd(cues, 0, 6);
  const k0 = outCubic(seg(t, 0.3, 0.9));
  // les deux commandes
  const ts = [a1 + 0.3, a1 + 2.0];
  const lines = S.cmds.map((s, i) => ({ p: "$ ", s, c: i === 0 ? C.accent : C.ink, w: i === 0 ? 700 : 400, a: ts[i], b: ts[i] + (i === 0 ? 1.3 : 1.9) }));
  terminal(80, 190, 520, 200, t, lines, { alpha: k0, size: 14, lh: 40, title: "bash" });
  const kc = [seg(t, ts[0] + 1.3, ts[0] + 1.9), seg(t, ts[1] + 1.9, ts[1] + 2.5)];
  S.cm.forEach((s, i) => { if (kc[i] > 0) pill(s, 100, 424 + i * 40, { size: 13, alpha: kc[i], color: i ? C.amber : C.accent, fill: i ? "rgba(240,180,60,0.08)" : undefined, stroke: i ? "rgba(240,180,60,0.45)" : undefined }); });
  const kt = outCubic(seg(t, a1 + 3.2, a1 + 3.8));
  if (kt > 0) {
    panel(80, 512, 520, 84, { r: 14, fill: "rgba(163,230,53,0.06)", stroke: C.accent, alpha: kt });
    text(S.tok, 100, 544, { size: 13, weight: 700, font: MONO, color: C.accent, alpha: kt });
    text(S.tok2, 100, 574, { size: 13, color: C.soft, alpha: kt });
  }
  // le schéma : IA → relais → MCP officiel
  const kd = outCubic(seg(t, a0 + 0.3, a0 + 0.9));
  const x = 700, w = 480;
  panel(x, 176, w, 122, { r: 16, alpha: kd });
  label(S.ai.toUpperCase(), x + 22, 206, kd, C.faint);
  S.ais.forEach((s, i) => {
    const ka = outBack(seg(t, a1 + 0.2 + i * 0.25, a1 + 0.6 + i * 0.25));
    if (ka > 0) pill(s, x + 22 + (i % 3) * 150, 238 + Math.floor(i / 3) * 40, { size: 13, font: INTER, alpha: clamp(ka), color: C.ink, fill: C.panel2, stroke: C.line });
  });
  const kr = outCubic(seg(t, a0 + 2.2, a0 + 2.8));
  arrow(x + w / 2, 298, x + w / 2, 340, clamp(kr), C.accent, kd);
  panel(x, 344, w, 92, { r: 16, fill: C.pine, stroke: C.accent, lw: 2, alpha: kr });
  text(S.relay, x + 24, 382, { size: 22, weight: 800, font: SORA, alpha: kr });
  text(S.relayF, x + 24, 412, { size: 14, font: MONO, color: C.accent, alpha: kr });
  const km = outCubic(seg(t, a0 + 3.6, a0 + 4.2));
  arrow(x + w / 2, 436, x + w / 2, 476, clamp(km), C.accent, kr);
  panel(x, 480, w, 70, { r: 16, alpha: km });
  logo(x + 50, 515, 0.5, km, BLUE);
  text(S.mcp, x + 98, 523, { size: 20, weight: 800, font: SORA, alpha: km });
  if (km > 0.5) packets(x + w / 2, 298, x + w / 2, 340, t, 3, 1.4, 0.9);
  const ka = outBack(seg(t, a1 + 4.8, a1 + 5.4));
  if (ka > 0) pill(S.alone, 700, 596, { size: 13, alpha: clamp(ka), color: C.soft, fill: C.deep, stroke: C.line });
}

/* ------------------------------ 02 · le triptyque ------------------------------ */
function sMorning(t, d, cues) {
  head(S.k2, S.h2, t);
  const a0 = at(cues, 0, 0.6), a1 = at(cues, 1, 6);
  S.cards.forEach(([n, v, tool], i) => {
    const a = a0 + 1.0 + i * 0.9, k = outBack(seg(t, a, a + 0.6)), x = 80 + i * 380, hero = i === 2;
    if (k <= 0) return;
    const ck = clamp(k);
    panel(x, 190 + (1 - ck) * 20, 360, 190, { r: 18, fill: hero ? "rgba(163,230,53,0.07)" : C.panel, stroke: hero ? C.accent : C.line, lw: hero ? 2 : 1, alpha: ck });
    label(n.toUpperCase(), x + 24, 228, ck, hero ? C.accent : C.faint);
    text(v, x + 24, 312, { size: 64, weight: 800, font: SORA, color: hero ? C.accent : C.ink, alpha: ck });
    text(tool, x + 24, 356, { size: 13, font: MONO, color: C.faint, alpha: ck });
  });
  const kp = outCubic(seg(t, a0 + 4.2, a0 + 4.8));
  if (kp > 0) pill(S.provider, 1200, 420, { align: "right", size: 13, alpha: kp, color: C.soft, fill: C.deep, stroke: C.line });
  // les interdits
  const kn = outCubic(seg(t, a1 + 0.2, a1 + 0.8));
  label(S.neverL.toUpperCase(), 80, 484, kn, C.red);
  S.never.forEach((s, i) => {
    const x = 200 + i * 340, k = outBack(seg(t, a1 + 0.6 + i * 0.9, a1 + 1.1 + i * 0.9));
    if (k <= 0) return;
    const w = pill(s, x, 480, { size: 18, font: INTER, alpha: clamp(k), color: C.ink, fill: C.panel2, stroke: C.red, padX: 20 });
    strike(x, 480, w, seg(t, a1 + 1.2 + i * 0.9, a1 + 1.7 + i * 0.9));
  });
}

/* ------------------------------ 03 · la nuit pas calculée ------------------------------ */
function sNight(t, d, cues) {
  head(S.k3, S.h3, t);
  const a0 = at(cues, 0, 0.6), a1 = at(cues, 1, 6);
  const k0 = outCubic(seg(t, 0.3, 0.9));
  panel(80, 180, 500, 200, { r: 18, alpha: k0 });
  label(S.raws.toUpperCase(), 104, 214, k0, C.faint);
  S.raw.forEach((s, i) => {
    const k = outCubic(seg(t, a0 + 0.6 + i * 0.5, a0 + 1.0 + i * 0.5));
    text(s, 104, 262 + i * 40, { size: 20, font: MONO, color: C.soft, alpha: k });
    if (k > 0) dot(88, 255 + i * 40, 4, C.faint, k);
  });
  const kv = outBack(seg(t, a0 + 2.6, a0 + 3.2));
  if (kv > 0) pill(S.verdict, 330, 420, { size: 18, align: "center", alpha: clamp(kv), color: C.amber, fill: "rgba(240,180,60,0.1)", stroke: C.amber, padX: 22 });
  // le « tout va bien » barré
  const kg = outBack(seg(t, a0 + 3.6, a0 + 4.2));
  if (kg > 0) {
    const w = pill(S.noGood, 330, 480, { size: 18, font: INTER, align: "center", alpha: clamp(kg), color: C.faint, fill: C.panel2, stroke: C.line, padX: 22 });
    strike(330 - w / 2, 480, w, seg(t, a0 + 4.2, a0 + 4.7));
  }
  // en headless : aucun fichier
  const kh = outCubic(seg(t, a1 + 0.2, a1 + 0.8));
  panel(660, 180, 540, 300, { r: 18, alpha: kh });
  label(S.headless.toUpperCase(), 684, 214, kh, PURPLE);
  const fx = 700, fy = 244, fw = 460, fh = 90;
  ctx.save(); ctx.globalAlpha *= kh; rr(fx, fy, fw, fh, 12); ctx.setLineDash([8, 7]); ctx.strokeStyle = C.faint; ctx.lineWidth = 2; ctx.stroke(); ctx.restore();
  text(S.file, fx + 24, fy + 40, { size: 18, font: MONO, color: C.faint, alpha: kh });
  const kx = outBack(seg(t, a1 + 1.0, a1 + 1.6));
  text(S.fileN, fx + 24, fy + 70, { size: 14, weight: 700, color: C.amber, alpha: clamp(kx) });
  cross(fx + fw - 40, fy + fh / 2, 14, C.red, seg(t, a1 + 1.2, a1 + 1.8));
  const kr = outCubic(seg(t, a1 + 2.6, a1 + 3.2));
  if (kr > 0) {
    ctx.save(); ctx.globalAlpha *= kr; ctx.translate(730, 400); ctx.rotate(t * 1.4);
    ctx.beginPath(); ctx.arc(0, 0, 16, 0.3, Math.PI * 1.7); ctx.strokeStyle = PURPLE; ctx.lineWidth = 4; ctx.lineCap = "round"; ctx.stroke(); ctx.restore();
    text(S.retry, 770, 408, { size: 18, weight: 700, font: SORA, alpha: kr });
  }
}

/* ------------------------------ 04 · les splits ------------------------------ */
function sSplits(t, d, cues) {
  head(S.k4, S.h4, t);
  const a0 = at(cues, 0, 0.6), a1 = at(cues, 1, 5);
  const k0 = outCubic(seg(t, 0.3, 0.9));
  // le FIT → le tableau
  panel(80, 180, 150, 90, { r: 14, fill: C.pine, stroke: C.accent, alpha: k0 });
  text(S.fit, 155, 236, { size: 34, weight: 800, font: SORA, color: C.accent, align: "center", alpha: k0 });
  arrow(230, 225, 290, 225, seg(t, a0 + 0.6, a0 + 1.2), C.accent, k0);
  pill(S.cmd4, 80, 470, { size: 13, alpha: outCubic(seg(t, a0 + 0.8, a0 + 1.4)) });
  const rows = [["1", "6:42", "138", "34"], ["2", "6:51", "141", "41"], ["3", "7:30", "146", "88"], ["4", "7:12", "148", "62"], ["5", "6:38", "145", "12"]];
  const tx = 300, cw = [70, 120, 90, 90];
  panel(tx, 176, 420, 252, { r: 16, alpha: k0 });
  let cx = tx + 24;
  S.kmCols.forEach((s, i) => { label(s.toUpperCase(), cx, 208, k0, C.faint); cx += cw[i]; });
  line([[tx + 18, 220], [tx + 402, 220]], C.line, 1, k0);
  rows.forEach((r, i) => {
    const k = outCubic(seg(t, a0 + 1.2 + i * 0.4, a0 + 1.6 + i * 0.4));
    let x = tx + 24;
    r.forEach((v, j) => { text(v, x, 254 + i * 38, { size: 18, font: MONO, weight: j === 1 ? 700 : 400, color: j === 1 ? C.accent : C.ink, alpha: k }); x += cw[j]; });
  });
  // les tours de la montre : repartent à chaque étape
  const kl = outCubic(seg(t, a1 + 0.2, a1 + 0.8));
  panel(760, 176, 440, 252, { r: 16, alpha: kl });
  label(S.laps.toUpperCase(), 784, 208, kl, C.amber);
  const steps = [[0, 150, "40:00"], [156, 70, "1"], [232, 40, "2"], [278, 70, "3"], [354, 38, "4"]];
  steps.forEach(([ox, ow, lab], i) => {
    const k = outCubic(seg(t, a1 + 0.6 + i * 0.25, a1 + 1.0 + i * 0.25));
    panel(784 + ox, 236, ow, 44, { r: 8, fill: "rgba(240,180,60,0.18)", stroke: C.amber, alpha: k });
    text(lab, 784 + ox + ow / 2, 264, { size: 14, font: MONO, color: C.amber, align: "center", alpha: k });
  });
  const kn = outCubic(seg(t, a1 + 1.8, a1 + 2.4));
  para(S.lapsN, 784, 320, 390, { size: 17, color: C.soft, alpha: kn });
  const kx = outBack(seg(t, a1 + 2.8, a1 + 3.4));
  if (kx > 0) {
    const w = pill(S.lapsX, 784, 388, { size: 14, alpha: clamp(kx), color: C.red, fill: "rgba(240,122,95,0.08)", stroke: C.red });
    cross(784 + w + 22, 388, 9, C.red, seg(t, a1 + 3.2, a1 + 3.6));
  }
}

/* ------------------------------ 05 · l'envoi à la montre ------------------------------ */
function sPush(t, d, cues) {
  head(S.k5, S.h5, t);
  const a0 = at(cues, 0, 0.6), a1 = at(cues, 1, 9);
  // la semaine
  S.wk.forEach(([day, what, tgt], i) => {
    const k = outCubic(seg(t, 0.8 + i * 0.3, 1.3 + i * 0.3)), y = 176 + i * 76, tpl = i === 3;
    if (k <= 0) return;
    const sent = t >= a0 + 5.8 + i * 0.35;
    panel(80, y, 600, 64, { r: 14, fill: sent ? "rgba(163,230,53,0.06)" : C.panel, stroke: sent ? C.accent : C.line, alpha: k });
    text(day, 104, y + 40, { size: 20, weight: 800, font: SORA, color: C.accent, alpha: k });
    text(what, 176, y + 30, { size: 17, weight: 700, alpha: k });
    text(tgt, 176, y + 50, { size: 13, font: MONO, color: tpl ? PURPLE : C.faint, alpha: k });
    if (sent) check(646, y + 32, 16, C.accent, seg(t, a0 + 5.8 + i * 0.35, a0 + 6.2 + i * 0.35));
  });
  const kt = outCubic(seg(t, a1 + 2.4, a1 + 3.0));
  if (kt > 0) pill(S.tpl, 80, 498, { size: 13, alpha: kt, color: PURPLE, fill: "rgba(179,157,219,0.08)", stroke: PURPLE });
  // les étapes
  const sx = 740;
  S.steps.forEach((s, i) => {
    const a = [0.8, a0 + 2.0, a0 + 5.4, a1 + 0.4][i], k = outCubic(seg(t, a, a + 0.5)), y = 190 + i * 70;
    if (k <= 0) return;
    ring2(sx + 20, y + 20, 18, k, i === 1 ? C.amber : C.accent);
    if (i !== 1) check(sx + 20, y + 20, 14, C.accent, k);
    else text("?", sx + 20, y + 28, { size: 22, weight: 800, font: SORA, color: C.amber, align: "center", alpha: k });
    text(s, sx + 56, y + 28, { size: 19, weight: 700, font: i === 1 ? INTER : INTER, alpha: k });
    if (i < 3) line([[sx + 20, y + 40], [sx + 20, y + 52]], C.line, 2, k);
  });
  // la réponse de Camille
  const kb = outBack(seg(t, a0 + 4.0, a0 + 4.6));
  if (kb > 0) {
    panel(1080, 232, 100, 48, { r: 24, fill: C.pine, stroke: C.accent, alpha: clamp(kb) });
    text(S.yes, 1130, 263, { size: 20, weight: 800, font: SORA, color: C.accent, align: "center", alpha: clamp(kb) });
  }
  const kh = outBack(seg(t, a0 + 8.5, a0 + 9.1));
  if (kh > 0) {
    const w = pill(S.noHL, 740, 500, { size: 14, alpha: clamp(kh), color: C.red, fill: "rgba(240,122,95,0.08)", stroke: C.red });
    cross(740 + w + 24, 500, 9, C.red, seg(t, a0 + 8.9, a0 + 9.3));
  }
}

/* ------------------------------ 06 · la fiche Pace Strategy ------------------------------ */
function sRace(t, d, cues) {
  head(S.k6, S.h6, t);
  const a0 = at(cues, 0, 0.6), a1 = at(cues, 1, 8);
  const k0 = outCubic(seg(t, 0.3, 0.9));
  terminal(80, 176, 1120, 96, t, [{ p: "$ ", s: "python3 scripts/" + S.cmd6, c: C.accent, a: 0.6, b: 3.2 }], { alpha: k0, size: 16, lh: 30, title: "bash" });
  // la fiche
  const ks = outCubic(seg(t, a0 + 3.2, a0 + 3.8));
  panel(80, 298, 640, 290, { r: 16, fill: C.paper, stroke: false, alpha: ks, shadow: true });
  label(S.sheet, 108, 332, ks, "#4a5a52");
  text(S.race, 108, 366, { size: 22, weight: 800, font: SORA, color: C.paperInk, alpha: ks });
  text(S.target, 108, 408, { size: 15, color: "#4a5a52", alpha: ks });
  text(S.targetV, 270, 410, { size: 28, weight: 800, font: SORA, color: C.paperInk, alpha: seg(t, a0 + 4.0, a0 + 4.5) });
  text(S.stops, 108, 452, { size: 15, color: "#4a5a52", alpha: ks });
  S.stopsV.forEach((s, i) => {
    const k = seg(t, a0 + 4.6 + i * 0.35, a0 + 5.0 + i * 0.35);
    text(`${s} · ${S.stopsT[i]}`, 270 + i * 150, 454, { size: 17, weight: 700, font: MONO, color: C.paperInk, alpha: k });
  });
  text(S.segs, 108, 498, { size: 15, color: "#4a5a52", alpha: ks });
  S.segsV.forEach(([r, p], i) => {
    const k = seg(t, a0 + 5.8 + i * 0.35, a0 + 6.2 + i * 0.35), x = 108 + (i % 2) * 300, y = 530 + Math.floor(i / 2) * 36;
    text(r, x, y, { size: 16, font: MONO, color: "#4a5a52", alpha: k });
    text(p + " /km", x + 120, y, { size: 18, weight: 700, font: MONO, color: C.paperInk, alpha: k });
  });
  // vers l'app
  const ka = outCubic(seg(t, a1 + 0.2, a1 + 0.8));
  arrow(720, 440, 790, 440, clamp(ka), C.accent, ka);
  phone(810, 298, 190, 290, (x, y, w, h) => {
    ctx.fillStyle = "#101713"; ctx.fillRect(x, y, w, h);
    text("COROS", x + w / 2, y + 44, { size: 16, weight: 800, font: SORA, color: C.ink, align: "center" });
    text(S.appP, x + w / 2, y + 74, { size: 10, font: MONO, color: C.accent, align: "center" });
    [0, 1, 2].forEach(i => { panel(x + 14, y + 98 + i * 52, w - 28, 40, { r: 8, fill: "#1b2620", stroke: false }); });
  }, { alpha: ka });
  const kn = outBack(seg(t, a1 + 1.2, a1 + 1.8));
  if (kn > 0) {
    text(S.app, 1020, 340, { size: 15, weight: 700, color: C.soft, alpha: clamp(kn) });
    pill(S.notSent, 1020, 410, { size: 14, alpha: clamp(kn), color: C.amber, fill: "rgba(240,180,60,0.08)", stroke: C.amber });
  }
}

/* ------------------------------ 07 · les limites ------------------------------ */
function sLimits(t, d, cues) {
  head(S.k7, S.h7, t);
  const a0 = at(cues, 0, 0.6), a1 = at(cues, 1, 6);
  S.lim.forEach(([n, why, then], i) => {
    const a = i < 3 ? a0 + 1.4 + i * 1.2 : a1 + 0.4, k = outCubic(seg(t, a, a + 0.5)), y = 176 + i * 94;
    if (k <= 0) return;
    const last = i === 3;
    panel(80 + (1 - k) * 20, y, 1120, 80, { r: 16, fill: last ? "rgba(240,180,60,0.06)" : C.panel, stroke: last ? C.amber : C.line, lw: last ? 2 : 1, alpha: k });
    cross(120, y + 40, 12, C.red, seg(t, a + 0.2, a + 0.6));
    text(n, 160, y + 36, { size: 22, weight: 800, font: SORA, alpha: k });
    text(why, 160, y + 62, { size: 14, font: MONO, color: C.faint, alpha: k });
    pill(then, 1176, y + 40, { align: "right", size: 14, alpha: k, color: last ? C.amber : C.soft, fill: last ? "rgba(240,180,60,0.08)" : C.deep, stroke: last ? "rgba(240,180,60,0.5)" : C.line });
  });
  if (t > a1 + 1.0) highlight(80, 176 + 3 * 94, 1120, 80, seg(t, a1 + 1.0, a1 + 1.6), C.amber);
}

ARC.episode({
  n: 22, slug: "montre-coros",
  strings: STR,
  shots: [],
  scenes: { relay: sRelay, morning: sMorning, night: sNight, splits: sSplits, push: sPush, race: sRace, limits: sLimits },
});
})();
