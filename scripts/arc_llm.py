#!/usr/bin/env python3
"""Configuration de l'IA du coach : catalogue des fournisseurs et connexion sans clé à copier.

Module partagé (stdlib seule, Python 3.9 : l'application macOS peut l'appeler avec
/usr/bin/python3). Sous-commandes :

  providers [--json]
      Catalogue des fournisseurs (source de vérité unique : libellé, type, modèles par défaut,
      variable de clé, coût indicatif, confidentialité, ancre de doc).

  connect openrouter [--headless] [--no-browser] [--json] [--timeout S] [--env-file PATH]
      OpenRouter OAuth PKCE (https://openrouter.ai/docs/guides/overview/auth/oauth) : le
      navigateur autorise, OpenRouter rend une clé, écrite dans llm.env (mode 600), puis vérifiée
      par GET /api/v1/key. La clé n'est JAMAIS affichée, journalisée ni écrite en JSON.
      --headless : sans navigateur ni callback (SSH) ; le code affiché par OpenRouter est collé
      sur l'entrée standard.

Codes de sortie de `connect` :
  0  clé obtenue, écrite et vérifiée
  2  usage ou configuration invalide (option, fournisseur, URL de test refusée)
  3  autorisation refusée par l'athlète (ou code vide en --headless)
  4  délai dépassé sans retour du navigateur
  5  échec réseau ou échange du code refusé par OpenRouter (rien n'est écrit)
  6  clé écrite dans llm.env mais non vérifiée (réseau, clé refusée par /key)
  130  interrompu (Ctrl-C, SIGTERM) : rien n'est écrit

Avec --json : UN objet JSON sur la sortie standard ; la progression est en lignes JSON
({"event": ...}) sur la sortie d'erreur. ARC_OPENROUTER_BASE_URL (boucle locale uniquement)
remplace https://openrouter.ai pour les tests.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import secrets
import signal
import socketserver
import sys
import tempfile
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Dict, List, Optional, Tuple
from urllib import error as urlerror
from urllib import parse as urlparse
from urllib import request as urlrequest

OPENROUTER_BASE = "https://openrouter.ai"
BASE_ENV = "ARC_OPENROUTER_BASE_URL"
DEFAULT_TIMEOUT_S = 300
HTTP_TIMEOUT_S = 20
KEY_LABEL = "AI Running Coach"
LOOPBACK_HOSTS = ("127.0.0.1", "localhost", "[::1]", "::1")

# Étape atteinte : sert à dire la vérité en cas d'interruption (la clé a-t-elle pu être créée ?).
_STAGE = {"name": "auth"}

EXIT_OK, EXIT_USAGE, EXIT_DENIED, EXIT_TIMEOUT, EXIT_EXCHANGE, EXIT_UNVERIFIED, EXIT_INTERRUPTED = 0, 2, 3, 4, 5, 6, 130

# Catalogue : UNE source de vérité. install.sh garde ses constantes de repli (le script doit
# fonctionner sans python3) ; tests/install/test_llm_connect.py vérifie qu'elles concordent.
# kind : oauth (connexion en un clic) | subscription (forfait existant) | api_key | free.
CATALOG: List[Dict[str, Any]] = [
    {
        "id": "openrouter",
        "label": "OpenRouter (connexion en un clic)",
        "kind": "oauth",
        "chat_model": "openrouter/deepseek/deepseek-v4.1-flash",
        "sync_model": "openrouter/deepseek/deepseek-v4.1-flash",
        "key_env": "OPENROUTER_API_KEY",
        "monthly_cost": "environ 1 € par mois (mesuré : ≈ 0,80 € pour un mois type)",
        "privacy": "Choisissez, dans les réglages de confidentialité d'OpenRouter, des "
                   "fournisseurs qui ne conservent ni n'entraînent sur vos données.",
        "docs": "docs/choisir-son-ia.md#openrouter-en-un-clic",
    },
    {
        "id": "anthropic",
        "label": "Clé API Anthropic",
        "kind": "api_key",
        "chat_model": "claude-sonnet-5-5",
        "sync_model": "claude-haiku-4-5",
        "key_env": "ANTHROPIC_API_KEY",
        "monthly_cost": "facturé au jeton ; quelques euros par mois (approximation du projet)",
        "privacy": "API commerciale : politique de rétention d'Anthropic.",
        "docs": "docs/choisir-son-ia.md#cle-api-anthropic-openai-ou-autre",
    },
    {
        "id": "openai",
        "label": "Clé API OpenAI (ou compatible)",
        "kind": "api_key",
        "chat_model": None,
        "sync_model": None,
        "key_env": "OPENAI_API_KEY",
        "monthly_cost": "facturé au jeton selon le modèle choisi (--model est obligatoire)",
        "privacy": "API commerciale : politique de rétention du fournisseur choisi.",
        "docs": "docs/choisir-son-ia.md#cle-api-anthropic-openai-ou-autre",
    },
]


def provider(pid: str) -> Optional[Dict[str, Any]]:
    for p in CATALOG:
        if p["id"] == pid:
            return p
    return None


# --------------------------------------------------------------------------- sortie

class Out:
    """Sortie : texte pour l'humain, ou un objet JSON final + événements sur stderr."""

    def __init__(self, as_json: bool) -> None:
        self.as_json = as_json

    def event(self, name: str, message: str, **extra: Any) -> None:
        if self.as_json:
            sys.stderr.write(json.dumps(dict(event=name, message=message, **extra), ensure_ascii=False) + "\n")
        else:
            sys.stderr.write(message + "\n")
        sys.stderr.flush()

    def final(self, ok: bool, message: str, **fields: Any) -> None:
        if self.as_json:
            sys.stdout.write(json.dumps(dict(ok=ok, message=message, **fields), ensure_ascii=False) + "\n")
        else:
            sys.stdout.write(message + "\n")
        sys.stdout.flush()


def _scrub(text: str, secret: Optional[str]) -> str:
    return text.replace(secret, "[clé masquée]") if secret else text


# --------------------------------------------------------------------------- URL de base

def base_url() -> str:
    """https://openrouter.ai, ou l'URL de test (boucle locale seulement)."""
    raw = os.environ.get(BASE_ENV, "").strip()
    if not raw:
        return OPENROUTER_BASE
    parts = urlparse.urlsplit(raw)
    if parts.scheme != "http" or (parts.hostname or "") not in ("127.0.0.1", "localhost", "::1"):
        raise ValueError("%s n'accepte qu'une URL http de la boucle locale (tests)." % BASE_ENV)
    return raw.rstrip("/")


# --------------------------------------------------------------------------- PKCE

def make_pkce() -> Tuple[str, str]:
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(48)).decode().rstrip("=")
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return verifier, base64.urlsafe_b64encode(digest).decode().rstrip("=")


def auth_url(base: str, challenge: str, callback: Optional[str], state: Optional[str]) -> str:
    params = [("code_challenge", challenge), ("code_challenge_method", "S256"), ("key_label", KEY_LABEL)]
    if callback:
        params.insert(0, ("callback_url", callback))
        if state:
            params.append(("state", state))
    return base + "/auth?" + urlparse.urlencode(params)


# --------------------------------------------------------------------------- HTTP

def _http_json(method: str, url: str, body: Optional[dict] = None, bearer: Optional[str] = None) -> Tuple[int, Any]:
    data = json.dumps(body).encode() if body is not None else None
    req = urlrequest.Request(url, data=data, method=method)
    req.add_header("Accept", "application/json")
    req.add_header("User-Agent", "ai-running-coach/arc_llm")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    if bearer:
        req.add_header("Authorization", "Bearer " + bearer)
    try:
        with urlrequest.urlopen(req, timeout=HTTP_TIMEOUT_S) as resp:
            status, raw = resp.status, resp.read()
    except urlerror.HTTPError as exc:
        status, raw = exc.code, exc.read()
    try:
        return status, json.loads(raw.decode("utf-8", "replace"))
    except ValueError:
        return status, None


# --------------------------------------------------------------------------- callback loopback

PAGE = (
    "<!doctype html><html lang=\"fr\"><meta charset=\"utf-8\"><title>AI Running Coach</title>"
    "<body style=\"font-family:system-ui;max-width:32rem;margin:4rem auto;padding:0 1rem\">"
    "<h1>%s</h1><p>%s</p></body></html>"
)


class _Server(socketserver.ThreadingMixIn, HTTPServer):
    # Une connexion inactive (préconnexion du navigateur) ne doit ni bloquer le vrai retour ni
    # repousser le délai maximal : un fil par requête, la boucle d'attente garde la main.
    daemon_threads = True

    # Pas de résolution DNS inverse au démarrage (voir tests/lib/local_http.py).
    def server_bind(self) -> None:
        socketserver.TCPServer.server_bind(self)
        host, port = self.server_address[:2]
        self.server_name, self.server_port = str(host), port


def _make_handler(state: str, result: Dict[str, Any]):
    class Handler(BaseHTTPRequestHandler):
        timeout = 5  # socket inactive : le fil se libère seul

        def log_message(self, *args: Any) -> None:  # silence : l'URL porte le code
            pass

        def _reply(self, status: int, title: str, text: str) -> None:
            body = (PAGE % (title, text)).encode()
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            parts = urlparse.urlsplit(self.path)
            if parts.path != "/callback":
                self._reply(404, "Page introuvable", "Cette adresse ne sert qu'à la connexion du coach.")
                return
            q = urlparse.parse_qs(parts.query)
            got_state = (q.get("state") or [""])[0]
            code = (q.get("code") or [""])[0]
            # OpenRouter ne renvoie pas `state` quand l'athlète refuse (et ne documente pas de
            # paramètre `error`) : un retour sans code ni state, ou avec `error`, vaut refus.
            # Compromis assumé : n'importe quel onglet local peut donc annuler la connexion en
            # appelant /callback sans paramètre. Le pire effet est un échec à relancer ; il ne
            # peut ni fournir un code, ni écrire une clé (le code exige le bon `state`).
            denied = "error" in q or (not code and not got_state)
            if got_state and not secrets.compare_digest(got_state.encode("utf-8"), state.encode("utf-8")):
                self._reply(400, "Requête refusée", "Le jeton de sécurité ne correspond pas : connexion ignorée.")
                return
            if denied:
                self._reply(200, "Connexion annulée", "Aucune clé n'a été créée. Vous pouvez fermer cet onglet.")
                result["denied"] = (q.get("error") or [""])[0] or "denied"
                return
            if not got_state or not code:
                self._reply(400, "Requête refusée", "Retour incomplet : connexion ignorée.")
                return
            self._reply(200, "Autorisation reçue", "Retournez à l'application AI Running Coach : la connexion se termine. Vous pouvez fermer cet onglet.")
            result["code"] = code

    return Handler


def wait_for_callback(server: HTTPServer, result: Dict[str, Any], timeout_s: float) -> None:
    deadline = time.monotonic() + timeout_s
    server.timeout = 0.5
    while time.monotonic() < deadline and "code" not in result and "denied" not in result:
        server.handle_request()
    time.sleep(0.2)  # laisse le fil de la requête finir d'écrire sa réponse


# --------------------------------------------------------------------------- llm.env

def default_env_file() -> str:
    return os.environ.get("ARC_LLM_ENV") or os.path.expanduser("~/.config/ai-running-coach/llm.env")


def check_env_readable(path: str) -> Optional[str]:
    """Message d'erreur si le fichier existe mais n'est pas un texte UTF-8 lisible, sinon None."""
    try:
        if os.path.exists(path):
            with open(path, encoding="utf-8") as fh:
                fh.read()
    except UnicodeDecodeError:
        return "%s n'est pas un fichier texte UTF-8 : corrigez-le ou déplacez-le, puis relancez." % path
    except OSError as exc:
        return "Impossible de lire %s : %s" % (path, exc.strerror or exc)
    return None


def write_env_var(path: str, var: str, value: str) -> None:
    """Pose VAR=valeur dans le fichier, de façon atomique (mode 600) ; garde les autres lignes."""
    path = os.path.realpath(path)  # un lien symbolique reste un lien : on écrit sa cible
    directory = os.path.dirname(path)
    if not os.path.isdir(directory):
        os.makedirs(directory, mode=0o700)
        os.chmod(directory, 0o700)
    lines: List[str] = []
    if os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            lines = fh.read().splitlines()
    pattern = re.compile(r"^\s*(?:export\s+)?(#?)\s*%s=" % re.escape(var))
    active = [i for i, ln in enumerate(lines) if pattern.match(ln) and not pattern.match(ln).group(1)]
    commented = [i for i, ln in enumerate(lines) if pattern.match(ln) and pattern.match(ln).group(1)]
    new_line = "%s=%s" % (var, value)
    if active:
        lines[active[0]] = new_line
        drop = set(active[1:])  # doublons actifs : le dernier gagnerait au chargement
        lines = [ln for i, ln in enumerate(lines) if i not in drop]
    elif commented:
        lines[commented[0]] = new_line
    else:
        lines.append(new_line)
    fd, tmp = tempfile.mkstemp(prefix=".llm.env.", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


# --------------------------------------------------------------------------- connect openrouter

def _key_summary(data: Dict[str, Any]) -> Dict[str, Any]:
    keep = ("label", "limit", "limit_remaining", "usage", "is_free_tier", "free_model_daily_requests")
    return {k: data.get(k) for k in keep}


def connect_openrouter(args: argparse.Namespace) -> int:
    out = Out(args.json)
    try:
        base = base_url()
    except ValueError as exc:
        out.final(False, str(exc), error="usage")
        return EXIT_USAGE
    env_file = args.env_file or default_env_file()
    problem = check_env_readable(env_file)
    if problem:
        out.final(False, problem, error="usage")
        return EXIT_USAGE
    verifier, challenge = make_pkce()
    state = secrets.token_urlsafe(24)
    result: Dict[str, Any] = {}
    server: Optional[HTTPServer] = None
    try:
        if args.headless:
            url = auth_url(base, challenge, None, None)
            out.event("auth_url", "Ouvrez cette adresse dans un navigateur, autorisez, puis collez le code affiché :\n" + url, url=url)
            out.event("paste_code", "Code OpenRouter :")
            code = sys.stdin.readline().strip()
            if not code:
                out.final(False, "Aucun code collé : connexion annulée.", error="denied")
                return EXIT_DENIED
            result["code"] = code
        else:
            server = _Server(("127.0.0.1", 0), _make_handler(state, result))
            callback = "http://127.0.0.1:%d/callback" % server.server_address[1]
            url = auth_url(base, challenge, callback, state)
            opened = False
            if not args.no_browser:
                try:
                    opened = bool(webbrowser.open(url))
                except Exception:
                    opened = False
            out.event("auth_url", ("Une page OpenRouter s'ouvre dans votre navigateur : autorisez le coach."
                                   if opened else "Ouvrez cette adresse dans votre navigateur pour autoriser le coach :")
                      + ("" if opened else "\n" + url), url=url, browser_opened=opened)
            wait_for_callback(server, result, args.timeout)
            if "denied" in result:
                out.final(False, "Autorisation refusée dans le navigateur : aucune clé créée.", error="denied")
                return EXIT_DENIED
            if "code" not in result:
                out.final(False, "Délai dépassé (%d s) sans retour du navigateur : relancez la connexion." % args.timeout, error="timeout")
                return EXIT_TIMEOUT
    finally:
        if server is not None:
            server.server_close()

    out.event("exchange", "Échange du code avec OpenRouter…")
    _STAGE["name"] = "exchange"
    try:
        status, body = _http_json("POST", base + "/api/v1/auth/keys", {
            "code": result["code"], "code_verifier": verifier, "code_challenge_method": "S256"})
    except (urlerror.URLError, OSError) as exc:
        out.final(False, "OpenRouter est injoignable (%s)." % type(exc).__name__, error="network")
        return EXIT_EXCHANGE
    key = body.get("key") if isinstance(body, dict) else None
    if status != 200 or not isinstance(key, str) or not key:
        hint = {400: "méthode de défi invalide", 403: "code invalide ou expiré (10 min)", 405: "méthode refusée"}.get(status, "réponse inattendue")
        out.final(False, "OpenRouter a refusé l'échange du code (HTTP %d : %s). Relancez la connexion." % (status, hint),
                  error="exchange", http_status=status)
        return EXIT_EXCHANGE

    try:
        write_env_var(env_file, "OPENROUTER_API_KEY", key)
    except (OSError, UnicodeError) as exc:
        out.final(False, _scrub("Impossible d'écrire %s : %s" % (env_file, getattr(exc, "strerror", None) or exc), key), error="write")
        return EXIT_EXCHANGE
    _STAGE["name"] = "stored"
    out.event("stored", "Clé enregistrée dans %s (mode 600)." % env_file)

    try:
        vstatus, vbody = _http_json("GET", base + "/api/v1/key", bearer=key)
    except (urlerror.URLError, OSError):
        vstatus, vbody = 0, None
    data = vbody.get("data") if isinstance(vbody, dict) else None
    if vstatus != 200 or not isinstance(data, dict):
        out.final(False, "Clé enregistrée dans %s mais OpenRouter n'a pas pu la vérifier (HTTP %d). "
                  "Relancez « arc_llm.py check » plus tard ou la connexion." % (env_file, vstatus),
                  error="unverified", stored=True, env_file=env_file)
        return EXIT_UNVERIFIED
    info = _key_summary(data)
    free = info.get("free_model_daily_requests")
    if isinstance(free, dict) and isinstance(free.get("limit"), int):
        tier = "modèles gratuits : %s requête(s) restante(s) aujourd'hui sur %d" % (
            free.get("remaining", "?"), free["limit"])
    else:
        tier = "quota gratuit non communiqué"
    out.final(True, "OpenRouter connecté (clé « %s », %s)." % (info.get("label") or "?", tier),
              provider="openrouter", env_file=env_file, **info)
    return EXIT_OK


# --------------------------------------------------------------------------- CLI

def cmd_providers(args: argparse.Namespace) -> int:
    if args.json:
        print(json.dumps({"providers": CATALOG}, ensure_ascii=False, indent=2))
    else:
        for p in CATALOG:
            print("%-11s %-13s %s — %s" % (p["id"], p["kind"], p["label"], p["monthly_cost"]))
    return EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Configuration de l'IA du coach (catalogue, connexion).")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sp = sub.add_parser("providers", help="catalogue des fournisseurs")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_providers)
    sc = sub.add_parser("connect", help="connexion à un fournisseur sans clé à copier")
    csub = sc.add_subparsers(dest="provider", required=True)
    so = csub.add_parser("openrouter", help="OpenRouter, OAuth PKCE")
    so.add_argument("--headless", action="store_true", help="sans navigateur local : coller le code affiché")
    so.add_argument("--no-browser", action="store_true", help="n'ouvre pas le navigateur, affiche l'adresse")
    so.add_argument("--json", action="store_true", help="un objet JSON (sans la clé) ; progression JSON sur stderr")
    so.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT_S, help="secondes d'attente du navigateur (défaut 300)")
    so.add_argument("--env-file", help="llm.env cible (défaut : $ARC_LLM_ENV ou ~/.config/ai-running-coach/llm.env)")
    so.set_defaults(func=connect_openrouter)
    return ap


def _on_sigterm(signum: int, frame: Any) -> None:
    raise KeyboardInterrupt()


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    # SIGTERM (bouton « Annuler » de l'application) : même sortie propre que Ctrl-C.
    signal.signal(signal.SIGTERM, _on_sigterm)
    signal.signal(signal.SIGINT, _on_sigterm)  # actif même si le lanceur ignorait SIGINT (processus en arrière-plan)
    try:
        return args.func(args)
    except KeyboardInterrupt:
        stage = _STAGE["name"]
        if stage == "stored":
            msg = "Connexion interrompue après l'enregistrement : la clé est dans llm.env mais n'a pas été vérifiée."
        elif stage == "exchange":
            msg = ("Connexion interrompue pendant l'échange : une clé a peut-être été créée chez OpenRouter "
                   "(https://openrouter.ai/settings/keys) sans être enregistrée ; supprimez-la si besoin et relancez la connexion.")
        else:
            msg = "Connexion interrompue : aucune clé n'a été créée."
        Out(bool(getattr(args, "json", False))).final(False, msg, error="interrupted", stage=stage)
        return EXIT_INTERRUPTED


if __name__ == "__main__":
    sys.exit(main())
