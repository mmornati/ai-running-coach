"""Palier A — tableau de bord en conteneur géré par install.sh (`--dashboard-docker`).

Verrouille : sans Docker (ou sans option ni configuration hors terminal), rien n'est fait ni écrit ;
`local` publie la boucle locale seulement ; `traefik` détecte réseau et point d'entrée, exige une
authentification quand Traefik est joignable du réseau, s'en passe quand il n'écoute que sur
127.0.0.1 ; install.sh lance le conteneur mais ne reconstruit JAMAIS l'image (c'est /update-coach,
tests/install/test_update_coach.py) ; la configuration [dashboard] est relue à la relance ; la
question n'est posée qu'en terminal, et sa réponse est mémorisée.
"""

from __future__ import annotations

from tests.lib.asserts import InstallAsserts
from tests.lib.sandbox import Sandbox

DOCKER = {"ARC_FAKE_UNAME": "Darwin", "ARC_FAKE_DOCKER": "1"}


def _user_toml(sb) -> str:
    path = sb.repo / "config/workspace.user.toml"
    return path.read_text() if path.exists() else ""


def _compose(sb) -> str:
    path = sb.home / ".config/ai-running-coach/dashboard/compose.yaml"
    return path.read_text() if path.exists() else ""


def _compose_calls(sb) -> list:
    return [args for _, args in sb.stub_calls("docker") if args.startswith("compose -p arc-dashboard")]


class TestDashboardDocker(InstallAsserts):

    def test_default_install_never_touches_docker(self):
        with Sandbox() as sb:
            self.assertSucceeded(sb.install("--preset", "laptop", **DOCKER))
            self.assertEqual(_compose_calls(sb), [])
            self.assertEqual(_compose(sb), "")
            self.assertNotIn("[dashboard]", _user_toml(sb))

    def test_local_mode_publishes_loopback_only_and_never_rebuilds(self):
        with Sandbox() as sb:
            self.assertSucceeded(sb.install("--preset", "laptop", "--dashboard-docker", "local", **DOCKER))
            compose = _compose(sb)
            self.assertIn('"127.0.0.1:8765:8765"', compose)
            self.assertIn(f'context: "{sb.repo}"', compose)
            self.assertIn(":/workspace:ro", compose)
            self.assertNotIn("traefik", compose)
            calls = _compose_calls(sb)
            self.assertTrue(calls and all(c.endswith(" up -d") for c in calls), calls)
            self.assertIn('docker = "local"', _user_toml(sb))

    def test_rerun_reads_the_config_and_keeps_the_container_up_without_rebuilding(self):
        with Sandbox() as sb:
            self.assertSucceeded(sb.install("--preset", "laptop", "--dashboard-docker", "local", **DOCKER))
            first = len(_compose_calls(sb))
            self.assertSucceeded(sb.install("--preset", "laptop", "--no-auth", **DOCKER))
            calls = _compose_calls(sb)
            self.assertGreater(len(calls), first)
            self.assertFalse(any("build" in c for c in calls), calls)

    def test_unreachable_docker_is_a_warning_not_a_failure(self):
        with Sandbox() as sb:
            (sb.repo / "config/workspace.user.toml").write_text('[dashboard]\ndocker = "local"\n')
            proc = sb.install("--preset", "laptop", ARC_FAKE_UNAME="Darwin")
            self.assertSucceeded(proc)
            self.assertIn("Docker injoignable", proc.stdout)
            self.assertEqual(_compose_calls(sb), [])

    def test_traefik_on_loopback_needs_no_auth(self):
        with Sandbox() as sb:
            proc = sb.install("--preset", "laptop", "--dashboard-docker", "traefik",
                              ARC_FAKE_TRAEFIK="127.0.0.1:80", **DOCKER)
            self.assertSucceeded(proc)
            compose = _compose(sb)
            self.assertIn("Host(`coach.localhost`)", compose)
            self.assertIn("entrypoints=web", compose)
            self.assertIn('name: "proxy"', compose)
            self.assertNotIn("middlewares", compose)
            self.assertNotIn("ports:", compose)
            toml = _user_toml(sb)
            self.assertIn('docker = "traefik"', toml)
            self.assertIn('docker_host = "coach.localhost"', toml)

    def test_traefik_reachable_from_the_network_requires_auth(self):
        with Sandbox() as sb:
            proc = sb.install("--preset", "laptop", "--dashboard-docker", "traefik",
                              ARC_FAKE_TRAEFIK="0.0.0.0:80", **DOCKER)
            self.assertNotEqual(proc.returncode, 0)
            self.assertIn("--dashboard-auth", proc.stdout + proc.stderr)
            self.assertEqual(_compose_calls(sb), [])
            proc = sb.install("--preset", "laptop", "--dashboard-docker", "traefik",
                              "--dashboard-host", "coach.example.org", "--dashboard-auth", "authentik@file",
                              ARC_FAKE_TRAEFIK="0.0.0.0:80", **DOCKER)
            self.assertSucceeded(proc)
            self.assertIn("middlewares=authentik@file", _compose(sb))
            self.assertIn("Host(`coach.example.org`)", _compose(sb))

    def test_traefik_without_a_running_traefik_is_refused(self):
        with Sandbox() as sb:
            proc = sb.install("--preset", "laptop", "--dashboard-docker", "traefik", **DOCKER)
            self.assertNotEqual(proc.returncode, 0)
            self.assertIn("aucun conteneur Traefik", proc.stdout + proc.stderr)

    def test_back_to_off_stops_only_the_managed_container(self):
        with Sandbox() as sb:
            self.assertSucceeded(sb.install("--preset", "laptop", "--dashboard-docker", "local", **DOCKER))
            self.assertSucceeded(sb.install("--preset", "laptop", "--dashboard-docker", "off", **DOCKER))
            self.assertIn('docker = "off"', _user_toml(sb))

    def test_invalid_values_are_refused(self):
        with Sandbox() as sb:
            self.assertNotEqual(sb.install("--dashboard-docker", "oui", **DOCKER).returncode, 0)
            self.assertNotEqual(sb.install("--dashboard-host", "coach.localhost", **DOCKER).returncode, 0)
            self.assertNotEqual(sb.install("--dashboard-docker", "local", "--dashboard-auth", "x", **DOCKER).returncode, 0)
            self.assertNotEqual(sb.install("--dashboard-docker", "traefik", "--dashboard-host", "http://x",
                                           ARC_FAKE_TRAEFIK="127.0.0.1:80", **DOCKER).returncode, 0)

    def test_terminal_question_is_asked_once_and_remembered(self):
        with Sandbox() as sb:
            # Oui au conteneur, oui à Traefik, adresse par défaut.
            proc = sb.run_pty([str(sb.repo / "install.sh"), "--preset", "laptop", "--no-auth"],
                              ["o", "o", ""], timeout=170, ARC_FAKE_TRAEFIK="127.0.0.1:80", **DOCKER)
            self.assertEqual(proc.returncode, 0, proc.stdout)
            self.assertIn("Docker détecté", proc.stdout)
            self.assertIn('docker = "traefik"', _user_toml(sb))
            self.assertIn("Host(`coach.localhost`)", _compose(sb))
            proc = sb.run_pty([str(sb.repo / "install.sh"), "--preset", "laptop", "--no-auth"],
                              [], timeout=170, ARC_FAKE_TRAEFIK="127.0.0.1:80", **DOCKER)
            self.assertEqual(proc.returncode, 0, proc.stdout)
            self.assertNotIn("Docker détecté", proc.stdout)

    def test_no_answer_is_remembered_too(self):
        with Sandbox() as sb:
            proc = sb.run_pty([str(sb.repo / "install.sh"), "--preset", "laptop", "--no-auth"],
                              ["n"], timeout=170, **DOCKER)
            self.assertEqual(proc.returncode, 0, proc.stdout)
            self.assertIn('docker = "off"', _user_toml(sb))
            self.assertEqual(_compose_calls(sb), [])
