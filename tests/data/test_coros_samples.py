"""Palier D — identifiant d'activité COROS (#168) : `coros_activity_id` (« c » + LabelId).

Verrouille : le quatrième espace d'identifiants (contrat, nom de fichier, colonnes de l'index)
est disjoint des trois autres ; une séance COROS dont les échantillons sont ceux d'une séance
Garmin rend exactement les mêmes KPI ; ses montées sont numérotées par l'heure de départ
(`start_time`), le LabelId de 18 chiffres ne tenant pas sous Number.MAX_SAFE_INTEGER ; sans
`start_time`, la séance s'indexe mais ses montées ne sont pas appariées et la dette est
signalée. Le téléchargeur (`download_fit.py --source coros`) demande l'URL au MCP par le relais
(simulé ici, aucun appel réseau), ne suit qu'une URL https de COROS et ne l'affiche jamais.
"""

from __future__ import annotations

import contextlib
import io
import json
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
from tests.data.test_strava_samples import _router  # noqa: E402

COROS_ID = "c481221836600803431"
GARMIN_ID = 90000000168
START = "2026-09-29T08:00:00+02:00"


class TestActivityRef(unittest.TestCase):
    def test_parse_activity_ref_accepts_the_coros_space(self):
        self.assertEqual(S.parse_activity_ref(COROS_ID), COROS_ID)
        for bad in ("c", "C1", "c12a", "cc1"):
            self.assertIsNone(S.parse_activity_ref(bad), bad)

    def test_file_name_carries_the_coros_id(self):
        self.assertEqual(S.sample_file_activity_id(Path(f"activities/fit/{COROS_ID}.json")), COROS_ID)

    def test_contract_validates_the_prefixed_id_only(self):
        import arc_contract as C
        base = {"arc": 1, "kind": "activity", "date": "2026-09-29", "sport": "trail", "duration_s": 60}
        errors, _warnings = C.validate({**base, "coros_activity_id": COROS_ID})
        self.assertEqual(errors, [])
        for bad in (481221836600803431, "481221836600803431", "c", "s123"):
            errors, _warnings = C.validate({**base, "coros_activity_id": bad})
            self.assertTrue(any("coros_activity_id" in e for e in errors), bad)

    def test_index_column_follows_the_prefix(self):
        self.assertEqual(I.ref_column(COROS_ID), "coros_activity_id")
        self.assertEqual(I.ref_column("s1"), "strava_activity_id")
        self.assertEqual(I.ref_column("i1"), "intervals_activity_id")


class TestClimbSeed(unittest.TestCase):
    def test_seed_comes_from_the_start_time(self):
        seed = VM.segment_seed(COROS_ID, "2026-10-22T19:20:19+02:00")
        self.assertEqual(seed, VM.COROS_SEED_OFFSET + 1792689619)
        self.assertLess(seed * VM.SEGMENT_ID_CLIMB_MULTIPLIER + 9999, 2 ** 53)

    def test_offsets_and_naive_times_give_one_stable_value(self):
        self.assertEqual(VM.segment_seed(COROS_ID, "2026-10-22T17:20:19Z"),
                         VM.segment_seed(COROS_ID, "2026-10-22T19:20:19+02:00"))
        self.assertEqual(VM.segment_seed(COROS_ID, "2026-10-22T17:20:19"),
                         VM.segment_seed(COROS_ID, "2026-10-22T17:20:19Z"))

    def test_no_start_time_means_no_seed(self):
        for value in (None, "", "pas une date"):
            self.assertIsNone(VM.segment_seed(COROS_ID, value), value)

    def test_coros_seeds_sit_between_strava_and_intervals(self):
        seed = VM.segment_seed(COROS_ID, START)
        self.assertGreater(seed, VM.segment_seed("s99999999999"))
        self.assertLess(seed, VM.segment_seed("i1"))
        with self.assertRaises(ValueError):
            VM.segment_seed(f"s{VM.COROS_SEED_OFFSET - VM.STRAVA_SEED_OFFSET}")


class TestParityWithGarmin(Workspace):
    """Séance Garmin vs séance COROS portant les mêmes échantillons."""

    def write_coros_activity(self, day, start_time=START, coros_id=COROS_ID):
        data = {"arc": 1, "kind": "activity", "date": day, "sport": "trail", "duration_s": 6000,
                "distance_m": 15000, "coros_activity_id": coros_id}
        if start_time:
            data["start_time"] = start_time
        self.write(f"activities/{day}_trail.md", f"# Séance\n\n```arc\n{json.dumps(data)}\n```\n")

    def setUp(self):
        super().setUp()
        self.records = _hilly_records()
        self.write_profile()
        self.write_activity("2026-09-28", intervals_id=None, garmin_id=GARMIN_ID)
        self.write_coros_activity("2026-09-29")
        self.write_fit(GARMIN_ID, self.records)
        self.write_fit(COROS_ID, self.records)
        self.index()
        self.garmin = self.activity("garmin_activity_id", GARMIN_ID)
        self.coros = self.activity("coros_activity_id", COROS_ID)

    def climbs(self, activity_id):
        return self.conn.execute("SELECT segment_id, vs_previous_pct FROM activity_climb WHERE activity_id = ?",
                                 (activity_id,)).fetchall()

    def test_the_coros_file_is_linked_by_its_own_column(self):
        stored = self.conn.execute(
            "SELECT DISTINCT garmin_activity_id, intervals_activity_id, strava_activity_id, coros_activity_id "
            "FROM activity_sample WHERE coros_activity_id IS NOT NULL").fetchall()
        self.assertEqual([tuple(r) for r in stored], [(None, None, None, COROS_ID)])

    def test_every_kpi_column_matches(self):
        for col in KPI_COLUMNS:
            with self.subTest(col=col):
                self.assertEqual(self.coros[col], self.garmin[col])
        self.assertIsNotNone(self.coros["gap_pace_s_km"])
        self.assertIsNotNone(self.coros["best_climb_vam_elapsed_m_h"])

    def test_a_coros_only_climb_is_numbered_from_its_start_time(self):
        self.write("activities/2026-09-28_trail.md", "# vide\n")
        self.index()
        coros = self.activity("coros_activity_id", COROS_ID)
        seed = VM.segment_seed(COROS_ID, START)
        ids = {r["segment_id"] for r in self.climbs(coros["id"])}
        self.assertTrue(ids)
        self.assertTrue(all(i // VM.SEGMENT_ID_CLIMB_MULTIPLIER == seed for i in ids), ids)

    def test_without_start_time_climbs_are_not_matched_and_the_debt_is_shown(self):
        self.write_coros_activity("2026-09-29", start_time=None)
        self.index()
        coros = self.activity("coros_activity_id", COROS_ID)
        self.assertIsNotNone(coros["gap_pace_s_km"])
        self.assertEqual(self.climbs(coros["id"]), [])
        data = {"sport": "trail", "coros_activity_id": COROS_ID}
        keys = I.expected_keys("activity", data, I.settings(I.load_config(self.ws)))
        self.assertIn("start_time", keys)
        self.assertNotIn("garmin_activity_id", keys)
        self.assertNotIn("splits", keys)

    def test_per_activity_reports_accept_the_coros_id(self):
        conf = I.settings(I.load_config(self.ws))
        for name, report in {
            "zones": I.activity_zone_report(self.conn, conf, COROS_ID),
            "gap": I.activity_gap_report(self.conn, COROS_ID),
            "decoupling": I.activity_decoupling_report(self.conn, COROS_ID),
            "vam": I.activity_climb_report(self.conn, COROS_ID),
            "durability": I.activity_durability_report(self.conn, COROS_ID),
        }.items():
            with self.subTest(report=name):
                self.assertEqual(report["coros_activity_id"], COROS_ID)
                self.assertNotEqual(report.get("reason_code"), "unknown_activity")


# ---------------------------------------------------------------------------
# Téléchargeur : relais simulé, HTTP injecté
# ---------------------------------------------------------------------------

FIT_URL = f"https://s3eu.coros.com/fit/481212744152924160/{COROS_ID[1:]}.fit"


class FakeRelay:
    def __init__(self, text=None, error=None, is_error=False, raises=None):
        self.text, self.error, self.is_error, self.raises = text, error, is_error, raises
        self.calls = []

    def handle(self, msg):
        self.calls.append(msg)
        if msg.get("method") != "tools/call":
            return [] if msg.get("id") is None else [{"jsonrpc": "2.0", "id": msg["id"], "result": {}}]
        if self.raises:
            raise self.raises
        if self.error:
            return [{"jsonrpc": "2.0", "id": msg["id"], "error": {"code": -32000, "message": self.error}}]
        return [{"jsonrpc": "2.0", "id": msg["id"],
                 "result": {"content": [{"type": "text", "text": self.text}], "isError": self.is_error}}]


def _urls_text(*urls):
    return "Activity FIT file download URL(s):\n" + "\n".join(
        f"{i}. {COROS_ID[1:]}.fit\n   {u}" for i, u in enumerate(urls, 1))


class TestCorosDownload(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_asks_the_url_by_label_then_downloads_without_any_token(self):
        relay, calls = FakeRelay(_urls_text(FIT_URL)), []
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            path = D._download_one_coros(COROS_ID, self.root, False, relay=relay,
                                         opener=_router({FIT_URL: b".FIT-bytes"}, calls))
        self.assertEqual(path, self.root / f"{COROS_ID}.fit")
        self.assertEqual(path.read_bytes(), b".FIT-bytes")
        call = relay.calls[-1]["params"]
        self.assertEqual(call["name"], "queryActivityFitFileDownloadUrls")
        self.assertEqual(call["arguments"], {"labelId": COROS_ID[1:], "sportType": D.COROS_URL_SPORT_TYPE})
        self.assertEqual(len(calls), 1)
        self.assertNotIn("Authorization", calls[0].headers)
        self.assertNotIn("s3eu.coros.com", out.getvalue())

    def test_unprefixed_id_is_rejected_without_any_call(self):
        relay = FakeRelay(_urls_text(FIT_URL))
        with self.assertRaises(D.CorosUnavailable):
            D._download_one_coros(COROS_ID[1:], self.root, False, relay=relay, opener=_router({}, []))
        self.assertEqual(relay.calls, [])

    def test_only_a_coros_https_url_for_this_label_is_followed(self):
        for text in ("No FIT file found.",
                     _urls_text(f"https://evil.example.com/{COROS_ID[1:]}.fit"),
                     _urls_text(f"http://s3eu.coros.com/fit/x/{COROS_ID[1:]}.fit"),
                     _urls_text("https://s3eu.coros.com/fit/x/123.fit")):
            with self.subTest(text=text), self.assertRaises(D.CorosUnavailable):
                D._download_one_coros(COROS_ID, self.root, False, relay=FakeRelay(text), opener=_router({}, []))

    def test_relay_and_tool_errors_are_failures_with_a_hint(self):
        import arc_coros_auth
        for relay in (FakeRelay(error="COROS : HTTP 500"), FakeRelay("quota", is_error=True),
                      FakeRelay(raises=arc_coros_auth.CorosAuthError("COROS non connecté", 2))):
            with self.subTest(relay=relay.error or relay.text or relay.raises):
                with self.assertRaises(D.CorosError) as ctx:
                    D._download_one_coros(COROS_ID, self.root, False, relay=relay, opener=_router({}, []))
                self.assertNotIsInstance(ctx.exception, D.CorosUnavailable)
                self.assertIn("arc_coros_auth.py status", str(ctx.exception))

    def test_http_error_on_the_file_never_shows_the_url(self):
        err = urllib.error.HTTPError(FIT_URL, 403, "err", {}, io.BytesIO(b""))
        with self.assertRaises(D.CorosError) as ctx:
            D._download_one_coros(COROS_ID, self.root, False, relay=FakeRelay(_urls_text(FIT_URL)),
                                  opener=_router({FIT_URL: err}, []))
        self.assertNotIn("s3eu", str(ctx.exception))

    def test_ids_are_read_from_the_contract_block(self):
        text = f"# x\n\n```arc\n{json.dumps({'coros_activity_id': COROS_ID})}\n```\n"
        self.assertEqual(D._activity_id_from_arc(text, "coros"), COROS_ID)
        self.assertIsNone(D._activity_id_from_arc(text.replace(COROS_ID, COROS_ID[1:]), "coros"))


if __name__ == "__main__":
    unittest.main()
