"""Assertions partagées par les tests d'installation."""

from __future__ import annotations

import unittest
from pathlib import Path


def _tail(proc, limit: int = 4000) -> str:
    return f"\n--- stdout ---\n{proc.stdout[-limit:]}\n--- stderr ---\n{proc.stderr[-limit:]}"


class InstallAsserts(unittest.TestCase):
    """Base des cas de test : assertions lisibles + diagnostic utile en échec."""

    def assertSucceeded(self, proc, msg: str = "") -> None:
        if proc.returncode != 0:
            self.fail(f"{msg or 'commande'} : code {proc.returncode}{_tail(proc)}")

    def assertFailed(self, proc, msg: str = "") -> None:
        if proc.returncode == 0:
            self.fail(f"{msg or 'commande'} : succès inattendu{_tail(proc)}")

    def assertOutputContains(self, proc, needle: str) -> None:
        if needle not in proc.stdout + proc.stderr:
            self.fail(f"« {needle} » absent de la sortie{_tail(proc)}")

    def assertOutputLacks(self, proc, needle: str) -> None:
        if needle in proc.stdout + proc.stderr:
            self.fail(f"« {needle} » présent alors qu'il ne devrait pas{_tail(proc)}")

    def assertIsFile(self, path: Path, msg: str = "") -> None:
        if not Path(path).is_file():
            self.fail(f"fichier attendu absent : {path} {msg}")

    def assertIsSymlink(self, path: Path) -> None:
        if not Path(path).is_symlink():
            self.fail(f"lien symbolique attendu : {path}")

    def assertResolves(self, path: Path) -> None:
        """Le chemin existe et, si c'est un lien, il n'est pas mort."""
        p = Path(path)
        if not p.exists():
            self.fail(f"chemin inexistant ou lien mort : {path}")

    def assertPopulated(self, directory: Path, minimum: int = 1) -> None:
        d = Path(directory)
        if not d.is_dir():
            self.fail(f"répertoire attendu : {directory}")
        entries = [e for e in d.iterdir() if e.exists()]
        if len(entries) < minimum:
            self.fail(
                f"{directory} contient {len(entries)} élément(s) résolvable(s), "
                f"{minimum} attendu(s) au minimum"
            )

    def assertFileContains(self, path: Path, needle: str) -> None:
        self.assertIsFile(path)
        content = Path(path).read_text(encoding="utf-8", errors="replace")
        if needle not in content:
            self.fail(f"« {needle} » absent de {path}\n--- contenu ---\n{content[:4000]}")

    def assertFileLacks(self, path: Path, needle: str) -> None:
        self.assertIsFile(path)
        content = Path(path).read_text(encoding="utf-8", errors="replace")
        if needle in content:
            self.fail(f"« {needle} » présent dans {path} alors qu'il ne devrait pas")

    def assertCalled(self, sandbox, tool: str, contains: str = "") -> None:
        calls = sandbox.stub_calls(tool)
        if not calls:
            self.fail(f"{tool} n'a jamais été appelé (appels : {sandbox.stub_calls()})")
        if contains and not any(contains in args for _, args in calls):
            self.fail(f"{tool} appelé, mais jamais avec « {contains} » : {calls}")

    def assertNotCalled(self, sandbox, tool: str) -> None:
        calls = sandbox.stub_calls(tool)
        if calls:
            self.fail(f"{tool} appelé alors qu'il ne devrait pas : {calls}")

    def assertTreeUnchanged(self, before: dict, after: dict, msg: str = "") -> None:
        added = sorted(set(after) - set(before))
        removed = sorted(set(before) - set(after))
        changed = sorted(k for k in set(before) & set(after) if before[k] != after[k])
        if added or removed or changed:
            self.fail(
                f"{msg or 'arbre modifié'}\n"
                f"  ajoutés  : {added[:20]}\n"
                f"  retirés  : {removed[:20]}\n"
                f"  modifiés : {changed[:20]}"
            )
