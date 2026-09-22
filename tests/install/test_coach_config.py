"""Palier A — scripts/coach_config.py (lecture/écriture TOML et JSON).

L'écriture doit PRÉSERVER le fichier : c'est tout l'intérêt par rapport à l'awk
de `setup-ntfy.sh`, qui reconstruisait le fichier et pouvait le perdre.
"""

from __future__ import annotations

import json
import textwrap

from tests.lib.asserts import InstallAsserts
from tests.lib.sandbox import Sandbox

USER_CONFIG = """\
# Overrides personnels — ce fichier est GITIGNORÉ.

[language]
# La langue de mes documents
documents = "fr"
responses = "auto"

[sync]
runner = "claude"
"""


class CoachConfigCase(InstallAsserts):
    def tool(self, sb: Sandbox, *args: str):
        return sb.run(["python3", str(sb.repo / "scripts/coach_config.py"), *args])

    def user_config(self, sb: Sandbox):
        return sb.repo / "config/workspace.user.toml"


class TestGet(CoachConfigCase):
    def test_reads_shared_default(self):
        with Sandbox() as sb:
            proc = self.tool(sb, "get", "--workspace", str(sb.repo), "--section", "coaching", "--key", "style")
            self.assertSucceeded(proc)
            self.assertEqual(proc.stdout.strip(), "bienveillant")

    def test_user_file_wins(self):
        with Sandbox() as sb:
            self.user_config(sb).write_text('[coaching]\nstyle = "factuel"\n')
            proc = self.tool(sb, "get", "--workspace", str(sb.repo), "--section", "coaching", "--key", "style")
            self.assertEqual(proc.stdout.strip(), "factuel")

    def test_missing_key_without_default_fails(self):
        with Sandbox() as sb:
            proc = self.tool(sb, "get", "--workspace", str(sb.repo), "--section", "coaching", "--key", "inexistant")
            self.assertFailed(proc)

    def test_list_is_returned_one_per_line(self):
        with Sandbox() as sb:
            proc = self.tool(sb, "get", "--workspace", str(sb.repo), "--section", "agents", "--key", "enabled")
            self.assertSucceeded(proc)
            self.assertEqual(
                proc.stdout.split(),
                ["coach", "medical", "nutritionist", "course-strategist"],
            )


class TestSet(CoachConfigCase):
    def test_replaces_a_value_and_keeps_everything_else(self):
        with Sandbox() as sb:
            cfg = self.user_config(sb)
            cfg.write_text(USER_CONFIG)
            proc = self.tool(sb, "set", "--workspace", str(sb.repo),
                             "--section", "language", "--key", "documents", "--value", "en")
            self.assertSucceeded(proc)

            content = cfg.read_text()
            self.assertIn('documents = "en"', content)
            self.assertIn("# La langue de mes documents", content, "commentaire de l'utilisateur perdu")
            self.assertIn('runner = "claude"', content, "autre section perdue")
            self.assertIn("# Overrides personnels", content, "en-tête perdu")

    def test_adds_a_key_to_an_existing_section(self):
        with Sandbox() as sb:
            cfg = self.user_config(sb)
            cfg.write_text(USER_CONFIG)
            self.assertSucceeded(self.tool(sb, "set", "--workspace", str(sb.repo),
                                           "--section", "sync", "--key", "lookback_days",
                                           "--value", "4", "--type", "int"))
            content = cfg.read_text()
            self.assertIn("lookback_days = 4", content)
            self.assertIn('runner = "claude"', content)

    def test_creates_a_missing_section(self):
        with Sandbox() as sb:
            cfg = self.user_config(sb)
            cfg.write_text(USER_CONFIG)
            self.assertSucceeded(self.tool(sb, "set", "--workspace", str(sb.repo),
                                           "--section", "health", "--key", "morning_check",
                                           "--value", "off"))
            self.assertIn('[health]\nmorning_check = "off"', cfg.read_text())

    def test_creates_the_file_when_absent(self):
        with Sandbox() as sb:
            cfg = self.user_config(sb)
            cfg.unlink(missing_ok=True)
            self.assertSucceeded(self.tool(sb, "set", "--workspace", str(sb.repo),
                                           "--section", "coaching", "--key", "style",
                                           "--value", "exigeant"))
            self.assertIn('style = "exigeant"', cfg.read_text())

    def test_writes_a_list(self):
        with Sandbox() as sb:
            cfg = self.user_config(sb)
            cfg.write_text(USER_CONFIG)
            self.assertSucceeded(self.tool(sb, "set", "--workspace", str(sb.repo),
                                           "--section", "agents", "--key", "enabled",
                                           "--list", "coach", "--list", "nutritionist"))
            self.assertIn('enabled = ["coach", "nutritionist"]', cfg.read_text())

    def test_replaces_a_multiline_list(self):
        with Sandbox() as sb:
            cfg = self.user_config(sb)
            cfg.write_text(textwrap.dedent('''\
                [agents]
                enabled = [
                  "coach",
                  "medical",
                ]

                [sport]
                primary = "trail"
                '''))
            self.assertSucceeded(self.tool(sb, "set", "--workspace", str(sb.repo),
                                           "--section", "agents", "--key", "enabled",
                                           "--list", "coach"))
            content = cfg.read_text()
            self.assertIn('enabled = ["coach"]', content)
            self.assertNotIn('"medical"', content, "ancienne entrée du tableau laissée derrière")
            self.assertIn('primary = "trail"', content, "section suivante abîmée")

    def test_is_idempotent(self):
        with Sandbox() as sb:
            cfg = self.user_config(sb)
            cfg.write_text(USER_CONFIG)
            args = ("set", "--workspace", str(sb.repo), "--section", "coaching",
                    "--key", "style", "--value", "factuel")
            self.assertSucceeded(self.tool(sb, *args))
            first = cfg.read_text()
            proc = self.tool(sb, *args)
            self.assertSucceeded(proc)
            self.assertEqual(cfg.read_text(), first)
            self.assertOutputContains(proc, "inchangé")

    def test_backs_up_before_overwriting(self):
        with Sandbox() as sb:
            cfg = self.user_config(sb)
            cfg.write_text(USER_CONFIG)
            self.assertSucceeded(self.tool(sb, "set", "--workspace", str(sb.repo),
                                           "--section", "language", "--key", "documents", "--value", "en"))
            self.assertFileContains(cfg.with_suffix(".toml.bak"), 'documents = "fr"')

    def test_round_trips_through_get(self):
        with Sandbox() as sb:
            self.assertSucceeded(self.tool(sb, "set", "--workspace", str(sb.repo),
                                           "--section", "health", "--key", "morning_check", "--value", "off"))
            proc = self.tool(sb, "get", "--workspace", str(sb.repo),
                             "--section", "health", "--key", "morning_check")
            self.assertEqual(proc.stdout.strip(), "off")


class TestMergeJson(CoachConfigCase):
    def test_refuses_to_touch_invalid_json(self):
        with Sandbox() as sb:
            target = sb.root / "broken.json"
            target.write_text('{"a": 1, oops')
            proc = self.tool(sb, "merge-json", "--file", str(target),
                             "--section", "mcp", "--name", "garmin", "--value", "{}")
            self.assertFailed(proc)
            self.assertEqual(target.read_text(), '{"a": 1, oops')

    def test_creates_from_template(self):
        with Sandbox() as sb:
            target = sb.root / "new.json"
            self.assertSucceeded(self.tool(sb, "merge-json", "--file", str(target),
                                           "--section", "mcp", "--name", "garmin",
                                           "--value", '{"enabled": true}',
                                           "--template", '{"$schema": "x"}'))
            data = json.loads(target.read_text())
            self.assertEqual(data["$schema"], "x")
            self.assertTrue(data["mcp"]["garmin"]["enabled"])
