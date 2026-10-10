"""Palier D — politique de permissions du chat coach (`scripts/arc_chat_policy.py`)."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))

import coach_config  # noqa: E402
from arc_chat_backend import payload_hash  # noqa: E402
from arc_chat_policy import Policy  # noqa: E402


class PolicyBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.ws = Path(self._tmp.name).resolve()
        (self.ws / "planning").mkdir()
        self.policy = Policy.load(REPO, self.ws)

    def d(self, tool, tool_input=None, **kw):
        return self.policy.decide(tool, tool_input or {}, **kw)


class PolicyTest(PolicyBase):
    def test_fichier_versionne_charge(self):
        self.assertIn("planning", self.policy.write_dirs)
        self.assertIn("wttr.in", self.policy.fetch_domains)

    def test_lecture_dans_le_workspace(self):
        self.assertEqual(self.d("fs.read", {"path": "planning/active_objective.md"}), "allow")
        self.assertEqual(self.d("fs.list", {"path": "activities"}), "allow")
        self.assertEqual(self.d("fs.list", {}), "allow")

    def test_lecture_hors_workspace_ou_secrete_refusee(self):
        for path in ("../etc/passwd", "/etc/passwd", "config/llm.env", ".env",
                     "x/garmin.token", ".garminconnect/oauth.json", ".arc/chat/approvals.json"):
            self.assertEqual(self.d("fs.read", {"path": path}), "deny", path)

    def test_ecriture_limitee_aux_dossiers_de_donnees(self):
        for folder in ("activities", "medical", "nutrition", "planning", "rapports"):
            self.assertEqual(self.d("fs.write", {"path": f"{folder}/x.md"}), "allow", folder)
        for path in ("scripts/arc_chat.py", "config/workspace.toml", ".arc/chat/x.json", "AGENTS.md",
                     "planning/../scripts/x.py", "planning/.env"):
            self.assertEqual(self.d("fs.write", {"path": path}), "deny", path)

    def test_shell_liste_blanche_sans_metacaracteres(self):
        self.assertEqual(self.d("shell", {"command": "python3 scripts/arc_index.py energy"}), "allow")
        self.assertEqual(self.d("shell", {"command": "python3 scripts/arc_log.py --help"}), "allow")
        # #222 : décision du poids — options déclarées et réponse Garmin passée sur stdin.
        self.assertEqual(self.d("shell", {"command": "python3 scripts/arc_weight_sync.py plan --date 2026-10-10 "
                                                     "--declared-kg 70.2"}), "allow")
        self.assertEqual(self.d("shell", {"command": "echo '{\"date\": \"2026-10-10\", \"measurements\": []}' | "
                                                     "python3 scripts/arc_weight_sync.py plan"}), "allow")
        for command in ("rm -rf /", "python3 scripts/arc_index.py; rm x", "python3 scripts/arc_index.py | sh",
                        "python3 scripts/arc_index.py $(id)", "python3 scripts/arc_index.py > /tmp/x",
                        "python3 scripts/arc_index.py `id`", "python3 scripts/arc_index.py\nrm x",
                        "python3 scripts/arc_index.pyx", "python3 scripts/arc_index.py ../x", "", "python3 -c 1"):
            self.assertEqual(self.d("shell", {"command": command}), "deny", repr(command))

    def test_web(self):
        self.assertEqual(self.d("web.fetch", {"url": "https://wttr.in/Lyon?format=j1"}), "allow")
        self.assertEqual(self.d("web.fetch", {"url": "https://overpass-api.de/api/interpreter"}), "allow")
        self.assertEqual(self.d("web.fetch", {"url": "https://evil.example/wttr.in"}), "deny")
        self.assertEqual(self.d("web.fetch", {"url": "https://wttr.in.evil.example/"}), "deny")
        self.assertEqual(self.d("web.fetch", {"url": "https://user@evil.example@wttr.in/"}), "deny")
        self.assertEqual(self.d("web.fetch", {"url": "file:///etc/passwd"}), "deny")
        self.assertEqual(self.d("web.search", {"query": "x"}), "deny")

    def test_task_skill_autres(self):
        self.assertEqual(self.d("task", {"agent": "coach"}), "allow")
        self.assertEqual(self.d("skill", {"name": "log"}), "allow")
        self.assertEqual(self.d("other:WebSearch", {}), "deny")
        self.assertEqual(self.d("inconnu", {}), "deny")

    def test_mcp_lectures_autorisees(self):
        for tool in ("mcp:garmin.get_activities", "mcp:garmin.get_hrv_data", "mcp:garmin.count_activities",
                     "mcp:intervals.get_events", "mcp:garmin.download_workout"):
            self.assertEqual(self.d(tool), "allow", tool)

    def test_mcp_ecritures_demandent_approbation(self):
        names = ("schedule_workouts", "schedule_workout", "schedule_week", "delete_workout", "delete_workouts",
                 "unschedule_workout", "upload_workout", "upload_workouts", "upload_course", "delete_course",
                 "create_strength_workout", "create_z2_walk_workout", "add_weigh_in", "set_blood_pressure",
                 "log_food", "create_custom_food", "update_custom_food", "delete_food_log",
                 "add_or_update_event", "create_event", "bulk_create_events", "update_event", "delete_event",
                 "delete_events_by_date_range", "request_reload")
        for server in ("garmin", "intervals"):
            for name in names:
                self.assertEqual(self.d(f"mcp:{server}.{name}"), "ask", f"{server}.{name}")

    def test_mcp_intervals_fork_icu_prefixe(self):
        """#165 : le fork hhopke préfixe tous ses outils `icu_`. Lectures libres, écritures et
        téléchargements (qui écrivent un fichier local, `output_path`) soumis à approbation."""
        for name in ("icu_get_wellness_for_date", "icu_get_recent_activities", "icu_get_calendar_events",
                     "icu_search_activities", "icu_get_gear_list"):
            self.assertEqual(self.d(f"mcp:intervals.{name}"), "allow", name)
        for name in ("icu_create_event", "icu_bulk_create_events", "icu_update_event", "icu_delete_event",
                     "icu_bulk_delete_events", "icu_update_wellness", "icu_add_activity_message",
                     "icu_duplicate_events", "icu_apply_training_plan", "icu_delete_activity",
                     "icu_download_fit_file", "icu_download_activity_file"):
            self.assertEqual(self.d(f"mcp:intervals.{name}"), "ask", name)

    def test_mcp_outil_inconnu_ou_serveur_inconnu(self):
        self.assertEqual(self.d("mcp:garmin.upsert_and_log"), "ask")        # inconnu d'un serveur connu
        self.assertEqual(self.d("mcp:hassmcp.get_entity"), "deny")
        self.assertEqual(self.d("mcp:garmin."), "deny")

    def test_hash_preapprouve_leve_ask_seulement_pour_la_charge_exacte(self):
        tool, payload = "mcp:garmin.schedule_workouts", {"workouts": [{"date": "2026-10-01"}]}
        approved = {payload_hash(tool, payload)}
        self.assertEqual(self.d(tool, payload), "ask")
        self.assertEqual(self.d(tool, payload, preapproved=approved), "allow")
        self.assertEqual(self.d(tool, {"workouts": [{"date": "2026-10-02"}]}, preapproved=approved), "ask")
        # jamais une levée de « deny »
        denied = {payload_hash("shell", {"command": "rm -rf /"})}
        self.assertEqual(self.d("shell", {"command": "rm -rf /"}, preapproved=denied), "deny")

    def test_fichier_personnalise_et_repli_toml(self):
        custom = self.ws / "policy.toml"
        custom.write_text('[web]\nfetch_domains = ["example.org"]\n', encoding="utf-8")
        policy = Policy.load(custom, self.ws)
        self.assertEqual(policy.decide("web.fetch", {"url": "https://example.org/x"}), "allow")
        self.assertEqual(policy.decide("web.fetch", {"url": "https://wttr.in/"}), "deny")
        # Sans fichier : les défauts intégrés s'appliquent.
        empty = Policy.load(self.ws / "absent", self.ws)
        self.assertEqual(empty.decide("mcp:garmin.schedule_workouts", {}), "ask")

    def test_le_fichier_versionne_passe_le_parseur_de_repli(self):
        """Python < 3.11 : le repli de coach_config doit lire config/chat-policy.toml à l'identique."""
        text = (REPO / "config/chat-policy.toml").read_text(encoding="utf-8")
        parsed = coach_config._read_toml_fallback(text)
        try:
            import tomllib
        except ImportError:
            return
        real = tomllib.loads(text)
        for section in ("fs", "shell", "web", "mcp"):
            for key, value in real[section].items():
                if key == "scripts":                      # tableaux imbriqués : clé de section complète en repli
                    for script, table in value.items():
                        self.assertEqual(parsed[f'shell.scripts."{script}"'], table, script)
                    continue
                self.assertEqual(parsed[section][key], value, f"{section}.{key}")


class ShellBypassTest(PolicyBase):
    """Revue : chemins absolus, `~`, options porteuses de chemin, `\\`, jokers."""

    def sh(self, command):
        return self.d("shell", {"command": command})

    def test_anciennes_commandes_toujours_permises(self):
        for command in ("python3 scripts/arc_index.py energy", "python3 scripts/arc_index.py energy --days 7",
                        "python3 scripts/arc_index.py --validate activities/x.md",
                        "python3 scripts/arc_log.py --input planning/in.json --output activities/out.json",
                        "python3 scripts/arc_race_pacing.py plan --gpx planning/course.gpx --pack-kg 3",
                        "python3 scripts/arc_index.py samples 123 --with-gps"):
            self.assertEqual(self.sh(command), "allow", command)

    def test_chemins_absolus_et_tilde_refuses(self):
        for command in (
                "python3 scripts/arc_log.py --output /any/path",
                "python3 scripts/arc_log.py --output=/any/path",
                "python3 scripts/arc_log.py --input ~/.garminconnect/oauth1_token.json",
                "python3 scripts/arc_index.py --db ~/.zshrc",
                "python3 scripts/arc_index.py --db /etc/x",
                "python3 scripts/arc_index.py --validate /etc/passwd",
                "python3 scripts/arc_index.py /etc/passwd",
                "python3 scripts/arc_race_pacing.py plan --gpx /etc/passwd",
                "python3 scripts/arc_race_pacing.py plan --gpx planning/a.gpx --weather-file /etc/hosts",
                "python3 scripts/coach_doctor.py --tokens-dir ~/.garminconnect",
                "python3 scripts/arc_index.py --workspace /tmp"):
            self.assertEqual(self.sh(command), "deny", command)

    def test_antislash_et_jokers_refuses(self):
        for command in ("python3 scripts/arc_index.py\\ x", "python3 scripts/arc_index.py energy\\ ",
                        "python3 scripts/arc_index.py --validate config/workspace.user.t*",
                        "python3 scripts/arc_index.py --validate config/*.toml",
                        "python3 scripts/arc_index.py --validate {a,b}", "python3 scripts/arc_index.py --validate ~"):
            self.assertEqual(self.sh(command), "deny", command)

    def test_option_inconnue_refusee(self):
        for command in ("python3 scripts/arc_log.py --evil x", "python3 scripts/arc_index.py --python /bin/sh",
                        "python3 scripts/arc_log.py -o planning/x.json", "python3 skills/fit-download/scripts/download_fit.py --python x",
                        "python3 scripts/arc_log.py --output"):
            self.assertEqual(self.sh(command), "deny", command)

    def test_scripts_des_skills_au_chemin_reel(self):
        # Les skills appellent leurs scripts sous skills/*/scripts/ (SKILL.md).
        self.assertEqual(self.sh("python3 skills/gpx-analysis/scripts/analyze_gpx.py planning/trace.gpx"), "allow")
        self.assertEqual(self.sh("python3 skills/fit-download/scripts/download_fit.py --output-dir activities/fit"), "allow")
        self.assertEqual(self.sh("python3 scripts/analyze_gpx.py planning/trace.gpx"), "deny")

    def test_sorties_uniquement_dans_les_dossiers_de_donnees(self):
        self.assertEqual(self.sh("python3 scripts/arc_log.py --output activities/o.json"), "allow")
        for command in ("python3 scripts/arc_log.py --output scripts/arc_chat.py",
                        "python3 scripts/arc_log.py --output config/workspace.toml",
                        "python3 scripts/arc_log.py --output .arc/chat/approvals.json",
                        "python3 scripts/arc_log.py --output planning/../scripts/x.py",
                        "python3 scripts/arc_log.py --output out.json",
                        "python3 scripts/arc_index.py --db .arc/coach.db",
                        "python3 scripts/arc_index.py --db planning/.env"):
            self.assertEqual(self.sh(command), "deny", command)

    def test_lecture_de_secrets_ou_hors_workspace_refusee(self):
        for command in ("python3 scripts/arc_log.py --input config/llm.env",
                        "python3 scripts/arc_log.py --input .arc/chat/approvals.json",
                        "python3 scripts/arc_log.py --input ../secret.json",
                        "python3 scripts/arc_index.py --validate .garminconnect/oauth1_token.json",
                        "python3 scripts/arc_index.py llm.env"):
            self.assertEqual(self.sh(command), "deny", command)

    def test_lien_symbolique_sortant_refuse(self):
        outside = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(outside, ignore_errors=True))
        (outside / "s.json").write_text("{}", encoding="utf-8")
        (self.ws / "planning" / "lien.json").symlink_to(outside / "s.json")
        self.assertEqual(self.sh("python3 scripts/arc_log.py --input planning/lien.json"), "deny")


class WebFetchBypassTest(PolicyBase):
    def test_contournements_de_domaine_refuses(self):
        for url in ("https://evil.com\\.wttr.in/x", "https://wttr.in@evil.com/", "https://wttr.in.evil.com/",
                    "https://evilwttr.in/", "https://wttr.in%2eevil.com/", "https://%77ttr.in/",
                    "https://wttr.in:8443/x", "https://wttr.in:99999/", "ftp://wttr.in/", "//wttr.in/x",
                    "https://wttr.in\\@evil.com/", "https://wttr.іn/x", "https://xn--wttr-in-x.evil/",
                    "https://wttr.in./", " https://wttr.in/", "https://wttr.in/ x", "https:wttr.in",
                    "https://user:pw@wttr.in/", "https://wttr.in.@evil.com/"):
            self.assertEqual(self.d("web.fetch", {"url": url}), "deny", repr(url))

    def test_domaines_valides(self):
        for url in ("https://wttr.in/Lyon?format=j1", "http://wttr.in/Lyon", "https://WTTR.in/x",
                    "https://fr.wttr.in/x", "https://wttr.in:443/x", "https://wttr.in?x=1",
                    "https://nominatim.openstreetmap.org/search?q=Besan%C3%A7on"):
            self.assertEqual(self.d("web.fetch", {"url": url}), "allow", url)


class FsListGlobTest(PolicyBase):
    def test_glob_visant_un_secret_refuse(self):
        (self.ws / "config").mkdir()
        (self.ws / "config" / "llm.env").write_text("x", encoding="utf-8")
        for tool_input in ({"path": "config", "glob": "llm.env"},
                           {"glob": "config/llm.env"},
                           {"path": "config", "glob": "*.env"},
                           {"path": "config", "glob": "*"},
                           {"glob": "**/*.env"},
                           {"glob": "**"},
                           {"glob": "*"},
                           {"glob": "**/llm.*"},
                           {"glob": "*.{md,env}"},
                           {"glob": ["*.md", "llm.env"]},
                           {"glob": "llm.en?"},
                           {"glob": ".garminconnect/*"},
                           {"glob": ".g*/oauth*"},
                           {"glob": "*/*.env"},
                           {"glob": ".e*"}, {"glob": "*.env"}, {"glob": "*.token"}, {"glob": "*.pem"},
                           {"glob": "/etc/*"}, {"glob": "../*"}, {"glob": ".arc/**"}):
            self.assertEqual(self.d("fs.list", tool_input), "deny", tool_input)

    def test_glob_inoffensif_autorise(self):
        (self.ws / "activities").mkdir()
        for tool_input in ({"glob": "*.md"}, {"path": "activities", "glob": "*"}, {"glob": "planning/*.md"},
                           {"glob": "**/*.md"}, {"glob": ["*.md", "*.json"]}, {"glob": "*.{md,json}"},
                           {"path": "activities", "glob": "2026-*.md", "pattern": "llm.env"}):
            self.assertEqual(self.d("fs.list", tool_input), "allow", tool_input)

    def test_secret_reel_dans_un_dossier_de_donnees_detecte(self):
        (self.ws / "planning" / "x.token").write_text("x", encoding="utf-8")
        self.assertEqual(self.d("fs.list", {"path": "planning", "glob": "*"}), "deny")
        self.assertEqual(self.d("fs.list", {"glob": "planning/*"}), "deny")


class Round2PolicyTest(PolicyBase):
    """Revue 2 : options multi-valeurs, accolades, casse, recherche de contenu."""

    def sh(self, command):
        return self.d("shell", {"command": command})

    CC = "python3 skills/course-comparison/scripts/compare_course.py --lieu x --ref 2026-01-01"

    def test_b1_option_multivaleur_n_avale_pas_l_option_suivante(self):
        # argparse : aliases=[] et output=AGENTS.md — la politique doit voir la même chose.
        self.assertEqual(self.sh(self.CC + " --aliases --output AGENTS.md"), "deny")
        self.assertEqual(self.sh(self.CC + " --aliases a b --output AGENTS.md"), "deny")
        self.assertEqual(self.sh(self.CC + " --exclude-dates --output scripts/x.py"), "deny")
        self.assertEqual(self.sh(self.CC + " --aliases a b --output rapports/c.md"), "allow")
        self.assertEqual(self.sh(self.CC + " --aliases 'Tournai Trail' x --exclude-dates 2026-01-02 2026-01-03"), "allow")
        self.assertEqual(self.sh("python3 scripts/arc_index.py --validate activities/a.md activities/b.md"), "allow")
        self.assertEqual(self.sh("python3 scripts/arc_index.py --validate activities/a.md config/llm.env"),
                         "deny")

    def test_b1_valeur_commencant_par_tiret_refusee(self):
        for command in ("python3 scripts/arc_log.py --output --input",
                        "python3 scripts/arc_index.py --today --db",
                        "python3 scripts/arc_index.py --today=--db",
                        "python3 scripts/arc_index.py --days -5",
                        self.CC + " --dates --output"):
            self.assertEqual(self.sh(command), "deny", command)

    def test_n2_workspace_jamais_accepte(self):
        for script in ("scripts/arc_index.py", "scripts/arc_log.py", "scripts/arc_race_pacing.py",
                       "skills/course-comparison/scripts/compare_course.py"):
            self.assertEqual(self.sh(f"python3 {script} --workspace planning"), "deny", script)
            self.assertEqual(self.sh(f"python3 {script} --workspace=planning"), "deny", script)

    def test_b2_accolades_trop_larges_ou_trop_imbriquees_refusees(self):
        many = ",".join(f"x{i}" for i in range(70))
        self.assertEqual(self.d("fs.list", {"glob": "{" + many + ",config/llm.env}"}), "deny")
        self.assertEqual(self.d("fs.list", {"glob": "{a,{b,{c,{d,e}}}}"}), "deny")
        two = ",".join(f"a{i}" for i in range(9))
        self.assertEqual(self.d("fs.list", {"glob": "{" + two + "}{" + two + "}{" + two + "}"}), "deny")
        self.assertEqual(self.d("fs.list", {"glob": "*.{md,json}"}), "allow")

    def test_s1_casse_ignoree_pour_les_secrets_et_arc(self):
        for path in ("config/LLM.ENV", ".ARC/chat/approvals.json", "Planning/.ENV", "x/A.TOKEN"):
            self.assertEqual(self.d("fs.read", {"path": path}), "deny", path)
        for command in ("python3 scripts/arc_log.py --input .ARC/coach.db",
                        "python3 scripts/arc_index.py --validate config/LLM.ENV"):
            self.assertEqual(self.sh(command), "deny", command)
        for tool_input in ({"glob": ".ARC/**"}, {"glob": ".ARC/*.json"}, {"path": ".ARC", "glob": "*"},
                           {"glob": "config/LLM.ENV"}):
            self.assertEqual(self.d("fs.list", tool_input), "deny", tool_input)
        self.assertEqual(self.d("fs.write", {"path": "PLANNING/x.md"}), "deny")
        self.assertEqual(self.d("fs.write", {"path": "planning/LLM.ENV"}), "deny")

    def test_s3_recherche_de_contenu_limitee_aux_dossiers_surs(self):
        for tool_input in ({"pattern": "token"}, {"path": ".", "pattern": "x"}, {"path": "config", "pattern": "x"},
                           {"path": ".arc", "pattern": "x"}, {"path": "scripts", "pattern": "x"}):
            self.assertEqual(self.d("fs.list", tool_input), "deny", tool_input)
        for tool_input in ({"path": "planning", "pattern": "x"}, {"path": "docs", "pattern": "x"},
                           {"path": "resources/running", "pattern": "x"}, {"path": "skills", "pattern": "x"}):
            (self.ws / tool_input["path"]).mkdir(parents=True, exist_ok=True)
            self.assertEqual(self.d("fs.list", tool_input), "allow", tool_input)
        # noms seulement : la racine reste permise
        self.assertEqual(self.d("fs.list", {"path": ".", "glob": "*.md"}), "allow")


if __name__ == "__main__":
    unittest.main()


class GearPolicyTest(PolicyBase):
    """Matériel (#132-#135, arrivé sur main après le chat) : dossier gear/ et options d'arc_index."""

    def sh(self, command):
        return self.d("shell", {"command": command})

    def test_gear_est_un_dossier_de_donnees(self):
        self.assertEqual(self.d("fs.write", {"path": "gear/2026-09-30_abc_inspection.md"}), "allow")
        self.assertEqual(self.sh("python3 scripts/arc_index.py --validate gear/2026-09-30_abc_inspection.md"), "allow")

    def test_options_materiel_d_arc_index(self):
        for command in ("python3 scripts/arc_index.py equipment --kit nuit --sport trail",
                        "python3 scripts/arc_index.py inspections --gear abc",
                        "python3 scripts/arc_index.py gear --activities 1,2 --today 2026-09-30",
                        "python3 scripts/arc_index.py equipment --last-pass 2026-09-01",
                        "python3 scripts/arc_index.py gear-attribution --garmin-gear u1 --chat-gear abc"):
            self.assertEqual(self.sh(command), "allow", command)

    def test_race_plan_valeur_facultative(self):
        # nargs="?" : seule, suivie d'une autre option, ou avec un fichier du workspace.
        for command in ("python3 scripts/arc_index.py equipment --race-plan",
                        "python3 scripts/arc_index.py equipment --race-plan --today 2026-09-30",
                        "python3 scripts/arc_index.py equipment --race-plan planning/plan_course.md"):
            self.assertEqual(self.sh(command), "allow", command)
        for command in ("python3 scripts/arc_index.py equipment --race-plan /etc/passwd",
                        "python3 scripts/arc_index.py equipment --race-plan ~/x.md",
                        "python3 scripts/arc_index.py equipment --race-plan config/llm.env",
                        "python3 scripts/arc_index.py equipment --race-plan --output planning/x.md"):
            self.assertEqual(self.sh(command), "deny", command)


class ReadableWorkspaceTest(unittest.TestCase):
    """Installation réelle : AGENTS.md, config/workspace.toml, agents/, skills/, scripts/ sont des
    LIENS vers le moteur (install.sh). Le coach doit pouvoir les lire — sans rien écrire ailleurs."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        root = Path(self._tmp.name).resolve()
        self.engine, self.ws, outside = root / "engine", root / "ws", root / "ailleurs"
        for d in (self.engine / "skills" / "meteo", self.engine / "config", self.ws / "config",
                  self.ws / "planning", outside):
            d.mkdir(parents=True)
        (self.engine / "AGENTS.md").write_text("x", encoding="utf-8")
        (self.engine / "skills" / "meteo" / "SKILL.md").write_text("x", encoding="utf-8")
        (self.engine / "config" / "workspace.toml").write_text("x", encoding="utf-8")
        (self.engine / "config" / "llm.env").write_text("x", encoding="utf-8")
        (outside / "id_rsa").write_text("x", encoding="utf-8")
        (self.ws / "AGENTS.md").symlink_to(self.engine / "AGENTS.md")
        (self.ws / "skills").symlink_to(self.engine / "skills")
        (self.ws / "config" / "workspace.toml").symlink_to(self.engine / "config" / "workspace.toml")
        (self.ws / "config" / "workspace.user.toml").write_text("x", encoding="utf-8")
        (self.ws / "planning" / "cle").symlink_to(outside / "id_rsa")
        (self.ws / "planning" / "env").symlink_to(self.engine / "config" / "llm.env")
        self.policy = Policy(self.ws, {}, engine=self.engine)

    def d(self, tool, tool_input):
        return self.policy.decide(tool, tool_input)

    def test_liens_vers_le_moteur_lisibles(self):
        for path in ("AGENTS.md", "config/workspace.toml", "skills/meteo/SKILL.md",
                     str(self.ws / "config" / "workspace.toml"), str(self.engine / "skills" / "meteo" / "SKILL.md"),
                     "config/workspace.user.toml"):
            self.assertEqual(self.d("fs.read", {"path": path}), "allow", path)
        self.assertEqual(self.d("fs.list", {"path": "skills", "pattern": "météo"}), "allow")

    def test_liens_vers_ailleurs_ou_vers_un_secret_refuses(self):
        for path in ("planning/cle", "planning/env", str(self.engine / "config" / "llm.env"), "~/x", "../ailleurs/id_rsa"):
            self.assertEqual(self.d("fs.read", {"path": path}), "deny", path)

    def test_ecriture_jamais_dans_le_moteur_ni_la_config(self):
        for path in ("skills/meteo/SKILL.md", "AGENTS.md", "config/workspace.user.toml", "config/workspace.toml"):
            self.assertEqual(self.d("fs.write", {"path": path}), "deny", path)


class StdinScriptTest(PolicyBase):
    """`/log` : arc_log.py lit son JSON sur l'entrée standard (`echo '<json>' | …`, SKILL.md).
    Deux formes sans expansion acceptées, pour les seuls `[shell].stdin_scripts`."""

    J = '{"catalogue_paths": ["resources/nutrition/x.md"], "nutrition_items": [{"product": "gel", "qty": "2"}]}'

    def sh(self, command):
        return self.d("shell", {"command": command})

    def test_formes_sures_autorisees(self):
        self.assertEqual(self.sh(f"echo '{self.J}' | python3 scripts/arc_log.py"), "allow")
        self.assertEqual(self.sh(f"python3 scripts/arc_log.py << 'JSONEOF'\n{self.J}\nJSONEOF"), "allow")
        self.assertEqual(self.sh(f"echo '{self.J}' | python3 scripts/arc_log.py --output activities/o.json"), "allow")

    def test_formes_dangereuses_refusees(self):
        for command in (f'echo "{self.J}" | python3 scripts/arc_log.py',            # guillemets : $() interprété
                        f"python3 scripts/arc_log.py << JSONEOF\n{self.J}\nJSONEOF",  # délimiteur nu : expansion
                        f"python3 scripts/arc_log.py << 'E'\n{self.J}\nE\nrm -rf x\nE",  # heredoc fermé tôt
                        f"echo '{self.J}' | python3 scripts/arc_index.py",           # script sans stdin
                        f"echo '{self.J}' | python3 scripts/arc_log.py; rm x",
                        f"echo '{self.J}' | python3 scripts/arc_log.py --output /etc/x",
                        "echo 'a' ; rm x ; echo 'b' | python3 scripts/arc_log.py",
                        "cat planning/x | python3 scripts/arc_log.py",
                        f"echo '{self.J}' | python3 -c 'import os'"):
            self.assertEqual(self.sh(command), "deny", command)


class GearBackfillPolicyTest(PolicyBase):
    """Rattrapage du matériel Garmin (#145) : simulation libre, `--apply` soumis à l'accord."""

    def sh(self, command):
        return self.d("shell", {"command": command})

    def test_simulation_autorisee(self):
        for command in ("python3 scripts/garmin_gear_backfill.py",
                        "python3 scripts/garmin_gear_backfill.py --json --since 2026-01-01 --all-shoes"):
            self.assertEqual(self.sh(command), "allow", command)

    def test_apply_demande_l_accord(self):
        self.assertEqual(self.sh("python3 scripts/garmin_gear_backfill.py --apply"), "ask")
        self.assertEqual(self.sh("python3 scripts/garmin_gear_backfill.py --gear u1 --apply"), "ask")
        cmd = "python3 scripts/garmin_gear_backfill.py --apply"
        from arc_chat_backend import payload_hash
        self.assertEqual(self.d("shell", {"command": cmd},
                                preapproved={payload_hash("shell", {"command": cmd})}), "allow")

    def test_options_de_redirection_refusees(self):
        for command in ("python3 scripts/garmin_gear_backfill.py --tokens-dir x",
                        "python3 scripts/garmin_gear_backfill.py --workspace planning",
                        "python3 scripts/garmin_gear_backfill.py --fake-client x.json",
                        "python3 scripts/garmin_gear_backfill.py --apply=1"):
            self.assertEqual(self.sh(command), "deny", command)


class SkillScriptsPolicyTest(PolicyBase):
    """Scripts appelés par les skills (/week, cibles de séance, débrief, diagnostic, segments)."""

    def sh(self, command):
        return self.d("shell", {"command": command})

    def test_scripts_des_skills_autorises(self):
        for command in ("python3 scripts/arc_guardrails.py check --week planning/Semaine.md --memory",
                        "python3 scripts/arc_workout_targets.py targets --session planning/Semaine.md#mardi --memory",
                        "python3 scripts/arc_race_debrief.py debrief --plan planning/plan.md --activity activities/a.md",
                        "python3 scripts/coach_doctor.py --check garmin_token --json",
                        "python3 skills/session-parts-analyzer/scripts/analyze_session_parts.py --activity-id 1 --part strides"):
            self.assertEqual(self.sh(command), "allow", command)

    def test_diese_refuse_seulement_en_debut_de_mot(self):
        self.assertEqual(self.sh("python3 scripts/arc_index.py energy # ; rm -rf x"), "deny")
        self.assertEqual(self.sh("python3 scripts/arc_index.py energy #x"), "deny")
        self.assertEqual(self.sh("python3 scripts/arc_workout_targets.py targets --session planning/S.md#jeudi"), "allow")

    def test_options_dangereuses_refusees(self):
        for command in ("python3 scripts/coach_doctor.py --tokens-dir x",
                        "python3 scripts/coach_doctor.py --workspace planning",
                        "python3 scripts/coach_setup.py",
                        "python3 skills/session-parts-analyzer/scripts/analyze_session_parts.py --garmin-host evil.com",
                        "python3 skills/session-parts-analyzer/scripts/analyze_session_parts.py --output /tmp/x.json",
                        "python3 scripts/arc_race_debrief.py debrief --plan /etc/passwd"):
            self.assertEqual(self.sh(command), "deny", command)


class ShellNormalizationTest(PolicyBase):
    """Écritures inoffensives et fréquentes (observées en essai réel) : `2>&1` final, chemin
    absolu d'un script du workspace. Toute autre redirection reste refusée."""

    def sh(self, command):
        return self.d("shell", {"command": command})

    def test_2_vers_1_final_accepte(self):
        self.assertEqual(self.sh("python3 scripts/arc_index.py gear 2>&1"), "allow")
        self.assertEqual(self.sh("python3 scripts/arc_guardrails.py check --week planning/S.md --memory 2>&1"), "allow")

    def test_chemin_absolu_du_workspace_accepte(self):
        self.assertEqual(self.sh(f"python3 {self.ws}/scripts/arc_log.py --help"), "allow")
        self.assertEqual(self.sh(f"echo '{{}}' | python3 {self.ws}/scripts/arc_log.py"), "allow")

    def test_autres_redirections_et_chemins_refuses(self):
        for command in ("python3 scripts/arc_index.py gear 2>&1 > /tmp/x",
                        "python3 scripts/arc_index.py gear 2>/tmp/err",
                        "python3 scripts/arc_index.py gear 1>&2",
                        "python3 scripts/arc_index.py gear 2>&1; rm x",
                        "python3 scripts/arc_index.py gear 2>&1 | head -40",
                        "python3 /etc/scripts/arc_log.py",
                        f"python3 {self.ws}/../x/scripts/arc_log.py"):
            self.assertEqual(self.sh(command), "deny", command)


class ShellChainAndAbsoluteArgsTest(PolicyBase):
    """Chaînes `&&` / `;` de commandes autorisées et chemins absolus DANS le workspace (essai réel)."""

    def sh(self, command):
        return self.d("shell", {"command": command})

    def test_chaines_de_commandes_autorisees(self):
        self.assertEqual(self.sh("python3 scripts/arc_index.py gear 2>&1 && python3 scripts/arc_index.py equipment"), "allow")
        self.assertEqual(self.sh('python3 scripts/arc_index.py gear; echo "---"; python3 scripts/arc_index.py equipment'), "allow")
        self.assertEqual(self.sh("python3 scripts/garmin_gear_backfill.py && python3 scripts/garmin_gear_backfill.py --apply"), "ask")

    def test_chaines_dangereuses_refusees(self):
        for command in ("python3 scripts/arc_index.py gear && rm -rf x",
                        "python3 scripts/arc_index.py gear; cat config/workspace.toml",
                        'python3 scripts/arc_index.py gear; echo "$(id)"',
                        "python3 scripts/arc_index.py gear && echo ok | sh",
                        "python3 scripts/arc_index.py gear || rm x",
                        'python3 scripts/arc_index.py --validate "a;b"',
                        "echo hi"):
            self.assertEqual(self.sh(command), "deny", command)

    def test_chemin_absolu_dans_le_workspace(self):
        self.assertEqual(self.sh(f"python3 scripts/arc_guardrails.py check --week {self.ws}/planning/S.md --memory"), "allow")
        self.assertEqual(self.sh("python3 scripts/arc_guardrails.py check --week /etc/passwd"), "deny")
        self.assertEqual(self.sh(f"python3 scripts/arc_log.py --output {self.ws}/config/x.json"), "deny")


class MultiFilePatchTest(PolicyBase):
    """Revue : un patch OpenCode peut toucher plusieurs fichiers — chacun doit passer."""

    def patch(self, *lines):
        sys.path.insert(0, str(REPO / "scripts"))
        from arc_chat_opencode import canonical_tool
        text = "*** Begin Patch\n" + "\n".join(lines) + "\n*** End Patch"
        return canonical_tool("apply_patch", {"patchText": text})

    def test_toutes_les_cibles_doivent_passer(self):
        tool, inp = self.patch("*** Add File: planning/x.md", "+a", "*** Update File: .arc/chat/approvals.json", "+b")
        self.assertEqual(inp["paths"], ["planning/x.md", ".arc/chat/approvals.json"])
        self.assertEqual(self.d(tool, inp), "deny")
        tool, inp = self.patch("*** Add File: planning/x.md", "+a", "*** Update File: config/workspace.user.toml", "+b")
        self.assertEqual(self.d(tool, inp), "deny")

    def test_renommage_vers_l_exterieur_refuse(self):
        tool, inp = self.patch("*** Update File: planning/x.md", "*** Move to: config/x.md", "+a")
        self.assertEqual(self.d(tool, inp), "deny")

    def test_patch_entierement_dans_les_dossiers_de_donnees_autorise(self):
        tool, inp = self.patch("*** Add File: planning/x.md", "+a", "*** Update File: activities/y.md", "+b")
        self.assertEqual(self.d(tool, inp), "allow")

    def test_patch_sans_cible_refuse(self):
        tool, inp = self.patch("rien")
        self.assertEqual(self.d(tool, inp), "deny")
