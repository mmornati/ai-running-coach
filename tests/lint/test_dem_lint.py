"""Palier B — correction altimétrique par MNT (#176) : défauts prudents, documentation,
vie privée, attribution.

Aucun réseau, aucun modèle : lecture statique de la configuration, des prompts et des docs.
"""

from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO / "tests/lint"))

from test_config_schema import CONFIG  # noqa: E402


def read(rel: str) -> str:
    return (REPO / rel).read_text(encoding="utf-8")


class TestDemDefaultsAreConservative(unittest.TestCase):
    def test_config_defaults_send_nothing(self):
        self.assertEqual(CONFIG["elevation"]["dem"], "off")
        self.assertIn(str(CONFIG["privacy"]["dem_for_activities"]).lower(), ("false",))

    def test_module_is_stdlib_and_makes_no_call_at_import(self):
        text = read("scripts/arc_dem.py")
        for forbidden in ("import requests", "import httpx", "import aiohttp"):
            self.assertNotIn(forbidden, text)
        self.assertIn("def default_http_get", text)

    def test_only_documented_hosts_are_contacted(self):
        text = read("scripts/arc_dem.py")
        hosts = set(re.findall(r"https://([a-z0-9.-]+)/", text))
        self.assertTrue({"data.geopf.fr", "api.open-meteo.com"} <= hosts)
        self.assertEqual(hosts - {"data.geopf.fr", "api.open-meteo.com", "github.com"}, set())


class TestDemDocumentation(unittest.TestCase):
    def test_page_exists_and_is_in_nav(self):
        self.assertIn("elevation.md", read("mkdocs.yml"))
        page = read("docs/elevation.md")
        for needle in ("Etalab 2.0", "Copernicus", "10.5270/ESA-c5d3d65", "dem_for_activities",
                       "coordonnées", "dem_trim_m", "protège qu'en partie", "non commercial",
                       "Hors ligne", "Hypothèses et limites"):
            self.assertIn(needle, page, needle)

    def test_configuration_and_agents_files_mention_the_feature(self):
        self.assertIn("[elevation]", read("docs/configuration.md"))
        self.assertIn("dem_for_activities", read("AGENTS.md"))
        for rel in ("skills/gpx-analysis/SKILL.md", "agents/course-strategist.md",
                    "docs/skills/gpx-analysis.md", "docs/agents/course-strategist.md"):
            self.assertIn("--dem", read(rel), rel)

    def test_prompts_keep_the_privacy_rule(self):
        skill = read("skills/gpx-analysis/SKILL.md")
        self.assertIn("dem_for_activities", skill)
        self.assertRegex(skill, r"Attribution")
        strategist = read("agents/course-strategist.md")
        self.assertIn("D+ fichier / D+ MNT", strategist)
        self.assertRegex(strategist, r"jamais d'envoi silencieux")

    def test_chat_policy_declares_the_new_flags(self):
        policy = read("config/chat-policy.toml")
        self.assertIn('"--dem"', policy)
        self.assertIn('"--dem-step"', policy)


if __name__ == "__main__":
    unittest.main()
