#!/usr/bin/env python3
"""Allure ajustée à la pente — GAP (« Grade Adjusted Pace », #44, épopée #21).

Modèle : coût énergétique de la course selon la pente (**Minetti et al.,
2002**, « Energy cost of walking and running at extreme uphill and downhill
slopes », J Appl Physiol), mesuré sur tapis roulant jusqu'à ±45 % :

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
contrôlée) — il est connu pour SURESTIMER le gain métabolique des descentes
très raides en conditions réelles de trail (freinage excentrique, terrain
technique, appuis prudents, prudence tactique) : Strava documente d'ailleurs
un modèle propriétaire différent pour cette même raison (voir
`docs/marques.md`). Ce module reste une **approximation du projet** fondée sur
Minetti tel quel — PAS une reproduction de Strava GAP, COROS Effort Pace ou
Suunto NGP (marques citées à titre de repère uniquement dans la documentation,
jamais une revendication d'équivalence). Sur les fortes descentes (au-delà
d'environ -20 %), le GAP calculé ici est donc probablement trop optimiste
(allure « plat équivalent » surestimée) : #47 (efficacité en descente) et #58
(modèle personnel pente → allure appris sur l'historique de l'athlète)
pourront affiner ce point avec des données réelles plutôt que le modèle de
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
  temps sur toute la séance.
- `split_boundaries(splits)` / `split_gap_paces(samples, splits, ...)` :
  bornes de distance cumulée par split (`activity_split`) et allure GAP (s/km)
  par split.

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

ASSUMPTIONS = {
    "model": (
        "Coût énergétique de Minetti et al. 2002 (course sur tapis, pentes mesurées jusqu'à "
        "±45 %) : C(i) = 155.4 i^5 − 30.4 i^4 − 43.3 i^3 + 46.3 i^2 + 19.5 i + 3.6 (J/kg/m). "
        "GAP = vitesse mesurée × C(pente)/C(0). Pente clampée à ±45 % (CLAMP_GRADE) avant "
        "d'entrer dans le polynôme, qui diverge violemment hors de cette plage — jamais une "
        "extrapolation. LIMITE CONNUE, documentée honnêtement : Minetti SURESTIME le gain "
        "métabolique des fortes descentes en conditions réelles de trail (freinage excentrique, "
        "terrain technique — Strava documente un modèle propriétaire différent pour cette même "
        "raison, voir docs/marques.md). Ce module reste une approximation du projet fondée sur "
        "Minetti tel quel, PAS une reproduction de Strava GAP / COROS Effort Pace / Suunto NGP "
        "(marques citées à titre de repère, voir docs/marques.md)."
    ),
    "grade_source": (
        "La pente vient de `arc_elevation.grade_series` : fenêtre de distance (20-50 m, "
        "altitude lissée par moyenne glissante), jamais une différence brute entre deux "
        "échantillons de 5 s (bruit barométrique amplifié sur une distance trop courte). Voir "
        "`arc_elevation.ASSUMPTIONS` pour la méthode complète."
    ),
    "restricted_to_run_family": (
        "GAP calculé UNIQUEMENT pour les activités de la famille course à pied "
        "(`arc_metrics.sport_family(sport) == \"run\"` : course, trail, randonnée, marche) "
        "AVEC des échantillons FIT ingérés — `None` sinon (renforcement, vélo, ou séance sans "
        "FIT associé). Même restriction et même raison que le temps en zone FC (#43, voir "
        "`arc_metrics.ASSUMPTIONS[\"hr_zones\"]`)."
    ),
    "split_distance_default": (
        "Un split (`activity_split`) sans `distance_m` (colonne optionnelle du contrat "
        "```arc```) est supposé faire 1000 m plein pour calculer les bornes de distance "
        "cumulée du GAP par split (`split_boundaries`) — approximation documentée qui ne "
        "dégrade que le GAP de CE split (les bornes sont cumulées séquentiellement, l'erreur "
        "ne se propage donc jamais aux autres splits)."
    ),
    "noise_robustness": (
        "Le modèle est sensible près du plat (dérivée dC/di en 0 ≈ 19,5 J/kg/m par unité de "
        "pente) : un bruit de pente de quelques % sur un SEUL échantillon peut changer sa "
        "vitesse GAP instantanée de plusieurs %. Agrégé (moyenne pondérée par le temps sur un "
        "split ou une séance entière), l'erreur résiduelle est du second ordre et négligeable "
        "pour un bruit raisonnable (voir `arc_elevation.ASSUMPTIONS[\"noise_robustness\"]`) — "
        "c'est pourquoi les critères d'acceptation de #44 portent sur le GAP AGRÉGÉ d'un plat "
        "bruité, jamais sur chaque échantillon individuellement."
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


def activity_gap_pace_from_series(series: Sequence[dict], *, resolution_s: float = DEFAULT_RESOLUTION_S) -> Optional[float]:
    """Comme `activity_gap_pace_s_km`, mais à partir d'une série DÉJÀ augmentée
    par `gap_sample_series` — évite de recalculer la pente/le GAP deux fois pour
    la même activité quand l'appelant a aussi besoin du détail par split
    (`split_gap_paces_from_series`), voir `arc_index.compute_metrics`."""
    if not series:
        return None
    return _pace_s_km(weighted_average(series, "gap_speed_ms", resolution_s))


def activity_gap_pace_s_km(samples: Sequence[dict], *, resolution_s: float = DEFAULT_RESOLUTION_S,
                            **grade_kwargs) -> Optional[float]:
    """Allure GAP (secondes par km) pondérée par le temps sur toute la séance.
    `None` sans échantillons, ou si aucune vitesse/pente exploitable nulle
    part."""
    if not samples:
        return None
    series = gap_sample_series(samples, **grade_kwargs)
    return activity_gap_pace_from_series(series, resolution_s=resolution_s)


def split_boundaries(splits: Sequence[dict]) -> List[dict]:
    """Bornes de distance cumulée (m) par split, à partir des lignes
    `activity_split` (`km`, `distance_m` — voir `arc_contract.SPLIT_COLUMNS`),
    triées par `km` croissant. Un split sans `distance_m` exploitable (colonne
    optionnelle du contrat, ou valeur non positive) est supposé faire 1000 m
    plein (voir `ASSUMPTIONS["split_distance_default"]`). Rend une liste de
    `{"km", "start_m", "end_m"}`."""
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
    return out


def split_gap_paces_from_series(series: Sequence[dict], splits: Sequence[dict], *,
                                 resolution_s: float = DEFAULT_RESOLUTION_S) -> Dict[int, Optional[float]]:
    """Comme `split_gap_paces`, mais à partir d'une série DÉJÀ augmentée par
    `gap_sample_series` — voir `activity_gap_pace_from_series` pour la même
    raison (éviter un recalcul en double pente/GAP pour la même activité)."""
    if not series or not splits:
        return {}
    bounds = split_boundaries(splits)
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
