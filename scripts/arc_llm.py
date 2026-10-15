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

  login chatgpt|copilot [--data-dir DIR] [--json] [--browser] [--no-browser] [--timeout S]
      Connexion d'un abonnement ChatGPT Plus/Pro ou GitHub Copilot (#266) : lance
      `opencode providers login -p <fournisseur> -m <méthode>` avec XDG_DATA_HOME = le magasin
      d'authentification dédié au coach (voir « Magasin » ci-dessous), relaie l'adresse et le code
      d'appareil, tue le processus enfant à la sortie. Interactif seulement (refusé sous
      ARC_HEADLESS : cron, launchd). Jamais de jeton affiché : OpenCode l'écrit dans auth.json.

  with-lock --data-dir DIR [--timeout S] -- COMMANDE…
      Exécute COMMANDE sous le verrou du magasin (voir « Concurrence »). Code 75 si le verrou n'a
      pas pu être pris dans le délai. Utilisé par daily-sync.sh.

  auth-status chatgpt|copilot [--data-dir DIR] [--json]
      Présence (jamais la valeur) du jeton dans le magasin : code 0 présent, 1 absent.

Magasin d'authentification dédié (#266). `[chat].opencode_data_dir` et `[sync].opencode_data_dir`
(même chemin, posés ensemble par `install.sh --llm chatgpt|copilot`) sont utilisés comme
XDG_DATA_HOME d'OpenCode par le chat ET la sync, pour ces deux fournisseurs seulement ; clé absente
ou vide = comportement historique (chat isolé sous .arc/chat/opencode/xdg, sync sur le magasin
global). Le dossier est partagé en entier (pas seulement auth.json) : OpenCode y garde aussi sa base
de sessions SQLite, prévue pour plusieurs processus, et le lien symbolique de auth.json n'est pas
fiable (OpenCode réécrit le fichier à chaque rafraîchissement, vérifié dans le code source v1.18.35).

Concurrence. OpenCode réécrit auth.json SANS verrou quand il rafraîchit le jeton ChatGPT, et le
jeton de rafraîchissement peut être à usage unique (non vérifié). Deux rafraîchissements
simultanés (tour de chat pendant la sync) risquent donc d'écraser la connexion. Le chat (par tour)
et la sync (par exécution) prennent un verrou `flock` exclusif `<magasin>/.arc-auth.lock` : jamais
deux processus qui peuvent rafraîchir en même temps. Copilot ne rafraîchit rien (jeton GitHub
direct) : pas de verrou.

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
import select
import shutil
import signal
import socketserver
import subprocess
import sys
import tempfile
import threading
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
    {
        "id": "chatgpt",
        "label": "J'ai ChatGPT Plus ou Pro (connexion avec mon compte)",
        "kind": "subscription",
        # Identifiants vérifiés dans models.dev (api.json du 2026-10-15) ET dans la liste d'autorisation
        # du plugin OAuth d'OpenCode v1.18.35 (plugin/openai/codex.ts) ; PAS évalués sur un vrai forfait
        # ChatGPT (aucune connexion réelle faite) : approximation du projet, à confirmer après la
        # première connexion (`opencode models openai`).
        "chat_model": "openai/gpt-5.4-mini",
        "sync_model": "openai/gpt-5.4",
        "key_env": "",
        "opencode_provider": "openai",
        "login_method": "ChatGPT Pro/Plus (headless)",
        "login_method_browser": "ChatGPT Pro/Plus (browser)",
        "plan_label": "ChatGPT",
        "refreshes_tokens": True,
        "monthly_cost": "inclus dans votre forfait ChatGPT Plus ou Pro (limites du forfait, aucun coût au jeton)",
        "privacy": "Vos échanges passent par votre compte ChatGPT : réglages de données et "
                   "d'entraînement de votre compte OpenAI.",
        "docs": "docs/choisir-son-ia.md#chatgpt-plus-ou-pro",
    },
    {
        "id": "copilot",
        "label": "J'ai GitHub Copilot (connexion avec GitHub)",
        "kind": "subscription",
        # Même vérification que ci-dessus (models.dev, github-copilot, 2026-10-15) ; la liste réelle
        # dépend du forfait (api.githubcopilot.com/models) et n'a pas été évaluée sur un vrai forfait.
        "chat_model": "github-copilot/gpt-5.4-mini",
        "sync_model": "github-copilot/claude-sonnet-5.5",
        "key_env": "",
        "opencode_provider": "github-copilot",
        "login_method": "Login with GitHub Copilot",
        "login_method_browser": "Login with GitHub Copilot",
        "plan_label": "GitHub Copilot",
        "refreshes_tokens": False,
        "monthly_cost": "inclus dans votre forfait Copilot Pro, Pro+, Business ou Enterprise (crédits du forfait)",
        "privacy": "Vos échanges passent par GitHub Copilot : paramètres de confidentialité de votre compte "
                   "ou de votre organisation GitHub.",
        "docs": "docs/choisir-son-ia.md#github-copilot",
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


# --------------------------------------------------------------------------- abonnements (#266)

EXIT_LOCK_TIMEOUT = 75     # with-lock : verrou non pris dans le délai (EX_TEMPFAIL)
LOCK_NAME = ".arc-auth.lock"
LOGIN_TIMEOUT_S = 600
COPILOT_DEPLOYMENT_PROMPT = "deployment type"

_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b[()][A-Za-z0-9]")
_URL_RE = re.compile(r"Go to:\s*(\S+)")
_CODE_RE = re.compile(r"Enter code:\s*(\S+)")


def default_data_dir() -> str:
    """Magasin d'authentification OpenCode du coach : hors dépôt et hors workspace."""
    return os.path.expanduser("~/.local/share/ai-running-coach/opencode")


def resolve_data_dir(value: Optional[str]) -> str:
    return os.path.abspath(os.path.expanduser(value)) if value else default_data_dir()


def ensure_data_dir(path: str) -> None:
    """Crée le magasin en mode 700 (et resserre un dossier existant)."""
    os.makedirs(path, mode=0o700, exist_ok=True)
    os.chmod(path, 0o700)


def subscription_entry(model: str, data_dir: str, api_key_env: str = "", base_url: str = "") -> Optional[Dict[str, Any]]:
    """Entrée du catalogue si (modèle, magasin) désignent un abonnement ChatGPT/Copilot, sinon None.

    Il faut : un magasin dédié posé, aucune clé API, aucune URL de base, et un modèle d'un des deux
    fournisseurs OpenCode (`openai/…` ou `github-copilot/…`). Tout autre cas = comportement historique.
    """
    if not data_dir or api_key_env or base_url:
        return None
    prefix = (model or "").partition("/")[0]
    for p in CATALOG:
        if p["kind"] == "subscription" and p.get("opencode_provider") == prefix:
            return p
    return None


def auth_status(data_dir: str, opencode_provider: str) -> Dict[str, Any]:
    """Présence du jeton dans `<magasin>/opencode/auth.json` — noms et échéance, JAMAIS les valeurs.

    `expires` (ms) n'a de sens que pour ChatGPT : le jeton d'accès est rafraîchi tout seul tant que le
    jeton de rafraîchissement est valable ; Copilot pose `expires: 0` (pas d'échéance connue).
    """
    path = os.path.join(data_dir, "opencode", "auth.json")
    info: Dict[str, Any] = {"present": False, "path": path}
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return info
    entry = data.get(opencode_provider) if isinstance(data, dict) else None
    if not isinstance(entry, dict) or not entry.get("type"):
        return info
    info.update(present=True, type=entry.get("type"))
    expires = entry.get("expires")
    if isinstance(expires, (int, float)) and not isinstance(expires, bool) and expires > 0:
        info["expires_ms"] = int(expires)
    return info


def reconnect_hint(entry: Dict[str, Any]) -> str:
    return "python3 scripts/arc_llm.py login %s" % entry["id"]


def missing_auth_message(entry: Dict[str, Any]) -> str:
    return "Connexion %s absente : reconnectez-vous avec « %s »." % (entry["plan_label"], reconnect_hint(entry))


def translate_subscription_error(entry: Dict[str, Any], name: str, status: Any, message: str) -> Optional[str]:
    """Erreur d'un fournisseur d'abonnement -> message français actionnable, ou None (repli générique).

    Motifs tirés du code source d'OpenCode v1.18.35 (provider/error.ts : `usage_not_included`,
    `insufficient_quota`, 401 « Unauthorized… » ; plugin/openai/codex.ts : « Token refresh failed:
    <statut> »). NON VÉRIFIÉS sur un vrai compte : le corps exact d'un dépassement de limite du forfait
    ChatGPT (429), les 401/403 de Copilot et l'erreur « fournisseur non connecté ».
    """
    low = (message or "").lower()
    label = entry["plan_label"]
    try:
        code = int(status)
    except (TypeError, ValueError):
        code = 0
    if "usage_not_included" in low or "upgrade to plus" in low:
        return ("Votre offre ChatGPT n'inclut pas cet usage (usage_not_included) : ChatGPT Plus ou Pro est "
                "nécessaire, l'offre Free n'est pas acceptée.")
    if "insufficient_quota" in low or "quota exceeded" in low or "usage limit" in low \
            or code == 429 or "rate limit" in low or "too many requests" in low:
        return ("Les limites de votre forfait %s sont atteintes : réessayez plus tard (la limite se renouvelle "
                "d'elle-même), ou passez sur une autre IA (docs/choisir-son-ia.md)." % label)
    if entry["id"] == "copilot" and code in (401, 403):
        return ("GitHub Copilot a refusé la connexion (%d) : reconnectez-vous avec « %s » et vérifiez que votre "
                "forfait Copilot (Pro, Pro+, Business ou Enterprise) est actif." % (code, reconnect_hint(entry)))
    if "token refresh failed" in low or name == "ProviderAuthError" or code == 401 or "401" in low \
            or "unauthorized" in low or "token may be missing or expired" in low \
            or "provider not found" in low or "not connected" in low:
        return "Connexion %s expirée ou refusée : reconnectez-vous avec « %s »." % (label, reconnect_hint(entry))
    if name == "ProviderModelNotFoundError" or "model not found" in low or "modelnotfound" in low:
        return ("Ce modèle n'est pas disponible avec votre forfait %s : choisissez-en un autre dans [chat].model "
                "(python3 scripts/arc_llm.py providers)." % label)
    return None


# -- verrou du magasin ---------------------------------------------------------

def _lock_path(data_dir: str) -> str:
    return os.path.join(data_dir, LOCK_NAME)


def _open_lock(data_dir: str) -> int:
    ensure_data_dir(data_dir)
    return os.open(_lock_path(data_dir), os.O_RDWR | os.O_CREAT, 0o600)


def _flock_wait(fd: int, timeout_s: float) -> bool:
    import fcntl
    deadline = time.monotonic() + max(0.0, timeout_s)
    while True:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except OSError:
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.2)


class StoreGate:
    """Verrou du magasin partagé entre les tours d'UN processus (le service du chat).

    `flock` est par descripteur : deux tours simultanés du même service se bloqueraient entre eux.
    On compte donc les tours en cours : le premier prend le verrou, le dernier le rend.
    """

    def __init__(self, data_dir: str) -> None:
        self.data_dir = data_dir
        self._mutex = threading.Lock()
        self._count = 0
        self._fd: Optional[int] = None

    def acquire(self, timeout_s: float) -> bool:
        with self._mutex:
            if self._count == 0:
                fd = _open_lock(self.data_dir)
                if not _flock_wait(fd, timeout_s):
                    os.close(fd)
                    return False
                self._fd = fd
            self._count += 1
            return True

    def release(self) -> None:
        with self._mutex:
            if self._count <= 0:
                return
            self._count -= 1
            if self._count == 0 and self._fd is not None:
                os.close(self._fd)   # ferme le descripteur = rend le verrou
                self._fd = None


def cmd_with_lock(args: argparse.Namespace) -> int:
    command = list(args.command)
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        sys.stderr.write("with-lock : aucune commande à exécuter.\n")
        return EXIT_USAGE
    data_dir = resolve_data_dir(args.data_dir)
    try:
        fd = _open_lock(data_dir)
    except OSError as exc:
        sys.stderr.write("with-lock : magasin illisible (%s).\n" % (exc.strerror or exc))
        return EXIT_USAGE
    if not _flock_wait(fd, args.timeout):
        os.close(fd)
        sys.stderr.write("with-lock : le magasin d'authentification est utilisé par un autre processus du coach "
                         "(délai de %d s dépassé).\n" % args.timeout)
        return EXIT_LOCK_TIMEOUT
    try:
        proc = subprocess.Popen(command)
    except OSError as exc:
        sys.stderr.write("with-lock : commande impossible (%s).\n" % (exc.strerror or exc))
        os.close(fd)
        return 127

    def forward(signum: int, _frame: Any) -> None:
        try:
            proc.send_signal(signum)
        except OSError:
            pass

    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, forward)
    try:
        return proc.wait()
    finally:
        os.close(fd)


# -- connexion (OpenCode) ---------------------------------------------------------

def _clean(text: str) -> str:
    return "".join(ch for ch in _ANSI_RE.sub("", text) if ch >= " " or ch == "\t").strip()


def _kill_group(proc: "subprocess.Popen[Any]") -> None:
    """Arrête le processus enfant ET son groupe (un login orphelin garde le port 1455 ouvert)."""
    if proc.poll() is not None:
        return
    for sig, wait_s in ((signal.SIGTERM, 3.0), (signal.SIGKILL, 3.0)):
        try:
            os.killpg(proc.pid, sig)
        except OSError:
            try:
                proc.send_signal(sig)
            except OSError:
                pass
        try:
            proc.wait(timeout=wait_s)
            return
        except subprocess.TimeoutExpired:
            continue


def _opencode_binary(explicit: Optional[str]) -> Optional[str]:
    return explicit or os.environ.get("ARC_OPENCODE_BIN") or shutil.which("opencode")


def cmd_login(args: argparse.Namespace) -> int:
    out = Out(args.json)
    entry = provider(args.provider)
    if entry is None or entry["kind"] != "subscription":
        out.final(False, "Fournisseur inconnu : %s (chatgpt ou copilot)." % args.provider, error="usage")
        return EXIT_USAGE
    if os.environ.get("ARC_HEADLESS"):
        out.final(False, "Connexion refusée en exécution sans surveillance (ARC_HEADLESS) : lancez-la vous-même "
                  "dans un terminal.", error="headless")
        return EXIT_USAGE
    binary = _opencode_binary(args.opencode_bin)
    if not binary:
        out.final(False, "OpenCode n'est pas installé (binaire « opencode » introuvable) : "
                  "curl -fsSL https://opencode.ai/v2/install | bash", error="opencode_missing")
        return EXIT_USAGE
    data_dir = resolve_data_dir(args.data_dir)
    try:
        ensure_data_dir(data_dir)
    except OSError as exc:
        out.final(False, "Impossible de créer %s : %s" % (data_dir, exc.strerror or exc), error="write")
        return EXIT_USAGE
    method = entry["login_method_browser"] if args.browser else entry["login_method"]
    cmd = [binary, "providers", "login", "-p", entry["opencode_provider"], "-m", method]
    env = dict(os.environ, XDG_DATA_HOME=data_dir)
    interactive = sys.stdin.isatty() and sys.stdout.isatty() and not args.json
    # Copilot pose une question de menu (type de déploiement) : il lui faut un terminal. Dans un
    # terminal, on lui laisse la main (GitHub Enterprise compris) ; sans terminal (application),
    # on répond « GitHub.com » à la place de l'athlète dans un pseudo-terminal.
    if entry["id"] == "copilot" and interactive:
        out.event("login_start", "Connexion à %s dans ce terminal (magasin : %s)…" % (entry["plan_label"], data_dir))
        try:
            rc = subprocess.run(cmd, env=env).returncode
        except OSError as exc:
            out.final(False, "OpenCode est inutilisable (%s)." % (exc.strerror or exc), error="opencode_missing")
            return EXIT_USAGE
        return _login_result(out, entry, data_dir, rc)
    return _login_relay(out, entry, cmd, env, data_dir, args, use_pty=(entry["id"] == "copilot"))


def _login_result(out: Out, entry: Dict[str, Any], data_dir: str, rc: int, tail: str = "") -> int:
    status = auth_status(data_dir, entry["opencode_provider"])
    if rc == 0 and status["present"]:
        out.final(True, "%s connecté (jeton enregistré dans %s, mode 700)." % (entry["plan_label"], data_dir),
                  provider=entry["id"], data_dir=data_dir)
        return EXIT_OK
    if "port 1455" in tail:
        out.final(False, "Le port 1455 est occupé par une autre connexion ChatGPT en cours : fermez-la puis relancez.",
                  error="port_busy")
        return EXIT_EXCHANGE
    out.final(False, "Connexion %s non terminée (code %d) : relancez « %s »." % (entry["plan_label"], rc, reconnect_hint(entry)),
              error="denied", exit_code=rc)
    return EXIT_DENIED


def _login_relay(out: Out, entry: Dict[str, Any], cmd: List[str], env: Dict[str, str],
                 data_dir: str, args: argparse.Namespace, use_pty: bool) -> int:
    master = None
    try:
        if use_pty:
            import pty
            master, slave = pty.openpty()
            proc = subprocess.Popen(cmd, env=env, stdin=slave, stdout=slave, stderr=slave, start_new_session=True)
            os.close(slave)
            read_fd = master
        else:
            proc = subprocess.Popen(cmd, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, start_new_session=True)
            read_fd = proc.stdout.fileno()  # type: ignore[union-attr]
    except OSError as exc:
        out.final(False, "OpenCode est inutilisable (%s)." % (exc.strerror or exc), error="opencode_missing")
        return EXIT_USAGE

    def on_signal(signum: int, _frame: Any) -> None:
        raise KeyboardInterrupt

    previous = {sig: signal.signal(sig, on_signal) for sig in (signal.SIGTERM, signal.SIGINT)}
    url = code = None
    tail = ""
    answered = False
    pending = ""
    deadline = time.monotonic() + args.timeout
    out.event("login_start", "Connexion à %s… (magasin : %s)" % (entry["plan_label"], data_dir))
    try:
        while True:
            if time.monotonic() > deadline:
                _kill_group(proc)
                out.final(False, "Délai dépassé (%d s) sans validation : relancez « %s »." % (args.timeout, reconnect_hint(entry)),
                          error="timeout")
                return EXIT_TIMEOUT
            ready, _, _ = select.select([read_fd], [], [], 0.5)
            chunk = b""
            if ready:
                try:
                    chunk = os.read(read_fd, 4096)
                except OSError:
                    chunk = b""
                if not chunk:   # fin du flux
                    break
            elif proc.poll() is not None:
                break
            pending += chunk.decode("utf-8", "replace")
            lines = re.split(r"[\r\n]+", pending)
            pending = lines.pop()   # fin de ligne incomplète
            for raw in lines + ([pending] if COPILOT_DEPLOYMENT_PROMPT in pending.lower() else []):
                line = _clean(raw)
                if not line:
                    continue
                tail = (tail + " " + line)[-400:]
                if use_pty and not answered and COPILOT_DEPLOYMENT_PROMPT in line.lower():
                    answered = True
                    os.write(master, b"\r")    # 1er choix du menu : GitHub.com (Public)
                match = _URL_RE.search(line)
                if match and match.group(1) != url:
                    url = match.group(1)
                    out.event("login_url", "Ouvrez cette adresse : " + url, url=url)
                match = _CODE_RE.search(line)
                if match and match.group(1) != code:
                    code = match.group(1)
                    out.event("login_code", "Saisissez ce code : " + code, code=code)
                if url and code and not getattr(proc, "_arc_opened", False):
                    proc._arc_opened = True    # type: ignore[attr-defined]
                    if not args.no_browser:
                        try:
                            webbrowser.open(url)
                        except Exception:
                            pass
        try:
            rc = proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            _kill_group(proc)
            rc = proc.returncode if proc.returncode is not None else 1
        return _login_result(out, entry, data_dir, rc, tail)
    except KeyboardInterrupt:
        _kill_group(proc)
        out.final(False, "Connexion annulée.", error="denied")
        return EXIT_DENIED
    finally:
        _kill_group(proc)
        for sig, handler in previous.items():
            signal.signal(sig, handler)
        if master is not None:
            try:
                os.close(master)
            except OSError:
                pass
        if proc.stdout is not None:
            proc.stdout.close()


def cmd_auth_status(args: argparse.Namespace) -> int:
    entry = provider(args.provider)
    if entry is None or entry["kind"] != "subscription":
        sys.stderr.write("Fournisseur inconnu : %s (chatgpt ou copilot).\n" % args.provider)
        return EXIT_USAGE
    status = auth_status(resolve_data_dir(args.data_dir), entry["opencode_provider"])
    if args.json:
        print(json.dumps(dict(provider=entry["id"], **status), ensure_ascii=False))
    else:
        print("%s : %s" % (entry["plan_label"], "connecté" if status["present"] else "non connecté (%s)" % reconnect_hint(entry)))
    return EXIT_OK if status["present"] else 1


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

    sl = sub.add_parser("login", help="connexion d'un abonnement ChatGPT ou GitHub Copilot (via OpenCode)")
    sl.add_argument("provider", choices=("chatgpt", "copilot"))
    sl.add_argument("--data-dir", help="magasin d'authentification OpenCode du coach (défaut : %s)" % default_data_dir())
    sl.add_argument("--json", action="store_true", help="un objet JSON final ; adresse et code en lignes JSON sur stderr")
    sl.add_argument("--browser", action="store_true",
                    help="ChatGPT : connexion par le navigateur de CETTE machine (port 1455) au lieu du code d'appareil")
    sl.add_argument("--no-browser", action="store_true", help="n'ouvre pas le navigateur, affiche l'adresse et le code")
    sl.add_argument("--timeout", type=int, default=LOGIN_TIMEOUT_S, help="secondes d'attente de la validation (défaut 600)")
    sl.add_argument("--opencode-bin", help="binaire opencode (défaut : $ARC_OPENCODE_BIN ou le PATH)")
    sl.set_defaults(func=cmd_login)

    sk = sub.add_parser("with-lock", help="exécute une commande sous le verrou du magasin d'authentification")
    sk.add_argument("--data-dir", help="magasin d'authentification (défaut : %s)" % default_data_dir())
    sk.add_argument("--timeout", type=int, default=300, help="secondes d'attente du verrou (défaut 300)")
    sk.add_argument("command", nargs=argparse.REMAINDER, help="-- COMMANDE [ARGUMENTS…]")
    sk.set_defaults(func=cmd_with_lock)

    sa = sub.add_parser("auth-status", help="le jeton d'abonnement est-il présent ? (jamais sa valeur)")
    sa.add_argument("provider", choices=("chatgpt", "copilot"))
    sa.add_argument("--data-dir")
    sa.add_argument("--json", action="store_true")
    sa.set_defaults(func=cmd_auth_status)
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
