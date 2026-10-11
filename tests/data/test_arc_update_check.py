"""Palier D — nouvelle version disponible (`scripts/arc_update_check.py`).

Aucun appel réseau : la récupération de la release est injectée (`fetch=`).
"""

from __future__ import annotations

import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))
import arc_update_check as U  # noqa: E402

RELEASE = {"latest": "v1.2.0", "url": "https://example.test/v1.2.0", "published_at": "2026-10-20T10:00:00Z",
           "notes": "Nouveautés"}


def fetch_ok():
    return dict(RELEASE)


def fetch_fail():
    raise OSError("hors ligne")


class Versions(unittest.TestCase):
    def test_only_strictly_newer_releases_count(self):
        cases = [
            ("v1.2.0", "v1.1.0", True),
            ("v1.1.0", "v1.1.0", False),
            ("v1.1.0", "v1.1.0-24-gaa77fc7", False),     # main après la release : pas d'alerte
            ("v1.2.0", "v1.1.0-24-gaa77fc7", True),
            ("v1.2.0", "v1.2.0-rc.1", True),             # la release suit sa pré-version
            ("v1.2.0", "v1.2.0-rc.1-3-gabc1234", True),
            ("v1.1.0", "v1.2.0-rc.1", False),
            ("v1.10.0", "v1.9.0", True),                 # tri numérique, pas lexical
            ("v1.2.0", None, False),                     # version locale inconnue : jamais d'alerte
            ("pas-une-version", "v1.0.0", False),
        ]
        for latest, current, expected in cases:
            with self.subTest(latest=latest, current=current):
                self.assertEqual(U.is_newer(latest, current), expected)


class Check(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        self.cache = self.tmp / "cache.json"
        self.workspace = self.tmp / "ws"
        (self.workspace / "config").mkdir(parents=True)
        patcher = mock.patch.dict(os.environ, {"ARC_UPDATE_CHECK": ""})
        patcher.start()
        self.addCleanup(patcher.stop)

    def run_check(self, **kwargs):
        kwargs.setdefault("fetch", fetch_ok)
        kwargs.setdefault("current", "v1.1.0")
        return U.check(self.workspace, cache=self.cache, **kwargs)

    def test_update_available_and_cached(self):
        state = self.run_check(now=1000.0)
        self.assertTrue(state["update_available"])
        self.assertEqual((state["latest"], state["url"]), ("v1.2.0", "https://example.test/v1.2.0"))
        self.assertEqual(json.loads(self.cache.read_text())["checked_at"], 1000.0)

    def test_cache_is_reused_for_24_hours(self):
        self.run_check(now=1000.0)
        calls = []
        state = self.run_check(now=1000.0 + U.CACHE_TTL_S - 1, fetch=lambda: calls.append(1) or fetch_ok())
        self.assertEqual(calls, [])
        self.assertTrue(state["update_available"])
        self.run_check(now=1000.0 + U.CACHE_TTL_S + 1, fetch=lambda: calls.append(1) or fetch_ok())
        self.assertEqual(calls, [1])

    def test_force_ignores_the_cache(self):
        self.run_check(now=1000.0)
        calls = []
        self.run_check(now=1001.0, force=True, fetch=lambda: calls.append(1) or fetch_ok())
        self.assertEqual(calls, [1])

    def test_network_failure_is_silent_and_keeps_the_stale_cache(self):
        state = self.run_check(fetch=fetch_fail)
        self.assertFalse(state["update_available"])
        self.assertIn("error", state)
        self.run_check(now=1000.0)
        state = self.run_check(now=1000.0 + 2 * U.CACHE_TTL_S, fetch=fetch_fail)
        self.assertTrue(state["update_available"])

    def test_failure_is_not_retried_for_an_hour(self):
        calls = []

        def failing():
            calls.append(1)
            raise OSError("hors ligne")
        self.run_check(now=1000.0, fetch=failing)
        state = self.run_check(now=1000.0 + U.RETRY_AFTER_FAILURE_S - 1, fetch=failing)
        self.assertEqual(calls, [1], "nouvel appel réseau malgré un échec récent")
        self.assertIn("error", state)
        self.run_check(now=1000.0 + U.RETRY_AFTER_FAILURE_S + 1, fetch=failing)
        self.assertEqual(calls, [1, 1])

    def test_failure_is_remembered_even_when_the_cache_is_not_writable(self):
        calls = []

        def failing():
            calls.append(1)
            raise OSError("hors ligne")
        with mock.patch.object(U, "_write_cache"):
            self.run_check(now=5000.0, fetch=failing)
            self.run_check(now=5001.0, fetch=failing)
        self.assertEqual(calls, [1])

    def test_unexpected_errors_never_escape(self):
        def broken():
            raise AttributeError("'list' object has no attribute 'get'")
        state = self.run_check(fetch=broken)
        self.assertFalse(state["update_available"])
        self.assertIn("error", state)

    def test_non_object_payload_is_rejected(self):
        response = mock.MagicMock()
        response.__enter__.return_value = io.BytesIO(b"[]")
        with mock.patch.object(U.urllib.request, "urlopen", return_value=response):
            with self.assertRaises(ValueError):
                U.fetch_latest()

    def test_disabled_by_config_never_fetches(self):
        (self.workspace / "config/workspace.user.toml").write_text("[update]\ncheck = false\n", encoding="utf-8")
        state = self.run_check(fetch=lambda: self.fail("appel réseau alors que [update].check = false"))
        self.assertEqual((state["enabled"], state["update_available"]), (False, False))
        self.assertFalse(self.cache.exists())

    def test_user_config_wins_over_shared(self):
        (self.workspace / "config/workspace.toml").write_text("[update]\ncheck = false\n", encoding="utf-8")
        (self.workspace / "config/workspace.user.toml").write_text("[update]\ncheck = true\n", encoding="utf-8")
        self.assertTrue(U.enabled(self.workspace))

    def test_disabled_by_environment(self):
        with mock.patch.dict(os.environ, {"ARC_UPDATE_CHECK": "off"}):
            state = self.run_check(fetch=lambda: self.fail("appel réseau alors que ARC_UPDATE_CHECK=off"))
        self.assertFalse(state["enabled"])

    def test_notify_once_per_release(self):
        state = self.run_check()
        marker = self.tmp / "logs/.update-notified"
        self.assertIn("v1.2.0", U.notify_once(state, marker))
        self.assertTrue(U.mark_notified(state, marker))
        self.assertIsNone(U.notify_once(state, marker))
        state["latest"] = "v1.3.0"
        self.assertIn("v1.3.0", U.notify_once(state, marker))

    def test_release_is_renotified_until_the_send_is_confirmed(self):
        state = self.run_check()
        marker = self.tmp / "logs/.update-notified"
        self.assertIsNotNone(U.notify_once(state, marker))
        self.assertFalse(marker.exists(), "release mémorisée avant l'envoi")
        self.assertIsNotNone(U.notify_once(state, marker), "envoi échoué : la release doit revenir")

    def test_disabled_by_string_or_empty_value(self):
        for raw in ('"off"', '"false"', '"non"', '""', "0"):
            with self.subTest(value=raw):
                (self.workspace / "config/workspace.user.toml").write_text(
                    f"[update]\ncheck = {raw}\n", encoding="utf-8")
                self.assertFalse(U.enabled(self.workspace))
        (self.workspace / "config/workspace.user.toml").write_text('[update]\ncheck = "on"\n', encoding="utf-8")
        self.assertTrue(U.enabled(self.workspace))

    def test_unknown_local_version_never_fetches(self):
        for current in ("", "abc1234"):
            with self.subTest(current=current):
                state = self.run_check(current=current,
                                       fetch=lambda: self.fail("appel réseau sans version locale connue"))
                self.assertFalse(state["update_available"])

    def test_notify_once_silent_when_up_to_date(self):
        state = self.run_check(current="v1.2.0")
        self.assertIsNone(U.notify_once(state, self.tmp / "marker"))
        self.assertFalse((self.tmp / "marker").exists())


class Cli(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)

    def run_main(self, *argv, env=None, state=None):
        out = io.StringIO()
        fake = state or {"enabled": True, "current": "v1.1.0", "latest": "v1.2.0", "update_available": True,
                         "url": "https://example.test/v1.2.0", "command": "/update-coach"}
        with mock.patch.dict(os.environ, env or {}), mock.patch.object(U, "check", return_value=fake), \
                redirect_stdout(out):
            self.assertEqual(U.main(["--workspace", str(self.tmp), *argv]), 0)
        return out.getvalue()

    def test_hook_prints_context_only_when_an_update_exists(self):
        text = self.run_main("--hook", env={"ARC_HEADLESS": ""})
        self.assertIn("v1.2.0", text)
        self.assertIn("/update-coach", text)
        up_to_date = {"enabled": True, "current": "v1.2.0", "latest": "v1.2.0", "update_available": False,
                      "url": None, "command": "/update-coach"}
        self.assertEqual(self.run_main("--hook", env={"ARC_HEADLESS": ""}, state=up_to_date), "")

    def test_hook_is_silent_in_headless_runs(self):
        self.assertEqual(self.run_main("--hook", env={"ARC_HEADLESS": "1"}), "")

    def test_api_version_skips_the_check_when_the_version_is_unknown(self):
        import arc_serve
        with mock.patch.object(arc_serve.V, "cached_engine_version", return_value=None), \
                mock.patch.object(arc_serve.U, "check", side_effect=AssertionError("check() appelé")):
            self.assertEqual(arc_serve.api_version(self.tmp), {"version": None, "update": None})

    def test_default_output_is_one_line(self):
        self.assertEqual(len(self.run_main().strip().splitlines()), 1)


if __name__ == "__main__":
    unittest.main()
