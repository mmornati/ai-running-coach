#!/usr/bin/env python3
"""Politique de permissions du chat coach : « allow », « ask » ou « deny ».

Une seule politique pour tous les backends (deploy/chat/SPEC.md, « Policy »).
Les noms d'outils sont canoniques (`scripts/arc_chat_backend.py`) ; les règles
viennent de `config/chat-policy.toml` (versionné, sans secret). Ce qui n'est
pas explicitement permis est refusé.

    Policy.load(racine_ou_fichier, workspace).decide("fs.write", {"path": "planning/x.md"})

Bibliothèque standard uniquement (CONTRIBUTING.md).
"""

from __future__ import annotations

import fnmatch
import os
import re
import shlex
import sys
from pathlib import Path
from typing import Iterable, Optional
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))
from arc_chat_backend import payload_hash, resolve_workspace_path  # noqa: E402

ENGINE_ROOT = Path(__file__).resolve().parent.parent
from coach_config import read_toml  # noqa: E402

POLICY_FILE = "config/chat-policy.toml"

# Métacaractères shell interdits dans une commande autorisée : redirections, chaînage,
# substitutions, échappement (`\` ferait diverger shlex et le vrai shell), `~` (expansion
# du répertoire personnel), jokers et accolades (un joker contournerait la liste des secrets).
SHELL_META = set(";|&$`><()\n\r\\~*?[]{}!")
# `echo "---"` entre deux commandes chaînées : littéral sans expansion possible.
ECHO_LITERAL_RE = re.compile(r"""^echo(?:[ \t]+(?:"[^"$`\\!]*"|'[^']*'|[A-Za-z0-9_.:=+,/-]+))*$""")
# `#` ne commence un commentaire qu'en début de mot : refusé là seulement (`fichier.md#mardi` passe).
COMMENT_RE = re.compile(r"(^|\s)#")
# Entrée standard des scripts qui lisent du JSON (`[shell].stdin_scripts`, ex. arc_log.py) : deux
# formes seulement, sans aucune expansion possible par le shell — une chaîne entre apostrophes
# (rien n'est interprété entre ' ') ou un heredoc à délimiteur entre apostrophes (`<< 'EOF'`).
STDIN_ECHO_RE = re.compile(r"^echo[ \t]+'(?P<body>[^']*)'[ \t]*\|[ \t]*(?P<cmd>[^\n\r]+)$")
STDIN_HEREDOC_RE = re.compile(
    r"^(?P<cmd>[^\n\r<]+?)[ \t]*<<[ \t]*'(?P<tag>[A-Za-z_][A-Za-z0-9_]*)'[ \t]*\n(?P<body>.*?)\n(?P=tag)[ \t]*\n?$",
    re.S)

# Un argument qui se termine ainsi est traité comme un chemin même sans « / ».
PATH_SUFFIXES = (".md", ".json", ".jsonl", ".toml", ".db", ".sqlite", ".gpx", ".fit", ".csv", ".txt",
                 ".yml", ".yaml", ".env", ".token", ".pem", ".key", ".py", ".sh")

# Options toujours permises (sans valeur) pour tout script de la liste blanche.
COMMON_FLAGS = ("--help", "-h")

# Borne de l'expansion réelle d'un joker (fs.list) : au-delà, on refuse.
GLOB_SCAN_LIMIT = 20000

WILDCARDS = "*?["

# Bornes de l'expansion d'accolades d'un glob (fs.list) : au-delà, refus (jamais de troncature).
BRACE_MAX_EXPANSION = 64
BRACE_MAX_DEPTH = 3

# Valeurs de repli si le fichier est absent ou incomplet : elles reproduisent
# `config/chat-policy.toml` (le refus reste le comportement par défaut).
DEFAULTS = {
    "fs": {
        "write_dirs": ["activities", "medical", "nutrition", "planning", "rapports", "gear"],
        "secret_patterns": [".env", "*.env", "*.token", ".garminconnect",
                            "llm.env", "*.pem", "*.key"],
        # Dossiers où une recherche de contenu (grep, `pattern`) est permise, en plus de write_dirs.
        "search_dirs": ["resources", "skills", "agents", "templates", "docs"],
    },
    "shell": {"allowed_prefixes": ["python3 scripts/arc_index.py", "python3 scripts/arc_log.py",
                                   "python3 scripts/garmin_gear_backfill.py", "python3 scripts/arc_guardrails.py",
                                   "python3 scripts/arc_workout_targets.py", "python3 scripts/arc_race_debrief.py",
                                   "python3 scripts/coach_doctor.py",
                                   "python3 skills/session-parts-analyzer/scripts/analyze_session_parts.py"],
              "stdin_scripts": ["scripts/arc_log.py"]},
    "web": {"fetch_domains": ["wttr.in", "overpass-api.de", "nominatim.openstreetmap.org"]},
    "mcp": {
        "servers": ["garmin", "intervals", "strava"],
        "read_prefixes": ["get_", "count_", "list_", "download_", "get-", "list-", "check-", "explore-"],
        "write_tools": ["schedule_*", "delete_*", "upload_*", "create_*", "add_*", "set_*", "log_*",
                        "update_*", "remove_*", "request_reload",
                        "connect-strava", "disconnect-strava", "star-segment"],
    },
}

# Options des scripts de repli (aucun fichier de politique) : les deux premiers scripts seulement.
DEFAULT_SCRIPTS = {
    "scripts/arc_index.py": {
        "flags": ["--memory", "--rebuild", "--with-gps", "--assumptions", "--calibration", "--active"],
        "value_options": ["--today", "--activity", "--weeks", "--segment", "--date", "--days", "--since",
                          "--limit", "--trigger", "--outcome", "--months", "--band", "--last-pass",
                          "--activities", "--garmin-gear", "--chat-gear", "--kit", "--sport", "--gear"],
        "optional_value_options": ["--race-plan"],
        "read_options": ["--validate", "--race-plan"],
        "multi_value_options": ["--validate"],
        "output_options": ["--db"],
    },
    "scripts/arc_log.py": {
        "read_options": ["--input"],
        "output_options": ["--output"],
    },
    "scripts/arc_guardrails.py": {
        "flags": ["--memory"], "value_options": ["--week-start", "--today"],
        "read_options": ["--week"], "output_options": ["--db"],
    },
    "scripts/arc_workout_targets.py": {
        "flags": ["--memory"], "value_options": ["--structure-text", "--band", "--today"],
        "read_options": ["--session"], "output_options": ["--db"],
    },
    "scripts/arc_race_debrief.py": {
        "value_options": ["--scenario", "--carbs-target-g-h", "--carbs-actual-g-h", "--carbs-ceiling-g-h"],
        "read_options": ["--plan", "--activity", "--planned-weather", "--actual-weather", "--fit"],
    },
    "scripts/coach_doctor.py": {
        "flags": ["--json", "--probe-mcp"], "value_options": ["--check", "--now"],
    },
    "skills/session-parts-analyzer/scripts/analyze_session_parts.py": {
        "flags": ["--quiet"],
        "value_options": ["--activity-id", "--part", "--smooth-window", "--stride-threshold", "--recovery-threshold"],
        "read_options": ["--fit", "--activity-json"], "output_options": ["--output", "--json"],
    },
    "scripts/garmin_gear_backfill.py": {
        "flags": ["--all-shoes", "--json"],
        "value_options": ["--since", "--gear"],
        "ask_flags": ["--apply"],
    },
}


def _as_list(value) -> list:
    if isinstance(value, str):
        return [value]
    return [str(v) for v in value] if isinstance(value, (list, tuple)) else []


def _script_rules(rules: dict) -> dict:
    """Options permises par script : `[shell.scripts."scripts/x.py"]` → {script: {clé: [options]}}.

    Deux formes selon le lecteur TOML : tableaux imbriqués (tomllib) ou nom de section
    complet en clé (repli Python < 3.11, qui n'imbrique pas).
    """
    found: dict = {}
    shell = rules.get("shell")
    nested = shell.get("scripts") if isinstance(shell, dict) else None
    if isinstance(nested, dict):
        for script, table in nested.items():
            if isinstance(table, dict):
                found[str(script)] = {k: _as_list(v) for k, v in table.items()}
    for key, table in rules.items():
        match = re.match(r'^shell\.scripts\.["\']?(.+?)["\']?$', str(key))
        if match and isinstance(table, dict):
            found[match.group(1)] = {k: _as_list(v) for k, v in table.items()}
    return found


def _has_wildcard(text: str) -> bool:
    return any(ch in text for ch in WILDCARDS)


class Policy:
    """Règles chargées ; `decide` est pur (aucun effet de bord, thread-safe)."""

    def __init__(self, workspace: Path, rules: Optional[dict] = None, engine: Optional[Path] = None):
        self.workspace = Path(workspace).resolve()
        # Le moteur (ce dépôt) : `install.sh` relie AGENTS.md, config/workspace.toml, agents/,
        # skills/ et scripts/ du workspace vers lui. Lecture seule, jamais d'écriture.
        self.engine = Path(engine).resolve() if engine else ENGINE_ROOT
        merged = {section: dict(values) for section, values in DEFAULTS.items()}
        for section, values in (rules or {}).items():
            if isinstance(values, dict):
                merged.setdefault(section, {}).update(values)
        self.write_dirs = _as_list(merged["fs"].get("write_dirs"))
        self.secret_patterns = _as_list(merged["fs"].get("secret_patterns"))
        self.search_dirs = _as_list(merged["fs"].get("search_dirs")) + list(self.write_dirs)
        self.shell_prefixes = _as_list(merged["shell"].get("allowed_prefixes"))
        self.stdin_scripts = _as_list(merged["shell"].get("stdin_scripts"))
        self.shell_scripts = _script_rules(rules or {}) or {k: dict(v) for k, v in DEFAULT_SCRIPTS.items()}
        self.fetch_domains = [d.lower() for d in _as_list(merged["web"].get("fetch_domains"))]
        self.mcp_servers = [s.lower() for s in _as_list(merged["mcp"].get("servers"))]
        self.mcp_read_prefixes = _as_list(merged["mcp"].get("read_prefixes"))
        self.mcp_write_tools = _as_list(merged["mcp"].get("write_tools"))

    @classmethod
    def load(cls, repo_root_or_path, workspace) -> "Policy":
        """`repo_root_or_path` : racine du dépôt (on lit `config/chat-policy.toml`) ou fichier TOML.

        Sans fichier à cet endroit, celui du workspace est tenté, puis les défauts ci-dessus.
        """
        given = Path(repo_root_or_path)
        first = given if given.is_file() else given / POLICY_FILE
        for path in (first, Path(workspace) / POLICY_FILE):
            if path.is_file():
                return cls(Path(workspace), read_toml(path))
        return cls(Path(workspace), {})

    # -- décisions -----------------------------------------------------------

    def decide(self, tool: str, tool_input: dict, preapproved: Iterable[str] = ()) -> str:
        """« allow » | « ask » | « deny ». Un hash pré-approuvé ne lève que « ask », jamais « deny »."""
        tool_input = tool_input if isinstance(tool_input, dict) else {}
        verdict = self._base(tool, tool_input)
        if verdict == "ask" and preapproved and payload_hash(tool, tool_input) in set(preapproved):
            return "allow"
        return verdict

    def _base(self, tool: str, tool_input: dict) -> str:
        if tool == "fs.read":
            return self._fs_read(tool_input)
        if tool == "fs.list":
            return self._fs_list(tool_input)
        if tool == "fs.write":
            return self._fs_write(tool_input)
        if tool == "shell":
            return self._shell(str(tool_input.get("command") or ""))
        if tool == "web.fetch":
            return self._web_fetch(str(tool_input.get("url") or ""))
        if tool in ("task", "skill"):
            return "allow"
        if tool.startswith("mcp:"):
            return self._mcp(tool)
        return "deny"           # web.search, other:*, inconnu

    def _secret(self, rel: str) -> bool:
        # Comparaison insensible à la casse des deux côtés (macOS : `.ARC` et `.arc` sont le même dossier).
        parts = [p.casefold() for p in rel.split("/") if p]
        return any(fnmatch.fnmatchcase(part, pattern.casefold())
                   for part in parts for pattern in self.secret_patterns)

    @staticmethod
    def _in_arc(rel: str) -> bool:
        low = rel.casefold()
        return low == ".arc" or low.startswith(".arc/")

    def _locate(self, raw: str) -> Optional[str]:
        """Chemin LISIBLE → son nom logique relatif au workspace, sinon None.

        Le chemin est pris tel qu'écrit (relatif au workspace, ou absolu sous le workspace ou
        sous le moteur) ; sa cible réelle doit rester dans le workspace ou dans le moteur — un
        lien du workspace vers le moteur (installation normale) est donc suivi, un lien vers
        ailleurs (~/.ssh…) jamais. Secrets et `.arc/` refusés sur le nom ET sur la cible.
        """
        raw = str(raw)
        if "\x00" in raw or raw.startswith("~"):
            return None
        path = Path(raw)
        if not path.is_absolute():
            path = self.workspace / path
        logical = Path(os.path.normpath(str(path)))
        try:
            real = logical.resolve()
        except (OSError, RuntimeError):
            return None
        names = []
        for root in (self.workspace, self.engine):
            try:
                names.append(logical.relative_to(root).as_posix())
                break
            except ValueError:
                continue
        if not names:
            return None                          # ni dans le workspace ni dans le moteur
        target = None
        for root in (self.workspace, self.engine):
            try:
                target = real.relative_to(root).as_posix()
                break
            except ValueError:
                continue
        if target is None:
            return None                          # lien qui sort vers ailleurs
        for name in (names[0], target):
            if name not in ("", ".") and (self._secret(name) or self._in_arc(name)):
                return None
        return names[0] if names[0] != "." else ""

    def _fs_read(self, tool_input: dict) -> str:
        raw = tool_input.get("path")
        if raw in (None, "", "."):
            return "allow"                       # racine du workspace (ls, glob)
        return "deny" if self._locate(str(raw)) is None else "allow"

    def _fs_write(self, tool_input: dict) -> str:
        # Patch multi-fichiers : CHAQUE cible doit passer (un seul refus refuse tout l'appel).
        extra = tool_input.get("paths")
        if extra is not None:
            if not isinstance(extra, list) or not extra:
                return "deny"
            for target in extra:
                if self._fs_write_one(str(target or "")) != "allow":
                    return "deny"
        return self._fs_write_one(str(tool_input.get("path") or ""))

    def _fs_write_one(self, raw: str) -> str:
        rel = resolve_workspace_path(self.workspace, raw)
        if rel is None or self._secret(rel) or "/" not in rel:
            return "deny"
        return "allow" if rel.split("/", 1)[0] in self.write_dirs else "deny"

    # -- fs.list : filtres de fichiers (glob) ----------------------------------------

    @staticmethod
    def _expand_braces(glob: str) -> Optional[list]:
        """`*.{md,toml}` → [`*.md`, `*.toml`] ; None si l'expansion dépasse la borne ou si
        l'imbrication dépasse le maximum : l'appelant refuse (jamais de troncature silencieuse)."""
        depth = level = 0
        for ch in glob:
            if ch == "{":
                level += 1
                depth = max(depth, level)
            elif ch == "}":
                level = max(0, level - 1)
        if depth > BRACE_MAX_DEPTH:
            return None
        out = [glob]
        while True:
            nxt: list = []
            changed = False
            for item in out:
                match = re.search(r"\{([^{}]*)\}", item)
                if not match:
                    nxt.append(item)
                    continue
                changed = True
                for alt in match.group(1).split(","):
                    nxt.append(item[:match.start()] + alt + item[match.end():])
                if len(nxt) > BRACE_MAX_EXPANSION:
                    return None
            out = nxt
            if len(out) > BRACE_MAX_EXPANSION:
                return None
            if not changed:
                return out

    def _component_may_match_secret(self, component: str) -> bool:
        """Un composant de glob peut-il désigner un secret ? Comparaison dans les deux sens."""
        if not component:
            return False
        comp = component.casefold()
        return any(fnmatch.fnmatchcase(pattern.casefold(), comp) or fnmatch.fnmatchcase(comp, pattern.casefold())
                   for pattern in self.secret_patterns)

    def _fs_list(self, tool_input: dict) -> str:
        """`path` comme fs.read, puis chaque valeur de `glob` (chaîne ou liste) ; `pattern` n'est pas un chemin."""
        if self._fs_read(tool_input) != "allow":
            return "deny"
        globs = tool_input.get("glob")
        globs = [globs] if isinstance(globs, str) else (list(globs) if isinstance(globs, (list, tuple)) else [])
        raw = tool_input.get("path")
        base = "" if raw in (None, "", ".") else (self._locate(str(raw)) or "")
        if tool_input.get("pattern") and not self._search_dir_ok(base):
            return "deny"                                   # grep : le contenu des fichiers serait lu
        for glob in globs:
            if not isinstance(glob, str) or not glob.strip():
                continue
            expanded = self._expand_braces(glob.strip())
            if expanded is None:
                return "deny"
            for one in expanded:
                if not self._glob_ok(base, one):
                    return "deny"
        return "allow"

    def _search_dir_ok(self, base: str) -> bool:
        """Une recherche de contenu ne porte que sur un dossier de `[fs].search_dirs` (ou un sous-dossier)."""
        first = base.split("/", 1)[0] if base else ""
        return bool(first) and first in self.search_dirs

    def _glob_ok(self, base: str, glob: str) -> bool:
        if glob.startswith(("/", "~")) or "\\" in glob or ".." in glob.split("/"):
            return False
        parts = [p for p in glob.split("/") if p and p != "."]
        if not parts:
            return True
        if any(not _has_wildcard(p) and (self._secret(p) or self._in_arc(p)) for p in parts):
            return False                                    # nom de secret (ou `.arc`) cité tel quel
        if any(self._component_may_match_secret(p) for p in parts[-1:]) or any(
                not set(p) <= {"*"} and self._component_may_match_secret(p) for p in parts[:-1]):
            # Joker large ou proche d'un secret : toléré seulement dans un dossier de données
            # littéral (jamais config/, jamais la racine, jamais récursif), après vérification réelle.
            literal = [p for p in base.split("/") if p]
            for part in parts[:-1]:
                if _has_wildcard(part):
                    break
                literal.append(part)
            if not literal or literal[0] not in self.write_dirs or "**" in parts:
                return False
        return not self._glob_hits_secret(base, parts)

    def _glob_hits_secret(self, base: str, parts: list) -> bool:
        """Développe le glob sur le disque (borné) : vrai si un fichier réel est un secret ou sous `.arc/`."""
        joined = "/".join(parts)
        if not _has_wildcard(joined):
            rel = (base + "/" + joined).lstrip("/")
            return self._secret(rel) or self._in_arc(rel)
        root = (self.workspace / base) if base else self.workspace
        seen = 0
        try:
            for match in root.glob(joined):
                seen += 1
                if seen > GLOB_SCAN_LIMIT:
                    return True                             # trop large pour être vérifié
                rel = os.path.relpath(match, self.workspace).replace(os.sep, "/")
                if self._secret(rel) or self._in_arc(rel):
                    return True
        except (OSError, ValueError, NotImplementedError):
            return True
        return False

    # -- shell : liste blanche par script et par option -------------------------------

    def _stdin_command(self, command: str) -> Optional[str]:
        """`echo '<json>' | cmd` ou `cmd << 'EOF' … EOF` → `cmd` si la forme est sûre, sinon None."""
        match = STDIN_ECHO_RE.match(command)
        if not match:
            match = STDIN_HEREDOC_RE.match(command)
            if not match:
                return None
            tag = match.group("tag")
            # Une ligne égale au délimiteur DANS le corps fermerait le heredoc plus tôt : la suite
            # serait exécutée comme des commandes. Refus.
            if any(line.strip() == tag for line in match.group("body").split("\n")):
                return None
        return self._normalize_command(match.group("cmd").strip())

    def _normalize_command(self, command: str) -> str:
        """Deux écritures inoffensives, très fréquentes chez les modèles, ramenées à la forme
        canonique AVANT tout contrôle :
        - `… 2>&1` en fin de commande : fusionne la sortie d'erreur dans la sortie standard,
          aucune écriture de fichier ;
        - chemin absolu d'un script du workspace (`python3 /…/ws/scripts/arc_log.py`) : même
          script que `python3 scripts/arc_log.py` (le chemin doit rester DANS le workspace).
        """
        command = re.sub(r"[ \t]+2>(?:&1|/dev/null)[ \t]*$", "", command)
        match = re.match(r"^(python3[ \t]+)(/\S+)(.*)$", command, re.S)
        if match:
            root = str(self.workspace) + os.sep
            script = os.path.normpath(match.group(2))
            if script.startswith(root):
                command = match.group(1) + script[len(root):] + match.group(3)
        return command

    def _chain(self, command: str) -> Optional[list]:
        """`a && b`, `a; echo "---"; b` → [a, echo, b] ; None si ce n'est pas une chaîne simple.

        Coupé seulement si aucun guillemet n'apparaît hors de segments `echo "<littéral>"` :
        les séparateurs ne peuvent donc pas être cachés dans une chaîne.
        """
        if "&&" not in command and ";" not in command:
            return None
        parts = [p.strip() for p in re.split(r"\s*(?:&&|;)\s*", command)]
        if len(parts) < 2 or any(not p for p in parts):
            return None
        for part in parts:
            if ("'" in part or '"' in part) and not ECHO_LITERAL_RE.match(part):
                return None
        return parts

    def _shell(self, command: str) -> str:
        command = self._normalize_command(command.strip())
        chain = self._chain(command)
        if chain is not None:
            # Chaque maillon doit passer seul ; le plus prudent l'emporte (deny > ask > allow).
            verdicts = ["allow" if ECHO_LITERAL_RE.match(p) else self._shell(p) for p in chain]
            return "deny" if "deny" in verdicts else "ask" if "ask" in verdicts else "allow"
        inner = self._stdin_command(command)
        if inner is not None:
            if any(ch in SHELL_META for ch in inner) or COMMENT_RE.search(inner):
                return "deny"
            try:
                words = shlex.split(inner)
            except ValueError:
                return "deny"
            script = next((p.split()[-1] for p in self.shell_prefixes
                           if p.split() and words[:len(p.split())] == p.split()), None)
            if script is None or script not in self.stdin_scripts:
                return "deny"
            return self._shell(inner)
        if not command or any(ch in SHELL_META for ch in command) or COMMENT_RE.search(command):
            return "deny"
        try:
            words = shlex.split(command)
        except ValueError:
            return "deny"
        for prefix in self.shell_prefixes:
            head = prefix.split()
            if head and words[:len(head)] == head:
                return self._shell_args(head[-1], words[len(head):])
        return "deny"

    def _shell_args(self, script: str, args: list) -> str:
        """Chaque option doit être connue du script ; chaque chemin reste dans le workspace."""
        rules = self.shell_scripts.get(script, {})
        flags = set(rules.get("flags", [])) | set(COMMON_FLAGS)
        outputs = set(rules.get("output_options", []))
        reads = set(rules.get("read_options", []))
        valued = outputs | reads | set(rules.get("value_options", []))
        multi = set(rules.get("multi_value_options", []))   # nargs "*" / "+" : plusieurs valeurs à la suite
        optional = set(rules.get("optional_value_options", []))  # nargs "?" : valeur facultative
        # Options qui font ÉCRIRE le script hors du contrôle des chemins (ex. `--apply` du
        # rattrapage matériel) : autorisées, mais seulement après accord de l'athlète.
        ask_flags = set(rules.get("ask_flags", []))
        verdict = "allow"
        i = 0
        while i < len(args):
            token = args[i]
            i += 1
            if self._option_like(token):
                name, eq, inline = token.partition("=")
                if name in ask_flags and not eq:
                    verdict = "ask"
                    continue
                if name in flags and not eq:
                    continue
                if name not in valued:
                    return "deny"                           # option inconnue : refusée
                kind = "write" if name in outputs else "read" if name in reads else "plain"
                values: list = []
                if eq:
                    values = [inline]
                elif name in optional and (i >= len(args) or self._option_like(args[i])):
                    continue                                # option seule : argparse prend sa constante
                elif name in multi:
                    while i < len(args) and not self._option_like(args[i]):
                        values.append(args[i])
                        i += 1
                elif i < len(args):
                    values, i = [args[i]], i + 1
                else:
                    return "deny"
                # Jamais de valeur qui commence par « - » : argparse la lirait comme une autre option
                # (ou l'avalerait) et la politique ne verrait plus ce qui s'exécute vraiment.
                if any(v.startswith("-") for v in values):
                    return "deny"
            else:
                values, kind = [token], "plain"
            if not all(self._shell_value(v, kind) for v in values):
                return "deny"
        return verdict

    @staticmethod
    def _option_like(token: str) -> bool:
        return token.startswith("-") and token != "-"

    def _shell_value(self, value: str, kind: str) -> bool:
        """Argument acceptable ? Les chemins restent dans le workspace, hors secrets et `.arc/`."""
        if value == "" and kind == "plain":
            return True
        if value.startswith("/"):
            # Chemin absolu DANS le workspace (OpenCode donne des chemins absolus au modèle) :
            # ramené au chemin relatif, puis contrôlé comme les autres. Ailleurs : refusé.
            normed, root = os.path.normpath(value), str(self.workspace) + os.sep
            if not normed.startswith(root):
                return False
            value = normed[len(root):]
        for piece in [value] + ([value.partition("=")[2]] if "=" in value else []):
            if piece.startswith(("/", "~")) or Path(piece).is_absolute():
                return False
        segments = re.split(r"[/=]", value)
        if ".." in segments or any(self._secret(seg) for seg in segments if seg):
            return False
        pathlike = (kind != "plain" or "/" in value or value in (".", "..")
                    or value.lower().endswith(PATH_SUFFIXES))
        if not pathlike:
            return True
        rel = resolve_workspace_path(self.workspace, value)
        if rel is None or self._secret(rel) or self._in_arc(rel):
            return False
        if kind == "write":                                 # sortie : uniquement les dossiers de données
            return "/" in rel and rel.split("/", 1)[0] in self.write_dirs
        return True

    # -- web -------------------------------------------------------------------------

    def _web_fetch(self, url: str) -> str:
        """http(s) sans identifiants, sans encodage dans l'hôte, hôte ASCII, port par défaut, domaine listé."""
        if not url or url != url.strip() or "\\" in url or any(ord(c) <= 0x20 or ord(c) == 0x7F for c in url):
            return "deny"
        try:
            parts = urlsplit(url)
            port = parts.port
        except ValueError:
            return "deny"
        if parts.scheme not in ("http", "https"):
            return "deny"
        netloc = parts.netloc
        if "@" in netloc or "%" in netloc or not netloc.isascii():
            return "deny"
        if port is not None and port != (443 if parts.scheme == "https" else 80):
            return "deny"
        host = (parts.hostname or "").lower()
        if not re.fullmatch(r"[a-z0-9]([a-z0-9.-]*[a-z0-9])?", host) or ".." in host:
            return "deny"
        return "allow" if any(host == d or host.endswith("." + d) for d in self.fetch_domains) else "deny"

    # -- mcp -------------------------------------------------------------------------

    def _mcp(self, tool: str) -> str:
        server, _, name = tool[len("mcp:"):].partition(".")
        if server.lower() not in self.mcp_servers or not name:
            return "deny"
        if any(fnmatch.fnmatch(name, pattern) for pattern in self.mcp_write_tools):
            return "ask"
        if any(name.startswith(prefix) for prefix in self.mcp_read_prefixes):
            return "allow"
        return "ask"            # outil inconnu d'un serveur connu : dans le doute, l'athlète tranche
