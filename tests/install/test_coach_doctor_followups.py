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
    def _check(self, chat):
        with tempfile.TemporaryDirectory() as home:
            return doctor.check_chat_service(Path(home), {"chat": chat})

    def test_proxy_auth_in_container_is_info_not_warning(self):
        # Défaut : « Chat activé mais aucun service installé et 127.0.0.1:8766 injoignable » sous Docker/Coolify.
        check = self._check({**DEAD, "auth": "proxy"})
        self.assertEqual(check["status"], "info", check)
        self.assertIn("conteneur", check["message"])

    def test_public_url_in_container_is_info(self):
        check = self._check({**DEAD, "public_url": "https://coach.example.invalid"})
        self.assertEqual(check["status"], "info", check)

    def test_local_install_without_service_still_warns(self):
        check = self._check({**DEAD, "auth": "local"})
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


if __name__ == "__main__":
    unittest.main()
