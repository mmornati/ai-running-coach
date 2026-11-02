#!/usr/bin/env python3
"""Hook PreToolUse de la session Telegram (Claude Code Channels, #337).

La session est pilotée par des messages distants : chaque appel d'outil passe ici AVANT les règles de
permission (matcher « * »). Ce hook est enregistré dans un fichier de réglages DÉDIÉ, passé par
`claude --settings` à cette seule session (jamais dans `settings.local.json`).

Décisions, du plus strict au plus lâche :

    deny  -> "deny"   refus net (la politique du chat, ou une règle propre au hook ci-dessous)
    ask   -> "ask"    approbation demandée
    allow -> "allow"  UNIQUEMENT pour Bash, quand `arc_chat_policy.Policy.decide("shell", …)` répond
                      allow (analyse complète de la ligne de commande, comme le chat du tableau de bord)
    sinon -> silence  les règles de `--settings` décident

Un « allow » de hook ne lève ni une règle `ask` ni une règle `deny` des réglages ; il évite seulement
l'invite pour une commande que la politique autorise. Règles propres au hook :

- le TRADUCTEUR d'appels est celui du chat du tableau de bord (`arc_chat_claude.canonical_tool`) : la
  regex d'un Grep, le filtre d'un Glob, les chemins d'un patch, l'URL et la commande arrivent tels quels
  à la politique ; un outil inconnu devient `other:<nom>`, refusé ;
- outils MCP : tout nom contenant delete / remove / unschedule / disconnect est refusé ; la passerelle
  `leanproxy` est refusée (elle pourrait porter une suppression sous un autre nom) ;
- outils du plugin Telegram : `reply` envoie des fichiers locaux (`files`) ; chacun doit passer par
  `Policy.decide("fs.read")` (secrets et `.arc/` refusés), sauf sous le dossier `inbox/` du plugin ;
  `react`, `edit_message` et `download_attachment` ne portent aucun chemin ; tout autre outil du plugin est
  refusé. Lire une photo reçue (Read sous `inbox/`) est permis ;
- quelques outils internes sans effet (TodoWrite, ExitPlanMode…) restent silencieux ; AskUserQuestion
  (personne ne verrait la question) et tout outil inconnu sont refusés.

Échec fermé : une erreur (entrée illisible, politique introuvable, import impossible) imprime un « deny »,
écrit la raison sur la sortie d'erreur et sort avec le code 2, qui bloque l'appel (les autres codes de
sortie, dont 1 et 127, ne bloquent pas). Aucun contenu de commande n'est journalisé.

Attention : `ask` ne protège PAS contre un compte autorisé compromis : tout compte de `allowFrom` peut
approuver une demande relayée par le plugin. Seules les décisions « deny » (réglages et hook) tiennent.

Entrée : JSON de Claude Code sur l'entrée standard (`tool_name`, `tool_input`, `cwd`).
Bibliothèque standard uniquement.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

ENGINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

CHANNEL_PREFIX = "mcp__plugin_telegram_telegram__"
# Outils du plugin sans chemin ni fichier : seuls autorisés en dehors de `reply`.
CHANNEL_PLAIN_TOOLS = ("react", "edit_message", "download_attachment")
# Outils internes de Claude Code sans effet sur le disque, le réseau ni les données : silence.
HARMLESS_BUILTINS = ("TodoWrite", "ExitPlanMode", "EnterPlanMode", "ToolSearch",
                     "TaskCreate", "TaskUpdate", "TaskList", "TaskGet")
# Noms d'outils MCP qui suppriment ou déconnectent : jamais depuis Telegram.
DESTRUCTIVE_MCP = re.compile(r"delete|remove|unschedule|disconnect", re.IGNORECASE)


def _deps():
    """Imports différés : une erreur d'import doit tomber dans le `try` de main (échec fermé)."""
    from arc_chat_claude import canonical_tool
    from arc_chat_policy import Policy
    return canonical_tool, Policy


def state_dir() -> Path:
    """Dossier d'état du plugin : TELEGRAM_STATE_DIR, sinon <CLAUDE_CONFIG_DIR ou ~/.claude>/channels/telegram."""
    explicit = os.environ.get("TELEGRAM_STATE_DIR")
    if explicit:
        return Path(explicit)
    config = os.environ.get("CLAUDE_CONFIG_DIR") or str(Path.home() / ".claude")
    return Path(config) / "channels" / "telegram"


def _under(path: Path, folder: Path) -> bool:
    try:
        path.relative_to(folder)
    except ValueError:
        return False
    return True


def _real(raw: str, base: Path) -> Path:
    p = Path(os.path.expanduser(raw))
    return (p if p.is_absolute() else base / p).resolve()


def _deny(reason: str) -> tuple:
    return "deny", reason


def decide_channel(tool: str, tool_input: dict, policy, workspace: Path) -> tuple:
    name = tool[len(CHANNEL_PREFIX):]
    if name in CHANNEL_PLAIN_TOOLS:
        return "", "canal Telegram"
    if name != "reply":
        return _deny(f"outil du plugin Telegram non prévu : {name}")
    files = tool_input.get("files")
    if files in (None, []):
        return "", "réponse sans fichier"
    if not isinstance(files, list):
        return _deny("reply : « files » doit être une liste")
    inbox = (state_dir() / "inbox").resolve()
    for item in files:
        if not isinstance(item, str) or not item.strip():
            return _deny("reply : chemin de fichier invalide")
        real = _real(item, workspace)
        if _under(real, inbox):
            continue
        if policy.decide("fs.read", {"path": str(real)}) != "allow":
            return _deny("reply : fichier hors de ce que la politique du chat laisse lire")
    return "", "réponse avec fichiers autorisés par la politique"


def decide(payload: dict) -> tuple:
    """(verdict, raison) ; verdict : « deny », « ask », « allow » (Bash seulement) ou « » (silence)."""
    tool = str(payload.get("tool_name") or "")
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        return _deny("entrée d'outil illisible")
    if tool in HARMLESS_BUILTINS:
        return "", "outil interne sans effet"
    if tool == "AskUserQuestion":
        return _deny("personne ne voit les questions du terminal : répondre par le canal Telegram")
    canonical_tool, Policy = _deps()
    workspace = Path(os.environ.get("CLAUDE_PROJECT_DIR") or payload.get("cwd") or os.getcwd()).resolve()
    policy = Policy.load(ENGINE, workspace)
    if tool.startswith(CHANNEL_PREFIX):
        return decide_channel(tool, tool_input, policy, workspace)
    if tool.startswith("mcp__"):
        parts = tool.split("__", 2)
        server, name = (parts[1].lower(), parts[2]) if len(parts) == 3 else ("", "")
        if server.startswith("leanproxy"):
            return _deny("la passerelle leanproxy est incompatible avec la session Telegram")
        if DESTRUCTIVE_MCP.search(name):
            return _deny("suppression ou déconnexion : interdite depuis Telegram")
    if tool in ("Read", "NotebookRead"):
        raw = str(tool_input.get("file_path") or tool_input.get("notebook_path") or "")
        if raw and _under(_real(raw, workspace), (state_dir() / "inbox").resolve()):
            return "", "photo ou fichier reçu par le plugin"
    canonical, entry = canonical_tool(tool, tool_input)
    verdict = policy.decide(canonical, entry)
    if verdict == "allow":
        return ("allow" if tool == "Bash" else ""), f"politique du chat : allow ({canonical})"
    return verdict, f"politique du chat : {verdict} ({canonical})"


def hook_output(payload: dict):
    """Objet de décision à imprimer, ou None (silence)."""
    verdict, reason = decide(payload)
    if verdict not in ("allow", "ask", "deny"):
        return None
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": verdict,
                                   "permissionDecisionReason": reason}}


def main() -> int:
    try:
        payload = json.loads(sys.stdin.read() or "{}")
        out = hook_output(payload if isinstance(payload, dict) else {"tool_input": None})
    except BaseException as exc:  # noqa: BLE001 - échec fermé, quelle que soit l'erreur
        reason = f"politique du chat illisible ({type(exc).__name__})"
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                                  "permissionDecisionReason": reason}}))
        print(reason, file=sys.stderr)
        return 2
    if out is not None:
        print(json.dumps(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
