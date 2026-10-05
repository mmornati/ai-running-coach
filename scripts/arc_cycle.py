#!/usr/bin/env python3
"""arc_cycle.py — Contexte du cycle menstruel, opt-in strict (#166).

Ce module est le SEUL endroit où la configuration `[health].cycle_tracking`
est interprétée, et où les valeurs de phase/jour sont normalisées. Il ne
calcule aucune décision : le cycle est un CONTEXTE de lecture (bilan matinal,
hydratation, chaleur), jamais une règle automatique ni un diagnostic.

`[health].cycle_tracking` :
  "off"    — défaut. Aucune donnée récupérée, aucun outil exposé, aucune
             mention par les agents.
  "garmin" — la phase est lue sur Garmin Connect (outils `get_menstrual_*` de
             garmin-mcp, activés SEULEMENT dans ce mode par `install.sh`).
  "intervals" — la phase est lue dans le champ wellness `menstrualPhase`
             d'intervals.icu (même appel `icu_get_wellness_for_date` que le bilan
             matinal, aucune installation à refaire).
  "manual" — la phase est déclarée par l'athlète (`/log`).
La casse et les espaces autour de la valeur sont ignorés (« Garmin » = « garmin »,
comme dans `install.sh`). Toute autre valeur (faute de frappe, type erroné) est
traitée comme "off" avec un avertissement : jamais une exception, jamais un mode
actif par accident.

Usage
-----
    python3 scripts/arc_cycle.py mode  [--workspace DIR]
    python3 scripts/arc_cycle.py gap   --last-period YYYY-MM-DD [--today YYYY-MM-DD]

Bibliothèque standard uniquement (CONTRIBUTING.md).
"""

from __future__ import annotations

import argparse
import json
import sys
import unicodedata
from datetime import date
from pathlib import Path
from typing import Dict, Optional

MODES = ("off", "garmin", "intervals", "manual")
DEFAULT_MODE = "off"

# Phases du contrat `arc` (`health.cycle_phase`). Quatre phases, volontairement
# grossières : c'est ce que les sources (Garmin, intervals.icu, déclaration)
# distinguent de façon fiable, et la littérature sur la performance ne permet
# pas davantage de finesse (voir docs/cycle-menstruel.md).
PHASES = ("menstrual", "follicular", "ovulation", "luteal")
SOURCES = ("garmin", "intervals", "manual")

# Valeurs reçues d'une source ou dites par l'athlète → phase du contrat.
# Normalisation : sans accent, minuscules, espaces/tirets/soulignés unifiés.
_PHASE_ALIASES = {
    "menstrual": "menstrual", "menstruation": "menstrual", "period": "menstrual",
    "menstruelle": "menstrual", "regles": "menstrual", "regle": "menstrual",
    "follicular": "follicular", "folliculaire": "follicular",
    "ovulation": "ovulation", "ovulating": "ovulation", "ovulatoire": "ovulation",
    "luteal": "luteal", "luteale": "luteal",
}

CYCLE_DAY_RANGE = (1, 60)

ASSUMPTIONS = {
    "amenorrhea_gap_days": (
        "90 jours sans début de règles documenté : repère indicatif du projet pour "
        "« peut mériter un avis médical », inspiré de la définition usuelle de "
        "l'aménorrhée secondaire (absence de règles depuis environ 3 mois chez une "
        "personne auparavant réglée) — approximation, pas un seuil diagnostique. Le "
        "projet ne pose jamais de diagnostic : il invite à consulter (voir "
        "docs/cycle-menstruel.md)."
    ),
    "cycle_day_range": (
        "Jour de cycle accepté de 1 à 60 : au-delà, la valeur est presque sûrement une "
        "erreur de saisie ; un cycle très long reste possible mais le jour exact n'a "
        "alors plus de sens comme contexte."
    ),
}
AMENORRHEA_GAP_DAYS = 90


def _fold(text: str) -> str:
    nfkd = unicodedata.normalize("NFKD", str(text))
    plain = "".join(c for c in nfkd if not unicodedata.combining(c))
    return " ".join(plain.lower().replace("-", " ").replace("_", " ").split())


def cycle_tracking_mode(config: Dict[str, dict], warn=True) -> str:
    """Résout `[health].cycle_tracking`, jamais en levant : absent, vide ou
    invalide → "off" (avertissement sur stderr dans le seul cas invalide)."""
    raw = (config.get("health") or {}).get("cycle_tracking")
    if raw in (None, ""):
        return DEFAULT_MODE
    if isinstance(raw, str) and raw.strip().lower() in MODES:
        return raw.strip().lower()
    if warn:
        print(f"avertissement : [health].cycle_tracking = {raw!r} hors de {MODES} — "
              f"traité comme « {DEFAULT_MODE} » (aucune donnée de cycle utilisée).", file=sys.stderr)
    return DEFAULT_MODE


def effective_source(mode: str, data_source: str) -> str:
    """Source réellement utilisable pour `mode` compte tenu de `[data].source` :
    "garmin" exige la source Garmin, "intervals" la source intervals.icu ; un mode qui ne
    correspond pas à la source configurée (outil absent) retombe sur "manual" — la phase
    n'est alors connue que si l'athlète la déclare. "off" reste "off"."""
    if mode == "off":
        return "off"
    if mode in ("garmin", "intervals"):
        return mode if mode == (data_source or "garmin") else "manual"
    return "manual"


def normalize_phase(value) -> Optional[str]:
    """Phase du contrat pour une valeur de source ou déclarée, sinon None."""
    if not isinstance(value, str):
        return None
    folded = _fold(value)
    if folded in _PHASE_ALIASES:
        return _PHASE_ALIASES[folded]
    # « phase luteale », « luteal phase », « phase folliculaire »…
    for token in folded.replace("phase", " ").split():
        if token in _PHASE_ALIASES:
            return _PHASE_ALIASES[token]
    return None


def normalize_day(value) -> Optional[int]:
    """Jour de cycle entier dans CYCLE_DAY_RANGE, sinon None (jamais deviné)."""
    if isinstance(value, bool):
        return None
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    if isinstance(value, str):
        text = value.strip()
        if text.lstrip("jJ").isdigit():
            value = int(text.lstrip("jJ"))
    if not isinstance(value, int):
        return None
    lo, hi = CYCLE_DAY_RANGE
    return value if lo <= value <= hi else None


def gap_days(last_period_start: str, today: Optional[str] = None) -> dict:
    """Jours écoulés depuis le dernier début de règles documenté + indicateur."""
    start = date.fromisoformat(last_period_start)
    ref = date.fromisoformat(today) if today else date.today()
    days = (ref - start).days
    if days < 0:
        raise ValueError("le dernier début de règles est dans le futur")
    return {"days_since_last_period": days, "threshold_days": AMENORRHEA_GAP_DAYS,
            "consult_suggested": days >= AMENORRHEA_GAP_DAYS}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_mode = sub.add_parser("mode", help="mode résolu de [health].cycle_tracking")
    p_mode.add_argument("--workspace", default=None, help="Racine du workspace (défaut : résolution standard)")
    p_gap = sub.add_parser("gap", help="jours depuis le dernier début de règles")
    p_gap.add_argument("--last-period", required=True)
    p_gap.add_argument("--today", default=None)
    args = parser.parse_args(argv)
    if args.cmd == "mode":
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import arc_index
        from coach_setup import workspace_root
        print(cycle_tracking_mode(arc_index.load_config(workspace_root(args.workspace))))
        return 0
    try:
        print(json.dumps(gap_days(args.last_period, args.today), ensure_ascii=False))
    except ValueError as exc:
        print(f"ERREUR : {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
