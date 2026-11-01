#!/usr/bin/env python3
"""Hook PreToolUse de la session Telegram (Claude Code Channels, #337).

La session est pilotée par des messages distants : chaque appel d'outil passe ici AVANT les règles
de permission. La décision vient de la politique du chat (`config/chat-policy.toml`,
`arc_chat_policy.Policy.decide`), la même que celle du chat du tableau de bord :

    allow -> permissionDecision "allow"   (lecture, écriture sous les dossiers de données, script listé
                                           avec des options déclarées, domaine web listé)
    ask   -> "ask"                        (approbation de l'athlète)
    deny  -> "deny"

Les règles `deny` de `.claude/settings.local.json` restent prioritaires sur un « allow » de hook. Toute
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

from arc_chat_policy import Policy  # noqa: E402

ENGINE = Path(__file__).resolve().parent.parent


def to_policy_call(tool: str, tool_input: dict):
    """Nom Claude Code -> (outil canonique de la politique, entrée), ou None si l'outil n'est pas couvert."""
    if tool == "Bash":
        return "shell", {"command": str(tool_input.get("command") or "")}
    if tool == "WebFetch":
        return "web.fetch", {"url": str(tool_input.get("url") or "")}
    if tool == "Read":
        return "fs.read", {"path": str(tool_input.get("file_path") or "")}
    if tool in ("Write", "Edit", "MultiEdit"):
        return "fs.write", {"path": str(tool_input.get("file_path") or "")}
    if tool in ("Glob", "Grep"):
        entry = {"path": str(tool_input.get("path") or "")}
        if tool == "Glob":
            entry["glob"] = str(tool_input.get("pattern") or "")
        elif tool_input.get("glob"):
            entry["glob"] = str(tool_input.get("glob"))
        return "fs.list", entry
    return None


def decide(payload: dict) -> tuple:
    tool = str(payload.get("tool_name") or "")
    tool_input = payload.get("tool_input")
    call = to_policy_call(tool, tool_input if isinstance(tool_input, dict) else {})
    if call is None:
        return "ask", f"{tool} : hors du périmètre de la politique du chat"
    workspace = Path(os.environ.get("CLAUDE_PROJECT_DIR") or payload.get("cwd") or os.getcwd())
    policy = Policy.load(ENGINE, workspace)
    verdict = policy.decide(call[0], call[1])
    return verdict, f"politique du chat : {verdict} ({call[0]})"


def main() -> int:
    try:
        payload = json.loads(sys.stdin.read() or "{}")
        verdict, reason = decide(payload if isinstance(payload, dict) else {})
    except Exception as exc:  # noqa: BLE001 - fail closed, quelle que soit l'erreur
        verdict, reason = "deny", f"politique du chat illisible ({type(exc).__name__})"
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": verdict,
                                              "permissionDecisionReason": reason}}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
