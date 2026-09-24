#!/usr/bin/env python3
"""Palier D — `render_results.py` (#29) : rendu déterministe de `RESULTS.md`.

Pur, stdlib, sans sous-processus : `render()` et `parse_previous()` ne touchent
ni disque ni réseau, ce qui permet de les verrouiller ici sans lancer le
moindre modèle — c'est ce module qui transforme le JSON écrit par
`runner.record_result` en la même table Markdown que celle, versionnée à la
main, de `tests/evals/RESULTS.md`.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from tests.evals import render_results  # noqa: E402

META = {"date": "2026-09-24 03:17 UTC", "model": "claude-haiku-4-5-20251001", "runner": "claude -p",
        "repeat": 3, "threshold": 2 / 3}


class TestRender(unittest.TestCase):
    def test_case_never_run_shows_placeholder_row(self):
        text = render_results.render({}, ["never-run"], META)
        self.assertIn("| `never-run` | — | — |", text)

    def test_passing_case_shows_ratio_and_check(self):
        results = {"ok-case": {"passed": 3, "attempts": 3, "rate": 1.0}}
        text = render_results.render(results, ["ok-case"], META)
        self.assertIn("| `ok-case` | 3/3 | ✅ |", text)

    def test_failing_case_below_threshold_shows_cross(self):
        results = {"bad-case": {"passed": 1, "attempts": 3, "rate": 1 / 3}}
        text = render_results.render(results, ["bad-case"], META)
        self.assertIn("| `bad-case` | 1/3 | ❌ |", text)

    def test_case_exactly_at_threshold_passes(self):
        """2/3 est le seuil par défaut : `>=`, pas `>`."""
        results = {"edge-case": {"passed": 2, "attempts": 3, "rate": 2 / 3}}
        text = render_results.render(results, ["edge-case"], META)
        self.assertIn("| `edge-case` | 2/3 | ✅ |", text)

    def test_header_shows_fraction_not_decimal(self):
        text = render_results.render({}, [], META)
        self.assertIn("| **Seuil de réussite** | 2/3 |", text)
        self.assertIn("| **Répétitions** | 3 par scénario |", text)
        self.assertIn("`claude-haiku-4-5-20251001`", text)

    def test_regression_marked_when_rate_drops(self):
        results = {"flaky": {"passed": 2, "attempts": 3, "rate": 2 / 3}}
        previous = {"flaky": 1.0}  # 3/3 la dernière fois
        text = render_results.render(results, ["flaky"], META, previous)
        self.assertIn("⚠️ régression", text)

    def test_no_regression_marker_when_rate_holds_or_improves(self):
        results = {"stable": {"passed": 3, "attempts": 3, "rate": 1.0}}
        previous = {"stable": 1.0}
        text = render_results.render(results, ["stable"], META, previous)
        self.assertNotIn("⚠️", text)

    def test_no_regression_marker_without_previous_data(self):
        """Un cas neuf n'a rien à quoi se comparer — jamais une fausse régression."""
        results = {"brand-new": {"passed": 1, "attempts": 3, "rate": 1 / 3}}
        text = render_results.render(results, ["brand-new"], META, previous={})
        self.assertNotIn("⚠️", text)

    def test_placeholder_note_only_when_nothing_ran(self):
        self.assertIn("Pas encore de relevé", render_results.render({}, ["x"], META))
        results = {"x": {"passed": 3, "attempts": 3, "rate": 1.0}}
        self.assertNotIn("Pas encore de relevé", render_results.render(results, ["x"], META))

    def test_deterministic_given_same_input(self):
        results = {"a": {"passed": 2, "attempts": 3, "rate": 2 / 3}, "b": {"passed": 3, "attempts": 3, "rate": 1.0}}
        first = render_results.render(results, ["a", "b"], META)
        second = render_results.render(results, ["a", "b"], META)
        self.assertEqual(first, second)


class TestParsePrevious(unittest.TestCase):
    def test_extracts_ratio_from_row(self):
        markdown = "| `health-full-triad` | 3/3 | ✅ |\n"
        previous = render_results.parse_previous(markdown)
        self.assertEqual(previous, {"health-full-triad": 1.0})

    def test_placeholder_row_is_absent_not_zero(self):
        markdown = "| `never-run` | — | — |\n"
        previous = render_results.parse_previous(markdown)
        self.assertNotIn("never-run", previous)

    def test_ignores_unrelated_lines(self):
        markdown = "# Résultats du palier C\n\nTexte libre | pas un tableau\n"
        self.assertEqual(render_results.parse_previous(markdown), {})

    def test_round_trip_with_render(self):
        """Ce que `render()` produit doit être ce que `parse_previous()` relit."""
        results = {"round-trip": {"passed": 2, "attempts": 3, "rate": 2 / 3}}
        rendered = render_results.render(results, ["round-trip"], META)
        previous = render_results.parse_previous(rendered)
        self.assertAlmostEqual(previous["round-trip"], 2 / 3)


class TestMinPasses(unittest.TestCase):
    def test_default_two_thirds_of_three(self):
        self.assertEqual(render_results._min_passes(2 / 3, 3), 2)

    def test_full_unanimity(self):
        self.assertEqual(render_results._min_passes(1.0, 5), 5)

    def test_floating_point_does_not_round_up_spuriously(self):
        """0.667 * 3 flirte avec 2.000000001 en flottant : jamais 3."""
        self.assertEqual(render_results._min_passes(2 / 3, 3), 2)


if __name__ == "__main__":
    unittest.main()
