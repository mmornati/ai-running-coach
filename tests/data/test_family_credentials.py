"""Palier D — identifiants et sync PAR WORKSPACE (#127, phase 1a).

Deux workspaces fictifs sous le même utilisateur : chacun porte ses jetons Garmin
(`GARMINTOKENS` de son `.mcp.json`) et ses identifiants intervals.icu ; aucun appel réseau
(faux module `garminconnect` injecté dans `sys.modules`). Défaut verrouillé : sans configuration,
le dossier historique, et le verrou `ARC_LOCK_WORKSPACE` ne gêne rien.
"""

from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "skills/fit-download/scripts"))
import arc_credentials as C  # noqa: E402
import coach_config  # noqa: E402
import coach_doctor  # noqa: E402
import coach_setup  # noqa: E402
import download_fit as D  # noqa: E402
import garmin_watch as W  # noqa: E402


def _workspace(root: Path, name: str, tokens: str | None = None, intervals_dir: str | None = None) -> Path:
    ws = root / name
    ws.mkdir()
    servers: dict = {}
    if tokens is not None:
        servers["garmin"] = {"command": "garmin-mcp", "args": ["stdio"],
                             "env": {"GARMIN_ENABLED_TOOLS": "get_stats", "GARMINTOKENS": tokens}}
    if intervals_dir is not None:
        servers["intervals"] = {"command": f"{intervals_dir}/run.sh", "args": []}
    if servers:
        (ws / ".mcp.json").write_text(json.dumps({"mcpServers": servers}), encoding="utf-8")
    return ws


class _EnvCase(unittest.TestCase):
    """Environnement propre : ni GARMINTOKENS, ni GARMIN_TOKENS_DIR, ni verrou, HOME factice."""

    KEYS = ("GARMINTOKENS", "GARMIN_TOKENS_DIR", "ARC_LOCK_WORKSPACE", "ARC_WORKSPACE", "HOME",
            "INTERVALS_ICU_API_KEY")

    def setUp(self):
        self._saved = {k: os.environ.get(k) for k in self.KEYS}
        for k in self.KEYS:
            os.environ.pop(k, None)
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name).resolve()
        os.environ["HOME"] = str(self.root / "home")
        (self.root / "home").mkdir()

    def tearDown(self):
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self._tmp.cleanup()


class TestGarminTokensPrecedence(_EnvCase):
    def test_default_is_the_historical_directory(self):
        ws = _workspace(self.root, "alone")
        path, source = C.garmin_tokens_dir_with_source(None, ws)
        self.assertEqual(path, self.root / "home" / ".garminconnect")
        self.assertEqual(source, C.SOURCE_DEFAULT)

    def test_precedence_chain(self):
        ws = _workspace(self.root, "alice", tokens=str(self.root / "t-mcp"))
        os.environ["GARMINTOKENS"] = str(self.root / "t-env")
        os.environ["GARMIN_TOKENS_DIR"] = str(self.root / "t-project")
        self.assertEqual(C.garmin_tokens_dir(str(self.root / "t-cli"), ws), self.root / "t-cli")
        self.assertEqual(C.garmin_tokens_dir(None, ws), self.root / "t-mcp")
        bare = _workspace(self.root, "bare")
        self.assertEqual(C.garmin_tokens_dir(None, bare), self.root / "t-env")
        del os.environ["GARMINTOKENS"]
        self.assertEqual(C.garmin_tokens_dir(None, bare), self.root / "t-project")

    def test_two_workspaces_resolve_to_two_directories(self):
        """Défaut verrouillé : sans `.mcp.json` par workspace, deux membres partageaient ~/.garminconnect."""
        alice = _workspace(self.root, "alice", tokens=str(self.root / "tokens-alice"))
        bob = _workspace(self.root, "bob", tokens=str(self.root / "tokens-bob"))
        self.assertEqual(C.garmin_tokens_dir(None, alice), self.root / "tokens-alice")
        self.assertEqual(C.garmin_tokens_dir(None, bob), self.root / "tokens-bob")

    def test_doctor_keeps_its_signature_and_delegates(self):
        alice = _workspace(self.root, "alice", tokens=str(self.root / "tokens-alice"))
        self.assertEqual(coach_doctor.resolve_tokens_dir(None, alice), self.root / "tokens-alice")
        self.assertEqual(coach_doctor.resolve_tokens_dir("~/x", alice), Path("~/x").expanduser())

    def test_malformed_mcp_json_falls_back_without_crashing(self):
        ws = self.root / "broken"
        ws.mkdir()
        (ws / ".mcp.json").write_text("{ pas du json", encoding="utf-8")
        self.assertEqual(C.garmin_tokens_dir(None, ws), self.root / "home" / ".garminconnect")


class _FakeGarminModule:
    """Faux `garminconnect` : mémorise le dossier de jetons passé à `login`."""

    logins: list = []

    def __init__(self):
        pass

    def login(self, token_dir=None):
        _FakeGarminModule.logins.append(token_dir)


class TestWatchAndDownloadUseTheWorkspaceTokens(_EnvCase):
    def setUp(self):
        super().setUp()
        _FakeGarminModule.logins = []
        fake = types.ModuleType("garminconnect")
        fake.Garmin = _FakeGarminModule
        self._patch = patch.dict(sys.modules, {"garminconnect": fake})
        self._patch.start()
        self.alice = _workspace(self.root, "alice", tokens=str(self.root / "tokens-alice"))
        self.bob = _workspace(self.root, "bob", tokens=str(self.root / "tokens-bob"))

    def tearDown(self):
        self._patch.stop()
        super().tearDown()

    def test_garmin_watch_logs_in_with_the_tokens_of_its_workspace(self):
        W.make_probe(self.alice)
        W.make_probe(self.bob)
        self.assertEqual(_FakeGarminModule.logins, [str(self.root / "tokens-alice"), str(self.root / "tokens-bob")])

    def test_garmin_watch_without_configuration_keeps_the_default(self):
        W.make_probe(_workspace(self.root, "alone"))
        self.assertEqual(_FakeGarminModule.logins, [str(self.root / "home" / ".garminconnect")])

    def test_garmin_watch_main_passes_its_workspace(self):
        seen = []

        def fake_tick(workspace, now, probe_factory, run_sync, dry_run=False):
            probe_factory()
            seen.append(workspace)
            return {}

        with patch.object(W, "tick", fake_tick), patch.object(W, "_ensure_garminconnect"):
            W.main(["--workspace", str(self.bob), "--dry-run"])
        self.assertEqual(seen, [self.bob])
        self.assertEqual(_FakeGarminModule.logins, [str(self.root / "tokens-bob")])

    def test_download_fit_logs_in_with_the_tokens_of_the_workspace(self):
        for ws, expected in ((self.alice, "tokens-alice"), (self.bob, "tokens-bob")):
            os.environ["ARC_WORKSPACE"] = str(ws)
            _FakeGarminModule.logins = []
            out = self.root / f"out-{expected}"
            counts = {"ok": 0, "unavailable": 0, "skipped": 1, "failed": 0}
            with patch.object(D, "_auto_relaunch"), patch.object(D, "_download_all", return_value=counts), \
                    patch("sys.stdout", io.StringIO()):
                rc = D.main(["--source", "garmin", "--output-dir", str(out), "123"])
            self.assertEqual(rc, 0)
            self.assertEqual(_FakeGarminModule.logins, [str(self.root / expected)])


class TestIntervalsDirPerWorkspace(_EnvCase):
    def test_default_directory(self):
        ws = _workspace(self.root, "alone")
        self.assertEqual(C.intervals_env_dir(ws), self.root / "home/.config/ai-running-coach/intervals-icu-mcp")

    def test_dir_follows_the_wrapper_of_the_workspace_mcp_json(self):
        alice = _workspace(self.root, "alice", intervals_dir=str(self.root / "icu-alice"))
        bob = _workspace(self.root, "bob", intervals_dir=str(self.root / "icu-bob"))
        self.assertEqual(C.intervals_env_dir(alice), self.root / "icu-alice")
        self.assertEqual(C.intervals_env_dir(bob), self.root / "icu-bob")

    def test_opencode_style_command_list(self):
        ws = self.root / "oc"
        ws.mkdir()
        (ws / ".mcp.json").write_text(json.dumps(
            {"mcpServers": {"intervals": {"command": [str(self.root / "icu-oc" / "run.sh")]}}}))
        self.assertEqual(C.intervals_env_dir(ws), self.root / "icu-oc")

    def test_hand_written_command_is_not_mistaken_for_our_wrapper(self):
        ws = self.root / "manual"
        ws.mkdir()
        (ws / ".mcp.json").write_text(json.dumps({"mcpServers": {"intervals": {"command": "uv", "args": ["run"]}}}))
        self.assertEqual(C.intervals_env_dir(ws), self.root / "home/.config/ai-running-coach/intervals-icu-mcp")

    def test_download_fit_reads_the_key_of_its_workspace(self):
        for name in ("alice", "bob"):
            icu = self.root / f"icu-{name}"
            icu.mkdir()
            (icu / ".env").write_text(f"INTERVALS_ICU_API_KEY=key-{name}\n", encoding="utf-8")
        alice = _workspace(self.root, "alice", intervals_dir=str(self.root / "icu-alice"))
        bob = _workspace(self.root, "bob", intervals_dir=str(self.root / "icu-bob"))
        os.environ["ARC_WORKSPACE"] = str(alice)
        self.assertEqual(D._intervals_api_key(), "key-alice")
        os.environ["ARC_WORKSPACE"] = str(bob)
        self.assertEqual(D._intervals_api_key(), "key-bob")


class TestWorkspaceLock(_EnvCase):
    def setUp(self):
        super().setUp()
        self.alice = _workspace(self.root, "alice")
        self.bob = _workspace(self.root, "bob")

    def test_foreign_workspace_is_refused_when_locked(self):
        os.environ.update(ARC_LOCK_WORKSPACE="1", ARC_WORKSPACE=str(self.alice))
        with self.assertRaises(SystemExit) as ctx:
            coach_setup.workspace_root(str(self.bob))
        self.assertIn("workspace refusé", str(ctx.exception))
        self.assertIn(str(self.alice), str(ctx.exception))
        self.assertNotEqual(ctx.exception.code, 0)

    def test_own_workspace_is_accepted_even_through_a_symlink(self):
        link = self.root / "alice-link"
        link.symlink_to(self.alice)
        os.environ.update(ARC_LOCK_WORKSPACE="1", ARC_WORKSPACE=str(self.alice))
        self.assertEqual(coach_setup.workspace_root(str(link)), self.alice)
        self.assertEqual(coach_setup.workspace_root(), self.alice)

    def test_unlocked_behaviour_is_unchanged(self):
        os.environ["ARC_WORKSPACE"] = str(self.alice)
        self.assertEqual(coach_setup.workspace_root(str(self.bob)), self.bob)

    def test_lock_covers_coach_config_which_writes_the_user_toml(self):
        os.environ.update(ARC_LOCK_WORKSPACE="1", ARC_WORKSPACE=str(self.alice))
        with self.assertRaises(SystemExit):
            coach_config.enforce_workspace_lock(str(self.bob))
        self.assertEqual(coach_config.enforce_workspace_lock(str(self.alice)), self.alice)

    def test_lock_without_workspace_fails_closed(self):
        """Verrou posé mais ARC_WORKSPACE vide : refus, jamais un repli sur le pointeur ou le moteur."""
        os.environ["ARC_LOCK_WORKSPACE"] = "1"
        with self.assertRaises(SystemExit) as ctx:
            coach_config.enforce_workspace_lock(str(self.alice))
        self.assertIn("sans ARC_WORKSPACE", str(ctx.exception))
        with self.assertRaises(SystemExit):
            coach_setup.workspace_root()
        with self.assertRaises(SystemExit):
            coach_setup.workspace_root(str(self.alice))

    def test_credentials_entry_point_enforces_the_lock(self):
        os.environ.update(ARC_LOCK_WORKSPACE="1", ARC_WORKSPACE=str(self.alice))
        with self.assertRaises(SystemExit):
            C.main(["garmin-tokens", "--workspace", str(self.bob)])
        with patch("sys.stdout", io.StringIO()) as out:
            self.assertEqual(C.main(["intervals-dir", "--workspace", str(self.alice)]), 0)
        self.assertTrue(out.getvalue().strip())

    def test_locked_tokens_ignore_env_overrides_and_foreign_tokens_dir(self):
        alice = _workspace(self.root, "alice2", tokens=str(self.root / "tokens-alice"))
        os.environ.update(ARC_LOCK_WORKSPACE="1", ARC_WORKSPACE=str(alice),
                          GARMINTOKENS=str(self.root / "tokens-bob"), GARMIN_TOKENS_DIR=str(self.root / "other"))
        path, source = C.garmin_tokens_dir_with_source(str(self.root / "tokens-bob"), alice)
        self.assertEqual(path, self.root / "tokens-alice")
        self.assertEqual(source, C.SOURCE_MCP)
        self.assertEqual(coach_doctor.resolve_tokens_dir(str(self.root / "x"), alice), self.root / "tokens-alice")
        with self.assertRaises(SystemExit):   # le .mcp.json d'un autre workspace n'est pas lisible non plus
            C.garmin_tokens_dir_with_source(None, self.bob)

    def test_locked_tokens_fall_back_to_the_default_not_to_the_environment(self):
        os.environ.update(ARC_LOCK_WORKSPACE="1", ARC_WORKSPACE=str(self.alice), GARMINTOKENS=str(self.root / "env"))
        self.assertEqual(C.garmin_tokens_dir(None, self.alice), self.root / "home" / ".garminconnect")

    def test_scripts_that_built_the_path_themselves_now_refuse_a_foreign_workspace(self):
        import arc_log
        import arc_telegram
        import arc_update_check
        os.environ.update(ARC_LOCK_WORKSPACE="1", ARC_WORKSPACE=str(self.alice))
        with self.assertRaises(SystemExit):
            arc_telegram._workspace(types.SimpleNamespace(workspace=str(self.bob)))
        self.assertEqual(arc_telegram._workspace(types.SimpleNamespace(workspace=str(self.alice))), self.alice)
        payload = self.root / "in.json"
        payload.write_text("{}", encoding="utf-8")
        with self.assertRaises(SystemExit), patch("sys.stderr", io.StringIO()):
            arc_log.main(["--workspace", str(self.bob), "--input", str(payload)])
        with self.assertRaises(SystemExit):
            arc_update_check.main(["--workspace", str(self.bob), "--json"])


class TestDoctorSchedulerDetection(_EnvCase):
    """`daily_sync_scheduled` reconnaît le marqueur historique ET le marqueur suffixé, par workspace."""

    def _cron(self, text: str, workspace: Path):
        completed = types.SimpleNamespace(returncode=0, stdout=text)
        with patch.object(coach_doctor, "_uname", return_value="Linux"), \
                patch.object(coach_doctor.subprocess, "run", return_value=completed):
            return coach_doctor.check_daily_sync(self.root / "home", workspace)

    def test_cron_lines_are_attributed_by_arc_workspace(self):
        alice = _workspace(self.root, "alice")
        bob = _workspace(self.root, "bob")
        crontab = (f'15 7 * * * ARC_WORKSPACE="{alice}" "/e/daily-sync.sh" >/dev/null 2>&1 # ai-running-coach daily-sync\n'
                   f'15 8 * * * ARC_WORKSPACE="{bob}" "/e/daily-sync.sh" >/dev/null 2>&1 '
                   '# ai-running-coach daily-sync [bob-123]\n')
        self.assertEqual(self._cron(crontab, alice)["status"], "ok")
        self.assertEqual(self._cron(crontab, bob)["status"], "ok")
        carol = _workspace(self.root, "carol")
        self.assertEqual(self._cron(crontab, carol)["status"], "info")

    def test_launchd_plists_are_attributed_by_arc_workspace(self):
        alice = _workspace(self.root, "alice")
        bob = _workspace(self.root, "bob")
        agents = self.root / "home/Library/LaunchAgents"
        agents.mkdir(parents=True)

        def plist(ws):
            return f"<dict><key>ARC_WORKSPACE</key><string>{ws}</string></dict>"

        (agents / "com.ai-running-coach.daily-sync.plist").write_text(plist(alice))
        (agents / "com.ai-running-coach.daily-sync.bob-1.plist").write_text(plist(bob))
        with patch.object(coach_doctor, "_uname", return_value="Darwin"):
            self.assertEqual(coach_doctor.check_daily_sync(self.root / "home", alice)["status"], "ok")
            self.assertEqual(coach_doctor.check_daily_sync(self.root / "home", bob)["status"], "ok")
            carol = _workspace(self.root, "carol")
            self.assertEqual(coach_doctor.check_daily_sync(self.root / "home", carol)["status"], "info")


if __name__ == "__main__":
    unittest.main()
