"""Palier B — les outils d'ÉCRITURE du serveur intervals.icu ne sont jamais appelables sans garde.

Quand le pin du serveur change (`INTERVALS_MCP_REF`), un nouvel outil d'écriture (v5.6.0 :
`icu_update_athlete_notes`) doit être classé écriture partout : refusé au run headless
(`scripts/arc_sync_tools.py`), soumis à approbation dans le chat (`scripts/arc_chat_policy.py`),
et jamais prescrit par un prompt d'agent ou de skill.
"""

from __future__ import annotations

import fnmatch
import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import arc_sync_tools  # noqa: E402
from arc_chat_policy import Policy  # noqa: E402

READ_PREFIXES = ("icu_get_", "icu_search_", "icu_list_")
# Outils d'écriture que le projet n'appelle jamais, même avec « oui » : aucun prompt ne doit les citer.
NEVER_CALLED = ("icu_update_athlete_notes",)


def _icu_tools() -> set:
    """Liste ICU_TOOLS du lint de parité (outils enregistrés par le serveur épinglé)."""
    text = (REPO / "tests/lint/test_data_source_parity.py").read_text(encoding="utf-8")
    block = re.search(r'ICU_TOOLS = frozenset\("""(.*?)"""', text, re.DOTALL).group(1)
    return set(block.split())


def _sync_write_tools() -> set:
    return set(arc_sync_tools.write_tools("intervals"))


def _opencode_permission(tmp: Path) -> dict:
    """Exécute le générateur OC_CONFIG_PY de daily-sync.sh avec les trois serveurs sportifs."""
    text = (REPO / "scripts/daily-sync.sh").read_text(encoding="utf-8")
    code = re.search(r"^OC_CONFIG_PY='\n(.*?)^'$", text, re.DOTALL | re.MULTILINE).group(1)
    mcp = tmp / "mcp.json"
    mcp.write_text(json.dumps({"mcpServers": {n: {"command": "true"} for n in ("garmin", "intervals", "strava")}}))
    out = subprocess.run(
        [sys.executable, "-c", code, "openrouter/x/y", "", "", str(mcp), "",
         " ".join(arc_sync_tools.write_tools("garmin")),
         " ".join(arc_sync_tools.write_tools("intervals")),
         " ".join(arc_sync_tools.write_tools("strava"))],
        capture_output=True, text=True, check=True).stdout
    return json.loads(out)["permission"]


def _denied(permission: dict, name: str) -> bool:
    """Vrai si une règle « deny » (nom exact ou motif OpenCode) couvre ce nom d'outil MCP."""
    return any(v == "deny" and fnmatch.fnmatchcase(name, k) for k, v in permission.items())


class OpencodeHeadlessDenyTest(unittest.TestCase):
    """OpenCode expose un outil MCP sous `<serveur>_<outil>` : chaque écriture doit être refusée sous CE nom."""

    @classmethod
    def setUpClass(cls):
        with tempfile.TemporaryDirectory() as tmp:
            cls.permission = _opencode_permission(Path(tmp))

    def test_every_non_read_intervals_tool_is_denied(self):
        for tool in sorted(t for t in _icu_tools() if not t.startswith(READ_PREFIXES)):
            self.assertTrue(_denied(self.permission, f"intervals_{tool}"), f"intervals_{tool}")

    def test_intervals_read_tools_are_not_denied(self):
        for tool in sorted(t for t in _icu_tools() if t.startswith(READ_PREFIXES)):
            self.assertFalse(_denied(self.permission, f"intervals_{tool}"), f"intervals_{tool}")

    def test_garmin_write_tools_are_denied(self):
        install = (REPO / "install.sh").read_text(encoding="utf-8")
        tools = set()
        for var in ("GARMIN_TOOL_WHITELIST", "GARMIN_CYCLE_TOOLS", "GARMIN_NUTRITION_TOOLS"):
            tools |= set(re.search(rf'^{var}="([^"]+)"', install, re.M).group(1).split(","))
        prefixes = arc_sync_tools.GARMIN_WRITE_PREFIXES
        writes = sorted(t for t in tools if t.startswith(prefixes))
        self.assertTrue(writes)
        for tool in writes:
            self.assertTrue(_denied(self.permission, f"garmin_{tool}"), f"garmin_{tool}")
        self.assertFalse(_denied(self.permission, "garmin_get_activities"))

    def test_strava_write_tools_are_denied(self):
        for tool in arc_sync_tools.STRAVA_WRITE_TOOLS:
            self.assertTrue(_denied(self.permission, f"strava_{tool}"), f"strava_{tool}")
        self.assertFalse(_denied(self.permission, "strava_get-recent-activities"))


class IcuWriteToolsTest(unittest.TestCase):
    def test_every_non_read_tool_is_denied_in_headless_sync(self):
        writes = _sync_write_tools()
        missing = sorted(t for t in _icu_tools() if not t.startswith(READ_PREFIXES) and t not in writes)
        self.assertFalse(missing, f"outils intervals non lus absents de arc_sync_tools.INTERVALS_WRITE_TOOLS : {missing}")

    def test_every_non_read_tool_asks_in_chat(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp).resolve()
            (ws / "planning").mkdir()
            policy = Policy.load(REPO, ws)
            for tool in sorted(t for t in _icu_tools() if not t.startswith(READ_PREFIXES)):
                self.assertEqual(policy.decide(f"mcp:intervals.{tool}", {}), "ask", tool)

    def test_never_called_tools_are_known_and_not_prescribed(self):
        self.assertTrue(set(NEVER_CALLED) <= _icu_tools())
        files = [*sorted((REPO / "agents").glob("*.md")), *sorted((REPO / "skills").glob("*/SKILL.md"))]
        for path in files:
            text = path.read_text(encoding="utf-8")
            for tool in NEVER_CALLED:
                self.assertNotIn(tool, text, f"{path.relative_to(REPO)} cite {tool}")


if __name__ == "__main__":
    unittest.main()
