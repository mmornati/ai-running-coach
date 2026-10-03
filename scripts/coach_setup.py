#!/usr/bin/env python3
"""Moteur du premier démarrage : `/coach-setup`.

Séparation volontaire, reprise de `bmad setup` : ce script sait ce qui manque et
sait écrire ; le modèle mène la conversation. C'est ce qui rend l'opération
idempotente — une valeur déjà écrite n'est jamais réécrite, donc relancer
`/coach-setup` ne pose aucune question et ne change rien.

    coach_setup.py --list-questions        # JSON des questions SANS réponse
    coach_setup.py --apply reponses.json   # écrit les réponses + installe les modèles
    coach_setup.py --apply-profile p.json  # fusionne des valeurs CONFIRMÉES dans Runner_Profile.md (#65)
    coach_setup.py --apply-shoes s.json    # ajoute des chaussures structurées, sans doublon
    coach_setup.py --apply-objective o.json # remplit l'objectif actif sans écraser
    coach_setup.py --export-state          # relit profil, chaussures et objectif pour l'interface
    coach_setup.py --status                # état de la configuration

Bibliothèque standard uniquement (CONTRIBUTING.md).
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from coach_config import ConfigError, read_toml, set_toml_key  # noqa: E402
import arc_legacy  # noqa: E402 — uniquement pour normalize_label (#65)

ENGINE = Path(__file__).resolve().parent.parent
QUESTIONS_FILE = ENGINE / "config/setup-questions.toml"
TEMPLATES = ENGINE / "templates"
PROFILE_FILE = "planning/Runner_Profile.md"
OBJECTIVE_FILE = "planning/active_objective.md"

# Puce de premier niveau, TROIS styles de libellé — « **Libellé** : valeur »
# (le style du modèle), « **Libellé :** valeur » (deux-points DANS le gras,
# toléré par `arc_legacy.parse_bullets`) et un libellé nu (repli tolérant,
# même alternative que `_BULLET_RE`). Le premier alternatif DOIT être essayé
# avant le second (`**Libellé :**` matcherait aussi `\*\*[^*]+\*\*` sans le
# `:` final si on inversait l'ordre) et DOIT inclure le `**` fermant dans le
# préfixe (revue de code #112, 2ᵉ tour) : le préfixe est écrit tel quel en cas
# de réécriture, un `**` fermant capturé dans `rest` au lieu de `prefix`
# disparaîtrait de la ligne écrite (« - **FC max :** 182 » devenait
# « - **FC max : 182 »). Pas de groupe `label` séparé : `arc_legacy.
# normalize_label` retire de toute façon tous les « * » et le « : » final,
# donc le préfixe (bullet marker excepté) sert directement de libellé pour
# les TROIS styles — voir `_profile_label`.
_PROFILE_BULLET_RE = re.compile(
    r"^(?P<prefix>[-*]\s+(?:\*\*[^*]+?:\s*\*\*|\*\*[^*]+\*\*\s*:|[^:\n]+?\s*:))(?P<rest>.*)$"
)
# Puce indentée (sous-liste) — `- **Zones / seuils** :` suivi de `  - Z1 : ...`
# compte comme un champ déjà rempli (revue de code #65) même si la ligne du
# libellé lui-même est vide.
_SUB_BULLET_RE = re.compile(r"^\s+[-*]\s+")
_INJECTION_CHARS_RE = re.compile(r"[\r\n]")


def _profile_label(prefix: str) -> str:
    """Libellé normalisé d'un préfixe de puce (`_PROFILE_BULLET_RE.group('prefix')`),
    quel que soit son style (« **Libellé** : », « **Libellé :** » ou nu) :
    `arc_legacy.normalize_label` retire déjà tout « * » et le « : » final, il
    suffit de lui retirer d'abord le marqueur de puce (`- `/`* `)."""
    return arc_legacy.normalize_label(re.sub(r"^[-*]\s+", "", prefix))


# Modèles déposés dans le workspace au premier démarrage : un fichier cité comme
# source de vérité par les agents doit exister pour de bon.
SCAFFOLD = {
    "templates/Runner_Profile.template.md": "planning/Runner_Profile.md",
    "templates/active_objective.template.md": "planning/active_objective.md",
}
WORK_DIRS = ["activities", "medical", "nutrition", "planning", "rapports", "resources", "gear"]


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


def _strip_html_comments(text: str) -> str:
    return re.sub(r"<!--.*?-->", "", text, flags=re.S)


def _is_blank_answer(raw) -> bool:
    """`None` (JSON `null`), une chaîne vide/blanche, ou une valeur qui ne
    contient QUE des `*` (« ** », qui disparaîtrait entièrement une fois
    `.replace("**", "")` appliqué par la lecture — un champ qui semblerait
    rempli dans le fichier mais rendrait une chaîne vide à tout parseur,
    revue de code #112, 2ᵉ tour) — jamais une valeur à écrire. Sans le premier
    garde-fou, `json.loads` rend `None` pour un `null`, et `str(None)`
    écrirait le texte littéral « None » dans le profil — un champ qu'aucune
    correction manuelle ultérieure ne rouvrirait, puisqu'il serait alors
    considéré comme déjà rempli (revue de code #65)."""
    if raw is None:
        return True
    text = str(raw).strip()
    return not text or not text.replace("*", "").strip()


def _ensure_scalar(raw, raw_label: str, field: str) -> None:
    """`value`/`source` doivent être une chaîne ou un nombre — jamais une
    liste ni un objet JSON, qui s'écrirait tel quel (`str([...])`) dans le
    profil sous une forme illisible et potentiellement injectante (revue de
    code #112, 2ᵉ tour). Un booléen JSON est rejeté À PART (revue de code
    #112, 3ᵉ tour) : `bool` est une sous-classe d'`int` en Python, donc
    `isinstance(True, (list, dict))` ne l'attrape pas, et `str(True)`
    écrirait le texte littéral « True »/« False » dans le profil — aussi
    invalide qu'un `None` écrit en « None »."""
    if isinstance(raw, bool):
        raise ConfigError(
            f"« {raw_label} » : « {field} » doit être une chaîne ou un nombre, pas un booléen."
        )
    if isinstance(raw, (list, dict)):
        raise ConfigError(
            f"« {raw_label} » : « {field} » doit être une chaîne ou un nombre, pas une liste/un objet."
        )


def _followed_by_sub_bullets(lines: list, index: int) -> bool:
    """Vrai si la ligne suivante (immédiatement, sans ligne vide entre les
    deux) est une puce INDENTÉE — `- **Zones / seuils** :` suivi de
    `  - Z1 : 120-135` compte comme un champ déjà rempli même si la ligne du
    libellé elle-même ne porte aucune valeur (revue de code #65)."""
    following = index + 1
    return following < len(lines) and bool(_SUB_BULLET_RE.match(lines[following]))


def apply_profile_answers(workspace: Path, answers: dict) -> dict:
    """Fusionne des réponses CONFIRMÉES dans `planning/Runner_Profile.md`, sans
    jamais réécrire un champ déjà rempli (story #65 — pré-remplissage Garmin).

    `answers` : `{"<Libellé exact du modèle>": "<valeur>"}`, ou
    `{"<Libellé>": {"value": "<valeur>", "source": "<provenance>"}}` pour
    tracer la provenance en commentaire HTML (retiré par `arc_legacy.parse_bullets`,
    donc invisible du parseur — uniquement pour un humain qui relit le fichier).

    Un libellé absent du fichier actuel est une erreur : les libellés du modèle
    ne sont jamais inventés ni renommés (cf. AGENTS.md). Un champ déjà rempli
    (même via une sous-liste indentée) est simplement ignoré (`skipped`),
    jamais écrasé. `value`/`source` doivent être une chaîne ou un nombre
    (jamais une liste/un objet), ne tolèrent ni retour à la ligne (une valeur
    ne tient jamais sur plusieurs puces) ni, pour `source`, la séquence `--`
    (elle refermerait prématurément le commentaire HTML `<!-- ... -->` et
    injecterait du Markdown arbitraire dans le fichier) — ces cas lèvent
    `ConfigError` plutôt que de corrompre silencieusement le profil.
    """
    path = workspace / PROFILE_FILE
    if not path.is_file():
        raise ConfigError(
            f"{path} n'existe pas encore — lancez d'abord `--apply` (ou `--scaffold`) "
            "pour installer le modèle avant d'y écrire des valeurs."
        )
    lines = path.read_text(encoding="utf-8").splitlines()

    written, skipped = [], []
    for raw_label, raw_answer in answers.items():
        if isinstance(raw_answer, dict):
            raw_value, source = raw_answer.get("value"), raw_answer.get("source")
        else:
            raw_value, source = raw_answer, None

        _ensure_scalar(raw_value, raw_label, "value")
        _ensure_scalar(source, raw_label, "source")

        if _is_blank_answer(raw_value):
            skipped.append(raw_label)
            continue
        value = str(raw_value).strip()

        if _INJECTION_CHARS_RE.search(value) or (source is not None and _INJECTION_CHARS_RE.search(str(source))):
            raise ConfigError(
                f"« {raw_label} » : « value »/« source » ne peuvent pas contenir de retour à la ligne."
            )
        if source is not None and "--" in str(source):
            raise ConfigError(
                f"« {raw_label} » : « source » ne peut pas contenir « -- » "
                "(refermerait le commentaire HTML de provenance)."
            )
        if "<!--" in value or "-->" in value:
            raise ConfigError(f"« {raw_label} » : « value » ne peut pas contenir de commentaire HTML.")

        target = arc_legacy.normalize_label(raw_label)
        match_index = None
        for index, line in enumerate(lines):
            match = _PROFILE_BULLET_RE.match(line)
            if match and _profile_label(match.group("prefix")) == target:
                match_index = index
                break
        if match_index is None:
            raise ConfigError(
                f"« {raw_label} » : aucun champ de ce nom dans {PROFILE_FILE} "
                "(un libellé n'est jamais inventé)."
            )

        match = _PROFILE_BULLET_RE.match(lines[match_index])
        rest = match.group("rest")
        current = _strip_html_comments(rest).replace("**", "").strip()
        if current or _followed_by_sub_bullets(lines, match_index):
            skipped.append(raw_label)          # jamais de réécriture d'un champ déjà rempli
            continue

        # Le champ était vide, mais portait peut-être un commentaire d'aide du
        # modèle (ex. « <!-- FC tenue ~1 h à fond... --> ») : on le conserve
        # après la valeur plutôt que de le perdre — la valeur écrite reste la
        # même pour le parseur (les commentaires HTML sont retirés avant
        # lecture), seul un humain qui relit le fichier le voit.
        hint = "".join(re.findall(r"<!--.*?-->", rest, flags=re.S))
        suffix = f" <!-- source : {source} -->" if source else ""
        if hint:
            suffix = f"{suffix} {hint}" if suffix else f" {hint}"
        lines[match_index] = f"{match.group('prefix')} {value}{suffix}"
        written.append(raw_label)

    if written:
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"written": written, "skipped": skipped}


def cmd_apply_profile(args) -> int:
    workspace = workspace_root(args.workspace)
    try:
        answers = json.loads(Path(args.apply_profile).read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigError(f"{args.apply_profile} : JSON invalide — {exc}") from exc
    if not isinstance(answers, dict):
        raise ConfigError(
            f"{args.apply_profile} : objet JSON attendu "
            '{"FC max": "182", "FC de repos de référence": {"value": "47", "source": "Garmin (get_stats), 2026-09-27"}}.'
        )
    result = apply_profile_answers(workspace, answers)
    print(json.dumps({"workspace": str(workspace), **result}, ensure_ascii=False, indent=2))
    return 0


def _shoe_text(raw, field: str, index: int, required: bool = False) -> str:
    """Champ texte d'une paire, borné à une seule ligne et sans séparateur de segments."""
    if raw is None:
        raw = ""
    if isinstance(raw, bool) or isinstance(raw, (list, dict)):
        raise ConfigError(f"chaussure {index} : « {field} » doit être du texte.")
    value = str(raw).strip()
    if required and not value:
        raise ConfigError(f"chaussure {index} : « {field} » est obligatoire.")
    if _INJECTION_CHARS_RE.search(value) or "<!--" in value or "-->" in value:
        raise ConfigError(f"chaussure {index} : « {field} » doit tenir sur une ligne sans commentaire HTML.")
    if "—" in value or "–" in value:
        raise ConfigError(f"chaussure {index} : « {field} » ne peut pas contenir le séparateur « — ».")
    return value


def _shoe_number(raw, field: str, index: int, *, positive: bool) -> float | None:
    if raw is None or str(raw).strip() == "":
        return None
    if isinstance(raw, bool) or isinstance(raw, (list, dict)):
        raise ConfigError(f"chaussure {index} : « {field} » doit être un nombre.")
    try:
        value = float(str(raw).strip().replace(",", "."))
    except ValueError as exc:
        raise ConfigError(f"chaussure {index} : « {field} » doit être un nombre de kilomètres.") from exc
    if not math.isfinite(value) or value < 0 or (positive and value == 0):
        qualifier = "strictement positif" if positive else "positif ou nul"
        raise ConfigError(f"chaussure {index} : « {field} » doit être {qualifier}.")
    return value


def _format_number(value: float) -> str:
    return str(int(value)) if value.is_integer() else f"{value:g}"


def apply_shoes(workspace: Path, shoes: list) -> dict:
    """Ajoute des paires confirmées dans « ### Chaussures », sans toucher aux existantes.

    La première paire ajoutée devient la paire par défaut seulement si le profil
    n'en possède pas déjà une. Les doublons de nom sont ignorés ; le modèle de
    profil reste la seule source de vérité et son format documenté est conservé.
    """
    path = workspace / PROFILE_FILE
    if not path.is_file():
        raise ConfigError(f"{path} n'existe pas encore — lancez d'abord `--apply` (ou `--scaffold`).")
    if not isinstance(shoes, list):
        raise ConfigError("--apply-shoes attend une liste JSON de chaussures.")

    text = path.read_text(encoding="utf-8")
    heading = re.search(r"^### Chaussures\s*$", text, flags=re.M | re.I)
    if not heading:
        raise ConfigError(f"section « ### Chaussures » introuvable dans {PROFILE_FILE}.")
    next_heading = re.search(r"^### Matériel\s*$", text[heading.end():], flags=re.M | re.I)
    if not next_heading:
        raise ConfigError(f"section « ### Matériel » introuvable après « ### Chaussures » dans {PROFILE_FILE}.")
    insertion = heading.end() + next_heading.start()

    existing = arc_legacy.parse_gear(text)
    existing_names = {str(item.get("name") or "").strip().casefold() for item in existing}
    has_default = any(bool(item.get("default")) for item in existing)
    added, skipped, lines = [], [], []

    for index, raw in enumerate(shoes, 1):
        if not isinstance(raw, dict):
            raise ConfigError(f"chaussure {index} : objet JSON attendu.")
        unknown = set(raw) - {"name", "start_date", "threshold_km", "start_km", "usage"}
        if unknown:
            raise ConfigError(f"chaussure {index} : champ(s) inconnu(s) {sorted(unknown)}.")
        name = _shoe_text(raw.get("name"), "name", index, required=True)
        normalized = name.casefold()
        if normalized in existing_names:
            skipped.append(name)
            continue
        start_date = _shoe_text(raw.get("start_date"), "start_date", index)
        if start_date and arc_legacy.parse_fr_date(start_date) is None:
            raise ConfigError(f"chaussure {index} : date d'achat illisible « {start_date} » (attendu : AAAA-MM-JJ ou mois/année).")
        threshold = _shoe_number(raw.get("threshold_km"), "threshold_km", index, positive=True)
        start_km = _shoe_number(raw.get("start_km"), "start_km", index, positive=False)
        usage = _shoe_text(raw.get("usage"), "usage", index)

        segments = [name]
        if start_date:
            segments.append(f"depuis {start_date}")
        if threshold is not None:
            segments.append(f"alerte {_format_number(threshold)} km")
        if start_km is not None:
            segments.append(f"départ {_format_number(start_km)} km")
        if usage:
            segments.append(f"usage: {usage}")
        line = "- " + " — ".join(segments)
        if not has_default:
            line += " (par défaut)"
            has_default = True
        lines.append(line)
        existing_names.add(normalized)
        added.append(name)

    if lines:
        before = text[:insertion].rstrip()
        after = text[insertion:].lstrip("\n")
        path.write_text(before + "\n\n" + "\n".join(lines) + "\n\n" + after, encoding="utf-8")
    return {"added": added, "skipped": skipped}


def cmd_apply_shoes(args) -> int:
    workspace = workspace_root(args.workspace)
    try:
        shoes = json.loads(Path(args.apply_shoes).read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigError(f"{args.apply_shoes} : JSON invalide — {exc}") from exc
    result = apply_shoes(workspace, shoes)
    print(json.dumps({"workspace": str(workspace), **result}, ensure_ascii=False, indent=2))
    return 0


def apply_objective_answers(workspace: Path, answers: dict) -> dict:
    """Fusionne des réponses dans l'objectif actif, avec les mêmes garanties que le profil."""
    path = workspace / OBJECTIVE_FILE
    if not path.is_file():
        raise ConfigError(f"{path} n'existe pas encore — lancez d'abord `--apply` (ou `--scaffold`).")
    lines = path.read_text(encoding="utf-8").splitlines()
    written, skipped = [], []

    for raw_label, raw_value in answers.items():
        _ensure_scalar(raw_value, raw_label, "value")
        if _is_blank_answer(raw_value):
            skipped.append(raw_label)
            continue
        value = str(raw_value).strip()
        if _INJECTION_CHARS_RE.search(value):
            raise ConfigError(f"« {raw_label} » : la valeur ne peut pas contenir de retour à la ligne.")
        if "<!--" in value or "-->" in value:
            raise ConfigError(f"« {raw_label} » : la valeur ne peut pas contenir de commentaire HTML.")

        target = arc_legacy.normalize_label(raw_label)
        match_index = None
        for index, line in enumerate(lines):
            match = _PROFILE_BULLET_RE.match(line)
            if match and _profile_label(match.group("prefix")) == target:
                match_index = index
                break
        if match_index is None:
            raise ConfigError(
                f"« {raw_label} » : aucun champ de ce nom dans {OBJECTIVE_FILE} "
                "(un libellé n'est jamais inventé)."
            )

        match = _PROFILE_BULLET_RE.match(lines[match_index])
        current = _strip_html_comments(match.group("rest")).replace("**", "").strip()
        if current or _followed_by_sub_bullets(lines, match_index):
            skipped.append(raw_label)
            continue
        hint = "".join(re.findall(r"<!--.*?-->", match.group("rest"), flags=re.S))
        lines[match_index] = f"{match.group('prefix')} {value}" + (f" {hint}" if hint else "")
        written.append(raw_label)

    if written:
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"written": written, "skipped": skipped}


def cmd_apply_objective(args) -> int:
    workspace = workspace_root(args.workspace)
    try:
        answers = json.loads(Path(args.apply_objective).read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigError(f"{args.apply_objective} : JSON invalide — {exc}") from exc
    if not isinstance(answers, dict):
        raise ConfigError(f"{args.apply_objective} : objet JSON attendu.")
    result = apply_objective_answers(workspace, answers)
    print(json.dumps({"workspace": str(workspace), **result}, ensure_ascii=False, indent=2))
    return 0


def cmd_export_state(args) -> int:
    """Expose l'état humain éditable sans modifier le workspace.

    Les clés de profil et d'objectif sont les libellés normalisés déjà utilisés
    par `arc_legacy.parse_bullets`. Les chaussures passent par le parseur de
    référence afin que l'interface ne réinterprète pas leur Markdown.
    """
    workspace = workspace_root(args.workspace)
    profile_path = workspace / PROFILE_FILE
    objective_path = workspace / OBJECTIVE_FILE
    profile_text = profile_path.read_text(encoding="utf-8") if profile_path.is_file() else ""
    objective_text = objective_path.read_text(encoding="utf-8") if objective_path.is_file() else ""
    # Le tableau « Journal des révisions » possède une colonne « Date » qui ne
    # doit jamais être confondue avec la date de course laissée vide.
    objective_fields = re.split(
        r"^##\s+Journal des révisions\s*$", objective_text, maxsplit=1, flags=re.M | re.I
    )[0]

    shoes = []
    for item in arc_legacy.parse_gear(profile_text):
        if item.get("ignored"):
            continue
        threshold_m = item.get("threshold_m")
        start_m = item.get("start_m")
        shoes.append({
            "name": str(item.get("name") or ""),
            "purchase_date": str(item.get("start_date") or ""),
            "threshold_km": _format_number(float(threshold_m) / 1000) if threshold_m is not None else "700",
            "starting_km": _format_number(float(start_m) / 1000) if start_m is not None else "0",
            "usage": str(item.get("usage") or ""),
        })

    print(json.dumps({
        "workspace": str(workspace),
        "profile": arc_legacy.parse_bullets(profile_text),
        "objective": arc_legacy.parse_bullets(objective_fields),
        "shoes": shoes,
    }, ensure_ascii=False, indent=2))
    return 0


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
    group.add_argument(
        "--apply-profile", metavar="FICHIER.json",
        help="fusionne des réponses CONFIRMÉES (ex. pré-remplissage Garmin) dans planning/Runner_Profile.md, "
             "sans jamais écraser un champ déjà rempli",
    )
    group.add_argument(
        "--apply-shoes", metavar="FICHIER.json",
        help="ajoute une liste JSON de chaussures confirmées dans le profil, sans toucher aux paires existantes",
    )
    group.add_argument(
        "--apply-objective", metavar="FICHIER.json",
        help="remplit les champs vides de planning/active_objective.md sans écraser l'objectif existant",
    )
    group.add_argument(
        "--export-state", action="store_true",
        help="relit le profil, les chaussures et l'objectif pour préremplir une interface",
    )
    group.add_argument("--status", action="store_true")
    group.add_argument("--scaffold", action="store_true", help="installe les modèles sans rien demander")
    args = parser.parse_args(argv)

    try:
        if args.list_questions:
            return cmd_list_questions(args)
        if args.apply:
            return cmd_apply(args)
        if args.apply_profile:
            return cmd_apply_profile(args)
        if args.apply_shoes:
            return cmd_apply_shoes(args)
        if args.apply_objective:
            return cmd_apply_objective(args)
        if args.export_state:
            return cmd_export_state(args)
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
