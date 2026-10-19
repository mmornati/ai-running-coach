"""Palier D — `coach_doctor` en mode famille (#127) : registre, jetons, ntfy, synchronisation par membre."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))

import arc_family as F  # noqa: E402
import coach_doctor as D  # noqa: E402


class FamilyDoctor(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name).resolve()
        env = mock.patch.dict(os.environ, {}, clear=False)
        env.start()
        self.addCleanup(env.stop)
        for var in ("GARMINTOKENS", "GARMIN_TOKENS_DIR", "ARC_FAMILY"):
            os.environ.pop(var, None)

    def member(self, name: str, tokens: str = None, topic: str = None, source: str = "garmin") -> Path:
        ws = self.root / f"coach-{name}"
        (ws / "config").mkdir(parents=True)
        toml = f'[data]\nsource = "{source}"\n'
        if topic:
            toml += f'[notifications]\nprovider = "ntfy"\nntfy_topic = "{topic}"\n'
        (ws / "config/workspace.user.toml").write_text(toml, encoding="utf-8")
        if tokens:
            (ws / ".mcp.json").write_text(json.dumps(
                {"mcpServers": {"garmin": {"command": "garmin-mcp", "env": {"GARMINTOKENS": tokens}}}}))
        return ws

    def registry(self, members: dict) -> F.Registry:
        text = '[family]\ntrusted_proxies = ["127.0.0.1"]\n' + "".join(
            f'[members.{m}]\nworkspace = "{ws}"\n' for m, ws in members.items())
        path = self.root / "family.toml"
        path.write_text(text, encoding="utf-8")
        return F.load_registry(path)

    def run_checks(self, members: dict, blobs=()) -> dict:
        registry = self.registry(members)
        with mock.patch.object(D, "_scheduled_blobs", return_value=list(blobs)):
            checks = D.check_family(registry.path, registry, None)
        return {c["id"]: c for c in checks}

    def test_registre_valide_et_tout_au_vert(self):
        a = self.member("alice", tokens=str(self.root / "tok-a"), topic="t-a")
        b = self.member("bob", tokens=str(self.root / "tok-b"), topic="t-b")
        checks = self.run_checks({"alice": a, "bob": b}, blobs=[f"0 6 * * * cd {a} # ai-running-coach", f"cd {b} #"])
        self.assertEqual({k: v["status"] for k, v in checks.items()},
                         {"family_registry": "ok", "family_tokens": "ok", "family_ntfy": "ok", "family_sync": "ok"})

    def test_registre_invalide_est_une_erreur(self):
        checks = D.check_family(self.root / "family.toml", None, "workspace inexistant")
        self.assertEqual([(c["id"], c["status"]) for c in checks], [("family_registry", "error")])

    def test_jetons_garmin_partages_entre_deux_membres(self):
        shared = str(self.root / "tok")
        checks = self.run_checks({"alice": self.member("alice", tokens=shared), "bob": self.member("bob", tokens=shared)})
        self.assertEqual(checks["family_tokens"]["status"], "warning")
        self.assertIn("alice", checks["family_tokens"]["message"])
        self.assertIn("bob", checks["family_tokens"]["message"])
        self.assertNotIn("garmin_tokens.json", json.dumps(checks))      # jamais le contenu d'un jeton

    def test_jetons_par_defaut_pour_deux_membres_sans_mcp_json(self):
        checks = self.run_checks({"alice": self.member("alice"), "bob": self.member("bob")})
        self.assertEqual(checks["family_tokens"]["status"], "warning")  # tous deux sur ~/.garminconnect

    def test_membre_intervals_hors_controle_des_jetons_garmin(self):
        checks = self.run_checks({"alice": self.member("alice"), "bob": self.member("bob", source="intervals")})
        self.assertEqual(checks["family_tokens"]["status"], "ok")

    def test_meme_topic_ntfy(self):
        checks = self.run_checks({"alice": self.member("alice", tokens="/t/a", topic="coach"),
                                  "bob": self.member("bob", tokens="/t/b", topic="coach")})
        self.assertEqual(checks["family_ntfy"]["status"], "warning")

    def test_membre_sans_synchronisation_planifiee(self):
        a = self.member("alice", tokens="/t/a")
        b = self.member("bob", tokens="/t/b")
        checks = self.run_checks({"alice": a, "bob": b}, blobs=[f"cd {a} # ai-running-coach daily-sync"])
        self.assertEqual(checks["family_sync"]["status"], "info")
        self.assertEqual(checks["family_sync"]["members"], ["bob"])

    def test_registre_absent_aucune_verification_ajoutee(self):
        with mock.patch("arc_family.default_registry_path", return_value=self.root / "absent.toml"):
            self.assertEqual(D._family_registry(None), (None, None, None))
        path, registry, error = D._family_registry(str(self.root / "absent.toml"))   # donné explicitement
        self.assertIsNone(registry)
        self.assertIn("introuvable", error)

    def test_main_ajoute_les_verifications_famille_au_json(self):
        import contextlib
        import io
        a = self.member("alice", tokens="/t/a")
        registry = self.registry({"alice": a})
        for argv, expect in ((["--family", str(registry.path)], True), (["--family", str(registry.path), "--check",
                                                                          "config_files"], False)):
            out = io.StringIO()
            with mock.patch.object(D, "_scheduled_blobs", return_value=[]), \
                    mock.patch.object(D, "run_all_checks", return_value=[]), \
                    mock.patch.object(D, "run_single_check", return_value={"id": "config_files", "status": "ok",
                                                                            "message": "", "fix": None}), \
                    contextlib.redirect_stdout(out):
                D.main(["--workspace", str(a), "--json", *argv])
            ids = [c["id"] for c in json.loads(out.getvalue())["checks"]]
            self.assertEqual("family_registry" in ids, expect, argv)

    def test_schema_additif_les_ids_historiques_inchanges(self):
        self.assertFalse([i for i in D.CHECK_IDS if i.startswith("family_")])


if __name__ == "__main__":
    unittest.main()
