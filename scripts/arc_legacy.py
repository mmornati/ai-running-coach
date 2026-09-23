#!/usr/bin/env python3
"""Lecture best-effort des fichiers écrits AVANT le contrat ```arc.

Trois formats coexistent dans les workspaces existants :

1. le format « canonique » du sync Garmin : bloc YAML sous
   `## Données brutes Garmin (référence)` + tableau `## Analyse par splits (km)`
   (ce que lisait `compare_course.py`, dont les parseurs vivent désormais ici) ;
2. des listes à puces `- Libellé : valeur`, avec des nombres écrits à la
   française (« 12,4 km », « 2 400 m », « 1 h 12 ») — c'est aussi le format des
   deux fichiers édités par l'humain, `planning/Runner_Profile.md` et
   `planning/active_objective.md`, dont les libellés sont fixés par les
   modèles de `templates/` ;
3. du texte libre, dont on ne tire rien.

Chaque fonction `legacy_*` rend un dict au format du contrat (mêmes clés, SI),
rempli de ce qui a pu être lu. Ce n'est jamais une garantie : l'indexeur marque
ces lignes `parsed_ok = 'partial'` et `arc_index.py backfill-plan` liste ce qui
manque pour qu'un agent réécrive le fichier au contrat.

Bibliothèque standard uniquement (CONTRIBUTING.md).
"""

from __future__ import annotations

import re
import unicodedata
from datetime import date, timedelta
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# Nombres, durées, dates « à la française »
# ---------------------------------------------------------------------------

_SPACES = "    "      # espace, insécable, fine insécable, fine
_NUMBER_RE = re.compile(
    r"[-+]?\d{1,3}(?:[    ]\d{3})+(?:[.,]\d+)?"   # 2 400 / 2 400,5
    r"|[-+]?\d+(?:[.,]\d+)?"                                      # 12,4 / 188 / 7.5
)


def parse_fr_number(text) -> Optional[float]:
    """Premier nombre d'un texte, virgule décimale et espace des milliers admis."""
    if text is None:
        return None
    if isinstance(text, (int, float)) and not isinstance(text, bool):
        return float(text)
    match = _NUMBER_RE.search(str(text).replace("*", ""))
    if not match:
        return None
    raw = match.group(0)
    for space in _SPACES:
        raw = raw.replace(space, "")
    return float(raw.replace(",", "."))


def parse_fr_duration(text) -> Optional[float]:
    """Durée → secondes. « 1 h 12 », « 7h00 », « 1:23:26 », « 5:58 », « 40 min », « 45' »."""
    if text is None:
        return None
    t = str(text).replace("*", "").strip().lower()
    for space in _SPACES:
        t = t.replace(space, " ")
    match = re.search(r"(\d+)\s*h\s*(\d{1,2})?\s*(?:min|mn|m)?\s*(?:(\d{1,2})\s*s)?", t)
    if match:
        return int(match.group(1)) * 3600 + int(match.group(2) or 0) * 60 + int(match.group(3) or 0)
    match = re.search(r"\b(\d+):(\d{2}):(\d{2}(?:[.,]\d+)?)\b", t)
    if match:
        return int(match.group(1)) * 3600 + int(match.group(2)) * 60 + float(match.group(3).replace(",", "."))
    match = re.search(r"\b(\d+):(\d{2}(?:[.,]\d+)?)\b", t)
    if match:                                   # m:ss, comme dans les splits
        return int(match.group(1)) * 60 + float(match.group(2).replace(",", "."))
    match = re.search(r"(\d+)\s*(?:min|mn)\s*(\d{1,2})\s*s\b", t)
    if match:
        return int(match.group(1)) * 60 + int(match.group(2))
    match = re.search(r"(\d+(?:[.,]\d+)?)\s*(?:min|mn|'|’)", t)
    if match:
        return float(match.group(1).replace(",", ".")) * 60
    match = re.search(r"(\d+(?:[.,]\d+)?)\s*s\b", t)
    if match:
        return float(match.group(1).replace(",", "."))
    return None


def parse_fr_distance_m(text) -> Optional[float]:
    """Distance → mètres. « 12,4 km » → 12400, « 480 m » → 480, nombre nu → km."""
    value = parse_fr_number(text)
    if value is None:
        return None
    t = str(text).lower()
    if re.search(r"\d\s*(?:m|mètres?|metres?)\b", t) and "km" not in t:
        return value
    if "mi" in t.split() or re.search(r"\d\s*miles?\b", t):
        return value * 1609.344
    return value * 1000.0


_MONTHS = {
    "janvier": 1, "février": 2, "fevrier": 2, "mars": 3, "avril": 4, "mai": 5, "juin": 6,
    "juillet": 7, "août": 8, "aout": 8, "septembre": 9, "octobre": 10, "novembre": 11,
    "décembre": 12, "decembre": 12,
}


def parse_fr_date(text) -> Optional[str]:
    """Date → AAAA-MM-JJ. ISO, « 13/06/2026 » ou « 13 juin 2026 »."""
    if not text:
        return None
    t = str(text).strip().lower()
    match = re.search(r"(\d{4})-(\d{2})-(\d{2})", t)
    candidates = []
    if match:
        candidates.append((int(match.group(1)), int(match.group(2)), int(match.group(3))))
    match = re.search(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b", t)
    if match:
        candidates.append((int(match.group(3)), int(match.group(2)), int(match.group(1))))
    match = re.search(r"\b(\d{1,2})(?:er)?\s+([a-zéûô]+)\s+(\d{4})\b", t)
    if match and match.group(2) in _MONTHS:
        candidates.append((int(match.group(3)), _MONTHS[match.group(2)], int(match.group(1))))
    for year, month, day in candidates:
        try:
            return date(year, month, day).isoformat()
        except ValueError:
            continue
    return None


def filename_date(name: str) -> Optional[str]:
    match = re.match(r"(\d{4}-\d{2}-\d{2})_", name)
    if not match:
        return None
    try:
        return date.fromisoformat(match.group(1)).isoformat()
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Puces « - Libellé : valeur »
# ---------------------------------------------------------------------------

def normalize_label(label: str) -> str:
    """« **FC de repos de référence** » → « fc de repos de reference »."""
    label = label.replace("*", "").replace("\u2019", "'").strip().rstrip(":").strip().lower()
    label = unicodedata.normalize("NFKD", label)
    return "".join(c for c in label if not unicodedata.combining(c))


_BULLET_RE = re.compile(r"^\s*[-*]\s+(\*\*[^*]+\*\*|[^:\n]+?)\s*:\s*(.*)$")
# Ligne de tableau « libellé | valeur » : | **Distance** | 35.90 km | … |
_TABLE_ROW_RE = re.compile(r"^\s*\|([^|]+)\|([^|]+)\|")
_TABLE_SEPARATOR_RE = re.compile(r"^[\s:|-]+$")


def parse_bullets(text: str) -> Dict[str, str]:
    """Dict libellé normalisé → valeur (commentaires HTML retirés, valeurs vides omises).

    Lit les puces `- Libellé : valeur` et les tableaux à deux colonnes
    `| Libellé | Valeur |` (la première colonne sert de libellé).

    Le premier libellé rencontré gagne : un modèle ne répète pas ses champs, et
    une redite plus bas est plus souvent un commentaire qu'une correction.
    """
    out: Dict[str, str] = {}
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    for line in text.splitlines():
        match = _BULLET_RE.match(line)
        if not match and not _TABLE_SEPARATOR_RE.match(line):
            match = _TABLE_ROW_RE.match(line)      # tableau libellé | valeur (en-têtes compris : inoffensifs)
        if not match:
            continue
        label, value = normalize_label(match.group(1)), match.group(2).strip()
        # « - **Lieu :** Tournai » : les deux-points sont dans le gras
        if label.endswith(":"):
            label = label.rstrip(":").strip()
        value = value.replace("**", "").strip()
        if value and label not in out:
            out[label] = value
    return out


def _pick(bullets: Dict[str, str], *prefixes: str) -> Optional[str]:
    """Valeur du libellé égal à l'un des préfixes, sinon du premier qui en commence un.

    L'égalité passe d'abord : « Lieu » ne doit pas prendre la valeur de
    « Lieu d'entraînement par défaut » parce que ce dernier est écrit plus haut.
    """
    for prefix in prefixes:
        if prefix in bullets:
            return bullets[prefix]
    for prefix in prefixes:
        for label, value in bullets.items():
            if label.startswith(prefix + " ") or label.startswith(prefix + "("):
                return value
    return None


def title_of(text: str) -> Optional[str]:
    for line in text.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return None


# ---------------------------------------------------------------------------
# Format canonique du sync (anciennement dans compare_course.py)
# ---------------------------------------------------------------------------

def parse_split_time(txt: str) -> Optional[float]:
    """Parse '5:58' ou '1:23:26' → secondes. Retourne None si invalide.
    Tolère les balises markdown **bold** autour de la valeur."""
    txt = txt.strip().replace("*", "").replace(",", ".")
    parts = txt.split(":")
    try:
        if len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
        if len(parts) == 2:
            return int(parts[0]) * 60 + float(parts[1])
        if len(parts) == 1:
            return float(parts[0])
    except ValueError:
        return None
    return None


def parse_yaml_block(md_text: str) -> Dict[str, Any]:
    """Extrait le bloc '## Données brutes Garmin (référence)' → dict."""
    data: Dict[str, Any] = {}
    m = re.search(r"## Données brutes Garmin \(référence\)\s*```(?:yaml)?\s*(.*?)```", md_text, re.S)
    if not m:
        return data
    for line in m.group(1).splitlines():
        line = line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, _, val = line.partition(":")
        key = key.strip()
        val = val.strip()
        # retire les commentaires en fin de ligne
        val = re.sub(r"\s*#.*$", "", val).strip()
        if val in ("", "null", "~"):
            data[key] = None
            continue
        # conversion numérique quand possible
        if re.fullmatch(r"-?\d+", val):
            data[key] = int(val)
        elif re.fullmatch(r"-?\d+\.\d+", val):
            data[key] = float(val)
        else:
            data[key] = val.strip('"\'')
    return data


def parse_splits_table(md_text: str) -> List[Dict[str, Any]]:
    """Parse le tableau '## Analyse par splits (km)' → liste de splits.

    Format attendu par ligne :
        | 1 | 5:58 | 5:58 | 11.2 | +3/-36 | 120 | 166 | Échauffement |
    Colonnes : num, durée, allure, vmax, D+/D-, FC moy, cadence, lecture.
    """
    splits: List[Dict[str, Any]] = []
    m = re.search(r"## Analyse par splits \(km\)\s*\n(.*?)(?:\n##|\Z)", md_text, re.S)
    if not m:
        return splits
    lines = m.group(1).splitlines()
    header_seen = False
    for line in lines:
        line = line.strip()
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        # détecte l'en-tête
        if not header_seen:
            if any("Split" in c or "Durée" in c for c in cells):
                header_seen = True
            continue
        if len(cells) < 7:
            continue
        num = cells[0]
        if not num.isdigit():
            continue
        duration = parse_split_time(cells[1])
        if duration is None:
            continue
        dplus_dminus = cells[4] if len(cells) > 4 else "+0/-0"
        # ignore les balises markdown (**bold**) autour des valeurs
        dplus_dminus_clean = dplus_dminus.replace("*", "")
        mdn = re.search(r"([+-]?\d+(?:\.\d+)?)\s*/\s*([+-]?\d+(?:\.\d+)?)", dplus_dminus_clean)
        dplus = abs(float(mdn.group(1))) if mdn else 0.0
        dminus = abs(float(mdn.group(2))) if mdn else 0.0
        try:
            fc_moy = float(cells[5].replace("*", "")) if cells[5].replace("*", "").strip() not in ("—", "-", "") else None
        except ValueError:
            fc_moy = None
        splits.append({
            "num": int(num),
            "duration_s": duration,
            "dplus_m": dplus,
            "dminus_m": dminus,
            "hr_avg_bpm": fc_moy,
        })
    return splits


# ---------------------------------------------------------------------------
# Lecteurs par type
# ---------------------------------------------------------------------------

def _drop_none(d: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in d.items() if v is not None}


def _int(value) -> Optional[int]:
    return None if value is None else int(round(value))


def sport_from_filename(name: str) -> Optional[str]:
    """`2026-05-04_home_trainer_endurance.md` → `home_trainer` ; None si le type n'est pas un sport."""
    from arc_contract import SPORTS
    match = re.match(r"\d{4}-\d{2}-\d{2}_([a-z_]+)", name)
    if not match:
        return None
    kind = match.group(1)
    for sport in sorted(SPORTS, key=len, reverse=True):
        if kind == sport or kind.startswith(sport + "_"):
            return sport
    return None


def _sport_from_filename(name: str, default: str) -> str:
    return sport_from_filename(name) or default


def legacy_activity(text: str, filename: str, default_sport: str = "running") -> Dict[str, Any]:
    day = filename_date(filename)
    sport = _sport_from_filename(filename, default_sport)
    yaml_data = parse_yaml_block(text)
    table = parse_splits_table(text)
    bullets = parse_bullets(text)

    out: Dict[str, Any] = {"arc": 0, "kind": "activity", "date": day, "sport": sport}
    if yaml_data:
        out.update(_drop_none({
            "garmin_activity_id": yaml_data.get("activity_id"),
            "name": yaml_data.get("name"),
            "distance_m": yaml_data.get("distance_m"),
            "duration_s": yaml_data.get("duration_s"),
            "elevation_gain_m": yaml_data.get("elevation_gain_m"),
            "elevation_loss_m": yaml_data.get("elevation_loss_m"),
            "avg_hr_bpm": yaml_data.get("avg_hr_bpm"),
            "max_hr_bpm": yaml_data.get("max_hr_bpm"),
            "recovery_hr_bpm": yaml_data.get("recovery_hr_bpm"),
            "training_effect_aerobic": yaml_data.get("training_effect"),
            "calories_kcal": yaml_data.get("calories"),
        }))
    lieu = re.search(r"\*\*Lieu\s*:\*\*\s*(.+)", text)
    if lieu:
        out["location"] = lieu.group(1).strip()
    name = re.search(r"\*\*Activité Garmin\s*:\*\*\s*.*?`([^`]+)`", text)
    if name and "name" not in out:
        out["name"] = name.group(1)

    # Puces : ne complètent que ce que le YAML n'a pas donné.
    fill = {
        "distance_m": parse_fr_distance_m(_pick(bullets, "distance")),
        "duration_s": parse_fr_duration(_pick(bullets, "duree", "temps")),
        "elevation_gain_m": parse_fr_number(_pick(bullets, "d+", "denivele positif", "denivele")),
        "elevation_loss_m": parse_fr_number(_pick(bullets, "d-", "denivele negatif")),
        "avg_hr_bpm": parse_fr_number(_pick(bullets, "fc moyenne", "fc moy")),
        "max_hr_bpm": parse_fr_number(_pick(bullets, "fc max", "fc maximale")),
        "recovery_hr_bpm": parse_fr_number(_pick(bullets, "hrr", "fc de recuperation")),
        "calories_kcal": parse_fr_number(_pick(bullets, "calories")),
        "location": _pick(bullets, "lieu"),
    }
    for key, value in fill.items():
        if out.get(key) is None and value is not None:
            out[key] = value
    for key in ("avg_hr_bpm", "max_hr_bpm", "recovery_hr_bpm", "garmin_activity_id"):
        if isinstance(out.get(key), float):
            out[key] = _int(out[key])

    if table:
        out["splits_cols"] = ["km", "duration_s", "elev_gain_m", "elev_loss_m", "avg_hr_bpm"]
        out["splits"] = [
            [s["num"], s["duration_s"], s["dplus_m"], s["dminus_m"],
             _int(s["hr_avg_bpm"]) if s["hr_avg_bpm"] is not None else None]
            for s in table
        ]
        if out.get("duration_s") is None:
            out["duration_s"] = float(sum(s["duration_s"] for s in table))
    if "name" not in out:
        title = title_of(text)
        if title:
            out["name"] = title
    return out


_HRV_STATUS = {
    "equilibre": "balanced", "balanced": "balanced",
    "desequilibre": "unbalanced", "unbalanced": "unbalanced",
    "bas": "low", "low": "low", "faible": "poor", "poor": "poor",
}


def legacy_health(text: str, filename: str, morning_check: str = "full") -> Dict[str, Any]:
    bullets = parse_bullets(text)
    out: Dict[str, Any] = {
        "arc": 0, "kind": "health", "date": filename_date(filename), "morning_check": morning_check,
    }
    sleep = _pick(bullets, "sommeil", "duree de sommeil")
    if sleep:
        out["sleep_total_s"] = parse_fr_duration(sleep)
        score = re.search(r"score\s*:?\s*(\d+)", sleep, re.I)
        if score:
            out["sleep_score"] = int(score.group(1))
    score = _pick(bullets, "score de sommeil", "score sommeil")
    if score:
        out["sleep_score"] = _int(parse_fr_number(score))
    hrv = _pick(bullets, "hrv nocturne", "hrv", "vfc")
    if hrv:
        out["hrv_overnight_ms"] = parse_fr_number(hrv)
        status = normalize_label(hrv)
        for word, value in _HRV_STATUS.items():
            if re.search(r"\b" + word + r"\b", status):
                out["hrv_status"] = value
                break
    fields = {
        "resting_hr_bpm": ("fc de repos", "fc repos"),
        "readiness_score": ("readiness", "training readiness", "disponibilite"),
        "body_battery_high": ("body battery",),
        "stress_avg": ("stress",),
        "weight_kg": ("poids",),
    }
    for key, labels in fields.items():
        value = parse_fr_number(_pick(bullets, *labels))
        if value is not None:
            out[key] = value if key == "weight_kg" else _int(value)
    return _drop_none(out)


_EMOJI_CATEGORY = {"🟢": "green", "🟡": "yellow", "🟠": "orange", "🔴": "red"}
_EMOJI_SLOT = {"🌅": "morning", "☀️": "midday", "☀": "midday", "🌇": "evening"}


def legacy_weather(text: str, filename: str) -> Dict[str, Any]:
    """Format du skill weather-forecast (skills/weather-forecast/SKILL.md)."""
    bullets = parse_bullets(text)
    out: Dict[str, Any] = {"arc": 0, "kind": "weather", "date": filename_date(filename)}
    title = title_of(text) or ""
    parts = [p.strip() for p in re.split(r"\s+[—-]\s+", title)]
    if len(parts) >= 2 and parts[0].lower().startswith("m"):
        out["location"] = parts[1]
    temp = _pick(bullets, "temperature")
    if temp:
        lo = re.search(r"min\s*(-?\d+(?:[.,]\d+)?)", temp)
        hi = re.search(r"max\s*(-?\d+(?:[.,]\d+)?)", temp)
        feels = re.search(r"ressenti\s*(-?\d+(?:[.,]\d+)?)", temp)
        for key, match in (("temp_min_c", lo), ("temp_max_c", hi), ("feels_like_c", feels)):
            if match:
                out[key] = float(match.group(1).replace(",", "."))
    wind = _pick(bullets, "vent")
    if wind:
        out["wind_kmh"] = parse_fr_number(wind)
        gust = re.search(r"rafales\s*(\d+(?:[.,]\d+)?)", wind)
        if gust:
            out["gust_kmh"] = float(gust.group(1).replace(",", "."))
    rain = _pick(bullets, "pluie")
    if rain:
        out["precip_mm"] = parse_fr_number(rain)
        chance = re.search(r"\((\d+)\s*%\)", rain)
        if chance:
            out["chance_of_rain_pct"] = int(chance.group(1))
    uv = parse_fr_number(_pick(bullets, "uv"))
    if uv is not None:
        out["uv_index"] = uv
    humidity = parse_fr_number(_pick(bullets, "humidite"))
    if humidity is not None:
        out["humidity_pct"] = humidity
    section = re.search(r"##\s*Catégorie\s*\n(.*?)(?:\n##|\Z)", text, re.S)
    for emoji, value in _EMOJI_CATEGORY.items():
        if section and emoji in section.group(1):
            out["category"] = value
            break
    section = re.search(r"##\s*Créneau[^\n]*\n(.*?)(?:\n##|\Z)", text, re.S)
    if section:
        for emoji, value in _EMOJI_SLOT.items():
            if emoji in section.group(1):
                out["best_slot"] = value
                break
    return _drop_none(out)


_DAYS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]


def _guess_session_sport(title: str, default: str) -> str:
    t = normalize_label(title)
    if re.search(r"renfo|muscu|force|gainage", t):
        return "strength"
    if re.search(r"home trainer|velo d.appartement|zwift", t):
        return "home_trainer"
    if re.search(r"\bvelo\b|cyclisme", t):
        return "cycling"
    if re.search(r"natation|piscine", t):
        return "swimming"
    if re.search(r"repos", t):
        return "rest"
    return default


def legacy_week(text: str, filename: str, default_sport: str = "trail") -> Dict[str, Any]:
    """`planning/Semaine_AAAA-MM-JJ.md` : tableau Jour | Séance | Réalisée."""
    match = re.search(r"(\d{4}-\d{2}-\d{2})", filename)
    start = match.group(1) if match else None
    bullets = parse_bullets(text)
    out: Dict[str, Any] = {"arc": 0, "kind": "week", "week_start": start}
    location = _pick(bullets, "lieu d'entrainement", "lieu")
    if location:
        out["location"] = location
    sessions = []
    try:
        monday = date.fromisoformat(start) if start else None
    except ValueError:
        monday = None
    for line in text.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")] if line.strip().startswith("|") else []
        if len(cells) < 2:
            continue
        day = normalize_label(cells[0])
        if day not in _DAYS or monday is None:
            continue
        title = cells[1].replace("*", "").strip()
        session: Dict[str, Any] = {
            "date": (monday + timedelta(days=_DAYS.index(day))).isoformat(),
            "sport": _guess_session_sport(title, default_sport),
            "title": title,
        }
        km = re.search(r"(\d+(?:[.,]\d+)?)\s*km", title)
        if km:
            session["planned_distance_m"] = float(km.group(1).replace(",", ".")) * 1000
        dplus = re.search(r"(\d[\d   ]*)\s*m\s*D\+", title)
        if dplus:
            session["planned_elevation_m"] = parse_fr_number(dplus.group(1))
        duration = re.search(r"(\d+)\s*min", title)
        if duration:
            session["planned_duration_s"] = int(duration.group(1)) * 60
        if len(cells) >= 3:
            done = normalize_label(cells[2])
            if done in ("oui", "yes", "fait", "faite", "ok", "x", "✅"):
                session["status"] = "done"
            elif done in ("non", "no", "manquee", "ratee", "❌"):
                session["status"] = "missed"
        sessions.append(session)
    out["sessions"] = sessions
    return _drop_none(out)


def legacy_nutrition(text: str, filename: str) -> Dict[str, Any]:
    bullets = parse_bullets(text)
    fields = {
        "intake_kcal": ("calories ingerees", "apports", "calories"),
        "carbs_g": ("glucides",),
        "protein_g": ("proteines",),
        "fat_g": ("lipides",),
        "hydration_ml": ("hydratation",),
        "burned_kcal": ("calories brulees", "depense"),
        "weight_kg": ("poids",),
    }
    out: Dict[str, Any] = {"arc": 0, "kind": "nutrition", "date": filename_date(filename)}
    for key, labels in fields.items():
        value = parse_fr_number(_pick(bullets, *labels))
        if value is not None:
            out[key] = value
    if "hydration_ml" in out:
        raw = _pick(bullets, "hydratation") or ""
        if re.search(r"\d\s*l\b", raw.lower()) and out["hydration_ml"] < 20:
            out["hydration_ml"] *= 1000
    return out


def legacy_report(text: str, filename: str) -> Dict[str, Any]:
    kind = "comparison" if "_comparaison" in filename else "weekly"
    return _drop_none({
        "arc": 0, "kind": "report", "date": filename_date(filename),
        "report_type": kind, "title": title_of(text) or filename,
    })


# ---------------------------------------------------------------------------
# Fichiers édités par l'humain : profil et objectif (libellés du modèle)
# ---------------------------------------------------------------------------

def parse_profile(text: str) -> Dict[str, Any]:
    """`planning/Runner_Profile.md` → champs utiles aux calculs (SI)."""
    b = parse_bullets(text)
    sex = normalize_label(_pick(b, "sexe") or "")
    out = {
        "hr_max_bpm": _int(parse_fr_number(_pick(b, "fc max"))),
        "hr_rest_bpm": _int(parse_fr_number(_pick(b, "fc de repos de reference", "fc de repos"))),
        "hr_threshold_bpm": _int(parse_fr_number(_pick(b, "fc au seuil", "fc seuil"))),
        "sex": "female" if re.match(r"^(f|femme|female)\b", sex) else ("male" if re.match(r"^(h|m|homme|male)\b", sex) else None),
        "weight_kg": parse_fr_number(_pick(b, "poids de forme", "poids")),
        "birth_year": _int(parse_fr_number(_pick(b, "annee de naissance"))),
        "default_location": _pick(b, "lieu par defaut"),
        "usual_slot": _pick(b, "creneau habituel"),
        "name": _pick(b, "prenom / surnom", "prenom"),
    }
    return _drop_none(out)


def parse_objective(text: str) -> Dict[str, Any]:
    """`planning/active_objective.md` → objectif courant (SI)."""
    b = parse_bullets(text)
    volume_start, volume_target = _pick(b, "volume hebdomadaire de depart"), _pick(b, "volume hebdomadaire cible")

    def volume(raw):
        if raw is None:
            return None, None
        if re.search(r"\d\s*h\b|\d\s*h\s*\d", raw.lower()):
            return parse_fr_duration(raw), None
        return None, parse_fr_distance_m(raw)

    start_s, start_m = volume(volume_start)
    target_s, target_m = volume(volume_target)
    out = {
        # Libellés du modèle d'abord, puis ceux des objectifs écrits avant lui (tableaux).
        "name": _pick(b, "nom", "course"),
        "race_date": parse_fr_date(_pick(b, "date")),
        "distance_m": parse_fr_distance_m(_pick(b, "distance")),
        "elevation_gain_m": parse_fr_number(_pick(b, "denivele positif", "denivele +", "d+")),
        "location": _pick(b, "lieu course", "lieu de course", "lieu"),
        "goal": _pick(b, "objectif principal", "priorite"),
        "target_time_s": parse_fr_duration(_pick(b, "temps vise")),
        "weekly_start_s": start_s, "weekly_start_m": start_m,
        "weekly_target_s": target_s, "weekly_target_m": target_m,
        "quality_per_week": _int(parse_fr_number(_pick(b, "seances qualite par semaine"))),
        "training_location": _pick(b, "lieu d'entrainement par defaut"),
    }
    return _drop_none(out)
