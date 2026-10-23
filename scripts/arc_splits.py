#!/usr/bin/env python3
"""Splits kilométriques calculés depuis les échantillons FIT.

Fonctions **pures**, stdlib uniquement, sans SQLite ni accès disque : la CLI
`arc_index.py splits <id>` lit les échantillons ingérés (`activity_sample`) et
appelle `km_splits`. Le résultat (`splits_cols` + `splits`) est prêt à recopier
dans le bloc ```arc``` de la séance (contrat `workspace-data-contract`) :
c'est l'agent qui l'écrit, le Markdown reste la source de vérité.

## Pourquoi depuis le FIT

Toutes les sources n'exposent pas de splits par km réguliers : intervals.icu
n'en a pas, Strava ne donne que des tours, et un découpage « par km » qui
repart de zéro à chaque étape d'une séance structurée n'est pas un split au km.
Les échantillons normalisés (`activities/fit/<id>.json`, `arc_samples.py`)
existent, eux, pour toutes les sources : un même calcul donne les mêmes splits
quelle que soit la montre ou le service.

## Hypothèses

Voir `ASSUMPTIONS` : temps écoulé (comme l'allure et le GAP par split déjà
affichés), bornes interpolées entre deux échantillons, dernier split partiel
gardé avec sa `distance_m` s'il est assez long, D+/D- sur l'altitude lissée.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Sequence

import arc_elevation as E

SPLIT_M = 1000.0
# En dessous, le reliquat de fin de séance n'est pas un split : 40 m après le
# dernier km entier ne disent rien de l'allure (et fausseraient les records).
MIN_PARTIAL_M = 100.0
# Mêmes seuils que le GAP (`arc_gap.STOPPED_SPEED_MS`) : à l'arrêt, la cadence
# n'est pas une cadence de course.
STOPPED_SPEED_MS = 0.2

SPLIT_COLS = ["km", "distance_m", "duration_s", "elev_gain_m", "elev_loss_m",
              "avg_hr_bpm", "max_hr_bpm", "max_speed_kmh", "cadence_spm"]

ASSUMPTIONS = {
    "elapsed_time": (
        "`duration_s` d'un split = temps ÉCOULÉ entre ses deux bornes, arrêts compris — comme "
        "l'allure et le GAP par split du tableau de bord (`arc_gap.ASSUMPTIONS[\"stopped_samples\"]`). "
        "Une pause au milieu d'un kilomètre allonge donc ce kilomètre ; le temps en mouvement de "
        "la séance reste `moving_duration_s`."
    ),
    "boundaries": (
        "Chaque borne de 1 000 m est placée par interpolation linéaire du temps entre les deux "
        "échantillons qui l'encadrent (5 s d'écart par défaut) : précision de l'ordre de la "
        "seconde, sans dépendre du découpage en tours de la montre ni des étapes d'une séance "
        "structurée."
    ),
    "distance_source": (
        "Distance cumulée telle qu'enregistrée par la montre (GPS ou capteur) : la somme des "
        "splits suit `distance_m` du FIT, pas une trace corrigée. Un recul de distance (glitch) "
        "est ignoré, jamais compté comme un retour en arrière."
    ),
    "partial_last": (
        f"Le reliquat après le dernier km entier devient un split partiel, avec sa `distance_m`, "
        f"s'il fait au moins {MIN_PARTIAL_M:.0f} m ; en dessous, il est ignoré."
    ),
    "elevation": (
        f"D+/D- par split sur l'altitude lissée par moyenne glissante "
        f"({E.DEFAULT_SMOOTH_TAPS} points, `arc_elevation.smooth_moving_average`), chaque pas "
        f"attribué au split où il se termine. Approximation du projet : la somme peut s'écarter "
        f"du D+ affiché par la montre ou le service (lissage propriétaire)."
    ),
    "hr_speed_cadence": (
        "FC moyenne = moyenne des échantillons du split (pas réguliers) ; FC max, vitesse max = "
        "maximum des échantillons (sous-échantillonnés à 5 s : un pic plus court est lissé). "
        f"Cadence = moyenne des échantillons en mouvement (vitesse > {STOPPED_SPEED_MS} m/s). "
        "Une colonne sans aucune mesure sur un split reste `null`, jamais devinée."
    ),
}


def _usable(samples: Sequence[dict]) -> List[dict]:
    """Échantillons avec `t_s` et `distance_m`, triés par temps, distance rendue
    non décroissante (un recul GPS est aplati, jamais retranché)."""
    pts = sorted((s for s in samples if s.get("t_s") is not None and s.get("distance_m") is not None),
                 key=lambda s: s["t_s"])
    out: List[dict] = []
    best = None
    for s in pts:
        d = s["distance_m"] if best is None else max(best, s["distance_m"])
        best = d
        out.append({**s, "distance_m": d})
    return out


def _time_at(pts: Sequence[dict], i: int, target_m: float) -> float:
    """Temps (s) où la distance cumulée atteint `target_m`, entre `pts[i-1]` et `pts[i]`."""
    a, b = pts[i - 1], pts[i]
    span = b["distance_m"] - a["distance_m"]
    if span <= 0:
        return b["t_s"]
    return a["t_s"] + (target_m - a["distance_m"]) / span * (b["t_s"] - a["t_s"])


def _mean(values: Sequence[float]) -> Optional[float]:
    return sum(values) / len(values) if values else None


def _round(value: Optional[float], ndigits: int = 0):
    if value is None:
        return None
    return int(round(value)) if ndigits == 0 else round(value, ndigits)


def km_splits(samples: Sequence[dict], *, split_m: float = SPLIT_M,
              min_partial_m: float = MIN_PARTIAL_M) -> Dict[str, object]:
    """Splits par km d'une séance depuis ses échantillons normalisés
    (`t_s`, `distance_m`, `altitude_m`, `hr_bpm`, `speed_ms`, `cadence_spm`).

    Rend TOUJOURS `{"splits_cols", "splits", "reason"}` : `splits` vaut `None`
    et `reason` explique pourquoi quand rien n'est calculable (aucun
    échantillon, pas de distance, séance de moins de `min_partial_m`)."""
    pts = _usable(samples)
    if len(pts) < 2:
        return {"splits_cols": SPLIT_COLS, "splits": None,
                "reason": "aucun échantillon FIT avec temps et distance pour cette séance"}
    start_d = pts[0]["distance_m"]
    total_m = pts[-1]["distance_m"] - start_d
    if total_m < min_partial_m:
        return {"splits_cols": SPLIT_COLS, "splits": None,
                "reason": f"distance enregistrée trop courte ({total_m:.0f} m) pour un split"}

    alt = E.smooth_moving_average([s.get("altitude_m") for s in pts], E.DEFAULT_SMOOTH_TAPS)
    n_full = int(total_m // split_m)
    remainder = total_m - n_full * split_m
    n_splits = n_full + (1 if remainder >= min_partial_m else 0)

    rows = []
    bucket: List[int] = []
    gain = loss = 0.0
    has_alt = False          # au moins un pas d'altitude mesuré dans le split courant
    k = 0                      # index du split courant (0 = premier km)
    t_start = pts[0]["t_s"]

    def close(t_end: float, length_m: float) -> None:
        nonlocal bucket, gain, loss, has_alt
        members = [pts[j] for j in bucket]
        hrs = [s["hr_bpm"] for s in members if s.get("hr_bpm") is not None]
        speeds = [s["speed_ms"] for s in members if s.get("speed_ms") is not None]
        cads = [s["cadence_spm"] for s in members
                if s.get("cadence_spm") is not None and (s.get("speed_ms") or 0) > STOPPED_SPEED_MS]
        rows.append([
            k + 1, _round(length_m), _round(t_end - t_start),
            _round(gain) if has_alt else None, _round(loss) if has_alt else None,
            _round(_mean(hrs)), _round(max(hrs) if hrs else None),
            _round(max(speeds) * 3.6 if speeds else None, 1), _round(_mean(cads)),
        ])
        bucket, gain, loss, has_alt = [], 0.0, 0.0, False

    bucket.append(0)
    for i in range(1, len(pts)):
        rel = pts[i]["distance_m"] - start_d
        # Une borne (ou plusieurs, après un trou de signal) franchie entre i-1 et i.
        while k < n_full and rel >= (k + 1) * split_m:
            t_cross = _time_at(pts, i, start_d + (k + 1) * split_m)
            close(t_cross, split_m)
            t_start = t_cross
            k += 1
        if k >= n_splits:
            break
        bucket.append(i)
        if alt[i - 1] is not None and alt[i] is not None:
            up, down = E.step_gain_loss(alt[i] - alt[i - 1])
            gain += up
            loss += down
            has_alt = True
    if k < n_splits:
        close(pts[-1]["t_s"], remainder)

    # `distance_m` n'a de sens que sur le split partiel : colonne retirée quand
    # tous les splits font exactement `split_m`.
    cols = list(SPLIT_COLS)
    if all(r[1] == _round(split_m) for r in rows):
        idx = cols.index("distance_m")
        cols.pop(idx)
        for r in rows:
            r.pop(idx)
    # Colonnes vides sur toute la séance (pas de ceinture, pas d'altimètre) : retirées,
    # jamais remplies de `null` à recopier dans le bloc arc.
    for col in [c for c in cols if c not in ("km", "duration_s")]:
        idx = cols.index(col)
        if all(r[idx] is None for r in rows):
            cols.pop(idx)
            for r in rows:
                r.pop(idx)
    return {"splits_cols": cols, "splits": rows, "reason": None}
