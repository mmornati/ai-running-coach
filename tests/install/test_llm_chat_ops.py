"""Palier A — chat avec le coach et sync sur une API : partie exploitation.

Verrouille, dans le bac à sable (aucun réseau, aucun LLM réel) :
  - le runner `opencode` de `scripts/daily-sync.sh` (commande, config locale au
    projet, clé réservée au process du runner, budget, échecs du fournisseur
    distincts d'un 401 Garmin, validation du contrat après le run) ;
  - `install.sh --llm / --chat / --chat-budget / --sync-budget` ;
  - `scripts/coach-chat.sh` (service systemd/launchd, dry-run) ;
  - les vérifications `llm_config`, `chat_service`, `opencode_cli` de coach_doctor.
"""

from __future__ import annotations

import json
import os
import stat
from datetime import date
from pathlib import Path

from tests.lib.asserts import InstallAsserts
from tests.lib.sandbox import STUBS_DIR, Sandbox

SECRET = "sk-or-SECRET-VALUE-0123456789"
TODAY = date.today().isoformat()

OPENCODE_SYNC = """\
[sync]
runner = "opencode"
model = "openrouter/deepseek/deepseek-v4.1-flash"
api_key_env = "OPENROUTER_API_KEY"
{extra}
[notifications]
provider = "ntfy"
ntfy_topic = "test-topic"
"""


def _write_config(sb: Sandbox, body: str) -> None:
    (sb.repo / "config").mkdir(exist_ok=True)
    (sb.repo / "config/workspace.user.toml").write_text(body, encoding="utf-8")


def _write_llm_env(sb: Sandbox, text: str, mode: int = 0o600) -> Path:
    path = sb.home / ".config/ai-running-coach/llm.env"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    path.chmod(mode)
    return path


def _prime_binary(sb: Sandbox, name: str, source: Path | None = None, body: str | None = None) -> Path:
    """`daily-sync.sh` préfixe son PATH avec `$HOME/.local/bin` : c'est là qu'un faux
    exécutable prime sur un vrai `opencode`/`claude` installé sur la machine du
    contributeur (voir test_token_expiry_alert.py)."""
    bin_dir = sb.home / ".local/bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    target = bin_dir / name
    target.write_text(body if body is not None else f'#!/usr/bin/env bash\nexec "{source}" "$@"\n')
    target.chmod(0o755)
    return target


def _stub_opencode(sb: Sandbox) -> None:
    _prime_binary(sb, "opencode", STUBS_DIR / "opencode")


def _events_file(sb: Sandbox, events: list) -> Path:
    path = sb.root / "opencode-out.jsonl"
    path.write_text("".join(json.dumps(e) + "\n" for e in events), encoding="utf-8")
    return path


def _text_event(text: str) -> dict:
    return {"type": "text", "part": {"type": "text", "text": text}}


def _run_sync(sb: Sandbox, *args: str, **env):
    tokens = sb.root / "tokens"
    tokens.mkdir(exist_ok=True)
    return sb.script("daily-sync.sh", *args, GARMIN_TOKENS_DIR=str(tokens), **env)


def _curl_calls(sb: Sandbox) -> list:
    return [args for _, args in sb.stub_calls("curl")]


class TestOpencodeRunnerDryRun(InstallAsserts):
    def test_command_and_local_config(self):
        with Sandbox() as sb:
            _write_config(sb, OPENCODE_SYNC.format(extra=""))
            _write_llm_env(sb, f"OPENROUTER_API_KEY={SECRET}\n")
            (sb.repo / ".mcp.json").write_text(json.dumps({"mcpServers": {"garmin": {
                "command": "garmin-mcp", "args": ["stdio"],
                "env": {"GARMIN_ENABLED_TOOLS": "get_activities,schedule_workouts,get_sleep_data"}}}}))
            proc = sb.script("daily-sync.sh", "--dry-run")
            self.assertSucceeded(proc)
            self.assertOutputContains(proc, "opencode run --format json --model openrouter/deepseek/deepseek-v4.1-flash")
            self.assertOutputContains(proc, f"--dir {sb.repo}")
            self.assertOutputContains(proc, "OPENCODE_CONFIG=")
            # Config : clé par référence, bash refusé, écritures Garmin refusées et retirées.
            self.assertOutputContains(proc, "{env:OPENROUTER_API_KEY}")
            self.assertOutputContains(proc, '"bash": "deny"')
            self.assertOutputContains(proc, '"garmin_schedule_*": "deny"')
            self.assertOutputContains(proc, '"GARMIN_ENABLED_TOOLS": "get_activities,get_sleep_data"')
            # Dry-run : rien d'écrit, et jamais la valeur de la clé.
            self.assertOutputLacks(proc, SECRET)
            self.assertFalse((sb.repo / ".arc/sync/opencode.json").exists())
            self.assertNotCalled(sb, "opencode")

    def test_gateway_only_mcp_is_flagged_in_dry_run(self):
        with Sandbox() as sb:
            _write_config(sb, OPENCODE_SYNC.format(extra=""))
            (sb.repo / ".mcp.json").write_text(json.dumps({"mcpServers": {"leanproxy": {
                "command": "leanproxy-mcp", "args": ["serve"]}}}))
            proc = sb.script("daily-sync.sh", "--dry-run")
            self.assertSucceeded(proc)
            self.assertOutputContains(proc, "opencode + leanproxy non pris en charge")

    def test_direct_mode_next_to_leanproxy_is_not_flagged(self):
        with Sandbox() as sb:
            _write_config(sb, OPENCODE_SYNC.format(extra=""))
            (sb.repo / ".mcp.json").write_text(json.dumps({"mcpServers": {
                "garmin": {"command": "garmin-mcp", "args": ["stdio"]},
                "leanproxy": {"command": "leanproxy-mcp"}}}))
            proc = sb.script("daily-sync.sh", "--dry-run")
            self.assertSucceeded(proc)
            self.assertOutputLacks(proc, "non pris en charge")

    def test_n6_intervals_icu_direct_server_next_to_leanproxy_is_not_flagged(self):
        for name in ("Intervals_icu", "intervals-icu", "INTERVALS"):
            with Sandbox() as sb:
                _write_config(sb, OPENCODE_SYNC.format(extra=""))
                (sb.repo / ".mcp.json").write_text(json.dumps({"mcpServers": {
                    name: {"command": "intervals-icu-mcp"}, "leanproxy": {"command": "leanproxy-mcp"}}}))
                proc = sb.script("daily-sync.sh", "--dry-run")
                self.assertSucceeded(proc)
                self.assertOutputLacks(proc, "non pris en charge")

    def test_subscription_mode_can_reuse_opencode_default_model(self):
        with Sandbox() as sb:
            _write_config(sb, '[sync]\nrunner = "opencode"\n')
            proc = sb.script("daily-sync.sh", "--dry-run")
            self.assertSucceeded(proc)
            self.assertOutputContains(proc, "opencode run --format json")
            self.assertOutputLacks(proc, "--model")

    def test_base_url_builds_an_openai_compatible_provider(self):
        with Sandbox() as sb:
            _write_config(sb, OPENCODE_SYNC.format(extra='base_url = "https://llm.example.org/v1"\n')
                          .replace("openrouter/deepseek/deepseek-v4.1-flash", "openai/gpt-4.1-mini"))
            proc = sb.script("daily-sync.sh", "--dry-run")
            self.assertSucceeded(proc)
            self.assertOutputContains(proc, "@ai-sdk/openai-compatible")
            self.assertOutputContains(proc, "https://llm.example.org/v1")

    def test_claude_api_mode_passes_model_and_json_output(self):
        with Sandbox() as sb:
            _write_config(sb, '[sync]\nrunner = "claude"\nmodel = "claude-haiku-4-5"\n'
                              'api_key_env = "ANTHROPIC_API_KEY"\n')
            proc = sb.script("daily-sync.sh", "--dry-run")
            self.assertSucceeded(proc)
            self.assertOutputContains(proc, "--output-format json")
            self.assertOutputContains(proc, "--model claude-haiku-4-5")

    def test_claude_subscription_mode_is_unchanged(self):
        with Sandbox() as sb:
            _write_config(sb, '[sync]\nrunner = "claude"\nmodel = "claude-haiku-4-5"\n')
            proc = sb.script("daily-sync.sh", "--dry-run")
            self.assertSucceeded(proc)
            self.assertOutputContains(proc, "--output-format text")
            self.assertOutputLacks(proc, "--model")


class TestOpencodeRunnerExecution(InstallAsserts):
    def _setup(self, sb: Sandbox, extra: str = "", key: bool = True) -> None:
        _write_config(sb, OPENCODE_SYNC.format(extra=extra))
        if key:
            _write_llm_env(sb, f"# commentaire\nOPENROUTER_API_KEY={SECRET}\nAUTRE=jamais-lu\n")
        _stub_opencode(sb)

    def test_key_is_injected_into_the_runner_process_only(self):
        with Sandbox() as sb:
            self._setup(sb)
            proc = _run_sync(sb)
            self.assertSucceeded(proc)
            env_line = [a for a in sb.stub_calls("opencode") if a[1].startswith("env ")]
            self.assertTrue(env_line, sb.stub_calls())
            self.assertIn(f"OPENROUTER_API_KEY_LEN={len(SECRET)}", env_line[0][1])
            self.assertIn("OPENCODE_CONFIG=" + str(sb.repo / ".arc/sync/opencode.json"), env_line[0][1])
            # La config générée référence la clé, ne la contient pas.
            config = (sb.repo / ".arc/sync/opencode.json").read_text()
            self.assertIn("{env:OPENROUTER_API_KEY}", config)
            self.assertNotIn(SECRET, config)
            self.assertNotIn(SECRET, proc.stdout + proc.stderr)
            for log in (sb.repo / "logs").glob("sync-*.log"):
                self.assertNotIn(SECRET, log.read_text())

    def test_existing_environment_variable_wins_over_llm_env(self):
        with Sandbox() as sb:
            self._setup(sb)
            proc = _run_sync(sb, OPENROUTER_API_KEY="court")
            self.assertSucceeded(proc)
            env_line = [a for a in sb.stub_calls("opencode") if a[1].startswith("env ")][0][1]
            self.assertIn("OPENROUTER_API_KEY_LEN=5", env_line)

    def test_missing_key_aborts_with_a_notification(self):
        with Sandbox() as sb:
            self._setup(sb, key=False)
            proc = _run_sync(sb)
            self.assertFailed(proc)
            self.assertNotCalled(sb, "opencode")
            self.assertTrue(any("clé API absente" in c for c in _curl_calls(sb)), _curl_calls(sb))

    def test_resume_is_extracted_and_spend_recorded(self):
        with Sandbox() as sb:
            self._setup(sb)
            proc = _run_sync(sb, ARC_STUB_OPENCODE_COST="0.5")
            self.assertSucceeded(proc)
            self.assertTrue(any("Sync OK (stub)" in c for c in _curl_calls(sb)), _curl_calls(sb))
            spend = (sb.repo / f"logs/.sync-spend-{TODAY}").read_text().strip()
            self.assertAlmostEqual(float(spend), 0.5 * 0.92, places=3)

    def test_gateway_only_mcp_fails_fast_with_a_notification(self):
        with Sandbox() as sb:
            self._setup(sb)
            (sb.repo / ".mcp.json").write_text(json.dumps({"mcpServers": {"leanproxy": {
                "command": "leanproxy-mcp", "args": ["serve"]}}}))
            proc = _run_sync(sb)
            self.assertFailed(proc)
            self.assertNotCalled(sb, "opencode")
            self.assertTrue(any("leanproxy non pris en charge" in c for c in _curl_calls(sb)), _curl_calls(sb))

    def test_over_budget_skips_the_run_and_notifies_once(self):
        with Sandbox() as sb:
            self._setup(sb)
            (sb.repo / "logs").mkdir()
            (sb.repo / f"logs/.sync-spend-{TODAY}").write_text("0.6\n")
            proc = _run_sync(sb)
            self.assertSucceeded(proc, "un budget dépassé n'est pas une panne")
            self.assertNotCalled(sb, "opencode")
            budget_calls = [c for c in _curl_calls(sb) if "budget" in c]
            self.assertEqual(len(budget_calls), 1, _curl_calls(sb))
            _run_sync(sb)
            budget_calls = [c for c in _curl_calls(sb) if "budget" in c]
            self.assertEqual(len(budget_calls), 1, "la notification de budget ne doit partir qu'une fois par jour")

    def test_budget_not_enforced_without_reported_cost(self):
        """Runner claude sur abonnement : aucun coût rapporté, donc aucun plafond."""
        with Sandbox() as sb:
            _write_config(sb, '[sync]\nrunner = "claude"\ndaily_budget_eur = 0.01\n')
            (sb.repo / "logs").mkdir()
            (sb.repo / f"logs/.sync-spend-{TODAY}").write_text("9.0\n")
            proc = _run_sync(sb)
            self.assertSucceeded(proc)
            self.assertCalled(sb, "claude")

    def test_provider_401_is_not_a_garmin_auth_failure(self):
        with Sandbox() as sb:
            self._setup(sb)
            out = _events_file(sb, [{"type": "error", "error": {
                "name": "APIError", "data": {"statusCode": 401, "message": "User not found."}}}])
            proc = _run_sync(sb, ARC_STUB_OPENCODE_OUT=str(out), ARC_STUB_OPENCODE_RC="1")
            self.assertFailed(proc)
            titles = " ".join(_curl_calls(sb))
            self.assertIn("clé openrouter refusée", titles)
            self.assertNotIn("Authentification Garmin", titles)
            self.assertNotIn("garmin-mcp-auth", titles)
            self.assertIn("pas un problème Garmin", titles)

    def test_provider_402_is_reported_as_missing_credits(self):
        with Sandbox() as sb:
            self._setup(sb)
            out = _events_file(sb, [{"type": "error", "error": {
                "name": "APIError", "data": {"statusCode": 402, "message": "Insufficient credits."}}}])
            proc = _run_sync(sb, ARC_STUB_OPENCODE_OUT=str(out), ARC_STUB_OPENCODE_RC="1")
            self.assertFailed(proc)
            titles = " ".join(_curl_calls(sb))
            self.assertIn("crédits openrouter épuisés", titles)
            self.assertNotIn("Authentification Garmin", titles)

    def test_explicit_garmin_wording_is_still_a_garmin_failure(self):
        with Sandbox() as sb:
            self._setup(sb)
            out = _events_file(sb, [_text_event(
                "ERREUR : tokens Garmin expirés — renouvelez avec garmin-mcp-auth")])
            proc = _run_sync(sb, ARC_STUB_OPENCODE_OUT=str(out), ARC_STUB_OPENCODE_RC="1")
            self.assertFailed(proc)
            titles = " ".join(_curl_calls(sb))
            self.assertIn("Authentification Garmin", titles)
            self.assertNotIn("clé openrouter", titles)

    def test_files_breaking_the_arc_contract_are_flagged(self):
        with Sandbox() as sb:
            self._setup(sb)
            bad = sb.repo / "activities/2099-01-01_running.md"
            proc = _run_sync(sb, ARC_STUB_OPENCODE_WRITE=str(bad))
            self.assertSucceeded(proc)
            self.assertOutputContains(proc, "hors contrat")
            # Le message ntfy est multi-lignes : on lit le journal brut des stubs.
            raw = sb.stub_log.read_text()
            self.assertIn("hors contrat arc", raw)
            self.assertIn("2099-01-01_running.md", raw)


class TestClaudeApiMode(InstallAsserts):
    def _fake_claude(self, sb: Sandbox, payload: dict, rc: int = 0) -> None:
        out = sb.root / "claude-out.json"
        out.write_text(json.dumps(payload), encoding="utf-8")
        argv_log = sb.root / "claude-argv.txt"
        _prime_binary(sb, "claude", body=(
            "#!/usr/bin/env bash\n"
            f'printf \'%s\\n\' "$*" > "{argv_log}"\n'
            f'printf \'%s\' "${{ANTHROPIC_API_KEY:+set}}" > "{sb.root}/claude-key.txt"\n'
            f'cat "{out}"\nexit {rc}\n'))

    def _config(self, sb: Sandbox) -> None:
        _write_config(sb, '[sync]\nrunner = "claude"\nmodel = "claude-haiku-4-5"\n'
                          'api_key_env = "ANTHROPIC_API_KEY"\ndaily_budget_eur = 1.0\n'
                          '[notifications]\nprovider = "ntfy"\nntfy_topic = "t"\n')
        _write_llm_env(sb, "ANTHROPIC_API_KEY=sk-ant-SECRET\n")

    def test_json_result_keeps_resume_and_records_cost(self):
        with Sandbox() as sb:
            self._config(sb)
            self._fake_claude(sb, {"type": "result", "is_error": False,
                                   "result": "```resume\nÀ jour (claude)\n```", "total_cost_usd": 0.1})
            proc = _run_sync(sb)
            self.assertSucceeded(proc)
            self.assertTrue(any("À jour (claude)" in c for c in _curl_calls(sb)), _curl_calls(sb))
            argv = (sb.root / "claude-argv.txt").read_text()
            self.assertIn("--output-format json", argv)
            self.assertIn("--model claude-haiku-4-5", argv)
            self.assertEqual((sb.root / "claude-key.txt").read_text(), "set")
            spend = float((sb.repo / f"logs/.sync-spend-{TODAY}").read_text())
            self.assertAlmostEqual(spend, 0.1 * 0.92, places=3)

    def test_anthropic_401_is_a_provider_failure(self):
        with Sandbox() as sb:
            self._config(sb)
            self._fake_claude(sb, {"type": "result", "is_error": True, "api_error_status": 401,
                                   "result": "Invalid API key"}, rc=1)
            proc = _run_sync(sb)
            self.assertFailed(proc)
            titles = " ".join(_curl_calls(sb))
            self.assertIn("clé Anthropic refusée", titles)
            self.assertNotIn("Authentification Garmin", titles)


class TestInstallLlm(InstallAsserts):
    def _toml(self, sb: Sandbox) -> str:
        path = sb.repo / "config/workspace.user.toml"
        return path.read_text(encoding="utf-8") if path.exists() else ""

    def _get(self, sb: Sandbox, section: str, key: str) -> str:
        proc = sb.run(["python3", str(sb.repo / "scripts/coach_config.py"), "get",
                       "--workspace", str(sb.repo), "--section", section, "--key", key, "--default", ""])
        return proc.stdout.strip()

    def test_openrouter_writes_chat_and_sync_and_creates_llm_env(self):
        with Sandbox() as sb:
            proc = sb.install("--no-auth", "--ide", "claude", "--llm", "openrouter")
            self.assertSucceeded(proc)
            model = "openrouter/deepseek/deepseek-v4.1-flash"
            self.assertEqual(self._get(sb, "chat", "backend"), "opencode")
            self.assertEqual(self._get(sb, "chat", "model"), model)
            self.assertEqual(self._get(sb, "chat", "api_key_env"), "OPENROUTER_API_KEY")
            self.assertEqual(self._get(sb, "sync", "runner"), "opencode")
            self.assertEqual(self._get(sb, "sync", "model"), model)
            self.assertEqual(self._get(sb, "sync", "api_key_env"), "OPENROUTER_API_KEY")
            env_file = sb.home / ".config/ai-running-coach/llm.env"
            self.assertIsFile(env_file)
            self.assertEqual(stat.S_IMODE(env_file.stat().st_mode), 0o600)
            self.assertIn("# OPENROUTER_API_KEY=", env_file.read_text())
            self.assertOutputContains(proc, "OPENROUTER_API_KEY absente")
            self.assertOutputContains(proc, "N'exportez pas")

    def test_no_key_is_ever_written_or_printed(self):
        with Sandbox() as sb:
            _write_llm_env(sb, f"OPENROUTER_API_KEY={SECRET}\n")
            proc = sb.install("--no-auth", "--ide", "claude", "--llm", "openrouter")
            self.assertSucceeded(proc)
            self.assertOutputLacks(proc, SECRET)
            self.assertNotIn(SECRET, self._toml(sb))
            self.assertOutputContains(proc, "présente (valeur non affichée)")

    def test_replaces_existing_values_with_a_warning_naming_old_and_new(self):
        with Sandbox() as sb:
            _write_config(sb, '[sync]\nrunner = "codex"\nmodel = "vieux"\n')
            proc = sb.install("--no-auth", "--ide", "claude", "--llm", "openrouter")
            self.assertSucceeded(proc)
            self.assertOutputContains(proc, "[sync].runner : codex → opencode")
            self.assertOutputContains(proc, "[sync].model : vieux → openrouter/deepseek/deepseek-v4.1-flash")
            self.assertOutputContains(proc, "Pour revenir")
            self.assertEqual(self._get(sb, "sync", "runner"), "opencode")

    def test_rerun_is_idempotent_and_silent(self):
        with Sandbox() as sb:
            self.assertSucceeded(sb.install("--no-auth", "--ide", "claude", "--llm", "openrouter"))
            before = self._toml(sb)
            proc = sb.install("--no-auth", "--ide", "claude", "--llm", "openrouter")
            self.assertSucceeded(proc)
            self.assertEqual(self._toml(sb), before)
            self.assertOutputLacks(proc, "Pour revenir")

    def test_plain_rerun_never_touches_llm_keys(self):
        with Sandbox() as sb:
            self.assertSucceeded(sb.install("--no-auth", "--ide", "claude", "--llm", "openrouter"))
            cfg = sb.repo / "config/workspace.user.toml"
            cfg.write_text(cfg.read_text().replace('model = "openrouter/deepseek/deepseek-v4.1-flash"',
                                                    'model = "openrouter/perso/mon-modele"'))
            proc = sb.install("--no-auth", "--ide", "claude")
            self.assertSucceeded(proc)
            self.assertEqual(self._get(sb, "sync", "model"), "openrouter/perso/mon-modele")
            self.assertEqual(self._get(sb, "chat", "model"), "openrouter/perso/mon-modele")
            self.assertOutputLacks(proc, "Pour revenir")

    def test_anthropic_defaults_and_remote_control_warning(self):
        with Sandbox() as sb:
            proc = sb.install("--no-auth", "--ide", "claude", "--llm", "anthropic", "--chat",
                              ARC_FAKE_UNAME="Linux", ANTHROPIC_API_KEY="exporte-dans-le-shell")
            self.assertSucceeded(proc)
            self.assertEqual(self._get(sb, "chat", "backend"), "claude")
            self.assertEqual(self._get(sb, "chat", "model"), "claude-sonnet-5-5")
            self.assertEqual(self._get(sb, "sync", "runner"), "claude")
            self.assertEqual(self._get(sb, "sync", "model"), "claude-haiku-4-5")
            self.assertEqual(self._get(sb, "sync", "api_key_env"), "ANTHROPIC_API_KEY")
            self.assertOutputContains(proc, "N'exportez PAS ANTHROPIC_API_KEY")
            self.assertOutputContains(proc, "DÉJÀ exporté")
            self.assertOutputContains(proc, "pip install claude-agent-sdk")
            self.assertOutputLacks(proc, "exporte-dans-le-shell")

    def test_anthropic_switch_from_subscription_to_paid_api_is_warned(self):
        with Sandbox() as sb:
            proc = sb.install("--no-auth", "--ide", "claude", "--llm", "anthropic")
            self.assertSucceeded(proc)
            self.assertOutputContains(proc, "[sync].api_key_env : (vide) → ANTHROPIC_API_KEY")
            self.assertOutputContains(proc, "abonnement → clé API facturée au token")
            # Rerun : déjà en mode API, plus rien à signaler.
            proc = sb.install("--no-auth", "--ide", "claude", "--llm", "anthropic")
            self.assertSucceeded(proc)
            self.assertOutputLacks(proc, "abonnement → clé API facturée au token")

    def test_openrouter_does_not_print_the_subscription_warning(self):
        with Sandbox() as sb:
            proc = sb.install("--no-auth", "--ide", "claude", "--llm", "openrouter")
            self.assertSucceeded(proc)
            self.assertOutputLacks(proc, "facturée au token")

    def test_custom_model_and_openai_requirements(self):
        with Sandbox() as sb:
            proc = sb.install("--no-auth", "--ide", "claude", "--llm", "openrouter",
                              "--model", "mistralai/mistral-small")
            self.assertSucceeded(proc)
            self.assertEqual(self._get(sb, "sync", "model"), "openrouter/mistralai/mistral-small")
        with Sandbox() as sb:
            self.assertFailed(sb.install("--no-auth", "--llm", "openai"), "openai sans --model")
        with Sandbox() as sb:
            proc = sb.install("--no-auth", "--ide", "claude", "--llm", "openai", "--model", "gpt-4.1-mini",
                              "--base-url", "https://llm.example.org/v1")
            self.assertSucceeded(proc)
            self.assertEqual(self._get(sb, "chat", "model"), "openai/gpt-4.1-mini")
            self.assertEqual(self._get(sb, "sync", "base_url"), "https://llm.example.org/v1")
            self.assertEqual(self._get(sb, "chat", "api_key_env"), "OPENAI_API_KEY")

    def test_invalid_llm_arguments_are_rejected(self):
        with Sandbox() as sb:
            self.assertFailed(sb.install("--no-auth", "--llm", "grok"))
            self.assertFailed(sb.install("--no-auth", "--model", "x"), "--model sans --llm")
            self.assertFailed(sb.install("--no-auth", "--llm", "anthropic", "--base-url", "https://x"))

    def test_missing_opencode_prints_the_official_install_command(self):
        with Sandbox() as sb:
            proc = sb.install("--no-auth", "--ide", "claude", "--llm", "openrouter", hide=("opencode",))
            self.assertSucceeded(proc)
            self.assertOutputContains(proc, "curl -fsSL https://opencode.ai/v2/install | bash")

    def test_dry_run_writes_nothing(self):
        with Sandbox() as sb:
            before = sb.tree(sb.home, sb.repo / "config")
            proc = sb.install("--no-auth", "--ide", "claude", "--llm", "openrouter", "--chat",
                              "--chat-budget", "3", "--dry-run", ARC_FAKE_UNAME="Linux")
            self.assertSucceeded(proc)
            self.assertEqual(sb.tree(sb.home, sb.repo / "config"), before)
            self.assertFalse((sb.home / ".config/ai-running-coach/llm.env").exists())

    def test_budgets_are_written_as_numbers_and_validated(self):
        with Sandbox() as sb:
            proc = sb.install("--no-auth", "--ide", "claude", "--chat-budget", "3", "--sync-budget", "0.25")
            self.assertSucceeded(proc)
            toml = self._toml(sb)
            self.assertRegex(toml, r"(?m)^daily_budget_eur = 3\.0$")
            self.assertRegex(toml, r"(?m)^daily_budget_eur = 0\.25$")
            self.assertEqual(self._get(sb, "sync", "daily_budget_eur"), "0.25")
        for bad in ("abc", "0", "-1", "1e3", ""):
            with self.subTest(value=bad), Sandbox() as sb:
                self.assertFailed(sb.install("--no-auth", "--chat-budget", bad))
                self.assertFailed(sb.install("--no-auth", "--sync-budget", bad))


class TestInstallChatService(InstallAsserts):
    def test_linux_installs_a_systemd_user_unit_with_the_key_file(self):
        with Sandbox() as sb:
            proc = sb.install("--no-auth", "--ide", "claude", "--llm", "openrouter", "--chat",
                              ARC_FAKE_UNAME="Linux")
            self.assertSucceeded(proc)
            unit = sb.home / ".config/systemd/user/ai-running-coach-chat.service"
            self.assertIsFile(unit)
            self.assertFileContains(unit, f"EnvironmentFile=-{sb.home}/.config/ai-running-coach/llm.env")
            self.assertFileContains(unit, "coach-chat.sh run")
            self.assertFileLacks(unit, "OPENROUTER_API_KEY=")
            self.assertCalled(sb, "systemctl", "--user enable --now ai-running-coach-chat")
            self.assertCalled(sb, "loginctl", "enable-linger")
            self.assertOutputContains(proc, "enable-linger")
            enabled = sb.run(["python3", str(sb.repo / "scripts/coach_config.py"), "get", "--workspace",
                              str(sb.repo), "--section", "chat", "--key", "enabled"])
            self.assertEqual(enabled.stdout.strip(), "true")

    def test_macos_installs_a_launch_agent(self):
        with Sandbox() as sb:
            proc = sb.install("--no-auth", "--ide", "claude", "--chat", ARC_FAKE_UNAME="Darwin")
            self.assertSucceeded(proc)
            plist = sb.home / "Library/LaunchAgents/com.ai-running-coach.chat.plist"
            self.assertIsFile(plist)
            self.assertFileContains(plist, "com.ai-running-coach.chat")
            self.assertFileContains(plist, "coach-chat.sh")
            self.assertCalled(sb, "launchctl", "bootstrap")

    def test_no_service_without_the_flag(self):
        with Sandbox() as sb:
            self.assertSucceeded(sb.install("--no-auth", "--ide", "claude", "--llm", "openrouter",
                                            ARC_FAKE_UNAME="Linux"))
            self.assertFalse((sb.home / ".config/systemd/user/ai-running-coach-chat.service").exists())


class TestCoachChatScript(InstallAsserts):
    def test_dry_run_install_writes_nothing(self):
        for uname in ("Linux", "Darwin"):
            with self.subTest(uname=uname), Sandbox() as sb:
                before = sb.tree(sb.home)
                proc = sb.script("coach-chat.sh", "--dry-run", "install", ARC_FAKE_UNAME=uname)
                self.assertSucceeded(proc)
                self.assertEqual(sb.tree(sb.home), before)
                self.assertOutputContains(proc, "[dry-run]")

    def test_install_then_uninstall_linux(self):
        with Sandbox() as sb:
            self.assertSucceeded(sb.script("coach-chat.sh", "install", ARC_FAKE_UNAME="Linux"))
            unit = sb.home / ".config/systemd/user/ai-running-coach-chat.service"
            self.assertIsFile(unit)
            self.assertSucceeded(sb.script("coach-chat.sh", "uninstall", ARC_FAKE_UNAME="Linux"))
            self.assertFalse(unit.exists())
            self.assertCalled(sb, "systemctl", "disable --now ai-running-coach-chat")

    def test_install_then_uninstall_macos(self):
        with Sandbox() as sb:
            self.assertSucceeded(sb.script("coach-chat.sh", "install", ARC_FAKE_UNAME="Darwin"))
            plist = sb.home / "Library/LaunchAgents/com.ai-running-coach.chat.plist"
            self.assertIsFile(plist)
            self.assertSucceeded(sb.script("coach-chat.sh", "uninstall", ARC_FAKE_UNAME="Darwin"))
            self.assertFalse(plist.exists())

    def test_run_loads_llm_env_into_the_service_process_only(self):
        with Sandbox() as sb:
            _write_llm_env(sb, f"OPENROUTER_API_KEY={SECRET}\n")
            (sb.repo / "scripts/arc_chat.py").write_text(
                "import os, sys\n"
                "print('KEYLEN=%d' % len(os.environ.get('OPENROUTER_API_KEY', '')))\n"
                "print('ARGS=' + ' '.join(sys.argv[1:]))\n")
            proc = sb.script("coach-chat.sh", "run")
            self.assertSucceeded(proc)
            self.assertOutputContains(proc, f"KEYLEN={len(SECRET)}")
            self.assertOutputContains(proc, f"ARGS=--workspace {sb.repo}")
            self.assertOutputLacks(proc, SECRET)

    def test_run_does_not_override_an_existing_variable(self):
        with Sandbox() as sb:
            _write_llm_env(sb, f"OPENROUTER_API_KEY={SECRET}\n")
            (sb.repo / "scripts/arc_chat.py").write_text(
                "import os\nprint('KEYLEN=%d' % len(os.environ.get('OPENROUTER_API_KEY', '')))\n")
            proc = sb.script("coach-chat.sh", "run", OPENROUTER_API_KEY="abc")
            self.assertOutputContains(proc, "KEYLEN=3")


def _doctor(sb: Sandbox, check: str, **env) -> dict:
    proc = sb.script("coach_doctor.py", "--json", "--check", check, **env)
    if proc.returncode not in (0, 1):
        raise AssertionError(proc.stderr)
    return json.loads(proc.stdout)["checks"][0]


class TestDoctorLlmChecks(InstallAsserts):
    def test_llm_config_info_without_api(self):
        with Sandbox() as sb:
            self.assertEqual(_doctor(sb, "llm_config")["status"], "info")

    def test_llm_config_ok_and_never_prints_the_key(self):
        with Sandbox() as sb:
            _write_config(sb, OPENCODE_SYNC.format(extra=""))
            _write_llm_env(sb, f"OPENROUTER_API_KEY={SECRET}\n")
            check = _doctor(sb, "llm_config")
            self.assertEqual(check["status"], "ok", check)
            self.assertNotIn(SECRET, json.dumps(check))

    def test_llm_config_warns_on_missing_file_loose_mode_and_undefined_variable(self):
        with Sandbox() as sb:
            _write_config(sb, OPENCODE_SYNC.format(extra=""))
            check = _doctor(sb, "llm_config")
            self.assertEqual(check["status"], "warning")
            self.assertIn("absent", check["message"])
            _write_llm_env(sb, "# OPENROUTER_API_KEY=\n", mode=0o644)
            check = _doctor(sb, "llm_config")
            self.assertEqual(check["status"], "warning")
            self.assertIn("644", check["message"])
            self.assertIn("non définie", check["message"])

    def test_llm_config_warns_on_opencode_with_the_leanproxy_gateway(self):
        with Sandbox() as sb:
            _write_config(sb, OPENCODE_SYNC.format(extra=""))
            _write_llm_env(sb, f"OPENROUTER_API_KEY={SECRET}\n")
            (sb.repo / ".mcp.json").write_text(json.dumps({"mcpServers": {"leanproxy": {"command": "x"}}}))
            check = _doctor(sb, "llm_config")
            self.assertEqual(check["status"], "warning")
            self.assertIn("opencode + leanproxy non pris en charge pour la synchronisation", check["message"])
            self.assertIn("mode direct", check["message"])
            (sb.repo / ".mcp.json").write_text(json.dumps({"mcpServers": {"garmin": {"command": "x"}}}))
            self.assertEqual(_doctor(sb, "llm_config")["status"], "ok")

    def test_n6_doctor_recognises_intervals_icu_as_a_direct_server(self):
        with Sandbox() as sb:
            _write_config(sb, OPENCODE_SYNC.format(extra=""))
            _write_llm_env(sb, f"OPENROUTER_API_KEY={SECRET}\n")
            (sb.repo / ".mcp.json").write_text(json.dumps({"mcpServers": {
                "Intervals_icu": {"command": "x"}, "leanproxy": {"command": "y"}}}))
            self.assertEqual(_doctor(sb, "llm_config")["status"], "ok")

    def test_llm_config_warns_on_inconsistent_model(self):
        with Sandbox() as sb:
            _write_config(sb, '[sync]\nrunner = "opencode"\nmodel = "deepseek-chat"\n')
            check = _doctor(sb, "llm_config")
            self.assertEqual(check["status"], "warning")
            self.assertIn("fournisseur/modèle", check["message"])

    def test_chat_service_states(self):
        with Sandbox() as sb:
            self.assertEqual(_doctor(sb, "chat_service")["status"], "info")
        with Sandbox() as sb:
            _write_config(sb, '[chat]\nenabled = true\nport = 1\n')
            check = _doctor(sb, "chat_service", ARC_FAKE_UNAME="Linux")
            self.assertEqual(check["status"], "warning", "chat activé mais injoignable : warning, jamais error")
            self.assertIn("aucun service installé", check["message"])
            unit = sb.home / ".config/systemd/user/ai-running-coach-chat.service"
            unit.parent.mkdir(parents=True)
            unit.write_text("[Service]\n")
            check = _doctor(sb, "chat_service", ARC_FAKE_UNAME="Linux")
            self.assertEqual(check["status"], "warning")
            self.assertIn("injoignable", check["message"])

    def test_chat_service_ok_when_healthz_answers(self):
        import http.server
        import threading

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                body = b'{"ok": true, "backend_check": "ok"}'
                self.send_response(200 if self.path == "/api/chat/healthz" else 404)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with Sandbox() as sb:
                _write_config(sb, f"[chat]\nenabled = true\nport = {server.server_address[1]}\n")
                check = _doctor(sb, "chat_service", ARC_FAKE_UNAME="Linux")
                self.assertEqual(check["status"], "ok", check)
        finally:
            server.shutdown()
            server.server_close()

    def test_chat_service_unhealthy_503_is_reported_as_running_but_unhealthy(self):
        # Revue : /healthz répond 503 quand le backend n'est pas sain ; HTTPError hérite
        # d'URLError et faisait passer le service pour « injoignable ».
        import http.server
        import threading

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                body = b'{"ok": false, "backend_check": "opencode absent"}'
                self.send_response(503)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with Sandbox() as sb:
                _write_config(sb, f"[chat]\nenabled = true\nport = {server.server_address[1]}\n")
                check = _doctor(sb, "chat_service", ARC_FAKE_UNAME="Linux")
                self.assertEqual(check["status"], "warning", check)
                self.assertIn("non sain", check["message"])
                self.assertIn("opencode absent", check["message"])
                self.assertNotIn("injoignable", check["message"])
        finally:
            server.shutdown()
            server.server_close()

    def test_opencode_cli_states(self):
        with Sandbox() as sb:
            self.assertEqual(_doctor(sb, "opencode_cli")["status"], "info")
        with Sandbox() as sb:
            _write_config(sb, '[sync]\nrunner = "opencode"\nmodel = "openrouter/x/y"\n')
            check = _doctor(sb, "opencode_cli")
            self.assertEqual(check["status"], "ok", check)
            self.assertIn("1.18.32-stub", check["message"])
        with Sandbox() as sb:
            _write_config(sb, '[sync]\nrunner = "opencode"\nmodel = "openrouter/x/y"\n')
            empty = sb.root / "empty-bin"
            empty.mkdir()
            proc = sb.script("coach_doctor.py", "--json", "--check", "opencode_cli",
                             PATH=f"{empty}:{os.path.dirname(os.popen('command -v python3').read().strip())}:/usr/bin:/bin")
            check = json.loads(proc.stdout)["checks"][0]
            if check["status"] == "warning":
                self.assertIn("opencode.ai/v2/install", check["fix"])
            self.assertNotEqual(check["status"], "error")
