// Carte et profil de la page séance : trace GPS des échantillons FIT
// (`/api/activity/<id>/track`), colorée par allure, GAP, FC ou pente, liée aux graphiques
// du profil par un curseur commun. Leaflet (copié dans `web/vendor/leaflet/`, aucun
// CDN) n'est chargé qu'ici, à la première carte affichée. Les couleurs viennent du CSS
// (classes `trk--b0…b4`), jamais d'un style en ligne : CSP de `arc_serve.py`.

let leaflet = null;

/** Charge Leaflet (script UMD → `window.L`) et sa feuille de style, une seule fois. */
export function loadLeaflet() {
  if (leaflet) return leaflet;
  leaflet = new Promise((resolve, reject) => {
    if (window.L) { resolve(window.L); return; }
    const css = document.createElement("link");
    css.rel = "stylesheet";
    css.href = "vendor/leaflet/leaflet.css";
    document.head.appendChild(css);
    const js = document.createElement("script");
    js.src = "vendor/leaflet/leaflet.js";
    js.onload = () => resolve(window.L);
    js.onerror = () => { leaflet = null; reject(new Error("Leaflet introuvable (web/vendor/leaflet)")); };
    document.head.appendChild(js);
  });
  return leaflet;
}

// ---------------------------------------------------------------------------
// Profil : rééchantillonnage à pas de distance constant
// ---------------------------------------------------------------------------

/** Valeur interpolée de `ys` à la distance `d` (abscisses `xs` croissantes), `null` hors trace. */
function interp(xs, ys, d, from) {
  let i = from;
  while (i < xs.length - 2 && xs[i + 1] < d) i++;
  const x0 = xs[i], x1 = xs[i + 1];
  const y0 = ys[i], y1 = ys[i + 1];
  if (y0 == null || y1 == null) return { v: y0 ?? y1 ?? null, i };
  const f = x1 > x0 ? Math.min(1, Math.max(0, (d - x0) / (x1 - x0))) : 0;
  return { v: y0 + (y1 - y0) * f, i };
}

/**
 * Le profil se lit en distance, la trace arrive en temps (un point toutes les ~5 s) :
 * les graphiques reçoivent ~600 points à pas de distance constant, pour qu'un rang
 * régulier de `timeChart` soit une vraie échelle de distance. Allure et pente sont
 * dérivées du temps et de l'altitude sur une fenêtre glissante (jamais de la vitesse
 * instantanée, trop bruitée). GAP (famille course à pied) : allure de la même fenêtre
 * divisée par le facteur de pente moyen `gf` calculé par le serveur (`arc_gap.gap_factor`,
 * jamais une seconde copie du modèle ici). Rend `null` sans distance exploitable.
 */
export function resampleByDistance(track, target = 600) {
  const idx = [];
  let last = -Infinity;
  track.d.forEach((d, i) => { if (d != null && d > last) { idx.push(i); last = d; } });
  if (idx.length < 2) return null;
  const pick = (k) => (track[k] ? idx.map((i) => track[k][i]) : null);
  const xs = pick("d");
  const total = xs[xs.length - 1] - xs[0];
  if (total < 200) return null;
  const step = Math.max(10, total / target);
  const n = Math.floor(total / step) + 1;
  const cols = { t: pick("t"), alt: pick("alt"), hr: pick("hr"), cad: pick("cad"), lat: pick("lat"), lon: pick("lon"), gf: pick("gf") };
  const out = { step, n, d: [], t: [], alt: [], hr: [], cad: [], lat: [], lon: [], gf: [], pace: [], gap: [], grade: [] };
  const cursor = Object.fromEntries(Object.keys(cols).map((k) => [k, 0]));
  for (let j = 0; j < n; j++) {
    const d = xs[0] + j * step;
    out.d.push(d);
    for (const k of Object.keys(cols)) {
      if (!cols[k]) { out[k].push(null); continue; }
      const r = interp(xs, cols[k], d, cursor[k]);
      cursor[k] = r.i;
      out[k].push(r.v);
    }
  }
  const at = (arr, j) => arr[Math.max(0, Math.min(n - 1, j))];
  // Cadence sous 60 pas/min : arrêt ou marche très lente, pas une foulée de course.
  out.cad = out.cad.map((v) => (v != null && v >= 60 ? v : null));
  const wPace = Math.max(2, Math.round(150 / step));
  const wGrade = Math.max(2, Math.round(60 / step));
  for (let j = 0; j < n; j++) {
    const t0 = at(out.t, j - wPace), t1 = at(out.t, j + wPace);
    const span = (Math.min(n - 1, j + wPace) - Math.max(0, j - wPace)) * step;
    const pace = t0 != null && t1 != null && span > 0 ? ((t1 - t0) / span) * 1000 : null;
    // Au-delà de 20 min/km, la montre était à l'arrêt (pause, ravitaillement) : pas une allure.
    const moving = pace != null && pace > 90 && pace < 1200;
    out.pace.push(moving ? pace : null);
    // Facteur moyen sur la même fenêtre : à pas de distance constant, c'est la moyenne
    // pondérée par la distance, donc allure ÷ facteur = temps ÷ distance « équivalent plat ».
    let sum = 0, cnt = 0;
    for (let k = Math.max(0, j - wPace); k <= Math.min(n - 1, j + wPace); k++) {
      if (out.gf[k] != null) { sum += out.gf[k]; cnt++; }
    }
    out.gap.push(moving && cnt ? pace / (sum / cnt) : null);
    const a0 = at(out.alt, j - wGrade), a1 = at(out.alt, j + wGrade);
    const gspan = (Math.min(n - 1, j + wGrade) - Math.max(0, j - wGrade)) * step;
    out.grade.push(a0 != null && a1 != null && gspan > 0 ? (a1 - a0) / gspan : null);
  }
  return out;
}

// ---------------------------------------------------------------------------
// Couleur de la trace
// ---------------------------------------------------------------------------

const GRADE_EDGES = [-0.08, -0.02, 0.02, 0.08];

function quantiles(values, qs) {
  const v = values.filter((x) => x != null).sort((a, b) => a - b);
  if (!v.length) return null;
  return qs.map((q) => v[Math.min(v.length - 1, Math.floor(q * v.length))]);
}

const binOf = (v, edges) => {
  if (v == null || !edges) return null;
  let b = 0;
  while (b < edges.length && v >= edges[b]) b++;
  return b;
};

/** Classes de couleur (0 à 4) et légende de chaque mode. `hrBounds` : bornes de zones FC
 * de la séance (`hr_zones.bounds_bpm`), les mêmes que la barre « Zones FC ». */
export function colorModes(profile, hrBounds) {
  const modes = {};
  const paceEdges = quantiles(profile.pace, [0.2, 0.4, 0.6, 0.8]);
  if (paceEdges) {
    // Allure : plus RAPIDE = classe plus haute (couleur plus chaude), comme une zone FC.
    modes.pace = { label: "Allure", bin: (j) => { const b = binOf(profile.pace[j], paceEdges); return b == null ? null : 4 - b; },
      legend: ["la plus lente", "", "", "", "la plus rapide"], legendNote: "quintiles de la séance" };
  }
  const gapEdges = quantiles(profile.gap, [0.2, 0.4, 0.6, 0.8]);
  if (gapEdges) {
    // GAP : l'effort à pente neutralisée — une côte montée à bonne allure ajustée ressort
    // aussi chaud qu'un plat rapide. Quintiles propres à la GAP de la séance.
    modes.gap = { label: "GAP", bin: (j) => { const b = binOf(profile.gap[j], gapEdges); return b == null ? null : 4 - b; },
      legend: ["la plus lente", "", "", "", "la plus rapide"], legendNote: "allure ajustée à la pente, quintiles de la séance" };
  }
  if (hrBounds && profile.hr.some((v) => v != null)) {
    const edges = hrBounds.slice(1, 5);
    modes.hr = { label: "FC", bin: (j) => binOf(profile.hr[j], edges), legend: ["Z1", "Z2", "Z3", "Z4", "Z5"], legendNote: "zones de la séance" };
  }
  if (profile.grade.some((v) => v != null)) {
    modes.grade = { label: "Pente", bin: (j) => binOf(profile.grade[j], GRADE_EDGES),
      legend: ["< −8 %", "−8 à −2 %", "plat", "+2 à +8 %", "> +8 %"], legendNote: "" };
  }
  modes.plain = { label: "Uni", bin: () => 2, legend: null, legendNote: "" };
  return modes;
}

// ---------------------------------------------------------------------------
// Carte
// ---------------------------------------------------------------------------

/**
 * Monte la carte dans `host`. `track` : réponse brute de `/track` (tous les points pour le
 * tracé) ; `profile` : `resampleByDistance(track)` (curseur, couleurs, montées).
 * `opts` : `{tiles, attribution, climbs, onHover(j)}`. Rend `{setMode, showIndex, focusRange,
 * reset}`, ou lève si Leaflet ne charge pas (l'appelant affiche alors une note).
 */
export async function sessionMap(host, track, profile, opts = {}) {
  const L = await loadLeaflet();
  const map = L.map(host, {
    scrollWheelZoom: false, zoomSnap: 0.25, attributionControl: true,
    preferCanvas: false, keyboard: true,
  });
  map.attributionControl.setPrefix('<a href="https://leafletjs.com">Leaflet</a>');
  if (opts.tiles) {
    L.tileLayer(opts.tiles, {
      subdomains: "abc", maxZoom: 17, className: "map-tiles", crossOrigin: false,
      attribution: opts.attribution || "", referrerPolicy: "strict-origin-when-cross-origin",
    }).addTo(map);
  } else {
    host.classList.add("map--blank");
  }
  // Points GPS du tracé complet, avec leur rang dans le profil (à pas de distance).
  const pts = [];
  track.lat.forEach((la, i) => {
    const lo = track.lon[i];
    const d = track.d[i];
    if (la == null || lo == null) return;
    const j = d == null ? null : Math.max(0, Math.min(profile.n - 1, Math.round((d - profile.d[0]) / profile.step)));
    pts.push({ ll: [la, lo], j });
  });
  const bounds = L.latLngBounds(track.bounds);
  const fit = () => map.fitBounds(bounds, { padding: [24, 24] });
  fit();

  const climbLayer = L.layerGroup().addTo(map);
  for (const c of opts.climbs || []) {
    const seg = pts.filter((p) => p.j != null && profile.d[p.j] >= c.start_km * 1000 && profile.d[p.j] <= c.end_km * 1000).map((p) => p.ll);
    if (seg.length < 2) continue;
    L.polyline(seg, { className: "trk-climb", interactive: false }).addTo(climbLayer);
    L.marker(seg[seg.length - 1], {
      interactive: false, keyboard: false,
      icon: L.divIcon({ className: "map-badge", html: String(c.index), iconSize: [20, 20], iconAnchor: [10, 10] }),
    }).addTo(climbLayer);
  }
  // Liseré clair sous la trace : elle reste lisible sur n'importe quelle tuile (forêt, roche, eau).
  L.polyline(pts.map((p) => p.ll), { className: "trk-casing", interactive: false }).addTo(map);
  const traceLayer = L.layerGroup().addTo(map);
  // Ligne de survol invisible et large : le doigt ou la souris n'a pas à viser 3 px.
  const hit = L.polyline(pts.map((p) => p.ll), { className: "trk-hit", weight: 18, opacity: 0 }).addTo(map);
  const pin = (ll, cls, label) => L.marker(ll, {
    interactive: false, keyboard: false, title: label,
    icon: L.divIcon({ className: `map-pin ${cls}`, iconSize: [14, 14], iconAnchor: [7, 7] }),
  }).addTo(map);
  if (pts.length) {
    pin(pts[0].ll, "map-pin--start", "Départ");
    pin(pts[pts.length - 1].ll, "map-pin--finish", "Arrivée");
  }
  const cursor = L.circleMarker(pts[0]?.ll || bounds.getCenter(), { className: "map-cursor", radius: 7, interactive: false });

  const nearest = (latlng) => {
    let best = null, bestD = Infinity;
    for (const p of pts) {
      const dy = p.ll[0] - latlng.lat, dx = (p.ll[1] - latlng.lng) * Math.cos((latlng.lat * Math.PI) / 180);
      const dd = dx * dx + dy * dy;
      if (dd < bestD) { bestD = dd; best = p; }
    }
    return best;
  };
  const onTrace = (ev) => {
    const p = nearest(ev.latlng);
    if (p && p.j != null && opts.onHover) opts.onHover(p.j);
  };
  hit.on("mousemove", onTrace);
  hit.on("click", onTrace);

  const setMode = (mode) => {
    traceLayer.clearLayers();
    let run = [], bin = null;
    const flush = () => {
      if (run.length > 1) L.polyline(run, { className: `trk trk--b${bin ?? 2}`, interactive: false }).addTo(traceLayer);
    };
    for (const p of pts) {
      const b = p.j == null ? bin : (mode.bin(p.j) ?? bin);
      if (b !== bin && run.length) {
        flush();
        run = [run[run.length - 1]];      // segments jointifs, sans trou entre deux couleurs
      }
      bin = b;
      run.push(p.ll);
    }
    flush();
    hit.bringToFront();
  };
  const showIndex = (j) => {
    const la = profile.lat[j], lo = profile.lon[j];
    if (la == null || lo == null) { cursor.remove(); return; }
    cursor.setLatLng([la, lo]);
    if (!map.hasLayer(cursor)) cursor.addTo(map);
  };
  const focusRange = (d0, d1) => {
    const seg = pts.filter((p) => p.j != null && profile.d[p.j] >= d0 && profile.d[p.j] <= d1).map((p) => p.ll);
    if (seg.length > 1) map.fitBounds(L.latLngBounds(seg), { padding: [48, 48], maxZoom: 16 });
  };
  // La mise en page (grille, police) peut finir après le montage : Leaflet doit relire sa taille.
  if ("ResizeObserver" in window) new ResizeObserver(() => map.invalidateSize()).observe(host);
  return { setMode, showIndex, focusRange, reset: fit };
}
