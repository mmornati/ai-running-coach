// Tableau de bord ai-running-coach — lecture seule, servi par scripts/arc_serve.py.
import * as F from "./format.js";
import { timeChart, attachCursor, verdictStrip, yearCalendar } from "./chart.js";

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

// Journal des décisions (#55) : lien de la documentation des garde-fous (#52),
// cité depuis « Décisions » et depuis l'encart « Pourquoi aujourd'hui ? ».
const GUARDRAILS_DOC_URL = "https://mmornati.github.io/ai-running-coach/guardrails/#les-sept-regles";

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

// Kilométrage chaussures et alerte d'usure (#40) : tuile « Aujourd'hui » — n'apparaît
// que si au moins une chaussure (non retirée) a atteint son seuil. Le détail complet
// (toutes les paires, retirées comprises) vit dans la vue Performance (`gearSection`).
function gearTile(gear) {
  const alerts = (gear?.shoes || []).filter((s) => s.alert);
  if (!alerts.length) return "";
  const names = alerts.map((s) => `${F.esc(s.name)} (${F.distance(s.distance_m, 0)})`).join(", ");
  return `<p class="weather">${chip("gear", "orange", "Chaussures à surveiller")} <span>${names}</span></p>`;
}

// Détail complet du kilométrage chaussures (vue Performance) : toutes les paires
// déclarées (retirées comprises, en fin de tableau), plus une ligne « inconnue »
// par `gear_id` vu sur une activité mais absent du profil (#40 — ne jamais
// masquer silencieusement un `gear_id` mal orthographié).
function gearSection(gear) {
  const shoes = gear?.shoes || [];
  const unknown = gear?.unknown || [];
  const warnings = gear?.warnings || [];
  if (!shoes.length && !unknown.length) return "";
  const sorted = [...shoes].sort((a, b) => (a.retired === b.retired ? 0 : a.retired ? 1 : -1));
  const rows = sorted.map((s) => `<tr${s.retired ? ` class="muted"` : ""}>
      <th scope="row">${F.esc(s.name)}${s.default ? ` <span class="tag">défaut</span>` : ""}${s.retired ? ` <span class="tag">retirée</span>` : ""}</th>
      <td class="num">${F.distance(s.distance_m, 0)}</td>
      <td class="num">${F.distance(s.threshold_m, 0)}</td>
      <td>${s.alert ? chip("gear", "orange", "À surveiller") : ""}</td></tr>`).join("");
  const unknownRows = unknown.map((u) => `<tr><th scope="row">${F.esc(u.gear_id)} <span class="tag">inconnue</span></th><td class="num">${F.distance(u.distance_m, 0)}</td><td class="num">—</td><td></td></tr>`).join("");
  return `<section class="band"><h2>Matériel</h2><table class="data data--compact">
      <thead><tr><th scope="col">Chaussure</th><th scope="col" class="num">Kilométrage</th><th scope="col" class="num">Seuil d'alerte</th><th scope="col">Statut</th></tr></thead>
      <tbody>${rows}${unknownRows}</tbody></table>
      ${unknown.length ? note("« inconnue » : gear_id vu sur une séance mais absent de la section « Chaussures » du profil (faute de frappe, paire jamais déclarée).") : ""}
      ${warnings.map((w) => note(F.esc(w))).join("")}</section>`;
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
  const nutrition = s.settings.agents?.includes("nutritionist");
  const items = [
    ["", "Aujourd'hui"], ["forme", "Forme & charge"], ["analyse", "Analyse"], ["sante", "Santé"], ["semaine", "Semaine"],
    ["seances", "Séances"], ["performance", "Performance"], ["calendrier", "Calendrier"],
    ["decisions", "Décisions"], ["rapports", "Rapports"], ...(nutrition ? [["nutrition", "Nutrition"]] : []),
  ];
  $("#nav").innerHTML = items.map(([h, l]) => `<a href="#/${h}" data-route="${h}">${l}</a>`).join("")
    + (s.incomplete_files ? `<a href="#/fichiers" data-route="fichiers" class="nav__debt">${s.incomplete_files} fichier${s.incomplete_files > 1 ? "s" : ""} hors contrat</a>` : "");
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
      || (route === "decision" && a.dataset.route === "decisions");
    a.toggleAttribute("aria-current", on);
    if (on) a.setAttribute("aria-current", "page");
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
    ? `<ul class="facts-list">${Object.entries(chosen.inputs).map(([k, v]) => `<li><code>${F.esc(k)}</code> : ${F.esc(String(v))}</li>`).join("")}</ul>` : "";
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
  const [health, week, form, reports, decisionHtml] = await Promise.all([
    api("health?days=14"), api("week"), api("form?days=30"), api("reports"), decisionEncart(s),
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
  const gearHtml = gearTile(s.gear);

  const f = form.series[form.series.length - 1];
  const formNow = f ? f.form : null;
  const formTxt = !f ? "Pas encore de séances indexées." :
    `${formNow > 5 ? "Fraîcheur : la fatigue est sous la condition physique." : formNow < -20 ? "Fatigue marquée : la charge récente dépasse nettement la condition." : "Zone de travail : fatigue et condition équilibrées."}${f.acwr > 1.3 ? " Charge aiguë au-dessus de la zone prudente." : ""}`;
  const formHtml = f ? `<dl class="facts"><div><dt>Condition</dt><dd>${F.num(f.fitness)}</dd></div><div><dt>Fatigue</dt><dd>${F.num(f.fatigue)}</dd></div><div><dt>Forme</dt><dd class="${formNow >= 0 ? "pos" : "neg"}">${formNow > 0 ? "+" : ""}${F.num(formNow)}</dd></div><div><dt>ACWR</dt><dd>${F.num(f.acwr, 2)}</dd></div></dl><p class="muted">${formTxt} <a href="#/forme">Courbe de forme</a></p>` : note(formTxt);

  const rep = reports.reports[0];
  main.innerHTML = `${header(F.dayLong(today).replace(/^./, (c) => c.toUpperCase()))}
    ${verdict}
    ${decisionHtml}
    <section class="band"><h2>Santé</h2>${triad}</section>
    <section class="band band--split"><div><h2>Au programme</h2>${sessionHtml}${weatherHtml}${heatHtml}${gearHtml}</div>
      <div><h2>Forme</h2>${formHtml}${complianceTrend(s.compliance_trend)}</div></section>
    ${rep ? `<section class="band"><h2>Dernier rapport du coach</h2><p><a href="#/rapport?path=${encodeURIComponent(rep.source_path)}">${F.esc(rep.title)}</a> <span class="muted">— ${F.dayLong(rep.date)}</span></p></section>` : ""}`;
}

// ---------------------------------------------------------------------------
// Vue : Forme & charge
// ---------------------------------------------------------------------------

async function viewForm(params) {
  const days = Number(params.get("jours")) || 180;
  const [form, load] = await Promise.all([api(`form?days=${days}`), api("load?weeks=26")]);
  const s = SUMMARY;
  const trail = s.settings.sport === "trail";
  const series = form.series;
  if (!series.length) {
    main.innerHTML = header("Forme & charge") + empty("Pas encore de séances", "La courbe de forme se construit à partir des séances indexées. Il faut environ six semaines d'historique pour qu'elle soit parlante.");
    return;
  }
  const dates = series.map((p) => p.date);
  const marks = [{ type: "hline", value: 0, cls: "mark mark--zero" }];
  if (form.race_date) marks.push({ type: "vline", date: form.race_date, cls: "mark mark--race", label: "Course" });
  const chart = timeChart(dates, [
    { type: "area", values: series.map((p) => p.form), cls: "area area--form" },
    { type: "line", values: series.map((p) => p.fitness), cls: "line line--fitness" },
    { type: "line", values: series.map((p) => p.fatigue), cls: "line line--fatigue" },
  ], marks, { height: 250, label: "Condition, fatigue et forme", yFormat: (v) => F.num(v) });
  const acwr = timeChart(dates, [
    { type: "band", lo: dates.map(() => form.acwr_safe[0]), hi: dates.map(() => form.acwr_safe[1]), cls: "band-fill" },
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
  main.innerHTML = `${header("Forme & charge", `Charge par séance : TRIMP (fréquence cardiaque), repli sur l'effort perçu. <a href="#/performance">Hypothèses des modèles</a>`)}
    <div class="toolbar">${periods}</div>
    <section class="band"><h2>Courbe de forme</h2>
      <p class="legend"><span class="legend__item"><span class="key key--fitness"></span>Condition (42 j)</span> <span class="legend__item"><span class="key key--fatigue"></span>Fatigue (7 j)</span> <span class="legend__item"><span class="key key--form"></span>Forme</span></p>
      <div class="chart-host" id="c-form">${chart.svg}</div><p class="readout" id="r-form"></p></section>
    <section class="band"><h2>Ratio charge aiguë / chronique</h2><p class="muted">Repère indicatif ${F.num(form.acwr_safe[0], 1)} – ${F.num(form.acwr_safe[1], 1)}, pas un seuil de blessure.</p>
      <div class="chart-host" id="c-acwr">${acwr.svg}</div></section>
    <section class="band"><h2>Volume hebdomadaire</h2>
      <p class="legend">${trail ? `<span class="legend__item"><span class="key key--bar"></span>Heures d'effort</span> <span class="legend__item"><span class="key key--dplus"></span>D+ cumulé</span>` : `<span class="legend__item"><span class="key key--bar"></span>Kilomètres</span>`}</p>
      <div class="chart-host" id="c-load">${loadChart.svg}</div><p class="readout" id="r-load"></p>
      <dl class="facts facts--inline"><div><dt>Monotonie (7 j)</dt><dd>${F.num(load.monotony, 2)}</dd></div><div><dt>Strain (7 j)</dt><dd>${F.num(load.strain)}</dd></div><div><dt>Charge du jour</dt><dd>${F.num(last.load)}</dd></div></dl>
      <p class="muted">Polarisation des zones FC, découplage aérobie, VAM, efficacité en descente et
        durabilité — issus des échantillons FIT ingérés — sont regroupés dans <a href="#/analyse">Analyse</a>.</p></section>`;

  attachCursor($("#c-form"), chart, (i) => {
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
  const [load, decoupling, vam, descent, durability, segments] = await Promise.all([
    api(`load?weeks=${weeks}`), api(`decoupling?weeks=${weeks}`), api(`vam?weeks=${weeks}`),
    api(`descent?weeks=${weeks}`), api(`durability?weeks=${weeks}`), api("climb-segments"),
  ]);
  const periods = [[12, "3 mois"], [26, "6 mois"], [52, "1 an"]].map(([w, l]) =>
    `<a class="seg ${w === weeks ? "is-on" : ""}" aria-current="${w === weeks ? "true" : "false"}" href="#/analyse?semaines=${w}">${l}</a>`).join("");
  const polarisationHtml = polarisationSection(load.polarisation_weeks, load.hr_zones_reason);
  const { html: decouplingHtml, chart: decouplingChart, points: decouplingPoints } = decouplingSection(decoupling);
  const { html: vamHtml, chart: vamChart, points: vamPoints } = vamSection(vam);
  const { html: descentHtml, chart: descentChart, points: descentPoints } = descentTrendSection(descent, weeks, params.get("descente"));
  const { html: durabilityHtml, chart: durabilityChart, points: durabilityPoints } = durabilitySection(durability);
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
    || (segments.segments || []).length > 0;
  if (!hasFitSamples) {
    main.innerHTML = header("Analyse", "Tendances calculées à partir des échantillons FIT (montre GPS) ingérés.")
      + empty("Pas encore d'échantillons FIT", "Ces tendances (polarisation des zones FC, découplage aérobie, VAM, "
        + "efficacité en descente, durabilité, historique des montées) exigent des échantillons FIT ingérés "
        + "(<code>activities/fit/*.json</code>), pas seulement le résumé d'une séance. Chargez le skill "
        + "<code>fit-download</code> (voir <code>skills/fit-download/SKILL.md</code>) pour les récupérer "
        + "depuis Garmin, puis relancez l'indexation.");
    return;
  }
  main.innerHTML = `${header("Analyse", `Tendances calculées à partir des échantillons FIT ingérés. <a href="#/performance">Hypothèses des modèles</a>`)}
    <div class="toolbar">${periods}</div>
    ${polarisationHtml}
    ${decouplingHtml}
    ${vamHtml}
    ${descentHtml}
    ${durabilityHtml}
    ${segmentsHtml}`;
  wirePolarisationChart(load.polarisation_weeks);
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
  const sorted = segments.slice().sort((a, b) => b.occurrences - a.occurrences);
  const rows = sorted.map((s) => {
    const label = `${s.location || "Montée"} — ${F.distance(s.distance_m, 2)}, +${F.elevation(s.gain_m)} (depuis ${F.dayShort(s.first_seen_date)})`;
    return `<tr><td><a href="#/montee/${s.segment_id}">${F.esc(label)}</a></td>
    <td class="num">${F.distance(s.distance_m, 2)}</td><td class="num">+${F.elevation(s.gain_m)}</td>
    <td class="num">${F.num(s.avg_grade * 100, 1)} % <span class="tag">${F.esc(s.grade_class)}</span></td>
    <td class="num">${F.num(s.occurrences)}</td>
    <td class="num">${s.best_time_elapsed_s != null ? F.clockShort(s.best_time_elapsed_s) : "—"}</td></tr>`;
  }).join("");
  return `<section class="band"><h2>Segments de montée (${segments.length})</h2>
    <p class="muted">Une même montée, reconnue d'une séance à l'autre (position GPS, ou à défaut profil
      distance/D+/pente — #49) : au moins deux occurrences pour apparaître ici, toutes périodes confondues
      (pas seulement la fenêtre choisie ci-dessus). Détail complet, occurrence par occurrence, dans
      l'historique de chaque segment.</p>
    <div class="table-wrap"><table class="data data--compact"><thead><tr>
      <th scope="col">Lieu</th><th scope="col" class="num">Distance</th><th scope="col" class="num">D+</th>
      <th scope="col" class="num">Pente moy.</th><th scope="col" class="num">Occurrences</th>
      <th scope="col" class="num">Meilleur temps</th></tr></thead>
      <tbody>${rows}</tbody></table></div></section>`;
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
      zones du profil (Karvonen, FC au seuil ou %FC max, voir <a href="#/performance">Hypothèses des modèles</a>),
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
// Vue : Santé
// ---------------------------------------------------------------------------

async function viewHealth(params) {
  const days = Number(params.get("jours")) || 90;
  const data = await api(`health?days=${days}`);
  const mode = data.morning_check;
  if (mode === "off") {
    main.innerHTML = header("Santé") + empty("Bilan matinal désactivé", "Avec <code>[health].morning_check = \"off\"</code>, le coach ne récupère ni HRV, ni FC de repos, ni readiness : leur absence ici n'est pas un manque. Passez à <code>minimal</code> ou <code>full</code> pour suivre ces courbes.");
    return;
  }
  const s = data.series;
  const dates = s.map((p) => p.date);
  if (!s.some((p) => p.readiness_score != null || p.hrv_overnight_ms != null || p.resting_hr_bpm != null)) {
    main.innerHTML = header("Santé") + empty("Pas encore de données de santé", "Les fichiers <code>medical/AAAA-MM-JJ_health.md</code> écrits par la synchronisation alimentent ces courbes.");
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
    ${charts.map(([id, title, sub, c, strip]) => `<section class="band"><h2>${title}</h2>${sub ? `<p class="muted">${sub}</p>` : ""}<div class="chart-host" id="c-${id}">${c.svg}</div>${strip ? `<div class="strip-host">${verdictStrip(dates, s.map((p) => p.verdict))}<p class="legend legend--small"><span class="legend__item"><span class="key key--green"></span>Maintenir</span> <span class="legend__item"><span class="key key--amber"></span>Alléger</span> <span class="legend__item"><span class="key key--red"></span>Repos</span> — verdicts du coach</p></div>` : ""}</section>`).join("")}`;
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
}

// ---------------------------------------------------------------------------
// Vue : Semaine
// ---------------------------------------------------------------------------

async function viewWeek(params) {
  const start = params.get("debut");
  const w = await api(start ? `week?start=${start}` : "week");
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
    <ol class="week">${cols}</ol>
    <section class="band"><h2>Réalisé</h2><dl class="facts facts--inline"><div><dt>Séances</dt><dd>${w.activities.length}</dd></div><div><dt>Durée</dt><dd>${F.hours(totalS)}${target.target_duration_s ? ` <small>/ ${F.hours(target.target_duration_s)}</small>` : ""}</dd></div><div><dt>Distance</dt><dd>${F.distance(totalM)}${target.target_distance_m ? ` <small>/ ${F.distance(target.target_distance_m, 0)}</small>` : ""}</dd></div></dl></section>
    ${complianceSection(w.compliance, trail)}
    ${w.body_html ? `<section class="band prose"><h2>Plan du coach</h2>${w.body_html}</section>` : ""}`;
  const sel = $("#weeks");
  if (sel) sel.addEventListener("change", () => { location.hash = `#/semaine?debut=${sel.value}`; });
}

// ---------------------------------------------------------------------------
// Vues : Séances, détail
// ---------------------------------------------------------------------------

async function viewSessions(params) {
  const { activities } = await api("activities?limit=500");
  const sport = params.get("sport") || "";
  const sort = params.get("tri") || "date";
  const dir = params.get("sens") === "asc" ? 1 : -1;
  const trail = SUMMARY.settings.sport === "trail";
  let rows = activities.filter((a) => !sport || a.sport === sport);
  const key = { date: (a) => a.date, distance: (a) => a.distance_m || 0, duree: (a) => a.duration_s || 0, dplus: (a) => a.elevation_gain_m || 0, fc: (a) => a.avg_hr_bpm || 0, charge: (a) => a.load || 0 }[sort] || ((a) => a.date);
  rows = rows.slice().sort((a, b) => (key(a) > key(b) ? 1 : key(a) < key(b) ? -1 : 0) * dir);
  const sports = [...new Set(activities.map((a) => a.sport))];
  const th = (k, label, num = true) => {
    const on = sort === k;
    const next = on && dir === -1 ? "asc" : "desc";
    return `<th scope="col" class="${num ? "num" : ""}" aria-sort="${on ? (dir === 1 ? "ascending" : "descending") : "none"}"><a href="#/seances?${new URLSearchParams({ sport, tri: k, sens: next })}">${label}${on ? (dir === 1 ? " ↑" : " ↓") : ""}</a></th>`;
  };
  main.innerHTML = `${header("Séances", `${activities.length} séances indexées.`)}
    <div class="toolbar"><label class="select">Sport : <select id="sport"><option value="">Tous</option>${sports.map((s) => `<option value="${s}" ${s === sport ? "selected" : ""}>${F.SPORT[s] || s}</option>`).join("")}</select></label></div>
    ${rows.length ? `<div class="table-wrap"><table class="data"><thead><tr>${th("date", "Date", false)}<th scope="col">Séance</th>${th("distance", "Distance")}${th("duree", "Durée")}${trail ? th("dplus", "D+") : `<th scope="col" class="num">Allure</th>`}${th("fc", "FC moy")}<th scope="col" class="num">HRR</th>${th("charge", "Charge")}</tr></thead>
    <tbody>${rows.map((a) => `<tr><td class="nowrap">${F.dayShort(a.date)} <span class="muted">${a.date.slice(0, 4)}</span></td><td><a href="#/seance/${a.id}">${F.esc(a.name || F.SPORT[a.sport] || a.sport)}</a> <span class="muted">${F.SPORT[a.sport] || a.sport}</span>${a.arc_version === 0 ? ` <span class="tag" title="Fichier hors contrat : lecture approximative">approx.</span>` : ""}</td>
      <td class="num">${F.distance(a.distance_m)}</td><td class="num">${F.duration(a.duration_s)}</td><td class="num">${trail ? F.elevation(a.elevation_gain_m) : F.pace(a.distance_m, a.duration_s)}</td>
      <td class="num">${F.num(a.avg_hr_bpm)}</td><td class="num">${a.recovery_hr_bpm != null ? F.num(a.recovery_hr_bpm) : `<span class="muted" title="non mesuré">—</span>`}</td><td class="num">${F.num(a.load)}${a.load_source === "estimated" ? `<span class="muted" title="Charge estimée : ni FC ni effort perçu">*</span>` : ""}</td></tr>`).join("")}</tbody></table></div>`
    : empty("Aucune séance", "Les fichiers <code>activities/AAAA-MM-JJ_&lt;sport&gt;.md</code> apparaissent ici une fois indexés.")}`;
  $("#sport").addEventListener("change", (e) => { location.hash = `#/seances?${new URLSearchParams({ sport: e.target.value, tri: sort, sens: dir === 1 ? "asc" : "desc" })}`; });
}

async function viewSession(id) {
  const d = await api(`activity/${id}`);
  const a = d.activity;
  const trail = SUMMARY.settings.sport === "trail";
  const missing = a.missing_reason || {};
  const facts = [
    ["Distance", F.distance(a.distance_m, 2)], ["Durée", F.duration(a.duration_s, { seconds: true })],
    ["Allure", F.pace(a.distance_m, a.moving_duration_s || a.duration_s)],
    // GAP (#44) : uniquement pour la famille course à pied avec échantillons FIT
    // ingérés (arc_gap.ASSUMPTIONS) — absent (jamais une ligne à "—") sinon, pour
    // ne pas laisser croire qu'une valeur a été calculée et vaut zéro/inconnue.
    ...(a.gap_pace_s_km != null ? [["GAP (allure ajustée à la pente)", F.paceFromSecPerKm(a.gap_pace_s_km)]] : []),
    // Découplage aérobie / Pa:HR (#45) : uniquement si calculable (séance de course
    // à pied, ≥ 60 min de mouvement, effort jugé stable — arc_decoupling.ASSUMPTIONS)
    // — jamais une ligne à "—", qui laisserait croire à une valeur nulle mesurée.
    // Couleur seulement dans les deux sens univoques (revue de code #45) : 0-5 %
    // (dérive attendue, repère de bonne durabilité) en positif, au-delà en
    // négatif (dérive trop marquée) — une valeur négative (efficacité qui
    // s'améliore, ou simplement du bruit de mesure) reste neutre, jamais
    // colorée comme si « moins » était automatiquement « mieux ».
    ...(a.decoupling_pct != null ? [["Découplage aérobie (Pa:HR)",
      `<span class="${a.decoupling_pct >= 0 && a.decoupling_pct <= 5 ? "pos" : a.decoupling_pct > 5 ? "neg" : ""}">${a.decoupling_pct > 0 ? "+" : ""}${F.num(a.decoupling_pct, 1)} %</span>${a.ef_whole != null ? `<small class="muted"> · EF ${F.num(a.ef_whole, 2)}</small>` : ""}`]] : []),
    // Durabilité (#48) : fade GAP entre le premier et le dernier tiers de la
    // sortie longue — uniquement si calculable (voir arc_durability.ASSUMPTIONS),
    // jamais une ligne à "—". Couleur seulement dans les deux sens univoques
    // (même discipline que le découplage ci-dessus) : positif (ralentissement en
    // fin de sortie) en négatif visuel, négatif ou nul (pas de baisse) neutre —
    // jamais coloré comme si un fade positif était souhaitable.
    ...(a.durability_gap_fade_pct != null ? [["Durabilité (fade GAP dernier tiers)",
      `<span class="${a.durability_gap_fade_pct > 0 ? "neg" : ""}">${a.durability_gap_fade_pct > 0 ? "+" : ""}${F.num(a.durability_gap_fade_pct, 1)} %</span>${a.durability_ef_fade_pct != null ? `<small class="muted"> · fade EF ${a.durability_ef_fade_pct > 0 ? "+" : ""}${F.num(a.durability_ef_fade_pct, 1)} %</small>` : ""}`]] : []),
    ...(trail || a.elevation_gain_m ? [["D+ / D-", a.elevation_gain_m != null ? `${F.elevation(a.elevation_gain_m)} / ${F.elevation(a.elevation_loss_m)}` : (missing.elevation_gain_m ? "non mesuré" : "—")]] : []),
    ["FC moy / max", a.avg_hr_bpm ? `${F.num(a.avg_hr_bpm)} / ${F.num(a.max_hr_bpm)} bpm` : (missing.avg_hr_bpm ? "non mesurée" : "—")],
    ["HRR", a.recovery_hr_bpm != null ? `${F.num(a.recovery_hr_bpm)} bpm` : `non mesuré${missing.recovery_hr_bpm ? ` — ${F.esc(missing.recovery_hr_bpm)}` : ""}`],
    ["Effet d'entraînement", a.te_aerobic != null ? `${F.num(a.te_aerobic, 1)}${a.te_anaerobic != null ? ` / ${F.num(a.te_anaerobic, 1)} anaérobie` : ""}` : "—"],
    ["Charge", `${F.num(a.load)} <small class="muted">${a.load_source === "trimp" ? "TRIMP" : a.load_source === "srpe" ? "effort perçu" : "estimée"}</small>`],
    ...(a.vo2max_est ? [["VO2max estimée", F.num(a.vo2max_est, 1)]] : []),
  ];
  let splitsHtml = "";
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
      <div class="table-wrap"><table class="data data--compact"><thead><tr><th scope="col">${unit}</th>${byKm ? "" : `<th scope="col" class="num">Distance</th>`}<th scope="col" class="num">Temps</th>${byKm ? "" : `<th scope="col" class="num">Allure</th>`}${hasGap ? `<th scope="col" class="num">GAP</th>` : ""}<th scope="col" class="num">D+ / D-</th><th scope="col" class="num">FC</th><th scope="col" class="num">Cadence</th><th scope="col">Lecture</th></tr></thead>
      <tbody>${all.map((x) => `<tr><td>${x.km}</td>${byKm ? "" : `<td class="num">${x.distance_m != null ? F.distance(x.distance_m, 2) : "—"}</td>`}<td class="num">${F.clockShort(x.duration_s)}</td>${byKm ? "" : `<td class="num">${lapPace(x)}</td>`}${hasGap ? `<td class="num">${F.paceFromSecPerKm(x.gap_pace_s_km)}</td>` : ""}<td class="num">${x.elev_gain_m != null ? `+${F.num(x.elev_gain_m)} / -${F.num(x.elev_loss_m)}` : "—"}</td><td class="num">${F.num(x.avg_hr_bpm)}</td><td class="num">${F.num(x.cadence_spm)}</td><td>${F.esc(x.label || "")}</td></tr>`).join("")}</tbody></table></div></section>`;
    setTimeout(() => attachCursor($("#c-splits"), c, (i) => {
      const x = sp[i];
      const what = byKm ? F.clockShort(x.duration_s) : `${F.distance(x.distance_m, 2)} en ${F.clockShort(x.duration_s)} (${lapPace(x)})`;
      readout($("#r-splits"), `<strong>${unit} ${x.km}</strong> · ${what}${x.gap_pace_s_km != null ? ` · GAP ${F.paceFromSecPerKm(x.gap_pace_s_km)}` : ""} · FC ${F.num(x.avg_hr_bpm)}${x.elev_gain_m != null ? ` · +${F.num(x.elev_gain_m)} m` : ""}${x.label ? ` · ${F.esc(x.label)}` : ""}`);
    }), 0);
  }
  const wx = d.weather;
  // Séance sans FIT (#50, critère d'acceptation) : `climbs.reason_code === "no_samples"`
  // (`arc_serve.py::api_activity_climbs`, même `reason_code` porté par `descent` et
  // implicitement par `hr_zones.zone_seconds`, les trois dérivés de la MÊME table
  // `activity_sample` pour la même activité) signale l'absence totale d'échantillons
  // FIT ingérés pour une séance de la famille course à pied — jamais un simple test
  // sur le texte français de `reason` (fragile, même motif que `climbs.applicable`
  // ci-dessus). Plutôt que d'empiler trois notes vides identiques (zones FC, montées,
  // descente), une seule note consolidée remplace les trois (critère d'acceptation :
  // « séance sans FIT : sections masquées proprement »).
  const noFitSamples = !!(d.climbs && d.climbs.applicable !== false && d.climbs.reason_code === "no_samples");
  main.innerHTML = `${header(a.name || F.SPORT[a.sport] || "Séance", `${F.dayLong(a.date)} · ${F.SPORT[a.sport] || a.sport}${a.location ? " · " + F.esc(a.location) : ""}`)}
    <p><a href="#/seances">← Toutes les séances</a></p>
    <dl class="facts facts--grid">${facts.map(([k, v]) => `<div><dt>${k}</dt><dd>${v}</dd></div>`).join("")}</dl>
    ${wx ? `<p class="weather">${weatherChip(wx.category)} <span>${F.esc(wx.location)} · ${F.num(wx.temp_min_c)}–${F.num(wx.temp_max_c)} °C · vent ${F.num(wx.wind_kmh)} km/h</span></p>` : ""}
    ${noFitSamples ? noFitSamplesNote(d.hr_zones) : hrZoneSection(d.hr_zones)}
    ${splitsHtml}
    ${noFitSamples ? "" : climbsSection(d.climbs)}
    ${noFitSamples ? "" : descentSection(d.descent)}
    <section class="band prose"><h2>Analyse du coach</h2>${d.body_html || "<p class=\"muted\">Pas de texte.</p>"}<p class="muted source">Source : <code>${F.esc(a.source_path)}</code></p></section>`;
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

function climbsSection(climbs) {
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
      <th scope="col" class="num">vs précédent/meilleur</th></tr></thead>
    <tbody>${rows.map((c) => `<tr><td>${c.index}</td><td class="num">${F.distance(c.start_km * 1000, 1)} → ${F.distance(c.end_km * 1000, 1)}</td>
      <td class="num">${F.distance(c.distance_m, 2)}</td><td class="num">+${F.elevation(c.gain_m)}</td>
      <td class="num">${F.num(c.avg_grade * 100, 1)} % <span class="tag">${F.esc(c.grade_class)}</span></td>
      <td class="num">${F.clockShort(c.duration_elapsed_s)}</td>
      <td class="num">${F.vam(c.vam_elapsed_m_h)}<br><small class="muted">mvt ${F.vam(c.vam_moving_m_h)}</small></td>
      <td class="num">${climbProgressionCell(c)}</td></tr>`).join("")}</tbody></table></div>
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
      classes de pente différentes. <a href="#/performance">Hypothèses des modèles</a></p>
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
    ${note("Aucun échantillon FIT ingéré pour cette séance : temps en zone, GAP par tour, montées (VAM) et "
      + "efficacité en descente ne peuvent pas être calculés. Synchronisez le fichier FIT (skill "
      + "<code>fit-download</code>) puis relancez l'indexation pour les activer.")}</section>`;
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

async function viewPerformance() {
  const p = await api("performance");
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
  const assumptions = SUMMARY.assumptions || {};
  main.innerHTML = `${header("Performance", "Estimations modélisées à partir des moyennes de chaque séance : des ordres de grandeur, pas des mesures.")}
    <section class="band"><h2>VO2max effective</h2>${p.vo2max_current ? `<p class="lead-num">${F.num(p.vo2max_current, 1)} <small>ml/kg/min, tendance 30 j${p.vo2max_date !== SUMMARY.today ? ` au ${F.dayShort(p.vo2max_date)}` : ""}</small></p>` : ""}${chartHtml}</section>
    <section class="band band--split"><div><h2>Prédictions</h2><table class="data data--compact"><thead><tr><th scope="col">Distance</th><th scope="col" class="num">VDOT</th><th scope="col" class="num">Riegel</th></tr></thead><tbody>${pred}</tbody></table>
      ${trail ? note("En trail, la distance « effort » ajoute le dénivelé (1000 m D+ ≈ 1,75 km de plat, <code>config/sports/trail.md</code>). Sable, vent et barrières ne sont pas modélisés.") : ""}</div>
      <div><h2>Records</h2>${rec}</div></section>
    ${gearSection(SUMMARY.gear)}
    <section class="band"><h2>Hypothèses</h2><dl class="assumptions">${Object.values(assumptions).map((t) => `<dd>${F.esc(t)}</dd>`).join("")}</dl></section>`;
  if (c) attachCursor($("#c-vo2"), c, (i) => readout($("#r-vo2"), `<strong>${F.dayLong(p.vo2max[i].date)}</strong> · ${p.vo2max[i].vo2max != null ? F.num(p.vo2max[i].vo2max, 1) : "pas d'estimation (aucune séance de course qualifiante sur 30 j)"}`));
}

// ---------------------------------------------------------------------------
// Vue : Calendrier
// ---------------------------------------------------------------------------

async function viewCalendar(params) {
  const cal = await api("calendar");
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
    <div class="toolbar">${years.map((y) => `<a class="seg ${y === year ? "is-on" : ""}" href="#/calendrier?annee=${y}">${y}</a>`).join("")}</div>
    <section class="band"><div class="chart-host chart-host--cal">${yearCalendar(Number(year), byDate, value, bucket)}</div>
      <p class="legend legend--small">Moins <span class="key cal--1"></span><span class="key cal--2"></span><span class="key cal--3"></span><span class="legend__item"><span class="key cal--4"></span>Plus (&lt; 40 min, 40–75, 75–120, &gt; 2 h)</span></p></section>
    <section class="band"><h2>Distance cumulée</h2><p class="legend">${years.slice(-3).map((y, k, arr) => `<span class="key key--year-${arr.length - 1 - k}"></span>${y}`).join(" ")}</p>
      <div class="chart-host chart-host--nox">${cum.svg}</div></section>`;
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
  const chart = timeChart(dates, [
    { type: "line", values: weightSeries.map((p) => p.weight_avg7_kg), cls: "line line--weight-avg" },
    { type: "dots", values: weightSeries.map((p) => p.weight_kg_merged), cls: "dot dot--weight" },
  ], marks, { height: 200, label: "Poids quotidien, moyenne mobile 7 jours et cible", yFormat: (v) => F.weight(v) });
  const gapTxt = weight.gap_kg != null ? `${weight.gap_kg > 0 ? "+" : ""}${F.weight(weight.gap_kg)}` : "—";
  const slopeTxt = weight.slope_kg_per_week != null ? `${weight.slope_kg_per_week > 0 ? "+" : ""}${F.weightRate(weight.slope_kg_per_week)}` : "—";
  // `avg7_kg` (et `gap_kg`, qui en dérive) est TOUJOURS la valeur du jour même (jamais la
  // dernière moyenne non nulle trouvée plus tôt dans la fenêtre, voir arc_serve.py) : un
  // « — » ici signifie « pas assez de pesées récentes », pas une absence de data ancienne.
  const avg7Txt = weight.avg7_kg != null ? `${F.weight(weight.avg7_kg)}<small> au ${F.dayShort(weight.avg7_date)}</small>` : "—";
  const html = `<section class="band"><h2>Poids</h2>
    <p class="legend"><span class="legend__item"><span class="key key--weight"></span>Poids quotidien</span> <span class="legend__item"><span class="key key--weight-avg"></span>Moyenne 7 j</span>${weight.target_kg != null ? ` <span class="legend__item"><span class="key key--target"></span>Cible</span>` : ""}</p>
    <div class="chart-host" id="c-weight">${chart.svg}</div><p class="readout" id="r-weight"></p>
    <dl class="facts facts--inline">
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
      <a href="#/performance">Hypothèses des modèles</a></p>
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
      la valeur la plus simple à interpréter. <a href="#/performance">Hypothèses des modèles</a></p>
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
      compare JAMAIS à une autre. <a href="#/performance">Hypothèses des modèles</a></p>
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
        <a href="#/performance">Hypothèses des modèles</a></p>
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
      lecture. <a href="#/performance">Hypothèses des modèles</a></p>
    <p class="legend"><span class="legend__item"><span class="key key--durability-gap"></span>Fade GAP</span> <span class="legend__item"><span class="key key--durability-ef"></span>Fade EF</span></p>
    <div class="chart-host" id="c-durability">${chart.svg}</div><p class="readout" id="r-durability"></p>
    <dl class="facts facts--inline">
      <div><dt>Sorties longues (${trend.window_weeks} sem.)</dt><dd>${F.num(trend.long_runs)} <small class="muted">dont ${trend.measured_n} éligible${trend.measured_n > 1 ? "s" : ""}</small></dd></div>
      <div><dt>Fade GAP moyen</dt><dd>${trend.avg_gap_fade_pct != null ? `${trend.avg_gap_fade_pct > 0 ? "+" : ""}${F.num(trend.avg_gap_fade_pct, 1)} %<small class="muted"> sur ${trend.measured_n} sortie${trend.measured_n > 1 ? "s" : ""}</small>` : "—"}</dd></div>
    </dl></section>`;
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
      readout($("#r-weight"), `<strong>${F.dayLong(p.date)}</strong> · poids ${F.weight(p.weight_kg_merged)} · moyenne 7 j ${F.weight(p.weight_avg7_kg)}`);
    });
  }
  if (fuelingChart) {
    attachCursor($("#c-fueling"), fuelingChart, (i) => {
      const p = fuelingPoints[i];
      readout($("#r-fueling"), `<strong>${F.dayLong(p.date)}</strong> · glucides ${F.carbsRate(p.carbs_per_hour_g)} · sudation ${F.sweatRate(p.sweat_rate_l_h)}`);
    });
  }
}

async function viewFiles() {
  const { items } = await api("files", { fresh: true });
  main.innerHTML = `${header("Fichiers hors contrat", "Lus au mieux par le tableau de bord, mais sans bloc <code>```arc</code> valide.")}
    ${items.length ? `${note("Pour les mettre au contrat, lancez <code>/arc-backfill</code> dans votre IDE : le coach les reprend par lots, sans rien inventer, en conservant le texte existant.")}
      <ul class="list">${items.map((i) => `<li><code>${F.esc(i.path)}</code><span class="list__meta">${F.esc(i.status === "no" ? "illisible" : i.status === "invalid" ? "bloc invalide" : "lecture partielle")} — ${F.esc(i.issues.slice(0, 3).join(" · "))}</span></li>`).join("")}</ul>`
    : empty("Tout est au contrat", "Chaque fichier du workspace porte un bloc <code>```arc</code> valide.")}`;
}

// ---------------------------------------------------------------------------
// Vue : Décisions (#55) — journal chronologique, filtrable
// ---------------------------------------------------------------------------

/** Liens de filtre : conserve TOUJOURS les deux autres filtres (`déclencheur`,
 * `résultat`, `jours`) lors du changement d'un seul, pour que les trois se
 * combinent plutôt que s'écraser — même discipline que `viewSessions` (tri +
 * sport) et `viewAnalyse` (semaines + classe de descente). */
function decisionFilterHash({ trigger, outcome, days }) {
  const p = new URLSearchParams();
  if (trigger) p.set("declencheur", trigger);
  if (outcome) p.set("resultat", outcome);
  if (days) p.set("jours", String(days));
  return `#/decisions?${p}`;
}

async function viewDecisions(params) {
  const trigger = params.get("declencheur") || "";
  const outcome = params.get("resultat") || "";
  const daysRaw = params.get("jours");
  const days = daysRaw && /^\d+$/.test(daysRaw) ? Number(daysRaw) : null;
  const qs = new URLSearchParams();
  if (days) qs.set("days", String(days));
  if (trigger) qs.set("trigger", trigger);
  if (outcome) qs.set("outcome", outcome);
  const data = await api(`decisions?${qs}`);
  const list = data.decisions || [];
  const periods = [[30, "1 mois"], [90, "3 mois"], [365, "1 an"], [null, "Tout"]];
  const toolbarPeriods = periods.map(([d, l]) => {
    const on = d === days;
    return `<a class="seg ${on ? "is-on" : ""}" aria-current="${on ? "true" : "false"}" href="${decisionFilterHash({ trigger, outcome, days: d })}">${l}</a>`;
  }).join("");
  const triggerOptions = Object.entries(F.TRIGGER).map(([k, l]) => `<option value="${k}" ${k === trigger ? "selected" : ""}>${l}</option>`).join("");
  const outcomeOptions = Object.entries(F.DECISION_OUTCOME).map(([k, l]) => `<option value="${k}" ${k === outcome ? "selected" : ""}>${l}</option>`).join("");
  const items = list.map((d) => {
    const ruleTxt = (d.rules || []).map((r) => F.esc(r.label || r.rule_id)).join(", ");
    return `<li>
      <a href="#/decision?id=${encodeURIComponent(d.id)}"><strong>${F.esc(d.summary)}</strong></a>
      <span class="list__meta">${F.dayLong(d.date)} · ${triggerChip(d.trigger)} ${outcomeChip(d.outcome)}${ruleTxt ? ` · ${ruleTxt}` : ""}${d.supersedes ? " · remplace une décision précédente" : ""}</span>
    </li>`;
  }).join("");
  main.innerHTML = `${header("Décisions", `Journal des ajustements du coach : ce qui a changé, ce qui l'a justifié. <a href="${GUARDRAILS_DOC_URL}" rel="noopener noreferrer">Garde-fous</a>`)}
    <div class="toolbar">${toolbarPeriods}
      <label class="select">Déclencheur : <select id="f-declencheur"><option value="">Tous</option>${triggerOptions}</select></label>
      <label class="select">Résultat : <select id="f-resultat"><option value="">Tous</option>${outcomeOptions}</select></label>
    </div>
    ${list.length ? `<ul class="list">${items}</ul>`
      : empty("Aucune décision sur cette période", "Le coach écrit une décision quand il ajuste, allège ou reporte une séance — bilan matinal, garde-fou, ou demande de l'athlète.")}`;
  $("#f-declencheur").addEventListener("change", (e) => { location.hash = decisionFilterHash({ trigger: e.target.value, outcome, days }); });
  $("#f-resultat").addEventListener("change", (e) => { location.hash = decisionFilterHash({ trigger, outcome: e.target.value, days }); });
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
  const before = d.before || {}, after = d.after || {};
  const diffKeys = [...new Set([...Object.keys(before), ...Object.keys(after)])];
  const diffHtml = diffKeys.length
    ? `<table class="data data--compact"><thead><tr><th scope="col">Champ</th><th scope="col">Avant</th><th scope="col">Après</th></tr></thead>
        <tbody>${diffKeys.map((k) => `<tr><th scope="row">${F.esc(k)}</th><td>${F.esc(before[k] ?? "—")}</td><td>${F.esc(after[k] ?? "—")}</td></tr>`).join("")}</tbody></table>` : "";
  const inputsHtml = d.inputs && Object.keys(d.inputs).length
    ? `<ul>${Object.entries(d.inputs).map(([k, v]) => `<li><code>${F.esc(k)}</code> : ${F.esc(String(v))}</li>`).join("")}</ul>` : "";
  const rulesHtml = (d.rules || []).length
    ? `<ul>${d.rules.map((r) => `<li>${F.esc(r.label || r.rule_id)} <span class="muted">(${r.rule_id}${r.default_severity ? ` · ${r.default_severity}` : ""})</span></li>`).join("")}</ul>` : "";
  const sourcesHtml = (d.source_links || []).length
    ? `<p>${d.source_links.map((sl) => sl.route ? `<a href="${sl.route}">${F.esc(sl.label)}</a>` : F.esc(sl.label)).join(", ")}</p>` : "";
  main.innerHTML = `${header(d.summary, `${F.dayLong(d.date)} · ${triggerChip(d.trigger)} ${outcomeChip(d.outcome)}`)}
    <p><a href="#/decisions">← Toutes les décisions</a></p>
    ${d.outcome === "proposed" ? note("En attente de ta confirmation.") : ""}
    ${diffHtml ? `<section class="band"><h2>Avant / après</h2>${diffHtml}</section>` : ""}
    ${inputsHtml ? `<section class="band"><h2>Données</h2>${inputsHtml}</section>` : ""}
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
  performance: viewPerformance, calendrier: viewCalendar, rapports: viewReports, rapport: viewReport,
  nutrition: viewNutrition, fichiers: viewFiles, decisions: viewDecisions, decision: viewDecision,
};

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
