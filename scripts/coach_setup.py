#!/usr/bin/env python3
"""Moteur du premier démarrage : `/coach-setup`.

Séparation volontaire, reprise de `bmad setup` : ce script sait ce qui manque et
sait écrire ; le modèle mène la conversation. C'est ce qui rend l'opération
idempotente — une valeur déjà écrite n'est jamais réécrite, donc relancer
`/coach-setup` ne pose aucune question et ne change rien.

    coach_setup.py --list-questions        # JSON des questions SANS réponse
    coach_setup.py --apply reponses.json   # écrit les réponses + installe les modèles
    coach_setup.py --status                # état de la configuration

Bibliothèque standard uniquement (CONTRIBUTING.md).
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from coach_config import ConfigError, read_toml, set_toml_key  # noqa: E402

ENGINE = Path(__file__).resolve().parent.parent
QUESTIONS_FILE = ENGINE / "config/setup-questions.toml"
TEMPLATES = ENGINE / "templates"

# Modèles déposés dans le workspace au premier démarrage : un fichier cité comme
# source de vérité par les agents doit exister pour de bon.
SCAFFOLD = {
    "templates/Runner_Profile.template.md": "planning/Runner_Profile.md",
    "templates/active_objective.template.md": "planning/active_objective.md",
}
WORK_DIRS = ["activities", "medical", "nutrition", "planning", "rapports", "resources"]


def workspace_root(explicit: str | None = None) -> Path:
    """Même résolution que scripts/lib/config.sh, pour que shell et Python voient le même workspace."""
    if explicit:
        return Path(explicit).expanduser().resolve()
    if os.environ.get("ARC_WORKSPACE"):
        return Path(os.environ["ARC_WORKSPACE"]).expanduser().resolve()
    pointer = Path.home() / ".config/ai-running-coach/workspace"
    if pointer.is_file():
        memorised = pointer.read_text(encoding="utf-8").splitlines()
        if memorised and memorised[0].strip():
            return Path(memorised[0].strip()).expanduser().resolve()
    return ENGINE


def load_questions() -> list:
    raw = read_toml(QUESTIONS_FILE)
    questions = []
    for name, spec in raw.items():
        if not isinstance(spec, dict) or "key" not in spec:
            continue
        section, _, key = spec["key"].partition(".")
        if not section or not key:
            raise ConfigError(f"{QUESTIONS_FILE} : [{name}].key doit valoir « section.clé ».")
        questions.append({**spec, "id": name, "section": section, "key": key})
    if not questions:
        raise ConfigError(f"{QUESTIONS_FILE} : aucune question.")
    return questions


def current_value(workspace: Path, section: str, key: str):
    """Valeur déjà choisie par l'utilisateur, ou None.

    Seul `workspace.user.toml` compte : `workspace.toml` est versionné et ne
    contient que des défauts, qui ne valent pas réponse.
    """
    user = read_toml(workspace / "config/workspace.user.toml")
    return user.get(section, {}).get(key)


def pending(workspace: Path) -> list:
    return [
        q for q in load_questions()
        if current_value(workspace, q["section"], q["key"]) is None
    ]


def cmd_list_questions(args) -> int:
    workspace = workspace_root(args.workspace)
    payload = []
    for q in pending(workspace):
        entry = {
            "id": q["id"],
            "key": f"{q['section']}.{q['key']}",
            "prompt": q["prompt"],
            "kind": q["kind"],
            "default": q.get("default", ""),
        }
        if q.get("help"):
            entry["help"] = q["help"]
        if q.get("options"):
            entry["choices"] = [
                {"value": value, "label": label}
                for value, label in zip(q["options"], q.get("labels", q["options"]))
            ]
        payload.append(entry)
    print(json.dumps({"workspace": str(workspace), "pending": payload}, ensure_ascii=False, indent=2))
    return 0


def validate(question: dict, answer) -> list:
    options = question.get("options")
    if not options:
        return answer if question["kind"] == "multi" else str(answer)
    values = answer if isinstance(answer, list) else [v.strip() for v in str(answer).split(",") if v.strip()]
    unknown = [v for v in values if v not in options]
    if unknown:
        raise ConfigError(
            f"{question['id']} : valeur(s) inconnue(s) {unknown}. Attendu parmi {options}."
        )
    if question["kind"] == "multi":
        return values
    if len(values) != 1:
        raise ConfigError(f"{question['id']} : une seule valeur attendue, reçu {values}.")
    return values[0]


def scaffold(workspace: Path) -> list:
    created = []
    for name in WORK_DIRS:
        (workspace / name).mkdir(parents=True, exist_ok=True)
    for source, destination in SCAFFOLD.items():
        target = workspace / destination
        if target.exists():
            continue                       # ne jamais écraser le travail de l'athlète
        template = ENGINE / source
        if not template.is_file():
            raise ConfigError(f"modèle introuvable : {template}")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(template, target)
        created.append(destination)
    return created


def cmd_apply(args) -> int:
    workspace = workspace_root(args.workspace)
    try:
        answers = json.loads(Path(args.apply).read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigError(f"{args.apply} : JSON invalide — {exc}") from exc
    if not isinstance(answers, dict):
        raise ConfigError(f"{args.apply} : objet JSON attendu {{\"coaching.style\": \"factuel\", …}}.")

    by_key = {f"{q['section']}.{q['key']}": q for q in load_questions()}
    by_id = {q["id"]: q for q in load_questions()}

    written, skipped = [], []
    for name, answer in answers.items():
        question = by_key.get(name) or by_id.get(name)
        if question is None:
            raise ConfigError(f"réponse « {name} » : aucune question correspondante.")
        section, key = question["section"], question["key"]
        if current_value(workspace, section, key) is not None:
            skipped.append(f"{section}.{key}")     # jamais de réécriture
            continue
        value = validate(question, answer)
        if value == "" or value == []:
            skipped.append(f"{section}.{key}")
            continue
        set_toml_key(workspace / "config/workspace.user.toml", section, key, value)
        written.append(f"{section}.{key}")

    created = scaffold(workspace)
    print(json.dumps(
        {"workspace": str(workspace), "written": written, "skipped": skipped,
         "scaffolded": created, "still_pending": [q["id"] for q in pending(workspace)]},
        ensure_ascii=False, indent=2,
    ))
    return 0


def cmd_status(args) -> int:
    workspace = workspace_root(args.workspace)
    user = workspace / "config/workspace.user.toml"
    remaining = pending(workspace)

    gitignored = False
    gitignore = workspace / ".gitignore"
    if gitignore.is_file():
        gitignored = "config/workspace.user.toml" in gitignore.read_text(encoding="utf-8")

    status = {
        "workspace": str(workspace),
        "config_file": str(user),
        "configured": user.is_file(),
        "pending_questions": [q["id"] for q in remaining],
        "profile": {
            destination: (workspace / destination).is_file()
            for destination in SCAFFOLD.values()
        },
        "personal_config_gitignored": gitignored,
        "next": "coach_setup.py --list-questions" if remaining else "rien à faire",
    }
    print(json.dumps(status, ensure_ascii=False, indent=2))
    return 0


def main(argv: list | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--workspace", default=None, help="racine du workspace (défaut : résolution habituelle)")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--list-questions", action="store_true")
    group.add_argument("--apply", metavar="FICHIER.json")
    group.add_argument("--status", action="store_true")
    group.add_argument("--scaffold", action="store_true", help="installe les modèles sans rien demander")
    args = parser.parse_args(argv)

    try:
        if args.list_questions:
            return cmd_list_questions(args)
        if args.apply:
            return cmd_apply(args)
        if args.scaffold:
            created = scaffold(workspace_root(args.workspace))
            print(json.dumps({"scaffolded": created}, ensure_ascii=False))
            return 0
        return cmd_status(args)
    except ConfigError as exc:
        print(f"coach_setup: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
