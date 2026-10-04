#!/usr/bin/env python3
"""Passerelle Telegram du coach (#174) : retours en un geste SANS LLM + pont opt-in vers le chat.

Deux niveaux, le premier ne demande ni clé d'API ni modèle :

1. **Retours déterministes.** Après la synchronisation quotidienne, `send-summary` envoie le
   résumé avec des boutons inline (« Séance faite / pas faite / décalée », RPE 1-10, « Douleur »).
   Le service (`run`) reçoit les appuis et écrit directement dans les blocs ```arc du workspace
   (`rpe` de l'activité, `pain` du fichier santé, `status` de la séance planifiée), par la MÊME
   logique que `/log` (`arc_log.process` : fusion, doublon, seuil de consultation) — jamais une
   arithmétique dupliquée ici —, valide le contrat, puis réindexe. Idempotent : le même appui
   deux fois n'écrit qu'une fois.
2. **Conversation libre (opt-in).** Avec `[telegram].chat_bridge = true` ET le chat activé, le
   texte libre est relayé au service `arc_chat` existant (même politique, mêmes approbations,
   même plafond de dépense) ; une proposition d'écriture devient deux boutons « Appliquer /
   Refuser ». Aucun second moteur de chat. Une clé d'API facturée est nécessaire (docs/mobile.md).

Sécurité : liste blanche d'identifiants de chat (`[telegram].allowed_chat_ids`, vide = tout est
refusé), jeton du bot dans un fichier hors dépôt (`[telegram].token_file`, mode 600, jamais journalisé),
interrogation périodique (long polling) : aucun point d'entrée public. Aucune écriture Garmin
depuis ce canal sans l'approbation explicite du chat ; le service n'appelle jamais Garmin lui-même.

Usage :
    arc_telegram.py run [--workspace DIR]            # service (long polling), premier plan
    arc_telegram.py send-summary [--workspace DIR] [--title T] [--priority N] [--date AAAA-MM-JJ] < résumé
    arc_telegram.py whoami [--workspace DIR]         # affiche les identifiants de chat qui ont écrit au bot

Variable d'environnement de test : ARC_TELEGRAM_API_BASE (https, ou http en boucle locale seulement).

Bibliothèque standard uniquement (CONTRIBUTING.md).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import signal
import sys
import threading
import time
import http.client
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
import arc_contract as C  # noqa: E402
import arc_log  # noqa: E402
from coach_config import read_toml  # noqa: E402
from coach_setup import workspace_root  # noqa: E402

ENGINE = Path(__file__).resolve().parent.parent
DEFAULT_API_BASE = "https://api.telegram.org"
DEFAULT_TOKEN_FILE = "~/.config/ai-running-coach/telegram.env"
TOKEN_VAR = "TELEGRAM_BOT_TOKEN"
TOKEN_RE = re.compile(r"^\d{5,}:[A-Za-z0-9_-]{20,}$")
TOKEN_IN_TEXT_RE = re.compile(r"bot\d{5,}:[A-Za-z0-9_-]{10,}")
MAX_MESSAGE_CHARS = 4096          # sendMessage : 1-4096 caractères (Bot API)
CHUNK_CHARS = 3900                # marge sous la limite
MAX_CALLBACK_BYTES = 64           # callback_data : 1-64 octets (Bot API)
LOOPBACK = ("127.0.0.1", "localhost", "::1")

TELEGRAM_DEFAULTS = {
    "enabled": False,
    "token_file": DEFAULT_TOKEN_FILE,
    "allowed_chat_ids": [],
    "send_summary": True,
    "chat_bridge": False,
    "poll_timeout_s": 30,
}

# Zones proposées par le parcours « Douleur » (la dernière ouvre une saisie libre).
PAIN_ZONES = ("genou", "cheville", "mollet", "tendon d'Achille", "hanche", "dos", "pied", "autre")
STATUS_LABELS = {"d": ("done", "faite"), "n": ("missed", "pas faite"), "m": ("moved", "décalée")}

HELP_TEXT = (
    "Coach — retours rapides (sans IA) :\n"
    "/rpe 7 — effort ressenti de la séance (1-10)\n"
    "/douleur genou gauche 3 [note] — douleur : zone puis score /10\n"
    "/statut faite | pas faite | décalée — état de la séance prévue\n"
    "Les boutons du résumé quotidien font la même chose. /nouveau ouvre une nouvelle conversation "
    "(si la conversation libre est activée)."
)

BRIDGE_OFF_TEXT = (
    "La conversation libre n'est pas activée : les retours en un geste (boutons, /rpe, /douleur, /statut) "
    "fonctionnent sans clé d'API. Pour parler au coach ici, voir docs/telegram.md "
    "([telegram].chat_bridge et le chat du tableau de bord, facturé à la clé d'API)."
)


def log(message: str) -> None:
    """Journal sur stderr : jamais de jeton, de clé ni de contenu de santé."""
    print(f"arc_telegram: {redact(message)}", file=sys.stderr, flush=True)


_SECRETS: set = set()


def redact(text: str) -> str:
    for secret in _SECRETS:
        if secret:
            text = text.replace(secret, "***")
    return TOKEN_IN_TEXT_RE.sub("bot***", text)


# ---------------------------------------------------------------------------
# Configuration et jeton
# ---------------------------------------------------------------------------

def load_config(workspace: Path) -> dict:
    """`[telegram]` résolu : défauts < workspace.toml < workspace.user.toml (clé par clé)."""
    shared = workspace / "config/workspace.toml"
    if not shared.exists():
        shared = ENGINE / "config/workspace.toml"
    merged: dict = {}
    for path in (shared, workspace / "config/workspace.user.toml"):
        for section, values in read_toml(path).items():
            if isinstance(values, dict):
                merged.setdefault(section, {}).update(values)
    cfg = dict(TELEGRAM_DEFAULTS)
    for key, value in (merged.get("telegram") or {}).items():
        if key in TELEGRAM_DEFAULTS:
            cfg[key] = _coerce(TELEGRAM_DEFAULTS[key], value)
    cfg["allowed_chat_ids"] = [c for c in (str(v).strip() for v in cfg["allowed_chat_ids"]) if c]
    cfg["_all"] = merged
    return cfg


def _coerce(default, value):
    try:
        if isinstance(default, bool):
            return value if isinstance(value, bool) else str(value).strip().lower() in ("1", "true", "yes")
        if isinstance(default, int):
            return int(float(value))
        if isinstance(default, list):
            return list(value) if isinstance(value, (list, tuple)) else ([value] if value not in ("", None) else [])
        return str(value)
    except (TypeError, ValueError):
        return default


def token_file_path(cfg: dict) -> Path:
    return Path(os.path.expanduser(str(cfg.get("token_file") or DEFAULT_TOKEN_FILE)))


def read_token(cfg: dict, environ=None) -> tuple:
    """(jeton ou None, erreur ou None). Fichier hors dépôt ; la variable d'environnement prime.
    Le message d'erreur ne contient jamais la valeur."""
    environ = os.environ if environ is None else environ
    token = (environ.get(TOKEN_VAR) or "").strip()
    if not token:
        path = token_file_path(cfg)
        if not path.is_file():
            return None, f"fichier du jeton introuvable : {path}"
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                match = re.match(rf"^\s*(?:export\s+)?{TOKEN_VAR}=(.*)$", line)
                if match:
                    token = match.group(1).strip().strip("\"'")
        except OSError as exc:
            return None, f"{path} illisible ({exc.strerror})"
    if not token:
        return None, f"{TOKEN_VAR} absent (voir docs/telegram.md)"
    if not TOKEN_RE.match(token):
        return None, f"{TOKEN_VAR} : format inattendu (attendu : <nombre>:<chaîne>, copié depuis BotFather)"
    _SECRETS.add(token)
    return token, None


def token_file_warning(cfg: dict) -> Optional[str]:
    path = token_file_path(cfg)
    try:
        if path.is_file() and path.stat().st_mode & 0o077:
            return f"{path} est lisible par d'autres utilisateurs — chmod 600"
    except OSError:
        pass
    return None


# ---------------------------------------------------------------------------
# Client de l'API Bot (urllib)
# ---------------------------------------------------------------------------

class TelegramError(Exception):
    def __init__(self, code: int, description: str, retry_after: Optional[int] = None):
        super().__init__(f"Telegram {code} : {description}")
        self.code = code
        self.description = description
        self.retry_after = retry_after


def api_base() -> str:
    base = (os.environ.get("ARC_TELEGRAM_API_BASE") or DEFAULT_API_BASE).rstrip("/")
    parsed = urlparse(base)
    if parsed.scheme != "https" and not (parsed.scheme == "http" and parsed.hostname in LOOPBACK):
        raise ValueError("ARC_TELEGRAM_API_BASE : https exigé (http seulement en boucle locale)")
    return base


class TelegramAPI:
    def __init__(self, token: str, base: Optional[str] = None, timeout: float = 15.0):
        _SECRETS.add(token)
        self._url = f"{base or api_base()}/bot{token}/"
        self.timeout = timeout

    def call(self, method: str, params: Optional[dict] = None, http_timeout: Optional[float] = None):
        body = json.dumps(params or {}).encode("utf-8")
        request = urllib.request.Request(self._url + method, data=body, method="POST",
                                         headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=http_timeout or self.timeout) as response:  # noqa: S310
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            try:
                payload = json.loads(exc.read().decode("utf-8"))
            except (ValueError, OSError):
                payload = {"ok": False, "error_code": exc.code, "description": "erreur HTTP"}
        except (urllib.error.URLError, http.client.HTTPException, OSError, ValueError, TimeoutError) as exc:
            # Jamais str(exc) : selon l'exception, l'URL (qui CONTIENT le jeton) peut y figurer.
            raise TelegramError(0, redact(f"réseau : {type(exc).__name__}"))
        if not isinstance(payload, dict) or not payload.get("ok"):
            payload = payload if isinstance(payload, dict) else {}
            retry = (payload.get("parameters") or {}).get("retry_after")
            raise TelegramError(int(payload.get("error_code") or 0), str(payload.get("description") or "erreur"),
                                int(retry) if isinstance(retry, (int, float)) else None)
        return payload.get("result")


# ---------------------------------------------------------------------------
# État persistant (offset, doublons, parcours en cours) — jetable
# ---------------------------------------------------------------------------

class Store:
    def __init__(self, workspace: Path):
        self.path = workspace / ".arc/telegram/state.json"
        self.lock = threading.RLock()
        self.data = {"offset": 0, "pending": {}, "sessions": {}, "approvals": {}}
        try:
            loaded = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                self.data.update({k: v for k, v in loaded.items() if k in self.data})
        except (OSError, ValueError):
            pass

    def save(self) -> None:
        with self.lock:
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                tmp = self.path.with_suffix(".tmp")
                tmp.write_text(json.dumps(self.data, ensure_ascii=False), encoding="utf-8")
                os.chmod(tmp, 0o600)
                os.replace(tmp, self.path)
            except OSError as exc:
                log(f"état non enregistré ({exc.strerror})")

    @property
    def offset(self) -> int:
        return int(self.data.get("offset") or 0)

    def heartbeat(self) -> None:
        """Marque le service vivant (lu par `coach_doctor.py --check telegram`) : un fichier, une date."""
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            (self.path.parent / "heartbeat").write_text(datetime.now().astimezone().isoformat(timespec="seconds"), encoding="utf-8")
        except OSError:
            pass

    def set_offset(self, value: int) -> None:
        with self.lock:
            self.data["offset"] = value
            self.save()


# ---------------------------------------------------------------------------
# Fichiers du workspace : lecture/écriture des blocs ```arc
# ---------------------------------------------------------------------------

_PROV_LINE_RE = re.compile(r"^\[/log [^\]]*\].*$", re.M)
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f-\x9f\u2028\u2029]+")


def one_line(text, limit: int = 300) -> str:
    """Texte libre venu de Telegram -> UNE ligne sûre pour le Markdown du workspace : aucun saut de
    ligne ni caractère de contrôle (sans quoi une note pourrait ouvrir un second bloc ```arc, ou un
    titre, sous le bloc), aucun accent grave (clôture de bloc), espaces normalisés, longueur bornée."""
    flat = _CONTROL_RE.sub(" ", str(text or "")).replace("`", "'")
    return re.sub(r"\s+", " ", flat).strip()[:limit]


def read_arc_file(path: Path) -> tuple:
    text = path.read_text(encoding="utf-8")
    return text, C.extract_block(text)


def render_block(data: dict) -> str:
    return "```arc\n" + json.dumps(data, indent=2, ensure_ascii=False) + "\n```"


def commit_file(path: Path, text: str, data: dict, provenance: Optional[str] = None) -> Optional[str]:
    """Écrit `data` comme bloc ```arc de `text` (+ ligne de provenance dessous). Renvoie un message
    d'erreur (et n'écrit RIEN) si le bloc résultant viole le contrat."""
    errors, _ = C.validate(data)
    if errors:
        return "contrat arc violé : " + "; ".join(errors[:2])
    match = C.BLOCK_RE.search(text)
    if match is None:
        return "bloc arc introuvable"
    head, tail = text[:match.start()], text[match.end():]
    block = render_block(data)
    if provenance:
        rest = tail.lstrip("\n")
        lines = rest.split("\n")
        i = 0
        while i < len(lines) and lines[i].startswith("[/log "):
            i += 1
        kept, remaining = lines[:i], "\n".join(lines[i:])
        tail = "\n\n" + "\n".join(kept + [provenance]) + ("\n\n" + remaining.lstrip("\n") if remaining.strip() else "\n")
    out = head + block + tail
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(out, encoding="utf-8")
    os.replace(tmp, path)
    return None


def provenance_entries(text: str) -> list:
    return _PROV_LINE_RE.findall(text)


def activity_files(workspace: Path, day: str) -> list:
    return sorted(p for p in (workspace / "activities").glob(f"{day}_*.md") if not p.name.endswith("_rest.md"))


def week_sessions(workspace: Path, day: str) -> list:
    """[(chemin, texte, bloc, session)] des séances prévues ce jour-là, tous fichiers semaine confondus."""
    found = []
    for path in sorted((workspace / "planning").glob("*.md")):
        try:
            text, block = read_arc_file(path)
        except (OSError, C.ContractError):
            continue
        if not block or block.get("kind") != "week":
            continue
        weeks = block.get("weeks") if isinstance(block.get("weeks"), list) else [block]
        for week in weeks:
            for session in (week or {}).get("sessions") or []:
                if isinstance(session, dict) and session.get("date") == day:
                    found.append((path, text, block, session))
    return found


def feedback_date(workspace: Path, today: date) -> str:
    """Jour auquel rattacher les retours : aujourd'hui, ou hier si seule la veille a une séance."""
    t, y = today.isoformat(), (today - timedelta(days=1)).isoformat()
    if activity_files(workspace, t) or week_sessions(workspace, t):
        return t
    if activity_files(workspace, y):
        return y
    return t


# ---------------------------------------------------------------------------
# Écritures déterministes (la logique de /log, jamais une copie)
# ---------------------------------------------------------------------------

def _num(value):
    """Entier si la valeur en est un (7.0 -> 7), pour des blocs arc propres."""
    return int(value) if float(value).is_integer() else value


class Result:
    def __init__(self, ok: bool, message: str, wrote: bool = False, choices: Optional[list] = None,
                 consult: bool = False):
        self.ok, self.message, self.wrote, self.choices, self.consult = ok, message, wrote, choices, consult


def _label(path: Path) -> str:
    return path.name


def apply_rpe(workspace: Path, day: str, rpe, idx: Optional[int] = None) -> Result:
    files = activity_files(workspace, day)
    if not files:
        return Result(False, f"Aucune séance synchronisée le {day} : RPE non enregistré "
                             "(relance après la synchronisation, ou dis-le au coach).")
    if idx is None and len(files) > 1:
        return Result(True, f"Plusieurs séances le {day} : laquelle ?",
                      choices=[(p.stem.split("_", 1)[-1], i) for i, p in enumerate(files)])
    if idx is not None and not 0 <= idx < len(files):
        return Result(False, "Séance introuvable (liste modifiée depuis) : recommence.")
    path = files[idx or 0]
    text, data = read_arc_file(path)
    if data is None:
        return Result(False, f"{_label(path)} n'a pas de bloc arc : RPE non enregistré.")
    out = arc_log.process({"rpe": rpe, "existing_activity_arc": data, "catalogue_paths": []}, workspace=workspace)
    if "rpe_unknown" in out:
        return Result(False, "RPE illisible ou hors de 0-10 : rien n'a été écrit.")
    value = _num(out["rpe"])
    shown = value
    if data.get("rpe") == value:
        return Result(True, f"RPE {shown}/10 déjà noté pour {_label(path)}.")
    data.update(out["activity_merge"], rpe=value)       # 7 et non 7.0 dans le bloc
    prov = arc_log.provenance_line(f"Telegram : RPE {shown}/10")
    err = commit_file(path, text, data, prov)
    if err:
        return Result(False, f"Écriture refusée ({err}).")
    return Result(True, f"Noté : RPE {shown}/10 dans activities/{_label(path)}.", wrote=True)


def apply_pain(workspace: Path, day: str, location: str, score, note: str = "") -> Result:
    location, note = one_line(location, 60), one_line(note)
    if not location:
        return Result(False, "Zone de douleur vide : rien n'a été écrit.")
    path = workspace / "medical" / f"{day}_health.md"
    raw = f"Telegram : douleur {location} {score}/10"
    existing, entries, text, data = [], [], None, None
    if path.is_file():
        text, data = read_arc_file(path)
        if data is None:
            return Result(False, f"{_label(path)} n'a pas de bloc arc : douleur non enregistrée.")
        existing = list(data.get("pain") or [])
        entries = provenance_entries(text)
    out = arc_log.process({"pain": [{"location": location, "score": score}], "raw_text": raw,
                           "existing_pain": existing, "existing_log_entries": entries,
                           "catalogue_paths": []}, workspace=workspace)
    if not out.get("pain", {}).get("entries"):
        return Result(False, "Score de douleur illisible ou hors de 0-10 : rien n'a été écrit.")
    entry = out["pain"]["entries"][0]
    threshold = out["pain"]["consult_threshold"]
    entry["score"] = _num(entry["score"])
    shown = entry["score"]
    if out.get("duplicate"):
        return Result(True, f"Douleur {entry['location']} {shown}/10 déjà notée aujourd'hui.", consult=entry["consult"])
    if data is None:
        mode = "full"
        try:
            import arc_index
            configured = (arc_index.load_config(workspace).get("health") or {}).get("morning_check")
            mode = configured if configured in C.MORNING_CHECK else "full"
        except Exception:
            pass
        data = {"arc": C.ARC_VERSION, "kind": "health", "date": day, "morning_check": mode}
        text = f"# Santé — {day}\n\n{render_block(data)}\n"
    # `pain_merge` (arc_log) = existant + nouvelles entrées ; le contrat ne garde que location/score
    # (`consult` n'est qu'un indicateur de sortie).
    data["pain"] = [{"location": p["location"], "score": _num(p["score"])} for p in out["pain_merge"]]
    prov = out.get("provenance_line") or arc_log.provenance_line(raw)
    if note:
        # Ligne À PART : la ligne de la douleur reste identique au `raw_text`, sinon la détection de
        # doublon d'arc_log (comparaison ligne à ligne) ne reconnaîtrait plus la même déclaration.
        prov += "\n" + arc_log.provenance_line(f"Telegram : note douleur {entry['location']} — {note}")
    err = commit_file(path, text, data, prov)
    if err:
        return Result(False, f"Écriture refusée ({err}).")
    msg = f"Noté : douleur {entry['location']} {shown}/10 dans medical/{_label(path)}."
    consult = bool(entry["consult"])
    if consult:
        msg += (f"\nScore ≥ seuil de consultation ({threshold:g}/10) : je te recommande de consulter un "
                "professionnel de santé avant de reprendre la course. Rien n'est modifié dans ton plan depuis "
                "ici — dis-le au coach.")
    return Result(True, msg, wrote=True, consult=consult)


def apply_status(workspace: Path, day: str, code: str, idx: Optional[int] = None) -> Result:
    status, label = STATUS_LABELS[code]
    sessions = week_sessions(workspace, day)
    if not sessions:
        return Result(False, f"Aucune séance prévue le {day} dans les fichiers semaine : statut non enregistré.")
    if idx is None and len(sessions) > 1:
        return Result(True, f"Plusieurs séances prévues le {day} : laquelle ?",
                      choices=[(str(s[3].get("title") or "séance")[:30], i) for i, s in enumerate(sessions)])
    if idx is not None and not 0 <= idx < len(sessions):
        return Result(False, "Séance introuvable (plan modifié depuis) : recommence.")
    path, text, block, session = sessions[idx or 0]
    title = one_line(session.get("title") or "séance", 80)
    if session.get("status") == status:
        return Result(True, f"« {title} » déjà marquée {label}.")
    session["status"] = status
    prov = arc_log.provenance_line(f"Telegram : séance « {title} » du {day} → {label}")
    err = commit_file(path, text, block, prov)
    if err:
        return Result(False, f"Écriture refusée ({err}).")
    msg = f"Noté : « {title} » {label} dans planning/{path.name}."
    if status == "moved":
        msg += "\nLe calendrier Garmin n'est pas modifié depuis ici : demande au coach de la replacer."
    return Result(True, msg, wrote=True)


def reindex(workspace: Path) -> None:
    import subprocess
    try:
        # Le jeton n'est jamais transmis à un processus enfant, même s'il venait de l'environnement.
        env = {k: v for k, v in os.environ.items() if k != TOKEN_VAR}
        subprocess.run([sys.executable, str(ENGINE / "scripts/arc_index.py"), "--workspace", str(workspace)],
                       capture_output=True, timeout=180, check=False, env=env)
    except (OSError, subprocess.SubprocessError) as exc:
        log(f"réindexation impossible ({type(exc).__name__})")


# ---------------------------------------------------------------------------
# Claviers et analyse des callbacks
# ---------------------------------------------------------------------------

def _button(label: str, data: str) -> dict:
    assert len(data.encode("utf-8")) <= MAX_CALLBACK_BYTES, data
    return {"text": label, "callback_data": data}


def feedback_keyboard(workspace: Path, day: str) -> Optional[dict]:
    rows = []
    if week_sessions(workspace, day):
        rows.append([_button("✅ Faite", f"st:{day}:d"), _button("❌ Pas faite", f"st:{day}:n"),
                     _button("⏭ Décalée", f"st:{day}:m")])
    if activity_files(workspace, day):
        rows.append([_button(str(n), f"rp:{day}:{n}") for n in range(1, 6)])
        rows.append([_button(str(n), f"rp:{day}:{n}") for n in range(6, 11)])
    rows.append([_button("🩹 Douleur", f"pn:{day}")])
    return {"inline_keyboard": rows}


def parse_callback(data: str) -> Optional[dict]:
    """`st:DATE:d|n|m[:I]`, `rp:DATE:N[:I]`, `pn:DATE`, `pz:DATE:Z`, `ps:DATE:S`, `ap:ID:a|d`."""
    parts = (data or "").split(":")
    kind = parts[0] if parts else ""
    day_ok = len(parts) > 1 and re.fullmatch(r"\d{4}-\d{2}-\d{2}", parts[1] or "")
    try:
        if kind == "st" and day_ok and len(parts) in (3, 4) and parts[2] in STATUS_LABELS:
            return {"kind": "st", "date": parts[1], "code": parts[2], "idx": int(parts[3]) if len(parts) == 4 else None}
        if kind == "rp" and day_ok and len(parts) in (3, 4) and 1 <= int(parts[2]) <= 10:
            return {"kind": "rp", "date": parts[1], "rpe": int(parts[2]), "idx": int(parts[3]) if len(parts) == 4 else None}
        if kind == "pn" and day_ok and len(parts) == 2:
            return {"kind": "pn", "date": parts[1]}
        if kind == "pz" and day_ok and len(parts) == 3 and 0 <= int(parts[2]) < len(PAIN_ZONES):
            return {"kind": "pz", "date": parts[1], "zone": int(parts[2])}
        if kind == "ps" and day_ok and len(parts) == 3 and 1 <= int(parts[2]) <= 10:
            return {"kind": "ps", "date": parts[1], "score": int(parts[2])}
        if kind == "ap" and len(parts) == 3 and parts[2] in ("a", "d") and re.fullmatch(r"[A-Za-z0-9_-]{6,40}", parts[1]):
            return {"kind": "ap", "id": parts[1], "decision": "allow" if parts[2] == "a" else "deny"}
    except ValueError:
        return None
    return None


def parse_pain_command(arg: str) -> Optional[tuple]:
    """`genou gauche 3 [note…]` -> (zone, score, note). None si zone ou score manquants."""
    tokens = arg.split()
    for i, tok in enumerate(tokens):
        if re.fullmatch(r"\d{1,2}(?:/10)?", tok):
            location = " ".join(tokens[:i]).strip()
            if not location:
                return None
            return location, tok.split("/")[0], " ".join(tokens[i + 1:])
    return None


# ---------------------------------------------------------------------------
# Pont vers le chat (niveau 2)
# ---------------------------------------------------------------------------

class ChatBridge:
    """Client HTTP du service `arc_chat` (boucle locale, auth = "local") : un seul moteur de chat."""

    def __init__(self, cfg_all: dict, timeout: float = 90.0):
        chat = dict(cfg_all.get("chat") or {})
        self.enabled = bool(chat.get("enabled"))
        self.auth = str(chat.get("auth") or "local")
        listen = str(chat.get("listen") or "127.0.0.1")
        self.host = "127.0.0.1" if listen in ("0.0.0.0", "::", "") else listen
        self.port = int(float(chat.get("port") or 8766))
        self.timeout = timeout

    @property
    def base(self) -> str:
        host = f"[{self.host}]" if ":" in self.host else self.host
        return f"http://{host}:{self.port}/api/chat"

    def _request(self, method: str, path: str, body: Optional[dict] = None, timeout: Optional[float] = None):
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, method=method,
                                     headers={"X-ARC-Chat": "1", "Content-Type": "application/json"})
        return urllib.request.urlopen(req, timeout=timeout or self.timeout)  # noqa: S310 - boucle locale

    def check(self) -> Optional[str]:
        """None si la conversation est possible, sinon la raison (courte, sans secret)."""
        if not self.enabled:
            return "le chat est désactivé ([chat].enabled = false, voir docs/dashboard/chat.md)"
        if self.auth != "local" or self.host not in LOOPBACK:
            return "le pont exige [chat].auth = \"local\" sur la boucle locale"
        try:
            with self._request("GET", "/healthz", timeout=5) as resp:
                payload = json.loads(resp.read(65536).decode("utf-8") or "{}")
        except urllib.error.HTTPError as exc:
            try:
                payload = json.loads(exc.read(65536).decode("utf-8") or "{}")
            except (ValueError, OSError):
                payload = {"ok": False}
        except (urllib.error.URLError, OSError, ValueError, TimeoutError):
            return "le service du chat est injoignable (scripts/coach-chat.sh status)"
        if payload.get("ok") is not True:
            detail = payload.get("backend_check")
            return "le backend du chat n'est pas prêt" + (f" : {detail}" if isinstance(detail, str) and len(detail) <= 120 else "")
        return None

    def new_session(self) -> str:
        with self._request("POST", "/sessions", {}) as resp:
            return json.loads(resp.read().decode("utf-8"))["id"]

    def stream(self, sid: str, text: str):
        """Génère (type, data) depuis le flux SSE d'un tour."""
        try:
            resp = self._request("POST", f"/sessions/{sid}/messages", {"text": text})
        except urllib.error.HTTPError as exc:
            yield "http_error", {"code": exc.code}
            return
        with resp:
            etype = None
            for raw in resp:
                line = raw.decode("utf-8", "replace").rstrip("\n").rstrip("\r")
                if line.startswith("event:"):
                    etype = line[6:].strip()
                elif line.startswith("data:") and etype:
                    try:
                        yield etype, json.loads(line[5:].strip())
                    except ValueError:
                        yield etype, {}
                elif not line:
                    etype = None

    def decide(self, approval_id: str, decision: str) -> int:
        try:
            with self._request("POST", f"/approvals/{approval_id}", {"decision": decision}):
                return 200
        except urllib.error.HTTPError as exc:
            return exc.code
        except (urllib.error.URLError, OSError, TimeoutError):
            return 0


# ---------------------------------------------------------------------------
# Le robot : traitement d'une mise à jour
# ---------------------------------------------------------------------------

class Bot:
    def __init__(self, workspace: Path, cfg: dict, api, store: Optional[Store] = None, bridge: Optional[ChatBridge] = None,
                 today=date.today, reindex_fn=reindex, min_interval_s: float = 1.05, run_async: bool = True):
        self.ws, self.cfg, self.api = workspace, cfg, api
        self.allowed = set(cfg["allowed_chat_ids"])
        self.store = store or Store(workspace)
        self.bridge = bridge if bridge is not None else ChatBridge(cfg.get("_all") or {})
        self.today, self.reindex_fn = today, reindex_fn
        self.min_interval_s, self.run_async = min_interval_s, run_async
        self._last_send: dict = {}
        self._send_lock = threading.Lock()
        self._busy: set = set()
        self._busy_lock = threading.Lock()
        self.threads: list = []

    # -- envoi ---------------------------------------------------------------

    def send(self, chat_id, text: str, keyboard: Optional[dict] = None, silent: bool = False) -> None:
        chunks = [text[i:i + CHUNK_CHARS] for i in range(0, len(text), CHUNK_CHARS)] or [""]
        for n, chunk in enumerate(chunks):
            params = {"chat_id": chat_id, "text": chunk or "…", "disable_notification": silent}
            if keyboard and n == len(chunks) - 1:
                params["reply_markup"] = keyboard
            self._throttled_call("sendMessage", params, chat_id)

    def _throttled_call(self, method: str, params: dict, chat_id) -> None:
        with self._send_lock:                      # ≤ 1 message/s par chat (FAQ Telegram)
            wait = self._last_send.get(chat_id, 0.0) + self.min_interval_s - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            for attempt in (1, 2):
                try:
                    self.api.call(method, params)
                    break
                except TelegramError as exc:
                    if exc.code == 429 and attempt == 1:
                        time.sleep(min(exc.retry_after or 1, 30))
                        continue
                    log(f"{method} refusé ({exc.code})")
                    break
            self._last_send[chat_id] = time.monotonic()

    def _answer(self, callback_id: str, text: str = "") -> None:
        try:
            self.api.call("answerCallbackQuery", {"callback_query_id": callback_id, "text": text[:190]})
        except TelegramError as exc:
            log(f"answerCallbackQuery refusé ({exc.code})")

    # -- autorisation ----------------------------------------------------------

    def authorized(self, chat: dict, sender: Optional[dict]) -> bool:
        chat_id = str((chat or {}).get("id", ""))
        if not chat_id or chat_id not in self.allowed:
            return False
        if (chat or {}).get("type", "private") != "private":
            return str((sender or {}).get("id", "")) in self.allowed
        return True

    # -- entrée -----------------------------------------------------------------

    def handle_update(self, update: dict) -> None:
        if "callback_query" in update:
            cb = update["callback_query"] or {}
            msg = cb.get("message") or {}
            if not self.authorized(msg.get("chat"), cb.get("from")):
                log(f"appui d'un chat non autorisé ignoré (id {(msg.get('chat') or {}).get('id')})")
                return
            self.on_callback(cb, msg["chat"]["id"])
        elif "message" in update:
            msg = update["message"] or {}
            if not self.authorized(msg.get("chat"), msg.get("from")):
                log(f"message d'un chat non autorisé ignoré (id {(msg.get('chat') or {}).get('id')})")
                return
            if isinstance(msg.get("text"), str):
                self.on_text(msg["chat"]["id"], msg["text"].strip())

    # -- callbacks --------------------------------------------------------------

    def on_callback(self, cb: dict, chat_id) -> None:
        cid = cb.get("id", "")
        parsed = parse_callback(cb.get("data") or "")
        if parsed is None:
            self._answer(cid, "Bouton inconnu.")
            return
        kind = parsed["kind"]
        if kind == "ap":
            self.on_approval(cid, chat_id, parsed)
            return
        if kind == "st":
            result = apply_status(self.ws, parsed["date"], parsed["code"], parsed["idx"])
            self._finish(cid, chat_id, result, lambda i: f"st:{parsed['date']}:{parsed['code']}:{i}")
        elif kind == "rp":
            result = apply_rpe(self.ws, parsed["date"], parsed["rpe"], parsed["idx"])
            self._finish(cid, chat_id, result, lambda i: f"rp:{parsed['date']}:{parsed['rpe']}:{i}")
        elif kind == "pn":
            self._answer(cid)
            rows = [[_button(z.capitalize(), f"pz:{parsed['date']}:{i}") for i, z in enumerate(PAIN_ZONES[j:j + 2], j)]
                    for j in range(0, len(PAIN_ZONES), 2)]
            self.send(chat_id, "Douleur : quelle zone ?", {"inline_keyboard": rows})
        elif kind == "pz":
            self._answer(cid)
            zone = PAIN_ZONES[parsed["zone"]]
            with self.store.lock:
                self.store.data["pending"][str(chat_id)] = {"date": parsed["date"], "location": None if zone == "autre" else zone,
                                                           "stage": "zone_text" if zone == "autre" else "score"}
                self.store.save()
            if zone == "autre":
                self.send(chat_id, "Écris la zone (ex. « mollet droit »).")
            else:
                self.ask_score(chat_id, parsed["date"], zone)
        elif kind == "ps":
            key = str(chat_id)
            with self.store.lock:
                pending = dict(self.store.data["pending"].get(key) or {})
            if pending.get("stage") != "score" or not pending.get("location") or pending.get("date") != parsed["date"]:
                self._answer(cid, "Parcours expiré.")
                self.send(chat_id, "Ce parcours Douleur n'est plus actif : relance-le avec le bouton « Douleur » ou /douleur.")
                return
            result = apply_pain(self.ws, parsed["date"], pending["location"], parsed["score"])
            with self.store.lock:
                if result.ok and result.wrote:
                    self.store.data["pending"][key] = {"date": parsed["date"], "stage": "note", "location": pending["location"]}
                else:
                    self.store.data["pending"].pop(key, None)
                self.store.save()
            self._finish(cid, chat_id, result, None)
            if result.ok and result.wrote:
                self.send(chat_id, "Une note (facultative) ? Réponds par un texte, ou ignore ce message.")

    def ask_score(self, chat_id, day: str, zone: str) -> None:
        rows = [[_button(str(n), f"ps:{day}:{n}") for n in range(1, 6)], [_button(str(n), f"ps:{day}:{n}") for n in range(6, 11)]]
        self.send(chat_id, f"Douleur ({zone}) : score sur 10 ?", {"inline_keyboard": rows})

    def _finish(self, cid: str, chat_id, result: Result, choice_data) -> None:
        self._answer(cid, "Noté" if result.wrote else ("OK" if result.ok else "Impossible"))
        if result.choices and choice_data:
            rows = [[_button(label, choice_data(i))] for label, i in result.choices]
            self.send(chat_id, result.message, {"inline_keyboard": rows})
            return
        self.send(chat_id, result.message)
        if result.wrote:
            self.reindex_fn(self.ws)

    # -- texte ---------------------------------------------------------------------

    def on_text(self, chat_id, text: str) -> None:
        if text.startswith("/"):
            head, _, arg = text.partition(" ")
            cmd = head.split("@")[0].lower()
            arg = arg.strip()
            if cmd in ("/start", "/aide", "/help"):
                self.send(chat_id, HELP_TEXT)
            elif cmd == "/rpe":
                if not re.fullmatch(r"\d{1,2}", arg):
                    self.send(chat_id, "Usage : /rpe 7")
                    return
                day = feedback_date(self.ws, self.today())
                result = apply_rpe(self.ws, day, int(arg))
                self._reply(chat_id, result, lambda i: f"rp:{day}:{arg}:{i}")
            elif cmd in ("/douleur", "/pain"):
                parsed = parse_pain_command(arg)
                if parsed is None:
                    self.send(chat_id, "Usage : /douleur genou gauche 3 [note]")
                    return
                result = apply_pain(self.ws, feedback_date(self.ws, self.today()), parsed[0], parsed[1], parsed[2])
                self._reply(chat_id, result, None)
            elif cmd == "/statut":
                code = {"faite": "d", "fait": "d", "pas faite": "n", "non faite": "n", "décalée": "m", "decalee": "m", "décalé": "m"}.get(arg.lower())
                if code is None:
                    self.send(chat_id, "Usage : /statut faite | pas faite | décalée")
                    return
                day = feedback_date(self.ws, self.today())
                self._reply(chat_id, apply_status(self.ws, day, code), lambda i: f"st:{day}:{code}:{i}")
            elif cmd == "/nouveau":
                with self.store.lock:
                    self.store.data["sessions"].pop(str(chat_id), None)
                    self.store.save()
                self.send(chat_id, "Nouvelle conversation ouverte.")
            else:
                self.send(chat_id, "Commande inconnue.\n" + HELP_TEXT)
            return
        with self.store.lock:
            pending = dict(self.store.data["pending"].get(str(chat_id)) or {})
        if pending.get("stage") == "zone_text":
            location = one_line(text, 60)
            if not location:
                self.send(chat_id, "Écris la zone (ex. « mollet droit »).")
                return
            with self.store.lock:
                self.store.data["pending"][str(chat_id)] = {"date": pending["date"], "location": location, "stage": "score"}
                self.store.save()
            self.ask_score(chat_id, pending["date"], location)
            return
        if pending.get("stage") == "note":
            with self.store.lock:
                self.store.data["pending"].pop(str(chat_id), None)
                self.store.save()
            self.add_pain_note(chat_id, pending, text)
            return
        self.on_free_text(chat_id, text)

    def _reply(self, chat_id, result: Result, choice_data) -> None:
        if result.choices and choice_data:
            self.send(chat_id, result.message, {"inline_keyboard": [[_button(l, choice_data(i))] for l, i in result.choices]})
            return
        self.send(chat_id, result.message)
        if result.wrote:
            self.reindex_fn(self.ws)

    def add_pain_note(self, chat_id, pending: dict, note: str) -> None:
        path = self.ws / "medical" / f"{pending['date']}_health.md"
        if not path.is_file():
            self.send(chat_id, "Fichier santé introuvable : note non enregistrée.")
            return
        text = path.read_text(encoding="utf-8")
        note = one_line(note)
        if not note:
            self.send(chat_id, "Note vide : rien n'a été ajouté.")
            return
        line = arc_log.provenance_line(f"Telegram : note douleur {one_line(pending['location'], 60)} — {note}")
        match = C.BLOCK_RE.search(text)
        if match is None:
            self.send(chat_id, "Bloc arc introuvable : note non enregistrée.")
            return
        try:
            data = C.extract_block(text)
        except C.ContractError:
            data = None
        if data is None:
            self.send(chat_id, "Bloc arc illisible : note non enregistrée.")
            return
        err = commit_file(path, text, data, line)
        self.send(chat_id, "Note ajoutée." if not err else f"Note refusée ({err}).")
        if not err:
            self.reindex_fn(self.ws)

    # -- niveau 2 ---------------------------------------------------------------------

    def on_free_text(self, chat_id, text: str) -> None:
        if not self.cfg.get("chat_bridge"):
            self.send(chat_id, BRIDGE_OFF_TEXT)
            return
        reason = self.bridge.check()
        if reason:
            self.send(chat_id, f"Conversation libre indisponible : {reason}.")
            return
        key = str(chat_id)
        with self._busy_lock:
            if key in self._busy:
                busy = True
            else:
                busy = False
                self._busy.add(key)
        if busy:
            self.send(chat_id, "Un échange est déjà en cours : patiente un instant.")
            return
        if self.run_async:
            thread = threading.Thread(target=self._turn, args=(chat_id, text), daemon=True)
            self.threads.append(thread)
            thread.start()
        else:
            self._turn(chat_id, text)

    def _turn(self, chat_id, text: str) -> None:
        key = str(chat_id)
        try:
            with self.store.lock:
                sid = self.store.data["sessions"].get(key)
            if not sid:
                sid = self.bridge.new_session()
                with self.store.lock:
                    self.store.data["sessions"][key] = sid
                    self.store.save()
            parts: list = []
            for etype, data in self.bridge.stream(sid, text):
                if etype == "text_delta":
                    parts.append(str(data.get("text", "")))
                elif etype == "approval_request":
                    aid = str(data.get("approval_id", ""))
                    if parse_callback(f"ap:{aid}:a") is None:
                        continue
                    with self.store.lock:
                        self.store.data["approvals"][aid] = key
                        self.store.save()
                    summary = str(data.get("summary", "")).strip()[:600] or "modification demandée"
                    self.send(chat_id, f"Le coach demande ta confirmation :\n{summary}",
                              {"inline_keyboard": [[_button("✅ Appliquer", f"ap:{aid}:a"), _button("✖ Refuser", f"ap:{aid}:d")]]})
                elif etype == "error":
                    parts.append("\n[erreur] " + str(data.get("message") or data.get("error") or "échec du tour")[:200])
                elif etype == "http_error":
                    code = data.get("code")
                    if code == 404:
                        with self.store.lock:
                            self.store.data["sessions"].pop(key, None)
                            self.store.save()
                        parts.append("Conversation expirée : renvoie ton message.")
                    else:
                        parts.append({409: "Un tour est déjà en cours.", 429: "Trop de messages : patiente une minute."}.get(
                            code, f"Le chat a répondu {code}."))
                elif etype == "done" and data.get("reason") == "budget":
                    parts.append("\n(plafond de dépense du jour atteint)")
            reply = "".join(parts).strip()
            if reply:
                self.send(chat_id, reply)
        except (urllib.error.URLError, OSError, TimeoutError, KeyError, ValueError) as exc:
            log(f"tour de chat interrompu ({type(exc).__name__})")
            self.send(chat_id, "Le service du chat ne répond plus : réessaie plus tard.")
        finally:
            self._busy.discard(key)

    def on_approval(self, cid: str, chat_id, parsed: dict) -> None:
        with self.store.lock:
            owner = self.store.data["approvals"].get(parsed["id"])
        if owner != str(chat_id):
            self._answer(cid, "Proposition inconnue.")
            return
        code = self.bridge.decide(parsed["id"], parsed["decision"])
        if code in (200, 404, 409, 410):
            # Usage unique : une proposition tranchée (ou close côté chat) n'est plus rejouable d'ici.
            with self.store.lock:
                self.store.data["approvals"].pop(parsed["id"], None)
                self.store.save()
        if code == 200:
            self._answer(cid, "Appliqué" if parsed["decision"] == "allow" else "Refusé")
            self.send(chat_id, "Décision transmise au coach." if parsed["decision"] == "allow" else "Proposition refusée.")
        elif code in (404, 409, 410):
            self._answer(cid, "Déjà traitée")
            self.send(chat_id, "Cette proposition a déjà été traitée ou a expiré.")
        else:
            self._answer(cid, "Échec")
            self.send(chat_id, "Impossible de joindre le service du chat.")


# ---------------------------------------------------------------------------
# Service (long polling)
# ---------------------------------------------------------------------------

class _Shutdown(Exception):
    pass


def poll_forever(bot: Bot, api, stop: threading.Event, timeout_s: int = 30, wait=None) -> None:
    wait = wait or stop.wait
    backoff = 1.0
    while not stop.is_set():
        bot.store.heartbeat()
        try:
            updates = api.call("getUpdates", {"offset": bot.store.offset, "timeout": timeout_s,
                                              "allowed_updates": ["message", "callback_query"]},
                               http_timeout=timeout_s + 15)
            backoff = 1.0
        except _Shutdown:
            break
        except TelegramError as exc:
            if exc.code == 401:
                log("jeton refusé par Telegram (401) : vérifiez le fichier du jeton ; nouvel essai dans 5 min")
                delay = 300.0
            elif exc.code == 409:
                log("conflit (409) : un autre getUpdates ou un webhook est actif pour ce bot ; nouvel essai dans 30 s")
                delay = 30.0
            elif exc.code == 429:
                delay = float(exc.retry_after or 5)
            else:
                delay = backoff
                backoff = min(backoff * 2, 60.0)
                log(f"getUpdates : {exc.code or 'réseau'} ; nouvel essai dans {delay:g} s")
            if wait(delay):
                break
            continue
        for update in updates or []:
            try:
                bot.handle_update(update)
            except _Shutdown:
                return
            except Exception as exc:  # noqa: BLE001 - une mise à jour défectueuse ne doit pas tuer le service
                log(f"mise à jour {update.get('update_id')} ignorée ({type(exc).__name__})")
            bot.store.set_offset(int(update["update_id"]) + 1)


def cmd_run(args) -> int:
    ws = _workspace(args)
    cfg = load_config(ws)
    if not cfg["enabled"]:
        log("[telegram].enabled n'est pas « true » : service non démarré (./install.sh --telegram).")
        return 1
    if not cfg["allowed_chat_ids"]:
        log("[telegram].allowed_chat_ids est vide : tout serait refusé. Voir docs/telegram.md.")
        return 1
    token, err = read_token(cfg)
    if err:
        log(err)
        return 1
    warning = token_file_warning(cfg)
    if warning:
        log(warning)
    api = TelegramAPI(token)
    bot = Bot(ws, cfg, api)
    stop = threading.Event()

    def _terminate(signum, _frame):
        stop.set()
        raise _Shutdown()

    signal.signal(signal.SIGTERM, _terminate)
    signal.signal(signal.SIGINT, _terminate)
    log(f"démarré ({len(cfg['allowed_chat_ids'])} chat autorisé(s), pont chat : {'oui' if cfg['chat_bridge'] else 'non'})")
    try:
        poll_forever(bot, api, stop, int(cfg["poll_timeout_s"]))
    except _Shutdown:
        pass
    bot.store.save()
    log("arrêté proprement")
    return 0


def cmd_send_summary(args) -> int:
    ws = _workspace(args)
    cfg = load_config(ws)
    if not cfg["enabled"] or not cfg["send_summary"]:
        return 0
    text = sys.stdin.read().strip()
    if not text:
        return 0
    token, err = read_token(cfg)
    if err or not cfg["allowed_chat_ids"]:
        log(err or "[telegram].allowed_chat_ids est vide : résumé non envoyé")
        return 1
    day = args.date or feedback_date(ws, date.today())
    title = args.title or "Coach"
    body = f"{title}\n\n{text}" if title else text
    keyboard = feedback_keyboard(ws, day)
    bot = Bot(ws, cfg, TelegramAPI(token), store=Store(ws), min_interval_s=0.0)
    failed = False
    for chat_id in cfg["allowed_chat_ids"]:
        try:
            bot.send(chat_id, body, keyboard, silent=int(args.priority) <= 2)
        except TelegramError as exc:
            log(f"envoi refusé ({exc.code})")
            failed = True
    return 2 if failed else 0


def cmd_whoami(args) -> int:
    cfg = load_config(_workspace(args))
    token, err = read_token(cfg)
    if err:
        print(f"ERREUR : {err}", file=sys.stderr)
        return 1
    try:
        updates = TelegramAPI(token).call("getUpdates", {"timeout": 0, "allowed_updates": ["message"]})
    except TelegramError as exc:
        print(f"ERREUR : {exc.code} {exc.description} (le service tourne-t-il déjà ? arrêtez-le d'abord)", file=sys.stderr)
        return 1
    seen = {}
    for update in updates or []:
        chat = ((update.get("message") or {}).get("chat")) or {}
        if "id" in chat:
            seen[chat["id"]] = chat.get("type", "?")
    if not seen:
        print("Aucun message reçu : envoyez /start à votre bot depuis Telegram, puis relancez.")
        return 0
    for chat_id, kind in seen.items():
        print(f"chat id : {chat_id} ({kind})")
    return 0


def _workspace(args) -> Path:
    return Path(args.workspace).expanduser().resolve() if args.workspace else workspace_root(None)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    for name, fn in (("run", cmd_run), ("send-summary", cmd_send_summary), ("whoami", cmd_whoami)):
        p = sub.add_parser(name)
        p.add_argument("--workspace", default=None)
        p.set_defaults(func=fn)
        if name == "send-summary":
            p.add_argument("--title", default="")
            p.add_argument("--priority", default="3")
            p.add_argument("--date", default=None)
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except ValueError as exc:
        print(f"ERREUR : {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
