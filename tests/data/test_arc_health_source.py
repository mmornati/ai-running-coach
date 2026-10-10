"""Palier D — source de la santé (#218, épopée #216) : `[health].source`, provenance des fichiers santé,
lignes de base par source. Aucun réseau. Dates fixes : jamais de donnée réelle."""

from __future__ import annotations

import contextlib
import io
import json
import shutil
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))
import arc_contract as C  # noqa: E402
import arc_decision_effects as DE  # noqa: E402
import arc_health_source as HS  # noqa: E402
import arc_index as I  # noqa: E402
import arc_serve as S  # noqa: E402

TODAY = date(2026, 9, 30)


def iso(offset: int) -> str:
    return (TODAY + timedelta(days=offset)).isoformat()


def arc(block: dict) -> str:
    return f"# Titre\n\n```arc\n{json.dumps(block)}\n```\n\nTexte.\n"


def health_block(day: str, hrv=None, rhr=None, source=None, provider=None, **extra) -> dict:
    block = {"arc": 1, "kind": "health", "date": day, "morning_check": "full"}
    if hrv is not None:
        block["hrv_overnight_ms"] = hrv
    if rhr is not None:
        block["resting_hr_bpm"] = rhr
    if source:
        block["health_source"] = source
    if provider:
        block["health_provider"] = provider
    block.update(extra)
    return block


def validate(block: dict):
    return C.validate(block)


class TestConfigResolution(unittest.TestCase):
    def resolve(self, config, warn=False):
        buf = io.StringIO()
        with contextlib.redirect_stderr(buf):
            out = HS.effective_health_source(config, warn=warn)
        return out, buf.getvalue()

    def test_absent_key_is_primary(self):
        self.assertEqual(self.resolve({})[0], ("primary", ""))
        self.assertEqual(self.resolve({"health": {"morning_check": "full"}})[0], ("primary", ""))
        self.assertEqual(self.resolve({"health": {"source": ""}})[0], ("primary", ""))

    def test_primary_is_silent(self):
        out, err = self.resolve({"health": {"source": "primary"}}, warn=True)
        self.assertEqual((out, err), (("primary", ""), ""))

    def test_invalid_value_falls_back_with_warning(self):
        for raw in ("garmin", "OpenWear", 3, True):
            out, err = self.resolve({"health": {"source": raw}}, warn=True)
            self.assertEqual(out, ("primary", ""), raw)
            self.assertIn("avertissement", err)
            self.assertIn("[health].source", err)

    def test_openwearables_with_known_provider(self):
        cfg = {"health": {"source": "OpenWearables ", "openwearables": {"provider": "Oura"}}}
        self.assertEqual(self.resolve(cfg)[0], ("openwearables", "oura"))

    def test_garmin_and_strava_providers_are_refused(self):
        for provider in ("garmin", "strava"):
            cfg = {"health": {"source": "openwearables", "openwearables": {"provider": provider}}}
            out, err = self.resolve(cfg, warn=True)
            self.assertEqual(out, ("primary", ""), provider)
            self.assertIn("refusé", err)

    def test_unknown_provider_stays_openwearables_with_warning(self):
        """Faute de frappe : on n'abandonne pas Open Wearables en silence (jamais de repli sur Garmin)."""
        cfg = {"health": {"source": "openwearables", "openwearables": {"provider": "fitbit-legacy"}}}
        out, err = self.resolve(cfg, warn=True)
        self.assertEqual(out, ("openwearables", ""))
        self.assertIn("configuration incomplète", err)

    def test_empty_provider_warns_once_and_stays_openwearables(self):
        cfg = {"health": {"source": "openwearables", "openwearables": {"provider": ""}}}
        out, err = self.resolve(cfg, warn=True)
        self.assertEqual(out, ("openwearables", ""))
        self.assertEqual(err.count("configuration incomplète : [health.openwearables].provider vide"), 1)
        self.assertEqual(self.resolve(cfg, warn=False)[1], "")

    def test_settings_warns_only_once(self):
        buf = io.StringIO()
        with contextlib.redirect_stderr(buf):
            conf = I.settings({"health": {"source": "openwearables"}})
        self.assertEqual((conf["health_source"], conf["health_provider"]), ("openwearables", ""))
        self.assertEqual(buf.getvalue().count("configuration incomplète"), 1)

    def test_load_config_nested_merge_keeps_shared_defaults(self):
        tmp = Path(tempfile.mkdtemp(prefix="arc-health-source-cfg-"))
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        (tmp / "config").mkdir()
        (tmp / "config/workspace.toml").write_text(
            '[health]\nsource = "primary"\n\n[health.openwearables]\nprovider = ""\nstale_after_h = 36\n'
            'api_key_file = "~/shared.key"\n', encoding="utf-8")
        (tmp / "config/workspace.user.toml").write_text(
            '[health.openwearables]\nprovider = "oura"\n', encoding="utf-8")
        ow = HS.openwearables_section(I.load_config(tmp))
        self.assertEqual((ow["provider"], ow["stale_after_h"], ow["api_key_file"]), ("oura", 36, "~/shared.key"))
        # une valeur vide du fichier perso gagne encore, dans la sous-table
        (tmp / "config/workspace.user.toml").write_text(
            '[health.openwearables]\napi_key_file = ""\n', encoding="utf-8")
        ow = HS.openwearables_section(I.load_config(tmp))
        self.assertEqual((ow["api_key_file"], ow["stale_after_h"]), ("", 36))

    def test_settings_carry_the_resolved_source(self):
        conf = I.settings({"health": {"source": "bogus"}, "data": {"source": "intervals"}})
        self.assertEqual((conf["health_source"], conf["health_provider"], conf["data_source"]),
                         ("primary", "", "intervals"))
        conf = I.settings({})
        self.assertEqual((conf["health_source"], conf["data_source"]), ("primary", "garmin"))

    def test_shipped_workspace_toml_defaults_to_primary(self):
        cfg = I.load_config(REPO)
        self.assertEqual(HS.effective_health_source(cfg), ("primary", ""))
        self.assertEqual(HS.openwearables_section(cfg)["provider"], "")
        self.assertEqual(HS.openwearables_section(cfg)["stale_after_h"], 36)

    def test_flat_and_nested_toml_forms_are_both_read(self):
        flat = {"health": {"source": "openwearables"}, "health.openwearables": {"provider": "oura"}}
        nested = {"health": {"source": "openwearables", "openwearables": {"provider": "oura"}}}
        self.assertEqual(HS.effective_health_source(flat), ("openwearables", "oura"))
        self.assertEqual(HS.effective_health_source(nested), ("openwearables", "oura"))

    def test_source_key(self):
        self.assertEqual(HS.source_key(None, None, "garmin"), "garmin")
        self.assertEqual(HS.source_key(None, None, "intervals"), "intervals")
        self.assertEqual(HS.source_key("openwearables", "Oura", "garmin"), "openwearables/oura")
        self.assertNotEqual(HS.source_key("openwearables", "oura", "garmin"),
                            HS.source_key("openwearables", "whoop", "garmin"))


class TestContract(unittest.TestCase):
    def score(self, **kw):
        entry = {"category": "readiness", "value": 82, "scale_min": 0, "scale_max": 100, "provider": "oura"}
        entry.update(kw)
        return entry

    def test_new_keys_accepted(self):
        errors, warnings = validate(health_block(
            "2026-09-24", hrv=58, rhr=49, source="openwearables", provider="oura", health_device="Oura Ring 4",
            provider_scores=[self.score(qualifier="GOOD")]))
        self.assertEqual(errors + warnings, [])

    def test_sdnn_accepted_without_rmssd(self):
        errors, warnings = validate(health_block("2026-09-24", rhr=52, source="openwearables", provider="apple",
                                                 hrv_sdnn_ms=44))
        self.assertEqual(errors + warnings, [])

    def test_value_out_of_scale_refused(self):
        errors, _ = validate(health_block("2026-09-24", provider_scores=[self.score(value=120)]))
        self.assertTrue(any("hors de l'échelle" in e for e in errors), errors)

    def test_native_scale_kept_not_rescaled(self):
        """Nightly Recharge Polar 4/6 : valide tel quel sur son échelle 1-6."""
        errors, _ = validate(health_block("2026-09-24", provider_scores=[
            self.score(provider="polar", value=4, scale_min=1, scale_max=6)]))
        self.assertEqual(errors, [])

    def test_missing_scale_refused(self):
        for key in ("scale_min", "scale_max"):
            entry = self.score()
            del entry[key]
            errors, _ = validate(health_block("2026-09-24", provider_scores=[entry]))
            self.assertTrue(any(key in e for e in errors), (key, errors))

    def test_inverted_scale_refused(self):
        errors, _ = validate(health_block("2026-09-24", provider_scores=[self.score(scale_min=10, scale_max=10)]))
        self.assertTrue(any("scale_min" in e for e in errors), errors)

    def test_strain_category_refused(self):
        errors, _ = validate(health_block("2026-09-24", provider_scores=[self.score(category="strain")]))
        self.assertTrue(errors)

    def test_apple_rmssd_refused(self):
        errors, _ = validate(health_block("2026-09-24", hrv=44, source="openwearables", provider="apple"))
        self.assertTrue(any("hrv_sdnn_ms" in e for e in errors), errors)

    def test_provider_score_provider_mismatch_refused(self):
        score = {"category": "readiness", "value": 80, "scale_min": 0, "scale_max": 100, "provider": "whoop"}
        errors, _ = validate(health_block("2026-09-24", rhr=50, source="openwearables", provider="oura",
                                          provider_scores=[score]))
        self.assertTrue(any("provider_scores[0].provider" in e for e in errors), errors)

    def test_unknown_health_source_refused(self):
        errors, _ = validate(health_block("2026-09-24", source="strava"))
        self.assertTrue(any("health_source" in e for e in errors), errors)

    def test_garmin_keys_refused_with_openwearables(self):
        for key, value in (("readiness_score", 82), ("sleep_score", 80), ("stress_avg", 30),
                           ("body_battery_high", 90), ("readiness_factors", {"sleep": 60})):
            errors, _ = validate(health_block("2026-09-24", source="openwearables", provider="oura", **{key: value}))
            self.assertTrue(any(key in e for e in errors), (key, errors))

    def test_garmin_keys_still_fine_with_garmin_or_absent_source(self):
        for source in (None, "garmin"):
            errors, _ = validate(health_block("2026-09-24", source=source, readiness_score=74, sleep_score=81))
            self.assertEqual(errors, [])

    def test_provider_requires_openwearables(self):
        errors, _ = validate(health_block("2026-09-24", source="garmin", provider="oura"))
        self.assertTrue(any("health_provider" in e for e in errors), errors)

    def test_expected_keys_openwearables_has_no_readiness_debt(self):
        conf = {"morning_check": "full"}
        ow = {"morning_check": "full", "health_source": "openwearables"}
        self.assertEqual(I.expected_keys("health", ow, conf),
                         ["sleep_total_s", "hrv_overnight_ms", "resting_hr_bpm", "verdict"])
        self.assertEqual(I.expected_keys("health", {**ow, "morning_check": "minimal"}, conf), ["verdict"])
        # défaut inchangé
        self.assertIn("readiness_score", I.expected_keys("health", {"morning_check": "full"}, conf))
        self.assertEqual(I.expected_keys("health", {"morning_check": "minimal"}, conf), ["readiness_score", "verdict"])


class Workspace(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="arc-health-source-"))
        self.ws = self.tmp / "ws"
        for d in ("activities", "medical", "nutrition", "planning", "rapports"):
            (self.ws / d).mkdir(parents=True)
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def health(self, day, hrv=None, rhr=None, source=None, provider=None, **extra):
        (self.ws / f"medical/{day}_health.md").write_text(
            arc(health_block(day, hrv, rhr, source, provider, **extra)), encoding="utf-8")

    def pain_only(self, day):
        """Fichier santé SANS mesure ni provenance (douleur seule, comme /log ou Telegram)."""
        (self.ws / f"medical/{day}_health.md").write_text(arc({
            "arc": 1, "kind": "health", "date": day, "morning_check": "full",
            "pain": [{"location": "genou", "score": 3}]}), encoding="utf-8")

    def conn(self):
        conn = I.open_db(self.ws, memory=True)
        self.addCleanup(conn.close)
        I.index_workspace(conn, self.ws, TODAY.isoformat())
        return conn


class TestHrvBaselinePerSource(Workspace):
    def test_default_without_provenance_is_unchanged(self):
        for i in range(70):
            self.health(iso(-69 + i), hrv=60.0)
        point = I.hrv_baseline_today(self.conn(), {"morning_check": "full"}, TODAY)
        self.assertEqual(point["hrv_personal_status"], "dans_la_norme")
        self.assertEqual((point["health_source"], point["health_provider"]), ("garmin", None))

    def test_old_files_follow_configured_data_source(self):
        for i in range(10):
            self.health(iso(-9 + i), hrv=60.0)
        point = I.hrv_baseline_today(self.conn(), {"morning_check": "full", "data_source": "intervals"}, TODAY)
        self.assertEqual(point["health_source"], "intervals")

    def test_baseline_never_spans_two_sources(self):
        """60 nuits garmin puis 5 nuits openwearables/oura : la référence repart de zéro."""
        for i in range(65):
            day = iso(-64 + i)
            if i < 60:
                self.health(day, hrv=60.0, source="garmin")
            else:
                self.health(day, hrv=90.0, source="openwearables", provider="oura")
        point = I.hrv_baseline_today(self.conn(), {"morning_check": "full"}, TODAY)
        self.assertEqual((point["health_source"], point["health_provider"]), ("openwearables", "oura"))
        self.assertEqual(point["hrv_personal_status"], "en_construction")
        self.assertIsNone(point["hrv_personal_low_ms"])
        # la moyenne 7 j ne contient que des nuits Oura (90 ms), aucune nuit Garmin (60 ms)
        self.assertAlmostEqual(point["hrv_personal_mean7_ms"], 90.0, places=1)

    def test_old_files_vs_explicit_garmin_are_the_same_source(self):
        for i in range(70):
            day = iso(-69 + i)
            self.health(day, hrv=60.0, source=None if i < 35 else "garmin")
        point = I.hrv_baseline_today(self.conn(), {"morning_check": "full", "data_source": "garmin"}, TODAY)
        self.assertEqual(point["hrv_personal_status"], "dans_la_norme")

    def test_two_providers_do_not_mix(self):
        for i in range(70):
            day = iso(-69 + i)
            if i < 65:
                self.health(day, hrv=60.0, source="openwearables", provider="whoop")
            else:
                self.health(day, hrv=60.0, source="openwearables", provider="oura")
        point = I.hrv_baseline_today(self.conn(), {"morning_check": "full"}, TODAY)
        self.assertEqual(point["health_provider"], "oura")
        self.assertEqual(point["hrv_personal_status"], "en_construction")

    def test_sdnn_never_enters_the_baseline(self):
        for i in range(70):
            self.health(iso(-69 + i), source="openwearables", provider="apple", hrv_sdnn_ms=44.0)
        point = I.hrv_baseline_today(self.conn(), {"morning_check": "full"}, TODAY)
        self.assertIsNone(point["hrv_personal_status"])   # aucune nuit RMSSD : aucune valeur, jamais le SDNN
        row = self.conn().execute("SELECT hrv_sdnn_ms, hrv_overnight_ms, health_source, health_provider "
                                  "FROM health_day LIMIT 1").fetchone()
        self.assertEqual(tuple(row), (44.0, None, "openwearables", "apple"))

    def test_switch_to_sdnn_only_source_does_not_keep_garmin_baseline(self):
        """Nuits Garmin puis nuits Apple SDNN seul : la source courante est Apple, aucun statut Garmin."""
        for i in range(70):
            day = iso(-69 + i)
            if i < 63:
                self.health(day, hrv=60.0, source="garmin")
            else:
                self.health(day, rhr=50, source="openwearables", provider="apple", hrv_sdnn_ms=44.0)
        point = I.hrv_baseline_today(self.conn(), {"morning_check": "full"}, TODAY)
        self.assertEqual((point["health_source"], point["health_provider"]), ("openwearables", "apple"))
        self.assertIsNone(point["hrv_personal_status"])
        self.assertIsNone(point.get("hrv_personal_mean7_ms"))

    def test_pain_only_file_does_not_change_the_baseline_source(self):
        for i in range(70):
            self.health(iso(-69 + i), hrv=60.0, source="openwearables", provider="oura")
        self.pain_only(iso(0))
        point = I.hrv_baseline_today(self.conn(), {"morning_check": "full", "data_source": "garmin"}, TODAY)
        self.assertEqual((point["health_source"], point["health_provider"]), ("openwearables", "oura"))
        self.assertEqual(point["hrv_personal_status"], "dans_la_norme")

    def test_provider_scores_stay_in_data_json_only(self):
        self.health(iso(0), hrv=58, source="openwearables", provider="oura", provider_scores=[
            {"category": "readiness", "value": 82, "scale_min": 0, "scale_max": 100, "provider": "oura"}])
        conn = self.conn()
        row = conn.execute("SELECT readiness_score, data_json FROM health_day").fetchone()
        self.assertIsNone(row["readiness_score"])
        self.assertEqual(json.loads(row["data_json"])["provider_scores"][0]["value"], 82)


class TestDecisionEffects(Workspace):
    DAY = iso(-20)

    def decision(self):
        block = {"arc": 1, "kind": "decision", "date": self.DAY, "created_at": self.DAY + "T07:00:00+02:00",
                 "trigger": "morning_check", "summary": "Allègement", "outcome": "applied",
                 "before": {"session_type": "tempo"}, "after": {"session_type": "endurance"}}
        (self.ws / f"planning/{self.DAY}_decision_x.md").write_text(arc(block), encoding="utf-8")

    def fill(self, switch_at):
        """HRV/FC de repos J-2..J+7 ; la source change à l'offset `switch_at` (None = jamais)."""
        d0 = date.fromisoformat(self.DAY)
        for off in range(-2, 8):
            day = (d0 + timedelta(days=off)).isoformat()
            after = switch_at is not None and off >= switch_at
            self.health(day, hrv=70 if off > 0 else 50, rhr=48 if off > 0 else 55,
                        source="openwearables" if after else "garmin", provider="oura" if after else None)

    def report(self, **kw):
        return I.decision_effects(self.conn(), TODAY, **kw)

    def test_window_with_two_sources_is_excluded_and_counted(self):
        self.decision()
        self.fill(switch_at=2)
        ev = self.report()["effects"][0]
        self.assertEqual(ev["effect"], "insufficient_data")
        self.assertEqual(ev["reason_code"], "source_change")
        self.assertEqual(ev["excluded_source_change"], 3)   # hrv, rhr, readiness
        self.assertEqual(ev["signals"], [])
        group = self.report()["synthesis"][0]
        self.assertEqual(group["excluded_source_change"], 1)
        self.assertIn("changement de source", group["statement"])

    def test_single_source_window_is_evaluated_as_before(self):
        self.decision()
        self.fill(switch_at=None)
        ev = self.report()["effects"][0]
        self.assertNotEqual(ev["effect"], "insufficient_data")
        self.assertNotIn("excluded_source_change", ev)
        self.assertNotIn("excluded_source_change", self.report()["synthesis"][0])

    def test_data_without_source_key_is_untouched(self):
        health = {iso(-22 + i): {"hrv_ms": 50 if i < 3 else 70} for i in range(10)}
        ev = DE.evaluate_decision(
            {"id": "x", "source_path": "p", "date": iso(-20), "trigger": "morning_check", "outcome": "applied"},
            {"health": health}, TODAY)
        self.assertEqual(ev["effect"], "improved")

    def test_pain_only_file_is_not_a_source_change(self):
        """Période Oura + fichier de douleur seule dans la fenêtre : pas de changement de source."""
        self.decision()
        d0 = date.fromisoformat(self.DAY)
        for off in range(-2, 8):
            self.health((d0 + timedelta(days=off)).isoformat(), hrv=70 if off > 0 else 50, rhr=48 if off > 0 else 55,
                        source="openwearables", provider="oura")
        pain_day = (d0 + timedelta(days=8)).isoformat()
        self.pain_only(pain_day)
        data = I._decision_effect_data(self.conn(), "garmin")
        self.assertNotIn("source", data["health"][pain_day])
        self.assertFalse(DE.source_changes(data, d0 - timedelta(days=2), d0 + timedelta(days=8)))
        self.assertNotIn("excluded_source_change", self.report()["effects"][0])

    def test_old_vs_explicit_default_source_is_not_a_change(self):
        self.decision()
        d0 = date.fromisoformat(self.DAY)
        for off in range(-2, 8):
            self.health((d0 + timedelta(days=off)).isoformat(), hrv=70 if off > 0 else 50, rhr=48 if off > 0 else 55,
                        source=None if off < 3 else "garmin")
        ev = self.report()["effects"][0]
        self.assertNotIn("excluded_source_change", ev)


class TestDashboardApi(Workspace):
    def store(self):
        store = S.Store(self.ws, memory=True, today=TODAY.isoformat())
        self.addCleanup(store.conn.close)
        return store

    def test_band_and_rhr_median_are_per_source(self):
        for i in range(70):
            day = iso(-69 + i)
            if i < 62:
                self.health(day, hrv=60.0, rhr=45, source="garmin")
            else:
                self.health(day, hrv=95.0, rhr=60, source="openwearables", provider="oura")
        body = S.api_health(self.store(), {"days": ["20"]})
        self.assertEqual(body["source"]["health_source"], "openwearables")
        self.assertEqual(body["source"]["health_provider"], "oura")
        self.assertIn("oura", body["source"]["label"])
        self.assertTrue(body["source"]["changed"])
        last = body["series"][-1]
        self.assertEqual(last["health_source"], "openwearables")
        self.assertEqual(last["hrv_personal_status"], "en_construction")        # pas de référence Garmin empruntée
        self.assertAlmostEqual(last["hrv_personal_mean7_ms"], 95.0, places=1)
        self.assertEqual(last["rhr_median7"], 60)                                # ni FC de repos Garmin
        # un jour Garmin plus ancien garde la bande de SA source
        old = next(p for p in body["series"] if p["date"] == iso(-12))
        self.assertEqual(old["hrv_personal_status"], "dans_la_norme")
        self.assertEqual(old["rhr_median7"], 45)

    def test_pain_only_today_is_not_a_source_change(self):
        for i in range(30):
            self.health(iso(-29 + i), hrv=95.0, rhr=60, source="openwearables", provider="oura")
        self.pain_only(iso(0))
        body = S.api_health(self.store(), {"days": ["20"]})
        self.assertEqual(body["source"]["health_source"], "openwearables")
        self.assertEqual(body["source"]["health_provider"], "oura")
        self.assertFalse(body["source"]["changed"])

    def test_default_workspace_output_is_unchanged(self):
        """Source principale unique : aucune clé `source` (sortie identique à avant #218), jamais « Strava »."""
        for i in range(20):
            self.health(iso(-19 + i), hrv=60.0, rhr=45)
        self.pain_only(iso(0))
        body = S.api_health(self.store(), {"days": ["10"]})
        self.assertNotIn("source", body)
        self.assertNotIn("health_source", body["series"][-1])

    def test_strava_data_source_is_never_labelled_strava(self):
        self.assertNotIn("Strava", HS.label("strava"))


class TestSchema(unittest.TestCase):
    def test_new_columns_exist_and_version_bumped(self):
        self.assertGreaterEqual(I.SCHEMA_VERSION, 38)
        tmp = Path(tempfile.mkdtemp(prefix="arc-health-source-schema-"))
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        (tmp / "medical").mkdir()
        conn = I.open_db(tmp, memory=True)
        self.addCleanup(conn.close)
        cols = {r[1] for r in conn.execute("PRAGMA table_info(health_day)")}
        self.assertTrue({"health_source", "health_provider", "hrv_sdnn_ms"} <= cols)


if __name__ == "__main__":
    unittest.main()
