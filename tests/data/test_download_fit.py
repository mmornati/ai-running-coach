"""Palier D — `skills/fit-download/scripts/download_fit.py` : résolution du workspace
(#42, revue PR #87, blocker 3), copie canonique normalisée, sport-gating de la
cadence, et les marqueurs `.gitignore` (should-fix 4/5). Aucune dépendance à
`garminconnect` ni `fitparse` (CONTRIBUTING.md : stdlib uniquement pour la suite de
tests — ces deux paquets ne sont installés que dans l'environnement `garmin-mcp`,
absent de la CI comme de cet environnement de dev) : seules `_activity_dir_out`,
`_write_canonical_samples`, `_ensure_gitignore` et `_write_records_json` n'en
dépendent pas DIRECTEMENT — `_write_records_json` importe `fitparse` localement,
donc testée via un FAUX module injecté dans `sys.modules` (voir
`TestWriteRecordsJsonSportExtraction`), jamais via `unittest.mock.patch("fitparse...")`
qui exigerait le vrai paquet installé pour résoudre l'attribut à patcher.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "skills/fit-download/scripts"))
import download_fit as D  # noqa: E402


class TestActivityDirOut(unittest.TestCase):
    """Blocker 3 : une version antérieure dérivait ce répertoire de `__file__`, qui
    remonte TOUJOURS au moteur (skills/ est un lien symbolique dans un workspace
    séparé) — jamais le workspace réel de l'utilisateur."""

    def setUp(self):
        self._saved = os.environ.get("ARC_WORKSPACE")

    def tearDown(self):
        if self._saved is None:
            os.environ.pop("ARC_WORKSPACE", None)
        else:
            os.environ["ARC_WORKSPACE"] = self._saved

    def test_respects_arc_workspace_env_var(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["ARC_WORKSPACE"] = tmp
            resolved = D._activity_dir_out()
            self.assertEqual(resolved, (Path(tmp) / "activities").resolve())

    def test_falls_back_to_engine_when_no_workspace_configured(self):
        os.environ.pop("ARC_WORKSPACE", None)
        # Sans pointeur ~/.config/ai-running-coach/workspace ni $ARC_WORKSPACE, le
        # repli est le moteur lui-même (installation fusionnée) — jamais une erreur.
        resolved = D._activity_dir_out()
        self.assertTrue(str(resolved).endswith("activities"))


class TestEnsureGitignore(unittest.TestCase):
    """Bug corrigé (revue PR #87, tour 2 — privacy) : une version antérieure ne faisait
    RIEN dès que `.gitignore` existait déjà, même sans les motifs attendus — un fichier
    préexistant dans `activities/` (installateur, ou l'athlète pour tout autre motif)
    empêchait alors silencieusement l'exclusion de `*.fit`/`*.records.json`, et
    `daily-sync` (`git add -A`) aurait committé des pistes GPS complètes."""

    def test_file_absent_creates_it_with_header_and_patterns(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            D._ensure_gitignore(directory, "# en-tête\n", ["*.fit", "*.records.json"])
            content = (directory / ".gitignore").read_text(encoding="utf-8")
            self.assertEqual(content, "# en-tête\n*.fit\n*.records.json\n")

    def test_file_present_without_patterns_gets_them_appended(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            (directory / ".gitignore").write_text("# personnalisé par l'utilisateur\n", encoding="utf-8")
            D._ensure_gitignore(directory, "# en-tête\n", ["*.fit", "*.records.json"])
            content = (directory / ".gitignore").read_text(encoding="utf-8")
            self.assertIn("# personnalisé par l'utilisateur\n", content)   # jamais écrasé
            self.assertIn("*.fit\n", content)
            self.assertIn("*.records.json\n", content)

    def test_file_present_without_patterns_and_without_trailing_newline(self):
        """Le contenu existant peut ne pas finir par un retour à la ligne : le premier
        motif ajouté ne doit pas se coller à la dernière ligne existante."""
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            (directory / ".gitignore").write_text("# sans retour à la ligne final", encoding="utf-8")
            D._ensure_gitignore(directory, "# en-tête\n", ["*.fit"])
            content = (directory / ".gitignore").read_text(encoding="utf-8")
            self.assertEqual(content, "# sans retour à la ligne final\n*.fit\n")

    def test_file_present_with_patterns_already_is_untouched_no_duplicate(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            original = "# personnalisé\n*.fit\n*.records.json\n"
            (directory / ".gitignore").write_text(original, encoding="utf-8")
            D._ensure_gitignore(directory, "# en-tête\n", ["*.fit", "*.records.json"])
            content = (directory / ".gitignore").read_text(encoding="utf-8")
            self.assertEqual(content, original)   # rien ajouté, rien dupliqué

    def test_only_the_missing_pattern_is_appended(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            (directory / ".gitignore").write_text("*.fit\n", encoding="utf-8")
            D._ensure_gitignore(directory, "# en-tête\n", ["*.fit", "*.records.json"])
            content = (directory / ".gitignore").read_text(encoding="utf-8")
            self.assertEqual(content, "*.fit\n*.records.json\n")
            self.assertEqual(content.count("*.fit"), 1)

    def test_repeated_calls_are_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            for _ in range(3):
                D._ensure_gitignore(directory, "# en-tête\n", ["*.fit", "*.records.json"])
            content = (directory / ".gitignore").read_text(encoding="utf-8")
            self.assertEqual(content, "# en-tête\n*.fit\n*.records.json\n")


class TestWriteCanonicalSamples(unittest.TestCase):
    RAW = [
        {"timestamp": "2026-01-01 08:00:00", "distance": 0.0, "heart_rate": 120, "cadence": 85},
        {"timestamp": "2026-01-01 08:00:05", "distance": 12.0, "heart_rate": 122, "cadence": 86},
    ]

    def test_writes_canonical_path_with_normalised_records(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "activities"
            root.mkdir()
            D._write_canonical_samples(123, self.RAW, root, sport="running")
            out = root / "fit/123.json"
            self.assertTrue(out.is_file())
            payload = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(payload["activity_id"], 123)
            self.assertEqual(len(payload["records"]), 2)

    def test_running_sport_doubles_cadence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "activities"
            root.mkdir()
            D._write_canonical_samples(1, self.RAW, root, sport="running")
            payload = json.loads((root / "fit/1.json").read_text(encoding="utf-8"))
            self.assertEqual(payload["records"][0]["cadence_spm"], 170.0)

    def test_cycling_sport_does_not_double_cadence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "activities"
            root.mkdir()
            D._write_canonical_samples(2, self.RAW, root, sport="cycling")
            payload = json.loads((root / "fit/2.json").read_text(encoding="utf-8"))
            self.assertEqual(payload["records"][0]["cadence_spm"], 85.0)

    def test_fit_dir_gets_its_own_gitignore_marker(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "activities"
            root.mkdir()
            D._write_canonical_samples(3, self.RAW, root, sport="running")
            marker = (root / "fit/.gitignore").read_text(encoding="utf-8")
            self.assertIn("*", marker)


class _FakeField:
    def __init__(self, name, value):
        self.name = name
        self.value = value


class _FakeMessage:
    def __init__(self, fields: dict):
        self.fields = [_FakeField(k, v) for k, v in fields.items()]
        self._fields = fields

    def get_value(self, name):
        return self._fields.get(name)


class TestWriteRecordsJsonSportExtraction(unittest.TestCase):
    """`_write_records_json` lit le sport dans le message FIT `session` — pour que le
    doublement de cadence (should-fix 5) ne s'applique jamais à tort à un FIT vélo.

    `fitparse` n'est PAS une dépendance de la suite de tests (CONTRIBUTING.md : stdlib
    uniquement — seul `download_fit.py`, hors index, en a besoin en production, via un
    import LOCAL à l'intérieur de `_write_records_json`). Un `patch("fitparse.FitFile")`
    échouerait en CI, où `fitparse` n'est pas installé (bug corrigé : la première
    version de ce test le faisait, cassant le palier D sur `ubuntu-latest` et
    `macos-latest`). On injecte donc un FAUX module `fitparse` dans `sys.modules`
    (`types.ModuleType` + attribut `FitFile`) via `patch.dict` : l'import local de
    `download_fit.py` le trouve sans jamais toucher au vrai paquet, présent ou non."""

    def _fake_fitparse_module(self, records, session_sport):
        instance = MagicMock()

        def get_messages(name):
            if name == "record":
                return [_FakeMessage(r) for r in records]
            if name == "session":
                return [_FakeMessage({"sport": session_sport})] if session_sport is not None else []
            return []

        instance.get_messages.side_effect = get_messages
        fake_module = types.ModuleType("fitparse")
        fake_module.FitFile = MagicMock(return_value=instance)
        return fake_module

    def test_extracts_running_sport(self):
        fake_module = self._fake_fitparse_module([{"heart_rate": 120}], "running")
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out.json"
            with patch.dict(sys.modules, {"fitparse": fake_module}):
                records, sport = D._write_records_json(b"FAKEFIT", out)
        self.assertEqual(sport, "running")
        self.assertEqual(len(records), 1)

    def test_extracts_cycling_sport_lowercased(self):
        fake_module = self._fake_fitparse_module([{"heart_rate": 130}], "Cycling")
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out.json"
            with patch.dict(sys.modules, {"fitparse": fake_module}):
                _, sport = D._write_records_json(b"FAKEFIT", out)
        self.assertEqual(sport, "cycling")

    def test_missing_session_message_yields_none_sport(self):
        fake_module = self._fake_fitparse_module([{"heart_rate": 140}], None)
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out.json"
            with patch.dict(sys.modules, {"fitparse": fake_module}):
                _, sport = D._write_records_json(b"FAKEFIT", out)
        self.assertIsNone(sport)

    def test_raw_records_file_still_written_unchanged(self):
        fake_module = self._fake_fitparse_module([{"heart_rate": 120, "distance": 5.0}], "running")
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out.json"
            with patch.dict(sys.modules, {"fitparse": fake_module}):
                D._write_records_json(b"FAKEFIT", out)
            raw = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual(raw, [{"heart_rate": 120, "distance": 5.0}])


if __name__ == "__main__":
    unittest.main()
