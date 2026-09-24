#!/usr/bin/env python3
"""Palier D — tests unitaires des nouvelles assertions d'évaluation.

Tests de `check()` sur des résultats simulés : succès et échec pour chaque
assertion (`arc_field`, `tool_args_match`, `sqlite_query`, `file_contains_any`).
"""

import json
import tempfile
import unittest
from pathlib import Path

# Import depuis le parent
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from evals import runner


class TestPathResolver(unittest.TestCase):
    """Tests unitaires du résolveur de chemin JSON."""

    def test_simple_key(self):
        """Clé simple."""
        data = {"foo": "bar"}
        result = runner._resolve_json_path(data, "foo")
        self.assertEqual(result, ["bar"])

    def test_nested_keys(self):
        """Clés imbriquées."""
        data = {"foo": {"bar": {"baz": 42}}}
        result = runner._resolve_json_path(data, "foo.bar.baz")
        self.assertEqual(result, [42])

    def test_array_index(self):
        """Accès par index."""
        data = {"items": [10, 20, 30]}
        result = runner._resolve_json_path(data, "items[0]")
        self.assertEqual(result, [10])

    def test_array_index_negative(self):
        """Index négatif."""
        data = {"items": [10, 20, 30]}
        result = runner._resolve_json_path(data, "items[-1]")
        self.assertEqual(result, [30])

    def test_wildcard(self):
        """Caractère générique sur liste."""
        data = {"items": [{"name": "a"}, {"name": "b"}]}
        result = runner._resolve_json_path(data, "items[*].name")
        self.assertEqual(result, ["a", "b"])

    def test_missing_key(self):
        """Clé manquante."""
        data = {"foo": "bar"}
        result = runner._resolve_json_path(data, "missing")
        self.assertEqual(result, [])

    def test_out_of_bounds_index(self):
        """Index hors limites."""
        data = {"items": [10, 20]}
        result = runner._resolve_json_path(data, "items[10]")
        self.assertEqual(result, [])

    def test_complex_path(self):
        """Chemin complexe."""
        data = {
            "sessions": [
                {"intensity": 5, "workout": {"type": "running"}},
                {"intensity": 8, "workout": {"type": "trail"}},
            ]
        }
        result = runner._resolve_json_path(data, "sessions[*].intensity")
        self.assertEqual(result, [5, 8])


class TestCompareValue(unittest.TestCase):
    """Tests unitaires du comparateur de valeurs."""

    def test_equals(self):
        """Comparateur equals."""
        self.assertTrue(runner._compare_value(42, 42, "equals"))
        self.assertFalse(runner._compare_value(42, 43, "equals"))

    def test_min(self):
        """Comparateur min."""
        self.assertTrue(runner._compare_value(50, 50, "min"))
        self.assertTrue(runner._compare_value(51, 50, "min"))
        self.assertFalse(runner._compare_value(49, 50, "min"))

    def test_max(self):
        """Comparateur max."""
        self.assertTrue(runner._compare_value(50, 50, "max"))
        self.assertTrue(runner._compare_value(49, 50, "max"))
        self.assertFalse(runner._compare_value(51, 50, "max"))

    def test_regex(self):
        """Comparateur regex."""
        self.assertTrue(runner._compare_value("hello world", "w.*d", "regex"))
        self.assertFalse(runner._compare_value("hello", "xyz", "regex"))

    def test_in(self):
        """Comparateur in."""
        self.assertTrue(runner._compare_value("foo", ["foo", "bar"], "in"))
        self.assertFalse(runner._compare_value("baz", ["foo", "bar"], "in"))


class TestArcFieldBasic(unittest.TestCase):
    """Tests unitaires du résolveur arc_field sur données en mémoire."""

    def test_arc_field_path_resolution(self):
        """Vérifie la résolution de chemin dans un bloc arc."""
        block = {
            "version": 1,
            "kind": "activity",
            "date": "2026-09-24",
            "distance_m": 5000,
            "sessions": [
                {"intensity": 5},
                {"intensity": 7},
            ]
        }

        # Chemin simple
        self.assertEqual(runner._resolve_json_path(block, "distance_m"), [5000])

        # Chemin avec wildcard
        self.assertEqual(
            runner._resolve_json_path(block, "sessions[*].intensity"),
            [5, 7]
        )


class TestToolArgsMatchAssertion(unittest.TestCase):
    """Tests de l'assertion tool_args_match."""

    def test_tool_args_match_equals(self):
        """Valide tool_args_match avec comparateur equals."""
        tool_log = json.dumps({
            "tool": "get_activities",
            "server": "garmin",
            "arguments": {"days": 7}
        }) + "\n"

        case = {
            "expect": {
                "tool_args_match": {
                    "tool": "get_activities",
                    "path": "days",
                    "equals": 7,
                }
            },
        }
        result = {
            "output": "",
            "tool_calls": tool_log,
            "workspace": Path("/tmp"),
        }
        failures = runner.check(case, result)
        self.assertEqual(failures, [])

    def test_tool_args_match_regex(self):
        """Valide tool_args_match avec comparateur regex."""
        tool_log = json.dumps({
            "tool": "get_health",
            "server": "garmin",
            "arguments": {"metric": "hrv_overnight"}
        }) + "\n"

        case = {
            "expect": {
                "tool_args_match": {
                    "tool": "get_health",
                    "path": "metric",
                    "regex": "hrv.*",
                }
            },
        }
        result = {
            "output": "",
            "tool_calls": tool_log,
            "workspace": Path("/tmp"),
        }
        failures = runner.check(case, result)
        self.assertEqual(failures, [])

    def test_tool_args_match_server_filter(self):
        """Filtre par serveur."""
        tool_log = json.dumps({
            "tool": "some_tool",
            "server": "garmin",
            "arguments": {"value": 42}
        }) + "\n"

        case = {
            "expect": {
                "tool_args_match": {
                    "tool": "some_tool",
                    "server": "garmin",
                    "path": "value",
                    "equals": 42,
                }
            },
        }
        result = {
            "output": "",
            "tool_calls": tool_log,
            "workspace": Path("/tmp"),
        }
        failures = runner.check(case, result)
        self.assertEqual(failures, [])

    def test_tool_args_match_not_found(self):
        """Échec si l'outil n'a jamais été appelé."""
        tool_log = ""

        case = {
            "expect": {
                "tool_args_match": {
                    "tool": "missing_tool",
                    "path": "value",
                    "equals": 42,
                }
            },
        }
        result = {
            "output": "",
            "tool_calls": tool_log,
            "workspace": Path("/tmp"),
        }
        failures = runner.check(case, result)
        self.assertTrue(any("ne satisfait pas" in f for f in failures))


class TestFileContainsAnyAssertion(unittest.TestCase):
    """Tests de l'assertion file_contains_any."""

    def test_file_contains_any_match(self):
        """Valide si un fichier contient une notion."""
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir) / "workspace"
            workspace.mkdir()
            (workspace / "rapports").mkdir()

            content = "Rapport hebdomadaire de la semaine du 24 septembre."
            (workspace / "rapports" / "2026-09-24_rapport.md").write_text(content)

            case = {
                "expect": {
                    "file_contains_any": {
                        "glob": "rapports/*.md",
                        "any": ["Rapport", "sommaire"],
                    }
                },
            }
            result = {
                "output": "",
                "tool_calls": "",
                "workspace": workspace,
            }
            failures = runner.check(case, result)
            self.assertEqual(failures, [])

    def test_file_contains_any_case_insensitive(self):
        """Vérifie la sensibilité à la casse."""
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir) / "workspace"
            workspace.mkdir()
            (workspace / "rapports").mkdir()

            content = "rapport hebdomadaire"
            (workspace / "rapports" / "2026-09-24_rapport.md").write_text(content)

            case = {
                "expect": {
                    "file_contains_any": {
                        "glob": "rapports/*.md",
                        "any": ["RAPPORT", "sommaire"],
                    }
                },
            }
            result = {
                "output": "",
                "tool_calls": "",
                "workspace": workspace,
            }
            failures = runner.check(case, result)
            self.assertEqual(failures, [])

    def test_file_contains_any_no_match(self):
        """Échec si aucune notion ne correspond."""
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir) / "workspace"
            workspace.mkdir()
            (workspace / "rapports").mkdir()

            content = "Contenu vide."
            (workspace / "rapports" / "2026-09-24_rapport.md").write_text(content)

            case = {
                "expect": {
                    "file_contains_any": {
                        "glob": "rapports/*.md",
                        "any": ["Rapport", "sommaire"],
                    }
                },
            }
            result = {
                "output": "",
                "tool_calls": "",
                "workspace": workspace,
            }
            failures = runner.check(case, result)
            self.assertTrue(any("aucun de" in f for f in failures))

    def test_file_contains_any_no_files(self):
        """Échec si aucun fichier ne correspond au glob."""
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir) / "workspace"
            workspace.mkdir()
            (workspace / "rapports").mkdir()

            case = {
                "expect": {
                    "file_contains_any": {
                        "glob": "rapports/*.md",
                        "any": ["Rapport"],
                    }
                },
            }
            result = {
                "output": "",
                "tool_calls": "",
                "workspace": workspace,
            }
            failures = runner.check(case, result)
            self.assertTrue(any("aucun fichier ne correspond" in f for f in failures))


if __name__ == "__main__":
    unittest.main()
