"""Palier D — brief Horae (`scripts/arc_brief.py`, `POST /mcp` de `arc_serve.py`).

Contrat : Horae brief v1 (https://github.com/horae-dev/plugin-mcp-brief), schéma et exemples
copiés dans `tests/data/fixtures/horae_brief/` (provenance : `SOURCE.json`). Le schéma est
vérifié par un petit validateur JSON Schema (le sous-ensemble que v1 utilise), lui-même éprouvé
sur les exemples valides ET invalides du contrat : bibliothèque standard seulement.
"""

from __future__ import annotations

import http.client
import json
import re
import shutil
import sys
import tempfile
import threading
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))
import arc_brief as AB  # noqa: E402
import arc_serve as S  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "horae_brief"
SCHEMA = json.loads((FIXTURES / "v1.json").read_text(encoding="utf-8"))
TOKEN = "t0k3n-" + "A" * 40
PARIS = timezone(timedelta(hours=1))


# ---------------------------------------------------------------------------
# Validateur JSON Schema (sous-ensemble draft 2020-12 utilisé par brief v1)
# ---------------------------------------------------------------------------

def _pattern(p: str) -> "re.Pattern":
    # ECMA `$` ne tolère pas un saut de ligne final, le `$` de Python si : ancrage strict.
    return re.compile(p[:-1] + r"\Z" if p.endswith("$") else p)


def schema_errors(instance, schema=SCHEMA, root=SCHEMA, path="$") -> list:
    errors = []
    if "$ref" in schema:
        name = schema["$ref"].split("/")[-1]
        return schema_errors(instance, root["$defs"][name], root, path)
    if "anyOf" in schema:
        if all(schema_errors(instance, sub, root, path) for sub in schema["anyOf"]):
            errors.append(f"{path}: aucune branche de anyOf")
    kind = schema.get("type")
    checks = {"object": dict, "array": list, "string": str, "null": type(None)}
    if kind == "integer":
        if not isinstance(instance, int) or isinstance(instance, bool):
            return errors + [f"{path}: entier attendu"]
    elif kind in checks and not isinstance(instance, checks[kind]):
        return errors + [f"{path}: {kind} attendu"]
    if "const" in schema and instance != schema["const"]:
        errors.append(f"{path}: const")
    if "enum" in schema and instance not in schema["enum"]:
        errors.append(f"{path}: enum")
    if isinstance(instance, str):
        if len(instance) < schema.get("minLength", 0) or len(instance) > schema.get("maxLength", 10 ** 9):
            errors.append(f"{path}: longueur")
        if "pattern" in schema and not _pattern(schema["pattern"]).search(instance):
            errors.append(f"{path}: motif")
        if schema.get("format") == "date":
            try:
                date.fromisoformat(instance)
            except ValueError:
                errors.append(f"{path}: date")
        if schema.get("format") == "date-time":
            try:
                datetime.fromisoformat(instance.replace("Z", "+00:00"))
            except ValueError:
                errors.append(f"{path}: date-time")
    if isinstance(instance, list):
        if len(instance) > schema.get("maxItems", 10 ** 9):
            errors.append(f"{path}: trop d'éléments")
        for i, item in enumerate(instance):
            errors += schema_errors(item, schema.get("items", {}), root, f"{path}[{i}]")
    if isinstance(instance, dict):
        props = schema.get("properties", {})
        for key in schema.get("required", []):
            if key not in instance:
                errors.append(f"{path}: {key} manquant")
        if schema.get("additionalProperties") is False:
            errors += [f"{path}: champ inconnu {k}" for k in instance if k not in props]
        for key, value in instance.items():
            if key in props:
                errors += schema_errors(value, props[key], root, f"{path}.{key}")
        if "if" in schema and not schema_errors(instance, schema["if"], root, path):
            errors += schema_errors(instance, schema.get("then", {}), root, path)
    return errors


def contract_errors(doc: dict) -> list:
    """Schéma + règles hors schéma du plugin (unicité des clés, validité bornée)."""
    errors = schema_errors(doc)
    keys = [a["key"] for a in doc.get("alerts", [])]
    ids = [t["id"] for t in doc.get("tasks", [])]
    if len(keys) != len(set(keys)) or len(ids) != len(set(ids)):
        errors.append("clé ou id répété")
    if not errors:
        generated = datetime.fromisoformat(doc["generated_at"].replace("Z", "+00:00"))
        valid = datetime.fromisoformat(doc["valid_until"].replace("Z", "+00:00"))
        if not generated < valid <= generated + timedelta(hours=24):
            errors.append("valid_until hors de ]generated_at, +24 h]")
    return errors


class TestVendoredContract(unittest.TestCase):
    """Le validateur ci-dessus accepte les exemples valides du contrat et refuse tous les invalides."""

    def test_source_is_pinned(self):
        source = json.loads((FIXTURES / "SOURCE.json").read_text(encoding="utf-8"))
        self.assertRegex(source["commit"], r"^[0-9a-f]{40}$")
        self.assertEqual(SCHEMA["title"], "Horae brief v1")

    def test_valid_examples_pass(self):
        files = sorted((FIXTURES / "examples/valid").glob("*.json"))
        self.assertTrue(files)
        for path in files:
            with self.subTest(path.name):
                self.assertEqual(schema_errors(json.loads(path.read_text(encoding="utf-8"))), [])

    def test_invalid_examples_fail(self):
        files = sorted((FIXTURES / "examples/invalid").glob("*.json"))
        self.assertGreaterEqual(len(files), 10)
        for path in files:
            with self.subTest(path.name):
                self.assertNotEqual(schema_errors(json.loads(path.read_text(encoding="utf-8"))), [])


# ---------------------------------------------------------------------------
# Producteur (faits → document)
# ---------------------------------------------------------------------------

NOW = datetime(2026, 11, 27, 6, 30, tzinfo=PARIS)            # un vendredi
BASE = "https://coach.example.org/"


def facts(**over) -> dict:
    base = {
        "today": "2026-11-27", "language": "fr", "morning_check": "full",
        "sessions_today": [{"sport": "trail", "intensity": "endurance", "planned_duration_s": 4200,
                            "planned_distance_m": 12000, "planned_elevation_m": 450, "status": "planned"}],
        "health_today": {"verdict": "green", "readiness_score": 72, "hrv_personal_status": "dans_la_norme",
                         "rhr_delta": 1.0, "advice_actions": ["keep"]},
        "feedback_missing": [], "next_week_planned": True, "race": None, "shoes": [],
        "sync": {"verdict": "ok", "mode": "schedule", "last_ok_run_at": "2026-11-27T05:15:00",
                 "oldest_run_at": "2026-11-14T07:15:00", "last_check_at": None},
    }
    base.update(over)
    return base


class TestBuildBrief(unittest.TestCase):
    def brief(self, now=NOW, base=BASE, **over) -> dict:
        doc = AB.build_brief(facts(**over), now, base)
        self.assertEqual(contract_errors(doc), [], json.dumps(doc, ensure_ascii=False, indent=1))
        return doc

    def test_nominal_day(self):
        doc = self.brief()
        self.assertEqual(doc["status"], {"state": "ok"})
        self.assertEqual(doc["service"], {"id": "ai-running-coach", "name": "Coach running"})
        self.assertEqual(doc["headline"], "Aujourd'hui : Trail endurance 1 h 10 · 12 km · 450 m D+ · feu vert, readiness 72")
        self.assertEqual(doc["alerts"], [])
        self.assertEqual(doc["tasks"], [])
        self.assertEqual(doc["generated_at"], "2026-11-27T06:30:00+01:00")
        self.assertEqual(doc["valid_until"], "2026-11-27T18:30:00+01:00")
        self.assertTrue(all(link["url"].startswith(BASE) for link in doc["links"]))

    def test_validity_ends_at_local_midnight_and_stays_after_generation(self):
        late = datetime(2026, 11, 27, 21, 0, tzinfo=PARIS)
        self.assertEqual(self.brief(now=late)["valid_until"], "2026-11-28T00:00:00+01:00")
        last_minute = datetime(2026, 11, 27, 23, 59, 30, tzinfo=PARIS)
        self.assertEqual(self.brief(now=last_minute)["valid_until"], "2026-11-28T00:14:30+01:00")

    def test_naive_now_is_refused(self):
        with self.assertRaises(ValueError):
            AB.build_brief(facts(), datetime(2026, 11, 27, 6, 30))

    def test_rest_day_and_missing_check(self):
        doc = self.brief(sessions_today=[], health_today=None)
        self.assertEqual(doc["headline"], "Aujourd'hui : rien de prévu · bilan matinal pas encore fait")

    def test_morning_check_off_hides_health(self):
        doc = self.brief(morning_check="off", health_today={"verdict": "red", "readiness_score": 10})
        self.assertNotIn("feu", doc["headline"])
        self.assertEqual(doc["alerts"], [])

    def test_low_readiness_hrv_and_rhr_are_warnings(self):
        doc = self.brief(health_today={"verdict": "red", "readiness_score": 22, "hrv_personal_status": "sous",
                                       "rhr_delta": 8.4, "advice_actions": ["cancel", "lighten"]})
        self.assertEqual([(a["key"], a["severity"]) for a in doc["alerts"]],
                         [("readiness.low", "warn"), ("hrv.below_baseline", "warn"), ("rhr.elevated", "warn")])
        self.assertIn("séance annulée par le bilan", doc["headline"])
        self.assertEqual(doc["alerts"][2]["title"], "FC de repos élevée (+8 bpm)")

    def test_shoes_near_and_over_threshold(self):
        doc = self.brief(shoes=[
            {"gear_id": "speedgoat", "name": "Hoka Speedgoat 5", "distance_m": 712000, "threshold_m": 700000,
             "alert": True},
            {"gear_id": "Pegasus 40 (rouge)", "name": "Pegasus‮ 40\n", "distance_m": 640000,
             "threshold_m": 700000, "near_threshold": True, "retire_forecast_date": "2026-12-20"},
            {"gear_id": "old", "name": "Old", "distance_m": 900000, "threshold_m": 700000, "alert": False,
             "retired": True},
        ])
        keys = [a["key"] for a in doc["alerts"]]
        self.assertEqual(keys[0], "shoe.speedgoat.retire")
        self.assertRegex(keys[1], r"^shoe\.h[0-9a-f]{12}\.near$")       # id non conforme : haché, stable
        self.assertEqual(doc["alerts"][1]["title"], "Chaussures bientôt en fin de vie : Pegasus 40")
        self.assertIn("vers le 20/12", doc["alerts"][1]["body"])
        self.assertEqual(len(doc["alerts"]), 2)                           # la paire retirée n'alerte pas

    def test_alerts_capped_with_crit_first(self):
        shoes = [{"gear_id": f"s{i}", "name": f"S{i}", "distance_m": 800000, "threshold_m": 700000, "alert": True}
                 for i in range(15)]
        doc = self.brief(shoes=shoes, sync={"verdict": "failing", "mode": "schedule",
                                            "last_ok_run_at": "2026-11-25T07:15:00"})
        self.assertEqual(len(doc["alerts"]), 10)
        self.assertEqual(doc["alerts"][0]["severity"], "crit")

    def test_sync_failing_over_24h_is_the_only_crit(self):
        doc = self.brief(sync={"verdict": "failing", "mode": "schedule", "last_ok_run_at": "2026-11-26T05:00:00",
                               "oldest_run_at": "2026-11-20T07:15:00"})
        self.assertEqual(doc["status"]["state"], "degraded")
        self.assertEqual([(a["key"], a["severity"]) for a in doc["alerts"]], [("sync.failing", "crit")])
        self.assertEqual(doc["alerts"][0]["link"], BASE + "#/synchro")

    def test_sync_failing_under_24h_is_a_warning(self):
        doc = self.brief(sync={"verdict": "failing", "mode": "schedule", "last_ok_run_at": "2026-11-26T14:15:00"})
        self.assertEqual([(a["key"], a["severity"]) for a in doc["alerts"]], [("sync.late", "warn")])
        self.assertEqual(doc["status"]["state"], "degraded")

    def test_watch_late_uses_last_probe(self):
        doc = self.brief(sync={"verdict": "late", "mode": "watch", "last_ok_run_at": "2026-11-27T05:00:00",
                               "last_check_at": "2026-11-25T22:00:00"})
        self.assertEqual(doc["alerts"][0]["severity"], "crit")

    def test_sync_never_and_degraded_are_warnings(self):
        for verdict in ("never", "degraded"):
            with self.subTest(verdict):
                doc = self.brief(sync={"verdict": verdict, "mode": "schedule", "last_ok_run_at": None,
                                       "oldest_run_at": "2026-11-01T07:15:00"})
                self.assertEqual(doc["status"]["state"], "degraded")
                self.assertNotIn("crit", [a["severity"] for a in doc["alerts"]])

    def test_tasks_feedback_plan_and_race(self):
        doc = self.brief(feedback_missing=["2026-11-26", "2026-11-27"], next_week_planned=False,
                         race={"name": "Trail des Collines", "date": "2026-12-06", "has_plan": True})
        self.assertEqual([(t["id"], t["due"]) for t in doc["tasks"]], [
            ("feedback.2026-11-26", "2026-11-27"), ("feedback.2026-11-27", "2026-11-27"),
            ("plan.week.2026-11-30", "2026-11-29"), ("race.review.2026-12-06", "2026-12-03")])
        self.assertEqual(doc["tasks"][3]["title"], "Relire le plan de course : Trail des Collines (06/12)")
        self.assertIn("Trail des Collines dans 9 j", doc["headline"])

    def test_race_without_plan_and_far_race(self):
        doc = self.brief(race={"name": "Ultra", "date": "2026-11-30", "has_plan": False})
        self.assertEqual([t["id"] for t in doc["tasks"]], ["race.plan.2026-11-30"])
        self.assertEqual(self.brief(race={"name": "Ultra", "date": "2027-03-01", "has_plan": False})["tasks"], [])

    def test_plan_week_only_from_friday(self):
        doc = self.brief(today="2026-11-25", next_week_planned=False)
        self.assertEqual(doc["tasks"], [])

    def test_ids_and_keys_are_stable_across_calls(self):
        over = dict(feedback_missing=["2026-11-27"], next_week_planned=False,
                    shoes=[{"gear_id": "x y", "name": "X", "distance_m": 9e5, "threshold_m": 7e5, "alert": True}])
        first = self.brief(**over)
        later = self.brief(now=NOW + timedelta(hours=3), **over)
        self.assertEqual([a["key"] for a in first["alerts"]], [a["key"] for a in later["alerts"]])
        self.assertEqual([t["id"] for t in first["tasks"]], [t["id"] for t in later["tasks"]])

    def test_english_workspace(self):
        doc = self.brief(language="en", feedback_missing=["2026-11-27"])
        self.assertEqual(doc["service"]["name"], "Running coach")
        self.assertTrue(doc["headline"].startswith("Today: Trail run endurance 1 h 10"))
        self.assertEqual(doc["tasks"][0]["title"], "Log how the 11/27 session felt (/log)")

    def test_no_links_without_a_usable_base(self):
        for base in (None, "http://coach.example.org/", "https://coach.example.org/a b/", "javascript:x"):
            with self.subTest(base):
                doc = self.brief(base=base, feedback_missing=["2026-11-27"])
                self.assertEqual(doc["links"], [])
                self.assertNotIn("link", doc["tasks"][0])

    def test_one_line_and_stable_key(self):
        self.assertEqual(AB.one_line("a\nb​‮c\td  e", 50), "a bc d e")
        self.assertEqual(AB.one_line("x" * 30, 10), "x" * 9 + "…")
        self.assertEqual(AB.stable_key("ok-id_1.2"), "ok-id_1.2")
        self.assertEqual(AB.stable_key("pas ok"), AB.stable_key("pas ok"))
        self.assertRegex(AB.stable_key("pas ok"), r"^h[0-9a-f]{12}$")

    def test_documented_example_is_what_the_producer_writes(self):
        """L'exemple de docs/dashboard/horae.md est la sortie réelle du producteur."""
        page = (REPO / "docs/dashboard/horae.md").read_text(encoding="utf-8")
        documented = json.loads(re.search(r"```json\n(.*?)\n```", page, re.S).group(1))
        doc = self.brief(feedback_missing=["2026-11-26"],
                         race={"name": "Trail des Collines", "date": "2026-12-06", "has_plan": True},
                         shoes=[{"gear_id": "speedgoat", "name": "Hoka Speedgoat 5", "distance_m": 712000,
                                 "threshold_m": 700000, "alert": True}])
        self.assertEqual(documented, doc)

    def test_error_brief_is_valid(self):
        doc = AB.error_brief(NOW, "fr")
        self.assertEqual(contract_errors(doc), [])
        self.assertEqual(doc["status"]["state"], "error")


# ---------------------------------------------------------------------------
# Faits lus dans l'index (workspace écrit à la main)
# ---------------------------------------------------------------------------

def arc(data: dict, title: str = "Titre", text: str = "Texte.") -> str:
    return f"# {title}\n\n```arc\n{json.dumps(data, ensure_ascii=False)}\n```\n\n{text}\n"


SECRET_TITLE = "Footing doux (douleur genou gauche, kiné jeudi)"
SECRET_REASON = "Douleur au genou signalée hier soir"
SECRET_NOTE = "Note privée : rendez-vous médecin"


class Workspace(unittest.TestCase):
    TODAY = "2026-09-25"           # un vendredi

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="arc-brief-"))
        self.ws = self.tmp / "ws"
        for d in ("activities", "medical", "nutrition", "planning", "rapports", "logs", "config"):
            (self.ws / d).mkdir(parents=True)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write(self, rel: str, text: str) -> None:
        (self.ws / rel).write_text(text, encoding="utf-8")

    def populate(self) -> None:
        today = date.fromisoformat(self.TODAY)
        self.write("config/workspace.user.toml", '[sync]\nmode = "schedule"\ntimes = ["07:15"]\n')
        self.write("planning/Runner_Profile.md",
                   "# Profil\n\n## Matériel & lieux\n\n### Chaussures\n\n"
                   "- Hoka Speedgoat 5 — alerte 20 km — id: speedgoat (par défaut)\n")
        monday = today - timedelta(days=today.weekday())
        self.write(f"planning/Semaine_{monday.isoformat()}.md", arc({
            "arc": 1, "kind": "week", "week_start": monday.isoformat(), "location": "X", "phase": "Base",
            "sessions": [{"date": self.TODAY, "sport": "trail", "title": SECRET_TITLE, "intensity": "endurance",
                          "planned_duration_s": 3600, "planned_distance_m": 10000}]}))
        self.write(f"medical/{self.TODAY}_bilan.md", arc({
            "arc": 1, "kind": "health", "date": self.TODAY, "morning_check": "full", "verdict": "red",
            "verdict_reason": SECRET_REASON, "readiness_score": 25, "resting_hr_bpm": 50}, text=SECRET_NOTE))
        yesterday = (today - timedelta(days=1)).isoformat()
        self.write(f"activities/{yesterday}_trail.md", arc({
            "arc": 1, "kind": "activity", "date": yesterday, "sport": "trail", "duration_s": 3600,
            "distance_m": 25000, "name": SECRET_TITLE}))
        race_day = (today + timedelta(days=10)).isoformat()
        self.write("planning/active_objective.md",
                   "# Objectif\n\n| Champ | Valeur |\n|:--|:--|\n| **Course** | Trail des Collines |\n"
                   f"| **Date** | {race_day} |\n| **Lieu course** | Quelque part |\n")
        # Synchronisation : dernier run réussi il y a 3 jours, puis des échecs.
        ok_day, ko_day = today - timedelta(days=3), today - timedelta(days=2)
        self.write(f"logs/sync-{ok_day.isoformat()}.log",
                   f"===== {ok_day.isoformat()} 07:15:02 — runner=claude lookback=2 trigger=morning =====\n"
                   f"===== {ok_day.isoformat()} 07:16:02 — fin code=0 durée=60s =====\n")
        self.write(f"logs/sync-{ko_day.isoformat()}.log",
                   f"===== {ko_day.isoformat()} 07:15:02 — runner=claude lookback=2 trigger=morning =====\n"
                   f"PROVIDER-ERREUR : {SECRET_NOTE}\n"
                   f"===== {ko_day.isoformat()} 07:15:09 — fin code=1 durée=7s =====\n")

    def store(self) -> "S.Store":
        return S.Store(self.ws, memory=True, today=self.TODAY)


class TestBriefFacts(Workspace):
    def test_facts_are_aggregates_and_brief_is_valid(self):
        self.populate()
        store = self.store()
        found = S.brief_facts(store)
        self.assertEqual(found["sessions_today"], [{"sport": "trail", "intensity": "endurance",
                                                    "planned_duration_s": 3600.0, "planned_distance_m": 10000.0,
                                                    "planned_elevation_m": None, "status": None}])
        self.assertEqual(found["health_today"]["verdict"], "red")
        self.assertEqual(found["feedback_missing"], ["2026-09-24"])
        self.assertFalse(found["next_week_planned"])
        self.assertEqual(found["race"], {"name": "Trail des Collines", "date": "2026-10-05", "has_plan": False})
        self.assertEqual([s["gear_id"] for s in found["shoes"]], ["speedgoat"])
        self.assertEqual(found["sync"]["last_ok_run_at"], "2026-09-22T07:15:02")
        doc = AB.build_brief(found, datetime.now().astimezone(), BASE)
        self.assertEqual(contract_errors(doc), [], json.dumps(doc, ensure_ascii=False, indent=1))
        self.assertEqual([a["key"] for a in doc["alerts"] if a["severity"] == "crit"], ["sync.failing"])
        self.assertIn("readiness.low", [a["key"] for a in doc["alerts"]])
        self.assertIn("shoe.speedgoat.retire", [a["key"] for a in doc["alerts"]])
        self.assertEqual({t["id"] for t in doc["tasks"]},
                         {"feedback.2026-09-24", "plan.week.2026-09-28", "race.plan.2026-10-05"})
        text = json.dumps([found, doc], ensure_ascii=False)
        for secret in (SECRET_TITLE, SECRET_REASON, SECRET_NOTE, "genou", "PROVIDER-ERREUR", "logs/"):
            self.assertNotIn(secret, text)

    def test_empty_workspace(self):
        doc = AB.build_brief(S.brief_facts(self.store()), datetime.now().astimezone(), None)
        self.assertEqual(contract_errors(doc), [])
        self.assertEqual(doc["status"]["state"], "degraded")         # aucune synchronisation jamais lancée
        self.assertEqual(doc["links"], [])


# ---------------------------------------------------------------------------
# Jeton et réglages
# ---------------------------------------------------------------------------

class TestToken(unittest.TestCase):
    def test_file_wins_and_is_trimmed(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "tok"
            path.write_text(TOKEN + "\n", encoding="utf-8")
            self.assertEqual(AB.load_token({"HORAE_BRIEF_TOKEN_FILE": str(path), "HORAE_BRIEF_TOKEN": "B" * 40}), TOKEN)

    def test_env_and_absent(self):
        self.assertEqual(AB.load_token({"HORAE_BRIEF_TOKEN": TOKEN}), TOKEN)
        self.assertIsNone(AB.load_token({}))
        self.assertIsNone(AB.load_token({"HORAE_BRIEF_TOKEN": "  "}))

    def test_weak_or_unreadable_token_disables_without_leaking(self):
        warnings = []
        for env in ({"HORAE_BRIEF_TOKEN": "short-secret"}, {"HORAE_BRIEF_TOKEN": "a" * 40 + " b"},
                    {"HORAE_BRIEF_TOKEN_FILE": "/nonexistent/horae-token"}):
            self.assertIsNone(AB.load_token(env, warn=warnings.append))
        self.assertEqual(len(warnings), 3)
        self.assertFalse(any("short-secret" in w or "aaaa" in w for w in warnings))

    def test_token_ok(self):
        self.assertTrue(AB.token_ok(f"Bearer {TOKEN}", TOKEN))
        self.assertTrue(AB.token_ok(f"bearer  {TOKEN} ", TOKEN))
        for header in (None, "", TOKEN, f"Basic {TOKEN}", f"Bearer {TOKEN}x", "Bearer ", f"Bearer {TOKEN[:-1]}"):
            self.assertFalse(AB.token_ok(header, TOKEN), header)
        self.assertFalse(AB.token_ok(f"Bearer {TOKEN}", ""))

    def test_brief_settings(self):
        env = {"HORAE_BRIEF_TOKEN": TOKEN}
        self.assertEqual(S.brief_settings(["coach.example.org"], False, env), (TOKEN, "https://coach.example.org/"))
        self.assertEqual(S.brief_settings([], False, env), (TOKEN, None))
        self.assertEqual(S.brief_settings(["x.org"], False, {**env, "HORAE_BRIEF_BASE_URL": "https://y.org/app"}),
                         (TOKEN, "https://y.org/app/"))
        self.assertEqual(S.brief_settings(["coach.example.org"], False, {}), (None, None))
        self.assertEqual(S.brief_settings(["coach.example.org"], True, env), (None, None))   # mode famille


# ---------------------------------------------------------------------------
# HTTP : POST /mcp sur le vrai serveur, en processus
# ---------------------------------------------------------------------------

class McpServer(Workspace):
    HOST = "coach.example.org"

    def setUp(self):
        super().setUp()
        self.populate()
        self.saved = {k: getattr(S.Handler, k) for k in ("store", "allowed_hosts", "brief_token", "brief_base_url",
                                                          "family", "chat_port")}
        S.Handler.store = self.store()
        S.Handler.family = None
        S.Handler.chat_port = None
        S.Handler.brief_token = TOKEN
        S.Handler.brief_base_url = "https://coach.example.org/"
        self.httpd = S.bind(0)
        self.port = self.httpd.server_address[1]
        S.Handler.allowed_hosts = S.host_allowlist(self.port, [self.HOST])
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        for k, v in self.saved.items():
            setattr(S.Handler, k, v)
        super().tearDown()

    def request(self, method="POST", body=None, token=TOKEN, headers=None, path="/mcp"):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
        h = {"Host": self.HOST, "Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
        if token is not None:
            h["Authorization"] = f"Bearer {token}"
        h.update(headers or {})
        h = {k: v for k, v in h.items() if v is not None}
        data = body if isinstance(body, bytes) else (json.dumps(body).encode() if body is not None else None)
        conn.request(method, path, body=data, headers=h)
        resp = conn.getresponse()
        raw = resp.read()
        conn.close()
        return resp.status, dict(resp.getheaders()), raw

    def rpc(self, method, params=None, req_id=1, **kw):
        payload = {"jsonrpc": "2.0", "id": req_id, "method": method}
        if params is not None:
            payload["params"] = params
        status, headers, raw = self.request(body=payload, **kw)
        return status, headers, json.loads(raw) if raw else None


class TestMcpHttp(McpServer):
    def test_auth_required(self):
        for token in (None, "wrong-" + "x" * 40, TOKEN + "x"):
            with self.subTest(token=token and token[:6]):
                status, headers, raw = self.request(body={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
                                                    token=token)
                self.assertEqual(status, 401)
                self.assertEqual(headers.get("WWW-Authenticate"), 'Bearer realm="mcp"')
                self.assertNotIn(b"brief", raw)
        status, _, _ = self.request(body={}, token=None, headers={"Authorization": f"Basic {TOKEN}"})
        self.assertEqual(status, 401)

    def test_disabled_without_token(self):
        S.Handler.brief_token = None
        status, _, _ = self.request(body={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        self.assertEqual(status, 404)
        self.assertEqual(self.request(method="GET", body=None)[0], 404)

    def test_disabled_in_family_mode(self):
        S.Handler.family = object()
        self.assertEqual(self.request(body={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})[0], 404)

    def test_only_post(self):
        for method in ("GET", "DELETE", "PUT"):
            with self.subTest(method):
                status, headers, _ = self.request(method=method, body=None)
                self.assertEqual(status, 405)
                self.assertEqual(headers.get("Allow"), "POST")

    def test_host_origin_size_and_type(self):
        self.assertEqual(self.request(body={}, headers={"Host": "evil.example"})[0], 403)
        self.assertEqual(self.request(body={}, headers={"Origin": "https://evil.example"})[0], 403)
        ok = self.request(body={"jsonrpc": "2.0", "id": 1, "method": "ping"},
                          headers={"Origin": f"https://{self.HOST}"})
        self.assertEqual(ok[0], 200)
        self.assertEqual(self.request(body=b"x" * (AB.MCP_BODY_MAX + 1))[0], 413)
        self.assertEqual(self.request(body=b"{}", headers={"Content-Type": "text/plain"})[0], 415)
        self.assertEqual(self.request(body=b"{not json")[0], 400)
        self.assertEqual(self.request(body=[{"jsonrpc": "2.0", "id": 1, "method": "ping"}])[0], 400)

    def test_handshake_and_tool_list(self):
        status, headers, out = self.rpc("server/discover")
        self.assertEqual(out["error"]["code"], -32601)          # sonde 2026-07-28 : le client retombe sur initialize
        status, headers, out = self.rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                                       "clientInfo": {"name": "t", "version": "1"}})
        self.assertEqual(status, 200)
        self.assertEqual(out["result"]["protocolVersion"], "2025-06-18")
        self.assertNotIn("Mcp-Session-Id", headers)
        _, _, out = self.rpc("initialize", {"protocolVersion": "2099-01-01"})
        self.assertEqual(out["result"]["protocolVersion"], "2025-11-25")
        status, _, raw = self.request(body={"jsonrpc": "2.0", "method": "notifications/initialized"})
        self.assertEqual((status, raw), (202, b""))
        _, _, out = self.rpc("tools/list")
        self.assertEqual([t["name"] for t in out["result"]["tools"]], ["brief"])
        self.assertTrue(out["result"]["tools"][0]["annotations"]["readOnlyHint"])
        _, _, out = self.rpc("resources/list")
        self.assertEqual(out["error"]["code"], -32601)

    def test_brief_call_is_schema_valid_bounded_and_aggregated(self):
        status, headers, raw = self.request(
            body={"jsonrpc": "2.0", "id": 7, "method": "tools/call",
                  "params": {"name": "brief", "arguments": {"schema_version": 1}}},
            headers={"Accept-Encoding": "gzip"})
        self.assertEqual(status, 200)
        self.assertNotIn("Content-Encoding", headers)
        self.assertEqual(headers["Content-Type"], "application/json")
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertLess(len(raw), 64 * 1024)
        out = json.loads(raw)
        result = out["result"]
        self.assertFalse(result["isError"])
        doc = result["structuredContent"]
        self.assertEqual(json.loads(result["content"][0]["text"]), doc)
        self.assertEqual(contract_errors(doc), [], json.dumps(doc, ensure_ascii=False, indent=1))
        self.assertEqual([a["key"] for a in doc["alerts"] if a["severity"] == "crit"], ["sync.failing"])
        self.assertTrue(all(link["url"].startswith("https://coach.example.org/") for link in doc["links"]))
        text = raw.decode("utf-8")
        for secret in (SECRET_TITLE, SECRET_REASON, SECRET_NOTE, "genou", '"lat"', '"lon"', str(self.ws)):
            self.assertNotIn(secret, text)

    def test_brief_call_errors(self):
        _, _, out = self.rpc("tools/call", {"name": "other", "arguments": {}})
        self.assertEqual(out["error"]["code"], -32602)
        _, _, out = self.rpc("tools/call", {"name": "brief", "arguments": {"schema_version": 0}})
        self.assertTrue(out["result"]["isError"])
        _, _, out = self.rpc("tools/call", {"name": "brief", "arguments": {"x": 1}})
        self.assertEqual(out["error"]["code"], -32602)
        _, _, out = self.rpc("tools/call", {"name": "brief"})                        # argument par défaut
        self.assertFalse(out["result"]["isError"])

    def test_producer_failure_is_a_bare_tool_error(self):
        status, out = AB.handle_body(json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                                 "params": {"name": "brief"}}).encode(),
                                     lambda: (_ for _ in ()).throw(RuntimeError("/secret/path")))
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(out)["result"]["content"][0]["text"], "Brief unavailable.")

    def test_read_only(self):
        before = sorted((p.relative_to(self.ws).as_posix(), p.stat().st_mtime_ns) for p in self.ws.rglob("*"))
        self.rpc("tools/call", {"name": "brief", "arguments": {"schema_version": 1}})
        after = sorted((p.relative_to(self.ws).as_posix(), p.stat().st_mtime_ns) for p in self.ws.rglob("*"))
        self.assertEqual(before, after)
        self.assertEqual(self.request(path="/api/summary", body={})[0], 405)      # le reste de l'API reste en lecture

    def test_other_routes_unchanged(self):
        status, _, raw = self.request(method="GET", path="/healthz", token=None)
        self.assertEqual(status, 200)
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
        conn.request("GET", "/api/version", headers={"Host": self.HOST, "Accept-Encoding": "gzip"})
        self.assertEqual(conn.getresponse().status, 200)
        conn.close()


if __name__ == "__main__":
    unittest.main()
