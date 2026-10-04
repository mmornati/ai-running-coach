"""Palier A — source de données `--source garmin|intervals` (#68).

Critère d'acceptation de la story : AUCUN comportement Garmin modifié quand
la source reste `garmin` (le défaut, jamais configuré). Ces tests verrouillent
en particulier (revue PR #116) :

  - une installation Garmin par défaut n'écrit JAMAIS de section `[data]`
    dans `workspace.user.toml` (persist_source() ne s'exécute que si
    `--source` a été passé explicitement) ;
  - un rerun SANS `--source` ne fait jamais revenir un athlète Intervals.icu
    vers Garmin (resolve_source() relit la config existante, comme
    resolve_agents() pour `[agents].enabled`) ;
  - `--source intervals` enregistre le WRAPPER (`run.sh`), jamais le binaire
    `intervals-icu-mcp` directement, et jamais de bloc `env` avec un secret ;
  - `--use-leanproxy` + `--source intervals` est rejeté (leanproxy ne route
    que garmin) ;
  - `--dry-run` n'écrit rien ;
  - changer de source retire l'entrée MCP de l'ANCIENNE source (elle ne doit
    jamais apparaître deux fois dans la config d'un même IDE).
"""

from __future__ import annotations

import json
import os

from tests.lib.asserts import InstallAsserts
from tests.lib.sandbox import STUBS_DIR, Sandbox


def _mcp_servers(sb: Sandbox) -> dict:
    cfg = sb.repo / ".mcp.json"
    if not cfg.is_file():
        return {}
    return json.loads(cfg.read_text()).get("mcpServers", {})


def _source(sb: Sandbox) -> str:
    proc = sb.run([
        "python3", str(sb.repo / "scripts/coach_config.py"), "get",
        "--workspace", str(sb.repo), "--section", "data", "--key", "source",
        "--default", "garmin",
    ])
    return proc.stdout.strip()


class TestDefaultGarminUnchanged(InstallAsserts):
    def test_no_data_section_written_by_default(self):
        with Sandbox() as sb:
            self.assertSucceeded(sb.install("--no-auth", "--ide", "claude"))
            user_toml = sb.repo / "config/workspace.user.toml"
            self.assertIsFile(user_toml)
            self.assertNotIn("[data]", user_toml.read_text(encoding="utf-8"))

    def test_default_registers_garmin_not_intervals(self):
        with Sandbox() as sb:
            self.assertSucceeded(sb.install("--no-auth", "--ide", "claude"))
            servers = _mcp_servers(sb)
            self.assertIn("garmin", servers)
            self.assertNotIn("intervals", servers)


class TestSourceIntervals(InstallAsserts):
    def test_registers_wrapper_not_the_raw_binary(self):
        with Sandbox() as sb:
            self.assertSucceeded(sb.install("--source", "intervals", "--no-auth", "--ide", "claude"))
            servers = _mcp_servers(sb)
            self.assertIn("intervals", servers)
            self.assertNotIn("garmin", servers)
            command = servers["intervals"]["command"]
            self.assertTrue(command.endswith("intervals-icu-mcp/run.sh"), command)
            self.assertNotIn("env", servers["intervals"], "un secret ne doit jamais être écrit ici")
            wrapper = sb.home / ".config/ai-running-coach/intervals-icu-mcp/run.sh"
            self.assertIsFile(wrapper)
            self.assertTrue(wrapper.stat().st_mode & 0o111, "wrapper non exécutable")

    def test_persists_source_only_when_explicit(self):
        with Sandbox() as sb:
            self.assertSucceeded(sb.install("--source", "intervals", "--no-auth"))
            self.assertEqual(_source(sb), "intervals")

    def test_rerun_without_source_does_not_revert_to_garmin(self):
        with Sandbox() as sb:
            self.assertSucceeded(sb.install("--source", "intervals", "--no-auth", "--ide", "claude"))
            # Deuxième passage SANS --source : ne doit RIEN changer.
            self.assertSucceeded(sb.install("--no-auth", "--ide", "claude"))
            self.assertEqual(_source(sb), "intervals")
            servers = _mcp_servers(sb)
            self.assertIn("intervals", servers)
            self.assertNotIn("garmin", servers)

    def test_leanproxy_rejected_with_intervals_source(self):
        with Sandbox() as sb:
            proc = sb.install("--source", "intervals", "--use-leanproxy", "--no-auth", "--dry-run")
            self.assertFailed(proc, "--use-leanproxy + --source intervals aurait dû être rejeté")
            self.assertOutputContains(proc, "intervals")

    def test_dry_run_writes_nothing(self):
        with Sandbox() as sb:
            self.assertSucceeded(sb.install("--source", "intervals", "--dry-run", "--ide", "claude"))
            self.assertFalse((sb.repo / ".mcp.json").exists())
            self.assertFalse((sb.repo / "config/workspace.user.toml").exists())
            self.assertFalse(
                (sb.home / ".config/ai-running-coach/intervals-icu-mcp/run.sh").exists()
            )


class TestIntervalsPinUpgrade(InstallAsserts):
    """#165 : un simple rerun d'`install.sh --source intervals` met à niveau un serveur installé
    depuis l'ancien dépôt (eddmann) ou un ancien commit — mais jamais une origine personnalisée, et
    jamais rien quand l'installation est déjà au pin. Environnement `uv` simulé : binaire +
    `direct_url.json` du dist-info (la source que lit `install.sh` et `coach_doctor.py`)."""

    LEGACY = ("https://github.com/eddmann/intervals-icu-mcp", "cb91d4a0f3b4dc21f57421e029c07a8e9af11649")
    FORK = "https://github.com/hhopke/intervals-icu-mcp"

    def _fake_tool(self, sb, url, commit):
        env = sb.home / ".local/share/uv/tools/intervals-icu-mcp"
        (env / "bin").mkdir(parents=True)
        exe = env / "bin/intervals-icu-mcp"
        exe.write_text("#!/bin/sh\nexit 0\n")
        exe.chmod(0o755)
        py = env / "bin/python3"                  # `import fitparse` réussit : pas d'ajout de fitparse
        py.write_text("#!/bin/sh\nexit 0\n")
        py.chmod(0o755)
        dist = env / "lib/python3.12/site-packages/intervals_icu_mcp-5.0.0.dist-info"
        dist.mkdir(parents=True)
        (dist / "direct_url.json").write_text(json.dumps({"url": url, "vcs_info": {"vcs": "git", "commit_id": commit}}))
        link_dir = sb.home / ".local/bin"
        link_dir.mkdir(parents=True, exist_ok=True)
        (link_dir / "intervals-icu-mcp").symlink_to(exe)
        return f"{link_dir}:{STUBS_DIR}:{os.environ.get('PATH', '')}"

    def _install(self, sb, path):
        return sb.install("--source", "intervals", "--no-auth", "--ide", "claude", PATH=path)

    def _tool_installs(self, sb):
        return [args for _, args in sb.stub_calls("uv") if args.startswith("tool install")]

    def test_existing_credentials_file_is_restricted_to_owner(self):
        # Constaté au test d'intégration de #165 : `intervals-icu-mcp-auth` écrit le .env en 0644.
        import re as _re
        with Sandbox() as sb:
            pinned = _re.search(r'^INTERVALS_MCP_REF="git\+[^@"]+@([0-9a-f]{40})"',
                                (sb.repo / "install.sh").read_text(encoding="utf-8"), _re.MULTILINE).group(1)
            path = self._fake_tool(sb, self.FORK, pinned)
            env_dir = sb.home / ".config/ai-running-coach/intervals-icu-mcp"
            env_dir.mkdir(parents=True)
            env_file = env_dir / ".env"
            env_file.write_text("INTERVALS_ICU_API_KEY=x\nINTERVALS_ICU_ATHLETE_ID=i1\n")
            env_file.chmod(0o644)
            proc = sb.install("--source", "intervals", "--ide", "claude", PATH=path)
            self.assertSucceeded(proc)
            self.assertEqual(env_file.stat().st_mode & 0o777, 0o600)
            self.assertNotIn("INTERVALS_ICU_API_KEY=x", proc.stdout + proc.stderr)

    def test_legacy_origin_is_reinstalled_at_the_pinned_commit(self):
        with Sandbox() as sb:
            path = self._fake_tool(sb, *self.LEGACY)
            proc = self._install(sb, path)
            self.assertSucceeded(proc)
            installs = self._tool_installs(sb)
            self.assertEqual(len(installs), 1, installs)
            self.assertIn("--force", installs[0])
            self.assertIn("--with fitparse", installs[0])
            self.assertIn("hhopke/intervals-icu-mcp@", installs[0])
            self.assertOutputContains(proc, "icu_")

    def test_legacy_origin_written_with_dot_git_is_reinstalled_too(self):
        with Sandbox() as sb:
            path = self._fake_tool(sb, self.LEGACY[0] + ".git", self.LEGACY[1])
            self.assertSucceeded(self._install(sb, path))
            self.assertEqual(len(self._tool_installs(sb)), 1)

    def test_unreadable_origin_is_never_reinstalled(self):
        """Sans `direct_url.json` lisible : avertissement, jamais de réinstallation à l'aveugle."""
        with Sandbox() as sb:
            path = self._fake_tool(sb, *self.LEGACY)
            for meta in (sb.home / ".local/share/uv/tools/intervals-icu-mcp").rglob("direct_url.json"):
                meta.write_text("{pas du json")
            proc = self._install(sb, path)
            self.assertSucceeded(proc)
            self.assertEqual(self._tool_installs(sb), [])
            self.assertOutputContains(proc, "illisible")

    def test_installation_at_the_pinned_commit_is_left_alone(self):
        with Sandbox() as sb:
            ref = [line for line in (sb.repo / "install.sh").read_text(encoding="utf-8").splitlines()
                   if line.startswith("INTERVALS_MCP_REF=")][0]
            sha = ref.rstrip('"').rsplit("@", 1)[1]
            path = self._fake_tool(sb, self.FORK, sha)
            self.assertSucceeded(self._install(sb, path))
            self.assertEqual(self._tool_installs(sb), [])

    def test_custom_origin_is_never_overwritten(self):
        with Sandbox() as sb:
            path = self._fake_tool(sb, "https://example.org/my-own-fork", "2" * 40)
            proc = self._install(sb, path)
            self.assertSucceeded(proc)
            self.assertEqual(self._tool_installs(sb), [])
            self.assertOutputContains(proc, "origine personnalisée")

    def test_default_garmin_install_never_touches_the_intervals_server(self):
        with Sandbox() as sb:
            self._fake_tool(sb, *self.LEGACY)
            self.assertSucceeded(sb.install("--no-auth", "--ide", "claude"))
            self.assertFalse([a for a in self._tool_installs(sb) if "intervals" in a])


class TestSwitchingSource(InstallAsserts):
    def test_switching_to_garmin_removes_the_intervals_entry(self):
        with Sandbox() as sb:
            self.assertSucceeded(sb.install("--source", "intervals", "--no-auth", "--ide", "claude"))
            self.assertIn("intervals", _mcp_servers(sb))
            self.assertSucceeded(sb.install("--source", "garmin", "--no-auth", "--ide", "claude"))
            servers = _mcp_servers(sb)
            self.assertIn("garmin", servers)
            self.assertNotIn("intervals", servers, "l'ancienne source doit être retirée, pas seulement ajoutée à côté")
            self.assertEqual(_source(sb), "garmin")

    def test_switching_to_intervals_removes_the_garmin_entry(self):
        with Sandbox() as sb:
            self.assertSucceeded(sb.install("--no-auth", "--ide", "claude"))
            self.assertIn("garmin", _mcp_servers(sb))
            self.assertSucceeded(sb.install("--source", "intervals", "--no-auth", "--ide", "claude"))
            servers = _mcp_servers(sb)
            self.assertIn("intervals", servers)
            self.assertNotIn("garmin", servers)


class TestInvalidSource(InstallAsserts):
    def test_unknown_source_is_rejected(self):
        with Sandbox() as sb:
            proc = sb.install("--source", "bogus", "--no-auth", "--dry-run")
            self.assertFailed(proc, "source inconnue aurait dû être rejetée")


def _add_hand_written_intervals_entry(sb: Sandbox) -> None:
    """docs/faq.md → « configurer Intervals.icu sans passer par install.sh » :
    un athlète Garmin peut ajouter Intervals.icu en secondaire, à la main,
    avec `uv run --directory ... intervals-icu-mcp` — jamais le wrapper que
    `install.sh --source intervals` écrirait lui-même."""
    cfg = sb.repo / ".mcp.json"
    data = json.loads(cfg.read_text()) if cfg.is_file() else {"mcpServers": {}}
    data.setdefault("mcpServers", {})["intervals"] = {
        "command": "uv",
        "args": ["run", "--directory", "/chemin/vers/intervals-icu-mcp", "intervals-icu-mcp"],
    }
    cfg.write_text(json.dumps(data))


class TestHandAddedServerNeverClobbered(InstallAsserts):
    """Blocker (revue PR #116) : `cleanup_stale_mcp_server()` supprimait
    l'entrée `intervals` à CHAQUE installation, y compris un simple rerun
    Garmin qui ne touche jamais `--source` — détruisant silencieusement le
    serveur qu'un athlète Garmin avait ajouté à la main pour un usage
    secondaire (docs/faq.md). Double garde-fou attendu : (1) le nettoyage ne
    tourne que si `--source` a RÉELLEMENT fait basculer la source
    (`SOURCE_CHANGED`), (2) même alors, il ne retire que l'entrée dont
    `command` correspond exactement à ce qu'`install.sh` écrit lui-même."""

    def test_plain_garmin_rerun_keeps_the_hand_added_intervals_entry(self):
        with Sandbox() as sb:
            self.assertSucceeded(sb.install("--no-auth", "--ide", "claude"))
            _add_hand_written_intervals_entry(sb)
            # Rerun SANS --source : ne doit RIEN nettoyer, quelle que soit
            # l'entrée présente.
            self.assertSucceeded(sb.install("--no-auth", "--ide", "claude"))
            servers = _mcp_servers(sb)
            self.assertIn("intervals", servers, "entrée ajoutée à la main supprimée par un simple rerun")
            self.assertEqual(servers["intervals"]["command"], "uv")
            self.assertIn("garmin", servers)

    def test_explicit_but_unchanged_source_keeps_the_hand_added_entry(self):
        with Sandbox() as sb:
            self.assertSucceeded(sb.install("--source", "garmin", "--no-auth", "--ide", "claude"))
            _add_hand_written_intervals_entry(sb)
            # --source garmin explicite, mais IDENTIQUE à la source déjà en
            # config : SOURCE_CHANGED doit rester à 0, aucun nettoyage.
            self.assertSucceeded(sb.install("--source", "garmin", "--no-auth", "--ide", "claude"))
            servers = _mcp_servers(sb)
            self.assertIn("intervals", servers)
            self.assertEqual(servers["intervals"]["command"], "uv")

    def test_real_switch_still_removes_the_installer_written_entry(self):
        with Sandbox() as sb:
            self.assertSucceeded(sb.install("--source", "intervals", "--no-auth", "--ide", "claude"))
            wrapper_command = _mcp_servers(sb)["intervals"]["command"]
            self.assertTrue(wrapper_command.endswith("intervals-icu-mcp/run.sh"))
            # Vrai changement de source : cette entrée-là (écrite par
            # install.sh, command = le wrapper) doit disparaître.
            self.assertSucceeded(sb.install("--source", "garmin", "--no-auth", "--ide", "claude"))
            self.assertNotIn("intervals", _mcp_servers(sb))

    def test_real_switch_does_not_unapprove_a_preserved_non_standard_entry(self):
        """Nit (revue PR #116) : la désapprobation dans ~/.claude.json doit
        suivre le MÊME sort que .mcp.json — une entrée préservée par le
        garde-fou --expect-command ne doit pas non plus être désapprouvée."""
        with Sandbox() as sb:
            self.assertSucceeded(sb.install("--no-auth", "--ide", "claude"))  # source garmin (défaut)
            self.assertIn("garmin", sb.claude_json()["projects"][str(sb.repo)]["enabledMcpjsonServers"])
            cfg = sb.repo / ".mcp.json"
            data = json.loads(cfg.read_text())
            data["mcpServers"]["garmin"] = {"command": "not-garmin-mcp-at-all", "args": []}
            cfg.write_text(json.dumps(data))
            self.assertSucceeded(sb.install("--source", "intervals", "--no-auth", "--ide", "claude"))
            enabled = sb.claude_json()["projects"][str(sb.repo)]["enabledMcpjsonServers"]
            self.assertIn("garmin", enabled, "entrée non standard désapprouvée alors qu'elle est conservée dans .mcp.json")
            self.assertIn("intervals", enabled)

    def test_real_switch_does_not_remove_a_non_standard_stale_entry(self):
        """La source bascule RÉELLEMENT (garmin -> intervals) — "garmin" est
        donc bien la source « stale » ciblée par le nettoyage — mais sa
        commande a été modifiée à la main et ne correspond plus à ce
        qu'`install.sh` écrit lui-même (`garmin-mcp`) : le garde-fou
        `--expect-command` doit la conserver quand même."""
        with Sandbox() as sb:
            self.assertSucceeded(sb.install("--no-auth", "--ide", "claude"))  # source garmin (défaut)
            cfg = sb.repo / ".mcp.json"
            data = json.loads(cfg.read_text())
            data["mcpServers"]["garmin"] = {"command": "not-garmin-mcp-at-all", "args": []}
            cfg.write_text(json.dumps(data))
            self.assertSucceeded(sb.install("--source", "intervals", "--no-auth", "--ide", "claude"))
            servers = _mcp_servers(sb)
            self.assertIn("garmin", servers, "entrée non standard supprimée malgré la non-correspondance de commande")
            self.assertEqual(servers["garmin"]["command"], "not-garmin-mcp-at-all")
            self.assertIn("intervals", servers)
