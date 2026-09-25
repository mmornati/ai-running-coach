#!/usr/bin/env python3
"""Allure ajustée à la pente — GAP (« Grade Adjusted Pace », #44, épopée #21).

Modèle : coût énergétique de la course selon la pente (**Minetti AE et al.,
2002**, « Energy cost of walking and running at extreme uphill and downhill
slopes », J Appl Physiol 93:1039–1046), mesuré sur tapis roulant jusqu'à ±45 % :

    C(i) = 155.4 i^5 − 30.4 i^4 − 43.3 i^3 + 46.3 i^2 + 19.5 i + 3.6   (J/kg/m)

`i` est la pente en fraction (0,10 = 10 %). Vitesse GAP = vitesse mesurée ×
C(pente) / C(0) : l'allure « équivalent plat » qui coûterait la même énergie
métabolique par mètre que l'allure réellement courue sur cette pente.

## Clampage — pente hors de la plage validée

`i` est clampé à ±`CLAMP_GRADE` (0,45, la borne haute de la plage étudiée par
Minetti et al.) avant d'entrer dans le polynôme : au-delà, celui-ci n'a jamais
été validé et diverge violemment (un polynôme de degré 5 extrapolé explose).
Ce n'est jamais une extrapolation, seulement un plafond documenté.

## Limite connue du modèle, documentée honnêtement (revue #44)

Minetti et al. 2002 modélise la course de LABORATOIRE (tapis, foulée
contrôlée). La littérature sur l'économie de course suggère que ce type de
modèle a tendance à SURESTIMER le gain métabolique des descentes très raides
en conditions réelles de trail (freinage excentrique, terrain technique,
appuis prudents, prudence tactique) — un phénomène qu'aucune montre ou
service grand public ne documente publiquement dans le détail de son propre
calcul. Ce module reste une **approximation du projet** fondée sur Minetti tel
quel — PAS une reproduction des marques Strava GAP, COROS Effort Pace ou Suunto NGP (citées à titre de repère uniquement dans `docs/marques.md`, jamais
une revendication d'équivalence : nous ne connaissons pas le détail de leurs
calculs propriétaires respectifs). Sur les fortes descentes (au-delà d'environ
-20 %), le GAP calculé ici est donc probablement trop optimiste (allure
« plat équivalent » surestimée) : #47 (efficacité en descente) et #58 (modèle
personnel pente → allure appris sur l'historique de l'athlète) pourront
affiner ce point avec des données réelles plutôt que le modèle de
laboratoire.

## API réutilisable, pure (sans SQLite ni disque) — pour #45, #47, #48, #58

- `minetti_cost(grade)` : coût C(i) après clamp — seule fonction que #58
  pourrait un jour remplacer par un modèle personnel pente → allure appris.
- `gap_speed_ms(speed_ms, grade)` : vitesse GAP d'un point.
- `gap_sample_series(samples, ...)` : `samples` (normalisés, triés ou non) →
  copie triée par `t_s`, augmentée de `"grade"` (`arc_elevation.grade_series`)
  et `"gap_speed_ms"` — la brique commune que #45 (découplage/Pa:HR calculé
  sur le GAP, jamais la vitesse brute — une côte ou une descente fausserait
  sinon la mesure), #47 (classes de pente en descente) et #48 (durabilité sur
  le GAP) réutilisent directement, sans recalculer pente/GAP chacun de leur
  côté.
- `weighted_average(series, key, resolution_s)` : moyenne pondérée par le
  temps, générique sur la clé (`"speed_ms"` ou `"gap_speed_ms"`) — même
  discipline que `arc_metrics._time_weighted_buckets` (chaque échantillon pèse
  jusqu'au suivant, plafonné à `resolution_s`, pour qu'un trou de signal ne
  fausse jamais une moyenne), réutilisable telle quelle par #45 (EF) et #48
  (fade).
- `activity_gap_pace_s_km(samples, ...)` : allure GAP (s/km) pondérée par le
  temps sur toute la séance, échantillons À L'ARRÊT EXCLUS par défaut (voir
  `STOPPED_SPEED_MS` et `ASSUMPTIONS["stopped_samples"]`) — comparable à
  l'allure sur temps de mouvement déjà affichée ailleurs dans le tableau de
  bord (`moving_duration_s`), jamais à l'allure sur temps total.
- `split_boundaries(splits)` / `split_gap_paces(samples, splits, ...)` :
  bornes de distance cumulée par split (`activity_split`) et allure GAP (s/km)
  par split — SUR TEMPS ÉCOULÉ, arrêts compris (voir
  `ASSUMPTIONS["stopped_samples"]`, cohérent avec l'affichage des splits par
  tour du tableau de bord, lui aussi sur temps écoulé).

Stdlib uniquement (CONTRIBUTING.md).
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent))
import arc_elevation as E  # noqa: E402

# Coefficients de Minetti et al. 2002, i^5 -> i^0 (J/kg/m).
MINETTI_COEFFS = (155.4, -30.4, -43.3, 46.3, 19.5, 3.6)
MINETTI_FLAT_COST = MINETTI_COEFFS[-1]  # C(0) = 3.6 J/kg/m, littéralement le terme constant

# Plage de validité approximative du modèle (tapis, jusqu'à ±45 %) : au-delà,
# la pente est CLAMPÉE avant d'entrer dans C(i), jamais extrapolée.
CLAMP_GRADE = 0.45

# Aligné sur `arc_samples.DEFAULT_RESOLUTION_S` : résolution nominale des
# échantillons sous-échantillonnés lus depuis `arc_index.samples`.
DEFAULT_RESOLUTION_S = 5.0

# En dessous de ce seuil (m/s), un échantillon est traité comme « à l'arrêt »
# (feu rouge, ravitaillement, pause) et exclu de la moyenne GAP DE LA SÉANCE
# ENTIÈRE — jamais du détail par split, qui reste volontairement sur temps
# écoulé (voir ASSUMPTIONS["stopped_samples"]). Volontairement bas : une
# marche en très forte montée (power hiking) descend rarement sous 0,2 m/s
# (720 m/h), donc reste comptée comme du mouvement, pas un arrêt.
STOPPED_SPEED_MS = 0.2

ASSUMPTIONS = {
    "model": (
        "Coût énergétique de la course selon la pente (Minetti AE et al., 2002, J Appl Physiol "
        "93:1039-1046, mesuré sur tapis roulant jusqu'à ±45 % de pente) : allure ajustée = "
        "allure mesurée multipliée par le rapport entre le coût énergétique de la pente réelle "
        "et celui du plat. Une pente au-delà de ±45 % est plafonnée à cette valeur avant le "
        "calcul, jamais extrapolée au-delà (le modèle n'a jamais été mesuré aussi loin). LIMITE "
        "CONNUE, documentée honnêtement : ce type de modèle de laboratoire a tendance à "
        "surestimer le gain métabolique des fortes descentes en conditions réelles de trail "
        "(freinage, terrain technique, prudence). Cette allure ajustée reste une approximation "
        "du projet fondée sur ce modèle, PAS une reproduction des calculs propriétaires (non "
        "documentés publiquement) des montres ou services du marché — voir docs/marques.md."
    ),
    "grade_source": (
        "La pente est calculée sur une fenêtre de distance (20 à 50 m), après un lissage de "
        "l'altitude par moyenne glissante — jamais une différence brute entre deux points "
        "rapprochés de 5 secondes, qui amplifierait le bruit du capteur barométrique sur une "
        "distance trop courte pour être fiable."
    ),
    "restricted_to_run_family": (
        "Allure ajustée calculée UNIQUEMENT pour les séances de la famille course à pied "
        "(course, trail, randonnée, marche) avec des données seconde par seconde disponibles — "
        "absente sinon (renforcement, vélo, ou séance sans ces données). Même restriction et "
        "même raison que le temps passé dans chaque zone de fréquence cardiaque (#43)."
    ),
    "split_distance_default": (
        "Un kilomètre (split) sans distance renseignée est supposé faire 1000 m plein pour "
        "calculer les bornes cumulées utilisées par l'allure ajustée par split — une "
        "approximation qui ne dégrade que CE split, jamais les autres (les bornes sont cumulées "
        "dans l'ordre). Par ailleurs, la distance totale déclarée par les splits peut légèrement "
        "différer de la distance réellement mesurée par la montre : le dernier split récupère "
        "alors l'écart plutôt que de perdre les derniers instants de la séance."
    ),
    "noise_robustness": (
        "Le modèle est sensible près du plat : un bruit de pente de quelques % sur un SEUL "
        "instant peut changer son allure ajustée de plusieurs %. Mais sur une moyenne (un split "
        "ou une séance entière), cette erreur s'annule presque complètement — c'est pourquoi la "
        "fiabilité de cette allure s'apprécie sur la durée, jamais instant par instant."
    ),
    "stopped_samples": (
        "L'allure ajustée de LA SÉANCE ENTIÈRE exclut les instants à l'arrêt (vitesse sous "
        "0,2 m/s environ — feu rouge, ravitaillement, pause), pour rester comparable à l'allure "
        "sur temps de mouvement déjà affichée ailleurs (jamais sur le temps total, qui inclurait "
        "les arrêts). L'allure ajustée PAR SPLIT (par kilomètre), elle, reste calculée sur le "
        "temps écoulé, arrêts compris — cohérent avec l'allure par kilomètre déjà affichée dans "
        "le tableau des splits, elle aussi sur temps écoulé : un arrêt au milieu d'un kilomètre "
        "ralentit donc son allure ajustée affichée, comme son allure brute."
    ),
}


def minetti_cost(grade: Optional[float]) -> Optional[float]:
    """Coût énergétique C(i) en J/kg/m (Minetti et al. 2002), `grade` clampé à
    ±`CLAMP_GRADE` avant évaluation du polynôme. `None` en entrée -> `None`
    (pente non calculable, voir `arc_elevation.grade_series`) — jamais un coût
    inventé."""
    if grade is None:
        return None
    i = max(-CLAMP_GRADE, min(CLAMP_GRADE, grade))
    c5, c4, c3, c2, c1, c0 = MINETTI_COEFFS
    return c5 * i**5 + c4 * i**4 + c3 * i**3 + c2 * i**2 + c1 * i + c0


def gap_speed_ms(speed_ms: Optional[float], grade: Optional[float]) -> Optional[float]:
    """Vitesse « allure ajustée à la pente » : vitesse mesurée × C(pente)/C(0).
    `None` si la vitesse ou la pente sont inconnues (jamais une vitesse
    inventée)."""
    if speed_ms is None or grade is None:
        return None
    cost = minetti_cost(grade)
    if cost is None:
        return None
    return speed_ms * (cost / MINETTI_FLAT_COST)


def gap_sample_series(samples: Sequence[dict], *, window_m: float = E.DEFAULT_GRADE_WINDOW_M,
                       min_window_m: float = E.DEFAULT_MIN_GRADE_WINDOW_M,
                       max_gap_s: float = E.DEFAULT_MAX_GAP_S,
                       smooth_taps: int = E.DEFAULT_SMOOTH_TAPS) -> List[dict]:
    """`samples` (normalisés, triés ou non) → copie triée par `t_s`, chaque dict
    augmenté de `"grade"` (fraction, voir `arc_elevation.grade_series`) et
    `"gap_speed_ms"` (`None` si pente ou vitesse manquante pour cet
    échantillon)."""
    series = E.grade_series(samples, window_m=window_m, min_window_m=min_window_m,
                             max_gap_s=max_gap_s, smooth_taps=smooth_taps)
    for s in series:
        s["gap_speed_ms"] = gap_speed_ms(s.get("speed_ms"), s.get("grade"))
    return series


def weighted_average(series: Sequence[dict], key: str, resolution_s: float = DEFAULT_RESOLUTION_S) -> Optional[float]:
    """Moyenne de `series[i][key]` pondérée par le temps (échantillons triés ou
    non par `t_s`, retriés ici) : chaque échantillon pèse `min(dt_vers_le_
    suivant, resolution_s)` — jamais `dt` brut, pour qu'un trou de signal
    (`arc_samples.ASSUMPTIONS["gaps"]`) ne fausse jamais la moyenne. Le dernier
    échantillon (pas de suivant) pèse `resolution_s`. Même discipline que
    `arc_metrics._time_weighted_buckets` (#43). `None` sans valeur exploitable."""
    ordered = sorted((s for s in series if s.get("t_s") is not None), key=lambda s: s["t_s"])
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
    return total_v / total_w if total_w > 0 else None


def _pace_s_km(speed_ms: Optional[float]) -> Optional[float]:
    return 1000.0 / speed_ms if speed_ms else None


def _moving_only(series: Sequence[dict]) -> List[dict]:
    """Échantillons dont la vitesse mesurée est au-dessus de `STOPPED_SPEED_MS`
    — voir `ASSUMPTIONS["stopped_samples"]` : un échantillon à l'arrêt (vitesse
    `None` ou sous le seuil) tirerait sinon la moyenne GAP de toute la séance
    vers une allure beaucoup plus lente qu'une pause n'en justifie, en
    contradiction avec l'allure sur temps de mouvement déjà affichée ailleurs."""
    return [s for s in series if (s.get("speed_ms") or 0.0) >= STOPPED_SPEED_MS]


def activity_gap_pace_from_series(series: Sequence[dict], *, resolution_s: float = DEFAULT_RESOLUTION_S,
                                   exclude_stopped: bool = True) -> Optional[float]:
    """Comme `activity_gap_pace_s_km`, mais à partir d'une série DÉJÀ augmentée
    par `gap_sample_series` — évite de recalculer la pente/le GAP deux fois pour
    la même activité quand l'appelant a aussi besoin du détail par split
    (`split_gap_paces_from_series`), voir `arc_index.compute_metrics`.

    `exclude_stopped` (défaut `True`) retire les instants à l'arrêt de la
    moyenne (voir `ASSUMPTIONS["stopped_samples"]`) — mettre `False` pour une
    moyenne sur le temps total, jamais le défaut car incomparable à l'allure
    sur temps de mouvement affichée ailleurs dans le tableau de bord."""
    if not series:
        return None
    moving = _moving_only(series) if exclude_stopped else series
    return _pace_s_km(weighted_average(moving, "gap_speed_ms", resolution_s))


def activity_gap_pace_s_km(samples: Sequence[dict], *, resolution_s: float = DEFAULT_RESOLUTION_S,
                            exclude_stopped: bool = True, **grade_kwargs) -> Optional[float]:
    """Allure GAP (secondes par km) pondérée par le temps sur toute la séance,
    échantillons à l'arrêt exclus par défaut (voir `exclude_stopped` sur
    `activity_gap_pace_from_series`). `None` sans échantillons, ou si aucune
    vitesse/pente exploitable nulle part."""
    if not samples:
        return None
    series = gap_sample_series(samples, **grade_kwargs)
    return activity_gap_pace_from_series(series, resolution_s=resolution_s, exclude_stopped=exclude_stopped)


def split_boundaries(splits: Sequence[dict], *, actual_total_m: Optional[float] = None) -> List[dict]:
    """Bornes de distance cumulée (m) par split, à partir des lignes
    `activity_split` (`km`, `distance_m` — voir `arc_contract.SPLIT_COLUMNS`),
    triées par `km` croissant. Un split sans `distance_m` exploitable (colonne
    optionnelle du contrat, ou valeur non positive) est supposé faire 1000 m
    plein (voir `ASSUMPTIONS["split_distance_default"]`). Rend une liste de
    `{"km", "start_m", "end_m"}`.

    `actual_total_m` (optionnel) : distance cumulée réellement observée dans
    les échantillons de la séance (FIT). Les distances déclarées par les
    splits (Markdown) peuvent légèrement dériver de celle-ci (arrondis,
    calibration GPS différente) : si la somme des splits est INFÉRIEURE à
    `actual_total_m`, la borne haute du DERNIER split est étendue jusqu'à
    `actual_total_m` plutôt que de laisser les derniers échantillons de la
    séance hors de toute plage (voir `ASSUMPTIONS["split_distance_default"]`).
    Si elle est supérieure (splits qui surestiment la distance réelle), rien à
    faire : la plage du dernier split ne contiendra simplement aucun
    échantillon au-delà de ce qui a été réellement enregistré."""
    ordered = sorted((s for s in splits if s.get("km") is not None), key=lambda s: s["km"])
    out = []
    start = 0.0
    for s in ordered:
        length = s.get("distance_m")
        if length is None or length <= 0:
            length = 1000.0
        end = start + length
        out.append({"km": s["km"], "start_m": start, "end_m": end})
        start = end
    if out and actual_total_m is not None and actual_total_m > out[-1]["end_m"]:
        out[-1]["end_m"] = actual_total_m
    return out


def split_gap_paces_from_series(series: Sequence[dict], splits: Sequence[dict], *,
                                 resolution_s: float = DEFAULT_RESOLUTION_S) -> Dict[int, Optional[float]]:
    """Comme `split_gap_paces`, mais à partir d'une série DÉJÀ augmentée par
    `gap_sample_series` — voir `activity_gap_pace_from_series` pour la même
    raison (éviter un recalcul en double pente/GAP pour la même activité).

    À la différence de l'allure GAP de la séance entière, les instants à
    l'arrêt ne sont JAMAIS exclus ici (voir `ASSUMPTIONS["stopped_samples"]`) :
    le GAP par split reste sur temps ÉCOULÉ, cohérent avec l'allure par split
    déjà affichée dans le tableau de bord (elle aussi sur temps écoulé, jamais
    sur temps de mouvement)."""
    if not series or not splits:
        return {}
    distances = [s["distance_m"] for s in series if s.get("distance_m") is not None]
    actual_total_m = max(distances) if distances else None
    bounds = split_boundaries(splits, actual_total_m=actual_total_m)
    out: Dict[int, Optional[float]] = {}
    last_index = len(bounds) - 1
    for i, b in enumerate(bounds):
        is_last = i == last_index
        in_range = []
        for s in series:
            d = s.get("distance_m")
            if d is None or d < b["start_m"]:
                continue
            if is_last:
                if d <= b["end_m"]:
                    in_range.append(s)
            elif d < b["end_m"]:
                in_range.append(s)
        out[b["km"]] = _pace_s_km(weighted_average(in_range, "gap_speed_ms", resolution_s)) if in_range else None
    return out


def split_gap_paces(samples: Sequence[dict], splits: Sequence[dict], *,
                     resolution_s: float = DEFAULT_RESOLUTION_S, **grade_kwargs) -> Dict[int, Optional[float]]:
    """Allure GAP (s/km) par split, indexée par `km` — pondérée par le temps sur
    les échantillons dont la distance cumulée tombe dans la borne du split
    (`split_boundaries` : `[start_m, end_m[`, DERNIER split inclusif à sa borne
    haute pour ne pas perdre le tout dernier échantillon de la séance). `{}` si
    `samples` ou `splits` est vide ; un split sans aucun échantillon exploitable
    dans sa plage rend `None` (jamais 0, jamais une exception)."""
    if not samples or not splits:
        return {}
    series = gap_sample_series(samples, **grade_kwargs)
    return split_gap_paces_from_series(series, splits, resolution_s=resolution_s)
