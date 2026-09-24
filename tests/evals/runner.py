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
import subprocess
import sys
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
    """
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

    return failures


def _as_list(value) -> list:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]
