"""Palier D — pièces jointes du chat (#342) : validation du contenu, nom généré, rangement sûr
(`scripts/arc_chat_upload.py`) et compatibilité avec la politique de permissions."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))

import arc_chat_upload as UP  # noqa: E402
from arc_chat_policy import Policy  # noqa: E402

GPX = (b'<?xml version="1.0" encoding="UTF-8"?><gpx version="1.1" xmlns="http://www.topografix.com/GPX/1/1">'
       b'<trk><trkseg><trkpt lat="45.0" lon="6.0"><ele>1000</ele></trkpt></trkseg></trk></gpx>')
TCX = (b'<?xml version="1.0"?><TrainingCenterDatabase xmlns="http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2">'
       b'<Activities/></TrainingCenterDatabase>')
FIT = bytes([14, 0x10, 0x4B, 0x08, 0, 0, 0, 0]) + b".FIT" + b"\x00\x00" + b"\x00" * 32
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
JPG = b"\xff\xd8\xff\xe0" + b"\x00" * 32
WEBP = b"RIFF\x24\x00\x00\x00WEBPVP8 " + b"\x00" * 32
HEIC = b"\x00\x00\x00\x18ftypheic\x00\x00\x00\x00mif1heic" + b"\x00" * 16


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name).resolve()

    def check(self, data: bytes, name: str):
        """Lance `check_content` sur `data` comme si le client l'avait nommé `name`."""
        kind, _, ext, _ = UP.classify_name(name)
        path = self.dir / "recu.bin"
        path.write_bytes(data)
        UP.check_content(path, kind, ext)

    def refused(self, data: bytes, name: str, fragment: str = "") -> str:
        with self.assertRaises(UP.UploadError) as ctx:
            self.check(data, name)
        self.assertEqual(ctx.exception.status, 415)
        self.assertIn(fragment, ctx.exception.message)
        return ctx.exception.message


class TestNames(Base):
    def test_classification_par_extension(self):
        expected = {"a.gpx": ("gpx", "planning/inbox", ".gpx"), "a.TCX": ("tcx", "planning/inbox", ".tcx"),
                    "a.fit": ("fit", "planning/inbox", ".fit"), "a.jpg": ("image", "gear/photos", ".jpg"),
                    "a.JPEG": ("image", "gear/photos", ".jpg"), "a.png": ("image", "gear/photos", ".png"),
                    "a.webp": ("image", "gear/photos", ".webp")}
        for name, (kind, folder, ext) in expected.items():
            with self.subTest(name):
                got = UP.classify_name(name)
                self.assertEqual(got[:3], (kind, folder, ext))

    def test_types_refuses(self):
        for name in ("a.txt", "a.exe", "a.svg", "a.html", "a.gpx.exe", "sans-extension", "", ".gpx.", "a.gif"):
            with self.subTest(name), self.assertRaises(UP.UploadError) as ctx:
                UP.classify_name(name)
            self.assertEqual(ctx.exception.status, 415)

    def test_heic_message_explicite(self):
        for name in ("IMG_1.HEIC", "IMG_1.heif"):
            with self.subTest(name), self.assertRaises(UP.UploadError) as ctx:
                UP.classify_name(name)
            self.assertIn("JPEG", ctx.exception.message)

    def test_slug_ascii_et_noms_hostiles(self):
        cases = {"Sortie Longue à Tournai.gpx": "sortie-longue-a-tournai",
                 "../../etc/passwd.gpx": "passwd", "a/b/c.gpx": "c", "a\\b\\d.gpx": "d",
                 "nul\x00byte.gpx": "nulbyte", "Été ✓ 日本.gpx": "ete", "....gpx": "fichier",
                 "x" * 300 + ".gpx": "x" * 40, "my file (1).GPX": "my-file-1"}
        for name, slug in cases.items():
            with self.subTest(name[:20]):
                _, _, ext, got = UP.classify_name(name)
                self.assertEqual(got, slug)
                self.assertEqual(ext, ".gpx")

    def test_decode_filename(self):
        self.assertEqual(UP.decode_filename("S%C3%A9ance%20%2F..%2Fx.gpx"), "Séance /../x.gpx")
        self.assertEqual(UP.decode_filename(None), "")


class TestContent(Base):
    def test_contenus_valides(self):
        for data, name in ((GPX, "a.gpx"), (TCX, "a.tcx"), (FIT, "a.fit"), (PNG, "a.png"), (JPG, "a.jpg"),
                           (JPG, "a.jpeg"), (WEBP, "a.webp"), (b"\xef\xbb\xbf" + GPX, "bom.gpx")):
            with self.subTest(name):
                self.check(data, name)

    def test_en_tete_fit(self):
        self.check(bytes([12]) + FIT[1:], "a.fit")
        self.refused(bytes([13]) + FIT[1:], "a.fit", "FIT")
        self.refused(FIT[:8] + b".FIX" + FIT[12:], "a.fit", "FIT")
        self.refused(FIT[:10], "a.fit", "FIT")

    def test_contenu_falsifie(self):
        self.refused(PNG, "a.gpx")
        self.refused(GPX, "a.png", "extension")
        self.refused(GPX, "a.jpg", "extension")
        self.refused(JPG, "a.png", "extension")
        self.refused(PNG, "a.webp", "extension")
        self.refused(GPX, "a.fit", "FIT")
        self.refused(FIT, "a.gpx")
        self.refused(TCX, "a.gpx")            # racine TrainingCenterDatabase dans un .gpx
        self.refused(GPX, "a.tcx")
        self.refused(b"<kml/>", "a.gpx")
        self.refused(GPX[:60], "a.gpx")        # XML tronqué
        self.refused(b"pas du xml", "a.gpx")

    def test_xml_sans_dtd_ni_entite(self):
        evil = b'<?xml version="1.0"?><!DOCTYPE gpx [<!ENTITY a "boum">]><gpx>&a;</gpx>'
        self.assertIn("DOCTYPE", self.refused(evil, "a.gpx"))
        self.refused(b'<?xml version="1.0"?><!doctype gpx><gpx/>', "a.gpx", "DOCTYPE")
        self.refused(b'<!ENTITY x SYSTEM "file:///etc/passwd"><gpx/>', "a.gpx", "ENTITY")
        # déclaration loin dans un gros fichier (plusieurs morceaux de lecture)
        self.refused(b"<gpx>" + b" " * (3 * UP.CHUNK) + b"<!DOCTYPE x><a/></gpx>", "a.gpx", "DOCTYPE")
        self.refused(b"<gpx><!-- " + b"x" * (UP.CHUNK - 12) + b" --><!ENTITY a 'b'></gpx>", "a.gpx")

    def test_xml_utf16_et_nul_refuses(self):
        self.refused(GPX.decode().encode("utf-16"), "a.gpx")
        self.refused(GPX + b"\x00", "a.gpx")

    def test_heic_deguise_en_jpeg(self):
        self.assertIn("JPEG", self.refused(HEIC, "a.jpg"))

    def test_webp_et_png_tronques(self):
        self.refused(b"RIFF", "a.webp")
        self.refused(b"\x89PNG", "a.png")


class TestStorage(Base):
    def put(self, folder, data: bytes, slug="sortie", ext=".gpx", now=None):
        fd, tmp = folder.new_temp()
        os.write(fd, data)
        os.close(fd)
        return folder.publish(tmp, slug, ext, now)

    def test_publication_sans_ecrasement(self):
        now = datetime(2026, 11, 1, 10, 30, 5)
        with UP.DropFolder(self.dir, "planning/inbox") as folder:
            names = [self.put(folder, b"contenu %d" % i, now=now) for i in range(3)]
        self.assertEqual(names, ["2026-11-01_103005_sortie.gpx", "2026-11-01_103005_sortie-2.gpx",
                                 "2026-11-01_103005_sortie-3.gpx"])
        out = self.dir / "planning" / "inbox"
        for i, name in enumerate(names):
            self.assertEqual((out / name).read_bytes(), b"contenu %d" % i)
        self.assertEqual(sorted(p.name for p in out.iterdir()), sorted(names))      # aucun temporaire laissé

    def test_un_fichier_existant_n_est_jamais_ecrase(self):
        (self.dir / "gear" / "photos").mkdir(parents=True)
        existing = self.dir / "gear" / "photos" / "2026-11-01_103005_a.png"
        existing.write_bytes(b"original")
        with UP.DropFolder(self.dir, "gear/photos") as folder:
            name = self.put(folder, b"nouveau", "a", ".png", datetime(2026, 11, 1, 10, 30, 5))
        self.assertEqual(name, "2026-11-01_103005_a-2.png")
        self.assertEqual(existing.read_bytes(), b"original")

    def test_droits_suivent_l_umask(self):
        old = os.umask(0o022)
        try:
            with UP.DropFolder(self.dir, "planning/inbox") as folder:
                name = self.put(folder, b"x")
        finally:
            os.umask(old)
        self.assertEqual((self.dir / "planning" / "inbox" / name).stat().st_mode & 0o777, 0o644)

    def test_lien_symbolique_dans_le_chemin_refuse(self):
        outside = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(outside, ignore_errors=True))
        (self.dir / "planning").symlink_to(outside)
        with self.assertRaises(UP.UploadError):
            UP.DropFolder(self.dir, "planning/inbox")
        self.assertEqual(list(outside.iterdir()), [])
        (self.dir / "gear").mkdir()
        (self.dir / "gear" / "photos").symlink_to(outside)
        with self.assertRaises(UP.UploadError):
            UP.DropFolder(self.dir, "gear/photos")
        self.assertEqual(list(outside.iterdir()), [])

    def test_composant_remplace_par_un_lien_apres_ouverture(self):
        """Le descripteur du dossier reste celui ouvert : un lien posé ensuite ne détourne rien."""
        outside = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(outside, ignore_errors=True))
        with UP.DropFolder(self.dir, "planning/inbox") as folder:
            (self.dir / "planning" / "inbox").rename(self.dir / "planning" / "ancien")
            (self.dir / "planning" / "inbox").symlink_to(outside)
            self.put(folder, b"x")
        self.assertEqual(list(outside.iterdir()), [])
        self.assertEqual(len(list((self.dir / "planning" / "ancien").iterdir())), 1)


class TestLimit(unittest.TestCase):
    def test_plafond_valide_partout_de_la_meme_facon(self):
        for bad in (0, -5, "x", None, "0"):
            self.assertEqual(UP.effective_limit(bad), UP.DEFAULT_UPLOAD_MAX_BYTES, bad)
        self.assertEqual(UP.effective_limit(1000), 1000)
        self.assertEqual(UP.effective_limit("2048"), 2048)

    def test_affichage_en_ko_sous_1_mio(self):
        self.assertEqual(UP.format_size(20 * 1024 * 1024), "20 Mo")
        self.assertEqual(UP.format_size(1000), "1 Ko")
        self.assertEqual(UP.format_size(512 * 1024), "512 Ko")


class TestPolicy(Base):
    """Rien à changer dans `chat-policy.toml` : un chemin relatif du workspace passe déjà."""

    def test_analyse_et_lecture_du_fichier_joint(self):
        (self.dir / "planning").mkdir()
        policy = Policy.load(REPO, self.dir)
        rel = "planning/inbox/2026-11-01_103005_sortie-longue.gpx"
        self.assertEqual(policy.decide("shell", {"command": f"python3 skills/gpx-analysis/scripts/analyze_gpx.py --gpx {rel}"}),
                         "allow")
        self.assertEqual(policy.decide("fs.read", {"path": rel}), "allow")
        self.assertEqual(policy.decide("fs.read", {"path": "gear/photos/2026-11-01_103005_semelle.jpg"}), "allow")


if __name__ == "__main__":
    unittest.main()
