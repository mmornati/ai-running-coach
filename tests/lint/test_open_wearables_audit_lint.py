"""Palier B — cohérence de l'audit Open Wearables (#216 / #217).

Deux commits distincts, à ne pas confondre :

* le commit **audité** (tag `0.9.0`), figé dans `docs/open-wearables.md` ;
* le commit **utilisé par le client** (`OW_REF` de `scripts/arc_openwearables.py`,
  #219/#220), qui peut légitimement être plus récent : #219 revérifie au dernier tag
  publié avant de le figer. La ligne « Version testée par le client » de la page
  doit alors être mise à jour avec lui, et c'est ce que ce test garantit.

La page ne doit jamais présenter la lecture santé d'Open Wearables comme déjà
branchée tant que ce n'est pas le cas.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
DOC = REPO / "docs" / "open-wearables.md"
AUDITED = "ff8527a52ad8a96cd1ebe8c19344295c934ae9dc"
MAIN_REREAD = "12941a4cb10fd77755d5b0007d8f267c5fea451b"
SHA = re.compile(r"\b[0-9a-f]{40}\b")
# `OW_REF = "<sha>"` (constante nommée, une par fichier consommateur).
OW_REF_ASSIGN = re.compile(r"""^\s*OW_REF\s*(?::\s*\w+\s*)?=\s*["']([0-9a-f]{40})["']""", re.M)
# Ligne parsable de la page : « Version testée par le client : `<sha>` (tag …) ».
TESTED_LINE = re.compile(r"Version testée par le client\s*:\s*`([0-9a-f]{40})`")
MONTHS = "janvier|février|mars|avril|mai|juin|juillet|août|septembre|octobre|novembre|décembre"
FR_DATE = re.compile(rf"\b\d{{1,2}}(?:er)? (?:{MONTHS}) \d{{4}}\b")
URL = re.compile(r"https?://[^\s)>\]`]+")
# Fichiers qui, une fois livrés, citeront le commit utilisé par le client.
CONSUMERS = ("scripts/arc_openwearables.py", "scripts/coach_doctor.py", "install.sh")
HOSTING = "the-momentum/open-wearables"


def _ow_refs(rel: str) -> set[str]:
    path = REPO / rel
    if not path.exists():
        return set()
    return set(OW_REF_ASSIGN.findall(path.read_text(encoding="utf-8")))


class TestOpenWearablesAudit(unittest.TestCase):
    def test_doc_cites_audited_commit(self):
        text = DOC.read_text(encoding="utf-8")
        self.assertIn(AUDITED, text)
        self.assertLessEqual(set(SHA.findall(text)), {AUDITED, MAIN_REREAD})

    def test_in_nav(self):
        nav = (REPO / "mkdocs.yml").read_text(encoding="utf-8")
        self.assertIn("open-wearables.md", nav)

    def test_doc_has_parseable_tested_version_line(self):
        text = DOC.read_text(encoding="utf-8")
        self.assertEqual(len(TESTED_LINE.findall(text)), 1, "une seule ligne « Version testée par le client »")

    def test_client_pin_matches_doc(self):
        """`OW_REF` du client (quand il existe) = la « Version testée » de la page.

        Ignoré tant que `scripts/arc_openwearables.py` ou sa constante `OW_REF`
        n'existent pas (livrés par #219/#220) ; ensuite, plus aucune échappatoire.
        """
        refs = _ow_refs("scripts/arc_openwearables.py")
        if not refs:
            self.skipTest("scripts/arc_openwearables.py / OW_REF pas encore livré (#219)")
        self.assertEqual(len(refs), 1, "OW_REF doit être défini une seule fois")
        (client,) = refs
        tested = TESTED_LINE.search(DOC.read_text(encoding="utf-8"))
        self.assertIsNotNone(tested)
        self.assertEqual(
            tested.group(1), client, "docs/open-wearables.md « Version testée par le client » ≠ OW_REF"
        )
        for rel in CONSUMERS[1:]:
            for other in _ow_refs(rel):
                self.assertEqual(other, client, f"{rel} : OW_REF différent de scripts/arc_openwearables.py")

    def test_health_integration_is_future_tense(self):
        # #221 (livraison de `[health].source`) devra mettre à jour ce test et la
        # page : « prévu » / « pas encore livrée » ne seront plus vrais à ce moment.
        text = DOC.read_text(encoding="utf-8")
        self.assertIn("prévu", text)
        self.assertNotRegex(text, r"(?i)\b(est|sont) (désormais )?(branchée?s?|livrée?s?)\b")
        self.assertIn("pas encore livrée", text)

    def test_every_external_fact_is_dated(self):
        text = DOC.read_text(encoding="utf-8")
        urls = [m for m in URL.finditer(text) if HOSTING not in m.group(0)]
        self.assertTrue(urls, "la page doit citer des sources externes")
        for m in urls:
            window = text[max(0, m.start() - 200) : m.end() + 200]
            self.assertRegex(window, FR_DATE, f"URL externe sans date à ±200 caractères : {m.group(0)}")
        self.assertIn("rapporté", text)


if __name__ == "__main__":
    unittest.main()
