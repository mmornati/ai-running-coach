#!/usr/bin/env python3
"""Hook PreToolUse de la session Telegram (Claude Code Channels, #337).

La session est pilotée par des messages distants : chaque appel d'outil passe ici AVANT les règles
de permission. La décision vient de la politique du chat (`config/chat-policy.toml`,
`arc_chat_policy.Policy.decide`), la même que celle du chat du tableau de bord :

    allow -> aucune décision (le hook se tait : les règles des réglages décident, jamais plus large)
    ask   -> "ask"                        (approbation de l'athlète)
    deny  -> "deny"

Le hook ne fait que durcir : il ne renvoie jamais « allow », qui lèverait une règle `ask` des réglages. Toute
erreur (entrée illisible, politique introuvable) renvoie « deny » : jamais d'autorisation par défaut.
Aucun contenu de commande n'est écrit dans un journal. Bibliothèque standard uniquement.

Entrée : JSON de Claude Code sur l'entrée standard (`tool_name`, `tool_input`, `cwd`).
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from arc_chat_claude import canonical_tool  # noqa: E402
from arc_chat_policy import Policy  # noqa: E402

ENGINE = Path(__file__).resolve().parent.parent


# Outils du plugin Telegram lui-même (reply, edit_message, react, download_attachment…) : le canal
# de la conversation, hors du périmètre des serveurs sportifs de la politique.
CHANNEL_TOOL_PREFIX = "mcp__plugin_telegram_telegram"


def decide(payload: dict) -> tuple:
    """(verdict, raison). La traduction nom Claude Code -> entrée de politique est CELLE du chat du
    tableau de bord (`arc_chat_claude.canonical_tool`, qui s'appuie sur `arc_chat_tools.fs_list_input`) :
    tous les champs sur lesquels la politique décide (regex d'un Grep, filtre de Glob, chemins d'un
    patch, URL, commande) lui arrivent, exactement comme dans le chat. Un outil inconnu devient
    `other:<nom>`, que la politique refuse."""
    tool = str(payload.get("tool_name") or "")
    tool_input = payload.get("tool_input")
    if tool.startswith(CHANNEL_TOOL_PREFIX):
        return "allow", "canal Telegram du plugin"
    canonical, entry = canonical_tool(tool, tool_input if isinstance(tool_input, dict) else {})
    workspace = Path(os.environ.get("CLAUDE_PROJECT_DIR") or payload.get("cwd") or os.getcwd())
    verdict = Policy.load(ENGINE, workspace).decide(canonical, entry)
    return verdict, f"politique du chat : {verdict} ({canonical})"


def hook_output(payload: dict):
    """Sortie du hook : un objet de décision pour `ask`/`deny`, JAMAIS pour `allow` (None).

    Le hook ne peut que durcir. Un « allow » de hook l'emporterait sur une règle `ask` des réglages
    (ex. `download_activity_file`, classé lecture par la politique du chat mais écrivant un fichier, donc
    `ask` dans le template) : quand la politique laisse passer, il se tait et les réglages décident."""
    verdict, reason = decide(payload)
    if verdict not in ("ask", "deny"):
        return None
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": verdict,
                                   "permissionDecisionReason": reason}}


def main() -> int:
    try:
        payload = json.loads(sys.stdin.read() or "{}")
        out = hook_output(payload if isinstance(payload, dict) else {})
    except Exception as exc:  # noqa: BLE001 - fail closed, quelle que soit l'erreur
        out = {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                      "permissionDecisionReason": f"politique du chat illisible ({type(exc).__name__})"}}
    if out is not None:
        print(json.dumps(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
