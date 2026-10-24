"""Exécute les transactions sur de faux moteurs, sans toucher au Mac de l'athlète."""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import unittest
import unittest.mock

ROOT = Path(__file__).resolve().parents[2]
HELPER = ROOT / "scripts/arc_engine_update.py"
spec = importlib.util.spec_from_file_location("engine_update", HELPER)
update = importlib.util.module_from_spec(spec)
spec.loader.exec_module(update)


class TestEngineUpdate(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="arc update test ")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.workspace = self.root / "données"
        self.workspace.mkdir()
        (self.workspace / "profile.md").write_text("Personnel inchangé")
        self.engine = self.root / "engine"
        self.engine.mkdir()
        (self.engine / "version").write_text("old")

    def archive(self, script="exit 0", *, valid=True):
        source = self.root / "source"
        source.mkdir(exist_ok=True)
        (source / "version").write_text("new")
        if valid:
            (source / "install.sh").write_text(script)
        archive = self.root / "engine.tar.gz"
        with tarfile.open(archive, "w:gz") as tar:
            tar.add(source, arcname=".")
        return archive

    def run_update(self, archive):
        return subprocess.run([sys.executable, str(HELPER), "--workspace", str(self.workspace),
                               "--engine", str(self.engine), "--archive", str(archive), "--",
                               "--workspace", str(self.workspace)], capture_output=True, text=True)

    def test_success_replaces_engine_and_preserves_personal_data(self):
        result = self.run_update(self.archive('test "$1" = --workspace && test -f "$2/profile.md"'))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.engine / "version").read_text(), "new")
        self.assertEqual((self.workspace / "profile.md").read_text(), "Personnel inchangé")

    def test_installer_failure_restores_old_engine(self):
        result = self.run_update(self.archive("exit 23"))
        self.assertEqual(result.returncode, 1)
        self.assertIn("23", result.stderr)
        self.assertEqual((self.engine / "version").read_text(), "old")

    def test_invalid_archive_does_not_replace_engine(self):
        result = self.run_update(self.archive(valid=False))
        self.assertEqual(result.returncode, 1)
        self.assertEqual((self.engine / "version").read_text(), "old")

    def test_corrupt_archive_does_not_replace_engine(self):
        archive = self.root / "broken.tar.gz"
        archive.write_text("not a tar archive")
        self.assertEqual(self.run_update(archive).returncode, 1)
        self.assertEqual((self.engine / "version").read_text(), "old")

    def test_running_sync_defers_update_then_allows_retry(self):
        archive = self.archive()
        fd = update.acquire_lock(self.workspace, exclusive=False)
        try:
            self.assertEqual(self.run_update(archive).returncode, update.BUSY)
            self.assertEqual((self.engine / "version").read_text(), "old")
        finally:
            os.close(fd)
        self.assertEqual(self.run_update(archive).returncode, 0)

    def test_legacy_running_sync_is_respected_but_stale_pid_is_ignored(self):
        logs = self.workspace / "logs"
        logs.mkdir()
        marker = logs / ".sync.lock"
        marker.write_text(str(os.getpid()))
        archive = self.archive()
        self.assertEqual(self.run_update(archive).returncode, update.BUSY)
        marker.write_text("invalid pid")
        self.assertEqual(self.run_update(archive).returncode, 0)

    def test_update_blocks_sync_before_command_runs(self):
        marker = self.root / "command-ran"
        fd = update.acquire_lock(self.workspace, exclusive=True)
        try:
            result = subprocess.run([sys.executable, str(HELPER), "--workspace", str(self.workspace),
                                     "--sync", "--", "/usr/bin/touch", str(marker)], capture_output=True)
            self.assertEqual(result.returncode, 0)
            self.assertFalse(marker.exists())
        finally:
            os.close(fd)

    def test_sync_exec_holds_lock_and_propagates_exit_status(self):
        code = '''import fcntl, os, sys
fd = os.open(sys.argv[1], os.O_RDWR)
try:
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
except BlockingIOError:
    sys.exit(42)
sys.exit(99)
'''
        result = subprocess.run([sys.executable, str(HELPER), "--workspace", str(self.workspace),
                                 "--sync", "--", sys.executable, "-c", code,
                                 str(self.workspace / "logs/.engine.lock")])
        self.assertEqual(result.returncode, 42)
        fd = update.acquire_lock(self.workspace, exclusive=True)
        os.close(fd)

    def test_workspace_inside_engine_is_rejected_before_any_change(self):
        original = self.workspace
        self.workspace = self.engine / "personal"
        self.workspace.mkdir()
        (self.workspace / "profile.md").write_text("précieux")
        self.assertEqual(self.run_update(self.archive()).returncode, 1)
        self.assertEqual((self.workspace / "profile.md").read_text(), "précieux")
        self.workspace = original

    def test_interrupted_swap_recovers_backup_before_retry(self):
        self.engine.rename(self.engine.with_name("engine.previous"))
        self.engine.mkdir()
        (self.engine / "version").write_text("incomplete")
        self.assertEqual(self.run_update(self.archive("exit 9")).returncode, 1)
        self.assertEqual((self.engine / "version").read_text(), "old")
        self.assertFalse(self.engine.with_name("engine.previous").exists())


class TestStandaloneHelper(unittest.TestCase):
    """Défaut verrouillé : le helper est embarqué SEUL dans l'app macOS (build-macos-dmg.sh) ; un import
    frère (ex. `coach_config`) planterait la mise à jour du moteur de l'app livrée (#127)."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="arc standalone ")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.alone = self.root / "Resources"
        self.alone.mkdir()
        (self.alone / "arc_engine_update.py").write_text(HELPER.read_text(encoding="utf-8"), encoding="utf-8")
        self.ws = self.root / "ws"
        self.ws.mkdir()

    def run_alone(self, *argv, env=None):
        return subprocess.run([sys.executable, "-I", str(self.alone / "arc_engine_update.py"), *argv],
                              capture_output=True, text=True, cwd=self.alone, env=env or {})

    def test_helper_runs_without_any_sibling_module(self):
        result = self.run_alone("--help")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("ModuleNotFoundError", result.stderr)

    def test_lock_refusal_works_without_sibling_module(self):
        other = self.root / "autre"
        other.mkdir()
        env = {"ARC_LOCK_WORKSPACE": "1", "ARC_WORKSPACE": str(self.ws)}
        result = self.run_alone("--workspace", str(other), "--sync", "--", "true", env=env)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("workspace refusé", result.stderr)
        self.assertNotIn("ModuleNotFoundError", result.stderr)

    def test_lock_accepts_nfc_nfd_and_case_variants_of_same_folder(self):
        # Défaut : chemin NFC/casse différente du même dossier refusé à tort ("workspace refusé") sur APFS.
        import unicodedata
        sys.path.insert(0, str(ROOT / "scripts"))
        self.addCleanup(sys.path.remove, str(ROOT / "scripts"))
        import coach_config
        nfd_dir = self.root / unicodedata.normalize("NFD", "données-é")
        nfd_dir.mkdir()
        variants = [("nfc", self.root / unicodedata.normalize("NFC", "données-é"))]
        probe = self.root / "CaseProbe"
        probe.mkdir()
        if (self.root / "caseprobe").exists():
            variants.append(("case", self.root / "DONNÉES-É"))
        env = {"ARC_LOCK_WORKSPACE": "1", "ARC_WORKSPACE": str(nfd_dir)}
        for label, target in variants:
            if not target.exists():
                continue  # système de fichiers sensible à la casse / normalisation (Linux) : sans objet
            for fn in (update.enforce_workspace_lock, coach_config.enforce_workspace_lock):
                with self.subTest(label, fn=fn.__module__), unittest.mock.patch.dict(os.environ, env, clear=True):
                    fn(target)

    def test_inline_lock_matches_coach_config(self):
        sys.path.insert(0, str(ROOT / "scripts"))
        self.addCleanup(sys.path.remove, str(ROOT / "scripts"))
        import coach_config
        link = self.root / "lien"
        link.symlink_to(self.ws)
        foreign = self.root / "autre"
        foreign.mkdir()
        cases = [
            ("same dir", {"ARC_LOCK_WORKSPACE": "1", "ARC_WORKSPACE": str(self.ws)}, self.ws),
            ("symlinked same dir", {"ARC_LOCK_WORKSPACE": "1", "ARC_WORKSPACE": str(self.ws)}, link),
            ("foreign dir", {"ARC_LOCK_WORKSPACE": "1", "ARC_WORKSPACE": str(self.ws)}, foreign),
            ("empty ARC_WORKSPACE", {"ARC_LOCK_WORKSPACE": "1", "ARC_WORKSPACE": " "}, self.ws),
            ("unset ARC_WORKSPACE", {"ARC_LOCK_WORKSPACE": "1"}, self.ws),
            ("no lock", {"ARC_WORKSPACE": str(self.ws)}, foreign),
        ]

        def outcome(fn, env, target):
            with unittest.mock.patch.dict(os.environ, env, clear=True):
                try:
                    return ("ok", fn(target))
                except SystemExit as exc:
                    return ("refused", str(exc))

        for label, env, target in cases:
            with self.subTest(label):
                self.assertEqual(outcome(update.enforce_workspace_lock, env, target),
                                 outcome(coach_config.enforce_workspace_lock, env, target))
