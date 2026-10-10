#!/usr/bin/env python3
"""Service HTTP du chat coach : sessions, flux SSE, approbations, budget.

Processus SÉPARÉ de `arc_serve.py` (le tableau de bord reste en lecture seule et
sans clé d'API). Il parle au navigateur avec le protocole d'événements de
`scripts/arc_chat_backend.py` et délègue le modèle à un backend (`mock`,
`claude`, `opencode`). Contrat complet : `deploy/chat/SPEC.md`.

    arc_chat.py [--workspace DIR] [--port N] [--listen ADRESSE] [--backend NOM]

La ligne `URL: http://127.0.0.1:<port>/` est imprimée dès que le serveur écoute
(`--port 0` : port choisi par le système, tests).

Sécurité (deploy/chat/PLAN.md §2.4) :
- `auth = "local"` : loopback uniquement, aucune identité ; le service refuse de
  démarrer si `listen` n'est pas une adresse de boucle locale.
- `auth = "proxy"` : la source doit appartenir à `trusted_proxies` et porter
  l'en-tête d'identité posé par le forward-auth (`auth_header`), présent dans
  `allowed_users` quand la liste n'est pas vide.
- Toute requête POST exige `X-ARC-Chat: 1` ; un `Origin` présent doit égaler
  l'hôte, un `Sec-Fetch-Site` présent doit valoir `same-origin`. Aucun CORS.
- L'en-tête Host est vérifié (`allowed_hosts`, sinon `public_url` + boucle locale).
- Les clés d'API viennent de `~/.config/ai-running-coach/llm.env` (jamais du TOML).
  Rien de secret ni de médical n'est journalisé.

Persistance sous `<workspace>/.arc/chat/` (jetable, gitignoré) : sessions,
approbations, dépense du jour.

Bibliothèque standard uniquement (CONTRIBUTING.md).
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import ipaddress
import json
import os
import queue
import re
import secrets
import signal
import socket
import socketserver
import sys
import threading
import time
import traceback
import urllib.error
import urllib.request
from collections import deque
from datetime import date, datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
from arc_chat_backend import (EVENT_TYPES, BackendError, ChatBackend, TurnContext,  # noqa: E402
                              load_backend, payload_hash)
from arc_chat_policy import Policy  # noqa: E402
from coach_config import ConfigError, read_toml  # noqa: E402

ENGINE = Path(__file__).resolve().parent.parent
LOOPBACK_HOSTS = ("127.0.0.1", "localhost", "::1")
API = "/api/chat"
PING_INTERVAL_S = float(os.environ.get("ARC_CHAT_PING_S", "15"))
MAX_BODY_BYTES = 64 * 1024
MAX_TEXT_CHARS = 8000
ID_RE = re.compile(r"^[A-Za-z0-9_-]{6,40}$")
ISO = "%Y-%m-%dT%H:%M:%SZ"
APPROVE_PER_IP_PER_MIN = 30          # route à jeton : essais par minute et par adresse cliente
APPROVE_GLOBAL_PER_MIN = 120         # plafond global, toutes adresses confondues

# Valeurs par défaut de `[chat]` (config/workspace.toml peut les surcharger ; ce
# tableau garde le service utilisable même si la section n'y est pas encore).
CHAT_DEFAULTS = {
    "enabled": False, "backend": "claude", "model": "claude-sonnet-5-5", "base_url": "",
    "api_key_env": "ANTHROPIC_API_KEY", "port": 8766, "listen": "127.0.0.1",
    "auth": "local", "auth_header": "X-authentik-username", "allowed_users": [],
    "trusted_proxies": ["127.0.0.1"], "allowed_hosts": [], "public_url": "",
    "daily_budget_eur": 2.0, "usd_eur_rate": 0.92, "max_turns": 30, "rate_limit_per_min": 6,
    "approval_wait_s": 600, "approval_ttl_s": 86400, "ntfy_approvals": True,
    "ntfy_quick_approve": True, "ntfy_token_ttl_s": 1800,
    # Délai avant le push ntfy quand un onglet est attaché (SPEC : 60 s). Clé propre au service.
    "ntfy_delay_s": 60,
    # Plafond d'allocation d'un tour (€, 0 = tout le reste du jour, réservé au tour). Voir reserve_turn_budget.
    "turn_budget_max_eur": 1.0,
}


def log(message: str) -> None:
    """Journal sur stderr : jamais de jeton, de clé ni de contenu de santé."""
    print(f"arc_chat: {message}", file=sys.stderr, flush=True)


def iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).strftime(ISO)


# ---------------------------------------------------------------------------
# Configuration et environnement
# ---------------------------------------------------------------------------

def _merged_sections(workspace: Path) -> dict:
    """workspace.toml puis workspace.user.toml, clé par clé (même règle que config.sh)."""
    shared = workspace / "config/workspace.toml"
    if not shared.exists():
        shared = ENGINE / "config/workspace.toml"
    merged: dict = {}
    for path in (shared, workspace / "config/workspace.user.toml"):
        for section, values in read_toml(path).items():
            if isinstance(values, dict):
                merged.setdefault(section, {}).update(values)
    return merged


def _coerce(default, value):
    """Ramène une valeur TOML au type du défaut (le repli TOML < 3.11 rend les flottants en chaînes)."""
    try:
        if isinstance(default, bool):
            return value if isinstance(value, bool) else str(value).strip().lower() in ("1", "true", "yes")
        if isinstance(default, int):
            return int(float(value))
        if isinstance(default, float):
            return float(value)
        if isinstance(default, list):
            return [str(v) for v in value] if isinstance(value, (list, tuple)) else ([str(value)] if value else [])
        return str(value)
    except (TypeError, ValueError):
        return default


def load_chat_config(workspace: Path, sections: Optional[dict] = None) -> dict:
    """Section `[chat]` résolue : défauts du service < workspace.toml < workspace.user.toml."""
    raw = (sections if sections is not None else _merged_sections(workspace)).get("chat", {})
    cfg = dict(CHAT_DEFAULTS)
    for key, value in raw.items():
        cfg[key] = _coerce(CHAT_DEFAULTS[key], value) if key in CHAT_DEFAULTS else value
    return cfg


def load_language(workspace: Path, sections: Optional[dict] = None) -> str:
    """Langue des documents : `[language].documents` (défaut « fr »), pas `[chat]`."""
    raw = (sections if sections is not None else _merged_sections(workspace)).get("language", {})
    return str(raw.get("documents") or "fr").strip().lower() or "fr"


def load_notifications(workspace: Path, sections: Optional[dict] = None) -> dict:
    """Section `[notifications]` (ntfy) — mêmes clés que `scripts/notify.sh`."""
    raw = (sections if sections is not None else _merged_sections(workspace)).get("notifications", {})
    token_file = str(raw.get("ntfy_token_file") or "")
    return {
        "provider": str(raw.get("provider") or "none"),
        "ntfy_url": str(raw.get("ntfy_url") or "https://ntfy.sh").rstrip("/"),
        "ntfy_topic": str(raw.get("ntfy_topic") or ""),
        "ntfy_token_file": os.path.expanduser(token_file) if token_file else "",
    }


def parse_llm_env(text: str) -> dict:
    """Lignes `CLE=valeur` ; commentaires `#`, lignes vides, `export ` et guillemets tolérés."""
    values = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        key, sep, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if not sep or not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", key):
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key] = value
    return values


def load_llm_env(path: Optional[Path] = None, environ=None) -> tuple:
    """Charge `~/.config/ai-running-coach/llm.env` dans l'environnement ; renvoie (clés posées, avertissements).

    Une variable déjà présente n'est jamais écrasée. Un fichier lisible par d'autres que
    son propriétaire déclenche un avertissement (pas un refus). Les valeurs ne sont pas journalisées.
    """
    environ = os.environ if environ is None else environ
    path = Path(path) if path else Path(environ.get("ARC_LLM_ENV") or "~/.config/ai-running-coach/llm.env").expanduser()
    loaded, warnings = [], []
    if not path.is_file():
        return loaded, warnings
    try:
        if path.stat().st_mode & 0o077:
            warnings.append(f"{path} est lisible par d'autres utilisateurs — chmod 600 recommandé")
        values = parse_llm_env(path.read_text(encoding="utf-8"))
    except OSError as exc:
        return loaded, [f"{path} illisible ({exc.strerror})"]
    for key, value in values.items():
        if key not in environ:
            environ[key] = value
            loaded.append(key)
    return loaded, warnings


# ---------------------------------------------------------------------------
# Sécurité HTTP : Host, authentification, CSRF
# ---------------------------------------------------------------------------

def host_allowlist(port: int, cfg: dict) -> set:
    """En-têtes Host acceptés : boucle locale, `allowed_hosts`, à défaut le nom de `public_url`."""
    hosts = {f"127.0.0.1:{port}", f"localhost:{port}", f"[::1]:{port}"}
    if cfg.get("auth", "local") == "local":
        # En mode local, la page vient du tableau de bord (autre port) qui relaie
        # `/api/chat/*` en conservant son propre Host : tout nom de boucle locale,
        # quel que soit le port, est accepté. Jamais en mode proxy.
        hosts.update({"127.0.0.1", "localhost", "[::1]"})
    declared = [h for h in cfg.get("allowed_hosts", []) if str(h).strip()]
    if not declared and cfg.get("public_url"):
        declared = [urlparse(cfg["public_url"]).netloc]
    for name in declared:
        hosts.add(str(name).strip().lower())
    return hosts


def host_ok(host_header: str, allowed: set) -> bool:
    host = (host_header or "").lower()
    return host in allowed or host.rsplit(":", 1)[0] in allowed


def is_loopback(ip: str) -> bool:
    try:
        return ipaddress.ip_address(ip).is_loopback
    except ValueError:
        return False


# Noms d'hôte de `trusted_proxies` (ex. le conteneur « traefik » sur un réseau Docker, dont
# l'adresse change à chaque recréation) : résolus par le DNS, gardés quelques secondes.
HOST_CACHE_TTL_S = 30.0
_host_cache: dict = {}
_host_cache_lock = threading.Lock()


def resolve_host(name: str) -> frozenset:
    """Adresses IP de `name` (cache court) ; ensemble vide si le nom ne se résout pas."""
    now = time.monotonic()
    with _host_cache_lock:
        hit = _host_cache.get(name)
        if hit and now - hit[0] < HOST_CACHE_TTL_S:
            return hit[1]
    try:
        found = frozenset(info[4][0] for info in socket.getaddrinfo(name, None, proto=socket.IPPROTO_TCP))
    except (OSError, UnicodeError):
        found = frozenset()
    with _host_cache_lock:
        _host_cache[name] = (now, found)
    return found


def ip_in(ip: str, entries) -> bool:
    """Vrai si `ip` est l'une des adresses, l'un des réseaux (CIDR) ou l'un des noms d'hôte
    (résolus par le DNS, voir `resolve_host`) de `entries`."""
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    for entry in entries:
        entry = str(entry).strip()
        if not entry:
            continue
        try:
            if addr in ipaddress.ip_network(entry, strict=False):
                return True
            continue
        except ValueError:
            pass
        for resolved in resolve_host(entry):
            try:
                if addr == ipaddress.ip_address(resolved.split("%", 1)[0]):
                    return True
            except ValueError:
                continue
    return False


def authenticate(cfg: dict, peer_ip: str, headers, exempt_identity: bool = False,
                 health_from_loopback: bool = False) -> tuple:
    """(utilisateur, statut, message). Statut 0 = accepté.

    `exempt_identity` : route à jeton (`/approve/…`), sans en-tête d'identité mais avec
    contrôle de la source. `health_from_loopback` : `/healthz` depuis la boucle locale.
    """
    if health_from_loopback and is_loopback(peer_ip):
        return "healthz", 0, ""
    if cfg["auth"] == "local":
        if not is_loopback(peer_ip):
            return None, 403, "Accès refusé : ce service n'accepte que la boucle locale."
        return "local", 0, ""
    if not ip_in(peer_ip, cfg["trusted_proxies"]):
        return None, 403, "Accès refusé : source non autorisée."
    if exempt_identity:
        return "token", 0, ""
    user = (headers.get(cfg["auth_header"]) or "").strip()
    if not user:
        return None, 401, "Authentification requise."
    if cfg["allowed_users"] and user not in cfg["allowed_users"]:
        return None, 403, "Utilisateur non autorisé."
    return user, 0, ""


def client_ip(cfg: dict, peer_ip: str, headers) -> str:
    """Adresse cliente pour la limite de débit : derrière le proxy de confiance, la dernière
    entrée de `X-Forwarded-For` (celle qu'il a ajoutée) ; sinon l'adresse du pair."""
    if cfg.get("auth") == "proxy" and ip_in(peer_ip, cfg.get("trusted_proxies", [])):
        forwarded = (headers.get("X-Forwarded-For") or "").split(",")[-1].strip()
        try:
            return str(ipaddress.ip_address(forwarded))
        except ValueError:
            pass
    return peer_ip


def check_csrf(headers, token_route: bool = False) -> Optional[str]:
    """Message d'erreur si la requête POST ne respecte pas les règles CSRF, sinon None."""
    if headers.get("X-ARC-Chat") != "1":
        return "En-tête X-ARC-Chat manquant."
    if token_route:
        return None
    origin = headers.get("Origin")
    if origin is not None and (urlparse(origin).netloc.lower() != (headers.get("Host") or "").lower()):
        return "Origine refusée."
    site = headers.get("Sec-Fetch-Site")
    if site is not None and site != "same-origin":
        return "Requête inter-sites refusée."
    return None


class RateLimiter:
    """Fenêtre glissante d'une minute par utilisateur (tours par minute)."""

    PRUNE_EVERY_S = 5.0          # balayage des seaux périmés (le dictionnaire reste borné par la fenêtre)

    def __init__(self, per_min: int, clock=time.monotonic):
        self.per_min = per_min
        self.clock = clock
        self._hits: dict = {}
        self._last_prune = clock()
        self._lock = threading.Lock()

    def _prune(self, now: float) -> None:
        """Retire les clés dont tous les essais sont sortis de la fenêtre (sous verrou)."""
        if now - self._last_prune < self.PRUNE_EVERY_S:
            return
        self._last_prune = now
        for key in [k for k, hits in self._hits.items() if not hits or now - hits[-1] >= 60]:
            del self._hits[key]

    def peek(self, key: str) -> bool:
        """Un essai serait-il accepté ? N'enregistre rien (pour combiner plusieurs limites)."""
        if self.per_min <= 0:
            return True
        now = self.clock()
        with self._lock:
            hits = self._hits.get(key)
            if not hits:
                return True
            return sum(1 for t in hits if now - t < 60) < self.per_min

    def allow(self, key: str) -> bool:
        if self.per_min <= 0:
            return True
        now = self.clock()
        with self._lock:
            self._prune(now)
            hits = self._hits.setdefault(key, deque())
            while hits and now - hits[0] >= 60:
                hits.popleft()
            if len(hits) >= self.per_min:
                return False
            hits.append(now)
            return True


# ---------------------------------------------------------------------------
# Persistance : `.arc/chat/`
# ---------------------------------------------------------------------------

def _atomic_write(path: Path, data: dict) -> None:
    tmp = path.with_name(path.name + f".{os.getpid()}.{threading.get_ident()}.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


def _read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


class SpendStore:
    """Dépense du chat du jour (`spend-AAAA-MM-JJ.json`, `{"chat_eur": x}`)."""

    def __init__(self, directory: Path, today=date.today):
        self.dir = directory
        self.today = today
        self._lock = threading.Lock()

    def _path(self) -> Path:
        return self.dir / f"spend-{self.today().isoformat()}.json"

    def spent(self) -> float:
        with self._lock:
            return float(_read_json(self._path(), {}).get("chat_eur", 0.0) or 0.0)

    def add(self, eur: float) -> float:
        if eur <= 0:
            return self.spent()
        with self._lock:
            data = _read_json(self._path(), {})
            data["chat_eur"] = round(float(data.get("chat_eur", 0.0) or 0.0) + eur, 6)
            _atomic_write(self._path(), data)
            return data["chat_eur"]


class SessionStore:
    """`sessions/<id>.json` (méta) et `sessions/<id>.jsonl` (un événement par ligne)."""

    def __init__(self, directory: Path):
        self.dir = directory / "sessions"
        self.dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    def _meta_path(self, sid: str) -> Path:
        return self.dir / f"{sid}.json"

    def create(self, backend: str, model: str) -> dict:
        now = iso(time.time())
        meta = {"id": secrets.token_urlsafe(12), "title": "", "created": now, "updated": now,
                "backend": backend, "model": model, "backend_state": {}, "cost_eur": 0.0}
        with self._lock:
            _atomic_write(self._meta_path(meta["id"]), meta)
        return meta

    def get(self, sid: str) -> Optional[dict]:
        if not ID_RE.match(sid or ""):
            return None
        return _read_json(self._meta_path(sid), None)

    def save(self, meta: dict) -> None:
        with self._lock:
            meta["updated"] = iso(time.time())
            _atomic_write(self._meta_path(meta["id"]), meta)

    def update(self, sid: str, **changes) -> Optional[dict]:
        """Lecture-modification-écriture atomique de la méta (titre, coût, état du backend)."""
        with self._lock:
            meta = self.get(sid)
            if meta is None:
                return None
            for key, value in changes.items():
                if key == "add_cost":
                    meta["cost_eur"] = round(float(meta.get("cost_eur", 0.0)) + value, 6)
                elif key == "title" and meta.get("title"):
                    continue                              # le titre reste celui du premier message
                else:
                    meta[key] = value
            self.save(meta)
            return meta

    def list(self) -> list:
        metas = [_read_json(p, None) for p in self.dir.glob("*.json")]
        return sorted((m for m in metas if m), key=lambda m: m.get("updated", ""), reverse=True)

    def append_event(self, sid: str, etype: str, data: dict) -> None:
        line = json.dumps({"ts": iso(time.time()), "type": etype, "data": data}, ensure_ascii=False)
        with self._lock:
            with open(self.dir / f"{sid}.jsonl", "a", encoding="utf-8") as handle:
                handle.write(line + "\n")

    def events(self, sid: str) -> list:
        path = self.dir / f"{sid}.jsonl"
        if not path.is_file():
            return []
        events = []
        with self._lock:
            for line in path.read_text(encoding="utf-8").splitlines():
                try:
                    events.append(json.loads(line))
                except ValueError:
                    continue
        return events


OPEN_STATUSES = ("waiting", "pending")


def token_digest(approval_id: str, phash: str, secret: str) -> str:
    """Empreinte stockée d'un jeton : liée à l'identifiant ET à la charge exacte de l'appel."""
    return hashlib.sha256(f"{approval_id}|{phash}|{secret}".encode("utf-8")).hexdigest()


class ApprovalStore:
    """`approvals.json` : propositions en attente, décisions, jetons ntfy (hachés uniquement).

    Statuts : `waiting` (le tour attend), `pending` (le tour est terminé, la proposition reste
    ouverte), puis `allowed`, `denied`, `expired`, `cancelled` (tour interrompu pendant l'attente)
    ou `unexecuted` (approuvée mais la reprise n'a pas pu l'exécuter). Un jeton est
    `<id>.<secret>` ; seul `sha256(id|hash_charge|secret)` est conservé, et les DEUX jetons
    (appliquer/refuser) sont brûlés à la première décision, quelle que soit sa voie.

    `on_expired(liste)` est appelé (hors verrou) par QUICONQUE fait expirer des propositions
    — lecture, liste, décision, vérification de jeton ou balayage — pour que l'événement
    `approval_resolved: expired` atteigne toujours le journal de la session.
    """

    def __init__(self, path: Path, clock=time.time, on_expired=None):
        self.path = path
        self.clock = clock
        self.on_expired = on_expired
        self._lock = threading.RLock()

    def _load(self) -> dict:
        return _read_json(self.path, {})

    def _save(self, data: dict) -> None:
        _atomic_write(self.path, data)

    def create(self, session_id: str, tool: str, tool_input: dict, summary: str, diff: list,
               ttl_s: float, token_ttl_s: Optional[float] = None) -> tuple:
        """Crée une proposition ; renvoie (enregistrement, {"allow": jeton, "deny": jeton}).

        Les jetons ne sont renvoyés qu'ici (jamais stockés en clair) ; `token_ttl_s=None` : aucun jeton.
        """
        now = self.clock()
        approval_id = secrets.token_urlsafe(12)
        phash = payload_hash(tool, tool_input)
        tokens, hashes = {}, {}
        if token_ttl_s is not None:
            for action in ("allow", "deny"):
                secret = secrets.token_urlsafe(24)
                tokens[action] = f"{approval_id}.{secret}"
                hashes[action] = token_digest(approval_id, phash, secret)
        record = {
            "session_id": session_id, "tool": tool, "input": tool_input, "hash": phash,
            "summary": summary, "diff": diff, "status": "waiting",
            "created": iso(now), "expires_at": iso(now + ttl_s), "expires_ts": now + ttl_s,
            "token_expires_ts": now + (token_ttl_s or 0), "token_hashes": hashes, "burned_hashes": {},
        }
        with self._lock:
            data = self._load()
            data[approval_id] = record
            self._save(data)
        return dict(record, id=approval_id), tokens

    def get(self, approval_id: str) -> Optional[dict]:
        if not ID_RE.match(approval_id or ""):
            return None
        self.expire_due()
        record = self._load().get(approval_id)
        return dict(record, id=approval_id) if record else None

    def list(self, session_id: Optional[str] = None) -> list:
        self.expire_due()
        return [dict(rec, id=aid) for aid, rec in self._load().items()
                if session_id is None or rec.get("session_id") == session_id]

    def expire_due(self) -> list:
        """Passe en `expired` les propositions ouvertes dont le délai est écoulé ; les renvoie."""
        expired = []
        with self._lock:
            data = self._load()
            now = self.clock()
            for aid, rec in data.items():
                if rec["status"] in OPEN_STATUSES and rec["expires_ts"] <= now:
                    self._close(rec, "expired")
                    expired.append(dict(rec, id=aid))
            if expired:
                self._save(data)
        if expired and self.on_expired is not None:
            try:
                self.on_expired(expired)
            except Exception:                                        # noqa: BLE001 — jamais bloquant
                log("rappel d'expiration : erreur\n" + traceback.format_exc())
        return expired

    @staticmethod
    def _close(rec: dict, status: str) -> None:
        rec["status"] = status
        rec["resolved_at"] = iso(time.time())
        rec["resolved_ts"] = time.time()
        rec["burned_hashes"] = dict(rec.get("token_hashes") or {}) or rec.get("burned_hashes", {})
        rec["token_hashes"] = {}                                     # brûle les deux jetons

    def mark_pending(self, approval_id: str) -> bool:
        with self._lock:
            data = self._load()
            rec = data.get(approval_id)
            if not rec or rec["status"] != "waiting":
                return False
            rec["status"] = "pending"
            self._save(data)
            return True

    def resolve(self, approval_id: str, decision: str) -> tuple:
        """(résultat, enregistrement) ; résultat : ok | unknown | closed | expired.

        `decision` : allow | deny | cancelled (tour interrompu). Une approbation tardive (la
        proposition était `pending`) est marquée `resume = "queued"` : elle reste à exécuter
        tant que la reprise de la session n'a pas abouti (voir `set_resume`).
        """
        self.expire_due()
        with self._lock:
            data = self._load()
            rec = data.get(approval_id)
            if rec is None:
                return "unknown", None
            if rec["status"] not in OPEN_STATUSES:
                return ("expired" if rec["status"] == "expired" else "closed"), dict(rec, id=approval_id)
            previous = rec["status"]
            self._close(rec, {"allow": "allowed", "cancelled": "cancelled"}.get(decision, "denied"))
            if decision == "allow" and previous == "pending":
                rec["resume"] = "queued"
            self._save(data)
            return "ok", dict(rec, id=approval_id, previous_status=previous)

    def set_resume(self, approval_id: str, state: str, status: Optional[str] = None) -> None:
        """Suivi de la reprise d'une approbation tardive : `queued` → `running` → `done` | `failed` (+ statut visible)."""
        with self._lock:
            data = self._load()
            rec = data.get(approval_id)
            if rec is None:
                return
            rec["resume"] = state
            if status:
                rec["status"] = status
            self._save(data)

    def resumes_in_state(self, state: str) -> list:
        """Approbations acceptées dont la reprise est dans l'état `state` (`queued` | `running`)."""
        with self._lock:
            return [dict(rec, id=aid) for aid, rec in self._load().items()
                    if rec.get("status") == "allowed" and rec.get("resume") == state]

    def queued_resumes(self) -> list:
        """Approbations tardives acceptées dont la reprise n'a pas (encore) eu lieu."""
        return self.resumes_in_state("queued")

    def verify_token(self, token: str, action: str) -> tuple:
        """(résultat, enregistrement) ; résultat : ok | unknown | used | expired | mismatch.

        `mismatch` : le jeton était valide pour la charge d'origine, mais la charge stockée a
        changé depuis (un jeton ne peut pas approuver une autre modification).
        """
        approval_id, _, secret = (token or "").partition(".")
        if action not in ("allow", "deny") or not secret or not ID_RE.match(approval_id):
            return "unknown", None
        self.expire_due()
        rec = self._load().get(approval_id)
        if rec is None:
            return "unknown", None
        stored = token_digest(approval_id, rec["hash"], secret)
        burned = rec.get("burned_hashes", {}).get(action)
        if burned and hmac.compare_digest(burned, stored):
            return "used", dict(rec, id=approval_id)
        expected = (rec.get("token_hashes") or {}).get(action)
        if not expected:
            return "unknown", None
        if not hmac.compare_digest(expected, stored):
            return "unknown", None
        if payload_hash(rec["tool"], rec["input"]) != rec["hash"]:
            return "mismatch", dict(rec, id=approval_id)
        if rec["status"] not in OPEN_STATUSES:
            return "used", dict(rec, id=approval_id)
        if rec["token_expires_ts"] <= self.clock():
            return "expired", dict(rec, id=approval_id)
        return "ok", dict(rec, id=approval_id)

    def reopen_orphans(self) -> int:
        """Au démarrage : un tour `waiting` n'a plus de fil qui l'attend → `pending`."""
        with self._lock:
            data = self._load()
            count = 0
            for rec in data.values():
                if rec["status"] == "waiting":
                    rec["status"] = "pending"
                    count += 1
            if count:
                self._save(data)
        return count


# ---------------------------------------------------------------------------
# ntfy
# ---------------------------------------------------------------------------

def build_actions(public_url: str, approval_id: str, tokens: Optional[dict]) -> str:
    """En-tête `Actions` de ntfy : `view` (Ouvrir) et, si des jetons existent, `http` (Appliquer/Refuser)."""
    base = public_url.rstrip("/")
    actions = [f"view, Ouvrir, {base}/chat.html#approval={approval_id}"]
    if tokens:
        for label, action in (("Appliquer", "allow"), ("Refuser", "deny")):
            actions.append(f"http, {label}, {base}{API}/approve/{tokens[action]}/{action}, "
                           "method=POST, headers.X-ARC-Chat=1, clear=true")
    return "; ".join(actions)


def send_ntfy(notif: dict, title: str, body: str, actions: str = "", timeout: float = 10) -> bool:
    """Envoie une notification ntfy ; ne lève jamais (le service ne doit pas tomber pour un push)."""
    if notif.get("provider") != "ntfy" or not notif.get("ntfy_topic"):
        return False
    headers = {"Title": title, "Priority": "4", "Tags": "runner"}
    if actions:
        headers["Actions"] = actions
    if notif.get("ntfy_token_file"):
        try:
            token = Path(notif["ntfy_token_file"]).read_text(encoding="utf-8").strip()
            headers["Authorization"] = f"Bearer {token}"
        except OSError:
            log("ntfy : fichier token illisible")
            return False
    url = f"{notif['ntfy_url']}/{notif['ntfy_topic']}"
    request = urllib.request.Request(url, data=body.encode("utf-8"), headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout):
            return True
    except (urllib.error.URLError, OSError, ValueError) as exc:
        log(f"ntfy : envoi impossible ({type(exc).__name__})")
        return False


# ---------------------------------------------------------------------------
# Tours de conversation
# ---------------------------------------------------------------------------

class Turn:
    """Un tour en cours : journalise chaque événement et le diffuse aux flux SSE attachés."""

    def __init__(self, service: "ChatService", session_id: str):
        self.service = service
        self.session_id = session_id
        self.cancelled = threading.Event()
        self.subscribers: list = []
        self.terminal = False               # `done` ou `error` déjà émis
        self.pending_created = False
        self.finished = threading.Event()   # le backend est revenu : plus personne n'attend en ligne
        self.approval_ids: list = []        # propositions créées pendant ce tour
        self.spent_eur = 0.0
        self.lock = threading.Lock()

    def subscribe(self) -> "queue.Queue":
        q: queue.Queue = queue.Queue()
        with self.lock:
            self.subscribers.append(q)
        return q

    def unsubscribe(self, q) -> None:
        with self.lock:
            if q in self.subscribers:
                self.subscribers.remove(q)

    def emit(self, etype: str, data: dict) -> None:
        if etype not in EVENT_TYPES:
            log(f"événement inconnu ignoré : {etype}")
            return
        data = data if isinstance(data, dict) else {}
        with self.lock:
            if etype != "status":                   # passager : pas dans l'historique
                self.service.sessions.append_event(self.session_id, etype, data)
            if etype in ("done", "error"):
                self.terminal = True
            for q in list(self.subscribers):
                q.put((etype, data))
        if etype == "usage":
            self.service.record_usage(self.session_id, data, self)

    def close(self) -> None:
        with self.lock:
            for q in list(self.subscribers):
                q.put(None)


class ChatService:
    """État partagé par les requêtes : configuration, stockage, backend, tours, approbations."""

    def __init__(self, workspace: Path, cfg: dict, backend: ChatBackend, notif: Optional[dict] = None,
                 policy: Optional[Policy] = None, language: Optional[str] = None):
        self.workspace = Path(workspace)
        self.cfg = cfg
        self.language = language or load_language(self.workspace)
        self.backend = backend
        self.notif = notif if notif is not None else {"provider": "none"}
        self.policy = policy or Policy.load(ENGINE, self.workspace)
        root = self.workspace / ".arc" / "chat"
        root.mkdir(parents=True, exist_ok=True)
        os.chmod(root, 0o700)
        self.sessions = SessionStore(root)
        self.approvals = ApprovalStore(root / "approvals.json", on_expired=self._on_expired)
        self.spend = SpendStore(root)
        self.limiter = RateLimiter(int(cfg["rate_limit_per_min"]))
        self.approve_limiter = RateLimiter(APPROVE_PER_IP_PER_MIN)   # route à jeton : par adresse cliente
        self.approve_global = RateLimiter(APPROVE_GLOBAL_PER_MIN)    # … et plafond global
        self._lock = threading.Lock()
        self._slots: dict = {}                          # session_id → verrou « un tour à la fois »
        self.turns: dict = {}                           # session_id → Turn en cours
        self._waiters: dict = {}                        # approval_id → (Event, [décision])
        self._raw_tokens: dict = {}                     # approval_id → jetons en clair (mémoire seulement)
        self._notified: set = set()
        self._resumes: dict = {}                        # session_id → [enregistrements à reprendre] (FIFO)
        self._reserved: dict = {}                       # session_id → budget alloué au tour en cours (€)
        self._quick_warned = False
        self._drain_lock = threading.Lock()
        self.approvals.reopen_orphans()

    # -- dépense ---------------------------------------------------------------

    def record_usage(self, sid: str, data: dict, turn: Optional["Turn"] = None) -> None:
        try:
            eur = float(data.get("cost_eur") or 0.0)
        except (TypeError, ValueError):
            eur = 0.0
        if eur > 0:
            if turn is not None:
                turn.spent_eur += eur
            self.spend.add(eur)
            self.sessions.update(sid, add_cost=eur)

    def budget_exhausted(self) -> bool:
        return self.spend.spent() >= float(self.cfg["daily_budget_eur"])

    # -- tours -----------------------------------------------------------------

    def _slot(self, sid: str) -> threading.Lock:
        with self._lock:
            return self._slots.setdefault(sid, threading.Lock())

    def begin_turn(self, sid: str, user: str, text: str, preapproved=None, resume: bool = False,
                   resume_rec: Optional[dict] = None) -> tuple:
        """Démarre un tour. Renvoie (code, Turn|None, file d'événements|None).

        code : ok | busy (409) | rate (429) | unknown (404). Un tour de reprise (`resume`) n'entre
        pas dans la limite de débit ; si la session est occupée il renvoie `busy` et l'appelant
        (`_drain_resume`) le remet en file : il repart à la fin du tour en cours.
        """
        if self.sessions.get(sid) is None:
            return "unknown", None, None
        slot = self._slot(sid)
        if not slot.acquire(blocking=False):
            return "busy", None, None
        if not resume and not self.limiter.allow(user):
            slot.release()
            return "rate", None, None
        turn = Turn(self, sid)
        q = None if resume else turn.subscribe()
        with self._lock:
            self.turns[sid] = turn
        if resume_rec is not None:
            self.approvals.set_resume(resume_rec["id"], "running")   # dès ici : un redémarrage ne la rejouera pas
        self.sessions.append_event(sid, "user_message", {"text": text, **({"synthetic": True} if resume else {})})
        self.sessions.update(sid, title=re.sub(r"\s+", " ", text).strip()[:60] or "Conversation")
        threading.Thread(target=self._run_turn, args=(turn, text, set(preapproved or ()), resume_rec),
                         name=f"chat-turn-{sid[:6]}", daemon=True).start()
        return "ok", turn, q

    def remaining_budget(self) -> float:
        return max(0.0, float(self.cfg["daily_budget_eur"]) - self.spend.spent())

    def reserve_turn_budget(self, turn: Turn) -> float:
        """Budget alloué au tour : reste du jour moins ce que les AUTRES tours en cours ont encore
        en réserve (alloué − déjà dépensé). Plancher 0 ; réservé jusqu'à `release_turn_budget`.

        Sans cela, deux conversations simultanées recevraient chacune tout le reste du jour.
        `[chat].turn_budget_max_eur` (> 0) plafonne l'allocation d'un tour (permet la concurrence).
        """
        with self._lock:
            outstanding = sum(max(0.0, self._reserved[sid] - t.spent_eur)
                              for sid, t in self.turns.items() if sid != turn.session_id and sid in self._reserved)
            grant = max(0.0, self.remaining_budget() - outstanding)
            cap = float(self.cfg.get("turn_budget_max_eur") or 0.0)
            if cap > 0:
                grant = min(grant, cap)
            if grant > 0:
                self._reserved[turn.session_id] = grant
            return grant

    def release_turn_budget(self, sid: str) -> None:
        with self._lock:
            self._reserved.pop(sid, None)

    def _run_turn(self, turn: Turn, text: str, preapproved: set, resume_rec: Optional[dict] = None) -> None:
        sid = turn.session_id
        consumed: list = []                              # le hash pré-approuvé a-t-il servi ?
        failure = None                                   # raison d'échec d'une reprise
        try:
            grant = 0.0 if self.budget_exhausted() else self.reserve_turn_budget(turn)
            if grant <= 0:
                if self.budget_exhausted():
                    message = (f"Budget quotidien du chat atteint ({self.spend.spent():.2f} € sur "
                               f"{float(self.cfg['daily_budget_eur']):.2f} €). Réessaie demain ou relève "
                               "[chat].daily_budget_eur.")
                else:
                    message = ("Le budget restant du jour est réservé par une autre conversation en cours : "
                               "réessaie quand elle sera terminée.")
                turn.emit("error", {"message": message})
                turn.emit("done", {"reason": "budget"})
                failure = "budget quotidien atteint"
                return
            meta = self.sessions.get(sid) or {}
            state = meta.get("backend_state")
            state = state if isinstance(state, dict) else {}

            preapproved_lock = threading.Lock()

            def decide(tool, tool_input):
                # Une approbation = UNE exécution : le hash est retiré dès qu'il a servi (sous
                # verrou, les backends décident depuis plusieurs fils). Un second appel identique
                # dans la reprise repasse par « ask », donc par une nouvelle carte.
                verdict = self.policy.decide(tool, tool_input)
                if verdict != "ask" or not preapproved:
                    return verdict
                digest = payload_hash(tool, tool_input)
                with preapproved_lock:
                    if digest in preapproved:
                        preapproved.discard(digest)
                        consumed.append(digest)
                        return "allow"
                return verdict

            # Copie : le budget restant est propre au tour (les backends l'appliquent en cours de tour).
            config = dict(self.cfg, turn_budget_eur=grant)
            ctx = TurnContext(
                session_id=sid, workspace=self.workspace, config=config, emit=turn.emit,
                decide=decide,
                request_approval=lambda tool, tool_input, summary, diff: self._request_approval(
                    turn, tool, tool_input, summary, diff),
                cancelled=turn.cancelled, backend_state=state, language=self.language)
            try:
                self.backend.run_turn(ctx, text)
            finally:
                self.sessions.update(sid, backend_state=ctx.backend_state)
            if not turn.terminal:
                reason = ("interrupted" if turn.cancelled.is_set()
                          else "pending_approval" if turn.pending_created else "end_turn")
                turn.emit("done", {"reason": reason})
            if resume_rec is not None and not consumed:
                failure = "le modèle n'a pas exécuté l'appel approuvé"
                turn.emit("error", {"message": f"Proposition approuvée mais non exécutée : {failure}."})
        except BackendError as exc:
            turn.emit("error", {"message": str(exc)})
            failure = str(exc)
        except Exception:                                # noqa: BLE001 — jamais de trace vers le navigateur
            log("erreur inattendue dans un tour :\n" + traceback.format_exc())
            turn.emit("error", {"message": "Erreur interne du service de chat."})
            failure = "erreur interne du service"
        finally:
            turn.finished.set()
            self._settle_open_approvals(turn)            # `waiting` restées ouvertes → `pending`
            self.release_turn_budget(sid)
            with self._lock:
                self.turns.pop(sid, None)
            turn.close()
            self._slot(sid).release()
            if resume_rec is not None:
                if failure:
                    self._resume_failed(resume_rec, failure, emit_error=False)
                else:
                    self.approvals.set_resume(resume_rec["id"], "done")
            self._drain_resume(sid)                      # reprises arrivées pendant ce tour

    def _settle_open_approvals(self, turn: Turn) -> None:
        """Fin de tour : toute proposition du tour encore `waiting` (arrêt budget/max_turns, sortie du
        backend…) devient `pending` — une approbation ultérieure met alors une reprise en file, comme
        pour les autres propositions en attente. L'évènement est journalisé et l'athlète est notifié."""
        for aid in list(turn.approval_ids):
            if self.approvals.mark_pending(aid):
                turn.pending_created = True
                turn.emit("approval_resolved", {"approval_id": aid, "decision": "pending"})
                rec = self.approvals.get(aid) or {}
                self.notify_approval(aid, rec.get("summary", ""))
                log(f"approbation {aid[:4]}… : laissée en attente à la fin du tour")

    def interrupt(self, sid: str) -> bool:
        with self._lock:
            turn = self.turns.get(sid)
        if turn is None:
            return False
        turn.cancelled.set()
        return True

    # -- approbations ------------------------------------------------------------

    def _emit_session(self, sid: str, etype: str, data: dict) -> None:
        """Émet sur le tour vivant de la session (flux + journal), sinon dans le journal seul."""
        with self._lock:
            turn = self.turns.get(sid)
        if turn is not None:
            turn.emit(etype, data)
        else:
            self.sessions.append_event(sid, etype, data)

    def ntfy_enabled(self) -> bool:
        return bool(self.cfg["ntfy_approvals"] and self.notif.get("provider") == "ntfy"
                    and self.notif.get("ntfy_topic"))

    def notify_approval(self, approval_id: str, summary: str) -> None:
        """Push ntfy (une seule fois par proposition) : résumé seul, jamais de valeur de santé."""
        if not self.ntfy_enabled() or approval_id in self._notified:
            return
        self._notified.add(approval_id)
        public = str(self.cfg["public_url"]).rstrip("/")
        actions = build_actions(public, approval_id, self._raw_tokens.get(approval_id)) if public else ""
        if send_ntfy(self.notif, "Coach : confirmation demandée", summary, actions):
            log(f"ntfy envoyé pour la proposition {approval_id[:4]}…")

    def quick_approve_enabled(self) -> bool:
        """Boutons « Appliquer / Refuser » : seulement sur un sujet ntfy à accès contrôlé.

        Le jeton voyage dans la notification : sans `[notifications].ntfy_token_file`, tout abonné
        du sujet pourrait approuver. Sans fichier, seul « Ouvrir » (page derrière le SSO) est envoyé.
        """
        wanted = bool(self.cfg["ntfy_quick_approve"] and self.ntfy_enabled() and self.cfg["public_url"])
        if wanted and not self.notif.get("ntfy_token_file"):
            if not self._quick_warned:
                self._quick_warned = True
                log("avertissement : boutons rapides ntfy désactivés — [notifications].ntfy_token_file "
                    "absent (un sujet sans contrôle d'accès exposerait les jetons) ; seul « Ouvrir » est envoyé")
            return False
        return wanted

    def _request_approval(self, turn: Turn, tool: str, tool_input: dict, summary: str, diff: list) -> str:
        cfg = self.cfg
        quick = self.quick_approve_enabled()
        record, tokens = self.approvals.create(
            turn.session_id, tool, tool_input, summary, diff, float(cfg["approval_ttl_s"]),
            float(cfg["ntfy_token_ttl_s"]) if quick else None)
        aid = record["id"]
        turn.approval_ids.append(aid)
        if tokens:
            self._raw_tokens[aid] = tokens
        event, box = threading.Event(), []
        self._waiters[aid] = (event, box)
        turn.emit("approval_request", {"approval_id": aid, "tool": tool, "summary": summary,
                                       "diff": diff, "expires_at": record["expires_at"]})
        start = time.monotonic()
        wait = float(cfg["approval_wait_s"])
        delay = float(cfg["ntfy_delay_s"])
        try:
            if not turn.subscribers:
                self.notify_approval(aid, summary)       # personne devant l'écran : push tout de suite
            while True:
                if event.is_set():
                    return "allow" if box and box[0] == "allow" else "deny"
                if turn.cancelled.is_set():
                    result, rec = self.resolve_approval(aid, "cancelled", via="cancel")
                    if result == "closed" and rec and rec.get("status") == "allowed":
                        # L'athlète a autorisé pile avant l'annulation : l'outil n'a pas tourné.
                        # On met l'exécution en file (comme une approbation tardive) au lieu de
                        # laisser une proposition « approuvée » qui n'a jamais été appliquée.
                        self.approvals.set_resume(aid, "queued")
                        self._resume_after_approval(dict(rec, resume="queued"))
                    return "deny"
                if turn.finished.is_set():
                    break            # le backend est reparti (abandon budget/max_turns) : reste ouverte
                elapsed = time.monotonic() - start
                if elapsed >= wait:
                    break
                if aid not in self._notified and elapsed >= delay:
                    self.notify_approval(aid, summary)
                event.wait(min(0.2, wait - elapsed))
            # Délai d'attente en ligne écoulé : la proposition reste ouverte (reprise ultérieure).
            if self.approvals.mark_pending(aid):
                turn.pending_created = True
                turn.emit("approval_resolved", {"approval_id": aid, "decision": "pending"})
                self.notify_approval(aid, summary)
                return "pending"
            # Décision arrivée pile au bord : la source de vérité est l'enregistrement, pas la boîte
            # (le décideur a pu fermer la proposition sans avoir encore rempli la boîte).
            rec = self.approvals.get(aid) or {}
            return "allow" if rec.get("status") == "allowed" else "deny"
        finally:
            self._waiters.pop(aid, None)

    def resolve_approval(self, approval_id: str, decision: str, via: str = "page") -> tuple:
        """Applique une décision (page, ntfy ou annulation). Renvoie (résultat, enregistrement).

        `decision` : allow | deny | cancelled. Seul l'état AVANT la décision compte : une proposition
        `waiting` appartient au tour qui l'attend (il rend la décision, jamais de reprise) ; une
        proposition `pending` approuvée déclenche la reprise de la session.
        """
        result, rec = self.approvals.resolve(approval_id, decision)
        if result != "ok":
            return result, rec
        self._raw_tokens.pop(approval_id, None)
        sid = rec["session_id"]
        self._emit_session(sid, "approval_resolved", {"approval_id": approval_id, "decision": decision})
        log(f"approbation {approval_id[:4]}… : {decision} ({via})")
        if rec.get("previous_status") == "waiting":
            waiter = self._waiters.get(approval_id)
            if waiter:
                waiter[1].append(decision)
                waiter[0].set()
        elif decision == "allow":
            self._resume_after_approval(rec)
        return result, rec

    # -- reprise d'une approbation tardive ----------------------------------------

    def _resume_after_approval(self, rec: dict) -> None:
        """Approbation tardive : mise en file d'un tour dont SEUL l'appel approuvé (même hash) est pré-autorisé."""
        with self._lock:
            self._resumes.setdefault(rec["session_id"], []).append(rec)
        self._drain_resume(rec["session_id"])

    def _drain_resume(self, sid: str) -> None:
        """Lance la prochaine reprise de la session si elle est libre ; sinon elle reste en file.

        Rappelé à chaque libération du créneau de la session (fin de tour) : une approbation
        tardive arrivée pendant un autre tour n'est jamais perdue.
        """
        with self._drain_lock:                           # pop + tentative + remise en file : atomique
            with self._lock:
                queue_ = self._resumes.get(sid) or []
                rec = queue_.pop(0) if queue_ else None
                if not queue_:
                    self._resumes.pop(sid, None)
            if rec is None:
                return
            message = (f"[approbation] L'athlète a approuvé la proposition {rec['id']} ({rec['summary']}). "
                       "Exécute exactement cet appel maintenant.")
            code, _, _ = self.begin_turn(sid, "resume", message, preapproved={rec["hash"]}, resume=True,
                                         resume_rec=rec)
            if code == "busy":                           # un autre tour tient la session : il rappellera
                with self._lock:
                    self._resumes.setdefault(sid, []).insert(0, rec)
                return
        if code != "ok":                                 # session disparue
            self._resume_failed(rec, "conversation introuvable", emit_error=False)

    def _resume_failed(self, rec: dict, reason: str, emit_error: bool = True) -> None:
        """Reprise impossible : état visible dans la page, événement d'erreur dans le journal, push ntfy."""
        self.approvals.set_resume(rec["id"], "failed", status="unexecuted")
        sid = rec["session_id"]
        if emit_error and self.sessions.get(sid) is not None:
            self._emit_session(sid, "error", {"message": f"Proposition approuvée mais non exécutée : {reason}."})
        if self.sessions.get(sid) is not None:
            self._emit_session(sid, "approval_resolved", {"approval_id": rec["id"], "decision": "unexecuted"})
        log(f"approbation {rec['id'][:4]}… : reprise impossible ({reason})")
        if self.ntfy_enabled():
            public = str(self.cfg["public_url"]).rstrip("/")
            actions = f"view, Ouvrir, {public}/chat.html#approval={rec['id']}" if public else ""
            send_ntfy(self.notif, "Coach : proposition non exécutée",
                      f"Proposition approuvée mais non exécutée : {rec['summary']}", actions)

    def resume_at_startup(self) -> None:
        """Au démarrage : les approbations tardives acceptées mais jamais exécutées reprennent."""
        now = self.approvals.clock()
        for rec in self.approvals.resumes_in_state("running"):
            # Le service s'est arrêté pendant la reprise : on ne sait pas si l'outil a tourné → jamais rejouée.
            self._resume_failed(rec, "interrompue par un redémarrage du service", emit_error=True)
        for rec in self.approvals.queued_resumes():
            decided = rec.get("resolved_ts")
            if decided is not None and now > float(decided) + float(self.cfg["approval_ttl_s"]):
                self._resume_failed(rec, "expirée", emit_error=True)
                continue
            self._resume_after_approval(rec)

    # -- expiration ------------------------------------------------------------------

    def _on_expired(self, records: list) -> None:
        """Appelé par le magasin dès que des propositions expirent (quelle que soit la voie)."""
        for rec in records:
            self._raw_tokens.pop(rec["id"], None)
            self._emit_session(rec["session_id"], "approval_resolved",
                               {"approval_id": rec["id"], "decision": "expired"})
            waiter = self._waiters.get(rec["id"])
            if waiter and rec.get("previous_status", "waiting") == "waiting":
                waiter[1].append("deny")
                waiter[0].set()

    def sweep_expired(self) -> None:
        self.approvals.expire_due()

    # -- vues ---------------------------------------------------------------------

    def public_approval(self, rec: dict) -> dict:
        return {"id": rec["id"], "session_id": rec["session_id"], "tool": rec["tool"],
                "summary": rec["summary"], "diff": rec["diff"], "status": rec["status"],
                "created": rec["created"], "expires_at": rec["expires_at"]}

    def session_summary(self, meta: dict) -> dict:
        pending = sum(1 for a in self.approvals.list(meta["id"]) if a["status"] in OPEN_STATUSES)
        return {"id": meta["id"], "title": meta.get("title", ""), "created": meta["created"],
                "updated": meta["updated"], "cost_eur": meta.get("cost_eur", 0.0),
                "pending_approvals": pending}

    def status(self, user: str) -> dict:
        return {"enabled": bool(self.cfg["enabled"]), "backend": self.backend.name,
                "model": self.cfg["model"], "user": user,
                "budget": {"spent_eur": round(self.spend.spent(), 4),
                           "limit_eur": float(self.cfg["daily_budget_eur"])},
                "ntfy": self.ntfy_enabled()}


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------

TOKEN_RE = re.compile(rf"^{API}/approve/([^/]+)/(allow|deny)$")
TOKEN_PATH_REDACT = re.compile(rf"({API}/approve/)[^/\s]+")


class Handler(BaseHTTPRequestHandler):
    server_version = "arc-chat"
    service: ChatService = None
    allowed_hosts: set = set()

    def log_message(self, fmt, *args):
        pass

    def log_request(self, code="-", size="-"):
        # Le jeton ntfy fait partie du chemin : il ne doit jamais atteindre les journaux.
        safe = TOKEN_PATH_REDACT.sub(lambda m: m.group(1) + "***", self.path.split("?")[0])
        log(f"{self.command} {safe} {code}")

    # -- réponses -------------------------------------------------------------------

    def _headers(self) -> None:
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'")

    def _json(self, status: int, payload) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self._headers()
        self.end_headers()
        self.wfile.write(body)

    def _error(self, status: int, message: str) -> None:
        self._json(status, {"error": message})

    def _read_body(self) -> Optional[dict]:
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = -1
        if length < 0 or length > MAX_BODY_BYTES:
            self._error(413, "Corps de requête trop volumineux.")
            return None
        raw = self.rfile.read(length) if length else b"{}"
        try:
            data = json.loads(raw.decode("utf-8") or "{}")
        except (ValueError, UnicodeDecodeError):
            self._error(400, "JSON invalide.")
            return None
        if not isinstance(data, dict):
            self._error(400, "Objet JSON attendu.")
            return None
        return data

    # -- garde commune ----------------------------------------------------------------

    def _gate(self, post: bool) -> Optional[str]:
        """Contrôles Host → source/identité → CSRF. Renvoie l'utilisateur, ou None (réponse déjà envoyée)."""
        svc = self.service
        if not host_ok(self.headers.get("Host"), self.allowed_hosts):
            self._error(403, "Hôte non autorisé.")
            return None
        path = self.path.split("?")[0]
        token_route = bool(TOKEN_RE.match(path))
        health = path in (f"{API}/healthz", "/healthz")
        user, status, message = authenticate(svc.cfg, self.client_address[0], self.headers,
                                             exempt_identity=token_route, health_from_loopback=health)
        if status:
            self._error(status, message)
            return None
        if post:
            problem = check_csrf(self.headers, token_route)
            if problem:
                self._error(403, problem)
                return None
        return user

    # -- routage -----------------------------------------------------------------------

    def do_GET(self):
        user = self._gate(post=False)
        if user is None:
            return
        svc, path = self.service, self.path.split("?")[0]
        if path in (f"{API}/healthz", "/healthz"):
            ok, message = svc.backend.check()
            return self._json(200 if ok else 503, {"ok": bool(ok), "backend_check": message})
        if path == f"{API}/status":
            return self._json(200, svc.status(user))
        if path == f"{API}/sessions":
            return self._json(200, {"sessions": [svc.session_summary(m) for m in svc.sessions.list()]})
        match = re.match(rf"^{API}/sessions/([^/]+)$", path)
        if match:
            meta = svc.sessions.get(match.group(1))
            if meta is None:
                return self._error(404, "Conversation introuvable.")
            body = {k: v for k, v in meta.items() if k != "backend_state"}
            body["pending_approvals"] = svc.session_summary(meta)["pending_approvals"]
            body["running"] = match.group(1) in svc.turns
            body["events"] = svc.sessions.events(meta["id"])
            return self._json(200, body)
        match = re.match(rf"^{API}/approvals/([^/]+)$", path)
        if match:
            rec = svc.approvals.get(match.group(1))
            if rec is None:
                return self._error(404, "Proposition introuvable.")
            return self._json(200, svc.public_approval(rec))
        self._error(404, "Route inconnue.")

    def do_POST(self):
        user = self._gate(post=True)
        if user is None:
            return
        svc, path = self.service, self.path.split("?")[0]
        match = TOKEN_RE.match(path)
        if match:
            return self._post_token(match.group(1), match.group(2))
        if path == f"{API}/sessions":
            if self._read_body() is None:
                return
            meta = svc.sessions.create(svc.backend.name, str(svc.cfg["model"]))
            return self._json(200, {"id": meta["id"]})
        match = re.match(rf"^{API}/sessions/([^/]+)/messages$", path)
        if match:
            return self._post_message(match.group(1), user)
        match = re.match(rf"^{API}/sessions/([^/]+)/interrupt$", path)
        if match:
            if self._read_body() is None:
                return
            if svc.sessions.get(match.group(1)) is None:
                return self._error(404, "Conversation introuvable.")
            return self._json(200, {"ok": True, "running": svc.interrupt(match.group(1))})
        match = re.match(rf"^{API}/approvals/([^/]+)$", path)
        if match:
            return self._post_approval(match.group(1))
        self._error(404, "Route inconnue.")

    do_PUT = do_DELETE = do_PATCH = lambda self: self._error(405, "Méthode non autorisée.")

    # -- routes ------------------------------------------------------------------------

    def _post_approval(self, approval_id: str) -> None:
        body = self._read_body()
        if body is None:
            return
        decision = body.get("decision")
        if decision not in ("allow", "deny"):
            return self._error(400, "decision : « allow » ou « deny » attendu.")
        result, rec = self.service.resolve_approval(approval_id, decision, via="page")
        self._approval_result(result, rec, decision)

    def _approval_result(self, result: str, rec: Optional[dict], decision: str) -> None:
        if result == "ok":
            return self._json(200, {"ok": True, "decision": decision})
        if result == "unknown":
            return self._error(404, "Proposition introuvable.")
        if result == "expired":
            return self._error(410, "Cette proposition a expiré.")
        self._error(409, "Cette proposition a déjà été traitée.")

    def _post_token(self, token: str, action: str) -> None:
        """Action rapide ntfy : jeton à usage unique, lié à la proposition et à sa charge exacte."""
        svc = self.service
        who = client_ip(svc.cfg, self.client_address[0], self.headers)
        # Les deux plafonds sont vérifiés AVANT d'enregistrer quoi que ce soit : un refus global ne
        # doit pas consommer le quota de l'adresse (ni l'inverse).
        if not (svc.approve_global.peek("global") and svc.approve_limiter.peek(who)
                and svc.approve_global.allow("global") and svc.approve_limiter.allow(who)):
            return self._error(429, "Trop de tentatives.")
        if self._read_body() is None:
            return
        result, rec = svc.approvals.verify_token(token, action)
        if result != "ok":
            log(f"jeton refusé ({result})")
            status = {"unknown": 404, "used": 410, "expired": 410, "mismatch": 409}[result]
            return self._error(status, {"unknown": "Lien invalide.", "used": "Lien déjà utilisé.",
                                        "expired": "Lien expiré.",
                                        "mismatch": "La proposition a changé."}[result])
        outcome, _ = svc.resolve_approval(rec["id"], action, via="ntfy")
        self._approval_result(outcome, rec, action)

    def _post_message(self, sid: str, user: str) -> None:
        svc = self.service
        body = self._read_body()
        if body is None:
            return
        text = body.get("text")
        if not isinstance(text, str) or not text.strip():
            return self._error(400, "Message vide.")
        if len(text) > MAX_TEXT_CHARS:
            return self._error(413, "Message trop long.")
        code, turn, q = svc.begin_turn(sid, user, text.strip())
        if code == "unknown":
            return self._error(404, "Conversation introuvable.")
        if code == "busy":
            return self._error(409, "Un tour est déjà en cours dans cette conversation.")
        if code == "rate":
            return self._error(429, "Trop de messages : patiente une minute.")
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("X-Accel-Buffering", "no")
        self.send_header("Connection", "close")
        self._headers()
        self.end_headers()
        try:
            while True:
                try:
                    item = q.get(timeout=PING_INTERVAL_S)
                except queue.Empty:
                    self.wfile.write(b": ping\n\n")
                    self.wfile.flush()
                    continue
                if item is None:
                    break
                etype, data = item
                self.wfile.write(f"event: {etype}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n".encode("utf-8"))
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass                                          # l'onglet est parti ; le tour continue
        finally:
            turn.unsubscribe(q)
            self.close_connection = True


# ---------------------------------------------------------------------------
# Démarrage
# ---------------------------------------------------------------------------

def check_exposure(cfg: dict) -> None:
    if cfg["auth"] not in ("local", "proxy"):
        raise ConfigError(f"[chat].auth : « local » ou « proxy » attendu, « {cfg['auth']} » trouvé.")
    if cfg["auth"] == "local" and cfg["listen"] not in LOOPBACK_HOSTS:
        raise ConfigError(
            f"[chat].auth = \"local\" exige une écoute en boucle locale (listen = {cfg['listen']!r}). "
            "Derrière un reverse proxy : auth = \"proxy\" avec trusted_proxies et auth_header.")


def make_server(workspace: Path, cfg: dict, backend: ChatBackend, notif: Optional[dict] = None,
                port: Optional[int] = None, policy: Optional[Policy] = None) -> tuple:
    """(serveur HTTP lié, ChatService). `port=0` : port libre choisi par le système."""
    check_exposure(cfg)
    service = ChatService(workspace, cfg, backend, notif, policy)
    listen = cfg["listen"]

    class Server(ThreadingHTTPServer):
        daemon_threads = True
        allow_reuse_address = True

        def server_bind(self) -> None:
            # Sans `socket.getfqdn(host)` (cf. `arc_serve.Server`) : ~35 s de blocage
            # au démarrage sur un résolveur lent (runners macOS de GitHub, Mac hors ligne).
            socketserver.TCPServer.server_bind(self)
            host, port = self.server_address[:2]
            self.server_name = str(host)
            self.server_port = port

    # Sous-classe par serveur : deux services dans un même processus (tests) ne se marchent pas dessus.
    bound = type("BoundHandler", (Handler,), {"service": service})
    wanted = int(cfg["port"] if port is None else port)
    try:
        httpd = Server((listen, wanted), bound)
    except OSError as exc:
        raise ConfigError(f"impossible d'écouter sur {listen}:{wanted} ({exc.strerror}).")
    bound.allowed_hosts = host_allowlist(httpd.server_address[1], cfg)
    service.resume_at_startup()
    return httpd, service


def serve(workspace: Path, port: Optional[int] = None, listen: Optional[str] = None,
          backend_name: Optional[str] = None) -> None:
    for warning in load_llm_env()[1]:
        log(f"avertissement : {warning}")
    sections = _merged_sections(workspace)
    cfg = load_chat_config(workspace, sections)
    if listen:
        cfg["listen"] = listen
    if backend_name:
        cfg["backend"] = backend_name
    try:
        backend = load_backend(cfg["backend"], workspace, cfg)
    except BackendError as exc:
        raise ConfigError(str(exc))
    httpd, service = make_server(workspace, cfg, backend, load_notifications(workspace, sections), port)
    stop = threading.Event()

    def sweeper():
        while not stop.wait(30):
            try:
                service.sweep_expired()
            except Exception:                             # noqa: BLE001
                log("balayage des propositions expirées : erreur")

    threading.Thread(target=sweeper, name="chat-sweeper", daemon=True).start()
    shown = "127.0.0.1" if cfg["listen"] in LOOPBACK_HOSTS else cfg["listen"]
    print(f"URL: http://{shown}:{httpd.server_address[1]}/", flush=True)
    log(f"backend {backend.name}, auth {cfg['auth']}, budget {float(cfg['daily_budget_eur']):.2f} €/jour")
    def _terminate(signum, _frame):
        # launchd / systemd / kill : même arrêt propre que Ctrl-C (le serveur OpenCode enfant
        # est arrêté par `backend.shutdown()` au lieu de rester orphelin).
        raise KeyboardInterrupt
    for signame in ("SIGTERM", "SIGHUP"):
        if hasattr(signal, signame):
            signal.signal(getattr(signal, signame), _terminate)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        httpd.server_close()
        backend.shutdown()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--workspace")
    parser.add_argument("--port", type=int)
    parser.add_argument("--listen")
    parser.add_argument("--backend")
    args = parser.parse_args(argv)
    from coach_setup import workspace_root
    serve(workspace_root(args.workspace), args.port, args.listen, args.backend)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except ConfigError as exc:
        print(f"erreur : {exc}", file=sys.stderr)
        sys.exit(1)
