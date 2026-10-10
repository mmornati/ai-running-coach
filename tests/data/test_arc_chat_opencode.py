"""Palier D — `scripts/arc_chat_opencode.py` : adaptateur du serveur OpenCode.

Aucun vrai OpenCode, aucun réseau externe : un faux serveur HTTP (port 0, seulement
les endpoints utilisés par l'adaptateur) rejoue des évènements SSE réels capturés sur
OpenCode 1.18.32 (`tests/data/fixtures/chat/opencode_*.json`) et la création du
processus enfant est remplacée.
"""

from __future__ import annotations

import base64
import json
import os
import queue
import stat
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from unittest import mock

from tests.lib.local_http import ThreadingHTTPServer

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))
import arc_chat_opencode as O  # noqa: E402
from arc_chat_backend import SYSTEM_ADDENDUM, BackendError, TurnContext  # noqa: E402

FIXTURES = REPO / "tests" / "data" / "fixtures" / "chat"
SID = "ses_fake1"
CHILD = "ses_child1"


def fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class FakeOpenCode:
    """Faux `opencode serve` : health, session, prompt_async, event (SSE), permission, abort."""

    def __init__(self, ws: Path):
        self.ws = ws
        self.password = None
        self.requests: list = []
        self.scenario: dict = {}
        self.session_exists = True
        self.child_info: dict = {}      # id de session fille -> réponse de GET /session/{id}
        self.child_messages: dict = {}  # id de session fille -> réponse de GET /session/{id}/message/…
        self.subscribers: list = []
        self.stopping = threading.Event()
        self.lock = threading.Lock()
        outer = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.0"

            def log_message(self, *args):
                pass

            def _authorized(self) -> bool:
                if outer.password is None:
                    return True
                want = "Basic " + base64.b64encode(f"opencode:{outer.password}".encode()).decode()
                if self.headers.get("Authorization") == want:
                    return True
                self.send_response(401)
                self.end_headers()
                return False

            def _json(self, code, obj):
                raw = json.dumps(obj).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def _body(self):
                n = int(self.headers.get("Content-Length") or 0)
                return json.loads(self.rfile.read(n)) if n else None

            def do_GET(self):
                if not self._authorized():
                    return
                if self.path == "/global/health":
                    return self._json(200, {"healthy": True, "version": O.OPENCODE_TESTED_VERSION})
                for child_id, info in outer.child_info.items():
                    if self.path == f"/session/{child_id}":
                        return self._json(200, info)
                for child_id, msg in outer.child_messages.items():
                    if self.path.startswith(f"/session/{child_id}/message/"):
                        outer.requests.append(("GET", self.path, None))
                        return self._json(200, msg)
                if self.path == f"/session/{SID}":
                    return self._json(200 if outer.session_exists else 404,
                                      {"id": SID} if outer.session_exists else {"name": "NotFoundError"})
                if self.path.startswith(f"/session/{SID}/message/"):
                    outer.requests.append(("GET", self.path, None))
                    return self._json(200, outer.scenario.get("message_lookup", {"info": {}, "parts": []}))
                if self.path == "/event":
                    q: queue.Queue = queue.Queue()
                    with outer.lock:
                        outer.subscribers.append(q)
                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream")
                    self.end_headers()
                    q.put({"id": "evt_0", "type": "server.connected", "properties": {}})
                    try:
                        while True:
                            ev = q.get()
                            if ev is None:
                                return
                            self.wfile.write(f"data: {json.dumps(ev)}\n\n".encode())
                            self.wfile.flush()
                    except (BrokenPipeError, ConnectionResetError, OSError):
                        return
                return self._json(404, {})

            def do_POST(self):
                if not self._authorized():
                    return
                body = self._body()
                outer.requests.append(("POST", self.path, body))
                if self.path == "/session":
                    return self._json(200, {"id": SID})
                if self.path == f"/session/{SID}/prompt_async":
                    self.send_response(204)
                    self.end_headers()
                    threading.Thread(target=outer.on_prompt, daemon=True).start()
                    return
                if self.path.startswith("/permission/") and self.path.endswith("/reply"):
                    self._json(200, True)
                    outer.on_reply(body)
                    return
                if self.path.endswith("/abort") and self.path.startswith("/session/"):
                    self._json(200, True)
                    if self.path == f"/session/{SID}/abort":
                        outer.publish([{"id": "evt_a", "type": "session.idle", "properties": {"sessionID": SID}}])
                    return
                return self._json(404, {})

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.httpd.daemon_threads = True
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    # -- rejeu ---------------------------------------------------------

    def _render(self, events, feedback=""):
        raw = json.dumps(events)
        raw = (raw.replace("$SESSION", SID).replace("$WSREL", str(self.ws).lstrip("/"))
               .replace("$WS", str(self.ws)).replace("$FEEDBACK", feedback))
        return json.loads(raw)

    def publish(self, events):
        with self.lock:
            subs = list(self.subscribers)
        for ev in events:
            for q in subs:
                q.put(ev)

    def on_prompt(self):
        sc = self.scenario
        if sc.get("heartbeat"):
            def beat():
                while not self.stopping.is_set():
                    self.publish([{"id": "hb", "type": "server.heartbeat", "properties": {}}])
                    self.stopping.wait(0.05)
            threading.Thread(target=beat, daemon=True).start()
        if sc.get("ticks"):
            def tick():
                while not self.stopping.is_set():
                    self.publish([{"id": "tk", "type": "session.status",
                                   "properties": {"sessionID": SID, "status": {"type": "busy"}}}])
                    self.stopping.wait(0.05)
            threading.Thread(target=tick, daemon=True).start()
        if "events" in sc:
            self.publish(self._render(sc["events"]))
        else:
            self.publish(self._render(sc["before_permission"]))

    def on_reply(self, body):
        kind = "once" if body.get("reply") == "once" else "reject"
        after = self.scenario.get("after", {}).get(kind, [])
        self.publish(self._render(after, body.get("message", "")))

    def close(self):
        self.stopping.set()
        with self.lock:
            for q in self.subscribers:
                q.put(None)
        self.httpd.shutdown()
        self.httpd.server_close()


class FakeProc:
    def __init__(self):
        self.alive = True
        self.terminated = False

    def poll(self):
        return None if self.alive else 1

    def terminate(self):
        self.terminated = True
        self.alive = False

    def kill(self):
        self.alive = False

    def wait(self, timeout=None):
        return 0


class Harness:
    def __init__(self, ws, decisions=None, approval="allow", config=None, state=None, approval_hook=None):
        self.events: list = []
        self.decided: list = []
        self.approvals: list = []
        decisions = decisions or {}

        def decide(tool, tinput):
            self.decided.append((tool, tinput))
            return decisions.get(tool, "allow")

        def request_approval(tool, tinput, summary, diff):
            self.approvals.append((tool, tinput, summary, diff))
            if approval_hook:
                return approval_hook()
            return approval

        cfg = {"usd_eur_rate": 0.5, "max_turns": 30}
        cfg.update(config or {})
        self.ctx = TurnContext(session_id="s1", workspace=ws, config=cfg,
                               emit=lambda t, p: self.events.append((t, p)), decide=decide,
                               request_approval=request_approval,
                               backend_state=state if state is not None else {})

    def of(self, kind):
        return [p for t, p in self.events if t == kind]

    def types(self):
        return [t for t, _ in self.events]


class OpenCodeCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.ws = Path(self._tmp.name).resolve()
        (self.ws / "planning").mkdir()
        self.fake = FakeOpenCode(self.ws)
        self.spawned: list = []
        self._env = dict(os.environ)
        os.environ["OPENROUTER_API_KEY"] = "sk-or-secret-test-value"
        self.addCleanup(self._cleanup)
        self.backend = O.OpenCodeBackend(self.ws, {"model": "openrouter/deepseek/deepseek-v4.1-flash"})

        def fake_spawn(cmd, env, cwd, log_path):
            self.spawned.append({"cmd": cmd, "env": dict(env), "cwd": cwd})
            self.fake.password = env["OPENCODE_SERVER_PASSWORD"]
            return FakeProc()

        patches = [mock.patch.object(O.OpenCodeBackend, "_spawn", staticmethod(fake_spawn)),
                   mock.patch.object(O.OpenCodeBackend, "_pick_port", staticmethod(lambda: self.fake.port)),
                   mock.patch.object(O.OpenCodeBackend, "_binary", lambda self_: "/fake/bin/opencode")]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def _cleanup(self):
        self.backend.shutdown()
        self.fake.close()
        os.environ.clear()
        os.environ.update(self._env)
        self._tmp.cleanup()

    def run_turn(self, scenario, harness=None, text="salut"):
        self.fake.scenario = scenario
        h = harness or Harness(self.ws)
        self.backend.run_turn(h.ctx, text)
        return h

    def replies(self):
        return [b for m, p, b in self.fake.requests if p.startswith("/permission/")]


class TestMapping(unittest.TestCase):
    def test_canonical_table(self):
        servers = {"garmin", "intervals", "leanproxy", "my_srv"}
        cases = [
            ("read", {"filePath": "a.md"}, "fs.read", {"path": "a.md"}),
            ("write", {"filePath": "planning/x.md", "content": "c"}, "fs.write", {"path": "planning/x.md", "content": "c"}),
            ("edit", {"filePath": "p", "oldString": "a", "newString": "b"}, "fs.write", None),
            ("patch", {"patchText": "*** Begin Patch\n*** Update File: planning/y.md\n"}, "fs.write", None),
            ("glob", {"pattern": "*.md"}, "fs.list", {"path": ".", "glob": "*.md"}),
            ("glob", {"pattern": "**/*.token", "path": "config"}, "fs.list", {"path": "config", "glob": "**/*.token"}),
            ("grep", {"pattern": "x", "path": "activities"}, "fs.list", {"path": "activities", "pattern": "x"}),
            ("grep", {"pattern": "tok", "include": ".env*"}, "fs.list",
             {"path": ".", "pattern": "tok", "glob": ".env*"}),
            ("list", {"path": "."}, "fs.list", {"path": "."}),
            ("bash", {"command": "ls", "description": "d"}, "shell", {"command": "ls"}),
            ("webfetch", {"url": "https://wttr.in"}, "web.fetch", {"url": "https://wttr.in"}),
            ("websearch", {"query": "q"}, "web.search", {"query": "q"}),
            ("task", {"subagent_type": "coach", "prompt": "p"}, "task", {"agent": "coach"}),
            ("skill", {"name": "log"}, "skill", {"name": "log"}),
            ("garmin_schedule_workouts", {"w": 1}, "mcp:garmin.schedule_workouts", {"w": 1}),
            ("intervals_get_events", {}, "mcp:intervals.get_events", {}),
            ("my_srv_do_it", {}, "mcp:my_srv.do_it", {}),
            ("mystery", {}, "other:mystery", None),
            ("todowrite", {}, "other:todowrite", None),
        ]
        for name, inp, tool, cinput in cases:
            got_tool, got = O.canonical_tool(name, inp, servers)
            self.assertEqual(got_tool, tool, name)
            if cinput is not None:
                self.assertEqual(got, cinput, name)
        self.assertEqual(O.canonical_tool("patch", {"patchText": "*** Update File: planning/y.md"}, ())[1]["path"],
                         "planning/y.md")

    def test_leanproxy_gateway(self):
        self.assertEqual(
            O.canonical_tool("leanproxy_leanproxy_invoke_tool",
                             {"server": "garmin", "tool": "schedule_week", "arguments": {"w": 1}}, {"leanproxy"}),
            ("mcp:garmin.schedule_week", {"w": 1}))

    def test_gateway_only_maps_arguments(self):
        tool, inp = O.canonical_tool("leanproxy_leanproxy_invoke_tool",
                                     {"server": "garmin", "tool": "schedule_week", "args": {"w": 1}}, {"leanproxy"})
        self.assertTrue(tool.startswith("other:"), tool)
        self.assertEqual(inp["args"], {"w": 1})

    def test_leanproxy_direct_exposed_tools(self):
        self.assertEqual(O.canonical_tool("leanproxy_garmin__get_rhr_day", {"d": 1}, {"leanproxy"}),
                         ("mcp:garmin.get_rhr_day", {"d": 1}))
        self.assertEqual(O.canonical_tool("leanproxy_garmin__schedule_week", {}, {"leanproxy"})[0],
                         "mcp:garmin.schedule_week")

    def test_split_model(self):
        self.assertEqual(O.split_model("openrouter/deepseek/deepseek-v4.1-flash"), ("openrouter", "deepseek/deepseek-v4.1-flash"))
        with self.assertRaises(BackendError):
            O.split_model("nomodel")

    def test_convert_mcp(self):
        out = O.convert_mcp_servers({"mcpServers": {
            "garmin": {"command": "garmin-mcp", "args": ["stdio"], "env": {"GARMIN_ENABLED_TOOLS": "a,b"}},
            "lp": {"command": "leanproxy-mcp", "args": []}, "bad": {}}})
        self.assertEqual(out["garmin"], {"type": "local", "command": ["garmin-mcp", "stdio"], "enabled": True,
                                         "environment": {"GARMIN_ENABLED_TOOLS": "a,b"}})
        self.assertEqual(out["lp"]["command"], ["leanproxy-mcp"])
        self.assertNotIn("bad", out)


class TestConfigGeneration(OpenCodeCase):
    def test_config_without_secret(self):
        (self.ws / ".mcp.json").write_text(json.dumps({"mcpServers": {"garmin": {
            "command": "garmin-mcp", "args": ["stdio"]}}}), encoding="utf-8")
        path = self.backend.write_config()
        self.assertEqual(path, self.ws / ".arc" / "chat" / "opencode" / "opencode.json")
        text = path.read_text(encoding="utf-8")
        cfg = json.loads(text)
        self.assertNotIn("sk-or-secret-test-value", text)
        self.assertEqual(cfg["provider"]["openrouter"]["options"]["apiKey"], "{env:OPENROUTER_API_KEY}")
        self.assertEqual(cfg["model"], "openrouter/deepseek/deepseek-v4.1-flash")
        self.assertIn("deepseek/deepseek-v4.1-flash", cfg["provider"]["openrouter"]["models"])
        self.assertEqual(cfg["permission"]["*"], "ask")
        self.assertEqual(cfg["permission"]["question"], "deny")
        self.assertEqual(cfg["mcp"]["garmin"]["command"], ["garmin-mcp", "stdio"])
        self.assertFalse(cfg["autoupdate"])

    def test_config_file_mode_600(self):
        path = self.backend.write_config()
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        path.chmod(0o644)   # fichier préexistant trop ouvert : réécrit en 600
        self.backend.write_config()
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)

    def test_custom_base_url(self):
        b = O.OpenCodeBackend(self.ws, {"model": "mistral/mistral-large", "base_url": "https://api.mistral.ai/v1",
                                        "api_key_env": "MISTRAL_API_KEY"})
        os.environ["MISTRAL_API_KEY"] = "mk"
        cfg = json.loads(b.write_config().read_text(encoding="utf-8"))
        prov = cfg["provider"]["mistral"]
        self.assertEqual(prov["npm"], "@ai-sdk/openai-compatible")
        self.assertEqual(prov["options"]["baseURL"], "https://api.mistral.ai/v1")
        self.assertEqual(prov["options"]["apiKey"], "{env:MISTRAL_API_KEY}")
        self.assertIn("mistral-large", prov["models"])

    def test_loopback_provider_needs_no_key(self):
        b = O.OpenCodeBackend(self.ws, {"model": "ollama/llama3", "base_url": "http://localhost:11434/v1"})
        cfg = json.loads(b.write_config().read_text(encoding="utf-8"))
        self.assertNotIn("apiKey", cfg["provider"]["ollama"]["options"])

    def test_spawn_environment_and_no_key_on_disk(self):
        self.run_turn(fixture("opencode_text_only.json"))
        spawn = self.spawned[0]
        self.assertEqual(spawn["cmd"][:2], ["/fake/bin/opencode", "serve"])
        self.assertIn("127.0.0.1", spawn["cmd"])
        self.assertEqual(spawn["cwd"], str(self.ws))
        env = spawn["env"]
        self.assertEqual(env["OPENCODE_CONFIG"], str(self.ws / ".arc/chat/opencode/opencode.json"))
        self.assertEqual(env["OPENROUTER_API_KEY"], "sk-or-secret-test-value")
        self.assertTrue(len(env["OPENCODE_SERVER_PASSWORD"]) >= 24)
        self.assertTrue(env["XDG_CONFIG_HOME"].startswith(str(self.ws / ".arc/chat/opencode/xdg")))
        for path in (self.ws / ".arc").rglob("*"):
            if path.is_file():
                self.assertNotIn(b"sk-or-secret-test-value", path.read_bytes(), str(path))
                self.assertNotIn(env["OPENCODE_SERVER_PASSWORD"].encode(), path.read_bytes(), str(path))


class TestTurns(OpenCodeCase):
    def test_text_only(self):
        h = self.run_turn(fixture("opencode_text_only.json"))
        self.assertEqual("".join(p["text"] for p in h.of("text_delta")), "Termine.")
        self.assertEqual(h.of("done"), [{"reason": "end_turn"}])
        usage = h.of("usage")[0]
        self.assertEqual((usage["input_tokens"], usage["output_tokens"]), (150, 5))
        self.assertAlmostEqual(usage["cost_eur"], 0.00016 * 0.5, places=6)
        self.assertEqual(h.ctx.backend_state["opencode_session_id"], SID)
        prompt = next(b for m, p, b in self.fake.requests if p.endswith("/prompt_async"))
        self.assertEqual(prompt["model"], {"providerID": "openrouter", "modelID": "deepseek/deepseek-v4.1-flash"})
        self.assertTrue(prompt["system"].startswith(SYSTEM_ADDENDUM))
        self.assertIn("en français", prompt["system"])      # langue explicite (commande seule)
        self.assertEqual(prompt["parts"], [{"type": "text", "text": "salut"}])

    def test_text_not_duplicated_by_delta_then_update(self):
        h = self.run_turn(fixture("opencode_edit_permission.json") | {})  # tour outil + réponse
        del h  # (couvert plus bas ; ici on vérifie seulement l'absence d'exception)

    def test_session_reused_and_recreated(self):
        state = {"opencode_session_id": SID}
        h = self.run_turn(fixture("opencode_text_only.json"), Harness(self.ws, state=state))
        self.assertFalse([1 for m, p, b in self.fake.requests if (m, p) == ("POST", "/session")])
        self.assertEqual(h.ctx.backend_state["opencode_session_id"], SID)
        self.fake.session_exists = False
        self.fake.requests.clear()
        state2 = {"opencode_session_id": "ses_gone"}
        self.run_turn(fixture("opencode_text_only.json"), Harness(self.ws, state=state2))
        self.assertEqual(state2["opencode_session_id"], SID)

    def test_edit_allowed_by_policy(self):
        h = self.run_turn(fixture("opencode_edit_permission.json"))
        self.assertEqual(self.replies(), [{"reply": "once"}])
        self.assertEqual(h.approvals, [])
        self.assertEqual(h.decided, [("fs.write", {"path": f"{self.ws}/planning/x.md", "content": "hello\n"})])
        start = h.of("tool_start")[0]
        self.assertEqual((start["name"], start["id"]), ("fs.write", "call_1"))
        self.assertIn("planning/x.md", start["summary"])
        self.assertEqual(h.of("tool_end"), [{"id": "call_1", "ok": True, "summary": "Terminé"}])
        self.assertEqual(h.of("file_written"), [{"path": "planning/x.md"}])
        texts = "".join(p["text"] for p in h.of("text_delta"))
        self.assertEqual(texts, "Je vais Termine.")  # deltas puis mise à jour finale : aucun doublon
        self.assertEqual(h.of("done"), [{"reason": "end_turn"}])
        usage = h.of("usage")[0]
        self.assertEqual((usage["input_tokens"], usage["output_tokens"]), (250, 25))
        self.assertAlmostEqual(usage["cost_eur"], (0.00014 + 0.00016) * 0.5, places=6)

    def test_edit_ask_allow_uses_diff(self):
        h = self.run_turn(fixture("opencode_edit_permission.json"),
                          Harness(self.ws, {"fs.write": "ask"}, "allow"))
        self.assertEqual(self.replies(), [{"reply": "once"}])
        self.assertEqual(len(h.approvals), 1)
        tool, tinput, summary, diff = h.approvals[0]
        self.assertEqual(tool, "fs.write")
        self.assertIn({"op": "+", "text": "hello"}, diff)
        self.assertEqual(h.of("file_written"), [{"path": "planning/x.md"}])

    def test_edit_ask_deny_and_policy_deny(self):
        for decisions, approval in (({"fs.write": "ask"}, "deny"), ({"fs.write": "deny"}, "allow")):
            self.fake.requests.clear()
            h = self.run_turn(fixture("opencode_edit_permission.json"), Harness(self.ws, decisions, approval))
            reply = self.replies()[0]
            self.assertEqual(reply["reply"], "reject")
            self.assertIn("Refusé", reply["message"])
            end = h.of("tool_end")[0]
            self.assertEqual((end["ok"], end["summary"]), (False, "Refusé"))
            self.assertEqual(h.of("file_written"), [])
            self.assertEqual(h.of("done"), [{"reason": "end_turn"}])
            if "ask" not in decisions.values():
                self.assertEqual(h.approvals, [])

    def test_mcp_ask_allow(self):
        (self.ws / ".mcp.json").write_text(json.dumps({"mcpServers": {"garmin": {"command": "garmin-mcp"}}}))
        h = self.run_turn(fixture("opencode_mcp_permission.json"),
                          Harness(self.ws, {"mcp:garmin.schedule_workouts": "ask"}, "allow"))
        self.assertEqual(self.replies(), [{"reply": "once"}])
        tool, tinput, summary, diff = h.approvals[0]
        self.assertEqual((tool, tinput), ("mcp:garmin.schedule_workouts", {"workouts": []}))
        self.assertIn("Garmin", summary)
        self.assertEqual(h.of("tool_start")[0]["name"], "mcp:garmin.schedule_workouts")
        self.assertTrue(h.of("tool_end")[0]["ok"])
        self.assertEqual(h.of("file_written"), [])

    def test_mcp_pending(self):
        (self.ws / ".mcp.json").write_text(json.dumps({"mcpServers": {"garmin": {"command": "garmin-mcp"}}}))
        h = self.run_turn(fixture("opencode_mcp_permission.json"),
                          Harness(self.ws, {"mcp:garmin.schedule_workouts": "ask"}, "pending"))
        reply = self.replies()[0]
        self.assertEqual(reply, {"reply": "reject", "message": "La proposition attend la confirmation de l'athlète."})
        self.assertEqual(h.of("tool_end")[0]["summary"], "En attente de confirmation")
        self.assertEqual(h.of("done"), [{"reason": "pending_approval"}])

    def test_question_permission_is_rejected_without_policy(self):
        scenario = {"before_permission": [
            {"id": "e1", "type": "session.status", "properties": {"sessionID": "$SESSION", "status": {"type": "busy"}}},
            {"id": "e2", "type": "permission.asked", "properties": {
                "id": "per_q", "sessionID": "$SESSION", "permission": "question", "patterns": ["*"],
                "metadata": {}, "always": [], "tool": {"messageID": "msg_1", "callID": "c9"}}}],
            "after": {"reject": [{"id": "e3", "type": "session.idle", "properties": {"sessionID": "$SESSION"}}]}}
        h = self.run_turn(scenario)
        self.assertEqual(h.decided, [])
        self.assertEqual(self.replies()[0]["reply"], "reject")

    def test_input_fetched_when_running_event_missing(self):
        (self.ws / ".mcp.json").write_text(json.dumps({"mcpServers": {"garmin": {"command": "garmin-mcp"}}}))
        fx = fixture("opencode_mcp_permission.json")
        # retire l'évènement « running » : l'entrée doit être relue via GET /session/{id}/message/{id}
        fx["before_permission"] = [e for e in fx["before_permission"] if not (
            e["type"] == "message.part.updated" and e["properties"]["part"].get("state", {}).get("status") == "running")]
        fx["message_lookup"] = {"info": {}, "parts": [{"type": "tool", "callID": "call_1",
                                                       "tool": "garmin_schedule_workouts",
                                                       "state": {"status": "pending", "input": {"workouts": [7]}}}]}
        h = self.run_turn(fx, Harness(self.ws, {"mcp:garmin.schedule_workouts": "ask"}, "allow"))
        self.assertEqual(h.approvals[0][1], {"workouts": [7]})
        self.assertTrue([1 for m, p, b in self.fake.requests if m == "GET" and "/message/" in p])

    def test_cancel_aborts_session(self):
        release = threading.Event()

        def hook():
            release.wait(5)
            return "deny"

        h = Harness(self.ws, {"fs.write": "ask"}, approval_hook=hook)
        self.fake.scenario = fixture("opencode_edit_permission.json")

        def cancel():
            h.ctx.cancelled.set()
            threading.Timer(0.4, release.set).start()
        threading.Timer(0.5, cancel).start()
        self.backend.run_turn(h.ctx, "go")
        self.assertTrue([1 for m, p, b in self.fake.requests if p == f"/session/{SID}/abort"])
        self.assertEqual(h.of("done"), [{"reason": "interrupted"}])

    def test_session_error_translated(self):
        for error, needle in (({"name": "ProviderAuthError", "data": {"providerID": "openrouter", "message": "bad"}}, "401"),
                              ({"name": "APIError", "data": {"message": "Insufficient credits", "statusCode": 402}}, "402"),
                              ({"name": "UnknownError", "data": {"message": "boom"}}, "boom")):
            scenario = {"events": [
                {"id": "e1", "type": "session.status", "properties": {"sessionID": "$SESSION", "status": {"type": "busy"}}},
                {"id": "e2", "type": "session.error", "properties": {"sessionID": "$SESSION", "error": error}}]}
            with self.assertRaises(BackendError) as cm:
                self.run_turn(scenario)
            self.assertIn(needle, str(cm.exception))

    def test_max_turns_aborts(self):
        h = Harness(self.ws, config={"max_turns": 1})
        self.run_turn(fixture("opencode_edit_permission.json"), h)
        self.assertEqual(h.of("done"), [{"reason": "max_turns"}])
        self.assertTrue([1 for m, p, b in self.fake.requests if p.endswith("/abort")])


class TestSubAgents(OpenCodeCase):
    """Le tool `task` ouvre des sessions FILLES : leurs permissions/coûts appartiennent au tour."""

    def test_child_permission_answered_through_policy(self):
        h = self.run_turn(fixture("opencode_task_child_permission.json"))
        # la permission de la session fille est traitée (sinon le tour resterait bloqué)
        self.assertEqual(self.replies(), [{"reply": "once"}])
        self.assertEqual(h.decided, [("fs.read", {"path": f"{self.ws}/planning/x.md"})])
        self.assertEqual(h.of("done"), [{"reason": "end_turn"}])
        # texte interne du sous-agent masqué ; texte du tour visible
        self.assertEqual("".join(p["text"] for p in h.of("text_delta")), "Fini.")
        # outils du sous-agent visibles dans la trace, préfixés et avec un id propre à la session
        starts = {p["id"]: p for p in h.of("tool_start")}
        self.assertIn("call_task", starts)
        child = starts[f"{CHILD}:call_c1"]
        self.assertTrue(child["summary"].startswith("Sous-agent · "))
        self.assertEqual(child["name"], "fs.read")
        self.assertIn({"id": f"{CHILD}:call_c1", "ok": True, "summary": "Terminé"}, h.of("tool_end"))
        # coûts et jetons de la session fille comptés
        usage = h.of("usage")[0]
        self.assertEqual((usage["input_tokens"], usage["output_tokens"], usage["cache_read_tokens"]), (500, 25, 50))
        self.assertAlmostEqual(usage["cost_eur"], (0.0004 + 0.0001) * 0.5, places=6)

    def test_child_permission_rejected_by_policy(self):
        h = self.run_turn(fixture("opencode_task_child_permission.json"),
                          Harness(self.ws, {"fs.read": "deny"}))
        reply = self.replies()[0]
        self.assertEqual(reply["reply"], "reject")
        self.assertIn("Refusé", reply["message"])
        self.assertIn({"id": f"{CHILD}:call_c1", "ok": False, "summary": "Refusé"}, h.of("tool_end"))
        self.assertEqual(h.of("done"), [{"reason": "end_turn"}])

    def test_child_found_from_task_metadata_without_session_created(self):
        fx = fixture("opencode_task_child_permission.json")
        fx["before_permission"] = [e for e in fx["before_permission"] if e["type"] != "session.created"]
        h = self.run_turn(fx)   # `metadata.sessionId` de la partie task suffit
        self.assertEqual(self.replies(), [{"reply": "once"}])
        self.assertEqual(h.of("done"), [{"reason": "end_turn"}])

    def test_unknown_session_adopted_through_parent_lookup(self):
        fx = fixture("opencode_task_child_permission.json")
        fx["before_permission"] = [e for e in fx["before_permission"] if e["type"] != "session.created"
                                   and not (e["type"] == "message.part.updated"
                                            and e["properties"]["part"].get("tool") == "task")]
        self.fake.child_info[CHILD] = {"id": CHILD, "parentID": SID}
        # les évènements de la fille précèdent l'adoption : l'entrée est relue côté serveur
        self.fake.child_messages[CHILD] = {"info": {}, "parts": [{
            "type": "tool", "callID": "call_c1", "tool": "read",
            "state": {"status": "running", "input": {"filePath": f"{self.ws}/planning/x.md"}}}]}
        h = self.run_turn(fx)
        self.assertEqual(self.replies(), [{"reply": "once"}])
        self.assertEqual(h.of("done"), [{"reason": "end_turn"}])

    def test_foreign_session_permission_is_ignored(self):
        scenario = {"events": [
            {"id": "e1", "type": "session.status", "properties": {"sessionID": "$SESSION", "status": {"type": "busy"}}},
            {"id": "e2", "type": "permission.asked", "properties": {
                "id": "per_x", "sessionID": "ses_stranger", "permission": "read", "patterns": ["*"],
                "metadata": {}, "tool": {"messageID": "m", "callID": "c"}}},
            {"id": "e3", "type": "session.idle", "properties": {"sessionID": "$SESSION"}}]}
        h = self.run_turn(scenario)
        self.assertEqual(self.replies(), [])
        self.assertEqual(h.decided, [])

    def test_child_cost_counts_towards_turn_budget(self):
        # 0.0004 USD * 0.5 = 0.0002 EUR de la session fille > plafond du tour
        h = self.run_turn(fixture("opencode_task_child_permission.json"),
                          Harness(self.ws, config={"turn_budget_eur": 0.0001}))
        self.assertEqual(h.of("done"), [{"reason": "budget"}])
        self.assertIn("budget", "".join(p["text"] for p in h.of("text_delta")).lower())
        aborts = [p for m, p, b in self.fake.requests if p.endswith("/abort")]
        self.assertIn(f"/session/{SID}/abort", aborts)
        self.assertIn(f"/session/{CHILD}/abort", aborts)


class TestBudgetAndTimeouts(OpenCodeCase):
    def test_turn_budget_aborts_session(self):
        # 1re étape : 0.00014 USD * 0.5 = 0.00007 EUR > 0.00005
        h = self.run_turn(fixture("opencode_edit_permission.json"),
                          Harness(self.ws, config={"turn_budget_eur": 0.00005}))
        self.assertEqual(h.of("done"), [{"reason": "budget"}])
        self.assertTrue([1 for m, p, b in self.fake.requests if p == f"/session/{SID}/abort"])
        self.assertIn("budget", "".join(p["text"] for p in h.of("text_delta")).lower())
        self.assertGreater(h.of("usage")[0]["cost_eur"], 0)

    def test_no_cap_without_turn_budget(self):
        h = self.run_turn(fixture("opencode_edit_permission.json"))
        self.assertEqual(h.of("done"), [{"reason": "end_turn"}])

    def test_partial_usage_emitted_when_turn_fails(self):
        scenario = {"events": [
            {"id": "e1", "type": "session.status", "properties": {"sessionID": "$SESSION", "status": {"type": "busy"}}},
            {"id": "e2", "type": "message.part.updated", "properties": {"sessionID": "$SESSION", "part": {
                "id": "st1", "type": "step-finish", "messageID": "m1", "sessionID": "$SESSION", "cost": 0.002,
                "tokens": {"input": 30, "output": 7, "cache": {"read": 0, "write": 0}}}}},
            {"id": "e3", "type": "session.error", "properties": {"sessionID": "$SESSION", "error": {
                "name": "UnknownError", "data": {"message": "boom"}}}}]}
        h = Harness(self.ws)
        with self.assertRaises(BackendError):
            self.run_turn(scenario, h)
        usage = h.of("usage")
        self.assertEqual(len(usage), 1)
        self.assertEqual((usage[0]["input_tokens"], usage[0]["output_tokens"]), (30, 7))
        self.assertAlmostEqual(usage[0]["cost_eur"], 0.001, places=6)

    def test_heartbeats_do_not_reset_idle_timer(self):
        scenario = {"heartbeat": True, "events": [
            {"id": "e1", "type": "session.status", "properties": {"sessionID": "$SESSION", "status": {"type": "busy"}}}]}
        with mock.patch.object(O, "EVENT_IDLE_TIMEOUT_S", 0.6):
            with self.assertRaises(BackendError) as cm:
                self.run_turn(scenario)
        self.assertIn("ne répond plus", str(cm.exception))

    def test_turn_timeout_even_with_activity(self):
        scenario = {"ticks": True, "events": []}
        h = Harness(self.ws, config={"turn_timeout_s": 0.6})
        with self.assertRaises(BackendError) as cm:
            self.run_turn(scenario, h)
        self.assertIn("durée maximale", str(cm.exception))
        self.assertTrue([1 for m, p, b in self.fake.requests if p == f"/session/{SID}/abort"])

    def test_approval_wait_does_not_trip_idle_timer(self):
        def hook():
            threading.Event().wait(1.2)
            return "allow"
        h = Harness(self.ws, {"fs.write": "ask"}, approval_hook=hook)
        with mock.patch.object(O, "EVENT_IDLE_TIMEOUT_S", 0.5):
            self.run_turn(fixture("opencode_edit_permission.json"), h)
        self.assertEqual(h.of("done"), [{"reason": "end_turn"}])
        self.assertEqual(self.replies(), [{"reply": "once"}])


class TestAbortSignal(OpenCodeCase):
    def test_s5_abort_pose_un_signal_local_qui_fait_refuser_les_permissions(self):
        h = Harness(self.ws)
        turn = O._Turn(h.ctx)
        turn.root = SID
        with mock.patch.object(self.backend, "_request"):
            self.backend._abort(SID, turn)
        self.assertTrue(turn.abort_event.is_set())
        self.assertFalse(h.ctx.cancelled.is_set())        # l'annulation de l'athlète reste distincte
        self.fake.scenario = {"events": []}
        self.backend._ensure_server()
        self.backend._answer_permission(SID, turn, {
            "id": "per_late", "permission": "edit", "tool": {"messageID": "m", "callID": "c"}})
        self.assertEqual(h.decided, [])                    # jamais soumis à la politique
        self.assertEqual(self.replies()[0]["reply"], "reject")


class TestUnresolvedPermission(OpenCodeCase):
    def _scenario(self):
        return {"before_permission": [
            {"id": "e1", "type": "session.status", "properties": {"sessionID": "$SESSION", "status": {"type": "busy"}}},
            {"id": "e2", "type": "permission.asked", "properties": {
                "id": "per_u", "sessionID": "$SESSION", "permission": "garmin_schedule_workouts",
                "patterns": ["*"], "metadata": {}, "always": [], "tool": {"messageID": "msg_9", "callID": "cX"}}}],
            "after": {"reject": [{"id": "e3", "type": "session.idle", "properties": {"sessionID": "$SESSION"}}]}}

    def test_rejected_when_tool_part_cannot_be_found(self):
        h = self.run_turn(self._scenario())
        self.assertEqual(h.decided, [])   # jamais soumis à la politique avec `{}`
        self.assertEqual(h.approvals, [])
        reply = self.replies()[0]
        self.assertEqual(reply["reply"], "reject")
        self.assertIn("introuvable", reply["message"])

    def test_zero_argument_mcp_tool_with_known_input_is_not_rejected(self):
        (self.ws / ".mcp.json").write_text(json.dumps({"mcpServers": {"garmin": {"command": "garmin-mcp"}}}))
        sc = self._scenario()
        sc["before_permission"].insert(1, {"id": "e1b", "type": "message.part.updated", "properties": {
            "sessionID": "$SESSION", "part": {"type": "tool", "tool": "garmin_get_rhr_day", "callID": "cX",
                                              "id": "p1", "messageID": "msg_9", "sessionID": "$SESSION",
                                              "state": {"status": "running", "input": {}}}}})
        sc["after"] = {"once": sc["after"]["reject"]}
        h = self.run_turn(sc)
        self.assertEqual(h.decided, [("mcp:garmin.get_rhr_day", {})])
        self.assertEqual(self.replies(), [{"reply": "once"}])


class TestSupervision(OpenCodeCase):
    def test_server_started_lazily_reused_and_restarted(self):
        self.assertEqual(self.spawned, [])
        self.run_turn(fixture("opencode_text_only.json"))
        self.run_turn(fixture("opencode_text_only.json"))
        self.assertEqual(len(self.spawned), 1)
        self.backend._proc.alive = False  # le processus meurt
        self.run_turn(fixture("opencode_text_only.json"))
        self.assertEqual(len(self.spawned), 2)

    def test_shutdown_terminates_child(self):
        self.run_turn(fixture("opencode_text_only.json"))
        proc = self.backend._proc
        self.backend.shutdown()
        self.assertTrue(proc.terminated)
        self.assertIsNone(self.backend._proc)

    def test_wrong_password_is_unreachable(self):
        self.run_turn(fixture("opencode_text_only.json"))
        self.fake.password = "autre"
        with self.assertRaises(BackendError):
            self.backend._request("GET", "/global/health")

    def test_missing_key(self):
        os.environ.pop("OPENROUTER_API_KEY")
        with self.assertRaises(BackendError) as cm:
            self.run_turn(fixture("opencode_text_only.json"))
        self.assertIn("OPENROUTER_API_KEY", str(cm.exception))
        self.assertEqual(self.spawned, [])


class TestCheck(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.ws = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self._env = dict(os.environ)
        self.addCleanup(lambda: (os.environ.clear(), os.environ.update(self._env)))

    def test_binary_absent(self):
        with mock.patch("shutil.which", return_value=None):
            ok, msg = O.OpenCodeBackend(self.ws, {}).check()
        self.assertFalse(ok)
        self.assertIn("opencode", msg)
        self.assertIn("install", msg)

    def test_version_and_key(self):
        script = self.ws / "opencode"
        script.write_text(f"#!/bin/sh\necho {O.OPENCODE_TESTED_VERSION}\n")
        script.chmod(script.stat().st_mode | stat.S_IXUSR)
        backend = O.OpenCodeBackend(self.ws, {"opencode_bin": str(script)})
        os.environ.pop("OPENROUTER_API_KEY", None)
        ok, msg = backend.check()
        self.assertFalse(ok)
        self.assertIn("OPENROUTER_API_KEY", msg)
        os.environ["OPENROUTER_API_KEY"] = "k"
        ok, msg = backend.check()
        self.assertTrue(ok)
        self.assertEqual(msg, f"opencode {O.OPENCODE_TESTED_VERSION}")
        script.write_text("#!/bin/sh\necho 9.9.9\n")
        ok, msg = backend.check()
        self.assertTrue(ok)
        self.assertIn("testé avec", msg)


if __name__ == "__main__":
    unittest.main()
