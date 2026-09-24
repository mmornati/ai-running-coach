"""Palier B — le générateur d'échantillons synthétiques (story #25) ne doit
jamais produire de donnée qui ressemble à une vraie séance Garmin.

Aucun modèle, aucun réseau : appelle directement les fonctions pures de
`tests.lib.synthetic`, ne lance aucun sous-processus.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO))

from tests.lib.synthetic import FAKE_ACTIVITY_ID_BASE, build, sample_session  # noqa: E402


class TestNoRealisticGarminId(unittest.TestCase):
    def test_fit_samples_use_the_obviously_fake_id_range(self):
        """Même convention que `build()` : un ID Garmin réel n'atteint jamais ce plafond."""
        with tempfile.TemporaryDirectory() as tmp:
            root = build(Path(tmp), days=6, sport="trail", seed=1, with_samples=True)
            files = list((root / "activities/fit").glob("*.json"))
            self.assertGreater(len(files), 0)
            import json
            for f in files:
                payload = json.loads(f.read_text(encoding="utf-8"))
                self.assertGreaterEqual(payload["activity_id"], FAKE_ACTIVITY_ID_BASE)


class TestNoGpsCoordinates(unittest.TestCase):
    def test_no_lat_lon_in_generated_records(self):
        """Pas de coordonnées GPS : ni domicile, ni lieu réel, ne peuvent y fuiter."""
        recs, _ = sample_session(seed=1, duration_s=30)
        for record in recs:
            self.assertNotIn("lat", record)
            self.assertNotIn("lon", record)


if __name__ == "__main__":
    unittest.main()
