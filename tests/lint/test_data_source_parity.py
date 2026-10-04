"""Palier B — parité de comportement Garmin quand `[data].source = "garmin"` (#68).

Critère d'acceptation de la story : aucun comportement Garmin modifié quand la
source reste `garmin` (le défaut). Comme les prompts des agents sont le
comportement (ce sont les seules instructions que l'agent suit), on ne peut
pas comparer un "avant/après" binaire une fois la story mergée — ce test
verrouille à la place un jeu de phrases Garmin **load-bearing**, prises mot
pour mot dans `agents/coach.md`/`agents/medical.md` AVANT #68, et vérifie
qu'elles existent encore, verbatim, après l'ajout de la section « DATA SOURCE
MANDATE ». Un futur changement qui les modifierait devra mettre à jour cette
liste consciemment, jamais par accident au détour d'un ajout intervals.icu.

Complète (ne remplace pas) les cas d'éval existants (`health-full-triad`,
`daily-sync-resume-block`, ...) : ceux-ci exercent le comportement à
l'exécution (palier C) quand `ARC_LLM_TESTS=1` ; celui-ci verrouille le texte
source, gratuitement, à chaque run du palier B.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
COACH = (REPO / "agents/coach.md").read_text(encoding="utf-8")
MEDICAL = (REPO / "agents/medical.md").read_text(encoding="utf-8")
AGENTS_MD = (REPO / "AGENTS.md").read_text(encoding="utf-8")
DAILY_SYNC_SKILL = (REPO / "skills/garmin-daily-sync/SKILL.md").read_text(encoding="utf-8")
DAILY_SYNC_SH = (REPO / "scripts/daily-sync.sh").read_text(encoding="utf-8")
INSTALL_SH = (REPO / "install.sh").read_text(encoding="utf-8")
GARMIN_SYNC_EFFICIENCY_SKILL = (REPO / "skills/garmin-sync-efficiency/SKILL.md").read_text(encoding="utf-8")
LOG_SKILL = (REPO / "skills/log/SKILL.md").read_text(encoding="utf-8")

# Outils enregistrés par le serveur intervals.icu retenu (hhopke/intervals-icu-mcp, commit épinglé,
# #165) en mode de suppression `full` (le plus large) — relevés en important le serveur installé et
# en listant `mcp.list_tools()`. Toute mention `icu_<outil>` d'un prompt/doc doit en faire partie
# (détecte une faute de frappe ou un outil inventé). À régénérer quand le pin change.
ICU_TOOLS = frozenset("""
icu_add_activity_message icu_apply_sport_settings icu_apply_training_plan icu_bulk_create_events
icu_bulk_create_manual_activities icu_bulk_create_workouts icu_bulk_delete_events
icu_bulk_update_event_access icu_create_custom_item icu_create_event icu_create_gear
icu_create_gear_reminder icu_create_sport_settings icu_create_workout icu_create_workout_folder
icu_delete_activity icu_delete_custom_item icu_delete_event icu_delete_gear icu_delete_sport_settings
icu_delete_workout icu_delete_workout_folder icu_download_activity_file icu_download_fit_file
icu_download_gpx_file icu_duplicate_events icu_get_activities_around icu_get_activities_by_date
icu_get_activity_details icu_get_activity_intervals icu_get_activity_messages icu_get_activity_streams
icu_get_annual_training_plan icu_get_athlete_profile icu_get_best_efforts icu_get_calendar_events
icu_get_custom_item icu_get_custom_items icu_get_event icu_get_fitness_chart icu_get_fitness_summary
icu_get_gap_histogram icu_get_gear_list icu_get_hr_curves icu_get_hr_histogram icu_get_pace_curves
icu_get_pace_histogram icu_get_power_curves icu_get_power_histogram icu_get_recent_activities
icu_get_sport_settings icu_get_upcoming_workouts icu_get_wellness_data icu_get_wellness_for_date
icu_get_workout_library icu_get_workouts_in_folder icu_list_athletes icu_search_activities
icu_search_activities_full icu_search_intervals icu_update_activity icu_update_activity_streams
icu_update_custom_item icu_update_event icu_update_gear icu_update_gear_reminder
icu_update_sport_settings icu_update_wellness icu_update_workout
""".split())
# Identifiants `icu_*` qui ne sont PAS des outils (champs de l'API) et peuvent apparaître en prose.
ICU_NON_TOOLS = frozenset({"icu_training_load"})
# Anciens noms (sans préfixe) du serveur eddmann, qui ne doivent plus être cités comme outils.
LEGACY_INTERVALS_TOOLS = (
    "get_wellness_for_date", "get_recent_activities", "get_activity_details", "get_upcoming_workouts",
    "get_fitness_summary", "get_athlete_profile", "get_gear_list", "bulk_create_events",
    "create_event", "update_event", "delete_event", "get_event",
)

# Phrases Garmin-mode telles qu'écrites avant #68 — copiées verbatim depuis
# `agents/coach.md`/`agents/medical.md` (git blame antérieur à cette story).
COACH_GARMIN_SENTENCES = [
    "you MUST fetch and report ALL THREE of: overnight HRV (`get_hrv_data`), "
    "**resting heart rate (`get_rhr_day`)**, and training readiness (`get_training_readiness`)",
    "`get_rhr_day(date)` returns it directly. Do NOT fall back to `get_sleep_data`",
    "push the planned sessions DIRECTLY to the Garmin Connect calendar via the "
    "`schedule_workouts` tool",
    "**Push:** Use `schedule_workouts` with `{calendar_date, workout_data}` per session.",
    "**JSON schema:** See the `garmin-workout-scheduling` skill. Never use "
    "`steps`/`conditionValue` (400 error); use `workoutSegments`/`workoutSteps`/`endConditionValue`.",
]

MEDICAL_GARMIN_SENTENCES = [
    "Any availability decision MUST be based on all three — overnight HRV "
    "(`get_hrv_data`), **resting heart rate (`get_rhr_day`)** and training readiness "
    "(`get_training_readiness`)",
    "Use `get_rhr_day` — never pull `get_sleep_data` (>400 KB) just to read resting HR.",
]

# Idem pour skills/garmin-daily-sync/SKILL.md.
DAILY_SYNC_GARMIN_SENTENCES = [
    "fetch from the `garmin`\n   > MCP server: activities (with splits and `recovery_hr_bpm`), "
    "sleep, HRV, training\n   > readiness,",
]

# Idem pour AGENTS.md — la règle "secondaire sinon" doit rester la règle par
# défaut (source garmin, jamais configurée) : c'est la phrase qui dit que rien
# n'installe/n'active intervals.icu sans que l'athlète l'ait demandé.
AGENTS_MD_GARMIN_SENTENCES = [
    "**SECONDAIRE sinon** (défaut) : uniquement si l'utilisateur le demande "
    "explicitement (skill `intervals-icu-best-practices`), serveur non installé "
    "par `install.sh`, configuration manuelle (`docs/faq.md`).",
]


class TestGarminModeTextUnchanged(unittest.TestCase):
    def test_coach_garmin_sentences_still_present_verbatim(self):
        missing = [s for s in COACH_GARMIN_SENTENCES if s not in COACH]
        self.assertFalse(
            missing,
            "agents/coach.md : phrase(s) Garmin-mode modifiée(s) ou supprimée(s) — "
            "vérifier qu'aucun comportement source=garmin n'a changé (#68) :\n  "
            + "\n  ".join(missing),
        )

    def test_medical_garmin_sentences_still_present_verbatim(self):
        missing = [s for s in MEDICAL_GARMIN_SENTENCES if s not in MEDICAL]
        self.assertFalse(
            missing,
            "agents/medical.md : phrase(s) Garmin-mode modifiée(s) ou supprimée(s) — "
            "vérifier qu'aucun comportement source=garmin n'a changé (#68) :\n  "
            + "\n  ".join(missing),
        )

    def test_daily_sync_skill_garmin_sentences_still_present_verbatim(self):
        missing = [s for s in DAILY_SYNC_GARMIN_SENTENCES if s not in DAILY_SYNC_SKILL]
        self.assertFalse(
            missing,
            "skills/garmin-daily-sync/SKILL.md : phrase(s) Garmin-mode modifiée(s) — "
            "vérifier qu'aucun comportement source=garmin n'a changé (#68) :\n  "
            + "\n  ".join(missing),
        )

    def test_agents_md_secondary_rule_still_present_verbatim(self):
        missing = [s for s in AGENTS_MD_GARMIN_SENTENCES if s not in AGENTS_MD]
        self.assertFalse(
            missing,
            "AGENTS.md : la règle « secondaire sinon » a changé — intervals.icu ne "
            "doit jamais devenir actif sans que [data].source = \"intervals\" soit "
            "explicitement configuré (#68) :\n  " + "\n  ".join(missing),
        )


class TestDataSourceDocumented(unittest.TestCase):
    """Le nouveau comportement (#68) est bien documenté là où un agent le lit."""

    def test_agents_and_skill_mention_data_source_mandate(self):
        for path, text in (("agents/coach.md", COACH), ("agents/medical.md", MEDICAL)):
            with self.subTest(path=path):
                self.assertIn("[data].source", text)
                self.assertIn("DATA SOURCE MANDATE", text)

    def test_agents_md_documents_the_tool_mapping_and_degraded_features(self):
        self.assertIn("[data].source", AGENTS_MD)
        for tool in (
            "icu_get_wellness_for_date", "icu_get_recent_activities", "icu_get_activity_details",
            "icu_create_event", "icu_bulk_create_events",
        ):
            self.assertIn(tool, AGENTS_MD)
        # La readiness algorithmique Garmin n'a pas d'équivalent : ne jamais
        # laisser cette exception disparaître silencieusement d'un futur edit.
        self.assertIn("aucun équivalent", AGENTS_MD)
        self.assertIn("Téléchargement FIT", AGENTS_MD)
        self.assertIn("Upload de parcours", AGENTS_MD)

    def test_config_workspace_toml_declares_the_key_and_default(self):
        toml_text = (REPO / "config/workspace.toml").read_text(encoding="utf-8")
        self.assertIn("[data]", toml_text)
        self.assertIn('source = "garmin"', toml_text)

    def test_install_sh_exposes_source_flag_for_both_values(self):
        self.assertIn("--source", INSTALL_SH)
        self.assertIn("garmin|intervals", INSTALL_SH)
        self.assertIn("install_intervals_mcp", INSTALL_SH)

    def test_install_sh_only_persists_source_when_explicit(self):
        """Une installation Garmin par défaut ne doit JAMAIS écrire [data] dans
        workspace.user.toml (revue PR #116, blocker 2) — sinon un simple
        `./install.sh` diffère de main pour tout le monde."""
        self.assertIn('[[ "$EXPLICIT_SOURCE" -eq 1 ]] || return 0', INSTALL_SH)

    def test_install_sh_resolves_source_from_existing_config(self):
        """Un rerun sans --source ne doit jamais faire revenir un athlète
        intervals.icu vers garmin (revue PR #116, blocker 2)."""
        self.assertIn("resolve_source", INSTALL_SH)
        self.assertIn("--section data --key source --default garmin", INSTALL_SH)

    def test_install_sh_never_puts_credentials_in_mcp_env_block(self):
        """Ni .env (introuvable au démarrage du serveur par l'IDE) ni ${VAR}
        (jamais exporté, jamais interpolé par tous les IDE) — voir
        write_intervals_wrapper() (revue PR #116, blocker 1). La chaîne
        `INTERVALS_ICU_API_KEY` reste CITÉE en commentaire (pour expliquer
        pourquoi elle est évitée) : seul le corps réel des deux fonctions qui
        construisent la config MCP ne doit plus jamais l'injecter dans un
        `printf`."""
        import re

        for fn in ("mcp_server_value_intervals", "mcp_server_value_intervals_opencode"):
            match = re.search(rf"^{fn}\(\) \{{(.*?)^\}}", INSTALL_SH, re.MULTILINE | re.DOTALL)
            self.assertIsNotNone(match, f"fonction {fn}() introuvable dans install.sh")
            body = match.group(1)
            for line in body.splitlines():
                if line.strip().startswith("printf"):
                    self.assertNotIn("INTERVALS_ICU_API_KEY", line, f"{fn}() : secret dans le printf JSON")
        self.assertIn("write_intervals_wrapper", INSTALL_SH)
        self.assertIn("INTERVALS_ENV_DIR/run.sh", INSTALL_SH)

    def test_install_sh_pins_the_intervals_server_commit(self):
        """#165 : le pin est le fork hhopke, à un commit COMPLET (40 hex) — jamais une branche ni un
        tag, qui bougeraient sous nos pieds. Le même SHA est reporté dans coach_doctor et la doc."""
        match = re.search(r'^INTERVALS_MCP_REF="git\+(https://github\.com/[^@"]+)@([0-9a-f]{40})"$',
                          INSTALL_SH, re.MULTILINE)
        self.assertIsNotNone(match, "INTERVALS_MCP_REF doit valoir git+<url>@<sha complet de 40 hex>")
        url, sha = match.groups()
        self.assertEqual(url, "https://github.com/hhopke/intervals-icu-mcp")
        doctor = (REPO / "scripts/coach_doctor.py").read_text(encoding="utf-8")
        self.assertIn(f'INTERVALS_MCP_PINNED_URL = "{url}"', doctor)
        self.assertIn(f'INTERVALS_MCP_PINNED_COMMIT = "{sha}"', doctor)
        setup_doc = (REPO / "docs/intervals-setup.md").read_text(encoding="utf-8")
        self.assertIn(sha, setup_doc)
        self.assertIn(sha[:7], AGENTS_MD)
        self.assertIn(sha[:7], (REPO / "skills/intervals-icu-best-practices/SKILL.md").read_text(encoding="utf-8"))

    def test_install_sh_upgrades_a_stale_intervals_pin(self):
        """#165 : sans cela, « déjà installé » laisserait l'ancien serveur en place pour toujours."""
        self.assertIn("upgrade_intervals_pin_if_needed", INSTALL_SH)
        self.assertIn('uv tool install --python 3.12 --force --with fitparse "$INTERVALS_MCP_REF"', INSTALL_SH)
        # Seules les origines amont connues sont remplacées : jamais une installation personnalisée.
        self.assertIn("origine personnalisée", INSTALL_SH)

    def test_icu_tool_mentions_are_real_tools(self):
        """Toute mention `icu_<outil>` des prompts/docs de la source intervals.icu est un outil réel
        du serveur épinglé (liste `ICU_TOOLS`) — ni faute de frappe, ni outil inventé. Les motifs
        génériques de la politique du chat (`icu_get_*`, `icu_create_` …) se terminent par `_`/`*`."""
        files = [REPO / "AGENTS.md", *sorted((REPO / "agents").glob("*.md")),
                 *sorted((REPO / "skills").glob("*/SKILL.md")),
                 *sorted((REPO / "docs").glob("*.md")), *sorted((REPO / "docs/skills").glob("*.md"))]
        unknown = {}
        for path in files:
            for name in re.findall(r"\bicu_[a-z0-9_]*[a-z0-9]\b", path.read_text(encoding="utf-8")):
                if name not in ICU_TOOLS and name not in ICU_NON_TOOLS:
                    unknown.setdefault(name, path.relative_to(REPO).as_posix())
        self.assertFalse(unknown, f"outils icu_* inconnus du serveur épinglé : {unknown}")

    def test_intervals_column_uses_prefixed_tool_names(self):
        """La colonne `intervals` de la table de correspondance (AGENTS.md) ne cite plus que des
        outils préfixés `icu_` — l'ancien nom nu n'est plus un outil du serveur (#165)."""
        start = AGENTS_MD.index("### Correspondance des outils — Garmin ↔ intervals.icu")
        # Fin : la section suivante (table Strava, #164) ou, à défaut, le paragraphe FIT.
        nxt = AGENTS_MD.find("\n### ", start + 1)
        end = nxt if nxt != -1 else AGENTS_MD.index("**Téléchargement FIT")
        for line in AGENTS_MD[start:end].splitlines():
            if not line.startswith("|") or line.startswith("|---") or line.startswith("| Besoin"):
                continue
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if len(cells) < 3:
                continue
            for legacy in LEGACY_INTERVALS_TOOLS:
                self.assertIsNone(
                    re.search(rf"(?<![A-Za-z_]){legacy}\b", cells[2]),
                    f"colonne intervals : `{legacy}` sans préfixe icu_ — {line[:90]}",
                )

    def test_no_legacy_intervals_read_tool_outside_migration_notes(self):
        """Aucun prompt/doc/script ne cite un ancien nom de LECTURE intervals (serveur eddmann,
        sans préfixe `icu_`) comme outil à appeler — y compris les fonctionnalités arrivées
        après le fork (cycle menstruel #166 : `other.menstrual_phase` de
        `icu_get_wellness_for_date`). Ces noms n'existent pas côté Garmin ni Strava (tirets),
        donc toute occurrence nue est une régression. Seules les notes de migration, qui
        expliquent l'ancien nom, sont exemptées."""
        legacy_reads = ("get_wellness_for_date", "get_wellness_data", "get_recent_activities",
                        "get_activity_details", "get_upcoming_workouts", "get_fitness_summary",
                        "get_gear_list")
        exempt = {"docs/update.md", "docs/troubleshooting.md",
                  "skills/intervals-icu-best-practices/SKILL.md"}
        files = [REPO / "AGENTS.md", *sorted((REPO / "agents").glob("*.md")),
                 *sorted((REPO / "skills").glob("*/SKILL.md")),
                 *sorted((REPO / "docs").glob("*.md")), *sorted((REPO / "docs/skills").glob("*.md")),
                 *sorted((REPO / "scripts").glob("*.py")), *sorted((REPO / "config").rglob("*.toml"))]
        found = []
        for path in files:
            rel = path.relative_to(REPO).as_posix()
            if rel in exempt:
                continue
            text = path.read_text(encoding="utf-8")
            for legacy in legacy_reads:
                for m in re.finditer(rf"(?<![A-Za-z0-9_-]){legacy}\b", text):
                    found.append(f"{rel}:{text.count(chr(10), 0, m.start()) + 1} {legacy}")
        self.assertFalse(found, f"ancien nom intervals sans préfixe icu_ : {found}")

    def test_best_practices_skill_documents_the_structured_form_and_fallback(self):
        skill = (REPO / "skills/intervals-icu-best-practices/SKILL.md").read_text(encoding="utf-8")
        for needle in ("workout_parsed", "workout_steps", "intervals-icu://workout-syntax",
                       "Text fallback", "no `workout_doc` parameter", "event_type"):
            self.assertIn(needle, skill)
        # Le repli texte et le pas-d'upsert restent des règles explicites.
        self.assertIn("no upsert", skill.lower())

    def test_install_sh_ships_fitparse_with_the_intervals_server(self):
        """`download_fit.py --source intervals --json` se relance dans
        l'environnement `intervals-icu-mcp` pour lire le FIT : `fitparse` doit y être
        installé à neuf (`--with fitparse`) ET ajouté à une installation antérieure
        sans jamais réinstaller le serveur (`uv pip install`, jamais `--reinstall`,
        qui écraserait un correctif local de l'athlète)."""
        self.assertIn('uv tool install --python 3.12 --with fitparse "$INTERVALS_MCP_REF"', INSTALL_SH)
        self.assertIn('uv pip install --python "$tool_py" fitparse', INSTALL_SH)
        commands = [line for line in INSTALL_SH.splitlines() if line.strip().startswith("run uv ")]
        self.assertFalse([c for c in commands if "--reinstall" in c], "aucune commande uv --reinstall")

    def test_not_yet_synced_marker_is_source_aware(self):
        """#67 (\"/log\", merged after #68) introduced a "not yet synced"
        marker keyed on `garmin_activity_id`. #68's source-awareness pass must
        cover it everywhere it's restated: `garmin-sync-efficiency` rule 1a
        (the marker's own definition), `skills/log/SKILL.md` (the interactive
        fetch-before-create step), and `garmin-daily-sync` (which restates the
        rule for the headless prompt) — never left Garmin-only by accident."""
        for label, text in (
            ("garmin-sync-efficiency", GARMIN_SYNC_EFFICIENCY_SKILL),
            ("log", LOG_SKILL),
            ("garmin-daily-sync", DAILY_SYNC_SKILL),
        ):
            with self.subTest(skill=label):
                self.assertIn("intervals_activity_id", text)
                self.assertIn("garmin_activity_id", text)
        # Le skill /log doit utiliser l'outil de la source configurée, pas
        # `get_activities` en dur, pour le sync ciblé avant création.
        self.assertIn("icu_get_recent_activities", LOG_SKILL)
        self.assertIn("get_activities", LOG_SKILL)
        # Les clés santé restent IDENTIQUES quelle que soit la source (aucun
        # champ santé propre à intervals.icu n'existe) — la story ne doit pas
        # en avoir inventé un.
        self.assertIn("hrv_overnight_ms", GARMIN_SYNC_EFFICIENCY_SKILL)

    def test_daily_sync_skips_garmin_token_checks_in_intervals_mode(self):
        """check_token_alert() ne doit jamais tourner sous source=intervals —
        intervals-icu-mcp n'a pas d'échéance de token OAuth comparable, et
        `coach_doctor.py --check garmin_token` n'a rien à y lire (revue PR #116,
        blocker 3)."""
        self.assertIn('[[ "$SOURCE" == "garmin" ]] || return 0', DAILY_SYNC_SH)
        self.assertIn('SOURCE="$(toml_get data source garmin)"', DAILY_SYNC_SH)



if __name__ == "__main__":
    unittest.main()
