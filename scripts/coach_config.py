#!/usr/bin/env python3
"""Lecture/écriture sûre des fichiers de configuration d'ai-running-coach.

Écrire du JSON ou du TOML depuis bash conduit invariablement à remplacer un
fichier entier là où il fallait fusionner une clé. Les configurations MCP
touchées par `install.sh` sont pour certaines **globales et partagées**
(`~/.config/opencode/opencode.json`, `~/.claude.json`) : les réécrire détruit
les serveurs que l'utilisateur y a mis pour d'autres projets.

Ce module ne dépend que de la bibliothèque standard (voir CONTRIBUTING.md).

Sous-commandes :
    merge-json          insère une clé dans un fichier JSON, en préservant le reste
    approve-claude-mcp  pré-approuve un serveur MCP de projet dans ~/.claude.json
    get                 lit une clé TOML (user.toml > workspace.toml > défaut)
    set                 écrit une clé dans workspace.user.toml sans toucher au reste
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path


class ConfigError(RuntimeError):
    """Erreur attendue : message lisible, pas de trace."""


def read_json(path: Path) -> dict:
    """Charge un JSON existant, ou {} s'il n'existe pas / est vide.

    Un fichier illisible ou malformé lève : mieux vaut interrompre
    l'installation que réécrire par-dessus l'état global de l'utilisateur.
    """
    if not path.exists():
        return {}
    try:
        raw = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise ConfigError(f"{path} n'est pas de l'UTF-8 valide : {exc}") from exc
    except OSError as exc:
        raise ConfigError(f"{path} illisible : {exc}") from exc
    if not raw.strip():
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ConfigError(
            f"{path} contient du JSON invalide (ligne {exc.lineno}, colonne {exc.colno}) : "
            f"{exc.msg}.\n"
            f"Ce fichier n'a PAS été modifié. Corrigez-le ou mettez-le de côté, puis relancez."
        ) from exc
    if not isinstance(data, dict):
        raise ConfigError(f"{path} : objet JSON attendu, {type(data).__name__} trouvé.")
    return data


def write_json(path: Path, data: dict, backup: bool = True) -> None:
    """Écrit atomiquement, après sauvegarde de l'original."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if backup and path.exists():
        shutil.copy2(path, path.with_suffix(path.suffix + ".bak"))
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".arc-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


# ---------------------------------------------------------------------------
# TOML
# ---------------------------------------------------------------------------
# Le projet n'écrit qu'un sous-ensemble plat : sections, chaînes, booléens,
# entiers, tableaux de chaînes. Plutôt qu'une dépendance, une écriture qui
# PRÉSERVE le fichier ligne à ligne — commentaires, ordre et espacement compris.
# C'est ce que `setup-ntfy.sh` faisait à coups d'awk, avec les dégâts connus.

SECTION_RE = re.compile(r"^\s*\[([^\]]+)\]\s*$")
KEY_RE = re.compile(r"^\s*([A-Za-z0-9_.-]+)\s*=")


def toml_encode(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, list):
        return "[" + ", ".join(toml_encode(v) for v in value) + "]"
    escaped = str(value).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def read_toml(path: Path) -> dict:
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8")
    try:
        import tomllib

        return tomllib.loads(text)
    except ImportError:
        pass
    except Exception as exc:                       # tomllib.TOMLDecodeError
        raise ConfigError(f"{path} : TOML invalide — {exc}") from exc
    return _read_toml_fallback(text)


def _read_toml_fallback(text: str) -> dict:
    """Repli pour Python < 3.11 : même sous-ensemble plat que l'écriture."""
    data, section, pending_key, buffer = {}, None, None, ""
    for raw in text.splitlines():
        line = strip_toml_comment(raw).strip()
        if pending_key is not None:
            buffer += " " + line
            if "]" not in line:
                continue
            data[section][pending_key] = _parse_scalar(buffer)
            pending_key, buffer = None, ""
            continue
        if not line:
            continue
        match = SECTION_RE.match(line)
        if match:
            section = match.group(1)
            data.setdefault(section, {})
            continue
        if section is None or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if value.startswith("[") and "]" not in value:
            pending_key, buffer = key, value
            continue
        data[section][key] = _parse_scalar(value)
    return data


def _parse_scalar(value: str):
    value = value.strip()
    if value.startswith("[") and value.endswith("]"):
        inner = value[1:-1].strip()
        return [v.strip().strip('"') for v in inner.split(",") if v.strip()] if inner else []
    if value in ("true", "false"):
        return value == "true"
    if re.fullmatch(r"-?\d+", value):
        return int(value)
    return value.strip('"')


def strip_toml_comment(line: str) -> str:
    """Retire un commentaire de fin de ligne sans toucher aux « # » entre guillemets."""
    out, in_string = [], False
    for char in line:
        if char == '"':
            in_string = not in_string
        elif char == "#" and not in_string:
            break
        out.append(char)
    return "".join(out)


def set_toml_key(path: Path, section: str, key: str, value) -> bool:
    """Insère ou remplace `section.key`. Rend True si le fichier a changé.

    Tout le reste du fichier est conservé tel quel : commentaires de
    l'utilisateur, ordre des clés, sections inconnues.
    """
    encoded = f"{key} = {toml_encode(value)}"
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []

    section_start = section_end = None
    for index, line in enumerate(lines):
        match = SECTION_RE.match(line)
        if not match:
            continue
        if match.group(1) == section:
            section_start = index
        elif section_start is not None and section_end is None:
            section_end = index
    if section_start is not None and section_end is None:
        section_end = len(lines)

    if section_start is None:                       # section absente : on l'ajoute
        block = ([""] if lines and lines[-1].strip() else []) + [f"[{section}]", encoded]
        new_lines = lines + block
    else:
        index, replaced = section_start + 1, False
        while index < section_end:
            key_match = KEY_RE.match(strip_toml_comment(lines[index]))
            if key_match and key_match.group(1) == key:
                end = index
                # Un tableau peut courir sur plusieurs lignes.
                if "[" in lines[index] and "]" not in strip_toml_comment(lines[index]):
                    while end + 1 < section_end and "]" not in strip_toml_comment(lines[end]):
                        end += 1
                lines[index : end + 1] = [encoded]
                replaced = True
                break
            index += 1
        if not replaced:
            insert_at = section_end
            while insert_at > section_start + 1 and not lines[insert_at - 1].strip():
                insert_at -= 1
            lines.insert(insert_at, encoded)
        new_lines = lines

    content = "\n".join(new_lines).rstrip("\n") + "\n"
    if path.exists() and path.read_text(encoding="utf-8") == content:
        return False

    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        shutil.copy2(path, path.with_suffix(path.suffix + ".bak"))
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".arc-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(content)
        os.chmod(tmp, 0o644)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return True


def config_paths(workspace: Path) -> tuple:
    return workspace / "config/workspace.user.toml", workspace / "config/workspace.toml"


def cmd_get(args) -> int:
    user, shared = config_paths(Path(args.workspace))
    for path in (user, shared):
        section = read_toml(path).get(args.section, {})
        if args.key in section:
            value = section[args.key]
            print("\n".join(str(v) for v in value) if isinstance(value, list) else _render(value))
            return 0
    if args.default is None:
        return 1
    print(args.default)
    return 0


def _render(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def cmd_set(args) -> int:
    user, _ = config_paths(Path(args.workspace))
    if args.list is not None:
        value = args.list
    elif args.type == "bool":
        value = args.value.lower() in ("1", "true", "oui", "yes")
    elif args.type == "int":
        value = int(args.value)
    else:
        value = args.value
    changed = set_toml_key(user, args.section, args.key, value)
    print(f"{'écrit' if changed else 'inchangé'}: [{args.section}].{args.key} dans {user}")
    return 0


def cmd_merge_json(args) -> int:
    path = Path(args.file)
    data = read_json(path)

    if args.template and not data:
        data = json.loads(args.template)

    container = data
    for part in args.section.split(".") if args.section else []:
        nxt = container.get(part)
        if nxt is None:
            nxt = {}
            container[part] = nxt
        elif not isinstance(nxt, dict):
            raise ConfigError(f"{path} : « {args.section} » n'est pas un objet JSON.")
        container = nxt

    value = json.loads(args.value)
    if container.get(args.name) == value:
        print(f"inchangé: {path} ({args.name})")
        return 0

    container[args.name] = value
    write_json(path, data)
    print(f"fusionné: {args.name} dans {path}")
    return 0


def cmd_approve_claude_mcp(args) -> int:
    """Pré-approuve le serveur MCP du projet dans ~/.claude.json.

    Sans cela, Claude Code laisse le serveur « Pending approval » jusqu'à une
    session interactive — bloquant sur une machine coach sans écran.
    """
    store = Path(args.store)
    data = read_json(store)

    project = data.setdefault("projects", {}).setdefault(args.project, {})
    enabled = project.setdefault("enabledMcpjsonServers", [])
    changed = False
    if args.server not in enabled:
        enabled.append(args.server)
        changed = True
    # `hasTrustDialogAccepted` répond à la place de l'utilisateur à une invite de
    # sécurité : on ne le pose que si l'appelant l'a explicitement demandé, et on
    # le signale.
    if args.trust and not project.get("hasTrustDialogAccepted"):
        project["hasTrustDialogAccepted"] = True
        changed = True
        print(f"note: dossier {args.project} marqué comme approuvé (hasTrustDialogAccepted)")

    if not changed:
        print(f"inchangé: {store}")
        return 0
    write_json(store, data)
    print(f"approuvé: serveur MCP {args.server} pour {args.project}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="coach_config.py", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    merge = sub.add_parser("merge-json", help="insère une clé dans un fichier JSON")
    merge.add_argument("--file", required=True)
    merge.add_argument("--section", default="", help="chemin pointé, ex. « mcpServers » ou « a.b »")
    merge.add_argument("--name", required=True, help="clé à insérer dans la section")
    merge.add_argument("--value", required=True, help="valeur JSON")
    merge.add_argument("--template", default="", help="contenu JSON initial si le fichier est absent")
    merge.set_defaults(func=cmd_merge_json)

    approve = sub.add_parser("approve-claude-mcp", help="pré-approuve un serveur MCP de projet")
    approve.add_argument("--store", required=True)
    approve.add_argument("--project", required=True)
    approve.add_argument("--server", required=True)
    approve.add_argument("--trust", action="store_true", help="accepte aussi le dialogue de confiance")
    approve.set_defaults(func=cmd_approve_claude_mcp)

    get = sub.add_parser("get", help="lit une clé TOML avec la précédence du projet")
    get.add_argument("--workspace", default=".")
    get.add_argument("--section", required=True)
    get.add_argument("--key", required=True)
    get.add_argument("--default", default=None)
    get.set_defaults(func=cmd_get)

    setter = sub.add_parser("set", help="écrit une clé dans workspace.user.toml")
    setter.add_argument("--workspace", default=".")
    setter.add_argument("--section", required=True)
    setter.add_argument("--key", required=True)
    setter.add_argument("--value", default="")
    setter.add_argument("--list", action="append", help="répéter pour un tableau de chaînes")
    setter.add_argument("--type", choices=("string", "bool", "int"), default="string")
    setter.set_defaults(func=cmd_set)

    return parser


def main(argv: list | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except ConfigError as exc:
        print(f"coach_config: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
