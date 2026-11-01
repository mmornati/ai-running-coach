"""Palier B — conversation Telegram sur abonnement (Claude Code Channels, #337).

Verrouille, sans rien exécuter de réseau :
- les permissions de `templates/settings.telegram.json` restent alignées sur `config/chat-policy.toml`
  (arc_chat_policy.Policy) et sur les refus de `scripts/lib/sync_tools.sh` : aucun outil refusé ou soumis à
  approbation par la politique n'est autorisé d'office, aucune écriture Garmin / COROS / Strava /
  intervals.icu n'est dans `allow` ;
- le script refuse deux fois le même bot, n'écrit jamais un jeton, marque le mode expérimental ;
- la documentation, la configuration et le doctor suivent.
"""

from __future__ import annotations

import fnmatch
import json
import re
import subprocess
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO / "scripts"))

from arc_chat_policy import Policy  # noqa: E402

TEMPLATE = REPO / "templates/settings.telegram.json"
SCRIPT = REPO / "scripts/coach-telegram-chat.sh"
SERVERS = ("garmin", "intervals", "strava", "coros")
# Outils du plugin Telegram lui-même (reply, react, edit_message, download_attachment…).
PLUGIN_RULE = "mcp__plugin_telegram_telegram"


def read(rel: str) -> str:
    return (REPO / rel).read_text(encoding="utf-8")


def template() -> dict:
    return json.loads(TEMPLATE.read_text(encoding="utf-8"))["permissions"]


def policy() -> Policy:
    return Policy.load(REPO, REPO)


def sync_write_tools(source: str) -> list:
    out = subprocess.run(["bash", "-c", f"source scripts/lib/sync_tools.sh; sync_write_tools {source}"],
                         cwd=REPO, capture_output=True, text=True, check=True).stdout
    return out.split()


def mcp_rule(rule: str):
    """`mcp__garmin__get_sleep_data` -> ("garmin", "get_sleep_data") ; sinon None."""
    match = re.fullmatch(r"mcp__([A-Za-z0-9_.-]+?)__(.+)", rule)
    return (match.group(1), match.group(2)) if match else None


class TestPermissionsFollowThePolicy(unittest.TestCase):
    def test_template_is_valid_and_has_the_three_lists(self):
        perms = template()
        for kind in ("allow", "ask", "deny"):
            self.assertIsInstance(perms.get(kind), list, kind)
            self.assertEqual(len(perms[kind]), len(set(perms[kind])), f"doublons dans {kind}")

    def test_no_rule_is_both_allowed_and_restricted(self):
        perms = template()
        self.assertFalse(set(perms["allow"]) & set(perms["ask"]))
        self.assertFalse(set(perms["allow"]) & set(perms["deny"]))
        self.assertFalse(set(perms["ask"]) & set(perms["deny"]))

    def test_allowed_mcp_tools_are_reads_for_the_policy(self):
        """Tout outil MCP de `allow` est autorisé d'office par la politique du chat (jamais `ask`/`deny`)."""
        pol = policy()
        for rule in template()["allow"]:
            parsed = mcp_rule(rule)
            if parsed is None or rule == PLUGIN_RULE:
                continue
            server, tool = parsed
            self.assertIn(server, SERVERS, f"{rule} : serveur inconnu de la politique")
            self.assertEqual(pol.decide(f"mcp:{server}.{tool}", {}), "allow",
                             f"{rule} figure dans allow alors que la politique ne l'autorise pas d'office")

    def test_no_tool_asked_or_denied_by_the_policy_is_allowed(self):
        """Test central de l'exigence : l'inverse du précédent, sur les outils d'écriture connus."""
        allowed = {mcp_rule(r) for r in template()["allow"] if mcp_rule(r) and r != PLUGIN_RULE}
        for server in SERVERS:
            for tool in self._known_write_tools(server):
                # Même un outil que la politique laisse passer en lecture (garmin.download_activity_file :
                # préfixe `download_`) reste hors de `allow` s'il figure dans les refus de sync_tools.sh.
                self.assertNotIn((server, tool), allowed, f"{server}.{tool} est autorisé d'office")

    def test_every_remote_write_is_ask_or_deny(self):
        """Aucune écriture Garmin / COROS / Strava / intervals.icu de sync_tools.sh n'échappe à ask/deny."""
        perms = template()
        restricted = set(perms["ask"]) | set(perms["deny"])
        for server in SERVERS:
            for tool in self._known_write_tools(server):
                self.assertIn(f"mcp__{server}__{tool}", restricted, f"{server}.{tool} n'est ni en ask ni en deny")

    def test_deletions_and_unscheduling_are_denied(self):
        perms = template()
        for server in SERVERS:
            for tool in self._known_write_tools(server):
                if "delete" in tool or "unschedule" in tool:
                    self.assertIn(f"mcp__{server}__{tool}", perms["deny"], f"{server}.{tool} doit être interdit")

    def test_policy_write_patterns_match_nothing_allowed(self):
        """Les motifs `write_tools` de chat-policy.toml (add_*, icu_update_*…) ne couvrent aucun outil de `allow`."""
        pol = policy()
        for rule in template()["allow"]:
            parsed = mcp_rule(rule)
            if parsed is None or rule == PLUGIN_RULE:
                continue
            for pattern in pol.mcp_write_tools:
                self.assertFalse(fnmatch.fnmatch(parsed[1], pattern), f"{rule} correspond à l'écriture « {pattern} »")

    def test_file_writes_stay_under_the_policy_data_dirs(self):
        pol = policy()
        scoped = set()
        for rule in template()["allow"]:
            match = re.fullmatch(r"(Write|Edit)\((.+)\)", rule)
            if rule in ("Write", "Edit"):
                self.fail(f"{rule} sans périmètre : la politique limite l'écriture à {pol.write_dirs}")
            if match:
                directory = match.group(2)
                self.assertTrue(directory.endswith("/**"), rule)
                self.assertIn(directory[:-3], pol.write_dirs, f"{rule} hors de [fs].write_dirs")
                scoped.add((match.group(1), directory[:-3]))
        for directory in pol.write_dirs:
            self.assertIn(("Write", directory), scoped)
            self.assertIn(("Edit", directory), scoped)

    def test_shell_rules_stay_within_the_policy_prefixes(self):
        pol = policy()
        for rule in template()["allow"]:
            match = re.fullmatch(r"Bash\((.+):\*\)", rule)
            if rule.startswith("Bash"):
                self.assertIsNotNone(match, f"{rule} : seul le préfixe `Bash(préfixe:*)` est admis")
                self.assertIn(match.group(1), pol.shell_prefixes, f"{rule} hors de [shell].allowed_prefixes")

    def test_scripts_with_ask_flags_cannot_run_those_flags_unprompted(self):
        """`--write`, `--mark-retired`, `--apply`… (ask_flags de chat-policy.toml) : approbation, jamais `allow`."""
        perms = template()
        shell = policy().shell_scripts
        flagged = {script: rules.get("ask_flags") for script, rules in shell.items() if rules.get("ask_flags")}
        self.assertTrue(flagged)
        for script, flags in flagged.items():
            for flag in flags:
                self.assertIn(f"Bash(python3 {script} *{flag}*)", perms["ask"], f"{script} {flag} : aucune règle `ask`")

    def test_web_fetch_domains_are_listed_by_the_policy(self):
        domains = policy().fetch_domains
        for rule in template()["allow"]:
            match = re.fullmatch(r"WebFetch\(domain:(.+)\)", rule)
            if match:
                self.assertIn(match.group(1), domains, f"{rule} hors de [web].fetch_domains")
            self.assertFalse(rule.startswith(("WebSearch", "WebFetch")) and not match, f"{rule} trop large")

    def test_secret_files_are_denied_for_reading(self):
        deny = " ".join(template()["deny"])
        for pattern in (".env", "*.env", "*.token", ".garminconnect", "llm.env", "*.pem", "*.key"):
            self.assertIn(pattern, deny, f"secret « {pattern} » (chat-policy.toml) non protégé en lecture")
        self.assertIn("Read(~/.claude/channels/telegram/inbox/**)", template()["allow"])

    def test_permission_mode_default_is_not_accept_edits(self):
        toml = read("config/workspace.toml").split("[telegram_chat]", 1)[1].split("\n[", 1)[0]
        self.assertRegex(toml, r'(?m)^permission_mode = "default"$')

    @staticmethod
    def _known_write_tools(server: str) -> list:
        tools = sync_write_tools(server)
        if server == "intervals":
            tools = [t for t in tools if t.startswith("icu_")]
        return sorted(set(tools))


class TestDistinctBotAndSecrecy(unittest.TestCase):
    def test_script_compares_tokens_and_never_prints_them(self):
        text = SCRIPT.read_text(encoding="utf-8")
        self.assertIn("require_distinct_bot", text)
        self.assertIn("409", text)
        self.assertIn("BotFather", text)
        for line in text.splitlines():
            if line.lstrip().startswith("#"):
                continue
            if "printf '%s' \"" in line:
                continue            # renvoi de valeur capturé par $(…), jamais affiché tel quel
            if re.search(r"\b(echo|printf|log|warn|die|err|ok)\b", line):
                self.assertNotRegex(line, r"\$\{?(chat_token|bot_token|TELEGRAM_BOT_TOKEN)\b",
                                    f"jeton affiché : {line.strip()}")

    def test_script_has_its_own_names(self):
        text = SCRIPT.read_text(encoding="utf-8")
        for needle in ('SERVICE_NAME="ai-running-coach-telegram-chat"', 'LAUNCHD_LABEL="com.ai-running-coach.telegram-chat"',
                       'TMUX_SESSION="coach-telegram-chat"', "telegram-chat.log", "tmux -L", "--dry-run"):
            self.assertIn(needle, text)

    def test_script_marks_the_mode_as_experimental(self):
        self.assertIn("EXPÉRIMENTAL", SCRIPT.read_text(encoding="utf-8"))
        self.assertIn("expérimental", read("docs/telegram.md").lower())
        self.assertIn("research preview", read("docs/telegram.md"))


class TestDocsConfigAndDoctor(unittest.TestCase):
    def test_telegram_page_has_the_level_3_section(self):
        text = read("docs/telegram.md")
        self.assertIn("## Niveau 3 — conversation sur abonnement (Claude Code Channels, expérimental)", text)
        for needle in ("chat_bridge", "abonnement", "second bot", "409", "/telegram:access policy allowlist",
                       "Confidentialité", "coach-telegram-chat.sh install", "templates/settings.telegram.json"):
            self.assertIn(needle, text, f"docs/telegram.md : « {needle} » manquant")

    def test_subscription_sentence_stays_true(self):
        text = read("docs/telegram.md")
        self.assertNotIn("un bot ne peut pas utiliser un abonnement", text.replace("\n", " "))
        self.assertIn("`arc_telegram` (niveaux 1 et 2) ne peut pas utiliser un", text.replace("\n", " "))

    def test_skill_page_and_navigation(self):
        self.assertTrue((REPO / "skills/telegram-chat/SKILL.md").is_file())
        self.assertTrue((REPO / "docs/skills/telegram-chat.md").is_file())
        self.assertIn("skills/telegram-chat.md", read("mkdocs.yml"))
        self.assertIn("skills/telegram-chat.md", read("docs/skills.md"))
        self.assertIn("`telegram-chat`", read("skills/skills-reference/SKILL.md"))
        self.assertIn("`telegram-chat`", read("AGENTS.md"))

    def test_config_keys_are_documented(self):
        toml = read("config/workspace.toml")
        section = toml.split("[telegram_chat]", 1)[1].split("\n[", 1)[0]
        keys = re.findall(r"^([a-z_]+) = ", section, re.M)
        self.assertEqual(set(keys), {"permission_mode", "daily_restart"})
        doc = read("docs/configuration.md").split("## La conversation Telegram sur abonnement", 1)[1].split("\n## ", 1)[0]
        for key in keys:
            self.assertIn(f"`{key}`", doc)

    def test_doctor_check_is_registered_and_documented(self):
        doctor = read("scripts/coach_doctor.py")
        self.assertIn('"telegram", "telegram_chat",', doctor)
        self.assertIn("def check_telegram_chat", doctor)
        self.assertIn('check_id == "telegram_chat"', doctor)
        self.assertIn("`telegram_chat`", read("skills/coach-doctor/SKILL.md"))
        self.assertIn("`telegram_chat`", read("docs/skills/coach-doctor.md"))


if __name__ == "__main__":
    unittest.main()
