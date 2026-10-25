"""Palier B — captures de la documentation reproductibles (`scripts/docs_capture.py`) : la table nom → vue
couvre exactement les images de `docs/assets/dashboard/`, et le profil vidéo reste figé sur l'ancien design.
Lint pur : aucun navigateur, aucun serveur.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO / "scripts"))
import docs_capture as DC  # noqa: E402
import video_capture as VC  # noqa: E402
import video_demo_workspace as VW  # noqa: E402


class TestDocsCaptureTable(unittest.TestCase):
    def test_table_covers_every_image(self):
        names = [s["name"] for s in DC.SHOTS]
        self.assertEqual(len(names), len(set(names)), "nom en double dans SHOTS")
        on_disk = {p.stem for p in (REPO / "docs/assets/dashboard").glob("*.webp")}
        self.assertEqual(set(names), on_disk)

    def test_every_row_is_well_formed(self):
        for s in DC.SHOTS:
            self.assertIn(s["fmt"], DC.FORMATS, s["name"])
            if s["fmt"] in ("mobile", "thumb"):
                self.assertEqual(s["clip"], "viewport", s["name"])

    def test_dark_only_for_the_dark_image(self):
        dark = [s["name"] for s in DC.SHOTS if s.get("scheme") == "dark"]
        self.assertEqual(dark, ["sombre-forme"])

    def test_no_dev_artifacts_in_captures(self):
        """Ni version `git describe`, ni lien « Ancien design », ni curseur de frappe sur les images."""
        for sel in ("#version", "#update", ".rk-classic", "is-streaming", "#stop"):
            self.assertIn(sel, DC.DOCS_CSS)
        self.assertIn("rk-navgroup--debt", DC.DEBT_CSS)
        self.assertEqual([s["name"] for s in DC.SHOTS if s.get("debt")], ["fichiers"])
        self.assertIn('"ARC_UPDATE_CHECK": "off"', Path(DC.__file__).read_text(encoding="utf-8"))

    def test_docs_use_the_real_names(self):
        views = (REPO / "docs/dashboard/views.md").read_text(encoding="utf-8")
        for name in ("sante-foulee", "sombre-forme", "seance-tours"):
            self.assertIn(f"assets/dashboard/{name}.webp", views)


class TestVideoDesign(unittest.TestCase):
    def test_video_profile_is_frozen_on_classic(self):
        self.assertEqual(VC.DESIGN, "classic")
        self.assertIn("arc-design-v14", VC.DESIGN_INIT_JS)
        self.assertIn("classic", VC.DESIGN_INIT_JS)

    def test_docs_variant_dates_exist(self):
        self.assertLess(VW.ULTRA_ACTIVITY_DATE, VW.TODAY)
        self.assertLess(VW.LAPS_ACTIVITY_DATE, VW.TODAY)


if __name__ == "__main__":
    unittest.main()
