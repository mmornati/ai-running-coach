"""Palier D — chat OpenCode sur un modèle OpenRouter gratuit (`:free`, #267).

Verrouille : la traduction des erreurs (quota du jour / limite par minute / fournisseur saturé / ZDR),
qui ne s'applique aux 429 que pour un modèle gratuit, et l'annonce `billing` « free » du statut.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))
import arc_chat_opencode as O  # noqa: E402
import arc_llm  # noqa: E402
from arc_chat_backend import BackendError  # noqa: E402
from tests.data import test_arc_chat_opencode as base  # noqa: E402

FREE = "openrouter/nvidia/nemotron-3-ultra-550b-a55b:free"
PAID = "openrouter/deepseek/deepseek-v4.1-flash"
# Corps réel reçu le 2026-10-15 du modèle gratuit par défaut (HTTP 200, erreur dans le flux).
OVERLOADED_BODY = {"error": {"message": "Upstream error from Nvidia: Service temporarily overloaded", "code": 503,
                             "metadata": {"error_type": "provider_overloaded"}}}
# Ce qu'en fait OpenCode v1.18.35 (MessageV2.fromError) : objet sans `type: "error"` -> UnknownError
# dont le message est l'objet d'erreur sérialisé, sans statusCode.
OVERLOADED_UNKNOWN = {"name": "UnknownError", "data": {"message": json.dumps(OVERLOADED_BODY["error"])}}


def _err(status, message, **data):
    return {"name": "APIError", "data": dict({"statusCode": status, "message": message}, **data)}


class TestFreeErrorMapping(base.OpenCodeCase):
    def tr(self, error, model=FREE):
        return O.OpenCodeBackend._translate_error(error, None, model=model)

    def test_daily_quota(self):
        for text in ("Rate limit exceeded: free-models-per-day", "limit reached: 50 requests per day"):
            msg = self.tr(_err(429, text))
            self.assertIn("Quota gratuit du jour atteint", msg)
            self.assertIn("50 requêtes", msg)
            self.assertIn("10 $", msg)

    def test_daily_quota_found_in_the_raw_response_body(self):
        msg = self.tr(_err(429, "Too Many Requests", responseBody='{"error":{"message":"free-models-per-day"}}'))
        self.assertIn("Quota gratuit du jour atteint", msg)

    def test_per_minute_limit(self):
        self.assertIn("20 requêtes par minute", self.tr(_err(429, "Rate limit exceeded: free-models-per-min")))

    def test_upstream_saturation_is_not_the_quota(self):
        msg = self.tr(_err(429, "Provider returned error"))
        self.assertIn("saturé", msg)
        self.assertNotIn("Quota gratuit du jour", msg)

    def test_unknown_free_429_says_the_three_cases(self):
        msg = self.tr(_err(429, "Rate limit exceeded"))
        self.assertIn("20 requêtes par minute", msg)
        self.assertIn("50 par jour", msg)

    def test_per_minute_body_with_a_daily_upsell_is_still_the_minute_limit(self):
        msg = self.tr(_err(429, "Rate limit exceeded: free-models-per-min. Add 10 credits to unlock 1000 free model "
                                "requests per day"))
        self.assertIn("20 requêtes par minute", msg)
        self.assertNotIn("Quota gratuit du jour", msg)
        generic = self.tr(_err(429, "Rate limit: too many requests per minute; 1000 requests per day with credits"))
        self.assertIn("par minute", generic)
        self.assertNotIn("Quota gratuit du jour", generic)

    def test_a_bare_daily_word_is_not_the_quota(self):
        self.assertNotIn("Quota gratuit du jour", self.tr(_err(429, "daily maintenance, rate limit exceeded")))

    def test_privacy_setting_404_free_model_names_the_training_cause(self):
        for text in ("No endpoints found: 0 endpoints, ZDR violation",
                     "No endpoints found matching your data policy (Free model training)"):
            msg = self.tr(_err(404, text), FREE)
            self.assertIn("réglage de confidentialité", msg)
            self.assertIn("NVIDIA", msg)
            self.assertNotIn("rétention zéro (ZDR) imposée", msg)

    def test_privacy_setting_404_paid_model_has_its_own_wording(self):
        for text in ("No endpoints found matching your data policy", "0 endpoints, ZDR violation"):
            msg = self.tr(_err(404, text), PAID)
            self.assertIn("réglage de confidentialité", msg)
            self.assertIn("[chat].model", msg)
            self.assertNotIn("NVIDIA", msg)
            self.assertNotIn("gratuit", msg)

    def test_429_on_a_paid_or_other_model_keeps_the_historical_message(self):
        self.assertIn("Limite de débit du fournisseur", self.tr(_err(429, "Rate limit exceeded"), PAID))
        self.assertIn("Limite de débit du fournisseur", self.tr(_err(429, "Rate limit exceeded"), ""))
        self.assertIn("402", self.tr(_err(402, "x"), FREE))
        self.assertIn("llm.env", self.tr(_err(401, "x"), FREE))

    def test_provider_overloaded_free_model_is_the_saturation_message(self):
        for error in (OVERLOADED_UNKNOWN,
                      _err(503, "Service Unavailable", responseBody=json.dumps(OVERLOADED_BODY)),
                      _err(None, "Upstream error from Nvidia: Service temporarily overloaded")):
            msg = self.tr(error, FREE)
            self.assertIn("Le fournisseur du modèle gratuit est saturé", msg)
            self.assertIn("pas votre quota", msg)
            self.assertNotIn("Quota gratuit du jour", msg)
            self.assertNotIn("Erreur du fournisseur", msg)

    def test_provider_overloaded_paid_model_has_its_own_wording(self):
        msg = self.tr(OVERLOADED_UNKNOWN, PAID)
        self.assertIn("fournisseur de ce modèle est saturé", msg)
        self.assertIn("[chat].model", msg)
        self.assertNotIn("gratuit", msg)

    def test_provider_overloaded_other_provider_gets_the_generic_saturation(self):
        msg = self.tr(_err(503, "Overloaded"), "anthropic/claude-sonnet-5-5")
        self.assertIn("saturé", msg)
        self.assertNotIn("Limite de débit", msg)

    def test_a_503_inside_another_number_is_not_saturation(self):
        self.assertFalse(arc_llm.is_provider_overloaded(None, '{"code": 5030}'))
        self.assertFalse(arc_llm.is_provider_overloaded(500, "internal error"))
        self.assertTrue(arc_llm.is_provider_overloaded("503", ""))

    def test_classifier(self):
        self.assertEqual(arc_llm.classify_openrouter_free_error(None, json.dumps(OVERLOADED_BODY), FREE), "upstream")
        self.assertEqual(arc_llm.classify_openrouter_free_error(503, "", PAID), "upstream")
        self.assertEqual(arc_llm.classify_openrouter_free_error(429, "per-day", FREE), "quota")
        self.assertEqual(arc_llm.classify_openrouter_free_error(429, "per-day", PAID), "")
        self.assertEqual(arc_llm.classify_openrouter_free_error(404, "zdr violation", PAID), "privacy")
        self.assertEqual(arc_llm.classify_openrouter_free_error(404, "your data policy", FREE), "privacy")


class TestFreeSessionError(base.OpenCodeCase):
    def test_overloaded_session_error_reaches_the_athlete_as_saturation(self):
        self.backend = O.OpenCodeBackend(self.ws, {"model": FREE})
        scenario = {"events": [
            {"id": "e1", "type": "session.status", "properties": {"sessionID": "$SESSION", "status": {"type": "busy"}}},
            {"id": "e2", "type": "session.error", "properties": {"sessionID": "$SESSION", "error": OVERLOADED_UNKNOWN}}]}
        with self.assertRaises(BackendError) as cm:
            self.run_turn(scenario)
        self.assertIn("modèle gratuit est saturé", str(cm.exception))


class TestFreeBilling(base.OpenCodeCase):
    def test_status_announces_the_free_trial_only_for_free_models(self):
        free = O.OpenCodeBackend(self.ws, {"model": FREE})
        billing = free.billing()
        self.assertEqual(billing["mode"], "free")
        self.assertIn("50 requêtes", billing["quota"])
        self.assertIn("santé", billing["privacy"])
        self.assertIsNone(self.backend.billing())      # modèle payant : inchangé
