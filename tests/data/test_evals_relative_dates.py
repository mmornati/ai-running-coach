"""Palier D — `{{PREV_WEEK_START}}` et la matérialisation des dates relatives
des fixtures d'évals (#107, revue de code, 2ᵉ tour, BLOQUANT).

Contexte : un fichier `<N>d_reste.md` daté via `{{DATE}}` (N jours avant
aujourd'hui) tombe un jour de semaine QUELCONQUE — jamais garanti un lundi.
Une fixture qui utilisait `{{DATE}}` comme `week.week_start` (ex.
`tests/evals/fixtures/workout-personal-targets/planning/7d_semaine_precedente.md`,
avant ce correctif) ne produisait donc un `week_start` valide (un vrai lundi)
QUE si le cas tournait lui-même un lundi — tout autre jour,
`arc_guardrails.py check --week` rejette (exit 2, « n'est pas un lundi »).
`{{PREV_WEEK_START}}` (`tests/evals/runner.py::_materialize_relative_dates`) =
`{{WEEK_START}}` moins 7 jours est, lui, TOUJOURS un lundi, quel que soit le
jour d'exécution — ces tests le vérifient avec `date.today()` patché sur un
lundi ET sur un dimanche (les deux bornes de la semaine ISO), et vérifient
que `arc_guardrails.py check --week` accepte réellement le résultat (exit 0).
"""

from __future__ import annotations

import datetime as _dt
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))

from tests.evals import runner  # noqa: E402


def _fixed_date_class(fixed: _dt.date):
    """Sous-classe de `datetime.date` dont `.today()` rend `fixed` — pour
    patcher `tests.evals.runner.date` sans toucher au reste du module (les
    autres usages, `date.fromisoformat` etc., ne sont pas exercés par
    `_materialize_relative_dates`)."""
    class _FixedDate(_dt.date):
        @classmethod
        def today(cls):
            return cls(fixed.year, fixed.month, fixed.day)
    return _FixedDate


class TestPrevWeekStartPlaceholder(unittest.TestCase):
    """`_materialize_relative_dates` : `{{PREV_WEEK_START}}` est toujours un
    lundi, et la séance `{{DATE}}` (7 jours avant aujourd'hui, fichier
    `7d_...`) tombe toujours DANS la semaine qu'il désigne."""

    FIXTURE_CONTENT = (
        "# Semaine précédente\n\n```arc\n"
        '{"arc": 1, "kind": "week", "week_start": "{{PREV_WEEK_START}}", '
        '"location": "Tournai", "sessions": [{"date": "{{DATE}}", "sport": "trail", '
        '"title": "Séance seuil 30 min", "intensity": "threshold", '
        '"planned_duration_s": 1800, "outdoor": true, "status": "done"}]}\n```\n'
    )

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="arc-evals-relative-dates-"))
        self.ws = self.tmp / "workspace"
        (self.ws / "planning").mkdir(parents=True)
        (self.ws / "planning" / "7d_semaine_precedente.md").write_text(
            self.FIXTURE_CONTENT, encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _materialize(self, today: _dt.date) -> dict:
        with mock.patch.object(runner, "date", _fixed_date_class(today)):
            runner._materialize_relative_dates(self.ws)
        matches = list((self.ws / "planning").glob("*_semaine_precedente.md"))
        self.assertEqual(len(matches), 1, matches)
        path = matches[0]
        text = path.read_text(encoding="utf-8")
        start = text.find("```arc")
        start = text.find("\n", start) + 1
        end = text.find("```", start)
        block = json.loads(text[start:end])
        block["_path"] = path
        return block

    def _run_guardrails_check(self, week_file: Path, today: _dt.date) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(REPO / "scripts/arc_guardrails.py"), "check",
             "--week", str(week_file), "--workspace", str(self.ws), "--memory",
             "--today", today.isoformat()],
            capture_output=True, text=True,
        )

    def test_week_start_is_a_monday_when_today_is_a_monday(self):
        today = _dt.date(2026, 9, 28)
        self.assertEqual(today.weekday(), 0)  # garde-fou du test lui-même
        block = self._materialize(today)
        week_start = _dt.date.fromisoformat(block["week_start"])
        self.assertEqual(week_start.weekday(), 0)

    def test_week_start_is_a_monday_when_today_is_a_sunday(self):
        today = _dt.date(2026, 10, 4)
        self.assertEqual(today.weekday(), 6)  # garde-fou du test lui-même
        block = self._materialize(today)
        week_start = _dt.date.fromisoformat(block["week_start"])
        self.assertEqual(week_start.weekday(), 0)

    def test_session_date_falls_within_the_week_it_declares_on_a_monday(self):
        today = _dt.date(2026, 9, 28)
        block = self._materialize(today)
        week_start = _dt.date.fromisoformat(block["week_start"])
        session_date = _dt.date.fromisoformat(block["sessions"][0]["date"])
        self.assertLessEqual(week_start, session_date)
        self.assertLessEqual(session_date, week_start + _dt.timedelta(days=6))

    def test_session_date_falls_within_the_week_it_declares_on_a_sunday(self):
        today = _dt.date(2026, 10, 4)
        block = self._materialize(today)
        week_start = _dt.date.fromisoformat(block["week_start"])
        session_date = _dt.date.fromisoformat(block["sessions"][0]["date"])
        self.assertLessEqual(week_start, session_date)
        self.assertLessEqual(session_date, week_start + _dt.timedelta(days=6))

    def test_guardrails_check_accepts_the_materialized_week_on_a_monday(self):
        today = _dt.date(2026, 9, 28)
        block = self._materialize(today)
        result = self._run_guardrails_check(block["_path"], today)
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertIn("ok", payload)

    def test_guardrails_check_accepts_the_materialized_week_on_a_sunday(self):
        today = _dt.date(2026, 10, 4)
        block = self._materialize(today)
        result = self._run_guardrails_check(block["_path"], today)
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertIn("ok", payload)

    def test_using_date_placeholder_directly_as_week_start_would_have_failed_on_a_sunday(self):
        """Non-régression documentée : le motif REJETÉ par cette revue de code
        (`week_start` = `{{DATE}}` au lieu de `{{PREV_WEEK_START}}`) échoue
        bien un dimanche — preuve que le correctif change un comportement
        réel, pas seulement de la documentation."""
        today = _dt.date(2026, 10, 4)  # dimanche
        buggy_week_start = (today - _dt.timedelta(days=7)).isoformat()
        self.assertNotEqual(_dt.date.fromisoformat(buggy_week_start).weekday(), 0)


class TestWeekStartPlusPlaceholder(unittest.TestCase):
    """`{{WEEK_START+N}}` (#172) : N jours après le lundi de la semaine ISO courante — N = 7 donne
    toujours un lundi, quel que soit le jour du run."""

    def test_offsets_from_monday_whatever_the_weekday(self):
        for today in (_dt.date(2026, 9, 28), _dt.date(2026, 10, 3), _dt.date(2026, 10, 4)):  # lundi, samedi, dimanche
            with self.subTest(today=today):
                tmp = Path(tempfile.mkdtemp(prefix="arc-evals-week-plus-"))
                self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
                (tmp / "planning").mkdir()
                (tmp / "planning" / "plan.md").write_text(
                    "{{WEEK_START}} {{WEEK_START+7}} {{WEEK_START+8}} {{WEEK_START+20}}", encoding="utf-8")
                with mock.patch.object(runner, "date", _fixed_date_class(today)):
                    runner._materialize_relative_dates(tmp)
                monday = today - _dt.timedelta(days=today.weekday())
                expected = " ".join((monday + _dt.timedelta(days=n)).isoformat() for n in (0, 7, 8, 20))
                self.assertEqual((tmp / "planning" / "plan.md").read_text(encoding="utf-8"), expected)
                self.assertEqual((monday + _dt.timedelta(days=7)).weekday(), 0)


if __name__ == "__main__":
    unittest.main()
