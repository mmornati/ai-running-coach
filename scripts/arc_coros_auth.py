#!/usr/bin/env python3
"""Connexion au MCP officiel COROS, propre au projet — l'équivalent de `garmin-mcp-auth`.

L'athlète se connecte UNE fois (`login`, navigateur, interactif seulement) ; les jetons
sont rangés dans un dossier à nous (défaut `~/.config/ai-running-coach/coros/`, dossier 700,
fichiers 600) et partagés par le relais MCP `scripts/arc_coros_mcp.py` (déclaré dans la config
de chaque client d'IA par `install.sh --coros`) et par la synchronisation sans tête. Le client
d'IA n'a donc plus de connexion OAuth à faire, et les jetons de Claude Code ne sont jamais lus.

Constaté le 22 octobre 2026 (`docs/coros.md`, « Client OAuth à nous ») : enregistrement
dynamique d'un client public (`/connect/register`, sans secret), code + PKCE `S256`, jeton
d'accès de 30 jours, jeton de rafraîchissement qui CHANGE à chaque rafraîchissement
(rotation). D'où une règle : un seul propriétaire des jetons, et un rafraîchissement sous
verrou de fichier (le relais et le cron peuvent tourner en même temps).

Sous-commandes :
    login [--device] [--base-url URL]   connexion (navigateur ; --device : code à saisir)
    verify [--json]                     jeton valide + appel réel du MCP (réseau)
    status [--json]                     présence, échéance, droits — sans réseau
    logout                              efface les jetons locaux

Sorties : 0 = OK ; 2 = pas connecté / configuration ; 3 = COROS injoignable ou jeton refusé.
Aucun jeton n'est jamais affiché. Bibliothèque standard seule (Python 3.9).
"""

from __future__ import annotations

import argparse
import base64
import contextlib
import hashlib
import http.server
import json
import os
import secrets
import socketserver
import stat
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from pathlib import Path
from typing import Iterator, Optional, Tuple

DEFAULT_BASE_URL = "https://mcpeu.coros.com"
SCOPE = "openid mcp.tools offline_access"
CLIENT_NAME = "ai-running-coach"
CALLBACK_PORT = 8765
# Rafraîchir quand il reste moins que ça : le jeton d'accès vit 30 jours, et un
# rafraîchissement régulier garde aussi le jeton de rafraîchissement neuf.
REFRESH_MARGIN_S = 7 * 24 * 3600
TIMEOUT_S = 30.0
DEVICE_GRANT = "urn:ietf:params:oauth:grant-type:device_code"


class CorosAuthError(Exception):
    """Erreur dite à l'athlète. `code` = code de sortie (2 configuration, 3 COROS)."""

    def __init__(self, message: str, code: int = 3):
        super().__init__(message)
        self.code = code


def token_dir() -> Path:
    custom = os.environ.get("ARC_COROS_DIR", "").strip()
    return Path(custom).expanduser() if custom else Path.home() / ".config" / "ai-running-coach" / "coros"


def _client_file() -> Path:
    return token_dir() / "client.json"


def _tokens_file() -> Path:
    return token_dir() / "tokens.json"


def _ensure_dir() -> Path:
    d = token_dir()
    d.mkdir(parents=True, exist_ok=True)
    os.chmod(d, stat.S_IRWXU)
    return d


def _write_private(path: Path, obj: dict) -> None:
    """Écriture atomique en 600 : un lecteur concurrent ne voit jamais un fichier à moitié écrit."""
    _ensure_dir()
    tmp = path.with_name(path.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(obj, f)
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


def _read_json(path: Path) -> Optional[dict]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


@contextlib.contextmanager
def _locked() -> Iterator[None]:
    """Verrou exclusif entre le relais et le cron : deux rafraîchissements simultanés
    utiliseraient le même jeton de rafraîchissement, et la rotation en invaliderait un."""
    import fcntl  # POSIX (Linux, macOS, WSL) — comme le reste de l'installation

    _ensure_dir()
    fd = os.open(token_dir() / ".lock", os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


# --- HTTP ---------------------------------------------------------------------

def http_post(url: str, *, form: Optional[dict] = None, body: Optional[dict] = None,
              headers: Optional[dict] = None, timeout: float = TIMEOUT_S) -> Tuple[int, dict, str]:
    """POST ; rend (statut, en-têtes en minuscules, texte). Jamais d'exception HTTP."""
    hdrs = dict(headers or {})
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        hdrs["Content-Type"] = "application/json"
    else:
        data = urllib.parse.urlencode(form or {}).encode("utf-8")
        hdrs["Content-Type"] = "application/x-www-form-urlencoded"
    req = urllib.request.Request(url, data=data, headers=hdrs, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, {k.lower(): v for k, v in r.headers.items()}, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, {k.lower(): v for k, v in e.headers.items()}, e.read().decode("utf-8", "replace")
    except (urllib.error.URLError, OSError) as e:
        raise CorosAuthError(f"COROS injoignable ({getattr(e, 'reason', e)})", 3)


def http_get_json(url: str, timeout: float = TIMEOUT_S) -> dict:
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise CorosAuthError(f"métadonnées OAuth COROS illisibles ({getattr(e, 'reason', e)})", 3)


def discover(base_url: str) -> dict:
    meta = http_get_json(base_url.rstrip("/") + "/.well-known/oauth-authorization-server")
    for key in ("authorization_endpoint", "token_endpoint", "registration_endpoint"):
        if not meta.get(key):
            raise CorosAuthError(f"métadonnées OAuth COROS sans {key}", 3)
    return meta


# --- Jetons -------------------------------------------------------------------

def _store_tokens(client: dict, tok: dict, now: Optional[float] = None) -> dict:
    now = time.time() if now is None else now
    if not tok.get("access_token"):
        raise CorosAuthError("réponse de COROS sans jeton d'accès", 3)
    stored = {
        "access_token": tok["access_token"],
        "refresh_token": tok.get("refresh_token") or (_read_json(_tokens_file()) or {}).get("refresh_token"),
        "expires_at": int(now + int(tok.get("expires_in") or 0)),
        "scope": tok.get("scope", ""),
        "obtained_at": int(now),
    }
    _write_private(_tokens_file(), stored)
    return stored


def mcp_url(client: Optional[dict] = None) -> str:
    client = client if client is not None else (_read_json(_client_file()) or {})
    return client.get("base_url", DEFAULT_BASE_URL).rstrip("/") + "/mcp"


def _refresh(client: dict, tokens: dict) -> dict:
    if not tokens.get("refresh_token"):
        raise CorosAuthError("pas de jeton de rafraîchissement — relancez : python3 scripts/arc_coros_auth.py login", 2)
    status, _, text = http_post(client["token_endpoint"], form={
        "grant_type": "refresh_token", "refresh_token": tokens["refresh_token"],
        "client_id": client["client_id"], "resource": mcp_url(client)})
    if status != 200:
        raise CorosAuthError(
            f"rafraîchissement refusé par COROS (HTTP {status}) — relancez : python3 scripts/arc_coros_auth.py login", 3)
    try:
        return _store_tokens(client, json.loads(text))
    except ValueError:
        raise CorosAuthError("réponse de rafraîchissement illisible", 3)


def access_token(rejected: Optional[str] = None, now: Optional[float] = None) -> str:
    """Jeton d'accès valide, rafraîchi sous verrou s'il expire bientôt, ou s'il est encore
    celui que COROS vient de refuser (`rejected`, après un 401). Relit le fichier SOUS le
    verrou : un autre processus a peut-être déjà rafraîchi, et son jeton de rafraîchissement
    est alors le seul encore valable."""
    client = _read_json(_client_file())
    if not client or not _tokens_file().exists():
        raise CorosAuthError("COROS non connecté — lancez : python3 scripts/arc_coros_auth.py login", 2)
    with _locked():
        tokens = _read_json(_tokens_file()) or {}
        current = time.time() if now is None else now
        stale = int(tokens.get("expires_at") or 0) - current < REFRESH_MARGIN_S
        if rejected and tokens.get("access_token") == rejected:
            stale = True
        if stale or not tokens.get("access_token"):
            tokens = _refresh(client, tokens)
        return tokens["access_token"]


# --- Connexion (interactive) --------------------------------------------------

def register_client(meta: dict, base_url: str, redirect_uri: str) -> dict:
    status, _, text = http_post(meta["registration_endpoint"], body={
        "client_name": CLIENT_NAME,
        "redirect_uris": [redirect_uri],
        "grant_types": ["authorization_code", "refresh_token", DEVICE_GRANT],
        "response_types": ["code"],
        "token_endpoint_auth_method": "none",
        "scope": SCOPE})
    if status not in (200, 201):
        raise CorosAuthError(f"enregistrement du client refusé par COROS (HTTP {status})", 3)
    reg = json.loads(text)
    client = {
        "client_id": reg["client_id"], "base_url": base_url.rstrip("/"),
        "redirect_uri": redirect_uri,
        "token_endpoint": meta["token_endpoint"],
        "authorization_endpoint": meta["authorization_endpoint"],
        "device_authorization_endpoint": meta.get("device_authorization_endpoint", ""),
        "registered_at": int(time.time()),
    }
    _write_private(_client_file(), client)
    return client


def pkce_pair() -> Tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


class _Server(socketserver.ThreadingMixIn, http.server.HTTPServer):
    # Une préconnexion inactive du navigateur ne doit pas bloquer le vrai retour (comme arc_llm.py).
    daemon_threads = True

    # Pas de résolution DNS inverse au démarrage (voir tests/lib/local_http.py).
    def server_bind(self) -> None:
        socketserver.TCPServer.server_bind(self)
        host, port = self.server_address[:2]
        self.server_name, self.server_port = str(host), port


def _wait_for_code(port: int, timeout_s: int) -> dict:
    got: dict = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        timeout = 5  # socket inactive : le fil se libère seul

        def do_GET(self):  # noqa: N802 (API de http.server)
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            got.update({k: v[0] for k, v in q.items()})
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write("ai-running-coach : connexion COROS reçue, vous pouvez fermer cet onglet.".encode())

        def log_message(self, *_args):
            pass

    srv = _Server(("127.0.0.1", port), Handler)
    threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.5}, daemon=True).start()
    deadline = time.time() + timeout_s
    try:
        while not got.get("code") and not got.get("error") and time.time() < deadline:
            time.sleep(0.5)
    finally:
        srv.shutdown()
        srv.server_close()
    return got


def login_browser(client: dict, port: int, timeout_s: int = 300) -> dict:
    verifier, challenge = pkce_pair()
    state = secrets.token_urlsafe(16)
    url = client["authorization_endpoint"] + "?" + urllib.parse.urlencode({
        "response_type": "code", "client_id": client["client_id"], "redirect_uri": client["redirect_uri"],
        "scope": SCOPE, "state": state, "code_challenge": challenge,
        "code_challenge_method": "S256", "resource": mcp_url(client)})
    print("Ouvrez cette adresse dans votre navigateur et autorisez l'accès à votre compte COROS :\n")
    print(url + "\n", flush=True)
    with contextlib.suppress(Exception):
        threading.Thread(target=webbrowser.open, args=(url,), daemon=True).start()
    print(f"(en attente du retour sur 127.0.0.1:{port}, {timeout_s // 60} min max ; "
          "sans navigateur sur cette machine : relancez avec --device)", flush=True)
    got = _wait_for_code(port, timeout_s)
    if not got:
        raise CorosAuthError("aucun retour du navigateur — relancez, ou utilisez --device", 2)
    if got.get("error"):
        raise CorosAuthError(f"accès refusé : {got.get('error')}", 2)
    if got.get("state") != state:
        raise CorosAuthError("réponse inattendue (state différent) : connexion abandonnée", 2)
    status, _, text = http_post(client["token_endpoint"], form={
        "grant_type": "authorization_code", "code": got.get("code", ""),
        "redirect_uri": client["redirect_uri"], "client_id": client["client_id"],
        "code_verifier": verifier, "resource": mcp_url(client)})
    if status != 200:
        raise CorosAuthError(f"échange du code refusé par COROS (HTTP {status})", 3)
    return _store_tokens(client, json.loads(text))


def login_device(client: dict, timeout_s: int = 600) -> dict:
    endpoint = client.get("device_authorization_endpoint")
    if not endpoint:
        raise CorosAuthError("COROS n'annonce pas de connexion par code", 3)
    status, _, text = http_post(endpoint, form={"client_id": client["client_id"], "scope": SCOPE,
                                                "resource": mcp_url(client)})
    if status != 200:
        raise CorosAuthError(f"connexion par code refusée par COROS (HTTP {status})", 3)
    dev = json.loads(text)
    print("Sur n'importe quel appareil, ouvrez :", dev.get("verification_uri_complete") or dev.get("verification_uri"))
    if not dev.get("verification_uri_complete"):
        print("et saisissez le code :", dev.get("user_code"))
    print(flush=True)
    interval = int(dev.get("interval") or 5)
    deadline = time.time() + min(timeout_s, int(dev.get("expires_in") or timeout_s))
    while time.time() < deadline:
        time.sleep(interval)
        status, _, text = http_post(client["token_endpoint"], form={
            "grant_type": DEVICE_GRANT, "device_code": dev["device_code"], "client_id": client["client_id"]})
        if status == 200:
            return _store_tokens(client, json.loads(text))
        err = (json.loads(text) if text.strip().startswith("{") else {}).get("error")
        if err == "slow_down":
            interval += 5
        elif err != "authorization_pending":
            raise CorosAuthError(f"connexion par code refusée ({err or 'HTTP %d' % status})", 2)
    raise CorosAuthError("code expiré avant validation — relancez", 2)


# --- MCP (vérification) -------------------------------------------------------

def parse_mcp_body(text: str) -> list:
    """Réponse JSON simple, ou flux SSE (lignes `data:`) : rend la liste des messages JSON-RPC."""
    stripped = text.strip()
    if not stripped:
        return []
    if stripped.startswith("{") or stripped.startswith("["):
        obj = json.loads(stripped)
        return obj if isinstance(obj, list) else [obj]
    out, buf = [], []
    for line in text.splitlines():
        if line.startswith("data:"):
            buf.append(line[5:].lstrip())
        elif not line.strip() and buf:
            out.append(json.loads("\n".join(buf)))
            buf = []
    if buf:
        out.append(json.loads("\n".join(buf)))
    return out


def verify() -> dict:
    """Jeton valide + vrai appel du MCP : initialize puis tools/list (lecture seule)."""
    token = access_token()
    url = mcp_url()
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json, text/event-stream"}
    status, hdrs, text = http_post(url, headers=headers, body={
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                   "clientInfo": {"name": CLIENT_NAME, "version": "1"}}})
    if status == 401:
        raise CorosAuthError("jeton refusé par COROS — relancez : python3 scripts/arc_coros_auth.py login", 3)
    if status != 200:
        raise CorosAuthError(f"MCP COROS : HTTP {status}", 3)
    session = hdrs.get("mcp-session-id")
    if session:
        headers["Mcp-Session-Id"] = session
    http_post(url, headers=headers, body={"jsonrpc": "2.0", "method": "notifications/initialized"})
    status, _, text = http_post(url, headers=headers, body={"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    msgs = [m for m in parse_mcp_body(text) if m.get("id") == 2]
    tools = (msgs[0].get("result") or {}).get("tools", []) if msgs else []
    if status != 200 or not tools:
        raise CorosAuthError(f"MCP COROS : liste d'outils vide (HTTP {status})", 3)
    return {"ok": True, "tools": len(tools), **status_info()}


def status_info(now: Optional[float] = None) -> dict:
    """Sans réseau : présence, échéance, droits (repris par /coach-doctor)."""
    now = time.time() if now is None else now
    d, tokens = token_dir(), _read_json(_tokens_file())
    info = {"dir": str(d), "connected": bool(tokens and tokens.get("access_token") and _client_file().exists())}
    if tokens:
        info["expires_in_days"] = round((int(tokens.get("expires_at") or 0) - now) / 86400, 1)
        info["has_refresh_token"] = bool(tokens.get("refresh_token"))
    loose = []
    for p in [d, _client_file(), _tokens_file()]:
        if p.exists():
            mode = stat.S_IMODE(p.stat().st_mode)
            if mode & 0o077:
                loose.append(f"{p.name or p} ({oct(mode)})")
    info["loose_permissions"] = loose
    return info


def _refuse_headless() -> None:
    if os.environ.get("ARC_HEADLESS") or not sys.stdin.isatty():
        raise CorosAuthError("connexion COROS : interactive seulement (navigateur), jamais en headless", 2)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Connexion du projet au MCP officiel COROS.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_login = sub.add_parser("login", help="connexion (interactive)")
    p_login.add_argument("--device", action="store_true", help="code à saisir sur un autre appareil")
    p_login.add_argument("--base-url", default=DEFAULT_BASE_URL)
    p_login.add_argument("--port", type=int, default=CALLBACK_PORT)
    for name in ("verify", "status"):
        sub.add_parser(name).add_argument("--json", action="store_true")
    sub.add_parser("logout")
    args = ap.parse_args(argv)
    try:
        if args.cmd == "login":
            _refuse_headless()
            meta = discover(args.base_url)
            client = register_client(meta, args.base_url, f"http://127.0.0.1:{args.port}/callback")
            tok = login_device(client) if args.device else login_browser(client, args.port)
            days = round((tok["expires_at"] - time.time()) / 86400)
            print(f"Connecté à COROS. Jetons rangés dans {token_dir()} (accès valable {days} jours, "
                  "renouvelé automatiquement).")
            return 0
        if args.cmd == "logout":
            for p in (_tokens_file(), _client_file()):
                with contextlib.suppress(FileNotFoundError):
                    p.unlink()
            print("Jetons COROS locaux effacés.")
            return 0
        info = verify() if args.cmd == "verify" else status_info()
        if args.json:
            print(json.dumps(info, ensure_ascii=False))
        elif args.cmd == "verify":
            print(f"COROS : connecté, {info['tools']} outils, accès encore valable "
                  f"{info.get('expires_in_days')} jours.")
        else:
            print(f"COROS : {'connecté' if info['connected'] else 'non connecté'} ({info['dir']})"
                  + (f", accès encore valable {info['expires_in_days']} jours" if "expires_in_days" in info else "")
                  + (f" — droits trop larges : {', '.join(info['loose_permissions'])}" if info["loose_permissions"] else ""))
        return 0 if args.cmd == "verify" or info["connected"] else 2
    except CorosAuthError as e:
        if getattr(args, "json", False):
            print(json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False))
        else:
            print(f"COROS : {e}", file=sys.stderr)
        return e.code


if __name__ == "__main__":
    sys.exit(main())
