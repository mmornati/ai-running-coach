"""Palier C — exécution des agents contre un workspace de démonstration.

Ce que ce palier vérifie, ce sont des **comportements**, pas des tournures :
quels outils l'agent a tenté d'appeler, quels fichiers il a écrits, quelles
notions apparaissent ou n'apparaissent pas. Un test qui exigerait une phrase
précise serait du bruit.

Hermétique par construction : aucun compte Garmin, aucune donnée réelle. Le
workspace est un jeu de fixtures synthétiques et le serveur MCP est un stub qui
journalise chaque appel — « le coach a-t-il cherché la HRV ? » devient ainsi une
assertion sur un fichier, pas une devinette sur du texte.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent.parent
REPO = TESTS_DIR.parent
CASES_DIR = TESTS_DIR / "evals" / "cases"
FIXTURES_DIR = TESTS_DIR / "evals" / "fixtures"

DEFAULT_MODEL = "claude-haiku-4-5-20251001"
DEFAULT_REPEAT = 3
DEFAULT_THRESHOLD = 2 / 3

# Serveurs MCP factices disponibles pour un scénario (#26). `garmin` reste le
# nom historique et le seul câblé par défaut ; `intervals` (#68) ne l'est que
# si le cas déclare `[stub.intervals.*]` — voir `build_workspace`.
STUB_SCRIPTS = {
    "garmin": TESTS_DIR / "evals" / "stub_garmin_mcp.py",
    "intervals": TESTS_DIR / "evals" / "stub_intervals_mcp.py",
}


def _write_stub_config(root: Path, server: str, stub_section) -> Path | None:
    """Dépose la section `[stub.<server>]` d'un cas en JSON pour le stub.

    Le stub la lit via `ARC_STUB_CONFIG` (`mcp_stub_common.load_stub_config`).
    Rien à écrire pour un cas sans section `[stub]` — c'est ce qui garantit la
    non-régression des cas existants.

    Écrit à côté du workspace (`root`, pas `root / "workspace"`) et non
    dedans : l'agent testé n'a accès qu'au workspace via ses outils fichiers,
    il ne doit pas pouvoir lire à l'avance le scénario de panne qu'on lui
    scripte.
    """
    if not stub_section:
        return None
    path = root / f".stub-config-{server}.json"
    path.write_text(json.dumps(stub_section, ensure_ascii=False), encoding="utf-8")
    return path


def _uses_timeout_error(case: dict) -> bool:
    """Un cas script-t-il au moins un `error = "timeout"` (n'importe quel
    serveur, n'importe quel outil) ? Détermine si `run_case` doit brider le
    timeout MCP côté client (voir `run_case`)."""
    for stub_section in case.get("stub", {}).values():
        for override in stub_section.values():
            if str(override.get("error")) == "timeout":
                return True
    return False


def enabled() -> bool:
    return os.environ.get("ARC_LLM_TESTS") == "1"


def skip_reason() -> str:
    if not enabled():
        return "palier C désactivé (ARC_LLM_TESTS=1 pour l'activer)"
    if shutil.which(runner_command()[0]) is None:
        return f"{runner_command()[0]} introuvable dans le PATH"
    return ""


def runner_command() -> list:
    return os.environ.get("ARC_EVAL_RUNNER", "claude").split()


def model() -> str:
    return os.environ.get("ARC_EVAL_MODEL", DEFAULT_MODEL)


def repeat() -> int:
    return int(os.environ.get("ARC_EVAL_REPEAT", DEFAULT_REPEAT))


def threshold() -> float:
    return float(os.environ.get("ARC_EVAL_THRESHOLD", DEFAULT_THRESHOLD))


def load_cases() -> list:
    """Charge les scénarios. Un fichier TOML par cas, aucun analyseur maison.

    Le projet parle déjà TOML partout (`workspace.toml`, `setup-questions.toml`)
    et `tomllib` le lit sans dépendance : écrire un sous-ensemble YAML à la main
    aurait été du code fragile pour rien.
    """
    import tomllib

    cases = []
    for path in sorted(CASES_DIR.glob("*.toml")):
        case = tomllib.loads(path.read_text(encoding="utf-8"))
        case.setdefault("id", path.stem)
        case["source"] = str(path)
        cases.append(case)
    return cases


def build_workspace(root: Path, case: dict) -> Path:
    """Workspace jetable : fixtures + configuration propre au scénario."""
    workspace = root / "workspace"
    fixture = FIXTURES_DIR / case.get("fixture", "base-week")
    if fixture.is_dir():
        shutil.copytree(fixture, workspace)
    else:
        workspace.mkdir(parents=True)
    for name in ("activities", "medical", "nutrition", "planning", "rapports", "resources"):
        (workspace / name).mkdir(parents=True, exist_ok=True)

    # Le moteur est lié, jamais copié : les prompts testés sont ceux du dépôt.
    (workspace / "config").mkdir(exist_ok=True)
    for name in ("workspace.toml", "coaching-styles.md", "setup-questions.toml", "sports"):
        source = REPO / "config" / name
        target = workspace / "config" / name
        if source.exists() and not target.exists():
            target.symlink_to(source)
    for name in ("agents", "skills", "scripts", "templates", "AGENTS.md"):
        target = workspace / name
        if not target.exists():
            target.symlink_to(REPO / name)

    # Serveur(s) MCP factice(s) : aucune donnée réelle, et chaque appel d'outil
    # est journalisé — c'est ce qui rend « n'a pas cherché la HRV »
    # vérifiable. `garmin` est toujours câblé (non-régression) ; `intervals`
    # (#68) ne l'est que si le cas script explicitement ses réponses, pour ne
    # pas exposer un serveur que le scénario n'a pas demandé.
    tool_log = workspace / ".tool-calls.log"
    mcp_servers = {}
    for server, script in STUB_SCRIPTS.items():
        stub_section = case.get("stub", {}).get(server)
        if server != "garmin" and not stub_section:
            continue
        config_path = _write_stub_config(root, server, stub_section)
        env = {
            "ARC_TOOL_LOG": str(tool_log),
            # Toujours présente, même vide : une valeur héritée de l'environnement
            # de l'appelant (export ARC_STUB_CONFIG=... resté dans un shell) ne
            # doit jamais fuiter dans un cas qui ne script rien.
            "ARC_STUB_CONFIG": str(config_path) if config_path else "",
        }
        mcp_servers[server] = {"command": sys.executable, "args": [str(script)], "env": env}
    (workspace / ".mcp.json").write_text(
        json.dumps({"mcpServers": mcp_servers}, indent=2), encoding="utf-8",
    )

    # Les agents sont découverts via .claude/agents ; on ne lie que ceux du scénario.
    enabled = case.get("config", {}).get("agents", {}).get("enabled")
    agents_dir = workspace / ".claude/agents"
    agents_dir.mkdir(parents=True, exist_ok=True)
    for agent in sorted((REPO / "agents").glob("*.md")):
        if enabled is None or agent.stem in enabled:
            (agents_dir / agent.name).symlink_to(agent)
    skills_link = workspace / ".claude/skills"
    if not skills_link.exists():
        skills_link.symlink_to(REPO / "skills")

    overrides = case.get("config", {})
    if overrides:
        lines = []
        for section, values in overrides.items():
            lines.append(f"[{section}]")
            for key, value in values.items():
                if isinstance(value, list):
                    lines.append(f"{key} = [" + ", ".join(f'"{v}"' for v in value) + "]")
                elif isinstance(value, bool):
                    lines.append(f"{key} = {'true' if value else 'false'}")
                else:
                    lines.append(f'{key} = "{value}"')
            lines.append("")
        (workspace / "config/workspace.user.toml").write_text("\n".join(lines), encoding="utf-8")
    return workspace


# Timeout MCP côté client pour un cas qui scripte `error = "timeout"`
# (millisecondes). Sans lui, un appel jamais répondu par le stub (#26,
# `DropRequest`) laisse l'agent — et donc `subprocess.run` — attendre le
# timeout du PROCESS (300s par défaut) avant d'échouer, ce qui ne démontre
# rien de plus qu'un `MAX_TIMEOUT_DELAY_S` déjà court côté stub. `claude -p`
# lit cette variable pour bander ses propres appels d'outils MCP.
MCP_TOOL_TIMEOUT_MS = os.environ.get("ARC_MCP_TOOL_TIMEOUT_MS", "15000")


def run_case(case: dict, workspace: Path, timeout: int = 300) -> dict:
    """Une exécution. Rend le texte produit et le journal des outils."""
    tool_log = workspace / ".tool-calls.log"
    command = runner_command() + [
        "-p", case["prompt"],
        "--model", model(),
        "--permission-mode", "acceptEdits",
        "--strict-mcp-config", "--mcp-config", str(workspace / ".mcp.json"),
    ]
    env = dict(os.environ, ARC_WORKSPACE=str(workspace), ARC_TOOL_LOG=str(tool_log))
    if _uses_timeout_error(case):
        env.setdefault("MCP_TOOL_TIMEOUT", MCP_TOOL_TIMEOUT_MS)
    try:
        completed = subprocess.run(
            command, cwd=str(workspace), env=env, capture_output=True, text=True, timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        # Le runner lui-même n'a pas répondu dans le budget imparti — un
        # échec de cas normal (le comportement attendu était que l'agent
        # abandonne l'outil lent et réponde), pas une exception qui remonte
        # et casse toute la suite.
        return {
            "returncode": -1,
            "output": _decode(exc.stdout),
            "stderr": _decode(exc.stderr) or f"le runner n'a pas répondu sous {timeout}s (TimeoutExpired)",
            "tool_calls": tool_log.read_text(encoding="utf-8") if tool_log.exists() else "",
            "workspace": workspace,
        }
    return {
        "returncode": completed.returncode,
        "output": completed.stdout,
        "stderr": completed.stderr,
        "tool_calls": tool_log.read_text(encoding="utf-8") if tool_log.exists() else "",
        "workspace": workspace,
    }


def _decode(value) -> str:
    if value is None:
        return ""
    return value.decode("utf-8", errors="replace") if isinstance(value, bytes) else value


NOT_LOGGED_IN = re.compile(r"not logged in|/login|unauthor", re.IGNORECASE)


def looks_unauthenticated(result: dict) -> bool:
    """Le runner a répondu, mais sans identifiants.

    Cas fréquent : le CLI est installé, l'utilisateur est connecté dans son
    terminal, mais pas dans l'environnement qui lance les tests. Mieux vaut
    ignorer le palier avec un message clair que rendre onze échecs identiques.

    `returncode == -1` est le sentinel posé par `run_case` pour un
    `subprocess.TimeoutExpired` (cas qui scripte un `error = "timeout"`, #26).
    Le message de relais d'un 401 stub (« ... Unauthorized ... ») peut alors
    apparaître dans la sortie partielle sans que le run soit réellement « pas
    authentifié » — ce n'est pas ce qu'on veut *skip*, c'est un vrai résultat
    de cas (l'agent a-t-il su abandonner l'outil lent ?).
    """
    if result["returncode"] == -1:
        return False
    return result["returncode"] != 0 and bool(
        NOT_LOGGED_IN.search(result["output"] + result["stderr"])
    )


def _new_files(case: dict, result: dict, pattern: str) -> list:
    """Fichiers du workspace correspondant au motif, hors ceux apportés par la fixture."""
    fixture = FIXTURES_DIR / case.get("fixture", "base-week")
    return sorted(p for p in result["workspace"].glob(pattern)
                  if p.is_file() and not (fixture / p.relative_to(result["workspace"])).exists())


def _arc_problem(path: Path):
    """Motif de non-conformité au contrat ```arc, ou None."""
    sys.path.insert(0, str(REPO / "scripts"))
    import arc_contract as C

    try:
        block = C.extract_block(path.read_text(encoding="utf-8"))
    except C.ContractError as exc:
        return str(exc)
    if block is None:
        return "bloc ```arc absent"
    errors, _ = C.validate(block)
    return "; ".join(errors[:3]) if errors else None


def _resolve_json_path(data, path: str):
    """Résout un chemin JSON simple dans une donnée.

    Syntaxe supportée :
    - clés pointées : `foo.bar.baz`
    - indices : `items[0]`
    - caractères génériques : `items[*].name` (chaque élément d'une liste)

    Rend une liste de valeurs (vide si le chemin ne résout rien).
    """
    # Construire une liste de segments : (key, index_or_wildcard)
    # "foo.bar[0].baz[*].name" → [("foo", None), ("bar", 0), ("baz", None), ("baz", "*"), ("name", None)]
    segments = []
    remaining = path
    while remaining:
        # Chercher le prochain "." ou "["
        dot_pos = remaining.find(".")
        bracket_pos = remaining.find("[")

        if dot_pos == -1 and bracket_pos == -1:
            # Dernier segment
            segments.append((remaining, None))
            break

        if dot_pos != -1 and (bracket_pos == -1 or dot_pos < bracket_pos):
            # Le "." vient avant le "["
            segments.append((remaining[:dot_pos], None))
            remaining = remaining[dot_pos + 1:]
        elif bracket_pos != -1:
            # Le "[" vient en premier (ou il n'y a pas de ".")
            key = remaining[:bracket_pos] if bracket_pos > 0 else None
            if key:
                segments.append((key, None))

            # Extraire l'index ou le caractère générique : [...] ou [0] ou [*]
            close_pos = remaining.find("]", bracket_pos)
            if close_pos == -1:
                # Malformé : ignorer
                break
            index_str = remaining[bracket_pos + 1:close_pos]
            if index_str == "*":
                segments.append((None, "*"))
            else:
                try:
                    segments.append((None, int(index_str)))
                except ValueError:
                    # Index non entier : ignorer ce segment
                    break
            remaining = remaining[close_pos + 1:]
            if remaining.startswith("."):
                remaining = remaining[1:]
        else:
            break

    # Appliquer les segments en commençant par `data`
    results = [data]
    for key, index_or_wildcard in segments:
        new_results = []
        for current in results:
            if index_or_wildcard is None and key is not None:
                # Accès au dictionnaire
                if isinstance(current, dict) and key in current:
                    new_results.append(current[key])
            elif index_or_wildcard == "*":
                # Caractère générique sur liste
                if isinstance(current, list):
                    new_results.extend(current)
            elif isinstance(index_or_wildcard, int):
                # Accès par index
                if isinstance(current, list) and -len(current) <= index_or_wildcard < len(current):
                    new_results.append(current[index_or_wildcard])
        results = new_results
        if not results:
            break

    return results


def _load_arc_block(path: Path) -> dict | None:
    """Extrait et analyse le bloc ```arc d'un fichier."""
    sys.path.insert(0, str(REPO / "scripts"))
    import arc_contract as C

    try:
        text = path.read_text(encoding="utf-8")
        block = C.extract_block(text)
        if block is None:
            return None
        # Valider avant de renvoyer
        errors, _ = C.validate(block)
        if errors:
            return None
        return block
    except Exception:
        return None


def _parse_tool_log(tool_calls_text: str) -> list:
    """Parse le journal des appels d'outils.

    Chaque ligne est JSON : {"tool", "server", "arguments"}
    """
    calls = []
    for line in tool_calls_text.strip().split("\n"):
        if not line.strip():
            continue
        try:
            calls.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return calls


def _compare_value(found, expected, comparator: str) -> bool:
    """Compare une valeur trouvée avec une attendue selon le comparateur."""
    if comparator == "equals":
        return found == expected
    if comparator == "regex":
        return bool(re.search(str(expected), str(found)))
    if comparator == "min":
        return found is not None and found >= expected
    if comparator == "max":
        return found is not None and found <= expected
    if comparator == "in":
        # `in` = found doit être dans la liste expected
        return found in (expected if isinstance(expected, list) else [expected])
    return False


def check(case: dict, result: dict) -> list:
    """Applique les assertions déterministes. Rend la liste des échecs."""
    expect = case.get("expect", {})
    failures = []
    haystack = result["output"]

    for needle in _as_list(expect.get("must_match")):
        if not re.search(needle, haystack, re.IGNORECASE):
            failures.append(f"attendu mais absent : /{needle}/")
    for needle in _as_list(expect.get("must_not_match")):
        if re.search(needle, haystack, re.IGNORECASE):
            failures.append(f"présent alors qu'il ne devrait pas : /{needle}/")

    for tool in _as_list(expect.get("tools_called")):
        if tool not in result["tool_calls"]:
            failures.append(f"outil jamais appelé : {tool}")
    for tool in _as_list(expect.get("tools_not_called")):
        if tool in result["tool_calls"]:
            failures.append(f"outil appelé alors qu'il ne devrait pas : {tool}")

    for relative in _as_list(expect.get("files_created")):
        if not (result["workspace"] / relative).exists():
            failures.append(f"fichier attendu non créé : {relative}")

    # Contrat de données : fichiers ÉCRITS pendant le run (la fixture n'en a aucun au contrat).
    for pattern in _as_list(expect.get("files_with_arc_block")):
        new = _new_files(case, result, pattern)
        if not new:
            failures.append(f"aucun fichier écrit ne correspond à {pattern}")
        for path in new:
            problem = _arc_problem(path)
            if problem:
                failures.append(f"{path.relative_to(result['workspace'])} : {problem}")
    for pattern in _as_list(expect.get("files_absent")):
        new = _new_files(case, result, pattern)
        if new:
            failures.append(f"fichier(s) écrit(s) alors qu'attendu(s) absent(s) : "
                            + ", ".join(str(p.relative_to(result["workspace"])) for p in new))

    limit = expect.get("max_words")
    if limit and len(haystack.split()) > int(limit):
        failures.append(f"réponse trop longue : {len(haystack.split())} mots > {limit}")

    pattern = expect.get("first_line_matches")
    if pattern:
        first = next((l for l in haystack.splitlines() if l.strip()), "")
        if not re.search(pattern, first.strip(), re.IGNORECASE):
            failures.append(f"première ligne « {first.strip()[:80]} » ne correspond pas à /{pattern}/")

    # Nouvelles assertions : arc_field
    for assertion in _as_list(expect.get("arc_field")):
        glob_pattern = assertion.get("glob")
        path_expr = assertion.get("path")
        if not glob_pattern or not path_expr:
            continue

        new = _new_files(case, result, glob_pattern)
        if not new:
            failures.append(f"arc_field : aucun fichier ne correspond à {glob_pattern}")
            continue

        # Résolvants pour chaque fichier
        comparators = {k: v for k, v in assertion.items() if k in ("equals", "min", "max", "in")}
        if not comparators:
            failures.append(f"arc_field : {glob_pattern} : aucun comparateur (equals|min|max|in)")
            continue

        found_match = False
        for fpath in new:
            block = _load_arc_block(fpath)
            if block is None:
                continue

            values = _resolve_json_path(block, path_expr)
            if not values:
                continue

            # Vérifier si au moins une valeur satisfait tous les comparateurs
            for val in values:
                all_match = all(_compare_value(val, cmp_val, cmp_kind)
                               for cmp_kind, cmp_val in comparators.items())
                if all_match:
                    found_match = True
                    break

            if found_match:
                break

        if not found_match:
            comp_str = ", ".join(f"{k}={v}" for k, v in comparators.items())
            failures.append(f"arc_field : {glob_pattern} : {path_expr} ne satisfait pas {comp_str}")

    # Nouvelles assertions : tool_args_match
    tool_calls = _parse_tool_log(result["tool_calls"])
    for assertion in _as_list(expect.get("tool_args_match")):
        tool_name = assertion.get("tool")
        path_expr = assertion.get("path")
        server = assertion.get("server")
        if not tool_name or not path_expr:
            continue

        comparators = {k: v for k, v in assertion.items() if k in ("equals", "min", "max", "regex")}
        if not comparators:
            failures.append(f"tool_args_match : {tool_name} : aucun comparateur")
            continue

        found_match = False
        for call in tool_calls:
            if call.get("tool") != tool_name:
                continue
            if server and call.get("server") != server:
                continue

            arguments = call.get("arguments", {})
            values = _resolve_json_path(arguments, path_expr)
            if not values:
                continue

            for val in values:
                all_match = all(_compare_value(val, cmp_val, cmp_kind)
                               for cmp_kind, cmp_val in comparators.items())
                if all_match:
                    found_match = True
                    break

            if found_match:
                break

        if not found_match:
            comp_str = ", ".join(f"{k}={v}" for k, v in comparators.items())
            failures.append(f"tool_args_match : {tool_name} : arguments.{path_expr} ne satisfait pas {comp_str}")

    # Nouvelles assertions : sqlite_query
    for assertion in _as_list(expect.get("sqlite_query")):
        sql = assertion.get("sql")
        if not sql:
            continue

        comparators = {k: v for k, v in assertion.items() if k in ("equals", "min", "max")}
        if not comparators:
            failures.append(f"sqlite_query : aucun comparateur")
            continue

        # Valider que c'est un SELECT
        sql_upper = sql.strip().upper()
        if not sql_upper.startswith("SELECT"):
            failures.append(f"sqlite_query : requête non SELECT")
            continue

        # Indexer le workspace dans une DB temporaire
        try:
            with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
                tmp_db = tmp.name

            sys.path.insert(0, str(REPO / "scripts"))
            import arc_index as I

            conn = I.open_db(result["workspace"], db=tmp_db, rebuild=True)
            I.index_workspace(conn, result["workspace"])

            # Exécuter la requête
            cursor = conn.execute(sql)
            row = cursor.fetchone()
            conn.close()

            if row is None:
                failures.append(f"sqlite_query : requête n'a renvoyé aucune ligne")
                continue

            # Comparer la première colonne
            found = row[0]
            found_match = all(_compare_value(found, cmp_val, cmp_kind)
                             for cmp_kind, cmp_val in comparators.items())
            if not found_match:
                comp_str = ", ".join(f"{k}={v}" for k, v in comparators.items())
                failures.append(f"sqlite_query : {found} ne satisfait pas {comp_str}")

        except Exception as exc:
            failures.append(f"sqlite_query : erreur d'exécution : {exc}")

    # Nouvelles assertions : file_contains_any
    for assertion in _as_list(expect.get("file_contains_any")):
        glob_pattern = assertion.get("glob")
        any_list = assertion.get("any", [])
        if not glob_pattern or not any_list:
            continue

        new = _new_files(case, result, glob_pattern)
        if not new:
            failures.append(f"file_contains_any : aucun fichier ne correspond à {glob_pattern}")
            continue

        found_match = False
        for fpath in new:
            try:
                content = fpath.read_text(encoding="utf-8").lower()
                for needle in any_list:
                    if str(needle).lower() in content:
                        found_match = True
                        break
            except Exception:
                continue
            if found_match:
                break

        if not found_match:
            notions = ", ".join(str(n) for n in any_list)
            failures.append(f"file_contains_any : {glob_pattern} : aucun de « {notions} »")

    return failures


def _as_list(value) -> list:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]
