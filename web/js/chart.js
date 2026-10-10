// Graphiques SVG écrits à la main : séries temporelles (lignes, aires, bandes,
// barres, seuils, repères) et calendrier. Aucune dépendance. Les couleurs
// viennent du CSS (classes), jamais d'attributs de style : la CSP de
// `arc_serve.py` interdit les styles en ligne.

const NS = "http://www.w3.org/2000/svg";
const W = 760;
const PAD = { top: 14, right: 16, bottom: 26, left: 44 };

const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const MONTHS = ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc."];

function niceTicks(min, max, count = 4) {
  if (min === max) { min -= 1; max += 1; }
  const raw = (max - min) / count;
  const mag = 10 ** Math.floor(Math.log10(raw));
  // 1, 2, 5 : jamais 2,5 — une graduation « 7,5 » arrondie à « 8 » mentait sur l'axe.
  const step = [1, 2, 5, 10].map((m) => m * mag).find((s) => s >= raw) || raw;
  const lo = Math.floor(min / step) * step;
  const hi = Math.ceil(max / step) * step;
  const ticks = [];
  for (let v = lo; v <= hi + step / 2; v += step) ticks.push(Math.round(v * 1000) / 1000);
  return { lo, hi, ticks };
}

/** Graduations multiples de `step` couvrant [min, max]. */
function stepTicks(min, max, step) {
  const lo = Math.floor(min / step) * step;
  const hi = Math.ceil(max / step) * step;
  const ticks = [];
  for (let v = lo; v <= hi + step / 2; v += step) ticks.push(Math.round(v * 1000) / 1000);
  return { lo, hi, ticks };
}

function pathFrom(points) {
  let d = "";
  let pen = false;
  for (const p of points) {
    if (p === null) { pen = false; continue; }
    d += `${pen ? "L" : "M"}${p[0].toFixed(1)},${p[1].toFixed(1)}`;
    pen = true;
  }
  return d;
}

/**
 * Série temporelle.
 *   dates   : tableau de dates ISO (axe x, un point par entrée)
 *   layers  : [{type: "line"|"area"|"band"|"bars"|"dots", values|lo|hi, cls, axis: "y"|"y2"}]
 *   marks   : [{type: "hline", value, cls, label, axis} | {type: "vline", date, cls, label}]
 *   opts    : {height, y: {min, max, zero}, y2: {...}, yFormat, y2Format, label, band}
 *
 * Avec des barres (ou opts.band), chaque point occupe le centre d'une case : la
 * première et la dernière barre restent dans la zone de tracé au lieu de
 * déborder sur les graduations.
 */
export function timeChart(dates, layers, marks = [], opts = {}) {
  const H = opts.height || 220;
  const iw = W - PAD.left - (opts.y2 ? 44 : PAD.right);
  const ih = H - PAD.top - PAD.bottom;
  const n = dates.length;
  const band = opts.band ?? layers.some((l) => l.type === "bars");
  // Échelle temporelle vraie (`opts.timeScale`, #62) : chaque point à une
  // abscisse proportionnelle à sa date RÉELLE, pas à son rang dans le tableau —
  // indispensable pour une série aux relevés espacés irrégulièrement (mois,
  // parfois années), où un axe par simple rang écraserait les écarts réels.
  // Par défaut (`false`, comportement inchangé pour tous les appelants
  // existants) : un rang régulier, adapté aux séries à pas fixe (jour/semaine).
  const dateMs = opts.timeScale ? dates.map((d) => Date.parse(`${d}T00:00:00Z`)) : null;
  const span = dateMs && n > 1 ? (dateMs[n - 1] - dateMs[0] || 1) : 1;
  const x = band
    ? (i) => PAD.left + ((i + 0.5) / Math.max(n, 1)) * iw
    : dateMs
      ? (i) => PAD.left + (n <= 1 ? iw / 2 : ((dateMs[i] - dateMs[0]) / span) * iw)
      : (i) => PAD.left + (n <= 1 ? iw / 2 : (i / (n - 1)) * iw);
  // Inverse de x : l'indice le plus proche d'une abscisse (curseur). En échelle
  // temporelle, les points ne sont pas régulièrement espacés : recherche du
  // plus proche par balayage (séries courtes en pratique — relevés d'indice,
  // pas des séries quotidiennes), plutôt qu'un calcul de rang qui supposerait
  // un espacement régulier.
  const index = band
    ? (px) => Math.floor(((px - PAD.left) / iw) * n)
    : dateMs
      ? (px) => {
          if (n <= 1) return 0;
          const targetMs = dateMs[0] + ((px - PAD.left) / iw) * span;
          let best = 0;
          let bestDiff = Infinity;
          dateMs.forEach((ms, i) => {
            const diff = Math.abs(ms - targetMs);
            if (diff < bestDiff) { bestDiff = diff; best = i; }
          });
          return best;
        }
      : (px) => Math.round(((px - PAD.left) / iw) * (n - 1));
  const anchor = (i) => (i === 0 && !band ? "start" : "middle");

  const scale = (axis) => {
    const vals = [];
    for (const l of layers.filter((l) => (l.axis || "y") === axis)) {
      for (const k of ["values", "lo", "hi"]) (l[k] || []).forEach((v) => v !== null && v !== undefined && vals.push(v));
    }
    for (const m of marks.filter((m) => m.type === "hline" && (m.axis || "y") === axis)) vals.push(m.value);
    const o = opts[axis] || {};
    let min = o.min ?? Math.min(...vals);
    let max = o.max ?? Math.max(...vals);
    if (o.zero) { min = Math.min(0, min); max = Math.max(0, max); }
    if (!Number.isFinite(min) || !Number.isFinite(max)) { min = 0; max = 1; }
    // `o.step` : pas imposé (ex. allure en minutes, où les pas décimaux 1/2/5 de
    // `niceTicks` tombent mal) ; sinon pas « rond » choisi par `niceTicks`.
    const t = o.step ? stepTicks(min, max, o.step) : niceTicks(min, max, o.ticks || 4);
    const lo = o.min ?? t.lo;
    const hi = o.max ?? t.hi;
    // `o.invert` (défaut absent = comportement inchangé) : la petite valeur en haut,
    // la grande en bas — utile pour une allure (plus RAPIDE = nombre plus petit),
    // où « en haut » doit rester « meilleur », comme pour toute autre série du
    // tableau de bord. Mathématiquement l'exacte réciproque de la formule non
    // inversée ci-dessous (`frac` vers 0 en haut au lieu du bas) : aucune autre
    // série existante ne passe `invert`, donc aucun changement pour elles.
    const frac = (v) => (v - lo) / (hi - lo || 1);
    const y = o.invert ? (v) => PAD.top + frac(v) * ih : (v) => PAD.top + ih - frac(v) * ih;
    return { lo, hi, ticks: t.ticks.filter((v) => v >= lo && v <= hi), y };
  };
  const axes = { y: scale("y") };
  if (opts.y2) axes.y2 = scale("y2");

  const parts = [];
  // Grille et axes
  for (const t of axes.y.ticks) {
    const yy = axes.y.y(t);
    parts.push(`<line class="grid" x1="${PAD.left}" x2="${PAD.left + iw}" y1="${yy}" y2="${yy}"/>`);
    parts.push(`<text class="tick" x="${PAD.left - 6}" y="${yy + 4}" text-anchor="end">${esc(opts.yFormat ? opts.yFormat(t) : t)}</text>`);
  }
  if (axes.y2) {
    for (const t of axes.y2.ticks) {
      const yy = axes.y2.y(t);
      parts.push(`<text class="tick tick--y2" x="${PAD.left + iw + 6}" y="${yy + 4}">${esc(opts.y2Format ? opts.y2Format(t) : t)}</text>`);
    }
  }
  // Axe x : libellés de catégories (km…) ou mois
  if (opts.xLabels) {
    const shown = opts.xLabels.filter(Boolean).length;
    const every = shown <= Math.floor(iw / 30) ? 1 : Math.ceil(n / Math.floor(iw / 30));
    if (opts.timeScale) {
      // En échelle temporelle (#62/#109), `every` seul ne suffit pas : deux
      // dates rapprochées peuvent tomber à quelques pixels l'une de l'autre
      // (ex. 1 et 8 mars, ~11 px) même si leur écart d'INDICE passe le filtre
      // `every` — celui-ci suppose un espacement RÉGULIER par rang, faux ici
      // par construction. Filtre dédié, jamais appliqué aux autres appelants
      // (rang régulier, sans ce problème) :
      // 1. la distance minimale entre deux libellés affichés est dérivée de
      //    leur largeur ESTIMÉE (nombre de caractères × une largeur de
      //    caractère approximative pour la police du tableau de bord, #109
      //    3e tour) — jamais une constante arbitraire, qui serait tantôt trop
      //    large pour deux libellés courts, tantôt trop étroite pour deux
      //    libellés longs (l'année alourdit chaque repère, voir
      //    `indexMiniChart` dans `web/js/app.js`) ;
      // 2. le DERNIER point (le plus récent, celui qu'on lit en premier) est
      //    TOUJOURS affiché : si son libellé chevaucherait le précédent, c'est
      //    ce dernier qui est retiré, jamais l'inverse (#109 3e tour) ;
      // 3. ce dernier libellé est ancré à "end" (jamais "middle") pour ne
      //    jamais déborder du viewBox à droite : son point est au bord droit
      //    de la zone de tracé, un ancrage centré y ferait dépasser la moitié
      //    du texte.
      // Pire cas, jamais la taille de bureau (revue de code #109, 3e tour,
      // BLOQUANT visuel) : `.chart .tick` fait 11px sur bureau MAIS 21px en
      // dessous de 36em (`web/css/app.css`, media query dédiée à la
      // lisibilité tactile) — le SVG scale tout le RESTE proportionnellement
      // (viewBox), mais PAS ce texte, dont la taille CSS reste fixe en
      // pixels physiques quel que soit le facteur d'échelle du graphique.
      // Cette fonction ne connaît pas la largeur d'écran du client (le SVG
      // généré est le MÊME sur mobile et sur bureau) : elle doit donc estimer
      // avec la police la PLUS GRANDE des deux, sous peine de sous-estimer
      // largement la largeur réelle sur mobile (chevauchement constaté avec
      // 11px : deux libellés jugés espacés de ~15 unités s'affichaient en fait
      // à cheval l'un sur l'autre, la police réelle étant presque deux fois
      // plus grande que l'estimation).
      const FONT_SIZE_PX = 21;
      const CHAR_WIDTH_FACTOR = 0.6;
      const LABEL_GAP_MARGIN_PX = 8;
      const estimateLabelWidth = (label) => label.length * FONT_SIZE_PX * CHAR_WIDTH_FACTOR;
      // Étendue [gauche, droite] RÉELLE d'un libellé selon son ancrage — un
      // label "start" (le premier point) déborde ENTIÈREMENT vers la droite
      // depuis `xi`, jamais pour moitié comme le supposerait une simple
      // demi-largeur symétrique (bug de la première tentative : le premier
      // libellé, ancré "start", débordait bien plus que prévu sur le suivant).
      const labelExtent = (label, xi, anchorType) => {
        const w = estimateLabelWidth(label);
        if (anchorType === "start") return [xi, xi + w];
        if (anchorType === "end") return [xi - w, xi];
        return [xi - w / 2, xi + w / 2];
      };
      const candidates = [];
      opts.xLabels.forEach((label, i) => {
        if (label && (every === 1 || i % every === 0 || i === n - 1)) {
          // Le DERNIER point (le plus récent) est ancré "end" (jamais "middle")
          // pour ne jamais déborder du viewBox à droite (#109 3e tour) : son
          // point est au bord droit de la zone de tracé.
          const anchorType = i === n - 1 ? "end" : anchor(i);
          const xi = x(i);
          const [left, right] = labelExtent(label, xi, anchorType);
          candidates.push({ i, label, xi, anchorType, left, right });
        }
      });
      const visible = [];
      for (const c of candidates) {
        const prev = visible[visible.length - 1];
        const overlaps = prev && c.left < prev.right + LABEL_GAP_MARGIN_PX;
        if (!prev || !overlaps) {
          visible.push(c);
        } else if (c.i === n - 1) {
          // Le dernier libellé prime toujours : on retire le précédent plutôt
          // que de faire disparaître celui-ci (#109 3e tour).
          visible.pop();
          visible.push(c);
        }
      }
      visible.forEach((c) => {
        parts.push(`<text class="tick" x="${c.xi}" y="${H - 8}" text-anchor="${c.anchorType}">${esc(c.label)}</text>`);
      });
    } else {
      opts.xLabels.forEach((label, i) => {
        if (label && (every === 1 || i % every === 0 || i === n - 1)) {
          parts.push(`<text class="tick" x="${x(i)}" y="${H - 8}" text-anchor="${anchor(i)}">${esc(label)}</text>`);
        }
      });
    }
  }
  let lastMonth = opts.xLabels ? "skip" : null;
  let lastX = -Infinity;
  dates.forEach((d, i) => {
    const month = d.slice(0, 7);
    if (lastMonth !== "skip" && month !== lastMonth && (n < 60 ? d.slice(8) <= "07" || i === 0 : d.slice(8) === "01" || i === 0)) {
      lastMonth = month;
      if (x(i) - lastX < 52) return;                 // pas de libellés qui se chevauchent
      const m = Number(d.slice(5, 7)) - 1;
      const label = n <= 21 ? `${Number(d.slice(8))} ${MONTHS[m]}` : MONTHS[m];
      parts.push(`<text class="tick" x="${x(i)}" y="${H - 8}" text-anchor="${anchor(i)}">${label}</text>`);
      lastX = x(i);
    }
  });

  const bw = Math.max(2, Math.min(28, (iw / Math.max(n, 1)) * 0.62));
  for (const l of layers) {
    const ax = axes[l.axis || "y"];
    if (l.type === "band") {
      const top = [];
      const bottom = [];
      l.lo.forEach((lo, i) => {
        const hi = l.hi[i];
        if (lo === null || hi === null || lo === undefined || hi === undefined) return;
        top.push([x(i), ax.y(hi)]);
        bottom.unshift([x(i), ax.y(lo)]);
      });
      if (top.length) parts.push(`<path class="${l.cls}" d="${pathFrom(top)}L${pathFrom(bottom).slice(1)}Z"/>`);
    } else if (l.type === "area") {
      const base = ax.y(Math.max(ax.lo, Math.min(ax.hi, l.base ?? 0)));
      let run = [];
      const flush = () => {
        if (run.length > 1) parts.push(`<path class="${l.cls}" d="M${run[0][0]},${base}${run.map((p) => `L${p[0].toFixed(1)},${p[1].toFixed(1)}`).join("")}L${run[run.length - 1][0]},${base}Z"/>`);
        run = [];
      };
      l.values.forEach((v, i) => (v === null || v === undefined ? flush() : run.push([x(i), ax.y(v)])));
      flush();
    } else if (l.type === "line") {
      const pts = l.values.map((v, i) => (v === null || v === undefined ? null : [x(i), ax.y(v)]));
      parts.push(`<path class="${l.cls}" d="${pathFrom(pts)}"/>`);
    } else if (l.type === "dots") {
      l.values.forEach((v, i) => {
        if (v !== null && v !== undefined) parts.push(`<circle class="${l.cls}" cx="${x(i)}" cy="${ax.y(v)}" r="${l.r || 2.6}"/>`);
      });
    } else if (l.type === "bars") {
      const zero = ax.y(Math.max(ax.lo, 0));
      l.values.forEach((v, i) => {
        if (!v) return;
        const y1 = ax.y(v);
        const cls = typeof l.cls === "function" ? l.cls(i, v) : l.cls;
        parts.push(`<rect class="${cls}" x="${(x(i) - bw / 2).toFixed(1)}" y="${Math.min(y1, zero).toFixed(1)}" width="${bw.toFixed(1)}" height="${Math.max(1, Math.abs(zero - y1)).toFixed(1)}" rx="1.5"/>`);
      });
    }
  }
  for (const m of marks) {
    if (m.type === "hline") {
      const ax = axes[m.axis || "y"];
      if (m.value < ax.lo || m.value > ax.hi) continue;
      const yy = ax.y(m.value);
      parts.push(`<line class="${m.cls || "mark"}" x1="${PAD.left}" x2="${PAD.left + iw}" y1="${yy}" y2="${yy}"/>`);
      if (m.label) parts.push(`<text class="mark-label" x="${PAD.left + iw - 4}" y="${yy - 5}" text-anchor="end">${esc(m.label)}</text>`);
    } else if (m.type === "vline") {
      const i = dates.indexOf(m.date);
      if (i < 0) continue;
      parts.push(`<line class="${m.cls || "mark"}" x1="${x(i)}" x2="${x(i)}" y1="${PAD.top}" y2="${PAD.top + ih}"/>`);
      if (m.label) parts.push(`<text class="mark-label" x="${x(i) + (i > n * 0.8 ? -5 : 5)}" y="${PAD.top + 11}" text-anchor="${i > n * 0.8 ? "end" : "start"}">${esc(m.label)}</text>`);
    }
  }
  parts.push(`<line class="cursor" x1="0" x2="0" y1="${PAD.top}" y2="${PAD.top + ih}" visibility="hidden"/>`);
  parts.push(`<rect class="hit" x="${PAD.left}" y="${PAD.top}" width="${iw}" height="${ih}"/>`);

  const svg = `<svg class="chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(opts.label || "")}" xmlns="${NS}">${parts.join("")}</svg>`;
  return { svg, x, n, iw, index };
}

/**
 * Relie un graphique à une ligne de lecture : survol / toucher / clavier
 * déplacent un curseur et appellent onIndex(i). Rend `move(i)`, qui place le
 * curseur SANS rappeler onIndex — pour lier plusieurs graphiques (et la carte de
 * la page séance) à un même curseur sans boucle.
 */
export function attachCursor(host, chart, onIndex, initial = chart.n - 1) {
  const svg = host.querySelector("svg.chart");
  if (!svg) return () => {};
  const cursor = svg.querySelector(".cursor");
  const hit = svg.querySelector(".hit");
  let current = initial;
  const move = (i) => {
    current = Math.max(0, Math.min(chart.n - 1, i));
    const xx = chart.x(current);
    cursor.setAttribute("x1", xx);
    cursor.setAttribute("x2", xx);
    cursor.setAttribute("visibility", "visible");
  };
  const set = (i) => {
    move(i);
    onIndex(current);
  };
  const fromEvent = (ev) => {
    const box = svg.getBoundingClientRect();
    const px = ((ev.clientX - box.left) / box.width) * W;
    const i = chart.index(px);
    set(i);
  };
  hit.addEventListener("pointermove", fromEvent);
  hit.addEventListener("pointerdown", fromEvent);
  svg.setAttribute("tabindex", "0");
  svg.addEventListener("keydown", (ev) => {
    if (ev.key === "ArrowLeft") { set(current - 1); ev.preventDefault(); }
    if (ev.key === "ArrowRight") { set(current + 1); ev.preventDefault(); }
  });
  if (chart.n && initial !== null) set(initial);
  return move;
}

/** Bande de verdicts (un rectangle par jour), alignée sur un timeChart. */
export function verdictStrip(dates, verdicts) {
  const n = dates.length;
  const iw = W - PAD.left - PAD.right;
  const w = n <= 1 ? 12 : iw / (n - 1);
  const cx = (i) => PAD.left + (n <= 1 ? iw / 2 : (i * iw) / (n - 1));   // mêmes abscisses que timeChart
  const cells = verdicts.map((v, i) => (v ? `<rect class="strip strip--${v}" x="${(cx(i) - w / 2 + 0.5).toFixed(1)}" y="2" width="${Math.max(1.5, w - 1).toFixed(1)}" height="12" rx="2"><title>${dates[i]}</title></rect>` : "")).join("");
  return `<svg class="chart chart--strip" viewBox="0 0 ${W} 16" aria-hidden="true" xmlns="${NS}"><line class="strip-base" x1="${PAD.left}" x2="${PAD.left + iw}" y1="8" y2="8"/>${cells}</svg>`;
}

/** Calendrier annuel (semaines en colonnes, lundi en haut). */
export function yearCalendar(year, byDate, valueOf, bucketOf) {
  const first = new Date(`${year}-01-01T12:00:00`);
  const offset = (first.getDay() + 6) % 7;
  const cell = 12;
  const gap = 2;
  const parts = [];
  const days = (new Date(`${year + 1}-01-01T12:00:00`) - first) / 86400000;
  for (let d = 0; d < days; d++) {
    const date = new Date(first.getTime() + d * 86400000);
    const iso = date.toISOString().slice(0, 10);
    const pos = d + offset;
    const col = Math.floor(pos / 7);
    const row = pos % 7;
    const row0 = byDate[iso];
    const bucket = row0 ? bucketOf(valueOf(row0)) : 0;
    const title = row0 ? `${iso} — ${valueOf(row0, true)}` : iso;
    parts.push(`<rect class="cal cal--${bucket}" x="${28 + col * (cell + gap)}" y="${16 + row * (cell + gap)}" width="${cell}" height="${cell}" rx="2.5"><title>${esc(title)}</title></rect>`);
    if (date.getDate() === 1) parts.push(`<text class="tick" x="${28 + col * (cell + gap)}" y="10">${MONTHS[date.getMonth()]}</text>`);
  }
  ["L", "", "M", "", "V", "", ""].forEach((l, r) => l && parts.push(`<text class="tick" x="16" y="${16 + r * (cell + gap) + 10}" text-anchor="middle">${l}</text>`));
  const width = 28 + 54 * (cell + gap);
  return `<svg class="chart chart--cal" viewBox="0 0 ${width} ${16 + 7 * (cell + gap)}" role="img" aria-label="Calendrier ${year}" xmlns="${NS}">${parts.join("")}</svg>`;
}

/** Frise du bloc (#193) : une colonne par semaine planifiée, teinte = phase, hauteur = volume prévu,
 * trait = volume réalisé, pastille = semaine allégée, drapeau = course, cadre = semaine courante.
 * Chaque semaine est un LIEN (`<a>`, focalisable au clavier) ; aucune couleur ni taille en `style` :
 * tout passe par les classes `.frise-*` (CSP). Dimensions fixes en px (`width`/`height`) : le défilement
 * horizontal est dans la carte (`.chart-host--frise`), jamais dans la page.
 * `items` : { href, aria, tip, phase, phaseText, tick, h (0–1|null), d (0–1|null), light, current, selected, race }. */
export function blockFrise(items, label) {
  const cw = 46, gap = 4, top = 22, barH = 64, left = 6;
  const parts = [];
  items.forEach((it, i) => {
    const x = left + i * (cw + gap);
    const hh = Math.max(4, Math.round(barH * Math.max(0, Math.min(1, it.h ?? 0))));
    const cls = ["frise-cell", `frise-cell--${it.phase}`, it.h == null ? "frise-cell--noplan" : ""].filter(Boolean).join(" ");
    const state = `${it.current ? " is-current" : ""}${it.selected ? " is-selected" : ""}`;
    let g = `<rect class="frise-track" x="${x}" y="${top}" width="${cw}" height="${barH}" rx="4"/>`;
    g += `<rect class="${cls}" x="${x}" y="${top + barH - hh}" width="${cw}" height="${hh}" rx="4"/>`;
    if (it.d != null) {
      const dy = top + barH - Math.max(2, Math.round(barH * Math.max(0, Math.min(1, it.d))));
      g += `<line class="frise-done-case" x1="${x + 3}" x2="${x + cw - 3}" y1="${dy}" y2="${dy}"/><line class="frise-done" x1="${x + 3}" x2="${x + cw - 3}" y1="${dy}" y2="${dy}"/>`;
    }
    g += `<rect class="frise-focus${state}" x="${x - 1.5}" y="${top - 1.5}" width="${cw + 3}" height="${barH + 3}" rx="5.5"/>`;
    if (it.light) g += `<circle class="frise-light" cx="${x + cw / 2}" cy="${top + barH + 9}" r="3.5"/>`;
    g += `<text class="tick frise-tick${state}" x="${x + cw / 2}" y="${top - 7}" text-anchor="middle">${esc(it.tick)}</text>`;
    if (it.race) g += `<path class="frise-flag" d="M${x + 4} ${top + 4} v20 M${x + 4} ${top + 4} h14 l-3 5 l3 5 h-14"/>`;
    parts.push(`<a href="${esc(it.href)}" aria-label="${esc(it.aria)}" data-i="${i}"><title>${esc(it.tip)}</title>${g}</a>`);
  });
  // Étiquettes de phase : une par suite de semaines de même phase, seulement si elle tient dans la largeur.
  let i = 0;
  while (i < items.length) {
    let j = i;
    while (j + 1 < items.length && items[j + 1].phaseText === items[i].phaseText) j++;
    const width = (j - i + 1) * (cw + gap) - gap;
    if (width >= 62 && items[i].phaseText) parts.push(`<text class="frise-phase" x="${left + i * (cw + gap)}" y="${top + barH + 30}">${esc(items[i].phaseText)}</text>`);
    i = j + 1;
  }
  const width = left * 2 + items.length * (cw + gap) - gap;
  const height = top + barH + 38;
  return `<svg class="chart chart--frise" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}" role="group" aria-label="${esc(label)}" xmlns="${NS}">${parts.join("")}</svg>`;
}
