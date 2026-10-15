#!/usr/bin/env python3
"""Export des séances et du plan de course au format Vanoor (`.vanoor`).

## Pourquoi

Vanoor est une application de course pour Apple Watch, sans serveur ni API, qui
importe des séances structurées depuis un fichier JSON au format publié
`vanoor.workout/1` (étapes à la distance ou à la durée, cibles d'allure ou de FC,
répétitions, rappels de ravitaillement). C'est le seul chemin vers la montre pour
un athlète qui court avec une Apple Watch : rien n'est « poussé », l'athlète
importe le fichier dans l'app iPhone (*Mes séances → + → Importer des séances*),
qui l'envoie à la montre.

Opt-in strict : `[vanoor].export = "on"` (défaut `"off"`). À `off`, ce script
n'écrit rien (seul `--dry-run` reste permis) et aucun agent n'en parle.

## Sous-commandes

- `week` — séances d'une semaine planifiée. La STRUCTURE de chaque séance (étapes,
  cibles) est composée par le coach à partir des consignes de la semaine et lue sur
  l'entrée standard ; le script la valide contre les limites publiées, la rattache à
  la séance du fichier semaine (date, titre, sport) et écrit le fichier.
- `race` — plan de course : une séance par scénario, une étape par segment du plan
  (`race_plan.segments[]` ou sortie JSON de `arc_race_pacing.py`), allure cible du
  scénario, rappel à chaque ravitaillement. Déterministe, rien n'est composé par le
  modèle.
- `validate` — vérifie un fichier `.vanoor` existant.

Format vérifié sur les instructions d'import fournies par l'app (*Importer des
séances → Copier*), relevées le 2026-10-15 : voir `VANOOR_LIMITS`. Aucune
dépendance hors bibliothèque standard.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
import arc_contract as C  # noqa: E402
from arc_index import load_config  # noqa: E402
from coach_setup import workspace_root  # noqa: E402 (même résolution que arc_index.py)

SCHEMA = "vanoor.workout/1"

# Limites publiées dans les instructions d'import de l'app (format `vanoor.workout/1`).
VANOOR_LIMITS = {
    "workouts_per_file": 50,
    "steps_per_workout": 100,
    "splits_per_repeat": 20,
    "repeat_count": (1, 30),
    "distance_m": (1, 100000),
    "duration_s": (1, 86400),
    "pace_s_km": (120, 1200),
    "hr_zone": (1, 5),
}
TARGETS = ("open", "conversational", "pace", "hr_zone", "hr_range")
NUTRITION_TRIGGERS = ("position", "elapsed", "distance")
NUTRITION_UNITS = ("ml", "g", "pcs", "sip")
# Bornes de plausibilité d'une plage FC (bpm) : au-delà, c'est une faute de frappe.
HR_BOUNDS = (40, 230)

# Seuls sports exportés : Vanoor est une app de course à pied.
RUNNING_SPORTS = ("running", "trail")

# Plan de course — approximations du projet :
# - un segment de pente moyenne >= 3 % est une « montée », <= -2 % une « descente » ;
# - marge d'allure ±30 s/km en montée (l'allure y varie beaucoup avec la pente locale,
#   même sur un segment de pente moyenne régulière), ±20 s/km ailleurs.
CLIMB_GRADE_PCT = 3.0
DESCENT_GRADE_PCT = -2.0
CLIMB_TOLERANCE_S = 30
DEFAULT_TOLERANCE_S = 20
SCENARIOS = ("safe", "realistic", "ambitious")

LABELS = {
    "fr": {
        "climb": "Montée", "descent": "Descente", "flat": "Roulant", "walk": "marche",
        "week_folder": "Semaine du {d}", "aid": "Ravito {name}",
        "safe": "prudent", "realistic": "réaliste", "ambitious": "ambitieux",
        "days": ("Lun", "Mar", "Mer", "Jeu", "Ven", "Sam", "Dim"), "decimal": ",",
    },
    "en": {
        "climb": "Climb", "descent": "Descent", "flat": "Rolling", "walk": "walk",
        "week_folder": "Week of {d}", "aid": "Aid {name}",
        "safe": "safe", "realistic": "realistic", "ambitious": "ambitious",
        "days": ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"), "decimal": ".",
    },
}

SELECTOR_RE = re.compile(r"^(?P<date>\d{4}-\d{2}-\d{2})(?:@(?P<index>\d+)|:(?P<title>.+))?$")


class VanoorError(ValueError):
    """Entrée invalide : message lisible, pas de trace."""


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


def settings(workspace: Path) -> dict:
    """`[vanoor]` résolu (user.toml prime) : `export` (`on`/`off`, inconnu = `off`), `output_dir`
    (vide = `<workspace>/exports/vanoor`, `~` développé, relatif = depuis le workspace) et la
    langue des documents (libellés des étapes)."""
    config = load_config(workspace)
    section = config.get("vanoor", {})
    export = section.get("export", "off")
    raw_dir = section.get("output_dir", "")
    if not isinstance(raw_dir, str) or not raw_dir.strip():
        out = workspace / "exports" / "vanoor"
    else:
        out = Path(raw_dir.strip()).expanduser()
        if not out.is_absolute():
            out = workspace / out
    lang = config.get("language", {}).get("documents", "fr")
    return {
        "enabled": export == "on",
        "output_dir": out,
        "lang": lang if lang in LABELS else "fr",
    }


# ---------------------------------------------------------------------------
# Validation et normalisation des étapes
# ---------------------------------------------------------------------------


def _int(value, where: str, bounds: Tuple[int, int]) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise VanoorError(f"{where} : nombre attendu, {value!r} trouvé")
    number = round(value)
    lo, hi = bounds
    if not lo <= number <= hi:
        raise VanoorError(f"{where} : {number} hors des limites Vanoor [{lo}, {hi}]")
    return number


def normalize_split(step: dict, where: str) -> dict:
    """Une étape `split` au format Vanoor. Raccourci accepté : `"paceRange": [lent, rapide]`
    (s/km, tel que rendu par `arc_workout_targets.py`) → `secondsPerKm` au milieu de la plage et
    `toleranceSeconds` à la demi-largeur."""
    label = step.get("label")
    if not isinstance(label, str) or not label.strip():
        raise VanoorError(f"{where} : « label » obligatoire")
    out = {"type": "split", "label": label.strip()}
    has_distance, has_duration = "distance" in step, "duration" in step
    if has_distance == has_duration:
        raise VanoorError(f"{where} ({label}) : « distance » OU « duration », jamais les deux ni aucun")
    if has_distance:
        out["distance"] = _int(step["distance"], f"{where}.distance", VANOOR_LIMITS["distance_m"])
    else:
        out["duration"] = _int(step["duration"], f"{where}.duration", VANOOR_LIMITS["duration_s"])
    target = step.get("target")
    if target not in TARGETS:
        raise VanoorError(f"{where} ({label}) : « target » parmi {', '.join(TARGETS)}, {target!r} trouvé")
    out["target"] = target
    if target == "pace":
        if "paceRange" in step:
            rng = step["paceRange"]
            if not (isinstance(rng, list) and len(rng) == 2):
                raise VanoorError(f"{where}.paceRange : [allure lente, allure rapide] en s/km attendu")
            a = _int(rng[0], f"{where}.paceRange", VANOOR_LIMITS["pace_s_km"])
            b = _int(rng[1], f"{where}.paceRange", VANOOR_LIMITS["pace_s_km"])
            lo, hi = min(a, b), max(a, b)
            out["secondsPerKm"] = round((lo + hi) / 2)
            out["toleranceSeconds"] = max(1, round((hi - lo) / 2))
        else:
            out["secondsPerKm"] = _int(step.get("secondsPerKm"), f"{where}.secondsPerKm",
                                       VANOOR_LIMITS["pace_s_km"])
            if "toleranceSeconds" in step:
                out["toleranceSeconds"] = _int(step["toleranceSeconds"], f"{where}.toleranceSeconds", (1, 600))
    elif target == "hr_zone":
        out["zone"] = _int(step.get("zone"), f"{where}.zone", VANOOR_LIMITS["hr_zone"])
    elif target == "hr_range":
        lo = _int(step.get("minBpm"), f"{where}.minBpm", HR_BOUNDS)
        hi = _int(step.get("maxBpm"), f"{where}.maxBpm", HR_BOUNDS)
        if lo >= hi:
            raise VanoorError(f"{where} ({label}) : minBpm ({lo}) doit être inférieur à maxBpm ({hi})")
        out["minBpm"], out["maxBpm"] = lo, hi
    return out


def normalize_nutrition(step: dict, where: str) -> dict:
    trigger = step.get("trigger")
    if trigger not in NUTRITION_TRIGGERS:
        raise VanoorError(f"{where} : « trigger » parmi {', '.join(NUTRITION_TRIGGERS)}, {trigger!r} trouvé")
    out: dict = {"type": "nutrition", "trigger": trigger}
    if trigger == "elapsed":
        out["seconds"] = _int(step.get("seconds"), f"{where}.seconds", VANOOR_LIMITS["duration_s"])
    elif trigger == "distance":
        out["meters"] = _int(step.get("meters"), f"{where}.meters", VANOOR_LIMITS["distance_m"])
    items = step.get("items")
    if not isinstance(items, list) or not items:
        raise VanoorError(f"{where} : « items » (liste non vide) obligatoire")
    out["items"] = []
    for i, item in enumerate(items):
        if not isinstance(item, dict) or not isinstance(item.get("name"), str) or not item["name"].strip():
            raise VanoorError(f"{where}.items[{i}] : « name » obligatoire")
        quantity = item.get("quantity")
        if isinstance(quantity, bool) or not isinstance(quantity, (int, float)) or quantity <= 0:
            raise VanoorError(f"{where}.items[{i}] : « quantity » > 0 attendue")
        if item.get("unit") not in NUTRITION_UNITS:
            raise VanoorError(f"{where}.items[{i}] : « unit » parmi {', '.join(NUTRITION_UNITS)}")
        out["items"].append({"name": item["name"].strip(), "quantity": quantity, "unit": item["unit"]})
    return out


def normalize_steps(steps, where: str) -> List[dict]:
    """Valide et normalise la liste d'étapes d'une séance (limites Vanoor). Le plafond de
    100 étapes compte les étapes telles qu'écrites (une répétition et chacune de ses étapes),
    pas leur déroulé × `count` : les instructions de l'app ne précisent pas le mode de calcul,
    ce choix est le moins restrictif des deux lectures."""
    if not isinstance(steps, list) or not steps:
        raise VanoorError(f"{where} : « steps » (liste non vide) obligatoire")
    out, count = [], 0
    for i, step in enumerate(steps):
        at = f"{where}.steps[{i}]"
        kind = step.get("type") if isinstance(step, dict) else None
        if kind == "split":
            out.append(normalize_split(step, at))
            count += 1
        elif kind == "nutrition":
            out.append(normalize_nutrition(step, at))
            count += 1
        elif kind == "repeat":
            inner = step.get("steps")
            if not isinstance(inner, list) or not inner:
                raise VanoorError(f"{at} : une répétition contient une liste « steps » non vide")
            if len(inner) > VANOOR_LIMITS["splits_per_repeat"]:
                raise VanoorError(f"{at} : {len(inner)} étapes dans la répétition (max "
                                  f"{VANOOR_LIMITS['splits_per_repeat']})")
            splits = []
            for j, sub in enumerate(inner):
                if not isinstance(sub, dict) or sub.get("type") != "split":
                    raise VanoorError(f"{at}.steps[{j}] : une répétition ne contient que des « split »")
                splits.append(normalize_split(sub, f"{at}.steps[{j}]"))
            out.append({"type": "repeat",
                        "count": _int(step.get("count"), f"{at}.count", VANOOR_LIMITS["repeat_count"]),
                        "steps": splits})
            count += 1 + len(splits)
        else:
            raise VanoorError(f"{at} : « type » parmi split, repeat, nutrition ; {kind!r} trouvé")
    if count > VANOOR_LIMITS["steps_per_workout"]:
        raise VanoorError(f"{where} : {count} étapes (max {VANOOR_LIMITS['steps_per_workout']})")
    return out


def validate_document(doc) -> List[str]:
    """Erreurs d'un document `.vanoor` complet (liste vide = valide)."""
    if not isinstance(doc, dict) or doc.get("schema") != SCHEMA:
        return [f"« schema » : {SCHEMA!r} attendu"]
    workouts = doc.get("workouts")
    if not isinstance(workouts, list) or not workouts:
        return ["« workouts » : liste non vide attendue"]
    errors = []
    if len(workouts) > VANOOR_LIMITS["workouts_per_file"]:
        errors.append(f"{len(workouts)} séances (max {VANOOR_LIMITS['workouts_per_file']} par fichier)")
    for i, workout in enumerate(workouts):
        where = f"workouts[{i}]"
        if not isinstance(workout, dict) or not isinstance(workout.get("name"), str) or not workout["name"].strip():
            errors.append(f"{where} : « name » obligatoire")
            continue
        try:
            normalize_steps(workout.get("steps"), f"{where} ({workout['name']})")
        except VanoorError as exc:
            errors.append(str(exc))
    return errors


# ---------------------------------------------------------------------------
# Semaine
# ---------------------------------------------------------------------------


def _read_arc(path: Path, kind: str) -> dict:
    try:
        block = C.extract_block(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise VanoorError(f"{path} illisible : {exc}") from exc
    except C.ContractError as exc:
        raise VanoorError(f"{path} : {exc}") from exc
    if not block or block.get("kind") != kind:
        raise VanoorError(f"{path} : bloc ```arc de type « {kind} » attendu")
    return block


def select_session(sessions: List[dict], selector: str) -> dict:
    """`AAAA-MM-JJ` (une seule séance ce jour-là), `AAAA-MM-JJ@index` (0-based, ordre du fichier)
    ou `AAAA-MM-JJ:titre` (titre exact) — même grammaire que `arc_workout_targets.py --session`."""
    m = SELECTOR_RE.match(selector or "")
    if not m:
        raise VanoorError(f"séance {selector!r} : AAAA-MM-JJ, AAAA-MM-JJ@index ou AAAA-MM-JJ:titre attendu")
    same_day = [s for s in sessions if s.get("date") == m.group("date")]
    if m.group("title") is not None:
        same_day = [s for s in same_day if s.get("title") == m.group("title")]
    elif m.group("index") is not None:
        idx = int(m.group("index"))
        same_day = same_day[idx:idx + 1]
    if not same_day:
        raise VanoorError(f"séance {selector!r} absente du fichier semaine")
    if len(same_day) > 1:
        raise VanoorError(f"séance {selector!r} : {len(same_day)} séances ce jour-là, préciser @index ou :titre")
    return same_day[0]


def _short_date(iso: str, lang: str) -> str:
    d = date.fromisoformat(iso)
    return f"{LABELS[lang]['days'][d.weekday()]} {d.day:02d}/{d.month:02d}"


def build_week(week: dict, request: dict, lang: str) -> Tuple[dict, List[dict]]:
    """Document Vanoor des séances demandées, dans l'ordre du fichier semaine. Rend aussi les
    séances de course de la semaine encore `planned` sans structure fournie (`missing`) pour que
    le coach sache ce qu'il n'a pas exporté."""
    entries = request.get("sessions") if isinstance(request, dict) else None
    if not isinstance(entries, list) or not entries:
        raise VanoorError("entrée standard : {\"sessions\": [{\"session\": \"AAAA-MM-JJ\", \"steps\": [...]}]} attendu")
    sessions = week.get("sessions", [])
    chosen: Dict[int, Tuple[dict, List[dict]]] = {}
    for i, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise VanoorError(f"sessions[{i}] : objet attendu")
        session = select_session(sessions, entry.get("session"))
        if session.get("sport") not in RUNNING_SPORTS:
            raise VanoorError(f"séance {entry.get('session')!r} ({session.get('sport')}) : seules les séances "
                              f"{' / '.join(RUNNING_SPORTS)} vont dans Vanoor")
        key = next(k for k, s in enumerate(sessions) if s is session)
        if key in chosen:
            raise VanoorError(f"séance {entry.get('session')!r} fournie deux fois")
        chosen[key] = (session, normalize_steps(entry.get("steps"), f"séance {entry.get('session')}"))
    labels = LABELS[lang]
    monday = date.fromisoformat(week["week_start"])
    folder = labels["week_folder"].format(d=f"{monday.day:02d}/{monday.month:02d}")
    workouts = []
    for key in sorted(chosen):
        session, steps = chosen[key]
        workouts.append({"name": f"{_short_date(session['date'], lang)} · {session.get('title', '').strip()}",
                         "folder": folder, "steps": steps})
    if len(workouts) > VANOOR_LIMITS["workouts_per_file"]:
        raise VanoorError(f"{len(workouts)} séances (max {VANOOR_LIMITS['workouts_per_file']} par fichier)")
    missing = [{"date": s.get("date"), "title": s.get("title")}
               for k, s in enumerate(sessions)
               if k not in chosen and s.get("sport") in RUNNING_SPORTS and s.get("status", "planned") == "planned"]
    return {"schema": SCHEMA, "workouts": workouts}, missing


# ---------------------------------------------------------------------------
# Plan de course
# ---------------------------------------------------------------------------


def load_race_plan(path: Path) -> dict:
    """Un plan de course au contrat (`planning/…md`, bloc `race_plan`) ou la sortie JSON brute de
    `arc_race_pacing.py plan` (clé `segments` à la racine)."""
    if path.suffix.lower() == ".json":
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise VanoorError(f"{path} : JSON illisible ({exc})") from exc
        if not isinstance(data, dict) or not isinstance(data.get("segments"), list):
            raise VanoorError(f"{path} : sortie de arc_race_pacing.py attendue (clé « segments »)")
        return data
    return _read_arc(path, "race_plan")


def _km(value: float, lang: str) -> str:
    return f"{value:.1f}".replace(".", LABELS[lang]["decimal"])


def _hm(seconds: float) -> str:
    total = round(seconds)
    return f"{total // 3600}h{total % 3600 // 60:02d}"


def build_race(plan: dict, name: str, scenarios: Sequence[str], lang: str) -> Tuple[dict, List[str]]:
    segments = plan.get("segments")
    if not isinstance(segments, list) or not segments:
        raise VanoorError("plan de course sans segments (plan écrit sans GPX ?) : rien à exporter")
    labels = LABELS[lang]
    warnings: List[str] = []
    aid_stations = sorted((a for a in plan.get("aid_stations", []) if isinstance(a, dict)),
                          key=lambda a: a.get("km", 0))
    workouts = []
    for scenario in scenarios:
        steps: List[dict] = []
        total = 0.0
        for seg in segments:
            pace = (seg.get("pace_s_km") or {}).get(scenario)
            if pace is None:
                raise VanoorError(f"segment {seg.get('id')} : pas d'allure pour le scénario « {scenario} »")
            total += (seg.get("predicted_time_s") or {}).get(scenario, 0)
            grade = seg.get("grade_mean_pct", 0.0)
            kind = "climb" if grade >= CLIMB_GRADE_PCT else "descent" if grade <= DESCENT_GRADE_PCT else "flat"
            label = f"{labels[kind]} km {_km(seg['km_start'], lang)}-{_km(seg['km_end'], lang)}"
            distance = seg.get("distance_m") or (seg["km_end"] - seg["km_start"]) * 1000
            step = {"type": "split", "label": label, "distance": round(distance)}
            lo, hi = VANOOR_LIMITS["pace_s_km"]
            if lo <= pace <= hi:
                step.update(target="pace", secondsPerKm=round(pace),
                            toleranceSeconds=CLIMB_TOLERANCE_S if kind == "climb" else DEFAULT_TOLERANCE_S)
            else:
                # Hors des bornes Vanoor (montée d'ultra marchée au-delà de 20:00/km) : au ressenti,
                # jamais une allure tronquée qui mentirait sur le plan.
                step.update(target="conversational", label=f"{label} ({labels['walk']})")
                warnings.append(f"segment {seg.get('id')} ({scenario}) : allure {round(pace)} s/km hors des "
                                f"bornes Vanoor [{lo}, {hi}], exporté au ressenti")
            steps.append(normalize_split(step, f"segment {seg.get('id')}"))
        for aid in aid_stations:
            meters = round(aid["km"] * 1000)
            if VANOOR_LIMITS["distance_m"][0] <= meters <= VANOOR_LIMITS["distance_m"][1]:
                steps.append({"type": "nutrition", "trigger": "distance", "meters": meters,
                              "items": [{"name": labels["aid"].format(name=aid["name"]), "quantity": 1,
                                         "unit": "pcs"}]})
        title = f"{name} · {labels[scenario]}"
        if total:
            title += f" {_hm(total)}"
        workouts.append({"name": title, "folder": name, "steps": normalize_steps(steps, title)})
    return {"schema": SCHEMA, "workouts": workouts}, warnings


# ---------------------------------------------------------------------------
# Écriture et CLI
# ---------------------------------------------------------------------------


def slugify(text: str) -> str:
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", ascii_text.lower()).strip("-") or "course"


def write_document(doc: dict, out_dir: Path, filename: str) -> Path:
    errors = validate_document(doc)
    if errors:  # garde-fou : jamais un fichier que l'app refuserait
        raise VanoorError("document invalide : " + " ; ".join(errors))
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / filename
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def _emit(payload: dict) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def _finish(doc: dict, conf: dict, filename: str, dry_run: bool, extra: dict) -> int:
    summary = [{"name": w["name"], "steps": len(w["steps"])} for w in doc["workouts"]]
    if dry_run:
        _emit({"status": "dry_run", "filename": filename, "workouts": summary, **extra, "document": doc})
        return 0
    if not conf["enabled"]:
        _emit({"status": "disabled", "reason": "[vanoor].export n'est pas « on » : rien n'est écrit "
                                               "(--dry-run pour voir le fichier)"})
        return 2
    path = write_document(doc, conf["output_dir"], filename)
    _emit({"status": "written", "path": str(path), "workouts": summary, **extra})
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0],
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--workspace", help="racine du workspace (défaut : même résolution que arc_index.py)")
    sub = parser.add_subparsers(dest="command", required=True)

    p_week = sub.add_parser("week", help="séances d'une semaine (structure lue en JSON sur l'entrée standard)")
    p_week.add_argument("--week", required=True, help="fichier semaine (planning/Semaine_AAAA-MM-JJ.md)")
    p_week.add_argument("--dry-run", action="store_true", help="affiche le document sans rien écrire")

    p_race = sub.add_parser("race", help="plan de course : une séance par scénario, une étape par segment")
    p_race.add_argument("--plan", required=True,
                        help="plan de course au contrat (planning/…md) ou sortie JSON de arc_race_pacing.py")
    p_race.add_argument("--name", help="nom de la course (défaut : race_name du plan)")
    p_race.add_argument("--race-date", help="date de la course AAAA-MM-JJ (défaut : race_date du plan)")
    p_race.add_argument("--scenario", action="append", choices=SCENARIOS,
                        help="scénario à exporter, répétable (défaut : tous ceux du plan)")
    p_race.add_argument("--dry-run", action="store_true", help="affiche le document sans rien écrire")

    p_val = sub.add_parser("validate", help="vérifie un fichier .vanoor")
    p_val.add_argument("file", help="fichier .vanoor à vérifier")

    args = parser.parse_args(argv)
    workspace = workspace_root(args.workspace)
    try:
        if args.command == "validate":
            try:
                doc = json.loads(Path(args.file).read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise VanoorError(f"{args.file} : JSON illisible ({exc})") from exc
            errors = validate_document(doc)
            _emit({"status": "ok" if not errors else "invalid", "errors": errors})
            return 0 if not errors else 1

        conf = settings(workspace)
        if args.command == "week":
            week_path = Path(args.week)
            if not week_path.is_absolute():
                week_path = workspace / week_path
            week = _read_arc(week_path, "week")
            raw = sys.stdin.read() if not sys.stdin.isatty() else ""
            try:
                request = json.loads(raw) if raw.strip() else None
            except json.JSONDecodeError as exc:
                raise VanoorError(f"entrée standard : JSON invalide ({exc.msg}, ligne {exc.lineno})") from exc
            doc, missing = build_week(week, request, conf["lang"])
            return _finish(doc, conf, f"semaine-{week['week_start']}.vanoor", args.dry_run, {"missing": missing})

        plan_path = Path(args.plan)
        if not plan_path.is_absolute():
            plan_path = workspace / plan_path
        plan = load_race_plan(plan_path)
        name = args.name or plan.get("race_name")
        if not name:
            raise VanoorError("nom de la course absent du plan : --name obligatoire")
        race_date = args.race_date or plan.get("race_date") or ""
        scenarios = args.scenario or [s for s in SCENARIOS
                                      if all(s in (seg.get("pace_s_km") or {}) for seg in plan.get("segments", []))]
        if not scenarios:
            raise VanoorError("aucun scénario commun à tous les segments du plan")
        doc, warnings = build_race(plan, name, scenarios, conf["lang"])
        filename = f"course-{race_date + '-' if race_date else ''}{slugify(name)}.vanoor"
        return _finish(doc, conf, filename, args.dry_run, {"warnings": warnings})
    except VanoorError as exc:
        _emit({"status": "error", "error": str(exc)})
        return 1


if __name__ == "__main__":
    sys.exit(main())
