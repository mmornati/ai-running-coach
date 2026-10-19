"""Palier A — plusieurs workspaces sur la même machine, sous le même utilisateur (#127, phase 1a).

Jetons Garmin et identifiants intervals.icu propres à chaque workspace (`--garmin-tokens`,
`--intervals-dir`), planification cron/launchd PAR workspace (installer B ne remplace jamais la ligne
de A), verrou de la sync (`ARC_LOCK_WORKSPACE`). Tout dans le bac à sable : `uv`, `crontab` et
`launchctl` sont des stubs. Le défaut (aucune option) reste verrouillé : mêmes lignes cron, même
label launchd, même `.mcp.json`.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from tests.lib.asserts import InstallAsserts
from tests.lib.sandbox import Sandbox

LEGACY_MARKER = "# ai-running-coach daily-sync"
LEGACY_PLIST = "Library/LaunchAgents/com.ai-running-coach.daily-sync.plist"


def _ws(sb: Sandbox, name: str) -> Path:
    ws = sb.root / name
    ws.mkdir()
    return ws


def _mcp(ws: Path) -> dict:
    return json.loads((ws / ".mcp.json").read_text(encoding="utf-8"))


def _lines(sb: Sandbox, ws: Path) -> list:
    return [line for line in sb.crontab().splitlines() if f'ARC_WORKSPACE="{ws}"' in line]


class TestGarminTokensFlag(InstallAsserts):
    def test_flag_writes_garmintokens_in_every_workspace_local_config_and_authenticates_there(self):
        with Sandbox() as sb:
            ws, tokens = _ws(sb, "alice"), sb.root / "tokens-alice"
            self.assertSucceeded(sb.install("--workspace", str(ws), "--garmin-tokens", str(tokens)))
            for cfg in (ws / ".mcp.json", ws / ".cursor/mcp.json", ws / ".gemini/settings.json",
                        ws / ".windsurf/mcp_config.json"):
                env = json.loads(cfg.read_text())["mcpServers"]["garmin"]["env"]
                self.assertEqual(env["GARMINTOKENS"], str(tokens), cfg)
                self.assertIn("GARMIN_ENABLED_TOOLS", env)
            auth = [args for _, args in sb.stub_calls("uv") if "garmin-mcp-auth" in args]
            self.assertTrue(auth and all(f"--token-path {tokens}" in a for a in auth), auth)
            self.assertTrue(tokens.is_dir())

    def test_global_opencode_config_is_not_overwritten_by_a_workspace_specific_entry(self):
        """Défaut verrouillé : ~/.config/opencode/opencode.json est partagé par tous les workspaces."""
        with Sandbox() as sb:
            cfg = sb.home / ".config/opencode/opencode.json"
            cfg.parent.mkdir(parents=True)
            cfg.write_text(json.dumps({"mcp": {"garmin": {"type": "local", "command": ["garmin-mcp", "stdio"],
                                                          "environment": {"MARK": "other-workspace"}}}}))
            before = cfg.read_text()
            ws = _ws(sb, "bob")
            self.assertSucceeded(sb.install("--workspace", str(ws), "--garmin-tokens", str(sb.root / "t-bob")))
            self.assertEqual(cfg.read_text(), before)

    def test_plain_rerun_keeps_the_tokens_directory(self):
        with Sandbox() as sb:
            ws, tokens = _ws(sb, "alice"), sb.root / "tokens-alice"
            self.assertSucceeded(sb.install("--workspace", str(ws), "--garmin-tokens", str(tokens)))
            self.assertSucceeded(sb.install("--workspace", str(ws)))
            self.assertEqual(_mcp(ws)["mcpServers"]["garmin"]["env"]["GARMINTOKENS"], str(tokens))
            last_auth = [args for _, args in sb.stub_calls("uv") if "garmin-mcp-auth" in args][-1]
            self.assertIn(f"--token-path {tokens}", last_auth)

    def test_two_workspaces_keep_two_distinct_directories(self):
        with Sandbox() as sb:
            alice, bob = _ws(sb, "alice"), _ws(sb, "bob")
            self.assertSucceeded(sb.install("--workspace", str(alice), "--garmin-tokens", str(sb.root / "ta")))
            self.assertSucceeded(sb.install("--workspace", str(bob), "--garmin-tokens", str(sb.root / "tb")))
            self.assertEqual(_mcp(alice)["mcpServers"]["garmin"]["env"]["GARMINTOKENS"], str(sb.root / "ta"))
            self.assertEqual(_mcp(bob)["mcpServers"]["garmin"]["env"]["GARMINTOKENS"], str(sb.root / "tb"))

    def test_default_install_is_unchanged(self):
        with Sandbox() as sb:
            ws = _ws(sb, "solo")
            self.assertSucceeded(sb.install("--workspace", str(ws)))
            env = _mcp(ws)["mcpServers"]["garmin"]["env"]
            self.assertEqual(list(env), ["GARMIN_ENABLED_TOOLS"])
            auth = [args for _, args in sb.stub_calls("uv") if "garmin-mcp-auth" in args]
            self.assertTrue(auth)
            self.assertFalse([a for a in auth if "--token-path" in a], auth)

    def test_relative_path_is_made_absolute(self):
        with Sandbox() as sb:
            ws = _ws(sb, "alice")
            self.assertSucceeded(sb.install("--workspace", str(ws), "--garmin-tokens", "rel/tokens", "--no-auth"))
            value = _mcp(ws)["mcpServers"]["garmin"]["env"]["GARMINTOKENS"]
            self.assertTrue(value.startswith("/") and value.endswith("rel/tokens"), value)

    def test_flag_refused_with_another_source(self):
        with Sandbox() as sb:
            ws = _ws(sb, "alice")
            self.assertFailed(sb.install("--workspace", str(ws), "--source", "intervals",
                                         "--garmin-tokens", str(sb.root / "t"), "--no-auth"),
                              "--garmin-tokens ne s'applique qu'à la source garmin")


class TestIntervalsDirFlag(InstallAsserts):
    def test_wrapper_and_mcp_command_live_in_the_workspace_directory(self):
        with Sandbox() as sb:
            ws, icu = _ws(sb, "alice"), sb.root / "icu-alice"
            self.assertSucceeded(sb.install("--workspace", str(ws), "--source", "intervals",
                                            "--intervals-dir", str(icu), "--no-auth"))
            self.assertTrue((icu / "run.sh").is_file())
            self.assertEqual(_mcp(ws)["mcpServers"]["intervals"]["command"], f"{icu}/run.sh")
            self.assertFalse((sb.home / ".config/ai-running-coach/intervals-icu-mcp/run.sh").exists())

    def test_plain_rerun_keeps_the_directory(self):
        with Sandbox() as sb:
            ws, icu = _ws(sb, "alice"), sb.root / "icu-alice"
            self.assertSucceeded(sb.install("--workspace", str(ws), "--source", "intervals",
                                            "--intervals-dir", str(icu), "--no-auth"))
            self.assertSucceeded(sb.install("--workspace", str(ws), "--no-auth"))
            self.assertEqual(_mcp(ws)["mcpServers"]["intervals"]["command"], f"{icu}/run.sh")
            self.assertFalse((sb.home / ".config/ai-running-coach/intervals-icu-mcp/run.sh").exists())

    def test_default_install_is_unchanged(self):
        with Sandbox() as sb:
            ws = _ws(sb, "solo")
            self.assertSucceeded(sb.install("--workspace", str(ws), "--source", "intervals", "--no-auth"))
            default = sb.home / ".config/ai-running-coach/intervals-icu-mcp"
            self.assertEqual(_mcp(ws)["mcpServers"]["intervals"], {"command": f"{default}/run.sh", "args": []})
            self.assertTrue((default / "run.sh").is_file())

    def test_flag_refused_with_another_source(self):
        with Sandbox() as sb:
            ws = _ws(sb, "alice")
            self.assertFailed(sb.install("--workspace", str(ws), "--intervals-dir", str(sb.root / "i"), "--no-auth"),
                              "--intervals-dir ne s'applique qu'à la source intervals")


class TestCronPerWorkspace(InstallAsserts):
    """Défaut verrouillé : `crontab` remplaçait TOUTES les lignes marquées — installer le workspace B
    supprimait celles du workspace A."""

    def _install(self, sb, ws, *extra):
        return sb.install("--no-auth", "--daily-sync", "--workspace", str(ws), *extra, ARC_FAKE_UNAME="Linux")

    def test_second_workspace_keeps_the_first_workspace_lines(self):
        with Sandbox() as sb:
            alice, bob = _ws(sb, "alice"), _ws(sb, "bob")
            self.assertSucceeded(self._install(sb, alice))
            self.assertSucceeded(self._install(sb, bob))
            self.assertEqual(len(_lines(sb, alice)), 2, sb.crontab())
            self.assertEqual(len(_lines(sb, bob)), 2, sb.crontab())
            # Le premier garde le marqueur historique ; le second reçoit un marqueur suffixé.
            self.assertTrue(all(line.endswith(LEGACY_MARKER) for line in _lines(sb, alice)), sb.crontab())
            self.assertTrue(all(re.search(re.escape(LEGACY_MARKER) + r" \[bob-\d+\]$", l) for l in _lines(sb, bob)),
                            sb.crontab())

    def test_reruns_do_not_duplicate_nor_disturb_the_other_workspace(self):
        with Sandbox() as sb:
            alice, bob = _ws(sb, "alice"), _ws(sb, "bob")
            for ws in (alice, bob, alice, bob, alice):
                self.assertSucceeded(self._install(sb, ws))
            self.assertEqual(len(_lines(sb, alice)), 2, sb.crontab())
            self.assertEqual(len(_lines(sb, bob)), 2, sb.crontab())

    def test_legacy_lines_of_this_workspace_are_replaced_and_other_legacy_lines_kept(self):
        with Sandbox() as sb:
            alice, bob = _ws(sb, "alice"), _ws(sb, "bob")
            legacy = ('0 6 * * * ARC_WORKSPACE="{ws}" "/engine/scripts/daily-sync.sh" >/dev/null 2>&1 '
                      + LEGACY_MARKER + "\n")
            sb.set_crontab("30 3 * * * /usr/bin/backup.sh\n" + legacy.format(ws=alice) + legacy.format(ws=bob))
            self.assertSucceeded(self._install(sb, alice))
            crontab = sb.crontab()
            self.assertIn("backup.sh", crontab)
            self.assertEqual(len(_lines(sb, alice)), 2, crontab)          # remplacée, pas dupliquée
            self.assertEqual(len(_lines(sb, bob)), 1, crontab)            # l'autre workspace est intact
            self.assertIn(legacy.format(ws=bob).strip(), crontab)
            self.assertFalse([l for l in _lines(sb, alice) if l.startswith("0 6 ")], crontab)

    def test_legacy_line_of_another_workspace_forces_a_suffixed_marker(self):
        with Sandbox() as sb:
            alice, bob = _ws(sb, "alice"), _ws(sb, "bob")
            sb.set_crontab(f'0 6 * * * ARC_WORKSPACE="{alice}" "/e/daily-sync.sh" >/dev/null 2>&1 {LEGACY_MARKER}\n')
            self.assertSucceeded(self._install(sb, bob))
            self.assertEqual(len(_lines(sb, alice)), 1, sb.crontab())
            self.assertTrue(all("[bob-" in l for l in _lines(sb, bob)), sb.crontab())

    def test_single_workspace_install_keeps_the_historical_lines(self):
        with Sandbox() as sb:
            alice = _ws(sb, "alice")
            self.assertSucceeded(self._install(sb, alice))
            self.assertTrue(all(l.endswith(" >/dev/null 2>&1 " + LEGACY_MARKER) for l in _lines(sb, alice)),
                            sb.crontab())

    def test_dry_run_does_not_touch_the_crontab(self):
        with Sandbox() as sb:
            alice, bob = _ws(sb, "alice"), _ws(sb, "bob")
            self.assertSucceeded(self._install(sb, alice))
            before = sb.crontab()
            self.assertSucceeded(self._install(sb, bob, "--dry-run"))
            self.assertEqual(sb.crontab(), before)


class TestLaunchdPerWorkspace(InstallAsserts):
    def _install(self, sb, ws):
        return sb.install("--no-auth", "--daily-sync", "--workspace", str(ws), ARC_FAKE_UNAME="Darwin")

    def test_second_workspace_gets_a_suffixed_label_and_the_first_keeps_the_legacy_one(self):
        with Sandbox() as sb:
            alice, bob = _ws(sb, "alice"), _ws(sb, "bob")
            self.assertSucceeded(self._install(sb, alice))
            self.assertSucceeded(self._install(sb, bob))
            legacy = (sb.home / LEGACY_PLIST).read_text()
            self.assertIn(f"<key>ARC_WORKSPACE</key><string>{alice}</string>", legacy)
            self.assertIn("<key>Label</key><string>com.ai-running-coach.daily-sync</string>", legacy)
            suffixed = sorted((sb.home / "Library/LaunchAgents").glob("com.ai-running-coach.daily-sync.bob-*.plist"))
            self.assertEqual(len(suffixed), 1)
            content = suffixed[0].read_text()
            self.assertIn(f"<key>ARC_WORKSPACE</key><string>{bob}</string>", content)
            self.assertIn(f"<key>Label</key><string>{suffixed[0].stem}</string>", content)

    def test_reinstalling_each_workspace_keeps_its_own_plist(self):
        with Sandbox() as sb:
            alice, bob = _ws(sb, "alice"), _ws(sb, "bob")
            for ws in (alice, bob, alice, bob):
                self.assertSucceeded(self._install(sb, ws))
            plists = list((sb.home / "Library/LaunchAgents").glob("com.ai-running-coach.daily-sync*.plist"))
            self.assertEqual(len(plists), 2, plists)
            self.assertIn(str(alice), (sb.home / LEGACY_PLIST).read_text())

    def test_single_workspace_keeps_the_legacy_label(self):
        with Sandbox() as sb:
            alice = _ws(sb, "alice")
            self.assertSucceeded(self._install(sb, alice))
            self.assertEqual([p.name for p in (sb.home / "Library/LaunchAgents").glob("*daily-sync*")],
                             ["com.ai-running-coach.daily-sync.plist"])


class TestSyncWorkspaceLock(InstallAsserts):
    def test_daily_sync_exports_the_lock_for_its_runner(self):
        with Sandbox() as sb:
            text = (sb.repo / "scripts/daily-sync.sh").read_text(encoding="utf-8")
            self.assertRegex(text, r"(?m)^export ARC_WORKSPACE ARC_LOCK_WORKSPACE=1$")

    def test_python_scripts_refuse_a_foreign_workspace_when_locked(self):
        with Sandbox() as sb:
            alice, bob = _ws(sb, "alice"), _ws(sb, "bob")
            proc = sb.run(["python3", str(sb.repo / "scripts/arc_index.py"), "--workspace", str(bob), "--validate",
                           str(bob / "x.md")], ARC_LOCK_WORKSPACE="1", ARC_WORKSPACE=str(alice))
            self.assertFailed(proc, "workspace refusé")
            proc = sb.run(["python3", str(sb.repo / "scripts/coach_config.py"), "get", "--workspace", str(bob),
                           "--section", "sync", "--key", "mode"], ARC_LOCK_WORKSPACE="1", ARC_WORKSPACE=str(alice))
            self.assertFailed(proc, "workspace refusé")

    def test_same_workspace_and_unlocked_runs_are_unaffected(self):
        with Sandbox() as sb:
            alice, bob = _ws(sb, "alice"), _ws(sb, "bob")
            ok = sb.run(["python3", str(sb.repo / "scripts/coach_config.py"), "get", "--workspace", str(alice),
                         "--section", "sync", "--key", "mode", "--default", "schedule"],
                        ARC_LOCK_WORKSPACE="1", ARC_WORKSPACE=str(alice))
            self.assertSucceeded(ok)
            free = sb.run(["python3", str(sb.repo / "scripts/coach_config.py"), "get", "--workspace", str(bob),
                           "--section", "sync", "--key", "mode", "--default", "schedule"], ARC_WORKSPACE=str(alice))
            self.assertSucceeded(free)

    def test_shell_helpers_refuse_a_foreign_workspace_and_a_missing_lock_target(self):
        with Sandbox() as sb:
            alice, bob = _ws(sb, "alice"), _ws(sb, "bob")
            lib = sb.repo / "scripts/lib/config.sh"
            foreign = sb.run(["bash", "-c", f'source "{lib}"; arc_assert_workspace "{bob}"; echo OK'],
                             ARC_LOCK_WORKSPACE="1", ARC_WORKSPACE=str(alice))
            self.assertFailed(foreign, "workspace refusé")
            own = sb.run(["bash", "-c", f'source "{lib}"; arc_assert_workspace "{alice}"; echo OK'],
                         ARC_LOCK_WORKSPACE="1", ARC_WORKSPACE=str(alice))
            self.assertSucceeded(own)
            self.assertIn("OK", own.stdout)
            # Verrou sans workspace valide : jamais de repli sur le pointeur ni sur le moteur.
            (sb.home / ".config/ai-running-coach").mkdir(parents=True, exist_ok=True)
            (sb.home / ".config/ai-running-coach/workspace").write_text(f"{bob}\n")
            fallback = sb.run(["bash", "-c", f'source "{lib}"; echo "$ARC_WORKSPACE"'], ARC_LOCK_WORKSPACE="1")
            self.assertFailed(fallback, "ARC_LOCK_WORKSPACE=1 sans ARC_WORKSPACE valide")
            unlocked = sb.run(["bash", "-c", f'source "{lib}"; arc_assert_workspace "{bob}"; echo "$ARC_WORKSPACE"'])
            self.assertSucceeded(unlocked)
            self.assertIn(str(bob), unlocked.stdout)


class TestDoctorReportsTheTokensSource(InstallAsserts):
    def test_json_payload_names_the_directory_and_its_source(self):
        with Sandbox() as sb:
            ws, tokens = _ws(sb, "alice"), sb.root / "tokens-alice"
            self.assertSucceeded(sb.install("--workspace", str(ws), "--garmin-tokens", str(tokens), "--no-auth"))
            proc = sb.script("coach_doctor.py", "--json", "--workspace", str(ws), ARC_FAKE_UNAME="Linux")
            payload = json.loads(proc.stdout)
            self.assertEqual(payload["tokens_dir"], str(tokens))
            self.assertIn("GARMINTOKENS", payload["tokens_dir_source"])
            human = sb.script("coach_doctor.py", "--workspace", str(ws), ARC_FAKE_UNAME="Linux")
            self.assertIn(f"Jetons Garmin : {tokens}", human.stdout)

    def test_default_human_output_has_no_extra_line(self):
        with Sandbox() as sb:
            ws = _ws(sb, "solo")
            human = sb.script("coach_doctor.py", "--workspace", str(ws), ARC_FAKE_UNAME="Linux")
            self.assertNotIn("Jetons Garmin :", human.stdout)
