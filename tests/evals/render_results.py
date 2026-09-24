#!/usr/bin/env python3
"""Rend `tests/evals/RESULTS.md` depuis le JSON écrit par `runner.record_result` (#29).

Le palier C lui-même reste un `unittest` classique (pas de sortie machine par
défaut) : quand la CI règle `ARC_EVAL_RESULTS_OUT`, chaque cas y ajoute son
taux de réussite (voir `runner.record_result`). Ce script relit ce JSON et
produit le même tableau Markdown que celui, versionné à la main, de
`tests/evals/RESULTS.md` — pour que le workflow `Évals` (#29) puisse joindre
un relevé à jour en artefact et en commentaire de PR sans jamais committer à
la place d'un mainteneur.

Aucune dépendance : stdlib pure, déterministe à métadonnées égales — c'est ce
qui permet de le verrouiller au palier D (`tests/data/test_render_results.py`)
sans lancer le moindre modèle.

    python3 tests/evals/render_results.py --results /tmp/eval-results.json \\
        --previous tests/evals/RESULTS.md --out /tmp/RESULTS.md
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent.parent
REPO = TESTS_DIR.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

# Une ligne de tableau du RESULTS.md existant : `| `id` | 3/3 | ✅ |`. Le
# « Verdict » n'est jamais reparsé pour la régression — seul le ratio
# Réussites/Répétitions compte, le symbole est une représentation, pas la donnée.
_ROW_RE = re.compile(r"^\|\s*`([a-z0-9_-]+)`\s*\|\s*([^|]+?)\s*\|\s*[^|]+?\s*\|\s*$")
_FRACTION_RE = re.compile(r"^(\d+)\s*/\s*(\d+)$")


def parse_previous(markdown: str) -> dict:
    """Extrait `{case_id: taux_de_réussite}` d'un RESULTS.md déjà rendu.

    Un « — » (cas jamais exécuté) ou une ligne qui ne correspond pas au motif
    attendu est simplement absent du résultat : ni erreur, ni régression
    détectable faute de point de comparaison.
    """
    previous = {}
    for raw_line in markdown.splitlines():
        match = _ROW_RE.match(raw_line.strip())
        if not match:
            continue
        case_id, reussites = match.groups()
        fraction = _FRACTION_RE.match(reussites.strip())
        if not fraction:
            continue
        passed, attempts = int(fraction.group(1)), int(fraction.group(2))
        if attempts:
            previous[case_id] = passed / attempts
    return previous


def _min_passes(threshold: float, repeat: int) -> int:
    """`2/3` plutôt que `0.667` dans l'en-tête — lisible par un non-développeur."""
    return math.ceil(threshold * repeat - 1e-9)


def render(results: dict, case_ids: list, meta: dict, previous: dict | None = None) -> str:
    """Rend le Markdown complet. Pur : aucune I/O, ce qui le rend testable au palier D."""
    previous = previous or {}
    repeat, threshold = int(meta["repeat"]), float(meta["threshold"])
    lines = [
        "# Résultats du palier C",
        "",
        "Dernier relevé des évals d'exécution. **Versionné volontairement** : une",
        "régression de comportement se lit alors dans un diff de PR, pas dans la couleur",
        "d'un job qui a déjà défilé.",
        "",
        "Régénérer :",
        "",
        "```bash",
        "ARC_LLM_TESTS=1 python3 tests/run_tests.py --tier c --repeat 3",
        "```",
        "",
        "## Dernier relevé",
        "",
        "| | |",
        "|---|---|",
        f"| **Date** | {meta['date']} |",
        f"| **Modèle** | `{meta['model']}` |",
        f"| **Runner** | `{meta.get('runner', 'claude -p')}` |",
        f"| **Répétitions** | {repeat} par scénario |",
        f"| **Seuil de réussite** | {_min_passes(threshold, repeat)}/{repeat} |",
        "",
        "| Scénario | Réussites | Verdict |",
        "|---|---|---|",
    ]

    any_result = False
    for case_id in case_ids:
        entry = results.get(case_id)
        if entry is None:
            lines.append(f"| `{case_id}` | — | — |")
            continue
        any_result = True
        passed, attempts, rate = entry["passed"], entry["attempts"], entry["rate"]
        verdict = "✅" if rate >= threshold else "❌"
        prev_rate = previous.get(case_id)
        if prev_rate is not None and rate < prev_rate:
            verdict += " ⚠️ régression"
        lines.append(f"| `{case_id}` | {passed}/{attempts} | {verdict} |")

    lines.append("")
    if not any_result:
        lines.extend([
            "> **Pas encore de relevé.** Le harnais est complet et validé — scénarios,",
            "> fixtures, serveur MCP factice, journal des appels d'outils — mais aucune",
            "> exécution réelle n'a encore eu lieu : cela demande un runner authentifié.",
            "> Lancez la commande ci-dessus, ou le workflow `Évals` depuis l'onglet Actions,",
            "> puis remplacez ce tableau par le relevé obtenu.",
            "",
        ])
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--results", type=Path, required=True, help="JSON écrit par ARC_EVAL_RESULTS_OUT")
    parser.add_argument("--previous", type=Path, help="RESULTS.md existant, pour détecter une régression")
    parser.add_argument("--out", type=Path, help="fichier de sortie (défaut : stdout)")
    parser.add_argument("--model", default=None)
    parser.add_argument("--runner", default="claude -p")
    parser.add_argument("--repeat", type=int, default=None)
    parser.add_argument("--threshold", type=float, default=None)
    args = parser.parse_args(argv)

    from tests.evals import runner as evals_runner

    data = {}
    if args.results.exists():
        try:
            data = json.loads(args.results.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            parser.error(f"{args.results} : JSON invalide : {exc}")
    saved_meta = data.get("_meta", {})
    results = {k: v for k, v in data.items() if k != "_meta"}

    meta = {
        "date": saved_meta.get("date") or datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "model": args.model or saved_meta.get("model") or evals_runner.model(),
        "runner": args.runner,
        "repeat": args.repeat or saved_meta.get("repeat") or evals_runner.repeat(),
        "threshold": args.threshold if args.threshold is not None else saved_meta.get("threshold", evals_runner.threshold()),
    }

    case_ids = [case["id"] for case in evals_runner.load_cases()]

    previous = {}
    if args.previous and args.previous.exists():
        previous = parse_previous(args.previous.read_text(encoding="utf-8"))

    text = render(results, case_ids, meta, previous)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
