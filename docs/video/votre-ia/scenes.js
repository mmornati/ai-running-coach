/* Le Sentier · étape 25 — « Votre IA, votre forfait » : l'abonnement ChatGPT ou GitHub Copilot que l'on
 * paie déjà (#266) — `install.sh --llm chatgpt|copilot`, connexion unique `arc_llm.py login`, magasin
 * d'authentification dédié (mode 700), coût « inclus dans votre forfait » — le choix explicite de la
 * synchronisation (--sync-subscription / --no-sync-subscription), `arc_llm.py sync` (la synchronisation
 * seule, #265) et le diagnostic `arc_llm.py check [--probe]` / « Tester la connexion » (#268).
 * Libellés et messages : docs/choisir-son-ia.md, docs/troubleshooting.md (« La connexion IA »), install.sh
 * (persist_llm_subscription), scripts/arc_llm.py (translate_subscription_error), arc_llm_check.py.
 * Moteur : ../engine/engine.js (helpers globaux). Découpage et narration : script.json.
 * Athlète fictive (bible de la série : Camille, mardi 29 septembre 2026). */
"use strict";
(() => {
const BLUE = "#6ea6e3", PURPLE = "#b39ddb";
const STR = {
  fr: {
    k1: "01 · VOTRE FORFAIT", h1: "Un forfait déjà payé, c'est une IA déjà payée.",
    me: "Camille", pays: "paie déjà", planName: "ChatGPT Plus",
    plansH: ["Forfait", "Accepté ?"],
    plans: [["ChatGPT Plus / Pro", true, ""], ["ChatGPT Free", false, "usage_not_included"],
      ["Copilot Pro / Pro+", true, ""], ["Copilot Business / Enterprise", true, ""], ["Copilot Free", false, "non pris en charge"]],
    k2: "02 · UNE OPTION", h2: "À l'installation, une option. Une connexion.",
    cmdA: "./install.sh --llm chatgpt", altA: "ou  --llm copilot", cmdB: "python3 scripts/arc_llm.py login chatgpt",
    pillsB: ["à faire vous-même", "dans un terminal", "jamais en tâche de fond"],
    k3: "03 · UN COFFRE À PART", h3: "La connexion reste à part, et gratuite à l'usage.",
    store: "~/.local/share/ai-running-coach/opencode", storeSub: "magasin d'authentification dédié au coach",
    pillsS: ["mode 700", "hors du dépôt", "jetons jamais lus"], perso: "votre OpenCode personnel : intact",
    counter: "Compteur du chat", included: "inclus dans votre forfait ChatGPT", limits: "seules les limites du forfait comptent",
    k4: "04 · LA SYNCHRONISATION", h4: "Le chat, oui. La synchro, vous décidez.",
    rowsS: [["installation neuve", "synchro sur le forfait", true], ["installation existante", "garde son exécuteur actuel", false],
      ["--sync-subscription", "la met aussi sur le forfait", true], ["--no-sync-subscription", "jamais, même sur une installation neuve", false]],
    whyS: "Aucune déclaration officielle n'autorise l'usage planifié, sans surveillance, d'un forfait grand public.",
    k5: "05 · SYNCHRO SEULE", h5: "Changer l'IA de la synchro, pas du chat.",
    colsC: ["Commande", "La synchro tourne sur"],
    rowsC: [["sync anthropic", "Claude Code + API Anthropic"], ["sync openrouter", "OpenCode + OpenRouter"], ["sync openrouter-free", "OpenCode + modèle gratuit"],
      ["sync openai", "OpenCode + API compatible OpenAI"], ["sync claude-subscription", "retour à l'abonnement Claude"]],
    haiku: "modèle par défaut : claude-haiku-5-5", perTok: "payé au jeton, clé dans llm.env",
    chatKept: "Chat : inchangé", noReinstall: "aucune réinstallation",
    k6: "06 · LE DIAGNOSTIC", h6: "Un doute ? Testez la connexion.",
    btnMac: "Tester la connexion", btnWeb: "Tester la connexion", appLab: "Application macOS", webLab: "Page du chat",
    termA: "python3 scripts/arc_llm.py check", termB: "python3 scripts/arc_llm.py check --probe",
    outA: ["✅ Connexion ChatGPT présente dans le magasin du coach", "   (jetons non affichés)."], netA: "réseau : aucun",
    outB: ["→ un appel minimal par fournisseur"], netB: "réseau : seulement avec --probe",
    fixes: "chaque ligne : la commande qui corrige",
    k7: "07 · JETON EXPIRÉ", h7: "Le message dit quoi faire. Rien ne se reconnecte seul.",
    chatErr: "Connexion ChatGPT expirée ou refusée : reconnectez-vous avec « python3 scripts/arc_llm.py login chatgpt ».",
    chatLab: "Chat", testLab: "Tester la connexion", syncLab: "Notification de la synchro",
    testMsg: "même message, même commande", notif: "🔑 Sync Garmin — reconnectez ChatGPT",
    never: "jamais de connexion automatique", noBrowser: "aucun navigateur ouvert",
  },
  en: {
    k1: "01 · YOUR PLAN", h1: "A plan you already pay for is an AI you already pay for.",
    me: "Camille", pays: "already pays for", planName: "ChatGPT Plus",
    plansH: ["Plan", "Accepted?"],
    plans: [["ChatGPT Plus / Pro", true, ""], ["ChatGPT Free", false, "usage_not_included"],
      ["Copilot Pro / Pro+", true, ""], ["Copilot Business / Enterprise", true, ""], ["Copilot Free", false, "not supported"]],
    k2: "02 · ONE OPTION", h2: "One install option. One sign-in.",
    cmdA: "./install.sh --llm chatgpt", altA: "or  --llm copilot", cmdB: "python3 scripts/arc_llm.py login chatgpt",
    pillsB: ["do it yourself", "in a terminal", "never in the background"],
    k3: "03 · A VAULT OF ITS OWN", h3: "The sign-in stays apart, and costs nothing per use.",
    store: "~/.local/share/ai-running-coach/opencode", storeSub: "authentication store dedicated to the coach",
    pillsS: ["mode 700", "outside the repo", "tokens never read"], perso: "your personal OpenCode: untouched",
    counter: "Chat counter", included: "included in your ChatGPT plan", limits: "only your plan's limits count",
    k4: "04 · THE SYNC", h4: "The chat, yes. The sync is your call.",
    rowsS: [["fresh install", "sync on the plan", true], ["existing install", "keeps its current runner", false],
      ["--sync-subscription", "puts it on the plan too", true], ["--no-sync-subscription", "never, even on a fresh install", false]],
    whyS: "No official statement allows scheduled, unattended use of a consumer plan.",
    k5: "05 · SYNC ONLY", h5: "Change the sync's AI, not the chat's.",
    colsC: ["Command", "The sync runs on"],
    rowsC: [["sync anthropic", "Claude Code + Anthropic API"], ["sync openrouter", "OpenCode + OpenRouter"], ["sync openrouter-free", "OpenCode + free model"],
      ["sync openai", "OpenCode + OpenAI-compatible API"], ["sync claude-subscription", "back to the Claude plan"]],
    haiku: "default model: claude-haiku-5-5", perTok: "paid per token, key in llm.env",
    chatKept: "Chat: unchanged", noReinstall: "no reinstall",
    k6: "06 · DIAGNOSIS", h6: "In doubt? Test the connection.",
    btnMac: "Test the connection", btnWeb: "Test the connection", appLab: "macOS app", webLab: "Chat page",
    termA: "python3 scripts/arc_llm.py check", termB: "python3 scripts/arc_llm.py check --probe",
    outA: ["✅ ChatGPT sign-in present in the coach's store", "   (tokens not shown)."], netA: "network: none",
    outB: ["→ one minimal call per provider"], netB: "network: only with --probe",
    fixes: "every line: the command that fixes it",
    k7: "07 · EXPIRED TOKEN", h7: "The message says what to do. Nothing signs in by itself.",
    chatErr: "ChatGPT sign-in expired or refused: sign in again with “python3 scripts/arc_llm.py login chatgpt”.",
    chatLab: "Chat", testLab: "Test the connection", syncLab: "Sync notification",
    testMsg: "same message, same command", notif: "🔑 Garmin sync — reconnect ChatGPT",
    never: "never an automatic sign-in", noBrowser: "no browser opened",
  },
};

/* ------------------------------- dessins locaux ------------------------------- */
const nolig = s => s.replace(/=(?=[=>])/g, "= ").replace(/--/g, "- -");
function head(k, h, t) { kicker(k, seg(t, 0, 0.4)); headline(h, seg(t, 0.1, 0.7), 132, 36); fictTag(seg(t, 0.3, 0.8)); }
function label(s, x, y, k, col = C.accent) { text(s, x, y, { size: 12, weight: 600, font: MONO, color: col, alpha: k, spacing: "2px" }); }
function btn(s, x, y, w, k, o = {}) {
  panel(x, y, w, 38, { r: 9, fill: o.primary ? "#0a84ff" : "#3a3d3b", stroke: false, alpha: k });
  text(s, x + w / 2, y + 25, { size: 14, weight: 600, color: "#fff", align: "center", alpha: k });
}
function cross(x, y, s, col, alpha = 1) {
  line([[x - s, y - s], [x + s, y + s]], col, 3, alpha); line([[x + s, y - s], [x - s, y + s]], col, 3, alpha);
}

/* ------------------------------ 01 · le forfait ------------------------------ */
function sPlans(t, d, cues) {
  head(S.k1, S.h1, t);
  const a0 = at(cues, 0, 0.6), a1 = at(cues, 1, 5);
  const kq = outBack(seg(t, a0 + 0.3, a0 + 0.9));
  if (kq > 0) {
    panel(80, 220, 330, 230, { r: 20, fill: C.pine, stroke: C.accent, lw: 2, alpha: clamp(kq), shadow: true });
    text(S.me, 245, 280, { size: 26, weight: 800, font: SORA, align: "center", alpha: clamp(kq) });
    text(S.pays, 245, 312, { size: 15, color: C.soft, align: "center", alpha: clamp(kq) });
    pill(S.planName, 245, 372, { size: 20, align: "center", alpha: clamp(kq), padX: 22, color: C.deep, fill: C.accent, stroke: C.accent });
    text("✓", 245, 428, { size: 22, weight: 800, color: C.accent, align: "center", alpha: clamp(kq) });
  }
  const kp = outCubic(seg(t, a1 - 0.4, a1 + 0.2));
  panel(470, 190, 730, 380, { r: 18, alpha: kp });
  label(S.plansH[0].toUpperCase(), 500, 224, kp, C.faint);
  label(S.plansH[1].toUpperCase(), 940, 224, kp, C.faint);
  line([[490, 238], [1180, 238]], C.line, 1, kp);
  S.plans.forEach(([n, ok, why], i) => {
    const a = a1 + 0.3 + i * 0.55, k = outCubic(seg(t, a, a + 0.5)), y = 284 + i * 56;
    if (!ok) highlight(486, y - 28, 698, 44, seg(t, a + 0.3, a + 0.8) * 0.8, C.red);
    text(n, 500, y, { size: 19, weight: 700, font: SORA, alpha: k, color: ok ? C.ink : C.soft });
    if (ok) check(965, y - 6, 12, C.accent, k); else cross(965, y - 6, 9, C.red, k);
    if (why) text(why, 1180, y, { size: 13, font: MONO, color: C.red, align: "right", alpha: k });
  });
}

/* ------------------------------ 02 · une option, une connexion ------------------------------ */
function sInstall(t, d, cues) {
  head(S.k2, S.h2, t);
  const a0 = at(cues, 0, 0.6), a1 = at(cues, 1, 6);
  const size = 20, lh = 46, tx = 80, ty = 190;
  const lines = [
    { p: "$ ", s: nolig(S.cmdA), c: C.accent, w: 700, a: a0 + 0.4, b: a0 + 2.2 },
    { p: "$ ", s: nolig(S.cmdB), c: C.accent, w: 700, a: a1 + 0.3, b: a1 + 2.4 },
  ];
  terminal(tx, ty, 1120, 200, t, lines, { alpha: outCubic(seg(t, 0.3, 0.9)), size, lh, title: "bash" });
  const x0 = tx + 22 + measure("$ ", size, 400, MONO);
  const ka = outCubic(seg(t, a0 + 2.4, a0 + 3.0));
  if (ka > 0) text(nolig(S.altA), x0 + measure(nolig(S.cmdA), size, 700, MONO) + 30, ty + 62 + 0 * lh, { size: 17, font: MONO, color: C.soft, alpha: ka });
  let px = 80;
  S.pillsB.forEach((s, i) => {
    const k = outBack(seg(t, a1 + 2.6 + i * 0.7, a1 + 3.1 + i * 0.7)), red = i === 2;
    if (k > 0) pill(s, px, 470, { size: 17, alpha: clamp(k), padX: 20, color: red ? C.amber : C.accent,
      fill: red ? "rgba(240,180,60,0.08)" : undefined, stroke: red ? "rgba(240,180,60,0.45)" : undefined });
    px += measure(s, 17, 600, MONO) + 40 + 18;
  });
}

/* ------------------------------ 03 · le magasin dédié ------------------------------ */
function sStore(t, d, cues) {
  head(S.k3, S.h3, t);
  const a0 = at(cues, 0, 0.6), a1 = at(cues, 1, 6);
  const k0 = outCubic(seg(t, a0 + 0.3, a0 + 0.9));
  panel(80, 190, 640, 300, { r: 18, alpha: k0 });
  // le dossier
  ctx.save(); ctx.globalAlpha *= k0; rr(110, 228, 70, 54, 8); ctx.fillStyle = C.pine; ctx.fill(); ctx.strokeStyle = C.accent; ctx.lineWidth = 2; ctx.stroke(); ctx.restore();
  text(S.store, 200, 252, { size: 16, weight: 700, font: MONO, color: C.accent, alpha: k0 });
  text(S.storeSub, 200, 278, { size: 14, color: C.soft, alpha: k0 });
  text("auth.json", 132, 336, { size: 16, font: MONO, alpha: k0 });
  let px = 110;
  S.pillsS.forEach((s, i) => {
    const k = outBack(seg(t, a0 + 2.6 + i * 0.7, a0 + 3.1 + i * 0.7));
    if (k > 0) pill(s, px, 404, { size: 14, alpha: clamp(k), padX: 16 });
    px += measure(s, 14, 600, MONO) + 32 + 14;
  });
  const kp = outCubic(seg(t, a0 + 6, a0 + 6.6));
  text(S.perso, 110, 462, { size: 15, color: C.soft, alpha: kp });
  // le compteur du chat
  const kc = outBack(seg(t, a1 + 0.3, a1 + 0.9));
  if (kc > 0) {
    panel(760, 190, 440, 300, { r: 18, alpha: clamp(kc), shadow: true });
    label(S.counter.toUpperCase(), 788, 228, clamp(kc), C.faint);
    text("0 €", 980, 340, { size: 22, weight: 800, font: SORA, color: C.faint, align: "center", alpha: clamp(kc) * 0 });
    pill(S.included, 980, 330, { size: 17, align: "center", alpha: clamp(kc), padX: 22, color: C.deep, fill: C.accent, stroke: C.accent });
    para(S.limits, 788, 410, 380, { size: 16, color: C.soft, alpha: seg(t, a1 + 2, a1 + 2.6) });
  }
}

/* ------------------------------ 04 · la synchronisation, un choix ------------------------------ */
function sSync(t, d, cues) {
  head(S.k4, S.h4, t);
  const a0 = at(cues, 0, 0.6), a1 = at(cues, 1, 6);
  const k0 = outCubic(seg(t, 0.3, 0.9));
  panel(80, 178, 1120, 292, { r: 18, alpha: k0 });
  S.rowsS.forEach(([when, what, yes], i) => {
    const a = a0 + 0.8 + i * 1.3, k = outCubic(seg(t, a, a + 0.5)), y = 226 + i * 64;
    const flag = i >= 2;
    text(nolig(when), 112, y, { size: 19, weight: 700, font: flag ? MONO : SORA, color: flag ? C.accent : C.ink, alpha: k });
    line([[480, y - 6], [530, y - 6]], C.line, 2, k);
    text(what, 560, y, { size: 18, color: C.ink, alpha: k });
    if (yes) check(1150, y - 6, 12, C.accent, k); else cross(1150, y - 6, 9, i === 3 ? C.red : C.amber, k);
  });
  const kw = outCubic(seg(t, a1 + 0.2, a1 + 0.8));
  if (kw > 0) {
    panel(80, 500, 1120, 80, { r: 16, fill: "rgba(240,180,60,0.07)", stroke: C.amber, lw: 2, alpha: kw });
    para(S.whyS, 112, 548, 1060, { size: 20, weight: 600, font: SORA, alpha: kw });
  }
}

/* ------------------------------ 05 · la synchro seule ------------------------------ */
function sSwitch(t, d, cues) {
  head(S.k5, S.h5, t);
  const a0 = at(cues, 0, 0.6), a1 = at(cues, 1, 6);
  const k0 = outCubic(seg(t, 0.3, 0.9));
  panel(80, 176, 760, 390, { r: 18, alpha: k0 });
  label(S.colsC[0].toUpperCase(), 108, 210, k0, C.faint); label(S.colsC[1].toUpperCase(), 420, 210, k0, C.faint);
  line([[100, 226], [820, 226]], C.line, 1, k0);
  S.rowsC.forEach(([c, r], i) => {
    const a = a0 + 1.2 + i * 0.45, k = outCubic(seg(t, a, a + 0.4)), y = 270 + i * 58;
    if (i === 0) highlight(96, y - 28, 728, 44, seg(t, a1 + 0.2, a1 + 0.8), C.accent);
    text(nolig(c), 108, y, { size: 16, weight: 700, font: MONO, color: i === 0 ? C.accent : C.ink, alpha: k });
    text(r, 420, y, { size: 16, color: C.soft, alpha: k });
  });
  // à droite : le chat ne bouge pas
  const kc = outBack(seg(t, a0 + 3.4, a0 + 4.0));
  if (kc > 0) {
    panel(880, 176, 320, 120, { r: 16, fill: "rgba(163,230,53,0.07)", stroke: C.accent, alpha: clamp(kc) });
    check(914, 226, 14, C.accent, clamp(kc));
    text(S.chatKept, 944, 232, { size: 20, weight: 700, font: SORA, alpha: clamp(kc) });
    text(S.noReinstall, 944, 262, { size: 14, color: C.soft, alpha: clamp(kc) });
  }
  const kh = outBack(seg(t, a1 + 1.0, a1 + 1.6));
  if (kh > 0) {
    panel(880, 320, 320, 130, { r: 16, alpha: clamp(kh) });
    text("Haiku", 910, 368, { size: 28, weight: 800, font: SORA, color: PURPLE, alpha: clamp(kh) });
    text(S.haiku, 910, 402, { size: 13, font: MONO, color: C.soft, alpha: clamp(kh) });
    text(S.perTok, 910, 428, { size: 13, color: C.soft, alpha: clamp(kh) });
  }
}

/* ------------------------------ 06 · le diagnostic ------------------------------ */
function sCheck(t, d, cues) {
  head(S.k6, S.h6, t);
  const a0 = at(cues, 0, 0.6), a1 = at(cues, 1, 6);
  const k0 = outCubic(seg(t, 0.3, 0.9));
  // deux boutons
  panel(80, 176, 430, 130, { r: 14, fill: "#1b1d1c", stroke: "#3a3d3b", alpha: k0 });
  text(S.appLab, 104, 212, { size: 13, color: "#9aa09c", alpha: k0 });
  const press = seg(t, a0 + 3.0, a0 + 3.4) * (1 - seg(t, a0 + 3.6, a0 + 4.0));
  btn(S.btnMac, 104, 232, 220, k0, { primary: press > 0.5 });
  panel(80, 330, 430, 130, { r: 14, fill: "#f4f5f4", stroke: false, alpha: k0 });
  text(S.webLab, 104, 366, { size: 13, color: "#6b736f", alpha: k0 });
  panel(104, 386, 220, 38, { r: 9, fill: "#fff", stroke: "#cfd4d1", alpha: k0 });
  text(S.btnWeb, 214, 411, { size: 14, weight: 600, color: "#1c2b24", align: "center", alpha: k0 });
  // le terminal
  const lines = [
    { p: "$ ", s: nolig(S.termA), c: C.accent, w: 700, a: a1 + 0.1, b: a1 + 1.0 },
    { s: S.outA[0], c: C.ink, a: a1 + 1.3 }, { s: S.outA[1], c: C.soft, a: a1 + 1.3 },
    { p: "$ ", s: nolig(S.termB), c: C.accent, w: 700, a: a1 + 2.6, b: a1 + 3.6 },
    { s: S.outB[0], c: C.ink, a: a1 + 3.9 },
  ];
  terminal(550, 176, 650, 284, t, lines, { alpha: k0, size: 14, lh: 30, title: "bash" });
  const kn = outBack(seg(t, a1 + 1.6, a1 + 2.1)), kn2 = outBack(seg(t, a1 + 4.1, a1 + 4.6));
  if (kn > 0) pill(S.netA, 560, 500, { size: 15, alpha: clamp(kn) * (1 - seg(t, a1 + 2.6, a1 + 3.0)), padX: 18 });
  if (kn2 > 0) pill(S.netB, 560, 500, { size: 15, alpha: clamp(kn2), padX: 18, color: C.amber, fill: "rgba(240,180,60,0.08)", stroke: "rgba(240,180,60,0.45)" });
  const kf = outBack(seg(t, a1 + 4.8, a1 + 5.4));
  if (kf > 0) pill(S.fixes, 80, 520, { size: 16, alpha: clamp(kf), padX: 20 });
}

/* ------------------------------ 07 · le jeton expiré ------------------------------ */
function sExpired(t, d, cues) {
  head(S.k7, S.h7, t);
  const a0 = at(cues, 0, 0.6), a1 = at(cues, 1, 5);
  const k0 = outCubic(seg(t, 0.3, 0.9));
  const card = (x, y, w, lab, k, col) => {
    panel(x, y, w, 128, { r: 16, fill: "rgba(240,122,95,0.07)", stroke: col, lw: 2, alpha: k });
    label(lab.toUpperCase(), x + 22, y + 30, k, col);
  };
  const k1 = outCubic(seg(t, a0 + 0.5, a0 + 1.1));
  card(80, 180, 1120, S.chatLab, k1, C.red);
  para(S.chatErr, 102, 250, 1070, { size: 19, font: MONO, alpha: k1 });
  const k2 = outCubic(seg(t, a0 + 2.6, a0 + 3.2));
  card(80, 330, 540, S.testLab, k2, C.amber);
  para(S.chatErr, 102, 392, 500, { size: 12, font: MONO, color: C.soft, alpha: k2 });
  const k3 = outCubic(seg(t, a0 + 3.8, a0 + 4.4));
  card(660, 330, 540, S.syncLab, k3, C.amber);
  text(S.notif, 682, 390, { size: 18, weight: 700, alpha: k3 });
  text("python3 scripts/arc_llm.py login chatgpt", 682, 424, { size: 14, font: MONO, color: C.accent, alpha: k3 });
  const kt = outBack(seg(t, a0 + 4.6, a0 + 5.2));
  if (kt > 0) pill(S.testMsg, 80, 506, { size: 15, alpha: clamp(kt), padX: 18, color: C.soft, fill: C.deep, stroke: C.line });
  const kn = outBack(seg(t, a1 + 0.6, a1 + 1.2));
  if (kn > 0) {
    const w = pill(S.never, 80, 566, { size: 18, alpha: clamp(kn), padX: 22 });
    pill(S.noBrowser, 80 + w + 24, 566, { size: 18, alpha: clamp(kn), padX: 22, color: C.amber, fill: "rgba(240,180,60,0.08)", stroke: "rgba(240,180,60,0.45)" });
  }
}

ARC.episode({
  n: 25, slug: "votre-ia",
  strings: STR,
  shots: [],
  scenes: { plans: sPlans, install: sInstall, store: sStore, sync: sSync, switch: sSwitch, check: sCheck, expired: sExpired },
});
})();
