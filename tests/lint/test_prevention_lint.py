"""Palier B — prévention ciblée (#192) : câblage des prompts (portes `[agents].enabled`, avertissement
« pas un avis médical », jamais d'assouplissement d'une décision `medical` ni d'un drapeau de risque de
blessure, aucune poussée automatique), documentation, et aucun mot de diagnostic dans les textes que le
module et la documentation mettent dans la bouche de l'agent.

Lecture statique, aucun réseau."""

from __future__ import annotations

import json
import re
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO / "scripts"))
import arc_prevention as PV  # noqa: E402
import arc_strength as SG  # noqa: E402


def read(rel: str) -> str:
    return (REPO / rel).read_text(encoding="utf-8")


COACH = read("agents/coach.md")
MEDICAL = read("agents/medical.md")
STRENGTH_DOC = read("docs/strength.md")


def section(text: str, start: str, end: str) -> str:
    i = text.index(start)
    return text[i:text.index(end, i)]


COACH_PARA = section(COACH, "**Targeted prevention from declared pain (#192):**", "\n")
MEDICAL_SEC = section(MEDICAL, "### TARGETED PREVENTION FROM DECLARED PAIN (#192", "### CYCLE CONTEXT")
DOC_SEC = section(STRENGTH_DOC, "## Prévention ciblée", "## Sources")
# Liste partagée avec le palier D (sorties du module) : une seule source, `arc_prevention`.
DIAGNOSIS = PV.DIAGNOSIS_TERMS
CARE_FR = PV.CARE_TERMS
CARE_EN = re.compile(r"\b(?<!never a )(?<!not a )(?<!no )treatment|\btreat(s|ing)?\b|\bheal(s|ed|ing)?\b|\bcure[sd]?\b|"
                     r"\btherap(y|ies|eutic)\b|\brehab", re.IGNORECASE)
LOG_PARA = section(read("skills/log/SKILL.md"), "**Prévention ciblée (#192) :**", "\n4. ")
TELEGRAM_PARA = section(read("docs/telegram.md"), "Une douleur légère saisie ici", "\n\n")
AGENTS_LINES = "\n".join(line for line in read("AGENTS.md").splitlines() if "#192" in line)
DOCS_AGENT_LINES = "\n".join(line for f in ("docs/agents/coach.md", "docs/agents/medical.md")
                              for line in read(f).splitlines() if "#192" in line)


class TestCoachPrompt(unittest.TestCase):
    def test_command_and_zone_only_wording(self):
        self.assertIn("arc_index.py prevention", COACH_PARA)
        self.assertIn("never a diagnosis", COACH_PARA)
        self.assertIn("approximations du projet", COACH_PARA)

    def test_medical_gating_both_ways(self):
        self.assertIn("If `medical` is in `[agents].enabled`, IT owns the decision", COACH_PARA)
        self.assertIn("never relax it", COACH_PARA)
        self.assertIn("If `medical` is absent", COACH_PARA)

    def test_disclaimer_is_mandatory_without_medical(self):
        self.assertIn("ALWAYS say « ce n'est pas un avis médical »", COACH_PARA)
        self.assertIn("Ce n'est pas un avis médical", PV.DISCLAIMER_COACH)

    def test_no_exercise_when_consult_and_never_overrides_flags(self):
        self.assertIn("no exercise at all and recommend a healthcare professional", COACH_PARA)
        self.assertIn("whatever the athlete asks for", COACH_PARA)
        self.assertIn("Never override an injury-risk flag or a medical decision", COACH_PARA)

    def test_proposal_only_never_automatic_and_push_rule_kept(self):
        self.assertIn("PROPOSE the gentle `routine` at the next interaction", COACH_PARA)
        self.assertIn("never push it automatically", COACH_PARA)
        self.assertIn("explicit-yes, never-headless", COACH_PARA)

    def test_first_light_declaration_is_observed_and_known_needs_the_athlete(self):
        self.assertIn('`status: "observe"`', COACH_PARA)
        self.assertIn("no exercise yet", COACH_PARA)
        self.assertIn("new? sharp or sudden? swollen?", COACH_PARA)
        self.assertIn("only if the athlete explicitly says it is a known, non-acute, stable discomfort", COACH_PARA)
        self.assertIn("`--known <zone>`", COACH_PARA)
        self.assertIn("never on your own inference, never in headless mode", COACH_PARA)
        self.assertIn("delegate to it before proposing anything", COACH_PARA)

    def test_unknown_zone_or_equipment_means_asking(self):
        self.assertIn("unknown equipment → ask", COACH_PARA)
        self.assertIn("an unrecognised zone → ask, never improvise", COACH_PARA)

    def test_existing_strength_rules_not_weakened(self):
        self.assertIn("pain or a medical protocol → defer to `medical` when enabled", COACH)
        self.assertIn('explicit "yes" in the conversation, never headless', COACH)


class TestMedicalPrompt(unittest.TestCase):
    def test_medical_owns_the_decision(self):
        self.assertIn("YOU own the decision", MEDICAL_SEC)
        self.assertIn("the Coach relays it and never softens it", MEDICAL_SEC)
        self.assertIn("arc_index.py prevention", MEDICAL_SEC)

    def test_rules_match_the_script(self):
        th = PV.load_prevention()["thresholds"]
        self.assertIn(f"> {th['gentle_max_score']}/10", MEDICAL_SEC)
        self.assertIn(f"more than {th['persistence_days']} days", MEDICAL_SEC)
        self.assertIn("pain_consult_threshold", MEDICAL_SEC)
        self.assertIn("`consult: true` or `level: \"high\"`", MEDICAL_SEC)

    def test_observe_status_and_red_flags_kept(self):
        self.assertIn("`observe`", MEDICAL_SEC)
        self.assertIn("only when the athlete explicitly confirms", MEDICAL_SEC)
        self.assertIn("never assumed low", MEDICAL_SEC)
        self.assertIn("A zone back at 0/10 stays `consult`", MEDICAL_SEC)
        self.assertNotIn("no loading exercise", MEDICAL_SEC)       # aigu = AUCUN exercice, comme le script

    def test_zones_only_and_no_automatic_push(self):
        self.assertIn("Name zones only", MEDICAL_SEC)
        self.assertIn("never a pathology", MEDICAL_SEC)
        self.assertIn("Never push anything automatically", MEDICAL_SEC)
        self.assertIn("approximation du projet", MEDICAL_SEC)


class TestDocs(unittest.TestCase):
    def test_strength_page_has_the_section_and_its_rules(self):
        for needle in ("arc_index.py prevention", "decision_owner", "ce n'est pas un avis médical", "approximations du projet",
                       "jamais une pathologie", "[injury_risk].pain_consult_threshold", "7 jours", "3/10",
                       "jamais en mode headless", "Drapeau de risque de blessure"):
            self.assertIn(needle, DOC_SEC, needle)

    def test_every_zone_is_documented(self):
        for z in PV.load_prevention()["zones"]:
            self.assertIn(z["label"].split(" (")[0].lower(), DOC_SEC.lower(), z["id"])

    def test_documentation_wiring(self):
        self.assertIn("arc_index.py prevention", read("AGENTS.md"))
        self.assertIn("arc_prevention.py", read("AGENTS.md"))
        self.assertIn("prévention ciblée", read("README.md"))
        self.assertIn("strength.md#prevention-ciblee", read("docs/agents/coach.md"))
        self.assertIn("strength.md#prevention-ciblee", read("docs/agents/medical.md"))
        self.assertIn("arc_index.py prevention", read("skills/log/SKILL.md"))
        self.assertIn("jamais automatiquement", read("skills/log/SKILL.md"))
        self.assertIn("strength.md#prevention-ciblee", read("docs/telegram.md"))

    def test_agents_table_mentions_the_medical_decision(self):
        agents = read("AGENTS.md")
        self.assertIn("`medical` décide s'il est activé", agents)
        self.assertIn("ce n'est pas un avis médical", agents)

    def test_docs_and_script_texts_name_no_diagnosis(self):
        french = (("docs/strength.md section", DOC_SEC), ("skills/log", LOG_PARA), ("docs/telegram", TELEGRAM_PARA),
                  ("AGENTS.md #192", AGENTS_LINES), ("docs/agents #192", DOCS_AGENT_LINES))
        english = (("coach", COACH_PARA), ("medical", MEDICAL_SEC))
        for name, text in french + english:
            self.assertTrue(text.strip(), name)
            # « pathologie » est permis dans « jamais une pathologie » ; les noms précis ne le sont jamais.
            m = DIAGNOSIS.search(text)
            self.assertIsNone(m, f"{name} : {m and m.group(0)}")
        for name, text in french:
            m = CARE_FR.search(text)
            self.assertIsNone(m, f"{name} : {m and m.group(0)}")
        for name, text in english:
            m = CARE_EN.search(text)
            self.assertIsNone(m, f"{name} : {m and m.group(0)}")

    def test_the_lint_patterns_bite(self):
        for word in ("tendinite", "fasciite", "périostite", "syndrome", "entorse", "déchirure", "fracture", "bursite",
                     "rupture"):
            self.assertIsNotNone(DIAGNOSIS.search(word), word)
        for word in ("treatment for it", "to treat", "will heal", "a cure", "physical therapy", "rehab"):
            self.assertIsNotNone(CARE_EN.search(word), word)
        for ok in ("never a treatment", "never a diagnosis", "physiotherapist"):
            self.assertIsNone(CARE_EN.search(ok), ok)

    def test_docs_describe_the_observe_status(self):
        for needle in ("`observe`", "aucun exercice", "--known", "nouveau ?", "gonflement ?",
                       "jamais supposé bas", "consulter reste alors affichée"):
            self.assertIn(needle, DOC_SEC, needle)


class TestData(unittest.TestCase):
    def test_data_ships_with_the_engine(self):
        self.assertTrue((REPO / "config/strength/prevention.json").is_file())

    def test_only_library_exercises_are_referenced(self):
        exercises, _ = SG.load_library()
        doc = PV.load_prevention()
        for z in doc["zones"]:
            for b in z["exercises"]:
                self.assertIn(b["exercise"], exercises, z["id"])
        self.assertEqual(json.loads(read("config/strength/prevention.json"))["status"], "approximation_projet")

    def test_no_garmin_keys_in_prevention_data(self):
        # Les clés Garmin vivent UNIQUEMENT dans la bibliothèque vérifiée (`GARMIN_VERIFIED`) : jamais dupliquées ici.
        self.assertNotIn("garmin", read("config/strength/prevention.json").lower())

    def test_cli_is_documented_in_arc_index_usage(self):
        self.assertIn("arc_index.py prevention", read("scripts/arc_index.py"))


class TestEvalCases(unittest.TestCase):
    def test_both_cases_exist_with_relative_fixtures(self):
        for case, fixture in (("prevention-mollet-stable-routine", "prevention-mollet-stable"),
                              ("prevention-genou-consult-no-exercise", "prevention-genou-consult"),
                              ("prevention-premiere-declaration-observe", "prevention-premiere-observe")):
            text = read(f"tests/evals/cases/{case}.toml")
            self.assertIn(f'fixture = "{fixture}"', text)
            self.assertTrue((REPO / "tests/evals/fixtures" / fixture / "medical").is_dir())
            for f in (REPO / "tests/evals/fixtures" / fixture / "medical").glob("*_health.md"):
                self.assertRegex(f.name, r"^\d+d_health\.md$")           # dates relatives, jamais codées en dur
                self.assertIn("{{DATE}}", f.read_text(encoding="utf-8"))

    def test_the_stable_case_has_no_medical_agent(self):
        self.assertIn('enabled = ["coach", "nutritionist"]', read("tests/evals/cases/prevention-mollet-stable-routine.toml"))
        self.assertIn('enabled = ["coach", "nutritionist"]',
                      read("tests/evals/cases/prevention-premiere-declaration-observe.toml"))


if __name__ == "__main__":
    unittest.main()
