"""Politique du chat ↔ scripts réellement appelés par les skills et agents.

Un script ajouté à un skill sans entrée dans `config/chat-policy.toml` est refusé dans le
chat : le coach contourne alors (ou abandonne) une étape que le skill impose — observé avec
`arc_guardrails.py` (/week) et `arc_log.py` (/log). Ce lint oblige à trancher : autorisé avec
ses options exactes, ou exclu avec une raison.
"""

from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))

from arc_chat_policy import Policy  # noqa: E402

# Scripts appelés par un skill/agent mais volontairement absents du chat, avec la raison.
EXCLUDED = {
    "scripts/coach_setup.py": "premier démarrage : réécrit la configuration, pas une tâche du chat",
    "skills/mywhoosh-route/scripts/mywhoosh_route.py": "fetch lit le mot de passe MyWhoosh au terminal (getpass) : session interactive uniquement",
}

CALL_RE = re.compile(r"python3 ((?:scripts|skills/[a-z0-9-]+/scripts)/[a-z0-9_]+\.py)")
OPTION_RE = re.compile(r'add_argument\(\s*"(--[a-z0-9-]+)"')


def referenced_scripts() -> set:
    found = set()
    sources = [REPO / "AGENTS.md", *sorted((REPO / "agents").glob("*.md")),
               *sorted((REPO / "skills").glob("*/SKILL.md"))]
    for path in sources:
        found.update(CALL_RE.findall(path.read_text(encoding="utf-8")))
    return found


class ChatPolicyScriptsTest(unittest.TestCase):
    def setUp(self):
        self.policy = Policy.load(REPO, REPO)

    def allowed(self) -> set:
        return {p.split()[-1] for p in self.policy.shell_prefixes}

    def test_chaque_script_appele_est_autorise_ou_exclu(self):
        missing = sorted(s for s in referenced_scripts() if s not in self.allowed() and s not in EXCLUDED)
        self.assertEqual(missing, [], "scripts appelés par un skill/agent mais refusés par le chat — "
                                      "ajoutez-les à config/chat-policy.toml (options exactes) ou à EXCLUDED")

    def test_scripts_autorises_existent(self):
        for script in self.allowed():
            self.assertTrue((REPO / script).is_file(), script)

    def test_options_de_la_politique_existent_dans_argparse(self):
        keys = ("flags", "value_options", "read_options", "output_options", "multi_value_options",
                "optional_value_options", "ask_flags")
        for script, rules in self.policy.shell_scripts.items():
            real = set(OPTION_RE.findall((REPO / script).read_text(encoding="utf-8")))
            declared = {opt for key in keys for opt in rules.get(key, [])}
            self.assertEqual(sorted(declared - real), [], f"{script} : options inconnues de son argparse")

    def test_exclusions_toujours_referencees(self):
        stale = sorted(set(EXCLUDED) - referenced_scripts())
        self.assertEqual(stale, [], "exclusion devenue inutile : à retirer de EXCLUDED")


if __name__ == "__main__":
    unittest.main()
