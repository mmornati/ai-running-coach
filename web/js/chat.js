// Page « Coach » : conversation en streaming (SSE) avec le service de chat.
// Aucun innerHTML sur du texte venu du modèle : tout passe par textContent / createElement.
import * as F from "./format.js";
import { navItems, showVersion, showSyncPill } from "./nav.js";

const $ = (s, root = document) => root.querySelector(s);
const API = "api/chat";
const CSRF = { "X-ARC-Chat": "1" };
const DOCS_URL = "https://mmornati.github.io/ai-running-coach/dashboard/chat/";
const eur = new Intl.NumberFormat("fr-FR", { style: "currency", currency: "EUR", minimumFractionDigits: 2, maximumFractionDigits: 2 });
const fmtEur = (v) => eur.format(Number.isFinite(+v) ? +v : 0);

const els = {
  thread: $("#thread"), empty: $("#empty"), banner: $("#banner"), pinned: $("#pinned"),
  form: $("#composer"), input: $("#composer-input"), send: $("#send"), stop: $("#stop"),
  select: $("#session-select"), newBtn: $("#new-session"), cost: $("#cost"), backend: $("#backend"),
};

const state = {
  status: null,
  sessionId: null,
  streaming: false,
  replaying: false,
  abort: null,
  turn: null,          // tour du coach en cours de dessin
  sessionCost: 0,
  lastUsage: null,
  approvals: new Map(), // approval_id -> { card, pinned }
  pollTimer: null,      // sondage d'une session dont un tour tourne ailleurs (autre onglet, reprise)
};

// ---------------------------------------------------------------------------
// Réseau
// ---------------------------------------------------------------------------

async function call(method, path, body) {
  const opts = { method, headers: { Accept: "application/json" } };
  if (method !== "GET") {
    opts.headers = { ...opts.headers, ...CSRF, "Content-Type": "application/json" };
    opts.body = JSON.stringify(body ?? {});
  }
  const res = await fetch(`${API}${path}`, opts);
  let data = null;
  try { data = await res.json(); } catch { /* corps vide ou non JSON */ }
  if (!res.ok) {
    const err = new Error((data && data.error) || `HTTP ${res.status}`);
    err.status = res.status;
    throw err;
  }
  return data;
}

// ---------------------------------------------------------------------------
// Rendu : markdown réduit (gras, italique, code, listes, titres, tableaux, blocs ```) sans innerHTML
// ---------------------------------------------------------------------------

const INLINE_RE = /(\*\*[^*]+?\*\*|`[^`]+`|\*[^*\s][^*]*?\*)/g;

function inline(parent, text) {
  for (const part of text.split(INLINE_RE)) {
    if (!part) continue;
    let node;
    if (part.length > 4 && part.startsWith("**") && part.endsWith("**")) {
      node = document.createElement("strong"); node.textContent = part.slice(2, -2);
    } else if (part.length > 2 && part.startsWith("`") && part.endsWith("`")) {
      node = document.createElement("code"); node.textContent = part.slice(1, -1);
    } else if (part.length > 2 && part.startsWith("*") && part.endsWith("*")) {
      node = document.createElement("em"); node.textContent = part.slice(1, -1);
    } else {
      node = document.createTextNode(part);
    }
    parent.appendChild(node);
  }
}

// Blocs de données (contrat ```arc, JSON, YAML) : repliés — l'athlète n'a pas à lire du JSON,
// mais rien n'est caché au point d'être perdu. Tout autre bloc ``` est rendu en <pre>.
const DATA_FENCES = new Set(["arc", "json", "yaml", "yml", "toml"]);

function codeBlock(lang, lines) {
  const pre = document.createElement("pre");
  pre.className = "md-pre";
  const code = document.createElement("code");
  code.textContent = lines.join("\n");
  pre.appendChild(code);
  if (!DATA_FENCES.has(lang)) return pre;
  const box = document.createElement("details");
  box.className = "md-data";
  const sum = document.createElement("summary");
  sum.textContent = lang === "arc" ? "Données structurées du fichier" : `Données (${lang})`;
  box.append(sum, pre);
  return box;
}

const TABLE_SEP_RE = /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$/;
const cells = (line) => line.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map((c) => c.trim());

function table(rows) {
  const wrap = document.createElement("div");
  wrap.className = "md-table";
  const t = document.createElement("table");
  const head = document.createElement("thead");
  const hr = document.createElement("tr");
  for (const c of cells(rows[0])) { const th = document.createElement("th"); inline(th, c); hr.appendChild(th); }
  head.appendChild(hr);
  const body = document.createElement("tbody");
  for (const row of rows.slice(2)) {
    const tr = document.createElement("tr");
    for (const c of cells(row)) { const td = document.createElement("td"); inline(td, c); tr.appendChild(td); }
    body.appendChild(tr);
  }
  t.append(head, body);
  wrap.appendChild(t);
  return wrap;
}

export function renderMarkdown(container, text) {
  container.replaceChildren();
  let list = null;
  let para = [];
  const flushPara = () => {
    if (!para.length) return;
    const p = document.createElement("p");
    para.forEach((line, i) => { if (i) p.appendChild(document.createElement("br")); inline(p, line); });
    container.appendChild(p);
    para = [];
  };
  const lines = text.split("\n");
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i].replace(/\s+$/, "");
    const fence = /^\s*```\s*([\w-]*)/.exec(line);
    if (fence) {
      // Bloc ``` : jusqu'à la clôture — ou jusqu'à la fin pendant le streaming.
      flushPara(); list = null;
      const body = [];
      while (++i < lines.length && !/^\s*```\s*$/.test(lines[i])) body.push(lines[i]);
      container.appendChild(codeBlock(fence[1].toLowerCase(), body));
      continue;
    }
    if (line.includes("|") && i + 1 < lines.length && TABLE_SEP_RE.test(lines[i + 1])) {
      flushPara(); list = null;
      const rows = [line, lines[++i]];
      while (i + 1 < lines.length && lines[i + 1].includes("|") && lines[i + 1].trim()) rows.push(lines[++i]);
      container.appendChild(table(rows));
      continue;
    }
    const heading = /^\s*(#{1,6})\s+(.*)$/.exec(line);
    if (heading) {
      flushPara(); list = null;
      const h = document.createElement(heading[1].length <= 2 ? "h3" : "h4");
      h.className = "md-h";
      inline(h, heading[2].replace(/\s*#+\s*$/, ""));
      container.appendChild(h);
      continue;
    }
    if (/^\s*(-{3,}|\*{3,}|_{3,})\s*$/.test(line)) {
      flushPara(); list = null;
      container.appendChild(document.createElement("hr"));
      continue;
    }
    const item = /^\s*(?:[-*•]|\d+[.)])\s+(.*)$/.exec(line);
    if (item) {
      flushPara();
      const ordered = /^\s*\d/.test(line);
      const tag = ordered ? "ol" : "ul";
      if (!list || list.tagName.toLowerCase() !== tag) {
        list = document.createElement(tag);
        container.appendChild(list);
      }
      const li = document.createElement("li");
      inline(li, item[1]);
      list.appendChild(li);
    } else if (!line.trim()) {
      flushPara(); list = null;
    } else {
      list = null;
      para.push(line.trim());
    }
  }
  flushPara();
}

const el = (tag, cls, text) => {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text != null) n.textContent = text;
  return n;
};

function scrollDown() { els.thread.scrollTop = els.thread.scrollHeight; }

// ---------------------------------------------------------------------------
// Tour du coach : trace des outils, texte, cartes, fichiers
// ---------------------------------------------------------------------------

function addUser(text) {
  els.empty?.remove();
  const art = el("article", "msg msg--user");
  art.appendChild(el("div", "msg__bubble", text));
  els.thread.appendChild(art);
  scrollDown();
}

function startTurn() {
  els.empty?.remove();
  const art = el("article", "msg msg--coach is-streaming");
  const avatar = el("div", "msg__avatar", "C");
  avatar.setAttribute("aria-hidden", "true");
  const body = el("div", "msg__body");
  art.append(avatar, body);
  els.thread.appendChild(art);
  state.turn = { art, body, text: null, raw: "", trace: null, tools: new Map(), files: null, fileSet: new Set(), pending: false };
  scrollDown();
  return state.turn;
}

function ensureTurn() { return state.turn || startTurn(); }

// État passager (fournisseur saturé, nouvelle tentative…) : une ligne en bas du tour, remplacée
// par la suivante, effacée dès que la réponse avance.
function onStatus(d) {
  const t = ensureTurn();
  if (!t.status) {
    t.status = el("p", "msg__status");
    t.status.setAttribute("role", "status");
  }
  t.status.textContent = String(d.message || "");
  t.body.appendChild(t.status);
  scrollDown();
}

function clearStatus() {
  const t = state.turn;
  if (t && t.status) { t.status.remove(); t.status = null; }
}

// Fin de tour : parmi les blocs de texte écrits APRÈS le dernier outil, seul le dernier est la
// réponse ; les précédents (« le fichier est validé, je résume… ») rejoignent la trace.
function foldTrailingNarration(t) {
  if (!t.trace) return;
  // Seulement les blocs CONSÉCUTIFS en fin de tour : un texte séparé de la fin par une carte
  // d'approbation (ou des fichiers) fait partie de la réponse, il reste visible.
  const blocks = [];
  for (let n = t.body.lastElementChild; n && n.classList.contains("msg__text"); n = n.previousElementSibling) {
    blocks.unshift(n);
  }
  if (t.text) flushText(t);
  for (const node of blocks.slice(0, -1)) {
    if (!node.textContent.trim()) { node.remove(); continue; }
    t.trace.list.appendChild(noteItem(node));
  }
}

function endTurn() {
  const t = state.turn;
  if (!t) return;
  foldTrailingNarration(t);
  t.art.classList.remove("is-streaming");
  if (t.status) { t.status.remove(); t.status = null; }
  if (t.trace) t.trace.details.classList.remove("is-running");
  if (!t.body.children.length) t.art.remove();
  state.turn = null;
}

function traceLabel(trace) {
  const n = trace.list.querySelectorAll(":scope > li:not(.trace__note)").length;
  return `${n} étape${n > 1 ? "s" : ""}`;
}

// Texte écrit juste AVANT un appel d'outil = le coach qui commente son travail (« je lis le
// plan… », voire tout son raisonnement chez certains modèles) : rangé dans la trace repliée.
// La réponse — le texte après le dernier outil — reste seule visible.
function noteItem(node) {
  const li = el("li", "trace__note");
  node.classList.add("trace__note-text");
  li.appendChild(node);                 // retire le bloc du fil
  return li;
}

function ensureTrace(t) {
  // Tout chemin qui ouvre (ou reprend) une trace range d'abord les commentaires qui la
  // précèdent — tous les blocs de texte consécutifs en fin de tour (un modèle peut en écrire
  // plusieurs d'affilée avant d'appeler un outil).
  if (t.text) flushText(t);
  const trailing = [];
  for (let n = t.body.lastElementChild; n && n.classList.contains("msg__text"); n = n.previousElementSibling) {
    trailing.unshift(n);
  }
  t.text = trailing.length ? null : t.text;
  if (trailing.length) t.raw = "";
  const notes = [];
  for (const node of trailing) {
    if (node.textContent.trim()) notes.push(noteItem(node)); else node.remove();
  }
  if (t.trace && t.body.lastElementChild === t.trace.details) {
    for (const note of notes) t.trace.list.appendChild(note);
    return t.trace;
  }
  const details = el("details", "trace is-running");
  const summary = el("summary");
  summary.append(el("span", "trace__dot"), el("span", "trace__label", "Le coach consulte le workspace…"));
  const list = el("ol");
  details.append(summary, list);
  t.body.appendChild(details);
  t.text = null; t.raw = "";
  t.trace = { details, list, label: summary.lastChild };
  for (const note of notes) list.appendChild(note);
  return t.trace;
}

function onToolStart(d) {
  const t = ensureTurn();
  const trace = ensureTrace(t);
  const li = el("li");
  li.append(el("code", null, d.name || "outil"), document.createTextNode(" "), el("span", "trace__sum", d.summary || ""));
  trace.list.appendChild(li);
  trace.label.textContent = traceLabel(trace);
  if (d.id != null) t.tools.set(d.id, li);
}

function onToolEnd(d) {
  const t = ensureTurn();
  let li = d.id != null ? t.tools.get(d.id) : null;
  // Étape déjà rangée dans une trace (même plus haut) : on la met à jour sur place, sans ouvrir
  // une trace vide sous le texte en cours.
  const trace = li ? null : ensureTrace(t);
  if (!li) {
    li = el("li");
    li.append(el("code", null, d.name || "outil"), document.createTextNode(" "), el("span", "trace__sum", d.summary || ""));
    trace.list.appendChild(li);
    trace.label.textContent = traceLabel(trace);
  } else if (d.summary) {
    const sum = li.querySelector(".trace__sum");
    if (sum) sum.textContent = d.summary;
  }
  if (d.ok === false) li.appendChild(el("span", "trace__ko", "échec"));
  (trace ? trace.details : li.closest("details"))?.classList.remove("is-running");
}

// Chaque bloc de texte garde son propre markdown brut : un bloc remplacé par un outil
// avant la prochaine image doit quand même être dessiné (sinon le texte est perdu).
const RAW = new WeakMap();
const dirty = new Set();
let frameQueued = false;

function paint() {
  frameQueued = false;
  for (const node of dirty) renderMarkdown(node, RAW.get(node) || "");
  dirty.clear();
  scrollDown();
}

function onTextDelta(d) {
  const t = ensureTurn();
  const part = d.part || "";
  if (!t.text || t.body.lastElementChild !== t.text || (part && t.textPart && part !== t.textPart)) {
    if (t.text) flushText(t);
    if (t.trace) t.trace.details.classList.remove("is-running");
    t.text = el("div", "msg__text");
    t.raw = "";
    t.body.appendChild(t.text);
  }
  t.textPart = part;
  t.raw += d.text || "";
  RAW.set(t.text, t.raw);
  dirty.add(t.text);
  if (!frameQueued) {
    frameQueued = true;
    requestAnimationFrame(paint);
  }
}

function flushText(t) {
  if (t && t.text) { RAW.set(t.text, t.raw); dirty.delete(t.text); renderMarkdown(t.text, t.raw); }
}

const ROUTES_BY_PREFIX = [
  [/^planning\/[^/]*_decision_/, "index.html#/decisions"],
  [/^planning\/[^/]*_semaine/, "index.html#/semaine"],
  [/^activities\//, "index.html#/seances"],
  [/^rapports\//, "index.html#/rapports"],
  [/^medical\//, "index.html#/sante"],
];

function onFileWritten(d) {
  const path = String(d.path || "");
  if (!path) return;
  const t = ensureTurn();
  if (t.fileSet.has(path)) return;
  t.fileSet.add(path);
  if (!t.files) {
    t.files = el("div", "files");
    t.files.appendChild(el("span", "files__label", "Fichier écrit"));
    t.body.appendChild(t.files);
    t.text = null;
  }
  const route = ROUTES_BY_PREFIX.find(([re]) => re.test(path));
  let chip;
  if (route) { chip = el("a", "file-chip", path); chip.href = route[1]; }
  else chip = el("span", "file-chip", path);
  t.files.appendChild(chip);
}

function onUsage(d) {
  state.lastUsage = d;
  state.sessionCost += Number(d.cost_eur) || 0;
  renderCost();
}

function kTokens(n) { return n >= 1000 ? `${Math.round(n / 100) / 10} k`.replace(".", ",") : String(n); }

function renderCost() {
  const parts = [];
  const u = state.lastUsage;
  // Forfait ChatGPT / Copilot (#266) : aucun coût au jeton, jamais d'euros ni de budget du jour.
  const plan = state.status && state.status.billing && state.status.billing.mode === "subscription"
    ? state.status.billing.label : "";
  // Essai gratuit OpenRouter (#267) : 0 €, mais un quota — dit au lieu d'un budget en euros.
  const free = state.status && state.status.billing && state.status.billing.mode === "free";
  if (plan) parts.push(`inclus dans votre forfait ${plan}`);
  else if (free) parts.push(`essai gratuit (${state.status.billing.quota || "quota gratuit limité"})`);
  else if (state.sessionCost > 0) parts.push(`≈ ${fmtEur(state.sessionCost)} cette conversation`);
  if (u) {
    // Noms du contrat (arc_chat_backend.py) : input_tokens, output_tokens, cache_read_tokens.
    const cached = u.cache_read_tokens || 0;
    const output = u.output_tokens || 0;
    const input = (u.input_tokens || 0) + cached;
    if (input + output > 0) {
      const cache = input ? ` (${Math.round((cached / input) * 100)} % en cache)` : "";
      parts.push(`${kTokens(input + output)} jetons dernier tour${cache}`);
    }
  }
  const b = state.status && state.status.budget;
  if (!plan && !free && b && b.limit_eur != null) parts.push(`budget du jour ${fmtEur(b.spent_eur)} / ${fmtEur(b.limit_eur)}`);
  els.cost.textContent = parts.join(" · ");
}

// ---------------------------------------------------------------------------
// Carte d'approbation
// ---------------------------------------------------------------------------

function diffRows(diff) {
  if (!diff) return [];
  const rows = [];
  const push = (kind, text) => { if (text != null && String(text) !== "") rows.push({ kind, text: String(text) }); };
  const line = (l) => {
    if (typeof l === "string") {
      if (/^\+(?!\+\+)/.test(l)) push("new", l.slice(1).trim());
      else if (/^-(?!--)/.test(l)) push("old", l.slice(1).trim());
      else if (!/^(\+\+\+|---|@@)/.test(l)) push("ctx", l);
    } else if (l && typeof l === "object") {
      const kind = String(l.op || l.kind || l.type || "").toLowerCase();
      if (l.old != null || l.new != null) { push("old", l.old); push("new", l.new); }
      else if (/^(add|new|\+|insert)/.test(kind)) push("new", l.text ?? l.line);
      else if (/^(del|old|-|remove)/.test(kind)) push("old", l.text ?? l.line);
      else push("ctx", l.text ?? l.line);
    }
  };
  if (typeof diff === "string") diff.split("\n").forEach(line);
  else if (Array.isArray(diff)) diff.forEach(line);
  else if (typeof diff === "object") { push("old", diff.old ?? diff.before); push("new", diff.new ?? diff.after); }
  return rows;
}

const RESOLVED = {
  allow: "applied", allowed: "applied", applied: "applied", approved: "applied",
  deny: "refused", denied: "refused", refused: "refused", rejected: "refused", rejected_by_athlete: "refused",
  waiting: "waiting", pending: "pending", expired: "expired",
  cancelled: "cancelled", unexecuted: "unexecuted",
};

function buildApprovalCard(d) {
  const id = d.approval_id || d.id;
  const card = el("div", "action");
  card.dataset.approval = id;
  const head = el("div", "action__head");
  const icon = el("span", "action__icon", "⌚");
  icon.setAttribute("aria-hidden", "true");
  const info = el("div");
  const title = el("strong", null, d.human_summary || d.summary || "Modification demandée par le coach");
  const tool = el("span", "action__tool", d.tool || "");
  const state_ = el("span", "action__state", "Écriture externe : ta confirmation est nécessaire");
  info.append(title, state_);
  if (d.tool) info.appendChild(tool);
  head.append(icon, info);
  card.appendChild(head);

  const rows = diffRows(d.diff);
  if (rows.length) {
    const diff = el("div", "diff");
    diff.setAttribute("role", "group");
    diff.setAttribute("aria-label", "Changement proposé");
    for (const r of rows) {
      const row = el("div", `diff__row${r.kind === "old" ? " diff__row--old" : r.kind === "new" ? " diff__row--new" : ""}`);
      row.append(el("span", null, r.kind === "old" ? "−" : r.kind === "new" ? "+" : ""), document.createTextNode(r.text));
      diff.appendChild(row);
    }
    card.appendChild(diff);
  }
  const btns = el("div", "action__btns");
  card.appendChild(btns);
  return { card, btns, state: state_, id };
}

function setApprovalStatus(entry, status) {
  const { card, btns, state: hint } = entry;
  const norm = RESOLVED[String(status || "").toLowerCase()] || "pending";
  card.classList.remove("is-done", "is-refused", "is-pending");
  btns.replaceChildren();
  if (norm === "waiting" || norm === "pending") {
    // « waiting » : le coach attend la réponse dans ce tour ; « pending » : délai
    // d'attente écoulé, la proposition reste ouverte (page ou notification).
    card.classList.toggle("is-pending", norm === "pending");
    hint.textContent = norm === "waiting"
      ? "Confirmation nécessaire avant toute écriture"
      : "En attente — confirmez depuis la notification ou ici";
    addApprovalButtons(entry);
    return;
  }
  hint.textContent = "";
  hint.hidden = true;
  if (norm === "applied") {
    card.classList.add("is-done");
    btns.appendChild(el("span", "action__result", "Appliqué — le coach exécute la modification"));
  } else if (norm === "refused") {
    card.classList.add("is-refused");
    btns.appendChild(el("span", "action__result action__result--rejected", "Refusé — décision tracée comme refusée par l'athlète"));
  } else if (norm === "cancelled") {
    card.classList.add("is-refused");
    btns.appendChild(el("span", "action__result action__result--rejected", "Annulée (tour interrompu)"));
  } else if (norm === "unexecuted") {
    card.classList.add("is-refused");
    btns.appendChild(el("span", "action__result action__result--rejected", "Approuvée mais non exécutée — redemande au coach"));
  } else {
    btns.appendChild(el("span", "action__result action__result--rejected", "Expiré — la proposition n'est plus valable"));
  }
}

function addApprovalButtons(entry) {
  const ok = el("button", "btn btn--primary", "Appliquer");
  ok.type = "button";
  const no = el("button", "btn btn--ghost", "Refuser");
  no.type = "button";
  const decide = async (decision) => {
    ok.disabled = no.disabled = true;
    try {
      const res = await call("POST", `/approvals/${encodeURIComponent(entry.id)}`, { decision });
      const status = (res && (res.status || res.decision)) || decision;
      setApprovalStatus(entry, status);
      if (decision === "allow") followResume();
    } catch (err) {
      ok.disabled = no.disabled = false;
      showBanner(`Décision non enregistrée : ${err.message}`);
    }
  };
  ok.addEventListener("click", () => decide("allow"));
  no.addEventListener("click", () => decide("deny"));
  entryButtons(entry, ok, no);
}

function entryButtons(entry, ok, no) { entry.btns.append(ok, no); }

function onApprovalRequest(d) {
  const t = ensureTurn();
  const id = d.approval_id || d.id;
  const built = buildApprovalCard(d);
  state.approvals.set(id, built);
  t.body.appendChild(built.card);
  t.text = null;
  setApprovalStatus(built, d.status || "waiting");
  scrollDown();
}

function onApprovalResolved(d) {
  const id = d.approval_id || d.id;
  const status = d.status || d.decision || d.resolution;
  for (const key of [id, `pinned:${id}`]) {
    const entry = state.approvals.get(key);
    if (entry) setApprovalStatus(entry, status);
  }
}

// Une approbation tardive relance un tour côté service (sans flux pour cette page) :
// on relit le journal de la session pour afficher la suite.
function followResume() {
  if (state.streaming || !state.sessionId) return;
  const id = state.sessionId;
  for (const delay of [2500, 7000, 15000]) {
    setTimeout(() => { if (!state.streaming && state.sessionId === id) loadSession(id, { quiet: true }); }, delay);
  }
}

// ---------------------------------------------------------------------------
// Événements SSE / journal
// ---------------------------------------------------------------------------

function showBanner(msg, info = false) {
  els.banner.textContent = msg;
  els.banner.classList.toggle("banner--info", info);
  els.banner.hidden = !msg;
}

function handleEvent(type, d) {
  d = d && typeof d === "object" ? d : {};
  switch (type) {
    case "user_message": endTurn(); addUser(d.text || ""); break;
    case "status": if (!state.replaying) onStatus(d); break;
    case "text_delta": clearStatus(); onTextDelta(d); break;
    case "tool_start": clearStatus(); onToolStart(d); break;
    case "tool_end": onToolEnd(d); break;
    case "approval_request": onApprovalRequest(d); break;
    case "approval_resolved": onApprovalResolved(d); break;
    case "file_written": onFileWritten(d); break;
    case "usage": onUsage(d); break;
    case "error": if (!state.replaying) showBanner(d.message || d.reason || d.error || "Erreur du service de chat."); break;
    case "done": {
      flushText(state.turn);
      if (state.replaying) { /* historique : pas de bandeau périmé */ }
      else if (d.reason === "budget") showBanner("Budget quotidien atteint — le coach reprendra demain (ou augmentez [chat].daily_budget_eur).", true);
      else if (d.reason === "pending_approval") showBanner("Proposition en attente d'approbation — appliquez-la depuis la carte ou la notification.", true);
      endTurn();
      break;
    }
    default: break; // événement inconnu : ignoré
  }
}

async function readSse(res, onEvent) {
  const reader = res.body.getReader();
  const decoder = new TextDecoder("utf-8");
  let buf = "";
  const frame = (raw) => {
    let event = "message";
    const data = [];
    for (const line of raw.split(/\r?\n/)) {
      if (!line || line.startsWith(":")) continue; // commentaire / ping
      const i = line.indexOf(":");
      const field = i < 0 ? line : line.slice(0, i);
      const value = i < 0 ? "" : line.slice(i + 1).replace(/^ /, "");
      if (field === "event") event = value;
      else if (field === "data") data.push(value);
    }
    if (!data.length) return;
    let payload = {};
    try { payload = JSON.parse(data.join("\n")); } catch { payload = { text: data.join("\n") }; }
    onEvent(event, payload);
  };
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    let m;
    while ((m = /\r?\n\r?\n/.exec(buf))) {
      frame(buf.slice(0, m.index));
      buf = buf.slice(m.index + m[0].length);
    }
  }
  buf += decoder.decode();
  if (buf.trim()) frame(buf);
}

// ---------------------------------------------------------------------------
// Envoi / interruption
// ---------------------------------------------------------------------------

function setBusy(busy) {
  state.streaming = busy;
  els.send.hidden = busy;
  els.stop.hidden = !busy;
  els.send.disabled = busy || !state.sessionId;
  els.input.disabled = busy || !state.sessionId;
  els.select.disabled = busy;
  els.newBtn.disabled = busy;
  if (!busy) els.input.focus();
}

async function sendMessage(text) {
  if (!text || state.streaming || !state.sessionId) return;
  showBanner("");
  addUser(text);
  startTurn();
  setBusy(true);
  state.abort = new AbortController();
  const sid = state.sessionId;
  try {
    const res = await fetch(`${API}/sessions/${encodeURIComponent(sid)}/messages`, {
      method: "POST",
      headers: { ...CSRF, "Content-Type": "application/json", Accept: "text/event-stream" },
      body: JSON.stringify({ text }),
      signal: state.abort.signal,
    });
    if (!res.ok) {
      let msg = `HTTP ${res.status}`;
      try { msg = (await res.json()).error || msg; } catch { /* corps non JSON */ }
      if (res.status === 409) msg = "Une réponse est déjà en cours pour cette conversation.";
      if (res.status === 429) msg = "Trop de messages d'affilée — patientez une minute.";
      throw new Error(msg);
    }
    await readSse(res, handleEvent);
  } catch (err) {
    if (err.name !== "AbortError") showBanner(`Connexion interrompue : ${err.message}`);
  } finally {
    flushText(state.turn);
    endTurn();
    setBusy(false);
    state.abort = null;
    refreshStatus();
    refreshSessions();
  }
}

async function interrupt() {
  if (!state.streaming || !state.sessionId) return;
  els.stop.disabled = true;
  try {
    await call("POST", `/sessions/${encodeURIComponent(state.sessionId)}/interrupt`, {});
  } catch (err) {
    showBanner(`Interruption impossible : ${err.message}`);
  } finally {
    els.stop.disabled = false;
  }
}

// ---------------------------------------------------------------------------
// Sessions
// ---------------------------------------------------------------------------

function sessionLabel(s) {
  let when = "";
  try { when = new Intl.DateTimeFormat("fr-FR", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }).format(new Date(s.updated || s.created)); } catch { /* date illisible */ }
  const pending = s.pending_approvals ? ` · ${s.pending_approvals} en attente` : "";
  return `${s.title || "Nouvelle conversation"} — ${when}${pending}`;
}

async function refreshSessions() {
  try {
    const data = await call("GET", "/sessions");
    const list = Array.isArray(data) ? data : data.sessions || [];
    els.select.replaceChildren(...list.map((s) => {
      const o = el("option", null, sessionLabel(s));
      o.value = s.id;
      return o;
    }));
    if (state.sessionId) els.select.value = state.sessionId;
    return list;
  } catch {
    return [];
  }
}

function renderHistory(events) {
  els.thread.replaceChildren();
  els.empty = null;
  state.turn = null;
  state.approvals.forEach((v, k) => { if (!k.startsWith("pinned:")) state.approvals.delete(k); });
  state.sessionCost = 0;
  state.lastUsage = null;
  state.replaying = true;
  for (const e of events) handleEvent(e.type, e.data);
  state.replaying = false;
  flushText(state.turn);
  endTurn();
  if (!els.thread.children.length) showEmptyThread();
  renderCost();
  scrollDown();
}

function showEmptyThread() {
  const p = el("p", "chat__empty", "Pose une question au coach, ou utilise une commande rapide ci-dessous.");
  p.id = "empty";
  els.thread.appendChild(p);
  els.empty = p;
}

// Un tour tourne déjà dans cette conversation (autre onglet, reprise après approbation) :
// on bloque la saisie (sinon 409) et on relit la session jusqu'à la fin du tour.
function watchRunning(id) {
  clearTimeout(state.pollTimer);
  state.pollTimer = setTimeout(async () => {
    if (state.sessionId !== id || state.streaming) return;
    try {
      const detail = await call("GET", `/sessions/${encodeURIComponent(id)}`);
      if (state.sessionId !== id || state.streaming) return;
      renderHistory(detail.events || detail.log || []);
      if (detail.running) { watchRunning(id); return; }
      showBanner("");
      els.input.disabled = false;
      els.send.disabled = false;
      els.input.focus();
      refreshStatus();
      refreshSessions();
    } catch {
      watchRunning(id);
    }
  }, 2000);
}

async function loadSession(id, { quiet = false } = {}) {
  clearTimeout(state.pollTimer);
  try {
    const detail = await call("GET", `/sessions/${encodeURIComponent(id)}`);
    state.sessionId = id;
    const events = detail.events || detail.log || [];
    renderHistory(events);
    if (detail.cost_eur != null && !state.sessionCost) { state.sessionCost = Number(detail.cost_eur) || 0; renderCost(); }
    els.select.value = id;
    const running = Boolean(detail.running) && !state.streaming;
    els.input.disabled = state.streaming || running;
    els.send.disabled = state.streaming || running;
    els.newBtn.disabled = state.streaming;
    els.select.disabled = state.streaming;
    if (running) {
      showBanner("Une réponse est en cours dans cette conversation — la saisie reprendra à la fin.", true);
      watchRunning(id);
    } else if (!quiet) {
      els.input.focus();
    }
  } catch (err) {
    showBanner(`Conversation illisible : ${err.message}`);
  }
}

async function newSession() {
  clearTimeout(state.pollTimer);
  showBanner("");
  try {
    const res = await call("POST", "/sessions", {});
    state.sessionId = res.id;
    els.thread.replaceChildren();
    showEmptyThread();
    state.sessionCost = 0;
    state.lastUsage = null;
    renderCost();
    await refreshSessions();
    els.select.value = res.id;
    els.input.disabled = false;
    els.send.disabled = false;
    els.input.focus();
  } catch (err) {
    showBanner(`Impossible de créer la conversation : ${err.message}`);
  }
}

// ---------------------------------------------------------------------------
// Statut du service, lien profond d'approbation
// ---------------------------------------------------------------------------

async function refreshStatus() {
  try {
    state.status = await call("GET", "/status");
    els.backend.textContent = `Backend : ${state.status.backend || "—"}${state.status.model ? ` · ${state.status.model}` : ""}`;
    $("#ctx-user").textContent = state.status.user ? `Connecté en tant que ${state.status.user}` : "";
    renderCost();
    return state.status;
  } catch (err) {
    return null;
  }
}

function showDisabled(kind, detail) {
  els.thread.replaceChildren();
  const box = el("div", "disabled-panel");
  const title = kind === "disabled" ? "Le chat coach n'est pas activé" : kind === "auth" ? "Authentification requise" : "Service de chat injoignable";
  box.appendChild(el("h2", null, title));
  const hint = kind === "disabled"
    ? "Activez-le avec [chat] enabled = true dans config/workspace.user.toml, puis lancez scripts/coach-chat.sh start."
    : kind === "auth"
      ? "Votre session n'a pas été reconnue par le service de chat. Reconnectez-vous puis rechargez la page."
      : "Lancez scripts/coach-chat.sh start (ou vérifiez le conteneur chat), puis rechargez la page.";
  box.appendChild(el("p", null, hint));
  if (detail) box.appendChild(el("p", "muted", detail));
  const p = el("p");
  const a = el("a", null, "Documentation : dashboard / chat");
  a.href = DOCS_URL; a.rel = "noopener noreferrer"; a.target = "_blank";
  p.appendChild(a);
  box.appendChild(p);
  els.thread.appendChild(box);
  els.select.disabled = true;
  els.newBtn.disabled = true;
  els.input.disabled = true;
  els.send.disabled = true;
}

async function showApprovalDeepLink(id) {
  const key = `pinned:${id}`;
  if (state.approvals.has(key)) return;
  try {
    const d = await call("GET", `/approvals/${encodeURIComponent(id)}`);
    const built = buildApprovalCard({ ...d, approval_id: id });
    state.approvals.set(key, built);
    // Carte épinglée en haut : le lien profond doit marcher même si la session n'est pas chargée.
    els.pinned.replaceChildren(built.card);
    setApprovalStatus(built, d.status || "pending");
    built.card.scrollIntoView({ block: "nearest" });
  } catch (err) {
    showBanner(err.status === 404 ? "Cette proposition n'existe plus (expirée ou déjà traitée)." : `Proposition illisible : ${err.message}`);
  }
}

function checkHash() {
  const m = /approval=([^&]+)/.exec(location.hash);
  if (m) showApprovalDeepLink(decodeURIComponent(m[1]));
}

// ---------------------------------------------------------------------------
// Panneau « Ce que voit le coach » + en-tête
// ---------------------------------------------------------------------------

async function getJson(path) {
  const res = await fetch(path, { headers: { Accept: "application/json" } });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

function renderObjective(s) {
  const box = $("#objective");
  const o = s && s.objective;
  if (!o || !o.race_date) return;
  const left = o.days_left;
  const when = left > 0 ? `J-${left}` : left === 0 ? "Jour de course" : `Terminé il y a ${-left} j`;
  const meta = [F.dateLong(o.race_date), o.distance_m ? F.distance(o.distance_m, 0) : null].filter(Boolean).join(" · ");
  box.replaceChildren();
  const count = el("span", `objective__count${left < 0 ? " is-past" : ""}`, when);
  const text = el("span", "objective__text");
  text.append(el("strong", null, o.name || "Objectif"), el("span", null, meta));
  box.append(count, text);
}

function renderStaff(s) {
  const all = ["coach", "medical", "nutritionist", "course-strategist"];
  const enabled = new Set((s && s.settings && s.settings.agents) || all);
  const ul = $("#ctx-staff");
  ul.replaceChildren();
  for (const name of all) {
    const li = el("li");
    const on = enabled.has(name);
    li.append(el("span", `dot${on ? " dot--on" : ""}`), document.createTextNode(name));
    if (!on) { li.appendChild(document.createTextNode(" ")); li.appendChild(el("em", null, "non activé")); }
    ul.appendChild(li);
  }
}

function renderWeek(week) {
  const box = $("#ctx-session");
  const wbox = $("#ctx-week");
  box.replaceChildren();
  wbox.replaceChildren();
  const today = week.today;
  const session = (week.sessions || []).find((x) => x.date === today);
  if (session) {
    box.appendChild(el("p", "ctx-session-title", session.title || F.SPORT[session.sport] || "Séance"));
    const bits = [session.planned_duration_s ? F.duration(session.planned_duration_s) : null,
      session.intensity || null,
      session.planned_elevation_m ? `${F.elevation(session.planned_elevation_m)} D+` : null].filter(Boolean);
    if (bits.length) box.appendChild(el("p", "ctx-soft", bits.join(" · ")));
    const status = session.status || "planned";
    const chip = el("span", `chip chip--status-${status}`);
    chip.append(el("span", "chip__dot"), document.createTextNode((F.STATUS[status] || status).toLowerCase()));
    box.appendChild(chip);
  } else {
    box.appendChild(el("p", "ctx-soft", "Rien de planifié aujourd'hui."));
  }

  const wk = week.week || {};
  const doneS = (week.activities || []).reduce((a, x) => a + (x.duration_s || 0), 0);
  const doneEl = (week.activities || []).reduce((a, x) => a + (x.elevation_gain_m || 0), 0);
  const target = wk.target_duration_s || (week.sessions || []).reduce((a, x) => a + (x.planned_duration_s || 0), 0);
  $("#ctx-week-title").textContent = week.week_start ? `Semaine du ${F.dayShort(week.week_start)}` : "Semaine";
  if (target > 0 || doneS > 0) {
    const bar = el("div", "bar");
    const fill = el("span", "bar__fill");
    fill.style.setProperty("width", `${target > 0 ? Math.min(100, Math.round((doneS / target) * 100)) : 0}%`);
    bar.appendChild(fill);
    wbox.appendChild(bar);
    const txt = [`${F.duration(doneS)}${target > 0 ? ` / ${F.duration(target)}` : ""}`,
      doneEl > 0 || wk.target_elevation_m ? `${F.elevation(doneEl)}${wk.target_elevation_m ? ` / ${F.elevation(wk.target_elevation_m)}` : ""} D+` : null].filter(Boolean).join(" · ");
    wbox.appendChild(el("p", "ctx-soft", txt));
  } else {
    wbox.appendChild(el("p", "ctx-soft", "Pas de plan pour cette semaine."));
  }
}

// Même liste que le tableau de bord (nav.js) ; la page Coach reste marquée comme courante.
function renderNav(settings) {
  const nav = $("#nav");
  if (!nav) return;
  const links = navItems(settings || {}).map(([h, l]) => {
    const a = el("a", null, l);
    a.href = `index.html#/${h}`;
    return a;
  });
  const coach = el("a", null, "Coach");
  coach.href = "chat.html";
  coach.setAttribute("aria-current", "page");
  nav.replaceChildren(...links, coach);
}

async function loadContext() {
  const [summary, week] = await Promise.allSettled([getJson("api/summary"), getJson("api/week")]);
  renderNav(summary.status === "fulfilled" ? summary.value.settings : null);
  if (summary.status === "fulfilled") {
    F.setUnits(summary.value.settings && summary.value.settings.units);
    renderObjective(summary.value);
    renderStaff(summary.value);
  } else renderStaff(null);
  if (week.status === "fulfilled") {
    try { renderWeek(week.value); } catch { /* champ manquant : on garde le panneau tel quel */ }
  } else {
    $("#ctx-session").replaceChildren(el("p", "ctx-soft", "Indisponible."));
    $("#ctx-week").replaceChildren(el("p", "ctx-soft", "Indisponible."));
  }
}

// ---------------------------------------------------------------------------
// Thème, saisie, démarrage
// ---------------------------------------------------------------------------

function setupTheme() {
  const btn = $("#theme");
  const forced = new URLSearchParams(location.search).get("theme");
  const saved = (() => { try { return localStorage.getItem("arc-theme"); } catch { return null; } })();
  const theme = ["dark", "light"].includes(forced) ? forced : saved;
  if (theme) document.documentElement.dataset.theme = theme;
  btn.addEventListener("click", () => {
    const dark = document.documentElement.dataset.theme
      ? document.documentElement.dataset.theme === "dark"
      : window.matchMedia("(prefers-color-scheme: dark)").matches;
    const next = dark ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    try { localStorage.setItem("arc-theme", next); } catch { /* stockage indisponible */ }
  });
}

function setupComposer() {
  els.form.addEventListener("submit", (e) => {
    e.preventDefault();
    const text = els.input.value.trim();
    if (!text) return;
    els.input.value = "";
    els.input.style.height = "";
    sendMessage(text);
  });
  els.input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); els.form.requestSubmit(); }
  });
  els.input.addEventListener("input", () => {
    els.input.style.height = "auto";
    els.input.style.height = `${els.input.scrollHeight}px`;
  });
  document.querySelectorAll(".quick__btn").forEach((b) => b.addEventListener("click", () => {
    if (els.input.disabled) return;
    els.input.value = b.dataset.cmd;
    els.input.focus();
    if (!b.dataset.cmd.endsWith(" ")) els.form.requestSubmit();
  }));
  els.stop.addEventListener("click", interrupt);
  els.newBtn.addEventListener("click", newSession);
  els.select.addEventListener("change", () => { if (els.select.value) loadSession(els.select.value); });
}

async function boot() {
  setupTheme();
  setupComposer();
  loadContext();
  showVersion();
  showSyncPill();
  window.addEventListener("hashchange", checkHash);

  let status;
  try {
    status = await call("GET", "/status");
  } catch (err) {
    if (err.status === 401 || err.status === 403) showDisabled("auth", err.message);
    else if (err.status === 404) showDisabled("disabled");
    else showDisabled("unreachable", err.message);
    return;
  }
  if (!status || status.enabled === false) { showDisabled("disabled"); return; }
  state.status = status;
  els.backend.textContent = `Backend : ${status.backend || "—"}${status.model ? ` · ${status.model}` : ""}`;
  $("#ctx-user").textContent = status.user ? `Connecté en tant que ${status.user}` : "";
  renderCost();
  checkHash();

  const list = await refreshSessions();
  els.select.disabled = false;
  els.newBtn.disabled = false;
  if (list.length) await loadSession(list[0].id, { quiet: !!location.hash });
  else await newSession();
  els.input.disabled = !state.sessionId;
  els.send.disabled = !state.sessionId;
}

boot();
