"""Suivis de #127 pour `coach_doctor` : faux positifs `chat_service` (conteneur) et `garmin_mcp` (PATH ssh)."""
from __future__ import annotations

import importlib.util
import os
import stat
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("coach_doctor_followups", ROOT / "scripts/coach_doctor.py")
doctor = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = doctor
spec.loader.exec_module(doctor)

# Port inutilisé : la sonde locale échoue immédiatement.
DEAD = {"enabled": True, "port": 1}


class TestChatServiceContainer(unittest.TestCase):
    def _check(self, chat, compose_file=None):
        with tempfile.TemporaryDirectory() as home, tempfile.TemporaryDirectory() as engine:
            if compose_file is not None:
                env = Path(engine) / "deploy/dashboard/.env"
                env.parent.mkdir(parents=True)
                env.write_text(f"COMPOSE_FILE={compose_file}\n")
            return doctor.check_chat_service(Path(home), {"chat": chat}, engine_root=Path(engine))

    def test_container_detected_is_info(self):
        # Défaut : « Chat activé mais aucun service installé et 127.0.0.1:8766 injoignable » sous Docker/Coolify.
        check = self._check({**DEAD, "auth": "proxy"}, "compose.yaml:compose.chat.yaml")
        self.assertEqual(check["status"], "info", check)
        self.assertIn("conteneur", check["message"])

    def test_proxy_without_container_evidence_keeps_message_and_fix(self):
        # Défaut : un chat hôte (systemd) derrière Traefik dont l'unité manque était masqué en info, fix=None.
        check = self._check({**DEAD, "auth": "proxy"})
        self.assertIn(check["status"], ("warning", "info"), check)
        self.assertIn("compose.chat.yaml", check["message"])
        self.assertEqual(check["fix"], "./install.sh --chat")

    def test_local_auth_with_public_url_and_no_service_still_warns(self):
        # Défaut : public_url (boutons ntfy) était pris pour un déploiement en conteneur.
        check = self._check({**DEAD, "auth": "local", "public_url": "https://coach.example.invalid"})
        self.assertEqual(check["status"], "warning", check)

    def test_compose_file_without_chat_overlay_is_not_a_container(self):
        check = self._check({**DEAD, "auth": "local"}, "compose.yaml:compose.authentik.yaml")
        self.assertEqual(check["status"], "warning", check)


class TestMcpCommandSearchesDailySyncDirs(unittest.TestCase):
    def test_command_in_local_bin_found_with_bare_path(self):
        # Défaut : `ssh hôte` non interactif -> PATH sans ~/.local/bin -> « introuvable » alors que daily-sync le trouve.
        with tempfile.TemporaryDirectory() as home, tempfile.TemporaryDirectory() as ws:
            binary = Path(home) / ".local/bin/garmin-mcp"
            binary.parent.mkdir(parents=True)
            binary.write_text("#!/bin/sh\nexit 0\n")
            binary.chmod(binary.stat().st_mode | stat.S_IXUSR)
            with unittest.mock.patch.dict(os.environ, {"PATH": "/usr/bin:/bin", "HOME": home}), \
                    unittest.mock.patch.object(Path, "home", return_value=Path(home)):
                check = doctor.check_garmin_mcp_presence(Path(ws))
            self.assertEqual(check["status"], "ok", check)

    def test_empty_path_entry_does_not_resolve_from_cwd(self):
        # Défaut : une entrée vide du PATH = dossier courant pour shutil.which.
        with tempfile.TemporaryDirectory() as cwd:
            binary = Path(cwd) / "garmin-mcp-cwd-probe"
            binary.write_text("#!/bin/sh\nexit 0\n")
            binary.chmod(binary.stat().st_mode | stat.S_IXUSR)
            old = os.getcwd()
            os.chdir(cwd)
            try:
                with unittest.mock.patch.dict(os.environ, {"PATH": ""}):
                    self.assertIsNone(doctor._which_with_extra("garmin-mcp-cwd-probe"))
            finally:
                os.chdir(old)


if __name__ == "__main__":
    unittest.main()
