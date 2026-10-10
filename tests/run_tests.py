#!/usr/bin/env python3
"""Point d'entrée de la suite de tests ai-running-coach.

    python3 tests/run_tests.py --tier a     # intégration installateur (sandbox)
    python3 tests/run_tests.py --tier b     # lint prompts & configuration
    python3 tests/run_tests.py --tier c     # évals d'exécution (modèle léger)
    python3 tests/run_tests.py --tier d     # données : contrat, index dérivé, métriques
    python3 tests/run_tests.py --tier all
    python3 tests/run_tests.py --tier a --shard 2/3   # 2e tiers du palier A (CI parallèle)

Le palier C coûte des jetons et n'est pas déterministe : il est ignoré sauf si
ARC_LLM_TESTS=1 et que le runner est authentifié. Voir tests/README.md.
"""

from __future__ import annotations

import argparse
import os
import sys
import unittest
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
REPO_ROOT = TESTS_DIR.parent

TIERS = {
    "a": ("install", "intégration installateur"),
    "b": ("lint", "lint prompts & configuration"),
    "c": ("evals", "évals d'exécution des prompts"),
    "d": ("data", "données : contrat, index, métriques"),
}


def build_suite(tiers: list) -> unittest.TestSuite:
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    for tier in tiers:
        directory, _ = TIERS[tier]
        path = TESTS_DIR / directory
        if not path.is_dir():
            continue
        suite.addTests(loader.discover(str(path), pattern="test_*.py", top_level_dir=str(REPO_ROOT)))
    return suite


def iter_cases(suite):
    for sub in suite:
        if isinstance(sub, unittest.TestSuite):
            yield from iter_cases(sub)
        else:
            yield sub


def parse_shard(value: str) -> tuple:
    try:
        index, total = (int(part) for part in value.split("/", 1))
    except ValueError:
        raise argparse.ArgumentTypeError(f"attendu I/N (p. ex. 1/3), reçu {value!r}")
    if not 1 <= index <= total:
        raise argparse.ArgumentTypeError(f"I doit être entre 1 et N, reçu {value!r}")
    return index, total


def shard_suite(suite: unittest.TestSuite, index: int, total: int) -> unittest.TestSuite:
    """Garde la part `index`/`total` de la suite, découpée PAR CLASSE (jamais au milieu
    d'une classe : `setUpClass` reste partagé). Répartition déterministe, gloutonne sur
    le nombre de cas pour équilibrer les parts : toutes les parts réunies = la suite."""
    classes: dict = {}
    for case in iter_cases(suite):
        key = f"{type(case).__module__}.{type(case).__qualname__}"
        classes.setdefault(key, []).append(case)
    loads = [0] * total
    buckets: list = [[] for _ in range(total)]
    for key in sorted(classes, key=lambda k: (-len(classes[k]), k)):
        target = loads.index(min(loads))
        loads[target] += len(classes[key])
        buckets[target].extend(classes[key])
    return unittest.TestSuite(buckets[index - 1])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tier", default="abd", help="a, b, c, d, une combinaison (« abd ») ou « all »")
    parser.add_argument("-v", "--verbose", action="count", default=1)
    parser.add_argument("--repeat", type=int, default=None, help="palier C : répétitions par cas")
    parser.add_argument("-k", "--filter", default=None, help="ne garder que les tests dont le nom contient ce motif")
    parser.add_argument("--shard", type=parse_shard, default=None, metavar="I/N",
                        help="ne lancer que la part I sur N (découpage par classe, pour la CI parallèle)")
    args = parser.parse_args()

    tiers = list(TIERS) if args.tier == "all" else [t for t in args.tier if t in TIERS]
    if not tiers:
        parser.error(f"palier inconnu : {args.tier!r} (attendu : a, b, c, d, all)")

    if args.repeat is not None:
        os.environ["ARC_EVAL_REPEAT"] = str(args.repeat)

    # `ARC_STRICT_METRICS=1` (revue de code #46, 4e passe) : la défense en
    # profondeur de `arc_index.compute_metrics` rattrape en PRODUCTION toute
    # exception inattendue d'un calcul dérivé des échantillons (zones, GAP,
    # découplage, VAM) pour ne jamais faire échouer toute l'indexation à cause
    # d'une seule séance — mais un VRAI bug de programmation ne doit jamais
    # disparaître silencieusement dans un test, sous peine de rester invisible
    # jusqu'à ce qu'un athlète le remarque sur son propre tableau de bord. Toute
    # la suite (donc la CI, qui passe uniquement par ce point d'entrée) tourne
    # donc avec ce garde-fou levé ; le seul test qui exerce délibérément le
    # chemin de rattrapage (un détecteur monkeypatché pour lever) désactive la
    # variable explicitement le temps de son propre appel.
    os.environ["ARC_STRICT_METRICS"] = "1"

    sys.path.insert(0, str(REPO_ROOT))
    suite = build_suite(tiers)

    if args.filter:
        suite = unittest.TestSuite(case for case in iter_cases(suite) if args.filter in case.id())

    shard_note = ""
    if args.shard:
        suite = shard_suite(suite, *args.shard)
        shard_note = f" — part {args.shard[0]}/{args.shard[1]} ({suite.countTestCases()} cas)"

    print(f"Paliers : {', '.join(f'{t} ({TIERS[t][1]})' for t in tiers)}{shard_note}\n")
    # Les tests les plus lents en fin de sortie : la seule façon de savoir où part
    # le temps sur un runner CI (le palier A est ~15× plus lent sur macOS).
    runner_opts = {"durations": 25} if sys.version_info >= (3, 12) else {}
    result = unittest.TextTestRunner(verbosity=args.verbose, **runner_opts).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
