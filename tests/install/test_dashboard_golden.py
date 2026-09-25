"""Palier A — instantanés « golden » de l'API JSON du tableau de bord (#28).

Construit un workspace synthétique à date et graine figées (`tests/lib/synthetic.py`),
lance `scripts/arc_serve.py` pour de vrai sur un port libre de la boucle locale
(même infrastructure que `test_dashboard.py` : `Sandbox`, `Server`), interroge
les routes JSON de `arc_serve.ROUTES` — dérivées à l'exécution, pas d'une liste
recopiée à la main, pour qu'une route ajoutée à `ROUTES` sans golden fasse
échouer la comparaison plutôt que de passer inaperçue (preuve dans
`TestGoldenDetectsNewRoute`, avec un vrai serveur) — plus la route paramétrée
`/api/activity/<id>` (routée à part, par une expression régulière dans
`Handler._api`, donc **hors** de `ROUTES` : elle est ajoutée ici explicitement,
faute de pouvoir l'énumérer sans dupliquer cette regex), quelques appels
paramétrés représentatifs (fenêtre courte, un rapport précis), et compare au
JSON de `tests/data/golden/dashboard_api_<sport>.json`.

Deux profils (`trail`, `road`) : le coût de générer un deuxième workspace
synthétique est négligeable et les deux empruntent des chemins de code
différents dans `scripts/arc_metrics.py::predictions` (VDOT plat vs. ajusté au
D+).

Régénération volontaire :

    ARC_UPDATE_GOLDEN=1 python3 tests/run_tests.py -k Golden

Budget de taille : le workspace synthétique est volontairement court (40 jours,
~28 séances) — assez pour que `/api/form`, `/api/health` etc. aient une série
non triviale, assez peu pour que les deux fichiers golden pèsent environ 120 Ko
chacun (~240 Ko à eux deux, mesuré et documenté dans `tests/README.md`).
`/api/health` sans paramètre (fenêtre par défaut fixe de 90 jours, indépendante
de la taille du workspace — voir `scripts/arc_serve.py::api_health`) en
représente à lui seul environ 28 % ; ce n'est pas la majorité du volume, mais
c'est de loin la plus grosse route individuelle.
"""

from __future__ import annotations

import copy
import datetime
import json
import re
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



# Durée totale des échantillons FIT figés, en secondes. Étendue de 1800 s (30 min)
# à 3900 s (65 min) pour #45 (revue de code) : le découplage aérobie exige au
# moins `arc_decoupling.MIN_MOVING_DURATION_S` (60 min) de mouvement, sous peine
# de rester `null` (inéligible) partout dans le golden — ce chemin de calcul
# (découplage/EF réellement mesurés) ne serait alors jamais verrouillé. 3900 s
# laisse une marge confortable au-delà du seuil (échauffement de 10 min +
# 2 × 10 min minimum par moitié, voir `arc_decoupling.ASSUMPTIONS`).
FIXED_FIT_DURATION_S = 3900

# Frontière des deux moitiés du découplage (#45) : échauffement de
# `arc_decoupling.WARMUP_S` (600 s) exclu EN PREMIER, PUIS le reste
# (600 -> FIXED_FIT_DURATION_S) partagé en deux moitiés ÉGALES de temps de
# mouvement (protocole standard, voir `arc_decoupling.ASSUMPTIONS["warmup"]`) —
# ce fixture est plat en vitesse (2,7 m/s constante, aucun arrêt), donc le
# temps de mouvement coïncide avec le temps écoulé et cette frontière peut être
# calculée à l'avance : 600 + (3900 - 600) / 2 = 2250 s.
_HALF_BOUNDARY_S = 600 + (FIXED_FIT_DURATION_S - 600) / 2.0


def _fixed_altitude_m(t: int) -> float:
    """Profil d'altitude déterministe : DEUX collines identiques (montée puis
    descente symétriques, 30 m de dénivelé chacune), une entièrement dans
    chaque moitié du découplage (#45, revue de code — voir `_HALF_BOUNDARY_S`)
    — jamais une seule colline qui traverserait la frontière des deux moitiés
    (un profil asymétrique entre les deux moitiés, ex. montée dans l'une,
    descente dans l'autre, biaiserait le découplage mesuré par le relief plutôt
    que par la vraie dérive de FC imposée, voir `arc_decoupling.ASSUMPTIONS
    ["grade_asymmetry"]" — c'est exactement le bug que verrouillait, à tort,
    l'ancien profil « montée/plateau/descente » unique). Plat (0 m) pendant
    l'échauffement (0-600 s, hors calcul de découplage). Assez de dénivelé
    pour que le GAP diverge visiblement de l'allure brute et verrouille un
    chemin de calcul non trivial dans le golden (#44), sans changer le reste
    du fichier (cadence, distance) verrouillé par #43."""
    if t < 600:
        return 0.0
    half_len = (FIXED_FIT_DURATION_S - 600) / 2.0  # 1650 s
    quarter = half_len / 2.0  # 825 s : montée puis descente, à l'intérieur d'une seule moitié
    offset = (t - 600) % half_len
    if offset < quarter:
        return round(30.0 * (offset / quarter), 2)
    return round(30.0 * (1 - (offset - quarter) / quarter), 2)


def _fixed_hr_bpm(t: int) -> float:
    """FC déterministe : 150 bpm sur la première moitié du découplage (#45),
    155 bpm sur la seconde — une dérive fixe et modeste (+3,3 %, découplage
    théorique en séance plate : 1 - 150/155 ≈ 3,23 %), assez pour verrouiller
    un découplage aérobie mesuré NON NUL dans le golden (la FC constante à
    150 bpm sur toute la séance, suffisante pour #43/#44, aurait verrouillé un
    découplage nul partout, jamais le chemin de calcul de la dérive
    elle-même). La frontière est `_HALF_BOUNDARY_S` (2250 s), PAS le milieu de
    `FIXED_FIT_DURATION_S` (1950 s) : elle doit coïncider avec la frontière
    RÉELLEMENT utilisée par `arc_decoupling` (échauffement exclu D'ABORD, puis
    partage en deux moitiés égales du reste, voir `_HALF_BOUNDARY_S`), sinon
    la valeur verrouillée dériverait du 3,23 % théorique pour une raison
    différente de la dérive de FC elle-même."""
    return 150.0 if t < _HALF_BOUNDARY_S else 155.0


def _write_fixed_fit_samples(ws: Path, today: str) -> None:
    """Écrit `activities/fit/<garmin_activity_id>.json` À LA MAIN (jamais le
    générateur aléatoire `tests.lib.synthetic.sample_session`) pour l'activité datée
    `today` du workspace golden (#43, revue de code, nit) : sans ce fichier, AUCUNE
    activité du workspace synthétique n'a d'échantillon FIT ingéré, donc
    `hr_zones`/`polarisation_weeks` restent `null` PARTOUT dans le golden — ce chemin
    (bornes connues + temps en zone/polarisation réellement calculés) ne serait donc
    jamais verrouillé par la comparaison golden. `FIXED_FIT_DURATION_S` (65 min) à
    5 s de résolution : entièrement déterministe, sans tirage `rng`. Altitude en deux
    collines symétriques, une par moitié du découplage (`_fixed_altitude_m`, #44/#45) :
    sans dénivelé, le GAP calculé serait toujours strictement égal à l'allure brute, ce
    qui ne verrouillerait jamais le chemin de calcul de la pente ; un profil asymétrique
    entre les deux moitiés verrouillerait à tort un découplage biaisé par le relief (bug
    de revue de code #45, voir `_fixed_altitude_m`). FC en palier 150 -> 155 bpm à la
    frontière des deux moitiés (`_fixed_hr_bpm`, #45) : verrouille un découplage
    aérobie/EF mesurés NON NULS et proches de la dérive théorique (3,23 %). Le
    `garmin_activity_id` est LU dans le fichier Markdown de l'activité (jamais codé en
    dur) : il reste correct même si le générateur venait à changer sa façon de les
    attribuer."""
    matches = sorted((ws / "activities").glob(f"{today}_*.md"))
    if not matches:
        raise AssertionError(f"aucune activité datée {today} dans le workspace golden — "
                             "`_write_fixed_fit_samples` doit être ajustée")
    text = matches[0].read_text(encoding="utf-8")
    match = re.search(r'"garmin_activity_id":\s*(\d+)', text)
    if not match:
        raise AssertionError(f"garmin_activity_id introuvable dans {matches[0]}")
    garmin_id = int(match.group(1))
    records = [
        {"t_s": t, "distance_m": round(t * 2.7, 2), "altitude_m": _fixed_altitude_m(t),
         "hr_bpm": _fixed_hr_bpm(t), "speed_ms": 2.7, "cadence_spm": 172.0}
        for t in range(0, FIXED_FIT_DURATION_S, 5)
    ]
    fit_dir = ws / "activities/fit"
    fit_dir.mkdir(parents=True, exist_ok=True)
    (fit_dir / f"{garmin_id}.json").write_text(
        json.dumps({"activity_id": garmin_id, "records": records}), encoding="utf-8")


def _endpoint_urls(server: Server) -> dict:
    """{clé lisible et stable → URL réellement interrogée}.

    Les clés simples (`/api/summary`) viennent de `arc_serve.ROUTES` **au moment
    de l'exécution** : si une route y est ajoutée, elle apparaît ici sans
    modification de ce fichier. Les clés paramétrées utilisent un identifiant
    symbolique (`{first}`) plutôt que l'id/chemin réel : le golden reste
    lisible même si l'ordre d'insertion venait à changer (auquel cas la
    comparaison le signalerait ailleurs, sur le contenu de `/api/activities`
    ou `/api/reports`).
    """
    urls = {route: route for route in sorted(arc_serve.ROUTES)}
    urls["/api/form?days=14"] = "/api/form?days=14"
    urls["/api/load?weeks=6"] = "/api/load?weeks=6"
    urls["/api/health?days=14"] = "/api/health?days=14"
    # `days=3` (et non `days=14`, qui produit la même fenêtre que le défaut :
    # `synthetic.build` n'écrit de la nutrition que sur les 13 derniers jours,
    # donc toute borne ≥ 14 capture les mêmes lignes) — `_days()` remonte tout
    # de même le plancher à 7 (`scripts/arc_serve.py::_days`), ce qui suffit à
    # exclure quelques lignes par rapport au défaut (60 j) et à prouver que le
    # paramètre est bien pris en compte.
    urls["/api/nutrition?days=3"] = "/api/nutrition?days=3"
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


def _check_route_coverage(expected_keys: set, got_keys: set) -> list:
    """Compare les deux ensembles de clés (golden vs. instantané) et rend une
    liste d'erreurs (vide si identiques). Factorisé pour être exercé
    directement par `TestGoldenDetectsNewRoute`, sans dupliquer la logique
    utilisée par `GoldenCase.test_matches_golden`."""
    missing_golden = got_keys - expected_keys
    missing_response = expected_keys - got_keys
    if not missing_golden and not missing_response:
        return []
    return [f"routes différentes entre le golden et le serveur (voir tests/README.md) : "
            f"absentes du golden = {sorted(missing_golden)}, absentes de la réponse = {sorted(missing_response)}"]


def _walk_strings(value):
    """Itère toutes les chaînes d'une structure JSON déjà chargée (dict/list/
    scalaires), récursivement — utilisé pour chercher une fuite de chemin
    absolu du bac à sable dans une réponse."""
    if isinstance(value, dict):
        for v in value.values():
            yield from _walk_strings(v)
    elif isinstance(value, list):
        for v in value:
            yield from _walk_strings(v)
    elif isinstance(value, str):
        yield value


class GoldenCase:
    """Un cas par profil sportif — factorisé pour ne pas dupliquer setUp.

    N'hérite PAS de `unittest.TestCase` : `TestLoader.loadTestsFromModule` collecte
    toute sous-classe de `TestCase` présente dans le module, préfixe « Test » ou
    non — en hériter directement ferait tourner ce cas une troisième fois avec
    `sport = None` (et écrirait un golden `dashboard_api_None.json`). Les classes
    concrètes ci-dessous combinent ce mixin avec `unittest.TestCase`."""

    sport = None  # posé par les sous-classes

    def setUp(self):
        # `addCleanup` juste après CHAQUE acquisition de ressource : si une étape
        # suivante de `setUp` lève (ex. l'assertion sur `self.server.url`),
        # unittest n'appelle PAS `tearDown` — sans ceci, le sandbox et/ou le
        # process serveur fuiraient silencieusement à chaque échec de setUp.
        self.sb = Sandbox().__enter__()
        self.addCleanup(self.sb.__exit__, None, None, None)
        self.ws = build(self.sb.root / "ws", days=DAYS, sport=self.sport, seed=SEED,
                        today=datetime.date.fromisoformat(TODAY))
        _write_fixed_fit_samples(self.ws, TODAY)
        self.server = Server(self.sb, ["python3", str(self.sb.repo / "scripts/arc_serve.py"),
                                       "--workspace", str(self.ws), "--port", "0", "--today", TODAY])
        self.addCleanup(self.server.stop)
        self.assertIsNotNone(self.server.url,
                             self.server.proc.stderr.read() if self.server.proc.poll() is not None else "pas d'URL")

    def golden_path(self) -> Path:
        return GOLDEN_DIR / f"dashboard_api_{self.sport}.json"

    def _assert_no_leaked_sandbox_paths(self, endpoints: dict) -> None:
        """Le workspace synthétique vit sous `self.sb.root` (bac à sable
        temporaire, différent à chaque exécution) : si un chemin absolu de ce
        genre apparaissait dans une réponse au lieu du chemin relatif attendu
        (`source_path` doit déjà l'être, voir `arc_index.py::index_workspace`),
        il finirait, une fois figé dans un golden, par toujours « matcher » son
        propre bac à sable dans les runs suivants — un golden ne doit jamais
        contenir de fuite d'un détail d'exécution privé à la machine qui l'a
        généré. On ne normalise donc PAS ce genre de chaîne (voir
        `tests/lib/golden.py::normalize`) : on la fait échouer, ici, tant
        qu'elle est encore visible."""
        needle = str(self.sb.root)
        leaks = [(key, s) for key, payload in endpoints.items()
                for s in _walk_strings(payload) if needle in s]
        self.assertEqual(leaks, [], f"chemin absolu du bac à sable ({needle}) présent dans une réponse")

    def test_matches_golden(self):
        endpoints = _snapshot(self.server)
        self._assert_no_leaked_sandbox_paths(endpoints)
        path = self.golden_path()

        if update_requested():
            for key, payload in endpoints.items():
                status = payload["status"]
                ok = status == 200 or (status == 404 and key == "/api/report")
                self.assertTrue(ok, f"{key} : statut {status} inattendu — un golden ne doit jamais figer une "
                                    "route en échec (mode ARC_UPDATE_GOLDEN=1)")
            dump_golden(path, {"today": TODAY, "seed": SEED, "days": DAYS, "sport": self.sport}, endpoints)
            self.skipTest(f"ARC_UPDATE_GOLDEN=1 : {path} régénéré, comparaison non effectuée")

        golden = load_golden(path)
        self.assertIsNotNone(
            golden,
            f"{path} absent — lancez `ARC_UPDATE_GOLDEN=1 python3 tests/run_tests.py -k Golden` pour le créer")

        problems = _check_route_coverage(set(golden["endpoints"]), set(endpoints))
        if problems:
            self.fail("\n".join(problems))

        mismatches = []
        for key in sorted(endpoints):
            mismatches.extend(f"{key} → {line}" for line in compare(golden["endpoints"][key], endpoints[key]))
        if mismatches:
            self.fail("instantané différent du golden :\n" + "\n".join(mismatches))


class TestGoldenTrail(GoldenCase, unittest.TestCase):
    sport = "trail"


class TestGoldenRoad(GoldenCase, unittest.TestCase):
    sport = "road"


class TestGoldenDetectsNewRoute(GoldenCase, unittest.TestCase):
    """Preuve, avec un vrai serveur, que la suite échoue si une route est
    ajoutée à `arc_serve.ROUTES` sans golden. On ajoute une route factice
    *en process* (restaurée par `addCleanup`, jamais en éditant
    `scripts/arc_serve.py`), on fait tourner la même énumération que
    `test_matches_golden` contre le vrai serveur, et on vérifie que
    `_check_route_coverage` — la fonction utilisée par ce test-là — rapporte
    exactement cette route comme non couverte."""

    sport = "trail"  # golden déjà présent (tests/data/golden/dashboard_api_trail.json)

    def test_new_route_without_golden_is_detected(self):
        route = "/api/__fake_new_route_28__"

        def _fake_handler(store, q):
            return {"fake": True}

        arc_serve.ROUTES[route] = _fake_handler
        self.addCleanup(arc_serve.ROUTES.pop, route, None)

        endpoints = _snapshot(self.server)
        self.assertIn(route, endpoints, "l'énumération doit suivre arc_serve.ROUTES en direct")

        golden = load_golden(self.golden_path())
        self.assertIsNotNone(golden)
        self.assertNotIn(route, golden["endpoints"], "le golden existant ne doit évidemment pas la connaître")

        problems = _check_route_coverage(set(golden["endpoints"]), set(endpoints))
        self.assertTrue(problems, "une route ajoutée sans golden doit être détectée")
        self.assertIn(route, problems[0])


class TestGoldenComparatorDetectsMetricChange(unittest.TestCase):
    """Palier A du critère d'acceptation : un changement volontaire d'une
    métrique fait échouer l'instantané. On charge le VRAI golden trail (pas un
    dict inventé), on perturbe une métrique réelle (la condition/CTL d'un jour
    de `/api/form`) dans une copie, et on vérifie que `compare()` la rapporte
    au chemin JSON exact — sans dépendre d'une modification du code de
    production."""

    def test_perturbed_real_metric_is_reported(self):
        golden = load_golden(GOLDEN_DIR / "dashboard_api_trail.json")
        self.assertIsNotNone(golden, "golden trail absent — générez-le d'abord (ARC_UPDATE_GOLDEN=1)")
        expected = golden["endpoints"]["/api/form"]
        got = copy.deepcopy(expected)

        series = got["body"]["series"]
        idx = next(i for i, point in enumerate(series) if point.get("fitness") is not None)
        got["body"]["series"][idx]["fitness"] += 5.0  # condition (CTL) modifiée délibérément

        mismatches = compare(expected, got)

        self.assertEqual(len(mismatches), 1, mismatches)
        self.assertIn(f"series[{idx}].fitness", mismatches[0])

    def test_unperturbed_copy_matches(self):
        expected = {"status": 200, "body": {"a": 1.0000000001, "b": [1, 2, {"c": "x"}]}}
        got = copy.deepcopy(expected)
        got["body"]["a"] = 1.0000000002  # sous la tolérance flottante documentée
        self.assertEqual(compare(expected, got), [])

    def test_bool_vs_int_is_reported(self):
        """`True == 1` en Python : sans garde explicite, un booléen qui se
        mettrait à sortir en entier (ou l'inverse) passerait inaperçu."""
        self.assertNotEqual(compare({"a": True}, {"a": 1}), [])
        self.assertNotEqual(compare({"a": False}, {"a": 0}), [])
        self.assertEqual(compare({"a": True}, {"a": True}), [])

    def test_int_float_type_change_is_reported(self):
        """5000 == 5000.0 numériquement, mais json distingue les deux formes :
        un champ qui se met à sortir un flottant là où il sortait un entier
        (ou l'inverse) est un changement de forme, pas du bruit à tolérer."""
        mismatches = compare({"a": 5000}, {"a": 5000.0})
        self.assertEqual(len(mismatches), 1, mismatches)
        self.assertIn("type", mismatches[0].lower())

    def test_nan_equals_nan(self):
        """Deux NaN issus du même calcul déterministe (ex. ACWR non défini,
        condition quasi nulle) ne doivent pas être rapportés comme un écart —
        `nan != nan` en Python ferait sinon échouer la comparaison à chaque
        exécution, sans aucune régression réelle."""
        self.assertEqual(compare({"a": float("nan")}, {"a": float("nan")}), [])
        self.assertNotEqual(compare({"a": float("nan")}, {"a": 1.0}), [])


if __name__ == "__main__":
    unittest.main()
