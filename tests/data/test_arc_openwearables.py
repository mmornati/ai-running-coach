"""Palier D — client REST Open Wearables (#219, épopée #216). Faux serveur HTTP local (127.0.0.1) et
fixtures SYNTHÉTIQUES construites d'après les schémas OW 0.9.0 ; aucun accès réseau, aucune donnée réelle."""

from __future__ import annotations

import contextlib
import io
import json
import os
import re
import shutil
import socket
import sys
import tempfile
import threading
import time
import unittest
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from unittest import mock
from urllib.parse import parse_qs, urlsplit

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))
import arc_contract as C  # noqa: E402
import arc_openwearables as OW  # noqa: E402
from tests.lib.local_http import ThreadingHTTPServer  # noqa: E402

FIXTURES = REPO / "tests/data/fixtures/openwearables"
FAKE_KEY = "sk-0123456789abcdef0123456789abcdef"
DAY = "2026-10-05"


def load(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


class OWStub:
    """Faux serveur OW : sert un « bundle » de fixtures, journalise chaque requête, vérifie l'en-tête de clé."""

    def __init__(self, bundle: dict, key: str = FAKE_KEY, page_size: int = 0):
        self.bundle, self.key, self.page_size = bundle, key, page_size
        self.log: list = []          # [(chemin, {param: [valeurs]}, en-têtes)]
        stub = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                parts = urlsplit(self.path)
                query = parse_qs(parts.query)
                stub.log.append((parts.path, query, {k.lower(): v for k, v in self.headers.items()}))
                if self.headers.get(OW.API_KEY_HEADER) != stub.key:
                    return self._send({"detail": "Invalid or missing API key"}, 401)
                path = parts.path
                b = stub.bundle
                if path == "/api/v1/users":
                    return self._send(b["users"])
                if path.endswith("/connections"):
                    return self._send(b["connections"])
                if path.endswith("/summaries/sleep"):
                    return self._send(b["sleep"])
                if path.endswith("/timeseries"):
                    return self._send(stub._timeseries(query))
                if path.endswith("/health-scores"):
                    return self._send(b["scores"])
                if path.endswith("/summaries/recovery"):
                    return self._send({"data": [], "pagination": {"has_more": False}})
                return self._send({"detail": "Not Found"}, 404)

            def _send(self, payload, status=200):
                body = json.dumps(payload).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.httpd.daemon_threads = True
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    def _timeseries(self, query: dict) -> dict:
        data = self.bundle["timeseries"]["data"]
        wanted = set(query.get("types") or [])
        data = [s for s in data if not wanted or s["type"] in wanted]
        if not self.page_size:
            return {**self.bundle["timeseries"], "data": data}
        start = int((query.get("cursor") or ["0"])[0])
        chunk = data[start:start + self.page_size]
        nxt = str(start + self.page_size) if start + self.page_size < len(data) else None
        return {"data": chunk, "pagination": {"next_cursor": nxt, "has_more": nxt is not None},
                "metadata": {"resolution": "raw"}}

    def paths(self) -> list:
        return [entry[0] for entry in self.log]

    def __enter__(self) -> "OWStub":
        self.thread.start()
        return self

    def __exit__(self, *exc) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()


class Base(unittest.TestCase):
    provider = "oura"

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="arc-ow-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.ws = self.tmp / "ws"
        (self.ws / "config").mkdir(parents=True)
        self.key_file = self.tmp / "ow.key"
        self.key_file.write_text(FAKE_KEY + "\n", encoding="utf-8")
        os.chmod(self.key_file, 0o600)

    def write_config(self, provider=None, source="openwearables", user_id="", extra=""):
        provider = self.provider if provider is None else provider
        (self.ws / "config/workspace.user.toml").write_text(
            f'[health]\nsource = "{source}"\n\n[health.openwearables]\nprovider = "{provider}"\n'
            f'user_id = "{user_id}"\nstale_after_h = 36\n{extra}', encoding="utf-8")

    def run_cli(self, base_url, *args, key_file=None, env=None):
        """Rend (code, stdout, stderr) ; la configuration passe par les surcharges ARC_OW_*."""
        environ = {"ARC_OW_BASE_URL": base_url, "ARC_OW_API_KEY_FILE": str(key_file or self.key_file)}
        environ.update(env or {})
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.dict(os.environ, environ), contextlib.redirect_stdout(out), \
                contextlib.redirect_stderr(err):
            try:
                code = OW.main(["--workspace", str(self.ws), *args])
            except SystemExit as exc:       # argparse
                code = exc.code
        return code, out.getvalue(), err.getvalue()

    def health_day(self, stub, date=DAY, expect=0):
        code, out, err = self.run_cli(stub.base, "health-day", "--date", date, "--json")
        self.assertEqual(code, expect, (out, err))
        self.assertNotIn(FAKE_KEY, out + err)
        return json.loads(out)

    def assert_contract(self, arc: dict):
        block = {"arc": 1, "kind": "health", "date": DAY, "morning_check": "full", **arc}
        errors, _ = C.validate(block)
        self.assertEqual(errors, [], errors)


class NominalTests(Base):
    def test_oura_nominal(self):
        self.write_config("oura")
        with OWStub(load("oura")) as stub:
            res = self.health_day(stub)
        arc = res["arc"]
        self.assertEqual(arc["health_source"], "openwearables")
        self.assertEqual(arc["health_provider"], "oura")
        self.assertEqual(arc["health_device"], "Oura Ring 4")
        self.assertEqual(arc["hrv_overnight_ms"], 48.2)
        self.assertNotIn("hrv_sdnn_ms", arc)
        self.assertEqual(arc["resting_hr_bpm"], 47)
        self.assertEqual(arc["sleep_total_s"], 435 * 60)
        self.assertEqual((arc["sleep_deep_s"], arc["sleep_light_s"], arc["sleep_rem_s"], arc["sleep_awake_s"]),
                         (5400, 14400, 6300, 1500))
        self.assertEqual(arc["sleep_start"], "2026-10-04T23:05:00+02:00")
        self.assertEqual(arc["sleep_end"], "2026-10-05T06:45:00+02:00")
        # readiness 1-100 et sommeil 1-100 de l'Oura ; le score `internal` et la strain WHOOP sont ignorés
        self.assertEqual([(s["category"], s["value"], s["scale_min"], s["scale_max"], s["provider"])
                          for s in arc["provider_scores"]],
                         [("readiness", 82, 1, 100, "oura"), ("sleep", 77, 1, 100, "oura")])
        self.assertEqual(res["unavailable"], {})
        self.assertTrue(res["ok"])
        for forbidden in ("readiness_score", "sleep_score", "readiness_factors"):
            self.assertNotIn(forbidden, arc)
        self.assert_contract(arc)

    def test_polar_scores_never_rescaled_and_strain_ignored(self):
        self.write_config("polar")
        with OWStub(load("polar")) as stub:
            res = self.health_day(stub)
        scores = {s["category"]: s for s in res["arc"]["provider_scores"]}
        self.assertEqual(set(scores), {"readiness", "recovery", "sleep"})
        self.assertEqual((scores["sleep"]["value"], scores["sleep"]["scale_max"]), (80, 100))
        self.assertEqual((scores["readiness"]["value"], scores["readiness"]["scale_min"], scores["readiness"]["scale_max"]),
                         (7, 0, 10))
        self.assertEqual((scores["recovery"]["value"], scores["recovery"]["scale_min"], scores["recovery"]["scale_max"]),
                         (4, 1, 6))
        self.assertEqual(scores["recovery"]["qualifier"], "OK")
        self.assertNotIn("strain", json.dumps(res))
        self.assert_contract(res["arc"])

    def test_apple_sdnn_only(self):
        self.write_config("apple")
        with OWStub(load("apple")) as stub:
            res = self.health_day(stub)
        arc = res["arc"]
        self.assertEqual(arc["hrv_sdnn_ms"], 61.3)
        self.assertNotIn("hrv_overnight_ms", arc)
        self.assertIn("SDNN", res["unavailable"]["hrv_overnight_ms"])
        self.assertIn("readiness", res["unavailable"])
        # Fournisseur SDK présent dans la liste : la fraîcheur vient de la connexion
        self.assertEqual(res["freshness"]["provider"], "apple")
        self.assert_contract(arc)

    def test_apple_rmssd_is_ignored(self):
        self.write_config("apple")
        bundle = load("apple")
        bundle["sleep"]["data"][0]["avg_hrv_rmssd_ms"] = 30.0
        with OWStub(bundle) as stub:
            res = self.health_day(stub)
        self.assertNotIn("hrv_overnight_ms", res["arc"])
        self.assertIn("apple_rmssd_ignored", [w["code"] for w in res["warnings"]])
        self.assert_contract(res["arc"])

    def test_withings_has_explicit_unavailabilities(self):
        self.write_config("withings")
        with OWStub(load("withings")) as stub:
            res = self.health_day(stub)
        arc = res["arc"]
        for key in ("hrv_overnight_ms", "hrv_sdnn_ms", "resting_hr_bpm", "provider_scores"):
            self.assertNotIn(key, arc)
        self.assertEqual(set(res["unavailable"]), {"hrv_overnight_ms", "resting_hr_bpm", "readiness"})
        self.assertIn("aucun score de readiness ni de recovery chez withings", res["unavailable"]["readiness"])
        self.assertEqual(arc["sleep_total_s"], 435 * 60)
        self.assert_contract(arc)

    def test_no_data_for_the_day(self):
        self.write_config("oura")
        with OWStub(load("oura")) as stub:
            res = self.health_day(stub, date="2026-10-20")
        self.assertTrue(res["ok"])
        self.assertEqual(set(res["arc"]), {"health_source", "health_provider"})
        self.assertEqual(set(res["unavailable"]), {"hrv_overnight_ms", "resting_hr_bpm", "readiness"})
        self.assertIn("aucune nuit", res["unavailable"]["hrv_overnight_ms"])
        self.assert_contract(res["arc"])


class SourceRulesTests(Base):
    def test_provider_mismatch_ignores_the_entry(self):
        self.write_config("oura")
        with OWStub(load("provider_mismatch")) as stub:
            res = self.health_day(stub)
        self.assertIn("provider_mismatch", [w["code"] for w in res["warnings"]])
        message = next(w["message"] for w in res["warnings"] if w["code"] == "provider_mismatch")
        self.assertIn("priorités", message)
        self.assertNotIn("sleep_total_s", res["arc"])
        self.assertNotIn("hrv_sdnn_ms", res["arc"])
        self.assertEqual(res["arc"]["health_provider"], "oura")

    def test_hrv_fallback_uses_only_the_sleep_window(self):
        self.write_config("oura")
        with OWStub(load("hrv_fallback")) as stub:
            res = self.health_day(stub)
        # 40 et 50 dans la nuit (21:05Z-04:45Z) ; 99 (veille 15:00Z) et 98 (08:00Z, après le réveil) exclus
        self.assertEqual(res["arc"]["hrv_overnight_ms"], 45.0)
        self.assertIn("hrv_from_timeseries", [w["code"] for w in res["warnings"]])
        self.assert_contract(res["arc"])

    def test_hrv_fallback_follows_pagination(self):
        self.write_config("oura")
        with OWStub(load("hrv_fallback"), page_size=2) as stub:
            res = self.health_day(stub)
            pages = [q for p, q, _ in stub.log if p.endswith("/timeseries")]
        self.assertGreaterEqual(len(pages), 3)
        self.assertEqual(res["arc"]["hrv_overnight_ms"], 45.0)

    def test_summary_rmssd_wins_over_series(self):
        self.write_config("oura")
        with OWStub(load("oura")) as stub:
            self.health_day(stub)
            types = [q.get("types") for p, q, _ in stub.log if p.endswith("/timeseries")]
        self.assertEqual(types, [["resting_heart_rate"]])

    def test_unknown_scale_and_internal_dropped(self):
        self.write_config("oura")
        with OWStub(load("unknown_scale")) as stub:
            res = self.health_day(stub)
        self.assertEqual([(s["category"], s["value"]) for s in res["arc"]["provider_scores"]], [("readiness", 82)])
        self.assertIn("unknown_score_scale", [w["code"] for w in res["warnings"]])
        self.assert_contract(res["arc"])

    def test_recovery_summary_endpoint_is_never_requested(self):
        for provider, name in (("oura", "oura"), ("polar", "polar"), ("apple", "apple"), ("withings", "withings")):
            self.write_config(provider)
            with OWStub(load(name)) as stub:
                self.health_day(stub)
                self.run_cli(stub.base, "check", "--json")
                paths = stub.paths()
            self.assertFalse([p for p in paths if "recovery" in p], paths)
            self.assertTrue(any(p.endswith("/health-scores") for p in paths))

    def test_read_only_and_expected_requests(self):
        self.write_config("oura")
        with OWStub(load("oura")) as stub:
            self.health_day(stub)
            log = list(stub.log)
        self.assertEqual([re.sub(r"^/api/v1/(users/[^/]+/)?", "", p) for p, _, _ in log],
                         ["users", "connections", "summaries/sleep", "timeseries", "health-scores"])
        ts = next(q for p, q, _ in log if p.endswith("/timeseries"))
        self.assertEqual(ts["provider"], ["oura"])
        self.assertEqual(ts["resolution"], ["raw"])
        scores = next(q for p, q, _ in log if p.endswith("/health-scores"))
        self.assertEqual(scores["provider"], ["oura"])
        for _, query, headers in log:
            self.assertNotIn(FAKE_KEY, json.dumps(query))
            self.assertEqual(headers.get(OW.API_KEY_HEADER.lower()), FAKE_KEY)


class UserAndConnectionTests(Base):
    def test_two_users_without_user_id_is_ambiguous(self):
        self.write_config("oura")
        bundle = load("oura")
        bundle["users"] = load("users_two")
        with OWStub(bundle) as stub:
            code, out, err = self.run_cli(stub.base, "health-day", "--date", DAY, "--json")
        self.assertEqual(code, 2)
        res = json.loads(out)
        self.assertEqual(res["error"]["code"], "ambiguous_user")
        self.assertEqual(res["error"]["user_count"], 2)
        blob = out + err
        for leak in ("Prenom", "Nom0", "athlete0", "example.invalid"):
            self.assertNotIn(leak, blob)

    def test_configured_user_id_must_be_listed(self):
        bundle = load("oura")
        self.write_config("oura", user_id="00000000-0000-4000-8000-0000000000ff")
        with OWStub(bundle) as stub:
            code, out, _ = self.run_cli(stub.base, "health-day", "--date", DAY, "--json")
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(out)["error"]["code"], "user_not_found")
        self.write_config("oura", user_id=bundle["user_id"])
        with OWStub(bundle) as stub:
            self.health_day(stub)

    def test_stale_connection_warns(self):
        self.write_config("oura")
        bundle = load("oura")
        old = (datetime.now(timezone.utc) - timedelta(hours=100)).strftime("%Y-%m-%dT%H:%M:%SZ")
        bundle["connections"][0]["last_synced_at"] = old
        with OWStub(bundle) as stub:
            res = self.health_day(stub)
        self.assertTrue(res["freshness"]["stale"])
        self.assertIn("stale", [w["code"] for w in res["warnings"]])

    def test_recent_sync_is_not_stale(self):
        self.write_config("oura")
        bundle = load("oura")
        bundle["connections"][0]["last_synced_at"] = (datetime.now(timezone.utc) - timedelta(hours=2)
                                                      ).strftime("%Y-%m-%dT%H:%M:%SZ")
        with OWStub(bundle) as stub:
            res = self.health_day(stub)
        self.assertFalse(res["freshness"]["stale"])
        self.assertNotIn("stale", [w["code"] for w in res["warnings"]])

    def test_revoked_connection_reads_nothing(self):
        self.write_config("oura")
        bundle = load("oura")
        bundle["connections"][0]["status"] = "revoked"
        with OWStub(bundle) as stub:
            res = self.health_day(stub)
            paths = stub.paths()
        self.assertEqual(res["freshness"]["status"], "revoked")
        self.assertEqual(set(res["arc"]), {"health_source", "health_provider"})
        self.assertIn("revoked", res["unavailable"]["readiness"])
        self.assertFalse([p for p in paths if p.endswith(("/timeseries", "/health-scores", "/summaries/sleep"))])

    def test_sdk_provider_absent_from_connections_is_unknown(self):
        self.write_config("apple")
        bundle = load("apple")
        bundle["connections"] = []
        with OWStub(bundle) as stub:
            res = self.health_day(stub)
        self.assertEqual(res["freshness"]["status"], "unknown")
        self.assertIsNone(res["freshness"]["stale"])
        self.assertIn("freshness_unknown", [w["code"] for w in res["warnings"]])
        self.assertEqual(res["arc"]["hrv_sdnn_ms"], 61.3)


class ErrorTests(Base):
    def test_401_exits_3_and_leaks_nothing(self):
        self.write_config("oura")
        with OWStub(load("oura"), key="sk-un-autre-secret") as stub:
            for args in (("health-day", "--json"), ("check", "--json"), ("health-day",)):
                code, out, err = self.run_cli(stub.base, *args)
                self.assertEqual(code, 3, args)
                self.assertNotIn(FAKE_KEY, out + err)
                self.assertNotIn("Traceback", out + err)
            code, out, _ = self.run_cli(stub.base, "check", "--json")
            self.assertEqual(json.loads(out)["error"]["code"], "auth")
            self.assertEqual(json.loads(out)["auth"], "refused")
            self.assertTrue(all(FAKE_KEY not in p for p in stub.paths()))

    def test_unreachable_host_exits_3(self):
        self.write_config("oura")
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]      # port libre, rien n'écoute
        code, out, err = self.run_cli(f"http://127.0.0.1:{port}", "health-day", "--json")
        self.assertEqual(code, 3)
        self.assertEqual(json.loads(out)["error"]["code"], "unreachable")
        self.assertNotIn(FAKE_KEY, out + err)

    def test_malformed_json_is_clean(self):
        self.write_config("oura")

        class Bad(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                body = b"<html>pas du json</html>"
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        httpd = ThreadingHTTPServer(("127.0.0.1", 0), Bad)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        self.addCleanup(httpd.server_close)
        self.addCleanup(httpd.shutdown)
        code, out, err = self.run_cli(f"http://127.0.0.1:{httpd.server_address[1]}", "health-day", "--json")
        self.assertEqual(code, 3)
        self.assertEqual(json.loads(out)["error"]["code"], "bad_response")
        self.assertNotIn("Traceback", out + err)

    def test_redirect_is_refused_and_key_not_forwarded(self):
        self.write_config("oura")
        seen = []

        class Redirect(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                seen.append(self.path)
                self.send_response(302)
                self.send_header("Location", "http://127.0.0.1:1/ailleurs")
                self.send_header("Content-Length", "0")
                self.end_headers()

        httpd = ThreadingHTTPServer(("127.0.0.1", 0), Redirect)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        self.addCleanup(httpd.server_close)
        self.addCleanup(httpd.shutdown)
        code, out, _ = self.run_cli(f"http://127.0.0.1:{httpd.server_address[1]}", "health-day", "--json")
        self.assertEqual(code, 3)
        self.assertEqual(json.loads(out)["error"]["code"], "redirect")
        self.assertEqual(len(seen), 1)

    def test_500_exits_3(self):
        self.write_config("oura")

        class Boom(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                self.send_response(500)
                self.send_header("Content-Length", "0")
                self.end_headers()

        httpd = ThreadingHTTPServer(("127.0.0.1", 0), Boom)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        self.addCleanup(httpd.server_close)
        self.addCleanup(httpd.shutdown)
        code, out, _ = self.run_cli(f"http://127.0.0.1:{httpd.server_address[1]}", "check", "--json")
        self.assertEqual(code, 3)
        self.assertEqual(json.loads(out)["error"]["code"], "http")


class ConfigTests(Base):
    def test_refuses_without_provider(self):
        self.write_config(provider="")
        with OWStub(load("oura")) as stub:
            for args in (("health-day", "--json"), ("check", "--json")):
                code, out, _ = self.run_cli(stub.base, *args)
                self.assertEqual(code, 2)
                res = json.loads(out)
                self.assertEqual(res["error"]["code"], "no_provider")
                self.assertIn("fournisseur", res["error"]["message"])
            self.assertEqual(stub.log, [])        # aucun appel réseau

    def test_refuses_unknown_or_forbidden_provider(self):
        with OWStub(load("oura")) as stub:
            for provider in ("ouraa", "garmin", "strava"):
                self.write_config(provider=provider)
                code, out, _ = self.run_cli(stub.base, "health-day", "--json")
                self.assertEqual(code, 2, provider)
                expected = "no_provider" if provider == "ouraa" else "refused_provider"
                self.assertEqual(json.loads(out)["error"]["code"], expected, provider)
            self.assertEqual(stub.log, [])

    def test_not_enabled_when_source_is_primary(self):
        self.write_config("oura", source="primary")
        with OWStub(load("oura")) as stub:
            code, out, _ = self.run_cli(stub.base, "health-day", "--json")
            self.assertEqual(code, 2)
            self.assertEqual(json.loads(out)["error"]["code"], "not_enabled")
            self.assertEqual(stub.log, [])

    def test_missing_key_file_exits_2_without_path_leak(self):
        self.write_config("oura")
        with OWStub(load("oura")) as stub:
            code, out, err = self.run_cli(stub.base, "check", "--json", key_file=self.tmp / "absent.key")
            self.assertEqual(code, 2)
            self.assertEqual(json.loads(out)["error"]["code"], "key_unreadable")
            self.assertNotIn("absent.key", out + err)
            self.assertEqual(stub.log, [])

    def test_empty_base_url_exits_2(self):
        self.write_config("oura")
        code, out, _ = self.run_cli("", "check", "--json")
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(out)["error"]["code"], "no_base_url")

    def test_open_key_file_mode_warns(self):
        self.write_config("oura")
        os.chmod(self.key_file, 0o644)
        with OWStub(load("oura")) as stub:
            res = self.health_day(stub)
        self.assertIn("key_file_mode", [w["code"] for w in res["warnings"]])

    def test_bad_date_exits_2(self):
        self.write_config("oura")
        code, _, _ = self.run_cli("http://127.0.0.1:9", "health-day", "--date", "demain")
        self.assertEqual(code, 2)

    def test_human_output_has_no_json_and_no_key(self):
        self.write_config("oura")
        with OWStub(load("oura")) as stub:
            code, out, err = self.run_cli(stub.base, "health-day", "--date", DAY)
        self.assertEqual(code, 0)
        self.assertIn("Santé du 2026-10-05", out)
        self.assertIn("readiness", out)
        self.assertNotIn(FAKE_KEY, out + err)
        self.assertNotRegex(out, r"^\s*\{")


class CheckTests(Base):
    def test_check_nominal(self):
        self.write_config("oura")
        bundle = load("oura")
        bundle["connections"][0]["last_synced_at"] = (datetime.now(timezone.utc) - timedelta(hours=1)
                                                      ).strftime("%Y-%m-%dT%H:%M:%SZ")
        with OWStub(bundle) as stub:
            code, out, err = self.run_cli(stub.base, "check", "--json")
        self.assertEqual(code, 0, err)
        res = json.loads(out)
        self.assertEqual({k: res[k] for k in ("ok", "reachable", "auth", "provider", "provider_connected",
                                              "stale", "shape_ok", "tested_version")},
                         {"ok": True, "reachable": True, "auth": "ok", "provider": "oura",
                          "provider_connected": True, "stale": False, "shape_ok": True,
                          "tested_version": OW.TESTED_VERSION})
        self.assertEqual(res["user"], {"resolved": True, "count": 1})

    def test_check_detects_shape_change(self):
        self.write_config("oura")
        bundle = load("oura")
        del bundle["sleep"]["data"][0]["stages"]
        with OWStub(bundle) as stub:
            code, out, _ = self.run_cli(stub.base, "check", "--json")
        res = json.loads(out)
        self.assertEqual(code, 0)
        self.assertFalse(res["shape_ok"])
        self.assertFalse(res["ok"])
        self.assertIn("shape_mismatch", [w["code"] for w in res["warnings"]])

    def test_check_provider_not_connected(self):
        self.write_config("polar")
        with OWStub(load("oura")) as stub:        # la connexion servie est celle d'oura
            code, out, _ = self.run_cli(stub.base, "check", "--json")
        res = json.loads(out)
        self.assertEqual(code, 0)
        self.assertFalse(res["provider_connected"])
        self.assertFalse(res["ok"])


def at_tz(name):
    """Fuseau de la machine pour la durée d'un test (l'athlète en UTC−4, par exemple)."""
    class _Ctx:
        def __enter__(self):
            self.old = os.environ.get("TZ")
            os.environ["TZ"] = name
            time.tzset()

        def __exit__(self, *exc):
            if self.old is None:
                os.environ.pop("TZ", None)
            else:
                os.environ["TZ"] = self.old
            time.tzset()
    return _Ctx()


def shift_night(bundle, start, end, offset):
    sleep = bundle["sleep"]["data"][0]
    sleep["start_time"], sleep["end_time"], sleep["zone_offset"] = start, end, offset


class RealTimingTests(Base):
    """Horodatages tels que OW 0.9.0 les produit (relus dans les sources, commit épinglé)."""

    def ts_window(self, stub):
        q = next(q for p, q, _ in stub.log if p.endswith("/timeseries"))
        return OW.parse_dt(q["start_time"][0]), OW.parse_dt(q["end_time"][0])

    def test_oura_resting_hr_recorded_at_sleep_start_the_evening_before(self):
        # `lowest_heart_rate` -> resting_heart_rate à `start_dt` (début du sommeil, 23:05 locale la veille)
        self.write_config("oura")
        with OWStub(load("oura")) as stub:
            res = self.health_day(stub)
            start, _ = self.ts_window(stub)
        self.assertEqual(res["arc"]["resting_hr_bpm"], 47)
        self.assertNotIn("resting_hr_bpm", res["unavailable"])
        self.assertLessEqual(start, OW.parse_dt("2026-10-04T21:00:00Z"))      # début − 5 min, borne incluse

    def test_resting_hr_takes_the_night_sample_before_a_day_sample(self):
        self.write_config("oura")
        bundle = load("oura")
        day = {**bundle["timeseries"]["data"][0], "timestamp": "2026-10-05T10:00:00Z", "value": 60}
        bundle["timeseries"]["data"].append(day)
        with OWStub(bundle) as stub:
            res = self.health_day(stub)
        self.assertEqual(res["arc"]["resting_hr_bpm"], 47)

    def test_resting_hr_falls_back_to_local_date_without_night(self):
        self.write_config("oura")
        bundle = load("oura")
        bundle["sleep"]["data"] = []
        bundle["timeseries"]["data"][0]["timestamp"] = "2026-10-05T07:00:00Z"
        with OWStub(bundle) as stub:
            res = self.health_day(stub)
        self.assertEqual(res["arc"]["resting_hr_bpm"], 47)
        bundle["timeseries"]["data"][0]["timestamp"] = "2026-10-04T21:05:00Z"        # veille : pas de repli
        with OWStub(bundle) as stub:
            res = self.health_day(stub)
        self.assertNotIn("resting_hr_bpm", res["arc"])

    def test_oura_scores_at_local_midnight(self):
        self.write_config("oura")
        with OWStub(load("oura")) as stub:
            res = self.health_day(stub)
        self.assertEqual([(s["category"], s["value"]) for s in res["arc"]["provider_scores"]],
                         [("readiness", 82), ("sleep", 77)])

    def test_athlete_in_utc_minus_4(self):
        # Nuit 23:05 -> 06:45 locales (UTC−4) ; aucun score ne porte de zone_offset ; TZ de la machine = New York
        self.write_config("polar")
        bundle = load("polar")
        shift_night(bundle, "2026-10-05T03:05:00Z", "2026-10-05T10:45:00Z", "-04:00")
        sc = bundle["scores"]["data"]
        sc[0]["recorded_at"] = "2026-10-05T10:45:00Z"      # readiness : réveil
        sc[1]["recorded_at"] = "2026-10-05T00:00:00Z"      # Nightly Recharge : date naïve lue en UTC = 20:00 la veille
        sc[3]["recorded_at"] = "2026-10-05T03:05:00Z"      # sommeil : début de la nuit = 23:05 la veille
        with at_tz("America/New_York"), OWStub(bundle) as stub:
            res = self.health_day(stub)
        got = {s["category"]: s["value"] for s in res["arc"]["provider_scores"]}
        self.assertEqual(got, {"readiness": 7, "recovery": 4, "sleep": 80})
        self.assertNotIn("readiness", res["unavailable"])

    def test_sleep_score_of_another_night_is_not_attributed(self):
        self.write_config("polar")
        bundle = load("polar")
        sc = bundle["scores"]["data"]
        sc[3]["recorded_at"] = "2026-10-05T21:05:00Z"      # la nuit SUIVANTE (23:05 locale le jour D)
        with OWStub(bundle) as stub:
            res = self.health_day(stub)
        self.assertNotIn("sleep", [s["category"] for s in res["arc"]["provider_scores"]])
        sc[3]["recorded_at"] = "2026-10-03T21:05:00Z"      # la nuit précédente
        with OWStub(bundle) as stub:
            res = self.health_day(stub)
        self.assertNotIn("sleep", [s["category"] for s in res["arc"]["provider_scores"]])

    def test_date_only_score_uses_the_utc_date(self):
        self.write_config("polar")
        bundle = load("polar")
        bundle["scores"]["data"][1]["recorded_at"] = "2026-10-04T00:00:00Z"      # Nightly Recharge de la veille
        with OWStub(bundle) as stub:
            res = self.health_day(stub)
        self.assertNotIn("recovery", [s["category"] for s in res["arc"]["provider_scores"]])

    def test_polar_has_no_resting_hr(self):
        self.write_config("polar")
        with OWStub(load("polar")) as stub:
            res = self.health_day(stub)
        self.assertNotIn("resting_hr_bpm", res["arc"])
        self.assertIn("polar", res["unavailable"]["resting_hr_bpm"])


class SummaryHrvSourcesTests(Base):
    def multi_source(self):
        bundle = load("oura")
        bundle["connections"].append({**bundle["connections"][0], "id": "00000000-0000-4000-8000-0000000000d2",
                                      "provider": "apple"})
        base = bundle["timeseries"]["data"][0]
        bundle["timeseries"]["data"] += [
            {**base, "timestamp": "2026-10-05T00:00:00Z", "type": "heart_rate_variability_rmssd", "value": 40,
             "unit": "ms"},
            {**base, "timestamp": "2026-10-05T02:00:00Z", "type": "heart_rate_variability_rmssd", "value": 50,
             "unit": "ms"},
            {**base, "timestamp": "2026-10-05T01:00:00Z", "type": "heart_rate_variability_sdnn", "value": 70,
             "unit": "ms"},
        ]
        return bundle

    def test_other_connection_makes_the_summary_hrv_unusable(self):
        self.write_config("oura")
        with OWStub(self.multi_source()) as stub:
            res = self.health_day(stub)
            types = sorted(sum((q.get("types", []) for p, q, _ in stub.log if p.endswith("/timeseries")), []))
        self.assertEqual(res["arc"]["hrv_overnight_ms"], 45.0)          # série Oura, pas les 48.2 du résumé
        self.assertEqual(res["arc"]["hrv_sdnn_ms"], 70)
        codes = [w["code"] for w in res["warnings"]]
        self.assertIn("summary_hrv_multi_source", codes)
        self.assertIn("hrv_from_timeseries", codes)
        self.assertEqual(types, ["heart_rate_variability_rmssd", "heart_rate_variability_sdnn",
                                 "resting_heart_rate"])
        self.assert_contract(res["arc"])

    def test_multi_source_without_series_reports_unavailable(self):
        self.write_config("oura")
        bundle = self.multi_source()
        bundle["timeseries"]["data"] = bundle["timeseries"]["data"][:1]
        with OWStub(bundle) as stub:
            res = self.health_day(stub)
        self.assertNotIn("hrv_overnight_ms", res["arc"])
        self.assertIn("hrv_overnight_ms", res["unavailable"])

    def test_sole_connection_keeps_the_summary_hrv(self):
        self.write_config("oura")
        with OWStub(load("oura")) as stub:
            res = self.health_day(stub)
        self.assertEqual(res["arc"]["hrv_overnight_ms"], 48.2)
        self.assertNotIn("summary_hrv_multi_source", [w["code"] for w in res["warnings"]])


class FreshnessEdgeTests(Base):
    def test_sdk_provider_never_synced_is_unknown_not_stale(self):
        self.write_config("apple")
        bundle = load("apple")
        bundle["connections"][0]["last_synced_at"] = None
        with OWStub(bundle) as stub:
            res = self.health_day(stub)
        self.assertEqual(res["freshness"]["status"], "active")
        self.assertIsNone(res["freshness"]["stale"])
        self.assertIn("freshness_unknown", [w["code"] for w in res["warnings"]])
        self.assertNotIn("stale", [w["code"] for w in res["warnings"]])

    def test_cloud_provider_never_synced_is_stale(self):
        self.write_config("oura")
        bundle = load("oura")
        bundle["connections"][0]["last_synced_at"] = None
        with OWStub(bundle) as stub:
            res = self.health_day(stub)
        self.assertTrue(res["freshness"]["stale"])


class TimeoutAndTransportTests(Base):
    def slow_server(self, delay, counter):
        class Slow(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                counter.append(self.path)
                time.sleep(delay)
                try:
                    body = b"{}"
                    self.send_response(200)
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                except OSError:
                    pass

        httpd = ThreadingHTTPServer(("127.0.0.1", 0), Slow)
        httpd.daemon_threads = True
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        self.addCleanup(httpd.server_close)
        self.addCleanup(httpd.shutdown)
        return f"http://127.0.0.1:{httpd.server_address[1]}"

    def test_timeout_option_bounds_the_wait_and_is_not_retried(self):
        self.write_config("oura")
        seen: list = []
        base = self.slow_server(1.5, seen)
        started = time.monotonic()
        code, out, _ = self.run_cli(base, "check", "--json", "--timeout", "0.3")
        elapsed = time.monotonic() - started
        self.assertEqual(code, 3)
        self.assertEqual(json.loads(out)["error"]["code"], "unreachable")
        self.assertLess(elapsed, 1.2)
        self.assertEqual(len(seen), 1)          # un délai n'est jamais rejoué

    def test_timeout_env_and_global_position(self):
        self.write_config("oura")
        seen: list = []
        base = self.slow_server(1.5, seen)
        code, _, _ = self.run_cli(base, "--timeout", "0.3", "health-day", "--json")
        self.assertEqual(code, 3)
        code, _, _ = self.run_cli(base, "check", "--json", env={"ARC_OW_TIMEOUT": "0.3"})
        self.assertEqual(code, 3)
        self.assertEqual(len(seen), 2)

    def test_bad_timeout_exits_2(self):
        self.write_config("oura")
        for value in ("0", "-1", "abc", "nan", "1000"):
            code, _, _ = self.run_cli("http://127.0.0.1:9", "check", "--timeout", value)
            self.assertEqual(code, 2, value)
        code, out, _ = self.run_cli("http://127.0.0.1:9", "check", "--json", env={"ARC_OW_TIMEOUT": "zzz"})
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(out)["error"]["code"], "bad_timeout")

    def test_connection_error_is_retried_exactly_once(self):
        self.write_config("oura")
        hits: list = []

        class Drop(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                hits.append(self.path)
                self.connection.close()          # coupure sans réponse

        httpd = ThreadingHTTPServer(("127.0.0.1", 0), Drop)
        httpd.daemon_threads = True
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        self.addCleanup(httpd.server_close)
        self.addCleanup(httpd.shutdown)
        code, out, _ = self.run_cli(f"http://127.0.0.1:{httpd.server_address[1]}", "check", "--json")
        self.assertEqual(code, 3)
        self.assertEqual(json.loads(out)["error"]["code"], "unreachable")
        self.assertEqual(len(hits), 2)

    def config_warnings(self, url):
        self.write_config("oura")
        with mock.patch.dict(os.environ, {"ARC_OW_BASE_URL": url, "ARC_OW_API_KEY_FILE": str(self.key_file)}):
            return [w["code"] for w in OW._config(str(self.ws))["warnings"]]

    def test_insecure_transport_warning(self):
        for url in ("http://ow.example.com", "http://1.1.1.1:8000", "http://8.8.8.8"):
            self.assertEqual(self.config_warnings(url), ["insecure_transport"], url)
        for url in ("http://127.0.0.1:8000", "http://localhost:8000", "http://192.168.1.20:8000",
                    "http://10.0.0.5", "http://[::1]:8000", "http://open-wearables:8000", "http://ow.lan",
                    "https://ow.example.com"):
            self.assertEqual(self.config_warnings(url), [], url)

    def test_loopback_http_has_no_transport_warning_in_the_output(self):
        self.write_config("oura")
        with OWStub(load("oura")) as stub:
            res = self.health_day(stub)
        self.assertNotIn("insecure_transport", [w["code"] for w in res["warnings"]])


class PinTests(unittest.TestCase):
    def test_pin_constants(self):
        text = (REPO / "scripts/arc_openwearables.py").read_text(encoding="utf-8")
        self.assertRegex(text, r'(?m)^OW_REF = "ff8527a52ad8a96cd1ebe8c19344295c934ae9dc"$')
        self.assertEqual(OW.OW_TAG, "0.9.0")
        self.assertEqual(OW.TESTED_VERSION, OW.OW_TAG)

    def test_score_table_matches_pinned_ranges(self):
        # Recopie de `HEALTH_SCORE_RANGES` (OW 0.9.0) : tout changement doit être délibéré.
        self.assertEqual(OW.SCORE_RANGES[("readiness", "polar")], (0, 10))
        self.assertEqual(OW.SCORE_RANGES[("recovery", "polar")], (1, 6))
        self.assertNotIn(("sleep", "samsung"), OW.SCORE_RANGES)
        self.assertFalse([k for k in OW.SCORE_RANGES if k[0] == "strain" or k[1] == "internal"])

    def test_module_docstring_lists_endpoints(self):
        for endpoint in ("/users/{user_id}/connections", "/summaries/sleep", "/timeseries", "/health-scores"):
            self.assertIn(endpoint, OW.__doc__)
        self.assertTrue(re.search(r"\bASSUMPTIONS\b", (REPO / "scripts/arc_openwearables.py").read_text()))


if __name__ == "__main__":
    unittest.main()
