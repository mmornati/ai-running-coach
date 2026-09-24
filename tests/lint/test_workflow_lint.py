"""Palier B — hygiène des workflows GitHub Actions (#29).

Aucun parseur YAML tiers (le projet reste stdlib-only) : ces contrôles sont
volontairement des motifs textuels conservateurs, dans le même esprit que
`test_docker.py`. Le but n'est pas de comprendre tout GitHub Actions, mais de
verrouiller la classe de bug connue sous le nom de « pwn request » : un
`pull_request_target` (ou un `pull_request` mal gardé) qui expose des secrets
à du code de fork, ou un commentaire de PR qui interpole une chaîne contrôlée
par l'auteur de la PR (titre, corps…) dans un `run:` shell.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
WORKFLOWS_DIR = REPO / ".github" / "workflows"
WORKFLOW_FILES = sorted(WORKFLOWS_DIR.glob("*.yml"))

EVALS_YML = WORKFLOWS_DIR / "evals.yml"

# Champs d'événement GitHub dont le contenu est écrit par l'auteur de la PR/issue
# (donc non fiable) : jamais à interpoler tel quel dans un `run:` shell — la
# bonne pratique est de le faire transiter par une variable d'environnement ou
# un fichier, jamais par `${{ ... }}` au milieu d'une commande.
_UNTRUSTED_EVENT_TEXT = re.compile(
    r"\$\{\{\s*github\.event\.(pull_request|issue|comment|review)\."
    r"(title|body|head\.(ref|label))"
)

_RUN_LINE_RE = re.compile(r"^(?P<indent>[ \t]*)run:[ \t]*(?P<style>\|[+-]?|>[+-]?)?[ \t]*(?P<inline>.*)$")


def _strip_comments(text: str) -> str:
    """Retire les commentaires YAML (`# …` en fin de ligne) avant une recherche
    textuelle sur les clés réelles — un commentaire qui *mentionne* `pull-requests:
    write` (documentation d'une garde, comme dans evals.yml) ne doit pas compter
    comme la déclaration elle-même. Naïf (ignore les `#` à l'intérieur d'une
    chaîne), mais suffisant : aucune valeur YAML de ce dépôt ne contient `#`."""
    return "\n".join(re.split(r"(?<!\S)#", line, maxsplit=1)[0] for line in text.splitlines())


def _extract_run_blocks(text: str) -> list:
    """Rend le texte de chaque étape `run:` (bloc `|`/`>` ou une ligne simple).

    Suffisant pour nos deux workflows actuels : suit l'indentation pour
    délimiter un bloc scalaire, sans prétendre à un parseur YAML complet.
    """
    lines = text.splitlines()
    blocks, i, n = [], 0, len(lines)
    while i < n:
        match = _RUN_LINE_RE.match(lines[i])
        if not match:
            i += 1
            continue
        indent, style, inline = match.group("indent"), match.group("style"), match.group("inline")
        if not style:
            blocks.append(inline)
            i += 1
            continue
        base_indent = len(indent)
        block_lines = []
        i += 1
        while i < n:
            line = lines[i]
            if line.strip() == "":
                block_lines.append(line)
                i += 1
                continue
            current_indent = len(line) - len(line.lstrip(" \t"))
            if current_indent <= base_indent:
                break
            block_lines.append(line)
            i += 1
        blocks.append("\n".join(block_lines))
    return blocks


class TestNoPwnRequestPattern(unittest.TestCase):
    """La classe de bug « pwn request » : `pull_request_target` + secrets + code de PR."""

    def test_no_workflow_uses_pull_request_target(self):
        """Motif de la clé elle-même (`pull_request_target:`), pas une mention en
        commentaire expliquant pourquoi on ne l'utilise pas (voir l'en-tête d'evals.yml)."""
        for path in WORKFLOW_FILES:
            with self.subTest(workflow=path.name):
                text = _strip_comments(path.read_text(encoding="utf-8"))
                self.assertNotRegex(
                    text, r"(?m)^\s*pull_request_target\s*:",
                    f"{path.name} : `pull_request_target` expose les secrets à du code de PR non fiable "
                    "(voir la section Sécurité de la PR #29) — utiliser `pull_request` (pas de secrets pour "
                    "les forks) avec une garde same-repo, ou un job `workflow_run` séparé.",
                )

    def test_no_run_block_interpolates_untrusted_pr_text(self):
        for path in WORKFLOW_FILES:
            text = path.read_text(encoding="utf-8")
            for block in _extract_run_blocks(text):
                with self.subTest(workflow=path.name, block=block[:60]):
                    self.assertNotRegex(
                        block, _UNTRUSTED_EVENT_TEXT,
                        f"{path.name} : un `run:` interpole du texte contrôlé par l'auteur de la PR/issue "
                        "(titre, corps…) — faire transiter cette valeur par `env:` ou un fichier, jamais "
                        "directement dans la commande shell.",
                    )


class TestPermissionsAreExplicit(unittest.TestCase):
    """Un jeton par défaut (souvent `contents: write` selon les réglages du dépôt) ne doit
    jamais être hérité sans y penser — chaque workflow déclare ce dont il a besoin."""

    def test_every_workflow_declares_permissions(self):
        for path in WORKFLOW_FILES:
            with self.subTest(workflow=path.name):
                text = _strip_comments(path.read_text(encoding="utf-8"))
                has_top_level = re.search(r"^permissions:", text, re.MULTILINE) is not None
                # Ou bien chaque job déclare les siennes (au moins un `permissions:` indenté sous `jobs:`).
                has_per_job = len(re.findall(r"^  [A-Za-z0-9_-]+:\n(?:.*\n)*?    permissions:", text, re.MULTILINE)) > 0
                self.assertTrue(
                    has_top_level or has_per_job,
                    f"{path.name} : aucune section `permissions:` — le jeton par défaut du dépôt s'applique "
                    "silencieusement, ce qui est trop large pour un job qui n'a besoin que de lire le dépôt.",
                )

    def test_no_workflow_grants_write_all(self):
        for path in WORKFLOW_FILES:
            with self.subTest(workflow=path.name):
                text = _strip_comments(path.read_text(encoding="utf-8"))
                self.assertNotRegex(text, r"permissions:\s*write-all")


class TestEvalsWorkflowLabelGuard(unittest.TestCase):
    """`evals.yml` (#29) : le déclenchement sur étiquette de PR doit être une exception
    explicite, jamais un `pull_request` générique qui tournerait sur n'importe quelle PR."""

    def setUp(self):
        self.text = _strip_comments(EVALS_YML.read_text(encoding="utf-8"))

    def test_pull_request_trigger_is_scoped_to_labeled(self):
        """`synchronize` sur une PR déjà étiquetée redéclencherait les évals à chaque
        push — coûteux et sans plafond. Seul l'événement `labeled` doit lancer le job ;
        un mainteneur qui veut relancer retire puis remet l'étiquette."""
        match = re.search(r"pull_request:\s*\n((?:[ \t]+.*\n)*)", self.text)
        self.assertIsNotNone(match, "evals.yml : aucun déclencheur `pull_request` — voir la section Sécurité de la PR")
        block = match.group(1)
        types_match = re.search(r"types:\s*\[([^\]]*)\]", block)
        self.assertIsNotNone(types_match, "evals.yml : `pull_request` sans `types:` explicite")
        types = [t.strip() for t in types_match.group(1).split(",")]
        self.assertEqual(types, ["labeled"], f"evals.yml : types attendus ['labeled'], trouvé {types}")

    def test_label_name_is_checked(self):
        self.assertIn("run-evals", self.text)
        self.assertRegex(self.text, r"contains\([^)]*labels[^)]*,\s*'run-evals'\)")

    def test_same_repo_guard_present(self):
        """Sans cette garde, une PR de fork qui reçoit l'étiquette (si un mainteneur
        se trompe) tournerait quand même — sans secrets utiles, mais en gaspillant
        des minutes CI. Documentée dans la section Sécurité de la PR #29."""
        self.assertIn("head.repo.full_name == github.repository", self.text)

    def test_comment_permission_is_isolated_from_the_eval_job(self):
        """Le job qui exécute les prompts (code du dépôt + outils MCP factices) ne
        doit pas porter `pull-requests: write` — seul le job qui poste le commentaire,
        et qui ne fait qu'écrire un fichier déjà produit, en a besoin (moindre
        privilège par job, cf. section Sécurité de la PR #29)."""
        jobs_text = _strip_comments(self.text).split("jobs:", 1)[1]
        job_blocks = re.split(r"^  (?=[A-Za-z0-9_-]+:)", jobs_text, flags=re.MULTILINE)
        writers = [b for b in job_blocks if re.search(r"pull-requests:\s*write", b)]
        self.assertTrue(writers, "evals.yml : aucun job avec `pull-requests: write` — le commentaire de PR ne peut pas être posté")
        for block in writers:
            self.assertNotIn(
                "ANTHROPIC_API_KEY", block,
                "evals.yml : le job qui peut écrire sur la PR ne doit pas aussi être celui qui exécute "
                "les prompts (secret modèle) — cela recrée la surface qu'on isole.",
            )


if __name__ == "__main__":
    unittest.main()
