#!/usr/bin/env python3
"""Normalisation des échantillons FIT seconde-par-seconde (#42, épopée #21).

Fonctions **pures**, sans SQLite ni accès disque : la normalisation et le
sous-échantillonnage sont testés isolément (palier D). L'ingestion (écriture en
base, idempotence, résolution du lien avec `activity`) vit dans
`scripts/arc_index.py`, qui importe ce module ; l'écriture du fichier canonique
vit dans `skills/fit-download/scripts/download_fit.py`, qui l'importe aussi.

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
l'installation. Les fichiers `.fit`/`.records.json` bruts (GPS complets, plus
lourds, écrits à côté par `download_fit.py` pour compatibilité ascendante)
reçoivent le même traitement (voir `download_fit._ensure_gitignore`).

`Le Markdown de la séance reste la source de vérité` (distance, D+, FC moyenne
déjà écrits dans le bloc ```arc``` par l'agent `coach`) : les échantillons
FIT ne sont qu'une donnée dérivée qui permet des KPI plus fins (zones #43, GAP
#44, découplage #45, VAM #46, descente #47, durabilité #48, modèle pente→allure
#58) — une séance sans FIT associé reste une séance valide, simplement sans ces
KPI. Symétriquement, un FIT ingéré avant que le Markdown de la séance n'existe
encore (téléchargement puis synchronisation, ou ordre inverse d'un run
`daily-sync`) n'est PAS perdu : voir `arc_index.py` — les échantillons sont
stockés sous leur `garmin_activity_id`, indépendamment de l'existence d'une
ligne `activity`, et se rattachent d'eux-mêmes dès qu'elle apparaît.

## Deux formats d'entrée acceptés par `normalise_records`

1. **Format normalisé** (celui que produit déjà `tests/lib/synthetic.py::sample_session`
   et celui que ce module produit en sortie) : une liste de dicts
   `{t_s, distance_m, altitude_m, hr_bpm, speed_ms, cadence_spm}` — `t_s` est le
   nombre de secondes écoulées depuis le départ de la séance (pas un horodatage
   absolu). Passé tel quel après validation/nettoyage des types (et retri par
   `t_s`, au cas où la source ne le garantirait pas).
2. **Format brut `fitparse`** — celui qu'écrit aujourd'hui
   `skills/fit-download/scripts/download_fit.py::_write_records_json`
   (`<id>.records.json`, une liste de dicts, un par message FIT `record`, champs
   nommés exactement comme les attributs `fitparse`) : `timestamp` (objet
   `datetime`, ou sa représentation `str()`/`isoformat()` une fois passé par
   `json.dumps(..., default=str)` — Garmin/`fitparse` produit en général un
   datetime UTC naïf, format `AAAA-MM-JJ HH:MM:SS[.ffffff]`, mais une source ISO
   8601 avec fuseau (`...+00:00`, `...Z`) est aussi acceptée, fuseau ignoré une
   fois la valeur rendue naïve — voir `_parse_timestamp`), `distance` (mètres,
   cumulés depuis le départ), `heart_rate` (bpm), `enhanced_altitude` ou
   `altitude` (mètres — `enhanced_*` est préféré, résolution plus fine sur les
   FIT récents), `enhanced_speed` ou `speed` (m/s — **déjà en m/s dans le
   FIT**, aucune conversion depuis des km/h), `cadence` (+ `fractional_cadence`
   optionnel).

   **Cadence — piège documenté, ET spécifique au sport.** Le champ ANT+/FIT
   `cadence` d'une séance à pied (course, marche, randonnée) compte les
   foulées d'**un seul pied** par minute (une demi-foulée totale), pas le
   nombre de pas total par minute affiché par Garmin Connect (« cadence » à
   l'écran = pas des deux pieds/min) — **mais ce même champ, sur une séance de
   vélo, est déjà la cadence complète (tr/min des deux pédales)** : le
   doubler serait un doublement erroné, pas une correction. `normalise_records`
   prend donc un paramètre `sport` optionnel (chaîne FIT/Garmin, ex.
   `"running"`, `"trail_running"`, `"cycling"` — voir `CADENCE_DOUBLING_SPORTS`
   pour la liste exacte et sa justification) : seuls les sports à pied
   reçoivent le doublement. `sport=None` (absent — FIT sans message `session`
   lisible, ou appelant qui ne l'a pas encore résolu) applique **par défaut**
   le doublement : la quasi-totalité des FIT ingérés par ce moteur de coaching
   trail-running sont des séances à pied (voir `ASSUMPTIONS["cadence_doubling"]`)
   — `download_fit.py` lit ce champ dans le message `session` du FIT et le
   transmet explicitement dès qu'il est disponible, pour ne JAMAIS tomber sur
   ce défaut avec un vrai FIT vélo. Une valeur `cadence` absente reste `None`,
   jamais 0 (0 pas/min serait un arrêt réel, pas une mesure manquante).

`t_s` est calculé par rapport au **plus ancien horodatage exploitable** de la
séance (`t0 = min(...)`, jamais le premier enregistrement du fichier — un FIT
dont le tout premier `record` serait hors séquence ne doit jamais produire de
`t_s` négatif), jamais une horloge murale absolue — un enregistrement sans
`timestamp` lisible, ou une valeur non finie (`NaN`/`inf`, `fitparse` peut en
produire sur un capteur défaillant), est écarté (jamais un `t_s` inventé qui
décalerait tout ce qui suit).

**GPS (`lat_deg`/`lon_deg`, #49)** — repris depuis `position_lat`/`position_long`
(entiers FIT en semi-cercles, `fitparse` ne les convertit PAS lui-même en degrés :
conversion `valeur × 180 / 2³¹`, voir `_semicircle_to_deg`) quand le FIT les fournit,
`None` sinon (capteur GPS absent/coupé, séance indoor, ou trou de signal ponctuel —
jamais une valeur inventée). Colonnes `lat`/`lon` de `activity_sample`, réservées par
#42 « pour un usage futur » : #49 (identité de montée entre séances, `arc_climb_match.py`)
est cet usage — la position n'est utilisée QUE pour apparier une montée détectée à un
`climb_segment` déjà vu (bornes début/sommet), **jamais exposée telle quelle par l'API**
(voir `arc_climb_match.ASSUMPTIONS["privacy"]`) : le tableau de bord et
`skills/course-comparison` ne reçoivent qu'un `segment_id` et un nom de lieu, jamais une
coordonnée brute. Le format déjà normalisé (`tests/lib/synthetic.py::sample_session`)
n'émet PAS ces clés (voir `tests/lint/test_synthetic_no_real_data.py`) : `sample_session`
n'a reçu AUCUN paramètre GPS par cette histoire (#49) — les tests qui ont besoin d'une
trace GPS (`tests/data/test_arc_climb_match.py`) construisent leurs propres échantillons à
la main, avec des coordonnées fictives (océan sans terre, jamais un vrai lieu — voir
`tests/lint/test_synthetic_no_real_data.py::SAFE_LAT_RANGE`/`SAFE_LON_RANGE`), plutôt que
d'étendre le générateur partagé. Un appelant qui fournit EXPLICITEMENT `lat_deg`/`lon_deg`
au format déjà normalisé les voit repassées telles quelles par `_clean_normalised`
(passthrough générique, pas une fonctionnalité dédiée de `sample_session`).

## Pauses et trous de signal : jamais interpolés

Un `record` FIT est absent pendant une pause (montre en veille), une perte GPS,
ou un signal FC qui décroche : ce module ne comble **jamais** ces trous — le
`t_s` du `record` suivant reprend simplement là où le capteur reprend, ce qui
peut laisser un écart entre deux `t_s` consécutifs **strictement supérieur** à
`resolution_s` après sous-échantillonnage (aucun bucket vide n'est inséré pour
la période silencieuse). Un consommateur aval (durée effective de mouvement,
VAM #46, GAP #44…) qui suppose un pas de temps constant entre échantillons
consécutifs DOIT vérifier `dt = t_s[i] - t_s[i-1]` avant de l'utiliser comme
diviseur — voir `ASSUMPTIONS["gaps"]`.

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
- `distance_m`, `altitude_m` : **dernière valeur (dans le temps)** du bucket,
  jamais une moyenne — ce sont des cumuls monotones (D+ et distance totale) ;
  moyenner des valeurs cumulées sous-estimerait systématiquement la fin de la
  séance et fausserait tout calcul de pente entre deux buckets consécutifs.
  Le bucket est trié par `t_s` avant d'en prendre la dernière valeur : `downsample`
  ne suppose donc PAS que son entrée est déjà triée (contrairement à une
  version antérieure de ce module), seul `normalise_records` en sortie est
  garanti trié.
- Un bucket sans aucune valeur non nulle pour une colonne donnée rend `None`
  pour cette colonne (jamais 0) — cohérent avec le reste du projet
  (`arc_metrics.ASSUMPTIONS`) : une mesure absente reste absente.
- `resolution_s <= 1` désactive le sous-échantillonnage (chaque seconde reste
  son propre point) — utile en test, jamais le défaut en production.
- Un trou de signal (voir ci-dessus) laisse simplement des buckets absents de
  la sortie — jamais un bucket `None` inséré pour combler.

`resolution_s = 5` donne, pour une sortie d'1 h : 720 lignes. Voir le budget de
taille documenté dans `arc_index.ingest_samples`.

## Ce que ce module NE fait PAS

Aucun lissage d'altitude, aucune hystérésis D+/D- (la fluctuation typique d'un
altimètre barométrique produirait un D+ démesuré sans un filtre dédié) : ce
sont des choix de méthode qui appartiennent aux consommateurs (#46 VAM, #47
descente) et à leurs propres `ASSUMPTIONS`, documentés là-bas, pas ici. Ce
module se contente de restituer fidèlement — normalisé, sous-échantillonné —
ce que le capteur a mesuré.

Bibliothèque standard uniquement (CONTRIBUTING.md) — `fitparse` reste
l'affaire exclusive de `download_fit.py`, jamais une dépendance de l'index.
"""

from __future__ import annotations

import math
from datetime import datetime
from typing import Dict, Iterable, List, Optional, Sequence

DEFAULT_RESOLUTION_S = 5

NORMALISED_KEYS = ("t_s", "distance_m", "altitude_m", "hr_bpm", "speed_ms", "cadence_spm")

# GPS (#49) — clés OPTIONNELLES, jamais requises : un enregistrement/échantillon sans
# position reste valide, `lat_deg`/`lon_deg` valent alors `None`. Séparées de
# `NORMALISED_KEYS` (toujours requises pour un `t_s` exploitable) à dessein.
GPS_KEYS = ("lat_deg", "lon_deg")

# FIT/ANT+ code les positions en "semi-cercles" (entier signé 32 bits, plage complète du
# type = 360°) : conversion vers des degrés décimaux usuels. `fitparse` NE convertit PAS
# lui-même `position_lat`/`position_long` (aucun scale/offset défini par le profil FIT
# pour ces champs) — la conversion reste à la charge du consommateur, ici.
_SEMICIRCLE_TO_DEG = 180.0 / (2 ** 31)

# Sports FIT/Garmin « à pied » : seuls ceux-là voient leur `cadence` doublée (un
# pied/min → deux pieds/min). Les noms couvrent à la fois les valeurs `fitparse`
# habituelles ("running", "walking", "hiking") et leurs variantes composées que
# Garmin utilise parfois pour le sous-sport ("trail_running", "track_running").
# Le vélo (`cycling`, `indoor_cycling`, ...), la nage, l'aviron et le reste en
# sont volontairement absents : leur `cadence` FIT est déjà la valeur complète.
CADENCE_DOUBLING_SPORTS = frozenset({
    "running", "trail_running", "track_running", "treadmill_running",
    "walking", "hiking", "trail_hiking",
})

# Formats `str(datetime)` rencontrés une fois passés par `json.dumps(..., default=str)`
# côté `download_fit.py` (naïf UTC, avec ou sans microsecondes).
_TIMESTAMP_FORMATS = (
    "%Y-%m-%d %H:%M:%S.%f",
    "%Y-%m-%d %H:%M:%S",
)

ASSUMPTIONS = {
    "canonical_path": "Échantillons bruts : activities/fit/<garmin_activity_id>.json, "
                       "{'activity_id', 'records'} — jetable, jamais versionné (voir docstring du module).",
    "cadence_doubling": "Le champ FIT `cadence` d'une séance à pied (course, marche, randonnée — "
                         "CADENCE_DOUBLING_SPORTS) compte les foulées d'UN pied/min ; cadence_spm = "
                         "(cadence + fractional_cadence) × 2 pour rester comparable à avg_cadence_spm "
                         "(Garmin Connect, déjà doublé) déjà stocké dans `activity`. Sur un sport hors de "
                         "cette liste (vélo notamment), le champ est déjà la cadence complète : PAS doublé. "
                         "`sport=None` (non résolu) applique le doublement par défaut — l'immense majorité des "
                         "FIT ingérés par ce moteur trail-running sont des séances à pied ; `download_fit.py` "
                         "lit le sport réel dans le message FIT `session` dès que possible pour éviter ce défaut.",
    "downsampling": f"Bucket de resolution_s secondes (défaut {DEFAULT_RESOLUTION_S} s), horodaté à sa borne "
                     "inférieure. hr_bpm/speed_ms/cadence_spm : moyenne du bucket. distance_m/altitude_m/"
                     "lat_deg/lon_deg : dernière valeur (temporellement) du bucket (cumuls monotones ou "
                     "position, jamais moyennés).",
    "gps": "lat_deg/lon_deg (#49) : degrés décimaux convertis depuis les semi-cercles FIT "
           "(`position_lat`/`position_long`, `_semicircle_to_deg` — plage plausible PAR AXE, "
           "±90° latitude/±180° longitude, jamais un plafond unique aux deux, revue de code "
           "BLOQUANT), `None` si absents (indoor, capteur coupé) ou si la PAIRE vaut exactement "
           "(0, 0) — « île nulle », valeur sentinelle d'un GPS non fixé, jamais une position "
           "réelle plausible en course à pied (voir `_position_deg`) — jamais une position "
           "inventée en aval. Réservées à l'appariement de montée entre séances "
           "(`arc_climb_match.py`, #49) : jamais exposées telles quelles par l'API du tableau de "
           "bord ni par défaut par le CLI `samples`/`climb-history` (`--with-gps` les inclut "
           "explicitement pour un débogage local, voir `arc_climb_match.ASSUMPTIONS[\"privacy\"]`).",
    "missing_timestamp": "Un enregistrement fitparse sans `timestamp` exploitable, ou une valeur non finie "
                          "(NaN/inf), est écarté silencieusement (jamais de t_s inventé qui décalerait les "
                          "échantillons suivants). t0 = le PLUS ANCIEN horodatage exploitable, pas le premier "
                          "enregistrement du fichier (un capteur peut livrer un premier point hors séquence).",
    "gaps": "Les pauses/trous de signal (montre en veille, perte GPS/FC) ne sont JAMAIS interpolés : le t_s du "
            "record suivant reprend tel quel, sans bucket comblé pour la période silencieuse. dt entre deux "
            "échantillons consécutifs (avant ou après sous-échantillonnage) peut donc dépasser resolution_s — "
            "tout consommateur aval (#44 GAP, #46 VAM, #48 durabilité) qui utilise dt comme diviseur doit le "
            "vérifier explicitement plutôt que de supposer un pas constant.",
}


def _num(value) -> Optional[float]:
    if value is None:
        return None
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def _first_present(record: dict, *keys: str):
    for key in keys:
        value = record.get(key)
        if value is not None:
            return value
    return None


def _parse_timestamp(value) -> Optional[datetime]:
    """Horodatage fitparse → `datetime` naïf. `None` si illisible (jamais d'exception).

    Une valeur avec fuseau (ISO 8601 `...+00:00`/`...Z`) est acceptée puis rendue
    naïve (fuseau retiré) : `t_s` n'est qu'un écart relatif au premier
    horodatage de la MÊME séance, jamais une horloge absolue — mélanger naïf et
    "aware" ferait lever `TypeError` à la soustraction sans cette normalisation.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=None) if value.tzinfo is not None else value
    if isinstance(value, (int, float)):
        # Rare (timestamp epoch déjà numérique plutôt qu'un objet datetime) : traité
        # comme des secondes Unix, sans fuseau (cohérent avec le reste, purement relatif).
        if not math.isfinite(value):
            return None
        try:
            return datetime.fromtimestamp(float(value))
        except (OverflowError, OSError, ValueError):
            return None
    text = str(value).strip()
    for fmt in _TIMESTAMP_FORMATS:
        try:
            return datetime.strptime(text.replace("T", " "), fmt)
        except ValueError:
            continue
    # Repli ISO 8601 (avec ou sans fuseau, ex. "2026-01-01T08:00:00+00:00" ou
    # "...Z") : `datetime.fromisoformat` gère aussi bien le "T" que l'espace.
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=None) if parsed.tzinfo is not None else parsed


def _semicircle_to_deg(value, *, max_abs: float) -> Optional[float]:
    """Semi-cercles FIT (`position_lat`/`position_long`) → degrés décimaux, `None` si
    absent/non numérique/hors plage plausible — `max_abs` DOIT être passé explicitement par
    l'appelant (revue de code #49, BLOQUANT : une latitude et une longitude n'ont PAS la
    même plage valide — ±90° pour une latitude, ±180° pour une longitude — un plafond
    unique à 180° laissait passer une latitude physiquement impossible, ex. 150°, sans la
    détecter comme un FIT corrompu)."""
    deg = _num(value)
    if deg is None:
        return None
    deg *= _SEMICIRCLE_TO_DEG
    return round(deg, 6) if abs(deg) <= max_abs else None


def _cadence_spm(record: dict, sport: Optional[str]) -> Optional[float]:
    raw = record.get("cadence")
    if raw is None:
        return None
    fractional = record.get("fractional_cadence") or 0
    try:
        value = float(raw) + float(fractional)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(value):
        return None
    # sport=None (non résolu) : doublé par défaut — voir ASSUMPTIONS["cadence_doubling"].
    if sport is None or sport.lower() in CADENCE_DOUBLING_SPORTS:
        value *= 2
    return value


def _position_deg(record: dict) -> tuple:
    """`(lat_deg, lon_deg)` d'un enregistrement fitparse brut — voir `_semicircle_to_deg`
    pour la conversion/le plafond par axe. « Île nulle » (`lat == lon == 0.0` EXACTEMENT,
    revue de code #49, nit) : rejetée en PAIRE — c'est la valeur SENTINELLE classique d'un
    GPS non fixé/en panne (jamais une position réelle plausible pour ce moteur, un point de
    course à pied au large du Golfe de Guinée n'existe pas) — jamais rejetée séparément (un
    lon EXACTEMENT nul avec une vraie latitude reste une position parfaitement valide sur le
    méridien de Greenwich, ne pas la confondre avec l'île nulle)."""
    lat = _semicircle_to_deg(record.get("position_lat"), max_abs=90.0)
    lon = _semicircle_to_deg(record.get("position_long"), max_abs=180.0)
    if lat == 0.0 and lon == 0.0:
        return None, None
    return lat, lon


def _normalise_fitparse(records: Sequence[dict], sport: Optional[str]) -> List[dict]:
    parsed = [_parse_timestamp(r.get("timestamp")) for r in records]
    valid_ts = [t for t in parsed if t is not None]
    if not valid_ts:
        return []  # aucun horodatage exploitable dans tout le fichier : rien à ingérer
    t0 = min(valid_ts)   # PAS le premier enregistrement : voir ASSUMPTIONS["missing_timestamp"]
    out = []
    for record, ts in zip(records, parsed):
        if ts is None:
            continue
        lat_deg, lon_deg = _position_deg(record)
        out.append({
            "t_s": (ts - t0).total_seconds(),
            "distance_m": _num(record.get("distance")),
            "altitude_m": _num(_first_present(record, "enhanced_altitude", "altitude")),
            "hr_bpm": _num(record.get("heart_rate")),
            "speed_ms": _num(_first_present(record, "enhanced_speed", "speed")),
            "cadence_spm": _cadence_spm(record, sport),
            "lat_deg": lat_deg,
            "lon_deg": lon_deg,
        })
    out.sort(key=lambda r: r["t_s"])
    return out


def _clean_normalised(record: dict) -> Optional[dict]:
    cleaned = {key: _num(record.get(key)) for key in NORMALISED_KEYS}
    if cleaned["t_s"] is None:
        return None
    # GPS (#49) : repassé tel quel si l'appelant l'a déjà fourni au format normalisé
    # (`lat_deg`/`lon_deg` déjà en degrés décimaux, pas des semi-cercles ici — jamais
    # reconverti une seconde fois) — `None` sinon, jamais une clé absente (forme de
    # dict stable, comme le reste de ce module).
    for key in GPS_KEYS:
        cleaned[key] = _num(record.get(key))
    return cleaned


def normalise_records(raw, sport: Optional[str] = None) -> List[dict]:
    """Normalise des échantillons bruts (fitparse OU déjà normalisés) vers le format
    canonique `{t_s, distance_m, altitude_m, hr_bpm, speed_ms, cadence_spm}`, trié
    par `t_s` croissant.

    Accepte `raw` sous forme d'objet `{"records": [...], ...}` (format canonique
    `activities/fit/<id>.json`, avec ou sans `truth`) ou directement une liste de
    dicts. Détecte le format déjà normalisé à la présence de la clé `t_s` dans le
    premier enregistrement ; sinon, applique le mapping fitparse documenté en tête
    de module. `[]` en entrée (ou une liste vide) rend `[]`, jamais une exception.

    `sport` (chaîne FIT/Garmin, ex. `"running"`, `"cycling"`) gouverne le
    doublement de la cadence sur le chemin fitparse UNIQUEMENT (voir
    `CADENCE_DOUBLING_SPORTS`) — ignoré sur le chemin déjà normalisé, dont la
    cadence est supposée déjà dans l'unité finale (spm) par son producteur
    (`tests/lib/synthetic.py`, ou une ingestion précédente).
    """
    records = raw.get("records") if isinstance(raw, dict) else raw
    if not records:
        return []
    if "t_s" in records[0]:
        cleaned = [_clean_normalised(r) for r in records]
        cleaned = [r for r in cleaned if r is not None]
        cleaned.sort(key=lambda r: r["t_s"])
        return cleaned
    return _normalise_fitparse(records, sport)


def _mean(values: Iterable) -> Optional[float]:
    values = [v for v in values if v is not None]
    return sum(values) / len(values) if values else None


def downsample(records: Sequence[dict], resolution_s: int = DEFAULT_RESOLUTION_S) -> List[dict]:
    """Regroupe des échantillons normalisés (triés ou non) par buckets de `resolution_s`
    secondes. Voir la docstring du module pour la méthode (moyenne vs dernière valeur,
    trous de signal jamais comblés) et ses raisons. `resolution_s <= 1` désactive le
    regroupement (chaque échantillon reste son propre point)."""
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
        group = sorted(buckets[idx], key=lambda r: r["t_s"])   # dernière valeur = dernière DANS LE TEMPS
        last = group[-1]
        out.append({
            "t_s": idx * resolution_s,
            "distance_m": last.get("distance_m"),
            "altitude_m": last.get("altitude_m"),
            "hr_bpm": _mean(r.get("hr_bpm") for r in group),
            "speed_ms": _mean(r.get("speed_ms") for r in group),
            "cadence_spm": _mean(r.get("cadence_spm") for r in group),
            # GPS (#49) : dernière position (temporellement) du bucket, même convention que
            # distance_m/altitude_m — une moyenne de deux positions n'a aucun sens géométrique
            # simple (et serait fausse en présence de courbure/méridien), la dernière position
            # connue du bucket reste la plus proche de la borne du bucket suivant.
            "lat_deg": last.get("lat_deg"),
            "lon_deg": last.get("lon_deg"),
        })
    return out


def sample_file_activity_id(path) -> Optional[int]:
    """`garmin_activity_id` porté par un chemin canonique `<id>.json` (nom de fichier).

    `None` si le nom de fichier n'est pas un entier — appelant alors replié sur la
    clé `activity_id` du contenu JSON (voir `arc_index.ingest_samples`)."""
    stem = path.stem if hasattr(path, "stem") else path.rsplit("/", 1)[-1].rsplit(".", 1)[0]
    return int(stem) if stem.isdigit() else None
