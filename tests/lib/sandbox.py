"""Bac à sable d'exécution pour les tests d'installation.

`install.sh` écrit dans `$HOME/.config`, `$HOME/.claude.json`,
`$HOME/Library/LaunchAgents` et **la crontab de l'utilisateur**, et installe des
logiciels par le réseau. Une suite de tests qui toucherait l'un de ces éléments
sur la machine d'un contributeur serait pire que pas de tests du tout.

Le bac à sable :
  - place `HOME` dans un répertoire temporaire neuf, et refuse de démarrer si
    `HOME` désigne encore le vrai utilisateur ;
  - préfixe `PATH` avec `tests/lib/stubs/` (uv, curl, brew, crontab, launchctl,
    claude, …). Chaque stub journalise son argv dans `$ARC_STUB_LOG` ;
  - copie le dépôt dans le temporaire pour que les tests puissent observer les
    fichiers créés à côté du moteur.

Aucune modification du code de production n'est nécessaire : tous ces binaires
sont déjà invoqués via `PATH`.
"""

from __future__ import annotations

import json
import os
import pty
import select
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = TESTS_DIR.parent
STUBS_DIR = TESTS_DIR / "lib" / "stubs"

# Recopié tel quel dans le bac à sable. Tout le reste du dépôt (dont .git et les
# images de docs/) est inutile aux tests et coûte du temps à chaque cas.
COPIED = [
    "install.sh",
    "AGENTS.md",
    "agents",
    "skills",
    "scripts",
    "config",
    "templates",
    "web",
]


# Exécutables réels dont les scripts ont besoin lorsqu'on isole le PATH
# (tests qui doivent faire *disparaître* un binaire, p. ex. screen/tmux).
ESSENTIAL_BINARIES = [
    "awk", "basename", "bash", "cat", "chmod", "cp", "cut", "date", "dirname",
    "env", "find", "grep", "head", "id", "ln", "ls", "mkdir", "mktemp", "mv",
    "python3", "readlink", "rm", "sed", "sh", "sleep", "sort", "tail", "touch",
    "tr", "wc", "xargs",
]


class SandboxError(RuntimeError):
    pass


def _real_home() -> Path:
    return Path(os.path.expanduser("~")).resolve()


class Sandbox:
    """Contexte : un HOME jetable, un dépôt jetable, un PATH truqué."""

    def __init__(self, copy_repo: bool = True):
        self._tmp = tempfile.TemporaryDirectory(prefix="arc-test-")
        self.root = Path(self._tmp.name)
        self.home = self.root / "home"
        self.repo = self.root / "repo"
        self.stub_log = self.root / "stub.log"
        self.fake_crontab = self.root / "crontab.txt"

        self.home.mkdir()
        (self.home / ".config").mkdir()
        self.stub_log.touch()

        self._isolated_bin = None

        if copy_repo:
            self.repo.mkdir()
            for name in COPIED:
                src = REPO_ROOT / name
                if not src.exists():
                    continue
                dst = self.repo / name
                if src.is_dir():
                    shutil.copytree(src, dst, symlinks=True)
                else:
                    shutil.copy2(src, dst)
                    dst.chmod(src.stat().st_mode)

    # -- cycle de vie ------------------------------------------------------
    def __enter__(self) -> "Sandbox":
        return self

    def __exit__(self, *exc) -> None:
        self._tmp.cleanup()

    # -- environnement -----------------------------------------------------
    def isolated_bin(self, hide: tuple = ()) -> Path:
        """Un PATH réduit : coreutils + stubs, moins les outils `hide`.

        Indispensable pour tester « cet outil est absent de la machine » : on ne
        peut pas faire échouer `command -v` en ajoutant quelque chose au PATH,
        seulement en en retirant.
        """
        binroot = self.root / ("bin-" + ("none" if not hide else "-".join(sorted(hide))))
        if binroot.exists():
            return binroot
        binroot.mkdir()
        search = [
            Path(d)
            for d in os.environ.get("PATH", "").split(":")
            if d and Path(d) != STUBS_DIR
        ]
        for name in ESSENTIAL_BINARIES:
            if name in hide:
                continue
            for directory in search:
                candidate = directory / name
                if candidate.exists() and os.access(candidate, os.X_OK):
                    (binroot / name).symlink_to(candidate)
                    break
        for stub in STUBS_DIR.iterdir():
            if stub.name.startswith("_") or stub.name in hide:
                continue
            target = binroot / stub.name
            if target.exists() or target.is_symlink():
                target.unlink()
            target.symlink_to(stub)
        return binroot

    def env(self, hide: tuple = (), isolate: bool = False, **extra: str) -> dict:
        env = dict(os.environ)
        env.pop("ARC_WORKSPACE", None)
        if isolate or hide:
            path = str(self.isolated_bin(tuple(hide)))
        else:
            path = f"{STUBS_DIR}:{env.get('PATH', '')}"
        env.update(
            HOME=str(self.home),
            PATH=path,
            ARC_STUB_LOG=str(self.stub_log),
            ARC_FAKE_CRONTAB=str(self.fake_crontab),
            # Sorties déterministes, indépendantes de la locale du contributeur.
            LC_ALL="C",
            LANG="C",
        )
        env.setdefault("ARC_STUB_FAIL", "")
        env.update(extra)

        resolved = Path(env["HOME"]).resolve()
        if resolved == _real_home():
            raise SandboxError(
                "HOME pointe toujours sur le vrai utilisateur — refus de lancer le test."
            )
        return env

    # -- exécution ---------------------------------------------------------
    def run(
        self,
        argv: list,
        cwd: Path | None = None,
        stdin: str = "",
        timeout: int = 180,
        hide: tuple = (),
        isolate: bool = False,
        **env_extra: str,
    ) -> subprocess.CompletedProcess:
        return subprocess.run(
            argv,
            cwd=str(cwd or self.repo),
            env=self.env(hide=hide, isolate=isolate, **env_extra),
            input=stdin,
            capture_output=True,
            text=True,
            timeout=timeout,
        )

    def run_pty(
        self,
        argv: list,
        answers: list,
        cwd: Path | None = None,
        timeout: int = 60,
        **env_extra: str,
    ) -> subprocess.CompletedProcess:
        """Comme `run`, mais avec un vrai terminal.

        Nécessaire pour tout ce que les scripts gardent derrière `[[ -t 0 ]]` :
        `setup-ntfy.sh` et `coach-remote.sh` prennent une branche entièrement
        différente hors terminal, et c'est la branche interactive qui casse.
        """
        master, slave = pty.openpty()
        proc = subprocess.Popen(
            argv,
            cwd=str(cwd or self.repo),
            env=self.env(**env_extra),
            stdin=slave,
            stdout=slave,
            stderr=slave,
            close_fds=True,
        )
        os.close(slave)
        os.write(master, ("".join(f"{a}\n" for a in answers)).encode())

        chunks = []
        deadline = time.time() + timeout
        try:
            while True:
                if time.time() >= deadline:
                    proc.kill()
                    raise AssertionError(f"{argv[0]} n'a pas rendu la main en {timeout}s")
                ready, _, _ = select.select([master], [], [], 0.2)
                if ready:
                    try:
                        data = os.read(master, 4096)
                    except OSError:
                        data = b""       # le maître se ferme quand l'esclave part
                    if data:
                        chunks.append(data)
                        continue
                    break                # fin de flux : le processus se termine
                if proc.poll() is not None:
                    break
            try:
                proc.wait(timeout=max(1, int(deadline - time.time())))
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=10)
                raise AssertionError(f"{argv[0]} n'a pas rendu la main en {timeout}s")
        finally:
            os.close(master)
            if proc.poll() is None:
                proc.kill()
                proc.wait(timeout=10)

        output = b"".join(chunks).decode(errors="replace")
        return subprocess.CompletedProcess(argv, proc.returncode, output, "")

    def install(self, *args: str, **kwargs) -> subprocess.CompletedProcess:
        """Lance `install.sh` dans le bac à sable."""
        return self.run([str(self.repo / "install.sh"), *args], **kwargs)

    def script(self, name: str, *args: str, **kwargs) -> subprocess.CompletedProcess:
        """Lance un script de `scripts/` dans le bac à sable."""
        return self.run([str(self.repo / "scripts" / name), *args], **kwargs)

    # -- observation -------------------------------------------------------
    def stub_calls(self, tool: str | None = None) -> list:
        """Appels enregistrés, sous forme de couples (outil, args)."""
        calls = []
        for line in self.stub_log.read_text().splitlines():
            if not line.strip():
                continue
            name, _, args = line.partition("\t")
            if tool is None or name == tool:
                calls.append((name, args))
        return calls

    def crontab(self) -> str:
        return self.fake_crontab.read_text() if self.fake_crontab.exists() else ""

    def set_crontab(self, content: str) -> None:
        self.fake_crontab.write_text(content)

    def claude_json(self) -> dict:
        path = self.home / ".claude.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}

    def tree(self, *roots: Path) -> dict:
        """Empreinte d'un arbre : chemin relatif → contenu ou cible du lien.

        Sert aux tests d'idempotence et de dry-run.
        """
        snapshot = {}
        for root in roots or (self.home, self.repo):
            root = Path(root)
            if not root.exists():
                continue
            for path in sorted(root.rglob("*")):
                key = str(path.relative_to(self.root))
                if path.is_symlink():
                    snapshot[key] = f"-> {os.readlink(path)}"
                elif path.is_dir():
                    snapshot[key] = "<dir>"
                else:
                    try:
                        snapshot[key] = path.read_bytes()
                    except OSError as exc:  # pragma: no cover - diagnostic
                        snapshot[key] = f"<illisible: {exc}>"
        return snapshot
