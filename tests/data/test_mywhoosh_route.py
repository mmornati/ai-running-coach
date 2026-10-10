"""Palier D — `skills/mywhoosh-route/scripts/mywhoosh_route.py` : aplatissement du
catalogue MyWhoosh, jeton (mode 600, échéance), modèle de temps, sélection des
parcours (boucles, difficulté, intensité), corps d'une tâche de calendrier et
garde-fous d'écriture. Aucun appel réseau."""

from __future__ import annotations

import base64
import io
import json
import os
import stat
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "skills/mywhoosh-route/scripts"))
import mywhoosh_route as M  # noqa: E402

ROUTES = [
    {"id": 1, "name": "Flat 12k", "world": "T", "world_id": 9, "distance_m": 12300, "elevation_gain_m": 24,
     "difficulty": 1, "route_type": "E_Circuit", "loop": True},
    {"id": 2, "name": "Rolling 31k", "world": "T", "world_id": 9, "distance_m": 31400, "elevation_gain_m": 332,
     "difficulty": 3, "route_type": "E_Circuit", "loop": True},
    {"id": 3, "name": "Climb", "world": "T", "world_id": 9, "distance_m": 16500, "elevation_gain_m": 735,
     "difficulty": 4, "route_type": "E_Sprint", "loop": False},
    {"id": 4, "name": "Too long", "world": "T", "world_id": 9, "distance_m": 60000, "elevation_gain_m": 100,
     "difficulty": 2, "route_type": "E_Circuit", "loop": True},
    {"id": 5, "name": "Point to point 12k", "world": "T", "world_id": 9, "distance_m": 12300,
     "elevation_gain_m": 20, "difficulty": 1, "route_type": "E_Sprint", "loop": False},
    {"id": 6, "name": "Event stage", "world": "UCI", "world_id": 7, "distance_m": 35000, "elevation_gain_m": 50,
     "difficulty": 0, "route_type": "E_Circuit", "loop": True},
]

CALIBRATION = {
    "status": "ok", "weight_kg": 73.8, "equipment": {"bike_mass_kg": 8.5},
    "fit": {"intercept_w": -79.0, "slope_w_per_bpm": 1.85, "resid_sd_w": 17.0, "windows": 600,
            "hr_range_bpm": [91, 150]},
    "zones": [{"zone": 1, "bounds_bpm": [109, 123], "power_w": [123, 149], "extrapolated": False},
              {"zone": 2, "bounds_bpm": [123, 136], "power_w": [149, 174], "extrapolated": False}],
}


def _jwt(exp: int) -> str:
    payload = base64.urlsafe_b64encode(json.dumps({"exp": exp}).encode()).decode().rstrip("=")
    return f"h.{payload}.s"


class TestFlattenRoutes(unittest.TestCase):
    def test_keeps_free_ride_routes_with_world_and_loop(self):
        worlds = [{"WorldName": "Arabia", "WorldId": 1, "Routes": [
            {"Id": 1, "Name": "Jabel Hafeet ", "Km": 16.5, "Elevation": 735, "Difficulty": 4,
             "RouteType": "E_Sprint", "bIsAvailableForFreeRide": True},
            {"Id": 22, "Name": "Al Qudra", "Km": 12.3, "Elevation": 24, "Difficulty": 1, "RouteType": "E_Circuit"},
            {"Id": 2, "Name": "Event only", "Km": 10, "Elevation": 10, "bIsAvailableForFreeRide": False},
            {"Id": 3, "Name": "No km", "Elevation": 10},
        ]}]
        out = M.flatten_routes(worlds)
        self.assertEqual([r["id"] for r in out], [1, 22])
        self.assertEqual(out[0]["name"], "Jabel Hafeet")
        self.assertEqual(out[0]["world_id"], 1)
        self.assertFalse(out[0]["loop"])
        self.assertTrue(out[1]["loop"])

    def test_empty_response(self):
        self.assertEqual(M.flatten_routes(None), [])


class TestToken(unittest.TestCase):
    def test_saved_with_mode_600_and_read_back(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "sub" / "token.json"
            token = _jwt(2_000_000_000)
            M.save_token(path, token)
            self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600)
            self.assertEqual(M.load_token(path, now=1_000_000_000), token)

    def test_expired_or_missing_token_is_ignored(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "token.json"
            self.assertIsNone(M.load_token(path))
            M.save_token(path, _jwt(1_000_000_100))
            self.assertIsNone(M.load_token(path, now=1_000_000_000))   # échéance dans < 5 min

    def test_device_id_is_stable_across_logins(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "token.json"
            first = M.device_id(path)                      # aucun fichier : nouvel identifiant
            M.save_token(path, _jwt(1_000_000_100), first)
            self.assertEqual(M.device_id(path), first)     # gardé, même jeton expiré
            payload = base64.urlsafe_b64encode(json.dumps({"exp": 1, "deviceId": "dev-42"}).encode()).decode()
            path.write_text(json.dumps({"access_token": f"h.{payload.rstrip('=')}.s"}))
            self.assertEqual(M.device_id(path), "dev-42")  # ancien fichier : repris du jeton

    def test_login_reuses_device_id(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "token.json"
            M.save_token(path, _jwt(1_000_000_100), "dev-7")

            class Args:
                token_file = path
                username = "athlete@example.org"
            sent = {}

            def fake(url, **kw):
                sent.update(kw.get("body") or {})
                return {"Success": True, "AccessToken": _jwt(2_000_000_000)}
            with patch.object(M, "_request", side_effect=fake), patch("getpass.getpass", return_value="x"), \
                    patch.object(sys.stdin, "isatty", return_value=True):
                self.assertTrue(M.login(Args()))
            self.assertEqual(sent["DeviceId"], "dev-7")
            self.assertEqual(json.loads(path.read_text())["device_id"], "dev-7")

    def test_non_interactive_login_never_prompts(self):
        class Args:
            token_file = Path("/nonexistent/token.json")
        with redirect_stderr(io.StringIO()), patch("builtins.input") as ask, patch("getpass.getpass") as pwd:
            self.assertIsNone(M.login(Args(), interactive=False))
        ask.assert_not_called()
        pwd.assert_not_called()


class TestModel(unittest.TestCase):
    def test_matches_published_samples_within_band(self):
        # Temps publiés (mywhooshinfo.com, Alula Adventure Loop 31,4 km / 332 m).
        for watts, wkg, secs in [(95, 1.6, 5182), (206, 3.0, 3493), (232, 3.2, 3250), (297, 4.0, 3019)]:
            est = M.route_time_s(watts, watts / wkg, 31400, 332)
            self.assertLess(abs(est - secs) / secs, M.BAND, (watts, est, secs))

    def test_climbing_and_bike_mass_cost_time(self):
        flat = M.route_time_s(150, 74, 20000, 0)
        hilly = M.route_time_s(150, 74, 20000, 400)
        heavy = M.route_time_s(150, 74, 20000, 400, bike_kg=12)
        self.assertGreater(hilly, flat)
        self.assertGreater(heavy, hilly)

    def test_session_power_below_target(self):
        self.assertLess(M.session_power(160, 70, 5, 5), 160)


class TestSuggest(unittest.TestCase):
    def _run(self, **kw):
        args = dict(duration_min=70, avg_power_w=149, rider_kg=73.8)
        args.update(kw)
        return M.suggest(ROUTES, **args)

    def test_fits_and_ranks_closest_first(self):
        res = self._run(max_m_per_km=12.0)
        names = [r["name"] for r in res]
        self.assertNotIn("Too long", names)
        self.assertNotIn("Climb", names)
        for r in res:
            self.assertLessEqual(r["predicted_s"], 75 * 60)
            self.assertGreaterEqual(r["predicted_s"], 0.85 * 70 * 60)
        fills = [abs(r["fill"] - 1) for r in res]
        self.assertEqual(fills, sorted(fills))

    def test_laps_only_on_loops(self):
        res = self._run()
        flat = next(r for r in res if r["name"] == "Flat 12k")
        self.assertGreater(flat["laps"], 1)
        self.assertNotIn("Point to point 12k", [r["name"] for r in res])

    def test_event_routes_excluded(self):
        self.assertNotIn("Event stage", [r["name"] for r in self._run()])

    def test_difficulty_filter(self):
        names = [r["name"] for r in self._run(max_difficulty=1)]
        self.assertNotIn("Rolling 31k", names)
        self.assertIn("Flat 12k", names)

    def test_labels_and_trace(self):
        r = self._run()[0]
        label = M.garmin_label(r, 70, 2)
        self.assertEqual(label, f"HT Z2 70min - {r['name']}" + (f" x{r['laps']}" if r["laps"] > 1 else ""))
        trace = M.virtual_route(r, 155.4)
        self.assertEqual(trace["platform"], "mywhoosh")
        self.assertEqual(trace["target_power_w"], 155)
        self.assertEqual(trace["distance_m"], r["distance_m"] * r["laps"])


class TestCliSuggest(unittest.TestCase):
    def _cli(self, *extra):
        with tempfile.TemporaryDirectory() as d:
            cache = Path(d, "routes.json")
            cache.write_text(json.dumps({"routes": ROUTES}))
            cal = Path(d, "cal.json")
            cal.write_text(json.dumps(CALIBRATION))
            out, err = io.StringIO(), io.StringIO()
            with redirect_stdout(out), redirect_stderr(err):
                code = M.main(["--cache", str(cache), "suggest", "--duration-min", "70",
                               "--calibration", str(cal), *extra])
            return code, out.getvalue(), err.getvalue()

    def test_uses_zone_weight_and_bike_from_calibration(self):
        code, out, _ = self._cli("--intensity", "endurance")
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertEqual(data["hr_band_bpm"], [123, 136])
        self.assertEqual(data["weight_kg"], 73.8)
        self.assertEqual(data["bike_kg"], 8.5)
        self.assertEqual(data["max_difficulty"], 2)
        self.assertTrue(all("garmin_workout_name" in r and "virtual_route" in r for r in data["routes"]))

    def test_low_half_lowers_target(self):
        full = json.loads(self._cli()[1])["target_power_w"]
        low = json.loads(self._cli("--low-half")[1])["target_power_w"]
        self.assertLess(low, full)

    def test_refused_calibration_gives_no_suggestion(self):
        with tempfile.TemporaryDirectory() as d:
            cache = Path(d, "routes.json")
            cache.write_text(json.dumps({"routes": ROUTES}))
            cal = Path(d, "cal.json")
            cal.write_text(json.dumps({"status": "no_power_samples", "fit": None, "reason": "aucune séance"}))
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                code = M.main(["--cache", str(cache), "suggest", "--duration-min", "70",
                               "--calibration", str(cal), "--weight-kg", "70"])
            self.assertEqual(code, 2)


class TestSchedule(unittest.TestCase):
    def test_task_body(self):
        body = M.build_task(route=ROUTES[0], date="2026-10-11", start="10:00", duration_min=70, name="HT")
        self.assertEqual(body["TaskType"], "E_FreeRide")
        self.assertEqual(body["TaskTypeId"], "1")
        self.assertEqual(body["MapId"], 9)
        self.assertEqual(body["TaskEndEpochTime"] - body["TaskStartedTimeEpoc"], 70 * 60)

    def test_dry_run_by_default_never_calls_network(self):
        with tempfile.TemporaryDirectory() as d:
            cache = Path(d, "routes.json")
            cache.write_text(json.dumps({"routes": ROUTES}))
            out = io.StringIO()
            with patch.object(M, "_request") as req, redirect_stdout(out), redirect_stderr(io.StringIO()):
                code = M.main(["--cache", str(cache), "schedule", "--route-id", "1", "--date", "2026-10-11",
                               "--duration-min", "70"])
            self.assertEqual(code, 0)
            req.assert_not_called()
            self.assertTrue(json.loads(out.getvalue())["dry_run"])

    def test_write_refused_without_terminal(self):
        with tempfile.TemporaryDirectory() as d:
            cache = Path(d, "routes.json")
            cache.write_text(json.dumps({"routes": ROUTES}))
            with patch.object(M, "_request") as req, patch.object(sys.stdin, "isatty", return_value=False), \
                    redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                code = M.main(["--cache", str(cache), "schedule", "--route-id", "1", "--date", "2026-10-11",
                               "--duration-min", "70", "--yes"])
            self.assertEqual(code, 2)
            req.assert_not_called()


if __name__ == "__main__":
    unittest.main()
