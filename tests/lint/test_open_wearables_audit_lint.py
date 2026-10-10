"""Palier B — cohérence de l'audit Open Wearables (#216 / #217).

Le commit épinglé cité dans `docs/open-wearables.md` doit être le même partout où
il apparaîtra (doc, puis `scripts/arc_openwearables.py` et `scripts/coach_doctor.py`
quand ces stories seront livrées), et la page ne doit jamais présenter la lecture
santé d'Open Wearables comme déjà branchée tant que ce n'est pas le cas.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
DOC = REPO / "docs" / "open-wearables.md"
PINNED = "ff8527a52ad8a96cd1ebe8c19344295c934ae9dc"
MAIN_REREAD = "12941a4cb10fd77755d5b0007d8f267c5fea451b"
SHA = re.compile(r"\b[0-9a-f]{40}\b")
# Fichiers qui, une fois livrés, citeront le commit épinglé d'Open Wearables.
CONSUMERS = ("scripts/arc_openwearables.py", "scripts/coach_doctor.py")


class TestOpenWearablesAudit(unittest.TestCase):
    def test_doc_cites_pinned_commit(self):
        text = DOC.read_text(encoding="utf-8")
        self.assertIn(PINNED, text)
        self.assertLessEqual(set(SHA.findall(text)), {PINNED, MAIN_REREAD})

    def test_in_nav(self):
        nav = (REPO / "mkdocs.yml").read_text(encoding="utf-8")
        self.assertIn("open-wearables.md", nav)

    def test_pinned_commit_identical_where_present(self):
        for rel in CONSUMERS:
            path = REPO / rel
            if not path.exists():
                continue
            shas = set(SHA.findall(path.read_text(encoding="utf-8")))
            if "open-wearables" in path.read_text(encoding="utf-8").lower() and shas:
                self.assertIn(PINNED, shas, f"{rel} : commit Open Wearables différent de la doc")

    def test_health_integration_is_future_tense(self):
        text = DOC.read_text(encoding="utf-8")
        self.assertIn("prévu", text)
        self.assertNotRegex(text, r"(?i)\b(est|sont) (désormais )?(branchée?s?|livrée?s?)\b")
        self.assertIn("pas encore livrée", text)

    def test_every_external_fact_is_dated(self):
        text = DOC.read_text(encoding="utf-8")
        self.assertIn("10 octobre 2026", text)
        self.assertIn("rapporté", text)


if __name__ == "__main__":
    unittest.main()
