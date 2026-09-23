"""Workspace synthétique au contrat ```arc, déterministe (graine fixe).

Sert aux tests du palier A (tableau de bord de bout en bout) et à la
vérification visuelle :

    python3 -m tests.lib.synthetic DIR [--days 120] [--today AAAA-MM-JJ] [--sport trail|road]

Les valeurs sont plausibles, pas réalistes : un bloc de base, une montée de
charge, une semaine allégée toutes les quatre. Aucune donnée réelle.
"""

from __future__ import annotations

import argparse
import json
import random
from datetime import date, timedelta
from pathlib import Path

HR_REST, HR_MAX = 48, 188


def _block(data: dict) -> str:
    return "```arc\n" + json.dumps(data, ensure_ascii=False, indent=1) + "\n```\n"


def _write(root: Path, rel: str, title: str, data: dict, prose: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"# {title}\n\n{_block(data)}\n{prose.strip()}\n", encoding="utf-8")


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


def build(root: Path, days: int = 120, today: date | None = None, sport: str = "trail", seed: int = 7) -> Path:
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
    args = parser.parse_args(argv)
    root = build(Path(args.dir), args.days, date.fromisoformat(args.today) if args.today else None, args.sport)
    print(root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
