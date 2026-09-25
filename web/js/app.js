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
    ["", "Aujourd'hui"], ["forme", "Forme & charge"], ["sante", "Santé"], ["semaine", "Semaine"],
    ["seances", "Séances"], ["performance", "Performance"], ["calendrier", "Calendrier"],
    ["rapports", "Rapports"], ...(nutrition ? [["nutrition", "Nutrition"]] : []),
  ];
  $("#nav").innerHTML = items.map(([h, l]) => `<a href="#/${h}" data-route="${h}">${l}</a>`).join("")
    + (s.incomplete_files ? `<a href="#/fichiers" data-route="fichiers" class="nav__debt">${s.incomplete_files} fichier${s.incomplete_files > 1 ? "s" : ""} hors contrat</a>` : "");
}

function markNav(route) {
  for (const a of document.querySelectorAll("#nav a")) {
    const on = a.dataset.route === route || (route === "seance" && a.dataset.route === "seances") || (route === "rapport" && a.dataset.route === "rapports");
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

async function viewToday() {
  const s = SUMMARY;
  const [health, week, form, reports] = await Promise.all([
    api("health?days=14"), api("week"), api("form?days=30"), api("reports"),
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
  const [form, load, decoupling] = await Promise.all([api(`form?days=${days}`), api("load?weeks=26"), api("decoupling")]);
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

  const periods = [[90, "3 mois"], [180, "6 mois"], [365, "1 an"]].map(([d, l]) => `<a class="seg ${d === days ? "is-on" : ""}" href="#/forme?jours=${d}">${l}</a>`).join("");
  const last = series[series.length - 1];
  const { html: decouplingHtml, chart: decouplingChart, points: decouplingPoints } = decouplingSection(decoupling);
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
      <dl class="facts facts--inline"><div><dt>Monotonie (7 j)</dt><dd>${F.num(load.monotony, 2)}</dd></div><div><dt>Strain (7 j)</dt><dd>${F.num(load.strain)}</dd></div><div><dt>Charge du jour</dt><dd>${F.num(last.load)}</dd></div></dl></section>
    ${polarisationSection(load.polarisation_weeks, load.hr_zones_reason)}
    ${decouplingHtml}`;

  attachCursor($("#c-form"), chart, (i) => {
    const p = series[i];
    readout($("#r-form"), `<strong>${F.dayLong(p.date)}</strong> · charge ${F.num(p.load)} · condition ${F.num(p.fitness, 1)} · fatigue ${F.num(p.fatigue, 1)} · forme ${p.form > 0 ? "+" : ""}${F.num(p.form, 1)} · ACWR ${F.num(p.acwr, 2)}`);
  });
  attachCursor($("#c-acwr"), acwr, () => {});
  attachCursor($("#c-load"), loadChart, (i) => {
    const w = weeks[i];
    readout($("#r-load"), `<strong>Semaine du ${F.dayShort(w.week_start)}</strong> · ${w.sessions} séance${w.sessions > 1 ? "s" : ""} · ${F.hours(w.duration_s)} · ${F.distance(w.distance_m)}${trail ? ` · ${F.elevation(w.elevation_m)} D+${w.effort_km ? ` · ${F.num(w.effort_km, 1)} km-effort` : ""}` : ` · ${F.pace(w.distance_m, w.duration_s)}`} · charge ${F.num(w.load)}`);
  });
  wirePolarisationChart(load.polarisation_weeks);
  if (decouplingChart) {
    attachCursor($("#c-decoupling"), decouplingChart, (i) => {
      const p = decouplingPoints[i];
      readout($("#r-decoupling"), `<strong>${F.dayLong(p.date)}</strong> · ${F.esc(p.name || F.SPORT[p.sport] || p.sport)} · découplage ${F.num(p.decoupling_pct, 1)} %${p.ef_whole != null ? ` · EF ${F.num(p.ef_whole, 2)}` : ""}`);
    });
  }
}

/** Section « Polarisation 80/20 » de Forme & charge (#43) : une barre empilée par
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
  const periods = [[30, "1 mois"], [90, "3 mois"], [180, "6 mois"]].map(([d, l]) => `<a class="seg ${d === days ? "is-on" : ""}" href="#/sante?jours=${d}">${l}</a>`).join("");
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
    ...(a.decoupling_pct != null ? [["Découplage aérobie (Pa:HR)",
      `<span class="${a.decoupling_pct <= 5 ? "pos" : "neg"}">${a.decoupling_pct > 0 ? "+" : ""}${F.num(a.decoupling_pct, 1)} %</span>${a.ef_whole != null ? `<small class="muted"> · EF ${F.num(a.ef_whole, 2)}</small>` : ""}`]] : []),
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
      <tbody>${all.map((x) => `<tr><td>${x.km}</td>${byKm ? "" : `<td class="num">${x.distance_m != null ? F.distance(x.distance_m, 2) : "—"}</td>`}<td class="num">${F.clock(x.duration_s).replace(/^0:/, "")}</td>${byKm ? "" : `<td class="num">${lapPace(x)}</td>`}${hasGap ? `<td class="num">${F.paceFromSecPerKm(x.gap_pace_s_km)}</td>` : ""}<td class="num">${x.elev_gain_m != null ? `+${F.num(x.elev_gain_m)} / -${F.num(x.elev_loss_m)}` : "—"}</td><td class="num">${F.num(x.avg_hr_bpm)}</td><td class="num">${F.num(x.cadence_spm)}</td><td>${F.esc(x.label || "")}</td></tr>`).join("")}</tbody></table></div></section>`;
    setTimeout(() => attachCursor($("#c-splits"), c, (i) => {
      const x = sp[i];
      const what = byKm ? F.clock(x.duration_s).replace(/^0:/, "") : `${F.distance(x.distance_m, 2)} en ${F.clock(x.duration_s).replace(/^0:/, "")} (${lapPace(x)})`;
      readout($("#r-splits"), `<strong>${unit} ${x.km}</strong> · ${what}${x.gap_pace_s_km != null ? ` · GAP ${F.paceFromSecPerKm(x.gap_pace_s_km)}` : ""} · FC ${F.num(x.avg_hr_bpm)}${x.elev_gain_m != null ? ` · +${F.num(x.elev_gain_m)} m` : ""}${x.label ? ` · ${F.esc(x.label)}` : ""}`);
    }), 0);
  }
  const wx = d.weather;
  main.innerHTML = `${header(a.name || F.SPORT[a.sport] || "Séance", `${F.dayLong(a.date)} · ${F.SPORT[a.sport] || a.sport}${a.location ? " · " + F.esc(a.location) : ""}`)}
    <p><a href="#/seances">← Toutes les séances</a></p>
    <dl class="facts facts--grid">${facts.map(([k, v]) => `<div><dt>${k}</dt><dd>${v}</dd></div>`).join("")}</dl>
    ${wx ? `<p class="weather">${weatherChip(wx.category)} <span>${F.esc(wx.location)} · ${F.num(wx.temp_min_c)}–${F.num(wx.temp_max_c)} °C · vent ${F.num(wx.wind_kmh)} km/h</span></p>` : ""}
    ${splitsHtml}
    ${hrZoneSection(d.hr_zones)}
    <section class="band prose"><h2>Analyse du coach</h2>${d.body_html || "<p class=\"muted\">Pas de texte.</p>"}<p class="muted source">Source : <code>${F.esc(a.source_path)}</code></p></section>`;
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

/** Section « Découplage aérobie » de Forme & charge (#45) : un point par sortie
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
    { type: "hline", value: 5, cls: "mark mark--decoupling-good", label: "Repère 5 %" },
    { type: "dots", values: points.map((p) => p.decoupling_pct), cls: "dot dot--decoupling" },
  ], [], {
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
// Routeur
// ---------------------------------------------------------------------------

const ROUTES = {
  "": viewToday, forme: viewForm, sante: viewHealth, semaine: viewWeek, seances: viewSessions,
  performance: viewPerformance, calendrier: viewCalendar, rapports: viewReports, rapport: viewReport,
  nutrition: viewNutrition, fichiers: viewFiles,
};

async function route() {
  const hash = location.hash.replace(/^#\/?/, "");
  const [path, query] = hash.split("?");
  const params = new URLSearchParams(query || "");
  const [name, arg] = path.split("/");
  markNav(name);
  main.setAttribute("aria-busy", "true");
  try {
    if (name === "seance" && arg) await viewSession(Number(arg));
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
