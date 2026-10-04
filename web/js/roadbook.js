// Roadbook imprimable (#187, épopée #170) : rendu de `/api/roadbook`.
// Fonctions de rendu pures (chaîne HTML en sortie) + `wireRoadbook` pour le sélecteur de scénario et
// les boutons d'impression. Aucun style en ligne (CSP `style-src 'self'`), aucun script externe, aucune
// donnée réseau : tout vient du modèle servi localement, l'impression passe par `window.print()`.
import * as F from "./format.js";

export const SCENARIO_LABEL = { safe: "Prudent", realistic: "Réaliste", ambitious: "Ambitieux" };
const SCENARIO_ORDER = ["safe", "realistic", "ambitious"];

// Statuts du contrôle du matériel (#134, `arc_metrics.race_gear_check`) : texte ET case à cocher,
// jamais la seule couleur (une feuille imprimée en noir et blanc doit rester lisible).
const GEAR_STATUS = {
  ok: ["ok", "Prêt"],
  alert: ["warn", "À vérifier : usure"],
  never_used: ["warn", "Jamais utilisé à l'entraînement"],
  category_match: ["warn", "À vérifier : spécification exacte"],
  missing: ["bad", "Non retrouvé dans l'inventaire"],
  unchecked: ["muted", "Non vérifié"],
};
const CUTOFF_STATUS = { ok: "marge", tendu: "TENDU", hors_delai: "HORS DÉLAI" };
const NIGHT_LABEL = { full: "Nuit", partial: "Nuit partielle" };

const sign = (s) => (s < 0 ? "−" : "+");

/** Marge de barrière : « +1 h 25 », « −0 min » jamais ambigu (signe toujours écrit). */
function marginText(c) {
  return `${sign(c.margin_s)}${F.duration(Math.abs(c.margin_s))}`;
}

/** Texte de barrière lisible sur papier : une date-heure ISO du plan (`2026-10-25T12:00`, barrière du
 * surlendemain) devient « 12:00 (25/10) » — heure murale telle qu'écrite, aucun fuseau converti ;
 * `HH:MM` et `+HH:MM` restent tels quels. */
function cutoffText(text) {
  const m = /^\d{4}-(\d{2})-(\d{2})T(\d{2}:\d{2})/.exec(text || "");
  return m ? `${m[3]} (${m[2]}/${m[1]})` : (text || "");
}

/** Pas de graduation « rond » (km) pour une course de `total` km, ~6 graduations. */
function kmStep(total) {
  for (const s of [1, 2, 5, 10, 20, 25, 50, 100]) if (total / s <= 8) return s;
  return 100;
}

/** Profil d'élévation RELATIF au départ (le plan ne contient pas l'altitude absolue) : aire, nuit
 * hachurée (motif lisible en noir et blanc), repères de ravito numérotés (R1, R2…). */
export function profileSvg(profile, nightSpans, uid) {
  if (!profile || !profile.points || profile.points.length < 2) return "";
  const pts = profile.points;
  const W = 760, H = 200, L = 64, R = 12, T = 22, B = 26;
  const kmMax = pts[pts.length - 1][0] || 1;
  const els = pts.map((p) => p[1]);
  let lo = Math.min(...els, 0), hi = Math.max(...els, 0);
  if (hi - lo < 20) hi = lo + 20;
  const x = (km) => L + ((km - pts[0][0]) / ((kmMax - pts[0][0]) || 1)) * (W - L - R);
  const y = (e) => T + (1 - (e - lo) / (hi - lo)) * (H - T - B);
  const line = pts.map((p, i) => `${i ? "L" : "M"}${x(p[0]).toFixed(1)} ${y(p[1]).toFixed(1)}`).join("");
  const area = `${line}L${x(kmMax).toFixed(1)} ${y(lo).toFixed(1)}L${x(pts[0][0]).toFixed(1)} ${y(lo).toFixed(1)}Z`;
  const step = kmStep(kmMax);
  let xticks = "";
  for (let k = 0; k <= kmMax + 1e-6; k += step) {
    xticks += `<line class="rb-tick" x1="${x(k).toFixed(1)}" x2="${x(k).toFixed(1)}" y1="${H - B}" y2="${H - B + 4}"/><text class="rb-ticklabel" x="${x(k).toFixed(1)}" y="${H - 8}" text-anchor="middle">${F.esc(F.distanceValue(k * 1000, 0))}</text>`;
  }
  const yTicks = [lo, (lo + hi) / 2, hi].map((raw) => { const e = Math.round(raw) || 0; return `<line class="rb-grid" x1="${L}" x2="${W - R}" y1="${y(e).toFixed(1)}" y2="${y(e).toFixed(1)}"/><text class="rb-ticklabel" x="${L - 6}" y="${(y(e) + 4).toFixed(1)}" text-anchor="end">${F.esc(`${e > 0 ? "+" : e < 0 ? "−" : ""}${F.elevation(Math.abs(e))}`)}</text>`; }).join("");
  const night = (nightSpans || []).map(([a, b]) => `<rect class="rb-night" x="${x(a).toFixed(1)}" y="${T}" width="${Math.max(1, x(b) - x(a)).toFixed(1)}" height="${H - T - B}" fill="url(#rb-hatch-${uid})"/>`).join("");
  const aid = (profile.aid_stations || []).map((m, i) => {
    const cx = x(m.km), cy = y(m.elev_m);
    return `<g class="rb-aid"><line x1="${cx.toFixed(1)}" x2="${cx.toFixed(1)}" y1="${cy.toFixed(1)}" y2="${H - B}"/><circle cx="${cx.toFixed(1)}" cy="${cy.toFixed(1)}" r="4"/><text x="${cx.toFixed(1)}" y="${(cy - 8).toFixed(1)}" text-anchor="middle">R${i + 1}</text></g>`;
  }).join("");
  return `<svg class="rb-profile" viewBox="0 0 ${W} ${H}" role="img" aria-label="Profil d'élévation relatif au départ, ${F.esc(F.distance(kmMax * 1000, 0))}">
    <defs><pattern id="rb-hatch-${uid}" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><line class="rb-hatch" x1="0" y1="0" x2="0" y2="6"/></pattern></defs>
    ${yTicks}${night}<path class="rb-area" d="${area}"/><path class="rb-line" d="${line}"/>${aid}${xticks}
    </svg><p class="rb-profile-cap muted">Axe horizontal en ${F.esc(F.distanceUnit())} · hachures = nuit · altitude relative au départ (le plan ne contient pas l'altitude absolue)</p>`;
}

function stationCell(row, idx) {
  const st = row.station;
  if (!st) return row.to_name === "Arrivée" ? "<strong>Arrivée</strong>" : F.esc(row.to_name);
  const take = st.take && st.take.length
    ? `<div class="rb-take"><strong>À prendre :</strong> ${st.take.map(F.esc).join(" · ")}</div>`
    : `<div class="rb-take rb-take--none muted">À prendre : non renseigné</div>`;
  const serv = st.services && st.services.length ? `<div class="rb-serv muted">Servi : ${st.services.map(F.esc).join(", ")}</div>` : "";
  const stop = row.stop_s ? `<div class="rb-serv muted">Arrêt prévu ${F.esc(F.duration(row.stop_s, { seconds: row.stop_s % 60 !== 0 }))}</div>` : "";
  return `<strong>R${idx} ${F.esc(st.name)}</strong>${take}${serv}${stop}`;
}

function sectionsTable(sc) {
  let stationIdx = 0;
  const rows = sc.sections.map((r) => {
    const idx = r.station ? ++stationIdx : 0;
    const night = r.night ? `<span class="rb-night-tag">${NIGHT_LABEL[r.night]} · frontale</span>` : "";
    const cut = r.cutoff
      ? `<span class="rb-cut rb-cut--${F.esc(r.cutoff.status)}">${F.esc(cutoffText(r.cutoff.text))}${r.cutoff.day ? ` (J${r.cutoff.day})` : ""}</span><br><span class="rb-cut__margin">${F.esc(marginText(r.cutoff))} · ${F.esc(CUTOFF_STATUS[r.cutoff.status] || r.cutoff.status)}</span>`
      : r.station ? `<span class="muted">—</span>` : "";
    const passage = r.arrival_clock
      ? `<strong>${F.esc(r.arrival_clock)}</strong><br><span class="muted">T+${F.esc(F.duration(r.arrival_s))}</span>`
      : `<strong>T+${F.esc(F.duration(r.arrival_s))}</strong>`;
    const leave = r.departure_clock ? `<br><span class="muted">repart ${F.esc(r.departure_clock)}</span>` : "";
    return `<tr class="${r.night ? "rb-row--night" : ""}">
      <td class="rb-km">${F.esc(F.distanceValue(r.from_km * 1000, 1))}→${F.esc(F.distance(r.to_km * 1000, 1))}${night ? `<br>${night}` : ""}</td>
      <td class="num" data-label="Dist. · D+/D−">${F.esc(F.distance(r.distance_m, 1))}<br><span class="muted">+${F.esc(F.elevation(r.gain_m))} / −${F.esc(F.elevation(r.loss_m))}</span></td>
      <td class="num" data-label="Temps">${F.esc(F.duration(r.moving_s))}</td>
      <td class="num" data-label="Passage">${passage}${leave}</td>
      <td data-label="Barrière">${cut}</td>
      <td class="rb-stationcell">${stationCell(r, idx)}</td></tr>`;
  }).join("");
  return `<div class="table-wrap rb-table-wrap"><table class="data data--compact rb-table">
    <caption class="sr-only">Sections, heures de passage, barrières et ravitaillements</caption>
    <thead><tr><th scope="col">Section</th><th scope="col" class="num">Dist. · D+/D−</th><th scope="col" class="num">Temps</th><th scope="col" class="num">Passage</th><th scope="col">Barrière</th><th scope="col">Ravito · à prendre</th></tr></thead>
    <tbody>${rows}</tbody></table></div>`;
}

function gearList(gear) {
  if (!gear) return `<p class="muted">Aucun matériel obligatoire déclaré dans le plan.</p>`;
  const items = gear.entries.map((e) => {
    const [kind, label] = GEAR_STATUS[e.status] || ["muted", e.status];
    const has = e.items && e.items.length ? ` <span class="muted">(${e.items.map(F.esc).join(", ")})</span>` : "";
    return `<li class="rb-gear rb-gear--${kind}"><span class="rb-box" aria-hidden="true"></span><span>${F.esc(e.entry)}${has}<span class="rb-gear__status"> — ${F.esc(label)}</span></span></li>`;
  }).join("");
  const unchecked = gear.inventory_checked ? "" : `<p class="note">Inventaire du matériel vide ou plan non croisé : la colonne de statut n'est pas un contrôle.</p>`;
  return `<ul class="rb-gearlist">${items}</ul>${unchecked}`;
}

function textList(items) {
  return `<ul class="rb-list">${items.map((t) => `<li>${F.esc(t)}</li>`).join("")}</ul>`;
}

function sheet(model, name, active) {
  const sc = model.scenarios[name];
  const h = model.header;
  const meta = [
    h.race_date ? F.dateLong(h.race_date) : null,
    h.start_clock ? `départ ${h.start_clock}` : null,
    h.distance_m ? F.distance(h.distance_m, 1) : null,
    h.elevation_gain_m ? `D+ ${F.elevation(h.elevation_gain_m)}` : null,
    h.elevation_loss_m ? `D− ${F.elevation(h.elevation_loss_m)}` : null,
  ].filter(Boolean).map(F.esc).join(" · ");
  const target = sc.target_s ? `<span>objectif du plan <strong>${F.esc(F.duration(sc.target_s))}</strong></span>` : "";
  const finish = sc.finish_clock ? `<span>arrivée <strong>${F.esc(sc.finish_clock)}</strong></span>` : "";
  const lamp = sc.lamp_sections ? `<span class="rb-night-tag">Frontale : ${sc.lamp_sections} section${sc.lamp_sections > 1 ? "s" : ""} de nuit</span>` : "";
  const water = model.water_points && model.water_points.length
    ? `<h3>Points d'eau</h3><p class="rb-water">${model.water_points.map((w) => `${F.esc(F.distance(w.km * 1000, 1))}${w.name ? ` ${F.esc(w.name)}` : ""}`).join(" · ")}</p>` : "";
  const gaps = [...(model.missing || []), ...(model.warnings || [])];
  const missing = gaps.length
    ? `<section class="rb-gaps"><h3>À compléter / à savoir</h3>${textList(gaps)}</section>` : "";
  return `<section class="rb-sheet${active ? " is-active" : ""}" data-scenario="${F.esc(name)}" aria-label="Roadbook, scénario ${F.esc(SCENARIO_LABEL[name])}">
    <header class="rb-head">
      <h2 class="rb-title">${F.esc(h.race_name || "Course")}</h2>
      <p class="rb-meta">${meta}</p>
      <p class="rb-scenario"><span class="rb-scenario__name">Scénario ${F.esc(SCENARIO_LABEL[name])}</span>
        <span>temps prévu <strong>${F.esc(F.duration(sc.total_s))}</strong></span>${finish}${target}${lamp}</p>
    </header>
    ${profileSvg(model.profile, sc.night_spans_km, name)}
    ${sectionsTable(sc)}
    ${water}
    <div class="rb-cols">
      <section><h3>Matériel obligatoire</h3>${gearList(model.gear)}</section>
      <section><h3>Urgence et consignes</h3>
        ${model.emergency.length ? textList(model.emergency) : `<p class="muted">Aucune consigne d'urgence dans le plan.</p>`}
        ${model.notes.length ? textList(model.notes) : ""}
        ${model.nutrition_plan ? `<p class="muted">Plan nutrition : <code>${F.esc(model.nutrition_plan)}</code></p>` : ""}</section>
    </div>
    ${missing}
    <p class="rb-foot muted">Estimations du coach (scénario ${F.esc(SCENARIO_LABEL[name].toLowerCase())}), pas des promesses. Source : ${F.esc(model.plan || "plan de course")}.</p>
  </section>`;
}

/** Page complète (hors en-tête de vue) pour un modèle `status: "ok"`. `wanted` = scénario affiché. */
export function roadbookHtml(model, wanted) {
  const avail = SCENARIO_ORDER.filter((s) => model.scenarios[s] && model.scenarios[s].available);
  if (!avail.length) {
    const why = (model.missing || []).map(F.esc).join("<br>") || "Le plan ne contient pas de temps prédits par scénario.";
    return { html: `<div class="empty"><h3>Roadbook indisponible pour ce plan</h3><p>${why}</p></div>`, active: null };
  }
  const active = avail.includes(wanted) ? wanted : (avail.includes(model.default_scenario) ? model.default_scenario : avail[0]);
  const plans = model.plans && model.plans.length > 1
    ? `<div class="toolbar rb-plans">${model.plans.map((p) => `<a class="seg ${p.path === model.plan ? "is-on" : ""}" href="#/roadbook?plan=${encodeURIComponent(p.path)}">${F.esc(p.race_name || p.path)}${p.race_date ? ` · ${F.esc(p.race_date)}` : ""}</a>`).join("")}</div>` : "";
  const buttons = SCENARIO_ORDER.map((s) => {
    const on = avail.includes(s);
    return `<button type="button" class="seg rb-pick${s === active ? " is-on" : ""}" data-scenario="${s}" aria-pressed="${s === active}"${on ? "" : " disabled"}>${SCENARIO_LABEL[s]}</button>`;
  }).join("");
  const html = `<div class="rb-controls">${plans}
      <div class="toolbar"><span class="rb-controls__label" id="rb-pick-label">Scénario</span><span role="group" aria-labelledby="rb-pick-label" class="rb-picks">${buttons}</span>
        <span class="rb-actions"><button type="button" class="seg rb-print" data-all="0">Imprimer / PDF</button>
        ${avail.length > 1 ? `<button type="button" class="seg rb-print" data-all="1">Imprimer les ${avail.length} scénarios</button>` : ""}</span></div>
      <p class="note">« Imprimer / PDF » ouvre la boîte d'impression du navigateur : choisis « Enregistrer au format PDF » pour un fichier. Format A4 portrait, noir et blanc lisible.</p></div>
    <article class="rb">${avail.map((s) => sheet(model, s, s === active)).join("")}</article>`;
  return { html, active };
}

/** Branche le sélecteur de scénario et les boutons d'impression (aucun appel réseau). */
export function wireRoadbook(root, onScenario) {
  const sheets = [...root.querySelectorAll(".rb-sheet")];
  for (const btn of root.querySelectorAll(".rb-pick")) {
    btn.addEventListener("click", () => {
      const name = btn.dataset.scenario;
      for (const s of sheets) s.classList.toggle("is-active", s.dataset.scenario === name);
      for (const b of root.querySelectorAll(".rb-pick")) {
        b.classList.toggle("is-on", b === btn);
        b.setAttribute("aria-pressed", String(b === btn));
      }
      if (onScenario) onScenario(name);
    });
  }
  for (const btn of root.querySelectorAll(".rb-print")) {
    btn.addEventListener("click", () => {
      const all = btn.dataset.all === "1";
      root.classList.toggle("rb-all", all);
      if (all) window.addEventListener("afterprint", () => root.classList.remove("rb-all"), { once: true });
      window.print();
    });
  }
}
