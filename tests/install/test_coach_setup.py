"""Palier A — moteur du premier démarrage (scripts/coach_setup.py).

La propriété qui compte : relancer `/coach-setup` ne doit RIEN changer. Sans
cela, un athlète qui relance la commande par curiosité se fait réinterroger et
risque d'écraser ses réglages.
"""

from __future__ import annotations

import json
import re

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
            for name in ("activities", "medical", "nutrition", "planning", "rapports", "resources", "gear"):
                self.assertTrue((sb.repo / name).is_dir(), f"{name}/ manquant")


class TestExportState(SetupCase):
    def test_empty_templates_do_not_invent_an_objective_from_the_revision_table(self):
        with Sandbox() as sb:
            self.setup(sb, "--scaffold")
            data = self.json_out(self.setup(sb, "--export-state"))
            self.assertEqual(data["profile"], {})
            self.assertEqual(data["objective"], {})
            self.assertEqual(data["shoes"], [])

    def test_exports_profile_objective_and_structured_shoes_for_the_app(self):
        with Sandbox() as sb:
            self.setup(sb, "--scaffold")
            self.setup(sb, "--apply-profile", self.answers(sb, {
                "Prénom / surnom": "Camille",
                "Ce qui me motive": "Les grands objectifs",
            }))
            self.setup(sb, "--apply-objective", self.answers(sb, {
                "Nom": "Trail des Crêtes",
                "Date": "2027-06-12",
            }))
            self.setup(sb, "--apply-shoes", self.answers(sb, [{
                "name": "Hoka Speedgoat 6",
                "start_date": "2026-09-01",
                "threshold_km": "750",
                "start_km": "42.5",
                "usage": "trail",
            }]))

            data = self.json_out(self.setup(sb, "--export-state"))

            self.assertEqual(data["profile"]["prenom / surnom"], "Camille")
            self.assertEqual(data["profile"]["ce qui me motive"], "Les grands objectifs")
            self.assertEqual(data["objective"]["nom"], "Trail des Crêtes")
            self.assertEqual(data["objective"]["date"], "2027-06-12")
            self.assertEqual(data["shoes"], [{
                "name": "Hoka Speedgoat 6",
                "purchase_date": "2026-09-01",
                "threshold_km": "750",
                "starting_km": "42.5",
                "usage": "trail",
            }])


class TestApplyProfile(SetupCase):
    """Story #65 — pré-remplissage Garmin confirmé, fusionné dans
    `planning/Runner_Profile.md` sans jamais écraser un champ déjà rempli."""

    def test_requires_the_profile_to_already_exist(self):
        with Sandbox() as sb:
            proc = self.setup(sb, "--apply-profile", self.answers(sb, {"FC max": "182"}))
            self.assertFailed(proc, "profil pas encore installé")
            self.assertOutputContains(proc, "--apply")

    def test_writes_confirmed_values_with_provenance(self):
        with Sandbox() as sb:
            self.setup(sb, "--scaffold")
            data = self.json_out(self.setup(sb, "--apply-profile", self.answers(sb, {
                "FC max": {"value": "182", "source": "Garmin (get_stats), 2026-09-27"},
                "FC de repos de référence": "47",
            })))
            self.assertEqual(sorted(data["written"]), ["FC de repos de référence", "FC max"])
            profile = (sb.repo / "planning/Runner_Profile.md").read_text()
            self.assertIn("**FC max** : 182 <!-- source : Garmin (get_stats), 2026-09-27 -->", profile)
            self.assertIn("**FC de repos de référence** : 47", profile)

    def test_never_overwrites_an_existing_profile_field(self):
        with Sandbox() as sb:
            self.setup(sb, "--scaffold")
            self.setup(sb, "--apply-profile", self.answers(sb, {"FC max": "182"}))
            data = self.json_out(self.setup(sb, "--apply-profile", self.answers(sb, {"FC max": "999"})))
            self.assertEqual(data["written"], [])
            self.assertEqual(data["skipped"], ["FC max"])
            self.assertFileContains(sb.repo / "planning/Runner_Profile.md", "**FC max** : 182")

    def test_fills_only_empty_fields_alongside_an_athlete_edited_one(self):
        with Sandbox() as sb:
            self.setup(sb, "--scaffold")
            profile = sb.repo / "planning/Runner_Profile.md"
            profile.write_text(profile.read_text().replace(
                "- **FC max** :", "- **FC max** : 175  <!-- valeur perso, mesurée en labo -->"
            ))
            data = self.json_out(self.setup(sb, "--apply-profile", self.answers(sb, {
                "FC max": "182", "FC de repos de référence": "47",
            })))
            self.assertEqual(data["written"], ["FC de repos de référence"])
            self.assertEqual(data["skipped"], ["FC max"])
            content = profile.read_text()
            self.assertIn("175", content)
            self.assertNotIn("182", content)

    def test_rerun_is_idempotent(self):
        with Sandbox() as sb:
            self.setup(sb, "--scaffold")
            answers = self.answers(sb, {"FC max": "182", "VO2max (Garmin)": "52"})
            self.setup(sb, "--apply-profile", answers)
            before = (sb.repo / "planning/Runner_Profile.md").read_text()

            data = self.json_out(self.setup(sb, "--apply-profile", answers))

            self.assertEqual(data["written"], [], "une relance a réécrit des valeurs")
            self.assertEqual((sb.repo / "planning/Runner_Profile.md").read_text(), before)

    def test_rejects_an_unknown_profile_label(self):
        with Sandbox() as sb:
            self.setup(sb, "--scaffold")
            proc = self.setup(sb, "--apply-profile", self.answers(sb, {"FC de croisière": "150"}))
            self.assertFailed(proc, "libellé inconnu")
            self.assertOutputContains(proc, "jamais inventé")

    def test_blank_value_is_skipped_never_invented(self):
        with Sandbox() as sb:
            self.setup(sb, "--scaffold")
            data = self.json_out(self.setup(sb, "--apply-profile", self.answers(sb, {"FC max": "  "})))
            self.assertEqual(data["written"], [])
            self.assertEqual(data["skipped"], ["FC max"])

    def test_json_null_is_skipped_never_written_as_the_word_none(self):
        """Revue de code #112 : un `null` JSON (`None` côté Python) ne doit
        jamais finir écrit tel quel (`str(None)` = « None ») — un bug qui
        verrouille le champ pour toujours, puisqu'il compterait alors comme
        rempli."""
        with Sandbox() as sb:
            self.setup(sb, "--scaffold")
            data = self.json_out(self.setup(sb, "--apply-profile", self.answers(sb, {
                "FC max": None, "FC au seuil": {"value": None, "source": "Garmin"},
            })))
            self.assertEqual(data["written"], [])
            self.assertEqual(sorted(data["skipped"]), ["FC au seuil", "FC max"])
            content = (sb.repo / "planning/Runner_Profile.md").read_text()
            self.assertNotIn("None", content)

    def test_asterisks_only_value_is_treated_as_blank(self):
        """`« ** »` disparaîtrait entièrement une fois `**` retiré par tout
        lecteur du fichier (revue de code #112, 2ᵉ tour) — jamais une valeur
        à écrire, même si la ligne semble « remplie » avant nettoyage."""
        with Sandbox() as sb:
            self.setup(sb, "--scaffold")
            data = self.json_out(self.setup(sb, "--apply-profile", self.answers(sb, {"FC max": "**"})))
            self.assertEqual(data["written"], [])
            self.assertEqual(data["skipped"], ["FC max"])

    def test_rejects_a_boolean_value(self):
        """`bool` est une sous-classe d'`int` en Python : sans un contrôle
        dédié, `{"FC max": true}` passerait la validation « chaîne ou nombre »
        et écrirait le texte littéral « True » (revue de code #112, 3ᵉ tour)."""
        with Sandbox() as sb:
            self.setup(sb, "--scaffold")
            proc = self.setup(sb, "--apply-profile", self.answers(sb, {"FC max": True}))
            self.assertFailed(proc, "booléen refusé comme valeur")
            self.assertOutputContains(proc, "booléen")
            content = (sb.repo / "planning/Runner_Profile.md").read_text()
            self.assertNotIn("True", content)

    def test_rejects_a_boolean_source(self):
        with Sandbox() as sb:
            self.setup(sb, "--scaffold")
            proc = self.setup(sb, "--apply-profile", self.answers(sb, {
                "FC max": {"value": "182", "source": False},
            }))
            self.assertFailed(proc, "booléen refusé comme source")
            self.assertOutputContains(proc, "booléen")

    def test_rejects_a_list_value(self):
        with Sandbox() as sb:
            self.setup(sb, "--scaffold")
            proc = self.setup(sb, "--apply-profile", self.answers(sb, {"FC max": [182, 183]}))
            self.assertFailed(proc, "liste refusée comme valeur")
            self.assertOutputContains(proc, "liste")

    def test_rejects_a_dict_value(self):
        with Sandbox() as sb:
            self.setup(sb, "--scaffold")
            proc = self.setup(sb, "--apply-profile", self.answers(sb, {
                "FC max": {"value": {"nested": "object"}, "source": "x"},
            }))
            self.assertFailed(proc, "objet refusé comme valeur")
            self.assertOutputContains(proc, "objet")

    def test_rejects_a_list_source(self):
        with Sandbox() as sb:
            self.setup(sb, "--scaffold")
            proc = self.setup(sb, "--apply-profile", self.answers(sb, {
                "FC max": {"value": "182", "source": ["a", "b"]},
            }))
            self.assertFailed(proc, "liste refusée comme source")

    def test_rejects_a_newline_in_the_value(self):
        with Sandbox() as sb:
            self.setup(sb, "--scaffold")
            proc = self.setup(sb, "--apply-profile", self.answers(sb, {
                "FC max": {"value": "182\n- **FC au seuil** : 999", "source": "x"},
            }))
            self.assertFailed(proc, "retour à la ligne dans la valeur")
            self.assertOutputContains(proc, "retour à la ligne")
            content = (sb.repo / "planning/Runner_Profile.md").read_text()
            self.assertNotIn("999", content, "aucune ligne injectée : le fichier n'a pas dû être touché")

    def test_rejects_a_newline_in_the_source(self):
        with Sandbox() as sb:
            self.setup(sb, "--scaffold")
            proc = self.setup(sb, "--apply-profile", self.answers(sb, {
                "FC max": {"value": "182", "source": "Garmin\n- **Sexe** : H"},
            }))
            self.assertFailed(proc, "retour à la ligne dans la source")
            self.assertOutputContains(proc, "retour à la ligne")

    def test_rejects_a_double_dash_in_the_source(self):
        """`--` fermerait prématurément le commentaire HTML `<!-- source : ... -->`."""
        with Sandbox() as sb:
            self.setup(sb, "--scaffold")
            proc = self.setup(sb, "--apply-profile", self.answers(sb, {
                "FC max": {"value": "182", "source": "x --> <script>y</script>"},
            }))
            self.assertFailed(proc, "-- dans la source")
            self.assertOutputContains(proc, "--")
            content = (sb.repo / "planning/Runner_Profile.md").read_text()
            self.assertNotIn("<script>", content)

    def test_rejects_an_html_comment_in_the_value(self):
        with Sandbox() as sb:
            self.setup(sb, "--scaffold")
            proc = self.setup(sb, "--apply-profile", self.answers(sb, {"FC max": "182 <!-- oops -->"}))
            self.assertFailed(proc, "commentaire HTML dans la valeur")
            self.assertOutputContains(proc, "commentaire HTML")

    def test_field_filled_via_indented_sub_bullets_counts_as_filled(self):
        """« Zones / seuils » sans valeur sur sa propre ligne, mais suivi d'une
        sous-liste indentée (Z1/Z2/...), compte comme déjà rempli — jamais de
        réécriture par-dessus une sous-liste existante."""
        with Sandbox() as sb:
            self.setup(sb, "--scaffold")
            profile = sb.repo / "planning/Runner_Profile.md"
            profile.write_text(profile.read_text().replace(
                "- **Zones / seuils** :",
                "- **Zones / seuils** :\n  - Z1 : 120-135\n  - Z2 : 136-150",
            ))
            before = profile.read_text()
            data = self.json_out(self.setup(sb, "--apply-profile", self.answers(sb, {"Zones / seuils": "Z2 140-155"})))
            self.assertEqual(data["written"], [])
            self.assertEqual(data["skipped"], ["Zones / seuils"])
            self.assertEqual(profile.read_text(), before)

    def test_accepts_the_bold_colon_label_style_when_empty(self):
        """`- **FC max :**` (deux-points DANS le gras) est un style toléré par
        `arc_legacy.parse_bullets` — doit être reconnu comme le même champ,
        pas comme un libellé inconnu, et le `**` fermant ne doit JAMAIS
        disparaître à l'écriture (revue de code #112, 2ᵉ tour :
        « - **FC max :** 182 » devenait « - **FC max : 182 »)."""
        with Sandbox() as sb:
            self.setup(sb, "--scaffold")
            profile = sb.repo / "planning/Runner_Profile.md"
            profile.write_text(profile.read_text().replace("- **FC max** :", "- **FC max :**"))
            data = self.json_out(self.setup(sb, "--apply-profile", self.answers(sb, {"FC max": "182"})))
            self.assertEqual(data["written"], ["FC max"])
            self.assertFileContains(profile, "- **FC max :** 182")
            self.assertFileLacks(profile, "- **FC max : 182")

    def test_accepts_the_bold_colon_label_style_with_a_hint_comment(self):
        """Même style, mais le champ porte en plus le commentaire d'aide du
        modèle — le `**` fermant ET le commentaire doivent survivre."""
        with Sandbox() as sb:
            self.setup(sb, "--scaffold")
            profile = sb.repo / "planning/Runner_Profile.md"
            profile.write_text(profile.read_text().replace(
                "- **FC au seuil** : <!-- FC tenue ~1 h à fond (seuil lactique), ex. 172 -->",
                "- **FC au seuil :** <!-- FC tenue ~1 h à fond (seuil lactique), ex. 172 -->",
            ))
            data = self.json_out(self.setup(sb, "--apply-profile", self.answers(sb, {"FC au seuil": "168"})))
            self.assertEqual(data["written"], ["FC au seuil"])
            self.assertFileContains(profile, "- **FC au seuil :** 168 <!-- FC tenue")
            self.assertFileLacks(profile, "- **FC au seuil : 168")

    def test_bold_colon_label_style_already_filled_is_never_overwritten(self):
        with Sandbox() as sb:
            self.setup(sb, "--scaffold")
            profile = sb.repo / "planning/Runner_Profile.md"
            profile.write_text(profile.read_text().replace("- **FC max** :", "- **FC max :** 175"))
            data = self.json_out(self.setup(sb, "--apply-profile", self.answers(sb, {"FC max": "999"})))
            self.assertEqual(data["written"], [])
            self.assertEqual(data["skipped"], ["FC max"])
            self.assertFileContains(profile, "175")
            content = profile.read_text()
            self.assertNotIn("999", content)


class TestApplyShoes(SetupCase):
    """Assistant macOS : saisie structurée des chaussures dans le profil."""

    def test_adds_multiple_shoes_and_only_the_first_is_default(self):
        with Sandbox() as sb:
            self.setup(sb, "--scaffold")
            data = self.json_out(self.setup(sb, "--apply-shoes", self.answers(sb, [
                {"name": "Hoka Speedgoat 6", "start_date": "2026-09-01", "threshold_km": "700", "usage": "trail"},
                {"name": "Nike Pegasus", "start_km": "125.5", "usage": "route"},
            ])))
            self.assertEqual(data["added"], ["Hoka Speedgoat 6", "Nike Pegasus"])
            profile = (sb.repo / "planning/Runner_Profile.md").read_text()
            self.assertIn("- Hoka Speedgoat 6 — depuis 2026-09-01 — alerte 700 km — usage: trail (par défaut)", profile)
            self.assertIn("- Nike Pegasus — départ 125.5 km — usage: route", profile)
            visible = re.sub(r"<!--.*?-->", "", profile, flags=re.S)
            self.assertEqual(visible.count("(par défaut)"), 1)

    def test_rerun_skips_existing_name_without_rewriting(self):
        with Sandbox() as sb:
            self.setup(sb, "--scaffold")
            answer = self.answers(sb, [{"name": "Hoka Speedgoat 6", "threshold_km": 700}])
            self.setup(sb, "--apply-shoes", answer)
            before = (sb.repo / "planning/Runner_Profile.md").read_text()
            data = self.json_out(self.setup(sb, "--apply-shoes", answer))
            self.assertEqual(data["added"], [])
            self.assertEqual(data["skipped"], ["Hoka Speedgoat 6"])
            self.assertEqual((sb.repo / "planning/Runner_Profile.md").read_text(), before)

    def test_preserves_an_existing_default(self):
        with Sandbox() as sb:
            self.setup(sb, "--scaffold")
            profile = sb.repo / "planning/Runner_Profile.md"
            marker = "\n\n### Matériel\n"
            profile.write_text(profile.read_text().replace(marker, "\n- Ancienne paire (par défaut)\n" + marker))
            self.setup(sb, "--apply-shoes", self.answers(sb, [{"name": "Nouvelle paire"}]))
            content = profile.read_text()
            self.assertIn("- Ancienne paire (par défaut)", content)
            self.assertIn("- Nouvelle paire", content)
            visible = re.sub(r"<!--.*?-->", "", content, flags=re.S)
            self.assertEqual(visible.count("(par défaut)"), 1)

    def test_rejects_invalid_values_without_touching_the_profile(self):
        with Sandbox() as sb:
            self.setup(sb, "--scaffold")
            profile = sb.repo / "planning/Runner_Profile.md"
            before = profile.read_text()
            proc = self.setup(sb, "--apply-shoes", self.answers(sb, [
                {"name": "Paire injectée\n- Faux", "start_date": "hier", "threshold_km": -1},
            ]))
            self.assertFailed(proc, "chaussure injectante refusée")
            self.assertEqual(profile.read_text(), before)

    def test_rejects_non_finite_mileage(self):
        with Sandbox() as sb:
            self.setup(sb, "--scaffold")
            proc = self.setup(sb, "--apply-shoes", self.answers(sb, [
                {"name": "Paire", "threshold_km": "nan"},
            ]))
            self.assertFailed(proc, "kilométrage non fini refusé")


class TestApplyObjective(SetupCase):
    def test_fills_the_active_objective_without_renaming_labels(self):
        with Sandbox() as sb:
            self.setup(sb, "--scaffold")
            data = self.json_out(self.setup(sb, "--apply-objective", self.answers(sb, {
                "Nom": "Trail des Crêtes",
                "Date": "2027-05-15",
                "Distance": "52 km",
                "Dénivelé positif": "2 800 m",
                "Objectif principal": "finir en moins de 8 h",
                "Lieu d'entraînement par défaut": "Annecy",
            })))
            self.assertIn("Nom", data["written"])
            objective = (sb.repo / "planning/active_objective.md").read_text()
            self.assertIn("- **Nom** : Trail des Crêtes", objective)
            self.assertIn("- **Dénivelé positif** : 2 800 m", objective)
            self.assertIn("- **Lieu d'entraînement par défaut** : Annecy", objective)

    def test_never_overwrites_an_existing_objective(self):
        with Sandbox() as sb:
            self.setup(sb, "--scaffold")
            first = self.answers(sb, {"Nom": "Premier trail"})
            self.setup(sb, "--apply-objective", first)
            second = self.answers(sb, {"Nom": "Course remplacée"})
            data = self.json_out(self.setup(sb, "--apply-objective", second))
            self.assertEqual(data["written"], [])
            self.assertEqual(data["skipped"], ["Nom"])
            objective = (sb.repo / "planning/active_objective.md").read_text()
            self.assertIn("Premier trail", objective)
            self.assertNotIn("Course remplacée", objective)

    def test_rejects_unknown_or_injected_fields(self):
        with Sandbox() as sb:
            self.setup(sb, "--scaffold")
            proc = self.setup(sb, "--apply-objective", self.answers(sb, {"Course secrète": "x"}))
            self.assertFailed(proc, "libellé inconnu")
            proc = self.setup(sb, "--apply-objective", self.answers(sb, {"Nom": "x\n- **Date** : demain"}))
            self.assertFailed(proc, "retour à la ligne")


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
                "health.cycle_tracking": "off",
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
