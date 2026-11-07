"""Palier D — briques du service de chat (`scripts/arc_chat.py`) : jetons, dépense, approbations, garde HTTP."""

from __future__ import annotations

import json
import os
import stat
import sys
import tempfile
import unittest
from unittest import mock
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))

import arc_chat as C  # noqa: E402
from arc_chat_backend import payload_hash  # noqa: E402

TOOL = "mcp:garmin.schedule_workouts"
INPUT = {"workouts": [{"date": "2026-10-01"}]}


class Clock:
    def __init__(self, now=1000.0):
        self.now = now

    def __call__(self):
        return self.now


class UsageLogTest(unittest.TestCase):
    def _line(self, env):
        with mock.patch.dict(os.environ, env), mock.patch("sys.stderr") as err:
            C.log_usage("claude", "claude-sonnet-5-5", {"input_tokens": 3, "output_tokens": 2, "cost_eur": 0.01})
        return "".join(c.args[0] for c in err.write.call_args_list)

    def test_off_by_default(self):
        with mock.patch.dict(os.environ):
            os.environ.pop("ARC_CHAT_USAGE_LOG", None)
            self.assertEqual(self._line({}), "")

    def test_one_json_line_with_numbers_only(self):
        line = json.loads(self._line({"ARC_CHAT_USAGE_LOG": "1"}))
        self.assertEqual(line["event"], "llm_usage")
        self.assertEqual(line["gen_ai_usage_input_tokens"], 3)
        self.assertEqual(line["gen_ai_request_model"], "claude-sonnet-5-5")


class TmpCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)


class TestApprovalStore(TmpCase):
    def make(self):
        self.clock = Clock()
        return C.ApprovalStore(self.dir / "approvals.json", clock=self.clock)

    def create(self, store, token_ttl=60.0, ttl=600.0):
        return store.create("sess1234", TOOL, INPUT, "Jeudi : EF 45 min", [], ttl, token_ttl)

    def test_seuls_les_hachages_sont_stockes(self):
        store = self.make()
        rec, tokens = self.create(store)
        raw = (self.dir / "approvals.json").read_text(encoding="utf-8")
        for token in tokens.values():
            self.assertNotIn(token, raw)
            self.assertNotIn(token.split(".", 1)[1], raw)
        self.assertEqual(set(rec["token_hashes"]), {"allow", "deny"})
        self.assertTrue(tokens["allow"].startswith(rec["id"] + "."))
        self.assertEqual(rec["hash"], payload_hash(TOOL, INPUT))

    def test_pas_de_jeton_sans_quick_approve(self):
        store = self.make()
        rec, tokens = self.create(store, token_ttl=None)
        self.assertEqual(tokens, {})
        self.assertEqual(store.verify_token(f"{rec['id']}.abc", "allow")[0], "unknown")

    def test_jeton_valide_puis_brule_par_la_premiere_decision(self):
        store = self.make()
        rec, tokens = self.create(store)
        self.assertEqual(store.verify_token(tokens["allow"], "allow")[0], "ok")
        self.assertEqual(store.resolve(rec["id"], "allow")[0], "ok")
        # les DEUX jetons sont brûlés
        self.assertEqual(store.verify_token(tokens["allow"], "allow")[0], "used")
        self.assertEqual(store.verify_token(tokens["deny"], "deny")[0], "used")

    def test_jeton_lie_a_l_action(self):
        store = self.make()
        _, tokens = self.create(store)
        self.assertEqual(store.verify_token(tokens["allow"], "deny")[0], "unknown")

    def test_jeton_expire(self):
        store = self.make()
        _, tokens = self.create(store, token_ttl=60)
        self.clock.now += 61
        self.assertEqual(store.verify_token(tokens["allow"], "allow")[0], "expired")

    def test_jeton_refuse_si_la_charge_a_change(self):
        store = self.make()
        rec, tokens = self.create(store)
        data = json.loads((self.dir / "approvals.json").read_text(encoding="utf-8"))
        data[rec["id"]]["input"] = {"workouts": [{"date": "2026-12-25"}]}
        (self.dir / "approvals.json").write_text(json.dumps(data), encoding="utf-8")
        self.assertEqual(store.verify_token(tokens["allow"], "allow")[0], "mismatch")

    def test_jetons_inconnus_ou_malformes(self):
        store = self.make()
        rec, tokens = self.create(store)
        for bad in ("", "abc", "x.y", f"{rec['id']}.faux", "..", tokens["allow"] + "x"):
            self.assertEqual(store.verify_token(bad, "allow")[0], "unknown", bad)

    def test_statuts_attente_pending_decision(self):
        store = self.make()
        rec, _ = self.create(store)
        self.assertEqual(store.get(rec["id"])["status"], "waiting")
        self.assertTrue(store.mark_pending(rec["id"]))
        self.assertEqual(store.get(rec["id"])["status"], "pending")
        result, done = store.resolve(rec["id"], "allow")
        self.assertEqual((result, done["status"], done["previous_status"]), ("ok", "allowed", "pending"))
        self.assertEqual(store.resolve(rec["id"], "deny")[0], "closed")
        self.assertEqual(store.resolve("inexistant1", "deny")[0], "unknown")

    def test_expiration_de_la_proposition(self):
        store = self.make()
        rec, tokens = self.create(store, ttl=100)
        store.mark_pending(rec["id"])
        self.clock.now += 101
        expired = store.expire_due()
        self.assertEqual([e["id"] for e in expired], [rec["id"]])
        self.assertEqual(store.get(rec["id"])["status"], "expired")
        self.assertEqual(store.resolve(rec["id"], "allow")[0], "expired")
        self.assertEqual(store.verify_token(tokens["allow"], "allow")[0], "used")

    def test_orphelins_repris_au_demarrage(self):
        store = self.make()
        rec, _ = self.create(store)
        self.assertEqual(store.reopen_orphans(), 1)
        self.assertEqual(store.get(rec["id"])["status"], "pending")

    def test_annulation_a_son_propre_statut(self):
        store = self.make()
        rec, tokens = self.create(store)
        result, done = store.resolve(rec["id"], "cancelled")
        self.assertEqual((result, done["status"]), ("ok", "cancelled"))
        self.assertEqual(store.verify_token(tokens["deny"], "deny")[0], "used")

    def test_expiration_notifiee_par_toutes_les_voies(self):
        seen = []
        for voie in ("get", "list", "resolve", "verify", "expire_due"):
            store = self.make()
            store.on_expired = lambda records, seen=seen: seen.extend(r["id"] for r in records)
            rec, tokens = self.create(store, ttl=100)
            store.mark_pending(rec["id"])
            self.clock.now += 101
            seen.clear()
            if voie == "get":
                store.get(rec["id"])
            elif voie == "list":
                store.list()
            elif voie == "resolve":
                store.resolve(rec["id"], "allow")
            elif voie == "verify":
                store.verify_token(tokens["allow"], "allow")
            else:
                store.expire_due()
            self.assertEqual(seen, [rec["id"]], voie)
            store.get(rec["id"])
            self.assertEqual(seen, [rec["id"]], f"{voie} : notifiée une seule fois")
            (self.dir / "approvals.json").unlink()

    def test_approbation_tardive_marquee_a_reprendre(self):
        store = self.make()
        rec, _ = self.create(store)
        store.mark_pending(rec["id"])
        self.assertEqual(store.resolve(rec["id"], "allow")[1]["resume"], "queued")
        self.assertEqual([r["id"] for r in store.queued_resumes()], [rec["id"]])
        store.set_resume(rec["id"], "failed", status="unexecuted")
        self.assertEqual(store.queued_resumes(), [])
        self.assertEqual(store.get(rec["id"])["status"], "unexecuted")
        # une approbation en cours de tour (waiting) n'a rien à reprendre
        other, _ = self.create(store)
        self.assertNotIn("resume", store.resolve(other["id"], "allow")[1])

    def test_identifiants_invalides_ne_touchent_pas_le_disque(self):
        store = self.make()
        self.assertIsNone(store.get("../../etc/passwd"))


class TestSpendAndSessions(TmpCase):
    def test_depense_du_jour_cumulee_et_par_jour(self):
        day = [date(2026, 9, 29)]
        spend = C.SpendStore(self.dir, today=lambda: day[0])
        self.assertEqual(spend.spent(), 0.0)
        spend.add(0.25)
        spend.add(0.5)
        spend.add(-3)                       # ignoré
        self.assertAlmostEqual(spend.spent(), 0.75)
        data = json.loads((self.dir / "spend-2026-09-29.json").read_text(encoding="utf-8"))
        self.assertEqual(list(data), ["chat_eur"])
        day[0] = date(2026, 9, 30)
        self.assertEqual(spend.spent(), 0.0)

    def test_sessions_meta_et_journal(self):
        store = C.SessionStore(self.dir)
        meta = store.create("mock", "m")
        sid = meta["id"]
        store.append_event(sid, "user_message", {"text": "Salut"})
        store.append_event(sid, "text_delta", {"text": "é"})
        events = store.events(sid)
        self.assertEqual([e["type"] for e in events], ["user_message", "text_delta"])
        self.assertEqual(events[1]["data"], {"text": "é"})
        store.update(sid, title="Premier titre", add_cost=0.1)
        store.update(sid, title="Autre", add_cost=0.2)
        got = store.get(sid)
        self.assertEqual(got["title"], "Premier titre")
        self.assertAlmostEqual(got["cost_eur"], 0.3)
        self.assertEqual([m["id"] for m in store.list()], [sid])
        self.assertIsNone(store.get("../x"))
        mode = stat.S_IMODE((self.dir / "sessions" / f"{sid}.json").stat().st_mode)
        self.assertEqual(mode & 0o077, 0)


class TestConfigAndEnv(TmpCase):
    def test_parse_llm_env(self):
        text = "# commentaire\n\nANTHROPIC_API_KEY=sk-x\nexport OPENROUTER_API_KEY='or-y'\nQ=\"a b\"\nmauvais ligne\n1BAD=z\n"
        self.assertEqual(C.parse_llm_env(text), {"ANTHROPIC_API_KEY": "sk-x", "OPENROUTER_API_KEY": "or-y", "Q": "a b"})

    def test_load_llm_env_ne_remplace_pas_l_existant_et_avertit(self):
        path = self.dir / "llm.env"
        path.write_text("A_KEY=nouveau\nB_KEY=b\n", encoding="utf-8")
        os.chmod(path, 0o644)
        environ = {"A_KEY": "déjà"}
        loaded, warnings = C.load_llm_env(path, environ)
        self.assertEqual(environ, {"A_KEY": "déjà", "B_KEY": "b"})
        self.assertEqual(loaded, ["B_KEY"])
        self.assertEqual(len(warnings), 1)
        self.assertNotIn("nouveau", warnings[0])
        os.chmod(path, 0o600)
        self.assertEqual(C.load_llm_env(path, {})[1], [])

    def test_load_llm_env_fichier_absent(self):
        self.assertEqual(C.load_llm_env(self.dir / "nope.env", {}), ([], []))

    def test_config_par_defaut_et_surcharge_utilisateur(self):
        ws = self.dir
        (ws / "config").mkdir()
        (ws / "config/workspace.toml").write_text('[chat]\nport = 9000\ndaily_budget_eur = 3.5\n', encoding="utf-8")
        (ws / "config/workspace.user.toml").write_text('[chat]\nport = 9100\nauth = "proxy"\n'
                                                       '[notifications]\nprovider = "ntfy"\nntfy_topic = "t"\n',
                                                       encoding="utf-8")
        cfg = C.load_chat_config(ws)
        self.assertEqual(cfg["port"], 9100)
        self.assertEqual(cfg["daily_budget_eur"], 3.5)
        self.assertEqual(cfg["auth"], "proxy")
        self.assertEqual(cfg["max_turns"], 30)                   # défaut du service
        notif = C.load_notifications(ws)
        self.assertEqual((notif["provider"], notif["ntfy_topic"], notif["ntfy_url"]), ("ntfy", "t", "https://ntfy.sh"))


class TestHttpGuards(unittest.TestCase):
    def cfg(self, **over):
        cfg = dict(C.CHAT_DEFAULTS)
        cfg.update(over)
        return cfg

    def test_host_par_defaut_et_public_url(self):
        allowed = C.host_allowlist(8766, self.cfg(public_url="https://Coach.Example.com"))
        self.assertTrue(C.host_ok("127.0.0.1:8766", allowed))
        self.assertTrue(C.host_ok("coach.example.com", allowed))
        self.assertTrue(C.host_ok("COACH.example.com:443", allowed))
        self.assertFalse(C.host_ok("evil.example", allowed))
        self.assertFalse(C.host_ok("", allowed))

    def test_host_boucle_locale_tout_port_en_mode_local_seulement(self):
        # Le tableau de bord (port 8765) relaie /api/chat avec son propre Host.
        local = C.host_allowlist(8766, self.cfg(auth="local"))
        self.assertTrue(C.host_ok("127.0.0.1:8765", local))
        self.assertTrue(C.host_ok("localhost:8765", local))
        self.assertFalse(C.host_ok("evil.example:8765", local))
        proxy = C.host_allowlist(8766, self.cfg(auth="proxy", public_url="https://coach.example.com"))
        self.assertFalse(C.host_ok("127.0.0.1:1", proxy))
        self.assertTrue(C.host_ok("127.0.0.1:8766", proxy))

    def test_allowed_hosts_prime_sur_public_url(self):
        allowed = C.host_allowlist(1, self.cfg(allowed_hosts=["a.example"], public_url="https://b.example"))
        self.assertTrue(C.host_ok("a.example", allowed))
        self.assertFalse(C.host_ok("b.example", allowed))

    def test_auth_locale(self):
        cfg = self.cfg()
        self.assertEqual(C.authenticate(cfg, "127.0.0.1", {})[0], "local")
        self.assertEqual(C.authenticate(cfg, "10.0.0.5", {})[1], 403)

    def test_auth_proxy(self):
        cfg = self.cfg(auth="proxy", trusted_proxies=["10.0.0.0/24"], allowed_users=["marco"])
        head = {"X-authentik-username": "marco"}
        self.assertEqual(C.authenticate(cfg, "10.0.0.7", head), ("marco", 0, ""))
        self.assertEqual(C.authenticate(cfg, "192.168.1.1", head)[1], 403)           # source non fiable
        self.assertEqual(C.authenticate(cfg, "10.0.0.7", {})[1], 401)                # identité absente
        self.assertEqual(C.authenticate(cfg, "10.0.0.7", {"X-authentik-username": "autre"})[1], 403)
        self.assertEqual(C.authenticate(cfg, "10.0.0.7", {}, exempt_identity=True)[1], 0)   # route à jeton
        self.assertEqual(C.authenticate(cfg, "192.168.1.1", {}, exempt_identity=True)[1], 403)
        self.assertEqual(C.authenticate(cfg, "127.0.0.1", {}, health_from_loopback=True)[1], 0)
        self.assertEqual(C.authenticate(cfg, "10.0.0.7", {}, health_from_loopback=True)[1], 401)

    def test_trusted_proxies_nom_d_hote(self):
        # Conteneur « traefik » sur un réseau Docker : son adresse change à chaque recréation,
        # le nom est résolu par le DNS (cache court).
        C._host_cache.clear()
        with mock.patch.object(C.socket, "getaddrinfo",
                               return_value=[(2, 1, 6, "", ("172.18.0.27", 0))]) as gai:
            self.assertTrue(C.ip_in("172.18.0.27", ["traefik"]))
            self.assertFalse(C.ip_in("172.18.0.5", ["traefik"]))
            self.assertEqual(gai.call_count, 1)                               # cache
        C._host_cache.clear()
        with mock.patch.object(C.socket, "getaddrinfo", side_effect=OSError("inconnu")):
            self.assertFalse(C.ip_in("172.18.0.27", ["traefik"]))             # nom introuvable : refus
        C._host_cache.clear()

    def test_auth_proxy_sans_liste_d_utilisateurs(self):
        cfg = self.cfg(auth="proxy", auth_header="Remote-User")
        self.assertEqual(C.authenticate(cfg, "127.0.0.1", {"Remote-User": "qui-que-ce-soit"})[0], "qui-que-ce-soit")

    def test_csrf(self):
        ok = {"X-ARC-Chat": "1", "Host": "h:1"}
        self.assertIsNone(C.check_csrf(ok))
        self.assertIsNone(C.check_csrf(dict(ok, Origin="http://h:1", **{"Sec-Fetch-Site": "same-origin"})))
        self.assertIsNotNone(C.check_csrf({"Host": "h:1"}))
        self.assertIsNotNone(C.check_csrf(dict(ok, **{"X-ARC-Chat": "0"})))
        self.assertIsNotNone(C.check_csrf(dict(ok, Origin="http://evil.example")))
        self.assertIsNotNone(C.check_csrf(dict(ok, Origin="null")))
        self.assertIsNotNone(C.check_csrf(dict(ok, **{"Sec-Fetch-Site": "cross-site"})))
        # route à jeton : seul l'en-tête compte
        self.assertIsNone(C.check_csrf(dict(ok, Origin="http://evil.example"), token_route=True))
        self.assertIsNotNone(C.check_csrf({"Host": "h:1"}, token_route=True))

    def test_limite_de_debit_par_utilisateur(self):
        clock = Clock(0)
        limiter = C.RateLimiter(2, clock=clock)
        self.assertTrue(limiter.allow("a"))
        self.assertTrue(limiter.allow("a"))
        self.assertFalse(limiter.allow("a"))
        self.assertTrue(limiter.allow("b"))
        clock.now += 61
        self.assertTrue(limiter.allow("a"))
        self.assertTrue(C.RateLimiter(0).allow("x"))

    def test_exposition(self):
        C.check_exposure(self.cfg())
        C.check_exposure(self.cfg(auth="proxy", listen="0.0.0.0"))
        with self.assertRaises(C.ConfigError):
            C.check_exposure(self.cfg(listen="0.0.0.0"))
        with self.assertRaises(C.ConfigError):
            C.check_exposure(self.cfg(auth="nimporte"))

    def test_actions_ntfy(self):
        tokens = {"allow": "id1.aaa", "deny": "id1.bbb"}
        actions = C.build_actions("https://coach.example.com/", "id1", tokens)
        self.assertIn("view, Ouvrir, https://coach.example.com/chat.html#approval=id1", actions)
        self.assertIn("http, Appliquer, https://coach.example.com/api/chat/approve/id1.aaa/allow, "
                      "method=POST, headers.X-ARC-Chat=1, clear=true", actions)
        self.assertIn("http, Refuser, https://coach.example.com/api/chat/approve/id1.bbb/deny", actions)
        self.assertNotIn("http,", C.build_actions("https://c.example", "id1", None))


if __name__ == "__main__":
    unittest.main()
