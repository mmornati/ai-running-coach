#!/usr/bin/env python3
"""Backend « claude » du chat coach : Claude Agent SDK (paquet `claude-agent-sdk`).

Le SDK EST le harnais Claude Code en bibliothèque : il charge `.claude/agents`,
skills, `.mcp.json` et `AGENTS.md` du workspace comme l'IDE. Authentification par
clé API uniquement (variable nommée par `[chat].api_key_env`), jamais l'OAuth
d'un abonnement.

Sources officielles vérifiées (claude-agent-sdk 0.2.165, CLI embarqué 2.1.294) :
  - https://code.claude.com/docs/en/agent-sdk/python      (ClaudeAgentOptions, messages)
  - https://code.claude.com/docs/en/agent-sdk/permissions (ordre d'évaluation, can_use_tool, hooks)
  - https://github.com/anthropics/claude-agent-sdk-python (le wheel EMBARQUE le CLI Claude Code :
    pas de Node à installer ; Python >= 3.10) et le code du wheel lui-même (types.py, client.py).

Faits établis dans le code du wheel :
  - `can_use_tool` : `async (tool_name, input, ToolPermissionContext) -> PermissionResultAllow|Deny`,
    `ToolPermissionContext.tool_use_id` toujours renseigné ; il n'est appelé QUE pour les appels
    qui ne sont pas déjà approuvés (règles allow, lectures dans le cwd, `acceptEdits`…).
  - Pour que CHAQUE appel passe par la politique, on branche donc AUSSI un hook `PreToolUse`
    (`HookMatcher`), exécuté avant tout le reste ; les deux partagent un cache par `tool_use_id`
    pour ne jamais demander deux fois la même approbation.
  - `ClaudeSDKClient` (mode streaming) : `connect()`, `query()`, `receive_response()`,
    `interrupt()`, `disconnect()`. `StreamEvent.event` = évènement brut de l'API Messages.
  - `ResultMessage` : `subtype`, `is_error`, `session_id`, `total_cost_usd`, `usage`.
  - `system_prompt={"type": "preset", "preset": "claude_code", "append": ...}`.

Le module s'importe sans le paquet : `claude_agent_sdk` n'est importé que dans les méthodes.
"""

from __future__ import annotations

import asyncio
import os
import re
import threading
from pathlib import Path
from typing import Any, Optional

from arc_chat_backend import (SYSTEM_ADDENDUM, system_addendum, BackendError, ChatBackend, TurnContext,
                              resolve_workspace_path)
from arc_chat_tools import (REFUSAL_DENY, display_input, fs_list_input, gate, map_leanproxy,
                            remember_result, short, summarize_tool, usd_to_eur)

SDK_TESTED_VERSION = "0.2.165"
# Plancher de sécurité : avant 0.2.121, GHSA-h4mw-j7qp-8mwm (critique, injection d'arguments par
# `resume`). Une version plus ancienne est refusée par `check()`.
SDK_MIN_VERSION = "0.2.121"
SDK_INSTALL_HINT = f"pip install -U 'claude-agent-sdk>={SDK_MIN_VERSION}'"
DEFAULT_API_KEY_ENV = "ANTHROPIC_API_KEY"

# Outils natifs retirés du contexte du modèle (interaction terminal sans objet dans le chat).
DISALLOWED_TOOLS = ["AskUserQuestion", "TodoWrite", "EnterPlanMode", "ExitPlanMode"]

_FS_WRITE = ("Write", "Edit", "MultiEdit", "NotebookEdit")
_FS_LIST = ("Glob", "Grep", "LS")
HOOK_TIMEOUT_MARGIN_S = 120      # marge au-dessus de approval_wait_s pour le délai du hook PreToolUse
DEFAULT_APPROVAL_WAIT_S = 600

# Tarifs USD par million de jetons (entrée, sortie) : repli quand aucun `ResultMessage` n'est arrivé
# (plantage du SDK) — le coût est alors estimé depuis les jetons comptés. Lecture du cache = 10 % de l'entrée.
# Modèle inconnu : tarif Sonnet, le choix prudent le plus courant.
MODEL_PRICES_USD_PER_MTOK = {
    "claude-sonnet-5-5": (2.0, 10.0),
    "claude-opus-5-5": (4.0, 20.0),
    "claude-haiku-4-5": (1.0, 5.0),
}
DEFAULT_MODEL_PRICE = MODEL_PRICES_USD_PER_MTOK["claude-sonnet-5-5"]
CACHE_READ_FACTOR = 0.1


def model_price(model: Any) -> tuple:
    """(entrée, sortie) en USD/MTok ; correspondance exacte, puis par famille, sinon tarif Sonnet."""
    name = str(model or "").lower()
    if name in MODEL_PRICES_USD_PER_MTOK:
        return MODEL_PRICES_USD_PER_MTOK[name]
    for family in ("opus", "haiku", "sonnet"):
        if family in name:
            return next(v for k, v in MODEL_PRICES_USD_PER_MTOK.items() if family in k)
    return DEFAULT_MODEL_PRICE


def estimate_cost_usd(model: Any, tokens: dict) -> float:
    """Coût estimé depuis les jetons cumulés (`input`, `output`, `cache_read`)."""
    price_in, price_out = model_price(model)
    return (tokens.get("input", 0) * price_in + tokens.get("cache_read", 0) * price_in * CACHE_READ_FACTOR
            + tokens.get("output", 0) * price_out) / 1_000_000


def canonical_tool(name: str, tool_input: Optional[dict]) -> tuple:
    """Nom d'outil Claude Code -> (nom canonique, entrée canonique)."""
    inp = dict(tool_input or {})
    if name in ("Read", "NotebookRead"):
        return "fs.read", {"path": inp.get("file_path") or inp.get("notebook_path") or ""}
    if name in _FS_WRITE:
        out = {k: v for k, v in inp.items() if k not in ("file_path", "notebook_path")}
        out["path"] = inp.get("file_path") or inp.get("notebook_path") or ""
        return "fs.write", out
    if name in _FS_LIST:
        if name == "Glob":   # `pattern` de Glob = filtre de fichiers, pas une regex
            return "fs.list", fs_list_input(inp.get("path"), None, inp.get("pattern"))
        if name == "Grep":   # `pattern` = regex ; `glob` = filtre de fichiers
            return "fs.list", fs_list_input(inp.get("path"), inp.get("pattern"), inp.get("glob"))
        return "fs.list", fs_list_input(inp.get("path"))
    if name == "Bash":
        return "shell", {"command": inp.get("command", "")}
    if name == "WebFetch":
        return "web.fetch", {"url": inp.get("url", "")}
    if name == "WebSearch":
        return "web.search", {"query": inp.get("query", "")}
    if name in ("Task", "Agent"):
        return "task", {"agent": inp.get("subagent_type") or inp.get("agent") or ""}
    if name == "Skill":
        return "skill", {"name": inp.get("skill") or inp.get("name") or ""}
    if name.startswith("mcp__"):
        parts = name.split("__", 2)
        server = parts[1].lower() if len(parts) > 1 else ""
        tool = parts[2] if len(parts) > 2 else ""
        if server.startswith("leanproxy"):
            mapped = map_leanproxy(tool, inp)
            if mapped:
                return mapped
        return f"mcp:{server}.{tool}", inp
    return f"other:{name}", inp


class _Flight:
    """Décision d'UN tool_use_id : en cours (`done` non posé) ou terminée (`result`)."""

    def __init__(self) -> None:
        self.done = threading.Event()
        self.result: Optional[tuple] = None


class _Turn:
    """État d'UN tour : contexte, cache d'approbations, outils en vol."""

    def __init__(self, ctx: TurnContext, workspace: Path):
        self.ctx = ctx
        self.workspace = workspace
        self.cache: dict = {}            # tool_use_id -> _Flight
        self.cache_lock = threading.Lock()
        self.tools: dict = {}            # tool_use_id -> (canonique, entrée)
        self.pending = False
        self.streamed_text = False
        self.usage_emitted = False
        self.tokens = {"input": 0, "output": 0, "cache_read": 0}
        self.seen_messages: set = set()  # message_id dont l'usage est déjà compté
        self.budget_hit = False

    def cached_result(self, tool_use_id: Optional[str]) -> Optional[tuple]:
        with self.cache_lock:
            flight = self.cache.get(tool_use_id) if tool_use_id else None
        return flight.result if flight else None

    def gate_sync(self, tool_use_id: Optional[str], name: str, tool_input: dict) -> tuple:
        """Politique + approbation (bloquant, exécuté dans un thread).

        Le hook PreToolUse et `can_use_tool` peuvent porter sur le MÊME appel (et se
        chevaucher si le hook expire pendant une attente d'approbation) : la première voie
        crée un « vol » dans le cache, la seconde attend SA décision au lieu d'ouvrir une
        seconde approbation (donc jamais deux écritures Garmin).
        """
        flight: Optional[_Flight] = None
        owner = True
        if tool_use_id:
            with self.cache_lock:
                flight = self.cache.get(tool_use_id)
                if flight is None:
                    flight = self.cache[tool_use_id] = _Flight()
                else:
                    owner = False
        if not owner and flight is not None:
            while not flight.done.wait(0.25):
                if self.ctx.cancelled.is_set():
                    return "deny", REFUSAL_DENY
            return flight.result or ("deny", REFUSAL_DENY)
        result: tuple = ("deny", REFUSAL_DENY)
        try:
            tool, cinput = canonical_tool(name, tool_input)
            result = gate(self.ctx, tool, cinput)
            if result[0] == "pending":
                self.pending = True
        finally:
            if flight is not None:
                flight.result = result
                flight.done.set()
        return result


def parse_version(raw: Any) -> Optional[tuple]:
    """Préfixe numérique d'une version (« 0.2.121 », « 1.0.0rc1 » -> (1, 0, 0)) ; `None` si
    inconnue ou illisible (« ? », « 0.0-fake » reste (0, 0)). Bibliothèque standard seulement."""
    match = re.match(r"\s*v?(\d+(?:\.\d+)*)", str(raw or ""))
    if not match:
        return None
    return tuple(int(part) for part in match.group(1).split("."))


def version_below(version: Any, minimum: str) -> Optional[bool]:
    """`True` si `version` < `minimum`, `False` sinon, `None` si `version` est illisible.
    Les composantes manquantes valent 0 ((0, 2) == (0, 2, 0))."""
    have, floor = parse_version(version), parse_version(minimum)
    if have is None or floor is None:
        return None
    width = max(len(have), len(floor))
    return have + (0,) * (width - len(have)) < floor + (0,) * (width - len(floor))


class ClaudeBackend(ChatBackend):
    name = "claude"

    def __init__(self, workspace: Path, config: dict):
        super().__init__(workspace, config)

    # -- configuration -------------------------------------------------

    def _hook_timeout(self) -> float:
        """Délai du hook PreToolUse (SDK : `HookMatcher.timeout`, 60 s par défaut) : doit
        dépasser l'attente d'approbation en ligne, sinon le CLI passe à `can_use_tool`."""
        try:
            wait = float(self.config.get("approval_wait_s") or DEFAULT_APPROVAL_WAIT_S)
        except (TypeError, ValueError):
            wait = float(DEFAULT_APPROVAL_WAIT_S)
        return wait + HOOK_TIMEOUT_MARGIN_S

    def _cfg_value(self, ctx: Optional[TurnContext], key: str) -> Any:
        """Valeur du tour (`ctx.config`, où le service pose le budget restant) sinon de la configuration du backend."""
        ctx_config = getattr(ctx, "config", None) or {}
        return ctx_config[key] if ctx_config.get(key) is not None else self.config.get(key)

    def _rate(self, ctx: Optional[TurnContext]) -> float:
        try:
            return float(self._cfg_value(ctx, "usd_eur_rate") or 0.92)
        except (TypeError, ValueError):
            return 0.92

    def _budget_usd(self, ctx: Optional[TurnContext] = None) -> Optional[float]:
        """Plafond du tour en USD (`ClaudeAgentOptions.max_budget_usd`) ; None = pas de plafond.

        `turn_budget_eur` (budget restant du jour, propre au tour) vient de `ctx.config`."""
        raw = self._cfg_value(ctx, "turn_budget_eur")
        try:
            eur = float(raw)
        except (TypeError, ValueError):
            return None
        if eur <= 0:
            return 0.000001                     # budget épuisé : jamais « sans plafond »
        return round(eur / self._rate(ctx), 6)

    def _api_key_env(self) -> str:
        return str(self.config.get("api_key_env") or DEFAULT_API_KEY_ENV)

    def _api_key(self) -> str:
        return os.environ.get(self._api_key_env(), "").strip()

    def check(self) -> tuple:
        try:
            import claude_agent_sdk  # type: ignore
        except ImportError:
            return False, f"paquet claude-agent-sdk absent — {SDK_INSTALL_HINT}"
        if not self._api_key():
            return False, (f"clé API absente : variable {self._api_key_env()} vide "
                           "(à renseigner dans ~/.config/ai-running-coach/llm.env)")
        version = getattr(claude_agent_sdk, "__version__", "?")
        if version_below(version, SDK_MIN_VERSION):
            return False, (f"claude-agent-sdk {version} < {SDK_MIN_VERSION} (GHSA-h4mw-j7qp-8mwm) — "
                           f"{SDK_INSTALL_HINT}")
        if parse_version(version) is None:
            return True, f"claude-agent-sdk version inconnue (minimum {SDK_MIN_VERSION}, testé avec {SDK_TESTED_VERSION})"
        return True, f"claude-agent-sdk {version} (testé avec {SDK_TESTED_VERSION})"

    def _options(self, sdk: Any, turn: _Turn, resume: Optional[str]) -> Any:
        cfg = self.config
        key = self._api_key()
        env = {
            "ANTHROPIC_API_KEY": key,
            # Jamais d'abonnement : on neutralise les autres sources d'identifiants.
            # À VÉRIFIER : la chaîne vide est bien traitée comme « non définie » par le CLI.
            "CLAUDE_CODE_OAUTH_TOKEN": "",
            "ANTHROPIC_AUTH_TOKEN": "",
        }

        async def pre_tool_use(input_data: dict, tool_use_id: Optional[str], _context: Any) -> dict:
            name = input_data.get("tool_name", "")
            tuid = tool_use_id or input_data.get("tool_use_id")
            decision, message = await asyncio.to_thread(
                turn.gate_sync, tuid, name, input_data.get("tool_input") or {})
            out = {"hookEventName": "PreToolUse",
                   "permissionDecision": "allow" if decision == "allow" else "deny"}
            if decision != "allow":
                out["permissionDecisionReason"] = message
            return {"hookSpecificOutput": out}

        async def can_use_tool(name: str, tool_input: dict, context: Any) -> Any:
            decision, message = await asyncio.to_thread(
                turn.gate_sync, getattr(context, "tool_use_id", None), name, tool_input)
            if decision == "allow":
                return sdk.PermissionResultAllow()
            return sdk.PermissionResultDeny(message=message or REFUSAL_DENY)

        kwargs: dict = dict(
            cwd=str(self.workspace),
            setting_sources=["project"],
            system_prompt={"type": "preset", "preset": "claude_code", "append": system_addendum(turn.ctx.language)},
            can_use_tool=can_use_tool,
            hooks={"PreToolUse": [sdk.HookMatcher(matcher=None, hooks=[pre_tool_use],
                                                   timeout=self._hook_timeout())]},
            include_partial_messages=True,
            permission_mode="default",
            disallowed_tools=list(DISALLOWED_TOOLS),
            env=env,
        )
        if cfg.get("model"):
            kwargs["model"] = str(cfg["model"])
        if cfg.get("max_turns"):
            kwargs["max_turns"] = int(cfg["max_turns"])
        cap_usd = self._budget_usd(turn.ctx)
        if cap_usd is not None:
            kwargs["max_budget_usd"] = cap_usd
        if resume:
            kwargs["resume"] = resume
        return sdk.ClaudeAgentOptions(**kwargs)

    # -- tour ------------------------------------------------------------

    def run_turn(self, ctx: TurnContext, user_message: str) -> None:
        try:
            import claude_agent_sdk as sdk  # type: ignore
        except ImportError:
            raise BackendError("Le paquet claude-agent-sdk n'est pas installé "
                               f"({SDK_INSTALL_HINT}).")
        if not self._api_key():
            raise BackendError(f"Clé API Anthropic absente : la variable {self._api_key_env()} "
                               "est vide (voir ~/.config/ai-running-coach/llm.env).")
        turn = _Turn(ctx, self.workspace)
        try:
            # Boucle privée par tour : le service appelle run_turn depuis un thread.
            asyncio.run(self._run_async(sdk, turn, user_message))
        except BackendError:
            raise
        except Exception as exc:  # noqa: BLE001 — traduit en message lisible
            raise BackendError(self._translate_exception(sdk, exc)) from exc

    @staticmethod
    def _translate_exception(sdk: Any, exc: Exception) -> str:
        if isinstance(exc, getattr(sdk, "CLINotFoundError", ())):
            return "Le CLI Claude Code est introuvable (réinstaller claude-agent-sdk)."
        text = str(exc)
        low = text.lower()
        if "401" in low or "authentication" in low or "invalid x-api-key" in low:
            return "Clé API Anthropic refusée (401) : vérifier la clé dans llm.env."
        if "402" in low or "credit balance" in low:
            return "Crédit Anthropic insuffisant (402)."
        return f"Erreur du backend Claude : {short(text, 200)}"

    async def _run_async(self, sdk: Any, turn: _Turn, user_message: str) -> None:
        ctx = turn.ctx
        resume = ctx.backend_state.get("sdk_session_id")
        options = self._options(sdk, turn, resume)
        client = sdk.ClaudeSDKClient(options=options)
        watcher: Optional[asyncio.Task] = None
        result: Any = None
        assistant_error: Optional[str] = None
        try:
            await client.connect()
            async def watch_cancel() -> None:
                while True:
                    await asyncio.sleep(0.1)
                    if ctx.cancelled.is_set():
                        try:
                            await client.interrupt()
                        except Exception:  # noqa: BLE001
                            pass
                        return

            watcher = asyncio.create_task(watch_cancel())
            await client.query(user_message)
            async for message in client.receive_response():
                kind = type(message).__name__
                sid = getattr(message, "session_id", None)
                if sid and kind in ("ResultMessage", "StreamEvent", "SystemMessage"):
                    ctx.backend_state["sdk_session_id"] = sid
                if kind == "StreamEvent":
                    self._on_stream_event(turn, message)
                elif kind == "AssistantMessage":
                    assistant_error = getattr(message, "error", None) or assistant_error
                    self._count_usage(turn, message)
                    self._on_assistant(turn, message)
                elif kind == "UserMessage":
                    self._on_user(turn, message)
                elif kind == "ResultMessage":
                    result = message
        except BaseException:
            # Tour interrompu par une exception du SDK : le coût partiel n'est pas perdu.
            if result is not None or any(turn.tokens.values()):
                self._emit_usage(turn, result)
            raise
        finally:
            if watcher:
                watcher.cancel()
            try:
                await client.disconnect()
            except Exception:  # noqa: BLE001
                pass
        self._finish(turn, result, assistant_error)

    # -- traduction des messages ---------------------------------------

    def _on_stream_event(self, turn: _Turn, message: Any) -> None:
        if getattr(message, "parent_tool_use_id", None):
            return  # texte interne d'un sous-agent : non affiché
        event = getattr(message, "event", None) or {}
        if event.get("type") == "content_block_start" and (event.get("content_block") or {}).get("type") == "text":
            turn.text_part = getattr(turn, "text_part", 0) + 1       # nouveau bloc de texte
        if event.get("type") == "content_block_delta":
            delta = event.get("delta") or {}
            if delta.get("type") == "text_delta" and delta.get("text"):
                turn.streamed_text = True
                turn.ctx.emit("text_delta", {"text": delta["text"], "part": f"b{getattr(turn, 'text_part', 0)}"})

    def _on_assistant(self, turn: _Turn, message: Any) -> None:
        top_level = not getattr(message, "parent_tool_use_id", None)
        for block in getattr(message, "content", None) or []:
            bname = type(block).__name__
            if bname == "TextBlock" and top_level and not turn.streamed_text and block.text:
                turn.ctx.emit("text_delta", {"text": block.text})
            elif bname == "ToolUseBlock":
                tool, cinput = canonical_tool(block.name, block.input)
                turn.tools[block.id] = (tool, cinput)
                turn.ctx.emit("tool_start", {"id": block.id, "name": tool,
                                             "summary": summarize_tool(
                                                 tool, display_input(self.workspace, tool, cinput))})
        if top_level:
            turn.streamed_text = False

    def _on_user(self, turn: _Turn, message: Any) -> None:
        content = getattr(message, "content", None)
        if not isinstance(content, list):
            return
        for block in content:
            if type(block).__name__ != "ToolResultBlock":
                continue
            tool, cinput = turn.tools.get(block.tool_use_id, ("other:inconnu", {}))
            ok = not bool(block.is_error)
            cached = turn.cached_result(block.tool_use_id)
            if not ok and cached and cached[0] != "allow":
                summary = "Refusé" if cached[0] == "deny" else "En attente de confirmation"
            else:
                summary = "Terminé" if ok else "Échec"
            turn.ctx.emit("tool_end", {"id": block.tool_use_id, "ok": ok, "summary": summary})
            if ok:
                remember_result(turn.ctx.backend_state, tool, getattr(block, "content", None))
            if ok and tool == "fs.write":
                rel = resolve_workspace_path(self.workspace, cinput.get("path"))
                if rel:
                    turn.ctx.emit("file_written", {"path": rel})

    @staticmethod
    def _count_usage(turn: _Turn, message: Any) -> None:
        """Cumule les jetons des messages assistant (une fois par message_id) — repli si le
        `ResultMessage` n'arrive jamais ; son coût, lui, n'est connu qu'à la fin."""
        usage = getattr(message, "usage", None)
        mid = getattr(message, "message_id", None)
        if not isinstance(usage, dict) or (mid and mid in turn.seen_messages):
            return
        if mid:
            turn.seen_messages.add(mid)
        turn.tokens["input"] += int(usage.get("input_tokens") or 0)
        turn.tokens["output"] += int(usage.get("output_tokens") or 0)
        turn.tokens["cache_read"] += int(usage.get("cache_read_input_tokens") or 0)

    def _emit_usage(self, turn: _Turn, result: Any) -> None:
        """Émet `usage` une seule fois, avec ce qui est connu (jetons cumulés, coût du résultat)."""
        if turn.usage_emitted:
            return
        turn.usage_emitted = True
        usage = (getattr(result, "usage", None) or {}) if result is not None else {}
        tokens = turn.tokens
        cost_usd = getattr(result, "total_cost_usd", None) if result is not None else None
        if cost_usd is None and any(tokens.values()):
            # Pas de `ResultMessage` (plantage) : estimation depuis les jetons, jamais 0 €.
            model = (getattr(turn.ctx, "config", None) or {}).get("model") or self.config.get("model")
            cost_usd = estimate_cost_usd(model, tokens)
        turn.ctx.emit("usage", {
            "input_tokens": int(usage.get("input_tokens") or tokens["input"]),
            "output_tokens": int(usage.get("output_tokens") or tokens["output"]),
            "cache_read_tokens": int(usage.get("cache_read_input_tokens") or tokens["cache_read"]),
            "cost_eur": usd_to_eur(cost_usd, self._rate(turn.ctx)),
        })

    def _finish(self, turn: _Turn, result: Any, assistant_error: Optional[str]) -> None:
        ctx = turn.ctx
        self._emit_usage(turn, result)
        if assistant_error == "authentication_failed":
            raise BackendError("Clé API Anthropic refusée (401) : vérifier la clé dans llm.env.")
        if assistant_error == "billing_error":
            raise BackendError("Crédit Anthropic insuffisant (402).")
        if assistant_error == "rate_limit":
            raise BackendError("Limite de débit Anthropic atteinte : réessaie dans un instant.")
        subtype = getattr(result, "subtype", "") if result is not None else ""
        if subtype == "error_max_budget_usd":
            ctx.emit("text_delta", {"text": "\n\nLe budget du jour est atteint : je m'arrête ici."})
            ctx.emit("done", {"reason": "budget"})
            return
        if result is not None and getattr(result, "is_error", False) and subtype != "error_max_turns":
            detail = short(getattr(result, "result", None) or subtype or "erreur inconnue", 200)
            raise BackendError(f"Le backend Claude a échoué : {detail}")
        if ctx.cancelled.is_set():
            reason = "interrupted"
        elif turn.pending:
            reason = "pending_approval"
        elif subtype == "error_max_turns":
            reason = "max_turns"
        else:
            reason = "end_turn"
        ctx.emit("done", {"reason": reason})

    def shutdown(self) -> None:
        """Rien à libérer : une boucle asyncio et un client par tour, fermés en fin de tour."""
