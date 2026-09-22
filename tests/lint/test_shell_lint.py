"""Palier B — hygiène des scripts shell, indépendante de la machine.

Ces contrôles verrouillent des régressions que les tests d'intégration ne
peuvent pas garantir partout : le cas « aucun gestionnaire de services » n'est
pas atteignable sur une machine qui a tmux, mais le motif fautif, lui, est
toujours visible dans le source.
"""

from __future__ import annotations

import re
import subprocess
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
SHELL_SCRIPTS = sorted(
    [REPO / "install.sh"]
    + list((REPO / "scripts").glob("*.sh"))
    + list((REPO / "scripts/lib").glob("*.sh"))
)
PYTHON_SCRIPTS = sorted(
    list((REPO / "scripts").glob("*.py")) + list((REPO / "skills").glob("*/scripts/*.py"))
)


class TestSyntax(unittest.TestCase):
    def test_shell_scripts_parse(self):
        for path in SHELL_SCRIPTS:
            with self.subTest(script=path.name):
                proc = subprocess.run(["bash", "-n", str(path)], capture_output=True, text=True)
                self.assertEqual(proc.returncode, 0, f"{path.name} : {proc.stderr}")

    def test_python_scripts_compile(self):
        import ast

        for path in PYTHON_SCRIPTS:
            with self.subTest(script=path.name):
                try:
                    ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
                except SyntaxError as exc:
                    self.fail(f"{path} : {exc}")


class TestFatalErrorsReachTheParentShell(unittest.TestCase):
    """`die` dans `$(fonction)` ne tue que le sous-shell.

    C'est ce qui faisait que `coach-remote.sh` annonçait « Sur le téléphone : … »
    après avoir constaté qu'aucun backend n'était disponible.
    """

    # Fonctions dont l'échec est fatal : leur statut doit être testé.
    STATUS_BEARING = ("backend",)

    def test_status_bearing_functions_are_not_called_bare(self):
        offenders = []
        for path in SHELL_SCRIPTS:
            for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                stripped = line.strip()
                if stripped.startswith("#"):
                    continue
                for func in self.STATUS_BEARING:
                    if f"$({func})" not in stripped:
                        continue
                    # Seule forme acceptée : une affectation, dont le statut est
                    # celui de la substitution, suivie d'un « || die ».
                    if re.match(rf'^\w+="\$\({func}\)"\s*\|\|\s*die\b', stripped):
                        continue
                    offenders.append(f"{path.name}:{lineno}: {stripped}")
        self.assertFalse(
            offenders,
            "statut ignoré sur une substitution de commande fatale :\n  " + "\n  ".join(offenders),
        )

    def test_no_die_inside_status_bearing_functions(self):
        for path in SHELL_SCRIPTS:
            text = path.read_text(encoding="utf-8")
            for func in self.STATUS_BEARING:
                match = re.search(rf"^{func}\(\) \{{(.*?)^\}}", text, re.DOTALL | re.MULTILINE)
                if not match:
                    continue
                with self.subTest(script=path.name, function=func):
                    self.assertNotIn(
                        "die ",
                        match.group(1),
                        f"{path.name} : « die » dans {func}() — inefficace en substitution de commande",
                    )


class TestGeneratedFilesAreFresh(unittest.TestCase):
    def test_gemini_commands_up_to_date(self):
        proc = subprocess.run(
            ["python3", str(REPO / "scripts/build-gemini-commands.py"), "--check"],
            capture_output=True,
            text=True,
            cwd=str(REPO),
        )
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

    def test_generated_files_carry_a_warning(self):
        for path in sorted((REPO / "config/gemini/commands").glob("*.toml")):
            with self.subTest(command=path.name):
                self.assertIn(
                    "NE PAS ÉDITER À LA MAIN",
                    path.read_text(encoding="utf-8").split("\n")[0],
                    f"{path.name} : en-tête « généré » absent",
                )


class TestPrerequisitesAreHonest(unittest.TestCase):
    """Le dépôt annonçait « bash 4+ » sans utiliser une seule construction bash 4."""

    BASH4_ONLY = [
        (r"declare\s+-A", "tableaux associatifs"),
        (r"local\s+-A", "tableaux associatifs locaux"),
        (r"\bmapfile\b", "mapfile"),
        (r"\breadarray\b", "readarray"),
        (r"\$\{[A-Za-z_][A-Za-z0-9_]*(\[[^]]*\])?,,", "${var,,}"),
        (r"\$\{[A-Za-z_][A-Za-z0-9_]*(\[[^]]*\])?\^\^", "${var^^}"),
        (r"\bcoproc\b", "coproc"),
        (r"\[\[\s+-v\s", "[[ -v ]]"),
    ]

    def test_no_bash4_only_constructs(self):
        found = []
        for path in SHELL_SCRIPTS:
            text = path.read_text(encoding="utf-8")
            for pattern, label in self.BASH4_ONLY:
                if re.search(pattern, text):
                    found.append(f"{path.name} : {label}")
        self.assertFalse(
            found,
            "constructions bash 4 détectées — soit les retirer, soit corriger les "
            "prérequis annoncés (macOS livre bash 3.2) :\n  " + "\n  ".join(found),
        )

    def test_documented_prerequisite_matches_reality(self):
        for relative in ("README.md", "docs/quickstart.md", "install.sh"):
            with self.subTest(document=relative):
                text = (REPO / relative).read_text(encoding="utf-8")
                self.assertNotIn(
                    "bash 4", text,
                    f"{relative} exige « bash 4 » alors qu'aucune construction bash 4 n'est utilisée",
                )
