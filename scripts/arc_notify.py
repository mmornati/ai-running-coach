#!/usr/bin/env python3
"""Notifications push (ntfy) d'ai-running-coach — envoi et configuration.

Module unique pour tout ce qui part vers ntfy : la synchronisation headless
(daily-sync.sh), le service de chat (`arc_chat.send_ntfy`) et la configuration
interactive. Bibliothèque standard uniquement (voir CONTRIBUTING.md).

ntfy (https://ntfy.sh) : appli gratuite iOS/Android, sans compte.

Usage :
  scripts/arc_notify.py send [--title "Titre"] [--priority 1-5] [--tags "tag1,tag2"] "message"
  echo "message" | scripts/arc_notify.py send --title "Titre"
  scripts/arc_notify.py setup                   # interactif : serveur, sujet, token, test
  scripts/arc_notify.py setup --url https://ntfy.example.com --topic mon-sujet [--token-file ~/.config/ai-running-coach/ntfy.token] [--no-test]
  scripts/arc_notify.py setup --disable         # provider = "none"

Configuration : section [notifications] de config/workspace.toml (overrides dans
config/workspace.user.toml) :
  provider        = "ntfy" | "none"
  ntfy_url        = "https://ntfy.sh"          # ou votre serveur auto-hébergé
  ntfy_topic      = "running-coach-xxxx"
  ntfy_token_file = "~/.config/ai-running-coach/ntfy.token"  # optionnel (serveur avec auth)

`ARC_NTFY_URL`, s'il est posé, remplace `ntfy_url` (tests, serveur de développement).

Codes de sortie de `send` : 0 envoyé (ou provider = "none"), 1 erreur de configuration,
2 échec réseau. Les anciens `scripts/notify.sh` et `scripts/setup-ntfy.sh` appellent ce module.
"""

from __future__ import annotations

import argparse
import base64
import os
import secrets
import string
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from arc_runtime import (ConfigError, config_paths, err, log, ok,  # noqa: E402
                         resolve_workspace, section, warn)
from coach_config import set_toml_key  # noqa: E402

DEFAULT_URL = "https://ntfy.sh"
DEFAULT_TOKEN_FILE = "~/.config/ai-running-coach/ntfy.token"
SEND_TIMEOUT_S = 15


class NotifyError(Exception):
    """Erreur attendue : message lisible, pas de trace."""


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

def notifications_section(workspace: Path) -> dict:
    """[notifications] fusionnée clé par clé : workspace.user.toml > workspace.toml. Une config
    invalide ailleurs est lue en mode tolérant : un canal d'alerte ne doit pas tomber pour ça."""
    return section(workspace, "notifications")


def settings(section: dict) -> dict:
    """Réglages ntfy normalisés depuis une section [notifications] déjà lue.

    Une valeur vide retombe sur le défaut (un serveur ou un fournisseur vide n'a pas de sens).
    `ntfy_token_file` est développé (`~`) mais pas lu ici : le jeton n'est lu qu'à l'envoi.
    """
    token_file = str(section.get("ntfy_token_file") or "")
    url = os.environ.get("ARC_NTFY_URL") or str(section.get("ntfy_url") or DEFAULT_URL)
    return {
        "provider": str(section.get("provider") or "none"),
        "ntfy_url": url.rstrip("/"),
        "ntfy_topic": str(section.get("ntfy_topic") or ""),
        "ntfy_token_file": os.path.expanduser(token_file) if token_file else "",
    }


def load_settings(workspace: Path) -> dict:
    return settings(notifications_section(workspace))


# ---------------------------------------------------------------------------
# Envoi
# ---------------------------------------------------------------------------

def _header(value: str) -> str:
    """Valeur d'en-tête HTTP : ASCII tel quel, sinon mot encodé RFC 2047 (décodé par ntfy).

    `http.client` encode les en-têtes en latin-1 : un titre avec emoji lèverait, et un « é »
    partirait en latin-1, illisible pour ntfy qui attend de l'UTF-8.
    """
    if value.isascii():
        return value
    return "=?UTF-8?B?" + base64.b64encode(value.encode("utf-8")).decode("ascii") + "?="


def read_token(token_file: str) -> str:
    """Jeton d'accès du serveur ntfy, sans aucun blanc. Fichier absent ou illisible : NotifyError."""
    path = Path(token_file)
    if not path.is_file():
        raise NotifyError(f"Fichier token introuvable : {token_file}")
    try:
        return "".join(path.read_text(encoding="utf-8").split())
    except OSError as exc:
        raise NotifyError(f"Fichier token illisible : {token_file} ({type(exc).__name__})") from exc


def topic_url(conf: dict) -> str:
    return f"{conf['ntfy_url']}/{conf['ntfy_topic']}"


def post(conf: dict, title: str, message: str, priority: str = "3", tags: str = "running",
         actions: str = "", timeout: float = SEND_TIMEOUT_S) -> None:
    """Publie sur le sujet configuré. Lève NotifyError (configuration) ou OSError (réseau, HTTP)."""
    if not conf.get("ntfy_topic"):
        raise NotifyError("ntfy_topic manquant — lancez scripts/arc_notify.py setup")
    headers = {"Title": _header(title), "Priority": str(priority), "Tags": _header(tags)}
    if actions:
        headers["Actions"] = _header(actions)
    if conf.get("ntfy_token_file"):
        headers["Authorization"] = f"Bearer {read_token(conf['ntfy_token_file'])}"
    request = urllib.request.Request(topic_url(conf), data=message.encode("utf-8"),
                                     headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout):
            pass
    except ValueError as exc:                      # URL invalide
        raise NotifyError(f"ntfy_url invalide : {conf['ntfy_url']}") from exc


def send(conf: dict, title: str, message: str, priority: str = "3", tags: str = "running",
         actions: str = "", timeout: float = SEND_TIMEOUT_S, on_error=None) -> bool:
    """Version qui ne lève jamais (service de chat) : False si rien n'est parti.

    `on_error` reçoit un message court, sans valeur secrète."""
    if conf.get("provider") != "ntfy" or not conf.get("ntfy_topic"):
        return False
    try:
        post(conf, title, message, priority, tags, actions, timeout)
        return True
    except NotifyError as exc:
        if on_error:
            on_error(f"ntfy : {exc}")
    except OSError as exc:                         # URLError, HTTPError, socket.timeout
        if on_error:
            on_error(f"ntfy : envoi impossible ({type(exc).__name__})")
    return False


def cmd_send(args) -> int:
    message = args.message
    if not message and not sys.stdin.isatty():
        message = sys.stdin.read()
    if not message:
        err("Aucun message à envoyer.")
        return 1
    try:
        conf = load_settings(resolve_workspace())
    except ConfigError as exc:
        err(str(exc))
        return 1
    provider = conf["provider"]
    if provider == "none":
        warn('Notifications désactivées (provider = "none") — message non envoyé :')
        print(message, flush=True)
        return 0
    if provider != "ntfy":
        err(f"Provider de notification inconnu : {provider} (ntfy|none)")
        return 1
    try:
        post(conf, args.title, message, args.priority, args.tags)
    except NotifyError as exc:
        err(str(exc))
        return 1
    except OSError:
        err(f"Échec de l'envoi vers {topic_url(conf)} (token ? réseau ?)")
        return 2
    ok(f"Notification envoyée sur {topic_url(conf)}")
    return 0


# ---------------------------------------------------------------------------
# Configuration interactive
# ---------------------------------------------------------------------------

def random_topic() -> str:
    alphabet = string.ascii_lowercase + string.digits
    return "running-coach-" + "".join(secrets.choice(alphabet) for _ in range(8))


def portable_path(path: str) -> str:
    """Forme `~/…` d'un chemin sous le dossier personnel, pour rester portable entre machines."""
    home = str(Path.home())
    return "~" + path[len(home):] if path == home or path.startswith(home + os.sep) else path


USER_CONFIG_HEADER = (
    "# Overrides personnels — ce fichier est GITIGNORÉ.\n"
    "# Les valeurs ci-dessous priment sur config/workspace.toml (versionné).\n"
)


def write_settings(user_config: Path, provider: str, url: str, topic: str, token_file: str) -> None:
    """Écrit les clés de [notifications] sans toucher au reste de workspace.user.toml."""
    user_config.parent.mkdir(parents=True, exist_ok=True)
    original = user_config.read_bytes() if user_config.exists() else None
    if original is None:
        user_config.write_text(USER_CONFIG_HEADER, encoding="utf-8")
    for key, value in (("provider", provider), ("ntfy_url", url), ("ntfy_topic", topic),
                       ("ntfy_token_file", token_file)):
        set_toml_key(user_config, "notifications", key, value)
    # `set_toml_key` refait `.bak` à chaque clé : la sauvegarde doit rester le fichier d'avant.
    backup = user_config.with_suffix(user_config.suffix + ".bak")
    if original is None:
        backup.unlink(missing_ok=True)
    elif user_config.read_bytes() != original:
        backup.write_bytes(original)
    ok(f"Section [notifications] écrite dans {user_config}")


def ask(prompt: str) -> str:
    try:
        return input(prompt).strip()
    except EOFError:
        return ""


def cmd_setup(args) -> int:
    workspace = resolve_workspace()
    user_config = config_paths(workspace)[1]
    try:
        current = notifications_section(workspace)
    except ConfigError as exc:
        err(str(exc))
        return 1
    current_url = str(current.get("ntfy_url") or DEFAULT_URL)
    current_topic = str(current.get("ntfy_topic") or "")
    interactive = sys.stdin.isatty()

    if args.disable:
        write_settings(user_config, "none", current_url, current_topic,
                       str(current.get("ntfy_token_file") or ""))
        ok("Notifications désactivées.")
        return 0

    log("Configuration des notifications ntfy")
    print()

    # --- 1. Serveur ---------------------------------------------------------------
    url = args.url or ""
    if not url and not interactive:
        url = current_url
    if not url:
        print("Serveur ntfy :")
        print("  1) public  — https://ntfy.sh (gratuit, aucun compte ; le sujet fait office de secret)")
        print("  2) auto-hébergé — votre propre serveur (ex. https://ntfy.mondomaine.fr)")
        if (ask("Choix [1/2] (défaut : 1) : ") or "1") == "2":
            url = ask(f"URL du serveur [{current_url}] : ") or current_url
        else:
            url = DEFAULT_URL
    url = url.rstrip("/")

    # --- 2. Sujet -----------------------------------------------------------------
    topic = args.topic or ""
    if not topic and not interactive:
        topic = current_topic
        if not topic:
            err("--topic requis en mode non interactif.")
            return 1
    if not topic:
        suggested = current_topic or random_topic()
        topic = ask(f"Sujet (topic) [{suggested}] : ") or suggested

    # --- 3. Token (serveur avec authentification) ---------------------------------
    token_file = args.token_file or ""
    if not token_file and url != DEFAULT_URL and interactive:
        print()
        print("Si votre serveur exige une authentification (auth-default-access: deny-all),")
        print("créez un utilisateur + token côté serveur, par exemple :")
        print("  ntfy user add --role=user coach            # ou : docker exec -it ntfy ntfy user add ...")
        print(f"  ntfy access coach {topic} write-only")
        print("  ntfy token add coach                       # → tk_xxxxxxxx")
        token = ask("Token d'accès (laisser vide si le serveur n'en exige pas) : ")
        if token:
            path = Path(os.path.expanduser(DEFAULT_TOKEN_FILE))
            path.parent.mkdir(parents=True, exist_ok=True)
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(token + "\n")
            token_file = str(path)
            ok(f"Token enregistré dans {path} (chmod 600, hors du dépôt)")
    if token_file:
        expanded = os.path.expanduser(token_file)
        if not os.path.isfile(expanded):
            err(f"Fichier token introuvable : {expanded}")
            return 1
        try:
            os.chmod(expanded, 0o600)
        except OSError:
            pass
        token_file = portable_path(expanded)

    # --- 4. Écriture + test --------------------------------------------------------
    write_settings(user_config, "ntfy", url, topic, token_file)

    print()
    log("Sur votre téléphone : installez l'appli ntfy, puis « + » → abonnez-vous à :")
    print(f"    serveur : {url}")
    print(f"    sujet   : {topic}")
    print()

    if not args.no_test and interactive:
        answer = ask("Envoyer une notification de test maintenant ? [O/n] : ").lower() or "o"
        if answer in ("o", "oui", "y", "yes"):
            test = argparse.Namespace(
                title="AI Running Coach", priority="3", tags="white_check_mark",
                message="Notifications configurées ✅ — vous recevrez ici le résumé de chaque "
                        "synchronisation Garmin.")
            cmd_send(test)
    ok("Terminé. Les synchronisations automatiques (scripts/daily-sync.sh) enverront leur résumé ici.")
    return 0


def parse_send(argv: list) -> argparse.Namespace:
    """Options de `send`, lues comme le faisait notify.sh : tout argument qui n'est pas une
    option connue est le message (un résumé qui commence par « - » reste un message)."""
    args = argparse.Namespace(title="AI Running Coach", priority="3", tags="running", message="")
    values = list(argv)
    while values:
        arg = values.pop(0)
        if arg in ("--title", "--priority", "--tags"):
            if not values:
                raise NotifyError(f"L'option {arg} attend une valeur (voir --help).")
            setattr(args, arg[2:], values.pop(0))
        elif arg in ("--help", "-h"):
            print(__doc__.strip())
            raise SystemExit(0)
        else:
            args.message = arg
    return args


def build_setup_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="arc_notify.py setup", description="Configurer ntfy (serveur, sujet, token) et tester.")
    parser.add_argument("--url", default="")
    parser.add_argument("--topic", default="")
    parser.add_argument("--token-file", default="")
    parser.add_argument("--disable", action="store_true", help='provider = "none"')
    parser.add_argument("--no-test", action="store_true", help="pas de notification de test")
    return parser


def main(argv: Optional[list] = None) -> int:
    argv = sys.argv[1:] if argv is None else list(argv)
    command, rest = (argv[0], argv[1:]) if argv else ("", [])
    try:
        if command == "send":
            return cmd_send(parse_send(rest))
        if command == "setup":
            return cmd_setup(build_setup_parser().parse_args(rest))
        if command in ("--help", "-h"):
            print(__doc__.strip())
            return 0
        err("Commande attendue : send | setup (voir --help).")
        return 1
    except NotifyError as exc:
        err(str(exc))
        return 1
    except KeyboardInterrupt:
        print()
        return 130


if __name__ == "__main__":
    sys.exit(main())
