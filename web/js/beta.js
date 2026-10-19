// Design bêta « roadbook » du tableau de bord (opt-in, `js/early.js`) : la saison comme le
// roadbook d'une course. Le bloc d'entraînement est dessiné comme un profil coupé en sections
// jusqu'à l'arrivée, et chaque jour se lit comme une feuille de ravito.
//
// Ce module ne lit AUCUNE donnée par lui-même : les vues reçoivent l'`api()` en cache, le
// résumé et les petits composants de `app.js` (même source, mêmes règles). Il ne remplace que
// la coque (navigation) et les vues Aujourd'hui et Semaine ; les autres vues gardent leur
// rendu et prennent l'habillage par les jetons de `css/beta.css`.
import * as F from "./format.js";
import { navItems } from "./nav.js";

export const BETA = document.documentElement.dataset.design === "roadbook";

const NB = " ";
const $ = (sel, root = document) => root.querySelector(sel);

// La CSP (`style-src 'self'`) interdit l'attribut `style=` dans le HTML injecté : les positions
// calculées passent par `data-vars="--x:12%;--w:3%"` puis par le CSSOM, qu'elle autorise.
function applyVars(root) {
  for (const el of root.querySelectorAll("[data-vars]")) {
    for (const decl of el.dataset.vars.split(";")) {
      const i = decl.indexOf(":");
      if (i > 0) el.style.setProperty(decl.slice(0, i).trim(), decl.slice(i + 1).trim());
    }
  }
}

// ---------------------------------------------------------------------------
// Coque : rail (ordinateur), barre du bas et feuille « Sections » (téléphone)
// ---------------------------------------------------------------------------

// Regroupement des sections de `navItems` (la liste reste UNE, dans nav.js) : une route
// absente de ces groupes rejoint le dernier, jamais perdue.
const GROUPS = [
  ["Au quotidien", ["", "semaine", "coach-chat"]],
  ["Entraînement", ["seances", "calendrier", "analyse", "forme", "performance"]],
  ["Corps et matériel", ["sante", "nutrition", "materiel"]],
  ["Course", ["roadbook", "trail-shape"]],
  ["Journal", ["decisions", "rapports", "hypotheses", "synchro"]],
];

// Icônes dessinées sur une grille de 24, trait de 1,75 : une seule famille.
const ICON = {
  today: '<path d="M3 18.5h18"/><path d="M6.5 18.5a5.5 5.5 0 0 1 11 0"/><path d="M12 5v3M5.2 8.7l2 2M18.8 8.7l-2 2"/>',
  week: '<rect x="3.5" y="5" width="17" height="15" rx="2"/><path d="M3.5 10h17M8 3v4M16 3v4M7.5 14h3M13.5 14h3M7.5 17h3"/>',
  health: '<path d="M12 20s-7.5-4.6-7.5-10.2A4.2 4.2 0 0 1 12 7.3a4.2 4.2 0 0 1 7.5 2.5C19.5 15.4 12 20 12 20Z"/><path d="M7.8 12.2h2.4l1.3-2.2 1.9 4.2 1.2-2h1.6"/>',
  coach: '<path d="M5 5h14a1.5 1.5 0 0 1 1.5 1.5v9A1.5 1.5 0 0 1 19 17h-8l-4.5 3.5V17H5a1.5 1.5 0 0 1-1.5-1.5v-9A1.5 1.5 0 0 1 5 5Z"/><path d="M8 10h8M8 13h5"/>',
  course: '<path d="M5.5 21V3.5"/><path d="M5.5 4h12l-2.4 4.2 2.4 4.3h-12"/>',
  sections: '<path d="M9 6.5h11M9 12h11M9 17.5h11"/><path d="M4 5.5h2v2H4zM4 11h2v2H4zM4 16.5h2v2H4z"/>',
  close: '<path d="M6 6l12 12M18 6 6 18"/>',
};
const icon = (name) => `<svg class="rk-icon" viewBox="0 0 24 24" aria-hidden="true">${ICON[name]}</svg>`;
const ARROW = '<svg viewBox="0 0 24 12" aria-hidden="true"><path d="M1 6h20M16 1.5 21.5 6 16 10.5"/></svg>';
const ARROW_BACK = '<svg viewBox="0 0 24 12" aria-hidden="true"><path d="M23 6H3M8 1.5 2.5 6 8 10.5"/></svg>';

function sectionLinks(settings, page, roadbook) {
  const items = navItems(settings || {}, { roadbook });
  if (page === "chat" || (settings && settings.chat_enabled)) items.push(["coach-chat", "Coach"]);
  const href = (route) => {
    if (route === "coach-chat") return "chat.html";
    return page === "chat" ? `index.html#/${route}` : `#/${route}`;
  };
  return items.map(([route, label]) => ({ route, label, href: href(route) }));
}

function groupedNavHtml(links, page) {
  const known = new Set(GROUPS.flatMap(([, ids]) => ids));
  const groups = GROUPS.map(([title, ids]) => [title, ids.map((id) => links.find((l) => l.route === id)).filter(Boolean)]);
  const rest = links.filter((l) => !known.has(l.route));
  if (rest.length) groups[groups.length - 1][1].push(...rest);
  return groups.filter(([, ls]) => ls.length).map(([title, ls]) => `<div class="rk-navgroup"><p class="rk-navgroup__title">${title}</p>
    ${ls.map((l) => `<a href="${l.href}" data-route="${l.route}"${page === "chat" && l.route === "coach-chat" ? ' aria-current="page"' : ""}>${F.esc(l.label)}</a>`).join("")}</div>`).join("");
}

const classicLink = `<a class="rk-classic" href="?design=classic">Revenir au design actuel</a>`;

/** Monte la coque bêta. `debt` : liens « fichiers hors contrat » déjà rendus par app.js. */
export function mountShell({ settings, page = "app", debt = "", roadbook = false }) {
  const links = sectionLinks(settings, page, roadbook);
  const nav = $("#nav");
  if (nav) {
    nav.classList.add("rk-rail");
    nav.innerHTML = `${groupedNavHtml(links, page)}${debt ? `<div class="rk-navgroup rk-navgroup--debt">${debt}</div>` : ""}<div class="rk-rail__foot">${classicLink}</div>`;
  }

  const coach = page === "chat" || (settings && settings.chat_enabled);
  const tabs = [
    { route: "", label: "Aujourd'hui", icon: "today" },
    { route: "semaine", label: "Semaine", icon: "week" },
    { route: "sante", label: "Santé", icon: "health" },
    coach ? { route: "coach-chat", label: "Coach", icon: "coach" } : { route: "trail-shape", label: "Course", icon: "course" },
  ];
  const tabHref = (r) => (r === "coach-chat" ? "chat.html" : page === "chat" ? `index.html#/${r}` : `#/${r}`);
  const bar = document.createElement("nav");
  bar.className = "rk-tabbar";
  bar.setAttribute("aria-label", "Sections principales");
  bar.innerHTML = tabs.map((t) => `<a href="${tabHref(t.route)}" data-route="${t.route}"${page === "chat" && t.route === "coach-chat" ? ' aria-current="page"' : ""}>${icon(t.icon)}<span>${t.label}</span></a>`).join("")
    + `<button type="button" class="rk-tabbar__more" aria-haspopup="dialog" aria-controls="rk-sheet">${icon("sections")}<span>Sections</span></button>`;
  document.body.appendChild(bar);

  const sheet = document.createElement("dialog");
  sheet.className = "rk-sheet";
  sheet.id = "rk-sheet";
  sheet.setAttribute("aria-labelledby", "rk-sheet-title");
  sheet.innerHTML = `<div class="rk-sheet__bar"><p class="rk-sheet__title" id="rk-sheet-title">Toutes les sections</p>
      <button type="button" class="rk-sheet__close" aria-label="Fermer">${icon("close")}</button></div>
    <nav class="rk-sheet__nav" aria-labelledby="rk-sheet-title">${groupedNavHtml(links, page)}${debt ? `<div class="rk-navgroup rk-navgroup--debt">${debt}</div>` : ""}</nav>
    <div class="rk-sheet__foot">${classicLink}</div>`;
  document.body.appendChild(sheet);
  bar.querySelector(".rk-tabbar__more").addEventListener("click", () => sheet.showModal());
  sheet.querySelector(".rk-sheet__close").addEventListener("click", () => sheet.close());
  // Clic hors de la feuille (sur le fond), sur un lien, ou changement de vue : on referme.
  sheet.addEventListener("click", (ev) => {
    if (ev.target === sheet || ev.target.closest("a")) sheet.close();
  });
  window.addEventListener("hashchange", () => { if (sheet.open) sheet.close(); });
}

/** Les sélecteurs de liens de navigation que `markNav` doit marquer en bêta. */
export const NAV_LINKS = "#nav a, .rk-tabbar a, .rk-sheet a";

// ---------------------------------------------------------------------------
// Profil du bloc : la saison dessinée comme un profil de course
// ---------------------------------------------------------------------------

const MONTH = new Intl.DateTimeFormat("fr-FR", { month: "short" });
const PHASE_SHORT = { base: "Base", development: "Développement", specific: "Spécifique", taper: "Affûtage", recovery: "Récupération" };

// Profil adouci (spline cardinale bornée) : le dessin reste au-dessus de la ligne de base.
function smoothPath(points, H) {
  if (!points.length) return "";
  let d = `M${points[0][0].toFixed(1)},${points[0][1].toFixed(1)}`;
  for (let i = 0; i < points.length - 1; i += 1) {
    const p0 = points[i - 1] || points[i], p1 = points[i], p2 = points[i + 1], p3 = points[i + 2] || p2;
    const c1 = [p1[0] + (p2[0] - p0[0]) / 6, Math.min(H, p1[1] + (p2[1] - p0[1]) / 6)];
    const c2 = [p2[0] - (p3[0] - p1[0]) / 6, Math.min(H, p2[1] - (p3[1] - p1[1]) / 6)];
    d += ` C${c1[0].toFixed(1)},${c1[1].toFixed(1)} ${c2[0].toFixed(1)},${c2[1].toFixed(1)} ${p2[0].toFixed(1)},${p2[1].toFixed(1)}`;
  }
  return d;
}

/**
 * Le profil du bloc : une colonne par semaine, de la première semaine planifiée au jour de
 * course. Hauteur = volume hebdomadaire PRÉVU (durée), aire pleine = réalisé. Les semaines
 * sans fichier de semaine jusqu'à la course sont dites « à planifier », jamais inventées.
 * Renvoie `{ html, mount }` ; vide si ni bloc ni objectif.
 */
export function ribbon(block, summary, { selected = null } = {}) {
  const today = summary.today;
  const objective = summary.objective || {};
  const raceDate = (block && block.race && block.race.date) || objective.race_date || null;
  const raceName = (block && block.race && block.race.name) || objective.name || "Course";
  const blockWeeks = block && block.status === "ok" ? block.weeks : [];
  if (!blockWeeks.length && !raceDate) return { html: "", mount() {} };

  const weeks = blockWeeks.map((w) => ({ ...w }));
  const mondayOf = (iso) => F.addDays(iso, -((F.parseDate(iso).getDay() + 6) % 7));
  // Course passée (objectif terminé, pas encore remplacé) : on ne prolonge pas le profil vers
  // elle ; elle n'apparaît que si elle tombe dans les semaines du bloc.
  const racePast = Boolean(raceDate) && raceDate < today;
  if (raceDate && !racePast) {
    const raceMonday = mondayOf(raceDate);
    let next = weeks.length ? F.addDays(weeks[weeks.length - 1].week_start, 7) : mondayOf(today);
    while (next <= raceMonday) {
      weeks.push({ week_start: next, gap: true, planned: false, is_race_week: next === raceMonday, status: next <= today ? "past" : "future" });
      next = F.addDays(next, 7);
    }
    const last = weeks[weeks.length - 1];
    if (last && last.week_start === raceMonday) last.is_race_week = true;
  }
  if (!weeks.length) return { html: "", mount() {} };

  const start = weeks[0].week_start;
  const lastEnd = F.addDays(weeks[weeks.length - 1].week_start, 7);
  const end = raceDate && !racePast && F.addDays(raceDate, 1) > lastEnd ? F.addDays(raceDate, 1) : lastEnd;
  const raceShown = Boolean(raceDate) && raceDate >= start && raceDate < end;
  const todayShown = today >= start && today < end;
  const span = Math.max(1, F.daysBetween(start, end));
  const X = (iso) => Math.max(0, Math.min(1000, (F.daysBetween(start, iso) / span) * 1000));
  const H = 100, TOP = 12;
  const vol = (w) => (w.gap ? null : (w.target_duration_s || (w.done && w.done.duration_s) || 0));
  const peak = Math.max(1, ...weeks.map((w) => Math.max(vol(w) || 0, (w.done && w.done.duration_s) || 0)));
  const y = (v) => H - (v / peak) * (H - TOP);

  // Profil prévu : un point au milieu de chaque semaine planifiée, posé à la base aux bords.
  const planned = weeks.filter((w) => !w.gap);
  let profile = "", plannedArea = "", doneArea = "";
  if (planned.length) {
    const pts = [[X(planned[0].week_start), H], ...planned.map((w) => [X(F.addDays(w.week_start, 3)) + 500 / span, y(vol(w))]),
      [X(F.addDays(planned[planned.length - 1].week_start, 7)), H]];
    profile = smoothPath(pts, H);
    plannedArea = `${profile} Z`;
    const past = planned.filter((w) => w.done && w.week_start <= today);
    if (past.length) {
      const dpts = [[X(past[0].week_start), H], ...past.map((w) => [Math.min(X(F.addDays(w.week_start, 3)) + 500 / span, X(today)), y(Math.min(peak, w.done.duration_s || 0))]),
        [Math.min(X(today), X(F.addDays(past[past.length - 1].week_start, 7))), H]];
      doneArea = `${smoothPath(dpts, H)} Z`;
    }
  }
  const gaps = weeks.filter((w) => w.gap);
  const gapLine = gaps.length ? `<path class="rk-profile__gap" d="M${X(gaps[0].week_start).toFixed(1)},${H - 1} L${X(end).toFixed(1)},${H - 1}"/>` : "";

  // Sections : suites de semaines de même phase (les trous forment « À planifier »).
  const runs = [];
  for (const w of weeks) {
    const key = w.gap ? "gap" : (w.phase || "unknown");
    const lastRun = runs[runs.length - 1];
    if (lastRun && lastRun.key === key) lastRun.weeks.push(w);
    else runs.push({ key, weeks: [w], label: w.gap ? "À planifier" : (w.phase_label || PHASE_SHORT[w.phase] || "Phase non renseignée") });
  }
  const sections = runs.map((r) => {
    const a = X(r.weeks[0].week_start), b = Math.min(1000, X(F.addDays(r.weeks[r.weeks.length - 1].week_start, 7)));
    return { ...r, a, b };
  });

  // Repères de mois (« 1 oct. ») le long de la ligne de base.
  const months = [];
  for (let d = F.addDays(start, 1); d < end; d = F.addDays(d, 1)) {
    if (d.endsWith("-01")) months.push({ x: X(d), label: `1${NB}${MONTH.format(F.parseDate(d))}` });
  }
  const todayX = X(today);
  const raceX = raceShown ? X(raceDate) : null;
  const sel = selected ? weeks.find((w) => w.week_start === selected) : null;
  const pct = (x) => `${(x / 10).toFixed(2)}%`;

  const describe = (w, i) => {
    const bits = [`Semaine du ${F.dayShort(w.week_start)}`];
    if (w.gap) bits.push(w.is_race_week ? "semaine de course, pas encore planifiée" : "à planifier");
    else {
      bits.push(w.phase_label || PHASE_SHORT[w.phase] || "phase non renseignée");
      bits.push(w.target_duration_s ? `prévu ${F.hours(w.target_duration_s)}` : "volume prévu non renseigné");
      if (w.done && w.week_start <= today) bits.push(`réalisé ${F.hours(w.done.duration_s)}${w.done.partial ? " (en cours)" : ""}`);
      if (w.is_race_week) bits.push("semaine de course");
    }
    return bits.join(" · ");
  };
  const current = weeks.findIndex((w) => w.week_start <= today && today < F.addDays(w.week_start, 7));
  const initial = sel ? describe(sel, weeks.indexOf(sel)) : current >= 0 ? describe(weeks[current], current)
    : today >= end ? `Bloc terminé le ${F.dateLong(F.addDays(end, -1))}` : raceShown ? `${raceName} le ${F.dateLong(raceDate)}` : "";

  const html = `<figure class="rk-profile" aria-labelledby="rk-profile-cap">
    <div class="rk-profile__plot">
      <svg class="rk-profile__svg" viewBox="0 0 1000 ${H}" preserveAspectRatio="none" aria-hidden="true">
        ${sections.slice(1).map((s) => `<line class="rk-profile__cut" x1="${s.a.toFixed(1)}" y1="0" x2="${s.a.toFixed(1)}" y2="${H}"/>`).join("")}
        ${sel ? `<rect class="rk-profile__sel" x="${X(sel.week_start).toFixed(1)}" y="0" width="${(X(F.addDays(sel.week_start, 7)) - X(sel.week_start)).toFixed(1)}" height="${H}"/>` : ""}
        ${plannedArea ? `<path class="rk-profile__area" d="${plannedArea}"/>` : ""}
        ${doneArea ? `<path class="rk-profile__done" d="${doneArea}"/>` : ""}
        ${profile ? `<path class="rk-profile__line" d="${profile}"/>` : ""}
        ${gapLine}
        ${weeks.slice(1).map((w) => `<line class="rk-profile__tick" x1="${X(w.week_start).toFixed(1)}" y1="${H - 4}" x2="${X(w.week_start).toFixed(1)}" y2="${H}"/>`).join("")}
        <line class="rk-profile__base" x1="0" y1="${H - 0.5}" x2="1000" y2="${H - 0.5}"/>
      </svg>
      ${todayShown ? `<span class="rk-pin${todayX < 110 ? " is-start" : todayX > 890 ? " is-end" : ""}" data-vars="--x:${pct(todayX)}"><span class="rk-pin__label">Vous êtes ici</span></span>` : ""}
      ${raceX !== null ? `<span class="rk-finish${raceX < 550 ? " is-left" : ""}" data-vars="--x:${pct(raceX)}"><span class="rk-finish__label" title="${F.esc(raceName)}"><span class="rk-finish__name">${F.esc(raceName)}</span><small>${racePast ? "couru le " : ""}${F.dayShort(raceDate)}</small></span></span>` : ""}
      <div class="rk-profile__hits">${weeks.map((w, i) => `<a class="rk-profile__hit${w.week_start === selected ? " is-selected" : ""}" data-vars="--a:${pct(X(w.week_start))};--w:${pct(X(F.addDays(w.week_start, 7)) - X(w.week_start))}" href="#/semaine?debut=${w.week_start}" data-i="${i}" aria-label="${F.esc(describe(w, i))}"></a>`).join("")}</div>
    </div>
    ${months.length ? `<ol class="rk-profile__months" aria-hidden="true">${months.map((m) => `<li class="rk-profile__month" data-vars="--x:${pct(m.x)}">${m.label}</li>`).join("")}</ol>` : ""}
    <ol class="rk-profile__sections">${sections.map((s) => `<li class="rk-profile__section rk-profile__section--${s.key}" data-vars="--a:${pct(s.a)};--w:${pct(s.b - s.a)}"><span>${F.esc(s.label)}</span></li>`).join("")}</ol>
    <figcaption class="rk-profile__cap" id="rk-profile-cap"><span class="rk-profile__readout" aria-live="polite">${F.esc(initial)}</span><span class="rk-profile__legend">hauteur : volume prévu par semaine · plein : réalisé</span></figcaption>
  </figure>`;

  const mount = () => {
    const fig = $(".rk-profile");
    if (!fig) return;
    const out = fig.querySelector(".rk-profile__readout");
    const base = out.textContent;
    const show = (ev) => {
      const a = ev.target.closest && ev.target.closest(".rk-profile__hit");
      if (a) out.textContent = describe(weeks[Number(a.dataset.i)], Number(a.dataset.i));
    };
    fig.addEventListener("pointerover", show);
    fig.addEventListener("focusin", show);
    fig.addEventListener("pointerleave", () => { out.textContent = base; });
    fig.addEventListener("focusout", (ev) => { if (!fig.contains(ev.relatedTarget)) out.textContent = base; });
  };
  return { html, mount };
}

// ---------------------------------------------------------------------------
// Feuilles de roadbook
// ---------------------------------------------------------------------------

function sheet({ title, meta = "", body, cls = "", level = 2, id = "" }) {
  const hid = id || `rk-${Math.random().toString(36).slice(2, 8)}`;
  return `<section class="rk-sheet-card ${cls}" aria-labelledby="${hid}">
    <header class="rk-sheet-card__head"><h${level} id="${hid}">${title}</h${level}>${meta ? `<span class="rk-sheet-card__meta">${meta}</span>` : ""}</header>
    <div class="rk-sheet-card__body">${body}</div></section>`;
}

// Marque d'état d'une ligne de barrière : forme ET mot, jamais la couleur seule.
const STATE_WORD = { ok: "dans la cible", warn: "à surveiller", bad: "hors cible", none: "pas de mesure" };
const stateMark = (state, word) => `<span class="rk-state rk-state--${state}"><svg viewBox="0 0 12 12" aria-hidden="true">${
  state === "ok" ? '<circle cx="6" cy="6" r="4.5"/>' : state === "warn" ? '<path d="M6 1.2 11 10.5H1Z"/>' : state === "bad" ? '<rect x="1.6" y="1.6" width="8.8" height="8.8" transform="rotate(45 6 6)"/>' : '<path d="M1.5 6h9"/>'
}</svg>${F.esc(word || STATE_WORD[state])}</span>`;

function checkRows(health, summary) {
  const mode = health.morning_check;
  const series = health.series || [];
  const today = summary.today;
  const h = series.find((p) => p.date === today) || null;
  const latest = h || [...series].reverse().find((p) => p.readiness_score !== undefined || p.hrv_overnight_ms !== undefined) || {};
  const rows = [];
  if (mode === "full") {
    const lo = latest.hrv_baseline_low_ms, hi = latest.hrv_baseline_high_ms, v = latest.hrv_overnight_ms;
    if (v != null && lo != null && hi != null) {
      const inBand = v >= lo && v <= hi;
      rows.push({ label: "HRV nocturne", value: `${F.num(v)}${NB}ms`, ref: `bande ${F.num(lo)}–${F.num(hi)}`,
        state: inBand ? "ok" : "warn", word: v < lo ? "sous la bande" : v > hi ? "au-dessus de la bande" : "dans la bande" });
    } else {
      rows.push({ label: "HRV nocturne", value: v != null ? `${F.num(v)}${NB}ms` : "—",
        ref: latest.hrv_personal_status === "en_construction" ? "référence en construction" : "bande non renseignée", state: "none", word: v != null ? "sans référence" : "pas de mesure" });
    }
    const d = latest.rhr_delta;
    rows.push({ label: "FC de repos", value: latest.resting_hr_bpm != null ? `${F.num(latest.resting_hr_bpm)}${NB}bpm` : "—",
      ref: latest.rhr_median7 != null ? `médiane 7${NB}j ${F.num(latest.rhr_median7)}` : "médiane indisponible",
      state: d == null ? "none" : d > 7 ? "bad" : d >= 5 ? "warn" : "ok",
      word: d == null ? "pas de comparaison" : `${d > 0 ? "+" : ""}${F.num(d)} sur la médiane` });
  }
  const r = latest.readiness_score;
  rows.push({ label: "Readiness", value: r != null ? `${F.num(r)}<small>/100</small>` : "—", ref: "seuil 60", raw: true,
    state: r == null ? "none" : r >= 60 ? "ok" : r >= 40 ? "warn" : "bad", word: r == null ? "pas de mesure" : r >= 60 ? "prêt" : r >= 40 ? "modérée" : "faible" });
  if (mode === "full") {
    const ss = latest.sleep_score;
    rows.push({ label: "Sommeil", value: latest.sleep_total_s ? F.duration(latest.sleep_total_s) : "—", ref: ss != null ? `score ${F.num(ss)}` : "score non renseigné",
      state: ss == null ? "none" : ss >= 80 ? "ok" : ss >= 60 ? "warn" : "bad", word: ss == null ? "sans score" : ss >= 80 ? "bon" : ss >= 60 ? "moyen" : "court" });
    const debt = summary.sleep_debt;
    if (debt && debt.sleep_debt_7d_s != null) {
      const hrs = debt.sleep_debt_7d_s / 3600;
      const warnH = health.thresholds?.sleep_debt_warn_h ?? 5, alertH = health.thresholds?.sleep_debt_alert_h ?? 10;
      rows.push({ label: "Dette de sommeil", value: `${F.num(hrs, 1)}${NB}h`, ref: `7 nuits · besoin ${F.duration(debt.sleep_need_s)}`,
        state: hrs > alertH ? "bad" : hrs > warnH ? "warn" : "ok", word: hrs > alertH ? "élevée" : hrs > warnH ? "à surveiller" : "faible" });
    }
  }
  const stale = latest.date && latest.date !== today ? latest.date : null;
  return { rows, stale, mode };
}

function rowsTable(rows, caption) {
  return `<table class="rk-cutoffs"><caption class="sr-only">${F.esc(caption)}</caption>
    <thead class="sr-only"><tr><th scope="col">Mesure</th><th scope="col">Valeur</th><th scope="col">Référence</th><th scope="col">État</th></tr></thead>
    <tbody>${rows.map((r) => `<tr class="rk-cutoffs__row rk-cutoffs__row--${r.state}"><th scope="row">${F.esc(r.label)}</th>
      <td class="rk-cutoffs__value">${r.raw ? r.value : F.esc(r.value)}</td><td class="rk-cutoffs__ref">${F.esc(r.ref)}</td>
      <td class="rk-cutoffs__state">${r.state ? stateMark(r.state, r.word) : ""}</td></tr>`).join("")}</tbody></table>`;
}

/** Lectures sans barrière (forme, réalisé) : libellé, valeur, repère — des lignes, pas des tuiles. */
function readings(rows, caption) {
  return `<table class="rk-readings"><caption class="sr-only">${F.esc(caption)}</caption><tbody>${rows.map((r) =>
    `<tr><th scope="row">${F.esc(r.label)}</th><td class="rk-readings__value${r.cls ? ` ${r.cls}` : ""}">${r.value}</td><td class="rk-readings__ref">${F.esc(r.ref || "")}</td></tr>`).join("")}</tbody></table>`;
}

const QUALITY = new Set(["tempo", "threshold", "vo2max", "race"]);
const EASY = new Set(["recovery", "endurance"]);
const intensityClass = (x) => (QUALITY.has(x) ? "quality" : EASY.has(x) ? "easy" : x === "strength" ? "strength" : "other");

function sessionLine(x, statusChip) {
  const meta = [F.SPORT[x.sport] || x.sport, x.planned_duration_s ? F.duration(x.planned_duration_s) : null,
    x.planned_distance_m ? F.distance(x.planned_distance_m) : null, x.planned_elevation_m ? `${F.elevation(x.planned_elevation_m)} D+` : null,
    x.best_slot && x.best_slot !== "none" ? `créneau ${F.SLOT[x.best_slot].toLowerCase()}` : null].filter(Boolean).join(" · ");
  return `<li class="rk-run rk-run--${F.esc(x.status || "planned")} rk-run--${intensityClass(x.intensity)}"><span class="rk-run__title">${F.esc(x.title)}</span>
    <span class="rk-run__meta">${meta}</span>${statusChip(x.status)}</li>`;
}

// ---------------------------------------------------------------------------
// Vue : Aujourd'hui
// ---------------------------------------------------------------------------

export async function viewToday(ctx) {
  const { api, summary: s, main, ui } = ctx;
  const [health, week, form, reports, block, decisions, injuryRisk] = await Promise.all([
    api("health?days=14"), api("week"), api("form?days=30"), api("reports"), api("block").catch(() => null),
    api("decisions?days=2&active=1").catch(() => ({ decisions: [] })), api("injury-risk").catch(() => null),
  ]);
  const today = s.today;
  const series = health.series || [];
  const h = series.find((p) => p.date === today) || null;
  const lastVerdict = [...series].reverse().find((p) => p.verdict);
  const prof = ribbon(block, s);

  // Repère du bloc pour l'en-tête de la feuille (« Semaine 5 · Spécifique »).
  const bw = block && block.status === "ok" ? block.weeks : [];
  const bi = bw.findIndex((w) => w.status === "current");
  const where = bi >= 0 ? `${F.esc(bw[bi].phase_label || PHASE_SHORT[bw[bi].phase] || "Bloc")} · semaine ${bi + 1} du bloc` : "";

  // Verdict : le mot du coach à la taille d'une affiche, sa raison, et le changement de séance.
  const v = h && h.verdict;
  const verdictHtml = v
    ? `<div class="rk-verdict rk-verdict--${v}"><p class="rk-verdict__word">${F.VERDICT[v]}</p><p class="rk-verdict__why">${F.esc(h.verdict_reason || "")}</p></div>`
    : `<div class="rk-verdict rk-verdict--none"><p class="rk-verdict__word">Pas de verdict</p><p class="rk-verdict__why">${lastVerdict
      ? `Dernier verdict le ${F.dayLong(lastVerdict.date)} : <strong>${F.VERDICT[lastVerdict.verdict]}</strong> — ${F.esc(lastVerdict.verdict_reason || "")}`
      : "Le coach pose un verdict (maintenir, alléger, repos) lors du bilan matinal."}</p></div>`;

  const list = decisions.decisions || [];
  const dec = list.find((d) => d.date === today) || list[0];
  let decisionHtml = "";
  if (dec) {
    const own = dec.date === today ? "" : ` du ${F.dayLong(dec.date)}`;
    const change = dec.before && dec.after && dec.before.title && dec.after.title
      ? `<p class="rk-change"><span class="rk-change__before">${F.esc(dec.before.title)}${dec.before.planned_duration_s ? ` <small>${F.duration(dec.before.planned_duration_s)}</small>` : ""}</span>
          <svg class="rk-change__arrow" viewBox="0 0 24 12" aria-hidden="true"><path d="M1 6h20M16 1.5 21.5 6 16 10.5"/></svg><span class="sr-only">remplacée par</span>
          <span class="rk-change__after">${F.esc(dec.after.title)}${dec.after.planned_duration_s ? ` <small>${F.duration(dec.after.planned_duration_s)}</small>` : ""}</span></p>`
      : `<p class="rk-decision__summary">${F.esc(dec.summary)}</p>`;
    const rules = (dec.rules || []).length ? `<p class="rk-decision__rules">Règle${dec.rules.length > 1 ? "s" : ""} : ${dec.rules.map((r) => F.esc(r.label || r.rule_id)).join(", ")}</p>` : "";
    decisionHtml = `<div class="rk-decision">
      <p class="rk-plate"><span class="rk-plate__who">${F.esc(F.TRIGGER[dec.trigger] || dec.trigger || "Décision")}${own}</span><span class="rk-plate__what">${F.esc(F.DECISION_OUTCOME[dec.outcome] || dec.outcome || "")}</span></p>
      ${change}${rules}
      ${dec.outcome === "proposed" ? `<p class="note">En attente de ta confirmation.</p>` : ""}
      <p class="rk-links"><a href="#/decision?id=${encodeURIComponent(dec.id)}">Pourquoi cette décision</a><a href="#/decisions">Journal des décisions</a></p></div>`;
  }

  // Une seule action principale (lime) : demander au coach si le chat est là, sinon la séance.
  const doneToday = week.activities.find((a) => a.date === today);
  const actions = [];
  if (s.settings.chat_enabled) actions.push(`<a class="rk-action" href="chat.html">Demander au coach${ARROW}</a>`);
  if (doneToday) actions.push(`<a class="rk-action${actions.length ? " rk-action--ghost" : ""}" href="#/seance/${doneToday.id}">Ouvrir la séance${ARROW}</a>`);
  if (!actions.length) actions.push(`<a class="rk-action" href="#/semaine">Voir la semaine${ARROW}</a>`);
  const actionsHtml = `<p class="rk-actions">${actions.join("")}</p>`;

  let checkHtml;
  if (health.morning_check === "off") {
    checkHtml = ui.note("Bilan matinal désactivé (<code>[health].morning_check = \"off\"</code>) : pas de données de santé attendues.");
  } else {
    const c = checkRows(health, s);
    checkHtml = `${c.stale ? `<p class="note">Dernières données : ${F.dayLong(c.stale)}.</p>` : ""}${rowsTable(c.rows, "Bilan du matin")}
      ${c.mode === "minimal" ? ui.note("Bilan minimal : readiness seule (<code>[health].morning_check = \"minimal\"</code>).") : ""}`;
  }

  const dayTitle = F.dayLong(today).replace(/^./, (ch) => ch.toUpperCase());
  const injury = ui.injuryRiskTile(injuryRisk);
  const ravito = sheet({ level: 1, id: "rk-today-title", title: dayTitle, meta: where, cls: "rk-sheet-card--lead",
    body: `${verdictHtml}${decisionHtml}${actionsHtml}
      ${injury ? `<div class="rk-subsheet"><h2 class="rk-subhead">Signal de vigilance</h2>${injury}</div>` : ""}
      <div class="rk-subsheet"><h2 class="rk-subhead">Bilan du matin</h2>${checkHtml}</div>` });

  // Au programme : les séances du jour, l'ancienne restyle sa ligne (annulée) sans bouger.
  const todaySessions = week.sessions.filter((x) => x.date === today);
  const todayActs = week.activities.filter((x) => x.date === today);
  const wx = week.weather.find((w) => w.date === today);
  const runs = todaySessions.length || todayActs.length
    ? `<ul class="rk-runs">${todaySessions.map((x) => sessionLine(x, ui.statusChip)).join("")}
        ${todayActs.map((a) => `<li class="rk-run rk-run--done"><a class="rk-run__title" href="#/seance/${a.id}">${F.esc(a.name || F.SPORT[a.sport])}</a><span class="rk-run__meta">Réalisée · ${a.distance_m ? F.distance(a.distance_m) + " · " : ""}${F.duration(a.duration_s)}</span>${ui.statusChip("done")}</li>`).join("")}</ul>`
    : `<p class="muted">Aucune séance planifiée aujourd'hui${week.week ? "" : " — pas de plan de semaine au contrat pour cette semaine"}.</p>`;
  const weather = wx ? `<p class="rk-weather">${weatherChip(wx)}<span>${F.esc(wx.location)} · ${F.num(wx.temp_max_c)}${NB}°C max · vent ${F.num(wx.wind_kmh)}${NB}km/h${wx.best_slot && wx.best_slot !== "none" ? ` · créneau <strong>${F.SLOT[wx.best_slot]}</strong>` : ""}</span></p>${wx.slot_reason ? `<p class="muted rk-weather__why">${F.esc(wx.slot_reason)}</p>` : ""}` : "";
  const equipment = ui.equipmentTile(s.equipment);
  const extras = ui.heatTile(s.heat_acclimation) + ui.gearTile(s.gear, !equipment) + equipment;
  // Prochaine séance clé : qualité ou sortie de 2 h et plus, après aujourd'hui, dans la semaine.
  const key = week.sessions.filter((x) => x.date > today && !["cancelled", "done", "missed"].includes(x.status)
    && (QUALITY.has(x.intensity) || (x.planned_duration_s || 0) >= 7200)).sort((a, b) => a.date.localeCompare(b.date))[0];
  const next = key ? `<p class="rk-next"><span class="rk-next__label">Prochaine séance clé</span>
      <span class="rk-next__what">${F.esc(key.title)}<small>${[F.SPORT[key.sport] || key.sport, key.planned_duration_s ? F.duration(key.planned_duration_s) : null, key.planned_elevation_m ? `${F.elevation(key.planned_elevation_m)} D+` : null].filter(Boolean).join(" · ")}</small></span>
      <span class="rk-next__when">${F.weekday(key.date)} ${F.dayShort(key.date)}</span></p>` : "";
  const program = sheet({ title: "Au programme", meta: wx ? F.esc(wx.location) : "", body: `${runs}${weather}${next}${extras}` });

  // Colonne de droite : la semaine en un coup d'œil, la forme, le dernier rapport.
  const days = [...Array(7)].map((_, i) => F.addDays(week.week_start, i));
  const weekList = `<ol class="rk-mini-week">${days.map((d) => {
    const plans = week.sessions.filter((x) => x.date === d && x.status !== "cancelled");
    const acts = week.activities.filter((x) => x.date === d);
    const label = acts.length ? F.esc(acts[0].name || F.SPORT[acts[0].sport]) : plans.length ? F.esc(plans[0].title) : `<span class="muted">—</span>`;
    const st = acts.length ? "done" : plans.length ? plans[0].status : "none";
    return `<li class="rk-mini-week__day${d === today ? " is-today" : ""} rk-mini-week__day--${st}"><span class="rk-mini-week__name">${F.weekday(d)}</span><span class="rk-mini-week__what">${label}</span></li>`;
  }).join("")}</ol><p class="rk-links"><a href="#/semaine">La semaine en détail</a></p>`;
  const f = form.series[form.series.length - 1];
  const formHtml = f ? `${readings([
      { label: "Condition", value: F.num(f.fitness), ref: "charge sur 42 j" },
      { label: "Fatigue", value: F.num(f.fatigue), ref: "charge sur 7 j" },
      { label: "Forme", value: `${f.form > 0 ? "+" : ""}${F.num(f.form)}`, cls: f.form >= 0 ? "pos" : "neg", ref: "condition − fatigue" },
      { label: "ACWR", value: F.num(f.acwr, 2), cls: f.acwr > 1.3 ? "neg" : "", ref: "repère prudent ≤ 1,3" },
    ], "Forme")}
      <p class="muted">${f.form > 5 ? "Fraîcheur : la fatigue est sous la condition physique." : f.form < -20 ? "Fatigue marquée : la charge récente dépasse nettement la condition." : "Zone de travail : fatigue et condition équilibrées."}${f.acwr > 1.3 ? " Charge aiguë au-dessus de la zone prudente." : ""}</p>
      ${ui.complianceTrend(s.compliance_trend)}<p class="rk-links"><a href="#/forme">Courbe de forme</a></p>`
    : ui.note("Pas encore de séances indexées.");
  const rep = reports.reports[0];
  const side = sheet({ title: "Cette semaine", body: weekList })
    + sheet({ title: "Forme", body: formHtml })
    + (rep ? sheet({ title: "Dernier rapport", body: `<p><a href="#/rapport?path=${encodeURIComponent(rep.source_path)}">${F.esc(rep.title)}</a></p><p class="muted">${F.dayLong(rep.date)}</p>` }) : "");

  main.innerHTML = `${prof.html}<div class="rk-grid"><div class="rk-grid__main">${ravito}${program}</div><aside class="rk-grid__side" aria-label="La semaine et la forme">${side}</aside></div>`;
  applyVars(main);
  prof.mount();
}

// ---------------------------------------------------------------------------
// Vue : Semaine
// ---------------------------------------------------------------------------

/** Bande de la semaine : le volume prévu posé sur la longueur de la cible, sans jamais la
 * dépasser en silence (le débordement est hachuré et chiffré). */
function capacity(w) {
  const target = w.week && w.week.target_duration_s;
  const planned = w.sessions.filter((x) => x.status !== "cancelled" && x.sport !== "rest" && x.planned_duration_s);
  const plannedS = planned.reduce((t, x) => t + x.planned_duration_s, 0);
  const doneS = w.activities.reduce((t, a) => t + (a.duration_s || 0), 0);
  if (!target && !plannedS) return "";
  const scale = Math.max(target || 0, plannedS, doneS) || 1;
  const pct = (v) => `${((v / scale) * 100).toFixed(2)}%`;
  const over = target && plannedS > target ? plannedS - target : 0;
  const segs = planned.map((x) => `<span class="rk-tape__seg rk-tape__seg--${intensityClass(x.intensity)}" data-vars="--w:${pct(x.planned_duration_s)}" title="${F.esc(`${F.weekday(x.date)} · ${x.title} · ${F.duration(x.planned_duration_s)}`)}"></span>`).join("");
  return `<div class="rk-capacity">
    <div class="rk-capacity__row"><span class="rk-capacity__label">Prévu</span>
      <div class="rk-tape" role="img" aria-label="${F.esc(`Prévu ${F.hours(plannedS)}${target ? ` sur une cible de ${F.hours(target)}` : ""}`)}">${segs}${target ? `<span class="rk-tape__target" data-vars="--x:${pct(target)}"></span>` : ""}${over ? `<span class="rk-tape__over" data-vars="--a:${pct(target)};--w:${pct(over)}"></span>` : ""}</div>
      <span class="rk-capacity__num">${F.hours(plannedS)}${target ? `<small> / ${F.hours(target)}</small>` : ""}</span></div>
    <div class="rk-capacity__row"><span class="rk-capacity__label">Réalisé</span>
      <div class="rk-tape rk-tape--done" role="img" aria-label="${F.esc(`Réalisé ${F.hours(doneS)}`)}"><span class="rk-tape__fill" data-vars="--w:${pct(doneS)}"></span>${target ? `<span class="rk-tape__target" data-vars="--x:${pct(target)}"></span>` : ""}</div>
      <span class="rk-capacity__num">${F.hours(doneS)}</span></div>
    <p class="rk-capacity__key"><span class="rk-key rk-key--quality"></span>Qualité <span class="rk-key rk-key--easy"></span>Endurance <span class="rk-key rk-key--strength"></span>Renforcement <span class="rk-key rk-key--other"></span>Autre${target ? ` <span class="rk-key rk-key--target"></span>Cible de la semaine` : ""}</p>
    ${over ? `<p class="note rk-capacity__over">Le prévu dépasse la cible de ${F.duration(over)}.</p>` : ""}</div>`;
}

// Icônes de sport : Lucide (lucide.dev, lucide-static 0.460.0, licence ISC), tracés recopiés tels
// quels. Un sport absent de la table garde son libellé seul.
const SPORT_ICON = {
  running: '<path d="M4 16v-2.38C4 11.5 2.97 10.5 3 8c.03-2.72 1.49-6 4.5-6C9.37 2 10 3.8 10 5.5c0 3.11-2 5.66-2 8.68V16a2 2 0 1 1-4 0Z"/><path d="M20 20v-2.38c0-2.12 1.03-3.12 1-5.62-.03-2.72-1.49-6-4.5-6C14.63 6 14 7.8 14 9.5c0 3.11 2 5.66 2 8.68V20a2 2 0 1 0 4 0Z"/><path d="M16 17h4"/><path d="M4 13h4"/>',
  trail: '<path d="m8 3 4 8 5-5 5 15H2L8 3z"/>',
  strength: '<path d="M12.409 13.017A5 5 0 0 1 22 15c0 3.866-4 7-9 7-4.077 0-8.153-.82-10.371-2.462-.426-.316-.631-.832-.62-1.362C2.118 12.723 2.627 2 10 2a3 3 0 0 1 3 3 2 2 0 0 1-2 2c-1.105 0-1.64-.444-2-1"/><path d="M15 14a5 5 0 0 0-7.584 2"/><path d="M9.964 6.825C8.019 7.977 9.5 13 8 15"/>', // biceps-flexed
  cycling: '<circle cx="18.5" cy="17.5" r="3.5"/><circle cx="5.5" cy="17.5" r="3.5"/><circle cx="15" cy="5" r="1"/><path d="M12 17.5V14l-3-3 4-3 2 3h2"/>',
  hiking: '<path d="M4 10a4 4 0 0 1 4-4h8a4 4 0 0 1 4 4v10a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2z"/><path d="M8 10h8"/><path d="M8 18h8"/><path d="M8 22v-6a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v6"/><path d="M9 6V4a2 2 0 0 1 2-2h2a2 2 0 0 1 2 2v2"/>',
  walking: '<circle cx="12" cy="5" r="1"/><path d="m9 20 3-6 3 6"/><path d="m6 8 6 2 6-2"/><path d="M12 10v4"/>',
  elliptical: '<path d="M22 12h-2.48a2 2 0 0 0-1.93 1.46l-2.35 8.36a.25.25 0 0 1-.48 0L9.24 2.18a.25.25 0 0 0-.48 0l-2.35 8.36A2 2 0 0 1 4.49 12H2"/>',
  rest: '<path d="M2 4v16"/><path d="M2 8h18a2 2 0 0 1 2 2v10"/><path d="M2 17h20"/><path d="M6 8v9"/>',
  swimming: '<path d="M2 6c.6.5 1.2 1 2.5 1C7 7 7 5 9.5 5c2.6 0 2.4 2 5 2 2.5 0 2.5-2 5-2 1.3 0 1.9.5 2.5 1"/><path d="M2 12c.6.5 1.2 1 2.5 1 2.5 0 2.5-2 5-2 2.6 0 2.4 2 5 2 2.5 0 2.5-2 5-2 1.3 0 1.9.5 2.5 1"/><path d="M2 18c.6.5 1.2 1 2.5 1 2.5 0 2.5-2 5-2 2.6 0 2.4 2 5 2 2.5 0 2.5-2 5-2 1.3 0 1.9.5 2.5 1"/>',
  rowing: '<path d="M22 18H2a4 4 0 0 0 4 4h12a4 4 0 0 0 4-4Z"/><path d="M21 14 10 2 3 14h18Z"/><path d="M10 2v16"/>',
};
SPORT_ICON.indoor_cycling = SPORT_ICON.home_trainer = SPORT_ICON.cycling;

// Icônes météo (Lucide, même origine) : la couleur reste celle de la catégorie, l'icône dit
// le facteur qui pèse le plus et son palier, d'après les seuils du skill `weather-forecast`
// (pluie 1/5/15 mm, vent 20/35/50 km/h, chaleur 22/28/32 °C). À égalité : pluie, vent,
// chaleur. Aucun facteur (catégorie due aux UV, ou optimale) : soleil.
const SUN = '<circle cx="12" cy="12" r="4"/><path d="M12 2v2"/><path d="M12 20v2"/><path d="m4.93 4.93 1.41 1.41"/><path d="m17.66 17.66 1.41 1.41"/><path d="M2 12h2"/><path d="M20 12h2"/><path d="m6.34 17.66-1.41 1.41"/><path d="m19.07 4.93-1.41 1.41"/>';
const WIND = '<path d="M12.8 19.6A2 2 0 1 0 14 16H2"/><path d="M17.5 8a2.5 2.5 0 1 1 2 4H2"/><path d="M9.8 4.4A2 2 0 1 1 11 8H2"/>';
const WEATHER_ICON = {
  sun: [SUN],
  // cloud-drizzle, cloud-rain-wind, cloud-lightning (le palier 3 dit « Dangereux », pas un orage mesuré)
  rain: ['<path d="M4 14.899A7 7 0 1 1 15.71 8h1.79a4.5 4.5 0 0 1 2.5 8.242"/><path d="M8 19v1"/><path d="M8 14v1"/><path d="M16 19v1"/><path d="M16 14v1"/><path d="M12 21v1"/><path d="M12 16v1"/>',
    '<path d="M4 14.899A7 7 0 1 1 15.71 8h1.79a4.5 4.5 0 0 1 2.5 8.242"/><path d="m9.2 22 3-7"/><path d="m9 13-3 7"/><path d="m17 13-3 7"/>',
    '<path d="M6 16.326A7 7 0 1 1 15.71 8h1.79a4.5 4.5 0 0 1 .5 8.973"/><path d="m13 12-3 5h4l-3 5"/>'],
  // wind, wind, tornado
  wind: [WIND, WIND, '<path d="M21 4H3"/><path d="M18 8H6"/><path d="M19 12H9"/><path d="M16 16h-6"/><path d="M11 20H9"/>'],
  // sun, thermometer-sun, flame
  heat: [SUN, '<path d="M12 9a4 4 0 0 0-2 7.5"/><path d="M12 3v2"/><path d="m6.6 18.4-1.4 1.4"/><path d="M20 4v10.54a4 4 0 1 1-4 0V4a2 2 0 0 1 4 0Z"/><path d="M4 13H2"/><path d="M6.34 7.34 4.93 5.93"/>',
    '<path d="M8.5 14.5A2.5 2.5 0 0 0 11 12c0-1.38-.5-2-1-3-1.072-2.143-.224-4.054 2-6 .5 2.5 2 4.9 4 6.5 2 1.6 3 3.5 3 5.5a7 7 0 1 1-14 0c0-1.153.433-2.294 1-3a2.5 2.5 0 0 0 2.5 2.5z"/>'],
};
const level = (v, [a, b, c]) => (v == null ? 0 : v > c ? 3 : v >= b ? 2 : v >= a ? 1 : 0);
/** Tracé de l'icône : facteur dominant, à son palier (1 à 3). */
function weatherIcon(wx) {
  const factors = [["rain", level(wx.precip_mm, [1, 5, 15])], ["wind", level(wx.wind_kmh, [20, 35, 50])],
    ["heat", wx.temp_max_c > 22 ? level(wx.temp_max_c, [22, 28, 32]) : 0]];
  const [factor, lvl] = factors.reduce((best, f) => (f[1] > best[1] ? f : best), ["sun", 0]);
  return WEATHER_ICON[factor][Math.max(lvl, 1) - 1];
}

/** Météo d'un jour de la feuille de semaine : l'icône seule, à la couleur de la catégorie ;
 * le mot et les valeurs restent en infobulle et pour les lecteurs d'écran. */
function weatherMark(wx) {
  if (!wx || !wx.category) return "";
  const label = F.WEATHER[wx.category] || wx.category;
  const values = [wx.temp_max_c != null ? `${F.num(wx.temp_max_c)}${NB}°C max` : null, wx.wind_kmh != null ? `vent ${F.num(wx.wind_kmh)}${NB}km/h` : null,
    wx.precip_mm != null ? `pluie ${F.num(wx.precip_mm, 1)}${NB}mm` : null].filter(Boolean).join(" · ");
  const tip = `Météo : ${label}${values ? ` · ${values}` : ""}`;
  return `<span class="rk-wx rk-wx--${F.esc(wx.category)}" title="${F.esc(tip)}"><svg class="rk-wx__icon" viewBox="0 0 24 24" aria-hidden="true">${weatherIcon(wx)}</svg><span class="sr-only">${F.esc(tip)}</span></span>`;
}

/** Puce météo du roadbook : couleur de la catégorie, icône du facteur dominant, valeurs en infobulle. */
function weatherChip(wx) {
  if (!wx || !wx.category) return "";
  const tip = [wx.temp_max_c != null ? `${F.num(wx.temp_max_c)}${NB}°C max` : null, wx.wind_kmh != null ? `vent ${F.num(wx.wind_kmh)}${NB}km/h` : null,
    wx.precip_mm != null ? `pluie ${F.num(wx.precip_mm, 1)}${NB}mm` : null].filter(Boolean).join(" · ");
  return `<span class="chip chip--weather-${F.esc(wx.category)} chip--icon"${tip ? ` title="${F.esc(tip)}"` : ""}><svg class="chip__icon" viewBox="0 0 24 24" aria-hidden="true">${weatherIcon(wx)}</svg>${F.esc(F.WEATHER[wx.category] || wx.category)}</span>`;
}

/** Libellé du sport précédé de son icône (décorative : le libellé reste le texte lu). */
function sportLabel(sport) {
  const label = F.esc(F.SPORT[sport] || sport);
  const path = SPORT_ICON[sport];
  return path ? `<span class="rk-sport"><svg class="rk-sport__icon" viewBox="0 0 24 24" aria-hidden="true">${path}</svg>${label}</span>` : label;
}

const CHECK = '<svg class="rk-check" viewBox="0 0 16 16" aria-hidden="true"><circle cx="8" cy="8" r="6.5"/><path d="M5.2 8.2 7.2 10.2 10.9 6.2"/></svg>';

/** Distance, FC moyenne et D+ réalisés d'une activité (D+ seulement s'il est significatif). */
const actFacts = (a) => [a.distance_m ? F.distance(a.distance_m) : null,
  a.elevation_gain_m >= 20 ? `${F.elevation(a.elevation_gain_m)} D+` : null,
  a.avg_hr_bpm ? `${F.num(a.avg_hr_bpm)}${NB}bpm` : null];

/** Ligne « réalisé » sous une séance prévue : lien vers l'activité appariée et ses chiffres. */
function realLine(a, label) {
  const facts = actFacts(a).filter(Boolean).join(" · ");
  return `<span class="rk-runsheet__real"><span class="rk-runsheet__link">${CHECK}<a href="#/seance/${a.id}"${a.name ? ` title="${F.esc(a.name)}"` : ""}>${F.esc(label)}</a></span>${facts ? ` · ${facts}` : ""}</span>`;
}

/** Colonne « Prévu → réalisé » : le prévu en petit au-dessus, le réalisé en gras ; une seule
 * valeur (en gras) quand l'autre manque. `deviation` colore un réalisé écourté ou allongé. */
function durCell(plannedS, actualS, deviation) {
  const planned = plannedS ? F.duration(plannedS) : "—";
  if (actualS == null) return plannedS ? `<span class="rk-dur__real">${planned}</span>` : "—";
  return `<span class="rk-dur__plan">${planned}<span class="sr-only"> prévu, </span></span><span class="rk-dur__real${deviation ? ` rk-dur__real--${deviation}` : ""}">${F.duration(actualS)}<span class="sr-only"> réalisé</span></span>`;
}

export async function viewWeek(ctx, params) {
  const { api, summary: s, main, ui } = ctx;
  const start = params.get("debut");
  const [w, block, decisions] = await Promise.all([api(start ? `week?start=${start}` : "week"), api("block").catch(() => null),
    api("decisions?all=1").catch(() => ({ decisions: [] }))]);
  const prof = ribbon(block, s, { selected: w.week_start });
  const prev = F.addDays(w.week_start, -7), next = F.addDays(w.week_start, 7);
  const days = [...Array(7)].map((_, i) => F.addDays(w.week_start, i));

  // Prévu et réalisé fusionnés : l'appariement vient du serveur (`activity_id`, `effective`,
  // `deviation`, `unplanned`), le même que celui de la conformité — jamais refait ici.
  const actById = new Map(w.activities.map((a) => [a.id, a]));
  const rows = days.map((d) => {
    const plans = w.sessions.filter((x) => x.date === d);
    const extras = w.activities.filter((a) => a.date === d && a.unplanned);
    // Météo seulement pour aujourd'hui et la suite : sur un jour passé, elle ne décide plus rien.
    const wx = d >= w.today ? w.weather.find((x) => x.date === d) : null;
    const entries = [
      ...plans.map((x) => {
        const a = x.activity_id != null ? actById.get(x.activity_id) : null;
        const rest = x.sport === "rest" || x.intensity === "rest";
        const eff = x.effective || x.status || "planned";
        const shown = eff === "done" && x.deviation ? (x.deviation === "short" ? "shortened" : "extended") : eff === "future" ? "planned" : eff;
        const climb = x.planned_elevation_m ? `${F.elevation(x.planned_elevation_m)} D+` : null;
        const real = a ? realLine(a, a.sport !== x.sport && F.SPORT[a.sport] ? `Réalisé · ${F.SPORT[a.sport]}` : "Réalisé")
          : eff === "done" ? `<span class="rk-runsheet__real">${CHECK}Faite, sans activité synchronisée</span>` : "";
        // Séance faite : le type de séance seul, suivi du réalisé sur la même ligne — le D+ et le
        // créneau prévus ne disent plus rien une fois la séance courue.
        return { cls: `rk-run--${F.esc(eff)} rk-run--${rest ? "rest" : intensityClass(x.intensity)}`, title: F.esc(x.title),
          meta: rest ? "" : real ? `${sportLabel(x.sport)} · ${real}`
            : [sportLabel(x.sport), climb, x.best_slot && x.best_slot !== "none" ? F.SLOT[x.best_slot] : null].filter(Boolean).join(" · "),
          real: rest ? real : "",
          dur: durCell(x.planned_duration_s, a ? a.duration_s : null, x.deviation), status: rest ? "" : ui.statusChip(shown) };
      }),
      ...extras.map((a) => ({ cls: "rk-run--unplanned", title: `<a href="#/seance/${a.id}">${F.esc(a.name || F.SPORT[a.sport])}</a>`,
        meta: [sportLabel(a.sport), ...actFacts(a)].filter(Boolean).join(" · "),
        real: "", dur: durCell(null, a.duration_s), status: ui.statusChip("unplanned") })),
    ];
    const day = `<th scope="rowgroup" class="rk-runsheet__day"${entries.length > 1 ? ` rowspan="${entries.length}"` : ""}><span class="rk-runsheet__wd">${F.weekday(d)}${weatherMark(wx)}</span><span class="rk-runsheet__date">${F.dayShort(d)}</span></th>`;
    if (!entries.length) return `<tbody class="rk-runsheet__group${d === w.today ? " is-today" : ""}"><tr>${day}<td colspan="3" class="muted">—</td></tr></tbody>`;
    return `<tbody class="rk-runsheet__group${d === w.today ? " is-today" : ""}">${entries.map((e, i) => `<tr class="rk-run ${e.cls}">${i === 0 ? day : ""}
      <td class="rk-runsheet__what"><span class="rk-run__title">${e.title}</span>${e.meta ? `<span class="rk-run__meta">${e.meta}</span>` : ""}${e.real}<span class="rk-runsheet__inline">${e.status}</span></td>
      <td class="rk-runsheet__dur">${e.dur}</td><td class="rk-runsheet__status">${e.status}</td></tr>`).join("")}</tbody>`;
  }).join("");

  const totalS = w.activities.reduce((t, a) => t + (a.duration_s || 0), 0);
  const totalM = w.activities.reduce((t, a) => t + (a.distance_m || 0), 0);
  const target = w.week || {};
  const trail = s.settings.sport === "trail";
  const meta = w.week ? [w.week.phase, w.week.location].filter(Boolean).map(F.esc).join(" · ") : "Pas de plan de semaine";
  const nav = `<nav class="rk-weeknav" aria-label="Autres semaines"><a href="#/semaine?debut=${prev}">${ARROW_BACK}Précédente</a><a href="#/semaine"${w.week_start === F.addDays(s.today, -((F.parseDate(s.today).getDay() + 6) % 7)) ? ' aria-current="page"' : ""}>Cette semaine</a><a href="#/semaine?debut=${next}">Suivante${ARROW}</a></nav>`;

  const runsheet = sheet({ level: 1, id: "rk-week-title", title: `Semaine du ${F.dayShort(w.week_start)}`, meta, cls: "rk-sheet-card--lead",
    body: `${nav}${capacity(w)}
      <table class="rk-runsheet"><caption class="sr-only">Séances de la semaine, jour par jour</caption>
        <thead><tr><th scope="col">Jour</th><th scope="col">Séance</th><th scope="col" class="rk-runsheet__dur">Prévu → réalisé</th><th scope="col" class="rk-runsheet__status">Statut</th></tr></thead>${rows}</table>` });
  const done = sheet({ title: "Réalisé", body: readings([
    { label: "Séances", value: String(w.activities.length), ref: `${w.sessions.filter((x) => x.status !== "cancelled" && x.sport !== "rest").length} prévues` },
    { label: "Durée", value: `${F.hours(totalS)}${target.target_duration_s ? `<small> / ${F.hours(target.target_duration_s)}</small>` : ""}`, ref: target.target_duration_s ? "cible de la semaine" : "" },
    { label: "Distance", value: `${F.distance(totalM)}${target.target_distance_m ? `<small> / ${F.distance(target.target_distance_m, 0)}</small>` : ""}`, ref: "" },
  ], "Réalisé de la semaine") });

  // Les décisions qui ont touché cette semaine (garde-fous, bilans, demandes), en lignes de barrière.
  const weekEnd = F.addDays(w.week_start, 6);
  const own = (decisions.decisions || []).filter((d) => (d.session_ref && d.session_ref.week && w.week && d.session_ref.week === w.week.source_path)
    || (d.session_ref && d.session_ref.date >= w.week_start && d.session_ref.date <= weekEnd) || (d.date >= w.week_start && d.date <= weekEnd))
    .sort((a, b) => a.date.localeCompare(b.date));
  const barriers = own.length ? sheet({ title: "Barrières de la semaine", meta: `${own.length}`, body: `<ul class="rk-barriers">${own.map((d) => `<li>
      <p class="rk-plate"><span class="rk-plate__who">${F.esc(F.TRIGGER[d.trigger] || d.trigger || "Décision")}</span><span class="rk-plate__what">${F.esc(F.DECISION_OUTCOME[d.outcome] || d.outcome || "")}</span></p>
      ${d.before && d.after && d.before.title && d.after.title ? `<p class="rk-change"><span class="rk-change__before">${F.esc(d.before.title)}</span>${ARROW.replace("<svg", '<svg class="rk-change__arrow"')}<span class="sr-only">remplacée par</span><span class="rk-change__after">${F.esc(d.after.title)}</span></p>` : `<p class="rk-decision__summary">${F.esc(d.summary)}</p>`}
      <a class="rk-barriers__date" href="#/decision?id=${encodeURIComponent(d.id)}">${F.dayLong(d.date)} · le détail</a></li>`).join("")}</ul>` }) : "";

  main.innerHTML = `${prof.html}<div class="rk-grid"><div class="rk-grid__main">${runsheet}${barriers}${w.body_html ? `<section class="band prose rk-prose"><h2>Plan du coach</h2>${w.body_html}</section>` : ""}</div>
    <aside class="rk-grid__side" aria-label="Bilan de la semaine">${done}${ui.complianceSection(w.compliance, trail)}</aside></div>`;
  applyVars(main);
  prof.mount();
}
