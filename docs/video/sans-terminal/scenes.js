/* Le Sentier · étape 18 — « Sans terminal » : l'application macOS (#163) — DMG, questionnaire d'installation,
 * chat intégré ou assistant habituel, moteur et données séparés, connexion du compte dans une fenêtre à part,
 * écran d'accueil, synchronisation qui n'écrit jamais côté source —, puis la pesée lue dans Garmin Connect (#222).
 * Les fenêtres sont redessinées d'après les libellés de macos/AI-Running-Coach/AI_Running_CoachApp.swift
 * (aucune capture : l'app native n'est pas servie par le tableau de bord) ; les règles de la pesée sont celles
 * de scripts/arc_weight_sync.py et de docs/garmin-setup.md. Outils d'écriture refusés : scripts/daily-sync.sh.
 * Moteur : ../engine/engine.js (helpers globaux). Découpage et narration : script.json.
 * Athlète et chiffres fictifs (bible de la série : Camille, mardi 29 septembre 2026). */
"use strict";
(() => {
const BLUE = "#6ea6e3", PURPLE = "#b39ddb";
const STR = {
  fr: {
    dec: ",", win6: "6. Comment parler au coach", prompt: "▌ coach prêt — on court quoi aujourd'hui ?",
    k1: "01 · INSTALLER", h1: "Un questionnaire, pas une ligne de commande.",
    apps: "Applications", app: "AI Running Coach", sub: "Votre coach de course, installé sans ligne de commande",
    g1: "1. Faisons connaissance",
    f1: [["Prénom ou surnom", "Camille"], ["Année de naissance", "1991"], ["Années de pratique", "3 ans"], ["Temps disponible", "4 séances, environ 6 h"], ["Ville habituelle", "Val-d'Orée"]],
    steps: [["2. Votre objectif", "Trail des Crêtes · 22 nov. · 42 km"], ["3. Vos données sportives", "Garmin Connect"], ["4. Votre pratique", "Trail · Bienveillant · Bilan complet"],
      ["5. Votre équipe", "Coach + santé + nutrition + course"], ["6. Comment parler au coach", "…"], ["7. Où garder vos données", "~/Documents/AI Running Coach"]],
    later: "le reste : plus tard, depuis le même questionnaire", install: "Installer mon coach",
    k2: "02 · PARLER AU COACH", h2: "Le chat intégré, ou votre assistant.",
    seg: ["Chat intégré dans l'application", "Mon assistant IA habituel"],
    key: "Clé OpenRouter", keyV: "sk-or-v1-••••••••••••", cap: "Plafond par jour", capV: "1.00 €",
    keyN: "~/.config/ai-running-coach/llm.env · mode 600 · jamais dans le dossier de données",
    ide: "Assistant IA", ides: ["Claude Code", "GitHub Copilot", "OpenCode", "Gemini CLI", "Cursor"],
    ideN: "installé par l'application · ouvert dans le dossier de données", btn: "Parler au coach avec Claude Code",
    term: "~/Documents/AI Running Coach",
    k3: "03 · VOS DONNÉES", h3: "L'app d'un côté, vos données de l'autre.",
    eng: "Moteur", engP: "~/Library/Application Support/AI Running Coach/engine", dat: "Vos données", datP: "~/Documents/AI Running Coach",
    dirs: ["activities/", "medical/", "nutrition/", "planning/", "rapports/"], upd: "mise à jour · suppression de l'app", safe: "intactes",
    login: "Connexion Garmin", loginN: "fenêtre séparée : l'outil d'authentification d'origine", pw: "Mot de passe", mfa: "Code MFA", ok: "Compte connecté",
    never: "jamais saisis dans l'application",
    k4: "04 · AU QUOTIDIEN", h4: "Un seul écran.",
    ready: "Tout est prêt pour courir",
    cards: [["Compte connecté", "Garmin Connect", C.accent], ["Données personnelles", "AI Running Coach", BLUE], ["Synchronisation", "Automatique", PURPLE]],
    b1: "Parler au coach", b2: "Tableau de bord", b3: "Mes données", b4: "Synchroniser maintenant", done: "Synchronisation terminée — les données sont à jour.",
    local: "127.0.0.1 · jamais exposé au réseau",
    k5: "05 · EN ARRIÈRE-PLAN", h5: "La synchro lit. Elle n'écrit jamais.",
    reads: ["activités", "sommeil, HRV, readiness", "pesées"], writes: ["schedule_workouts", "upload_workout", "delete_workout", "add_gear_to_activity", "add_weigh_in", "log_food"],
    rT: "lit", wT: "refusés, un par un", how: [["Claude Code", "--disallowedTools"], ["Copilot", "--deny-tool"], ["Gemini", "excludeTools"], ["Cursor", "Mcp(serveur:outil)"]],
    srcs: "Garmin · Intervals.icu · Strava",
    k6: "06 · LA PESÉE", h6: "La balance parle au coach.",
    scale: "62,0 kg", when: "pesée de 7 h 02 · Garmin Connect", file: "medical/2026-09-29_health.md", ro: "lecture seule",
    rules: [["Jour sans pesée", "pas de weight_kg — jamais la valeur de la veille"], ["Poids donné en chat : 63,2 kg", "il prime ; écart > 1 kg signalé une fois"], ["Plusieurs pesées", "la plus ancienne, celle du matin"]],
    nw: "add_weigh_in · delete_weigh_ins : jamais exposés",
    k7: "07 · LES PAGES", h7: "Deux pages à garder sous la main.",
    pages: [["Application macOS", "installer, parler au coach, synchroniser", "macos"], ["Connexion Garmin", "jetons, liste blanche, poids lu dans Garmin Connect", "garmin-setup"]],
  },
  en: {
    dec: ".", win6: "6. How to talk to the coach", prompt: "▌ coach ready — what are we running today?",
    k1: "01 · INSTALL", h1: "A questionnaire, not a command line.",
    apps: "Applications", app: "AI Running Coach", sub: "Your running coach, installed without a command line",
    g1: "1. Getting to know you",
    f1: [["First name or nickname", "Camille"], ["Year of birth", "1991"], ["Years running", "3 years"], ["Time available", "4 sessions, about 6 h"], ["Usual town", "Val-d'Orée"]],
    steps: [["2. Your goal", "Trail des Crêtes · Nov 22 · 42 km"], ["3. Your sports data", "Garmin Connect"], ["4. Your training", "Trail · Supportive · Full check"],
      ["5. Your team", "Coach + health + nutrition + race"], ["6. How to talk to the coach", "…"], ["7. Where to keep your data", "~/Documents/AI Running Coach"]],
    later: "the rest: later, from the same questionnaire", install: "Install my coach",
    k2: "02 · TALK TO THE COACH", h2: "The built-in chat, or your assistant.",
    seg: ["Chat built into the app", "My usual AI assistant"],
    key: "OpenRouter key", keyV: "sk-or-v1-••••••••••••", cap: "Daily cap", capV: "€1.00",
    keyN: "~/.config/ai-running-coach/llm.env · mode 600 · never in the data folder",
    ide: "AI assistant", ides: ["Claude Code", "GitHub Copilot", "OpenCode", "Gemini CLI", "Cursor"],
    ideN: "installed by the app · opened in the data folder", btn: "Talk to the coach with Claude Code",
    term: "~/Documents/AI Running Coach",
    k3: "03 · YOUR DATA", h3: "The app on one side, your data on the other.",
    eng: "Engine", engP: "~/Library/Application Support/AI Running Coach/engine", dat: "Your data", datP: "~/Documents/AI Running Coach",
    dirs: ["activities/", "medical/", "nutrition/", "planning/", "rapports/"], upd: "app update · app deletion", safe: "untouched",
    login: "Garmin sign-in", loginN: "separate window: the original sign-in tool", pw: "Password", mfa: "MFA code", ok: "Account connected",
    never: "never typed into the app",
    k4: "04 · EVERY DAY", h4: "One single screen.",
    ready: "All set to run",
    cards: [["Account connected", "Garmin Connect", C.accent], ["Personal data", "AI Running Coach", BLUE], ["Sync", "Automatic", PURPLE]],
    b1: "Talk to the coach", b2: "Dashboard", b3: "My data", b4: "Sync now", done: "Sync finished — your data is up to date.",
    local: "127.0.0.1 · never exposed to the network",
    k5: "05 · IN THE BACKGROUND", h5: "Sync reads. It never writes.",
    reads: ["activities", "sleep, HRV, readiness", "weigh-ins"], writes: ["schedule_workouts", "upload_workout", "delete_workout", "add_gear_to_activity", "add_weigh_in", "log_food"],
    rT: "reads", wT: "denied, one by one", how: [["Claude Code", "--disallowedTools"], ["Copilot", "--deny-tool"], ["Gemini", "excludeTools"], ["Cursor", "Mcp(server:tool)"]],
    srcs: "Garmin · Intervals.icu · Strava",
    k6: "06 · THE SCALE", h6: "The scale talks to the coach.",
    scale: "62.0 kg", when: "7:02 am weigh-in · Garmin Connect", file: "medical/2026-09-29_health.md", ro: "read only",
    rules: [["Day without a weigh-in", "no weight_kg — never yesterday's value"], ["Weight given in chat: 63.2 kg", "it wins; a gap > 1 kg is flagged once"], ["Several weigh-ins", "the earliest, the morning one"]],
    nw: "add_weigh_in · delete_weigh_ins: never exposed",
    k7: "07 · THE PAGES", h7: "Two pages to keep at hand.",
    pages: [["macOS app", "install, talk to the coach, sync", "macos"], ["Garmin connection", "tokens, allow-list, weight read from Garmin Connect", "garmin-setup"]],
  },
};

/* ------------------------------- dessins locaux ------------------------------- */
function head(k, h, t) { kicker(k, seg(t, 0, 0.4)); headline(h, seg(t, 0.1, 0.7), 132, 40); fictTag(seg(t, 0.3, 0.8)); }
function label(s, x, y, k, col = C.accent) { text(s, x, y, { size: 12, weight: 600, font: MONO, color: col, alpha: k, spacing: "2px" }); }
function cross(x, y, s, col, alpha = 1) {
  line([[x - s, y - s], [x + s, y + s]], col, 3, alpha); line([[x + s, y - s], [x - s, y + s]], col, 3, alpha);
}
/* Fenêtre macOS (thème sombre) : barre de titre et feux tricolores. */
function macWin(x, y, w, h, title, k, o = {}) {
  panel(x, y, w, h, { r: 14, fill: o.fill ?? "#1b1d1c", stroke: "#3a3d3b", alpha: k, shadow: true });
  ctx.save(); ctx.globalAlpha *= k; rr(x, y, w, 30, [14, 14, 0, 0]); ctx.fillStyle = "#2a2d2b"; ctx.fill(); ctx.restore();
  ["#ff5f57", "#febc2e", "#28c840"].forEach((c, i) => dot(x + 18 + i * 18, y + 15, 6, c, k));
  if (title) text(title, x + w / 2, y + 20, { size: 13, weight: 600, color: "#c9cdca", align: "center", alpha: k });
}
/* Icône de l'app : la montagne de la série sur fond vert. */
function appIcon(x, y, s, k) {
  panel(x, y, s, s, { r: s * 0.22, fill: C.pine, stroke: false, alpha: k, shadow: true });
  logo(x + s / 2, y + s / 2, s / 100, k);
}
function folder(x, y, w, h, k, col = BLUE) {
  ctx.save(); ctx.globalAlpha *= k;
  rr(x, y + h * 0.12, w * 0.42, h * 0.2, 6); ctx.fillStyle = col; ctx.fill();
  rr(x, y + h * 0.22, w, h * 0.78, 8); ctx.fill(); ctx.restore();
}
function btn(s, x, y, w, k, o = {}) {
  panel(x, y, w, 38, { r: 9, fill: o.primary ? "#0a84ff" : "#3a3d3b", stroke: false, alpha: k });
  text(s, x + w / 2, y + 25, { size: 14, weight: 600, color: "#fff", align: "center", alpha: k });
}
function field(lab, val, x, y, w, k, kv) {
  text(lab, x, y + 22, { size: 14, color: "#c9cdca", alpha: k });
  panel(x + 190, y, w - 190, 32, { r: 7, fill: "#121413", stroke: "#3a3d3b", alpha: k });
  text(typed(val, kv), x + 202, y + 22, { size: 14, color: "#fff", alpha: k });
}
function path(t, pts) {
  if (t <= pts[0][0]) return [pts[0][1], pts[0][2]];
  for (let i = 1; i < pts.length; i++) {
    if (t <= pts[i][0]) { const k = inOut(seg(t, pts[i - 1][0], pts[i][0])); return [lerp(pts[i - 1][1], pts[i][1], k), lerp(pts[i - 1][2], pts[i][2], k)]; }
  }
  const p = pts[pts.length - 1]; return [p[1], p[2]];
}

/* ------------------------------ 01 · le DMG et le questionnaire ------------------------------ */
function sInstall(t, d, cues) {
  head(S.k1, S.h1, t);
  const a0 = at(cues, 0, 0.6), a1 = at(cues, 1, 6);
  const sw = outCubic(seg(t, a0 + 3.4, a0 + 4.2));
  // le DMG : l'icône glisse vers Applications
  if (sw < 1) {
    const k = outCubic(seg(t, 0.3, 0.9)) * (1 - sw);
    macWin(300, 190, 680, 380, "AI-Running-Coach.dmg", k);
    const [ix, iy] = path(t, [[a0 + 0.8, 380, 300], [a0 + 2.6, 760, 300]]);
    folder(740, 286, 140, 120, k);
    text(S.apps, 810, 450, { size: 15, color: "#c9cdca", align: "center", alpha: k });
    arrow(530, 360, 700, 360, seg(t, a0 + 0.2, a0 + 0.8), C.faint, k * (1 - seg(t, a0 + 1.0, a0 + 1.4)));
    if (t < a0 + 2.7) {
      appIcon(ix, iy, 110, k);
      text(S.app, ix + 55, iy + 146, { size: 14, color: "#c9cdca", align: "center", alpha: k });
      cursor(ix + 70, iy + 70, { alpha: k * seg(t, a0 + 0.4, a0 + 0.8) });
    } else check(810, 360, 30, C.accent, seg(t, a0 + 2.7, a0 + 3.2), k);
  }
  // le questionnaire
  if (sw > 0) {
    macWin(80, 168, 1120, 470, "", sw);
    appIcon(110, 214, 64, sw);
    text(S.app, 194, 240, { size: 24, weight: 800, font: SORA, color: "#fff", alpha: sw });
    text(S.sub, 194, 266, { size: 14, color: "#9aa09c", alpha: sw });
    panel(110, 296, 560, 320, { r: 12, fill: "#232625", stroke: "#3a3d3b", alpha: sw });
    text(S.g1, 130, 326, { size: 15, weight: 700, color: "#fff", alpha: sw });
    S.f1.forEach(([l, v], i) => field(l, v, 130, 346 + i * 52, 520, sw, seg(t, a0 + 4.4 + i * 0.5, a0 + 5.0 + i * 0.5)));
    S.steps.forEach(([n, v], i) => {
      const a = a1 + 0.2 + i * 0.55, k = outCubic(seg(t, a, a + 0.4)) * sw, y = 304 + i * 46;
      if (k <= 0) return;
      panel(700, y, 470, 38, { r: 9, fill: "#232625", stroke: "#3a3d3b", alpha: k });
      check(720, y + 19, 9, C.accent, seg(t, a + 0.1, a + 0.5), k);
      text(n, 740, y + 24, { size: 13, weight: 700, color: "#fff", alpha: k });
      text(v, 1156, y + 24, { size: 12, font: MONO, color: "#9aa09c", align: "right", alpha: k });
    });
    const kb = outCubic(seg(t, a1 + 3.8, a1 + 4.4)) * sw;
    btn(S.install, 1000, 584, 170, kb, { primary: true });
    para(S.later, 700, 596, 280, { size: 12, font: MONO, color: C.faint, alpha: kb });
  }
}

/* ------------------------------ 02 · chat intégré ou assistant habituel ------------------------------ */
function sAssistant(t, d, cues) {
  head(S.k2, S.h2, t);
  const a0 = at(cues, 0, 0.6), a1 = at(cues, 1, 8);
  const k0 = outCubic(seg(t, 0.3, 0.9)), ext = t >= a1;
  macWin(80, 168, 700, 450, S.win6, k0);
  // contrôle segmenté
  panel(110, 216, 640, 36, { r: 9, fill: "#2a2d2b", stroke: false, alpha: k0 });
  const sx = lerp(114, 432, outCubic(seg(t, a1 - 0.2, a1 + 0.3)));
  panel(sx, 220, 314, 28, { r: 7, fill: "#4a4e4b", stroke: false, alpha: k0 });
  S.seg.forEach((s, i) => text(s, 271 + i * 318, 240, { size: 13, weight: 600, color: "#fff", align: "center", alpha: k0 }));
  if (!ext) {
    const k1 = outCubic(seg(t, a0 + 1.4, a0 + 2.0));
    field(S.key, S.keyV, 110, 280, 640, k1, seg(t, a0 + 2.0, a0 + 3.2));
    field(S.cap, S.capV, 110, 330, 640, outCubic(seg(t, a0 + 3.4, a0 + 3.9)), seg(t, a0 + 3.8, a0 + 4.4));
    const kn = outCubic(seg(t, a0 + 5.2, a0 + 5.8));
    if (kn > 0) {
      panel(110, 390, 640, 70, { r: 12, fill: "rgba(163,230,53,0.06)", stroke: C.accent, alpha: kn });
      ctx.save(); ctx.globalAlpha *= kn; ctx.beginPath(); ctx.arc(140, 418, 8, Math.PI, 0); ctx.strokeStyle = C.accent; ctx.lineWidth = 3; ctx.stroke(); ctx.restore();
      panel(128, 418, 24, 18, { r: 4, fill: C.accent, stroke: false, alpha: kn });
      para(S.keyN, 170, 418, 560, { size: 13, font: MONO, color: C.soft, alpha: kn });
    }
  } else {
    text(S.ide, 110, 300, { size: 14, color: "#c9cdca" });
    S.ides.forEach((s, i) => {
      const k = outBack(seg(t, a1 + 0.6 + i * 0.35, a1 + 1.0 + i * 0.35)), on = i === 0, x = 110 + (i % 3) * 214, y = 318 + Math.floor(i / 3) * 52;
      if (k > 0) pill(s, x, y + 20, { size: 14, font: INTER, alpha: clamp(k), color: on ? C.deep : "#fff", fill: on ? C.accent : "#2a2d2b", stroke: on ? C.accent : "#3a3d3b", padX: 18 });
    });
    text(S.ideN, 110, 440, { size: 13, font: MONO, color: C.faint, alpha: outCubic(seg(t, a1 + 2.6, a1 + 3.2)) });
    const kb = outCubic(seg(t, a1 + 3.4, a1 + 3.9));
    btn(S.btn, 110, 470, 330, kb, { primary: true });
    const T = a1 + 4.4;
    if (t > T - 1) cursor(...path(t, [[T - 1, 600, 600], [T, 270, 490]]), { click: seg(t, T, T + 0.5), alpha: seg(t, T - 1, T - 0.6) * (1 - seg(t, T + 1.4, T + 1.9)) });
    const kt = outCubic(seg(t, T + 0.5, T + 1.1));
    if (kt > 0) {
      const lines = [{ p: "$ ", s: "cd " + S.term, c: C.soft, a: T + 0.8 }, { p: "$ ", s: "claude", c: C.ink, a: T + 1.4, b: T + 1.9 }, { s: S.prompt, c: C.accent, a: T + 2.4 }];
      terminal(820, 300, 380, 200, t, lines, { alpha: kt, size: 13, lh: 30, title: "Terminal" });
    }
  }
}

/* ------------------------------ 03 · moteur et données séparés, connexion à part ------------------------------ */
function sData(t, d, cues) {
  head(S.k3, S.h3, t);
  const a0 = at(cues, 0, 0.6), a1 = at(cues, 1, 7);
  const k0 = outCubic(seg(t, 0.3, 0.9));
  // le moteur, dans l'app
  panel(80, 176, 520, 150, { r: 18, alpha: k0 });
  appIcon(104, 200, 56, k0);
  text(S.eng, 180, 226, { size: 22, weight: 800, font: SORA, alpha: k0 });
  para(S.engP, 180, 254, 400, { size: 12, font: MONO, color: C.faint, alpha: k0 });
  // vos données
  const kd = outCubic(seg(t, a0 + 1.6, a0 + 2.2));
  panel(680, 176, 520, 236, { r: 18, alpha: kd });
  folder(704, 196, 60, 52, kd);
  text(S.dat, 784, 226, { size: 22, weight: 800, font: SORA, alpha: kd });
  text(S.datP, 784, 250, { size: 12, font: MONO, color: C.faint, alpha: kd });
  S.dirs.forEach((s, i) => text(s, 710 + (i % 3) * 160, 300 + Math.floor(i / 3) * 34, { size: 14, font: MONO, color: C.soft, alpha: outCubic(seg(t, a0 + 2.2 + i * 0.15, a0 + 2.6 + i * 0.15)) }));
  // une mise à jour ne touche que le moteur
  const ku = seg(t, a0 + 4.0, a0 + 5.0);
  if (ku > 0) {
    text(S.upd, 340, 398, { size: 13, font: MONO, color: C.amber, align: "center", alpha: clamp(ku * 2) });
    arrow(340, 378, 340, 334, ku, C.amber);
    const ks = outBack(seg(t, a0 + 5.2, a0 + 5.8));
    if (ks > 0) { check(1160, 214, 14, C.accent, clamp(ks)); text(S.safe, 1140, 220, { size: 14, weight: 700, font: MONO, color: C.accent, align: "right", alpha: clamp(ks) }); }
  }
  // la connexion du compte, dans une fenêtre à part
  const kl = outCubic(seg(t, a1 - 0.2, a1 + 0.4));
  if (kl > 0) {
    macWin(80, 430, 520, 200, S.login, kl, { fill: "#0a120e" });
    text(S.loginN, 104, 486, { size: 12, font: MONO, color: C.faint, alpha: kl });
    field(S.pw, "••••••••••", 104, 504, 472, kl, seg(t, a1 + 0.8, a1 + 1.6));
    field(S.mfa, "4 8 2 7 1 9", 104, 552, 472, kl, seg(t, a1 + 1.8, a1 + 2.6));
    const kn = outCubic(seg(t, a1 + 3.0, a1 + 3.6));
    pill(S.never, 680, 470, { size: 13, alpha: kn, color: C.amber, fill: "rgba(240,180,60,0.08)", stroke: "rgba(240,180,60,0.45)" });
    const ko = outBack(seg(t, a1 + 4.2, a1 + 4.8));
    if (ko > 0) { panel(680, 520, 300, 56, { r: 12, fill: "#1b1d1c", stroke: C.accent, alpha: clamp(ko) }); check(706, 548, 12, C.accent, clamp(ko)); text(S.ok, 730, 554, { size: 16, weight: 700, alpha: clamp(ko) }); }
  }
}

/* ------------------------------ 04 · l'écran d'accueil ------------------------------ */
function sHome(t, d, cues) {
  head(S.k4, S.h4, t);
  const a0 = at(cues, 0, 0.6), a1 = at(cues, 1, 6);
  const k0 = outCubic(seg(t, 0.3, 0.9));
  macWin(140, 168, 1000, 456, "", k0);
  appIcon(172, 212, 64, k0);
  text(S.app, 256, 238, { size: 24, weight: 800, font: SORA, color: "#fff", alpha: k0 });
  text(S.ready, 256, 264, { size: 14, color: "#9aa09c", alpha: k0 });
  S.cards.forEach(([n, v, col], i) => {
    const k = outCubic(seg(t, 0.6 + i * 0.25, 1.1 + i * 0.25)) * k0, x = 172 + i * 316;
    panel(x, 300, 300, 80, { r: 12, fill: "#232625", stroke: "#3a3d3b", alpha: k });
    dot(x + 32, 340, 14, col, k);
    text(n, x + 58, 334, { size: 15, weight: 700, color: "#fff", alpha: k });
    text(v, x + 58, 358, { size: 13, color: "#9aa09c", alpha: k });
  });
  const bs = [[S.b1, 180, true], [S.b2, 170, false], [S.b3, 140, false]];
  let x = 172;
  bs.forEach(([s, w, p], i) => {
    const a = a0 + 1.6 + i * 0.9, on = t >= a && t < a + 0.9;
    btn(s, x, 410, w, k0, { primary: p });
    if (on) highlight(x, 410, w, 38, seg(t, a, a + 0.3));
    x += w + 14;
  });
  const T = a0 + 4.4;
  btn("⟳ " + S.b4, 172, 466, 250, k0);
  if (t > T - 1) cursor(...path(t, [[T - 1, 700, 600], [T, 300, 486]]), { click: seg(t, T, T + 0.5), alpha: seg(t, T - 1, T - 0.6) * (1 - seg(t, T + 1.2, T + 1.7)) });
  const kd = outCubic(seg(t, T + 0.8, T + 1.4));
  text(S.done, 440, 491, { size: 14, color: "#9aa09c", alpha: kd });
  const kl = outBack(seg(t, a1 + 0.2, a1 + 0.8));
  if (kl > 0) pill(S.local, 640, 568, { size: 15, align: "center", alpha: clamp(kl) });
}

/* ------------------------------ 05 · la synchronisation lit, n'écrit jamais ------------------------------ */
function sSync(t, d, cues) {
  head(S.k5, S.h5, t);
  const a0 = at(cues, 0, 0.6);
  const k0 = outCubic(seg(t, 0.3, 0.9));
  // le cycle
  const cx = 200, cy = 330;
  ctx.save(); ctx.globalAlpha *= k0; ctx.translate(cx, cy); ctx.rotate(t * 0.9);
  ctx.beginPath(); ctx.arc(0, 0, 54, 0.3, Math.PI * 1.7); ctx.strokeStyle = PURPLE; ctx.lineWidth = 7; ctx.lineCap = "round"; ctx.stroke(); ctx.restore();
  text(S.srcs, cx, 430, { size: 13, font: MONO, color: C.faint, align: "center", alpha: k0 });
  // lit
  panel(340, 176, 300, 260, { r: 18, alpha: k0 });
  label(S.rT.toUpperCase(), 364, 210, k0, C.teal);
  S.reads.forEach((s, i) => { const k = outCubic(seg(t, a0 + 0.6 + i * 0.4, a0 + 1.0 + i * 0.4)); check(374, 246 + i * 46, 10, C.teal, k, k); text(s, 396, 252 + i * 46, { size: 17, weight: 600, alpha: k }); });
  // refusés
  const kw = outCubic(seg(t, a0 + 3.0, a0 + 3.6));
  panel(680, 176, 520, 260, { r: 18, fill: "rgba(240,122,95,0.05)", stroke: C.red, alpha: kw });
  label(S.wT.toUpperCase(), 704, 210, kw, C.red);
  S.writes.forEach((s, i) => {
    const k = outCubic(seg(t, a0 + 3.4 + i * 0.35, a0 + 3.8 + i * 0.35)), x = 704 + (i % 2) * 250, y = 246 + Math.floor(i / 2) * 50;
    cross(x + 8, y, 6, C.red, k);
    text(s, x + 24, y + 5, { size: 14, font: MONO, color: C.soft, alpha: k });
  });
  // un mécanisme par assistant
  S.how.forEach(([n, how], i) => {
    const k = outCubic(seg(t, a0 + 6.0 + i * 0.4, a0 + 6.5 + i * 0.4)), x = 80 + i * 284;
    panel(x, 470, 268, 80, { r: 14, alpha: k });
    text(n, x + 20, 502, { size: 15, weight: 700, alpha: k });
    text(how, x + 20, 530, { size: 13, font: MONO, color: C.amber, alpha: k });
  });
}

/* ------------------------------ 06 · la pesée ------------------------------ */
function sWeight(t, d, cues) {
  head(S.k6, S.h6, t);
  const a0 = at(cues, 0, 0.6), a1 = at(cues, 1, 6);
  const k0 = outCubic(seg(t, 0.3, 0.9));
  // la balance
  panel(80, 180, 260, 200, { r: 30, fill: "#e9ece9", stroke: false, alpha: k0, shadow: true });
  panel(130, 214, 160, 60, { r: 10, fill: "#0a120e", stroke: false, alpha: k0 });
  const kv = seg(t, a0 + 0.6, a0 + 1.6);
  text(kv < 1 ? (60 + 2 * kv).toFixed(1).replace(".", S.dec) + " kg" : S.scale, 210, 254, { size: 24, weight: 700, font: MONO, color: C.accent, align: "center", alpha: k0 });
  text(S.when, 210, 410, { size: 12, font: MONO, color: C.faint, align: "center", alpha: k0 });
  // vers le fichier santé du jour
  const ka = seg(t, a0 + 2.0, a0 + 3.0);
  arrow(360, 280, 470, 280, ka, C.accent);
  const lines = [{ s: '"weight_kg": 62.0,', c: C.ink, a: a0 + 3.0 }, { s: '"weight_origin": "garmin"', c: C.accent, a: a0 + 3.5 }];
  terminal(490, 196, 400, 150, t, lines, { alpha: outCubic(seg(t, a0 + 2.8, a0 + 3.3)), size: 15, lh: 32, title: S.file });
  const kr = outBack(seg(t, a0 + 4.4, a0 + 5.0));
  if (kr > 0) pill(S.ro, 920, 270, { size: 15, alpha: clamp(kr) });
  // les règles
  S.rules.forEach(([a, b], i) => {
    const k = outCubic(seg(t, a1 + (i === 0 ? 0.2 : i === 1 ? 2.6 : 5.6), a1 + (i === 0 ? 0.7 : i === 1 ? 3.1 : 6.1))), y = 430 + i * 58;
    if (k <= 0) return;
    panel(80, y, 1120, 48, { r: 12, alpha: k });
    text(a, 104, y + 31, { size: 16, weight: 700, alpha: k });
    text(b, 1176, y + 31, { size: 15, color: C.soft, align: "right", alpha: k });
  });
  text(S.nw, 640, 412, { size: 12, font: MONO, color: C.red, align: "center", alpha: outCubic(seg(t, a1 - 1.0, a1 - 0.4)) });
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
  n: 18, slug: "sans-terminal",
  strings: STR,
  shots: [],
  scenes: { install: sInstall, assistant: sAssistant, data: sData, home: sHome, sync: sSync, weight: sWeight, pages: sPages },
});
})();
