"""Palier A — durcissement Garmin : droits des jetons (GHSA-wjhr-76vg-2hvc) et pin garmin-mcp appliqué.

`install.sh` resserre `~/.garminconnect` (dossier 700, fichiers 600), réinstalle garmin-mcp au
commit épinglé quand l'installation en place n'y est pas (comme pour intervals-icu-mcp, #165) et
`coach_doctor.py` le contrôle (checks `garmin_token_perms` et `garmin_mcp_pin`). Tout se passe dans
le bac à sable : jamais le vrai HOME, `uv` est un stub qui journalise ses appels.
"""

from __future__ import annotations

import json
import os
import re
import stat

from tests.lib.asserts import InstallAsserts
from tests.lib.sandbox import STUBS_DIR, Sandbox

OLD_COMMIT = "a" * 40


def _pinned(sb):
    text = (sb.repo / "install.sh").read_text(encoding="utf-8")
    return re.search(r'^GARMIN_MCP_REF="git\+([^@"]+)@([0-9a-f]{40})"', text, re.MULTILINE).groups()


def _fake_tool(sb, url, commit):
    """Faux environnement `uv tool` de garmin-mcp ; retourne le PATH qui le place devant le stub."""
    env = sb.home / ".local/share/uv/tools/garmin-mcp"
    (env / "bin").mkdir(parents=True)
    exe = env / "bin/garmin-mcp"
    exe.write_text("#!/bin/sh\nexit 0\n")
    exe.chmod(0o755)
    py = env / "bin/python3"
    py.write_text("#!/bin/sh\nexit 0\n")
    py.chmod(0o755)
    dist = env / "lib/python3.12/site-packages/garmin_mcp-0.1.0.dist-info"
    dist.mkdir(parents=True)
    (dist / "direct_url.json").write_text(json.dumps({"url": url, "vcs_info": {"vcs": "git", "commit_id": commit}}))
    link_dir = sb.home / ".local/bin"
    link_dir.mkdir(parents=True, exist_ok=True)
    (link_dir / "garmin-mcp").symlink_to(exe)
    return f"{link_dir}:{STUBS_DIR}:{os.environ.get('PATH', '')}"


def _tokens(sb, dir_mode=0o755, file_mode=0o644):
    d = sb.home / ".garminconnect"
    d.mkdir(exist_ok=True)
    f = d / "garmin_tokens.json"
    f.write_text(json.dumps({"di_refresh_token": "fake-not-a-secret"}))
    f.chmod(file_mode)
    d.chmod(dir_mode)
    return d, f


def _mode(path):
    return stat.S_IMODE(path.stat().st_mode)


def _tool_installs(sb):
    return [args for _, args in sb.stub_calls("uv") if args.startswith("tool install")]


class TestGarminTokenPermsInstall(InstallAsserts):
    def test_rerun_tightens_dir_and_files(self):
        with Sandbox() as sb:
            d, f = _tokens(sb)
            other = d / "extra.json"
            other.write_text("{}")
            other.chmod(0o664)
            proc = sb.install("--no-auth", "--ide", "claude")
            self.assertSucceeded(proc)
            self.assertEqual(_mode(d), 0o700)
            self.assertEqual(_mode(f), 0o600)
            self.assertEqual(_mode(other), 0o600)
            self.assertNotIn("fake-not-a-secret", proc.stdout + proc.stderr)

    def test_never_loosens_and_leaves_symlink_targets_alone(self):
        with Sandbox() as sb:
            d, f = _tokens(sb, 0o700, 0o400)
            outside = sb.root / "outside.txt"
            outside.write_text("x")
            outside.chmod(0o644)
            (d / "link").symlink_to(outside)
            self.assertSucceeded(sb.install("--no-auth", "--ide", "claude"))
            self.assertEqual(_mode(f), 0o400)             # seuls les droits groupe/autres sont retirés
            self.assertEqual(_mode(outside), 0o644)       # jamais de suivi hors du dossier

    def test_dry_run_changes_nothing(self):
        with Sandbox() as sb:
            d, f = _tokens(sb)
            proc = sb.install("--dry-run", "--no-auth", "--ide", "claude")
            self.assertSucceeded(proc)
            self.assertEqual(_mode(d), 0o755)
            self.assertEqual(_mode(f), 0o644)
            self.assertOutputContains(proc, "resserrage des droits")

    def test_no_tokens_dir_is_a_noop(self):
        with Sandbox() as sb:
            self.assertSucceeded(sb.install("--no-auth", "--ide", "claude"))
            self.assertFalse((sb.home / ".garminconnect").exists())


class TestGarminPinUpgrade(InstallAsserts):
    def _install(self, sb, path, **env):
        return sb.install("--no-auth", "--ide", "claude", PATH=path, **env)

    def test_unpinned_install_is_reinstalled_at_the_pin_and_tokens_kept(self):
        with Sandbox() as sb:
            url, sha = _pinned(sb)
            path = _fake_tool(sb, url, OLD_COMMIT)
            d, f = _tokens(sb)
            before = f.read_text()
            self.assertSucceeded(self._install(sb, path))
            installs = _tool_installs(sb)
            self.assertEqual(len(installs), 1, installs)
            self.assertIn("--force", installs[0])
            self.assertIn(f"{url}@{sha}", installs[0])
            self.assertEqual(f.read_text(), before)

    def test_dot_git_origin_counts_as_upstream(self):
        with Sandbox() as sb:
            url, _ = _pinned(sb)
            path = _fake_tool(sb, url + ".git", OLD_COMMIT)
            self.assertSucceeded(self._install(sb, path))
            self.assertEqual(len(_tool_installs(sb)), 1)

    def test_installation_at_the_pin_is_left_alone(self):
        with Sandbox() as sb:
            url, sha = _pinned(sb)
            path = _fake_tool(sb, url, sha)
            self.assertSucceeded(self._install(sb, path))
            self.assertEqual(_tool_installs(sb), [])

    def test_custom_origin_is_never_overwritten(self):
        with Sandbox() as sb:
            path = _fake_tool(sb, "https://example.org/my-garmin-fork", "2" * 40)
            proc = self._install(sb, path)
            self.assertSucceeded(proc)
            self.assertEqual(_tool_installs(sb), [])
            self.assertOutputContains(proc, "origine personnalisée")

    def test_unreadable_origin_is_never_reinstalled(self):
        with Sandbox() as sb:
            url, _ = _pinned(sb)
            path = _fake_tool(sb, url, OLD_COMMIT)
            for meta in (sb.home / ".local/share/uv/tools/garmin-mcp").rglob("direct_url.json"):
                meta.write_text("{pas du json")
            proc = self._install(sb, path)
            self.assertSucceeded(proc)
            self.assertEqual(_tool_installs(sb), [])
            self.assertOutputContains(proc, "illisible")

    def test_failed_reinstall_is_only_a_warning(self):
        with Sandbox() as sb:
            url, _ = _pinned(sb)
            path = _fake_tool(sb, url, OLD_COMMIT)
            proc = self._install(sb, path, ARC_STUB_FAIL="uv")
            self.assertSucceeded(proc)
            self.assertOutputContains(proc, "ancienne version reste en place")


def _doctor(sb, check, tokens_dir, source=None):
    if source:
        (sb.repo / "config").mkdir(exist_ok=True)
        (sb.repo / "config/workspace.user.toml").write_text(f'[data]\nsource = "{source}"\n')
    proc = sb.script("coach_doctor.py", "--json", "--workspace", str(sb.repo),
                     "--tokens-dir", str(tokens_dir), "--check", check)
    return proc, next(c for c in json.loads(proc.stdout)["checks"] if c["id"] == check)


class TestGarminTokenPermsDoctor(InstallAsserts):
    def test_group_other_readable_is_a_warning_with_fix_and_no_secret(self):
        with Sandbox() as sb:
            d, _ = _tokens(sb, 0o755, 0o644)
            proc, check = _doctor(sb, "garmin_token_perms", d)
            self.assertEqual(check["status"], "warning")
            self.assertEqual(check["fix"], "chmod 700 ~/.garminconnect && chmod 600 ~/.garminconnect/*")
            self.assertNotIn("fake-not-a-secret", proc.stdout)

    def test_only_a_file_open_is_a_warning(self):
        with Sandbox() as sb:
            d, _ = _tokens(sb, 0o700, 0o640)
            self.assertEqual(_doctor(sb, "garmin_token_perms", d)[1]["status"], "warning")

    def test_restricted_is_ok(self):
        with Sandbox() as sb:
            d, _ = _tokens(sb, 0o700, 0o600)
            self.assertEqual(_doctor(sb, "garmin_token_perms", d)[1]["status"], "ok")

    def test_missing_dir_is_info(self):
        with Sandbox() as sb:
            self.assertEqual(_doctor(sb, "garmin_token_perms", sb.home / ".garminconnect")[1]["status"], "info")

    def test_other_source_is_info(self):
        with Sandbox() as sb:
            d, _ = _tokens(sb)
            self.assertEqual(_doctor(sb, "garmin_token_perms", d, source="intervals")[1]["status"], "info")


class TestGarminMcpPinDoctor(InstallAsserts):
    def _check(self, sb, url, commit, source=None):
        _fake_tool(sb, url, commit)
        d, _ = _tokens(sb, 0o700, 0o600)
        return _doctor(sb, "garmin_mcp_pin", d, source)

    def test_at_pin_is_ok(self):
        with Sandbox() as sb:
            url, sha = _pinned(sb)
            self.assertEqual(self._check(sb, url, sha)[1]["status"], "ok")

    def test_other_commit_is_a_warning_with_force_fix(self):
        with Sandbox() as sb:
            url, sha = _pinned(sb)
            proc, check = self._check(sb, url, OLD_COMMIT)
            self.assertSucceeded(proc)
            self.assertEqual(check["status"], "warning")
            self.assertIn("--force", check["fix"])
            self.assertIn(sha, check["fix"])
            self.assertIn("sécurité", check["message"])

    def test_custom_origin_is_info(self):
        with Sandbox() as sb:
            self.assertEqual(self._check(sb, "https://example.org/fork", "2" * 40)[1]["status"], "info")

    def test_unreadable_origin_is_info(self):
        with Sandbox() as sb:
            url, _ = _pinned(sb)
            _fake_tool(sb, url, OLD_COMMIT)
            for meta in (sb.home / ".local/share/uv/tools/garmin-mcp").rglob("direct_url.json"):
                meta.write_text("{pas du json")
            d, _ = _tokens(sb, 0o700, 0o600)
            self.assertEqual(_doctor(sb, "garmin_mcp_pin", d)[1]["status"], "info")

    def test_other_source_is_info(self):
        with Sandbox() as sb:
            url, _ = _pinned(sb)
            self.assertEqual(self._check(sb, url, OLD_COMMIT, source="strava")[1]["status"], "info")
