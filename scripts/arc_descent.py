#!/usr/bin/env python3
"""Efficacité en descente, par classe de pente (#47, épopée #21).

## Pourquoi pas une détection de « descentes » façon `arc_climb.py`

`arc_climb.py` (#46) détecte des MONTÉES (zigzag à hystérésis, rognage, fusion
de creux) parce que la VAM a besoin d'une montée entière et continue (gain net
/ durée de CETTE montée précise). L'efficacité en descente demandée par #47
(« allure par classe de pente descendante, comparée au modèle théorique »)
n'a besoin de rien de tel : c'est un indicateur PAR ÉCHANTILLON (la pente
instantanée déjà calculée pour le GAP, `arc_gap.gap_sample_series`), agrégé
par classe de pente, jamais par segment détecté.

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
`arc_gap.ASSUMPTIONS["model"]`). L'indicateur retenu compare donc l'athlète À
LUI-MÊME, via le modèle, plutôt qu'au modèle en absolu.

Pour UN échantillon isolé, la vitesse GAP (`arc_gap.gap_speed_ms`, déjà
`vitesse mesurée × C(pente)/C(0)`) rend le ratio demandé par l'issue :

    efficacité(t) = vitesse(t) / (référence plate × C(0)/C(pente(t)))
                  = vitesse GAP(t) / référence plate

Sur une CLASSE de pente (plusieurs échantillons à pentes légèrement
différentes), la valeur retenue est la MOYENNE PONDÉRÉE PAR LE TEMPS de ce
ratio par échantillon — jamais le ratio d'une vitesse moyenne de classe à une
pente moyenne de classe unique (`C` n'étant pas linéaire, les deux ne
coïncident pas en général, inégalité de Jensen). Comme la référence est une
CONSTANTE de la séance (facteur qui sort de la moyenne), cela revient
exactement à :

    efficacité classe = (moyenne pondérée par le temps de vitesse GAP sur la
                          classe) / référence plate

ce qui EST ce que `descent_speed_by_grade_class` calcule (voir
`ASSUMPTIONS["indicator"]` pour la mise en garde complète — l'équivalence
algébrique ne vaut que parce que la référence ne varie pas d'un échantillon à
l'autre à l'intérieur d'une même classe).

**Lecture** : `efficacité = 1.0` signifie que l'athlète descend exactement à
l'allure que prédirait le modèle s'il maintenait le même effort métabolique
qu'à son allure plate de référence. Le modèle étant connu pour SURESTIMER le
bénéfice énergétique des fortes descentes (`arc_gap.ASSUMPTIONS["model"]`),
une valeur `< 1.0` sur les classes les plus raides est ATTENDUE et NORMALE —
ce n'est PAS la preuve d'une mauvaise descente. **C'est la TENDANCE de cet
indicateur dans le temps, à classe de pente égale, qui est exploitable**,
jamais sa valeur absolue isolée — voir `ASSUMPTIONS["indicator"]`.

## Référence « plat » — sections réellement plates de LA MÊME séance, repli sur le hors-forte-descente

`ASSUMPTIONS["reference"]` (revue de code, BLOQUANT corrigé) : une PREMIÈRE
VERSION de ce module utilisait l'allure GAP de LA SÉANCE ENTIÈRE comme
référence. Ceci mélange, dans la référence elle-même, l'effort fourni en
montée, sur le plat ET dans les descentes à mesurer — de sorte qu'une MÊME
descente (même pente, même vitesse) obtenait une efficacité DIFFÉRENTE selon
le reste du parcours (une sortie avec plus de montée, ou une descente plus
longue, changeait la référence et donc le résultat de la classe, sans que le
comportement en descente lui-même ait changé). La référence est donc
recalculée : allure GAP pondérée par le temps sur les échantillons EN
MOUVEMENT dont `|pente| < MIN_DESCENT_GRADE` (5 %, la même borne que le seuil
de classification), retenue seulement si elle couvre au moins
`MIN_REFERENCE_DURATION_S` (5 min). Si la séance n'a pas assez de plat
(profil de trail montagnard sans replat), repli sur l'allure GAP pondérée par
le temps de TOUS les échantillons HORS forte descente (`pente >
-MIN_DESCENT_GRADE`, donc plat ET montée, jamais les descentes elles-mêmes —
sinon la référence se contaminerait à nouveau par ce qu'elle doit mesurer),
avec le même seuil de durée minimale. Sans l'un ou l'autre, `reason`
explicite (`REASON_NO_REFERENCE`) — jamais une référence bruitée sur trop peu
de données. La source effectivement utilisée (`"flat"` ou `"non_descent"`)
est exposée telle quelle (`reference_source`, activité ET API) : jamais
cachée à l'utilisateur, une référence de repli reste moins fiable qu'une
référence plate franche.

## Seuils minimaux par classe — nommés, pas de valeur magique

Une classe de pente avec trop peu de données (quelques secondes de descente
raide croisées une fois) ne doit jamais produire une « efficacité » stable en
apparence mais statistiquement vide de sens. `MIN_CLASS_DURATION_S` (2 min) et
`MIN_CLASS_DISTANCE_M` (300 m) : une classe est retenue si SEULEMENT L'UN des
deux est atteint — voir `ASSUMPTIONS["thresholds"]`.

## Classes de pente descendante — alignées sur `arc_climb.GRADE_CLASSES` (#46), sauf au-delà de -20 %

#46 documentait explicitement que ses classes de pente pourraient être
réutilisées telles quelles côté descente ; ce module reprend le MIROIR des 3
classes ascendantes intermédiaires (`5-10 %` -> `-5 à -10 %`, etc.), voir
`ASSUMPTIONS["grade_classes"]`. Au-delà de -20 %, en revanche, la classe
ascendante `>20%` n'a PAS de miroir direct valable : le coût énergétique de
Minetti n'est PAS monotone en descente (contrairement à la montée) — il
DIMINUE jusqu'à un minimum vers -18 % (C(i)/C(0) ≈ 0,495) puis RE-AUGMENTE
(-25 % : 0,562 ; -30 % : 0,684 ; -45 %, le plafond du modèle : 1,12, DÉJÀ
au-dessus du coût du plat). Un unique panier `< -20 %` mélangerait donc des
pentes aux prédictions de modèle radicalement différentes (proches du
bénéfice maximal à -20 %, quasi neutres à -30 %, pénalisantes à -45 %) : la
classe se lirait alors comme un indicateur du RELIEF traversé (quelle pente
moyenne le panier a-t-il vu ce jour-là) plutôt que de l'EFFICACITÉ de
l'athlète. Ce module scinde donc ce panier en deux : `-20 à -30 %` et
`< -30 %` (voir `ASSUMPTIONS["grade_classes"]`), et expose en plus la pente
MOYENNE pondérée par le temps de chaque classe (`mean_grade`) pour que le
tableau de bord puisse toujours montrer, à côté du libellé de la classe, la
pente réellement rencontrée.

## API réutilisable, pure (sans SQLite ni disque)

- `grade_class_descent(grade)` : classe de pente descendante d'une pente
  signée (`None` si non descendante ou sous le seuil `MIN_DESCENT_GRADE`).
- `reference_gap_speed_ms(series, ...)` : référence « plat » de la séance
  (voir ci-dessus), rend `(vitesse_ms, source)`.
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
# sujet pour un KPI de descente) — AUSSI la borne de la référence « plate »
# (`reference_gap_speed_ms`, voir la docstring du module).
MIN_DESCENT_GRADE = VC.MIN_CLIMB_AVG_GRADE

# Classes de pente descendante — MIROIR des 3 classes ascendantes intermédiaires
# de `arc_climb.GRADE_CLASSES` (#46), scindées différemment au-delà de -20 % (voir
# la docstring du module : le coût de Minetti n'est pas monotone en descente,
# contrairement à la montée — un panier ouvert unique au-delà de -20 % mélangerait
# des pentes aux prédictions radicalement différentes).
DESCENT_GRADE_CLASSES: Tuple[Tuple[float, float, str], ...] = (
    (0.05, 0.10, "-5 à -10 %"),
    (0.10, 0.15, "-10 à -15 %"),
    (0.15, 0.20, "-15 à -20 %"),
    (0.20, 0.30, "-20 à -30 %"),
    (0.30, float("inf"), "< -30 %"),
)
# Seules les 3 classes intermédiaires (5-10/10-15/15-20 %) ont un miroir direct :
# voir ASSUMPTIONS["grade_classes"] pour la scission volontaire au-delà de -20 %.
assert tuple((lo, hi) for lo, hi, _ in DESCENT_GRADE_CLASSES[:3]) == tuple(
    (lo, hi) for lo, hi, _ in VC.GRADE_CLASSES[1:4]
), "DESCENT_GRADE_CLASSES a divergé des bornes de arc_climb.GRADE_CLASSES (#46) — voir ASSUMPTIONS['grade_classes']."

# Seuils minimaux par classe (#47, critère d'acceptation : « classes sans assez
# de données -> absentes ») — voir ASSUMPTIONS["thresholds"] : L'UN des deux
# suffit (jamais les deux exigés ensemble), contrairement au filtre de
# détection de montée (#46) qui exige gain ET pente.
MIN_CLASS_DURATION_S = 120.0  # 2 minutes
MIN_CLASS_DISTANCE_M = 300.0  # 300 mètres

# Durée minimale pour que la référence « plat » (voir `reference_gap_speed_ms`)
# soit jugée exploitable, plate ou de repli — voir ASSUMPTIONS["reference"].
# Plus large que `MIN_CLASS_DURATION_S` : une référence bruitée fausserait
# l'efficacité de TOUTES les classes de la séance, pas d'une seule.
MIN_REFERENCE_DURATION_S = 300.0  # 5 minutes

# Raisons canoniques (#47, revue de code, nit) — un seul texte par cas, réutilisé
# tel quel par `arc_index.activity_descent_report` et `arc_serve.api_activity_descent`
# plutôt que trois formulations indépendantes qui pourraient dériver l'une de
# l'autre au fil des futures modifications.
REASON_NOT_RUN_FAMILY = ("hors de la famille course à pied (arc_metrics.sport_family), voir "
                          "arc_descent.ASSUMPTIONS[\"restricted_to_run_family\"]")
REASON_NO_SAMPLES = "aucun échantillon FIT ingéré pour cette séance"
REASON_NO_REFERENCE = ("aucune allure GAP de référence disponible pour cette séance (ni section "
                        "plate, ni section hors forte descente couvrant au moins "
                        f"{MIN_REFERENCE_DURATION_S / 60:.0f} min — voir ASSUMPTIONS[\"reference\"])")
REASON_NO_QUALIFYING_CLASS = ("aucune classe de pente descendante avec assez de données sur cette "
                               "séance (voir ASSUMPTIONS[\"thresholds\"])")
REASON_UNKNOWN_ACTIVITY = "aucune activité indexée pour ce garmin_activity_id"

ASSUMPTIONS = {
    "model": (
        "Aucun nouveau modèle physiologique : ce module réutilise tel quel le coût énergétique de "
        "Minetti AE et al. (2002, J Appl Physiol 93:1039-1046) déjà appliqué par le GAP (arc_gap.py, "
        "#44) — jamais un second calcul du polynôme, seulement la vitesse GAP déjà produite par "
        "`arc_gap.gap_sample_series`, agrégée par classe de pente descendante."
    ),
    "indicator": (
        "« Efficacité en descente » = moyenne pondérée par le temps du ratio PAR ÉCHANTILLON (vitesse "
        "GAP de l'échantillon / référence plate de la séance) sur les échantillons d'une classe — "
        "PRÉCISION IMPORTANTE (revue de code) : ceci équivaut algébriquement à (moyenne pondérée par "
        "le temps de la vitesse GAP sur la classe) / référence UNIQUEMENT parce que la référence est "
        "une CONSTANTE de la séance qui sort de la moyenne — ce n'est PAS la même chose que (vitesse "
        "moyenne mesurée sur la classe) / (référence × C(0)/C(pente MOYENNE de la classe)), un calcul "
        "à pente unique qui ne coïnciderait pas en général avec la vraie moyenne pondérée du fait de la "
        "non-linéarité de C (inégalité de Jensen) — voir la docstring du module pour le détail. Une "
        "valeur de 1,0 signifie que l'athlète maintient, en moyenne sur la classe, le même effort "
        "métabolique (au sens du modèle de Minetti) qu'à son allure plate de référence. LIMITE CONNUE, "
        "documentée honnêtement (voir arc_gap.ASSUMPTIONS['model']) : le modèle de Minetti SURESTIME le "
        "gain métabolique des fortes descentes en conditions réelles de trail (freinage excentrique, "
        "terrain technique, prudence tactique) — une efficacité BIEN EN DESSOUS de 1,0 sur les classes "
        "les plus raides est donc ATTENDUE et NORMALE, jamais la preuve d'une mauvaise descente. Cet "
        "indicateur n'a de sens qu'en TENDANCE, dans le temps, à classe de pente égale — jamais comme un "
        "score absolu à comparer entre athlètes ou à un seuil universel."
    ),
    "reference": (
        "BLOQUANT (revue de code) : une première version utilisait l'allure GAP DE LA SÉANCE ENTIÈRE "
        "comme référence — ceci mélange dans la référence elle-même l'effort de montée, de plat ET des "
        "descentes à mesurer, si bien qu'une MÊME descente (même pente, même vitesse) obtenait une "
        "efficacité différente selon le reste du parcours (mesuré : 0,68 à 0,89 pour une descente "
        "identique selon le relief environnant), et une descente plus longue changeait sa PROPRE "
        "efficacité en pesant plus lourd dans sa propre référence. La référence est donc désormais "
        "l'allure GAP pondérée par le temps, échantillons en mouvement seulement, restreinte aux "
        "échantillons dont `|pente| < MIN_DESCENT_GRADE` (5 %) — retenue seulement si elle couvre au "
        "moins `MIN_REFERENCE_DURATION_S` (5 min). À défaut (profil de trail montagnard sans replat "
        "suffisant), repli sur l'allure GAP pondérée par le temps de TOUS les échantillons HORS forte "
        "descente (`pente > -MIN_DESCENT_GRADE`, donc plat ET montée, JAMAIS les descentes elles-mêmes, "
        "qui contamineraient à nouveau la référence par ce qu'elle doit mesurer), même seuil de durée. "
        "Sans l'un ou l'autre : `REASON_NO_REFERENCE`, jamais une référence bruitée sur trop peu de "
        "données. La source retenue (`\"flat\"` ou `\"non_descent\"`) est exposée telle quelle "
        "(`reference_source`) — une référence de repli reste moins fiable qu'une référence plate franche, "
        "jamais cachée à l'utilisateur."
    ),
    "thresholds": (
        f"Une classe de pente descendante n'est retenue que si SES échantillons couvrent au moins "
        f"{MIN_CLASS_DURATION_S:.0f} s de temps de mouvement OU {MIN_CLASS_DISTANCE_M:.0f} m de "
        "distance (l'un des deux suffit, jamais les deux exigés ensemble comme le filtre de détection "
        "de montée d'#46, qui répond à un besoin différent) — sous ces deux seuils, l'agrégat serait "
        f"statistiquement trop bruité pour être exploitable. La référence « plat » elle-même exige "
        f"{MIN_REFERENCE_DURATION_S:.0f} s (voir ASSUMPTIONS['reference']) : plus large, une référence "
        "bruitée fausserait l'efficacité de TOUTES les classes de la séance, pas d'une seule. Seuils "
        "ronds, non calibrés sur un jeu de séances étiquetées."
    ),
    "moving_only": (
        "Les échantillons à l'arrêt (vitesse sous `arc_gap.STOPPED_SPEED_MS`) sont exclus de "
        "l'agrégation ET de la référence, comme pour l'allure GAP de la séance entière (`arc_gap."
        "ASSUMPTIONS['stopped_samples']`) — une pause en pleine descente (photo, prudence sur un "
        "passage technique) ne doit pas tirer la vitesse moyenne de sa classe vers le bas."
    ),
    "restricted_to_run_family": (
        "Calculé UNIQUEMENT pour les séances de la famille course à pied (arc_metrics.sport_family == "
        "\"run\" : course, trail, randonnée, marche) avec des échantillons FIT ingérés — même "
        "restriction que le GAP (#44), le découplage (#45) et la VAM (#46)."
    ),
    "grade_classes": (
        f"Classes de pente descendante retenues : {', '.join(label for _, _, label in DESCENT_GRADE_CLASSES)} "
        "— les 3 classes intermédiaires (5-10/10-15/15-20 %) sont le MIROIR direct des classes "
        "ascendantes correspondantes d'`arc_climb.GRADE_CLASSES` (#46), qui anticipait explicitement "
        "cette réutilisation. Au-delà de -20 %, en revanche, PAS de miroir direct de la classe "
        "ascendante `>20%` : le coût énergétique de Minetti N'EST PAS monotone en descente (contrairement "
        "à la montée, où C(i) croît sans cesse avec la pente) — il DIMINUE jusqu'à un minimum vers -18 % "
        "(C(i)/C(0) ≈ 0,495, le point où le modèle prédit le plus grand bénéfice) puis RE-AUGMENTE : "
        "-20 % ≈ 0,50, -25 % ≈ 0,562, -30 % ≈ 0,684, -45 % (plafond du modèle, `arc_gap.CLAMP_GRADE`) ≈ "
        "1,12, DÉJÀ AU-DESSUS du coût du plat. Un panier ouvert unique `< -20 %` mélangerait donc des "
        "pentes aux prédictions radicalement différentes (bénéfice quasi maximal à -20 %, quasi neutre "
        "à -30 %, pénalisant à -45 %) : sa valeur refléterait alors le RELIEF traversé plutôt que "
        "l'EFFICACITÉ de l'athlète. Scindé en `-20 à -30 %` et `< -30 %` en conséquence — asymétrie "
        "ASSUMÉE avec la VAM (#46), qui n'a pas ce problème (montée strictement monotone). "
        "`mean_grade` (pente moyenne pondérée par le temps de la classe, voir "
        "`descent_speed_by_grade_class`) reste exposé pour que le tableau de bord montre la pente "
        "réellement rencontrée à côté du libellé, y compris à l'intérieur d'un panier large. Une pente "
        "descendante sous 5 % n'est pas classée (quasi-plat)."
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


def _weighted_mean_and_duration(ordered: Sequence[dict], key: str,
                                 resolution_s: float) -> Tuple[Optional[float], float]:
    """Moyenne de `ordered[i][key]` pondérée par le temps, et durée totale
    pondérée — même discipline que `arc_gap.weighted_average` (chaque
    échantillon pèse `min(dt_vers_le_suivant, resolution_s)`, jamais `dt` brut,
    pour qu'un trou de signal ne fausse jamais ni la moyenne ni la durée), mais
    rend AUSSI la durée totale (`arc_gap.weighted_average` ne rend que la
    moyenne) — nécessaire ici pour vérifier `MIN_REFERENCE_DURATION_S`.
    `ordered` doit déjà être trié par `t_s` croissant. `(None, 0.0)` sans
    valeur exploitable."""
    n = len(ordered)
    total_w = 0.0
    total_v = 0.0
    for i, s in enumerate(ordered):
        v = s.get(key)
        if v is None:
            continue
        dt = ordered[i + 1]["t_s"] - s["t_s"] if i + 1 < n else resolution_s
        dt = max(0.0, min(dt, resolution_s))
        total_w += dt
        total_v += dt * v
    mean = total_v / total_w if total_w > 0 else None
    return mean, total_w


def reference_gap_speed_ms(series: Sequence[dict], *,
                            min_duration_s: float = MIN_REFERENCE_DURATION_S,
                            resolution_s: float = G.DEFAULT_RESOLUTION_S
                            ) -> Tuple[Optional[float], Optional[str]]:
    """Référence « plat » de la séance pour l'efficacité en descente — voir la
    docstring du module et `ASSUMPTIONS["reference"]` pour la justification
    complète (BLOQUANT, revue de code : ne JAMAIS utiliser l'allure GAP de
    toute la séance, qui se contaminerait avec l'effort des descentes à
    mesurer elles-mêmes).

    `series` DÉJÀ augmentée par `arc_gap.gap_sample_series`. Échantillons à
    l'arrêt exclus (voir `ASSUMPTIONS["moving_only"]`). Essaie d'abord les
    échantillons réellement plats (`|pente| < MIN_DESCENT_GRADE`) ; à défaut
    (durée insuffisante), replie sur TOUS les échantillons hors forte descente
    (`pente > -MIN_DESCENT_GRADE`, donc plat ET montée, jamais les descentes).
    Rend `(vitesse_ms, source)` — `source` vaut `"flat"` ou `"non_descent"` ;
    `(None, None)` si ni l'un ni l'autre n'atteint `min_duration_s`."""
    moving = sorted(
        (s for s in series if s.get("t_s") is not None and (s.get("speed_ms") or 0.0) >= G.STOPPED_SPEED_MS),
        key=lambda s: s["t_s"])
    flat = [s for s in moving if s.get("grade") is not None and abs(s["grade"]) < MIN_DESCENT_GRADE]
    mean, duration = _weighted_mean_and_duration(flat, "gap_speed_ms", resolution_s)
    if mean is not None and duration >= min_duration_s:
        return mean, "flat"
    non_descent = [s for s in moving if s.get("grade") is not None and s["grade"] > -MIN_DESCENT_GRADE]
    mean, duration = _weighted_mean_and_duration(non_descent, "gap_speed_ms", resolution_s)
    if mean is not None and duration >= min_duration_s:
        return mean, "non_descent"
    return None, None


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
    "mean_speed_ms", "mean_pace_s_km", "mean_gap_speed_ms", "mean_grade",
    "efficiency"}}`, dans l'ordre croissant de `DESCENT_GRADE_CLASSES`.
    `mean_grade` (fraction signée) est la pente RÉELLEMENT rencontrée en
    moyenne sur la classe (voir `ASSUMPTIONS["grade_classes"]` : utile
    notamment sur les paniers larges `-20 à -30 %`/`< -30 %`). `efficiency`
    (voir `ASSUMPTIONS["indicator"]`) est la moyenne pondérée par le temps du
    ratio PAR ÉCHANTILLON vitesse GAP / référence — algébriquement égale à
    (moyenne pondérée de la vitesse GAP sur la classe) / référence puisque la
    référence est constante sur la séance — `None` si `reference_gap_speed_ms`
    est `None` ou nul."""
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
                                       "grade_dt": 0.0, "distance_m": 0.0, "count": 0})
        bucket["count"] += 1
        bucket["dt"] += dt
        bucket["grade_dt"] += dt * s["grade"]
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
        mean_grade = b["grade_dt"] / b["dt"] if b["dt"] > 0 else None
        efficiency = (mean_gap_speed / reference_gap_speed_ms
                      if (mean_gap_speed is not None and reference_gap_speed_ms) else None)
        out[label] = {
            "count": b["count"],
            "duration_moving_s": round(b["dt"], 1),
            "distance_m": round(b["distance_m"], 1),
            "mean_speed_ms": round(mean_speed, 3) if mean_speed is not None else None,
            "mean_pace_s_km": round(1000.0 / mean_speed, 1) if mean_speed else None,
            "mean_gap_speed_ms": round(mean_gap_speed, 3) if mean_gap_speed is not None else None,
            "mean_grade": round(mean_grade, 4) if mean_grade is not None else None,
            "efficiency": round(efficiency, 3) if efficiency is not None else None,
        }
    return out


def descent_report(samples: Sequence[dict], sport: Optional[str], *,
                    min_duration_s: float = MIN_CLASS_DURATION_S,
                    min_distance_m: float = MIN_CLASS_DISTANCE_M,
                    reference_min_duration_s: float = MIN_REFERENCE_DURATION_S,
                    resolution_s: float = G.DEFAULT_RESOLUTION_S, **grade_kwargs) -> dict:
    """Rapport complet d'efficacité en descente d'une séance (#47), à partir de
    ses échantillons normalisés et de son sport — API autonome, restreinte à
    la famille course à pied (voir `ASSUMPTIONS["restricted_to_run_family"]`).

    Rend TOUJOURS `{"classes", "reference_gap_pace_s_km", "reference_source",
    "reason", "reason_code", "applicable"}` — `reason` explique une absence en
    français, jamais une exception ni un échec muet (même discipline que
    `arc_climb.climb_report`) : hors de la famille course à pied, pas
    d'échantillons FIT, GAP de référence indisponible (voir
    `ASSUMPTIONS["reference"]`), ou aucune classe de pente descendante avec
    assez de données. `classes: {}` avec une `reason` explicite dans TOUS les
    cas vides (contrairement à `climb_report`, où un parcours plat est un état
    normal sans `reason` — ici, l'absence de toute classe qualifiante est
    TOUJOURS documentée, critère d'acceptation de #47 : « classes sans assez
    de données -> absentes », jamais silencieusement). `reason_code` (revue de
    code, nit) est la contrepartie STABLE et NON localisée de `reason` — un des
    littéraux `"not_run_family"`/`"no_samples"`/`"no_reference"`/
    `"no_qualifying_class"`/`None` — pour qu'un appelant (l'UI notamment) ne
    dépende jamais d'un `test()` sur le texte français, fragile aux
    reformulations. `applicable` (bool) : `False` UNIQUEMENT quand la séance
    n'a structurellement jamais pu avoir de descente classée (hors famille
    course à pied) — `True` sinon, y compris pour une absence de données."""
    empty = {"classes": {}, "reference_gap_pace_s_km": None, "reference_source": None}
    if M.sport_family(sport) != "run":
        return {**empty, "reason": REASON_NOT_RUN_FAMILY, "reason_code": "not_run_family", "applicable": False}
    if not samples:
        return {**empty, "reason": REASON_NO_SAMPLES, "reason_code": "no_samples", "applicable": True}
    series = G.gap_sample_series(samples, **grade_kwargs)
    reference_speed, reference_source = reference_gap_speed_ms(
        series, min_duration_s=reference_min_duration_s, resolution_s=resolution_s)
    # Sans référence, un panier de classe resterait rempli (count/vitesse/allure
    # calculables) mais avec `efficiency: None` partout — un rapport dont le SEUL
    # but est l'efficacité n'a alors rien d'exploitable : `classes` reste `{}`,
    # jamais une liste de classes à l'efficacité muette, pour que `reason_code`
    # (`"no_reference"`) reflète honnêtement l'absence totale de résultat plutôt
    # que de laisser croire à des classes partiellement calculées.
    classes = (descent_speed_by_grade_class(
        series, min_duration_s=min_duration_s, min_distance_m=min_distance_m,
        resolution_s=resolution_s, reference_gap_speed_ms=reference_speed)
        if reference_speed is not None else {})
    reason = reason_code = None
    if not classes:
        if reference_speed is None:
            reason, reason_code = REASON_NO_REFERENCE, "no_reference"
        else:
            reason, reason_code = REASON_NO_QUALIFYING_CLASS, "no_qualifying_class"
    reference_pace = (1000.0 / reference_speed) if reference_speed else None
    return {
        "classes": classes,
        "reference_gap_pace_s_km": round(reference_pace, 1) if reference_pace else None,
        "reference_source": reference_source,
        "reason": reason,
        "reason_code": reason_code,
        "applicable": True,
    }
