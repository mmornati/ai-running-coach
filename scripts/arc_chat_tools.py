#!/usr/bin/env python3
"""Briques communes aux backends du chat coach (Claude, OpenCode).

Résumés français courts, diff d'approbation, textes de refus renvoyés au modèle,
conversion USD -> EUR. Aucune dépendance : bibliothèque standard uniquement.
Fichier propre à l'agent « backends » (pas listé dans SPEC, ajouté pour éviter
de dupliquer ce code dans les deux adaptateurs).
"""

from __future__ import annotations

import json
import re
from typing import Any, Optional

# Texte renvoyé au modèle quand l'outil n'est pas exécuté.
REFUSAL_DENY = ("Refusé : cette action n'est pas autorisée par la politique du coach "
                "ou l'athlète l'a refusée. Ne la réessaie pas ; explique-le simplement à l'athlète.")
REFUSAL_PENDING = "La proposition attend la confirmation de l'athlète."

MAX_DIFF_LINES = 40
MAX_TEXT = 80


def short(text: Any, limit: int = MAX_TEXT) -> str:
    """Texte sur une ligne, tronqué."""
    s = " ".join(str(text if text is not None else "").split())
    return s if len(s) <= limit else s[: limit - 1] + "…"


def usd_to_eur(usd: Any, rate: Any) -> float:
    """USD -> EUR arrondi au millionième d'euro ; 0 si la valeur est absente."""
    try:
        r = float(rate) if rate else 0.92
        return round(float(usd or 0.0) * r, 6)
    except (TypeError, ValueError):
        return 0.0


_LEANPROXY_META = ("list_servers", "list_tools", "search_tools")
_HASH_SUFFIX_RE = re.compile(r"_[0-9a-f]{10}$")
# Alias de noms de serveurs tels qu'exposés par leanproxy -> nom de serveur de la politique.
_SERVER_ALIASES = {"intervals_icu": "intervals"}


def map_leanproxy(tool: str, inp: dict) -> Optional[tuple]:
    """Outil exposé par le serveur MCP « leanproxy » (`tool` = nom SANS préfixe de serveur).

    - `invoke_tool` (passerelle) : seul `arguments` est l'entrée réellement exécutée ; si
      l'appel porte `args` à la place, on ne devine pas -> `other:` (refusé par la politique),
      pour que hash et diff reflètent ce qui s'exécute vraiment.
    - `list_servers|list_tools|search_tools` : `mcp:leanproxy.<outil>`.
    - outils exposés en direct `<serveur>__<outil>[_<hash>]` (ex. `garmin__get_rhr_day`,
      constaté dans la liste d'outils de leanproxy) : `mcp:<serveur>.<outil>`.
    Renvoie None si aucun motif ne s'applique (l'appelant garde le mapping générique).
    """
    if tool.endswith("invoke_tool"):
        server, name = inp.get("server"), inp.get("tool")
        if not (server and name):
            return None
        if isinstance(inp.get("arguments"), dict):
            args = inp["arguments"]
        elif "arguments" not in inp and "args" not in inp:
            args = {}
        else:
            return f"other:leanproxy.{tool}", dict(inp)
        return f"mcp:{str(server).lower()}.{name}", dict(args)
    if tool in _LEANPROXY_META:
        return f"mcp:leanproxy.{tool}", inp
    if "__" in tool:
        server, _, name = tool.partition("__")
        server = server.lower()
        name = _HASH_SUFFIX_RE.sub("", name)
        if server and name:
            return f"mcp:{_SERVER_ALIASES.get(server, server)}.{name}", inp
    return None


def fs_list_input(path: Any, pattern: Any = None, glob: Any = None) -> dict:
    """Entrée canonique `fs.list` : `path`, `pattern` (regex de grep) et `glob` (filtre de fichiers).

    Le filtre de fichiers vit sous `glob` (str ou liste) pour que la politique le confronte
    aux motifs de fichiers secrets ; un `pattern` de grep n'est jamais un chemin.
    """
    out: dict = {"path": path or "."}
    if pattern:
        out["pattern"] = pattern
    if glob:
        out["glob"] = glob
    return out


def _server_label(server: str) -> str:
    return {"garmin": "Garmin", "intervals": "intervals.icu", "strava": "Strava"}.get(server, server)


def display_input(workspace: Any, tool: str, tool_input: dict) -> dict:
    """Copie d'affichage : chemins du workspace rendus relatifs (résumés courts pour l'athlète)."""
    inp = dict(tool_input or {})
    raw = inp.get("path")
    if tool.startswith("fs.") and raw and workspace is not None:
        try:
            from pathlib import Path
            p = Path(str(raw))
            if p.is_absolute():
                inp["path"] = p.resolve().relative_to(Path(workspace).resolve()).as_posix()
        except (ValueError, OSError):
            pass
    return inp


def summarize_tool(tool: str, tool_input: dict) -> str:
    """Résumé français d'un appel d'outil canonique (pas de valeurs de santé)."""
    inp = tool_input or {}
    if tool == "fs.read":
        return f"Lecture de {short(inp.get('path'))}"
    if tool == "fs.write":
        return f"Écriture de {short(inp.get('path'))}"
    if tool == "fs.list":
        extra = inp.get("glob")
        if isinstance(extra, list):
            extra = ", ".join(str(g) for g in extra)
        return f"Recherche dans {short(inp.get('path') or '.')}" + (f" ({short(extra, 40)})" if extra else "")
    if tool == "shell":
        command = str(inp.get("command") or "")
        # `echo '<json>' | script` / `script << 'EOF' …` : montrer le script, pas le JSON.
        piped = re.match(r"^echo\s+'[^']*'\s*\|\s*(.+)$", command, re.S) or \
            re.match(r"^([^\n<]+?)\s*<<\s*'?\w+'?\s*\n", command)
        if piped:
            return f"Commande : {short(piped.group(1).strip(), 60)} (données en entrée)"
        return f"Commande : {short(command, 60)}"
    if tool == "web.fetch":
        return f"Consultation de {short(inp.get('url'), 60)}"
    if tool == "web.search":
        return f"Recherche web : {short(inp.get('query'), 60)}"
    if tool == "task":
        return f"Délégation à l'agent {short(inp.get('agent') or '?')}"
    if tool == "skill":
        return f"Chargement de la compétence {short(inp.get('name') or '?')}"
    if tool.startswith("mcp:"):
        server, _, name = tool[4:].partition(".")
        return f"{_server_label(server)} : {name}"
    return f"Outil {short(tool)}"


def approval_diff(tool: str, tool_input: dict) -> list:
    """Diff lisible pour la carte d'approbation : [{"op": "+"|"-"|" ", "text": str}]."""
    inp = tool_input or {}
    out: list = []
    if tool == "fs.write":
        old, new = inp.get("old_string") or inp.get("oldString"), inp.get("new_string") or inp.get("newString")
        if old or new:
            out += [{"op": "-", "text": line} for line in str(old or "").splitlines()]
            out += [{"op": "+", "text": line} for line in str(new or "").splitlines()]
        elif inp.get("content") is not None:
            out += [{"op": "+", "text": line} for line in str(inp["content"]).splitlines()]
        else:
            out.append({"op": " ", "text": short(inp.get("path"))})
    else:
        try:
            dumped = json.dumps(inp, ensure_ascii=False, indent=2, sort_keys=True)
        except (TypeError, ValueError):
            dumped = str(inp)
        out += [{"op": "+", "text": line} for line in dumped.splitlines()]
    if len(out) > MAX_DIFF_LINES:
        rest = len(out) - MAX_DIFF_LINES
        out = out[:MAX_DIFF_LINES] + [{"op": " ", "text": f"… ({rest} lignes de plus)"}]
    return out


def parse_unified_diff(diff_text: str) -> list:
    """Convertit un diff unifié (OpenCode `metadata.diff`) en lignes d'approbation."""
    out: list = []
    for line in (diff_text or "").splitlines():
        if line.startswith(("Index:", "====", "---", "+++", "@@")):
            continue
        if line[:1] in ("+", "-"):
            out.append({"op": line[0], "text": line[1:]})
        elif line.startswith(" "):
            out.append({"op": " ", "text": line[1:]})
    if len(out) > MAX_DIFF_LINES:
        rest = len(out) - MAX_DIFF_LINES
        out = out[:MAX_DIFF_LINES] + [{"op": " ", "text": f"… ({rest} lignes de plus)"}]
    return out


def gate(ctx: Any, tool: str, tool_input: dict, diff: Any = None) -> tuple:
    """Politique puis approbation : renvoie (« allow » | « deny » | « pending », texte de refus).

    Implémentation unique pour les deux backends : `ctx.decide` d'abord ; sur
    « ask », `ctx.request_approval` (bloquant). Toute réponse inattendue vaut refus.
    """
    decision = ctx.decide(tool, tool_input)
    if decision == "allow":
        return "allow", ""
    if decision != "ask":
        return "deny", REFUSAL_DENY
    result = ctx.request_approval(tool, tool_input, summarize_tool(tool, tool_input),
                                  diff if diff is not None else approval_diff(tool, tool_input))
    if result == "allow":
        return "allow", ""
    if result == "pending":
        return "pending", REFUSAL_PENDING
    return "deny", REFUSAL_DENY
