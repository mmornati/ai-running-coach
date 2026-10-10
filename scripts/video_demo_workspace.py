#!/usr/bin/env python3
"""Workspace de démonstration « Camille » pour la série de vidéos — fictif, déterministe.

    python3 scripts/video_demo_workspace.py DIR [--force] [--no-samples]

Construit, sous `DIR`, le workspace d'une athlète imaginaire (Camille, 3e saison de trail, Val-d'Orée,
objectif Trail des Crêtes 42 km / 2 100 m D+ le 2026-11-22) arrêté au **mardi 2026-09-29** (J-54), le
matin du bilan. Tout vient du générateur des tests (`tests/lib/synthetic.py`), puis les fichiers de
l'histoire sont réécrits par-dessus pour que chaque vue du tableau de bord raconte la même chose :

- bilan matinal : HRV 38 ms sous une bande 52–70 ms depuis 3 nuits, FC de repos 52 bpm (+6 sur la
  médiane 7 j), readiness 34/100, sommeil 6 h 12 → verdict « Alléger » (seuil 5 × 6 min → EF 45') ;
- semaine du 28 septembre, garde-fou r7 (qualité deux jours de suite) : côtes décalées de mercredi à
  jeudi ; séance du dimanche 27 : 18,2 km, 820 m D+, FC 142, RPE 6, 2 gels + 500 ml ;
- matériel fictif (« Crête Pro (bleue) », « Route Légère », « Vieille Grimpeuse », kit trail-long),
  plan de course à trois scénarios, rapports, nutrition, météo, inspections photo (images
  générées, jamais de vraies photos).

Garanties : aucune donnée réelle (jamais de lecture du workspace de l'utilisateur), aucune coordonnée
GPS réelle (la variante `--suite` trace une boucle fictive en plein océan, sans fond de carte), identifiants Garmin ≥ `FAKE_ACTIVITY_ID_BASE`, aucun sigle déposé par TrainingPeaks. Chaque fichier
écrit respecte le contrat `arc` (`python3 scripts/arc_index.py --validate`).

`--force` remplace un dossier existant, mais SEULEMENT s'il porte le marqueur `.arc-video-demo` posé
par ce script (ou s'il est vide) : jamais d'effacement d'un vrai workspace.
`--no-samples` saute les échantillons FIT seconde par seconde (rapide ; les vues « Analyse » et les
montées de la séance restent alors vides).
`--bloc` (épisode 15) et `--suite` (épisodes 16-17) construisent les variantes du workspace : les autres
épisodes gardent le workspace d'origine.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import math
import re
import shutil
import struct
import sys
import zlib
from datetime import date, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))

from tests.lib import synthetic as syn  # noqa: E402

TODAY = date(2026, 9, 29)                 # mardi, J-54
RACE_DATE = date(2026, 11, 22)
DAYS = 231
SEED = 7
MARKER = ".arc-video-demo"
CITY = "Val-d'Orée"
SHOE = "crete-pro-bleue"                  # « Crête Pro (bleue) », paire par défaut
ROAD_SHOE = "route-legere"
STORY_ACTIVITY = date(2026, 9, 27)        # dimanche : 18,2 km, 820 m D+
SHOE_TARGET_M = 612_000                   # ~612 km au compteur au 2026-09-29
SAMPLES_DAYS = 70                         # échantillons FIT seulement sur les 10 dernières semaines

HEALTH_WEEK = {                           # (HRV ms, FC repos, readiness, sommeil s, verdict)
    "2026-09-22": (60, 46, 72, 26400, "green"),
    "2026-09-23": (57, 46, 66, 25500, "green"),
    "2026-09-24": (55, 47, 62, 25200, "green"),
    "2026-09-25": (54, 46, 60, 24600, "green"),
    "2026-09-26": (50, 47, 51, 23400, "amber"),
    "2026-09-27": (48, 47, 46, 22800, "amber"),
    "2026-09-28": (45, 46, 41, 22000, "amber"),
    "2026-09-29": (38, 52, 34, 22320, "amber"),
}

TEXT_FIXES = {                            # réécritures sur les fichiers `activities/` du générateur
    "Côtes 8 × 90 s": "Seuil 4 × 8 min", "côtes 8 × 90 s": "seuil 4 × 8 min",
    "Tournai": CITY, "adizero-sl": ROAD_SHOE, "batons-leki": "batons-cime",
    "T12:10:00": "T18:10:00",
}


# ---------------------------------------------------------------------------
# Lecture / écriture de fichiers au contrat
# ---------------------------------------------------------------------------

_BLOCK_RE = re.compile(r"```arc\n(.*?)\n```\n", re.S)


def read_block(path: Path) -> dict:
    return json.loads(_BLOCK_RE.search(path.read_text(encoding="utf-8")).group(1))


def mutate(path: Path, fn) -> dict:
    """Relit le bloc ```arc d'un fichier, applique `fn(data)` (qui modifie `data` en place) et le réécrit
    sans toucher au texte libre."""
    text = path.read_text(encoding="utf-8")
    match = _BLOCK_RE.search(text)
    data = json.loads(match.group(1))
    fn(data)
    path.write_text(text[:match.start()] + syn._block(data) + text[match.end():], encoding="utf-8")
    return data


def write(root: Path, rel: str, title: str, data: dict, prose: str) -> None:
    syn._write(root, rel, title, data, prose)


def hms(seconds: float) -> str:
    h, rest = divmod(int(round(seconds)), 3600)
    return f"{h} h {rest // 60:02d}"


def activity_files(root: Path):
    return sorted((root / "activities").glob("*.md"))


# ---------------------------------------------------------------------------
# Images factices (aucune vraie photo)
# ---------------------------------------------------------------------------

def placeholder_png(width: int, height: int, wear: tuple, *, profile: bool = False) -> bytes:
    """PNG 8 bits RVB d'une semelle stylisée (silhouette, crampons, zone d'usure `wear` = (cx, cy, r) en
    fractions de la largeur/hauteur). Pur Python, déterministe ; `profile=True` dessine une vue de côté."""
    bg, sole, lug, worn = (16, 28, 22), (40, 58, 50), (66, 90, 80), (201, 165, 92)
    rows = bytearray()
    for y in range(height):
        rows.append(0)
        for x in range(width):
            u, v = x / width, y / height
            if profile:
                top = 0.42 + 0.10 * (1 - abs(u - 0.5) * 2) ** 2
                inside = 0.10 < u < 0.90 and top < v < 0.70
                lugs = inside and v > 0.60 and int(u * 40) % 2 == 0
            else:
                fore = ((u - 0.5) / 0.36) ** 2 + ((v - 0.27) / 0.24) ** 2 <= 1
                heel = ((u - 0.5) / 0.27) ** 2 + ((v - 0.79) / 0.17) ** 2 <= 1
                arch = abs(u - 0.5) < 0.2 and 0.38 < v < 0.66
                inside = fore or heel or arch
                lugs = inside and (int(u * 22) + int(v * 22)) % 2 == 0
            color = bg
            if inside:
                color = lug if lugs else sole
                if ((u - wear[0]) / wear[2]) ** 2 + ((v - wear[1]) / wear[2]) ** 2 <= 1:
                    color = worn
            rows.extend(color)

    def chunk(kind: bytes, payload: bytes) -> bytes:
        body = kind + payload
        return struct.pack(">I", len(payload)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header)
            + chunk(b"IDAT", zlib.compress(bytes(rows), 9)) + chunk(b"IEND", b""))


# ---------------------------------------------------------------------------
# Profil et objectif (puces du modèle, libellés inchangés)
# ---------------------------------------------------------------------------

PROFILE_VALUES = {
    "Prénom / surnom": "Camille",
    "Année de naissance": "1990",
    "Années de pratique": "3 saisons de trail",
    "Disponibilité hebdomadaire": "5 séances, 7 h à 8 h au total",
    "Jours impossibles": "lundi (repos), vendredi (repos)",
    "Contraintes de vie": "travail en journée, sorties le soir ou le week-end",
    "FC max": "188",
    "FC de repos de référence": "46",
    "FC au seuil": "172",
    "VO2max (Garmin)": "54",
    "Poids de forme": "62 kg",
    "Besoin de sommeil": "7 h 30",
    "Meilleures performances": "Trail des Collines 28 km : 3 h 21 (2025)",
    "Antécédents de blessure": "tendinite rotulienne gauche (2024), résolue",
    "Zones fragiles à surveiller": "genou gauche",
    "Lieu par défaut": CITY,
    "Créneau habituel": "soir (18 h-19 h)",
    "Terrain accessible": "sentiers, crêtes, 900 m de dénivelé à 20 minutes",
    "Sports croisés pratiqués": "renforcement",
    "Ce qui me motive": "la régularité et voir la forme monter semaine après semaine",
    "Ce qui ne marche pas avec moi": "les consignes sans explication",
    "Sujets à ne pas commenter spontanément": "le poids",
    "Tolérance au risque": "prudent : mieux vaut 10 % de moins qu'une blessure",
    "Quand me poser une question plutôt que supposer": "dès que le sommeil ou le genou sont en jeu",
}

PROFILE_SECTIONS = {
    "### Historique des indices": [
        "- 2025-11-01 — itra : 540",
        "- 2026-02-15 — utmb 50k : 510",
        "- 2026-08-30 — utmb 50k : 535",
    ],
    "### Chaussures": [
        "- Crête Pro (bleue) — depuis 2026-01-10 — alerte 700 km — départ {depart} km — usage: trail — id: crete-pro-bleue (par défaut)",
        "- Route Légère — alerte 600 km — usage: route — id: route-legere",
        "- Vieille Grimpeuse — usage: trail — id: vieille-grimpeuse (retirée)",
    ],
    "### Matériel": [
        "- Poche à eau 2 L — catégorie: poche — depuis 2026-01-10 — alerte 365 jours — id: poche-eau — kit: trail-long",
        "- Frontale Aube — catégorie: frontale — alerte 100 h — id: frontale-nuit — kit: trail-long",
        "- Bâtons Cime — catégorie: bâtons — alerte 800 km — id: batons-cime — kit: trail-long",
        "- Couverture de survie — catégorie: autre — id: couverture-survie — kit: trail-long",
        "- Ceinture cardio — catégorie: ceinture — depuis 2026-01-10 — alerte 365 jours — id: ceinture-cardio",
    ],
}

OBJECTIVE_VALUES = {
    "Nom": "Trail des Crêtes",
    "Date": RACE_DATE.isoformat(),
    "Distance": "42 km",
    "Dénivelé positif": "2 100 m",
    "Lieu": CITY,
    "Objectif principal": "temps cible",
    "Temps visé": "6 h 05",
    "Scénario acceptable / scénario noir": "acceptable : 6 h 40 · noir : abandon au km 24 sur blessure",
    "Semaines restantes": "8",
    "Volume hebdomadaire de départ": "6 h",
    "Volume hebdomadaire cible": "8 h",
    "Séances qualité par semaine": "2",
    "Lieu d'entraînement par défaut": CITY,
    "Indisponibilités": "aucune",
    "Courses intermédiaires": "aucune",
    "Limites médicales en cours": "aucune",
}


def _fill_template(text: str, values: dict) -> str:
    """Complète les puces `- **Libellé** :` d'un modèle sans jamais changer un libellé ; retire les
    commentaires HTML et les citations d'aide du modèle (exemples de marques réelles compris)."""
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    out = []
    for line in text.splitlines():
        if line.startswith(">"):
            continue
        m = re.match(r"^(- \*\*)([^*]+)(\*\*\s*:)", line)
        if m:
            value = values.get(m.group(2).strip())
            line = f"{m.group(1)}{m.group(2)}{m.group(3)}" + (f" {value}" if value else "")
        out.append(line)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip() + "\n"


def write_profile(root: Path, depart_km: int) -> None:
    text = _fill_template((REPO / "templates/Runner_Profile.template.md").read_text(encoding="utf-8"),
                          PROFILE_VALUES)
    for heading, bullets in PROFILE_SECTIONS.items():
        block = "\n".join(b.format(depart=depart_km) for b in bullets)
        text = text.replace(heading + "\n", f"{heading}\n\n{block}\n", 1)
    text = text.replace("# Profil de l'athlète\n", "# Profil de l'athlète — Camille\n", 1)
    (root / "planning/Runner_Profile.md").write_text(text, encoding="utf-8")


def write_objective(root: Path) -> None:
    text = _fill_template((REPO / "templates/active_objective.template.md").read_text(encoding="utf-8"),
                          OBJECTIVE_VALUES)
    text = text.replace("|  |  |  |", "| 2026-09-20 | Objectif fixé : Trail des Crêtes | Plan de course validé avec le stratège |")
    (root / "planning/active_objective.md").write_text(text, encoding="utf-8")


def write_config(root: Path) -> None:
    (root / "config/workspace.user.toml").write_text(
        '[sport]\nprimary = "trail"\n\n[health]\nmorning_check = "full"\n\n'
        '[coaching]\nstyle = "bienveillant"\nintensity = "balanced"\nverbosity = "standard"\n',
        encoding="utf-8")


# ---------------------------------------------------------------------------
# Historique : activités, santé
# ---------------------------------------------------------------------------

def clean_base(root: Path) -> None:
    """Retire du générateur ce que l'histoire réécrit entièrement."""
    for pattern in ("planning/*_decision_*.md", "planning/Semaine_*.md", "rapports/*.md", "gear/*.md",
                    "medical/*_meteo.md"):
        for path in root.glob(pattern):
            path.unlink()
    shutil.rmtree(root / "gear/photos", ignore_errors=True)
    for path in activity_files(root):                    # rien d'enregistré le jour même ni après
        if path.name[:10] >= TODAY.isoformat():
            gid = read_block(path).get("garmin_activity_id")
            path.unlink()
            if gid:
                (root / f"activities/fit/{gid}.json").unlink(missing_ok=True)


def fix_activities(root: Path) -> None:
    for path in activity_files(root):
        text = path.read_text(encoding="utf-8")
        for old, new in TEXT_FIXES.items():
            text = text.replace(old, new)
        path.write_text(text, encoding="utf-8")


def fix_health(root: Path) -> None:
    for path in sorted((root / "medical").glob("*_health.md")):
        day = path.name[:10]

        def fn(d: dict) -> None:
            d["hrv_baseline_low_ms"], d["hrv_baseline_high_ms"] = 52, 70
            d["resting_hr_bpm"] = max(40, d["resting_hr_bpm"] - 2)
            if day < "2026-09-22":                        # avant la semaine racontée : jamais sous la bande
                d["hrv_overnight_ms"] = max(d["hrv_overnight_ms"], 54)
            if "weight_kg" in d:
                d["weight_kg"] = round(62.0 + ((int(day[-2:]) * 7) % 5 - 2) * 0.1, 1)
            if day in HEALTH_WEEK:
                hrv, rhr, ready, sleep, verdict = HEALTH_WEEK[day]
                d.update({"hrv_overnight_ms": hrv, "resting_hr_bpm": rhr, "readiness_score": ready,
                          "sleep_total_s": sleep, "sleep_deep_s": round(sleep * 0.17),
                          "sleep_light_s": round(sleep * 0.56), "sleep_rem_s": round(sleep * 0.21),
                          "sleep_awake_s": round(sleep * 0.06), "sleep_score": max(40, round(sleep / 330)),
                          "verdict": verdict})
                d["verdict_reason"] = ("Triade dans la norme : séance maintenue." if verdict == "green"
                                       else "HRV sous la bande depuis plusieurs nuits : garder l'aérobie, couper l'intensité.")
                d["body_battery_high"] = min(100, ready + 12)
            d["hrv_status"] = "balanced" if d["hrv_overnight_ms"] >= 52 else "low"

        mutate(path, fn)

    # 2026-09-27 : douleur déclarée au /log ; 2026-09-29 : le bilan du matin de l'histoire.
    mutate(root / "medical/2026-09-27_health.md",
           lambda d: d.update({"pain": [{"location": "genou gauche", "score": 3}]}))
    write(root, "medical/2026-09-29_health.md", "Santé du 2026-09-29", {
        "arc": 1, "kind": "health", "date": "2026-09-29", "morning_check": "full",
        "sleep_total_s": 22320, "sleep_deep_s": 3800, "sleep_light_s": 12500, "sleep_rem_s": 4700,
        "sleep_awake_s": 1320, "sleep_score": 58,
        "sleep_start": "2026-09-28T23:48:00+02:00", "sleep_end": "2026-09-29T06:54:00+02:00",
        "hrv_overnight_ms": 38, "hrv_baseline_low_ms": 52, "hrv_baseline_high_ms": 70, "hrv_status": "low",
        "resting_hr_bpm": 52, "readiness_score": 34,
        "readiness_factors": {"sleep": 40, "sleep_history": 38, "hrv": 28, "acute_load": 45},
        "body_battery_high": 46, "body_battery_low": 12, "stress_avg": 41, "weight_kg": 62.0,
        "verdict": "amber",
        "verdict_reason": "HRV sous la bande depuis 3 nuits, FC de repos +6 et readiness 34 : on allège, EF 45 min au lieu du seuil.",
    }, """## Analyse du bilan matinal

- **HRV** : 38 ms, sous la bande personnelle 52–70 ms, pour la 4e nuit d'affilée en dessous.
- **FC de repos** : 52 bpm, +6 sur la médiane des 7 derniers jours (46 bpm).
- **Readiness** : 34/100, faible. Sommeil : 6 h 12, score 58.

Les trois signaux vont dans le même sens : la fatigue du week-end (sortie longue samedi, 820 m D+
dimanche) n'est pas encore résorbée. Verdict : **alléger**. Le seuil 5 × 6 min du jour est remplacé
par 45 minutes d'endurance fondamentale (EF 45').

*Ce bilan ne remplace pas un avis médical : si la fatigue dure, parlez-en à un professionnel de santé.*""")


def story_sunday(root: Path, with_samples: bool) -> dict:
    """Réécrit la séance du dimanche 27 : 18,2 km, 820 m D+, FC 142, RPE 6, 2 gels + 500 ml."""
    path = root / f"activities/{STORY_ACTIVITY.isoformat()}_trail.md"
    gains = [10, 25, 70, 95, 90, 85, 40, 20, 15, 30, 60, 65, 70, 50, 35, 25, 25, 10]
    assert sum(gains) == 820 and len(gains) == 18
    splits = []
    for km, gain in enumerate(gains, start=1):
        loss = round(gain * (0.9 if km < 10 else 1.1))
        duration = round(300 + 3.6 * gain)
        label = "Échauffement" if km == 1 else ("Montée" if gain >= 60 else ("Retour au calme" if km == 18 else "Allure"))
        splits.append([km, duration, gain, loss, round(136 + gain / 9), round(3600 / duration * 1.2, 1),
                       166 if gain < 60 else 160, label])
    moving = sum(r[1] for r in splits) + 70
    data = {
        "arc": 1, "kind": "activity", "date": STORY_ACTIVITY.isoformat(), "sport": "trail",
        "garmin_activity_id": syn.FAKE_ACTIVITY_ID_BASE + (STORY_ACTIVITY - (TODAY - timedelta(days=DAYS - 1))).days,
        "name": "Sortie trail — crêtes de Val-d'Orée",
        "location": CITY, "start_time": f"{STORY_ACTIVITY.isoformat()}T09:30:00+02:00",
        "distance_m": 18200, "duration_s": moving + 260, "moving_duration_s": moving,
        "elevation_gain_m": 820, "elevation_loss_m": sum(r[3] for r in splits) - 60,
        "avg_hr_bpm": 142, "max_hr_bpm": 171, "training_effect_aerobic": 3.5, "training_effect_anaerobic": 1.0,
        "calories_kcal": 1420, "avg_cadence_spm": 164, "rpe": 7, "recovery_hr_bpm": 21,
        "gear_id": SHOE, "gear_source": "chat", "gear_ids": ["poche-eau", "batons-cime"],
        "carbs_g": 50, "fluid_intake_ml": 500,
        "splits_cols": ["km", "duration_s", "elev_gain_m", "elev_loss_m", "avg_hr_bpm", "max_speed_kmh",
                        "cadence_spm", "label"],
        "splits": splits,
    }
    write(root, f"activities/{STORY_ACTIVITY.isoformat()}_trail.md",
          f"Séance du {STORY_ACTIVITY.isoformat()} — {data['name']}", data,
          """## Analyse du coach

Sortie vallonnée de 18,2 km pour 820 m D+, FC moyenne 142 bpm : une vraie séance d'endurance de
montagne, effort perçu 6/10. Les quatre grandes montées (km 3 à 6, km 11 à 14) sont gérées en marche
rapide, sans dérive de FC marquée.

- **Ravitaillement** : 2 gels + 500 ml au km 15, noté en chat, soit 50 g de glucides pour 2 h 25.
  C'est en dessous de l'objectif de course (60 g/h) : à travailler sur la prochaine sortie longue.
- **Genou gauche** : gêne légère 3/10 signalée en fin de séance, à surveiller (fichier santé du jour).
- **Matériel** : Crête Pro (bleue), poche à eau 2 L et bâtons.

Enchaînée la veille avec une sortie longue, cette séance explique en partie la baisse de HRV des
trois dernières nuits.""")
    if with_samples:
        syn._write_samples(root, data["garmin_activity_id"], seed=SEED + 99, duration_s=data["duration_s"],
                           target_distance_m=18200.0, target_gain_m=820.0,
                           target_loss_m=float(data["elevation_loss_m"]), target_avg_hr_bpm=142.0,
                           cadence_spm=164.0)
    return data


def write_samples(root: Path) -> None:
    """Échantillons FIT des 10 dernières semaines (hors dimanche 27, déjà écrit par `story_sunday`)."""
    start = TODAY - timedelta(days=DAYS - 1)
    cutoff = (TODAY - timedelta(days=SAMPLES_DAYS)).isoformat()
    for path in activity_files(root):
        d = read_block(path)
        if (d["date"] < cutoff or d["date"] == STORY_ACTIVITY.isoformat()
                or d["sport"] not in ("running", "trail") or "garmin_activity_id" not in d):
            continue
        offset = (date.fromisoformat(d["date"]) - start).days
        syn._write_samples(root, d["garmin_activity_id"], seed=SEED + offset, duration_s=d["duration_s"],
                           target_distance_m=float(d["distance_m"]), target_gain_m=float(d["elevation_gain_m"]),
                           target_loss_m=float(d["elevation_loss_m"]),
                           target_avg_hr_bpm=float(d["avg_hr_bpm"]), cadence_spm=float(d["avg_cadence_spm"]))


# ---------------------------------------------------------------------------
# Semaines, décisions
# ---------------------------------------------------------------------------

def _intensity(name: str, sport: str) -> str:
    if sport == "strength":
        return "strength"
    return "threshold" if name.startswith("Seuil") else "endurance"


def week_from_activities(root: Path, monday: date) -> dict:
    sessions = []
    for path in activity_files(root):
        d = read_block(path)
        if monday.isoformat() <= d["date"] <= (monday + timedelta(days=6)).isoformat():
            name = d.get("name") or "Renforcement"
            s = {"date": d["date"], "sport": d["sport"], "title": name, "intensity": _intensity(name, d["sport"]),
                 "outdoor": d["sport"] != "strength", "planned_duration_s": d["duration_s"], "status": "done"}
            if d.get("distance_m") and d["sport"] != "strength":
                s["planned_distance_m"] = d["distance_m"]
            sessions.append(s)
    return {"week_start": monday.isoformat(), "location": CITY, "phase": "Spécifique",
            "target_duration_s": 27000, "sessions": sessions}


def write_weeks(root: Path) -> None:
    monday = TODAY - timedelta(days=TODAY.weekday())
    for k in range(4, 0, -1):                                     # 4 semaines passées, jouées
        prev = monday - timedelta(weeks=k)
        data = week_from_activities(root, prev)
        write(root, f"planning/Semaine_{prev.isoformat()}.md", f"Semaine du {prev.isoformat()}",
              {"arc": 1, "kind": "week", **data}, "## Intention\n\nConsolider le volume, une séance de qualité par semaine.")

    d = lambda n: (monday + timedelta(days=n)).isoformat()      # noqa: E731
    sessions = [
        {"date": d(1), "sport": "running", "title": "Seuil 5 × 6 min", "planned_duration_s": 4500,
         "intensity": "threshold", "outdoor": True, "status": "cancelled", "weather_category": "green", "best_slot": "evening"},
        {"date": d(1), "sport": "running", "title": "Endurance fondamentale 45 min (EF 45')", "planned_duration_s": 2700,
         "intensity": "endurance", "outdoor": True, "status": "planned", "weather_category": "green", "best_slot": "evening"},
        {"date": d(2), "sport": "trail", "title": "Côtes 8 × 1 min", "planned_duration_s": 3600, "planned_elevation_m": 350,
         "intensity": "vo2max", "outdoor": True, "status": "moved", "weather_category": "green", "best_slot": "evening"},
        {"date": d(2), "sport": "running", "title": "Endurance fondamentale 45 min", "planned_duration_s": 2700,
         "intensity": "endurance", "outdoor": True, "status": "planned", "weather_category": "green", "best_slot": "evening"},
        {"date": d(3), "sport": "trail", "title": "Côtes 8 × 1 min", "planned_duration_s": 3600, "planned_elevation_m": 350,
         "intensity": "vo2max", "outdoor": True, "status": "planned", "weather_category": "yellow", "best_slot": "midday"},
        {"date": d(5), "sport": "trail", "title": "Sortie longue 2 h 30 / 900 m D+", "planned_duration_s": 9000,
         "planned_elevation_m": 900, "intensity": "endurance", "outdoor": True, "status": "planned",
         "weather_category": "green", "best_slot": "morning"},
        {"date": d(6), "sport": "running", "title": "Endurance fondamentale 50 min", "planned_duration_s": 3000,
         "intensity": "endurance", "outdoor": True, "status": "planned"},
    ]
    write(root, f"planning/Semaine_{monday.isoformat()}.md", f"Semaine du {monday.isoformat()}", {
        "arc": 1, "kind": "week", "week_start": monday.isoformat(), "location": CITY, "phase": "Spécifique",
        "target_duration_s": 25200, "target_elevation_m": 1250, "sessions": sessions,
    }, """## Intention

Semaine de charge contrôlée, 54 jours avant le Trail des Crêtes : une séance de qualité (côtes), la
sortie longue du samedi, le reste en endurance. Camille arrive fatiguée du week-end.

## Garde-fous

| Règle | Constat | Ajustement |
|---|---|---|
| r7 · qualité deux jours de suite | Seuil mardi + côtes mercredi | Côtes décalées de mercredi à **jeudi**, EF 45 min mercredi |

## Bilan matinal du mardi 29

HRV 38 ms (bande 52–70), FC de repos 52 bpm, readiness 34 : le **seuil 5 × 6 min** est remplacé par
**45 min d'endurance (EF 45')** à 18 h – 19 h, 19 °C, vent 10 km/h.

## Samedi

Sortie longue 2 h 30 / 900 m D+, tôt le matin. Kit trail-long : poche à eau 2 L, frontale, bâtons.
Si la HRV n'est pas remontée dans sa bande vendredi, la sortie sera raccourcie.""")


def write_decisions(root: Path) -> None:
    week = f"planning/Semaine_{(TODAY - timedelta(days=TODAY.weekday())).isoformat()}.md"
    write(root, "planning/2026-09-28_decision_garde-fou-qualite-consecutive.md",
          "Décision — garde-fou r7 (qualité consécutive)", {
              "arc": 1, "kind": "decision", "date": "2026-09-28", "created_at": "2026-09-28T07:40:00+02:00",
              "trigger": "guardrail", "outcome": "applied", "rule_ids": ["r7_consecutive_quality"],
              "summary": "Seuil mardi et côtes mercredi se suivent : côtes décalées à jeudi, EF 45 min mercredi.",
              "inputs": {"quality_sessions": "mardi + mercredi", "consecutive_quality_days": 2},
              "sources": [week],
              "before": {"date": "2026-09-30", "title": "Côtes 8 × 1 min", "intensity": "vo2max"},
              "after": {"date": "2026-10-01"},
              "session_ref": {"week": week, "date": "2026-10-01"},
          }, "## Contexte\n\nLa règle r7 signale deux séances de qualité sur deux jours consécutifs. Les côtes passent "
             "de mercredi à jeudi : 48 h de récupération après le seuil.")
    write(root, "planning/2026-09-29_decision_bilan-matinal.md", "Décision — bilan matinal", {
        "arc": 1, "kind": "decision", "date": "2026-09-29", "created_at": "2026-09-29T07:10:00+02:00",
        "trigger": "morning_check", "outcome": "applied",
        "summary": "HRV 38 ms sous la bande 52–70 depuis 3 nuits, FC de repos +6, readiness 34 : seuil 5 × 6 min remplacé par EF 45 min.",
        "inputs": {"hrv_overnight_ms": 38, "hrv_band_low_ms": 52, "hrv_band_high_ms": 70, "nights_below_band": 3,
                   "resting_hr_bpm": 52, "resting_hr_delta_bpm": 6, "readiness_score": 34},
        "sources": ["medical/2026-09-29_health.md"],
        "before": {"title": "Seuil 5 × 6 min", "intensity": "threshold", "planned_duration_s": 4500},
        "after": {"title": "Endurance fondamentale 45 min (EF 45')", "intensity": "endurance", "planned_duration_s": 2700},
        "session_ref": {"week": week, "date": "2026-09-29"},
    }, """## Contexte

Bilan matinal complet : HRV 38 ms (bande personnelle 52–70 ms, 4e nuit en dessous), FC de repos 52 bpm
(+6 sur la médiane 7 j), readiness 34/100, sommeil 6 h 12. Verdict : **alléger**.

## Décision

Le seuil 5 × 6 min est remplacé par 45 minutes d'endurance fondamentale, ce soir entre 18 h et 19 h
(19 °C, vent 10 km/h). Les côtes restent prévues jeudi si la HRV remonte.

*Ne remplace pas un avis médical.*""")


# ---------------------------------------------------------------------------
# Météo, nutrition, plan de course, rapports, inspections
# ---------------------------------------------------------------------------

WEATHER = (   # offset, cat, tmin, tmax, feels, wind, gust, rain %, mm, uv, slot, raison
    (-2, "green", 9, 18, 17, 8, 15, 5, 0.0, 4, "morning", "Frais le matin, 18 °C l'après-midi : sortie du matin idéale."),
    (-1, "green", 9, 17, 16, 12, 20, 20, 0.8, 3, "evening", "Journée grise : fin d'après-midi plus douce."),
    (0, "green", 10, 19, 18, 10, 18, 10, 0.0, 4, "evening", "19 °C et 10 km/h de vent entre 18 h et 19 h : conditions idéales pour une EF."),
    (1, "green", 9, 18, 17, 9, 16, 10, 0.0, 4, "evening", "Soirée sèche et douce : créneau habituel."),
    (2, "yellow", 8, 16, 14, 12, 24, 40, 2.5, 3, "midday", "Averse probable en soirée : sortir à midi pour les côtes."),
    (3, "green", 7, 15, 14, 8, 14, 10, 0.0, 3, "morning", "Jour de repos : conditions sèches."),
    (4, "green", 6, 17, 16, 14, 25, 5, 0.0, 4, "morning", "Fraîcheur du matin pour 2 h 30 de sortie : départ avant 9 h."),
)


def write_weather(root: Path) -> None:
    for off, cat, tmin, tmax, feels, wind, gust, rain, mm, uv, slot, why in WEATHER:
        day = (TODAY + timedelta(days=off)).isoformat()
        write(root, f"medical/{day}_meteo.md", f"Météo — {CITY} — {day}", {
            "arc": 1, "kind": "weather", "date": day, "location": CITY, "category": cat,
            "temp_min_c": tmin, "temp_max_c": tmax, "feels_like_c": feels, "humidity_pct": 58,
            "chance_of_rain_pct": rain, "wind_kmh": wind, "gust_kmh": gust, "wind_dir_deg": 250,
            "precip_mm": mm, "uv_index": uv, "thunderstorm": False, "sunrise": "07:22", "sunset": "19:08",
            "best_slot": slot, "slot_reason": why, "source": "wttr.in (données de démonstration)",
            "fetched_at": f"{TODAY.isoformat()}T07:05:00+02:00",
        }, "## Ajustements\n\n- Hydratation normale\n- Coupe-vent léger dans la poche")


def fix_nutrition(root: Path) -> None:
    for i, path in enumerate(sorted((root / "nutrition").glob("*_nutrition.md"))):
        mutate(path, lambda d, i=i: d.update({"weight_kg": [62.2, 62.1, 62.3, 62.0, 62.1, 62.2, 62.0][i % 7],
                                              "target_weight_kg": 61.5}))


def write_race_plan(root: Path) -> None:
    write(root, "planning/2026-09-20_plan-de-course_trail-des-cretes.md", "Plan de course — Trail des Crêtes", {
        "arc": 1, "kind": "race_plan", "date": "2026-09-20", "race_name": "Trail des Crêtes",
        "race_date": RACE_DATE.isoformat(), "distance_m": 42000, "elevation_gain_m": 2100,
        "start_time": f"{RACE_DATE.isoformat()}T08:00:00+01:00", "target_time_s": 21900,
        "scenarios": {"ambitious": 20280, "realistic": 21900, "safe": 24000},
        "aid_stations": [
            {"km": 12, "name": "Ravito de la Combe", "services": ["eau", "solide", "boisson isotonique"], "cutoff": "10:30"},
            {"km": 24, "name": "Refuge des Crêtes", "services": ["eau", "solide", "soupe"], "cutoff": "12:45", "stop_s": 150},
            {"km": 34, "name": "Col du Houx", "services": ["eau", "solide"], "cutoff": "14:15"},
        ],
        "water_points": [{"km": 18.5, "source": "officiel", "name": "Fontaine du hameau"}],
        "gear": ["poche à eau", "frontale", "bâtons", "couverture de survie"],
    }, """## Scénarios

| Scénario | Temps | Allure moyenne |
|---|---|---|
| Sécurité | 6 h 40 | 9 min 31 /km |
| **Réaliste** | **6 h 05** | 8 min 41 /km |
| Ambitieux | 5 h 38 | 8 min 03 /km |

## Passages (scénario réaliste, départ 8 h 00)

| Point | Km | Passage | Arrêt |
|---|---|---|---|
| Ravito de la Combe | 12 | 9 h 30 | 90 s |
| Refuge des Crêtes | 24 | 11 h 20 | 150 s |
| Col du Houx | 34 | 13 h 05 | 90 s |
| Arrivée | 42 | 14 h 05 | |

## Ravitaillement

**60 g de glucides par heure**, environ **520 kcal/h** de dépense : un gel ou une barre toutes les
30 à 40 minutes, 500 ml d'eau par heure (poche 2 L : recharge au km 12 et au km 24). Les ravitos des
km 12, 24 et 34 servent à recharger l'eau, pas à rattraper un retard de glucides.

## Matériel

Poche à eau 2 L, frontale (jour de brume ou arrivée tardive), bâtons pour la montée du km 24 au km 28,
couverture de survie obligatoire. Chaussures : Crête Pro (bleue), sous le seuil des 700 km.

*Plan indicatif, ne remplace pas un avis médical ni la lecture du règlement de la course.*""")


# ---------------------------------------------------------------------------
# Ultra des Crêtes (épisode 14) : un plan de nuit, calculé par le vrai moteur de pacing
# ---------------------------------------------------------------------------
# Le projet de l'an prochain de Camille : 66 km, ~3 600 m D+, départ à 16 h le samedi du passage à
# l'heure d'hiver. Parcours SYNTHÉTIQUE (profil rectiligne inventé, coordonnées jamais écrites dans le
# workspace) passé dans `arc_race_pacing.build_race_plan` : nuit (#184), technicité simulée à partir de
# chemins OpenStreetMap fictifs (#186), segments, passages. Rien n'est dessiné à la main : le roadbook
# montré à l'écran est celui que le tableau de bord calcule vraiment.

ULTRA_DATE = date(2027, 10, 30)
ULTRA_PROFILE = [(0, 1000), (8, 1750), (13, 1450), (22, 2350), (28, 1650), (34, 2150), (41, 1250),
                 (49, 2300), (55, 2000), (60, 2450), (66, 1100)]          # (km, altitude m) fictifs
ULTRA_BINS = [(-0.15, 2.7, 140), (-0.08, 3.0, 140), (0.0, 2.6, 145), (0.08, 1.25, 155), (0.15, 0.9, 162)]
ULTRA_STATIONS = [
    {"km": 13, "name": "Col de la Combe", "services": ["eau", "solide", "soupe"], "cutoff": "+03:15",
     "take": ["2 gels", "500 ml de boisson d'effort"]},
    {"km": 28, "name": "Refuge du Houx", "services": ["eau", "solide", "soupe"], "cutoff": "+06:00",
     "take": ["1 barre", "500 ml d'eau"]},
    {"km": 41, "name": "Base de vie des Crêtes", "services": ["repas chaud", "eau"], "stop_s": 600,
     "cutoff": "+08:30", "take": ["repas chaud", "piles de frontale"]},
    {"km": 55, "name": "Bergerie haute", "services": ["eau", "solide"], "cutoff": "+13:00",
     "take": ["2 gels", "caféine"]},
]
# Tronçons techniques (km, km, tags OSM fictifs) ; le reste du parcours est une piste facile.
ULTRA_WAYS = [
    (0, 66, {"highway": "track", "tracktype": "grade2"}),
    (6, 13, {"highway": "path", "sac_scale": "mountain_hiking"}),
    (18, 25, {"highway": "path", "sac_scale": "alpine_hiking", "surface": "rock", "trail_visibility": "bad"}),
    (30, 34, {"highway": "path", "sac_scale": "mountain_hiking"}),
    (44, 53, {"highway": "path", "sac_scale": "demanding_mountain_hiking", "surface": "rock"}),
    (57, 61, {"highway": "path", "sac_scale": "alpine_hiking", "trail_visibility": "bad"}),
]


def _ultra_elevation(d_m: float) -> float:
    km = d_m / 1000.0
    for (k0, e0), (k1, e1) in zip(ULTRA_PROFILE, ULTRA_PROFILE[1:]):
        if k0 <= km <= k1:
            u = (km - k0) / (k1 - k0)
            return e0 + (e1 - e0) * (u * u * (3 - 2 * u) * 0.35 + u * 0.65)
    return float(ULTRA_PROFILE[-1][1])


def ultra_pacing() -> dict:
    """Plan de pacing de l'Ultra des Crêtes : le vrai `build_race_plan`, sur un parcours inventé."""
    import math
    import arc_race_pacing as RP
    lat, lon, step = 45.05, 6.45, 25.0                      # zone alpine imaginaire, jamais persistée
    m_per_deg = 111320.0 * math.cos(math.radians(lat))
    pts = [{"lat": lat, "lon": lon + i * step / m_per_deg, "ele": _ultra_elevation(i * step)}
           for i in range(int(66000 / step) + 1)]
    bins = [{"grade_mid": g, "speed_ms": v, "source": "personal", "ci_low_speed_ms": v * 0.92,
             "ci_high_speed_ms": v * 1.06, "hr_bpm": h} for g, v, h in ULTRA_BINS]
    ways = [{"tags": tags, "geom": [(lat, lon + a * 1000 / m_per_deg), (lat, lon + b * 1000 / m_per_deg)]}
            for a, b, tags in ULTRA_WAYS]
    techno = {"ways": ways, "osm_requested": True, "osm_status": "ok", "osm_baseline": 1.06,
              "osm_baseline_label": "sac_scale=mountain_hiking"}
    return RP.build_race_plan(pts, bins, aid_stations=ULTRA_STATIONS, fade_pct=4.0, start_time="16:00",
                              race_date=ULTRA_DATE.isoformat(), segment_m=1500.0, tz="Europe/Paris",
                              technicity=techno)


def write_ultra_plan(root: Path) -> None:
    pacing = ultra_pacing()
    totals = pacing["totals"]
    write(root, "planning/2026-09-27_ultra_ultra-des-cretes.md", "Plan de course — Ultra des Crêtes", {
        "arc": 1, "kind": "race_plan", "date": "2026-09-27", "race_name": "Ultra des Crêtes",
        "race_date": ULTRA_DATE.isoformat(), "start_time": f"{ULTRA_DATE.isoformat()}T16:00",
        "timezone": "Europe/Paris", "distance_m": totals["distance_m"], "elevation_gain_m": totals["elevation_gain_m"],
        "target_time_s": totals["time_s"]["realistic"], "scenarios": dict(totals["time_s"]),
        "aid_stations": ULTRA_STATIONS,
        "gear": ["Frontale", "Frontale de secours", "Couverture de survie", "Poche à eau", "Veste imperméable"],
        "notes": ["Rien de nouveau le jour J", "Frontale allumée dès 18 h 56", "Caféine après H+8 seulement"],
        "emergency": ["Organisation : numéro au dos du dossard", "Abandon possible à chaque ravito"],
        "segments": pacing["segments"],
    }, """## Projet de l'an prochain

Ultra de nuit, départ à 16 h : la nuit tombe au km 20 environ et dure plus de douze heures, à cheval sur
le passage à l'heure d'hiver. Plan fictif de démonstration (parcours inventé), à recalibrer avec la saison.

*Plan indicatif, ne remplace pas un avis médical ni la lecture du règlement de la course.*""")


def _week_stats(root: Path, monday: date) -> dict:
    n = secs = gain = 0
    for path in activity_files(root):
        d = read_block(path)
        if monday.isoformat() <= d["date"] <= (monday + timedelta(days=6)).isoformat():
            n += 1
            secs += d["duration_s"]
            gain += d.get("elevation_gain_m", 0)
    return {"n": n, "secs": secs, "gain": gain}


def write_reports(root: Path) -> None:
    this_monday = TODAY - timedelta(days=TODAY.weekday())
    notes = {
        0: ("La semaine finit sur deux sorties de montagne enchaînées (samedi et dimanche : 18,2 km, 820 m D+). "
            "La HRV passe sous la bande 52–70 ms dès samedi, la FC de repos remonte : signal de fatigue à ne pas "
            "ignorer. Ravitaillement dimanche : 50 g de glucides, à monter vers 60 g/h.",
            ["Alléger si la HRV reste sous la bande", "Une seule séance de qualité (côtes jeudi)",
             "Genou gauche (3/10) à surveiller"]),
        1: ("Bonne régularité, sortie longue en endurance stricte. HRV dans la bande toute la semaine.",
            ["Garder la sortie longue en endurance", "Ajouter 5 minutes de côtes en fin de séance"]),
        2: ("Semaine de reprise de charge après l'allègement : tout est au plan, conformité 100 %.",
            ["Monter le D+ de la sortie longue de 10 % maximum", "Tester les gels du jour de course"]),
    }
    for w in (1, 2, 3):
        monday = this_monday - timedelta(weeks=w)
        sunday = monday + timedelta(days=6)
        stats = _week_stats(root, monday)
        text, nxt = notes[w - 1]
        write(root, f"rapports/{sunday.isoformat()}_rapport.md", f"Bilan de la semaine du {monday.isoformat()}", {
            "arc": 1, "kind": "report", "date": sunday.isoformat(), "report_type": "weekly",
            "title": f"Bilan de la semaine du {monday.day} au {sunday.day} {['', 'janvier', 'février', 'mars', 'avril', 'mai', 'juin', 'juillet', 'août', 'septembre', 'octobre', 'novembre', 'décembre'][sunday.month]}",
            "period_start": monday.isoformat(), "period_end": sunday.isoformat(),
        }, f"""## Synthèse

{text}

| Indicateur | Valeur |
|---|---|
| Séances | {stats['n']} |
| Volume | {hms(stats['secs'])} |
| D+ | {stats['gain']} m |

## Pour la semaine prochaine

""" + "\n".join(f"- {n}" for n in nxt))


def write_inspections(root: Path) -> None:
    second = TODAY - timedelta(days=5)
    first = TODAY - timedelta(days=40)
    photo_dir = root / "gear/photos"
    photo_dir.mkdir(parents=True, exist_ok=True)
    photos = {}
    for day, wear, tag in ((first, (0.42, 0.80, 0.07), "light"), (second, (0.40, 0.81, 0.13), "worn")):
        for view in ("semelles", "profil"):
            rel = f"gear/photos/{day.isoformat()}_{SHOE}_{view}.png"
            (root / rel).write_bytes(placeholder_png(360, 480, wear, profile=view == "profil"))
            photos.setdefault(day, []).append(rel)
    write(root, f"gear/{first.isoformat()}_{SHOE}_inspection.md", "Inspection Crête Pro (bleue)", {
        "arc": 1, "kind": "gear_inspection", "date": first.isoformat(), "gear_id": SHOE, "condition": "green",
        "distance_m": int(round(pair_distance_m(root, first), -3)),
        "wear_zones": [{"side": "left", "zone": "heel_posterolateral", "severity": "light"},
                       {"side": "right", "zone": "heel_posterolateral", "severity": "light"}],
        "asymmetry": {"level": "none"}, "gait_hints": ["heel_strike"], "photos": photos[first],
        "scale_reference": True, "lug_depth_mm": 4.6,
    }, "Crampons intacts (4,6 mm), mousse sans pli. Attaque talon symétrique. Indice seulement, pas un diagnostic.")
    write(root, f"gear/{second.isoformat()}_{SHOE}_inspection.md", "Inspection Crête Pro (bleue)", {
        "arc": 1, "kind": "gear_inspection", "date": second.isoformat(), "gear_id": SHOE, "condition": "yellow",
        "distance_m": int(round(pair_distance_m(root, second), -3)),
        "wear_zones": [{"side": "left", "zone": "heel_posterolateral", "severity": "moderate"},
                       {"side": "right", "zone": "heel_posterolateral", "severity": "light"}],
        "asymmetry": {"level": "mild", "side": "left"}, "gait_hints": ["heel_strike"],
        "photos": photos[second], "previous": f"gear/{first.isoformat()}_{SHOE}_inspection.md",
        "scale_reference": True, "lug_depth_mm": 3.4,
    }, "Crampons à 3,4 mm (4,6 mm à la précédente) : usure plus nette sur le talon gauche, légère asymétrie. "
       "Rien d'alarmant avant le seuil des 700 km, mais à revoir dans 100 km. Indice de foulée seulement, "
       "jamais un diagnostic.")


# ---------------------------------------------------------------------------
# Kilométrage de la paire par défaut : « départ » calculé pour tomber sur ~612 km
# ---------------------------------------------------------------------------

def pair_distance_m(root: Path, as_of: date = TODAY) -> float:
    """Kilométrage de la paire par défaut à la date `as_of` (règle d'attribution du tableau de bord)."""
    import arc_index as I
    conn = I.open_db(root, memory=True)
    I.index_workspace(conn, root, TODAY.isoformat())
    activities = [a for a in I._gear_activities(conn) if (a.get("date") or "") <= as_of.isoformat()]
    shoes = I.M.gear_mileage(activities, I._gear_defs(conn), TODAY)["shoes"]
    conn.close()
    return float(next(s["distance_m"] for s in shoes if s["gear_id"] == SHOE))


def set_departure(root: Path) -> int:
    """Répartit l'historique entre les deux paires de trail, puis fixe le « départ » de la paire par défaut.

    Sur 7 mois, la paire par défaut dépasserait largement ~612 km : les séances les plus anciennes sont
    attribuées (déclaration de l'athlète) à « Vieille Grimpeuse », aujourd'hui retirée ; le reliquat
    (moins d'une sortie) devient le kilométrage de départ de « Crête Pro (bleue) »."""
    import arc_index as I
    write_profile(root, 0)
    conn = I.open_db(root, memory=True)
    I.index_workspace(conn, root, TODAY.isoformat())
    mine = [a for a, gear in I.M.attribute_gear(I._gear_activities(conn), I._gear_defs(conn), TODAY) if gear == SHOE]
    conn.close()
    mine.sort(key=lambda a: (a["date"], a["id"]), reverse=True)
    kept = 0.0
    for i, act in enumerate(mine):
        if kept + act["distance_m"] > SHOE_TARGET_M:
            for old in mine[i:]:
                path = root / next(r for r in old["refs"] if r.endswith(".md"))
                mutate(path, lambda d: d.update({"gear_id": "vieille-grimpeuse", "gear_source": "chat"}))
            break
        kept += act["distance_m"]
    depart_km = max(round((SHOE_TARGET_M - pair_distance_m(root)) / 1000), 0)
    write_profile(root, depart_km)
    return depart_km


# ---------------------------------------------------------------------------
# Bloc d'entraînement (épisode 15) : squelette écrit par le VRAI `plan-skeleton`
# ---------------------------------------------------------------------------

BLOC_OBJECTIVE = {                    # variante « bloc » : le Trail des Crêtes (22 nov.) n'a que 7 semaines, gabarit trop court
    "Nom": "Trail du Solstice", "Date": "2026-12-27", "Distance": "42 km", "Dénivelé positif": "2 000 m",
    "Temps visé": "6 h 20", "Scénario acceptable / scénario noir": "acceptable : 7 h 00 · noir : abandon sur blessure",
    "Semaines restantes": "13",
}


def write_skeleton(root: Path) -> None:
    """Vise la course de fin décembre (objectif actif de la variante), puis écrit les semaines du bloc avec
    `arc_index.py plan-skeleton --write`
    (gabarit marathon_trail, volume tenu lu dans l'index, chaque semaine vérifiée par les garde-fous) : rien n'est
    inventé ici, c'est la sortie réelle de la commande. À la date du film (J-54 du Trail des Crêtes) ce même
    gabarit, appliqué à la course du 22 novembre, répond honnêtement « trop court » (7 semaines pour 12)."""
    import arc_index as I
    text = _fill_template((REPO / "templates/active_objective.template.md").read_text(encoding="utf-8"),
                          {**OBJECTIVE_VALUES, **BLOC_OBJECTIVE})
    text = text.replace("|  |  |  |", "| 2026-09-29 | Objectif fixé : Trail du Solstice | Squelette du bloc généré par plan-skeleton |")
    (root / "planning/active_objective.md").write_text(text, encoding="utf-8")
    with contextlib.redirect_stdout(io.StringIO()):              # la sortie JSON de la commande n'intéresse pas
        rc = I.main(["plan-skeleton", "--workspace", str(root), "--today", TODAY.isoformat(), "--write"])
    if rc not in (0, None):
        raise RuntimeError(f"plan-skeleton --write a échoué ({rc})")


# ---------------------------------------------------------------------------
# Variante « suite » (épisodes 16 et 17) : de quoi ajuster une vitesse critique, une trace à carte,
# un bloc planifié jusqu'à la course et un historique de décisions à évaluer
# ---------------------------------------------------------------------------

# Efforts posés dans les séances « Seuil » des dix dernières semaines : (date, début s, durée s). Vitesse =
# CS(date) + D′ / durée (modèle CS/D′, docs/vitesse-critique.md), CS montant doucement de 3,80 à 3,86 m/s
# (4:23 → 4:19/km), D′ 120 m, tenue à 98-99 % (efforts d'entraînement, pas des tests à l'épuisement).
EFFORTS = (
    ("2026-07-21", 700, 300), ("2026-07-28", 600, 720), ("2026-08-04", 700, 180), ("2026-08-11", 600, 1200),
    ("2026-08-18", 700, 420), ("2026-08-25", 600, 900), ("2026-09-01", 700, 240), ("2026-09-08", 600, 600),
    ("2026-09-15", 700, 360), ("2026-09-22", 600, 1080),
)
CS_START_MS, CS_GAIN_MS_PER_DAY, D_PRIME_M = 3.80, 0.001, 120.0
# Trace GPS FICTIVE de la sortie du dimanche : une boucle tracée en plein Atlantique (0° N, 25° O, aucun lieu
# réel), servie SANS fond de carte (`[dashboard].map_tiles = ""`) : la carte ne montre que la trace.
GPS_ORIGIN = (0.05, -25.0)


def _cs_speed(day: str, duration_s: int) -> float:
    days = (date.fromisoformat(day) - date(2026, 7, 21)).days
    return (CS_START_MS + CS_GAIN_MS_PER_DAY * days + D_PRIME_M / duration_s) * (0.98 + 0.01 * (duration_s % 2 == 0))


def _sample_file(root: Path, day: str) -> Path:
    path = next(p for p in activity_files(root) if p.name.startswith(day) and "running" in p.name)
    return root / f"activities/fit/{read_block(path)['garmin_activity_id']}.json"


def plant_efforts(root: Path) -> None:
    """Remplace une fenêtre de chaque séance « Seuil » par un effort soutenu à allure constante (± 0,6 %, bruit
    déterministe), sur le plat ; la distance cumulée est recalculée à partir de la fenêtre, le reste de la
    séance garde ses incréments. La FC monte vers 172 bpm pendant l'effort."""
    for day, start, duration in EFFORTS:
        path = _sample_file(root, day)
        doc = json.loads(path.read_text(encoding="utf-8"))
        recs = doc["records"]
        v = _cs_speed(day, duration)
        i0 = next(i for i, r in enumerate(recs) if r["t_s"] >= start)
        i1 = next((i for i, r in enumerate(recs) if r["t_s"] >= start + duration), len(recs) - 1)
        alt0, alt1 = recs[i0]["altitude_m"], recs[i1]["altitude_m"]
        old = [r["distance_m"] for r in recs]
        for i in range(i0, len(recs)):
            r = recs[i]
            dt = r["t_s"] - recs[i - 1]["t_s"] if i else 1
            if i < i1:
                k = (i - i0) / max(i1 - i0, 1)
                r["speed_ms"] = round(v * (1 + 0.006 * math.sin(i * 0.7)), 3)
                r["distance_m"] = round(recs[i - 1]["distance_m"] + r["speed_ms"] * dt, 3)
                r["altitude_m"] = round(alt0 + (alt1 - alt0) * k, 2)
                r["hr_bpm"] = round(min(174.0, 150 + 22 * (1 - math.exp(-(r["t_s"] - start) / 90))), 1)
            else:
                r["distance_m"] = round(recs[i - 1]["distance_m"] + (old[i] - old[i - 1]), 3)
        path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")


def add_fictional_gps(root: Path) -> None:
    """Boucle fictive de 18,2 km pour la sortie du dimanche 27 (aucune coordonnée réelle, voir GPS_ORIGIN)."""
    gid = read_block(root / f"activities/{STORY_ACTIVITY.isoformat()}_trail.md")["garmin_activity_id"]
    path = root / f"activities/fit/{gid}.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    total = doc["records"][-1]["distance_m"] or 1.0
    lat0, lon0 = GPS_ORIGIN
    for r in doc["records"]:
        a = 2 * math.pi * r["distance_m"] / total
        x = math.cos(a) + 0.18 * math.cos(2 * a + 0.6) + 0.05 * math.sin(5 * a)
        y = 0.58 * math.sin(a) + 0.14 * math.sin(2 * a + 1.9) + 0.05 * math.cos(4 * a)
        r["lat_deg"] = round(lat0 + 0.0215 * y, 6)
        r["lon_deg"] = round(lon0 + 0.0215 * x, 6)
    path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    cfg = root / "config/workspace.user.toml"
    cfg.write_text(cfg.read_text(encoding="utf-8") + '\n[dashboard]\nmap_tiles = ""\n', encoding="utf-8")


# Historique de décisions : (date, déclencheur, résultat, HRV/FC repos/readiness AVANT (J-2..J), APRÈS (J+1..J+3)).
# Les bilans matinaux allègent quand la triade plonge ; une fois Camille a gardé son seuil (refus).
DECISION_HISTORY = (
    ("2026-07-08", "morning_check", "applied", (46, 52, 40), (60, 47, 68)),
    ("2026-07-23", "morning_check", "applied", (45, 51, 37), (59, 46, 66)),
    ("2026-08-06", "morning_check", "applied", (47, 52, 41), (61, 47, 70)),
    ("2026-08-20", "morning_check", "applied", (44, 53, 36), (57, 48, 63)),
    ("2026-08-27", "morning_check", "rejected_by_athlete", (46, 52, 39), (43, 54, 33)),
    ("2026-09-03", "morning_check", "applied", (45, 52, 38), (58, 47, 66)),
    ("2026-09-10", "morning_check", "applied", (47, 51, 42), (49, 50, 45)),
)


def _set_health(root: Path, day: date, hrv: int, rhr: int, ready: int) -> None:
    path = root / f"medical/{day.isoformat()}_health.md"
    if path.exists():
        mutate(path, lambda d: d.update({"hrv_overnight_ms": hrv, "resting_hr_bpm": rhr, "readiness_score": ready,
                                         "hrv_status": "balanced" if hrv >= 52 else "low"}))


def write_decision_history(root: Path) -> None:
    for day_s, trigger, outcome, pre, post in DECISION_HISTORY:
        day = date.fromisoformat(day_s)
        for k in (2, 1, 0):
            _set_health(root, day - timedelta(days=k), pre[0] + k, pre[1] - (k > 0), pre[2] + 2 * k)
        for k in (1, 2, 3):
            _set_health(root, day + timedelta(days=k), post[0] - (3 - k), post[1] + (k == 1), post[2] - 2 * (3 - k))
        kept = outcome == "rejected_by_athlete"
        write(root, f"planning/{day_s}_decision_bilan-matinal.md", "Décision — bilan matinal", {
            "arc": 1, "kind": "decision", "date": day_s, "created_at": f"{day_s}T07:10:00+02:00",
            "trigger": trigger, "outcome": outcome,
            "summary": (f"HRV {pre[0]} ms sous la bande 52–70, readiness {pre[2]} : "
                        + ("allègement proposé, Camille garde son seuil." if kept else "seuil remplacé par une EF.")),
            "inputs": {"hrv_overnight_ms": pre[0], "hrv_band_low_ms": 52, "hrv_band_high_ms": 70,
                       "resting_hr_bpm": pre[1], "readiness_score": pre[2]},
            "sources": [f"medical/{day_s}_health.md"],
            "before": {"title": "Seuil 4 × 8 min", "intensity": "threshold", "planned_duration_s": 3600},
            "after": {"title": "Endurance fondamentale 45 min", "intensity": "endurance", "planned_duration_s": 2700},
        }, "## Contexte\n\nBilan matinal sous la bande personnelle : " + (
            "le coach propose d'alléger ; Camille préfère maintenir sa séance de seuil." if kept
            else "la séance de qualité est remplacée par de l'endurance fondamentale.")
            + "\n\n*Ne remplace pas un avis médical.*")


# Bloc planifié jusqu'au Trail des Crêtes : (lundi, phase, [(jour, sport, titre, intensité, durée min, D+)]).
_WEEK_PATTERN = ((1, "running", "Seuil 3 × 10 min", "threshold", 70, 0), (2, "running", "Endurance fondamentale", "endurance", 50, 0),
                 (3, "trail", "Côtes 10 × 1 min", "vo2max", 65, 380), (5, "trail", "Sortie longue", "endurance", 0, 0),
                 (6, "running", "Endurance fondamentale", "endurance", 45, 0))
PLAN_WEEKS = (   # lundi, phase, durée de la sortie longue (min) et son D+, facteur sur les autres séances
    ("2026-10-05", "Spécifique", 165, 1000, 1.0), ("2026-10-12", "Spécifique", 180, 1150, 1.05),
    ("2026-10-19", "Spécifique", 120, 700, 0.8), ("2026-10-26", "Spécifique", 195, 1250, 1.05),
    ("2026-11-02", "Spécifique", 180, 1100, 1.0), ("2026-11-09", "Affûtage", 120, 700, 0.75),
    ("2026-11-16", "Affûtage", 0, 0, 0.5),
)
SHORT_TAPER = (  # variante : affûtage d'une seule semaine (la semaine du 9 novembre reste une semaine de charge)
    ("2026-11-09", "Spécifique", 195, 1250, 1.05),
)


def _plan_week(monday_s: str, phase: str, long_min: int, long_dplus: int, factor: float) -> dict:
    monday = date.fromisoformat(monday_s)
    sessions = []
    race_week = long_min == 0
    for day, sport, title, intensity, minutes, dplus in _WEEK_PATTERN:
        when = (monday + timedelta(days=day)).isoformat()
        if race_week and day >= 5:
            continue
        if day == 5:
            minutes, dplus, title = long_min, long_dplus, f"Sortie longue {long_min // 60} h {long_min % 60:02d}"
        else:
            minutes = round(minutes * factor / 5) * 5
            dplus = round(dplus * factor, -1)
        s = {"date": when, "sport": sport, "title": title, "intensity": intensity, "outdoor": True,
             "planned_duration_s": minutes * 60, "status": "planned"}
        if dplus:
            s["planned_elevation_m"] = dplus
        sessions.append(s)
    if race_week:
        sessions.append({"date": RACE_DATE.isoformat(), "sport": "trail", "title": "Trail des Crêtes — 42 km",
                         "intensity": "race", "outdoor": True, "planned_duration_s": 22800,
                         "planned_elevation_m": 2100, "status": "planned"})
    total = sum(s["planned_duration_s"] for s in sessions if s["intensity"] != "race")
    return {"week_start": monday_s, "location": CITY, "phase": phase, "target_duration_s": total, "sessions": sessions}


def write_planned_block(root: Path) -> None:
    for week in PLAN_WEEKS:
        data = _plan_week(*week)
        write(root, f"planning/Semaine_{week[0]}.md", f"Semaine du {week[0]}", {"arc": 1, "kind": "week", **data},
              f"## Intention\n\nPhase {week[1].lower()} avant le Trail des Crêtes.")
    variant = {"weeks": [_plan_week(*w) for w in SHORT_TAPER]}
    (root / "planning/variante_affutage-court.json").write_text(json.dumps(variant, ensure_ascii=False, indent=1) + "\n",
                                                               encoding="utf-8")


# ---------------------------------------------------------------------------
# Assemblage
# ---------------------------------------------------------------------------

def build_demo(root: Path, *, with_samples: bool = True, force: bool = False, bloc: bool = False,
               suite: bool = False) -> Path:
    root = Path(root)
    if root.exists() and any(root.iterdir()):
        if not force:
            raise FileExistsError(f"{root} n'est pas vide : utilisez --force pour le reconstruire.")
        if not (root / MARKER).exists():
            raise FileExistsError(f"{root} n'est pas un workspace de démonstration (marqueur {MARKER} absent) : "
                                  "refus de l'effacer.")
        shutil.rmtree(root)
    root.mkdir(parents=True, exist_ok=True)
    (root / MARKER).write_text("Workspace de démonstration fictif (scripts/video_demo_workspace.py).\n", encoding="utf-8")

    syn.build(root, days=DAYS, today=TODAY, sport="trail", seed=SEED, with_samples=False)
    clean_base(root)
    fix_activities(root)
    fix_health(root)
    write_config(root)
    write_objective(root)
    story_sunday(root, with_samples)
    fix_nutrition(root)
    write_weeks(root)
    write_decisions(root)
    write_weather(root)
    write_race_plan(root)
    write_ultra_plan(root)
    write_reports(root)
    if with_samples:
        write_samples(root)
    set_departure(root)
    write_inspections(root)                       # après le départ : kilométrages cohérents avec la fiche
    if bloc:                                      # épisode 15 seulement : les autres épisodes gardent le workspace d'origine
        write_skeleton(root)                      # en dernier : lit le volume tenu dans l'index
    if suite:                                     # épisodes 16 et 17 seulement, même règle
        if with_samples:
            plant_efforts(root)
            add_fictional_gps(root)
        write_decision_history(root)
        write_planned_block(root)
    return root


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("dir")
    parser.add_argument("--force", action="store_true", help="reconstruit un workspace de démonstration existant")
    parser.add_argument("--no-samples", action="store_true", help="sans échantillons FIT (rapide)")
    parser.add_argument("--bloc", action="store_true", help="variante de l'épisode 15 (squelette de bloc)")
    parser.add_argument("--suite", action="store_true",
                        help="variante des épisodes 16-17 (efforts, trace fictive, bloc planifié, décisions passées)")
    args = parser.parse_args(argv)
    try:
        root = build_demo(Path(args.dir), with_samples=not args.no_samples, force=args.force, bloc=args.bloc,
                          suite=args.suite)
    except FileExistsError as exc:
        print(f"erreur : {exc}", file=sys.stderr)
        return 1
    print(root)
    return 0


if __name__ == "__main__":
    sys.exit(main())
