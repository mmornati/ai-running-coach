"""Palier D — correction altimétrique par MNT (#176, `scripts/arc_dem.py`).

AUCUN appel réseau : tout le HTTP passe par un stub (`StubDem`) injecté via `http_get`, ou
substitué à `arc_dem.default_http_get` pour les tests de CLI. Familles :
- amincissement (`thin_indices`), lots (`chunked`), arrondi/clé de cache, routage par zone
  (`provider_for`) ;
- `lookup`/`resample_track` : lots par fournisseur, cache (hits, persistance, désactivation),
  repli Open-Meteo quand l'IGN n'a pas de donnée, espacement des appels ;
- hors ligne : réessais avec attente exponentielle, 4xx sans réessai, `status = "unavailable"`,
  `strict` ;
- D+ sur série corrigée (`compare_gain_loss`), `analyze_gpx.py --dem` de bout en bout (stub) ;
- vie privée : `dem-check` désactivé par défaut, début/fin de trace jamais envoyés.

Les coordonnées de test sont fictives (zone Pacifique Sud conventionnelle du dépôt) ; la
couverture France du routage IGN utilise le centre géographique approximatif du pays en
arguments POSITIONNELS (aucun lieu réel enregistré).
"""

from __future__ import annotations

import io
import json
import math
import sys
import tempfile
import unittest
import urllib.error
import urllib.parse
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "skills/gpx-analysis/scripts"))

import arc_dem as D  # noqa: E402
import arc_elevation as EL  # noqa: E402
import analyze_gpx as AG  # noqa: E402

SAFE_LAT = -40.0
SAFE_LON = -140.0
M_PER_DEG_LON = 111320.0 * math.cos(math.radians(SAFE_LAT))


def line(base_lat, base_lon, n, step_m=10.0):
    """Trace rectiligne vers l'est, `n` points espacés de `step_m` mètres."""
    m_per_deg = 111320.0 * math.cos(math.radians(base_lat))
    return [{"lat": base_lat, "lon": base_lon + i * step_m / m_per_deg, "ele": 0.0} for i in range(n)]


def terrain(lon_deg, base_lon):
    """Terrain stubbé : 0,1 m par 10⁻⁴ degré de longitude (rampe), indépendant de la latitude."""
    return round(100.0 + (lon_deg - base_lon) * 1000.0, 2)


class StubDem:
    """Faux fournisseurs : enregistre les URLs, calcule l'altitude depuis la longitude."""

    def __init__(self, base_lon, ign_no_data=lambda lat, lon: False):
        self.base_lon = base_lon
        self.urls = []
        self.ign_no_data = ign_no_data

    def __call__(self, url):
        self.urls.append(url)
        parsed = urllib.parse.urlparse(url)
        q = urllib.parse.parse_qs(parsed.query)
        if "data.geopf.fr" in parsed.netloc:
            lons = [float(v) for v in q["lon"][0].split("|")]
            lats = [float(v) for v in q["lat"][0].split("|")]
            assert q["resource"] == ["ign_rge_alti_wld"]
            return {"elevations": [D.NO_DATA_Z if self.ign_no_data(la, lo) else terrain(lo, self.base_lon)
                                   for la, lo in zip(lats, lons)]}
        assert "api.open-meteo.com" in parsed.netloc
        lons = [float(v) for v in q["longitude"][0].split(",")]
        return {"elevation": [float(round(terrain(lo, self.base_lon))) for lo in lons]}


class TestPureHelpers(unittest.TestCase):
    def test_thin_indices_keeps_first_last_and_spacing(self):
        dist = [i * 10.0 for i in range(101)]  # 1 km, un point tous les 10 m
        idx = D.thin_indices(dist, 50.0)
        self.assertEqual(idx[0], 0)
        self.assertEqual(idx[-1], 100)
        self.assertEqual(idx, [0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55, 60, 65, 70, 75, 80, 85, 90, 95, 100])

    def test_thin_indices_always_keeps_endpoints_even_if_closer_than_step(self):
        self.assertEqual(D.thin_indices([0.0, 10.0], 50.0), [0, 1])
        self.assertEqual(D.thin_indices([0.0], 50.0), [0])
        self.assertEqual(D.thin_indices([], 50.0), [])

    def test_thin_indices_widens_step_to_respect_max_points(self):
        dist = [i * 10.0 for i in range(1001)]  # 10 km
        idx = D.thin_indices(dist, 10.0, max_points=101)
        self.assertLessEqual(len(idx), 102)
        self.assertLess(len(idx), 200)

    def test_chunked(self):
        self.assertEqual(D.chunked(list(range(5)), 2), [[0, 1], [2, 3], [4]])
        self.assertEqual(D.chunked([], 3), [])
        with self.assertRaises(ValueError):
            D.chunked([1], 0)

    def test_provider_routing_by_bbox(self):
        self.assertEqual(D.provider_for(46.5, 2.5), "ign")          # centre approximatif de la France
        self.assertEqual(D.provider_for(42.0, 9.0), "ign")          # Corse (dans la boîte)
        self.assertEqual(D.provider_for(40.0, 2.5), "open-meteo")   # au sud de la boîte
        self.assertEqual(D.provider_for(46.5, 15.0), "open-meteo")  # à l'est
        self.assertEqual(D.provider_for(SAFE_LAT, SAFE_LON), "open-meteo")

    def test_cache_key_rounds_per_provider(self):
        self.assertEqual(D.cache_key("ign", 46.1234567, 2.7654321), "ign:46.12346,2.76543")
        self.assertEqual(D.cache_key("open-meteo", 46.1234567, 2.7654321), "open-meteo:46.1235,2.7654")

    def test_interpolate_by_distance(self):
        out = D.interpolate_by_distance([0.0, 100.0], [10.0, 20.0], [-5.0, 0.0, 50.0, 100.0, 200.0])
        self.assertEqual(out, [10.0, 10.0, 15.0, 20.0, 20.0])

    def test_urls_use_documented_endpoints_and_parameters(self):
        url = D.ign_url([(1.0, 2.0), (3.0, 4.0)])
        self.assertTrue(url.startswith("https://data.geopf.fr/altimetrie/1.0/calcul/alti/rest/elevation.json?"))
        q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
        self.assertEqual(q["lon"], ["2.00000|4.00000"])
        self.assertEqual(q["lat"], ["1.00000|3.00000"])
        self.assertEqual(q["resource"], ["ign_rge_alti_wld"])
        om = D.open_meteo_url([(1.0, 2.0), (3.0, 4.0)])
        self.assertTrue(om.startswith("https://api.open-meteo.com/v1/elevation?"))
        q = urllib.parse.parse_qs(urllib.parse.urlparse(om).query)
        self.assertEqual(q["latitude"], ["1.0000,3.0000"])
        self.assertEqual(q["longitude"], ["2.0000,4.0000"])

    def test_parsers_reject_malformed_payloads(self):
        with self.assertRaises(D.DemError):
            D.parse_ign({"oops": []}, 1)
        with self.assertRaises(D.DemError):
            D.parse_open_meteo({"elevation": [1.0]}, 2)
        self.assertEqual(D.parse_ign({"elevations": [-99999.0, {"z": 12.5}]}, 2), [None, 12.5])


class TestLookupAndCache(unittest.TestCase):
    def test_open_meteo_batches_of_100(self):
        pts = line(SAFE_LAT, SAFE_LON, 250, step_m=100.0)
        stub = StubDem(SAFE_LON)
        stats = {}
        out = D.lookup([(p["lat"], p["lon"]) for p in pts], http_get=stub, sleep=lambda s: None, stats=stats)
        self.assertEqual(len(stub.urls), 3)  # 100 + 100 + 50
        self.assertEqual(stats["coords_sent"], 250)
        self.assertTrue(all(prov == "open-meteo" for _, prov in out))
        self.assertTrue(all(z is not None for z, _ in out))

    def test_ign_used_inside_france_in_batches_of_200(self):
        pts = line(46.5, 2.5, 450, step_m=20.0)
        stub = StubDem(2.5)
        out = D.lookup([(p["lat"], p["lon"]) for p in pts], http_get=stub, sleep=lambda s: None)
        self.assertEqual(len(stub.urls), 3)  # 200 + 200 + 50
        self.assertTrue(all("data.geopf.fr" in u for u in stub.urls))
        self.assertTrue(all(prov == "ign" for _, prov in out))

    def test_ign_gap_falls_back_to_open_meteo(self):
        pts = line(46.5, 2.5, 10, step_m=20.0)
        stub = StubDem(2.5, ign_no_data=lambda la, lo: lo > 2.5 + 0.0004)
        out = D.lookup([(p["lat"], p["lon"]) for p in pts], http_get=stub, sleep=lambda s: None)
        providers = [prov for _, prov in out]
        self.assertIn("ign", providers)
        self.assertIn("open-meteo", providers)
        self.assertTrue(any("api.open-meteo.com" in u for u in stub.urls))

    def test_cache_hits_avoid_any_network_call_and_persist(self):
        pts = line(SAFE_LAT, SAFE_LON, 60, step_m=10.0)
        coords = [(p["lat"], p["lon"]) for p in pts]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / ".arc" / "dem-cache.json"
            stub = StubDem(SAFE_LON)
            first = D.lookup(coords, cache=D.DemCache(path), http_get=stub, sleep=lambda s: None)
            self.assertEqual(len(stub.urls), 1)
            self.assertTrue(path.is_file())
            stats = {}
            second_stub = StubDem(SAFE_LON)
            second = D.lookup(coords, cache=D.DemCache(path), http_get=second_stub, sleep=lambda s: None, stats=stats)
            self.assertEqual(second_stub.urls, [])
            self.assertEqual(stats["cache_hits"], len(coords))
            self.assertEqual(first, second)

    def test_disabled_cache_is_ignored_and_never_written(self):
        coords = [(p["lat"], p["lon"]) for p in line(SAFE_LAT, SAFE_LON, 5)]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "c.json"
            stub = StubDem(SAFE_LON)
            D.lookup(coords, cache=D.DemCache(path, enabled=False), http_get=stub, sleep=lambda s: None)
            D.lookup(coords, cache=D.DemCache(path, enabled=False), http_get=stub, sleep=lambda s: None)
            self.assertEqual(len(stub.urls), 2)
            self.assertFalse(path.exists())

    def test_corrupt_cache_is_rebuilt_not_fatal(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "c.json"
            path.write_text("{pas du json", encoding="utf-8")
            self.assertEqual(D.DemCache(path).data, {})

    def test_cache_file_is_private_and_holds_no_track_order(self):
        import os
        import stat
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / ".arc" / "dem-cache.json"
            coords = [(p["lat"], p["lon"]) for p in line(SAFE_LAT, SAFE_LON, 5)]
            D.lookup(coords, cache=D.DemCache(path), http_get=StubDem(SAFE_LON), sleep=lambda s: None)
            self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600)
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertTrue(all(k.startswith("open-meteo:") for k in data))

    def test_calls_are_spaced_to_respect_rate_limit(self):
        coords = [(p["lat"], p["lon"]) for p in line(SAFE_LAT, SAFE_LON, 250, step_m=100.0)]
        sleeps = []
        clock = iter([0.0, 0.01, 0.02, 0.03, 0.04, 0.05, 0.06, 0.07]).__next__
        stub = StubDem(SAFE_LON)
        with mock.patch.object(D.time, "monotonic", clock):
            D.lookup(coords, http_get=stub, sleep=sleeps.append)
        self.assertEqual(len(stub.urls), 3)
        self.assertEqual(len(sleeps), 2)  # attente avant les 2e et 3e lots
        self.assertTrue(all(0 < s <= D.MIN_INTERVAL_S["open-meteo"] for s in sleeps))


class TestOffline(unittest.TestCase):
    def test_retries_with_exponential_backoff_then_unavailable(self):
        calls, sleeps = [], []

        def down(url):
            calls.append(url)
            raise urllib.error.URLError("pas de réseau")

        res = D.resample_track(line(SAFE_LAT, SAFE_LON, 20), http_get=down, sleep=sleeps.append)
        self.assertEqual(res["status"], "unavailable")
        self.assertIsNone(res["ele"])
        self.assertIn("indisponible", res["report"]["error"])
        self.assertEqual(len(calls), D.RETRIES)
        self.assertEqual(sleeps, [D.BACKOFF_S, D.BACKOFF_S * 2])

    def test_http_429_is_retried_but_404_is_not(self):
        def make(code):
            n = []

            def f(url):
                n.append(1)
                raise urllib.error.HTTPError(url, code, "x", {}, io.BytesIO(b""))
            return f, n

        f429, n429 = make(429)
        D.resample_track(line(SAFE_LAT, SAFE_LON, 20), http_get=f429, sleep=lambda s: None)
        self.assertEqual(len(n429), D.RETRIES)
        f404, n404 = make(404)
        D.resample_track(line(SAFE_LAT, SAFE_LON, 20), http_get=f404, sleep=lambda s: None)
        self.assertEqual(len(n404), 1)

    def test_strict_raises(self):
        def down(url):
            raise TimeoutError("lent")
        with self.assertRaises(D.DemError):
            D.resample_track(line(SAFE_LAT, SAFE_LON, 20), http_get=down, sleep=lambda s: None, strict=True)

    def test_insufficient_coverage_is_unavailable(self):
        stub = StubDem(SAFE_LON)

        def holes(url):
            data = stub(url)
            data["elevation"] = [None] * len(data["elevation"])
            return data

        res = D.resample_track(line(SAFE_LAT, SAFE_LON, 50), http_get=holes, sleep=lambda s: None)
        self.assertEqual(res["status"], "unavailable")
        self.assertIn("couverture", res["report"]["error"])

    def test_too_short_track(self):
        self.assertEqual(D.resample_track([{"lat": SAFE_LAT, "lon": SAFE_LON}])["status"], "unavailable")

    def test_malformed_response_is_unavailable(self):
        res = D.resample_track(line(SAFE_LAT, SAFE_LON, 20), http_get=lambda u: {"x": 1}, sleep=lambda s: None)
        self.assertEqual(res["status"], "unavailable")


class TestResampleAndGain(unittest.TestCase):
    def test_resample_interpolates_and_sends_only_thinned_nodes(self):
        pts = line(SAFE_LAT, SAFE_LON, 201, step_m=5.0)  # 1 km, un point tous les 5 m
        stub = StubDem(SAFE_LON)
        res = D.resample_track(pts, step_m=50.0, http_get=stub, sleep=lambda s: None)
        self.assertEqual(res["status"], "ok")
        self.assertEqual(len(res["ele"]), 201)
        nodes = res["report"]["nodes"]
        self.assertIn(nodes, (20, 21))  # un point tous les ~50 m (dérive flottante du cumul)
        self.assertEqual(res["report"]["coords_sent"], nodes)
        self.assertEqual(res["report"]["providers"], {"open-meteo": nodes})
        self.assertIn("Copernicus", res["report"]["attribution"][0])
        # Les points d'origine ne sont pas modifiés.
        self.assertTrue(all(p["ele"] == 0.0 for p in pts))
        # Rampe montante : l'altitude interpolée est croissante.
        self.assertEqual(res["ele"], sorted(res["ele"]))

    def test_dem_gain_on_corrected_series(self):
        # Terrain stubbé : rampe d'environ 0,1 m par 10 m (1 %) sur 1 km -> ~+10 m... mesuré
        # directement sur la série corrigée, sans seuil ni lissage.
        pts = line(SAFE_LAT, SAFE_LON, 101, step_m=10.0)
        res = D.resample_track(pts, step_m=50.0, http_get=StubDem(SAFE_LON), sleep=lambda s: None)
        gain, loss = EL.gain_loss(res["ele"])
        self.assertAlmostEqual(gain, res["ele"][-1] - res["ele"][0], places=6)
        self.assertEqual(loss, 0.0)
        self.assertGreater(gain, 5.0)

    def test_compare_gain_loss_flags_noisy_file_gain(self):
        # Fichier plat bruité de ±3 m (GPS) vs MNT plat : D+ fichier gonflé, D+ MNT nul.
        noisy = [100.0 + (3.0 if i % 2 else -3.0) for i in range(100)]
        comp = D.compare_gain_loss(noisy, [100.0] * 100, file_smooth=1)
        self.assertGreater(comp["file_gain_m"], 100.0)
        self.assertEqual(comp["dem_gain_m"], 0.0)
        self.assertLess(comp["delta_gain_m"], 0)
        self.assertEqual(comp["delta_gain_pct"], -100.0)

    def test_compare_gain_loss_zero_file_gain_has_no_pct(self):
        self.assertIsNone(D.compare_gain_loss([100.0] * 5, [100.0, 105.0, 110.0, 115.0, 120.0])["delta_gain_pct"])

    def test_dem_gain_never_exceeds_true_terrain_gain(self):
        """Interpolation linéaire entre altitudes VRAIES : le D+ ne peut que sous-estimer le
        terrain (inégalité triangulaire) — proche pour une longue ondulation, nettement en
        deçà pour des bosses plus courtes que deux pas (ASSUMPTIONS["thinning"])."""
        def true_gain(f, length, ds=0.5):
            return EL.gain_loss([f(i * ds) for i in range(int(length / ds) + 1)])[0]

        length, step = 10000.0, 50.0
        node_d = [i * step for i in range(int(length / step) + 1)]
        dists = [i * 5.0 for i in range(int(length / 5.0) + 1)]
        for wavelength, amp, max_under_pct in ((2000.0, 200.0, 1.0), (600.0, 30.0, 3.0), (100.0, 3.0, 30.0)):
            f = lambda s, w=wavelength, a=amp: a * math.sin(2 * math.pi * s / w) + 0.08 * s
            ref = true_gain(f, length)
            dem = EL.gain_loss(D.interpolate_by_distance(node_d, [f(d) for d in node_d], dists))[0]
            self.assertLessEqual(dem, ref + 1e-6, wavelength)
            self.assertLess((ref - dem) / ref * 100.0, max_under_pct, wavelength)

    def test_gain_loss_pure(self):
        self.assertEqual(EL.gain_loss([0, 10, 5, 15]), (20.0, 5.0))
        self.assertEqual(EL.gain_loss([0, 0.5, 0.2], min_step_m=1.0), (0.0, 0.0))
        self.assertEqual(EL.gain_loss([1.0]), (0.0, 0.0))
        self.assertEqual(EL.gain_loss([None, 5.0, None, 8.0]), (0.0, 0.0))


class TestSettings(unittest.TestCase):
    def _ws(self, user_toml=None):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        (root / "config").mkdir()
        if user_toml is not None:
            (root / "config/workspace.user.toml").write_text(user_toml, encoding="utf-8")
        return root

    def test_defaults_are_conservative(self):
        s = D.load_settings(self._ws())
        self.assertEqual(s, {"dem": "off", "step_m": 50.0, "cache": True, "activities": False,
                             "activity_trim_m": 500.0})
        self.assertEqual(D.load_settings(None)["dem"], "off")

    def test_shipped_workspace_toml_defaults_to_off(self):
        s = D.load_settings(REPO)
        self.assertEqual(s["dem"], "off")
        self.assertFalse(s["activities"])

    def test_user_override_and_invalid_values_warn(self):
        warnings = []
        ws = self._ws('[elevation]\ndem = "auto"\nstep_m = 25\n[privacy]\ndem_for_activities = true\n')
        s = D.load_settings(ws, warn=warnings.append)
        self.assertEqual((s["dem"], s["step_m"], s["activities"]), ("auto", 25.0, True))
        self.assertEqual(warnings, [])
        bad = self._ws('[elevation]\ndem = "oui"\nstep_m = 1\n[privacy]\ndem_for_activities = "yes"\n')
        s = D.load_settings(bad, warn=warnings.append)
        self.assertEqual((s["dem"], s["step_m"], s["activities"]), ("off", 50.0, False))
        self.assertEqual(len(warnings), 3)

    def test_activity_trim_is_configurable_within_bounds(self):
        warnings = []
        ws = self._ws('[privacy]\ndem_trim_m = 1500\n')
        self.assertEqual(D.load_settings(ws, warn=warnings.append)["activity_trim_m"], 1500.0)
        self.assertEqual(warnings, [])
        for bad in ("50", "100000", '"loin"', "true"):
            warnings = []
            s = D.load_settings(self._ws(f"[privacy]\ndem_trim_m = {bad}\n"), warn=warnings.append)
            self.assertEqual(s["activity_trim_m"], D.PRIVACY_TRIM_M, bad)
            self.assertEqual(len(warnings), 1, bad)

    def test_shipped_trim_default_is_500_m(self):
        self.assertEqual(D.load_settings(REPO)["activity_trim_m"], 500.0)

    def test_cache_lives_in_workspace_arc_dir(self):
        with mock.patch.dict("os.environ", {}, clear=False):
            import os
            os.environ.pop("ARC_DEM_CACHE", None)
            self.assertEqual(D.cache_path(Path("/ws")), Path("/ws/.arc/dem-cache.json"))


class TestActivityPrivacy(unittest.TestCase):
    def _samples(self, n=400, step_m=10.0, noise=2.0):
        out = []
        m_per_deg = M_PER_DEG_LON
        for i in range(n):
            out.append({"lat_deg": SAFE_LAT, "lon_deg": SAFE_LON + i * step_m / m_per_deg,
                        "altitude_m": 100.0 + i * 0.1 + (noise if i % 2 else -noise)})
        return out

    def test_start_and_end_are_never_sent(self):
        samples = self._samples()  # ~4 km
        stub = StubDem(SAFE_LON)
        res = D.activity_check(samples, step_m=100.0, http_get=stub, sleep=lambda s: None)
        self.assertIn(res["status"], ("ok", "partial"))
        sent_lons = []
        for url in stub.urls:
            q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
            sent_lons += [float(v) for v in q["longitude"][0].split(",")]
        first_lon, last_lon = samples[0]["lon_deg"], samples[-1]["lon_deg"]
        trim_deg = D.PRIVACY_TRIM_M / M_PER_DEG_LON
        self.assertGreaterEqual(min(sent_lons), first_lon + trim_deg - 1e-4)
        self.assertLessEqual(max(sent_lons), last_lon - trim_deg + 1e-4)
        # Seules des coordonnées partent : aucun autre paramètre que latitude/longitude.
        for url in stub.urls:
            self.assertEqual(sorted(urllib.parse.parse_qs(urllib.parse.urlparse(url).query)), ["latitude", "longitude"])

    def test_larger_trim_is_honoured_and_floor_cannot_be_lowered(self):
        samples = self._samples(n=600)  # ~6 km
        for asked, expected in ((1500.0, 1500.0), (10.0, D.PRIVACY_TRIM_BOUNDS_M[0])):
            stub = StubDem(SAFE_LON)
            res = D.activity_check(samples, step_m=100.0, http_get=stub, sleep=lambda s: None, trim_m=asked)
            self.assertEqual(res["trimmed_m"], expected)
            sent = []
            for url in stub.urls:
                q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
                sent += [float(v) for v in q["longitude"][0].split(",")]
            trim_deg = expected / M_PER_DEG_LON
            self.assertGreaterEqual(min(sent), samples[0]["lon_deg"] + trim_deg - 1e-4)
            self.assertLessEqual(max(sent), samples[-1]["lon_deg"] - trim_deg + 1e-4)

    def test_noisy_recorded_altitude_vs_dem(self):
        res = D.activity_check(self._samples(), step_m=100.0, http_get=StubDem(SAFE_LON), sleep=lambda s: None)
        self.assertGreater(res["file_gain_m"], res["dem_gain_m"])
        self.assertIn("mean_offset_m", res)
        self.assertEqual(res["trimmed_m"], D.PRIVACY_TRIM_M)

    def test_too_short_after_trim(self):
        stub = StubDem(SAFE_LON)
        res = D.activity_check(self._samples(n=40), http_get=stub, sleep=lambda s: None)  # 400 m
        self.assertEqual(res["status"], "too_short")
        self.assertEqual(stub.urls, [])

    def test_no_gps(self):
        res = D.activity_check([{"altitude_m": 1.0}, {"altitude_m": 2.0}], http_get=StubDem(SAFE_LON))
        self.assertEqual(res["status"], "no_gps")

    def test_arc_index_dem_check_disabled_by_default_sends_nothing(self):
        import arc_index as IDX
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            (ws / "config").mkdir()
            conn = IDX.open_db(ws, None, True, False)
            stub = StubDem(SAFE_LON)
            out = IDX.activity_dem_check(conn, ws, 90000000001, http_get=stub)
            self.assertEqual(out["status"], "disabled")
            self.assertEqual(stub.urls, [])
            self.assertIn("dem_for_activities", out["reason"])

    def test_arc_index_dem_check_enabled_unknown_activity(self):
        import arc_index as IDX
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            (ws / "config").mkdir()
            (ws / "config/workspace.user.toml").write_text("[privacy]\ndem_for_activities = true\n", encoding="utf-8")
            conn = IDX.open_db(ws, None, True, False)
            stub = StubDem(SAFE_LON)
            out = IDX.activity_dem_check(conn, ws, 90000000001, http_get=stub)
            self.assertEqual(out["status"], "unknown_activity")
            self.assertEqual(stub.urls, [])


class TestAnalyzeGpxDem(unittest.TestCase):
    def _gpx(self, tmp, n=200, step_m=10.0):
        pts = line(SAFE_LAT, SAFE_LON, n, step_m)
        body = "".join(f'<trkpt lat="{p["lat"]}" lon="{p["lon"]}"><ele>{100 + (3 if i % 2 else -3)}</ele></trkpt>'
                       for i, p in enumerate(pts))
        path = Path(tmp) / "t.gpx"
        path.write_text(f'<?xml version="1.0"?><gpx xmlns="http://www.topografix.com/GPX/1/1"><trk><trkseg>{body}'
                        "</trkseg></trk></gpx>", encoding="utf-8")
        return path

    def _run(self, argv, http):
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(D, "default_http_get", http), mock.patch.object(D.time, "sleep", lambda s: None), \
                redirect_stdout(out), redirect_stderr(err):
            rc = AG.main(argv)
        return rc, out.getvalue(), err.getvalue()

    def test_default_run_makes_no_network_call(self):
        with tempfile.TemporaryDirectory() as tmp:
            stub = StubDem(SAFE_LON)
            ws = Path(tmp) / "ws"
            (ws / "config").mkdir(parents=True)
            js = Path(tmp) / "o.json"
            rc, out, _ = self._run(["--gpx", str(self._gpx(tmp)), "--workspace", str(ws), "--json", str(js)], stub)
            self.assertEqual(rc, 0)
            self.assertEqual(stub.urls, [])
            self.assertNotIn("Correction altimétrique", out)
            # Sortie JSON inchangée par rapport à avant #176 : ni `dem` ni `elevation_source`.
            dump = json.loads(js.read_text(encoding="utf-8"))
            self.assertNotIn("dem", dump)
            self.assertNotIn("elevation_source", dump["metrics"])

    def test_dem_flag_corrects_and_shows_both_gains(self):
        with tempfile.TemporaryDirectory() as tmp:
            stub = StubDem(SAFE_LON)
            ws = Path(tmp) / "ws"
            (ws / "config").mkdir(parents=True)
            js = Path(tmp) / "o.json"
            rc, out, _ = self._run(["--gpx", str(self._gpx(tmp)), "--workspace", str(ws), "--dem",
                                    "--json", str(js), "--quiet"], stub)
            self.assertEqual(rc, 0)
            self.assertGreater(len(stub.urls), 0)
            self.assertIn("## Correction altimétrique (MNT)", out)
            self.assertIn("D+ fichier", out)
            self.assertIn("D+ MNT", out)
            self.assertIn("Copernicus", out)
            dump = json.loads(js.read_text(encoding="utf-8"))
            self.assertEqual(dump["metrics"]["elevation_source"], "dem")
            comp = dump["dem"]["comparison"]
            self.assertEqual(dump["metrics"]["elevation_gain_m"], round(comp["dem_gain_m"], 1))
            self.assertGreater(comp["file_gain_m"], comp["dem_gain_m"])
            self.assertTrue((ws / ".arc" / "dem-cache.json").is_file())

    def test_offline_falls_back_to_file_elevation_with_warning(self):
        def down(url):
            raise urllib.error.URLError("hors ligne")

        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp) / "ws"
            (ws / "config").mkdir(parents=True)
            gpx = self._gpx(tmp)
            _, baseline, _ = self._run(["--gpx", str(gpx), "--workspace", str(ws)], down)
            rc, out, err = self._run(["--gpx", str(gpx), "--workspace", str(ws), "--dem"], down)
            self.assertEqual(rc, 0)
            self.assertIn("indisponible", err)
            self.assertIn("altitudes du fichier conservées", out)
            # Mêmes chiffres que sans --dem (hors bandeau d'avertissement).
            strip = lambda t: "\n".join(l for l in t.splitlines() if l.strip() and "MNT" not in l)
            self.assertEqual(strip(out).strip(), strip(baseline).strip())

    def test_auto_mode_in_config_and_no_dem_override(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp) / "ws"
            (ws / "config").mkdir(parents=True)
            (ws / "config/workspace.user.toml").write_text('[elevation]\ndem = "auto"\n', encoding="utf-8")
            gpx = self._gpx(tmp)
            stub = StubDem(SAFE_LON)
            _, out, _ = self._run(["--gpx", str(gpx), "--workspace", str(ws)], stub)
            self.assertIn("Correction altimétrique", out)
            stub2 = StubDem(SAFE_LON)
            _, out2, _ = self._run(["--gpx", str(gpx), "--workspace", str(ws), "--no-dem"], stub2)
            self.assertEqual(stub2.urls, [])
            self.assertNotIn("Correction altimétrique", out2)

    def test_km_profile_matches_dem_table_on_a_descending_track(self):
        """Régression (intégration #176) : sur une trace qui DESCEND, le profil par km comptait
        l'écart arrivée → départ (`ele[-1]` pour `i = 0`) comme D+ du km 0 — le tableau MNT
        disait D+ 37 m quand le profil en affichait 472. La somme du profil doit égaler les
        totaux du rapport, et une descente pure n'a aucun D+."""
        with tempfile.TemporaryDirectory() as tmp:
            pts = list(reversed(line(SAFE_LAT, SAFE_LON, 250, step_m=10.0)))  # 2,5 km vers l'ouest
            body = "".join(f'<trkpt lat="{p["lat"]}" lon="{p["lon"]}"><ele>{1400 - 2 * i}</ele></trkpt>'
                           for i, p in enumerate(pts))
            gpx = Path(tmp) / "descente.gpx"
            gpx.write_text(f'<?xml version="1.0"?><gpx xmlns="http://www.topografix.com/GPX/1/1"><trk><trkseg>{body}'
                           "</trkseg></trk></gpx>", encoding="utf-8")
            ws = Path(tmp) / "ws"
            (ws / "config").mkdir(parents=True)
            js = Path(tmp) / "o.json"
            rc, _, _ = self._run(["--gpx", str(gpx), "--workspace", str(ws), "--dem", "--json", str(js), "--quiet"],
                                 StubDem(SAFE_LON))
            self.assertEqual(rc, 0)
            dump = json.loads(js.read_text(encoding="utf-8"))
            m, prof, comp = dump["metrics"], dump["km_profile"], dump["dem"]["comparison"]
            self.assertEqual(comp["dem_gain_m"], 0.0)  # terrain stubbé : rampe montante vers l'est
            self.assertGreater(comp["dem_loss_m"], 0.0)
            self.assertEqual((m["elevation_gain_m"], m["elevation_loss_m"]), (comp["dem_gain_m"], comp["dem_loss_m"]))
            self.assertAlmostEqual(sum(k["dp"] for k in prof), m["elevation_gain_m"], delta=0.5)
            self.assertAlmostEqual(sum(k["dm"] for k in prof), m["elevation_loss_m"], delta=0.5)
            self.assertEqual(prof[0]["dp"], 0)

    def test_km_profile_never_wraps_to_the_last_point_without_dem(self):
        pts = [{"lat": p["lat"], "lon": p["lon"], "ele": 500.0 - 0.5 * i}
               for i, p in enumerate(line(SAFE_LAT, SAFE_LON, 300, step_m=10.0))]
        m = AG.compute_metrics(pts, smooth=1, min_step_m=0.0)
        self.assertEqual(m["km_profile"][0]["dp"], 0)
        self.assertAlmostEqual(sum(k["dm"] for k in m["km_profile"]), m["elevation_loss_m"], delta=0.5)

    def test_dem_and_no_dem_conflict(self):
        with tempfile.TemporaryDirectory() as tmp:
            rc, _, err = self._run(["--gpx", str(self._gpx(tmp)), "--dem", "--no-dem"], StubDem(SAFE_LON))
            self.assertEqual(rc, 1)
            self.assertIn("incompatibles", err)


class TestRacePacingDem(unittest.TestCase):
    """`arc_race_pacing.py plan` : aucun appel réseau par défaut ; `--dem` corrige (stub)."""

    def _run(self, extra, http, user_toml=None):
        import arc_race_pacing as RP
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp) / "ws"
            (ws / "config").mkdir(parents=True)
            if user_toml:
                (ws / "config/workspace.user.toml").write_text(user_toml, encoding="utf-8")
            gpx = TestAnalyzeGpxDem()._gpx(tmp, n=300)
            out, err = io.StringIO(), io.StringIO()
            with mock.patch.object(D, "default_http_get", http), mock.patch.object(D.time, "sleep", lambda s: None), \
                    redirect_stdout(out), redirect_stderr(err):
                rc = RP.main(["plan", "--workspace", str(ws), "--memory", "--gpx", str(gpx),
                              "--race-date", "2030-06-01", "--start", "08:00", "--today", "2030-05-01", *extra])
            return rc, out.getvalue(), err.getvalue()

    def test_default_plan_makes_no_network_call(self):
        def forbidden(url):
            raise AssertionError("appel réseau interdit par défaut")

        rc, out, _ = self._run([], forbidden)
        self.assertEqual(rc, 0)
        self.assertNotIn("elevation_dem", json.loads(out))
        rc, out, _ = self._run(["--no-dem"], forbidden, user_toml='[elevation]\ndem = "auto"\n')
        self.assertEqual(rc, 0)
        self.assertNotIn("elevation_dem", json.loads(out))

    def test_dem_plan_uses_dem_and_cites_attribution(self):
        stub = StubDem(SAFE_LON)
        rc, out, _ = self._run(["--dem"], stub)
        self.assertEqual(rc, 0)
        self.assertGreater(len(stub.urls), 0)
        plan = json.loads(out)
        dem = plan["elevation_dem"]
        self.assertIn(dem["status"], ("ok", "partial"))
        # Fichier en dents de scie (±3 m) : son D+ (mesuré comme le plan sans --dem) dépasse le MNT.
        self.assertGreater(dem["file_gain_m"], dem["dem_gain_m"])
        self.assertTrue(any("Copernicus" in w for w in plan.get("warnings", [])))

    def test_dem_composes_with_the_night_pipeline(self):
        """#184 × #176 : la pénalité de nuit tourne sur l'altitude MNT ; `elevation_dem` est posé
        après `build_race_plan`, juste avant l'impression finale."""
        rc, out, _ = self._run(["--dem", "--tz", "Pacific/Pitcairn", "--start", "02:00"], StubDem(SAFE_LON))
        self.assertEqual(rc, 0)
        plan = json.loads(out)
        self.assertIn(plan["elevation_dem"]["status"], ("ok", "partial"))
        self.assertIn(plan["night"]["status"], ("night", "daylight"))

    def test_dem_plan_offline_keeps_file_elevation(self):
        def down(url):
            raise urllib.error.URLError("hors ligne")

        rc, out, err = self._run(["--dem"], down)
        self.assertEqual(rc, 0)
        self.assertEqual(json.loads(out)["elevation_dem"]["status"], "unavailable")
        self.assertIn("altitudes du fichier conservées", err)


class TestAssumptions(unittest.TestCase):
    def test_assumptions_cover_resolution_privacy_and_licences(self):
        for key in ("resolution", "horizontal_error", "gain_reference", "thinning", "privacy", "cache", "rate_limits"):
            self.assertIn(key, D.ASSUMPTIONS)
        self.assertIn("Etalab", D.ATTRIBUTION["ign"])
        self.assertIn("Copernicus", D.ATTRIBUTION["open-meteo"])
        self.assertIn("dem_series", EL.ASSUMPTIONS)


if __name__ == "__main__":
    unittest.main()
