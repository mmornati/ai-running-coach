"""Palier D — `scripts/arc_chat_claude.py` : adaptateur Claude Agent SDK du chat coach.

Ni réseau ni vrai SDK : un faux module `claude_agent_sdk` (mêmes noms de classes que
le paquet 0.2.161 — voir la docstring du module testé) est injecté dans `sys.modules`
et rejoue une séquence de messages en appelant, comme le CLI, le hook `PreToolUse`
puis le callback `can_use_tool` avant d'« exécuter » l'outil.
"""

from __future__ import annotations

import sys
import tempfile
import threading
import types
import unittest
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))
import arc_chat_claude as C  # noqa: E402
from arc_chat_backend import BackendError, TurnContext  # noqa: E402


# ---------------------------------------------------------------------------
# Faux SDK
# ---------------------------------------------------------------------------

def make_fake_sdk(script: list, record: dict) -> types.ModuleType:
    mod = types.ModuleType("claude_agent_sdk")
    mod.__version__ = "0.2.165"

    @dataclass
    class TextBlock:
        text: str

    @dataclass
    class ToolUseBlock:
        id: str
        name: str
        input: dict

    @dataclass
    class ToolResultBlock:
        tool_use_id: str
        content: Any = None
        is_error: Optional[bool] = None

    @dataclass
    class AssistantMessage:
        content: list
        model: str = "fake"
        parent_tool_use_id: Optional[str] = None
        error: Optional[str] = None
        usage: Optional[dict] = None
        message_id: Optional[str] = None
        session_id: Optional[str] = None

    @dataclass
    class UserMessage:
        content: Any
        parent_tool_use_id: Optional[str] = None

    @dataclass
    class StreamEvent:
        uuid: str
        session_id: str
        event: dict
        parent_tool_use_id: Optional[str] = None

    @dataclass
    class ResultMessage:
        subtype: str = "success"
        is_error: bool = False
        session_id: str = "sdk-1"
        total_cost_usd: Optional[float] = None
        usage: Optional[dict] = None
        result: Optional[str] = None

    @dataclass
    class ClaudeAgentOptions:
        cwd: Any = None
        setting_sources: Any = None
        model: Any = None
        system_prompt: Any = None
        can_use_tool: Any = None
        hooks: Any = None
        include_partial_messages: bool = False
        permission_mode: Any = None
        disallowed_tools: list = field(default_factory=list)
        env: dict = field(default_factory=dict)
        max_turns: Any = None
        max_budget_usd: Any = None
        resume: Any = None

    @dataclass
    class HookMatcher:
        matcher: Optional[str] = None
        hooks: list = field(default_factory=list)
        timeout: Optional[float] = None

    @dataclass
    class PermissionResultAllow:
        behavior: str = "allow"
        updated_input: Any = None

    @dataclass
    class PermissionResultDeny:
        behavior: str = "deny"
        message: str = ""
        interrupt: bool = False

    @dataclass
    class ToolPermissionContext:
        tool_use_id: Optional[str] = None

    class CLINotFoundError(Exception):
        pass

    class ClaudeSDKClient:
        def __init__(self, options=None):
            self.options = options
            record["options"] = options
            record["interrupted"] = False

        async def connect(self):
            record["connected"] = True

        async def disconnect(self):
            record["disconnected"] = True

        async def query(self, prompt, session_id="default"):
            record["prompt"] = prompt

        async def interrupt(self):
            record["interrupted"] = True

        async def receive_response(self):
            import asyncio
            hook = self.options.hooks["PreToolUse"][0].hooks[0]
            for step in script:
                if step[0] == "msg":
                    yield step[1]
                elif step[0] == "raise":
                    raise step[1]
                elif step[0] == "wait_cancel":
                    for _ in range(100):
                        if record["interrupted"]:
                            break
                        await asyncio.sleep(0.05)
                elif step[0] == "tool":
                    _, tid, name, tinput = step
                    yield AssistantMessage([ToolUseBlock(tid, name, tinput)])
                    out = await hook({"hook_event_name": "PreToolUse", "tool_name": name,
                                      "tool_input": tinput, "tool_use_id": tid}, tid, None)
                    decision = out["hookSpecificOutput"]["permissionDecision"]
                    executed = decision == "allow"
                    if executed:  # le CLI peut aussi retomber sur can_use_tool
                        res = await self.options.can_use_tool(name, tinput, ToolPermissionContext(tid))
                        executed = res.behavior == "allow"
                    record.setdefault("executed", []).append((name, executed))
                    yield UserMessage([ToolResultBlock(tid, "ok" if executed else "refusé",
                                                       is_error=not executed)])

    for cls in (TextBlock, ToolUseBlock, ToolResultBlock, AssistantMessage, UserMessage, StreamEvent,
                ResultMessage, ClaudeAgentOptions, HookMatcher, PermissionResultAllow,
                PermissionResultDeny, ClaudeSDKClient, CLINotFoundError):
        setattr(mod, cls.__name__, cls)
    mod._cls = types.SimpleNamespace(TextBlock=TextBlock, ToolUseBlock=ToolUseBlock,
                                     AssistantMessage=AssistantMessage, StreamEvent=StreamEvent,
                                     ResultMessage=ResultMessage)
    return mod


MB = make_fake_sdk([], {})._cls  # fabrique de messages (les noms de classes suffisent)


def delta(sdk, text, parent=None):
    return ("msg", MB.StreamEvent("u", "sdk-1", {"type": "content_block_delta",
                                                       "delta": {"type": "text_delta", "text": text}},
                                        parent))


class Harness:
    """Contexte de tour avec des appelables factices et un journal des évènements."""

    def __init__(self, workspace: Path, decisions=None, approval="allow", state=None):
        self.events: list = []
        self.decided: list = []
        self.approvals: list = []
        decisions = decisions or {}

        def decide(tool, tinput):
            self.decided.append((tool, tinput))
            return decisions.get(tool, "allow")

        def request_approval(tool, tinput, summary, diff):
            self.approvals.append((tool, tinput, summary, diff))
            return approval

        self.ctx = TurnContext(
            session_id="s1", workspace=workspace, config={}, emit=lambda t, p: self.events.append((t, p)),
            decide=decide, request_approval=request_approval, backend_state=state if state is not None else {})

    def types(self):
        return [t for t, _ in self.events]

    def of(self, kind):
        return [p for t, p in self.events if t == kind]


class ClaudeBackendCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.ws = Path(self._tmp.name).resolve()
        (self.ws / "planning").mkdir()
        self._saved = sys.modules.get("claude_agent_sdk")
        self._env = dict(**{k: v for k, v in __import__("os").environ.items()})
        import os
        os.environ["ANTHROPIC_API_KEY"] = "sk-test-key"
        self.addCleanup(self._restore)

    def _restore(self):
        import os
        self._tmp.cleanup()
        if self._saved is None:
            sys.modules.pop("claude_agent_sdk", None)
        else:
            sys.modules["claude_agent_sdk"] = self._saved
        os.environ.clear()
        os.environ.update(self._env)

    def backend(self, script, config=None, record=None):
        record = record if record is not None else {}
        sdk = make_fake_sdk(script, record)
        sys.modules["claude_agent_sdk"] = sdk
        cfg = {"model": "claude-sonnet-5-5", "max_turns": 7, "usd_eur_rate": 0.9}
        cfg.update(config or {})
        return C.ClaudeBackend(self.ws, cfg), sdk, record


class TestCanonicalNames(unittest.TestCase):
    def test_table(self):
        cases = [
            ("Read", {"file_path": "a.md"}, "fs.read", {"path": "a.md"}),
            ("Write", {"file_path": "planning/x.md", "content": "c"}, "fs.write", None),
            ("Edit", {"file_path": "planning/x.md", "old_string": "a", "new_string": "b"}, "fs.write", None),
            ("MultiEdit", {"file_path": "p"}, "fs.write", None),
            ("NotebookEdit", {"notebook_path": "n.ipynb"}, "fs.write", None),
            ("Glob", {"pattern": "*.md"}, "fs.list", {"path": ".", "glob": "*.md"}),
            ("Glob", {"pattern": "**/*.token", "path": "config"}, "fs.list", {"path": "config", "glob": "**/*.token"}),
            ("Grep", {"pattern": "x", "path": "activities"}, "fs.list", {"path": "activities", "pattern": "x"}),
            ("Grep", {"pattern": "tok", "glob": ".env*"}, "fs.list", {"path": ".", "pattern": "tok", "glob": ".env*"}),
            ("LS", {"path": "."}, "fs.list", {"path": "."}),
            ("Bash", {"command": "ls"}, "shell", {"command": "ls"}),
            ("WebFetch", {"url": "https://wttr.in"}, "web.fetch", {"url": "https://wttr.in"}),
            ("WebSearch", {"query": "q"}, "web.search", {"query": "q"}),
            ("Task", {"subagent_type": "coach"}, "task", {"agent": "coach"}),
            ("Agent", {"subagent_type": "medical"}, "task", {"agent": "medical"}),
            ("Skill", {"skill": "log"}, "skill", {"name": "log"}),
            ("TodoWrite", {}, "other:TodoWrite", None),
        ]
        for name, inp, expected, cinput in cases:
            tool, got = C.canonical_tool(name, inp)
            self.assertEqual(tool, expected, name)
            if cinput is not None:
                self.assertEqual(got, cinput, name)
        self.assertEqual(C.canonical_tool("Write", {"file_path": "planning/x.md", "content": "c"})[1],
                         {"path": "planning/x.md", "content": "c"})

    def test_mcp_and_leanproxy(self):
        self.assertEqual(C.canonical_tool("mcp__garmin__schedule_workouts", {"a": 1}),
                         ("mcp:garmin.schedule_workouts", {"a": 1}))
        self.assertEqual(C.canonical_tool("mcp__Intervals__get_events", {})[0], "mcp:intervals.get_events")
        self.assertEqual(
            C.canonical_tool("mcp__leanproxy__leanproxy_invoke_tool",
                             {"server": "garmin", "tool": "schedule_week", "arguments": {"w": 1}}),
            ("mcp:garmin.schedule_week", {"w": 1}))
        self.assertEqual(
            C.canonical_tool("mcp__leanproxy__invoke_tool", {"server": "Garmin", "tool": "get_rhr_day"}),
            ("mcp:garmin.get_rhr_day", {}))
        self.assertEqual(C.canonical_tool("mcp__leanproxy__list_tools", {})[0], "mcp:leanproxy.list_tools")

    def test_gateway_only_maps_arguments(self):
        # `args` n'est PAS `arguments` : on ne devine pas -> other: (refusé par la politique)
        tool, inp = C.canonical_tool("mcp__leanproxy__invoke_tool",
                                     {"server": "garmin", "tool": "schedule_week", "args": {"w": 1}})
        self.assertTrue(tool.startswith("other:"), tool)
        self.assertEqual(inp["args"], {"w": 1})
        tool, inp = C.canonical_tool("mcp__leanproxy__invoke_tool",
                                     {"server": "garmin", "tool": "schedule_week",
                                      "arguments": {"w": 2}, "args": {"w": 1}})
        self.assertEqual((tool, inp), ("mcp:garmin.schedule_week", {"w": 2}))

    def test_leanproxy_direct_exposed_tools(self):
        self.assertEqual(C.canonical_tool("mcp__leanproxy__garmin__get_rhr_day", {"d": 1}),
                         ("mcp:garmin.get_rhr_day", {"d": 1}))
        self.assertEqual(C.canonical_tool("mcp__leanproxy__garmin__schedule_workouts", {})[0],
                         "mcp:garmin.schedule_workouts")
        self.assertEqual(C.canonical_tool("mcp__leanproxy__Intervals_icu__add_or_update_event_76a553387d", {})[0],
                         "mcp:intervals.add_or_update_event")


class TestRunTurn(ClaudeBackendCase):
    def test_text_usage_resume_and_options(self):
        script = [delta(None, "Bon"), delta(None, "jour"),
                  ("msg", MB.AssistantMessage([MB.TextBlock("Bonjour")])),
                  ("msg", MB.ResultMessage(session_id="sdk-42", total_cost_usd=0.10,
                                           usage={"input_tokens": 12, "output_tokens": 3,
                                                  "cache_read_input_tokens": 100}))]
        rec: dict = {}
        backend, sdk, rec = self.backend(script, record=rec)
        h = Harness(self.ws)
        backend.run_turn(h.ctx, "salut")
        self.assertEqual(h.types(), ["text_delta", "text_delta", "usage", "done"])
        self.assertEqual("".join(p["text"] for p in h.of("text_delta")), "Bonjour")  # pas de doublon
        usage = h.of("usage")[0]
        self.assertEqual((usage["input_tokens"], usage["output_tokens"], usage["cache_read_tokens"]),
                         (12, 3, 100))
        self.assertAlmostEqual(usage["cost_eur"], 0.09, places=4)  # 0.10 USD * 0.9
        self.assertEqual(h.of("done")[0], {"reason": "end_turn"})
        self.assertEqual(h.ctx.backend_state["sdk_session_id"], "sdk-42")
        opts = rec["options"]
        self.assertEqual(opts.cwd, str(self.ws))
        self.assertEqual(opts.setting_sources, ["project"])
        self.assertEqual(opts.model, "claude-sonnet-5-5")
        self.assertEqual(opts.max_turns, 7)
        self.assertTrue(opts.include_partial_messages)
        self.assertIsNone(opts.resume)
        self.assertEqual(opts.system_prompt["preset"], "claude_code")
        self.assertIn("approbation explicite", opts.system_prompt["append"])
        self.assertEqual(opts.env["ANTHROPIC_API_KEY"], "sk-test-key")
        self.assertEqual(opts.env["CLAUDE_CODE_OAUTH_TOKEN"], "")
        self.assertEqual(rec["prompt"], "salut")
        # tour suivant : reprise de la session SDK
        h2 = Harness(self.ws, state=h.ctx.backend_state)
        backend.run_turn(h2.ctx, "suite")
        self.assertEqual(rec["options"].resume, "sdk-42")

    def test_text_from_assistant_message_when_not_streamed_and_subagent_text_hidden(self):
        script = [delta(None, "interne", parent="toolu_x"),
                  ("msg", MB.AssistantMessage([MB.TextBlock("Réponse complète")])),
                  ("msg", MB.ResultMessage())]
        backend, sdk, rec = self.backend(script)
        h = Harness(self.ws)
        backend.run_turn(h.ctx, "x")
        self.assertEqual([p["text"] for p in h.of("text_delta")], ["Réponse complète"])

    def _tool_script(self, sdk, tid, name, tinput):
        return [("tool", tid, name, tinput),
                ("msg", MB.ResultMessage(session_id="sdk-1"))]

    def run_tool(self, name, tinput, decisions=None, approval="allow"):
        record: dict = {}
        holder: list = []
        backend, sdk, record = self.backend(holder, record=record)
        holder[:] = self._tool_script(sdk, "t1", name, tinput)
        h = Harness(self.ws, decisions, approval)
        backend.run_turn(h.ctx, "go")
        return h, record

    def test_allow_runs_without_approval_and_reports_file_written(self):
        h, rec = self.run_tool("Write", {"file_path": str(self.ws / "planning/x.md"), "content": "hi"})
        self.assertEqual(rec["executed"], [("Write", True)])
        self.assertEqual(h.approvals, [])
        self.assertEqual(len(h.decided), 1)  # hook + can_use_tool : UNE seule décision (cache)
        self.assertEqual(h.of("tool_start")[0]["name"], "fs.write")
        self.assertEqual(h.of("tool_end")[0]["ok"], True)
        self.assertEqual(h.of("file_written"), [{"path": "planning/x.md"}])
        self.assertEqual(h.of("done"), [{"reason": "end_turn"}])

    def test_write_outside_workspace_not_reported(self):
        h, _ = self.run_tool("Write", {"file_path": "/etc/passwd", "content": "x"})
        self.assertEqual(h.of("file_written"), [])

    def test_ask_then_allow_asks_once(self):
        h, rec = self.run_tool("mcp__garmin__schedule_workouts", {"workouts": [1]},
                               {"mcp:garmin.schedule_workouts": "ask"}, approval="allow")
        self.assertEqual(rec["executed"], [("mcp__garmin__schedule_workouts", True)])
        self.assertEqual(len(h.approvals), 1)  # hook + can_use_tool ne doublent pas la demande
        tool, tinput, summary, diff = h.approvals[0]
        self.assertEqual(tool, "mcp:garmin.schedule_workouts")
        self.assertEqual(tinput, {"workouts": [1]})
        self.assertIn("Garmin", summary)
        self.assertTrue(any(line["op"] == "+" for line in diff))
        self.assertEqual(h.of("tool_end")[0]["ok"], True)

    def test_ask_then_deny(self):
        h, rec = self.run_tool("mcp__garmin__delete_workout", {"id": 1},
                               {"mcp:garmin.delete_workout": "ask"}, approval="deny")
        self.assertEqual(rec["executed"], [("mcp__garmin__delete_workout", False)])
        end = h.of("tool_end")[0]
        self.assertFalse(end["ok"])
        self.assertEqual(end["summary"], "Refusé")
        self.assertEqual(h.of("done"), [{"reason": "end_turn"}])

    def test_ask_then_pending_ends_turn_pending(self):
        h, rec = self.run_tool("mcp__garmin__schedule_week", {"w": 1},
                               {"mcp:garmin.schedule_week": "ask"}, approval="pending")
        self.assertEqual(rec["executed"], [("mcp__garmin__schedule_week", False)])
        self.assertEqual(h.of("done"), [{"reason": "pending_approval"}])
        self.assertEqual(h.of("tool_end")[0]["summary"], "En attente de confirmation")

    def test_policy_deny_never_asks(self):
        h, rec = self.run_tool("Bash", {"command": "rm -rf /"}, {"shell": "deny"})
        self.assertEqual(rec["executed"], [("Bash", False)])
        self.assertEqual(h.approvals, [])

    def test_hook_reason_texts(self):
        record: dict = {}
        holder: list = []
        backend, sdk, record = self.backend(holder, record=record)
        holder[:] = [("msg", MB.ResultMessage())]
        h = Harness(self.ws, {"mcp:garmin.schedule_week": "ask"}, "pending")
        backend.run_turn(h.ctx, "x")
        hook = record["options"].hooks["PreToolUse"][0].hooks[0]
        import asyncio
        out = asyncio.run(hook({"tool_name": "mcp__garmin__schedule_week", "tool_input": {},
                                "tool_use_id": "z"}, "z", None))
        spec = out["hookSpecificOutput"]
        self.assertEqual(spec["permissionDecision"], "deny")
        self.assertEqual(spec["permissionDecisionReason"], "La proposition attend la confirmation de l'athlète.")
        h2 = Harness(self.ws, {"shell": "deny"})
        backend2, sdk2, rec2 = self.backend([("msg", MB.ResultMessage())])
        backend2.run_turn(h2.ctx, "x")
        hook2 = rec2["options"].hooks["PreToolUse"][0].hooks[0]
        out2 = asyncio.run(hook2({"tool_name": "Bash", "tool_input": {"command": "x"}, "tool_use_id": "y"},
                                 "y", None))
        self.assertIn("Refusé", out2["hookSpecificOutput"]["permissionDecisionReason"])

    def test_cancel_interrupts(self):
        record: dict = {}
        holder: list = []
        backend, sdk, record = self.backend(holder, record=record)
        holder[:] = [("wait_cancel",), ("msg", MB.ResultMessage())]
        h = Harness(self.ws)
        threading.Timer(0.3, h.ctx.cancelled.set).start()
        backend.run_turn(h.ctx, "x")
        self.assertTrue(record["interrupted"])
        self.assertEqual(h.of("done"), [{"reason": "interrupted"}])

    def test_max_turns_and_errors(self):
        holder: list = []
        backend, sdk, _ = self.backend(holder)
        holder[:] = [("msg", MB.ResultMessage(subtype="error_max_turns", is_error=True))]
        h = Harness(self.ws)
        backend.run_turn(h.ctx, "x")
        self.assertEqual(h.of("done"), [{"reason": "max_turns"}])
        holder[:] = [("msg", MB.AssistantMessage([], error="authentication_failed")),
                     ("msg", MB.ResultMessage(is_error=True))]
        with self.assertRaises(BackendError) as cm:
            backend.run_turn(Harness(self.ws).ctx, "x")
        self.assertIn("401", str(cm.exception))
        holder[:] = [("msg", MB.AssistantMessage([], error="billing_error")),
                     ("msg", MB.ResultMessage(is_error=True))]
        with self.assertRaises(BackendError) as cm:
            backend.run_turn(Harness(self.ws).ctx, "x")
        self.assertIn("402", str(cm.exception))


class TestApprovalDedupe(ClaudeBackendCase):
    def _turn(self, approval_hook):
        h = Harness(self.ws, {"mcp:garmin.schedule_week": "ask"})
        calls: list = []

        def request(tool, tinput, summary, diff):
            calls.append(tool)
            return approval_hook()
        h.ctx.request_approval = request
        return C._Turn(h.ctx, self.ws), calls

    def test_concurrent_paths_share_one_approval(self):
        release = threading.Event()
        turn, calls = self._turn(lambda: (release.wait(5), "allow")[1])
        out: list = []

        def go():
            out.append(turn.gate_sync("tu1", "mcp__garmin__schedule_week", {"w": 1}))
        t1 = threading.Thread(target=go)
        t1.start()
        for _ in range(100):
            if calls:
                break
            threading.Event().wait(0.02)
        t2 = threading.Thread(target=go)  # 2e voie (can_use_tool après expiration du hook)
        t2.start()
        threading.Event().wait(0.3)
        self.assertEqual(len(calls), 1)   # la seconde voie attend, n'ouvre rien
        release.set()
        t1.join(5)
        t2.join(5)
        self.assertEqual(out, [("allow", ""), ("allow", "")])
        self.assertEqual(len(calls), 1)

    def test_second_path_gets_pending_and_cancel_releases_waiter(self):
        release = threading.Event()
        turn, calls = self._turn(lambda: (release.wait(5), "pending")[1])
        t1 = threading.Thread(target=lambda: turn.gate_sync("tu2", "mcp__garmin__schedule_week", {}))
        t1.start()
        for _ in range(100):
            if calls:
                break
            threading.Event().wait(0.02)
        res: list = []
        t2 = threading.Thread(target=lambda: res.append(turn.gate_sync("tu2", "mcp__garmin__schedule_week", {})))
        t2.start()
        release.set()
        t1.join(5)
        t2.join(5)
        self.assertEqual(res[0][0], "pending")
        self.assertEqual(len(calls), 1)
        # annulation : le second waiter ne reste pas bloqué
        block = threading.Event()
        turn2, calls2 = self._turn(lambda: (block.wait(5), "allow")[1])
        t3 = threading.Thread(target=lambda: turn2.gate_sync("tu3", "mcp__garmin__schedule_week", {}))
        t3.start()
        for _ in range(100):
            if calls2:
                break
            threading.Event().wait(0.02)
        res2: list = []
        t4 = threading.Thread(target=lambda: res2.append(turn2.gate_sync("tu3", "mcp__garmin__schedule_week", {})))
        t4.start()
        turn2.ctx.cancelled.set()
        t4.join(3)
        self.assertFalse(t4.is_alive())
        self.assertEqual(res2[0][0], "deny")
        block.set()
        t3.join(5)

    def test_hook_timeout_exceeds_approval_wait(self):
        backend, sdk, rec = self.backend([("msg", MB.ResultMessage())], {"approval_wait_s": 600})
        backend.run_turn(Harness(self.ws).ctx, "x")
        self.assertEqual(rec["options"].hooks["PreToolUse"][0].timeout, 600 + C.HOOK_TIMEOUT_MARGIN_S)
        backend2, _, rec2 = self.backend([("msg", MB.ResultMessage())], {})
        backend2.run_turn(Harness(self.ws).ctx, "x")
        self.assertGreater(rec2["options"].hooks["PreToolUse"][0].timeout, 600)


class TestBudget(ClaudeBackendCase):
    def test_partial_usage_emitted_on_sdk_exception(self):
        script = [("msg", MB.AssistantMessage([MB.TextBlock("a")], message_id="m1",
                                              usage={"input_tokens": 10, "output_tokens": 4})),
                  ("msg", MB.AssistantMessage([MB.TextBlock("a")], message_id="m1",
                                              usage={"input_tokens": 10, "output_tokens": 4})),
                  ("raise", RuntimeError("boom"))]
        backend, sdk, _ = self.backend(script)
        h = Harness(self.ws)
        with self.assertRaises(BackendError):
            backend.run_turn(h.ctx, "x")
        usage = h.of("usage")
        self.assertEqual(len(usage), 1)
        self.assertEqual((usage[0]["input_tokens"], usage[0]["output_tokens"]), (10, 4))  # dédupliqué par message_id

    def test_no_usage_when_nothing_known(self):
        backend, sdk, _ = self.backend([("raise", RuntimeError("boom"))])
        h = Harness(self.ws)
        with self.assertRaises(BackendError):
            backend.run_turn(h.ctx, "x")
        self.assertEqual(h.of("usage"), [])

    def test_result_error_still_reports_cost(self):
        script = [("msg", MB.ResultMessage(is_error=True, subtype="error_during_execution", total_cost_usd=0.2,
                                           result="x"))]
        backend, sdk, _ = self.backend(script)
        h = Harness(self.ws)
        with self.assertRaises(BackendError):
            backend.run_turn(h.ctx, "x")
        self.assertAlmostEqual(h.of("usage")[0]["cost_eur"], 0.18, places=4)

    def test_turn_budget_passed_to_sdk_in_usd(self):
        backend, sdk, rec = self.backend([("msg", MB.ResultMessage())],
                                         {"turn_budget_eur": 0.45, "usd_eur_rate": 0.9})
        backend.run_turn(Harness(self.ws).ctx, "x")
        self.assertAlmostEqual(rec["options"].max_budget_usd, 0.5, places=4)
        backend2, _, rec2 = self.backend([("msg", MB.ResultMessage())], {})
        backend2.run_turn(Harness(self.ws).ctx, "x")
        self.assertIsNone(rec2["options"].max_budget_usd)

    def test_budget_result_ends_with_budget_done(self):
        script = [("msg", MB.ResultMessage(subtype="error_max_budget_usd", is_error=True, total_cost_usd=0.5))]
        backend, sdk, _ = self.backend(script, {"turn_budget_eur": 0.45})
        h = Harness(self.ws)
        backend.run_turn(h.ctx, "x")
        self.assertEqual(h.of("done"), [{"reason": "budget"}])
        self.assertIn("budget", "".join(p["text"] for p in h.of("text_delta")).lower())
        self.assertAlmostEqual(h.of("usage")[0]["cost_eur"], 0.45, places=4)

    def test_b3_budget_du_tour_lu_dans_ctx_config(self):
        """Le service pose `turn_budget_eur` sur `ctx.config` (pas sur la config du backend)."""
        backend, sdk, rec = self.backend([("msg", MB.ResultMessage())], {"usd_eur_rate": 0.9})
        h = Harness(self.ws)
        h.ctx.config = {"turn_budget_eur": 0.45, "usd_eur_rate": 0.9}
        backend.run_turn(h.ctx, "x")
        self.assertAlmostEqual(rec["options"].max_budget_usd, 0.5, places=4)

    def test_b3_budget_epuise_jamais_sans_plafond(self):
        backend, sdk, rec = self.backend([("msg", MB.ResultMessage())], {})
        h = Harness(self.ws)
        h.ctx.config = {"turn_budget_eur": 0.0}
        backend.run_turn(h.ctx, "x")
        self.assertLess(rec["options"].max_budget_usd, 0.001)

    def test_s4_plantage_sans_resultat_cout_estime_depuis_les_jetons(self):
        script = [("msg", MB.AssistantMessage([MB.TextBlock("a")], message_id="m1",
                                              usage={"input_tokens": 1_000_000, "output_tokens": 100_000,
                                                     "cache_read_input_tokens": 1_000_000})),
                  ("raise", RuntimeError("boom"))]
        for model, usd in (("claude-sonnet-5-5", 2.0 + 0.2 + 1.0), ("claude-opus-5-5", 4.0 + 0.4 + 2.0),
                           ("claude-haiku-4-5", 1.0 + 0.1 + 0.5), ("modele-inconnu", 2.0 + 0.2 + 1.0)):
            backend, sdk, _ = self.backend(script, {"model": model, "usd_eur_rate": 0.9})
            h = Harness(self.ws)
            with self.assertRaises(BackendError):
                backend.run_turn(h.ctx, "x")
            self.assertAlmostEqual(h.of("usage")[0]["cost_eur"], usd * 0.9, places=4, msg=model)


class TestPreconditions(ClaudeBackendCase):
    def test_missing_key(self):
        import os
        backend, _, _ = self.backend([])
        os.environ.pop("ANTHROPIC_API_KEY")
        ok, msg = backend.check()
        self.assertFalse(ok)
        self.assertIn("ANTHROPIC_API_KEY", msg)
        with self.assertRaises(BackendError):
            backend.run_turn(Harness(self.ws).ctx, "x")

    def test_custom_key_env_is_forwarded_as_anthropic_key(self):
        import os
        record: dict = {}
        holder: list = []
        os.environ.pop("ANTHROPIC_API_KEY")
        os.environ["MY_CLAUDE_KEY"] = "sk-custom"
        backend, sdk, record = self.backend(holder, {"api_key_env": "MY_CLAUDE_KEY"}, record)
        holder[:] = [("msg", MB.ResultMessage())]
        backend.run_turn(Harness(self.ws).ctx, "x")
        self.assertEqual(record["options"].env["ANTHROPIC_API_KEY"], "sk-custom")
        ok, _ = backend.check()
        self.assertTrue(ok)

    def test_package_absent(self):
        sys.modules["claude_agent_sdk"] = None  # force ImportError
        backend = C.ClaudeBackend(self.ws, {})
        ok, msg = backend.check()
        self.assertFalse(ok)
        self.assertEqual(msg, "paquet claude-agent-sdk absent — pip install -U 'claude-agent-sdk>=0.2.121'")
        with self.assertRaises(BackendError):
            backend.run_turn(Harness(self.ws).ctx, "x")

    def test_version_floor_blocks_vulnerable_sdk(self):
        """GHSA-h4mw-j7qp-8mwm : < 0.2.121 refusé par check() ; inconnue = non bloquant, dite."""
        cases = [("0.2.120", False), ("0.2.121", True), ("0.2.165", True), ("1.0.0", True),
                 ("0.1.99", False), ("0.2", False), ("0.2.121rc1", True), ("?", True)]
        for version, expected in cases:
            with self.subTest(version=version):
                backend, sdk, _ = self.backend([])
                sdk.__version__ = version
                ok, msg = backend.check()
                self.assertEqual(ok, expected, msg)
                if not expected:
                    self.assertIn("GHSA-h4mw-j7qp-8mwm", msg)
                    self.assertIn("pip install -U 'claude-agent-sdk>=0.2.121'", msg)
                if version == "?":
                    self.assertIn("version inconnue", msg)

    def test_version_compare_helpers(self):
        self.assertTrue(C.version_below("0.2.120", "0.2.121"))
        self.assertFalse(C.version_below("0.2.121", "0.2.121"))
        self.assertFalse(C.version_below("0.10.0", "0.2.121"))
        self.assertIsNone(C.version_below("?", "0.2.121"))
        self.assertEqual(C.SDK_TESTED_VERSION, "0.2.165")

    def test_sdk_exception_is_translated(self):
        holder: list = []
        backend, sdk, _ = self.backend(holder)

        class Boom(sdk.ClaudeSDKClient):
            async def connect(self):
                raise sdk.CLINotFoundError("no cli")
        sdk.ClaudeSDKClient = Boom
        with self.assertRaises(BackendError) as cm:
            backend.run_turn(Harness(self.ws).ctx, "x")
        self.assertIn("introuvable", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
