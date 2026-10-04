"""Palier B — les prompts de la chaleur (#171) passent par le script, jamais par un calcul maison."""

from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))

import arc_heat as H  # noqa: E402

PROMPTS = (
    "agents/coach.md",
    "skills/weather-forecast/SKILL.md",
    "skills/garmin-workout-scheduling/SKILL.md",
    "skills/intervals-icu-best-practices/SKILL.md",
)


class TestHeatPromptsUseTheScript(unittest.TestCase):
    def test_prompts_mention_the_heat_command(self):
        for rel in PROMPTS:
            text = (REPO / rel).read_text(encoding="utf-8")
            self.assertIn("--heat", text, rel)
            self.assertIn("arc_workout_targets.py", text, rel)

    def test_coach_never_in_prompt_arithmetic(self):
        text = (REPO / "agents/coach.md").read_text(encoding="utf-8")
        self.assertIn("never your own arithmetic", text)
        self.assertIn("never keep the intensity at 🔴", text)


class TestWeatherThresholdsSingleSourced(unittest.TestCase):
    """Le tableau « Catégories & seuils » du skill `weather-forecast` et les constantes
    `WEATHER_*` de `arc_heat.py` doivent rester égaux (revue de code #171) : toute
    modification de l'un sans l'autre fait échouer ce test."""

    def _rows(self) -> dict:
        text = (REPO / "skills/weather-forecast/SKILL.md").read_text(encoding="utf-8")
        section = text.split("## Catégories & seuils", 1)[1].split("\n## ", 1)[0]
        rows = {}
        for emoji, key in (("🟡", "yellow"), ("🟠", "orange"), ("🔴", "red")):
            line = next(l for l in section.splitlines() if l.startswith("| " + emoji))
            rows[key] = line
        return rows

    @staticmethod
    def _low(line: str, unit_re: str, label: str) -> float:
        """Borne basse d'un critère (« T 22-28 °C » -> 22 ; « vent > 50 km/h » -> 50)."""
        m = re.search(label + r"\s*(?:>\s*)?(\d+(?:[.,]\d+)?)(?:-\d+(?:[.,]\d+)?)?\s*" + unit_re, line)
        if not m:
            raise AssertionError(f"critère {label!r} introuvable dans : {line}")
        return float(m.group(1).replace(",", "."))

    def test_temperature_thresholds(self):
        rows = self._rows()
        self.assertEqual(self._low(rows["yellow"], "°C", "T"), H.WEATHER_YELLOW_C)
        self.assertEqual(self._low(rows["orange"], "°C", "T"), H.WEATHER_ORANGE_C)
        self.assertEqual(self._low(rows["red"], "°C", "T"), H.WEATHER_RED_C)

    def test_non_thermal_thresholds(self):
        rows = self._rows()
        levels = ("yellow", "orange", "red")
        self.assertEqual(tuple(self._low(rows[k], "km/h", "vent") for k in levels), H.WEATHER_WIND_KMH)
        self.assertEqual(tuple(self._low(rows[k], "mm", "pluie") for k in levels), H.WEATHER_PRECIP_MM)
        self.assertEqual(tuple(self._low(rows[k], r"(?:\*|\||$)", "UV") for k in ("yellow", "orange")),
                         H.WEATHER_UV)
        self.assertNotIn("UV", rows["red"])   # pas de seuil UV 🔴 : `arc_heat` n'en invente pas
        self.assertIn("orage", rows["red"])   # orage -> 🔴 (`thunderstorm`)

    def test_skill_points_to_the_script(self):
        text = (REPO / "skills/weather-forecast/SKILL.md").read_text(encoding="utf-8")
        self.assertIn("scripts/arc_heat.py", text)
        self.assertIn("toute modification du tableau doit y être reportée", text)


if __name__ == "__main__":
    unittest.main()
