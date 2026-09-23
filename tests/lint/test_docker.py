"""Palier B — le conteneur du tableau de bord ne s'expose jamais sans protection.

Le tableau de bord montre des données de santé et n'a pas d'authentification
propre. Ces contrôles statiques (sans Docker) verrouillent les invariants du
déploiement : aucun port publié, workspace en lecture seule, middleware
d'authentification obligatoire, utilisateur non root, image réduite au moteur.
"""

from __future__ import annotations

import re
import subprocess
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
DOCKERFILE = REPO / "Dockerfile"
DEPLOY = REPO / "deploy/dashboard"
COMPOSE_FILES = sorted(DEPLOY.glob("compose*.yaml"))

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


if __name__ == "__main__":
    unittest.main()
