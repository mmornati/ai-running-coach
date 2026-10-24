"""Palier A — plusieurs workspaces sur la même machine, sous le même utilisateur (#127, phase 1a).

Jetons Garmin et identifiants intervals.icu propres à chaque workspace (`--garmin-tokens`,
`--intervals-dir`), planification cron/launchd PAR workspace (installer B ne remplace jamais la ligne
de A), verrou de la sync (`ARC_LOCK_WORKSPACE`). Tout dans le bac à sable : `uv`, `crontab` et
`launchctl` sont des stubs. Le défaut (aucune option) reste verrouillé : mêmes lignes cron, même
label launchd, même `.mcp.json`.
"""

from __future__ import annotations

import shutil
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

    def test_legacy_garmin_watch_line_of_this_workspace_is_replaced_by_watch_py(self):
        with Sandbox() as sb:
            alice = _ws(sb, "alice")
            sb.set_crontab(f'*/15 * * * * ARC_WORKSPACE="{alice}" python3 "/e/scripts/garmin_watch.py" >/dev/null 2>&1 '
                           + LEGACY_MARKER + "\n")
            self.assertSucceeded(self._install(sb, alice))
            crontab = sb.crontab()
            self.assertNotIn("garmin_watch.py", crontab)
            self.assertEqual(len(_lines(sb, alice)), 2, crontab)

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

    def test_shell_lib_refuses_a_missing_lock_target_and_never_falls_back(self):
        with Sandbox() as sb:
            alice, bob = _ws(sb, "alice"), _ws(sb, "bob")
            lib = sb.repo / "scripts/lib/config.sh"
            own = sb.run(["bash", "-c", f'source "{lib}"; echo "$ARC_WORKSPACE"'],
                         ARC_LOCK_WORKSPACE="1", ARC_WORKSPACE=str(alice))
            self.assertSucceeded(own)
            self.assertIn(str(alice), own.stdout)
            # Verrou sans workspace valide : jamais de repli sur le pointeur ni sur le moteur.
            (sb.home / ".config/ai-running-coach").mkdir(parents=True, exist_ok=True)
            (sb.home / ".config/ai-running-coach/workspace").write_text(f"{bob}\n")
            fallback = sb.run(["bash", "-c", f'source "{lib}"; echo "$ARC_WORKSPACE"'], ARC_LOCK_WORKSPACE="1")
            self.assertFailed(fallback, "ARC_LOCK_WORKSPACE=1 sans ARC_WORKSPACE valide")
            unlocked = sb.run(["bash", "-c", f'source "{lib}"; echo "$ARC_WORKSPACE"'])
            self.assertSucceeded(unlocked)
            self.assertIn(str(bob), unlocked.stdout)

    def test_unused_shell_assert_helper_stays_removed(self):
        """Défaut verrouillé : `arc_assert_workspace` était définie sans aucun appelant (aucun script shell
        n'accepte d'option --workspace) — code mort qui donnait un faux sentiment de couverture."""
        with Sandbox() as sb:
            self.assertNotIn("arc_assert_workspace", (sb.repo / "scripts/lib/config.sh").read_text(encoding="utf-8"))

    def test_daily_sync_exports_an_absolute_workspace_even_when_given_a_relative_one(self):
        """Défaut verrouillé : un ARC_WORKSPACE relatif exporté tel quel désignait, après un `cd` du runner,
        un autre dossier pour le verrou que pour lib/config.sh."""
        with Sandbox() as sb:
            ws = _ws(sb, "alice")
            fake_bin = sb.root / "fake-bin"
            fake_bin.mkdir()
            dump = sb.root / "seen.txt"
            claude = fake_bin / "claude"
            claude.write_text(f'#!/usr/bin/env bash\nprintf "%s|%s" "$ARC_WORKSPACE" "$ARC_LOCK_WORKSPACE" > "{dump}"\n')
            claude.chmod(0o755)
            proc = sb.run([str(sb.repo / "scripts/daily-sync.sh")], cwd=sb.root, ARC_WORKSPACE="alice",
                          PATH=f"{fake_bin}:{sb.env()['PATH']}")
            self.assertTrue(dump.exists(), proc.stdout + proc.stderr)
            seen_ws, lock = dump.read_text().split("|")
            self.assertTrue(seen_ws.startswith("/"), seen_ws)
            self.assertEqual(Path(seen_ws).resolve(), ws.resolve())
            self.assertEqual(lock, "1")


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


class TestMigrationAndMovedWorkspaceCron(InstallAsserts):
    """Défaut verrouillé : l'appartenance d'une ligne était une égalité de chaînes avec $WORKSPACE_ROOT. Sur main,
    le marqueur remplaçait tout : « Migrer un workspace existant » (installation fusionnée puis --workspace),
    un workspace déplacé ou une autre graphie du chemin laissaient l'ancienne ligne et doublaient la sync."""

    def _install(self, sb, *args):
        return sb.install("--no-auth", "--daily-sync", *args, ARC_FAKE_UNAME="Linux")

    def _sync_lines(self, sb):
        return [l for l in sb.crontab().splitlines() if LEGACY_MARKER in l]

    def test_merged_install_then_workspace_replaces_the_engine_root_lines(self):
        with Sandbox() as sb:
            alice = _ws(sb, "alice")
            self.assertSucceeded(self._install(sb))                                    # fusionnée : racine du moteur
            self.assertEqual(len([l for l in self._sync_lines(sb) if f'ARC_WORKSPACE="{sb.repo}"' in l]), 2)
            proc = self._install(sb, "--workspace", str(alice))
            self.assertSucceeded(proc)
            self.assertEqual(len(self._sync_lines(sb)), 2, sb.crontab())
            self.assertEqual(len(_lines(sb, alice)), 2, sb.crontab())
            self.assertNotIn(f'ARC_WORKSPACE="{sb.repo}"', sb.crontab())
            self.assertTrue(all(l.endswith(" " + LEGACY_MARKER) for l in self._sync_lines(sb)), sb.crontab())
            self.assertOutputContains(proc, "périmée")

    def test_moved_workspace_replaces_the_line_of_the_old_path(self):
        with Sandbox() as sb:
            alice = _ws(sb, "alice")
            self.assertSucceeded(self._install(sb, "--workspace", str(alice)))
            moved = sb.root / "alice-moved"
            alice.rename(moved)
            self.assertSucceeded(self._install(sb, "--workspace", str(moved)))
            self.assertEqual(len(self._sync_lines(sb)), 2, sb.crontab())
            self.assertEqual(len(_lines(sb, moved)), 2, sb.crontab())
            self.assertNotIn(f'ARC_WORKSPACE="{alice}"', sb.crontab())

    def test_symlinked_spelling_of_the_same_workspace_is_not_a_second_workspace(self):
        with Sandbox() as sb:
            alice = _ws(sb, "alice")
            link = sb.root / "alice-link"
            link.symlink_to(alice)
            self.assertSucceeded(self._install(sb, "--workspace", str(alice)))
            self.assertSucceeded(self._install(sb, "--workspace", str(link)))
            self.assertEqual(len(self._sync_lines(sb)), 2, sb.crontab())

    def test_another_existing_workspace_is_still_kept(self):
        with Sandbox() as sb:
            alice, bob = _ws(sb, "alice"), _ws(sb, "bob")
            self.assertSucceeded(self._install(sb, "--workspace", str(alice)))
            self.assertSucceeded(self._install(sb, "--workspace", str(bob)))
            self.assertEqual(len(_lines(sb, alice)), 2, sb.crontab())
            self.assertEqual(len(_lines(sb, bob)), 2, sb.crontab())

    def test_copied_workspace_reinstall_prints_info_and_keeps_both(self):
        """Défaut verrouillé : l'ancienne copie d'un workspace gardait sa planification SANS un mot -> double sync muette."""
        with Sandbox() as sb:
            alice = _ws(sb, "alice")
            self.assertSucceeded(self._install(sb, "--workspace", str(alice)))
            copy = sb.root / "alice-copie"
            shutil.copytree(alice, copy, symlinks=True)
            proc = self._install(sb, "--workspace", str(copy))
            self.assertSucceeded(proc)
            self.assertEqual(len(_lines(sb, alice)), 2, sb.crontab())
            self.assertEqual(len(_lines(sb, copy)), 2, sb.crontab())
            self.assertOutputContains(proc, "ancienne copie de vos données")
            self.assertOutputContains(proc, "crontab -e")


class TestMigrationAndLegacyPlistLaunchd(InstallAsserts):
    def _install(self, sb, *args):
        return sb.install("--no-auth", "--daily-sync", *args, ARC_FAKE_UNAME="Darwin")

    def _plists(self, sb):
        return sorted((sb.home / "Library/LaunchAgents").glob("com.ai-running-coach.daily-sync*.plist"))

    def test_merged_install_then_workspace_leaves_a_single_plist(self):
        """Défaut verrouillé : le plist de la racine du moteur restait, le nouveau workspace recevait un second label."""
        with Sandbox() as sb:
            alice = _ws(sb, "alice")
            self.assertSucceeded(self._install(sb))
            self.assertSucceeded(self._install(sb, "--workspace", str(alice)))
            plists = self._plists(sb)
            self.assertEqual([p.name for p in plists], ["com.ai-running-coach.daily-sync.plist"], plists)
            self.assertIn(f"<key>ARC_WORKSPACE</key><string>{alice}</string>", plists[0].read_text())

    def test_copied_workspace_reinstall_prints_info_and_keeps_both_plists(self):
        """Défaut verrouillé : l'ancienne copie d'un workspace gardait son LaunchAgent sans un mot."""
        with Sandbox() as sb:
            alice = _ws(sb, "alice")
            self.assertSucceeded(self._install(sb, "--workspace", str(alice)))
            copy = sb.root / "alice-copie"
            shutil.copytree(alice, copy, symlinks=True)
            proc = self._install(sb, "--workspace", str(copy))
            self.assertSucceeded(proc)
            self.assertEqual(len(self._plists(sb)), 2, self._plists(sb))
            self.assertOutputContains(proc, "ancienne copie de vos données")
            self.assertOutputContains(proc, "launchctl bootout")

    def test_plist_without_arc_workspace_counts_as_this_workspaces(self):
        """Défaut verrouillé : un plist écrit avant ARC_WORKSPACE (pas d'EnvironmentVariables) n'était à personne
        -> second LaunchAgent -> double sync. Même règle que la ligne cron sans ARC_WORKSPACE."""
        with Sandbox() as sb:
            alice = _ws(sb, "alice")
            legacy = sb.home / LEGACY_PLIST
            legacy.parent.mkdir(parents=True)
            legacy.write_text('<?xml version="1.0"?><plist version="1.0"><dict><key>Label</key>'
                              '<string>com.ai-running-coach.daily-sync</string></dict></plist>\n')
            self.assertSucceeded(self._install(sb, "--workspace", str(alice)))
            plists = self._plists(sb)
            self.assertEqual(len(plists), 1, plists)
            self.assertIn(f"<key>ARC_WORKSPACE</key><string>{alice}</string>", plists[0].read_text())

    def test_moved_workspace_retires_the_stale_suffixed_plist(self):
        with Sandbox() as sb:
            alice, bob = _ws(sb, "alice"), _ws(sb, "bob")
            self.assertSucceeded(self._install(sb, "--workspace", str(alice)))
            self.assertSucceeded(self._install(sb, "--workspace", str(bob)))
            moved = sb.root / "bob-moved"
            bob.rename(moved)
            self.assertSucceeded(self._install(sb, "--workspace", str(moved)))
            plists = self._plists(sb)
            self.assertEqual(len(plists), 2, plists)
            texts = "".join(p.read_text() for p in plists)
            self.assertIn(f"<string>{moved}</string>", texts)
            self.assertNotIn(f"<string>{bob}</string>", texts)
            self.assertIn(f"<string>{alice}</string>", texts)


class TestGarminTokensWithLeanproxy(InstallAsserts):
    def test_explicit_combination_is_refused(self):
        """Défaut verrouillé : accepté mais cassé (la passerelle lit ~/.garminconnect, valeur non écrite)."""
        with Sandbox() as sb:
            ws = _ws(sb, "alice")
            self.assertFailed(sb.install("--workspace", str(ws), "--garmin-tokens", str(sb.root / "t"),
                                         "--use-leanproxy", "--no-auth"),
                              "incompatibles avec le mode passerelle")

    def test_remembered_tokens_then_leanproxy_is_refused(self):
        with Sandbox() as sb:
            ws = _ws(sb, "alice")
            self.assertSucceeded(sb.install("--workspace", str(ws), "--garmin-tokens", str(sb.root / "t"), "--no-auth"))
            self.assertFailed(sb.install("--workspace", str(ws), "--use-leanproxy", "--no-auth"),
                              "incompatibles avec le mode passerelle")


class TestDoctorDailySyncOwnership(InstallAsserts):
    """Défaut verrouillé : repli « rien ne correspond et au plus un ARC_WORKSPACE déclaré -> tout est à nous » :
    `--check daily_sync_scheduled --workspace B` répondait OK alors que seul A était planifié."""

    def _check(self, sb, ws, uname):
        proc = sb.script("coach_doctor.py", "--check", "daily_sync_scheduled", "--json", "--workspace", str(ws),
                         ARC_FAKE_UNAME=uname)
        return json.loads(proc.stdout)["checks"][0]["status"]

    def test_cron_only_a_scheduled(self):
        with Sandbox() as sb:
            alice, bob = _ws(sb, "alice"), _ws(sb, "bob")
            sb.set_crontab(f'0 6 * * * ARC_WORKSPACE="{alice}" "/e/daily-sync.sh" >/dev/null 2>&1 {LEGACY_MARKER}\n')
            self.assertEqual(self._check(sb, alice, "Linux"), "ok")
            self.assertNotEqual(self._check(sb, bob, "Linux"), "ok")

    def test_cron_vanished_declared_directory_is_an_orphan_not_ours(self):
        """Défaut verrouillé (nit N5) : un dossier déclaré disparu était réputé « le nôtre » -> B rapporté planifié
        alors que la seule ligne vise un dossier supprimé. Remplace l'ancien test « tolerated »."""
        with Sandbox() as sb:
            bob = _ws(sb, "bob")
            sb.set_crontab(f'0 6 * * * ARC_WORKSPACE="{sb.root}/gone" "/e/daily-sync.sh" >/dev/null 2>&1 {LEGACY_MARKER}\n')
            proc = sb.script("coach_doctor.py", "--check", "daily_sync_scheduled", "--json", "--workspace", str(bob),
                             ARC_FAKE_UNAME="Linux")
            check = json.loads(proc.stdout)["checks"][0]
            self.assertEqual(check["status"], "info")
            self.assertIn("orpheline", check["message"])

    def test_launchd_only_a_scheduled(self):
        with Sandbox() as sb:
            alice, bob = _ws(sb, "alice"), _ws(sb, "bob")
            plist = sb.home / LEGACY_PLIST
            plist.parent.mkdir(parents=True)
            plist.write_text(f"<plist><dict><key>EnvironmentVariables</key><dict><key>ARC_WORKSPACE</key>"
                             f"<string>{alice}</string></dict></dict></plist>")
            self.assertEqual(self._check(sb, alice, "Darwin"), "ok")
            self.assertNotEqual(self._check(sb, bob, "Darwin"), "ok")


class TestCredentialDirsSurviveASourceRoundTrip(InstallAsserts):
    """Défaut verrouillé : le dossier propre n'était mémorisé que par l'entrée garmin du .mcp.json, perdue
    avec garmin -> intervals -> garmin."""

    def test_garmin_tokens(self):
        with Sandbox() as sb:
            ws, tokens = _ws(sb, "alice"), sb.root / "tokens-alice"
            self.assertSucceeded(sb.install("--workspace", str(ws), "--garmin-tokens", str(tokens), "--no-auth"))
            self.assertSucceeded(sb.install("--workspace", str(ws), "--source", "intervals", "--no-auth"))
            self.assertSucceeded(sb.install("--workspace", str(ws), "--source", "garmin", "--no-auth"))
            self.assertEqual(_mcp(ws)["mcpServers"]["garmin"]["env"]["GARMINTOKENS"], str(tokens))
            toml = (ws / "config/workspace.user.toml").read_text()
            self.assertIn("[credentials]", toml)
            self.assertIn('source = "garmin"', toml)          # les autres clés de l'utilisateur sont intactes

    def test_intervals_dir(self):
        with Sandbox() as sb:
            ws, icu = _ws(sb, "alice"), sb.root / "icu-alice"
            self.assertSucceeded(sb.install("--workspace", str(ws), "--source", "intervals",
                                            "--intervals-dir", str(icu), "--no-auth"))
            self.assertSucceeded(sb.install("--workspace", str(ws), "--source", "garmin", "--no-auth"))
            self.assertSucceeded(sb.install("--workspace", str(ws), "--source", "intervals", "--no-auth"))
            self.assertEqual(_mcp(ws)["mcpServers"]["intervals"]["command"], f"{icu}/run.sh")

    def test_default_install_writes_no_credentials_section(self):
        with Sandbox() as sb:
            ws = _ws(sb, "solo")
            self.assertSucceeded(sb.install("--workspace", str(ws), "--no-auth"))
            self.assertNotIn("[credentials]", (ws / "config/workspace.user.toml").read_text())


class TestOpencodeProjectConfig(InstallAsserts):
    """Défaut verrouillé : l'avertissement affirmait « OpenCode lit le .mcp.json du projet » ; OpenCode lit
    opencode.json (global fusionné avec celui de la racine du projet), si bien que l'entrée propre au workspace
    n'existait nulle part."""

    def test_project_level_opencode_json_carries_the_workspace_tokens_and_keeps_user_keys(self):
        with Sandbox() as sb:
            ws, tokens = _ws(sb, "alice"), sb.root / "tokens-alice"
            (ws / "opencode.json").write_text(json.dumps({"theme": "mine", "mcp": {"other": {"type": "local"}}}))
            global_cfg = sb.home / ".config/opencode/opencode.json"
            self.assertSucceeded(sb.install("--workspace", str(ws), "--garmin-tokens", str(tokens), "--no-auth"))
            cfg = json.loads((ws / "opencode.json").read_text())
            self.assertEqual(cfg["theme"], "mine")
            self.assertIn("other", cfg["mcp"])
            self.assertEqual(cfg["mcp"]["garmin"]["environment"]["GARMINTOKENS"], str(tokens))
            self.assertFalse(global_cfg.exists())
            self.assertIn("/opencode.json", (ws / ".gitignore").read_text().splitlines())

    def test_default_install_writes_no_project_opencode_json(self):
        with Sandbox() as sb:
            ws = _ws(sb, "solo")
            self.assertSucceeded(sb.install("--workspace", str(ws), "--no-auth"))
            self.assertFalse((ws / "opencode.json").exists())
            self.assertNotIn("opencode.json", (ws / ".gitignore").read_text())
            global_env = json.loads((sb.home / ".config/opencode/opencode.json").read_text())["mcp"]["garmin"]["environment"]
            self.assertEqual(list(global_env), ["GARMIN_ENABLED_TOOLS"])


def _athlete_data(root: Path) -> None:
    (root / "planning").mkdir(parents=True, exist_ok=True)
    (root / "planning" / "Runner_Profile.md").write_text("- Prénom : Alice\n", encoding="utf-8")


class TestFamilyAdditionKeepsTheEngineRootSchedule(InstallAsserts):
    """Défaut verrouillé (N1) : installation fusionnée de A (workspace = racine du moteur) puis ajout de B avec
    --workspace : la planification de A était réputée « migrée » -> lignes cron retirées (Linux), plist historique
    réécrit pour B en silence (Darwin). Migration d'une même personne et ajout d'un membre se ressemblent : tant
    que la racine porte des données, c'est celle d'un autre ; --replace-schedule force le remplacement."""

    def _linux(self, sb, *args):
        return sb.install("--no-auth", "--daily-sync", *args, ARC_FAKE_UNAME="Linux")

    def _darwin(self, sb, *args):
        return sb.install("--no-auth", "--daily-sync", *args, ARC_FAKE_UNAME="Darwin")

    def _engine_lines(self, sb):
        return [l for l in sb.crontab().splitlines() if f'ARC_WORKSPACE="{sb.repo}"' in l]

    def _plists(self, sb):
        return sorted((sb.home / "Library/LaunchAgents").glob("com.ai-running-coach.daily-sync*.plist"))

    # -- Linux -----------------------------------------------------------------------------------------------
    def test_cron_merged_member_then_second_member_keeps_both(self):
        with Sandbox() as sb:
            bob = _ws(sb, "bob")
            self.assertSucceeded(self._linux(sb))
            _athlete_data(sb.repo)
            before = self._engine_lines(sb)
            self.assertEqual(len(before), 2)
            proc = self._linux(sb, "--workspace", str(bob))
            self.assertSucceeded(proc)
            self.assertEqual(self._engine_lines(sb), before, sb.crontab())
            self.assertEqual(len(_lines(sb, bob)), 2, sb.crontab())
            self.assertTrue(all("[bob-" in l for l in _lines(sb, bob)), sb.crontab())
            self.assertOutputContains(proc, "--replace-schedule")
            self.assertOutputContains(proc, "RACINE DU MOTEUR CONSERVÉE")

    def test_cron_migration_without_the_flag_keeps_both_and_warns(self):
        with Sandbox() as sb:
            alice = _ws(sb, "alice")
            self.assertSucceeded(self._linux(sb))
            _athlete_data(sb.repo)
            proc = self._linux(sb, "--workspace", str(alice))
            self.assertSucceeded(proc)
            self.assertEqual(len(self._engine_lines(sb)), 2, sb.crontab())
            self.assertEqual(len(_lines(sb, alice)), 2, sb.crontab())
            self.assertOutputContains(proc, "--replace-schedule")

    def test_cron_migration_with_the_flag_replaces_the_engine_root_lines(self):
        with Sandbox() as sb:
            alice = _ws(sb, "alice")
            self.assertSucceeded(self._linux(sb))
            _athlete_data(sb.repo)
            proc = self._linux(sb, "--workspace", str(alice), "--replace-schedule")
            self.assertSucceeded(proc)
            self.assertEqual(self._engine_lines(sb), [], sb.crontab())
            self.assertEqual(len(_lines(sb, alice)), 2, sb.crontab())
            self.assertOutputContains(proc, "périmée")

    def test_cron_engine_root_emptied_of_athlete_data_is_replaced_automatically(self):
        with Sandbox() as sb:
            alice = _ws(sb, "alice")
            self.assertSucceeded(self._linux(sb))
            (sb.repo / "activities").mkdir(exist_ok=True)                     # dossier vide : pas de donnée
            proc = self._linux(sb, "--workspace", str(alice))
            self.assertSucceeded(proc)
            self.assertEqual(self._engine_lines(sb), [], sb.crontab())
            self.assertEqual(len(_lines(sb, alice)), 2, sb.crontab())

    def test_a_single_activity_journal_counts_as_athlete_data(self):
        with Sandbox() as sb:
            alice = _ws(sb, "alice")
            self.assertSucceeded(self._linux(sb))
            (sb.repo / "activities").mkdir(exist_ok=True)
            (sb.repo / "activities" / "2026-01-01_running.md").write_text("x\n", encoding="utf-8")
            self.assertSucceeded(self._linux(sb, "--workspace", str(alice)))
            self.assertEqual(len(self._engine_lines(sb)), 2, sb.crontab())

    def test_the_replace_flag_is_not_remembered_for_updates(self):
        with Sandbox() as sb:
            alice = _ws(sb, "alice")
            self.assertSucceeded(self._linux(sb, "--workspace", str(alice), "--replace-schedule"))
            remembered = (sb.home / ".config/ai-running-coach/install-args").read_text(encoding="utf-8")
            self.assertNotIn("--replace-schedule", remembered)

    # -- Darwin ----------------------------------------------------------------------------------------------
    def test_launchd_merged_member_then_second_member_never_touches_the_legacy_plist(self):
        with Sandbox() as sb:
            bob = _ws(sb, "bob")
            self.assertSucceeded(self._darwin(sb))
            _athlete_data(sb.repo)
            legacy = sb.home / LEGACY_PLIST
            before = legacy.read_text()
            proc = self._darwin(sb, "--workspace", str(bob))
            self.assertSucceeded(proc)
            self.assertEqual(legacy.read_text(), before)
            self.assertIn(f"<string>{sb.repo}</string>", before)
            suffixed = sorted((sb.home / "Library/LaunchAgents").glob("com.ai-running-coach.daily-sync.bob-*.plist"))
            self.assertEqual(len(suffixed), 1, self._plists(sb))
            self.assertIn(f"<string>{bob}</string>", suffixed[0].read_text())
            self.assertOutputContains(proc, "--replace-schedule")

    def test_launchd_migration_with_the_flag_replaces_the_legacy_plist(self):
        with Sandbox() as sb:
            alice = _ws(sb, "alice")
            self.assertSucceeded(self._darwin(sb))
            _athlete_data(sb.repo)
            self.assertSucceeded(self._darwin(sb, "--workspace", str(alice), "--replace-schedule"))
            plists = self._plists(sb)
            self.assertEqual([p.name for p in plists], ["com.ai-running-coach.daily-sync.plist"], plists)
            self.assertIn(f"<string>{alice}</string>", plists[0].read_text())
            backups = list((sb.home / ".config/ai-running-coach").glob("launchagent-*.bak"))
            self.assertEqual(len(backups), 1, backups)
            self.assertIn(f"<string>{sb.repo}</string>", backups[0].read_text())

    def test_launchd_engine_root_emptied_of_athlete_data_is_replaced_automatically(self):
        with Sandbox() as sb:
            alice = _ws(sb, "alice")
            self.assertSucceeded(self._darwin(sb))
            self.assertSucceeded(self._darwin(sb, "--workspace", str(alice)))
            self.assertEqual(len(self._plists(sb)), 1, self._plists(sb))


class TestUnavailableWorkspaceSchedule(InstallAsserts):
    """Défaut verrouillé (N2) : un membre dont le workspace est momentanément indisponible (volume démonté, partage
    réseau, dossier parent renommé) perdait sa planification quand un autre membre réinstallait."""

    def _linux(self, sb, ws):
        return sb.install("--no-auth", "--daily-sync", "--workspace", str(ws), ARC_FAKE_UNAME="Linux")

    def _darwin(self, sb, ws):
        return sb.install("--no-auth", "--daily-sync", "--workspace", str(ws), ARC_FAKE_UNAME="Darwin")

    def _unmounted(self, sb) -> Path:
        return sb.root / "mnt-gone" / "alice"                    # ni le dossier ni son parent n'existent

    def test_cron_missing_parent_keeps_the_line_and_warns(self):
        with Sandbox() as sb:
            bob = _ws(sb, "bob")
            ghost = self._unmounted(sb)
            sb.set_crontab(f'0 6 * * * ARC_WORKSPACE="{ghost}" "/e/daily-sync.sh" >/dev/null 2>&1 {LEGACY_MARKER}\n')
            proc = self._linux(sb, bob)
            self.assertSucceeded(proc)
            self.assertEqual(len(_lines(sb, ghost)), 1, sb.crontab())
            self.assertEqual(len(_lines(sb, bob)), 2, sb.crontab())
            self.assertOutputContains(proc, "volume démonté")

    def test_cron_missing_directory_with_existing_parent_is_replaced_with_a_restore_hint(self):
        with Sandbox() as sb:
            bob = _ws(sb, "bob")
            gone = sb.root / "alice-gone"
            sb.set_crontab(f'0 6 * * * ARC_WORKSPACE="{gone}" "/e/daily-sync.sh" >/dev/null 2>&1 {LEGACY_MARKER}\n')
            proc = self._linux(sb, bob)
            self.assertSucceeded(proc)
            self.assertEqual(_lines(sb, gone), [], sb.crontab())
            self.assertOutputContains(proc, f'./install.sh --daily-sync --workspace "{gone}"')
            self.assertTrue(list((sb.home / ".config/ai-running-coach").glob("crontab-*.bak")))

    def test_launchd_missing_parent_keeps_the_plist_untouched(self):
        with Sandbox() as sb:
            bob = _ws(sb, "bob")
            ghost = self._unmounted(sb)
            legacy = sb.home / LEGACY_PLIST
            legacy.parent.mkdir(parents=True)
            text = (f"<plist><dict><key>Label</key><string>com.ai-running-coach.daily-sync</string>"
                    f"<key>EnvironmentVariables</key><dict><key>ARC_WORKSPACE</key><string>{ghost}</string></dict>"
                    f"</dict></plist>")
            legacy.write_text(text)
            proc = self._darwin(sb, bob)
            self.assertSucceeded(proc)
            self.assertEqual(legacy.read_text(), text)
            self.assertEqual(len(list(legacy.parent.glob("com.ai-running-coach.daily-sync.bob-*.plist"))), 1)
            self.assertOutputContains(proc, "volume démonté")

    def test_launchd_stale_suffixed_plist_is_backed_up_before_removal(self):
        with Sandbox() as sb:
            alice, bob = _ws(sb, "alice"), _ws(sb, "bob")
            self.assertSucceeded(self._darwin(sb, alice))
            self.assertSucceeded(self._darwin(sb, bob))
            moved = sb.root / "bob-moved"
            bob.rename(moved)
            proc = self._darwin(sb, moved)
            self.assertSucceeded(proc)
            backups = list((sb.home / ".config/ai-running-coach").glob("launchagent-*.bak"))
            self.assertEqual(len(backups), 1, backups)
            self.assertIn(f"<string>{bob}</string>", backups[0].read_text())
            self.assertOutputContains(proc, f'./install.sh --daily-sync --workspace "{bob}"')
