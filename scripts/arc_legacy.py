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
from typing import Any, Dict, List, Optional, Tuple

from arc_contract import gear_slug

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


# Conversion livre -> kg (revue de code) : `[athlete].units = "imperial"`
# n'empêche pas l'athlète d'écrire son poids en livres dans un libellé de puce
# (profil, ou une vieille fiche santé/nutrition au format bullets hérité) —
# 1 lb = 0.45359237 kg EXACT (définition internationale de la livre avoirdupois,
# 1959), jamais une valeur arrondie approximative.
LB_TO_KG = 0.45359237


def parse_weight_kg(text: Optional[str]) -> Optional[float]:
    """Poids en kg depuis un libellé de puce libre (`_pick`) — profil
    (`parse_profile`) ou fiche santé/nutrition au format bullets hérité
    (`legacy_health`/`legacy_nutrition`) : SEULE fonction du module qui convertit
    un poids, pour que les trois appelants restent d'accord (revue de code).
    Détection par le TEXTE du libellé lui-même (« lb »/« lbs », insensible à la
    casse, limite de mot pour ne jamais confondre avec un autre mot commençant
    par ces lettres) — PAS par `[athlete].units` (ce module n'a pas accès à la
    config du workspace, et une puce reste ce qu'elle dit, quelle que soit la
    config) : un poids annoté « kg » ou sans unité explicite reste interprété tel
    quel, jamais deviné depuis `[athlete].units` seul. Sans cette conversion, un
    poids en livres serait silencieusement traité comme des kg (154 lb -> "154",
    lu comme 154 kg au lieu de ~70 kg) — une confusion qui fausserait TOUT calcul
    dérivé du poids, dont la dépense énergétique modèle
    (`arc_index.resolve_weight_kg_as_of`)."""
    value = parse_fr_number(text)
    if value is None:
        return None
    # Seule l'unité qui suit le PREMIER nombre compte : « 72 kg (159 lb) » ou
    # « 72 kg — objectif 150 lbs » restent 72 kg (revue de code, faux positifs).
    first = re.search(r"(\d+(?:[.,]\d+)?)\s*(kg|lbs?)?\b", str(text), re.IGNORECASE)
    if first and first.group(2) and first.group(2).lower().startswith("lb"):
        return round(value * LB_TO_KG, 2)
    return value


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


# Plage plausible pour un besoin de sommeil humain déclaré : au-delà, c'est une
# faute de saisie (« 25 h »), jamais une valeur à retenir telle quelle.
SLEEP_NEED_PLAUSIBLE_H = (4.0, 12.0)

_SLEEP_NEED_DECIMAL_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*h(?!\s*\d)")           # « 7.5 h », « 7,5 h »
_SLEEP_NEED_HM_RE = re.compile(r"(\d+)\s*h\s*(\d{1,2})\b")                       # « 7h30 », « 7 h 30 »
_SLEEP_NEED_COLON_RE = re.compile(r"\b(\d{1,2}):(\d{2})\b")                      # « 7:30 » = 7 h 30, PAS 7 min 30
_SLEEP_NEED_MIN_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*(?:min|mn)\b")             # « 450 min »
_SLEEP_NEED_BARE_RE = re.compile(r"^(\d+(?:[.,]\d+)?)$")                        # « 8 » nu, en heures


def _parse_sleep_need_s(text) -> Optional[float]:
    """Besoin de sommeil (« Besoin de sommeil » du profil) → secondes.

    Format DÉDIÉ, distinct de `parse_fr_duration` : ce dernier lit « 7:30 » comme
    m:ss (450 s, pas 7 h 30) et n'a pas de notation décimale d'heures, deux
    contresens silencieux sur ce champ précis (revue de code, PR #82) — une durée
    de séance et un besoin de sommeil ne s'écrivent pas avec la même ambiguïté
    tolérable. Ordre d'essai, le premier qui matche gagne :

    1. décimale d'heures — « 7.5 h », « 7,5 h » — testée AVANT « Hh MM » via une
       négation `(?!\\s*\\d)` après le « h » (sans elle, « 7.5 h » matcherait comme
       Hh MM avec `h=7`, perdant le « .5 » : 7.5 h deviendrait 5 h) ;
    2. « 7h30 », « 7 h 30 » (heures-minutes) ;
    3. « 7:30 » — interprété ICI comme HEURES:MINUTES (7 h 30), jamais
       minutes:secondes : un besoin de sommeil de 7 minutes n'aurait aucun sens ;
    4. « 450 min », « 450 mn » ;
    5. un nombre nu — « 8 » — interprété en heures.

    Rend `None` si rien ne matche, ou si le résultat sort de `SLEEP_NEED_PLAUSIBLE_H`
    (ex. « 25 h », faute de saisie) : l'appelant applique alors son propre défaut
    (7 h 30, `arc_metrics.SLEEP_NEED_DEFAULT_S`) plutôt qu'une valeur bruitée.
    """
    if text is None:
        return None
    t = str(text).replace("*", "").strip().lower()
    for space in _SPACES:
        t = t.replace(space, " ")
    seconds = None
    m = _SLEEP_NEED_DECIMAL_RE.search(t)
    if m:
        seconds = float(m.group(1).replace(",", ".")) * 3600
    else:
        m = _SLEEP_NEED_HM_RE.search(t)
        if m:
            seconds = int(m.group(1)) * 3600 + int(m.group(2)) * 60
        else:
            m = _SLEEP_NEED_COLON_RE.search(t)
            if m:
                seconds = int(m.group(1)) * 3600 + int(m.group(2)) * 60
            else:
                m = _SLEEP_NEED_MIN_RE.search(t)
                if m:
                    seconds = float(m.group(1).replace(",", ".")) * 60
                else:
                    m = _SLEEP_NEED_BARE_RE.match(t)
                    if m:
                        seconds = float(m.group(1).replace(",", ".")) * 3600
    if seconds is None:
        return None
    lo_h, hi_h = SLEEP_NEED_PLAUSIBLE_H
    return seconds if lo_h * 3600 <= seconds <= hi_h * 3600 else None


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
    """Date → AAAA-MM-JJ. ISO, « 13/06/2026 », « 13 juin 2026 » — ou, sans jour
    précis (revue PR #85 : la puce « depuis » du profil #40 s'en sert plus
    lourdement depuis que la date filtre l'attribution par défaut), « 03/2026 »
    ou « mars 2026 » → 1er du mois. Les motifs à jour complet sont essayés EN
    PREMIER (`candidates` est ordonné, la boucle rend le premier qui construit
    une date valide) : un texte « 13/06/2026 » ne doit jamais se résoudre au
    1er juin faute d'avoir laissé le motif mois/année le doubler."""
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
    match = re.search(r"\b(\d{1,2})/(\d{4})\b", t)
    if match:
        candidates.append((int(match.group(2)), int(match.group(1)), 1))
    match = re.search(r"\b([a-zéûô]+)\s+(\d{4})\b", t)
    if match and match.group(1) in _MONTHS:
        candidates.append((int(match.group(2)), _MONTHS[match.group(1)], 1))
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
        raw = _pick(bullets, *labels)
        # `weight_kg` : conversion livre -> kg éventuelle (`parse_weight_kg`) —
        # les autres champs numériques n'ont pas d'unité ambiguë ici,
        # `parse_fr_number` seul suffit.
        value = parse_weight_kg(raw) if key == "weight_kg" else parse_fr_number(raw)
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
        raw = _pick(bullets, *labels)
        # `weight_kg` : conversion livre -> kg éventuelle (`parse_weight_kg`) —
        # les autres champs numériques n'ont pas d'unité ambiguë ici
        # (hydratation gérée à part ci-dessous), `parse_fr_number` seul suffit.
        value = parse_weight_kg(raw) if key == "weight_kg" else parse_fr_number(raw)
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
# Section « Matériel » : chaussures (#40)
# ---------------------------------------------------------------------------

# Une puce de la sous-section « Chaussures » n'est PAS un « Libellé : valeur »
# (`parse_bullets` ne s'applique pas) : c'est une description en langage libre,
# nom d'abord, puis des segments optionnels séparés par un tiret cadratin/demi-
# cadratin (« — »/« – », espaces optionnels — « 5—alerte » colle sans espace),
# par un simple tiret ENTOURÉ D'ESPACES (« - ») UNIQUEMENT quand ce qui suit est
# un mot-clé reconnu, ou par un deux-points dans le même cas (« Hoka Speedgoat
# 5: depuis 2026-03-01 » — le « : » de « id: » lui-même n'est PAS un séparateur,
# voir `_GEAR_SEGMENT_SPLIT_RE`). Un simple tiret NON suivi d'un mot-clé reste
# dans le nom : un modèle peut légitimement en contenir un, SANS espaces
# (« Salomon S/Lab Ultra-Trail ») ou AVEC (« Brooks Cascadia 17 - GTX », suffixe
# de variante ; « Salomon S/Lab Ultra - 3 » ; revue PR #85, round 2) — sans le
# garde-fou du mot-clé, ces deux exemples se tronqueraient en « Brooks Cascadia
# 17 »/« Salomon S/Lab Ultra », un `gear_id` faux qui peut même collider avec un
# autre modèle réellement homonyme (fausse alerte de collision, voir
# `parse_gear`).
# Format documenté dans `templates/Runner_Profile.template.md` :
#   - Hoka Speedgoat 5 (bleues) — depuis 2026-03-01 — alerte 700 km — id: speedgoat-bleues (par défaut)
#   - Nike Pegasus — départ 300 km (retirée)
# Tout est facultatif sauf le nom. `(par défaut)`/`(retirée)` peuvent être
# accolés n'importe où sur la ligne (avant ou après les segments « — »).
_GEAR_HEADING_RE = re.compile(r"^\s{0,3}#{2,4}\s*chaussures\s*$", re.I | re.M)
_GEAR_NEXT_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s", re.M)
# Puce de PREMIER niveau (aucune indentation) seulement — une puce indentée est une
# sous-puce d'une chaussure précédente (revue #85 blocker 4 : « - alerte 800 km »
# indenté sous une chaussure ne doit jamais devenir sa propre chaussure fantôme) et
# est repliée dans les segments de la chaussure en cours, voir `parse_gear`.
_GEAR_TOP_BULLET_RE = re.compile(r"^[-*]\s+(.+)$")
_GEAR_SUB_BULLET_RE = re.compile(r"^\s+[-*]\s+(.+)$")
_GEAR_SEGMENT_SPLIT_RE = re.compile(
    r"\s+-\s+(?=depuis\b|alerte\b|d[ée]part\b|usage\s*:|id\s*:|garmin\s*:)|\s*[—–]\s*|"
    r"\s*:\s*(?=depuis\b|alerte\b|d[ée]part\b|usage\s*:|id\s*:|garmin\s*:)", re.I)
# Segment « garmin: <uuid> » (#133) : identifiant OPAQUE du matériel côté Garmin Connect,
# recopié tel quel de `get_gear` (champ `uuid`). Aucun format Garmin n'est garanti par
# le serveur MCP — on accepte donc un jeton alphanumérique/tirets de 8 à 64 caractères,
# comparé sans casse ; toute autre forme est du texte libre ignoré (clé omise).
_GEAR_GARMIN_UUID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]{7,63}$")
GEAR_GARMIN_UUID_RE = _GEAR_GARMIN_UUID_RE   # public : validé aussi par `arc_index.py gear-attribution`
# `(ignorée)` (#133) : matériel Garmin volontairement NON suivi — la puce ne porte que son
# `garmin: <uuid>` ; plus jamais reproposé ni signalé « non associé », mais jamais crédité non plus
# à la paire par défaut (`gear_source: "garmin_unmapped"`).
_GEAR_IGNORED_RE = re.compile(r"\(\s*ignor[ée]e?\s*\)", re.I)
_GEAR_DEFAULT_RE = re.compile(r"\(\s*par\s*d[ée]faut\s*\)", re.I)
_GEAR_RETIRED_RE = re.compile(r"\(\s*retir[ée]e?\s*\)", re.I)
# « 186mi » (unité collée au nombre) compte : seul un préfixe alphabétique (« min ») l'exclut.
_GEAR_MILES_RE = re.compile(r"(?<![a-z])mi(?:les?)?\b", re.I)
# Segment « départ » : UNIQUEMENT « [~] <nombre> [km|mi|mile(s)] » — toute autre forme
# (« départ usine 2025 », « départ en rotation le 12/03 ») reste du texte libre ignoré.
# Séparateur de milliers = espace ; un point ou une virgule est TOUJOURS décimal
# (« 1.200 km » = 1,2 km, jamais 1 200 km).
_GEAR_START_VALUE_RE = re.compile(
    r"^~?\s*(\d+(?:[ \u00a0\u202f]\d{3})*(?:[.,]\d+)?)\s*(km|mi(?:les?)?)?\s*$", re.I)


def _gear_section(text: str, heading_re: Optional["re.Pattern"] = None) -> Optional[str]:
    """Texte de la sous-section « ### Chaussures » (n'importe quel niveau de
    titre entre `##` et `####`), jusqu'au prochain titre ou la fin du fichier.
    `None` si la section est absente (rien à lire, pas une erreur : la plupart
    des profils n'ont pas encore de chaussures déclarées). Les commentaires
    HTML sont retirés avant la recherche du titre — même règle que
    `parse_bullets` — pour que l'exemple commenté du modèle
    (`templates/Runner_Profile.template.md`) ne soit jamais lu comme une
    chaussure réellement déclarée."""
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    m = (heading_re or _GEAR_HEADING_RE).search(text)
    if not m:
        return None
    rest = text[m.end():]
    nxt = _GEAR_NEXT_HEADING_RE.search(rest)
    return rest[: nxt.start()] if nxt else rest


def _gear_bullets(section: str) -> List[str]:
    """Une chaîne brute par chaussure : la puce de premier niveau, avec toute
    puce indentée qui la suit repliée dedans comme un segment supplémentaire
    (revue #85 blocker 4). Une puce indentée AVANT la première puce de premier
    niveau est ignorée (rien à quoi la rattacher)."""
    raws: List[str] = []
    current: Optional[str] = None
    for line in section.splitlines():
        top = _GEAR_TOP_BULLET_RE.match(line)
        if top:
            if current is not None:
                raws.append(current)
            current = top.group(1).strip()
            continue
        sub = _GEAR_SUB_BULLET_RE.match(line)
        if sub and current is not None:
            current = f"{current} — {sub.group(1).strip()}"
    if current is not None:
        raws.append(current)
    return raws


def _gear_segment_kind(segment: str) -> Tuple[Optional[str], str]:
    """(type, valeur brute) d'un segment « — xxx » : `start_date`/`threshold`/
    `start_mileage` (« départ N km », #132)/`usage`/`id`/`garmin` (#133), ou `(None, segment)` pour un segment non reconnu (ignoré silencieusement
    — un athlète peut vouloir noter autre chose, ex. « — usure semelle visible »).

    Ancrés sur le DÉBUT du segment avec limite de mot (`\\b`) : revue #85 blocker 3
    — un `startswith` nu prenait « idéale » ou « idem » pour le mot-clé `id`
    (segment amputé, `gear_id` faux dérivé de sa propre fin de phrase)."""
    stripped = segment.strip()
    m = re.match(r"depuis\b\s*:?\s*(.*)$", stripped, re.I)
    if m:
        return "start_date", m.group(1).strip()
    m = re.match(r"alerte\b\s*:?\s*(.*)$", stripped, re.I)
    if m:
        return "threshold", m.group(1).strip()
    m = re.match(r"d[ée]part\b\s*:?\s*(.*)$", stripped, re.I)
    if m:
        return "start_mileage", m.group(1).strip()
    m = re.match(r"usage\s*:\s*(.*)$", stripped, re.I)
    if m:
        return "usage", m.group(1).strip()
    m = re.match(r"id\s*:\s*(.*)$", stripped, re.I)
    if m:
        return "id", m.group(1).strip()
    m = re.match(r"garmin\s*:\s*(.*)$", stripped, re.I)
    if m:
        return "garmin", m.group(1).strip()
    return None, stripped


def parse_gear(text: str) -> List[Dict[str, Any]]:
    """Sous-section « Chaussures » du profil (`## Matériel & lieux` → `### Chaussures`)
    → liste de dicts `{gear_id, name, start_date, threshold_m, default, retired,
    start_m, usage, garmin_uuid, collision_base}` (clés absentes plutôt que `None` — voir `_drop_none`).

    `gear_id` : l'identifiant explicite (`id: …`) passé par `arc_contract.gear_slug`
    pour rester au format slug (même si l'athlète l'a déjà écrit en minuscules avec
    tirets, c'est idempotent), sinon dérivé du nom — RÈGLE PARTAGÉE avec #39 et le
    coach (voir `arc_contract.gear_slug`, `skills/workspace-data-contract/SKILL.md`).
    Une puce dont ni le nom ni l'id explicite ne contiennent de caractère
    alphanumérique (slug vide) est ignorée : rien de fiable à recouper avec les
    `gear_id` d'activité.

    Deux puces qui dérivent le MÊME slug (rachat du même modèle sans `id:` pour les
    distinguer — revue #85 blocker 2) ne s'écrasent plus l'une l'autre : la
    première garde le slug nu, chaque suivante reçoit `-2`, `-3`… et porte
    `collision_base` (le slug d'origine) — `arc_metrics.gear_mileage` s'en sert
    pour signaler la collision plutôt que de la laisser invisible (une paire
    active qui « disparaît » derrière une plus ancienne, ou l'inverse).

    `threshold_m` : le nombre du segment « alerte » est en km, SAUF si l'unité
    « mi »/« mile »/« miles » apparaît (alors × 1609,344 — revue #85 blocker 6) ;
    aucune autre unité n'est reconnue.

    `start_m` (#132) : segment « départ N km » (ou « N mi »/« miles », × 1609,344) — le
    kilométrage déjà parcouru AVANT le suivi (paire d'occasion, usage antérieur à
    l'installation), ajouté au cumul par `arc_metrics.gear_mileage` ; 0 est une valeur
    valide (« départ 0 km »). Seule la forme « [~]N [km|mi] » est acceptée : toute autre
    (« départ usine 2025 », valeur négative ou illisible) est du texte libre ignoré (clé
    omise). Un point/une virgule est toujours décimal (« 1.200 km » = 1,2 km).
    `usage` (#132, facultatif) : rôle libre en minuscules (« usage: course », « trail »,
    « route », « récup ») — lu par le coach pour suggérer une paire, jamais par un KPI.

    `garmin_uuid` (#133, facultatif) : segment « garmin: <uuid> » — identifiant du matériel
    côté Garmin Connect (`get_gear` → `uuid`), en minuscules ; sert à rattacher le matériel
    attaché par la montre à une activité (`get_activity_gear`) à cette puce, jamais deviné.
    `garmin_uuid_invalid` : `True` si un segment `garmin:` est présent mais illisible (jamais indexé,
    lu par `coach_doctor`). `ignored` : `True` pour `(ignorée)` (matériel Garmin non suivi, voir plus haut).
    Un uuid partagé par deux puces n'est pas résolu ici (voir `arc_metrics.resolve_gear_attribution`).

    `(par défaut)` déclare la chaussure attribuée à une activité sans `gear_id`
    (voir `arc_metrics.gear_mileage`) ; `(retirée)`, une chaussure sortie de
    rotation (exclue des alertes, voir la même fonction). Les deux repères sont
    cherchés sur la ligne ENTIÈRE (n'importe quelle position), puis retirés avant
    de découper le reste en segments — sans quoi l'un d'eux traînerait dans le nom
    ou dans un segment mal reconnu."""
    section = _gear_section(text)
    if not section:
        return []
    out: List[Dict[str, Any]] = []
    seen: Dict[str, int] = {}
    for raw in _gear_bullets(section):
        raw = raw.replace("**", "").strip()   # gras markdown : jamais significatif ici (comme `parse_bullets`)
        is_default = bool(_GEAR_DEFAULT_RE.search(raw))
        is_retired = bool(_GEAR_RETIRED_RE.search(raw))
        is_ignored = bool(_GEAR_IGNORED_RE.search(raw))
        raw = _GEAR_IGNORED_RE.sub("", _GEAR_RETIRED_RE.sub("", _GEAR_DEFAULT_RE.sub("", raw))).strip()
        segments = [s for s in _GEAR_SEGMENT_SPLIT_RE.split(raw) if s.strip()]
        if not segments:
            continue
        name = segments[0].strip()
        explicit_id = None
        start_date = None
        threshold_m = None
        start_m = None
        usage = None
        garmin_uuid = None
        garmin_invalid = False
        for segment in segments[1:]:
            kind, value = _gear_segment_kind(segment)
            if kind == "start_date":
                start_date = parse_fr_date(value)
            elif kind == "threshold":
                number = parse_fr_number(value)
                if number is not None:
                    factor = 1609.344 if _GEAR_MILES_RE.search(value) else 1000.0
                    threshold_m = round(number * factor)
            elif kind == "start_mileage":
                m_start = _GEAR_START_VALUE_RE.match(value.strip())
                if m_start:
                    number = parse_fr_number(m_start.group(1))
                    unit = (m_start.group(2) or "").lower()
                    factor = 1609.344 if unit.startswith("mi") else 1000.0
                    start_m = round(number * factor)
            elif kind == "usage":
                usage = value.strip().lower() or None
            elif kind == "id":
                explicit_id = value.strip() or None
            elif kind == "garmin":
                if _GEAR_GARMIN_UUID_RE.match(value.strip()):
                    garmin_uuid = value.strip().lower()
                else:
                    garmin_invalid = True   # segment présent mais illisible (signalé par le doctor)
        base_id = gear_slug(explicit_id) if explicit_id else gear_slug(name)
        if not base_id:
            continue
        seen[base_id] = seen.get(base_id, 0) + 1
        n = seen[base_id]
        gear_id = base_id if n == 1 else f"{base_id}-{n}"
        entry = {
            "gear_id": gear_id, "name": name or None, "start_date": start_date,
            "threshold_m": threshold_m, "default": is_default or None, "retired": is_retired or None,
            "start_m": start_m, "usage": usage, "garmin_uuid": garmin_uuid,
            "garmin_uuid_invalid": garmin_invalid or None, "ignored": is_ignored or None,
        }
        if n > 1:
            entry["collision_base"] = base_id
        out.append(_drop_none(entry))
    return out


# ---------------------------------------------------------------------------
# Matériel hors chaussures (#134) : sous-section « ### Matériel » du profil
# (`## Matériel & lieux` → `### Matériel`), même principe libre que « Chaussures »
# (une puce de premier niveau par objet, segments séparés par « — »).
#   - Poche à eau 2 L — catégorie: poche — depuis 2026-03-01 — alerte 30 jours — kit: trail-long
#   - Frontale Petzl — catégorie: frontale — alerte 100 h — id: frontale-nuit
#   - Bâtons Leki — catégorie: bâtons — alerte 800 km — kit: trail-long
# Déclencheurs typés (`alerte`) : « N km » | « N h » | « N séances » | « N jours »,
# combinables (le premier atteint déclenche) — voir `arc_metrics.equipment_usage`.
# La catégorie n'est lue QUE du segment « catégorie: … » : jamais devinée du nom.
# `### Chaussures` n'est pas touchée : elle garde son propre analyseur (`parse_gear`).
# ---------------------------------------------------------------------------
_EQUIP_HEADING_RE = re.compile(r"^\s{0,3}#{3,4}\s*mat[ée]riel\s*$", re.I | re.M)
_EQUIP_KEYWORDS = (r"depuis\b|alerte\b|d[ée]part\b|id\s*:|cat[ée]gorie\s*:|kit\s*:|entretien\b|"
                   r"r[ée]vis[ée]e?\b")
_EQUIP_SEGMENT_SPLIT_RE = re.compile(
    rf"\s+-\s+(?={_EQUIP_KEYWORDS})|\s*[—–]\s*|\s*:\s*(?={_EQUIP_KEYWORDS})", re.I)
# « <nombre> <unité> » : seule une unité explicite compte pour le matériel (jamais un nombre nu,
# contrairement aux chaussures où « alerte 700 » vaut 700 km — ici l'unité décide du type de
# déclencheur, la deviner serait inventer une alerte). Durées calendaires : semaine = 7 jours,
# mois = 30 jours, an = 365 jours (approximation du projet, voir `arc_metrics.ASSUMPTIONS`).
# « 1h30 »/« 2 h 30 » (heures + minutes) est lu avant, par `_EQUIP_HM_RE`.
_EQUIP_TRIGGER_RE = re.compile(
    r"(\d+(?:[   ]\d{3})*(?:[.,]\d+)?)\s*"
    r"(km|mi(?:les?)?|h|heures?|s[ée]ances?|sorties?|semaines?|mois|jours?|j|ans?)\b", re.I)
_EQUIP_HM_RE = re.compile(r"(\d+)\s*h\s*([0-5]\d)\b", re.I)
# Catégories reconnues (clé canonique → alias, sans accent, minuscules, singulier ou pluriel).
EQUIPMENT_CATEGORIES: Dict[str, Tuple[str, ...]] = {
    "batons": ("baton", "batons", "baton de trail", "batons de trail"),
    "gilet": ("gilet", "gilets", "sac d'hydratation", "gilet d'hydratation"),
    "poche": ("poche", "poches", "poche a eau", "poches a eau"),
    "flasques": ("flasque", "flasques", "softflask", "softflasks", "gourde", "gourdes"),
    "frontale": ("frontale", "frontales", "lampe frontale"),
    "ceinture": ("ceinture", "ceintures", "ceinture cardio", "ceinture fc"),
    "veste": ("veste", "vestes"),
    "semelles": ("semelle", "semelles"),
    "lacets": ("lacet", "lacets"),
    "autre": ("autre", "autres"),
}


def normalize_equipment_category(raw: Optional[str]) -> Optional[str]:
    """Valeur brute du segment « catégorie: … » → clé canonique (`EQUIPMENT_CATEGORIES`) ;
    une valeur non reconnue est gardée en slug (l'objet est indexé, `arc_metrics` la dit
    inconnue et n'invente aucune alerte) ; vide → `None`."""
    text = normalize_label(raw or "").strip()
    if not text:
        return None
    for key, aliases in EQUIPMENT_CATEGORIES.items():
        if text == key or text in aliases:
            return key
    return gear_slug(text) or None


def _equip_triggers(value: str) -> Dict[str, float]:
    """« 30 jours ou 40 h » → `{days: 30, duration_s: 144000}` (clés : distance_m, duration_s,
    sessions, days). « 1h30 » = 1,5 h ; semaines/mois/ans → jours (7/30/365). Un même type répété :
    le dernier gagne ; texte sans unité : ignoré (l'appelant avertit quand rien n'est lu)."""
    out: Dict[str, float] = {}
    for m in _EQUIP_HM_RE.finditer(value):
        out["duration_s"] = int(m.group(1)) * 3600 + int(m.group(2)) * 60
    value = _EQUIP_HM_RE.sub(" ", value)
    for m in _EQUIP_TRIGGER_RE.finditer(value):
        number = parse_fr_number(m.group(1))
        if number is None or number <= 0:
            continue
        unit = m.group(2).lower()
        if unit == "km":
            out["distance_m"] = round(number * 1000)
        elif unit.startswith("mi") and unit != "mois":
            out["distance_m"] = round(number * 1609.344)
        elif unit.startswith("h"):
            out["duration_s"] = round(number * 3600)
        elif unit.startswith(("séance", "seance", "sortie")):
            out["sessions"] = int(round(number))
        elif unit.startswith("semaine"):
            out["days"] = int(round(number * 7))
        elif unit == "mois":
            out["days"] = int(round(number * 30))
        elif unit.startswith("an"):
            out["days"] = int(round(number * 365))
        else:
            out["days"] = int(round(number))
    return out


def parse_equipment(text: str) -> List[Dict[str, Any]]:
    """Sous-section « Matériel » du profil → liste de dicts `{gear_id, name, category, start_date,
    maintenance_date, retired, kits, threshold_m, threshold_s, threshold_sessions, threshold_days,
    start_m, start_s, start_sessions, collision_base}` (clés absentes plutôt que `None`).

    Segments (tous facultatifs sauf le nom) : `depuis <date>`, `catégorie: <mot>`,
    `alerte <N km|N h|N séances|N jours>` (combinables : « alerte 30 jours ou 40 h », ou plusieurs
    segments `alerte`), `départ <N km|N h|N séances>` (usage antérieur au suivi — un départ en
    jours n'existe pas : les jours partent de `depuis`), `entretien <date>` / `révisé <date>`
    (dernier entretien — remet à zéro les compteurs, voir `arc_metrics.ASSUMPTIONS["equipment_usage"]`),
    `kit: <slug>[, <slug>…]`, `id: <identifiant>`, `(retirée)`. `id` et collisions : même règle que
    `parse_gear` (`arc_contract.gear_slug`, suffixe `-2`, `-3`…)."""
    section = _gear_section(text, _EQUIP_HEADING_RE)
    if not section:
        return []
    out: List[Dict[str, Any]] = []
    seen: Dict[str, int] = {}
    for raw in _gear_bullets(section):
        raw = raw.replace("**", "").strip()
        is_retired = bool(_GEAR_RETIRED_RE.search(raw))
        raw = _GEAR_RETIRED_RE.sub("", raw).strip()
        warns: List[str] = []
        if _GEAR_IGNORED_RE.search(raw):
            # `(ignorée)` (#133) est une notion de matériel Garmin des CHAUSSURES : sans effet ici.
            raw = _GEAR_IGNORED_RE.sub("", raw).strip()
            warns.append("« (ignorée) » n'existe que pour les chaussures — retiré de la puce ; le matériel "
                         "Garmin hors chaussures n'est pas rattaché (pas de segment `garmin:`).")
        segments = [s for s in _EQUIP_SEGMENT_SPLIT_RE.split(raw) if s.strip()]
        if not segments:
            continue
        name = segments[0].strip()
        explicit_id = None
        category = None
        start_date = None
        maintenance_date = None
        kits: List[str] = []
        thresholds: Dict[str, float] = {}
        starts: Dict[str, float] = {}
        for segment in segments[1:]:
            stripped = segment.strip()
            m = re.match(r"depuis\b\s*:?\s*(.*)$", stripped, re.I)
            if m:
                start_date = parse_fr_date(m.group(1).strip())
                continue
            m = re.match(r"alerte\b\s*:?\s*(.*)$", stripped, re.I)
            if m:
                got = _equip_triggers(m.group(1))
                if not got:
                    warns.append(f"segment « {stripped} » sans déclencheur lisible — ajoutez une unité "
                                 "(km, h, séances, jours, semaines, mois, ans) ; ignoré.")
                thresholds.update(got)
                continue
            m = re.match(r"d[ée]part\b\s*:?\s*(.*)$", stripped, re.I)
            if m:
                got = {k: v for k, v in _equip_triggers(m.group(1)).items() if k != "days"}
                if not got:
                    warns.append(f"segment « {stripped} » sans départ lisible — km, h ou séances (pas de "
                                 "départ en jours : les jours partent de `depuis`) ; ignoré.")
                starts.update(got)
                continue
            m = re.match(r"id\s*:\s*(.*)$", stripped, re.I)
            if m:
                explicit_id = m.group(1).strip() or None
                continue
            m = re.match(r"cat[ée]gorie\s*:\s*(.*)$", stripped, re.I)
            if m:
                category = normalize_equipment_category(m.group(1))
                continue
            m = re.match(r"kit\s*:\s*(.*)$", stripped, re.I)
            if m:
                for part in re.split(r"[,;/]", m.group(1)):
                    slug = gear_slug(part)
                    if slug and slug not in kits:
                        kits.append(slug)
                continue
            m = re.match(r"(?:entretien|r[ée]vis[ée]e?)\b\s*:?\s*(.*)$", stripped, re.I)
            if m:
                d = parse_fr_date(m.group(1).strip())
                if d and (maintenance_date is None or d > maintenance_date):
                    maintenance_date = d
        base_id = gear_slug(explicit_id) if explicit_id else gear_slug(name)
        if not base_id:
            continue
        seen[base_id] = seen.get(base_id, 0) + 1
        n = seen[base_id]
        gear_id = base_id if n == 1 else f"{base_id}-{n}"
        entry = {
            "gear_id": gear_id, "name": name or None, "category": category, "start_date": start_date,
            "maintenance_date": maintenance_date, "retired": is_retired or None, "kits": kits or None,
            "threshold_m": thresholds.get("distance_m"), "threshold_s": thresholds.get("duration_s"),
            "threshold_sessions": thresholds.get("sessions"), "threshold_days": thresholds.get("days"),
            "start_m": starts.get("distance_m"), "start_s": starts.get("duration_s"),
            "start_sessions": starts.get("sessions"), "parse_warnings": warns or None,
        }
        if n > 1:
            entry["collision_base"] = base_id
        out.append(_drop_none(entry))
    return out


# ---------------------------------------------------------------------------
# Indices de performance (#62) : ITRA / UTMB — sous-section « Historique des
# indices » du profil, une puce datée par relevé, sur le même principe que
# `parse_gear` (langage libre, pas des puces « Libellé : valeur »).
#
# Nomenclature UTMB (20K/50K/100K/100M) vérifiée ; celle des catégories ITRA
# n'a pas pu être confirmée depuis cet environnement — la catégorie ITRA reste
# donc du texte libre, jamais validée contre une liste fermée (voir
# `templates/Runner_Profile.template.md` et le PR #62).
#
# Migration (revue de code #62) : les puces sont acceptées aussi bien
# directement sous « ## Indices de performance (ITRA / UTMB) » que sous une
# sous-section « ### Historique des indices » — un profil installé AVANT ce
# sous-titre, ou un athlète qui a simplement collé ses relevés sous le titre
# principal, doit être lu tout pareil. `_index_section` capture donc tout le
# contenu de la section de NIVEAU du titre principal (jusqu'au prochain titre
# de niveau égal ou supérieur), sous-titre inclus, plutôt que d'ancrer
# spécifiquement sur le sous-titre.
# ---------------------------------------------------------------------------

# Exige ITRA ou UTMB sur la ligne de titre (revue de code #109, 2e tour) :
# sans cette contrainte, un titre sans rapport comme « #### Indice de
# performance VO2 » (VO2max, vue Performance du tableau de bord) matchait
# aussi, à cause du `.*$` permissif après « de performance ».
_INDEX_TOP_HEADING_RE = re.compile(r"^(#{2,4})\s*indices? de performance\b.*(itra|utmb).*$", re.I | re.M)
# Repli (revue de code #109, 3e tour) : un titre « nu », sans ITRA/UTMB — un
# athlète qui a renommé/simplifié le titre du modèle, ou une variante plus
# ancienne. Volontairement plus STRICT que le motif principal pour ne rien
# accepter à tort à sa place : la ligne doit s'arrêter juste après
# « performance », avec au plus une parenthèse en fin de ligne — jamais un
# texte libre qui suit sans parenthèses (ce qui aurait, par exemple, laissé
# passer « Indice de performance VO2 » à nouveau). Accepté mais SIGNALÉ (voir
# `parse_performance_index`) : mieux vaut lire une section probable avec un
# avertissement que la faire disparaître silencieusement.
_INDEX_TOP_HEADING_LOOSE_RE = re.compile(r"^(#{2,4})\s*indices? de performance\b(?:\s*\([^)\n]*\))?\s*$",
                                          re.I | re.M)
_INDEX_TOP_BULLET_RE = re.compile(r"^[-*]\s+(.+)$")
_ANY_HEADING_RE = re.compile(r"^(#{1,6})\s", re.M)
# Séparateur date / reste de la ligne : cadratin/demi-cadratin entouré d'espaces,
# ou un tiret simple/double ENTOURÉ D'ESPACES (même discipline que
# `_GEAR_SEGMENT_SPLIT_RE` : jamais un tiret sans espaces, qui ferait partie de
# la date ISO elle-même — revue de code #62 : élargi à `--` pour l'athlète qui
# tape un double tiret ASCII au lieu d'un cadratin).
_INDEX_DATE_SPLIT_RE = re.compile(r"\s*[—–]\s*|\s+-{1,2}\s+")
UTMB_INDEX_CATEGORIES = ("20k", "50k", "100k", "100m")
# Unité UTMB collée au nombre avec un espace intercalé (« 100 k », « 100 K ») :
# revue de code #62 — repliée sur la forme sans espace avant tokenisation.
_INDEX_UTMB_UNIT_SPACING_RE = re.compile(r"(\d)\s+([km])\b", re.I)
# Synonymes de « indice général » (sans catégorie), tous types confondus,
# comparés une fois accents retirés et en minuscule — revue de code #62 :
# « Général »/« general »/« global »/« Index » (ce dernier pour « UTMB Index »,
# le nom officiel de l'indice général UTMB) doivent tous se résoudre à
# `category = None`, pas à une fausse catégorie littérale « general »/« index ».
_INDEX_GENERAL_SYNONYMS = {"general", "generale", "global", "globale", "index"}
# Bornes plausibles d'un indice ITRA/UTMB (revue de code #62) : au-delà, une
# valeur est presque sûrement une faute de saisie (un temps, un dossard...),
# jamais un indice réel — avertie et rejetée plutôt que stockée telle quelle.
INDEX_VALUE_MIN, INDEX_VALUE_MAX = 0, 1000


def _strip_html_comments(text: str) -> str:
    return re.sub(r"<!--.*?-->", "", text, flags=re.S)


def _index_section(text: str) -> Tuple[Optional[str], Optional[str]]:
    """`(texte, avertissement)` de la section « Indices de performance » :
    depuis le titre principal (n'importe quel niveau entre `##` et `####`)
    jusqu'au prochain titre de niveau ÉGAL OU SUPÉRIEUR (donc jamais coupé par
    la sous-section « ### Historique des indices », de niveau plus profond) —
    ou la fin du fichier. `(None, None)` si aucun titre, strict ou nu, n'est
    trouvé. Les commentaires HTML sont retirés avant la recherche, comme
    `_gear_section` — l'exemple commenté du modèle ne doit jamais être lu
    comme un relevé réel.

    Titre STRICT (mentionne ITRA/UTMB) d'abord, sans avertissement. À défaut,
    titre NU (`_INDEX_TOP_HEADING_LOOSE_RE`, revue de code #109 3e tour) —
    accepté quand même, mais avec un avertissement : un titre renommé ou
    simplifié par l'athlète reste plus probablement CETTE section qu'une
    coïncidence, mieux vaut la lire en le signalant que la perdre en silence."""
    text = _strip_html_comments(text)
    m = _INDEX_TOP_HEADING_RE.search(text)
    warning = None
    if not m:
        m = _INDEX_TOP_HEADING_LOOSE_RE.search(text)
        if not m:
            return None, None
        warning = (f"titre « {m.group(0).strip()} » sans mention ITRA/UTMB — lu comme la section "
                   "« Indices de performance » quand même, à vérifier.")
    level = len(m.group(1))
    rest = text[m.end():]
    for candidate in _ANY_HEADING_RE.finditer(rest):
        if len(candidate.group(1)) <= level:
            return rest[: candidate.start()], warning
    return rest, warning


def _normalize_index_category(tokens: List[str]) -> Optional[str]:
    """Jointure des tokens de catégorie restants (catégorie multi-mots
    préservée, ex. « senior hommes ») ; `None` si le résultat est un synonyme
    d'« indice général » (`_INDEX_GENERAL_SYNONYMS`), accents et casse
    ignorés."""
    if not tokens:
        return None
    category = " ".join(tokens)
    bare = "".join(c for c in unicodedata.normalize("NFKD", category.lower()) if not unicodedata.combining(c))
    if bare in _INDEX_GENERAL_SYNONYMS:
        return None
    return category


def _parse_index_entry(raw: str) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Une ligne « AAAA-MM-JJ — itra|utmb [catégorie] : valeur » → `(entrée,
    avertissement)`. `entrée` est `None` si la ligne ne respecte pas ce format
    (date absente, type ni « itra » ni « utmb », catégorie UTMB hors
    nomenclature, valeur hors bornes ou non numérique) — l'avertissement porte
    alors la raison exacte.

    Une date FUTURE n'est PAS vérifiée ici (revue de code #109, 2e tour) :
    « futur » n'a de sens qu'au moment de la LECTURE, pas de l'écriture — un
    relevé du 30 septembre 2026 était futur le jour où l'athlète l'a écrit
    (course pas encore courue ? faute de frappe ?) mais ne l'est plus le
    lendemain, sans que le fichier lui-même n'ait changé. Un avertissement
    calculé ICI, au parsing, resterait donc figé « date future » en base tant
    que le fichier ne change pas, périmé dès le jour suivant. Ce calcul vit à
    la place dans `arc_index.performance_index`, recalculé à CHAQUE lecture
    contre le jour courant, jamais stocké."""
    original = raw.replace("**", "").strip()
    parts = _INDEX_DATE_SPLIT_RE.split(original, maxsplit=1)
    if len(parts) != 2:
        return None, f"format non reconnu (date — type [catégorie] : valeur attendu) : « {original} »"
    date_part, rest = parts
    entry_date = parse_fr_date(date_part)
    if not entry_date:
        return None, f"date illisible, ligne ignorée : « {original} »"
    if ":" not in rest:
        return None, f"format non reconnu (« : valeur » manquant) : « {original} »"
    head, value_raw = rest.split(":", 1)
    head = _INDEX_UTMB_UNIT_SPACING_RE.sub(r"\1\2", head)
    tokens = head.strip().lower().split()
    if not tokens or tokens[0] not in ("itra", "utmb"):
        return None, f"type ni « itra » ni « utmb », ligne ignorée : « {original} »"
    kind = tokens[0]
    category = _normalize_index_category(tokens[1:])
    if kind == "utmb" and category and category not in UTMB_INDEX_CATEGORIES:
        return None, (f"catégorie UTMB « {category} » inconnue (attendu : "
                       f"{'/'.join(UTMB_INDEX_CATEGORIES)} ou aucune), ligne ignorée : « {original} »")
    value = parse_fr_number(value_raw)
    if value is None or not (INDEX_VALUE_MIN < value <= INDEX_VALUE_MAX):
        return None, (f"valeur absente ou hors bornes plausibles (0 à {INDEX_VALUE_MAX}), "
                       f"ligne ignorée : « {original} »")
    entry = {"date": entry_date, "kind": kind, "value": value}
    if category:
        entry["category"] = category
    return entry, None


def parse_performance_index(text: str) -> Tuple[List[Dict[str, Any]], List[str]]:
    """Section « Indices de performance » du profil → `(entrées, avertissements)`.

    `entrées` : liste de dicts `{date, kind, value, category?, ordinal}` triée
    par date croissante, `ordinal` (ordre d'apparition dans le fichier, avant
    tri) servant de départage stable et explicite entre entrées de même date —
    jamais l'ordre implicite d'une table SQL. Vide si la section est absente.

    `avertissements` : un message par ligne illisible (ignorée) ou par doublon
    exact résolu — jamais imprimés ici : c'est à l'appelant (`arc_index.store`)
    de les faire persister, pour qu'ils restent visibles sans réapparaître en
    bruit console à chaque réindexation (voir `arc_index.performance_index`).
    La date FUTURE n'est PAS un avertissement de CE niveau (voir
    `_parse_index_entry`) : elle est recalculée à la lecture par
    `arc_index.performance_index`, jamais stockée ici.

    Un doublon EXACT (même date, même type, même catégorie) sur plusieurs
    lignes est un avertissement, pas une erreur : seule la DERNIÈRE ligne du
    fichier est retenue (correction probable d'une valeur mal saisie plus
    haut) — deux catégories DIFFÉRENTES à la même date ne sont jamais des
    doublons.

    AUCUNE récupération réseau ici, ni nulle part dans ce module : ces valeurs
    ne viennent QUE de ce que l'athlète a écrit lui-même (voir AGENTS.md,
    règle de vie privée #62 — un agent peut proposer une recherche web, mais
    seulement sur demande explicite, et jamais l'écrire sans confirmation)."""
    section, heading_warning = _index_section(text)
    if not section:
        return [], []
    warnings: List[str] = [heading_warning] if heading_warning else []
    parsed: List[Dict[str, Any]] = []
    ordinal = 0
    for line in section.splitlines():
        m = _INDEX_TOP_BULLET_RE.match(line)
        if not m:
            continue
        raw = m.group(1).strip()
        entry, warning = _parse_index_entry(raw)
        if entry is None:
            warnings.append(warning)
            continue
        entry["ordinal"] = ordinal
        ordinal += 1
        parsed.append(entry)

    # Doublons exacts (même date/type/catégorie) : garder la DERNIÈRE ligne du
    # fichier, avertir sur les précédentes.
    by_key: Dict[Tuple[str, str, Optional[str]], Dict[str, Any]] = {}
    for entry in parsed:
        key = (entry["date"], entry["kind"], entry.get("category"))
        previous = by_key.get(key)
        if previous is not None:
            label = f"{entry['kind']}" + (f" {entry['category']}" if entry.get("category") else "")
            warnings.append(
                f"doublon pour {entry['date']} ({label}) : {previous['value']:g} puis {entry['value']:g} — "
                "la dernière valeur du fichier est retenue.")
        by_key[key] = entry

    out = list(by_key.values())
    out.sort(key=lambda e: (e["date"], e["ordinal"]))
    return out, warnings


# ---------------------------------------------------------------------------
# Fichiers édités par l'humain : profil et objectif (libellés du modèle)
# ---------------------------------------------------------------------------

def _plausible_num(value: Optional[float], lo: float, hi: float) -> Optional[float]:
    """Valeur déclarée gardée seulement dans une plage plausible (sinon absente, jamais clampée)."""
    return value if value is not None and lo <= value <= hi else None


def parse_profile(text: str) -> Dict[str, Any]:
    """`planning/Runner_Profile.md` → champs utiles aux calculs (SI)."""
    b = parse_bullets(text)
    sex = normalize_label(_pick(b, "sexe") or "")
    out = {
        "hr_max_bpm": _int(parse_fr_number(_pick(b, "fc max"))),
        "hr_rest_bpm": _int(parse_fr_number(_pick(b, "fc de repos de reference", "fc de repos"))),
        "hr_threshold_bpm": _int(parse_fr_number(_pick(b, "fc au seuil", "fc seuil"))),
        # Snapshot Garmin informatif (story #65) : le tableau de bord calcule sa
        # propre estimation (`arc_metrics.vo2max_effective`/`vo2max_trend`) depuis
        # les séances réelles — ce champ n'alimente aucun calcul, juste un repère.
        "vo2max_reference": parse_fr_number(_pick(b, "vo2max (garmin)", "vo2max")),
        "sex": "female" if re.match(r"^(f|femme|female)\b", sex) else ("male" if re.match(r"^(h|m|homme|male)\b", sex) else None),
        "weight_kg": parse_weight_kg(_pick(b, "poids de forme", "poids")),
        "birth_year": _int(parse_fr_number(_pick(b, "annee de naissance"))),
        "sleep_need_s": _parse_sleep_need_s(_pick(b, "besoin de sommeil")),
        "default_location": _pick(b, "lieu par defaut"),
        "usual_slot": _pick(b, "creneau habituel"),
        "name": _pick(b, "prenom / surnom", "prenom"),
        # Section « ### Vélo & home trainer » : équipement DÉCLARÉ. Libellés choisis pour ne
        # jamais entrer en collision de préfixe avec « poids » (poids de l'athlète) ni « fc ».
        "ht_trainer": _pick(b, "home trainer"),
        "ht_bike": _pick(b, "velo sur home trainer"),
        "bike_mass_kg": _plausible_num(parse_fr_number(_pick(b, "masse du velo")), 3, 30),
        "ftp_declared_w": _plausible_num(parse_fr_number(_pick(b, "ftp declaree", "ftp")), 50, 600),
    }
    gear = parse_gear(text)
    if gear:
        out["gear"] = gear
    equipment = parse_equipment(text)
    if equipment:
        out["equipment"] = equipment
    performance_index, performance_index_warnings = parse_performance_index(text)
    if performance_index:
        out["performance_index"] = performance_index
    if performance_index_warnings:
        out["performance_index_warnings"] = performance_index_warnings
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
