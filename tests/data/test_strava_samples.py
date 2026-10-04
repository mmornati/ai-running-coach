"""Palier D — source Strava (#164) : flux par seconde → échantillons normalisés → mêmes KPI que le FIT.

Aucune donnée Strava réelle (accord API Strava : rien dans le dépôt public) : les flux sont
FABRIQUÉS depuis la séance synthétique à vérité connue (`tests/lib/synthetic.sample_session`),
au format que l'API Strava documente (`key_by_type=true` : `{"time": {"data": [...]}, ...}`).
Aucun appel réseau : l'ouvreur HTTP est injecté.

Critère central (`TestParityWithGarmin`) : les MÊMES échantillons donnent EXACTEMENT les mêmes KPI
(zones, GAP, découplage, VAM, descente, durabilité, énergie) qu'ils viennent d'un identifiant
Garmin ou Strava — seul l'identifiant change.
"""

from __future__ import annotations

import io
import json
import os
import stat
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "skills/fit-download/scripts"))
sys.path.insert(0, str(REPO))
import arc_climb_match as VM  # noqa: E402
import arc_index as I  # noqa: E402
import arc_samples as S  # noqa: E402
import download_fit as D  # noqa: E402
from tests.data.test_intervals_samples import KPI_COLUMNS, Workspace, _hilly_records  # noqa: E402

STRAVA_ID = "s9000000164"
GARMIN_ID = 90000000164


def to_streams(records: list, foot: bool = True) -> dict:
    """Séance normalisée → flux Strava `key_by_type=true` (inverse de `strava_streams_to_records` :
    la cadence est celle d'UN pied, que le convertisseur double pour un sport à pied)."""
    def col(key, f=lambda v: v):
        return {"data": [f(r[key]) for r in records]}
    return {
        "time": col("t_s"), "distance": col("distance_m"), "altitude": col("altitude_m"),
        "heartrate": col("hr_bpm"), "velocity_smooth": col("speed_ms"),
        "cadence": col("cadence_spm", lambda v: v / 2 if foot else v),
    }


class TestConverter(unittest.TestCase):
    def test_maps_every_stream_to_its_column(self):
        streams = {"time": {"data": [0, 1, 2]}, "distance": {"data": [0.0, 2.5, 5.0]},
                   "altitude": {"data": [100.0, 100.5, 101.0]}, "heartrate": {"data": [120, 121, 122]},
                   "velocity_smooth": {"data": [2.5, 2.5, 2.5]}, "cadence": {"data": [80, 81, 82]},
                   "latlng": {"data": [[45.0, 6.0], [45.0001, 6.0], [45.0002, 6.0]]}}
        recs = S.strava_streams_to_records(streams, "TrailRun")
        self.assertEqual([r["t_s"] for r in recs], [0, 1, 2])
        self.assertEqual(recs[1]["distance_m"], 2.5)
        self.assertEqual(recs[1]["hr_bpm"], 121)
        self.assertEqual(recs[1]["speed_ms"], 2.5)
        self.assertEqual(recs[1]["cadence_spm"], 162)          # doublée : sport à pied
        self.assertEqual((recs[2]["lat_deg"], recs[2]["lon_deg"]), (45.0002, 6.0))

    def test_cadence_is_not_doubled_for_a_ride(self):
        recs = S.strava_streams_to_records({"time": {"data": [0]}, "cadence": {"data": [90]}}, "Ride")
        self.assertEqual(recs[0]["cadence_spm"], 90)

    def test_list_form_of_the_api_is_accepted(self):
        streams = [{"type": "time", "data": [0, 1]}, {"type": "heartrate", "data": [100, 101]}]
        self.assertEqual([r["hr_bpm"] for r in S.strava_streams_to_records(streams, "Run")], [100, 101])

    def test_no_time_stream_means_no_samples(self):
        self.assertEqual(S.strava_streams_to_records({"heartrate": {"data": [1, 2]}}, "Run"), [])
        self.assertEqual(S.strava_streams_to_records({}, "Run"), [])
        self.assertEqual(S.strava_streams_to_records(None, "Run"), [])

    def test_a_stream_of_the_wrong_length_is_dropped_whole(self):
        streams = {"time": {"data": [0, 1, 2]}, "heartrate": {"data": [120, 121]},
                   "distance": {"data": [0, 1, 2]}}
        recs = S.strava_streams_to_records(streams, "Run")
        self.assertEqual(len(recs), 3)
        self.assertTrue(all(r["hr_bpm"] is None for r in recs))
        self.assertEqual([r["distance_m"] for r in recs], [0, 1, 2])

    def test_missing_streams_are_none_never_invented(self):
        recs = S.strava_streams_to_records({"time": {"data": [0, 1]}}, "Run")
        for key in ("distance_m", "altitude_m", "hr_bpm", "speed_ms", "cadence_spm", "lat_deg", "lon_deg"):
            self.assertTrue(all(r[key] is None for r in recs), key)


class TestActivityRef(unittest.TestCase):
    def test_parse_activity_ref_accepts_the_strava_space(self):
        self.assertEqual(S.parse_activity_ref("s12345678901"), "s12345678901")
        for bad in ("s", "S1", "s12a", "ss1"):
            self.assertIsNone(S.parse_activity_ref(bad), bad)

    def test_file_name_carries_the_strava_id(self):
        self.assertEqual(S.sample_file_activity_id(Path("activities/fit/s42.json")), "s42")

    def test_contract_validates_the_prefixed_id_only(self):
        import arc_contract as C
        base = {"arc": 1, "kind": "activity", "date": "2026-09-29", "sport": "trail", "duration_s": 60}
        errors, _warnings = C.validate({**base, "strava_activity_id": "s123"})
        self.assertEqual(errors, [])
        for bad in (123, "123", "s", "i123"):
            errors, _warnings = C.validate({**base, "strava_activity_id": bad})
            self.assertTrue(any("strava_activity_id" in e for e in errors), bad)

    def test_climb_seed_is_disjoint_from_garmin_and_intervals(self):
        s, i = VM.segment_seed("s123"), VM.segment_seed("i123")
        self.assertNotEqual(s, i)
        self.assertGreater(s, 10 ** 11)
        self.assertLess(s * VM.SEGMENT_ID_CLIMB_MULTIPLIER + 9999, 2 ** 53)
        with self.assertRaises(ValueError):
            VM.segment_seed("s")


class TestCycleWithStravaSource(unittest.TestCase):
    """#166 × #164 : Strava n'expose aucune donnée de cycle — tout mode source retombe sur manual."""

    def test_source_modes_fall_back_to_manual(self):
        import arc_cycle
        for mode in ("garmin", "intervals", "manual"):
            self.assertEqual(arc_cycle.effective_source(mode, "strava"), "manual", mode)


class TestParityWithGarmin(Workspace):
    """Séance Garmin vs séance Strava dont les flux sont dérivés des mêmes échantillons."""

    def write_strava_activity(self, day):
        import json as _j
        data = {"arc": 1, "kind": "activity", "date": day, "sport": "trail", "duration_s": 6000,
                "distance_m": 15000, "strava_activity_id": STRAVA_ID}
        self.write(f"activities/{day}_trail.md", f"# Séance\n\n```arc\n{_j.dumps(data)}\n```\n")

    def setUp(self):
        super().setUp()
        records = _hilly_records()
        self.write_profile()
        self.write_activity("2026-09-28", intervals_id=None, garmin_id=GARMIN_ID)
        self.write_strava_activity("2026-09-29")
        self.write_fit(GARMIN_ID, records)
        converted = S.strava_streams_to_records(to_streams(records), "TrailRun")
        self.write_fit(STRAVA_ID, converted)
        self.index()
        self.garmin = self.activity("garmin_activity_id", GARMIN_ID)
        self.strava = self.activity("strava_activity_id", STRAVA_ID)

    def test_the_strava_file_is_linked_by_its_own_column(self):
        stored = self.conn.execute(
            "SELECT DISTINCT garmin_activity_id, intervals_activity_id, strava_activity_id "
            "FROM activity_sample WHERE strava_activity_id IS NOT NULL").fetchall()
        self.assertEqual([tuple(r) for r in stored], [(None, None, STRAVA_ID)])

    def test_every_kpi_column_matches(self):
        for col in KPI_COLUMNS:
            with self.subTest(col=col):
                self.assertEqual(self.strava[col], self.garmin[col])
        self.assertIsNotNone(self.strava["gap_pace_s_km"])
        self.assertIsNotNone(self.strava["best_climb_vam_elapsed_m_h"])
        self.assertIsNotNone(self.strava["decoupling_pct"])

    def test_zone_time_and_energy_match(self):
        def zones(i):
            return dict(self.conn.execute(
                "SELECT zone, seconds FROM hr_zone_time WHERE activity_id = ?", (i,)).fetchall())

        def kcal(i):
            return self.conn.execute(
                "SELECT model_kcal FROM activity_energy WHERE activity_id = ?", (i,)).fetchone()[0]
        self.assertTrue(zones(self.strava["id"]))
        self.assertEqual(zones(self.strava["id"]), zones(self.garmin["id"]))
        self.assertIsNotNone(kcal(self.strava["id"]))
        self.assertEqual(kcal(self.strava["id"]), kcal(self.garmin["id"]))

    def test_per_activity_reports_accept_the_strava_id(self):
        conf = I.settings(I.load_config(self.ws))
        for name, report in {
            "zones": I.activity_zone_report(self.conn, conf, STRAVA_ID),
            "gap": I.activity_gap_report(self.conn, STRAVA_ID),
            "decoupling": I.activity_decoupling_report(self.conn, STRAVA_ID),
            "vam": I.activity_climb_report(self.conn, STRAVA_ID),
            "durability": I.activity_durability_report(self.conn, STRAVA_ID),
        }.items():
            with self.subTest(report=name):
                self.assertEqual(report["strava_activity_id"], STRAVA_ID)
                self.assertNotEqual(report.get("reason_code"), "unknown_activity")

    def test_cli_accepts_the_strava_id(self):
        out = self.cli("samples", STRAVA_ID)
        self.assertEqual(out["strava_activity_id"], STRAVA_ID)
        self.assertNotIn("garmin_activity_id", out)


# ---------------------------------------------------------------------------
# Téléchargeur : jetons, rafraîchissement, requêtes (HTTP injecté)
# ---------------------------------------------------------------------------

class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _http_error(code):
    return urllib.error.HTTPError("https://www.strava.com/x", code, "err", {}, io.BytesIO(b"SECRET-BODY"))


def _router(routes: dict, calls: list):
    """`routes` : {sous-chaîne d'URL: octets | Exception | liste (réponses successives)}."""
    def opener(req, timeout=None):
        calls.append(req)
        for needle, body in routes.items():
            if needle in req.full_url:
                if isinstance(body, list):
                    body = body.pop(0)
                if isinstance(body, Exception):
                    raise body
                return _Resp(body)
        raise AssertionError(f"route inattendue {req.full_url}")
    return opener


class StravaDownloadCase(unittest.TestCase):
    NOW = 1_800_000_000.0

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.cfg = self.root / "config.json"

    def tearDown(self):
        self.tmp.cleanup()

    def write_cfg(self, **over):
        data = {"clientId": "cid", "clientSecret": "SECRET-CLIENT", "accessToken": "ACC1",
                "refreshToken": "REF1", "expiresAt": self.NOW + 3600, "unrelated": "garde-moi"}
        data.update(over)
        self.cfg.write_text(json.dumps(data), encoding="utf-8")

    def tokens(self, opener=None):
        return D.StravaTokens(self.cfg, opener=opener, now=lambda: self.NOW)


class TestStravaTokens(StravaDownloadCase):
    FRESH = json.dumps({"access_token": "ACC2", "refresh_token": "REF2", "expires_at": 1_800_007_200}).encode()

    def test_missing_tokens_is_an_explicit_error_without_secrets(self):
        with self.assertRaises(D.StravaError) as cm:
            self.tokens()
        self.assertIn("connect-strava", str(cm.exception))

    def test_valid_token_is_used_without_any_refresh(self):
        self.write_cfg()
        calls: list = []
        self.assertEqual(self.tokens(_router({}, calls)).access_token, "ACC1")
        self.assertEqual(calls, [])

    def test_expired_token_is_refreshed_and_the_rotated_pair_is_persisted(self):
        self.write_cfg(expiresAt=self.NOW - 10)
        calls: list = []
        t = self.tokens(_router({"oauth/token": self.FRESH}, calls))
        self.assertEqual(t.access_token, "ACC2")
        body = calls[0].data.decode()
        self.assertIn("grant_type=refresh_token", body)
        self.assertIn("refresh_token=REF1", body)
        saved = json.loads(self.cfg.read_text(encoding="utf-8"))
        self.assertEqual((saved["accessToken"], saved["refreshToken"], saved["expiresAt"]),
                         ("ACC2", "REF2", 1_800_007_200))
        self.assertEqual(saved["clientId"], "cid")
        self.assertEqual(saved["unrelated"], "garde-moi", "les autres clés du fichier du MCP sont conservées")
        self.assertEqual(stat.S_IMODE(self.cfg.stat().st_mode), 0o600)
        self.assertEqual([p.name for p in self.root.iterdir()], ["config.json"], "aucun fichier temporaire")

    def test_refresh_failure_never_leaks_secrets(self):
        self.write_cfg(expiresAt=self.NOW - 10)
        t = self.tokens(_router({"oauth/token": _http_error(400)}, []))
        with self.assertRaises(D.StravaError) as cm:
            t.access_token
        msg = str(cm.exception)
        for secret in ("SECRET-CLIENT", "REF1", "ACC1", "SECRET-BODY"):
            self.assertNotIn(secret, msg)
        self.assertEqual(json.loads(self.cfg.read_text())["refreshToken"], "REF1", "fichier inchangé")

    def test_missing_client_credentials_cannot_refresh(self):
        self.write_cfg(expiresAt=self.NOW - 10, clientSecret="")
        with self.assertRaises(D.StravaError):
            self.tokens().access_token


class TestStravaDownload(StravaDownloadCase):
    META = json.dumps({"id": 9000000164, "sport_type": "TrailRun", "manual": False}).encode()

    def streams(self):
        records = _hilly_records()[:30]
        return json.dumps(to_streams(records)).encode(), records

    def test_writes_the_canonical_copy_under_the_prefixed_id(self):
        self.write_cfg()
        body, records = self.streams()
        calls: list = []
        out = self.root / "activities"
        path = D._download_one_strava("s9000000164", out, self.tokens(), opener=_router({
            "/streams": body, "/activities/9000000164": self.META}, calls))
        data = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(path, out / "fit" / "s9000000164.json")
        self.assertEqual(data["activity_id"], "s9000000164")
        self.assertEqual(len(data["records"]), len(records))
        self.assertEqual(data["records"][5]["cadence_spm"], records[5]["cadence_spm"])
        self.assertTrue(all(c.get_header("Authorization") == "Bearer ACC1" for c in calls))
        self.assertIn("key_by_type=true", calls[1].full_url)
        self.assertIn("*", (out / "fit" / ".gitignore").read_text(encoding="utf-8"))

    def test_a_401_refreshes_once_then_retries(self):
        self.write_cfg()
        body, _ = self.streams()
        calls: list = []
        opener = _router({
            "oauth/token": TestStravaTokens.FRESH,
            "/streams": body,
            "/activities/9000000164": [_http_error(401), self.META]}, calls)
        D._download_one_strava("s9000000164", self.root, self.tokens(opener), opener=opener)
        self.assertEqual(json.loads(self.cfg.read_text())["accessToken"], "ACC2")

    def test_manual_activity_and_missing_streams_are_unavailable_not_failures(self):
        self.write_cfg()
        manual = json.dumps({"manual": True, "sport_type": "Run"}).encode()
        with self.assertRaises(D.StravaUnavailable):
            D._download_one_strava("s1", self.root, self.tokens(), opener=_router({"/activities/1": manual}, []))
        with self.assertRaises(D.StravaUnavailable):
            D._download_one_strava("s1", self.root, self.tokens(), opener=_router({
                "/streams": _http_error(404), "/activities/1": self.META}, []))
        with self.assertRaises(D.StravaUnavailable):
            D._download_one_strava("s1", self.root, self.tokens(), opener=_router({
                "/streams": b"{}", "/activities/1": self.META}, []))
        self.assertFalse((self.root / "fit").exists())

    def test_unprefixed_id_is_rejected_without_any_request(self):
        self.write_cfg()
        calls: list = []
        with self.assertRaises(D.StravaUnavailable):
            D._download_one_strava("9000000164", self.root, self.tokens(), opener=_router({}, calls))
        self.assertEqual(calls, [])

    def test_http_errors_have_dedicated_messages(self):
        self.write_cfg()
        for code, needle in ((403, "activity:read_all"), (429, "100 requêtes de lecture")):
            with self.subTest(code=code):
                with self.assertRaises(D.StravaError) as cm:
                    D._download_one_strava("s1", self.root, self.tokens(), opener=_router({
                        "/activities/1": _http_error(code)}, []))
                self.assertNotIsInstance(cm.exception, D.StravaUnavailable)
                self.assertIn(needle, str(cm.exception))
                self.assertNotIn("SECRET", str(cm.exception))

    def test_download_all_counts_unavailable_apart_from_failures(self):
        counts = D._download_all(["s1", "s2"], lambda a: (_ for _ in ()).throw(
            D.StravaUnavailable("x") if a == "s1" else D.StravaError("y")), lambda a: False)
        self.assertEqual((counts["unavailable"], counts["failed"]), (1, 1))


class TestStravaCli(unittest.TestCase):
    def test_arc_id_and_dir_scan(self):
        md = '# x\n\n```arc\n{"strava_activity_id": "s42"}\n```\n'
        self.assertEqual(D._activity_id_from_arc(md, "strava"), "s42")
        self.assertIsNone(D._activity_id_from_arc(md, "garmin"))
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "a.md").write_text(md, encoding="utf-8")
            self.assertEqual(D._ids_from_dir(Path(tmp), "strava"), ["s42"])

    def test_strava_is_a_known_source_and_skip_uses_the_normalised_copy(self):
        self.assertIn("strava", D._RELAUNCH)
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            self.assertFalse(D._should_skip_download(out / "s1.fit", out, "s1", overwrite=False, want_json=True))
            (out / "fit").mkdir()
            (out / "fit" / "s1.json").write_text("{}", encoding="utf-8")
            self.assertTrue(D._should_skip_download(out / "s1.fit", out, "s1", overwrite=False, want_json=True))

    def test_main_without_tokens_exits_2_and_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            old = D.STRAVA_CONFIG_FILE
            D.STRAVA_CONFIG_FILE = Path(tmp) / "absent.json"
            try:
                code = D.main(["s1", "--source", "strava", "--output-dir", str(Path(tmp) / "act")])
            finally:
                D.STRAVA_CONFIG_FILE = old
            self.assertEqual(code, 2)
            self.assertEqual([p.name for p in Path(tmp).iterdir()], ["act"])


if __name__ == "__main__":
    unittest.main()
