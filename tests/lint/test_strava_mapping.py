"""Palier B — table de correspondance Garmin ↔ Strava (#164) : jamais d'outil deviné.

Chaque outil nommé dans la colonne `strava` de `AGENTS.md` (et chaque outil interdit en headless par
`daily-sync.sh` / la politique du chat) doit figurer dans `VERIFIED_TOOLS`, la liste relevée dans
le tarball npm 1.2.1 du serveur communautaire r-huijts/strava-mcp (dist/tools/*.js, champ `name`), publié
depuis le commit épinglé (`gitHead`). `get-athlete-shoes` / `get-segment-leaderboard` n'existent que dans des
commits postérieurs, non publiés : volontairement absents. Le connecteur officiel n'est volontairement pas
couvert : ses noms n'ont pas pu être vérifiés (OAuth requis).
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
PINNED_COMMIT = "a68112aa12a88909593db0f4b1ac0f6aebed6e3a"
PINNED_VERSION = "1.2.1"

VERIFIED_TOOLS = frozenset({
    "get-recent-activities", "get-all-activities", "get-activity-details", "get-activity-streams",
    "get-activity-laps", "get-activity-photos", "get-athlete-zones",
    "get-athlete-profile", "get-athlete-stats", "connect-strava", "disconnect-strava",
    "check-strava-connection", "star-segment", "explore-segments", "export-route-gpx",
    "export-route-tcx", "format-workout-file", "get-route", "get-segment", "get-segment-effort",
    "get-server-version", "list-athlete-clubs", "list-athlete-routes",
    "list-segment-efforts", "list-starred-segments",
})
ACTING_TOOLS = {"connect-strava", "disconnect-strava", "star-segment"}


def _strava_table_rows() -> list:
    text = (REPO / "AGENTS.md").read_text(encoding="utf-8")
    section = text.split("### Correspondance des outils — Garmin ↔ Strava", 1)[1]
    section = section.split("\n**Fonctionnalités/champs Garmin sans portage Strava", 1)[0]
    rows = [line for line in section.splitlines() if line.startswith("|")][2:]   # sans en-tête
    return [[c.strip() for c in row.strip("|").split("|")] for row in rows]


UNPUBLISHED_TOOLS = ("get-athlete-shoes", "get-segment-leaderboard")


class TestStravaMappingTable(unittest.TestCase):
    def test_unpublished_tools_are_never_presented_as_callable(self):
        for row in _strava_table_rows():
            for tool in UNPUBLISHED_TOOLS:
                if tool in row[2]:
                    self.fail(f"« {tool} » (non publié en 1.2.1) dans la colonne strava : {row[0]}")

    def test_table_is_present_with_a_strava_column(self):
        rows = _strava_table_rows()
        self.assertGreaterEqual(len(rows), 8)
        for row in rows:
            self.assertEqual(len(row), 4, row)

    def test_every_tool_of_the_strava_column_is_verified(self):
        for row in _strava_table_rows():
            for tool in re.findall(r"`([a-z][a-z-]+)`", row[2]):
                if "-" in tool and tool != "fit-download":        # nom d'outil à tirets (les paramètres camelCase n'en ont pas)
                    self.assertIn(tool, VERIFIED_TOOLS, f"outil non vérifié « {tool} » — ligne : {row[0]}")

    def test_unavailable_rows_say_so(self):
        for row in _strava_table_rows():
            if row[0].startswith(("Santé", "Calendrier", "Matériel attaché")):
                self.assertIn("aucun", row[2].lower(), row[0])

    def test_pin_is_documented_consistently(self):
        install = (REPO / "install.sh").read_text(encoding="utf-8")
        self.assertIn(f"@r-huijts/strava-mcp-server@{PINNED_VERSION}", install)
        self.assertIn(PINNED_COMMIT, install)
        for doc in ("AGENTS.md", "docs/strava-setup.md"):
            text = (REPO / doc).read_text(encoding="utf-8")
            self.assertIn(PINNED_VERSION, text, doc)
            self.assertIn(PINNED_COMMIT, text, doc)

    def test_acting_tools_are_denied_in_headless_and_asked_in_chat(self):
        sync = (REPO / "scripts/daily-sync.sh").read_text(encoding="utf-8")
        policy = (REPO / "config/chat-policy.toml").read_text(encoding="utf-8")
        for tool in ACTING_TOOLS:
            self.assertIn(tool, VERIFIED_TOOLS)
            self.assertIn(f"mcp__strava__{tool}", sync)
            self.assertIn(f'"{tool}"', sync)
            self.assertIn(f'"{tool}"', policy)

    def test_official_connector_is_marked_unverified(self):
        text = (REPO / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("mcp.strava.com/mcp", text)
        self.assertRegex(text, r"pas pu être vérifiés")


if __name__ == "__main__":
    unittest.main()
