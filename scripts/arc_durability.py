#!/usr/bin/env python3
"""Durabilité sur les sorties longues (#48, épopée #21).

## Principe

Sur une sortie longue, indicateur de baisse de performance en fin de
parcours : compare le dernier tiers (en temps de mouvement) à son premier
tiers, sur l'allure ajustée à la pente (GAP, `arc_gap.py`, #44) et sur la
fréquence cardiaque, la comparaison EF (GAP/FC) se faisant sur le
SOUS-ENSEMBLE COMMUN d'échantillons où FC et GAP sont TOUS DEUX présents
(jamais deux moyennes sur deux sous-ensembles différents, qui biaiseraient le
ratio dès qu'un trou de FC ne coïncide pas avec un trou de GAP — même
discipline que `arc_decoupling._ef`, #45) :

    fade GAP % = (GAP_1er_tiers − GAP_dernier_tiers) / GAP_1er_tiers × 100
    fade EF %  = (EF_1er_tiers  − EF_dernier_tiers)  / EF_1er_tiers  × 100

Une valeur POSITIVE signale une baisse de performance en fin de sortie (le
sens attendu du mot « fade ») ; une valeur négative ou nulle signale une
séance sans baisse mesurable, voire une deuxième partie plus rapide (négatif
splitting). Repère de coaching indicatif, jamais un seuil validé
cliniquement, ni un « prédicteur » démontré de la tenue en ultra — aucune
source vérifiable n'établit un tel lien quantifié pour ce calcul précis,
seulement le raisonnement physiologique de bon sens (un athlète qui ralentit
nettement en fin de sortie longue tient probablement moins bien l'effort
prolongé) ; calqué sur l'esprit du découplage aérobie (`arc_decoupling.py`,
#45) mais sur le DERNIER TIERS plutôt que la seconde moitié — le fade cible
spécifiquement l'effondrement de fin de sortie longue, pas une dérive
linéaire sur toute la séance.

### Lire fade GAP et fade EF ensemble (voir `ASSUMPTIONS["reading_gap_vs_ef"]`)

Les deux chiffres racontent des histoires différentes, jamais à lire
séparément : **fade EF nettement supérieur au fade GAP** signale une dérive
cardiaque à allure comparable (la FC est montée alors que l'allure a peu
changé — fatigue cardiovasculaire) ; **fade GAP marqué avec un fade EF proche
de 0** signale que l'allure ET la FC ont baissé ENSEMBLE (l'athlète a
volontairement ou involontairement réduit l'effort, pas seulement l'allure) —
voir `ASSUMPTIONS["reading_gap_vs_ef"]` pour le détail complet.

## Réutilisation — rien de recalculé, helpers PARTAGÉS avec le découplage (#45)

Ce module ne recalcule ni pente ni GAP : il consomme une série DÉJÀ augmentée
par `arc_gap.gap_sample_series` (voir `arc_index.compute_metrics`, qui la
calcule une seule fois par activité pour le GAP/#44, le découplage/#45, la
descente/#47 ET la durabilité/#48). Il réutilise en outre TELS QUELS les
helpers d'éligibilité déjà écrits et testés par `arc_decoupling.py` (#45) —
jamais une seconde implémentation parallèle des mêmes règles :

- `_is_moving`/`_is_walking`/`_is_steep`/`_usable_for_ef` : mouvement, marche/
  power-hiking, pente forte, échantillon utilisable pour l'EF — voir
  `arc_decoupling.ASSUMPTIONS["steep_grade_and_walking"]`.
- `_dt_to_next`/`_weighted_time` : pondération temporelle d'un échantillon.
- `_split_by_moving_time_n` (généralisée par #48 à partir de la version à
  deux moitiés de #45, SANS changement de comportement pour le découplage —
  voir sa docstring) : découpage en `n` portions ÉGALES de temps de
  mouvement — ici `n=3`.
- `_hr_coverage_frac` : couverture FC d'une portion, tout terrain confondu.

Seuls le découpage en TROIS portions (au lieu de deux), le calcul du fade
GAP/EF sur PREMIER vs DERNIER tiers (le tiers du milieu n'entre dans aucun
ratio, seulement dans le calcul de sa propre FC moyenne, exposée à titre
descriptif) et l'assemblage des raisons d'inéligibilité sont propres à ce
module.

## Éligibilité

Voir `ASSUMPTIONS` pour le détail complet. Résumé : famille course à pied,
échantillons FIT ingérés, durée de mouvement TOTALE (échauffement compris)
strictement supérieure à `arc_metrics.LONG_RUN_MIN_DURATION_S` (90 min, même
borne que les autres KPI « sortie longue » du projet — glucides/h #41,
tendance de découplage #45) ; échauffement exclu EN PREMIER (même
`arc_decoupling.WARMUP_S`, 10 min), PUIS le reste découpé en trois portions
ÉGALES de temps de mouvement ; pentes fortes et marche exclues du calcul
(mais ne rejettent jamais la séance entière) ; couverture FC ≥ 80 % sur le
premier ET le dernier tiers (le tiers du milieu n'entrant dans aucun ratio,
sa couverture n'est pas vérifiée) ; au moins 10 minutes de portions
RÉELLEMENT COURUES exploitables sur le premier et le dernier tiers ; profil
de pente comparable entre premier et dernier tiers (écart de pente moyenne
≤ 3 points, même seuil que le découplage — le GAP ne corrige pas parfaitement
la pente en forte déclivité, voir `arc_gap.ASSUMPTIONS["model"]`). AUCUNE
règle d'« effort stable » contrairement au découplage (#45) : le fade de fin
de sortie longue est précisément ce qu'on cherche à détecter, une sortie qui
ralentit nettement en fin de parcours ne doit pas être écartée pour ça.

## Limites connues (revue de code #48, honnêteté du repère)

**Une bonne part des sorties longues en terrain montagneux est
STRUCTURELLEMENT inéligible**, jamais un bug : un aller-retour à un sommet
(montée dans le premier tiers, descente dans le dernier) ou un circuit
« montée d'abord » (gros dénivelé en début de sortie, plus plat ensuite)
déclenchent presque systématiquement `ASSUMPTIONS["grade_asymmetry"]` ou
`ASSUMPTIONS["usable_running"]` (trop de pente forte/marche concentrée dans
un seul tiers) — voir `ASSUMPTIONS["mountain_long_runs"]` pour le détail et
la mesure sur un workspace synthétique de 365 jours (0/39 sorties longues
éligibles sur un profil trail avec relief marqué). Le tiers du MILIEU n'est
JAMAIS utilisé dans un ratio (voir `ASSUMPTIONS["portions"]`) : une grosse
montée qui y est intégralement contenue n'a donc aucun effet sur
l'éligibilité, mais une sortie où la montée déborde sur le premier ou le
dernier tiers reste vulnérable à l'asymétrie ci-dessus. **Sans règle d'effort
stable** (volontairement, voir ci-dessus), une course avec accélération
finale (« kick »), un fartlek ou des intervalles en fin de sortie longue
produisent un fade qui reflète le PLAN de la séance, pas une baisse de
performance réelle — ce KPI n'est interprétable que sur une sortie à effort
globalement continu (endurance fondamentale), jamais sur une séance à
structure imposée.

## API réutilisable, pure (sans SQLite ni disque)

- `durability_report(samples, sport, resolution_s=...)` : rapport complet à
  partir des échantillons normalisés et du sport de l'activité — TOUJOURS un
  dict avec `reason`/`reason_code`/`applicable` explicites, jamais une
  exception (même discipline que `arc_descent.descent_report`, #47).
- `durability_report_from_series(series, resolution_s=...)` : même rapport à
  partir d'une série DÉJÀ augmentée par `arc_gap.gap_sample_series` — évite un
  second calcul pente/GAP pour la même activité (`arc_index.compute_metrics`).

Stdlib uniquement (CONTRIBUTING.md).
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent))
import arc_decoupling as DC  # noqa: E402
import arc_gap as G  # noqa: E402
import arc_metrics as M  # noqa: E402

DEFAULT_RESOLUTION_S = G.DEFAULT_RESOLUTION_S

# Nombre de portions du découpage post-échauffement — TROIS, contrairement aux
# deux moitiés du découplage (#45) : c'est le premier ET le dernier tiers qui
# comptent pour le fade, le tiers du milieu n'étant qu'un intermédiaire.
N_PORTIONS = 3

# Seuil d'éligibilité (#48, critère d'acceptation : « séances > 90 min ») —
# réutilise TELLE QUELLE la borne « sortie longue » déjà partagée par
# `carbs_per_hour_g`/`fueling_trend` (#41) et la tendance de découplage (#45) :
# une seule définition de « sortie longue » dans tout le projet, jamais une
# borne différente par KPI. Comparaison STRICTE (`>`), pas `>=` — même
# convention que `arc_metrics.carbs_per_hour_g`.
MIN_MOVING_DURATION_S = M.LONG_RUN_MIN_DURATION_S

# Échauffement exclu EN PREMIER — même valeur et même justification que
# `arc_decoupling.WARMUP_S` (#45) : la FC met plusieurs minutes à atteindre
# son régime de croisière, l'inclure fausserait la mesure du premier tiers.
WARMUP_S = DC.WARMUP_S

# Chaque tiers utilisé dans un ratio (premier, dernier) doit couvrir au moins
# 10 minutes de mouvement post-échauffement — même seuil et même
# justification que `arc_decoupling.MIN_HALF_MOVING_S` : sous ce seuil, la
# moyenne pondérée devient trop sensible à un seul échantillon bruité.
MIN_PORTION_MOVING_S = DC.MIN_HALF_MOVING_S

# Couverture FC minimale du premier ET du dernier tiers (tout terrain
# confondu, pente forte et marche comprises) — même seuil et même
# justification que `arc_decoupling.MIN_HR_COVERAGE_FRAC`.
MIN_HR_COVERAGE_FRAC = DC.MIN_HR_COVERAGE_FRAC

# Écart de pente moyenne maximal toléré entre le premier et le dernier tiers
# — même seuil et même justification que `arc_decoupling.GRADE_ASYMMETRY_MAX` :
# un aller-retour avec le gros de la montée dans un tiers et la descente dans
# l'autre produirait un fade qui reflète surtout le relief, pas la fatigue.
GRADE_ASYMMETRY_MAX = DC.GRADE_ASYMMETRY_MAX

REASON_NOT_RUN_FAMILY = ("hors de la famille course à pied (arc_metrics.sport_family), voir "
                          "arc_durability.ASSUMPTIONS[\"restricted_to_run_family\"]")
REASON_NO_SAMPLES = "aucun échantillon FIT ingéré pour cette séance"
REASON_TOO_SHORT = (f"durée de mouvement insuffisante (≤ {MIN_MOVING_DURATION_S / 60:.0f} min), voir "
                     "arc_durability.ASSUMPTIONS[\"min_duration\"]")
REASON_NO_POST_WARMUP = ("aucun échantillon après exclusion de l'échauffement, voir "
                          "arc_durability.ASSUMPTIONS[\"warmup\"]")
REASON_INSUFFICIENT_PORTION = (
    f"durée exploitable insuffisante sur le premier ou le dernier tiers (< {MIN_PORTION_MOVING_S / 60:.0f} "
    "min de mouvement), voir arc_durability.ASSUMPTIONS[\"portions\"]")
REASON_HR_INCOMPLETE = (
    f"FC incomplète sur le premier ou le dernier tiers (minimum {MIN_HR_COVERAGE_FRAC * 100:.0f} %), voir "
    "arc_durability.ASSUMPTIONS[\"hr_coverage\"]")
REASON_INSUFFICIENT_USABLE_RUNNING = (
    "trop peu de portions courues exploitables (hors pente forte/marche) sur le premier ou le dernier "
    f"tiers (< {MIN_PORTION_MOVING_S / 60:.0f} min), voir arc_durability.ASSUMPTIONS[\"usable_running\"]")
REASON_GRADE_ASYMMETRY = (
    f"profil de pente trop différent entre le premier et le dernier tiers, voir "
    "arc_durability.ASSUMPTIONS[\"grade_asymmetry\"]")
REASON_MISSING_HR_OR_GAP = "FC ou GAP insuffisant sur le premier ou le dernier tiers"
REASON_UNKNOWN_ACTIVITY = "aucune activité indexée pour ce garmin_activity_id"

ASSUMPTIONS = {
    "model": (
        "Durabilité sur les sorties longues (#48), indicateur de baisse de performance en fin de "
        "parcours : compare le dernier tiers (temps de mouvement, post-échauffement) au premier tiers de "
        "la même sortie, sur l'allure ajustée à la pente (GAP, arc_gap.py, #44) et sur la fréquence "
        "cardiaque — fade GAP % = (GAP 1er tiers − GAP dernier tiers) / GAP 1er tiers × 100, fade EF % de "
        "même sur EF = GAP/FC. GAP et FC moyens sont calculés sur le MÊME sous-ensemble commun "
        "d'échantillons (FC et GAP tous deux présents) pour chaque tiers — jamais deux moyennes sur deux "
        "sous-ensembles différents, qui biaiseraient le ratio EF dès qu'un trou de FC ne coïncide pas "
        "avec un trou de GAP (même discipline que arc_decoupling.ASSUMPTIONS['model'], #45). Une valeur "
        "POSITIVE signale une baisse de performance en fin de sortie (fade) ; négative ou nulle, une "
        "séance sans baisse mesurable, voire un négative splitting. Repère de coaching indicatif, PAS un "
        "seuil validé cliniquement, ET PAS un « prédicteur » démontré de la tenue en ultra (revue de "
        "code #48) : aucune source vérifiable n'établit un lien quantifié pour ce calcul précis, seulement "
        "le raisonnement physiologique de bon sens qu'un ralentissement net en fin de sortie longue "
        "reflète probablement une moins bonne tenue de l'effort prolongé — même prudence que le "
        "découplage aérobie (#45), dont ce module partage l'esprit et les helpers d'éligibilité, mais sur "
        "le DERNIER TIERS plutôt que la seconde moitié : le fade cible spécifiquement l'effondrement de "
        "fin de sortie longue, pas une dérive linéaire sur toute la séance."
    ),
    "reading_gap_vs_ef": (
        "Fade GAP et fade EF se lisent ENSEMBLE, jamais isolément (revue de code #48, nit) : un fade EF "
        "NETTEMENT SUPÉRIEUR au fade GAP signale une dérive cardiaque À ALLURE COMPARABLE (la FC est "
        "montée alors que l'allure a peu changé sur le dernier tiers — fatigue cardiovasculaire, même "
        "phénomène que le découplage aérobie, #45, mais concentré en fin de sortie). Un fade GAP MARQUÉ "
        "avec un fade EF PROCHE DE 0, à l'inverse, signale que l'allure ET la FC ont baissé ENSEMBLE dans "
        "la même proportion (l'effort métabolique réel, lui, n'a pas changé) : l'athlète a réduit "
        "l'intensité — volontairement (gestion tactique d'une sortie longue) ou involontairement (fatigue "
        "musculaire/mécanique plutôt que cardiovasculaire) — pas seulement son allure. Un fade GAP ET un "
        "fade EF tous deux marqués et proches combinent probablement les deux effets. Ni l'un ni l'autre "
        "cas ne distingue une cause précise (chaleur, hydratation, nutrition, fatigue musculaire...) : ce "
        "module mesure un SYMPTÔME, pas un diagnostic."
    ),
    "mountain_long_runs": (
        "LIMITE CONNUE, documentée honnêtement (revue de code #48) : une bonne part des sorties longues "
        "en terrain montagneux est STRUCTURELLEMENT inéligible, jamais un bug de seuil. Un aller-retour à "
        "un sommet (montée concentrée dans le premier tiers, descente dans le dernier) ou un circuit "
        "« montée d'abord » (gros dénivelé en début de sortie) déclenchent presque systématiquement "
        "ASSUMPTIONS['grade_asymmetry'] ou ASSUMPTIONS['usable_running'] (trop de pente forte/marche "
        "concentrée dans un seul tiers) — mesuré sur `tests.lib.synthetic.build(days=365, sport='trail', "
        "seed=7, with_samples=True)` : 0 sortie longue éligible sur 40 (31 pour asymétrie de pente, 9 pour "
        "manque de course exploitable). Le tiers du MILIEU n'est JAMAIS utilisé dans un ratio (voir "
        "ASSUMPTIONS['portions']) : une grosse montée entièrement contenue dans ce tiers n'affecte donc "
        "PAS l'éligibilité, mais une montée qui déborde sur le premier ou le dernier tiers reste "
        "vulnérable à l'asymétrie ci-dessus. Un profil trail avec relief RÉPARTI (plusieurs bosses "
        "comparables dans chaque tiers, comme les sorties vallonnées éligibles au découplage, #45) reste "
        "éligible — c'est le déséquilibre CONCENTRÉ dans un seul tiers, pas le relief en général, qui "
        "rend une sortie inéligible."
    ),
    "restricted_to_run_family": (
        "Calculé UNIQUEMENT pour les séances de la famille course à pied (arc_metrics.sport_family == "
        "\"run\") avec des échantillons FIT ingérés — même restriction que le GAP (#44), le découplage "
        "(#45), la VAM (#46) et la descente (#47)."
    ),
    "min_duration": (
        f"Séance de plus de {MIN_MOVING_DURATION_S / 60:.0f} minutes de mouvement (échauffement compris) "
        "— la même borne « sortie longue » que `arc_metrics.LONG_RUN_MIN_DURATION_S`, déjà utilisée par "
        "les glucides/h (#41) et la tendance de découplage (#45) : une seule définition de sortie longue "
        "dans tout le projet. Comparaison STRICTE, pas ≥."
    ),
    "warmup": (
        f"Les {WARMUP_S / 60:.0f} premières minutes ÉCOULÉES (arrêts compris dans ce décompte) sont "
        "exclues EN PREMIER, puis le reste est partagé en TROIS portions ÉGALES de temps de mouvement — "
        "même protocole et même justification que `arc_decoupling.ASSUMPTIONS['warmup']` (#45) : la FC "
        "met plusieurs minutes à atteindre son régime de croisière, l'inclure fausserait la mesure du "
        "premier tiers à la baisse (dérive apparente sous-estimée)."
    ),
    "portions": (
        f"Le premier ET le dernier tiers (post-échauffement, temps de mouvement) doivent chacun couvrir "
        f"au moins {MIN_PORTION_MOVING_S / 60:.0f} minutes de mouvement — sous ce seuil, la moyenne "
        "pondérée d'un tiers deviendrait trop sensible à un seul échantillon bruité (même seuil que "
        "`arc_decoupling.ASSUMPTIONS['halves']`, transposé à un tiers plutôt qu'une moitié). Le tiers du "
        "milieu n'est soumis à AUCUN seuil de durée minimale : il n'entre dans aucun ratio de fade, "
        "seulement dans le calcul descriptif de sa propre FC moyenne."
    ),
    "steep_grade_and_walking": (
        "Les échantillons de pente forte et de marche/power-hiking sont exclus du calcul du fade ET de "
        "la FC par tiers, dans les TROIS tiers — jamais de la séance dans son ensemble (elle reste "
        "éligible si le reste suffit) — même seuils et même justification que "
        "`arc_decoupling.ASSUMPTIONS['steep_grade_and_walking']` (#45) : au-delà d'environ 12 % le "
        "modèle de Minetti (#44) est moins fiable, et ces portions sont le plus souvent marchées plutôt "
        "que courues."
    ),
    "hr_coverage": (
        f"Le premier ET le dernier tiers doivent avoir au moins {MIN_HR_COVERAGE_FRAC * 100:.0f} % de "
        "leur temps de mouvement couvert par une FC présente — tout terrain confondu, pente forte et "
        "marche COMPRISES, même seuil et même justification que "
        "`arc_decoupling.ASSUMPTIONS['hr_coverage']` (#45). Le tiers du milieu n'est PAS soumis à cette "
        "vérification (il n'entre dans aucun ratio de fade)."
    ),
    "usable_running": (
        f"Indépendamment de la couverture FC ci-dessus, le premier ET le dernier tiers doivent chacun "
        f"conserver au moins {MIN_PORTION_MOVING_S / 60:.0f} minutes de temps RÉELLEMENT COURU "
        "exploitable (FC et GAP présents, hors pente forte et marche) — une DURÉE ABSOLUE, jamais une "
        "part relative, même discipline que `arc_decoupling.ASSUMPTIONS['usable_running']` (#45) : une "
        "sortie de montagne où la pente forte/la marche occupent une portion importante d'un tiers reste "
        "éligible tant qu'il reste assez de course exploitable en minutes."
    ),
    "grade_asymmetry": (
        f"Si la pente moyenne (pondérée par le temps, échantillons utilisés pour le fade) diffère de "
        f"plus de {GRADE_ASYMMETRY_MAX * 100:.0f} points entre le premier et le dernier tiers (ex. un "
        "aller-retour avec la montée principale dans un tiers et la descente dans l'autre), la séance "
        "est jugée inéligible — même seuil et même justification que "
        "`arc_decoupling.ASSUMPTIONS['grade_asymmetry']` (#45) : le GAP corrige l'effet de la pente sur "
        "l'allure, mais pas parfaitement (biais connu du modèle de Minetti en forte descente) — un "
        "profil trop différent entre les deux tiers comparés produirait un fade qui reflète surtout le "
        "relief traversé, pas la fatigue."
    ),
    "no_steady_effort_rule": (
        "Contrairement au découplage aérobie (#45), AUCUNE règle d'« effort stable » n'est appliquée "
        "ici : le fade de fin de sortie longue (baisse nette d'allure sur le dernier tiers) est "
        "précisément le phénomène que ce KPI cherche à détecter — une sortie qui ralentit fortement en "
        "fin de parcours ne doit jamais être écartée pour cette raison, ce serait rejeter l'exact signal "
        "recherché. CONTREPARTIE ASSUMÉE (revue de code #48, nit) : ce KPI n'est interprétable QUE sur une "
        "sortie à effort globalement continu (endurance fondamentale). Une course avec accélération "
        "finale (« kick », finish rapide), un fartlek ou des intervalles placés en fin de sortie longue "
        "produisent un fade qui reflète le PLAN DE LA SÉANCE (allure volontairement variée), pas une "
        "baisse de performance réelle — dans ces cas, ni le fade GAP ni le fade EF ne doivent être lus "
        "comme un signal de durabilité, une valeur négative ou positive marquée y étant simplement "
        "l'effet du plan d'entraînement. Aucune détection automatique de ce cas n'est faite ici (le "
        "titre/l'intensité déclarée de la séance n'est pas consultée) : à l'athlète et au coach de savoir "
        "que la séance avait une structure imposée avant d'interpréter le chiffre."
    ),
    "hr_by_third": (
        "La FC moyenne (pondérée par le temps, sur les échantillons utilisables — hors pente forte/"
        "marche, voir ASSUMPTIONS['steep_grade_and_walking']) est exposée pour les TROIS tiers "
        "(`hr_first_third_bpm`/`hr_middle_third_bpm`/`hr_last_third_bpm`), à titre descriptif — c'est un "
        "fait de séance utile pour la fiche, indépendant du fade lui-même (qui ne compare que le premier "
        "et le dernier tiers). Le tiers du milieu peut donc afficher une FC même quand le fade global est "
        "`None` (ex. tiers du milieu couvert, premier ou dernier trop court)."
    ),
}


def durability_report_from_series(series: Sequence[dict], *,
                                   resolution_s: float = DEFAULT_RESOLUTION_S) -> dict:
    """Rapport de durabilité (#48) à partir d'une série DÉJÀ augmentée par
    `arc_gap.gap_sample_series` — évite un second calcul pente/GAP pour la
    même activité (voir `arc_index.compute_metrics`). ASSUME que `series` est
    déjà restreinte à la famille course à pied par l'appelant (comme
    `arc_decoupling.decoupling_report_from_series`) — voir `durability_report`
    pour une API autonome qui vérifie le sport elle-même.

    Rend TOUJOURS `{"gap_fade_pct", "ef_fade_pct", "gap_first_third_ms",
    "gap_last_third_ms", "ef_first_third", "ef_last_third",
    "hr_first_third_bpm", "hr_middle_third_bpm", "hr_last_third_bpm",
    "moving_duration_s", "eligible", "reason", "reason_code", "applicable"}` —
    `reason`/`reason_code` explique un `eligible: False`, jamais une exception
    ni un échec muet (même discipline que `arc_descent.descent_report`, #47).
    `applicable` (bool) : `False` UNIQUEMENT quand la séance n'a
    structurellement jamais pu être évaluée par ce KPI (hors famille course à
    pied) — `True` sinon, y compris pour une absence de données."""
    empty = {"gap_fade_pct": None, "ef_fade_pct": None, "gap_first_third_ms": None, "gap_last_third_ms": None,
              "ef_first_third": None, "ef_last_third": None, "hr_first_third_bpm": None,
              "hr_middle_third_bpm": None, "hr_last_third_bpm": None, "moving_duration_s": None,
              "eligible": False}
    ordered = sorted((s for s in series if s.get("t_s") is not None), key=lambda s: s["t_s"])
    if not ordered:
        return {**empty, "reason": "aucun échantillon exploitable (t_s manquant)",
                "reason_code": "no_usable_samples", "applicable": True}

    whole_moving_s = sum(
        DC._dt_to_next(ordered, i, resolution_s) for i, s in enumerate(ordered) if DC._is_moving(s))
    if whole_moving_s <= MIN_MOVING_DURATION_S:
        return {**empty, "moving_duration_s": round(whole_moving_s, 1),
                "reason": REASON_TOO_SHORT, "reason_code": "too_short", "applicable": True}

    # Échauffement exclu EN PREMIER (voir ASSUMPTIONS["warmup"]), PUIS découpage
    # du reste en trois portions ÉGALES de temps de mouvement.
    t0 = ordered[0]["t_s"]
    post_warmup = [s for s in ordered if s["t_s"] - t0 >= WARMUP_S]
    if not post_warmup:
        return {**empty, "moving_duration_s": round(whole_moving_s, 1),
                "reason": REASON_NO_POST_WARMUP, "reason_code": "no_post_warmup", "applicable": True}

    thirds = DC._split_by_moving_time_n(post_warmup, N_PORTIONS, resolution_s=resolution_s)
    first_raw, middle_raw, last_raw = thirds
    first_moving_s = DC._weighted_time(first_raw, resolution_s)
    last_moving_s = DC._weighted_time(last_raw, resolution_s)
    if first_moving_s < MIN_PORTION_MOVING_S or last_moving_s < MIN_PORTION_MOVING_S:
        return {**empty, "moving_duration_s": round(whole_moving_s, 1),
                "reason": REASON_INSUFFICIENT_PORTION, "reason_code": "insufficient_portion",
                "applicable": True}

    coverage_first = DC._hr_coverage_frac(first_raw, resolution_s)
    coverage_last = DC._hr_coverage_frac(last_raw, resolution_s)
    if coverage_first < MIN_HR_COVERAGE_FRAC or coverage_last < MIN_HR_COVERAGE_FRAC:
        return {**empty, "moving_duration_s": round(whole_moving_s, 1),
                "reason": REASON_HR_INCOMPLETE, "reason_code": "hr_incomplete", "applicable": True}

    usable_first = [s for s in first_raw if DC._usable_for_ef(s) and s.get("hr_bpm") is not None
                    and s.get("gap_speed_ms") is not None]
    usable_middle = [s for s in middle_raw if DC._usable_for_ef(s) and s.get("hr_bpm") is not None
                      and s.get("gap_speed_ms") is not None]
    usable_last = [s for s in last_raw if DC._usable_for_ef(s) and s.get("hr_bpm") is not None
                   and s.get("gap_speed_ms") is not None]
    usable_first_s = DC._weighted_time(usable_first, resolution_s)
    usable_last_s = DC._weighted_time(usable_last, resolution_s)
    if usable_first_s < MIN_PORTION_MOVING_S or usable_last_s < MIN_PORTION_MOVING_S:
        return {**empty, "moving_duration_s": round(whole_moving_s, 1),
                "reason": REASON_INSUFFICIENT_USABLE_RUNNING, "reason_code": "insufficient_usable_running",
                "applicable": True}

    grade_first = G.weighted_average(usable_first, "grade", resolution_s)
    grade_last = G.weighted_average(usable_last, "grade", resolution_s)
    if grade_first is not None and grade_last is not None and abs(grade_first - grade_last) > GRADE_ASYMMETRY_MAX:
        return {**empty, "moving_duration_s": round(whole_moving_s, 1),
                "reason": REASON_GRADE_ASYMMETRY, "reason_code": "grade_asymmetry", "applicable": True}

    def _ef(usable: Sequence[dict]) -> Optional[float]:
        if not usable:
            return None
        mean_gap_ms = G.weighted_average(usable, "gap_speed_ms", resolution_s)
        mean_hr = G.weighted_average(usable, "hr_bpm", resolution_s)
        if mean_gap_ms is None or not mean_hr:
            return None
        return (mean_gap_ms * 60.0) / mean_hr

    gap_first = G.weighted_average(usable_first, "gap_speed_ms", resolution_s)
    gap_last = G.weighted_average(usable_last, "gap_speed_ms", resolution_s)
    ef_first = _ef(usable_first)
    ef_last = _ef(usable_last)
    if gap_first is None or gap_last is None or ef_first is None or ef_last is None:
        return {**empty, "moving_duration_s": round(whole_moving_s, 1),
                "reason": REASON_MISSING_HR_OR_GAP, "reason_code": "missing_hr_or_gap", "applicable": True}

    # FC par tiers (#48, à titre descriptif — voir ASSUMPTIONS["hr_by_third"]) : sur
    # les échantillons utilisables (hors pente forte/marche), le tiers du milieu
    # inclus même s'il n'entre dans aucun ratio.
    hr_first = G.weighted_average(usable_first, "hr_bpm", resolution_s)
    hr_middle = G.weighted_average(usable_middle, "hr_bpm", resolution_s)
    hr_last = G.weighted_average(usable_last, "hr_bpm", resolution_s)

    gap_fade_pct = round((gap_first - gap_last) / gap_first * 100.0, 2) if gap_first else None
    ef_fade_pct = round((ef_first - ef_last) / ef_first * 100.0, 2) if ef_first else None
    return {
        "gap_fade_pct": gap_fade_pct,
        "ef_fade_pct": ef_fade_pct,
        "gap_first_third_ms": round(gap_first, 3),
        "gap_last_third_ms": round(gap_last, 3),
        "ef_first_third": round(ef_first, 4),
        "ef_last_third": round(ef_last, 4),
        "hr_first_third_bpm": round(hr_first, 1) if hr_first is not None else None,
        "hr_middle_third_bpm": round(hr_middle, 1) if hr_middle is not None else None,
        "hr_last_third_bpm": round(hr_last, 1) if hr_last is not None else None,
        "moving_duration_s": round(whole_moving_s, 1),
        "eligible": True,
        "reason": None,
        "reason_code": None,
        "applicable": True,
    }


def durability_report(samples: Sequence[dict], sport: Optional[str], *,
                       resolution_s: float = DEFAULT_RESOLUTION_S, **grade_kwargs) -> dict:
    """Rapport de durabilité (#48) d'une séance, à partir de ses échantillons
    normalisés (`arc_index.samples`/`samples_by_garmin_id`) et de son sport —
    API autonome qui calcule sa propre série GAP (voir
    `durability_report_from_series` pour réutiliser une série déjà calculée,
    ex. `arc_index.compute_metrics`)."""
    empty = {"gap_fade_pct": None, "ef_fade_pct": None, "gap_first_third_ms": None, "gap_last_third_ms": None,
              "ef_first_third": None, "ef_last_third": None, "hr_first_third_bpm": None,
              "hr_middle_third_bpm": None, "hr_last_third_bpm": None, "moving_duration_s": None,
              "eligible": False}
    if M.sport_family(sport) != "run":
        return {**empty, "reason": REASON_NOT_RUN_FAMILY, "reason_code": "not_run_family", "applicable": False}
    if not samples:
        return {**empty, "reason": REASON_NO_SAMPLES, "reason_code": "no_samples", "applicable": True}
    series = G.gap_sample_series(samples, **grade_kwargs)
    return durability_report_from_series(series, resolution_s=resolution_s)
