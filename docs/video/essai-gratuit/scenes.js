/* Le Sentier · étape 21 — « Zéro euro pour démarrer » : choisir son IA (#264), puis l'essai gratuit
 * OpenRouter (#267) — `install.sh --llm openrouter-free --connect`, connexion OAuth sans clé à copier
 * (#265), le même choix dans l'application macOS, le quota (50 requêtes/jour, requêtes mesurées par
 * demande), la confidentialité des modèles gratuits, et « 10 $ une fois ».
 * Chiffres, libellés et messages : docs/choisir-son-ia.md, install.sh (persist_llm_free_trial),
 * scripts/arc_llm.py (connect, free_quota_text) et macos/AI-Running-Coach/AI_Running_CoachApp.swift.
 * Moteur : ../engine/engine.js (helpers globaux). Découpage et narration : script.json.
 * Athlète, clé et compteurs fictifs (bible de la série : Camille, mardi 29 septembre 2026). */
"use strict";
(() => {
const BLUE = "#6ea6e3", PURPLE = "#b39ddb";
const STR = {
  fr: {
    k1: "01 · QUE PAYEZ-VOUS DÉJÀ ?", h1: "Pas une technologie : ce que vous avez déjà.",
    q: ["Que payez-vous", "déjà ?"],
    rows: [
      ["Claude Pro / Max", "Claude Code + Remote Control", "aucun coût en plus"],
      ["ChatGPT Plus / Pro", "Se connecter avec ChatGPT", "inclus dans le forfait"],
      ["GitHub Copilot", "Se connecter avec GitHub", "crédits du forfait"],
      ["Rien", "OpenRouter en un clic", "≈ 1 € / mois"],
    ],
    free: "Essai gratuit · 0 €",
    k2: "02 · UNE OPTION", h2: "Trois lignes, une option.",
    cmds: ["git clone https://github.com/mmornati/ai-running-coach.git", "cd ai-running-coach", "./install.sh --llm openrouter-free --connect"],
    c1: "l'essai gratuit", c2: "connexion dans le navigateur",
    out: [["==> ", "Essai gratuit OpenRouter : modèle nvidia/nemotron-3-ultra-550b-a55b:free"], ["    ", "— 0 € (aucun budget en euros)."]],
    noCap: "0 € · aucun plafond à régler",
    k3: "03 · UN CLIC", h3: "Aucune clé à créer ni à copier.",
    url: "openrouter.ai/auth?callback_url=http://127.0.0.1:…",
    asks: "AI Running Coach", asks2: "demande l'accès à votre compte OpenRouter", allow: "Autoriser", deny: "Refuser",
    acct: "camille@example.com",
    term: [
      "Une page OpenRouter s'ouvre dans votre navigateur :", "autorisez le coach.", "Échange du code avec OpenRouter…",
      "Clé enregistrée dans", "  ~/.config/ai-running-coach/llm.env (mode 600).", "OpenRouter connecté (clé « sk-or-v1-0c4…7e2 »,",
      "  modèles gratuits : 50 requête(s) restante(s)", "  aujourd'hui sur 50).",
    ],
    keyPills: ["mode 600 · hors du dépôt", "jamais affichée", "vérifiée"],
    k4: "04 · SANS TERMINAL", h4: "Le même essai, dans l'application.",
    win: "6. Comment parler au coach",
    mode: ["Chat intégré dans l'application", "Mon assistant IA habituel"],
    prov: ["OpenRouter", "Essai gratuit", "ChatGPT Plus/Pro", "GitHub Copilot"],
    acc: ["Connecter OpenRouter", "J'ai déjà une clé"],
    note: "Ce chat utilise un modèle gratuit d'OpenRouter : 0 €, aucun plafond en euros.",
    note2: "Une page OpenRouter s'ouvre : créez un compte ou connectez-vous, puis autorisez le coach.",
    labP: "Fournisseur", labA: "OpenRouter", same: "même connexion en un clic", btn: "Installer mon coach",
    k5: "05 · LE QUOTA", h5: "Zéro euro, cinquante requêtes par jour.",
    gauge: "requêtes gratuites par jour", perMin: "20 par minute · remis à zéro chaque jour (UTC)",
    asks5: [["/log", 17, 48], ["/week", 6, 12], ["bilan matinal", 4, 9]], meas: "requêtes LLM par demande (mesuré)",
    oneTool: "1 appel d'outil = 1 requête",
    day: "≈ un /log + quelques questions",
    watch: "sync : mode watch", watchN: "l'IA ne travaille que si Garmin a du neuf",
    k6: "06 · LE REVERS", h6: "Gratuit, mais pas confidentiel.",
    cols: ["Modèle gratuit", "Fournisseur", "Entraîne", "Conserve"],
    models: [["nemotron-3-ultra (défaut)", "NVIDIA", "oui", "oui"], ["nemotron-3-super", "NVIDIA", "oui", "oui"], ["gemma-4-31b-it", "Google AI Studio", "non", "55 jours"]],
    src: "pages de modèles OpenRouter, 15 octobre 2026 — à revérifier",
    sends: ["HRV", "sommeil", "blessures"], warn: "Pas de données de santé sensibles sur l'essai gratuit.",
    k7: "07 · DIX DOLLARS, UNE FOIS", h7: "10 $ une fois ≈ un an de coaching.",
    credit: "crédit OpenRouter", once: "une seule fois",
    months: ["oct.", "nov.", "déc.", "janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept."],
    perMonth: "≈ 0,80 € / mois · mesuré avec DeepSeek", switchCmd: "./install.sh --llm openrouter",
    thou: " ", qBefore: "sans achat", qAfter: "après 10 $ achetés", qUnit: "requêtes gratuites / jour",
  },
  en: {
    k1: "01 · WHAT DO YOU ALREADY PAY FOR?", h1: "Not a technology: what you already have.",
    q: ["What do you", "already pay for?"],
    rows: [
      ["Claude Pro / Max", "Claude Code + Remote Control", "no extra cost"],
      ["ChatGPT Plus / Pro", "Sign in with ChatGPT", "included in the plan"],
      ["GitHub Copilot", "Sign in with GitHub", "plan credits"],
      ["Nothing", "OpenRouter in one click", "≈ €1 / month"],
    ],
    free: "Free trial · €0",
    k2: "02 · ONE OPTION", h2: "Three lines, one option.",
    cmds: ["git clone https://github.com/mmornati/ai-running-coach.git", "cd ai-running-coach", "./install.sh --llm openrouter-free --connect"],
    c1: "the free trial", c2: "sign-in in the browser",
    out: [["==> ", "OpenRouter free trial: model nvidia/nemotron-3-ultra-550b-a55b:free"], ["    ", "— €0 (no euro budget)."]],
    noCap: "€0 · no spending cap to set",
    k3: "03 · ONE CLICK", h3: "No key to create or copy.",
    url: "openrouter.ai/auth?callback_url=http://127.0.0.1:…",
    asks: "AI Running Coach", asks2: "requests access to your OpenRouter account", allow: "Authorize", deny: "Deny",
    acct: "camille@example.com",
    term: [
      "An OpenRouter page opens in your browser:", "authorize the coach.", "Exchanging the code with OpenRouter…",
      "Key saved in", "  ~/.config/ai-running-coach/llm.env (mode 600).", "OpenRouter connected (key “sk-or-v1-0c4…7e2”,",
      "  free models: 50 request(s) left", "  today out of 50).",
    ],
    keyPills: ["mode 600 · outside the repo", "never shown", "checked"],
    k4: "04 · NO TERMINAL", h4: "The same trial, in the app.",
    win: "6. How to talk to the coach",
    mode: ["Chat built into the app", "My usual AI assistant"],
    prov: ["OpenRouter", "Free trial", "ChatGPT Plus/Pro", "GitHub Copilot"],
    acc: ["Connect OpenRouter", "I already have a key"],
    note: "This chat uses a free OpenRouter model: €0, no euro cap.",
    note2: "An OpenRouter page opens: create an account or sign in, then authorize the coach.",
    labP: "Provider", labA: "OpenRouter", same: "same one-click connection", btn: "Install my coach",
    k5: "05 · THE QUOTA", h5: "Zero euros, fifty requests a day.",
    gauge: "free requests a day", perMin: "20 a minute · reset every day (UTC)",
    asks5: [["/log", 17, 48], ["/week", 6, 12], ["morning check", 4, 9]], meas: "LLM requests per ask (measured)",
    oneTool: "1 tool call = 1 request",
    day: "≈ one /log + a few questions",
    watch: "sync: watch mode", watchN: "the AI only works when Garmin has something new",
    k6: "06 · THE CATCH", h6: "Free, but not private.",
    cols: ["Free model", "Provider", "Trains", "Keeps"],
    models: [["nemotron-3-ultra (default)", "NVIDIA", "yes", "yes"], ["nemotron-3-super", "NVIDIA", "yes", "yes"], ["gemma-4-31b-it", "Google AI Studio", "no", "55 days"]],
    src: "OpenRouter model pages, October 15, 2026 — check again",
    sends: ["HRV", "sleep", "injuries"], warn: "No sensitive health data on the free trial.",
    k7: "07 · TEN DOLLARS, ONCE", h7: "$10 once ≈ a year of coaching.",
    credit: "OpenRouter credit", once: "just once",
    months: ["Oct", "Nov", "Dec", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep"],
    perMonth: "≈ €0.80 / month · measured with DeepSeek", switchCmd: "./install.sh --llm openrouter",
    thou: ",", qBefore: "no purchase", qAfter: "after $10 bought", qUnit: "free requests / day",
  },
};

/* ------------------------------- dessins locaux ------------------------------- */
/* JetBrains Mono lie « ==> » en flèche (le canvas ignore l'antiliant U+200C) : une espace ultrafine (U+200A) l'en empêche. */
const nolig = s => s.replace(/=(?=[=>])/g, "=\u200A");
function head(k, h, t) { kicker(k, seg(t, 0, 0.4)); headline(h, seg(t, 0.1, 0.7), 132, 40); fictTag(seg(t, 0.3, 0.8)); }
function label(s, x, y, k, col = C.accent) { text(s, x, y, { size: 12, weight: 600, font: MONO, color: col, alpha: k, spacing: "2px" }); }
function macWin(x, y, w, h, title, k) {
  panel(x, y, w, h, { r: 14, fill: "#1b1d1c", stroke: "#3a3d3b", alpha: k, shadow: true });
  ctx.save(); ctx.globalAlpha *= k; rr(x, y, w, 30, [14, 14, 0, 0]); ctx.fillStyle = "#2a2d2b"; ctx.fill(); ctx.restore();
  ["#ff5f57", "#febc2e", "#28c840"].forEach((c, i) => dot(x + 18 + i * 18, y + 15, 6, c, k));
  if (title) text(title, x + w / 2, y + 20, { size: 13, weight: 600, color: "#c9cdca", align: "center", alpha: k });
}
/* Contrôle segmenté macOS ; sel = position (fractionnaire pendant le glissement). */
function segmented(opts, x, y, w, sel, k) {
  const n = opts.length, cw = (w - 8) / n;
  panel(x, y, w, 34, { r: 9, fill: "#2a2d2b", stroke: false, alpha: k });
  panel(x + 4 + sel * cw, y + 4, cw, 26, { r: 7, fill: "#4a4e4b", stroke: false, alpha: k });
  opts.forEach((s, i) => text(s, x + 4 + cw * (i + 0.5), y + 22, { size: 13, weight: 600, color: "#fff", align: "center", alpha: k }));
}
function btn(s, x, y, w, k, o = {}) {
  panel(x, y, w, 38, { r: 9, fill: o.primary ? "#0a84ff" : "#3a3d3b", stroke: false, alpha: k });
  text(s, x + w / 2, y + 25, { size: 14, weight: 600, color: "#fff", align: "center", alpha: k });
}
function path(t, pts) {
  if (t <= pts[0][0]) return [pts[0][1], pts[0][2]];
  for (let i = 1; i < pts.length; i++) {
    if (t <= pts[i][0]) { const k = inOut(seg(t, pts[i - 1][0], pts[i][0])); return [lerp(pts[i - 1][1], pts[i][1], k), lerp(pts[i - 1][2], pts[i][2], k)]; }
  }
  const p = pts[pts.length - 1]; return [p[1], p[2]];
}
function cross(x, y, s, col, alpha = 1) {
  line([[x - s, y - s], [x + s, y + s]], col, 3, alpha); line([[x + s, y - s], [x - s, y + s]], col, 3, alpha);
}

/* ------------------------------ 01 · l'arbre de décision ------------------------------ */
function sQuestion(t, d, cues) {
  head(S.k1, S.h1, t);
  const a0 = at(cues, 0, 0.6), a1 = at(cues, 1, 6), e1 = atEnd(cues, 1, 10);
  // la question
  const kq = outBack(seg(t, a0 + 0.4, a0 + 1.0));
  if (kq > 0) {
    panel(80, 290, 290, 130, { r: 20, fill: C.pine, stroke: C.accent, lw: 2, alpha: clamp(kq), shadow: true });
    S.q.forEach((s, i) => text(s, 225, 346 + i * 34, { size: 24, weight: 800, font: SORA, align: "center", alpha: clamp(kq) }));
  }
  // les réponses
  S.rows.forEach(([who, what, cost], i) => {
    const a = i < 3 ? a1 + 0.3 + i * 0.7 : a1 + 3.6, k = outCubic(seg(t, a, a + 0.5)), y = 184 + i * 102;
    if (k <= 0) return;
    const last = i === 3;
    line(partial([[370, 355], [400, 355], [400, y + 42], [440, y + 42]], k), last ? C.accent : C.line, 2);
    panel(440 + (1 - k) * 20, y, 760, 84, { r: 16, fill: last ? "rgba(163,230,53,0.07)" : C.panel, stroke: last ? C.accent : C.line, lw: last ? 2 : 1, alpha: k });
    text(who, 468, y + 38, { size: 21, weight: 800, font: SORA, alpha: k });
    text("→ " + what, 468, y + 66, { size: 15, color: C.soft, alpha: k });
    pill(cost, 1176, y + 42, { align: "right", size: 13, alpha: k, color: last ? C.amber : C.accent,
      fill: last ? "rgba(240,180,60,0.08)" : undefined, stroke: last ? "rgba(240,180,60,0.45)" : undefined });
  });
  // l'essai gratuit, à côté d'OpenRouter
  const kf = outBack(seg(t, e1 - 1.6, e1 - 1.0));
  if (kf > 0) {
    const fx = 468 + measure("→ " + S.rows[3][1], 15) + 18, fy = 184 + 3 * 102 + 61;
    const fw = pill(S.free, fx, fy, { size: 14, alpha: clamp(kf), color: C.deep, fill: C.accent, stroke: C.accent, padX: 16 });
    highlight(fx, fy - 15, fw, 30, seg(t, e1 - 1.0, e1 - 0.4));
  }
}

/* ------------------------------ 02 · trois lignes, une option ------------------------------ */
function sInstall(t, d, cues) {
  head(S.k2, S.h2, t);
  const a0 = at(cues, 0, 0.6), a1 = at(cues, 1, 6);
  const ts = [a0 + 0.3, a0 + 1.6, a0 + 2.4], dur = [1.1, 0.6, 1.6];
  const size = 19, lh = 42, tx = 80, ty = 176;
  const lines = S.cmds.map((s, i) => ({ p: "$ ", s: nolig(s), c: i === 2 ? C.accent : C.ink, w: i === 2 ? 700 : 400, a: ts[i], b: ts[i] + dur[i] }));
  S.out.forEach(([p, s], i) => lines.push({ s: nolig(p + s), c: C.soft, a: a1 + 0.3 + i * 0.3 }));
  terminal(tx, ty, 1120, 290, t, lines, { alpha: outCubic(seg(t, 0.3, 0.9)), size, lh, title: "bash" });
  // callouts sur les deux options de la troisième ligne
  const x0 = tx + 22 + measure("$ ", size, 400, MONO), y3 = ty + 62 + 2 * lh - size * 0.4;
  const pre = "./install.sh ", f1 = "--llm openrouter-free", f2 = "--connect";
  const x1 = x0 + measure(pre, size, 700, MONO), w1 = measure(f1, size, 700, MONO);
  const x2 = x1 + w1 + measure(" ", size, 700, MONO), w2 = measure(f2, size, 700, MONO);
  const kc = seg(t, ts[2] + dur[2], ts[2] + dur[2] + 0.6);
  const ko = 1 - seg(t, a1, a1 + 0.4);
  callout(S.c1, x1 + w1 / 2, 520, x1 + w1 / 2, y3 + 14, kc * ko, { size: 16 });
  callout(S.c2, x2 + w2 / 2 + 120, 520, x2 + w2 / 2, y3 + 14, seg(t, ts[2] + dur[2] + 0.5, ts[2] + dur[2] + 1.1) * ko, { size: 16 });
  const kn = outBack(seg(t, a1 + 1.4, a1 + 2.0));
  if (kn > 0) pill(S.noCap, 640, 590, { size: 18, align: "center", alpha: clamp(kn), padX: 22 });
}

/* ------------------------------ 03 · la connexion en un clic ------------------------------ */
function sConnect(t, d, cues) {
  head(S.k3, S.h3, t);
  const a0 = at(cues, 0, 0.6), a1 = at(cues, 1, 7), e1 = atEnd(cues, 1, 13);
  const kb = outCubic(seg(t, a0 + 0.2, a0 + 0.8));
  // le navigateur
  panel(80, 176, 570, 420, { r: 14, fill: "#f4f5f4", stroke: false, alpha: kb, shadow: true });
  ctx.save(); ctx.globalAlpha *= kb; rr(80, 176, 570, 44, [14, 14, 0, 0]); ctx.fillStyle = "#dfe2e0"; ctx.fill(); ctx.restore();
  ["#ff5f57", "#febc2e", "#28c840"].forEach((c, i) => dot(100 + i * 18, 198, 6, c, kb));
  panel(160, 186, 474, 24, { r: 12, fill: "#fff", stroke: false, alpha: kb });
  text(S.url, 174, 203, { size: 11, font: MONO, color: "#5b625e", alpha: kb });
  text("OpenRouter", 365, 270, { size: 26, weight: 800, font: SORA, color: "#1c2b24", align: "center", alpha: kb });
  text(S.acct, 365, 296, { size: 13, color: "#6b736f", align: "center", alpha: kb });
  panel(120, 318, 490, 130, { r: 14, fill: "#fff", stroke: "#d6dad7", alpha: kb });
  panel(144, 342, 56, 56, { r: 12, fill: C.pine, stroke: false, alpha: kb });
  logo(172, 370, 0.5, kb);
  text(S.asks, 218, 364, { size: 18, weight: 700, color: "#1c2b24", alpha: kb });
  para(S.asks2, 218, 388, 370, { size: 14, color: "#4a524e", alpha: kb });
  const T = a0 + 3.0, clicked = t >= T;
  panel(370, 480, 220, 44, { r: 10, fill: clicked ? "#16a34a" : "#1c2b24", stroke: false, alpha: kb });
  text(clicked ? "✓ " + S.allow : S.allow, 480, 508, { size: 16, weight: 700, color: "#fff", align: "center", alpha: kb });
  panel(140, 480, 200, 44, { r: 10, fill: "#fff", stroke: "#cfd4d1", alpha: kb });
  text(S.deny, 240, 508, { size: 16, weight: 600, color: "#4a524e", align: "center", alpha: kb });
  if (t > T - 1.2) cursor(...path(t, [[T - 1.2, 620, 600], [T, 470, 506]]), { click: seg(t, T, T + 0.5), alpha: seg(t, T - 1.2, T - 0.8) * (1 - seg(t, T + 1.2, T + 1.7)) });
  // le terminal, en face
  const m = S.term;
  const lines = [
    { s: m[0], c: C.soft, a: a0 + 0.9 }, { s: m[1], c: C.soft, a: a0 + 0.9 },
    { s: m[2], c: C.faint, a: T + 0.6 },
    { s: m[3], c: C.ink, a: a1 + 0.2 }, { s: m[4], c: C.accent, a: a1 + 0.2 },
    { s: m[5], c: C.ink, a: e1 - 3.4 }, { s: m[6], c: C.ink, a: e1 - 3.4 }, { s: m[7], c: C.ink, a: e1 - 3.4 },
  ];
  terminal(680, 176, 520, 330, t, lines, { alpha: kb, size: 13, lh: 30, title: "bash" });
  // la clé : où, et ce qui ne lui arrive jamais
  let px = 690;
  S.keyPills.forEach((s, i) => {
    const k = outBack(seg(t, a1 + 1.0 + i * 0.7, a1 + 1.5 + i * 0.7)), lab = (i === 2 ? "✓ " : "") + s;
    if (k > 0) pill(lab, px, 556, { size: 13, alpha: clamp(k), color: i === 1 ? C.amber : C.accent,
      fill: i === 1 ? "rgba(240,180,60,0.08)" : undefined, stroke: i === 1 ? "rgba(240,180,60,0.45)" : undefined });
    px += measure(lab, 13, 600, MONO) + 28 + 16;
  });
}

/* ------------------------------ 04 · le même essai dans l'application ------------------------------ */
function sApp(t, d, cues) {
  head(S.k4, S.h4, t);
  const a0 = at(cues, 0, 0.6), e0 = atEnd(cues, 0, 6);
  const k0 = outCubic(seg(t, 0.3, 0.9));
  macWin(80, 168, 820, 460, S.win, k0);
  segmented(S.mode, 110, 216, 760, 0, k0);
  text(S.labP, 110, 282, { size: 13, color: "#9aa09c", alpha: k0 });
  const sel = inOut(seg(t, a0 + 2.2, a0 + 2.8));
  segmented(S.prov, 110, 292, 760, sel, k0);
  const kf = outCubic(seg(t, a0 + 2.8, a0 + 3.4));
  if (kf > 0) {
    para(S.note, 110, 360, 760, { size: 14, color: "#9aa09c", alpha: kf });
    text(S.labA, 110, 404, { size: 13, color: "#9aa09c", alpha: kf });
    segmented(S.acc, 110, 414, 500, 0, kf);
    para(S.note2, 110, 480, 760, { size: 14, color: "#9aa09c", alpha: kf });
  }
  const kb = outCubic(seg(t, a0 + 4.2, a0 + 4.8));
  btn(S.btn, 700, 566, 170, kb, { primary: true });
  // le rappel : c'est la même connexion que la ligne de commande
  const ks = outBack(seg(t, e0 - 1.6, e0 - 1.0));
  if (ks > 0) {
    highlight(110, 414, 250, 34, seg(t, e0 - 1.6, e0 - 1.0));
    panel(940, 330, 260, 130, { r: 18, alpha: clamp(ks) });
    check(976, 372, 14, C.accent, clamp(ks));
    para(S.same, 1000, 378, 180, { size: 17, weight: 700, alpha: clamp(ks) });
    text(nolig("--connect"), 976, 436, { size: 15, font: MONO, color: C.accent, alpha: clamp(ks) });
  }
}

/* ------------------------------ 05 · le quota ------------------------------ */
function sQuota(t, d, cues) {
  head(S.k5, S.h5, t);
  const a0 = at(cues, 0, 0.6), a1 = at(cues, 1, 7);
  const k0 = outCubic(seg(t, 0.3, 0.9));
  // la jauge : 50 cases
  panel(80, 176, 470, 300, { r: 18, alpha: k0 });
  label(S.gauge.toUpperCase(), 104, 210, k0);
  const fill = [30, 6, 6]; // un /log, deux questions : une journée type
  const cols = [C.accent, BLUE, PURPLE];
  for (let i = 0; i < 50; i++) {
    const cx = 104 + (i % 10) * 42, cy = 232 + Math.floor(i / 10) * 42;
    const ki = outBack(seg(t, a0 + 0.6 + i * 0.03, a0 + 0.9 + i * 0.03));
    let col = "#22302a", used = 0, acc = 0;
    for (let j = 0; j < 3; j++) { if (i >= acc && i < acc + fill[j]) { used = j + 1; break; } acc += fill[j]; }
    if (used) {
      const ka = a1 + 0.4 + (used - 1) * 1.0 + (i - acc) * 0.025;
      if (t >= ka) col = cols[used - 1];
    }
    if (ki > 0) panel(cx, cy, 34, 34, { r: 7, fill: col, stroke: false, alpha: clamp(ki) * k0 });
  }
  text("50", 520, 210, { size: 22, weight: 800, font: SORA, color: C.accent, align: "right", alpha: k0 });
  text(S.perMin, 104, 456, { size: 12, font: MONO, color: C.faint, alpha: k0 });
  // ce que coûte chaque demande (échelle 0..50)
  const kx = outCubic(seg(t, a0 + 2.6, a0 + 3.2));
  panel(590, 176, 610, 300, { r: 18, alpha: kx });
  label(S.meas.toUpperCase(), 614, 210, kx, C.amber);
  const bx = 770, bw = 360, sx = v => bx + bw * v / 50;
  line([[bx, 418], [bx + bw, 418]], C.line, 1, kx);
  [0, 25, 50].forEach(v => text(String(v), sx(v), 440, { size: 12, font: MONO, color: C.faint, align: "center", alpha: kx }));
  S.asks5.forEach(([n, lo, hi], i) => {
    const a = a0 + 3.0 + i * 0.6, k = outCubic(seg(t, a, a + 0.6)), y = 252 + i * 54;
    text(n, 614, y + 6, { size: 17, weight: 700, font: i < 2 ? MONO : INTER, alpha: kx });
    panel(sx(0), y - 10, sx(hi * k) - sx(0), 22, { r: 6, fill: i === 0 ? "rgba(240,180,60,0.18)" : "rgba(163,230,53,0.12)", stroke: false, alpha: kx });
    panel(sx(lo * k), y - 10, sx(hi * k) - sx(lo * k), 22, { r: 6, fill: i === 0 ? C.amber : C.accent, stroke: false, alpha: kx });
    text(`${lo}–${hi}`, sx(hi * k) + 10, y + 6, { size: 14, font: MONO, color: C.soft, alpha: k });
  });
  const kt = outBack(seg(t, a0 + 5.0, a0 + 5.6));
  if (kt > 0) pill(S.oneTool, 1176, 210 - 4, { align: "right", size: 12, alpha: clamp(kt), color: C.soft, fill: C.deep, stroke: C.line });
  // une journée type, puis la sync en mode watch
  const kd = outBack(seg(t, a1 + 2.6, a1 + 3.2));
  if (kd > 0) pill(S.day, 80, 532, { size: 17, alpha: clamp(kd), padX: 20 });
  const kw = outCubic(seg(t, a1 + 4.4, a1 + 5.0));
  if (kw > 0) {
    panel(590, 500, 610, 64, { r: 16, fill: "rgba(179,157,219,0.08)", stroke: PURPLE, alpha: kw });
    ctx.save(); ctx.globalAlpha *= kw; ctx.translate(626, 532); ctx.rotate(t * 1.2);
    ctx.beginPath(); ctx.arc(0, 0, 12, 0.3, Math.PI * 1.7); ctx.strokeStyle = PURPLE; ctx.lineWidth = 3.5; ctx.lineCap = "round"; ctx.stroke(); ctx.restore();
    text(S.watch, 656, 528, { size: 16, weight: 700, font: MONO, color: PURPLE, alpha: kw });
    text(S.watchN, 656, 550, { size: 13, color: C.soft, alpha: kw });
  }
}

/* ------------------------------ 06 · la confidentialité ------------------------------ */
function sPrivacy(t, d, cues) {
  head(S.k6, S.h6, t);
  const a0 = at(cues, 0, 0.6), a1 = at(cues, 1, 6);
  const k0 = outCubic(seg(t, 0.3, 0.9));
  const xs = [104, 470, 760, 940];
  panel(80, 176, 1120, 236, { r: 18, alpha: k0 });
  S.cols.forEach((s, i) => label(s.toUpperCase(), xs[i], 210, k0, C.faint));
  line([[100, 226], [1180, 226]], C.line, 1, k0);
  S.models.forEach(([m, p, tr, keep], i) => {
    const a = a0 + 0.8 + i * 0.9, k = outCubic(seg(t, a, a + 0.5)), y = 268 + i * 50;
    const bad = tr !== S.models[2][2];
    if (i === 0) highlight(96, y - 28, 1088, 42, seg(t, a0 + 3.4, a0 + 4.0) * (1 - seg(t, a1 + 0.2, a1 + 0.8)), C.red);
    text(m, xs[0], y, { size: 16, weight: i === 0 ? 700 : 400, font: MONO, alpha: k });
    text(p, xs[1], y, { size: 16, color: C.soft, alpha: k });
    text(tr, xs[2], y, { size: 16, weight: 700, color: bad ? C.red : C.teal, alpha: k });
    text(keep, xs[3], y, { size: 16, weight: 700, color: C.amber, alpha: k });
  });
  text(S.src, 1176, 400, { size: 11, font: MONO, color: C.faint, align: "right", alpha: k0 });
  // ce que le coach envoie
  let sx = 80;
  S.sends.forEach((s, i) => {
    const a = a1 + 0.6 + i * 0.6, k = outBack(seg(t, a, a + 0.5));
    if (k > 0) pill(s, sx, 466, { size: 16, font: INTER, alpha: clamp(k), color: C.ink, fill: C.panel2, stroke: C.line, padX: 18 });
    sx += measure(s, 16, 600, INTER) + 36 + 14;
  });
  const kw = outCubic(seg(t, a1 + 2.6, a1 + 3.2));
  if (kw > 0) {
    panel(80, 508, 1120, 70, { r: 16, fill: "rgba(240,122,95,0.07)", stroke: C.red, lw: 2, alpha: kw });
    ctx.save(); ctx.globalAlpha *= kw; ctx.beginPath(); ctx.moveTo(122, 528); ctx.lineTo(140, 560); ctx.lineTo(104, 560); ctx.closePath();
    ctx.fillStyle = C.red; ctx.fill(); ctx.restore();
    text("!", 122, 556, { size: 18, weight: 800, color: C.deep, align: "center", alpha: kw });
    text(S.warn, 164, 551, { size: 21, weight: 700, font: SORA, alpha: kw });
  }
}

/* ------------------------------ 07 · dix dollars, une fois ------------------------------ */
function sUpgrade(t, d, cues) {
  head(S.k7, S.h7, t);
  const a0 = at(cues, 0, 0.6), a1 = at(cues, 1, 6);
  const k0 = outCubic(seg(t, 0.3, 0.9));
  // le ticket de crédit
  const kc = outBack(seg(t, a0 + 0.4, a0 + 1.0));
  if (kc > 0) {
    panel(80, 186, 280, 170, { r: 20, fill: C.pine, stroke: C.accent, lw: 2, alpha: clamp(kc), shadow: true });
    text("10 $", 220, 280, { size: 64, weight: 800, font: SORA, color: C.accent, align: "center", alpha: clamp(kc) });
    text(S.credit, 220, 314, { size: 14, color: C.soft, align: "center", alpha: clamp(kc) });
    text(S.once.toUpperCase(), 220, 340, { size: 12, weight: 600, font: MONO, color: C.amber, align: "center", alpha: clamp(kc), spacing: "2px" });
  }
  // douze mois à ≈ 0,80 €
  const mx = 410, mw = 790;
  panel(mx, 186, mw, 170, { r: 18, alpha: k0 });
  S.months.forEach((s, i) => {
    const a = a0 + 1.6 + i * 0.22, k = outCubic(seg(t, a, a + 0.4)), x = mx + 24 + i * 63;
    panel(x, 290 - 64 * k, 46, 64 * k, { r: 6, fill: C.accent, stroke: false, alpha: 0.85 * k0 });
    text(s, x + 23, 316, { size: 12, font: MONO, color: C.faint, align: "center", alpha: k0 });
  });
  text(S.perMonth, mx + 24, 214, { size: 13, font: MONO, color: C.soft, alpha: outCubic(seg(t, a0 + 4.0, a0 + 4.6)) });
  text(nolig(S.switchCmd), mx + mw - 24, 344, { size: 13, font: MONO, color: C.accent, align: "right", alpha: outCubic(seg(t, a0 + 4.6, a0 + 5.2)) });
  // le quota gratuit : 50 → 1000
  const kq = outCubic(seg(t, a1 + 0.2, a1 + 0.8));
  const qx = 280, qw = 820, sx = v => qw * v / 1000;
  label(S.qUnit.toUpperCase(), 80, 412, kq, C.faint);
  [[S.qBefore, 50, C.soft, a1 + 0.4], [S.qAfter, 1000, C.accent, a1 + 1.6]].forEach(([n, v, col, a], i) => {
    const k = inOut(seg(t, a, a + 1.4)), y = 446 + i * 60;
    text(n, 80, y + 22, { size: 16, weight: 700, alpha: kq });
    panel(qx, y, Math.max(6, sx(v * k)), 32, { r: 8, fill: col, stroke: false, alpha: kq });
    text(String(Math.round(v * k)).replace(/\B(?=(\d{3})+(?!\d))/g, S.thou), qx + Math.max(6, sx(v * k)) + 12, y + 24, { size: 18, weight: 800, font: MONO, color: col, alpha: kq * seg(t, a, a + 0.3) });
  });
}

ARC.episode({
  n: 21, slug: "essai-gratuit",
  strings: STR,
  shots: [],
  scenes: { question: sQuestion, install: sInstall, connect: sConnect, app: sApp, quota: sQuota, privacy: sPrivacy, upgrade: sUpgrade },
});
})();
