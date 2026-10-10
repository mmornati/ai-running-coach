"""Palier A — préréglages d'installation (`--preset laptop|coach-server|docker`, #64).

Chaque préréglage ne fait que composer des options déjà existantes
(`--ide`, `--daily-sync`, `--remote-control`, `--no-auth`/`--auth`,
`--use-leanproxy`, et leurs négations `--no-daily-sync`/`--no-remote-control`)
— voir `apply_preset()` dans `install.sh`. Ces tests verrouillent :

  - le mapping réel de chaque préréglage (empreinte d'arborescence, en
    `--dry-run` et en installation réelle) — notamment que `docker` garde
    l'authentification Garmin ACTIVE (revue #111 : le conteneur ne parle
    jamais à Garmin, mais `docs/dashboard/docker.md` le déploie « sur la
    machine coach », dont la synchronisation en a besoin comme n'importe
    quelle autre machine coach) ;
  - la priorité systématique d'une option explicite sur le préréglage,
    quel que soit l'ordre des arguments, y compris pour ÉTEINDRE une valeur
    qu'un préréglage aurait allumée (`--no-daily-sync`, `--no-remote-control`,
    `--auth`) ;
  - le rejet propre d'un préréglage inconnu, d'une valeur manquante (y
    compris quand elle ressemble à une autre option) et d'un `--preset`
    répété avec deux valeurs différentes.

`ARC_FAKE_UNAME=Darwin` fixe le backend (LaunchAgent, jamais crontab) pour que
les empreintes d'arborescence soient les mêmes sur les machines de CI Linux et
macOS — `tests/lib/sandbox.Sandbox.tree()` ne renvoie que des chemins relatifs
au bac à sable (jamais un chemin absolu de l'hôte), donc les empreintes
ci-dessous sont portables telles quelles.
"""

from __future__ import annotations

from tests.lib.asserts import InstallAsserts
from tests.lib.sandbox import Sandbox

DARWIN = {"ARC_FAKE_UNAME": "Darwin"}

# Empreintes attendues : chemins AJOUTÉS par rapport à un dépôt fraîchement
# copié (avant tout appel à install.sh), pour une installation réelle avec le
# préréglage nommé et rien d'autre. Régénérées en lisant la sortie réelle de
# `sb.tree()` (voir la story #64) — un écart doit être expliqué par un
# changement assumé du mapping du préréglage, jamais par un artefact
# d'environnement (aucun chemin absolu n'y figure).
EXPECTED_ADDED_PATHS = {
    "laptop": {
        "home/.claude.json",
        "home/.config/ai-running-coach",
        "home/.config/ai-running-coach/workspace",
        "home/.config/opencode",
        "home/.config/opencode/opencode.json",
        "repo/.claude",
        "repo/.claude/agents",
        "repo/.claude/agents/coach.md",
        "repo/.claude/agents/course-strategist.md",
        "repo/.claude/agents/medical.md",
        "repo/.claude/agents/nutritionist.md",
        "repo/.claude/agents/sports-director.md",
        "repo/.claude/skills",
        "repo/.cursor",
        "repo/.cursor/cli.json",
        "repo/.cursor/mcp.json",
        "repo/.gemini",
        "repo/.gemini/commands",
        "repo/.gemini/commands/coach.toml",
        "repo/.gemini/commands/course-strategist.toml",
        "repo/.gemini/commands/inspection.toml",
        "repo/.gemini/commands/log.toml",
        "repo/.gemini/commands/medical.toml",
        "repo/.gemini/commands/nutritionist.toml",
        "repo/.gemini/commands/race.toml",
        "repo/.gemini/commands/sports-director.toml",
        "repo/.gemini/commands/today.toml",
        "repo/.gemini/commands/week.toml",
        "repo/.gemini/commands/why.toml",
        "repo/.gemini/settings.json",
        "repo/.github",
        "repo/.github/agents",
        "repo/.github/agents/coach.md",
        "repo/.github/agents/course-strategist.md",
        "repo/.github/agents/medical.md",
        "repo/.github/agents/nutritionist.md",
        "repo/.github/agents/sports-director.md",
        "repo/.github/skills",
        "repo/.mcp.json",
        "repo/.opencode",
        "repo/.opencode/agents",
        "repo/.opencode/agents/coach.md",
        "repo/.opencode/agents/course-strategist.md",
        "repo/.opencode/agents/medical.md",
        "repo/.opencode/agents/nutritionist.md",
        "repo/.opencode/agents/sports-director.md",
        "repo/.opencode/skills",
        "repo/.windsurf",
        "repo/.windsurf/mcp_config.json",
        "repo/activities",
        "repo/config/workspace.user.toml",
        "repo/config/workspace.user.toml.bak",
        "repo/medical",
        "repo/nutrition",
        "repo/planning",
        "repo/gear",
        "repo/rapports",
        "repo/resources",
    },
    "coach-server": {
        "home/.claude.json",
        "home/.config/ai-running-coach",
        "home/.config/ai-running-coach/workspace",
        "home/Library",
        "home/Library/LaunchAgents",
        "home/Library/LaunchAgents/com.ai-running-coach.daily-sync.plist",
        "home/Library/LaunchAgents/com.ai-running-coach.remote.plist",
        "repo/.claude",
        "repo/.claude/agents",
        "repo/.claude/agents/coach.md",
        "repo/.claude/agents/course-strategist.md",
        "repo/.claude/agents/medical.md",
        "repo/.claude/agents/nutritionist.md",
        "repo/.claude/agents/sports-director.md",
        "repo/.claude/skills",
        "repo/.mcp.json",
        "repo/activities",
        "repo/config/workspace.user.toml",
        "repo/config/workspace.user.toml.bak",
        "repo/logs",
        "repo/medical",
        "repo/nutrition",
        "repo/planning",
        "repo/gear",
        "repo/rapports",
        "repo/resources",
    },
    "docker": {
        "home/.claude.json",
        "home/.config/ai-running-coach",
        "home/.config/ai-running-coach/workspace",
        "home/Library",
        "home/Library/LaunchAgents",
        "home/Library/LaunchAgents/com.ai-running-coach.daily-sync.plist",
        "repo/.claude",
        "repo/.claude/agents",
        "repo/.claude/agents/coach.md",
        "repo/.claude/agents/course-strategist.md",
        "repo/.claude/agents/medical.md",
        "repo/.claude/agents/nutritionist.md",
        "repo/.claude/agents/sports-director.md",
        "repo/.claude/skills",
        "repo/.mcp.json",
        "repo/activities",
        "repo/config/workspace.user.toml",
        "repo/config/workspace.user.toml.bak",
        "repo/logs",
        "repo/medical",
        "repo/nutrition",
        "repo/planning",
        "repo/gear",
        "repo/rapports",
        "repo/resources",
    },
}


def _added(before: dict, after: dict) -> set:
    return set(after) - set(before)


class TestPresetDryRun(InstallAsserts):
    """`--dry-run` doit fonctionner pour chaque préréglage, sans rien écrire."""

    def test_dry_run_writes_nothing_per_preset(self):
        for preset in EXPECTED_ADDED_PATHS:
            with self.subTest(preset=preset):
                with Sandbox() as sb:
                    before = sb.tree()
                    proc = sb.install("--preset", preset, "--dry-run", **DARWIN)
                    self.assertSucceeded(proc, f"--preset {preset} --dry-run")
                    self.assertTreeUnchanged(
                        before, sb.tree(), f"--preset {preset} --dry-run a écrit sur le disque"
                    )


class TestPresetRealRunFingerprint(InstallAsserts):
    """Empreinte d'arborescence par préréglage — installation réelle (sandbox)."""

    def test_fingerprint_matches_mapping(self):
        for preset, expected in EXPECTED_ADDED_PATHS.items():
            with self.subTest(preset=preset):
                with Sandbox() as sb:
                    before = sb.tree()
                    proc = sb.install("--preset", preset, **DARWIN)
                    self.assertSucceeded(proc, f"--preset {preset}")
                    added = _added(before, sb.tree())
                    missing = expected - added
                    unexpected = added - expected
                    self.assertFalse(
                        missing or unexpected,
                        f"--preset {preset} : empreinte inattendue\n"
                        f"  manquants : {sorted(missing)}\n"
                        f"  en trop   : {sorted(unexpected)}",
                    )

    def test_laptop_configures_every_ide(self):
        with Sandbox() as sb:
            self.assertSucceeded(sb.install("--preset", "laptop", **DARWIN))
            for rel in (".mcp.json", ".cursor/mcp.json", ".windsurf/mcp_config.json"):
                self.assertIsFile(sb.repo / rel)
            self.assertIsFile(sb.home / ".config/opencode/opencode.json")

    def test_coach_server_matches_mobile_doc_steps(self):
        """docs/mobile.md enchaîne --ide claude, --daily-sync puis --remote-control."""
        with Sandbox() as sb:
            self.assertSucceeded(sb.install("--preset", "coach-server", **DARWIN))
            self.assertIsFile(sb.repo / ".mcp.json")
            self.assertFalse((sb.repo / ".opencode").exists(), "coach-server ne devrait cibler que Claude Code")
            self.assertIsFile(sb.home / "Library/LaunchAgents/com.ai-running-coach.daily-sync.plist")
            self.assertIsFile(sb.home / "Library/LaunchAgents/com.ai-running-coach.remote.plist")
            self.assertCalled(sb, "uv", "run garmin-mcp-auth")

    def test_docker_keeps_auth_on_and_skips_remote_control(self):
        """docs/dashboard/docker.md : « sur la machine coach » — le conteneur ne parle
        jamais à Garmin lui-même, mais la synchronisation (elle, sur l'hôte) en a
        besoin comme sur n'importe quelle machine coach : l'auth reste active."""
        with Sandbox() as sb:
            self.assertSucceeded(sb.install("--preset", "docker", **DARWIN))
            self.assertIsFile(sb.home / "Library/LaunchAgents/com.ai-running-coach.daily-sync.plist")
            self.assertFalse(
                (sb.home / "Library/LaunchAgents/com.ai-running-coach.remote.plist").exists(),
                "docker ne doit pas activer Remote Control",
            )
            self.assertTrue(
                any("garmin-mcp-auth" in args for _, args in sb.stub_calls("uv")),
                "docker : l'authentification Garmin doit tourner (--daily-sync en a besoin)",
            )

    def test_docker_help_and_preset_table_do_not_disable_auth(self):
        """Régression : le préréglage ne doit plus composer --no-auth (#111 review)."""
        with Sandbox() as sb:
            proc = sb.install("--preset", "docker", "--dry-run", **DARWIN)
            self.assertSucceeded(proc)
            self.assertOutputContains(proc, "Auth Garmin : activée (préréglage docker)")
            help_proc = sb.install("--help")
            self.assertOutputLacks(help_proc, "docker        --ide claude --daily-sync --no-auth")


class TestPresetExplicitOverridesWin(InstallAsserts):
    """Une option explicite l'emporte toujours sur le préréglage, quel que soit l'ordre."""

    def test_explicit_daily_sync_wins_after_preset(self):
        with Sandbox() as sb:
            self.assertSucceeded(sb.install("--preset", "laptop", "--daily-sync", "--no-auth", **DARWIN))
            self.assertIsFile(sb.home / "Library/LaunchAgents/com.ai-running-coach.daily-sync.plist")

    def test_explicit_daily_sync_wins_before_preset(self):
        """Même résultat en inversant l'ordre : « --daily-sync --preset laptop »."""
        with Sandbox() as sb:
            self.assertSucceeded(sb.install("--daily-sync", "--preset", "laptop", "--no-auth", **DARWIN))
            self.assertIsFile(sb.home / "Library/LaunchAgents/com.ai-running-coach.daily-sync.plist")

    def test_explicit_no_auth_wins_after_preset(self):
        with Sandbox() as sb:
            self.assertSucceeded(sb.install("--preset", "coach-server", "--no-auth", **DARWIN))
            self.assertFalse(
                any("garmin-mcp-auth" in args for _, args in sb.stub_calls("uv")),
                "garmin-mcp-auth appelé malgré --no-auth explicite (préréglage coach-server)",
            )

    def test_explicit_no_auth_wins_before_preset(self):
        with Sandbox() as sb:
            self.assertSucceeded(sb.install("--no-auth", "--preset", "coach-server", **DARWIN))
            self.assertFalse(
                any("garmin-mcp-auth" in args for _, args in sb.stub_calls("uv")),
                "garmin-mcp-auth appelé malgré --no-auth explicite (préréglage coach-server)",
            )

    def test_explicit_ide_wins_over_preset_after(self):
        with Sandbox() as sb:
            self.assertSucceeded(sb.install("--preset", "coach-server", "--ide", "all", "--no-auth", **DARWIN))
            self.assertIsFile(sb.repo / ".cursor/mcp.json")

    def test_explicit_ide_wins_over_preset_before(self):
        with Sandbox() as sb:
            self.assertSucceeded(sb.install("--ide", "all", "--preset", "coach-server", "--no-auth", **DARWIN))
            self.assertIsFile(sb.repo / ".cursor/mcp.json")

    def test_recap_marks_explicit_vs_preset_origin(self):
        """Vérifie des LIGNES précises, pas juste la présence du mot « explicite »
        quelque part dans la sortie (qui passerait même si la mauvaise ligne le
        portait, p. ex. sur Dry-run plutôt que sur Auth Garmin)."""
        with Sandbox() as sb:
            proc = sb.install("--preset", "coach-server", "--no-auth", "--dry-run", **DARWIN)
            self.assertSucceeded(proc)
            out = proc.stdout
            self.assertRegex(out, r"Auth Garmin\s*:\s*sautée\s*\(explicite\)")
            self.assertRegex(out, r"Sync auto \(cron\)\s*:\s*oui\s*\(préréglage coach-server\)")
            self.assertRegex(out, r"Remote Control\s*:\s*oui\s*\(préréglage coach-server\)")
            self.assertRegex(out, r"IDE\s*:\s*claude\s*\(préréglage coach-server\)")

    def test_negating_flag_turns_off_preset_daily_sync_after(self):
        with Sandbox() as sb:
            proc = sb.install("--preset", "coach-server", "--no-daily-sync", "--no-auth", "--dry-run", **DARWIN)
            self.assertSucceeded(proc)
            self.assertRegex(proc.stdout, r"Sync auto \(cron\)\s*:\s*non\s*\(explicite\)")

    def test_negating_flag_turns_off_preset_daily_sync_before(self):
        with Sandbox() as sb:
            proc = sb.install("--no-daily-sync", "--preset", "coach-server", "--no-auth", "--dry-run", **DARWIN)
            self.assertSucceeded(proc)
            self.assertRegex(proc.stdout, r"Sync auto \(cron\)\s*:\s*non\s*\(explicite\)")

    def test_negating_flag_turns_off_preset_remote_control_after(self):
        with Sandbox() as sb:
            self.assertSucceeded(
                sb.install("--preset", "coach-server", "--no-remote-control", "--no-auth", **DARWIN)
            )
            self.assertFalse((sb.home / "Library/LaunchAgents/com.ai-running-coach.remote.plist").exists())

    def test_negating_flag_turns_off_preset_remote_control_before(self):
        with Sandbox() as sb:
            self.assertSucceeded(
                sb.install("--no-remote-control", "--preset", "coach-server", "--no-auth", **DARWIN)
            )
            self.assertFalse((sb.home / "Library/LaunchAgents/com.ai-running-coach.remote.plist").exists())

    def test_auth_flag_turns_auth_back_on_after_docker_style_no_auth(self):
        """`--auth` doit pouvoir annuler un `--no-auth` explicite antérieur sur la
        ligne de commande (comportement standard « le dernier gagne » pour deux
        options explicites contradictoires, indépendant des préréglages)."""
        with Sandbox() as sb:
            self.assertSucceeded(sb.install("--no-auth", "--auth", **DARWIN))
            self.assertTrue(
                any("garmin-mcp-auth" in args for _, args in sb.stub_calls("uv")),
                "--auth après --no-auth devrait réactiver l'authentification",
            )

    def test_laptop_preset_equals_defaults_and_recap_says_so(self):
        """laptop == les défauts du script (docs/quickstart.md n'utilise aucune
        option) : la seule différence observable est que le récapitulatif
        rattache désormais IDE au préréglage plutôt qu'à « défaut »."""
        with Sandbox() as sb:
            before = sb.tree()
            proc_plain = sb.install("--no-auth", "--dry-run", **DARWIN)
            self.assertSucceeded(proc_plain)
            self.assertTreeUnchanged(before, sb.tree(), "--dry-run sans préréglage a écrit sur le disque")

            proc_preset = sb.install("--preset", "laptop", "--no-auth", "--dry-run", **DARWIN)
            self.assertSucceeded(proc_preset)
            self.assertRegex(proc_preset.stdout, r"IDE\s*:\s*all\s*\(préréglage laptop\)")
            # Sans préréglage, la même valeur IDE est un défaut, pas un préréglage.
            self.assertRegex(proc_plain.stdout, r"IDE\s*:\s*all\s*\(défaut\)")


class TestUnknownPreset(InstallAsserts):
    def test_unknown_preset_is_a_clean_error(self):
        with Sandbox() as sb:
            proc = sb.install("--preset", "raspberry-pi")
            self.assertFailed(proc, "--preset inconnu")
            self.assertOutputContains(proc, "raspberry-pi")
            for name in ("laptop", "coach-server", "docker"):
                self.assertOutputContains(proc, name)
            self.assertOutputLacks(proc, "unbound variable")

    def test_preset_missing_value_is_a_clean_error(self):
        with Sandbox() as sb:
            proc = sb.install("--preset")
            self.assertFailed(proc, "--preset sans valeur")
            self.assertOutputLacks(proc, "unbound variable")

    def test_preset_followed_by_another_flag_is_a_missing_value_not_an_unknown_preset(self):
        """`--preset --dry-run` : « --dry-run » est une option, pas une valeur de
        préréglage — le message doit porter sur la valeur manquante, jamais dire
        « préréglage inconnu : --dry-run »."""
        with Sandbox() as sb:
            proc = sb.install("--preset", "--dry-run")
            self.assertFailed(proc, "--preset suivi d'une autre option")
            self.assertOutputContains(proc, "--preset attend une valeur")
            self.assertOutputLacks(proc, "Préréglage inconnu")

    def test_repeated_preset_with_different_values_is_rejected(self):
        with Sandbox() as sb:
            proc = sb.install("--preset", "laptop", "--preset", "coach-server", "--dry-run")
            self.assertFailed(proc, "--preset répété avec des valeurs différentes")
            self.assertOutputContains(proc, "laptop")
            self.assertOutputContains(proc, "coach-server")
            self.assertOutputLacks(proc, "unbound variable")

    def test_repeated_preset_with_same_value_is_accepted(self):
        with Sandbox() as sb:
            proc = sb.install("--preset", "laptop", "--preset", "laptop", "--dry-run", **DARWIN)
            self.assertSucceeded(proc, "--preset répété avec la même valeur")


class TestGearWhitelistInstalled(InstallAsserts):
    """#133 — `install.sh` écrit la liste blanche (avec les outils matériel) dans `.mcp.json` et
    `opencode.json`, et une relance la met à jour sans toucher aux autres serveurs de l'athlète."""

    TOOLS = ("get_gear", "get_activity_gear", "add_gear_to_activity")

    @staticmethod
    def _garmin_tools(entry: dict) -> list:
        env = entry.get("env") or entry.get("environment") or {}
        return env["GARMIN_ENABLED_TOOLS"].split(",")

    def test_whitelist_reaches_mcp_json_and_opencode_json(self):
        import json
        with Sandbox() as sb:
            self.assertSucceeded(sb.install("--preset", "laptop", **DARWIN))
            mcp = json.loads((sb.repo / ".mcp.json").read_text())
            tools = self._garmin_tools(mcp["mcpServers"]["garmin"])
            for tool in self.TOOLS:
                self.assertIn(tool, tools)
            self.assertNotIn("remove_gear_from_activity", tools)
            opencode = json.loads((sb.home / ".config/opencode/opencode.json").read_text())
            entry = opencode["mcp"]["garmin"]
            for tool in self.TOOLS:
                self.assertIn(tool, self._garmin_tools(entry))

    def test_rerun_upgrades_an_old_whitelist_and_keeps_other_servers(self):
        import json
        with Sandbox() as sb:
            (sb.repo / ".mcp.json").write_text(json.dumps({"mcpServers": {
                "garmin": {"command": "garmin-mcp", "args": ["stdio"],
                           "env": {"GARMIN_ENABLED_TOOLS": "get_activities,get_sleep_data"}},
                "autre": {"command": "mon-serveur", "args": []},
            }}))
            self.assertSucceeded(sb.install("--preset", "laptop", **DARWIN))
            mcp = json.loads((sb.repo / ".mcp.json").read_text())
            self.assertIn("get_gear", self._garmin_tools(mcp["mcpServers"]["garmin"]))
            self.assertEqual(mcp["mcpServers"]["autre"], {"command": "mon-serveur", "args": []})
