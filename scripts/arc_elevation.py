#!/usr/bin/env python3
"""Lissage d'altitude et calcul de pente — partagé par le GAP (`arc_gap.py`,
#44, allure ajustée à la pente) et par l'analyse GPX générique
(`skills/gpx-analysis/scripts/analyze_gpx.py`, qui importe ce module pour son
propre lissage d'altitude plutôt que de dupliquer l'algorithme).

Fonctions **pures**, stdlib uniquement (CONTRIBUTING.md), sans SQLite ni accès
disque : testées isolément au palier D.

## Pourquoi pas la pente brute entre deux échantillons de 5 s

`altitude_m` (voir `arc_samples.py`) est un cumul barométrique bruité, et ce
module ne reçoit explicitement AUCUN lissage en amont (« aucun lissage
d'altitude... appartient aux consommateurs », `arc_samples.ASSUMPTIONS`).
Diviser une différence d'altitude entre deux échantillons consécutifs de 5 s
par la distance parcourue amplifierait ce bruit : à 2,7 m/s (allure
d'endurance typique), 5 s ne couvrent qu'environ 13,5 m, une distance sur
laquelle même 1 m de bruit barométrique donne une pente de plusieurs points de
pourcentage. Ce module calcule donc la pente sur une FENÊTRE de distance
(`window_m`, 20 à 50 m par défaut — recommandation de l'issue #44, cohérente
avec la pratique GPX habituelle), après un lissage léger de l'altitude par
moyenne glissante (même principe que `analyze_gpx.compute_metrics`, qui
moyenne les altitudes brutes GPS voisines pour tuer le bruit GPS/baro).

## Trous de signal (pauses) : jamais traversés

Comme `arc_samples.ASSUMPTIONS["gaps"]`, un trou de signal (montre en veille,
perte GPS/altimètre) ne doit jamais être traversé par une fenêtre de pente :
`max_gap_s` (défaut 30 s, six fois la résolution par défaut de 5 s —
largement au-delà d'une simple variance de sous-échantillonnage, mais assez
tôt pour attraper une vraie pause) sépare les échantillons en segments
contigus ; la pente n'est jamais calculée entre deux segments différents, ni
entre deux points dont la distance cumulée recule ou stagne (capteur figé ou
GPS glitché — traité comme non exploitable, jamais comme une pente nulle).

## Robustesse au bruit — pourquoi l'agrégat compte, pas l'échantillon isolé

Le modèle de coût énergétique utilisé en aval (Minetti, `arc_gap.py`) est très
sensible près du plat (dérivée `dC/di` en `i=0` ≈ 19,5 J/kg/m par unité de
pente) : un bruit de pente de quelques % sur un SEUL échantillon peut changer
sa vitesse GAP instantanée de plusieurs %. Mais ce bruit est proche de
moyenne nulle sur une séance entière : agrégé (moyenne pondérée par le temps
sur un split ou une séance), l'erreur résiduelle est du second ordre
(`E[C(pente bruitée)] ≈ C(0) + C''(0)/2 × Var(bruit)`, négligeable pour un
bruit raisonnable) — c'est pourquoi le critère d'acceptation de #44 porte sur
le GAP AGRÉGÉ d'un plat bruité, jamais sur chaque échantillon individuel.
"""

from __future__ import annotations

from typing import List, Optional, Sequence

# Fenêtre de calcul de pente : 20-50 m recommandés par l'issue #44 ; 30 m par
# défaut, un compromis entre réactivité (détecter un vrai changement de pente)
# et robustesse au bruit barométrique (voir docstring du module).
DEFAULT_GRADE_WINDOW_M = 30.0
DEFAULT_MIN_GRADE_WINDOW_M = 20.0
# Six fois la résolution par défaut de sous-échantillonnage (`arc_samples.
# DEFAULT_RESOLUTION_S`) : au-delà, un écart entre deux échantillons consécutifs
# est traité comme une vraie pause, jamais comme une simple variance de mesure.
DEFAULT_MAX_GAP_S = 30.0
# Moyenne glissante sur 3 points voisins (même ordre de grandeur que le
# `--smooth` par défaut d'`analyze_gpx.py`) avant de prendre la différence
# d'altitude aux deux bords de la fenêtre de pente.
DEFAULT_SMOOTH_TAPS = 3

ASSUMPTIONS = {
    "grade_window": (
        "La pente n'est JAMAIS calculée entre deux échantillons consécutifs (5 s, bruit "
        "barométrique amplifié sur une trop courte distance) : `grade_series` cherche, de part "
        "et d'autre de chaque échantillon, les points les plus proches couvrant au moins "
        "`window_m / 2` (défaut 30 m -> 15 m de chaque côté) de distance cumulée, avant de "
        "diviser la différence d'altitude LISSÉE (moyenne glissante `smooth_taps`, défaut 3 "
        "points, même principe qu'`analyze_gpx.compute_metrics`) par la distance totale "
        "obtenue. En dessous de `min_window_m` (défaut 20 m — bord de segment trop court, "
        "arrêt), la pente reste `None` plutôt qu'une valeur bruitée sur une distance trop "
        "courte."
    ),
    "gap_segmentation": (
        "Une pente n'est jamais calculée à travers un trou de signal (`max_gap_s`, défaut "
        "30 s — six fois la résolution par défaut de sous-échantillonnage) : les échantillons "
        "sont d'abord découpés en segments contigus (voir `arc_samples.ASSUMPTIONS[\"gaps\"]` "
        "pour la raison), la pente de chaque échantillon ne regardant jamais au-delà des "
        "bornes de SON segment."
    ),
    "noise_robustness": (
        "Le modèle de coût énergétique en aval (Minetti, `arc_gap.py`) est sensible près du "
        "plat : un bruit de pente de quelques % sur un SEUL échantillon peut changer sa "
        "vitesse GAP instantanée de plusieurs %. Agrégé (moyenne pondérée par le temps sur un "
        "split ou une séance entière), l'erreur résiduelle est du second ordre et négligeable "
        "pour un bruit raisonnable — voir la docstring du module pour la justification "
        "complète. Les tests de robustesse (#44, palier D) portent donc sur le GAP agrégé "
        "d'un plat bruité, jamais sur la pente d'un échantillon isolé."
    ),
}


def smooth_moving_average(values: Sequence[Optional[float]], taps: int = DEFAULT_SMOOTH_TAPS) -> List[Optional[float]]:
    """Moyenne glissante centrée sur `taps` valeurs voisines, `None` ignorés dans
    la fenêtre (jamais traités comme 0) ; rend `None` uniquement si AUCUNE valeur
    n'est disponible dans la fenêtre. `taps <= 1` désactive le lissage (identité).

    Même principe que le lissage d'altitude d'`analyze_gpx.compute_metrics`,
    factorisé ici pour être partagé (voir docstring du module)."""
    n = len(values)
    if n == 0 or taps <= 1:
        return list(values)
    half = taps // 2
    out: List[Optional[float]] = []
    for i in range(n):
        lo, hi = max(0, i - half), min(n, i + half + 1)
        vals = [v for v in values[lo:hi] if v is not None]
        out.append(sum(vals) / len(vals) if vals else None)
    return out


def _segments(t_values: Sequence[Optional[float]], max_gap_s: float) -> List[List[int]]:
    """Indices contigus (sur `t_values`, DÉJÀ TRIÉS croissants) sans écart entre
    deux valeurs consécutives supérieur à `max_gap_s`. Les indices dont la valeur
    est `None` sont exclus de tout segment (aucun `t_s` exploitable)."""
    segments: List[List[int]] = []
    current: List[int] = []
    prev_t: Optional[float] = None
    for i, t in enumerate(t_values):
        if t is None:
            continue
        if prev_t is not None and t - prev_t > max_gap_s:
            if current:
                segments.append(current)
            current = []
        current.append(i)
        prev_t = t
    if current:
        segments.append(current)
    return segments


def segments_by_gap(t_values: Sequence[Optional[float]], max_gap_s: float = DEFAULT_MAX_GAP_S) -> List[List[int]]:
    """Alias PUBLIC de `_segments` — segmentation par trou de signal, réutilisée
    par la détection de montées (`arc_climb.py`, #46) : une montée ne doit
    jamais être détectée à travers une pause GPS/altimètre (montre en veille),
    même principe que la pente (`grade_series` ci-dessus) et que le GAP
    (`arc_gap.py`, #44)."""
    return _segments(t_values, max_gap_s)


def _extend_back(dist: Sequence[Optional[float]], li: int, half_window: float) -> int:
    """Indice `j <= li` le plus proche tel que `dist[li] - dist[j] >= half_window`
    (ou 0 / le bord d'un trou de distance manquante si cette distance n'est jamais
    atteinte)."""
    j = li
    d_i = dist[li]
    while j > 0 and (dist[j] is None or (d_i - dist[j]) < half_window):
        j -= 1
    return j


def _extend_fwd(dist: Sequence[Optional[float]], li: int, half_window: float, m: int) -> int:
    """Symétrique de `_extend_back`, vers l'avant."""
    k = li
    d_i = dist[li]
    while k < m - 1 and (dist[k] is None or (dist[k] - d_i) < half_window):
        k += 1
    return k


def grade_series(samples: Sequence[dict], *, window_m: float = DEFAULT_GRADE_WINDOW_M,
                  min_window_m: float = DEFAULT_MIN_GRADE_WINDOW_M,
                  max_gap_s: float = DEFAULT_MAX_GAP_S,
                  smooth_taps: int = DEFAULT_SMOOTH_TAPS) -> List[dict]:
    """Pente (fraction signée, ex. 0.05 = 5 % de montée) par échantillon, sur des
    échantillons normalisés (`t_s, distance_m, altitude_m, ...`, triés ou non —
    voir `arc_samples.NORMALISED_KEYS`).

    Rend une COPIE triée par `t_s` de `samples` (échantillons sans `t_s`
    exploitable écartés), chaque dict augmenté d'une clé `"grade"` : fraction
    signée, ou `None` si non calculable (bord de segment trop court, trou de
    signal, distance/altitude manquante, ou distance cumulée qui ne progresse
    jamais assez sur la fenêtre — voir `ASSUMPTIONS` pour la méthode complète).
    Jamais de pente calculée à travers un trou de signal, ni sur une distance
    qui stagne ou recule (capteur figé/GPS glitché)."""
    ordered = sorted((dict(s) for s in samples if s.get("t_s") is not None), key=lambda s: s["t_s"])
    for s in ordered:
        s["grade"] = None
    n = len(ordered)
    if n == 0:
        return ordered
    t_values = [s["t_s"] for s in ordered]
    half_window = window_m / 2.0
    for segment in _segments(t_values, max_gap_s):
        dist = [ordered[i].get("distance_m") for i in segment]
        raw_alt = [ordered[i].get("altitude_m") for i in segment]
        alt = smooth_moving_average(raw_alt, smooth_taps)
        m = len(segment)
        for li in range(m):
            d_i = dist[li]
            if d_i is None:
                continue
            j = _extend_back(dist, li, half_window)
            k = _extend_fwd(dist, li, half_window, m)
            d_j, d_k = dist[j], dist[k]
            a_j, a_k = alt[j], alt[k]
            if d_j is None or d_k is None or a_j is None or a_k is None:
                continue
            span = d_k - d_j
            if span < min_window_m:
                continue
            ordered[segment[li]]["grade"] = (a_k - a_j) / span
    return ordered
