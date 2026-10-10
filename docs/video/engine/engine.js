/* ==========================================================================
 * Moteur de la série vidéo « Le Sentier » (docs/video/).
 *
 * Chaque épisode = une page HTML minimale qui charge, dans l'ordre :
 *   engine/engine.js        — ce fichier : outils de dessin, lecteur, scènes communes ;
 *   ../shots/manifest.js    — captures réelles du tableau de bord (facultatif) ;
 *   <épisode>/timing.js     — GÉNÉRÉ par scripts/video_narration.py depuis script.json :
 *                             durée des scènes et répliques, par langue ;
 *   <épisode>/scenes.js     — les fonctions de dessin, puis ARC.episode({...}).
 *
 * Règle d'or (héritée de la bande-annonce) : chaque image est une fonction pure
 * du temps. render(t) redessine tout à partir de t, sans état caché ni hasard
 * non seedé : lecture, recherche et export image par image
 * (scripts/render_video.py -> window.renderFrame) donnent des images identiques.
 *
 * Les helpers sont exposés en globales (text, panel, seg, S, C…) pour que les
 * scènes restent aussi concises que celles de la bande-annonce.
 * Toutes les données montrées sont fictives (athlète « Camille »).
 * ======================================================================== */
"use strict";

(function () {
const W = 1280, H = 720;
const params = new URLSearchParams(location.search);
const RES = { "720": 1, "1080": 1.5, "1440": 2, "2160": 3 }[params.get("res") || "1080"] || 1.5;
const CAPTURE = params.has("capture");

const C = {
  bg: "#0d1410", bg2: "#0f1c16", panel: "#13201a", panel2: "#182a21", line: "#27392f",
  pine: "#1e4d3b", deep: "#0f2a1f", ink: "#e7ede9", soft: "#b8c4bd", faint: "#7d8e85",
  accent: "#a3e635", amber: "#f0b43c", red: "#f07a5f", teal: "#5fb8a0", paper: "#f6f4ef", paperInk: "#1c2b24",
};
const SORA = "Sora, Inter, sans-serif", INTER = "Inter, sans-serif", MONO = '"JetBrains Mono", monospace';

/* ------------------------------- la série --------------------------------- */
/* Ordre, titres et page de documentation associée (chemin relatif à la racine du site). */
const SERIES = [
  { n: 0, dir: "", docs: "", fr: "La bande-annonce", en: "The trailer" },
  { n: 1, dir: "ligne-de-depart", docs: "quickstart/", fr: "Ligne de départ", en: "Start line" },
  { n: 2, dir: "bilan-matinal", docs: "skills/today/", fr: "Le réveil du traileur", en: "Morning check" },
  { n: 3, dir: "garde-fous", docs: "guardrails/", fr: "Le plan qui sait dire non", en: "The plan that says no" },
  { n: 4, dir: "chat-coach", docs: "dashboard/chat/", fr: "Parler à son coach", en: "Talk to your coach" },
  { n: 5, dir: "tableau-de-bord", docs: "dashboard/views/", fr: "Tour du propriétaire", en: "Dashboard tour" },
  { n: 6, dir: "jour-de-course", docs: "agents/course-strategist/", fr: "La course, segment par segment", en: "Race day, segment by segment" },
  { n: 7, dir: "analyse-seance", docs: "skills/session-parts-analyzer/", fr: "Disséquer une sortie", en: "Anatomy of a run" },
  { n: 8, dir: "ravito", docs: "skills/log/", fr: "Ravito", en: "Fuel stop" },
  { n: 9, dir: "materiel", docs: "skills/gear-inspection/", fr: "Usure", en: "Wear and tear" },
  { n: 10, dir: "coach-poche", docs: "mobile/", fr: "Le coach dans la poche", en: "Coach in your pocket" },
  { n: 11, dir: "styles-coaching", docs: "configuration/", fr: "Trois voix, une décision", en: "Three voices, one decision" },
  { n: 12, dir: "donnees", docs: "workspace/", fr: "Vos données, votre sentier", en: "Your data, your trail" },
  { n: 13, dir: "sources-retours", docs: "strava-setup/", fr: "Nouvelles portes d'entrée", en: "New ways in" },
  { n: 14, dir: "ultra", docs: "agents/course-strategist/", fr: "La nuit, la roche et le roadbook", en: "The night, the rock and the roadbook" },
  { n: 15, dir: "bloc", docs: "plans/", fr: "Construire son bloc", en: "Building your block" },
  { n: 16, dir: "allure-juste", docs: "vitesse-critique/", fr: "L'allure juste", en: "The honest pace" },
  { n: 17, dir: "avant-apres", docs: "skills/why/", fr: "Avant, après", en: "Before and after" },
  { n: 18, dir: "sans-terminal", docs: "macos/", fr: "Sans terminal", en: "No terminal needed" },
];

const UI = {
  fr: {
    series: "Le Sentier", stage: "Étape", back: "Documentation", all: "Toutes les vidéos",
    play: "Lecture", pause: "Pause", full: "Plein écran", subs: "Sous-titres", sound: "Son",
    chapters: "Ravitos (chapitres)", seek: "Position dans la vidéo", fict: "Données d'exemple fictives",
    note: "Chaque image est dessinée en JavaScript sur un canvas, à partir du seul temps écoulé. Voix de synthèse (Kokoro, hors ligne). Espace : lecture/pause · flèches : ±5 s · <code>c</code> : sous-titres. Paramètres d'URL : <code>?lang=en</code>, <code>?t=30</code>. Athlète et données fictifs. Version MP4 : <code>scripts/render_video.py</code>.",
    missing: "Narration non générée : python3 scripts/video_narration.py",
    bibEvent: "LE SENTIER · AI-RUNNING-COACH", bibOf: "étape", gain: "D+",
    finish: "ARRIVÉE", finishSub: "Pour aller plus loin", next: "Prochaine étape",
    lastLeg: "Fin du parcours — merci d'avoir couru avec nous !", disclaimer: "Outil d'aide à la préparation sportive : il ne remplace pas un avis médical.",
  },
  en: {
    series: "The Trail", stage: "Stage", back: "Documentation", all: "All videos",
    play: "Play", pause: "Pause", full: "Fullscreen", subs: "Subtitles", sound: "Sound",
    chapters: "Aid stations (chapters)", seek: "Position in the video", fict: "Fictional sample data",
    note: "Every frame is drawn in JavaScript on a canvas from elapsed time alone. Synthetic voice (Kokoro, offline). Space: play/pause · arrows: ±5 s · <code>c</code>: subtitles. URL parameters: <code>?lang=en</code>, <code>?t=30</code>. Fictional athlete and data. MP4 version: <code>scripts/render_video.py</code>.",
    missing: "Narration not built: python3 scripts/video_narration.py",
    bibEvent: "THE TRAIL · AI-RUNNING-COACH", bibOf: "stage", gain: "gain",
    finish: "FINISH", finishSub: "Go further", next: "Next stage",
    lastLeg: "End of the trail — thanks for running with us!", disclaimer: "A training aid: it does not replace medical advice.",
  },
};

/* ------------------------------- outils ----------------------------------- */
let ctx = null;
const clamp = (v, a = 0, b = 1) => Math.min(b, Math.max(a, v));
const lerp = (a, b, k) => a + (b - a) * k;
const seg = (t, a, b) => clamp((t - a) / (b - a));
const outCubic = k => 1 - Math.pow(1 - k, 3);
const inOut = k => k < 0.5 ? 4 * k * k * k : 1 - Math.pow(-2 * k + 2, 3) / 2;
const outBack = k => { const c = 1.6; return 1 + (c + 1) * Math.pow(k - 1, 3) + c * Math.pow(k - 1, 2); };
const typed = (s, k) => s.slice(0, Math.round(s.length * clamp(k)));
const bump = (k, c, w) => Math.exp(-Math.pow((k - c) / w, 2));
/* Pseudo-aléatoire déterministe (mulberry32) : même graine, mêmes images. */
function rng(seed) {
  let a = seed >>> 0;
  return () => { a = (a + 0x6D2B79F5) >>> 0; let t = a; t = Math.imul(t ^ (t >>> 15), t | 1); t ^= t + Math.imul(t ^ (t >>> 7), t | 61); return ((t ^ (t >>> 14)) >>> 0) / 4294967296; };
}
const hash = s => { let h = 2166136261; for (const ch of s) { h ^= ch.charCodeAt(0); h = Math.imul(h, 16777619); } return h >>> 0; };
const fmt = s => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;
/* Début (temps local) de la réplique i d'une scène, ou fb si elle n'existe pas :
 * permet de caler une animation sur la voix, quelle que soit la langue. */
const at = (cues, i, fb = 0) => (cues && cues[i] ? cues[i].s : fb);
const atEnd = (cues, i, fb = 0) => (cues && cues[i] ? cues[i].e : fb);

function text(s, x, y, o = {}) {
  ctx.save();
  ctx.globalAlpha *= o.alpha ?? 1;
  ctx.font = `${o.weight ?? 400} ${o.size ?? 18}px ${o.font ?? INTER}`;
  ctx.fillStyle = o.color ?? C.ink;
  ctx.textAlign = o.align ?? "left";
  ctx.textBaseline = o.base ?? "alphabetic";
  if ("letterSpacing" in ctx) ctx.letterSpacing = o.spacing ?? "0px";
  ctx.fillText(s, x, y);
  ctx.restore();
}
function measure(s, size, weight = 400, font = INTER) {
  ctx.save(); ctx.font = `${weight} ${size}px ${font}`;
  const w = ctx.measureText(s).width; ctx.restore(); return w;
}
function wrap(s, maxW, size, weight = 400, font = INTER) {
  const words = s.split(" "), lines = []; let cur = "";
  for (const w of words) {
    const next = cur ? cur + " " + w : w;
    if (measure(next, size, weight, font) > maxW && cur) { lines.push(cur); cur = w; } else cur = next;
  }
  if (cur) lines.push(cur);
  return lines;
}
/* Paragraphe : renvoie la hauteur occupée. k (0..1) = machine à écrire. */
function para(s, x, y, maxW, o = {}) {
  const size = o.size ?? 17, lh = o.lh ?? Math.round(size * 1.45);
  const lines = wrap(s, maxW, size, o.weight ?? 400, o.font ?? INTER);
  const k = o.k ?? 1;
  lines.forEach((l, j) => text(o.k === undefined ? l : typed(l, k * lines.length - j), x, y + j * lh, o));
  return lines.length * lh;
}
function rr(x, y, w, h, r) { ctx.beginPath(); ctx.roundRect(x, y, w, h, r); }
function panel(x, y, w, h, o = {}) {
  ctx.save();
  ctx.globalAlpha *= o.alpha ?? 1;
  if (o.shadow) { ctx.shadowColor = "rgba(0,0,0,0.45)"; ctx.shadowBlur = 30; ctx.shadowOffsetY = 12; }
  rr(x, y, w, h, o.r ?? 16);
  ctx.fillStyle = o.fill ?? C.panel; ctx.fill();
  ctx.shadowColor = "transparent";
  if (o.stroke !== false) { ctx.lineWidth = o.lw ?? 1; ctx.strokeStyle = o.stroke ?? C.line; ctx.stroke(); }
  ctx.restore();
}
function dot(x, y, r, color, alpha = 1) {
  if (r <= 0) return;
  ctx.save(); ctx.globalAlpha *= alpha; ctx.beginPath(); ctx.arc(x, y, r, 0, Math.PI * 2);
  ctx.fillStyle = color; ctx.fill(); ctx.restore();
}
function ring(x, y, r, color, lw = 2, alpha = 1) {
  if (r <= 0) return;
  ctx.save(); ctx.globalAlpha *= alpha; ctx.beginPath(); ctx.arc(x, y, r, 0, Math.PI * 2);
  ctx.strokeStyle = color; ctx.lineWidth = lw; ctx.stroke(); ctx.restore();
}
function line(pts, color, lw = 2, alpha = 1, dash = null) {
  ctx.save(); ctx.globalAlpha *= alpha; ctx.beginPath();
  pts.forEach(([x, y], i) => i ? ctx.lineTo(x, y) : ctx.moveTo(x, y));
  ctx.strokeStyle = color; ctx.lineWidth = lw; ctx.lineCap = "round"; ctx.lineJoin = "round";
  if (dash) ctx.setLineDash(dash);
  ctx.stroke(); ctx.restore();
}
/* Polyligne tracée progressivement jusqu'à k (0..1) de sa longueur. */
function partial(pts, k) {
  if (k <= 0 || pts.length < 2) return [];
  if (k >= 1) return pts;
  const L = []; let tot = 0;
  for (let i = 1; i < pts.length; i++) { const d = Math.hypot(pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1]); L.push(d); tot += d; }
  let rem = tot * k; const out = [pts[0]];
  for (let i = 1; i < pts.length; i++) {
    if (rem >= L[i - 1]) { out.push(pts[i]); rem -= L[i - 1]; continue; }
    const f = rem / (L[i - 1] || 1);
    out.push([lerp(pts[i - 1][0], pts[i][0], f), lerp(pts[i - 1][1], pts[i][1], f)]);
    break;
  }
  return out;
}
function arrow(x1, y1, x2, y2, k, color = C.faint, alpha = 1) {
  if (k <= 0) return;
  const x = lerp(x1, x2, k), y = lerp(y1, y2, k);
  line([[x1, y1], [x, y]], color, 2, alpha);
  if (k > 0.95) {
    const a = Math.atan2(y2 - y1, x2 - x1), s = 8;
    line([[x - s * Math.cos(a - 0.5), y - s * Math.sin(a - 0.5)], [x, y], [x - s * Math.cos(a + 0.5), y - s * Math.sin(a + 0.5)]], color, 2, alpha);
  }
}
function packets(x1, y1, x2, y2, t, n = 3, p = 1.4, alpha = 1) {
  for (let i = 0; i < n; i++) {
    const k = ((t / p) + i / n) % 1;
    dot(lerp(x1, x2, k), lerp(y1, y2, k), 3.5, C.accent, alpha * Math.sin(Math.PI * k));
  }
}
function check(x, y, s, color, k = 1, alpha = 1) {
  if (k <= 0 || alpha <= 0) return;
  const pts = [[x - s * 0.5, y], [x - s * 0.12, y + s * 0.38], [x + s * 0.55, y - s * 0.4]];
  const a = clamp(k * 2), b = clamp(k * 2 - 1);
  line([pts[0], [lerp(pts[0][0], pts[1][0], a), lerp(pts[0][1], pts[1][1], a)]], color, 2.6, alpha);
  if (b > 0) line([pts[1], [lerp(pts[1][0], pts[2][0], b), lerp(pts[1][1], pts[2][1], b)]], color, 2.6, alpha);
}
function kicker(s, k, x = 80) { text(s, x, 86, { size: 14, weight: 600, font: MONO, color: C.accent, alpha: k, spacing: "2px" }); }
function headline(s, k, y = 132, size = 42, x = 80) {
  text(s, x, y + (1 - outCubic(k)) * 18, { size, weight: 800, font: SORA, alpha: k, spacing: "-1px" });
}
function fictTag(k) { text(UI[lang].fict, W - 80, 86, { size: 12, font: MONO, color: C.faint, align: "right", alpha: k }); }
/* Pastille texte (badge). Renvoie sa largeur. */
function pill(s, x, y, o = {}) {
  const size = o.size ?? 14, w = measure(s, size, o.weight ?? 600, o.font ?? MONO) + (o.padX ?? 14) * 2, h = o.h ?? size + 16;
  const ax = o.align === "center" ? x - w / 2 : o.align === "right" ? x - w : x;
  panel(ax, y - h / 2, w, h, { r: h / 2, fill: o.fill ?? "rgba(163,230,53,0.1)", stroke: o.stroke ?? "rgba(163,230,53,0.4)", alpha: o.alpha ?? 1 });
  text(s, ax + w / 2, y + size * 0.36, { size, weight: o.weight ?? 600, font: o.font ?? MONO, color: o.color ?? C.accent, align: "center", alpha: o.alpha ?? 1 });
  return w;
}
/* Logo : triangle de montagne. */
function logo(x, y, s = 1, alpha = 1, color = C.accent) {
  ctx.save(); ctx.globalAlpha *= alpha; ctx.translate(x, y); ctx.scale(s, s);
  ctx.beginPath(); ctx.moveTo(-36, 20); ctx.lineTo(-8, -20); ctx.lineTo(4, -4); ctx.lineTo(14, -16); ctx.lineTo(36, 20); ctx.closePath();
  ctx.fillStyle = color; ctx.fill(); ctx.restore();
}

/* Ligne de crête déterministe (0..1 sur x). */
function ridge(u, ph = 0) {
  return 0.5 + 0.22 * Math.sin(u * 6.1 + 0.8 + ph) + 0.14 * Math.sin(u * 15.3 + 2.1 + ph * 1.7) + 0.07 * Math.sin(u * 37.7 + 0.4) + 0.03 * Math.sin(u * 91 + 1.3);
}

/* ---------------------------- éléments d'interface ------------------------- */

/* Fenêtre de terminal. lines = [{p: "$ ", s: "texte", c: couleur, a: début, b: fin (temps local)}]. */
function terminal(x, y, w, h, t, lines, o = {}) {
  const k = o.alpha ?? 1;
  panel(x, y, w, h, { fill: "#0a120e", alpha: k, shadow: o.shadow });
  ctx.save(); ctx.globalAlpha *= k; rr(x, y, w, 34, [16, 16, 0, 0]); ctx.fillStyle = C.panel2; ctx.fill(); ctx.restore();
  [C.red, C.amber, C.accent].forEach((c, i) => dot(x + 20 + i * 16, y + 17, 5, c, k * 0.8));
  if (o.title) text(o.title, x + w / 2, y + 22, { size: 12, font: MONO, color: C.faint, align: "center", alpha: k });
  const size = o.size ?? 16, lh = o.lh ?? 28;
  let row = 0;
  const maxRows = Math.floor((h - 56) / lh);
  const visible = lines.filter(l => t >= (l.a ?? 0));
  const skip = Math.max(0, visible.length - maxRows);
  visible.slice(skip).forEach(l => {
    const ty = y + 62 + row * lh;
    const kk = l.b === undefined ? 1 : seg(t, l.a ?? 0, l.b);
    if (l.p) text(l.p, x + 22, ty, { size, font: MONO, color: C.faint, alpha: k });
    const px = l.p ? x + 22 + measure(l.p, size, 400, MONO) : x + 22;
    text(typed(l.s, kk), px, ty, { size, font: MONO, color: l.c ?? C.ink, weight: l.w ?? 400, alpha: k });
    // curseur clignotant sur la ligne en cours de frappe
    if (kk < 1 && kk > 0) {
      const cx = px + measure(typed(l.s, kk), size, l.w ?? 400, MONO) + 2;
      ctx.save(); ctx.globalAlpha *= k; ctx.fillStyle = C.accent; ctx.fillRect(cx, ty - size + 2, size * 0.55, size + 2); ctx.restore();
    }
    row++;
  });
}

/* Cadre de téléphone ; draw(x, y, w, h) dessine le contenu, découpé à l'écran. */
function phone(x, y, w, h, draw, o = {}) {
  const k = o.alpha ?? 1;
  panel(x, y, w, h, { r: 42, fill: "#050806", stroke: "#33463b", lw: 3, alpha: k, shadow: true });
  ctx.save(); ctx.globalAlpha *= k;
  rr(x + 10, y + 10, w - 20, h - 20, 34); ctx.clip();
  draw(x + 10, y + 10, w - 20, h - 20);
  ctx.restore();
  ctx.save(); ctx.globalAlpha *= k; rr(x + w / 2 - 45, y + 18, 90, 24, 12); ctx.fillStyle = "#000"; ctx.fill(); ctx.restore();
}

/* Bulle de conversation. side = "me" (à droite, accent) | "coach" (à gauche). Renvoie sa hauteur. */
function bubble(s, x, y, maxW, o = {}) {
  const size = o.size ?? 15, lh = Math.round(size * 1.45), pad = 14;
  const lines = wrap(s, maxW - pad * 2, size, o.weight ?? 400);
  const w = Math.min(maxW, Math.max(...lines.map(l => measure(l, size, o.weight ?? 400))) + pad * 2);
  const h = lines.length * lh + pad * 2 - (lh - size);
  const me = o.side === "me";
  const bx = me ? x + maxW - w : x;
  const k = o.alpha ?? 1;
  panel(bx, y, w, h, { r: 16, fill: me ? C.accent : C.panel2, stroke: me ? false : C.line, alpha: k });
  const kk = o.k ?? 1;
  lines.forEach((l, j) => text(typed(l, kk * lines.length - j), bx + pad, y + pad + size - 2 + j * lh, { size, weight: o.weight ?? 400, color: me ? C.deep : C.ink, alpha: k }));
  return h;
}

/* Pointeur de souris ; click (0..1) dessine l'onde du clic. */
function cursor(x, y, o = {}) {
  const k = o.alpha ?? 1;
  if (o.click > 0 && o.click < 1) ring(x, y, 6 + 26 * outCubic(o.click), C.accent, 2.5, k * (1 - o.click));
  ctx.save(); ctx.globalAlpha *= k; ctx.translate(x, y); const s = o.scale ?? 1.1; ctx.scale(s, s);
  ctx.beginPath(); ctx.moveTo(0, 0); ctx.lineTo(0, 22); ctx.lineTo(6, 17); ctx.lineTo(10, 26); ctx.lineTo(14, 24); ctx.lineTo(10, 15); ctx.lineTo(17, 15); ctx.closePath();
  ctx.fillStyle = "#fff"; ctx.fill(); ctx.lineWidth = 1.5; ctx.strokeStyle = "#0a120e"; ctx.stroke();
  ctx.restore();
}

/* Cadre lumineux autour d'une zone (mise en évidence). */
function highlight(x, y, w, h, k, color = C.accent) {
  if (k <= 0) return;
  const p = 6 + 10 * (1 - outCubic(k));
  ctx.save();
  ctx.globalAlpha *= clamp(k);
  ctx.shadowColor = color; ctx.shadowBlur = 18;
  rr(x - p, y - p, w + 2 * p, h + 2 * p, 12); ctx.strokeStyle = color; ctx.lineWidth = 2.5; ctx.stroke();
  ctx.restore();
}
/* Assombrit tout sauf un rectangle (projecteur). */
function spotlight(x, y, w, h, k, alpha = 0.55) {
  if (k <= 0) return;
  ctx.save(); ctx.globalAlpha *= clamp(k) * alpha;
  ctx.beginPath(); ctx.rect(0, 0, W, H); ctx.roundRect(x - 8, y - 8, w + 16, h + 16, 12);
  ctx.fillStyle = "#050806"; ctx.fill("evenodd"); ctx.restore();
}
/* Étiquette avec trait de rappel vers (tx, ty). */
function callout(s, x, y, tx, ty, k, o = {}) {
  if (k <= 0) return;
  line(partial([[tx, ty], [x, y]], outCubic(k)), o.color ?? C.accent, 1.5, 0.9);
  dot(tx, ty, 4, o.color ?? C.accent, clamp(k));
  pill(s, x, y, { alpha: seg(k, 0.5, 1), align: o.align ?? "center", size: o.size ?? 14, font: o.font ?? INTER, color: o.textColor ?? C.ink, fill: o.fill ?? C.deep, stroke: o.color ?? C.accent });
}

/* --------------------- captures réelles du tableau de bord ----------------- */
/* window.ARC_SHOTS (shots/manifest.js, écrit par scripts/video_capture.py) :
 * {shots: [{name, file, width, height, scale, boxes: {nom: [x, y, w, h]}}]} — ou directement
 * {nom: {...}}. Boîtes et dimensions en px CSS de la capture. */
const IMG = {};
let SHOTS = null;
function shotsMap() {
  if (SHOTS) return SHOTS;
  const raw = window.ARC_SHOTS || {};
  SHOTS = Array.isArray(raw.shots) ? Object.fromEntries(raw.shots.map(s => [s.name, s])) : raw;
  return SHOTS;
}
function loadShots(names) {
  const M = shotsMap();
  return Promise.all(names.map(n => new Promise(res => {
    const m = M[n];
    if (!m) { res(); return; }
    const im = new Image();
    im.onload = () => { IMG[n] = im; res(); };
    im.onerror = () => res();
    im.src = `${ARC.shotsBase}${m.file}`;
  })));
}
const shotMeta = n => shotsMap()[n];
function shotBox(n, b) { const m = shotMeta(n); return m && m.boxes && m.boxes[b]; }
/* Rectangle de recadrage [x, y, w, h] (px CSS) qui entoure la boîte b avec une marge,
 * au rapport largeur/hauteur demandé, sans sortir de la capture. */
function cropTo(n, b, aspect, pad = 40) {
  const m = shotMeta(n);
  if (!m) return null;
  const r = Array.isArray(b) ? b : shotBox(n, b);
  if (!r) return [0, 0, m.width, m.height];
  let [x, y, w, h] = [r[0] - pad, r[1] - pad, r[2] + 2 * pad, r[3] + 2 * pad];
  if (w / h > aspect) { const nh = w / aspect; y -= (nh - h) / 2; h = nh; } else { const nw = h * aspect; x -= (nw - w) / 2; w = nw; }
  w = Math.min(w, m.width); h = Math.min(h, m.height);
  x = clamp(x, 0, m.width - w); y = clamp(y, 0, m.height - h);
  return [x, y, w, h];
}
const lerpRect = (a, b, k) => a.map((v, i) => lerp(v, b[i], k));
/* Dessine une capture dans (x, y, w, h). o.crop = [x, y, w, h] en px CSS de la capture
 * (défaut : haut de page, au rapport du cadre) ; o.chrome = barre de navigateur.
 * Renvoie map(box) -> [X, Y, W, H] à l'écran, pour placer surlignages et curseur. */
function shot(n, x, y, w, h, o = {}) {
  const m = shotMeta(n), k = o.alpha ?? 1;
  const bar = o.chrome === false ? 0 : 30;
  const r = o.r ?? 14;
  panel(x, y, w, h, { r, fill: "#0a120e", stroke: o.stroke ?? "#33463b", alpha: k, shadow: o.shadow !== false });
  if (bar) {
    ctx.save(); ctx.globalAlpha *= k; rr(x, y, w, bar, [r, r, 0, 0]); ctx.fillStyle = C.panel2; ctx.fill(); ctx.restore();
    [C.red, C.amber, C.accent].forEach((c, i) => dot(x + 16 + i * 13, y + bar / 2, 4, c, k * 0.7));
    const url = o.url ?? "127.0.0.1:8765";
    const uw = Math.min(w - 120, measure(url, 11, 400, MONO) + 30);
    panel(x + w / 2 - uw / 2, y + 6, uw, bar - 12, { r: 9, fill: "#0a120e", stroke: false, alpha: k });
    text(url, x + w / 2, y + bar / 2 + 4, { size: 11, font: MONO, color: C.faint, align: "center", alpha: k });
  }
  const iy = y + bar, ih = h - bar;
  const crop = o.crop || (m ? [0, 0, m.width, Math.min(m.height, m.width * ih / w)] : [0, 0, w, ih]);
  ctx.save(); ctx.globalAlpha *= k;
  rr(x, iy, w, ih, bar ? [0, 0, r, r] : r); ctx.clip();
  const im = IMG[n];
  if (im && m) {
    const s = m.scale || (im.naturalWidth / m.width);
    // le recadrage peut ne pas avoir exactement le rapport du cadre : on remplit en largeur
    const sh = Math.min(crop[3], crop[2] * ih / w);
    ctx.imageSmoothingQuality = "high";
    ctx.drawImage(im, crop[0] * s, crop[1] * s, crop[2] * s, sh * s, x, iy, w, ih);
  } else {
    ctx.fillStyle = C.panel; ctx.fillRect(x, iy, w, ih);
    text(`capture « ${n} » absente`, x + w / 2, iy + ih / 2, { size: 14, font: MONO, color: C.faint, align: "center" });
  }
  ctx.restore();
  const sx = w / crop[2];
  return b => {
    const bb = Array.isArray(b) ? b : shotBox(n, b);
    if (!bb) return null;
    return [x + (bb[0] - crop[0]) * sx, iy + (bb[1] - crop[1]) * sx, bb[2] * sx, bb[3] * sx];
  };
}

/* ------------------------------- décor commun ------------------------------ */
function background(t) {
  const g = ctx.createLinearGradient(0, 0, 0, H);
  g.addColorStop(0, C.bg2); g.addColorStop(1, C.bg);
  ctx.fillStyle = g; ctx.fillRect(0, 0, W, H);
  const clusters = [[1080, 150, 0], [170, 640, 3]];
  for (const [cx, cy, ph] of clusters) {
    for (let i = 1; i <= 9; i++) {
      ctx.beginPath();
      for (let j = 0; j <= 120; j++) {
        const th = (j / 120) * Math.PI * 2;
        const r = i * 34 * (1 + 0.09 * Math.sin(3 * th + i * 0.6 + ph) + 0.05 * Math.sin(5 * th - i * 0.7 + t * 0.06 + ph));
        const x = cx + r * Math.cos(th), y = cy + r * 0.72 * Math.sin(th);
        j ? ctx.lineTo(x, y) : ctx.moveTo(x, y);
      }
      ctx.strokeStyle = "rgba(163,230,53,0.045)"; ctx.lineWidth = 1; ctx.stroke();
    }
  }
}

/* -------------------------- scènes communes -------------------------------- */

/* Dossard d'ouverture : numéro d'étape, titre, durée et « D+ ». */
function sBib(t, d) {
  const ep = ARC.ep, s = UI[lang];
  const kc = outBack(seg(t, 0.1, 0.9));
  const sway = Math.sin(t * 1.3) * 0.006 * seg(t, 0.9, 1.6);
  const bw = 600, bh = 380, bx = W / 2 - bw / 2, by = 150;
  ctx.save();
  ctx.translate(W / 2, by - 40); ctx.rotate(lerp(-0.18, 0, clamp(kc)) + sway); ctx.translate(-W / 2, -(by - 40));
  ctx.translate(0, (1 - clamp(kc)) * -260);
  ctx.globalAlpha *= clamp(kc * 1.5);
  panel(bx, by, bw, bh, { r: 18, fill: C.paper, stroke: false, shadow: true });
  // bandeau
  ctx.save(); rr(bx, by, bw, 64, [18, 18, 0, 0]); ctx.fillStyle = C.pine; ctx.fill(); ctx.restore();
  logo(bx + 44, by + 32, 0.55, 1);
  text(s.bibEvent, bx + 80, by + 39, { size: 15, weight: 700, font: MONO, color: C.paper, spacing: "2px" });
  // perforations
  for (let i = 0; i < 26; i++) dot(bx + 24 + i * 21.8, by + bh - 70, 2.2, "#d9d5ca");
  // numéro
  const num = String(ep.n).padStart(2, "0");
  const kn = outCubic(seg(t, 0.6, 1.3));
  text(num, W / 2, by + 220, { size: 170, weight: 800, font: SORA, color: C.deep, align: "center", alpha: kn, spacing: "-6px" });
  const title = ep[lang];
  const ts = measure(title, 30, 700, SORA) > bw - 80 ? 24 : 30;
  text(title, W / 2, by + 270, { size: ts, weight: 700, font: SORA, color: C.paperInk, align: "center", alpha: seg(t, 1.0, 1.6) });
  const dur = ARC.duration();
  const meta = `${s.stage} ${ep.n}/${SERIES.length - 1}   ·   ⏱ ${fmt(dur)}   ·   ${Math.round(dur * 6 / 10) * 10} m ${s.gain}`;
  text(ep.n ? meta : `⏱ ${fmt(dur)}`, W / 2, by + bh - 28, { size: 15, weight: 600, font: MONO, color: "#4a5a52", align: "center", alpha: seg(t, 1.3, 1.9) });
  // épingles
  [[bx + 22, by + 86], [bx + bw - 22, by + 86], [bx + 22, by + bh - 98], [bx + bw - 22, by + bh - 98]].forEach(([px, py], i) => {
    const kp = outBack(seg(t, 0.8 + i * 0.1, 1.1 + i * 0.1));
    if (kp <= 0) return;
    ctx.save(); ctx.translate(px, py); ctx.scale(kp, kp);
    ctx.beginPath(); ctx.ellipse(0, 0, 10, 4, -0.5, 0, Math.PI * 2); ctx.strokeStyle = "#9aa6a0"; ctx.lineWidth = 2; ctx.stroke();
    dot(-8, 4, 3, "#9aa6a0");
    ctx.restore();
  });
  ctx.restore();
  text(s.series.toUpperCase(), W / 2, 96, { size: 14, weight: 600, font: MONO, color: C.accent, align: "center", spacing: "4px", alpha: seg(t, 0.2, 0.8) });
}

/* Arche d'arrivée : chrono, lien vers la documentation, étape suivante. */
function sFinish(t, d) {
  const ep = ARC.ep, s = UI[lang];
  const ground = 470;
  const ka = outCubic(seg(t, 0.1, 0.9));
  // sol
  line([[0, ground], [W, ground]], C.line, 2, ka);
  // arche
  ctx.save(); ctx.globalAlpha *= ka; ctx.translate(0, (1 - ka) * 40);
  const ax0 = 340, ax1 = 940, top = 170;
  [ax0, ax1].forEach(px => { rr(px - 18, top, 36, ground - top, 8); ctx.fillStyle = C.pine; ctx.fill(); });
  rr(ax0 - 40, top - 26, ax1 - ax0 + 80, 92, 14); ctx.fillStyle = C.pine; ctx.fill();
  ctx.strokeStyle = C.accent; ctx.lineWidth = 2; ctx.stroke();
  text(s.finish, W / 2, top + 36, { size: 52, weight: 800, font: SORA, color: C.accent, align: "center", spacing: "6px" });
  ctx.restore();
  // chrono
  const dur = ARC.duration();
  const kt = seg(t, 0.3, 1.8);
  const shown = dur * outCubic(kt);
  const chrono = `${fmt(shown)}.${Math.floor((shown % 1) * 10)}`;
  panel(W / 2 - 110, top + 90, 220, 54, { r: 10, fill: "#050806", stroke: "#33463b", alpha: ka });
  text(chrono, W / 2, top + 128, { size: 32, weight: 700, font: MONO, color: kt >= 1 ? C.accent : C.ink, align: "center", alpha: ka });
  // coureur qui franchit la ligne
  const kr = inOut(seg(t, 0.4, 1.9));
  const rx = lerp(120, W / 2 + 10, kr);
  dot(rx, ground - 14, 12, C.accent, ka); dot(rx, ground - 14, 22, C.accent, 0.2 * ka);
  // confettis déterministes
  if (t > 1.9) {
    const R = rng(hash(ARC.slug));
    for (let i = 0; i < 70; i++) {
      const ang = -Math.PI / 2 + (R() - 0.5) * 2.2, sp = 160 + R() * 260, life = t - 1.9 - R() * 0.3;
      if (life <= 0) continue;
      const x = W / 2 + Math.cos(ang) * sp * life, y = ground - 30 + Math.sin(ang) * sp * life + 160 * life * life;
      if (y > ground) continue;
      const c = [C.accent, C.amber, C.teal, C.ink][i % 4];
      ctx.save(); ctx.globalAlpha *= clamp(1.4 - life * 0.5); ctx.translate(x, y); ctx.rotate(life * (3 + R() * 6));
      ctx.fillStyle = c; ctx.fillRect(-4, -2, 8, 4); ctx.restore();
    }
  }
  // pour aller plus loin
  const kd = seg(t, 1.8, 2.4);
  text(s.finishSub.toUpperCase(), W / 2, 528, { size: 13, weight: 600, font: MONO, color: C.faint, align: "center", spacing: "2px", alpha: kd });
  const docsUrl = `mmornati.github.io/ai-running-coach/${ep.docs}`;
  text(docsUrl, W / 2, 562, { size: 20, weight: 600, font: MONO, color: C.accent, align: "center", alpha: kd });
  const next = SERIES[ep.n + 1];
  const kn = seg(t, 2.4, 3.0);
  text(next ? `${s.next} · ${String(next.n).padStart(2, "0")} — ${next[lang]}` : s.lastLeg, W / 2, 606, { size: 17, color: C.soft, align: "center", alpha: kn });
  text(s.disclaimer, W / 2, 648, { size: 13, color: C.faint, align: "center", alpha: seg(t, 3.0, 3.6) });
}

/* ------------------------------ timeline ----------------------------------- */
let lang = UI[params.get("lang")] ? params.get("lang") : "fr";
let subsOn = params.get("subs") === "1";
const ARC = {
  W, H, C, SORA, INTER, MONO, SERIES, UI, IMG,
  ep: null, slug: "", shotsBase: "../shots/", base: "",
  plan: null,         // {duration, scenes: [{id, start, d, cues: [{s, e, text}]}]} pour la langue courante
  duration: () => (ARC.plan ? ARC.plan.duration : 0),
};

/* Plan de lecture d'une langue : timing.js (généré) ; à défaut, durées minimales du script. */
function planFor(l) {
  const T = window.ARC_TIMING;
  if (T && T[l]) return T[l];
  return null;
}

const FADE = 0.45;
function render(t) {
  const plan = ARC.plan;
  ctx.setTransform(RES, 0, 0, RES, 0, 0);
  ctx.globalAlpha = 1;
  background(t);
  if (!plan) {
    text(UI[lang].missing + " " + ARC.slug, W / 2, H / 2, { size: 18, font: MONO, color: C.amber, align: "center" });
    return;
  }
  t = clamp(t, 0, plan.duration);
  const n = plan.scenes.length;
  plan.scenes.forEach((sc, i) => {
    const lt = t - sc.start;
    const last = i === n - 1;
    if (lt < 0 || !(lt < sc.d || (last && lt <= sc.d))) return;
    const f = ARC.sceneFns[sc.id];
    const fin = i === 0 ? 1 : seg(lt, 0, FADE);
    const fout = last ? 1 : 1 - seg(lt, sc.d - FADE, sc.d);
    ctx.save();
    ctx.globalAlpha = Math.min(fin, fout);
    if (f) f(lt, sc.d, sc.cues);
    else text(`scène « ${sc.id} » absente de scenes.js`, W / 2, H / 2, { size: 18, font: MONO, color: C.red, align: "center" });
    ctx.restore();
  });
  progressRidge(t);
  if (subsOn) drawSubs(t);
}

/* Frise de progression incrustée dans l'image : profil parcouru, ravitos aux chapitres. */
function progressRidge(t) {
  const plan = ARC.plan, D = plan.duration;
  const x0 = 80, x1 = W - 80, yb = 704, hh = 14, u = t / D, ph = ARC.phase;
  ctx.save();
  ctx.beginPath();
  for (let i = 0; i <= 200; i++) { const v = i / 200, x = lerp(x0, x1, v), y = yb - hh * ridge(v, ph); i ? ctx.lineTo(x, y) : ctx.moveTo(x, y); }
  ctx.strokeStyle = "rgba(231,237,233,0.14)"; ctx.lineWidth = 1.5; ctx.stroke();
  ctx.beginPath();
  for (let i = 0; i <= 200 * u; i++) { const v = i / 200, x = lerp(x0, x1, v), y = yb - hh * ridge(v, ph); i ? ctx.lineTo(x, y) : ctx.moveTo(x, y); }
  ctx.strokeStyle = C.accent; ctx.globalAlpha = 0.8; ctx.stroke();
  ctx.restore();
  plan.scenes.forEach((sc, i) => {
    if (!i || !sc.chapter) return;
    const v = sc.start / D;
    dot(lerp(x0, x1, v), yb - hh * ridge(v, ph), 2.2, t >= sc.start ? C.accent : "rgba(231,237,233,0.3)");
  });
  dot(lerp(x0, x1, u), yb - hh * ridge(u, ph), 4.5, C.accent);
}

function cueAt(t) {
  for (const sc of ARC.plan.scenes) for (const c of sc.cues || []) {
    if (t >= sc.start + c.s && t < sc.start + c.e + 0.25) return c.text;
  }
  return null;
}
function drawSubs(t) {
  const s = cueAt(t);
  if (!s) return;
  const lines = wrap(s, 980, 22, 500);
  const lh = 31, h = lines.length * lh + 18, y = 698 - h;
  const w = Math.max(...lines.map(l => measure(l, 22, 500))) + 40;
  panel(W / 2 - w / 2, y, w, h, { r: 10, fill: "rgba(5,8,6,0.82)", stroke: false });
  lines.forEach((l, j) => text(l, W / 2, y + 31 + j * lh, { size: 22, weight: 500, align: "center" }));
}

/* ------------------------------- lecteur ----------------------------------- */
function el(tag, attrs = {}, kids = []) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "text") e.textContent = v; else if (k === "html") e.innerHTML = v; else e.setAttribute(k, v);
  }
  kids.forEach(c => e.appendChild(c));
  return e;
}
const SVGNS = "http://www.w3.org/2000/svg";
const svg = (tag, attrs = {}) => { const e = document.createElementNS(SVGNS, tag); for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v); return e; };

function buildPage(ep) {
  const main = el("main");
  const header = el("header");
  const h = el("div");
  h.appendChild(el("p", { class: "ep-kicker", id: "kick" }));
  h.appendChild(el("h1", { id: "title" }));
  header.appendChild(h);
  const nav = el("nav", { class: "nav", "aria-label": "Navigation" });
  nav.appendChild(el("a", { id: "prev" })); nav.appendChild(el("a", { id: "next" }));
  nav.appendChild(el("a", { id: "all" })); nav.appendChild(el("a", { id: "docs" }));
  header.appendChild(nav);
  main.appendChild(header);
  const stage = el("div", { class: "stage" });
  stage.appendChild(el("canvas", { id: "c", role: "img" }));
  main.appendChild(stage);
  // profil altimétrique cliquable
  const wrapP = el("div", { class: "profile-wrap" });
  const prof = svg("svg", { class: "profile", id: "profile", viewBox: "0 0 1000 64", preserveAspectRatio: "none", tabindex: "0", role: "slider", "aria-valuemin": "0" });
  wrapP.appendChild(prof);
  wrapP.appendChild(el("div", { class: "tip", id: "tip" }));
  main.appendChild(wrapP);
  const bar = el("div", { class: "bar" });
  bar.appendChild(el("button", { id: "play", type: "button" }));
  bar.appendChild(el("span", { class: "time", id: "time" }));
  bar.appendChild(el("span", { class: "spacer" }));
  bar.appendChild(el("button", { id: "subs", type: "button", "aria-pressed": "false" }));
  bar.appendChild(el("button", { id: "sound", type: "button", "aria-pressed": "true" }));
  const sel = el("select", { id: "lang", "aria-label": "Langue / Language" });
  sel.appendChild(el("option", { value: "fr", text: "Français" }));
  sel.appendChild(el("option", { value: "en", text: "English" }));
  bar.appendChild(sel);
  bar.appendChild(el("button", { id: "full", type: "button" }));
  main.appendChild(bar);
  main.appendChild(el("p", { class: "chapters-title", id: "chapTitle" }));
  main.appendChild(el("ol", { class: "chapters", id: "chapters" }));
  main.appendChild(el("p", { class: "note", id: "note" }));
  main.appendChild(el("audio", { id: "audio", preload: "auto" }));
  document.body.appendChild(main);
  if (CAPTURE) document.body.classList.add("capture");
}

const $ = id => document.getElementById(id);
let playing = false, t0 = 0, tNow = 0, raf = 0, soundOn = true;
const audio = () => $("audio");

function profileY(v) { return 58 - 44 * ridge(v, ARC.phase); }
function drawProfile() {
  const prof = $("profile"), D = ARC.duration();
  prof.innerHTML = "";
  if (!D) return;
  let d = "M0,64";
  for (let i = 0; i <= 200; i++) { const v = i / 200; d += ` L${v * 1000},${profileY(v).toFixed(2)}`; }
  d += " L1000,64 Z";
  prof.appendChild(svg("path", { class: "base", d }));
  const clip = svg("clipPath", { id: "doneClip" });
  clip.appendChild(svg("rect", { id: "doneRect", x: 0, y: 0, width: 0, height: 64 }));
  prof.appendChild(clip);
  prof.appendChild(svg("path", { class: "done", d, "clip-path": "url(#doneClip)" }));
  let r = ""; for (let i = 0; i <= 200; i++) { const v = i / 200; r += `${i ? " L" : "M"}${v * 1000},${profileY(v).toFixed(2)}`; }
  prof.appendChild(svg("path", { class: "ridge", d: r }));
  prof.appendChild(svg("path", { class: "ridge-done", d: r, "clip-path": "url(#doneClip)" }));
  ARC.plan.scenes.forEach((sc, i) => {
    if (!i || !sc.chapter) return;
    const v = sc.start / D, x = v * 1000, y = profileY(v);
    prof.appendChild(svg("line", { class: "aid", x1: x, y1: y, x2: x, y2: 6 }));
    prof.appendChild(svg("path", { class: "aid-flag", "data-start": sc.start, d: `M${x},4 L${x + 12},8 L${x},12 Z` }));
  });
  prof.appendChild(svg("circle", { class: "runner-halo", id: "runnerHalo", r: 9, cx: 0, cy: profileY(0) }));
  prof.appendChild(svg("circle", { class: "runner", id: "runner", r: 4.5, cx: 0, cy: profileY(0) }));
  prof.setAttribute("aria-valuemax", Math.round(D));
}
function updateProfile(t) {
  const D = ARC.duration(); if (!D) return;
  const v = clamp(t / D), x = v * 1000, y = profileY(v);
  const rect = $("doneRect"); if (rect) rect.setAttribute("width", x);
  for (const id of ["runner", "runnerHalo"]) { const c = $(id); if (c) { c.setAttribute("cx", x); c.setAttribute("cy", y); } }
  document.querySelectorAll(".aid-flag").forEach(f => f.classList.toggle("passed", t >= +f.dataset.start));
  const prof = $("profile");
  prof.setAttribute("aria-valuenow", Math.round(t));
  prof.setAttribute("aria-valuetext", `${fmt(t)} / ${fmt(D)}`);
  const cur = currentChapter(t);
  document.querySelectorAll(".chapters button").forEach(b => b.classList.toggle("on", b.dataset.id === cur));
}
function currentChapter(t) {
  let cur = null;
  for (const sc of ARC.plan.scenes) if (sc.chapter && t >= sc.start) cur = sc.id;
  return cur;
}
function buildChapters() {
  const ol = $("chapters"); ol.innerHTML = "";
  if (!ARC.plan) return;
  ARC.plan.scenes.forEach(sc => {
    if (!sc.chapter) return;
    const b = el("button", { type: "button", "data-id": sc.id });
    b.appendChild(el("span", { class: "t", text: fmt(sc.start) }));
    b.appendChild(el("span", { text: sc.chapter }));
    b.addEventListener("click", () => seekTo(sc.start + 0.01));
    const li = el("li"); li.appendChild(b); ol.appendChild(li);
  });
}

function applyLang() {
  const s = UI[lang], ep = ARC.ep;
  window.S = (ARC.strings && ARC.strings[lang]) || {};
  ARC.plan = planFor(lang);
  document.documentElement.lang = lang;
  const title = ep.n ? `${s.stage} ${ep.n} · ${ep[lang]}` : ep[lang];
  document.title = `${ep[lang]} — ai-running-coach`;
  $("kick").textContent = `${s.series} · ${ep.n ? s.stage + " " + String(ep.n).padStart(2, "0") : "00"}`;
  $("title").textContent = ep[lang];
  $("c").setAttribute("aria-label", title);
  const prev = SERIES[ep.n - 1], next = SERIES[ep.n + 1];
  const href = e => `${ARC.root}video/${e.dir ? e.dir + "/" : ""}?lang=${lang}`;
  $("prev").textContent = prev ? `← ${prev[lang]}` : ""; $("prev").hidden = !prev; if (prev) $("prev").href = href(prev);
  $("next").textContent = next ? `${next[lang]} →` : ""; $("next").hidden = !next; if (next) $("next").href = href(next);
  $("all").textContent = s.all; $("all").href = `${ARC.root}videos/`;
  $("docs").textContent = s.back; $("docs").href = `${ARC.root}${ep.docs}`;
  $("full").textContent = s.full; $("subs").textContent = s.subs; $("sound").textContent = s.sound;
  $("play").textContent = playing ? s.pause : s.play;
  $("note").innerHTML = s.note;
  $("chapTitle").textContent = s.chapters;
  $("profile").setAttribute("aria-label", s.seek);
  $("lang").value = lang;
  const a = audio();
  const src = `${ARC.base}audio/${lang}.m4a`;
  if (!a.src.endsWith(src.replace(/^\.\//, ""))) { a.src = src; a.load(); }
  drawProfile(); buildChapters();
}
function show(t) {
  tNow = t; render(t);
  const D = ARC.duration();
  $("time").textContent = `${fmt(t)} / ${fmt(D)}`;
  updateProfile(t);
}
function tick(now) {
  if (!playing) return;
  const D = ARC.duration();
  const a = audio();
  let t = (now - t0) / 1000;
  // l'audio fait foi tant qu'il joue : aucune dérive voix/image
  if (soundOn && !a.paused && a.readyState >= 3 && t < D - 0.3) { t = a.currentTime; t0 = now - t * 1000; }
  if (t >= D) { pause(); show(D); return; }
  show(t);
  raf = requestAnimationFrame(tick);
}
function syncAudio(t) {
  const a = audio();
  if (!soundOn || !playing) { a.pause(); return; }
  try { a.currentTime = t; } catch (_) { /* métadonnées pas encore chargées */ }
  a.play().catch(() => {});
}
function play() {
  if (tNow >= ARC.duration()) tNow = 0;
  playing = true; t0 = performance.now() - tNow * 1000;
  $("play").textContent = UI[lang].pause;
  syncAudio(tNow);
  raf = requestAnimationFrame(tick);
}
function pause() { playing = false; cancelAnimationFrame(raf); audio().pause(); $("play").textContent = UI[lang].play; }
function toggle() { playing ? pause() : play(); }
function seekTo(t) { t = clamp(t, 0, ARC.duration()); if (playing) { t0 = performance.now() - t * 1000; syncAudio(t); } show(t); }
function store(k, v) { try { localStorage.setItem(k, v); } catch (_) { /* stockage indisponible */ } }
function stored(k) { try { return localStorage.getItem(k); } catch (_) { return null; } }

function wire() {
  $("play").addEventListener("click", toggle);
  $("c").addEventListener("click", toggle);
  $("lang").addEventListener("change", e => {
    lang = e.target.value; const wasPlaying = playing; pause(); applyLang(); show(clamp(tNow, 0, ARC.duration()));
    const u = new URL(location.href); u.searchParams.set("lang", lang); history.replaceState(null, "", u);
    if (wasPlaying) play();
  });
  $("subs").addEventListener("click", () => { subsOn = !subsOn; $("subs").setAttribute("aria-pressed", subsOn); store("arc-video-subs", subsOn ? "1" : "0"); show(tNow); });
  $("sound").addEventListener("click", () => { soundOn = !soundOn; $("sound").setAttribute("aria-pressed", soundOn); syncAudio(tNow); });
  $("full").addEventListener("click", () => {
    const st = document.querySelector(".stage");
    document.fullscreenElement ? document.exitFullscreen() : st.requestFullscreen?.();
  });
  const prof = $("profile"), tip = $("tip");
  const tAt = e => { const r = prof.getBoundingClientRect(); return clamp((e.clientX - r.left) / r.width) * ARC.duration(); };
  let drag = false;
  prof.addEventListener("pointerdown", e => { drag = true; prof.setPointerCapture(e.pointerId); seekTo(tAt(e)); });
  prof.addEventListener("pointermove", e => {
    const t = tAt(e), r = prof.getBoundingClientRect();
    const ch = ARC.plan && ARC.plan.scenes.filter(sc => sc.chapter && sc.start <= t).pop();
    tip.textContent = ch ? `${fmt(t)} · ${ch.chapter}` : fmt(t);
    tip.style.left = `${e.clientX - r.left}px`; tip.style.top = "8px"; tip.style.opacity = 1;
    if (drag) seekTo(t);
  });
  prof.addEventListener("pointerup", () => { drag = false; });
  prof.addEventListener("pointerleave", () => { tip.style.opacity = 0; });
  prof.addEventListener("keydown", e => {
    if (e.key === "ArrowRight") { e.preventDefault(); seekTo(tNow + 5); }
    if (e.key === "ArrowLeft") { e.preventDefault(); seekTo(tNow - 5); }
    if (e.key === "Home") { e.preventDefault(); seekTo(0); }
    if (e.key === "End") { e.preventDefault(); seekTo(ARC.duration()); }
  });
  document.addEventListener("keydown", e => {
    if (e.target.tagName === "INPUT" || e.target.tagName === "SELECT" || e.target.id === "profile") return;
    if (e.code === "Space") { e.preventDefault(); toggle(); }
    if (e.code === "ArrowRight") seekTo(tNow + 5);
    if (e.code === "ArrowLeft") seekTo(tNow - 5);
    if (e.key === "c") $("subs").click();
  });
}

/* Point d'entrée d'un épisode.
 * def = { slug, n (numéro dans SERIES), strings: {fr: {}, en: {}}, scenes: {id: fn(t, d, cues)},
 *         shots: [noms de captures], root: chemin vers la racine du site (défaut "../../"),
 *         base: dossier de l'épisode relatif à la page (défaut "") } */
ARC.episode = function (def) {
  const ep = SERIES[def.n];
  ARC.ep = ep; ARC.slug = def.slug || ep.dir || "bande-annonce";
  ARC.strings = def.strings || {};
  ARC.sceneFns = Object.assign({ bib: sBib, finish: sFinish }, def.scenes);
  ARC.root = def.root ?? "../../";
  ARC.base = def.base ?? "";
  ARC.shotsBase = def.shotsBase ?? "../shots/";
  ARC.phase = (hash(ARC.slug) % 628) / 100;
  buildPage(ep);
  const canvas = $("c");
  canvas.width = W * RES; canvas.height = H * RES;
  ctx = canvas.getContext("2d");
  if (!CAPTURE) { const s = stored("arc-video-subs"); if (s !== null && !params.has("subs")) subsOn = s === "1"; }
  $("subs").setAttribute("aria-pressed", subsOn);
  wire();
  window.renderFrame = t => render(t);
  window.videoReady = Promise.all([
    "800 20px Sora", "700 20px Sora", "600 20px Sora", "400 20px Inter", "500 20px Inter", "600 20px Inter", "700 20px Inter",
    '400 20px "JetBrains Mono"', '600 20px "JetBrains Mono"', '700 20px "JetBrains Mono"',
  ].map(f => document.fonts.load(f))).then(() => document.fonts.ready).then(() => loadShots(def.shots || [])).then(() => {
    applyLang();
    window.DURATION = ARC.duration();
    tNow = clamp(parseFloat(params.get("t")) || 0, 0, ARC.duration());
    show(tNow);
    const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (params.get("autoplay") === "1" && !reduce) play();
    return true;
  });
};

/* Exposition des outils aux scènes. */
Object.assign(window, {
  ARC, W, H, C, SORA, INTER, MONO,
  clamp, lerp, seg, outCubic, inOut, outBack, typed, bump, rng, hash, fmt, at, atEnd,
  text, measure, wrap, para, rr, panel, dot, ring, line, partial, arrow, packets, check,
  kicker, headline, fictTag, pill, logo, ridge,
  terminal, phone, bubble, cursor, highlight, spotlight, callout,
  shot, shotBox, shotMeta, cropTo, lerpRect,
});
Object.defineProperty(window, "ctx", { get: () => ctx });
Object.defineProperty(window, "LANG", { get: () => lang });
})();
