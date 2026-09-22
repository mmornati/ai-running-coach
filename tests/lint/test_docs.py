"""Palier B — intégrité de la documentation, sans installer mkdocs.

`mkdocs build --strict` échoue sur un lien mort, mais il tourne uniquement en CI.
Ces contrôles attrapent la même chose en quelques millisecondes, partout.
"""

from __future__ import annotations

import re
import subprocess
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
DOCS = REPO / "docs"

MARKDOWN_LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
NAV_ENTRY = re.compile(r"^\s+-\s+[^:]+:\s*([A-Za-z0-9_./-]+\.md)\s*$", re.MULTILINE)


def doc_files() -> list:
    return sorted(DOCS.rglob("*.md"))


class TestInternalLinks(unittest.TestCase):
    def test_relative_links_resolve(self):
        broken = []
        for path in doc_files():
            for target in MARKDOWN_LINK.findall(path.read_text(encoding="utf-8")):
                if target.startswith(("http://", "https://", "mailto:", "#")):
                    continue
                file_part = target.split("#", 1)[0]
                if not file_part:
                    continue                       # ancre dans la même page
                if not (path.parent / file_part).resolve().exists():
                    broken.append(f"{path.relative_to(REPO)} → {target}")
        self.assertFalse(broken, "liens internes morts :\n  " + "\n  ".join(broken))

    def test_anchors_point_at_real_headings(self):
        broken = []
        for path in doc_files():
            for target in MARKDOWN_LINK.findall(path.read_text(encoding="utf-8")):
                if target.startswith(("http://", "https://", "mailto:")) or "#" not in target:
                    continue
                file_part, _, anchor = target.partition("#")
                page = (path.parent / file_part).resolve() if file_part else path
                if not page.exists():
                    continue                       # déjà signalé par le test précédent
                slugs = {
                    _slugify(line.lstrip("#").strip())
                    for line in page.read_text(encoding="utf-8").splitlines()
                    if line.startswith("#")
                }
                if anchor not in slugs:
                    broken.append(f"{path.relative_to(REPO)} → {target}")
        self.assertFalse(broken, "ancres inexistantes :\n  " + "\n  ".join(broken))


def _slugify(heading: str) -> str:
    """Approche la génération d'ancre de mkdocs (Python-Markdown `toc`)."""
    import unicodedata

    text = unicodedata.normalize("NFKD", heading)
    text = "".join(c for c in text if not unicodedata.combining(c)).lower()
    text = re.sub(r"[^\w\s-]", "", text)
    return re.sub(r"[\s_]+", "-", text).strip("-")


class TestNav(unittest.TestCase):
    def test_every_nav_entry_exists(self):
        nav = (REPO / "mkdocs.yml").read_text(encoding="utf-8")
        nav = nav.split("nav:", 1)[1]
        missing = [entry for entry in NAV_ENTRY.findall(nav) if not (DOCS / entry).is_file()]
        self.assertFalse(missing, f"entrées de navigation sans fichier : {missing}")

    def test_every_page_is_reachable(self):
        nav = (REPO / "mkdocs.yml").read_text(encoding="utf-8").split("nav:", 1)[1]
        listed = set(NAV_ENTRY.findall(nav))
        orphans = sorted(
            str(p.relative_to(DOCS)) for p in doc_files()
            if str(p.relative_to(DOCS)) not in listed
        )
        self.assertFalse(orphans, f"pages absentes de la navigation : {orphans}")


class TestFixturesAreTracked(unittest.TestCase):
    """Les fixtures des évals doivent être dans le dépôt.

    `.gitignore` excluait `activities/`, `planning/`… sans ancre, donc aussi
    `tests/evals/fixtures/*/activities/`. Les fixtures disparaissaient en
    silence : le palier C n'aurait rien eu à lire en CI.
    """

    FIXTURES = REPO / "tests/evals/fixtures"

    def test_no_fixture_file_is_gitignored(self):
        files = [p for p in self.FIXTURES.rglob("*") if p.is_file()]
        self.assertTrue(files, "aucune fixture trouvée")
        proc = subprocess.run(
            ["git", "check-ignore", "--stdin"],
            input="\n".join(str(p.relative_to(REPO)) for p in files),
            capture_output=True, text=True, cwd=str(REPO),
        )
        ignored = [line for line in proc.stdout.splitlines() if line.strip()]
        self.assertFalse(ignored, "fixtures exclues par .gitignore :\n  " + "\n  ".join(ignored))

    def test_work_directory_patterns_are_anchored(self):
        """Un motif non ancré s'applique à toute profondeur — jamais ce qu'on veut ici."""
        unanchored = []
        for line in (REPO / ".gitignore").read_text(encoding="utf-8").splitlines():
            entry = line.strip()
            if entry.rstrip("/") in ("activities", "medical", "nutrition", "planning",
                                     "rapports", "resources") and not entry.startswith("/"):
                unanchored.append(entry)
        self.assertFalse(
            unanchored,
            f"motifs de dossiers de travail non ancrés (ajoutez « / ») : {unanchored}",
        )
