#!/usr/bin/env python3
"""arc_weight_sync.py — Poids du jour lu dans Garmin Connect (#222).

Le modèle ne fait que deux choses : appeler les outils de LECTURE du serveur MCP
`garmin` et passer leur réponse brute à ce script. Le choix de la pesée, la règle de
priorité (l'athlète prime le même jour) et le signalement d'un écart sont décidés ici,
en pur stdlib, de façon déterministe et testable sans modèle ni Garmin. Le script lit
les fichiers santé existants (`medical/AAAA-MM-JJ_health.md`) mais n'écrit RIEN : il dit
quelles clés poser dans le bloc ```arc``` ; l'agent écrit puis valide le fichier.

Outils `garmin-mcp` lus (noms, paramètres et formes vérifiés dans
`src/garmin_mcp/weight_management.py` au commit épinglé `GARMIN_MCP_REF` d'`install.sh`) :

  get_daily_weigh_ins(date) → {"date", "measurement_count", "measurements": [{"weight_kg",
      "weight_grams", "source_type", "timestamp_gmt", ...}]} ; texte brut
      « No weight measurements found for <date>. » si aucune pesée
  get_weigh_ins(start_date, end_date) → même forme, chaque mesure portant en plus `date`
      (rattrapage sur une plage, un seul appel) ; texte « No weight measurements found
      between ... » si vide

Jamais utilisés (écriture Garmin, hors liste blanche) : `add_weigh_in`,
`add_weigh_in_with_timestamps`, `add_body_composition`, `delete_weigh_ins`.

Règles (voir aussi `ASSUMPTIONS`) :
  - une pesée n'est écrite QUE le jour où elle a été faite : un jour sans pesée Garmin
    reste sans `weight_kg` (action `none`) — jamais la valeur de la veille recopiée ;
    `arc_index.resolve_weight_kg_as_of` reprend déjà la dernière pesée connue ;
  - plusieurs pesées le même jour : la plus ancienne (`timestamp_gmt`) — celle du matin,
    comme le reste du bilan santé, et stable d'une synchronisation à l'autre ;
  - priorité : une valeur déclarée par l'athlète le même jour (`weight_origin: "chat"`,
    ou clé absente = fichier antérieur à #222) prime sur Garmin ; si l'écart dépasse
    `WEIGHT_CONFLICT_KG`, il est signalé UNE fois — la pesée Garmin écartée est gardée
    dans `weight_garmin_kg`, ce qui empêche de le signaler à nouveau.

Sous-commande `plan` — entrée JSON (`--input`, `--garmin '<json>'` ou stdin ; sur stdin, la
réponse brute de l'outil est aussi acceptée telle quelle, sans l'envelopper dans `garmin`) :
    {"garmin": <réponse brute de get_daily_weigh_ins ou get_weigh_ins>,
     "date": "2026-10-10",            # requis avec get_daily_weigh_ins si la réponse n'est
                                      # que le texte « No weight ... » (jour sans pesée)
     "existing_only": false}          # rattrapage : ne jamais créer de fichier santé

ou, quand l'athlète DÉCLARE son poids en conversation :
    {"declared": {"date": "2026-10-10", "weight_kg": 71.2}}

Sortie : {"days": [{"date", "action", "file", "file_exists", "set", "remove", "flag",
"message", ...}], "weighed_by_garmin": ["AAAA-MM-JJ", ...], "warnings": [...]}.
`action` ∈ write | update | unchanged | keep_athlete | declare | none | skip_no_file.
`set` : clés à poser dans le bloc arc (un fichier absent se crée avec `create`,
squelette minimal du contrat `health`) ; `remove` : clés à retirer ; `flag` : écart à
signaler à l'athlète (une seule fois).

Bibliothèque standard uniquement (CONTRIBUTING.md).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date as _date, timedelta
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
import arc_contract as C  # noqa: E402

ASSUMPTIONS = {
    "earliest_weigh_in": (
        "Plusieurs pesées Garmin le même jour : la plus ancienne (`timestamp_gmt`) est retenue — "
        "celle du matin, cohérente avec le bilan santé (`weight_merge`), et stable d'une "
        "synchronisation à l'autre (une pesée du soir ne remplace pas celle du matin). Sans "
        "horodatage, l'ordre de la réponse Garmin est conservé."
    ),
    "athlete_priority": (
        "Le même jour, une valeur déclarée par l'athlète prime toujours sur Garmin (même règle que "
        "le matériel, #133). Écart signalé au-delà de 1 kg — seuil du projet (variation "
        "intra-journalière usuelle de l'hydratation et du contenu digestif), pas une valeur de "
        "la littérature ; signalé une seule fois, la pesée écartée étant gardée dans "
        "`weight_garmin_kg`."
    ),
    "no_carry_forward": (
        "Un jour sans pesée Garmin n'a pas de `weight_kg` : la valeur de la veille n'est jamais "
        "recopiée. La lecture (`resolve_weight_kg_as_of`) prend déjà la dernière pesée connue."
    ),
}

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_SAME_KG = 0.005


class WeightSyncError(ValueError):
    """Entrée malformée (date illisible, JSON invalide...)."""


# ---------------------------------------------------------------------------
# Lecture de la réponse Garmin
# ---------------------------------------------------------------------------

def _num(value) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _measurement_kg(m: dict) -> Optional[float]:
    kg = _num(m.get("weight_kg"))
    if kg is None:
        grams = _num(m.get("weight_grams"))
        kg = grams / 1000 if grams is not None else None
    if kg is None:
        return None
    lo, hi = C.BODY_WEIGHT_KG_PLAUSIBLE
    return round(kg, 2) if lo <= kg <= hi else None


def parse_garmin(raw, date: Optional[str] = None) -> tuple:
    """Réponse brute → ({date: poids retenu}, avertissements, dates couvertes).

    `raw` : dict/JSON de get_daily_weigh_ins ou get_weigh_ins, ou leur texte
    « No weight measurements found ... » (aucune pesée). Les dates couvertes sont
    celles que la réponse décrit, pesée ou non (pour dire `none` explicitement)."""
    warnings: list = []
    if raw is None:
        raise WeightSyncError("réponse Garmin absente (`garmin`)")
    if isinstance(raw, str):
        text = raw.strip()
        try:
            raw = json.loads(text)
        except json.JSONDecodeError:
            low = text.lower()
            if low.startswith("no weight measurements found"):
                return {}, warnings, [date] if date else []
            raise WeightSyncError(f"réponse Garmin illisible : {text[:120]}")
    if not isinstance(raw, dict):
        raise WeightSyncError("réponse Garmin : objet JSON attendu")
    top_date = raw.get("date") if isinstance(raw.get("date"), str) else date
    covered = []
    rng = raw.get("date_range")
    if isinstance(rng, dict) and _DATE_RE.match(str(rng.get("start", ""))) and _DATE_RE.match(str(rng.get("end", ""))):
        start, end = _date.fromisoformat(rng["start"]), _date.fromisoformat(rng["end"])
        covered = [(start + timedelta(days=i)).isoformat() for i in range((end - start).days + 1)]
    elif top_date:
        covered = [top_date]
    by_date: dict = {}
    for index, m in enumerate(raw.get("measurements") or []):
        if not isinstance(m, dict):
            continue
        day = m.get("date") or top_date
        if not (isinstance(day, str) and _DATE_RE.match(day)):
            warnings.append(f"pesée sans date ignorée (mesure n° {index + 1})")
            continue
        kg = _measurement_kg(m)
        if kg is None:
            warnings.append(f"{day} : pesée absente ou hors de {C.BODY_WEIGHT_KG_PLAUSIBLE[0]:g}-"
                            f"{C.BODY_WEIGHT_KG_PLAUSIBLE[1]:g} kg ignorée")
            continue
        ts = _num(m.get("timestamp_gmt"))
        key = (0, ts, index) if ts is not None else (1, 0.0, index)
        if day not in by_date or key < by_date[day][0]:
            by_date[day] = (key, kg)
        if day not in covered:
            covered.append(day)
    return {d: v[1] for d, v in by_date.items()}, warnings, sorted(covered)


# ---------------------------------------------------------------------------
# Fichiers santé
# ---------------------------------------------------------------------------

def health_path(workspace: Path, day: str) -> Path:
    return workspace / "medical" / f"{day}_health.md"


def read_health(workspace: Path, day: str) -> tuple:
    """(existe, bloc arc ou None). Un fichier sans bloc lisible est signalé, jamais réécrit."""
    path = health_path(workspace, day)
    if not path.is_file():
        return False, None
    try:
        return True, C.extract_block(path.read_text(encoding="utf-8"))
    except C.ContractError as exc:
        raise WeightSyncError(f"{path.name} : {exc}")


def _same(a, b) -> bool:
    return a is not None and b is not None and abs(a - b) < _SAME_KG


def _diff(a, b) -> float:
    return round(a - b, 2)


def decide_garmin(day: str, garmin_kg: Optional[float], exists: bool, data: Optional[dict],
                  existing_only: bool = False) -> dict:
    """Action pour une date, à partir de la pesée Garmin retenue (ou de son absence)."""
    out = {"date": day, "file": f"medical/{day}_health.md", "file_exists": exists,
           "garmin_kg": garmin_kg, "set": {}, "remove": [], "flag": None}
    if garmin_kg is None:
        out.update(action="none", message="Aucune pesée Garmin ce jour : aucune clé écrite.")
        return out
    if exists and data is None:
        out.update(action="none", message="Fichier santé sans bloc arc : rien n'est écrit, à corriger d'abord.")
        return out
    data = data or {}
    current, origin = _num(data.get("weight_kg")), data.get("weight_origin")
    out.update(existing_kg=current, existing_origin=origin)
    if not exists:
        if existing_only:
            out.update(action="skip_no_file", message="Rattrapage : pas de fichier santé ce jour, aucun créé.")
            return out
        out.update(action="write", create=True, set={"weight_kg": garmin_kg, "weight_origin": "garmin"},
                   message="Fichier santé absent : le créer (squelette `health`) avec la pesée Garmin.")
        return out
    if current is None:
        out.update(action="write", set={"weight_kg": garmin_kg, "weight_origin": "garmin"},
                   message="Pesée Garmin écrite.")
        return out
    if origin == "garmin":
        if _same(current, garmin_kg):
            out.update(action="unchanged", message="Pesée Garmin déjà écrite.")
        else:
            out.update(action="update", set={"weight_kg": garmin_kg},
                       message="Pesée Garmin du jour corrigée dans Garmin Connect : valeur mise à jour.")
        return out
    # Valeur de l'athlète (`chat`, ou clé absente : fichier d'avant #222) : elle prime.
    out["action"] = "keep_athlete"
    gap = _diff(garmin_kg, current)
    if abs(gap) > C.WEIGHT_CONFLICT_KG:
        if _same(_num(data.get("weight_garmin_kg")), garmin_kg):
            out["message"] = "Valeur déclarée conservée ; écart avec Garmin déjà signalé."
        else:
            out["set"] = {"weight_garmin_kg": garmin_kg}
            out["flag"] = {"athlete_kg": current, "garmin_kg": garmin_kg, "diff_kg": gap}
            out["message"] = (f"Valeur déclarée conservée ({current:g} kg) ; Garmin indique {garmin_kg:g} kg "
                              f"(écart {gap:+g} kg) — à signaler une fois à l'athlète.")
    else:
        out["message"] = "Valeur déclarée conservée (écart avec Garmin ≤ 1 kg)."
    return out


def decide_declared(day: str, declared_kg: float, exists: bool, data: Optional[dict]) -> dict:
    """L'athlète déclare son poids : il prime sur une pesée Garmin du même jour."""
    out = {"date": day, "file": f"medical/{day}_health.md", "file_exists": exists,
           "declared_kg": declared_kg, "set": {"weight_kg": declared_kg, "weight_origin": "chat"},
           "remove": [], "flag": None, "action": "declare"}
    if exists and data is None:
        out.update(action="none", set={}, message="Fichier santé sans bloc arc : rien n'est écrit, à corriger d'abord.")
        return out
    data = data or {}
    if not exists:
        out.update(create=True, message="Fichier santé absent : le créer (squelette `health`) avec la valeur déclarée.")
        return out
    current = _num(data.get("weight_kg"))
    garmin_ref = current if data.get("weight_origin") == "garmin" else _num(data.get("weight_garmin_kg"))
    if garmin_ref is not None and abs(_diff(declared_kg, garmin_ref)) > C.WEIGHT_CONFLICT_KG:
        if not _same(_num(data.get("weight_garmin_kg")), garmin_ref):
            out["set"]["weight_garmin_kg"] = garmin_ref
            out["flag"] = {"athlete_kg": declared_kg, "garmin_kg": garmin_ref,
                           "diff_kg": _diff(garmin_ref, declared_kg)}
        out["message"] = (f"Valeur déclarée retenue ({declared_kg:g} kg) ; la pesée Garmin "
                          f"({garmin_ref:g} kg) est gardée dans weight_garmin_kg.")
    else:
        if "weight_garmin_kg" in data:
            out["remove"] = ["weight_garmin_kg"]
        out["message"] = f"Valeur déclarée retenue ({declared_kg:g} kg)."
    return out


def build_plan(payload: dict, workspace: Path) -> dict:
    if not isinstance(payload, dict):
        raise WeightSyncError("entrée : objet JSON attendu")
    declared = payload.get("declared")
    if declared is not None:
        if not isinstance(declared, dict):
            raise WeightSyncError("`declared` : objet {date, weight_kg} attendu")
        day, kg = declared.get("date"), _num(declared.get("weight_kg"))
        if not (isinstance(day, str) and _DATE_RE.match(day)):
            raise WeightSyncError("`declared.date` : AAAA-MM-JJ attendu")
        lo, hi = C.BODY_WEIGHT_KG_PLAUSIBLE
        if kg is None or not lo <= kg <= hi:
            raise WeightSyncError(f"`declared.weight_kg` : poids en kg attendu ({lo:g}-{hi:g})")
        exists, data = read_health(workspace, day)
        return {"days": [decide_declared(day, round(kg, 2), exists, data)], "weighed_by_garmin": [], "warnings": []}
    date = payload.get("date")
    if date is not None and not (isinstance(date, str) and _DATE_RE.match(date)):
        raise WeightSyncError("`date` : AAAA-MM-JJ attendu")
    weights, warnings, covered = parse_garmin(payload.get("garmin"), date)
    if not covered:
        raise WeightSyncError("aucune date déductible de la réponse : passer `date`")
    existing_only = bool(payload.get("existing_only"))
    days = []
    for day in covered:
        exists, data = read_health(workspace, day)
        days.append(decide_garmin(day, weights.get(day), exists, data, existing_only))
    return {"days": days, "weighed_by_garmin": sorted(weights), "warnings": warnings}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _workspace(arg) -> Path:
    try:
        from coach_setup import workspace_root
        return workspace_root(arg)
    except Exception:
        return Path(arg or ".").resolve()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("plan", help="décide quoi écrire dans les fichiers santé")
    p.add_argument("--workspace", default=None, help="Racine du workspace (défaut : résolution standard)")
    p.add_argument("--input", type=Path, default=None, help="Fichier JSON d'entrée (défaut : stdin)")
    p.add_argument("--garmin", default=None, help="Réponse brute de get_daily_weigh_ins/get_weigh_ins")
    p.add_argument("--date", default=None, help="Date de la pesée demandée (AAAA-MM-JJ)")
    p.add_argument("--existing-only", action="store_true", help="Rattrapage : ne jamais créer de fichier")
    p.add_argument("--declared-kg", type=float, default=None, help="Poids déclaré par l'athlète (avec --date)")
    args = parser.parse_args(argv)
    try:
        if args.declared_kg is not None:
            payload = {"declared": {"date": args.date, "weight_kg": args.declared_kg}}
        elif args.garmin is not None:
            payload = {"garmin": args.garmin, "date": args.date, "existing_only": args.existing_only}
        else:
            raw = args.input.read_text(encoding="utf-8") if args.input else sys.stdin.read()
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                # Texte brut de l'outil (« No weight measurements found ... ») : réponse Garmin.
                payload = {"garmin": raw}
            if isinstance(payload, dict) and "garmin" not in payload and "declared" not in payload:
                # Réponse brute de get_daily_weigh_ins/get_weigh_ins passée telle quelle (forme
                # `echo '<réponse>' | python3 scripts/arc_weight_sync.py plan`, celle du chat).
                payload = {"garmin": payload}
            if isinstance(payload, dict):
                if args.date and "date" not in payload:
                    payload["date"] = args.date
                if args.existing_only:
                    payload["existing_only"] = True
        result = build_plan(payload, _workspace(args.workspace))
    except (json.JSONDecodeError, WeightSyncError) as exc:
        print(f"ERREUR : {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
