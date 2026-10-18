"""Palier A — `arc_llm.py sync` : changer l'IA de la synchronisation seule, et la notification
« limite de l'abonnement Claude atteinte » de daily-sync.sh.

Verrouille :
  - seules les clés [sync] runner/model/base_url/api_key_env/opencode_data_dir changent, dans
    workspace.user.toml ; [chat], mode et commentaires de l'athlète restent intacts ;
  - refus (code 3, rien d'écrit) quand la clé visée manque dans llm.env ;
  - --dry-run n'écrit rien ; idempotence ; retour à l'abonnement ;
  - aucune valeur de clé en sortie (texte et JSON) ;
  - daily-sync.sh lance `claude -p … --output-format json --model …` et passe la clé au runner ;
  - un abonnement Claude à sa limite donne une notification dédiée, une fois par jour.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests.install.test_daily_sync_resume_cap import ResumeCapSandbox
from tests.lib.sandbox import Sandbox

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "arc_llm.py"
SECRET = "sk-ant-SYNC-SECRET-VALUE-0123456789"


class SyncSwitchCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="arc-llm-sync-"))
        self.ws = self.tmp / "ws"
        (self.ws / "config").mkdir(parents=True)
        (self.ws / "config/workspace.toml").write_text((REPO / "config/workspace.toml").read_text())
        self.user = self.ws / "config/workspace.user.toml"
        self.user.write_text('# mes réglages\n[sync]\nmode = "watch"  # garder\n\n'
                             '[chat]\nbackend = "opencode"\nmodel = "anthropic/claude-haiku-5-5"\n')
        self.env_file = self.tmp / "llm.env"
        self.env_file.write_text("# clés\n")
        self.env_file.chmod(0o600)

    def tearDown(self) -> None:
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_sync(self, *args: str):
        env = {k: v for k, v in os.environ.items() if k not in ("ANTHROPIC_API_KEY", "OPENROUTER_API_KEY",
                                                                  "OPENAI_API_KEY")}
        env.update(HOME=str(self.tmp), ARC_WORKSPACE=str(self.ws), ARC_LLM_ENV=str(self.env_file))
        return subprocess.run([sys.executable, str(SCRIPT), "sync", *args], capture_output=True, text=True,
                              env=env, timeout=30)

    def add_key(self, name: str = "ANTHROPIC_API_KEY") -> None:
        with self.env_file.open("a") as fh:
            fh.write("%s=%s\n" % (name, SECRET))

    def sync_section(self) -> dict:
        import tomllib
        return tomllib.loads(self.user.read_text()).get("sync", {})

    def test_status_without_argument(self):
        r = self.run_sync()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("abonnement Claude", r.stdout)

    def test_refuses_without_key_and_writes_nothing(self):
        before = self.user.read_text()
        r = self.run_sync("anthropic")
        self.assertEqual(r.returncode, 3, r.stdout + r.stderr)
        self.assertIn("ANTHROPIC_API_KEY", r.stdout)
        self.assertEqual(self.user.read_text(), before)

    def test_anthropic_switch_touches_only_sync(self):
        self.add_key()
        r = self.run_sync("anthropic")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        sync = self.sync_section()
        self.assertEqual(sync["api_key_env"], "ANTHROPIC_API_KEY")
        self.assertEqual(sync["model"], "claude-haiku-4-5")
        self.assertEqual(sync["mode"], "watch")
        text = self.user.read_text()
        self.assertIn("# mes réglages", text)
        self.assertIn('model = "anthropic/claude-haiku-5-5"', text)  # [chat] intact
        self.assertIn("abonnement → clé API", r.stdout)
        self.assertIn("sync claude-subscription", r.stdout)
        self.assertNotIn(SECRET, r.stdout + r.stderr)
        # Idempotent
        again = self.run_sync("anthropic", "--json")
        data = json.loads(again.stdout)
        self.assertEqual(data["changes"], [])
        self.assertNotIn(SECRET, again.stdout)

    def test_dry_run_writes_nothing(self):
        self.add_key()
        before = self.user.read_text()
        r = self.run_sync("anthropic", "--model", "claude-haiku-5-5", "--dry-run", "--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        data = json.loads(r.stdout)
        self.assertTrue(data["dry_run"])
        self.assertIn({"key": "model", "old": "", "new": "claude-haiku-5-5"}, data["changes"])
        self.assertEqual(self.user.read_text(), before)

    def test_back_to_subscription(self):
        self.add_key()
        self.run_sync("anthropic")
        r = self.run_sync("claude-subscription")
        self.assertEqual(r.returncode, 0, r.stderr)
        sync = self.sync_section()
        self.assertEqual(sync["api_key_env"], "")
        self.assertEqual(sync["model"], "")
        self.assertIn("sync anthropic --model claude-haiku-4-5", r.stdout)

    def test_openrouter_and_usage_errors(self):
        self.add_key("OPENROUTER_API_KEY")
        r = self.run_sync("openrouter", "--model", "mistralai/mistral-small")
        self.assertEqual(r.returncode, 0, r.stderr)
        sync = self.sync_section()
        self.assertEqual((sync["runner"], sync["model"]), ("opencode", "openrouter/mistralai/mistral-small"))
        self.assertEqual(self.run_sync("openai").returncode, 2)
        self.assertEqual(self.run_sync("anthropic", "--model", "anthropic/claude-haiku-4-5").returncode, 2)
        self.assertEqual(self.run_sync("openrouter-free", "--model", "deepseek/x").returncode, 2)

    def test_daily_sync_dry_run_uses_api_key(self):
        self.add_key()
        self.run_sync("anthropic")
        env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}
        env.update(HOME=str(self.tmp), ARC_WORKSPACE=str(self.ws), ARC_LLM_ENV=str(self.env_file))
        r = subprocess.run(["bash", str(REPO / "scripts/daily-sync.sh"), "--dry-run"], capture_output=True,
                           text=True, env=env, timeout=60)
        out = r.stdout + r.stderr
        self.assertIn("claude -p", out)
        self.assertIn("--output-format json --model claude-haiku-4-5", out)
        self.assertIn("variable réservée au process du runner : ANTHROPIC_API_KEY", out)
        self.assertNotIn(SECRET, out)


class TestClaudePlanLimitNotification(ResumeCapSandbox):
    LIMIT = "You've hit your weekly limit · resets 3pm (Europe/Paris)"

    def test_dedicated_notification_once_per_day(self):
        with Sandbox() as sb:
            self._configure_notifications(sb)
            self._run(sb, self.LIMIT, exit_code=1)
            message = self._notified_message(sb)
            self.assertIn("hit your weekly limit", message)
            self.assertIn("arc_llm.py sync anthropic", message)
            self.assertNotIn("échouée", message)
            sb.stub_log.write_text("")
            self._run(sb, self.LIMIT, exit_code=1)
            self.assertNotIn("curl\t", sb.stub_log.read_text())


if __name__ == "__main__":
    unittest.main()
