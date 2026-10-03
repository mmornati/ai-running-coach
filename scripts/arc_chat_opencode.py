#!/usr/bin/env python3
"""Backend « opencode » du chat coach : serveur OpenCode + fournisseurs compatibles OpenAI.

OpenCode est le harnais (agents `.opencode/agents`, skills, MCP, outils fichiers) ;
ce module est un adaptateur mince : il supervise un `opencode serve` local, lui envoie
les messages de l'athlète, traduit son flux d'évènements vers le protocole du chat
et répond à ses demandes de permission après passage par la politique du coach.
Fournisseur par défaut : OpenRouter (`openrouter/deepseek/deepseek-v4.1-flash`), ou tout
endpoint compatible OpenAI via `[chat].base_url`.

Bibliothèque standard uniquement (urllib, threads, subprocess).

Sources vérifiées le 2026-09 contre OpenCode 1.18.32 (binaire réel, `/doc` OpenAPI 3.1
du serveur, et un tour complet rejoué contre un faux fournisseur OpenAI local) :
  - https://opencode.ai/docs/server        (auth Basic via OPENCODE_SERVER_PASSWORD, /doc)
  - https://opencode.ai/docs/config        (précédence, OPENCODE_CONFIG, `{env:VAR}`)
  - https://opencode.ai/docs/permissions   (clés `edit|bash|webfetch|task|skill|…`, ask/allow/deny)
  - https://opencode.ai/docs/providers     (openrouter, `@ai-sdk/openai-compatible`)
  - https://opencode.ai/docs/mcp-servers   (`type: local`, outils exposés `<serveur>_<outil>`)

Faits établis (voir `tests/data/fixtures/chat/opencode_*.json`, extraits du binaire réel) :
  - `POST /session` {title} -> Session ; `POST /session/{id}/prompt_async` {parts, system,
    model:{providerID, modelID}} -> 204 ; `POST /session/{id}/abort` -> true.
  - `GET /event` (SSE, `data: {"type", "properties"}`) : `server.connected`, `session.status`
    {busy|idle}, `session.idle`, `message.updated` (info.role user|assistant, cost, tokens),
    `message.part.updated` (part.type text|tool|step-start|step-finish…), `message.part.delta`
    {partID, field:"text", delta}, `permission.asked`, `permission.replied`, `session.error`.
  - Partie « tool » : `state.status` pending -> running (input complet) -> completed|error ;
    `step-finish` porte `tokens` {input, output, cache:{read, write}} et `cost` (USD).
  - `permission.asked` {id, permission, patterns, metadata, tool:{messageID, callID}} : NE porte PAS
    l'entrée de l'outil (sauf `metadata.diff`/`filepath` pour `edit`) -> on la relit dans la
    partie « tool » (évènement `running`, ou `GET /session/{id}/message/{messageID}`).
  - Réponse : `POST /permission/{id}/reply` {reply: once|always|reject, message?}. Avec un
    `message`, le rejet est renvoyé au modèle comme retour d'expérience ET la boucle continue
    (sans message, le tour s'arrête net) : on fournit donc toujours un message.
  - `permission: {"*": "ask", "question"|"todowrite"|"external_directory"|"doom_loop": "deny"}` :
    `*` = ask pour tout (lectures comprises) ; un outil « deny » disparaît du contexte du modèle.
  - Les outils MCP sont demandés sous `permission = "<serveur>_<outil>"`, `patterns = ["*"]`.
  - Le tool `task` exécute les sous-agents dans des sessions FILLES (`session.created` /
    `session.updated` avec `info.parentID` ; `metadata.sessionId` sur la partie `task`, vérifiés
    dans le schéma OpenAPI 1.18.32 et `tool/task.ts`) : leurs `permission.asked` (avec `"*": "ask"`)
    portent l'id de la session fille -> même politique ; leurs coûts comptent dans le tour.
  - `OPENCODE_CONFIG` charge notre fichier ; le config global `~/.config/opencode` est aussi lu
    -> on isole XDG_CONFIG_HOME/XDG_DATA_HOME/XDG_STATE_HOME/XDG_CACHE_HOME sous `.arc/chat/opencode/xdg`.
"""

from __future__ import annotations

import base64
import http.client
import json
import os
import queue
import re
import secrets
import shutil
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse

from arc_chat_backend import (SYSTEM_ADDENDUM, system_addendum, BackendError, ChatBackend, TurnContext,
                              resolve_workspace_path)
from arc_chat_tools import (REFUSAL_DENY, display_input, fs_list_input, gate, map_leanproxy,
                            parse_unified_diff, short, summarize_tool, usd_to_eur)

OPENCODE_TESTED_VERSION = "1.18.32"
DEFAULT_MODEL = "openrouter/deepseek/deepseek-v4.1-flash"
DEFAULT_API_KEY_ENV = "OPENROUTER_API_KEY"

HEALTH_TIMEOUT_S = 40.0
EVENT_IDLE_TIMEOUT_S = 120.0     # sans évènement UTILE (les `server.heartbeat` ne comptent pas)
SOCKET_TIMEOUT_S = 120.0         # lecture du flux SSE (le serveur émet un `server.heartbeat` régulier)
TURN_TIMEOUT_S = 1800.0          # durée maximale d'un tour (hors attente d'approbation), `[chat].turn_timeout_s`
HEARTBEAT_EVENTS = ("server.heartbeat", "server.connected")
ABORT_GRACE_S = 15.0

# Permissions refusées d'office (sans passer par la politique) : sans objet dans le chat.
ALWAYS_REJECT = ("question", "external_directory", "doom_loop", "todowrite", "todoread")

REFUSAL_UNRESOLVED = ("Refusé : l'appel d'outil à approuver est introuvable côté serveur "
                      "(entrée inconnue). Ne le réessaie pas ; explique-le simplement à l'athlète.")
BUDGET_NOTICE = "\n\nLe budget du jour est atteint : je m'arrête ici."


# ---------------------------------------------------------------------------
# Traduction des noms d'outils
# ---------------------------------------------------------------------------

# Toutes les cibles d'un patch : fichiers ajoutés / modifiés / supprimés ET destinations de
# renommage — un patch peut en toucher plusieurs, la politique doit les voir toutes.
_PATCH_FILE_RE = re.compile(r"^\*\*\* (?:(?:Add|Update|Delete) File|Move to): (.+)$", re.MULTILINE)


def canonical_tool(name: str, tool_input: Optional[dict], mcp_servers: Any = ()) -> tuple:
    """Nom d'outil OpenCode -> (nom canonique, entrée canonique)."""
    inp = dict(tool_input or {})
    if name == "read":
        return "fs.read", {"path": inp.get("filePath") or inp.get("path") or ""}
    if name in ("write", "edit", "multiedit", "patch", "apply_patch"):
        out = {k: v for k, v in inp.items() if k not in ("filePath", "path")}
        path = inp.get("filePath") or inp.get("path") or ""
        if isinstance(inp.get("patchText"), str):
            targets = [t.strip() for t in _PATCH_FILE_RE.findall(inp["patchText"])]
            # Patch sans aucune cible lisible : chemin vide → refus par la politique.
            out["paths"] = targets if targets else [""]
            path = path or (targets[0] if targets else "")
        out["path"] = path
        return "fs.write", out
    if name in ("glob", "grep", "list", "ls"):
        if name == "glob":   # `pattern` de glob = filtre de fichiers
            return "fs.list", fs_list_input(inp.get("path"), None, inp.get("pattern"))
        if name == "grep":   # `pattern` = regex ; `include` = filtre de fichiers
            return "fs.list", fs_list_input(inp.get("path"), inp.get("pattern"),
                                            inp.get("include") or inp.get("glob"))
        return "fs.list", fs_list_input(inp.get("path"))
    if name == "bash":
        return "shell", {"command": inp.get("command", "")}
    if name == "webfetch":
        return "web.fetch", {"url": inp.get("url", "")}
    if name in ("websearch", "codesearch"):
        return "web.search", {"query": inp.get("query", "")}
    if name == "task":
        return "task", {"agent": inp.get("subagent_type") or inp.get("agent") or ""}
    if name == "skill":
        return "skill", {"name": inp.get("name") or inp.get("skill") or ""}
    # MCP : « <serveur>_<outil> » — le plus long nom de serveur connu gagne.
    for server in sorted(mcp_servers, key=len, reverse=True):
        prefix = f"{server}_"
        if name.startswith(prefix) and len(name) > len(prefix):
            tool = name[len(prefix):]
            srv = str(server).lower()
            if srv.startswith("leanproxy"):
                mapped = map_leanproxy(tool, inp)
                if mapped:
                    return mapped
            return f"mcp:{srv}.{tool}", inp
    return f"other:{name}", inp


# ---------------------------------------------------------------------------
# Configuration OpenCode générée (clé fournisseur par référence `{env:VAR}`, jamais en clair)
# ---------------------------------------------------------------------------

def split_model(model: str) -> tuple:
    """« openrouter/deepseek/deepseek-v4.1-flash » -> (« openrouter », « deepseek/deepseek-v4.1-flash »)."""
    provider, _, model_id = (model or DEFAULT_MODEL).partition("/")
    if not model_id:
        raise BackendError(f"Modèle OpenCode invalide : {model!r} (attendu « fournisseur/modèle »).")
    return provider, model_id


def convert_mcp_servers(mcp_json: dict) -> dict:
    """Format `.mcp.json` (Claude/Copilot…) -> format OpenCode (`type: local`)."""
    out: dict = {}
    for name, spec in (mcp_json.get("mcpServers") or {}).items():
        if not isinstance(spec, dict):
            continue
        if spec.get("url"):
            out[name] = {"type": "remote", "url": spec["url"], "enabled": True}
            continue
        if not spec.get("command"):
            continue
        entry: dict = {"type": "local", "command": [spec["command"], *[str(a) for a in spec.get("args") or []]],
                       "enabled": True}
        if spec.get("env"):
            entry["environment"] = {str(k): str(v) for k, v in spec["env"].items()}
        out[name] = entry
    return out


def build_config(model: str, base_url: str, api_key_env: str, mcp: dict) -> dict:
    """Contenu de `opencode.json` : fournisseur, MCP, permissions « ask » partout."""
    provider_id, model_id = split_model(model)
    options: dict = {}
    if api_key_env:
        options["apiKey"] = "{env:%s}" % api_key_env   # substitué par OpenCode, jamais écrit en clair
    if base_url:
        provider = {"npm": "@ai-sdk/openai-compatible", "name": provider_id,
                    "options": {**options, "baseURL": base_url},
                    "models": {model_id: {"name": model_id}}}
    else:
        # OpenRouter & fournisseurs connus : le catalogue interne connaît la plupart des modèles ;
        # on déclare le nôtre au cas où il serait récent.
        provider = {"options": options, "models": {model_id: {}}}
    return {
        "$schema": "https://opencode.ai/config.json",
        "model": f"{provider_id}/{model_id}",
        "autoupdate": False,
        "share": "disabled",
        "provider": {provider_id: provider},
        "mcp": mcp,
        # `*` = ask : l'adaptateur reçoit CHAQUE demande de permission (lectures comprises) et
        # applique la politique du coach ; les outils sans objet disparaissent du contexte.
        "permission": {"*": "ask", "question": "deny", "todowrite": "deny",
                       "external_directory": "deny", "doom_loop": "deny"},
    }


def _is_loopback_url(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return host in ("localhost", "127.0.0.1", "::1") or host.endswith(".localhost")


# ---------------------------------------------------------------------------
# Adaptateur
# ---------------------------------------------------------------------------

class _Turn:
    """État d'un tour (partagé entre la boucle d'évènements et les threads de permission)."""

    def __init__(self, ctx: TurnContext):
        self.ctx = ctx
        self.lock = threading.Lock()
        # Même verrou : `with turn.lock` et `with turn.cond` s'excluent mutuellement.
        self.cond = threading.Condition(self.lock)
        # Permissions posées et pas encore répondues, par session ; et celles qui attendent
        # pour être REFUSÉES (voir `_send`).
        self.outstanding: dict = {}
        self.rejecting: dict = {}
        self.user_ids: set = set()
        self.text_seen: dict = {}          # partID -> nb de caractères déjà émis
        self.tools: dict = {}              # callID -> {"tool","input","name","started","ended"}
        self.verdicts: dict = {}           # callID -> "allow"|"deny"|"pending"
        self.step_parts: set = set()
        self.tokens = {"input": 0, "output": 0, "cache_read": 0}
        self.cost_usd = 0.0
        self.steps = 0
        self.pending = False
        self.started = False
        self.aborted = False
        # Signal PROPRE au tour, posé par `_abort` : les fils de permission refusent alors tout
        # nouvel appel. (`ctx.cancelled` reste réservé à l'annulation demandée par l'athlète : il
        # annulerait aussi les propositions en attente, qui doivent rester ouvertes.)
        self.abort_event = threading.Event()
        self.max_steps_hit = False
        self.workers: list = []
        self.root = ""                     # id de la session du tour
        self.children: set = set()         # sessions filles (sous-agents `task`), descendantes de root
        self.awaiting = 0                  # approbations en cours (le délai d'inactivité est suspendu)
        self.budget_hit = False
        self.abort_at: Optional[float] = None
        self.usage_emitted = False

    def known_sessions(self) -> set:
        return {self.root} | self.children


class OpenCodeBackend(ChatBackend):
    name = "opencode"

    def __init__(self, workspace: Path, config: dict):
        super().__init__(workspace, config)
        self._lock = threading.RLock()
        self._proc: Any = None
        self._base = ""
        self._password = ""
        self._mcp_names: set = set()

    # -- utilitaires de configuration ---------------------------------

    @property
    def _state_dir(self) -> Path:
        return self.workspace / ".arc" / "chat" / "opencode"

    def _model(self) -> str:
        return str(self.config.get("model") or DEFAULT_MODEL)

    def _api_key_env(self) -> str:
        return str(self.config.get("api_key_env") or DEFAULT_API_KEY_ENV)

    def _base_url(self) -> str:
        return str(self.config.get("base_url") or "").strip()

    def _binary(self) -> Optional[str]:
        return str(self.config.get("opencode_bin") or "") or shutil.which("opencode")

    def _need_key(self) -> bool:
        return not (self._base_url() and _is_loopback_url(self._base_url()))

    def _read_mcp(self) -> dict:
        """Entrées MCP d'OpenCode : `.mcp.json` du workspace, sinon config OpenCode de l'utilisateur."""
        mcp_path = self.workspace / ".mcp.json"
        try:
            servers = convert_mcp_servers(json.loads(mcp_path.read_text(encoding="utf-8")))
            if servers:
                return servers
        except (OSError, ValueError):
            pass
        home_cfg = Path(os.environ.get("HOME", "~")).expanduser() / ".config" / "opencode" / "opencode.json"
        try:
            found = json.loads(home_cfg.read_text(encoding="utf-8")).get("mcp") or {}
            return {k: v for k, v in found.items() if k in ("garmin", "intervals", "leanproxy")}
        except (OSError, ValueError):
            return {}

    def write_config(self) -> Path:
        """Écrit `.arc/chat/opencode/opencode.json` (mode 600) et renvoie son chemin.

        La clé du fournisseur reste une référence `{env:VAR}` ; en revanche les blocs `env`
        de `.mcp.json` sont recopiés TELS QUELS (ils peuvent contenir des identifiants des
        serveurs MCP) — d'où le mode 600.
        """
        mcp = self._read_mcp()
        self._mcp_names = set(mcp)
        cfg = build_config(self._model(), self._base_url(),
                           self._api_key_env() if self._need_key() else "", mcp)
        self._state_dir.mkdir(parents=True, exist_ok=True)
        path = self._state_dir / "opencode.json"
        fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(cfg, indent=2, ensure_ascii=False) + "\n")
        os.chmod(path, 0o600)   # fichier préexistant : os.open ne change pas son mode
        return path

    # -- vérifications ---------------------------------------------------

    def check(self) -> tuple:
        binary = self._binary()
        if not binary:
            return False, ("binaire opencode absent — installer OpenCode "
                           "(curl -fsSL https://opencode.ai/v2/install | bash, ou npm i -g opencode-ai)")
        try:
            out = subprocess.run([binary, "--version"], capture_output=True, text=True, timeout=15)
        except (OSError, subprocess.SubprocessError) as exc:
            return False, f"opencode inutilisable : {short(exc, 100)}"
        version = (out.stdout or out.stderr).strip().splitlines()[-1:] or ["?"]
        version = version[0].strip()
        if out.returncode != 0:
            return False, f"opencode --version a échoué ({short(version, 80)})"
        if self._need_key() and not os.environ.get(self._api_key_env(), "").strip():
            return False, f"clé API absente : variable {self._api_key_env()} vide"
        note = "" if version == OPENCODE_TESTED_VERSION else f" (testé avec {OPENCODE_TESTED_VERSION})"
        return True, f"opencode {version}{note}"

    # -- supervision du serveur -------------------------------------------

    @staticmethod
    def _pick_port() -> int:
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            return s.getsockname()[1]

    @staticmethod
    def _spawn(cmd: list, env: dict, cwd: str, log_path: str) -> Any:
        log = open(log_path, "ab")  # noqa: SIM115 — hérité par le processus enfant
        return subprocess.Popen(cmd, cwd=cwd, env=env, stdin=subprocess.DEVNULL, stdout=log,
                                stderr=subprocess.STDOUT)

    def _auth_headers(self) -> dict:
        token = base64.b64encode(f"opencode:{self._password}".encode()).decode()
        return {"Authorization": f"Basic {token}"}

    def _healthy(self) -> bool:
        if not self._base:
            return False
        try:
            body = self._request("GET", "/global/health", timeout=3)
            return bool(isinstance(body, dict) and body.get("healthy"))
        except BackendError:
            return False

    def _ensure_server(self) -> None:
        with self._lock:
            if self._proc is not None and self._proc.poll() is None and self._healthy():
                return
            self._stop_locked()
            binary = self._binary()
            if not binary:
                raise BackendError("OpenCode n'est pas installé (binaire « opencode » introuvable).")
            if self._need_key() and not os.environ.get(self._api_key_env(), "").strip():
                raise BackendError(f"Clé API du fournisseur absente : la variable {self._api_key_env()} "
                                   "est vide (voir ~/.config/ai-running-coach/llm.env).")
            cfg_path = self.write_config()
            xdg = self._state_dir / "xdg"
            env = dict(os.environ)
            for var, sub in (("XDG_CONFIG_HOME", "config"), ("XDG_DATA_HOME", "data"),
                             ("XDG_STATE_HOME", "state"), ("XDG_CACHE_HOME", "cache")):
                (xdg / sub).mkdir(parents=True, exist_ok=True)
                env[var] = str(xdg / sub)
            self._password = secrets.token_urlsafe(24)
            env.update({"OPENCODE_CONFIG": str(cfg_path), "OPENCODE_SERVER_PASSWORD": self._password})
            if self._need_key():
                env[self._api_key_env()] = os.environ[self._api_key_env()]
            port = self._pick_port()
            self._base = f"http://127.0.0.1:{port}"
            cmd = [binary, "serve", "--pure", "--hostname", "127.0.0.1", "--port", str(port)]
            self._reap_stale()
            try:
                self._proc = self._spawn(cmd, env, str(self.workspace), str(self._state_dir / "server.log"))
            except OSError as exc:
                raise BackendError(f"Impossible de démarrer OpenCode : {short(exc, 120)}") from exc
            try:
                (self._state_dir / "server.pid").write_text(str(self._proc.pid), encoding="utf-8")
            except (OSError, AttributeError):
                pass
            deadline = time.monotonic() + HEALTH_TIMEOUT_S
            while time.monotonic() < deadline:
                if self._proc.poll() is not None:
                    self._stop_locked()
                    raise BackendError("Le serveur OpenCode s'est arrêté au démarrage "
                                       "(voir .arc/chat/opencode/server.log).")
                if self._healthy():
                    return
                time.sleep(0.25)
            self._stop_locked()
            raise BackendError("Le serveur OpenCode ne répond pas (délai de démarrage dépassé).")

    def _reap_stale(self) -> None:
        """Serveur laissé par un service tué sans nettoyage (SIGKILL, plantage) : on l'arrête.

        Seulement si le PID noté appartient encore à un `opencode serve` — jamais un autre
        processus qui aurait récupéré ce numéro.
        """
        pid_file = self._state_dir / "server.pid"
        try:
            pid = int(pid_file.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            return
        try:
            out = subprocess.run(["ps", "-p", str(pid), "-o", "command="], capture_output=True,
                                 text=True, timeout=5).stdout
        except (OSError, subprocess.SubprocessError):
            out = ""
        if "opencode" in out and " serve" in out and "--hostname 127.0.0.1" in out:
            try:
                os.kill(pid, 15)
            except OSError:
                pass
        try:
            pid_file.unlink()
        except OSError:
            pass

    def _stop_locked(self) -> None:
        proc, self._proc = self._proc, None
        self._base = ""
        try:
            (self._state_dir / "server.pid").unlink()
        except (OSError, AttributeError):
            pass
        if proc is None:
            return
        try:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except Exception:  # noqa: BLE001
                    proc.kill()
        except Exception:  # noqa: BLE001
            pass

    def shutdown(self) -> None:
        with self._lock:
            self._stop_locked()

    # -- HTTP --------------------------------------------------------------

    def _request(self, method: str, path: str, body: Any = None, timeout: float = 30) -> Any:
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(self._base + path, data=data, method=method,
                                     headers={"Content-Type": "application/json", **self._auth_headers()})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read()
        except urllib.error.HTTPError as exc:
            body_text = exc.read().decode("utf-8", "replace")[:300]
            exc.close()
            raise _HttpError(exc.code, body_text) from exc
        except (urllib.error.URLError, OSError) as exc:
            raise BackendError("Le serveur OpenCode est injoignable.") from exc
        if not raw:
            return None
        try:
            return json.loads(raw)
        except ValueError:
            return raw.decode("utf-8", "replace")

    def _open_events(self) -> "queue.Queue":
        """Ouvre `GET /event` dans un thread ; renvoie la file d'évènements (None = flux coupé).

        `http.client` plutôt qu'urllib : il faut pouvoir couper la socket depuis un autre
        thread (`q.stop()`), `close()` bloquerait tant que le lecteur attend une ligne.
        """
        q: queue.Queue = queue.Queue()
        parsed = urlparse(self._base)
        conn = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=SOCKET_TIMEOUT_S)
        try:
            conn.request("GET", "/event", headers=self._auth_headers())
            resp = conn.getresponse()
        except (http.client.HTTPException, OSError) as exc:
            conn.close()
            raise BackendError("Le flux d'évènements OpenCode est injoignable.") from exc
        if resp.status != 200:
            conn.close()
            raise BackendError(f"Le flux d'évènements OpenCode a refusé la connexion ({resp.status}).")

        def stop() -> None:
            try:
                if conn.sock is not None:
                    conn.sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass

        # Dépannage : `ARC_OPENCODE_TRACE=<fichier>` y recopie chaque évènement brut d'OpenCode
        # (contenu des échanges compris : à réserver au diagnostic, fichier à supprimer ensuite).
        trace_path = os.environ.get("ARC_OPENCODE_TRACE", "").strip()

        def reader() -> None:
            trace = open(trace_path, "a", encoding="utf-8") if trace_path else None  # noqa: SIM115
            try:
                for raw in resp:
                    line = raw.decode("utf-8", "replace").strip()
                    if trace and line.startswith("data:"):
                        trace.write(line[5:].strip() + "\n")
                        trace.flush()
                    if line.startswith("data:"):
                        try:
                            q.put(json.loads(line[5:].strip()))
                        except ValueError:
                            continue
            except Exception:  # noqa: BLE001 — flux coupé
                pass
            finally:
                if trace:
                    trace.close()
                q.put(None)
                try:
                    conn.close()
                except Exception:  # noqa: BLE001
                    pass

        threading.Thread(target=reader, name="opencode-events", daemon=True).start()
        q.stop = stop  # type: ignore[attr-defined]
        return q

    # -- session -----------------------------------------------------------

    def _session_id(self, ctx: TurnContext) -> str:
        sid = ctx.backend_state.get("opencode_session_id")
        if sid:
            try:
                self._request("GET", f"/session/{sid}")
                return sid
            except _HttpError as exc:
                if exc.status != 404:
                    raise BackendError(f"OpenCode a refusé la session ({exc.status}).") from exc
        created = self._request("POST", "/session", {"title": f"chat {ctx.session_id}"})
        sid = (created or {}).get("id") if isinstance(created, dict) else None
        if not sid:
            raise BackendError("OpenCode n'a pas créé de session.")
        ctx.backend_state["opencode_session_id"] = sid
        return sid

    # -- tour --------------------------------------------------------------

    def run_turn(self, ctx: TurnContext, user_message: str) -> None:
        self._ensure_server()
        provider_id, model_id = split_model(self._model())
        sid = self._session_id(ctx)
        turn = _Turn(ctx)
        turn.root = sid
        events = self._open_events()
        try:
            # Attendre `server.connected` : aucun évènement du tour ne doit être manqué.
            self._wait_connected(events)
            self._request("POST", f"/session/{sid}/prompt_async", {
                "parts": [{"type": "text", "text": user_message}],
                "system": system_addendum(ctx.language),
                "model": {"providerID": provider_id, "modelID": model_id},
            })
            self._consume(sid, turn, events)
        except BackendError:
            self._emit_usage(turn, only_if_known=True)   # coût partiel du tour interrompu
            raise
        finally:
            events.stop()  # type: ignore[attr-defined]
            for worker in turn.workers:
                worker.join(timeout=2)
        self._finish(turn)

    @staticmethod
    def _wait_connected(events: "queue.Queue") -> None:
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            try:
                event = events.get(timeout=0.5)
            except queue.Empty:
                continue
            if event is None:
                raise BackendError("Le flux d'évènements OpenCode s'est fermé.")
            if event.get("type") == "server.connected":
                return
        raise BackendError("Le flux d'évènements OpenCode ne s'est pas ouvert.")

    def _abort(self, sid: str, turn: _Turn) -> None:
        """Interrompt la session du tour (et ses sessions filles, au mieux)."""
        turn.aborted = True
        turn.abort_event.set()
        turn.abort_at = time.monotonic()
        for target in [sid, *sorted(turn.children)]:
            try:
                self._request("POST", f"/session/{target}/abort", timeout=10)
            except BackendError:
                pass

    def _turn_cost_eur(self, turn: _Turn) -> float:
        return usd_to_eur(turn.cost_usd, turn.ctx.config.get("usd_eur_rate"))

    def _adopt_if_child(self, sid: str, turn: _Turn, candidate: str) -> bool:
        """Session inconnue qui demande une permission : fille de la nôtre ? (GET /session/{id})."""
        try:
            info = self._request("GET", f"/session/{candidate}", timeout=5)
        except BackendError:
            return False
        parent = (info or {}).get("parentID") if isinstance(info, dict) else None
        if parent and parent in turn.known_sessions():
            turn.children.add(candidate)
            return True
        return False

    def _consume(self, sid: str, turn: _Turn, events: "queue.Queue") -> None:
        ctx = turn.ctx
        started = last_event = last_tick = time.monotonic()
        paused = 0.0
        max_steps = int(ctx.config.get("max_turns") or 0)
        try:
            turn_timeout = float(ctx.config.get("turn_timeout_s") or TURN_TIMEOUT_S)
        except (TypeError, ValueError):
            turn_timeout = TURN_TIMEOUT_S
        try:
            cap_eur: Optional[float] = float(ctx.config["turn_budget_eur"])
        except (KeyError, TypeError, ValueError):
            cap_eur = None
        while True:
            now = time.monotonic()
            if turn.awaiting:   # attente d'approbation : ni inactivité ni durée ne courent
                paused += now - last_tick
                last_event = now
            last_tick = now
            if ctx.cancelled.is_set() and not turn.aborted:
                self._abort(sid, turn)
            if turn.abort_at is not None and now - turn.abort_at > ABORT_GRACE_S:
                return
            if self._proc is not None and self._proc.poll() is not None:
                raise BackendError("Le serveur OpenCode s'est arrêté pendant le tour.")
            if not turn.aborted and now - started - paused > turn_timeout:
                self._abort(sid, turn)
                raise BackendError("Le tour a dépassé la durée maximale autorisée : il a été interrompu.")
            if now - last_event > EVENT_IDLE_TIMEOUT_S:   # vérifié à CHAQUE tour de boucle (battements compris)
                raise BackendError("Le serveur OpenCode ne répond plus (aucun évènement).")
            try:
                event = events.get(timeout=0.2)
            except queue.Empty:
                continue
            if event is None:
                if turn.aborted:
                    return
                raise BackendError("Le flux d'évènements OpenCode s'est interrompu.")
            etype = event.get("type", "")
            if etype not in HEARTBEAT_EVENTS:   # les battements de cœur ne prouvent pas que le tour avance
                last_event = time.monotonic()
            props = event.get("properties") or {}
            # Sous-agents : le tool `task` ouvre des sessions FILLES ; leurs permissions doivent
            # passer par la même politique, sinon le tour reste bloqué.
            if etype in ("session.created", "session.updated"):
                info = props.get("info") or {}
                if info.get("id") and info.get("parentID") in turn.known_sessions():
                    turn.children.add(info["id"])
                continue
            esid = props.get("sessionID")
            child = esid is not None and esid != sid and esid in turn.children
            if esid not in (None, sid) and not child:
                if etype == "permission.asked" and self._adopt_if_child(sid, turn, esid):
                    child = True
                else:
                    continue
            if etype == "message.updated":
                if not child:
                    self._on_message(turn, props.get("info") or {})
            elif etype == "message.part.updated":
                self._on_part(esid or sid, turn, props.get("part") or {}, child)
                if cap_eur is not None and not turn.aborted and self._turn_cost_eur(turn) > cap_eur:
                    turn.budget_hit = True
                    self._abort(sid, turn)
                elif max_steps and turn.steps >= max_steps and not turn.aborted:
                    turn.max_steps_hit = True
                    self._abort(sid, turn)
            elif etype == "message.part.delta":
                if not child:
                    self._on_delta(turn, props)
            elif etype == "permission.asked":
                with turn.lock:
                    turn.awaiting += 1
                    turn.outstanding.setdefault(esid or sid, set()).add(props.get("id", ""))
                worker = threading.Thread(target=self._answer_permission_guarded,
                                          args=(esid or sid, turn, props),
                                          name="opencode-permission", daemon=True)
                turn.workers.append(worker)
                worker.start()
            elif etype == "session.status" and (props.get("status") or {}).get("type") == "retry":
                # Fournisseur saturé ou injoignable : OpenCode réessaie seul, parfois pendant des
                # minutes — on le dit à l'athlète au lieu de laisser une page muette.
                info = props.get("status") or {}
                reason = str(info.get("message") or "").strip()
                short = "fournisseur saturé" if re.search(r"rate.?limit|429|overloaded", reason, re.I) \
                    else "fournisseur injoignable" if re.search(r"connect|network|timeout", reason, re.I) \
                    else "réponse du fournisseur en échec"
                attempt = info.get("attempt")
                turn.ctx.emit("status", {"message": f"{short.capitalize()} — nouvelle tentative"
                                               + (f" n°{attempt}" if isinstance(attempt, int) and attempt else "")
                                               + "…"})
            elif child:
                continue
            elif etype == "session.status":
                status = (props.get("status") or {}).get("type")
                if status == "busy":
                    turn.started = True
                elif status == "idle" and turn.started:
                    return
            elif etype == "session.idle":
                if turn.started:
                    return
            elif etype == "session.error":
                if turn.aborted:
                    continue
                raise BackendError(self._translate_error(props.get("error") or {}))

    # -- évènements ----------------------------------------------------

    def _on_message(self, turn: _Turn, info: dict) -> None:
        if info.get("role") == "user":
            turn.user_ids.add(info.get("id"))
        elif info.get("role") == "assistant":
            turn.started = True
            error = info.get("error")
            if error and not turn.aborted and not (error.get("name") == "MessageAbortedError"):
                raise BackendError(self._translate_error(error))

    def _on_delta(self, turn: _Turn, props: dict) -> None:
        if props.get("field") != "text" or props.get("messageID") in turn.user_ids:
            return
        text = props.get("delta") or ""
        if not text:
            return
        pid = props.get("partID")
        turn.text_seen[pid] = turn.text_seen.get(pid, 0) + len(text)
        turn.ctx.emit("text_delta", {"text": text, "part": pid or ""})

    @staticmethod
    def _key(turn: _Turn, sid: str, call_id: str) -> str:
        """Identifiant d'appel unique du tour : les appels des sous-agents portent l'id de leur session."""
        return call_id if sid == turn.root else f"{sid}:{call_id}"

    def _on_part(self, sid: str, turn: _Turn, part: dict, child: bool = False) -> None:
        ptype = part.get("type")
        if not child and part.get("messageID") in turn.user_ids:
            return
        if ptype == "text":
            if child or part.get("synthetic") or part.get("ignored"):
                return  # texte interne d'un sous-agent : non affiché
            text = part.get("text") or ""
            seen = turn.text_seen.get(part.get("id"), 0)
            if len(text) > seen:
                turn.text_seen[part["id"]] = len(text)
                turn.ctx.emit("text_delta", {"text": text[seen:], "part": part.get("id") or ""})
        elif ptype == "tool":
            self._on_tool(sid, turn, part, child)
        elif ptype == "step-finish":
            pid = part.get("id")
            if pid in turn.step_parts:
                return
            turn.step_parts.add(pid)
            if not child:
                turn.steps += 1
            tokens = part.get("tokens") or {}
            turn.tokens["input"] += int(tokens.get("input") or 0)
            turn.tokens["output"] += int(tokens.get("output") or 0)
            turn.tokens["cache_read"] += int((tokens.get("cache") or {}).get("read") or 0)
            turn.cost_usd += float(part.get("cost") or 0.0)

    def _on_tool(self, sid: str, turn: _Turn, part: dict, child: bool = False) -> None:
        raw_id = part.get("callID") or part.get("id")
        call_id = self._key(turn, sid, raw_id)
        state = part.get("state") or {}
        status = state.get("status")
        name = part.get("tool", "")
        if name == "task":   # `metadata.sessionId` = session fille créée par le tool `task`
            meta = state.get("metadata") or part.get("metadata") or {}
            if isinstance(meta, dict) and meta.get("sessionId"):
                turn.children.add(meta["sessionId"])
        with turn.lock:
            rec = turn.tools.setdefault(call_id, {"name": name, "input": {}, "started": False, "ended": False,
                                                  "child": child})
            if state.get("input"):
                rec["input"] = state["input"]
            if status in ("running", "completed", "error") and "input" in state:
                rec["input_known"] = True
        if status in ("running", "completed", "error"):
            self._ensure_started(turn, call_id)
        if status in ("completed", "error") and not rec["ended"]:
            rec["ended"] = True
            ok = status == "completed"
            verdict = turn.verdicts.get(call_id)
            if ok:
                summary = "Terminé"
            elif verdict == "deny":
                summary = "Refusé"
            elif verdict == "pending":
                summary = "En attente de confirmation"
            else:
                summary = "Échec : " + short(state.get("error"), 60) if state.get("error") else "Échec"
            turn.ctx.emit("tool_end", {"id": call_id, "ok": ok, "summary": summary})
            if ok and rec.get("tool") == "fs.write":
                cinput = rec.get("cinput") or {}
                targets = cinput.get("paths") or [cinput.get("path")]
                for rel in dict.fromkeys(resolve_workspace_path(self.workspace, t) for t in targets):
                    if rel:
                        turn.ctx.emit("file_written", {"path": rel})

    def _ensure_started(self, turn: _Turn, call_id: str, name: str = "", inp: Optional[dict] = None,
                        child: bool = False) -> None:
        """Émet `tool_start` une seule fois par appel (depuis la boucle d'évènements OU le thread de permission)."""
        with turn.lock:
            rec = turn.tools.setdefault(call_id, {"name": name, "input": {}, "started": False, "ended": False,
                                                  "child": child})
            if name and not rec["name"]:
                rec["name"] = name
            if inp and not rec["input"]:
                rec["input"] = inp
            if rec["started"]:
                return
            rec["started"] = True
            tool, cinput = canonical_tool(rec["name"], rec["input"], self._mcp_names)
            rec["tool"], rec["cinput"] = tool, cinput
            prefix = "Sous-agent · " if rec.get("child") else ""
        turn.ctx.emit("tool_start", {"id": call_id, "name": tool,
                                     "summary": prefix + summarize_tool(
                                         tool, display_input(self.workspace, tool, cinput))})

    # -- permissions ---------------------------------------------------

    def _lookup_tool_part(self, sid: str, message_id: str, call_id: str) -> Optional[dict]:
        try:
            msg = self._request("GET", f"/session/{sid}/message/{message_id}", timeout=10)
        except BackendError:
            return None
        for part in (msg or {}).get("parts", []) if isinstance(msg, dict) else []:
            if part.get("type") == "tool" and part.get("callID") == call_id:
                return part
        return None

    def _reply(self, sid: str, request_id: str, allow: bool, message: str) -> None:
        body: dict = {"reply": "once"} if allow else {"reply": "reject", "message": message}
        try:
            self._request("POST", f"/permission/{request_id}/reply", body, timeout=15)
        except _HttpError as exc:
            if exc.status not in (404, 405):
                raise BackendError(f"OpenCode a refusé la réponse de permission ({exc.status}).") from exc
            # Anciennes versions : `POST /session/{id}/permissions/{id}` {response}.
            # À VÉRIFIER : non testé (absent de 1.18.32 en dehors de l'alias déprécié).
            legacy = {"response": "once" if allow else "reject"}
            self._request("POST", f"/session/{sid}/permissions/{request_id}", legacy, timeout=15)

    def _send(self, turn: _Turn, sid: str, request_id: str, allow: bool, message: str) -> None:
        """Répond à une permission ; un REFUS attend d'abord les autres réponses de la session.

        OpenCode (`permission/index.ts`) : un « reject » refuse aussi TOUTES les autres
        permissions en attente de la même session, et celles-là sans message — ce qui arrête
        le tour (et annule la tâche d'un sous-agent). Quand le modèle lance plusieurs outils en
        parallèle et qu'un seul est refusé par la politique, les autorisations partent donc en
        premier, le refus ensuite. Limite connue : deux refus simultanés dans la même session
        arrêtent quand même le tour (le second est emporté sans message).
        """
        if not allow:
            hold = float(turn.ctx.config.get("approval_wait_s", 600) or 600) + 60.0
            deadline = time.monotonic() + hold
            with turn.cond:
                turn.rejecting.setdefault(sid, set()).add(request_id)
                while not (turn.abort_event.is_set() or turn.ctx.cancelled.is_set()):
                    others = turn.outstanding.get(sid, set()) - turn.rejecting.get(sid, set())
                    left = deadline - time.monotonic()
                    if not others or left <= 0:
                        break
                    turn.cond.wait(min(left, 0.5))
        try:
            self._reply(sid, request_id, allow, message)
        finally:
            with turn.cond:
                turn.outstanding.get(sid, set()).discard(request_id)
                turn.rejecting.get(sid, set()).discard(request_id)
                turn.cond.notify_all()

    def _answer_permission_guarded(self, sid: str, turn: _Turn, props: dict) -> None:
        try:
            self._answer_permission(sid, turn, props)
        finally:
            with turn.lock:
                turn.awaiting -= 1

    def _answer_permission(self, sid: str, turn: _Turn, props: dict) -> None:
        """Répond à une permission de la session `sid` (celle du tour OU une session fille)."""
        ctx = turn.ctx
        request_id = props.get("id", "")
        permission = props.get("permission", "")
        tool_ref = props.get("tool") or {}
        raw_call = tool_ref.get("callID") or ""
        call_id = self._key(turn, sid, raw_call) if raw_call else ""
        child = sid != turn.root
        try:
            if permission in ALWAYS_REJECT or ctx.cancelled.is_set() or turn.abort_event.is_set():
                self._send(turn, sid, request_id, False, REFUSAL_DENY)
                return
            with turn.lock:
                rec = turn.tools.get(call_id) if call_id else None
            inp = dict(rec["input"]) if rec and rec.get("input") else {}
            name = rec["name"] if rec else ""
            known = bool(rec and (rec.get("input_known") or rec.get("input")))
            if not known and raw_call:
                part = self._lookup_tool_part(sid, tool_ref.get("messageID", ""), raw_call)
                if part:
                    name = part.get("tool", name)
                    pstate = part.get("state") or {}
                    inp = dict(pstate.get("input") or {})
                    known = bool(inp) or pstate.get("status") in ("running", "completed", "error")
            metadata = props.get("metadata") or {}
            if not name:
                name = permission
            if not inp and metadata.get("filepath"):
                inp = {"filePath": metadata["filepath"]}
                known = True
            if not known:
                # Entrée introuvable : ne JAMAIS laisser passer un appel non résolu (une reprise
                # d'approbation pré-approuverait sinon n'importe quoi avec `{}`).
                self._send(turn, sid, request_id, False, REFUSAL_UNRESOLVED)
                return
            tool, cinput = canonical_tool(name, inp, self._mcp_names)
            if call_id:
                self._ensure_started(turn, call_id, name, inp, child)
            diff = parse_unified_diff(metadata["diff"]) if metadata.get("diff") and tool == "fs.write" else None
            decision, message = gate(ctx, tool, cinput, diff)
            if call_id:
                turn.verdicts[call_id] = decision
            if decision == "pending":
                turn.pending = True
            self._send(turn, sid, request_id, decision == "allow", message or REFUSAL_DENY)
        except BackendError:
            # Réponse impossible : le tour ne peut plus avancer, on l'interrompt proprement.
            ctx.cancelled.set()
        except Exception:  # noqa: BLE001 — jamais laisser l'outil en attente
            try:
                self._send(turn, sid, request_id, False, REFUSAL_DENY)
            except Exception:  # noqa: BLE001
                ctx.cancelled.set()

    # -- fin de tour -----------------------------------------------------

    @staticmethod
    def _translate_error(error: dict) -> str:
        name = str(error.get("name", ""))
        data = error.get("data") or {}
        message = str(data.get("message") or error.get("message") or "")
        status = data.get("statusCode")
        low = message.lower()
        if name == "ProviderAuthError" or status == 401 or "401" in low or "invalid api key" in low \
                or "unauthorized" in low:
            return "Clé API du fournisseur refusée (401) : vérifier la clé dans llm.env."
        if status == 402 or "402" in low or "insufficient" in low or "credit" in low:
            return "Crédit du fournisseur insuffisant (402)."
        if status == 429 or "rate limit" in low:
            return "Limite de débit du fournisseur atteinte : réessaie dans un instant."
        if name in ("ContextOverflowError",):
            return "La conversation est trop longue pour ce modèle : démarre une nouvelle session."
        if any(w in low for w in ("connect", "unreachable", "enotfound", "econnrefused", "timeout")):
            return "Fournisseur injoignable : vérifier la connexion et l'URL du fournisseur."
        return f"Erreur du fournisseur : {short(message or name or 'inconnue', 200)}"

    def _emit_usage(self, turn: _Turn, only_if_known: bool = False) -> None:
        """Émet `usage` une seule fois (sessions fille comprises) ; `only_if_known` : pas de zéros."""
        if turn.usage_emitted:
            return
        if only_if_known and not (turn.cost_usd or any(turn.tokens.values())):
            return
        turn.usage_emitted = True
        turn.ctx.emit("usage", {
            "input_tokens": turn.tokens["input"],
            "output_tokens": turn.tokens["output"],
            "cache_read_tokens": turn.tokens["cache_read"],
            "cost_eur": self._turn_cost_eur(turn),
        })

    def _finish(self, turn: _Turn) -> None:
        ctx = turn.ctx
        self._emit_usage(turn)
        if turn.budget_hit:
            ctx.emit("text_delta", {"text": BUDGET_NOTICE})
            reason = "budget"
        elif turn.max_steps_hit:
            reason = "max_turns"
        elif ctx.cancelled.is_set():
            reason = "interrupted"
        elif turn.pending:
            reason = "pending_approval"
        else:
            reason = "end_turn"
        ctx.emit("done", {"reason": reason})


class _HttpError(BackendError):
    """Réponse HTTP d'erreur du serveur OpenCode (sous-classe : les appelants génériques la traitent)."""

    def __init__(self, status: int, body: str):
        super().__init__(f"HTTP {status}: {body}")
        self.status = status
        self.body = body
