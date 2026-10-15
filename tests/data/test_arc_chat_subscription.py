"""Palier D — chat OpenCode sur un abonnement ChatGPT / GitHub Copilot (#266).

Même faux serveur OpenCode que `test_arc_chat_opencode.py` ; verrouille :
  - XDG_DATA_HOME = magasin du coach SEULEMENT quand `opencode_data_dir` est posé (et que le modèle est
    d'un fournisseur d'abonnement, sans clé API) ; clé absente = isolation historique inchangée ;
  - aucune clé exigée, aucun bloc `provider` dans la config générée ;
  - jeton absent = message actionnable, aucun serveur démarré ; jamais de connexion lancée ;
  - coût : jamais compté en euros (ChatGPT rapporte 0, Copilot des pseudo-USD), `billing` annoncé ;
  - verrou du magasin pendant un tour ChatGPT (pas pour Copilot) ;
  - traduction des erreurs du fournisseur.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))
import arc_chat_opencode as O  # noqa: E402
import arc_llm  # noqa: E402
from arc_chat_backend import BackendError  # noqa: E402
from tests.data import test_arc_chat_opencode as base  # noqa: E402


def _store_with_token(root: Path, provider: str = "openai") -> Path:
    store = root / "coach-store"
    (store / "opencode").mkdir(parents=True)
    (store / "opencode/auth.json").write_text(json.dumps({provider: {
        "type": "oauth", "refresh": "r", "access": "a", "expires": 4102444800000}}))
    return store


class SubscriptionCase(base.OpenCodeCase):
    MODEL = "openai/gpt-5.4-mini"

    def setUp(self):
        super().setUp()
        os.environ.pop("OPENROUTER_API_KEY", None)        # aucune clé : l'abonnement n'en exige pas
        self.store = _store_with_token(self.ws, "openai" if self.MODEL.startswith("openai/") else "github-copilot")
        self.backend = O.OpenCodeBackend(self.ws, {
            "model": self.MODEL, "api_key_env": "", "opencode_data_dir": str(self.store)})


class TestChatGPT(SubscriptionCase):
    def test_store_becomes_xdg_data_home_and_the_rest_stays_isolated(self):
        self.run_turn(base.fixture("opencode_text_only.json"))
        env = self.spawned[0]["env"]
        self.assertEqual(env["XDG_DATA_HOME"], str(self.store))
        for var in ("XDG_CONFIG_HOME", "XDG_STATE_HOME", "XDG_CACHE_HOME"):
            self.assertTrue(env[var].startswith(str(self.ws / ".arc/chat/opencode/xdg")), var)
        self.assertEqual(oct(os.stat(self.store).st_mode & 0o777), "0o700")
        self.assertNotIn("OPENROUTER_API_KEY", env)

    def test_config_has_no_provider_block_and_no_key(self):
        cfg = json.loads(self.backend.write_config().read_text(encoding="utf-8"))
        self.assertEqual(cfg["provider"], {})
        self.assertEqual(cfg["model"], "openai/gpt-5.4-mini")
        self.assertNotIn("apiKey", json.dumps(cfg))

    def test_prompt_targets_the_openai_provider(self):
        self.run_turn(base.fixture("opencode_text_only.json"))
        prompt = next(b for m, p, b in self.fake.requests if p.endswith("/prompt_async"))
        self.assertEqual(prompt["model"], {"providerID": "openai", "modelID": "gpt-5.4-mini"})

    def test_cost_is_not_counted_in_euros_and_billing_is_announced(self):
        h = self.run_turn(base.fixture("opencode_text_only.json"))
        usage = h.of("usage")[0]
        self.assertEqual(usage["cost_eur"], 0.0)              # la fixture rapporte 0,00016 USD
        self.assertEqual(usage["billing"], "subscription")
        self.assertEqual((usage["input_tokens"], usage["output_tokens"]), (150, 5))
        self.assertEqual(self.backend.billing(), {"mode": "subscription", "label": "ChatGPT"})

    def test_missing_token_gives_the_reconnect_command_and_starts_nothing(self):
        (self.store / "opencode/auth.json").unlink()
        h = base.Harness(self.ws)
        with self.assertRaises(BackendError) as ctx:
            self.backend.run_turn(h.ctx, "salut")
        self.assertIn("python3 scripts/arc_llm.py login chatgpt", str(ctx.exception))
        self.assertEqual(self.spawned, [])
        ok, message = self.backend.check()
        self.assertFalse(ok)

    def test_token_of_the_other_provider_does_not_count(self):
        (self.store / "opencode/auth.json").write_text(json.dumps({"github-copilot": {"type": "oauth"}}))
        with self.assertRaises(BackendError):
            self.backend.run_turn(base.Harness(self.ws).ctx, "salut")

    def test_store_lock_is_held_during_a_turn_and_released_after(self):
        seen = {}
        original = O.OpenCodeBackend._run_turn

        def spy(self_, ctx, message, lease=None):
            other = arc_llm.StoreGate(str(self.store))
            seen["held"] = not other.acquire(0.2)
            return original(self_, ctx, message, lease)

        O.OpenCodeBackend._run_turn = spy
        try:
            self.run_turn(base.fixture("opencode_text_only.json"))
        finally:
            O.OpenCodeBackend._run_turn = original
        self.assertTrue(seen["held"])
        free = arc_llm.StoreGate(str(self.store))
        self.assertTrue(free.acquire(1))
        free.release()

    def test_turn_waits_then_explains_when_the_sync_holds_the_store(self):
        sync = arc_llm.StoreGate(str(self.store))
        self.assertTrue(sync.acquire(1))
        old = O.STORE_WAIT_S
        O.STORE_WAIT_S = 0.4
        try:
            with self.assertRaises(BackendError) as ctx:
                self.backend.run_turn(base.Harness(self.ws).ctx, "salut")
        finally:
            O.STORE_WAIT_S = old
            sync.release()
        self.assertIn("synchronisation", str(ctx.exception))
        self.assertEqual(self.spawned, [])

    def test_concurrent_turns_of_the_service_do_not_block_each_other(self):
        gate = self.backend._store_gate()
        self.assertTrue(gate.acquire(1))
        self.assertTrue(gate.acquire(1))
        gate.release()
        other = arc_llm.StoreGate(str(self.store))
        self.assertFalse(other.acquire(0.2))     # encore tenu par le premier tour
        gate.release()
        self.assertTrue(other.acquire(1))
        other.release()


class TestCopilot(SubscriptionCase):
    MODEL = "github-copilot/gpt-5.4-mini"

    def test_pseudo_usd_cost_is_ignored(self):
        h = self.run_turn(base.fixture("opencode_text_only.json"))
        usage = h.of("usage")[0]
        self.assertEqual(usage["cost_eur"], 0.0)
        self.assertEqual(self.backend.billing()["label"], "GitHub Copilot")
        self.assertEqual(self.spawned[0]["env"]["XDG_DATA_HOME"], str(self.store))

    def test_no_lock_for_copilot(self):
        self.assertIsNone(self.backend._store_gate())


class TestUnsetKeyIsUnchanged(base.OpenCodeCase):
    """Sans `opencode_data_dir` : comportement historique, même avec un modèle openai/…"""

    def test_default_isolation_and_cost(self):
        backend = O.OpenCodeBackend(self.ws, {"model": "openrouter/deepseek/deepseek-v4.1-flash"})
        self.backend = backend
        h = self.run_turn(base.fixture("opencode_text_only.json"))
        env = self.spawned[0]["env"]
        self.assertTrue(env["XDG_DATA_HOME"].startswith(str(self.ws / ".arc/chat/opencode/xdg")))
        self.assertGreater(h.of("usage")[0]["cost_eur"], 0)
        self.assertNotIn("billing", h.of("usage")[0])
        self.assertIsNone(backend.billing())

    def test_openai_model_without_store_is_not_a_subscription(self):
        os.environ["OPENAI_API_KEY"] = "sk-test"
        backend = O.OpenCodeBackend(self.ws, {"model": "openai/gpt-4.1-mini", "api_key_env": "OPENAI_API_KEY"})
        self.assertIsNone(backend._subscription())
        backend = O.OpenCodeBackend(self.ws, {"model": "openai/gpt-4.1-mini", "api_key_env": "OPENAI_API_KEY",
                                              "opencode_data_dir": str(self.ws / "s")})
        self.assertIsNone(backend._subscription())      # une clé API n'est jamais un abonnement
        cfg = json.loads(backend.write_config().read_text(encoding="utf-8"))
        self.assertIn("apiKey", json.dumps(cfg["provider"]))

    def test_openrouter_model_with_store_is_not_a_subscription(self):
        backend = O.OpenCodeBackend(self.ws, {"model": "openrouter/x/y", "api_key_env": "",
                                              "opencode_data_dir": str(self.ws / "s")})
        self.assertIsNone(backend._subscription())


class TestErrorMapping(base.OpenCodeCase):
    CHATGPT = arc_llm.provider("chatgpt")
    COPILOT = arc_llm.provider("copilot")

    def test_table(self):
        tr = O.OpenCodeBackend._translate_error
        cases = [
            (self.CHATGPT, {"name": "APIError", "data": {"message": "Token refresh failed: 400"}}, "login chatgpt"),
            (self.CHATGPT, {"name": "ProviderAuthError", "data": {"message": "x"}}, "login chatgpt"),
            (self.CHATGPT, {"name": "APIError", "data": {"message": "Unauthorized: request was blocked", "statusCode": 401}}, "login chatgpt"),
            (self.CHATGPT, {"name": "APIError", "data": {"message": "usage_not_included"}}, "usage_not_included"),
            (self.CHATGPT, {"name": "APIError", "data": {"message": "To use Codex with your ChatGPT plan, upgrade to Plus"}}, "Plus ou Pro"),
            (self.CHATGPT, {"name": "APIError", "data": {"message": "insufficient_quota"}}, "limites de votre forfait ChatGPT"),
            (self.CHATGPT, {"name": "APIError", "data": {"message": "x", "statusCode": 429}}, "limites de votre forfait ChatGPT"),
            (self.COPILOT, {"name": "APIError", "data": {"message": "Forbidden", "statusCode": 403}}, "login copilot"),
            (self.COPILOT, {"name": "APIError", "data": {"message": "Bad credentials", "statusCode": 401}}, "login copilot"),
            (self.COPILOT, {"name": "APIError", "data": {"message": "x", "statusCode": 429}}, "limites de votre forfait GitHub Copilot"),
            (self.COPILOT, {"name": "ProviderModelNotFoundError", "data": {"message": "model not found"}}, "[chat].model"),
        ]
        for subscription, error, needle in cases:
            self.assertIn(needle, tr(error, subscription), error)

    def test_without_subscription_the_messages_are_the_historical_ones(self):
        tr = O.OpenCodeBackend._translate_error
        self.assertIn("llm.env", tr({"name": "APIError", "data": {"message": "x", "statusCode": 401}}))
        self.assertIn("402", tr({"name": "APIError", "data": {"message": "x", "statusCode": 402}}))

    def test_unknown_subscription_error_falls_back_to_the_generic_message(self):
        message = O.OpenCodeBackend._translate_error({"name": "Weird", "data": {"message": "boom"}}, self.CHATGPT)
        self.assertIn("Erreur du fournisseur", message)


class TestServiceStatus(SubscriptionCase):
    def test_status_announces_the_plan_and_only_then(self):
        import arc_chat
        from arc_chat_mock import MockBackend
        cfg = dict(arc_chat.CHAT_DEFAULTS, enabled=True, backend="opencode", model=self.MODEL)
        service = arc_chat.ChatService(self.ws, cfg, self.backend)
        self.assertEqual(service.status("moi")["billing"], {"mode": "subscription", "label": "ChatGPT"})
        plain = arc_chat.ChatService(self.ws, dict(cfg), MockBackend(self.ws, cfg))
        self.assertNotIn("billing", plain.status("moi"))
        self.assertEqual(arc_chat.CHAT_DEFAULTS["opencode_data_dir"], "")


class TestReviewFixes(SubscriptionCase):
    def test_own_db_and_snapshots_disabled(self):
        self.run_turn(base.fixture("opencode_text_only.json"))
        self.assertEqual(self.spawned[0]["env"]["OPENCODE_DB"], str(self.ws / ".arc/chat/opencode/opencode.db"))
        cfg = json.loads(self.backend.write_config().read_text(encoding="utf-8"))
        self.assertIs(cfg["snapshot"], False)

    def test_unset_key_has_no_own_db_and_keeps_snapshots(self):
        backend = O.OpenCodeBackend(self.ws, {"model": "openrouter/x/y"})
        self.assertNotIn("snapshot", json.loads(backend.write_config().read_text(encoding="utf-8")))

    def test_api_entry_in_the_store_is_missing_auth(self):
        (self.store / "opencode/auth.json").write_text(json.dumps({"openai": {"type": "api", "key": "k"}}))
        self.assertIsNotNone(self.backend._auth_missing())

    def test_hint_carries_a_custom_store(self):
        (self.store / "opencode/auth.json").unlink()
        self.assertIn("--data-dir", self.backend._auth_missing())

    def test_busy_store_emits_a_status_event_then_waits(self):
        sync = arc_llm.StoreGate(str(self.store))
        self.assertTrue(sync.acquire(1))
        old = O.STORE_WAIT_S
        O.STORE_WAIT_S = 0.3
        h = base.Harness(self.ws)
        try:
            with self.assertRaises(BackendError):
                self.backend.run_turn(h.ctx, "salut")
        finally:
            O.STORE_WAIT_S = old
            sync.release()
        self.assertTrue(any("Synchronisation en cours" in p["message"] for p in h.of("status")))

    def test_lease_released_while_waiting_for_an_approval(self):
        gate = self.backend._store_gate()
        lease = O._Lease(gate)
        self.assertTrue(lease.acquire(1))
        other = arc_llm.StoreGate(str(self.store))
        self.assertFalse(other.acquire(0.2))
        lease.suspend()
        lease.suspend()                              # deux approbations simultanées : un seul relâchement
        self.assertTrue(other.acquire(1))
        other.release()
        lease.resume()
        self.assertFalse(lease.held)                 # encore une approbation en attente
        lease.resume()
        self.assertTrue(lease.held)
        self.assertFalse(arc_llm.StoreGate(str(self.store)).acquire(0.2))
        lease.close()
        free = arc_llm.StoreGate(str(self.store))
        self.assertTrue(free.acquire(1))
        free.release()

    def test_approval_wait_goes_through_the_lease(self):
        calls = []
        lease = O._Lease(self.backend._store_gate())
        lease.acquire(1)
        h = base.Harness(self.ws)
        turn = O._Turn(h.ctx)
        turn.lease = lease
        other = arc_llm.StoreGate(str(self.store))

        def approval(*a):
            calls.append(other.acquire(0.5))       # pendant l'attente, le magasin est libre
            other.release()
            return "allow"

        h.ctx.request_approval = approval
        turn.ctx = h.ctx
        ctx = O.OpenCodeBackend._ctx_for_gate(turn)
        self.assertEqual(ctx.request_approval("t", {}, "s", []), "allow")
        self.assertEqual(calls, [True])
        self.assertTrue(lease.held)
        lease.close()

    def test_usage_limit_reached(self):
        msg = O.OpenCodeBackend._translate_error({"name": "APIError", "data": {"message": "usage_limit_reached"}},
                                                 arc_llm.provider("chatgpt"))
        self.assertIn("limites de votre forfait", msg)

    def test_relative_store_is_resolved_from_the_workspace(self):
        backend = O.OpenCodeBackend(self.ws, {"model": self.MODEL, "api_key_env": "", "opencode_data_dir": "rel"})
        self.assertEqual(backend._data_dir(), str(self.ws / "rel"))
