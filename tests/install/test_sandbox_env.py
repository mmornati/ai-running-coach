"""Palier A — isolation de l'environnement du bac à sable.

Un identifiant LLM exporté dans le shell du contributeur ne doit jamais
atteindre les scripts testés (ils ne remplacent pas une variable existante).
"""

from __future__ import annotations

import os
import unittest
from unittest import mock

from tests.lib.sandbox import LLM_CREDENTIAL_ENV, Sandbox


class TestSandboxEnvIsolation(unittest.TestCase):
    def test_llm_credentials_do_not_leak_from_parent_env(self):
        fake = {name: "fake-not-a-real-key" for name in LLM_CREDENTIAL_ENV}
        with mock.patch.dict(os.environ, fake):
            with Sandbox() as sb:
                env = sb.env()
        for name in LLM_CREDENTIAL_ENV:
            self.assertNotIn(name, env)

    def test_explicit_extra_credential_is_kept(self):
        with mock.patch.dict(os.environ, {"OPENROUTER_API_KEY": "fake-parent"}):
            with Sandbox() as sb:
                env = sb.env(OPENROUTER_API_KEY="fake-explicit")
        self.assertEqual(env["OPENROUTER_API_KEY"], "fake-explicit")


if __name__ == "__main__":
    unittest.main()
