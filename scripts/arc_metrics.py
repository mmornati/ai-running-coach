#!/usr/bin/env python3
"""Métriques d'entraînement déterministes, calculées à partir de la base dérivée.

Partage des rôles : le LLM observe et juge (il écrit les fichiers et pose le
verdict du jour) ; ce module calcule. Aucune de ces valeurs n'est demandée au
modèle.

- Charge par séance : TRIMP de Banister (FC moyenne, FC repos/max du profil),
  repli sur le session-RPE de Foster quand la FC manque.
- Forme (modèle impulsion-réponse de Banister) : condition (42 j) et fatigue
  (7 j) en moyennes mobiles exponentielles, forme = condition(j-1) − fatigue(j-1),
  ACWR = fatigue / condition. Noms génériques à dessein : voir « Marques »
  dans README.md.
- Monotonie et strain de Foster sur 7 jours.
- VO2max effective par séance (allure + fraction de FC max), tendance 30 j.
- Prédictions : VDOT de Daniels et Riegel.
- Records sur fenêtres glissantes de splits (précision ±1 km).

Toutes les hypothèses sont exposées dans `ASSUMPTIONS`, que le tableau de bord
affiche : ces chiffres sont des modèles, pas des mesures.

Bibliothèque standard uniquement (CONTRIBUTING.md).
"""

from __future__ import annotations

import math
import statistics
import unicodedata
from datetime import date, timedelta
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

# ---------------------------------------------------------------------------
# Constantes et hypothèses
# ---------------------------------------------------------------------------

FITNESS_DAYS = 42
FATIGUE_DAYS = 7
ACWR_SAFE = (0.8, 1.3)
ACWR_MIN_FITNESS = 10.0  # condition quasi nulle (reprise, historique naissant) : le ratio n'a pas de sens

# Banister (1991) : coefficient de pondération exponentielle selon le sexe.
BANISTER_K = {"male": 1.92, "female": 1.67}
BANISTER_K_DEFAULT = 1.92          # sexe non renseigné : valeur classique, signalée

# Session-RPE → échelle TRIMP. Foster compte `minutes × RPE` (≈ 5 UA/min pour un
# effort modéré) ; un TRIMP d'endurance vaut ≈ 1,5 UA/min. Le facteur ramène les
# séances sans FC (renforcement, home trainer sans ceinture) sur la même échelle
# que les autres, sans quoi elles écraseraient la courbe de forme.
RPE_TO_TRIMP = 0.3
DEFAULT_RPE = {"strength": 5, "hiking": 3, "walking": 2, "rest": 0}
DEFAULT_RPE_OTHER = 4

# Équivalence effort du dénivelé en trail — même règle que
# `config/sports/trail.md` (« 1000 m D+ ≈ 1,5 à 2 km plat »), dont
# tests/data/test_arc_metrics.py vérifie l'accord. Milieu de la fourchette.
TRAIL_FLAT_KM_PER_1000M = (1.5, 2.0)
TRAIL_FLAT_M_PER_M_DPLUS = sum(TRAIL_FLAT_KM_PER_1000M) / 2      # 1,75 m plat par m D+

# Ligne de base HRV personnelle (#34) : moyenne glissante 7 j de ln(HRV) comparée à
# une référence 60 j ± 0,5 ET (Plews, Laursen & Buchheit 2013 ; Kiviniemi et al. 2007).
# Nombres de jours minimaux exigés avant d'afficher quoi que ce soit — sous ce seuil,
# le calcul rend `None` plutôt qu'une valeur bruitée.
HRV_LN_WINDOW_DAYS = 7          # fenêtre de la moyenne glissante à court terme
HRV_LN_MIN_VALID_DAYS = 5       # jours HRV valides exigés dans ces 7 j
HRV_REF_WINDOW_DAYS = 60        # fenêtre de la référence longue
HRV_REF_MIN_VALID_DAYS = 30     # jours HRV valides exigés dans ces 60 j
HRV_BAND_SD_MULT = 0.5          # largeur de bande : ± 0,5 écart-type (smallest worthwhile change)

RUNNING_SPORTS = ("running", "trail")
RIEGEL_EXPONENT = {"road": 1.06, "trail": 1.15}
VO2MAX_TREND_DAYS = 30
VO2MAX_PLAUSIBLE = (20.0, 90.0)
VO2MAX_MIN_DURATION_S = 20 * 60
VO2MAX_MAX_DURATION_S = 3 * 3600      # au-delà, dérive cardiaque et fatigue cassent la relation FC → VO2
VO2MAX_MAX_PACE_S_PER_KM = 510        # allure effort > 8:30/km : c'est de la marche, pas une estimation de course
VO2MAX_MAX_WEIGHT_S = 90 * 60         # un ultra de 15 h ne doit pas écraser un mois de séances
VO2MAX_MIN_HR_FRACTION = 0.70         # en dessous de 70 % de la FC max, la relation FC→VO2 est trop lâche
RECORD_DISTANCES_KM = (1, 5, 10, 21)
PREDICTION_DISTANCES_M = (5000.0, 10000.0, 21097.5, 42195.0)

# Dette de sommeil 7 j (#37) : besoin (profil, défaut 7 h 30) − sommeil réalisé,
# sur les nuits AVEC donnée seulement (une nuit manquante n'est jamais comptée
# comme 0 h — voir ASSUMPTIONS["sleep_debt"]).
SLEEP_DEBT_WINDOW_DAYS = 7        # fenêtre glissante
SLEEP_DEBT_MIN_NIGHTS = 4         # nuits mesurées exigées dans ces 7 j, sinon `None`
SLEEP_NEED_DEFAULT_S = 7 * 3600 + 30 * 60   # 7 h 30 : défaut de l'issue #37, si le profil est vide
# Seuils d'affichage (tableau de bord ET prose des agents) : repères indicatifs, pas
# un seuil médical — même statut que `ACWR_SAFE` ci-dessus. Choisis pour que le seuil
# « à surveiller » corresponde à peu près à une nuit complète de dette accumulée sur
# la fenêtre, et « nettement » à deux.
SLEEP_DEBT_WARN_S = 5 * 3600      # 5 h cumulées sur 7 j : à surveiller
SLEEP_DEBT_ALERT_S = 10 * 3600    # 10 h cumulées sur 7 j : nettement, allègement recommandé

# Acclimatation à la chaleur (#38) : séances outdoor jointes à la météo du même jour.
# Sports SANS variante indoor déclarée dans le contrat (running, trail, hiking, walking,
# cycling, swimming, rowing) sont traités comme outdoor par défaut — voir
# ASSUMPTIONS["heat_acclimation"] pour la justification et ses limites.
INDOOR_SPORTS = ("strength", "indoor_cycling", "home_trainer", "elliptical", "rest")
HEAT_WINDOW_DAYS = 14              # fenêtre glissante, aujourd'hui inclus
HEAT_THRESHOLD_C_DEFAULT = 25.0    # seuil « séance chaude », configurable ([health].heat_threshold_c)

# Tendance du poids (#36) : moyenne mobile 7 j vs cible, pente 4 semaines.
WEIGHT_AVG_WINDOW_DAYS = 7        # fenêtre de la moyenne mobile affichée dans le graphique
WEIGHT_AVG_MIN_VALID_DAYS = 3     # jours pesés exigés dans ces 7 j, sinon moyenne à None (trop bruitée)
WEIGHT_SLOPE_WINDOW_DAYS = 28     # fenêtre de la régression (4 semaines)
WEIGHT_SLOPE_MIN_POINTS = 5       # jours pesés exigés dans ces 28 j pour une pente fiable
WEIGHT_SLOPE_MIN_SPAN_DAYS = 14   # écart mini entre 1re et dernière pesée : pas de pente sur des points groupés

# Taux de sudation (#39) : dérivé par séance depuis les pesées avant/après effort.
# Voir ASSUMPTIONS["sweat_rate"] pour la formule complète et ses hypothèses.
# Borne haute à 4 l/h (pas 3) : la littérature documente des gros transpirateurs
# au-delà de 2,5-3 l/h en ambiance chaude (ex. sportifs d'élite), et une borne trop
# serrée écarterait silencieusement ces séances réelles plutôt que les erreurs de
# saisie qu'elle est censée filtrer.
SWEAT_RATE_PLAUSIBLE_L_H = (0.0, 4.0)
# En dessous de cette durée, l'erreur de pesée (résolution de la balance, habits,
# passage aux toilettes) domine le signal : sur 10 min, 0,1 kg d'imprécision vaut
# déjà 0,6 l/h d'écart. Pas de calcul en dessous, plutôt qu'un chiffre bruité.
SWEAT_RATE_MIN_DURATION_S = 45 * 60

# Kilométrage chaussures (#40) : sports qui usent une semelle. Course (RUNNING_SPORTS)
# et randonnée — un sport SANS variante indoor (contrairement à `INDOOR_SPORTS` pour la
# chaleur, ce n'est pas la même liste : le vélo/natation/aviron n'usent pas une paire
# de chaussures de course, même pratiqués outdoor). Voir ASSUMPTIONS["gear_mileage"].
GEAR_WEAR_SPORTS = RUNNING_SPORTS + ("hiking",)
# Seuil d'alerte par défaut si la puce du profil n'en précise pas (`arc_legacy.parse_gear`,
# segment « alerte NNN km ») — valeur courante pour une chaussure de route/trail.
GEAR_ALERT_THRESHOLD_M_DEFAULT = 700_000

# Glucides/h et taux de sudation sur les sorties longues (#41) : entraînement digestif.
# « Sortie longue » = duration_s STRICTEMENT supérieure à 90 min (issue #41), la même
# borne que celle citée pour le plan de course (60-90 g/h). Une séance de 90 min pile
# n'est pas une sortie longue au sens de ce KPI.
LONG_RUN_MIN_DURATION_S = 90 * 60
# Sports considérés (revue de code #41, blocker : sans filtre, un vélo de 3 h à 100 g/h
# plafonnait un plan de COURSE À PIED à 110 g/h). `RUNNING_SPORTS` (running, trail) —
# jamais `GEAR_WEAR_SPORTS`, qui inclut aussi `hiking` pour l'usure de semelle : une
# randonnée est typiquement beaucoup plus lente qu'un effort de course (allure, FC,
# dépense horaire), donc pas comparable à la cible glucides/h d'un plan de course à
# pied — l'inclure risquerait de faire plafonner (ou de gonfler) la cible sur un
# régime d'effort différent. Le vélo est exclu pour la même raison, en plus marquée :
# une intensité et une digestion à l'effort nettement différentes de la course à pied.
FUELING_SPORTS = RUNNING_SPORTS
# Fenêtre de tendance : 12 semaines glissantes, aujourd'hui inclus (choix de l'issue #41).
FUELING_TREND_WEEKS = 12
# Fourchette de repère généraliste (60-90 g/h), affichée comme guide, jamais comme
# seuil normatif — même statut que ACWR_SAFE/SLEEP_DEBT_WARN_S ci-dessus.
FUELING_TARGET_BAND_G_H = (60, 90)
# Marge de progression documentée au-dessus du meilleur débit réellement toléré à
# l'entraînement, utilisée par `course-strategist` pour plafonner l'objectif d'un
# plan de course : voir ASSUMPTIONS["fueling"]. Volontairement conservatrice : c'est
# une étape de projet documentée (pas une valeur validée par un essai contrôlé sur CE
# workspace), cohérente avec la littérature sur l'entraînement progressif de la
# tolérance digestive (Jeukendrup 2017, « Training the Gut for Athletes », Sports
# Medicine ; Costa et al. 2017, revue sur les troubles gastro-intestinaux d'exercice)
# qui documente une tolérance qui s'accroît par exposition répétée à l'effort, sans
# fixer de pourcentage de progression consensuel par unité de temps — la marge choisie
# ici reste donc une règle de projet, pas une valeur tirée de ces sources.
FUELING_MAX_MARGIN_G_H = 10

# Zones FC, temps en zone et polarisation 80/20 (#43). 5 zones, trois méthodes de
# calcul des bornes, choisies par précédence (voir `hr_zone_bounds`) : LTHR (FC au
# seuil) si connue, sinon Karvonen (réserve FC), sinon %FCmax, sinon aucune zone
# calculable. Voir ASSUMPTIONS["hr_zones"] pour la justification complète et les
# citations.
HR_ZONE_COUNT = 5
HR_ZONE_METHODS = ("lthr", "karvonen", "percent_max")
HR_ZONE_METHOD_DEFAULT = "auto"     # précédence : lthr -> karvonen -> percent_max
# Karvonen (réserve FC = FC max - FC repos) : bornes à 50/60/70/80/90/100 % de la
# réserve — même convention que `tests/lib/synthetic.py::KARVONEN_HRR_PCT`, pour que
# les tests de temps en zone (palier D) retombent exactement sur les bornes du
# générateur synthétique quand le profil type (FC repos 48, FC max 188) est utilisé.
HR_ZONE_KARVONEN_HRR_PCT = (0.50, 0.60, 0.70, 0.80, 0.90, 1.00)
# Friel (« The Triathlete's Training Bible », zones course à pied à partir de la FC
# au seuil lactique/LTHR) : Z1 < 85 %, Z2 85-90 %, Z3 90-95 %, Z4 95-100 %,
# Z5 >= 100 % de LTHR. Friel décrit en réalité TROIS paliers au-dessus du seuil
# (5a/5b/5c, respectivement 100-102 %, 102-106 % et > 106 % de LTHR) : notre Z5 les
# FUSIONNE en un seul, pour rester à 5 zones partout dans le projet (voir
# `HR_ZONE_COUNT`). Le premier terme (0.0) et le dernier (1.5) ne gouvernent aucun
# calcul (`hr_zone_of` sature la zone 1 vers le bas et la zone 5 vers le haut) : ils
# ne servent qu'à exposer une borne d'affichage cohérente.
HR_ZONE_LTHR_PCT = (0.0, 0.85, 0.90, 0.95, 1.00, 1.5)
# %FCmax : convention à 5 zones courante (Z1 < 60 %, Z2 60-70 %, Z3 70-80 %,
# Z4 80-90 %, Z5 90-100 %+ de la FC max) — la méthode de repli quand ni la FC au
# seuil ni la FC de repos ne sont connues (seule la FC max suffit).
HR_ZONE_PCT_MAX = (0.0, 0.60, 0.70, 0.80, 0.90, 1.5)
# Polarisation 80/20 façon Seiler (Seiler & Kjerland 2006 ; Seiler 2010, « What is
# best practice for training intensity and duration distribution in endurance
# athletes? ») : une APPROXIMATION du modèle à 3 zones (sous le premier seuil
# ventilatoire/lactique, entre les deux seuils, au-dessus du second), jamais une
# mesure de lactate ou de seuils ventilatoires réels — voir ASSUMPTIONS["hr_zones"].
#
# Les seuils Seiler ne tombent PAS sur les mêmes bornes bpm selon la méthode de
# zones : un simple mapping fixe des 5 zones (Z1+Z2/Z3/Z4+Z5) serait FAUX pour LTHR
# et %FCmax, où les bornes de zones répondent à une autre logique (paliers
# d'entraînement Friel/%FCmax, pas les seuils ventilatoires VT1/VT2 que Seiler
# suppose) — voir `seiler_bounds`, qui calcule deux bornes bpm DÉDIÉES par méthode
# plutôt que de réutiliser les bornes des 5 zones affichées :
# - Karvonen : le mapping Z1+Z2/Z3/Z4+Z5 EST correct ici, parce que nos bornes de
#   zones 3 et 4 (70 %/80 % de la réserve FC) sont déjà les seuils Seiler usuels sur
#   la réserve FC (Karvonen, Kentala & Mustala 1957 pour la réserve elle-même).
# - LTHR : les seuils Seiler sont à 90 % et 100 % de la LTHR, PAS aux bornes de nos
#   zones 2/3 (90 %, en fait identique) et 4/5 (100 %, identique aussi) — mais Z4
#   (95-99 % LTHR) reste alors dans la zone MODÉRÉE (encore sous le second seuil),
#   pas la difficile : `seiler_bounds("lthr")` regroupe donc Z1+Z2 facile,
#   Z3+Z4 modérée, Z5 difficile — jamais Z4+Z5 difficile comme pour Karvonen.
# - %FCmax : nos bornes de zones (60/70/80/90 %) NE correspondent à aucun seuil
#   ventilatoire usuel en %FCmax — les regrouper donnerait une polarisation
#   trompeuse (ex. Z3, 70-80 % FCmax, est typiquement SOUS VT1, pas « modérée »).
#   `seiler_bounds("percent_max")` calcule donc deux bornes INDÉPENDANTES des 5
#   zones affichées, à 82 % et 87 % de la FC max — une APPROXIMATION MAISON de
#   l'emplacement typique de VT1/VT2 en %FCmax pour un adulte entraîné, PAS une
#   valeur tirée d'une source vérifiée (aucune citation fiable trouvée pour ces
#   deux pourcentages précis — mieux vaut le dire explicitement que citer une
#   source invérifiable) : nettement moins précis qu'un test d'effort réel, d'où
#   l'usage du mot « approximation ». À affiner si une source solide se présente.
HR_ZONE_SEILER_PCT_MAX = (0.82, 0.87)

ASSUMPTIONS = {
    "trimp": "TRIMP de Banister : minutes × FCr × 0,64 × e^(k·FCr), FCr = (FC moy − FC repos) / (FC max − FC repos), "
             "k = 1,92 (homme) / 1,67 (femme).",
    "trimp_sex_default": "Sexe non renseigné dans le profil : k = 1,92 appliqué par défaut.",
    "srpe": f"Sans FC : session-RPE de Foster (minutes × RPE) × {RPE_TO_TRIMP} pour rester sur l'échelle TRIMP. "
            "RPE absent : valeur par défaut selon le sport (renforcement 5, randonnée 3, autres 4).",
    "form": f"Modèle impulsion-réponse de Banister : condition = moyenne exponentielle {FITNESS_DAYS} j de la charge, "
            f"fatigue = {FATIGUE_DAYS} j, forme = condition(j-1) − fatigue(j-1). D'autres outils nomment ces grandeurs "
            "CTL, ATL et TSB (marques revendiquées par Peaksware LLC / TrainingPeaks) ; calculées ici sur le TRIMP, "
            "nos valeurs ne sont pas comparables aux leurs.",
    "acwr": f"ACWR = fatigue / condition, affiché dès que la condition atteint {ACWR_MIN_FITNESS:g}. "
            f"La zone {ACWR_SAFE[0]}–{ACWR_SAFE[1]} est un repère indicatif, discuté dans la littérature, pas un seuil de blessure.",
    "monotony": "Monotonie de Foster = moyenne / écart-type de la charge quotidienne sur 7 j ; strain = charge 7 j × monotonie.",
    "hrv_baseline": f"Ligne de base HRV personnelle : moyenne glissante {HRV_LN_WINDOW_DAYS} j de ln(HRV nocturne) "
                    f"(min. {HRV_LN_MIN_VALID_DAYS} jours valides sur {HRV_LN_WINDOW_DAYS}, sinon aucune valeur), "
                    f"comparée à une référence glissante {HRV_REF_WINDOW_DAYS} j de ln(HRV) (moyenne et écart-type, "
                    f"min. {HRV_REF_MIN_VALID_DAYS} jours valides, sinon « en construction ») ± {HRV_BAND_SD_MULT:g} "
                    "écart-type — une largeur de bande couramment retenue comme « plus petit changement significatif » "
                    "(smallest worthwhile change) sur le lnRMSSD 7 j (Plews, Laursen & Buchheit 2013). La fenêtre de "
                    f"référence se termine {HRV_LN_WINDOW_DAYS} j AVANT le jour évalué (jours j-{HRV_LN_WINDOW_DAYS} à "
                    f"j-{HRV_LN_WINDOW_DAYS + HRV_REF_WINDOW_DAYS - 1}) : elle ne recouvre JAMAIS la fenêtre courte, "
                    "sinon la moyenne 7 j se retrouve diluée dans sa propre référence et l'écart entre les deux est "
                    "mécaniquement rétréci. Hypothèse : `hrv_overnight_ms` (moyenne nocturne Garmin) est traité comme "
                    "une mesure de type rMSSD — Garmin ne documente pas publiquement l'algorithme exact. Le passage "
                    "au log réduit l'asymétrie de la distribution du rMSSD (Plews et al. 2012 ; Plews, Laursen & "
                    "Buchheit 2013). Un jour sans mesure n'est jamais compté comme 0, il est simplement absent des "
                    "deux fenêtres. CV 7 j = écart-type / moyenne de ln(HRV) (pas des valeurs brutes) sur la fenêtre "
                    "courte, en pourcentage : Plews et al. (2012) évaluent la stabilité de la modulation "
                    "parasympathique sur le coefficient de variation du lnRMSSD hebdomadaire, pas sur la valeur "
                    "brute. Kiviniemi et al. (2007) est cité comme PRÉCÉDENT de l'entraînement individualisé guidé "
                    "par une bande statistique (± 1 écart-type autour de la puissance HF de la variabilité "
                    "cardiaque, une mesure et une largeur différentes de celles retenues ici) — pas comme source de "
                    "la largeur ± 0,5 ET ni du CV appliqués dans ce module. Écart-type demandé aux deux fenêtres : "
                    "population (division par N, pas N-1), cohérent avec le reste du module (`daily_series`, "
                    "monotonie de Foster). Ce statut n'est calculé et affiché qu'en `[health].morning_check = "
                    "\"full\"` : en `minimal`, seule la readiness est exposée (rien qui dépende de l'HRV) ; en "
                    "`off`, aucune donnée de santé n'est récupérée.",
    "vo2max": "VO2max effective : VO2 de l'allure (Daniels) ÷ fraction de VO2max estimée par (FC moy / FC max − 0,37) / 0,64. "
              "Calculée depuis l'allure et la FC MOYENNES de la séance (pas de série seconde par seconde) : "
              "ordre de grandeur, pas une mesure. Séances de course de 20 min à 3 h seulement, FC moy ≥ 70 % de la FC max, allure effort ≤ 8:30/km ; "
              "tendance 30 j pondérée par la durée, plafonnée à 90 min par séance.",
    "trail_equivalence": f"Trail : équivalence plat (prédictions) = distance + D+ × {TRAIL_FLAT_M_PER_M_DPLUS:g} "
                         "(config/sports/trail.md : 1000 m D+ ≈ 1,5 à 2 km plat). Sert uniquement aux prédictions "
                         "VDOT/Riegel ; à ne pas confondre avec le « km-effort ITRA » (`effort_km`, D+/100) "
                         "affiché dans le volume hebdomadaire.",
    "prediction": "Prédictions VDOT (Daniels) depuis la tendance VO2max, et Riegel depuis le meilleur effort récent "
                  "(exposant 1,06 route / 1,15 trail).",
    "records": "Records sur fenêtres de splits consécutifs d'environ 1 km : précision ±1 km.",
    "compliance": "Conformité plan vs réalisé : séances de repos hors calcul (sport ou intensité `rest`), "
                  "`cancelled` exclue du dénominateur (le contrat n'a pas de motif d'annulation distinct "
                  "médical/autre), `moved` exclue (pas de date cible dans le contrat), séance future de la semaine "
                  "en cours jamais comptée manquée, séance du jour même sans activité encore en attente (pas "
                  "manquée), `done` sans activité chiffrée exclue des ratios durée/D+ (comptée en séance faite "
                  "seulement), appariement séance ↔ activité par date + sport (route/trail/randonnée/marche et "
                  "variantes vélo interchangeables), les `done` explicites réservant leur activité avant les "
                  "séances sans statut.",
    "effort_km": "Km-effort ITRA : pour les activités de la famille course (`SPORT_FAMILY` = \"run\" : running, "
                 "trail, hiking, walking — cyclisme exclu), effort_km = distance_km + D+_m / 100. Absence de D+ : "
                 "0 m utilisé. Absence de distance : l'activité n'est pas comptée. Somme hebdomadaire calculée sur "
                 "les valeurs brutes puis arrondie une seule fois (pas la somme de valeurs déjà arrondies par "
                 "activité). Distinct de l'« équivalence plat » (`trail_equivalence`, D+ × 1,75) utilisée pour les "
                 "prédictions.",
    "sleep_debt": f"Dette de sommeil {SLEEP_DEBT_WINDOW_DAYS} j (#37) : somme, sur les nuits des "
                 f"{SLEEP_DEBT_WINDOW_DAYS} derniers jours AVEC une mesure de `sleep_total_s`, de "
                 "max(0, besoin − sommeil réalisé de la nuit). Une nuit ABSENTE de `medical/*_health.md` "
                 "n'est jamais comptée comme un manque de 0 h (elle est simplement ignorée, comme dans "
                 "`hrv_baseline`/`weight_trend`) — sans quoi un simple trou de synchronisation gonflerait "
                 "artificiellement la dette. Le résultat n'est rendu qu'à partir de "
                 f"{SLEEP_DEBT_MIN_NIGHTS} nuits mesurées sur les {SLEEP_DEBT_WINDOW_DAYS}, sinon `None` "
                 "— `nights_counted` est TOUJOURS rendu, y compris `None`, pour que l'appelant sache s'il "
                 "manque une nuit ou sept. Nuits EXCÉDENTAIRES (sommeil > besoin) : chaque nuit est "
                 "plafonnée à 0 avant sommation (`max(0, …)`), jamais sommée en négatif — une dette "
                 "« nette » qui autoriserait un excédent à compenser un déficit d'une autre nuit "
                 "suppose une récupération linéaire et immédiate que la littérature sur la dette de "
                 "sommeil ne documente pas (contrairement, par exemple, à la charge d'entraînement où "
                 "un jour de repos réduit authentiquement la fatigue accumulée) ; deux nuits courtes "
                 "suivies d'une longue nuit restent donc un déficit réel, pas un solde nul. Ce plafonnage "
                 "par nuit est délibérément plus CONSERVATEUR qu'un modèle de remboursement partiel "
                 "(« recovery sleep ») : la littérature sur la privation chronique de sommeil documente "
                 "une récupération réelle mais partielle et non linéaire des déficits (ex. Belenky et al. "
                 "2003 ; Banks & Dinges 2007, revue sur la dette de sommeil cumulative et la récupération "
                 "incomplète après une seule nuit de rattrapage) — nous ne modélisons aucun remboursement "
                 "du tout, par prudence, plutôt que de choisir un taux de remboursement partiel arbitraire "
                 "et invérifiable sur ce workspace. Seuils d'AFFICHAGE (tableau de bord, prose des agents), "
                 "repères indicatifs et non médicaux, même statut que `ACWR_SAFE` : "
                 f"{SLEEP_DEBT_WARN_S / 3600:g} h cumulées sur la fenêtre → « à surveiller », "
                 f"{SLEEP_DEBT_ALERT_S / 3600:g} h → « nettement », allègement recommandé — exposés "
                 "par `/api/health` (`thresholds.sleep_debt_warn_h`/`sleep_debt_alert_h`), jamais recalculés "
                 "séparément côté JS. Besoin "
                 "(`sleep_need_s`) : lu dans `planning/Runner_Profile.md` (« Besoin de sommeil », "
                 f"`arc_legacy.parse_profile`), sinon {SLEEP_NEED_DEFAULT_S / 3600:g} h par défaut "
                 "(7 h 30, valeur de l'issue #37) — jamais 8 h, chiffre plus courant mais non retenu ici. "
                 "Calculé et exposé seulement en `[health].morning_check = \"full\"` (même porte que "
                 "`hrv_baseline` : en `minimal`, seule la readiness sort du bilan matinal ; en `off`, "
                 "aucune donnée de santé n'est même récupérée) — voir `scripts/arc_index.py sleep-debt` "
                 "pour l'appel headless utilisé par les agents `coach`/`medical`.",
    "heat_acclimation": f"Acclimatation à la chaleur (#38) : sur les {HEAT_WINDOW_DAYS} derniers jours "
                 "(aujourd'hui inclus), jointure de chaque activité OUTDOOR avec le fichier météo "
                 "(`medical/*_meteo.md`) du MÊME JOUR calendaire. Outdoor / indoor : un sport listé "
                 "dans `INDOOR_SPORTS` (`strength`, `indoor_cycling`, `home_trainer`, `elliptical`, "
                 "`rest`) est exclu ; tout autre sport connu du contrat (`running`, `trail`, `hiking`, "
                 "`walking`, `cycling`, `swimming`, `rowing`) est traité comme outdoor par défaut — le "
                 "contrat ne distingue une variante indoor que pour le cyclisme (`indoor_cycling`/"
                 "`home_trainer` vs `cycling`) ; `swimming`/`rowing` peuvent en pratique se pratiquer "
                 "en piscine ou sur ergomètre, mais faute d'un `outdoor` explicite au niveau de "
                 "l'activité (contrairement à `week.sessions[].outdoor`, réservé au plan), les compter "
                 "en outdoor par défaut reste la lecture la plus proche du contrat existant. Séance "
                 "« chaude » : `temp_max_c` DU JOUR ≥ seuil (borne INCLUSE), défaut "
                 f"{HEAT_THRESHOLD_C_DEFAULT:g} °C, configurable (`[health].heat_threshold_c`). Le "
                 "contrat n'a pas d'heure de mesure météo infra-journalière : `temp_max_c` est le "
                 "maximum du jour entier, pas la température à l'heure de départ de la séance "
                 "(`start_time`) — une approximation CONSERVATRICE (une séance matinale par jour "
                 "caniculaire peut compter « chaude » alors qu'elle s'est déroulée avant la pointe de "
                 "chaleur) assumée en l'absence de données horaires ; le raffiner demanderait une "
                 "série météo horaire, hors contrat actuel. `temp_max_c` peut lui-même être une "
                 "PRÉVISION écrite plusieurs jours avant la séance (le skill `weather-forecast` ne "
                 "refetch pas un jour déjà persisté, règle d'idempotence < 24 h) et non une mesure a "
                 "posteriori : un écart entre la prévision et la météo réelle du jour n'est pas corrigé "
                 "rétroactivement. Plusieurs fichiers météo le même jour (plusieurs lieux) : priorité "
                 "au fichier dont `location` correspond à celui de l'activité — comparaison sur le nom "
                 "de VILLE (avant la première virgule, ex. « Annecy » dans « Annecy, France »), accents "
                 "et casse ignorés (`normalize_location`), pas une égalité de chaîne stricte. À défaut "
                 "de correspondance (activité sans lieu, ou aucun fichier météo du jour ne correspond) "
                 "MAIS que tous les fichiers du jour s'accordent sur le verdict chaud/pas chaud (même "
                 "seuil), ce verdict est quand même retenu — peu importe lequel des lieux est le bon "
                 "puisqu'ils concluent tous pareil (`_resolve_hot`). S'ils divergent (au moins un chaud, "
                 "au moins un non), l'activité est traitée comme SANS météo plutôt que de deviner "
                 "laquelle s'applique — voir `sessions_without_weather` ci-dessous. Un seul fichier "
                 "météo ce jour-là : il s'applique, quel que soit son lieu — c'est le fichier de la "
                 "séance d'ENTRAÎNEMENT du jour (le skill `weather-forecast` fetch d'abord le lieu "
                 "d'entraînement) ; ce raccourci n'est PAS repris pour la météo de la course d'un "
                 "objectif (`objective_forecast_hot`, `scripts/arc_serve.py::api_heat_acclimation`), "
                 "où un lieu de course lointain ne doit jamais hériter du seul fichier du jour si ce "
                 "fichier ne le nomme pas explicitement (`pick_weather_strict`, sans ce raccourci). "
                 "Absence TOTALE de fichier météo pour le jour : la séance n'est ni chaude ni froide, "
                 "elle est IGNORÉE du compte (`hot_sessions`/`hot_duration_s`) et comptée séparément "
                 "dans `sessions_without_weather` — sans quoi un simple trou de synchronisation météo "
                 "ferait baisser artificiellement le compte de séances chaudes. Rendu : "
                 "`hot_sessions` (nombre), `hot_duration_s` (somme de `duration_s` des séances "
                 "chaudes), `sessions_considered` (total des séances outdoor de la fenêtre, chaudes "
                 "ou non, hors sans-météo), `sessions_without_weather`, `window_days`, `threshold_c`. "
                 "Aucun seuil minimal de séances avant affichage (contrairement à `sleep_debt`/"
                 "`hrv_baseline`) : `0` séance chaude sur la fenêtre est une réponse valide en soi, pas "
                 "une valeur bruitée à masquer. `[health].heat_threshold_c` invalide (texte non "
                 "numérique, booléen, section absente…) : jamais d'exception qui casserait TOUT appel "
                 "de `scripts/arc_index.py` (index, hrv-baseline, sleep-debt, heat-acclimation) ni "
                 "l'actualisation du tableau de bord — repli sur le défaut avec un avertissement, voir "
                 "`arc_index.py::settings`.",
    "weight_merge": "Fusion des deux sources de poids (#36) : le contrat n'a pas de champ d'heure de mesure "
                    "dédié, mais `health.weight_kg` est renseigné pendant le bilan matinal (`morning_check`) — "
                    "traité comme la pesée du matin — tandis que `nutrition.weight_kg` n'a aucune garantie "
                    "d'horaire. Un jour où les deux sont présents : `health` gagne TOUJOURS, jamais de moyenne "
                    "des deux sources ni de préférence à la plus récemment écrite. Un jour sans aucune des deux : "
                    "absent, jamais 0. Doublon DANS une même source (deux fichiers santé, ou deux fichiers "
                    "nutrition, pour la même date — pas d'heure de mesure pour départager) : le `source_path` le "
                    "plus grand par ordre alphabétique gagne, appliqué en base par `arc_serve.py` (`ORDER BY date, "
                    "source_path` avant fusion ; `ORDER BY date DESC, source_path DESC` pour la cible la plus "
                    "récente) — jamais l'ordre arbitraire que rendrait SQLite sans tri explicite.",
    "weight_trend": f"Moyenne mobile {WEIGHT_AVG_WINDOW_DAYS} j du poids fusionné (`weight_merge`) : moyenne des "
                    f"jours PRÉSENTS dans la fenêtre (jour manquant jamais compté 0), rendue seulement à partir de "
                    f"{WEIGHT_AVG_MIN_VALID_DAYS} jours pesés sur les {WEIGHT_AVG_WINDOW_DAYS}, sinon `None`. "
                    "`avg7_kg`/`gap_kg` exposés par `/api/nutrition` sont TOUJOURS la valeur DU JOUR (aujourd'hui), "
                    "jamais la dernière moyenne non nulle trouvée plus tôt dans la fenêtre affichée — une pesée "
                    "vieille de plusieurs semaines ne doit jamais s'afficher comme si elle datait d'aujourd'hui ; "
                    "`avg7_date` porte la date effectivement utilisée. Écart à la cible = moyenne 7 j du jour − "
                    "`target_weight_kg` le plus récent connu (nutrition uniquement dans le contrat) ; positif = "
                    "au-dessus de la cible. Pente 4 semaines : régression des moindres carrés (x = jour, y = poids "
                    f"fusionné, PAS la moyenne lissée) sur les {WEIGHT_SLOPE_WINDOW_DAYS} derniers jours, convertie "
                    f"en kg/semaine (× 7) ; rendue seulement à partir de {WEIGHT_SLOPE_MIN_POINTS} jours pesés ET "
                    f"{WEIGHT_SLOPE_MIN_SPAN_DAYS} jours d'écart entre la première et la dernière pesée de la "
                    "fenêtre (sinon `None`) — sans ce second seuil, quelques pesées groupées sur deux ou trois "
                    "jours donneraient une pente extrapolée sur 4 semaines à partir d'un intervalle bien trop "
                    "court pour être fiable. Aucun commentaire normatif n'est dérivé de ces chiffres : chiffres "
                    "seulement (voir issue #36).",
    "sweat_rate": "Taux de sudation par séance (#39) : ((weight_pre_kg − weight_post_kg) + fluid_intake_ml / 1000) "
                 "/ durée en heures, calculé UNIQUEMENT quand weight_pre_kg, weight_post_kg et une durée sont "
                 "tous les trois présents dans le bloc ```arc de l'activité — sinon `None`, jamais estimé. "
                 "Durée : `duration_s` (durée TOTALE de la sortie), PAS `moving_duration_s` — la pesée encadre la "
                 "sortie entière (avant le départ, après le retour), et la transpiration comme l'ingestion "
                 "continuent pendant les arrêts (ravitaillement, photo, pause à un point d'eau) ; utiliser la "
                 "seule durée de mouvement sous-estimerait le temps réel d'exposition. Sous "
                 f"{SWEAT_RATE_MIN_DURATION_S / 60:g} min, `None` : sur une sortie courte, l'imprécision d'une "
                 "pesée maison (résolution de la balance, habits, passage aux toilettes) domine le signal — un "
                 "écart de 0,1 kg sur 10 min vaut déjà plusieurs l/h d'erreur. `fluid_intake_ml` absent est traité "
                 "comme 0 dans le calcul et documenté ici plutôt que dans le contrat : le résultat devient alors "
                 "une BORNE BASSE (l'athlète a pu boire sans le déclarer). Ce chiffre reste néanmoins une "
                 "APPROXIMATION dans les deux sens, jamais une mesure : la perte urinaire (non soustraite) et la "
                 "perte d'eau respiratoire/métabolique (comptée à tort comme de la sueur) le SURESTIMENT ; la "
                 "masse des aliments solides ingérés (gels, barres — non retranchée du poids « après ») le "
                 "SOUS-ESTIME légèrement. Résultat négatif — chaque fois que (weight_pre_kg − weight_post_kg) + "
                 "fluid_intake_ml / 1000 < 0, y compris sans franchir l'avertissement du contrat "
                 "(`arc_contract.WEIGHT_POST_TOLERANCE_KG`), ex. 70 → 70,5 kg sans liquide déclaré — ou hors plage "
                 f"plausible {SWEAT_RATE_PLAUSIBLE_L_H[0]:g}-{SWEAT_RATE_PLAUSIBLE_L_H[1]:g} l/h → `None`, jamais "
                 "affiché tel quel. Alimente #41 (KPI glucides/h et taux de sudation).",
    "fueling": "Glucides/h et taux de sudation sur les sorties longues (#41), entraînement "
               "digestif. `carbs_per_hour_g` (fonction `carbs_per_hour_g`) = `carbs_g` / "
               f"(`duration_s` en heures), calculé UNIQUEMENT pour les séances de plus de "
               f"{LONG_RUN_MIN_DURATION_S / 60:g} min (`LONG_RUN_MIN_DURATION_S`, la même borne "
               "que le repère 60-90 g/h cité aux plans de course) — sous ce seuil, `None` (pas "
               "une sortie longue au sens de ce KPI), tout comme si `carbs_g` est absent (jamais "
               "0 par défaut : un `carbs_g` explicitement à 0 reste un 0 g/h légitime, une "
               "absence de déclaration n'en est pas un). Sport : `FUELING_SPORTS` (running, trail) "
               "SEULEMENT (revue de code #41, blocker) — jamais `GEAR_WEAR_SPORTS`, qui inclut "
               "aussi la randonnée pour l'usure de semelle : une randonnée est typiquement bien "
               "plus lente qu'un effort de course (allure, FC, dépense horaire), et le vélo a une "
               "intensité et une digestion à l'effort différentes ; sans ce filtre, un long vélo à "
               "haut débit glucidique gonflerait `max_carbs_per_hour_g` et donc le plafond d'un "
               "plan de COURSE À PIED. Durée : `duration_s` (durée TOTALE), "
               "la même que `sweat_rate_l_h` ci-dessus — cohérence entre les deux KPI dérivés de "
               "la même sortie, tous deux encadrés par la pesée/le ravitaillement sur la sortie "
               "entière, arrêts compris. `sweat_rate_l_h` n'est JAMAIS recalculé ici : "
               "`fueling_trend` réutilise tel quel le champ déjà dérivé à l'indexation "
               "(`arc_metrics.sweat_rate_l_h`), pour ne jamais faire dériver deux définitions du "
               "même chiffre. `fueling_trend` agrège les sorties longues des "
               f"`FUELING_TREND_WEEKS` ({FUELING_TREND_WEEKS}) dernières semaines glissantes "
               "(aujourd'hui inclus) : `max_carbs_per_hour_g` (le plus haut débit observé sur "
               "une sortie longue de la fenêtre — c'est le seul repère de tolérance dont on "
               "dispose : le contrat n'a AUCUN champ de trouble digestif déclaré, donc « toléré » "
               "veut seulement dire « ingéré sans qu'un problème n'ait été signalé ailleurs », "
               "jamais une vraie mesure de tolérance — à confirmer par l'athlète ou l'agent avant "
               "de s'en servir comme plafond dur), `carbs_per_hour_n` (nombre de sorties longues "
               "AVEC un `carbs_per_hour_g` défini, pour que l'appelant sache si le maximum repose "
               "sur une ou dix séances), `median_sweat_rate_l_h` et `sweat_rate_n` (médiane et "
               "effectif des `sweat_rate_l_h` non `None` sur la même fenêtre — une médiane "
               "plutôt qu'une moyenne : un seul jour très chaud ne doit pas à lui seul déplacer "
               "le repère). Une sortie longue sans aucune des deux valeurs compte quand même dans "
               "`long_runs` (nombre total de sorties longues de la fenêtre) : elle prouve qu'un "
               "entraînement digestif a eu lieu, même non chiffré. Fenêtre volontairement "
               "identique pour les deux KPI (jamais une fenêtre glucides et une fenêtre sudation "
               "différentes) : ce sont les mêmes séances qui alimentent les deux courbes du même "
               "graphique de tendance. `fueling_carbs_ceiling` = "
               "min(`max_carbs_per_hour_g` + `FUELING_MAX_MARGIN_G_H`, "
               f"max(`FUELING_TARGET_BAND_G_H[1]` ({FUELING_TARGET_BAND_G_H[1]:g}), "
               "`max_carbs_per_hour_g`)), arrondi PAR EXCÈS (`math.ceil`, jamais `round` : un plafond ne doit jamais tomber sous le débit réellement observé) — plafond réaliste proposé à "
               "`course-strategist` pour un plan de course, PAS une limite physiologique dure. "
               f"La marge (`FUELING_MAX_MARGIN_G_H`, {FUELING_MAX_MARGIN_G_H:g} g/h) reste une "
               "étape de projet CONSERVATRICE, cohérente avec la littérature sur l'entraînement "
               "progressif de la tolérance digestive (Jeukendrup 2017, « Training the Gut for "
               "Athletes », Sports Medicine ; Costa et al. 2017, revue sur les troubles "
               "gastro-intestinaux d'exercice) qui documente une tolérance qui s'accroît par "
               "exposition répétée à l'effort, sans fixer de pourcentage de progression "
               "consensuel — PAS une valeur tirée telle quelle de ces sources. Le plafond ne "
               "dépasse JAMAIS le haut du repère généraliste (90 g/h) sauf si l'athlète a DÉJÀ "
               "personnellement démontré un débit supérieur, auquel cas aucune marge "
               "supplémentaire n'est ajoutée au-delà de ce qu'il a prouvé (revue de code #41, "
               "SHOULD-FIX 3 : sans cette borne, un athlète déjà à 85 g/h recevait un plafond à "
               "95 g/h, au-dessus du haut de la fourchette généraliste sans qu'un dixième gramme "
               "au-delà de 90 n'ait jamais été démontré). `None` sans aucune sortie longue "
               "chiffrée sur la fenêtre : le stratège garde alors le repère générique 60-90 g/h "
               "(`FUELING_TARGET_BAND_G_H`) et doit suggérer un entraînement digestif progressif "
               "plutôt que d'inventer un plafond. Moins de 3 sorties longues chiffrées "
               "(`carbs_per_hour_n` < 3) : le plafond tient sur trop peu de données pour être "
               "présenté comme fiable — `course-strategist`/`nutritionist` doivent le signaler "
               "(« repose sur seulement N sortie(s) ») et suggérer de le confirmer à la prochaine "
               "sortie longue, plutôt que de le donner pour acquis. Non soumis à "
               "`[health].morning_check` : ne dépend d'aucune donnée de santé, seulement des "
               "activités déjà indexées.",
    "gear_mileage": "Kilométrage chaussures (#40) : somme de `distance_m` des activités de sport dans "
                 f"`GEAR_WEAR_SPORTS` ({', '.join(GEAR_WEAR_SPORTS)}) — course et randonnée seulement (la "
                 "marche, `walking`, n'y est délibérément PAS incluse : elle use une semelle bien plus lentement "
                 "et le contrat ne distingue pas une marche d'entraînement d'une simple promenade), un sport "
                 "hors de cette liste (vélo, natation, renforcement…) n'est jamais compté, même avec un "
                 "`gear_id` renseigné par erreur. Attribution : `gear_id` explicite de l'activité si présent — "
                 "JAMAIS filtré par une date, voir plus bas — sinon la chaussure marquée `(par défaut)` dans le "
                 "profil si une seule l'est (la première rencontrée si plusieurs, cas non censé arriver mais pas "
                 "une erreur), sinon la séance est IGNORÉE (ni comptée nulle part, ni signalée) — c'est le "
                 "comportement documenté par #40 : sans chaussure par défaut déclarée, une activité sans "
                 "`gear_id` n'a simplement rien à raconter côté matériel. `gear_id` explicite qui ne correspond "
                 "à AUCUNE chaussure du profil (faute de frappe, chaussure jamais déclarée) : jamais éliminé "
                 "silencieusement, regroupé sous `unknown` avec son kilométrage — libellé « inconnue » côté "
                 "tableau de bord. Date `depuis` du profil : filtre l'attribution PAR DÉFAUT SEULEMENT (revue "
                 "PR #85, blocker 1) — une séance sans `gear_id` datée AVANT le `depuis` de la chaussure "
                 "`(par défaut)` n'y est PAS attribuée (sans ce filtre, toute activité antérieure à #39, y "
                 "compris des années d'historique sans `gear_id` au contrat, se retrouverait comptée sur une "
                 "paire achetée hier) ; sans `depuis` déclaré sur la chaussure par défaut, aucun filtre, comme "
                 "avant. À l'inverse, une activité portant un `gear_id` EXPLICITE compte quel que soit son "
                 "rapport à `depuis` (même avant) : l'explicite du `gear_id` prime toujours sur une date de "
                 "début possiblement oubliée ou approximative — ne pas la compter risquerait de sous-estimer "
                 "silencieusement l'usure réelle, l'erreur la plus coûteuse ici. Seuil d'alerte : celui de la "
                 f"puce (segment « alerte NNN km », ou « alerte NNN miles/mi » — converti × 1609,344 — voir "
                 f"`arc_legacy.parse_gear`) si renseigné, sinon {GEAR_ALERT_THRESHOLD_M_DEFAULT / 1000:g} km par "
                 "défaut (`GEAR_ALERT_THRESHOLD_M_DEFAULT`) — TOUTE chaussure déclarée peut donc alerter, avec "
                 "ou sans seuil explicite ; `threshold_m` toujours arrondi à l'entier avant sérialisation "
                 "(cohérence de type JSON, valeur déclarée ou valeur par défaut). Chaussure `(retirée)` : "
                 "kilométrage affiché (historique), mais jamais d'alerte, et jamais candidate à l'attribution "
                 "par défaut même si `(par défaut)` est aussi coché sur la même puce (une chaussure qu'on ne "
                 "porte plus ne doit pas absorber les séances sans `gear_id`) — priorité documentée : retraite "
                 "avant défaut. Deux puces qui dérivent le même slug (rachat du même modèle sans `id:` pour les "
                 "distinguer) : `arc_legacy.parse_gear` renomme les suivantes `-2`, `-3`… plutôt que de laisser "
                 "la dernière écraser la première dans l'index, et la collision remonte dans `warnings`.",
    "hr_zones": "Zones FC, temps en zone et polarisation 80/20 (#43) : des APPROXIMATIONS d'entraînement, "
                "jamais une mesure physiologique directe (pas de test d'effort, pas de lactate, pas de "
                "seuils ventilatoires mesurés) — voir plus bas pour la polarisation, la plus approximative "
                "des deux. 5 zones, méthode de calcul des bornes choisie par PRÉCÉDENCE (configurable, "
                "`[athlete].hr_zones` dans `config/workspace.toml`, valeurs `\"auto\"` (défaut) | `\"lthr\"` | "
                "`\"karvonen\"` | `\"percent_max\"`, insensible à la casse, tout le reste retombant sur "
                "`\"auto\"` avec un avertissement — voir `arc_index.py::_hr_zone_method` — une valeur explicite "
                "FORCE cette méthode, sans repli si les champs qu'elle demande manquent, auquel cas aucune "
                "zone n'est calculée MAIS la raison est rendue explicitement par `hr_zone_resolution` (jamais "
                "une simple absence silencieuse) : "
                "1) LTHR (`hr_threshold_bpm` du profil, « FC au seuil ») si renseignée — Friel "
                "(« The Triathlete's Training Bible »), zones course à pied à 5 paliers : "
                f"{', '.join(f'Z{i+1} {round(HR_ZONE_LTHR_PCT[i]*100)}-{round(HR_ZONE_LTHR_PCT[i+1]*100)} %' for i in range(5))} "
                "de la LTHR (dernière borne ouverte vers le haut) — Friel décrit en réalité trois paliers "
                "au-dessus du seuil (5a/5b/5c) que notre Z5 FUSIONNE, pour rester à 5 zones partout dans le "
                "projet ; "
                "2) Karvonen (réserve FC = FC max - FC repos, `hr_max_bpm`/`hr_rest_bpm` du profil) sinon, "
                f"bornes à {', '.join(f'{round(p*100)} %' for p in HR_ZONE_KARVONEN_HRR_PCT)} de la réserve — "
                "MÊME convention que `tests/lib/synthetic.py::KARVONEN_HRR_PCT`, ce qui permet aux tests de "
                "temps en zone (palier D) de comparer directement le temps en zone calculé à la vérité connue "
                "du générateur synthétique sur le profil type (FC repos 48, FC max 188 -> bornes 118/132/146/"
                "160/174/188 bpm) — NOTE : le workspace synthétique type renseigne AUSSI une FC au seuil "
                "(172 bpm), donc `\"auto\"` y résout en réalité sur LTHR, pas Karvonen (voir tests/README.md) ; "
                "cette comparaison directe ne vaut que si `[athlete].hr_zones = \"karvonen\"` est forcé, ou si "
                "le profil ne porte pas de FC au seuil ; "
                "3) %FCmax sinon (`hr_max_bpm` seul suffit), bornes à "
                f"{', '.join(f'{round(p*100)} %' for p in HR_ZONE_PCT_MAX)} de la FC max — convention à 5 "
                "zones courante quand ni la FC de repos ni la FC au seuil ne sont connues ; "
                "4) aucune zone calculée si même la FC max manque (`hr_zone_bounds` rend `None`) — jamais de "
                "bornes inventées. `hr_zone_of` sature : tout ce qui est sous la 2ᵉ borne tombe en zone 1, tout "
                "ce qui est au-delà de la 5ᵉ (dernière) borne tombe en zone 5, la 1ʳᵉ et la 6ᵉ valeur de chaque "
                "tuple ne sont que des repères d'affichage internes (JAMAIS montrées telles quelles à "
                "l'utilisateur : l'interface n'affiche que les bornes intérieures, « Z1 < X », « Z5 ≥ Y », le "
                "temps sous le plancher théorique de Z1 comptant quand même en Z1). "
                "Restreint aux sports de la famille course à pied (`arc_metrics.sport_family(sport) == "
                "\"run\"` : course, trail, randonnée, marche) : le renforcement et le vélo (d'intérieur ou "
                "non) sont EXCLUS du temps en zone et de la polarisation, même avec des échantillons FIT "
                "ingérés — une FC élevée en renforcement (musculation, gainage) répond à un effort "
                "essentiellement anaérobie/technique sans rapport avec les zones aérobies d'endurance, et le "
                "vélo a en pratique une FC au seuil différente de la course à pied que le profil ne "
                "renseigne pas séparément ; les compter gonflerait ou fausserait silencieusement la "
                "polarisation hebdomadaire. La randonnée et la marche restent incluses (même famille "
                "`\"run\"` que le reste du projet, ex. `GEAR_WEAR_SPORTS`, `effort_km`) : leur FC répond au "
                "même modèle aérobie que la course, à une intensité différente. "
                "Temps en zone (`time_in_zone_seconds`) : calculé sur les échantillons déjà sous-échantillonnés "
                "de `arc_index.samples`/`samples_by_garmin_id` (résolution par défaut 5 s, `arc_samples."
                "DEFAULT_RESOLUTION_S`), triés par `t_s`. Chaque échantillon pèse la durée `dt` jusqu'au "
                "suivant, PLAFONNÉE à la résolution du sous-échantillonnage : une pause ou un trou de signal "
                "(`arc_samples.ASSUMPTIONS[\"gaps\"]`, `dt` peut dépasser la résolution après un trou) n'est "
                "donc JAMAIS compté comme du temps en zone — sans ce plafond, une montre restée en veille "
                "30 min gonflerait artificiellement la zone où la FC se trouvait juste avant la pause. Le "
                "DERNIER échantillon d'une séance (pas de suivant pour mesurer `dt`) est compté pour la "
                "résolution nominale de son propre bucket. Un `hr_bpm` absent (`None`, capteur décroché) est "
                "ignoré : ni zone, ni secondes comptées pour cet échantillon — cohérent avec le reste du "
                "projet (mesure absente = absente, jamais 0). Recalculé pour CHAQUE activité à CHAQUE passage "
                "de `arc_index.index_workspace` (jamais mis en cache par fichier comme les tables `PER_FILE_"
                "TABLES`) : un changement du profil (FC max/repos/seuil, ou `[athlete].hr_zones`) est donc "
                "répercuté dès le prochain index, incrémental ou `--rebuild`, sans étape supplémentaire. "
                "Polarisation (`seiler_bounds` + `polarisation_shares`, modèle 3 zones de Seiler) : ENCORE "
                "PLUS approximative que le temps en zone, parce que le seuil qui sépare « facile » de "
                "« modérée » et « modérée » de « difficile » ne tombe PAS sur les mêmes bornes bpm que les 5 "
                "zones affichées selon la méthode — `seiler_bounds` calcule donc deux bornes bpm DÉDIÉES par "
                "méthode (voir sa docstring pour le détail par méthode) plutôt que de regrouper aveuglément "
                "les 5 zones affichées : le mapping Z1+Z2/Z3/Z4+Z5 n'est physiologiquement correct QUE pour "
                "Karvonen (Karvonen, Kentala & Mustala 1957 pour la réserve elle-même) ; pour LTHR, Z4 "
                "(95-99 % LTHR) reste sous le second seuil Seiler (donc « modérée », pas « difficile ») ; pour "
                "%FCmax, les seuils (82 %/87 %) sont une APPROXIMATION MAISON de l'emplacement typique de "
                "VT1/VT2 en %FCmax, SANS source vérifiée (pas une valeur tirée telle quelle de la "
                "littérature) — indépendants des bornes de zones affichées (60/70/80/90 %). Calculée "
                "UNIQUEMENT sur les activités qui ont des "
                "échantillons FIT ingérés (`hr_polarisation_time` non vide) ; une semaine sans AUCUNE activité "
                "avec échantillons rend `None` sur tous ses champs (jamais 0 % ni une part calculée sur zéro "
                "seconde) — une semaine avec au moins une activité datée sans FIT associé n'est pas `None` "
                "pour autant, cette activité est simplement absente de la somme.",
}

# ---------------------------------------------------------------------------
# Charge
# ---------------------------------------------------------------------------


def hr_reserve_fraction(avg_hr, hr_rest, hr_max) -> Optional[float]:
    if not avg_hr or not hr_rest or not hr_max or hr_max <= hr_rest:
        return None
    return min(1.0, max(0.0, (avg_hr - hr_rest) / (hr_max - hr_rest)))


def trimp_banister(duration_s, avg_hr, hr_rest, hr_max, sex=None) -> Optional[float]:
    fraction = hr_reserve_fraction(avg_hr, hr_rest, hr_max)
    if fraction is None or not duration_s:
        return None
    k = BANISTER_K.get(sex or "", BANISTER_K_DEFAULT)
    return (duration_s / 60.0) * fraction * 0.64 * math.exp(k * fraction)


def session_load(activity: dict, athlete: dict) -> Tuple[float, str]:
    """Charge d'une séance et sa provenance : « trimp », « srpe » ou « estimated »."""
    duration = activity.get("duration_s") or 0
    if activity.get("sport") == "rest" or not duration:
        return 0.0, "none"
    trimp = trimp_banister(
        duration, activity.get("avg_hr_bpm"),
        athlete.get("hr_rest_bpm"), athlete.get("hr_max_bpm"), athlete.get("sex"),
    )
    if trimp is not None:
        return trimp, "trimp"
    rpe = activity.get("rpe")
    source = "srpe"
    if rpe is None:
        rpe = DEFAULT_RPE.get(activity.get("sport"), DEFAULT_RPE_OTHER)
        source = "estimated"
    return (duration / 60.0) * rpe * RPE_TO_TRIMP, source


# ---------------------------------------------------------------------------
# Zones FC, temps en zone, polarisation 80/20 (#43)
# ---------------------------------------------------------------------------


def _normalise_hr_zone_method(method: Optional[str]) -> Optional[str]:
    """`None`/`"auto"` restent tels quels ; toute chaîne est ramenée en minuscules et
    sans espaces (`"LTHR"`, `" Lthr "` -> `"lthr"`) : un override de config ne doit pas
    échouer silencieusement sur une simple différence de casse. Une valeur qui reste
    hors de `HR_ZONE_METHODS ∪ {HR_ZONE_METHOD_DEFAULT}` après normalisation est
    renvoyée telle quelle (chaîne inconnue) : c'est `hr_zone_resolution` qui la
    transforme en raison lisible ; `arc_index.py::_hr_zone_method` filtre déjà ce cas
    en amont pour la configuration réelle, cette fonction reste défensive pour tout
    appelant direct (tests, CLI)."""
    if not isinstance(method, str):
        return method
    normalised = method.strip().lower()
    return normalised or None


def hr_zone_bounds(athlete: dict, method: Optional[str] = None) -> Optional[Tuple[Tuple[float, ...], str]]:
    """Bornes de zones FC (bpm, 6 valeurs pour 5 zones) et méthode effectivement utilisée.

    `method` : override explicite (`"lthr"` | `"karvonen"` | `"percent_max"`,
    insensible à la casse/aux espaces — voir `_normalise_hr_zone_method`) — une
    valeur inconnue, ou dont les champs manquent au profil, rend `None` (jamais de
    repli silencieux sur une autre méthode que celle demandée). `None` ou `"auto"`
    (défaut, voir `HR_ZONE_METHOD_DEFAULT`) applique la précédence documentée dans
    `ASSUMPTIONS["hr_zones"]` : LTHR -> Karvonen -> %FCmax -> `None` si même la FC max
    manque. Rend `None` quand aucune méthode n'est calculable — jamais des bornes
    inventées. Voir `hr_zone_resolution` pour une variante qui explique POURQUOI."""
    method = _normalise_hr_zone_method(method)
    hr_max = athlete.get("hr_max_bpm")
    hr_rest = athlete.get("hr_rest_bpm")
    lthr = athlete.get("hr_threshold_bpm")

    def _lthr() -> Optional[Tuple[float, ...]]:
        return tuple(round(lthr * p, 1) for p in HR_ZONE_LTHR_PCT) if lthr else None

    def _karvonen() -> Optional[Tuple[float, ...]]:
        if not hr_rest or not hr_max or hr_max <= hr_rest:
            return None
        reserve = hr_max - hr_rest
        return tuple(round(hr_rest + p * reserve, 1) for p in HR_ZONE_KARVONEN_HRR_PCT)

    def _percent_max() -> Optional[Tuple[float, ...]]:
        return tuple(round(hr_max * p, 1) for p in HR_ZONE_PCT_MAX) if hr_max else None

    resolvers = {"lthr": _lthr, "karvonen": _karvonen, "percent_max": _percent_max}
    if method and method != HR_ZONE_METHOD_DEFAULT:
        resolver = resolvers.get(method)
        if resolver is None:
            return None
        bounds = resolver()
        return (bounds, method) if bounds else None
    for name in ("lthr", "karvonen", "percent_max"):
        bounds = resolvers[name]()
        if bounds:
            return bounds, name
    return None


_HR_ZONE_MISSING_FIELDS = {
    "lthr": "la FC au seuil, à renseigner dans le profil",
    "karvonen": "la FC max et la FC de repos, à renseigner dans le profil",
    "percent_max": "la FC max, à renseigner dans le profil",
}


def hr_zone_resolution(athlete: dict, method: Optional[str] = None) -> dict:
    """Comme `hr_zone_bounds`, mais rend TOUJOURS un dict avec une raison explicite
    quand aucune zone n'est calculable — pour l'API et la CLI, qui doivent dire
    POURQUOI (méthode inconnue, méthode forcée mais champ manquant au profil, ou même
    la FC max manque) plutôt que de masquer silencieusement la section (voir revue de
    code #43, point 4).

    Rend `{"bounds_bpm": [...], "method": <méthode utilisée>, "reason": None}` en cas
    de succès, ou `{"bounds_bpm": None, "method": <méthode demandée ou None>,
    "reason": <texte>}` sinon — jamais d'exception."""
    normalised = _normalise_hr_zone_method(method)
    requested = normalised or HR_ZONE_METHOD_DEFAULT
    known = (HR_ZONE_METHOD_DEFAULT,) + HR_ZONE_METHODS
    if requested not in known:
        return {"bounds_bpm": None, "method": requested,
                "reason": f"méthode « {requested} » inconnue (attendu : {', '.join(known)})"}
    resolved = hr_zone_bounds(athlete, requested)
    if resolved:
        bounds, used = resolved
        return {"bounds_bpm": list(bounds), "method": used, "reason": None}
    if requested == HR_ZONE_METHOD_DEFAULT:
        return {"bounds_bpm": None, "method": None,
                "reason": "aucune méthode de zones calculable (profil sans FC max/repos/seuil renseignée)"}
    return {"bounds_bpm": None, "method": requested,
            "reason": f"méthode « {requested} » forcée par le réglage de zones FC de la configuration, mais "
                      f"{_HR_ZONE_MISSING_FIELDS[requested]}"}


def hr_zone_of(hr_bpm: float, bounds: Sequence[float]) -> int:
    """Numéro de zone (1..len(bounds)-1) contenant `hr_bpm` ; sature aux bornes —
    même convention que `tests/lib/synthetic.py::_zone_of_bpm`."""
    zones = len(bounds) - 1
    for z in range(1, zones + 1):
        if hr_bpm < bounds[z] or z == zones:
            return z
    return zones


def _time_weighted_buckets(samples: Sequence[dict], resolution_s: float,
                            bucket_of) -> Dict[Any, float]:
    """Partage commun à `time_in_zone_seconds` et `time_in_polarisation_seconds` :
    trie par `t_s`, ignore `hr_bpm` absent, pèse chaque échantillon par
    `min(dt_vers_le_suivant, resolution_s)` (jamais `dt` brut — voir
    `ASSUMPTIONS["hr_zones"]` pour pourquoi), et accumule dans le seau que rend
    `bucket_of(hr_bpm)`."""
    ordered = sorted((s for s in samples if s.get("t_s") is not None), key=lambda s: s["t_s"])
    seconds: Dict[Any, float] = {}
    n = len(ordered)
    for i, sample in enumerate(ordered):
        hr = sample.get("hr_bpm")
        if hr is None:
            continue
        dt = ordered[i + 1]["t_s"] - sample["t_s"] if i + 1 < n else resolution_s
        dt = max(0.0, min(dt, resolution_s))
        bucket = bucket_of(hr)
        seconds[bucket] = seconds.get(bucket, 0.0) + dt
    return seconds


def time_in_zone_seconds(samples: Sequence[dict], bounds: Sequence[float],
                          resolution_s: float) -> Dict[int, float]:
    """Temps en zone (secondes) par numéro de zone, depuis des échantillons
    sous-échantillonnés (`arc_index.samples`/`samples_by_garmin_id`, format
    `{t_s, hr_bpm, ...}`, triés ou non).

    Voir `ASSUMPTIONS["hr_zones"]` pour la méthode complète : chaque échantillon pèse
    `min(dt_vers_le_suivant, resolution_s)` — jamais `dt` brut, pour qu'une pause ou un
    trou de signal (`dt` peut dépasser `resolution_s`, voir `arc_samples.ASSUMPTIONS
    ["gaps"]`) ne soit jamais compté comme du temps en zone. Le dernier échantillon
    (pas de suivant) compte pour `resolution_s`. `hr_bpm` absent : échantillon ignoré."""
    return _time_weighted_buckets(samples, resolution_s, lambda hr: hr_zone_of(hr, bounds))


def seiler_bounds(athlete: dict, method: str) -> Optional[Tuple[float, float]]:
    """Bornes bpm (facile/modérée, modérée/difficile) du modèle 3 zones de Seiler,
    DÉDIÉES à `method` — jamais un simple regroupement des 5 zones affichées (voir
    `ASSUMPTIONS["hr_zones"]` pour la justification complète et les sources) :

    - `"karvonen"` : seuils à 70 %/80 % de la réserve FC — MÊMES valeurs que nos
      bornes de zones 3/4 (`HR_ZONE_KARVONEN_HRR_PCT[2]`/`[3]`), donc équivalent au
      regroupement Z1+Z2 facile / Z3 modérée / Z4+Z5 difficile.
    - `"lthr"` : seuils à 90 %/100 % de la LTHR — PAS aux bornes 2/3 et 4/5 de nos
      zones affichées telles quelles regroupées zone par zone : Z4 (95-99 % LTHR)
      reste sous le second seuil, donc « modérée ».
    - `"percent_max"` : seuils à `HR_ZONE_SEILER_PCT_MAX` (82 %/87 % de la FC max),
      INDÉPENDANTS des bornes de zones affichées (60/70/80/90 %).

    Rend `None` si les champs requis par `method` manquent au profil, ou si `method`
    n'est ni `"karvonen"`, ni `"lthr"`, ni `"percent_max"` (`"auto"` n'a pas de sens
    ici : appeler avec la méthode déjà résolue par `hr_zone_bounds`/`hr_zone_resolution`)."""
    method = _normalise_hr_zone_method(method)
    hr_max = athlete.get("hr_max_bpm")
    hr_rest = athlete.get("hr_rest_bpm")
    lthr = athlete.get("hr_threshold_bpm")
    if method == "karvonen":
        if not hr_rest or not hr_max or hr_max <= hr_rest:
            return None
        reserve = hr_max - hr_rest
        return (hr_rest + HR_ZONE_KARVONEN_HRR_PCT[2] * reserve, hr_rest + HR_ZONE_KARVONEN_HRR_PCT[3] * reserve)
    if method == "lthr":
        return (lthr * 0.90, lthr * 1.00) if lthr else None
    if method == "percent_max":
        return (hr_max * HR_ZONE_SEILER_PCT_MAX[0], hr_max * HR_ZONE_SEILER_PCT_MAX[1]) if hr_max else None
    return None


def _seiler_bucket(hr_bpm: float, thresholds: Tuple[float, float]) -> str:
    low_high, moderate_high = thresholds
    if hr_bpm < low_high:
        return "low"
    if hr_bpm < moderate_high:
        return "moderate"
    return "high"


def time_in_polarisation_seconds(samples: Sequence[dict], thresholds: Tuple[float, float],
                                  resolution_s: float) -> Dict[str, float]:
    """Temps (secondes) par seau Seiler (`"low"`/`"moderate"`/`"high"`), depuis des
    échantillons sous-échantillonnés et les bornes bpm dédiées rendues par
    `seiler_bounds` — même méthode de pondération que `time_in_zone_seconds` (voir sa
    docstring et `ASSUMPTIONS["hr_zones"]`), mais sur un DÉCOUPAGE bpm différent :
    jamais dérivé de `time_in_zone_seconds` en regroupant des numéros de zone."""
    return _time_weighted_buckets(samples, resolution_s, lambda hr: _seiler_bucket(hr, thresholds))


def polarisation_shares(bucket_seconds: Dict[str, float]) -> Optional[dict]:
    """Répartition Seiler à 3 zones (facile/modérée/difficile) depuis un temps par
    seau `{"low"|"moderate"|"high": secondes}` (voir `time_in_polarisation_seconds`).
    `None` si `bucket_seconds` est vide ou de somme nulle (rien à répartir) — jamais
    0 % partout, qui laisserait croire à une mesure réelle. Voir `ASSUMPTIONS["hr_zones"]`
    pour le caractère approximatif de ce modèle."""
    total = sum(bucket_seconds.values())
    if not total:
        return None
    low = bucket_seconds.get("low", 0.0)
    moderate = bucket_seconds.get("moderate", 0.0)
    high = bucket_seconds.get("high", 0.0)
    return {
        "total_s": total, "low_s": low, "moderate_s": moderate, "high_s": high,
        "low_pct": round(low / total * 100, 1),
        "moderate_pct": round(moderate / total * 100, 1),
        "high_pct": round(high / total * 100, 1),
    }


# ---------------------------------------------------------------------------
# Forme : condition / fatigue / forme / ACWR, monotonie / strain
# ---------------------------------------------------------------------------


def _daterange(start: date, end: date) -> Iterable[date]:
    day = start
    while day <= end:
        yield day
        day += timedelta(days=1)


def daily_series(loads_by_date: Dict[str, float], start: date, end: date) -> List[dict]:
    """Série quotidienne de start à end inclus (jours sans séance = charge 0)."""
    a_fit = 1 - math.exp(-1 / FITNESS_DAYS)
    a_fat = 1 - math.exp(-1 / FATIGUE_DAYS)
    fitness = fatigue = 0.0
    window: List[float] = []
    out = []
    for day in _daterange(start, end):
        load = loads_by_date.get(day.isoformat(), 0.0)
        form = fitness - fatigue                     # forme en entrant dans la journée
        fitness += (load - fitness) * a_fit
        fatigue += (load - fatigue) * a_fat
        window = (window + [load])[-7:]
        monotony = strain = None
        if len(window) == 7:
            mean = sum(window) / 7
            sd = math.sqrt(sum((x - mean) ** 2 for x in window) / 7)
            if sd > 0:
                monotony = mean / sd
                strain = sum(window) * monotony
        out.append({
            "date": day.isoformat(),
            "load": round(load, 2),
            "fitness": round(fitness, 2),
            "fatigue": round(fatigue, 2),
            "form": round(form, 2),
            "acwr": round(fatigue / fitness, 3) if fitness >= ACWR_MIN_FITNESS else None,
            "monotony": round(monotony, 3) if monotony is not None else None,
            "strain": round(strain, 1) if strain is not None else None,
        })
    return out


# ---------------------------------------------------------------------------
# Ligne de base HRV personnelle
# ---------------------------------------------------------------------------


def _window_values(by_date: Dict[str, float], day: date, days: int, end_offset: int = 0) -> List[float]:
    """Valeurs présentes et strictement positives (`ln` exige > 0) sur les `days` jours
    se terminant à `day - end_offset` inclus.

    Un jour absent de `by_date` n'est pas une mesure à 0 : il est simplement ignoré, la
    fenêtre glissante en compte alors moins que `days`. `end_offset` décale la fin de la
    fenêtre dans le passé — sert à rendre la fenêtre de référence NON chevauchante avec
    la fenêtre courte (voir `hrv_baseline_series`).
    """
    values = []
    last = day - timedelta(days=end_offset)
    for k in range(days):
        v = by_date.get((last - timedelta(days=k)).isoformat())
        if v is not None and v > 0:
            values.append(v)
    return values


def _mean(values: List[float]) -> float:
    return sum(values) / len(values)


def _population_sd(values: List[float], mean: float) -> float:
    return math.sqrt(sum((x - mean) ** 2 for x in values) / len(values))


def hrv_baseline_series(hrv_by_date: Dict[str, float], start: date, end: date) -> List[dict]:
    """Ligne de base HRV personnelle, jour par jour, de `start` à `end` inclus.

    `hrv_by_date` : `hrv_overnight_ms` brut (millisecondes) par date ISO, jours
    manquants absents du dict (jamais 0). Voir `ASSUMPTIONS["hrv_baseline"]` pour
    la méthode complète et ses sources.

    Chaque point rend :
    - `hrv_ln_mean7` : moyenne glissante 7 j de ln(HRV), `None` sous le seuil de jours valides.
    - `hrv_personal_mean7_ms` : la même moyenne, reconvertie en millisecondes (`exp`), pour
      tracer une courbe directement comparable à `hrv_overnight_ms` (moyenne lissée, pas la
      valeur brute de la nuit).
    - `hrv_cv7_pct` : coefficient de variation 7 j calculé sur ln(HRV) (%), même seuil —
      pas sur les valeurs brutes (Plews et al. 2012, voir `ASSUMPTIONS`).
    - `hrv_personal_low_ms` / `hrv_personal_high_ms` : bande de référence 60 j ± 0,5 ET,
      reconvertie en millisecondes (`exp`) pour rester comparable à la bande Garmin. La
      référence se termine `HRV_LN_WINDOW_DAYS` jours avant `day` : elle ne recouvre jamais
      la fenêtre courte (sinon la moyenne se dilue dans sa propre référence).
    - `hrv_personal_status` : `"sous"`, `"dans_la_norme"`, `"au_dessus"`, `"en_construction"`
      (moyenne 7 j disponible mais référence 60 j encore trop courte), ou `None`
      (pas même de moyenne 7 j).
    """
    out = []
    for day in _daterange(start, end):
        short = _window_values(hrv_by_date, day, HRV_LN_WINDOW_DAYS)
        ref = _window_values(hrv_by_date, day, HRV_REF_WINDOW_DAYS, end_offset=HRV_LN_WINDOW_DAYS)
        point = {
            "date": day.isoformat(),
            "hrv_ln_mean7": None,
            "hrv_personal_mean7_ms": None,
            "hrv_cv7_pct": None,
            "hrv_personal_low_ms": None,
            "hrv_personal_high_ms": None,
            "hrv_personal_status": None,
        }
        if len(short) < HRV_LN_MIN_VALID_DAYS:
            out.append(point)
            continue
        ln_short = [math.log(v) for v in short]
        mean7 = _mean(ln_short)
        point["hrv_ln_mean7"] = round(mean7, 4)
        point["hrv_personal_mean7_ms"] = round(math.exp(mean7), 1)
        point["hrv_cv7_pct"] = round(100 * _population_sd(ln_short, mean7) / mean7, 1)
        if len(ref) >= HRV_REF_MIN_VALID_DAYS:
            ln_ref = [math.log(v) for v in ref]
            ref_mean = _mean(ln_ref)
            ref_sd = _population_sd(ln_ref, ref_mean)
            low, high = ref_mean - HRV_BAND_SD_MULT * ref_sd, ref_mean + HRV_BAND_SD_MULT * ref_sd
            point["hrv_personal_low_ms"] = round(math.exp(low), 1)
            point["hrv_personal_high_ms"] = round(math.exp(high), 1)
            # Comparaison sur la moyenne NON arrondie : `hrv_ln_mean7` (arrondi à 4
            # décimales pour l'affichage) pourrait sinon basculer un cas pile à la
            # frontière (écart-type nul, par exemple) du mauvais côté du seuil.
            point["hrv_personal_status"] = "sous" if mean7 < low else "au_dessus" if mean7 > high else "dans_la_norme"
        else:
            point["hrv_personal_status"] = "en_construction"
        out.append(point)
    return out


# ---------------------------------------------------------------------------
# Tendance du poids (#36)
# ---------------------------------------------------------------------------


def merge_weight_kg(health_weight_kg: Optional[float], nutrition_weight_kg: Optional[float]) -> Optional[float]:
    """Poids fusionné pour un jour donné. Voir `ASSUMPTIONS["weight_merge"]`.

    `health_weight_kg` (mesure du matin, bilan santé) gagne TOUJOURS sur
    `nutrition_weight_kg` quand les deux sont présents — jamais de moyenne des deux.
    Absence des deux : `None`, jamais 0.
    """
    return health_weight_kg if health_weight_kg is not None else nutrition_weight_kg


def weight_avg7_series(weight_by_date: Dict[str, float], start: date, end: date) -> List[dict]:
    """Poids fusionné et moyenne mobile 7 j, jour par jour de `start` à `end` inclus.

    `weight_by_date` : poids déjà fusionné (`merge_weight_kg`) par date ISO, jours sans
    mesure absents du dict (jamais 0). Voir `ASSUMPTIONS["weight_trend"]`.

    Chaque point rend `weight_kg` (valeur fusionnée du jour, `None` si aucune mesure) et
    `weight_avg7_kg` (moyenne des valeurs présentes sur les `WEIGHT_AVG_WINDOW_DAYS`
    derniers jours, `None` sous `WEIGHT_AVG_MIN_VALID_DAYS` valeurs).
    """
    out = []
    for day in _daterange(start, end):
        window = _window_values(weight_by_date, day, WEIGHT_AVG_WINDOW_DAYS)
        avg7 = round(_mean(window), 1) if len(window) >= WEIGHT_AVG_MIN_VALID_DAYS else None
        out.append({
            "date": day.isoformat(),
            "weight_kg": weight_by_date.get(day.isoformat()),
            "weight_avg7_kg": avg7,
        })
    return out


def weight_slope_kg_per_week(weight_by_date: Dict[str, float], day: date,
                              window_days: int = WEIGHT_SLOPE_WINDOW_DAYS,
                              min_points: int = WEIGHT_SLOPE_MIN_POINTS,
                              min_span_days: int = WEIGHT_SLOPE_MIN_SPAN_DAYS) -> Optional[float]:
    """Pente du poids (kg/semaine) sur les `window_days` jours se terminant à `day` inclus.

    Régression des moindres carrés sur les valeurs quotidiennes FUSIONNÉES et PRÉSENTES
    (jamais la moyenne mobile lissée) : x = décalage en jours depuis le début de la
    fenêtre, y = poids. `None` sous `min_points` jours mesurés dans la fenêtre, ou si
    l'écart entre la première et la dernière pesée disponible est sous `min_span_days` —
    quelques pesées groupées sur deux ou trois jours ne donnent pas une pente fiable sur
    4 semaines, même avec assez de points bruts.
    """
    points = []
    start = day - timedelta(days=window_days - 1)
    for offset in range(window_days):
        v = weight_by_date.get((start + timedelta(days=offset)).isoformat())
        if v is not None:
            points.append((offset, v))
    if len(points) < min_points:
        return None
    if points[-1][0] - points[0][0] < min_span_days:
        return None
    n = len(points)
    mean_x = sum(p[0] for p in points) / n
    mean_y = sum(p[1] for p in points) / n
    den = sum((x - mean_x) ** 2 for x, _ in points)
    if den == 0:
        return None
    num = sum((x - mean_x) * (y - mean_y) for x, y in points)
    return round((num / den) * 7, 3)


def weight_target_gap_kg(weight_avg7_kg: Optional[float], target_weight_kg: Optional[float]) -> Optional[float]:
    """Écart (kg) entre la moyenne 7 j du poids et la cible. Positif = au-dessus de la cible."""
    if weight_avg7_kg is None or target_weight_kg is None:
        return None
    return round(weight_avg7_kg - target_weight_kg, 1)


# ---------------------------------------------------------------------------
# Dette de sommeil 7 j (#37)
# ---------------------------------------------------------------------------


def sleep_debt_7d(sleep_by_date: Dict[str, float], day: date, need_s: float = SLEEP_NEED_DEFAULT_S,
                   window_days: int = SLEEP_DEBT_WINDOW_DAYS,
                   min_nights: int = SLEEP_DEBT_MIN_NIGHTS) -> dict:
    """Dette de sommeil sur les `window_days` nuits se terminant à `day` inclus.

    `sleep_by_date` : `sleep_total_s` par date ISO, nuits sans mesure absentes du
    dict (jamais 0). Voir `ASSUMPTIONS["sleep_debt"]` pour la méthode complète et
    le choix documenté sur les nuits excédentaires.

    Rend toujours `nights_counted` (nombre de nuits mesurées dans la fenêtre,
    même sous le seuil) et `sleep_need_s` (le besoin effectivement utilisé).
    `sleep_debt_7d_s` est `None` sous `min_nights` nuits mesurées.
    """
    values = _window_values(sleep_by_date, day, window_days)
    nights_counted = len(values)
    debt = None
    if nights_counted >= min_nights:
        debt = round(sum(max(0.0, need_s - v) for v in values))
    return {"sleep_debt_7d_s": debt, "nights_counted": nights_counted, "sleep_need_s": need_s}


def sleep_debt_series(sleep_by_date: Dict[str, float], start: date, end: date,
                       need_s: float = SLEEP_NEED_DEFAULT_S) -> List[dict]:
    """Dette de sommeil 7 j, jour par jour, de `start` à `end` inclus. Voir `sleep_debt_7d`."""
    return [{"date": day.isoformat(), **sleep_debt_7d(sleep_by_date, day, need_s)}
            for day in _daterange(start, end)]


# ---------------------------------------------------------------------------
# VO2max effective, prédictions
# ---------------------------------------------------------------------------


def vo2_of_speed(meters_per_min: float) -> float:
    """Coût en O2 (ml/kg/min) d'une allure (Daniels & Gilbert)."""
    v = meters_per_min
    return -4.60 + 0.182258 * v + 0.000104 * v * v


def vo2max_fraction_of_duration(minutes: float) -> float:
    """Fraction de VO2max soutenable pendant `minutes` (Daniels & Gilbert)."""
    t = minutes
    return 0.8 + 0.1894393 * math.exp(-0.012778 * t) + 0.2989558 * math.exp(-0.1932605 * t)


def vdot(distance_m: float, time_s: float) -> Optional[float]:
    """VDOT d'une performance maximale (distance, temps)."""
    if distance_m <= 0 or time_s <= 0:
        return None
    minutes = time_s / 60
    return vo2_of_speed(distance_m / minutes) / vo2max_fraction_of_duration(minutes)


def effort_distance_m(activity: dict) -> Optional[float]:
    distance = activity.get("distance_m")
    if not distance:
        return None
    if activity.get("sport") == "trail":
        return distance + (activity.get("elevation_gain_m") or 0) * TRAIL_FLAT_M_PER_M_DPLUS
    return float(distance)


def effort_km_itra_raw(activity: dict) -> Optional[float]:
    """Unrounded ITRA km-effort (distance_km + elevation_gain_m / 100), for run-like sports.

    None if distance is missing (activity doesn't count) or the sport isn't in the "run"
    family (`SPORT_FAMILY`): running, trail, hiking, walking. Unrounded, so callers summing
    several activities (e.g. a weekly total) should round only once, after summing — never
    sum values already rounded per activity.
    """
    distance_m = activity.get("distance_m")
    if not distance_m or sport_family(activity.get("sport")) != "run":
        return None
    elevation_gain_m = activity.get("elevation_gain_m") or 0
    return distance_m / 1000 + elevation_gain_m / 100


def effort_km_itra(activity: dict) -> Optional[float]:
    """ITRA km-effort (km) for a single activity, rounded to 1 decimal. See `effort_km_itra_raw`."""
    raw = effort_km_itra_raw(activity)
    return None if raw is None else round(raw, 1)


def effort_km_week_total(activities: list) -> float:
    """Sum of ITRA km-effort over a set of activities (e.g. one week), rounded once.

    Non-run-like activities and activities missing a distance contribute nothing. Summing
    the unrounded per-activity values first, then rounding once, avoids drifting from the
    true weekly total (as summing values already rounded per activity would).
    """
    total = sum(v for v in (effort_km_itra_raw(a) for a in activities) if v is not None)
    return round(total, 1)


def vo2max_effective(activity: dict, athlete: dict) -> Optional[float]:
    """Estimation par séance. None si les données ne suffisent pas ou si l'estimation est aberrante."""
    if activity.get("sport") not in RUNNING_SPORTS:
        return None
    duration, avg_hr, hr_max = activity.get("duration_s"), activity.get("avg_hr_bpm"), athlete.get("hr_max_bpm")
    distance = effort_distance_m(activity)
    if not distance or not duration or not VO2MAX_MIN_DURATION_S <= duration <= VO2MAX_MAX_DURATION_S or not avg_hr or not hr_max:
        return None
    moving = activity.get("moving_duration_s") or duration
    if moving / (distance / 1000) > VO2MAX_MAX_PACE_S_PER_KM or avg_hr / hr_max < VO2MAX_MIN_HR_FRACTION:
        return None
    fraction = (avg_hr / hr_max - 0.37) / 0.64
    if fraction <= 0.3:
        return None
    estimate = vo2_of_speed(distance / (moving / 60)) / min(fraction, 1.0)
    lo, hi = VO2MAX_PLAUSIBLE
    return round(estimate, 2) if lo <= estimate <= hi else None


def vo2max_trend(estimates: List[Tuple[str, float, float]], day: str, days: int = VO2MAX_TREND_DAYS) -> Optional[float]:
    """Moyenne des estimations des `days` derniers jours, pondérée par la durée.

    `estimates` : liste de (date ISO, estimation, durée en s).
    """
    end = date.fromisoformat(day)
    start = end - timedelta(days=days - 1)
    weight = total = 0.0
    for when, value, duration in estimates:
        d = date.fromisoformat(when)
        if start <= d <= end:
            w = min(duration, VO2MAX_MAX_WEIGHT_S)
            total += value * w
            weight += w
    return round(total / weight, 2) if weight else None


def sweat_rate_l_h(activity: dict) -> Optional[float]:
    """Taux de sudation d'une séance (#39). `None` si pesées ou durée manquent, si la
    séance est trop courte pour que la pesée soit fiable, si le résultat est négatif
    ou hors plage plausible. Voir `ASSUMPTIONS["sweat_rate"]`."""
    pre, post = activity.get("weight_pre_kg"), activity.get("weight_post_kg")
    duration = activity.get("duration_s")   # durée TOTALE : la pesée encadre la sortie entière, pas le seul mouvement
    if pre is None or post is None or not duration or duration < SWEAT_RATE_MIN_DURATION_S:
        return None
    fluid_l = (activity.get("fluid_intake_ml") or 0) / 1000.0
    hours = duration / 3600.0
    rate = ((pre - post) + fluid_l) / hours
    lo, hi = SWEAT_RATE_PLAUSIBLE_L_H
    return round(rate, 2) if lo <= rate <= hi else None


def carbs_per_hour_g(activity: dict) -> Optional[float]:
    """Glucides ingérés par heure d'effort (#41), entraînement digestif. `None` si la
    séance n'est pas une sortie longue (`duration_s` ≤ `LONG_RUN_MIN_DURATION_S`, borne
    STRICTE) ou si `carbs_g` n'est pas renseigné — jamais 0 par défaut : un `carbs_g`
    explicitement à 0 reste un 0 g/h légitime. Voir `ASSUMPTIONS["fueling"]`."""
    duration = activity.get("duration_s")
    if not duration or duration <= LONG_RUN_MIN_DURATION_S:
        return None
    carbs = activity.get("carbs_g")
    if carbs is None:
        return None
    return round(carbs / (duration / 3600.0), 1)


def fueling_trend(activities: List[dict], day: date, window_weeks: int = FUELING_TREND_WEEKS) -> dict:
    """Tendance glucides/h et taux de sudation sur les sorties longues (#41), fenêtre
    de `window_weeks` semaines glissantes se terminant à `day` inclus. Voir
    `ASSUMPTIONS["fueling"]` pour la méthode complète.

    `activities` : dicts portant au moins `date` (AAAA-MM-JJ), `duration_s` et `sport` ;
    `carbs_g` et `sweat_rate_l_h` (déjà dérivé à l'indexation, JAMAIS recalculé ici)
    optionnels. Seules les activités de `FUELING_SPORTS` (running, trail — jamais le
    vélo ni la randonnée, voir la constante) avec `duration_s` > `LONG_RUN_MIN_DURATION_S`
    sont considérées (les deux filtres sont appliqués ici, que l'appelant ait ou non déjà
    pré-filtré sa requête — revue de code #41, blocker : sans le filtre sport, un long
    vélo à haut débit pouvait plafonner un objectif de COURSE À PIED). Fenêtre INCLUSIVE
    des deux côtés, `window_weeks * 7` jours au total (aujourd'hui et le jour
    `window_weeks` semaines avant tous les deux comptés) — même convention que
    `HEAT_WINDOW_DAYS` ci-dessus (`start = day - timedelta(days=N-1)`).
    """
    start = day - timedelta(days=window_weeks * 7 - 1)
    points = []
    for act in activities:
        iso = act.get("date")
        duration = act.get("duration_s")
        if not iso or not duration or duration <= LONG_RUN_MIN_DURATION_S:
            continue
        if act.get("sport") not in FUELING_SPORTS:
            continue
        try:
            act_date = date.fromisoformat(iso)
        except ValueError:
            continue
        if not (start <= act_date <= day):
            continue
        points.append({
            "date": iso,
            "sport": act.get("sport"),
            "distance_m": act.get("distance_m"),
            "duration_s": duration,
            "carbs_per_hour_g": carbs_per_hour_g(act),
            "sweat_rate_l_h": act.get("sweat_rate_l_h"),
        })
    points.sort(key=lambda p: p["date"])
    carbs_values = [p["carbs_per_hour_g"] for p in points if p["carbs_per_hour_g"] is not None]
    sweat_values = [p["sweat_rate_l_h"] for p in points if p["sweat_rate_l_h"] is not None]
    return {
        "points": points,
        "window_weeks": window_weeks,
        "long_runs": len(points),
        "max_carbs_per_hour_g": max(carbs_values) if carbs_values else None,
        "carbs_per_hour_n": len(carbs_values),
        "median_sweat_rate_l_h": round(statistics.median(sweat_values), 2) if sweat_values else None,
        "sweat_rate_n": len(sweat_values),
    }


def fueling_carbs_ceiling(max_observed_g_h: Optional[float],
                           margin_g_h: float = FUELING_MAX_MARGIN_G_H,
                           target_band_g_h: Tuple[float, float] = FUELING_TARGET_BAND_G_H) -> Optional[float]:
    """Plafond réaliste de glucides/h pour un plan de course (#41) : meilleur débit
    réellement observé à l'entraînement + marge de progression documentée
    (`ASSUMPTIONS["fueling"]`) — PAS une limite physiologique dure. `None` si aucune
    sortie longue chiffrée n'est disponible : le stratège garde alors le repère
    générique `FUELING_TARGET_BAND_G_H` et doit suggérer un entraînement digestif
    progressif plutôt que d'inventer un plafond.

    Borné au-dessus par `max(target_band_g_h[1], max_observed_g_h)` (revue de code #41,
    SHOULD-FIX 3) : le plafond ne dépasse JAMAIS le haut du repère généraliste
    (90 g/h) sauf si l'athlète a DÉJÀ personnellement démontré un débit supérieur —
    auquel cas aucune marge supplémentaire n'est ajoutée au-delà de ce qu'il a
    prouvé (le plafond devient alors exactement `max_observed_g_h`, jamais
    `max_observed_g_h + margin_g_h`). Sans cette borne, un athlète déjà à 50 g/h
    recevrait un plafond à 60 (cohérent), mais un athlète à 85 g/h recevrait un
    plafond à 95 g/h — au-dessus du haut de la fourchette généraliste sans qu'un
    dixième gramme au-delà de 90 n'ait jamais été démontré.

    Arrondi par EXCÈS (`math.ceil`), jamais `round` (revue de code #41, nit) : un
    plafond est une borne HAUTE — `round` peut arrondir PAR DÉFAUT (98,2 → 98), ce
    qui rendrait le plafond inférieur au débit RÉELLEMENT observé, un non-sens pour
    une valeur censée le couvrir."""
    if max_observed_g_h is None:
        return None
    return math.ceil(min(max_observed_g_h + margin_g_h, max(target_band_g_h[1], max_observed_g_h)))


# Fenêtre de la tendance de découplage (#45) : 12 semaines glissantes, comme demandé
# par le critère d'acceptation de l'issue — assez large pour dégager une tendance de
# fond sur les sorties longues sans remonter à un bloc d'entraînement complètement
# différent.
DECOUPLING_TREND_WEEKS = 12


def decoupling_trend(activities: List[dict], day: date, window_weeks: int = DECOUPLING_TREND_WEEKS) -> dict:
    """Tendance du découplage aérobie (Pa:HR, #45) sur les sorties longues, fenêtre de
    `window_weeks` semaines glissantes se terminant à `day` inclus — même discipline
    que `fueling_trend` (#41) : les DEUX filtres (famille course à pied, durée >
    `LONG_RUN_MIN_DURATION_S`) sont appliqués ici, que l'appelant ait ou non déjà
    pré-filtré sa requête.

    `activities` : dicts portant au moins `date` (AAAA-MM-JJ), `duration_s` et
    `sport` ; `decoupling_pct`/`ef_whole` (déjà dérivés à l'indexation par
    `arc_decoupling.decoupling_report`, JAMAIS recalculés ici) optionnels — une
    sortie longue sans découplage calculable (séance non stable, échauffement trop
    long, etc.) apparaît quand même dans `points` avec `decoupling_pct: None`,
    jamais silencieusement exclue de la liste (seulement de la moyenne)."""
    start = day - timedelta(days=window_weeks * 7 - 1)
    points = []
    for act in activities:
        iso = act.get("date")
        duration = act.get("duration_s")
        if not iso or not duration or duration <= LONG_RUN_MIN_DURATION_S:
            continue
        if sport_family(act.get("sport")) != "run":
            continue
        try:
            act_date = date.fromisoformat(iso)
        except ValueError:
            continue
        if not (start <= act_date <= day):
            continue
        points.append({
            "date": iso,
            "sport": act.get("sport"),
            "name": act.get("name"),
            "duration_s": duration,
            "decoupling_pct": act.get("decoupling_pct"),
            "ef_whole": act.get("ef_whole"),
        })
    points.sort(key=lambda p: p["date"])
    measured = [p["decoupling_pct"] for p in points if p["decoupling_pct"] is not None]
    return {
        "points": points,
        "window_weeks": window_weeks,
        "long_runs": len(points),
        "measured_n": len(measured),
        "avg_decoupling_pct": round(statistics.mean(measured), 2) if measured else None,
    }


def gear_mileage(activities: List[dict], gear_defs: List[dict]) -> dict:
    """Kilométrage cumulé par chaussure (#40). Voir `ASSUMPTIONS["gear_mileage"]`
    pour la méthode complète (attribution, chaussure par défaut, `gear_id` inconnu,
    date `depuis` filtrant l'attribution PAR DÉFAUT seulement, priorité
    retraite/défaut).

    `activities` : dicts portant au moins `sport`, `distance_m` (optionnel — une
    séance sans distance ne contribue rien), `gear_id` (optionnel) et `date`
    (AAAA-MM-JJ — nécessaire pour filtrer l'attribution par défaut par `depuis`,
    voir plus bas ; son absence n'exclut jamais une activité à `gear_id` explicite).
    `gear_defs` : liste au format `arc_legacy.parse_gear` (`gear_id`, `name`,
    `start_date`, `threshold_m`, `default`, `retired`, `collision_base`).

    Rend `{"shoes": [...], "unknown": [...], "warnings": [...]}` : `shoes` couvre
    TOUTE chaussure déclarée dans le profil, y compris à 0 m (l'athlète voit sa
    liste complète), chacune avec `distance_m`, `alert` (bool) et les champs du
    profil ; `unknown` liste les `gear_id` vus sur une activité mais absents du
    profil, avec leur seul kilométrage (pas de nom, pas de seuil — rien à
    afficher de plus) ; `warnings` signale toute collision de `gear_id` dérivé
    détectée par `arc_legacy.parse_gear` (revue #85 blocker 2)."""
    by_id = {g["gear_id"]: dict(g) for g in gear_defs if g.get("gear_id")}
    default_entry = next((g for g in by_id.values() if g.get("default") and not g.get("retired")), None)
    default_id = default_entry["gear_id"] if default_entry else None
    # Revue #85 blocker 1 : une chaussure par défaut déclarée avec `depuis` ne doit
    # RÉCUPÉRER que les séances postérieures (ou égales) à cette date — sans ce
    # filtre, TOUT l'historique sans `gear_id` (y compris des années d'activités
    # d'avant #39, où `gear_id` n'existait même pas encore dans le contrat) se
    # retrouve attribué à une paire achetée hier. Seule l'attribution PAR DÉFAUT
    # est filtrée : un `gear_id` EXPLICITE sur l'activité n'est jamais remis en
    # cause par la date (voir ASSUMPTIONS["gear_mileage"]).
    default_start = default_entry.get("start_date") if default_entry else None

    totals: Dict[str, float] = {}
    for act in activities:
        if act.get("sport") not in GEAR_WEAR_SPORTS:
            continue
        distance = act.get("distance_m")
        if not distance:
            continue
        gear_id = act.get("gear_id")
        if not gear_id:
            if not default_id:
                continue
            if default_start and (not act.get("date") or act["date"] < default_start):
                continue    # séance antérieure à l'entrée en service de la chaussure par défaut
            gear_id = default_id
        totals[gear_id] = totals.get(gear_id, 0.0) + distance

    shoes = []
    warnings = []
    for gear_id, g in by_id.items():
        distance_m = round(totals.get(gear_id, 0.0))
        threshold_m = round(g.get("threshold_m") or GEAR_ALERT_THRESHOLD_M_DEFAULT)
        retired = bool(g.get("retired"))
        shoes.append({
            "gear_id": gear_id, "name": g.get("name") or gear_id, "distance_m": distance_m,
            "threshold_m": threshold_m, "start_date": g.get("start_date"),
            "default": bool(g.get("default")), "retired": retired,
            "alert": (not retired) and distance_m >= threshold_m,
        })
        collision_base = g.get("collision_base")
        if collision_base:
            warnings.append(
                f"« {g.get('name') or gear_id} » dérive le même identifiant (« {collision_base} ») qu'une "
                f"autre chaussure du profil — renommé « {gear_id} » automatiquement ; ajoutez un `id:` "
                "explicite sur chaque puce pour lever l'ambiguïté (même modèle racheté, deux paires distinctes).")
    unknown = [{"gear_id": gid, "distance_m": round(m)} for gid, m in totals.items() if gid not in by_id]
    shoes.sort(key=lambda s: s["name"].casefold())
    unknown.sort(key=lambda s: s["gear_id"])
    warnings.sort()
    return {"shoes": shoes, "unknown": unknown, "warnings": warnings}


def predict_time_vdot(vdot_value: float, distance_m: float) -> Optional[float]:
    """Temps (s) sur `distance_m` pour un VDOT donné : résolution par dichotomie."""
    if not vdot_value or vdot_value <= 0 or distance_m <= 0:
        return None
    lo, hi = 60.0, 60.0 * 60 * 48
    for _ in range(80):
        mid = (lo + hi) / 2
        if vdot(distance_m, mid) > vdot_value:
            lo = mid                                # trop rapide pour ce VDOT
        else:
            hi = mid
    return round((lo + hi) / 2)


def riegel(time_s: float, distance_m: float, target_m: float, exponent: float) -> float:
    return round(time_s * (target_m / distance_m) ** exponent)


# ---------------------------------------------------------------------------
# Records (fenêtres de splits)
# ---------------------------------------------------------------------------


def best_efforts(activities: List[dict]) -> Dict[int, dict]:
    """Meilleur temps sur 1/5/10/21 km consécutifs, tous splits confondus.

    Chaque activité : {"date", "sport", "distance_m"?, "splits": [{"km", "duration_s", "distance_m"?}, …]}.
    Un tour qui ne fait pas environ 1 km (distance_m hors de 900-1100 : reliquat final,
    pas de séance structurée de 500 m ou de 2 km) interrompt la fenêtre. Sans distance par split,
    le dernier est présumé partiel dès qu'il y a plus de splits que de kilomètres
    entiers (25,19 km → 26 splits : le 26ᵉ fait 190 m, pas un « record » en 0:49).
    """
    best: Dict[int, dict] = {}
    for act in activities:
        if act.get("sport") not in RUNNING_SPORTS:
            continue
        splits = sorted(act.get("splits") or [], key=lambda s: s.get("km") or 0)
        whole_km = int((act.get("distance_m") or 0) // 1000)
        if splits and whole_km and len(splits) > whole_km and splits[-1].get("distance_m") is None:
            splits = splits[:-1]
        durations = []
        for split in splits:
            partial = split.get("distance_m") is not None and not 900 <= split["distance_m"] <= 1100
            durations.append(None if partial or not split.get("duration_s") else split["duration_s"])
        for km in RECORD_DISTANCES_KM:
            for i in range(0, len(durations) - km + 1):
                window = durations[i:i + km]
                if any(d is None for d in window):
                    continue
                total = sum(window)
                if km not in best or total < best[km]["time_s"]:
                    best[km] = {"time_s": round(total), "date": act["date"], "activity_name": act.get("name")}
    return best


def predictions(vdot_value: Optional[float], records: Dict[int, dict], primary: str,
                target_m: Optional[float] = None, target_dplus_m: Optional[float] = None) -> List[dict]:
    """Tableau de prédictions : distances standard + distance cible de l'objectif."""
    exponent = RIEGEL_EXPONENT.get(primary, RIEGEL_EXPONENT["road"])
    reference = None
    for km in sorted(records, reverse=True):            # le plus long effort est le plus prédictif
        if km >= 5:
            reference = (records[km]["time_s"], km * 1000.0)
            break
    rows = []
    targets = [(d, None, None) for d in PREDICTION_DISTANCES_M]
    if target_m:
        effort = target_m
        if primary == "trail" and target_dplus_m:
            effort = target_m + target_dplus_m * TRAIL_FLAT_M_PER_M_DPLUS
        targets.append((effort, target_m, "objective"))
    for effort_m, real_m, tag in targets:
        rows.append({
            "distance_m": real_m or effort_m,
            "effort_distance_m": round(effort_m),
            "tag": tag,
            "vdot_s": predict_time_vdot(vdot_value, effort_m) if vdot_value else None,
            "riegel_s": riegel(reference[0], reference[1], effort_m, exponent) if reference else None,
        })
    return rows


# ---------------------------------------------------------------------------
# Conformité plan vs réalisé (#33)
#
# Compare les séances planifiées d'une semaine (`planning/Semaine_<lundi>.md`,
# sous-schéma `session` de scripts/arc_contract.py) aux activités effectivement
# enregistrées (`activities/*.md`). But : un chiffre de conformité par semaine,
# jamais une déduction sur des données absentes.
#
# Règles, dans l'ordre :
# - une séance de repos (`sport == "rest"` ou `intensity == "rest"`) est hors
#   sujet pour ce KPI : rien n'y est « conforme » ou « manqué ». Elle est
#   retirée de tous les calculs (dénominateur global ET répartition par
#   intensité), comptée à part dans `sessions_rest`. Sans cette exclusion, les
#   semaines lues au format hérité (`scripts/arc_legacy.py::legacy_week`, qui
#   classe toute ligne « Repos » en `sport = "rest"` sans statut) tombaient à
#   50 % de conformité alors que tout avait été fait ;
# - un statut explicite (`done`, `missed`, `cancelled`, `moved`) prime toujours
#   sur l'appariement automatique — mais un appariement automatique différé
#   (deux passes, ci-dessous) leur laisse toujours la priorité sur les activités ;
# - `cancelled` : le contrat (scripts/arc_contract.py::SUBSCHEMA["session"]) n'a
#   pas de motif d'annulation distinct (médical vs organisationnel). Ajouter une
#   clé rien que pour ce KPI aurait été la seule raison de son existence ; on
#   exclut donc TOUTE séance `cancelled` du dénominateur — l'énoncé du critère
#   d'acceptation (annulation médicale hors assiduité) est ainsi respecté au prix
#   d'être plus généreux qu'une distinction fine ne le serait. Si un besoin de
#   distinguer apparaît, la clé optionnelle à ajouter est `cancel_reason`
#   (enum `medical` / autre), documentée aux deux endroits exigés par
#   CONTRIBUTING.md avant d'être utilisée ici ;
# - `moved` : rien n'indique dans le contrat vers quelle date la séance a été
#   déplacée. On l'exclut du dénominateur (ni faite, ni manquée) ; si le coach a
#   effectivement écrit une nouvelle séance à la date réelle, cette séance est
#   comptée pour elle-même, avec son propre statut ;
# - `done` explicite SANS activité appariée (le coach a coché « fait » avant que
#   la synchronisation n'écrive le fichier d'activité, ou l'a écrit sans
#   chiffres) : compte dans `sessions_done` / `sessions_pct`, mais est exclu des
#   DEUX côtés des ratios durée/D+ — l'inclure aurait dégradé le ratio d'un
#   dénominateur planifié sans numérateur réel, pour une séance qu'on sait
#   pourtant faite ;
# - `planned` (ou statut absent), appariement en deux passes pour qu'une séance
#   sans statut ne puisse jamais « voler » l'activité d'une séance `done`
#   explicite du même jour :
#     1. les séances `done` explicites réservent d'abord leur activité (sport
#        exact, puis famille — `SPORT_FAMILY` : route/trail/randonnée/marche
#        interchangeables, variantes de vélo entre elles) ;
#     2. puis les séances sans statut piochent dans ce qui reste. Séance future
#        (date > aujourd'hui) → ignorée (jamais comptée manquée par
#        anticipation) ; séance du jour même sans activité correspondante →
#        `pending` (le jour n'est pas terminé, pas encore une séance manquée) ;
#        séance strictement passée sans correspondance → `missed`.
#   Plusieurs séances/activités le même jour : chaque activité n'est consommée
#   qu'une fois ;
# - semaine sans aucune séance planifiée (hors repos) → `None` (KPI absent),
#   jamais un ratio à 0/0 qui laisserait croire à une semaine blanche.
#
# Répartition par intensité : `easy` (récupération, endurance), `quality`
# (tempo, seuil, VO2max, course) et `other` — le contrat autorise aussi
# `strength` (scripts/arc_contract.py::INTENSITY), qui n'est ni l'un ni
# l'autre ; `other` couvre cette valeur et toute intensité absente, pour que
# easy + quality + other reconstitue toujours le total (hors repos).
# ---------------------------------------------------------------------------

SPORT_FAMILY = {
    "running": "run", "trail": "run", "hiking": "run", "walking": "run",
    "cycling": "bike", "indoor_cycling": "bike", "home_trainer": "bike",
}


def sport_family(sport: Optional[str]) -> Optional[str]:
    return SPORT_FAMILY.get(sport, sport)


EASY_INTENSITIES = ("recovery", "endurance")
QUALITY_INTENSITIES = ("tempo", "threshold", "vo2max", "race")
INTENSITY_BUCKETS = {"easy": EASY_INTENSITIES, "quality": QUALITY_INTENSITIES}

# Statuts qui priment sur l'appariement automatique.
_EXPLICIT_DONE = "done"
_EXPLICIT_MISSED = "missed"


def _is_rest(session: dict) -> bool:
    return session.get("sport") == "rest" or session.get("intensity") == "rest"


def _match_activity(by_date: Dict[str, List[dict]], day: Optional[str], sport: Optional[str]) -> Optional[dict]:
    """Consomme, au plus une fois, la meilleure activité du jour pour ce sport."""
    candidates = by_date.get(day) or []
    for act in candidates:
        if not act["_used"] and act.get("sport") == sport:
            act["_used"] = True
            return act
    family = sport_family(sport)
    for act in candidates:
        if not act["_used"] and sport_family(act.get("sport")) == family:
            act["_used"] = True
            return act
    return None


def _resolve_sessions(sessions: List[dict], by_date: Dict[str, List[dict]], today_iso: str) -> List[dict]:
    """Rend, pour chaque séance (dans l'ordre donné), `{session, effective, actual}`.

    Statuts effectifs : `done`, `missed`, `cancelled`, `moved`, `future`, `pending`.
    Deux passes sur l'appariement automatique (voir le commentaire de tête du
    module) : les `done` explicites réservent leur activité avant que les
    séances sans statut ne piochent dans ce qui reste.
    """
    resolved: List[Optional[dict]] = [None] * len(sessions)

    for i, session in enumerate(sessions):
        if session.get("status") == _EXPLICIT_DONE:
            actual = _match_activity(by_date, session.get("date"), session.get("sport"))
            resolved[i] = {"session": session, "effective": "done", "actual": actual}

    for i, session in enumerate(sessions):
        if resolved[i] is not None:
            continue
        status, day = session.get("status"), session.get("date")
        if status == "cancelled":
            resolved[i] = {"session": session, "effective": "cancelled", "actual": None}
        elif status == "moved":
            resolved[i] = {"session": session, "effective": "moved", "actual": None}
        elif status == _EXPLICIT_MISSED:
            resolved[i] = {"session": session, "effective": "missed", "actual": None}
        elif day and day > today_iso:
            resolved[i] = {"session": session, "effective": "future", "actual": None}
        else:
            matched = _match_activity(by_date, day, session.get("sport"))
            if matched:
                resolved[i] = {"session": session, "effective": "done", "actual": matched}
            elif day == today_iso:
                resolved[i] = {"session": session, "effective": "pending", "actual": None}
            else:
                resolved[i] = {"session": session, "effective": "missed", "actual": None}
    return resolved


def _ratio(actual_total: float, planned_total: float, has_planned: bool) -> Optional[float]:
    return round(actual_total / planned_total, 3) if has_planned and planned_total > 0 else None


def _bucket_metrics(resolved: List[dict]) -> dict:
    """% de séances faites + ratios durée/D+ sur un sous-ensemble de séances résolues."""
    counted = [r for r in resolved if r["effective"] in (_EXPLICIT_DONE, _EXPLICIT_MISSED)]
    done = [r for r in counted if r["effective"] == _EXPLICIT_DONE]
    duration_planned = duration_actual = elevation_planned = elevation_actual = 0.0
    has_duration = has_elevation = False
    for r in counted:
        if r["effective"] == _EXPLICIT_DONE and not r["actual"]:
            # Faite, mais sans activité chiffrée : ni au numérateur ni au dénominateur
            # du ratio (voir le commentaire de tête du module).
            continue
        s = r["session"]
        planned_d = s.get("planned_duration_s")
        if planned_d is not None:
            has_duration = True
            duration_planned += planned_d
            if r["actual"]:
                duration_actual += r["actual"].get("duration_s") or 0
        planned_e = s.get("planned_elevation_m")
        if planned_e is not None:
            has_elevation = True
            elevation_planned += planned_e
            if r["actual"]:
                elevation_actual += r["actual"].get("elevation_gain_m") or 0
    return {
        "sessions_planned": len(counted),
        "sessions_done": len(done),
        "sessions_pct": round(100 * len(done) / len(counted), 1) if counted else None,
        "duration_ratio": _ratio(duration_actual, duration_planned, has_duration),
        "elevation_ratio": _ratio(elevation_actual, elevation_planned, has_elevation),
    }


def week_compliance(sessions: List[dict], activities: List[dict], today) -> Optional[dict]:
    """Conformité plan vs réalisé d'une semaine. `None` si aucune séance planifiée
    (hors repos — voir le commentaire de tête du module).

    `sessions` : lignes `planned_session` (ou sous-schéma `session` du contrat).
    `activities` : lignes `activity` de la même fenêtre (date, sport, duration_s,
    elevation_gain_m…). `today` : `date` ou chaîne AAAA-MM-JJ.
    """
    non_rest_input = [s for s in sessions if not _is_rest(s)]
    if not non_rest_input:
        return None
    today_iso = today.isoformat() if hasattr(today, "isoformat") else today
    by_date: Dict[str, List[dict]] = {}
    for act in activities:
        by_date.setdefault(act.get("date"), []).append({**act, "_used": False})

    ordered = sorted(sessions, key=lambda s: s.get("date") or "")
    resolved_all = _resolve_sessions(ordered, by_date, today_iso)
    rest_count = sum(1 for r in resolved_all if _is_rest(r["session"]))
    resolved = [r for r in resolved_all if not _is_rest(r["session"])]

    overall = _bucket_metrics(resolved)
    other_intensities = set(EASY_INTENSITIES) | set(QUALITY_INTENSITIES)
    by_intensity = {
        name: _bucket_metrics([r for r in resolved if r["session"].get("intensity") in values])
        for name, values in INTENSITY_BUCKETS.items()
    }
    by_intensity["other"] = _bucket_metrics(
        [r for r in resolved if r["session"].get("intensity") not in other_intensities])
    overall.update({
        "sessions_rest": rest_count,
        "sessions_cancelled": sum(1 for r in resolved if r["effective"] == "cancelled"),
        "sessions_moved": sum(1 for r in resolved if r["effective"] == "moved"),
        "sessions_future": sum(1 for r in resolved if r["effective"] == "future"),
        "sessions_pending": sum(1 for r in resolved if r["effective"] == "pending"),
        "by_intensity": by_intensity,
    })
    return overall


# ---------------------------------------------------------------------------
# Acclimatation à la chaleur (#38)
# ---------------------------------------------------------------------------


def is_outdoor_sport(sport: Optional[str]) -> bool:
    """`True` pour tout sport connu du contrat sauf `INDOOR_SPORTS`. Voir
    `ASSUMPTIONS["heat_acclimation"]` pour la justification (swimming/rowing traités
    outdoor par défaut faute de variante indoor déclarée dans le contrat)."""
    return sport is not None and sport not in INDOOR_SPORTS


def normalize_location(text: Optional[str]) -> Optional[str]:
    """Nom de ville normalisé pour comparer deux `location` : partie avant la
    première virgule (« Annecy, France » → « Annecy »), espaces de bord retirés,
    accents supprimés, casse ignorée. `None`/vide → `None`. Utilisé par
    `pick_weather`/`pick_weather_strict` pour que « Annecy » et « Annecy, France »
    se reconnaissent comme le même lieu — voir `ASSUMPTIONS["heat_acclimation"]`."""
    if not text:
        return None
    city = text.split(",", 1)[0].strip()
    if not city:
        return None
    stripped = "".join(ch for ch in unicodedata.normalize("NFKD", city) if not unicodedata.combining(ch))
    return stripped.casefold()


def pick_weather(weather_rows: List[dict], location: Optional[str]) -> Optional[dict]:
    """Choisit le fichier météo applicable parmi ceux du même jour, pour une
    ACTIVITÉ (voir `pick_weather_strict` pour un usage qui ne doit jamais deviner).

    Un seul fichier : il s'applique — l'activité est censée s'être déroulée au lieu
    d'entraînement pour lequel le skill `weather-forecast` fetch la météo du jour,
    donc un fichier unique correspond par construction, même si son `location` ne
    matche pas exactement le texte libre de l'activité. Plusieurs : priorité à
    celui dont `location` correspond (`normalize_location`, nom de ville, accents
    et casse ignorés) ; sans correspondance, `None` (voir `ASSUMPTIONS["heat_acclimation"]`).
    """
    if not weather_rows:
        return None
    if len(weather_rows) == 1:
        return weather_rows[0]
    loc = normalize_location(location)
    if loc:
        for row in weather_rows:
            if normalize_location(row.get("location")) == loc:
                return row
    return None


def pick_weather_strict(weather_rows: List[dict], location: Optional[str]) -> Optional[dict]:
    """Comme `pick_weather`, mais SANS le raccourci « un seul fichier => il
    s'applique » : à utiliser quand rien ne garantit que le fichier météo du jour
    a été fetché pour le lieu demandé (ex. météo de la course d'un objectif, alors
    que le skill `weather-forecast` fetch d'abord et surtout le lieu
    d'entraînement — un jour donné n'a souvent qu'un seul fichier météo, et c'est
    presque toujours celui de l'entraînement, pas celui d'une course lointaine).
    Exige une correspondance de lieu explicite ; `None` sinon, y compris avec un
    seul candidat non concordant ou sans lieu à comparer."""
    loc = normalize_location(location)
    if not loc:
        return None
    for row in weather_rows:
        if normalize_location(row.get("location")) == loc:
            return row
    return None


def _resolve_hot(candidates: List[dict], location: Optional[str], threshold_c: float) -> Optional[bool]:
    """`True`/`False` si on peut trancher si le jour était chaud pour cette activité,
    `None` si on ne peut pas savoir (voir `ASSUMPTIONS["heat_acclimation"]`).

    D'abord une correspondance de lieu (`pick_weather`). Si aucune ne correspond
    (plusieurs fichiers, lieu de l'activité absent ou non concordant) mais que
    TOUS les fichiers du jour s'accordent sur le verdict chaud/pas chaud, ce
    verdict est rendu quand même : peu importe lequel des lieux est le bon
    puisqu'ils concluent tous pareil. S'ils divergent, `None` (pas de verdict
    deviné)."""
    if not candidates:
        return None
    weather = pick_weather(candidates, location)
    if weather is not None:
        return weather["temp_max_c"] >= threshold_c
    hot_flags = {c["temp_max_c"] >= threshold_c for c in candidates}
    return hot_flags.pop() if len(hot_flags) == 1 else None


def heat_acclimation(activities: List[dict], weather_rows: List[dict], end,
                      threshold_c: float = HEAT_THRESHOLD_C_DEFAULT,
                      window_days: int = HEAT_WINDOW_DAYS) -> dict:
    """Acclimatation à la chaleur sur les `window_days` jours se terminant à `end` inclus.

    `activities` : dicts portant au moins `date` (AAAA-MM-JJ), `sport`, `duration_s`,
    `location` (optionnel). `weather_rows` : dicts `date`, `location`, `temp_max_c`
    (un fichier météo par lieu et par jour — voir skill `weather-forecast`). `end` :
    `date` ou chaîne AAAA-MM-JJ.

    Voir `ASSUMPTIONS["heat_acclimation"]` pour la méthode complète (jointure par
    date, choix du fichier météo si plusieurs lieux le même jour, séances sans
    météo ignorées et comptées à part, borne du seuil incluse).
    """
    end_d = end if hasattr(end, "isoformat") else date.fromisoformat(end)
    start_d = end_d - timedelta(days=window_days - 1)
    start_iso, end_iso = start_d.isoformat(), end_d.isoformat()

    weather_by_date: Dict[str, List[dict]] = {}
    for row in weather_rows:
        day = row.get("date")
        if day and start_iso <= day <= end_iso and row.get("temp_max_c") is not None:
            weather_by_date.setdefault(day, []).append(row)

    hot_sessions = 0
    hot_duration_s = 0.0
    sessions_considered = 0
    sessions_without_weather = 0
    for act in activities:
        day = act.get("date")
        if not day or not start_iso <= day <= end_iso or not is_outdoor_sport(act.get("sport")):
            continue
        hot = _resolve_hot(weather_by_date.get(day, []), act.get("location"), threshold_c)
        if hot is None:
            sessions_without_weather += 1
            continue
        sessions_considered += 1
        if hot:
            hot_sessions += 1
            hot_duration_s += act.get("duration_s") or 0

    return {
        "window_days": window_days,
        "threshold_c": threshold_c,
        "hot_sessions": hot_sessions,
        "hot_duration_s": round(hot_duration_s),
        "sessions_considered": sessions_considered,
        "sessions_without_weather": sessions_without_weather,
    }
