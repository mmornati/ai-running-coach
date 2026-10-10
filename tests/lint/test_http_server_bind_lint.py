"""Palier B — aucun serveur HTTP du dépôt ne résout `socket.getfqdn` au démarrage.

`http.server.HTTPServer.server_bind` appelle `socket.getfqdn(host)` pour un
`server_name` que personne n'utilise. Sur les runners macOS de GitHub, cet appel
bloque ~35 s : `arc_serve.py` (puis `arc_chat.py` et les faux services des tests)
payaient ce délai au démarrage. Tout fichier qui instancie ou dérive un serveur de
`http.server` doit donc redéfinir `server_bind` — ou, pour un test, importer les
remplaçants de `tests/lib/local_http.py`.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent

# Outils de production vidéo, lancés à la main et hors suite de tests.
ALLOWED = {"scripts/video_gallery.py", "scripts/render_video.py"}

STDLIB_SERVER = re.compile(
    r"from\s+http\.server\s+import\s+[^\n]*\b(?:Threading)?HTTPServer\b"
    r"|\bhttp\.server\.(?:Threading)?HTTPServer\b")


class TestNoFqdnLookupAtBind(unittest.TestCase):
    def test_stdlib_servers_override_server_bind(self):
        files = sorted(REPO.glob("scripts/*.py")) + sorted(REPO.glob("tests/**/*.py"))
        self.assertTrue(files)
        for path in files:
            rel = path.relative_to(REPO).as_posix()
            if rel in ALLOWED or path == Path(__file__).resolve():
                continue
            text = path.read_text(encoding="utf-8")
            if STDLIB_SERVER.search(text):
                with self.subTest(file=rel):
                    self.assertIn("def server_bind", text,
                                  f"{rel} : serveur de http.server sans server_bind redéfini "
                                  "(getfqdn bloque ~35 s sur macOS) — utiliser tests/lib/local_http.py")


if __name__ == "__main__":
    unittest.main()
