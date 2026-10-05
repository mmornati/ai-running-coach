"""Palier A — tableau de bord de bout en bout : index, serveur, lanceur, installation.

Le serveur tourne pour de vrai (port libre choisi par le système) sur un
workspace synthétique au contrat (`tests/lib/synthetic.py`).
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request

from tests.lib.asserts import InstallAsserts
from tests.lib.sandbox import Sandbox
from tests.lib.synthetic import build

TODAY = "2026-09-23"


class Server:
    """Lance une commande qui imprime « URL: … » et la garde vivante le temps du test."""

    def __init__(self, sb, argv, cwd=None, **env):
        self.proc = subprocess.Popen(argv, cwd=str(cwd or sb.repo), env=sb.env(**env), stdout=subprocess.PIPE,
                                     stderr=subprocess.PIPE, text=True, start_new_session=True)
        self.url = None
        for _ in range(40):
            line = self.proc.stdout.readline()
            if not line:
                break
            if "URL: " in line:
                self.url = line.split("URL: ", 1)[1].strip()
                break

    def get(self, path, host=None, method="GET"):
        req = urllib.request.Request(self.url.rstrip("/") + path, method=method)
        if host:
            req.add_header("Host", host)
        try:
            with urllib.request.urlopen(req, timeout=10) as res:
                return res.status, res.read(), dict(res.headers)
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read(), dict(exc.headers)

    def stop(self):
        try:
            os.killpg(self.proc.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        self.proc.wait(timeout=10)


class TestDashboardServer(InstallAsserts):
    def setUp(self):
        self.sb = Sandbox().__enter__()
        self.ws = build(self.sb.root / "ws", days=90, today=__import__("datetime").date.fromisoformat(TODAY))
        self.server = Server(self.sb, ["python3", str(self.sb.repo / "scripts/arc_serve.py"),
                                       "--workspace", str(self.ws), "--port", "0", "--today", TODAY])
        self.assertIsNotNone(self.server.url, self.server.proc.stderr.read() if self.server.proc.poll() is not None else "pas d'URL")

    def tearDown(self):
        self.server.stop()
        self.sb.__exit__(None, None, None)

    def test_listens_on_loopback_only(self):
        """Par défaut, 127.0.0.1 : seul le conteneur Docker écoute ailleurs (--listen)."""
        self.assertTrue(self.server.url.startswith("http://127.0.0.1:"), self.server.url)

    def test_api_serves_indexed_data(self):
        status, body, _ = self.server.get("/api/summary")
        self.assertEqual(status, 200)
        summary = json.loads(body)
        self.assertEqual(summary["today"], TODAY)
        self.assertGreater(summary["counts"]["activities"], 20)
        self.assertEqual(summary["incomplete_files"], 0, "le workspace synthétique est entièrement au contrat")
        form = json.loads(self.server.get("/api/form?days=60")[1])
        self.assertEqual(len(form["series"]), 60)
        self.assertIsNotNone(form["series"][-1]["fitness"])

    def test_static_page_and_csp(self):
        status, body, headers = self.server.get("/")
        self.assertEqual(status, 200)
        self.assertIn(b"js/app.js", body)
        self.assertIn("default-src 'self'", headers.get("Content-Security-Policy", ""))

    def test_rejects_foreign_host(self):
        """Protection contre le DNS rebinding : un Host étranger est refusé."""
        self.assertEqual(self.server.get("/api/summary", host="evil.example")[0], 403)

    def test_healthz(self):
        """Sonde du conteneur : répond sans réindexer, derrière le même contrôle d'hôte."""
        status, body, _ = self.server.get("/healthz")
        self.assertEqual((status, json.loads(body)), (200, {"status": "ok"}))
        self.assertEqual(self.server.get("/healthz", host="evil.example")[0], 403)

    def test_read_only(self):
        self.assertEqual(self.server.get("/api/summary", method="POST")[0], 405)

    def test_no_path_traversal(self):
        self.assertEqual(self.server.get("/..%2f..%2fconfig/workspace.toml")[0], 404)
        self.assertEqual(self.server.get("/../scripts/arc_serve.py")[0], 404)

    def test_gear_inspection_history_and_photo_route(self):
        """#135 : l'historique d'inspection est dans `/api/summary`, et la photo CITÉE par une
        inspection est servie (image seulement) — rien d'autre du workspace."""
        summary = json.loads(self.server.get("/api/summary")[1])
        entry = next(e for e in summary["gear_inspections"]["gear"] if e["gear_id"] == "adizero-sl")
        self.assertEqual(len(entry["inspections"]), 2)
        self.assertEqual(entry["latest"]["condition"], "yellow")
        self.assertEqual(entry["condition_change"], "worse")
        photo = entry["latest"]["photos"][0]
        status, body, headers = self.server.get("/media/gear-photo?path=" + urllib.parse.quote(photo, safe=""))
        self.assertEqual(status, 200)
        self.assertEqual(headers.get("Content-Type"), "image/png")
        self.assertEqual(headers.get("X-Content-Type-Options"), "nosniff")
        self.assertTrue(body.startswith(b"\x89PNG"))
        for bad in ("planning/Runner_Profile.md", "gear/photos/../../planning/Runner_Profile.md",
                    "gear/photos/absente.png", "/etc/passwd", "", "gear/photos/a\x00.png"):
            self.assertEqual(self.server.get("/media/gear-photo?path=" + urllib.parse.quote(bad, safe=""))[0],
                             404, bad)
        self.assertEqual(self.server.get("/media/gear-photo")[0], 404)
        self.assertEqual(self.server.get("/media/gear-photo?path=x", host="evil.example")[0], 403)
        self.assertEqual(self.server.get("/media/gear-photo?path=x", method="POST")[0], 405)

    def test_gear_detail_route(self):
        """#147 : `/api/gear/<id>` — paire (bilan, mois, séances), paire retirée, objet d'équipement ;
        inconnu / identifiant invalide → 404 ; même contrôle d'hôte et lecture seule que les autres routes."""
        status, body, _ = self.server.get("/api/gear/adizero-sl")
        self.assertEqual(status, 200)
        shoe = json.loads(body)
        self.assertEqual((shoe["kind"], shoe["gear_id"]), ("shoe", "adizero-sl"))
        self.assertTrue(shoe["sessions"] and shoe["monthly"])
        self.assertEqual(shoe["career"]["distance_m"], shoe["shoe"]["distance_m"])
        summary = json.loads(self.server.get("/api/summary")[1])
        listed = next(s for s in summary["gear"]["shoes"] if s["gear_id"] == "adizero-sl")
        self.assertEqual(listed["distance_m"], shoe["shoe"]["distance_m"])
        retired = json.loads(self.server.get("/api/gear/nike-pegasus")[1])
        self.assertTrue(retired["retired"])
        item = json.loads(self.server.get("/api/gear/poche-eau")[1])
        self.assertEqual(item["kind"], "equipment")
        self.assertIn("trail-long", item["kits"])
        for bad in ("absent", "Adizero-SL", "..", "a%2Fb", "%2e%2e%2fsummary"):
            self.assertEqual(self.server.get("/api/gear/" + bad)[0], 404, bad)
        self.assertEqual(self.server.get("/api/gear/adizero-sl", host="evil.example")[0], 403)
        self.assertEqual(self.server.get("/api/gear/adizero-sl", method="POST")[0], 405)

    def test_new_file_appears_without_restart(self):
        """Un fichier écrit par un agent apparaît sans relancer le serveur."""
        self.server.stop()
        self.server = Server(self.sb, ["python3", str(self.sb.repo / "scripts/arc_serve.py"),
                                       "--workspace", str(self.ws), "--port", "0", "--today", TODAY],
                             ARC_DASHBOARD_REFRESH_S="0")
        before = [r["title"] for r in json.loads(self.server.get("/api/reports")[1])["reports"]]
        self.assertNotIn("Bilan test", before)
        (self.ws / "rapports/2026-09-23_rapport.md").write_text(
            '# Bilan\n\n```arc\n{"arc": 1, "kind": "report", "date": "2026-09-23", "report_type": "weekly", "title": "Bilan test"}\n```\n\nTexte.\n',
            encoding="utf-8")
        # La réindexation tourne en arrière-plan (jamais dans la requête) : le fichier
        # apparaît au passage suivant du fil d'index, sans relance du serveur.
        deadline = time.monotonic() + 15
        after = []
        while time.monotonic() < deadline and "Bilan test" not in after:
            after = [r["title"] for r in json.loads(self.server.get("/api/reports")[1])["reports"]]
            time.sleep(0.1)
        self.assertIn("Bilan test", after)


class TestDashboardAnalysisView(InstallAsserts):
    """#50 — la vue « Analyse » (`#/analyse`) rassemble les tendances FIT (#43/#45-49)
    sorties de « Forme & charge » : verrouille que le bundle JS sert bien cette route
    et que chacun des endpoints qu'elle consomme répond sur un workspace synthétique
    à échantillons FIT (`--with-samples`), y compris `/api/climb-segments` (#49),
    servi depuis #49 mais jamais consommé par aucune vue avant #50."""

    def setUp(self):
        self.sb = Sandbox().__enter__()
        self.ws = build(self.sb.root / "ws", days=120, today=__import__("datetime").date.fromisoformat(TODAY),
                        with_samples=True)
        self.server = Server(self.sb, ["python3", str(self.sb.repo / "scripts/arc_serve.py"),
                                       "--workspace", str(self.ws), "--port", "0", "--today", TODAY])
        self.assertIsNotNone(self.server.url, self.server.proc.stderr.read() if self.server.proc.poll() is not None else "pas d'URL")

    def tearDown(self):
        self.server.stop()
        self.sb.__exit__(None, None, None)

    def test_app_js_wires_the_analyse_route(self):
        """Régression : la route `analyse` (nav + `ROUTES`) doit rester câblée dans le
        bundle statique servi — un renommage de route sans mise à jour du HTML/JS
        casserait silencieusement le lien de nav plutôt que de faire échouer un test."""
        status, body, _ = self.server.get("/js/app.js")
        self.assertEqual(status, 200)
        text = body.decode("utf-8")
        self.assertIn('analyse: viewAnalyse', text)
        # L'entrée de nav vit dans `nav.js` (liste partagée avec la page Coach), importé par app.js.
        self.assertIn('from "./nav.js"', text)
        status, nav, _ = self.server.get("/js/nav.js")
        self.assertEqual(status, 200)
        self.assertIn('["analyse", "Analyse"]', nav.decode("utf-8"))

    def test_analyse_view_endpoints_respond(self):
        """Chaque endpoint consommé par `viewAnalyse` (`web/js/app.js`) répond 200 sur
        un workspace à échantillons FIT, `climb-segments` compris (#49)."""
        for path in ("/api/load?weeks=26", "/api/decoupling?weeks=26", "/api/vam?weeks=26",
                     "/api/descent?weeks=26", "/api/durability?weeks=26", "/api/climb-segments",
                     "/api/energy-trend?weeks=26"):
            status, body, _ = self.server.get(path)
            self.assertEqual(status, 200, path)
            json.loads(body)  # une réponse JSON valide, quelle que soit sa forme

    def test_climb_segments_route_has_expected_shape(self):
        """#49/#50 : `/api/climb-segments` (jamais affiché avant #50) rend une liste de
        segments avec un `segment_id` exploitable par `#/montee/<id>` côté UI — jamais
        de coordonnée GPS (`arc_climb_match.ASSUMPTIONS["privacy"]`)."""
        status, body, _ = self.server.get("/api/climb-segments")
        self.assertEqual(status, 200)
        segments = json.loads(body)["segments"]
        self.assertGreater(len(segments), 0, "workspace --with-samples : au moins un segment de montée attendu")
        seg = segments[0]
        for key in ("segment_id", "location", "gain_m", "distance_m", "avg_grade", "grade_class", "occurrences"):
            self.assertIn(key, seg)
        for leaked in ("lat", "lon", "latitude", "longitude"):
            self.assertNotIn(leaked, seg, "aucune coordonnée GPS ne doit être exposée")

    def test_energy_trend_endpoint_has_expected_shape(self):
        """`/api/energy-trend` rend au moins une séance avec un `model_kcal`
        calculable sur un workspace à échantillons FIT ET poids connu
        (`tests.lib.synthetic.build` en écrit un jour sur cinq) — jamais un second
        calcul du delta/flag (voir `arc_index.energy_trend`, réutilise
        `_energy_session_for_activity_row`, même fonction que `/api/activity/<id>.
        energy`)."""
        status, body, _ = self.server.get("/api/energy-trend?weeks=26")
        self.assertEqual(status, 200)
        trend = json.loads(body)
        for key in ("model_id", "window_weeks", "delta_alert_pct", "sessions", "sessions_n",
                    "measured_n", "delta_median_pct"):
            self.assertIn(key, trend)
        measured = [s for s in trend["sessions"] if s.get("model_kcal") is not None]
        self.assertGreater(len(measured), 0, "workspace --with-samples : au moins une dépense "
                           "énergétique modèle calculable attendue")
        for s in measured:
            self.assertIn("delta_pct", s)
            self.assertIn("flag", s)


class TestDashboardGaitApi(InstallAsserts):
    """#151 — `/api/gait` (carte « Foulée » de la vue Santé) sur un workspace à échantillons FIT
    (dynamique de course synthétique, `tests.lib.synthetic.add_running_dynamics`) ET deux inspections
    de paires différentes (indices d'attaque opposés) : mesures, confiance, désaccords, forme JSON."""

    def setUp(self):
        self.sb = Sandbox().__enter__()
        self.ws = build(self.sb.root / "ws", days=120, today=__import__("datetime").date.fromisoformat(TODAY),
                        with_samples=True)
        self.server = Server(self.sb, ["python3", str(self.sb.repo / "scripts/arc_serve.py"),
                                       "--workspace", str(self.ws), "--port", "0", "--today", TODAY])
        self.assertIsNotNone(self.server.url, self.server.proc.stderr.read() if self.server.proc.poll() is not None else "pas d'URL")

    def tearDown(self):
        self.server.stop()
        self.sb.__exit__(None, None, None)

    def get(self, path):
        status, body, _ = self.server.get(path)
        self.assertEqual(status, 200, path)
        return json.loads(body)

    def test_gait_shape_and_measured_dynamics(self):
        g = self.get("/api/gait")
        for key in ("window", "sport_scope", "dynamics", "inspections", "contradictions", "confidence",
                    "balance_side_verified", "caveat"):
            self.assertIn(key, g)
        self.assertEqual(g["window"]["weeks"], 26)
        self.assertFalse(g["balance_side_verified"])
        for metric in ("ground_contact_s", "stance_balance_pct", "vertical_oscillation_m",
                       "vertical_ratio_pct", "step_length_m", "cadence_spm"):
            self.assertGreater(g["dynamics"][metric]["n"], 5, metric)
        balance = g["dynamics"]["stance_balance_pct"]
        self.assertLess(balance["n"], g["dynamics"]["ground_contact_s"]["n"],
                        "une séance sur quatre n'a pas de balance : jamais comblée par 50 %")
        self.assertFalse(balance["side_named"])
        gct = g["dynamics"]["ground_contact_s"]["mean"]
        self.assertTrue(0.2 < gct < 0.3, gct)

    def test_confidence_and_contradictions(self):
        g = self.get("/api/gait")
        conf = g["confidence"]
        self.assertEqual(conf["inspections"], 3)
        self.assertEqual(conf["pairs_inspected"], 2)
        self.assertEqual((conf["dynamics_level"], conf["inspections_level"]), ("ok", "ok"))
        self.assertLessEqual(conf["sessions_with_balance"], conf["sessions_with_dynamics"])
        codes = {c["code"] for c in g["contradictions"]}
        self.assertIn("strike_hint_differs_across_pairs", codes)
        for c in g["contradictions"]:
            self.assertIn(c["resolution"], ("measure_wins", "unresolved"))

    def test_weeks_parameter_is_clamped(self):
        self.assertEqual(self.get("/api/gait?weeks=4")["window"]["weeks"], 4)
        self.assertEqual(self.get("/api/gait?weeks=9999")["window"]["weeks"], 104)
        self.assertEqual(self.get("/api/gait?weeks=abc")["window"]["weeks"], 26)

    def test_no_gps_and_no_health_data_leak(self):
        text = json.dumps(self.get("/api/gait"))
        for leaked in ("lat_deg", "lon_deg", "latitude", "hrv", "readiness", "resting_hr"):
            self.assertNotIn(leaked, text)

    def test_app_js_wires_the_card_in_the_health_view(self):
        status, body, _ = self.server.get("/js/app.js")
        text = body.decode("utf-8")
        self.assertIn('api("gait")', text)
        self.assertIn("function gaitCard", text)
        self.assertIn("gait.mount()", text)


class TestDashboardAltitudeExposureApi(InstallAsserts):
    """#185 — `/api/altitude-exposure` (carte « Exposition à l'altitude » de la vue Santé) : forme,
    paramètre `days`, aucune fuite de position, câblage de la carte."""

    def setUp(self):
        self.sb = Sandbox().__enter__()
        self.ws = build(self.sb.root / "ws", days=120, today=__import__("datetime").date.fromisoformat(TODAY),
                        with_samples=True)
        self.server = Server(self.sb, ["python3", str(self.sb.repo / "scripts/arc_serve.py"),
                                       "--workspace", str(self.ws), "--port", "0", "--today", TODAY])
        self.assertIsNotNone(self.server.url, self.server.proc.stderr.read() if self.server.proc.poll() is not None else "pas d'URL")

    def tearDown(self):
        self.server.stop()
        self.sb.__exit__(None, None, None)

    def get(self, path):
        status, body, _ = self.server.get(path)
        self.assertEqual(status, 200, path)
        return json.loads(body)

    def test_shape_default_windows(self):
        a = self.get("/api/altitude-exposure")
        for key in ("status", "note", "windows", "thresholds_m", "assumption"):
            self.assertIn(key, a)
        self.assertEqual(sorted(a["windows"]), ["14", "28"])
        self.assertEqual(a["thresholds_m"], [1500, 2000])
        self.assertIn(a["status"], ("none", "exposed", "no_altitude", "no_activity"))
        w = a["windows"]["28"]
        for key in ("sessions", "sessions_with_altitude", "sessions_without_altitude", "thresholds"):
            self.assertIn(key, w)

    def test_days_parameter(self):
        self.assertEqual(list(self.get("/api/altitude-exposure?days=7")["windows"]), ["7"])
        self.assertEqual(list(self.get("/api/altitude-exposure?days=9999")["windows"]), ["365"])
        self.assertEqual(sorted(self.get("/api/altitude-exposure?days=abc")["windows"]), ["14", "28"])

    def test_no_gps_leak(self):
        text = json.dumps(self.get("/api/altitude-exposure"))
        for leaked in ("lat_deg", "lon_deg", "latitude", "longitude", "hrv", "readiness"):
            self.assertNotIn(leaked, text)

    def test_app_js_wires_the_card_in_the_health_view(self):
        status, body, _ = self.server.get("/js/app.js")
        text = body.decode("utf-8")
        self.assertIn('api("altitude-exposure")', text)
        self.assertIn("function altitudeCard", text)


class TestDashboardAnalysisViewEmptyState(InstallAsserts):
    """#50, revue de code (should-fix 1) : sur un workspace SANS échantillon FIT nulle
    part (`build(..., with_samples=False)`, le défaut), `viewAnalyse` doit afficher
    l'état vide global (pointeur vers le skill `fit-download`) plutôt qu'un mur de
    sections vides — ou, pire, une seule section (« Durabilité ») qui reste affichée
    seule car son propre message (« N sorties longues, aucune éligible ») ne dépend
    QUE de `duration_s` déclaré au contrat, jamais de la présence réelle
    d'échantillons FIT (contrairement aux quatre autres tendances). Un rendu DOM
    complet n'est pas disponible à ce palier (pas de navigateur dans le harnais de
    test) : ce test verrouille directement la CONDITION dont dépend `hasFitSamples`
    côté JS (`web/js/app.js::viewAnalyse`) sur les données réellement servies par
    chaque endpoint qu'elle consomme — si l'un de ces endpoints se mettait à
    retourner une valeur non nulle sur un workspace sans FIT, ce test le
    détecterait avant que l'état vide ne cesse de s'afficher en pratique."""

    def setUp(self):
        self.sb = Sandbox().__enter__()
        self.ws = build(self.sb.root / "ws", days=120, today=__import__("datetime").date.fromisoformat(TODAY),
                        sport="road")  # with_samples=False (défaut) : aucun `activities/fit/*.json`
        self.server = Server(self.sb, ["python3", str(self.sb.repo / "scripts/arc_serve.py"),
                                       "--workspace", str(self.ws), "--port", "0", "--today", TODAY])
        self.assertIsNotNone(self.server.url, self.server.proc.stderr.read() if self.server.proc.poll() is not None else "pas d'URL")

    def tearDown(self):
        self.server.stop()
        self.sb.__exit__(None, None, None)

    def test_no_endpoint_reports_fit_derived_data(self):
        """Reproduit `hasFitSamples` (`web/js/app.js::viewAnalyse`) terme à terme : si
        tous ces termes sont faux, la vue doit basculer sur l'état vide global —
        jamais laisser `durabilitySection` seule masquer l'absence de FIT."""
        polarisation_weeks = json.loads(self.server.get("/api/load?weeks=26")[1])["polarisation_weeks"]
        decoupling = json.loads(self.server.get("/api/decoupling?weeks=26")[1])
        vam = json.loads(self.server.get("/api/vam?weeks=26")[1])
        descent = json.loads(self.server.get("/api/descent?weeks=26")[1])
        durability = json.loads(self.server.get("/api/durability?weeks=26")[1])
        segments = json.loads(self.server.get("/api/climb-segments")[1])["segments"]
        energy = json.loads(self.server.get("/api/energy-trend?weeks=26")[1])

        self.assertFalse(any(w.get("polarisation") for w in polarisation_weeks),
                         "aucune semaine ne devrait avoir de polarisation sans échantillons FIT")
        self.assertFalse(any(p.get("decoupling_pct") is not None for p in decoupling["points"]),
                         "aucun découplage mesuré n'est attendu sans échantillons FIT")
        self.assertFalse(any(p.get("best_climb_vam_elapsed_m_h") is not None for p in vam["points"]),
                         "aucune VAM n'est attendue sans échantillons FIT")
        self.assertEqual(descent["classes"], {}, "aucune classe de descente sans échantillons FIT")
        # `durability.long_runs` PEUT être > 0 (des sorties longues DÉCLARÉES existent
        # sans aucun FIT, c'est précisément le piège verrouillé ici) — seul
        # `gap_fade_pct` (dérivé des échantillons) doit rester nul partout.
        self.assertFalse(any(p.get("gap_fade_pct") is not None for p in durability["points"]),
                         "aucun fade GAP n'est attendu sans échantillons FIT, même si des sorties longues existent")
        self.assertEqual(segments, [], "aucun segment de montée sans échantillons FIT")
        # `model_kcal` dépend des échantillons FIT (`arc_energy.
        # energy_from_samples`, voir `arc_index.compute_metrics`) au même titre que
        # les quatre tendances ci-dessus — jamais calculable sans eux, quel que soit
        # le poids connu par ailleurs.
        self.assertFalse(any(s.get("model_kcal") is not None for s in energy["sessions"]),
                         "aucune dépense énergétique modèle attendue sans échantillons FIT")


class TestDashboardHealthMorningCheck(InstallAsserts):
    """#34/#37 — la ligne de base HRV personnelle et la dette de sommeil sont deux
    calculs dérivés de données de santé : ni l'un ni l'autre ne doit apparaître dans
    `/api/health` (ou `/api/summary` pour la dette) hors de
    `[health].morning_check = "full"` — jamais en `"minimal"` (readiness seule) ni en
    `"off"` (aucune donnée de santé)."""

    HRV_KEYS = ("hrv_ln_mean7", "hrv_personal_mean7_ms", "hrv_cv7_pct",
                "hrv_personal_low_ms", "hrv_personal_high_ms", "hrv_personal_status")
    SLEEP_DEBT_KEYS = ("sleep_debt_7d_s", "nights_counted", "sleep_need_s")

    def _server_with_mode(self, sb, mode):
        ws = build(sb.root / "ws", days=90, today=__import__("datetime").date.fromisoformat(TODAY))
        (ws / "config/workspace.user.toml").write_text(
            f'[sport]\nprimary = "trail"\n\n[health]\nmorning_check = "{mode}"\n', encoding="utf-8")
        server = Server(sb, ["python3", str(sb.repo / "scripts/arc_serve.py"),
                             "--workspace", str(ws), "--port", "0", "--today", TODAY])
        self.assertIsNotNone(server.url, server.proc.stderr.read() if server.proc.poll() is not None else "pas d'URL")
        return server

    def _assert_no_personal_hrv_keys(self, mode):
        with Sandbox() as sb:
            server = self._server_with_mode(sb, mode)
            try:
                status, body, _ = server.get("/api/health?days=14")
                self.assertEqual(status, 200)
                data = json.loads(body)
                self.assertEqual(data["morning_check"], mode)
                for point in data["series"]:
                    for key in self.HRV_KEYS + self.SLEEP_DEBT_KEYS:
                        self.assertNotIn(key, point,
                                        f"morning_check={mode} : « {key} » ne devrait pas apparaître ({point})")
                summary_status, summary_body, _ = server.get("/api/summary")
                self.assertEqual(summary_status, 200)
                summary = json.loads(summary_body)
                self.assertIsNone(summary.get("sleep_debt"),
                                  f"morning_check={mode} : /api/summary.sleep_debt devrait être null ({summary.get('sleep_debt')})")
            finally:
                server.stop()

    def test_minimal_has_no_personal_baseline(self):
        self._assert_no_personal_hrv_keys("minimal")

    def test_off_has_no_personal_baseline(self):
        self._assert_no_personal_hrv_keys("off")


class TestDashboardBehindProxy(InstallAsserts):
    """Le conteneur Docker : le proxy présente le tableau de bord sous un nom public."""

    def test_public_name_accepted_foreign_refused(self):
        with Sandbox() as sb:
            ws = build(sb.root / "ws", days=10)
            server = Server(sb, ["python3", str(sb.repo / "scripts/arc_serve.py"), "--workspace", str(ws),
                                 "--port", "0", "--memory"], ARC_DASHBOARD_ALLOWED_HOSTS="coach.example.org, autre.example.org")
            try:
                self.assertIsNotNone(server.url)
                for host in ("coach.example.org", "Coach.Example.org", "coach.example.org:443", "autre.example.org"):
                    self.assertEqual(server.get("/api/summary", host=host)[0], 200, host)
                for host in ("evil.example", "coach.example.org.evil.example", "example.org"):
                    self.assertEqual(server.get("/api/summary", host=host)[0], 403, host)
                self.assertEqual(server.get("/api/summary")[0], 200, "la boucle locale reste acceptée (sonde)")
            finally:
                server.stop()

    def test_exposed_without_public_name_is_refused(self):
        """Défaut verrouillé : écouter sur le réseau sans nom public déclaré ne servirait
        que des 403 — le serveur refuse de démarrer et dit pourquoi."""
        with Sandbox() as sb:
            ws = build(sb.root / "ws", days=3)
            proc = sb.run(["python3", str(sb.repo / "scripts/arc_serve.py"), "--workspace", str(ws), "--memory",
                           "--port", "0", "--listen", "0.0.0.0"])
            self.assertEqual(proc.returncode, 1, proc.stderr)
            self.assertIn("--allowed-host", proc.stderr)

    def test_read_only_workspace_with_memory_index(self):
        """Le conteneur monte le workspace en lecture seule : --memory n'écrit rien."""
        with Sandbox() as sb:
            ws = build(sb.root / "ws", days=10)
            server = Server(sb, ["python3", str(sb.repo / "scripts/arc_serve.py"), "--workspace", str(ws),
                                 "--port", "0", "--memory"])
            try:
                self.assertEqual(server.get("/api/summary")[0], 200)
            finally:
                server.stop()
            self.assertFalse((ws / ".arc").exists(), "--memory a écrit dans le workspace")


class TestDashboardLauncher(InstallAsserts):
    def test_help(self):
        with Sandbox() as sb:
            proc = sb.script("dashboard.sh", "--help")
            self.assertSucceeded(proc)
            self.assertOutputContains(proc, "127.0.0.1")

    def test_serves_workspace_and_writes_only_arc(self):
        with Sandbox() as sb:
            ws = build(sb.root / "ws", days=30)
            before = sorted(p.relative_to(ws).as_posix() for p in ws.rglob("*") if ".arc" not in p.parts)
            env = sb.env(ARC_WORKSPACE=str(ws))
            proc = subprocess.Popen([str(sb.repo / "scripts/dashboard.sh"), "--no-open", "--port", "0"], cwd=str(sb.repo),
                                    env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True)
            try:
                url = None
                for _ in range(40):
                    line = proc.stdout.readline()
                    if "URL: " in line:
                        url = line.split("URL: ", 1)[1].strip()
                        break
                self.assertIsNotNone(url, "dashboard.sh n'a pas annoncé d'URL")
                with urllib.request.urlopen(url + "api/summary", timeout=10) as res:
                    self.assertEqual(res.status, 200)
            finally:
                os.killpg(proc.pid, signal.SIGTERM)
                proc.wait(timeout=10)
            after = sorted(p.relative_to(ws).as_posix() for p in ws.rglob("*") if ".arc" not in p.parts)
            self.assertEqual(before, after, "le tableau de bord a écrit hors de .arc/")
            self.assertIsFile(ws / ".arc/coach.db")

    def test_bad_port_is_refused(self):
        with Sandbox() as sb:
            self.assertFailed(sb.script("dashboard.sh", "--port", "abc", "--no-open"))

    def test_corrupt_derived_index_is_rebuilt_automatically(self):
        with Sandbox() as sb:
            ws = build(sb.root / "ws", days=10)
            arc = ws / ".arc"
            arc.mkdir()
            (arc / "coach.db").write_bytes(b"ancienne base sqlite corrompue")
            server = Server(sb, [str(sb.repo / "scripts/dashboard.sh"), "--no-open", "--port", "0"],
                            ARC_WORKSPACE=str(ws))
            try:
                self.assertIsNotNone(
                    server.url,
                    server.proc.stderr.read() if server.proc.poll() is not None else "pas d'URL",
                )
                self.assertEqual(server.get("/api/summary")[0], 200)
            finally:
                server.stop()


class TestInstallWorkspaceWiring(InstallAsserts):
    OLD_BLOCK = """
# ai-running-coach — généré par install.sh (ne pas éditer ce bloc)
/agents/
/skills/
/AGENTS.md
/config/workspace.toml
config/workspace.user.toml
/.mcp.json
/.claude/
/logs/
# fin du bloc ai-running-coach
"""

    def test_existing_workspace_gains_new_ignores(self):
        """Défaut verrouillé : le bloc n'était écrit qu'une fois, jamais complété."""
        with Sandbox() as sb:
            ws = sb.root / "prive"
            ws.mkdir()
            (ws / ".gitignore").write_text("mes-notes/\n" + self.OLD_BLOCK)
            self.assertSucceeded(sb.install("--no-auth", "--workspace", str(ws)))
            lines = (ws / ".gitignore").read_text().splitlines()
            for entry in ("/.arc/", "/scripts", "/.opencode/", "*.bak"):
                self.assertEqual(lines.count(entry), 1, f"{entry} absent ou en double")
            self.assertIn("mes-notes/", lines, "une ligne de l'utilisateur a disparu")
            end = lines.index("# fin du bloc ai-running-coach")
            self.assertLess(lines.index("/.arc/"), end, "ajout hors du bloc généré")
            before = (ws / ".gitignore").read_text()
            self.assertSucceeded(sb.install("--no-auth", "--workspace", str(ws)))
            self.assertEqual((ws / ".gitignore").read_text(), before, "relance non idempotente")

    def test_scripts_linked_for_agents(self):
        """Les agents appellent `python3 scripts/arc_index.py` depuis le workspace."""
        with Sandbox() as sb:
            ws = sb.root / "prive"
            ws.mkdir()
            self.assertSucceeded(sb.install("--no-auth", "--workspace", str(ws)))
            self.assertIsSymlink(ws / "scripts")
            (ws / "medical").mkdir(exist_ok=True)
            (ws / "medical/2026-09-23_health.md").write_text(
                '# Santé\n\n```arc\n{"arc": 1, "kind": "health", "date": "2026-09-23", "morning_check": "full", "resting_hr_bpm": 39}\n```\n')
            proc = sb.run(["python3", "scripts/arc_index.py", "--validate", "medical/2026-09-23_health.md"], cwd=ws)
            self.assertSucceeded(proc)
            self.assertOutputContains(proc, "ok:")

    def test_engine_links_never_committed(self):
        """Défaut verrouillé : « /scripts/ » ne couvre pas un lien symbolique, et
        `git add -A` (git_autocommit) versionnait le lien vers le moteur ; de même
        pour les sauvegardes *.bak laissées par l'installation."""
        with Sandbox() as sb:
            ws = sb.root / "prive"
            ws.mkdir()
            self.assertSucceeded(sb.run(["git", "init", "-q"], cwd=ws))
            self.assertSucceeded(sb.install("--no-auth", "--workspace", str(ws)))
            (ws / "config/workspace.user.toml.bak").write_text("[coaching]\n")
            status = sb.run(["git", "status", "--porcelain", "--untracked-files=all"], cwd=ws).stdout
            for leaked in ("scripts", ".bak", "AGENTS.md", "agents/", "skills/"):
                self.assertNotIn(leaked, status, f"{leaked} apparaît dans git :\n{status}")


class TestIndexNeverCommitted(InstallAsserts):
    """Défaut verrouillé : dans un workspace dont le .gitignore n'a pas /.arc/, la
    réindexation de la synchro suivie de `git add -A` aurait versionné la base."""

    def test_arc_dir_ignores_itself(self):
        with Sandbox() as sb:
            ws = build(sb.root / "ws", days=10)
            (ws / ".gitignore").write_text("logs/\n")          # ancien .gitignore, sans /.arc/
            self.assertSucceeded(sb.run(["git", "init", "-q"], cwd=ws))
            self.assertSucceeded(sb.run(["python3", str(sb.repo / "scripts/arc_index.py"), "--workspace", str(ws)]))
            self.assertIsFile(ws / ".arc/coach.db")
            status = sb.run(["git", "status", "--porcelain", "--untracked-files=all"], cwd=ws).stdout
            self.assertNotIn(".arc/", status, f"l'index apparaît dans git :\n{status}")


class TestCorruptIndexRepairScope(InstallAsserts):
    def test_explicit_db_that_is_not_sqlite_is_never_replaced(self):
        """La réparation ne vise que l'index : un `--db` mal orienté échoue sans écraser le fichier."""
        with Sandbox() as sb:
            ws = build(sb.root / "ws", days=3)
            target = ws / "planning/Runner_Profile.md"
            target.parent.mkdir(parents=True, exist_ok=True)
            content = "# Mon profil\n\n" + "Contenu à ne jamais perdre.\n" * 20
            target.write_text(content, encoding="utf-8")
            proc = sb.run(["python3", str(sb.repo / "scripts/arc_index.py"),
                           "--workspace", str(ws), "--db", str(target)])
            self.assertNotEqual(proc.returncode, 0)
            self.assertEqual(target.read_text(encoding="utf-8"), content)
