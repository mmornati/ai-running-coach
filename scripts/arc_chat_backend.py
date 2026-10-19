#!/usr/bin/env python3
"""Contrat commun du chat coach : événements, noms d'outils canoniques, backends.

Le service `scripts/arc_chat.py` parle au navigateur avec un protocole unique
(événements SSE ci-dessous) ; chaque backend — `mock`, `claude` (Claude Agent SDK,
`arc_chat_claude.py`), `opencode` (serveur OpenCode, `arc_chat_opencode.py`) —
traduit son propre flux vers ce protocole. Le navigateur ne sait jamais quel
modèle tourne derrière.

Les outils sont ramenés à des noms **canoniques** avant de passer par la
politique de permissions (`config/chat-policy.toml`) : les deux harnais
nomment différemment le même outil (`Write` / `write`,
`mcp__garmin__schedule_workouts` / `garmin_schedule_workouts`…).

Bibliothèque standard uniquement (CONTRIBUTING.md). Seul `arc_chat_claude.py`
importe un paquet tiers (`claude-agent-sdk`), paresseusement.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

# ---------------------------------------------------------------------------
# Événements (SSE : `event: <type>\ndata: <json>\n\n`)
# ---------------------------------------------------------------------------
#
#   text_delta         {"text": str, "part": str (facultatif : id du bloc de texte — un nouvel id
#                       ouvre un nouveau bloc côté page)}
#   tool_start         {"id": str, "name": str (canonique), "summary": str}
#   tool_end           {"id": str, "ok": bool, "summary": str}
#   approval_request   {"approval_id": str, "tool": str, "summary": str,
#                       "diff": [{"op": "-"|"+"|" ", "text": str}], "expires_at": iso8601}
#   approval_resolved  {"approval_id": str, "decision": "allow"|"deny"|"pending"|"expired"|"cancelled"|"unexecuted"}
#   file_written       {"path": str (relatif au workspace)}
#   usage              {"input_tokens": int, "output_tokens": int,
#                       "cache_read_tokens": int, "cost_eur": float,
#                       "billing": "subscription" (facultatif : forfait ChatGPT/Copilot, cost_eur = 0)}
#   done               {"reason": "end_turn"|"interrupted"|"budget"|"max_turns"|"pending_approval"}
#   error              {"message": str (français, lisible par l'athlète)}
#   status             {"message": str} — état passager (fournisseur saturé, nouvelle tentative…),
#                      affiché le temps d'attendre, jamais conservé dans l'historique

EVENT_TYPES = (
    "text_delta", "tool_start", "tool_end", "approval_request", "approval_resolved",
    "file_written", "usage", "done", "error", "status",
)

# ---------------------------------------------------------------------------
# Noms d'outils canoniques
# ---------------------------------------------------------------------------
#
#   fs.read      {"path": str}
#   fs.write     {"path": str}            (création, écrasement ou édition)
#   fs.list      {"path": str}            (glob/grep/ls)
#   shell        {"command": str}
#   web.fetch    {"url": str}
#   web.search   {"query": str}
#   task         {"agent": str}           (délégation à un sous-agent)
#   skill        {"name": str}
#   mcp:<serveur>.<outil>                 (ex. "mcp:garmin.schedule_workouts")
#   other:<nom>                           (tout le reste — refusé par défaut)

CANONICAL_PREFIXES = ("fs.", "shell", "web.", "task", "skill", "mcp:", "other:")

Decision = str  # "allow" | "deny" | "pending"


def payload_hash(tool: str, tool_input: dict) -> str:
    """Empreinte stable d'un appel d'outil : lie une approbation à UN contenu exact."""
    canonical = json.dumps({"tool": tool, "input": tool_input}, sort_keys=True,
                           ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# Ajouté au prompt système par chaque backend (langue de sortie inchangée :
# AGENTS.md et la configuration décident).
SYSTEM_ADDENDUM = """\
Tu réponds à l'athlète via l'interface web « Coach » du tableau de bord.
- Toute écriture vers Garmin ou intervals.icu est soumise à l'approbation explicite
  de l'athlète : propose le changement, appelle l'outil, et l'interface affichera une
  carte de confirmation. N'affirme jamais qu'un changement est appliqué avant le
  résultat de l'outil.
- Si l'outil répond que l'approbation est « en attente », dis simplement que la
  proposition attend la confirmation de l'athlète (depuis la page ou la notification).
- Pas de shell libre : seuls les scripts du projet listés par la politique sont exécutables.
- Réponses concises, adaptées à un écran de téléphone.
- Ne recopie JAMAIS dans ta réponse le contenu d'un fichier que tu lis ou écris, ni ses
  blocs ```arc / JSON / YAML : l'interface affiche déjà un lien vers chaque fichier écrit.
  Résume en phrases ce qui compte pour l'athlète (chiffres clés, décision, prochaine étape).
- N'affirme jamais avoir enregistré, écrit ou modifié quoi que ce soit sans que l'outil
  d'écriture correspondant ait réussi dans CE tour : l'athlète le vérifie dans la trace.
- Va au bout de la demande dans le même tour : n'annonce pas « je reviens avec… » pour
  t'arrêter ensuite — fais les appels nécessaires, puis réponds.
"""


LANGUAGE_NAMES = {"fr": "français", "en": "anglais", "it": "italien", "es": "espagnol",
                  "de": "allemand", "nl": "néerlandais", "pt": "portugais"}


def system_addendum(language: str = "fr") -> str:
    """`SYSTEM_ADDENDUM` + la langue de réponse, explicite.

    Une commande seule (« /today ») ne dit rien de la langue : sans cette ligne, un modèle
    peut répondre en anglais, voire mélanger les deux (observé avec DeepSeek).
    """
    name = LANGUAGE_NAMES.get((language or "fr").lower(), language or "français")
    return SYSTEM_ADDENDUM + (
        f"- Langue : réponds dans la langue du message de l'athlète ; pour une commande seule "
        f"(/today, /week, /why, /race, /log…) ou un message sans indice, en {name}. Une seule "
        f"langue par réponse, titres et libellés compris.\n")


class BackendError(RuntimeError):
    """Erreur attendue d'un backend : message français lisible, pas de trace."""


@dataclass
class TurnContext:
    """Ce que le service fournit à un backend pour UN tour de conversation.

    `emit` et `request_approval` sont thread-safe. `request_approval` bloque
    jusqu'à la décision de l'athlète, l'expiration du délai d'attente en ligne
    (→ "pending", la proposition reste ouverte et reprendra la session plus
    tard), ou l'annulation du tour (→ "deny").
    """

    session_id: str
    workspace: Path
    config: dict                                   # section [chat] résolue
    emit: Callable[[str, dict], None]              # emit(type, payload)
    decide: Callable[[str, dict], str]             # politique : "allow" | "ask" | "deny"
    request_approval: Callable[[str, dict, str, list], Decision]  # (tool, input, summary, diff)
    cancelled: threading.Event = field(default_factory=threading.Event)
    # État propre au backend, persisté avec la session (ex. id de session SDK / OpenCode).
    backend_state: dict = field(default_factory=dict)
    language: str = "fr"


# Identifiants retirés de l'environnement des processus enfants en mode famille : liste fermée (noms connus)
# PLUS une règle par motif (`family_scrubbed_names`), pour qu'un futur fournisseur ne passe pas entre les mailles.
FAMILY_SCRUBBED_ENV = ("GARMINTOKENS", "GARMIN_TOKENS_DIR", "GARMINTOKENS_BASE64", "GARMIN_EMAIL",
                       "GARMIN_PASSWORD", "INTERVALS_ICU_API_KEY", "INTERVALS_ICU_ATHLETE_ID",
                       "STRAVA_CLIENT_ID", "STRAVA_CLIENT_SECRET", "STRAVA_TOKEN_FILE",
                       "MYWHOOSH_USERNAME", "MYWHOOSH_PASSWORD", "ARC_OW_API_KEY_FILE", "ARC_OW_BASE_URL",
                       "TELEGRAM_BOT_TOKEN", "NTFY_TOKEN_FILE", "AZURE_SPEECH_KEY")
FAMILY_SCRUBBED_PREFIXES = ("GARMIN", "INTERVALS_ICU_", "STRAVA_", "MYWHOOSH_", "ARC_OW_", "TELEGRAM_", "NTFY_",
                            "OURA_", "WHOOP_", "WITHINGS_", "POLAR_", "COROS_", "SUUNTO_")
FAMILY_SCRUBBED_MARKERS = ("TOKEN", "SECRET", "PASSWORD", "PASSWD", "API_KEY", "APIKEY", "CREDENTIAL")
FAMILY_SCRUBBED_SUFFIXES = ("_KEY", "_KEY_FILE")


def family_reserved_name(name: str) -> bool:
    """Vrai si `name` désigne un identifiant du foyer (liste fermée ou préfixe de fournisseur) : jamais exemptable."""
    up = str(name).upper()
    return str(name) in FAMILY_SCRUBBED_ENV or up in FAMILY_SCRUBBED_ENV or up.startswith(FAMILY_SCRUBBED_PREFIXES)


def family_scrubbed_names(environ, keep=()) -> list:
    """Noms à retirer de `environ` en mode famille : liste fermée + toute variable présente dont le nom commence
    par un préfixe de fournisseur, contient un marqueur de secret ou finit par `_KEY` / `_KEY_FILE`.
    `keep` : ce dont le backend du membre a légitimement besoin (clé du fournisseur LLM), jamais retiré, SAUF un nom
    réservé (`family_reserved_name`) : un `api_key_env = "GARMINTOKENS"` ne doit pas exempter un identifiant du foyer."""
    keep = {k for k in keep if k and not family_reserved_name(k)}
    names = set(FAMILY_SCRUBBED_ENV)
    for name in environ:
        up = name.upper()
        if (up.startswith(FAMILY_SCRUBBED_PREFIXES) or any(m in up for m in FAMILY_SCRUBBED_MARKERS)
                or up.endswith(FAMILY_SCRUBBED_SUFFIXES)):
            names.add(name)
    return sorted(names - keep)


class ChatBackend(ABC):
    """Un backend traduit un harnais (SDK, serveur OpenCode, mock) vers le protocole."""

    name: str = "abstract"

    def __init__(self, workspace: Path, config: dict):
        self.workspace = workspace
        self.config = config

    @property
    def family_member(self) -> str:
        """Identifiant du membre en mode famille (#127, posé par `arc_chat.family_member_config`), sinon ""."""
        return str(self.config.get("family_member") or "")

    def llm_key_env(self) -> str:
        """Nom de la variable portant la clé du fournisseur LLM de ce backend (jamais retirée en mode famille)."""
        return str(self.config.get("api_key_env") or "")

    def family_overlay(self, base: Optional[dict] = None) -> dict:
        """Variables d'environnement à IMPOSER aux processus enfants (outils shell, serveurs MCP) en mode famille.

        Sans cela, les scripts autorisés (`arc_index.py`, `arc_log.py`…) retrouveraient le workspace d'un AUTRE
        membre par `$ARC_WORKSPACE` hérité du conteneur ou par le pointeur `~/.config/ai-running-coach/workspace`.
        Une valeur vide retire la variable (jetons Garmin : ceux du membre viennent du `.mcp.json` de SON workspace).
        Les identifiants intervals.icu et Garmin posés au niveau du foyer (conteneur, llm.env) sont retirés aussi :
        `download_fit.py` lit `$INTERVALS_ICU_API_KEY` en premier et le serveur MCP intervals l'hérite, ce qui
        donnerait à un membre les données d'un autre ; ceux du membre viennent du `.env` / `.mcp.json` de SON workspace.
        La règle est un motif (`family_scrubbed_names`, appliqué à `base`, défaut `os.environ`) : Strava, MyWhoosh,
        Open Wearables, Telegram, ntfy, Azure… et tout futur fournisseur, hors la clé LLM du membre (`llm_key_env`).
        Vide hors mode famille : comportement historique."""
        if not self.family_member:
            return {}
        return {"ARC_WORKSPACE": str(self.workspace), "ARC_LOCK_WORKSPACE": "1",
                **{name: "" for name in family_scrubbed_names(
                    os.environ if base is None else base, (self.llm_key_env(),))}}

    def child_env(self, base: Optional[dict] = None) -> dict:
        """Environnement complet d'un processus enfant : `base` (défaut `os.environ`) + `family_overlay()`."""
        env = dict(os.environ if base is None else base)
        for key, value in self.family_overlay(env).items():
            if value == "":
                env.pop(key, None)
            else:
                env[key] = value
        return env

    @abstractmethod
    def run_turn(self, ctx: TurnContext, user_message: str) -> None:
        """Exécute un tour complet ; émet les événements ; se termine par `done`.

        Doit passer CHAQUE appel d'outil par `ctx.decide(tool, input)` puis, si
        "ask", par `ctx.request_approval(...)`. "deny" / "pending" → l'outil
        n'est pas exécuté et le modèle reçoit un refus explicite. Lève
        `BackendError` pour une erreur attendue (clé absente, fournisseur
        injoignable, crédit épuisé…).
        """

    def check(self) -> tuple:
        """(ok, message) sans dépenser de jetons — utilisé par /healthz et coach-doctor."""
        return True, f"backend {self.name}"

    def billing(self) -> Optional[dict]:
        """`{"mode": "subscription", "label": "ChatGPT"}` quand les tours sont inclus dans un forfait
        (aucun coût au jeton, rien n'est compté contre le plafond du jour), sinon None."""
        return None

    def shutdown(self) -> None:
        """Libère les ressources (processus enfant, boucle asyncio…)."""


def load_backend(name: str, workspace: Path, config: dict) -> ChatBackend:
    """Fabrique : import paresseux, pour que `mock` n'exige aucun paquet tiers."""
    if name == "mock":
        from arc_chat_mock import MockBackend  # type: ignore
        return MockBackend(workspace, config)
    if name == "claude":
        from arc_chat_claude import ClaudeBackend  # type: ignore
        return ClaudeBackend(workspace, config)
    if name == "opencode":
        from arc_chat_opencode import OpenCodeBackend  # type: ignore
        return OpenCodeBackend(workspace, config)
    raise BackendError(f"Backend de chat inconnu : {name!r} (mock | claude | opencode)")


def resolve_workspace_path(workspace: Path, raw: Optional[str]) -> Optional[str]:
    """Chemin relatif au workspace, ou None s'il en sort (défense contre `..`)."""
    if not raw:
        return None
    try:
        p = (workspace / raw).resolve() if not Path(raw).is_absolute() else Path(raw).resolve()
        return p.relative_to(workspace.resolve()).as_posix()
    except (ValueError, OSError):
        return None
