"""Palier B — cohérence statique des prompts et de la configuration.

Aucun modèle, aucun réseau, quelques millisecondes. Ces contrôles attrapent la
classe de bug qui a produit `planning/Runner_Profile.md` : un chemin cité par
trois fichiers d'instructions et qui n'existe nulle part.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
AGENTS = REPO / "agents"
SKILLS = REPO / "skills"

# Préfixes de chemins qui désignent le MOTEUR : ils doivent exister dans le dépôt.
ENGINE_PREFIXES = ("agents/", "skills/", "config/", "scripts/", "templates/", "docs/")

# Préfixes qui désignent le WORKSPACE de l'athlète : créés à l'usage, jamais
# versionnés (cf. .gitignore).
WORKSPACE_PREFIXES = (
    "activities/", "medical/", "nutrition/", "planning/", "rapports/", "resources/", "logs/",
)

# Chemins cités qui ne sont ni l'un ni l'autre (exemples, dossiers générés par
# les IDE, chemins absolus d'illustration).
PATH_ALLOWLIST = {
    "config/workspace.user.toml",   # généré par install.sh, gitignoré
    "local/agents/",
    "local/skills/",
    ".arc/backfill.md",             # généré par scripts/arc_index.py backfill-plan, gitignoré
    ".arc/coach.db",                # généré par scripts/arc_index.py, gitignoré (skill coach-doctor)
}

# Un chemin entre backticks, assez spécifique pour éviter les faux positifs.
PATH_IN_BACKTICKS = re.compile(r"`([A-Za-z0-9_./-]+/[A-Za-z0-9_.*<>-]+)`")

FRONTMATTER = re.compile(r"\A---\n(.*?)\n---\n", re.DOTALL)


def read_frontmatter(path: Path) -> dict:
    match = FRONTMATTER.match(path.read_text(encoding="utf-8"))
    if not match:
        return {}
    fields = {}
    for line in match.group(1).splitlines():
        if ":" in line and not line.startswith(" "):
            key, _, value = line.partition(":")
            fields[key.strip()] = value.strip().strip('"').strip("'")
    return fields


def agent_files() -> list:
    return sorted(AGENTS.glob("*.md"))


def skill_files() -> list:
    return sorted(SKILLS.glob("*/SKILL.md"))


def prompt_files() -> list:
    return agent_files() + skill_files()


class TestAgentFrontmatter(unittest.TestCase):
    """Contrat de CONTRIBUTING.md:29 — obligatoire pour la découverte par Copilot."""

    def test_required_fields(self):
        for path in agent_files():
            with self.subTest(agent=path.name):
                fm = read_frontmatter(path)
                for key in ("name", "description", "mode"):
                    self.assertIn(key, fm, f"{path.name} : frontmatter sans « {key} »")
                self.assertEqual(fm["mode"], "subagent", f"{path.name} : mode inattendu")

    def test_name_matches_filename(self):
        for path in agent_files():
            with self.subTest(agent=path.name):
                self.assertEqual(
                    read_frontmatter(path).get("name"),
                    path.stem,
                    f"{path.name} : « name » doit valoir « {path.stem} »",
                )


class TestSkillFrontmatter(unittest.TestCase):
    def test_required_fields(self):
        for path in skill_files():
            with self.subTest(skill=path.parent.name):
                fm = read_frontmatter(path)
                self.assertIn("name", fm, f"{path} : frontmatter sans « name »")
                self.assertIn("description", fm, f"{path} : frontmatter sans « description »")

    def test_name_matches_directory(self):
        for path in skill_files():
            with self.subTest(skill=path.parent.name):
                self.assertEqual(read_frontmatter(path).get("name"), path.parent.name)

    def test_description_within_limit(self):
        """≤ 1024 caractères (CONTRIBUTING.md)."""
        for path in skill_files():
            with self.subTest(skill=path.parent.name):
                description = read_frontmatter(path).get("description", "")
                self.assertLessEqual(
                    len(description), 1024, f"{path} : description de {len(description)} caractères"
                )


class TestReferencedPaths(unittest.TestCase):
    """Tout chemin du moteur cité dans un prompt doit exister."""

    @staticmethod
    def _resolves(prompt: Path, ref: str) -> bool:
        # Un SKILL.md cite ses propres fichiers relativement à son dossier
        # (`scripts/analyze_gpx.py`), convention des skills.
        if prompt.name == "SKILL.md" and (prompt.parent / ref).exists():
            return True
        return (REPO / ref).exists()

    def test_engine_paths_resolve(self):
        missing = []
        for path in prompt_files():
            text = path.read_text(encoding="utf-8")
            for ref in sorted(set(PATH_IN_BACKTICKS.findall(text))):
                if ref in PATH_ALLOWLIST or not ref.startswith(ENGINE_PREFIXES):
                    continue
                if any(ch in ref for ch in "*<>"):
                    continue                     # motif, pas un chemin littéral
                if not self._resolves(path, ref):
                    missing.append(f"{path.relative_to(REPO)} → {ref}")
        self.assertFalse(missing, "chemins du moteur cités mais inexistants :\n  " + "\n  ".join(missing))

    def test_workspace_paths_use_known_folders(self):
        unknown = []
        for path in prompt_files():
            text = path.read_text(encoding="utf-8")
            for ref in sorted(set(PATH_IN_BACKTICKS.findall(text))):
                if ref in PATH_ALLOWLIST or ref.startswith(ENGINE_PREFIXES):
                    continue
                if ref.startswith(WORKSPACE_PREFIXES) or ref.startswith(("~", "/", "http")):
                    continue
                if path.name == "SKILL.md" and (path.parent / ref).exists():
                    continue                     # chemin relatif au skill
                unknown.append(f"{path.relative_to(REPO)} → {ref}")
        self.assertFalse(
            unknown,
            "chemins ne relevant ni du moteur ni des dossiers de travail connus :\n  "
            + "\n  ".join(unknown),
        )


class TestSkillReferences(unittest.TestCase):
    def test_skills_named_by_agents_exist(self):
        known = {p.parent.name for p in skill_files()}
        missing = []
        for path in agent_files():
            text = path.read_text(encoding="utf-8")
            for name in set(re.findall(r"`([a-z][a-z0-9-]+)`", text)):
                if name.endswith(("-analyzer", "-comparison", "-sync", "-scheduling",
                                  "-forecast", "-analysis", "-download", "-practices",
                                  "-efficiency", "-contract", "-backfill")) and name not in known:
                    missing.append(f"{path.name} → {name}")
        self.assertFalse(missing, "skills cités par un agent mais absents de skills/ :\n  " + "\n  ".join(missing))


class TestSurfaceParity(unittest.TestCase):
    """Chaque agent doit exister sur toutes les surfaces qu'on prétend supporter."""

    def test_every_agent_has_a_gemini_command(self):
        commands = {p.stem for p in (REPO / "config/gemini/commands").glob("*.toml")}
        missing = sorted({p.stem for p in agent_files()} - commands)
        self.assertFalse(missing, f"agents sans commande Gemini : {missing}")

    def test_every_agent_has_a_doc_page(self):
        pages = {p.stem for p in (REPO / "docs/agents").glob("*.md")}
        missing = sorted({p.stem for p in agent_files()} - pages)
        self.assertFalse(missing, f"agents sans page docs/agents/ : {missing}")

    def test_every_skill_has_a_doc_page(self):
        pages = {p.stem for p in (REPO / "docs/skills").glob("*.md")}
        missing = sorted({p.parent.name for p in skill_files()} - pages)
        self.assertFalse(missing, f"skills sans page docs/skills/ : {missing}")

    def test_doc_pages_are_in_the_nav(self):
        nav = (REPO / "mkdocs.yml").read_text(encoding="utf-8")
        missing = [
            f"docs/agents/{p.stem}.md" for p in agent_files()
            if f"agents/{p.stem}.md" not in nav
        ] + [
            f"docs/skills/{p.parent.name}.md" for p in skill_files()
            if f"skills/{p.parent.name}.md" not in nav
        ]
        self.assertFalse(missing, f"pages absentes de la navigation mkdocs.yml : {missing}")


class TestWorkspaceTemplates(unittest.TestCase):
    """Un fichier du workspace érigé en source de vérité doit avoir un modèle.

    Sinon l'agent lit un chemin que personne ne crée jamais — exactement le cas
    de `planning/Runner_Profile.md`.
    """

    REQUIRED = {
        "planning/Runner_Profile.md": "templates/Runner_Profile.template.md",
        "planning/active_objective.md": "templates/active_objective.template.md",
    }

    def test_referenced_workspace_files_have_templates(self):
        cited = set()
        for path in prompt_files():
            text = path.read_text(encoding="utf-8")
            for ref in PATH_IN_BACKTICKS.findall(text):
                if ref in self.REQUIRED:
                    cited.add(ref)
        missing = [
            f"{ref} (cité par un prompt) → modèle attendu : {self.REQUIRED[ref]}"
            for ref in sorted(cited)
            if not (REPO / self.REQUIRED[ref]).exists()
        ]
        self.assertFalse(missing, "fichiers de travail sans modèle :\n  " + "\n  ".join(missing))


class TestHeadlessSkill(unittest.TestCase):
    """Le skill de synchronisation tourne sous cron : il ne doit rien demander.

    Le contrôle de premier démarrage ajouté aux agents est exactement le genre de
    chose qui finirait sinon dans une notification push, sans personne pour y
    répondre.
    """

    SKILL = REPO / "skills/garmin-daily-sync/SKILL.md"

    def test_states_it_asks_nothing(self):
        self.assertIn("Ne JAMAIS poser de", self.SKILL.read_text(encoding="utf-8"))

    def test_opts_out_of_the_setup_check(self):
        text = self.SKILL.read_text(encoding="utf-8")
        self.assertIn(
            "coach-setup", text,
            "le skill headless doit dire explicitement qu'il ne propose pas /coach-setup",
        )
        self.assertIn("ne jamais le proposer", text.lower())
