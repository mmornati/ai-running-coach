"""Palier B — toute option `--workspace` passe par le verrou de la sync (#127).

`daily-sync.sh` pose `ARC_LOCK_WORKSPACE=1` ; seuls `coach_setup.workspace_root(explicit)` et
`coach_config.enforce_workspace_lock` le font respecter. Un script qui construit lui-même
`Path(args.workspace)` contournerait le verrou : le runner pourrait lire ou écrire le dossier d'un autre
membre du foyer. Les options qui désignent un fichier ou un dossier (`--db`, `--dir`, `--output-dir`) restent
hors périmètre, documenté dans docs/workspace.md.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
RESOLVERS = {"scripts/coach_setup.py", "scripts/coach_config.py"}
DIRECT = re.compile(r"\bPath\(\s*\w+\.workspace\b|\bos\.path\.\w+\(\s*\w+\.workspace\b"
                    r"|\.workspace\.(?:resolve|expanduser)\(")
# Angle mort corrigé : une option `type=Path` arrive déjà en Path, et `args.workspace.resolve()` /
# `.expanduser()` la résout sans passer par le verrou. Un fichier qui appelle `enforce_workspace_lock(`
# SUR CETTE OPTION (`enforce_workspace_lock(args.workspace)`, au parsing) peut ensuite la résoudre : c'est la
# liste blanche de ces motifs-là. Un appel du verrou sur autre chose (un autre argument) n'exempte rien.
TYPE_PATH = re.compile(r"\.workspace\.(?:resolve|expanduser)\(")
LOCKS_THE_OPTION = re.compile(r"enforce_workspace_lock\(\s*\w+\.workspace\b")


class TestWorkspaceOptionGoesThroughTheLock(unittest.TestCase):
    def _sources(self):
        yield from sorted((REPO / "scripts").glob("*.py"))
        yield from sorted((REPO / "skills").glob("*/scripts/*.py"))

    def test_the_pattern_flags_type_path_resolution(self):
        """Défaut verrouillé : `args.workspace.resolve()` (option `type=Path`) contournait le lint."""
        for line in ("ws = args.workspace.resolve()", "ws = opts.workspace.expanduser().resolve()",
                     "ws = Path(args.workspace)", "ws = os.path.abspath(args.workspace)"):
            self.assertTrue(DIRECT.search(line), line)
        self.assertFalse(DIRECT.search("ws = workspace_root(args.workspace)"))

    def test_the_exemption_needs_the_lock_on_the_workspace_option_itself(self):
        """Nit 9 : n'importe quel appel de `enforce_workspace_lock(` dans le fichier exemptait toutes ses lignes."""
        self.assertTrue(LOCKS_THE_OPTION.search("root = enforce_workspace_lock(args.workspace)"))
        self.assertFalse(LOCKS_THE_OPTION.search("enforce_workspace_lock(other_path)"))
        self.assertFalse(LOCKS_THE_OPTION.search("from coach_config import enforce_workspace_lock"))

    def test_no_direct_path_construction_from_the_workspace_option(self):
        offenders = []
        for path in self._sources():
            rel = path.relative_to(REPO).as_posix()
            if rel in RESOLVERS:
                continue
            text = path.read_text(encoding="utf-8")
            locked = bool(LOCKS_THE_OPTION.search(text))
            for number, line in enumerate(text.splitlines(), 1):
                if locked and TYPE_PATH.search(line) and not re.search(r"\bPath\(|os\.path\.", line):
                    continue
                if DIRECT.search(line) and not line.lstrip().startswith("#"):
                    offenders.append(f"{rel}:{number}: {line.strip()}")
        self.assertEqual(offenders, [], "passez par coach_setup.workspace_root(explicit) ou "
                                        "coach_config.enforce_workspace_lock")


if __name__ == "__main__":
    unittest.main()
