"""Palier D — workspace de démonstration des vidéos (`scripts/video_demo_workspace.py`).

Construit « Camille » sans échantillons FIT (rapide), valide chaque fichier au contrat `arc` et vérifie
quelques invariants de l'histoire (HRV 38 le 2026-09-29, objectif au 2026-11-22, séance du dimanche…).
"""

from __future__ import annotations

import json
import re
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))

import arc_contract as C  # noqa: E402
import video_demo_workspace as V  # noqa: E402
from tests.lib.synthetic import FAKE_ACTIVITY_ID_BASE  # noqa: E402

PROSE_ONLY = {"Runner_Profile.md", "active_objective.md"}


def block(path: Path) -> dict:
    return V.read_block(path)


class TestDemoWorkspace(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.root = V.build_demo(Path(cls._tmp.name) / "ws", with_samples=False)

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def test_tous_les_fichiers_sont_au_contrat(self):
        checked = 0
        for folder in ("activities", "medical", "nutrition", "planning", "rapports", "gear"):
            for path in sorted((self.root / folder).glob("*.md")):
                if path.name in PROSE_ONLY:
                    continue
                errors, _warnings = C.validate(block(path))
                self.assertEqual(errors, [], f"{path.relative_to(self.root)} : {errors}")
                checked += 1
        self.assertGreater(checked, 100)

    def test_bilan_matinal(self):
        h = block(self.root / "medical/2026-09-29_health.md")
        self.assertEqual((h["hrv_overnight_ms"], h["resting_hr_bpm"], h["readiness_score"]), (38, 52, 34))
        self.assertEqual((h["hrv_baseline_low_ms"], h["hrv_baseline_high_ms"]), (52, 70))
        self.assertEqual((h["sleep_total_s"], h["verdict"]), (22320, "amber"))
        for day in ("2026-09-26", "2026-09-27", "2026-09-28"):
            self.assertLess(block(self.root / f"medical/{day}_health.md")["hrv_overnight_ms"], 52)
        d = block(self.root / "planning/2026-09-29_decision_bilan-matinal.md")
        self.assertEqual((d["trigger"], d["outcome"]), ("morning_check", "applied"))
        g = block(self.root / "planning/2026-09-28_decision_garde-fou-qualite-consecutive.md")
        self.assertEqual(g["rule_ids"], ["r7_consecutive_quality"])

    def test_objectif_et_profil(self):
        text = (self.root / "planning/active_objective.md").read_text(encoding="utf-8")
        self.assertIn("- **Date** : 2026-11-22", text)
        self.assertIn("Trail des Crêtes", text)
        profile = (self.root / "planning/Runner_Profile.md").read_text(encoding="utf-8")
        for needle in ("- **FC max** : 188", "Crête Pro (bleue)", "id: route-legere", "Val-d'Orée"):
            self.assertIn(needle, profile)
        self.assertNotIn("<!--", profile)

    def test_semaine_et_dimanche(self):
        week = block(self.root / "planning/Semaine_2026-09-28.md")
        by_date = {}
        for s in week["sessions"]:
            by_date.setdefault(s["date"], []).append(s["status"])
        self.assertIn("moved", by_date["2026-09-30"])
        self.assertEqual(by_date["2026-10-01"], ["planned"])
        act = block(self.root / "activities/2026-09-27_trail.md")
        self.assertEqual((act["distance_m"], act["elevation_gain_m"], act["avg_hr_bpm"], act["rpe"]), (18200, 820, 142, 7))
        self.assertEqual((act["carbs_g"], act["fluid_intake_ml"], act["gear_id"]), (50, 500, "crete-pro-bleue"))
        self.assertGreaterEqual(act["garmin_activity_id"], FAKE_ACTIVITY_ID_BASE)
        self.assertEqual(sum(r[2] for r in act["splits"]), 820)

    def test_plan_de_course(self):
        plan = block(next((self.root / "planning").glob("*plan-de-course*.md")))
        self.assertEqual(plan["scenarios"], {"ambitious": 20280, "realistic": 21900, "safe": 24000})
        self.assertEqual([a["km"] for a in plan["aid_stations"]], [12, 24, 34])

    def test_plan_ultra_de_nuit(self):
        """Épisode 14 : plan calculé par le vrai moteur, nuit et technicité présentes, rien d'autre ne bouge."""
        plan = block(self.root / "planning/2026-09-27_ultra_ultra-des-cretes.md")
        self.assertEqual((plan["race_date"], plan["timezone"]), ("2027-10-30", "Europe/Paris"))
        self.assertEqual([a["km"] for a in plan["aid_stations"]], [13, 28, 41, 55])
        self.assertTrue(all("take" in a and "cutoff" in a for a in plan["aid_stations"]))
        segs = plan["segments"]
        self.assertTrue(any(s["night_fraction"]["realistic"] > 0 for s in segs))
        self.assertTrue(any(s["technicity"]["coef"] > 1.1 for s in segs))
        self.assertLessEqual(plan["scenarios"]["ambitious"], plan["scenarios"]["realistic"])
        self.assertLessEqual(plan["scenarios"]["realistic"], plan["scenarios"]["safe"])

    def test_inspections_et_photos(self):
        files = sorted((self.root / "gear").glob("*_inspection.md"))
        self.assertEqual(len(files), 2)
        for f in files:
            for photo in block(f)["photos"]:
                self.assertTrue((self.root / photo).read_bytes().startswith(b"\x89PNG"))

    def test_aucune_donnee_reelle_ni_marque(self):
        banned = re.compile(r"Tournai|Hoka|Adidas|Nike|Petzl|Leki|\b(?:TSS|CTL|ATL|TSB)\b|\"lat\"|\"lon\"")
        for path in self.root.rglob("*.md"):
            self.assertIsNone(banned.search(path.read_text(encoding="utf-8")), str(path))

    def test_refuse_decraser_un_dossier_etranger(self):
        with tempfile.TemporaryDirectory() as other:
            (Path(other) / "perso.md").write_text("x", encoding="utf-8")
            with self.assertRaises(FileExistsError):
                V.build_demo(Path(other), with_samples=False, force=True)

    def test_deterministe(self):
        with tempfile.TemporaryDirectory() as tmp:
            other = V.build_demo(Path(tmp) / "ws2", with_samples=False)
            for rel in ("medical/2026-09-29_health.md", "activities/2026-09-27_trail.md", "planning/Runner_Profile.md"):
                self.assertEqual((self.root / rel).read_text(encoding="utf-8"), (other / rel).read_text(encoding="utf-8"))

    def test_variante_bloc_ecrit_par_plan_skeleton(self):
        """Épisode 15 : le squelette vient de la vraie commande ; le workspace par défaut n'en a pas."""
        self.assertFalse((self.root / "planning/Semaine_2026-10-05.md").exists())
        with tempfile.TemporaryDirectory() as tmp:
            root = V.build_demo(Path(tmp) / "ws-bloc", with_samples=False, bloc=True)
            weeks = sorted(root.glob("planning/Semaine_2026-1[0-2]-*.md"))
            self.assertEqual(len(weeks), 13)                        # 12 semaines du gabarit + la récupération post-course
            self.assertIn("Trail du Solstice", (root / "planning/active_objective.md").read_text(encoding="utf-8"))
            for path in weeks:
                errors, _warnings = C.validate(block(path))
                self.assertEqual(errors, [], f"{path.name} : {errors}")
            self.assertEqual(block(weeks[0])["phase"], "Base")

    def test_variante_suite(self):
        """Épisodes 16-17 : bloc planifié jusqu'à la course, variante d'affûtage hors index, décisions passées."""
        self.assertFalse((self.root / "planning/2026-08-20_decision_bilan-matinal.md").exists())
        with tempfile.TemporaryDirectory() as tmp:
            root = V.build_demo(Path(tmp) / "ws-suite", with_samples=False, suite=True)
            weeks = sorted(root.glob("planning/Semaine_2026-1[01]-*.md"))
            self.assertEqual(len(weeks), 7)
            decisions = [root / f"planning/{d[0]}_decision_bilan-matinal.md" for d in V.DECISION_HISTORY]
            for path in weeks + decisions:
                errors, _warnings = C.validate(block(path))
                self.assertEqual(errors, [], f"{path.name} : {errors}")
            race_week = block(root / "planning/Semaine_2026-11-16.md")["sessions"]
            self.assertEqual(race_week[-1]["date"], V.RACE_DATE.isoformat())
            variant = json.loads((root / "planning/variante_affutage-court.json").read_text(encoding="utf-8"))
            self.assertEqual([w["week_start"] for w in variant["weeks"]], ["2026-11-09"])

    def test_variante_docs(self):
        """Captures de la documentation : ultra de 110 km, tours variables, matériel à contrôler ; défaut inchangé."""
        self.assertIn("alerte 100 h", (self.root / "planning/Runner_Profile.md").read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as tmp:
            root = V.build_demo(Path(tmp) / "ws-docs", with_samples=False, docs=True)
            ultra = block(root / f"activities/{V.ULTRA_ACTIVITY_DATE}_trail.md")
            self.assertEqual(len(ultra["splits"]), 110)
            self.assertEqual(sum(r[2] for r in ultra["splits"]), 4300)
            laps = block(root / f"activities/{V.LAPS_ACTIVITY_DATE}_running.md")
            self.assertEqual(sum(r[1] for r in laps["splits"]), laps["distance_m"])
            for path in (root / f"activities/{V.ULTRA_ACTIVITY_DATE}_trail.md",
                         root / f"activities/{V.LAPS_ACTIVITY_DATE}_running.md"):
                errors, _warnings = C.validate(block(path))
                self.assertEqual(errors, [], f"{path.name} : {errors}")
            self.assertIn("alerte 55 h", (root / "planning/Runner_Profile.md").read_text(encoding="utf-8"))
            # Lendemain de l'ultra : repos imposé dans la frise des verdicts.
            self.assertEqual(block(root / "medical/2026-06-14_health.md")["verdict"], "red")
            # Deux fichiers hors contrat VOLONTAIRES (vue « Fichiers hors contrat ») : jamais au contrat.
            self.assertFalse(C.validate(block(root / "nutrition/2026-02-20_nutrition.md"))[0] == [])
            self.assertNotIn("```arc", (root / "rapports/2026-02-15_notes-reprise.md").read_text(encoding="utf-8"))
            # Le workspace par défaut (épisodes) n'a aucun de ces ajouts.
            self.assertFalse((self.root / "rapports/2026-02-15_notes-reprise.md").exists())
            self.assertNotEqual(block(self.root / "medical/2026-06-14_health.md").get("verdict"), "red")

    def test_variante_docs_tours_suivent_les_echantillons(self):
        """Les échantillons FIT de la séance à tours suivent ses étapes (sinon la GAP par tour serait plate)."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fit = root / "fit.json"
            fit.write_text(json.dumps({"records": [{"t_s": i, "altitude_m": 5.0, "hr_bpm": 150.0} for i in range(100)]}),
                           encoding="utf-8")
            V._laps_samples(fit, [("Seuil 1", 1000, 200, 165), ("Récupération", 200, 100, 148)])
            recs = json.loads(fit.read_text(encoding="utf-8"))["records"]
            self.assertEqual(len(recs), 300)
            self.assertAlmostEqual(recs[-1]["distance_m"], 1200, delta=0.5)
            self.assertGreater(recs[10]["speed_ms"], recs[250]["speed_ms"])

    def test_efforts_suivent_le_modele_cs(self):
        """Vitesse des efforts posés = CS(date) + D′/durée, tenue à 98-99 % ; plus rapide sur les efforts courts."""
        v = [V._cs_speed("2026-09-22", d) for d in (180, 600, 1200)]
        self.assertGreater(v[0], v[1])
        self.assertGreater(v[1], v[2])
        self.assertTrue(3.7 < v[2] < 4.0)


if __name__ == "__main__":
    unittest.main()
