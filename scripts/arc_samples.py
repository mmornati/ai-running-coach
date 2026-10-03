#!/usr/bin/env python3
"""Normalisation des échantillons FIT seconde-par-seconde (#42, épopée #21).

Fonctions **pures**, sans SQLite ni accès disque : la normalisation et le
sous-échantillonnage sont testés isolément (palier D). L'ingestion (écriture en
base, idempotence, résolution du lien avec `activity`) vit dans
`scripts/arc_index.py`, qui importe ce module ; l'écriture du fichier canonique
vit dans `skills/fit-download/scripts/download_fit.py`, qui l'importe aussi.

## Où vivent les données brutes

Chemin canonique : `activities/fit/<id>.json`, un objet JSON
`{"activity_id": <id>, "records": [...]}` — `<id>` est le `garmin_activity_id`
(entier) d'une séance Garmin, l'`intervals_activity_id` (chaîne `i<chiffres>`,
#68) d'une séance synchronisée depuis Intervals.icu, ou le `strava_activity_id` (chaîne
`s<chiffres>`, #164) d'une séance Strava dont les flux par seconde ont été normalisés
par `strava_streams_to_records` (voir `parse_activity_ref`).
Le générateur synthétique (`tests/lib/synthetic.py::_write_samples`) y ajoute une
clé `truth`, ignorée ici. Ce dossier est une donnée **brute et jetable** —
reconstruisible à tout moment depuis les fichiers FIT réels (Garmin Connect ou
Intervals.icu, `skills/fit-download`) — au même titre que `.arc/` : il n'est
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
stockés sous leur identifiant externe (`garmin_activity_id` ou
`intervals_activity_id`), indépendamment de l'existence d'une ligne `activity`, et
se rattachent d'eux-mêmes dès qu'elle apparaît.

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
`climb_segment` déjà vu (bornes début/sommet) — et pour la carte de la page séance du
tableau de bord, seule route qui l'expose (`/api/activity/<id>/track`, voir
`arc_climb_match.ASSUMPTIONS["privacy"]`) : les routes de montée et
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

## Altitude à 0,0 m : valeur sentinelle, pas une mesure

Une plage d'altitude à exactement 0,0 m bordée d'un saut d'au moins
`ZERO_ALTITUDE_JUMP_M` vers la mesure voisine devient `None` (mesure absente) —
voir `ASSUMPTIONS["zero_altitude"]` et `_mask_zero_altitude_sentinels`.

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
- `covered_s` : secondes que les mesures du bucket couvrent réellement (≤
  `resolution_s`) — un bucket autour d'une pause ou en fin de séance n'est que
  partiellement rempli. Voir `ASSUMPTIONS["covered_s"]`.

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
import re
from datetime import datetime
from typing import Dict, Iterable, List, Optional, Sequence, Union

DEFAULT_RESOLUTION_S = 5

# Identifiant Intervals.icu d'une activité importée depuis un fichier (#68) : « i » +
# chiffres, ex. `i123456789` — voir `parse_activity_ref`.
INTERVALS_ID_RE = re.compile(r"^i\d+$")

# Identifiant Strava d'une activité (#164) : « s » + chiffres, ex. `s12345678901`. L'API
# Strava rend un entier 64 bits SANS préfixe, indiscernable d'un `garmin_activity_id` : le
# préfixe `s` est une convention de CE projet (comme le `i` d'Intervals.icu, qui lui est
# natif), il garde les trois espaces d'identifiants disjoints dans `activities/fit/<id>.json`
# et dans l'index. Voir `parse_activity_ref`.
STRAVA_ID_RE = re.compile(r"^s\d+$")

# Saut minimal (m) entre une plage d'altitude à 0,0 m et la mesure valide voisine pour
# la traiter en valeur sentinelle — voir ASSUMPTIONS["zero_altitude"].
ZERO_ALTITUDE_JUMP_M = 20.0

NORMALISED_KEYS = ("t_s", "distance_m", "altitude_m", "hr_bpm", "speed_ms", "cadence_spm")

# GPS (#49) — clés OPTIONNELLES, jamais requises : un enregistrement/échantillon sans
# position reste valide, `lat_deg`/`lon_deg` valent alors `None`. Séparées de
# `NORMALISED_KEYS` (toujours requises pour un `t_s` exploitable) à dessein.
GPS_KEYS = ("lat_deg", "lon_deg")

# Dynamique de course Garmin (#151) — clés OPTIONNELLES comme le GPS : une séance sans
# capteur de dynamique (montre seule sans ceinture/pod compatible, vélo, marche…) les garde à
# `None`, JAMAIS à 0 ni (pour la balance) à 50 %. Unités SI ; conversions FIT documentées par
# `ASSUMPTIONS["running_dynamics"]`. Noms = colonnes `activity_sample`.
DYNAMICS_KEYS = ("ground_contact_s", "stance_balance_pct", "vertical_oscillation_m",
                 "vertical_ratio_pct", "step_length_m")

# Plages physiologiquement plausibles : hors plage → mesure absente (`None`), jamais clampée.
# Un capteur qui renvoie 0 (pas de mesure) ou une valeur aberrante ne doit pas tirer une moyenne.
DYNAMICS_PLAUSIBLE = {
    "ground_contact_s": (0.05, 1.0),          # 50 ms – 1 s
    "stance_balance_pct": (30.0, 70.0),       # jamais 0 ni 100 ; 50 = symétrique
    "vertical_oscillation_m": (0.01, 0.30),   # 1 – 30 cm
    "vertical_ratio_pct": (1.0, 30.0),
    "step_length_m": (0.2, 3.0),
}

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
    "canonical_path": "Échantillons bruts : activities/fit/<garmin_activity_id | intervals_activity_id | strava_activity_id>.json, "
                       "{'activity_id', 'records'} — jetable, jamais versionné (voir docstring du module).",
    "cadence_doubling": "Le champ FIT `cadence` d'une séance à pied (course, marche, randonnée — "
                         "CADENCE_DOUBLING_SPORTS) compte les foulées d'UN pied/min ; cadence_spm = "
                         "(cadence + fractional_cadence) × 2 pour rester comparable à avg_cadence_spm "
                         "(Garmin Connect, déjà doublé) déjà stocké dans `activity`. Sur un sport hors de "
                         "cette liste (vélo notamment), le champ est déjà la cadence complète : PAS doublé. "
                         "`sport=None` (non résolu) applique le doublement par défaut — l'immense majorité des "
                         "FIT ingérés par ce moteur trail-running sont des séances à pied ; `download_fit.py` "
                         "lit le sport réel dans le message FIT `session` dès que possible pour éviter ce défaut.",
    "running_dynamics": "Dynamique de course Garmin (#151), champs `record` FIT lus par `fitparse` (l'échelle du "
                         "profil FIT est DÉJÀ appliquée par `fitparse`) : `stance_time` (ms) → ground_contact_s "
                         "= ms / 1000 ; `vertical_oscillation` (mm) → vertical_oscillation_m = mm / 1000 ; "
                         "`step_length` (mm) → step_length_m = mm / 1000 ; `vertical_ratio` (%) → "
                         "vertical_ratio_pct (inchangé) ; `stance_time_balance` (%) → stance_balance_pct "
                         "(inchangé). `stance_time_percent` (% de la foulée, autre champ) n'est PAS repris. Une "
                         "valeur absente, nulle ou hors DYNAMICS_PLAUSIBLE reste `None` — en particulier une "
                         "balance absente (capteur qui ne la fournit pas : 15 séances de course sur 80 dans "
                         "l'installation observée) n'est JAMAIS remplacée par 50 %. Sous-échantillonnage : "
                         "moyenne des valeurs présentes du bucket (comme cadence_spm). Le SENS de la balance "
                         "(quel pied porte le pourcentage) n'est pas établi par le profil FIT de `fitparse` : "
                         "voir arc_gait.ASSUMPTIONS[\"balance_side\"].",
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
    "zero_altitude": "Certaines montres/exports écrivent une altitude à EXACTEMENT 0,0 m quand l'altimètre "
                     "ne mesure rien (observé : Apple Watch via Intervals.icu, plages de plusieurs minutes "
                     "au milieu d'une séance à ~600 m). Une plage de 0,0 m dont la mesure valide voisine "
                     "(avant OU après) est à au moins ZERO_ALTITUDE_JUMP_M (20 m) est une sentinelle : "
                     "altitude_m = None sur toute la plage (mesure absente, jamais interpolée — même règle "
                     "que les trous de signal). Un tel saut en un pas d'échantillonnage est impossible à pied ; "
                     "au niveau de la mer, l'altitude voisine d'un vrai 0 reste à quelques mètres, la plage est "
                     "conservée. Une séance entièrement à 0,0 m (aucune mesure voisine) reste telle quelle : "
                     "les consommateurs la traitent déjà comme « altitude toujours identique ». Sans ce masque, "
                     "chaque bord de plage produit un dénivelé de plusieurs centaines de mètres en quelques "
                     "secondes (VAM > 100 000 m/h, GAP et découplage faussés).",
    "covered_s": "Chaque bucket sous-échantillonné porte `covered_s` : les secondes que ses mesures couvrent "
                  "réellement, ≤ resolution_s. Un bucket autour d'une pause (montre en veille), ou le dernier "
                  "de la séance, n'est que partiellement rempli : sans ce champ, tout consommateur qui pèse un "
                  "échantillon par min(dt, resolution_s) le compterait pour resolution_s entières et "
                  "surestimerait le temps total (observé : jusqu'à ~4 % de temps en zone en trop, au-delà de "
                  "la durée de la séance). Méthode : chaque mesure couvre [t, t + dt_suivant) si dt_suivant "
                  "≤ resolution_s (enregistrement irrégulier mais continu) ; au-delà c'est une pause, jamais "
                  "comptée : la mesure ne couvre qu'un pas typique (écart médian entre mesures de la séance, "
                  "1 s pour un enregistrement à 1 Hz). Intervalle réparti sur les buckets chevauchés ; la "
                  "dernière mesure de la séance ne couvre rien (N mesures = N − 1 intervalles). Somme des covered_s ≤ durée écoulée entre la première et "
                  "la dernière mesure. `resolution_s <= 1` (pas de regroupement) : pas de covered_s, "
                  "min(dt, resolution_s) suffit alors.",
    "strava_streams": "Flux Strava (#164, `strava_streams_to_records`) : `time` (s depuis le départ) → t_s ; "
                       "`distance` (m) → distance_m ; `altitude` (m) → altitude_m ; `heartrate` (bpm) → "
                       "hr_bpm ; `velocity_smooth` (m/s, vitesse LISSÉE par Strava, pas la vitesse brute du "
                       "capteur) → speed_ms ; `cadence` → cadence_spm ; `latlng` ([lat, lon] en degrés) → "
                       "lat_deg/lon_deg. Un flux dont la longueur diffère de celui de `time` est écarté en "
                       "entier (jamais tronqué ni réaligné au jugé). Cadence : doublée pour les sports à pied "
                       "(`STRAVA_FOOT_SPORTS`), comme le champ FIT — HYPOTHÈSE à vérifier sur une vraie séance "
                       "(la référence de l'API documente `cadence` en RPM sans préciser un ou deux pieds). Dynamique de course (temps de contact, balance, "
                       "oscillation) : AUCUN flux équivalent chez Strava → colonnes à None, jamais devinées. "
                       "Résolution : la copie complète (`resolution` omise) à la seconde que l'API sert pour les "
                       "activités enregistrées avec une montre ; une activité sans flux (saisie manuelle) n'en a "
                       "aucun. Les données restent dans l'espace de travail privé de l'athlète (accord API "
                       "Strava) : jamais dans le dépôt public.",
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


def _dynamics(record: dict) -> dict:
    """Dynamique de course d'un enregistrement fitparse brut → clés SI de `DYNAMICS_KEYS`
    (`None` si absente/hors plage plausible) — voir `ASSUMPTIONS["running_dynamics"]`."""
    raw = {
        "ground_contact_s": _scaled(record.get("stance_time"), 1 / 1000.0),
        "stance_balance_pct": _num(record.get("stance_time_balance")),
        "vertical_oscillation_m": _scaled(record.get("vertical_oscillation"), 1 / 1000.0),
        "vertical_ratio_pct": _num(record.get("vertical_ratio")),
        "step_length_m": _scaled(record.get("step_length"), 1 / 1000.0),
    }
    return {k: _plausible(k, v) for k, v in raw.items()}


def _scaled(value, factor: float) -> Optional[float]:
    number = _num(value)
    return None if number is None else number * factor


def _plausible(key: str, value: Optional[float]) -> Optional[float]:
    if value is None:
        return None
    lo, hi = DYNAMICS_PLAUSIBLE[key]
    return round(value, 6) if lo <= value <= hi else None


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
            **_dynamics(record),
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
    # Dynamique de course (#151) : déjà en SI au format normalisé, repassée (plausibilité
    # rejouée) — `None` si absente, jamais une clé manquante.
    for key in DYNAMICS_KEYS:
        cleaned[key] = _plausible(key, _num(record.get(key)))
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
        return _mask_zero_altitude_sentinels(cleaned)
    return _mask_zero_altitude_sentinels(_normalise_fitparse(records, sport))


def _mask_zero_altitude_sentinels(records: List[dict]) -> List[dict]:
    """Remplace par `None` les plages d'altitude à EXACTEMENT 0,0 m qui sont une
    valeur sentinelle « pas de mesure », pas une altitude — voir
    ASSUMPTIONS["zero_altitude"]. `records` est déjà trié par `t_s` ; modifié en
    place et rendu pour chaîner."""
    n = len(records)
    i = 0
    while i < n:
        if records[i]["altitude_m"] != 0.0:
            i += 1
            continue
        j = i
        while j + 1 < n and records[j + 1]["altitude_m"] == 0.0:
            j += 1
        before = next((r["altitude_m"] for r in reversed(records[:i]) if r["altitude_m"] is not None), None)
        after = next((r["altitude_m"] for r in records[j + 1:] if r["altitude_m"] is not None), None)
        if any(v is not None and abs(v) >= ZERO_ALTITUDE_JUMP_M for v in (before, after)):
            for k in range(i, j + 1):
                records[k]["altitude_m"] = None
        i = j + 1
    return records


def _mean(values: Iterable) -> Optional[float]:
    values = [v for v in values if v is not None]
    return sum(values) / len(values) if values else None


def _bucket_coverage(records: Sequence[dict], resolution_s: int) -> Dict[int, float]:
    """Secondes réellement couvertes par les mesures dans chaque bucket — voir
    ASSUMPTIONS["covered_s"]. Chaque mesure couvre `[t, t + dt)` (dt = écart jusqu'à la
    mesure suivante) si `dt <= resolution_s` ; au-delà, c'est une pause et la mesure ne
    couvre qu'un pas d'enregistrement typique (écart médian de la séance). La dernière
    mesure de la séance ne couvre rien. L'intervalle est réparti sur les buckets qu'il
    chevauche."""
    times = sorted({r["t_s"] for r in records if r.get("t_s") is not None})
    steps = sorted(b - a for a, b in zip(times, times[1:]))
    typical = min(steps[len(steps) // 2], resolution_s) if steps else 0.0
    coverage: Dict[int, float] = {}
    for t, nxt in zip(times, times[1:]):
        dt = nxt - t
        start, end = t, t + (dt if dt <= resolution_s else typical)
        while start < end:
            idx = int(start // resolution_s)
            stop = min(end, (idx + 1) * resolution_s)
            coverage[idx] = coverage.get(idx, 0.0) + (stop - start)
            start = stop
    return coverage


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
    covered = _bucket_coverage(records, resolution_s)
    out = []
    for idx in sorted(buckets):
        group = sorted(buckets[idx], key=lambda r: r["t_s"])   # dernière valeur = dernière DANS LE TEMPS
        last = group[-1]
        out.append({
            "t_s": idx * resolution_s,
            "covered_s": round(covered.get(idx, 0.0), 3),
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
            # Dynamique de course (#151) : moyenne des valeurs PRÉSENTES du bucket (une mesure
            # absente reste absente — jamais 0, jamais 50 % de balance).
            **{key: _mean(r.get(key) for r in group) for key in DYNAMICS_KEYS},
        })
    return out


# Sports Strava (`sport_type`/`type`) à pied : cadence à doubler, comme CADENCE_DOUBLING_SPORTS
# côté FIT — voir ASSUMPTIONS["strava_streams"] (hypothèse à vérifier).
STRAVA_FOOT_SPORTS = frozenset({"run", "trailrun", "virtualrun", "walk", "hike"})


def _stream_data(streams, key: str):
    """`data` du flux `key` — `streams` est soit l'objet `key_by_type=true` de l'API Strava
    (`{"time": {"data": [...]}, ...}`), soit la liste par défaut (`[{"type": "time", "data":
    [...]}, ...]`). `None` si absent ou mal formé."""
    if isinstance(streams, dict):
        entry = streams.get(key)
    else:
        entry = next((e for e in (streams or []) if isinstance(e, dict) and e.get("type") == key), None)
    data = entry.get("data") if isinstance(entry, dict) else None
    return data if isinstance(data, list) else None


def strava_streams_to_records(streams, sport_type: Optional[str] = None) -> List[dict]:
    """Flux par seconde Strava (#164) → liste de dicts au format NORMALISÉ (`NORMALISED_KEYS`
    + `GPS_KEYS`), prête pour `normalise_records` (qui la nettoie et masque les altitudes
    sentinelles) et donc pour la même chaîne de KPI que le FIT (zones, GAP, découplage, VAM,
    descente, durabilité, énergie). Fonction pure.

    Rend `[]` sans flux `time` exploitable : sans horloge, aucun échantillon n'est datable —
    jamais un `t_s` inventé. Un autre flux dont la longueur diffère de `time` est ignoré en
    entier (voir ASSUMPTIONS["strava_streams"]). `sport_type` (`Run`, `TrailRun`, `Ride`…,
    insensible à la casse) gouverne le doublement de la cadence ; `None` = doublé, comme
    `normalise_records` sans sport."""
    time_s = _stream_data(streams, "time")
    if not time_s:
        return []
    n = len(time_s)

    def column(key: str):
        data = _stream_data(streams, key)
        return data if data is not None and len(data) == n else None

    distance, altitude = column("distance"), column("altitude")
    heartrate, speed = column("heartrate"), column("velocity_smooth")
    cadence, latlng = column("cadence"), column("latlng")
    double = sport_type is None or str(sport_type).lower() in STRAVA_FOOT_SPORTS

    def at(col, i):
        return _num(col[i]) if col is not None else None

    out = []
    for i in range(n):
        t = _num(time_s[i])
        if t is None:
            continue
        cad = at(cadence, i)
        lat = lon = None
        if latlng is not None and isinstance(latlng[i], (list, tuple)) and len(latlng[i]) == 2:
            lat, lon = _num(latlng[i][0]), _num(latlng[i][1])
        out.append({
            "t_s": t, "distance_m": at(distance, i), "altitude_m": at(altitude, i),
            "hr_bpm": at(heartrate, i), "speed_ms": at(speed, i),
            "cadence_spm": cad * 2 if (cad is not None and double) else cad,
            "lat_deg": lat, "lon_deg": lon,
        })
    return out


def parse_activity_ref(value) -> Optional[Union[int, str]]:
    """Identifiant externe d'une séance : un entier (`garmin_activity_id`), une
    chaîne `i<chiffres>` (`intervals_activity_id`, #68) ou `s<chiffres>`
    (`strava_activity_id`, #164). Accepte un entier, ou une chaîne de chiffres
    (→ `int`) ou de la forme `i123`/`s123` (→ `str`, inchangée). `None` pour tout le
    reste (booléen, vide, forme inconnue) — jamais deviné.

    Les trois espaces ne se chevauchent pas : le préfixe (`i`, `s`) distingue sans
    ambiguïté un identifiant Intervals.icu ou Strava d'un identifiant Garmin, dans un
    nom de fichier (`activities/fit/i123456789.json`) comme en argument de CLI."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if not isinstance(value, str):
        return None
    value = value.strip()
    if value.isdigit():
        return int(value)
    return value if (INTERVALS_ID_RE.match(value) or STRAVA_ID_RE.match(value)) else None


def sample_file_activity_id(path) -> Optional[Union[int, str]]:
    """Identifiant de séance porté par un chemin canonique `<id>.json` (nom de fichier) :
    entier Garmin (`24070286912.json`), chaîne Intervals.icu (`i123456789.json`) ou
    Strava (`s12345678901.json`), voir `parse_activity_ref`.

    `None` si le nom de fichier n'a aucune de ces formes — appelant alors replié
    sur la clé `activity_id` du contenu JSON (voir `arc_index.ingest_samples`)."""
    stem = path.stem if hasattr(path, "stem") else path.rsplit("/", 1)[-1].rsplit(".", 1)[0]
    return parse_activity_ref(stem)
