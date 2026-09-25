#!/usr/bin/env python3
"""Normalisation des échantillons FIT seconde-par-seconde (#42, épopée #21).

Fonctions **pures**, sans SQLite ni accès disque en dehors de la découverte de
fichiers : la normalisation et le sous-échantillonnage sont testés isolément
(palier D), l'ingestion (écriture en base, idempotence, résolution de
`garmin_activity_id`) vit dans `scripts/arc_index.py` qui importe ce module.

## Où vivent les données brutes

Chemin canonique : `activities/fit/<garmin_activity_id>.json`, un objet JSON
`{"activity_id": <int>, "records": [...]}` (le générateur synthétique,
`tests/lib/synthetic.py::_write_samples`, y ajoute une clé `truth` ignorée ici).
Ce dossier est une donnée **brute et jetable** — reconstruisible à tout moment
depuis les fichiers FIT réels de Garmin — au même titre que `.arc/` : il n'est
**jamais versionné**. Le dépôt moteur l'exclut déjà via le motif racine
`/activities/` de `.gitignore` ; pour un workspace privé versionné séparément
(`docs/workspace.md`), `activities/fit/` reçoit son propre marqueur
`.gitignore` (même geste que `.arc/` dans `arc_index.open_db`), écrit à la
première utilisation par `download_fit.py` — pas besoin d'y penser à
l'installation.

`Le Markdown de la séance reste la source de vérité` (distance, D+, FC moyenne
déjà écrits dans le bloc ```arc``` par l'agent `coach`) : les échantillons
FIT ne sont qu'une donnée dérivée qui permet des KPI plus fins (zones #43, GAP
#44, découplage #45, VAM #46, descente #47, durabilité #48, modèle pente→allure
#58) — une séance sans FIT associé reste une séance valide, simplement sans ces
KPI (voir `arc_index.ingest_samples` : « orphelin » n'est jamais une erreur).

## Deux formats d'entrée acceptés par `normalise_records`

1. **Format normalisé** (celui que produit déjà `tests/lib/synthetic.py::sample_session`
   et celui que ce module produit en sortie) : une liste de dicts
   `{t_s, distance_m, altitude_m, hr_bpm, speed_ms, cadence_spm}` — `t_s` est le
   nombre de secondes écoulées depuis le départ de la séance (pas un horodatage
   absolu). Passé tel quel après validation/nettoyage des types.
2. **Format brut `fitparse`** — celui qu'écrit aujourd'hui
   `skills/fit-download/scripts/download_fit.py::_write_records_json`
   (`<id>.records.json`, une liste de dicts, un par message FIT `record`, champs
   nommés exactement comme les attributs `fitparse`) : `timestamp` (objet
   `datetime`, ou sa représentation `str()` une fois passé par
   `json.dumps(..., default=str)` — Garmin/`fitparse` produit un datetime UTC
   naïf, format `AAAA-MM-JJ HH:MM:SS[.ffffff]`), `distance` (mètres, cumulés
   depuis le départ), `heart_rate` (bpm), `enhanced_altitude` ou `altitude`
   (mètres — `enhanced_*` est préféré, résolution plus fine sur les FIT
   récents), `enhanced_speed` ou `speed` (m/s — **déjà en m/s dans le FIT**,
   aucune conversion depuis des km/h), `cadence` (+ `fractional_cadence`
   optionnel).

   **Cadence — piège documenté** : le champ ANT+/FIT `cadence` d'une séance de
   course à pied compte les foulées d'**un seul pied** par minute (une demi-
   foulée totale), pas le nombre de pas total par minute affiché par Garmin
   Connect (« cadence » à l'écran = pas des deux pieds/min). `cadence_spm` en
   sortie de ce module est donc `(cadence + fractional_cadence) × 2`, pour
   rester comparable à `avg_cadence_spm` déjà stocké dans `activity` (lu depuis
   le Markdown, où l'agent recopie la valeur Garmin Connect, donc déjà doublée).
   Une valeur `cadence` absente reste `None`, jamais 0 (0 pas/min serait un
   arrêt réel, pas une mesure manquante).

`t_s` est calculé par rapport au **premier horodatage exploitable** de la
séance (`t0`), jamais une horloge murale absolue — un enregistrement sans
`timestamp` lisible est écarté (jamais un `t_s` inventé qui décalerait tout ce
qui suit). GPS (`position_lat`/`position_long`) n'est **jamais** repris : hors
du format normalisé (voir `tests/lib/synthetic.py`), les colonnes `lat`/`lon`
de la table `activity_sample` restent `NULL` pour toute donnée ingérée par ce
module — présentes dans le schéma pour un usage futur, pas remplies ici.

## Sous-échantillonnage (résolution configurable, 5 s par défaut)

Un point par seconde est un luxe qu'aucun KPI de l'épopée FIT ne demande et que
la table `activity_sample` paierait cher en lignes. `downsample` regroupe les
échantillons en buckets de `resolution_s` secondes (bucket `t_s // resolution_s`,
horodaté à sa borne INFÉRIEURE — `0, 5, 10, …`, jamais le centre ni la borne
supérieure, pour rester alignée sur une grille prévisible côté consommateurs) :

- `hr_bpm`, `speed_ms`, `cadence_spm` : **moyenne** des valeurs non nulles du
  bucket — une chute FC/vitesse d'une seconde ne doit pas dominer un bucket de 5,
  et c'est la convention déjà documentée par `sample_session` (GAP, découplage)
  pour ces grandeurs instantanées.
- `distance_m`, `altitude_m` : **dernière valeur** du bucket, jamais une
  moyenne — ce sont des cumuls monotones (D+ et distance totale) ; moyenner des
  valeurs cumulées sous-estimerait systématiquement la fin de la séance et
  fausserait tout calcul de pente entre deux buckets consécutifs.
- Un bucket sans aucune valeur non nulle pour une colonne donnée rend `None`
  pour cette colonne (jamais 0) — cohérent avec le reste du projet
  (`arc_metrics.ASSUMPTIONS`) : une mesure absente reste absente.
- `resolution_s <= 1` désactive le sous-échantillonnage (chaque seconde reste
  son propre point) — utile en test, jamais le défaut en production.

`resolution_s = 5` donne, pour une sortie d'1 h : 720 lignes. Voir le budget de
taille documenté dans `arc_index.ingest_samples`.

Bibliothèque standard uniquement (CONTRIBUTING.md) — `fitparse` reste
l'affaire exclusive de `download_fit.py`, jamais une dépendance de l'index.
"""

from __future__ import annotations

from datetime import datetime
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

DEFAULT_RESOLUTION_S = 5

NORMALISED_KEYS = ("t_s", "distance_m", "altitude_m", "hr_bpm", "speed_ms", "cadence_spm")

# Formats `str(datetime)` rencontrés une fois passés par `json.dumps(..., default=str)`
# côté `download_fit.py` (naïf UTC, avec ou sans microsecondes) — et leurs équivalents
# "T" façon ISO 8601, au cas où une source future écrirait `datetime.isoformat()`.
_TIMESTAMP_FORMATS = (
    "%Y-%m-%d %H:%M:%S.%f",
    "%Y-%m-%d %H:%M:%S",
)

ASSUMPTIONS = {
    "canonical_path": "Échantillons bruts : activities/fit/<garmin_activity_id>.json, "
                       "{'activity_id', 'records'} — jetable, jamais versionné (voir docstring du module).",
    "cadence_doubling": "Le champ FIT `cadence` (course à pied) compte les foulées d'UN pied/min ; "
                         "cadence_spm = (cadence + fractional_cadence) × 2 pour rester comparable à "
                         "avg_cadence_spm (Garmin Connect, déjà doublé) déjà stocké dans `activity`.",
    "downsampling": f"Bucket de resolution_s secondes (défaut {DEFAULT_RESOLUTION_S} s), horodaté à sa borne "
                     "inférieure. hr_bpm/speed_ms/cadence_spm : moyenne du bucket. distance_m/altitude_m : "
                     "dernière valeur du bucket (cumuls monotones, jamais moyennés).",
    "missing_timestamp": "Un enregistrement fitparse sans `timestamp` exploitable est écarté silencieusement "
                          "(jamais de t_s inventé qui décalerait les échantillons suivants).",
}


def _num(value) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _first_present(record: dict, *keys: str):
    for key in keys:
        value = record.get(key)
        if value is not None:
            return value
    return None


def _parse_timestamp(value) -> Optional[datetime]:
    """Horodatage fitparse → `datetime` naïf. `None` si illisible (jamais d'exception)."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, (int, float)):
        # Rare (timestamp epoch déjà numérique plutôt qu'un objet datetime) : traité
        # comme des secondes Unix, sans fuseau (cohérent avec le reste, purement relatif).
        try:
            return datetime.fromtimestamp(float(value))
        except (OverflowError, OSError, ValueError):
            return None
    text = str(value).strip().replace("T", " ")
    for fmt in _TIMESTAMP_FORMATS:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def _cadence_spm(record: dict) -> Optional[float]:
    raw = record.get("cadence")
    if raw is None:
        return None
    fractional = record.get("fractional_cadence") or 0
    try:
        return (float(raw) + float(fractional)) * 2
    except (TypeError, ValueError):
        return None


def _normalise_fitparse(records: Sequence[dict]) -> List[dict]:
    parsed = [_parse_timestamp(r.get("timestamp")) for r in records]
    t0 = next((t for t in parsed if t is not None), None)
    if t0 is None:
        return []  # aucun horodatage exploitable dans tout le fichier : rien à ingérer
    out = []
    for record, ts in zip(records, parsed):
        if ts is None:
            continue
        out.append({
            "t_s": (ts - t0).total_seconds(),
            "distance_m": _num(record.get("distance")),
            "altitude_m": _num(_first_present(record, "enhanced_altitude", "altitude")),
            "hr_bpm": _num(record.get("heart_rate")),
            "speed_ms": _num(_first_present(record, "enhanced_speed", "speed")),
            "cadence_spm": _cadence_spm(record),
        })
    out.sort(key=lambda r: r["t_s"])
    return out


def _clean_normalised(record: dict) -> dict:
    return {key: _num(record.get(key)) for key in NORMALISED_KEYS}


def normalise_records(raw) -> List[dict]:
    """Normalise des échantillons bruts (fitparse OU déjà normalisés) vers le format
    canonique `{t_s, distance_m, altitude_m, hr_bpm, speed_ms, cadence_spm}`.

    Accepte `raw` sous forme d'objet `{"records": [...], ...}` (format canonique
    `activities/fit/<id>.json`, avec ou sans `truth`) ou directement une liste de
    dicts. Détecte le format déjà normalisé à la présence de la clé `t_s` dans le
    premier enregistrement ; sinon, applique le mapping fitparse documenté en tête
    de module. `[]` en entrée (ou une liste vide) rend `[]`, jamais une exception.
    """
    records = raw.get("records") if isinstance(raw, dict) else raw
    if not records:
        return []
    if "t_s" in records[0]:
        return [_clean_normalised(r) for r in records]
    return _normalise_fitparse(records)


def _mean(values: Iterable) -> Optional[float]:
    values = [v for v in values if v is not None]
    return sum(values) / len(values) if values else None


def downsample(records: Sequence[dict], resolution_s: int = DEFAULT_RESOLUTION_S) -> List[dict]:
    """Regroupe des échantillons normalisés (triés ou non) par buckets de `resolution_s`
    secondes. Voir la docstring du module pour la méthode (moyenne vs dernière valeur)
    et ses raisons. `resolution_s <= 1` désactive le regroupement."""
    if resolution_s <= 1:
        return [dict(r) for r in records]
    buckets: Dict[int, List[dict]] = {}
    for record in records:
        t_s = record.get("t_s")
        if t_s is None:
            continue
        idx = int(t_s // resolution_s)
        buckets.setdefault(idx, []).append(record)
    out = []
    for idx in sorted(buckets):
        group = buckets[idx]
        out.append({
            "t_s": idx * resolution_s,
            "distance_m": group[-1].get("distance_m"),
            "altitude_m": group[-1].get("altitude_m"),
            "hr_bpm": _mean(r.get("hr_bpm") for r in group),
            "speed_ms": _mean(r.get("speed_ms") for r in group),
            "cadence_spm": _mean(r.get("cadence_spm") for r in group),
        })
    return out


def sample_file_activity_id(path) -> Optional[int]:
    """`garmin_activity_id` porté par un chemin canonique `<id>.json` (nom de fichier).

    `None` si le nom de fichier n'est pas un entier — appelant alors replié sur la
    clé `activity_id` du contenu JSON (voir `arc_index.ingest_samples`)."""
    stem = path.stem if hasattr(path, "stem") else path.rsplit("/", 1)[-1].rsplit(".", 1)[0]
    return int(stem) if stem.isdigit() else None
