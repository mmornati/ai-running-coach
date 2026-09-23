"""Palier C — exécution réelle des prompts avec un modèle léger.

Non déterministe et facturé. Chaque cas est répété N fois et passe sur un
**seuil**, pas à l'unanimité : une seule exécution n'est pas un test.

Ignoré, jamais en échec, sans `ARC_LLM_TESTS=1` et un runner authentifié — un
contributeur sans accès modèle doit voir des tests ignorés, pas une suite rouge.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tests.evals import runner


class TestCaseFilesAreValid(unittest.TestCase):
    """Ce contrôle-là ne coûte rien et tourne même sans modèle."""

    KNOWN_EXPECTATIONS = {
        "must_match", "must_not_match", "tools_called", "tools_not_called",
        "files_created", "max_words", "first_line_matches", "files_with_arc_block", "files_absent",
    }

    def setUp(self):
        self.cases = runner.load_cases()

    def test_there_are_cases(self):
        self.assertTrue(self.cases, "aucun scénario dans tests/evals/cases/")

    def test_every_case_is_well_formed(self):
        for case in self.cases:
            with self.subTest(case=case["id"]):
                self.assertIn("prompt", case, "scénario sans prompt")
                self.assertIn("expect", case, "scénario sans attentes")
                unknown = set(case["expect"]) - self.KNOWN_EXPECTATIONS
                self.assertFalse(unknown, f"attentes inconnues : {sorted(unknown)}")

    def test_every_fixture_exists(self):
        for case in self.cases:
            with self.subTest(case=case["id"]):
                fixture = runner.FIXTURES_DIR / case.get("fixture", "base-week")
                self.assertTrue(fixture.is_dir(), f"fixture absente : {fixture}")

    def test_regexes_compile(self):
        import re

        for case in self.cases:
            for field in ("must_match", "must_not_match", "first_line_matches"):
                for pattern in runner._as_list(case["expect"].get(field)):
                    with self.subTest(case=case["id"], pattern=pattern):
                        re.compile(pattern)

    def test_config_keys_exist_in_the_schema(self):
        """Un scénario qui règle une clé inexistante ne teste rien."""
        import tomllib

        schema = tomllib.loads((runner.REPO / "config/workspace.toml").read_text(encoding="utf-8"))
        for case in self.cases:
            for section, values in case.get("config", {}).items():
                with self.subTest(case=case["id"], section=section):
                    self.assertIn(section, schema, f"[{section}] absent de config/workspace.toml")
                    unknown = set(values) - set(schema[section])
                    self.assertFalse(unknown, f"clés inconnues dans [{section}] : {sorted(unknown)}")


@unittest.skipIf(runner.skip_reason(), runner.skip_reason() or "palier C désactivé")
class TestPromptBehaviour(unittest.TestCase):
    """Un test par scénario, généré au chargement du module."""

    maxDiff = None

    def _run_case(self, case: dict):
        attempts, failures_by_run = runner.repeat(), []
        for attempt in range(attempts):
            with tempfile.TemporaryDirectory(prefix=f"arc-eval-{case['id']}-") as tmp:
                workspace = runner.build_workspace(Path(tmp), case)
                result = runner.run_case(case, workspace)
                if runner.looks_unauthenticated(result):
                    self.skipTest(
                        f"{runner.runner_command()[0]} n'est pas authentifié dans cet "
                        "environnement — connectez-vous puis relancez avec ARC_LLM_TESTS=1."
                    )
                failures_by_run.append(runner.check(case, result))

        passed = sum(1 for f in failures_by_run if not f)
        rate = passed / attempts
        if rate < runner.threshold():
            detail = "\n".join(
                f"  exécution {i + 1} : " + ("ok" if not f else "; ".join(f))
                for i, f in enumerate(failures_by_run)
            )
            self.fail(
                f"{case['id']} : {passed}/{attempts} réussites "
                f"(seuil {runner.threshold():.0%})\n{detail}\n  source : {case['source']}"
            )


def _attach_cases() -> None:
    for case in runner.load_cases():
        def test(self, case=case):
            self._run_case(case)

        test.__name__ = f"test_{case['id'].replace('-', '_')}"
        test.__doc__ = (case.get("description") or case["id"]).strip()
        setattr(TestPromptBehaviour, test.__name__, test)


_attach_cases()
