/* Le Sentier · étape 13 — « Nouvelles portes d'entrée » : Strava comme troisième source de données,
 * retours en un geste par Telegram (sans modèle), contexte du cycle et apports poussés vers Garmin
 * (deux options à activer soi-même).
 * Moteur : ../engine/engine.js (helpers globaux). Découpage et narration : script.json.
 * Chaque scène reçoit (t, d, cues) : temps local, durée, répliques [{s, e, text}] —
 * at(cues, i, repli) cale une animation sur la voix, quelle que soit la langue.
 * Athlète et chiffres fictifs (bible de la série : Camille, mardi 29 septembre 2026).
 * L'interface de messagerie est dessinée de façon générique (aucun logo ni capture d'une marque). */
"use strict";
(() => {
const STR = {
  fr: {
    k1: "01 · TROISIÈME SOURCE", h1: "Strava, à la place de Garmin.",
    src: [["Garmin", "source par défaut", "garmin"], ["intervals.icu", "facultatif", "intervals"], ["Strava", "toutes marques de montres", "strava"]],
    active: "actif",
    term: ["./install.sh --source strava", "serveur strava déclaré (version épinglée)", "[data].source = \"strava\""],
    termTitle: "installation", keep: ["Garmin ou intervals.icu : rien ne change", "Relancer l'installateur relit la source déjà choisie"],
    k2: "02 · FLUX PAR SECONDE", h2: "Les mêmes indicateurs que le FIT.",
    chartT: "flux à 1 Hz · sortie du 27 septembre", legend: ["altitude", "FC", "vitesse", "cadence"],
    kpis: ["Zones de FC", "Allure ajustée à la pente", "Découplage aérobie", "Durabilité", "Dépense d'énergie", "Vitesse ascensionnelle"],
    fileNote: "activities/fit/s…json · même format que le FIT",
    k3: "03 · SOYONS HONNÊTES", h3: "Dit explicitement, jamais simulé.",
    okT: "Disponible", okL: ["Activités et détails", "Flux par seconde", "Zones de FC de l'athlète"],
    noT: "Indisponible", noL: ["HRV", "FC de repos", "Sommeil", "Readiness", "Séances vers la montre"],
    cardT: "Bilan matinal", cardL: ["HRV : indisponible — source Strava", "FC de repos : indisponible", "Readiness : indisponible"],
    plan: "Planifié sur", planL: "charge · historique · ressenti déclaré", medical: "Une séance annulée pour raison médicale reste annulée.",
    k4: "04 · UN GESTE", h4: "Un appui, un fichier écrit.",
    chatHead: "Coach · résumé du matin", chatSub: "bot Telegram · liste blanche",
    msg: ["Séances : à jour", "Charge : modérée", "Bilan : indisponible (Strava)", "Séance du jour : EF 45 min", "Alerte : aucune"],
    btn1: ["Faite", "Pas faite", "Décalée"], btnRpe: "RPE", btnPain: "Douleur",
    tokens: "jetons dépensés", noKey: "aucune clé d'API · 0 €",
    cards: [["planning/2026-09-28_semaine.md", "status: \"done\""], ["activities/2026-09-29_trail.md", "\"rpe\": 7"], ["medical/2026-09-29_health.md", "pain : zone → score /10 → note"]],
    written: "écrit", same: "Même logique que /log · un second appui n'écrit rien de plus",
    k5: "05 · SANS SURPRISE", h5: "Un bot à liste blanche.",
    painT: "Douleur", painThr: "seuil de consultation 7/10", painAdvice: "consulter un professionnel de santé", painNote: "le plan n'est jamais modifié depuis ce canal",
    wlT: "Qui peut écrire", wlOk: ["Camille · chat privé", "autorisé"], wlNo: ["chat inconnu", "ignoré en silence"],
    clear: "Pas de chiffrement de bout en bout : Telegram peut lire ces messages.",
    lvT: "Deux niveaux", lv1: ["1 · Boutons", "aucun modèle · gratuit"], lv2: ["2 · Conversation libre", "option · clé d'API, plafond quotidien"],
    poll: "Aucune adresse publique : le bot interroge Telegram depuis votre machine.",
    k6: "06 · OPTION · LE CYCLE", h6: "Un contexte, jamais une règle.",
    cfg: "[health].cycle_tracking", modes: ["off", "garmin", "intervals", "manual"], dflt: "défaut", offNote: "aucune donnée · aucune mention", onNote: "contexte seulement",
    mcT: "Bilan matinal", mcL: ["HRV : 41 ms — basse (baseline 52-70)", "FC de repos : stable"], ctx: "contexte : phase lutéale, jour 22", mcEnd: "pas un motif d'annuler à elle seule : on recontrôle demain",
    neverT: "Ce que le cycle ne fait jamais", never: ["Pas une règle : aucun seuil n'en dépend", "Pas un diagnostic", "Ne relâche jamais un verdict rouge"],
    k7: "07 · OPTION · LES APPORTS", h7: "Le coach propose, vous dites oui.",
    cfg2: "[nutrition].garmin_sync = \"ask\"", logLine: "/log 2 gels + 500 ml",
    planT: "arc_nutrition_sync.py plan", planS: "le script décide",
    askT: "Pousser vers Garmin ?", askL: ["2 × Gel Crête citron", "500 ml d'eau"], yes: "oui", no: "non",
    steps: ["aliment personnalisé (créé une fois)", "journal alimentaire : 2 portions", "hydratation : + 500 ml", "trace garmin_pushed"],
    nHead: "jamais en headless", nStrava: "indisponible avec Strava",
    k8: "08 · LES PAGES", h8: "Une page par porte.",
    pages: [["Configuration Strava", "source de données, flux, limites d'API", "strava-setup"], ["Le bot Telegram", "boutons, liste blanche, confidentialité", "telegram"], ["Cycle menstruel", "option, contexte seulement", "cycle-menstruel"], ["Apports vers Garmin", "option, oui explicite", "nutrition-garmin"]],
  },
  en: {
    k1: "01 · THIRD SOURCE", h1: "Strava, instead of Garmin.",
    src: [["Garmin", "default source", "garmin"], ["intervals.icu", "optional", "intervals"], ["Strava", "every watch brand", "strava"]],
    active: "active",
    term: ["./install.sh --source strava", "strava server declared (pinned version)", "[data].source = \"strava\""],
    termTitle: "install", keep: ["Garmin or intervals.icu: nothing changes", "Rerunning the installer reads the source already chosen"],
    k2: "02 · PER-SECOND STREAMS", h2: "The same indicators as the FIT.",
    chartT: "1 Hz streams · run of September 27", legend: ["altitude", "HR", "speed", "cadence"],
    kpis: ["HR zones", "Grade-adjusted pace", "Aerobic decoupling", "Durability", "Energy expenditure", "Climbing rate"],
    fileNote: "activities/fit/s…json · same format as the FIT",
    k3: "03 · BEING HONEST", h3: "Said out loud, never simulated.",
    okT: "Available", okL: ["Activities and details", "Per-second streams", "Athlete HR zones"],
    noT: "Unavailable", noL: ["HRV", "Resting HR", "Sleep", "Readiness", "Sessions to the watch"],
    cardT: "Morning check", cardL: ["HRV: unavailable — Strava source", "Resting HR: unavailable", "Readiness: unavailable"],
    plan: "Planned from", planL: "load · history · declared feel", medical: "A session cancelled for a medical reason stays cancelled.",
    k4: "04 · ONE TAP", h4: "One tap, one file written.",
    chatHead: "Coach · morning summary", chatSub: "Telegram bot · allow list",
    msg: ["Sessions: up to date", "Load: moderate", "Check: unavailable (Strava)", "Today: easy 45 min", "Alert: none"],
    btn1: ["Done", "Not done", "Moved"], btnRpe: "RPE", btnPain: "Pain",
    tokens: "tokens spent", noKey: "no API key · €0",
    cards: [["planning/2026-09-28_semaine.md", "status: \"done\""], ["activities/2026-09-29_trail.md", "\"rpe\": 7"], ["medical/2026-09-29_health.md", "pain: zone → score /10 → note"]],
    written: "written", same: "Same logic as /log · a second tap writes nothing more",
    k5: "05 · NO SURPRISES", h5: "A bot with an allow list.",
    painT: "Pain", painThr: "see-a-professional threshold 7/10", painAdvice: "see a health professional", painNote: "the plan is never changed from this channel",
    wlT: "Who can write", wlOk: ["Camille · private chat", "allowed"], wlNo: ["unknown chat", "silently ignored"],
    clear: "No end-to-end encryption: Telegram can read these messages.",
    lvT: "Two levels", lv1: ["1 · Buttons", "no model · free"], lv2: ["2 · Free conversation", "option · API key, daily cap"],
    poll: "No public address: the bot polls Telegram from your machine.",
    k6: "06 · OPTION · THE CYCLE", h6: "Context, never a rule.",
    cfg: "[health].cycle_tracking", modes: ["off", "garmin", "intervals", "manual"], dflt: "default", offNote: "no data · no mention", onNote: "context only",
    mcT: "Morning check", mcL: ["HRV: 41 ms — low (baseline 52-70)", "Resting HR: stable"], ctx: "context: luteal phase, day 22", mcEnd: "not a reason to cancel on its own: we recheck tomorrow",
    neverT: "What the cycle never does", never: ["Not a rule: no threshold depends on it", "Not a diagnosis", "Never relaxes a red verdict"],
    k7: "07 · OPTION · INTAKE", h7: "The coach proposes, you say yes.",
    cfg2: "[nutrition].garmin_sync = \"ask\"", logLine: "/log 2 gels + 500 ml",
    planT: "arc_nutrition_sync.py plan", planS: "the script decides",
    askT: "Push to Garmin?", askL: ["2 × Gel Crête lemon", "500 ml of water"], yes: "yes", no: "no",
    steps: ["custom food (created once)", "food log: 2 servings", "hydration: + 500 ml", "garmin_pushed trace"],
    nHead: "never headless", nStrava: "unavailable with Strava",
    k8: "08 · THE PAGES", h8: "One page per door.",
    pages: [["Strava setup", "data source, streams, API limits", "strava-setup"], ["The Telegram bot", "buttons, allow list, privacy", "telegram"], ["Menstrual cycle", "option, context only", "cycle-menstruel"], ["Intake to Garmin", "option, explicit yes", "nutrition-garmin"]],
  },
};

/* ------------------------------- dessins locaux ------------------------------- */
function cross(x, y, s, col, alpha = 1) {
  line([[x - s, y - s], [x + s, y + s]], col, 3, alpha); line([[x + s, y - s], [x - s, y + s]], col, 3, alpha);
}
/* Bouton de clavier de messagerie : renvoie son rectangle ; on = bouton choisi. */
function keyBtn(label, x, y, w, h, on, o = {}) {
  panel(x, y, w, h, { r: 9, fill: on ? C.accent : "#1d3328", stroke: on ? C.accent : "#33463b", alpha: o.alpha ?? 1 });
  text(label, x + w / 2, y + h / 2 + (o.size ?? 13) * 0.36, { size: o.size ?? 13, weight: 600, align: "center", color: on ? C.deep : C.ink, alpha: o.alpha ?? 1 });
  return [x, y, w, h];
}
/* Chemin du curseur : points [t, x, y] interpolés doucement ; hors de ces temps, il reste au bord. */
function path(t, pts) {
  if (t <= pts[0][0]) return [pts[0][1], pts[0][2]];
  for (let i = 1; i < pts.length; i++) {
    if (t <= pts[i][0]) { const k = inOut(seg(t, pts[i - 1][0], pts[i][0])); return [lerp(pts[i - 1][1], pts[i][1], k), lerp(pts[i - 1][2], pts[i][2], k)]; }
  }
  const p = pts[pts.length - 1]; return [p[1], p[2]];
}

/* ------------------------------ 01 · Strava, troisième source ------------------------------ */
function sSource(t, d, cues) {
  kicker(S.k1, seg(t, 0, 0.4)); headline(S.h1, seg(t, 0.1, 0.7)); fictTag(seg(t, 0.3, 0.8));
  const a0 = at(cues, 0, 0.6), a1 = at(cues, 1, 6);
  const sw = seg(t, a0 + 3.4, a0 + 4.0);
  S.src.forEach(([name, sub, key], i) => {
    const k = outCubic(seg(t, 0.3 + i * 0.25, 0.9 + i * 0.25)), x = 80 + i * 390, y = 176 + (1 - k) * 16;
    const on = i === 2 ? sw > 0.5 : i === 0 ? sw <= 0.5 : false;
    panel(x, y, 360, 150, { r: 18, fill: on ? "rgba(163,230,53,0.08)" : C.panel, stroke: on ? C.accent : C.line, lw: on ? 2 : 1, alpha: k });
    text(name, x + 26, y + 54, { size: 28, weight: 800, font: SORA, color: on ? C.ink : C.soft, alpha: k });
    text(sub, x + 26, y + 84, { size: 14, color: C.soft, alpha: k });
    pill(`source = "${key}"`, x + 26, y + 116, { size: 13, alpha: k, color: on ? C.accent : C.faint, fill: on ? "rgba(163,230,53,0.1)" : "rgba(125,142,133,0.08)", stroke: on ? "rgba(163,230,53,0.4)" : C.line });
    if (on) text(S.active.toUpperCase(), x + 334, y + 40, { size: 12, weight: 600, font: MONO, color: C.accent, align: "right", alpha: k, spacing: "2px" });
  });
  // la montre publie vers Strava, qui alimente le coach
  const kf = outCubic(seg(t, a0 + 3.4, a0 + 4.2));
  if (kf > 0) arrow(80 + 2 * 390 + 180, 330, 80 + 2 * 390 + 180, 366, kf, C.accent, 0.8);
  // installation
  const kt = outCubic(seg(t, a1 - 0.4, a1 + 0.2));
  const lines = [{ p: "$ ", s: S.term[0], c: C.ink, a: a1, b: a1 + 1.6 }, { s: S.term[1], c: C.teal, a: a1 + 1.9 }, { s: S.term[2], c: C.accent, a: a1 + 2.6 }];
  terminal(80, 380, 700, 190, t, lines, { alpha: kt, size: 15, lh: 34, title: S.termTitle });
  S.keep.forEach((s, i) => {
    const a = a1 + 3.0 + i * 0.7, k = outCubic(seg(t, a, a + 0.5)); if (k <= 0) return;
    const y = 392 + i * 76;
    panel(820, y + (1 - k) * 12, 380, 62, { r: 14, alpha: k });
    check(848, y + 32 + (1 - k) * 12, 14, C.teal, seg(t, a + 0.2, a + 0.7), k);
    para(s, 874, y + 28 + (1 - k) * 12, 306, { size: 14, weight: 600, alpha: k });
  });
}

/* ------------------------------ 02 · flux par seconde ------------------------------ */
function sStreams(t, d, cues) {
  kicker(S.k2, seg(t, 0, 0.4)); headline(S.h2, seg(t, 0.1, 0.7)); fictTag(seg(t, 0.3, 0.8));
  const a0 = at(cues, 0, 0.6), a1 = at(cues, 1, 6);
  const x = 80, y = 180, w = 680, h = 360, k = outCubic(seg(t, 0.3, 0.9));
  panel(x, y, w, h, { r: 18, alpha: k });
  text(S.chartT, x + 24, y + 34, { size: 13, font: MONO, color: C.faint, alpha: k });
  const px = u => x + 24 + u * (w - 48), base = y + h - 70;
  const alt = u => base - (ridge(u * 0.9 + 0.05) - 0.12) * 190;
  const hr = u => y + 150 - (0.5 + 0.28 * Math.sin(u * 9 + 1) + 0.1 * Math.sin(u * 33)) * 90;
  const sp = u => y + 160 - (0.5 + 0.22 * Math.sin(u * 7 + 3) + 0.08 * Math.sin(u * 41 + 2)) * 70;
  const cad = u => y + 118 - (0.5 + 0.1 * Math.sin(u * 17)) * 24;
  const prog = outCubic(seg(t, 0.7, a0 + 4.5));
  const N = 160, upto = Math.floor(N * prog);
  const pts = f => Array.from({ length: upto + 1 }, (_, i) => [px(i / N), f(i / N)]);
  if (upto > 1) {
    const ap = pts(alt);
    ctx.save(); ctx.globalAlpha *= k; ctx.beginPath(); ap.forEach(([X, Y], i) => i ? ctx.lineTo(X, Y) : ctx.moveTo(X, Y));
    ctx.lineTo(ap[ap.length - 1][0], base + 20); ctx.lineTo(px(0), base + 20); ctx.closePath(); ctx.fillStyle = "rgba(95,184,160,0.16)"; ctx.fill(); ctx.restore();
    line(ap, C.teal, 2.5, k);
    line(pts(hr), C.red, 2, k * 0.95); line(pts(sp), C.amber, 1.8, k * 0.9); line(pts(cad), C.soft, 1.4, k * 0.7, [4, 4]);
    const X = px(prog); line([[X, y + 60], [X, base + 20]], C.accent, 1.5, 0.5 * k); dot(X, alt(prog), 5, C.accent, k);
  }
  const lc = [C.teal, C.red, C.amber, C.soft];
  S.legend.forEach((s, i) => { const lx = x + 24 + i * 150; dot(lx, y + h - 26, 5, lc[i], k); text(s, lx + 14, y + h - 21, { size: 14, color: C.soft, alpha: k }); });
  // indicateurs dérivés
  const kh = outCubic(seg(t, a1 - 0.3, a1 + 0.4));
  text("→", 780, 360, { size: 34, weight: 800, font: SORA, color: C.accent, align: "center", alpha: kh });
  S.kpis.forEach((s, i) => {
    const a = a1 + 2.4 + i * 0.7, kk = outCubic(seg(t, a, a + 0.5)); if (kk <= 0) return;
    const yy = 184 + i * 58;
    panel(810, yy + (1 - kk) * 12, 390, 48, { r: 12, alpha: kk });
    check(836, yy + 25 + (1 - kk) * 12, 12, C.teal, seg(t, a + 0.2, a + 0.7), kk);
    text(s, 860, yy + 30 + (1 - kk) * 12, { size: 16, weight: 600, alpha: kk });
  });
  const kn = outBack(seg(t, a1 + 6.8, a1 + 7.4));
  if (kn > 0) pill(S.fileNote, 80, 586, { size: 14, alpha: clamp(kn) });
}

/* ------------------------------ 03 · ce que Strava n'a pas ------------------------------ */
function sNoHealth(t, d, cues) {
  kicker(S.k3, seg(t, 0, 0.4)); headline(S.h3, seg(t, 0.1, 0.7)); fictTag(seg(t, 0.3, 0.8));
  const a0 = at(cues, 0, 0.6), a1 = at(cues, 1, 6);
  const kl = outCubic(seg(t, 0.3, 0.9));
  text(S.okT.toUpperCase(), 80, 186, { size: 13, weight: 600, font: MONO, color: C.teal, alpha: kl, spacing: "2px" });
  S.okL.forEach((s, i) => {
    const k = outCubic(seg(t, 0.5 + i * 0.3, 1.1 + i * 0.3)), y = 204 + i * 74;
    panel(80, y + (1 - k) * 12, 330, 62, { r: 14, alpha: k });
    check(108, y + 33 + (1 - k) * 12, 13, C.teal, seg(t, 0.8 + i * 0.3, 1.3 + i * 0.3), k);
    para(s, 134, y + 38 + (1 - k) * 12, 260, { size: 16, weight: 600, alpha: k });
  });
  text(S.noT.toUpperCase(), 450, 186, { size: 13, weight: 600, font: MONO, color: C.amber, alpha: kl, spacing: "2px" });
  S.noL.forEach((s, i) => {
    const a = i < 4 ? a0 + 2.0 + i * 1.0 : a1 - 0.6, k = outCubic(seg(t, a, a + 0.5)); if (k <= 0) return;
    const y = 204 + i * 66;
    panel(450, y + (1 - k) * 12, 340, 54, { r: 14, fill: "rgba(240,180,60,0.05)", stroke: "rgba(240,180,60,0.5)", alpha: k });
    cross(478, y + 28 + (1 - k) * 12, 7, C.amber, k);
    text(s, 502, y + 33 + (1 - k) * 12, { size: 16, weight: 600, alpha: k });
  });
  // le bilan matinal le dit
  const kc = outCubic(seg(t, a1 - 0.3, a1 + 0.4));
  panel(830, 204, 370, 330, { r: 18, alpha: kc });
  text(S.cardT, 856, 242, { size: 20, weight: 700, font: SORA, alpha: kc });
  S.cardL.forEach((s, i) => { const k = seg(t, a1 + 0.3 + i * 0.5, a1 + 0.8 + i * 0.5); para(s, 856, 284 + i * 50, 320, { size: 14, font: MONO, color: C.amber, alpha: k }); });
  const kp = outCubic(seg(t, a1 + 2.2, a1 + 2.9));
  line([[856, 424], [1174, 424]], C.line, 1, kp);
  text(S.plan.toUpperCase(), 856, 452, { size: 12, weight: 600, font: MONO, color: C.faint, alpha: kp, spacing: "2px" });
  para(S.planL, 856, 480, 320, { size: 16, weight: 600, color: C.accent, alpha: kp });
  const km = outCubic(seg(t, a1 + 4.0, a1 + 4.6));
  if (km > 0) para(S.medical, 80, 596, 1000, { size: 15, color: C.soft, alpha: km });
}

/* ------------------------------ 04 · retours en un geste ------------------------------ */
function sButtons(t, d, cues) {
  kicker(S.k4, seg(t, 0, 0.4)); headline(S.h4, seg(t, 0.1, 0.7)); fictTag(seg(t, 0.3, 0.8));
  const a0 = at(cues, 0, 0.6), a1 = at(cues, 1, 6);
  const T1 = a0 + 3.4, T2 = a1 + 1.2;
  const px = 110, py = 150, pw = 330, ph = 500, kp = outCubic(seg(t, 0.3, 0.9));
  const rects = {};
  phone(px, py, pw, ph, (x, y, w, h) => {
    ctx.fillStyle = "#0a120e"; ctx.fillRect(x, y, w, h);
    ctx.fillStyle = C.panel2; ctx.fillRect(x, y, w, 86);
    dot(x + 26, y + 56, 5, C.accent); text(S.chatHead, x + 40, y + 61, { size: 14, weight: 700, font: SORA });
    text(S.chatSub, x + 40, y + 78, { size: 11, font: MONO, color: C.faint });
    // le résumé du matin
    const km = outBack(seg(t, 0.8, 1.5));
    if (km > 0) {
      panel(x + 12, y + 100 + (1 - clamp(km)) * 20, w - 24, 176, { r: 16, fill: C.panel2, alpha: clamp(km) });
      S.msg.forEach((s, i) => text(s, x + 28, y + 132 + i * 28 + (1 - clamp(km)) * 20, { size: 13, font: MONO, color: i === 4 ? C.accent : C.ink, alpha: clamp(km) }));
    }
    // les boutons sous le message
    const kb = outCubic(seg(t, 1.6, 2.2)), bx = x + 12, bw = w - 24;
    const b3 = (bw - 12) / 3, sel1 = t >= T1 + 0.25, sel2 = t >= T2 + 0.25;
    S.btn1.forEach((s, i) => { rects[`b1${i}`] = keyBtn(s, bx + i * (b3 + 6), y + 288, b3, 36, i === 0 && sel1, { alpha: kb }); });
    for (let i = 1; i <= 10; i++) { const rw = (bw - 9 * 4) / 10; rects[`r${i}`] = keyBtn(String(i), bx + (i - 1) * (rw + 4), y + 332, rw, 34, i === 7 && sel2, { alpha: kb, size: 12 }); }
    text(S.btnRpe, bx + 2, y + 384, { size: 11, font: MONO, color: C.faint, alpha: kb });
    rects.pain = keyBtn(S.btnPain, bx, y + 394, bw, 36, false, { alpha: kb });
  }, { alpha: kp });
  // le doigt : Faite, puis 7
  const f = rects.b10, s7 = rects.r7;
  if (f && s7) {
    const [cx, cy] = path(t, [[T1 - 1.2, 470, 640], [T1, f[0] + f[2] * 0.6, f[1] + f[3] * 0.6], [T1 + 0.9, f[0] + f[2] * 0.6, f[1] + f[3] * 0.6], [T2, s7[0] + s7[2] / 2, s7[1] + s7[3] * 0.6]]);
    const click = t < T2 - 0.6 ? seg(t, T1, T1 + 0.5) : seg(t, T2, T2 + 0.5);
    if (t > T1 - 1.2) cursor(cx, cy, { click, alpha: seg(t, T1 - 1.2, T1 - 0.7) * (1 - seg(t, T2 + 1.4, T2 + 2)) });
  }
  // compteur de jetons : zéro, et l'écriture se fait quand même
  const kt = outCubic(seg(t, 0.8, 1.4));
  text(S.tokens, 1200, 168, { size: 13, font: MONO, color: C.faint, align: "right", alpha: kt });
  text("0", 1200, 212, { size: 40, weight: 800, font: SORA, color: C.teal, align: "right", alpha: kt });
  text(S.noKey, 1200, 240, { size: 13, font: MONO, color: C.teal, align: "right", alpha: kt });
  S.cards.forEach(([file, val], i) => {
    const a = i === 0 ? T1 + 0.3 : i === 1 ? T2 + 0.3 : T2 + 2.2, k = outCubic(seg(t, a, a + 0.5)); if (k <= 0) return;
    const y = 262 + i * 110, last = i === 2;
    panel(500, y + (1 - k) * 14, 700, 96, { r: 16, fill: last ? "rgba(240,180,60,0.05)" : C.panel, stroke: last ? "rgba(240,180,60,0.45)" : C.line, alpha: k });
    text(file, 526, y + 36 + (1 - k) * 14, { size: 16, weight: 700, font: MONO, color: last ? C.amber : C.accent, alpha: k });
    text(val, 526, y + 70 + (1 - k) * 14, { size: 18, font: MONO, color: C.ink, alpha: k });
    if (!last) { text(S.written, 1140, y + 54 + (1 - k) * 14, { size: 14, font: MONO, color: C.teal, align: "right", alpha: k }); check(1170, y + 49 + (1 - k) * 14, 12, C.teal, seg(t, a + 0.2, a + 0.7), k); }
  });
  const ks = outBack(seg(t, T2 + 3.0, T2 + 3.6));
  if (ks > 0) pill(S.same, 500, 612, { size: 14, alpha: clamp(ks) });
}

/* ------------------------------ 05 · liste blanche et honnêteté ------------------------------ */
function sSafety(t, d, cues) {
  kicker(S.k5, seg(t, 0, 0.4)); headline(S.h5, seg(t, 0.1, 0.7)); fictTag(seg(t, 0.3, 0.8));
  const a0 = at(cues, 0, 0.6), a1 = at(cues, 1, 5.5), a2 = a1 + 3.6;
  // A · la douleur
  const ka = outCubic(seg(t, 0.3, 0.9));
  panel(80, 190, 360, 330, { r: 18, alpha: ka });
  text(S.painT, 106, 232, { size: 20, weight: 700, font: SORA, alpha: ka });
  const gx = 106, gw = 308, gy = 300, gk = outCubic(seg(t, a0 + 1.2, a0 + 3.4)), v = 7 * gk;
  rr(gx, gy, gw, 16, 8); ctx.save(); ctx.globalAlpha *= ka; ctx.fillStyle = "#0a120e"; ctx.fill(); ctx.restore();
  ctx.save(); ctx.globalAlpha *= ka; rr(gx, gy, Math.max(8, gw * v / 10), 16, 8); ctx.fillStyle = v >= 7 ? C.amber : C.teal; ctx.fill(); ctx.restore();
  line([[gx + gw * 0.7, gy - 10], [gx + gw * 0.7, gy + 26]], C.red, 2, ka);
  text(`${Math.round(v)} / 10`, gx, gy + 62, { size: 30, weight: 800, font: SORA, color: v >= 7 ? C.amber : C.ink, alpha: ka });
  text(S.painThr, gx, gy + 92, { size: 12, font: MONO, color: C.faint, alpha: ka });
  const kv = outBack(seg(t, a0 + 3.4, a0 + 4.0));
  if (kv > 0) { para(S.painAdvice, gx, gy + 128, 300, { size: 15, weight: 700, color: C.amber, alpha: clamp(kv) }); para(S.painNote, gx, gy + 168, 300, { size: 13, color: C.soft, alpha: clamp(kv) }); }
  // B · la liste blanche
  const kb = outCubic(seg(t, a1 - 0.3, a1 + 0.4));
  panel(470, 190, 360, 330, { r: 18, alpha: kb });
  text(S.wlT, 496, 232, { size: 20, weight: 700, font: SORA, alpha: kb });
  [[S.wlOk, true], [S.wlNo, false]].forEach(([[a, b], ok], i) => {
    const kk = outCubic(seg(t, a1 + 0.3 + i * 0.8, a1 + 0.9 + i * 0.8)), y = 258 + i * 74;
    panel(496, y + (1 - kk) * 10, 308, 62, { r: 12, fill: "#0a120e", stroke: ok ? "rgba(95,184,160,0.5)" : "rgba(240,122,95,0.5)", alpha: kk });
    if (ok) check(522, y + 32 + (1 - kk) * 10, 12, C.teal, kk, kk); else cross(522, y + 32 + (1 - kk) * 10, 8, C.red, kk);
    text(a, 546, y + 28 + (1 - kk) * 10, { size: 15, weight: 600, alpha: kk });
    text(b, 546, y + 50 + (1 - kk) * 10, { size: 12, font: MONO, color: ok ? C.teal : C.red, alpha: kk });
  });
  const kw = outBack(seg(t, a1 + 2.4, a1 + 3.0));
  if (kw > 0) { panel(496, 414, 308, 84, { r: 12, fill: "rgba(240,180,60,0.07)", stroke: C.amber, alpha: clamp(kw) }); para(S.clear, 512, 442, 276, { size: 13, weight: 600, color: C.amber, alpha: clamp(kw) }); }
  // C · deux niveaux
  const kc = outCubic(seg(t, 0.6, 1.2));
  panel(860, 190, 340, 330, { r: 18, alpha: kc });
  text(S.lvT, 886, 232, { size: 20, weight: 700, font: SORA, alpha: kc });
  const l2 = outCubic(seg(t, a2 - 0.2, a2 + 0.5));
  [[S.lv1, true], [S.lv2, false]].forEach(([[a, b], on1], i) => {
    const y = 258 + i * 120, lit = on1 ? 1 : l2, col = on1 ? C.accent : C.amber;
    panel(886, y, 288, 104, { r: 14, fill: "#0a120e", stroke: lit > 0.5 ? col : C.line, lw: lit > 0.5 ? 2 : 1, alpha: kc * (on1 ? 1 : 0.45 + 0.55 * lit) });
    text(a, 906, y + 40, { size: 17, weight: 700, font: SORA, color: lit > 0.5 ? col : C.soft, alpha: kc });
    para(b, 906, y + 68, 250, { size: 13, color: C.soft, alpha: kc });
  });
  const kn = outCubic(seg(t, a2 + 0.8, a2 + 1.5));
  if (kn > 0) para(S.poll, 80, 580, 1000, { size: 14, font: MONO, color: C.faint, alpha: kn });
}

/* ------------------------------ 06 · option : le cycle ------------------------------ */
function sCycle(t, d, cues) {
  kicker(S.k6, seg(t, 0, 0.4)); headline(S.h6, seg(t, 0.1, 0.7)); fictTag(seg(t, 0.3, 0.8));
  const a0 = at(cues, 0, 0.6), a1 = at(cues, 1, 8);
  const flip = outCubic(seg(t, a1 - 0.2, a1 + 0.5)), isOn = flip > 0.5;
  const kl = outCubic(seg(t, 0.3, 0.9));
  panel(80, 190, 450, 330, { r: 18, alpha: kl });
  text(S.cfg, 106, 232, { size: 16, weight: 700, font: MONO, color: C.accent, alpha: kl });
  // l'interrupteur
  const sx = 106, sy = 262;
  rr(sx, sy, 128, 56, 28); ctx.save(); ctx.globalAlpha *= kl; ctx.fillStyle = isOn ? "rgba(163,230,53,0.22)" : "#0a120e"; ctx.fill(); ctx.strokeStyle = isOn ? C.accent : "#33463b"; ctx.lineWidth = 2; ctx.stroke(); ctx.restore();
  dot(sx + 28 + 72 * flip, sy + 28, 20, isOn ? C.accent : C.faint, kl);
  text(isOn ? S.modes[3] : S.modes[0], sx + 156, sy + 38, { size: 24, weight: 700, font: MONO, color: isOn ? C.accent : C.soft, alpha: kl });
  // les quatre valeurs
  let cx = 106;
  S.modes.forEach((m, i) => {
    const cur = isOn ? i === 3 : i === 0, k = outCubic(seg(t, 0.8 + i * 0.15, 1.3 + i * 0.15));
    cx += pill(m, cx, 372, { size: 13, alpha: k, color: cur ? C.accent : C.faint, fill: cur ? "rgba(163,230,53,0.12)" : "rgba(125,142,133,0.06)", stroke: cur ? C.accent : C.line }) + 10;
  });
  para(isOn ? S.onNote : S.offNote, 106, 430, 380, { size: 18, weight: 600, color: isOn ? C.accent : C.soft, alpha: kl });
  text(`${S.dflt} : off`, 106, 480, { size: 13, font: MONO, color: C.faint, alpha: kl });
  // le bilan matinal, avec une ligne de contexte
  const km = outCubic(seg(t, a1 + 0.4, a1 + 1.1));
  panel(570, 190, 630, 212, { r: 18, alpha: km });
  text(S.mcT, 596, 228, { size: 18, weight: 700, font: SORA, alpha: km });
  S.mcL.forEach((s, i) => text(s, 596, 266 + i * 30, { size: 15, font: MONO, color: C.ink, alpha: km }));
  const kc = outBack(seg(t, a1 + 1.4, a1 + 2.0));
  if (kc > 0) pill(S.ctx, 596, 338, { size: 14, alpha: clamp(kc), color: C.amber, fill: "rgba(240,180,60,0.1)", stroke: "rgba(240,180,60,0.5)" });
  const ke = outCubic(seg(t, a1 + 2.2, a1 + 2.8));
  para(S.mcEnd, 596, 384, 580, { size: 13, color: C.soft, alpha: ke });
  // ce que le cycle ne fait jamais
  const kn = outCubic(seg(t, a1 + 3.6, a1 + 4.2));
  panel(570, 418, 630, 102, { r: 18, alpha: kn });
  text(S.neverT.toUpperCase(), 596, 442, { size: 12, weight: 600, font: MONO, color: C.red, alpha: kn, spacing: "2px" });
  S.never.forEach((s, i) => {
    const k = outCubic(seg(t, a1 + 4.0 + i * 0.5, a1 + 4.5 + i * 0.5));
    cross(606, 462 + i * 22, 5, C.red, k); text(s, 626, 467 + i * 22, { size: 14, weight: 600, alpha: k * kn });
  });
}

/* ------------------------------ 07 · option : les apports vers Garmin ------------------------------ */
function sPush(t, d, cues) {
  kicker(S.k7, seg(t, 0, 0.4)); headline(S.h7, seg(t, 0.1, 0.7)); fictTag(seg(t, 0.3, 0.8));
  const a0 = at(cues, 0, 0.6), a1 = at(cues, 1, 6);
  const k0 = outCubic(seg(t, 0.3, 0.9));
  pill(S.cfg2, 80, 176, { alpha: k0, size: 14 });
  // /log -> le script décide
  panel(80, 220, 300, 70, { r: 14, alpha: k0 });
  text(S.logLine, 104, 262, { size: 17, weight: 700, font: MONO, color: C.accent, alpha: k0 });
  const k1 = outCubic(seg(t, a0 + 2.6, a0 + 3.2));
  arrow(384, 255, 424, 255, seg(t, a0 + 2.4, a0 + 2.9), C.faint, k1);
  panel(430, 220, 310, 70, { r: 14, alpha: k1 });
  text(S.planT, 452, 248, { size: 14, weight: 700, font: MONO, alpha: k1 });
  text(S.planS, 452, 272, { size: 13, color: C.soft, alpha: k1 });
  // la proposition
  const k2 = outBack(seg(t, a1 + 0.2, a1 + 0.9));
  if (k2 > 0) {
    const kk = clamp(k2), y = 330 + (1 - kk) * 20;
    panel(80, y, 660, 190, { r: 18, fill: C.panel2, stroke: C.accent, lw: 2, alpha: kk });
    text(S.askT, 108, y + 44, { size: 22, weight: 800, font: SORA, alpha: kk });
    S.askL.forEach((s, i) => { dot(114, y + 82 + i * 30 - 5, 4, C.teal, kk); text(s, 130, y + 82 + i * 30, { size: 17, alpha: kk }); });
    const T = a1 + 2.3, pressed = t >= T + 0.2;
    keyBtn(S.yes, 108, y + 132, 120, 42, pressed, { alpha: kk, size: 16 });
    keyBtn(S.no, 244, y + 132, 120, 42, false, { alpha: kk, size: 16 });
    const [cx, cy] = path(t, [[T - 1.4, 520, 560], [T, 108 + 120 * 0.6, y + 132 + 42 * 0.6]]);
    if (t > T - 1.4) cursor(cx, cy, { click: seg(t, T, T + 0.5), alpha: seg(t, T - 1.4, T - 0.9) * (1 - seg(t, T + 1.6, T + 2.2)) });
  }
  // écrit une étape à la fois
  S.steps.forEach((s, i) => {
    const a = a1 + 3.0 + i * 0.55, k = outCubic(seg(t, a, a + 0.5)); if (k <= 0) return;
    const y = 200 + i * 74;
    panel(790, y + (1 - k) * 12, 410, 62, { r: 14, alpha: k });
    text(String(i + 1), 818, y + 38 + (1 - k) * 12, { size: 20, weight: 800, font: SORA, color: C.faint, align: "center", alpha: k });
    para(s, 846, y + 28 + (1 - k) * 12, 290, { size: 14, weight: 600, alpha: k });
    check(1166, y + 32 + (1 - k) * 12, 12, C.teal, seg(t, a + 0.3, a + 0.8), k);
  });
  // les limites
  const kn = outCubic(seg(t, a1 + 5.4, a1 + 6.0));
  pill(S.nHead, 80, 574, { size: 14, alpha: kn, color: C.amber, fill: "rgba(240,180,60,0.08)", stroke: "rgba(240,180,60,0.45)" });
  const ks = outCubic(seg(t, a1 + 6.0, a1 + 6.6));
  pill(S.nStrava, 300, 574, { size: 14, alpha: ks, color: C.amber, fill: "rgba(240,180,60,0.08)", stroke: "rgba(240,180,60,0.45)" });
}

/* ------------------------------ 08 · les pages de documentation ------------------------------ */
function sPages(t, d, cues) {
  kicker(S.k8, seg(t, 0, 0.4)); headline(S.h8, seg(t, 0.1, 0.7)); fictTag(seg(t, 0.3, 0.8));
  const a0 = at(cues, 0, 0.6);
  S.pages.forEach(([title, sub, slug], i) => {
    const a = a0 + 1.2 + i * 1.3, k = outCubic(seg(t, a, a + 0.5)), y = 184 + i * 104;
    const on = t >= a && t < a + 1.3;
    panel(80, y + (1 - k) * 14, 1120, 88, { r: 18, fill: on ? "rgba(163,230,53,0.07)" : C.panel, stroke: on ? C.accent : C.line, lw: on ? 2 : 1, alpha: k });
    text(String(i + 1).padStart(2, "0"), 124, y + 56 + (1 - k) * 14, { size: 32, weight: 800, font: SORA, color: C.accent, align: "center", alpha: k });
    text(title, 176, y + 42 + (1 - k) * 14, { size: 24, weight: 800, font: SORA, alpha: k });
    text(sub, 176, y + 68 + (1 - k) * 14, { size: 15, color: C.soft, alpha: k });
    text(`${slug}/`, 1170, y + 54 + (1 - k) * 14, { size: 17, weight: 600, font: MONO, color: C.accent, align: "right", alpha: k });
  });
}

ARC.episode({
  n: 13, slug: "sources-retours",
  strings: STR,
  shots: [],
  scenes: { source: sSource, streams: sStreams, nohealth: sNoHealth, buttons: sButtons, safety: sSafety, cycle: sCycle, push: sPush, pages: sPages },
});
})();
