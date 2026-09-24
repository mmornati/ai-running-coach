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
from datetime import date, datetime, timezone
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent.parent
REPO = TESTS_DIR.parent
CASES_DIR = TESTS_DIR / "evals" / "cases"
FIXTURES_DIR = TESTS_DIR / "evals" / "fixtures"

DEFAULT_MODEL = "claude-haiku-4-5-20251001"
DEFAULT_REPEAT = 3
DEFAULT_THRESHOLD = 2 / 3

# Nom de la variable d'environnement lue par `record_result` / écrite par la CI
# (#29) : quand elle pointe vers un chemin, chaque cas y persiste son taux de
# réussite en JSON, pour que `render_results.py` en tire un `RESULTS.md` sans
# rejouer les cas. Absente en local par défaut : ça ne change rien au comportement
# historique du palier C tant que personne ne la règle.
RESULTS_ENV = "ARC_EVAL_RESULTS_OUT"

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


def results_output_path() -> Path | None:
    """Chemin du JSON de résultats (#29), ou `None` si la variable n'est pas réglée."""
    value = os.environ.get(RESULTS_ENV)
    return Path(value) if value else None


def record_result(case_id: str, passed: int, attempts: int) -> None:
    """Persiste le taux de réussite d'un cas pour `render_results.py` (#29).

    Sans effet si `ARC_EVAL_RESULTS_OUT` n'est pas réglé — c'est le cas de toute
    exécution locale qui ne le passe pas explicitement. Écrit après CHAQUE cas,
    pas seulement à la fin de la suite : un run interrompu (timeout du job CI)
    laisse ainsi une trace partielle plutôt que rien.

    Lecture-fusion-écriture, PAS de verrou : un cas n'efface jamais celui déjà
    écrit par un autre (chacun ne touche que sa propre clé), mais ce n'est
    correct que parce que `tests/run_tests.py` exécute le palier C de façon
    strictement séquentielle (`unittest` sans exécuteur parallèle) — deux
    process qui écriraient ici en même temps pourraient perdre l'un des deux
    écrits (read-modify-write classique). Si le palier C gagne un jour un mode
    parallèle, cette fonction devra écrire un fichier par cas (assemblé ensuite
    par `render_results.py`) plutôt que de partager un seul fichier.
    """
    path = results_output_path()
    if path is None:
        return
    data = {}
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = {}
    data[case_id] = {
        "passed": passed,
        "attempts": attempts,
        "rate": passed / attempts if attempts else 0.0,
    }
    data["_meta"] = {
        "date": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "model": model(),
        "repeat": repeat(),
        "threshold": threshold(),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False), encoding="utf-8")


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


def _load_arc_block(path: Path):
    """Extrait et valide le bloc ```arc d'un fichier.

    Rend `(bloc, None)` si tout va bien, `(None, motif)` sinon — bloc
    dupliqué, JSON invalide, bloc absent, ou en échec de validation contre le
    schéma (`scripts/arc_contract.py`). Ne lève jamais : c'est ce texte, pas
    une exception avalée, que `check()` doit pouvoir reporter dans le message
    d'échec (#27, revue PR #72 — l'ancienne version rendait `None` sur
    n'importe quelle erreur, y compris de programmation, sans distinction).
    """
    sys.path.insert(0, str(REPO / "scripts"))
    import arc_contract as C

    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return None, f"lecture impossible : {exc}"
    try:
        block = C.extract_block(text)
    except C.ContractError as exc:
        return None, str(exc)
    if block is None:
        return None, "bloc ```arc absent"
    errors, _ = C.validate(block)
    if errors:
        return None, "; ".join(errors[:3])
    return block, None


def _arc_problem(path: Path):
    """Motif de non-conformité au contrat ```arc, ou None (utilisé par `files_with_arc_block`)."""
    _, problem = _load_arc_block(path)
    return problem


# ---------------------------------------------------------------------------
# Chemins JSON simples : `foo.bar[0].baz[*].name`
# ---------------------------------------------------------------------------


def _parse_json_path(path: str) -> list:
    """Découpe un chemin JSON en segments : `("key", nom)`, `("index", n)`,
    `("wildcard",)`.

    Lève `ValueError` sur toute syntaxe malformée plutôt que d'ignorer
    silencieusement le reste du chemin (#27, revue PR #72) : un chemin comme
    `items[abc].x`, `items[0`, `a.b.` ou `items[*]x` est une faute de frappe
    dans un cas de test, pas une donnée absente — elle doit remonter comme
    échec explicite, pas comme un chemin qui « ne résout à rien ».
    """
    if not path:
        raise ValueError("chemin vide")
    segments = []
    i, n = 0, len(path)
    while i < n:
        if path[i] in ".[":
            raise ValueError(f"caractère {path[i]!r} inattendu en position {i} dans {path!r}")
        j = i
        while j < n and path[j] not in ".[":
            j += 1
        key = path[i:j]
        if not key:
            raise ValueError(f"clé vide dans {path!r}")
        segments.append(("key", key))
        i = j
        while i < n and path[i] == "[":
            close = path.find("]", i)
            if close == -1:
                raise ValueError(f"']' manquant dans {path!r}")
            index_str = path[i + 1:close]
            if index_str == "*":
                segments.append(("wildcard",))
            else:
                try:
                    segments.append(("index", int(index_str)))
                except ValueError:
                    raise ValueError(f"index non entier {index_str!r} dans {path!r}") from None
            i = close + 1
        if i < n:
            if path[i] != ".":
                raise ValueError(f"caractère {path[i]!r} inattendu après ']' dans {path!r} (un '.' est attendu)")
            i += 1
            if i >= n or path[i] in ".[":
                raise ValueError(f"clé manquante après '.' dans {path!r}")
    return segments


def _resolve_json_path(data, path: str) -> list:
    """Résout un chemin JSON contre `data`.

    Rend une liste de `(chemin_concret, valeur)` — le chemin concret a ses
    `[*]` remplacés par l'indice réellement traversé (`items[*].x` →
    `items[0].x`, `items[1].x`, …), ce qui permet aux messages d'échec de
    désigner l'élément fautif au lieu du seul motif générique (#27, revue
    PR #72). Une liste vide signifie « chemin introuvable » : ce n'est **pas**
    une erreur ici, c'est à l'appelant de décider si c'est un échec.

    Lève `ValueError` si `path` est syntaxiquement invalide.
    """
    segments = _parse_json_path(path)
    results = [("", data)]
    for segment in segments:
        new_results = []
        kind = segment[0]
        for prefix, current in results:
            if kind == "key":
                key = segment[1]
                if isinstance(current, dict) and key in current:
                    new_results.append((f"{prefix}.{key}" if prefix else key, current[key]))
            elif kind == "index":
                idx = segment[1]
                if isinstance(current, list) and -len(current) <= idx < len(current):
                    real_idx = idx if idx >= 0 else len(current) + idx
                    new_results.append((f"{prefix}[{real_idx}]", current[idx]))
            elif kind == "wildcard":
                if isinstance(current, list):
                    for i, item in enumerate(current):
                        new_results.append((f"{prefix}[{i}]", item))
        results = new_results
        if not results:
            break
    return results


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


def _is_numeric(value) -> bool:
    """`bool` n'est PAS numérique ici, même si `isinstance(True, int)` vaut vrai en
    Python — `min = 3` satisfait par `found = True` serait un faux positif absurde."""
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _compare_value(found, expected, comparator: str) -> bool:
    """Compare une valeur trouvée avec une attendue selon le comparateur.

    Lève `ValueError` (jamais une exception qui remonterait telle quelle
    jusqu'à `check()`) sur un comparateur numérique appliqué à une valeur non
    numérique (chaîne, `None`, `bool`…) ou sur une regex qui ne compile pas —
    c'est l'appelant qui transforme ça en ligne de résultat lisible (#27,
    revue PR #72 : « TOML min="3" » ou un `equals` de type incompatible ne
    doivent jamais faire planter la suite)."""
    if comparator == "equals":
        if isinstance(found, bool) or isinstance(expected, bool):
            return type(found) is type(expected) and found == expected
        return found == expected
    if comparator == "regex":
        try:
            return bool(re.search(str(expected), str(found)))
        except re.error as exc:
            raise ValueError(f"regex invalide {expected!r} : {exc}") from exc
    if comparator in ("min", "max"):
        if not _is_numeric(found) or not _is_numeric(expected):
            raise ValueError(
                f"comparateur {comparator} : valeur numérique attendue "
                f"(trouvé {found!r}, attendu {expected!r})"
            )
        return found >= expected if comparator == "min" else found <= expected
    if comparator == "in":
        allowed = expected if isinstance(expected, list) else [expected]
        return found in allowed
    raise ValueError(f"comparateur inconnu : {comparator!r}")   # inatteignable après validation (test_evals.py)


def _describe_expected(comparator: str, expected) -> str:
    """Décrit ce qu'attendait le comparateur, pour un message d'échec lisible."""
    if comparator == "equals":
        return f"≠ {expected!r}"
    if comparator == "min":
        return f"< {expected} (minimum attendu)"
    if comparator == "max":
        return f"> {expected} (maximum attendu)"
    if comparator == "in":
        return f"∉ {expected!r}"
    if comparator == "regex":
        return f"ne correspond pas à /{expected}/"
    return f"ne satisfait pas {comparator}={expected!r}"


def _validate_single_read_statement(sql: str):
    """Rend un motif de refus si `sql` n'est pas une unique requête de lecture, sinon None.

    Secondaire par construction (#27, revue PR #72) : le vrai garde-fou est la
    connexion SQLite ouverte en lecture seule dans `_check_sqlite_queries`
    (`mode=ro` + `PRAGMA query_only`). Ce contrôle textuel n'est qu'un
    diagnostic plus lisible en cas d'abus évident, et tolère les commentaires
    de tête (`-- …`) et les CTE (`WITH … SELECT`)."""
    if not isinstance(sql, str) or not sql.strip():
        return "requête vide"
    lines, body_started = [], False
    for line in sql.splitlines():
        stripped = line.strip()
        if not body_started and (not stripped or stripped.startswith("--")):
            continue
        body_started = True
        lines.append(line)
    body = "\n".join(lines).strip()
    if not body:
        return "requête vide (rien que des commentaires)"
    without_trailing = body[:-1] if body.endswith(";") else body
    if ";" in without_trailing:
        return "une seule instruction SQL est autorisée"
    upper = without_trailing.strip().upper()
    if not (upper.startswith("SELECT") or upper.startswith("WITH")):
        return "seules les requêtes SELECT (ou WITH … SELECT) sont autorisées"
    return None


ARC_FIELD_COMPARATORS = ("equals", "min", "max", "in")
TOOL_ARGS_COMPARATORS = ("equals", "min", "max", "regex")
SQLITE_COMPARATORS = ("equals", "min", "max")


def _check_arc_field(case: dict, result: dict, assertions: list) -> list:
    """`arc_field` : sémantique TOUT, pas AU MOINS UN (#27, revue PR #72).

    Chaque fichier écrit pendant le run et correspondant au glob doit
    résoudre au moins une valeur pour `path`, et **toutes** les valeurs
    résolues (un `[*]` peut en donner plusieurs, dans un seul fichier comme
    across plusieurs fichiers) doivent satisfaire **tous** les comparateurs.
    Un chemin qui ne résout à rien dans un fichier donné est un échec à part
    entière, pas un fichier ignoré."""
    failures = []
    for assertion in assertions:
        if not isinstance(assertion, dict):
            failures.append(f"arc_field : entrée mal formée : {assertion!r}")
            continue
        glob_pattern, path_expr = assertion.get("glob"), assertion.get("path")
        if not glob_pattern or not path_expr:
            failures.append("arc_field : 'glob' et 'path' sont obligatoires")
            continue
        comparators = {k: v for k, v in assertion.items() if k in ARC_FIELD_COMPARATORS}
        if not comparators:
            failures.append(f"arc_field : {glob_pattern} : {path_expr} : aucun comparateur (equals|min|max|in)")
            continue

        new = _new_files(case, result, glob_pattern)
        if not new:
            failures.append(f"arc_field : aucun fichier écrit ne correspond à {glob_pattern}")
            continue

        for fpath in new:
            relpath = fpath.relative_to(result["workspace"])
            block, problem = _load_arc_block(fpath)
            if problem:
                failures.append(f"arc_field : {relpath} : {problem}")
                continue
            try:
                resolved = _resolve_json_path(block, path_expr)
            except ValueError as exc:
                failures.append(f"arc_field : {relpath} : chemin invalide {path_expr!r} : {exc}")
                continue
            if not resolved:
                failures.append(f"arc_field : {relpath} : chemin introuvable : {path_expr}")
                continue
            for concrete_path, value in resolved:
                for cmp_kind, cmp_expected in comparators.items():
                    try:
                        ok = _compare_value(value, cmp_expected, cmp_kind)
                    except ValueError as exc:
                        failures.append(f"arc_field : {relpath} : {concrete_path} : {exc}")
                        continue
                    if not ok:
                        failures.append(
                            f"arc_field : {relpath} : {concrete_path} = {value!r} "
                            f"{_describe_expected(cmp_kind, cmp_expected)}"
                        )
    return failures


def _check_tool_args_match(tool_calls: list, assertions: list) -> list:
    """`tool_args_match` : au moins UN appel doit satisfaire — mais, DANS cet
    appel, TOUTES les valeurs résolues par un `[*]` doivent satisfaire (#27,
    revue PR #72). « L'outil n'a jamais été appelé » et « appelé, mais chemin
    introuvable dans les arguments » sont deux messages distincts."""
    failures = []
    for assertion in assertions:
        if not isinstance(assertion, dict):
            failures.append(f"tool_args_match : entrée mal formée : {assertion!r}")
            continue
        tool_name, path_expr, server = assertion.get("tool"), assertion.get("path"), assertion.get("server")
        if not tool_name or not path_expr:
            failures.append("tool_args_match : 'tool' et 'path' sont obligatoires")
            continue
        comparators = {k: v for k, v in assertion.items() if k in TOOL_ARGS_COMPARATORS}
        if not comparators:
            failures.append(f"tool_args_match : {tool_name} : aucun comparateur (equals|min|max|regex)")
            continue

        matching_calls = [c for c in tool_calls if c.get("tool") == tool_name
                          and (not server or c.get("server") == server)]
        if not matching_calls:
            scope = f" (serveur {server})" if server else ""
            failures.append(f"tool_args_match : aucun appel à {tool_name}{scope}")
            continue

        path_error, satisfied, call_reports = None, False, []
        for call in matching_calls:
            arguments = call.get("arguments") or {}
            try:
                resolved = _resolve_json_path(arguments, path_expr)
            except ValueError as exc:
                path_error = f"tool_args_match : {tool_name} : chemin invalide {path_expr!r} : {exc}"
                break
            if not resolved:
                call_reports.append(f"chemin introuvable : arguments.{path_expr}")
                continue
            call_failures = []
            for concrete_path, value in resolved:
                for cmp_kind, cmp_expected in comparators.items():
                    try:
                        ok = _compare_value(value, cmp_expected, cmp_kind)
                    except ValueError as exc:
                        call_failures.append(f"arguments.{concrete_path} : {exc}")
                        continue
                    if not ok:
                        call_failures.append(
                            f"arguments.{concrete_path} = {value!r} {_describe_expected(cmp_kind, cmp_expected)}"
                        )
            if not call_failures:
                satisfied = True
                break
            call_reports.append("; ".join(call_failures))

        if path_error:
            failures.append(path_error)
        elif not satisfied:
            details = " | ".join(call_reports) if call_reports else "aucune valeur résolue"
            failures.append(
                f"tool_args_match : {tool_name} : {len(matching_calls)} appel(s), aucun ne satisfait — {details}"
            )
    return failures


def _check_sqlite_queries(assertions: list, result: dict) -> list:
    """`sqlite_query` : indexe le workspace UNE FOIS pour toutes les assertions
    du cas (pas une réindexation par requête), sur une base temporaire
    nettoyée par `TemporaryDirectory` (jamais de fichier orphelin), puis rouvre
    en LECTURE SEULE (`mode=ro` + `PRAGMA query_only`) pour exécuter les
    requêtes elles-mêmes — le contrôle textuel de `_validate_single_read_statement`
    n'est qu'un filtre secondaire, plus lisible (#27, revue PR #72)."""
    failures, to_run = [], []
    for assertion in assertions:
        if not isinstance(assertion, dict):
            failures.append(f"sqlite_query : entrée mal formée : {assertion!r}")
            continue
        sql = assertion.get("sql")
        if not sql:
            failures.append("sqlite_query : 'sql' est obligatoire")
            continue
        comparators = {k: v for k, v in assertion.items() if k in SQLITE_COMPARATORS}
        if not comparators:
            failures.append(f"sqlite_query : {sql!r} : aucun comparateur (equals|min|max)")
            continue
        problem = _validate_single_read_statement(sql)
        if problem:
            failures.append(f"sqlite_query : {sql!r} : {problem}")
            continue
        to_run.append((sql, comparators))

    if not to_run:
        return failures

    # `today` fixe pour tout le check() : des métriques (charge, VDOT…) calculées
    # deux fois dans le même run avec un `today` qui dérive entre-temps (minuit
    # pendant une suite longue) donneraient des résultats différents pour la
    # même exécution — ce n'est pas déterministe (#27, revue PR #72).
    today = date.today().isoformat()
    with tempfile.TemporaryDirectory(prefix="arc-eval-sqlite-") as tmp:
        db_path = str(Path(tmp) / "index.db")
        sys.path.insert(0, str(REPO / "scripts"))
        import arc_index as I

        conn = I.open_db(result["workspace"], db=db_path, rebuild=True)
        try:
            I.index_workspace(conn, result["workspace"], today=today)
        finally:
            conn.close()

        ro_conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        try:
            ro_conn.execute("PRAGMA query_only = ON")
            for sql, comparators in to_run:
                try:
                    row = ro_conn.execute(sql).fetchone()
                except sqlite3.Error as exc:
                    failures.append(f"sqlite_query : {sql!r} : erreur d'exécution : {exc}")
                    continue
                if row is None:
                    failures.append(f"sqlite_query : {sql!r} : aucune ligne renvoyée")
                    continue
                found = row[0]
                if found is None:
                    failures.append(f"sqlite_query : {sql!r} : valeur NULL")
                    continue
                for cmp_kind, cmp_expected in comparators.items():
                    try:
                        ok = _compare_value(found, cmp_expected, cmp_kind)
                    except ValueError as exc:
                        failures.append(f"sqlite_query : {sql!r} : {exc}")
                        continue
                    if not ok:
                        failures.append(
                            f"sqlite_query : {sql!r} : {found!r} {_describe_expected(cmp_kind, cmp_expected)}"
                        )
        finally:
            ro_conn.close()
    return failures


def _check_file_contains_any(case: dict, result: dict, assertions: list) -> list:
    failures = []
    for assertion in assertions:
        if not isinstance(assertion, dict):
            failures.append(f"file_contains_any : entrée mal formée : {assertion!r}")
            continue
        glob_pattern, any_list = assertion.get("glob"), assertion.get("any")
        if not glob_pattern or not any_list:
            failures.append("file_contains_any : 'glob' et 'any' (non vide) sont obligatoires")
            continue
        new = _new_files(case, result, glob_pattern)
        if not new:
            failures.append(f"file_contains_any : aucun fichier ne correspond à {glob_pattern}")
            continue
        found_match = False
        for fpath in new:
            try:
                content = fpath.read_text(encoding="utf-8").lower()
            except OSError:
                continue
            if any(str(needle).lower() in content for needle in any_list):
                found_match = True
                break
        if not found_match:
            notions = ", ".join(str(n) for n in any_list)
            failures.append(f"file_contains_any : {glob_pattern} : aucun de « {notions} »")
    return failures


def _safe_check(label: str, fn, *args) -> list:
    """Ceinture et bretelles (#27, revue PR #72) : aucune exception, même une
    faute de programmation dans un helper, ne doit faire planter `check()` —
    au pire un échec de cas signalé proprement plutôt qu'une suite qui casse."""
    try:
        return fn(*args)
    except Exception as exc:      # noqa: BLE001 — c'est le but : tout attraper ici
        return [f"{label} : erreur inattendue : {exc}"]


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

    failures.extend(_safe_check("arc_field", _check_arc_field, case, result, _as_list(expect.get("arc_field"))))

    tool_calls = _parse_tool_log(result["tool_calls"])
    failures.extend(_safe_check(
        "tool_args_match", _check_tool_args_match, tool_calls, _as_list(expect.get("tool_args_match"))
    ))
    failures.extend(_safe_check("sqlite_query", _check_sqlite_queries, _as_list(expect.get("sqlite_query")), result))
    failures.extend(_safe_check(
        "file_contains_any", _check_file_contains_any, case, result, _as_list(expect.get("file_contains_any"))
    ))

    return failures


def _as_list(value) -> list:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]
