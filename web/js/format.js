// Formats d'affichage. La base est en SI ; seule cette couche convertit
// (`[athlete].units`), en français.

const NBSP = " ";
let UNITS = "metric";

export function setUnits(units) {
  UNITS = units === "imperial" ? "imperial" : "metric";
}

const nf = (digits) => new Intl.NumberFormat("fr-FR", { maximumFractionDigits: digits, minimumFractionDigits: digits });

export function num(value, digits = 0) {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return nf(digits).format(value);
}

export function distance(m, digits = 1) {
  if (m === null || m === undefined) return "—";
  if (UNITS === "imperial") return `${num(m / 1609.344, digits)}${NBSP}mi`;
  return `${num(m / 1000, digits)}${NBSP}km`;
}

export function elevation(m) {
  if (m === null || m === undefined) return "—";
  if (UNITS === "imperial") return `${num(m * 3.28084)}${NBSP}ft`;
  return `${num(m)}${NBSP}m`;
}

export function weight(kg, digits = 1) {
  if (kg === null || kg === undefined) return "—";
  if (UNITS === "imperial") return `${num(kg * 2.20462, digits)}${NBSP}lb`;
  return `${num(kg, digits)}${NBSP}kg`;
}

export function weightRate(kgPerWeek, digits = 2) {
  if (kgPerWeek === null || kgPerWeek === undefined) return "—";
  if (UNITS === "imperial") return `${num(kgPerWeek * 2.20462, digits)}${NBSP}lb/semaine`;
  return `${num(kgPerWeek, digits)}${NBSP}kg/semaine`;
}

// Glucides/h et taux de sudation (#41) : grammes et litres, indépendants de
// `[athlete].units` (pas de convention impériale d'usage pour ces deux grandeurs).
export function carbsRate(gPerHour, digits = 0) {
  if (gPerHour === null || gPerHour === undefined) return "—";
  return `${num(gPerHour, digits)}${NBSP}g/h`;
}

export function sweatRate(litersPerHour, digits = 2) {
  if (litersPerHour === null || litersPerHour === undefined) return "—";
  return `${num(litersPerHour, digits)}${NBSP}l/h`;
}

export function duration(s, { seconds = false } = {}) {
  if (s === null || s === undefined) return "—";
  const total = Math.round(s);
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const sec = total % 60;
  if (h > 0) return `${h}${NBSP}h${NBSP}${String(m).padStart(2, "0")}`;
  if (seconds) return `${m}${NBSP}min${NBSP}${String(sec).padStart(2, "0")}`;
  return `${m}${NBSP}min`;
}

export function hours(s) {
  if (!s) return "0" + NBSP + "h";
  return `${num(s / 3600, 1)}${NBSP}h`;
}

export function pace(distanceM, durationS) {
  if (!distanceM || !durationS) return "—";
  const unit = UNITS === "imperial" ? 1609.344 : 1000;
  const perUnit = durationS / (distanceM / unit);
  const m = Math.floor(perUnit / 60);
  const s = Math.round(perUnit % 60);
  return `${m}:${String(s === 60 ? 59 : s).padStart(2, "0")}/${UNITS === "imperial" ? "mi" : "km"}`;
}

// Allure ajustée à la pente (#44, GAP) : le serveur rend `gap_pace_s_km` déjà
// en SI (secondes par km, jamais une distance/durée séparées comme `pace()`
// ci-dessus) — cette fonction applique la même conversion impériale et le
// même format d'affichage (mm:ss/unité).
export function paceFromSecPerKm(secPerKm) {
  if (secPerKm === null || secPerKm === undefined) return "—";
  const perUnit = UNITS === "imperial" ? secPerKm * 1.609344 : secPerKm;
  const m = Math.floor(perUnit / 60);
  const s = Math.round(perUnit % 60);
  return `${m}:${String(s === 60 ? 59 : s).padStart(2, "0")}/${UNITS === "imperial" ? "mi" : "km"}`;
}

export function clock(s) {
  if (s === null || s === undefined) return "—";
  const total = Math.round(s);
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const sec = total % 60;
  return `${h}:${String(m).padStart(2, "0")}:${String(sec).padStart(2, "0")}`;
}

const DAY = new Intl.DateTimeFormat("fr-FR", { weekday: "long", day: "numeric", month: "long" });
const SHORT = new Intl.DateTimeFormat("fr-FR", { day: "numeric", month: "short" });
const WEEKDAY = new Intl.DateTimeFormat("fr-FR", { weekday: "short" });
const LONG = new Intl.DateTimeFormat("fr-FR", { day: "numeric", month: "long", year: "numeric" });

export const parseDate = (iso) => new Date(`${iso}T12:00:00`);
export const dayLong = (iso) => DAY.format(parseDate(iso));
export const dayShort = (iso) => SHORT.format(parseDate(iso));
export const weekday = (iso) => WEEKDAY.format(parseDate(iso)).replace(".", "");
export const dateLong = (iso) => LONG.format(parseDate(iso));

export function addDays(iso, n) {
  const d = parseDate(iso);
  d.setDate(d.getDate() + n);
  return d.toISOString().slice(0, 10);
}

export function daysBetween(a, b) {
  return Math.round((parseDate(b) - parseDate(a)) / 86400000);
}

export const SPORT = {
  running: "Course", trail: "Trail", strength: "Renforcement", indoor_cycling: "Vélo d'intérieur",
  home_trainer: "Home trainer", hiking: "Randonnée", walking: "Marche", elliptical: "Elliptique",
  rest: "Repos", cycling: "Vélo", swimming: "Natation", rowing: "Aviron",
};

export const VERDICT = { green: "Maintenir", amber: "Alléger", red: "Repos" };
export const WEATHER = { green: "Optimal", yellow: "Vigilance", orange: "Difficile", red: "Dangereux" };
export const SLOT = { morning: "Matin tôt", midday: "Midi", evening: "Soir", none: "Aucun créneau" };
export const STATUS = { planned: "Prévue", done: "Faite", missed: "Manquée", moved: "Déplacée", cancelled: "Annulée" };
export const REPORT = { weekly: "Hebdomadaire", monthly: "Mensuel", comparison: "Comparaison", race: "Course", adhoc: "Ponctuel" };

// Échappement pour les chaînes insérées dans le DOM par innerHTML.
export function esc(text) {
  return String(text ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
