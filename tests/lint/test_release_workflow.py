"""Palier B — une release ne pousse jamais rien sur `main`.

`main` peut exiger une pull request et le statut « Tests » (règle de protection) :
sur un dépôt personnel, GitHub Actions ne peut pas y être déclaré en exception, et
un push du GITHUB_TOKEN vers `main` serait refusé. « Tag a release » ne fait donc
que poser un tag sur le commit testé ; le numéro de version vient du tag, écrit au
build dans l'image Docker (publish.yml) et dans le moteur embarqué du DMG.
"""

from __future__ import annotations

import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests.lint.test_docker import IMAGE, _step_run_block

REPO = Path(__file__).resolve().parent.parent.parent
WORKFLOWS = REPO / ".github/workflows"
TAG_YML = WORKFLOWS / "tag.yml"
PUBLISH_YML = WORKFLOWS / "publish.yml"
DMG_SCRIPT = REPO / "scripts/build-macos-dmg.sh"

# Hors de la configuration de l'utilisateur (signature des tags, hooks…).
GIT_ENV = dict(os.environ, GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1")


def _git_repo(tags: tuple[str, ...], extra_commits: int = 0) -> tempfile.TemporaryDirectory:
    """Dépôt jetable : un commit tagué `tags`, puis `extra_commits` commits non tagués."""
    repo = tempfile.TemporaryDirectory()
    git = ["git", "-C", repo.name, "-c", "user.name=t", "-c", "user.email=t@t"]
    subprocess.run(git[:3] + ["init", "-q"], check=True, env=GIT_ENV)
    subprocess.run(git + ["commit", "-q", "--allow-empty", "-m", "init"], check=True, env=GIT_ENV)
    for tag in tags:
        subprocess.run(git + ["tag", tag], check=True, env=GIT_ENV)
    for i in range(extra_commits):
        subprocess.run(git + ["commit", "-q", "--allow-empty", "-m", f"c{i}"], check=True, env=GIT_ENV)
    return repo


class TestTagWorkflowNeverPushesMain(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = TAG_YML.read_text(encoding="utf-8")
        cls.code = "\n".join(re.split(r"(?<!\S)#", line, maxsplit=1)[0] for line in cls.text.splitlines())

    def test_no_commit_and_no_branch_push(self):
        self.assertNotIn("git commit", self.code)
        self.assertNotIn("git add", self.code)
        self.assertIsNone(re.search(r"HEAD:|refs/heads/main\b(?!')|origin\s+main\b", self.code),
                          "tag.yml ne doit rien pousser sur main")
        pushes = re.findall(r"git push\b.*", self.code)
        self.assertTrue(pushes, "tag.yml doit pousser le tag")
        for push in pushes:
            self.assertIn("refs/tags/", push, f"push autre qu'un tag : {push}")

    def test_tag_is_the_tested_commit(self):
        """Le commit vérifié (Tests verts) et le commit tagué sont tous deux github.sha."""
        tests = _step_run_block(self.text, "Tests verts sur le commit à taguer")
        self.assertIn("commits/$SHA/check-runs?check_name=Tests", tests)
        tag = _step_run_block(self.text, "Création et push du tag")
        self.assertRegex(tag, r'git tag -a "\$TAG" -m "[^"]*" "\$SHA"')
        self.assertEqual(self.text.count("SHA: ${{ github.sha }}"), 2)

    def test_still_main_only(self):
        self.assertIn("if: github.ref == 'refs/heads/main'", self.text)


class TestNextVersion(unittest.TestCase):
    """Exécute l'étape « Calcul de la prochaine version » comme Actions."""

    @classmethod
    def setUpClass(cls):
        cls.script = _step_run_block(TAG_YML.read_text(encoding="utf-8"), "Calcul de la prochaine version")
        cls.repo = _git_repo(("v1.2.0", "v1.3.0", "v1.4.0-rc.1"), extra_commits=2)

    @classmethod
    def tearDownClass(cls):
        cls.repo.cleanup()

    def next_tag(self, *, bump="minor", version="", version_file="1.3.0"):
        Path(self.repo.name, "VERSION").write_text(version_file + "\n", encoding="utf-8")
        with tempfile.NamedTemporaryFile("r", suffix=".out") as out:
            env = dict(GIT_ENV, BUMP=bump, VERSION=version, GITHUB_OUTPUT=out.name)
            proc = subprocess.run(["bash", "-c", self.script], cwd=self.repo.name, env=env,
                                  capture_output=True, text=True)
            tag = re.search(r"^tag=(.*)$", out.read(), re.MULTILINE)
        return proc.returncode, tag.group(1) if tag else None, proc.stdout

    def test_bumps_from_last_stable_tag(self):
        for bump, expected in (("patch", "v1.3.1"), ("minor", "v1.4.0"), ("major", "v2.0.0")):
            with self.subTest(bump=bump):
                self.assertEqual(self.next_tag(bump=bump)[:2], (0, expected))

    def test_explicit_version_gets_v_prefix(self):
        self.assertEqual(self.next_tag(version="1.5.0-rc.1")[:2], (0, "v1.5.0-rc.1"))

    def test_existing_or_invalid_tag_is_refused(self):
        for version in ("v1.3.0", "v1.4", "latest"):
            with self.subTest(version=version):
                code, tag, _ = self.next_tag(version=version)
                self.assertNotEqual(code, 0)
                self.assertIsNone(tag)

    def test_stale_version_file_only_warns(self):
        """VERSION n'est plus réécrit par la release : un écart est signalé, jamais bloquant."""
        code, tag, stdout = self.next_tag(version_file="1.2.0")
        self.assertEqual((code, tag), (0, "v1.4.0"))
        self.assertIn("::notice::VERSION", stdout)
        self.assertNotIn("::notice::", self.next_tag(version="v1.3.5", version_file="1.3.5")[2])


class TestImageVersionFile(unittest.TestCase):
    """L'image n'a pas de .git : son fichier VERSION est écrit depuis le tag au build."""

    @classmethod
    def setUpClass(cls):
        cls.script = _step_run_block(PUBLISH_YML.read_text(encoding="utf-8"), "Calcul des étiquettes")
        cls.repo = _git_repo(("v1.3.0",), extra_commits=2)

    @classmethod
    def tearDownClass(cls):
        cls.repo.cleanup()

    def version_file(self, *, input_tag="", ref_name="main"):
        path = Path(self.repo.name, "VERSION")
        path.write_text("1.2.0\n", encoding="utf-8")
        with tempfile.NamedTemporaryFile("r", suffix=".out") as out:
            env = dict(GIT_ENV, IMAGE=IMAGE, INPUT_TAG=input_tag, REF_TYPE="branch",
                       REF_NAME=ref_name, GITHUB_OUTPUT=out.name)
            proc = subprocess.run(["bash", "-c", self.script], cwd=self.repo.name, env=env,
                                  capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return path.read_text(encoding="utf-8").strip()

    def test_release_image_carries_the_tag(self):
        self.assertEqual(self.version_file(input_tag="v1.4.0"), "1.4.0")

    def test_edge_image_carries_git_describe(self):
        self.assertRegex(self.version_file(), r"^1\.3\.0-2-g[0-9a-f]{7,}$")


class TestDmgEngineVersion(unittest.TestCase):
    def test_embedded_engine_version_is_the_dmg_version(self):
        """Le VERSION du dépôt peut retarder : le moteur embarqué reçoit ARC_APP_VERSION."""
        script = DMG_SCRIPT.read_text(encoding="utf-8")
        self.assertIn('VERSION="${ARC_APP_VERSION:-$VERSION}"', script)
        self.assertIn("':(exclude)VERSION'", script)
        self.assertIn('printf \'%s\\n\' "$VERSION" > "$BUILD_ROOT/engine-version/VERSION"', script)
        self.assertIn('tar -rf "$BUILD_ROOT/engine.tar" -C "$BUILD_ROOT/engine-version" VERSION', script)


if __name__ == "__main__":
    unittest.main()
