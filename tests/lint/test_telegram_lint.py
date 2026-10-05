"""Palier B — bot Telegram (#174) : cohérence docs / configuration / scripts.

Verrouille, sans rien exécuter : la page de doc et sa navigation, les clés `[telegram]` documentées,
le branchement du résumé dans `daily-sync.sh`, et les garde-fous de sécurité lisibles dans le code
(jamais de jeton en option de ligne de commande, jamais d'appel Garmin depuis ce canal).
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent


def read(rel: str) -> str:
    return (REPO / rel).read_text(encoding="utf-8")


class TestTelegramDocs(unittest.TestCase):
    def test_page_is_in_the_nav_and_linked(self):
        self.assertIn("telegram.md", read("mkdocs.yml"))
        self.assertIn("telegram.md", read("docs/mobile.md"))
        self.assertIn("docs/telegram.md", read("README.md"))
        self.assertIn("docs/telegram.md", read("AGENTS.md"))
        self.assertIn("telegram.md", read("docs/configuration.md"))

    def test_config_keys_are_documented_everywhere(self):
        toml = read("config/workspace.toml")
        section = toml.split("[telegram]", 1)[1].split("\n[", 1)[0]
        keys = re.findall(r"^([a-z_]+) = ", section, re.M)
        self.assertEqual(set(keys), {"enabled", "token_file", "allowed_chat_ids", "send_summary", "chat_bridge", "poll_timeout_s"})
        config_doc = read("docs/configuration.md").split("## Le bot Telegram", 1)[1].split("\n## ", 1)[0]
        for key in keys:
            self.assertIn(f"`{key}`", config_doc, f"[telegram].{key} non documenté dans docs/configuration.md")

    def test_defaults_are_safe_and_opt_in(self):
        toml = read("config/workspace.toml").split("[telegram]", 1)[1].split("\n[", 1)[0]
        self.assertRegex(toml, r"(?m)^enabled = false$")
        self.assertRegex(toml, r"(?m)^chat_bridge = false$")
        self.assertRegex(toml, r"(?m)^allowed_chat_ids = \[\]$")
        self.assertNotRegex(toml, r"\d{6,}:[A-Za-z0-9_-]{20,}", "aucun jeton dans la config versionnée")

    def test_page_covers_the_required_topics(self):
        text = read("docs/telegram.md")
        for needle in ("BotFather", "allowed_chat_ids", "whoami", "sans clé d'API", "chat_bridge", "Confidentialité",
                       "discussions secrètes", "Coûts", "core.telegram.org/bots/api", "idempotent"):
            self.assertIn(needle, text, f"docs/telegram.md : « {needle} » manquant")

    def test_mobile_page_keeps_the_subscription_rule_and_explains_the_exception(self):
        text = read("docs/mobile.md")
        self.assertIn("ne peut\n    pas** utiliser votre abonnement", text)
        self.assertIn("n'appelle aucun modèle", text)

    def test_doctor_check_is_registered(self):
        doctor = read("scripts/coach_doctor.py")
        self.assertIn('"strava_connection", "telegram",', doctor)
        self.assertIn("check_telegram", doctor)


class TestTelegramScripts(unittest.TestCase):
    def test_daily_sync_sends_the_summary_after_ntfy_and_never_blocks(self):
        sync = read("scripts/daily-sync.sh")
        self.assertIn('telegram_summary "$title" "$priority" "$resume"', sync)
        self.assertLess(sync.index('notify "$title" "$priority" "$tags" "$resume"\n    telegram_summary'),
                        sync.index("main \"$@\""))
        body = sync.split("telegram_summary() {", 1)[1].split("\n}\n", 1)[0]
        self.assertIn("|| warn", body, "un échec Telegram ne doit jamais faire échouer la synchronisation")
        self.assertIn("send_summary", body)

    def test_install_never_takes_the_token_as_an_option(self):
        install = read("install.sh")
        self.assertNotRegex(install, r"--telegram-token|--bot-token|--token\)")
        self.assertIn("telegram.env", install)
        self.assertIn("umask 077", install.split("ensure_telegram_env()", 1)[1].split("\n}\n", 1)[0])

    def test_service_script_passes_no_secret_to_the_unit(self):
        script = read("scripts/coach-telegram.sh")
        self.assertNotIn("EnvironmentFile", script.replace("# Aucun EnvironmentFile", ""))
        self.assertNotIn("TELEGRAM_BOT_TOKEN", script)

    def test_bot_never_calls_garmin_nor_prints_the_token(self):
        code = read("scripts/arc_telegram.py")
        body = re.sub(r'""".*?"""', "", code, flags=re.S)
        for forbidden in ("schedule_workout", "upload_workout", "garminconnect", "mcp__garmin", "add_gear_to_activity"):
            self.assertNotIn(forbidden, body, f"arc_telegram.py ne doit jamais toucher Garmin ({forbidden})")
        self.assertNotRegex(code, r"print\(\s*f?[\"'][^\"']*\{?token", "le jeton ne doit jamais être imprimé")
        self.assertIn("redact(", code)
        self.assertIn("os.chmod(tmp, 0o600)", code)

    def test_callback_data_and_message_limits_are_enforced(self):
        code = read("scripts/arc_telegram.py")
        self.assertIn("MAX_CALLBACK_BYTES = 64", code)
        self.assertIn("MAX_MESSAGE_CHARS = 4096", code)


if __name__ == "__main__":
    unittest.main()
