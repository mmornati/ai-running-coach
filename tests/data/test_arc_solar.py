"""Palier D — position du soleil, lever/coucher, crépuscule civil (#184, épopée #170).

Valeurs de référence : API publique sunrise-sunset.org (`formatted=0`, UTC), interrogée
le 2026-10-04 pour des lieux publics (Paris, Chamonix, New York, Sydney). Tolérance ±3 min
(l'algorithme NOAA est une approximation ; mesuré : crépuscule civil < 1 min, lever/coucher
~2 min). Aux latitudes polaires seule l'EXISTENCE des événements est vérifiée (écart de
lever/coucher plus grand, le soleil rase l'horizon).
"""

from __future__ import annotations

import sys
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))

import arc_solar as S  # noqa: E402

TOL_S = 3 * 60


def _utc(text: str) -> datetime:
    return datetime.fromisoformat(text).replace(tzinfo=timezone.utc)


# (lat, lon, jour, lever, coucher, crépuscule civil début, fin) — UTC, source : voir docstring.
REFERENCE = [
    ("Paris solstice d'été", 48.8566, 2.3522, date(2026, 6, 21),
     "2026-06-21T03:44:59", "2026-06-21T19:59:51", "2026-06-21T03:04:21", "2026-06-21T20:40:28"),
    ("Chamonix solstice d'hiver", 45.9237, 6.8694, date(2026, 12, 21),
     "2026-12-21T07:09:16", "2026-12-21T15:51:52", "2026-12-21T06:36:33", "2026-12-21T16:24:36"),
    ("New York équinoxe", 40.7128, -74.0060, date(2026, 3, 20),
     "2026-03-20T10:57:28", "2026-03-20T23:09:21", "2026-03-20T10:31:34", "2026-03-20T23:35:15"),
    ("Sydney équinoxe (hémisphère sud, fuseau très à l'est)", -33.8688, 151.2093, date(2026, 9, 23),
     "2026-09-22T19:42:17", "2026-09-23T07:53:02", "2026-09-22T19:18:39", "2026-09-23T08:16:40"),
]


class TestSunTimes(unittest.TestCase):
    def test_against_published_values(self):
        for name, lat, lon, day, rise, sset, dawn, dusk in REFERENCE:
            with self.subTest(name):
                ev = S.sun_times(day, lat, lon)
                for key, expected in (("sunrise", rise), ("sunset", sset), ("civil_dawn", dawn),
                                      ("civil_dusk", dusk)):
                    delta = abs((ev[key] - _utc(expected)).total_seconds())
                    self.assertLessEqual(delta, TOL_S, f"{name} {key}: {ev[key]} vs {expected}")
                self.assertIsNone(ev["polar"])

    def test_event_order(self):
        ev = S.sun_times(date(2026, 6, 21), 48.8566, 2.3522)
        self.assertLess(ev["civil_dawn"], ev["sunrise"])
        self.assertLess(ev["sunrise"], ev["solar_noon"])
        self.assertLess(ev["solar_noon"], ev["sunset"])
        self.assertLess(ev["sunset"], ev["civil_dusk"])

    def test_local_date_in_timezone(self):
        try:
            tz = S.resolve_timezone("Europe/Paris")
        except ValueError:
            self.skipTest("base IANA absente")
        ev = S.local_sun_times(date(2026, 6, 21), 48.8566, 2.3522, tz)
        # 03:44:59 UTC = 05:44:59 CEST (heure d'été, UTC+2).
        self.assertLessEqual(abs((ev["sunrise"].replace(tzinfo=None) - datetime(2026, 6, 21, 5, 45)).total_seconds()),
                             TOL_S)
        self.assertEqual(ev["sunrise"].date(), date(2026, 6, 21))
        self.assertEqual(ev["civil_dusk"].date(), date(2026, 6, 21))

    def test_local_date_picks_the_right_solar_day_far_from_utc(self):
        try:
            tz = S.resolve_timezone("Australia/Sydney")
        except ValueError:
            self.skipTest("base IANA absente")
        ev = S.local_sun_times(date(2026, 9, 23), -33.8688, 151.2093, tz)
        # Lever du 23/09 local (AEST, UTC+10) = 22/09 19:42 UTC.
        self.assertEqual(ev["sunrise"].date(), date(2026, 9, 23))
        self.assertEqual(ev["sunset"].date(), date(2026, 9, 23))
        self.assertLess(ev["sunrise"], ev["sunset"])

    def test_polar_day_has_no_events(self):
        ev = S.sun_times(date(2026, 6, 21), 69.6492, 18.9553)  # Tromsø, soleil de minuit
        self.assertEqual(ev["polar"], "polar_day")
        self.assertIsNone(ev["sunrise"])
        self.assertIsNone(ev["civil_dusk"])

    def test_polar_night(self):
        ev = S.sun_times(date(2026, 12, 21), 69.6492, 18.9553)
        self.assertEqual(ev["polar"], "polar_night")
        self.assertIsNone(ev["sunset"])

    def test_no_civil_night_at_high_latitude_in_summer(self):
        # Reykjavik, solstice : le soleil monte et descend mais reste au-dessus de -6°.
        ev = S.sun_times(date(2026, 6, 21), 64.1466, -21.9426)
        self.assertIsNotNone(ev["sunrise"])
        self.assertIsNone(ev["civil_dawn"])
        self.assertIsNone(ev["civil_dusk"])

    def test_unknown_timezone_is_a_clear_error(self):
        with self.assertRaises(ValueError):
            S.resolve_timezone("Nowhere/Land")


class TestNightMask(unittest.TestCase):
    LAT, LON = 48.8566, 2.3522
    START = datetime(2026, 6, 21, 12, 0, tzinfo=timezone.utc)

    def setUp(self):
        self.mask = S.NightMask(self.START, self.START + timedelta(hours=40), self.LAT, self.LON)

    def test_night_starts_at_civil_dusk_and_ends_at_civil_dawn(self):
        windows = self.mask.night_windows(self.START, self.START + timedelta(hours=24))
        self.assertEqual(len(windows), 1)
        self.assertEqual(len(self.mask.night_windows(self.START, self.START + timedelta(hours=40))), 2)
        a, b = windows[0]
        self.assertLessEqual(abs((a - _utc("2026-06-21T20:40:28")).total_seconds()), 2 * 60)
        self.assertLessEqual(abs((b - _utc("2026-06-22T03:04:00")).total_seconds()), 3 * 60)

    def test_night_seconds_inside_and_outside(self):
        noon = self.START
        self.assertEqual(self.mask.night_seconds(noon, noon + timedelta(hours=2)), 0.0)
        self.assertAlmostEqual(self.mask.night_seconds(noon + timedelta(hours=10), noon + timedelta(hours=12)),
                               2 * 3600.0, delta=1.0)
        # Fenêtre à cheval sur l'aube (≈ 03:04 UTC = noon + 15 h 04) : seule la partie nocturne compte.
        part = self.mask.night_seconds(noon + timedelta(hours=14), noon + timedelta(hours=16))
        self.assertTrue(3600.0 < part < 3600.0 + 5 * 60, part)

    def test_empty_or_reversed_interval(self):
        t = self.START + timedelta(hours=10)
        self.assertEqual(self.mask.night_seconds(t, t), 0.0)
        self.assertEqual(self.mask.night_seconds(t + timedelta(hours=1), t), 0.0)

    def test_white_night_has_no_night(self):
        mask = S.NightMask(self.START, self.START + timedelta(hours=40), 64.1466, -21.9426)
        self.assertEqual(mask.night_windows(self.START, self.START + timedelta(hours=40)), [])

    def test_polar_night_is_continuous_night(self):
        start = datetime(2026, 12, 21, 12, 0, tzinfo=timezone.utc)
        mask = S.NightMask(start, start + timedelta(hours=10), 80.0, 0.0)
        self.assertAlmostEqual(mask.night_seconds(start, start + timedelta(hours=10)), 36000.0, delta=1.0)


if __name__ == "__main__":
    unittest.main()
