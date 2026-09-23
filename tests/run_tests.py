#!/usr/bin/env python3
"""Point d'entrée de la suite de tests ai-running-coach.

    python3 tests/run_tests.py --tier a     # intégration installateur (sandbox)
    python3 tests/run_tests.py --tier b     # lint prompts & configuration
    python3 tests/run_tests.py --tier c     # évals d'exécution (modèle léger)
    python3 tests/run_tests.py --tier d     # données : contrat, index dérivé, métriques
    python3 tests/run_tests.py --tier all

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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tier", default="abd", help="a, b, c, d, une combinaison (« abd ») ou « all »")
    parser.add_argument("-v", "--verbose", action="count", default=1)
    parser.add_argument("--repeat", type=int, default=None, help="palier C : répétitions par cas")
    parser.add_argument("-k", "--filter", default=None, help="ne garder que les tests dont le nom contient ce motif")
    args = parser.parse_args()

    tiers = list(TIERS) if args.tier == "all" else [t for t in args.tier if t in TIERS]
    if not tiers:
        parser.error(f"palier inconnu : {args.tier!r} (attendu : a, b, c, d, all)")

    if args.repeat is not None:
        os.environ["ARC_EVAL_REPEAT"] = str(args.repeat)

    sys.path.insert(0, str(REPO_ROOT))
    suite = build_suite(tiers)

    if args.filter:
        def keep(test):
            for sub in test:
                if isinstance(sub, unittest.TestSuite):
                    yield from keep(sub)
                elif args.filter in sub.id():
                    yield sub
        suite = unittest.TestSuite(keep(suite))

    print(f"Paliers : {', '.join(f'{t} ({TIERS[t][1]})' for t in tiers)}\n")
    result = unittest.TextTestRunner(verbosity=args.verbose).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
