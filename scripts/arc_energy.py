#!/usr/bin/env python3
"""Dépense énergétique brute d'une séance course à pied — modèle RE3 + marche.

## Pourquoi un contrôle indépendant, pas un remplacement de Garmin

Garmin (`calories_kcal`) reste la référence par défaut PARTOUT (bilan
nutrition, rapports, coach) — ce module n'a jamais vocation à la remplacer.
Il sert deux usages, décidés avec l'utilisateur avant cette histoire :

1. **Contrôle indépendant** : un écart marqué entre `calories_kcal` Garmin et
   la dépense recalculée ici depuis les échantillons FIT peut signaler un
   capteur défaillant (FC, foulée) ou une séance mal taguée (sport erroné) —
   jamais l'inverse, ce module ne « corrige » jamais Garmin. `DELTA_ALERT_PCT`
   (15 %) définit un SEUIL de signalement (`delta_flag`) ; ce module ne pousse
   RIEN lui-même vers un rapport ou une alerte affichée — c'est aux étapes
   suivantes (CLI, agents) d'en faire quelque chose.
2. **Outil de PRÉVISION** : `energy_from_profile` sert de brique à
   `course-strategist` pour estimer, AVANT la course, la
   dépense d'un plan de course par segment. Il est conçu pour consommer la
   SORTIE RÉELLE d'`arc_race_pacing.predict_segments` (`predicted_time_s` par
   scénario), pas seulement un format `{distance_m, grade, speed_ms}`
   simplifié — voir la section dédiée plus bas et
   `ASSUMPTIONS["race_pacing_integration"]`.

## Le modèle (trois régimes, deux frontières de vitesse)

- **Course** (vitesse >= `WALK_SPEED_MS`, 1,8 m/s) : équation RE3 — **Looney
  DP, Hoogkamer W & Kram R (2025)**, « Metabolic energy expenditure during
  level, uphill, and downhill running », *bioRxiv*,
  doi: 10.1101/2025.06.05.658094 (Eq. 4) — publiée depuis dans *Eur J Appl
  Physiol* 126:1621–1633, doi: 10.1007/s00421-025-05999-5 (vérifié via
  Crossref, mêmes auteurs D. P. Looney, W. Hoogkamer, R. Kram) :

      P (W/kg, brut) = 4.43 + 1.51·v + 0.37·v²
                        + 30.43·v·g·(1 − 1.133^(1 − 1.056^(100·g + 43)))

  `v` en m/s, `g` en fraction signée (0,10 = 10 % de montée). Puissance
  **brute** (métabolisme de base compris), directement comparable à
  `calories_kcal` Garmin — voir `docs/marques.md`. La RE3 elle-même intègre
  déjà le coût du métabolisme debout : Looney et al. (2025) écrivent l'avoir
  ajouté depuis **Looney DP, Potter AW, Pryor JL, Bremner PE, Chalmers CR,
  McClung HL, Welles AP & Santee WR (2019)**, « Metabolic Costs of Standing
  and Walking in Healthy Military-Age Adults: A Meta-regression », *Med Sci
  Sports Exerc* 51(2):346–351, valeur **1,44 W/kg** (vérifiée directement dans
  le texte de l'article RE3, pas une reprise non sourcée) — voir
  `STANDING_POWER_W_KG`, réutilisée pour la marche/l'arrêt pour rester
  cohérente avec le régime course.

- **Marche** (`STOPPED_SPEED_MS` <= vitesse < `WALK_SPEED_MS`) : polynôme
  MARCHE de **Minetti AE et al. (2002)**, *J Appl Physiol* 93:1039–1046 (même
  article que le polynôme COURSE utilisé par `arc_gap.py` pour le GAP —
  l'étude, dont le titre couvre explicitement « walking and running »,
  fournit les deux polynômes) :

      Cw(i) = 280.5 i^5 − 58.7 i^4 − 76.8 i^3 + 51.9 i^2 + 19.6 i + 2.5   (J/kg/m, net)
      P (W/kg, brut) = Cw(i)·v + STANDING_POWER_W_KG

- **Arrêt** (vitesse < `STOPPED_SPEED_MS`, 0,3 m/s — ravitaillement, feu
  rouge, pause) : `STANDING_POWER_W_KG` seul, aucun coût de déplacement.

Le coût métabolique d'une montée n'est **jamais** compensé par le gain
symétrique d'une descente à la même pente (même mise en garde que
`arc_gap.ASSUMPTIONS["model"]`) : cette non-linéarité est précisément
pourquoi ce module intègre la dépense **par échantillon/segment**, jamais sur
une pente moyenne de toute la séance.

## Pente bornée, jamais extrapolée — bornage DIFFÉRENT par régime

`RUN_GRADE_CLAMP` (±0,30, **approximation du projet**) borne la pente avant
d'entrer dans la RE3. Looney et al. (2025) précisent avoir eux-mêmes couvert
une plage **−0,45 à +0,82** (vérifié directement dans le texte de l'article :
« estimating Ṁ across an extreme range of downhill and uphill grades (−0.45
to 0.82) ») — notre borne à ±0,30 est donc délibérément plus CONSERVATRICE que
la plage réellement étudiée (le trail réel dépasse rarement ±30 % sur des
segments significatifs, et une pente extrême reste le plus souvent un artefact
GPS/baro plutôt qu'un vrai terrain) — un choix de projet documenté, pas une
limite du modèle source.

`WALK_GRADE_CLAMP` (±0,45) borne la pente avant d'entrer dans le polynôme
MARCHE de Minetti et al. (2002) : cette borne, elle, reprend EXACTEMENT la
plage étudiée par l'article (même étude que la borne `arc_gap.CLAMP_GRADE`
côté course, le titre de l'article couvrant les deux allures jusqu'à ±45 %).

## Segmentation : réutilise `arc_elevation`, jamais une seconde implémentation

La pente est calculée par `arc_elevation.grade_series` — **jamais une
différence brute entre deux échantillons de 5 s** (voir la docstring de ce
module pour la justification complète du lissage/de la fenêtre). Ce module
appelle `grade_series` avec `window_m=SEGMENT_M` (50 m, **décision de
projet** — c'est la fenêtre utilisée par le script de validation de
référence contre 7 séances réelles, `SEG_M` de `validate_calories.py`, choisi
plus fin que la fenêtre par défaut du GAP (30 m) pour capter des ruptures de
pente plus courtes, pertinentes à l'échelle d'un calcul énergétique) —
jamais une seconde implémentation du lissage/de la segmentation de pente : un
trou de signal n'est, ici non plus, jamais traversé (`max_gap_s`, même
paramètre qu'`arc_elevation`/`arc_gap`).

## Intégration temporelle : le `dt` RÉEL à l'intérieur d'un segment, jamais capé

**Correctif important** (revue de code, 1ʳᵉ passe) : une version antérieure de
ce module plafonnait `dt` à `resolution_s` (5 s) pour CHAQUE échantillon, y
compris à l'intérieur d'un même segment contigu. Sur un enregistrement Garmin
en « enregistrement intelligent » (pas variable, parfois 8-12 s entre deux
points), ce plafond sous-comptait systématiquement l'énergie (jusqu'à -38 %
observé à un pas de 12 s) — une énergie n'est PAS une moyenne pondérée par le
temps (où capper `dt` à une fenêtre nominale a du sens, voir
`arc_gap.weighted_average`), c'est une INTÉGRALE : il faut le temps RÉEL
pendant lequel une puissance a été soutenue, jamais une fenêtre nominale
tronquée.

`arc_elevation.segments_by_gap` garantit déjà, PAR CONSTRUCTION, qu'à
l'intérieur d'un même segment contigu, l'écart entre deux `t_s` consécutifs
est **toujours** <= `max_gap_s` (c'est le critère même de la segmentation) :
le `dt` réel vers l'échantillon suivant peut donc être intégré TEL QUEL, sans
aucun plafond, dans ce cas. Seul le DERNIER échantillon d'un segment (pas de
suivant avant la fin du segment/de la séance) pèse `resolution_s` — sa propre
fenêtre nominale, faute de savoir combien de temps il a réellement duré après
la dernière mesure. Le résultat expose :

- `counted_s` : la somme de tous les `dt` réellement intégrés (tous régimes,
  arrêt compris) — jamais tronquée par un plafond arbitraire.
- `gap_s` : la somme des trous de signal, DÉDUCTION FAITE de `resolution_s`
  par trou (la fenêtre nominale du dernier échantillon AVANT le trou est déjà
  comptée dans `counted_s` — la retrancher évite de compter ces secondes
  deux fois) — jamais traversés, jamais intégrés comme si une puissance y
  avait été soutenue.
- `excluded_s` : secondes ni comptées ni traitées comme un trou — un
  échantillon sans vitesse exploitable NI vitesse inférée depuis la distance
  (voir `ASSUMPTIONS["missing_speed"]`).

## Classification marche/course : vitesse LISSÉE, jamais l'instantané brut

Un bruit de mesure de quelques cm/s autour de `WALK_SPEED_MS` (1,8 m/s) ferait
sinon basculer un même passage entre les deux régimes d'un échantillon de 5 s
à l'autre (discontinuité de puissance ≈ 5,9 -> 8,3 W/kg sur le plat à ce
seuil) — la DÉCISION de régime (marche/course/arrêt) se fait donc sur une
vitesse lissée sur `SPEED_SMOOTH_TAPS` échantillons voisins (même mécanisme
que `arc_elevation.smooth_moving_average`, réutilisé tel quel), la PUISSANCE
elle-même restant calculée sur la vitesse RÉELLE (non lissée) de l'échantillon
— voir `ASSUMPTIONS["classification_smoothing"]`.

## API pure, réutilisable

- `re3_power_w_kg(speed_ms, grade)` / `walk_power_w_kg(speed_ms, grade)` :
  puissance brute (W/kg) d'un régime donné — **linéaires en masse**,
  l'appelant multiplie par `weight_kg` (voir `ASSUMPTIONS["mass_linearity"]`,
  utile pour ajouter le poids d'un sac/de flasques sans toucher au module).
- `energy_from_samples(samples, weight_kg, ...)` : dépense MESURÉE d'une
  séance déjà réalisée, à partir de ses échantillons normalisés
  (`arc_samples.normalise_records`) — brique de la table dérivée
  `activity_energy` (`scripts/arc_index.py::compute_metrics`).
- `energy_from_profile(segments, weight_kg, ...)` : dépense PRÉVUE d'un plan
  de course — accepte le format simple `{distance_m, grade, speed_ms}`, le
  profil point par point `_profile`/`profile` (format
  `arc_race_pacing.segment_course`), ET la sortie RÉELLE de
  `arc_race_pacing.predict_segments` (`predicted_time_s` par scénario, voir
  `ASSUMPTIONS["race_pacing_integration"]`) — brique de l'intégration à
  `course-strategist` (`scripts/arc_race_pacing.py`, agent `course-strategist`).
- `delta_pct(model_kcal, garmin_kcal)` / `delta_flag(delta)` : écart
  modèle-vs-Garmin et seuil de signalement (`DELTA_ALERT_PCT`, 15 % —
  décision validée avec l'utilisateur), constante nommée UNIQUE (jamais un
  seuil en dur ailleurs dans le moteur).

Pas d'accès disque, pas de SQLite ici (CONTRIBUTING.md, stdlib uniquement) :
l'ingestion dérivée (table `activity_energy`) et le CLI (`arc_index.py
energy`) viendront dans une étape séparée — voir le docstring de
`arc_samples.py` pour la même séparation de responsabilités (moteur pur vs
ingestion/CLI).

## Calibration personnelle — PRÉVISIONS uniquement, jamais les mesures

`calibration_band_report(ratios)` calcule, à partir d'une liste de ratios
`garmin_kcal / model_kcal` déjà filtrée par l'appelant SUR LE SEUL panier
(route/trail — voir `arc_index.energy_calibration`, qui reste seule
responsable de la requête SQLite et du filtrage par panier, ce module ne sait
rien d'une séance ni d'un sport) — MAIS PAS sur `flag` (voir plus bas), un
facteur de correction personnel : `n`, la médiane du ratio, sa dispersion
(IQR, écart interquartile), et un statut :

- `insufficient` (`n < CALIBRATION_MIN_N`, 15 — approximation du projet,
  aucune base statistique publiée pour ce seuil précis) : facteur `1.0`,
  jamais appliqué faute d'un échantillon suffisant.
- `not_needed` (médiane à `CALIBRATION_NOT_NEEDED_BAND_PCT` % (5 %) ou moins de
  1.0) : le modèle est déjà fidèle sur ce panier, facteur `1.0` — une
  calibration qui ne ferait que reproduire du bruit de mesure serait pire
  qu'inutile (fausse précision).
- `applied` (médiane hors de cette bande, ET `n` suffisant) : facteur = la
  médiane elle-même, BORNÉE à `[CALIBRATION_FACTOR_MIN, CALIBRATION_FACTOR_MAX]`
  (0.8-1.2 — approximation du projet documentée : un facteur hors de cette
  plage signalerait plus probablement un problème de saisie/poids qu'un vrai
  biais du modèle, jamais extrapolé au-delà).

**Exclusion des aberrantes, RELATIVE à la médiane du panier — jamais au
`flag` par séance** (correctif de revue de code, BLOQUANT) : exclure les
séances dont `arc_energy.delta_flag` vaut `True` (écart ABSOLU modèle/Garmin
> `DELTA_ALERT_PCT`, 15 %) AVANT de calculer le ratio bride mathématiquement
le ratio médian atteignable à environ `[1/1.15, 1.15]` — un biais RÉEL et
cohérent de 12-20 % (chaque séance dépasse alors le seuil PAR SÉANCE, mais
le panier entier n'a rien d'aberrant) tombait à tort en `insufficient`, les
bornes 0.8-1.2 devenant inatteignables. `calibration_band_report` calcule
donc lui-même une PREMIÈRE médiane sur TOUS les ratios reçus, puis exclut
UNIQUEMENT ceux dont l'écart relatif à cette médiane dépasse
`CALIBRATION_OUTLIER_RELATIVE_BAND_PCT` (15 %, approximation du projet,
mécanisme VOLONTAIREMENT DIFFÉRENT de `DELTA_ALERT_PCT` même s'ils partagent
le même ordre de grandeur) — la médiane/l'IQR/le facteur FINAUX sont
recalculés sur les ratios RETENUS. `arc_energy.delta_flag`/`DELTA_ALERT_PCT`
restent réservés à l'alerte affichée sur UNE séance individuelle, jamais
réutilisés pour la calibration d'un panier entier.

Le ratio est **Garmin / modèle** (jamais l'inverse) : un facteur > 1 signifie
que le modèle SOUS-estime Garmin sur ce panier (le kcal brut doit être
MULTIPLIÉ par le facteur pour s'en rapprocher), un facteur < 1 qu'il le
SUR-estime — voir `arc_race_pacing.race_energy_forecast`, seul consommateur
prévu de ce facteur, qui l'applique en multipliant `kcal`/`kcal_per_h` PAR
SCÉNARIO ET PAR SEGMENT (`kcal_calibrated`, `kcal_per_h_calibrated`,
`cumulative_kcal_calibrated`), à CÔTÉ des valeurs brutes, jamais à leur
place — le facteur étant un scalaire UNIQUE par scénario, l'appliquer
uniformément à chaque segment reste exact (linéarité, voir
`ASSUMPTIONS["mass_linearity"]` pour le même principe côté masse).

**Jamais appliquée à une séance déjà mesurée** (`activity_energy`/
`energy_report`/`energy_trend` restent le calcul BRUT du modèle, sans aucune
correction) : la calibration est un outil de PRÉVISION (corriger une future
estimation à partir de l'historique de l'athlète), jamais une réécriture
rétroactive d'une mesure déjà faite — une mesure reste une mesure, même
imparfaite.
"""

from __future__ import annotations

import math
import statistics
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
import arc_elevation as E  # noqa: E402

# ---------------------------------------------------------------------------
# Constantes nommées — voir le docstring du module pour la source de chacune.
# ---------------------------------------------------------------------------

J_PER_KCAL = 4184.0

# Coefficients RE3 (Looney DP, Hoogkamer W & Kram R, 2025, bioRxiv
# 10.1101/2025.06.05.658094, Eq. 4 ; publiée depuis dans Eur J Appl Physiol
# 126:1621-1633, doi 10.1007/s00421-025-05999-5) :
# P (W/kg, brut) = A + B·v + C·v² + D·v·g·(1 − E^(1 − F^(100·g + G))).
RE3_A = 4.43
RE3_B = 1.51
RE3_C = 0.37
RE3_D = 30.43
RE3_E = 1.133
RE3_F = 1.056
RE3_G = 43.0

# Coefficients du polynôme MARCHE de Minetti et al. 2002 (J Appl Physiol
# 93:1039-1046), i^5 -> i^0, coût NET en J/kg/m — le polynôme MARCHE de l'article
# (le polynôme COURSE servait à l'ancien GAP, remplacé par Kay 2012, voir docs/gap.md).
MINETTI_WALK_COEFFS = (280.5, -58.7, -76.8, 51.9, 19.6, 2.5)

# Seuil marche/course (m/s) — décision de projet, cohérent avec le script de
# validation de référence (`validate_calories.py::WALK_V`) : en dessous, un
# segment est considéré marché (polynôme MARCHE), pas couru (RE3).
WALK_SPEED_MS = 1.8

# Seuil d'arrêt (m/s) — décision de projet (`validate_calories.py`) : en
# dessous, un segment est traité comme un arrêt (ravitaillement, feu rouge),
# métabolisme debout seul, aucun coût de déplacement.
STOPPED_SPEED_MS = 0.3

# Métabolisme « debout » (W/kg) — Looney DP et al. (2019a), « Metabolic Costs
# of Standing and Walking in Healthy Military-Age Adults: A Meta-regression »,
# Med Sci Sports Exerc 51(2):346-351 — valeur CITÉE TELLE QUELLE par la RE3
# (Looney et al. 2025, vérifiée dans le texte de l'article : « we added the
# generalized standing Ṁ determined by Looney et al. (2019a) (1.44 W·kg⁻¹) »).
# Réutilisée pour la marche/l'arrêt (voir docstring du module) pour rester
# cohérente avec le régime course, qui l'intègre déjà.
STANDING_POWER_W_KG = 1.44

# Borne de pente COURSE (fraction signée) avant d'entrer dans la RE3 —
# approximation du projet, délibérément plus conservatrice que la plage
# RÉELLEMENT étudiée par Looney et al. 2025 (-0,45 à +0,82, vérifiée dans le
# texte de l'article) — voir docstring du module.
RUN_GRADE_CLAMP = 0.30

# Borne de pente MARCHE — reprend la plage ÉTUDIÉE par Minetti et al. 2002
# (même article que `arc_gap.CLAMP_GRADE`, jusqu'à ±45 %, titre de l'article :
# « extreme uphill and downhill slopes », walking ET running) — voir docstring
# du module.
WALK_GRADE_CLAMP = 0.45

# Bande de pente (fraction signée) traitée comme un PLAT en régime course —
# approximation du projet : un bruit de pente de quelques dixièmes de point
# (`arc_elevation.ASSUMPTIONS["noise_robustness"]`) ne doit jamais faire
# basculer une décomposition flat/uphill/downhill sur une route quasiment
# plate — sans cette bande, `grade == 0.0` exactement n'arrivait presque
# jamais en pratique (bruit de mesure), rendant la catégorie "flat" absurde
# (quasi vide) sur une séance réelle.
FLAT_GRADE_BAND = 0.02

# Nombre d'échantillons voisins lissés (moyenne glissante,
# `arc_elevation.smooth_moving_average`) pour la SEULE décision de régime
# marche/course/arrêt — jamais pour la puissance elle-même (voir docstring du
# module, "Classification marche/course"). Approximation du projet : à la
# résolution nominale de 5 s, 5 échantillons couvrent 25 s, un ordre de
# grandeur comparable à `SEGMENT_M` (50 m) à une allure d'endurance
# (~2,5-3 m/s) — pas une équivalence exacte fenêtre de distance/fenêtre de
# temps, juste un lissage du même ordre de grandeur.
SPEED_SMOOTH_TAPS = 5

# Fenêtre de segmentation/pente (m) passée à `arc_elevation.grade_series` —
# décision de projet, voir le docstring du module (fenêtre du script de
# validation de référence, plus fine que celle par défaut du GAP).
SEGMENT_M = 50.0

# Aligné sur `arc_samples.DEFAULT_RESOLUTION_S` : résolution nominale des
# échantillons sous-échantillonnés lus depuis `arc_index.samples`.
DEFAULT_RESOLUTION_S = 5.0

# Seuil de signalement d'écart modèle vs Garmin (%) — décision validée avec
# l'utilisateur, constante nommée UNIQUE (une seule source de vérité, jamais
# un seuil en dur ailleurs).
DELTA_ALERT_PCT = 15.0

# Taille d'échantillon minimale (nombre de séances) pour appliquer une
# calibration personnelle (voir la section « Calibration personnelle » du
# docstring du module) — approximation du projet, aucune base statistique
# publiée identifiée pour ce seuil précis, choisi assez petit pour rester
# atteignable sur une fenêtre de calibration réaliste (CALIBRATION_WINDOW_WEEKS),
# assez grand pour ne pas calibrer sur 2-3 séances bruitées.
CALIBRATION_MIN_N = 15

# Bande (%) autour de 1.0 (ratio Garmin/modèle) sous laquelle la calibration
# est jugée « pas nécessaire » (`status="not_needed"`, facteur laissé à 1.0)
# plutôt qu'appliquée — approximation du projet : reproduire du bruit de
# mesure par un facteur de calibration serait une fausse précision, pas une
# vraie correction.
CALIBRATION_NOT_NEEDED_BAND_PCT = 5.0

# Bande (%) d'exclusion des ratios ABERRANTS, RELATIVE à la médiane BRUTE de
# TOUS les ratios du panier (jamais au `flag` par séance, voir
# `calibration_band_report` — correctif de revue de code, BLOQUANT : exclure
# sur `flag` bride le ratio médian atteignable à environ [1/1.15, 1.15] et fait
# tomber en `insufficient` un biais réel et cohérent, chaque séance dépassant
# le seuil d'alerte PAR SÉANCE alors que le panier entier n'a rien d'aberrant).
# Approximation du projet, même ordre de grandeur que `DELTA_ALERT_PCT` mais un
# mécanisme VOLONTAIREMENT DIFFÉRENT et INDÉPENDANT : celui-ci exclut une
# MINORITÉ de ratios qui s'écarte du gros du panier (ex. un capteur clairement
# défaillant, ratio 2.0 au milieu d'un panier à 1.10-1.30), jamais tout un
# panier dont la médiane s'écarte franchement de 1.0.
CALIBRATION_OUTLIER_RELATIVE_BAND_PCT = 15.0

# Plage prudente (fraction) dans laquelle le facteur de calibration est borné
# quand il est appliqué — approximation du projet : un ratio médian hors de
# cette plage signalerait plus probablement un poids erroné/une séance mal
# taguée qu'un vrai biais du modèle sur ce panier, jamais extrapolé au-delà.
CALIBRATION_FACTOR_MIN = 0.8
CALIBRATION_FACTOR_MAX = 1.2

# Fenêtre glissante (semaines) de la calibration personnelle — INDÉPENDANTE de
# `ENERGY_TREND_WEEKS` (12, `arc_index.py`, plus courte, pensée pour un
# graphique de tendance récent) : 26 semaines (~6 mois), approximation du
# projet, pour suivre l'évolution de la forme/du capteur de l'athlète sans
# être trop sensible aux quelques dernières séances seules.
CALIBRATION_WINDOW_WEEKS = 26

# Scénario par défaut consommé depuis `arc_race_pacing.predict_segments`
# (clé de `predicted_time_s`/`SCENARIOS`) — "realistic" est le scénario
# central (médiane/interpolation, ni le plus prudent "safe" ni le plus
# optimiste "ambitious"), le choix par défaut le plus représentatif pour une
# estimation de dépense énergétique de plan de course.
DEFAULT_SCENARIO = "realistic"

# Identifiant de version du modèle, pour la traçabilité : toute
# évolution future des coefficients/seuils DOIT incrémenter ce suffixe, pour
# qu'une dépense déjà calculée et persistée (`activity_energy.model_id`) reste
# distinguable d'une dépense recalculée avec un modèle révisé. Incrémenté en /2 (revue de
# code, 1ʳᵉ passe) : `STANDING_POWER_W_KG` (1,4 -> 1,44), bornage de pente par
# régime, bande de plat, lissage de classification et intégration temporelle
# réelle changent tous le résultat numérique d'une même séance.
MODEL_ID = "re3-walk/2"

# Catégories de la décomposition temps/kcal (voir `energy_from_samples`) —
# ordre stable, utilisé pour initialiser le dict à zéro plutôt que de laisser
# une clé absente selon les données rencontrées.
BREAKDOWN_CATEGORIES = ("flat", "uphill", "downhill", "walk", "stopped")


ASSUMPTIONS = {
    "model": (
        "Trois régimes selon la vitesse LISSÉE de l'échantillon/segment (voir "
        "ASSUMPTIONS['classification_smoothing']) : COURSE (>= WALK_SPEED_MS, 1,8 m/s) via "
        "l'équation RE3 (Looney DP, Hoogkamer W & Kram R, 2025, bioRxiv 10.1101/2025.06.05.658094, "
        "Eq. 4 ; publiée depuis dans Eur J Appl Physiol 126:1621-1633, doi 10.1007/s00421-025-05999-5, "
        "qui intègre déjà le métabolisme debout de Looney et al. 2019a, 1,44 W/kg), MARCHE (entre "
        "STOPPED_SPEED_MS et WALK_SPEED_MS) via le polynôme marche de Minetti et al. (2002, J Appl "
        "Physiol 93:1039-1046, coût NET en J/kg/m) plus STANDING_POWER_W_KG. Sous STOPPED_SPEED_MS "
        "(0,3 m/s), seul le métabolisme debout est compté (arrêt, aucun coût de déplacement). "
        "Résultat BRUT (métabolisme de base compris), directement comparable à calories_kcal "
        "Garmin — jamais un calcul NET sans le soustraire explicitement (calories_bmr_kcal, quand "
        "connu)."
    ),
    "grade_clamp": (
        "Bornage DIFFÉRENT par régime (revue de code, 1ʳᵉ passe) : RUN_GRADE_CLAMP (±0,30) pour la "
        "RE3, délibérément plus conservateur que la plage RÉELLEMENT étudiée par Looney et al. "
        "2025 (-0,45 à +0,82, vérifiée dans le texte de l'article — approximation du projet quant "
        "au choix de la borne, PAS quant à la plage source, désormais citée avec exactitude) ; "
        "WALK_GRADE_CLAMP (±0,45) pour le polynôme marche de Minetti et al. 2002, qui reprend "
        "EXACTEMENT la plage étudiée par cet article (même source que `arc_gap.CLAMP_GRADE`, titre "
        "de l'article couvrant walking ET running jusqu'à ±45 %). Jamais une extrapolation non "
        "bornée sur une pente aberrante (capteur GPS/baro glitché)."
    ),
    "flat_band": (
        "Une pente dont la valeur absolue est sous FLAT_GRADE_BAND (0,02, approximation du projet) "
        "est classée « flat » en régime course, jamais « uphill »/« downhill » pour un bruit de "
        "mesure de quelques dixièmes de point — sans cette bande, `grade == 0.0` exactement "
        "n'arrive presque jamais sur une route réelle (bruit GPS/baro), rendant la catégorie "
        "« flat » de la décomposition quasiment toujours vide, même sur un profil objectivement "
        "plat."
    ),
    "classification_smoothing": (
        "La décision de régime (arrêt/marche/course) se fait sur une vitesse LISSÉE sur "
        "SPEED_SMOOTH_TAPS échantillons voisins (`arc_elevation.smooth_moving_average`, même "
        "mécanisme que le lissage d'altitude), jamais sur la vitesse instantanée brute : un bruit "
        "de quelques cm/s autour de WALK_SPEED_MS (1,8 m/s) ferait sinon basculer un même passage "
        "entre régimes d'un échantillon à l'autre (discontinuité de puissance ≈ 5,9 -> 8,3 W/kg sur "
        "le plat à ce seuil). La PUISSANCE elle-même reste calculée sur la vitesse RÉELLE "
        "(non lissée) de l'échantillon — seule la CATÉGORIE (et donc le régime/la formule "
        "appliquée) dépend du lissage. Approximation de projet : un lissage par NOMBRE "
        "d'échantillons voisins (temporel), pas une fenêtre de distance ~50 m équivalente à "
        "`SEGMENT_M` comme pour la pente — les deux mécanismes ne sont PAS mathématiquement "
        "équivalents, seulement du même ordre de grandeur à une allure d'endurance typique."
    ),
    "segmentation": (
        "La pente est calculée par `arc_elevation.grade_series`, appelée avec `window_m=SEGMENT_M` "
        "(50 m — décision de projet, fenêtre du script de validation de référence contre 7 séances "
        "réelles, plus fine que la fenêtre par défaut du GAP à 30 m) : jamais une seconde "
        "implémentation du lissage d'altitude ou de la segmentation par trou de signal "
        "(`max_gap_s`), toutes deux déjà partagées par `arc_gap.py`. Un trou de signal n'est "
        "jamais traversé, ni par le calcul de pente, ni par l'intégration temporelle ci-dessous."
    ),
    "time_weighting": (
        "L'énergie est une INTÉGRALE dans le temps, pas une moyenne pondérée : à l'intérieur d'un "
        "même segment contigu (`arc_elevation.segments_by_gap`, qui garantit par construction un "
        "écart <= max_gap_s entre deux échantillons consécutifs du même segment), le `dt` RÉEL vers "
        "l'échantillon suivant est intégré TEL QUEL, jamais plafonné à `resolution_s` — un plafond "
        "systématique sous-comptait l'énergie sur un enregistrement à pas variable > 5 s "
        "(« enregistrement intelligent » Garmin, jusqu'à -38 % observé à un pas de 12 s, revue de "
        "code, 1ʳᵉ passe). Seul le DERNIER échantillon d'un segment (pas de suivant avant la fin du "
        "segment/de la séance) pèse `resolution_s` — sa propre fenêtre nominale, faute de savoir "
        "combien de temps il a réellement duré après la dernière mesure. `counted_s` (résultat) "
        "somme tous les `dt` réellement intégrés ; `gap_s` somme les trous de signal, DÉDUCTION "
        "FAITE de `resolution_s` par trou (déjà compté dans `counted_s` via la fenêtre nominale du "
        "dernier échantillon avant le trou — jamais compté deux fois) — jamais traversés, jamais "
        "intégrés comme si une puissance y avait été soutenue."
    ),
    "missing_speed": (
        "Un échantillon sans `speed_ms` exploitable retombe D'ABORD sur une vitesse INFÉRÉE "
        "(Δdistance_m / Δt vers l'échantillon suivant du même segment, voir `_inferred_speed_ms`) "
        "avant d'être exclu — une vitesse manquante n'implique pas une distance manquante (capteur "
        "de vitesse GPS bruité, distance cumulée déjà fiable). Seulement si NI la vitesse mesurée "
        "NI cette inférence ne sont possibles (distance elle-même manquante, ou échantillon en fin "
        "de segment sans suivant), l'échantillon est EXCLU de l'intégration (ni temps ni énergie "
        "comptés pour lui, `excluded_s` du résultat compte ces secondes séparément) — jamais compté "
        "comme un arrêt inventé (vitesse 0 supposée) ni comme une vitesse de course inventée. "
        "Cohérent avec le reste du projet : une mesure absente reste absente, jamais remplacée par "
        "une valeur par défaut arbitraire quand aucune inférence fiable n'existe."
    ),
    "missing_elevation": (
        "Un échantillon sans pente calculable (altitude absente localement, ou séance ENTIÈRE sans "
        "altitude) est traité comme un PLAT explicite (grade = 0), jamais comme une énergie `None` "
        "qui ferait disparaître silencieusement sa contribution (même choix que "
        "`arc_race_pacing.ASSUMPTIONS['missing_elevation']` pour la prédiction de course). Le champ "
        "`elevation_missing_s` du résultat compte ces secondes séparément, et `elevation_missing` "
        "(bool) signale une séance ENTIÈREMENT sans altitude exploitable — jamais une confiance "
        "égale à une pente réellement mesurée."
    ),
    "mass_linearity": (
        "La RE3 comme le polynôme marche sont LINÉAIRES en masse (puissance en W/kg, multipliée "
        "par `weight_kg` une seule fois) : `energy_from_profile` accepte `weight_kg` comme un "
        "simple paramètre scalaire, jamais une constante figée dans le module, précisément pour "
        "qu'un appelant futur (sac/flasques de course) puisse y ajouter la masse portée sans "
        "toucher à ce module — passer `weight_kg + poids_sac_kg` suffit, le modèle physique reste "
        "inchangé."
    ),
    "no_exception": (
        "Aucune fonction de ce module ne lève d'exception sur une entrée incomplète : "
        "`energy_from_samples`/`energy_from_profile` rendent `None` si `weight_kg` est absent ou "
        "non positif (rien de calculable sans masse), ou un résultat à zéro avec un motif "
        "(`reason`/`reason_code`) si les échantillons/segments sont vides — jamais une "
        "`ZeroDivisionError`, un `TypeError` ou une `IndexError` remontée à l'appelant. Un profil "
        "`_profile`/`profile` malformé (élément qui n'est pas une paire, distance non numérique) "
        "est ignoré ÉLÉMENT PAR ÉLÉMENT, jamais une exception qui ferait échouer tout le segment."
    ),
    "race_pacing_integration": (
        "`arc_race_pacing.predict_segments` ne rend NI `speed_ms` NI `_profile` par segment "
        "(`_profile` est une clé PRIVÉE de `segment_course`, explicitement retirée par "
        "`predict_segments` avant l'export public — voir sa docstring) : seul `predicted_time_s` "
        "(dict par scénario `SCENARIOS = ('safe', 'realistic', 'ambitious')`) est exposé. "
        "`energy_from_profile` accepte donc, PAR ORDRE DE PRIORITÉ par segment : (1) `speed_ms` "
        "explicite (format simple, tests) ; (2) `time_s` explicite ; (3) `predicted_time_s[scenario]` "
        "(paramètre `scenario`, défaut `DEFAULT_SCENARIO`, 'realistic') — la vitesse effective du "
        "segment est alors `distance_m / time_s` (moyenne du segment, PAS une vitesse par "
        "sous-intervalle). Aucune vitesse résolue par aucune de ces trois voies -> "
        "`reason_code='no_speed'` pour ce segment (distance comptée, temps/énergie à zéro), jamais "
        "une exception ni un kcal=0 silencieux sans explication. Un appelant qui veut la précision "
        "point par point (terrain vallonné, voir `arc_race_pacing.ASSUMPTIONS['rolling_terrain']`) "
        "doit fournir la clé `_profile`/`profile` (conservée par l'appelant lui-même DEPUIS "
        "`segment_course`, avant l'appel à `predict_segments` qui la retire) EN PLUS de "
        "`predicted_time_s` — voir `_segment_intervals`. LIMITE CONNUE, documentée honnêtement : "
        "faute d'une vitesse par sous-intervalle (le temps du segment est un TOTAL, pas une série), "
        "`energy_from_profile` applique la MÊME vitesse moyenne du segment à chaque sous-intervalle "
        "du profil — seule la PENTE varie point par point (donc la puissance RE3/marche varie), la "
        "vitesse non. Ce n'est PAS une reproduction exacte de l'intégration `Δd / v(pente locale)` "
        "d'`arc_race_pacing.predict_segments` (qui, elle, fait varier la vitesse par "
        "sous-intervalle depuis le modèle personnel) — seulement une approximation qui capture "
        "quand même le surcoût réel d'une montée/descente locale sur un terrain vallonné, jamais "
        "la seule pente moyenne du segment."
    ),
    "delta_alert": (
        f"`DELTA_ALERT_PCT` ({DELTA_ALERT_PCT:.0f} %) définit le SEUIL utilisé par `delta_flag` "
        "pour signaler un écart entre la dépense recalculée ici et `calories_kcal` Garmin — "
        "décision validée avec l'utilisateur, constante nommée UNIQUE (une seule source de vérité, "
        "jamais un seuil en dur ailleurs dans le moteur). Ce module ne pousse RIEN lui-même vers un "
        "rapport ou une alerte affichée : `delta_flag` rend un booléen, c'est à l'appelant (étapes "
        "suivantes, CLI/agents) de décider quoi en faire. Un écart au-delà peut signaler un capteur "
        "défaillant ou une séance mal taguée — jamais une preuve que Garmin ou le modèle a tort en "
        "particulier : les deux sont des estimations, la comparaison est un signal, pas un verdict."
    ),
    "calibration": (
        f"Calibration PERSONNELLE, appliquée UNIQUEMENT aux PRÉVISIONS "
        f"(`arc_race_pacing.race_energy_forecast`), JAMAIS aux séances déjà mesurées "
        f"(`activity_energy`/`energy_report`/`energy_trend` restent le calcul BRUT du modèle, sans "
        f"aucune correction — une mesure reste une mesure). Ratio Garmin/modèle médian par panier "
        f"route/trail (`arc_index.energy_calibration`, randonnée/marche hors des deux paniers, même "
        f"regroupement qu'`ENERGY_TREND_ROUTE_TRAIL_BUCKET`), sur une fenêtre glissante de "
        f"CALIBRATION_WINDOW_WEEKS ({CALIBRATION_WINDOW_WEEKS:.0f} semaines, INDÉPENDANTE de la "
        f"fenêtre plus courte d'`energy_trend`). Exclusion des ratios ABERRANTS RELATIVE à la "
        f"médiane BRUTE du panier (`CALIBRATION_OUTLIER_RELATIVE_BAND_PCT`, 15 % — voir "
        f"`calibration_band_report`) — JAMAIS au `flag` par séance (`arc_energy.delta_flag`, "
        f"réservé à l'alerte PAR SÉANCE ABSOLUE) : exclure sur `flag` bride mathématiquement le "
        f"ratio médian atteignable à environ [1/1.15, 1.15] et fait tomber à tort en "
        f"`\"insufficient\"` un biais RÉEL et cohérent de 12-20 % du panier entier (correctif de "
        f"revue de code, BLOQUANT). `n < CALIBRATION_MIN_N` ({CALIBRATION_MIN_N:.0f}, compté APRÈS "
        f"exclusion des aberrantes) -> `status=\"insufficient\"`, facteur 1.0 (jamais appliqué faute "
        f"d'échantillon). Médiane à CALIBRATION_NOT_NEEDED_BAND_PCT % "
        f"({CALIBRATION_NOT_NEEDED_BAND_PCT:.0f} %) ou moins de 1.0 -> `status=\"not_needed\"`, "
        f"facteur 1.0 (calibrer sur du bruit de mesure serait une fausse précision). Sinon "
        f"`status=\"applied\"`, facteur = la médiane elle-même, BORNÉE à [CALIBRATION_FACTOR_MIN, "
        f"CALIBRATION_FACTOR_MAX] ({CALIBRATION_FACTOR_MIN:.1f}-{CALIBRATION_FACTOR_MAX:.1f}, "
        f"approximation du projet : un ratio hors de cette plage signale plus probablement un poids "
        f"erroné/une séance mal taguée qu'un vrai biais du modèle). Le facteur MULTIPLIE le kcal "
        f"BRUT (ratio Garmin/modèle : un facteur > 1 signifie que le modèle SOUS-estime Garmin sur "
        f"ce panier) pour rendre `kcal_calibrated`/`kcal_per_h_calibrated`/"
        f"`cumulative_kcal_calibrated`, PAR SCÉNARIO ET PAR SEGMENT (facteur scalaire unique, "
        f"application uniforme exacte par linéarité), TOUJOURS à CÔTÉ des valeurs brutes, jamais à "
        f"leur place — `status` insufficient/not_needed -> valeurs calibrées STRICTEMENT ÉGALES aux "
        f"brutes, jamais une différence silencieuse pour un facteur qui vaut justement 1.0."
    ),
}

# Résumé COURT (1-2 lignes) des hypothèses du modèle — pour la CLI
# (`arc_index.py energy`, sans `--assumptions`) : le détail complet
# (`ASSUMPTIONS`) coûte plusieurs Ko de JSON à chaque appel, inutile pour un
# agent qui liste juste des séances sans creuser le modèle. `--assumptions`
# rend `ASSUMPTIONS` en entier à la place de ce résumé — jamais les deux à la
# fois (voir `arc_index.energy_report`).
SUMMARY = (
    f"Modèle {MODEL_ID} : équation RE3 (course) + polynôme marche de Minetti (marche), résultat BRUT "
    f"comparable à calories_kcal Garmin — Garmin reste la référence, ce calcul est un CONTRÔLE INDÉPENDANT "
    f"(seuil de signalement |Δ| > {DELTA_ALERT_PCT:.0f} %) et un outil de PRÉVISION, jamais un remplacement. "
    "Voir --assumptions pour le détail complet des hypothèses."
)


# ---------------------------------------------------------------------------
# Puissance métabolique brute (W/kg).
# ---------------------------------------------------------------------------

def _clamp(grade: Optional[float], bound: float) -> float:
    """Pente bornée à ±`bound`, `None` traité comme un plat (0.0) — voir
    `ASSUMPTIONS["missing_elevation"]` (le marqueur d'altitude manquante vit au
    niveau de l'appelant, pas ici)."""
    if grade is None:
        return 0.0
    return max(-bound, min(bound, grade))


def re3_power_w_kg(speed_ms: float, grade: Optional[float]) -> float:
    """Puissance métabolique BRUTE de la course (W/kg) — équation RE3 (Looney,
    Hoogkamer & Kram, 2025, Eq. 4). `grade` (fraction signée) est bornée à
    ±`RUN_GRADE_CLAMP` avant évaluation (voir `ASSUMPTIONS["grade_clamp"]`),
    `None` traité comme un plat. `speed_ms` négative traitée comme `0.0`
    (jamais une puissance négative ou une extrapolation à reculons, qui n'a
    aucun sens physique ici)."""
    v = max(0.0, speed_ms)
    g = _clamp(grade, RUN_GRADE_CLAMP)
    return (RE3_A + RE3_B * v + RE3_C * v * v
            + RE3_D * v * g * (1 - RE3_E ** (1 - RE3_F ** (100 * g + RE3_G))))


def _minetti_walk_cost(grade: Optional[float]) -> float:
    """Coût NET de la marche (J/kg/m), polynôme de Minetti et al. 2002, pente
    bornée à ±`WALK_GRADE_CLAMP`."""
    g = _clamp(grade, WALK_GRADE_CLAMP)
    c5, c4, c3, c2, c1, c0 = MINETTI_WALK_COEFFS
    return c5 * g**5 + c4 * g**4 + c3 * g**3 + c2 * g**2 + c1 * g + c0


def walk_power_w_kg(speed_ms: float, grade: Optional[float]) -> float:
    """Puissance métabolique BRUTE de la marche (W/kg) : coût NET de Minetti
    et al. 2002 × vitesse, PLUS `STANDING_POWER_W_KG` (métabolisme debout) —
    voir `ASSUMPTIONS["model"]`. `speed_ms` négative traitée comme `0.0`
    (puissance debout seule, jamais négative)."""
    v = max(0.0, speed_ms)
    return _minetti_walk_cost(grade) * v + STANDING_POWER_W_KG


def _category_for(speed_ms: Optional[float], grade: Optional[float]) -> Optional[str]:
    """Catégorie de régime (`BREAKDOWN_CATEGORIES`) pour une vitesse DÉJÀ
    LISSÉE (voir `ASSUMPTIONS["classification_smoothing"]`) — `None` si
    `speed_ms` est inexploitable."""
    if speed_ms is None:
        return None
    if speed_ms < STOPPED_SPEED_MS:
        return "stopped"
    if speed_ms < WALK_SPEED_MS:
        return "walk"
    g = grade or 0.0
    if abs(g) < FLAT_GRADE_BAND:
        return "flat"
    return "uphill" if g > 0.0 else "downhill"


def _power_for_category(category: str, speed_ms: float, grade: Optional[float]) -> float:
    """Puissance BRUTE (W/kg) du régime `category`, sur la vitesse RÉELLE
    (non lissée) `speed_ms` — voir `ASSUMPTIONS["classification_smoothing"]`."""
    if category == "stopped":
        return STANDING_POWER_W_KG
    if category == "walk":
        return walk_power_w_kg(speed_ms, grade)
    return re3_power_w_kg(speed_ms, grade)


def _classify_and_power(speed_ms: Optional[float], grade: Optional[float]) -> Tuple[Optional[str], float]:
    """Catégorie et puissance BRUTE (W/kg) à partir d'UNE SEULE vitesse (pas de
    lissage disponible/pertinent — utilisé par `energy_from_profile`, où
    chaque segment ne porte qu'une vitesse moyenne, voir
    `ASSUMPTIONS["race_pacing_integration"]`) — `None` de catégorie si
    `speed_ms` est inexploitable, la puissance rendue est alors sans objet."""
    category = _category_for(speed_ms, grade)
    if category is None:
        return None, 0.0
    return category, _power_for_category(category, speed_ms, grade)


def _empty_breakdown() -> Dict[str, Dict[str, float]]:
    return {cat: {"seconds": 0.0, "kcal": 0.0} for cat in BREAKDOWN_CATEGORIES}


def _inferred_speed_ms(dist_a: Optional[float], dist_b: Optional[float], dt: float) -> Optional[float]:
    """Vitesse inférée (m/s) depuis une distance cumulée, `None` si l'une des
    deux distances manque ou si `dt` n'est pas positif (voir
    `ASSUMPTIONS["missing_speed"]`). Une distance qui recule légèrement
    (bruit GPS, voir `arc_elevation.grade_series`) rend une vitesse nulle,
    jamais négative."""
    if dist_a is None or dist_b is None or dt <= 0:
        return None
    return max(0.0, (dist_b - dist_a) / dt)


# ---------------------------------------------------------------------------
# Dépense MESURÉE — depuis les échantillons normalisés d'une séance réalisée.
# ---------------------------------------------------------------------------

def energy_from_samples(samples: Sequence[dict], weight_kg: Optional[float], *,
                         resolution_s: float = DEFAULT_RESOLUTION_S,
                         window_m: float = SEGMENT_M,
                         min_window_m: float = E.DEFAULT_MIN_GRADE_WINDOW_M,
                         max_gap_s: float = E.DEFAULT_MAX_GAP_S,
                         smooth_taps: int = E.DEFAULT_SMOOTH_TAPS,
                         speed_smooth_taps: int = SPEED_SMOOTH_TAPS) -> Optional[dict]:
    """Dépense énergétique BRUTE d'une séance déjà réalisée, à partir de ses
    échantillons NORMALISÉS (`arc_samples.normalise_records`, résolution 5 s
    par défaut dans l'index — voir `arc_samples.DEFAULT_RESOLUTION_S`).

    `weight_kg` absent ou non positif -> `None` (rien de calculable sans
    masse, voir `ASSUMPTIONS["no_exception"]`) — jamais une exception, jamais
    une masse par défaut inventée. `samples` vide -> un résultat à zéro avec
    `reason`/`reason_code` (`"no_samples"`), jamais `None` ni une exception
    (une séance sans échantillon FIT reste une séance valide, voir
    `arc_samples.py`, simplement sans ce KPI).

    Rend un dict :
    - `kcal` : dépense totale BRUTE (métabolisme de base compris).
    - `breakdown` : `{catégorie: {"seconds", "kcal"}}` pour chaque catégorie
      de `BREAKDOWN_CATEGORIES` (plat/montée/descente courus, marché, arrêt).
    - `moving_duration_s` : secondes hors arrêt (flat + uphill + downhill + walk).
    - `counted_s` : secondes RÉELLEMENT intégrées (tous régimes, arrêt
      compris) — voir `ASSUMPTIONS["time_weighting"]`.
    - `gap_s` : secondes de trous de signal jamais traversés (déduction faite
      de `resolution_s` par trou, déjà comptée dans `counted_s` — voir
      `ASSUMPTIONS["time_weighting"]`).
    - `excluded_s` : secondes ni comptées ni traitées comme un trou (vitesse
      inexploitable et non inférable, voir `ASSUMPTIONS["missing_speed"]`).
    - `elevation_missing` : `True` si AUCUN échantillon n'a de pente
      calculable (séance sans altitude exploitable, voir
      `ASSUMPTIONS["missing_elevation"]`).
    - `elevation_missing_s` : secondes où la pente était `None` (traitées
      comme un plat).
    - `model_id` : `MODEL_ID`, pour la traçabilité des versions du modèle.
    """
    if weight_kg is None or weight_kg <= 0:
        return None

    empty = {
        "kcal": 0.0, "breakdown": _empty_breakdown(), "moving_duration_s": 0.0,
        "counted_s": 0.0, "gap_s": 0.0, "excluded_s": 0.0,
        "elevation_missing": False, "elevation_missing_s": 0.0, "model_id": MODEL_ID,
    }
    if not samples:
        return {**empty, "reason": "aucun échantillon FIT ingéré pour cette séance", "reason_code": "no_samples"}

    series = E.grade_series(samples, window_m=window_m, min_window_m=min_window_m,
                             max_gap_s=max_gap_s, smooth_taps=smooth_taps)
    if not series:
        return {**empty, "reason": "aucun échantillon exploitable (t_s manquant partout)",
                "reason_code": "no_samples"}

    t_values = [s["t_s"] for s in series]
    breakdown = _empty_breakdown()
    total_kcal = 0.0
    grade_known_count = 0
    elevation_missing_s = 0.0
    counted_s = 0.0
    gap_s = 0.0
    excluded_s = 0.0

    segments = E.segments_by_gap(t_values, max_gap_s)
    for seg_i, segment in enumerate(segments):
        n = len(segment)
        # Vitesse lissée (décision de régime UNIQUEMENT, voir
        # ASSUMPTIONS["classification_smoothing"]) — lissage local au segment,
        # jamais à travers un trou de signal.
        raw_speeds = [series[idx].get("speed_ms") for idx in segment]
        smoothed_speeds = E.smooth_moving_average(raw_speeds, speed_smooth_taps)

        for local_i, idx in enumerate(segment):
            s = series[idx]
            t_s = s["t_s"]
            grade = s.get("grade")

            if local_i + 1 < n:
                dt = t_values[segment[local_i + 1]] - t_s  # RÉEL, jamais capé (déjà <= max_gap_s)
            else:
                dt = resolution_s  # dernier échantillon du segment : sa propre fenêtre nominale
            if dt <= 0:
                continue

            raw_speed = s.get("speed_ms")
            effective_speed = raw_speed
            if effective_speed is None and local_i + 1 < n:
                next_s = series[segment[local_i + 1]]
                effective_speed = _inferred_speed_ms(s.get("distance_m"), next_s.get("distance_m"),
                                                      t_values[segment[local_i + 1]] - t_s)
            if effective_speed is None:
                excluded_s += dt
                continue  # ni vitesse mesurée ni inférable : voir ASSUMPTIONS["missing_speed"]

            classify_speed = smoothed_speeds[local_i]
            if classify_speed is None:
                classify_speed = effective_speed
            category = _category_for(classify_speed, grade)
            if category is None:
                excluded_s += dt
                continue
            power_w_kg = _power_for_category(category, effective_speed, grade)

            if grade is not None:
                grade_known_count += 1
            elif category != "stopped":
                elevation_missing_s += dt

            counted_s += dt
            energy_j = power_w_kg * weight_kg * dt
            breakdown[category]["seconds"] += dt
            breakdown[category]["kcal"] += energy_j / J_PER_KCAL
            total_kcal += energy_j / J_PER_KCAL

        if seg_i + 1 < len(segments):
            next_segment = segments[seg_i + 1]
            # Le dernier échantillon AVANT le trou a déjà été compté sur sa
            # propre fenêtre nominale (`resolution_s`, voir `counted_s`
            # ci-dessus) : la retrancher évite de compter ces `resolution_s`
            # secondes deux fois (une fois dans `counted_s`, une fois dans
            # `gap_s`) — `gap_s` ne doit refléter que le silence RESTANT,
            # jamais déborder sur une fenêtre déjà attribuée.
            raw_gap = t_values[next_segment[0]] - t_values[segment[-1]]
            gap_s += max(0.0, raw_gap - resolution_s)

    moving_duration_s = sum(breakdown[c]["seconds"] for c in BREAKDOWN_CATEGORIES if c != "stopped")
    return {
        "kcal": total_kcal,
        "breakdown": breakdown,
        "moving_duration_s": moving_duration_s,
        "counted_s": counted_s,
        "gap_s": gap_s,
        "excluded_s": excluded_s,
        "elevation_missing": grade_known_count == 0,
        "elevation_missing_s": elevation_missing_s,
        "model_id": MODEL_ID,
    }


# ---------------------------------------------------------------------------
# Dépense PRÉVUE — depuis un profil de segments (plan de course).
# ---------------------------------------------------------------------------

def _segment_intervals(segment: dict) -> List[Tuple[float, Optional[float]]]:
    """Sous-intervalles `[(dx_m, grade), ...]` d'un segment. Réutilise la clé
    `_profile`/`profile` telle que produite par `arc_race_pacing.segment_course`
    quand présente (intégration point par point, voir
    `ASSUMPTIONS["race_pacing_integration"]` pour la limite connue — vitesse
    moyenne du segment appliquée à chaque sous-intervalle, seule la pente
    varie), sinon replie sur un unique intervalle `(distance_m, grade)`.

    Élément malformé (pas une paire `(dx, grade)`, `dx` non numérique) IGNORÉ
    individuellement, jamais une exception qui ferait échouer tout le segment
    (voir `ASSUMPTIONS["no_exception"]`).

    Duplication volontaire et minimale d'`arc_race_pacing._segment_intervals`
    (même principe qu'`arc_race_pacing.parse_gpx`/`haversine`, qui duplique
    délibérément le skill `gpx-analysis` plutôt que d'en dépendre) : ce module
    reste un moteur pur et FEUILLE (aucune dépendance à `arc_race_pacing`,
    qui lui-même importe `arc_metrics`/`arc_slope_model`/`coach_setup` et
    touche au disque via son CLI) — un import croisé introduirait soit un
    cycle, soit une dépendance lourde et inutile pour ~10 lignes de logique
    triviale."""
    profile = segment.get("profile") or segment.get("_profile")
    intervals: List[Tuple[float, Optional[float]]] = []
    if profile:
        for item in profile:
            try:
                dx, grade = item
                dx = float(dx)
            except (TypeError, ValueError):
                continue
            if dx > 0:
                intervals.append((dx, grade))
        if intervals:
            return intervals
    distance_m = segment.get("distance_m")
    try:
        distance_m = float(distance_m) if distance_m is not None else 0.0
    except (TypeError, ValueError):
        distance_m = 0.0
    grade = segment.get("grade")
    if grade is None and segment.get("grade_mean_pct") is not None:
        try:
            grade = float(segment["grade_mean_pct"]) / 100.0
        except (TypeError, ValueError):
            grade = None
    return [(distance_m, grade)]


def _segment_total_distance_m(segment: dict) -> float:
    """Distance totale (m) d'un segment, depuis son profil si présent (somme
    des `dx`, cohérente avec l'intégration point par point), sinon
    `distance_m` — jamais une exception sur une valeur non numérique."""
    profile = segment.get("profile") or segment.get("_profile")
    if profile:
        total = 0.0
        for item in profile:
            try:
                dx = float(item[0])
            except (TypeError, ValueError, IndexError):
                continue
            if dx > 0:
                total += dx
        if total > 0:
            return total
    try:
        return float(segment.get("distance_m") or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _as_positive_float(value) -> Optional[float]:
    """`value` en `float` strictement positif, `None` si le TYPE n'est pas
    numérique (`int`/`float`, jamais une chaîne comme `"3"` acceptée
    implicitement — un segment mal formé ne doit jamais faire lever
    d'exception, voir `ASSUMPTIONS["no_exception"]`, mais une valeur du
    mauvais type est un signal d'anomalie à ignorer, pas à convertir en
    silence), non fini (`NaN`/`inf`), ou non strictement positif."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not math.isfinite(value):
        return None
    return float(value) if value > 0 else None


def _resolve_segment_speed(segment: dict, scenario: str) -> Tuple[Optional[float], Optional[str]]:
    """Vitesse effective (m/s) d'un segment, PAR ORDRE DE PRIORITÉ — voir
    `ASSUMPTIONS["race_pacing_integration"]` : (1) `speed_ms` explicite (>0),
    (2) `time_s` explicite (>0) -> `distance_m / time_s`, (3)
    `predicted_time_s[scenario]` (sortie RÉELLE d'`arc_race_pacing.
    predict_segments`) -> `distance_m / predicted_time_s[scenario]`. Rend
    `(None, "no_speed")` si aucune des trois voies n'aboutit — jamais une
    vitesse inventée, jamais une `ZeroDivisionError`. Une valeur non
    numérique pour `speed_ms`/`time_s`/`predicted_time_s[scenario]` (type
    incorrect, ex. une chaîne) est simplement IGNORÉE (voie suivante essayée),
    jamais une exception (voir `_as_positive_float`)."""
    speed_ms = _as_positive_float(segment.get("speed_ms"))
    if speed_ms is not None:
        return speed_ms, None

    distance_m = _segment_total_distance_m(segment)
    time_s = _as_positive_float(segment.get("time_s"))
    if time_s is None:
        predicted_time_s = segment.get("predicted_time_s")
        if isinstance(predicted_time_s, dict):
            time_s = _as_positive_float(predicted_time_s.get(scenario))
    if time_s is not None and distance_m > 0:
        return distance_m / time_s, None
    return None, "no_speed"


def energy_from_profile(segments: Sequence[dict], weight_kg: Optional[float], *,
                         scenario: str = DEFAULT_SCENARIO) -> Optional[dict]:
    """Dépense énergétique BRUTE PRÉVUE d'un plan de course, à partir d'une
    liste de segments.

    Chaque segment est un dict qui porte, en plus de `distance_m` (ou
    `profile`/`_profile`, voir `_segment_intervals`), l'UNE de ces clés (par
    ordre de priorité, voir `_resolve_segment_speed`) :
    - `speed_ms` : vitesse prévue, constante sur le segment (format simple,
      tests) ;
    - `time_s` : temps total prévu pour le segment (vitesse dérivée) ;
    - `predicted_time_s` : dict par scénario (`{"safe", "realistic",
      "ambitious"}`), format exact rendu par `arc_race_pacing.
      predict_segments` — voir `scenario` (paramètre de cette fonction,
      défaut `DEFAULT_SCENARIO`) et `ASSUMPTIONS["race_pacing_integration"]`
      pour la limite connue (vitesse moyenne du segment, pas par
      sous-intervalle, même quand un `_profile` point par point est fourni).

    Aucune de ces clés exploitable -> `reason_code="no_speed"` PAR SEGMENT
    (distance comptée, temps/énergie à zéro pour ce segment SEULEMENT,
    jamais toute la fonction) — jamais un kcal=0 silencieux sans explication.

    `weight_kg` absent ou non positif -> `None` (voir
    `ASSUMPTIONS["no_exception"]`) — la masse est un simple PARAMÈTRE, jamais
    une constante figée ici (voir `ASSUMPTIONS["mass_linearity"]`) : un
    appelant futur peut y ajouter le poids d'un sac/de flasques sans
    modifier ce module. `segments` vide -> résultat à zéro avec `reason`.

    Rend un dict `{"segments": [...], "kcal", "time_s", "kcal_per_h",
    "scenario"}` : le détail par segment porte `id` (si fourni), `distance_m`,
    `time_s`, `kcal`, `kcal_per_h` (`None` si `time_s` nul, jamais une
    division par zéro), `reason_code` (`None` ou `"no_speed"`)."""
    if weight_kg is None or weight_kg <= 0:
        return None
    if not segments:
        return {"segments": [], "kcal": 0.0, "time_s": 0.0, "kcal_per_h": None, "scenario": scenario,
                "reason": "aucun segment fourni", "reason_code": "no_segments"}

    out_segments = []
    total_kcal = 0.0
    total_time_s = 0.0
    for seg in segments:
        speed_ms, reason_code = _resolve_segment_speed(seg, scenario)
        seg_kcal = 0.0
        seg_time_s = 0.0
        seg_distance_m = 0.0
        for dx, grade in _segment_intervals(seg):
            seg_distance_m += dx
            if speed_ms is None:
                continue  # pas de vitesse exploitable : distance comptée, temps/énergie non
            dt = dx / speed_ms
            _, power_w_kg = _classify_and_power(speed_ms, grade)
            energy_j = power_w_kg * weight_kg * dt
            seg_kcal += energy_j / J_PER_KCAL
            seg_time_s += dt

        total_kcal += seg_kcal
        total_time_s += seg_time_s
        out_segments.append({
            "id": seg.get("id"),
            "distance_m": seg_distance_m,
            "time_s": seg_time_s,
            "kcal": seg_kcal,
            "kcal_per_h": (seg_kcal / (seg_time_s / 3600.0)) if seg_time_s > 0 else None,
            "reason_code": reason_code,
        })

    return {
        "segments": out_segments,
        "kcal": total_kcal,
        "time_s": total_time_s,
        "kcal_per_h": (total_kcal / (total_time_s / 3600.0)) if total_time_s > 0 else None,
        "scenario": scenario,
    }


# ---------------------------------------------------------------------------
# Écart modèle vs Garmin.
# ---------------------------------------------------------------------------

def delta_pct(model_kcal: Optional[float], garmin_kcal: Optional[float]) -> Optional[float]:
    """Écart relatif (%) `(model_kcal - garmin_kcal) / garmin_kcal` — `None`
    si l'une des deux valeurs est inconnue, ou si `garmin_kcal` est nulle
    (division par zéro sans objet, jamais une exception)."""
    if model_kcal is None or not garmin_kcal:
        return None
    return (model_kcal - garmin_kcal) / garmin_kcal * 100.0


def delta_flag(delta_pct_value: Optional[float]) -> Optional[bool]:
    """`True` si `|delta_pct_value| > DELTA_ALERT_PCT` (voir
    `ASSUMPTIONS["delta_alert"]`) — `None` si l'écart lui-même est inconnu
    (jamais assimilé à « pas de signalement », voir
    `ASSUMPTIONS["no_exception"]`)."""
    if delta_pct_value is None:
        return None
    return abs(delta_pct_value) > DELTA_ALERT_PCT


# ---------------------------------------------------------------------------
# Calibration personnelle (prévisions uniquement) — voir la section dédiée du
# docstring du module et ASSUMPTIONS["calibration"].
# ---------------------------------------------------------------------------

def _median_and_iqr(values: Sequence[float]) -> Tuple[Optional[float], Optional[float]]:
    """Médiane et écart interquartile (méthode `"inclusive"`, cohérente avec
    une médiane calculée sur le MÊME jeu de valeurs — voir la documentation de
    `statistics.quantiles`) — `(None, None)` si `values` est vide, IQR `None`
    (pas seulement 0.0, qui laisserait croire à une dispersion mesurée nulle)
    si un seul point ne permet aucun quartile."""
    if not values:
        return None, None
    median = statistics.median(values)
    if len(values) < 2:
        return median, None
    q1, _, q3 = statistics.quantiles(values, n=4, method="inclusive")
    return median, q3 - q1


def calibration_band_report(ratios: Sequence[float], *, min_n: int = CALIBRATION_MIN_N,
                             band_pct: float = CALIBRATION_NOT_NEEDED_BAND_PCT,
                             outlier_band_pct: float = CALIBRATION_OUTLIER_RELATIVE_BAND_PCT,
                             factor_min: float = CALIBRATION_FACTOR_MIN,
                             factor_max: float = CALIBRATION_FACTOR_MAX) -> dict:
    """Calibration personnelle d'UN panier (route OU trail), à partir des
    ratios `garmin_kcal / model_kcal` de TOUTES les séances mesurables du
    panier sur la fenêtre — déjà filtrés par l'appelant SUR LE SEUL panier
    (route ou trail, voir `arc_index.energy_calibration`, seul appelant prévu),
    mais PAS sur `flag` (voir ci-dessous, correctif de revue de code). Fonction
    PURE, aucune connaissance d'un sport ou d'une date : `ratios` est une
    simple liste de nombres.

    **Exclusion des aberrantes, RELATIVE à la médiane BRUTE du panier — jamais
    au `flag` par séance** (correctif de revue de code, BLOQUANT) : une
    version antérieure excluait les séances dont `arc_energy.delta_flag`
    valait `True` (écart modèle/Garmin ABSOLU > `DELTA_ALERT_PCT`, 15 %) avant
    même de calculer un ratio — ce qui bride MATHÉMATIQUEMENT le ratio médian
    au panier `[0.870, 1.176]` environ (`1 / 1.15` à `1.15`), rendant les
    bornes `[factor_min, factor_max]` (0.8-1.2) inatteignables et faisant
    tomber en `"insufficient"` un biais RÉEL et cohérent de 12-20 % (chaque
    séance individuelle dépasse alors le seuil d'alerte PAR SÉANCE, mais le
    panier tout entier n'a RIEN d'aberrant : c'est justement ce que la
    calibration doit détecter). `arc_energy.delta_flag`/`DELTA_ALERT_PCT`
    restent RÉSERVÉS à l'alerte affichée sur une séance individuelle — jamais
    réutilisés ici. Le filtre appliqué ICI est différent : une PREMIÈRE
    médiane est calculée sur `ratios` en ENTIER, puis seuls les ratios dont
    l'écart RELATIF à CETTE médiane dépasse `outlier_band_pct` (15 %,
    approximation du projet — voir `ASSUMPTIONS["calibration"]`) sont exclus
    (typiquement une séance à capteur clairement défaillant, ex. ratio 2.0 au
    milieu d'un panier à 1.10-1.30) ; la médiane/IQR/facteur FINALS sont
    recalculés sur les ratios restants. Une majorité cohérente (même loin de
    1.0) n'est ainsi JAMAIS exclue par elle-même — seule une MINORITÉ qui
    s'écarte du gros du panier l'est.

    Rend `{"n", "ratio_median", "ratio_iqr", "status", "factor"}` :
    - `n` : nombre de ratios RETENUS après exclusion des aberrantes (taille de
      l'échantillon réellement utilisé pour la médiane/le facteur) — jamais le
      nombre de ratios reçus en entrée si des aberrantes ont été exclues.
    - `ratio_median`/`ratio_iqr` : médiane et dispersion (IQR) du ratio parmi
      les ratios RETENUS, arrondies à 3 décimales — `None` si `ratios` est
      vide (`ratio_iqr` aussi `None` avec un seul ratio retenu, voir
      `_median_and_iqr`) ; rendues MÊME quand `status="insufficient"`
      (diagnostic utile même sous le seuil, voir `n < min_n`), jamais
      masquées.
    - `status` : `"insufficient"` (`n < min_n`), `"not_needed"` (médiane à
      `band_pct` % ou moins de 1.0), ou `"applied"` (sinon).
    - `factor` : `1.0` pour `"insufficient"`/`"not_needed"` (jamais appliqué
      faute d'échantillon suffisant, ou parce que le modèle est déjà fidèle
      sur ce panier), sinon la médiane BORNÉE à `[factor_min, factor_max]` —
      jamais extrapolée au-delà (voir `ASSUMPTIONS["calibration"]`)."""
    if not ratios:
        return {"n": 0, "ratio_median": None, "ratio_iqr": None, "status": "insufficient", "factor": 1.0}
    raw_median = statistics.median(ratios)
    if raw_median > 0:
        kept = [r for r in ratios if abs(r / raw_median - 1.0) <= outlier_band_pct / 100.0]
    else:
        kept = list(ratios)  # médiane brute non positive : filet de sécurité, jamais de division par zéro
    if not kept:
        # Cas dégénéré (ex. deux ratios très écartés, tous deux hors de la bande relative
        # à leur propre médiane) : mieux vaut TOUT garder que rendre un panier vide, qui
        # masquerait des données réellement présentes derrière un `status="insufficient"`
        # à `n=0` trompeur.
        kept = list(ratios)

    n = len(kept)
    median, iqr = _median_and_iqr(kept)
    ratio_median = round(median, 3) if median is not None else None
    ratio_iqr = round(iqr, 3) if iqr is not None else None
    if n < min_n:
        return {"n": n, "ratio_median": ratio_median, "ratio_iqr": ratio_iqr,
                "status": "insufficient", "factor": 1.0}
    if abs(median - 1.0) * 100.0 <= band_pct:
        return {"n": n, "ratio_median": ratio_median, "ratio_iqr": ratio_iqr,
                "status": "not_needed", "factor": 1.0}
    factor = max(factor_min, min(factor_max, median))
    return {"n": n, "ratio_median": ratio_median, "ratio_iqr": ratio_iqr,
            "status": "applied", "factor": round(factor, 3)}
