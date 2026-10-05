"""Palier B — cohérence statique de la poussée des apports vers Garmin (#167).

Aucun modèle : (1) les outils nutrition ne sont jamais dans la liste blanche par défaut ni
étendus ailleurs que dans `resolve_nutrition_sync`, (2) les écritures sont interdites en headless,
(3) tout prompt qui parle de la poussée pose la garde `off` + « oui » explicite + interactif seul,
(4) le défaut de configuration est `off`, (5) les outils cités existent dans le code épinglé de
garmin-mcp (vérifiés à la main dans `src/garmin_mcp/nutrition.py`, `data_management.py`,
`health_wellness.py`, ici figés comme valeurs attendues), (6) la politique du chat demande
l'approbation pour chaque écriture.
"""

from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO / "scripts"))
from arc_chat_policy import Policy  # noqa: E402

READ_TOOLS = ("get_custom_foods", "get_custom_food_serving_units", "get_nutrition_daily_food_log",
              "get_nutrition_daily_meals", "get_hydration_data")
WRITE_TOOLS = ("create_custom_food", "log_custom_food", "log_food", "add_hydration_data")
NEVER = ("delete_food_log", "update_custom_food", "upsert_and_log")


def read(rel: str) -> str:
    return (REPO / rel).read_text(encoding="utf-8")


class TestDefaultsStayOff(unittest.TestCase):
    def test_default_whitelist_has_no_nutrition_tool(self):
        m = re.search(r'^GARMIN_TOOL_WHITELIST="([^"]+)"', read("install.sh"), re.M)
        for tool in READ_TOOLS + WRITE_TOOLS + NEVER:
            self.assertNotIn(tool, m.group(1).split(","))

    def test_constant_matches_the_verified_names_and_excludes_destructive_tools(self):
        m = re.search(r'^GARMIN_NUTRITION_TOOLS="([^"]+)"', read("install.sh"), re.M)
        self.assertEqual(set(m.group(1).split(",")), set(READ_TOOLS + WRITE_TOOLS))
        for tool in NEVER:
            self.assertNotIn(tool, m.group(1).split(","))

    def test_whitelist_extension_only_inside_resolve_nutrition_sync(self):
        install = read("install.sh")
        hits = [l for l in install.splitlines() if 'GARMIN_TOOL_WHITELIST="$GARMIN_TOOL_WHITELIST,$GARMIN_NUTRITION_TOOLS"' in l]
        self.assertEqual(len(hits), 1)
        body = install[install.index("resolve_nutrition_sync() {"):].split("persist_nutrition_sync")[0]
        self.assertIn('[[ "$NUTRITION_SYNC" == "ask" ]]', body)
        self.assertIn('[[ "$SOURCE" == "garmin" ]]', body)
        # La passerelle leanproxy est vérifiée AVANT l'extension (écritures non filtrables en headless).
        self.assertLess(body.index('"$USE_LEANPROXY" -eq 1'), body.index("$GARMIN_NUTRITION_TOOLS"))

    def test_shared_config_default_is_off(self):
        text = read("config/workspace.toml")
        self.assertRegex(text, r'(?m)^\[nutrition\]')
        self.assertRegex(text, r'(?m)^garmin_sync = "off"')

    def test_docs_whitelist_copies_still_match_install_default(self):
        install = re.search(r'^GARMIN_TOOL_WHITELIST="([^"]+)"', read("install.sh"), re.M).group(1)
        for copy in re.findall(r'GARMIN_ENABLED_TOOLS"?:\s*"([^"]+)"', read("docs/garmin-setup.md")):
            self.assertEqual(copy, install)


class TestHeadlessAndChatPolicy(unittest.TestCase):
    def test_daily_sync_script_disallows_every_nutrition_write(self):
        text = read("scripts/daily-sync.sh")
        for tool in WRITE_TOOLS + NEVER:
            self.assertIn(f"mcp__garmin__{tool}", text)
        self.assertIn("--disallowedTools", text)

    def test_daily_sync_skill_forbids_the_writes(self):
        text = read("skills/garmin-daily-sync/SKILL.md")
        self.assertRegex(text, r"NEVER call `add_gear_to_activity` here, nor any Garmin nutrition/hydration write")
        for tool in WRITE_TOOLS:
            self.assertIn(tool, text)

    def test_chat_policy_asks_for_every_write_and_allows_reads(self):
        policy = Policy.load(REPO, REPO)
        for tool in WRITE_TOOLS + NEVER:
            self.assertEqual(policy._mcp("mcp:garmin." + tool), "ask", tool)
        for tool in READ_TOOLS:
            self.assertEqual(policy._mcp("mcp:garmin." + tool), "allow", tool)

    def test_chat_policy_allows_the_planner_script_only_via_stdin_or_input(self):
        text = read("config/chat-policy.toml")
        self.assertIn('"python3 scripts/arc_nutrition_sync.py"', text)
        self.assertIn('[shell.scripts."scripts/arc_nutrition_sync.py"]', text)


class TestPromptsGate(unittest.TestCase):
    FILES = ("agents/nutritionist.md", "agents/coach.md", "skills/log/SKILL.md")

    def test_every_prompt_gates_on_off_asks_a_yes_and_is_interactive_only(self):
        for rel in self.FILES:
            text = read(rel)
            with self.subTest(file=rel):
                self.assertIn("garmin_sync", text)
                self.assertRegex(text, r"(?i)`off`")
                self.assertRegex(text, r'(?i)(explicit "oui"|« oui » explicite|clear "oui")')
                self.assertRegex(text, r"(?i)(headless|interactive only)")
                self.assertIn("arc_nutrition_sync.py", text)
                self.assertRegex(text, r"(?i)(intervals)")

    def test_nutritionist_states_the_single_source_rule_and_reverse_read(self):
        text = read("agents/nutritionist.md")
        self.assertRegex(text, r"(?i)single source of truth per day")
        self.assertIn("intake_source", text)
        self.assertIn("get_nutrition_daily_food_log", text)
        self.assertIn("garmin_pushed", text)

    def test_write_tools_cited_only_in_files_that_require_a_yes(self):
        files = list((REPO / "agents").glob("*.md")) + list((REPO / "skills").glob("*/SKILL.md")) + [REPO / "AGENTS.md"]
        for path in files:
            text = path.read_text(encoding="utf-8")
            if any(f"`{t}`" in text for t in WRITE_TOOLS):
                with self.subTest(file=path.name):
                    self.assertRegex(text, r"(?i)(oui|confirm|never|jamais)")

    def test_never_exposed_tools_are_not_instructed(self):
        for rel in self.FILES:
            text = read(rel)
            for tool in NEVER:
                for m in re.finditer(rf"`{tool}[^`]*`", text):
                    ctx = text[max(0, m.start() - 160): m.end() + 160].lower()
                    self.assertRegex(ctx, r"(not exposed|never|jamais|n'est|ne s'appelle)", f"{rel}: {tool}")


class TestDocs(unittest.TestCase):
    def test_documented_everywhere(self):
        for rel in ("AGENTS.md", "docs/configuration.md", "docs/agents/nutritionist.md", "docs/skills/log.md",
                    "docs/garmin-setup.md"):
            with self.subTest(file=rel):
                self.assertIn("garmin_sync", read(rel))
        self.assertIn("nutrition-garmin.md", read("mkdocs.yml"))
        self.assertIn("nutrition-garmin.md", read("README.md"))

    def test_eval_cases_use_relative_dates_only(self):
        for name in ("nutrition-garmin-push-asks", "nutrition-garmin-off-no-proposal"):
            text = read(f"tests/evals/cases/{name}.toml")
            self.assertNotRegex(text, r"\b20\d\d-\d\d-\d\d\b")
            self.assertIn("tools_not_called", text)


if __name__ == "__main__":
    unittest.main()
