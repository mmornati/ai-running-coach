"""Palier A — moteur du premier démarrage (scripts/coach_setup.py).

La propriété qui compte : relancer `/coach-setup` ne doit RIEN changer. Sans
cela, un athlète qui relance la commande par curiosité se fait réinterroger et
risque d'écraser ses réglages.
"""

from __future__ import annotations

import json

from tests.lib.asserts import InstallAsserts
from tests.lib.sandbox import Sandbox


class SetupCase(InstallAsserts):
    def setup(self, sb: Sandbox, *args: str):
        return sb.run(["python3", str(sb.repo / "scripts/coach_setup.py"),
                       "--workspace", str(sb.repo), *args])

    def answers(self, sb: Sandbox, mapping: dict) -> str:
        path = sb.root / "answers.json"
        path.write_text(json.dumps(mapping, ensure_ascii=False), encoding="utf-8")
        return str(path)

    def json_out(self, proc) -> dict:
        self.assertSucceeded(proc)
        return json.loads(proc.stdout)


class TestListQuestions(SetupCase):
    def test_lists_everything_on_a_fresh_workspace(self):
        with Sandbox() as sb:
            data = self.json_out(self.setup(sb, "--list-questions"))
            ids = [q["id"] for q in data["pending"]]
            self.assertIn("style", ids)
            self.assertIn("agents", ids)
            self.assertIn("morning_check", ids)

    def test_questions_carry_their_choices(self):
        with Sandbox() as sb:
            data = self.json_out(self.setup(sb, "--list-questions"))
            style = next(q for q in data["pending"] if q["id"] == "style")
            self.assertEqual(style["key"], "coaching.style")
            self.assertEqual(style["kind"], "select")
            values = [c["value"] for c in style["choices"]]
            self.assertEqual(values, ["bienveillant", "exigeant", "factuel", "pedagogue"])
            self.assertTrue(all(c["label"] for c in style["choices"]), "libellés manquants")

    def test_answered_questions_disappear(self):
        with Sandbox() as sb:
            self.setup(sb, "--apply", self.answers(sb, {"coaching.style": "factuel"}))
            data = self.json_out(self.setup(sb, "--list-questions"))
            self.assertNotIn("style", [q["id"] for q in data["pending"]])

    def test_versioned_defaults_do_not_count_as_answers(self):
        """config/workspace.toml ne contient que des défauts : ils ne valent pas réponse."""
        with Sandbox() as sb:
            data = self.json_out(self.setup(sb, "--list-questions"))
            self.assertIn("style", [q["id"] for q in data["pending"]])


class TestApply(SetupCase):
    def test_writes_answers(self):
        with Sandbox() as sb:
            self.setup(sb, "--apply", self.answers(sb, {
                "coaching.style": "exigeant",
                "coaching.intensity": "strong",
                "sport.primary": "road",
                "health.morning_check": "off",
                "agents.enabled": ["coach", "nutritionist"],
            }))
            cfg = (sb.repo / "config/workspace.user.toml").read_text()
            self.assertIn('style = "exigeant"', cfg)
            self.assertIn('primary = "road"', cfg)
            self.assertIn('morning_check = "off"', cfg)
            self.assertIn('enabled = ["coach", "nutritionist"]', cfg)

    def test_rerun_changes_nothing(self):
        with Sandbox() as sb:
            answers = self.answers(sb, {"coaching.style": "factuel", "sport.primary": "road"})
            self.setup(sb, "--apply", answers)
            before = (sb.repo / "config/workspace.user.toml").read_text()
            profile_before = (sb.repo / "planning/Runner_Profile.md").read_text()

            data = self.json_out(self.setup(sb, "--apply", answers))

            self.assertEqual(data["written"], [], "une relance a réécrit des valeurs")
            self.assertEqual((sb.repo / "config/workspace.user.toml").read_text(), before)
            self.assertEqual((sb.repo / "planning/Runner_Profile.md").read_text(), profile_before)

    def test_never_overwrites_an_existing_answer(self):
        with Sandbox() as sb:
            self.setup(sb, "--apply", self.answers(sb, {"coaching.style": "factuel"}))
            self.setup(sb, "--apply", self.answers(sb, {"coaching.style": "exigeant"}))
            self.assertFileContains(sb.repo / "config/workspace.user.toml", 'style = "factuel"')

    def test_rejects_an_unknown_option(self):
        with Sandbox() as sb:
            proc = self.setup(sb, "--apply", self.answers(sb, {"coaching.style": "sarcastique"}))
            self.assertFailed(proc, "valeur hors du catalogue")
            self.assertOutputContains(proc, "bienveillant")

    def test_rejects_an_unknown_question(self):
        with Sandbox() as sb:
            proc = self.setup(sb, "--apply", self.answers(sb, {"coaching.humour": "oui"}))
            self.assertFailed(proc)

    def test_rejects_invalid_json(self):
        with Sandbox() as sb:
            path = sb.root / "bad.json"
            path.write_text("{oops")
            self.assertFailed(self.setup(sb, "--apply", str(path)))

    def test_scaffolds_profile_and_objective(self):
        with Sandbox() as sb:
            self.setup(sb, "--apply", self.answers(sb, {"coaching.style": "factuel"}))
            self.assertIsFile(sb.repo / "planning/Runner_Profile.md")
            self.assertIsFile(sb.repo / "planning/active_objective.md")
            self.assertFileContains(sb.repo / "planning/Runner_Profile.md", "Lieu par défaut")

    def test_never_overwrites_an_existing_profile(self):
        with Sandbox() as sb:
            profile = sb.repo / "planning/Runner_Profile.md"
            profile.parent.mkdir(parents=True, exist_ok=True)
            profile.write_text("# Mon profil à moi\n")
            self.setup(sb, "--apply", self.answers(sb, {"coaching.style": "factuel"}))
            self.assertEqual(profile.read_text(), "# Mon profil à moi\n")

    def test_creates_the_work_directories(self):
        with Sandbox() as sb:
            self.setup(sb, "--scaffold")
            for name in ("activities", "medical", "nutrition", "planning", "rapports", "resources"):
                self.assertTrue((sb.repo / name).is_dir(), f"{name}/ manquant")


class TestStatus(SetupCase):
    def test_reports_a_fresh_workspace(self):
        with Sandbox() as sb:
            data = self.json_out(self.setup(sb, "--status"))
            self.assertFalse(data["configured"])
            self.assertTrue(data["pending_questions"])
            self.assertFalse(any(data["profile"].values()))

    def test_reports_a_configured_workspace(self):
        with Sandbox() as sb:
            every = {
                "coaching.style": "factuel", "coaching.intensity": "balanced",
                "coaching.verbosity": "brief", "sport.primary": "trail",
                "sport.disciplines": ["cycling"], "agents.enabled": ["coach"],
                "health.morning_check": "full", "language.documents": "fr",
                "language.responses": "auto", "athlete.units": "metric",
            }
            self.setup(sb, "--apply", self.answers(sb, every))
            data = self.json_out(self.setup(sb, "--status"))
            self.assertTrue(data["configured"])
            self.assertEqual(data["pending_questions"], [])
            self.assertTrue(all(data["profile"].values()))
            self.assertEqual(data["next"], "rien à faire")

    def test_flags_an_unprotected_personal_config(self):
        with Sandbox() as sb:
            (sb.repo / ".gitignore").write_text("logs/\n")
            data = self.json_out(self.setup(sb, "--status"))
            self.assertFalse(
                data["personal_config_gitignored"],
                "un .gitignore sans la config personnelle doit être signalé",
            )
