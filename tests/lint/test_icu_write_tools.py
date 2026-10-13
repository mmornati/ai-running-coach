"""Palier B — les outils d'ÉCRITURE du serveur intervals.icu ne sont jamais appelables sans garde.

Quand le pin du serveur change (`INTERVALS_MCP_REF`), un nouvel outil d'écriture (v5.6.0 :
`icu_update_athlete_notes`) doit être classé écriture partout : refusé au run headless
(`scripts/lib/sync_tools.sh`), soumis à approbation dans le chat (`scripts/arc_chat_policy.py`),
et jamais prescrit par un prompt d'agent ou de skill.
"""

from __future__ import annotations

import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO / "scripts"))

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
    out = subprocess.run(
        ["bash", "-c", f'source "{REPO}/scripts/lib/sync_tools.sh"; sync_write_tools intervals'],
        capture_output=True, text=True, check=True).stdout
    return set(out.split())


class IcuWriteToolsTest(unittest.TestCase):
    def test_every_non_read_tool_is_denied_in_headless_sync(self):
        writes = _sync_write_tools()
        missing = sorted(t for t in _icu_tools() if not t.startswith(READ_PREFIXES) and t not in writes)
        self.assertFalse(missing, f"outils intervals non lus absents de SYNC_INTERVALS_WRITE_TOOLS : {missing}")

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
