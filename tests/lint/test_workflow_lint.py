"""Palier B — hygiène des workflows GitHub Actions (#29, durci en revue PR #74).

Aucun parseur YAML tiers (le projet reste stdlib-only) : ces contrôles sont
volontairement des motifs textuels conservateurs, dans le même esprit que
`test_docker.py`. Le but n'est pas de comprendre tout GitHub Actions, mais de
verrouiller la classe de bug connue sous le nom de « pwn request » : un
`pull_request_target` (ou un `pull_request` mal gardé) qui expose des secrets
à du code de fork, ou un commentaire de PR qui interpole une chaîne contrôlée
par l'auteur de la PR (titre, corps, nom de branche, message de commit…) dans
un `run:` shell ou un `script:` de `github-script` (les deux sont interpolés
par Actions AVANT exécution — un `script:` n'est pas plus sûr qu'un `run:`).
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
WORKFLOWS_DIR = REPO / ".github" / "workflows"
WORKFLOW_FILES = sorted(WORKFLOWS_DIR.glob("*.yml"))

EVALS_YML = WORKFLOWS_DIR / "evals.yml"

# Champs d'événement GitHub dont le contenu est écrit par l'auteur de la PR/issue/push
# (donc non fiable), plus `inputs.*` (jamais interpolé directement non plus : même une
# entrée `workflow_dispatch` tapée par un mainteneur peut casser un guillemet de shell) —
# à faire transiter par `env:` puis `$VAR`, jamais par `${{ ... }}` au milieu d'une
# commande ou d'un script (revue PR #74, point 4 : l'ancien motif ne couvrait que
# `pull_request`/`issue`/`comment`/`review`.title|body et ratait `head_ref`, les noms
# d'étiquette, les messages de commit, et les `inputs.*`).
_UNTRUSTED_INTERPOLATION = re.compile(
    r"\$\{\{\s*"
    r"(github\.head_ref"
    r"|github\.event\.[a-zA-Z_][a-zA-Z0-9_.]*\.(title|body|message|ref|label|name)"
    r"|inputs\.[a-zA-Z0-9_-]+"
    r")"
)


def _strip_comments(text: str) -> str:
    """Retire les commentaires YAML (`# …` en fin de ligne) avant une recherche
    textuelle sur les clés réelles — un commentaire qui *mentionne* `pull-requests:
    write` (documentation d'une garde, comme dans evals.yml) ne doit pas compter
    comme la déclaration elle-même. Naïf (ignore les `#` à l'intérieur d'une
    chaîne), mais suffisant : aucune valeur YAML de ce dépôt ne contient `#`."""
    return "\n".join(re.split(r"(?<!\S)#", line, maxsplit=1)[0] for line in text.splitlines())


def _extract_scalar_blocks(text: str, key: str) -> list:
    """Rend le texte de chaque valeur de la clé scalaire `key:` (bloc `|`/`>` ou
    valeur en ligne) — utilisé pour `run:`, `script:` (github-script) et `if:`.

    Suffisant pour les workflows de ce dépôt : suit l'indentation pour délimiter
    un bloc scalaire, sans prétendre à un parseur YAML complet.
    """
    line_re = re.compile(rf"^(?P<indent>[ \t]*){re.escape(key)}:[ \t]*(?P<style>\|[+-]?|>[+-]?)?[ \t]*(?P<inline>.*)$")
    lines = text.splitlines()
    blocks, i, n = [], 0, len(lines)
    while i < n:
        match = line_re.match(lines[i])
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


def _job_blocks(text: str) -> dict:
    """Découpe le texte (déjà nettoyé des commentaires) en blocs par job, sous
    `jobs:`. Rend `{nom_du_job: texte_du_bloc}`, le nom du job restant en tête
    de son propre bloc (ex. `"evals:\\n    runs-on: ...\\n..."`)."""
    if "jobs:" not in text:
        return {}
    jobs_text = text.split("jobs:", 1)[1]
    parts = re.split(r"^  (?=[A-Za-z0-9_-]+:)", jobs_text, flags=re.MULTILINE)
    blocks = {}
    for part in parts:
        header = re.match(r"([A-Za-z0-9_-]+):", part)
        if header:
            blocks[header.group(1)] = part
    return blocks


class TestNoPwnRequestPattern(unittest.TestCase):
    """La classe de bug « pwn request » : `pull_request_target` + secrets + code de PR."""

    def test_no_workflow_uses_pull_request_target(self):
        """N'importe quelle forme YAML : mapping (`pull_request_target:`), liste
        de déclencheurs (`on: [pull_request_target]`) ou scalaire (`on: pull_request_target`)
        — revue PR #74, point 5 : l'ancienne regex n'attrapait que la forme mapping."""
        for path in WORKFLOW_FILES:
            with self.subTest(workflow=path.name):
                text = _strip_comments(path.read_text(encoding="utf-8"))
                self.assertNotRegex(
                    text, r"\bpull_request_target\b",
                    f"{path.name} : `pull_request_target` expose les secrets à du code de PR non fiable "
                    "(voir la section Sécurité de la PR #29) — utiliser `pull_request` (pas de secrets pour "
                    "les forks) avec une garde same-repo, ou un job `workflow_run` séparé.",
                )

    def test_no_run_or_script_block_interpolates_untrusted_text(self):
        """`run:` (shell) ET `script:` (github-script, lui aussi interpolé par Actions
        avant exécution — revue PR #74, point 4) : les deux sont scannés."""
        for path in WORKFLOW_FILES:
            text = path.read_text(encoding="utf-8")
            blocks = _extract_scalar_blocks(text, "run") + _extract_scalar_blocks(text, "script")
            for block in blocks:
                with self.subTest(workflow=path.name, block=block[:60]):
                    self.assertNotRegex(
                        block, _UNTRUSTED_INTERPOLATION,
                        f"{path.name} : un `run:`/`script:` interpole du texte non fiable "
                        "(champ de PR/issue/push, nom de branche, `inputs.*`…) — faire transiter cette "
                        "valeur par `env:` puis `$VAR`/`process.env`, jamais directement dans le bloc.",
                    )


class TestPermissionsAreExplicit(unittest.TestCase):
    """Un jeton par défaut (souvent `contents: write` selon les réglages du dépôt) ne doit
    jamais être hérité sans y penser — chaque workflow déclare ce dont il a besoin."""

    def test_every_workflow_declares_permissions(self):
        """`permissions:` de haut niveau, OU CHAQUE job (pas juste un seul — revue PR
        #74, point 3 : un unique job protégé ne dit rien des autres, qui hériteraient
        alors silencieusement du jeton par défaut du dépôt)."""
        for path in WORKFLOW_FILES:
            with self.subTest(workflow=path.name):
                text = _strip_comments(path.read_text(encoding="utf-8"))
                if re.search(r"^permissions:", text, re.MULTILINE):
                    continue
                jobs = _job_blocks(text)
                self.assertTrue(jobs, f"{path.name} : ni `permissions:` de haut niveau, ni job détecté")
                missing = [name for name, block in jobs.items()
                           if not re.search(r"^ {4}permissions:", block, re.MULTILINE)]
                self.assertFalse(
                    missing,
                    f"{path.name} : job(s) sans `permissions:` explicite ({', '.join(sorted(missing))}) et "
                    "aucun `permissions:` de haut niveau — le jeton par défaut du dépôt s'y appliquerait "
                    "silencieusement.",
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
        self.jobs = _job_blocks(self.text)

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

    def test_evals_job_if_condition_has_all_three_guards(self):
        """Isolé au job `evals` lui-même (revue PR #74, point 2) : avant, ces trois
        gardes étaient cherchées dans le fichier entier, donc une garde retirée du
        job `evals` mais laissée ailleurs (ex. dans le job `comment`) passait quand
        même — ce qui ne protège en rien le job qui exécute réellement les prompts."""
        self.assertIn("evals", self.jobs, "evals.yml : job `evals` introuvable")
        if_blocks = _extract_scalar_blocks(self.jobs["evals"], "if")
        self.assertTrue(if_blocks, "evals.yml : job `evals` sans condition `if:` de haut niveau")
        condition = if_blocks[0]  # le premier `if:` du bloc est celui du job (avant les `if:` de ses steps)
        self.assertRegex(
            condition, r"contains\([^)]*labels[^)]*,\s*'run-evals'\)",
            "evals.yml : le job `evals` ne vérifie pas l'étiquette `run-evals` dans sa propre condition",
        )
        self.assertIn(
            "head.repo.full_name == github.repository", condition,
            "evals.yml : le job `evals` ne porte pas la garde same-repo dans sa propre condition",
        )
        self.assertIn(
            "mmornati/ai-running-coach", condition,
            "evals.yml : le job `evals` ne vérifie pas le dépôt canonique (schedule/dispatch inclus)",
        )

    def test_comment_permission_is_isolated_from_the_eval_job(self):
        """Le job qui exécute les prompts (code du dépôt + outils MCP factices) ne
        doit pas porter `pull-requests: write` — seul le job qui poste le commentaire,
        et qui ne fait qu'écrire un fichier déjà produit, en a besoin (moindre
        privilège par job, cf. section Sécurité de la PR #29)."""
        writers = [name for name, block in self.jobs.items() if re.search(r"pull-requests:\s*write", block)]
        self.assertTrue(writers, "evals.yml : aucun job avec `pull-requests: write` — le commentaire de PR ne peut pas être posté")
        for name in writers:
            self.assertNotIn(
                "ANTHROPIC_API_KEY", self.jobs[name],
                f"evals.yml : le job `{name}` peut écrire sur la PR, il ne doit pas aussi exécuter "
                "les prompts (secret modèle) — cela recrée la surface qu'on isole.",
            )


if __name__ == "__main__":
    unittest.main()
