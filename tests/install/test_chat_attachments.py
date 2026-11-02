"""Palier A — pièces jointes du chat (#342) de bout en bout : route d'envoi, rangement, lien avec le message.

Vrai serveur HTTP sur port libre, workspace temporaire, backend `mock`. Aucun modèle ni réseau.
"""

from __future__ import annotations

import http.client
import json
import re
import socket
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from urllib.parse import quote

from tests.install.test_chat_service import CSRF, ChatCase

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))

import arc_chat as C  # noqa: E402
from arc_chat_mock import MockBackend  # noqa: E402

GPX = (b'<?xml version="1.0" encoding="UTF-8"?><gpx version="1.1" xmlns="http://www.topografix.com/GPX/1/1">'
       b'<trk><trkseg><trkpt lat="45.0" lon="6.0"><ele>1000</ele></trkpt></trkseg></trk></gpx>')
TCX = b'<?xml version="1.0"?><TrainingCenterDatabase xmlns="x"><Activities/></TrainingCenterDatabase>'
FIT = bytes([14, 0x10, 0x4B, 0x08, 0, 0, 0, 0]) + b".FIT" + b"\x00\x00" + b"\x00" * 32
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
JPG = b"\xff\xd8\xff\xe0" + b"\x00" * 32
WEBP = b"RIFF\x24\x00\x00\x00WEBPVP8 " + b"\x00" * 32
HEIC = b"\x00\x00\x00\x18ftypheic\x00\x00\x00\x00mif1heic" + b"\x00" * 16
NAME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}_\d{6}_[a-z0-9-]+(-\d+)?\.[a-z]+$")


class Capture(MockBackend):
    """Backend mock qui garde le texte exact reçu du service."""

    received: list = []

    def run_turn(self, ctx, user_message):
        Capture.received.append(user_message)
        super().run_turn(ctx, user_message)


BIG = 2 * 1024 * 1024


class AttachCase(ChatCase):
    def setUp(self):
        super().setUp()
        # Envois refusés sans corps (tests bruts) : ne pas attendre 10 s l'arrêt du client.
        old = C.UPLOAD_IDLE_TIMEOUT_S, C.UPLOAD_DRAIN_MIN_S
        C.UPLOAD_IDLE_TIMEOUT_S = C.UPLOAD_DRAIN_MIN_S = 0.3
        self.addCleanup(lambda: (setattr(C, "UPLOAD_IDLE_TIMEOUT_S", old[0]), setattr(C, "UPLOAD_DRAIN_MIN_S", old[1])))

    def start(self, **over):
        Capture.received = []
        over.setdefault("backend_factory", Capture)
        return super().start(**over)

    def upload(self, sid, data, name="sortie.gpx", headers=None, host=None):
        hdrs = dict(CSRF)
        hdrs.update({"Content-Type": "application/octet-stream", "X-Filename": quote(name, safe="")})
        hdrs.update(headers or {})
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        hdrs.setdefault("Host", host or f"127.0.0.1:{self.port}")
        try:
            conn.request("POST", f"/api/chat/sessions/{sid}/attachments", body=data, headers=hdrs)
            res = conn.getresponse()
            return res.status, json.loads(res.read().decode("utf-8") or "{}")
        finally:
            conn.close()

    def raw(self, request: bytes):
        """Requête brute (sans corps ou avec en-têtes inhabituels) ; renvoie (statut, JSON)."""
        with socket.create_connection(("127.0.0.1", self.port), timeout=5) as sock:
            sock.sendall(request)
            data = b""
            while True:
                chunk = sock.recv(65536)
                if not chunk:
                    break
                data += chunk
        head, _, body = data.partition(b"\r\n\r\n")
        return int(head.split()[1]), json.loads(body.decode("utf-8") or "{}")

    def files(self):
        """Tous les fichiers du workspace hors `.arc/` (chemins relatifs)."""
        return sorted(p.relative_to(self.ws).as_posix() for p in self.ws.rglob("*")
                      if p.is_file() and ".arc" not in p.relative_to(self.ws).parts)

    def message(self, sid, text, attachments, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=15)
        hdrs = dict(CSRF, **{"Content-Type": "application/json", "Host": f"127.0.0.1:{self.port}"}, **(headers or {}))
        body = {"attachments": attachments}
        if text is not None:
            body["text"] = text
        conn.request("POST", f"/api/chat/sessions/{sid}/messages", body=json.dumps(body), headers=hdrs)
        res = conn.getresponse()
        raw = res.read().decode("utf-8")
        conn.close()
        return res.status, raw


class TestUpload(AttachCase):
    def test_gpx_range_dans_planning_inbox(self):
        self.start()
        sid = self.new_session()
        status, data = self.upload(sid, GPX, "Sortie Longue à Tournai.gpx")
        self.assertEqual(status, 200, data)
        self.assertEqual(data["kind"], "gpx")
        self.assertEqual(data["bytes"], len(GPX))
        self.assertTrue(data["path"].startswith("planning/inbox/"), data)
        self.assertRegex(Path(data["path"]).name, NAME_RE)
        self.assertTrue(data["path"].endswith("_sortie-longue-a-tournai.gpx"))
        self.assertEqual((self.ws / data["path"]).read_bytes(), GPX)
        self.assertEqual(self.files(), [data["path"]])               # ni temporaire ni autre fichier
        meta = self.service.sessions.get(sid)
        self.assertEqual(meta["attachments"], [data])

    def test_rangement_par_type(self):
        self.start()
        sid = self.new_session()
        cases = [("a.gpx", GPX, "gpx", "planning/inbox", ".gpx"), ("a.TCX", TCX, "tcx", "planning/inbox", ".tcx"),
                 ("a.fit", FIT, "fit", "planning/inbox", ".fit"), ("a.jpg", JPG, "image", "gear/photos", ".jpg"),
                 ("A.JPEG", JPG, "image", "gear/photos", ".jpg"), ("a.png", PNG, "image", "gear/photos", ".png"),
                 ("a.webp", WEBP, "image", "gear/photos", ".webp")]
        for name, data, kind, folder, ext in cases:
            with self.subTest(name):
                status, body = self.upload(sid, data, name)
                self.assertEqual(status, 200, body)
                self.assertEqual(body["kind"], kind)
                self.assertEqual(Path(body["path"]).parent.as_posix(), folder)
                self.assertTrue(body["path"].endswith(ext))
                self.assertRegex(Path(body["path"]).name, NAME_RE)

    def test_photo_deposee_visible_dans_la_boite_de_depot(self):
        self.start()
        sid = self.new_session()
        status, data = self.upload(sid, JPG, "semelle.jpg")
        self.assertEqual(status, 200)
        out = subprocess.run([sys.executable, str(REPO / "scripts/arc_index.py"), "--workspace", str(self.ws),
                              "inspections", "--unreferenced-photos"], capture_output=True, text=True, timeout=60)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn(data["path"], json.loads(out.stdout)["unreferenced_photos"])

    def test_non_ecrasement(self):
        self.start()
        sid = self.new_session()
        paths = [self.upload(sid, GPX + b"<!-- %d -->" % i, "same.gpx")[1]["path"] for i in range(3)]
        self.assertEqual(len(set(paths)), 3)
        for i, path in enumerate(paths):
            self.assertEqual((self.ws / path).read_bytes(), GPX + b"<!-- %d -->" % i)

    def test_taille_refusee_avant_lecture_du_corps(self):
        self.start(upload_max_bytes=1000)
        sid = self.new_session()
        head = (f"POST /api/chat/sessions/{sid}/attachments HTTP/1.1\r\nHost: 127.0.0.1:{self.port}\r\n"
                f"X-ARC-Chat: 1\r\nX-Filename: a.gpx\r\nContent-Length: 5000\r\n\r\n").encode()
        status, body = self.raw(head)                 # aucun octet de corps envoyé : la réponse vient quand même
        self.assertEqual(status, 413, body)
        self.assertEqual(self.files(), [])
        pad = GPX + b" " * (1000 - len(GPX))           # pile à la limite : accepté
        self.assertEqual(self.upload(sid, pad)[0], 200)
        self.assertEqual(self.upload(sid, pad + b" ")[0], 413)

    def test_plafond_par_defaut_20_mo_et_messages_toujours_a_64_ko(self):
        self.start()
        self.assertEqual(self.service.cfg["upload_max_bytes"], 20 * 1024 * 1024)
        self.assertEqual(C.MAX_BODY_BYTES, 64 * 1024)
        sid = self.new_session()
        status, _, _ = self.request("POST", f"/api/chat/sessions/{sid}/messages", {"text": "x" * 70000}, CSRF)
        self.assertEqual(status, 413)
        self.assertEqual(self.get("/api/chat/status")[2]["upload_max_bytes"], 20 * 1024 * 1024)

    def test_content_length_obligatoire(self):
        self.start()
        sid = self.new_session()
        base = f"POST /api/chat/sessions/{sid}/attachments HTTP/1.1\r\nHost: 127.0.0.1:{self.port}\r\nX-ARC-Chat: 1\r\nX-Filename: a.gpx\r\n"
        self.assertEqual(self.raw((base + "\r\n").encode())[0], 411)
        self.assertEqual(self.raw((base + "Transfer-Encoding: chunked\r\n\r\n0\r\n\r\n").encode())[0], 411)
        self.assertEqual(self.raw((base + "Content-Length: 0\r\n\r\n").encode())[0], 400)
        self.assertEqual(self.raw((base + "Content-Length: abc\r\n\r\n").encode())[0], 400)
        self.assertEqual(self.files(), [])

    def test_corps_incomplet(self):
        self.start()
        sid = self.new_session()
        head = (f"POST /api/chat/sessions/{sid}/attachments HTTP/1.1\r\nHost: 127.0.0.1:{self.port}\r\n"
                f"X-ARC-Chat: 1\r\nX-Filename: a.gpx\r\nContent-Length: 500\r\n\r\n").encode()
        with socket.create_connection(("127.0.0.1", self.port), timeout=5) as sock:
            sock.sendall(head + GPX)
            sock.shutdown(socket.SHUT_WR)
            reply = sock.recv(65536)
        self.assertIn(b" 400 ", reply.split(b"\r\n")[0])
        self.assertEqual(self.files(), [])                                       # temporaire supprimé

    def test_types_refuses(self):
        self.start()
        sid = self.new_session()
        for name in ("notes.txt", "run.exe", "image.svg", "page.html", "sans-extension", "a.gpx.exe", "photo.gif"):
            with self.subTest(name):
                status, body = self.upload(sid, GPX, name)
                self.assertEqual(status, 415, body)
                self.assertIn("error", body)
        self.assertEqual(self.files(), [])

    def test_heic_refuse_avec_message_clair(self):
        self.start()
        sid = self.new_session()
        for name, data in (("IMG_0001.HEIC", HEIC), ("IMG_0001.jpg", HEIC), ("IMG_2.heif", JPG)):
            with self.subTest(name):
                status, body = self.upload(sid, data, name)
                self.assertEqual(status, 415)
                self.assertIn("JPEG", body["error"])
        self.assertEqual(self.files(), [])

    def test_contenu_falsifie(self):
        self.start()
        sid = self.new_session()
        cases = [("trace.gpx", PNG), ("photo.png", GPX), ("photo.jpg", GPX), ("photo.webp", PNG), ("trace.fit", GPX),
                 ("trace.gpx", FIT), ("trace.gpx", TCX), ("trace.tcx", GPX), ("trace.gpx", b"pas du xml"),
                 ("trace.gpx", GPX[:50])]
        for name, data in cases:
            with self.subTest(name, data=data[:8]):
                status, body = self.upload(sid, data, name)
                self.assertEqual(status, 415, body)
        self.assertEqual(self.files(), [])

    def test_xml_avec_doctype_ou_entite(self):
        self.start()
        sid = self.new_session()
        evil = [b'<?xml version="1.0"?><!DOCTYPE gpx [<!ENTITY a "boum">]><gpx>&a;</gpx>',
                b'<?xml version="1.0"?><!DOCTYPE lolz [<!ENTITY lol "lol"><!ENTITY lol2 "&lol;&lol;">]><gpx>&lol2;</gpx>',
                b'<!DOCTYPE gpx SYSTEM "http://127.0.0.1:1/x.dtd"><gpx/>',
                b'<?xml version="1.0"?><!ENTITY x SYSTEM "file:///etc/passwd"><gpx/>']
        for data in evil:
            for name in ("a.gpx", "a.tcx"):
                with self.subTest(name, data=data[:30]):
                    self.assertEqual(self.upload(sid, data, name)[0], 415)
        self.assertEqual(self.files(), [])

    def test_nom_d_origine_hostile(self):
        self.start()
        sid = self.new_session()
        names = ["../../etc/passwd.gpx", "../x.gpx", "/abs/olu.gpx", "a/b/c.gpx", "..\\..\\win.gpx", "nul\x00byte.gpx",
                 "été ✓ 日本.gpx", "....gpx", "x" * 400 + ".gpx", "a;rm -rf.gpx", "$(id).gpx", "-rf.gpx"]
        for name in names:
            with self.subTest(name[:25]):
                status, body = self.upload(sid, GPX, name)
                self.assertEqual(status, 200, body)
                self.assertRegex(Path(body["path"]).name, NAME_RE)
                self.assertEqual(Path(body["path"]).parent.as_posix(), "planning/inbox")
        self.assertTrue(all(f.startswith("planning/inbox/") for f in self.files()), self.files())
        self.assertEqual(len(self.files()), len(names))
        # en-tête brut : octets de contrôle, pourcentages invalides, absence d'en-tête
        for header in ("%2E%2E%2F%2E%2E%2Fz.gpx", "%00.gpx", "%ff%fe.gpx", "%"):
            with self.subTest(header):
                status, body = self.upload(sid, GPX, "ignored.gpx", headers={"X-Filename": header})
                self.assertIn(status, (200, 415), body)
        status, body = self.upload(sid, GPX, "ignored.gpx", headers={"X-Filename": ""})
        self.assertEqual(status, 415)
        self.assertTrue(all(f.startswith("planning/inbox/") for f in self.files()), self.files())

    def test_dossier_de_depot_lien_symbolique_refuse(self):
        outside = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(outside, ignore_errors=True))
        (self.ws / "planning").mkdir()
        (self.ws / "planning" / "inbox").symlink_to(outside)
        (self.ws / "gear").symlink_to(outside)
        self.start()
        sid = self.new_session()
        self.assertEqual(self.upload(sid, GPX, "a.gpx")[0], 500)
        self.assertEqual(self.upload(sid, JPG, "a.jpg")[0], 500)
        self.assertEqual(list(outside.iterdir()), [])

    def test_session_inconnue(self):
        self.start()
        self.assertEqual(self.upload("inconnue123456", GPX)[0], 404)
        self.assertEqual(self.upload("../../x", GPX)[0], 404)
        self.assertEqual(self.files(), [])

    def test_limite_de_debit(self):
        self.start()
        sid = self.new_session()
        self.service.upload_limiter.per_min = 2
        self.assertEqual([self.upload(sid, GPX)[0] for _ in range(3)], [200, 200, 429])

    def test_csrf_et_hote_exiges(self):
        self.start()
        sid = self.new_session()
        path = f"/api/chat/sessions/{sid}/attachments"
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.request("POST", path, body=GPX, headers={"X-Filename": "a.gpx"})              # sans X-ARC-Chat
        self.assertEqual(conn.getresponse().status, 403)
        conn.close()
        self.assertEqual(self.upload(sid, GPX, headers={"Origin": "https://evil.example"})[0], 403)
        self.assertEqual(self.upload(sid, GPX, headers={"Sec-Fetch-Site": "cross-site"})[0], 403)
        self.assertEqual(self.upload(sid, GPX, host="evil.example")[0], 403)
        self.assertEqual(self.files(), [])
        self.assertEqual(self.upload(sid, GPX, headers={"Sec-Fetch-Site": "same-origin"})[0], 200)

    def test_identite_exigee_en_mode_proxy(self):
        self.start(auth="proxy", allowed_users=["marco"], auth_header="Remote-User")
        status, _, data = self.post("/api/chat/sessions", headers={"Remote-User": "marco"})
        sid = data["id"]
        self.assertEqual(self.upload(sid, GPX)[0], 401)                                  # sans identité
        self.assertEqual(self.upload(sid, GPX, headers={"Remote-User": "intrus"})[0], 403)
        self.assertEqual(self.files(), [])
        self.assertEqual(self.upload(sid, GPX, headers={"Remote-User": "marco"})[0], 200)


class TestRefusalsWithRealBody(AttachCase):
    """Un refus envoyé avant la lecture du corps doit ATTEINDRE le client même avec ~2 Mo en route (pas de RST)."""

    def test_refus_avec_corps_de_2_mo(self):
        self.start(upload_max_bytes=1000)
        sid = self.new_session()
        big_jpg = b"\xff\xd8\xff" + b"\x00" * BIG
        status, body = self.upload(sid, big_jpg, "photo.jpg")
        self.assertEqual((status, "trop volumineux" in body["error"]), (413, True), body)
        self.service.cfg["upload_max_bytes"] = 4 * BIG
        status, body = self.upload(sid, big_jpg, "IMG_1.HEIC")
        self.assertEqual(status, 415, body)
        self.assertIn("JPEG", body["error"])
        status, body = self.upload("inconnue123456", big_jpg, "photo.jpg")
        self.assertEqual(status, 404, body)
        self.service.upload_limiter.per_min = 1
        self.assertEqual(self.upload(sid, big_jpg, "photo.jpg")[0], 200)
        status, body = self.upload(sid, big_jpg, "photo.jpg")
        self.assertEqual(status, 429, body)
        self.assertEqual(len(self.files()), 1)

    def test_les_refus_ne_consomment_pas_le_quota(self):
        self.start()
        sid = self.new_session()
        self.service.upload_limiter.per_min = 2
        for _ in range(4):
            self.assertEqual(self.upload("inconnue123456", GPX)[0], 404)
            self.assertEqual(self.upload(sid, GPX, "notes.txt")[0], 415)
        self.assertEqual([self.upload(sid, GPX)[0] for _ in range(3)], [200, 200, 429])


class TestRobustness(AttachCase):
    def test_plafond_invalide_retombe_sur_le_defaut(self):
        user = self.ws / "config"
        user.mkdir(parents=True)
        (user / "workspace.user.toml").write_text("[chat]\nupload_max_bytes = 0\n", encoding="utf-8")
        self.assertEqual(C.load_chat_config(self.ws)["upload_max_bytes"], 20 * 1024 * 1024)
        (user / "workspace.user.toml").write_text("[chat]\nupload_max_bytes = -1\n", encoding="utf-8")
        self.assertEqual(C.load_chat_config(self.ws)["upload_max_bytes"], 20 * 1024 * 1024)
        self.start(upload_max_bytes=-5)
        sid = self.new_session()
        self.assertEqual(self.upload(sid, GPX)[0], 200)
        self.assertEqual(self.get("/api/chat/status")[2]["upload_max_bytes"], 20 * 1024 * 1024)

    def test_message_d_erreur_de_taille_en_ko(self):
        self.start(upload_max_bytes=512 * 1024)
        sid = self.new_session()
        status, body = self.upload(sid, b"x" * (512 * 1024 + 1), "a.gpx")
        self.assertEqual(status, 413)
        self.assertIn("512 Ko", body["error"])

    def test_session_disparue_pendant_l_envoi(self):
        self.start()
        sid = self.new_session()
        self.service.sessions.add_attachment = lambda *a, **k: False
        status, body = self.upload(sid, GPX)
        self.assertEqual(status, 404, body)
        self.assertEqual(self.files(), [])                                       # fichier supprimé

    def test_fichier_renomme_apres_envoi(self):
        self.start()
        sid = self.new_session()
        path = self.upload(sid, JPG, "semelle.jpg")[1]["path"]
        (self.ws / path).rename(self.ws / "gear/photos/2026-11-01_pegasus_semelle.jpg")      # gear-inspection renomme
        status, raw = self.message(sid, "x", [path])
        self.assertEqual(status, 400)
        self.assertIn("n'existe plus", raw)

    def test_droits_selon_l_umask(self):
        import os
        old = os.umask(0o022)
        try:
            self.start()
            sid = self.new_session()
            path = self.upload(sid, GPX)[1]["path"]
        finally:
            os.umask(old)
        self.assertEqual((self.ws / path).stat().st_mode & 0o777, 0o644)

    def test_envoi_trop_lent_abandonne(self):
        self.start()
        sid = self.new_session()
        old = C.UPLOAD_MIN_DEADLINE_S
        C.UPLOAD_MIN_DEADLINE_S = 0.3
        self.addCleanup(lambda: setattr(C, "UPLOAD_MIN_DEADLINE_S", old))
        C.UPLOAD_MIN_RATE, old_rate = 10 ** 9, C.UPLOAD_MIN_RATE
        self.addCleanup(lambda: setattr(C, "UPLOAD_MIN_RATE", old_rate))
        import time
        head = (f"POST /api/chat/sessions/{sid}/attachments HTTP/1.1\r\nHost: 127.0.0.1:{self.port}\r\n"
                f"X-ARC-Chat: 1\r\nX-Filename: a.gpx\r\nContent-Length: 100000\r\n\r\n").encode()
        with socket.create_connection(("127.0.0.1", self.port), timeout=10) as sock:
            sock.sendall(head)
            reply = b""
            try:
                for _ in range(8):                           # goutte-à-goutte : le service coupe avant la fin
                    sock.sendall(b"<")
                    time.sleep(0.15)
                reply = sock.recv(65536)
            except OSError:
                pass                                         # coupure côté service : normal pour un client trop lent
        self.assertTrue(not reply or b" 408 " in reply.split(b"\r\n")[0], reply)
        self.assertEqual(self.files(), [])


class TestMessageLink(AttachCase):
    def test_prefixe_ajoute_au_texte_envoye_au_backend(self):
        self.start()
        sid = self.new_session()
        gpx = self.upload(sid, GPX, "trace.gpx")[1]
        img = self.upload(sid, JPG, "semelle.jpg")[1]
        status, raw = self.message(sid, "Analyse ça", [gpx["path"], img["path"]])
        self.assertEqual(status, 200)
        self.assertEqual(Capture.received, [f"Pièce jointe : {gpx['path']} (gpx)\n"
                                            f"Pièce jointe : {img['path']} (image)\nAnalyse ça"])
        self.assertIn(gpx["path"], raw)                                   # le mock accuse réception du fichier
        self.assertIn("event: done", raw)

    def test_commande_slash_reste_en_tete(self):
        self.start()
        sid = self.new_session()
        img = self.upload(sid, JPG, "semelle.jpg")[1]
        self.assertEqual(self.message(sid, "/inspection", [img["path"]])[0], 200)
        self.assertEqual(Capture.received, [f"/inspection\nPièce jointe : {img['path']} (image)"])

    def test_texte_vide_accepte_avec_piece_jointe(self):
        self.start()
        sid = self.new_session()
        gpx = self.upload(sid, GPX)[1]
        for text in ("", None, "   "):
            with self.subTest(repr(text)):
                self.assertEqual(self.message(sid, text, [gpx["path"]])[0], 200)
        self.assertTrue(all(m.endswith("Voici le fichier.") for m in Capture.received), Capture.received)
        self.assertEqual(self.message(sid, "", [])[0], 400)                          # ni texte ni fichier

    def test_historique_montre_les_pieces_jointes(self):
        self.start()
        sid = self.new_session()
        gpx = self.upload(sid, GPX)[1]
        self.message(sid, "Voilà", [gpx["path"]])
        _, _, detail = self.get(f"/api/chat/sessions/{sid}")
        user = [e for e in detail["events"] if e["type"] == "user_message"][0]["data"]
        self.assertEqual(user["text"], "Voilà")
        self.assertEqual(user["attachments"], [{"path": gpx["path"], "kind": "gpx"}])

    def test_chemin_non_cree_par_la_session_refuse(self):
        self.start()
        sid, other = self.new_session(), self.new_session()
        (self.ws / "planning").mkdir(exist_ok=True)
        (self.ws / "planning" / "secret.md").write_text("x")
        mine = self.upload(sid, GPX)[1]
        theirs = self.upload(other, GPX)[1]
        for paths in (["planning/secret.md"], ["../../etc/passwd"], ["config/workspace.user.toml"],
                      [theirs["path"]], [mine["path"], "planning/secret.md"], ["gear/photos/inexistante.jpg"]):
            with self.subTest(paths):
                status, raw = self.message(sid, "x", paths)
                self.assertEqual(status, 400, raw)
        self.assertEqual(Capture.received, [])
        self.assertEqual(self.message(sid, "x", [mine["path"]])[0], 200)           # le sien passe

    def test_forme_de_la_liste(self):
        self.start()
        sid = self.new_session()
        gpx = self.upload(sid, GPX)[1]
        for bad in ("planning/x.gpx", {"a": 1}, [1], [None], [[gpx["path"]]]):
            with self.subTest(repr(bad)):
                self.assertEqual(self.message(sid, "x", bad)[0], 400)
        self.assertEqual(self.message(sid, "x", [gpx["path"]] * 3)[0], 200)             # doublons écartés
        self.assertEqual(Capture.received[-1].count("Pièce jointe :"), 1)

    def test_dix_pieces_jointes_au_plus(self):
        self.start()
        sid = self.new_session()
        paths = [self.upload(sid, GPX + b"<!--%d-->" % i, "t.gpx")[1]["path"] for i in range(11)]
        self.assertEqual(self.message(sid, "x", paths)[0], 400)
        self.assertEqual(self.message(sid, "x", paths[:10])[0], 200)

    def test_le_texte_sans_piece_jointe_ne_change_pas(self):
        self.start()
        sid = self.new_session()
        self.assertEqual(self.message(sid, "Bonjour", [])[0], 200)
        self.assertEqual(Capture.received, ["Bonjour"])

    def test_session_survit_au_redemarrage(self):
        self.start()
        sid = self.new_session()
        gpx = self.upload(sid, GPX)[1]
        service = C.ChatService(self.ws, self.service.cfg, MockBackend(self.ws, {}), None)    # nouveau service, même disque
        records, problem = service.resolve_attachments(sid, [gpx["path"]])
        self.assertIsNone(problem)
        self.assertEqual(records, [{"path": gpx["path"], "kind": "gpx"}])


if __name__ == "__main__":
    unittest.main()
