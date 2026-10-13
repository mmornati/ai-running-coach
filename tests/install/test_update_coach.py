"""Palier A — `scripts/update-coach.sh` (/update-coach) sur un vrai dépôt git jetable.

Un dépôt « amont » nu (v1.0.0 puis v1.1.0) et un clone qui joue le moteur installé.
`install.sh` et `coach_doctor.py` y sont des faux qui journalisent leurs arguments :
on vérifie l'avance rapide de main et la réinstallation avec les options MÉMORISÉES.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

FAKE_INSTALL = """#!/usr/bin/env bash
printf '%s\\n' "$@" > "$HOME/install-called"
"""
FAKE_DOCTOR = """import sys
print("doctor ok")
"""
# Faux `docker` : un conteneur compose en cours par ligne de $HOME/containers (projet, dossier,
# fichiers, service séparés par des tabulations) ; `compose config` rend le build.context lu dans
# $HOME/context-<projet> ; `compose build|up` est journalisé dans $HOME/docker-calls.
FAKE_DOCKER = """#!/usr/bin/env bash
case "$1" in
    info) [[ -f "$HOME/docker-down" ]] && exit 1; exit 0 ;;
    ps) cat "$HOME/containers" 2>/dev/null; exit 0 ;;
    compose)
        shift; project=""
        while [[ $# -gt 0 ]]; do
            case "$1" in
                -p) project="$2"; shift 2 ;;
                --project-directory|-f) shift 2 ;;
                *) break ;;
            esac
        done
        if [[ "$1" == config ]]; then
            printf '{"services": {"dashboard": {"build": {"context": "%s"}}}}' "$(cat "$HOME/context-$project")"
        else
            printf '%s %s\\n' "$project" "$*" >> "$HOME/docker-calls"
        fi ;;
esac
"""


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false",
         "-c", "tag.gpgsign=false", "-c", "init.defaultBranch=main", *args],
        cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


@unittest.skipUnless(shutil.which("git"), "git absent")
class UpdateCoach(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        self.home = self.tmp / "home"
        (self.home / ".config/ai-running-coach").mkdir(parents=True)
        seed = self.seed = self.tmp / "seed"
        (seed / "scripts/lib").mkdir(parents=True)
        for rel in ("scripts/update-coach.sh", "scripts/lib/config.sh", "scripts/arc_version.py"):
            shutil.copy2(REPO / rel, seed / rel)
        (seed / "scripts/coach_doctor.py").write_text(FAKE_DOCTOR, encoding="utf-8")
        (seed / "install.sh").write_text(FAKE_INSTALL, encoding="utf-8")
        (seed / "install.sh").chmod(0o755)
        (seed / "VERSION").write_text("1.0.0\n", encoding="utf-8")
        git(seed, "init", "-q")
        git(seed, "add", ".")
        git(seed, "commit", "-q", "-m", "v1.0.0")
        git(seed, "tag", "-a", "v1.0.0", "-m", "v1.0.0")
        self.upstream = self.tmp / "upstream.git"
        git(self.tmp, "clone", "-q", "--bare", str(seed), str(self.upstream))
        self.engine = self.tmp / "engine"
        git(self.tmp, "clone", "-q", str(self.upstream), str(self.engine))
        # Nouvelle release publiée en amont après l'installation.
        (seed / "VERSION").write_text("1.1.0\n", encoding="utf-8")
        git(seed, "commit", "-q", "-am", "v1.1.0")
        git(seed, "tag", "-a", "v1.1.0", "-m", "v1.1.0")
        git(seed, "push", "-q", "--tags", str(self.upstream), "main")
        self.args_file = self.home / ".config/ai-running-coach/install-args"
        self.args_file.write_text("--ide\nclaude\n--workspace\n/chemin avec espaces/ws\n", encoding="utf-8")

    def run_update(self, *args: str, **env: str) -> subprocess.CompletedProcess:
        full_env = {**os.environ, "HOME": str(self.home), "ARC_WORKSPACE": str(self.tmp / "ws"),
                    "ARC_HEADLESS": "", **env}
        raw = subprocess.run([str(self.engine / "scripts/update-coach.sh"), *args], cwd=self.tmp,
                             env=full_env, capture_output=True, stdin=subprocess.DEVNULL)
        # Décodage tolérant : un octet invalide (vu sur macOS) ne doit pas masquer le vrai message.
        return subprocess.CompletedProcess(raw.args, raw.returncode,
                                           raw.stdout.decode("utf-8", "backslashreplace"),
                                           raw.stderr.decode("utf-8", "backslashreplace"))

    def head(self) -> str:
        return git(self.engine, "rev-parse", "HEAD")

    def test_check_reports_without_changing_anything(self):
        before = self.head()
        proc = self.run_update("--check")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("v1.1.0", proc.stdout)
        self.assertIn("/chemin\\ avec\\ espaces/ws", proc.stdout)
        self.assertEqual(self.head(), before)
        self.assertFalse((self.home / "install-called").exists())

    def test_yes_fast_forwards_and_reinstalls_with_remembered_options(self):
        proc = self.run_update("--yes")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertEqual(self.head(), git(self.upstream, "rev-parse", "main"))
        called = (self.home / "install-called").read_text(encoding="utf-8").splitlines()
        self.assertEqual(called, ["--ide", "claude", "--workspace", "/chemin avec espaces/ws", "--no-auth"])
        self.assertIn("doctor ok", proc.stdout)
        # Messages lisibles : aucun caractère coupé en deux (octets invalides vus sur macOS).
        self.assertNotIn("\\x", proc.stdout + proc.stderr, f"sortie non UTF-8 :\n{proc.stdout}\n{proc.stderr}")

    def test_install_is_rerun_without_auth_and_without_stdin_when_there_is_no_terminal(self):
        proc = self.run_update("--yes")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        called = (self.home / "install-called").read_text(encoding="utf-8").splitlines()
        self.assertEqual(called[-1], "--no-auth")
        self.assertIn("--no-auth", proc.stderr + proc.stdout)

    def test_stops_at_the_latest_release_not_at_the_tip_of_main(self):
        release = git(self.upstream, "rev-parse", "v1.1.0^{commit}")
        (self.seed / "WIP").write_text("pas encore publié\n", encoding="utf-8")
        git(self.seed, "add", "WIP")
        git(self.seed, "commit", "-q", "-m", "travail non publié")
        git(self.seed, "tag", "-a", "v1.2.0-rc.1", "-m", "pré-version")
        git(self.seed, "push", "-q", "--tags", str(self.upstream), "main")
        proc = self.run_update("--yes")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertEqual(self.head(), release)
        self.assertFalse((self.engine / "WIP").exists())
        proc = self.run_update("--yes")
        self.assertIn("Déjà à jour", proc.stdout)

    def test_already_up_to_date(self):
        self.assertEqual(self.run_update("--yes").returncode, 0)
        (self.home / "install-called").unlink()
        proc = self.run_update("--yes")
        self.assertEqual(proc.returncode, 0)
        self.assertIn("Déjà à jour", proc.stdout)
        self.assertFalse((self.home / "install-called").exists())

    def test_without_terminal_and_without_yes_nothing_happens(self):
        before = self.head()
        proc = self.run_update()
        self.assertEqual(proc.returncode, 1)
        self.assertEqual(self.head(), before)

    def test_missing_install_args(self):
        self.args_file.unlink()
        proc = self.run_update("--yes")
        self.assertEqual(proc.returncode, 4)
        self.assertIn("docs/update.md", proc.stderr)

    def test_local_changes_are_never_overwritten(self):
        (self.engine / "VERSION").write_text("bricolé\n", encoding="utf-8")
        proc = self.run_update("--yes")
        self.assertEqual(proc.returncode, 5)
        self.assertEqual((self.engine / "VERSION").read_text(encoding="utf-8"), "bricolé\n")

    def test_feature_branch_is_left_alone(self):
        git(self.engine, "switch", "-q", "-c", "ma-branche")
        proc = self.run_update("--yes")
        self.assertEqual(proc.returncode, 5)
        self.assertIn("ma-branche", proc.stderr)

    def test_refused_in_headless_runs(self):
        before = self.head()
        proc = self.run_update("--yes", ARC_HEADLESS="1")
        self.assertEqual(proc.returncode, 1)
        self.assertEqual(self.head(), before)

    def test_engine_without_git(self):
        shutil.rmtree(self.engine / ".git")
        proc = self.run_update("--check")
        self.assertEqual(proc.returncode, 3)
        self.assertIn("macOS", proc.stderr)


    # --- Tableaux de bord Docker construits depuis le moteur --------------------------------
    def fake_docker(self, *projects: tuple[str, str]) -> dict[str, str]:
        """Installe le faux docker ; projects = (nom, build.context) de conteneurs en cours."""
        bindir = self.tmp / "bin"
        bindir.mkdir(exist_ok=True)
        (bindir / "docker").write_text(FAKE_DOCKER, encoding="utf-8")
        (bindir / "docker").chmod(0o755)
        lines = []
        for name, context in projects:
            folder = self.tmp / "docker" / name
            folder.mkdir(parents=True, exist_ok=True)
            lines.append(f"{name}\t{folder}\t{folder}/compose.yaml\tdashboard\n")
            (self.home / f"context-{name}").write_text(context, encoding="utf-8")
        (self.home / "containers").write_text("".join(lines), encoding="utf-8")
        return {"PATH": f"{bindir}{os.pathsep}{os.environ['PATH']}"}

    def docker_calls(self) -> list[str]:
        calls = self.home / "docker-calls"
        return calls.read_text(encoding="utf-8").splitlines() if calls.exists() else []

    def test_docker_dashboard_built_from_the_engine_is_rebuilt(self):
        env = self.fake_docker(("coach", str(self.engine)), ("autre", str(self.tmp / "ailleurs")))
        proc = self.run_update("--check", **env)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("« coach » reconstruit", proc.stdout)
        self.assertNotIn("autre", proc.stdout)
        self.assertEqual(self.docker_calls(), [])
        proc = self.run_update("--yes", **env)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertEqual(self.docker_calls(), ["coach build --pull dashboard", "coach up -d dashboard"])
        self.assertIn("« coach » reconstruit et relancé", proc.stdout)

    def test_container_managed_by_install_sh_is_rebuilt_too(self):
        env = self.fake_docker(("arc-dashboard", str(self.engine)))
        proc = self.run_update("--yes", **env)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertEqual(self.docker_calls(), ["arc-dashboard build --pull dashboard", "arc-dashboard up -d dashboard"])

    def test_already_up_to_date_never_rebuilds(self):
        env = self.fake_docker(("coach", str(self.engine)))
        self.assertEqual(self.run_update("--yes", **env).returncode, 0)
        (self.home / "docker-calls").unlink()
        proc = self.run_update("--yes", **env)
        self.assertIn("Déjà à jour", proc.stdout)
        self.assertEqual(self.docker_calls(), [])

    def test_no_docker_dashboard_means_no_docker_call(self):
        env = self.fake_docker()
        proc = self.run_update("--yes", **env)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertEqual(self.docker_calls(), [])
        self.assertNotIn("Docker «", proc.stdout)

    def test_unreachable_docker_daemon_is_silent(self):
        env = self.fake_docker(("coach", str(self.engine)))
        (self.home / "docker-down").touch()
        proc = self.run_update("--yes", **env)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertEqual(self.docker_calls(), [])
        self.assertNotIn("Docker «", proc.stdout + proc.stderr)


if __name__ == "__main__":
    unittest.main()
