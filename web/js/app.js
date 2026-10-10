// Tableau de bord ai-running-coach — lecture seule, servi par scripts/arc_serve.py.
import * as F from "./format.js";
import { navItems } from "./nav.js";
import { timeChart, attachCursor, verdictStrip, yearCalendar, blockFrise } from "./chart.js";
import { resampleByDistance, colorModes, sessionMap } from "./map.js";
import { roadbookHtml, wireRoadbook } from "./roadbook.js";

const $ = (sel, root = document) => root.querySelector(sel);
const main = $("#main");
const cache = new Map();
let SUMMARY = null;

async function api(path, { fresh = false } = {}) {
  if (!fresh && cache.has(path)) return cache.get(path);
  const res = await fetch(`/api/${path}`, { headers: { Accept: "application/json" } });
  if (!res.ok) {
    let detail = "";
    try { detail = (await res.json()).error || ""; } catch { /* corps non JSON */ }
    throw new Error(`${res.status} ${detail}`.trim());
  }
  const data = await res.json();
  cache.set(path, data);
  return data;
}

// ---------------------------------------------------------------------------
// Petits composants
// ---------------------------------------------------------------------------

const chip = (kind, value, label) => `<span class="chip chip--${kind}-${F.esc(value)}"><span class="chip__dot" aria-hidden="true"></span>${F.esc(label)}</span>`;
const verdictChip = (v) => (v ? chip("verdict", v, F.VERDICT[v] || v) : "");
const weatherChip = (w) => (w ? chip("weather", w, F.WEATHER[w] || w) : "");
const statusChip = (s) => (s ? chip("status", s, F.STATUS[s] || s) : "");
const triggerChip = (t) => (t ? chip("trigger", t, F.TRIGGER[t] || t) : "");
const outcomeChip = (o) => (o ? chip("outcome", o, F.DECISION_OUTCOME[o] || o) : "");
const effectChip = (e) => (e ? chip("effect", e, F.DECISION_EFFECT[e] || e) : "");

// Effet des décisions (#175) : détail d'une évaluation (signaux, fenêtres, chiffres).
// Valeurs arrondies à l'affichage (moyennes de fenêtre : 3 décimales côté API) ; conformité en %.
const effectValue = (signal, v) => (signal === "compliance" ? `${F.num(v * 100)} %` : F.num(v, 1));
function effectDetailHtml(ev) {
  if (!ev) return "";
  const rows = (ev.signals || []).map((s) => `<tr><th scope="row">${F.esc(s.label)}</th>
      <td>${F.dayShort(s.pre.from)} → ${F.dayShort(s.pre.to)} (${s.pre.n})</td><td>${F.dayShort(s.post.from)} → ${F.dayShort(s.post.to)} (${s.post.n})</td>
      <td>${effectValue(s.signal, s.pre_value)} → ${effectValue(s.signal, s.post_value)}</td><td>${F.esc(F.DECISION_EFFECT[s.verdict] || s.verdict)}</td></tr>`).join("");
  const skipped = (ev.skipped || []).map((s) => `<li>${F.esc(s.label)} : ${F.esc(s.reason)}</li>`).join("");
  return `${ev.reason ? `<p class="muted">${F.esc(ev.reason)}${ev.mature_on ? ` (au plus tôt le ${F.dayLong(ev.mature_on)})` : ""}</p>` : ""}
    ${ev.action && F.DECISION_ACTION[ev.action] ? `<p class="muted">Nature de l'action (déduite de l'avant / après) : ${F.esc(F.DECISION_ACTION[ev.action])}</p>` : ""}
    ${(ev.overlaps || []).length ? `<p class="muted">Autre(s) décision(s) dans la même fenêtre : effets confondus.</p>` : ""}
    ${rows ? `<div class="table-wrap"><table class="data data--compact"><thead><tr><th scope="col">Signal</th><th scope="col">Avant (n)</th><th scope="col">Après (n)</th><th scope="col">Valeurs</th><th scope="col">Lecture</th></tr></thead><tbody>${rows}</tbody></table></div>` : ""}
    ${skipped ? `<p class="muted">Signaux non évalués :</p><ul>${skipped}</ul>` : ""}`;
}

// Journal des décisions (#55) : lien de la documentation des garde-fous (#52),
// cité depuis « Décisions » et depuis l'encart « Pourquoi aujourd'hui ? ».
const GUARDRAILS_DOC_URL = "https://mmornati.github.io/ai-running-coach/guardrails/#les-sept-regles";

// `decision.inputs`/`before`/`after` : valeurs libres (revue de code #55, nit) —
// un objet imbriqué (rare, mais le contrat ne l'interdit pas) doit se lire
// comme du JSON plutôt que devenir le peu lisible `[object Object]` d'un
// simple `String(v)`.
const fmtInputValue = (v) => (v !== null && typeof v === "object" ? JSON.stringify(v) : String(v));

// Libellé d'un champ `before`/`after` de décision par sa CLÉ (revue de code #55,
// should-fix 1) : une clé absente de `after` ne veut PAS dire « valeur vide » —
// `formatDecisionDiffValue` reste `null` dans ce cas précis, à distinguer par
// l'appelant (`viewDecision`) d'une valeur réellement effacée.
const INTENSITY_FULL_LABEL = {
  rest: "Repos", recovery: "Récupération", endurance: "Endurance", tempo: "Tempo",
  threshold: "Seuil", vo2max: "VO2max", race: "Course", strength: "Renforcement",
};
function formatDecisionDiffValue(key, value) {
  if (value === undefined) return null;
  if (key === "planned_duration_s") return F.duration(value);
  if (key === "status") return F.STATUS[value] || value;
  if (key === "date") return F.dayLong(value);
  if (key === "intensity") return INTENSITY_FULL_LABEL[value] || value;
  return fmtInputValue(value);
}

function note(text) {
  return `<p class="note">${text}</p>`;
}

function empty(title, body) {
  return `<div class="empty"><h3>${F.esc(title)}</h3><p>${body}</p></div>`;
}

function header(title, sub = "") {
  return `<header class="view-head"><h1>${F.esc(title)}</h1>${sub ? `<p class="view-sub">${sub}</p>` : ""}</header>`;
}

/** Jauge horizontale : valeur située dans une bande de référence. */
function rangeBar(value, lo, hi, min, max, cls = "") {
  if (value === null || value === undefined) return `<svg class="range" viewBox="0 0 200 14" aria-hidden="true"></svg>`;
  const span = max - min || 1;
  const px = (v) => Math.max(0, Math.min(200, ((v - min) / span) * 200));
  const band = lo !== null && lo !== undefined && hi !== null && hi !== undefined
    ? `<rect class="range__band" x="${px(lo)}" y="3" width="${Math.max(2, px(hi) - px(lo))}" height="8" rx="4"/>` : "";
  return `<svg class="range ${cls}" viewBox="0 0 200 14" aria-hidden="true"><rect class="range__track" x="0" y="5" width="200" height="4" rx="2"/>${band}<circle class="range__dot" cx="${px(value)}" cy="7" r="5"/></svg>`;
}

function readout(el, html) {
  if (el) el.innerHTML = html;
}

// ---------------------------------------------------------------------------
// Listes longues : recherche, tri et pagination côté navigateur
// ---------------------------------------------------------------------------

// Comparaison insensible à la casse ET aux accents (« eze » trouve « Èze »).
const fold = (s) => String(s ?? "").normalize("NFD").replace(/\p{Diacritic}/gu, "").toLowerCase();

const CHEVRON = {
  left: `<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M10 3 5 8l5 5"/></svg>`,
  right: `<svg viewBox="0 0 16 16" aria-hidden="true"><path d="m6 3 5 5-5 5"/></svg>`,
  sort: `<svg viewBox="0 0 16 16" aria-hidden="true"><path d="m5 6 3-3 3 3M5 10l3 3 3-3"/></svg>`,
  up: `<svg viewBox="0 0 16 16" aria-hidden="true"><path d="m4 10 4-4 4 4"/></svg>`,
  down: `<svg viewBox="0 0 16 16" aria-hidden="true"><path d="m4 6 4 4 4-4"/></svg>`,
};

/** Découpe `items` en pages ; `page` est ramenée dans les bornes (filtre plus strict = moins de pages). */
function paginate(items, page, size) {
  const pages = Math.max(1, Math.ceil(items.length / size));
  const p = Math.min(Math.max(1, page || 1), pages);
  const start = (p - 1) * size;
  return { page: p, pages, from: items.length ? start + 1 : 0, to: Math.min(items.length, start + size), slice: items.slice(start, start + size) };
}

/** Pages affichées : première, dernière, la courante et ses voisines ; « … » entre deux trous. */
function pageWindow(page, pages) {
  const keep = new Set([1, pages, page - 1, page, page + 1].filter((n) => n >= 1 && n <= pages));
  const out = [];
  let prev = 0;
  for (const n of [...keep].sort((a, b) => a - b)) {
    if (n - prev > 1) out.push(null);
    out.push(n);
    prev = n;
  }
  return out;
}

/** Pagination : boutons `data-page`, à câbler par délégation par la vue. Rien sous une seule page. */
function pagerHtml(pg, total, label) {
  if (pg.pages <= 1) return "";
  const nums = pageWindow(pg.page, pg.pages).map((n) => (n === null
    ? `<span class="pager__gap" aria-hidden="true">…</span>`
    : `<button type="button" class="pager__num" data-page="${n}" ${n === pg.page ? `aria-current="page"` : ""} aria-label="Page ${n}">${n}</button>`)).join("");
  return `<nav class="pager" aria-label="${F.esc(label)}">
    <p class="pager__range"><strong>${F.num(pg.from)}–${F.num(pg.to)}</strong> sur ${F.num(total)}</p>
    <div class="pager__pages">
      <button type="button" class="pager__step" data-page="${pg.page - 1}" ${pg.page === 1 ? "disabled" : ""}>${CHEVRON.left}<span>Précédente</span></button>
      ${nums}
      <button type="button" class="pager__step" data-page="${pg.page + 1}" ${pg.page === pg.pages ? "disabled" : ""}><span>Suivante</span>${CHEVRON.right}</button>
    </div></nav>`;
}

/** En-tête de colonne triable : un bouton `data-sort` (la vue décide du sens). */
function sortTh(key, label, state, num = true, cls = "") {
  const on = state.sort === key;
  const aria = on ? (state.dir === 1 ? "ascending" : "descending") : "none";
  return `<th scope="col" class="${[num ? "num" : "", cls].filter(Boolean).join(" ")}" aria-sort="${aria}"><button type="button" class="th-sort${on ? " is-on" : ""}" data-sort="${key}">${label}${on ? (state.dir === 1 ? CHEVRON.up : CHEVRON.down) : CHEVRON.sort}</button></th>`;
}

/** Champ de recherche d'une liste longue (filtré à la frappe, sans recharger la vue). */
function searchField(id, value, placeholder, label) {
  return `<label class="search"><span class="visually-hidden">${F.esc(label)}</span>
    <svg viewBox="0 0 16 16" aria-hidden="true"><circle cx="7" cy="7" r="4.5"/><path d="m10.5 10.5 3.5 3.5"/></svg>
    <input type="search" id="${id}" value="${F.esc(value)}" placeholder="${F.esc(placeholder)}" autocomplete="off" spellcheck="false"></label>`;
}

const debounce = (fn, ms = 140) => {
  let t = null;
  return (...args) => { clearTimeout(t); t = setTimeout(() => fn(...args), ms); };
};

// ---------------------------------------------------------------------------
// Conformité plan vs réalisé (#33)
// ---------------------------------------------------------------------------

const pctClass = (pct) => (pct === null || pct === undefined ? "" : pct >= 80 ? "pos" : pct < 50 ? "neg" : "");
const ratioText = (r) => (r === null || r === undefined ? "—" : `${F.num(r * 100, 0)}\u00a0%`);

const INTENSITY_LABEL = { easy: "Facile", quality: "Qualité", other: "Autre" };

/** Le texte d'une semaine de conformité : soit un %, soit ce qui explique son absence. */
function complianceWeekLabel(c) {
  if (!c) return "pas de plan";
  if (c.sessions_planned === 0) return "séances à venir";
  return `${F.num(c.sessions_pct, 0)}\u00a0% des séances (${c.sessions_done}/${c.sessions_planned})`;
}

/** Bloc « Conformité » de la vue Semaine : % de séances faites, ratios durée/D+, par intensité. */
function complianceSection(c, trail) {
  if (!c) {
    return `<section class="band"><h2>Conformité</h2>${note("Pas de séance planifiée cette semaine-là (hors repos) : conformité non calculée.")}</section>`;
  }
  const intensityRows = Object.entries(c.by_intensity)
    .filter(([, v]) => v.sessions_planned > 0)
    .map(([name, v]) => `<div><dt>${INTENSITY_LABEL[name] || name}</dt><dd class="${pctClass(v.sessions_pct)}">${F.num(v.sessions_pct, 0)}\u00a0%<small> (${v.sessions_done}/${v.sessions_planned})</small></dd></div>`)
    .join("");
  const excluded = [
    c.sessions_rest ? `${c.sessions_rest} repos` : null,
    c.sessions_cancelled ? `${c.sessions_cancelled} annulée${c.sessions_cancelled > 1 ? "s" : ""}` : null,
    c.sessions_moved ? `${c.sessions_moved} déplacée${c.sessions_moved > 1 ? "s" : ""}` : null,
    c.sessions_future ? `${c.sessions_future} à venir` : null,
    c.sessions_pending ? `${c.sessions_pending} en attente (aujourd'hui)` : null,
  ].filter(Boolean).join(" · ");
  return `<section class="band"><h2>Conformité</h2>
    <dl class="facts facts--grid">
      <div><dt>Séances faites</dt><dd class="${pctClass(c.sessions_pct)}">${c.sessions_pct !== null ? F.num(c.sessions_pct, 0) + "\u00a0%" : "—"}<small> (${c.sessions_done}/${c.sessions_planned})</small></dd></div>
      <div><dt>Durée réalisée / planifiée</dt><dd>${ratioText(c.duration_ratio)}</dd></div>
      ${trail ? `<div><dt>D+ réalisé / planifié</dt><dd>${ratioText(c.elevation_ratio)}</dd></div>` : ""}
      ${intensityRows}
    </dl>
    ${excluded ? note(`Hors calcul : ${F.esc(excluded)}.`) : ""}
  </section>`;
}

/** Mini-tendance 4 semaines pour la vue Aujourd'hui : une barre SVG par semaine.
 *
 * En SVG (comme `rangeBar`), pas en CSS : la hauteur varie par valeur, et le CSP du
 * tableau de bord (`style-src 'self'`, sans `unsafe-inline`) interdit tout style
 * posé en ligne — seuls des attributs SVG (`height`, `y`) peuvent varier par item.
 *
 * `role="img"` masque aux lecteurs d'écran tout contenu interne (les `<title>` par
 * barre ne sont donc pas exposés individuellement) : l'`aria-label` du `<svg>` est
 * construit à partir des mêmes données que les `<title>`, pour porter toute
 * l'information par un seul nom accessible plutôt que de la perdre.
 */
function complianceTrend(trend) {
  if (!trend || !trend.some((w) => w.compliance)) return "";
  const barW = 40, gap = 10, chartH = 36;
  const bars = trend.map((w, i) => {
    const c = w.compliance;
    const pct = c && c.sessions_planned > 0 ? c.sessions_pct : null;
    const barH = pct !== null ? Math.max(3, (pct / 100) * chartH) : 3;
    const cls = pct === null ? "trend__bar--none" : pct >= 80 ? "trend__bar--pos" : pct < 50 ? "trend__bar--neg" : "trend__bar--mid";
    const title = `${F.dayShort(w.week_start)} : ${complianceWeekLabel(c)}`;
    const x = i * (barW + gap);
    return `<rect class="trend__bar ${cls}" x="${x}" y="${chartH - barH}" width="${barW}" height="${barH}" rx="3"><title>${F.esc(title)}</title></rect>`;
  }).join("");
  const totalW = trend.length * barW + (trend.length - 1) * gap;
  const label = `Conformité au plan sur les 4 dernières semaines : ${trend.map((w) => `${F.dayShort(w.week_start)} : ${complianceWeekLabel(w.compliance)}`).join(" ; ")}.`;
  return `<svg class="trend" viewBox="0 0 ${totalW} ${chartH}" role="img" aria-label="${F.esc(label)}">${bars}</svg>
    <p class="muted">Conformité au plan, 4 dernières semaines. <a href="#/semaine">Détail</a></p>`;
}

/** Tuile « Acclimatation à la chaleur » (#38) — Aujourd'hui.
 *
 * Affichée quand elle est utile MAINTENANT : au moins une séance chaude sur la
 * fenêtre de 14 j (le compte a du contenu), OU la météo de la course de l'objectif
 * est déjà connue et chaude (`objective_forecast_hot === true`). Le seul critère
 * « objectif » resterait presque toujours invisible en dehors de la semaine de
 * course : `wttr.in` ne prévoit qu'à quelques jours, donc `objective_forecast_hot`
 * est `null` (inconnu, pas « pas chaud ») pendant tout le bloc d'entraînement — d'où
 * la combinaison des deux signaux plutôt que le seul critère cité par #38.
 */
function heatTile(heat) {
  if (!heat || (heat.hot_sessions <= 0 && heat.objective_forecast_hot !== true)) return "";
  const n = heat.hot_sessions;
  const t = heat.threshold_c;
  const tTxt = t != null && !Number.isInteger(t) ? F.num(t, 1) : F.num(t);
  const bits = [`${n} séance${n > 1 ? "s" : ""} chaude${n > 1 ? "s" : ""} (≥ ${tTxt} °C) sur ${heat.window_days} j`];
  if (heat.hot_duration_s) bits.push(`${F.duration(heat.hot_duration_s)} cumulée${n > 1 ? "s" : ""}`);
  if (heat.objective_forecast_hot) bits.push("météo chaude prévue pour l'objectif");
  if (heat.sessions_without_weather) bits.push(`${heat.sessions_without_weather} sans météo (non compté${heat.sessions_without_weather > 1 ? "es" : "e"})`);
  return `<p class="weather">${chip("weather", n > 0 ? "orange" : "yellow", "Acclimatation chaleur")} <span>${bits.join(" · ")}</span></p>`;
}

// Libellés courts, en français, des facteurs du drapeau composite de risque de
// blessure (#57) — affichage seulement, jamais recalculé côté client (l'API
// `/api/injury-risk` rend déjà `factors[].label`, ce fallback ne sert que si un
// futur id de facteur n'était pas encore connu de cette version du JS).
const INJURY_FACTOR_FALLBACK = {
  acwr: "ACWR élevé", monotony: "Monotonie élevée", pain: "Douleur déclarée",
  rpe_hr_mismatch: "Effort perçu bien supérieur à la charge FC",
  sleep_debt: "Dette de sommeil", red_verdict: "Verdict santé rouge récent",
};

/** Formatage PAR FACTEUR (#57, revue de code #104, should-fix 2) : l'API rend
 * déjà `observed`/`threshold` dans l'unité pertinente pour chaque facteur
 * (score /10 pour `pain`, heures pour `sleep_debt`, `null` pour `red_verdict`
 * — un fait booléen n'a rien à comparer à un seuil), cette fonction n'ajoute
 * QUE le suffixe d'unité et, pour `pain`, la zone déclarée (`location`).
 * Jamais de conversion d'unité ici : elle vivrait alors en double (API +
 * tuile), avec le risque qu'elles divergent. */
function injuryFactorValueText(f) {
  if (f.observed == null || f.threshold == null) return "";
  if (f.id === "pain") {
    const loc = f.location ? ` — ${F.esc(f.location)}` : "";
    return ` <span class="muted">(${F.esc(String(f.observed))}/10, seuil ${F.esc(String(f.threshold))}/10)${loc}</span>`;
  }
  if (f.id === "sleep_debt") {
    return ` <span class="muted">(${F.esc(String(f.observed))} h, seuil ${F.esc(String(f.threshold))} h)</span>`;
  }
  return ` <span class="muted">(${F.esc(String(f.observed))} vs seuil ${F.esc(String(f.threshold))})</span>`;
}

/** Tuile « Signal de vigilance blessure » (#57) — Aujourd'hui. N'apparaît QUE si
 * le niveau est `moderate`/`high` (jamais pour `low`, pas un signal actionnable
 * au quotidien) : facteurs contributeurs cités par leur libellé + valeur
 * formatée par facteur (`injuryFactorValueText`), le disclaimer NON-diagnostique
 * rendu par l'API tel quel (jamais reformulé ici — voir
 * `arc_guardrails.INJURY_RISK_DISCLAIMER`), et une recommandation de
 * consultation explicite dès `consult: true` (douleur sévère, ou niveau élevé
 * avec douleur contributrice — voir `arc_guardrails.evaluate_injury_risk`). */
function injuryRiskTile(risk) {
  if (!risk || risk.level === "low") return "";
  const contributing = (risk.factors || []).filter((f) => f.contributes);
  if (!contributing.length) return "";
  const label = risk.level === "high" ? "Signal de vigilance élevé" : "Signal de vigilance modéré";
  const items = contributing.map((f) => {
    const name = F.esc(f.label || INJURY_FACTOR_FALLBACK[f.id] || f.id);
    return `<li>${name}${injuryFactorValueText(f)}</li>`;
  }).join("");
  const consult = risk.consult
    ? `<p class="note">Consulte un professionnel de santé pour un avis avant de reprendre.</p>` : "";
  return `<div role="note" aria-label="${F.esc(label)}">
    <p class="weather">${chip("injury", risk.level, label)}</p>
    <ul class="facts-list">${items}</ul>
    ${consult}
    <p class="muted">${F.esc(risk.disclaimer)}</p>
  </div>`;
}

// Kilométrage chaussures et alerte d'usure (#40) : tuile « Aujourd'hui » — n'apparaît
// que si au moins une chaussure (non retirée) a atteint son seuil. Le détail complet
// (toutes les paires, retirées comprises) vit dans la vue Matériel (`gearSection`, #147).
const gearHref = (id) => `#/materiel/${encodeURIComponent(id)}`;
const gearLink = (id, name) => `<a href="${F.esc(gearHref(id))}">${F.esc(name)}</a>`;

function gearTile(gear, withLink = true) {
  const alerts = (gear?.shoes || []).filter((s) => s.alert);
  if (!alerts.length) return "";
  const names = alerts.map((s) => `${gearLink(s.gear_id, s.name)} (${F.distance(s.distance_m, 0)})`).join(", ");
  return `<p class="weather">${chip("gear", "orange", "Chaussures à surveiller")} <span>${names}</span>${withLink ? ` <a href="#/materiel">Voir le matériel</a>` : ""}</p>`;
}

// Tuile « Aujourd'hui » : objets hors chaussures sous alerte (#134), même règle que `gearTile`.
function equipmentTile(eq) {
  const alerts = (eq?.items || []).filter((i) => i.alert);
  if (!alerts.length) return "";
  return `<p class="weather">${chip("gear", "orange", "Matériel à contrôler")} <span>${alerts.map((i) => gearLink(i.gear_id, i.name)).join(", ")}</span> <a href="#/materiel">Voir le matériel</a></p>`;
}

// Prévision de retraite (#132) : « ≈ 6 sem. » (clé omise côté API = pas de prévision, on
// n'affiche rien) ; seuil dépassé → « seuil dépassé » ; « proche » à ≥ 90 % du seuil.
function gearForecast(s) {
  if (s.retired) return "";
  if (s.alert) return `<span class="tag">seuil dépassé</span>`;
  const near = s.near_threshold ? `${chip("gear", "orange", "Proche du seuil")} ` : "";
  if (s.retire_forecast_weeks == null) return near;
  const weeks = Math.max(1, Math.round(s.retire_forecast_weeks));
  return `${near}<span class="tag" title="Rythme des 28 derniers jours — approximation linéaire, retraite estimée le ${F.esc(s.retire_forecast_date)}">≈ ${weeks} sem.</span>`;
}

// Inspection photo des chaussures (#135) : dernier état connu de la paire (pastille 🟢🟡🟠🔴 + date)
// sur sa ligne du tableau, et rappel « inspection conseillée » (jamais imposé). Texte d'état toujours
// écrit en toutes lettres à côté de la couleur (pas seulement la couleur).
const GEAR_CONDITION = { green: "Bon état", yellow: "Usure visible", orange: "Usure avancée", red: "Fin de vie" };
const GEAR_SIDE = { left: "pied gauche", right: "pied droit" };
const GEAR_ZONE = {
  heel_posterolateral: "talon postéro-latéral", heel_lateral: "talon latéral", heel_medial: "talon médial",
  heel_central: "talon central", midfoot_lateral: "médio-pied latéral", midfoot_medial: "médio-pied médial",
  midfoot_central: "médio-pied central", forefoot_lateral: "avant-pied latéral", forefoot_medial: "avant-pied médial",
  forefoot_central: "avant-pied central", toe: "bout",
};
const GEAR_SEVERITY = { light: "légère", moderate: "modérée", marked: "marquée" };
const GEAR_HINT = {
  heel_strike: "attaque talon", midfoot_forefoot_strike: "attaque médio/avant-pied",
  pronation_hint: "indice de pronation", supination_hint: "indice de supination",
};
const GEAR_ASYMMETRY = { none: "aucune asymétrie", mild: "asymétrie légère", marked: "asymétrie marquée" };
const gearConditionChip = (c) => chip("gearcond", c, GEAR_CONDITION[c] || c);
function inspectionBadge(entry) {
  if (!entry) return "";
  const latest = entry.latest ? `<span class="tag" title="Inspection du ${F.esc(entry.latest.date)}">inspectée ${F.esc(F.dayShort(entry.latest.date))}</span> ${gearConditionChip(entry.latest.condition)}` : "";
  const due = entry.due ? ` ${chip("gear", "orange", "Inspection conseillée")}` : "";
  return `${latest}${due}`;
}
function inspectionPhotos(insp) {
  const photos = insp.photos || [];
  if (!photos.length) return "";
  const alt = `Photo d'inspection du ${insp.date}`;
  return `<span class="gear-photos">${photos.map((path, i) => {
    const src = `/media/gear-photo?path=${encodeURIComponent(path)}`;
    return `<a href="${F.esc(src)}" target="_blank" rel="noopener"><img class="gear-photo" loading="lazy" width="72" height="72" src="${F.esc(src)}" alt="${F.esc(alt)} (${i + 1}/${photos.length})"></a>`;
  }).join("")}</span>`;
}
// Zones d'usure en petit tableau zone × pied gauche / pied droit (#151) : une cellule vide = zone non
// notée sur ce pied (jamais « sans usure »). Sévérité en toutes lettres, pas seulement une teinte.
function wearTable(zones) {
  if (!zones?.length) return "";
  const byZone = new Map();
  for (const z of zones) {
    const row = byZone.get(z.zone) || {};
    row[z.side] = z.severity || "seen";
    byZone.set(z.zone, row);
  }
  const order = Object.keys(GEAR_ZONE);
  const rank = (z) => (order.includes(z) ? order.indexOf(z) : order.length);
  const cell = (sev) => (sev
    ? `<span class="wear__sev wear__sev--${F.esc(sev)}">${F.esc(sev === "seen" ? "constatée" : GEAR_SEVERITY[sev] || sev)}</span>`
    : `<span class="muted" aria-label="non notée">—</span>`);
  const rows = [...byZone.keys()].sort((a, b) => rank(a) - rank(b)).map((zone) => {
    const row = byZone.get(zone);
    return `<tr><th scope="row">${F.esc(GEAR_ZONE[zone] || zone)}</th><td>${cell(row.left)}</td><td>${cell(row.right)}</td></tr>`;
  }).join("");
  return `<table class="wear"><thead><tr><th scope="col">Zone d'usure</th><th scope="col">Pied gauche</th><th scope="col">Pied droit</th></tr></thead><tbody>${rows}</tbody></table>`;
}
// Asymétrie : neutre quand « aucune », mise en avant (avec le côté le plus usé) sinon.
function asymmetryBadge(asym) {
  if (!asym?.level) return "";
  const label = GEAR_ASYMMETRY[asym.level] || asym.level;
  if (asym.level === "none") return `<span class="tag">${F.esc(label)}</span>`;
  const side = asym.side ? ` — ${GEAR_SIDE[asym.side] || asym.side} plus usé` : "";
  return chip("gearcond", asym.level === "marked" ? "orange" : "yellow", `${label}${side}`);
}
const hintBadges = (hints) => (hints || []).map((h) => `<span class="tag tag--hint">indice : ${F.esc(GEAR_HINT[h] || h)}</span>`).join("");
// Rappel « indice, pas diagnostic » : UNE fois par carte (jamais par inspection), avec le lien vers la
// synthèse mesurée de la vue Santé.
const INSPECTION_CAVEAT = `Indices d'attaque et d'asymétrie : tirés de photos de semelle, à prendre comme des indices, pas un diagnostic. La foulée mesurée par la montre est dans <a href="#/sante?section=foulee">la carte « Foulée » de la vue Santé</a>.`;
function inspectionItem(insp) {
  const badges = [asymmetryBadge(insp.asymmetry), hintBadges(insp.gait_hints)].filter(Boolean).join(" ");
  return `<li class="insp">
    <div class="insp__head"><strong>${F.esc(F.dayLong(insp.date))}</strong> ${gearConditionChip(insp.condition)}${insp.distance_m != null ? ` <span class="muted">à ${F.distance(insp.distance_m, 0)}</span>` : ""}</div>
    ${badges ? `<div class="insp__badges">${badges}</div>` : ""}${wearTable(insp.wear_zones)}${inspectionPhotos(insp) ? `<div>${inspectionPhotos(insp)}</div>` : ""}</li>`;
}
function gearInspectionSection(inspections) {
  const entries = (inspections?.gear || []).filter((e) => e.inspections.length || e.due);
  if (!entries.length) return "";
  const blocks = entries.map((e) => {
    const change = e.condition_change === "worse" ? ` <span class="tag">plus dégradée que la précédente</span>` : e.condition_change === "better" ? ` <span class="tag">mieux que la précédente</span>` : e.condition_change === "same" ? ` <span class="tag">état stable</span>` : "";
    const due = e.due ? ` ${chip("gear", "orange", "Inspection conseillée")} <small class="muted">${e.due_reason === "threshold_alert" ? "seuil d'alerte franchi" : e.due_reason === "never_inspected" ? "jamais inspectée" : `${F.distance(e.km_since_inspection_m, 0)} depuis la dernière`}</small>` : "";
    const list = e.inspections.length ? `<ol class="gear-inspections">${e.inspections.map(inspectionItem).join("")}</ol>` : `<p class="muted">Aucune inspection enregistrée.</p>`;
    return `<div class="gear-inspection-block"><h3>${gearLink(e.gear_id, e.name)}${e.retired ? ` <span class="tag">retirée</span>` : ""}${e.unknown ? ` <span class="tag">inconnue</span>` : ""}${e.ignored ? ` <span class="tag">ignorée</span>` : ""}${change}${due}</h3>${list}</div>`;
  }).join("");
  return `<section class="band"><h2>Inspections photo</h2>${blocks}
    ${note("L'usure d'une semelle est un signal faible (les chaussures modernes la déforment) : la comparaison avec l'inspection précédente compte plus que le verdict isolé. Demandez une inspection au coach — il la propose environ tous les 200 km.")}
    ${note(INSPECTION_CAVEAT)}</section>`;
}

// Détail complet du kilométrage chaussures (vue Matériel, #147) : toutes les paires
// déclarées (retirées comprises, en fin de tableau), plus une ligne « inconnue »
// par `gear_id` vu sur une activité mais absent du profil (#40 — ne jamais
// masquer silencieusement un `gear_id` mal orthographié).
function gearSection(gear, inspections) {
  const shoes = gear?.shoes || [];
  const inspectionByGear = Object.fromEntries((inspections?.gear || []).map((e) => [e.gear_id, e]));
  const unknown = gear?.unknown || [];
  const warnings = gear?.warnings || [];
  if (!shoes.length && !unknown.length) return "";
  const sorted = [...shoes].sort((a, b) => (a.retired === b.retired ? 0 : a.retired ? 1 : -1));
  const rows = sorted.map((s) => `<tr${s.retired ? ` class="muted"` : ""}>
      <th scope="row">${gearLink(s.gear_id, s.name)}${s.default ? ` <span class="tag">défaut</span>` : ""}${s.retired ? ` <span class="tag">retirée</span>` : ""}${s.usage ? ` <span class="tag">${F.esc(s.usage)}</span>` : ""}</th>
      <td class="num">${F.distance(s.distance_m, 0)}${s.start_m ? `<br><small class="muted">dont ${F.distance(s.start_m, 0)} de départ</small>` : ""}</td>
      <td class="num">${F.distance(s.threshold_m, 0)}</td>
      <td>${s.alert ? chip("gear", "orange", "À surveiller") : ""} ${gearForecast(s)} ${inspectionBadge(inspectionByGear[s.gear_id])}</td></tr>`).join("");
  const unknownRows = unknown.map((u) => `<tr><th scope="row">${gearLink(u.gear_id, u.gear_id)} <span class="tag">inconnue</span></th><td class="num">${F.distance(u.distance_m, 0)}</td><td class="num">—</td><td></td></tr>`).join("");
  return `<section class="band"><h2>Chaussures</h2><div class="table-wrap"><table class="data data--compact">
      <thead><tr><th scope="col">Chaussure</th><th scope="col" class="num">Kilométrage</th><th scope="col" class="num">Seuil</th><th scope="col">Statut</th></tr></thead>
      <tbody>${rows}${unknownRows}</tbody></table></div>
      ${unknown.length ? note("« inconnue » : gear_id vu sur une séance mais absent de la section « Chaussures » du profil (faute de frappe, paire jamais déclarée).") : ""}
      ${warnings.map((w) => note(F.esc(w))).join("")}</section>`;
}

// Matériel hors chaussures (#134) : une valeur d'usage par type de déclencheur. Un déclencheur
// non déclaré n'est jamais affiché (aucun seuil inventé) ; « en jours » sans date de référence
// (`unavailable`) est dit comme tel plutôt que présenté comme 0.
const EQUIP_TRIGGER = {
  distance: (v) => F.distance(v, 0),
  duration: (v) => F.hours(v),
  sessions: (v) => `${F.num(v, 0)} séance${v > 1 ? "s" : ""}`,
  days: (v) => `${F.num(v, 0)} j`,
};
const EQUIP_CATEGORY_LABEL = { batons: "bâtons", gilet: "gilet", poche: "poche", flasques: "flasques",
  frontale: "frontale", ceinture: "ceinture", veste: "veste", semelles: "semelles", lacets: "lacets", autre: "autre" };
function equipmentTriggers(item) {
  if (!item.triggers?.length) return `<span class="muted">aucun seuil déclaré</span>`;
  return item.triggers.map((t) => {
    if (t.unavailable) return `<span class="tag" title="Ajoutez « depuis <date> » ou « entretien <date> » au profil">jours : date de référence manquante</span>`;
    const fmt = EQUIP_TRIGGER[t.type] || ((v) => F.num(v, 0));
    return `<span class="tag${t.reached ? " tag--alert" : ""}">${fmt(t.value)} / ${fmt(t.threshold)}</span>`;
  }).join(" ");
}
function equipmentSection(eq) {
  const items = eq?.items || [];
  const unknown = eq?.unknown || [];
  const warnings = eq?.warnings || [];
  if (!items.length && !unknown.length) return "";
  const sorted = [...items].sort((a, b) => (a.retired === b.retired ? 0 : a.retired ? 1 : -1));
  const rows = sorted.map((it) => `<tr${it.retired ? ` class="muted"` : ""}>
      <th scope="row">${gearLink(it.gear_id, it.name)}${it.category ? ` <span class="tag">${F.esc(EQUIP_CATEGORY_LABEL[it.category] || it.category)}</span>` : ""}${it.retired ? ` <span class="tag">retiré</span>` : ""}${(it.kits || []).map((k) => ` <span class="tag">kit ${F.esc(k)}</span>`).join("")}</th>
      <td class="num">${F.distance(it.usage.distance_m, 0)}<br><small class="muted">${F.hours(it.usage.duration_s)} · ${F.num(it.usage.sessions, 0)} séance${it.usage.sessions > 1 ? "s" : ""}${it.usage.days != null ? ` · ${F.num(it.usage.days, 0)} j` : ""}</small></td>
      <td>${equipmentTriggers(it)}</td>
      <td>${it.alert ? chip("gear", "orange", "À surveiller") : it.near_threshold ? chip("gear", "orange", "Proche du seuil") : ""}</td></tr>`).join("");
  const unknownRows = unknown.map((u) => `<tr><th scope="row">${gearLink(u.gear_id, u.gear_id)} <span class="tag">inconnu</span></th><td class="num">${F.distance(u.distance_m, 0)}</td><td></td><td></td></tr>`).join("");
  return `<section class="band"><h2>Équipement</h2><div class="table-wrap"><table class="data data--compact">
      <thead><tr><th scope="col">Objet</th><th scope="col" class="num">Usage</th><th scope="col">Déclencheurs</th><th scope="col">Statut</th></tr></thead>
      <tbody>${rows}${unknownRows}</tbody></table></div>
      ${unknown.length ? note("« inconnu » : identifiant cité dans <code>gear_ids</code> d'une séance mais absent de la section « Matériel » du profil.") : ""}
      ${warnings.map((w) => note(F.esc(w))).join("")}</section>`;
}

// Indices de performance ITRA/UTMB (#62, vue Performance) : valeur courante par
// (type, catégorie) — la plus récente déclarée dans le profil, jamais récupérée
// automatiquement (voir `agents/coach.md`, mandat vie privée) — plus un mini
// graphique d'historique pour l'indice GÉNÉRAL de chaque type (sans catégorie),
// quand au moins deux relevés existent. Les catégories (ITRA libre, UTMB
// 20K/50K/100K/100M) n'ont chacune, en pratique, que trop peu de relevés pour
// justifier un graphique par catégorie : leur valeur courante reste visible
// dans le tableau, sans historique tracé.
function indexLabel(kind, category) {
  const name = kind === "itra" ? "ITRA" : "UTMB";
  return category ? `${name} ${category.toUpperCase()}` : `${name} (général)`;
}

// Empêche une année en un seul chiffre (`d.slice(0,4)` sur une date déjà ISO
// donne toujours 4 chiffres, mais mieux vaut le nom explicite qu'un slice nu
// répété à chaque appel).
const isoYear = (iso) => iso.slice(0, 4);

function indexMiniChart(entries, kind, cls) {
  if (entries.length < 2) return null;
  const dates = entries.map((e) => e.date);
  const values = entries.map((e) => e.value);
  const label = `Historique ${indexLabel(kind, null)}`;
  // Échelle temporelle VRAIE (`timeScale`, revue de code #62) : deux relevés
  // espacés de dix mois ne doivent pas occuper la même distance à l'écran que
  // deux relevés consécutifs — chaque point est positionné proportionnellement
  // à sa date réelle, pas à son simple rang. `xLabels` porte l'année
  // explicitement sur CHAQUE repère (`F.dayShort` + année) plutôt que de
  // s'en remettre à l'heuristique « premiers jours du mois » de `timeChart`
  // (pensée pour une série quotidienne dense, pas pour des relevés occasionnels
  // qui peuvent s'étaler sur plusieurs années).
  const xLabels = dates.map((d) => `${F.dayShort(d)} ${isoYear(d)}`);
  // `dot`/`dot--<kind>` (revue de code #109, 2e tour, nit) : jamais la classe
  // `line`/`line--<kind>` réutilisée telle quelle pour les points — `.chart
  // .line { fill: none; ... }` (web/css/app.css) laisserait les points creux,
  // invisibles sauf un mince cerne. C'est la même convention que toutes les
  // autres séries à points du tableau de bord (`dot--hrv`, `dot--vam`…).
  const chart = timeChart(dates, [{ type: "line", values, cls }, { type: "dots", values, cls: `dot dot--${kind}` }], [], {
    height: 160, label, yFormat: (v) => F.num(v, 0), timeScale: true, xLabels,
  });
  return { chart, entries, label };
}

function performanceIndexSection(idx) {
  const current = idx?.current || [];
  const history = idx?.history || [];
  const warnings = idx?.warnings || [];
  // Calculée une seule fois, jamais imbriquée dans un <p> d'un autre bloc
  // (revue de code #109, 2e tour, nit) : ce sont toujours des <p class="note">
  // FRÈRES du bloc qui précède (le <div class="empty"> de l'état vide, ou le
  // <table> de l'état rempli plus bas), jamais son enfant.
  const warningsHtml = warnings.map((w) => note(F.esc(w))).join("");
  if (!current.length && !history.length) {
    const emptyHtml = empty("Pas d'indice de performance déclaré",
      "Ajoutez, dans votre profil (« Indices de performance (ITRA / UTMB) »), une ligne par relevé au "
      + "format : AAAA-MM-JJ — itra|utmb [catégorie] : valeur (ex. 2025-11-01 — itra : 610) — jamais "
      + "récupéré automatiquement.");
    return { html: emptyHtml + warningsHtml, charts: [] };
  }
  const rows = [...current]
    .sort((a, b) => (a.kind === b.kind ? (a.category || "").localeCompare(b.category || "") : a.kind.localeCompare(b.kind)))
    .map((c) => `<tr><th scope="row">${F.esc(indexLabel(c.kind, c.category))}</th>
        <td class="num">${F.num(c.value, 0)}</td><td>${F.dayShort(c.date)} ${isoYear(c.date)}</td></tr>`)
    .join("");
  const charts = [];
  for (const kind of ["itra", "utmb"]) {
    const general = history.filter((h) => h.kind === kind && !h.category);
    const built = indexMiniChart(general, kind, `line line--${kind}`);
    if (built) charts.push({ id: `c-idx-${kind}`, readoutId: `r-idx-${kind}`, ...built });
  }
  const chartHost = (c) => `<div><h3>${F.esc(c.label)}</h3>
      <div class="chart-host" id="${c.id}">${c.chart.svg}</div><p class="readout" id="${c.readoutId}"></p></div>`;
  // Un seul graphique ne doit jamais se retrouver à moitié de largeur dans une
  // grille à deux colonnes prévue pour DEUX (revue de code #62, nit) : la
  // grille `band--split` n'est posée que si les deux séries générales existent.
  const chartsHtml = charts.length === 2
    ? `<div class="band--split">${charts.map(chartHost).join("")}</div>`
    : charts.map(chartHost).join("");
  const html = `<section class="band"><h2>Indices de performance (ITRA / UTMB)</h2>
      <table class="data data--compact">
        <thead><tr><th scope="col">Indice</th><th scope="col" class="num">Valeur</th><th scope="col">Date</th></tr></thead>
        <tbody>${rows}</tbody></table>
      ${chartsHtml}
      ${note("Valeurs déclarées par vous dans le profil, jamais récupérées automatiquement — voir la règle de vie privée du coach.")}
      ${warningsHtml}
    </section>`;
  return { html, charts };
}

// ---------------------------------------------------------------------------
// Cadre : objectif, navigation, thème
// ---------------------------------------------------------------------------

function renderObjective(s) {
  const o = s.objective;
  const box = $("#objective");
  if (!o || !o.race_date) {
    box.innerHTML = `<span class="objective__none">Aucun objectif actif — <code>planning/active_objective.md</code></span>`;
    return;
  }
  const left = o.days_left;
  const when = left > 0 ? `J-${left}` : left === 0 ? "Jour de course" : `Terminé il y a ${-left} j`;
  const meta = [F.dateLong(o.race_date), o.distance_m ? F.distance(o.distance_m, 0) : null,
    o.elevation_gain_m && s.settings.sport === "trail" ? `${F.elevation(o.elevation_gain_m)} D+` : null].filter(Boolean).join(" · ");
  box.innerHTML = `<span class="objective__count ${left < 0 ? "is-past" : ""}">${when}</span>
    <span class="objective__text"><strong>${F.esc(o.name || "Objectif")}</strong><span>${meta}</span></span>`;
}

function renderNav(s) {
  const items = navItems(s.settings);
  $("#nav").innerHTML = items.map(([h, l]) => `<a href="#/${h}" data-route="${h}">${l}</a>`).join("")
    // Page séparée (chat.html), pas une route à hash : visible seulement si `[chat].enabled`.
    + (s.settings.chat_enabled ? `<a href="chat.html" data-route="coach-chat">Coach</a>` : "")
    + (s.incomplete_files ? `<a href="#/fichiers" data-route="fichiers" class="nav__debt">${s.incomplete_files} fichier${s.incomplete_files > 1 ? "s" : ""} hors contrat</a>` : "")
    // `week_collisions_count` (#69, revue de code) : compté À PART de
    // `incomplete_files` — ces fichiers sont déjà valides au contrat, jamais
    // « hors contrat » (voir `arc_serve.api_summary`/`viewFiles`).
    + (s.week_collisions_count ? `<a href="#/fichiers" data-route="fichiers" class="nav__debt">${s.week_collisions_count} collision${s.week_collisions_count > 1 ? "s" : ""} de semaine</a>` : "");
}

function markNav(route) {
  for (const a of document.querySelectorAll("#nav a")) {
    const on = a.dataset.route === route || (route === "seance" && a.dataset.route === "seances") || (route === "rapport" && a.dataset.route === "rapports")
      // `#/montee/<id>` (#49) n'a pas d'entrée de nav propre — c'est un sous-détail
      // d'Analyse (#50, historique d'un segment de montée listé là), même motif
      // que `seance`/`rapport` ci-dessus (sous-page sans onglet dédié).
      || (route === "montee" && a.dataset.route === "analyse")
      // `#/decision?id=…` (#55, détail d'une décision) : même motif que `rapport`
      // ci-dessus, sous-page de « Décisions » sans onglet dédié.
      || (route === "decision" && a.dataset.route === "decisions")
      // `#/roadbook` (#187, roadbook imprimable d'un plan de course) : sous-page de Trail Shape.
      || (route === "roadbook" && a.dataset.route === "trail-shape");
    a.toggleAttribute("aria-current", on);
    if (on) {
      a.setAttribute("aria-current", "page");
      // Nav défilante sur mobile (#147, une entrée de plus) : l'onglet actif reste visible.
      if (a.scrollIntoView) a.scrollIntoView({ block: "nearest", inline: "nearest" });
    }
  }
}

function setupTheme() {
  const btn = $("#theme");
  // ?theme=dark|light force le thème (lien partagé, capture d'écran) ; sinon le choix mémorisé.
  const forced = new URLSearchParams(location.search).get("theme");
  const saved = (() => { try { return localStorage.getItem("arc-theme"); } catch { return null; } })();
  const theme = ["dark", "light"].includes(forced) ? forced : saved;
  if (theme) document.documentElement.dataset.theme = theme;
  btn.addEventListener("click", () => {
    const dark = document.documentElement.dataset.theme
      ? document.documentElement.dataset.theme === "dark"
      : matchMedia("(prefers-color-scheme: dark)").matches;
    const next = dark ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    try { localStorage.setItem("arc-theme", next); } catch { /* stockage indisponible */ }
    route();
  });
}

// ---------------------------------------------------------------------------
// Vue : Aujourd'hui
// ---------------------------------------------------------------------------

/** Encart « Pourquoi aujourd'hui ? » (#55) : la dernière décision ACTIVE du
 * coach, pour rendre visible — sans ouvrir l'IDE — le principal différenciateur
 * face aux apps commerciales : chaque ajustement de séance est tracé, avec ce
 * qui l'a justifié.
 *
 * Sélection : décision `date === aujourd'hui` en priorité ; à défaut, la plus
 * récente décision active des 2 derniers jours (`/api/decisions?days=2&active=1`
 * rend déjà « plus récente d'abord » — `[0]` suffit), étiquetée avec SA propre
 * date pour ne jamais laisser croire qu'elle date d'aujourd'hui. Aucune décision
 * dans cette fenêtre : encart absent (jamais un encart vide) — c'est un jour
 * sans ajustement notable, pas une panne.
 */
async function decisionEncart(s) {
  let data;
  try { data = await api("decisions?days=2&active=1"); } catch { return ""; }
  const list = data.decisions || [];
  const chosen = list.find((d) => d.date === s.today) || list[0];
  if (!chosen) return "";
  const isToday = chosen.date === s.today;
  const inputs = chosen.inputs
    ? `<ul class="facts-list">${Object.entries(chosen.inputs).map(([k, v]) => `<li><code>${F.esc(k)}</code> : ${F.esc(fmtInputValue(v))}</li>`).join("")}</ul>` : "";
  const rules = (chosen.rules || []).length
    ? `<p class="muted">Règle${chosen.rules.length > 1 ? "s" : ""} : ${chosen.rules.map((r) => F.esc(r.label || r.rule_id)).join(", ")} — <a href="${GUARDRAILS_DOC_URL}" rel="noopener noreferrer">garde-fous</a></p>` : "";
  const sources = (chosen.source_links || []).map((sl) => sl.route ? `<a href="${sl.route}">${F.esc(sl.label)}</a>` : F.esc(sl.label)).join(", ");
  const pending = chosen.outcome === "proposed" ? `<p class="note">En attente de ta confirmation.</p>` : "";
  return `<section class="band" aria-labelledby="decision-encart-title">
    <h2 id="decision-encart-title">Pourquoi ${isToday ? "aujourd'hui" : F.dayLong(chosen.date)} ?</h2>
    <p>${triggerChip(chosen.trigger)} ${outcomeChip(chosen.outcome)}</p>
    <p>${F.esc(chosen.summary)}</p>
    ${inputs}${rules}
    ${sources ? `<p class="muted">Sources : ${sources}</p>` : ""}
    ${pending}
    <p><a href="#/decision?id=${encodeURIComponent(chosen.id)}">Voir cette décision</a> · <a href="#/decisions">Le journal des décisions</a></p>
  </section>`;
}

async function viewToday() {
  const s = SUMMARY;
  const [health, week, form, reports, decisionHtml, injuryRisk] = await Promise.all([
    api("health?days=14"), api("week"), api("form?days=30"), api("reports"), decisionEncart(s),
    api("injury-risk").catch(() => null),
  ]);
  const today = s.today;
  const mode = health.morning_check;
  const series = health.series;
  const h = series.find((p) => p.date === today) || null;
  const lastVerdict = [...series].reverse().find((p) => p.verdict);

  let verdict;
  if (h && h.verdict) {
    verdict = `<div class="verdict verdict--${h.verdict}"><div class="verdict__word">${F.VERDICT[h.verdict]}</div><p class="verdict__why">${F.esc(h.verdict_reason || "")}</p></div>`;
  } else {
    verdict = `<div class="verdict verdict--none"><div class="verdict__word">Pas de verdict aujourd'hui</div><p class="verdict__why">${lastVerdict
      ? `Dernier verdict du coach le ${F.dayLong(lastVerdict.date)} : <strong>${F.VERDICT[lastVerdict.verdict]}</strong> — ${F.esc(lastVerdict.verdict_reason || "")}`
      : "Le coach pose un verdict (maintenir, alléger, repos) dans le fichier santé du jour lors du bilan matinal."}</p></div>`;
  }

  let triad = "";
  if (mode === "off") {
    triad = note("Bilan matinal désactivé (<code>[health].morning_check = \"off\"</code>) : pas de données de santé attendues.");
  } else {
    const latest = h || [...series].reverse().find((p) => p.readiness_score !== undefined || p.hrv_overnight_ms !== undefined) || {};
    const rows = [];
    if (mode === "full") {
      // Le statut personnel (`hrv_personal_status`) porte sur la MOYENNE 7 j, pas sur la
      // valeur brute de la nuit : on l'affiche tel quel plutôt que de recomparer la valeur
      // brute à la bande personnelle (qui n'est pas à la même échelle qu'une nuit isolée).
      const lo = latest.hrv_baseline_low_ms, hi = latest.hrv_baseline_high_ms;
      const garminBand = lo != null && hi != null;
      const statusLabel = { sous: "sous", au_dessus: "au-dessus de", dans_la_norme: "dans" }[latest.hrv_personal_status];
      let hrvTxt, barValue = latest.hrv_overnight_ms, barLo = lo, barHi = hi;
      if (garminBand) {
        hrvTxt = (latest.hrv_overnight_ms < lo ? "sous la bande" : latest.hrv_overnight_ms > hi ? "au-dessus de la bande" : "dans la bande")
          + ` ${F.num(lo)}–${F.num(hi)}`;
        if (statusLabel) hrvTxt += ` · moyenne 7 j ${statusLabel} la référence personnelle`;
      } else if (latest.hrv_personal_status === "en_construction") {
        hrvTxt = "pas de bande Garmin disponible ; référence personnelle en construction (historique encore court)";
      } else if (statusLabel) {
        hrvTxt = `pas de bande Garmin disponible ; moyenne 7 j ${statusLabel} la référence personnelle ${F.num(latest.hrv_personal_low_ms)}–${F.num(latest.hrv_personal_high_ms)}`;
        barValue = latest.hrv_personal_mean7_ms; barLo = latest.hrv_personal_low_ms; barHi = latest.hrv_personal_high_ms;
      } else {
        hrvTxt = "bande de référence non renseignée";
      }
      rows.push(["HRV nocturne", latest.hrv_overnight_ms != null ? `${F.num(latest.hrv_overnight_ms)} ms` : "—",
        rangeBar(barValue, barLo, barHi, 20, 120), hrvTxt]);
      const d = latest.rhr_delta;
      const rhrTxt = latest.rhr_median7 != null && d != null
        ? `${d > 0 ? "+" : ""}${F.num(d)} vs médiane 7 j (${F.num(latest.rhr_median7)})${d > 7 ? " — nettement élevée" : d >= 5 ? " — à surveiller" : ""}`
        : "médiane 7 j indisponible";
      rows.push(["FC de repos", latest.resting_hr_bpm != null ? `${F.num(latest.resting_hr_bpm)} bpm` : "—",
        rangeBar(latest.resting_hr_bpm, latest.rhr_median7 != null ? latest.rhr_median7 - 3 : null, latest.rhr_median7 != null ? latest.rhr_median7 + 5 : null, 30, 70, d > 7 ? "range--alert" : d >= 5 ? "range--warn" : ""), rhrTxt]);
      // Dette de sommeil 7 j (#37) : lue depuis `/api/summary` (calculée pour AUJOURD'HUI
      // précisément), pas depuis `latest` (qui peut retomber sur un jour plus ancien si
      // rien n'a encore été synchronisé aujourd'hui — `nights_counted` est toujours rendu
      // par l'API, même sous le seuil de nuits mesurées, pour distinguer « pas assez de
      // nuits » de « aucune dette » plutôt que d'afficher un simple tiret dans les deux cas.
      const debt = s.sleep_debt;
      const debtWarnH = health.thresholds?.sleep_debt_warn_h ?? 5;
      const debtAlertH = health.thresholds?.sleep_debt_alert_h ?? 10;
      if (debt && debt.sleep_debt_7d_s != null) {
        const debtH = debt.sleep_debt_7d_s / 3600;
        rows.push(["Dette de sommeil (7 j)", `${F.num(debtH, 1)} h`,
          rangeBar(debtH, 0, debtWarnH, 0, debtAlertH * 1.5, debtH > debtAlertH ? "range--alert" : debtH > debtWarnH ? "range--warn" : ""),
          `sur ${debt.nights_counted} nuit${debt.nights_counted > 1 ? "s" : ""} mesurée${debt.nights_counted > 1 ? "s" : ""} · besoin ${F.duration(debt.sleep_need_s)}`]);
      } else if (debt && debt.nights_counted != null) {
        rows.push(["Dette de sommeil (7 j)", "—", rangeBar(null, 0, debtWarnH, 0, debtAlertH * 1.5),
          `pas assez de nuits mesurées (${debt.nights_counted}/7)`]);
      }
    }
    rows.push(["Readiness", latest.readiness_score != null ? `${F.num(latest.readiness_score)}/100` : "—",
      rangeBar(latest.readiness_score, 60, 100, 0, 100), latest.readiness_score != null ? (latest.readiness_score >= 60 ? "prêt" : latest.readiness_score >= 40 ? "modéré" : "faible") : ""]);
    rows.push(["Sommeil", latest.sleep_total_s ? F.duration(latest.sleep_total_s) : "—",
      rangeBar(latest.sleep_score, 80, 100, 0, 100), latest.sleep_score != null ? `score ${F.num(latest.sleep_score)}` : ""]);
    triad = `<table class="triad"><caption>Bilan du matin${latest.date && latest.date !== today ? ` — dernières données : ${F.dayLong(latest.date)}` : ""}</caption>
      <tbody>${rows.map((r) => `<tr><th scope="row">${r[0]}</th><td class="triad__value">${r[1]}</td><td class="triad__bar">${r[2]}</td><td class="triad__ctx">${F.esc(r[3])}</td></tr>`).join("")}</tbody></table>
      ${mode === "minimal" ? note("Bilan minimal : readiness seule (<code>[health].morning_check = \"minimal\"</code>).") : ""}`;
  }

  const todaySessions = week.sessions.filter((x) => x.date === today);
  const todayActs = week.activities.filter((x) => x.date === today);
  const weather = week.weather.find((w) => w.date === today);
  const sessionHtml = todaySessions.length || todayActs.length
    ? `<ul class="plan">${todaySessions.map((x) => `<li><span class="plan__title">${F.esc(x.title)}</span><span class="plan__meta">${F.SPORT[x.sport] || x.sport}${x.planned_duration_s ? " · " + F.duration(x.planned_duration_s) : ""}${x.planned_distance_m ? " · " + F.distance(x.planned_distance_m) : ""}</span>${statusChip(x.status)}</li>`).join("")}
        ${todayActs.map((a) => `<li class="plan__done"><a href="#/seance/${a.id}">${F.esc(a.name || F.SPORT[a.sport])}</a><span class="plan__meta">Réalisée · ${a.distance_m ? F.distance(a.distance_m) + " · " : ""}${F.duration(a.duration_s)}</span></li>`).join("")}</ul>`
    : `<p class="muted">Aucune séance planifiée aujourd'hui${week.week ? "" : " — pas de plan de semaine au contrat pour cette semaine"}.</p>`;
  const weatherHtml = weather
    ? `<p class="weather">${weatherChip(weather.category)} <span>${F.esc(weather.location)} · ${F.num(weather.temp_max_c)} °C max · vent ${F.num(weather.wind_kmh)} km/h</span>${weather.best_slot ? ` <span class="slot">Créneau : <strong>${F.SLOT[weather.best_slot]}</strong></span>` : ""}</p>${weather.slot_reason ? `<p class="muted">${F.esc(weather.slot_reason)}</p>` : ""}`
    : "";
  const heatHtml = heatTile(s.heat_acclimation);
  // Un seul lien « Voir le matériel » quand les deux tuiles s'affichent (#147) : celle d'équipement le porte.
  const equipmentHtml = equipmentTile(s.equipment);
  const gearHtml = gearTile(s.gear, !equipmentHtml) + equipmentHtml;
  const injuryRiskHtml = injuryRiskTile(injuryRisk);

  const f = form.series[form.series.length - 1];
  const formNow = f ? f.form : null;
  const formTxt = !f ? "Pas encore de séances indexées." :
    `${formNow > 5 ? "Fraîcheur : la fatigue est sous la condition physique." : formNow < -20 ? "Fatigue marquée : la charge récente dépasse nettement la condition." : "Zone de travail : fatigue et condition équilibrées."}${f.acwr > 1.3 ? " Charge aiguë au-dessus de la zone prudente." : ""}`;
  const formHtml = f ? `<dl class="facts"><div><dt>Condition</dt><dd>${F.num(f.fitness)}</dd></div><div><dt>Fatigue</dt><dd>${F.num(f.fatigue)}</dd></div><div><dt>Forme</dt><dd class="${formNow >= 0 ? "pos" : "neg"}">${formNow > 0 ? "+" : ""}${F.num(formNow)}</dd></div><div><dt>ACWR</dt><dd>${F.num(f.acwr, 2)}</dd></div></dl><p class="muted">${formTxt} <a href="#/forme">Courbe de forme</a></p>` : note(formTxt);

  const rep = reports.reports[0];
  main.innerHTML = `${header(F.dayLong(today).replace(/^./, (c) => c.toUpperCase()))}
    ${verdict}
    ${decisionHtml}
    ${injuryRiskHtml ? `<section class="band" aria-labelledby="injury-risk-title"><h2 id="injury-risk-title">Signal de vigilance</h2>${injuryRiskHtml}</section>` : ""}
    <section class="band"><h2>Santé</h2>${triad}</section>
    <section class="band band--split"><div><h2>Au programme</h2>${sessionHtml}${weatherHtml}${heatHtml}${gearHtml}</div>
      <div><h2>Forme</h2>${formHtml}${complianceTrend(s.compliance_trend)}</div></section>
    ${rep ? `<section class="band"><h2>Dernier rapport du coach</h2><p><a href="#/rapport?path=${encodeURIComponent(rep.source_path)}">${F.esc(rep.title)}</a> <span class="muted">— ${F.dayLong(rep.date)}</span></p></section>` : ""}`;
}

// ---------------------------------------------------------------------------
// Vue : Forme & charge
// ---------------------------------------------------------------------------

/** Projection de charge jusqu'à la course (#172) : « forme prévue le jour J » ou l'état honnête d'indisponibilité. */
function forecastBlock(fc) {
  if (!fc) return "";
  if (fc.status !== "ok") {
    const why = {
      no_objective: "Aucun objectif actif : pas de date de course vers laquelle projeter la forme.",
      no_plan: "Aucune séance planifiée d'ici la course : écrivez les semaines pour obtenir une projection.",
      insufficient_history: "Historique insuffisant (moins de 84 jours) : la projection serait faussée par le démarrage de la condition.",
      target_past: "La date de la course est passée : rien à projeter.",
      invalid_until: "Date de projection invalide.",
    }[fc.status] || fc.reason || "";
    return why ? note(`Projection indisponible. ${F.esc(why)}`) : "";
  }
  const day = fc.race_day || fc.end;
  const peak = fc.peak_fatigue;
  const acwr = fc.acwr_max;
  const unplanned = fc.weeks_unplanned
    ? ` ${fc.weeks_unplanned} semaine${fc.weeks_unplanned > 1 ? "s" : ""} non planifiée${fc.weeks_unplanned > 1 ? "s" : ""} : charge supposée nulle, la forme prévue est alors optimiste.` : "";
  const cal = fc.calibration || {};
  const scale = cal.applied
    ? ` Charge planifiée recalée ×${F.num(cal.scale, 2)} sur vos ${cal.pairs} dernières séances planifiées réalisées.`
    : cal.ratio == null
      ? " Charge planifiée non recalée (trop peu de séances planifiées réalisées pour mesurer l'écart réel / estimé)."
      : ` Charge planifiée non recalée (écart réel / estimé ×${F.num(cal.ratio, 2)} jugé aberrant : vérifier FC de repos / max).`;
  return `<dl class="facts facts--inline">
      <div><dt>${fc.race_day ? "Forme prévue le jour J" : "Forme prévue à la date visée"}</dt><dd class="${day.form >= 0 ? "pos" : "neg"}">${day.form > 0 ? "+" : ""}${F.num(day.form, 1)}</dd></div>
      <div><dt>Pic de fatigue</dt><dd>${peak ? `sem. du ${F.dayShort(peak.week_start)}` : "—"}</dd></div>
      <div><dt>ACWR projeté (max)</dt><dd>${acwr ? F.num(acwr.value, 2) : "—"}</dd></div></dl>
    <p class="muted">Projection = <strong>estimation</strong> à partir du planifié (même modèle de charge que les garde-fous), pas une mesure.${scale}${unplanned} ${hypLink("charge")}</p>`;
}

async function viewForm(params) {
  const days = Number(params.get("jours")) || 180;
  const [form, load, forecast] = await Promise.all([
    api(`form?days=${days}`), api("load?weeks=26"),
    // La projection est un plus : son absence (erreur réseau/serveur) ne casse jamais la vue.
    api("load-forecast").catch(() => null),
  ]);
  const s = SUMMARY;
  const trail = s.settings.sport === "trail";
  const series = form.series;
  if (!series.length) {
    main.innerHTML = header("Forme & charge") + empty("Pas encore de séances", "La courbe de forme se construit à partir des séances indexées. Il faut environ six semaines d'historique pour qu'elle soit parlante.");
    return;
  }
  const histDates = series.map((p) => p.date);
  // Prolongement en pointillés jusqu'à la course (#172) : ESTIMATION à partir du planifié, jamais une mesure.
  const projected = forecast && forecast.status === "ok"
    ? forecast.series.filter((p) => p.projected && p.date > histDates[histDates.length - 1])
      // Le jour J s'arrête « en entrant dans la journée » (comme la valeur affichée) : la charge de la
      // course elle-même ne dessine pas un pic de fatigue au bout de la courbe.
      .map((p) => (forecast.race_day && p.date === forecast.race_day.date
        ? { ...p, ...forecast.race_day, load: null, entering: true } : p))
    : [];
  const nHist = series.length;
  const dates = histDates.concat(projected.map((p) => p.date));
  const histOnly = (key) => series.map((p) => p[key]).concat(projected.map(() => null));
  // Le dernier point réel ancre le tracé pointillé : il se raccorde à la courbe pleine.
  const projOnly = (key) => series.map((p, i) => (i === nHist - 1 ? p[key] : null)).concat(projected.map((p) => p[key]));
  const marks = [{ type: "hline", value: 0, cls: "mark mark--zero" }];
  if (form.race_date) marks.push({ type: "vline", date: form.race_date, cls: "mark mark--race", label: "Course" });
  const layers = [
    { type: "area", values: histOnly("form"), cls: "area area--form" },
    { type: "line", values: histOnly("fitness"), cls: "line line--fitness" },
    { type: "line", values: histOnly("fatigue"), cls: "line line--fatigue" },
  ];
  if (projected.length) {
    layers.push(
      { type: "area", values: projOnly("form"), cls: "area area--form area--projected" },
      { type: "line", values: projOnly("fitness"), cls: "line line--fitness line--projected" },
      { type: "line", values: projOnly("fatigue"), cls: "line line--fatigue line--projected" },
    );
  }
  const chart = timeChart(dates, layers, marks, { height: 250, label: "Condition, fatigue et forme", yFormat: (v) => F.num(v) });
  const acwr = timeChart(histDates, [
    { type: "band", lo: histDates.map(() => form.acwr_safe[0]), hi: histDates.map(() => form.acwr_safe[1]), cls: "band-fill" },
    { type: "line", values: series.map((p) => p.acwr), cls: "line line--acwr" },
  ], [], { height: 140, y: { min: 0, max: Math.max(2, ...series.map((p) => p.acwr || 0)) }, label: "Ratio charge aiguë / chronique", yFormat: (v) => F.num(v, 1) });

  const weeks = load.weeks;
  const wd = weeks.map((w) => w.week_start);
  const loadChart = trail
    ? timeChart(wd, [
      { type: "bars", values: weeks.map((w) => w.duration_s / 3600), cls: "bar" },
      { type: "line", values: weeks.map((w) => w.elevation_m), cls: "line line--dplus", axis: "y2" },
      { type: "dots", values: weeks.map((w) => w.elevation_m), cls: "dot dot--dplus", axis: "y2" },
    ], [], { height: 200, y: { zero: true }, y2: { zero: true }, label: "Volume hebdomadaire : heures et D+", yFormat: (v) => `${F.num(v)} h`, y2Format: (v) => `${F.num(v)} m` })
    : timeChart(wd, [
      { type: "bars", values: weeks.map((w) => w.distance_m / 1000), cls: "bar" },
    ], [], { height: 200, y: { zero: true }, label: "Volume hebdomadaire en kilomètres", yFormat: (v) => `${F.num(v)} km` });

  const periods = [[90, "3 mois"], [180, "6 mois"], [365, "1 an"]].map(([d, l]) => `<a class="seg ${d === days ? "is-on" : ""}" aria-current="${d === days ? "true" : "false"}" href="#/forme?jours=${d}">${l}</a>`).join("");
  const last = series[series.length - 1];
  main.innerHTML = `${header("Forme & charge", `Charge par séance : TRIMP (fréquence cardiaque), repli sur l'effort perçu. ${hypLink("charge")}`)}
    <div class="toolbar">${periods}</div>
    <section class="band"><h2>Courbe de forme</h2>
      <p class="legend"><span class="legend__item"><span class="key key--fitness"></span>Condition (42 j)</span> <span class="legend__item"><span class="key key--fatigue"></span>Fatigue (7 j)</span> <span class="legend__item"><span class="key key--form"></span>Forme</span>${projected.length ? ` <span class="legend__item"><span class="key key--projected"></span>Projection (pointillés)</span>` : ""}</p>
      <div class="chart-host" id="c-form">${chart.svg}</div><p class="readout" id="r-form"></p>
      ${forecastBlock(forecast)}</section>
    <section class="band"><h2>Ratio charge aiguë / chronique</h2><p class="muted">Repère indicatif ${F.num(form.acwr_safe[0], 1)} – ${F.num(form.acwr_safe[1], 1)}, pas un seuil de blessure.</p>
      <div class="chart-host" id="c-acwr">${acwr.svg}</div></section>
    <section class="band"><h2>Volume hebdomadaire</h2>
      <p class="legend">${trail ? `<span class="legend__item"><span class="key key--bar"></span>Heures d'effort</span> <span class="legend__item"><span class="key key--dplus"></span>D+ cumulé</span>` : `<span class="legend__item"><span class="key key--bar"></span>Kilomètres</span>`}</p>
      <div class="chart-host" id="c-load">${loadChart.svg}</div><p class="readout" id="r-load"></p>
      <dl class="facts facts--inline"><div><dt>Monotonie (7 j)</dt><dd>${F.num(load.monotony, 2)}</dd></div><div><dt>Strain (7 j)</dt><dd>${F.num(load.strain)}</dd></div><div><dt>Charge du jour</dt><dd>${F.num(last.load)}</dd></div></dl>
      <p class="muted">Polarisation des zones FC, découplage aérobie, VAM, efficacité en descente et
        durabilité — issus des échantillons FIT ingérés — sont regroupés dans <a href="#/analyse">Analyse</a>.</p></section>`;

  attachCursor($("#c-form"), chart, (i) => {
    if (i >= nHist) {
      const q = projected[i - nHist];
      readout($("#r-form"), `<strong>${F.dayLong(q.date)}</strong> · <em>projection (estimation)</em> · ${q.entering ? "en entrant dans la journée (course non comptée)" : `charge ${F.num(q.load)}`} · condition ${F.num(q.fitness, 1)} · fatigue ${F.num(q.fatigue, 1)} · forme ${q.form > 0 ? "+" : ""}${F.num(q.form, 1)}`);
      return;
    }
    const p = series[i];
    readout($("#r-form"), `<strong>${F.dayLong(p.date)}</strong> · charge ${F.num(p.load)} · condition ${F.num(p.fitness, 1)} · fatigue ${F.num(p.fatigue, 1)} · forme ${p.form > 0 ? "+" : ""}${F.num(p.form, 1)} · ACWR ${F.num(p.acwr, 2)}`);
  });
  attachCursor($("#c-acwr"), acwr, () => {});
  attachCursor($("#c-load"), loadChart, (i) => {
    const w = weeks[i];
    readout($("#r-load"), `<strong>Semaine du ${F.dayShort(w.week_start)}</strong> · ${w.sessions} séance${w.sessions > 1 ? "s" : ""} · ${F.hours(w.duration_s)} · ${F.distance(w.distance_m)}${trail ? ` · ${F.elevation(w.elevation_m)} D+${w.effort_km ? ` · ${F.num(w.effort_km, 1)} km-effort` : ""}` : ` · ${F.pace(w.distance_m, w.duration_s)}`} · charge ${F.num(w.load)}`);
  });
}

// ---------------------------------------------------------------------------
// Vue : Analyse (#50) — tendances FIT avancées, sorties de « Forme & charge »
// ---------------------------------------------------------------------------

/** Vue « Analyse » (#50) : rassemble les tendances calculées à partir des
 * échantillons FIT ingérés (`activities/fit/*.json`, #42) — polarisation 80/20
 * (#43), découplage aérobie (#45), VAM (#46), efficacité en descente (#47),
 * durabilité (#48) et la liste des segments de montée connus (#49,
 * `/api/climb-segments`, jusqu'ici jamais consommée par le tableau de bord).
 * Ces sections vivaient auparavant dans « Forme & charge » (#43-#48), qui reste
 * désormais concentrée sur la condition/fatigue/forme et le volume — voir
 * `docs/dashboard/views.md`.
 *
 * Fenêtre en SEMAINES (`?semaines=`), pas en jours comme « Forme & charge » :
 * toutes les tendances FIT interrogent déjà `/api/{decoupling,vam,descent,
 * durability}?weeks=` et `/api/load?weeks=` côté serveur — un seul paramètre
 * pour toute la vue, jamais une conversion approximative jours/semaines.
 * Défaut 12 semaines (revue de code #50) : les seuils par défaut côté serveur
 * (`M.DECOUPLING_TREND_WEEKS` et consorts) valent tous 12 — un défaut différent
 * ici (26 dans une version antérieure) aurait affiché une fenêtre plus large que
 * ce que chaque endpoint sert par défaut hors dashboard (CLI `arc_index.py`).
 *
 * Compatibilité des liens (#50) : l'ancien sélecteur de classe de descente
 * vivait sur `#/forme?jours=…&descente=…` (#47) — `route()` redirige ces
 * hashes vers `#/analyse?semaines=…&descente=…` plutôt que de les casser. */
async function viewAnalyse(params) {
  const weeks = Number(params.get("semaines")) || 12;
  const [load, decoupling, vam, descent, durability, segments, energy] = await Promise.all([
    api(`load?weeks=${weeks}`), api(`decoupling?weeks=${weeks}`), api(`vam?weeks=${weeks}`),
    api(`descent?weeks=${weeks}`), api(`durability?weeks=${weeks}`), api("climb-segments"),
    api(`energy-trend?weeks=${weeks}`),
  ]);
  const periods = [[12, "3 mois"], [26, "6 mois"], [52, "1 an"]].map(([w, l]) =>
    `<a class="seg ${w === weeks ? "is-on" : ""}" aria-current="${w === weeks ? "true" : "false"}" href="#/analyse?semaines=${w}">${l}</a>`).join("");
  const polarisationHtml = polarisationSection(load.polarisation_weeks, load.hr_zones_reason);
  const { html: decouplingHtml, chart: decouplingChart, points: decouplingPoints } = decouplingSection(decoupling);
  const { html: vamHtml, chart: vamChart, points: vamPoints } = vamSection(vam);
  const { html: descentHtml, chart: descentChart, points: descentPoints } = descentTrendSection(descent, weeks, params.get("descente"));
  const { html: durabilityHtml, chart: durabilityChart, points: durabilityPoints } = durabilitySection(durability);
  const { html: energyHtml, chart: energyChart, points: energyPoints } = energyTrendSection(energy);
  const segmentsHtml = climbSegmentsSection(segments.segments);
  // Revue de code #50, should-fix 1 : la présence d'échantillons FIT se décide sur
  // les DONNÉES elles-mêmes, jamais sur le HTML rendu — `durabilitySection` reste
  // affichée (un texte, jamais un graphique) dès qu'il existe des sorties longues
  // DÉCLARÉES (`long_runs > 0`, simple durée déclarée au contrat, `duration_s`),
  // même sans AUCUN échantillon FIT ingéré nulle part dans le workspace (cas
  // observé sur un workspace route sans `--with-samples`) : `durabilityHtml` seul
  // ne suffit donc PAS à conclure que le workspace a des échantillons FIT.
  const hasFitSamples = (load.polarisation_weeks || []).some((w) => w.polarisation)
    || decoupling.points.some((p) => p.decoupling_pct != null)
    || vam.points.some((p) => p.best_climb_vam_elapsed_m_h != null)
    || Object.keys(descent.classes || {}).length > 0
    || durability.points.some((p) => p.gap_fade_pct != null)
    || (segments.segments || []).length > 0
    || (energy.sessions || []).some((s) => s.model_kcal != null);
  if (!hasFitSamples) {
    main.innerHTML = header("Analyse", "Tendances calculées à partir des échantillons FIT (montre GPS) ingérés.")
      + empty("Pas encore d'échantillons FIT", "Ces tendances (polarisation des zones FC, découplage aérobie, VAM, "
        + "efficacité en descente, durabilité, dépense énergétique, historique des montées) exigent des "
        + "échantillons FIT ingérés (<code>activities/fit/*.json</code>), pas seulement le résumé d'une séance. "
        + "Chargez le skill <code>fit-download</code> (voir <code>skills/fit-download/SKILL.md</code>) pour les "
        + "récupérer depuis Garmin, puis relancez l'indexation.");
    return;
  }
  main.innerHTML = `${header("Analyse", `Tendances calculées à partir des échantillons FIT ingérés. ${hypLink()}`)}
    <div class="toolbar">${periods}</div>
    ${polarisationHtml}
    ${decouplingHtml}
    ${vamHtml}
    ${descentHtml}
    ${durabilityHtml}
    ${energyHtml}
    ${segmentsHtml}`;
  wirePolarisationChart(load.polarisation_weeks);
  wireClimbSegments(segments.segments);
  if (decouplingChart) {
    attachCursor($("#c-decoupling"), decouplingChart, (i) => {
      const p = decouplingPoints[i];
      readout($("#r-decoupling"), `<strong>${F.dayLong(p.date)}</strong> · ${F.esc(p.name || F.SPORT[p.sport] || p.sport)} · découplage ${F.num(p.decoupling_pct, 1)} %${p.ef_whole != null ? ` · EF ${F.num(p.ef_whole, 2)}` : ""}`);
    });
  }
  if (vamChart) {
    attachCursor($("#c-vam"), vamChart, (i) => {
      const p = vamPoints[i];
      readout($("#r-vam"), `<strong>${F.dayLong(p.date)}</strong> · ${F.esc(p.name || F.SPORT[p.sport] || p.sport)} · meilleure montée ${F.vam(p.best_climb_vam_elapsed_m_h)}`);
    });
  }
  if (descentChart) {
    attachCursor($("#c-descent"), descentChart, (i) => {
      const p = descentPoints[i];
      const refNote = p.reference_source === "non_descent" ? " · référence de repli (anneau creux)" : "";
      readout($("#r-descent"), `<strong>${F.dayLong(p.date)}</strong> · ${F.esc(p.name || F.SPORT[p.sport] || p.sport)} · efficacité ${F.efficiency(p.efficiency)}${p.mean_grade != null ? ` · pente moy. ${F.num(Math.abs(p.mean_grade) * 100, 1)} %` : ""}${refNote}`);
    });
  }
  if (durabilityChart) {
    attachCursor($("#c-durability"), durabilityChart, (i) => {
      const p = durabilityPoints[i];
      // FC par tiers (revue de code #48, nit) : affichée dans le readout au même
      // titre que le fade lui-même — un fait de séance utile pour situer le fade
      // (ex. distinguer une dérive cardiaque d'un effort simplement réduit).
      const hrParts = [p.hr_first_third_bpm, p.hr_middle_third_bpm, p.hr_last_third_bpm]
        .map((v) => (v != null ? F.num(v) : "—")).join("/");
      readout($("#r-durability"), `<strong>${F.dayLong(p.date)}</strong> · ${F.esc(p.name || F.SPORT[p.sport] || p.sport)} · fade GAP ${p.gap_fade_pct != null ? `${p.gap_fade_pct > 0 ? "+" : ""}${F.num(p.gap_fade_pct, 1)} %` : "—"}${p.ef_fade_pct != null ? ` · fade EF ${p.ef_fade_pct > 0 ? "+" : ""}${F.num(p.ef_fade_pct, 1)} %` : ""} · FC 1er/milieu/dernier ${hrParts} bpm`);
    });
  }
  if (energyChart) {
    attachCursor($("#c-energy"), energyChart, (i) => {
      const p = energyPoints[i];
      const flagTxt = p.flag ? " · écart notable" : "";
      // Sport TOUJOURS affiché ici (`F.SPORT[p.sport]`, jamais seulement en repli
      // du nom comme les autres tendances) : c'est justement ce qui distingue les
      // deux séries du graphique (trail plein / route creux, voir `energyTrendSection`).
      readout($("#r-energy"), `<strong>${F.dayLong(p.date)}</strong> · ${F.esc(F.SPORT[p.sport] || p.sport)}${p.name ? ` · ${F.esc(p.name)}` : ""} · Garmin ${F.kcal(p.garmin_kcal)} · modèle ${F.kcal(p.model_kcal)} · écart ${p.delta_pct > 0 ? "+" : ""}${F.num(p.delta_pct, 1)} %${flagTxt}`);
    });
  }
}

/** Section « Segments de montée » de la vue Analyse (#49, #50) : un tableau,
 * une ligne par segment connu (`/api/climb-segments`, servi depuis #49 mais
 * jusqu'ici jamais affiché nulle part dans le tableau de bord), lien vers
 * l'historique complet (`#/montee/<id>`, `viewClimbSegment`). Jamais de
 * coordonnée GPS ici (l'API n'en renvoie aucune, voir
 * `arc_climb_match.ASSUMPTIONS["privacy"]`). Vide (pas de section) tant
 * qu'aucun segment n'a encore été identifié (moins de deux occurrences d'une
 * même montée, voir `arc_climb_match.py`).
 *
 * Texte du lien (revue de code #50, should-fix 4) : `location` seul se répète
 * IDENTIQUE d'une ligne à l'autre (plusieurs montées différentes au même lieu
 * déclaré, ex. plusieurs cols d'un même massif nommés par la commune la plus
 * proche) — le lien porte donc aussi la distance/le D+ et la date de première
 * observation, seule information qui distingue deux montées de même lieu sans
 * jamais exposer de coordonnée GPS. Trié par occurrences décroissantes (les
 * montées les plus régulièrement gravies d'abord) — `climb_segment_list` (Python)
 * trie déjà ainsi, mais un tri explicite ici protège l'UI d'un futur changement
 * d'ordre côté serveur qui passerait inaperçu. */
function climbSegmentsSection(segments) {
  if (!segments || !segments.length) return "";
  const many = segments.length > CLIMB_SEGMENTS_PAGE_SIZE;
  return `<section class="band" id="segments"><h2>Segments de montée (${F.num(segments.length)})</h2>
    <p class="muted">Une même montée, reconnue d'une séance à l'autre (position GPS, ou à défaut profil
      distance/D+/pente — #49) : au moins deux occurrences pour apparaître ici, toutes périodes confondues
      (pas seulement la fenêtre choisie ci-dessus). Détail complet, occurrence par occurrence, dans
      l'historique de chaque segment.</p>
    ${many ? `<div class="toolbar toolbar--list">${searchField("seg-q", "", "Lieu de la montée", "Filtrer les segments par lieu")}</div>` : ""}
    <div id="seg-results" class="results"></div></section>`;
}

// Segments de montée : la liste grandit avec chaque nouveau lieu fréquenté (plusieurs
// centaines sur deux ans de trail). Tri par occurrences par défaut (les montées les plus
// régulièrement gravies d'abord — `climb_segment_list` trie déjà ainsi côté serveur, le tri
// explicite ici protège l'UI d'un changement d'ordre qui passerait inaperçu), filtre par
// lieu et pages de 15, sans toucher à l'URL : la vue Analyse porte déjà sa fenêtre.
const CLIMB_SEGMENTS_PAGE_SIZE = 15;
const CLIMB_SORT = {
  lieu: (s) => fold(s.location || ""), distance: (s) => s.distance_m || 0, dplus: (s) => s.gain_m || 0,
  pente: (s) => s.avg_grade || 0, occurrences: (s) => s.occurrences || 0,
  temps: (s) => (s.best_time_elapsed_s != null ? -s.best_time_elapsed_s : -Infinity),
};

function wireClimbSegments(segments) {
  const results = $("#seg-results");
  if (!results) return;
  const st = { q: "", sort: "occurrences", dir: -1, page: 1 };
  const render = () => {
    const f = fold(st.q.trim());
    const key = CLIMB_SORT[st.sort];
    const rows = segments.filter((s) => !f || fold(s.location || "Montée").includes(f))
      .sort((a, b) => ((key(a) > key(b) ? 1 : key(a) < key(b) ? -1 : 0) || (b.occurrences - a.occurrences)) * st.dir);
    const pg = paginate(rows, st.page, CLIMB_SEGMENTS_PAGE_SIZE);
    st.page = pg.page;
    if (!rows.length) {
      results.innerHTML = note(`Aucun segment dont le lieu contient « ${F.esc(st.q.trim())} ».`);
      return;
    }
    const body = pg.slice.map((s) => {
      const label = `${s.location || "Montée"} — ${F.distance(s.distance_m, 2)}, +${F.elevation(s.gain_m)} (depuis ${F.dayShort(s.first_seen_date)})`;
      return `<tr><td><a href="#/montee/${s.segment_id}">${F.esc(label)}</a></td>
      <td class="num col-opt">${F.distance(s.distance_m, 2)}</td><td class="num col-opt">+${F.elevation(s.gain_m)}</td>
      <td class="num col-opt">${F.num(s.avg_grade * 100, 1)} % <span class="tag">${F.esc(s.grade_class)}</span></td>
      <td class="num">${F.num(s.occurrences)}</td>
      <td class="num">${s.best_time_elapsed_s != null ? F.clockShort(s.best_time_elapsed_s) : "—"}</td></tr>`;
    }).join("");
    // « Meilleur temps » : clé négative, l'ordre décroissant par défaut met donc le plus rapide d'abord.
    results.innerHTML = `${st.q.trim() ? `<p class="results__sum" aria-live="polite"><strong>${F.num(rows.length)} segment${rows.length > 1 ? "s" : ""}</strong> sur ${F.num(segments.length)}</p>` : ""}
      <div class="table-wrap"><table class="data data--compact data--segments"><thead><tr>
      ${sortTh("lieu", "Lieu", st, false)}${sortTh("distance", "Distance", st, true, "col-opt")}${sortTh("dplus", "D+", st, true, "col-opt")}
      ${sortTh("pente", "Pente moy.", st, true, "col-opt")}${sortTh("occurrences", `<span class="lbl-long">Occurrences</span><span class="lbl-short">Occ.</span>`, st)}${sortTh("temps", `<span class="lbl-long">Meilleur temps</span><span class="lbl-short">Meilleur</span>`, st)}</tr></thead>
      <tbody>${body}</tbody></table></div>
      ${pagerHtml(pg, rows.length, "Pages de segments de montée")}`;
  };
  render();
  $("#seg-q")?.addEventListener("input", debounce((e) => { st.q = e.target.value; st.page = 1; render(); }));
  results.addEventListener("click", (e) => {
    const sortBtn = e.target.closest("[data-sort]");
    if (sortBtn) {
      const k = sortBtn.dataset.sort;
      st.dir = st.sort === k ? -st.dir : (k === "lieu" ? 1 : -1);
      st.sort = k;
      st.page = 1;
      render();
      results.querySelector(`[data-sort="${k}"]`)?.focus();
      return;
    }
    const pageBtn = e.target.closest("[data-page]");
    if (pageBtn && !pageBtn.disabled) {
      st.page = Number(pageBtn.dataset.page);
      render();
      $("#segments").scrollIntoView({ block: "start" });
      results.querySelector(".pager [aria-current]")?.focus({ preventScroll: true });
    }
  });
}

/** Section « Polarisation 80/20 » de la vue Analyse (#43, #50) : une barre empilée par
 * semaine (facile / modérée / difficile, seuils Seiler DÉDIÉS à la méthode de zones
 * du profil — voir `arc_metrics.seiler_bounds`), en SVG (pas de style en ligne, CSP).
 * Une semaine sans AUCUNE activité à échantillons FIT (`polarisation: null`, voir
 * `arc_index.weekly_polarisation`) reste visible, barre grise, plutôt que masquée :
 * on veut voir où la donnée manque, pas la faire disparaître silencieusement.
 *
 * Une semaine par groupe `<g>` (`tabindex`/`role="img"`/`aria-label`, navigable au
 * clavier), pour que `wirePolarisationChart` (appelée après insertion dans le DOM)
 * mette à jour un `readout` visible au survol/focus — jamais SEULEMENT un `<title>`
 * SVG, illisible au clavier et peu visible à la souris (revue de code #43, nit). Un
 * résumé de la semaine la plus récente reste affiché par défaut, avant toute
 * interaction. Les seuils facile/modérée/difficile dépendent de la méthode de zones
 * du profil (Karvonen, LTHR ou %FCmax) : jamais un simple « Z1-Z2/Z3/Z4-Z5 » fixe,
 * faux pour LTHR et %FCmax (voir `arc_metrics.seiler_bounds`). */
function polarisationSection(weeks, hrZonesReason) {
  // `hrZonesReason` (non nul) : AUCUNE zone n'est calculable pour ce profil (FC max/
  // repos/seuil manquante, ou méthode forcée incomplète) — la section reste visible
  // avec la raison plutôt que de disparaître silencieusement (revue de code #43,
  // round 3). Distinct d'une fenêtre simplement sans séances à échantillons FIT
  // (`weeks` vide de données), qui n'est pas une erreur de configuration.
  if (hrZonesReason) {
    return `<section class="band"><h2>Polarisation 80/20</h2>${note(F.esc(hrZonesReason))}</section>`;
  }
  if (!weeks || !weeks.some((w) => w.polarisation)) return "";
  const barW = 22, gap = 8, chartH = 64;
  const groups = weeks.map((w, i) => {
    const x = i * (barW + gap);
    const p = w.polarisation;
    if (!p) {
      const label = `${F.dayShort(w.week_start)} : pas d'échantillons FIT`;
      return `<g class="polar-week" data-i="${i}" tabindex="0" role="img" aria-label="${F.esc(label)}">
        <rect class="polar polar--none" x="${x}" y="${chartH - 4}" width="${barW}" height="4" rx="2"></rect></g>`;
    }
    const segs = [["low", p.low_pct], ["moderate", p.moderate_pct], ["high", p.high_pct]];
    let y = chartH;
    const rects = segs.map(([cls, pct]) => {
      const segH = Math.max(0, (pct / 100) * chartH);
      y -= segH;
      return `<rect class="polar polar--${cls}" x="${x}" y="${y.toFixed(1)}" width="${barW}" height="${segH.toFixed(1)}"></rect>`;
    }).join("");
    const label = `${F.dayShort(w.week_start)} : facile ${F.num(p.low_pct, 0)} % · modérée ${F.num(p.moderate_pct, 0)} % · difficile ${F.num(p.high_pct, 0)} %`;
    return `<g class="polar-week" data-i="${i}" tabindex="0" role="img" aria-label="${F.esc(label)}">${rects}</g>`;
  }).join("");
  const totalW = weeks.length * barW + (weeks.length - 1) * gap;
  const latest = [...weeks].reverse().find((w) => w.polarisation);
  const defaultReadout = latest
    ? polarisationReadoutHtml(latest)
    : "Pas encore de semaine avec échantillons FIT.";
  return `<section class="band"><h2>Polarisation 80/20</h2>
    <p class="muted">Part du temps en zone FC facile, modérée et difficile — seuils propres à la méthode de
      zones du profil (Karvonen, FC au seuil ou %FC max, voir ${hypLink("zones")}),
      sur les semaines avec séances à échantillons FIT.</p>
    <p class="legend"><span class="legend__item"><span class="key key--polar-low"></span>Facile</span> <span class="legend__item"><span class="key key--polar-moderate"></span>Modérée</span> <span class="legend__item"><span class="key key--polar-high"></span>Difficile</span></p>
    <div class="chart-host" id="c-polar"><svg class="polar-chart" viewBox="0 0 ${totalW} ${chartH}">${groups}</svg></div>
    <p class="readout" id="r-polar">${defaultReadout}</p></section>`;
}

function polarisationReadoutHtml(week) {
  const p = week.polarisation;
  return `<strong>Semaine du ${F.dayShort(week.week_start)}</strong> · facile ${F.num(p.low_pct, 0)} % · modérée ${F.num(p.moderate_pct, 0)} % · difficile ${F.num(p.high_pct, 0)} %`;
}

/** Câble le survol/focus clavier de chaque semaine du graphique de polarisation vers
 * le `readout` visible sous le graphique (voir `polarisationSection`) — appelée une
 * fois le HTML inséré dans le DOM, jamais avant (les `<g data-i>` n'existent pas
 * encore sinon). */
function wirePolarisationChart(weeks) {
  const host = $("#c-polar");
  if (!host) return;
  host.querySelectorAll(".polar-week").forEach((g) => {
    const week = weeks[Number(g.dataset.i)];
    if (!week) return;
    const show = () => readout($("#r-polar"),
      week.polarisation ? polarisationReadoutHtml(week) : `${F.dayLong(week.week_start)} : pas d'échantillons FIT.`);
    g.addEventListener("mouseenter", show);
    g.addEventListener("focus", show);
  });
}

// ---------------------------------------------------------------------------
// Carte « Foulée » de la vue Santé (#151) : dynamique de course MESURÉE par la montre + indices des
// inspections photo, avec confiance et contradictions. Jamais un diagnostic, aucune modification de charge.
// ---------------------------------------------------------------------------

const NB = " ";
// Sens d'une variation : décidé CÔTÉ SERVEUR (`direction` : up / down / flat, `arc_gait.change_direction`,
// testé en palier D) — jamais déduit ici d'un nombre arrondi. Flèche neutre (ni bon ni mauvais) + valeur signée ;
// « stable » sans signe quand la variation s'arrondit à zéro à l'affichage.
const GAIT_ARROW = { up: "↑", down: "↓", flat: "→" };
function gaitTrend(direction, magnitudeText) {
  if (!direction) return "";
  if (direction === "flat") return `<span class="nowrap"><span aria-label="stable">${GAIT_ARROW.flat}</span> stable</span>`;
  const sign = direction === "up" ? "+" : "\u2212";
  return `<span class="nowrap"><span aria-label="${direction === "up" ? "en hausse" : "en baisse"}">${GAIT_ARROW[direction]}</span> ${sign}${magnitudeText}</span>`;
}
const GAIT_ROWS = [
  ["ground_contact_s", "Temps de contact au sol", (v) => `${F.num(v * 1000, 0)}${NB}ms`, (d) => `${F.num(Math.abs(d) * 1000, 0)}${NB}ms`],
  ["stance_balance_pct", "Balance du temps de contact", (v) => `${F.num(v, 1)}${NB}%`, (d) => `${F.num(Math.abs(d), 2)}${NB}pt`],
  ["vertical_oscillation_m", "Oscillation verticale", (v) => F.oscillation(v), (d) => F.oscillation(Math.abs(d))],
  ["vertical_ratio_pct", "Ratio vertical", (v) => `${F.num(v, 1)}${NB}%`, (d) => `${F.num(Math.abs(d), 2)}${NB}pt`],
  ["step_length_m", "Longueur de pas", (v) => F.stepLength(v), (d) => F.stepLength(Math.abs(d))],
  ["cadence_spm", "Cadence (pas/min, deux pieds)", (v) => `${F.num(v, 0)}${NB}pas/min`, (d) => `${F.num(Math.abs(d), 0)}${NB}pas/min`],
];

/** Une valeur par date (plusieurs séances le même jour : moyenne) pour l'axe du graphique. */
function gaitDaily(series) {
  const byDate = new Map();
  for (const p of series) {
    const cur = byDate.get(p.date) || [];
    cur.push(p.value);
    byDate.set(p.date, cur);
  }
  const dates = [...byDate.keys()].sort();
  return { dates, values: dates.map((d) => byDate.get(d).reduce((a, b) => a + b, 0) / byDate.get(d).length) };
}

function gaitInspectionFacts(insp) {
  if (!insp?.pairs?.length) return `<p class="muted">Aucune inspection photo enregistrée : demandez-en une au coach (environ tous les 200${NB}km) pour obtenir un indice d'attaque et d'asymétrie d'usure.</p>`;
  const rows = insp.pairs.map((p) => {
    const strike = Object.entries(p.strike_hints || {}).filter(([h]) => GEAR_HINT[h]).map(([h, n]) => `${F.esc(GEAR_HINT[h])} (${n}/${p.n})`).join(", ") || "—";
    const asym = p.asymmetry?.length ? p.asymmetry.map((a) => `${F.esc(F.dayShort(a.date))} : ${F.esc(a.level === "none" ? "aucune" : `${GEAR_ASYMMETRY[a.level] || a.level}${a.side ? ` (${GEAR_SIDE[a.side] || a.side})` : ""}`)}`).join(" · ") : "—";
    const rep = p.asymmetry_repeats ? ` <span class="tag">même côté ${p.asymmetry_repeats.count}/${p.asymmetry_repeats.of} fois : ${F.esc(GEAR_SIDE[p.asymmetry_repeats.side] || p.asymmetry_repeats.side)}</span>` : "";
    return `<tr><th scope="row">${gearLink(p.gear_id, p.name)}<br><small class="muted">${p.n} inspection${p.n > 1 ? "s" : ""}</small></th><td>${strike}</td><td>${asym}${rep}</td></tr>`;
  }).join("");
  return `<div class="table-wrap"><table class="data data--compact"><thead><tr><th scope="col">Paire</th><th scope="col">Indices</th><th scope="col">Asymétrie d'usure</th></tr></thead><tbody>${rows}</tbody></table></div>`;
}

/** `{html, mount}` : `html` à poser dans la page, `mount()` à appeler ensuite (curseurs des graphiques). */
function gaitCard(g) {
  const link = `<p class="note">Indice, jamais un diagnostic : cette synthèse ne modifie ni la charge ni le plan d'entraînement. Inspections photo : <a href="#/materiel">vue Matériel</a>.</p>`;
  if (!g) return { html: "", mount() {} };
  const conf = g.confidence || {};
  const head = `<h2>Comment évolue ma foulée ?</h2>`;
  if (!conf.sessions_with_dynamics && !conf.inspections) {
    return { html: `<section class="band" id="foulee">${head}${empty("Pas encore de données de foulée", `Ni dynamique de course (temps de contact, balance, oscillation…) dans l'index, ni inspection photo de chaussures. Les séances de course doivent avoir leurs échantillons FIT (<code>skills/fit-download</code>) ; pour ceux déjà téléchargés : <code>download_fit.py --refresh-dynamics</code>.`)}</section>`, mount() {} };
  }
  const dyn = g.dynamics || {};
  const rowsHtml = GAIT_ROWS.filter(([k]) => dyn[k]).map(([k, label, fmt, fmtDelta]) => {
    const d = dyn[k];
    const change = d.change != null ? `${gaitTrend(d.direction, fmtDelta(d.change))} <small class="muted gait-counts">(${d.recent_n} récentes / ${d.prior_n} avant)</small>` : `<span class="muted">pas assez de séances de chaque côté</span>`;
    const extra = k === "stance_balance_pct" ? `<br><small class="muted">écart moyen à 50${NB}% : ${F.num(d.mean_gap_pts, 1)}${NB}pt</small>` : "";
    return `<tr><th scope="row">${F.esc(label)}<small class="muted gait-n-inline">${d.n} séance${d.n > 1 ? "s" : ""}</small></th><td class="num">${fmt(d.mean)}${extra}</td><td class="gait-trend">${change}</td><td class="num gait-col-n">${d.n}</td></tr>`;
  }).join("");
  const bal = dyn.stance_balance_pct;
  const balanceNote = bal
    ? `<p class="note">Balance : ${F.num(bal.beyond_band_share * 100, 0)}${NB}% des séances mesurées (${bal.beyond_band_n}/${bal.n}) s'écartent de plus de ${F.num(bal.band_pts, 0)}${NB}point de 50${NB}% (bande = ${F.esc(bal.band_label)}, pas un seuil publié). Le côté que porte ce pourcentage (gauche ou droite) n'est pas établi par le format FIT : on parle d'écart, jamais de pied gauche ou droit.</p>`
    : (conf.sessions_with_dynamics ? `<p class="note">Aucune séance n'a de balance du temps de contact (selon le capteur) : elle n'est jamais remplacée par 50${NB}%.</p>` : "");
  const noDynamics = !conf.sessions_with_dynamics;      // la cadence seule remplit une ligne : elle ne dit rien de la dynamique
  const refreshHint = `<p class="muted">Aucune séance de course de la fenêtre ne porte de dynamique de course (temps de contact, balance, oscillation…) : les échantillons FIT sont absents, ou l'index a été reconstruit avant l'extraction. Pour les FIT déjà téléchargés : <code>python3 skills/fit-download/scripts/download_fit.py --refresh-dynamics</code>, puis rechargez.</p>`;
  const table = rowsHtml
    ? `${noDynamics ? refreshHint : ""}<div class="table-wrap"><table class="data data--compact gait-table"><thead><tr><th scope="col">Grandeur</th><th scope="col" class="num">Moyenne</th><th scope="col"><span class="gait-long">4 dernières semaines vs avant</span><span class="gait-short">4 sem. vs avant</span></th><th scope="col" class="num gait-col-n">Séances</th></tr></thead><tbody>${rowsHtml}</tbody></table></div>`
    : refreshHint;

  const charts = [];
  const gct = dyn.ground_contact_s;
  if (gct?.series?.length) {
    const { dates, values } = gaitDaily(gct.series);
    const c = timeChart(dates, [{ type: "line", values: values.map((v) => v * 1000), cls: "line line--gait" }, { type: "dots", values: values.map((v) => v * 1000), cls: "dot dot--gait" }], [],
      { height: 190, label: "Temps de contact au sol en millisecondes", yFormat: (v) => `${F.num(v, 0)}` });
    charts.push({ id: "gct", title: "Temps de contact au sol (ms)", c, show: (i) => `<strong>${F.dayLong(dates[i])}</strong> · ${F.num(values[i] * 1000, 0)}${NB}ms` });
  }
  if (bal?.series?.length) {
    const { dates, values } = gaitDaily(bal.series);
    const lo = 50 - bal.band_pts;
    const hi = 50 + bal.band_pts;
    const c = timeChart(dates, [
      { type: "band", lo: dates.map(() => lo), hi: dates.map(() => hi), cls: "band-fill" },
      { type: "line", values, cls: "line line--gait" }, { type: "dots", values, cls: "dot dot--gait" },
    ], [{ type: "hline", value: 50, cls: "mark mark--zero", label: "50 %" }],
    { height: 250, y: { min: Math.floor(Math.min(lo, ...values) - 0.5), max: Math.ceil(Math.max(hi, ...values) + 0.5) }, label: "Balance du temps de contact en pourcentage", yFormat: (v) => `${F.num(v, 0)}` });
    charts.push({ id: "bal", title: "Balance du temps de contact (%), bande grisée = bande du projet", c, show: (i) => `<strong>${F.dayLong(dates[i])}</strong> · ${F.num(values[i], 2)}${NB}% (écart ${F.num(Math.abs(values[i] - 50), 2)}${NB}pt)` });
  }
  const chartsHtml = charts.map((x) => `<h3>${F.esc(x.title)}</h3><div class="chart-host" id="c-gait-${x.id}">${x.c.svg}</div><p class="readout" id="r-gait-${x.id}"></p>`).join("");

  const contradictions = (g.contradictions || []).length
    ? `<h3>Désaccords entre les sources</h3><ul class="gait-contradictions">${g.contradictions.map((c) => `<li>${F.esc(c.message)} ${c.resolution === "measure_wins" ? `<span class="tag">la mesure prime</span>` : ""}</li>`).join("")}</ul>`
    : (conf.inspections && conf.sessions_with_dynamics ? `<p class="muted">Aucun désaccord relevé entre les inspections et la dynamique mesurée.</p>` : "");

  const levelTag = (lvl) => (lvl === "ok" ? "" : ` <span class="tag tag--alert">${lvl === "none" ? "aucune donnée" : "confiance faible"}</span>`);
  const confidence = `<p class="muted">${conf.sessions_with_dynamics} séance${conf.sessions_with_dynamics > 1 ? "s" : ""} de course avec dynamique sur ${conf.running_sessions} (dont ${conf.sessions_with_balance} avec balance)${levelTag(conf.dynamics_level)} · ${conf.inspections} inspection${conf.inspections > 1 ? "s" : ""} sur ${conf.pairs_inspected} paire${conf.pairs_inspected > 1 ? "s" : ""}${levelTag(conf.inspections_level)} — ${g.window.weeks} dernières semaines pour les séances.</p>`;

  const html = `<section class="band gait" id="foulee">${head}
    <p class="muted">Ce que la montre mesure de votre foulée sur les séances de course (route et trail), et ce que les photos de semelles suggèrent — en séparant le mesuré du deviné.</p>
    ${confidence}${table}${balanceNote}${chartsHtml}
    <h3>Indices tirés des inspections photo</h3>${gaitInspectionFacts(g.inspections)}
    ${contradictions}${link}</section>`;
  return {
    html,
    mount() {
      for (const x of charts) attachCursor($(`#c-gait-${x.id}`), x.c, (i) => readout($(`#r-gait-${x.id}`), x.show(i)));
      if (new URLSearchParams(location.hash.split("?")[1] || "").get("section") === "foulee") {
        setTimeout(() => $("#foulee")?.scrollIntoView(), 0);   // `route()` remonte en haut APRÈS la vue
      }
    },
  };
}

/** Carte « Exposition à l'altitude » de la vue Santé (#185) : séances et temps au-dessus de 1 500 / 2 000 m
 * sur 14 et 28 jours (échantillons FIT). Indicateur d'exposition, pas un modèle d'acclimatation. */
function altitudeCard(a) {
  const head = `<h2>Exposition à l'altitude</h2>`;
  if (!a) return "";
  if (a.status === "no_activity" || a.status === "no_altitude") {
    return `<section class="band" id="altitude">${head}${empty(a.status === "no_altitude" ? "Pas d'altitude dans les séances" : "Pas de séance récente", a.status === "no_altitude" ? `Des séances existent, mais aucune n'a d'échantillon d'altitude : échantillons FIT absents ou capteur muet (<code>skills/fit-download</code>). Ce n'est pas une exposition nulle.` : `Aucune séance indexée sur la fenêtre : rien à mesurer.`)}</section>`;
  }
  const rows = Object.values(a.windows).map((w) => {
    const t15 = w.thresholds["1500"], t20 = w.thresholds["2000"];
    const missing = w.sessions_without_altitude ? `<small class="muted"> · ${w.sessions_without_altitude} sans altitude (non comptée${w.sessions_without_altitude > 1 ? "s" : ""})</small>` : "";
    return `<tr><th scope="row">${w.window_days} jours${missing}</th><td class="num">${t15.sessions} séance${t15.sessions > 1 ? "s" : ""} · ${F.duration(t15.duration_s)}</td><td class="num">${t20.sessions} séance${t20.sessions > 1 ? "s" : ""} · ${F.duration(t20.duration_s)}</td><td class="num">${w.max_altitude_m != null ? `${F.num(w.max_altitude_m)}${NB}m` : "—"}</td></tr>`;
  }).join("");
  return `<section class="band" id="altitude">${head}
    <p class="muted">Temps passé en altitude à l'entraînement d'après les échantillons FIT (séances de terrain) : ${F.esc(a.note)}.</p>
    <div class="table-wrap"><table class="data data--compact"><thead><tr><th scope="col">Fenêtre</th><th scope="col" class="num">≥ 1${NB}500${NB}m</th><th scope="col" class="num">≥ 2${NB}000${NB}m</th><th scope="col" class="num">Max</th></tr></thead><tbody>${rows}</tbody></table></div>
    <p class="note">Une séance compte au seuil à partir de 5 minutes au-dessus. Altitude barométrique ou GPS approximative près d'un seuil. Cette exposition réduit légèrement la pénalité d'altitude du plan d'une course à 14 jours ou moins (approximation du projet) ; ce n'est pas un modèle d'acclimatation.</p></section>`;
}

// ---------------------------------------------------------------------------
// Vue : Santé
// ---------------------------------------------------------------------------

async function viewHealth(params) {
  const days = Number(params.get("jours")) || 90;
  // La carte « Foulée » (#151) ne dépend pas du bilan matinal : elle est montrée même quand celui-ci est
  // désactivé ou vide. Son échec ne doit jamais masquer la vue Santé.
  const [data, gaitData, altData] = await Promise.all([api(`health?days=${days}`), api("gait").catch(() => null), api("altitude-exposure").catch(() => null)]);
  const gait = gaitCard(gaitData);
  const altitude = altitudeCard(altData);   // idem : un échec n'empêche jamais la vue Santé
  const mode = data.morning_check;
  if (mode === "off") {
    main.innerHTML = header("Santé") + empty("Bilan matinal désactivé", "Avec <code>[health].morning_check = \"off\"</code>, le coach ne récupère ni HRV, ni FC de repos, ni readiness : leur absence ici n'est pas un manque. Passez à <code>minimal</code> ou <code>full</code> pour suivre ces courbes.") + gait.html + altitude;
    gait.mount();
    return;
  }
  const s = data.series;
  const dates = s.map((p) => p.date);
  if (!s.some((p) => p.readiness_score != null || p.hrv_overnight_ms != null || p.resting_hr_bpm != null)) {
    main.innerHTML = header("Santé") + empty("Pas encore de données de santé", "Les fichiers <code>medical/AAAA-MM-JJ_health.md</code> écrits par la synchronisation alimentent ces courbes.") + gait.html + altitude;
    gait.mount();
    return;
  }
  const charts = [];
  if (mode === "full") {
    const hasGarminBand = s.some((p) => p.hrv_baseline_low_ms != null);
    charts.push(["hrv", "HRV nocturne",
      (hasGarminBand
        ? "Bande pleine : référence Garmin (valeur brute de la nuit). Tirets : référence "
        : "Pas de bande Garmin renseignée : les tirets sont la référence ")
        + "personnelle — bande appliquée à la MOYENNE 7 j (courbe pointillée), pas à la valeur "
        + "brute de la nuit (moyenne 7 j de ln(HRV) vs 60 j ± 0,5 ET, fenêtres non chevauchantes).",
      timeChart(dates, [
      { type: "band", lo: s.map((p) => p.hrv_baseline_low_ms), hi: s.map((p) => p.hrv_baseline_high_ms), cls: "band-fill" },
      { type: "line", values: s.map((p) => p.hrv_personal_low_ms), cls: "line line--personal" },
      { type: "line", values: s.map((p) => p.hrv_personal_high_ms), cls: "line line--personal" },
      { type: "line", values: s.map((p) => p.hrv_personal_mean7_ms), cls: "line line--personal-mean" },
      { type: "line", values: s.map((p) => p.hrv_overnight_ms), cls: "line line--hrv" },
      { type: "dots", values: s.map((p) => p.hrv_overnight_ms), cls: "dot dot--hrv" },
    ], [], { height: 190, label: "HRV nocturne en millisecondes", yFormat: (v) => `${F.num(v)}` }), true]);
    charts.push(["rhr", "FC de repos", "Tirets : médiane 7 j, puis seuils +5 (à surveiller) et +7 (nettement élevée).", timeChart(dates, [
      { type: "line", values: s.map((p) => p.rhr_median7), cls: "line line--median" },
      { type: "line", values: s.map((p) => (p.rhr_median7 != null ? p.rhr_median7 + 5 : null)), cls: "line line--warn" },
      { type: "line", values: s.map((p) => (p.rhr_median7 != null ? p.rhr_median7 + 7 : null)), cls: "line line--alert" },
      { type: "line", values: s.map((p) => p.resting_hr_bpm), cls: "line line--rhr" },
      { type: "dots", values: s.map((p) => p.resting_hr_bpm), cls: "dot dot--rhr" },
    ], [], { height: 170, label: "Fréquence cardiaque de repos", yFormat: (v) => `${F.num(v)}` }), false]);
  }
  charts.push(["ready", "Readiness", "", timeChart(dates, [
    { type: "bars", values: s.map((p) => p.readiness_score), cls: (i, v) => `bar bar--ready-${v >= 60 ? "hi" : v >= 40 ? "mid" : "lo"}` },
  ], [], { height: 150, y: { min: 0, max: 100 }, label: "Readiness sur 100" }), false]);
  if (mode === "full") {
    // Besoin de sommeil (#37) : lu depuis `/api/summary` (source unique déjà résolue
    // côté serveur — profil ou défaut moteur), jamais recalculé ni codé en dur ici, pour
    // que cette ligne reste cohérente avec la dette de sommeil calculée sur ce même besoin.
    const needS = SUMMARY.sleep_debt?.sleep_need_s ?? 27000;
    // Seuils d'affichage (#37) : servis par l'API (`thresholds.sleep_debt_warn_h`/
    // `sleep_debt_alert_h`, `scripts/arc_metrics.py::SLEEP_DEBT_WARN_S`/`ALERT_S`) —
    // jamais une deuxième copie de ces nombres côté JS.
    const debtWarnH = data.thresholds?.sleep_debt_warn_h ?? 5;
    const debtAlertH = data.thresholds?.sleep_debt_alert_h ?? 10;
    charts.push(["sleep", "Sommeil", "", timeChart(dates, [
      { type: "bars", values: s.map((p) => (p.sleep_total_s ? p.sleep_total_s / 3600 : null)), cls: "bar bar--sleep" },
    ], [{ type: "hline", value: needS / 3600, cls: "mark", label: F.duration(needS) }], { height: 150, y: { min: 0 }, label: "Durée de sommeil en heures", yFormat: (v) => `${F.num(v)} h` }), false]);
    charts.push(["sleepdebt", "Dette de sommeil (7 j)",
      `Somme, sur les nuits mesurées des 7 derniers jours, du manque par rapport au besoin (${F.duration(needS)}) — une nuit non mesurée n'est jamais comptée comme un manque de 0 h.`,
      timeChart(dates, [
        { type: "bars", values: s.map((p) => (p.sleep_debt_7d_s != null ? p.sleep_debt_7d_s / 3600 : null)), cls: (i, v) => `bar bar--sleep${v > debtAlertH ? " bar--alert" : v > debtWarnH ? " bar--warn" : ""}` },
      ], [], { height: 150, y: { min: 0 }, label: "Dette de sommeil cumulée en heures", yFormat: (v) => `${F.num(v)} h` }), false]);
  }
  const periods = [[30, "1 mois"], [90, "3 mois"], [180, "6 mois"]].map(([d, l]) => `<a class="seg ${d === days ? "is-on" : ""}" aria-current="${d === days ? "true" : "false"}" href="#/sante?jours=${d}">${l}</a>`).join("");
  main.innerHTML = `${header("Santé", mode === "minimal" ? "Bilan minimal : readiness seule." : "Triade du matin : HRV, FC de repos, readiness — et le verdict du coach, jour par jour.")}
    <div class="toolbar">${periods}</div>
    <p class="readout readout--sticky" id="r-health"></p>
    ${charts.map(([id, title, sub, c, strip]) => `<section class="band"><h2>${title}</h2>${sub ? `<p class="muted">${sub}</p>` : ""}<div class="chart-host" id="c-${id}">${c.svg}</div>${strip ? `<div class="strip-host">${verdictStrip(dates, s.map((p) => p.verdict))}<p class="legend legend--small"><span class="legend__item"><span class="key key--green"></span>Maintenir</span> <span class="legend__item"><span class="key key--amber"></span>Alléger</span> <span class="legend__item"><span class="key key--red"></span>Repos</span> — verdicts du coach</p></div>` : ""}</section>`).join("")}${gait.html}${altitude}`;
  const show = (i) => {
    const p = s[i];
    const bits = [`<strong>${F.dayLong(p.date)}</strong>`];
    if (p.hrv_overnight_ms != null) bits.push(`HRV ${F.num(p.hrv_overnight_ms)} ms`);
    if (p.hrv_personal_mean7_ms != null) bits.push(`moyenne 7 j ${F.num(p.hrv_personal_mean7_ms)} ms`);
    if (p.hrv_personal_status && p.hrv_personal_status !== "en_construction") {
      bits.push(`référence personnelle : ${{ sous: "sous", au_dessus: "au-dessus de", dans_la_norme: "dans" }[p.hrv_personal_status]} la norme`);
    } else if (p.hrv_personal_status === "en_construction") {
      bits.push("référence personnelle en construction");
    }
    if (p.resting_hr_bpm != null) bits.push(`FC repos ${F.num(p.resting_hr_bpm)}${p.rhr_delta != null ? ` (${p.rhr_delta > 0 ? "+" : ""}${F.num(p.rhr_delta)})` : ""}`);
    if (p.readiness_score != null) bits.push(`readiness ${F.num(p.readiness_score)}`);
    if (p.sleep_total_s) bits.push(`sommeil ${F.duration(p.sleep_total_s)}${p.sleep_score != null ? ` (${F.num(p.sleep_score)})` : ""}`);
    if (p.sleep_debt_7d_s != null) bits.push(`dette 7 j ${F.num(p.sleep_debt_7d_s / 3600, 1)} h (${p.nights_counted} nuits)`);
    readout($("#r-health"), bits.join(" · ") + (p.verdict ? `<br>${verdictChip(p.verdict)} ${F.esc(p.verdict_reason || "")}` : ""));
  };
  for (const [id, , , c] of charts) attachCursor($(`#c-${id}`), c, show);
  gait.mount();
}

// ---------------------------------------------------------------------------
// Vue : Semaine
// ---------------------------------------------------------------------------

/** Frise du bloc planifié (#193) : phases semaine par semaine, volume prévu/réalisé, drapeau de course.
 * `selected` : lundi de la semaine affichée (vue Semaine). Rien n'est rendu sans plan au contrat ;
 * une erreur d'API ne casse jamais la vue qui l'accueille. Retourne `{ html, mount }` (`mount` branche
 * le lecteur de détail et recentre la frise, une fois le HTML inséré). */
async function friseSection(selected = null) {
  let b;
  try { b = await api("block"); } catch { return { html: "", mount: () => {} }; }
  if (!b || b.status !== "ok" || !b.weeks.length) return { html: "", mount: () => {} };
  const TYPE = { build: "construction", recovery: "allégée", taper: "affûtage", race: "course", lead_in: "mise en route", post_race: "récupération post-course" };
  const peak = Math.max(1, ...b.weeks.map((w) => Math.max(w.target_duration_s || 0, (w.done && w.done.duration_s) || 0)));
  const describe = (w) => {
    const bits = [`Semaine du ${F.dayShort(w.week_start)}`, w.phase_label];
    if (w.week_type) bits.push(TYPE[w.week_type] || w.week_type);
    if (!w.planned) bits.push("aucun fichier de semaine (trou dans le bloc)");
    else bits.push(w.target_duration_s ? `prévu ${F.duration(w.target_duration_s)}${w.target_elevation_m ? ` · ${F.elevation(w.target_elevation_m)}` : ""}` : "volume prévu non renseigné");
    if (w.done) bits.push(`réalisé ${F.duration(w.done.duration_s)}${w.done.elevation_m ? ` · ${F.elevation(w.done.elevation_m)}` : ""}${w.done.partial ? " (semaine en cours)" : ""}`);
    if (w.status === "current") bits.push("semaine en cours");
    if (w.is_race_week) bits.push("semaine de course");
    return bits.join(", ");
  };
  const items = b.weeks.map((w) => {
    const d = F.parseDate(w.week_start);
    return {
      href: `#/semaine?debut=${w.week_start}`, aria: describe(w), tip: describe(w), phase: w.phase,
      phaseText: w.phase_label,
      tick: `${String(d.getDate()).padStart(2, "0")}/${String(d.getMonth() + 1).padStart(2, "0")}`,
      h: w.target_duration_s ? w.target_duration_s / peak : null, d: w.done ? w.done.duration_s / peak : null,
      light: w.light, current: w.status === "current", selected: w.week_start === selected, race: w.is_race_week,
    };
  });
  const present = new Set(b.weeks.map((w) => w.phase));
  const keys = b.phases.filter((p) => present.has(p.id)).map((p) => `<span class="legend__item"><span class="key key--phase-${p.id}"></span>${F.esc(p.label)}</span>`);
  if (present.has("other")) keys.push(`<span class="legend__item"><span class="key key--phase-other"></span>Autre libellé</span>`);
  if (present.has("unknown")) keys.push(`<span class="legend__item"><span class="key key--phase-unknown"></span>Phase inconnue</span>`);
  if (present.has("missing")) keys.push(`<span class="legend__item"><span class="key key--phase-missing"></span>Semaine sans plan</span>`);
  const idx = b.weeks.findIndex((w) => w.status === "current");
  const race = b.race;
  const raceTxt = race ? (race.in_block ? `course le ${F.dateLong(race.date)}${race.days_left >= 0 ? ` (dans ${race.days_left} j)` : ""}` : `course le ${F.dateLong(race.date)}, hors des semaines planifiées`) : "";
  const pos = idx >= 0 ? `Semaine ${idx + 1} sur ${b.weeks.length} du bloc` : (b.weeks[0].status === "future" ? `Bloc de ${b.weeks.length} semaines à venir` : `Bloc de ${b.weeks.length} semaines terminé`);
  const unknownTxt = b.unknown_weeks ? ` · ${b.unknown_weeks} semaine${b.unknown_weeks > 1 ? "s" : ""} sans phase renseignée (plan antérieur au squelette de bloc ?)` : "";
  const missingTxt = b.missing_weeks ? ` · ${b.missing_weeks} semaine sans fichier dans le bloc` : "";
  const html = `<section class="band band--frise" aria-labelledby="frise-title"><h2 id="frise-title">Frise du bloc</h2>
    <p class="legend">${keys.join("")}<span class="legend__item"><span class="key key--frise-light"></span>Semaine allégée</span><span class="legend__item"><span class="key key--frise-done"></span>Réalisé</span></p>
    <div class="chart-host chart-host--frise" id="frise-host">${blockFrise(items, "Phases du bloc planifié, une colonne par semaine")}</div>
    <p class="readout" id="frise-readout" aria-live="polite">${F.esc(pos)}${raceTxt ? ` · ${F.esc(raceTxt)}` : ""}${F.esc(unknownTxt)}${F.esc(missingTxt)}</p></section>`;
  const mount = () => {
    const host = $("#frise-host");
    const readout = $("#frise-readout");
    if (!host) return;
    const initial = readout.textContent;
    const show = (ev) => { const a = ev.target.closest && ev.target.closest("a[data-i]"); if (a) readout.textContent = describe(b.weeks[Number(a.dataset.i)]); };
    host.addEventListener("mouseover", show);
    host.addEventListener("focusin", show);
    host.addEventListener("mouseleave", () => { readout.textContent = initial; });
    const target = host.querySelector(".frise-focus.is-selected") || host.querySelector(".frise-focus.is-current");
    if (target) host.scrollLeft = Math.max(0, target.getBoundingClientRect().left - host.getBoundingClientRect().left + host.scrollLeft - host.clientWidth / 2);
  };
  return { html, mount };
}

async function viewWeek(params) {
  const start = params.get("debut");
  const w = await api(start ? `week?start=${start}` : "week");
  const frise = await friseSection(w.week_start);
  const known = w.known_weeks;
  const prev = F.addDays(w.week_start, -7);
  const next = F.addDays(w.week_start, 7);
  const days = [...Array(7)].map((_, i) => F.addDays(w.week_start, i));
  const cols = days.map((d) => {
    const plans = w.sessions.filter((x) => x.date === d);
    const acts = w.activities.filter((x) => x.date === d);
    const wx = w.weather.find((x) => x.date === d);
    return `<li class="day ${d === w.today ? "day--today" : ""}"><div class="day__head"><span class="day__name">${F.weekday(d)}</span><span class="day__date">${F.dayShort(d)}</span>${wx ? weatherChip(wx.category) : ""}</div>
      ${plans.map((x) => `<div class="session"><span class="session__title">${F.esc(x.title)}</span><span class="session__meta">${F.SPORT[x.sport] || x.sport}${x.best_slot && x.best_slot !== "none" ? ` · ${F.SLOT[x.best_slot]}` : ""}</span>${statusChip(x.status)}</div>`).join("")}
      ${acts.map((a) => `<a class="session session--done" href="#/seance/${a.id}"><span class="session__title">${F.esc(a.name || F.SPORT[a.sport])}</span><span class="session__meta">${a.distance_m ? F.distance(a.distance_m) + " · " : ""}${F.duration(a.duration_s)}${a.avg_hr_bpm ? ` · ${F.num(a.avg_hr_bpm)} bpm` : ""}</span></a>`).join("")}
      ${!plans.length && !acts.length ? `<span class="muted">—</span>` : ""}</li>`;
  }).join("");
  const totalS = w.activities.reduce((t, a) => t + (a.duration_s || 0), 0);
  const totalM = w.activities.reduce((t, a) => t + (a.distance_m || 0), 0);
  const target = w.week || {};
  const trail = SUMMARY.settings.sport === "trail";
  main.innerHTML = `${header(`Semaine du ${F.dayShort(w.week_start)}`, w.week ? `${F.esc(w.week.location || "")}${w.week.phase ? " · " + F.esc(w.week.phase) : ""}` : "Pas de plan de semaine au contrat pour ces dates.")}
    <div class="toolbar"><a class="seg" href="#/semaine?debut=${prev}">← Précédente</a><a class="seg" href="#/semaine">Cette semaine</a><a class="seg" href="#/semaine?debut=${next}">Suivante →</a>
      ${known.length ? `<label class="select">Plans : <select id="weeks">${known.slice().reverse().map((k) => `<option value="${k}" ${k === w.week_start ? "selected" : ""}>${F.dayShort(k)}</option>`).join("")}</select></label>` : ""}</div>
    ${frise.html}
    <ol class="week">${cols}</ol>
    <section class="band"><h2>Réalisé</h2><dl class="facts facts--inline"><div><dt>Séances</dt><dd>${w.activities.length}</dd></div><div><dt>Durée</dt><dd>${F.hours(totalS)}${target.target_duration_s ? ` <small>/ ${F.hours(target.target_duration_s)}</small>` : ""}</dd></div><div><dt>Distance</dt><dd>${F.distance(totalM)}${target.target_distance_m ? ` <small>/ ${F.distance(target.target_distance_m, 0)}</small>` : ""}</dd></div></dl></section>
    ${complianceSection(w.compliance, trail)}
    ${w.body_html ? `<section class="band prose"><h2>Plan du coach</h2>${w.body_html}</section>` : ""}`;
  frise.mount();
  const sel = $("#weeks");
  if (sel) sel.addEventListener("change", () => { location.hash = `#/semaine?debut=${sel.value}`; });
}

// ---------------------------------------------------------------------------
// Vues : Séances, détail
// ---------------------------------------------------------------------------

// Séances : l'historique entier dépasse vite les 500 lignes. La vue garde TOUT
// en mémoire (une seule requête, déjà en cache), puis recherche, filtre, trie et
// pagine côté navigateur — l'état vit dans l'URL (`history.replaceState`, jamais
// `location.hash` : un `hashchange` relancerait la vue et volerait le focus du
// champ de recherche à chaque frappe). Trié par date, le tableau se découpe par
// mois, avec les totaux du mois sur TOUT le filtre (pas seulement la page).
const SESSIONS_PAGE_SIZE = 50;
const MONTH_LONG = new Intl.DateTimeFormat("fr-FR", { month: "long", year: "numeric" });
const SESSION_SORT = {
  date: (a) => a.date, distance: (a) => a.distance_m || 0, duree: (a) => a.duration_s || 0,
  dplus: (a) => a.elevation_gain_m || 0, fc: (a) => a.avg_hr_bpm || 0, charge: (a) => a.load || 0,
};

function sessionTotals(rows) {
  let distance = 0, duration = 0, gain = 0;
  for (const a of rows) { distance += a.distance_m || 0; duration += a.duration_s || 0; gain += a.elevation_gain_m || 0; }
  return { n: rows.length, distance, duration, gain };
}

function sessionRow(a, trail) {
  return `<tr><td class="nowrap">${F.dayShort(a.date)} <span class="muted year">${a.date.slice(0, 4)}</span></td><td class="session-name"><a href="#/seance/${a.id}">${F.esc(a.name || F.SPORT[a.sport] || a.sport)}</a> <span class="muted">${F.SPORT[a.sport] || a.sport}</span>${a.arc_version === 0 ? ` <span class="tag" title="Fichier hors contrat : lecture approximative">approx.</span>` : ""}</td>
      <td class="num">${F.distance(a.distance_m)}</td><td class="num col-opt">${F.duration(a.duration_s)}</td><td class="num">${trail ? F.elevation(a.elevation_gain_m) : F.pace(a.distance_m, a.duration_s)}</td>
      <td class="num col-opt">${F.num(a.avg_hr_bpm)}</td><td class="num col-opt">${a.recovery_hr_bpm != null ? F.num(a.recovery_hr_bpm) : `<span class="muted" title="non mesuré">—</span>`}</td><td class="num col-opt">${F.num(a.load)}${a.load_source === "estimated" ? `<span class="muted" title="Charge estimée : ni FC ni effort perçu">*</span>` : ""}</td></tr>`;
}

async function viewSessions(params) {
  const { activities } = await api("activities?limit=10000");
  const trail = SUMMARY.settings.sport === "trail";
  const sports = [...new Set(activities.map((a) => a.sport))].sort((a, b) => (F.SPORT[a] || a).localeCompare(F.SPORT[b] || b, "fr"));
  const years = [...new Set(activities.map((a) => a.date.slice(0, 4)))].sort().reverse();
  const st = {
    q: params.get("q") || "", sport: params.get("sport") || "", year: params.get("annee") || "",
    sort: SESSION_SORT[params.get("tri")] ? params.get("tri") : "date",
    dir: params.get("sens") === "asc" ? 1 : -1, page: Number(params.get("page")) || 1,
  };
  if (!activities.length) {
    main.innerHTML = `${header("Séances")}${empty("Aucune séance", "Les fichiers <code>activities/AAAA-MM-JJ_&lt;sport&gt;.md</code> apparaissent ici une fois indexés.")}`;
    return;
  }
  const total = sessionTotals(activities);
  main.innerHTML = `${header("Séances", `${F.num(total.n)} séances indexées, depuis le ${F.dateLong(activities[activities.length - 1].date)}.`)}
    <div class="toolbar toolbar--list">
      ${searchField("s-q", st.q, "Nom ou lieu de la séance", "Rechercher une séance")}
      <label class="select">Sport <select id="s-sport"><option value="">Tous</option>${sports.map((s) => `<option value="${s}" ${s === st.sport ? "selected" : ""}>${F.SPORT[s] || s}</option>`).join("")}</select></label>
      <label class="select select--tight">Année <select id="s-year"><option value="">Toutes</option>${years.map((y) => `<option ${y === st.year ? "selected" : ""}>${y}</option>`).join("")}</select></label>
    </div>
    <div id="s-results" class="results"></div>`;

  const results = $("#s-results");
  const sync = () => {
    const qs = new URLSearchParams();
    if (st.q) qs.set("q", st.q);
    if (st.sport) qs.set("sport", st.sport);
    if (st.year) qs.set("annee", st.year);
    if (st.sort !== "date") qs.set("tri", st.sort);
    if (st.dir === 1) qs.set("sens", "asc");
    if (st.page > 1) qs.set("page", String(st.page));
    const q = qs.toString();
    history.replaceState(null, "", `#/seances${q ? `?${q}` : ""}`);
  };
  const render = () => {
    const needle = fold(st.q.trim());
    let rows = activities.filter((a) => (!st.sport || a.sport === st.sport) && (!st.year || a.date.startsWith(st.year))
      && (!needle || fold(`${a.name || ""} ${a.location || ""} ${F.SPORT[a.sport] || a.sport}`).includes(needle)));
    const key = SESSION_SORT[st.sort];
    rows = rows.slice().sort((a, b) => ((key(a) > key(b) ? 1 : key(a) < key(b) ? -1 : 0) || (a.id - b.id)) * st.dir);
    const pg = paginate(rows, st.page, SESSIONS_PAGE_SIZE);
    st.page = pg.page;
    sync();
    if (!rows.length) {
      results.innerHTML = empty("Aucune séance ne correspond", "Élargissez la recherche, ou choisissez « Tous » / « Toutes » dans les filtres.");
      return;
    }
    const sum = sessionTotals(rows);
    const filtered = rows.length !== activities.length;
    const head = `<thead><tr>${sortTh("date", "Date", st, false)}<th scope="col">Séance</th>${sortTh("distance", "Distance", st)}${sortTh("duree", "Durée", st, true, "col-opt")}${trail ? sortTh("dplus", "D+", st) : `<th scope="col" class="num">Allure</th>`}${sortTh("fc", "FC moy", st, true, "col-opt")}<th scope="col" class="num col-opt">HRR</th>${sortTh("charge", "Charge", st, true, "col-opt")}</tr></thead>`;
    let bodies;
    if (st.sort === "date") {
      // Groupes par mois ; totaux calculés sur toutes les lignes filtrées du mois.
      const byMonth = new Map();
      for (const a of rows) {
        const m = a.date.slice(0, 7);
        if (!byMonth.has(m)) byMonth.set(m, []);
        byMonth.get(m).push(a);
      }
      const groups = [];
      for (const a of pg.slice) {
        const m = a.date.slice(0, 7);
        if (!groups.length || groups[groups.length - 1].m !== m) groups.push({ m, rows: [] });
        groups[groups.length - 1].rows.push(a);
      }
      bodies = groups.map((g, i) => {
        const t = sessionTotals(byMonth.get(g.m));
        const cont = i === 0 && pg.page > 1 && pg.slice[0] !== byMonth.get(g.m)[0];
        return `<tbody><tr class="month"><th scope="rowgroup" colspan="8"><span class="month__name">${MONTH_LONG.format(F.parseDate(`${g.m}-01`))}${cont ? ` <span class="muted">(suite)</span>` : ""}</span>
          <span class="month__totals">${F.num(t.n)} séance${t.n > 1 ? "s" : ""} · ${F.distance(t.distance, 0)} · ${F.hours(t.duration)}${trail ? ` · ${F.elevation(t.gain)} D+` : ""}</span></th></tr>
          ${g.rows.map((a) => sessionRow(a, trail)).join("")}</tbody>`;
      }).join("");
    } else {
      bodies = `<tbody>${pg.slice.map((a) => sessionRow(a, trail)).join("")}</tbody>`;
    }
    results.innerHTML = `<p class="results__sum" aria-live="polite"><strong>${F.num(sum.n)} séance${sum.n > 1 ? "s" : ""}</strong>${filtered ? ` sur ${F.num(activities.length)}` : ""} · ${F.distance(sum.distance, 0)} · ${F.hours(sum.duration)}${trail ? ` · ${F.elevation(sum.gain)} D+` : ""}</p>
      <div class="table-wrap"><table class="data data--sessions">${head}${bodies}</table></div>
      ${pagerHtml(pg, rows.length, "Pages de séances")}`;
  };
  const go = (patch, { resetPage = true, scroll = false } = {}) => {
    Object.assign(st, patch);
    if (resetPage && !("page" in patch)) st.page = 1;
    render();
    if (scroll) results.scrollIntoView({ block: "start" });
  };
  render();
  $("#s-q").addEventListener("input", debounce((e) => go({ q: e.target.value })));
  $("#s-sport").addEventListener("change", (e) => go({ sport: e.target.value }));
  $("#s-year").addEventListener("change", (e) => go({ year: e.target.value }));
  results.addEventListener("click", (e) => {
    const sortBtn = e.target.closest("[data-sort]");
    if (sortBtn) {
      const k = sortBtn.dataset.sort;
      go({ sort: k, dir: st.sort === k ? -st.dir : -1 });
      results.querySelector(`[data-sort="${k}"]`)?.focus();
      return;
    }
    const pageBtn = e.target.closest("[data-page]");
    if (pageBtn && !pageBtn.disabled) {
      go({ page: Number(pageBtn.dataset.page) }, { scroll: true });
      results.querySelector(".pager [aria-current]")?.focus({ preventScroll: true });
    }
  });
}

async function viewSession(id) {
  // Trace (carte + profil) chargée en parallèle : une erreur sur elle ne doit jamais
  // empêcher la page de s'afficher — la séance reste lisible sans carte.
  const [d, tr] = await Promise.all([api(`activity/${id}`), api(`activity/${id}/track`).catch(() => null)]);
  const a = d.activity;
  const trail = SUMMARY.settings.sport === "trail";
  const missing = a.missing_reason || {};
  const moving = a.moving_duration_s || a.duration_s;
  const profile = tr && tr.points > 1 ? resampleByDistance(tr) : null;
  const hasMap = !!(tr && tr.has_gps && profile);

  // Grand livre de la séance : trois groupes courts plutôt qu'une grille de quinze cases
  // égales — l'effort d'abord, le cœur ensuite, le contexte enfin.
  const effort = [
    ...(a.distance_m ? [["Distance", F.distance(a.distance_m, 2)]] : []),
    ["Durée", `${F.duration(moving, { seconds: true })}${a.moving_duration_s && a.duration_s && a.duration_s - a.moving_duration_s >= 60 ? `<small class="muted"> en mouvement · ${F.duration(a.duration_s)} au total</small>` : ""}`],
    ...(a.distance_m ? [["Allure", F.pace(a.distance_m, moving)]] : []),
    // GAP (#44) : uniquement pour la famille course à pied avec échantillons FIT
    // ingérés (arc_gap.ASSUMPTIONS) — absent (jamais une ligne à "—") sinon, pour
    // ne pas laisser croire qu'une valeur a été calculée et vaut zéro/inconnue.
    ...(a.gap_pace_s_km != null ? [["GAP <small class=\"muted\">allure ajustée à la pente</small>", F.paceFromSecPerKm(a.gap_pace_s_km)]] : []),
    ...((trail && a.distance_m) || a.elevation_gain_m ? [["D+ / D-", a.elevation_gain_m != null ? `${F.elevation(a.elevation_gain_m)} / ${F.elevation(a.elevation_loss_m)}` : (missing.elevation_gain_m ? "non mesuré" : "—")]] : []),
    ["Charge", `${F.num(a.load)} <small class="muted">${a.load_source === "trimp" ? "TRIMP" : a.load_source === "srpe" ? "effort perçu" : "estimée"}</small>`],
    ["Effet d'entraînement", a.te_aerobic != null ? `${F.num(a.te_aerobic, 1)}${a.te_anaerobic != null ? `<small class="muted"> · ${F.num(a.te_anaerobic, 1)} anaérobie</small>` : ""}` : "—"],
  ];
  const heart = [
    ["FC moy / max", a.avg_hr_bpm ? `${F.num(a.avg_hr_bpm)} / ${F.num(a.max_hr_bpm)} bpm` : (missing.avg_hr_bpm ? "non mesurée" : "—")],
    ["HRR", a.recovery_hr_bpm != null ? `${F.num(a.recovery_hr_bpm)} bpm` : `<span class="muted">non mesuré${missing.recovery_hr_bpm ? ` — ${F.esc(missing.recovery_hr_bpm)}` : ""}</span>`],
    // Découplage aérobie / Pa:HR (#45) : uniquement si calculable (séance de course
    // à pied, ≥ 60 min de mouvement, effort jugé stable — arc_decoupling.ASSUMPTIONS)
    // — jamais une ligne à "—", qui laisserait croire à une valeur nulle mesurée.
    // Couleur seulement dans les deux sens univoques (revue de code #45) : 0-5 %
    // (dérive attendue) en positif, au-delà en négatif — une valeur négative reste neutre.
    ...(a.decoupling_pct != null ? [["Découplage (Pa:HR)",
      `<span class="${a.decoupling_pct >= 0 && a.decoupling_pct <= 5 ? "pos" : a.decoupling_pct > 5 ? "neg" : ""}">${a.decoupling_pct > 0 ? "+" : ""}${F.num(a.decoupling_pct, 1)} %</span>${a.ef_whole != null ? `<small class="muted"> · EF ${F.num(a.ef_whole, 2)}</small>` : ""}`]] : []),
    // Durabilité (#48) : fade GAP entre le premier et le dernier tiers — jamais une
    // ligne à "—" ; un fade positif (ralentissement) en négatif visuel, sinon neutre.
    ...(a.durability_gap_fade_pct != null ? [["Durabilité <small class=\"muted\">fade GAP dernier tiers</small>",
      `<span class="${a.durability_gap_fade_pct > 0 ? "neg" : ""}">${a.durability_gap_fade_pct > 0 ? "+" : ""}${F.num(a.durability_gap_fade_pct, 1)} %</span>${a.durability_ef_fade_pct != null ? `<small class="muted"> · EF ${a.durability_ef_fade_pct > 0 ? "+" : ""}${F.num(a.durability_ef_fade_pct, 1)} %</small>` : ""}`]] : []),
    ...(a.avg_cadence_spm ? [["Cadence", `${F.num(a.avg_cadence_spm)} pas/min`]] : []),
    ...(a.vo2max_est ? [["VO2max estimée", F.num(a.vo2max_est, 1)]] : []),
  ];
  const wx = d.weather;
  const context = [
    // Matériel (#147) : chaussure attribuée par la règle unique (`arc_metrics.attribute_gear`, côté
    // serveur) et objets portés (`gear_ids`) — chaque nom renvoie vers sa fiche ; rien si absent.
    ...(d.gear?.shoe ? [["Chaussure", `${gearLink(d.gear.shoe.gear_id, d.gear.shoe.name)}${d.gear.shoe.source === "default" ? ` <small class="muted">paire par défaut</small>` : ""}`]] : []),
    ...(d.gear?.equipment?.length ? [["Équipement porté", d.gear.equipment.map((g) => gearLink(g.gear_id, g.name)).join(", ")]] : []),
    ...(wx ? [["Météo", `${weatherChip(wx.category)} <small class="muted">${F.esc(wx.location)} · ${F.num(wx.temp_min_c)}–${F.num(wx.temp_max_c)} °C · vent ${F.num(wx.wind_kmh)} km/h</small>`]] : []),
  ];
  const group = (title, rows) => (rows.length ? `<section class="ledger__group"><h2>${title}</h2><dl class="ledger__rows">${rows.map(([k, v]) => `<div><dt>${k}</dt><dd>${v}</dd></div>`).join("")}</dl></section>` : "");

  const modes = profile ? colorModes(profile, d.hr_zones?.bounds_bpm) : {};
  const modeOrder = ["pace", "gap", "hr", "grade", "plain"].filter((k) => modes[k]);
  const firstMode = modeOrder[0];
  const mapHtml = hasMap ? `<figure class="session-map">
      <div class="map" id="s-map" role="region" aria-label="Carte de la séance : trace GPS"></div>
      <figcaption class="map-bar">
        <div class="toolbar" role="group" aria-label="Couleur de la trace">${modeOrder.map((k) => `<button type="button" class="seg${k === firstMode ? " is-on" : ""}" aria-pressed="${k === firstMode}" data-mode="${k}">${modes[k].label}</button>`).join("")}
          <button type="button" class="seg seg--ghost" id="s-map-fit">Recentrer</button></div>
        <p class="map-legend" id="s-map-legend"></p>
      </figcaption></figure>` : "";
  // Une séance de course sans FIT, ou un FIT sans GPS : on le dit une fois, sous le grand livre.
  const runFamily = ["running", "trail"].includes(a.sport);
  const outdoor = runFamily || ["hiking", "walking", "cycling"].includes(a.sport);
  const mapNote = hasMap || !outdoor ? "" : tr?.reason_code === "no_gps"
    ? note("Pas de carte : le fichier FIT de cette séance ne contient aucune position GPS (tapis, intérieur ou GPS coupé).")
    : (runFamily && tr?.reason_code === "no_samples" ? note("Pas de carte : aucun échantillon FIT ingéré pour cette séance (skill <code>fit-download</code>).") : "");

  let splitsHtml = "";
  let splitsMount = () => {};
  if (d.splits.length) {
    const all = d.splits;
    // Tours Garmin : souvent 1 km, mais un pas de séance structurée ou le reliquat
    // final peut faire 500 m ou 20 m. On trace l'allure (temps ramené au km),
    // et un tour de moins de 200 m n'entre pas dans le graphique.
    const lapKm = (x) => (x.distance_m != null ? x.distance_m / 1000 : 1);
    const byKm = all.every((x) => x.distance_m == null || Math.abs(x.distance_m - 1000) <= 50);
    const sp = all.filter((x) => x.duration_s && (x.distance_m == null || x.distance_m >= 200));
    const unit = byKm ? "Km" : "Tour";
    const labels = sp.map((x) => String(x.km));
    // GAP par split (#44) : rendu SEULEMENT s'il y a au moins une valeur — une
    // séance sans échantillons FIT (ou hors famille course à pied,
    // `arc_gap.ASSUMPTIONS`) n'a aucun `gap_pace_s_km`, jamais une ligne plate à 0.
    const hasGap = sp.some((x) => x.gap_pace_s_km != null);
    const c = timeChart(labels, [
      { type: "bars", values: sp.map((x) => x.duration_s / lapKm(x) / 60), cls: "bar" },
      ...(hasGap ? [{ type: "line", values: sp.map((x) => (x.gap_pace_s_km != null ? x.gap_pace_s_km / 60 : null)), cls: "line line--gap" }] : []),
      { type: "line", values: sp.map((x) => x.avg_hr_bpm), cls: "line line--rhr", axis: "y2" },
      { type: "dots", values: sp.map((x) => x.avg_hr_bpm), cls: "dot dot--rhr", axis: "y2" },
    ], [], { height: 200, y: { zero: true }, y2: {}, xLabels: labels, label: byKm ? "Temps, GAP et FC par kilomètre" : "Allure, GAP et FC par tour", yFormat: (v) => `${F.num(v)}′`, y2Format: (v) => F.num(v) });
    const hidden = all.length - sp.length;
    const lapPace = (x) => (x.distance_m ? F.pace(x.distance_m, x.duration_s) : "—");
    splitsHtml = `<section class="band"><h2>Splits</h2><p class="legend"><span class="legend__item"><span class="key key--bar"></span>${byKm ? "Temps au km" : "Allure (min/km)"}</span> ${hasGap ? `<span class="legend__item"><span class="key key--gap"></span>GAP (allure ajustée à la pente)</span> ` : ""}<span class="legend__item"><span class="key key--rhr"></span>FC moyenne</span></p>
      <div class="chart-host chart-host--nox" id="c-splits">${c.svg}</div><p class="readout" id="r-splits"></p>
      ${hidden ? `<p class="muted"><small>${hidden === 1 ? "Un tour de moins de 200 m n'est pas tracé" : `${hidden} tours de moins de 200 m ne sont pas tracés`} ; il${hidden === 1 ? " reste" : "s restent"} dans le tableau.</small></p>` : ""}
      ${all.length > 20 ? `<details class="fold"><summary>Les ${all.length} ${byKm ? "kilomètres" : "tours"} en détail</summary>` : ""}<div class="table-wrap"><table class="data data--compact"><thead><tr><th scope="col">${unit}</th>${byKm ? "" : `<th scope="col" class="num">Distance</th>`}<th scope="col" class="num">Temps</th>${byKm ? "" : `<th scope="col" class="num">Allure</th>`}${hasGap ? `<th scope="col" class="num">GAP</th>` : ""}<th scope="col" class="num">D+ / D-</th><th scope="col" class="num">FC</th><th scope="col" class="num">Cadence</th><th scope="col">Lecture</th></tr></thead>
      <tbody>${all.map((x) => `<tr><td>${x.km}</td>${byKm ? "" : `<td class="num">${x.distance_m != null ? F.distance(x.distance_m, 2) : "—"}</td>`}<td class="num">${F.clockShort(x.duration_s)}</td>${byKm ? "" : `<td class="num">${lapPace(x)}</td>`}${hasGap ? `<td class="num">${F.paceFromSecPerKm(x.gap_pace_s_km)}</td>` : ""}<td class="num">${x.elev_gain_m != null ? `+${F.num(x.elev_gain_m)} / -${F.num(x.elev_loss_m)}` : "—"}</td><td class="num">${F.num(x.avg_hr_bpm)}</td><td class="num">${F.num(x.cadence_spm)}</td><td>${F.esc(x.label || "")}</td></tr>`).join("")}</tbody></table></div>${all.length > 20 ? "</details>" : ""}</section>`;
    splitsMount = () => attachCursor($("#c-splits"), c, (i) => {
      const x = sp[i];
      const what = byKm ? F.clockShort(x.duration_s) : `${F.distance(x.distance_m, 2)} en ${F.clockShort(x.duration_s)} (${lapPace(x)})`;
      readout($("#r-splits"), `<strong>${unit} ${x.km}</strong> · ${what}${x.gap_pace_s_km != null ? ` · GAP ${F.paceFromSecPerKm(x.gap_pace_s_km)}` : ""} · FC ${F.num(x.avg_hr_bpm)}${x.elev_gain_m != null ? ` · +${F.num(x.elev_gain_m)} m` : ""}${x.label ? ` · ${F.esc(x.label)}` : ""}`);
    });
  }
  // Séance sans FIT (#50, critère d'acceptation) : `climbs.reason_code === "no_samples"`
  // (`arc_serve.py::api_activity_climbs`, même `reason_code` porté par `descent` et
  // implicitement par `hr_zones.zone_seconds`, les trois dérivés de la MÊME table
  // `activity_sample` pour la même activité) signale l'absence totale d'échantillons
  // FIT ingérés pour une séance de la famille course à pied — jamais un simple test
  // sur le texte français de `reason`. Une seule note consolidée remplace les trois
  // sections vides (critère d'acceptation : « séance sans FIT : sections masquées proprement »).
  const noFitSamples = !!(d.climbs && d.climbs.applicable !== false && d.climbs.reason_code === "no_samples");
  const climbs = (d.climbs && d.climbs.climbs) || [];
  const prof = profile ? profileSection(profile, climbs, trail || a.elevation_gain_m) : null;
  const sub = `${F.dayLong(a.date)} · ${F.SPORT[a.sport] || a.sport}${a.location ? " · " + F.esc(a.location) : ""} · <a href="#/seances">Toutes les séances</a>`;

  main.innerHTML = `${header(a.name || F.SPORT[a.sport] || "Séance", sub)}
    <div class="session-hero${hasMap ? "" : " session-hero--nomap"}">
      ${mapHtml}
      <div class="ledger">${group("Effort", effort)}${group("Cœur", heart)}${group("Contexte", context)}</div>
    </div>
    ${mapNote}
    ${prof ? prof.html : ""}
    ${loggedSection(a, d.pain)}
    ${noFitSamples ? noFitSamplesNote(d.hr_zones) : hrZoneSection(d.hr_zones)}
    ${splitsHtml}
    ${noFitSamples ? "" : climbsSection(d.climbs, { onMap: hasMap })}
    ${noFitSamples ? "" : descentSection(d.descent)}
    ${sessionGaitSection(d.gait)}
    ${energySection(d.energy, noFitSamples)}
    <section class="band prose"><h2>Analyse du coach</h2>${d.body_html || "<p class=\"muted\">Pas de texte.</p>"}<p class="muted source">Source : <code>${F.esc(a.source_path)}</code></p></section>`;

  splitsMount();
  let mapCtl = null;
  const moveProfile = prof ? prof.mount((j) => mapCtl?.showIndex(j)) : () => {};
  if (!hasMap) return;
  const legend = $("#s-map-legend");
  const showLegend = (key) => {
    const m = modes[key];
    legend.innerHTML = m.legend
      ? `${m.legend.map((l, b) => `<span class="map-legend__step"><span class="key key--trk${b}"></span>${F.esc(l)}</span>`).join("")}${m.legendNote ? `<span class="muted">${F.esc(m.legendNote)}</span>` : ""}`
      : `<span class="muted">Survolez la trace ou le profil pour suivre la séance.</span>`;
  };
  try {
    mapCtl = await sessionMap($("#s-map"), tr, profile, {
      tiles: SUMMARY.settings.map_tiles, attribution: SUMMARY.settings.map_attribution, climbs,
      onHover: (j) => { moveProfile(j); mapCtl?.showIndex(j); },
    });
  } catch (err) {
    $(".session-map").outerHTML = note(`Carte indisponible : ${F.esc(err.message)}.`);
    return;
  }
  mapCtl.setMode(modes[firstMode]);
  showLegend(firstMode);
  for (const btn of document.querySelectorAll(".map-bar [data-mode]")) {
    btn.addEventListener("click", () => {
      for (const b of document.querySelectorAll(".map-bar [data-mode]")) {
        b.classList.toggle("is-on", b === btn);
        b.setAttribute("aria-pressed", String(b === btn));
      }
      mapCtl.setMode(modes[btn.dataset.mode]);
      showLegend(btn.dataset.mode);
    });
  }
  $("#s-map-fit").addEventListener("click", () => mapCtl.reset());
  for (const btn of document.querySelectorAll("[data-climb-km]")) {
    btn.addEventListener("click", () => {
      const [k0, k1] = btn.dataset.climbKm.split(",").map(Number);
      mapCtl.focusRange(k0 * 1000, k1 * 1000);
      $(".session-map").scrollIntoView({ behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth", block: "nearest" });
    });
  }
}

/** Profil de la séance, à pas de distance : altitude (montées détectées ombrées), puis FC,
 * allure et cadence sur le même axe. Un curseur commun lie les graphiques entre eux et à
 * la carte. `{html, mount(onIndex) → move(j)}`. */
function profileSection(p, climbs, showElevation) {
  const has = (arr) => arr.some((v) => v != null);
  const total = p.d[p.n - 1] - p.d[0];
  const kmStep = [1, 2, 5, 10, 20, 50].find((s) => total / 1000 / s <= 10) || 100;
  const labels = p.d.map((d, j) => {
    const km = (d - p.d[0]) / 1000;
    const prev = j ? (p.d[j - 1] - p.d[0]) / 1000 : -1;
    return Math.floor(km / kmStep) !== Math.floor(prev / kmStep) ? `${F.num(Math.floor(km / kmStep) * kmStep)} km` : "";
  });
  const inClimb = (j) => climbs.some((c) => p.d[j] >= c.start_km * 1000 && p.d[j] <= c.end_km * 1000);
  // Axe robuste (5e-95e centile, marge 15 %) : un arrêt au ravitaillement ne doit pas écraser
  // toute la courbe ; les valeurs hors de l'axe y sont ramenées à son bord.
  // `extra` : courbe superposée sur le même axe (GAP sur l'allure), prise en compte dans les bornes.
  const robust = (arr, extra = []) => {
    const v = arr.concat(extra).filter((x) => x != null).sort((a, b) => a - b);
    const lo = v[Math.floor(v.length * 0.05)], hi = v[Math.floor(v.length * 0.95)];
    const m = (hi - lo) * 0.15 || 1;
    const y = { min: lo - m, max: hi + m };
    const clamp = (a) => a.map((x) => (x == null ? null : Math.min(y.max, Math.max(y.min, x))));
    return { y, values: clamp(arr), extra: clamp(extra) };
  };
  const perMin = (arr) => arr.map((v) => (v == null ? null : v / 60));
  // GAP (allure ajustée à la pente) en pointillés sur le graphique d'allure, même axe, même
  // style que dans les splits ; absente hors course à pied (pas de facteur `gf`).
  const hasGap = has(p.gap);
  const paceR = has(p.pace) ? robust(perMin(p.pace), hasGap ? perMin(p.gap) : []) : null;
  const cadR = has(p.cad) ? robust(p.cad) : null;
  const paceFmt = (v) => `${Math.floor(v)}:${String(Math.round((v % 1) * 60) % 60).padStart(2, "0")}`;
  const specs = [
    showElevation && has(p.alt) && { id: "alt", title: "Altitude", height: 170, label: "Altitude le long de la séance", yFormat: (v) => F.num(v),
      layers: [{ type: "area", values: p.alt, cls: "area area--elev", base: -1e9 },
        ...(climbs.length ? [{ type: "area", values: p.alt.map((v, j) => (inClimb(j) ? v : null)), cls: "area area--climb", base: -1e9 }] : []),
        { type: "line", values: p.alt, cls: "line line--elev" }] },
    has(p.hr) && { id: "hr", title: "FC", height: 110, label: "Fréquence cardiaque le long de la séance", yFormat: (v) => F.num(v),
      layers: [{ type: "line", values: p.hr, cls: "line line--rhr" }] },
    paceR && { id: "pace", title: hasGap ? "Allure · GAP" : "Allure", height: 110, y: { ...paceR.y, invert: true },
      label: hasGap ? "Allure et allure ajustée à la pente le long de la séance, plus rapide en haut" : "Allure le long de la séance, plus rapide en haut", yFormat: paceFmt,
      layers: [{ type: "line", values: paceR.values, cls: "line line--pace" },
        ...(hasGap ? [{ type: "line", values: paceR.extra, cls: "line line--gap" }] : [])] },
    cadR && { id: "cad", title: "Cadence", height: 100, y: cadR.y, label: "Cadence le long de la séance", yFormat: (v) => F.num(v),
      layers: [{ type: "line", values: cadR.values, cls: "line line--cad" }] },
  ].filter(Boolean);
  if (!specs.length) return null;
  const xs = p.d.map(String);   // `timeChart` attend des chaînes (dates) ; l'échelle reste le rang
  // Graduations kilométriques sous le dernier graphique seulement : un seul axe pour toute la pile.
  const rows = specs.map((sp, k) => {
    const last = k === specs.length - 1;
    // Les bandes fines (FC, allure, cadence) n'ont que deux graduations : lisibles sur téléphone.
    const y = sp.id === "alt" ? sp.y : { ...(sp.y || {}), ticks: 2 };
    return { ...sp, c: timeChart(xs, sp.layers, [], { height: sp.height + (last ? 20 : 0), y, xLabels: last ? labels : labels.map(() => ""), label: sp.label, yFormat: sp.yFormat }) };
  });
  const climbKey = climbs.length && rows[0].id === "alt" ? `<span class="legend__item"><span class="key key--climb"></span>Montées détectées</span>` : "";
  const gapKey = hasGap && paceR ? `<span class="legend__item"><span class="key key--pace"></span>Allure</span> <span class="legend__item"><span class="key key--gap"></span>GAP (allure ajustée à la pente)</span>` : "";
  const keys = [climbKey, gapKey].filter(Boolean).join(" ");
  const html = `<section class="band profile"><h2>Profil</h2>
    ${keys ? `<p class="legend">${keys}</p>` : ""}
    <div class="profile__stack">${rows.map((r) => `<div class="profile__row"><span class="profile__label" aria-hidden="true">${r.title}</span><div class="chart-host chart-host--nox" id="c-prof-${r.id}">${r.c.svg}</div></div>`).join("")}</div>
    <p class="readout readout--sticky" id="r-prof" aria-live="polite"></p></section>`;
  const show = (j) => {
    const km = (p.d[j] - p.d[0]) / 1000;
    const g = p.grade[j];
    readout($("#r-prof"), `<strong>${F.distance(km * 1000, 2)}</strong>`
      + (p.alt[j] != null ? ` · ${F.elevation(p.alt[j])}` : "")
      + (g != null ? ` · pente ${g > 0 ? "+" : ""}${F.num(g * 100, 0)}${NB}%` : "")
      + (p.hr[j] != null ? ` · ${F.num(p.hr[j])}${NB}bpm` : "")
      + (p.pace[j] != null ? ` · ${F.paceFromSecPerKm(p.pace[j])}` : "")
      + (p.gap[j] != null ? ` · GAP ${F.paceFromSecPerKm(p.gap[j])}` : "")
      + (p.cad[j] != null ? ` · ${F.num(p.cad[j])}${NB}pas/min` : "")
      + (p.t[j] != null ? ` <span class="muted">· ${F.clockShort(p.t[j] - (p.t[0] || 0))}</span>` : ""));
  };
  return {
    html,
    mount(onIndex) {
      const moves = [];
      const all = (j) => { for (const m of moves) m(j); show(j); };
      for (const r of rows) {
        moves.push(attachCursor($(`#c-prof-${r.id}`), r.c, (j) => { all(j); onIndex(j); }, null));
      }
      show(0);
      return all;
    },
  };
}

/** « Ressenti & ravitaillement » : ce que l'athlète a déclaré (souvent par `/log`, #67) —
 * effort perçu, glucides, boisson, pesées, douleurs du jour. Rien de déclaré : rien d'affiché. */
function loggedSection(a, pain) {
  const sweat = a.sweat_rate_l_h;
  const hours = (a.moving_duration_s || a.duration_s || 0) / 3600;
  const perHour = (v, unit) => (hours >= 0.5 ? `<small class="muted"> · ${F.num(v / hours, 0)}${NB}${unit}/h</small>` : "");
  const rows = [
    ...(a.rpe != null ? [["Effort perçu (RPE)", `${F.num(a.rpe, 0)}<small class="muted">${NB}/${NB}10</small>`]] : []),
    ...(a.carbs_g != null ? [["Glucides", `${F.num(a.carbs_g, 0)}${NB}g${perHour(a.carbs_g, "g")}`]] : []),
    ...(a.fluid_intake_ml != null ? [["Boisson", `${F.num(a.fluid_intake_ml, 0)}${NB}ml${perHour(a.fluid_intake_ml, "ml")}`]] : []),
    ...(a.weight_pre_kg != null && a.weight_post_kg != null ? [["Pesée avant → après", `${F.weight(a.weight_pre_kg)} → ${F.weight(a.weight_post_kg)} <small class="muted">(${a.weight_post_kg - a.weight_pre_kg > 0 ? "+" : ""}${F.weight(a.weight_post_kg - a.weight_pre_kg)})</small>`]] : []),
    ...(sweat != null ? [["Taux de sudation", `${F.num(sweat, 2)}${NB}L/h`]] : []),
    ...((pain || []).map((x) => [`Douleur · ${F.esc(x.location)}`, `<span class="${Number(x.score) >= 7 ? "neg" : ""}">${F.esc(String(x.score))}<small class="muted">${NB}/${NB}10</small></span>`])),
  ];
  if (!rows.length) return "";
  const hurt = (pain || []).some((x) => Number(x.score) >= 7);
  return `<section class="band"><h2>Ressenti & ravitaillement</h2>
    <dl class="facts">${rows.map(([k, v]) => `<div><dt>${k}</dt><dd>${v}</dd></div>`).join("")}</dl>
    ${pain?.length ? `<p class="note">Douleurs déclarées ce jour-là (fichier santé).${hurt ? " Une douleur à 7/10 ou plus justifie l'avis d'un professionnel de santé." : ""}</p>` : ""}</section>`;
}

/** Foulée de CETTE séance (#151) : moyennes de la dynamique de course mesurée par la montre,
 * même lecture que la carte « Foulée » de la vue Santé (tendances) — jamais un diagnostic. */
function sessionGaitSection(g) {
  if (!g?.values) return "";
  const rows = GAIT_ROWS.filter(([k]) => g.values[k]).map(([k, label, fmt]) => {
    const v = g.values[k];
    const extra = k === "stance_balance_pct" ? ` <small class="muted">écart ${F.num(Math.abs(v.value - 50), 1)}${NB}pt</small>` : "";
    return `<div><dt>${F.esc(label)}</dt><dd>${fmt(v.value)}${extra}${v.source === "arc" ? ` <span class="tag" title="Valeur du fichier de la séance, sans échantillons FIT">déclarée</span>` : ""}</dd></div>`;
  }).join("");
  return `<section class="band"><h2>Foulée</h2><dl class="facts">${rows}</dl>
    <p class="note">Moyennes de la séance, pondérées par le temps. Le côté que porte la balance (gauche ou droite) n'est pas établi par le format FIT. Tendances : <a href="#/sante?section=foulee">carte « Foulée » de la vue Santé</a>.</p></section>`;
}

/** Section « Montées » de la page séance (#46, VAM) : un tableau, une ligne par
 * montée détectée (D+ minimal et pente minimale — `arc_climb.ASSUMPTIONS`), triée
 * chronologiquement. `climbs` vient de `/api/activity/<id>.climbs` (voir
 * `arc_serve.py::api_activity_climbs`) et porte TOUJOURS une `reason` explicite
 * (même discipline que `hrZoneSection`/#43) quand `climbs.climbs` est vide pour
 * une raison AUTRE qu'un parcours plat : `reason` non nulle distingue « hors de
 * la famille course à pied » (renforcement, vélo — la section est alors masquée,
 * ELLE N'A JAMAIS PU avoir de montée) et « pas d'échantillons FIT ingérés »
 * (l'athlète peut agir : synchroniser le FIT) d'une séance ÉLIGIBLE mais
 * réellement plate (`reason: null`, revue de code #46, should-fix 5 : avant
 * cette distinction, le même message « aucune montée détectée » s'affichait
 * partout, laissant croire à tort qu'une séance de renforcement aurait pu en
 * avoir une). Les deux VAM (temps écoulé/temps de mouvement, voir
 * `arc_climb.ASSUMPTIONS["vam_basis"]") sont toutes deux affichées : la seconde en
 * `<small>`, pour ne pas laisser croire qu'une seule existe.
 *
 * Colonne « vs précédent/meilleur » (#49, identité de montée entre séances) :
 * `segment_id`/`vs_previous_pct`/`vs_best_pct` déjà calculés à l'indexation
 * (`arc_climb_match.py`) — un tiret pour la toute première occurrence d'un
 * segment (rien à comparer, jamais un « 0 % » qui laisserait croire à une
 * progression nulle mesurée), un lien vers l'historique complet
 * (`#/montee/<segment_id>`) sinon. Une montée jamais appariée à AUCUN segment
 * (ne devrait pas arriver, voir `arc_index.compute_metrics`) n'a simplement pas
 * de lien, sans erreur. */
// Même ordre que `arc_climb.GRADE_CLASSES` (Python) — dupliqué ici volontairement
// (pas de dépendance runtime entre le serveur Python et le JS statique) : à tenir
// à jour si `GRADE_CLASSES` change côté serveur.
const GRADE_CLASS_ORDER = ["<5%", "5-10%", "10-15%", "15-20%", ">20%"];

function climbsSection(climbs, { onMap = false } = {}) {
  const rows = (climbs && climbs.climbs) || [];
  const reason = climbs && climbs.reason;
  // `applicable === false` (jamais un test sur le texte français de `reason`,
  // fragile aux reformulations — revue de code #47, nit) : séance qui n'a
  // structurellement jamais pu avoir de montée (renforcement, vélo...), section
  // masquée plutôt qu'un message qui laisserait croire qu'une montée aurait pu y
  // être détectée.
  if (climbs && climbs.applicable === false) {
    return "";
  }
  if (!rows.length) {
    const msg = reason
      ? F.esc(reason).replace(/^./, (c) => c.toUpperCase())
      : "Aucune montée détectée (D+ ou pente sous le seuil de détection : parcours plat).";
    return `<section class="band"><h2>Montées</h2>${note(msg)}</section>`;
  }
  const byClass = (climbs && climbs.vam_by_grade_class) || {};
  // Ordre des classes de pente : celui d'`arc_climb.GRADE_CLASSES` (croissant),
  // JAMAIS un tri alphabétique du texte (qui placerait ">20%" et "<5%" n'importe
  // où — revue de code #46, nit) — une classe absente de `byClass` est simplement
  // ignorée.
  const classLegend = GRADE_CLASS_ORDER.filter((cls) => byClass[cls]).map((cls) =>
    `<span class="legend__item">${F.esc(cls)} : ${F.vam(byClass[cls].avg_vam_elapsed_m_h)} <small class="muted">(${byClass[cls].count})</small></span>`
  ).join(" · ");
  return `<section class="band"><h2>Montées (${rows.length})</h2>
    <div class="table-wrap"><table class="data data--compact"><thead><tr>
      <th scope="col">#</th><th scope="col" class="num">Km</th><th scope="col" class="num">Distance</th>
      <th scope="col" class="num">D+</th><th scope="col" class="num">Pente moy.</th>
      <th scope="col" class="num">Durée</th><th scope="col" class="num">VAM</th>
      <th scope="col" class="num">vs précédent/meilleur</th>${onMap ? `<th scope="col"><span class="visually-hidden">Carte</span></th>` : ""}</tr></thead>
    <tbody>${rows.map((c) => `<tr><td>${c.index}</td><td class="num">${F.distance(c.start_km * 1000, 1)} → ${F.distance(c.end_km * 1000, 1)}</td>
      <td class="num">${F.distance(c.distance_m, 2)}</td><td class="num">+${F.elevation(c.gain_m)}</td>
      <td class="num">${F.num(c.avg_grade * 100, 1)} % <span class="tag">${F.esc(c.grade_class)}</span></td>
      <td class="num">${F.clockShort(c.duration_elapsed_s)}</td>
      <td class="num">${F.vam(c.vam_elapsed_m_h)}<br><small class="muted">mvt ${F.vam(c.vam_moving_m_h)}</small></td>
      <td class="num">${climbProgressionCell(c)}</td>${onMap ? `<td><button type="button" class="link-btn" data-climb-km="${c.start_km},${c.end_km}">Sur la carte</button></td>` : ""}</tr>`).join("")}</tbody></table></div>
    ${classLegend ? `<p class="legend legend--small">VAM moyenne par pente : ${classLegend}</p>` : ""}</section>`;
}

/** Cellule « vs précédent/meilleur » d'une ligne de `climbsSection` (#49) — voir la
 * docstring de `climbsSection` ci-dessus pour la sémantique complète. */
function climbProgressionCell(c) {
  if (c.segment_id == null) return "—";
  const link = `<a href="#/montee/${c.segment_id}">historique</a>`;
  if (c.vs_previous_pct == null) return `<small class="muted">1ʳᵉ fois</small><br>${link}`;
  const fmt = (pct) => `<span class="${pct > 0 ? "pos" : pct < 0 ? "neg" : ""}">${pct > 0 ? "+" : ""}${F.num(pct, 1)} %</span>`;
  return `${fmt(c.vs_previous_pct)} <small class="muted">préc.</small>` +
    (c.vs_best_pct != null && c.vs_best_pct !== c.vs_previous_pct
      ? `<br>${fmt(c.vs_best_pct)} <small class="muted">meill.</small>` : "") +
    `<br>${link}`;
}

/** Page « Historique d'une montée » (#49, `#/montee/<segment_id>`) : chaque
 * occurrence connue du même segment (voir `arc_climb_match.py`), un graphique
 * temps/VAM par date et un tableau détaillé — jamais de coordonnée GPS ici (l'API
 * n'en renvoie aucune, voir `arc_climb_match.ASSUMPTIONS["privacy"]`). Un id
 * périmé (`climb_segment.id` n'est pas stable d'une réindexation à l'autre, voir
 * `arc_index.DDL`) rend une page d'erreur explicite plutôt qu'une page vide
 * muette. */
async function viewClimbSegment(id) {
  const d = await api(`climb-segment/${id}`, { fresh: true });
  if (!d.segment) {
    main.innerHTML = header("Montée introuvable") +
      empty("Cet historique n'existe plus", "L'identifiant de montée n'est pas stable d'une réindexation à l'autre : revenez à la séance pour retrouver le lien à jour.");
    return;
  }
  const seg = d.segment;
  const occ = d.occurrences;
  const dates = occ.map((o) => o.date);
  const chart = timeChart(dates, [
    { type: "dots", values: occ.map((o) => o.vam_elapsed_m_h), cls: "dot dot--vam" },
  ], [], { height: 200, y: { zero: true }, label: "VAM (temps écoulé) par occurrence", yFormat: (v) => F.vam(v) });
  main.innerHTML = `${header(seg.location || "Montée", `${F.distance(seg.distance_m, 2)} · +${F.elevation(seg.gain_m)} · ${F.num(seg.avg_grade * 100, 1)} % (${F.esc(seg.grade_class)}) · ${seg.occurrences} occurrence${seg.occurrences > 1 ? "s" : ""}`)}
    <div class="chart-host" id="c-segment">${chart.svg}</div><p class="readout" id="r-segment"></p>
    <div class="table-wrap"><table class="data data--compact"><thead><tr>
      <th scope="col">Date</th><th scope="col">Séance</th><th scope="col" class="num">Durée</th>
      <th scope="col" class="num">VAM</th><th scope="col" class="num">FC (1ᵉʳ→3ᵉ tiers)</th>
      <th scope="col" class="num">Dérive FC/100 m</th><th scope="col" class="num">vs précédent</th>
      <th scope="col" class="num">vs meilleur</th></tr></thead>
    <tbody>${occ.map((o) => `<tr><td><a href="#/seance/${o.activity_id}">${F.dayLong(o.date)}</a></td>
      <td>${F.esc(o.name || "")}</td><td class="num">${F.clockShort(o.duration_elapsed_s)}</td>
      <td class="num">${F.vam(o.vam_elapsed_m_h)}</td>
      <td class="num">${o.hr_first_third_bpm != null ? `${F.num(o.hr_first_third_bpm)} → ${F.num(o.hr_last_third_bpm)}` : "—"}</td>
      <td class="num">${o.hr_drift_bpm_per_100m != null ? `${o.hr_drift_bpm_per_100m > 0 ? "+" : ""}${F.num(o.hr_drift_bpm_per_100m, 1)}` : "—"}</td>
      <td class="num">${o.vs_previous_pct != null ? `${o.vs_previous_pct > 0 ? "+" : ""}${F.num(o.vs_previous_pct, 1)} %` : "—"}</td>
      <td class="num">${o.vs_best_pct != null ? `${o.vs_best_pct > 0 ? "+" : ""}${F.num(o.vs_best_pct, 1)} %` : "—"}</td></tr>`).join("")}</tbody></table></div>`;
  setTimeout(() => attachCursor($("#c-segment"), chart, (i) => {
    const o = occ[i];
    readout($("#r-segment"), `<strong>${F.dayLong(o.date)}</strong> · VAM ${F.vam(o.vam_elapsed_m_h)}${o.vs_previous_pct != null ? ` · ${o.vs_previous_pct > 0 ? "+" : ""}${F.num(o.vs_previous_pct, 1)} % vs précédent` : ""}`);
  }), 0);
}

/** Section « Efficacité en descente » de la page séance (#47) : un tableau, une
 * ligne par classe de pente descendante RÉELLEMENT qualifiante (durée/distance
 * minimales, voir `arc_descent.ASSUMPTIONS["thresholds"]`) — jamais une classe
 * sans assez de données (critère d'acceptation de #47). `descent` vient de
 * `/api/activity/<id>.descent` (`arc_serve.py::api_activity_descent`) et porte
 * TOUJOURS une `reason` explicite quand `descent.classes` est vide, y compris
 * pour un parcours sans descente qualifiante — contrairement aux montées
 * (`climbsSection`), l'absence de classe est ici TOUJOURS documentée (jamais un
 * état muet, voir `arc_descent.descent_report`). L'indicateur d'efficacité est
 * un RATIO à l'athlète lui-même (via le modèle de Minetti), pas une note
 * absolue — un rappel explicite de cette lecture accompagne le tableau (voir
 * `arc_descent.ASSUMPTIONS["indicator"]`). */
// Même ordre que `arc_descent.DESCENT_GRADE_CLASSES` (Python) — dupliqué ici
// volontairement (pas de dépendance runtime entre le serveur Python et le JS
// statique, même motif que `GRADE_CLASS_ORDER` ci-dessus) : à tenir à jour si
// `DESCENT_GRADE_CLASSES` change côté serveur. Scindé au-delà de -20 % (revue de
// code #47) : le coût de Minetti n'est pas monotone en descente (voir
// `arc_descent.ASSUMPTIONS["grade_classes"]`).
const DESCENT_GRADE_CLASS_ORDER = ["-5 à -10 %", "-10 à -15 %", "-15 à -20 %", "-20 à -30 %", "< -30 %"];
const DESCENT_REFERENCE_SOURCE_LABEL = { flat: "sections plates de la séance", non_descent: "hors forte descente (repli)" };

function descentSection(descent) {
  const classes = (descent && descent.classes) || {};
  const reason = descent && descent.reason;
  const labels = DESCENT_GRADE_CLASS_ORDER.filter((cls) => classes[cls]);
  // `applicable === false` (jamais un test sur le texte français de `reason` —
  // revue de code #47, nit, même motif que `climbsSection`) : séance qui n'a
  // structurellement jamais pu avoir de descente classée (renforcement, vélo...).
  if (descent && descent.applicable === false) {
    return "";
  }
  if (!labels.length) {
    const msg = reason
      ? F.esc(reason).replace(/^./, (c) => c.toUpperCase())
      : "Aucune classe de pente descendante avec assez de données sur cette séance.";
    return `<section class="band"><h2>Efficacité en descente</h2>${note(msg)}</section>`;
  }
  const refSource = descent.reference_source ? DESCENT_REFERENCE_SOURCE_LABEL[descent.reference_source] : null;
  return `<section class="band"><h2>Efficacité en descente</h2>
    <p class="muted">Efficacité = moyenne, pondérée par le temps, du ratio vitesse en descente /
      vitesse prédite par le modèle (Minetti) à partir de l'allure GAP de référence de la séance —
      <strong>1,00×</strong> si l'effort métabolique reste constant. Le modèle SURESTIME le bénéfice
      des fortes descentes en conditions réelles de trail : une valeur bien sous 1,00× sur les pentes
      les plus raides est normale (prudence, terrain technique), pas un mauvais résultat. C'est sa
      <strong>tendance dans le temps, à pente égale</strong>, qui compte — jamais une comparaison entre
      classes de pente différentes. ${hypLink("descente")}</p>
    <div class="table-wrap"><table class="data data--compact"><thead><tr>
      <th scope="col">Pente</th><th scope="col" class="num">Pente moy.</th><th scope="col" class="num">Allure</th>
      <th scope="col" class="num">Distance</th><th scope="col" class="num">Durée</th>
      <th scope="col" class="num">Efficacité</th></tr></thead>
    <tbody>${labels.map((cls) => { const c = classes[cls]; return `<tr><td><span class="tag">${F.esc(cls)}</span></td>
      <td class="num">${c.mean_grade != null ? `${F.num(Math.abs(c.mean_grade) * 100, 1)} %` : "—"}</td>
      <td class="num">${F.paceFromSecPerKm(c.mean_pace_s_km)}</td>
      <td class="num">${F.distance(c.distance_m, 2)}</td>
      <td class="num">${F.duration(c.duration_moving_s, { seconds: true })}</td>
      <td class="num">${F.efficiency(c.efficiency)} <small class="muted" title="Échantillons agrégés dans cette classe">(${c.count} éch.)</small></td></tr>`; }).join("")}</tbody></table></div>
    ${descent.reference_gap_pace_s_km != null ? `<p class="legend legend--small">Référence (allure GAP, ${F.esc(refSource || "source inconnue")}) : ${F.paceFromSecPerKm(descent.reference_gap_pace_s_km)}</p>` : ""}</section>`;
}

/** Section « Dépense énergétique » de la page séance : Garmin (`calories_kcal`,
 * référence par défaut PARTOUT AILLEURS — nutrition, rapports) et le modèle
 * indépendant (RE3 course + marche de Minetti, brut — métabolisme de base
 * inclus, voir `scripts/arc_energy.py::ASSUMPTIONS`/`docs/marques.md`) côte à
 * côte, avec leur écart. `energy` vient de `/api/activity/<id>.energy`
 * (`arc_serve.py::api_activity_energy`, qui délègue ENTIÈREMENT à
 * `arc_index.activity_energy_report_by_id` — même fonction que la CLI `arc_index.py
 * energy` et `/api/energy-trend` : le delta et le drapeau `flag` (écart notable,
 * |écart| > `arc_energy.DELTA_ALERT_PCT`, 15 %) sont déjà calculés côté serveur,
 * jamais recalculés ici).
 *
 * Masquée pour les sports hors de la famille course à pied
 * (`reason_code === "not_run_family"`, même discipline que `climbsSection`/
 * `descentSection` ci-dessus : la section n'a structurellement jamais pu
 * s'appliquer). `noFitSamples` (calculé par l'appelant, `viewSession`) évite de
 * DOUBLER la note consolidée de `noFitSamplesNote` (revue de code) : quand elle
 * s'affiche déjà (séance de la famille course à pied sans AUCUN échantillon
 * FIT), cette section se réduit au seul fait Garmin, sans répéter la raison.
 * Dans tous les AUTRES cas SANS `model_kcal` (pas d'identifiant Garmin —
 * séance Intervals.icu, #68 ; pas de poids connu à la date de la séance),
 * Garmin reste affiché seul quand connu, avec une raison explicite en français
 * — jamais un « NaN » ni une section vide muette. */
function energySection(energy, noFitSamples) {
  if (!energy || energy.reason_code === "not_run_family") return "";
  const hasGarmin = energy.garmin_kcal != null;
  if (energy.model_kcal == null) {
    if (noFitSamples && energy.reason_code === "no_samples") {
      // La raison (absence d'échantillons FIT) est déjà dite UNE fois par
      // `noFitSamplesNote` — jamais un second texte identique ici.
      return hasGarmin ? `<section class="band"><h2>Dépense énergétique</h2>
        <dl class="facts facts--inline"><div><dt>Garmin (référence)</dt><dd>${F.kcal(energy.garmin_kcal)}</dd></div></dl></section>` : "";
    }
    const reasonText = ENERGY_REASON_LABEL[energy.reason_code] || energy.reason;
    const msg = reasonText
      ? F.esc(reasonText).replace(/^./, (c) => c.toUpperCase())
      : "Dépense énergétique modèle non calculable pour cette séance.";
    return `<section class="band"><h2>Dépense énergétique</h2>
      <dl class="facts facts--inline"><div><dt>Garmin (référence)</dt><dd>${hasGarmin ? F.kcal(energy.garmin_kcal) : "non mesuré"}</dd></div></dl>
      ${note(msg)}</section>`;
  }
  const flagged = energy.flag === true;
  const deltaHtml = hasGarmin
    ? `<span class="${flagged ? "neg" : ""}">${energy.delta_pct > 0 ? "+" : ""}${F.num(energy.delta_pct, 1)} %</span>${flagged ? ` <span class="chip chip--verdict-amber">Écart notable</span>` : ""}`
    : `<span class="muted" title="Garmin n'a pas mesuré la dépense de cette séance">—</span>`;
  const breakdown = energy.breakdown || {};
  const breakdownRows = ENERGY_BREAKDOWN_ORDER.filter((cat) => breakdown[cat]
    && ((breakdown[cat].kcal != null && breakdown[cat].kcal !== 0) || (breakdown[cat].seconds != null && breakdown[cat].seconds !== 0)));
  const weightLabel = ENERGY_WEIGHT_SOURCE_LABEL[energy.weight_source] || energy.weight_source;
  return `<section class="band"><h2>Dépense énergétique</h2>
    <p class="muted">Garmin (<code>calories_kcal</code>) reste la référence par défaut partout ailleurs
      (nutrition, rapports) ; le modèle indépendant n'est qu'un contrôle, jamais un remplacement.
      ${hypLink("energie")}</p>
    <dl class="facts facts--inline">
      <div><dt>Garmin (référence)</dt><dd>${hasGarmin ? F.kcal(energy.garmin_kcal) : "non mesuré"}</dd></div>
      <div><dt>Modèle</dt><dd>${F.kcal(energy.model_kcal)}</dd></div>
      <div><dt>Écart</dt><dd>${deltaHtml}</dd></div>
      ${energy.bmr_kcal != null ? `<div><dt>Net (hors métabolisme de base)</dt><dd>Garmin ${energy.net_garmin_kcal != null ? F.kcal(energy.net_garmin_kcal) : "—"} · Modèle ${F.kcal(energy.net_model_kcal)}</dd></div>` : ""}
    </dl>
    ${energy.bmr_kcal == null ? `<p><small class="muted">BMR Garmin non disponible pour cette séance : la part nette (hors métabolisme de base) ne peut pas être calculée.</small></p>` : ""}
    ${breakdownRows.length ? `<div class="table-wrap"><table class="data data--compact"><thead><tr>
      <th scope="col">Segment</th><th scope="col" class="num">Temps</th><th scope="col" class="num">kcal</th></tr></thead>
      <tbody>${breakdownRows.map((cat) => `<tr><td>${ENERGY_BREAKDOWN_LABEL[cat]}</td><td class="num">${F.duration(breakdown[cat].seconds, { seconds: true })}</td><td class="num">${breakdown[cat].kcal != null ? F.num(breakdown[cat].kcal) : "—"}</td></tr>`).join("")}</tbody></table></div>` : ""}
    ${energy.weight_kg != null ? `<p class="legend legend--small">Poids utilisé pour le modèle : ${F.weight(energy.weight_kg)} <small class="muted">(${F.esc(weightLabel || "source inconnue")})</small></p>` : ""}</section>`;
}

// Libellés français, indexés sur `reason_code` — jamais une raison technique
// (nom de module, de table, de story) affichée telle quelle à l'athlète (revue
// de code : `no_activity_id`/`no_row` mentionnaient `garminconnect`/
// `activity_energy` dans le texte serveur, du jargon interne). `reason` (texte
// serveur, `arc_index._energy_reason_for_missing_row`) reste le repli si un
// `reason_code` futur n'a pas encore son libellé ici.
const ENERGY_REASON_LABEL = {
  no_activity_id: "séance sans identifiant de montre (saisie manuelle ?) : le modèle a besoin "
    + "des mesures fines de la montre, indisponibles ici.",
  no_samples: "aucun échantillon FIT ingéré pour cette séance.",
  no_row: "dépense énergétique modèle indisponible pour cette séance.",
  no_weight: "aucun poids connu à la date de cette séance (santé, nutrition ou profil).",
  internal_error: "calcul impossible pour cette séance (erreur interne).",
};

// Ordre/libellés des segments du modèle — dupliqués ici volontairement (pas de
// dépendance runtime entre le serveur Python et le JS statique, même motif que
// `GRADE_CLASS_ORDER`/`DESCENT_GRADE_CLASS_ORDER` ci-dessus) : à tenir à jour si
// `arc_energy.BREAKDOWN_CATEGORIES` change côté serveur.
const ENERGY_BREAKDOWN_ORDER = ["flat", "uphill", "downhill", "walk", "stopped"];
const ENERGY_BREAKDOWN_LABEL = { flat: "Plat", uphill: "Montée", downhill: "Descente", walk: "Marche", stopped: "Arrêt" };
const ENERGY_WEIGHT_SOURCE_LABEL = { health_day: "santé", nutrition_day: "nutrition", profile: "profil" };

/** Section « Zones FC » de la page séance (#43) : temps en zone en barre empilée
 * (SVG, jamais de style en ligne — CSP `style-src 'self'`) + légende. `hz` vient de
 * `/api/activity/<id>.hr_zones` (voir `arc_serve.py::api_activity_hr_zones`), et est
 * TOUJOURS un objet (jamais `null` — revue de code #43, point 4) : `bounds_bpm: null`
 * porte une `reason` explicite (méthode inconnue, méthode forcée mais champ manquant
 * au profil, ou aucune donnée du tout) affichée à l'utilisateur plutôt que masquée ;
 * `zone_seconds: null` avec des bornes connues signale une séance sans échantillons
 * FIT (ou un sport hors de la famille course à pied, voir `compute_metrics`). */
const HR_ZONE_METHOD_LABEL = { lthr: "FC au seuil (LTHR)", karvonen: "Karvonen (réserve FC)", percent_max: "% FC max" };

/** Bornes INTÉRIEURES seulement (« Z1 < 146 · Z2 146-153 · … · Z5 ≥ 170 ») : le
 * premier (0) et le dernier (1,5×) élément de `bounds_bpm` sont des repères de calcul
 * internes, jamais des seuils réels (revue de code #43, point 3 — un temps de FC sous
 * le plancher théorique de Z1 compte quand même dans Z1, `arc_metrics.hr_zone_of`). */
function hrZoneBoundsLabel(bounds) {
  const b = bounds.map((v) => Math.round(v));
  return [
    `Z1 < ${b[1]}`, `Z2 ${b[1]}-${b[2]}`, `Z3 ${b[2]}-${b[3]}`, `Z4 ${b[3]}-${b[4]}`, `Z5 ≥ ${b[4]}`,
  ].join(" · ") + " bpm";
}

/** Note unique remplaçant zones FC + montées + descente quand une séance de la
 * famille course à pied n'a AUCUN échantillon FIT ingéré (#50, voir le calcul de
 * `noFitSamples` dans `viewSession`) — plutôt que trois sections vides côte à
 * côte disant chacune, à sa façon, la même chose.
 *
 * `hz` (revue de code #50, should-fix 5) : consolider zones/montées/descente en
 * une note ne doit PAS faire perdre les deux informations que `hrZoneSection`
 * portait seule — les bornes bpm effectives (`hz.bounds_bpm`, utiles même sans
 * échantillons : elles restent affichées sur la page dès que la méthode de
 * zones du profil est connue) et, quand la méthode elle-même est inconnue ou
 * incomplète (`hz.bounds_bpm` nul), la `reason` explicite (#43, point 4) — un
 * problème de PROFIL (méthode manquante, champ requis absent), pas la même
 * cause qu'une simple absence de FIT sur cette séance, jamais fusionné avec
 * elle sous peine de perdre l'information qui permettrait de le corriger. */
function noFitSamplesNote(hz) {
  const methodLabel = hz && hz.method ? (HR_ZONE_METHOD_LABEL[hz.method] || hz.method) : null;
  const boundsLine = hz && hz.bounds_bpm
    ? `<p class="muted">Bornes (${F.esc(methodLabel)}) : ${hrZoneBoundsLabel(hz.bounds_bpm)}.</p>`
    : (hz && hz.reason ? note(F.esc(hz.reason)) : "");
  return `<section class="band"><h2>Détail avancé</h2>${boundsLine}
    ${note("Aucun échantillon FIT ingéré pour cette séance : temps en zone, GAP par tour, montées (VAM), "
      + "efficacité en descente et dépense énergétique modèle ne peuvent pas être calculés. Synchronisez le "
      + "fichier FIT (skill <code>fit-download</code>) puis relancez l'indexation pour les activer.")}</section>`;
}

function hrZoneSection(hz) {
  const methodLabel = HR_ZONE_METHOD_LABEL[hz.method] || hz.method;
  if (!hz.bounds_bpm) {
    return `<section class="band"><h2>Zones FC</h2>${note(F.esc(hz.reason || "Zones FC non calculables."))}</section>`;
  }
  const boundsTxt = hrZoneBoundsLabel(hz.bounds_bpm);
  if (!hz.zone_seconds) {
    return `<section class="band"><h2>Zones FC</h2><p class="muted">Bornes (${F.esc(methodLabel)}) : ${boundsTxt}.</p>
      ${note(F.esc(hz.reason || "Pas d'échantillons FIT ingérés pour cette séance : le temps en zone ne peut pas être calculé."))}</section>`;
  }
  const seconds = [1, 2, 3, 4, 5].map((z) => hz.zone_seconds[z] ?? hz.zone_seconds[String(z)] ?? 0);
  const total = seconds.reduce((a, b) => a + b, 0);
  if (!total) return "";
  const w = 640, h = 26;
  let x = 0;
  const segs = seconds.map((secs, i) => {
    const z = i + 1, width = (secs / total) * w;
    const rect = width > 0 ? `<rect class="zone zone--${z}" x="${x.toFixed(2)}" y="0" width="${width.toFixed(2)}" height="${h}"><title>Zone ${z} : ${F.duration(secs)}</title></rect>` : "";
    x += width;
    return rect;
  }).join("");
  const label = `Temps en zone : ${seconds.map((s, i) => `zone ${i + 1} ${F.duration(s)}`).join(", ")}, total ${F.duration(total)}.`;
  const legend = seconds.map((s, i) => `<span class="legend__item"><span class="key key--zone${i + 1}"></span>Z${i + 1} ${F.duration(s)}</span>`).join(" ");
  const pol = hz.polarisation;
  const polTxt = pol ? `<p class="muted">Polarisation : facile ${F.num(pol.low_pct, 0)} % · modérée ${F.num(pol.moderate_pct, 0)} % · difficile ${F.num(pol.high_pct, 0)} %.</p>` : "";
  return `<section class="band"><h2>Zones FC</h2><p class="muted">Bornes (${F.esc(methodLabel)}) : ${boundsTxt}.</p>
    <svg class="zone-bar" viewBox="0 0 ${w} ${h}" role="img" aria-label="${F.esc(label)}">${segs}</svg>
    <p class="legend">${legend}</p>${polTxt}</section>`;
}

// ---------------------------------------------------------------------------
// Vue : Performance
// ---------------------------------------------------------------------------

/** Étiquette d'un panier de pente (`arc_slope_model.GRADE_BINS`) pour l'axe x —
 * arrondie au point de pourcentage, plus lisible que le libellé brut du serveur
 * (ex. « +7.5/+10.0% » -> « +9 % ») : le point milieu (`grade_mid`) est déjà la
 * valeur qui sert à l'interpolation (`predict_speed` côté serveur), donc la
 * SEULE pente que ce panier représente réellement pour la lecture au survol. */
function slopeGradeLabel(b) {
  return `${b.grade_mid >= 0 ? "+" : ""}${Math.round(b.grade_mid * 100)} %`;
}

/** Section « Modèle personnel pente -> allure » de la vue Performance (#58) :
 * un graphique allure (F.paceFromSecPerKm, imperial-aware) vs pente, avec une
 * bande d'intervalle interquartile (repère de dispersion, pas un IC statistique
 * au sens strict — voir `arc_slope_model.ASSUMPTIONS['robust_stats']`) et une
 * courbe générique de comparaison (repli Minetti). Les DEUX courbes viennent
 * directement de `b.pace_s_km` par panier, TELLES QUE `/api/slope-model` les
 * renvoie (déjà lissées avec leurs voisins de même provenance — voir
 * `arc_slope_model.ASSUMPTIONS['smoothing']`) : rien n'est recalculé côté
 * client (revue de code #58, nit — une version antérieure de ce commentaire
 * prétendait à tort le contraire).
 *
 * Un panier PERSONNEL isolé (aucun voisin personnel adjacent, donc jamais relié
 * par un trait à `pathFrom`, voir `chart.js`) reste rendu en POINT (couche
 * `dots` séparée, revue de code #58, nit) — sans elle, un point personnel isolé
 * entre deux paniers génériques disparaîtrait silencieusement du graphique.
 *
 * Axe x par INDICE de panier, pas à l'échelle réelle de la pente (mêmes limites
 * assumées que `fuelingSection` : les paniers sont de largeur égale, donc
 * l'écart n'est trompeur qu'aux deux paniers ouverts en bout de plage, dont le
 * point milieu est un ancrage nominal — voir `arc_slope_model.ASSUMPTIONS
 * ['interpolation']`). Axe y INVERSÉ (`invert: true`, `chart.js`) : plus RAPIDE
 * (nombre plus petit) affiché en HAUT, comme la convention « mieux = plus haut »
 * du reste du tableau de bord. */
function slopeModelSection(model, band) {
  if (model.reason_code) {
    return { html: `<section class="band"><h2>Modèle personnel pente → allure</h2>${note(F.esc(model.reason))}</section>`, chart: null };
  }
  // Paniers ouverts (queues) exclus de l'AFFICHAGE (leur point milieu est un ancrage
  // nominal, pas une pente réellement représentative) — restent utilisés par
  // `predict_speed` côté serveur pour #59/#60/#61, juste pas tracés ici.
  const bins = model.bins.filter((b) => Number.isFinite(b.grade_lo) && Number.isFinite(b.grade_hi));
  if (!bins.length) {
    return { html: `<section class="band"><h2>Modèle personnel pente → allure</h2>${note("Aucun panier de pente exploitable.")}</section>`, chart: null };
  }
  const xLabels = bins.map(slopeGradeLabel);
  const personal = bins.map((b) => (b.source === "personal" ? b.pace_s_km : null));
  // Repli générique affiché seulement jusqu'à ±20 % (revue de code #58, nit) : au-delà,
  // le repli (déjà plafonné en descente, mais pas en montée) diverge trop pour partager
  // un axe lisible avec l'allure personnelle — mieux vaut l'arrêter que d'écraser toute
  // la partie utile du graphique pour montrer une queue extrême. `predict_speed` côté
  // serveur continue, lui, d'utiliser TOUS les paniers, affichage ou pas.
  const GENERIC_DISPLAY_MAX_ABS_GRADE = 0.20;
  const generic = bins.map((b) => (
    b.source === "generic" && Math.abs(b.grade_mid) <= GENERIC_DISPLAY_MAX_ABS_GRADE ? b.pace_s_km : null));
  // `ci_low_speed_ms`/`ci_high_speed_ms` sont des bornes de VITESSE (p25/p75) : converties
  // en allure, elles s'INVERSENT (la vitesse p25, plus lente, donne l'allure la plus
  // GRANDE — le "haut" numérique de la bande d'allure, pas son "bas").
  const paceFromSlowSpeedP25 = bins.map((b) => (b.ci_low_speed_ms ? 1000 / b.ci_low_speed_ms : null));
  const paceFromFastSpeedP75 = bins.map((b) => (b.ci_high_speed_ms ? 1000 / b.ci_high_speed_ms : null));
  const hasHr = bins.some((b) => b.hr_bpm != null);
  // Un panier ISOLÉ (aucun voisin de même provenance, PARMI CE QUI EST AFFICHÉ) ne
  // serait jamais tracé par sa `line` (aucun segment ne le relie à rien, `pathFrom`
  // n'émet qu'un "M" sans "L" — même motif que `fuelingSection`, revue de code #58,
  // nit) : une couche `dots` séparée le rend visible même isolé — pour le personnel
  // ET pour le générique affiché (ex. un seul panier générique entre deux personnels).
  const isolatedValues = (values) => values.map((v, i) => {
    if (v == null) return null;
    const prevSame = i > 0 && values[i - 1] != null;
    const nextSame = i + 1 < values.length && values[i + 1] != null;
    return prevSame || nextSame ? null : v;
  });
  const personalDots = isolatedValues(personal);
  const genericDots = isolatedValues(generic);
  const layers = [
    { type: "band", lo: paceFromFastSpeedP75, hi: paceFromSlowSpeedP25, cls: "band--slope-ci" },
    { type: "line", values: personal, cls: "line line--slope" },
    { type: "line", values: generic, cls: "line line--slope-generic" },
    { type: "dots", values: personalDots, cls: "dot dot--slope", r: 3 },
    { type: "dots", values: genericDots, cls: "dot dot--slope-generic", r: 2.6 },
  ];
  // Axe y borné aux valeurs PERSONNELLES (+ dispersion, + repli générique affiché ci-dessus,
  // marge de 15 %) plutôt qu'à l'étendue brute de tous les paniers (revue de code #58,
  // nit) : sans ce clamp, un seul panier générique extrême (montée très raide, jamais
  // plafonnée comme la descente) écrasait toute la partie personnelle du graphique sur
  // une fraction illisible de la hauteur disponible.
  const rangeValues = [...personal, ...paceFromSlowSpeedP25, ...paceFromFastSpeedP75, ...generic]
    .filter((v) => v != null);
  let yOpts = { invert: true };
  if (rangeValues.length) {
    const yLo = Math.min(...rangeValues), yHi = Math.max(...rangeValues);
    const margin = (yHi - yLo) * 0.15 || yHi * 0.15 || 10;
    yOpts = { invert: true, min: Math.max(0, yLo - margin), max: yHi + margin };
  }
  let y2Opts;
  if (hasHr) {
    layers.push({ type: "dots", values: bins.map((b) => b.hr_bpm), cls: "dot dot--slope-hr", axis: "y2", r: 3 });
    // Plage minimale de 10 bpm (revue de code #58, should-fix 7) : sur une fenêtre de
    // FC très resserrée (ex. 140-144 bpm), l'arrondi de `niceTicks` produisait des
    // graduations dupliquées (« 144 bpm » deux fois) — un padding symétrique évite
    // à la fois les doublons et un axe qui donnerait une fausse impression de
    // variation en zoomant sur un écart de 1-2 bpm.
    const hrValues = bins.map((b) => b.hr_bpm).filter((v) => v != null);
    const hrMin = Math.min(...hrValues), hrMax = Math.max(...hrValues);
    const pad = Math.max(0, (10 - (hrMax - hrMin)) / 2);
    y2Opts = { min: hrMin - pad, max: hrMax + pad };
  }
  // Pas de repère à 0 (revue de code #58, should-fix 7) : une allure de 0:00/km n'a
  // aucun sens et forcer l'axe à l'inclure écrase l'échelle utile — contrairement à
  // un delta ou une charge, l'allure n'a pas de « zéro » de référence à marquer.
  const chart = timeChart(xLabels, layers, [], {
    height: 220, y: yOpts, y2: y2Opts,
    label: `Allure par classe de pente, bande ${band === "all" ? "tous efforts" : "endurance"}`,
    yFormat: (v) => F.paceFromSecPerKm(v), y2Format: hasHr ? (v) => `${F.num(v)} bpm` : undefined,
    xLabels,
  });
  const bandLabel = band === "all" ? "tous efforts" : "endurance";
  const other = band === "all" ? "endurance" : "all";
  const otherLabel = other === "all" ? "Tous efforts" : "Endurance";
  const html = `<section class="band"><h2>Modèle personnel pente → allure</h2>
    <p class="muted">Allure typique (médiane pondérée par le temps et la récence, demi-vie
      ${F.num(model.half_life_days, 0)} j) par classe de pente, sur les ${F.num(model.months)} derniers mois
      (${F.num(model.n_activities)} séance${model.n_activities > 1 ? "s" : ""}), bande <strong>${bandLabel}</strong>.
      Repli sur le modèle générique (Minetti, trait pointillé) quand l'historique manque sur une classe.
      La bande grisée est un repère de dispersion (quartiles), pas un intervalle de confiance statistique.
      <a href="#/performance?bande=${other}">Voir la bande « ${otherLabel} »</a> ·
      ${hypLink("pente")}</p>
    <p class="legend"><span class="legend__item"><span class="key key--slope-band"></span>Dispersion (quartiles)</span>
      <span class="legend__item"><span class="key key--slope"></span>Personnel</span>
      <span class="legend__item"><span class="key key--slope-generic"></span>Générique (Minetti)</span>
      ${hasHr ? `<span class="legend__item"><span class="key key--slope-hr"></span>FC médiane</span>` : ""}</p>
    <div class="chart-host" id="c-slope">${chart.svg}</div><p class="readout" id="r-slope"></p>
    ${model.flat_reference_speed_ms ? `<p class="legend legend--small">Référence plate personnelle : ${F.paceFromSecPerKm(1000 / model.flat_reference_speed_ms)}</p>` : ""}</section>`;
  return { html, chart, bins };
}

// Libellé d'une durée de la courbe allure-durée (30 s, 5 min, 2 h) — axe x par INDICE.
function paceCurveDurationLabel(s) {
  if (s < 60) return `${s} s`;
  if (s < 3600) return `${Math.round(s / 60)} min`;
  return `${F.num(s / 3600, s % 3600 ? 1 : 0)} h`;
}

/** Section « Vitesse critique et courbe allure-durée » (#169) : meilleure allure GAP par durée
 * (fenêtres 42 j / 90 j / 365 j, axe y inversé : plus rapide en haut), CS/D′ de la fenêtre de
 * 90 j avec sa qualité (n, R², erreur standard), tendance. Aucun calcul côté client : tout vient
 * de `/api/pace-curve`. Un ajustement refusé affiche son motif (« données insuffisantes »), jamais
 * une valeur. Axe x par indice de durée (échelle non linéaire, comme `slopeModelSection`). */
function paceCurveSection(data) {
  const title = "<h2>Vitesse critique et courbe allure-durée</h2>";
  if (!data) return { html: `<section class="band">${title}${note("Courbe indisponible.")}</section>` };
  const w90 = data.windows.find((w) => w.window_days === data.trend_window_days) || data.windows[0];
  if (!data.n_activities || !w90 || !w90.curve.length) {
    return { html: `<section class="band">${title}${note(`Données insuffisantes : ${F.esc(data.reason || "aucune séance de course avec échantillons FIT (altitude) sur la période")}.`)}</section>` };
  }
  const durs = data.durations_s;
  // Seules quelques durées sont étiquetées sur l'axe (lisibilité mobile) ; le survol nomme chacune.
  const LABELLED = [60, 300, 600, 1200, 3600, 7200];
  const xLabels = durs.map((d) => (LABELLED.includes(d) ? paceCurveDurationLabel(d) : ""));
  const series = (w) => durs.map((d) => { const r = w.curve.find((c) => c.duration_s === d); return r ? r.pace_s_km : null; });
  const isolated = (vals) => vals.map((v, i) => (v != null && (i === 0 || vals[i - 1] == null) && (i + 1 >= vals.length || vals[i + 1] == null) ? v : null));
  const byDays = Object.fromEntries(data.windows.map((w) => [w.window_days, w]));
  const main90 = series(w90);
  const layers = [];
  if (byDays[365]) layers.push({ type: "line", values: series(byDays[365]), cls: "line line--slope-generic" });
  if (byDays[42]) layers.push({ type: "line", values: series(byDays[42]), cls: "line line--fatigue" });
  layers.push({ type: "line", values: main90, cls: "line line--slope" }, { type: "dots", values: isolated(main90), cls: "dot dot--slope", r: 3 });
  const marks = [];
  const fit = data.current;
  if (fit && fit.valid) marks.push({ type: "hline", value: fit.cs_pace_s_km, cls: "mark", label: "CS" });
  const all = layers.flatMap((l) => l.values).filter((v) => v != null);
  const lo = Math.min(...all), hi = Math.max(...all);
  const margin = (hi - lo) * 0.1 || 10;
  const chart = timeChart(xLabels, layers, marks, {
    height: 220, y: { invert: true, min: Math.max(0, lo - margin), max: hi + margin },
    label: "Meilleure allure ajustée à la pente par durée", yFormat: (v) => F.paceFromSecPerKm(v), xLabels,
  });
  let fitHtml;
  if (fit && fit.valid) {
    fitHtml = `<p class="lead-num">${F.paceFromSecPerKm(fit.cs_pace_s_km)} <small>vitesse critique (GAP) · réserve anaérobie D′ ${F.num(fit.d_prime_m, 0)} m</small></p>
      <p class="muted">Qualité ${F.esc(fit.quality)} : ${fit.n_points} efforts de 3 à 20 min, incertitude ± ${F.num(fit.cs_se_pct, 1)} % sur la vitesse critique
      (± ${F.num(fit.cs_se_ms * 3.6, 2)} km/h) et ± ${F.num(fit.d_prime_se_m, 0)} m sur D′, R² ${F.num(fit.r2, 3)}. Estimation à partir des meilleurs efforts
      d'entraînement, pas d'un test : un effort jamais couru à fond la sous-estime.</p>`;
  } else {
    fitHtml = note(`Données insuffisantes pour ajuster la vitesse critique : ${F.esc((fit && fit.reason) || "aucun effort exploitable")}.`);
  }
  const chk = data.threshold_check;
  const chkHtml = chk && chk.available
    ? `<p class="muted">Seuil lactique Garmin : écart ${chk.delta_pct > 0 ? "+" : ""}${F.num(chk.delta_pct, 1)} % avec la vitesse critique${chk.diverges ? " — divergence signalée, aucune des deux valeurs n'est préférée" : ""}.</p>` : "";
  // Tendance : un point tous les 28 j (meilleur de 90 j) ; les refus laissent un trou, jamais une valeur reportée.
  const tr = data.trend;
  const trVals = tr.map((p) => (p.status === "ok" ? p.cs_pace_s_km : null));
  let trendHtml = "", trendChart = null;
  if (trVals.some((v) => v != null)) {
    const tv = trVals.filter((v) => v != null);
    const tlo = Math.min(...tv), thi = Math.max(...tv), tm = (thi - tlo) * 0.2 || 10;
    trendChart = timeChart(tr.map((p) => p.date), [
      { type: "line", values: trVals, cls: "line line--slope" }, { type: "dots", values: trVals, cls: "dot dot--slope", r: 3 },
    ], [], { height: 160, y: { invert: true, min: Math.max(0, tlo - tm), max: thi + tm }, label: "Vitesse critique (allure GAP), tendance", yFormat: (v) => F.paceFromSecPerKm(v) });
    trendHtml = `<h3>Tendance</h3><div class="chart-host" id="c-cstrend">${trendChart.svg}</div><p class="readout" id="r-cstrend"></p>`;
  }
  const html = `<section class="band">${title}
    <p class="muted">Meilleure allure ajustée à la pente (GAP) tenue sur chaque durée, sur ${F.num(data.n_activities)} sortie${data.n_activities > 1 ? "s" : ""}
      de course avec FIT. ${hypLink("vitesse-critique")}</p>
    ${fitHtml}${chkHtml}
    <p class="legend"><span class="legend__item"><span class="key key--slope"></span>90 jours</span>
      <span class="legend__item"><span class="key key--fatigue"></span>42 jours</span>
      <span class="legend__item"><span class="key key--slope-generic"></span>365 jours</span></p>
    <div class="chart-host" id="c-pcurve">${chart.svg}</div><p class="readout" id="r-pcurve"></p>${trendHtml}
    ${data.skipped_no_grade ? `<p class="legend legend--small">${data.skipped_no_grade} séance${data.skipped_no_grade > 1 ? "s" : ""} sans altitude exploitable écartée${data.skipped_no_grade > 1 ? "s" : ""}.</p>` : ""}</section>`;
  return { html, chart, w90, durs, trendChart, tr };
}

async function viewPerformance(params) {
  const band = params && params.get("bande") === "all" ? "all" : "endurance";
  const [p, slope, pace] = await Promise.all([api("performance"), api(`slope-model?band=${band}`), api("pace-curve").catch(() => null)]);
  const trail = p.sport === "trail";
  let chartHtml = empty("Pas encore d'estimation", "La VO2max effective s'estime sur les séances de course d'au moins 20 minutes, à plus de 70 % de la FC max, avec distance et FC moyenne.");
  let c = null;
  if (p.vo2max.length) {
    c = timeChart(p.vo2max.map((x) => x.date), [{ type: "line", values: p.vo2max.map((x) => x.vo2max), cls: "line line--fitness" }], [], { height: 200, label: "VO2max effective, tendance 30 jours", yFormat: (v) => F.num(v) });
    chartHtml = `<div class="chart-host" id="c-vo2">${c.svg}</div><p class="readout" id="r-vo2"></p>`;
  }
  const names = { 5000: "5 km", 10000: "10 km", 21097.5: "Semi-marathon", 42195: "Marathon" };
  const pred = p.predictions.map((r) => `<tr><th scope="row">${r.tag === "objective" ? `${F.esc(p.objective.name || "Objectif")} <span class="muted">${F.distance(r.distance_m, 1)}${trail && r.effort_distance_m !== Math.round(r.distance_m) ? ` · effort ${F.distance(r.effort_distance_m, 0)}` : ""}</span>` : names[r.distance_m] || F.distance(r.distance_m)}</th><td class="num">${F.clock(r.vdot_s)}</td><td class="num">${F.clock(r.riegel_s)}</td></tr>`).join("");
  const rec = p.records.length ? `<table class="data data--compact"><thead><tr><th scope="col">Distance</th><th scope="col" class="num">Temps</th><th scope="col" class="num">Allure</th><th scope="col">Date</th></tr></thead><tbody>${p.records.map((r) => `<tr><th scope="row">${r.km} km</th><td class="num">${F.clock(r.time_s)}</td><td class="num">${F.pace(r.km * 1000, r.time_s)}</td><td>${F.dayShort(r.date)} ${r.date.slice(0, 4)}</td></tr>`).join("")}</tbody></table>` : note("Pas de splits kilométriques indexés : les records se calculent sur les séances qui en ont.");
  const { html: slopeHtml, chart: slopeChart, bins: slopeBins } = slopeModelSection(slope, band);
  const { html: indexHtml, charts: indexCharts } = performanceIndexSection(SUMMARY.performance_index);
  const paceSec = paceCurveSection(pace);
  main.innerHTML = `${header("Performance", "Estimations modélisées à partir des moyennes de chaque séance : des ordres de grandeur, pas des mesures.")}
    <section class="band"><h2>VO2max effective</h2>${p.vo2max_current ? `<p class="lead-num">${F.num(p.vo2max_current, 1)} <small>ml/kg/min, tendance 30 j${p.vo2max_date !== SUMMARY.today ? ` au ${F.dayShort(p.vo2max_date)}` : ""}</small></p>` : ""}${chartHtml}</section>
    <section class="band band--split"><div><h2>Prédictions</h2><table class="data data--compact"><thead><tr><th scope="col">Distance</th><th scope="col" class="num">VDOT</th><th scope="col" class="num">Riegel</th></tr></thead><tbody>${pred}</tbody></table>
      ${trail ? note("En trail, la distance « effort » ajoute le dénivelé (1000 m D+ ≈ 1,75 km de plat, <code>config/sports/trail.md</code>). Sable, vent et barrières ne sont pas modélisés.") : ""}</div>
      <div><h2>Records</h2>${rec}</div></section>
    ${paceSec.html}
    ${slopeHtml}
    <p class="note">Kilométrage des chaussures, équipement et inspections : <a href="#/materiel">vue Matériel</a>.</p>
    ${indexHtml}
    <p class="note">Formules, seuils et limites connues de chaque estimation : ${hypLink("performance", "Hypothèses des modèles")}.</p>`;
  if (c) attachCursor($("#c-vo2"), c, (i) => readout($("#r-vo2"), `<strong>${F.dayLong(p.vo2max[i].date)}</strong> · ${p.vo2max[i].vo2max != null ? F.num(p.vo2max[i].vo2max, 1) : "pas d'estimation (aucune séance de course qualifiante sur 30 j)"}`));
  if (slopeChart) attachCursor($("#c-slope"), slopeChart, (i) => {
    const b = slopeBins[i];
    const hrTxt = b.hr_bpm != null ? ` · FC médiane ${F.num(b.hr_bpm, 0)} bpm` : "";
    const runTxt = b.run_share != null && b.run_share < 0.95 ? ` · couru ${F.num(b.run_share * 100, 0)} %` : "";
    readout($("#r-slope"), `<strong>${slopeGradeLabel(b)}</strong> · ${F.paceFromSecPerKm(b.pace_s_km)} · ${b.source === "personal" ? `personnel (${b.n_activities} séance${b.n_activities > 1 ? "s" : ""})` : "générique"}${hrTxt}${runTxt}`);
  });
  if (paceSec.chart) attachCursor($("#c-pcurve"), paceSec.chart, (i) => {
    const r = paceSec.w90.curve.find((c) => c.duration_s === paceSec.durs[i]);
    readout($("#r-pcurve"), r
      ? `<strong>${paceCurveDurationLabel(r.duration_s)}</strong> · ${F.paceFromSecPerKm(r.pace_s_km)} (GAP) · ${F.dayShort(r.date)} ${r.date.slice(0, 4)}`
      : `<strong>${paceCurveDurationLabel(paceSec.durs[i])}</strong> · pas d'effort exploitable sur 90 j`);
  });
  if (paceSec.trendChart) attachCursor($("#c-cstrend"), paceSec.trendChart, (i) => {
    const p = paceSec.tr[i];
    readout($("#r-cstrend"), `<strong>${F.dateLong(p.date)}</strong> · ${p.status === "ok" ? `${F.paceFromSecPerKm(p.cs_pace_s_km)} · D′ ${F.num(p.d_prime_m, 0)} m · R² ${F.num(p.r2, 3)}` : F.esc(p.reason || "pas d'ajustement")}`);
  });
  for (const c2 of indexCharts) {
    attachCursor($(`#${c2.id}`), c2.chart, (i) => readout($(`#${c2.readoutId}`),
      `<strong>${F.dateLong(c2.entries[i].date)}</strong> · ${F.num(c2.entries[i].value, 0)}`));
  }
}

// ---------------------------------------------------------------------------
// Vue : Hypothèses des modèles — une référence lisible, plus un mur de texte
// ---------------------------------------------------------------------------

// `/api/assumptions` (~100 Ko) agrège les `ASSUMPTIONS` de chaque module Python : les
// clés préfixées (`vam_`, `descent_`…) viennent d'un module dédié, les autres
// d'`arc_metrics`/`arc_gap` (voir `arc_index.py`, agrégation des hypothèses). Le
// regroupement par modèle et les libellés ne vivent qu'ici ; une clé inconnue tombe
// dans « Autres » avec un libellé dérivé de son nom — jamais masquée.
const HYP_FAMILIES = [
  { id: "charge", title: "Charge & forme", keys: ["trimp", "trimp_sex_default", "srpe", "form", "acwr", "monotony", "compliance", "load_forecast"] },
  { id: "performance", title: "Performance", keys: ["vo2max", "prediction", "trail_equivalence", "records", "effort_km"] },
  { id: "sante", title: "Santé & récupération", keys: ["hrv_baseline", "sleep_debt", "heat_acclimation"] },
  { id: "zones", title: "Zones FC & foulée", keys: ["hr_zones", "gait"] },
  { id: "nutrition", title: "Poids, sudation & ravitaillement", keys: ["weight_merge", "weight_trend", "sweat_rate", "fueling"] },
  { id: "materiel", title: "Matériel", keys: ["gear_mileage", "equipment_usage", "gear_inspection"] },
  { id: "gap", title: "Allure ajustée à la pente (GAP)", keys: ["model", "grade_source", "restricted_to_run_family", "split_distance_default", "noise_robustness", "stopped_samples"] },
  { id: "decouplage", title: "Découplage aérobie", prefix: "decoupling_" },
  { id: "vam", title: "Montées & VAM", prefix: "vam_" },
  { id: "descente", title: "Efficacité en descente", prefix: "descent_" },
  { id: "durabilite", title: "Durabilité", prefix: "durability_" },
  { id: "pente", title: "Allure selon la pente", prefix: "slope_model_" },
  { id: "energie", title: "Dépense énergétique", prefix: "energy_" },
  { id: "vitesse-critique", title: "Vitesse critique et D′", prefix: "cs_" },
];
const HYP_LABELS = {
  trimp: "TRIMP de Banister", trimp_sex_default: "Sexe non renseigné", srpe: "Charge sans FC (session-RPE)",
  form: "Condition, fatigue et forme", acwr: "Ratio fatigue / condition (ACWR)", monotony: "Monotonie et strain",
  compliance: "Conformité plan vs réalisé", load_forecast: "Projection de charge jusqu'à la course", vo2max: "VO2max effective", prediction: "Prédictions de course",
  trail_equivalence: "Équivalence plat en trail", records: "Records", effort_km: "Km-effort ITRA",
  hrv_baseline: "Ligne de base HRV", sleep_debt: "Dette de sommeil", heat_acclimation: "Acclimatation à la chaleur",
  hr_zones: "Zones FC et polarisation 80/20", gait: "Synthèse « Foulée »",
  weight_merge: "Fusion des sources de poids", weight_trend: "Tendance du poids", sweat_rate: "Taux de sudation",
  fueling: "Glucides par heure", gear_mileage: "Kilométrage des chaussures", equipment_usage: "Matériel hors chaussures",
  gear_inspection: "Inspection photo", model: "Modèle de Minetti", grade_source: "Calcul de la pente",
  split_distance_default: "Split sans distance", noise_robustness: "Sensibilité au bruit de pente",
};
const HYP_SUFFIX = {
  model: "Modèle", restricted_to_run_family: "Course à pied uniquement", min_duration: "Durée minimale",
  warmup: "Échauffement exclu", stopped_samples: "Arrêts exclus", steep_grade_and_walking: "Forte pente et marche",
  hr_coverage: "Couverture FC", usable_running: "Temps réellement couru", grade_asymmetry: "Asymétrie de pente",
  halves: "Découpage en moitiés", steady_effort: "Effort stable", whole_activity_ef: "EF de la séance entière",
  detection: "Détection d'une montée", zigzag: "Simplification en zigzag", trim: "Rognage des extrémités",
  merge: "Fusion de montées voisines", gap_segmentation: "Trous de signal", vam_basis: "Deux VAM par montée",
  grade_classes: "Classes de pente", best_window: "Meilleures fenêtres", indicator: "Indicateur",
  reference: "Allure de référence", thresholds: "Seuils de retenue", moving_only: "Temps de mouvement seul",
  reading_gap_vs_ef: "Lire GAP et EF ensemble", mountain_long_runs: "Sorties longues en montagne",
  portions: "Premier et dernier tiers", no_steady_effort_rule: "Sans règle d'effort stable", hr_by_third: "FC par tiers",
  grade_bins: "Paniers de pente", population: "Séances retenues", walking: "Marche conservée",
  robust_stats: "Statistiques robustes", recency: "Poids de l'ancienneté", aggregation_cost: "Une valeur par séance",
  fallback: "Repli générique", smoothing: "Lissage", interpolation: "Interpolation", grade_clamp: "Bornage de la pente",
  flat_band: "Bande « plat »", classification_smoothing: "Lissage du régime", segmentation: "Segmentation",
  time_weighting: "Pondération par le temps", missing_speed: "Vitesse manquante", missing_elevation: "Altitude manquante",
  mass_linearity: "Linéarité en masse", no_exception: "Entrées incomplètes", race_pacing_integration: "Plan de course",
  delta_alert: "Seuil d'alerte d'écart", calibration: "Calibration personnelle",
  gap_basis: "Vitesses en GAP", windows_and_gaps: "Fenêtres et trous de signal",
  best_efforts_not_tests: "Meilleurs efforts, pas des tests", refusal: "Refus explicite", trend: "Tendance",
  targets: "Cibles d'intervalles", quality: "Qualité de l'ajustement", lactate_crosscheck: "Contrôle avec le seuil lactique Garmin",
};

/** Lien vers une famille d'hypothèses (`#/hypotheses?modele=<id>`), depuis n'importe quelle vue. */
function hypLink(family, text = "Hypothèses des modèles") {
  return `<a href="#/hypotheses${family ? `?modele=${family}` : ""}">${text}</a>`;
}

function hypLabel(key, family) {
  if (HYP_LABELS[key]) return HYP_LABELS[key];
  const suffix = family?.prefix && key.startsWith(family.prefix) ? key.slice(family.prefix.length) : key;
  if (HYP_SUFFIX[suffix]) return HYP_SUFFIX[suffix];
  const t = suffix.replace(/_/g, " ");
  return t.charAt(0).toUpperCase() + t.slice(1);
}

function hypGroups(assumptions) {
  const used = new Set();
  const groups = HYP_FAMILIES.map((f) => {
    const keys = f.keys ? f.keys.filter((k) => k in assumptions) : Object.keys(assumptions).filter((k) => k.startsWith(f.prefix));
    keys.forEach((k) => used.add(k));
    return { ...f, entries: keys.map((k) => ({ key: k, label: hypLabel(k, f), text: assumptions[k] })) };
  });
  const rest = Object.keys(assumptions).filter((k) => !used.has(k));
  if (rest.length) groups.push({ id: "autres", title: "Autres", entries: rest.map((k) => ({ key: k, label: hypLabel(k), text: assumptions[k] })) });
  return groups.filter((g) => g.entries.length);
}

/** Phrases d'un texte d'hypothèse : coupe après « . » suivi d'une majuscule (jamais « et al. (2002 »). */
function hypSentences(text) {
  return String(text).split(/(?<=[.!?])\s+(?=[A-ZÀ-ÖØ-Ý«])/u);
}

/** Texte échappé, `code` rendu, termes recherchés surlignés (hors balises). */
function hypInline(text, needle) {
  let html = F.esc(text).replace(/`([^`]+)`/g, "<code>$1</code>");
  if (!needle) return html;
  const re = new RegExp(needle.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"), "gi");
  return html.split(/(<[^>]+>)/).map((part) => (part.startsWith("<") ? part : part.replace(re, (m) => `<mark>${m}</mark>`))).join("");
}

/** Paragraphes d'environ 420 caractères : un bloc de 6 000 signes devient lisible sans changer un mot. */
function hypParagraphs(sentences, needle) {
  const paras = [];
  let cur = "";
  for (const sentence of sentences) {
    cur = cur ? `${cur} ${sentence}` : sentence;
    if (cur.length >= 420) { paras.push(cur); cur = ""; }
  }
  if (cur) paras.push(cur);
  return paras.map((p) => `<p>${hypInline(p, needle)}</p>`).join("");
}

function hypEntry(e, needle, open) {
  const [lead, ...rest] = hypSentences(e.text);
  const words = rest.join(" ").split(/\s+/).filter(Boolean).length;
  return `<article class="hyp" id="h-${e.key}">
    <h3 class="hyp__title">${hypInline(e.label, needle)}</h3>
    <p class="hyp__lead">${hypInline(lead, needle)}</p>
    ${rest.length ? `<details class="hyp__more"${open ? " open" : ""}><summary>Détail <span class="muted">· ${F.num(words)} mots</span></summary>${hypParagraphs(rest, needle)}</details>` : ""}
  </article>`;
}

async function viewHypotheses(params) {
  const { assumptions = {} } = await api("assumptions");
  const groups = hypGroups(assumptions);
  const total = groups.reduce((n, g) => n + g.entries.length, 0);
  if (!total) {
    main.innerHTML = `${header("Hypothèses des modèles")}${empty("Aucune hypothèse indexée", "Relancez <code>scripts/dashboard.sh --rebuild</code> : l'index se reconstruit depuis les fichiers.")}`;
    return;
  }
  // Un modèle à la fois (comme une page de documentation) : 94 hypothèses empilées faisaient
  // une page de 20 000 px. La recherche, elle, parcourt TOUS les modèles.
  const famOf = (id) => groups.find((g) => g.id === id) || groups[0];
  const st = { q: params.get("q") || "", fam: famOf(params.get("modele")).id };
  main.innerHTML = `${header("Hypothèses des modèles", `Ce que chaque calcul du tableau de bord suppose, et ses limites connues : des approximations d'entraînement, jamais des mesures. ${F.num(total)} hypothèses, regroupées par modèle.`)}
    <div class="hyp-layout">
      <nav class="hyp-toc" aria-label="Modèles">
        ${searchField("h-q", st.q, "Rechercher un terme", "Rechercher dans toutes les hypothèses")}
        <ul id="h-toc">${groups.map((g) => `<li><a href="#/hypotheses?modele=${g.id}" data-fam="${g.id}"><span>${F.esc(g.title)}</span><span class="hyp-toc__n">${g.entries.length}</span></a></li>`).join("")}</ul>
      </nav>
      <div class="hyp-body" id="h-body"></div>
    </div>`;
  const body = $("#h-body");
  const toc = $("#h-toc");
  const familyHtml = (g, entries, needle, open) => `<section class="hyp-family" id="m-${g.id}" aria-labelledby="mt-${g.id}">
      <h2 id="mt-${g.id}" tabindex="-1">${F.esc(g.title)} <span class="muted">${entries.length}</span></h2>
      ${entries.map((e) => hypEntry(e, needle, open)).join("")}</section>`;
  const render = () => {
    const needle = st.q.trim();
    const f = fold(needle);
    const qs = new URLSearchParams();
    if (f) {
      let shown = 0;
      const html = groups.map((g) => {
        const entries = g.entries.filter((e) => fold(`${e.label} ${e.text}`).includes(f));
        toc.querySelector(`[data-fam="${g.id}"] .hyp-toc__n`).textContent = entries.length;
        toc.querySelector(`[data-fam="${g.id}"]`).classList.toggle("is-empty", !entries.length);
        shown += entries.length;
        return entries.length ? familyHtml(g, entries, needle, true) : "";
      }).join("");
      body.innerHTML = `<p class="results__sum" aria-live="polite"><strong>${F.num(shown)} hypothèse${shown > 1 ? "s" : ""}</strong> sur ${F.num(total)} contiennent « ${F.esc(needle)} »</p>`
        + (html || empty("Aucune hypothèse ne contient ce terme", "Essayez un mot plus court, ou le nom d'un modèle (Banister, Minetti, Daniels…)."));
      qs.set("q", st.q);
    } else {
      const i = groups.findIndex((g) => g.id === st.fam);
      const g = groups[i];
      for (const x of groups) {
        toc.querySelector(`[data-fam="${x.id}"] .hyp-toc__n`).textContent = x.entries.length;
        toc.querySelector(`[data-fam="${x.id}"]`).classList.remove("is-empty");
      }
      const prev = groups[i - 1];
      const next = groups[i + 1];
      body.innerHTML = familyHtml(g, g.entries, "", false)
        + `<nav class="hyp-steps" aria-label="Modèle précédent ou suivant">
          ${prev ? `<a href="#/hypotheses?modele=${prev.id}" data-fam="${prev.id}" class="hyp-steps__prev">${CHEVRON.left}<span><small>Précédent</small>${F.esc(prev.title)}</span></a>` : "<span></span>"}
          ${next ? `<a href="#/hypotheses?modele=${next.id}" data-fam="${next.id}" class="hyp-steps__next"><span><small>Suivant</small>${F.esc(next.title)}</span>${CHEVRON.right}</a>` : ""}</nav>`;
      qs.set("modele", g.id);
    }
    for (const a of toc.querySelectorAll("[data-fam]")) {
      if (!f && a.dataset.fam === st.fam) {
        a.setAttribute("aria-current", "page");
        // Sommaire en rangée défilante sur téléphone : le modèle courant reste visible (jamais de défilement vertical).
        if (toc.scrollWidth > toc.clientWidth) toc.scrollLeft = a.parentElement.offsetLeft - (toc.clientWidth - a.offsetWidth) / 2;
      } else a.removeAttribute("aria-current");
    }
    history.replaceState(null, "", `#/hypotheses?${qs}`);
  };
  render();
  $("#h-q").addEventListener("input", debounce((e) => { st.q = e.target.value; render(); }));
  $(".hyp-layout").addEventListener("click", (e) => {
    const a = e.target.closest("#h-toc [data-fam], .hyp-steps [data-fam]");
    if (!a) return;
    e.preventDefault();
    const fam = a.dataset.fam;
    if (st.q.trim()) {
      // Pendant une recherche, le sommaire saute au modèle dans les résultats.
      $(`#m-${fam}`)?.scrollIntoView({ block: "start" });
      $(`#mt-${fam}`)?.focus({ preventScroll: true });
      return;
    }
    st.fam = fam;
    render();
    if (body.getBoundingClientRect().top < 0) window.scrollTo(0, 0);
    $(`#mt-${fam}`)?.focus({ preventScroll: true });
  });
}

// ---------------------------------------------------------------------------
// Vue : Matériel (#147) — chaussures, équipement (kits compris), inspections, et fiche par paire
// ---------------------------------------------------------------------------

// Synthèse « à traiter » : une entrée par paire/objet (jamais deux lignes pour le même), avec TOUTES
// ses raisons — seuil franchi, inspection conseillée. Mêmes drapeaux que les cartes détaillées
// (`alert`, `due`), jamais une seconde règle côté navigateur.
const dayYear = (iso) => `${F.dayShort(iso)} ${iso.slice(0, 4)}`;
const MONTH_FMT = new Intl.DateTimeFormat("fr-FR", { month: "short", year: "numeric" });
const monthLabel = (m) => MONTH_FMT.format(F.parseDate(`${m}-01`));
const HYPOTHESES_LINK = hypLink("materiel");

function gearAlertEntries(summary) {
  const byId = new Map();
  const add = (id, name, kind, reason) => {
    if (!byId.has(id)) byId.set(id, { id, name, kind, reasons: [] });
    byId.get(id).reasons.push(reason);
  };
  const fmtTrigger = (type, v) => (EQUIP_TRIGGER[type] || ((x) => F.num(x, 0)))(v);
  for (const sh of summary.gear?.shoes || []) {
    if (sh.alert) add(sh.gear_id, sh.name, "shoe", `seuil dépassé (${F.distance(sh.distance_m, 0)} / ${F.distance(sh.threshold_m, 0)})`);
  }
  for (const it of summary.equipment?.items || []) {
    if (!it.alert) continue;
    const reached = (it.triggers || []).filter((t) => t.reached).map((t) => `${fmtTrigger(t.type, t.value)} / ${fmtTrigger(t.type, t.threshold)}`);
    add(it.gear_id, it.name, "equipment", `seuil atteint${reached.length ? ` (${reached.join(", ")})` : ""}`);
  }
  for (const e of summary.gear_inspections?.gear || []) {
    if (e.due && !e.retired) add(e.gear_id, e.name, "shoe", "inspection conseillée");
  }
  return [...byId.values()];
}

function gearAlertsSection(summary) {
  const entries = gearAlertEntries(summary);
  if (!entries.length) return `<section class="band"><h2>À traiter</h2>${note("Rien à signaler : aucune paire ni aucun objet n'a atteint son seuil, aucune inspection n'est conseillée.")}</section>`;
  return `<section class="band"><h2>À traiter</h2><ul class="facts-list">${entries.map((e) => `<li><span class="tag">${e.kind === "shoe" ? "Chaussure" : "Équipement"}</span> ${gearLink(e.id, e.name)} — ${e.reasons.map(F.esc).join(" · ")}</li>`).join("")}</ul></section>`;
}

function gearEmptyState() {
  return `<div class="empty">
    <h3>Aucun matériel déclaré</h3>
    <p>Déclarez vos paires et votre équipement dans <code>planning/Runner_Profile.md</code>, section « Matériel & lieux » :</p>
    <pre class="empty__code"><code>### Chaussures

- Hoka Speedgoat 5 — depuis 2026-01-01 — alerte 700 km — id: speedgoat-5 (par défaut)

### Matériel

- Gilet 10 L — catégorie: gilet — alerte 1000 km — id: gilet-10l — kit: trail-long</code></pre>
    <p>Vous avez déjà des séances dans Garmin Connect ? Simulez le rattrapage du matériel de l'historique avec
    <code>python3 scripts/garmin_gear_backfill.py</code> (simulation par défaut, rien n'est écrit sans <code>--apply</code>).</p>
    <p>Détails : <a href="https://mmornati.github.io/ai-running-coach/workspace/#declarer-vos-chaussures-40" target="_blank" rel="noopener">syntaxe du profil</a>,
    <a href="https://mmornati.github.io/ai-running-coach/garmin-setup/#rattraper-le-materiel-de-lhistorique" target="_blank" rel="noopener">rattrapage Garmin</a>.</p></div>`;
}

function gearIgnoredSection(ignored) {
  if (!ignored?.length) return "";
  return `<section class="band"><h2>Paires ignorées</h2><ul class="facts-list">${ignored.map((g) => `<li>${gearLink(g.gear_id, g.name)} <span class="tag">ignorée</span></li>`).join("")}</ul>
    ${note("Matériel Garmin volontairement non suivi : ses séances ne sont attribuées à aucune paire et n'entrent dans aucun kilométrage.")}</section>`;
}

async function viewMateriel() {
  const s = SUMMARY;
  const has = (s.gear?.shoes?.length || s.gear?.unknown?.length || s.equipment?.items?.length || s.equipment?.unknown?.length || s.gear_ignored?.length);
  main.innerHTML = `${header("Matériel", `Mon matériel est-il en état ? Que dois-je remplacer ? ${HYPOTHESES_LINK}`)}
    ${has ? `${gearAlertsSection(s)}
    ${gearSection(s.gear, s.gear_inspections)}
    ${equipmentSection(s.equipment)}
    ${gearInspectionSection(s.gear_inspections)}
    ${gearIgnoredSection(s.gear_ignored)}` : gearEmptyState()}`;
}

function gearSessionsTable(sessions) {
  if (!sessions.length) return note("Aucune séance attribuée pour l'instant.");
  return `<div class="table-wrap"><table class="data data--compact">
    <thead><tr><th scope="col">Date</th><th scope="col">Séance</th><th scope="col" class="num">Distance</th></tr></thead>
    <tbody>${sessions.map((x) => `<tr${x.counted === false ? ` class="muted" title="Avant le dernier entretien : non comptée dans les déclencheurs"` : ""}><td class="nowrap">${F.dayShort(x.date)} <span class="muted">${x.date.slice(0, 4)}</span></td>
      <td><a href="#/seance/${x.id}">${F.esc(x.name || F.SPORT[x.sport] || x.sport)}</a> <span class="muted">${F.esc(F.SPORT[x.sport] || x.sport)}</span>${x.is_race ? ` <span class="tag">course</span>` : ""}</td>
      <td class="num">${x.distance_m ? F.distance(x.distance_m, 1) : "—"}</td></tr>`).join("")}</tbody></table></div>`;
}

function gearCareerFacts(d) {
  const c = d.career;
  const sh = d.shoe;
  const facts = [
    ["Kilométrage", `${F.distance(c.distance_m, 0)}${c.start_m ? `<small class="muted"> · dont ${F.distance(c.start_m, 0)} de départ</small>` : ""}`],
    ["Séances", `${F.num(c.sessions, 0)}${c.first_date ? `<small class="muted"> · du ${F.dayShort(c.first_date)} ${c.first_date.slice(0, 4)} au ${F.dayShort(c.last_date)} ${c.last_date.slice(0, 4)}</small>` : ""}`],
    ["Courses", c.races.length ? c.races.map((r) => `${F.esc(r.name || F.SPORT[r.sport] || "Course")} <small class="muted">${F.dayShort(r.date)} ${r.date.slice(0, 4)}${r.distance_m ? ` · ${F.distance(r.distance_m, 1)}` : ""}</small>`).join("<br>") : `<span class="muted">aucune</span>`],
    ...(c.longest ? [["Sortie la plus longue", `${F.distance(c.longest.distance_m, 1)} <small class="muted">${F.esc(c.longest.name || "")} · ${F.dayShort(c.longest.date)} ${c.longest.date.slice(0, 4)}</small>`]] : []),
    ...(c.best_efforts ? [["Meilleurs efforts", c.best_efforts.map((b) => `${b.km} km : ${F.clock(b.time_s)}`).join("<br>")]] : []),
  ];
  if (sh) {
    facts.push(["Seuil d'alerte", `${F.distance(sh.threshold_m, 0)}${sh.alert ? ` ${chip("gear", "orange", "À surveiller")}` : ""} ${gearForecast(sh)}`]);
    if (sh.usage) facts.push(["Usage", F.esc(sh.usage)]);
    if (sh.start_date) facts.push(["En service depuis", dayYear(sh.start_date)]);
  }
  facts.push(["Lien Garmin", d.garmin_linked ? "rattachée à Garmin Connect" : `<span class="muted">non rattachée</span>`]);
  return facts;
}

function gearShoeDetail(d) {
  const tags = `${d.retired ? ` <span class="tag">retirée</span>` : ""}${d.unknown ? ` <span class="tag">inconnue</span>` : ""}${d.shoe?.default ? ` <span class="tag">défaut</span>` : ""}`;
  if (d.ignored) {
    const ins = d.inspections?.inspections?.length ? `<section class="band"><h2>Inspections</h2><ol class="gear-inspections">${d.inspections.inspections.map(inspectionItem).join("")}</ol>${note(INSPECTION_CAVEAT)}</section>` : "";
    return { html: `${header(d.name, `Paire ignorée · ${HYPOTHESES_LINK}`)}<p><a href="#/materiel">← Matériel</a></p>
      ${note(`Cette paire est marquée <em>ignorée</em> dans le profil : ses séances ne sont attribuées à aucune paire et n'entrent dans aucun kilométrage.${d.garmin_linked ? " Elle est rattachée à Garmin Connect." : ""}`)}${ins}` };
  }
  const facts = d.unknown ? [["Kilométrage", F.distance(d.career.distance_m, 0)]] : gearCareerFacts(d);
  let chartHtml = "";
  let chart = null;
  if (d.monthly.length) {
    chart = timeChart(d.monthly.map((m) => `${m.month}-01`), [{ type: "bars", values: d.monthly.map((m) => m.distance_m / 1000), cls: "bar" }], [],
      { height: 180, y: { zero: true }, label: `Kilomètres par mois — ${d.name}`, yFormat: (v) => `${F.num(v)} km`,
        xLabels: d.monthly.map((m, i) => (i % Math.max(1, Math.ceil(d.monthly.length / 6)) === 0 ? monthLabel(m.month) : "")) });
    chartHtml = `<section class="band"><h2>Kilomètres par mois</h2><div class="chart-host" id="c-gear">${chart.svg}</div><p class="readout" id="r-gear"></p>
      ${d.career.start_m ? note("Le départ déclaré n'est pas daté : il compte dans le kilométrage total, pas dans ce graphique.") : ""}</section>`;
  }
  const insp = d.inspections;
  const inspHtml = insp && (insp.inspections.length || insp.due)
    ? `<section class="band"><h2>Inspections</h2>${insp.due ? `<p>${chip("gear", "orange", "Inspection conseillée")} <small class="muted">${insp.due_reason === "threshold_alert" ? "seuil d'alerte franchi" : insp.due_reason === "never_inspected" ? "jamais inspectée" : `${F.distance(insp.km_since_inspection_m, 0)} depuis la dernière`}</small></p>` : ""}
      ${insp.inspections.length ? `<ol class="gear-inspections">${insp.inspections.map(inspectionItem).join("")}</ol>${note(INSPECTION_CAVEAT)}` : ""}</section>` : "";
  const html = `${header(d.name, `Fiche de la paire${tags ? ` ·${tags}` : ""} · ${HYPOTHESES_LINK}`)}<p><a href="#/materiel">← Matériel</a></p>
    <dl class="facts facts--grid">${facts.map(([k, v]) => `<div><dt>${k}</dt><dd>${v}</dd></div>`).join("")}</dl>
    ${chartHtml}
    <section class="band"><h2>Séances</h2>${gearSessionsTable(d.sessions)}</section>
    ${inspHtml}`;
  return { html, chart, monthly: d.monthly };
}

function gearEquipmentDetail(d) {
  if (d.unknown) {
    const u = d.unknown_usage;
    return { html: `${header(d.gear_id, "Objet inconnu du profil")}<p><a href="#/materiel">← Matériel</a></p>
      ${note("Cet identifiant est cité dans <code>gear_ids</code> de séances mais absent de la section « Matériel » du profil (faute de frappe, objet jamais déclaré).")}
      <dl class="facts facts--grid"><div><dt>Distance</dt><dd>${F.distance(u.distance_m, 0)}</dd></div><div><dt>Durée</dt><dd>${F.hours(u.duration_s)}</dd></div><div><dt>Séances</dt><dd>${F.num(u.sessions, 0)}</dd></div></dl>
      <section class="band"><h2>Séances</h2>${gearSessionsTable(d.sessions)}</section>` };
  }
  const it = d.item;
  const tags = `${it.category ? ` <span class="tag">${F.esc(EQUIP_CATEGORY_LABEL[it.category] || it.category)}</span>` : ""}${d.retired ? ` <span class="tag">retiré</span>` : ""}`;
  const facts = [
    [it.maintenance_date ? "Usage depuis l'entretien" : "Usage", `${F.distance(it.usage.distance_m, 0)}<small class="muted"> · ${F.hours(it.usage.duration_s)} · ${F.num(it.usage.sessions, 0)} séance${it.usage.sessions > 1 ? "s" : ""}${it.usage.days != null ? ` · ${F.num(it.usage.days, 0)} j` : ""}</small>`],
    ...(it.maintenance_date ? [["Total à vie", `${F.distance(it.lifetime.distance_m, 0)}<small class="muted"> · ${F.hours(it.lifetime.duration_s)} · ${F.num(it.lifetime.sessions, 0)} séance${it.lifetime.sessions > 1 ? "s" : ""}</small>`]] : []),
    ...(it.reference_date ? [[it.maintenance_date ? "Dernier entretien" : "En service depuis", dayYear(it.reference_date)]] : []),
    ["Statut", it.alert ? chip("gear", "orange", "À surveiller") : it.near_threshold ? chip("gear", "orange", "Proche du seuil") : "en état"],
  ];
  const kits = Object.entries(d.kits || {}).map(([k, members]) => `<li>kit <strong>${F.esc(k)}</strong> : ${members.map((m) => (m.gear_id === d.gear_id ? F.esc(m.name) : gearLink(m.gear_id, m.name))).join(", ")}</li>`).join("");
  return { html: `${header(it.name, `Fiche de l'objet${tags ? ` ·${tags}` : ""} · ${HYPOTHESES_LINK}`)}<p><a href="#/materiel">← Matériel</a></p>
    <dl class="facts facts--grid">${facts.map(([k, v]) => `<div><dt>${k}</dt><dd>${v}</dd></div>`).join("")}</dl>
    <section class="band"><h2>Déclencheurs</h2><p>${equipmentTriggers(it)}</p>${it.pre_session_check ? note(`Avant la séance : ${F.esc(it.pre_session_check)}`) : ""}</section>
    ${kits ? `<section class="band"><h2>Kits</h2><ul class="facts-list">${kits}</ul></section>` : ""}
    <section class="band"><h2>Séances</h2>${gearSessionsTable(d.sessions)}${d.sessions.some((x) => x.counted === false) ? note("Les séances grisées datent d'avant le dernier entretien : non comptées dans les déclencheurs.") : ""}</section>` };
}

async function viewGearDetail(id) {
  let d;
  try {
    d = await api(`gear/${encodeURIComponent(id)}`);
  } catch (err) {
    if (/^404/.test(err.message)) {
      main.innerHTML = `${header("Matériel introuvable")}<p><a href="#/materiel">← Matériel</a></p>${empty("Aucune paire ni aucun objet avec cet identifiant", `« ${F.esc(id)} » n'est ni déclaré dans le profil, ni cité par une séance.`)}`;
      return;
    }
    throw err;
  }
  const r = d.kind === "equipment" ? gearEquipmentDetail(d) : gearShoeDetail(d);
  main.innerHTML = r.html;
  if (r.chart) attachCursor($("#c-gear"), r.chart, (i) => readout($("#r-gear"), `<strong>${F.esc(monthLabel(r.monthly[i].month))}</strong> · ${F.distance(r.monthly[i].distance_m, 0)}`));
}

// ---------------------------------------------------------------------------
// Vue : Trail Shape (#63)
// ---------------------------------------------------------------------------

// Libellés des statuts renvoyés par `/api/trail-shape` quand aucun score n'est
// calculable — jamais un statut inconnu affiché tel quel (repli sur son libellé
// brut, prudence, mais toujours accompagné des `notes` du serveur, en français,
// qui expliquent le POURQUOI précis).
const TRAIL_SHAPE_EMPTY_TITLE = {
  no_objective: "Aucun objectif actif",
  incomplete_objective: "Objectif incomplet",
  race_past: "Course déjà passée",
  race_too_short: "Course trop courte pour ce score",
};

// L'UI pilote son affichage sur le `code` STABLE de chaque note (#63, revue de
// code — jamais une sous-chaine francaise du `message`, qui casse des que deux
// notes partagent un mot comme les semaines, voir arc_trail_shape._note).
const TRAIL_SHAPE_LOW_CONFIDENCE = "low_confidence";

/** Barre de ratio composante/cible (#63) : même esprit que `rangeBar` (SVG,
 * jamais de style posé en ligne — CSP `style-src 'self'`), mais un simple
 * remplissage 0-100 % plutôt qu'une bande de référence : chaque composante a
 * SA PROPRE cible (déjà résumée par le ratio), pas de plage à visualiser. */
function trailShapeBar(ratio) {
  if (ratio === null || ratio === undefined) return "";
  const pct = Math.max(0, Math.min(1, ratio)) * 100;
  const cls = ratio >= 0.9 ? "ts-bar__fill--pos" : ratio < 0.5 ? "ts-bar__fill--neg" : "ts-bar__fill--mid";
  return `<svg class="ts-bar" viewBox="0 0 200 10" aria-hidden="true">
    <rect class="ts-bar__track" x="0" y="0" width="200" height="10" rx="5"/>
    <rect class="ts-bar__fill ${cls}" x="0" y="0" width="${pct * 2}" height="10" rx="5"/>
  </svg>`;
}

/** Formatage PAR UNITE (#63, revue de code, BLOQUANT) : `km_effort` (km-effort
 * ITRA, #35, grandeur composite distance + D+/100, jamais passee dans
 * `F.distance`, qui convertirait a tort en miles/km une valeur qui n'est deja
 * plus une distance pure) ; `m_elevation` (denivele, TOUJOURS `F.elevation`,
 * jamais `F.distance` - un D+ de 1250 m affiche via `F.distance` sortirait
 * "1,3 km", un contresens) ; `m` (distance reelle, `F.distance`) ;
 * `pct_fade` (fade GAP, #48, jamais convertible). */
function trailShapeValue(v, unit) {
  if (v === null || v === undefined) return "—";
  if (unit === "km_effort") return `${F.num(v, 1)} km-effort`;
  if (unit === "m_elevation") return F.elevation(v);
  if (unit === "m") return F.distance(v, 1);
  return `${F.num(v, 1)} %`;
}

function trailShapeComponentRow(c) {
  if (!c.eligible) {
    return `<div class="ts-row ts-row--omitted">
      <div class="ts-row__label">${F.esc(c.label)}</div>
      <div class="ts-row__omitted muted">Non intégrée au score : ${F.esc(c.reason || "non éligible")}</div>
    </div>`;
  }
  // Durabilite (#63, revue de code) : "moins on fade, mieux c'est" - jamais
  // presentee comme une "cible" a atteindre par le haut (le vocabulaire des
  // trois autres lignes), mais comme un fade observe sous un PLAFOND.
  const isDurability = c.id === "durability";
  const valuesHtml = isDurability
    ? `<span>fade ${trailShapeValue(c.actual, c.unit)} (plafond ${trailShapeValue(c.target, c.unit)})</span>`
    : `<span>${trailShapeValue(c.actual, c.unit)}</span><span class="muted"> / cible ${trailShapeValue(c.target, c.unit)}</span>`;
  // Meme vocabulaire "plafond" que la valeur ci-dessus pour la durabilite
  // (#63, revue de code, nit) - jamais "de la cible", reserve aux trois
  // autres lignes qui ont une VRAIE cible a atteindre par le haut.
  const metaRatioLabel = isDurability ? "sous le plafond" : "de la cible";
  return `<div class="ts-row">
    <div class="ts-row__label">${F.esc(c.label)}</div>
    <div class="ts-row__values">${valuesHtml}</div>
    ${trailShapeBar(c.ratio)}
    <div class="ts-row__meta muted">${F.num(c.ratio * 100, 0)} % ${metaRatioLabel} · poids ${F.num((c.weight_renormalized ?? c.weight) * 100, 0)} % du score</div>
  </div>`;
}

// Accès au roadbook imprimable (#187) depuis la zone « course » du tableau de bord.
const ROADBOOK_LINK = `<p class="rb-link"><a href="#/roadbook">Roadbook imprimable du plan de course</a> <span class="muted">— profil, passages, barrières, ravitos et matériel, à imprimer ou en PDF.</span></p>`;

async function viewTrailShape() {
  const r = await api("trail-shape");
  const sub = "Sorties longues, volume et D+ en moyenne sur les 8 dernières semaines glissantes, comparés aux exigences de l'objectif actif — un indicateur parmi d'autres, jamais un verdict.";
  if (r.status !== "ok") {
    const title = TRAIL_SHAPE_EMPTY_TITLE[r.status] || r.status;
    main.innerHTML = `${header("Trail Shape", sub)}${empty(title, (r.notes || []).map((n) => F.esc(n.message)).join("<br>") || "Pas assez d'information pour calculer ce score.")}${ROADBOOK_LINK}`;
    return;
  }
  const o = r.objective || {};
  const scoreClass = r.score >= 80 ? "pos" : r.score < 50 ? "neg" : "";
  const rows = (r.components || []).map(trailShapeComponentRow).join("");
  const confidenceNote = r.data_confidence === "low"
    ? note(F.esc((r.notes || []).find((n) => n.code === TRAIL_SHAPE_LOW_CONFIDENCE)?.message || "Confiance réduite : données éparses sur la fenêtre."))
    : "";
  const otherNotes = (r.notes || []).filter((n) => n.code !== TRAIL_SHAPE_LOW_CONFIDENCE);
  main.innerHTML = `${header("Trail Shape", sub)}
    <section class="band">
      <p class="lead-num ${scoreClass}">${F.num(r.score, 0)}<small> / 100 · ${F.esc(o.name || "objectif")}, ${F.dayLong(o.race_date)}${o.days_left >= 0 ? ` (J-${o.days_left})` : ""}</small></p>
      ${confidenceNote}
      ${otherNotes.map((n) => note(F.esc(n.message))).join("")}
    </section>
    <section class="band ts-components">${rows}</section>
    <section class="band"><h2>Formule</h2><p class="muted">${F.esc(r.formula)}</p>
      ${note("Score calculé uniquement à partir de l'historique d'entraînement (aucune donnée de santé — HRV, FC de repos, readiness — n'y entre). Aucun affûtage n'est détecté : une baisse de volume dans les dernières semaines avant la course peut simplement refléter un affûtage réussi.")}</section>
    ${ROADBOOK_LINK}`;
}

// ---------------------------------------------------------------------------
// Vue : Roadbook imprimable (#187) — sous-page de Trail Shape (zone « course »)
// ---------------------------------------------------------------------------

async function viewRoadbook(params) {
  const plan = params.get("plan");
  const r = await api(`roadbook${plan ? `?plan=${encodeURIComponent(plan)}` : ""}`, { fresh: true });
  const sub = "Une feuille par scénario : profil, sections, heures de passage, barrières, ravitos et matériel obligatoire — à imprimer ou à enregistrer en PDF.";
  if (r.status !== "ok") {
    const plans = (r.plans || []).map((p) => `<li><a href="#/roadbook?plan=${encodeURIComponent(p.path)}">${F.esc(p.race_name || p.path)}</a></li>`).join("");
    main.innerHTML = `${header("Roadbook", sub)}${empty(r.status === "no_plan" ? "Aucun plan de course" : "Plan introuvable", `${F.esc(r.message || "")}${plans ? `</p><ul>${plans}</ul><p>` : ""}`)}`;
    return;
  }
  const { html, active } = roadbookHtml(r, params.get("scenario"));
  main.innerHTML = `<div class="rb-page">${header("Roadbook", sub)}${html}</div>`;
  if (!active) return;
  wireRoadbook($(".rb-page", main), (name) => {
    const q = new URLSearchParams(location.hash.split("?")[1] || "");
    q.set("scenario", name);
    history.replaceState(null, "", `#/roadbook?${q}`);
  });
}

// ---------------------------------------------------------------------------
// Vue : Calendrier
// ---------------------------------------------------------------------------

async function viewCalendar(params) {
  const cal = await api("calendar");
  const frise = await friseSection();
  const years = Object.keys(cal.cumulative).sort();
  if (!years.length) {
    main.innerHTML = header("Calendrier") + empty("Aucune séance", "Le calendrier se remplit avec les séances indexées.");
    return;
  }
  const year = params.get("annee") || cal.today.slice(0, 4);
  const byDate = Object.fromEntries(cal.days.map((d) => [d.date, d]));
  const trail = SUMMARY.settings.sport === "trail";
  const value = (d, text) => (text ? `${F.duration(d.duration_s)}${d.distance_m ? " · " + F.distance(d.distance_m) : ""}` : d.duration_s / 60);
  const bucket = (m) => (m <= 0 ? 0 : m < 40 ? 1 : m < 75 ? 2 : m < 120 ? 3 : 4);
  const maxDoy = 366;
  const cumDates = [...Array(maxDoy)].map((_, i) => `2000-${String(Math.floor(i / 31) + 1).padStart(2, "0")}-01`);
  const cumLayers = years.slice(-3).map((y, k, arr) => {
    const pts = new Array(maxDoy).fill(null);
    let last = 0;
    const map = Object.fromEntries(cal.cumulative[y].map((p) => [p.doy, p.distance_m]));
    const lastDoy = y === cal.today.slice(0, 4) ? Math.round((F.parseDate(cal.today) - F.parseDate(`${y}-01-01`)) / 86400000) + 1 : maxDoy;
    for (let d = 1; d <= Math.min(lastDoy, maxDoy); d++) { if (map[d] !== undefined) last = map[d]; pts[d - 1] = last / 1000; }
    return { type: "line", values: pts, cls: `line line--year line--year-${arr.length - 1 - k}` };
  });
  const monthLabels = cumDates.map((_, i) => (i % 31 === 0 ? ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc."][i / 31] || "" : ""));
  const cum = timeChart(cumDates, cumLayers, [], { height: 200, y: { zero: true }, xLabels: monthLabels, label: "Distance cumulée par année", yFormat: (v) => `${F.num(v)} km` });
  main.innerHTML = `${header("Calendrier", trail ? "Intensité : durée d'effort du jour." : "Intensité : durée d'effort du jour.")}
    ${frise.html}
    <div class="toolbar">${years.map((y) => `<a class="seg ${y === year ? "is-on" : ""}" href="#/calendrier?annee=${y}">${y}</a>`).join("")}</div>
    <section class="band"><div class="chart-host chart-host--cal">${yearCalendar(Number(year), byDate, value, bucket)}</div>
      <p class="legend legend--small">Moins <span class="key cal--1"></span><span class="key cal--2"></span><span class="key cal--3"></span><span class="legend__item"><span class="key cal--4"></span>Plus (&lt; 40 min, 40–75, 75–120, &gt; 2 h)</span></p></section>
    <section class="band"><h2>Distance cumulée</h2><p class="legend">${years.slice(-3).map((y, k, arr) => `<span class="key key--year-${arr.length - 1 - k}"></span>${y}`).join(" ")}</p>
      <div class="chart-host chart-host--nox">${cum.svg}</div></section>`;
  frise.mount();
}

// ---------------------------------------------------------------------------
// Vues : Rapports, Nutrition, Fichiers
// ---------------------------------------------------------------------------

async function viewReports() {
  const { reports } = await api("reports");
  main.innerHTML = `${header("Rapports du coach")}${reports.length ? `<ul class="list">${reports.map((r) => `<li><a href="#/rapport?path=${encodeURIComponent(r.source_path)}">${F.esc(r.title)}</a><span class="list__meta">${F.dayShort(r.date)} ${r.date.slice(0, 4)} · ${F.REPORT[r.report_type] || r.report_type}${r.period_start && r.period_end && r.period_start !== r.period_end ? ` · du ${F.dayShort(r.period_start)} au ${F.dayShort(r.period_end)}` : ""}</span></li>`).join("")}</ul>`
    : empty("Aucun rapport", "Les rapports écrits par le coach dans <code>rapports/</code> apparaissent ici.")}`;
}

async function viewReport(params) {
  const r = await api(`report?path=${encodeURIComponent(params.get("path") || "")}`);
  main.innerHTML = `${header(r.title, `${F.dayLong(r.date)} · ${F.REPORT[r.report_type] || r.report_type}`)}<p><a href="#/rapports">← Tous les rapports</a></p>
    <article class="prose">${r.body_html}</article><p class="muted source">Source : <code>${F.esc(r.source_path)}</code></p>`;
}

/** Provenance d'une pesée (#222, `weight_origin` de `/api/nutrition`). */
const WEIGHT_ORIGIN_LABEL = { garmin: "Garmin", athlete: "déclarée" };

/** Section « Poids » de la vue Nutrition (#36) : points quotidiens (fusion santé/nutrition,
 * santé prioritaire — voir `ASSUMPTIONS["weight_merge"]` côté serveur), moyenne mobile 7 j
 * et cible. Chiffres seulement, aucun commentaire normatif sur le poids (issue #36).
 */
function weightSection(weightSeries, weight) {
  if (!weightSeries.some((p) => p.weight_kg_merged != null)) return { html: "", chart: null };
  const dates = weightSeries.map((p) => p.date);
  const marks = weight.target_kg != null
    ? [{ type: "hline", value: weight.target_kg, cls: "mark mark--target", label: `Cible ${F.weight(weight.target_kg)}` }]
    : [];
  // Provenance (#222) : pesée Garmin = disque plein, pesée déclarée = anneau creux — la forme
  // distingue les deux séries sans dépendre de la couleur.
  const pick = (origin) => weightSeries.map((p) => (p.weight_origin === origin ? p.weight_kg_merged : null));
  const hasGarmin = weightSeries.some((p) => p.weight_origin === "garmin");
  const hasDeclared = weightSeries.some((p) => p.weight_origin === "athlete");
  const chart = timeChart(dates, [
    { type: "line", values: weightSeries.map((p) => p.weight_avg7_kg), cls: "line line--weight-avg" },
    { type: "dots", values: pick("garmin"), cls: "dot dot--weight" },
    { type: "dots", values: pick("athlete"), cls: "dot dot--weight-declared" },
  ], marks, { height: 200, label: "Poids quotidien (pesées Garmin et déclarées), moyenne mobile 7 jours et cible", yFormat: (v) => F.weight(v) });
  const gapTxt = weight.gap_kg != null ? `${weight.gap_kg > 0 ? "+" : ""}${F.weight(weight.gap_kg)}` : "—";
  const slopeTxt = weight.slope_kg_per_week != null ? `${weight.slope_kg_per_week > 0 ? "+" : ""}${F.weightRate(weight.slope_kg_per_week)}` : "—";
  // `avg7_kg` (et `gap_kg`, qui en dérive) est TOUJOURS la valeur du jour même (jamais la
  // dernière moyenne non nulle trouvée plus tôt dans la fenêtre, voir arc_serve.py) : un
  // « — » ici signifie « pas assez de pesées récentes », pas une absence de data ancienne.
  const latest = weight.latest;
  const latestTxt = latest ? `${F.weight(latest.weight_kg)}<small> au ${F.dayShort(latest.date)} · ${WEIGHT_ORIGIN_LABEL[latest.origin] || "—"}</small>` : "—";
  const avg7Txt = weight.avg7_kg != null ? `${F.weight(weight.avg7_kg)}<small> au ${F.dayShort(weight.avg7_date)}</small>` : "—";
  const html = `<section class="band"><h2>Poids</h2>
    <p class="legend">${hasGarmin ? `<span class="legend__item"><span class="key key--weight"></span>Pesée Garmin</span> ` : ""}${hasDeclared ? `<span class="legend__item"><span class="key key--weight-declared"></span>Pesée déclarée</span> ` : ""}<span class="legend__item"><span class="key key--weight-avg"></span>Moyenne 7 j</span>${weight.target_kg != null ? ` <span class="legend__item"><span class="key key--target"></span>Cible</span>` : ""}</p>
    <div class="chart-host" id="c-weight">${chart.svg}</div><p class="readout" id="r-weight"></p>
    <dl class="facts facts--inline">
      <div><dt>Dernière pesée</dt><dd>${latestTxt}</dd></div>
      <div><dt>Moyenne 7 j</dt><dd>${avg7Txt}</dd></div>
      <div><dt>Cible</dt><dd>${F.weight(weight.target_kg)}</dd></div>
      <div><dt>Écart à la cible</dt><dd>${gapTxt}</dd></div>
      <div><dt>Pente 4 semaines</dt><dd>${slopeTxt}</dd></div>
    </dl></section>`;
  return { html, chart };
}

/** Section « Glucides & sudation » de la vue Nutrition (#41), entraînement digestif :
 * un point par sortie longue (> 90 min) — glucides/h (axe principal) et taux de
 * sudation quand pesé (axe secondaire, `sweat_rate_l_h` déjà dérivé à l'indexation,
 * jamais recalculé ici) — plus une bande de repère générique 60-90 g/h (documentaire,
 * pas une cible normative) et le meilleur débit observé sur la fenêtre. Chiffres
 * seulement, comme la section « Poids » ci-dessus (#36) : aucun avis sur ce qu'il
 * faudrait manger.
 */
function fuelingSection(fueling) {
  const points = fueling.points.filter((p) => p.carbs_per_hour_g != null || p.sweat_rate_l_h != null);
  if (!points.length) return { html: "", chart: null };
  // Abscisses espacées RÉGULIÈREMENT par indice (`timeChart` sans `xLabels`, comme le
  // volume hebdomadaire) — pas à l'échelle réelle du calendrier : deux sorties longues
  // rapprochées de trois jours et deux espacées de trois semaines occupent la même
  // largeur. Assumé délibérément ici (revue de code #41, nit) : les sorties longues
  // sont trop peu nombreuses et trop irrégulières (une par semaine dans le meilleur
  // des cas) pour qu'un axe temporel continu reste lisible sans écraser les points
  // récents dans un coin — documenté plutôt que « corrigé » par un axe réel.
  const dates = points.map((p) => p.date);
  const [lo, hi] = fueling.target_band_g_h;
  const marks = fueling.carbs_ceiling_g_h != null
    ? [{ type: "hline", value: fueling.carbs_ceiling_g_h, cls: "mark mark--carbs-ceiling", label: `Plafond course ${F.carbsRate(fueling.carbs_ceiling_g_h)}` }]
    : [];
  const chart = timeChart(dates, [
    { type: "band", lo: dates.map(() => lo), hi: dates.map(() => hi), cls: "band-fill" },
    { type: "dots", values: points.map((p) => p.carbs_per_hour_g), cls: "dot dot--carbs" },
    // Sudation en `dots` (jamais `line`) : les sorties longues ne sont pas toutes pesées, donc
    // cette série est CRIBLÉE de trous — `pathFrom` (chart.js) coupe une ligne à chaque `null`
    // et un point non-`null` isolé entre deux `null` (aucun voisin immédiat) génère un simple
    // « M » sans « L » à la suite, un sous-tracé d'un seul point qu'aucun navigateur ne rend
    // (revue de code #41). Un point par sortie pesée reste visible même isolé ; anneau creux
    // (voir `.dot--sweat` CSS) plutôt qu'un disque plein, pour rester distinct des points
    // glucides/h au premier coup d'œil, y compris en niveaux de gris.
    { type: "dots", values: points.map((p) => p.sweat_rate_l_h), cls: "dot dot--sweat", axis: "y2", r: 3.2 },
  ], marks, {
    height: 200, y: { zero: true }, y2: { zero: true }, label: "Glucides par heure et taux de sudation, sorties longues",
    yFormat: (v) => F.carbsRate(v), y2Format: (v) => F.sweatRate(v),
  });
  const maxTxt = fueling.max_carbs_per_hour_g != null
    ? `${F.carbsRate(fueling.max_carbs_per_hour_g)}<small> sur ${fueling.carbs_per_hour_n} sortie${fueling.carbs_per_hour_n > 1 ? "s" : ""}</small>` : "—";
  const medianTxt = fueling.median_sweat_rate_l_h != null
    ? `${F.sweatRate(fueling.median_sweat_rate_l_h)}<small> sur ${fueling.sweat_rate_n} sortie${fueling.sweat_rate_n > 1 ? "s" : ""}</small>` : "—";
  const html = `<section class="band"><h2>Glucides &amp; sudation</h2>
    <p class="muted">Repère indicatif ${F.carbsRate(lo)} – ${F.carbsRate(hi)}, pas une cible normative — le plafond réaliste d'un plan de course est le meilleur débit observé ci-dessous, plus une marge de progression documentée.</p>
    <p class="legend"><span class="legend__item"><span class="key key--band"></span>Repère 60-90 g/h</span> <span class="legend__item"><span class="key key--carbs"></span>Glucides/h</span> <span class="legend__item"><span class="key key--sweat"></span>Sudation</span>${fueling.carbs_ceiling_g_h != null ? ` <span class="legend__item"><span class="key key--carbs-ceiling"></span>Plafond course</span>` : ""}</p>
    <div class="chart-host" id="c-fueling">${chart.svg}</div><p class="readout" id="r-fueling"></p>
    <dl class="facts facts--inline">
      <div><dt>Sorties longues (${fueling.window_weeks} sem.)</dt><dd>${F.num(fueling.long_runs)}</dd></div>
      <div><dt>Débit maximal observé</dt><dd>${maxTxt}</dd></div>
      <div><dt>Sudation médiane</dt><dd>${medianTxt}</dd></div>
    </dl></section>`;
  return { html, chart, points };
}

/** Section « Découplage aérobie » de la vue Analyse (#45, #50) : un point par sortie
 * longue (> `arc_metrics.LONG_RUN_MIN_DURATION_S`, 90 min) éligible (course à pied,
 * ≥ 60 min de mouvement, effort jugé stable — `arc_decoupling.ASSUMPTIONS`), Pa:HR
 * en pourcentage. Repère indicatif à 5 % (coaching endurance/ultra courant, pas un
 * seuil validé cliniquement — voir docs/marques.md), jamais présenté comme une
 * norme. Abscisses espacées par indice, comme `fuelingSection` (#41) : les sorties
 * longues sont trop irrégulières pour un axe temporel continu lisible. */
function decouplingSection(trend) {
  const points = trend.points.filter((p) => p.decoupling_pct != null);
  if (!points.length) return { html: "", chart: null, points: [] };
  const dates = points.map((p) => p.date);
  const chart = timeChart(dates, [
    { type: "dots", values: points.map((p) => p.decoupling_pct), cls: "dot dot--decoupling" },
  ], [
    // Revue de code (#47) : un repère `hline` va dans `marks` (3e argument), jamais
    // dans `layers` (2e) — `timeChart` (web/js/chart.js) n'y reconnaît que
    // "line"/"area"/"band"/"bars"/"dots" et ignore silencieusement tout le reste, y
    // compris un `hline` glissé par erreur : le repère « 5 % » n'était donc jamais
    // dessiné.
    { type: "hline", value: 5, cls: "mark mark--decoupling-good", label: "Repère 5 %" },
  ], {
    height: 200, y: { zero: true }, label: "Découplage aérobie (Pa:HR) sur les sorties longues",
    yFormat: (v) => `${F.num(v, 1)} %`,
  });
  const html = `<section class="band"><h2>Découplage aérobie (Pa:HR)</h2>
    <p class="muted">Dérive de la fréquence cardiaque à allure ajustée (GAP) constante entre les deux
      moitiés d'une sortie longue. Sous 5 %, repère de coaching courant en endurance/ultra pour une
      bonne durabilité aérobie — pas un seuil validé cliniquement.
      ${hypLink("decouplage")}</p>
    <p class="legend"><span class="legend__item"><span class="key key--decoupling"></span>Découplage mesuré</span></p>
    <div class="chart-host" id="c-decoupling">${chart.svg}</div><p class="readout" id="r-decoupling"></p>
    <dl class="facts facts--inline">
      <div><dt>Sorties longues (${trend.window_weeks} sem.)</dt><dd>${F.num(trend.long_runs)}</dd></div>
      <div><dt>Découplage moyen</dt><dd>${trend.avg_decoupling_pct != null ? `${F.num(trend.avg_decoupling_pct, 1)} %<small class="muted"> sur ${trend.measured_n} sortie${trend.measured_n > 1 ? "s" : ""}</small>` : "—"}</dd></div>
    </dl></section>`;
  return { html, chart, points };
}

/** Section « VAM » (vitesse ascensionnelle, #46) de la vue Analyse (#50) : un point par
 * séance de la famille course à pied où au moins une montée a été détectée
 * (D+ minimal et pente minimale, voir `arc_climb.ASSUMPTIONS`) — meilleure VAM
 * (temps écoulé) de la séance. Vide (pas de section) tant qu'aucune montée n'a
 * jamais été détectée (parcours plats, ou pas encore de séance en relief) —
 * même motif que `decouplingSection`/`fuelingSection` : abscisses espacées par
 * indice, pas un axe temporel continu (les montées sont trop irrégulières). */
function vamSection(trend) {
  const points = trend.points.filter((p) => p.best_climb_vam_elapsed_m_h != null);
  if (!points.length) return { html: "", chart: null, points: [] };
  const dates = points.map((p) => p.date);
  const chart = timeChart(dates, [
    { type: "dots", values: points.map((p) => p.best_climb_vam_elapsed_m_h), cls: "dot dot--vam" },
  ], [], {
    height: 200, y: { zero: true }, label: "Meilleure VAM par sortie (vitesse ascensionnelle)",
    yFormat: (v) => F.vam(v),
  });
  const best10 = Math.max(...points.map((p) => p.vam_best_10min_m_h || 0)) || null;
  const best20 = Math.max(...points.map((p) => p.vam_best_20min_m_h || 0)) || null;
  const html = `<section class="band"><h2>VAM (vitesse ascensionnelle)</h2>
    <p class="muted">Gain d'altitude / durée sur les montées détectées (D+ et pente minimaux,
      trous de signal jamais franchis). Deux VAM existent par montée (temps écoulé/temps de
      mouvement, une pause n'est pas comptée deux fois) ; le point ici est le temps écoulé,
      la valeur la plus simple à interpréter. ${hypLink("vam")}</p>
    <p class="legend"><span class="legend__item"><span class="key key--vam"></span>Meilleure montée de la sortie</span></p>
    <div class="chart-host" id="c-vam">${chart.svg}</div><p class="readout" id="r-vam"></p>
    <dl class="facts facts--inline">
      <div><dt>Sorties avec montée (${trend.window_weeks} sem.)</dt><dd>${F.num(trend.with_climb_n)} <small class="muted">/ ${F.num(trend.activities_n)}</small></dd></div>
      <div><dt>Meilleure VAM 10 min</dt><dd>${best10 != null ? F.vam(best10) : "—"}</dd></div>
      <div><dt>Meilleure VAM 20 min</dt><dd>${best20 != null ? F.vam(best20) : "—"}</dd></div>
    </dl></section>`;
  return { html, chart, points };
}

/** Section « Efficacité en descente » (#47) de la vue Analyse (#50) : UNE SÉRIE PAR
 * CLASSE DE PENTE, jamais un mélange (revue de code, should-fix 2, BLOQUANT) —
 * l'indicateur n'a de sens qu'« à pente égale » (voir
 * `arc_descent.ASSUMPTIONS["indicator"]`), donc le graphique affiche la classe
 * choisie par le sélecteur (`?descente=<classe>` dans l'URL, comme les
 * périodes de la courbe de forme) et JAMAIS une moyenne toutes classes
 * confondues, qui mélangerait des pentes différentes d'une sortie à l'autre —
 * `trend.activities[].avg_efficiency_all_classes` (arc_metrics.descent_trend)
 * existe côté API mais n'est délibérément PAS affiché en graphique ici pour
 * cette raison, seul `trend.classes` (le détail par classe) alimente cette
 * vue. Classe par défaut : celle qui a le plus de points dans la fenêtre.
 * Vide (pas de section) tant qu'aucune classe n'a jamais été retenue. */
function descentTrendSection(trend, weeks, selectedClass) {
  const classes = trend.classes || {};
  const labels = DESCENT_GRADE_CLASS_ORDER.filter((cls) => classes[cls] && classes[cls].count);
  if (!labels.length) return { html: "", chart: null, points: [] };
  const active = labels.includes(selectedClass)
    ? selectedClass
    : labels.slice().sort((a, b) => classes[b].count - classes[a].count)[0];
  const points = classes[active].points.filter((p) => p.efficiency != null);
  // La référence peut venir de deux sources DIFFÉRENTES d'une séance à l'autre
  // (`arc_descent.ASSUMPTIONS["reference"]`) — le plat de LA séance (`"flat"`),
  // ou son repli hors forte descente (`"non_descent"`) quand elle n'a pas assez
  // de plat. Les deux ne sont PAS sur la même échelle (revue de code : mesuré
  // 0,664 en `flat` contre 0,548 en `non_descent` pour la MÊME descente) —
  // JAMAIS tracées comme un seul point de même nature, sous peine de lire une
  // chute d'efficacité là où seule la référence a changé de source. Repli
  // affiché en anneau creux (même motif que `.dot--sweat`), avec sa propre
  // légende, plutôt qu'exclu : la donnée reste réelle, juste moins fiable.
  const flatValues = points.map((p) => (p.reference_source === "flat" ? p.efficiency : null));
  const fallbackValues = points.map((p) => (p.reference_source === "non_descent" ? p.efficiency : null));
  const fallbackCount = fallbackValues.filter((v) => v != null).length;
  const selector = labels.map((cls) =>
    `<a class="seg ${cls === active ? "is-on" : ""}" aria-current="${cls === active ? "true" : "false"}" href="#/analyse?semaines=${weeks}&descente=${encodeURIComponent(cls)}">${F.esc(cls)}</a>`
  ).join("");
  const chart = points.length ? timeChart(points.map((p) => p.date), [
    { type: "dots", values: flatValues, cls: "dot dot--descent" },
    { type: "dots", values: fallbackValues, cls: "dot dot--descent-fallback" },
  ], [
    // `hline` va dans `marks` (3e argument), jamais dans `layers` (2e) — voir le
    // même correctif sur `decouplingSection` ci-dessus.
    { type: "hline", value: 1, cls: "mark mark--descent-model", label: "1,00×" },
  ], {
    height: 200, label: `Efficacité en descente, classe ${active}`,
    yFormat: (v) => F.efficiency(v),
  }) : null;
  const classLegend = labels.map((cls) =>
    `<span class="legend__item">${F.esc(cls)} : ${F.efficiency(classes[cls].avg_efficiency)} <small class="muted">(${classes[cls].count})</small></span>`
  ).join(" · ");
  const html = `<section class="band"><h2>Efficacité en descente</h2>
    <p class="muted">Vitesse en descente comparée à celle prédite par le modèle de Minetti à partir de
      l'allure GAP de référence de la séance (<strong>1,00×</strong> = effort métabolique constant,
      repère pointillé). Le modèle surestime le bénéfice des fortes descentes en conditions réelles de
      trail : une valeur sous 1,00× sur les pentes les plus raides est normale, pas un mauvais résultat —
      seule la <strong>tendance, à pente égale</strong>, est exploitable : une classe de pente ne se
      compare JAMAIS à une autre. ${hypLink("descente")}</p>
    <div class="toolbar">${selector}</div>
    <p class="legend"><span class="legend__item"><span class="key key--descent"></span>Référence plate de la séance</span> <span class="legend__item"><span class="key key--descent-fallback"></span>Référence de repli (hors forte descente, pas de plat suffisant)</span></p>
    ${chart ? `<div class="chart-host" id="c-descent">${chart.svg}</div><p class="readout" id="r-descent"></p>` : note("Pas assez de points pour cette classe.")}
    ${fallbackCount ? `<p class="muted"><small>${fallbackCount} point${fallbackCount > 1 ? "s" : ""} en anneau creux : référence de repli, échelle différente d'un point plein — ne pas comparer directement.</small></p>` : ""}
    <p class="legend legend--small">Efficacité moyenne par classe de pente (${trend.window_weeks} sem.) : ${classLegend}</p>
  </section>`;
  return { html, chart, points };
}

/** Section « Durabilité » (#48) de la vue Analyse (#50) : un point par sortie longue
 * (> `arc_metrics.LONG_RUN_MIN_DURATION_S`, 90 min) éligible (course à pied,
 * échauffement exclu puis trois tiers de mouvement égaux, portions/FC suffisantes
 * sur le premier ET le dernier tiers, pente comparable entre les deux —
 * `arc_durability.ASSUMPTIONS`), fade GAP et fade EF entre le premier et le
 * dernier tiers, en pourcentage. Repère à 0 % (aucune baisse mesurée) — une
 * valeur POSITIVE signale un ralentissement en fin de sortie (fade), jamais une
 * amélioration. Fade EF en anneau creux DESSINÉ EN PREMIER (revue de code #48,
 * should-fix 1 : `fill: var(--surface)` dessiné APRÈS masquait totalement le
 * point GAP dès que les deux fades sont proches — voir `web/css/app.css`,
 * `.dot--durability-ef`) : le point GAP plein reste toujours visible par-dessus.
 * Abscisses espacées par INDICE (pas par date réelle, voir `web/js/chart.js::x`),
 * même motif que `decouplingSection` (#45) : les sorties longues sont trop
 * irrégulières dans le temps pour qu'un axe continu reste lisible. Revue de
 * code #48, should-fix 2 : une bonne part des sorties longues en montagne (voir
 * `arc_durability.ASSUMPTIONS["mountain_long_runs"]`) est STRUCTURELLEMENT
 * inéligible — quand `trend.long_runs > 0` mais `trend.measured_n === 0`, la
 * section reste affichée avec un message (raison dominante) au lieu de
 * disparaître silencieusement ; elle ne disparaît QUE si `trend.long_runs === 0`
 * (aucune sortie longue du tout dans la fenêtre). */
function durabilitySection(trend) {
  if (!trend.long_runs) return { html: "", chart: null, points: [] };
  const points = trend.points.filter((p) => p.gap_fade_pct != null);
  if (!points.length) {
    const html = `<section class="band"><h2>Durabilité</h2>
      <p class="muted">Baisse de performance en fin de sortie longue : allure ajustée à la pente (GAP) et
        facteur d'efficacité (EF = GAP/FC) du dernier tiers de la sortie comparés au premier tiers.
        ${hypLink("durabilite")}</p>
      ${note(`${F.num(trend.long_runs)} sortie${trend.long_runs > 1 ? "s" : ""} longue${trend.long_runs > 1 ? "s" : ""}, aucune éligible${trend.dominant_reason ? ` — ${F.esc(trend.dominant_reason)}` : ""}.`)}
      </section>`;
    return { html, chart: null, points: [] };
  }
  const dates = points.map((p) => p.date);
  const chart = timeChart(dates, [
    // EF (anneau creux) dessiné EN PREMIER, GAP (point plein) par-dessus — voir
    // le docstring ci-dessus (revue de code #48, should-fix 1) : l'ordre inverse
    // masquait totalement le point GAP quand les deux fades sont proches.
    { type: "dots", values: points.map((p) => p.ef_fade_pct), cls: "dot dot--durability-ef", r: 3.4 },
    { type: "dots", values: points.map((p) => p.gap_fade_pct), cls: "dot dot--durability-gap" },
  ], [
    // `hline` va dans `marks` (3e argument), jamais dans `layers` (2e) — voir le
    // correctif de #47 sur `decouplingSection`/`descentTrendSection`.
    { type: "hline", value: 0, cls: "mark mark--durability-zero" },
  ], {
    height: 200, label: "Fade GAP/EF (dernier tiers vs premier tiers) sur les sorties longues",
    yFormat: (v) => `${F.num(v, 1)} %`,
  });
  const html = `<section class="band"><h2>Durabilité</h2>
    <p class="muted">Baisse de performance en fin de sortie longue : allure ajustée à la pente (GAP) et
      facteur d'efficacité (EF = GAP/FC) du dernier tiers de la sortie (temps de mouvement, échauffement
      exclu), comparés au premier tiers. Une valeur POSITIVE signale un ralentissement en fin de sortie ;
      négative ou nulle, pas de baisse mesurable. Repère de coaching indicatif, pas un seuil validé
      cliniquement, ni un lien démontré avec la tenue en ultra. <strong>Fade EF nettement supérieur au
      fade GAP</strong> : dérive cardiaque à allure comparable. <strong>Fade GAP marqué, fade EF proche de
      0</strong> : allure et FC ont baissé ensemble (effort réellement réduit). Sans règle d'effort
      stable : une accélération finale, un fartlek ou des intervalles en fin de sortie longue faussent la
      lecture. ${hypLink("durabilite")}</p>
    <p class="legend"><span class="legend__item"><span class="key key--durability-gap"></span>Fade GAP</span> <span class="legend__item"><span class="key key--durability-ef"></span>Fade EF</span></p>
    <div class="chart-host" id="c-durability">${chart.svg}</div><p class="readout" id="r-durability"></p>
    <dl class="facts facts--inline">
      <div><dt>Sorties longues (${trend.window_weeks} sem.)</dt><dd>${F.num(trend.long_runs)} <small class="muted">dont ${trend.measured_n} éligible${trend.measured_n > 1 ? "s" : ""}</small></dd></div>
      <div><dt>Fade GAP moyen</dt><dd>${trend.avg_gap_fade_pct != null ? `${trend.avg_gap_fade_pct > 0 ? "+" : ""}${F.num(trend.avg_gap_fade_pct, 1)} %<small class="muted"> sur ${trend.measured_n} sortie${trend.measured_n > 1 ? "s" : ""}</small>` : "—"}</dd></div>
    </dl></section>`;
  return { html, chart, points };
}

/** Section « Dépense énergétique » de la vue Analyse : écart modèle vs Garmin
 * (%) par séance éligible (famille course à pied, échantillon FIT ingéré ET
 * poids connu à la date — voir `arc_energy.ASSUMPTIONS`), sur la fenêtre de la
 * vue. `trend` vient de `/api/energy-trend` (`arc_serve.py::api_energy_trend`,
 * qui délègue ENTIÈREMENT à `arc_index.energy_trend` — même fonction que
 * `/api/activity/<id>.energy` : le delta est déjà calculé côté serveur, jamais
 * recalculé ici).
 *
 * Bande grisée ±`trend.delta_alert_pct` (`arc_energy.DELTA_ALERT_PCT`, servie par
 * l'API — JAMAIS une valeur recopiée en dur ici, contrairement à
 * `ENERGY_BREAKDOWN_ORDER` ci-dessus : un seuil numérique qui divergerait entre
 * le serveur et l'affichage serait trompeur, alors qu'un ORDRE de libellés ne
 * peut que rester incomplet au pire) : au-delà, l'écart est notable — un signal
 * de contrôle du modèle, jamais un verdict sur la séance elle-même. Garmin reste
 * la référence par défaut PARTOUT AILLEURS (nutrition, rapports) ; ce graphique
 * sert uniquement à suivre la fidélité du modèle dans le temps.
 *
 * Route et trail sont deux séries DISTINCTES (plein pour le trail, creux pour la
 * route — même motif que `durabilitySection`, EF creux/GAP plein) : les deux
 * biais mesurés par la validation de référence diffèrent (route ±6 %, trail
 * +3/+5 %, voir `arc_energy.ASSUMPTIONS`/`docs/marques.md`) — les confondre sous
 * un même point masquerait cette différence. Randonnée/marche (aussi éligibles,
 * `arc_index.ENERGY_ELIGIBLE_SPORTS`) restent HORS de ce graphique comme du
 * calcul de médiane, sans référence de validation connue pour les distinguer
 * visuellement à leur tour — comptées quand même dans `sessions_n`/`measured_n`
 * ci-dessous, qui ne dépendent pas des points réellement tracés.
 *
 * Abscisses espacées par indice (même motif que `fuelingSection`/
 * `decouplingSection` ci-dessus) : une séance éligible dépend d'un échantillon
 * FIT ingéré ET d'un poids connu à sa date, deux conditions qui la rendent trop
 * irrégulière pour un axe temporel continu lisible.
 *
 * Ligne de faits « Calibration personnelle » : statut par panier route/trail
 * (`trend.calibration.buckets`, `arc_index.energy_calibration`) — appliquée
 * UNIQUEMENT aux PRÉVISIONS de course (`arc_race_pacing`), JAMAIS à ce graphique
 * lui-même (qui reste le delta BRUT modèle/Garmin). Sur SA PROPRE fenêtre
 * (`trend.calibration.window_weeks`, 26 semaines par défaut), INDÉPENDANTE de
 * `trend.window_weeks` (celle du graphique, souvent plus courte, choisie par
 * l'athlète) — jamais confondues dans le libellé affiché. */
function energyTrendSection(trend) {
  const points = (trend.sessions || []).filter((s) => s.delta_pct != null && (s.sport === "trail" || s.sport === "running"));
  const band = trend.delta_alert_pct;
  // Calibration personnelle (prévisions UNIQUEMENT, jamais ce graphique lui-même — voir
  // `arc_energy.ASSUMPTIONS["calibration"]`) : ligne de FAITS sobre, un statut par panier,
  // jamais une action à faire par l'athlète (la calibration s'applique d'elle-même dans
  // `arc_race_pacing`, rien à configurer ici). `trend.calibration` porte sa PROPRE fenêtre
  // (`arc_energy.CALIBRATION_WINDOW_WEEKS`, 26 semaines), INDÉPENDANTE de `trend.window_weeks`
  // (celle de CE graphique, souvent plus courte, choisie par l'athlète) — jamais confondues dans
  // le libellé. Affichée MÊME quand la fenêtre COURTE du graphique (`points`) est vide : les deux
  // fenêtres sont indépendantes, une calibration sur 26 semaines peut très bien exister alors que
  // les 8/12 dernières semaines choisies pour LE GRAPHIQUE n'ont aucune séance mesurable.
  const CALIBRATION_STATUS_LABEL = {
    insufficient: "échantillon insuffisant", not_needed: "non nécessaire", applied: "appliquée",
  };
  const calibrationTxt = (bucket) => {
    if (!bucket) return "—";
    const label = CALIBRATION_STATUS_LABEL[bucket.status] || bucket.status;
    const factor = bucket.status === "applied" ? ` · facteur ${F.num(bucket.factor, 2)}` : "";
    return `${label}${factor} <small class="muted">(n=${F.num(bucket.n)})</small>`;
  };
  const calibration = trend.calibration || {};
  const calibrationBuckets = calibration.buckets || {};
  const hasCalibrationData = ["route", "trail"].some((b) => (calibrationBuckets[b] || {}).n > 0);
  const calibrationHtml = `<p class="legend">Calibration personnelle des prévisions de course
      (${F.num(calibration.window_weeks)} sem.) — route : ${calibrationTxt(calibrationBuckets.route)} ·
      trail : ${calibrationTxt(calibrationBuckets.trail)} ${hypLink("energie", "détail")}</p>`;

  if (!points.length) {
    // Fenêtre COURTE du graphique vide : pas de courbe possible, mais la ligne de
    // calibration (fenêtre longue, indépendante) reste affichée si elle a quelque chose
    // à dire — jamais masquée par l'absence de points récents à tracer.
    if (!hasCalibrationData) return { html: "", chart: null, points: [] };
    const html = `<section class="band"><h2>Dépense énergétique (modèle vs Garmin)</h2>
      <p class="muted">Garmin (<code>calories_kcal</code>) reste la référence partout ailleurs
        (nutrition, rapports) ; aucune séance mesurable sur la fenêtre choisie ici, mais la
        calibration personnelle des prévisions (fenêtre plus longue, indépendante) reste
        disponible ci-dessous.</p>
      ${calibrationHtml}</section>`;
    return { html, chart: null, points: [] };
  }

  const dates = points.map((p) => p.date);
  const chart = timeChart(dates, [
    { type: "band", lo: dates.map(() => -band), hi: dates.map(() => band), cls: "band-fill" },
    { type: "dots", values: points.map((p) => (p.sport === "trail" ? p.delta_pct : null)), cls: "dot dot--energy" },
    { type: "dots", values: points.map((p) => (p.sport === "running" ? p.delta_pct : null)), cls: "dot dot--energy-route" },
  ], [
    // `hline` va dans `marks` (3e argument), jamais dans `layers` (2e) — voir le
    // correctif de #47 sur `decouplingSection`/`descentTrendSection`.
    { type: "hline", value: 0, cls: "mark mark--zero", label: "0 %" },
  ], {
    height: 200, y: { zero: true }, label: "Écart modèle vs Garmin sur la dépense énergétique",
    yFormat: (v) => `${F.num(v, 0)} %`,
  });
  const median = trend.delta_median_pct || {};
  const medianTxt = (v) => (v != null ? `${v > 0 ? "+" : ""}${F.num(v, 1)} %` : "—");
  const html = `<section class="band"><h2>Dépense énergétique (modèle vs Garmin)</h2>
    <p class="muted">Garmin (<code>calories_kcal</code>) reste la référence partout ailleurs (nutrition,
      rapports) ; ce graphique suit la fidélité du modèle indépendant (RE3 course + marche de Minetti)
      dans le temps — un écart mis en évidence au-delà de ±${F.num(band)} % (bande grisée) n'est jamais
      un verdict sur la séance, seulement un signal de contrôle du modèle.
      ${hypLink("energie")}</p>
    <p class="legend"><span class="legend__item"><span class="key key--band"></span>Repère ±${F.num(band)} %</span> <span class="legend__item"><span class="key key--energy"></span>${F.SPORT.trail}</span> <span class="legend__item"><span class="key key--energy-route"></span>${F.SPORT.running}</span></p>
    <div class="chart-host" id="c-energy">${chart.svg}</div><p class="readout" id="r-energy"></p>
    <dl class="facts facts--inline">
      <div><dt>Séances (${trend.window_weeks} sem.)</dt><dd>${F.num(trend.sessions_n)} <small class="muted">dont ${F.num(trend.measured_n)} avec un écart calculable</small></dd></div>
      <div><dt>Écart médian route</dt><dd>${medianTxt(median.route)}</dd></div>
      <div><dt>Écart médian trail</dt><dd>${medianTxt(median.trail)}</dd></div>
    </dl>
    ${calibrationHtml}</section>`;
  return { html, chart, points };
}

async function viewNutrition() {
  const [{ days, weight_series, weight }, fueling] = await Promise.all([api("nutrition?days=180"), api("fueling")]);
  const weighed = days.filter((d) => d.weight_kg != null || d.intake_kcal != null);
  const { html: weightHtml, chart: weightChart } = weightSection(weight_series, weight);
  const { html: fuelingHtml, chart: fuelingChart, points: fuelingPoints } = fuelingSection(fueling);
  if (!weighed.length && !weightChart && !fuelingChart) {
    main.innerHTML = header("Nutrition") + empty("Pas encore de suivi chiffré", "Les journaux <code>nutrition/</code> et <code>medical/</code> au contrat (apports, macros, poids) alimentent cette vue.");
    return;
  }
  const table = weighed.length ? `<div class="table-wrap"><table class="data"><thead><tr><th scope="col">Date</th><th scope="col" class="num">Poids</th><th scope="col" class="num">Cible</th><th scope="col" class="num">Apports</th><th scope="col" class="num">Dépense</th><th scope="col" class="num">G / P / L</th></tr></thead>
    <tbody>${days.slice().reverse().map((d) => `<tr><td>${F.dayShort(d.date)}</td><td class="num">${F.weight(d.weight_kg)}</td><td class="num">${F.weight(d.target_weight_kg)}</td><td class="num">${F.num(d.intake_kcal)}</td><td class="num">${F.num(d.burned_kcal)}</td><td class="num">${d.carbs_g != null ? `${F.num(d.carbs_g)} / ${F.num(d.protein_g)} / ${F.num(d.fat_g)} g` : "—"}</td></tr>`).join("")}</tbody></table></div>`
    : empty("Pas encore d'apports déclarés", "Les journaux <code>nutrition/</code> au contrat (apports, macros) alimentent ce tableau.");
  main.innerHTML = `${header("Nutrition")}${weightHtml}${fuelingHtml}${table}`;
  if (weightChart) {
    attachCursor($("#c-weight"), weightChart, (i) => {
      const p = weight_series[i];
      const origin = p.weight_origin ? ` <small class="muted">(${WEIGHT_ORIGIN_LABEL[p.weight_origin]})</small>` : "";
      readout($("#r-weight"), `<strong>${F.dayLong(p.date)}</strong> · poids ${F.weight(p.weight_kg_merged)}${origin} · moyenne 7 j ${F.weight(p.weight_avg7_kg)}`);
    });
  }
  if (fuelingChart) {
    attachCursor($("#c-fueling"), fuelingChart, (i) => {
      const p = fuelingPoints[i];
      readout($("#r-fueling"), `<strong>${F.dayLong(p.date)}</strong> · glucides ${F.carbsRate(p.carbs_per_hour_g)} · sudation ${F.sweatRate(p.sweat_rate_l_h)}`);
    });
  }
}

/** #69, revue de code : un item `collision` (fichier VALIDE au contrat, une de
 * ses semaines seulement éclipsée par un autre fichier — voir
 * `arc_index.week_collisions`/`backfill_items`) n'est PAS un fichier hors
 * contrat. Il ne doit ni apparaître sous « Fichiers hors contrat » (avec le
 * conseil `/arc-backfill`, qui réécrirait un bloc déjà correct), ni compter
 * dans `incomplete_files` (`/api/summary`, `viewToday`) — les deux comptent
 * une dette de CONTRAT, la collision en est une différente (trim/suppression
 * de l'entrée en trop). Une section séparée, sa propre explication. */
async function viewFiles() {
  const { items } = await api("files", { fresh: true });
  const contractItems = items.filter((i) => !i.collision);
  const collisionItems = items.filter((i) => i.collision);
  const contractBlock = contractItems.length
    ? `<section class="band">${note("Pour les mettre au contrat, lancez <code>/arc-backfill</code> dans votre IDE : le coach les reprend par lots, sans rien inventer, en conservant le texte existant.")}
        <ul class="list">${contractItems.map((i) => `<li><code>${F.esc(i.path)}</code><span class="list__meta">${F.esc(i.status === "no" ? "illisible" : i.status === "invalid" ? "bloc invalide" : "lecture partielle")} — ${F.esc(i.issues.slice(0, 3).join(" · "))}</span></li>`).join("")}</ul></section>`
    : empty("Tout est au contrat", "Chaque fichier du workspace porte un bloc <code>```arc</code> valide.");
  const collisionBlock = collisionItems.length
    ? `<section class="band"><h2>Collisions de semaine</h2>${note("Ces fichiers sont déjà valides au contrat : n'y ajoutez ni ne réécrivez aucun bloc <code>```arc</code>. Un autre fichier décrit déjà la même semaine et fait foi (le fichier dédié, sinon le chemin le plus petit) — corrigez en retirant ou en supprimant l'entrée <code>weeks[]</code> en trop.")}
        <ul class="list">${collisionItems.map((i) => `<li><code>${F.esc(i.path)}</code><span class="list__meta">${F.esc(i.issues.slice(0, 3).join(" · "))}</span></li>`).join("")}</ul></section>`
    : "";
  main.innerHTML = `${header("Fichiers hors contrat", "Lus au mieux par le tableau de bord, mais sans bloc <code>```arc</code> valide.")}${contractBlock}${collisionBlock}`;
}

// ---------------------------------------------------------------------------
// Vue : Décisions (#55) — journal chronologique, filtrable
// ---------------------------------------------------------------------------

/** Liens de filtre : conserve TOUJOURS les deux autres filtres (`déclencheur`,
 * `résultat`, `jours`) lors du changement d'un seul, pour que les trois se
 * combinent plutôt que s'écraser — même discipline que `viewSessions` (tri +
 * sport) et `viewAnalyse` (semaines + classe de descente). */
// Fenêtre par défaut de la vue « Décisions » (#55, revue de code) : SANS
// paramètre `jours`, `/api/decisions` se bornait à 90 j côté serveur (voir
// `arc_serve.api_decisions`) — « Tout » reste offert, mais via la valeur
// EXPLICITE `jours=tout`, jamais l'absence de paramètre (qui redeviendrait
// silencieusement le défaut serveur si on l'utilisait pour ça).
const DECISIONS_DEFAULT_DAYS = 90;

function decisionFilterHash({ trigger, outcome, days }) {
  const p = new URLSearchParams();
  if (trigger) p.set("declencheur", trigger);
  if (outcome) p.set("resultat", outcome);
  if (days != null) p.set("jours", String(days));
  return `#/decisions?${p}`;
}

async function viewDecisions(params) {
  const trigger = params.get("declencheur") || "";
  const outcome = params.get("resultat") || "";
  const joursRaw = params.get("jours");
  const showAll = joursRaw === "tout";
  const days = showAll ? null : (joursRaw && /^\d+$/.test(joursRaw) ? Number(joursRaw) : DECISIONS_DEFAULT_DAYS);
  const qs = new URLSearchParams();
  if (showAll) qs.set("all", "1"); else qs.set("days", String(days));
  if (trigger) qs.set("trigger", trigger);
  if (outcome) qs.set("outcome", outcome);
  const data = await api(`decisions?${qs}`);
  const list = data.decisions || [];
  // Effet des décisions (#175) : même fenêtre/déclencheur ; une indisponibilité ne casse jamais le journal.
  let effects = null;
  try {
    const eq = new URLSearchParams({ days: String(showAll ? 3650 : days) });
    if (trigger) eq.set("trigger", trigger);
    effects = await api(`decision-effects?${eq}`);
  } catch { effects = null; }
  const effectById = new Map(((effects && effects.effects) || []).map((e) => [e.id, e]));
  // Journal vide : l'état vide ci-dessous suffit, pas de carte de synthèse redondante au-dessus.
  const synthesisHtml = !effects || !list.length ? "" : `<section class="band" aria-labelledby="effets-title">
      <h2 id="effets-title">Ce qui s'est passé ensuite</h2>
      ${(effects.synthesis || []).length
        ? `<ul>${effects.synthesis.map((g) => `<li>${F.esc(g.statement)}${g.trend ? ` — tendance ${F.esc(g.trend)}` : ""}${g.warning ? ` <span class="muted">(${F.esc(g.warning)})</span>` : ""}</li>`).join("")}</ul>`
        : `<p class="muted">Pas encore de décision évaluable : il faut qu'une décision appliquée (ou refusée) soit suivie de quelques jours de données pour être comparée avant / après.</p>`}
      ${note(F.esc(effects.caveat))}
    </section>`;
  const periods = [[30, "1 mois"], [90, "3 mois"], [365, "1 an"], ["tout", "Tout"]];
  const toolbarPeriods = periods.map(([value, label]) => {
    const on = value === "tout" ? showAll : value === days;
    return `<a class="seg ${on ? "is-on" : ""}" aria-current="${on ? "true" : "false"}" href="${decisionFilterHash({ trigger, outcome, days: value })}">${label}</a>`;
  }).join("");
  const triggerOptions = Object.entries(F.TRIGGER).map(([k, l]) => `<option value="${k}" ${k === trigger ? "selected" : ""}>${l}</option>`).join("");
  const outcomeOptions = Object.entries(F.DECISION_OUTCOME).map(([k, l]) => `<option value="${k}" ${k === outcome ? "selected" : ""}>${l}</option>`).join("");
  const items = list.map((d) => {
    const ruleTxt = (d.rules || []).map((r) => F.esc(r.label || r.rule_id)).join(", ");
    return `<li>
      <a href="#/decision?id=${encodeURIComponent(d.id)}"><strong>${F.esc(d.summary)}</strong></a>
      <span class="list__meta">${F.dayLong(d.date)} · ${triggerChip(d.trigger)} ${outcomeChip(d.outcome)}${ruleTxt ? ` · ${ruleTxt}` : ""}${d.supersedes ? " · remplace une décision précédente" : ""}${effectById.get(d.id) ? ` · ${effectChip(effectById.get(d.id).effect)}` : ""}</span>
    </li>`;
  }).join("");
  const currentHashDays = showAll ? "tout" : days;
  main.innerHTML = `${header("Décisions", `Journal des ajustements du coach : ce qui a changé, ce qui l'a justifié. <a href="${GUARDRAILS_DOC_URL}" rel="noopener noreferrer">Garde-fous</a>`)}
    <div class="toolbar">${toolbarPeriods}
      <label class="select">Déclencheur : <select id="f-declencheur"><option value="">Tous</option>${triggerOptions}</select></label>
      <label class="select">Résultat : <select id="f-resultat"><option value="">Tous</option>${outcomeOptions}</select></label>
    </div>
    ${synthesisHtml}
    ${list.length ? `<ul class="list">${items}</ul>`
      : empty("Aucune décision sur cette période", "Le coach écrit une décision quand il ajuste, allège ou reporte une séance — bilan matinal, garde-fou, ou demande de l'athlète.")}`;
  $("#f-declencheur").addEventListener("change", (e) => { location.hash = decisionFilterHash({ trigger: e.target.value, outcome, days: currentHashDays }); });
  $("#f-resultat").addEventListener("change", (e) => { location.hash = decisionFilterHash({ trigger, outcome: e.target.value, days: currentHashDays }); });
}

/** Vue « Décisions », détail (#55, `#/decision?id=…`) : avant/après, données,
 * règles, sources et chaîne `supersedes` — tout ce que le journal doit
 * exposer pour qu'« pourquoi cette séance a changé » se lise sans ouvrir
 * l'IDE ni relancer une conversation disparue. */
async function viewDecision(params) {
  const id = params.get("id") || "";
  let d;
  try {
    d = await api(`decision/${encodeURIComponent(id)}`);
  } catch {
    main.innerHTML = header("Décision introuvable") + empty("Décision introuvable", `Aucune décision ne correspond à cet identifiant. <a href="#/decisions">Retour au journal</a>.`);
    return;
  }
  let effectHtml = "";
  try {
    const eff = await api(`decision-effects?days=3650`);
    const ev = (eff.effects || []).find((e) => e.id === id);
    if (ev) effectHtml = `<section class="band"><h2>Ce qui s'est passé ensuite ${effectChip(ev.effect)}</h2>${effectDetailHtml(ev)}${note(F.esc(eff.caveat))}</section>`;
  } catch { effectHtml = ""; }
  const before = d.before || {}, after = d.after || {};
  // Diff avant/après (revue de code #55, should-fix 1) : une clé ABSENTE de
  // `after` (le contrat n'y recopie que les champs qui CHANGENT — voir
  // workspace-data-contract.md) ne veut pas dire « effacée » — l'afficher en
  // « — » se lisait à tort comme un champ vidé (le cas le plus visible :
  // `date`/`sport` de la décision du bilan matinal synthétique, qui ne
  // figurent jamais dans son `after`). La valeur AVANT, grisée avec
  // « (inchangé) », le dit sans ambiguïté ; formatage PAR CLÉ (durée, statut,
  // date, intensité) plutôt que la valeur brute.
  const diffKeys = [...new Set([...Object.keys(before), ...Object.keys(after)])];
  const diffHtml = diffKeys.length
    ? `<table class="data data--compact"><thead><tr><th scope="col">Champ</th><th scope="col">Avant</th><th scope="col">Après</th></tr></thead>
        <tbody>${diffKeys.map((k) => {
          const beforeVal = formatDecisionDiffValue(k, before[k]);
          const hasAfter = Object.prototype.hasOwnProperty.call(after, k);
          const afterVal = hasAfter ? formatDecisionDiffValue(k, after[k]) : null;
          const beforeCell = beforeVal !== null ? F.esc(beforeVal) : "—";
          const afterCell = hasAfter
            ? (afterVal !== null ? F.esc(afterVal) : "—")
            : `<span class="muted">${beforeCell} (inchangé)</span>`;
          return `<tr><th scope="row">${F.esc(k)}</th><td>${beforeCell}</td><td>${afterCell}</td></tr>`;
        }).join("")}</tbody></table>` : "";
  const inputsHtml = d.inputs && Object.keys(d.inputs).length
    ? `<ul>${Object.entries(d.inputs).map(([k, v]) => `<li><code>${F.esc(k)}</code> : ${F.esc(fmtInputValue(v))}</li>`).join("")}</ul>` : "";
  const rulesHtml = (d.rules || []).length
    ? `<ul>${d.rules.map((r) => `<li>${F.esc(r.label || r.rule_id)} <span class="muted">(${F.esc(r.rule_id)}${r.default_severity ? ` · ${F.esc(r.default_severity)}` : ""})</span></li>`).join("")}</ul>` : "";
  const sourcesHtml = (d.source_links || []).length
    ? `<p>${d.source_links.map((sl) => sl.route ? `<a href="${sl.route}">${F.esc(sl.label)}</a>` : F.esc(sl.label)).join(", ")}</p>` : "";
  main.innerHTML = `${header(d.summary, `${F.dayLong(d.date)} · ${triggerChip(d.trigger)} ${outcomeChip(d.outcome)}`)}
    <p><a href="#/decisions">← Toutes les décisions</a></p>
    ${d.outcome === "proposed" ? note("En attente de ta confirmation.") : ""}
    ${diffHtml ? `<section class="band"><h2>Avant / après</h2>${diffHtml}</section>` : ""}
    ${inputsHtml ? `<section class="band"><h2>Données</h2>${inputsHtml}</section>` : ""}
    ${effectHtml}
    ${rulesHtml ? `<section class="band"><h2>Règles</h2>${rulesHtml}</section>` : ""}
    ${sourcesHtml ? `<section class="band"><h2>Sources</h2>${sourcesHtml}</section>` : ""}
    ${d.session_ref_route ? `<p><a href="${d.session_ref_route}">Voir la semaine concernée</a></p>` : ""}
    ${d.supersedes_info ? `<p class="muted">Remplace : <a href="#/decision?id=${encodeURIComponent(d.supersedes_info.id)}">${F.esc(d.supersedes_info.summary)}</a> (${F.dayLong(d.supersedes_info.date)})</p>` : ""}
    ${(d.superseded_by || []).length ? `<p class="muted">Remplacée par : ${d.superseded_by.map((sb) => `<a href="#/decision?id=${encodeURIComponent(sb.id)}">${F.esc(sb.summary)}</a>`).join(", ")}</p>` : ""}
    ${d.body_html ? `<section class="band">${d.body_html}</section>` : ""}`;
}

// ---------------------------------------------------------------------------
// Routeur
// ---------------------------------------------------------------------------

/** Convertit l'ancien paramètre `jours` de « Forme & charge » (#/forme?jours=…,
 * #47) vers le sélecteur de fenêtre EN SEMAINES d'Analyse (#50) — jamais un
 * simple arrondi (`Math.round(jours / 7)`) : 90 jours donnerait 13 semaines,
 * qu'AUCUN des trois boutons de la vue (12/26/52, « 3 mois »/« 6 mois »/« 1 an »)
 * n'offre — le sélecteur resterait sans état actif (`aria-current` nulle part),
 * la fenêtre demandée silencieusement différente de celle affichée par les
 * boutons (revue de code #50, should-fix 2). Correspondance exacte pour les
 * trois périodes historiques de « Forme & charge » (90/180/365 j) ; sinon, la
 * période OFFERTE la plus proche — jamais une valeur hors de `[12, 26, 52]`. */
function daysToWeeksPeriod(days) {
  const exact = { 90: 12, 180: 26, 365: 52 };
  if (exact[days] != null) return exact[days];
  const offered = [12, 26, 52];
  return offered.reduce((best, w) => (Math.abs(w * 7 - days) < Math.abs(best * 7 - days) ? w : best));
}

const ROUTES = {
  "": viewToday, forme: viewForm, analyse: viewAnalyse, sante: viewHealth, semaine: viewWeek, seances: viewSessions,
  performance: viewPerformance, materiel: viewMateriel, "trail-shape": viewTrailShape, roadbook: viewRoadbook, calendrier: viewCalendar, rapports: viewReports, rapport: viewReport,
  nutrition: viewNutrition, fichiers: viewFiles, hypotheses: viewHypotheses, decisions: viewDecisions, decision: viewDecision,
};

// `decodeURIComponent` lève sur `%E0` (#/materiel/%E0) : repli sur l'identifiant brut → « introuvable ».
function safeDecode(v) {
  try { return decodeURIComponent(v); } catch { return v; }
}

async function route() {
  const hash = location.hash.replace(/^#\/?/, "");
  const [path, query] = hash.split("?");
  const params = new URLSearchParams(query || "");
  const [name, arg] = path.split("/");
  // Compatibilité des liens (#50) : le sélecteur de classe de descente vivait sur
  // `#/forme?jours=…&descente=…` (#47) avant que ces tendances FIT ne rejoignent
  // la vue Analyse — un lien partagé ou mis en favori avant #50 doit continuer à
  // ouvrir la bonne classe plutôt que de renvoyer vers « Forme & charge » où la
  // section a disparu. `jours` est mappé sur l'une des trois fenêtres OFFERTES
  // par le sélecteur d'Analyse (voir `daysToWeeksPeriod`), jamais un simple
  // arrondi jours/7 qui produirait une fenêtre sans bouton actif.
  if (name === "forme" && params.has("descente")) {
    const joursVal = Number(params.get("jours")) || 180;
    const semaines = daysToWeeksPeriod(joursVal);
    const redirected = new URLSearchParams({ semaines: String(semaines), descente: params.get("descente") });
    location.replace(`#/analyse?${redirected}`);
    return;
  }
  markNav(name);
  main.setAttribute("aria-busy", "true");
  try {
    if (name === "seance" && arg) await viewSession(Number(arg));
    else if (name === "materiel" && arg) await viewGearDetail(safeDecode(arg));
    else if (name === "montee" && arg) await viewClimbSegment(Number(arg));
    else if (ROUTES[name]) await ROUTES[name](params);
    else main.innerHTML = header("Page introuvable") + `<p><a href="#/">Retour à aujourd'hui</a></p>`;
  } catch (err) {
    main.innerHTML = header("Données indisponibles") + empty("Le serveur n'a pas répondu comme prévu", `${F.esc(err.message)}. Vérifiez que <code>scripts/dashboard.sh</code> tourne toujours, puis rechargez la page.`);
  } finally {
    main.removeAttribute("aria-busy");
    main.focus({ preventScroll: true });
    window.scrollTo(0, 0);
  }
}

async function boot() {
  setupTheme();
  try {
    SUMMARY = await api("summary");
    F.setUnits(SUMMARY.settings.units);
    renderObjective(SUMMARY);
    renderNav(SUMMARY);
  } catch (err) {
    main.innerHTML = header("Tableau de bord indisponible") + empty("Impossible de lire l'index", `${F.esc(err.message)}. Relancez <code>scripts/dashboard.sh</code>.`);
    return;
  }
  window.addEventListener("hashchange", route);
  route();
}

boot();
