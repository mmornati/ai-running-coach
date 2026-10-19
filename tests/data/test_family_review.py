"""Palier D — mode famille (#127), durcissements de la revue : environnement des backends, plafond du foyer
sous concurrence, configuration cassée d'un membre, exposition réseau, doctor, OpenCode."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))

import arc_chat as C  # noqa: E402
import arc_chat_mock as M  # noqa: E402
import arc_family as F  # noqa: E402
from arc_chat_backend import BackendError  # noqa: E402
from coach_config import ConfigError  # noqa: E402
import tests.data.test_family_isolation as T  # noqa: E402


class FamilyEnvCase(T.FamilyCase):
    def mock_registry(self, extra_family: str = ""):
        """Registre dont les membres utilisent le backend « mock », chargé par le vrai `load_backend`."""
        cfg = '[chat]\nenabled = true\nbackend = "mock"\n'
        workspaces = {m: T.make_workspace(self.root, m, cfg) for m in ("alice", "bob")}
        return self.registry(workspaces=workspaces, extra_family=extra_family)


class TestBackendEnvironment(FamilyEnvCase):
    """BLOQUANT de la revue : les outils shell héritaient `$ARC_WORKSPACE` / le pointeur → workspace d'un autre membre."""

    def foreign_base(self, home: Path) -> dict:
        return {"ARC_WORKSPACE": str(self.root / "coach-alice"), "GARMINTOKENS": "/tok/alice",
                "GARMIN_TOKENS_DIR": "/tok", "GARMINTOKENS_BASE64": "e30=",
                "INTERVALS_ICU_API_KEY": "cle-foyer", "INTERVALS_ICU_ATHLETE_ID": "i1", "HOME": str(home), "PATH": os.environ.get("PATH", ""),
                "KEEP_ME": "1"}

    def test_chaque_backend_recoit_son_workspace_et_aucune_valeur_etrangere(self):
        fam = C.FamilyChat(self.mock_registry())            # vrai load_backend("mock")
        base = self.foreign_base(self.root / "home")
        for member in ("alice", "bob"):
            backend = fam.services[member].backend
            self.assertEqual(backend.family_member, member)
            env = backend.child_env(base)
            self.assertEqual(env["ARC_WORKSPACE"], str(self.workspaces[member]))
            self.assertEqual(env["ARC_LOCK_WORKSPACE"], "1")
            self.assertNotIn("GARMINTOKENS", env)
            self.assertNotIn("GARMIN_TOKENS_DIR", env)
            for leaked in ("GARMINTOKENS_BASE64", "INTERVALS_ICU_API_KEY", "INTERVALS_ICU_ATHLETE_ID"):
                self.assertNotIn(leaked, env)                 # la clé intervals du foyer ne doit pas ouvrir les données d'un autre
            self.assertEqual(env["KEEP_ME"], "1")             # le reste de l'environnement est conservé
        self.assertNotEqual(fam.services["alice"].backend.child_env(base)["ARC_WORKSPACE"],
                            fam.services["bob"].backend.child_env(base)["ARC_WORKSPACE"])

    SECRETS = ("STRAVA_CLIENT_ID", "STRAVA_CLIENT_SECRET", "STRAVA_TOKEN_FILE", "STRAVA_ACCESS_TOKEN",
               "MYWHOOSH_USERNAME", "MYWHOOSH_PASSWORD", "ARC_OW_API_KEY_FILE", "ARC_OW_BASE_URL",
               "TELEGRAM_BOT_TOKEN", "NTFY_TOKEN_FILE", "AZURE_SPEECH_KEY", "GARMIN_EMAIL", "OURA_PAT",
               "ACME_API_TOKEN", "FOO_SECRET", "SOME_SERVICE_KEY", "DB_PASSWD")

    def secret_env(self, home: Path) -> dict:
        return dict({name: "valeur-foyer" for name in self.SECRETS}, HOME=str(home), PATH="/usr/bin", LANG="fr_FR.UTF-8",
                    TZ="Europe/Paris", XDG_CONFIG_HOME="/x", ANTHROPIC_API_KEY="cle-llm", MY_LLM_KEY="cle-llm-2")

    def test_identifiants_retires_par_motif_pour_tout_backend_membre(self):
        """Défaut verrouillé : liste fermée de noms -> Strava, MyWhoosh, Telegram, ntfy... et tout futur fournisseur
        restaient visibles des outils et serveurs MCP d'un membre."""
        fam = C.FamilyChat(self.mock_registry())
        base = self.secret_env(self.root / "home")
        env = fam.services["alice"].backend.child_env(base)
        for name in self.SECRETS:
            self.assertNotIn(name, env, name)
        for name in ("PATH", "HOME", "LANG", "TZ", "XDG_CONFIG_HOME"):
            self.assertEqual(env[name], base[name])
        # clé LLM configurée du membre : conservée
        backend = M.MockBackend(self.workspaces["alice"], {"family_member": "alice", "api_key_env": "MY_LLM_KEY"})
        env = backend.child_env(base)
        self.assertEqual(env["MY_LLM_KEY"], "cle-llm-2")
        self.assertNotIn("ANTHROPIC_API_KEY", env)
        self.assertNotIn("ACME_API_TOKEN", env)

    def test_api_key_env_ne_peut_pas_exempter_un_identifiant_du_foyer(self):
        """Défaut verrouillé : `api_key_env = "GARMINTOKENS"` d'un membre exemptait l'identifiant du foyer du nettoyage."""
        from arc_chat_claude import ClaudeBackend
        alice_ws = T.make_workspace(self.root, "alice")
        base = dict(self.secret_env(self.root), GARMINTOKENS="/tok/foyer", INTERVALS_ICU_API_KEY="cle-foyer")
        for name in ("GARMINTOKENS", "INTERVALS_ICU_API_KEY", "STRAVA_CLIENT_SECRET"):
            env = M.MockBackend(alice_ws, {"family_member": "alice", "api_key_env": name}).child_env(base)
            self.assertNotIn(name, env, name)
            ws = self.root / "coach-bob"
            ws.mkdir(exist_ok=True)
            sdk = SimpleNamespace(ClaudeAgentOptions=lambda **kw: kw, HookMatcher=lambda **kw: kw,
                                  PermissionResultAllow=lambda: None, PermissionResultDeny=lambda **kw: None)
            turn = SimpleNamespace(ctx=SimpleNamespace(language="fr", config={}), gate_sync=lambda *a: ("deny", ""))
            with mock.patch.dict(os.environ, base, clear=True):
                opts = ClaudeBackend(ws, {"family_member": "bob", "api_key_env": name})._options(sdk, turn, None)["env"]
            self.assertEqual(opts[name], "", name)
        # clés LLM légitimes : conservées
        for name in ("ANTHROPIC_API_KEY", "OPENROUTER_API_KEY", "MY_LLM_KEY"):
            env = M.MockBackend(alice_ws, {"family_member": "alice", "api_key_env": name}).child_env(
                dict(base, **{name: "cle-llm"}))
            self.assertEqual(env[name], "cle-llm", name)

    def test_membre_dont_api_key_env_designe_un_identifiant_du_foyer_refuse_en_503(self):
        cfg = '[chat]\nenabled = true\nbackend = "mock"\napi_key_env = "GARMINTOKENS"\n'
        workspaces = {"alice": T.make_workspace(self.root, "alice", '[chat]\nenabled = true\nbackend = "mock"\n'),
                      "bob": T.make_workspace(self.root, "bob", cfg)}
        fam = C.FamilyChat(self.registry(workspaces=workspaces))
        self.assertEqual(sorted(fam.errors), ["bob"])
        self.assertEqual(sorted(fam.services), ["alice"])
        self.assertIn("GARMINTOKENS", fam.errors["bob"])

    def test_hors_mode_famille_aucun_identifiant_retire(self):
        backend = M.MockBackend(T.make_workspace(self.root, "alice"), {})
        base = self.secret_env(self.root / "home")
        self.assertEqual(backend.family_overlay(base), {})
        self.assertEqual(backend.child_env(base), base)

    def test_claude_options_videntes_identifiants_mais_gardent_la_cle_llm(self):
        from arc_chat_claude import ClaudeBackend
        ws = self.root / "coach-bob"
        ws.mkdir()
        sdk = SimpleNamespace(ClaudeAgentOptions=lambda **kw: kw, HookMatcher=lambda **kw: kw,
                              PermissionResultAllow=lambda: None, PermissionResultDeny=lambda **kw: None)
        turn = SimpleNamespace(ctx=SimpleNamespace(language="fr", config={}), gate_sync=lambda *a: ("deny", ""))
        for cfg, var in (({}, "ANTHROPIC_API_KEY"), ({"api_key_env": "MY_LLM_KEY"}, "MY_LLM_KEY")):
            with mock.patch.dict(os.environ, self.secret_env(self.root), clear=True):
                env = ClaudeBackend(ws, dict(cfg, family_member="bob"))._options(sdk, turn, None)["env"]
            for name in self.SECRETS:
                self.assertEqual(env[name], "", name)         # le SDK fusionne par-dessus os.environ : blanc
            # la clé LLM du membre atteint bien le processus Claude (ordre de fusion : posée APRÈS le recouvrement)
            self.assertEqual(env["ANTHROPIC_API_KEY"], "cle-llm" if var == "ANTHROPIC_API_KEY" else "cle-llm-2")
            self.assertEqual(env["CLAUDE_CODE_OAUTH_TOKEN"], "")
            self.assertNotIn("PATH", env)                     # non secret : hérité tel quel, jamais touché
            self.assertEqual(env["ARC_WORKSPACE"], str(ws))

    def test_opencode_serveur_sans_identifiants_du_foyer_avec_cle_llm(self):
        from arc_chat_opencode import OpenCodeBackend
        ws = self.root / "coach-bob"
        ws.mkdir()
        backend = OpenCodeBackend(ws, {"family_member": "bob", "model": "openrouter/some-model",
                                       "api_key_env": "MY_LLM_KEY"})
        captured = {}

        def fake_spawn(cmd, env, cwd, log_path):
            captured.update(env)
            raise OSError("stop")
        with mock.patch.dict(os.environ, self.secret_env(self.root), clear=True), \
                mock.patch.object(backend, "_binary", return_value="/bin/true"), \
                mock.patch.object(backend, "_auth_missing", return_value=None), \
                mock.patch.object(backend, "_need_key", return_value=True), \
                mock.patch.object(backend, "_reap_stale"), \
                mock.patch.object(backend, "_spawn", side_effect=fake_spawn), \
                self.assertRaises(BackendError):
            backend._ensure_server()
        for name in self.SECRETS + ("ANTHROPIC_API_KEY",):
            self.assertNotIn(name, captured, name)
        self.assertEqual(captured["MY_LLM_KEY"], "cle-llm-2")
        self.assertEqual(captured["PATH"], "/usr/bin")
        self.assertEqual(captured["HOME"], str(self.root))

    def test_mono_athlete_environnement_inchange(self):
        ws = T.make_workspace(self.root, "alice")
        backend = M.MockBackend(ws, {})
        base = {"ARC_WORKSPACE": "/x", "GARMINTOKENS": "/y"}
        self.assertEqual(backend.family_overlay(), {})
        self.assertEqual(backend.child_env(base), base)

    def test_script_autorise_de_bob_ne_lit_que_bob_meme_si_l_environnement_parent_pointe_vers_alice(self):
        fam = C.FamilyChat(self.mock_registry())
        home = self.root / "home"
        (home / ".config/ai-running-coach").mkdir(parents=True)
        (home / ".config/ai-running-coach/workspace").write_text(str(self.workspaces["alice"]), encoding="utf-8")
        base = self.foreign_base(home)                         # parent : ARC_WORKSPACE ET pointeur → Alice
        cmd = [sys.executable, str(REPO / "scripts/arc_index.py"), "decisions", "--days", "3650", "--json"]

        def run(env):
            done = subprocess.run(cmd, env=env, cwd=str(self.root), capture_output=True, text=True, timeout=120)
            return done.stdout + done.stderr

        # témoin : sans l'environnement du membre, le script lit le workspace d'ALICE (le défaut corrigé)
        leaked = run(base)
        self.assertIn("ALICEMARK", leaked)
        # avec l'environnement du backend de Bob : Bob, et seulement Bob
        own = run(fam.services["bob"].backend.child_env(base))
        self.assertIn("BOBMARK", own)
        self.assertNotIn("ALICEMARK", own)
        # et inversement
        mine = run(fam.services["alice"].backend.child_env(dict(base, ARC_WORKSPACE=str(self.workspaces["bob"]))))
        self.assertIn("ALICEMARK", mine)
        self.assertNotIn("BOBMARK", mine)

    def test_claude_options_imposent_le_workspace_du_membre(self):
        from arc_chat_claude import ClaudeBackend
        ws = self.root / "coach-bob"
        ws.mkdir()
        sdk = SimpleNamespace(ClaudeAgentOptions=lambda **kw: kw, HookMatcher=lambda **kw: kw,
                              PermissionResultAllow=lambda: None, PermissionResultDeny=lambda **kw: None)
        turn = SimpleNamespace(ctx=SimpleNamespace(language="fr", config={}), gate_sync=lambda *a: ("deny", ""))
        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "k"}):
            family = ClaudeBackend(ws, {"family_member": "bob"})._options(sdk, turn, None)
            single = ClaudeBackend(ws, {})._options(sdk, turn, None)
        self.assertEqual(family["env"]["ARC_WORKSPACE"], str(ws))
        self.assertEqual(family["env"]["ARC_LOCK_WORKSPACE"], "1")
        self.assertEqual(family["env"]["GARMINTOKENS"], "")         # le SDK fusionne PAR-DESSUS os.environ : on vide
        self.assertEqual(family["env"]["GARMIN_TOKENS_DIR"], "")
        for name in ("GARMINTOKENS_BASE64", "INTERVALS_ICU_API_KEY", "INTERVALS_ICU_ATHLETE_ID"):
            self.assertEqual(family["env"][name], "")
        self.assertNotIn("ARC_WORKSPACE", single["env"])             # mono-athlète : inchangé

    def test_opencode_serveur_lance_avec_l_environnement_du_membre(self):
        from arc_chat_opencode import OpenCodeBackend
        ws = self.root / "coach-bob"
        ws.mkdir()
        backend = OpenCodeBackend(ws, {"family_member": "bob", "model": "openrouter/some-model"})
        captured = {}

        def fake_spawn(cmd, env, cwd, log_path):
            captured.update(env)
            raise OSError("stop")
        with mock.patch.dict(os.environ, {"ARC_WORKSPACE": "/autre", "GARMINTOKENS": "/jetons-autre",
                                      "INTERVALS_ICU_API_KEY": "cle-foyer", "HOME": str(self.root)}), \
                mock.patch.object(backend, "_binary", return_value="/bin/true"), \
                mock.patch.object(backend, "_auth_missing", return_value=None), \
                mock.patch.object(backend, "_need_key", return_value=False), \
                mock.patch.object(backend, "_reap_stale"), \
                mock.patch.object(backend, "_spawn", side_effect=fake_spawn), \
                self.assertRaises(BackendError):
            backend._ensure_server()
        self.assertEqual(captured["ARC_WORKSPACE"], str(ws))
        self.assertEqual(captured["ARC_LOCK_WORKSPACE"], "1")
        self.assertNotIn("GARMINTOKENS", captured)
        self.assertNotIn("INTERVALS_ICU_API_KEY", captured)

    def test_opencode_ne_lit_pas_la_config_systeme_en_mode_famille(self):
        from arc_chat_opencode import OpenCodeBackend
        home = self.root / "home"
        (home / ".config/opencode").mkdir(parents=True)
        (home / ".config/opencode/opencode.json").write_text(
            json.dumps({"mcp": {"garmin": {"type": "local", "command": ["x"], "environment": {"TOK": "autre"}}}}))
        ws = self.root / "coach-bob"
        ws.mkdir()
        with mock.patch.dict(os.environ, {"HOME": str(home)}):
            self.assertIn("garmin", OpenCodeBackend(ws, {})._read_mcp())          # mono-athlète : repli conservé
            self.assertEqual(OpenCodeBackend(ws, {"family_member": "bob"})._read_mcp(), {})
            (ws / ".mcp.json").write_text(json.dumps(
                {"mcpServers": {"garmin": {"command": "garmin-mcp", "args": ["stdio"], "env": {"GARMINTOKENS": "/b"}}}}))
            self.assertIn("garmin", OpenCodeBackend(ws, {"family_member": "bob"})._read_mcp())   # son .mcp.json, oui


class BlockingBackend(M.MockBackend):
    """Tour qui reste ouvert tant que `release` n'est pas posé (réservation de budget en cours)."""

    release = None
    boom = False

    def run_turn(self, ctx, user_message):
        if self.boom:
            raise BackendError("échec simulé")
        self.release.wait(10)


class TestHouseholdCap(T.ChatCase):
    def household(self, backend_cls=None, cap="1.0"):
        registry = self.registry(extra_family=f"daily_budget_eur = {cap}")
        backend_cls = backend_cls or M.MockBackend
        fam = C.FamilyChat(registry, lambda m, c: backend_cls(m.workspace, c))
        return registry, fam

    def test_reservations_concurrentes_ne_depassent_jamais_le_plafond_du_foyer(self):
        _, fam = self.household(cap="1.0")
        grants, turns = [], []
        for member in ("alice", "bob"):
            svc = fam.services[member]
            for i in range(4):
                turn = C.Turn(svc, f"{member}-sess-{i}")
                svc.turns[turn.session_id] = turn
                turns.append((svc, turn))
        barrier = threading.Barrier(len(turns))

        def reserve(svc, turn):
            barrier.wait()
            grants.append(svc.reserve_turn_budget(turn))
        threads = [threading.Thread(target=reserve, args=pair) for pair in turns]
        for t in threads:
            t.start()
        for t in threads:
            t.join(10)
        self.assertEqual(len(grants), 8)
        self.assertLessEqual(sum(grants), 1.0 + 1e-9)               # le cas fautif accordait 1,0 € PAR membre
        self.assertGreater(sum(grants), 0.0)
        self.assertAlmostEqual(fam.outstanding(), sum(grants))
        for svc, turn in turns:
            svc.release_turn_budget(turn.session_id)
        self.assertEqual(fam.outstanding(), 0.0)
        self.assertGreater(turns[0][0].reserve_turn_budget(turns[0][1]), 0.0)        # libéré : de nouveau disponible

    def test_reservation_visible_entre_membres_puis_liberee_a_la_fin_du_tour(self):
        gate = threading.Event()

        class Held(BlockingBackend):
            release = gate
        _, fam = self.household(Held, cap="1.0")
        a, b = fam.services["alice"], fam.services["bob"]
        sid = a.sessions.create("mock", "m")["id"]
        code, turn, _ = a.begin_turn(sid, "alice", "bonjour")
        self.assertEqual(code, "ok")
        for _ in range(100):
            if fam.outstanding() > 0:
                break
            time.sleep(0.02)
        self.assertAlmostEqual(fam.outstanding(), 1.0)             # tout le plafond est réservé par le tour d'Alice
        sid_b = b.sessions.create("mock", "m")["id"]
        turn_b = C.Turn(b, sid_b)
        b.turns[sid_b] = turn_b
        self.assertEqual(b.reserve_turn_budget(turn_b), 0.0)       # Bob ne peut rien réserver
        gate.set()
        for _ in range(200):
            if not a.turns:
                break
            time.sleep(0.02)
        self.assertEqual(fam.outstanding(), 0.0)                    # libéré à la fin du tour
        self.assertGreater(b.reserve_turn_budget(turn_b), 0.0)

    def test_message_distinct_quand_le_budget_est_reserve_par_un_autre_membre(self):
        gate = threading.Event()

        class Held(BlockingBackend):
            release = gate
        _, fam = self.household(Held, cap="1.0")
        a, b = fam.services["alice"], fam.services["bob"]
        code, _, _ = a.begin_turn(a.sessions.create("mock", "m")["id"], "alice", "bonjour")
        self.assertEqual(code, "ok")
        for _ in range(100):
            if fam.outstanding() > 0:
                break
            time.sleep(0.02)

        def blocked_message(svc, who):
            code, _, q = svc.begin_turn(svc.sessions.create("mock", "m")["id"], who, "bonjour")
            self.assertEqual(code, "ok")
            while True:
                etype, data = q.get(timeout=10)
                if etype == "error":
                    return data["message"]
        # Bob est bloqué par le tour d'Alice : message propre au foyer, pas le message générique
        self.assertIn("d'un autre membre", blocked_message(b, "bob"))
        # Alice, bloquée par sa propre réservation (autre conversation à elle) : message historique
        self.assertIn("réservé par une autre conversation", blocked_message(a, "alice"))
        gate.set()

    def test_reservation_liberee_aussi_en_cas_d_erreur(self):
        class Failing(BlockingBackend):
            boom = True
        _, fam = self.household(Failing, cap="1.0")
        a = fam.services["alice"]
        sid = a.sessions.create("mock", "m")["id"]
        self.assertEqual(a.begin_turn(sid, "alice", "bonjour")[0], "ok")
        for _ in range(200):
            if not a.turns:
                break
            time.sleep(0.02)
        self.assertEqual(fam.outstanding(), 0.0)

    def test_statut_reflete_le_reste_effectif(self):
        _, fam = self.household(cap="1.0")
        fam.services["alice"].spend.add(0.7)
        budget = fam.services["bob"].status("bob")["budget"]
        self.assertAlmostEqual(budget["remaining_eur"], 0.3)        # min(propre 2,0 ; foyer 0,3)
        self.assertEqual(budget["limit_eur"], 2.0)                  # clé historique inchangée
        self.assertEqual(budget["household_limit_eur"], 1.0)

    def test_statut_mono_athlete_inchange(self):
        ws = T.make_workspace(self.root, "alice")
        svc = C.ChatService(ws, dict(C.CHAT_DEFAULTS), M.MockBackend(ws, {}))
        self.assertEqual(set(svc.status("local")["budget"]), {"spent_eur", "limit_eur"})


class TestMemberIsolationOfFailures(T.ChatCase):
    def test_config_cassee_d_un_membre_ne_tue_pas_les_autres(self):
        registry = self.registry()
        (self.workspaces["bob"] / "config/workspace.user.toml").write_text("[chat\ncassé = ", encoding="utf-8")
        port = self.start(registry)
        self.assertEqual(list(self.fam.services), ["alice"])
        self.assertIn("bob", self.fam.errors)
        self.assertEqual(self.call(port, "GET", "/api/chat/status", "alice")[0], 200)
        status, body = self.call(port, "GET", "/api/chat/status", "bob")
        self.assertEqual(status, 503)
        self.assertNotIn("TOML", json.dumps(body))                   # pas de détail de configuration vers le navigateur

    def test_backend_introuvable_idem(self):
        cfg = '[chat]\nbackend = "inexistant"\n'
        workspaces = {"alice": T.make_workspace(self.root, "alice"), "bob": T.make_workspace(self.root, "bob", cfg)}
        fam = C.FamilyChat(T.FamilyCase.registry(self, workspaces=workspaces))
        self.assertEqual(sorted(fam.errors), ["bob"])
        self.assertEqual(sorted(fam.services), ["alice"])


class TestExposure(T.ChatCase):
    def test_ecoute_reseau_sans_hote_public_refusee(self):
        registry = self.registry()
        registry.settings["listen"] = "0.0.0.0"
        registry.settings["allowed_hosts"] = []
        registry.settings["public_url"] = ""
        fam = C.FamilyChat(registry, lambda m, c: M.MockBackend(m.workspace, c))
        with self.assertRaises(ConfigError):
            C.make_family_server(fam, 0)

    def test_ecoute_reseau_avec_hote_public_acceptee(self):
        registry = self.registry()
        registry.settings["listen"] = "127.0.0.1"
        fam = C.FamilyChat(registry, lambda m, c: M.MockBackend(m.workspace, c))
        httpd = C.make_family_server(fam, 0)
        httpd.server_close()


class TestDoctorDiscretion(T.FamilyCase):
    def setUp(self):
        super().setUp()
        import coach_doctor as D
        self.D = D
        self.path = self.registry_file()

    def test_aucune_decouverte_implicite_du_registre(self):
        with mock.patch.dict(os.environ, {}), mock.patch("arc_family.default_registry_path", return_value=self.path):
            os.environ.pop("ARC_FAMILY", None)
            os.environ.pop("ARC_LOCK_WORKSPACE", None)
            self.assertEqual(self.D._family_registry(None), (None, None, None))

    def test_registre_explicite_ou_variable_d_environnement(self):
        with mock.patch.dict(os.environ, {}):
            os.environ.pop("ARC_LOCK_WORKSPACE", None)
            os.environ.pop("ARC_FAMILY", None)
            self.assertIsNotNone(self.D._family_registry(str(self.path))[1])
            os.environ["ARC_FAMILY"] = str(self.path)
            self.assertIsNotNone(self.D._family_registry(None)[1])

    def test_rien_depuis_une_session_confinee_a_un_workspace(self):
        with mock.patch.dict(os.environ, {"ARC_LOCK_WORKSPACE": "1", "ARC_FAMILY": str(self.path)}):
            self.assertEqual(self.D._family_registry(str(self.path)), (None, None, None))


if __name__ == "__main__":
    unittest.main()
