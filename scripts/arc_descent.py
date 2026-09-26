#!/usr/bin/env python3
"""Efficacité en descente, par classe de pente (#47, épopée #21).

## Pourquoi pas une détection de « descentes » façon `arc_climb.py`

`arc_climb.py` (#46) détecte des MONTÉES (zigzag à hystérésis, rognage, fusion
de creux) parce que la VAM a besoin d'une montée entière et continue (gain net
/ durée de CETTE montée précise). L'efficacité en descente demandée par #47
(« allure par classe de pente descendante, comparée au modèle théorique »)
n'a besoin de rien de tel : c'est un indicateur PAR ÉCHANTILLON (la pente
instantanée déjà calculée pour le GAP, `arc_gap.gap_sample_series`), agrégé
par classe de pente, jamais par segment détecté. Réutiliser une détection de
segments aurait ajouté de la complexité (rognage, fusion, trous de signal)
pour un problème qui n'en a pas besoin : contrairement au D+ d'une montée, la
distance/durée totale déjà passée dans chaque classe de pente ne dépend pas de
savoir où une « descente » commence ou finit au sens strict.

## Réutilisation — rien de recalculé

Ce module ne recalcule ni pente ni GAP : il consomme directement la sortie de
`arc_gap.gap_sample_series` (pente `arc_elevation.grade_series`, vitesse GAP
`arc_gap.gap_speed_ms`, elles-mêmes réutilisées telles quelles par
`arc_index.compute_metrics`, qui calcule déjà cette série pour le GAP/#44 et
le découplage/#45 — jamais un second calcul pour la même activité). Seul le
groupement par classe de pente descendante et l'agrégation pondérée par le
temps sont propres à ce module.

## Indicateur : efficacité en descente, PAS une comparaison brute au modèle

Comparer une allure de descente au modèle de Minetti (`arc_gap.py`, #44) en
valeur absolue n'aurait aucun sens : le modèle EST déjà connu pour surestimer
le gain métabolique des fortes descentes en conditions réelles de trail (voir
`arc_gap.ASSUMPTIONS["model"]`) — un coureur qui suivrait le modèle à la
lettre courrait plus vite qu'il n'est raisonnable en terrain technique.
L'indicateur retenu ici compare donc l'athlète À LUI-MÊME, via le modèle,
plutôt qu'au modèle en absolu :

    efficacité = vitesse GAP moyenne de la classe / vitesse GAP de référence
                 de la séance (le « plat équivalent » de CETTE sortie)

où la vitesse GAP moyenne de la classe est déjà `vitesse mesurée × C(pente)/
C(0)` (Minetti, voir `arc_gap.gap_speed_ms`), pondérée par le temps sur les
échantillons de cette classe. Algébriquement, ceci équivaut exactement à :

    efficacité = vitesse mesurée sur la classe / (référence plat × C(0)/C(pente))

c'est-à-dire au ratio demandé par l'issue (« vitesse réelle / (référence plat
× facteur de vitesse de Minetti C(0)/C(i)) ») — calculé ici en réutilisant la
vitesse GAP déjà produite par `arc_gap.py`, jamais un second calcul du
polynôme de Minetti.

**Lecture** : `efficacité = 1.0` signifie que l'athlète descend exactement à
l'allure que prédirait le modèle s'il maintenait le même effort métabolique
qu'à son allure plate de référence. Le modèle étant connu pour SURESTIMER le
bénéfice énergétique des fortes descentes (`arc_gap.ASSUMPTIONS["model"]`),
une valeur `< 1.0` sur les classes les plus raides est ATTENDUE et NORMALE
(prudence tactique, terrain technique, freinage excentrique) — ce n'est PAS
la preuve d'une mauvaise descente. **C'est la TENDANCE de cet indicateur dans
le temps, à classe de pente égale, qui est exploitable** (une valeur qui
progresse traduit une meilleure technique/confiance en descente), jamais sa
valeur absolue isolée — voir `ASSUMPTIONS["indicator"]`.

## Référence « plat » — allure GAP de la séance entière, pas des sections plates

`ASSUMPTIONS["reference"]` : la référence utilisée est l'allure GAP DE LA
SÉANCE ENTIÈRE (`arc_gap.activity_gap_pace_s_km`, déjà calculée à
l'indexation pour #44, jamais recalculée ici), pas seulement ses sections
plates. Une sortie de trail en montagne a souvent très peu d'échantillons
réellement plats (grade proche de 0) — les isoler donnerait une référence
bruitée sur trop peu de données, ou carrément absente sur un parcours sans
aucun plat. L'allure GAP de toute la séance est déjà, par construction, une
estimation de l'effort à allure « plat équivalent » (c'est la définition même
du GAP) : l'utiliser comme référence est donc cohérent et stable, au prix
d'un mélange avec l'effort fourni en montée (accepté, documenté).

## Seuils minimaux par classe — nommés, pas de valeur magique

Une classe de pente avec trop peu de données (quelques secondes de descente
raide croisées une fois) ne doit jamais produire une « efficacité » stable en
apparence mais statistiquement vide de sens. `MIN_CLASS_DURATION_S` (2 min) et
`MIN_CLASS_DISTANCE_M` (300 m) : une classe est retenue si SEULEMENT L'UN des
deux est atteint (300 m parcourus très vite peuvent prendre moins de 2 min à
allure de descente rapide ; 2 min à allure lente en terrain très technique
peuvent ne couvrir qu'un peu moins de 300 m) — voir `ASSUMPTIONS["thresholds"]`.

## Classes de pente descendante — alignées sur `arc_climb.GRADE_CLASSES` (#46)

#46 (`arc_climb.ASSUMPTIONS["grade_classes"]`) documentait explicitement que
ses classes de pente (`<5%`, `5-10%`, `10-15%`, `15-20%`, `>20%`, en valeur
absolue) pourraient être réutilisées telles quelles côté descente. Ce module
choisit le MIROIR de ces 4 classes non triviales (`-5/-10 %`, `-10/-15 %`,
`-15/-20 %`, `< -20 %`) plutôt que le découpage à 3 paliers suggéré dans le
texte de l'issue (`-5/-10`, `-10/-20`, `< -20`) — voir `ASSUMPTIONS
["grade_classes"]` pour la justification complète (cohérence visuelle entre
vue montée et vue descente du tableau de bord, un seul jeu de bornes à
maintenir). Une assertion au chargement du module vérifie que les bornes
restent identiques à `arc_climb.GRADE_CLASSES` — un futur changement des
bornes ascendantes fait échouer ce module au lieu de diverger en silence.

## API réutilisable, pure (sans SQLite ni disque)

- `grade_class_descent(grade)` : classe de pente descendante d'une pente
  signée (`None` si non descendante ou sous le seuil `MIN_DESCENT_GRADE`).
- `descent_speed_by_grade_class(series, ...)` : agrégation par classe sur une
  série DÉJÀ augmentée par `arc_gap.gap_sample_series` — seules les classes
  qualifiant `MIN_CLASS_DURATION_S`/`MIN_CLASS_DISTANCE_M` apparaissent.
- `descent_report(samples, sport, ...)` : rapport complet, restreint à la
  famille course à pied, TOUJOURS un dict avec une `reason` explicite en cas
  d'échec ou d'absence — jamais une exception ni un échec muet (même
  discipline que `arc_climb.climb_report`/`arc_decoupling.decoupling_report`).

Stdlib uniquement (CONTRIBUTING.md).
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Dict, Optional, Sequence, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
import arc_climb as VC  # noqa: E402
import arc_gap as G  # noqa: E402
import arc_metrics as M  # noqa: E402

# Seuil de classification (#47, mirroir de `arc_climb.MIN_CLIMB_AVG_GRADE`, #46) :
# une pente descendante moins raide que 5 % n'est pas classée (quasi-plat, hors
# sujet pour un KPI de descente).
MIN_DESCENT_GRADE = VC.MIN_CLIMB_AVG_GRADE

# Classes de pente descendante — MIROIR des classes ascendantes non triviales
# de `arc_climb.GRADE_CLASSES` (#46), voir la docstring du module pour la
# justification du choix (alignement #46 plutôt que le découpage à 3 paliers
# suggéré par le texte de l'issue #47) et `ASSUMPTIONS["grade_classes"]`.
DESCENT_GRADE_CLASSES: Tuple[Tuple[float, float, str], ...] = (
    (0.05, 0.10, "-5 à -10 %"),
    (0.10, 0.15, "-10 à -15 %"),
    (0.15, 0.20, "-15 à -20 %"),
    (0.20, float("inf"), "< -20 %"),
)
assert tuple((lo, hi) for lo, hi, _ in DESCENT_GRADE_CLASSES) == tuple(
    (lo, hi) for lo, hi, _ in VC.GRADE_CLASSES[1:]
), "DESCENT_GRADE_CLASSES a divergé des bornes de arc_climb.GRADE_CLASSES (#46) — voir ASSUMPTIONS['grade_classes']."

# Seuils minimaux par classe (#47, critère d'acceptation : « classes sans assez
# de données -> absentes ») — voir ASSUMPTIONS["thresholds"] : L'UN des deux
# suffit (jamais les deux exigés ensemble), contrairement au filtre de
# détection de montée (#46) qui exige gain ET pente.
MIN_CLASS_DURATION_S = 120.0  # 2 minutes
MIN_CLASS_DISTANCE_M = 300.0  # 300 mètres

ASSUMPTIONS = {
    "model": (
        "Aucun nouveau modèle physiologique : ce module réutilise tel quel le coût énergétique de "
        "Minetti AE et al. (2002, J Appl Physiol 93:1039-1046) déjà appliqué par le GAP (arc_gap.py, "
        "#44) — jamais un second calcul du polynôme, seulement la vitesse GAP déjà produite par "
        "`arc_gap.gap_sample_series`, agrégée par classe de pente descendante."
    ),
    "indicator": (
        "« Efficacité en descente » = vitesse GAP moyenne (pondérée par le temps) de la classe de "
        "pente / vitesse GAP de référence de la séance entière — algébriquement équivalent à (vitesse "
        "réelle mesurée sur la classe) / (vitesse de référence plate × C(0)/C(pente), le facteur de "
        "vitesse de Minetti), la formule demandée par l'issue #47, mais calculée ici en réutilisant la "
        "vitesse GAP déjà calculée par arc_gap.py plutôt qu'un second calcul du modèle. Une valeur de "
        "1,0 signifie que l'athlète maintient, en descente, le même effort métabolique (au sens du "
        "modèle de Minetti) qu'à son allure plate de référence. LIMITE CONNUE, documentée honnêtement "
        "(voir arc_gap.ASSUMPTIONS['model']) : le modèle de Minetti SURESTIME le gain métabolique des "
        "fortes descentes en conditions réelles de trail (freinage excentrique, terrain technique, "
        "prudence tactique) — une efficacité BIEN EN DESSOUS de 1,0 sur les classes les plus raides "
        "(< -20 %, notamment) est donc ATTENDUE et NORMALE, jamais la preuve d'une mauvaise descente. "
        "Cet indicateur n'a de sens qu'en TENDANCE, dans le temps, à classe de pente égale — jamais "
        "comme un score absolu à comparer entre athlètes ou à un seuil universel."
    ),
    "reference": (
        "La référence « plat » utilisée est l'allure GAP DE LA SÉANCE ENTIÈRE "
        "(`arc_gap.activity_gap_pace_s_km`, déjà calculée à l'indexation pour #44, jamais recalculée "
        "ici), pas seulement ses sections réellement plates : une sortie de trail en montagne peut "
        "n'avoir presque aucun échantillon à pente proche de zéro, rendant une référence limitée aux "
        "sections plates bruitée ou absente. L'allure GAP de toute la séance est par construction une "
        "estimation de l'effort à allure « plat équivalent », ce qui en fait une référence stable, au "
        "prix d'un mélange avec l'effort fourni en montée sur la même séance (assumé)."
    ),
    "thresholds": (
        f"Une classe de pente descendante n'est retenue que si SES échantillons couvrent au moins "
        f"{MIN_CLASS_DURATION_S:.0f} s de temps de mouvement OU {MIN_CLASS_DISTANCE_M:.0f} m de "
        "distance (l'un des deux suffit, jamais les deux exigés ensemble comme le filtre de détection "
        "de montée d'#46, qui répond à un besoin différent) — sous ces deux seuils, l'agrégat serait "
        "statistiquement trop bruité pour être exploitable. Seuils ronds, non calibrés sur un jeu de "
        "séances étiquetées."
    ),
    "moving_only": (
        "Les échantillons à l'arrêt (vitesse sous `arc_gap.STOPPED_SPEED_MS`) sont exclus de "
        "l'agrégation, comme pour l'allure GAP de la séance entière (`arc_gap.ASSUMPTIONS "
        "['stopped_samples']») — une pause en pleine descente (photo, prudence sur un passage "
        "technique) ne doit pas tirer la vitesse moyenne de sa classe vers le bas."
    ),
    "restricted_to_run_family": (
        "Calculé UNIQUEMENT pour les séances de la famille course à pied (arc_metrics.sport_family == "
        "\"run\" : course, trail, randonnée, marche) avec des échantillons FIT ingérés — même "
        "restriction que le GAP (#44), le découplage (#45) et la VAM (#46)."
    ),
    "grade_classes": (
        f"Classes de pente descendante retenues : {', '.join(label for _, _, label in DESCENT_GRADE_CLASSES)} "
        "— le MIROIR des 4 classes ascendantes non triviales d'`arc_climb.GRADE_CLASSES` (#46 : "
        "5-10 %, 10-15 %, 15-20 %, >20 %), jamais le découpage informel à 3 paliers suggéré par le "
        "texte de l'issue #47 (-5/-10, -10/-20, < -20). Choix justifié par la cohérence visuelle du "
        "tableau de bord (la vue « Montées » et une future vue « Descentes » partagent alors "
        "exactement les mêmes seuils de pente, lisibles côte à côte) et par la maintenance (un seul "
        "jeu de bornes à faire évoluer si besoin, jamais deux découpages différents à synchroniser) — "
        "#46 anticipait déjà explicitement cette réutilisation (« #47 pourra les réutiliser telles "
        "quelles »). Une pente descendante sous 5 % n'est pas classée (quasi-plat)."
    ),
}


def grade_class_descent(grade: Optional[float]) -> Optional[str]:
    """Classe de pente descendante (voir `DESCENT_GRADE_CLASSES`) d'une pente
    signée — `None` si `grade` est `None`, non descendante (>= 0) ou sous le
    seuil `MIN_DESCENT_GRADE` (quasi-plat). Même discipline d'arrondi que
    `arc_climb.grade_class` (au dixième de point de pourcentage, avant
    classement) — voir `arc_climb.ASSUMPTIONS["grade_classes"]`."""
    if grade is None or grade >= 0:
        return None
    g = round(abs(grade), 3)
    if g < MIN_DESCENT_GRADE:
        return None
    for lo, hi, label in DESCENT_GRADE_CLASSES:
        if lo <= g < hi:
            return label
    return DESCENT_GRADE_CLASSES[-1][2]


def descent_speed_by_grade_class(series: Sequence[dict], *,
                                  min_duration_s: float = MIN_CLASS_DURATION_S,
                                  min_distance_m: float = MIN_CLASS_DISTANCE_M,
                                  resolution_s: float = G.DEFAULT_RESOLUTION_S,
                                  reference_gap_speed_ms: Optional[float] = None) -> Dict[str, dict]:
    """Vitesse/allure moyenne (pondérée par le temps) par classe de pente
    descendante, sur une série DÉJÀ augmentée par `arc_gap.gap_sample_series`
    (clés `t_s`, `speed_ms`, `grade`, `gap_speed_ms`). Échantillons à l'arrêt
    exclus (voir `ASSUMPTIONS["moving_only"]`). Seules les classes qui
    atteignent `min_duration_s` OU `min_distance_m` apparaissent (voir
    `ASSUMPTIONS["thresholds"]`) — jamais une classe statistiquement vide de
    sens.

    Rend un dict `{label: {"count", "duration_moving_s", "distance_m",
    "mean_speed_ms", "mean_pace_s_km", "mean_gap_speed_ms", "efficiency"}}`,
    dans l'ordre croissant de `DESCENT_GRADE_CLASSES`. `efficiency` (voir
    `ASSUMPTIONS["indicator"]`) est `None` si `reference_gap_speed_ms` est
    `None` ou nul."""
    ordered = sorted(
        (s for s in series if s.get("t_s") is not None and (s.get("speed_ms") or 0.0) >= G.STOPPED_SPEED_MS),
        key=lambda s: s["t_s"])
    n = len(ordered)
    acc: Dict[str, dict] = {}
    for i, s in enumerate(ordered):
        cls = grade_class_descent(s.get("grade"))
        if cls is None:
            continue
        dt = ordered[i + 1]["t_s"] - s["t_s"] if i + 1 < n else resolution_s
        dt = max(0.0, min(dt, resolution_s))
        bucket = acc.setdefault(cls, {"dt": 0.0, "speed_dt": 0.0, "gap_speed_dt": 0.0,
                                       "distance_m": 0.0, "count": 0})
        bucket["count"] += 1
        bucket["dt"] += dt
        speed = s.get("speed_ms")
        if speed is not None:
            bucket["speed_dt"] += dt * speed
            # Distance approximée par vitesse x temps (jamais une différence de
            # `distance_m` cumulée, plus sensible à un trou de signal ou à un GPS
            # glitché) — cohérent avec la pondération temporelle du reste de
            # l'agrégat.
            bucket["distance_m"] += dt * speed
        gap_speed = s.get("gap_speed_ms")
        if gap_speed is not None:
            bucket["gap_speed_dt"] += dt * gap_speed
    out: Dict[str, dict] = {}
    for _lo, _hi, label in DESCENT_GRADE_CLASSES:
        b = acc.get(label)
        if b is None:
            continue
        if b["dt"] < min_duration_s and b["distance_m"] < min_distance_m:
            continue
        mean_speed = b["speed_dt"] / b["dt"] if b["dt"] > 0 else None
        mean_gap_speed = b["gap_speed_dt"] / b["dt"] if b["dt"] > 0 else None
        efficiency = (mean_gap_speed / reference_gap_speed_ms
                      if (mean_gap_speed is not None and reference_gap_speed_ms) else None)
        out[label] = {
            "count": b["count"],
            "duration_moving_s": round(b["dt"], 1),
            "distance_m": round(b["distance_m"], 1),
            "mean_speed_ms": round(mean_speed, 3) if mean_speed is not None else None,
            "mean_pace_s_km": round(1000.0 / mean_speed, 1) if mean_speed else None,
            "mean_gap_speed_ms": round(mean_gap_speed, 3) if mean_gap_speed is not None else None,
            "efficiency": round(efficiency, 3) if efficiency is not None else None,
        }
    return out


def descent_report(samples: Sequence[dict], sport: Optional[str], *,
                    min_duration_s: float = MIN_CLASS_DURATION_S,
                    min_distance_m: float = MIN_CLASS_DISTANCE_M,
                    resolution_s: float = G.DEFAULT_RESOLUTION_S, **grade_kwargs) -> dict:
    """Rapport complet d'efficacité en descente d'une séance (#47), à partir de
    ses échantillons normalisés et de son sport — API autonome, restreinte à
    la famille course à pied (voir `ASSUMPTIONS["restricted_to_run_family"]`).

    Rend TOUJOURS `{"classes", "reference_gap_pace_s_km", "reason"}` —
    `reason` explique une absence, jamais une exception ni un échec muet
    (même discipline que `arc_climb.climb_report`) : hors de la famille course
    à pied, pas d'échantillons FIT, GAP de référence indisponible (séance sans
    vitesse/pente exploitable), ou aucune classe de pente descendante avec
    assez de données. `classes: {}` avec une `reason` explicite dans TOUS les
    cas vides (contrairement à `climb_report`, où un parcours plat est un état
    normal sans `reason` — ici, l'absence de toute classe qualifiante est
    TOUJOURS documentée, critère d'acceptation de #47 : « classes sans assez
    de données -> absentes », jamais silencieusement)."""
    empty = {"classes": {}, "reference_gap_pace_s_km": None}
    if M.sport_family(sport) != "run":
        return {**empty, "reason": "hors de la famille course à pied (arc_metrics.sport_family), voir "
                                    "ASSUMPTIONS[\"restricted_to_run_family\"]"}
    if not samples:
        return {**empty, "reason": "aucun échantillon FIT ingéré pour cette séance"}
    series = G.gap_sample_series(samples, **grade_kwargs)
    reference_pace = G.activity_gap_pace_from_series(series, resolution_s=resolution_s)
    reference_speed = (1000.0 / reference_pace) if reference_pace else None
    classes = descent_speed_by_grade_class(
        series, min_duration_s=min_duration_s, min_distance_m=min_distance_m,
        resolution_s=resolution_s, reference_gap_speed_ms=reference_speed)
    reason = None
    if not classes:
        reason = ("allure GAP de référence indisponible pour cette séance (voir arc_gap.ASSUMPTIONS)"
                   if reference_speed is None else
                   "aucune classe de pente descendante avec assez de données sur cette séance "
                   "(voir ASSUMPTIONS[\"thresholds\"])")
    return {
        "classes": classes,
        "reference_gap_pace_s_km": round(reference_pace, 1) if reference_pace else None,
        "reason": reason,
    }
