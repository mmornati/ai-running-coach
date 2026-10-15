#!/usr/bin/env python3
"""Diagnostic de la connexion IA du coach (`arc_llm.py check`, #268).

Répond à « pourquoi le coach ne répond pas ? » : clé absente ou refusée, crédit ou quota gratuit
épuisé, jeton d'abonnement expiré, OpenCode absent. Module stdlib (Python 3.9), appelé par
`arc_llm.py check`, par `coach_doctor.py` (`llm_config`) et par la route `/api/chat/llm-check`.

Ce qui est vérifié, par cible (le chat `[chat]` s'il est activé, la sync `[sync]`) :

  - fournisseur déduit de la configuration effective (workspace.toml puis workspace.user.toml) :
    openrouter | openrouter-free | chatgpt | copilot | anthropic | openai-compatible |
    assistant (claude/codex/copilot/gemini/cursor sur abonnement, sans clé) | opencode-global (sync
    OpenCode sans clé du coach) | mock | opencode-other ;
  - clé API : présente dans llm.env ou l'environnement (jamais sa valeur), fichier en mode 600 ;
  - abonnement ChatGPT/Copilot : entrée `oauth` dans le magasin du coach (jamais les jetons),
    échéance lisible pour ChatGPT seulement (Copilot pose `expires: 0`), droits du dossier ;
  - OpenCode : présent, version comparée à OPENCODE_TESTED_VERSION, OPENCODE_DISABLE_DEFAULT_PLUGINS
    (désactive les connexions d'abonnement d'OpenCode, vérifié dans son code source) ;
  - chat et sync sur deux fournisseurs différents : signalé (information).

Avec --probe (SEUL cas où le réseau est utilisé, délai court) :
  - OpenRouter : GET /api/v1/key (clé valide, crédit restant, requêtes gratuites du jour) ;
  - Anthropic : GET https://api.anthropic.com/v1/models (en-têtes x-api-key et anthropic-version) ;
  - compatible OpenAI : GET {base_url}/models (Authorization: Bearer).
  Ces deux derniers points d'accès ont été vérifiés le 2026-10-15 (réponse 401 à une fausse clé).
  Aucun appel de ce type n'existe pour ChatGPT/Copilot : leur validité réelle n'apparaît qu'à la
  première requête (le chat la traduit alors avec les mêmes mots).

Schéma JSON (stable) :
  {"schema": 1, "ok": bool, "worst": "ok|info|warn|error", "probe": bool, "workspace": "...",
   "targets": [{"role": "chat|sync", "backend": "...", "model": "...", "provider": "..."}],
   "checks": [{"id": "...", "scope": "chat|sync|chat+sync|common", "status": "ok|info|warn|error",
               "message": "français", "action": "commande ou consigne" | null,
               "action_kind": "reconnect_openrouter|reconnect_chatgpt|reconnect_copilot|add_credit|
                               wait|set_key|fix_mode|install_opencode|reconfigure|retry|null"}]}
Code de sortie : 0 (ok, info, warn), 1 (au moins une erreur), 2 (usage).

Tests : ARC_OPENROUTER_BASE_URL (déjà utilisé par `connect`), ARC_ANTHROPIC_BASE_URL et
ARC_OPENAI_BASE_URL remplacent les adresses publiques, boucle locale (http) UNIQUEMENT.
Aucune valeur de clé ni de jeton n'est jamais écrite : une dernière passe retire de la sortie toute
clé connue, par précaution.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib import error as urlerror
from urllib import parse as urlparse

import arc_llm

ENGINE = Path(__file__).resolve().parent.parent
PROBE_TIMEOUT_S = 8
SCHEMA = 1
CREDITS_URL = arc_llm.CREDITS_URL
ANTHROPIC_BASE = "https://api.anthropic.com"
ANTHROPIC_VERSION = "2023-06-01"
OPENAI_BASE = "https://api.openai.com/v1"
ANTHROPIC_BASE_ENV = "ARC_ANTHROPIC_BASE_URL"
OPENAI_BASE_ENV = "ARC_OPENAI_BASE_URL"
LOW_CREDIT_USD = 1.0
LOW_FREE_REQUESTS = 5
ORDER = {"ok": 0, "info": 0, "warn": 1, "error": 2}
ICON = {"ok": "✅", "info": "ℹ️ ", "warn": "⚠️ ", "error": "❌"}
ASSISTANT_BINARY = {"claude": "claude", "codex": "codex", "copilot": "copilot", "gemini": "gemini",
                    "cursor": "cursor-agent"}
KEY_ENV_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


# --------------------------------------------------------------------------- configuration

def _merged_sections(workspace: Path) -> dict:
    """workspace.toml puis workspace.user.toml, clé par clé (même règle que config.sh)."""
    from coach_config import read_toml
    shared = workspace / "config/workspace.toml"
    if not shared.exists():
        shared = ENGINE / "config/workspace.toml"
    merged: dict = {}
    for path in (shared, workspace / "config/workspace.user.toml"):
        for section, values in read_toml(path).items():
            if isinstance(values, dict):
                merged.setdefault(section, {}).update(values)
    return merged


def _s(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def build_targets(sections: dict) -> List[Dict[str, Any]]:
    """Cibles effectives : le chat (s'il est activé) puis la sync, avec leur fournisseur déduit."""
    chat, sync = sections.get("chat") or {}, sections.get("sync") or {}
    targets: List[Dict[str, Any]] = []
    if chat.get("enabled") is True or _s(chat.get("enabled")).lower() in ("1", "true", "yes"):
        backend = _s(chat.get("backend")) or "claude"
        model = _s(chat.get("model")) or ("claude-sonnet-5-5" if backend == "claude" else "")
        targets.append(_target("chat", backend, model, _s(chat.get("api_key_env")), _s(chat.get("base_url")),
                               _s(chat.get("opencode_data_dir")), _s(chat.get("opencode_bin"))))
    runner = _s(sync.get("runner")) or "claude"
    targets.append(_target("sync", runner, _s(sync.get("model")), _s(sync.get("api_key_env")),
                           _s(sync.get("base_url")), _s(sync.get("opencode_data_dir")), _s(sync.get("opencode_bin"))))
    return targets


def _target(role: str, backend: str, model: str, key_env: str, base_url: str, data_dir: str,
            opencode_bin: str) -> Dict[str, Any]:
    data_dir = os.path.abspath(os.path.expanduser(data_dir)) if data_dir else ""
    uses_opencode = backend == "opencode"
    sub = arc_llm.subscription_entry(model, data_dir, key_env, base_url) if uses_opencode else None
    t: Dict[str, Any] = {"role": role, "backend": backend, "model": model, "key_env": key_env,
                         "base_url": base_url, "data_dir": data_dir, "opencode_bin": opencode_bin,
                         "uses_opencode": uses_opencode, "subscription": sub}
    t["provider"] = detect_provider(role, backend, model, key_env, base_url, sub)
    if role == "chat" and not key_env and t["provider"] in ("openrouter", "openrouter-free", "anthropic", "openai-compatible"):
        # Défaut du chat quand `api_key_env` est vide (voir arc_chat_opencode / arc_chat_claude).
        t["key_env"] = "ANTHROPIC_API_KEY" if backend == "claude" else "OPENROUTER_API_KEY"
    return t


def detect_provider(role: str, backend: str, model: str, key_env: str, base_url: str,
                    sub: Optional[Dict[str, Any]]) -> str:
    if backend == "mock":
        return "mock"
    if sub is not None:
        return sub["id"]
    if backend == "opencode":
        if role == "sync" and not key_env and not base_url:
            return "opencode-global"   # la sync ne reçoit aucune clé du coach : connexion propre à OpenCode
        prefix = model.partition("/")[0]
        if base_url:
            return "openai-compatible"
        if prefix == "openrouter":
            return "openrouter-free" if arc_llm.is_openrouter_free_model(model) else "openrouter"
        if prefix == "anthropic":
            return "anthropic"
        if prefix == "openai":
            return "openai-compatible"
        return "opencode-other"
    if backend == "claude":
        # Chat : Claude Agent SDK, clé API uniquement. Sync : clé nommée = mode API, sinon abonnement.
        return "anthropic" if (role == "chat" or key_env) else "assistant"
    if backend in ASSISTANT_BINARY:
        return "assistant"
    return "opencode-other"


# --------------------------------------------------------------------------- éléments

def item(check_id: str, status: str, message: str, action: Optional[str] = None,
         action_kind: Optional[str] = None) -> Dict[str, Any]:
    return {"id": check_id, "status": status, "message": message, "action": action, "action_kind": action_kind}


def _q(path: str) -> str:
    return shlex.quote(str(path))


def _loopback_env(name: str, default: str) -> str:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    parts = urlparse.urlsplit(raw)
    if parts.scheme != "http" or (parts.hostname or "") not in ("127.0.0.1", "localhost", "::1"):
        raise ValueError("%s n'accepte qu'une URL http de la boucle locale (tests)." % name)
    return raw.rstrip("/")


def _env_file_value(path: str, var: str) -> Tuple[str, str]:
    """(valeur, origine) de VAR : « llm.env », « environnement » ou (« », « »). Ne sort jamais du module."""
    pattern = re.compile(r"^\s*(?:export\s+)?%s=(.*)$" % re.escape(var))
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                m = pattern.match(line.rstrip("\n"))
                if m and m.group(1).strip().strip("'\""):
                    return m.group(1).strip().strip("'\""), "llm.env"
    except OSError:
        pass
    value = os.environ.get(var, "").strip()
    return (value, "environnement") if value else ("", "")


def _is_loopback(url: str) -> bool:
    try:
        host = urlparse.urlsplit(url).hostname or ""
    except ValueError:
        return False
    return host in ("127.0.0.1", "localhost", "::1")


def _mode(path: str) -> Optional[int]:
    try:
        return os.stat(path).st_mode & 0o777
    except OSError:
        return None


# --------------------------------------------------------------------------- clé API + sondes

class Ctx:
    """État d'un passage : fichier llm.env, clés lues (pour la passe anti-fuite), cache des sondes."""

    def __init__(self, probe: bool) -> None:
        self.probe = probe
        self.env_file = arc_llm.default_env_file()
        self.secrets: List[str] = []
        self.cache: Dict[Tuple[str, str], Any] = {}

    def key(self, var: str) -> Tuple[str, str]:
        value, where = _env_file_value(self.env_file, var)
        if value and value not in self.secrets:
            self.secrets.append(value)
        return value, where


def _api_key_items(ctx: Ctx, t: Dict[str, Any], label: str) -> Tuple[List[Dict[str, Any]], str]:
    """Clé présente et mode du fichier. Retourne (éléments, valeur de la clé ou « »)."""
    out: List[Dict[str, Any]] = []
    var = t["key_env"]
    if not var or not KEY_ENV_PATTERN.match(var):
        out.append(item("key_config", "error", "Nom de variable de clé invalide ou vide dans la configuration (%s)." % (var or "vide"),
                        "./install.sh --llm openrouter|anthropic|openai", "reconfigure"))
        return out, ""
    value, where = ctx.key(var)
    if t["base_url"] and _is_loopback(t["base_url"]) and not value:
        out.append(item("key", "info", "Serveur local (%s) : aucune clé nécessaire." % t["base_url"]))
        return out, ""
    if not value:
        if t["provider"] in ("openrouter", "openrouter-free"):
            out.append(item("key", "error", "Clé OpenRouter absente (%s introuvable dans llm.env ni dans l'environnement)." % var,
                            "python3 scripts/arc_llm.py connect openrouter", "reconnect_openrouter"))
        else:
            out.append(item("key", "error", "Clé %s absente (%s introuvable dans llm.env ni dans l'environnement)." % (label, var),
                            "Ajoutez la ligne %s=… dans %s (mode 600), ou relancez ./install.sh --llm <fournisseur>" % (var, _q(ctx.env_file)),
                            "set_key"))
        return out, ""
    out.append(item("key", "ok", "Clé %s présente (%s dans %s ; valeur non affichée)." % (label, var, where or "?")))
    if where == "llm.env":
        mode = _mode(ctx.env_file)
        if mode is not None and mode & 0o077:
            out.append(item("env_mode", "warn", "%s est lisible par d'autres utilisateurs (mode %s, attendu 600)." % (ctx.env_file, oct(mode)[2:]),
                            "chmod 600 %s" % _q(ctx.env_file), "fix_mode"))
    return out, value


def _probe_get(ctx: Ctx, url: str, headers: Dict[str, str]) -> Tuple[Optional[int], Any]:
    """(statut, corps JSON) d'un GET court ; (None, None) si le réseau est coupé. Mis en cache par (url, clé)."""
    cache_key = (url, json.dumps(sorted(headers.items())))
    if cache_key in ctx.cache:
        return ctx.cache[cache_key]
    try:
        result: Tuple[Optional[int], Any] = arc_llm._http_json("GET", url, headers=headers, timeout=PROBE_TIMEOUT_S)
    except (urlerror.URLError, OSError, ValueError):
        result = (None, None)
    ctx.cache[cache_key] = result
    return result


def _fmt_money(value: Any) -> str:
    try:
        return ("%.2f" % float(value)).replace(".", ",") + " $"
    except (TypeError, ValueError):
        return "?"


def _openrouter_probe(ctx: Ctx, t: Dict[str, Any], key: str) -> List[Dict[str, Any]]:
    try:
        url = arc_llm.base_url() + "/api/v1/key"
    except ValueError as exc:
        return [item("probe", "error", str(exc), None, "reconfigure")]
    status, body = _probe_get(ctx, url, {"Authorization": "Bearer " + key})
    reconnect = ("python3 scripts/arc_llm.py connect openrouter", "reconnect_openrouter")
    credits = ("Ajoutez du crédit : %s" % CREDITS_URL, "add_credit")
    if status is None:
        return [item("probe", "warn", "OpenRouter est injoignable (réseau coupé ou service indisponible) : clé non vérifiée.",
                     "Vérifiez la connexion Internet puis relancez : %s" % arc_llm.DIAG_COMMAND, "retry")]
    if status == 401:
        return [item("probe", "error", "Clé OpenRouter refusée (401) : elle est invalide, révoquée ou supprimée.", *reconnect)]
    if status == 402:
        return [item("probe", "error", "Crédit OpenRouter insuffisant (402) : le compte n'a plus de crédit.", *credits)]
    data = body.get("data") if isinstance(body, dict) else None
    if status != 200 or not isinstance(data, dict):
        return [item("probe", "warn", "Réponse inattendue d'OpenRouter (HTTP %s) : clé non vérifiée." % status, "Réessayez dans un instant.", "retry")]
    out = [item("probe", "ok", "Clé OpenRouter valide (« %s »)." % (data.get("label") or "?"))]
    remaining, limit = data.get("limit_remaining"), data.get("limit")
    free_model = t["provider"] == "openrouter-free"
    if isinstance(remaining, (int, float)) and not isinstance(remaining, bool):
        if remaining <= 0:
            out.append(item("credit", "error", "Crédit de la clé épuisé (limite de %s atteinte)." % _fmt_money(limit), *credits))
        elif remaining < LOW_CREDIT_USD:
            out.append(item("credit", "warn", "Crédit restant faible : %s." % _fmt_money(remaining), *credits))
        else:
            out.append(item("credit", "ok", "Crédit restant : %s." % _fmt_money(remaining)))
    elif data.get("is_free_tier") and not free_model:
        out.append(item("credit", "warn", "Aucun crédit acheté sur ce compte : les modèles payants seront refusés (402).", *credits))
    else:
        out.append(item("credit", "ok", "Aucun plafond propre à cette clé (le solde du compte n'est pas lu)."))
    quota = data.get("free_model_daily_requests")
    if free_model and isinstance(quota, dict) and isinstance(quota.get("remaining"), int):
        left = quota["remaining"]
        text = "Requêtes gratuites restantes aujourd'hui : %d sur %s (remise à zéro à minuit UTC)." % (left, quota.get("limit", "?"))
        if left <= 0:
            out.append(item("free_quota", "error", "Quota gratuit du jour atteint : %s" % text.replace("restantes aujourd'hui", "restantes"),
                            "Attendez demain (minuit UTC) ou ajoutez du crédit : %s" % CREDITS_URL, "wait"))
        elif left < LOW_FREE_REQUESTS:
            out.append(item("free_quota", "warn", text, "Gardez-les pour l'essentiel ou ajoutez du crédit : %s" % CREDITS_URL, "wait"))
        else:
            out.append(item("free_quota", "ok", text))
    elif free_model:
        out.append(item("free_quota", "info", "Quota gratuit du jour non communiqué par OpenRouter."))
    return out


def _models_probe(ctx: Ctx, label: str, url: str, headers: Dict[str, str], refused: Tuple[str, str],
                  note: str = "") -> List[Dict[str, Any]]:
    status, _ = _probe_get(ctx, url, headers)
    if status is None:
        return [item("probe", "warn", "%s est injoignable (réseau coupé ou service indisponible) : clé non vérifiée." % label,
                     "Vérifiez la connexion Internet puis relancez : %s" % arc_llm.DIAG_COMMAND, "retry")]
    if status in (401, 403):
        return [item("probe", "error", "Clé %s refusée (%d) : elle est invalide, révoquée ou sans droit." % (label, status),
                     refused[0], refused[1])]
    if status == 429:
        return [item("probe", "warn", "%s limite le débit (429) : clé acceptée, réessayez dans un instant." % label, None, "retry")]
    if status != 200:
        return [item("probe", "warn", "Réponse inattendue de %s (HTTP %d) : clé non vérifiée." % (label, status), None, "retry")]
    return [item("probe", "ok", "Clé %s acceptée (liste des modèles lue)%s." % (label, note))]


def _key_provider_items(ctx: Ctx, t: Dict[str, Any]) -> List[Dict[str, Any]]:
    provider = t["provider"]
    label = {"openrouter": "OpenRouter", "openrouter-free": "OpenRouter", "anthropic": "Anthropic",
             "openai-compatible": "du fournisseur compatible OpenAI"}.get(provider, provider)
    if provider == "openai-compatible":
        label = "API compatible OpenAI"
    items, key = _api_key_items(ctx, t, label if provider != "openai-compatible" else "API")
    if not ctx.probe:
        if key or not any(i["status"] == "error" for i in items):
            items.append(item("probe", "info", "Validité de la clé non vérifiée (aucun appel réseau sans --probe).",
                              arc_llm.DIAG_COMMAND, "retry"))
        return items
    if provider in ("openrouter", "openrouter-free"):
        if key:
            items.extend(_openrouter_probe(ctx, t, key))
    elif provider == "anthropic":
        if key:
            try:
                base = _loopback_env(ANTHROPIC_BASE_ENV, ANTHROPIC_BASE)
            except ValueError as exc:
                return items + [item("probe", "error", str(exc), None, "reconfigure")]
            items.extend(_models_probe(ctx, "Anthropic", base + "/v1/models?limit=1",
                                       {"x-api-key": key, "anthropic-version": ANTHROPIC_VERSION},
                                       ("Créez une clé sur console.anthropic.com puis mettez-la dans %s" % _q(ctx.env_file), "set_key"),
                                       note=" ; le solde n'est pas lisible par l'API"))
    elif provider == "openai-compatible":
        try:
            base = t["base_url"].rstrip("/") if t["base_url"] else _loopback_env(OPENAI_BASE_ENV, OPENAI_BASE)
        except ValueError as exc:
            return items + [item("probe", "error", str(exc), None, "reconfigure")]
        headers = {"Authorization": "Bearer " + key} if key else {}
        if key or _is_loopback(base):
            items.extend(_models_probe(ctx, "du fournisseur (%s)" % urlparse.urlsplit(base).netloc, base + "/models", headers,
                                       ("Vérifiez la clé %s dans %s" % (t["key_env"], _q(ctx.env_file)), "set_key")))
    return items


# --------------------------------------------------------------------------- abonnements

def _subscription_items(ctx: Ctx, t: Dict[str, Any]) -> List[Dict[str, Any]]:
    entry, data_dir = t["subscription"], t["data_dir"]
    label = entry["plan_label"]
    login = "python3 scripts/arc_llm.py login %s --data-dir %s" % (entry["id"], _q(data_dir))
    kind = "reconnect_" + entry["id"]
    out: List[Dict[str, Any]] = []
    mode = _mode(data_dir)
    if mode is None:
        return [item("auth", "error", "Magasin de connexion %s introuvable (%s)." % (label, data_dir), login, kind)]
    if mode & 0o077:
        out.append(item("store_mode", "warn", "Le magasin %s est lisible par d'autres utilisateurs (mode %s, attendu 700)." % (data_dir, oct(mode)[2:]),
                        "chmod 700 %s" % _q(data_dir), "fix_mode"))
    auth_file = os.path.join(data_dir, "opencode", "auth.json")
    amode = _mode(auth_file)
    if amode is not None and amode & 0o077:
        out.append(item("auth_mode", "warn", "%s est lisible par d'autres utilisateurs (mode %s, attendu 600)." % (auth_file, oct(amode)[2:]),
                        "chmod 600 %s" % _q(auth_file), "fix_mode"))
    status = arc_llm.auth_status(data_dir, entry["opencode_provider"])
    if not status["present"]:
        out.append(item("auth", "error", "Connexion %s absente du magasin du coach." % label, login, kind))
        return out
    if status.get("type") != "oauth":
        out.append(item("auth", "warn", "L'entrée %s du magasin n'est pas une connexion de compte (type « %s », attendu « oauth »)."
                        % (label, status.get("type")), login, kind))
        return out
    out.append(item("auth", "ok", "Connexion %s présente dans le magasin du coach (jetons non affichés)." % label))
    expires = status.get("expires_ms")
    if entry["id"] == "chatgpt" and expires:
        delta_s = expires / 1000.0 - time.time()
        if delta_s <= 0:
            out.append(item("expiry", "info", "Jeton d'accès ChatGPT échu depuis %s : OpenCode le rafraîchit tout seul à la prochaine requête ; "
                            "si le chat échoue, la connexion est expirée." % _duration(-delta_s), login, kind))
        else:
            out.append(item("expiry", "ok", "Jeton d'accès ChatGPT valable encore %s (rafraîchi automatiquement)." % _duration(delta_s)))
    elif entry["id"] == "copilot":
        out.append(item("expiry", "info", "GitHub Copilot ne publie pas d'échéance : la validité n'apparaît qu'à la première requête."))
    out.append(item("probe", "info", "Pas de test réseau pour un abonnement : la validité réelle se voit à la première requête "
                    "(le chat traduit alors l'erreur avec ces mêmes mots).", None, None))
    return out


def _duration(seconds: float) -> str:
    seconds = int(seconds)
    if seconds < 90:
        return "%d s" % seconds
    if seconds < 5400:
        return "%d min" % round(seconds / 60.0)
    if seconds < 172800:
        return "%d h" % round(seconds / 3600.0)
    return "%d jours" % round(seconds / 86400.0)


# --------------------------------------------------------------------------- OpenCode, assistants

def find_opencode(explicit: str = "") -> Optional[str]:
    if explicit:
        return explicit if os.path.exists(explicit) else None
    if os.environ.get("ARC_OPENCODE_BIN"):
        return os.environ["ARC_OPENCODE_BIN"]
    extra = [os.path.expanduser("~/.local/bin"), os.path.expanduser("~/.opencode/bin"), "/opt/homebrew/bin", "/usr/local/bin"]
    return shutil.which("opencode", path=os.pathsep.join([os.environ.get("PATH", ""), *extra]))


def tested_version() -> str:
    try:
        import arc_chat_opencode
        return arc_chat_opencode.OPENCODE_TESTED_VERSION
    except Exception:  # noqa: BLE001 — repli : lecture de la constante dans le source
        try:
            text = (Path(__file__).resolve().parent / "arc_chat_opencode.py").read_text(encoding="utf-8")
            m = re.search(r'^OPENCODE_TESTED_VERSION = "([^"]+)"', text, re.M)
            return m.group(1) if m else ""
        except OSError:
            return ""


def _opencode_items(targets: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    explicit = next((t["opencode_bin"] for t in targets if t["opencode_bin"]), "")
    install = "Installez OpenCode : curl -fsSL https://opencode.ai/install | bash (voir docs/choisir-son-ia.md)"
    binary = find_opencode(explicit)
    out: List[Dict[str, Any]] = []
    if not binary:
        return [item("opencode", "error", "OpenCode est introuvable alors que la configuration l'utilise.", install, "install_opencode")]
    version = ""
    try:
        proc = subprocess.run([binary, "--version"], capture_output=True, text=True, timeout=5)
        text = (proc.stdout or proc.stderr).strip()
        version = text.splitlines()[0].strip() if proc.returncode == 0 and text else ""
    except (OSError, subprocess.TimeoutExpired):
        version = ""
    if not version:
        out.append(item("opencode", "warn", "OpenCode présent (%s) mais « --version » ne répond pas." % binary, install, "install_opencode"))
    else:
        tested = tested_version()
        if tested and version != tested:
            out.append(item("opencode", "info", "OpenCode %s (version testée avec le coach : %s) : à signaler si le chat se comporte mal." % (version, tested)))
        else:
            out.append(item("opencode", "ok", "OpenCode %s (version testée)." % version))
    if any(t["subscription"] for t in targets) and os.environ.get("OPENCODE_DISABLE_DEFAULT_PLUGINS", "").strip().lower() not in ("", "0", "false"):
        out.append(item("opencode_plugins", "warn", "OPENCODE_DISABLE_DEFAULT_PLUGINS est défini : OpenCode n'utilise alors pas les connexions "
                        "ChatGPT/Copilot.", "Retirez-le de l'environnement : unset OPENCODE_DISABLE_DEFAULT_PLUGINS", "reconfigure"))
    return out


def _claude_sdk_items() -> List[Dict[str, Any]]:
    try:
        from importlib import metadata
        version = metadata.version("claude-agent-sdk")
    except Exception:  # noqa: BLE001
        return [item("claude_sdk", "info", "Paquet claude-agent-sdk non détecté dans cet interpréteur "
                     "(le service du chat peut en utiliser un autre : « scripts/coach-chat.sh logs »).")]
    return [item("claude_sdk", "ok", "claude-agent-sdk %s installé." % version)]


def _assistant_items(t: Dict[str, Any]) -> List[Dict[str, Any]]:
    runner = t["backend"]
    binary = ASSISTANT_BINARY.get(runner, runner)
    note = ("Synchronisation par l'abonnement de l'assistant « %s » : sa connexion est gérée par l'assistant (aucune clé du coach à vérifier)." % runner)
    if shutil.which(binary) is None:
        return [item("assistant", "warn", note + " Le programme « %s » est introuvable dans le PATH." % binary,
                     "Installez et connectez « %s » (voir docs/mobile.md)" % binary, "reconfigure")]
    return [item("assistant", "info", note)]


# --------------------------------------------------------------------------- orchestration

def _group_key(t: Dict[str, Any]) -> Tuple[str, str, str, str]:
    return (t["provider"], t["key_env"] if t["provider"] not in ("chatgpt", "copilot") else "", t["base_url"], t["data_dir"])


def run_checks(workspace: Path, probe: bool) -> Dict[str, Any]:
    ctx = Ctx(probe)
    checks: List[Dict[str, Any]] = []
    try:
        sections = _merged_sections(workspace)
    except Exception as exc:  # noqa: BLE001 — TOML invalide : dit, ne plante pas
        checks.append(dict(item("config", "error", "Configuration illisible : %s" % exc, "python3 scripts/coach_doctor.py --check config_files", "reconfigure"),
                           scope="common"))
        return _result(workspace, probe, [], checks, ctx)
    targets = build_targets(sections)

    groups: Dict[Tuple[str, str, str, str], List[Dict[str, Any]]] = {}
    for t in targets:
        groups.setdefault(_group_key(t), []).append(t)
    for members in groups.values():
        t = members[0]
        scope = "+".join(m["role"] for m in members)
        provider = t["provider"]
        if provider in ("openrouter", "openrouter-free", "anthropic", "openai-compatible"):
            items = _key_provider_items(ctx, t)
        elif provider in ("chatgpt", "copilot"):
            items = _subscription_items(ctx, t)
        elif provider == "assistant":
            items = _assistant_items(t)
        elif provider == "mock":
            items = [item("provider", "info", "Moteur de test (mock) : aucune connexion à vérifier.")]
        elif provider == "opencode-global":
            items = [item("provider", "info", "Synchronisation par OpenCode sans clé du coach ([sync].api_key_env vide) : "
                          "la connexion propre à OpenCode n'est pas vérifiée.")]
        else:
            items = [item("provider", "info", "Fournisseur « %s » via OpenCode : connexion gérée par OpenCode, non vérifiée." % t["model"].partition("/")[0])]
        for it in items:
            checks.append(dict(it, scope=scope))
    if any(t["uses_opencode"] for t in targets):
        checks.extend(dict(it, scope="common") for it in _opencode_items([t for t in targets if t["uses_opencode"]]))
    if any(t["backend"] == "claude" and t["role"] == "chat" for t in targets):
        checks.extend(dict(it, scope="common") for it in _claude_sdk_items())
    providers = sorted({t["provider"] for t in targets})
    if len(providers) > 1:
        checks.append(dict(item("mixed_providers", "info", "Le chat (%s) et la synchronisation (%s) utilisent des fournisseurs différents : "
                                "chacun est vérifié séparément." % tuple(next(t["provider"] for t in targets if t["role"] == r) for r in ("chat", "sync"))),
                           scope="common"))
    return _result(workspace, probe, targets, checks, ctx)


def _result(workspace: Path, probe: bool, targets: List[Dict[str, Any]], checks: List[Dict[str, Any]], ctx: Ctx) -> Dict[str, Any]:
    worst = max((c["status"] for c in checks), key=lambda s: ORDER[s], default="ok")
    if worst == "info":
        worst = "ok"
    report = {
        "schema": SCHEMA, "ok": worst != "error", "worst": worst, "probe": probe, "workspace": str(workspace),
        "targets": [{k: t[k] for k in ("role", "backend", "model", "provider")} for t in targets],
        "checks": checks,
    }
    return _scrub(report, ctx.secrets)


def _scrub(value: Any, secrets_list: List[str]) -> Any:
    """Dernière passe anti-fuite : aucune clé lue ne peut rester dans la sortie."""
    if not secrets_list:
        return value
    text = json.dumps(value, ensure_ascii=False)
    for secret in secrets_list:
        if len(secret) >= 4:
            text = text.replace(secret, "[masqué]")
    return json.loads(text)


def check(workspace: Optional[str] = None, probe: bool = False) -> Dict[str, Any]:
    from coach_setup import workspace_root
    return run_checks(workspace_root(workspace), probe)


def render_text(report: Dict[str, Any]) -> str:
    lines = []
    for tg in report["targets"]:
        lines.append("%-5s %s (%s)" % (tg["role"], tg["provider"], tg["model"] or tg["backend"]))
    if lines:
        lines.append("")
    for c in report["checks"]:
        lines.append("%s %s" % (ICON[c["status"]], c["message"]))
        if c.get("action") and c["status"] != "ok":
            lines.append("    → %s" % c["action"])
    lines.append("")
    lines.append("Aucune erreur." if report["ok"] else "Au moins un point est en erreur (❌) : suivez les actions ci-dessus.")
    if not report["probe"]:
        lines.append("Réseau non utilisé : ajoutez --probe pour vérifier la clé, le crédit et le quota.")
    return "\n".join(lines)


def run(args: Any) -> int:
    try:
        report = check(getattr(args, "workspace", None), bool(getattr(args, "probe", False)))
    except Exception as exc:  # noqa: BLE001 — jamais de trace brute ni de secret
        msg = "Diagnostic impossible : %s" % type(exc).__name__
        print(json.dumps({"schema": SCHEMA, "ok": False, "error": msg}, ensure_ascii=False) if getattr(args, "json", False) else msg)
        return 1
    if getattr(args, "json", False):
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(render_text(report))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(arc_llm.main(["check"] + sys.argv[1:]))
