#!/usr/bin/env python3
"""Sommeil COROS — réponse texte de `querySleepOverview` -> clés `sleep_*` du bloc `arc`.

## Pourquoi

Le MCP officiel de COROS rend le sommeil en texte formaté, daté par le **jour du
réveil**. Ce module fait la lecture et l'arithmétique que le modèle ne doit jamais
faire de tête, et applique deux règles relevées sur une nuit réelle (2026-10-24) :

- **Sommeil principal seulement.** `sleep_total_s` = « Main Sleep (asleep) » ; les
  siestes (« Daily Sleep (incl. naps) ») ne sont jamais additionnées.
- **Nuit coupée.** COROS peut couper une nuit continue en « sommeil principal » +
  « sieste » (constaté : un réveil de la personne à côté vers 9 h 40, l'athlète,
  lui, a dormi d'une traite ; la série HRV n'avait aucun trou). Une sieste qui
  commence moins de `SPLIT_GAP_MAX_S` après la fin du sommeil principal lève
  `split_suspected` : l'agent donne les deux morceaux et demande, ne corrige rien
  seul ; la déclaration de l'athlète prime. Un sommeil court issu d'un découpage
  douteux ne fait jamais passer un verdict à l'orange ou au rouge à lui seul.

Les ratios de phases (profond, léger, paradoxal, éveil) sont recopiés tels quels
dans `stage_ratios` mais jamais convertis en secondes : COROS les annonce sur la
portée « daily » (`Sleep metrics scope`), sans dire s'ils couvrent la sieste —
`sleep_deep_s`… restent donc omis plutôt qu'approchés.

`Sleep Score: 0` + « not available yet » = nuit pas encore calculée (la première
nuit avec une nouvelle montre n'est jamais publiée) : `available` vaut `false`,
aucune clé `sleep_*`.

## Usage

    python3 scripts/arc_coros_sleep.py --date 2026-10-24 [--tz Europe/Paris] < reponse.txt

La réponse brute du MCP (texte, ou chaîne JSON encodée telle que le relais la rend)
est lue sur l'entrée standard ; sortie JSON. Code 1 si la date est absente de la
réponse. Aucune dépendance hors bibliothèque standard, aucun appel réseau.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from typing import List, Optional, Sequence

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover - Python < 3.9
    ZoneInfo = None  # type: ignore[assignment]

# Écart maximal entre la fin du sommeil principal et le début d'une sieste pour
# soupçonner une nuit coupée par COROS (approximation du projet : 1 h 52 constaté).
SPLIT_GAP_MAX_S = 3 * 3600

_DAY_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})\s*$", re.M)
_DUR_RE = r"(?:(\d+)h)?\s*(?:(\d+)\s*min)?"
_WINDOW_RE = r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2})\s*-\s*(\d{4}-\d{2}-\d{2} \d{2}:\d{2})"


def _plain(raw: str) -> str:
    """Le relais rend parfois le texte sous forme de chaîne JSON encodée."""
    raw = raw.strip()
    if raw.startswith('"'):
        try:
            value = json.loads(raw)
            if isinstance(value, str):
                return value
        except ValueError:
            pass
    return raw


def _block(text: str, day: str) -> Optional[str]:
    """Le paragraphe d'un jour (du titre `AAAA-MM-JJ` au jour suivant)."""
    marks = list(_DAY_RE.finditer(text))
    for i, m in enumerate(marks):
        if m.group(1) == day:
            end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
            return text[m.end():end]
    return None


def _duration_s(block: str, label: str) -> Optional[int]:
    m = re.search(re.escape(label) + r":\s*" + _DUR_RE + r"\s*(?:\(.*\))?\s*$", block, re.M)
    if not m or not (m.group(1) or m.group(2)):
        return None
    return int(m.group(1) or 0) * 3600 + int(m.group(2) or 0) * 60


def _windows(block: str, label: str) -> List[tuple]:
    return re.findall(re.escape(label) + r":\s*" + _WINDOW_RE, block)


def _stamp(local: str, tz: Optional[str]) -> datetime:
    dt = datetime.strptime(local, "%Y-%m-%d %H:%M")
    if tz and ZoneInfo is not None:
        return dt.replace(tzinfo=ZoneInfo(tz))
    return dt.astimezone()  # fuseau de la machine, comme l'heure COROS du compte


def parse_sleep(raw: str, day: str, tz: Optional[str] = None) -> Optional[dict]:
    """Nuit du jour de réveil `day` (AAAA-MM-JJ) ; `None` si le jour est absent."""
    block = _block(_plain(raw), day)
    if block is None:
        return None
    score_m = re.search(r"Sleep Score:\s*(\d+)", block)
    score = int(score_m.group(1)) if score_m else 0
    main_s = _duration_s(block, "Main Sleep (asleep)")
    if not score and main_s is None:
        return {"date": day, "available": False, "arc": {},
                "reason": "nuit pas encore calculée par COROS (Sleep Score: 0)"}

    arc: dict = {}
    if main_s is not None:
        arc["sleep_total_s"] = main_s
    main_win = _windows(block, "Main Sleep Window")
    main_end = None
    if main_win:
        start, end = (_stamp(v, tz) for v in main_win[0])
        arc["sleep_start"], arc["sleep_end"] = start.isoformat(), end.isoformat()
        main_end = end
    if score:
        arc["provider_scores"] = [{"category": "sleep", "provider": "coros", "value": score,
                                   "scale_min": 0, "scale_max": 100}]

    naps = []
    for start_txt, end_txt in _windows(block, "Nap Window"):
        start, end = _stamp(start_txt, tz), _stamp(end_txt, tz)
        naps.append({"start": start.isoformat(), "end": end.isoformat(),
                     "gap_after_main_s": int((start - main_end).total_seconds()) if main_end else None})
    ratios = {}
    for key, label in (("deep", "Deep Sleep Ratio"), ("light", "Light Sleep Ratio"),
                       ("rem", "REM Ratio"), ("awake", "Awake Ratio")):
        m = re.search(re.escape(label) + r":\s*(\d+)%", block)
        if m:
            ratios[key] = int(m.group(1)) / 100
    scope = re.search(r"Sleep metrics scope:\s*(\w+)", block)

    split = next((n for n in naps if n["gap_after_main_s"] is not None
                  and 0 <= n["gap_after_main_s"] <= SPLIT_GAP_MAX_S), None)
    return {
        "date": day, "available": True, "arc": arc,
        "naps": naps, "naps_asleep_s": _duration_s(block, "Naps Total (asleep)"),
        "daily_asleep_s": _duration_s(block, "Daily Sleep"),
        "stage_ratios": ratios, "stage_scope": scope.group(1) if scope else None,
        "split_suspected": split is not None,
        "split": split,
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--date", required=True, help="jour du réveil, AAAA-MM-JJ")
    ap.add_argument("--tz", help="fuseau IANA du compte COROS (défaut : celui de la machine)")
    args = ap.parse_args(argv)
    result = parse_sleep(sys.stdin.read(), args.date, args.tz)
    if result is None:
        print(json.dumps({"date": args.date, "error": "jour absent de la réponse"}, ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
