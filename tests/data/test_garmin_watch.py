"""Palier D — `scripts/garmin_watch.py` : la surveillance Garmin sans LLM.

Le point du watcher est de NE PAS lancer le LLM quand il n'y a rien de neuf :
chaque test affirme autant ce qui ne se passe pas (sonde non appelée, sync non
lancée) que ce qui se passe. Aucune dépendance à `garminconnect` : les tests
passent une sonde factice à `tick()`, ou le `FakeClient` JSON au script réel.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))
import garmin_watch as W  # noqa: E402

NOW = datetime(2026, 9, 27, 9, 0, 0)
TODAY = NOW.date()


def ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


class FakeProbe:
    """Sonde factice : compte ses appels, lève sur demande."""

    def __init__(self, upload=None, activities=(), sleep_ready=False, error=None):
        self.upload = upload
        self.activities = list(activities)
        self._sleep_ready = sleep_ready
        self.error = error
        self.calls = []

    def _check(self, name):
        self.calls.append(name)
        if self.error:
            raise self.error

    def last_upload_ms(self):
        self._check("last_upload_ms")
        return self.upload

    def recent_activities(self, limit=10):
        self._check("recent_activities")
        return self.activities

    def sleep_ready(self, day):
        self._check("sleep_ready")
        return self._sleep_ready


def activity(activity_id: int, day: date = TODAY) -> dict:
    return {"activityId": activity_id, "startTimeLocal": f"{day.isoformat()} 07:30:00"}


class WatchCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="arc-watch-")
        self.ws = Path(self._tmp.name)
        for d in ("config", "activities", "medical", "logs"):
            (self.ws / d).mkdir()
        self.config("")
        self.runs = []

    def tearDown(self):
        self._tmp.cleanup()

    def config(self, extra: str):
        # Pas de repli par défaut : il fausserait les tests qui n'en parlent pas.
        # Une clé en double rendrait le TOML invalide (défauts partout) : on ne
        # l'ajoute que si le test ne la fixe pas lui-même.
        default = "" if "fallback_times" in extra else "fallback_times = []\n"
        (self.ws / "config/workspace.user.toml").write_text(
            "[sync]\n" + default + extra, encoding="utf-8"
        )

    def run_sync(self, triggers):
        self.runs.append(list(triggers))
        return 0

    def tick(self, probe, now=NOW, dry_run=False):
        return W.tick(self.ws, now, lambda: probe, self.run_sync, dry_run=dry_run)

    def state(self) -> dict:
        return W.load_state(self.ws)

    def set_state(self, **values):
        W.save_state(self.ws, values)

    def persist_activity(self, activity_id: int, name="2026-09-27_running.md"):
        (self.ws / "activities" / name).write_text(
            f'# Séance\n\n```arc\n{{"arc": 1, "kind": "activity", "garmin_activity_id": {activity_id}}}\n```\n',
            encoding="utf-8",
        )


class TestNothingNew(WatchCase):
    def test_unchanged_upload_costs_one_call_and_no_llm(self):
        upload = ms(NOW - timedelta(hours=5))
        self.set_state(last_upload_ms=upload, upload_seen_at=(NOW - timedelta(hours=5)).isoformat())
        probe = FakeProbe(upload=upload, activities=[activity(1)], sleep_ready=True)
        result = self.tick(probe)
        self.assertEqual(result["action"], "none")
        self.assertEqual(probe.calls, ["last_upload_ms"])
        self.assertEqual(self.runs, [])
        self.assertEqual(self.state()["last_check"], NOW.isoformat(timespec="seconds"))

    def test_known_activity_and_existing_health_file_do_not_trigger(self):
        self.persist_activity(42)
        (self.ws / "medical/2026-09-27_health.md").write_text("# Santé\n")
        probe = FakeProbe(upload=ms(NOW - timedelta(hours=1)), activities=[activity(42)], sleep_ready=True)
        self.assertEqual(self.tick(probe)["action"], "none")
        self.assertEqual(self.runs, [])

    def test_activity_older_than_lookback_is_ignored(self):
        old = activity(7, TODAY - timedelta(days=5))
        probe = FakeProbe(upload=ms(NOW - timedelta(hours=1)), activities=[old])
        self.assertEqual(self.tick(probe)["action"], "none")

    def test_second_same_day_file_counts_as_known(self):
        self.persist_activity(1)
        self.persist_activity(2, name="2026-09-27_running_2.md")
        probe = FakeProbe(upload=ms(NOW - timedelta(hours=1)), activities=[activity(1), activity(2)])
        self.assertEqual(self.tick(probe)["action"], "none")


class TestTriggers(WatchCase):
    def test_new_activity_launches_one_sync_with_its_id(self):
        probe = FakeProbe(upload=ms(NOW - timedelta(minutes=20)), activities=[activity(99)])
        result = self.tick(probe)
        self.assertEqual(result["action"], "sync")
        self.assertEqual(self.runs, [["activity:99"]])
        state = self.state()
        self.assertEqual(state["runs"], {"date": "2026-09-27", "count": 1})
        self.assertNotIn("pending", state)
        self.assertIn("activity:99", (self.ws / "logs/watch.log").read_text())

    def test_morning_trigger_when_sleep_ready_and_health_missing(self):
        probe = FakeProbe(upload=ms(NOW - timedelta(minutes=20)), sleep_ready=True)
        self.tick(probe)
        self.assertEqual(self.runs, [["morning"]])

    def test_sleep_not_processed_yet_waits_silently(self):
        probe = FakeProbe(upload=ms(NOW - timedelta(minutes=20)), sleep_ready=False)
        self.assertEqual(self.tick(probe)["action"], "none")
        self.assertEqual(self.runs, [])

    def test_morning_check_off_never_triggers_on_sleep(self):
        self.config('[health]\nmorning_check = "off"\n')
        probe = FakeProbe(upload=ms(NOW - timedelta(minutes=20)), sleep_ready=True)
        self.tick(probe)
        self.assertEqual(self.runs, [])
        self.assertNotIn("sleep_ready", probe.calls)

    def test_recheck_window_catches_sleep_computed_after_the_upload(self):
        upload = ms(NOW - timedelta(minutes=40))
        self.set_state(last_upload_ms=upload, upload_seen_at=(NOW - timedelta(minutes=30)).isoformat())
        probe = FakeProbe(upload=upload, sleep_ready=True)
        self.tick(probe)
        self.assertEqual(self.runs, [["morning"]])

    def test_intervals_source_is_not_watched(self):
        self.config('[data]\nsource = "intervals"\n')
        probe = FakeProbe(upload=ms(NOW), activities=[activity(1)])
        self.assertEqual(self.tick(probe)["action"], "skip")
        self.assertEqual(probe.calls, [])


class TestGuards(WatchCase):
    def test_waits_for_garmin_to_settle(self):
        probe = FakeProbe(upload=ms(NOW - timedelta(minutes=3)), activities=[activity(5)])
        result = self.tick(probe)
        self.assertEqual(result["action"], "wait")
        self.assertEqual(self.runs, [])
        self.assertEqual(self.state()["pending"], ["activity:5"])
        # Plus tard, sans nouvel envoi : la séance en attente part.
        later = NOW + timedelta(minutes=15)
        self.tick(FakeProbe(upload=ms(NOW - timedelta(minutes=3)), activities=[activity(5)]), now=later)
        self.assertEqual(self.runs, [["activity:5"]])

    def test_min_gap_between_runs(self):
        self.set_state(last_run=(NOW - timedelta(minutes=10)).isoformat())
        probe = FakeProbe(upload=ms(NOW - timedelta(minutes=20)), activities=[activity(5)])
        self.assertEqual(self.tick(probe)["action"], "wait")
        self.assertEqual(self.runs, [])

    def test_daily_cap(self):
        self.config("max_runs_per_day = 2\n")
        self.set_state(runs={"date": "2026-09-27", "count": 2})
        probe = FakeProbe(upload=ms(NOW - timedelta(minutes=20)), activities=[activity(5)])
        self.assertEqual(self.tick(probe)["action"], "wait")
        self.assertEqual(self.runs, [])

    def test_trigger_given_up_after_two_ineffective_runs(self):
        upload = ms(NOW - timedelta(minutes=20))
        for i in range(4):
            self.tick(FakeProbe(upload=upload, activities=[activity(5)]), now=NOW + timedelta(minutes=40 * i))
        self.assertEqual(self.runs, [["activity:5"], ["activity:5"]])
        self.assertIn("abandon", (self.ws / "logs/watch.log").read_text())

    def test_dry_run_neither_launches_nor_writes_state(self):
        probe = FakeProbe(upload=ms(NOW - timedelta(minutes=20)), activities=[activity(5)])
        result = self.tick(probe, dry_run=True)
        self.assertEqual(result["action"], "sync")
        self.assertEqual(self.runs, [])
        self.assertFalse((self.ws / W.STATE_REL).exists())


class TestErrors(WatchCase):
    def test_transient_error_backs_off_exponentially(self):
        probe = FakeProbe(error=W.TransientError("429 Too Many Requests"))
        self.assertEqual(self.tick(probe)["action"], "error")
        first = datetime.fromisoformat(self.state()["backoff_until"])
        self.assertEqual(first, NOW + timedelta(minutes=15))
        # Pendant le backoff, Garmin n'est même pas interrogé.
        quiet = FakeProbe(upload=ms(NOW))
        self.assertEqual(self.tick(quiet, now=NOW + timedelta(minutes=5))["action"], "skip")
        self.assertEqual(quiet.calls, [])
        self.tick(probe, now=NOW + timedelta(minutes=16))
        second = datetime.fromisoformat(self.state()["backoff_until"])
        self.assertEqual(second, NOW + timedelta(minutes=16 + 30))

    def test_success_clears_backoff(self):
        self.set_state(errors=3, backoff_until=(NOW - timedelta(minutes=1)).isoformat())
        self.tick(FakeProbe(upload=ms(NOW - timedelta(hours=3))))
        state = self.state()
        self.assertNotIn("errors", state)
        self.assertNotIn("backoff_until", state)

    def test_auth_error_does_not_launch_llm_before_fallback(self):
        self.config('fallback_times = ["21:30"]\n')
        probe = FakeProbe(error=W.AuthError("401"))
        self.assertEqual(self.tick(probe)["action"], "error")
        self.assertEqual(self.runs, [])

    def test_auth_error_still_runs_fallback_once(self):
        self.config('fallback_times = ["21:30"]\n')
        evening = NOW.replace(hour=21, minute=45)
        probe = FakeProbe(error=W.AuthError("401"))
        self.tick(probe, now=evening)
        self.tick(probe, now=evening + timedelta(minutes=15))
        self.assertEqual(self.runs, [[]])


class TestFallback(WatchCase):
    def test_fallback_runs_once_when_no_run_today(self):
        self.config('fallback_times = ["21:30"]\n')
        upload = ms(NOW - timedelta(hours=10))
        self.set_state(last_upload_ms=upload)
        evening = NOW.replace(hour=21, minute=45)
        self.assertEqual(self.tick(FakeProbe(upload=upload), now=evening)["action"], "sync")
        self.tick(FakeProbe(upload=upload), now=evening + timedelta(minutes=15))
        self.assertEqual(self.runs, [[]])

    def test_no_fallback_if_a_run_already_happened(self):
        self.config('fallback_times = ["21:30"]\n')
        self.set_state(runs={"date": "2026-09-27", "count": 1})
        evening = NOW.replace(hour=21, minute=45)
        self.assertEqual(self.tick(FakeProbe(upload=None), now=evening)["action"], "none")
        self.assertEqual(self.runs, [])

    def test_no_fallback_if_daily_sync_ran_outside_the_watcher(self):
        # Session mobile, lancement manuel, ou ancien cron le jour de la bascule.
        self.config('fallback_times = ["21:30"]\n')
        (self.ws / "logs/sync-2026-09-27.log").write_text("===== 2026-09-27 07:15:02 — runner=claude lookback=2 =====\n")
        evening = NOW.replace(hour=21, minute=45)
        self.assertEqual(self.tick(FakeProbe(upload=None), now=evening)["action"], "none")
        self.assertEqual(self.runs, [])

    def test_yesterdays_sync_log_does_not_count(self):
        self.config('fallback_times = ["21:30"]\n')
        (self.ws / "logs/sync-2026-09-26.log").write_text("===== 2026-09-26 21:30:00 — runner=claude =====\n")
        evening = NOW.replace(hour=21, minute=45)
        self.assertEqual(self.tick(FakeProbe(upload=None), now=evening)["action"], "sync")

    def test_no_fallback_before_its_time(self):
        self.config('fallback_times = ["21:30"]\n')
        self.assertEqual(self.tick(FakeProbe(upload=None))["action"], "none")


class TestSettings(WatchCase):
    def test_invalid_values_fall_back_to_defaults(self):
        self.config('max_runs_per_day = "beaucoup"\nsettle_min = -3\nfallback_times = ["tard", "22:00"]\n')
        settings = W.load_settings(self.ws)
        self.assertEqual(settings["max_runs_per_day"], W.DEFAULTS["max_runs_per_day"])
        self.assertEqual(settings["settle_min"], W.DEFAULTS["settle_min"])
        self.assertEqual(settings["fallback_times"], ["22:00"])


class TestCli(WatchCase):
    """Le vrai script, Garmin simulé par `ARC_WATCH_FAKE_GARMIN`."""

    def _run(self, fake: dict, *args):
        fake_path = self.ws / "fake.json"
        fake_path.write_text(json.dumps(fake))
        record = self.ws / "sync-args.txt"
        env = dict(
            os.environ,
            ARC_WORKSPACE=str(self.ws),
            ARC_WATCH_NOW=NOW.isoformat(),
            ARC_WATCH_FAKE_GARMIN=str(fake_path),
            ARC_WATCH_SYNC_CMD=f"sh -c 'echo \"$@\" > {record}' sync",
            HOME=str(self.ws),
        )
        proc = subprocess.run(
            [sys.executable, str(REPO / "scripts/garmin_watch.py"), *args],
            env=env, capture_output=True, text=True, timeout=30,
        )
        return proc, record

    def test_new_activity_calls_daily_sync_with_trigger(self):
        proc, record = self._run({
            "upload_ms": ms(NOW - timedelta(minutes=20)),
            "activities": [activity(24502120201)],
        })
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(record.read_text().strip(), "--trigger activity:24502120201")

    def test_nothing_new_never_calls_daily_sync(self):
        self.persist_activity(1)
        proc, record = self._run({"upload_ms": ms(NOW - timedelta(minutes=20)), "activities": [activity(1)]})
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertFalse(record.exists())

    def test_auth_error_is_reported_not_crashed(self):
        proc, record = self._run({"error": "auth"}, "--dry-run")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(json.loads(proc.stdout.strip().splitlines()[-1])["action"], "error")
        self.assertFalse(record.exists())

    def test_status_prints_state(self):
        self.set_state(last_check="2026-09-27T08:45:00")
        proc, _ = self._run({}, "--status")
        self.assertEqual(json.loads(proc.stdout)["last_check"], "2026-09-27T08:45:00")


# COROS (#168) : textes de forme relevée (docs/coros.md), identifiants synthétiques.
COROS_LABEL = "900000000000000001"
COROS_RECORDS = (
    "Sport Records — 2026-09-26 to 2026-09-27 (2 records)\n========================\n\n"
    "1. Outdoor Run — 2026-09-27\n   Location: Endurance 40 min\n"
    "   Time Window: startTimestamp=1790000000 | endTimestamp=1790003600\n"
    f"   Duration: 1:00:00 | Distance: 9.00 km\n   LabelId: {COROS_LABEL} | SportType: 100\n\n"
    "2. Trail Run — 2026-09-20\n   Location: Vieille sortie\n   LabelId: 900000000000000002 | SportType: 102"
)
SLEEP_NOT_YET = ("Sleep Overview\n========================\n\n2026-09-27\nSleep Score: 0\n"
                 "Sleep detail for this day is not available yet.")
SLEEP_READY = "Sleep Overview\n========================\n\n2026-09-27\nSleep Score: 75\nMain Sleep: 7h46m"


class FakeCorosClient:
    def __init__(self, tools=None, error=None):
        self.tools, self.error, self.calls = tools or {}, error, []

    def call(self, tool, arguments):
        self.calls.append((tool, arguments))
        if self.error:
            raise self.error
        return self.tools.get(tool, "")


def login_error():
    exc = RuntimeError("COROS : COROS non connecté — lancez : python3 scripts/arc_coros_auth.py login")
    exc.login_required = True
    return exc


class TestCoros(WatchCase):
    def setUp(self):
        super().setUp()
        (self.ws / "config/workspace.user.toml").write_text(
            '[data]\nsource = "coros"\n\n[sync]\nfallback_times = []\n', encoding="utf-8")

    def probe(self, **tools):
        return W.CorosProbe(FakeCorosClient({"querySportRecords": COROS_RECORDS, "querySleepOverview": SLEEP_NOT_YET,
                                             **tools}))

    def test_records_are_parsed_into_contract_ids(self):
        self.assertEqual(self.probe().recent_activities(days=10),
                         [(f"c{COROS_LABEL}", "2026-09-27"), ("c900000000000000002", "2026-09-20")])

    def test_sleep_score_zero_is_not_a_night(self):
        self.assertFalse(self.probe().sleep_ready(TODAY))
        self.assertTrue(self.probe(querySleepOverview=SLEEP_READY).sleep_ready(TODAY))

    def test_new_activity_waits_settle_from_first_sight_then_syncs(self):
        probe = self.probe()
        first = self.tick(probe)
        self.assertEqual(first["action"], "wait")
        self.assertEqual(first["triggers"], [f"activity:c{COROS_LABEL}"])
        self.assertEqual(self.runs, [])
        later = self.tick(probe, now=NOW + timedelta(minutes=11))
        self.assertEqual(later["action"], "sync")
        self.assertEqual(self.runs, [[f"activity:c{COROS_LABEL}"]])
        self.assertNotIn("pending_since", self.state())

    def test_known_coros_activity_and_health_file_mean_nothing_new(self):
        (self.ws / "activities/2026-09-27_running.md").write_text(
            f'# S\n\n```arc\n{{"arc": 1, "kind": "activity", "coros_activity_id": "c{COROS_LABEL}"}}\n```\n')
        (self.ws / "medical/2026-09-27_health.md").write_text("# Santé\n")
        probe = self.probe(querySleepOverview=SLEEP_READY)
        self.assertEqual(self.tick(probe)["action"], "none")
        self.assertEqual([c[0] for c in probe.client.calls], ["querySportRecords"])

    def test_morning_only_once_the_night_is_computed(self):
        (self.ws / "activities/2026-09-27_running.md").write_text(
            f'```arc\n{{"arc": 1, "kind": "activity", "coros_activity_id": "c{COROS_LABEL}"}}\n```\n')
        self.assertEqual(self.tick(self.probe())["action"], "none")
        result = self.tick(self.probe(querySleepOverview=SLEEP_READY), now=NOW + timedelta(minutes=15))
        self.assertEqual(result["triggers"], ["morning"])

    def test_login_error_names_the_coros_command_and_never_runs_the_llm(self):
        probe = W.CorosProbe(FakeCorosClient(error=login_error()))
        result = self.tick(probe)
        self.assertEqual(result["action"], "error")
        self.assertIn("python3 scripts/arc_coros_auth.py login", result["reason"])
        self.assertEqual(self.runs, [])

    def test_network_error_backs_off(self):
        probe = W.CorosProbe(FakeCorosClient(error=RuntimeError("COROS : COROS injoignable")))
        result = self.tick(probe)
        self.assertEqual(result["action"], "error")
        self.assertIn("COROS injoignable", result["reason"])
        self.assertIn("backoff_until", self.state())

    def test_cli_with_fake_coros(self):
        fake = self.ws / "fake-coros.json"
        fake.write_text(json.dumps({"tools": {"querySportRecords": COROS_RECORDS,
                                              "querySleepOverview": SLEEP_NOT_YET}}))
        env = dict(os.environ, ARC_WORKSPACE=str(self.ws), ARC_WATCH_NOW=NOW.isoformat(),
                   ARC_WATCH_FAKE_COROS=str(fake), HOME=str(self.ws))
        proc = subprocess.run([sys.executable, str(REPO / "scripts/garmin_watch.py"), "--dry-run"],
                              env=env, capture_output=True, text=True, timeout=30)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        result = json.loads(proc.stdout.strip().splitlines()[-1])
        self.assertEqual(result["triggers"], [f"activity:c{COROS_LABEL}"])


if __name__ == "__main__":
    unittest.main()
