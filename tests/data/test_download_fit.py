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

import io
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


class TestShouldSkipDownload(unittest.TestCase):
    """Correctif rattrapage historique (revue de code) : `--json` ne doit sauter une
    séance déjà présente que si sa copie NORMALISÉE canonique
    (`<out_dir>/fit/<id>.json`, celle qu'`arc_index.py` ingère réellement) existe
    déjà — jamais sur le seul `.fit` brut, qu'un téléchargement antérieur SANS
    `--json` a pu laisser seul derrière lui."""

    def _paths(self, tmp, aid=42):
        out_dir = Path(tmp)
        dst = out_dir / f"{aid}.fit"
        return out_dir, dst

    def test_missing_fit_is_never_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_dir, dst = self._paths(tmp)
            self.assertFalse(D._should_skip_download(dst, out_dir, 42, overwrite=False, want_json=False))
            self.assertFalse(D._should_skip_download(dst, out_dir, 42, overwrite=False, want_json=True))

    def test_existing_fit_without_json_flag_is_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_dir, dst = self._paths(tmp)
            dst.write_bytes(b"FIT")
            self.assertTrue(D._should_skip_download(dst, out_dir, 42, overwrite=False, want_json=False))

    def test_existing_fit_with_json_flag_but_no_canonical_copy_is_not_skipped(self):
        """Cas du bug corrigé : un `.fit` déjà présent (téléchargé sans `--json` la
        première fois) ne doit PAS être sauté quand `--json` est maintenant demandé —
        la copie normalisée qu'`arc_index.py` ingère n'existe pas encore."""
        with tempfile.TemporaryDirectory() as tmp:
            out_dir, dst = self._paths(tmp)
            dst.write_bytes(b"FIT")
            self.assertFalse(D._should_skip_download(dst, out_dir, 42, overwrite=False, want_json=True))

    def test_existing_fit_with_json_flag_and_canonical_copy_is_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_dir, dst = self._paths(tmp)
            dst.write_bytes(b"FIT")
            fit_dir = out_dir / "fit"
            fit_dir.mkdir()
            (fit_dir / "42.json").write_text("{}", encoding="utf-8")
            self.assertTrue(D._should_skip_download(dst, out_dir, 42, overwrite=False, want_json=True))

    def test_canonical_copy_alone_is_enough_with_json_flag(self):
        """Les `.fit` bruts supprimés (lourds, jetables) mais `fit/<id>.json`
        conservé : `--json` ne re-télécharge rien (revue de code)."""
        with tempfile.TemporaryDirectory() as tmp:
            out_dir, dst = self._paths(tmp)
            fit_dir = out_dir / "fit"
            fit_dir.mkdir()
            (fit_dir / "42.json").write_text("{}", encoding="utf-8")
            self.assertTrue(D._should_skip_download(dst, out_dir, 42, overwrite=False, want_json=True))
            self.assertFalse(D._should_skip_download(dst, out_dir, 42, overwrite=False, want_json=False))

    def test_overwrite_never_skips_regardless_of_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_dir, dst = self._paths(tmp)
            dst.write_bytes(b"FIT")
            fit_dir = out_dir / "fit"
            fit_dir.mkdir()
            (fit_dir / "42.json").write_text("{}", encoding="utf-8")
            self.assertFalse(D._should_skip_download(dst, out_dir, 42, overwrite=True, want_json=True))
            self.assertFalse(D._should_skip_download(dst, out_dir, 42, overwrite=True, want_json=False))


class _FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _fake_opener(routes: dict, calls: list):
    """`urlopen` factice : `routes` = {suffixe de chemin: bytes | HTTPError}."""
    def opener(req, timeout=None):
        calls.append(req)
        path = req.full_url[len(D.INTERVALS_API):]
        body = routes[path]
        if isinstance(body, Exception):
            raise body
        return _FakeResponse(body)

    return opener


def _http_error(code: int):
    import urllib.error

    return urllib.error.HTTPError("https://intervals.icu/x", code, "err", {}, None)


class TestIntervalsCredentials(unittest.TestCase):
    """Source Intervals.icu (#68) : la clé API est celle du serveur MCP — une seule
    clé à configurer. Jamais d'appel réseau dans ces tests."""

    def setUp(self):
        self._saved = os.environ.pop("INTERVALS_ICU_API_KEY", None)

    def tearDown(self):
        os.environ.pop("INTERVALS_ICU_API_KEY", None)
        if self._saved is not None:
            os.environ["INTERVALS_ICU_API_KEY"] = self._saved

    def test_reads_the_mcp_env_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = Path(tmp) / ".env"
            env.write_text("# commentaire\nINTERVALS_ICU_API_KEY='abc123'\nINTERVALS_ICU_ATHLETE_ID=i1\n",
                           encoding="utf-8")
            self.assertEqual(D._intervals_api_key(env), "abc123")

    def test_environment_variable_wins_over_the_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = Path(tmp) / ".env"
            env.write_text("INTERVALS_ICU_API_KEY=fichier\n", encoding="utf-8")
            os.environ["INTERVALS_ICU_API_KEY"] = "variable"
            self.assertEqual(D._intervals_api_key(env), "variable")

    def test_missing_or_placeholder_key_is_an_explicit_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = Path(tmp) / ".env"
            with self.assertRaises(D.IntervalsError):
                D._intervals_api_key(env)
            env.write_text("INTERVALS_ICU_API_KEY=your_api_key_here\n", encoding="utf-8")
            with self.assertRaises(D.IntervalsError):
                D._intervals_api_key(env)


class TestIntervalsDownload(unittest.TestCase):
    FIT = b"\x0e\x10FAKE.FIT"
    META = json.dumps({"id": "i123456789", "source": "OAUTH_CLIENT", "type": "Run"}).encode()

    def _download(self, routes, aid="i123456789", want_json=False):
        calls: list = []
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            result = D._download_one_intervals(aid, out_dir, want_json, "k3y", opener=_fake_opener(routes, calls))
            written = result.read_bytes()
            gitignore = (out_dir / ".gitignore").read_text(encoding="utf-8")
        return result.name, written, gitignore, calls

    def test_writes_the_fit_under_its_intervals_id(self):
        name, written, gitignore, calls = self._download({
            "/activity/i123456789": self.META, "/activity/i123456789/fit-file": self.FIT})
        self.assertEqual(name, "i123456789.fit")
        self.assertEqual(written, self.FIT)
        self.assertIn("*.fit", gitignore)
        auth = calls[0].get_header("Authorization")
        self.assertTrue(auth.startswith("Basic "))
        import base64
        self.assertEqual(base64.b64decode(auth.split()[1]).decode(), "API_KEY:k3y")

    def test_gzipped_fit_is_decompressed(self):
        import gzip
        _, written, _, _ = self._download({
            "/activity/i123456789": self.META, "/activity/i123456789/fit-file": gzip.compress(self.FIT)})
        self.assertEqual(written, self.FIT)

    def test_json_flag_writes_the_canonical_copy_under_the_intervals_id(self):
        fake = types.ModuleType("fitparse")

        class _Msg:
            def __init__(self, fields):
                self.fields = [types.SimpleNamespace(name=k, value=v) for k, v in fields.items()]
                self._fields = fields

            def get_value(self, name):
                return self._fields.get(name)

        class _Fit:
            def __init__(self, _stream):
                pass

            def get_messages(self, name):
                if name == "record":
                    return [_Msg({"timestamp": "2026-09-29 16:56:53", "distance": 0.0, "heart_rate": 120,
                                  "cadence": 80}),
                            _Msg({"timestamp": "2026-09-29 16:56:54", "distance": 2.5, "heart_rate": 121,
                                  "cadence": 81})]
                return [_Msg({"sport": "running"})]

        fake.FitFile = _Fit
        calls: list = []
        with tempfile.TemporaryDirectory() as tmp, patch.dict(sys.modules, {"fitparse": fake}):
            out_dir = Path(tmp)
            D._download_one_intervals("i123456789", out_dir, True, "k3y", opener=_fake_opener({
                "/activity/i123456789": self.META, "/activity/i123456789/fit-file": self.FIT}, calls))
            canonical = json.loads((out_dir / "fit/i123456789.json").read_text(encoding="utf-8"))
        self.assertEqual(canonical["activity_id"], "i123456789")
        self.assertEqual([r["cadence_spm"] for r in canonical["records"]], [160.0, 162.0])

    def test_strava_import_is_unavailable_and_never_downloads_the_fit(self):
        meta = json.dumps({"id": "i1", "source": "STRAVA",
                           "_note": "STRAVA activities are not available via the API"}).encode()
        calls: list = []
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(D.IntervalsUnavailable) as cm:
                D._download_one_intervals("i1", Path(tmp), False, "k", opener=_fake_opener(
                    {"/activity/i1": meta}, calls))
            self.assertEqual(list(Path(tmp).iterdir()), [])
        self.assertIn("Strava", str(cm.exception))
        self.assertEqual(len(calls), 1, "le FIT ne doit même pas être demandé")

    def test_unprefixed_id_is_unavailable_without_any_request(self):
        calls: list = []
        with tempfile.TemporaryDirectory() as tmp, self.assertRaises(D.IntervalsUnavailable):
            D._download_one_intervals("123456789", Path(tmp), False, "k", opener=_fake_opener({}, calls))
        self.assertEqual(calls, [])

    def test_http_errors_map_to_explicit_reasons(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(D.IntervalsUnavailable):   # manuelle : pas de fichier
                D._download_one_intervals("i1", Path(tmp), False, "k", opener=_fake_opener({
                    "/activity/i1": self.META, "/activity/i1/fit-file": _http_error(404)}, []))
            with self.assertRaises(D.IntervalsError) as cm:
                D._download_one_intervals("i1", Path(tmp), False, "k", opener=_fake_opener({
                    "/activity/i1": _http_error(401)}, []))
            self.assertNotIsInstance(cm.exception, D.IntervalsUnavailable)
            self.assertIn("clé API", str(cm.exception))

    def test_403_and_429_have_dedicated_messages(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(D.IntervalsError) as cm:
                D._download_one_intervals("i1", Path(tmp), False, "k", opener=_fake_opener({
                    "/activity/i1": _http_error(403)}, []))
            self.assertIn("autre athlète", str(cm.exception))
            with self.assertRaises(D.IntervalsError) as cm:
                D._download_one_intervals("i1", Path(tmp), False, "k", opener=_fake_opener({
                    "/activity/i1": _http_error(429)}, []))
            self.assertNotIsInstance(cm.exception, D.IntervalsUnavailable)
            self.assertIn("réessayer plus tard", str(cm.exception))


class TestBatchExitCode(unittest.TestCase):
    """Revue #142 : seul un FAIL réel fait sortir en 1 — une activité INDISPONIBLE
    (import Strava, saisie manuelle) ou déjà présente n'est pas une panne, sinon
    `daily-sync.sh` signalerait un échec un jour avec une seule séance Strava."""

    @staticmethod
    def _run(outcomes, skipped=()):
        def fetch(aid):
            if outcomes[aid] == "unavailable":
                raise D.IntervalsUnavailable("import Strava")
            if outcomes[aid] == "fail":
                raise D.IntervalsError("HTTP 500")

        with patch("sys.stdout", io.StringIO()), patch("sys.stderr", io.StringIO()):
            return D._download_all(list(outcomes), fetch, lambda aid: aid in skipped)

    def test_only_unavailable_is_not_a_failure(self):
        counts = self._run({"i1": "unavailable", "i2": "unavailable"})
        self.assertEqual(counts, {"ok": 0, "unavailable": 2, "skipped": 0, "failed": 0})

    def test_all_skipped_is_not_a_failure(self):
        counts = self._run({"i1": "ok", "i2": "ok"}, skipped={"i1", "i2"})
        self.assertEqual(counts, {"ok": 0, "unavailable": 0, "skipped": 2, "failed": 0})

    def test_a_real_failure_is_counted_even_among_successes(self):
        counts = self._run({"i1": "ok", "i2": "fail", "i3": "unavailable"})
        self.assertEqual(counts, {"ok": 1, "unavailable": 1, "skipped": 0, "failed": 1})

    def test_main_exit_code_follows_real_failures_only(self):
        for outcome, expected in (("unavailable", 0), ("fail", 1)):
            with tempfile.TemporaryDirectory() as tmp, \
                    patch.object(D, "_intervals_api_key", return_value="k"), \
                    patch.object(D, "_download_one_intervals", side_effect=(
                        D.IntervalsUnavailable("Strava") if outcome == "unavailable" else D.IntervalsError("x"))), \
                    patch("sys.stdout", io.StringIO()), patch("sys.stderr", io.StringIO()):
                rc = D.main(["--source", "intervals", "--output-dir", tmp, "i1"])
            self.assertEqual(rc, expected, outcome)


class TestIntervalsIdsFromMarkdown(unittest.TestCase):
    def _md(self, data: dict) -> str:
        return f"# Séance\n\n```arc\n{json.dumps(data)}\n```\n"

    def test_reads_the_id_of_the_requested_source_only(self):
        text = self._md({"arc": 1, "kind": "activity", "intervals_activity_id": "i42"})
        self.assertEqual(D._activity_id_from_arc(text, "intervals"), "i42")
        self.assertIsNone(D._activity_id_from_arc(text, "garmin"))
        garmin = self._md({"arc": 1, "kind": "activity", "garmin_activity_id": 42})
        self.assertEqual(D._activity_id_from_arc(garmin), 42)
        self.assertIsNone(D._activity_id_from_arc(garmin, "intervals"))

    def test_malformed_intervals_id_is_ignored(self):
        text = self._md({"arc": 1, "kind": "activity", "intervals_activity_id": "42"})
        self.assertIsNone(D._activity_id_from_arc(text, "intervals"))

    def test_from_dir_collects_intervals_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a.md").write_text(self._md({"intervals_activity_id": "i1"}), encoding="utf-8")
            (root / "b.md").write_text(self._md({"garmin_activity_id": 2}), encoding="utf-8")
            self.assertEqual(D._ids_from_dir(root, "intervals"), ["i1"])
            self.assertEqual(D._ids_from_dir(root, "garmin"), [2])

    def test_garmin_source_rejects_an_intervals_id_with_a_hint(self):
        import argparse
        ap = argparse.ArgumentParser()
        with patch.object(ap, "error", side_effect=SystemExit) as err, self.assertRaises(SystemExit):
            D._parse_ids(["i42"], "garmin", ap)
        self.assertIn("--source intervals", err.call_args[0][0])
        self.assertEqual(D._parse_ids(["i42"], "intervals", ap), ["i42"])


def _fit_file(*messages: bytes, header_crc: bool = True) -> bytes:
    """FIT synthétique : en-tête de 14 octets (`.FIT`), messages bruts, CRC du fichier."""
    data = b"".join(messages)
    head = bytes([14, 0x20]) + (2132).to_bytes(2, "little") + len(data).to_bytes(4, "little") + b".FIT"
    head += D._fit_crc(head).to_bytes(2, "little") if header_crc else b"\0\0"
    body = head + data
    return body + D._fit_crc(body).to_bytes(2, "little")


def _definition(local: int, mesg: int, fields, dev_fields=()) -> bytes:
    """Message de définition little-endian : `fields` = [(numéro, taille, type de base)]."""
    head = 0x40 | local | (0x20 if dev_fields else 0)
    out = bytes([head, 0, 0]) + mesg.to_bytes(2, "little") + bytes([len(fields)])
    out += b"".join(bytes(f) for f in fields)
    if dev_fields:
        out += bytes([len(dev_fields)]) + b"".join(bytes(f) for f in dev_fields)
    return out


class TestFixFitFieldSizes(unittest.TestCase):
    """`fitparse` 1.2.0 refuse un FIT entier dès qu'un champ a une taille non multiple de son type (cas réel :
    `event.data`, uint32 écrit sur 1 octet par une COROS Pace 4 Pro). `_fix_fit_field_sizes` relit ces
    définitions en octets et recalcule le CRC — stdlib, testé sans `fitparse`."""

    UINT32, UINT16, BYTE = 0x86, 0x84, 0x0D

    def test_crc_matches_the_fit_sdk_reference(self):
        # Valeur de référence calculée avec `fitparse.records.Crc.calculate` (même table que le FIT SDK).
        self.assertEqual(D._fit_crc(b"123456789"), 0xBB3D)

    def test_odd_sized_field_is_read_as_bytes_and_the_crc_recomputed(self):
        fit = _fit_file(
            _definition(0, 21, [(253, 4, self.UINT32), (3, 1, self.UINT32), (0, 1, 0x00)]),
            bytes([0x00]) + (1000).to_bytes(4, "little") + bytes([7, 0]),
            _definition(1, 20, [(253, 4, self.UINT32), (3, 1, 0x02)]),
            bytes([0x01]) + (1001).to_bytes(4, "little") + bytes([140]),
        )
        fixed, fixes = D._fix_fit_field_sizes(fit)
        self.assertEqual(fixes, ["message 21 champ 3 : 1 octet(s) pour un type de 4"])
        self.assertEqual(len(fixed), len(fit))
        diff = [i for i, (a, b) in enumerate(zip(fit, fixed)) if a != b]
        self.assertEqual(fixed[diff[0]], self.BYTE)                # seul le type de base change…
        self.assertTrue(set(diff[1:]) <= {len(fit) - 2, len(fit) - 1})   # … et le CRC du fichier
        self.assertEqual(D._fit_crc(fixed[:-2]), int.from_bytes(fixed[-2:], "little"))
        self.assertEqual(D._fix_fit_field_sizes(fixed), (fixed, []))    # idempotent

    def test_consistent_fit_is_returned_untouched(self):
        fit = _fit_file(_definition(0, 20, [(253, 4, self.UINT32), (3, 1, 0x02)]),
                        bytes([0x00]) + (1000).to_bytes(4, "little") + bytes([140]))
        self.assertEqual(D._fix_fit_field_sizes(fit), (fit, []))

    def test_compressed_timestamps_and_developer_fields_are_walked(self):
        fit = _fit_file(
            _definition(0, 20, [(3, 1, 0x02), (7, 3, self.UINT16)], dev_fields=[(0, 2, 0)]),
            bytes([0x00, 140, 1, 2, 3, 9, 9]),                      # 1 + 3 octets de champs + 2 développeur
            bytes([0x80 | 0x05, 141, 1, 2, 3, 9, 9]),               # en-tête compressé, type local 0
        )
        fixed, fixes = D._fix_fit_field_sizes(fit)
        self.assertEqual(fixes, ["message 20 champ 7 : 3 octet(s) pour un type de 2"])
        self.assertEqual(D._fit_crc(fixed[:-2]), int.from_bytes(fixed[-2:], "little"))

    def test_chained_fit_files_are_each_fixed(self):
        bad = _fit_file(_definition(0, 21, [(3, 1, self.UINT32)]), bytes([0x00, 7]))
        fixed, fixes = D._fix_fit_field_sizes(bad + bad)
        self.assertEqual(len(fixes), 1)                             # même définition : signalée une fois
        half = len(bad)
        for part in (fixed[:half], fixed[half:]):
            self.assertEqual(D._fit_crc(part[:-2]), int.from_bytes(part[-2:], "little"))
            self.assertNotEqual(part, bad)

    def test_bad_crc_truncated_or_foreign_bytes_are_left_to_fitparse(self):
        bad = _fit_file(_definition(0, 21, [(3, 1, self.UINT32)]), bytes([0x00, 7]))
        corrupted = bad[:-1] + bytes([bad[-1] ^ 0xFF])
        for raw in (corrupted, bad[:-5], b"not a fit file", b"",
                    _fit_file(bytes([0x00, 7]))):                    # données sans définition
            self.assertEqual(D._fix_fit_field_sizes(raw), (raw, []))

    def test_read_fit_hands_the_fixed_bytes_to_fitparse_and_says_so(self):
        bad = _fit_file(_definition(0, 21, [(3, 1, self.UINT32)]), bytes([0x00, 7]))
        seen = []

        class _Fit:
            def __init__(self, stream):
                seen.append(stream.read())

            def get_messages(self, _name):
                return []

        fake = types.ModuleType("fitparse")
        fake.FitFile = _Fit
        with patch.dict(sys.modules, {"fitparse": fake}), patch("sys.stderr", new_callable=io.StringIO) as err:
            self.assertEqual(D._read_fit(bad), ([], None))
        self.assertEqual(seen, [D._fix_fit_field_sizes(bad)[0]])
        self.assertIn("message 21 champ 3", err.getvalue())


if __name__ == "__main__":
    unittest.main()
