"""Workspace synthétique au contrat ```arc, déterministe (graine fixe).

Sert aux tests du palier A (tableau de bord de bout en bout) et à la
vérification visuelle :

    python3 -m tests.lib.synthetic DIR [--days 120] [--today AAAA-MM-JJ] [--sport trail|road]
    python3 -m tests.lib.synthetic DIR --with-samples   # + échantillons seconde par seconde

Les valeurs sont plausibles, pas réalistes : un bloc de base, une montée de
charge, une semaine allégée toutes les quatre. Aucune donnée réelle.

## Échantillons seconde par seconde (`sample_session`)

Toute l'épopée FIT (zones, GAP, découplage, VAM, descente, durabilité, modèle
pente→allure — voir les stories de l'épopée #21) a besoin de séries seconde
par seconde dont le résultat attendu est connu à l'avance. `sample_session`
génère une telle série avec des **propriétés paramétrées** (pente et longueur
de montée, dérive FC imposée, répartition de zones imposée, fade de fin de
séance, trous de signal) et renvoie, à côté des échantillons, un dict
`truth` : ce que le générateur affirme avoir produit, mesuré sur les données
qu'il vient d'écrire (pas seulement les paramètres demandés en entrée). Les
tests du palier D (`tests/data/test_synthetic_samples.py`) vérifient que
mesuré ≈ demandé, à la tolérance documentée dans chaque test.

Champs par échantillon — alignés sur le schéma `activity_sample` de
`scripts/arc_index.py` (colonnes `t_s, distance_m, altitude_m, hr_bpm,
speed_ms, cadence_spm`), pour que l'ingestion FIT (story #42, non encore
implémentée) puisse consommer ce format sans traduction : un fichier FIT réel,
lu via `skills/fit-download/scripts/download_fit.py` (champs bruts
`fitparse` : `timestamp`, `distance`, `heart_rate`, `enhanced_altitude` ou
`altitude`, `enhanced_speed` ou `speed`, `cadence`), s'y ramène par le mapping
`{heart_rate → hr_bpm, distance → distance_m, altitude → altitude_m,
speed → speed_ms, cadence → cadence_spm, timestamp → t_s relatif au départ}`.
Aucune coordonnée GPS n'est générée (`lat`/`lon` restent hors du format —
inutiles aux KPI de l'épopée FIT, et ça évite tout risque de ressemblance
avec un lieu réel).

`--with-samples` écrit, pour chaque séance running/trail générée, un fichier
`activities/fit/<garmin_activity_id>.json` (`{"activity_id", "records",
"truth"}`) — l'emplacement brut proposé par la story d'ingestion (#42).
"""

from __future__ import annotations

import argparse
import json
import random
from datetime import date, timedelta
from pathlib import Path
from typing import Callable, Optional

HR_REST, HR_MAX = 48, 188

# Bornes de zones FC par défaut (bpm), 5 zones : Zi = [ZONE_BOUNDS_BPM[i-1], ZONE_BOUNDS_BPM[i]).
# Cohérentes avec le profil type de `planning/Runner_Profile.md` (FC max 188) — valeurs
# rondes, pas une méthode de calcul (Karvonen/LTHR) : la story #43 la rendra configurable.
ZONE_BOUNDS_BPM = (90, 130, 150, 160, 170, 190)

# ID Garmin manifestement synthétiques (même convention que `build()` : jamais un ID plausible).
FAKE_ACTIVITY_ID_BASE = 20_000_000_000


def _default_slope_factor(grade_pct: float) -> float:
    """Modèle pente→allure minimal : -6 % de vitesse par point de pente en montée.

    Volontairement simpliste (ce n'est pas le modèle de la story #58, qui sera
    appris sur l'historique) : sert seulement à faire varier la vitesse pendant
    une montée synthétique de façon déterministe. `sample_session` accepte un
    `slope_factor_fn` de remplacement pour imposer une courbe pente→allure précise.
    """
    return max(0.2, 1 - 0.06 * grade_pct)


def _zone_of_bpm(hr_bpm: float, zone_bounds_bpm: tuple = ZONE_BOUNDS_BPM) -> int:
    """Numéro de zone (1..len(bounds)-1) contenant `hr_bpm` ; sature aux bornes."""
    zones = len(zone_bounds_bpm) - 1
    for z in range(1, zones + 1):
        if hr_bpm < zone_bounds_bpm[z] or z == zones:
            return z
    return zones


def sample_session(
    seed: int = 7,
    duration_s: int = 3600,
    base_speed_ms: float = 2.78,
    cadence_spm: float = 170.0,
    hr_base_bpm: float = 140.0,
    climb_start_m: Optional[float] = None,
    climb_length_m: float = 1000.0,
    climb_grade_pct: float = 8.0,
    decoupling_pct: float = 0.0,
    fade_pct: float = 0.0,
    zone_shares: Optional[dict] = None,
    zone_bounds_bpm: tuple = ZONE_BOUNDS_BPM,
    dropout_windows: tuple = (),
    slope_factor_fn: Optional[Callable[[float], float]] = None,
    noise: bool = True,
) -> tuple[list, dict]:
    """Génère une séance échantillonnée seconde par seconde, à vérité connue.

    Chaque propriété est **imposée** par un paramètre et **mesurée** en retour
    dans `truth`, sur les données réellement écrites (pas seulement rejouer le
    paramètre d'entrée) — c'est ce que les tests du palier D comparent.

    - `climb_start_m` / `climb_length_m` / `climb_grade_pct` : une montée
      unique, démarrant quand la distance parcourue atteint `climb_start_m`,
      sur `climb_length_m` mètres horizontaux, à la pente donnée. `None` =
      parcours plat. D+ attendu ≈ `climb_length_m * climb_grade_pct / 100`.
    - `decoupling_pct` : la FC de la seconde moitié de la séance est relevée
      de ce pourcentage par rapport à la première (à allure/effort équivalents)
      — la dérive cardiaque (Pa:HR / découplage, story #45) mesurable dans les
      données brutes. Incompatible avec `zone_shares` (la FC y est pilotée par
      le calendrier de zones, pas par la dérive) : ce dernier prévaut si fourni.
    - `zone_shares` : dict `{zone: part_du_temps}` (parts sommant à 1) imposant
      la répartition du temps en zones FC (story #43). Le calendrier est
      déterministe (zones dans l'ordre croissant, reliquat d'arrondi sur la
      dernière) — pas un tirage aléatoire de l'ordre des zones.
    - `fade_pct` : la vitesse du dernier tiers de la séance est réduite de ce
      pourcentage par rapport au reste (fade / durabilité, story #48).
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
    rng = random.Random(seed)
    slope_factor_fn = slope_factor_fn or _default_slope_factor
    climb_end_m = None if climb_start_m is None else climb_start_m + climb_length_m

    zone_schedule = None
    zone_seconds_requested = None
    if zone_shares:
        zones_sorted = sorted(zone_shares)
        zone_seconds_requested = {}
        allocated = 0
        for z in zones_sorted[:-1]:
            n = round(duration_s * zone_shares[z])
            zone_seconds_requested[z] = n
            allocated += n
        zone_seconds_requested[zones_sorted[-1]] = duration_s - allocated  # reliquat exact
        zone_schedule = []
        for z in zones_sorted:
            zone_schedule.extend([z] * zone_seconds_requested[z])

    t_out, distance_out, altitude_out, hr_out, speed_out, cadence_out = [], [], [], [], [], []
    distance = altitude = 0.0
    hr_first_half, hr_second_half = [], []
    speed_first_two_thirds, speed_last_third = [], []
    zone_seconds_from_hr = {}

    for t in range(duration_s):
        grade_pct = 0.0
        if climb_start_m is not None and climb_start_m <= distance < climb_end_m:
            grade_pct = climb_grade_pct

        speed = base_speed_ms * slope_factor_fn(grade_pct)
        if t >= 2 * duration_s / 3:
            speed *= (1 - fade_pct / 100)
            speed_last_third.append(speed)
        else:
            speed_first_two_thirds.append(speed)
        if noise:
            speed *= (1 + rng.uniform(-0.02, 0.02))
        speed = max(0.1, speed)

        if zone_schedule is not None:
            zone = zone_schedule[t]
            lo, hi = zone_bounds_bpm[zone - 1], zone_bounds_bpm[zone]
            hr = (lo + hi) / 2
        else:
            hr = hr_base_bpm * (1 + decoupling_pct / 100 if t >= duration_s / 2 else 1)
        if noise:
            hr += rng.uniform(-1.5, 1.5)
        (hr_first_half if t < duration_s / 2 else hr_second_half).append(hr)
        zone_seconds_from_hr[_zone_of_bpm(hr, zone_bounds_bpm)] = \
            zone_seconds_from_hr.get(_zone_of_bpm(hr, zone_bounds_bpm), 0) + 1

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

    avg_hr_first = sum(hr_first_half) / len(hr_first_half) if hr_first_half else None
    avg_hr_second = sum(hr_second_half) / len(hr_second_half) if hr_second_half else None
    decoupling_measured = (
        round((avg_hr_second / avg_hr_first - 1) * 100, 2)
        if avg_hr_first and avg_hr_second else None
    )
    avg_speed_first = sum(speed_first_two_thirds) / len(speed_first_two_thirds) if speed_first_two_thirds else None
    avg_speed_last = sum(speed_last_third) / len(speed_last_third) if speed_last_third else None
    fade_measured = (
        round((1 - avg_speed_last / avg_speed_first) * 100, 2)
        if avg_speed_first and avg_speed_last else None
    )
    elevation_gain_m = round(max(0.0, altitude_out[-1] if altitude_out else 0.0), 2)

    truth = {
        "seed": seed,
        "duration_s": duration_s,
        "n_samples": len(records),
        "distance_m": distance_out[-1] if distance_out else 0.0,
        "elevation_gain_m": elevation_gain_m,
        "climb_requested_gain_m": (
            round(climb_length_m * climb_grade_pct / 100, 2) if climb_start_m is not None else None
        ),
        "decoupling_pct_requested": decoupling_pct if not zone_shares else None,
        "decoupling_pct_measured": decoupling_measured,
        "fade_pct_requested": fade_pct,
        "fade_pct_measured": fade_measured,
        "zone_seconds_requested": zone_seconds_requested,
        "zone_seconds_from_hr": zone_seconds_from_hr,
        "dropout_windows": list(dropout_windows),
        "dropout_seconds": duration_s - len(records),
    }
    return records, truth


def _block(data: dict) -> str:
    return "```arc\n" + json.dumps(data, ensure_ascii=False, indent=1) + "\n```\n"


def _write(root: Path, rel: str, title: str, data: dict, prose: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"# {title}\n\n{_block(data)}\n{prose.strip()}\n", encoding="utf-8")


def _write_samples(root: Path, activity_id: int, **kwargs) -> None:
    """Écrit les échantillons seconde par seconde d'une séance (`--with-samples`).

    Emplacement brut proposé par la story d'ingestion FIT (#42) :
    `activities/fit/<garmin_activity_id>.json`, gitignoré (donnée jetable,
    reconstruite depuis le Markdown + les FIT réels — voir `tests/README.md`).
    """
    records, truth = sample_session(**kwargs)
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
        _write(root, f"medical/{iso}_health.md", f"Santé du {iso}", {
            "arc": 1, "kind": "health", "date": iso, "morning_check": "full",
            "sleep_total_s": sleep, "sleep_deep_s": round(sleep * 0.18), "sleep_light_s": round(sleep * 0.55),
            "sleep_rem_s": round(sleep * 0.22), "sleep_score": max(40, min(95, round(sleep / 360 - 2))),
            "hrv_overnight_ms": hrv, "hrv_baseline_low_ms": 56, "hrv_baseline_high_ms": 68,
            "hrv_status": "balanced" if hrv >= 56 else "low",
            "resting_hr_bpm": rhr, "readiness_score": readiness,
            "body_battery_high": min(100, readiness + 12), "body_battery_low": 20, "stress_avg": round(25 + 20 * fatigue),
            "weight_kg": round(69.2 - 0.6 * i / days + rng.uniform(-0.3, 0.3), 1),
            "verdict": verdict, "verdict_reason": reason,
        }, f"## Analyse\n\n{reason}")

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
            "garmin_activity_id": 20000000000 + i, "name": {"quality": "Côtes 8 × 90 s" if trail else "Seuil 3 × 10 min",
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
        if rng.random() < 0.8:
            data["recovery_hr_bpm"] = round(24 + 10 * rng.random() - 8 * fatigue)
        else:
            data["missing_reason"] = {"recovery_hr_bpm": "activité validée avant les 2 minutes"}
        _write(root, f"activities/{iso}_{kind}.md", f"Séance du {iso} — {data['name']}", data,
               f"## Analyse du coach\n\nSéance **{data['name'].lower()}** conforme. FC moyenne {data['avg_hr_bpm']} bpm, "
               f"HRR {data.get('recovery_hr_bpm', '—')}.\n\n- Allure régulière sur le plat\n- Montées gérées en marche rapide")
        if with_samples:
            _write_samples(root, data["garmin_activity_id"], seed=seed + i, duration_s=duration,
                            base_speed_ms=km * 1000 / duration,
                            climb_grade_pct=8.0 if kind == "trail" else 0.0,
                            climb_length_m=min(1000.0, km * 1000 / 3) if kind == "trail" else 0.0,
                            climb_start_m=km * 500.0 if kind == "trail" else None,
                            hr_base_bpm=hr, cadence_spm=168.0)
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
    for k in range(0, 14, 2):
        day = today - timedelta(days=k)
        _write(root, f"nutrition/{day.isoformat()}_nutrition.md", f"Nutrition du {day.isoformat()}", {
            "arc": 1, "kind": "nutrition", "date": day.isoformat(),
            "intake_kcal": 2400 + rng.randint(-200, 300), "burned_kcal": 2500 + rng.randint(-300, 500),
            "carbs_g": 320 + rng.randint(-40, 60), "protein_g": 115, "fat_g": 78, "hydration_ml": 2400,
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
