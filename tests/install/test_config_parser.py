"""Palier A — le lecteur TOML de scripts/lib/config.sh.

Ce n'est pas un vrai analyseur TOML et il n'a pas besoin de l'être, mais il doit
être honnête sur le sous-ensemble qu'il prétend lire : les valeurs qu'il rend
pilotent le cron, les notifications et bientôt la sélection des agents.
"""

from __future__ import annotations

import textwrap

from tests.lib.asserts import InstallAsserts
from tests.lib.sandbox import Sandbox


class ConfigParserCase(InstallAsserts):
    def read(self, sb: Sandbox, expression: str, shared: str = "", user: str = "") -> str:
        (sb.repo / "config").mkdir(exist_ok=True)
        (sb.repo / "config/workspace.toml").write_text(textwrap.dedent(shared), encoding="utf-8")
        if user:
            (sb.repo / "config/workspace.user.toml").write_text(textwrap.dedent(user), encoding="utf-8")
        else:
            (sb.repo / "config/workspace.user.toml").unlink(missing_ok=True)
        proc = sb.run(
            ["bash", "-c", f'source "$0/scripts/lib/config.sh"; {expression}', str(sb.repo)],
            ARC_WORKSPACE=str(sb.repo),
        )
        self.assertSucceeded(proc, expression)
        return proc.stdout.strip()


class TestScalars(ConfigParserCase):
    def test_reads_a_plain_value(self):
        with Sandbox() as sb:
            self.assertEqual(
                self.read(sb, "toml_get language documents", '[language]\ndocuments = "fr"\n'),
                "fr",
            )

    def test_missing_key_falls_back_to_default(self):
        with Sandbox() as sb:
            self.assertEqual(
                self.read(sb, "toml_get language absent defaut", '[language]\ndocuments = "fr"\n'),
                "defaut",
            )

    def test_section_scoping(self):
        """Une clé homonyme dans une autre section ne doit pas être retournée."""
        with Sandbox() as sb:
            config = '''
                [a]
                valeur = "de-a"
                [b]
                valeur = "de-b"
            '''
            self.assertEqual(self.read(sb, "toml_get b valeur", config), "de-b")
            self.assertEqual(self.read(sb, "toml_get a valeur", config), "de-a")

    def test_hash_inside_a_quoted_string_is_kept(self):
        """`ntfy_topic = "run #42"` ne doit pas être tronqué à « run »."""
        with Sandbox() as sb:
            self.assertEqual(
                self.read(sb, "toml_get notifications ntfy_topic",
                          '[notifications]\nntfy_topic = "run #42"\n'),
                "run #42",
            )

    def test_trailing_comment_is_stripped(self):
        with Sandbox() as sb:
            self.assertEqual(
                self.read(sb, "toml_get sync runner", '[sync]\nrunner = "claude"   # exécuteur\n'),
                "claude",
            )


class TestPrecedence(ConfigParserCase):
    def test_user_file_wins(self):
        with Sandbox() as sb:
            self.assertEqual(
                self.read(sb, "toml_get language documents",
                          '[language]\ndocuments = "fr"\n', '[language]\ndocuments = "en"\n'),
                "en",
            )

    def test_user_file_can_override_with_an_empty_value(self):
        """Une valeur vide explicite doit effacer l'héritage, pas être ignorée."""
        with Sandbox() as sb:
            self.assertEqual(
                self.read(sb, "toml_get notifications ntfy_token_file",
                          '[notifications]\nntfy_token_file = "~/.config/arc/ntfy.token"\n',
                          '[notifications]\nntfy_token_file = ""\n'),
                "",
            )

    def test_empty_configured_value_does_not_become_the_default(self):
        with Sandbox() as sb:
            self.assertEqual(
                self.read(sb, "toml_get notifications ntfy_topic defaut-code",
                          '[notifications]\nntfy_topic = ""\n'),
                "",
            )


class TestLists(ConfigParserCase):
    def test_inline_array(self):
        with Sandbox() as sb:
            self.assertEqual(
                self.read(sb, "toml_get_list sync times", '[sync]\ntimes = ["07:15", "14:15"]\n'),
                "07:15\n14:15",
            )

    def test_multiline_array(self):
        """Un tableau réparti sur plusieurs lignes retombait silencieusement sur le défaut."""
        with Sandbox() as sb:
            config = '''
                [agents]
                enabled = [
                  "coach",
                  "medical",
                ]
            '''
            self.assertEqual(
                self.read(sb, "toml_get_list agents enabled", config),
                "coach\nmedical",
            )

    def test_multiline_array_does_not_break_the_next_section(self):
        with Sandbox() as sb:
            config = '''
                [agents]
                enabled = [
                  "coach",
                ]

                [sport]
                primary = "trail"
            '''
            self.assertEqual(self.read(sb, "toml_get sport primary", config), "trail")

    def test_missing_list_uses_default(self):
        with Sandbox() as sb:
            self.assertEqual(
                self.read(sb, 'toml_get_list sync times "07:15 14:15"', "[sync]\n"),
                "07:15\n14:15",
            )
