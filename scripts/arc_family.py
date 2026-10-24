#!/usr/bin/env python3
"""Mode famille (#127) : registre des membres et identité de la requête.

Une seule application (tableau de bord `arc_serve.py`, chat `arc_chat.py`) sert
plusieurs athlètes, chacun dans SON workspace. Le reverse proxy (Authentik →
Traefik, forward-auth) pose l'identité dans un en-tête (`X-authentik-username`) ;
ce module la ramène à un membre du registre, ou refuse. Ce module est partagé par
les deux services : une seule règle d'identité, jamais deux.

    arc_family.py [--family FICHIER]      # valide le registre et le résume

Registre (`~/.config/ai-running-coach/family.toml`, ou `--family`, ou `ARC_FAMILY`) :

    [family]                                  # facultatif pour la validation, requis pour servir
    trusted_proxies = ["traefik"]             # adresses, CIDR ou noms d'hôte des proxys de confiance
    auth_header = "X-authentik-username"      # défaut
    daily_budget_eur = 5.0                    # plafond du foyer pour le chat (0 ou absent : aucun)
    allowed_hosts = ["coach.example.org"]     # en-têtes Host acceptés (chat)
    public_url = "https://coach.example.org"  # liens ntfy du chat

    [members.alice]                           # identifiant : [a-z0-9_-]+
    workspace = "/home/athlete/coach-alice"   # chemin absolu d'un dossier existant
    display_name = "Alice"                    # facultatif
    identities = ["Alice.Martin"]             # facultatif : autres valeurs de l'en-tête pour ce membre

Garanties :
- l'en-tête sert de CLÉ DE RECHERCHE (comparaison exacte), jamais à construire un chemin ;
- source hors `trusted_proxies`, en-tête absent ou inconnu : 403, sans donnée ni liste de membres ;
- chemins absolus existants, ni doublon ni imbrication entre workspaces.

Bibliothèque standard uniquement (CONTRIBUTING.md).
"""

from __future__ import annotations

import argparse
import ipaddress
import os
import re
import socket
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
from coach_config import ConfigError, read_toml  # noqa: E402

MEMBER_ID_RE = re.compile(r"^[a-z0-9_-]+$")
DEFAULT_AUTH_HEADER = "X-authentik-username"
FAMILY_ENV = "ARC_FAMILY"
DENIED = "Accès refusé."


# ---------------------------------------------------------------------------
# Source de confiance (partagé avec arc_chat : même comportement, un seul code)
# ---------------------------------------------------------------------------

def _normalized(ip: str):
    """Adresse IP analysée ; un pair IPv4-mappé (`::ffff:a.b.c.d`, socket double pile) devient son IPv4."""
    addr = ipaddress.ip_address(str(ip).split("%", 1)[0])
    mapped = getattr(addr, "ipv4_mapped", None)
    return mapped if mapped is not None else addr


def is_loopback(ip: str) -> bool:
    try:
        return _normalized(ip).is_loopback
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
        addr = _normalized(ip)
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


# ---------------------------------------------------------------------------
# Registre
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Member:
    id: str
    workspace: Path
    display_name: str
    identities: tuple = ()


@dataclass
class Registry:
    path: Path
    members: dict = field(default_factory=dict)       # id → Member (ordre du fichier)
    settings: dict = field(default_factory=dict)      # section [family] normalisée
    _by_identity: dict = field(default_factory=dict)  # valeur d'en-tête → Member

    @property
    def auth_header(self) -> str:
        return self.settings["auth_header"]

    @property
    def trusted_proxies(self) -> list:
        return self.settings["trusted_proxies"]

    def lookup(self, identity: str) -> Optional[Member]:
        """Membre dont l'identifiant ou un alias est EXACTEMENT `identity` (dictionnaire :
        aucun chemin n'est jamais construit à partir de cette valeur)."""
        return self._by_identity.get(identity)

    def require_trusted_proxies(self) -> None:
        """Le mode famille se fie à un en-tête d'identité : sans proxy de confiance déclaré, n'importe
        quel client pourrait l'écrire lui-même. On refuse de démarrer."""
        if not self.trusted_proxies:
            raise ConfigError(
                f"{self.path} : [family].trusted_proxies est vide — le mode famille se fie à l'en-tête "
                f"{self.auth_header} posé par le proxy d'authentification et refuse de démarrer sans lui.")


def default_registry_path() -> Path:
    return Path("~/.config/ai-running-coach/family.toml").expanduser()


def resolve_registry_path(raw: Optional[str] = None, environ=None) -> Path:
    """`--family PATH` > `ARC_FAMILY` > `~/.config/ai-running-coach/family.toml`."""
    environ = os.environ if environ is None else environ
    value = raw or environ.get(FAMILY_ENV)
    return Path(value).expanduser() if value else default_registry_path()


def _str_list(value, label: str, path: Path) -> list:
    if value is None or value == "":
        return []
    if isinstance(value, str):
        return [value]
    if not isinstance(value, (list, tuple)) or not all(isinstance(v, str) for v in value):
        raise ConfigError(f"{path} : {label} doit être une liste de chaînes.")
    return [v.strip() for v in value if v.strip()]


def _llm_key_envs(value, path: Path) -> list:
    """`[family].llm_key_envs` : noms de variables de clé LLM autorisés en plus des fournisseurs connus."""
    from arc_chat_backend import LLM_KEY_ENV_RE, family_reserved_name
    names = _str_list(value, "[family].llm_key_envs", path)
    for name in names:
        if not re.fullmatch(LLM_KEY_ENV_RE, name):
            raise ConfigError(f"{path} : [family].llm_key_envs : nom invalide « {name} » (A-Z, 0-9 et « _ »).")
        if family_reserved_name(name):
            raise ConfigError(f"{path} : [family].llm_key_envs : « {name} » est un identifiant du foyer, "
                              "jamais utilisable comme clé LLM.")
    return names


def _settings(raw: dict, path: Path) -> dict:
    header = str(raw.get("auth_header") or DEFAULT_AUTH_HEADER).strip()
    if not re.fullmatch(r"[A-Za-z0-9-]+", header):
        raise ConfigError(f"{path} : [family].auth_header invalide (« {header} »).")
    try:
        budget = float(raw.get("daily_budget_eur") or 0.0)
    except (TypeError, ValueError):
        raise ConfigError(f"{path} : [family].daily_budget_eur doit être un nombre.")
    if budget < 0:
        raise ConfigError(f"{path} : [family].daily_budget_eur ne peut pas être négatif.")
    return {
        "auth_header": header,
        "trusted_proxies": _str_list(raw.get("trusted_proxies"), "[family].trusted_proxies", path),
        "allowed_hosts": _str_list(raw.get("allowed_hosts"), "[family].allowed_hosts", path),
        "public_url": str(raw.get("public_url") or "").strip(),
        "daily_budget_eur": budget,
        "llm_key_envs": _llm_key_envs(raw.get("llm_key_envs"), path),
        "llm_base_urls": _str_list(raw.get("llm_base_urls"), "[family].llm_base_urls", path),
        "listen": str(raw.get("listen") or "").strip(),
        "port": raw.get("port"),
        "chat_port": raw.get("chat_port"),
    }


def parse_registry(raw: dict, path: Path) -> Registry:
    # Repli TOML (Python < 3.11, `coach_config`) : « [members.alice] » arrive à plat sous la clé « members.alice ».
    flat = {k[len("members."):]: v for k, v in raw.items() if k.startswith("members.") and isinstance(v, dict)}
    members_raw = raw.get("members")
    if flat:
        members_raw = {**(members_raw if isinstance(members_raw, dict) else {}), **flat}
    if not isinstance(members_raw, dict) or not members_raw:
        raise ConfigError(f"{path} : aucune section [members.<identifiant>] — le registre est vide.")
    registry = Registry(path=path, settings=_settings(raw.get("family") or {}, path))
    workspaces: dict = {}
    for member_id, entry in members_raw.items():
        if not MEMBER_ID_RE.fullmatch(str(member_id)):
            raise ConfigError(f"{path} : identifiant de membre invalide « {member_id} » "
                              "(minuscules, chiffres, « _ » et « - » uniquement).")
        if not isinstance(entry, dict):
            raise ConfigError(f"{path} : [members.{member_id}] doit être une table.")
        raw_ws = str(entry.get("workspace") or "").strip()
        if not raw_ws or not os.path.isabs(raw_ws):
            raise ConfigError(f"{path} : [members.{member_id}].workspace doit être un chemin ABSOLU.")
        workspace = Path(raw_ws)
        if not workspace.is_dir():
            raise ConfigError(f"{path} : [members.{member_id}].workspace n'existe pas ou n'est pas un dossier.")
        real = workspace.resolve()
        for other_id, other in workspaces.items():
            if real == other or real in other.parents or other in real.parents:
                raise ConfigError(
                    f"{path} : les workspaces de « {other_id} » et « {member_id} » sont identiques ou imbriqués.")
        workspaces[member_id] = real
        aliases = tuple(_str_list(entry.get("identities"), f"[members.{member_id}].identities", path))
        member = Member(id=member_id, workspace=workspace,
                        display_name=str(entry.get("display_name") or member_id), identities=aliases)
        registry.members[member_id] = member
        for key in (member_id, *aliases):
            if key in registry._by_identity:
                raise ConfigError(f"{path} : l'identité « {key} » désigne deux membres.")
            registry._by_identity[key] = member
    return registry


def load_registry(path) -> Registry:
    path = Path(path).expanduser()
    if not path.is_file():
        raise ConfigError(f"registre famille introuvable : {path} (voir docs/family.md).")
    return parse_registry(read_toml(path), path)


# ---------------------------------------------------------------------------
# Identité de la requête
# ---------------------------------------------------------------------------

def authenticate_member(registry: Registry, peer_ip: str, headers) -> tuple:
    """(membre, statut, message). Statut 0 = accepté, sinon 403 — toujours la même réponse
    neutre : ni la raison précise, ni la liste des membres ne sortent."""
    if not ip_in(peer_ip, registry.trusted_proxies):
        return None, 403, DENIED
    identity = (headers.get(registry.auth_header) or "").strip()
    member = registry.lookup(identity) if identity else None
    if member is None:
        return None, 403, DENIED
    return member, 0, ""


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--family", help="registre (défaut : ARC_FAMILY, puis ~/.config/ai-running-coach/family.toml)")
    args = parser.parse_args(argv)
    registry = load_registry(resolve_registry_path(args.family))
    print(f"registre {registry.path} : {len(registry.members)} membre(s)")
    for member in registry.members.values():
        print(f"  {member.id} → {member.workspace}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except ConfigError as exc:
        print(f"erreur : {exc}", file=sys.stderr)
        sys.exit(1)
