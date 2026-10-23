"""Palier B — le conteneur du tableau de bord ne s'expose jamais sans protection.

Le tableau de bord montre des données de santé et n'a pas d'authentification
propre. Ces contrôles statiques (sans Docker) verrouillent les invariants du
déploiement : aucun port publié, workspace en lecture seule, middleware
d'authentification obligatoire, utilisateur non root, image réduite au moteur.
"""

from __future__ import annotations

import os
import re
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
DOCKERFILE = REPO / "Dockerfile"
DEPLOY = REPO / "deploy/dashboard"
COMPOSE_FILES = sorted(DEPLOY.glob("compose*.yaml"))
WORKFLOWS = REPO / ".github/workflows"
PUBLISH_YML = WORKFLOWS / "publish.yml"
IMAGE = "ghcr.io/mmornati/ai-running-coach-dashboard"

VARIABLE = re.compile(r"\$\{([A-Z_][A-Z0-9_]*)")


def compose_text() -> str:
    return "\n".join(p.read_text(encoding="utf-8") for p in COMPOSE_FILES)


class TestDockerfile(unittest.TestCase):
    def setUp(self):
        self.text = DOCKERFILE.read_text(encoding="utf-8")

    def test_copied_sources_exist_and_pass_dockerignore(self):
        """Un COPY vers un dossier absent ou filtré casserait la construction."""
        allowed = [line[1:].strip().rstrip("/") for line in (REPO / ".dockerignore").read_text().splitlines()
                   if line.startswith("!")]
        for src in re.findall(r"^COPY\s+(\S+)\s+\S+", self.text, re.MULTILINE):
            name = src.rstrip("/")
            self.assertTrue((REPO / name).exists(), f"COPY {src} : introuvable")
            self.assertIn(name, allowed, f"COPY {src} : exclu par .dockerignore")

    def test_runs_as_non_root(self):
        users = re.findall(r"^USER\s+(\S+)", self.text, re.MULTILINE)
        self.assertTrue(users, "aucune instruction USER : le conteneur tournerait en root")
        self.assertNotIn(users[-1].split(":")[0], ("0", "root"))

    def test_engine_readable_by_container_user(self):
        """Des fichiers en 600 sur l'hôte (umask 077) ne doivent pas casser le démarrage."""
        chmod = re.search(r"^RUN\s+chmod\s+-R\s+a\+rX\s+/app\s*$", self.text, re.MULTILINE)
        self.assertTrue(chmod, "RUN chmod -R a+rX /app manquant")
        self.assertLess(self.text.rindex("\nCOPY "), chmod.start(), "le chmod doit suivre le dernier COPY")
        self.assertLess(chmod.start(), self.text.index("\nUSER "), "le chmod doit précéder USER (root requis)")

    def test_memory_index_on_mounted_workspace(self):
        """Le workspace est monté en lecture seule : l'index doit vivre en mémoire."""
        entry = re.search(r"^ENTRYPOINT\s+(.+)$", self.text, re.MULTILINE).group(1)
        for arg in ('"--memory"', '"--workspace", "/workspace"'):
            self.assertIn(arg, entry)

    def test_healthcheck_uses_healthz(self):
        self.assertRegex(self.text, r"HEALTHCHECK[\s\S]+/healthz")


class TestCompose(unittest.TestCase):
    def setUp(self):
        self.assertTrue(COMPOSE_FILES, "deploy/dashboard/compose*.yaml introuvables")
        self.text = compose_text()

    def test_no_published_port(self):
        """Le conteneur n'est joignable que par le reverse proxy, jamais en direct."""
        self.assertNotRegex(self.text, r"^\s+ports:", "un port publié contournerait l'authentification du proxy")

    def test_workspace_mounted_read_only(self):
        mounts = [line.strip().strip('-"').strip().rstrip('"') for line in self.text.splitlines()
                  if ":/workspace" in line and not line.lstrip().startswith("#")]
        self.assertTrue(mounts, "montage du workspace introuvable")
        for mount in mounts:
            self.assertTrue(mount.endswith(":ro"), f"montage en écriture : {mount}")
        self.assertIn("read_only: true", self.text)

    def test_auth_middleware_is_mandatory(self):
        """Pas de valeur par défaut : sans middleware déclaré, compose refuse de démarrer."""
        self.assertRegex(self.text, r"routers\.arc-dashboard\.middlewares=\$\{TRAEFIK_AUTH_MIDDLEWARE:\?")

    def test_public_name_is_the_only_allowed_host(self):
        """Le nom routé par Traefik est aussi celui que le serveur accepte (Host)."""
        self.assertIn("ARC_DASHBOARD_ALLOWED_HOSTS", self.text)
        self.assertRegex(self.text, r"ARC_DASHBOARD_ALLOWED_HOSTS:\s+\"?\$\{ARC_DASHBOARD_HOST:\?")
        self.assertIn("Host(`${ARC_DASHBOARD_HOST}`)", self.text)

    def test_env_example_documents_every_variable(self):
        example = (DEPLOY / ".env.example").read_text(encoding="utf-8")
        declared = set(re.findall(r"^([A-Z_][A-Z0-9_]*)=", example, re.MULTILINE))
        missing = sorted(set(VARIABLE.findall(self.text)) - declared)
        self.assertFalse(missing, f"variables absentes de .env.example : {missing}")

    def test_env_file_is_ignored(self):
        """Le .env réel (nom public, chemins) ne part jamais dans le dépôt public."""
        proc = subprocess.run(["git", "check-ignore", "-q", str(DEPLOY / ".env")], cwd=str(REPO))
        self.assertEqual(proc.returncode, 0, "deploy/dashboard/.env n'est pas ignoré par git")


def _step_run_block(text: str, step_name: str) -> str:
    """Le bloc `run: |` (désindenté) de l'étape `- name: <step_name>`."""
    match = re.search(rf"- name: {re.escape(step_name)}\n(?:.*\n)*?(?P<indent> +)run: \|\n", text)
    if not match:
        raise AssertionError(f"étape « {step_name} » sans bloc run: | dans publish.yml")
    body = []
    for line in text[match.end():].splitlines():
        if line.strip() and len(line) - len(line.lstrip()) <= len(match.group("indent")):
            break
        body.append(line)
    return textwrap.dedent("\n".join(body))


class TestPublishWorkflow(unittest.TestCase):
    """L'image publiée sur GHCR : jamais :latest depuis main, et chaque release a la sienne."""

    @classmethod
    def setUpClass(cls):
        cls.text = PUBLISH_YML.read_text(encoding="utf-8")
        cls.tags_script = _step_run_block(cls.text, "Calcul des étiquettes")
        cls.repo = tempfile.TemporaryDirectory()
        # Hors de la configuration de l'utilisateur (signature des tags, hooks…).
        env = dict(os.environ, GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1")
        git = ["git", "-C", cls.repo.name, "-c", "user.name=t", "-c", "user.email=t@t"]
        subprocess.run(git[:3] + ["init", "-q"], check=True, env=env)
        subprocess.run(git + ["commit", "-q", "--allow-empty", "-m", "init"], check=True, env=env)
        for tag in ("v1.3.0", "v1.4.0", "v1.5.0-rc.1"):
            subprocess.run(git + ["tag", tag], check=True, env=env)
        cls.sha = subprocess.run(git[:3] + ["rev-parse", "HEAD"], check=True, env=env,
                                 capture_output=True, text=True).stdout.strip()

    @classmethod
    def tearDownClass(cls):
        cls.repo.cleanup()

    def tags_for(self, *, input_tag="", ref_type="branch", ref_name="main"):
        """Exécute l'étape de calcul comme Actions : rend (code, étiquettes, sorties)."""
        with tempfile.NamedTemporaryFile("r", suffix=".out") as out:
            env = dict(os.environ, IMAGE=IMAGE, INPUT_TAG=input_tag, REF_TYPE=ref_type,
                       REF_NAME=ref_name, GITHUB_OUTPUT=out.name)
            proc = subprocess.run(["bash", "-c", self.tags_script], cwd=self.repo.name, env=env,
                                  capture_output=True, text=True)
            raw = out.read()
        outputs = dict(re.findall(r"^(revision|version)=(.*)$", raw, re.MULTILINE))
        tags = re.search(r"^tags<<EOF\n(.*?)^EOF$", raw, re.MULTILINE | re.DOTALL)
        tags = {t.split(":", 1)[1] for t in tags.group(1).split()} if tags else set()
        return proc.returncode, tags, outputs

    def test_main_is_edge_never_latest(self):
        code, tags, out = self.tags_for()
        self.assertEqual(code, 0)
        self.assertEqual(tags, {"edge", f"sha-{self.sha[:7]}"})
        self.assertEqual(out["revision"], self.sha)

    def test_highest_release_moves_latest(self):
        for kwargs in ({"input_tag": "v1.4.0"}, {"ref_type": "tag", "ref_name": "v1.4.0"}):
            with self.subTest(**kwargs):
                code, tags, out = self.tags_for(**kwargs)
                self.assertEqual(code, 0)
                self.assertEqual(tags, {"1.4.0", "1.4", "latest", f"sha-{self.sha[:7]}"})
                self.assertEqual(out["version"], "1.4.0")

    def test_older_release_keeps_latest(self):
        code, tags, _ = self.tags_for(input_tag="v1.3.0")
        self.assertEqual(code, 0)
        self.assertEqual(tags, {"1.3.0", "1.3", f"sha-{self.sha[:7]}"})

    def test_prerelease_is_never_latest(self):
        code, tags, _ = self.tags_for(input_tag="v1.5.0-rc.1")
        self.assertEqual(code, 0)
        self.assertEqual(tags, {"1.5.0-rc.1", f"sha-{self.sha[:7]}"})

    def test_manual_branch_build_gets_a_valid_docker_tag(self):
        code, tags, _ = self.tags_for(ref_name="claude/Feature_x+y")
        self.assertEqual(code, 0)
        self.assertEqual(tags, {"branch-claude-feature_x-y", f"sha-{self.sha[:7]}"})

    def test_invalid_release_tag_fails(self):
        code, tags, _ = self.tags_for(input_tag="v1.4")
        self.assertNotEqual(code, 0)
        self.assertFalse(tags)

    def test_image_name_matches_dockerfile_title(self):
        self.assertIn(f"IMAGE: {IMAGE}", self.text)
        dockerfile = DOCKERFILE.read_text(encoding="utf-8")
        self.assertIn(f'org.opencontainers.image.title="{IMAGE.rsplit("/", 1)[1]}"', dockerfile)

    def test_revision_label_is_the_built_commit(self):
        """Lue par scripts/update-docker.sh --check : le commit construit, pas github.sha
        (sous workflow_run ou appelée depuis tag.yml, ce n'est pas forcément lui)."""
        self.assertIn("org.opencontainers.image.revision=${{ steps.meta.outputs.revision }}", self.text)
        self.assertIn("ARC_REVISION=${{ steps.meta.outputs.revision }}", self.text)
        self.assertIsNone(re.search(r"\$\{\{\s*github\.sha", self.text),
                          "publish.yml : github.sha n'est pas le commit construit")

    def test_tag_workflow_calls_publish_with_packages_write(self):
        """Un tag poussé par le GITHUB_TOKEN ne déclenche pas `push: tags` : sans cet appel,
        aucune release n'aurait d'image."""
        tag_yml = (WORKFLOWS / "tag.yml").read_text(encoding="utf-8")
        job = re.search(r"^  docker:\n((?:    .*\n|\n)+)", tag_yml, re.MULTILINE)
        self.assertTrue(job, "tag.yml : job `docker` introuvable")
        self.assertIn("uses: ./.github/workflows/publish.yml", job.group(1))
        self.assertIn("packages: write", job.group(1))
        self.assertIn("tag: ${{ needs.tag.outputs.tag }}", job.group(1))


if __name__ == "__main__":
    unittest.main()
