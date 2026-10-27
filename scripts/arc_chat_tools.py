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
# Refus d'une commande shell PAR LA POLITIQUE : le shell n'accepte que les scripts du coach, mais
# lister, lire ou tester l'existence d'un fichier reste permis avec les outils fichiers. « Ne la
# réessaie pas » seul faisait abandonner toute la tâche (un /log entier perdu sur un `ls`).
REFUSAL_SHELL = ("Refusé : le shell n'accepte que les scripts du coach (python3 scripts/…, "
                 "une commande par appel, sans redirection ni tube). Ne réessaie pas cette commande, "
                 "mais poursuis la tâche : pour lister, lire ou vérifier qu'un fichier existe, "
                 "utilise les outils fichiers (glob, read, list) ; pour écrire, l'outil d'écriture.")
REFUSAL_PENDING ="La proposition attend la confirmation de l'athlète."

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
    return {"garmin": "Garmin", "intervals": "intervals.icu", "strava": "Strava", "coros": "COROS"}.get(server, server)


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


# ---------------------------------------------------------------------------
# Catalogue Garmin de la session : ce que les lectures ont montré au modèle
# ---------------------------------------------------------------------------
# Une carte d'approbation qui ne montre que `{"scheduled_workout_ids": [1783059687, …]}`
# ne laisse rien à vérifier. Le service retient donc, depuis les RÉSULTATS des outils
# Garmin lus pendant la conversation (`get_scheduled_workouts`, `get_workouts`,
# `upload_workout`…), à quoi correspond chaque identifiant, et la carte l'affiche.
# Jamais la parole du modèle : seulement ce que Garmin a renvoyé. Un identifiant
# jamais vu est signalé comme tel, pas deviné.

CATALOG_KEY = "garmin_catalog"
MAX_CATALOG = 400
_WEEKDAYS = ("lun.", "mar.", "mer.", "jeu.", "ven.", "sam.", "dim.")


def result_text(content: Any) -> str:
    """Texte d'un résultat d'outil (chaîne, ou liste de blocs `{"type": "text", "text": …}`)."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict):
                parts.append(str(block.get("text") or ""))
            elif getattr(block, "text", None):
                parts.append(str(block.text))
            elif isinstance(block, str):
                parts.append(block)
        return "\n".join(parts)
    return str(content)


def _loads(text: Any) -> Any:
    """JSON d'un résultat, y compris doublement encodé (passerelle) ; None sinon."""
    value = text
    for _ in range(3):
        if not isinstance(value, str):
            return value
        raw = value.strip()
        if not raw or raw[0] not in "[{\"":
            start = min((i for i in (raw.find("{"), raw.find("[")) if i >= 0), default=-1)
            if start < 0:
                return None
            raw = raw[start:]
        try:
            value = json.loads(raw)
        except (TypeError, ValueError):
            return None
    return value if not isinstance(value, str) else None


def _walk(node: Any):
    if isinstance(node, dict):
        yield node
        for v in node.values():
            yield from _walk(v)
    elif isinstance(node, list):
        for v in node:
            yield from _walk(v)


def _put(table: dict, key: Any, entry: dict) -> None:
    if key is None or isinstance(key, bool):
        return
    clean = {k: v for k, v in entry.items() if v not in (None, "")}
    if not clean:
        return
    k = str(key)
    merged = dict(table.pop(k, {}), **clean)       # ré-insertion : la plus récente en dernier
    table[k] = merged
    while len(table) > MAX_CATALOG:
        table.pop(next(iter(table)))


def remember_result(state: Optional[dict], tool: str, output: Any) -> None:
    """Retient, depuis le résultat d'un outil Garmin, le nom/la date des séances qu'il cite."""
    if state is None or not tool.startswith("mcp:garmin."):
        return
    data = _loads(result_text(output))
    if data is None:
        return
    name = tool.split(".", 1)[1]
    catalog = state.setdefault(CATALOG_KEY, {})
    scheduled = catalog.setdefault("scheduled", {})
    workouts = catalog.setdefault("workouts", {})
    library = name in ("get_workouts", "get_workout_by_id")
    for d in _walk(data):
        title = d.get("name") or d.get("workout_name") or d.get("workoutName")
        sport = d.get("sport") or d.get("workoutType")
        wid = d.get("workout_id", d.get("workoutId"))
        if library and wid is None:
            wid = d.get("id")
        if "scheduled_workout_id" in d or "scheduledWorkoutId" in d:
            _put(scheduled, d.get("scheduled_workout_id", d.get("scheduledWorkoutId")),
                 {"date": d.get("date") or d.get("scheduleDate"), "name": title, "sport": sport,
                  "workout_id": wid})
        if wid is not None and (title or sport):
            _put(workouts, wid, {"name": title, "sport": sport})


def _day(value: Any) -> str:
    """« lun. 13/10 » pour une date ISO ; la valeur brute sinon."""
    from datetime import date
    try:
        d = date.fromisoformat(str(value)[:10])
    except ValueError:
        return short(value, 20)
    return f"{_WEEKDAYS[d.weekday()]} {d.day:02d}/{d.month:02d}"


def _ids(value: Any) -> list:
    if isinstance(value, (list, tuple)):
        return list(value)
    return [] if value is None else [value]


def _garmin_lines(name: str, inp: dict, catalog: dict) -> Optional[tuple]:
    """(résumé, lignes, nb d'identifiants inconnus) pour les écritures Garmin connues ; None sinon."""
    scheduled = catalog.get("scheduled") or {}
    workouts = catalog.get("workouts") or {}

    def workout_label(wid: Any, inline: Optional[dict] = None) -> tuple:
        if isinstance(inline, dict):
            title = inline.get("workoutName") or inline.get("name")
            return (f"{short(title)} (nouvelle séance)" if title else "nouvelle séance sans nom"), True
        info = workouts.get(str(wid))
        if info and info.get("name"):
            return short(info["name"]), True
        return f"séance {wid} — non identifiée dans cette conversation", False

    lines: list = []
    unknown = 0
    if name in ("unschedule_workout", "unschedule_workouts"):
        ids = _ids(inp.get("scheduled_workout_ids", inp.get("scheduled_workout_id")))
        for sid in ids:
            info = scheduled.get(str(sid))
            if info:
                title = info.get("name") or workout_label(info.get("workout_id"))[0]
                lines.append({"op": "-", "text": f"{_day(info.get('date'))} · {short(title)}"})
            else:
                unknown += 1
                lines.append({"op": "-", "text": f"entrée de calendrier {sid} — non identifiée "
                                                 "dans cette conversation"})
        n = len(ids)
        summary = f"Garmin : retirer {n} séance{'s' if n > 1 else ''} du calendrier"
    elif name in ("delete_workout", "delete_workouts"):
        ids = _ids(inp.get("workout_ids", inp.get("workout_id")))
        for wid in ids:
            label, known = workout_label(wid)
            unknown += not known
            lines.append({"op": "-", "text": label})
        n = len(ids)
        summary = f"Garmin : supprimer définitivement {n} séance{'s' if n > 1 else ''} de la bibliothèque"
    elif name in ("schedule_workout", "schedule_workouts", "schedule_week"):
        if name == "schedule_workout":
            items = [{"workout_id": inp.get("workout_id"), "calendar_date": inp.get("calendar_date")}]
        else:
            items = [i for i in _ids(inp.get("schedules", inp.get("week"))) if isinstance(i, dict)]
        for item in sorted(items, key=lambda i: str(i.get("calendar_date") or i.get("date") or "")):
            label, known = workout_label(item.get("workout_id"), item.get("workout_data"))
            unknown += not known
            when = _day(item.get("calendar_date") or item.get("date"))
            lines.append({"op": "+", "text": f"{when} · {label}"})
        n = len(items)
        summary = f"Garmin : ajouter {n} séance{'s' if n > 1 else ''} au calendrier"
    else:
        return None
    if not lines:
        return None
    return summary, lines, unknown


def approval_summary(tool: str, tool_input: dict, catalog: Optional[dict] = None) -> str:
    """Titre de la carte d'approbation : ce qui va changer, pas le nom technique de l'outil."""
    if tool.startswith("mcp:garmin."):
        found = _garmin_lines(tool.split(".", 1)[1], tool_input or {}, catalog or {})
        if found:
            summary, _, unknown = found
            if unknown:
                summary += f" ({unknown} non identifiée{'s' if unknown > 1 else ''})"
            return summary
    return summarize_tool(tool, tool_input)


def approval_diff(tool: str, tool_input: dict, catalog: Optional[dict] = None) -> list:
    """Diff lisible pour la carte d'approbation : [{"op": "+"|"-"|" ", "text": str}]."""
    inp = tool_input or {}
    out: list = []
    found = _garmin_lines(tool.split(".", 1)[1], inp, catalog or {}) if tool.startswith("mcp:garmin.") else None
    if found:
        out = list(found[1])
        if found[2]:
            out.append({"op": " ", "text": "⚠ Identifiant(s) jamais lu(s) chez Garmin dans cette conversation : "
                                           "demande au coach de relire le calendrier avant d'accepter."})
    elif tool == "fs.write":
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
        return "deny", REFUSAL_SHELL if tool == "shell" else REFUSAL_DENY
    catalog = (getattr(ctx, "backend_state", None) or {}).get(CATALOG_KEY)
    result = ctx.request_approval(tool, tool_input, approval_summary(tool, tool_input, catalog),
                                  diff if diff is not None else approval_diff(tool, tool_input, catalog))
    if result == "allow":
        return "allow", ""
    if result == "pending":
        return "pending", REFUSAL_PENDING
    return "deny", REFUSAL_DENY
