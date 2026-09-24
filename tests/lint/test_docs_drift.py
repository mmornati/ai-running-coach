"""Palier B — Vérifier que docs et skills/agents ne dérivent pas.

Teste:
- Le nombre de skills/agents cités dans README et docs/skills.md correspond à la réalité
- Chaque skill et agent du répertoire est bien listé dans la documentation
- Aucune affirmation inexacte sur les backends (ex. « Garmin seulement »)
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
AGENTS = REPO / "agents"
SKILLS = REPO / "skills"
README = REPO / "README.md"
DOCS_SKILLS = REPO / "docs" / "skills.md"


def count_agents() -> int:
    """Compte les fichiers agents/*.md."""
    return len(list(AGENTS.glob("*.md")))


def count_skills() -> int:
    """Compte les dossiers skills/*/SKILL.md."""
    return len(list(SKILLS.glob("*/SKILL.md")))


def get_skill_names() -> set[str]:
    """Extrait les noms des dossiers skills/."""
    return {p.parent.name for p in SKILLS.glob("*/SKILL.md")}


def get_agent_names() -> set[str]:
    """Extrait les noms des agents (fichiers agents/*.md sans .md)."""
    return {p.stem for p in AGENTS.glob("*.md")}


class TestSkillAgentCounts(unittest.TestCase):
    """Vérifie que les counts en doc correspondent à la réalité."""

    def test_readme_skill_count(self):
        """README.md doit mentionner le bon nombre de skills."""
        readme_text = README.read_text(encoding="utf-8")
        actual_count = count_skills()

        # Cherche les nombres près de "skills" (cas-insensible)
        matches = re.findall(r"(\d+)\s+skills?", readme_text, re.IGNORECASE)
        self.assertTrue(
            matches,
            f"README.md ne mentionne aucun nombre de skills (attendu: {actual_count})"
        )

        for match in matches:
            count = int(match)
            self.assertEqual(
                count, actual_count,
                f"README.md mentionne {count} skills, trouvé {actual_count} dans skills/"
            )

    def test_readme_agent_count(self):
        """README.md doit mentionner le bon nombre d'agents."""
        readme_text = README.read_text(encoding="utf-8")
        actual_count = count_agents()

        # Cherche "4 agents" ou similaire
        matches = re.findall(r"(\d+)\s+agents?", readme_text, re.IGNORECASE)
        self.assertTrue(
            matches,
            f"README.md ne mentionne aucun nombre d'agents (attendu: {actual_count})"
        )

        for match in matches:
            count = int(match)
            self.assertEqual(
                count, actual_count,
                f"README.md mentionne {count} agents, trouvé {actual_count} dans agents/"
            )

    def test_docs_skills_count(self):
        """docs/skills.md doit mentionner le bon nombre de skills."""
        docs_text = DOCS_SKILLS.read_text(encoding="utf-8")
        actual_count = count_skills()

        # Cherche "N skills" dans le texte
        matches = re.findall(r"(\d+)\s+skills?", docs_text, re.IGNORECASE)
        self.assertTrue(
            matches,
            f"docs/skills.md ne mentionne aucun nombre de skills (attendu: {actual_count})"
        )

        for match in matches:
            count = int(match)
            self.assertEqual(
                count, actual_count,
                f"docs/skills.md mentionne {count} skills, trouvé {actual_count} dans skills/"
            )


class TestSkillDocumentation(unittest.TestCase):
    """Vérifie que chaque skill est bien documenté."""

    def test_all_skills_listed_in_docs(self):
        """Tous les skills doivent être listés dans docs/skills.md."""
        docs_text = DOCS_SKILLS.read_text(encoding="utf-8")
        actual_skills = get_skill_names()

        # Cherche les noms de skills en liens: `skills/nomskill.md`
        # ou en texte direct
        listed_in_overview = set()

        # Pattern: <a href="skills/xxx.md"> ou skills/xxx.md mentionné
        pattern = r'skills/([a-z0-9-]+)\.md'
        for match in re.finditer(pattern, docs_text):
            listed_in_overview.add(match.group(1))

        missing = actual_skills - listed_in_overview
        self.assertFalse(
            missing,
            f"Skills dans skills/ mais pas documentés dans docs/skills.md: {missing}"
        )


class TestAgentDocumentation(unittest.TestCase):
    """Vérifie que chaque agent est bien documenté."""

    def test_all_agents_exist(self):
        """Les agents doivent avoir leurs fichiers."""
        actual_agents = get_agent_names()
        expected = {"coach", "course-strategist", "medical", "nutritionist"}
        self.assertEqual(
            actual_agents, expected,
            f"Agents trouvés: {actual_agents}, attendus: {expected}"
        )


class TestIntervalsIcuDocumentation(unittest.TestCase):
    """Vérifie que la documentation sur Intervals.icu est correcte."""

    def test_no_garmin_only_claims_without_context(self):
        """
        README.md ne doit pas dire « Garmin seulement » sans clarifier
        que Intervals.icu est secondaire et optionnel.
        """
        readme_text = README.read_text(encoding="utf-8")

        # Si on trouve "Garmin seulement" ou "Garmin uniquement",
        # il doit y avoir du contexte mentionnant Intervals.icu ou "secondaire"
        garmin_only = re.search(
            r"(Garmin\s+(?:seulement|uniquement)|ne\s+supporte\s+que\s+Garmin)",
            readme_text,
            re.IGNORECASE
        )

        if garmin_only:
            # Cherche du contexte clarificateur à proximité (±500 caractères)
            start = max(0, garmin_only.start() - 500)
            end = min(len(readme_text), garmin_only.end() + 500)
            context = readme_text[start:end]

            has_clarification = any(phrase in context.lower() for phrase in [
                "secondaire", "optionnel", "intervals.icu", "explicit"
            ])

            self.assertTrue(
                has_clarification,
                f"Affirmation « {garmin_only.group()} » détectée sans clarification "
                "sur le caractère optionnel d'Intervals.icu"
            )

    def test_skill_for_intervals_icu_exists(self):
        """Le skill intervals-icu-best-practices doit exister."""
        intervals_skill = SKILLS / "intervals-icu-best-practices" / "SKILL.md"
        self.assertTrue(
            intervals_skill.exists(),
            f"Skill Intervals.icu absent: {intervals_skill}"
        )


if __name__ == "__main__":
    unittest.main()
