"""Palier D — mode « GAP » de la carte de la page séance (`web/js/map.js`).

`resampleByDistance` tire l'allure ajustée à la pente de l'allure de sa fenêtre glissante
divisée par le facteur de pente moyen `gf` renvoyé par le serveur (`arc_gap.gap_factor`) :
aucune seconde copie du modèle de Minetti côté navigateur. Le module est exécuté tel quel
par `node` (copié en `.mjs`, ses fonctions pures ne touchent ni `window` ni `document`),
même discipline que `test_dashboard_days_to_weeks.py`.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
MAP_JS = REPO / "web/js/map.js"
NODE = shutil.which("node")


def _run(track: dict) -> dict:
    """`resampleByDistance` puis `colorModes` sur `track` ; rend le profil et les modes offerts."""
    with tempfile.TemporaryDirectory() as tmp:
        module = Path(tmp) / "map.mjs"
        module.write_text(MAP_JS.read_text(encoding="utf-8"), encoding="utf-8")
        script = (f"import {{ resampleByDistance, colorModes }} from {json.dumps(module.as_uri())};\n"
                  f"const p = resampleByDistance({json.dumps(track)});\n"
                  "console.log(JSON.stringify({ pace: p.pace, gap: p.gap, modes: Object.keys(colorModes(p, null)) }));")
        result = subprocess.run([NODE, "--input-type=module", "-e", script],
                                capture_output=True, text=True, timeout=15)
    if result.returncode != 0:
        raise AssertionError(f"node a échoué : {result.stderr}")
    return json.loads(result.stdout)


def _track(n: int = 400, gf=None) -> dict:
    # 3 m/s en continu (allure 333 s/km), un point toutes les 5 s.
    out = {"d": [i * 15.0 for i in range(n)], "t": [i * 5.0 for i in range(n)],
           "alt": [100.0] * n, "hr": [140] * n, "cad": [170] * n}
    if gf is not None:
        out["gf"] = gf
    return out


@unittest.skipUnless(NODE, "node absent de la machine — voir CONTRIBUTING.md (node --check)")
class TestMapGap(unittest.TestCase):
    def test_gap_is_pace_divided_by_window_factor(self):
        # Première moitié à facteur 1,5 (montée), seconde à 1 (plat).
        out = _run(_track(gf=[1.5] * 200 + [1.0] * 200))
        j_up, j_flat = 50, len(out["pace"]) - 50
        self.assertAlmostEqual(out["gap"][j_up], out["pace"][j_up] / 1.5, places=3)
        self.assertAlmostEqual(out["gap"][j_flat], out["pace"][j_flat], places=3)
        self.assertIn("gap", out["modes"])

    def test_no_factor_means_no_gap_mode(self):
        """Hors famille course à pied, le serveur n'envoie pas `gf` : pas de mode, jamais une
        GAP égale à l'allure brute."""
        out = _run(_track())
        self.assertTrue(all(v is None for v in out["gap"]))
        self.assertNotIn("gap", out["modes"])
        self.assertIn("pace", out["modes"])

    def test_unknown_factor_everywhere_gives_no_gap(self):
        out = _run(_track(gf=[None] * 400))
        self.assertTrue(all(v is None for v in out["gap"]))


if __name__ == "__main__":
    unittest.main()
