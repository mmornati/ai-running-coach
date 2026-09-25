"""Workspace synthétique au contrat ```arc, déterministe (graine fixe).

Sert aux tests du palier A (tableau de bord de bout en bout) et à la
vérification visuelle :

    python3 -m tests.lib.synthetic DIR [--days 120] [--today AAAA-MM-JJ] [--sport trail|road]
    python3 -m tests.lib.synthetic DIR --with-samples   # + échantillons seconde par seconde

Les valeurs sont plausibles, pas réalistes : un bloc de base, une montée de
charge, une semaine allégée toutes les quatre. Aucune donnée réelle.

## Échantillons seconde par seconde (`sample_session`)

Toute l'épopée FIT (zones #43, GAP #44, découplage #45, VAM #46, descente #47,
durabilité #48, modèle pente→allure #58 — épopée #21) a besoin de séries
seconde par seconde dont le résultat attendu est connu à l'avance.
`sample_session` génère une telle série avec des **propriétés paramétrées**
(montées/descentes par segment, dérive FC imposée, répartition de zones
imposée, fade de fin de séance, trous de signal) et renvoie, à côté des
échantillons, un dict `truth`.

**Toute valeur *mesurée* de `truth` est recalculée après coup, en ne lisant
que la liste `records` finale** (jamais un tableau interne du générateur) —
un trou de signal ne doit jamais gonfler silencieusement un total, et une
pente ne doit jamais fausser une mesure sans que ce soit visible dans les
données réellement émises. Les tests du palier D
(`tests/data/test_synthetic_samples.py`) vérifient mesuré ≈ demandé, à la
tolérance documentée dans chaque test, et recalculent certaines mesures de
façon indépendante (même formule, appliquée depuis l'extérieur) pour prouver
qu'il n'y a pas d'incohérence entre `truth` et `records`.

Champs par échantillon — **format normalisé**, aligné sur le schéma
`activity_sample` de `scripts/arc_index.py` (colonnes `t_s, distance_m,
altitude_m, hr_bpm, speed_ms, cadence_spm`) — **ce n'est pas** le format brut
que `skills/fit-download/scripts/download_fit.py` écrit aujourd'hui (celui-ci
dumpe les champs `fitparse` tels quels : `timestamp`, `distance`,
`heart_rate`, `enhanced_altitude` ou `altitude`, `enhanced_speed` ou `speed`,
`cadence`). C'est le format que l'ingestion FIT (story #42, non encore
implémentée) devra produire en sortie de sa normalisation, avec le mapping
`{heart_rate → hr_bpm, distance → distance_m, altitude/enhanced_altitude →
altitude_m, speed/enhanced_speed → speed_ms, cadence → cadence_spm, timestamp
→ t_s relatif au départ}`. Aucune coordonnée GPS n'est générée (`lat`/`lon`
restent hors du format — inutiles aux KPI de l'épopée FIT, et ça évite tout
risque de ressemblance avec un lieu réel).

Convention de pente : `distance_m` est une distance **horizontale** (la
projection au sol, comme le champ `distance` d'un FIT), `altitude_m` est
verticale. La pente d'un segment (`grade_pct`) est donc `100 × dénivelé /
distance horizontale`, jamais la distance parcourue en biais sur le versant.

`--with-samples` écrit, pour chaque séance running/trail générée, un fichier
`activities/fit/<garmin_activity_id>.json` (`{"activity_id", "records",
"truth"}`) — l'emplacement brut proposé par la story d'ingestion (#42). La
distance, le D+/D− et la FC moyenne des échantillons sont calibrés pour
rester cohérents avec ceux déjà écrits dans le Markdown de la séance (mêmes
ordres de grandeur, cf. `_write_samples`).
"""

from __future__ import annotations

import argparse
import json
import random
from datetime import date, timedelta
from pathlib import Path
from typing import Callable, Optional, Sequence

HR_REST, HR_MAX = 48, 188

# Zones FC par défaut : méthode Karvonen (réserve FC = FC max − FC repos), bornes à
# 50/60/70/80/90/100 % de la réserve — une convention courante à 5 zones, pas la
# seule valide : la story #43 rendra la méthode configurable par profil (Karvonen ou
# LTHR). Calculées ici sur les valeurs par défaut du profil type que `build()` écrit
# dans `planning/Runner_Profile.md` (FC repos 48, FC max 188) — pas des bornes
# choisies au hasard.
KARVONEN_HRR_PCT = (0.50, 0.60, 0.70, 0.80, 0.90, 1.00)


def karvonen_zone_bounds_bpm(hr_rest: int = HR_REST, hr_max: int = HR_MAX) -> tuple:
    """Bornes de zones (bpm), 5 zones façon Karvonen sur la réserve FC (`hr_max - hr_rest`)."""
    reserve = hr_max - hr_rest
    return tuple(round(hr_rest + p * reserve) for p in KARVONEN_HRR_PCT)


ZONE_BOUNDS_BPM = karvonen_zone_bounds_bpm()

# ID Garmin manifestement synthétiques. Les ID réels observés en 2025-2026 tournent
# autour de 1,8 à 2,1 × 10¹⁰ : un plafond à 2 × 10¹⁰ n'aurait donc rien d'improbable.
# 9 × 10¹⁰ est hors de toute plage Garmin plausible à ce jour — c'est la valeur que
# `tests/lint/test_synthetic_no_real_data.py` vérifie.
FAKE_ACTIVITY_ID_BASE = 90_000_000_000


def default_slope_factor(grade_pct: float) -> float:
    """Modèle pente→allure minimal, borné à des vitesses plausibles.

    Volontairement simpliste (ce n'est pas le modèle appris sur l'historique de
    la story #58) : fait varier la vitesse de façon déterministe sur une montée
    ou une descente synthétique. `sample_session` accepte un `slope_factor_fn`
    de remplacement pour imposer une courbe pente→allure précise — la courbe
    utilisée est exposée telle quelle dans `truth["speed_by_grade_curve"]`,
    pour un test qui la retrouverait par régression (story #58).

    - Montée : -3,5 % de vitesse par point de pente, plancher à 0,35× (une
      pente soutenue reste beaucoup plus lente, jamais à l'arrêt). Un
      coefficient plus dur (ex. -6 %/point) plafonne trop vite : sur une
      montée à 16 % (le maximum que produit `_spread_segments`), il ferait
      chuter le facteur au plancher, ce qui forcerait `_calibrate_base_speed`
      à relever d'autant la vitesse nominale pour tenir la distance visée —
      exactement la cause du bug d'allures irréalistes verrouillé par
      `TestPlausibleSpeeds`.
    - Descente : accélère jusqu'à un pic (+24 % vers -8 %), **puis ralentit à
      nouveau au-delà** — comme un coureur réel qui freine en descente
      technique — jusqu'à un plancher à 0,3×. Sans ce second segment, une
      pente à -20 % donnerait une vitesse ×2,2 (au-delà de ce qui est
      plausible en course à pied).
    """
    if grade_pct >= 0:
        return max(0.35, 1 - 0.035 * grade_pct)
    downhill = -grade_pct
    if downhill <= 8:
        factor = 1 + 0.03 * downhill  # pic à +24 % vers -8 %
    else:
        factor = 1.24 - 0.03 * (downhill - 8)  # freinage au-delà
    return max(0.3, min(1.24, factor))


def _zone_of_bpm(hr_bpm: float, zone_bounds_bpm: Sequence[float] = ZONE_BOUNDS_BPM) -> int:
    """Numéro de zone (1..len(bounds)-1) contenant `hr_bpm` ; sature aux bornes."""
    zones = len(zone_bounds_bpm) - 1
    for z in range(1, zones + 1):
        if hr_bpm < zone_bounds_bpm[z] or z == zones:
            return z
    return zones


def _grade_at(distance_m: float, segments: Sequence) -> float:
    """Pente (%) au point `distance_m`, selon les segments `(start_m, length_m, grade_pct)`.

    Segments non chevauchants attendus (le premier qui contient `distance_m`
    l'emporte) ; hors de tout segment, le parcours est plat (0 %).
    """
    for start, length, grade in segments:
        if start <= distance_m < start + length:
            return grade
    return 0.0


def _validate_zone_shares(zone_shares: Optional[dict], zone_bounds_bpm: Sequence[float]) -> None:
    if not zone_shares:
        return
    n_zones = len(zone_bounds_bpm) - 1
    total = sum(zone_shares.values())
    if abs(total - 1.0) > 1e-6:
        raise ValueError(f"zone_shares doit sommer à 1,0 (somme = {total})")
    for zone in zone_shares:
        if not (1 <= zone <= n_zones):
            raise ValueError(f"zone {zone} hors de la plage 1..{n_zones} (zone_bounds_bpm a {n_zones} zones)")


def sample_session(
    seed: int = 7,
    duration_s: int = 3600,
    base_speed_ms: float = 2.78,
    cadence_spm: float = 170.0,
    hr_base_bpm: float = 140.0,
    segments: Sequence = (),
    decoupling_pct: float = 0.0,
    fade_pct: float = 0.0,
    zone_shares: Optional[dict] = None,
    zone_bounds_bpm: Sequence[float] = ZONE_BOUNDS_BPM,
    dropout_windows: Sequence = (),
    slope_factor_fn: Optional[Callable[[float], float]] = None,
    noise: bool = True,
) -> tuple:
    """Génère une séance échantillonnée seconde par seconde, à vérité connue.

    Chaque propriété est **imposée** par un paramètre ; chaque valeur *mesurée*
    de `truth` est recalculée après coup depuis la liste `records` finale
    (jamais depuis un tableau interne pré-troncature) — voir le docstring du
    module. C'est ce que les tests du palier D comparent.

    - `segments` : tuple de `(start_m, length_m, grade_pct)` — montées
      (`grade_pct > 0`) ou descentes (`grade_pct < 0`), non chevauchantes,
      démarrant quand la distance horizontale parcourue atteint `start_m`.
      `()` (défaut) = parcours plat. D+/D− attendus : voir
      `truth["segments_gain_requested_m"]` / `["segments_loss_requested_m"]`.
    - `decoupling_pct` : la FC de la seconde moitié de la séance (en temps,
      pas en distance) est divisée par `(1 - decoupling_pct/100)` par rapport
      à la première — la dérive cardiaque (Pa:HR / découplage, story #45),
      mesurée dans `truth` comme `EF = moyenne(GAP)/moyenne(FC)` par moitié.
      Cette forme (division, pas multiplication) est choisie précisément pour
      que `decoupling_pct_measured` retombe sur `decoupling_pct` demandé, à
      bruit près, **sur un parcours plat sans fade** (ex. demander 4 → mesurer
      ≈ 3,98, pas 3,83 comme le donnerait une FC simplement multipliée par
      `1 + d/100`).

      La FC elle-même ne dépend **que** de cette dérive, jamais de la pente :
      l'effort est supposé constant (le modèle pente→allure absorbe déjà la
      pente), sinon une montée viendrait fausser silencieusement le
      découplage mesuré. **Un `fade_pct` actif, en revanche, augmente
      légitimement le découplage mesuré au-delà du `decoupling_pct` demandé** :
      le fade réduit le GAP du dernier tiers sans réduire la FC, exactement
      comme le ferait une dérive cardiaque plus forte — ce n'est pas un bug,
      c'est le signal réel que le découplage est censé capter (demander
      découplage 4 % + fade 8 % mesure un découplage global ≈ 9,1 %, pas 4 %,
      voir `TestDecoupling.test_ef_based_decoupling_matches_independent_recomputation_with_climb_and_fade`).
      Incompatible avec `zone_shares` (la FC y est pilotée par le calendrier
      de zones) : ce dernier prévaut si fourni, et
      `decoupling_pct_requested`/`decoupling_pct_measured` valent alors `None`.
    - `zone_shares` : dict `{zone: part_du_temps}` (parts sommant à 1,0, sinon
      `ValueError`) imposant la répartition du temps en zones FC (story #43).
      Calendrier déterministe (zones dans l'ordre croissant, reliquat
      d'arrondi sur la dernière) — pas un tirage aléatoire de l'ordre.
    - `fade_pct` : l'allure ajustée à la pente (GAP) du dernier tiers de la
      séance (en temps) est réduite de ce pourcentage par rapport au premier
      tiers (durabilité, story #48) — comparaison GAP à GAP, pas vitesse
      brute à vitesse brute, pour ne pas confondre fade et relief.
    - `dropout_windows` : tuple de `(début_s, fin_s)` (fin exclue) — secondes
      sans échantillon, comme un GPS qui décroche. La distance/l'altitude
      continuent d'être intégrées en interne pendant le trou (elles reprennent
      sans saut à la réapparition du signal), seule l'émission est coupée.
    - `noise` : `False` désactive tout bruit aléatoire (utile pour des
      assertions exactes en test) ; `True` (défaut) ajoute un bruit borné et
      centré, qui ne change pas les moyennes attendues à grande échelle.

    Déterministe : même `seed` + mêmes paramètres → mêmes échantillons,
    octet pour octet (pas d'horloge, pas d'aléatoire hors `random.Random(seed)`).
    """
    _validate_zone_shares(zone_shares, zone_bounds_bpm)
    rng = random.Random(seed)
    slope_factor_fn = slope_factor_fn or default_slope_factor
    segments = tuple(tuple(s) for s in segments)

    zone_schedule = None
    if zone_shares:
        zones_sorted = sorted(zone_shares)
        schedule_counts = {}
        allocated = 0
        for z in zones_sorted[:-1]:
            n = round(duration_s * zone_shares[z])
            schedule_counts[z] = n
            allocated += n
        schedule_counts[zones_sorted[-1]] = duration_s - allocated  # reliquat exact
        zone_schedule = []
        for z in zones_sorted:
            zone_schedule.extend([z] * schedule_counts[z])

    t_out, distance_out, altitude_out, hr_out, speed_out, cadence_out = [], [], [], [], [], []
    distance = altitude = 0.0
    third_t, half_t = duration_s / 3, duration_s / 2

    for t in range(duration_s):
        grade_pct = _grade_at(distance, segments)

        speed = base_speed_ms * slope_factor_fn(grade_pct)
        if t >= 2 * third_t:
            speed *= (1 - fade_pct / 100)
        if noise:
            speed *= (1 + rng.uniform(-0.02, 0.02))
        speed = max(0.1, speed)

        if zone_schedule is not None:
            zone = zone_schedule[t]
            lo, hi = zone_bounds_bpm[zone - 1], zone_bounds_bpm[zone]
            hr = (lo + hi) / 2
        else:
            # FC divisée (pas multipliée) par (1 − d/100) sur la seconde moitié : cette
            # forme fait que le découplage EF mesuré (voir `_measure_truth`) retombe
            # exactement sur `decoupling_pct` demandé, à bruit près, sur un parcours
            # plat sans fade — voir le docstring de `decoupling_pct` pour le calcul et
            # ce qui se passe quand un fade est aussi actif.
            hr = hr_base_bpm * (1 / (1 - decoupling_pct / 100) if t >= half_t else 1)
        if noise:
            hr += rng.uniform(-1.5, 1.5)

        cadence = cadence_spm + (rng.uniform(-2, 2) if noise else 0.0)

        distance += speed
        altitude += speed * grade_pct / 100

        if not any(a <= t < b for a, b in dropout_windows):
            t_out.append(t)
            distance_out.append(round(distance, 3))
            altitude_out.append(round(altitude, 3))
            hr_out.append(round(hr, 1))
            speed_out.append(round(speed, 3))
            cadence_out.append(round(cadence, 1))

    records = [
        {"t_s": t, "distance_m": d, "altitude_m": a, "hr_bpm": h, "speed_ms": s, "cadence_spm": c}
        for t, d, a, h, s, c in zip(t_out, distance_out, altitude_out, hr_out, speed_out, cadence_out)
    ]

    truth = _measure_truth(
        records, seed=seed, duration_s=duration_s, segments=segments,
        decoupling_pct=decoupling_pct, fade_pct=fade_pct, zone_shares=zone_shares,
        zone_bounds_bpm=zone_bounds_bpm, dropout_windows=dropout_windows,
        slope_factor_fn=slope_factor_fn,
    )
    return records, truth


def _measure_truth(
    records: list,
    *,
    seed: int,
    duration_s: int,
    segments: tuple,
    decoupling_pct: float,
    fade_pct: float,
    zone_shares: Optional[dict],
    zone_bounds_bpm: Sequence[float],
    dropout_windows: Sequence,
    slope_factor_fn: Callable[[float], float],
) -> dict:
    """Calcule tout champ *mesuré* de `truth` en ne lisant QUE `records`.

    Aucun tableau interne du générateur (pré-troncature par les trous de
    signal, pré-arrondi) n'est utilisé ici : un trou de signal ou une pente ne
    peut donc jamais fausser une mesure sans que ce soit visible dans les
    données réellement émises.
    """
    n = len(records)
    third_t, half_t = duration_s / 3, duration_s / 2

    # Pente et GAP (allure ajustée à la pente) recalculées entre échantillons
    # CONSÉCUTIFS DE `records` (pas entre secondes consécutives : un trou de
    # signal élargit juste l'intervalle, sans introduire de saut fictif).
    grades = [0.0] * n
    gaps = [None] * n
    gain = loss = 0.0
    for i in range(n):
        if i > 0:
            dd = records[i]["distance_m"] - records[i - 1]["distance_m"]
            da = records[i]["altitude_m"] - records[i - 1]["altitude_m"]
            grades[i] = (da / dd * 100) if dd else 0.0
            if da > 0:
                gain += da
            else:
                loss += -da
        factor = slope_factor_fn(grades[i]) or 1.0
        gaps[i] = records[i]["speed_ms"] / factor

    def _mean(xs):
        xs = [x for x in xs if x is not None]
        return sum(xs) / len(xs) if xs else None

    def _idx(pred):
        return [i for i, r in enumerate(records) if pred(r["t_s"])]

    hr_vals = [r["hr_bpm"] for r in records]

    # --- découplage (Pa:HR / EF, story #45) : EF = moyenne(GAP) / moyenne(FC),
    # par moitié de séance en TEMPS. Sans objet quand la FC est pilotée par
    # `zone_shares` plutôt que par la dérive.
    ef1 = ef2 = decoupling_measured = None
    if not zone_shares:
        idx1, idx2 = _idx(lambda t: t < half_t), _idx(lambda t: t >= half_t)
        mean_gap1, mean_hr1 = _mean([gaps[i] for i in idx1]), _mean([hr_vals[i] for i in idx1])
        mean_gap2, mean_hr2 = _mean([gaps[i] for i in idx2]), _mean([hr_vals[i] for i in idx2])
        if mean_gap1 is not None and mean_hr1:
            ef1 = mean_gap1 / mean_hr1
        if mean_gap2 is not None and mean_hr2:
            ef2 = mean_gap2 / mean_hr2
        if ef1 and ef2:
            decoupling_measured = round((ef1 - ef2) / ef1 * 100, 2)

    # --- fade (durabilité, story #48) : dernier tiers vs PREMIER tiers, sur le
    # GAP (pas la vitesse brute) pour ne pas confondre fade et relief.
    idx_first_third = _idx(lambda t: t < third_t)
    idx_middle_third = _idx(lambda t: third_t <= t < 2 * third_t)
    idx_last_third = _idx(lambda t: t >= 2 * third_t)
    gap_first_third = _mean([gaps[i] for i in idx_first_third])
    gap_last_third = _mean([gaps[i] for i in idx_last_third])
    fade_measured = (
        round((1 - gap_last_third / gap_first_third) * 100, 2)
        if gap_first_third and gap_last_third is not None else None
    )
    hr_by_third_bpm = [
        _mean([hr_vals[i] for i in idx_first_third]),
        _mean([hr_vals[i] for i in idx_middle_third]),
        _mean([hr_vals[i] for i in idx_last_third]),
    ]

    # --- zones FC (story #43) : comptage strictement sur les échantillons émis.
    zone_seconds_measured: dict = {}
    for hr in hr_vals:
        z = str(_zone_of_bpm(hr, zone_bounds_bpm))
        zone_seconds_measured[z] = zone_seconds_measured.get(z, 0) + 1

    # --- courbe pente→allure imposée (story #58) : clés en liste `[grade, facteur]`
    # (pas un dict à clé float) pour rester identique après un aller-retour JSON.
    grade_values = sorted({round(g, 4) for _, _, g in segments} | {0.0})
    speed_by_grade_curve = [[g, round(slope_factor_fn(g), 4)] for g in grade_values]

    segments_gain_requested_m = round(sum(length * grade / 100 for _, length, grade in segments if grade > 0), 2)
    segments_loss_requested_m = round(sum(length * -grade / 100 for _, length, grade in segments if grade < 0), 2)
    zone_bounds_method = "karvonen_hrr" if tuple(zone_bounds_bpm) == ZONE_BOUNDS_BPM else "custom"

    return {
        "seed": seed,
        "duration_s": duration_s,
        "n_samples": n,
        "dropout_seconds": duration_s - n,
        "dropout_windows": [list(w) for w in dropout_windows],

        "distance_m": records[-1]["distance_m"] if records else 0.0,
        "elevation_gain_m": round(gain, 2),
        "elevation_loss_m": round(loss, 2),
        "segments_requested": [list(s) for s in segments],
        "segments_gain_requested_m": segments_gain_requested_m,
        "segments_loss_requested_m": segments_loss_requested_m,

        "decoupling_pct_requested": decoupling_pct if not zone_shares else None,
        "decoupling_pct_measured": decoupling_measured,
        "ef_first_half": round(ef1, 6) if ef1 else None,
        "ef_second_half": round(ef2, 6) if ef2 else None,

        "fade_pct_requested": fade_pct,
        "fade_pct_measured": fade_measured,
        "gap_first_third_ms": round(gap_first_third, 3) if gap_first_third is not None else None,
        "gap_last_third_ms": round(gap_last_third, 3) if gap_last_third is not None else None,
        "hr_by_third_bpm": [round(v, 1) if v is not None else None for v in hr_by_third_bpm],

        "zone_bounds_bpm": list(zone_bounds_bpm),
        "zone_bounds_method": zone_bounds_method,
        "zone_shares_requested": {str(z): s for z, s in zone_shares.items()} if zone_shares else None,
        "zone_seconds_measured": zone_seconds_measured,

        "speed_by_grade_curve": speed_by_grade_curve,
    }


def _block(data: dict) -> str:
    return "```arc\n" + json.dumps(data, ensure_ascii=False, indent=1) + "\n```\n"


def _write(root: Path, rel: str, title: str, data: dict, prose: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"# {title}\n\n{_block(data)}\n{prose.strip()}\n", encoding="utf-8")


def _spread_segments(distance_m: float, gain_m: float, loss_m: float, n: int = 2) -> tuple:
    """Répartit `n` montées + `n` descentes le long du parcours, sommant à `gain_m`/`loss_m`.

    La pente est dérivée d'un budget de longueur cumulée (au plus ~85 % du
    parcours, et plafonnée à 16 %) plutôt que fixée en dur, pour rester
    cohérente même sur un fort D+/km (typiquement une sortie trail) SANS
    exiger des pentes qui forceraient ensuite la calibration de
    `base_speed_ms` vers des vitesses à plat non plausibles (une pente trop
    raide ferait plonger `default_slope_factor` en montée, donc
    `_calibrate_base_speed` devrait relever d'autant la vitesse nominale pour
    tenir la distance visée — voir
    `tests/data/test_synthetic_samples.py::TestPlausibleSpeeds`, qui
    verrouille des vitesses ≤ ~7 m/s sur des séances `build()` réelles).

    Les segments sont ensuite posés **séquentiellement** (montées puis
    descentes), séparés par des intervalles plats de taille égale, sur 97 %
    de la distance visée au plus : ils ne se chevauchent jamais et ne
    débordent jamais au-delà du parcours (un segment tronqué par une fin de
    parcours produirait moins de D+/D− que demandé). Si le plafond de pente
    ne suffit quand même pas à faire tenir le D+/D− demandé sur la distance
    visée (un D+/km extrême, hors de ce que produit `build()`), les longueurs
    sont réduites proportionnellement plutôt que de déborder : le D+/D−
    obtenu est alors inférieur à celui demandé, mais jamais un segment
    silencieusement tronqué en aval.
    """
    if distance_m <= 0 or (gain_m <= 0 and loss_m <= 0):
        return ()
    budget_m = 0.85 * distance_m
    vertical_total = gain_m + loss_m
    grade_pct = max(6.0, min(16.0, (vertical_total / budget_m) * 100)) if budget_m > 0 else 10.0

    climb_len = (gain_m / n / (grade_pct / 100)) if gain_m > 0 else 0.0
    descent_len = (loss_m / n / (grade_pct / 100)) if loss_m > 0 else 0.0
    seg_lengths = ([climb_len] * n if gain_m > 0 else []) + ([descent_len] * n if loss_m > 0 else [])
    seg_grades = ([grade_pct] * n if gain_m > 0 else []) + ([-grade_pct] * n if loss_m > 0 else [])
    if not seg_lengths:
        return ()

    placement_cap_m = 0.97 * distance_m
    if sum(seg_lengths) > placement_cap_m:
        scale = placement_cap_m / sum(seg_lengths)
        seg_lengths = [length * scale for length in seg_lengths]

    gap = max(0.0, (placement_cap_m - sum(seg_lengths)) / (len(seg_lengths) + 1))
    segments, cursor = [], gap
    for length, grade in zip(seg_lengths, seg_grades):
        segments.append((round(cursor, 1), round(length, 1), grade))
        cursor += length + gap
    return tuple(segments)


def _calibrate_base_speed(duration_s: int, target_distance_m: float, segments: tuple,
                           slope_factor_fn: Callable[[float], float],
                           tol_rel: float = 0.01, max_iter: int = 20) -> float:
    """Cherche `base_speed_ms` (dichotomie, sans bruit) pour que la distance finale
    d'une séance de `duration_s` secondes avec ces `segments` colle à `target_distance_m`.
    """
    lo, hi = 0.2, 12.0
    mid = (lo + hi) / 2
    for _ in range(max_iter):
        mid = (lo + hi) / 2
        recs, _ = sample_session(seed=0, duration_s=duration_s, base_speed_ms=mid,
                                  segments=segments, slope_factor_fn=slope_factor_fn, noise=False)
        dist = recs[-1]["distance_m"] if recs else 0.0
        if abs(dist - target_distance_m) <= tol_rel * max(target_distance_m, 1.0):
            break
        if dist < target_distance_m:
            lo = mid
        else:
            hi = mid
    return mid


def _write_samples(root: Path, activity_id: int, *, seed: int, duration_s: int,
                    target_distance_m: float, target_gain_m: float, target_loss_m: float,
                    target_avg_hr_bpm: float, cadence_spm: float) -> None:
    """Écrit les échantillons seconde par seconde d'une séance (`--with-samples`).

    Calibré pour rester cohérent avec le Markdown de la même séance : la
    distance finale, le D+/D− et la FC moyenne des échantillons visent la
    distance, le dénivelé et la FC moyenne déjà écrits dans le bloc ```arc```
    de l'activité (`tests/data/test_synthetic_samples.py::TestMarkdownAgreement`
    vérifie l'accord, à tolérance documentée).

    Emplacement brut proposé par la story d'ingestion FIT (#42) :
    `activities/fit/<garmin_activity_id>.json`, gitignoré (donnée jetable,
    reconstruite depuis le Markdown + les FIT réels — voir `tests/README.md`).
    """
    segments = _spread_segments(target_distance_m, target_gain_m, target_loss_m)
    base_speed_ms = _calibrate_base_speed(duration_s, target_distance_m, segments, default_slope_factor)
    records, truth = sample_session(
        seed=seed, duration_s=duration_s, base_speed_ms=base_speed_ms, segments=segments,
        hr_base_bpm=target_avg_hr_bpm, cadence_spm=cadence_spm, noise=True,
    )
    path = root / "activities/fit" / f"{activity_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"activity_id": activity_id, "records": records, "truth": truth},
                                ensure_ascii=False), encoding="utf-8")


def _splits(rng, km: int, pace_s: float, hr: float, dplus_total: float, trail: bool) -> list:
    rows, left = [], dplus_total
    for k in range(1, km + 1):
        gain = round(min(left, rng.uniform(0, 2.2 * dplus_total / max(km, 1)))) if trail else rng.randint(0, 6)
        left -= gain
        loss = round(gain * rng.uniform(0.6, 1.3))
        duration = round(pace_s * (1 + gain / 400) * rng.uniform(0.96, 1.04))
        label = "Échauffement" if k == 1 else ("Montée" if gain > 40 else ("Retour au calme" if k == km else "Allure"))
        rows.append([k, duration, gain, loss, round(hr + gain / 12 + rng.uniform(-4, 4)),
                     round(3600 / duration * 1.25, 1), rng.randint(160, 176), label])
    return rows


def build(root: Path, days: int = 120, today: date | None = None, sport: str = "trail", seed: int = 7,
          with_samples: bool = False) -> Path:
    rng = random.Random(seed)
    today = today or date.today()
    start = today - timedelta(days=days - 1)
    trail = sport == "trail"
    race = today + timedelta(days=54)

    (root / "config").mkdir(parents=True, exist_ok=True)
    (root / "config/workspace.user.toml").write_text(
        f'[sport]\nprimary = "{sport}"\n\n[health]\nmorning_check = "full"\n', encoding="utf-8")
    for folder in ("activities", "medical", "nutrition", "planning", "rapports", "resources"):
        (root / folder).mkdir(parents=True, exist_ok=True)

    # Adidas Adizero SL : seuil bas (50 km, pas les 500 km d'une vraie chaussure)
    # exprès — les séances qualité (~57 km cumulés sur la fenêtre, déterministe,
    # cf. `data["gear_id"] = "adizero-sl"` plus bas) le dépassent TOUJOURS, ce qui
    # verrouille `alert: true` dans les goldens sans dépendre d'un tirage `rng`
    # (revue PR #85, point 7).
    (root / "planning/Runner_Profile.md").write_text(f"""# Profil de l'athlète

## Physiologie

- **FC max** : {HR_MAX}
- **FC de repos de référence** : {HR_REST}
- **FC au seuil** : 172
- **Sexe** : H
- **Poids de forme** : 68,5 kg

## Matériel & lieux

- **Lieu par défaut** : Tournai
- **Créneau habituel** : pause de midi (12 h-14 h)

### Chaussures

- Hoka Speedgoat 5 (bleue) — depuis 2026-01-01 — alerte 700 km — id: hoka-speedgoat-5-bleue (par défaut)
- Adidas Adizero SL — alerte 50 km — id: adizero-sl
- Nike Pegasus (retirée)
""", encoding="utf-8")
    (root / "planning/active_objective.md").write_text(f"""# Objectif actif

## Course visée

- **Nom** : {"Trail des Collines" if trail else "Marathon de Lille"}
- **Date** : {race.isoformat()}
- **Distance** : {"52 km" if trail else "42,195 km"}
- **Dénivelé positif** : {"2 400 m" if trail else ""}
- **Lieu** : Tournai

## Objectif de performance

- **Objectif principal** : {"finir en restant lucide" if trail else "temps cible"}
- **Temps visé** : {"7 h 00" if trail else "3 h 15"}

## Paramètres d'entraînement

- **Volume hebdomadaire de départ** : 5 h
- **Volume hebdomadaire cible** : 8 h
- **Séances qualité par semaine** : 2
- **Lieu d'entraînement par défaut** : Tournai
""", encoding="utf-8")

    fitness = 0.0
    for i in range(days):
        day = start + timedelta(days=i)
        iso = day.isoformat()
        week_index = i // 7
        deload = week_index % 4 == 3
        ramp = 0.75 + 0.5 * i / days
        fatigue = rng.random()

        # --- santé -------------------------------------------------------
        hrv = round(62 + 6 * (fitness / 60) - 9 * fatigue * (1.3 if not deload else 0.6) + rng.uniform(-3, 3))
        rhr = round(HR_REST + (6 if rng.random() < 0.05 else 0) + 3 * fatigue + rng.uniform(-2, 2))
        readiness = max(20, min(96, round(78 - 30 * fatigue + rng.uniform(-6, 6))))
        verdict = "green" if readiness >= 60 else ("amber" if readiness >= 40 else "red")
        reason = {
            "green": "Triade dans la norme : séance maintenue.",
            "amber": "HRV sous la bande, FC de repos stable : garder l'aérobie, couper l'intensité.",
            "red": "HRV basse et FC de repos élevée : repos ou Z1 strict.",
        }[verdict]
        sleep = round(6.2 * 3600 + 1.8 * 3600 * rng.random())
        health_data = {
            "arc": 1, "kind": "health", "date": iso, "morning_check": "full",
            "sleep_total_s": sleep, "sleep_deep_s": round(sleep * 0.18), "sleep_light_s": round(sleep * 0.55),
            "sleep_rem_s": round(sleep * 0.22), "sleep_score": max(40, min(95, round(sleep / 360 - 2))),
            "hrv_overnight_ms": hrv, "hrv_baseline_low_ms": 56, "hrv_baseline_high_ms": 68,
            "hrv_status": "balanced" if hrv >= 56 else "low",
            "resting_hr_bpm": rhr, "readiness_score": readiness,
            "body_battery_high": min(100, readiness + 12), "body_battery_low": 20, "stress_avg": round(25 + 20 * fatigue),
            "verdict": verdict, "verdict_reason": reason,
        }
        # `weight_kg` omis un jour sur cinq (#36), afin que le repli sur `nutrition.weight_kg`
        # (`merge_weight_kg`) soit réellement exercé par les goldens : sans ce trou, la santé
        # porte un poids TOUS les jours et la branche nutrition du merge ne serait jamais
        # prise dans les fixtures. Le bruit est tiré INCONDITIONNELLEMENT (même sur un jour
        # omis, la valeur est juste jetée) pour que le flux `rng` partagé — et donc toutes
        # les valeurs tirées ensuite — ne se décale pas selon `i % 5`.
        weight_noise = rng.uniform(-0.3, 0.3)
        if i % 5 != 0:
            health_data["weight_kg"] = round(69.2 - 0.6 * i / days + weight_noise, 1)
        _write(root, f"medical/{iso}_health.md", f"Santé du {iso}", health_data, f"## Analyse\n\n{reason}")

        # --- séance --------------------------------------------------------
        weekday = day.weekday()
        plan = {0: "rest", 1: "quality", 2: "easy", 3: "strength", 4: "rest", 5: "long", 6: "easy"}[weekday]
        if plan == "rest" or (deload and plan == "easy" and weekday == 6):
            continue
        if plan == "strength":
            duration = 2400
            data = {"arc": 1, "kind": "activity", "date": iso, "sport": "strength", "duration_s": duration,
                    "rpe": 6, "missing_reason": {"avg_hr_bpm": "pas de ceinture cardio"}}
            _write(root, f"activities/{iso}_strength.md", f"Séance du {iso} — Renforcement", data,
                   "## Contenu\n\n- Squat 4 × 8\n- Fentes 3 × 10\n- Gainage 3 × 45 s")
            fitness += 0.4
            continue
        km = {"quality": 10, "easy": 8, "long": 18}[plan]
        km = max(5, round(km * ramp * (0.7 if deload else 1.0)))
        pace = {"quality": 318, "easy": 352, "long": 372}[plan] - fitness * 0.4
        hr = {"quality": 158, "easy": 138, "long": 142}[plan] + rng.uniform(-3, 3)
        kind = "trail" if trail and plan != "quality" else "running"
        dplus = round(km * (48 if kind == "trail" else 4) * rng.uniform(0.7, 1.3))
        splits = _splits(rng, km, pace, hr, dplus, kind == "trail")
        duration = sum(r[1] for r in splits) + rng.randint(20, 90)
        data = {
            "arc": 1, "kind": "activity", "date": iso, "sport": kind,
            "garmin_activity_id": FAKE_ACTIVITY_ID_BASE + i, "name": {"quality": "Côtes 8 × 90 s" if trail else "Seuil 3 × 10 min",
                                                             "easy": "Endurance fondamentale", "long": "Sortie longue"}[plan],
            "location": "Tournai", "start_time": f"{iso}T12:10:00+02:00",
            "distance_m": km * 1000, "duration_s": duration, "moving_duration_s": duration - 30,
            "elevation_gain_m": sum(r[2] for r in splits), "elevation_loss_m": sum(r[3] for r in splits),
            "avg_hr_bpm": round(hr + 2), "max_hr_bpm": round(hr + 22),
            "training_effect_aerobic": round(2.4 + km / 10 + (0.8 if plan == "quality" else 0), 1),
            "training_effect_anaerobic": 1.8 if plan == "quality" else 0.4,
            "calories_kcal": km * 68, "avg_cadence_spm": 168,
            "splits_cols": ["km", "duration_s", "elev_gain_m", "elev_loss_m", "avg_hr_bpm", "max_speed_kmh", "cadence_spm", "label"],
            "splits": splits,
        }
        # Kilométrage chaussures (#40) : `gear_id` posé sur `plan`, jamais sur un tirage
        # `rng` — sans quoi ajouter/retirer une chaussure décalerait tout le flux aléatoire
        # partagé qui suit (même précaution que le poids omis un jour sur cinq, #36).
        # Séances qualité -> paire explicite ; sortie longue/facile -> aucun `gear_id`,
        # pour exercer l'attribution par défaut (`(par défaut)` du profil synthétique
        # ci-dessus) plutôt que l'identifiant explicite sur toutes les séances.
        if plan == "quality":
            data["gear_id"] = "adizero-sl"
        # Glucides/fluide/pesées sur certaines sorties longues (#41, entraînement
        # digestif) : motifs déterministes sur `i` uniquement, JAMAIS un nouveau tirage
        # `rng` — même précaution que `weight_kg`/`gear_id` ci-dessus, sans quoi ajouter
        # ce champ décalerait tout le flux aléatoire partagé qui suit selon `i % N`.
        if plan == "long" and duration > 5400 and i % 2 == 0:
            data["carbs_g"] = round(30 + 6 * (i % 6))            # 30-60 g déclarés
            data["fluid_intake_ml"] = round(500 + 50 * (i % 4))
            if i % 4 == 0:
                data["weight_pre_kg"] = round(69.5 - 0.4 * i / days, 1)
                data["weight_post_kg"] = round(data["weight_pre_kg"] - 0.5 - 0.1 * (i % 3), 1)
        if rng.random() < 0.8:
            data["recovery_hr_bpm"] = round(24 + 10 * rng.random() - 8 * fatigue)
        else:
            data["missing_reason"] = {"recovery_hr_bpm": "activité validée avant les 2 minutes"}
        _write(root, f"activities/{iso}_{kind}.md", f"Séance du {iso} — {data['name']}", data,
               f"## Analyse du coach\n\nSéance **{data['name'].lower()}** conforme. FC moyenne {data['avg_hr_bpm']} bpm, "
               f"HRR {data.get('recovery_hr_bpm', '—')}.\n\n- Allure régulière sur le plat\n- Montées gérées en marche rapide")
        if with_samples:
            _write_samples(root, data["garmin_activity_id"], seed=seed + i, duration_s=duration,
                            target_distance_m=float(data["distance_m"]),
                            target_gain_m=float(data["elevation_gain_m"]),
                            target_loss_m=float(data["elevation_loss_m"]),
                            target_avg_hr_bpm=float(data["avg_hr_bpm"]),
                            cadence_spm=float(data["avg_cadence_spm"]))
        fitness += km * 0.12

    # --- météo (7 jours autour d'aujourd'hui) ---------------------------------
    for k in range(-2, 5):
        day = today + timedelta(days=k)
        t = round(14 + 10 * rng.random())
        cat = "green" if t < 22 else ("yellow" if t < 28 else "orange")
        _write(root, f"medical/{day.isoformat()}_meteo.md", f"Météo — Tournai — {day.isoformat()}", {
            "arc": 1, "kind": "weather", "date": day.isoformat(), "location": "Tournai", "category": cat,
            "temp_min_c": t - 8, "temp_max_c": t, "wind_kmh": round(8 + 20 * rng.random()),
            "precip_mm": round(3 * rng.random(), 1), "uv_index": 4,
            "best_slot": "midday" if cat == "green" else "morning",
            "slot_reason": "Conditions stables toute la journée." if cat == "green" else "Chaleur l'après-midi : sortir tôt.",
        }, "## Ajustements\n\n- Hydratation normale")

    # --- semaine courante + précédente ---------------------------------------
    for offset in (-7, 0):
        monday = today - timedelta(days=today.weekday()) + timedelta(days=offset)
        sessions = []
        for d, sp, title, dur, dist, dp, inten in (
            (1, "trail" if trail else "running", "Côtes 8 × 90 s" if trail else "Seuil 3 × 10 min", 4200, None, 450 if trail else None, "vo2max"),
            (2, "running", "Endurance fondamentale 50 min", 3000, None, None, "endurance"),
            (3, "strength", "Renforcement 40 min", 2400, None, None, "strength"),
            (5, "trail" if trail else "running", "Sortie longue 25 km / 900 m D+" if trail else "Sortie longue 26 km", None, 25000, 900 if trail else None, "endurance"),
            (6, "running", "Footing récupération 40 min", 2400, None, None, "recovery"),
        ):
            when = monday + timedelta(days=d)
            s = {"date": when.isoformat(), "sport": sp, "title": title, "intensity": inten,
                 "outdoor": sp != "strength"}
            if dur:
                s["planned_duration_s"] = dur
            if dist:
                s["planned_distance_m"] = dist
            if dp:
                s["planned_elevation_m"] = dp
            s["status"] = "done" if when < today else "planned"
            if when < today and d == 6 and offset == 0:
                s["status"] = "missed"
            sessions.append(s)
        _write(root, f"planning/Semaine_{monday.isoformat()}.md", f"Semaine du {monday.isoformat()}", {
            "arc": 1, "kind": "week", "week_start": monday.isoformat(), "location": "Tournai",
            "phase": "Spécifique", "target_duration_s": 28800, "sessions": sessions,
        }, "## Intention\n\nConsolider le volume, une seule séance de qualité si la HRV reste dans la bande.")

    # --- rapports hebdomadaires ------------------------------------------------
    for w in range(1, 4):
        end = today - timedelta(days=today.weekday() + 1) - timedelta(weeks=w - 1)
        begin = end - timedelta(days=6)
        _write(root, f"rapports/{end.isoformat()}_rapport.md", f"Bilan de la semaine du {begin.isoformat()}", {
            "arc": 1, "kind": "report", "date": end.isoformat(), "report_type": "weekly",
            "title": f"Bilan de la semaine du {begin.isoformat()}",
            "period_start": begin.isoformat(), "period_end": end.isoformat(),
        }, f"""## Synthèse

Semaine **conforme au plan** : charge en hausse contrôlée, HRV stable.

| Indicateur | Valeur |
|---|---|
| Séances | 5 / 5 |
| Volume | 7 h 40 |
| D+ | 1 650 m |

## Pour la semaine prochaine

- Garder la sortie longue en endurance stricte
- Une seule séance de côtes""")

    # --- nutrition (quelques jours) --------------------------------------------
    # `weight_kg` est délibérément différent de `medical/<date>_health.md` le même jour
    # (#36) : ça exerce la règle de fusion (santé, mesure du matin, prioritaire) plutôt
    # que de la laisser non testée par simple absence de conflit. `target_weight_kg` est
    # constant, comme un objectif qui ne change pas d'un jour à l'autre. Valeur du poids
    # calculée SANS `rng` (fonction déterministe de `k` seule) : consommer le flux `rng`
    # ici décalerait tous les tirages suivants et changerait des valeurs déjà couvertes
    # par le golden (apports, dépense…) sans rapport avec #36.
    for k in range(0, 14, 2):
        day = today - timedelta(days=k)
        _write(root, f"nutrition/{day.isoformat()}_nutrition.md", f"Nutrition du {day.isoformat()}", {
            "arc": 1, "kind": "nutrition", "date": day.isoformat(),
            "intake_kcal": 2400 + rng.randint(-200, 300), "burned_kcal": 2500 + rng.randint(-300, 500),
            "carbs_g": 320 + rng.randint(-40, 60), "protein_g": 115, "fat_g": 78, "hydration_ml": 2400,
            "weight_kg": round(70.5 - 0.05 * k, 1), "target_weight_kg": 67.0,
        }, "## Commentaire\n\nApports cohérents avec la charge.")
    return root


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Workspace synthétique au contrat ```arc")
    parser.add_argument("dir")
    parser.add_argument("--days", type=int, default=120)
    parser.add_argument("--today")
    parser.add_argument("--sport", choices=("trail", "road"), default="trail")
    parser.add_argument("--with-samples", action="store_true",
                         help="génère aussi activities/fit/<id>.json (échantillons seconde par seconde)")
    args = parser.parse_args(argv)
    root = build(Path(args.dir), args.days, date.fromisoformat(args.today) if args.today else None, args.sport,
                 with_samples=args.with_samples)
    print(root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
