#!/usr/bin/env python3
"""Découplage aérobie (Pa:HR) et facteur d'efficacité — #45, épopée #21.

## Principe

Sur une séance longue à effort stable, la fréquence cardiaque nécessaire pour
tenir la même allure « plat équivalent » (GAP, `arc_gap.py`, #44) dérive
généralement à la hausse au fil du temps (fatigue, chaleur, déshydratation).
Cette dérive — désignée dans la littérature d'entraînement d'endurance sous le
nom **Pa:HR** (« Pace:HR », popularisé par la marque TrainingPeaks — voir
`docs/marques.md`, non reproduit ici, formule publique) — se mesure en
comparant le **facteur d'efficacité** (EF = allure ajustée à la pente / FC) de
la première moitié de la séance à celui de la seconde :

    EF = moyenne(vitesse GAP, m/min) / moyenne(FC, bpm)         (pondérées par le temps)
    découplage % = (EF_première_moitié − EF_seconde_moitié) / EF_première_moitié × 100

Une valeur positive signale une dérive (efficacité qui se dégrade) ; une
valeur négative ou nulle signale une séance stable, voire un athlète qui
« monte en régime ». **Repère de coaching courant, jamais un seuil validé
cliniquement** : un découplage sous 5 % est habituellement considéré comme un
signe de bonne durabilité aérobie sur les sorties longues (ce seuil circule
largement dans le coaching d'endurance/ultra — voir par exemple Uphill
Athlete — mais nous n'avons pas de source primaire évaluée par les pairs à
citer ; le présenter comme un simple repère indicatif, jamais une norme).

Le GAP (jamais la vitesse brute) est utilisé aux deux moitiés : sur un
parcours vallonné, une moitié plus pentue que l'autre fausserait sinon
totalement la comparaison (une côte fait naturellement monter la FC à allure
égale). Réutilise `arc_gap.gap_sample_series`/`weighted_average` telles
quelles (#44) — jamais un second calcul de pente/GAP.

## Éligibilité et règle d'« effort stable »

Voir `ASSUMPTIONS` ci-dessous pour le détail complet et sa justification :
famille course à pied, durée de mouvement ≥ 60 min, échauffement exclu,
arrêts exclus, coefficient de variation du GAP sur fenêtres d'une minute
plafonné (repère simple de séance non fractionnée).

## API réutilisable, pure (sans SQLite ni disque) — pour #48 (durabilité, même
famille de calcul sur le dernier tiers plutôt que la seconde moitié)

- `decoupling_report(samples, sport, resolution_s=...)` : rapport complet à
  partir des échantillons normalisés (`arc_index.samples`) et du sport de
  l'activité — TOUJOURS un dict avec une `reason` explicite en cas d'échec,
  jamais une exception.
- `coefficient_of_variation_pct(series, resolution_s=...)` : robustesse de
  l'effort (dispersion du GAP par fenêtre d'une minute), réutilisable pour
  toute autre détection de séance non stable.

Stdlib uniquement (CONTRIBUTING.md).
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
import arc_gap as G  # noqa: E402
import arc_metrics as M  # noqa: E402

# Résolution nominale des échantillons sous-échantillonnés (alignée sur
# `arc_samples.DEFAULT_RESOLUTION_S` / `arc_gap.DEFAULT_RESOLUTION_S`).
DEFAULT_RESOLUTION_S = G.DEFAULT_RESOLUTION_S

# Seuil d'éligibilité (#45, critère d'acceptation) : séance de mouvement d'au
# moins 60 minutes — sous ce seuil, deux moitiés seraient trop courtes pour
# qu'une dérive de FC se distingue du bruit normal séance à séance.
MIN_MOVING_DURATION_S = 60 * 60.0

# Échauffement exclu (10 premières minutes ÉCOULÉES depuis le premier
# échantillon, arrêts compris dans ce décompte) : la FC met plusieurs minutes
# à atteindre son régime de croisière (retard cardiovasculaire, « cardiac
# lag ») ; l'inclure grossirait artificiellement l'EF de la première moitié
# (FC basse pour l'allure) et gonflerait le découplage mesuré. Valeur ronde
# documentée, pas calibrée sur des données réelles (aucune source publiée
# retenue pour une valeur plus précise) — voir ASSUMPTIONS["warmup"].
WARMUP_S = 10 * 60.0

# Chaque moitié doit conserver au moins 10 minutes de temps de MOUVEMENT
# exploitable (post-échauffement, arrêts exclus) : sous ce seuil, la moyenne
# pondérée d'une moitié devient trop sensible à un seul échantillon bruité.
MIN_HALF_MOVING_S = 10 * 60.0

# Détection d'« effort stable » (#45, critère d'acceptation : portions non
# stables exclues selon une règle documentée) : coefficient de variation
# (écart-type / moyenne) du GAP sur des fenêtres d'une minute, calculé sur les
# échantillons en mouvement post-échauffement. Un fractionné (alternance
# effort/récupération) ou des arrêts répétés (feux, ravitaillements) créent
# une variation minute à minute BEAUCOUP plus grande qu'une sortie longue à
# allure stable, même vallonnée (le GAP absorbe déjà le relief). Seuil choisi
# par jugement d'ingénierie (pas calibré sur un jeu de séances réelles
# étiquetées « stable »/« fractionné ») : volontairement généreux pour ne pas
# rejeter à tort une sortie longue avec quelques replats/relances naturelles.
CV_WINDOW_S = 60.0
CV_THRESHOLD_PCT = 20.0
CV_MIN_WINDOWS = 3  # sous ce nombre de fenêtres, la CV n'est pas jugée fiable (voir ASSUMPTIONS)

ASSUMPTIONS = {
    "model": (
        "Découplage aérobie (Pa:HR) et facteur d'efficacité (EF), sur le modèle popularisé par la "
        "marque TrainingPeaks (voir docs/marques.md) : EF = vitesse GAP moyenne (m/min, pondérée par "
        "le temps) / FC moyenne (bpm) sur une moitié de séance ; découplage % = (EF première moitié − "
        "EF seconde moitié) / EF première moitié × 100. Le GAP (arc_gap.py, #44), jamais la vitesse "
        "brute, est utilisé aux deux moitiés pour qu'une côte ou une descente ne fausse pas la "
        "comparaison. Un découplage sous 5 % est un repère de coaching courant (endurance/ultra, par "
        "exemple Uphill Athlete) pour une bonne durabilité aérobie — PAS un seuil validé "
        "cliniquement, jamais présenté comme une norme."
    ),
    "restricted_to_run_family": (
        "Calculé UNIQUEMENT pour les séances de la famille course à pied (arc_metrics.sport_family == "
        "\"run\") avec des échantillons FIT ingérés — même restriction et même raison que les zones FC "
        "(#43) et le GAP (#44) : une FC de renforcement ou de vélo n'a pas le même sens physiologique."
    ),
    "min_duration": (
        f"Séance de {MIN_MOVING_DURATION_S / 60:.0f} minutes de mouvement minimum (moving_duration, "
        "arrêts exclus) — sous ce seuil, deux moitiés seraient trop courtes pour distinguer une "
        "vraie dérive cardiaque du bruit normal séance à séance."
    ),
    "warmup": (
        f"Les {WARMUP_S / 60:.0f} premières minutes ÉCOULÉES (depuis le premier échantillon, arrêts "
        "compris dans ce décompte) sont exclues du calcul : la FC met plusieurs minutes à atteindre "
        "son régime de croisière (retard cardiovasculaire) ; les inclure gonflerait artificiellement "
        "l'EF de la première moitié (FC encore basse pour l'allure déjà courue) et donc le découplage "
        "mesuré. Valeur ronde documentée, pas calibrée sur des données réelles. IMPORTANT : la "
        "frontière entre les deux moitiés est fixée AVANT l'exclusion de l'échauffement (sur le temps "
        "de mouvement total de la séance), puis l'échauffement est retiré à l'intérieur de la "
        "première moitié — jamais l'inverse (exclure d'abord, puis re-partager en deux le reste), ce "
        "qui décalerait la frontière et ferait fuir des échantillons de fin de première moitié "
        "(potentiellement déjà en dérive) vers ce qui est compté comme de l'échauffement, biaisant le "
        "découplage mesuré vers le bas. Le refroidissement (fin de séance) n'est volontairement PAS "
        "exclu séparément : le découpage en deux moitiés absorbe déjà une petite portion finale plus "
        "lente dans la seconde moitié, et une exclusion dédiée ajouterait un paramètre de plus sans "
        "justification aussi claire que l'échauffement."
    ),
    "stopped_samples": (
        "Les instants à l'arrêt (vitesse sous arc_gap.STOPPED_SPEED_MS — feu rouge, ravitaillement, "
        "pause) sont exclus du calcul de l'EF ET du découpage en deux moitiés, qui se fait sur le "
        "TEMPS DE MOUVEMENT cumulé (jamais le temps écoulé) : une pause au milieu de la séance ne doit "
        "ni fausser la FC/le GAP moyens d'une moitié, ni déplacer artificiellement la frontière entre "
        "les deux moitiés."
    ),
    "steady_effort": (
        f"Règle d'« effort stable » (portions non stables exclues, critère d'acceptation #45) : "
        f"coefficient de variation (écart-type / moyenne) du GAP sur des fenêtres de "
        f"{CV_WINDOW_S:.0f} secondes, calculé sur les échantillons en mouvement post-échauffement. "
        f"Au-delà de {CV_THRESHOLD_PCT:.0f} %, l'activité est jugée non stable (fractionné probable, "
        "ou arrêts répétés au-delà de ce que l'exclusion des arrêts absorbe déjà) et le découplage "
        "n'est pas calculé — ni le titre/l'intensité déclarée de la séance, ni une détection "
        "d'intervalles plus sophistiquée (repérage de pics répétés) ne sont utilisés : cette règle "
        "statistique unique reste volontairement simple et s'applique à toute activité indexée, que "
        "son intensité planifiée soit connue ou non. Avec moins de "
        f"{CV_MIN_WINDOWS} fenêtres exploitables, la CV n'est pas jugée fiable et cette règle est "
        "ignorée (pas assez de points pour distinguer un vrai fractionné d'un artefact)."
    ),
    "halves": (
        "Les deux moitiés sont découpées sur le TEMPS DE MOUVEMENT cumulé (post-échauffement, arrêts "
        "exclus), jamais la distance ni le temps écoulé : une moitié plus lente (fatigue, montée) "
        "couvrirait sinon moins de distance mais devrait rester comparable en durée réelle d'effort. "
        "Chaque moitié doit conserver au moins "
        f"{MIN_HALF_MOVING_S / 60:.0f} minutes de mouvement exploitable, sinon l'activité est jugée "
        "inéligible (durée exploitable insuffisante après exclusions)."
    ),
    "whole_activity_ef": (
        "Le facteur d'efficacité « séance entière » (ef_whole) est calculé sur TOUS les échantillons "
        "post-échauffement en mouvement (les deux moitiés réunies), pour une valeur unique comparable "
        "d'une séance à l'autre dans la tendance (indépendante du découpage en deux moitiés)."
    ),
}


def _dt_to_next(ordered: Sequence[dict], i: int, resolution_s: float) -> float:
    n = len(ordered)
    dt = ordered[i + 1]["t_s"] - ordered[i]["t_s"] if i + 1 < n else resolution_s
    return max(0.0, min(dt, resolution_s))


def _is_moving(sample: dict) -> bool:
    return (sample.get("speed_ms") or 0.0) >= G.STOPPED_SPEED_MS


def coefficient_of_variation_pct(series: Sequence[dict], *, window_s: float = CV_WINDOW_S,
                                  resolution_s: float = DEFAULT_RESOLUTION_S) -> Optional[float]:
    """Coefficient de variation (%) du GAP (`gap_speed_ms`) par fenêtres de
    `window_s` secondes, sur `series` déjà filtrée (mouvement, post-
    échauffement) — voir `ASSUMPTIONS["steady_effort"]`. `None` si moins de
    `CV_MIN_WINDOWS` fenêtres ont une moyenne exploitable (pas assez de points
    pour juger, jamais une fausse alerte de fractionné)."""
    ordered = sorted((s for s in series if s.get("t_s") is not None), key=lambda s: s["t_s"])
    if not ordered:
        return None
    t0 = ordered[0]["t_s"]
    buckets: Dict[int, List[dict]] = {}
    for s in ordered:
        buckets.setdefault(int((s["t_s"] - t0) // window_s), []).append(s)
    means = []
    for bucket_samples in buckets.values():
        avg = G.weighted_average(bucket_samples, "gap_speed_ms", resolution_s)
        if avg is not None:
            means.append(avg)
    if len(means) < CV_MIN_WINDOWS:
        return None
    mean = sum(means) / len(means)
    if not mean:
        return None
    variance = sum((v - mean) ** 2 for v in means) / len(means)
    return (variance ** 0.5) / mean * 100.0


def _split_by_moving_time(series: Sequence[dict], *,
                           resolution_s: float = DEFAULT_RESOLUTION_S) -> Tuple[List[dict], List[dict], float]:
    """Découpe `series` (triée ou non) en deux moitiés sur le temps de MOUVEMENT
    cumulé (voir `ASSUMPTIONS["halves"]`/`["stopped_samples"]`). Rend
    `(moitié_1, moitié_2, temps_de_mouvement_total_s)` — les échantillons à
    l'arrêt n'apparaissent dans AUCUNE des deux moitiés.

    Appelée sur la séance ENTIÈRE (échauffement compris) : voir
    `ASSUMPTIONS["warmup"]` pour pourquoi la frontière doit être fixée AVANT
    d'exclure l'échauffement, jamais après."""
    ordered = sorted((s for s in series if s.get("t_s") is not None), key=lambda s: s["t_s"])
    moving = [(i, s) for i, s in enumerate(ordered) if _is_moving(s)]
    weights = {i: _dt_to_next(ordered, i, resolution_s) for i, _s in moving}
    total_moving_s = sum(weights.values())
    half1: List[dict] = []
    half2: List[dict] = []
    running = 0.0
    halfway = total_moving_s / 2.0
    for i, s in moving:
        (half1 if running < halfway else half2).append(s)
        running += weights[i]
    return half1, half2, total_moving_s


def _ef(series: Sequence[dict], *, resolution_s: float = DEFAULT_RESOLUTION_S) -> Optional[float]:
    """Facteur d'efficacité (vitesse GAP moyenne en m/min / FC moyenne en bpm),
    pondéré par le temps. `None` sans GAP ou sans FC exploitable sur `series`."""
    mean_gap_ms = G.weighted_average(series, "gap_speed_ms", resolution_s)
    mean_hr = G.weighted_average(series, "hr_bpm", resolution_s)
    if mean_gap_ms is None or not mean_hr:
        return None
    return (mean_gap_ms * 60.0) / mean_hr


def decoupling_report(samples: Sequence[dict], sport: Optional[str], *,
                       resolution_s: float = DEFAULT_RESOLUTION_S,
                       moving_duration_s: Optional[float] = None,
                       **grade_kwargs) -> dict:
    """Rapport de découplage aérobie (#45) d'une séance, à partir de ses
    échantillons normalisés (`arc_index.samples`/`samples_by_garmin_id`) et de
    son sport.

    Rend TOUJOURS `{"decoupling_pct", "ef_whole", "ef_first_half",
    "ef_second_half", "moving_duration_s", "eligible", "reason"}` — `reason`
    explique un `None`/`eligible: False`, jamais une exception ni un échec
    muet (même discipline que `arc_index.activity_gap_report`/
    `activity_zone_report`, #43/#44).

    `moving_duration_s`, si fourni (colonne `activity.moving_duration_s`),
    sert UNIQUEMENT au seuil d'éligibilité de durée globale — pas au calcul
    lui-même, qui recalcule son propre temps de mouvement post-échauffement
    depuis les échantillons (voir `ASSUMPTIONS`)."""
    empty = {"decoupling_pct": None, "ef_whole": None, "ef_first_half": None,
             "ef_second_half": None, "moving_duration_s": None, "eligible": False}
    if M.sport_family(sport) != "run":
        return {**empty, "reason": "hors de la famille course à pied (arc_metrics.sport_family), "
                                    "voir ASSUMPTIONS[\"restricted_to_run_family\"]"}
    if not samples:
        return {**empty, "reason": "aucun échantillon FIT ingéré pour cette séance"}

    series = G.gap_sample_series(samples, **grade_kwargs)
    ordered = sorted((s for s in series if s.get("t_s") is not None), key=lambda s: s["t_s"])
    if not ordered:
        return {**empty, "reason": "aucun échantillon exploitable (t_s manquant)"}

    whole_moving_s = sum(_dt_to_next(ordered, i, resolution_s) for i, s in enumerate(ordered) if _is_moving(s))
    if whole_moving_s < MIN_MOVING_DURATION_S:
        return {**empty, "moving_duration_s": round(whole_moving_s, 1),
                "reason": f"durée de mouvement insuffisante (< {MIN_MOVING_DURATION_S / 60:.0f} min), "
                          "voir ASSUMPTIONS[\"min_duration\"]"}

    t0 = ordered[0]["t_s"]
    # Frontière des deux moitiés fixée sur la séance ENTIÈRE (voir
    # ASSUMPTIONS["warmup"]) : l'échauffement est retiré ENSUITE, à l'intérieur
    # de chaque moitié, jamais avant (ce qui décalerait la frontière).
    half1_raw, half2_raw, _total_moving_s = _split_by_moving_time(ordered, resolution_s=resolution_s)
    half1 = [s for s in half1_raw if s["t_s"] - t0 >= WARMUP_S]
    half2 = [s for s in half2_raw if s["t_s"] - t0 >= WARMUP_S]
    if not half1 and not half2:
        return {**empty, "moving_duration_s": round(whole_moving_s, 1),
                "reason": "aucun échantillon après exclusion de l'échauffement, "
                          "voir ASSUMPTIONS[\"warmup\"]"}

    with_hr_and_gap = [s for s in half1 + half2
                        if s.get("hr_bpm") is not None and s.get("gap_speed_ms") is not None]
    if not with_hr_and_gap:
        return {**empty, "moving_duration_s": round(whole_moving_s, 1),
                "reason": "aucune fréquence cardiaque (ou pente/GAP) exploitable pour cette séance"}

    cv_pct = coefficient_of_variation_pct(half1 + half2, resolution_s=resolution_s)
    if cv_pct is not None and cv_pct > CV_THRESHOLD_PCT:
        return {**empty, "moving_duration_s": round(whole_moving_s, 1),
                "reason": f"effort jugé non stable (coefficient de variation du GAP {cv_pct:.1f} % > "
                          f"{CV_THRESHOLD_PCT:.0f} % sur fenêtres d'une minute, fractionné ou arrêts "
                          "répétés probables), voir ASSUMPTIONS[\"steady_effort\"]"}

    half1_moving_s = sum(_dt_to_next(half1, i, resolution_s) for i in range(len(half1)))
    half2_moving_s = sum(_dt_to_next(half2, i, resolution_s) for i in range(len(half2)))
    if half1_moving_s < MIN_HALF_MOVING_S or half2_moving_s < MIN_HALF_MOVING_S:
        return {**empty, "moving_duration_s": round(whole_moving_s, 1),
                "reason": "durée exploitable insuffisante après exclusion de l'échauffement et des "
                          f"arrêts (< {MIN_HALF_MOVING_S / 60:.0f} min de mouvement sur au moins une "
                          "moitié), voir ASSUMPTIONS[\"halves\"]"}

    ef1 = _ef(half1, resolution_s=resolution_s)
    ef2 = _ef(half2, resolution_s=resolution_s)
    if ef1 is None or ef2 is None:
        return {**empty, "moving_duration_s": round(whole_moving_s, 1),
                "reason": "FC ou GAP insuffisant sur au moins une des deux moitiés"}

    ef_whole = _ef(half1 + half2, resolution_s=resolution_s)
    decoupling_pct = round((ef1 - ef2) / ef1 * 100.0, 2) if ef1 else None
    return {
        "decoupling_pct": decoupling_pct,
        "ef_whole": round(ef_whole, 4) if ef_whole is not None else None,
        "ef_first_half": round(ef1, 4),
        "ef_second_half": round(ef2, 4),
        "moving_duration_s": round(whole_moving_s, 1),
        "eligible": True,
        "reason": None,
    }
