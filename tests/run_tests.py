#!/usr/bin/env python3
"""Point d'entrée de la suite de tests ai-running-coach.

    python3 tests/run_tests.py --tier a     # intégration installateur (sandbox)
    python3 tests/run_tests.py --tier b     # lint prompts & configuration
    python3 tests/run_tests.py --tier c     # évals d'exécution (modèle léger)
    python3 tests/run_tests.py --tier d     # données : contrat, index dérivé, métriques
    python3 tests/run_tests.py --tier all
    python3 tests/run_tests.py --tier a --shard 2/3   # 2e tiers du palier A (CI parallèle)
    python3 tests/run_tests.py --tier a --jobs auto   # un processus par cœur disponible

Le palier C coûte des jetons et n'est pas déterministe : il est ignoré sauf si
ARC_LLM_TESTS=1 et que le runner est authentifié. Voir tests/README.md.

Les tests tournent sous le Python de la CI (3.12) : lancé avec un Python plus ancien
(3.10 d'Ubuntu, 3.9 de macOS), ce script se relance sous 3.12 via `uv`, et place un
`python3` 3.12 en tête du PATH pour les scripts que les tests lancent eux-mêmes.
ARC_TESTS_ANY_PYTHON=1 garde le Python courant.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import multiprocessing
import os
import shutil
import subprocess
import sys
import tempfile
import time
import traceback
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


# Python de la CI (.github/workflows/tests.yml) : `tomllib` (3.11+), syntaxe des f-strings
# (3.12) et valeurs flottantes des goldens supposent cette version.
CI_PYTHON = (3, 12)


def find_ci_python() -> str | None:
    """Interpréteur CI_PYTHON trouvé (ou installé) par `uv`, sinon None."""
    uv = shutil.which("uv")
    if not uv:
        return None
    version = ".".join(map(str, CI_PYTHON))
    for cmd in (["python", "find", version], ["python", "install", version]):
        proc = subprocess.run([uv, *cmd], capture_output=True, text=True)
        if proc.returncode == 0:
            break
    else:
        return None
    found = subprocess.run([uv, "python", "find", version], capture_output=True, text=True)
    path = found.stdout.strip()
    return path if found.returncode == 0 and path else None


def python_shim_dir(interpreter: str) -> Path:
    """Dossier où `python3` et `python` pointent sur `interpreter` (réutilisé d'un run à l'autre)."""
    digest = hashlib.sha256(interpreter.encode()).hexdigest()[:12]
    shim = Path(tempfile.gettempdir()) / f"arc-tests-python-{digest}"
    shim.mkdir(exist_ok=True)
    for name in ("python3", "python"):
        link = shim / name
        if not (link.is_symlink() and os.readlink(link) == interpreter):
            if link.is_symlink() or link.exists():
                link.unlink()
            link.symlink_to(interpreter)
    return shim


def ensure_ci_python() -> None:
    """Se relance sous CI_PYTHON si le Python courant est plus ancien (sans effet en CI)."""
    if sys.version_info[:2] >= CI_PYTHON or os.environ.get("ARC_TESTS_ANY_PYTHON") == "1":
        return
    current = ".".join(map(str, sys.version_info[:3]))
    if os.environ.get("ARC_TESTS_REEXEC") == "1":
        return  # déjà relancé : ne jamais boucler
    interpreter = find_ci_python()
    wanted = ".".join(map(str, CI_PYTHON))
    if not interpreter:
        print(f"⚠ Python {current} : les tests attendent Python {wanted} (CI). Installez uv "
              f"(https://docs.astral.sh/uv/) ou lancez-les avec python{wanted} — des erreurs "
              "tomllib/f-string sont attendues avec ce Python.\n", file=sys.stderr)
        return
    env = dict(os.environ, ARC_TESTS_REEXEC="1",
               PATH=f"{python_shim_dir(interpreter)}{os.pathsep}{os.environ.get('PATH', '')}")
    print(f"Python {current} → relance sous {interpreter} (Python de la CI)\n", file=sys.stderr)
    sys.stderr.flush()
    os.execve(interpreter, [interpreter, str(Path(__file__).resolve()), *sys.argv[1:]], env)


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


def cases_by_class(suite: unittest.TestSuite) -> dict:
    classes: dict = {}
    for case in iter_cases(suite):
        key = f"{type(case).__module__}.{type(case).__qualname__}"
        classes.setdefault(key, []).append(case)
    return classes


def shard_suite(suite: unittest.TestSuite, index: int, total: int) -> unittest.TestSuite:
    """Garde la part `index`/`total` de la suite, découpée PAR CLASSE (jamais au milieu
    d'une classe : `setUpClass` reste partagé). Répartition déterministe, gloutonne sur
    le nombre de cas pour équilibrer les parts : toutes les parts réunies = la suite."""
    classes = cases_by_class(suite)
    loads = [0] * total
    buckets: list = [[] for _ in range(total)]
    for key in sorted(classes, key=lambda k: (-len(classes[k]), k)):
        target = loads.index(min(loads))
        loads[target] += len(classes[key])
        buckets[target].extend(classes[key])
    return unittest.TestSuite(buckets[index - 1])


def parse_jobs(value: str) -> int:
    if value == "auto":
        if hasattr(os, "sched_getaffinity"):
            return len(os.sched_getaffinity(0)) or 1
        return os.cpu_count() or 1
    try:
        jobs = int(value)
    except ValueError:
        jobs = 0
    if jobs < 1:
        raise argparse.ArgumentTypeError(f"attendu un entier >= 1 ou « auto », reçu {value!r}")
    return jobs


def run_class_in_worker(test_ids: list) -> dict:
    """Lance une classe dans un processus de travail, sortie capturée au niveau des
    descripteurs (les sous-processus des tests y écrivent aussi) : les classes ne se
    mélangent pas dans le journal, et seule celle qui échoue l'encombre."""
    sys.stdout.flush()
    sys.stderr.flush()
    saved = os.dup(1), os.dup(2)
    with tempfile.TemporaryFile() as sink:
        os.dup2(sink.fileno(), 1)
        os.dup2(sink.fileno(), 2)
        try:
            suite = unittest.defaultTestLoader.loadTestsFromNames(test_ids)
            # Un nom qui se charge en un autre nombre de cas ferait disparaître des tests.
            if suite.countTestCases() != len(test_ids):
                raise RuntimeError(f"{len(test_ids)} cas attendus, {suite.countTestCases()} chargés")
            result = unittest.TextTestRunner(stream=sys.stderr, verbosity=1).run(suite)
        finally:
            sys.stdout.flush()
            sys.stderr.flush()
            os.dup2(saved[0], 1)
            os.dup2(saved[1], 2)
            os.close(saved[0])
            os.close(saved[1])
        sink.seek(0)
        output = sink.read().decode("utf-8", errors="replace")
    return {
        "ok": result.wasSuccessful(),
        "tests": result.testsRun,
        "failures": len(result.failures) + len(result.unexpectedSuccesses),
        "errors": len(result.errors),
        "skipped": len(result.skipped),
        "durations": getattr(result, "collectedDurations", []),
        "output": output,
    }


def run_parallel(suite: unittest.TestSuite, jobs: int) -> bool:
    """Répartit les classes de `suite` sur `jobs` processus, en file partagée : chacun prend
    la classe suivante quand il a fini, ce qui absorbe sans réglage l'écart de durée entre
    classes et le bruit des runners. Jamais au milieu d'une classe (`setUpClass` partagé)."""
    started = time.perf_counter()
    classes = cases_by_class(suite)
    totals = {"tests": 0, "failures": 0, "errors": 0, "skipped": 0}
    durations: list = []
    reports: list = []

    # Un module qui ne s'importe pas n'existe que comme cas synthétique de `unittest`, sans
    # nom rechargeable : il est joué ici, pour qu'il compte comme un échec et non un oubli.
    unloadable = [key for key in classes if key.startswith("unittest.")]
    for key in unloadable:
        inline = unittest.TextTestRunner(stream=sys.stdout, verbosity=1).run(unittest.TestSuite(classes.pop(key)))
        totals["tests"] += inline.testsRun
        totals["failures"] += len(inline.failures) + len(inline.unexpectedSuccesses)
        totals["errors"] += len(inline.errors)
        totals["skipped"] += len(inline.skipped)

    workers = min(jobs, len(classes)) or 1
    print(f"Parallèle : {workers} processus, {len(classes)} classes\n", flush=True)
    # Les plus grosses d'abord : les petites comblent ensuite les trous.
    ordered = sorted(classes, key=lambda k: (-len(classes[k]), k))
    # `spawn` partout : le même comportement sur Linux et macOS, sans hériter de l'état du parent.
    context = multiprocessing.get_context("spawn")
    with concurrent.futures.ProcessPoolExecutor(max_workers=workers, mp_context=context) as pool:
        pending = {pool.submit(run_class_in_worker, [c.id() for c in classes[key]]): key for key in ordered}
        for future in concurrent.futures.as_completed(pending):
            key = pending[future]
            try:
                report = future.result()
            except Exception:  # processus mort (BrokenProcessPool) ou chargement impossible
                report = {"ok": False, "tests": 0, "failures": 0, "errors": 1, "skipped": 0, "durations": [],
                          "output": traceback.format_exc()}
            for field in totals:
                totals[field] += report[field]
            durations.extend(report["durations"])
            if not report["ok"]:
                reports.append((key, report["output"]))
            print("." if report["ok"] else "F", end="", flush=True)
    print()

    for key, output in sorted(reports):
        print(f"\n{'=' * 70}\nÉCHEC : {key}\n{'=' * 70}\n{output}", flush=True)
    if durations:
        print("\nSlowest test durations\n" + "-" * 70)
        for name, seconds in sorted(durations, key=lambda d: -d[1])[:25]:
            print(f"{seconds:.3f}s     {name}")
    print(f"\n{'-' * 70}\nRan {totals['tests']} tests in {time.perf_counter() - started:.3f}s\n")
    success = not (totals["failures"] or totals["errors"])
    details = [f"{name}={totals[name]}" for name in ("failures", "errors", "skipped") if totals[name]]
    print(("OK" if success else "FAILED") + (f" ({', '.join(details)})" if details else ""), flush=True)
    return success


def main() -> int:
    ensure_ci_python()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tier", default="abd", help="a, b, c, d, une combinaison (« abd ») ou « all »")
    parser.add_argument("-v", "--verbose", action="count", default=1)
    parser.add_argument("--repeat", type=int, default=None, help="palier C : répétitions par cas")
    parser.add_argument("-k", "--filter", default=None, help="ne garder que les tests dont le nom contient ce motif")
    parser.add_argument("--shard", type=parse_shard, default=None, metavar="I/N",
                        help="ne lancer que la part I sur N (découpage par classe, pour la CI parallèle)")
    parser.add_argument("--jobs", type=parse_jobs, default=1, metavar="N|auto",
                        help="lancer les classes sur N processus (« auto » : un par cœur disponible)")
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
    # Le palier C dépense des jetons et se répète : jamais en parallèle.
    if args.jobs > 1 and "c" in tiers:
        print("--jobs ignoré : le palier C reste séquentiel.\n")
    elif args.jobs > 1:
        return 0 if run_parallel(suite, args.jobs) else 1

    # Les tests les plus lents en fin de sortie : la seule façon de savoir où part
    # le temps sur un runner CI (le palier A est ~15× plus lent sur macOS).
    runner_opts = {"durations": 25} if sys.version_info >= (3, 12) else {}
    result = unittest.TextTestRunner(verbosity=args.verbose, **runner_opts).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
