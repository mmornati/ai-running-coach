"""Palier A — instantanés « golden » de l'API JSON du tableau de bord (#28).

Construit un workspace synthétique à date et graine figées (`tests/lib/synthetic.py`),
lance `scripts/arc_serve.py` pour de vrai sur un port libre de la boucle locale
(même infrastructure que `test_dashboard.py` : `Sandbox`, `Server`), interroge
**chaque** route JSON exposée — dérivées de `arc_serve.ROUTES` à l'exécution,
pas d'une liste recopiée à la main, pour qu'une route ajoutée sans golden fasse
échouer la comparaison plutôt que de passer inaperçue — plus quelques appels
paramétrés représentatifs (fenêtre courte, séance précise, rapport précis), et
compare au JSON de `tests/data/golden/dashboard_api_<sport>.json`.

Deux profils (`trail`, `road`) : le coût de générer un deuxième workspace
synthétique est négligeable et les deux empruntent des chemins de code
différents dans `scripts/arc_metrics.py::predictions` (VDOT plat vs. ajusté au
D+).

Régénération volontaire :

    ARC_UPDATE_GOLDEN=1 python3 tests/run_tests.py -k Golden

Budget de taille : le workspace synthétique est volontairement court (40 jours,
~28 séances) — assez pour que `/api/form`, `/api/health` etc. aient une série
non triviale, assez peu pour que les deux fichiers golden pèsent environ 120 Ko
chacun (~240 Ko à eux deux, mesuré et documenté dans `tests/README.md` ;
`/api/health` sans paramètre domine, car sa fenêtre par défaut est fixe — 90
jours, voir `scripts/arc_serve.py::api_health` — indépendante de la taille du
workspace), pas des mégaoctets à relire à chaque revue de diff.
"""

from __future__ import annotations

import copy
import json
import sys
import unittest
import urllib.parse
from pathlib import Path

from tests.install.test_dashboard import Server
from tests.lib.golden import compare, dump_golden, load_golden, update_requested
from tests.lib.sandbox import Sandbox
from tests.lib.synthetic import build

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
GOLDEN_DIR = REPO_ROOT / "tests" / "data" / "golden"

sys.path.insert(0, str(REPO_ROOT / "scripts"))
import arc_serve  # noqa: E402

TODAY = "2026-09-23"
SEED = 12345
DAYS = 40  # cf. docstring : budget de taille du golden


def _endpoint_urls(server: Server) -> dict:
    """{clé lisible et stable → URL réellement interrogée}.

    Les clés simples (`/api/summary`) viennent de `arc_serve.ROUTES` **au moment
    de l'exécution** : si une route y est ajoutée, elle apparaît ici sans
    modification de ce fichier, et échoue faute d'entrée dans le golden (voir
    `TestGoldenDetectsNewRoute` pour la preuve, sans dépendre du vrai serveur).
    Les clés paramétrées utilisent un identifiant symbolique (`{first}`) plutôt
    que l'id/chemin réel : le golden reste lisible même si l'ordre d'insertion
    venait à changer (auquel cas la comparaison le signalerait ailleurs, sur le
    contenu de `/api/activities` ou `/api/reports`).
    """
    urls = {route: route for route in sorted(arc_serve.ROUTES)}
    urls["/api/form?days=14"] = "/api/form?days=14"
    urls["/api/load?weeks=6"] = "/api/load?weeks=6"
    urls["/api/health?days=14"] = "/api/health?days=14"
    urls["/api/nutrition?days=14"] = "/api/nutrition?days=14"
    urls["/api/activities?limit=5"] = "/api/activities?limit=5"

    activities = json.loads(server.get("/api/activities?limit=1")[1]).get("activities", [])
    if activities:
        urls["/api/activity/{first}"] = f"/api/activity/{activities[0]['id']}"

    reports = json.loads(server.get("/api/reports")[1]).get("reports", [])
    if reports:
        quoted = urllib.parse.quote(reports[0]["source_path"], safe="")
        urls["/api/report?path={first}"] = f"/api/report?path={quoted}"

    return urls


def _snapshot(server: Server) -> dict:
    endpoints = {}
    for key, url in _endpoint_urls(server).items():
        status, body, _ = server.get(url)
        endpoints[key] = {"status": status, "body": json.loads(body)}
    return endpoints


class GoldenCase:
    """Un cas par profil sportif — factorisé pour ne pas dupliquer setUp/tearDown.

    N'hérite PAS de `unittest.TestCase` : `TestLoader.loadTestsFromModule` collecte
    toute sous-classe de `TestCase` présente dans le module, préfixe « Test » ou
    non — en hériter directement ferait tourner ce cas une troisième fois avec
    `sport = None` (et écrirait un golden `dashboard_api_None.json`). Les classes
    concrètes ci-dessous combinent ce mixin avec `unittest.TestCase`."""

    sport = None  # posé par les sous-classes

    def setUp(self):
        self.sb = Sandbox().__enter__()
        self.ws = build(self.sb.root / "ws", days=DAYS, sport=self.sport, seed=SEED,
                        today=__import__("datetime").date.fromisoformat(TODAY))
        self.server = Server(self.sb, ["python3", str(self.sb.repo / "scripts/arc_serve.py"),
                                       "--workspace", str(self.ws), "--port", "0", "--today", TODAY])
        self.assertIsNotNone(self.server.url,
                             self.server.proc.stderr.read() if self.server.proc.poll() is not None else "pas d'URL")

    def tearDown(self):
        self.server.stop()
        self.sb.__exit__(None, None, None)

    def golden_path(self) -> Path:
        return GOLDEN_DIR / f"dashboard_api_{self.sport}.json"

    def test_matches_golden(self):
        endpoints = _snapshot(self.server)
        path = self.golden_path()

        if update_requested():
            dump_golden(path, {"_meta": {"today": TODAY, "seed": SEED, "days": DAYS, "sport": self.sport},
                               "endpoints": endpoints})
            self.skipTest(f"ARC_UPDATE_GOLDEN=1 : {path} régénéré, comparaison non effectuée")

        golden = load_golden(path)
        self.assertIsNotNone(
            golden,
            f"{path} absent — lancez `ARC_UPDATE_GOLDEN=1 python3 tests/run_tests.py -k Golden` pour le créer")

        expected_keys = set(golden["endpoints"])
        got_keys = set(endpoints)
        self.assertEqual(expected_keys, got_keys,
                         "routes différentes entre le golden et le serveur (voir tests/README.md) : "
                         f"absentes du golden = {sorted(got_keys - expected_keys)}, "
                         f"absentes de la réponse = {sorted(expected_keys - got_keys)}")

        mismatches = []
        for key in sorted(expected_keys):
            mismatches.extend(f"{key} → {line}" for line in compare(golden["endpoints"][key], endpoints[key]))
        if mismatches:
            self.fail("instantané différent du golden :\n" + "\n".join(mismatches))


class TestGoldenTrail(GoldenCase, unittest.TestCase):
    sport = "trail"


class TestGoldenRoad(GoldenCase, unittest.TestCase):
    sport = "road"


class TestGoldenDetectsNewRoute(unittest.TestCase):
    """Preuve que la suite échoue si une route est ajoutée sans golden — sans
    dépendre d'un vrai serveur ni éditer `scripts/arc_serve.py` : on simule
    juste la réponse qu'aurait donnée `_snapshot()` pour une route inconnue du
    golden, et on vérifie que la logique de comparaison utilisée par
    `test_matches_golden` (mêmes clés, sinon échec explicite) le détecte."""

    def test_unknown_key_fails_key_comparison(self):
        golden_keys = {"/api/summary", "/api/health"}
        got_keys = golden_keys | {"/api/nouvelle-route"}
        self.assertNotEqual(golden_keys, got_keys)
        self.assertEqual(got_keys - golden_keys, {"/api/nouvelle-route"})


class TestGoldenComparatorDetectsMetricChange(unittest.TestCase):
    """Palier A du critère d'acceptation : un changement volontaire d'une
    métrique fait échouer l'instantané. On perturbe une copie d'un instantané
    déjà capturé (pas besoin de production ni de serveur) et on vérifie que
    `compare()` le rapporte avec le chemin JSON, la valeur attendue et obtenue."""

    def test_perturbed_copy_is_reported(self):
        expected = {
            "status": 200,
            "body": {
                "series": [{"date": "2026-09-01", "distance_m": 10000.0, "load": 42.5}],
                "objective": {"race_date": "2026-11-01"},
            },
        }
        got = copy.deepcopy(expected)
        got["body"]["series"][0]["distance_m"] = 12000.0  # métrique modifiée délibérément

        mismatches = compare(expected, got)

        self.assertEqual(len(mismatches), 1, mismatches)
        self.assertIn("series[0].distance_m", mismatches[0])
        self.assertIn("10000", mismatches[0])
        self.assertIn("12000", mismatches[0])

    def test_unperturbed_copy_matches(self):
        expected = {"status": 200, "body": {"a": 1.0000000001, "b": [1, 2, {"c": "x"}]}}
        got = copy.deepcopy(expected)
        got["body"]["a"] = 1.0000000002  # sous la tolérance flottante documentée
        self.assertEqual(compare(expected, got), [])

    def test_ignored_keys_are_not_reported(self):
        expected = {"body": {"generated_at": "2026-01-01T00:00:00Z", "value": 1}}
        got = {"body": {"generated_at": "2099-12-31T23:59:59Z", "value": 1}}
        self.assertEqual(compare(expected, got), [])


if __name__ == "__main__":
    unittest.main()
