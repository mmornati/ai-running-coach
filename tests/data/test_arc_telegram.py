"""Palier D — `scripts/arc_telegram.py` (#174) : retours en un geste sans LLM + pont vers le chat.

Aucun réseau, aucun vrai jeton : l'API Telegram est un faux serveur local
(`tests/lib/telegram_stub.py`) ; le pont est branché sur un vrai `arc_chat`
(backend scripté `mock`) en boucle locale.
"""

from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import threading
import time
import unittest
from contextlib import redirect_stderr
from datetime import date
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))

import arc_chat as CHAT  # noqa: E402
import arc_index  # noqa: E402
import arc_telegram as T  # noqa: E402
from arc_chat_mock import MockBackend  # noqa: E402
from tests.lib.telegram_stub import FAKE_TOKEN, TelegramStub  # noqa: E402

DAY = "2026-10-05"            # un lundi
TODAY = date(2026, 10, 5)
CHAT_ID = 4242


def block(data: dict) -> str:
    return "```arc\n" + json.dumps(data, indent=2, ensure_ascii=False) + "\n```"


def wait_for(predicate, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.02)
    return None


def cb(data: str, chat_id=CHAT_ID, message_id=7, sender=None) -> dict:
    return {"callback_query": {"id": f"cb{message_id}{abs(hash(data)) % 1000}", "data": data,
                               "from": {"id": sender or chat_id},
                               "message": {"message_id": message_id, "chat": {"id": chat_id, "type": "private"}}}}


def msg(text: str, chat_id=CHAT_ID, chat_type="private", sender=None) -> dict:
    return {"message": {"message_id": 1, "text": text, "from": {"id": sender or chat_id},
                        "chat": {"id": chat_id, "type": chat_type}}}


class Case(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.ws = Path(self._tmp.name) / "ws"
        for sub in ("activities", "medical", "planning"):
            (self.ws / sub).mkdir(parents=True)
        self.stub = TelegramStub()
        self.stub.__enter__()
        self.addCleanup(lambda: self.stub.__exit__())
        self.reindexed = []
        quiet = redirect_stderr(io.StringIO())
        quiet.__enter__()
        self.addCleanup(lambda: quiet.__exit__(None, None, None))

    def activity(self, day=DAY, sport="trail", **extra):
        data = dict({"arc": 1, "kind": "activity", "date": day, "sport": sport, "duration_s": 3600}, **extra)
        path = self.ws / "activities" / f"{day}_{sport}.md"
        path.write_text(f"# Sortie\n\n{block(data)}\n\nTexte libre.\n", encoding="utf-8")
        return path

    def week(self, sessions=None):
        sessions = sessions if sessions is not None else [
            {"date": DAY, "sport": "trail", "title": "Sortie facile", "status": "planned"}]
        data = {"arc": 1, "kind": "week", "week_start": DAY, "location": "Lyon", "sessions": sessions}
        path = self.ws / "planning" / f"{DAY}_semaine.md"
        path.write_text(f"# Semaine\n\n{block(data)}\n", encoding="utf-8")
        return path

    def bot(self, **over):
        bridge = over.pop("bridge", None)
        cfg = dict(T.TELEGRAM_DEFAULTS, enabled=True, allowed_chat_ids=[str(CHAT_ID)], _all={})
        cfg.update(over)
        api = T.TelegramAPI(FAKE_TOKEN, base=self.stub.base)
        return T.Bot(self.ws, cfg, api, store=T.Store(self.ws), bridge=bridge, today=lambda: TODAY,
                     reindex_fn=lambda ws: self.reindexed.append(ws), min_interval_s=0.0, run_async=False)

    def validate(self, path):
        ok, errors, _ = arc_index.validate_file(path)
        self.assertTrue(ok, errors)


class TestCallbackParsing(unittest.TestCase):
    def test_valid_callbacks(self):
        self.assertEqual(T.parse_callback(f"rp:{DAY}:7"), {"kind": "rp", "date": DAY, "rpe": 7, "idx": None})
        self.assertEqual(T.parse_callback(f"rp:{DAY}:10:1")["idx"], 1)
        self.assertEqual(T.parse_callback(f"st:{DAY}:m")["code"], "m")
        self.assertEqual(T.parse_callback(f"pn:{DAY}")["kind"], "pn")
        self.assertEqual(T.parse_callback(f"ps:{DAY}:3")["score"], 3)
        self.assertEqual(T.parse_callback("ap:abc_DEF-123456:a")["decision"], "allow")

    def test_invalid_callbacks_are_rejected(self):
        for bad in ("", "x", f"rp:{DAY}:11", f"rp:{DAY}:0", f"rp:{DAY}:x", "rp:2026-13-99x:5", f"st:{DAY}:z",
                    f"pz:{DAY}:99", "ap:../etc:a", "ap:abc_DEF-123456:x", f"ps:{DAY}:0"):
            with self.subTest(bad=bad):
                self.assertIsNone(T.parse_callback(bad))

    def test_all_keyboard_payloads_fit_in_64_bytes(self):
        ws = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(ws, ignore_errors=True))
        (ws / "activities").mkdir()
        (ws / "planning").mkdir()
        (ws / "activities" / f"{DAY}_trail.md").write_text(block({"arc": 1}), encoding="utf-8")
        kb = T.feedback_keyboard(ws, DAY)
        for row in kb["inline_keyboard"]:
            for button in row:
                self.assertLessEqual(len(button["callback_data"].encode()), 64)
                self.assertIsNotNone(T.parse_callback(button["callback_data"]))

    def test_pain_command(self):
        self.assertEqual(T.parse_pain_command("genou gauche 3"), ("genou gauche", "3", ""))
        self.assertEqual(T.parse_pain_command("mollet 6/10 depuis km 12"), ("mollet", "6", "depuis km 12"))
        self.assertIsNone(T.parse_pain_command("3"))
        self.assertIsNone(T.parse_pain_command("genou"))


class TestRpe(Case):
    def test_rpe_callback_writes_activity_and_reindexes(self):
        path = self.activity()
        self.bot().handle_update(cb(f"rp:{DAY}:7"))
        _, data = T.read_arc_file(path)
        self.assertEqual(data["rpe"], 7)
        self.assertIsInstance(data["rpe"], int)
        self.assertEqual(data["duration_s"], 3600)
        self.validate(path)
        self.assertIn("Texte libre.", path.read_text(encoding="utf-8"))
        self.assertIn("[/log ", path.read_text(encoding="utf-8"))
        self.assertEqual(len(self.reindexed), 1)
        self.assertTrue(any("RPE 7/10" in t for t in self.stub.texts()))

    def test_same_callback_twice_writes_once(self):
        path = self.activity()
        bot = self.bot()
        bot.handle_update(cb(f"rp:{DAY}:7"))
        first = path.read_bytes()
        bot.handle_update(cb(f"rp:{DAY}:7"))
        self.assertEqual(path.read_bytes(), first)
        self.assertEqual(len(self.reindexed), 1)
        self.assertIn("déjà noté", self.stub.texts()[-1])

    def test_other_value_replaces(self):
        path = self.activity()
        bot = self.bot()
        bot.handle_update(cb(f"rp:{DAY}:7"))
        bot.handle_update(cb(f"rp:{DAY}:5"))
        self.assertEqual(T.read_arc_file(path)[1]["rpe"], 5)

    def test_no_activity_writes_nothing(self):
        self.bot().handle_update(cb(f"rp:{DAY}:7"))
        self.assertEqual(list((self.ws / "activities").iterdir()), [])
        self.assertIn("Aucune séance synchronisée", self.stub.texts()[-1])
        self.assertEqual(self.reindexed, [])

    def test_two_activities_ask_which(self):
        self.activity(sport="trail")
        self.activity(sport="strength")
        self.bot().handle_update(cb(f"rp:{DAY}:6"))
        markup = self.stub.sent()[-1]["reply_markup"]["inline_keyboard"]
        self.assertEqual(len(markup), 2)
        self.assertTrue(all(row[0]["callback_data"].startswith(f"rp:{DAY}:6:") for row in markup))

    def test_rpe_command(self):
        path = self.activity()
        self.bot().handle_update(msg("/rpe 8"))
        self.assertEqual(T.read_arc_file(path)[1]["rpe"], 8)


class TestStatus(Case):
    def test_done_missed_moved(self):
        path = self.week()
        bot = self.bot()
        bot.handle_update(cb(f"st:{DAY}:d"))
        self.assertEqual(T.read_arc_file(path)[1]["sessions"][0]["status"], "done")
        self.validate(path)
        first = path.read_bytes()
        bot.handle_update(cb(f"st:{DAY}:d"))
        self.assertEqual(path.read_bytes(), first, "idempotent")
        bot.handle_update(cb(f"st:{DAY}:m"))
        self.assertEqual(T.read_arc_file(path)[1]["sessions"][0]["status"], "moved")
        self.assertIn("calendrier Garmin n'est pas modifié", self.stub.texts()[-1])

    def test_no_planned_session(self):
        self.bot().handle_update(cb(f"st:{DAY}:d"))
        self.assertIn("Aucune séance prévue", self.stub.texts()[-1])

    def test_multi_week_file(self):
        data = {"arc": 1, "kind": "week", "weeks": [{"week_start": DAY, "location": "Lyon", "sessions": [
            {"date": DAY, "sport": "trail", "title": "A", "status": "planned"}]}]}
        path = self.ws / "planning" / "plan.md"
        path.write_text(f"# Plan\n\n{block(data)}\n", encoding="utf-8")
        self.bot().handle_update(cb(f"st:{DAY}:n"))
        self.assertEqual(T.read_arc_file(path)[1]["weeks"][0]["sessions"][0]["status"], "missed")


class TestPain(Case):
    def flow(self, bot, zone=0, score=3):
        bot.handle_update(cb(f"pn:{DAY}"))
        bot.handle_update(cb(f"pz:{DAY}:{zone}"))
        bot.handle_update(cb(f"ps:{DAY}:{score}"))

    def test_guided_flow_creates_health_file(self):
        bot = self.bot()
        self.flow(bot)
        path = self.ws / "medical" / f"{DAY}_health.md"
        _, data = T.read_arc_file(path)
        self.assertEqual(data["pain"], [{"location": "genou", "score": 3}])
        self.assertEqual(data["morning_check"], "full")
        self.validate(path)
        self.assertEqual(len(self.reindexed), 1)
        self.assertTrue(any("facultative" in t for t in self.stub.texts()))
        self.assertFalse(any("consulter" in t for t in self.stub.texts()))

    def test_note_is_appended_after_flow(self):
        bot = self.bot()
        self.flow(bot)
        bot.handle_update(msg("apparue au km 12"))
        path = self.ws / "medical" / f"{DAY}_health.md"
        self.assertIn("apparue au km 12", path.read_text(encoding="utf-8"))
        self.validate(path)
        bot.handle_update(msg("autre texte"))               # plus de parcours : pas une note
        self.assertNotIn("autre texte", path.read_text(encoding="utf-8"))

    def test_other_zone_asks_free_text(self):
        bot = self.bot()
        bot.handle_update(cb(f"pn:{DAY}"))
        bot.handle_update(cb(f"pz:{DAY}:{len(T.PAIN_ZONES) - 1}"))
        bot.handle_update(msg("mollet droit"))
        bot.handle_update(cb(f"ps:{DAY}:4"))
        data = T.read_arc_file(self.ws / "medical" / f"{DAY}_health.md")[1]
        self.assertEqual(data["pain"][0]["location"], "mollet droit")

    def test_same_pain_twice_is_not_duplicated(self):
        bot = self.bot()
        bot.handle_update(msg("/douleur genou gauche 3"))
        bot.handle_update(msg("/douleur genou gauche 3"))
        data = T.read_arc_file(self.ws / "medical" / f"{DAY}_health.md")[1]
        self.assertEqual(len(data["pain"]), 1)
        self.assertIn("déjà notée", self.stub.texts()[-1])
        bot.handle_update(msg("/douleur cheville 2"))
        self.assertEqual(len(T.read_arc_file(self.ws / "medical" / f"{DAY}_health.md")[1]["pain"]), 2)

    def test_existing_health_file_is_merged_not_replaced(self):
        path = self.ws / "medical" / f"{DAY}_health.md"
        path.write_text(f"# Santé\n\n{block({'arc': 1, 'kind': 'health', 'date': DAY, 'morning_check': 'minimal', 'readiness_score': 70})}\n",
                        encoding="utf-8")
        self.bot().handle_update(msg("/douleur dos 2"))
        data = T.read_arc_file(path)[1]
        self.assertEqual(data["readiness_score"], 70)
        self.assertEqual(data["morning_check"], "minimal")
        self.assertEqual(data["pain"], [{"location": "dos", "score": 2}])

    def test_pain_at_or_above_threshold_recommends_consultation(self):
        bot = self.bot()
        bot.handle_update(msg("/douleur genou 7"))
        self.assertIn("consulter un professionnel de santé", self.stub.texts()[-1])
        bot.handle_update(msg("/douleur hanche 6"))
        self.assertNotIn("consulter", self.stub.texts()[-1])

    def test_threshold_comes_from_workspace_config(self):
        (self.ws / "config").mkdir()
        (self.ws / "config/workspace.user.toml").write_text("[injury_risk]\npain_consult_threshold = 5\n", encoding="utf-8")
        self.bot().handle_update(msg("/douleur genou 5"))
        self.assertIn("consulter", self.stub.texts()[-1])

    def test_free_text_cannot_inject_markdown_or_a_second_arc_block(self):
        # Revue #174 : une note (ou une zone libre) multi-lignes ouvrait un second bloc ```arc sous
        # le bloc -> fichier hors contrat (ContractError) et index cassé.
        bot = self.bot()
        zone = "mollet\n```arc\n{}\n```"
        bot.handle_update(cb(f"pn:{DAY}"))
        bot.handle_update(cb(f"pz:{DAY}:{len(T.PAIN_ZONES) - 1}"))
        bot.handle_update(msg(zone))
        bot.handle_update(cb(f"ps:{DAY}:4"))
        bot.handle_update(msg('ok\n```arc\n{"arc": 1}\n```\n# Titre'))
        bot.handle_update(msg("/douleur genou 2 a ```arc"))
        path = self.ws / "medical" / f"{DAY}_health.md"
        text = path.read_text(encoding="utf-8")
        self.assertEqual(text.count("```"), 2, text)
        self.assertNotIn("\n# Titre", text)
        self.validate(path)
        self.assertEqual([p["location"] for p in T.read_arc_file(path)[1]["pain"]], [T.one_line(zone, 60), "genou"])
        self.assertNotIn("\n", T.one_line(zone))

    def test_same_pain_with_a_note_is_still_a_duplicate(self):
        bot = self.bot()
        bot.handle_update(msg("/douleur genou 3 apparue au km 12"))
        bot.handle_update(msg("/douleur genou 3 apparue au km 12"))
        path = self.ws / "medical" / f"{DAY}_health.md"
        self.assertEqual(len(T.read_arc_file(path)[1]["pain"]), 1)
        self.assertEqual(path.read_text(encoding="utf-8").count("apparue au km 12"), 1)

    def test_out_of_range_pain_writes_nothing(self):
        self.bot().handle_update(msg("/douleur genou 12"))
        self.assertFalse((self.ws / "medical" / f"{DAY}_health.md").exists())

    def test_expired_flow_is_refused(self):
        self.bot().handle_update(cb(f"ps:{DAY}:3"))
        self.assertFalse((self.ws / "medical" / f"{DAY}_health.md").exists())
        self.assertIn("plus actif", self.stub.texts()[-1])


class TestAllowlist(Case):
    def test_unknown_chat_gets_no_reply_and_no_write(self):
        path = self.activity()
        before = path.read_bytes()
        bot = self.bot()
        bot.handle_update(cb(f"rp:{DAY}:9", chat_id=999))
        bot.handle_update(msg("/douleur genou 9", chat_id=999))
        bot.handle_update(msg("bonjour", chat_id=999))
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(self.stub.calls, [])
        self.assertEqual(list((self.ws / "medical").glob("*.md")), [])

    def test_empty_allowlist_rejects_everyone(self):
        self.activity()
        bot = self.bot(allowed_chat_ids=[])
        bot.handle_update(cb(f"rp:{DAY}:9"))
        self.assertEqual(self.stub.calls, [])

    def test_group_requires_allowlisted_sender(self):
        self.activity()
        bot = self.bot(allowed_chat_ids=["-100", str(CHAT_ID)])
        bot.handle_update(msg("/rpe 4", chat_id=-100, chat_type="group", sender=555))
        self.assertEqual(self.stub.calls, [])
        bot.handle_update(msg("/rpe 4", chat_id=-100, chat_type="group", sender=CHAT_ID))
        self.assertTrue(self.stub.sent())

    def test_unknown_callback_does_not_crash(self):
        self.bot().handle_update(cb("zz:what"))
        self.assertEqual(self.stub.sent("answerCallbackQuery")[-1]["text"], "Bouton inconnu.")


class TestSecurity(Case):
    def test_api_base_requires_https_or_loopback(self):
        with mock.patch.dict(os.environ, {"ARC_TELEGRAM_API_BASE": "http://evil.example"}):
            with self.assertRaises(ValueError):
                T.api_base()
        with mock.patch.dict(os.environ, {"ARC_TELEGRAM_API_BASE": "http://127.0.0.1:9"}):
            self.assertEqual(T.api_base(), "http://127.0.0.1:9")

    def test_token_never_in_errors_or_logs(self):
        api = T.TelegramAPI(FAKE_TOKEN, base=self.stub.base)
        bad = T.TelegramAPI(FAKE_TOKEN[:-3] + "xyz", base=self.stub.base)
        with self.assertRaises(T.TelegramError) as ctx:
            bad.call("getMe")
        self.assertEqual(ctx.exception.code, 401)
        self.assertNotIn(FAKE_TOKEN, str(ctx.exception))
        buf = io.StringIO()
        with redirect_stderr(buf):
            T.log(f"échec {FAKE_TOKEN} sur /bot{FAKE_TOKEN}/getMe")
        self.assertNotIn(FAKE_TOKEN, buf.getvalue())
        self.assertNotIn("AAFake", buf.getvalue())
        self.assertEqual(api.call("getMe"), True)

    def test_network_errors_never_carry_the_url(self):
        import http.client
        api = T.TelegramAPI(FAKE_TOKEN, base=self.stub.base)
        for exc in (http.client.IncompleteRead(b"x"), OSError(f"échec sur {api._url}")):
            with mock.patch("urllib.request.urlopen", side_effect=exc):
                with self.assertRaises(T.TelegramError) as ctx:
                    api.call("getMe")
            self.assertNotIn(FAKE_TOKEN, str(ctx.exception))
            self.assertEqual(ctx.exception.code, 0)

    def test_reindex_child_never_inherits_the_token(self):
        with mock.patch.dict(os.environ, {T.TOKEN_VAR: FAKE_TOKEN}):
            with mock.patch("subprocess.run") as run:
                T.reindex(self.ws)
        self.assertNotIn(T.TOKEN_VAR, run.call_args.kwargs["env"])
        self.assertNotIn(FAKE_TOKEN, " ".join(run.call_args.args[0]))

    def test_other_update_types_are_ignored_even_from_an_allowed_chat(self):
        path = self.activity()
        before = path.read_bytes()
        bot = self.bot()
        edited = msg("/rpe 9")["message"]
        for update in ({"edited_message": edited}, {"my_chat_member": {"chat": {"id": CHAT_ID}}},
                       {"channel_post": edited},
                       {"callback_query": {"id": "x", "data": f"rp:{DAY}:9", "inline_message_id": "abc",
                                           "from": {"id": CHAT_ID}}}):
            bot.handle_update(update)
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(self.stub.calls, [])

    def test_read_token_from_file_and_errors(self):
        path = Path(self._tmp.name) / "telegram.env"
        path.write_text(f"# commentaire\n{T.TOKEN_VAR}={FAKE_TOKEN}\n", encoding="utf-8")
        path.chmod(0o600)
        cfg = {"token_file": str(path)}
        self.assertEqual(T.read_token(cfg, environ={}), (FAKE_TOKEN, None))
        self.assertIsNone(T.token_file_warning(cfg))
        path.chmod(0o644)
        self.assertIn("chmod 600", T.token_file_warning(cfg))
        path.write_text(f"{T.TOKEN_VAR}=pas-un-jeton\n", encoding="utf-8")
        token, err = T.read_token(cfg, environ={})
        self.assertIsNone(token)
        self.assertNotIn("pas-un-jeton", err)
        token, err = T.read_token({"token_file": str(path) + ".absent"}, environ={})
        self.assertIsNone(token)


class TestPolling(Case):
    def test_poll_processes_updates_and_persists_offset(self):
        path = self.activity()
        bot = self.bot()
        uid = self.stub.queue_update(cb(f"rp:{DAY}:6"))
        stop = threading.Event()
        thread = threading.Thread(target=T.poll_forever, args=(bot, bot.api, stop, 1), daemon=True)
        thread.start()
        self.assertTrue(wait_for(lambda: T.read_arc_file(path)[1].get("rpe") == 6))
        self.assertTrue(wait_for(lambda: bot.store.offset == uid + 1))
        stop.set()
        thread.join(5)
        self.assertEqual(json.loads((self.ws / ".arc/telegram/state.json").read_text())["offset"], uid + 1)
        self.assertEqual(oct((self.ws / ".arc/telegram/state.json").stat().st_mode & 0o777), "0o600")
        # un redémarrage repart de l'offset : l'update confirmée n'est pas rejouée
        self.assertEqual(T.Store(self.ws).offset, uid + 1)

    def test_errors_back_off_instead_of_crashing(self):
        bot = self.bot()
        waits = []
        stop = threading.Event()

        def wait(delay):
            waits.append(delay)
            stop.set()
            return True

        self.stub.fail_next["getUpdates"] = (409, "Conflict", None)
        T.poll_forever(bot, bot.api, stop, 1, wait=wait)
        self.assertEqual(waits[0], 30.0)

    def test_unauthorized_token_waits_long(self):
        stop = threading.Event()
        waits = []
        self.stub.fail_next["getUpdates"] = (401, "Unauthorized", None)

        def wait(delay):
            waits.append(delay)
            stop.set()
            return True

        bot = self.bot()
        T.poll_forever(bot, bot.api, stop, 1, wait=wait)
        self.assertEqual(waits, [300.0])

    def test_rate_limit_retry_after_is_honoured_for_sends(self):
        bot = self.bot()
        self.stub.fail_next["sendMessage"] = (429, "Too Many Requests", {"retry_after": 0})
        with mock.patch.object(T.time, "sleep"):
            bot.send(CHAT_ID, "salut")
        self.assertEqual(len(self.stub.sent()), 2)

    def test_long_messages_are_split_under_the_limit(self):
        self.bot().send(CHAT_ID, "x" * 9000)
        texts = self.stub.texts()
        self.assertEqual(len(texts), 3)
        self.assertTrue(all(len(t) <= T.MAX_MESSAGE_CHARS for t in texts))


class TestSendSummary(Case):
    def run_cli(self, text, *extra, env=None):
        environ = {"TELEGRAM_BOT_TOKEN": FAKE_TOKEN, "ARC_TELEGRAM_API_BASE": self.stub.base}
        environ.update(env or {})
        with mock.patch.dict(os.environ, environ), mock.patch.object(sys, "stdin", io.StringIO(text)):
            return T.main(["send-summary", "--workspace", str(self.ws), *extra])

    def config(self, body):
        (self.ws / "config").mkdir(exist_ok=True)
        (self.ws / "config/workspace.user.toml").write_text(body, encoding="utf-8")

    def test_disabled_sends_nothing(self):
        self.assertEqual(self.run_cli("résumé"), 0)
        self.assertEqual(self.stub.calls, [])

    def test_enabled_sends_summary_with_buttons(self):
        self.activity()
        self.week()
        self.config(f'[telegram]\nenabled = true\nallowed_chat_ids = ["{CHAT_ID}"]\n')
        with mock.patch.object(T, "date") as fake_date:
            fake_date.today.return_value = TODAY
            self.assertEqual(self.run_cli("Sync OK : 1 séance", "--title", "Sync Garmin", "--priority", "2"), 0)
        sent = self.stub.sent()[0]
        self.assertEqual(sent["chat_id"], str(CHAT_ID))
        self.assertIn("Sync OK : 1 séance", sent["text"])
        self.assertTrue(sent["disable_notification"])
        data = [b["callback_data"] for row in sent["reply_markup"]["inline_keyboard"] for b in row]
        self.assertIn(f"st:{DAY}:d", data)
        self.assertIn(f"rp:{DAY}:10", data)
        self.assertIn(f"pn:{DAY}", data)

    def test_send_summary_flag_off(self):
        self.config(f'[telegram]\nenabled = true\nsend_summary = false\nallowed_chat_ids = ["{CHAT_ID}"]\n')
        self.assertEqual(self.run_cli("résumé"), 0)
        self.assertEqual(self.stub.calls, [])

    def test_missing_token_or_allowlist_fails_softly(self):
        self.config('[telegram]\nenabled = true\nallowed_chat_ids = []\n')
        self.assertEqual(self.run_cli("résumé"), 1)
        self.config(f'[telegram]\nenabled = true\nallowed_chat_ids = ["{CHAT_ID}"]\ntoken_file = "{self._tmp.name}/nope"\n')
        with mock.patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": ""}):
            with mock.patch.object(sys, "stdin", io.StringIO("x")):
                self.assertEqual(T.main(["send-summary", "--workspace", str(self.ws)]), 1)
        self.assertEqual(self.stub.calls, [])


class TestBridge(Case):
    """Niveau 2 : pont vers un vrai `arc_chat` (backend mock), jamais un second moteur."""

    def start_chat(self, **over):
        original, CHAT.log = CHAT.log, lambda message: None
        self.addCleanup(lambda: setattr(CHAT, "log", original))
        cfg = dict(CHAT.CHAT_DEFAULTS)
        cfg.update({"enabled": True, "backend": "mock", "approval_wait_s": 1, "ntfy_delay_s": 0,
                    "rate_limit_per_min": 0, "mock_slow_s": 5})
        cfg.update(over)
        chat_ws = Path(self._tmp.name) / "chat-ws"
        chat_ws.mkdir()
        httpd, _ = CHAT.make_server(chat_ws, cfg, MockBackend(chat_ws, cfg), {"provider": "none"}, port=0)
        threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True).start()

        def stop():
            httpd.shutdown()
            httpd.server_close()

        self.addCleanup(stop)
        return httpd.server_address[1], cfg

    def bridged_bot(self, port, chat_enabled=True, chat_bridge=True, **chat_over):
        chat = {"enabled": chat_enabled, "port": port, "listen": "127.0.0.1", "auth": "local"}
        chat.update(chat_over)
        bridge = T.ChatBridge({"chat": chat})
        return self.bot(chat_bridge=chat_bridge, bridge=bridge, _all={"chat": chat})

    def test_bridge_off_explains_and_never_calls_chat(self):
        port, _ = self.start_chat()
        bot = self.bridged_bot(port, chat_bridge=False)
        bot.handle_update(msg("Analyse ma semaine"))
        self.assertEqual(self.stub.texts()[-1], T.BRIDGE_OFF_TEXT)
        self.assertEqual(bot.store.data["sessions"], {})

    def test_chat_disabled_explains(self):
        bot = self.bridged_bot(1, chat_enabled=False)
        bot.handle_update(msg("Analyse ma semaine"))
        self.assertIn("chat est désactivé", self.stub.texts()[-1])

    def test_chat_unreachable_explains(self):
        bot = self.bridged_bot(1)
        bot.handle_update(msg("Analyse ma semaine"))
        self.assertIn("injoignable", self.stub.texts()[-1])

    def test_non_local_auth_refused(self):
        port, _ = self.start_chat()
        bot = self.bridged_bot(port, auth="proxy")
        bot.handle_update(msg("salut"))
        self.assertIn("auth", self.stub.texts()[-1])

    def test_free_text_is_relayed_to_the_chat_service(self):
        port, _ = self.start_chat()
        bot = self.bridged_bot(port)
        bot.handle_update(msg("Rien de spécial, dis-moi bonjour"))
        text = self.stub.texts()[-1]
        self.assertIn("Rien à modifier pour l'instant.", text)
        self.assertIn(str(CHAT_ID), bot.store.data["sessions"])
        sid = bot.store.data["sessions"][str(CHAT_ID)]
        bot.handle_update(msg("et encore"))
        self.assertEqual(bot.store.data["sessions"][str(CHAT_ID)], sid, "même conversation")
        bot.handle_update(msg("/nouveau"))
        self.assertEqual(bot.store.data["sessions"], {})

    def test_approval_surfaces_as_buttons_and_is_decided_through_the_chat(self):
        port, _ = self.start_chat(approval_wait_s=30)
        bot = self.bridged_bot(port)
        bot.run_async = True
        bot.handle_update(msg("planifie ma séance de jeudi"))
        self.assertTrue(wait_for(lambda: any("reply_markup" in p for p in self.stub.sent())))
        markup = [p for p in self.stub.sent() if "reply_markup" in p][0]["reply_markup"]["inline_keyboard"][0]
        allow = markup[0]["callback_data"]
        self.assertTrue(allow.startswith("ap:") and allow.endswith(":a"))
        # une autre conversation ne peut pas trancher
        bot.store.data["approvals"][allow.split(":")[1]] = "999"
        bot.handle_update(cb(allow))
        self.assertEqual(self.stub.sent("answerCallbackQuery")[-1]["text"], "Proposition inconnue.")
        bot.store.data["approvals"][allow.split(":")[1]] = str(CHAT_ID)
        bot.handle_update(cb(allow))
        self.assertEqual(self.stub.sent("answerCallbackQuery")[-1]["text"], "Appliqué")
        self.assertTrue(wait_for(lambda: any("C'est fait" in t for t in self.stub.texts())))
        for thread in bot.threads:
            thread.join(5)
        bot.handle_update(cb(allow))                            # même appui deux fois : usage unique
        self.assertEqual(self.stub.sent("answerCallbackQuery")[-1]["text"], "Proposition inconnue.")
        self.assertNotIn(allow.split(":")[1], bot.store.data["approvals"])

    def test_deny_through_button(self):
        port, _ = self.start_chat(approval_wait_s=30)
        bot = self.bridged_bot(port)
        bot.run_async = True
        bot.handle_update(msg("planifie ma séance"))
        self.assertTrue(wait_for(lambda: any("reply_markup" in p for p in self.stub.sent())))
        deny = [p for p in self.stub.sent() if "reply_markup" in p][0]["reply_markup"]["inline_keyboard"][0][1]["callback_data"]
        bot.handle_update(cb(deny))
        self.assertTrue(wait_for(lambda: any("je ne modifie rien" in t for t in self.stub.texts())))
        for thread in bot.threads:
            thread.join(5)


if __name__ == "__main__":
    unittest.main()
