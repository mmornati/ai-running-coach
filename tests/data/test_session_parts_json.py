"""Palier D — `analyze_session_parts.py --activity-json` (session-parts-analyzer).

Régression : `_records_from_fit_json` soustrayait directement les horodatages lus
depuis le JSON (`<id>.records.json` écrit par `download_fit.py` avec
`json.dumps(default=str)`, donc des CHAÎNES) -> TypeError. Il ignorait aussi le
champ FIT `distance` (vitesse intégrée à la place) et `enhanced_speed`.

Familles de tests :
- horodatages chaînes (format `default=str` et ISO 8601), t0 = plus petit
  horodatage (pas le premier enregistrement) ;
- `distance` FIT reprise telle quelle, `enhanced_speed` utilisé ;
- conversion semi-cercles -> degrés ;
- formes acceptées : liste brute, objet `{"records": [...]}`, échantillons
  normalisés (`t_s`) ;
- CLI `--activity-json` de bout en bout, sans exception.

Données entièrement fictives ; positions dans la zone sûre du Pacifique Sud
(voir `tests/lint/test_synthetic_no_real_data.py`).
"""

from __future__ import annotations

import importlib.util
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "skills" / "session-parts-analyzer" / "scripts" / "analyze_session_parts.py"

_spec = importlib.util.spec_from_file_location("analyze_session_parts", SCRIPT)
ASP = importlib.util.module_from_spec(_spec)
# Enregistré avant exécution : @dataclass résout ses annotations via sys.modules.
sys.modules[_spec.name] = ASP
_spec.loader.exec_module(ASP)

# Position fictive (zone sûre), convertie en semi-cercles FIT.
lat_semicircles = round(-40.0 / 180.0 * 2 ** 31)
lon_semicircles = round(-130.0 / 180.0 * 2 ** 31)


def _raw_payload():
    """Dump fitparse fictif tel que relu depuis `<id>.records.json` : horodatages
    chaînes, `enhanced_speed` seul (pas de `speed`), `distance` cumulée FIT
    volontairement différente de l'intégrale de la vitesse, un enregistrement
    hors d'ordre (le plus ancien arrive en second)."""
    return [
        {"timestamp": "2026-01-01 10:00:01", "enhanced_speed": 3.0, "distance": 12.0,
         "heart_rate": 140, "enhanced_altitude": 101.0, "cadence": 85,
         "position_lat": lat_semicircles, "position_long": lon_semicircles},
        {"timestamp": "2026-01-01 10:00:00", "enhanced_speed": 3.0, "distance": 10.0,
         "heart_rate": 138, "enhanced_altitude": 100.0, "cadence": 84,
         "position_lat": lat_semicircles, "position_long": lon_semicircles},
        {"timestamp": "2026-01-01T10:00:02", "enhanced_speed": 4.0, "distance": 15.0,
         "heart_rate": 142, "enhanced_altitude": 102.0, "cadence": 86,
         "position_lat": lat_semicircles, "position_long": lon_semicircles},
        {"timestamp": "2026-01-01 10:00:05", "enhanced_speed": 4.0, "distance": 27.0,
         "heart_rate": 145, "enhanced_altitude": 103.0, "cadence": 87,
         "position_lat": lat_semicircles, "position_long": lon_semicircles},
    ]


class TestRecordsFromFitJson(unittest.TestCase):

    def test_string_timestamps_do_not_raise_and_t0_is_min(self):
        # Aller-retour JSON réel : les horodatages sont bien des chaînes.
        data = json.loads(json.dumps(_raw_payload()))
        records = ASP._records_from_fit_json(data)
        self.assertEqual([r.t for r in records], [0.0, 1.0, 2.0, 5.0])

    def test_fit_distance_and_enhanced_speed_are_used(self):
        records = ASP._records_from_fit_json(_raw_payload())
        self.assertEqual([r.distance_m for r in records], [10.0, 12.0, 15.0, 27.0])
        self.assertAlmostEqual(records[2].speed_kmh, 4.0 * 3.6)
        self.assertEqual(records[0].hr, 138)
        self.assertEqual(records[0].elevation_m, 100.0)

    def test_semicircles_converted_to_degrees(self):
        record = ASP._records_from_fit_json(_raw_payload())[0]
        self.assertAlmostEqual(record.lat, -40.0, places=5)
        self.assertAlmostEqual(record.lon, -130.0, places=5)

    def test_object_form_with_records_key(self):
        records = ASP._records_from_fit_json({"records": _raw_payload()})
        self.assertEqual(len(records), 4)

    def test_distance_integrated_over_real_gap_when_absent(self):
        # Sans `distance` FIT : intégration vitesse × écart de temps réel (3 s ici).
        data = [
            {"timestamp": "2026-01-01 10:00:00", "enhanced_speed": 2.0},
            {"timestamp": "2026-01-01 10:00:03", "enhanced_speed": 2.0},
        ]
        records = ASP._records_from_fit_json(data)
        self.assertEqual([r.distance_m for r in records], [0.0, 6.0])

    def test_normalised_samples_accepted(self):
        data = {"records": [
            {"t_s": 0, "distance_m": 0.0, "speed_ms": 3.0, "hr_bpm": 140.0,
             "lat_deg": -40.0, "lon_deg": -130.0},
            {"t_s": 1, "distance_m": 3.0, "speed_ms": 3.0, "hr_bpm": 141.0,
             "lat_deg": -40.0, "lon_deg": -130.0},
        ]}
        records = ASP._records_from_fit_json(data)
        self.assertEqual([r.t for r in records], [0.0, 1.0])
        self.assertEqual(records[1].distance_m, 3.0)
        self.assertEqual(records[0].lat, -40.0)

    def test_empty_payload(self):
        self.assertEqual(ASP._records_from_fit_json([]), [])
        self.assertEqual(ASP._records_from_fit_json({"records": []}), [])


class TestCliActivityJson(unittest.TestCase):

    def test_cli_runs_on_string_timestamp_payload(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "fictif.records.json"
            src.write_text(json.dumps(_raw_payload()), encoding="utf-8")
            out = Path(tmp) / "rapport.md"
            with redirect_stdout(io.StringIO()):
                code = ASP.main(["--activity-json", str(src), "--part", "stride",
                                 "--output", str(out), "--quiet"])
            # 1 = aucune portion détectée (séance trop courte) — l'essentiel : pas d'exception.
            self.assertIn(code, (0, 1))
            self.assertTrue(out.exists())


if __name__ == "__main__":
    unittest.main()
