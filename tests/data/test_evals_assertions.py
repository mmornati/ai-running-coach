#!/usr/bin/env python3
"""Palier D — tests unitaires des assertions d'éval `arc_field`, `tool_args_match`,
`sqlite_query` et `file_contains_any` (#27).

Exercice systématique : chaque comparateur, dans son sens PASS et son sens FAIL,
via `check()` (pas seulement les helpers internes) — c'est `check()` que
`test_evals.py` (palier C) appelle réellement. Couvre aussi les cas limites listés
par la revue de la PR #72 : sémantique TOUT (pas AU MOINS UN), chemins malformés,
comparateurs numériques appliqués à des valeurs non numériques, `sqlite_query`
sans ligne / avec NULL / non-lecture / `WITH … SELECT`, et l'absence de fichier
temporaire laissé derrière `sqlite_query`.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from tests.evals import runner  # noqa: E402


def _arc_activity_file(path: Path, **fields) -> None:
    block = {"arc": 1, "kind": "activity", "date": "2026-09-21", "sport": "running", "duration_s": 1800}
    block.update(fields)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("# Séance\n\n```arc\n" + json.dumps(block, ensure_ascii=False) + "\n```\n", encoding="utf-8")


def _arc_week_file(path: Path, sessions: list) -> None:
    block = {
        "arc": 1, "kind": "week", "week_start": "2026-09-21", "location": "Chamonix",
        "sessions": sessions,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("# Semaine\n\n```arc\n" + json.dumps(block, ensure_ascii=False) + "\n```\n", encoding="utf-8")


def _result(workspace: Path, tool_calls: str = "", output: str = "") -> dict:
    return {"output": output, "tool_calls": tool_calls, "workspace": workspace}


def _tool_log(*calls) -> str:
    return "".join(json.dumps(c, ensure_ascii=False) + "\n" for c in calls)


class TestJsonPathParsing(unittest.TestCase):
    """`_parse_json_path` : segments valides et rejet explicite du malformé (#27)."""

    def test_simple_key(self):
        self.assertEqual(runner._parse_json_path("foo"), [("key", "foo")])

    def test_nested_keys(self):
        self.assertEqual(
            runner._parse_json_path("foo.bar.baz"),
            [("key", "foo"), ("key", "bar"), ("key", "baz")],
        )

    def test_index_and_wildcard(self):
        self.assertEqual(
            runner._parse_json_path("items[0].x"),
            [("key", "items"), ("index", 0), ("key", "x")],
        )
        self.assertEqual(
            runner._parse_json_path("items[*].x"),
            [("key", "items"), ("wildcard",), ("key", "x")],
        )

    def test_negative_index(self):
        self.assertEqual(runner._parse_json_path("items[-1]"), [("key", "items"), ("index", -1)])

    def test_empty_path_is_rejected(self):
        with self.assertRaises(ValueError):
            runner._parse_json_path("")

    def test_non_integer_index_is_rejected(self):
        with self.assertRaises(ValueError):
            runner._parse_json_path("items[abc].x")

    def test_unclosed_bracket_is_rejected(self):
        with self.assertRaises(ValueError):
            runner._parse_json_path("items[0")

    def test_trailing_dot_is_rejected(self):
        with self.assertRaises(ValueError):
            runner._parse_json_path("a.b.")

    def test_missing_dot_after_bracket_is_rejected(self):
        with self.assertRaises(ValueError):
            runner._parse_json_path("items[*]x")


class TestJsonPathResolution(unittest.TestCase):
    """`_resolve_json_path` : rend des `(chemin_concret, valeur)`."""

    def test_simple_key(self):
        self.assertEqual(runner._resolve_json_path({"foo": "bar"}, "foo"), [("foo", "bar")])

    def test_nested_keys(self):
        data = {"foo": {"bar": {"baz": 42}}}
        self.assertEqual(runner._resolve_json_path(data, "foo.bar.baz"), [("foo.bar.baz", 42)])

    def test_wildcard_gives_concrete_indices(self):
        data = {"items": [{"name": "a"}, {"name": "b"}]}
        self.assertEqual(
            runner._resolve_json_path(data, "items[*].name"),
            [("items[0].name", "a"), ("items[1].name", "b")],
        )

    def test_missing_key_resolves_to_nothing(self):
        self.assertEqual(runner._resolve_json_path({"foo": "bar"}, "missing"), [])

    def test_out_of_bounds_index_resolves_to_nothing(self):
        self.assertEqual(runner._resolve_json_path({"items": [10, 20]}, "items[10]"), [])

    def test_negative_index_resolves_real_position(self):
        data = {"items": [10, 20, 30]}
        self.assertEqual(runner._resolve_json_path(data, "items[-1]"), [("items[2]", 30)])


class TestCompareValue(unittest.TestCase):
    """`_compare_value` : chaque comparateur, PASS et FAIL, plus les rejets explicites."""

    def test_equals(self):
        self.assertTrue(runner._compare_value(42, 42, "equals"))
        self.assertFalse(runner._compare_value(42, 43, "equals"))

    def test_equals_bool_is_not_numeric_equal(self):
        """`True == 1` en Python : on ne veut PAS que `equals = 1` soit satisfait par `True`."""
        self.assertFalse(runner._compare_value(True, 1, "equals"))
        self.assertTrue(runner._compare_value(True, True, "equals"))

    def test_min_max(self):
        self.assertTrue(runner._compare_value(50, 50, "min"))
        self.assertTrue(runner._compare_value(51, 50, "min"))
        self.assertFalse(runner._compare_value(49, 50, "min"))
        self.assertTrue(runner._compare_value(50, 50, "max"))
        self.assertFalse(runner._compare_value(51, 50, "max"))

    def test_min_max_reject_non_numeric_found(self):
        with self.assertRaises(ValueError):
            runner._compare_value("vo2max", 5, "min")

    def test_min_max_reject_non_numeric_expected(self):
        """TOML `min = "3"` (chaîne) doit être un échec lisible, pas un crash silencieux."""
        with self.assertRaises(ValueError):
            runner._compare_value(5, "3", "min")

    def test_min_max_reject_bool(self):
        with self.assertRaises(ValueError):
            runner._compare_value(True, 0, "min")

    def test_regex(self):
        self.assertTrue(runner._compare_value("hello world", "w.*d", "regex"))
        self.assertFalse(runner._compare_value("hello", "xyz", "regex"))

    def test_regex_invalid_pattern_raises(self):
        with self.assertRaises(ValueError):
            runner._compare_value("hello", "(", "regex")

    def test_in(self):
        self.assertTrue(runner._compare_value("foo", ["foo", "bar"], "in"))
        self.assertFalse(runner._compare_value("baz", ["foo", "bar"], "in"))

    def test_unknown_comparator_raises(self):
        with self.assertRaises(ValueError):
            runner._compare_value(1, 1, "frobnicate")


class TestArcFieldViaCheck(unittest.TestCase):
    """`arc_field` via `check()` — sémantique TOUT, pas AU MOINS UN (#27, revue PR #72)."""

    def test_pass_single_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp) / "workspace"
            _arc_activity_file(ws / "activities" / "2026-09-21_running.md", distance_m=10000)
            case = {"id": "t", "fixture": "base-week", "expect": {
                "arc_field": [{"glob": "activities/*.md", "path": "distance_m", "min": 5000}]
            }}
            self.assertEqual(runner.check(case, _result(ws)), [])

    def test_fail_min_across_multiple_files_all_must_pass(self):
        """Repro revue PR #72 : deux activités (10000 m et 3000 m) vs `min = 5000` —
        l'ancienne implémentation passait dès qu'UNE seule satisfaisait."""
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp) / "workspace"
            _arc_activity_file(ws / "activities" / "2026-09-21_running.md", distance_m=10000)
            _arc_activity_file(ws / "activities" / "2026-09-22_running.md", distance_m=3000)
            case = {"id": "t", "fixture": "base-week", "expect": {
                "arc_field": [{"glob": "activities/*.md", "path": "distance_m", "min": 5000}]
            }}
            failures = runner.check(case, _result(ws))
            self.assertTrue(any("3000" in f and "5000" in f for f in failures), failures)

    def test_fail_wildcard_all_values_in_one_file_must_pass(self):
        """Repro revue PR #72 : `sessions[*].intensity` = ["endurance", "vo2max"]
        vs `in = ["endurance", "recovery"]` — une seule valeur en dehors doit
        faire échouer, avec l'indice concret dans le message."""
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp) / "workspace"
            _arc_week_file(ws / "planning" / "Semaine_2026-09-21.md", sessions=[
                {"date": "2026-09-21", "sport": "running", "title": "a", "intensity": "endurance"},
                {"date": "2026-09-22", "sport": "running", "title": "b", "intensity": "vo2max"},
            ])
            case = {"id": "t", "fixture": "base-week", "expect": {
                "arc_field": [{
                    "glob": "planning/Semaine_*.md", "path": "sessions[*].intensity",
                    "in": ["endurance", "recovery"],
                }]
            }}
            failures = runner.check(case, _result(ws))
            self.assertTrue(any("sessions[1].intensity" in f and "vo2max" in f for f in failures), failures)

    def test_fail_wildcard_max_repro(self):
        """Repro revue PR #72 : `items[*].x` = [1, 9] vs `max = 5`."""
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp) / "workspace"
            path = ws / "planning" / "Semaine_2026-09-21.md"
            block = {
                "arc": 1, "kind": "week", "week_start": "2026-09-21", "location": "Chamonix",
                "sessions": [{"date": "2026-09-21", "sport": "running", "title": "a"}],
                "items": [{"x": 1}, {"x": 9}],
            }
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("# Semaine\n\n```arc\n" + json.dumps(block, ensure_ascii=False) + "\n```\n", encoding="utf-8")
            case = {"id": "t", "fixture": "base-week", "expect": {
                "arc_field": [{"glob": "planning/*.md", "path": "items[*].x", "max": 5}]
            }}
            failures = runner.check(case, _result(ws))
            self.assertTrue(any("items[1].x" in f and "9" in f for f in failures), failures)

    def test_missing_glob_or_path_is_a_failure_not_silent(self):
        case = {"id": "t", "fixture": "base-week", "expect": {"arc_field": [{"glob": "activities/*.md"}]}}
        with tempfile.TemporaryDirectory() as tmp:
            failures = runner.check(case, _result(Path(tmp)))
            self.assertTrue(failures)

    def test_no_file_written_is_a_failure(self):
        case = {"id": "t", "fixture": "base-week", "expect": {
            "arc_field": [{"glob": "activities/*.md", "path": "distance_m", "min": 1}]
        }}
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp) / "workspace"
            ws.mkdir()
            failures = runner.check(case, _result(ws))
            self.assertTrue(any("aucun fichier" in f for f in failures))

    def test_path_not_found_is_its_own_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp) / "workspace"
            _arc_activity_file(ws / "activities" / "2026-09-21_running.md")
            case = {"id": "t", "fixture": "base-week", "expect": {
                "arc_field": [{"glob": "activities/*.md", "path": "missing_field", "min": 1}]
            }}
            failures = runner.check(case, _result(ws))
            self.assertTrue(any("chemin introuvable" in f for f in failures), failures)

    def test_malformed_path_is_a_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp) / "workspace"
            _arc_activity_file(ws / "activities" / "2026-09-21_running.md")
            case = {"id": "t", "fixture": "base-week", "expect": {
                "arc_field": [{"glob": "activities/*.md", "path": "items[abc].x", "min": 1}]
            }}
            failures = runner.check(case, _result(ws))
            self.assertTrue(any("chemin invalide" in f for f in failures), failures)

    def test_invalid_arc_block_is_reported_not_swallowed(self):
        """#27, revue PR #72 : `_load_arc_block` doit rendre le motif de non-conformité,
        pas juste `None`."""
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp) / "workspace"
            (ws / "activities").mkdir(parents=True)
            (ws / "activities" / "2026-09-21_running.md").write_text(
                "# Séance\n\n```arc\n{not valid json\n```\n", encoding="utf-8"
            )
            case = {"id": "t", "fixture": "base-week", "expect": {
                "arc_field": [{"glob": "activities/*.md", "path": "distance_m", "min": 1}]
            }}
            failures = runner.check(case, _result(ws))
            self.assertTrue(any("JSON invalide" in f for f in failures), failures)


class TestToolArgsMatchViaCheck(unittest.TestCase):
    def test_pass_equals(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            tool_log = _tool_log({"tool": "get_scheduled_workouts", "server": "garmin",
                                   "arguments": {"start_date": "2026-09-21"}})
            case = {"id": "t", "expect": {"tool_args_match": [{
                "tool": "get_scheduled_workouts", "path": "start_date", "equals": "2026-09-21",
            }]}}
            self.assertEqual(runner.check(case, _result(ws, tool_calls=tool_log)), [])

    def test_pass_regex(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            tool_log = _tool_log({"tool": "get_hrv_data", "server": "garmin", "arguments": {"date": "2026-09-21"}})
            case = {"id": "t", "expect": {"tool_args_match": [{
                "tool": "get_hrv_data", "path": "date", "regex": r"^\d{4}-\d{2}-\d{2}$",
            }]}}
            self.assertEqual(runner.check(case, _result(ws, tool_calls=tool_log)), [])

    def test_wrong_value_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            tool_log = _tool_log({"tool": "get_scheduled_workouts", "server": "garmin",
                                   "arguments": {"start_date": "2026-01-01"}})
            case = {"id": "t", "expect": {"tool_args_match": [{
                "tool": "get_scheduled_workouts", "path": "start_date", "equals": "2026-09-21",
            }]}}
            failures = runner.check(case, _result(ws, tool_calls=tool_log))
            self.assertTrue(failures)

    def test_server_mismatch_is_treated_as_absent(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            tool_log = _tool_log({"tool": "get_activities", "server": "intervals", "arguments": {"x": 1}})
            case = {"id": "t", "expect": {"tool_args_match": [{
                "tool": "get_activities", "server": "garmin", "path": "x", "equals": 1,
            }]}}
            failures = runner.check(case, _result(ws, tool_calls=tool_log))
            self.assertTrue(any("aucun appel" in f for f in failures), failures)

    def test_tool_never_called_has_distinct_message(self):
        with tempfile.TemporaryDirectory() as tmp:
            case = {"id": "t", "expect": {"tool_args_match": [{
                "tool": "missing_tool", "path": "value", "equals": 42,
            }]}}
            failures = runner.check(case, _result(Path(tmp), tool_calls=""))
            self.assertTrue(any("aucun appel à missing_tool" in f for f in failures), failures)

    def test_min_max_on_call_arguments(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            tool_log = _tool_log({"tool": "get_activities_by_date", "server": "garmin",
                                   "arguments": {"days": 7}})
            case = {"id": "t", "expect": {"tool_args_match": [{
                "tool": "get_activities_by_date", "path": "days", "min": 5,
            }]}}
            self.assertEqual(runner.check(case, _result(ws, tool_calls=tool_log)), [])

    def test_wildcard_all_calls_arguments_must_pass(self):
        """Repro généralisée : un appel qui planifie plusieurs séances, une seule
        hors gabarit, doit faire échouer même si les autres sont bonnes."""
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            tool_log = _tool_log({"tool": "schedule_workouts", "server": "garmin", "arguments": {
                "schedules": [{"calendar_date": "2026-09-21"}, {"calendar_date": "2026-10-01"}],
            }})
            case = {"id": "t", "expect": {"tool_args_match": [{
                "tool": "schedule_workouts", "path": "schedules[*].calendar_date", "regex": "^2026-09",
            }]}}
            failures = runner.check(case, _result(ws, tool_calls=tool_log))
            self.assertTrue(failures)

    def test_malformed_path_is_a_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            tool_log = _tool_log({"tool": "get_activities", "server": "garmin", "arguments": {"x": 1}})
            case = {"id": "t", "expect": {"tool_args_match": [{
                "tool": "get_activities", "path": "items[abc]", "equals": 1,
            }]}}
            failures = runner.check(case, _result(Path(tmp), tool_calls=tool_log))
            self.assertTrue(any("chemin invalide" in f for f in failures), failures)


class TestSqliteQueryViaCheck(unittest.TestCase):
    def _workspace_with_activity(self, tmp: Path, distance_m: int = 12000) -> Path:
        ws = tmp / "workspace"
        _arc_activity_file(ws / "activities" / "2026-09-21_running.md", distance_m=distance_m)
        for name in ("activities", "medical", "nutrition", "planning", "rapports", "resources"):
            (ws / name).mkdir(parents=True, exist_ok=True)
        return ws

    def test_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = self._workspace_with_activity(Path(tmp))
            case = {"id": "t", "fixture": "base-week", "expect": {"sqlite_query": [{
                "sql": "SELECT COUNT(*) FROM activity WHERE sport = 'running'", "equals": 1,
            }]}}
            self.assertEqual(runner.check(case, _result(ws)), [])

    def test_fail_wrong_value(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = self._workspace_with_activity(Path(tmp))
            case = {"id": "t", "fixture": "base-week", "expect": {"sqlite_query": [{
                "sql": "SELECT COUNT(*) FROM activity WHERE sport = 'running'", "equals": 5,
            }]}}
            failures = runner.check(case, _result(ws))
            self.assertTrue(failures)

    def test_no_row_is_a_distinct_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = self._workspace_with_activity(Path(tmp))
            case = {"id": "t", "fixture": "base-week", "expect": {"sqlite_query": [{
                "sql": "SELECT distance_m FROM activity WHERE sport = 'swimming'", "equals": 1,
            }]}}
            failures = runner.check(case, _result(ws))
            self.assertTrue(any("aucune ligne" in f for f in failures), failures)

    def test_null_value_is_a_distinct_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = self._workspace_with_activity(Path(tmp))
            case = {"id": "t", "fixture": "base-week", "expect": {"sqlite_query": [{
                "sql": "SELECT elevation_gain_m FROM activity WHERE sport = 'running'", "equals": 1,
            }]}}
            failures = runner.check(case, _result(ws))
            self.assertTrue(any("NULL" in f for f in failures), failures)

    def test_with_select_is_accepted(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = self._workspace_with_activity(Path(tmp))
            case = {"id": "t", "fixture": "base-week", "expect": {"sqlite_query": [{
                "sql": "WITH r AS (SELECT distance_m AS d FROM activity) SELECT MAX(d) FROM r",
                "min": 10000,
            }]}}
            self.assertEqual(runner.check(case, _result(ws)), [])

    def test_leading_comment_is_accepted(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = self._workspace_with_activity(Path(tmp))
            case = {"id": "t", "fixture": "base-week", "expect": {"sqlite_query": [{
                "sql": "-- décompte des sorties\nSELECT COUNT(*) FROM activity", "min": 1,
            }]}}
            self.assertEqual(runner.check(case, _result(ws)), [])

    def test_non_read_statement_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = self._workspace_with_activity(Path(tmp))
            case = {"id": "t", "fixture": "base-week", "expect": {"sqlite_query": [{
                "sql": "DELETE FROM activity", "equals": 0,
            }]}}
            failures = runner.check(case, _result(ws))
            self.assertTrue(failures)
            # la table n'a pas été vidée : le refus est réel, pas cosmétique
            case_count = {"id": "t", "fixture": "base-week", "expect": {"sqlite_query": [{
                "sql": "SELECT COUNT(*) FROM activity", "equals": 1,
            }]}}
            self.assertEqual(runner.check(case_count, _result(ws)), [])

    def test_multi_statement_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = self._workspace_with_activity(Path(tmp))
            case = {"id": "t", "fixture": "base-week", "expect": {"sqlite_query": [{
                "sql": "SELECT 1; DROP TABLE activity", "equals": 1,
            }]}}
            failures = runner.check(case, _result(ws))
            self.assertTrue(failures)

    def test_no_temp_file_left_behind(self):
        """#27, revue PR #72 : plus de `NamedTemporaryFile(delete=False)` qui fuit."""
        with tempfile.TemporaryDirectory() as tmp:
            ws = self._workspace_with_activity(Path(tmp))
            before = set(Path(tempfile.gettempdir()).glob("tmp*.db"))
            case = {"id": "t", "fixture": "base-week", "expect": {"sqlite_query": [{
                "sql": "SELECT COUNT(*) FROM activity", "min": 1,
            }]}}
            runner.check(case, _result(ws))
            after = set(Path(tempfile.gettempdir()).glob("tmp*.db"))
            self.assertEqual(before, after)

    def test_indexes_once_for_several_assertions(self):
        """Deux `sqlite_query` dans le même cas ne doivent réindexer qu'une fois."""
        with tempfile.TemporaryDirectory() as tmp:
            ws = self._workspace_with_activity(Path(tmp))
            calls = []
            sys.path.insert(0, str(REPO / "scripts"))
            import arc_index as I

            original = I.index_workspace

            def spy(*args, **kwargs):
                calls.append(1)
                return original(*args, **kwargs)

            I.index_workspace = spy
            try:
                case = {"id": "t", "fixture": "base-week", "expect": {"sqlite_query": [
                    {"sql": "SELECT COUNT(*) FROM activity", "min": 1},
                    {"sql": "SELECT COUNT(*) FROM activity", "max": 100},
                ]}}
                runner.check(case, _result(ws))
            finally:
                I.index_workspace = original
            self.assertEqual(len(calls), 1)


class TestFileContainsAnyViaCheck(unittest.TestCase):
    def test_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp) / "workspace"
            (ws / "rapports").mkdir(parents=True)
            (ws / "rapports" / "2026-09-24_rapport.md").write_text(
                "Rapport hebdomadaire de la semaine du 24 septembre.", encoding="utf-8"
            )
            case = {"id": "t", "fixture": "base-week", "expect": {
                "file_contains_any": [{"glob": "rapports/*.md", "any": ["Rapport", "sommaire"]}]
            }}
            self.assertEqual(runner.check(case, _result(ws)), [])

    def test_case_insensitive(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp) / "workspace"
            (ws / "rapports").mkdir(parents=True)
            (ws / "rapports" / "2026-09-24_rapport.md").write_text("rapport hebdomadaire", encoding="utf-8")
            case = {"id": "t", "fixture": "base-week", "expect": {
                "file_contains_any": [{"glob": "rapports/*.md", "any": ["RAPPORT"]}]
            }}
            self.assertEqual(runner.check(case, _result(ws)), [])

    def test_no_match_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp) / "workspace"
            (ws / "rapports").mkdir(parents=True)
            (ws / "rapports" / "2026-09-24_rapport.md").write_text("Contenu vide.", encoding="utf-8")
            case = {"id": "t", "fixture": "base-week", "expect": {
                "file_contains_any": [{"glob": "rapports/*.md", "any": ["Rapport"]}]
            }}
            failures = runner.check(case, _result(ws))
            self.assertTrue(any("aucun de" in f for f in failures))

    def test_no_files_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp) / "workspace"
            (ws / "rapports").mkdir(parents=True)
            case = {"id": "t", "fixture": "base-week", "expect": {
                "file_contains_any": [{"glob": "rapports/*.md", "any": ["Rapport"]}]
            }}
            failures = runner.check(case, _result(ws))
            self.assertTrue(any("aucun fichier ne correspond" in f for f in failures))


class TestCheckNeverRaises(unittest.TestCase):
    """#27, revue PR #72 : aucune exception ne doit sortir de `check()`, quel que
    soit le n'importe-quoi passé dans le `.toml` d'un cas."""

    def test_arc_field_bad_types(self):
        with tempfile.TemporaryDirectory() as tmp:
            case = {"id": "t", "fixture": "base-week", "expect": {"arc_field": "not-a-list-of-dicts"}}
            runner.check(case, _result(Path(tmp)))  # ne doit pas lever

    def test_sqlite_query_bad_sql(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp) / "workspace"
            ws.mkdir()
            case = {"id": "t", "fixture": "base-week", "expect": {"sqlite_query": [
                {"sql": "SELECT * FROM table_qui_n_existe_pas", "equals": 1}
            ]}}
            failures = runner.check(case, _result(ws))
            self.assertTrue(failures)

    def test_tool_args_match_non_dict_arguments(self):
        with tempfile.TemporaryDirectory() as tmp:
            tool_log = json.dumps({"tool": "get_activities", "server": "garmin", "arguments": None}) + "\n"
            case = {"id": "t", "expect": {"tool_args_match": [
                {"tool": "get_activities", "path": "x", "equals": 1}
            ]}}
            failures = runner.check(case, _result(Path(tmp), tool_calls=tool_log))
            self.assertTrue(failures)


if __name__ == "__main__":
    unittest.main()
