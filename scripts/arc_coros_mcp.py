#!/usr/bin/env python3
"""Relais MCP stdio → MCP officiel COROS, avec les jetons du projet (`arc_coros_auth.py`).

Déclaré par `install.sh --coros` dans la config de chaque client d'IA (Claude Code, Copilot,
Cursor, OpenCode…), comme `garmin-mcp stdio` pour Garmin : le client lance ce programme local,
qui transmet chaque message JSON-RPC au serveur HTTP de COROS en ajoutant le jeton. L'athlète
ne se connecte donc qu'une fois (`arc_coros_auth.py login`), le client d'IA ne fait aucune
connexion OAuth, et un seul propriétaire rafraîchit les jetons (sous verrou).

Le relais ne réécrit rien : mêmes outils, mêmes réponses. Il ne fait que filtrer :
- `COROS_ENABLED_TOOLS` (liste séparée par des virgules) : seuls ces outils sont listés et
  appelables — l'équivalent de `GARMIN_ENABLED_TOOLS` ;
- `COROS_READ_ONLY=1`, ou `ARC_HEADLESS=1` (exporté par `scripts/daily-sync.sh`, hérité par
  l'exécuteur puis par ce relais) : les outils d'écriture sont retirés, quelle que soit la
  liste blanche — aucune écriture COROS sans personne pour confirmer, quel que soit
  l'exécuteur de la synchronisation.

Un 401 déclenche un rafraîchissement puis un seul nouvel essai ; une session expirée
(404 avec `Mcp-Session-Id`) est rouverte en rejouant l'`initialize` du client.
Journal sur stderr, jamais de jeton. Bibliothèque standard seule (Python 3.9).
"""

from __future__ import annotations

import json
import os
import sys
from typing import Callable, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import arc_coros_auth as auth  # noqa: E402

# Outils qui écrivent sur le compte COROS (liste relevée le 22 octobre 2026, docs/coros.md).
WRITE_TOOLS = frozenset({
    "createScheduledWorkout", "updateScheduledWorkout", "scheduleWorkout",
    "createSingleWorkout", "updateWorkoutDetails", "createTrainingPlan", "updateTrainingPlan",
})

PostFn = Callable[..., Tuple[int, dict, str]]
# Toute erreur de `arc_coros_auth.py` qui exige une action de l'athlète porte cette commande.
LOGIN_HINT = "arc_coros_auth.py login"


def _log(msg: str) -> None:
    print(f"[arc_coros_mcp] {msg}", file=sys.stderr, flush=True)


def allowed_tools(env=None) -> Tuple[Optional[frozenset], bool]:
    env = os.environ if env is None else env
    raw = env.get("COROS_ENABLED_TOOLS", "").strip()
    allow = frozenset(t.strip() for t in raw.split(",") if t.strip()) if raw else None
    truthy = ("1", "true", "yes")
    read_only = (env.get("COROS_READ_ONLY", "").strip().lower() in truthy
                 or env.get("ARC_HEADLESS", "").strip().lower() in truthy)
    return allow, read_only


def tool_permitted(name: str, allow: Optional[frozenset], read_only: bool) -> bool:
    if read_only and name in WRITE_TOOLS:
        return False
    return allow is None or name in allow


def _error(msg_id, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message}}


class Relay:
    def __init__(self, post: PostFn = auth.http_post, token: Callable[..., str] = auth.access_token,
                 url: Optional[str] = None, env=None):
        self.post, self.token = post, token
        self.url = url or auth.mcp_url()
        self.allow, self.read_only = allowed_tools(env)
        self.session: Optional[str] = None
        self.protocol: Optional[str] = None
        self.init_msg: Optional[dict] = None

    def _send(self, msg: dict, token: str) -> Tuple[int, dict, str]:
        headers = {"Authorization": f"Bearer {token}", "Accept": "application/json, text/event-stream"}
        if self.session:
            headers["Mcp-Session-Id"] = self.session
        if self.protocol:
            headers["MCP-Protocol-Version"] = self.protocol
        return self.post(self.url, body=msg, headers=headers)

    def _forward(self, msg: dict) -> Tuple[int, dict, str]:
        token = self.token()
        status, hdrs, text = self._send(msg, token)
        if status == 401:
            _log("jeton refusé : rafraîchissement")
            status, hdrs, text = self._send(msg, self.token(rejected=token))
        elif status == 404 and self.session and self.init_msg and msg is not self.init_msg:
            _log("session expirée : réouverture")
            self.session = None
            self.handle(self.init_msg)
            self._send({"jsonrpc": "2.0", "method": "notifications/initialized"}, self.token())
            status, hdrs, text = self._send(msg, self.token())
        return status, hdrs, text

    def handle(self, msg: dict) -> List[dict]:
        """Un message du client → les messages à lui renvoyer (vide pour une notification)."""
        method, msg_id = msg.get("method"), msg.get("id")
        if method == "tools/call":
            name = (msg.get("params") or {}).get("name", "")
            if not tool_permitted(name, self.allow, self.read_only):
                return [_error(msg_id, -32601, f"outil COROS non autorisé par cette installation : {name}")]
        if method == "initialize":
            self.init_msg = msg
        try:
            status, hdrs, text = self._forward(msg)
        except auth.CorosAuthError as e:
            if msg_id is None:
                return []
            err = _error(msg_id, -32000, f"COROS : {e}")
            # Connexion à refaire par l'athlète (absente, rafraîchissement refusé) : signalé à part
            # pour les appelants sans IA (garmin_watch.py), qui ne doivent pas insister.
            err["error"]["data"] = {"login_required": LOGIN_HINT in str(e)}
            return [err]
        if hdrs.get("mcp-session-id"):
            self.session = hdrs["mcp-session-id"]
        if status in (202, 204) or msg_id is None:
            return []
        if status != 200:
            return [_error(msg_id, -32000, f"COROS : HTTP {status}")]
        try:
            out = auth.parse_mcp_body(text)
        except ValueError:
            return [_error(msg_id, -32700, "COROS : réponse illisible")]
        for m in out:
            result = m.get("result") if isinstance(m, dict) else None
            if not isinstance(result, dict):
                continue
            if method == "initialize" and result.get("protocolVersion"):
                self.protocol = result["protocolVersion"]
            if method == "tools/list" and isinstance(result.get("tools"), list):
                result["tools"] = [t for t in result["tools"]
                                   if tool_permitted(t.get("name", ""), self.allow, self.read_only)]
        return out


def _plain(text: str) -> str:
    """COROS rend son texte encodé en chaîne JSON (« "Sport Records…\\n…" », constaté le 23/10/2026) :
    décodé une fois ; tout autre texte est rendu tel quel."""
    stripped = text.strip()
    if len(stripped) >= 2 and stripped[0] == stripped[-1] == '"':
        try:
            decoded = json.loads(stripped)
        except ValueError:
            return text
        if isinstance(decoded, str):
            return decoded
    return text


class CallError(RuntimeError):
    """Appel d'outil COROS en échec. `login_required` : la connexion du projet est à refaire."""

    def __init__(self, message: str, login_required: bool = False):
        super().__init__(message)
        self.login_required = login_required


class Client:
    """Appels d'outils COROS SANS client d'IA (download_fit.py, garmin_watch.py) : le même relais,
    donc les mêmes jetons, le même filtrage (lecture seule en headless) et la même reprise sur 401."""

    def __init__(self, relay: Optional[Relay] = None, name: str = "ai-running-coach"):
        self.relay = relay or Relay()
        self.name = name
        self._next_id = 1
        self._ready = False

    def _id(self) -> int:
        self._next_id += 1
        return self._next_id

    def _open(self) -> None:
        if self._ready:
            return
        out = self.relay.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                                 "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                                            "clientInfo": {"name": self.name, "version": "1"}}})
        self._raise_on_error(out, 1, "initialize")
        self.relay.handle({"jsonrpc": "2.0", "method": "notifications/initialized"})
        self._ready = True

    @staticmethod
    def _raise_on_error(out: List[dict], msg_id: int, what: str) -> Optional[dict]:
        msg = next((m for m in out if isinstance(m, dict) and m.get("id") == msg_id), None)
        if msg is None:
            raise CallError(f"MCP COROS : aucune réponse à {what}")
        if "error" in msg:
            error = msg.get("error") or {}
            data = error.get("data") if isinstance(error.get("data"), dict) else {}
            raise CallError(str(error.get("message") or "erreur inconnue"), bool(data.get("login_required")))
        return msg

    def call(self, tool: str, arguments: Optional[dict] = None) -> str:
        """Texte de la réponse de l'outil `tool` ; `CallError` si l'appel échoue."""
        self._open()
        msg_id = self._id()
        out = self.relay.handle({"jsonrpc": "2.0", "id": msg_id, "method": "tools/call",
                                 "params": {"name": tool, "arguments": arguments or {}}})
        result = self._raise_on_error(out, msg_id, tool).get("result") or {}
        text = "\n".join(_plain(c.get("text", "")) for c in result.get("content") or [] if isinstance(c, dict))
        if result.get("isError"):
            raise CallError(f"MCP COROS : {text.strip()[:200] or tool + ' en erreur'}")
        return text


def main() -> int:
    relay = Relay()
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            _log("message illisible ignoré")
            continue
        batch = msg if isinstance(msg, list) else [msg]
        for item in batch:
            for out in relay.handle(item):
                sys.stdout.write(json.dumps(out, ensure_ascii=False) + "\n")
            sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
