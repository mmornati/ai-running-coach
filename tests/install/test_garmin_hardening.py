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


    def test_base64_token_file_is_tightened_and_symlink_left_alone(self):
        with Sandbox() as sb:
            b64 = sb.home / ".garminconnect_base64"
            b64.write_text("fake-not-a-secret")
            b64.chmod(0o644)
            self.assertSucceeded(sb.install("--no-auth", "--ide", "claude"))
            self.assertEqual(_mode(b64), 0o600)
        with Sandbox() as sb:
            target = sb.root / "elsewhere.txt"
            target.write_text("x")
            target.chmod(0o644)
            (sb.home / ".garminconnect_base64").symlink_to(target)
            self.assertSucceeded(sb.install("--no-auth", "--ide", "claude"))
            self.assertEqual(_mode(target), 0o644)

    def test_custom_garmintokens_dir_from_mcp_json_is_tightened(self):
        with Sandbox() as sb:
            custom = sb.root / "custom-tokens"
            custom.mkdir()
            tok = custom / "garmin_tokens.json"
            tok.write_text("{}")
            tok.chmod(0o644)
            custom.chmod(0o755)
            first = sb.install("--no-auth", "--ide", "claude")
            self.assertSucceeded(first)
            mcp = sb.repo / ".mcp.json"
            data = json.loads(mcp.read_text())
            data["mcpServers"]["garmin"].setdefault("env", {})["GARMINTOKENS"] = str(custom)
            mcp.write_text(json.dumps(data))
            tok.chmod(0o644)
            custom.chmod(0o755)
            self.assertSucceeded(sb.install("--no-auth", "--ide", "claude"))
            self.assertEqual(_mode(custom), 0o700)
            self.assertEqual(_mode(tok), 0o600)

    def test_tokens_are_tightened_even_when_source_is_not_garmin(self):
        with Sandbox() as sb:
            d, f = _tokens(sb)
            self.assertSucceeded(sb.install("--source", "intervals", "--no-auth", "--ide", "claude"))
            self.assertEqual(_mode(d), 0o700)
            self.assertEqual(_mode(f), 0o600)
            self.assertEqual(_tool_installs_for(sb, "garmin"), [])

    def test_ok_message_does_not_overclaim(self):
        with Sandbox() as sb:
            _tokens(sb)
            proc = sb.install("--no-auth", "--ide", "claude")
            self.assertOutputContains(proc, "accès réservé au propriétaire")
            self.assertOutputLacks(proc, "fichiers 600")


def _tool_installs_for(sb, name):
    return [a for _, a in sb.stub_calls("uv") if a.startswith("tool install") and name in a]


class TestDailySyncTokenHook(InstallAsserts):
    def _run(self, sb, **env):
        fake_bin = sb.root / "fake-claude-bin"
        fake_bin.mkdir(exist_ok=True)
        fake = fake_bin / "claude"
        fake.write_text("#!/usr/bin/env bash\necho ok\nexit 0\n")
        fake.chmod(0o755)
        path = f"{fake_bin}:{STUBS_DIR}:{os.environ.get('PATH', '')}"
        return sb.script("daily-sync.sh", PATH=path, **env)

    def test_hook_tightens_a_world_readable_token_file(self):
        with Sandbox() as sb:
            d, f = _tokens(sb)
            b64 = sb.home / ".garminconnect_base64"
            b64.write_text("x")
            b64.chmod(0o644)
            self.assertSucceeded(self._run(sb))
            self.assertEqual(_mode(f), 0o600)
            self.assertEqual(_mode(d), 0o700)
            self.assertEqual(_mode(b64), 0o600)

    def test_missing_dir_is_silent_and_exit_status_unaffected(self):
        with Sandbox() as sb:
            with_dir = self._run(sb)
            self.assertFalse((sb.home / ".garminconnect").exists())
            self.assertSucceeded(with_dir)
            self.assertOutputLacks(with_dir, "chmod")
            _tokens(sb)
            again = self._run(sb)
            self.assertEqual(with_dir.returncode, again.returncode)


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

    def test_non_object_direct_url_json_never_fails_the_install(self):
        with Sandbox() as sb:
            url, _ = _pinned(sb)
            path = _fake_tool(sb, url, OLD_COMMIT)
            for meta in (sb.home / ".local/share/uv/tools/garmin-mcp").rglob("direct_url.json"):
                meta.write_text("[]")
            proc = self._install(sb, path)
            self.assertSucceeded(proc)
            self.assertEqual(_tool_installs(sb), [])
            self.assertOutputContains(proc, "illisible")

    def test_reinstall_message_names_the_project_pin(self):
        with Sandbox() as sb:
            url, _ = _pinned(sb)
            path = _fake_tool(sb, url, OLD_COMMIT)
            proc = self._install(sb, path)
            self.assertOutputContains(proc, "au commit épinglé du projet")

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
            self.assertEqual(check["fix"], "chmod 700 ~/.garminconnect && find ~/.garminconnect -type f -exec chmod 600 {} +")
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


    def test_symlinked_dir_is_info_not_a_non_directory(self):
        with Sandbox() as sb:
            real, _ = _tokens(sb, 0o755, 0o644)
            link = sb.root / "link-tokens"
            link.symlink_to(real)
            check = _doctor(sb, "garmin_token_perms", link)[1]
            self.assertEqual(check["status"], "info")
            self.assertIn("lien symbolique", check["message"])
            self.assertNotIn("n'est pas un dossier", check["message"])

    def test_base64_file_is_checked_and_fix_follows_resolved_dir(self):
        with Sandbox() as sb:
            d, _ = _tokens(sb, 0o700, 0o600)
            b64 = sb.home / ".garminconnect_base64"
            b64.write_text("x")
            b64.chmod(0o644)
            check = _doctor(sb, "garmin_token_perms", d)[1]
            self.assertEqual(check["status"], "warning")
            self.assertIn(".garminconnect_base64", check["message"])
            self.assertIn("chmod 600 ~/.garminconnect_base64", check["fix"])
        with Sandbox() as sb:
            custom = sb.root / "custom tokens"
            custom.mkdir()
            (custom / "garmin_tokens.json").write_text("{}")
            (custom / "garmin_tokens.json").chmod(0o644)
            custom.chmod(0o755)
            check = _doctor(sb, "garmin_token_perms", custom)[1]
            self.assertIn(f"'{custom}'", check["fix"])
            self.assertNotIn("~/.garminconnect ", check["fix"])


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
