"""Palier C — exécution réelle des prompts avec un modèle léger.

Non déterministe et facturé. Chaque cas est répété N fois et passe sur un
**seuil**, pas à l'unanimité : une seule exécution n'est pas un test.

Ignoré, jamais en échec, sans `ARC_LLM_TESTS=1` et un runner authentifié — un
contributeur sans accès modèle doit voir des tests ignorés, pas une suite rouge.
"""

from __future__ import annotations

import re
import tempfile
import unittest
from pathlib import Path

from tests.evals import mcp_stub_common, runner, stub_garmin_mcp, stub_intervals_mcp


class TestCaseFilesAreValid(unittest.TestCase):
    """Ce contrôle-là ne coûte rien et tourne même sans modèle."""

    KNOWN_EXPECTATIONS = {
        "must_match", "must_not_match", "tools_called", "tools_not_called",
        "files_created", "max_words", "first_line_matches", "files_with_arc_block", "files_absent",
        "arc_field", "arc_field_absent", "tool_args_match", "sqlite_query", "file_contains_any",
    }

    # Dérivés des modules qui font foi, pas dupliqués : un stub retiré de
    # `runner.STUB_SCRIPTS`, ou un type d'erreur ajouté à
    # `mcp_stub_common.ERROR_KINDS`, se répercute ici sans y toucher.
    KNOWN_STUB_SERVERS = set(runner.STUB_SCRIPTS)
    KNOWN_STUB_ERRORS = mcp_stub_common.ERROR_KINDS
    STUB_TOOL_NAMES = {
        "garmin": {name for name, _ in stub_garmin_mcp.TOOLS},
        "intervals": {name for name, _ in stub_intervals_mcp.TOOLS},
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

    def test_stub_section_is_well_formed(self):
        """Une section `[stub]` mal écrite ne scripte rien silencieusement :
        un serveur ou un type d'erreur inconnu doit faire échouer le chargement,
        pas juste être ignoré par le stub (voir `mcp_stub_common.resolve_content`,
        qui lève sur un `error` inconnu — cette assertion attrape la même classe
        de faute plus tôt, sans lancer de sous-processus)."""
        for case in self.cases:
            stub = case.get("stub", {})
            with self.subTest(case=case["id"]):
                unknown_servers = set(stub) - self.KNOWN_STUB_SERVERS
                self.assertFalse(unknown_servers, f"serveur(s) stub inconnu(s) : {sorted(unknown_servers)}")
                for server, tools in stub.items():
                    self.assertIsInstance(tools, dict, f"[stub.{server}] doit être une table d'outils")
                    known_tools = self.STUB_TOOL_NAMES.get(server, set())
                    for tool, override in tools.items():
                        with self.subTest(case=case["id"], server=server, tool=tool):
                            self.assertIn(
                                tool, known_tools,
                                f"[stub.{server}.{tool}] : outil inconnu du stub {server} "
                                f"(tools/list n'en parle pas — le cas scripte un outil qui n'existe pas)",
                            )
                            self.assertIsInstance(override, dict, f"[stub.{server}.{tool}] doit être une table")
                            has_file = "file" in override
                            has_error = "error" in override
                            self.assertTrue(
                                has_file or has_error,
                                f"[stub.{server}.{tool}] doit déclarer `file` ou `error`",
                            )
                            self.assertFalse(
                                has_file and has_error,
                                f"[stub.{server}.{tool}] ne peut pas déclarer `file` ET `error`",
                            )
                            if has_error:
                                self.assertIn(
                                    override["error"], self.KNOWN_STUB_ERRORS,
                                    f"[stub.{server}.{tool}] error inconnue : {override['error']!r}",
                                )
                            if has_file:
                                # Même borne que `mcp_stub_common.resolve_content` : un
                                # `file` qui s'évaderait de `stub-responses/` (chemin
                                # absolu, `../..`) doit échouer ici, pas seulement à
                                # l'exécution du stub.
                                base = (runner.FIXTURES_DIR / "stub-responses").resolve()
                                candidate = (base / override["file"]).resolve()
                                self.assertTrue(
                                    candidate == base or base in candidate.parents,
                                    f"[stub.{server}.{tool}] file en dehors de stub-responses/ : "
                                    f"{override['file']!r}",
                                )
                                self.assertTrue(
                                    candidate.is_file(),
                                    f"[stub.{server}.{tool}] fichier introuvable : {candidate}",
                                )

    def test_arc_field_assertions_are_well_formed(self):
        """`arc_field` (#27) : `glob`/`path` obligatoires, chemin syntaxiquement
        valide, exactement un comparateur parmi equals|min|max|in, min/max
        numériques, `in` en liste — sinon le cas ne teste rien de fiable."""
        allowed_keys = {"glob", "path"} | set(runner.ARC_FIELD_COMPARATORS)
        for case in self.cases:
            for assertion in runner._as_list(case["expect"].get("arc_field")):
                with self.subTest(case=case["id"], assertion=assertion):
                    self.assertIn("glob", assertion, "arc_field : 'glob' manquant")
                    self.assertIn("path", assertion, "arc_field : 'path' manquant")
                    try:
                        runner._parse_json_path(assertion["path"])
                    except ValueError as exc:
                        self.fail(f"arc_field : chemin invalide {assertion['path']!r} : {exc}")
                    unknown = set(assertion) - allowed_keys
                    self.assertFalse(unknown, f"arc_field : clé(s) inconnue(s) {sorted(unknown)}")
                    comparators = set(assertion) & set(runner.ARC_FIELD_COMPARATORS)
                    self.assertEqual(
                        len(comparators), 1,
                        f"arc_field : exactement un comparateur attendu (equals|min|max|in), trouvé {sorted(comparators)}",
                    )
                    comparator = next(iter(comparators))
                    value = assertion[comparator]
                    if comparator in ("min", "max"):
                        self.assertTrue(
                            runner._is_numeric(value), f"arc_field : {comparator} doit être numérique (trouvé {value!r})"
                        )
                    if comparator == "in":
                        self.assertIsInstance(value, list, "arc_field : 'in' doit être une liste")

    def test_arc_field_absent_assertions_are_well_formed(self):
        """`arc_field_absent` (#51) : 'glob'/'paths' obligatoires, 'paths' une
        liste non vide de chemins syntaxiquement valides — le pendant négatif
        d'`arc_field` (voir sa docstring dans `runner.py` pour pourquoi
        `arc_field` lui-même ne peut pas exprimer une absence)."""
        allowed_keys = {"glob", "paths"}
        for case in self.cases:
            for assertion in runner._as_list(case["expect"].get("arc_field_absent")):
                with self.subTest(case=case["id"], assertion=assertion):
                    self.assertIn("glob", assertion, "arc_field_absent : 'glob' manquant")
                    self.assertIn("paths", assertion, "arc_field_absent : 'paths' manquant")
                    unknown = set(assertion) - allowed_keys
                    self.assertFalse(unknown, f"arc_field_absent : clé(s) inconnue(s) {sorted(unknown)}")
                    paths = assertion["paths"]
                    self.assertIsInstance(paths, list, "arc_field_absent : 'paths' doit être une liste")
                    self.assertTrue(paths, "arc_field_absent : 'paths' ne doit pas être vide")
                    for path_expr in paths:
                        try:
                            runner._parse_json_path(path_expr)
                        except ValueError as exc:
                            self.fail(f"arc_field_absent : chemin invalide {path_expr!r} : {exc}")

    def test_tool_args_match_assertions_are_well_formed(self):
        """`tool_args_match` (#27) : `tool`/`path` obligatoires, chemin valide,
        `server` connu, `tool` dans les outils réellement exposés par ce stub
        (ou par n'importe lequel si `server` est omis), exactement un
        comparateur, min/max numériques, regex qui compile."""
        all_known_tools = set()
        for names in self.STUB_TOOL_NAMES.values():
            all_known_tools |= names
        allowed_keys = {"tool", "path", "server"} | set(runner.TOOL_ARGS_COMPARATORS)
        for case in self.cases:
            for assertion in runner._as_list(case["expect"].get("tool_args_match")):
                with self.subTest(case=case["id"], assertion=assertion):
                    self.assertIn("tool", assertion, "tool_args_match : 'tool' manquant")
                    self.assertIn("path", assertion, "tool_args_match : 'path' manquant")
                    try:
                        runner._parse_json_path(assertion["path"])
                    except ValueError as exc:
                        self.fail(f"tool_args_match : chemin invalide {assertion['path']!r} : {exc}")
                    server = assertion.get("server")
                    if server is not None:
                        self.assertIn(server, self.KNOWN_STUB_SERVERS, f"tool_args_match : serveur inconnu {server!r}")
                        known_tools = self.STUB_TOOL_NAMES.get(server, set())
                    else:
                        known_tools = all_known_tools
                    self.assertIn(
                        assertion["tool"], known_tools,
                        f"tool_args_match : outil inconnu du stub {assertion['tool']!r}",
                    )
                    unknown = set(assertion) - allowed_keys
                    self.assertFalse(unknown, f"tool_args_match : clé(s) inconnue(s) {sorted(unknown)}")
                    comparators = set(assertion) & set(runner.TOOL_ARGS_COMPARATORS)
                    self.assertEqual(
                        len(comparators), 1,
                        f"tool_args_match : exactement un comparateur attendu (equals|min|max|regex), trouvé {sorted(comparators)}",
                    )
                    comparator = next(iter(comparators))
                    value = assertion[comparator]
                    if comparator in ("min", "max"):
                        self.assertTrue(
                            runner._is_numeric(value), f"tool_args_match : {comparator} doit être numérique (trouvé {value!r})"
                        )
                    if comparator == "regex":
                        try:
                            re.compile(str(value))
                        except re.error as exc:
                            self.fail(f"tool_args_match : regex invalide {value!r} : {exc}")

    def test_sqlite_query_assertions_are_well_formed(self):
        """`sqlite_query` (#27) : une seule instruction de lecture, exactement
        un comparateur, min/max numériques. Le vrai garde-fou reste la
        connexion `mode=ro` de `_check_sqlite_queries` — ce test ne verrouille
        que la lisibilité du refus."""
        allowed_keys = {"sql"} | set(runner.SQLITE_COMPARATORS)
        for case in self.cases:
            for assertion in runner._as_list(case["expect"].get("sqlite_query")):
                with self.subTest(case=case["id"], assertion=assertion):
                    self.assertIn("sql", assertion, "sqlite_query : 'sql' manquant")
                    problem = runner._validate_single_read_statement(assertion["sql"])
                    self.assertIsNone(problem, f"sqlite_query : {problem}")
                    unknown = set(assertion) - allowed_keys
                    self.assertFalse(unknown, f"sqlite_query : clé(s) inconnue(s) {sorted(unknown)}")
                    comparators = set(assertion) & set(runner.SQLITE_COMPARATORS)
                    self.assertEqual(
                        len(comparators), 1,
                        f"sqlite_query : exactement un comparateur attendu (equals|min|max), trouvé {sorted(comparators)}",
                    )
                    comparator = next(iter(comparators))
                    value = assertion[comparator]
                    if comparator in ("min", "max"):
                        self.assertTrue(
                            runner._is_numeric(value), f"sqlite_query : {comparator} doit être numérique (trouvé {value!r})"
                        )

    def test_file_contains_any_assertions_are_well_formed(self):
        """`file_contains_any` (#27) : `glob`/`any` obligatoires, `any` est
        une liste non vide — une liste vide ne pourrait jamais être satisfaite."""
        for case in self.cases:
            for assertion in runner._as_list(case["expect"].get("file_contains_any")):
                with self.subTest(case=case["id"], assertion=assertion):
                    self.assertIn("glob", assertion, "file_contains_any : 'glob' manquant")
                    self.assertIn("any", assertion, "file_contains_any : 'any' manquant")
                    self.assertIsInstance(assertion["any"], list, "file_contains_any : 'any' doit être une liste")
                    self.assertTrue(assertion["any"], "file_contains_any : 'any' ne doit pas être vide")
                    unknown = set(assertion) - {"glob", "any"}
                    self.assertFalse(unknown, f"file_contains_any : clé(s) inconnue(s) {sorted(unknown)}")

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

    def test_tokens_section_is_well_formed(self):
        """`[tokens]` (#31/#32) : seule clé connue `expires_in_days`, un nombre."""
        for case in self.cases:
            tokens = case.get("tokens")
            if tokens is None:
                continue
            with self.subTest(case=case["id"]):
                unknown = set(tokens) - {"expires_in_days"}
                self.assertFalse(unknown, f"[tokens] : clé(s) inconnue(s) {sorted(unknown)}")
                if "expires_in_days" in tokens:
                    self.assertIsInstance(
                        tokens["expires_in_days"], (int, float),
                        "[tokens].expires_in_days doit être un nombre",
                    )


class TestRelativeDateFixtures(unittest.TestCase):
    """#34 — `<N>d_...` (`runner._materialize_relative_dates`) : sans LLM, sans réseau,
    aucune raison de dépendre de `ARC_LLM_TESTS`. Verrouille le mécanisme qui garde
    `fixtures/health-own-baseline/` fraîche quelle que soit la date du run — un
    historique HRV figé à des dates de plus en plus lointaines finirait par sortir de
    la fenêtre de référence 60 j et changer silencieusement le comportement attendu."""

    def test_offsets_become_real_dates_relative_to_today(self):
        import datetime
        case = {"id": "health-own-baseline", "fixture": "health-own-baseline"}
        with tempfile.TemporaryDirectory(prefix="arc-eval-relative-dates-") as tmp:
            workspace = runner.build_workspace(Path(tmp), case)
            names = sorted(p.name for p in (workspace / "medical").glob("*.md"))
            self.assertEqual(len(names), 40, "40 jours d'historique attendus dans la fixture")
            self.assertFalse(
                any(re.match(r"^\d+d_", n) for n in names),
                f"nom(s) non matérialisé(s) : {[n for n in names if re.match(r'^\\d+d_', n)]}",
            )
            for path in (workspace / "medical").glob("*.md"):
                self.assertNotIn("{{DATE}}", path.read_text(encoding="utf-8"), f"{path.name} : placeholder non substitué")
                # Le nom encode la date réelle : elle doit être analysable et dans le passé récent.
                iso = path.stem.split("_", 1)[0]
                day = datetime.date.fromisoformat(iso)
                self.assertLessEqual(day, datetime.date.today())
                self.assertGreaterEqual(day, datetime.date.today() - datetime.timedelta(days=40))

    def test_new_files_excludes_materialized_fixture_files(self):
        """`_new_files` (utilisé par `file_contains_any`) ne doit pas prendre les fichiers
        de fixture renommés (dates réelles) pour des fichiers écrits par l'agent — sans
        quoi l'assertion `file_contains_any` du cas `health-own-baseline` pourrait passer
        sur un vieux fichier d'historique au lieu du fichier réellement écrit pendant le
        run, ou pire, échouer à tort si aucun des 40 fichiers ne contient la notion."""
        case = {"id": "health-own-baseline", "fixture": "health-own-baseline"}
        with tempfile.TemporaryDirectory(prefix="arc-eval-relative-dates-") as tmp:
            workspace = runner.build_workspace(Path(tmp), case)
            result = {"workspace": workspace}
            self.assertEqual(runner._new_files(case, result, "medical/*.md"), [],
                             "les 40 fichiers de la fixture ne doivent pas compter comme écrits par le run")
            new_file = workspace / "medical/2099-01-01_health.md"
            new_file.write_text("# Santé\n\nréférence personnelle : sous la norme.\n", encoding="utf-8")
            self.assertEqual(runner._new_files(case, result, "medical/*.md"), [new_file])


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
        # Toujours enregistré, échec ou pas (#29) : c'est ce qui permet à
        # `render_results.py` de produire un RESULTS.md fidèle même quand la
        # suite se termine avec des échecs — un cas en échec doit apparaître au
        # tableau, pas disparaître avec le reste de la suite.
        runner.record_result(case["id"], passed, attempts)
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
