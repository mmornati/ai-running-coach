"""Palier D — pièces jointes du chat (#342) en mode famille : chaque membre écrit dans SON workspace."""

from __future__ import annotations

import http.client
import json
import unittest
from urllib.parse import quote

from tests.data.test_family_isolation import ChatCase, HEADER

GPX = b'<?xml version="1.0"?><gpx version="1.1" xmlns="http://www.topografix.com/GPX/1/1"><trk/></gpx>'
JPG = b"\xff\xd8\xff\xe0" + b"\x00" * 32


class TestFamilyAttachments(ChatCase):
    def setUp(self):
        super().setUp()
        self.port = self.start(self.registry())

    def upload(self, sid, user, data=GPX, name="trace.gpx", csrf=True):
        headers = {"Host": "coach.example.org", "Content-Type": "application/octet-stream",
                   "X-Filename": quote(name, safe="")}
        if csrf:
            headers["X-ARC-Chat"] = "1"
        if user is not None:
            headers[HEADER] = user
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=15)
        conn.request("POST", f"/api/chat/sessions/{sid}/attachments", body=data, headers=headers)
        res = conn.getresponse()
        body = json.loads(res.read() or b"{}")
        conn.close()
        return res.status, body

    def test_le_fichier_arrive_dans_le_workspace_du_membre(self):
        sid = self.new_session(self.port, "alice")
        status, body = self.upload(sid, "alice")
        self.assertEqual(status, 200, body)
        self.assertEqual((self.workspaces["alice"] / body["path"]).read_bytes(), GPX)
        self.assertFalse((self.workspaces["bob"] / "planning" / "inbox").exists())
        status, body = self.upload(sid, "alice", JPG, "semelle.jpg")
        self.assertEqual(status, 200, body)
        self.assertTrue((self.workspaces["alice"] / body["path"]).is_file())
        self.assertEqual(list((self.workspaces["bob"] / "gear" / "photos").glob("*.jpg")), [])

    def test_identite_et_csrf_exiges(self):
        sid = self.new_session(self.port, "alice")
        self.assertIn(self.upload(sid, None)[0], (401, 403))
        self.assertIn(self.upload(sid, "inconnu")[0], (401, 403))
        self.assertEqual(self.upload(sid, "alice", csrf=False)[0], 403)
        self.assertFalse((self.workspaces["alice"] / "planning" / "inbox").exists())

    def test_un_membre_ne_joint_pas_dans_la_conversation_d_un_autre(self):
        sid = self.new_session(self.port, "alice")
        self.assertEqual(self.upload(sid, "bob")[0], 404)                  # session d'Alice inconnue du service de Bob
        self.assertFalse((self.workspaces["bob"] / "planning" / "inbox").exists())

    def test_chemin_d_un_autre_membre_refuse_dans_un_message(self):
        a_sid = self.new_session(self.port, "alice")
        b_sid = self.new_session(self.port, "bob")
        path = self.upload(a_sid, "alice")[1]["path"]
        status, body = self.call(self.port, "POST", f"/api/chat/sessions/{b_sid}/messages", "bob",
                                 {"text": "x", "attachments": [path]})
        self.assertEqual(status, 400, body)


if __name__ == "__main__":
    unittest.main()
