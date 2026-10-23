"""Palier B — cohérence statique des prompts et de la configuration.

Aucun modèle, aucun réseau, quelques millisecondes. Ces contrôles attrapent la
classe de bug qui a produit `planning/Runner_Profile.md` : un chemin cité par
trois fichiers d'instructions et qui n'existe nulle part.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
AGENTS = REPO / "agents"
SKILLS = REPO / "skills"

# Préfixes de chemins qui désignent le MOTEUR : ils doivent exister dans le dépôt.
ENGINE_PREFIXES = ("agents/", "skills/", "config/", "scripts/", "templates/", "docs/")

# Préfixes qui désignent le WORKSPACE de l'athlète : créés à l'usage, jamais
# versionnés (cf. .gitignore).
WORKSPACE_PREFIXES = (
    "activities/", "medical/", "nutrition/", "planning/", "rapports/", "resources/", "gear/", "logs/",
)

# Chemins cités qui ne sont ni l'un ni l'autre (exemples, dossiers générés par
# les IDE, chemins absolus d'illustration).
PATH_ALLOWLIST = {
    "config/workspace.user.toml",   # généré par install.sh, gitignoré
    "local/agents/",
    "local/skills/",
    ".arc/backfill.md",             # généré par scripts/arc_index.py backfill-plan, gitignoré
    ".arc/coach.db",                # généré par scripts/arc_index.py, gitignoré (skill coach-doctor)
    ".arc/garmin_gear.json",        # instantané get_gear, écrit par arc_index.py garmin-gear-status, gitignoré
    ".arc/get_gear_response.json",  # réponse brute de get_gear déposée par l'agent avant garmin-gear-status
}

# Un chemin entre backticks, assez spécifique pour éviter les faux positifs.
PATH_IN_BACKTICKS = re.compile(r"`([A-Za-z0-9_./-]+/[A-Za-z0-9_.*<>-]+)`")

FRONTMATTER = re.compile(r"\A---\n(.*?)\n---\n", re.DOTALL)


def read_frontmatter(path: Path) -> dict:
    match = FRONTMATTER.match(path.read_text(encoding="utf-8"))
    if not match:
        return {}
    fields = {}
    for line in match.group(1).splitlines():
        if ":" in line and not line.startswith(" "):
            key, _, value = line.partition(":")
            fields[key.strip()] = value.strip().strip('"').strip("'")
    return fields


def agent_files() -> list:
    return sorted(AGENTS.glob("*.md"))


def skill_files() -> list:
    return sorted(SKILLS.glob("*/SKILL.md"))


def prompt_files() -> list:
    return agent_files() + skill_files()


class TestAgentFrontmatter(unittest.TestCase):
    """Contrat de CONTRIBUTING.md:29 — obligatoire pour la découverte par Copilot."""

    def test_required_fields(self):
        for path in agent_files():
            with self.subTest(agent=path.name):
                fm = read_frontmatter(path)
                for key in ("name", "description", "mode"):
                    self.assertIn(key, fm, f"{path.name} : frontmatter sans « {key} »")
                self.assertEqual(fm["mode"], "subagent", f"{path.name} : mode inattendu")

    def test_name_matches_filename(self):
        for path in agent_files():
            with self.subTest(agent=path.name):
                self.assertEqual(
                    read_frontmatter(path).get("name"),
                    path.stem,
                    f"{path.name} : « name » doit valoir « {path.stem} »",
                )


class TestSkillFrontmatter(unittest.TestCase):
    def test_required_fields(self):
        for path in skill_files():
            with self.subTest(skill=path.parent.name):
                fm = read_frontmatter(path)
                self.assertIn("name", fm, f"{path} : frontmatter sans « name »")
                self.assertIn("description", fm, f"{path} : frontmatter sans « description »")

    def test_name_matches_directory(self):
        for path in skill_files():
            with self.subTest(skill=path.parent.name):
                self.assertEqual(read_frontmatter(path).get("name"), path.parent.name)

    def test_description_within_limit(self):
        """≤ 1024 caractères (CONTRIBUTING.md)."""
        for path in skill_files():
            with self.subTest(skill=path.parent.name):
                description = read_frontmatter(path).get("description", "")
                self.assertLessEqual(
                    len(description), 1024, f"{path} : description de {len(description)} caractères"
                )


class TestReferencedPaths(unittest.TestCase):
    """Tout chemin du moteur cité dans un prompt doit exister."""

    @staticmethod
    def _resolves(prompt: Path, ref: str) -> bool:
        # Un SKILL.md cite ses propres fichiers relativement à son dossier
        # (`scripts/analyze_gpx.py`), convention des skills.
        if prompt.name == "SKILL.md" and (prompt.parent / ref).exists():
            return True
        return (REPO / ref).exists()

    def test_engine_paths_resolve(self):
        missing = []
        for path in prompt_files():
            text = path.read_text(encoding="utf-8")
            for ref in sorted(set(PATH_IN_BACKTICKS.findall(text))):
                if ref in PATH_ALLOWLIST or not ref.startswith(ENGINE_PREFIXES):
                    continue
                if any(ch in ref for ch in "*<>"):
                    continue                     # motif, pas un chemin littéral
                if not self._resolves(path, ref):
                    missing.append(f"{path.relative_to(REPO)} → {ref}")
        self.assertFalse(missing, "chemins du moteur cités mais inexistants :\n  " + "\n  ".join(missing))

    def test_workspace_paths_use_known_folders(self):
        unknown = []
        for path in prompt_files():
            text = path.read_text(encoding="utf-8")
            for ref in sorted(set(PATH_IN_BACKTICKS.findall(text))):
                if ref in PATH_ALLOWLIST or ref.startswith(ENGINE_PREFIXES):
                    continue
                if ref.startswith(WORKSPACE_PREFIXES) or ref.startswith(("~", "/", "http")):
                    continue
                if path.name == "SKILL.md" and (path.parent / ref).exists():
                    continue                     # chemin relatif au skill
                unknown.append(f"{path.relative_to(REPO)} → {ref}")
        self.assertFalse(
            unknown,
            "chemins ne relevant ni du moteur ni des dossiers de travail connus :\n  "
            + "\n  ".join(unknown),
        )


class TestSkillReferences(unittest.TestCase):
    def test_skills_named_by_agents_exist(self):
        known = {p.parent.name for p in skill_files()}
        missing = []
        for path in agent_files():
            text = path.read_text(encoding="utf-8")
            for name in set(re.findall(r"`([a-z][a-z0-9-]+)`", text)):
                if name.endswith(("-analyzer", "-comparison", "-sync", "-scheduling",
                                  "-forecast", "-analysis", "-download", "-practices",
                                  "-efficiency", "-contract", "-backfill")) and name not in known:
                    missing.append(f"{path.name} → {name}")
        self.assertFalse(missing, "skills cités par un agent mais absents de skills/ :\n  " + "\n  ".join(missing))


def command_skill_files() -> list:
    """Skills-commandes de premier niveau (`gemini_command: "true"`, ex. /today, #66).

    Comparaison insensible à la casse, comme `scripts/build-gemini-commands.py`
    (`.lower() == "true"`) : les deux lectures de ce même champ ne doivent
    jamais diverger sur un « True »/« TRUE » qui passerait l'une et pas l'autre."""
    return [p for p in skill_files() if read_frontmatter(p).get("gemini_command", "").lower() == "true"]


class TestSurfaceParity(unittest.TestCase):
    """Chaque agent doit exister sur toutes les surfaces qu'on prétend supporter."""

    def test_every_agent_has_a_gemini_command(self):
        commands = {p.stem for p in (REPO / "config/gemini/commands").glob("*.toml")}
        missing = sorted({p.stem for p in agent_files()} - commands)
        self.assertFalse(missing, f"agents sans commande Gemini : {missing}")

    def test_every_command_skill_has_a_gemini_command(self):
        """#66 — un skill marqué `gemini_command: "true"` doit avoir sa commande générée."""
        commands = {p.stem for p in (REPO / "config/gemini/commands").glob("*.toml")}
        missing = sorted({p.parent.name for p in command_skill_files()} - commands)
        self.assertFalse(missing, f"skills-commandes sans commande Gemini : {missing}")

    def test_every_agent_has_a_doc_page(self):
        pages = {p.stem for p in (REPO / "docs/agents").glob("*.md")}
        missing = sorted({p.stem for p in agent_files()} - pages)
        self.assertFalse(missing, f"agents sans page docs/agents/ : {missing}")

    def test_every_skill_has_a_doc_page(self):
        pages = {p.stem for p in (REPO / "docs/skills").glob("*.md")}
        missing = sorted({p.parent.name for p in skill_files()} - pages)
        self.assertFalse(missing, f"skills sans page docs/skills/ : {missing}")

    def test_doc_pages_are_in_the_nav(self):
        nav = (REPO / "mkdocs.yml").read_text(encoding="utf-8")
        missing = [
            f"docs/agents/{p.stem}.md" for p in agent_files()
            if f"agents/{p.stem}.md" not in nav
        ] + [
            f"docs/skills/{p.parent.name}.md" for p in skill_files()
            if f"skills/{p.parent.name}.md" not in nav
        ]
        self.assertFalse(missing, f"pages absentes de la navigation mkdocs.yml : {missing}")


class TestWorkspaceTemplates(unittest.TestCase):
    """Un fichier du workspace érigé en source de vérité doit avoir un modèle.

    Sinon l'agent lit un chemin que personne ne crée jamais — exactement le cas
    de `planning/Runner_Profile.md`.
    """

    REQUIRED = {
        "planning/Runner_Profile.md": "templates/Runner_Profile.template.md",
        "planning/active_objective.md": "templates/active_objective.template.md",
    }

    def test_referenced_workspace_files_have_templates(self):
        cited = set()
        for path in prompt_files():
            text = path.read_text(encoding="utf-8")
            for ref in PATH_IN_BACKTICKS.findall(text):
                if ref in self.REQUIRED:
                    cited.add(ref)
        missing = [
            f"{ref} (cité par un prompt) → modèle attendu : {self.REQUIRED[ref]}"
            for ref in sorted(cited)
            if not (REPO / self.REQUIRED[ref]).exists()
        ]
        self.assertFalse(missing, "fichiers de travail sans modèle :\n  " + "\n  ".join(missing))


class TestHeadlessSkill(unittest.TestCase):
    """Le skill de synchronisation tourne sous cron : il ne doit rien demander.

    Le contrôle de premier démarrage ajouté aux agents est exactement le genre de
    chose qui finirait sinon dans une notification push, sans personne pour y
    répondre.
    """

    SKILL = REPO / "skills/garmin-daily-sync/SKILL.md"

    def test_states_it_asks_nothing(self):
        self.assertIn("Ne JAMAIS poser de", self.SKILL.read_text(encoding="utf-8"))

    def test_opts_out_of_the_setup_check(self):
        text = self.SKILL.read_text(encoding="utf-8")
        self.assertIn(
            "coach-setup", text,
            "le skill headless doit dire explicitement qu'il ne propose pas /coach-setup",
        )
        self.assertIn("ne jamais le proposer", text.lower())


class TestGuardrailsWiring(unittest.TestCase):
    """#53 — le moteur `arc_guardrails.py` (#52) ne fait rien tant que personne
    ne l'appelle : verrouille que le coach et le skill de push Garmin citent
    bien la commande et distinguent explicitement les trois issues (block /
    warn-info / erreur d'entrée), pour qu'un futur refactor de ces prompts ne
    puisse pas faire disparaître le câblage sans qu'un test le voie."""

    COACH = REPO / "agents/coach.md"
    SCHEDULING_SKILL = REPO / "skills/garmin-workout-scheduling/SKILL.md"

    def test_coach_cites_the_guardrails_command(self):
        text = self.COACH.read_text(encoding="utf-8")
        self.assertIn("scripts/arc_guardrails.py check", text)

    def test_coach_states_exit_1_and_exit_2_handling(self):
        text = self.COACH.read_text(encoding="utf-8")
        self.assertIn("Exit 1", text, "le coach doit nommer explicitement l'issue « block » (exit 1)")
        self.assertIn("Exit 2", text, "le coach doit nommer explicitement l'issue « erreur d'entrée » (exit 2)")

    def test_scheduling_skill_cites_the_guardrails_command(self):
        text = self.SCHEDULING_SKILL.read_text(encoding="utf-8")
        self.assertIn("scripts/arc_guardrails.py check", text)

    def test_scheduling_skill_states_exit_1_and_exit_2_handling(self):
        text = self.SCHEDULING_SKILL.read_text(encoding="utf-8")
        self.assertIn("Exit 1", text, "le skill de push doit nommer explicitement l'issue « block » (exit 1)")
        self.assertIn("Exit 2", text, "le skill de push doit nommer explicitement l'issue « erreur d'entrée » (exit 2)")


class TestGearAlertsWiring(unittest.TestCase):
    """#132 — l'alerte d'usure des chaussures, la correction par chat et la
    suggestion de paire n'existent que par les prompts : verrouille que le coach,
    `garmin-daily-sync` et `/week` citent bien les commandes et les garde-fous
    (une seule alerte par franchissement, suggestion seulement à partir de deux
    paires actives, jamais imposée, source du rodage honnête)."""

    COACH = REPO / "agents/coach.md"
    SYNC = REPO / "skills/garmin-daily-sync/SKILL.md"
    WEEK = REPO / "skills/week/SKILL.md"

    def test_coach_cites_the_gear_command_and_chat_correction(self):
        text = self.COACH.read_text(encoding="utf-8")
        self.assertIn("scripts/arc_index.py gear", text)
        self.assertIn("départ", text)
        self.assertIn("never negative", text)

    def test_coach_suggestion_needs_two_active_pairs_and_is_not_imposed(self):
        text = self.COACH.read_text(encoding="utf-8")
        self.assertIn("SHOE SUGGESTION MANDATE", text)
        self.assertIn("at least 2 non-retired pairs", text)
        self.assertIn("SUGGESTION, never an instruction", text)

    def test_coach_break_in_budget_is_labelled_as_a_project_approximation(self):
        text = self.COACH.read_text(encoding="utf-8")
        self.assertIn("approximation du projet", text)

    def test_daily_sync_alerts_once_per_crossing(self):
        text = self.SYNC.read_text(encoding="utf-8")
        self.assertIn("arc_index.py gear --activities", text)
        self.assertIn("crossed_in_run", text)
        self.assertIn("une seule fois", text)

    def test_week_skill_mentions_pairs_over_or_near_threshold(self):
        text = self.WEEK.read_text(encoding="utf-8")
        self.assertIn("arc_index.py gear", text)
        self.assertIn("near_threshold", text)


class TestGearBackfillWiring(unittest.TestCase):
    """#145 — le rattrapage du matériel Garmin sur l'historique n'existe pour l'agent que par le prompt :
    proposé UNE fois en interactif, toujours en simulation d'abord, `--apply` après un « oui » explicite,
    jamais dans la synchronisation headless (qui ne le mentionne même pas)."""

    COACH = REPO / "agents/coach.md"
    SYNC = REPO / "skills/garmin-daily-sync/SKILL.md"
    SYNC_SH = REPO / "scripts/daily-sync.sh"

    def test_coach_offers_backfill_once_interactive_dry_run_first(self):
        text = self.COACH.read_text(encoding="utf-8")
        self.assertIn("scripts/garmin_gear_backfill.py", text)
        self.assertIn("History backfill (#145)", text)
        self.assertRegex(text, r"(?s)History backfill.*?interactive only, proposed ONCE")
        self.assertRegex(text, r"(?s)History backfill.*?DRY RUN")
        self.assertRegex(text, r"(?s)History backfill.*?`--apply`.*?ONLY after an explicit yes")
        self.assertRegex(text, r"(?s)History backfill.*?NEVER in a headless run")

    def test_coach_trigger_is_a_ratio_and_mentions_long_timeout(self):
        text = self.COACH.read_text(encoding="utf-8")
        self.assertRegex(text, r"(?s)History backfill.*?MORE THAN HALF")
        self.assertRegex(text, r"(?s)History backfill.*?long timeout")
        self.assertRegex(text, r"(?s)History backfill.*?APPLY REFUS|History backfill.*?--apply REFUS")

    def test_coach_never_sets_default_pair_automatically(self):
        text = self.COACH.read_text(encoding="utf-8")
        self.assertRegex(text, r"(?s)History backfill.*?never sets `\(par défaut\)`")

    def test_headless_sync_never_runs_or_mentions_backfill(self):
        for path in (self.SYNC, self.SYNC_SH):
            self.assertNotIn("garmin_gear_backfill", path.read_text(encoding="utf-8"), path)

    def test_gemini_command_is_regenerated(self):
        toml = (REPO / "config/gemini/commands/coach.toml").read_text(encoding="utf-8")
        self.assertIn("garmin_gear_backfill.py", toml)


class TestGarminGearWhitelist(unittest.TestCase):
    """#133 — liste blanche `install.sh` ↔ prompts/skills/docs qui citent les outils matériel.

    Lecture (`get_gear`, `get_activity_gear`) et écriture (`add_gear_to_activity`) doivent être
    autorisées côté serveur ; l'écriture doit toujours être encadrée par « confirmation » dans tout
    fichier qui la cite, et interdite dans la synchronisation headless."""

    TOOLS = ("get_gear", "get_activity_gear", "add_gear_to_activity")

    @classmethod
    def setUpClass(cls):
        install = (REPO / "install.sh").read_text(encoding="utf-8")
        m = re.search(r'GARMIN_TOOL_WHITELIST="([^"]+)"', install)
        cls.whitelist = m.group(1).split(",")

    def test_gear_tools_are_whitelisted(self):
        for tool in self.TOOLS:
            self.assertIn(tool, self.whitelist)

    def test_remove_gear_is_not_whitelisted(self):
        self.assertNotIn("remove_gear_from_activity", self.whitelist)

    def test_docs_whitelist_copies_match_install_sh(self):
        text = (REPO / "docs/garmin-setup.md").read_text(encoding="utf-8")
        copies = re.findall(r'GARMIN_ENABLED_TOOLS"?:\s*"([^"]+)"', text)
        self.assertGreaterEqual(len(copies), 2)
        for copy in copies:
            self.assertEqual(copy.split(","), self.whitelist)

    def test_every_file_citing_the_write_tool_requires_confirmation(self):
        files = list(AGENTS.glob("*.md")) + list(SKILLS.glob("*/SKILL.md")) + [REPO / "AGENTS.md"]
        cited = [f for f in files if "add_gear_to_activity" in f.read_text(encoding="utf-8")]
        self.assertTrue(cited)
        for f in cited:
            with self.subTest(file=f.name):
                self.assertRegex(f.read_text(encoding="utf-8"), r"(?i)confirm")

    def test_daily_sync_script_disallows_gear_writes(self):
        text = (REPO / "scripts/daily-sync.sh").read_text(encoding="utf-8")
        self.assertIn("mcp__garmin__add_gear_to_activity", text)
        self.assertIn("mcp__garmin__remove_gear_from_activity", text)
        self.assertIn("--disallowedTools", text)
        # Limite documentée : en mode passerelle l'outil `invoke_tool` n'est pas filtrable par sous-outil.
        self.assertRegex(text, r"(?i)invoke_tool[^\n]*\n[^\n]*filtr")

    def test_priority_wording_is_consistent_everywhere(self):
        """Priorité = déclaration de l'athlète > Garmin > défaut ; jamais « Garmin > chat »."""
        for rel in ("AGENTS.md", "agents/coach.md", "skills/garmin-daily-sync/SKILL.md",
                    "skills/garmin-sync-efficiency/SKILL.md", "skills/workspace-data-contract/SKILL.md",
                    "docs/garmin-setup.md", "docs/workspace.md", "docs/agents/coach.md", "docs/skills.md",
                    "docs/skills/garmin-daily-sync.md"):
            text = (REPO / rel).read_text(encoding="utf-8")
            with self.subTest(file=rel):
                self.assertNotRegex(text, r"(?i)garmin\s*>\s*(gear_id|chat|d[ée]claration)")
                self.assertNotRegex(text, r"(?i)matériel garmin\s*>\s*(gear_id|paire (que|cit)|chat|d[ée]claration)")

    def test_headless_sync_never_writes_gear(self):
        text = (SKILLS / "garmin-daily-sync/SKILL.md").read_text(encoding="utf-8")
        self.assertRegex(text, r"NEVER call `add_gear_to_activity`")

    def test_read_tools_cited_by_sync_skills_are_whitelisted(self):
        for rel in ("skills/garmin-daily-sync/SKILL.md", "skills/garmin-sync-efficiency/SKILL.md", "agents/coach.md"):
            text = (REPO / rel).read_text(encoding="utf-8")
            for tool in ("get_gear", "get_activity_gear"):
                if re.search(rf"`{tool}\b", text):
                    self.assertIn(tool, self.whitelist, f"{rel} cite {tool}")

    def test_sync_efficiency_limits_gear_calls_to_new_activities(self):
        text = (SKILLS / "garmin-sync-efficiency/SKILL.md").read_text(encoding="utf-8")
        self.assertIn("one `get_activity_gear(activity_id)` call per NEW activity", text)
        self.assertIn("include_stats=False", text)
class TestEquipmentWiring(unittest.TestCase):
    """#134 — matériel hors chaussures : kits, entretien, alertes une seule fois et contrôle du
    matériel de course n'existent que par les prompts ; verrouille les commandes citées, les
    garde-fous (jamais inventer un objet ni un seuil) et la cohérence avec le CLI réel."""

    COACH = REPO / "agents/coach.md"
    STRATEGIST = REPO / "agents/course-strategist.md"
    SYNC = REPO / "skills/garmin-daily-sync/SKILL.md"
    WEEK = REPO / "skills/week/SKILL.md"
    CONTRACT = REPO / "skills/workspace-data-contract/SKILL.md"

    def read(self, path):
        return path.read_text(encoding="utf-8")

    def test_strategist_crosses_race_gear_with_inventory(self):
        text = self.read(self.STRATEGIST)
        self.assertIn("arc_index.py equipment --race-plan", text)
        for status in ("missing", "never_used", "alert"):
            self.assertIn(f"`{status}`", text)
        self.assertRegex(text, r"(?i)rien de nouveau le jour J")
        self.assertRegex(text, r"(?i)n'invente aucun objet")
        self.assertIn("inventory_empty", text)

    def test_strategist_gear_list_is_written_in_the_race_plan_block(self):
        self.assertIn("`gear` du bloc `arc`", self.read(self.STRATEGIST))

    def test_coach_kit_and_maintenance_rules(self):
        text = self.read(self.COACH)
        self.assertIn("arc_index.py equipment --kit", text)
        self.assertIn("gear_ids", text)
        self.assertIn("entretien <date>", text)
        self.assertRegex(text, r"(?i)never add an item of your own")
        self.assertRegex(text, r"never invent a threshold")
        self.assertIn("pre_session_check", text)

    def test_gear_ids_preserved_on_garmin_merge(self):
        for rel in ("skills/garmin-daily-sync/SKILL.md", "skills/garmin-sync-efficiency/SKILL.md"):
            self.assertIn("`gear_ids`", (REPO / rel).read_text(encoding="utf-8"), rel)

    def test_coach_never_touches_gear_id_for_kits_and_defines_kit_and_maintenance_rule(self):
        text = self.read(self.COACH)
        self.assertIn("Never touch `gear_id`/`gear_source`", text)
        self.assertIn("planned kit", text)
        self.assertNotIn("usual kit", text)
        self.assertIn("LAST session done BEFORE the maintenance", text)

    def test_dashboard_shows_category_display_label(self):
        js = (REPO / "web/js/app.js").read_text(encoding="utf-8")
        self.assertIn("EQUIP_CATEGORY_LABEL", js)
        self.assertIn('batons: "bâtons"', js)

    def test_coach_keeps_gear_id_as_the_shoe(self):
        self.assertIn("never replaces `gear_id`", self.read(self.COACH))

    def test_sync_emits_equipment_alert_once_without_state(self):
        text = self.read(self.SYNC)
        self.assertIn("arc_index.py equipment --activities", text)
        self.assertRegex(text, r"(?i)AUCUNE alerte ici")          # jours : jamais dans le resume
        self.assertRegex(text, r"(?i)aucune séance nouvelle = ne PAS lancer")
        self.assertRegex(text, r"(?i)tout sport")
        self.assertRegex(text, r"(?i)sans état persistant")
        step3c = text[text.index("3c. **Alerte matériel"):text.index("4. **Garde-fou r5")]
        self.assertNotIn("--since", step3c.replace("N'utiliser jamais `--last-pass`", ""))

    def test_week_skill_reports_equipment(self):
        text = self.read(self.WEEK)
        self.assertIn("arc_index.py equipment", text)
        self.assertIn("Matériel :", text)

    def test_cited_equipment_flags_exist_in_the_cli(self):
        cli = (REPO / "scripts/arc_index.py").read_text(encoding="utf-8")
        for flag in ("--kit", "--race-plan", "--sport", "--since", "--activities"):
            self.assertIn(f'"{flag}"', cli)
        for path in (self.COACH, self.STRATEGIST, self.SYNC, self.CONTRACT):
            for flag in re.findall(r"arc_index\.py equipment[^`\n]*?(--[a-z-]+)", self.read(path)):
                self.assertIn(f'"{flag}"', cli, f"{path.name} : {flag}")

    def test_contract_documents_gear_ids_and_triggers(self):
        text = self.read(self.CONTRACT)
        for needle in ("`gear_ids`", "alerte N km", "N séances", "N jours", "entretien", "kit:", "catégorie:"):
            self.assertIn(needle, text)
class TestGearInspectionWiring(unittest.TestCase):
    """#135 — le skill `gear-inspection` n'existe que par son prompt : verrouille ses
    garde-fous (signal faible, jamais un diagnostic, aucune mesure sans échelle, pas de
    changement de foulée recommandé sur une photo, relais médical conditionné, proposition
    jamais imposée), l'absence de vocabulaire de diagnostic, et le câblage du coach et de
    la documentation mobile (envoi de photos non validé)."""

    SKILL = REPO / "skills/gear-inspection/SKILL.md"
    COACH = REPO / "agents/coach.md"
    MOBILE = REPO / "docs/mobile.md"
    DOC = REPO / "docs/skills/gear-inspection.md"

    # Formulations qui affirment un diagnostic ou étiquettent l'athlète.
    DIAGNOSIS_VOCABULARY = re.compile(
        r"diagnostic\s+(de|d['’])|vous\s+souffrez|tu\s+souffres|pronateur|supinateur|"
        r"sur-?pronat|sous-?pronat|syndrome\b|pathologi", re.IGNORECASE)

    def text(self, path) -> str:
        return path.read_text(encoding="utf-8")

    def test_skill_has_frontmatter_within_limit(self):
        fields = read_frontmatter(self.SKILL)
        self.assertEqual(fields.get("name"), "gear-inspection")
        self.assertTrue(0 < len(fields.get("description", "")) <= 1024)

    def test_guardrail_phrases_are_present(self):
        text = self.text(self.SKILL)
        for phrase in (
            "signal faible",
            "jamais un diagnostic",
            "Aucune mesure en mm sans référence d'échelle",
            "Ne jamais recommander de changer de technique de foulée",
            "proposée, jamais imposée",
            "approximation du projet",
            "redemander l'angle manquant",
            "comparaison explicite",
            "asymétrie",
            "indisponible",
        ):
            self.assertIn(phrase, text, f"garde-fou absent du skill : {phrase}")

    def test_medical_handoff_is_gated_on_enabled_agents(self):
        text = self.text(self.SKILL)
        self.assertIn("[agents].enabled", text)
        self.assertIn("kiné", text)
        self.assertIn("analyse de foulée", text)

    def test_no_diagnosis_vocabulary(self):
        for path in (self.SKILL, self.DOC):
            hits = self.DIAGNOSIS_VOCABULARY.findall(self.text(path))
            self.assertFalse(hits, f"vocabulaire de diagnostic dans {path.relative_to(REPO)} : {hits}")

    def test_only_the_two_verified_sources_are_cited(self):
        urls = set(re.findall(r"https?://[^\s)]+", self.text(self.SKILL)))
        self.assertEqual(urls, {
            "https://www.doctorsofrunning.com/footwear-science-outsole-wear-patterns/",
            "https://marathonhandbook.com/wear-on-running-shoes/",
        })

    def test_no_ground_contact_claim(self):
        """Le temps de contact au sol est extrait depuis #151 (`gait-summary`), mais le sens de la balance
        n'est pas établi et les règles d'usage par les agents viennent plus tard : le skill dit les deux,
        et ne l'invente jamais quand la mesure manque."""
        text = self.text(self.SKILL)
        self.assertIn("temps de contact au sol", text)
        self.assertIn("gait-summary", text)
        self.assertIn("pas établi", text)
        self.assertIn("ne jamais l'inventer", text)

    def test_coach_wires_the_skill_command_and_guardrails(self):
        text = self.text(self.COACH)
        for needle in ("GEAR INSPECTION MANDATE", "scripts/arc_index.py inspections",
                       "scripts/arc_index.py gear-career", "a proposal, never an imposition",
                       "NEVER recommend changing foot strike", "ONLY IF `medical` is in `[agents].enabled`",
                       "Never in headless mode", "is NOT established",
                       "worded by `due_reason`", "`threshold_alert` →", "`never_inspected` →",
                       "belongs to the chat reply ONLY"):
            self.assertIn(needle, text, f"coach.md : {needle}")

    def test_mobile_doc_flags_photo_upload_as_unvalidated(self):
        text = self.text(self.MOBILE)
        self.assertIn("à valider", text)
        self.assertIn("pas validé", text)
