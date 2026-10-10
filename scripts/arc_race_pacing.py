#!/usr/bin/env python3
"""Allures de course par segment depuis le modèle personnel pente -> allure
(#59, épopée #23).

## Pourquoi

Les scénarios ×3 du plan de course (`agents/course-strategist.md`) reposaient
sur des règles génériques (« +2-3 % par 10 km », « sable -> ×1.2-1.3 »),
jamais sur l'historique réel de l'athlète. Ce module consomme les briques déjà
posées par les épopées précédentes — `arc_slope_model.predict_speed` (#58,
courbe personnelle pente -> allure), `arc_durability` (#48, fade de fin de
sortie longue), `arc_metrics.predictions` (#33, Riegel/VDOT) — et les combine
à un fichier GPX de course pour produire des temps de passage PAR SEGMENT,
avec leur provenance (personnel vs générique), trois scénarios documentés et
une vérification de barrières horaires.

Sert aussi de socle à #61 (débrief post-course, comparaison plan vs réalisé
PAR SEGMENT) : les identifiants de segment (`s01`, `s02`…) et leurs bornes
kilométriques sont stables d'un appel à l'autre pour un même GPX et un même
`--segment-m` (déterminisme, voir `ASSUMPTIONS["segmentation"]`) — #61 doit
pouvoir aligner un segment du plan avec le même segment mesuré après course
sans recalculer sa propre segmentation.

## Découpage en couches (comme le reste du moteur)

- **Segmentation** (`segment_course`) : pure, ne dépend que du GPX (via
  `arc_elevation.grade_series`, déjà partagé par le GAP/#44 et l'analyse GPX
  générique du skill `gpx-analysis`). Conserve, en plus des champs publics du
  contrat, un profil pente/distance POINT PAR POINT (clé privée `_profile`,
  jamais émise dans le JSON final) — voir `ASSUMPTIONS["rolling_terrain"]`
  pour pourquoi la moyenne de pente seule ne suffit pas.
- **Prédiction** (`predict_segments`) : pure, ne dépend que des segments, des
  paniers du modèle personnel (`arc_slope_model.predict_speed`), d'un taux de
  fade, d'un facteur météo et d'un facteur d'intensité de course déjà résolus
  par l'appelant — aucun accès disque ni réseau ici.
- **Passages/barrières** (`compute_passages`/`check_cutoffs`) : pures, cumul
  des temps de segment + arrêts ravito, comparaison aux barrières horaires.
- **CLI** (`plan`, fonction `main`) : la SEULE couche qui touche le disque —
  lit le GPX, ouvre l'index du workspace UNE SEULE FOIS (`arc_index`, mêmes
  conventions que les autres sous-commandes : `--workspace`, `--db`,
  `--memory`, `--rebuild`, `--today`) pour résoudre le modèle personnel, la
  tendance de durabilité, l'intensité de course et l'acclimatation chaleur,
  et assemble le JSON final.

## Pourquoi un script séparé plutôt qu'une sous-commande `arc_index.py`

Même logique que `skills/gpx-analysis/scripts/analyze_gpx.py` et
`skills/course-comparison/scripts/compare_course.py` (#59 ne rompt pas cette
convention) : ce script combine un fichier EXTERNE fourni à l'appel (le GPX de
la course, jamais indexé) avec des paramètres de scénario (date de course,
heure de départ, ravitos, météo prévue) qui n'ont pas de sens comme requête
sur l'index seul — contrairement à `slope-model`/`durability`, qui ne lisent
QUE l'historique déjà indexé. `arc_race_pacing.py` IMPORTE `arc_index` comme
bibliothèque (même précédent que `arc_serve.py`/`arc_guardrails.py`/
`coach_doctor.py`) pour réutiliser sa résolution de workspace/config et ses
rapports `slope_model_report`/`durability_trend`/`heat_acclimation_today`,
jamais une seconde implémentation de ces calculs. L'index n'est ouvert et
reconstruit QU'UNE SEULE FOIS par appel CLI (revue de code #59 : trois
réindexations indépendantes coûtaient ≈ 7,6 s contre ≈ 2,5 s pour une seule) —
`main()` ouvre `conn` et le passe à chaque résolveur, aucun résolveur
n'importe plus `arc_index` lui-même.

## Segmentation (voir `ASSUMPTIONS["segmentation"]`)

Longueur cible fixe (`--segment-m`, défaut 750 m — au milieu de la fourchette
500 m-1 km demandée par #59), puis une passe de fusion GREEDY de gauche à
droite : deux segments adjacents dont la pente moyenne diffère de moins de
`MERGE_GRADE_DELTA_PCT` (2 points) sont fusionnés, tant que le segment fusionné
ne dépasse pas `MAX_SEGMENT_FACTOR` × la longueur cible (2250 m par défaut) —
évite une avalanche de tout petits segments sur un profil plat tout en gardant
un côté déterministe et un plafond de longueur pour ne jamais dissoudre une
vraie rupture de pente dans un segment démesuré. Cette même passe couvre
maintenant aussi le DERNIER segment (revue de code #59 : l'ancienne fusion
inconditionnelle du reliquat final ignorait la pente) ; un reliquat encore
trop court après la fusion par pente (`MIN_SEGMENT_M`, 300 m) est fusionné
dans le précédent en dernier recours, quelle que soit sa pente — jamais un
segment orphelin, mais seulement quand la fusion « intelligente » n'a pas
suffi.

## Terrain vallonné : intégration point par point (voir `ASSUMPTIONS["rolling_terrain"]`)

La pente MOYENNE d'un segment (`grade_mean_pct`, conservée pour l'affichage)
ne suffit PAS à prédire son temps : un aller-retour +12 %/-12 % tous les
375 m dans un même segment de 750 m a une pente moyenne quasi nulle mais un
temps réel bien plus long qu'un vrai plat (le coût d'une montée n'est jamais
compensé par le gain symétrique d'une descente à la même pente, voir
`arc_gap.ASSUMPTIONS["model"]`). Le temps prédit intègre donc `Δd / v(pente
locale)` sur CHAQUE paire de points GPX du segment (pente lissée de
`arc_elevation.grade_series`), jamais sur la seule pente moyenne.

## Fade (voir `ASSUMPTIONS["fade"]`)

Le fade GAP médian des sorties longues récentes (`arc_durability`, #48) est
appliqué comme un ralentissement PROGRESSIF, calibré pour que la MOYENNE du
ralentissement sur le DERNIER TIERS de la course égale `fade_pct` (même
définition que la mesure source, qui compare premier et dernier tiers) —
nul sur le premier tiers, rampe linéaire ensuite. Échelonné en plus par la
durée de course PRÉDITE face au seuil de sortie longue
(`arc_metrics.LONG_RUN_MIN_DURATION_S`, 90 min) : un fade mesuré sur des
sorties de plus de 90 minutes n'a pas de raison de s'appliquer PLEINEMENT à
une course de 30 minutes.

## Chaleur (voir `ASSUMPTIONS["heat"]`)

Reprend TELS QUELS les seuils déjà documentés dans `agents/course-strategist.md`
(ÉTAPE 6, approximation du projet, jamais une source physiologique
vérifiable pour ces pourcentages précis) : > 25 °C -> +10 % de temps,
< 5 °C -> +5 % de temps — avec un supplément de +5 % si la course est prévue
chaude ET que l'athlète a peu été exposé à la chaleur récemment
(`arc_index.heat_acclimation_today`, #38) : un pari optimiste sur une
acclimatation supposée serait plus dangereux qu'un plan trop prudent.

## Nuit (voir `ASSUMPTIONS["night"]`, #184)

Avec `--race-date`, `--start` explicite et `--tz`, l'heure d'horloge de chaque section
(par scénario, arrêts ravito compris) est confrontée au crépuscule civil calculé localement
(`arc_solar.py`) ; le temps de la section est multiplié par `1 + fraction de nuit × pénalité`
(pénalité dépendant de la pente, approximation du projet), en itérant (bornée) puisque la
pénalité décale les sections suivantes, et en gardant `prudent >= réaliste >= ambitieux`.
Sans ces entrées, ou de jour : sortie inchangée (clé additive `night` seulement).

## Technicité du terrain (voir `ASSUMPTIONS["technicity"]`, #186)

Option `--technicity` (fichier JSON déclaré et/ou `osm`) : coefficient par section,
déclaré par l'athlète ou dérivé des tags OpenStreetMap (`sac_scale`, `trail_visibility`,
`surface`, `tracktype`, `highway`) via Overpass (réseau, opt-in, cache `.arc/overpass/`),
pondéré par la pente (descente technique plus pénalisante), appliqué de façon identique
aux trois scénarios avant la nuit. Sans l'option : sortie inchangée (aucune clé).

## Altitude (voir `ASSUMPTIONS["altitude"]`, #185)

Facteur de temps par section dès que l'altitude moyenne dépasse 1 500 m (pente tirée de
Wehrlin & Hallén 2006, traduction vers la vitesse = approximation du projet), réduit par
l'acclimatation déclarée (`--altitude-acclimated-days`) et l'exposition à l'entraînement
(`arc_index.py altitude-exposure`), surcoût mis à l'échelle par `[pacing.personal].altitude_scale`
(#188 ; `--altitude-loss-pct` prime). Appliqué après la technicité et avant la nuit, identique
pour les trois scénarios ; sous le seuil partout : sortie inchangée (clé additive `altitude`
seulement).

Ordre des étapes de `build_race_plan` : (correction MNT #176, faite par `main` avant l'appel) →
modèle pente -> allure, chaleur comprise (`predict_segments`, facteur scalaire par section) →
fade (renormalisé neutre en temps sous 6 h) → technicité → altitude → nuit. Chaleur, technicité
et altitude sont des facteurs multiplicatifs indépendants de l'horloge : leur ordre ne change le
résultat qu'à l'arrondi près ; la nuit vient en dernier car elle lit les heures de passage.

## Allure de BASE : endurance mise à l'échelle de l'intensité de course (voir `ASSUMPTIONS["base_pace"]`)

`arc_slope_model.predict_speed` rend une allure de la bande « endurance »
(effort facile) — jamais l'allure de COURSE visée, qui est en général bien
plus rapide. `intensity_factor` corrige cette différence : rapport entre la
vitesse plate ÉQUIVALENTE prédite pour la course (Riegel, à partir du
meilleur effort récent — voir `ASSUMPTIONS["base_pace"]`) et la référence
plate personnelle de la bande endurance. Sans objectif chiffré ou sans
historique suffisant pour une prédiction, le facteur reste `1.0`
(`intensity_source: "none"`) et le plan reste explicitement une allure
D'ENDURANCE, jamais une allure de course inventée.

## Scénarios (voir `ASSUMPTIONS["scenarios"]`)

Quand un segment est prédit par le modèle PERSONNEL, les trois scénarios
utilisent directement la dispersion déjà calculée par panier
(`arc_slope_model` : IQR pondéré p25/p50/p75, exposé par `predict_speed` comme
`ci_low_speed_ms`/`speed_ms`/`ci_high_speed_ms`) — jamais un pourcentage
inventé quand une vraie dispersion mesurée existe, mais JAMAIS plus ÉTROITE
non plus que l'écart générique documenté (`GENERIC_SCENARIO_SPEED_FACTOR`,
±6-8 %, revue de code #59 : un historique de deux sorties à allure quasi
identique ne doit pas produire un écart quasi nul entre scénarios). Un
segment générique ou mixte (pas de dispersion, `ci_*` à `None`) retombe
directement sur ce pourcentage fixe documenté, signalé comme approximation du
projet.

Jamais de fausse précision : les temps de segment sont arrondis à la seconde
la plus proche (une fraction de seconde n'a aucun sens physique) mais les
temps de passage CUMULÉS et les totaux sont arrondis à la MINUTE la plus
proche — un plan de course n'a jamais la précision de la seconde sur
plusieurs heures d'effort.

Stdlib uniquement (CONTRIBUTING.md).
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
import arc_altitude as AL  # noqa: E402
import arc_contract as C  # noqa: E402
import arc_elevation as EL  # noqa: E402
import arc_energy as EN  # noqa: E402
import arc_metrics as M  # noqa: E402
import arc_slope_model as SL  # noqa: E402
import arc_pacing_personal as PP  # noqa: E402
import arc_technicity as TECH  # noqa: E402
from coach_setup import workspace_root  # noqa: E402 (revue de code #107 : même résolution que arc_index.py/arc_guardrails.py, jamais un simple Path(".") qui ignore ARC_WORKSPACE/le pointeur)

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

DEFAULT_SEGMENT_M = 750.0
MIN_SEGMENT_M = 300.0
MAX_SEGMENT_FACTOR = 3.0
MERGE_GRADE_DELTA_PCT = 2.0  # points de pourcentage
DEFAULT_BAND = "endurance"
DEFAULT_FADE_WEEKS = 12  # même fenêtre par défaut que decoupling/vam/descent/durability

# Référence Riegel (revue de code #59, BLOQUANT) : seules les intensités
# planifiées d'un effort RÉELLEMENT dur (tempo et au-delà) qualifient une
# activité comme référence de vitesse de COURSE — un footing facile, même
# long, sous-estime largement l'allure de course et produirait une prédiction
# plus LENTE que l'allure d'endurance elle-même. Mêmes valeurs que
# `arc_contract.INTENSITY`, sous-ensemble « dur ».
HARD_REFERENCE_INTENSITIES = ("tempo", "threshold", "vo2max", "race")
# Distance minimale d'une référence Riegel — même seuil que
# `arc_metrics.predictions`/`RECORD_DISTANCES_KM` (`km >= 5` = « le plus long
# effort est le plus prédictif »).
MIN_REFERENCE_DISTANCE_M = 5000.0
# En dessous de ce seuil, un `intensity_factor` calculé sous 1.0 (allure de
# course plus LENTE que l'allure d'endurance mesurée) est implausible et
# plafonné à 1.0 (revue de code #59, BLOQUANT) — au-delà, l'exposant de Riegel
# en trail (1.15, `arc_metrics.RIEGEL_EXPONENT`) prédit déjà, à raison, un
# ralentissement marqué sur un ultra : aucun plancher n'y est nécessaire.
INTENSITY_CLAMP_DURATION_S = 4.5 * 3600.0
# Écart (%) entre l'objectif chiffré (`planning/active_objective.md`) et le GPX
# réellement analysé, en équivalent plat, au-delà duquel un avertissement est
# émis — l'intensité de course est TOUJOURS calculée depuis le GPX (revue de
# code #59, BLOQUANT), jamais depuis l'objectif, qui peut décrire une autre
# course ou une distance arrondie.
OBJECTIVE_GPX_MISMATCH_PCT = 10.0

# Riegel PAR MORCEAUX (3ᵉ revue de code #59, BLOQUANT) — voir
# `ASSUMPTIONS["base_pace"]` : un exposant Riegel UNIQUE (1.06 route / 1.15
# trail) reste optimiste passé quelques heures d'effort, ce qui rendait une
# allure d'ultra plus RAPIDE que des références élites réelles (ex. un 171 km/
# 10 000 m D+ prédit en 18 h, plus vite que l'UTMB). `RIEGEL_ULTRA_ANCHOR_M`
# (42,195 km — la distance MARATHON, standard bien connu) est le point de
# pivot : l'exposant de la bande (`arc_metrics.RIEGEL_EXPONENT`) s'applique
# JUSQU'À ce pivot, `RIEGEL_ULTRA_EXPONENT` (1.30, approximation du projet —
# aucune source vérifiable ne fixe cette valeur précise, choisie pour
# recouper l'ordre de grandeur de références ultra publiques) au-delà.
RIEGEL_ULTRA_ANCHOR_M = 42195.0
RIEGEL_ULTRA_EXPONENT = 1.30

# Extrapolation Riegel trop lointaine (3ᵉ revue de code #59, should-fix) : au-delà
# de ce ratio (cible / référence, en équivalent plat), la prédiction s'appuie sur
# une référence trop courte pour être fiable — le scénario « safe » est alors
# élargi (`EXTRAPOLATION_SAFE_SCENARIO_FACTOR`, -12 % au lieu du plancher
# générique -8 %) et un avertissement est émis.
RIEGEL_EXTRAPOLATION_RATIO = 4.0
EXTRAPOLATION_SAFE_SCENARIO_FACTOR = 0.88

# Durée de course PRÉDITE au-delà de laquelle le fade reste ADDITIF (un vrai
# ralentissement net) plutôt que neutre en temps total (3ᵉ revue de code #59,
# should-fix) — voir `ASSUMPTIONS["fade"]` : sur un ultra de plusieurs heures,
# la dégradation d'endurance implicite de Riegel/VDOT (déjà approximative au-delà
# de ce point, voir `RIEGEL_ULTRA_EXPONENT`) ne doit pas être présumée couvrir
# EXACTEMENT le fade mesuré à l'entraînement — les deux s'additionnent plutôt
# que de se neutraliser, en dessous ce seuil reste le régime « fade neutre ».
FADE_TIME_NEUTRAL_MAX_DURATION_S = 6.0 * 3600.0

# Clés EN ANGLAIS (contrat ```arc, AGENTS.md « clés en anglais ») — mêmes noms
# que `race_plan.scenarios` déjà défini par le skill `workspace-data-contract`
# (`{"ambitious": s, "realistic": s, "safe": s}`) : un plan de course par
# segment doit utiliser le même vocabulaire de scénario que le plan global,
# jamais un second jeu de noms pour la même notion. "safe" = prudent (le plus
# lent), "realistic" = cible (médiane/interpolation), "ambitious" = ambitieux
# (le plus rapide).
SCENARIOS = ("safe", "realistic", "ambitious")

# Approximation du projet (revue de code #59) : AUCUNE source vérifiable ne
# documente ces pourcentages précis pour un athlète sans dispersion mesurée —
# ils encadrent la cible d'un ordre de grandeur raisonnable (±6-8 %). Sert
# AUSSI d'écart PLANCHER pour un segment personnel dont la dispersion mesurée
# serait plus étroite (revue de code #59, voir `_scenario_speeds`) : jamais une
# vraie mesure de dispersion individuelle, mais jamais un signal de confiance
# artificiellement optimiste non plus.
GENERIC_SCENARIO_SPEED_FACTOR = {"safe": 0.92, "realistic": 1.0, "ambitious": 1.06}

# Fade générique de repli (#59, ASSUMPTIONS["fade"]) : appliqué UNIQUEMENT si
# aucune sortie longue récente n'a de fade GAP mesurable (`arc_durability`) —
# approximation du projet, pas une mesure. Volontairement modeste : un plan de
# course ne doit pas supposer un effondrement qu'aucune donnée ne suggère.
DEFAULT_GENERIC_FADE_PCT = 5.0

# Calibration du profil de fade (revue de code #59) : `fade_speed_multiplier`
# rampe linéairement à partir du premier tiers de course — un simple facteur
# ×1 à l'arrivée ne fait, en MOYENNE sur le dernier tiers, que 0,75 × `fade_pct`
# (aire d'un triangle), alors que `fade_pct` est défini par `arc_durability`
# comme la MOYENNE du dernier tiers. `FADE_LAST_THIRD_MEAN_FACTOR` (4/3) est le
# facteur qui rend cette moyenne exacte : voir `ASSUMPTIONS["fade"]` pour le
# calcul complet.
FADE_LAST_THIRD_MEAN_FACTOR = 4.0 / 3.0
# Plancher de sécurité (jamais une vitesse nulle ou négative) pour un `fade_pct`
# extrême — approximation du projet, pas une mesure.
FADE_MIN_SPEED_FACTOR = 0.05

# Seuils/facteurs de chaleur : SOURCE UNIQUE dans `arc_heat.py` (#171), partagée avec
# l'ajustement des séances d'entraînement ; ré-exportés ici sous leurs noms historiques
# (valeurs reprises TELLES QUELLES de `agents/course-strategist.md`, ÉTAPE 6 — approximation
# du projet, voir `ASSUMPTIONS["heat"]`).
from arc_heat import (  # noqa: E402,F401
    HEAT_ACCLIMATION_MIN_HOT_SESSIONS, HEAT_COLD_C, HEAT_COLD_TIME_FACTOR, HEAT_HOT_C,
    HEAT_HOT_TIME_FACTOR, HEAT_UNACCLIMATED_EXTRA_FACTOR, heat_time_factor, resolve_acclimated,
)

# Ravitaillement : temps d'arrêt par défaut si non précisé par station (#59) —
# approximation du projet (un ravito simple, ni drop bag ni repas chaud).
DEFAULT_AID_STATION_STOP_S = 90.0

# Barrière horaire : marge de confort avant de considérer un scénario comme
# "tendu" plutôt que "confortable" — approximation du projet, jamais une règle
# de course réelle (chaque course a ses propres marges de sécurité).
CUTOFF_MARGIN_OK_S = 30 * 60

# Arrondis (revue de code #59, honnêteté de la précision affichée) : un temps
# de SEGMENT à la seconde la plus proche, un temps de PASSAGE/TOTAL cumulé à
# la minute la plus proche — jamais l'inverse, jamais les deux à la seconde.
SEGMENT_ROUND_S = 1
PASSAGE_ROUND_S = 60

# Poids du sac/flasques/matériel porté (dépense énergétique prévue) — voir
# `ASSUMPTIONS["energy"]`. Défaut `0.0` si `--pack-kg` n'est jamais fourni :
# AUCUNE valeur « typique » n'est inventée sans source vérifiable, un
# avertissement explicite invite l'appelant à le renseigner à la place.
DEFAULT_PACK_KG = 0.0
# Bornes de validation de `--pack-kg` (revue de code) — approximation du
# projet, PAS une limite physiologique précise : `PACK_KG_MAX` (30 kg) écarte
# une saisie manifestement fausse (confusion kg/lb, poids CORPOREL saisi par
# erreur à la place du sac) sans prétendre encadrer ce qu'un athlète peut
# raisonnablement porter. Jamais une valeur non finie (NaN/infini), qui
# fausserait silencieusement la masse totale et donc tout le calcul d'énergie.
PACK_KG_MIN = 0.0
PACK_KG_MAX = 30.0

# Pénalité de NUIT (#184, épopée #170) — voir `ASSUMPTIONS["night"]`. TOUS ces coefficients
# sont des APPROXIMATIONS DU PROJET : aucune source vérifiée n'en donne la valeur pour un
# athlète donné (visibilité réduite, vigilance, foulée prudente sur terrain technique).
# Pénalité de TEMPS (%) à pleine nuit sur plat/montée :
NIGHT_BASE_PENALTY_PCT = 5.0
# Supplément de temps (points de %) par point de % de DESCENTE au-delà de
# `NIGHT_DESCENT_FREE_GRADE_PCT`, plafonné à `NIGHT_DESCENT_EXTRA_MAX_PCT` : on freine
# davantage en descente de nuit (le sol se lit mal) qu'à plat.
NIGHT_DESCENT_FREE_GRADE_PCT = 2.0
NIGHT_DESCENT_EXTRA_PER_GRADE_PCT = 0.6
NIGHT_DESCENT_EXTRA_MAX_PCT = 8.0
# Bornes de validation des options CLI (rejette une saisie manifestement fausse).
NIGHT_PENALTY_PCT_MAX = 30.0
# Itérations (bornées) du calcul, car la pénalité décale l'heure de passage des sections
# suivantes, donc leur fraction de nuit ; critère d'arrêt sur le facteur (écart absolu max).
NIGHT_MAX_ITERATIONS = 8
NIGHT_CONVERGENCE_TOL = 1e-4
# Contrôle de vraisemblance du fuseau (`--tz`) : écart (heures) au-delà duquel le décalage UTC
# du fuseau au départ s'éloigne trop de l'heure solaire de la longitude du départ (lon / 15).
# Les fuseaux réels s'en écartent de 0 à ~3 h (Espagne l'été ≈ +2 h, ouest de la Chine ≈ +3 h) :
# au-delà, le fuseau est probablement faux (course sur un autre continent). Approximation du projet,
# simple AVERTISSEMENT, jamais un refus.
NIGHT_TZ_SUSPECT_OFFSET_H = 3.5


def _round_passage(seconds: float) -> int:
    return int(round(seconds / PASSAGE_ROUND_S)) * PASSAGE_ROUND_S


ASSUMPTIONS = {
    "segmentation": (
        "Segments de longueur cible fixe (`DEFAULT_SEGMENT_M`, 750 m — milieu de la fourchette "
        "500 m-1 km demandée par #59), pente moyenne calculée par distance parcourue (pondérée) sur "
        "le profil d'altitude lissé (`arc_elevation.grade_series`, fenêtre 30 m, même moteur que le "
        "GAP #44 et l'analyse GPX générique du skill gpx-analysis). Une passe de fusion GREEDY, de "
        "gauche à droite, fusionne deux segments adjacents (dernier compris, revue de code #59) dont la "
        "pente moyenne diffère de moins de `MERGE_GRADE_DELTA_PCT` (2 points), tant que le segment "
        "fusionné ne dépasse pas `MAX_SEGMENT_FACTOR` × la longueur cible (2250 m par défaut) — réduit "
        "la fragmentation sur un profil plat sans jamais dissoudre une vraie rupture de pente dans un "
        "segment démesuré. Un reliquat encore plus court que `MIN_SEGMENT_M` (300 m) APRÈS cette passe "
        "est fusionné dans le précédent en dernier recours, quelle que soit sa pente — jamais un "
        "segment orphelin, mais seulement quand la fusion par pente n'a pas suffi. Déterministe pour un "
        "GPX et un `--segment-m` donnés : mêmes identifiants (`s01`, `s02`…) et mêmes bornes "
        "kilométriques d'un appel à l'autre — propriété nécessaire à #61 (débrief post-course par "
        "segment)."
    ),
    "rolling_terrain": (
        "La pente MOYENNE d'un segment (`grade_mean_pct`, conservée pour l'affichage) ne suffit PAS à "
        "prédire son temps (revue de code #59, blocant) : un profil vallonné (+12 %/-12 % tous les "
        "375 m dans un segment de 750 m) a une pente moyenne quasi nulle mais un temps réel bien plus "
        "long qu'un vrai plat — le temps perdu en montée n'est jamais compensé par le gain "
        "symétrique d'une descente à la même pente (modèle de pente de Kay, voir "
        "`arc_gap.ASSUMPTIONS['model']`) ; moyenner la pente AVANT de prédire la vitesse revient à "
        "prédire la vitesse d'un plat qui n'existe pas. `predict_segments` intègre donc `Δd / "
        "v(pente locale)` sur CHAQUE paire de points GPX consécutifs du segment (pente lissée de "
        "`arc_elevation.grade_series`, moyenne des deux pentes d'extrémité de la paire), jamais sur la "
        "seule pente moyenne — `grade_mean_pct` reste UNIQUEMENT un repère d'affichage. Une pente qui "
        "tombe dans l'intervalle `[lo, hi)` d'un panier PERSONNEL du modèle est en plus SNAPÉE "
        "EXACTEMENT sur le point milieu de ce panier avant la prédiction (`_snap_grade_to_bin`, 2ᵉ revue "
        "de code #59, should-fix) : sans ce snap, `predict_speed` interpole entre deux paniers voisins "
        "dès que la pente n'est pas EXACTEMENT sur un point milieu, étiquetant à tort `\"mixed\"` un "
        "point qui tombe pourtant bien dans la plage MESURÉE d'un panier personnel — jusqu'à 58 % de "
        "segments `\"mixed\"` observés sur un profil trail synthétique dont les pentes de 1-2 % "
        "tombaient hors du seul panier central snappé par la première version de ce correctif. Repli, "
        "pour un `bins` de test sans `grade_lo`/`grade_hi` (ou si aucun panier personnel ne couvre la "
        "pente) : neutralise seulement le panier CENTRAL canonique du modèle "
        "(`arc_slope_model.GRADE_BINS`), pour ne jamais interpoler un bruit GPS de quelques dixièmes de "
        "point autour du plat."
    ),
    "scenarios": (
        "Un segment prédit par le modèle PERSONNEL (`source == \"personal\"`) utilise directement la "
        "dispersion déjà calculée par panier de pente (`arc_slope_model`, IQR pondéré p25/p50/p75, "
        "exposée par `predict_speed` comme `ci_low_speed_ms`/`speed_ms`/`ci_high_speed_ms`) : "
        "« safe » = p25 (plus lent), « realistic » = médiane/interpolation, « ambitious » = p75 (plus "
        "rapide) — jamais un pourcentage inventé quand une vraie dispersion mesurée existe. Cette "
        "dispersion mesurée ne peut cependant jamais être PLUS ÉTROITE que l'écart générique documenté "
        "(`GENERIC_SCENARIO_SPEED_FACTOR`, ±6-8 % — revue de code #59, should-fix) : deux sorties "
        "d'entraînement à allure quasi identique produisent un IQR quasi nul, ce qui donnerait trois "
        "scénarios pratiquement confondus — un signal de confiance que rien ne justifie sur seulement "
        "deux séances. `safe` est donc le MINIMUM (le plus lent) entre la borne p25 mesurée et "
        "`speed × 0.92`, `ambitious` le MAXIMUM (le plus rapide) entre la borne p75 mesurée et "
        "`speed × 1.06` — la mesure l'emporte seulement quand elle est PLUS large que le plancher "
        "générique, jamais quand elle est plus étroite. Un segment générique ou mixte (`ci_*` à "
        "`None`) retombe directement sur ce pourcentage fixe, signalé comme approximation du projet, "
        "sans source vérifiable pour ces valeurs précises. Le plancher « safe » lui-même est élargi à "
        "`EXTRAPOLATION_SAFE_SCENARIO_FACTOR` (-12 %) plutôt que le générique (-8 %) quand la cible "
        "extrapole à plus de `RIEGEL_EXTRAPOLATION_RATIO` fois la distance de la référence Riegel (voir "
        "`ASSUMPTIONS[\"base_pace\"]`, 3ᵉ revue de code #59, should-fix) : une prédiction extrapolée "
        "loin de toute mesure mérite une marge de sécurité plus large, pas la même que pour une "
        "distance proche de la référence."
    ),
    "base_pace": (
        "`arc_slope_model.predict_speed` (#58) est ajusté sur la bande « endurance » (effort facile "
        "d'entraînement) : ses vitesses ne sont PAS l'allure de COURSE visée, en général nettement plus "
        "rapide (revue de code #59, blocant — cette distinction n'était affichée nulle part). "
        "`intensity_factor` corrige l'écart : `(vitesse plate équivalente prédite pour la course) / "
        "(référence plate personnelle de la bande endurance, slope_model_report."
        "flat_reference_speed_ms)`.\n\n"
        "**Cible = le GPX analysé, jamais l'objectif** (2ᵉ revue de code #59, BLOQUANT) : la vitesse "
        "plate cible se calcule sur `distance_m`/`elevation_gain_m` mesurés du GPX (équivalence plat "
        "trail : `arc_metrics.TRAIL_FLAT_M_PER_M_DPLUS`), jamais sur `planning/active_objective.md` — "
        "un objectif qui décrit une autre course, ou une distance arrondie, aurait sinon faussé le "
        "facteur sans rapport avec le parcours réellement chargé. Si `planning/active_objective.md` "
        "existe et diffère de plus de `OBJECTIVE_GPX_MISMATCH_PCT` (10 %) du GPX en équivalent plat, un "
        "avertissement le signale dans `warnings` — l'objectif reste alors purement informatif.\n\n"
        "**Référence = un effort RÉEL et DUR, jamais un footing facile** (2ᵉ revue de code #59, "
        "BLOQUANT) : un simple filtre « le plus long effort connu » (l'ancienne méthode) retenait "
        "parfois une longue sortie d'ENDURANCE vallonnée comme référence de vitesse de COURSE — sa "
        "pente ralentit déjà la référence (aucune conversion plate n'était appliquée côté référence), "
        "ET la courbe pente -> allure la ralentit une seconde fois sur les segments en côte du plan : un "
        "double comptage qui pouvait rendre l'allure de « course » plus LENTE que l'allure d'endurance "
        "mesurée. La référence Riegel n'est donc retenue que parmi les activités course à pied "
        "d'au moins `MIN_REFERENCE_DISTANCE_M` (5 km) dont l'intensité planifiée "
        "(`arc_index.planned_intensity_for`) est dans `HARD_REFERENCE_INTENSITIES` (tempo/seuil/VO2max/"
        "course), ou, à défaut de plan, dont la FC moyenne dépasse la borne Z3/Z4 de l'athlète "
        "(`arc_index.athlete_hr_zone_bounds`) — la plus longue qualifiante est la plus prédictive (même "
        "principe que `arc_metrics.predictions`). Sa distance ET son D+ propres sont convertis en "
        "équivalent plat EXACTEMENT comme la cible, avant d'appeler `_riegel_time_s` — les DEUX "
        "côtés de la comparaison sont ainsi en équivalent plat, jamais un mélange brut/converti qui "
        "compterait le relief deux fois. VDOT (tendance de VO2max, `metric_day.vo2max`) en repli si "
        "aucune référence dure n'est trouvée.\n\n"
        "**Riegel PAR MORCEAUX au-delà du marathon** (3ᵉ revue de code #59, BLOQUANT) : un exposant "
        "Riegel UNIQUE (1.06 route / 1.15 trail, `arc_metrics.RIEGEL_EXPONENT`) reste OPTIMISTE passé "
        "quelques heures d'effort — approximation du projet, aucune source vérifiable ne chiffre "
        "précisément ce biais pour ce calcul-ci, mais la dégradation de l'endurance sur un effort de "
        "plusieurs heures est bien plus marquée qu'un exposant calibré sur des distances de compétition "
        "courtes (5 km-marathon) ne le prédit. Une allure d'ultra calculée avec l'exposant unique "
        "pouvait ainsi dépasser des références élites publiques réelles (ex. 171 km/10 000 m D+ prédit "
        "en ~18 h, plus vite que le record de l'UTMB). `_riegel_time_s` applique donc l'exposant de la "
        "bande JUSQU'À `RIEGEL_ULTRA_ANCHOR_M` (42,195 km équivalent plat — la distance MARATHON, un "
        "standard bien connu et vérifiable, retenu comme pivot), `RIEGEL_ULTRA_EXPONENT` (1.30 — "
        "approximation du projet, choisie pour recouper l'ORDRE DE GRANDEUR de repères ultra publics, "
        "PAS une valeur mesurée pour cet athlète) au-delà. Se réduit EXACTEMENT à la formule Riegel "
        "standard quand référence ET cible sont toutes deux au marathon ou moins (aucun changement pour "
        "ces distances, voir les tests). Repères de calibration (« avant fade », donc avant "
        "l'ajustement additif décrit ci-dessous ; approximatifs, dépendent de la référence RÉELLEMENT "
        "retenue pour l'athlète, jamais une garantie) ayant guidé le choix de 1.30 : ≈ 8h30 pour 80 km/"
        "3 500 m D+, ≈ 9h30 pour 100 km plat, ≈ 11h20 pour 100 km/5 000 m D+, ≈ 21 h pour 160 km/8 000 m "
        "D+, ≈ 22h45 pour 171 km/10 000 m D+.\n\n"
        "**Extrapolation trop lointaine** (3ᵉ revue de code #59, should-fix) : au-delà de "
        "`RIEGEL_EXTRAPOLATION_RATIO` (4×) entre la distance cible et celle de la référence Riegel "
        "retenue (toutes deux en équivalent plat), la prédiction s'appuie sur un point de mesure trop "
        "court pour être fiable — le scénario « safe » est alors élargi "
        "(`EXTRAPOLATION_SAFE_SCENARIO_FACTOR`, -12 % au lieu du plancher générique -8 %) et un "
        "avertissement est ajouté à `notes`.\n\n"
        "Toutes les vitesses issues du modèle (personnel ET générique) sont multipliées par ce facteur "
        "avant d'en dériver les trois scénarios — la dispersion personnelle (IQR) est donc, elle aussi, "
        "mise à l'échelle de l'intensité de course, pas seulement le point central. Un facteur calculé "
        "sous 1.0 pour une course prédite de moins de `INTENSITY_CLAMP_DURATION_S` (4h30) est implausible "
        "(l'allure de course ne peut pas être plus lente que l'allure d'endurance sur une distance "
        "courte) et plafonné à 1.0, avec un avertissement — au-delà de ce seuil, l'exposant ultra "
        "(1.30) prédit déjà, à raison, un ralentissement marqué, aucun plancher n'y est appliqué. Sans "
        "distance GPX exploitable, sans référence plate personnelle, ou sans référence dure/tendance "
        "VO2max exploitable, `intensity_factor` reste `1.0` et `intensity_source` vaut `\"none\"` — le "
        "plan reste alors EXPLICITEMENT une allure d'ENDURANCE (jamais une allure de course inventée), "
        "signalé en clair dans `warnings`."
    ),
    "fade": (
        "Le fade GAP médian des sorties longues récentes (`arc_durability`/`arc_index.durability_trend`, "
        "#48, fenêtre `--fade-weeks`, défaut 12 semaines glissantes) est appliqué comme un "
        "ralentissement PROGRESSIF sur la vitesse : nul sur le premier tiers de la distance totale de "
        "la course (même repère que la mesure source, qui compare premier et dernier tiers d'une sortie "
        "longue), puis une rampe LINÉAIRE jusqu'à l'arrivée. Calibrée pour que la MOYENNE du "
        "ralentissement sur le DERNIER TIERS égale exactement `fade_pct` (revue de code #59, should-fix) "
        "— une simple rampe de 0 à `fade_pct` à l'arrivée ne fait, en moyenne sur ce dernier tiers, que "
        "0,75 × `fade_pct` (aire d'un triangle) ; `FADE_LAST_THIRD_MEAN_FACTOR` (4/3) est le facteur qui "
        "rend cette moyenne exacte au ralentissement MESURÉ (`fade_pct` est LUI-MÊME défini par "
        "`arc_durability` comme une moyenne de dernier tiers, jamais une valeur ponctuelle à "
        "l'arrivée). `FADE_MIN_SPEED_FACTOR` (5 %) plafonne le ralentissement en toute circonstance — "
        "jamais une vitesse nulle ou négative pour un `fade_pct` extrême. Sans aucune sortie longue avec "
        "un fade GAP mesurable dans la fenêtre, un fade générique de repli est utilisé "
        "(`DEFAULT_GENERIC_FADE_PCT`, 5 %) — approximation du projet, PAS une mesure, toujours signalée "
        "(`fade_source: \"generic\"`). Le fade mesuré/générique est en outre ÉCHELONNÉ par la durée de "
        "course PRÉDITE (scénario réaliste, avant application du fade) face au seuil de sortie longue "
        "(`arc_metrics.LONG_RUN_MIN_DURATION_S`, 90 min, revue de code #59, should-fix) : appliquer "
        "PLEINEMENT un fade mesuré sur des sorties de plus de 90 minutes à une course de 30 minutes n'a "
        "aucune justification physiologique. `fade_pct_applied` (proportionnel à `durée prédite / 90 "
        "min`, plafonné à 1) est la valeur RÉELLEMENT appliquée ; `fade_pct` reste la valeur mesurée/"
        "générique brute, pour la transparence.\n\n"
        "**Neutre en temps total quand `intensity_source != \"none\"` ET course prédite <= "
        "`FADE_TIME_NEUTRAL_MAX_DURATION_S` (6 h)** (2ᵉ puis 3ᵉ revue de code #59, should-fix) : "
        "Riegel/VDOT prédisent déjà un temps de course qui intègre implicitement une dégradation "
        "d'endurance sur la distance (l'exposant de Riegel > 1, la courbe VDOT) — appliquer EN PLUS le "
        "fade GAP comme un ralentissement NET aurait compté cette dégradation deux fois, gonflant le "
        "temps total au-delà de ce que Riegel/VDOT prédisent déjà. Le fade est alors RENORMALISÉ après "
        "application (`_renormalize_fade_time_neutral`) : chaque scénario garde le MÊME total qu'un plan "
        "sans fade (plus rapide en début de course, plus lent en fin — la FORME reste utile pour le "
        "rythme à tenir), seule la RÉPARTITION dans le temps change, jamais le total.\n\n"
        "**Redevient ADDITIF (un vrai ralentissement net) au-delà de 6 h** (3ᵉ revue de code #59, "
        "should-fix) : passé ce seuil, l'exposant ULTRA de Riegel (`RIEGEL_ULTRA_EXPONENT`, voir "
        "ASSUMPTIONS[\"base_pace\"]) est lui-même une approximation du projet, pas une mesure — présumer "
        "qu'il couvre EXACTEMENT le fade GAP mesuré à l'entraînement (une grandeur d'une nature "
        "différente, issue de la durabilité sur sortie longue) serait une coïncidence non justifiée. "
        "Les deux effets s'ADDITIONNENT donc sur un ultra plutôt que de se neutraliser — un plan de plus "
        "de 6 h reste donc, à dessein, plus prudent (temps total plus long) qu'un simple report de la "
        "prédiction Riegel/VDOT. Quand `intensity_source == \"none\"` (allure d'endurance simple, "
        "aucune prédiction Riegel/VDOT sous-jacente), le fade reste ADDITIF quelle que soit la durée, "
        "comme avant #59 — rien à double-compter, l'allure de base n'intègre alors aucune dégradation "
        "implicite."
    ),
    "heat": (
        "Reprend TELS QUELS les seuils déjà documentés dans `agents/course-strategist.md` (ÉTAPE 6) — "
        "approximation du projet, jamais une source physiologique vérifiable pour ces pourcentages "
        "précis : température max prévue > 25 °C -> temps × 1.10, < 5 °C -> temps × 1.05, entre les "
        "deux -> aucun ajustement. Un supplément (`HEAT_UNACCLIMATED_EXTRA_FACTOR`, +5 %) s'applique "
        "en plus si la course est prévue chaude ET que l'athlète a eu moins de "
        "`HEAT_ACCLIMATION_MIN_HOT_SESSIONS` séances chaudes sur les 14 derniers jours "
        "(`arc_index.heat_acclimation_today`, #38) : un pari optimiste sur une acclimatation supposée "
        "serait plus dangereux qu'un plan trop prudent. Le facteur météo s'applique UNIFORMÉMENT à "
        "tous les segments (pas de section plus/moins exposée modélisée ici). Sans AUCUNE séance "
        "exploitable sur la fenêtre (`sessions_considered == 0`, revue de code #59, should-fix) — pas "
        "seulement sans séance chaude — l'acclimatation reste `None` (statut inconnu), jamais assimilée "
        "à une non-acclimatation : l'absence de donnée n'est pas une preuve d'exposition faible. "
        "L'acclimatation est évaluée sur les 14 jours précédant `--today` (ou la date du jour, par "
        "défaut) — jamais la date de la course elle-même, souvent bien plus tard."
    ),
    "aid_stations": (
        "Chaque ravitaillement ajoute un temps d'arrêt FIXE au cumul (`stop_s` de la station si fourni, "
        "sinon `DEFAULT_AID_STATION_STOP_S`, 90 s — approximation du projet, un ravito simple) — "
        "identique pour les trois scénarios (aucune donnée ne justifie un arrêt plus long pour un "
        "scénario plus lent). Un ravito situé au-delà de la fin mesurée du GPX (revue de code #59, "
        "should-fix — ex. tracé GPS coupé avant l'arrivée officielle) n'est jamais supprimé "
        "silencieusement : il est rattaché au temps d'ARRIVÉE (dernier cumul connu), avec une note "
        "explicite. `--official-distance-m` (optionnel) rééchelonne LINÉAIREMENT les `km` de "
        "ravitaillement fournis (supposés en km OFFICIELS de course) sur la distance RÉELLEMENT mesurée "
        "du GPX (`km_gpx = km_officiel × distance_gpx / distance_officielle`) — utile quand un tracé GPS "
        "mesure une distance légèrement différente de la distance officielle de course."
    ),
    "cutoffs": (
        "Une barrière horaire (`aid_station.cutoff`) accepte trois formats (revue de code #59, "
        "should-fix — l'ancien format HH:MM seul ne pouvait pas exprimer une barrière du surlendemain "
        "sur un ultra) : `HH:MM` (jour de course par défaut, ou `cutoff_day` explicite — 1 = jour du "
        "départ, 2 = lendemain, etc. ; SANS `cutoff_day`, une heure antérieure à l'heure de départ est "
        "supposée le LENDEMAIN, comportement historique conservé) ; `+HH:MM` élapsé depuis le départ "
        "(les heures peuvent dépasser 24, ex. `+30:00` pour un ultra) ; une date-heure ISO 8601 complète "
        "(`2026-11-16T10:30:00`) pour une barrière à une date/heure absolue sans ambiguïté, éventuellement "
        "avec décalage (`2026-10-25T12:00:00+01:00`, `…Z` — #205). Un seul parseur "
        "(`_parse_cutoff_dt`) : quand le fuseau de course est connu (`--tz`, champ `timezone` du plan, "
        "#184), `HH:MM` et l'ISO sans décalage sont des heures murales de ce fuseau, l'ISO avec décalage "
        "un instant exact, et les marges sont calculées en temps ABSOLU — justes après un changement "
        "d'heure en pleine course. Sans fuseau connu : heure murale du départ ; une barrière avec "
        "décalage garde alors sa propre heure murale (aucun fuseau deviné). Comparée à "
        "l'heure de passage CUMULÉE de chaque scénario (départ + temps de segment + arrêts ravito). "
        "Marge = barrière − passage. `\"ok\"` si marge ≥ `CUTOFF_MARGIN_OK_S` (30 min — approximation du "
        "projet, pas une règle de course réelle), `\"tendu\"` si 0 ≤ marge < 30 min, `\"hors_delai\"` "
        "si marge < 0 (le scénario n'atteindrait pas la barrière)."
    ),
    "missing_elevation": (
        "Un point GPX sans `<ele>` produit une pente `None` pour les paires qui le touchent "
        "(`arc_elevation.grade_series`) — revue de code #59, blocant : prédire une vitesse `None` sur "
        "ces portions faisait tomber le temps de segment ENTIER à `None`, ignoré par `compute_passages` "
        "comme une contribution nulle (un GPX sans AUCUNE altitude rendait donc un plan à 0 seconde, "
        "`exit 0`, sans le moindre avertissement). Une pente `None` est maintenant traitée comme un "
        "PLAT explicite (grade 0) avec un `reason_code`/une note dédiés (`\"missing_elevation\"`) sur le "
        "segment concerné — `source` est TOUJOURS `\"generic\"` pour ces points (nit, revue de code #59) : "
        "ce n'est jamais une mesure de terrain réelle, dire `\"personal\"` (ce que le modèle rendrait pour "
        "une VRAIE pente plate) prétendrait à une confiance que l'absence d'altitude ne permet pas. ET un "
        "avertissement `warnings` au niveau du "
        "plan dès que la couverture d'altitude du GPX est incomplète (`< 99,5 %` des points) — un GPX "
        "SANS AUCUNE altitude déclenche un avertissement fort (parcours entier traité à plat, D+/D- "
        "inconnus). Le D+/D- total reste, lui, sous-estimé d'autant (aucune donnée pour le calculer) — "
        "l'avertissement le dit explicitement plutôt que de laisser un total plus petit se faire passer "
        "pour un vrai D+/D-."
    ),
    "provenance": (
        "`provenance_summary` rend la part de distance totale prédite par segment `personal`/"
        "`generic`/`mixed` (`arc_slope_model.predict_speed.source`, combinée par segment — un segment "
        "dont les points touchent plusieurs provenances est lui-même `\"mixed\"`) — le critère "
        "d'acceptation #59 (« le plan indique la provenance par segment ») est vérifiable directement "
        "sur `segments[].source`, ce résumé n'est qu'un agrégat pratique pour l'affichage."
    ),
    "energy": (
        "Dépense énergétique PRÉVUE par segment et par scénario, socle "
        "`arc_energy.energy_from_profile` — un CONTRÔLE/OUTIL DE PRÉVISION indépendant "
        "(décision validée avec l'utilisateur), jamais une clé du contrat `race_plan` "
        "persisté : comme `python3 scripts/arc_index.py fueling` (jamais écrit dans le bloc "
        "```arc``` d'un plan de course non plus), `plan.energy` est un KPI DÉRIVÉ recalculable à la "
        "demande depuis le GPX/le modèle personnel — `course-strategist` en tire ce qu'il veut "
        "mettre en PROSE dans le plan persisté (kcal/h, déficit horaire face au ravitaillement), "
        "jamais une nouvelle clé `arc_contract`/`workspace-data-contract` pour ce chantier.\n\n"
        "**Masse** : poids de l'athlète résolu À LA DATE DE LA COURSE (`--race-date`, sinon la date "
        "du jour/`--today`) par `arc_index.resolve_weight_kg_as_of` — LE MÊME résolveur que "
        "`activity_energy`, jamais une seconde implémentation de cette priorité pesée "
        "santé/nutrition puis profil — PLUS `--pack-kg` (sac/flasques/matériel porté, kg). Défaut "
        "`DEFAULT_PACK_KG` (0.0) si `--pack-kg` est omis — AUCUNE valeur « typique » (« un sac de "
        "trail pèse en général... ») n'est inventée sans source vérifiable — avec un avertissement "
        "explicite (`plan.warnings`) invitant à le renseigner pour un calcul plus fidèle. Poids "
        "introuvable (aucune pesée santé/nutrition ni profil plausible à cette date) -> "
        "`energy.available=False`, `energy.reason_code='no_weight'` — le RESTE du plan (segments, "
        "passages, barrières horaires) reste valide et calculé normalement, un poids manquant ne "
        "doit jamais faire échouer tout le plan.\n\n"
        "**Profil point par point réattaché** : `predict_segments` retire délibérément `_profile` "
        "de son export public (voir sa docstring) — sans lui, `energy_from_profile` ne pourrait "
        "intégrer la puissance QUE sur la vitesse moyenne du segment entier (limite documentée dans "
        "`arc_energy.ASSUMPTIONS['race_pacing_integration']`). `_segments_with_profile` réattache "
        "donc le `_profile` conservé par `segment_course` (AVANT que `predict_segments` ne le "
        "retire) à chaque segment prédit, PAR IDENTIFIANT (`s01`, `s02`… stables et alignés entre "
        "les deux listes, issues du MÊME appel à `segment_course`) : la pente locale varie ainsi "
        "point par point dans le calcul d'énergie (voir `ASSUMPTIONS['rolling_terrain']`) — seule "
        "la VITESSE reste celle, moyenne, du couple scénario/segment (limite connue et acceptée, "
        "documentée côté `arc_energy`, pas reproduite en double ici).\n\n"
        "**Par scénario** : les trois scénarios (`safe`/`realistic`/`ambitious`) ont chacun leur "
        "propre vitesse par segment (`predicted_time_s[scenario]`) — `energy_from_profile` est donc "
        "appelé TROIS FOIS (un appel par scénario), jamais une seule fois sur une vitesse moyenne "
        "qui masquerait l'écart de kcal/h attendu entre scénarios. Un scénario plus LENT (« safe ») "
        "a un kcal/h plus faible que « ambitious » sur un même segment en côte (la puissance RE3 "
        "croît avec la vitesse), mais son temps total plus long peut compenser tout ou partie de "
        "cette baisse sur le total kcal de la course entière — AUCUN sens fixe n'est imposé ici sur "
        "le total (contrairement au temps, où « safe » est toujours plus long) : les tests "
        "vérifient la cohérence PHYSIQUE de la formule (kcal/h toujours plus faible à vitesse plus "
        "faible sur une même pente), pas une intuition non vérifiée sur le total.\n\n"
        "**Cumul** : `cumulative_kcal` par segment (somme courante dans l'ORDRE du parcours) — sert "
        "à `course-strategist` pour mettre un plan de ravitaillement PAR SECTION en regard d'un "
        "déficit horaire/cumulé, sans lui imposer de refaire cette somme lui-même.\n\n"
        "**Aucune vitesse prédite du tout (revue de code)** : un scénario dont AUCUN segment n'a de "
        "vitesse prédite (`predicted_time_s[scenario]` à `None` partout, ex. `intensity_source` sans "
        "aucune référence plate personnelle NI générique) rendrait sinon `time_s=0.0`/`kcal=0.0` côté "
        "`arc_energy.energy_from_profile` — un ZÉRO FAUX, jamais distingué d'un vrai « rien à "
        "dépenser ». `race_energy_forecast` traite donc `time_s <= 0` comme AUCUNE prédiction pour ce "
        "scénario (`by_scenario[scenario] = None`, même si d'autres scénarios, eux, ont une "
        "prédiction) ; si LES TROIS scénarios sont dans ce cas, `energy.available=False` avec "
        "`reason_code=\"no_prediction\"` — DISTINCT de `\"no_weight\"` : ici c'est la prédiction de "
        "temps qui manque, jamais le poids, qui lui est bien connu. Un scénario PARTIELLEMENT prédit "
        "(certains segments avec vitesse, d'autres sans) reste disponible : `n_segments_no_speed` "
        "compte, PAR SCÉNARIO, les segments sans contribution énergétique (distance comptée, kcal "
        "non) — jamais une sous-estimation silencieuse du kcal total.\n\n"
        "**`--pack-kg` validé, pas seulement clampé (revue de code)** : `PACK_KG_MIN`/`PACK_KG_MAX` "
        "(0-30 kg, approximation du projet — écarte une saisie manifestement fausse, ex. confusion "
        "kg/lb ou poids CORPOREL saisi par erreur, sans prétendre encadrer ce qu'un athlète peut "
        "raisonnablement porter) et une valeur non finie (NaN/infini) sont REJETÉS avec une erreur "
        "CLI explicite (`_validate_pack_kg`), jamais acceptés silencieusement pour ne pas fausser la "
        "masse totale et donc tout le calcul.\n\n"
        "**Arrêts ravito EXCLUS du calcul d'énergie (limite connue, revue de code)** : "
        "`compute_passages`/`DEFAULT_AID_STATION_STOP_S` ajoutent le temps d'arrêt aux ravitos "
        "UNIQUEMENT aux temps de PASSAGE cumulés (barrières horaires) — `race_energy_forecast` ne "
        "reçoit que les `segments` du parcours, jamais les arrêts ravito, et n'ajoute donc AUCUN kcal "
        "pour le temps passé à l'arrêt (même le métabolisme debout, `arc_energy.STANDING_POWER_W_KG`, "
        "n'est PAS compté pendant un arrêt ravito). Le kcal total prévu est donc une SOUS-ESTIMATION "
        "connue et non corrigée pour une course à ravitos nombreux/longs — jamais présentée comme une "
        "mesure exacte du besoin énergétique total de la journée de course.\n\n"
        "**`heat_factor` : limite connue, non corrigée (revue de code)** : `heat_time_factor` "
        "RALENTIT la vitesse effective (`effective_speed = base_speed / heat_factor`, voir "
        "`predict_segments`) sans ajouter aucun coût métabolique supplémentaire propre à la chaleur "
        "(sudation accrue, effort cardiovasculaire de thermorégulation — aucune source vérifiable "
        "n'est citée dans ce projet pour chiffrer ce surcoût). Une vitesse plus lente à pente "
        "identique donne, dans le modèle RE3, une puissance (donc un kcal/h) PLUS FAIBLE — le kcal/h "
        "prévu BAISSE donc sous la chaleur alors que le coût énergétique RÉEL d'un effort par forte "
        "chaleur est plus élevé (thermorégulation, fréquence cardiaque plus haute à vitesse égale). "
        "Ce n'est PAS corrigé ici : `plan.energy` reste un contrôle/une prévision utile pour l'ordre "
        "de grandeur et la RÉPARTITION par section, jamais une mesure fine du surcoût thermique — à "
        "dire explicitement si l'athlète pose la question par forte chaleur prévue.\n\n"
        "**Calibration personnelle (`plan.energy.calibration`)** : `arc_index.energy_calibration` "
        "(voir `arc_energy.ASSUMPTIONS['calibration']`) rend, par panier route/trail, un ratio médian "
        "Garmin/modèle appris sur l'historique RÉEL de l'athlète — appliqué ICI, sur les valeurs "
        "PRÉVUES uniquement (jamais sur une séance déjà mesurée, `activity_energy` reste le calcul "
        "BRUT). Le panier (route OU trail) est choisi depuis LE PARCOURS analysé, PAS depuis le "
        "profil de l'athlète (`resolve_calibration_band`, correctif de revue de code, BLOQUANT : une "
        "version antérieure utilisait `conf['sport']['primary']`, le profil GÉNÉRAL de l'athlète — un "
        "plan préparé pour une course de nature différente de ce profil habituel aurait alors calibré "
        "sur le MAUVAIS panier) : sans `--terrain`, dérivé du D+/km RÉEL de CE GPX "
        "(`TRAIL_GAIN_M_PER_KM`, 15 m/km, **approximation du projet**, aucun seuil publié identifié) "
        "-> `band_source=\"gpx\"` ; `--terrain road|trail` (choix EXPLICITE de l'athlète, qui peut "
        "savoir des choses que le tracé seul ne dit pas) prime TOUJOURS quand fourni -> "
        "`band_source=\"option\"`. `kcal_calibrated`/`kcal_per_h_calibrated`/"
        "`cumulative_kcal_calibrated` sont ajoutés À CÔTÉ de `kcal`/`kcal_per_h`/`cumulative_kcal` "
        "bruts, PAR SCÉNARIO ET PAR SEGMENT (`by_scenario[scenario]` et chaque "
        "`by_scenario[scenario]['segments'][i]`), JAMAIS à leur place — le facteur, SCALAIRE UNIQUE "
        "par scénario, s'applique UNIFORMÉMENT segment par segment (exact PAR LINÉARITÉ, jamais une "
        "fausse précision locale). `status` `insufficient`/`not_needed` (échantillon insuffisant, ou "
        "modèle déjà fidèle sur ce panier) donne des valeurs calibrées STRICTEMENT ÉGALES aux brutes "
        "(facteur 1.0), jamais une fausse différence. `plan.energy.calibration` (`{\"band\", "
        "\"band_source\", \"n\", \"ratio_median\", \"ratio_iqr\", \"status\", \"factor\"}`) est "
        "TOUJOURS présent quand `energy.available=True`, même `status=\"insufficient\"` — un agent "
        "qui veut savoir SI une calibration a été appliquée lit ce seul champ, jamais une comparaison "
        "manuelle brut/calibré."
    ),
    "night": (
        "Pénalité de NUIT (#184, épopée #170). Le calcul n'a lieu que si TROIS entrées sont connues : "
        "la date de course (`--race-date`), l'heure de départ EXPLICITE (`--start`, jamais le défaut "
        "07:00) et le fuseau horaire IANA (`--tz`, ex. Europe/Paris) ; sinon `night.status = "
        "\"unavailable\"` avec la raison, AUCUN facteur de nuit n'est appliqué et la sortie reste "
        "identique à celle d'avant #184 (hors la clé additive `night`). `--no-night` le désactive "
        "explicitement. Heures de lever/coucher et crépuscule civil calculées localement, sans réseau "
        "(`arc_solar.py`, algorithme NOAA, approximation de l'ordre de la minute) à la position du "
        "PREMIER point du GPX (approximation : sur un ultra qui traverse plusieurs degrés de longitude, "
        "l'écart est de ~4 min par degré). « Nuit » = soleil à plus de 6° sous l'horizon (crépuscule "
        "civil, convention) : c'est la limite retenue pour la frontale, avec une marge à prévoir "
        "côté athlète (forêt, ciel couvert).\n\n"
        "**Fraction de nuit par section et par scénario** (`night_fraction`, part du TEMPS DE COURSE "
        "de la section — arrêts ravito exclus — passée de nuit) d'après l'heure d'horloge de chaque "
        "section, déduite du départ, des temps de section déjà pénalisés et des arrêts ravito. "
        "**Facteur** (`night_factor`, multiplicateur du temps) = 1 + `night_fraction` × pénalité, "
        "avec pénalité = `NIGHT_BASE_PENALTY_PCT` (5 %) à plat/en montée, plus en DESCENTE "
        "`NIGHT_DESCENT_EXTRA_PER_GRADE_PCT` (0,6 point par % de pente au-delà de "
        "`NIGHT_DESCENT_FREE_GRADE_PCT` = 2 %), plafonné à `NIGHT_DESCENT_EXTRA_MAX_PCT` (8 points) "
        "— la pente utilisée est la pente MOYENNE de la section (`grade_mean_pct`). **Approximations "
        "du projet, jamais des mesures** : aucune source vérifiée ne chiffre ces pourcentages pour "
        "cet athlète ; réglables par `--night-penalty-pct` et `--night-descent-extra-max-pct`, et "
        "l'écart réel s'apprend au débrief (#188).\n\n"
        "**Itération** : la pénalité ralentit, donc décale l'heure de passage des sections suivantes "
        "et leur fraction de nuit. Le calcul itère (au plus `NIGHT_MAX_ITERATIONS` = 8 passes, arrêt "
        "quand le facteur varie de moins de `NIGHT_CONVERGENCE_TOL`) ; `night.iterations` et "
        "`night.converged` le disent. **Cohérence des scénarios** : après chaque passe le temps de "
        "chaque section est forcé à `prudent >= réaliste >= ambitieux` (une section de nuit pleine "
        "pénalisée pour l'un et de jour pour l'autre ne doit jamais inverser l'ordre) ; "
        "`night.scenario_order_clamped_segments` compte les sections concernées. La pénalité "
        "s'applique APRÈS la renormalisation neutre du fade et la chaleur, et avant les passages et "
        "barrières horaires (qui en tiennent donc compte).\n\n"
        "**Résumé par scénario** (`night.scenarios[s]`) : `night_duration_s` (temps passé de nuit "
        "entre le départ et l'arrivée, arrêts compris — on a besoin de lumière à l'arrêt aussi), "
        "`lamp_from`/`lamp_until` (premier et dernier instant de nuit pendant la course, heure "
        "locale ISO) et `summary` en français. Une course entièrement de jour n'émet AUCUN champ "
        "`night_*` par section (`night.status = \"daylight\"`). Le contrôle de la frontale dans le "
        "matériel obligatoire reste celui de `arc_index.py equipment --race-plan` (#134) : "
        "`night.gear_hint` y renvoie, rien n'est dupliqué ici. Cas polaire : nuit blanche = zéro nuit, "
        "nuit polaire = nuit continue (masque calculé sur l'altitude du soleil minute par minute).\n\n"
        "**Horloge** : le temps écoulé est compté en UTC (une course qui traverse le passage à l'heure "
        "d'hiver ne glisse pas d'une heure) ; seul l'affichage (`lamp_from`, `summary`) est en heure "
        "locale du fuseau, décalage du moment compris. Une section dont l'ordre des scénarios a été "
        "forcé porte un `night_factor` qui inclut ce forçage (multiplicateur réellement appliqué), pas "
        "seulement la nuit. **Fuseau** : aucune base hors-ligne lieu → fuseau dans la bibliothèque "
        "standard, le fuseau est donc une ENTRÉE ; contrôle grossier de vraisemblance seulement "
        "(`NIGHT_TZ_SUSPECT_OFFSET_H` = 3,5 h d'écart entre le décalage UTC du fuseau et l'heure "
        "solaire de la longitude du départ → `night.timezone_warning` et avertissement, jamais un "
        "refus ; une erreur d'une heure passe inaperçue)."
    ),
    "technicity": (
        "Coefficient de TECHNICITÉ du terrain par section (#186, épopée #170), appliqué EN PLUS du modèle "
        "pente -> allure, de la chaleur et de la nuit ; opt-in (`--technicity`), sinon l'étape n'existe pas "
        "(aucune clé `technicity`, temps inchangés octet pour octet). Deux sources, la déclaration gagnant "
        "section par section : (a) **déclarée** (`--technicity fichier.json`, "
        "`{\"sections\": [{\"km_start\", \"km_end\", \"coef\", \"note\"}]}`, coef dans [0,8 ; 1,8], 1,0 = terrain "
        "« comme à l'entraînement », 1,25 = très technique ; km OFFICIELS, rééchelonnés sur la distance "
        "mesurée du GPX avec `--official-distance-m` comme les ravitos) — retenue pour un segment couvert à "
        "au moins 50 % ; "
        "(b) **dérivée d'OpenStreetMap** (`--technicity osm`, RÉSEAU, jamais par défaut) : requête Overpass "
        "(`out tags geom`) des chemins `highway` (path, track, footway, steps, routes mineures) dans une boîte "
        "autour de chaque tronçon de ~8 km de la trace (marge 60 m, boîtes arrondies à ~10 m), trace "
        "échantillonnée tous les 40 m, appariement au chemin le plus proche à moins de 20 m "
        "(`MATCH_RADIUS_M`), coefficient du segment = moyenne pondérée par la distance des points appariés ; "
        "moins de 30 % de points appariés -> aucun coefficient (source `none`, 1,0), jamais une valeur "
        "inventée. Réponses mises en cache dans `<workspace>/.arc/overpass/` (une requête = un fichier) ; une "
        "requête à la fois, 1,5 s de pause entre deux requêtes réseau, User-Agent explicite (politique de "
        "l'instance publique) ; HTTP 429/502/503/504 -> au plus 2 nouvelles tentatives (`Retry-After` ou "
        "5 s puis 10 s, plafond 30 s) ; une réponse HTTP 200 portant une erreur d'exécution Overpass "
        "(`remark`, ex. délai dépassé) est un ÉCHEC, jamais mise en cache. Le cache n'expire pas (les tags "
        "OSM évoluent lentement) : supprimer `.arc/overpass/` pour rafraîchir. **Seuls des GPX de COURSE** sont concernés : seules des boîtes englobantes "
        "arrondies partent, jamais une trace d'activité personnelle. Hors ligne ou Overpass en erreur -> "
        "`technicity.osm.status = \"unavailable\"`, note explicite et avertissement, aucun coefficient OSM "
        "(tout ou rien : pas de coefficient sur la moitié d'un parcours).\n\n"
        "**Table tags -> coefficient (APPROXIMATIONS DU PROJET, jamais des mesures ni une source "
        "publiée)** : surcoût de temps (coef - 1) par tag. `sac_scale` : hiking 0 / mountain_hiking +6 % / "
        "demanding_mountain_hiking +15 % / alpine_hiking +30 % / demanding_alpine_hiking +45 % / "
        "difficult_alpine_hiking +60 %. `trail_visibility` : excellent, good 0 / intermediate +5 % / bad +12 % "
        "/ horrible +25 % / no +35 %. `surface` : asphalt, paved, concrete, compacted, fine_gravel 0 / gravel, "
        "unpaved, ground, dirt, earth +3 % / grass +4 % / pebblestone +8 % / rock +12 % / sand, mud, snow "
        "+15 %. `tracktype` : grade1-2 0 / grade3 +3 % / grade4 +6 % / grade5 +10 %. `highway` : steps +15 % / "
        "path +2 % / autres 0. Ordre de grandeur seulement : en T5-T6 (passages d'escalade facile, "
        "désescalade) le ralentissement réel peut dépasser +60 %, le plafond reste prudent dans l'autre "
        "sens (pas de prédiction extrême tirée d'un tag). **Combinaison** : surcoût dominant + la moitié du deuxième (les tags sont "
        "corrélés : un sentier alpin est presque toujours « mauvaise visibilité » et « rocheux », on "
        "n'additionne pas), plafonné à 1,8. Un coefficient dérivé d'OSM ne descend JAMAIS sous 1,0 (aucun "
        "crédit de vitesse tiré de tags incertains) ; une valeur de tag inconnue est ignorée, jamais "
        "devinée ; un chemin sans aucun tag exploitable vaut 1,0.\n\n"
        "**Pente** : le surcoût est pondéré par la pente MOYENNE de la section — `effective_factor` = 1 + "
        "(coef - 1) × poids : ×0,7 en montée (> +2 %, l'effort y est limité par la puissance plus que par "
        "l'appui), ×1,0 à plat (|pente| <= 2 %), de ×1,0 à ×1,5 en descente (pleine à -12 %) car un terrain "
        "technique ralentit surtout la descente. Pente inconnue = ×1,0. Approximations du projet.\n\n"
        "**Composition et scénarios** : `effective_factor` multiplie les temps (et allures) de la section "
        "pour les TROIS scénarios à l'identique — un même facteur positif sur trois temps ordonnés conserve "
        "prudent >= réaliste >= ambitieux par construction (aucun écrêtage nécessaire), et la dispersion des "
        "scénarios reste relative ; aucune donnée ne justifie de moduler la technicité par scénario. L'étape "
        "s'applique APRÈS le fade neutre et la chaleur et AVANT la nuit : la technicité est une propriété du "
        "terrain, pas de l'horloge, et l'itération de nuit part des temps déjà corrigés, donc des heures de "
        "passage cohérentes (les deux facteurs se multiplient). **Limite à connaître** : le modèle personnel "
        "pente -> allure a été appris sur les sorties de l'athlète, qui contiennent déjà son terrain habituel "
        "— un coefficient DÉCLARÉ exprime l'écart par rapport à CE terrain (1,0 = « comme à "
        "l'entraînement »). La table OSM, elle, est ABSOLUE (1,0 = chemin facile) : elle est donc rapportée "
        "au terrain habituel déclaré par `--technicity-baseline` (nombre ou valeur `sac_scale`, ex. "
        "`mountain_hiking` = 1,06) — coef appliqué = max(1,0 ; coef OSM / référence), valeur absolue "
        "conservée dans `osm_coef`. Sans référence déclarée, la référence vaut 1,0 et un avertissement dit "
        "que la pénalité est surestimée pour un athlète qui s'entraîne déjà en montagne (double comptage) ; "
        "la référence n'est JAMAIS dérivée des traces d'entraînement (ce serait envoyer des traces "
        "personnelles à Overpass). OSM décrit le chemin, pas l'état du jour (boue, neige, "
        "éboulis récents) et ses tags sont inégalement renseignés. Réglable (fichier déclaré), jamais une "
        "vérité ; l'écart réel s'apprend au débrief (#188).\n\n"
        "**Sortie** : par section `technicity` = `{coef, effective_factor, source (declared | osm | none), "
        "tags (déclaration : notes ; OSM : trois tags les plus présents), coverage_pct, osm_coef si référence}` ; "
        "au niveau du plan "
        "`technicity` = `{status, sources_requested, osm, distance_pct_by_source, mean_coef, max_coef, "
        "scenario_scaling}`."
    ),
    "altitude": AL.ASSUMPTIONS["race_penalty"] + " " + AL.ASSUMPTIONS["acclimation"],
}


# ---------------------------------------------------------------------------
# GPX -> points (duplication volontaire et minimale de
# `skills/gpx-analysis/scripts/analyze_gpx.parse_gpx`/`haversine` : le moteur
# racine ne doit jamais dépendre d'un script de skill, voir le docstring du
# module — sens de dépendance unique skill -> moteur, jamais l'inverse).
# ---------------------------------------------------------------------------

def parse_gpx(path: Path) -> List[dict]:
    """Extrait la liste ordonnée des points `{lat, lon, ele}` de TOUS les
    `trk`/`trkseg` du fichier, concaténés dans l'ordre du document (pas
    seulement le premier — un GPX à plusieurs segments/traces reste rare pour
    un parcours de course, mais rien ici ne le suppose)."""
    tree = ET.parse(path)
    root = tree.getroot()
    pts: List[dict] = []
    for trkpt in root.iter():
        tag = trkpt.tag.rsplit("}", 1)[-1]
        if tag != "trkpt":
            continue
        try:
            lat = float(trkpt.attrib["lat"])
            lon = float(trkpt.attrib["lon"])
        except (KeyError, ValueError):
            continue
        ele = None
        for child in trkpt:
            if child.tag.rsplit("}", 1)[-1] == "ele":
                try:
                    ele = float(child.text)
                except (TypeError, ValueError):
                    pass
        pts.append({"lat": lat, "lon": lon, "ele": ele})
    return pts


def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distance en mètres entre deux points GPS (formule de Haversine)."""
    R = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def _cumulative_distances(pts: Sequence[dict]) -> List[float]:
    dist = [0.0]
    for i in range(1, len(pts)):
        dist.append(dist[-1] + haversine(pts[i - 1]["lat"], pts[i - 1]["lon"], pts[i]["lat"], pts[i]["lon"]))
    return dist


def elevation_coverage_pct(pts: Sequence[dict]) -> float:
    """Part (0-100) des points GPX porteurs d'une altitude — voir
    `ASSUMPTIONS["missing_elevation"]`. `100.0` pour une liste vide (rien à
    signaler)."""
    if not pts:
        return 100.0
    known = sum(1 for p in pts if p.get("ele") is not None)
    return known / len(pts) * 100.0


def course_totals(pts: Sequence[dict], *, smooth_taps: int = EL.DEFAULT_SMOOTH_TAPS) -> Tuple[float, float, float]:
    """Distance/D+/D- TOTAUX du GPX, calcul LÉGER (même lissage d'altitude que
    `segment_course`, mais sans segmentation) — utilisé par `main()` pour
    résoudre `intensity_factor` depuis les totaux du GPX RÉELLEMENT analysé,
    jamais depuis `planning/active_objective.md` (voir
    `ASSUMPTIONS["base_pace"]`, revue de code #59, BLOQUANT). `(0.0, 0.0, 0.0)`
    pour moins de 2 points."""
    if len(pts) < 2:
        return 0.0, 0.0, 0.0
    dist = _cumulative_distances(pts)
    ele_smooth = EL.smooth_moving_average([p.get("ele") for p in pts], smooth_taps)
    gain = loss = 0.0
    for k in range(1, len(pts)):
        a, b = ele_smooth[k - 1], ele_smooth[k]
        if a is None or b is None:
            continue
        d = b - a
        if d > 0:
            gain += d
        else:
            loss += -d
    return dist[-1], gain, loss


# ---------------------------------------------------------------------------
# Segmentation
# ---------------------------------------------------------------------------

def _weighted_mean(values: Sequence[Optional[float]], weights: Sequence[float]) -> Optional[float]:
    pairs = [(v, w) for v, w in zip(values, weights) if v is not None and w > 0]
    if not pairs:
        return None
    total_w = sum(w for _, w in pairs)
    return sum(v * w for v, w in pairs) / total_w


def _profile_for(dist: Sequence[float], grades: Sequence[Optional[float]],
                  i_start: int, i_end: int) -> List[Tuple[float, Optional[float]]]:
    """Profil `[(dx_m, grade), ...]` pour chaque paire de points consécutifs de
    `[i_start, i_end]` — consommé par `predict_segments` pour intégrer `Δd /
    v(pente locale)` (voir `ASSUMPTIONS["rolling_terrain"]`). `grade` est la
    moyenne des pentes des deux points de la paire (déjà lissées par
    `arc_elevation.grade_series`), l'une ou l'autre si une seule est connue,
    `None` si aucune (altitude manquante des deux côtés — voir
    `ASSUMPTIONS["missing_elevation"]`)."""
    profile: List[Tuple[float, Optional[float]]] = []
    for k in range(i_start + 1, i_end + 1):
        dx = dist[k] - dist[k - 1]
        if dx <= 0:
            continue
        g_a, g_b = grades[k - 1], grades[k]
        if g_a is not None and g_b is not None:
            g = (g_a + g_b) / 2.0
        elif g_a is not None:
            g = g_a
        elif g_b is not None:
            g = g_b
        else:
            g = None
        profile.append((dx, g))
    return profile


def _raw_segment(dist: Sequence[float], grades: Sequence[Optional[float]],
                  ele_smooth: Sequence[Optional[float]], i_start: int, i_end: int) -> dict:
    """Segment brut sur les indices [i_start, i_end] (inclusifs), AVANT fusion."""
    idx = list(range(i_start, i_end + 1))
    seg_weights = []
    for k in idx:
        prev = max(i_start, k - 1)
        seg_weights.append(max(0.0, dist[k] - dist[prev]) if k > i_start else 0.0)
    grade_mean = _weighted_mean([grades[k] for k in idx], [max(w, 1e-6) for w in seg_weights] or [1.0])
    gain = loss = 0.0
    for k in range(i_start + 1, i_end + 1):
        a, b = ele_smooth[k - 1], ele_smooth[k]
        if a is None or b is None:
            continue
        d = b - a
        if d > 0:
            gain += d
        else:
            loss += -d
    return {
        "i_start": i_start, "i_end": i_end,
        "km_start": round(dist[i_start] / 1000.0, 3),
        "km_end": round(dist[i_end] / 1000.0, 3),
        "distance_m": round(dist[i_end] - dist[i_start], 1),
        "grade_mean_pct": round(grade_mean * 100.0, 2) if grade_mean is not None else None,
        "elevation_gain_m": round(gain, 1),
        "elevation_loss_m": round(loss, 1),
        "_profile": _profile_for(dist, grades, i_start, i_end),
    }


def _merge_raw(a: dict, dist: Sequence[float], grades: Sequence[Optional[float]],
               ele_smooth: Sequence[Optional[float]], b: dict) -> dict:
    return _raw_segment(dist, grades, ele_smooth, a["i_start"], b["i_end"])


def segment_course(pts: Sequence[dict], *, target_segment_m: float = DEFAULT_SEGMENT_M,
                    min_segment_m: float = MIN_SEGMENT_M,
                    max_segment_factor: float = MAX_SEGMENT_FACTOR,
                    merge_grade_delta_pct: float = MERGE_GRADE_DELTA_PCT,
                    window_m: float = EL.DEFAULT_GRADE_WINDOW_M,
                    smooth_taps: int = EL.DEFAULT_SMOOTH_TAPS) -> List[dict]:
    """Découpe un parcours GPX (points `{lat, lon, ele}`, déjà parsés par
    `parse_gpx`) en segments de longueur cible fusionnés par pente similaire —
    voir `ASSUMPTIONS["segmentation"]` pour la méthode complète. Rend une liste
    VIDE si moins de 2 points exploitables (rien à segmenter).

    Chaque segment porte les champs PUBLICS du contrat (`id`, `km_start`,
    `km_end`, `distance_m`, `grade_mean_pct` — signé, `None` si non calculable
    sur tout le segment —, `elevation_gain_m`, `elevation_loss_m`) PLUS une clé
    privée `_profile` (voir `_profile_for`), consommée par `predict_segments`
    et jamais émise dans le JSON final du plan."""
    if len(pts) < 2:
        return []
    dist = _cumulative_distances(pts)
    raw_ele = [p.get("ele") for p in pts]
    ele_smooth = EL.smooth_moving_average(raw_ele, smooth_taps)
    samples = [{"t_s": float(i), "distance_m": dist[i], "altitude_m": raw_ele[i]} for i in range(len(pts))]
    graded = EL.grade_series(samples, window_m=window_m, smooth_taps=smooth_taps)
    grades = [s["grade"] for s in graded]  # aligné : grade_series trie par t_s, déjà croissant ici

    n = len(pts)
    total_m = dist[-1]
    if total_m <= 0:
        return []

    # 1) Découpage brut en tranches de distance ~cible.
    raws: List[dict] = []
    i_start = 0
    next_boundary = target_segment_m
    for i in range(1, n):
        if dist[i] >= next_boundary or i == n - 1:
            raws.append(_raw_segment(dist, grades, ele_smooth, i_start, i))
            i_start = i
            next_boundary = dist[i] + target_segment_m
            if i == n - 1:
                break
    if not raws:
        raws = [_raw_segment(dist, grades, ele_smooth, 0, n - 1)]

    # 2) Fusion greedy des segments adjacents de pente similaire, plafonnée en
    # longueur (voir ASSUMPTIONS["segmentation"]) — couvre maintenant aussi le
    # DERNIER segment (revue de code #59 : l'ancienne fusion inconditionnelle
    # du reliquat final, avant cette passe, ignorait la pente).
    max_segment_m = target_segment_m * max_segment_factor
    merged: List[dict] = []
    for seg in raws:
        if merged:
            prev = merged[-1]
            prev_grade, seg_grade = prev["grade_mean_pct"], seg["grade_mean_pct"]
            combined_len = prev["distance_m"] + seg["distance_m"]
            similar = (prev_grade is not None and seg_grade is not None
                       and abs(prev_grade - seg_grade) <= merge_grade_delta_pct)
            if similar and combined_len <= max_segment_m:
                merged[-1] = _merge_raw(prev, dist, grades, ele_smooth, seg)
                continue
        merged.append(dict(seg))

    # 3) Dernier recours (revue de code #59) : un reliquat encore trop court
    # APRÈS la fusion par pente (terrain trop varié pour fusionner « proprement »)
    # est fusionné dans le précédent quelle que soit sa pente — jamais un
    # segment orphelin de quelques mètres.
    if len(merged) > 1 and merged[-1]["distance_m"] < min_segment_m:
        merged[-2] = _merge_raw(merged[-2], dist, grades, ele_smooth, merged[-1])
        merged.pop()

    width = max(2, len(str(len(merged))))
    out = []
    for i, seg in enumerate(merged, start=1):
        out.append({
            "id": f"s{i:0{width}d}",
            "km_start": seg["km_start"],
            "km_end": seg["km_end"],
            "distance_m": seg["distance_m"],
            "grade_mean_pct": seg["grade_mean_pct"],
            "elevation_gain_m": seg["elevation_gain_m"],
            "elevation_loss_m": seg["elevation_loss_m"],
            "_profile": seg["_profile"],
        })
    return out


# ---------------------------------------------------------------------------
# Prédiction par segment
# ---------------------------------------------------------------------------

# Panier CENTRAL du modèle (celui qui contient la pente 0, `arc_slope_model.GRADE_BINS`)
# — repli de `_snap_grade_to_bin` (voir `ASSUMPTIONS["rolling_terrain"]`) pour
# un `bins` de test sans `grade_lo`/`grade_hi`.
_CENTER_BIN_LO, _CENTER_BIN_HI = next((lo, hi) for lo, hi, _ in SL.GRADE_BINS if lo <= 0.0 < hi)


def _snap_grade_to_bin(grade: Optional[float], bins: Sequence[dict]) -> Optional[float]:
    """Neutralise l'interpolation de `predict_speed` pour une pente qui tombe
    dans l'intervalle `[lo, hi)` d'un panier PERSONNEL de `bins` — voir
    `ASSUMPTIONS["rolling_terrain"]` (2ᵉ revue de code #59, should-fix). Rend
    exactement le point milieu de ce panier, jamais la pente brute. Un panier
    sans `grade_lo`/`grade_hi` (clés absentes — fixtures de test à un seul
    point) est IGNORÉ pour cette recherche, jamais traité comme couvrant
    `[-inf, +inf)` (ce que renverrait `dict.get` par défaut). Repli, si aucun
    panier personnel ne couvre `grade` : neutralise seulement le panier
    CENTRAL canonique du modèle (`_CENTER_BIN_LO`/`_CENTER_BIN_HI`)."""
    if grade is None:
        return None
    for b in bins:
        if b.get("source") != "personal" or "grade_lo" not in b or "grade_hi" not in b:
            continue
        lo = b["grade_lo"] if b["grade_lo"] is not None else float("-inf")
        hi = b["grade_hi"] if b["grade_hi"] is not None else float("inf")
        if lo <= grade < hi:
            return b["grade_mid"]
    if _CENTER_BIN_LO <= grade < _CENTER_BIN_HI:
        return 0.0
    return grade


def fade_speed_multiplier(km_frac: float, fade_pct: float) -> float:
    """Multiplicateur de vitesse (<= 1.0, jamais sous `FADE_MIN_SPEED_FACTOR`)
    au point `km_frac` (0-1, fraction de la distance totale de course) pour un
    fade GAP `fade_pct` (%) mesuré entre premier et dernier tiers d'une sortie
    longue — voir `ASSUMPTIONS["fade"]` pour la calibration complète (rampe
    linéaire à partir du premier tiers, `FADE_LAST_THIRD_MEAN_FACTOR` pour que
    la MOYENNE du dernier tiers égale exactement `fade_pct`)."""
    if fade_pct <= 0 or km_frac <= 1.0 / 3.0:
        return 1.0
    t = min(1.0, (km_frac - 1.0 / 3.0) / (2.0 / 3.0))
    reduction = t * FADE_LAST_THIRD_MEAN_FACTOR * (fade_pct / 100.0)
    return max(FADE_MIN_SPEED_FACTOR, 1.0 - reduction)


def scale_fade_to_duration(fade_pct: float, predicted_duration_s: Optional[float]) -> float:
    """Échelonne un `fade_pct` mesuré/générique sur SORTIE LONGUE
    (`arc_metrics.LONG_RUN_MIN_DURATION_S`, 90 min) à la durée RÉELLE de la
    course prédite — voir `ASSUMPTIONS["fade"]`. `predicted_duration_s`
    inconnu (`None`) laisse `fade_pct` inchangé (rien à échelonner sans une
    estimation de durée)."""
    if fade_pct <= 0 or predicted_duration_s is None:
        return fade_pct
    scale = min(1.0, max(0.0, predicted_duration_s / M.LONG_RUN_MIN_DURATION_S))
    return fade_pct * scale


def _scale_prediction_speeds(prediction: dict, factor: float) -> dict:
    """Multiplie les vitesses d'une prédiction (`speed_ms`/`ci_low_speed_ms`/
    `ci_high_speed_ms`) par `factor` (`intensity_factor`, voir
    `ASSUMPTIONS["base_pace"]`) — `source`/`reason_code` inchangés (la
    provenance ne dépend pas de l'intensité, seule la vitesse est mise à
    l'échelle)."""
    if factor == 1.0:
        return prediction
    scaled = dict(prediction)
    for key in ("speed_ms", "ci_low_speed_ms", "ci_high_speed_ms"):
        if scaled.get(key) is not None:
            scaled[key] = scaled[key] * factor
    return scaled


def _scenario_speeds(prediction: dict, *, safe_factor: float = GENERIC_SCENARIO_SPEED_FACTOR["safe"]
                      ) -> Dict[str, Optional[float]]:
    """Vitesse par scénario — voir `ASSUMPTIONS["scenarios"]` pour l'écart
    PLANCHER appliqué à une dispersion personnelle mesurée trop étroite.
    `safe_factor` (défaut : plancher générique -8 %) remplace ce plancher côté
    « safe » UNIQUEMENT — voir `ASSUMPTIONS["base_pace"]` pour le cas d'une
    extrapolation Riegel trop lointaine (`EXTRAPOLATION_SAFE_SCENARIO_FACTOR`,
    -12 %), jamais le côté « ambitious »."""
    speed = prediction.get("speed_ms")
    if speed is None:
        return {s: None for s in SCENARIOS}
    ci_low, ci_high = prediction.get("ci_low_speed_ms"), prediction.get("ci_high_speed_ms")
    ambitious_factor = GENERIC_SCENARIO_SPEED_FACTOR["ambitious"]
    if ci_low is not None and ci_high is not None:
        safe_speed = min(ci_low, speed * safe_factor)
        ambitious_speed = max(ci_high, speed * ambitious_factor)
        return {"safe": safe_speed, "realistic": speed, "ambitious": ambitious_speed}
    return {"safe": speed * safe_factor, "realistic": speed, "ambitious": speed * ambitious_factor}


def _segment_intervals(seg: dict) -> List[Tuple[float, Optional[float]]]:
    """Sous-intervalles `(dx_m, grade)` à intégrer pour ce segment — un segment
    RÉEL (`segment_course`) porte `_profile` (une entrée par paire de points
    GPX) ; un segment construit à la main (tests, pas de GPX) retombe sur UN
    SEUL intervalle couvrant `distance_m` à `grade_mean_pct` — mathématiquement
    équivalent au calcul par pente unique quand la pente est réellement
    uniforme sur tout le segment."""
    profile = seg.get("_profile")
    if profile:
        return profile
    grade = seg["grade_mean_pct"] / 100.0 if seg.get("grade_mean_pct") is not None else None
    return [(seg.get("distance_m") or 0.0, grade)]


def _combine_sources(sources: Sequence[Optional[str]]) -> Optional[str]:
    """Provenance représentative d'un segment à partir de la provenance de
    CHACUN de ses intervalles — `None` si aucun intervalle n'a de provenance,
    la provenance commune si tous s'accordent, `"mixed"` sinon (même sémantique
    que `arc_slope_model.predict_speed` pour un point isolé, étendue au
    segment)."""
    uniq = {s for s in sources if s is not None}
    if not uniq:
        return None
    if len(uniq) == 1:
        return next(iter(uniq))
    return "mixed"


def predict_segments(segments: Sequence[dict], bins: Sequence[dict], *,
                      fade_pct: float = 0.0, heat_factor: float = 1.0,
                      intensity_factor: float = 1.0,
                      safe_scenario_factor: float = GENERIC_SCENARIO_SPEED_FACTOR["safe"]) -> List[dict]:
    """Augmente chaque segment (`segment_course`) d'une prédiction de temps par
    scénario — pure, aucun accès disque. `bins` : `model["bins"]` d'un rapport
    `arc_slope_model.fit_slope_model`/`arc_index.slope_model_report`.
    `safe_scenario_factor` : plancher du scénario « safe », élargi
    (`EXTRAPOLATION_SAFE_SCENARIO_FACTOR`) quand la cible extrapole trop loin
    de la référence Riegel — voir `ASSUMPTIONS["base_pace"]`.

    Intègre `Δd / v(pente locale)` sur chaque sous-intervalle du segment (voir
    `ASSUMPTIONS["rolling_terrain"]`) plutôt que de prédire une seule fois sur
    la pente moyenne — jamais la même approximation pour un vrai plat et un
    profil vallonné à moyenne nulle. Une pente manquante (altitude GPX
    absente) est traitée comme un plat explicite, jamais une prédiction
    `None` silencieuse (voir `ASSUMPTIONS["missing_elevation"]`).

    Rend une COPIE des segments (champs publics uniquement — `_profile` et
    tout champ interne ne sont jamais réémis), chacun augmenté de `source`,
    `reason_code` (informationnel, ex. `"extrapolated"`/`"missing_elevation"`/
    `"no_model"`), `predicted_time_s` (objet par scénario, secondes entières —
    voir `SEGMENT_ROUND_S`), `pace_s_km` (objet par scénario), `notes` (liste
    de courtes explications)."""
    total_m = sum(seg["distance_m"] for seg in segments) or 1.0
    cum_m = 0.0
    out = []
    for seg in segments:
        intervals = _segment_intervals(seg)
        seg_total_m = sum(dx for dx, _ in intervals) or seg.get("distance_m") or 0.0

        time_acc: Dict[str, float] = {s: 0.0 for s in SCENARIOS}
        has_speed: Dict[str, bool] = {s: False for s in SCENARIOS}
        sources: List[Optional[str]] = []
        reason_codes: Set[str] = set()
        missing_elevation_m = 0.0
        cum_local = 0.0

        for dx, grade in intervals:
            if dx <= 0:
                continue
            point_frac = (cum_m + cum_local + dx / 2.0) / total_m
            cum_local += dx

            if grade is None:
                missing_elevation_m += dx
                query_grade = 0.0
                reason_codes.add("missing_elevation")
            else:
                query_grade = grade

            prediction = SL.predict_speed(_snap_grade_to_bin(query_grade, bins), bins)
            prediction = _scale_prediction_speeds(prediction, intensity_factor)
            if grade is None:
                # Altitude manquante (nit, revue de code #59) : jamais `"personal"`
                # (ce que le modèle rendrait pour une VRAIE pente plate mesurée) —
                # cette pente est SUPPOSÉE, pas mesurée, `"generic"` quelle que soit
                # la provenance que `predict_speed` rendrait pour 0 %.
                sources.append("generic" if prediction.get("speed_ms") is not None else None)
            else:
                sources.append(prediction.get("source"))
                if prediction.get("reason_code"):
                    reason_codes.add(prediction["reason_code"])

            fade_mult = fade_speed_multiplier(point_frac, fade_pct)
            for scenario, base_speed in _scenario_speeds(prediction, safe_factor=safe_scenario_factor).items():
                if base_speed is None or base_speed <= 0:
                    continue
                effective_speed = base_speed * fade_mult / heat_factor
                if effective_speed <= 0:
                    continue
                time_acc[scenario] += dx / effective_speed
                has_speed[scenario] = True

        cum_m += seg_total_m

        if reason_codes - {"missing_elevation"} and "no_model" in reason_codes:
            reason_code = "no_model"
        elif "extrapolated" in reason_codes:
            reason_code = "extrapolated"
        elif "missing_elevation" in reason_codes:
            reason_code = "missing_elevation"
        elif not has_speed["realistic"]:
            reason_code = "no_model"
        else:
            reason_code = None

        notes = []
        if reason_code == "no_model":
            notes.append("aucun modèle personnel disponible : ce segment ne peut pas être prédit")
        if reason_code == "extrapolated" or "extrapolated" in reason_codes:
            notes.append("pente hors plage du modèle personnel : vitesse prolongée à plat (extrapolation)")
        if missing_elevation_m > 0:
            notes.append(
                f"altitude manquante sur {round(missing_elevation_m)} m de ce segment : pente supposée "
                "nulle (plat)")

        predicted_time_s = {
            s: (int(round(time_acc[s] / SEGMENT_ROUND_S)) * SEGMENT_ROUND_S if has_speed[s] else None)
            for s in SCENARIOS
        }
        pace_s_km = {
            s: (round(1000.0 * time_acc[s] / seg_total_m, 1) if has_speed[s] and seg_total_m > 0 else None)
            for s in SCENARIOS
        }

        out.append({
            "id": seg["id"], "km_start": seg["km_start"], "km_end": seg["km_end"],
            "distance_m": seg["distance_m"], "grade_mean_pct": seg["grade_mean_pct"],
            "elevation_gain_m": seg["elevation_gain_m"], "elevation_loss_m": seg["elevation_loss_m"],
            "source": _combine_sources(sources), "reason_code": reason_code,
            "predicted_time_s": predicted_time_s, "pace_s_km": pace_s_km, "notes": notes,
        })
    return out


def provenance_summary(segments: Sequence[dict]) -> dict:
    """Part de distance totale par provenance (`ASSUMPTIONS["provenance"]`)."""
    total_m = sum(seg["distance_m"] for seg in segments)
    shares: Dict[str, float] = {}
    if total_m <= 0:
        return {"personal_pct": None, "generic_pct": None, "mixed_pct": None, "unknown_pct": None}
    for seg in segments:
        key = seg.get("source") or "unknown"
        shares[key] = shares.get(key, 0.0) + seg["distance_m"]
    return {
        f"{key}_pct": round(dist_m / total_m * 100.0, 1)
        for key, dist_m in {**{"personal": 0.0, "generic": 0.0, "mixed": 0.0, "unknown": 0.0}, **shares}.items()
    }


# ---------------------------------------------------------------------------
# Dépense énergétique prévue par segment/scénario (voir ASSUMPTIONS["energy"])
# ---------------------------------------------------------------------------

def _segments_with_profile(predicted_segments: Sequence[dict], raw_segments: Sequence[dict]) -> List[dict]:
    """Réattache le profil pente/distance point par point (`_profile`, retiré par
    `predict_segments` de son export public) à chaque segment PRÉDIT, par
    IDENTIFIANT (`s01`, `s02`… stables, voir `ASSUMPTIONS["segmentation"]`) —
    les deux listes proviennent du MÊME appel à `segment_course`, jamais
    reconstituées séparément. Consommé par `race_energy_forecast` pour que
    `arc_energy.energy_from_profile` intègre la puissance sur CHAQUE
    sous-intervalle plutôt que sur la seule vitesse moyenne du segment — voir
    `ASSUMPTIONS["energy"]` et `arc_energy.ASSUMPTIONS['race_pacing_integration']`
    pour la limite connue (vitesse moyenne, pente locale). Un segment prédit
    sans correspondance dans `raw_segments` (ne devrait pas arriver, mêmes
    identifiants générés par le même appel) garde simplement `distance_m`/
    `grade_mean_pct` comme seul intervalle (repli de `_segment_intervals`,
    jamais une exception)."""
    raw_by_id = {seg["id"]: seg for seg in raw_segments}
    out = []
    for seg in predicted_segments:
        merged = dict(seg)
        raw = raw_by_id.get(seg["id"])
        if raw is not None:
            merged["profile"] = raw.get("_profile")
        out.append(merged)
    return out


def _default_calibration_bucket() -> dict:
    """Repli quand aucune calibration n'a été résolue par l'appelant (`calibration=None`,
    ex. un test qui n'y a jamais pensé) — MÊME forme qu'un panier
    `arc_energy.calibration_band_report` réellement `insufficient` (`n=0`,
    facteur 1.0) : jamais une exception, jamais une clé absente."""
    return {"n": 0, "ratio_median": None, "ratio_iqr": None, "status": "insufficient", "factor": 1.0}


def _apply_calibration(kcal: float, kcal_per_h: Optional[float], factor: float) -> Tuple[float, Optional[float]]:
    """`(kcal, kcal_per_h)` MULTIPLIÉS par `factor` (voir `arc_energy.
    ASSUMPTIONS['calibration']` : le facteur est LINÉAIRE, comme la masse,
    voir `arc_energy.ASSUMPTIONS['mass_linearity']`) — `kcal_per_h` reste
    `None` s'il l'était déjà (jamais une division par zéro inventée)."""
    return kcal * factor, (kcal_per_h * factor if kcal_per_h is not None else None)


def race_energy_forecast(segments: Sequence[dict], raw_segments: Sequence[dict], *,
                          weight_kg: Optional[float], weight_source: Optional[str],
                          pack_kg: float = DEFAULT_PACK_KG, pack_kg_provided: bool = True,
                          calibration_band: Optional[str] = None,
                          calibration_band_source: Optional[str] = None,
                          calibration: Optional[dict] = None) -> dict:
    """Dépense énergétique BRUTE prévue de la course, par segment ET par scénario
    — voir `ASSUMPTIONS["energy"]` pour la méthode complète (masse, profil
    réattaché, indépendance des trois scénarios, non-persistance dans le
    contrat `race_plan`).

    `weight_kg`/`weight_source` : résolus par l'appelant (CLI) via
    `arc_index.resolve_weight_kg_as_of` — cette fonction reste pure (aucun
    accès disque), comme `build_race_plan`. `pack_kg` : poids du sac/matériel
    (kg), ajouté LINÉAIREMENT au poids de l'athlète (`arc_energy` multiplie la
    puissance W/kg par la masse totale, voir `arc_energy.ASSUMPTIONS
    ['mass_linearity']`) — un doublement de `pack_kg` double exactement sa
    contribution au kcal total, toutes choses égales par ailleurs.
    `pack_kg_provided=False` (CLI : `--pack-kg` omis) ajoute un avertissement
    invitant à le renseigner, sans empêcher le calcul (repli à `pack_kg=0.0`).

    `calibration_band`/`calibration_band_source`/`calibration` (voir
    `ASSUMPTIONS["energy"]`, section « Calibration personnelle ») : résolus
    par l'appelant (CLI) via `resolve_calibration_band` +
    `arc_index.energy_calibration` — cette fonction reste pure (aucun accès
    disque, aucun appel réseau), comme le reste du module. `calibration_band`/
    `calibration_band_source` sont de simples LIBELLÉS (`"route"`/`"trail"`/
    `None`, `"gpx"`/`"option"`/`None`) portés tels quels dans la sortie,
    jamais réinterprétés ici. `calibration=None` (appelant qui n'a pas encore
    ce paramètre, ex. un test antérieur à cette calibration) replie sur
    `_default_calibration_bucket()` (`status="insufficient"`, facteur 1.0) —
    jamais une exception.

    `weight_kg` absent ou non positif -> `{"available": False,
    "reason_code": "no_weight", ...}`, TOUS les champs par scénario à `None`
    — jamais une exception, jamais un plan entier invalidé pour un poids
    manquant.

    Poids CONNU mais AUCUNE vitesse prédite pour AUCUN scénario (revue de
    code : ex. `intensity_source`/modèle sans référence plate du tout, tous
    les segments en `reason_code="no_speed"`, ce qui rendrait sinon
    `time_s=0.0`/`kcal=0.0` — un kcal=0 FAUX, jamais distingué d'un vrai
    « rien à dépenser ») -> `{"available": False, "reason_code":
    "no_prediction", ...}`, distinct de `"no_weight"` : ici c'est la
    PRÉDICTION de temps qui manque, jamais le poids.

    Rend `{"available", "reason", "reason_code", "weight_kg", "weight_source",
    "pack_kg", "total_mass_kg", "calibration", "by_scenario", "warnings"}` —
    `calibration` (`{"band", "band_source", "n", "ratio_median", "ratio_iqr",
    "status", "factor"}`) TOUJOURS présent, même `available=False` (un agent
    peut vouloir savoir si une calibration existerait, indépendamment du reste
    du plan). `by_scenario` porte une entrée par scénario (`SCENARIOS`), `None`
    pour un scénario SANS AUCUNE vitesse prédite (même si d'autres scénarios,
    eux, en ont), sinon `{"kcal", "kcal_per_h", "kcal_calibrated",
    "kcal_per_h_calibrated", "segments", "n_segments_no_speed"}` —
    `kcal_calibrated`/`kcal_per_h_calibrated` sont `kcal`/`kcal_per_h`
    MULTIPLIÉS par `calibration["factor"]` (1.0, donc STRICTEMENT ÉGAUX aux
    valeurs brutes, si `status` est `insufficient`/`not_needed`) — TOUJOURS
    présents À CÔTÉ des valeurs brutes, jamais à leur place — avec
    `segments[].{"id", "kcal", "kcal_per_h", "kcal_calibrated",
    "kcal_per_h_calibrated", "cumulative_kcal", "cumulative_kcal_calibrated",
    "reason_code"}` (cumuls dans l'ORDRE du parcours) — le facteur de
    calibration est un SCALAIRE UNIQUE par scénario (appris sur tout le panier
    route/trail, jamais par segment) : l'appliquer UNIFORMÉMENT à chaque
    segment (`kcal_calibrated`/`cumulative_kcal_calibrated`, PAR LINÉARITÉ,
    voir `ASSUMPTIONS["mass_linearity"]` pour le même principe côté masse)
    reste exact, ce n'est PAS une fausse précision locale — `n_segments_no_speed`
    compte les segments de CE scénario sans vitesse prédite (distance comptée,
    énergie non : cas PARTIEL, jamais une sous-estimation silencieuse), `0` si
    tous les segments du scénario ont une vitesse. `warnings` : à fusionner
    par l'appelant dans `plan.warnings` (jamais un second canal
    d'avertissement séparé pour l'athlète)."""
    resolved_calibration = dict(calibration) if calibration is not None else _default_calibration_bucket()
    calibration_out = {"band": calibration_band, "band_source": calibration_band_source, **resolved_calibration}
    warnings: List[str] = []
    if not pack_kg_provided:
        warnings.append(
            "--pack-kg non renseigné : poids du sac/flasques/matériel supposé nul (0 kg) pour la "
            "dépense énergétique prévue — indiquez le poids réel porté pour un calcul plus fidèle "
            "(voir ASSUMPTIONS['energy']).")
    safe_pack_kg = max(0.0, pack_kg)
    if weight_kg is None or weight_kg <= 0:
        return {
            "available": False,
            "reason": ("poids de l'athlète introuvable à la date de la course (aucune pesée "
                       "santé/nutrition ni profil plausible) : dépense énergétique prévue non "
                       "calculée, le reste du plan reste valide"),
            "reason_code": "no_weight",
            "weight_kg": None, "weight_source": None,
            "pack_kg": round(safe_pack_kg, 2), "total_mass_kg": None,
            "calibration": calibration_out,
            "by_scenario": {s: None for s in SCENARIOS},
            "warnings": warnings,
        }

    total_mass_kg = weight_kg + safe_pack_kg
    enriched = _segments_with_profile(segments, raw_segments)
    by_scenario: Dict[str, Optional[dict]] = {}
    for scenario in SCENARIOS:
        result = EN.energy_from_profile(enriched, total_mass_kg, scenario=scenario)
        # Revue de code : `result` non `None` ne suffit PAS — un scénario SANS
        # AUCUNE vitesse prédite (ex. `no_flat_reference`, tous les segments en
        # `reason_code="no_speed"`) rend `time_s=0.0`/`kcal=0.0` (voir
        # `arc_energy.energy_from_profile`), ce qui rendrait `available=True`
        # avec 0 kcal — un kcal=0 FAUX (pas une vraie mesure de repos), jamais
        # distingué d'un vrai « rien à dépenser ». `time_s <= 0` (ou aucun
        # segment) est donc traité comme AUCUNE prédiction pour ce scénario,
        # jamais un zéro silencieux.
        if result is None or not result.get("segments") or result.get("time_s", 0.0) <= 0:
            by_scenario[scenario] = None
            continue
        n_segments_no_speed = sum(1 for seg in result["segments"] if seg.get("reason_code") == "no_speed")
        cumulative_kcal = 0.0
        cumulative_kcal_calibrated = 0.0
        seg_out = []
        for seg in result["segments"]:
            cumulative_kcal += seg["kcal"]
            # Facteur SCALAIRE UNIQUE par scénario (appris sur tout le panier route/
            # trail) appliqué UNIFORMÉMENT à chaque segment ET à son cumul (correctif
            # de revue de code) — exact PAR LINÉARITÉ (même principe que la masse,
            # voir ASSUMPTIONS["mass_linearity"]), jamais une fausse précision locale :
            # un même facteur constant multiplié terme à terme donne un cumul calibré
            # IDENTIQUE au cumul brut multiplié par ce facteur.
            seg_kcal_calibrated, seg_kcal_per_h_calibrated = _apply_calibration(
                seg["kcal"], seg["kcal_per_h"], resolved_calibration["factor"])
            cumulative_kcal_calibrated += seg_kcal_calibrated
            seg_out.append({
                "id": seg["id"],
                "kcal": round(seg["kcal"], 1),
                "kcal_per_h": round(seg["kcal_per_h"], 1) if seg["kcal_per_h"] is not None else None,
                "kcal_calibrated": round(seg_kcal_calibrated, 1),
                "kcal_per_h_calibrated": (round(seg_kcal_per_h_calibrated, 1)
                                          if seg_kcal_per_h_calibrated is not None else None),
                "cumulative_kcal": round(cumulative_kcal, 1),
                "cumulative_kcal_calibrated": round(cumulative_kcal_calibrated, 1),
                "reason_code": seg["reason_code"],
            })
        kcal_rounded = round(result["kcal"], 1)
        kcal_per_h_rounded = round(result["kcal_per_h"], 1) if result["kcal_per_h"] is not None else None
        kcal_calibrated, kcal_per_h_calibrated = _apply_calibration(
            kcal_rounded, kcal_per_h_rounded, resolved_calibration["factor"])
        by_scenario[scenario] = {
            "kcal": kcal_rounded,
            "kcal_per_h": kcal_per_h_rounded,
            "kcal_calibrated": round(kcal_calibrated, 1),
            "kcal_per_h_calibrated": round(kcal_per_h_calibrated, 1) if kcal_per_h_calibrated is not None else None,
            "segments": seg_out,
            # Cas PARTIEL (revue de code) : certains segments de CE scénario
            # n'ont aucune vitesse prédite (distance comptée dans `kcal`/
            # `kcal_per_h`, mais sans contribution énergétique) — jamais une
            # sous-estimation silencieuse, `0` si tous les segments ont une
            # vitesse.
            "n_segments_no_speed": n_segments_no_speed,
        }

    if all(v is None for v in by_scenario.values()):
        # Poids CONNU mais AUCUNE vitesse prédite pour AUCUN scénario (ex.
        # `no_flat_reference` : pas de référence plate personnelle du tout) —
        # distinct de `no_weight` : ici c'est la PRÉDICTION de temps qui manque,
        # jamais le poids. Le reste du plan (segments, passages horaires) reste
        # valide et calculé normalement.
        return {
            "available": False,
            "reason": ("aucune vitesse prédite pour aucun segment, dans aucun scénario (pas de "
                       "modèle personnel ni générique exploitable) : dépense énergétique prévue non "
                       "calculable, le reste du plan reste valide"),
            "reason_code": "no_prediction",
            "weight_kg": round(weight_kg, 1), "weight_source": weight_source,
            "pack_kg": round(safe_pack_kg, 2), "total_mass_kg": round(total_mass_kg, 1),
            "calibration": calibration_out,
            "by_scenario": {s: None for s in SCENARIOS},
            "warnings": warnings,
        }

    return {
        "available": True, "reason": None, "reason_code": None,
        "weight_kg": round(weight_kg, 1), "weight_source": weight_source,
        "pack_kg": round(safe_pack_kg, 2), "total_mass_kg": round(total_mass_kg, 1),
        "calibration": calibration_out,
        "by_scenario": by_scenario, "warnings": warnings,
    }


# ---------------------------------------------------------------------------
# Ravitaillements, temps de passage, barrières
# ---------------------------------------------------------------------------

def rescale_aid_stations(aid_stations: Sequence[dict], measured_total_m: Optional[float],
                          official_distance_m: Optional[float]) -> List[dict]:
    """Rééchelonne les `km` de ravitaillement (supposés en km OFFICIELS de
    course) sur la distance RÉELLEMENT mesurée du GPX — voir
    `ASSUMPTIONS["aid_stations"]`. Rend `aid_stations` inchangé si l'une des
    deux distances manque."""
    if not official_distance_m or official_distance_m <= 0 or not measured_total_m:
        return list(aid_stations)
    ratio = measured_total_m / official_distance_m
    out = []
    for station in aid_stations:
        rescaled = dict(station)
        rescaled["km"] = round(rescaled["km"] * ratio, 3)
        out.append(rescaled)
    return out


def compute_passages(segments: Sequence[dict], aid_stations: Sequence[dict]) -> dict:
    """Temps de passage cumulés par scénario à la fin de CHAQUE segment, plus
    les arrêts ravito (voir `ASSUMPTIONS["aid_stations"]`). Rend
    `{"segment_passages": [...], "totals_s": {...}, "aid_station_passages": [...]}`,
    tous les temps cumulés arrondis à la MINUTE (`PASSAGE_ROUND_S`).

    `segment_passages[i]` : `{"segment_id", "km_end", scenario: cumulative_s}`
    (cumul APRÈS le segment, arrêts ravito déjà traversés compris).
    `aid_station_passages` : une entrée par station fournie, avec le temps
    cumulé d'ARRIVÉE à la station (avant son propre arrêt) par scénario — une
    station au-delà de la fin mesurée du GPX est rattachée au temps
    d'ARRIVÉE, avec une `note` explicite (jamais supprimée silencieusement)."""
    cum = {s: 0.0 for s in SCENARIOS}
    segment_passages = []
    aid_idx = 0
    aid_sorted = sorted(aid_stations, key=lambda a: a["km"])
    aid_station_passages = []
    last_km_end = segments[-1]["km_end"] if segments else 0.0
    for seg in segments:
        for scenario in SCENARIOS:
            t = seg["predicted_time_s"].get(scenario)
            if t is not None:
                cum[scenario] += t
        segment_passages.append(
            {"segment_id": seg["id"], "km_end": seg["km_end"],
             **{s: _round_passage(cum[s]) for s in SCENARIOS}})
        while aid_idx < len(aid_sorted) and aid_sorted[aid_idx]["km"] <= seg["km_end"]:
            station = aid_sorted[aid_idx]
            aid_station_passages.append({
                "km": station["km"], "name": station.get("name"),
                **{s: _round_passage(cum[s]) for s in SCENARIOS},
            })
            stop_s = station.get("stop_s", DEFAULT_AID_STATION_STOP_S)
            for scenario in SCENARIOS:
                cum[scenario] += stop_s
            aid_idx += 1
    # Ravitos au-delà de la fin mesurée du GPX (revue de code #59, should-fix) :
    # rattachés à l'arrivée plutôt que silencieusement perdus.
    while aid_idx < len(aid_sorted):
        station = aid_sorted[aid_idx]
        entry = {
            "km": station["km"], "name": station.get("name"),
            **{s: _round_passage(cum[s]) for s in SCENARIOS},
            "note": (f"ravito au km {station['km']:g} au-delà de la fin mesurée du GPX "
                     f"({last_km_end:g} km) : rattaché au temps d'arrivée"),
        }
        aid_station_passages.append(entry)
        stop_s = station.get("stop_s", DEFAULT_AID_STATION_STOP_S)
        for scenario in SCENARIOS:
            cum[scenario] += stop_s
        aid_idx += 1
    totals_s = {s: _round_passage(cum[s]) for s in SCENARIOS}
    return {"segment_passages": segment_passages, "totals_s": totals_s, "aid_station_passages": aid_station_passages}


def _parse_hhmm(value: str, *, label: str) -> Tuple[int, int]:
    """`HH:MM` strict (0-23:0-59) — lève `ValueError` (message nommant `label`)
    plutôt que de retomber silencieusement sur une heure par défaut (revue de
    code #59, nit : une heure de départ invalide passait inaperçue)."""
    try:
        hh_s, mm_s = value.split(":")
        hh, mm = int(hh_s), int(mm_s)
        if not (0 <= hh <= 23 and 0 <= mm <= 59):
            raise ValueError
    except (ValueError, AttributeError) as exc:
        raise ValueError(f"{label} : heure HH:MM attendue (00:00-23:59), « {value} » reçu.") from exc
    return hh, mm


def _as_instant(dt: datetime, zone) -> datetime:
    """Instant comparable (#205) : UTC si `dt` porte un décalage ou si le fuseau de
    course `zone` est connu (heure murale `dt` interprétée dans `zone`), sinon heure
    murale naïve. Toute soustraction/comparaison se fait ensuite en temps ABSOLU — deux
    datetimes du MÊME `ZoneInfo` se comparent sinon à l'heure murale (faux d'1 h après
    un changement d'heure)."""
    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc)
    if zone is not None:
        # Heure ambiguë (recul) ou inexistante (avance) : le plus TÔT des deux instants
        # possibles — une barrière n'est jamais rendue plus généreuse qu'écrite.
        return min(dt.replace(tzinfo=zone, fold=f).astimezone(timezone.utc) for f in (0, 1))
    return dt


def has_offset_cutoff(aid_stations: Sequence[dict]) -> bool:
    """Vrai si une barrière est une date-heure ISO AVEC décalage (`+01:00`, `Z`) : sans fuseau de
    course connu, elle n'est comparée qu'à son heure murale (#205) — l'appelant le signale."""
    for station in aid_stations:
        cutoff = station.get("cutoff")
        if not isinstance(cutoff, str) or "T" not in cutoff:
            continue
        try:
            if datetime.fromisoformat(cutoff.strip().replace("Z", "+00:00")).tzinfo is not None:
                return True
        except ValueError:
            continue
    return False


def _race_clock(start_dt: datetime, zone=None) -> Tuple[datetime, Any, datetime]:
    """Normalise le départ (#205) : rend `(start_wall, race_tz, start_abs)` — heure murale
    NAÏVE du départ dans le fuseau de course, ce fuseau (`zone`, sinon le décalage d'un
    départ daté, sinon `None`) et l'instant absolu du départ (`_as_instant`)."""
    race_tz = zone if zone is not None else start_dt.tzinfo
    if start_dt.tzinfo is not None:
        start_wall = start_dt.astimezone(race_tz).replace(tzinfo=None)
    else:
        start_wall = start_dt
    return start_wall, race_tz, _as_instant(start_wall, race_tz)


def _parse_cutoff_dt(cutoff: Optional[str], cutoff_day: Optional[int], start_dt: datetime,
                     zone=None) -> Optional[datetime]:
    """Résout une barrière horaire en instant absolu comparable au départ
    `_race_clock(start_dt, zone)[2]` — voir `ASSUMPTIONS["cutoffs"]` pour les quatre
    formes acceptées (`HH:MM` [+ `cutoff_day` optionnel], `+HH:MM` élapsé, date-heure
    ISO 8601 naïve ou avec décalage `+01:00`/`Z`). Seul parseur des barrières (#205) :
    `HH:MM` et l'ISO naïve sont des heures murales du fuseau de course `zone` quand il est
    connu ; `+HH:MM` est du temps écoulé absolu. Rend `None` si `cutoff` est absent ou
    illisible (jamais une exception : une barrière mal formée ne doit pas faire échouer
    tout le plan)."""
    if not isinstance(cutoff, str) or not cutoff.strip():
        return None
    start_wall, race_tz, start_abs = _race_clock(start_dt, zone)
    text = cutoff.strip()
    if text.startswith("+"):
        try:
            hh_s, mm_s = text[1:].split(":")
            return start_abs + timedelta(hours=int(hh_s), minutes=int(mm_s))
        except ValueError:
            return None
    if "T" in text:
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is not None and race_tz is None:
            # Départ en heure murale sans fuseau connu : seule l'heure murale de la barrière
            # (dans son propre décalage) est comparable — aucun fuseau deviné.
            return parsed.replace(tzinfo=None)
        return _as_instant(parsed, race_tz)
    try:
        hh, mm = _parse_hhmm(text, label="aid_station.cutoff")
    except ValueError:
        return None
    try:
        day_offset = (int(cutoff_day) - 1) if cutoff_day else 0
    except (TypeError, ValueError):
        return None
    if day_offset < 0:
        return None
    cutoff_wall = (start_wall + timedelta(days=day_offset)).replace(hour=hh, minute=mm, second=0, microsecond=0)
    if not cutoff_day and cutoff_wall < start_wall:
        cutoff_wall += timedelta(days=1)
    return _as_instant(cutoff_wall, race_tz)


def check_cutoffs(aid_station_passages: Sequence[dict], aid_stations: Sequence[dict],
                   start_dt: datetime, zone=None) -> List[dict]:
    """Marge de chaque scénario face à une barrière horaire — voir
    `ASSUMPTIONS["cutoffs"]`. `start_dt` : départ naïf (heure murale) ou daté ;
    `zone` : fuseau de course (`tzinfo`, #184) quand il est connu — marges alors
    calculées en temps absolu, justes après un changement d'heure (#205). Une station
    sans `cutoff` (ou dont le `cutoff` est illisible) n'apparaît pas dans le résultat
    (rien à vérifier)."""
    by_km = {round(a["km"], 6): a for a in aid_stations if a.get("cutoff")}
    start_abs = _race_clock(start_dt, zone)[2]
    out = []
    for passage in aid_station_passages:
        station = by_km.get(round(passage["km"], 6))
        if station is None:
            continue
        cutoff_dt = _parse_cutoff_dt(station.get("cutoff"), station.get("cutoff_day"), start_dt, zone)
        if cutoff_dt is None:
            continue
        entry = {"km": passage["km"], "name": passage.get("name"), "cutoff": station["cutoff"]}
        for scenario in SCENARIOS:
            passage_dt = start_abs + timedelta(seconds=passage[scenario])
            margin_s = round((cutoff_dt - passage_dt).total_seconds())
            status = "ok" if margin_s >= CUTOFF_MARGIN_OK_S else ("tendu" if margin_s >= 0 else "hors_delai")
            entry[scenario] = {"margin_s": margin_s, "status": status}
        out.append(entry)
    return out


# ---------------------------------------------------------------------------
# Orchestration pure (assemblage complet, sans accès disque)
# ---------------------------------------------------------------------------

def _renormalize_fade_time_neutral(segments: Sequence[dict], provisional_totals: Dict[str, Optional[float]]) -> Tuple[List[dict], Optional[str]]:
    """Rend le fade NEUTRE en temps total (voir `ASSUMPTIONS["fade"]`, 2ᵉ revue
    de code #59, should-fix) : Riegel/VDOT prédisent déjà une dégradation
    d'endurance sur la distance, le fade ne doit alors PAS s'ajouter par-dessus
    en NET, seulement redistribuer le MÊME temps total dans la course (plus
    rapide en début, plus lent en fin). `provisional_totals` : totaux par
    scénario d'une prédiction SANS fade (même `intensity_factor`/`heat_factor`)
    — la cible que le total AVEC fade doit retrouver après renormalisation.
    Rend `(segments, note)` — `note` est `None` si rien n'a changé (aucun total
    provisoire exploitable, ou fade déjà neutre)."""
    faded_totals = {
        s: (sum(seg["predicted_time_s"][s] for seg in segments if seg["predicted_time_s"][s] is not None) or None)
        for s in SCENARIOS
    }
    ratios = {}
    for s in SCENARIOS:
        prov, faded = provisional_totals.get(s), faded_totals.get(s)
        ratios[s] = (prov / faded) if prov and faded else 1.0
    if all(abs(r - 1.0) < 1e-9 for r in ratios.values()):
        return list(segments), None

    out = []
    for seg in segments:
        new_time: Dict[str, Optional[float]] = {}
        new_pace: Dict[str, Optional[float]] = {}
        for s in SCENARIOS:
            t = seg["predicted_time_s"][s]
            if t is None:
                new_time[s], new_pace[s] = None, None
                continue
            scaled_t = t * ratios[s]
            new_time[s] = int(round(scaled_t))
            new_pace[s] = round(1000.0 * scaled_t / seg["distance_m"], 1) if seg["distance_m"] else None
        out.append({**seg, "predicted_time_s": new_time, "pace_s_km": new_pace})

    note = (
        "fade rendu neutre en temps total (revue de code #59, should-fix) : la prédiction de temps de "
        "course (Riegel/VDOT) intègre déjà une dégradation d'endurance sur la distance — le fade "
        "redistribue ce même temps total (plus rapide en début de course, plus lent en fin) au lieu de "
        "s'ajouter par-dessus la prédiction.")
    return out, note


# ---------------------------------------------------------------------------
# Pénalité de nuit (#184, voir ASSUMPTIONS["night"])
# ---------------------------------------------------------------------------

def night_penalty_fraction(grade_mean_pct: Optional[float], *, base_pct: float = NIGHT_BASE_PENALTY_PCT,
                            descent_extra_max_pct: float = NIGHT_DESCENT_EXTRA_MAX_PCT) -> float:
    """Pénalité de temps (fraction, 0.05 = +5 %) à PLEINE nuit pour une section de pente
    moyenne `grade_mean_pct` : `base_pct` à plat/en montée, plus un supplément proportionnel à
    la pente de descente au-delà de `NIGHT_DESCENT_FREE_GRADE_PCT`, plafonné à
    `descent_extra_max_pct`. Une pente inconnue (`None`) vaut plat. Approximation du projet."""
    extra = 0.0
    if grade_mean_pct is not None and grade_mean_pct < -NIGHT_DESCENT_FREE_GRADE_PCT:
        extra = min(descent_extra_max_pct,
                    NIGHT_DESCENT_EXTRA_PER_GRADE_PCT * (-grade_mean_pct - NIGHT_DESCENT_FREE_GRADE_PCT))
    return (base_pct + extra) / 100.0


def _stops_after_segments(segments: Sequence[dict], aid_stations: Sequence[dict]) -> Tuple[List[float], float]:
    """Secondes d'arrêt ravito APRÈS chaque segment (même règle que `compute_passages` :
    un ravito est traversé dès que son `km` <= `km_end` du segment), et total des arrêts
    rattachés au-delà de la fin du GPX."""
    stops = [0.0] * len(segments)
    idx = 0
    aid_sorted = sorted(aid_stations, key=lambda a: a["km"])
    for i, seg in enumerate(segments):
        while idx < len(aid_sorted) and aid_sorted[idx]["km"] <= seg["km_end"]:
            stops[i] += aid_sorted[idx].get("stop_s", DEFAULT_AID_STATION_STOP_S)
            idx += 1
    beyond = sum(a.get("stop_s", DEFAULT_AID_STATION_STOP_S) for a in aid_sorted[idx:])
    return stops, beyond


def build_night_mask(segments: Sequence[dict], aid_stations: Sequence[dict], start_dt: datetime,
                      lat: float, lon: float, *, base_pct: float = NIGHT_BASE_PENALTY_PCT,
                      descent_extra_max_pct: float = NIGHT_DESCENT_EXTRA_MAX_PCT):
    """Masque de nuit couvrant largement la course (borne haute = temps le plus lent × pénalité
    maximale + tous les arrêts + 1 h de marge)."""
    import arc_solar as SOLAR
    slowest = max((sum(seg["predicted_time_s"][s] or 0 for seg in segments) for s in SCENARIOS), default=0)
    stops, beyond = _stops_after_segments(segments, aid_stations)
    horizon_s = slowest * (1.0 + (base_pct + descent_extra_max_pct) / 100.0) + sum(stops) + beyond + 3600.0
    start_utc = start_dt.astimezone(timezone.utc)
    return SOLAR.NightMask(start_utc, start_utc + timedelta(seconds=horizon_s), lat, lon)


def apply_night_penalty(segments: Sequence[dict], aid_stations: Sequence[dict], start_dt: datetime, mask, *,
                         base_pct: float = NIGHT_BASE_PENALTY_PCT,
                         descent_extra_max_pct: float = NIGHT_DESCENT_EXTRA_MAX_PCT,
                         max_iterations: int = NIGHT_MAX_ITERATIONS) -> Tuple[List[dict], dict]:
    """Applique la pénalité de nuit — pure. `start_dt` : départ CONSCIENT (fuseau), `mask` :
    `arc_solar.NightMask`. Rend `(segments, info)`. Si aucune section n'est courue de nuit dans
    aucun scénario, rend `segments` INCHANGÉS (aucun champ ajouté) avec
    `info["has_night"] = False`. Sinon chaque segment gagne `night_fraction` et `night_factor`
    (objets par scénario) et ses temps/allures pénalisés. `info` : `has_night`, `iterations`,
    `converged`, `clamped_segments`."""
    n = len(segments)
    stops, _beyond = _stops_after_segments(segments, aid_stations)
    base = {s: [seg["predicted_time_s"][s] for seg in segments] for s in SCENARIOS}
    pen = [night_penalty_fraction(seg.get("grade_mean_pct"), base_pct=base_pct,
                                  descent_extra_max_pct=descent_extra_max_pct) for seg in segments]
    factor = {s: [1.0] * n for s in SCENARIOS}

    def times_from(factors):
        t = {s: [None if base[s][i] is None else base[s][i] * factors[s][i] for i in range(n)] for s in SCENARIOS}
        clamped = set()
        for i in range(n):  # prudent >= réaliste >= ambitieux, section par section
            for slower, faster in (("realistic", "ambitious"), ("safe", "realistic")):
                a, b = t[slower][i], t[faster][i]
                if a is not None and b is not None and a < b - 1e-9:
                    t[slower][i] = b
                    clamped.add(i)
        return t, clamped

    # Horloge en UTC : `datetime` conscient + `timedelta` ajoute du temps MURAL dans le fuseau
    # (zoneinfo), faux d'une heure après un changement d'heure en pleine course (dernier
    # dimanche d'octobre en Europe) — le temps écoulé, lui, est absolu.
    start_utc = start_dt.astimezone(timezone.utc)

    def walk(t):
        fractions = {s: [0.0] * n for s in SCENARIOS}
        for s in SCENARIOS:
            clock = start_utc
            for i in range(n):
                dur = t[s][i]
                if dur is None:
                    continue
                end = clock + timedelta(seconds=dur)
                if dur > 0:
                    fractions[s][i] = min(1.0, mask.night_seconds(clock, end) / dur)
                clock = end + timedelta(seconds=stops[i])
        return fractions

    iterations, converged = 0, False
    for iterations in range(1, max_iterations + 1):
        t, _ = times_from(factor)
        fractions = walk(t)
        new_factor = {s: [1.0 + fractions[s][i] * pen[i] for i in range(n)] for s in SCENARIOS}
        delta = max((abs(new_factor[s][i] - factor[s][i]) for s in SCENARIOS for i in range(n)), default=0.0)
        factor = new_factor
        if delta < NIGHT_CONVERGENCE_TOL:
            converged = True
            break
    t, clamped = times_from(factor)
    fractions = walk(t)

    has_night = any(f > 1e-9 for s in SCENARIOS for f in fractions[s])
    info = {"has_night": has_night, "iterations": iterations, "converged": converged,
            "clamped_segments": len(clamped)}
    if not has_night:
        return list(segments), info

    out = []
    for i, seg in enumerate(segments):
        new_time: Dict[str, Optional[int]] = {}
        new_pace: Dict[str, Optional[float]] = {}
        nf: Dict[str, Optional[float]] = {}
        nfac: Dict[str, Optional[float]] = {}
        for s in SCENARIOS:
            old = seg["predicted_time_s"][s]
            if old is None:
                new_time[s], new_pace[s], nf[s], nfac[s] = None, seg["pace_s_km"][s], None, None
                continue
            eff = t[s][i] / old if old else 1.0
            if abs(eff - 1.0) < 1e-12:
                new_time[s], new_pace[s] = old, seg["pace_s_km"][s]
            else:
                new_time[s] = int(round(t[s][i] / SEGMENT_ROUND_S)) * SEGMENT_ROUND_S
                p = seg["pace_s_km"][s]
                new_pace[s] = round(p * eff, 1) if p is not None else None
            nf[s] = round(fractions[s][i], 3)
            nfac[s] = round(eff, 4)
        out.append({**seg, "predicted_time_s": new_time, "pace_s_km": new_pace,
                    "night_fraction": nf, "night_factor": nfac})
    return out, info


def _fmt_local(dt: datetime, ref: datetime) -> str:
    days = (dt.date() - ref.date()).days
    return dt.strftime("%H:%M") + (f" (J+{days})" if days > 0 else "")


def night_scenario_summary(mask, start_dt: datetime, total_s: Optional[float], tz) -> dict:
    """Résumé de nuit d'un scénario sur la course entière, départ -> arrivée (arrêts compris)."""
    if total_s is None:
        return {"night_duration_s": None, "summary": "temps de course indisponible : pas de résumé de nuit"}
    start_utc = start_dt.astimezone(timezone.utc)  # temps écoulé absolu (changement d'heure)
    end = start_utc + timedelta(seconds=total_s)
    windows = mask.night_windows(start_utc, end)
    night_s = round(mask.night_seconds(start_utc, end))
    if not windows:
        return {"night_duration_s": 0, "summary": "aucune nuit pendant la course, frontale non requise"}
    local = [(a.astimezone(tz), b.astimezone(tz)) for a, b in windows]
    ref = start_dt.astimezone(tz)
    spans = "; ".join(f"{_fmt_local(a, ref)} à {_fmt_local(b, ref)}" for a, b in local)
    if night_s >= 3600:
        amount = f"{night_s / 3600.0:.1f}".replace(".", ",") + " h"
    else:  # « 0,0 h de nuit » pour 2 min de crépuscule serait trompeur
        amount = f"{max(1, round(night_s / 60.0))} min"
    return {
        "night_duration_s": night_s,
        "lamp_from": local[0][0].isoformat(timespec="minutes"),
        "lamp_until": local[-1][1].isoformat(timespec="minutes"),
        "summary": f"{amount} de nuit, frontale requise de {spans}",
    }


NIGHT_GEAR_HINT = (
    "Frontale (et piles/batterie de rechange) à inscrire dans `gear` du plan ; le contrôle contre "
    "l'inventaire est celui de `python3 scripts/arc_index.py equipment --race-plan <plan>` (#134).")


def night_unavailable(status: str, reason: str, note: str) -> dict:
    return {"status": status, "reason": reason, "note": note}


def timezone_plausibility_warning(start_dt: datetime, lon: float, tz_name: str) -> Optional[str]:
    """Avertissement (français) si le décalage UTC du fuseau au départ s'écarte de plus de
    `NIGHT_TZ_SUSPECT_OFFSET_H` de l'heure solaire de la longitude `lon` (lon / 15 h), écart
    ramené dans [-12, 12[ h ; `None` sinon. Contrôle grossier : il attrape un fuseau d'un autre
    continent, pas une erreur d'une heure."""
    offset_h = start_dt.utcoffset().total_seconds() / 3600.0
    diff = (offset_h - lon / 15.0 + 12.0) % 24.0 - 12.0
    if abs(diff) <= NIGHT_TZ_SUSPECT_OFFSET_H:
        return None
    return (f"fuseau « {tz_name} » (UTC{offset_h:+g} h au départ) peu vraisemblable pour la longitude "
            f"{lon:.2f}° du départ (heure solaire ≈ UTC{lon / 15.0:+.1f} h) : vérifier --tz, les heures "
            "de nuit en dépendent")


def _night_stage(pts, segments, aid_stations, hh, mm, race_date, tz, start_time_known, enabled,
                 base_pct, descent_extra_max_pct):
    """Étape « nuit » de `build_race_plan` (#184). Rend `(night, mask, start_dt, tzinfo)` ;
    `night` porte `_apply`/`_segments` (clés privées retirées par l'appelant) quand des
    sections sont pénalisées."""
    if not enabled:
        return night_unavailable("disabled", "disabled",
                                 "pénalité de nuit désactivée (--no-night)"), None, None, None
    missing = None
    if not race_date:
        missing = ("no_race_date", "date de course inconnue (--race-date) : facteur de nuit non appliqué")
    elif not start_time_known:
        missing = ("no_start_time", "heure de départ non fournie (--start) : facteur de nuit non appliqué")
    elif not tz:
        missing = ("no_timezone", "fuseau horaire non fourni (--tz, ex. Europe/Paris) : facteur de nuit "
                                  "non appliqué")
    elif not pts:
        missing = ("no_gpx_position", "aucune position GPX : facteur de nuit non appliqué")
    if missing:
        return night_unavailable("unavailable", *missing), None, None, None

    import arc_solar as SOLAR
    zone = SOLAR.resolve_timezone(tz)
    base_date = date.fromisoformat(race_date)
    start_dt = datetime(base_date.year, base_date.month, base_date.day, hh, mm, tzinfo=zone)
    lat, lon = pts[0]["lat"], pts[0]["lon"]
    tz_warning = timezone_plausibility_warning(start_dt, lon, tz)
    mask = build_night_mask(segments, aid_stations, start_dt, lat, lon, base_pct=base_pct,
                            descent_extra_max_pct=descent_extra_max_pct)
    new_segments, info = apply_night_penalty(segments, aid_stations, start_dt, mask, base_pct=base_pct,
                                             descent_extra_max_pct=descent_extra_max_pct)
    sun = SOLAR.local_sun_times(base_date, lat, lon, zone)
    night = {
        "status": "night" if info["has_night"] else "daylight",
        "timezone": tz,
        "location": {"lat": round(lat, 4), "lon": round(lon, 4), "source": "gpx_start"},
        "parameters": {
            "base_penalty_pct": base_pct, "descent_extra_max_pct": descent_extra_max_pct,
            "descent_free_grade_pct": NIGHT_DESCENT_FREE_GRADE_PCT,
            "descent_extra_per_grade_pct": NIGHT_DESCENT_EXTRA_PER_GRADE_PCT,
            "twilight": "civil (soleil à 6° sous l'horizon)",
        },
        "sun": {k: (v.isoformat(timespec="minutes") if hasattr(v, "isoformat") else v)
                for k, v in sun.items() if k != "solar_noon"},
        "iterations": info["iterations"], "converged": info["converged"],
        "scenario_order_clamped_segments": info["clamped_segments"],
        "scenarios": {},
        "gear_hint": NIGHT_GEAR_HINT,
    }
    if tz_warning:
        night["timezone_warning"] = tz_warning
    if info["has_night"]:
        night["_apply"] = True
        night["_segments"] = new_segments
    return night, mask, start_dt, zone


def _technicity_stage(pts, segments, technicity, scale: Optional[float] = None):
    """Étape « technicité » de `build_race_plan` (#186). `technicity` : `None` (non demandée ->
    `(segments, None, [])`, sortie inchangée octet pour octet) ou `{"declared": [...]|None,
    "ways": [...]|None, "osm_requested": bool, "osm_status": str, "osm_note": str|None,
    "osm_info": dict|None}` résolu par l'appelant (réseau et disque jamais ici). `scale` :
    coefficient personnel `[pacing.personal].technicity_scale` (#188), multiplie le SURCOÛT
    (coef - 1) de chaque section portant un coefficient ; `None` = inchangé. Rend
    `(segments, plan_technicity, warnings)`."""
    if technicity is None:
        return segments, None, []
    declared, ways = technicity.get("declared"), technicity.get("ways")
    baseline = float(technicity.get("osm_baseline") or 1.0)
    baseline_label = technicity.get("osm_baseline_label") or ""
    coefs = TECH.section_coefficients(segments, pts, declared=declared, ways=ways, osm_baseline=baseline)
    if scale is not None and abs(scale - 1.0) > 1e-12:
        for seg, c in zip(segments, coefs):
            if c["source"] == "none":
                continue
            c["coef_before_scale"] = c["coef"]
            c["coef"] = round(min(TECH.COEF_MAX, max(TECH.COEF_MIN_DECLARED, 1.0 + (c["coef"] - 1.0) * scale)), 3)
            c["effective_factor"] = round(TECH.effective_factor(c["coef"], seg.get("grade_mean_pct")), 4)
    warnings: List[str] = []
    osm_block = None
    if technicity.get("osm_requested"):
        osm_block = {"status": technicity.get("osm_status"), "note": technicity.get("osm_note"),
                     "match_radius_m": TECH.MATCH_RADIUS_M,
                     "baseline": {"coef": round(baseline, 3),
                                  "source": "declared" if baseline_label else "default",
                                  **({"label": baseline_label} if baseline_label else {})},
                     **(technicity.get("osm_info") or {})}
    info = {
        "status": "applied" if any(c["source"] != "none" for c in coefs) else "no_coefficient",
        "sources_requested": [k for k, v in (("declared", declared), ("osm", technicity.get("osm_requested")))
                               if v],
        "osm": osm_block,
        "scenario_scaling": "identique pour les trois scénarios (voir ASSUMPTIONS['technicity'])",
        **TECH.summarize(segments, coefs),
        **({"personal_scale": scale} if scale is not None and abs(scale - 1.0) > 1e-12 else {}),
    }
    if technicity.get("osm_note"):
        warnings.append(technicity["osm_note"])
    if any(c["source"] == "osm" for c in coefs) and not baseline_label:
        warnings.append("Technicité OSM sans terrain de référence (--technicity-baseline) : les coefficients "
                        "sont comptés depuis un chemin facile, alors que le modèle personnel contient déjà le "
                        "terrain habituel de l'athlète — s'il s'entraîne déjà sur sentier de montagne, la "
                        "pénalité est surestimée (voir ASSUMPTIONS['technicity']).")
    if info["status"] == "no_coefficient":
        warnings.append("Technicité demandée mais aucune section n'a de coefficient (déclaration absente "
                        "ou OSM sans couverture suffisante) : temps inchangés.")
    return TECH.apply_to_segments(segments, coefs, SCENARIOS, SEGMENT_ROUND_S), info, warnings


# ---------------------------------------------------------------------------
# Pénalité d'altitude (#185, voir ASSUMPTIONS["altitude"])
# ---------------------------------------------------------------------------

def _segment_altitudes(pts: Sequence[dict], segments: Sequence[dict], threshold_m: float
                       ) -> List[Tuple[Optional[float], Optional[float], Optional[float]]]:
    """Par section : `(altitude moyenne, excédent moyen au-dessus de threshold_m, altitude max)`
    en m, moyenne et excédent pondérés par la distance (`None` sans altitude) — l'excédent nourrit
    le facteur, la moyenne l'affichage (voir `AL.ASSUMPTIONS["race_penalty"]`). Avec la
    correction MNT (#176), `pts` porte déjà les altitudes corrigées."""
    dist_m = _cumulative_distances(pts)
    out: List[Tuple[Optional[float], Optional[float], Optional[float]]] = []
    for seg in segments:
        lo, hi = seg["km_start"] * 1000.0 - 0.5, seg["km_end"] * 1000.0 + 0.5
        sel = [(p["ele"], d) for p, d in zip(pts, dist_m) if p.get("ele") is not None and lo <= d <= hi]
        if not sel:
            out.append((None, None, None))
            continue
        num = den = 0.0
        for (a0, d0), (a1, d1) in zip(sel, sel[1:]):
            num += (d1 - d0) * (a0 + a1) / 2.0
            den += d1 - d0
        mean = num / den if den > 0 else sum(a for a, _ in sel) / len(sel)
        excess = AL.excess_above([a for a, _ in sel], [d for _, d in sel], threshold_m)
        out.append((mean, excess, max(a for a, _ in sel)))
    return out


def apply_altitude_penalty(pts: Sequence[dict], segments: Sequence[dict], *, credit: float = 0.0,
                            threshold_m: float = AL.ALTITUDE_THRESHOLD_M,
                            loss_pct_per_1000m: float = AL.ALTITUDE_VO2MAX_LOSS_PCT_PER_1000M,
                            scale: float = 1.0) -> Tuple[List[dict], dict]:
    """Applique le facteur d'altitude section par section — pure. Rend `(segments, info)` ;
    si aucune section ne dépasse `threshold_m`, `segments` est rendu INCHANGÉ (aucun champ
    ajouté). Sinon chaque section gagne `altitude_m` et `altitude_factor` (scalaire, identique
    pour les trois scénarios : l'ordre prudent >= réaliste >= ambitieux est conservé) et ses
    temps/allures majorés. `scale` : coefficient personnel `[pacing.personal].altitude_scale`
    (#188) — multiplie le SURCOÛT (facteur − 1) de chaque section, comme `technicity_scale` :
    c'est exactement ce qu'estime `arc_pacing_calibration` (ratio surcoût réel / surcoût prévu)."""
    triples = _segment_altitudes(pts, segments, threshold_m)
    alts = [a for a, _, _ in triples]
    factors = [AL.altitude_time_factor(None if ex is None else threshold_m + ex, credit=credit,
                                       threshold_m=threshold_m, loss_pct_per_1000m=loss_pct_per_1000m)
               for _, ex, _ in triples]
    if abs(scale - 1.0) > 1e-12:
        factors = [1.0 + (f - 1.0) * scale if f > 1.0 else f for f in factors]
    known = [a for a in alts if a is not None]
    peaks = [m for (_, _, m), f in zip(triples, factors) if m is not None and f > 1.0]
    info = {"max_mean_altitude_m": round(max(known)) if known else None,
            "max_altitude_m": round(max(peaks)) if peaks else None,
            "sections_above": sum(1 for f in factors if f > 1.0), "applied": any(f > 1.0 for f in factors)}
    if not info["applied"]:
        return list(segments), info
    out = []
    for seg, alt, f in zip(segments, alts, factors):
        new_time, new_pace = {}, {}
        for s in SCENARIOS:
            old = seg["predicted_time_s"][s]
            p = seg["pace_s_km"][s]
            if f == 1.0 or old is None:
                new_time[s], new_pace[s] = old, p
            else:
                new_time[s] = int(round(old * f / SEGMENT_ROUND_S)) * SEGMENT_ROUND_S
                new_pace[s] = round(p * f, 1) if p is not None else None
        out.append({**seg, "predicted_time_s": new_time, "pace_s_km": new_pace,
                    "altitude_m": round(alt) if alt is not None else None, "altitude_factor": round(f, 4)})
    return out, info


def _altitude_stage(pts, segments, enabled, threshold_m, loss_pct, acclimated_days, exposure, coverage,
                    race_date=None, scale: Optional[float] = None):
    """Étape « altitude » de `build_race_plan` (#185). `scale` : `[pacing.personal].altitude_scale`
    (#188, `None` = inchangé), multiplie le surcoût de chaque section. Rend
    `(altitude, segments, warnings)`."""
    personal = scale is not None and abs(scale - 1.0) > 1e-12
    params = {"threshold_m": threshold_m, "vo2max_loss_pct_per_1000m": loss_pct,
              "altitude_cap_m": AL.ALTITUDE_CAP_M, "measured_max_m": AL.ALTITUDE_MEASURED_MAX_M,
              "source": "Wehrlin & Hallén 2006, doi:10.1007/s00421-005-0081-9 ; "
                        "traduction vitesse = approximation du projet"}
    if not enabled:
        return {"status": "disabled", "note": "pénalité d'altitude désactivée (--no-altitude)"}, segments, []
    if coverage <= 0.0:
        return {"status": "no_elevation", "note": "aucune altitude dans le GPX : pénalité d'altitude non "
                                                   "appliquée"}, segments, []
    _probe, info = apply_altitude_penalty(pts, segments, credit=0.0, threshold_m=threshold_m,
                                          loss_pct_per_1000m=loss_pct)
    if not info["applied"]:
        return {"status": "below_threshold", "max_mean_altitude_m": info["max_mean_altitude_m"],
                "note": f"toutes les sections sous {threshold_m:.0f} m : aucun effet",
                "parameters": params}, segments, []
    hours = AL.training_hours_ge(exposure)
    lead_ok, lead_note = AL.training_credit_lead(exposure, race_date)
    credit = AL.altitude_credit(acclimated_days, hours if lead_ok else None)
    new_segments, info = apply_altitude_penalty(pts, segments, credit=credit["total"], threshold_m=threshold_m,
                                                loss_pct_per_1000m=loss_pct, scale=scale if personal else 1.0)
    before = {s: sum(x["predicted_time_s"][s] or 0 for x in segments) for s in SCENARIOS}
    after = {s: sum(x["predicted_time_s"][s] or 0 for x in new_segments) for s in SCENARIOS}
    altitude = {
        "status": "applied", "max_mean_altitude_m": info["max_mean_altitude_m"],
        "max_altitude_m": info["max_altitude_m"],
        "sections_above": info["sections_above"],
        "elevation_source": "gpx",
        "acclimation": {"declared_days": acclimated_days, "training_hours_ge_1500m_28d": (
            round(hours, 2) if hours is not None else None), "credit": credit,
            "training_credited": bool(lead_ok and hours),
            "note": ("aucune acclimatation déclarée ni exposition mesurée créditée : athlète supposé non acclimaté"
                     if credit["total"] == 0 else "crédit d'acclimatation appliqué (approximation du projet)")
                    + (f" ; {lead_note}" if hours else "")},
        "time_added_s": {s: after[s] - before[s] for s in SCENARIOS},
        "parameters": {**params, **({"personal_scale": scale} if personal else {})},
    }
    added_min = (after["realistic"] - before["realistic"]) / 60.0
    warnings = [f"altitude : {info['sections_above']} section(s) au-dessus de {threshold_m:.0f} m (point haut "
                f"{info['max_altitude_m']} m), temps réaliste "
                + (f"+{round(added_min)} min" if added_min >= 1 else "+< 1 min")
                + " — pénalité appliquée par défaut depuis #185 (`--no-altitude` pour l'ancien calcul), "
                "approximation du projet (ASSUMPTIONS['altitude'])"
                + (f" ; coefficient personnel altitude_scale = {scale:g} ([pacing.personal])" if personal else "")]
    if info["max_altitude_m"] is not None and info["max_altitude_m"] > AL.ALTITUDE_MEASURED_MAX_M:
        warnings.append(f"altitude > {AL.ALTITUDE_MEASURED_MAX_M:.0f} m sur le parcours : hors de la plage "
                        "mesurée par la source, pénalité extrapolée")
    return altitude, new_segments, warnings


def build_race_plan(pts: Sequence[dict], bins: Sequence[dict], *,
                     aid_stations: Optional[Sequence[dict]] = None,
                     fade_pct: float = 0.0, fade_source: str = "generic",
                     temp_max_c: Optional[float] = None, acclimated: Optional[bool] = None,
                     acclimation_note: Optional[str] = None,
                     intensity_factor: float = 1.0, intensity_source: str = "none",
                     intensity_notes: Optional[Sequence[str]] = None,
                     safe_scenario_factor: float = GENERIC_SCENARIO_SPEED_FACTOR["safe"],
                     flat_reference_speed_ms: Optional[float] = None, band: str = DEFAULT_BAND,
                     official_distance_m: Optional[float] = None,
                     start_time: str = "07:00", race_date: Optional[str] = None,
                     segment_m: float = DEFAULT_SEGMENT_M,
                     weight_kg: Optional[float] = None, weight_source: Optional[str] = None,
                     pack_kg: float = DEFAULT_PACK_KG, pack_kg_provided: bool = True,
                     calibration_band: Optional[str] = None,
                     calibration_band_source: Optional[str] = None,
                     calibration: Optional[dict] = None,
                     tz: Optional[str] = None, start_time_known: bool = True,
                     night_enabled: bool = True, night_penalty_pct: float = NIGHT_BASE_PENALTY_PCT,
                     night_descent_extra_max_pct: float = NIGHT_DESCENT_EXTRA_MAX_PCT,
                     technicity: Optional[dict] = None,
                     heat_hot_factor: Optional[float] = None, technicity_scale: Optional[float] = None,
                     personal_applied: Optional[dict] = None,
                     altitude_enabled: bool = True, altitude_threshold_m: float = AL.ALTITUDE_THRESHOLD_M,
                     altitude_loss_pct_per_1000m: float = AL.ALTITUDE_VO2MAX_LOSS_PCT_PER_1000M,
                     altitude_acclimated_days: Optional[int] = None,
                     altitude_exposure: Optional[dict] = None, altitude_scale: Optional[float] = None) -> dict:
    """Assemble le plan de course complet — pure (aucun accès disque), pour que
    la CLI et les tests partagent exactement le même chemin de calcul.

    `weight_kg`/`weight_source`/`pack_kg`/`pack_kg_provided`/`calibration_band`/
    `calibration_band_source`/`calibration` (dépense énergétique prévue,
    calibration personnelle) : voir `ASSUMPTIONS["energy"]`/
    `race_energy_forecast` — résolus par l'appelant (CLI, via
    `resolve_calibration_band` pour les deux premiers), jamais par cette
    fonction (qui reste pure).

    `tz` (nom IANA), `start_time_known` (faux = `start_time` est le défaut, pas un choix),
    `night_*` : pénalité de nuit (#184, `ASSUMPTIONS["night"]`) — appliquée seulement si la date
    de course, l'heure de départ explicite et le fuseau sont connus, sinon la clé additive
    `night` dit pourquoi et les temps restent ceux d'avant #184.

    `technicity` : coefficient de technicité par section (#186, `ASSUMPTIONS["technicity"]`), résolu par
    l'appelant ; `None` (défaut) = étape absente, sortie inchangée.

    `altitude_*` : pénalité d'altitude (#185, `ASSUMPTIONS["altitude"]`) — facteur de temps par
    section au-dessus du seuil, réduit par `altitude_acclimated_days` (déclaré) et par
    `altitude_exposure` (rapport de `arc_index.altitude_exposure`, résolu par l'appelant) ;
    sous le seuil partout, seule la clé additive `altitude` s'ajoute. `altitude_scale` :
    `[pacing.personal].altitude_scale` (#188), résolu par l'appelant (`None` si
    `--altitude-loss-pct` est donné : le drapeau CLI prime) ; consigné dans `pacing_personal`
    seulement quand la pénalité est réellement appliquée.

    Lève `ValueError` si `start_time` n'est pas un `HH:MM` valide (revue de
    code #59, nit : jamais un repli silencieux sur 07:00) ou si `tz` est inconnu."""
    hh, mm = _parse_hhmm(start_time, label="--start")
    base_date = date.fromisoformat(race_date) if race_date else date.today()
    start_dt = datetime(base_date.year, base_date.month, base_date.day, hh, mm)

    warnings: List[str] = []
    coverage = elevation_coverage_pct(pts)
    if coverage <= 0.0:
        warnings.append(
            "Aucune altitude dans le fichier GPX : le parcours entier est traité à plat (pente 0 "
            "partout), D+/D- et allures ne reflètent aucun relief réel — voir "
            "ASSUMPTIONS['missing_elevation'].")
    elif coverage < 99.5:
        warnings.append(
            f"Altitude manquante sur environ {100 - coverage:.0f} % des points du GPX : les segments "
            "concernés sont traités à plat (voir la note de chaque segment), le D+/D- total est "
            "sous-estimé d'autant.")
    if intensity_source == "none":
        warnings.append(
            "Aucune prédiction de temps de course exploitable (distance GPX, référence dure récente ou "
            "tendance VO2max manquants) : les allures reflètent l'allure D'ENDURANCE mesurée à "
            "l'entraînement, PAS l'allure de course visée — voir ASSUMPTIONS['base_pace'].")
    warnings.extend(intensity_notes or [])

    aid_stations = list(aid_stations or [])
    raw_segments = segment_course(pts, target_segment_m=segment_m)
    total_measured_m = raw_segments[-1]["km_end"] * 1000.0 if raw_segments else None
    aid_stations = rescale_aid_stations(aid_stations, total_measured_m, official_distance_m)
    if technicity and technicity.get("declared") and official_distance_m and official_distance_m > 0 \
            and total_measured_m:
        # Les km DÉCLARÉS sont des km officiels (roadbook), comme ceux des ravitos : même
        # rééchelonnement sur la distance mesurée du GPX (#186, revue de code).
        ratio = total_measured_m / official_distance_m
        technicity = {**technicity, "declared": [
            {**sec, "km_start": round(sec["km_start"] * ratio, 3), "km_end": round(sec["km_end"] * ratio, 3)}
            for sec in technicity["declared"]]}

    heat_factor, heat_notes = heat_time_factor(temp_max_c, acclimated=acclimated, hot_factor=heat_hot_factor)
    if acclimation_note:
        heat_notes = [*heat_notes, acclimation_note]

    # Passe préliminaire SANS fade (le facteur de fade dépend de la durée totale
    # PRÉDITE de la course, voir ASSUMPTIONS["fade"]) pour échelonner un fade
    # mesuré sur sortie longue à une course bien plus courte, ET pour disposer
    # d'un total DE RÉFÉRENCE par scénario (renormalisation "fade neutre",
    # voir `_renormalize_fade_time_neutral`).
    provisional = predict_segments(raw_segments, bins, fade_pct=0.0, heat_factor=heat_factor,
                                    intensity_factor=intensity_factor, safe_scenario_factor=safe_scenario_factor)
    provisional_totals = {
        s: (sum(seg["predicted_time_s"][s] for seg in provisional if seg["predicted_time_s"][s] is not None)
            or None)
        for s in SCENARIOS
    }
    predicted_duration_s = provisional_totals["realistic"]
    fade_pct_applied = scale_fade_to_duration(fade_pct, predicted_duration_s)
    fade_notes = []
    if fade_pct > 0 and fade_pct_applied < fade_pct - 1e-9:
        fade_notes.append(
            f"course prédite ≈ {round(predicted_duration_s / 60.0)} min, sous le seuil de sortie longue "
            f"(90 min, arc_metrics.LONG_RUN_MIN_DURATION_S) : fade réduit à {fade_pct_applied:.1f} % "
            f"(mesuré/générique : {fade_pct:.1f} %)")

    segments = predict_segments(raw_segments, bins, fade_pct=fade_pct_applied, heat_factor=heat_factor,
                                 intensity_factor=intensity_factor, safe_scenario_factor=safe_scenario_factor)

    # Fade rendu NEUTRE en temps total dès qu'une prédiction Riegel/VDOT sous-jacente
    # existe (voir ASSUMPTIONS["fade"]) ET que la course PRÉDITE reste sous
    # `FADE_TIME_NEUTRAL_MAX_DURATION_S` (6 h, 3ᵉ revue de code #59, should-fix) :
    # au-delà, la dégradation implicite de Riegel/VDOT (elle-même approximative sur
    # un ultra, voir `RIEGEL_ULTRA_EXPONENT`) ne doit pas être présumée couvrir
    # EXACTEMENT le fade mesuré — les deux s'additionnent plutôt que de s'annuler.
    if intensity_source != "none" and predicted_duration_s is not None \
            and predicted_duration_s <= FADE_TIME_NEUTRAL_MAX_DURATION_S:
        segments, renorm_note = _renormalize_fade_time_neutral(segments, provisional_totals)
        if renorm_note:
            fade_notes.append(renorm_note)
    elif intensity_source != "none" and fade_pct_applied > 0 and predicted_duration_s is not None:
        fade_notes.append(
            f"course prédite ≈ {predicted_duration_s / 3600.0:.1f} h (> "
            f"{FADE_TIME_NEUTRAL_MAX_DURATION_S / 3600.0:.0f} h) : le fade reste ADDITIF (pas neutralisé) "
            "malgré une prédiction Riegel/VDOT — voir ASSUMPTIONS['fade'].")

    # Technicité du terrain (#186) : propriété du TERRAIN, pas de l'horloge -> AVANT la nuit, dont
    # l'itération part ainsi des temps de section déjà corrigés (heures de passage cohérentes).
    segments, technicity_info, technicity_warnings = _technicity_stage(pts, segments, technicity, technicity_scale)
    warnings.extend(technicity_warnings)

    # Altitude AVANT la nuit : facteur indépendant de l'horloge, il décale les passages que
    # l'itération de nuit lit ensuite (composition multiplicative chaleur x altitude x nuit).
    altitude, segments, altitude_warnings = _altitude_stage(
        pts, segments, altitude_enabled, altitude_threshold_m, altitude_loss_pct_per_1000m,
        altitude_acclimated_days, altitude_exposure, coverage, race_date, altitude_scale)
    warnings.extend(altitude_warnings)
    if altitude.get("status") == "applied" and (altitude.get("parameters") or {}).get("personal_scale"):
        personal_applied = {**(personal_applied or {}), "altitude_scale": altitude_scale}

    night, night_mask, night_start_dt, night_tzinfo = _night_stage(
        pts, segments, aid_stations, hh, mm, race_date, tz, start_time_known, night_enabled,
        night_penalty_pct, night_descent_extra_max_pct)
    if night.pop("_apply", None) is not None:
        segments = night.pop("_segments")
    if night.get("timezone_warning"):
        warnings.append(night["timezone_warning"])

    passages = compute_passages(segments, aid_stations)
    if night_mask is not None:
        for scenario in SCENARIOS:
            night["scenarios"][scenario] = night_scenario_summary(
                night_mask, night_start_dt, passages["totals_s"][scenario], night_tzinfo)
    # Fuseau de course pour les barrières (#205) : celui de la nuit s'il a été résolu, sinon `--tz`
    # même sans pénalité de nuit (un fuseau illisible n'est alors qu'un avertissement).
    cutoff_zone = night_tzinfo
    if cutoff_zone is None and tz and any(a.get("cutoff") for a in aid_stations):
        import arc_solar as SOLAR
        try:
            cutoff_zone = SOLAR.resolve_timezone(tz)
        except ValueError as exc:
            warnings.append(f"barrières horaires calculées à l'heure murale : {exc}")
    if cutoff_zone is None and has_offset_cutoff(aid_stations):
        warnings.append(
            "barrière horaire avec décalage (+HH:MM/Z) sans fuseau de course (--tz) : comparée à son "
            "heure murale, marge fausse si ce décalage n'est pas celui du départ")
    cutoffs = check_cutoffs(passages["aid_station_passages"], aid_stations, start_dt, cutoff_zone)
    for aid_passage in passages["aid_station_passages"]:
        if aid_passage.get("note"):
            warnings.append(aid_passage["note"])

    energy = race_energy_forecast(segments, raw_segments, weight_kg=weight_kg, weight_source=weight_source,
                                   pack_kg=pack_kg, pack_kg_provided=pack_kg_provided,
                                   calibration_band=calibration_band,
                                   calibration_band_source=calibration_band_source, calibration=calibration)
    warnings.extend(energy.pop("warnings"))

    total_distance_m = sum(seg["distance_m"] for seg in segments)
    total_gain_m = sum(seg["elevation_gain_m"] for seg in segments)
    total_loss_m = sum(seg["elevation_loss_m"] for seg in segments)

    return {
        "segments": segments,
        "totals": {
            "distance_m": round(total_distance_m, 1),
            "elevation_gain_m": round(total_gain_m, 1),
            "elevation_loss_m": round(total_loss_m, 1),
            "time_s": passages["totals_s"],
        },
        "segment_passages": passages["segment_passages"],
        "aid_station_passages": passages["aid_station_passages"],
        "cutoffs": cutoffs,
        "provenance_summary": provenance_summary(segments),
        "energy": energy,
        "band": band,
        "flat_reference_speed_ms": (round(flat_reference_speed_ms, 3) if flat_reference_speed_ms else None),
        "intensity_factor": round(intensity_factor, 4),
        "intensity_source": intensity_source,
        "fade_pct": fade_pct,
        "fade_pct_applied": round(fade_pct_applied, 2),
        "fade_source": fade_source,
        "fade_notes": fade_notes,
        "heat_factor": round(heat_factor, 3),
        "heat_notes": heat_notes,
        "night": night,
        **({"technicity": technicity_info} if technicity_info is not None else {}),
        **({"pacing_personal": personal_applied} if personal_applied else {}),
        "altitude": altitude,
        "start_time": start_time,
        "race_date": race_date,
        "warnings": warnings,
        "assumptions": ASSUMPTIONS,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _resolve_fade(conn, today_date: date, args) -> Tuple[float, str]:
    """Fade médian des sorties longues récentes (#48), ou repli générique
    documenté — voir `ASSUMPTIONS["fade"]`. `conn` déjà ouvert/indexé par
    l'appelant (`main`, revue de code #59 : un seul passage d'indexation par
    appel CLI, jamais un par résolveur)."""
    if args.fade_pct is not None:
        return float(args.fade_pct), "override"
    import arc_index as IDX  # noqa: E402 (import tardif, voir docstring du module)
    trend = IDX.durability_trend(conn, today_date, args.fade_weeks or DEFAULT_FADE_WEEKS)
    measured = [p["gap_fade_pct"] for p in trend.get("points", []) if p.get("gap_fade_pct") is not None]
    if measured:
        return round(statistics.median(measured), 2), "durability_median"
    return DEFAULT_GENERIC_FADE_PCT, "generic"


def _resolve_model_bins(conn, conf: dict, args) -> Tuple[List[dict], Optional[float]]:
    """Paniers du modèle personnel + référence plate de la bande (voir
    `ASSUMPTIONS["base_pace"]`)."""
    import arc_index as IDX  # noqa: E402
    if args.months is not None:
        report = IDX.recompute_slope_model(conn, conf, args.band, args.months, args.today)
    else:
        report = IDX.slope_model_report(conn, args.band)
    return report.get("bins") or [], report.get("flat_reference_speed_ms")


def _resolve_acclimated(conn, conf: dict, today_date: date,
                         temp_max_c: Optional[float]) -> Tuple[Optional[bool], Optional[str]]:
    """`(acclimated, note)` — voir `ASSUMPTIONS["heat"]` ; logique partagée dans
    `arc_heat.resolve_acclimated` (#171)."""
    return resolve_acclimated(conn, conf, today_date, temp_max_c)


def _flat_equivalent_m(distance_m: Optional[float], elevation_gain_m: Optional[float], primary: str) -> float:
    """Distance équivalente plat (`arc_metrics.TRAIL_FLAT_M_PER_M_DPLUS`, trail
    uniquement — voir `ASSUMPTIONS["base_pace"]`). `0.0` si `distance_m` est
    absent."""
    if not distance_m or distance_m <= 0:
        return 0.0
    flat_m = distance_m
    if primary == "trail" and elevation_gain_m:
        flat_m += elevation_gain_m * M.TRAIL_FLAT_M_PER_M_DPLUS
    return flat_m


# D+ (m) par km du GPX ANALYSÉ au-delà duquel un parcours est traité « trail »
# pour choisir le panier de calibration énergétique (`arc_index.
# energy_calibration`) — approximation du projet, aucun seuil publié identifié
# pour cette distinction précise. Correctif de revue de code (BLOQUANT) :
# une version antérieure dérivait ce panier de `[sport].primary` (le PROFIL
# de l'athlète, config générale) — un plan de course POUR une course de road
# préparé par un trailer (ou l'inverse) aurait alors calibré sur le MAUVAIS
# panier. Le panier doit refléter LE PARCOURS de CETTE course précise, jamais
# le profil général de l'athlète.
TRAIL_GAIN_M_PER_KM = 15.0


def resolve_calibration_band(distance_m: Optional[float], elevation_gain_m: Optional[float],
                              terrain_option: Optional[str]) -> Tuple[str, str]:
    """`(band, band_source)` pour choisir le panier de calibration personnelle
    (route/trail, `arc_index.energy_calibration`) — voir `ASSUMPTIONS["energy"]`,
    section « Calibration personnelle ».

    `terrain_option` (CLI `--terrain road|trail`, choix EXPLICITE de
    l'athlète) prime TOUJOURS quand fourni -> `band_source="option"` — jamais
    remis en cause par le GPX, l'athlète peut savoir des choses que le tracé
    seul ne dit pas (ex. un parcours essentiellement plat mais couru en
    conditions « trail », sentier régulier sans road significative).

    Sans `--terrain`, dérivé du D+/km RÉEL du GPX analysé (`band_source=
    "gpx"`) — JAMAIS de `[sport].primary` (correctif de revue de code,
    BLOQUANT : le panier doit refléter LE PARCOURS de CETTE course, pas le
    profil général de l'athlète, voir `TRAIL_GAIN_M_PER_KM`) :
    `elevation_gain_m / (distance_m / 1000) >= TRAIL_GAIN_M_PER_KM` (15 m/km,
    approximation du projet) -> `"trail"`, sinon `"route"`. `distance_m`
    absente ou non positive (GPX sans distance exploitable) replie sur
    `"route"` (jamais de division par zéro) — reste `band_source="gpx"`, la
    valeur elle-même n'étant alors qu'un repli sûr, pas une vraie dérivation."""
    if terrain_option in ("road", "trail"):
        return ("trail" if terrain_option == "trail" else "route"), "option"
    if not distance_m or distance_m <= 0:
        return "route", "gpx"
    gain_per_km = (elevation_gain_m or 0.0) / (distance_m / 1000.0)
    return ("trail" if gain_per_km >= TRAIL_GAIN_M_PER_KM else "route"), "gpx"


def _riegel_time_s(time_s: float, distance_m: float, target_m: float, exponent: float,
                    ultra_exponent: float = RIEGEL_ULTRA_EXPONENT,
                    anchor_m: float = RIEGEL_ULTRA_ANCHOR_M) -> Optional[float]:
    """Riegel PAR MORCEAUX (3ᵉ revue de code #59, BLOQUANT) — voir
    `ASSUMPTIONS["base_pace"]` : `exponent` (bande route/trail,
    `arc_metrics.RIEGEL_EXPONENT`) jusqu'à `anchor_m` (42,195 km équivalent
    plat, la distance MARATHON), `ultra_exponent` (1.30) au-delà. Passe par le
    temps AU PIVOT (`anchor_m`), projeté depuis `distance_m`/`time_s` avec
    l'exposant du côté où `distance_m` se trouve — gère `distance_m >=
    anchor_m` de façon cohérente (référence déjà ultra : tout le trajet
    référence -> pivot -> cible utilise alors le même exposant si les deux
    sont au-delà du pivot, `ultra_exponent` s'annule algébriquement dans ce
    cas et redonne la formule Riegel directe référence -> cible). Se réduit
    EXACTEMENT à `arc_metrics.riegel` quand référence ET cible sont toutes
    deux `<= anchor_m` (aucun changement pour un marathon ou moins, voir les
    tests). `None` si une entrée est invalide."""
    if time_s <= 0 or distance_m <= 0 or target_m <= 0:
        return None
    exp_to_anchor = exponent if distance_m <= anchor_m else ultra_exponent
    time_at_anchor = time_s * (anchor_m / distance_m) ** exp_to_anchor
    exp_from_anchor = exponent if target_m <= anchor_m else ultra_exponent
    return time_at_anchor * (target_m / anchor_m) ** exp_from_anchor


def _select_hard_reference(conn, conf: dict) -> Optional[dict]:
    """Meilleur effort RÉCENT et DUR (planifié tempo+/seuil/VO2max/course, ou à
    défaut de plan FC moyenne au-dessus de la borne Z3/Z4 de l'athlète) — voir
    `ASSUMPTIONS["base_pace"]` (2ᵉ revue de code #59, BLOQUANT) : un footing
    facile, même long, n'est PAS une référence d'allure de COURSE. Rend
    l'activité (dict) la plus LONGUE parmi les qualifiantes (la plus
    prédictive — même principe que `arc_metrics.predictions`), ou `None`."""
    import arc_index as IDX  # noqa: E402 (import tardif, voir docstring du module)
    bounds = IDX.athlete_hr_zone_bounds(conn, conf)
    hard_hr_threshold = bounds[0][3] if bounds else None
    best = None
    for row in conn.execute(
            "SELECT date, sport, distance_m, duration_s, elevation_gain_m, avg_hr_bpm FROM activity "
            "WHERE sport IN ('running', 'trail') AND distance_m >= ? AND duration_s > 0",
            (MIN_REFERENCE_DISTANCE_M,)).fetchall():
        act = dict(row)
        planned = IDX.planned_intensity_for(conn, act.get("date"), act.get("sport"))
        if planned is not None:
            is_hard = planned in HARD_REFERENCE_INTENSITIES
        else:
            is_hard = (hard_hr_threshold is not None and act.get("avg_hr_bpm") is not None
                       and act["avg_hr_bpm"] >= hard_hr_threshold)
        if not is_hard:
            continue
        if best is None or act["distance_m"] > best["distance_m"]:
            best = act
    return best


def _resolve_intensity_factor(conn, conf: dict, flat_reference_speed_ms: Optional[float],
                               gpx_distance_m: Optional[float],
                               gpx_elevation_gain_m: Optional[float]
                               ) -> Tuple[float, str, Optional[float], List[str], float]:
    """`(intensity_factor, intensity_source, race_flat_speed_ms, notes,
    safe_scenario_factor)` — voir `ASSUMPTIONS["base_pace"]`. `intensity_source` :
    `"riegel"` (méthode retenue en priorité, référence dure exigée), `"vdot"`
    (repli) ou `"none"` (facteur `1.0`, allure d'endurance inchangée). La
    cible est TOUJOURS le GPX analysé (`gpx_distance_m`/`gpx_elevation_gain_m`),
    jamais `planning/active_objective.md` (2ᵉ revue de code #59, BLOQUANT) —
    un avertissement est ajouté à `notes` si l'objectif diffère sensiblement
    du GPX. `safe_scenario_factor` est élargi
    (`EXTRAPOLATION_SAFE_SCENARIO_FACTOR`) quand la cible extrapole à plus de
    `RIEGEL_EXTRAPOLATION_RATIO` fois la distance de la référence Riegel (3ᵉ
    revue de code #59, should-fix)."""
    notes: List[str] = []
    default_safe_factor = GENERIC_SCENARIO_SPEED_FACTOR["safe"]
    if not flat_reference_speed_ms or flat_reference_speed_ms <= 0:
        return 1.0, "none", None, notes, default_safe_factor
    primary = conf.get("sport", "trail")
    target_flat_m = _flat_equivalent_m(gpx_distance_m, gpx_elevation_gain_m, primary)
    if target_flat_m <= 0:
        return 1.0, "none", None, notes, default_safe_factor

    obj = conn.execute("SELECT distance_m, elevation_gain_m FROM objective LIMIT 1").fetchone()
    if obj and obj["distance_m"]:
        obj_flat_m = _flat_equivalent_m(obj["distance_m"], obj["elevation_gain_m"], primary)
        if obj_flat_m > 0 and abs(obj_flat_m - target_flat_m) / obj_flat_m * 100.0 > OBJECTIVE_GPX_MISMATCH_PCT:
            notes.append(
                f"l'objectif actif ({obj['distance_m']:.0f} m / {obj['elevation_gain_m'] or 0:.0f} m D+) et "
                f"le GPX analysé ({gpx_distance_m:.0f} m / {gpx_elevation_gain_m or 0:.0f} m D+) diffèrent "
                f"de plus de {OBJECTIVE_GPX_MISMATCH_PCT:g} % en équivalent plat : l'intensité de course "
                "est calculée depuis LE GPX, pas depuis l'objectif.")

    exponent = M.RIEGEL_EXPONENT.get(primary, M.RIEGEL_EXPONENT["road"])
    predicted_s: Optional[float] = None
    source = "none"
    safe_scenario_factor = default_safe_factor
    reference = _select_hard_reference(conn, conf)
    if reference:
        reference_flat_m = _flat_equivalent_m(reference["distance_m"], reference.get("elevation_gain_m"), primary)
        predicted_s = _riegel_time_s(reference["duration_s"], reference_flat_m, target_flat_m, exponent)
        if predicted_s is not None:
            predicted_s = round(predicted_s)  # jamais de fausse précision sous la seconde (comme arc_metrics.riegel)
        source = "riegel"
        # Extrapolation trop lointaine (3ᵉ revue de code #59, should-fix) : la
        # référence est trop courte pour porter confiance à la prédiction —
        # élargit le scénario "safe" plutôt que de le laisser artificiellement
        # étroit (voir ASSUMPTIONS["base_pace"]).
        if reference_flat_m > 0 and target_flat_m / reference_flat_m > RIEGEL_EXTRAPOLATION_RATIO:
            safe_scenario_factor = EXTRAPOLATION_SAFE_SCENARIO_FACTOR
            notes.append(
                f"la cible ({target_flat_m:.0f} m équivalent plat) fait plus de "
                f"{RIEGEL_EXTRAPOLATION_RATIO:g}× la référence Riegel retenue ({reference_flat_m:.0f} m) : "
                f"prédiction extrapolée loin de toute mesure — scénario « safe » élargi "
                f"({round((1 - EXTRAPOLATION_SAFE_SCENARIO_FACTOR) * 100)} % au lieu de "
                f"{round((1 - default_safe_factor) * 100)} %).")
    if not predicted_s:
        vo2max_row = conn.execute(
            "SELECT vo2max FROM metric_day WHERE vo2max IS NOT NULL ORDER BY date DESC LIMIT 1").fetchone()
        current_vdot = vo2max_row["vo2max"] if vo2max_row else None
        if current_vdot:
            predicted_s = M.predict_time_vdot(current_vdot, target_flat_m)
            source = "vdot"
    if not predicted_s or predicted_s <= 0:
        return 1.0, "none", None, notes, default_safe_factor

    race_flat_speed_ms = target_flat_m / predicted_s
    factor = race_flat_speed_ms / flat_reference_speed_ms

    # Plancher (2ᵉ revue de code #59, BLOQUANT) — voir ASSUMPTIONS["base_pace"] :
    # sous `INTENSITY_CLAMP_DURATION_S` (4h30), un facteur < 1.0 est implausible
    # (l'allure de course ne peut pas être plus lente que l'allure d'endurance
    # mesurée sur une distance courte). Aucun plancher au-delà : l'exposant
    # ultra (1.30 au-delà du marathon, `RIEGEL_ULTRA_EXPONENT`) prédit déjà,
    # à raison, un ralentissement marqué.
    if predicted_s < INTENSITY_CLAMP_DURATION_S and factor < 1.0:
        notes.append(
            f"facteur d'intensité calculé ({factor:.2f}) sous 1.0 pour une course prédite de "
            f"{predicted_s / 3600.0:.1f} h (< {INTENSITY_CLAMP_DURATION_S / 3600.0:.1f} h) : implausible "
            "(l'allure de course ne peut pas être plus lente que l'allure d'endurance mesurée sur cette "
            "distance) — plafonné à 1.0.")
        factor = 1.0

    return factor, source, race_flat_speed_ms, notes, safe_scenario_factor


def _load_aid_stations(path: Optional[str]) -> List[dict]:
    if not path:
        return []
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("--aid-stations : une liste JSON d'objets {km, name, cutoff?, cutoff_day?, stop_s?} "
                          "attendue")
    return data


def _validate_pack_kg(value: Optional[float]) -> float:
    """Valide `--pack-kg` — voir `ASSUMPTIONS["energy"]` et `PACK_KG_MIN`/
    `PACK_KG_MAX`. `None` (option omise) -> `DEFAULT_PACK_KG`, jamais une
    exception. Lève `ValueError` (message nommant la valeur reçue, même
    discipline que `_parse_hhmm`) sur une valeur non finie (NaN/infini) ou
    hors de `[PACK_KG_MIN, PACK_KG_MAX]` — jamais une valeur qui fausserait
    silencieusement la masse totale et donc tout le calcul d'énergie."""
    if value is None:
        return DEFAULT_PACK_KG
    if not math.isfinite(value):
        raise ValueError(f"--pack-kg : valeur finie attendue, « {value} » reçue.")
    if not (PACK_KG_MIN <= value <= PACK_KG_MAX):
        raise ValueError(
            f"--pack-kg : valeur entre {PACK_KG_MIN:g} et {PACK_KG_MAX:g} kg attendue, « {value:g} » "
            "reçue (poids du sac/flasques/matériel porté, jamais un poids corporel).")
    return value


def _validate_night_pct(value: Optional[float], default: float, label: str) -> float:
    """Valide une option de pénalité de nuit (%) : `None` -> défaut ; non finie ou hors
    `[0, NIGHT_PENALTY_PCT_MAX]` -> `ValueError` (jamais acceptée silencieusement)."""
    if value is None:
        return default
    if not math.isfinite(value) or not (0.0 <= value <= NIGHT_PENALTY_PCT_MAX):
        raise ValueError(f"{label} : valeur entre 0 et {NIGHT_PENALTY_PCT_MAX:g} attendue, « {value} » reçue.")
    return value


def _resolve_technicity(values: Optional[Sequence[str]], pts: Sequence[dict], workspace: Path,
                        baseline: Optional[str] = None) -> Optional[dict]:
    """Entrées CLI `--technicity` -> dict pour `build_race_plan` (I/O ici : fichier déclaré, Overpass).
    `None` si l'option est absente. Hors ligne / Overpass en erreur : pas de coefficient OSM,
    note explicite, jamais fatal. Lève `ValueError` (TechnicityError) sur une déclaration invalide."""
    if not values:
        if baseline:
            raise TECH.TechnicityError("--technicity-baseline n'a de sens qu'avec --technicity osm")
        return None
    declared, want_osm = None, False
    for v in values:
        if v.strip().lower() == "osm":
            want_osm = True
        else:
            declared = (declared or []) + TECH.load_declared(Path(v))
    base_coef, base_label = TECH.parse_baseline(baseline)
    if base_label and not want_osm:
        raise TECH.TechnicityError("--technicity-baseline n'a de sens qu'avec --technicity osm")
    out = {"declared": declared, "ways": None, "osm_requested": want_osm,
           "osm_baseline": base_coef, "osm_baseline_label": base_label}
    if want_osm:
        try:
            ways, info = TECH.fetch_ways(pts, cache_dir=Path(workspace) / ".arc" / "overpass")
            out.update(ways=ways, osm_status="ok", osm_note=None, osm_info={**info, "ways_found": len(ways)})
        except TECH.OverpassError as exc:
            out.update(osm_status="unavailable", osm_info=None,
                       osm_note=f"OpenStreetMap indisponible ({exc}) : aucun coefficient de technicité "
                                "dérivé d'OSM (déclarez --technicity fichier.json ou réessayez en ligne).")
    return out


def _validate_altitude_options(args) -> Tuple[float, float, Optional[int]]:
    """Valide `--altitude-threshold-m`, `--altitude-loss-pct` et `--altitude-acclimated-days`
    (jamais acceptées silencieusement hors bornes)."""
    thr = AL.ALTITUDE_THRESHOLD_M if args.altitude_threshold_m is None else args.altitude_threshold_m
    if not math.isfinite(thr) or not (0.0 <= thr <= AL.ALTITUDE_CAP_M):
        raise ValueError(f"--altitude-threshold-m : valeur entre 0 et {AL.ALTITUDE_CAP_M:g} attendue, « {thr} » reçue.")
    loss = AL.ALTITUDE_VO2MAX_LOSS_PCT_PER_1000M if args.altitude_loss_pct is None else args.altitude_loss_pct
    if not math.isfinite(loss) or not (0.0 <= loss <= AL.ALTITUDE_LOSS_PCT_MAX):
        raise ValueError(f"--altitude-loss-pct : valeur entre 0 et {AL.ALTITUDE_LOSS_PCT_MAX:g} attendue, « {loss} » reçue.")
    days = args.altitude_acclimated_days
    if days is not None and not (0 <= days <= AL.ALTITUDE_ACCLIMATED_DAYS_MAX):
        raise ValueError(f"--altitude-acclimated-days : entier entre 0 et {AL.ALTITUDE_ACCLIMATED_DAYS_MAX} attendu, « {days} » reçu.")
    return thr, loss, days


def _note_elevation_source(plan: dict) -> None:
    """Quand la correction MNT (#176) a été appliquée (`elevation_dem` du plan, statut autre que
    `unavailable`), les altitudes vues par la pénalité d'altitude sont celles du MNT : le dit."""
    dem = plan.get("elevation_dem")
    alt = plan.get("altitude") or {}
    if dem and dem.get("status") != "unavailable" and alt.get("status") == "applied":
        alt["elevation_source"] = "dem"


def _read_temp_max_c(args) -> Optional[float]:
    if args.temp_max_c is not None:
        return float(args.temp_max_c)
    if args.weather_file:
        text = Path(args.weather_file).read_text(encoding="utf-8")
        block = C.extract_block(text)
        if block:
            return block.get("temp_max_c")
    return None


def build_arg_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="Allures de course par segment depuis le modèle personnel pente -> allure (#59).")
    ap.add_argument("command", choices=("plan",), help="sous-commande (seule « plan » existe pour l'instant)")
    ap.add_argument("--gpx", required=True, type=Path, help="fichier GPX de la course")
    ap.add_argument("--workspace", help="racine du workspace (défaut : ARC_WORKSPACE, "
                                          "pointeur ~/.config/ai-running-coach/workspace, sinon répertoire courant)")
    ap.add_argument("--db", help="chemin de l'index SQLite (défaut : <workspace>/.arc/coach.db)")
    ap.add_argument("--memory", action="store_true", help="index en mémoire (tests)")
    ap.add_argument("--rebuild", action="store_true", help="repart de zéro pour l'index")
    ap.add_argument("--today", metavar="AAAA-MM-JJ", help="date de fin des séries pour les tendances (durabilité)")
    ap.add_argument("--band", choices=SL.BANDS, default=DEFAULT_BAND,
                     help="bande d'effort du modèle personnel (défaut « endurance »)")
    ap.add_argument("--months", type=int, help="recalcule le modèle sur N mois au lieu du modèle déjà stocké")
    ap.add_argument("--segment-m", type=float, default=DEFAULT_SEGMENT_M, dest="segment_m",
                     help="longueur cible d'un segment, en mètres (défaut 750)")
    ap.add_argument("--race-date", metavar="AAAA-MM-JJ", dest="race_date", help="date de la course")
    ap.add_argument("--start", default=None, help="heure de départ HH:MM (défaut 07:00 ; sans cette option "
                                                    "explicite, aucune pénalité de nuit n'est appliquée)")
    ap.add_argument("--tz", default=None,
                     help="fuseau horaire IANA de la course (ex. Europe/Paris) : requis, avec --race-date et "
                          "--start, pour la pénalité de nuit (heures de lever/coucher calculées localement)")
    ap.add_argument("--no-night", action="store_true", dest="no_night",
                     help="désactive la pénalité de nuit (voir ASSUMPTIONS['night'])")
    ap.add_argument("--night-penalty-pct", type=float, dest="night_penalty_pct",
                     help=f"pénalité de temps (%%) à pleine nuit sur plat/montée (défaut "
                          f"{NIGHT_BASE_PENALTY_PCT:g}, approximation du projet)")
    ap.add_argument("--night-descent-extra-max-pct", type=float, dest="night_descent_extra_max_pct",
                     help=f"supplément maximal (points de %%) de pénalité de nuit en descente (défaut "
                          f"{NIGHT_DESCENT_EXTRA_MAX_PCT:g}, approximation du projet)")
    ap.add_argument("--technicity", action="append", dest="technicity", metavar="FICHIER.json|osm",
                     help="coefficient de technicité du terrain par section (#186, ASSUMPTIONS['technicity']) : "
                          "un fichier JSON déclaré {\"sections\": [{\"km_start\", \"km_end\", \"coef\"}]} et/ou "
                          "`osm` (dérivé d'OpenStreetMap via Overpass, RÉSEAU, opt-in, GPX de COURSE seulement ; "
                          "cache <workspace>/.arc/overpass). Répétable ; la déclaration l'emporte section par "
                          "section. Absent = comportement inchangé")
    ap.add_argument("--technicity-baseline", dest="technicity_baseline", metavar="COEF|sac_scale",
                     help="terrain HABITUEL d'entraînement de l'athlète, pour ancrer les coefficients OSM "
                          "(son modèle pente -> allure le contient déjà) : nombre dans [1.0, 1.8] ou valeur "
                          "sac_scale (ex. mountain_hiking). Défaut : 1.0 = chemin facile, avec avertissement")
    ap.add_argument("--no-altitude", action="store_true", dest="no_altitude",
                     help="désactive la pénalité d'altitude (voir ASSUMPTIONS['altitude'])")
    ap.add_argument("--altitude-threshold-m", type=float, dest="altitude_threshold_m",
                     help=f"altitude (m) au-dessus de laquelle la pénalité s'applique (défaut "
                          f"{AL.ALTITUDE_THRESHOLD_M:g}, choix du projet)")
    ap.add_argument("--altitude-loss-pct", type=float, dest="altitude_loss_pct",
                     help=f"perte de VO2max (%% par 1000 m) retenue (défaut "
                          f"{AL.ALTITUDE_VO2MAX_LOSS_PCT_PER_1000M:g}, Wehrlin & Hallén 2006)")
    ap.add_argument("--altitude-acclimated-days", type=int, dest="altitude_acclimated_days",
                     help="jours déjà passés en altitude avant la course (acclimatation DÉCLARÉE ; sans "
                          "cette option, athlète supposé non acclimaté sauf exposition mesurée à l'entraînement)")
    ap.add_argument("--aid-stations", dest="aid_stations_path",
                     help="fichier JSON : liste d'objets {km, name, cutoff?, cutoff_day?, stop_s?}")
    ap.add_argument("--official-distance-m", type=float, dest="official_distance_m",
                     help="distance officielle de course (m) : rééchelonne les km de ravitaillement sur "
                          "la distance réellement mesurée du GPX")
    ap.add_argument("--fade-pct", type=float, dest="fade_pct",
                     help="fade (%%) explicite — sans cette option, médiane des sorties longues récentes "
                          "(#48) ou repli générique documenté")
    ap.add_argument("--fade-weeks", type=int, dest="fade_weeks",
                     help=f"fenêtre de la tendance de durabilité, semaines (défaut {DEFAULT_FADE_WEEKS})")
    ap.add_argument("--temp-max-c", type=float, dest="temp_max_c",
                     help="température maximale prévue le jour de la course (°C)")
    ap.add_argument("--weather-file", dest="weather_file",
                     help="fichier météo persisté (kind=weather) : temp_max_c lu depuis son bloc ```arc")
    ap.add_argument("--pack-kg", type=float, dest="pack_kg",
                     help=f"poids du sac/flasques/matériel porté (kg, {PACK_KG_MIN:g}-{PACK_KG_MAX:g}), "
                          "pour la dépense énergétique prévue — défaut 0.0 si omis, avec un "
                          "avertissement dans la sortie (voir ASSUMPTIONS['energy'])")
    ap.add_argument("--terrain", choices=("road", "trail"), default=None,
                     help="panier de calibration énergétique personnelle (route/trail, "
                          "voir ASSUMPTIONS['energy']) — force le choix explicitement ; sans cette "
                          "option, dérivé du D+/km RÉEL de ce GPX (TRAIL_GAIN_M_PER_KM), jamais du "
                          "profil général de l'athlète ([sport].primary)")
    ap.add_argument("--dem", action="store_true",
                     help="altitude corrigée par MNT public (IGN France / Copernicus ailleurs, #176) : "
                          "le D+ MNT devient la référence du plan, le D+ du fichier reste affiché "
                          "(`elevation_dem`). Envoie des coordonnées amincies au fournisseur ; hors "
                          "ligne, altitudes du fichier conservées avec un avertissement")
    ap.add_argument("--no-dem", action="store_true", dest="no_dem",
                     help="désactive la correction MNT même avec [elevation].dem = \"auto\"")
    return ap


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_arg_parser().parse_args(argv)
    if not args.gpx.exists():
        print(f"ERREUR : fichier GPX introuvable — {args.gpx}", file=sys.stderr)
        return 1
    pts = parse_gpx(args.gpx)
    if len(pts) < 2:
        print(f"ERREUR : GPX sans trace exploitable — {args.gpx}", file=sys.stderr)
        return 1
    start_time_known = args.start is not None
    args.start = args.start or "07:00"
    try:
        hh, mm = _parse_hhmm(args.start, label="--start")
        # Priorité : drapeau CLI > `[pacing.personal]` (#188) > défaut du projet. Validé après
        # lecture de la config (les défauts doivent rester dans [0, NIGHT_PENALTY_PCT_MAX]).
        workspace = workspace_root(args.workspace)
        personal = PP.read_workspace(workspace)
        for warning in personal["warnings"]:
            print(f"avertissement : {warning}", file=sys.stderr)
        personal_values = personal["values"]
        night_penalty_pct = _validate_night_pct(
            args.night_penalty_pct, personal_values.get("night_penalty_pct", NIGHT_BASE_PENALTY_PCT),
            "--night-penalty-pct")
        night_descent_extra_max_pct = _validate_night_pct(
            args.night_descent_extra_max_pct, NIGHT_DESCENT_EXTRA_MAX_PCT, "--night-descent-extra-max-pct")
        altitude_threshold_m, altitude_loss_pct, altitude_acclimated_days = _validate_altitude_options(args)
    except ValueError as exc:
        print(f"ERREUR : {exc}", file=sys.stderr)
        return 1
    print(f"heure de départ effective : {hh:02d}:{mm:02d}", file=sys.stderr)

    dem_info = None
    if args.dem and args.no_dem:
        print("ERREUR : --dem et --no-dem sont incompatibles.", file=sys.stderr)
        return 1
    import arc_dem as DEM
    dem_settings = DEM.load_settings(workspace)
    if args.dem or (dem_settings["dem"] == "auto" and not args.no_dem):
        dem_res = DEM.resample_track(
            pts, step_m=dem_settings["step_m"],
            cache=DEM.DemCache(DEM.cache_path(workspace), enabled=dem_settings["cache"]))
        if dem_res["status"] == "unavailable":
            dem_info = {"status": "unavailable", "error": dem_res["report"].get("error")}
            print(f"AVERTISSEMENT : correction MNT indisponible ({dem_info['error']}) — "
                  "altitudes du fichier conservées.", file=sys.stderr)
        else:
            dem_info = {"status": dem_res["status"],
                        # D+ fichier mesuré comme le plan l'aurait fait sans --dem (lissage
                        # 3 points, sans seuil : `course_totals`) : l'écart affiché est
                        # exactement l'effet de la correction sur le plan.
                        **DEM.compare_gain_loss([p.get("ele") for p in pts], dem_res["ele"],
                                                file_smooth=EL.DEFAULT_SMOOTH_TAPS, file_min_step_m=0.0),
                        "step_m": dem_res["report"]["step_m"], "providers": dem_res["report"]["providers"],
                        "attribution": dem_res["report"]["attribution"]}
            pts = [{**p, "ele": z} for p, z in zip(pts, dem_res["ele"])]

    # Index ouvert et reconstruit UNE SEULE FOIS (revue de code #59 : trois
    # réindexations indépendantes coûtaient ≈ 7,6 s contre ≈ 2,5 s pour une
    # seule) — chaque résolveur reçoit `conn`/`conf` déjà prêts.
    import arc_index as IDX
    conn = IDX.open_db(workspace, args.db, args.memory, args.rebuild)
    IDX.index_workspace(conn, workspace, args.today)
    conf = IDX.settings(IDX.load_config(workspace))
    today_date = date.fromisoformat(args.today) if args.today else date.today()

    bins, flat_reference_speed_ms = _resolve_model_bins(conn, conf, args)
    fade_pct, fade_source = _resolve_fade(conn, today_date, args)
    temp_max_c = _read_temp_max_c(args)
    altitude_exposure = None if args.no_altitude else IDX.altitude_exposure(conn, today_date)
    acclimated, acclimation_note = _resolve_acclimated(conn, conf, today_date, temp_max_c)
    # La cible d'intensité est TOUJOURS le GPX ANALYSÉ, jamais l'objectif (voir
    # ASSUMPTIONS["base_pace"], 2ᵉ revue de code #59, BLOQUANT).
    gpx_distance_m, gpx_elevation_gain_m, _gpx_elevation_loss_m = course_totals(pts)
    intensity_factor, intensity_source, _race_flat_speed, intensity_notes, safe_scenario_factor = \
        _resolve_intensity_factor(conn, conf, flat_reference_speed_ms, gpx_distance_m, gpx_elevation_gain_m)
    aid_stations = _load_aid_stations(args.aid_stations_path)
    try:
        technicity = _resolve_technicity(args.technicity, pts, workspace, args.technicity_baseline)
    except ValueError as exc:
        print(f"ERREUR : {exc}", file=sys.stderr)
        return 1

    # Poids de l'athlète à la date de la COURSE — MÊME résolveur que
    # `activity_energy`, voir ASSUMPTIONS["energy"] : jamais une seconde
    # implémentation de la priorité santé/nutrition/profil.
    athlete_row = conn.execute("SELECT * FROM athlete LIMIT 1").fetchone()
    athlete = dict(athlete_row) if athlete_row else {}
    energy_day = args.race_date or today_date.isoformat()
    weight_kg, weight_source = IDX.resolve_weight_kg_as_of(conn, energy_day, athlete)
    pack_kg_provided = args.pack_kg is not None

    # Calibration personnelle (voir ASSUMPTIONS["energy"], « Calibration personnelle ») :
    # panier route/trail dérivé DU PARCOURS (D+/km RÉEL de CE GPX,
    # `resolve_calibration_band`/`TRAIL_GAIN_M_PER_KM`) — correctif de revue de code,
    # BLOQUANT : jamais `[sport].primary` (profil GÉNÉRAL de l'athlète, qui peut très
    # bien préparer une course de nature différente de son profil habituel), sauf
    # override explicite `--terrain`.
    calibration_band, calibration_band_source = resolve_calibration_band(
        gpx_distance_m, gpx_elevation_gain_m, args.terrain)
    calibration_report = IDX.energy_calibration(conn, today_date)
    calibration = calibration_report["buckets"].get(calibration_band)
    try:
        pack_kg = _validate_pack_kg(args.pack_kg)
    except ValueError as exc:
        print(f"ERREUR : {exc}", file=sys.stderr)
        return 1

    # Coefficients personnels réellement appliqués (#188), consignés dans le plan : le débrief
    # en a besoin pour que ses estimations restent absolues (voir `arc_pacing_calibration`).
    personal_applied: Dict[str, float] = {}
    if args.night_penalty_pct is None and "night_penalty_pct" in personal_values and not args.no_night:
        personal_applied["night_penalty_pct"] = night_penalty_pct
    if technicity is not None and "technicity_scale" in personal_values:
        personal_applied["technicity_scale"] = personal_values["technicity_scale"]
    if temp_max_c is not None and temp_max_c > HEAT_HOT_C and "heat_hot_factor" in personal_values:
        personal_applied["heat_hot_factor"] = personal_values["heat_hot_factor"]

    try:
        plan = build_race_plan(
            pts, bins, aid_stations=aid_stations, fade_pct=fade_pct, fade_source=fade_source,
            temp_max_c=temp_max_c, acclimated=acclimated, acclimation_note=acclimation_note,
            intensity_factor=intensity_factor, intensity_source=intensity_source,
            intensity_notes=intensity_notes, safe_scenario_factor=safe_scenario_factor,
            flat_reference_speed_ms=flat_reference_speed_ms, band=args.band,
            official_distance_m=args.official_distance_m,
            start_time=args.start, race_date=args.race_date, segment_m=args.segment_m,
            weight_kg=weight_kg, weight_source=weight_source,
            pack_kg=pack_kg, pack_kg_provided=pack_kg_provided,
            calibration_band=calibration_band, calibration_band_source=calibration_band_source,
            calibration=calibration, tz=args.tz, start_time_known=start_time_known,
            night_enabled=not args.no_night, night_penalty_pct=night_penalty_pct,
            night_descent_extra_max_pct=night_descent_extra_max_pct, technicity=technicity,
            heat_hot_factor=personal_values.get("heat_hot_factor"),
            technicity_scale=personal_values.get("technicity_scale"), personal_applied=personal_applied,
            altitude_enabled=not args.no_altitude, altitude_threshold_m=altitude_threshold_m,
            altitude_loss_pct_per_1000m=altitude_loss_pct, altitude_acclimated_days=altitude_acclimated_days,
            altitude_exposure=altitude_exposure,
            # Priorité : --altitude-loss-pct (CLI) > [pacing.personal].altitude_scale > défaut.
            altitude_scale=(personal_values.get("altitude_scale") if args.altitude_loss_pct is None else None))
    except ValueError as exc:
        print(f"ERREUR : {exc}", file=sys.stderr)
        return 1
    if dem_info is not None:
        plan["elevation_dem"] = dem_info
        if dem_info["status"] != "unavailable":
            plan.setdefault("warnings", []).append(
                f"altitude corrigée par MNT (D+ fichier {dem_info['file_gain_m']:.0f} m, D+ MNT "
                f"{dem_info['dem_gain_m']:.0f} m) : le plan repose sur le D+ MNT — "
                + " ".join(dem_info["attribution"]))
    _note_elevation_source(plan)
    print(json.dumps(plan, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
