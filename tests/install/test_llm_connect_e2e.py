"""Palier A — chaîne complète `install.sh --llm openrouter --chat --connect` dans un vrai terminal (#265).

Un pty fait croire à install.sh qu'un athlète est présent : connect_llm lance alors vraiment
`arc_llm.py connect openrouter`, qui ouvre le « navigateur » via `webbrowser`. La variable BROWSER
(prioritaire sur les navigateurs par défaut, Linux comme macOS) désigne un faux navigateur : il lit
`callback_url` et `state` dans l'adresse reçue puis rappelle le callback, comme le ferait l'athlète
en cliquant sur « Autoriser » (ou « Refuser »). Faux OpenRouter local (ARC_OPENROUTER_BASE_URL).

Verrouille : llm.env écrit (mode 600, autres lignes conservées), clé vérifiée, redémarrage du chat
tenté, config [chat]/[sync] cohérente, --connect absent des options mémorisées, la clé est vue par
le backend du chat, et aucune valeur de clé dans la transcription du terminal.
"""

from __future__ import annotations

import stat
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

from tests.install.test_llm_connect import SECRET_KEY, FakeOpenRouter
from tests.lib.asserts import InstallAsserts
from tests.lib.sandbox import STUBS_DIR, Sandbox

# Faux navigateur : détaché (webbrowser attend la fin du processus alors que arc_llm ne sert
# le callback qu'après l'ouverture), puis rappelle le callback avec FAKE_BROWSER_QUERY.
FAKE_BROWSER = textwrap.dedent('''\
    #!%(python)s
    import os, sys, time, urllib.parse, urllib.request
    url = sys.argv[1]
    with open(os.environ["FAKE_BROWSER_LOG"], "a") as fh:
        fh.write(url + "\\n")
    if os.fork():
        sys.exit(0)
    os.setsid()
    q = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
    query = os.environ["FAKE_BROWSER_QUERY"].replace("{state}", q["state"][0])
    target = q["callback_url"][0] + "?" + query
    for _ in range(50):
        try:
            urllib.request.urlopen(target, timeout=5).read()
            break
        except OSError:
            time.sleep(0.2)
''')


class InstallConnectE2ETests(InstallAsserts):
    ARGS = ("--no-auth", "--ide", "claude", "--llm", "openrouter", "--chat", "--connect")

    def setUp(self):
        self.sb = Sandbox()
        self.sb.__enter__()
        self.addCleanup(self.sb.__exit__, None, None, None)
        tmp = tempfile.TemporaryDirectory(prefix="arc-browser-")
        self.addCleanup(tmp.cleanup)
        self.browser = Path(tmp.name) / "fake-browser"
        self.browser.write_text(FAKE_BROWSER % {"python": sys.executable})
        self.browser.chmod(0o755)
        self.browser_log = Path(tmp.name) / "urls.log"
        self.env_file = self.sb.home / ".config/ai-running-coach/llm.env"
        self.env_file.parent.mkdir(parents=True, exist_ok=True)
        self.env_file.write_text("# commentaire\nOTHER_KEY=keep-me\n")

    def _run(self, fake, query: str):
        return self.sb.run_pty(
            [str(self.sb.repo / "install.sh"), *self.ARGS], [], timeout=120,
            ARC_OPENROUTER_BASE_URL=fake.url, BROWSER=str(self.browser),
            FAKE_BROWSER_LOG=str(self.browser_log), FAKE_BROWSER_QUERY=query)

    def _config(self) -> str:
        path = self.sb.repo / "config/workspace.user.toml"
        return path.read_text() if path.exists() else ""

    def _remembered(self) -> str:
        return (self.sb.home / ".config/ai-running-coach/install-args").read_text()

    def test_authorize_end_to_end(self):
        with FakeOpenRouter() as fake:
            proc = self._run(fake, "code=the-code&state={state}")
            exchanges, key_auth = list(fake.exchanges), list(fake.key_auth)
        out = proc.stdout
        self.assertEqual(proc.returncode, 0, out)
        self.assertNotIn(SECRET_KEY, out)
        self.assertNotIn("FAKE-SECRET", out)
        # Le faux navigateur a bien été utilisé (BROWSER prioritaire), une seule fois.
        urls = self.browser_log.read_text().split()
        self.assertEqual(len(urls), 1, out)
        self.assertTrue(urls[0].startswith(fake.url + "/auth?"))
        # Échange puis vérification de la clé.
        self.assertEqual([e["code"] for e in exchanges], ["the-code"])
        self.assertEqual(key_auth, ["Bearer " + SECRET_KEY])
        self.assertIn("OpenRouter connecté", out)
        # llm.env : clé écrite, reste conservé, mode 600.
        text = self.env_file.read_text()
        self.assertIn("OPENROUTER_API_KEY=" + SECRET_KEY, text)
        self.assertIn("OTHER_KEY=keep-me", text)
        self.assertIn("# commentaire", text)
        self.assertEqual(stat.S_IMODE(self.env_file.stat().st_mode), 0o600)
        # Redémarrage du chat tenté (aucun vrai service : stubs).
        self.assertIn("Redémarrage du chat", out)
        # Configuration cohérente, sans aucune clé dedans.
        cfg = self._config()
        self.assertNotIn(SECRET_KEY, cfg)
        self.assertRegex(cfg, r'(?s)\[chat\].*backend = "opencode"')
        self.assertIn('api_key_env = "OPENROUTER_API_KEY"', cfg)
        self.assertRegex(cfg, r'(?s)\[sync\].*runner = "opencode"')
        # --connect jamais mémorisé pour les mises à jour.
        self.assertNotIn("--connect", self._remembered())
        self.assertIn("openrouter", self._remembered())
        self._assert_backend_key(present=True)

    def test_denied_finishes_with_warning_and_no_key(self):
        with FakeOpenRouter() as fake:
            proc = self._run(fake, "error=access_denied")
            exchanges = list(fake.exchanges)
        out = proc.stdout
        self.assertEqual(proc.returncode, 0, out)       # l'installation se termine malgré le refus
        self.assertEqual(exchanges, [])
        self.assertIn("Connexion OpenRouter non terminée", out)
        self.assertNotIn(SECRET_KEY, out)
        text = self.env_file.read_text()
        self.assertNotIn("OPENROUTER_API_KEY=sk", text)
        self.assertIn("OTHER_KEY=keep-me", text)
        self.assertNotIn("Redémarrage du chat", out)
        self.assertNotIn("--connect", self._remembered())
        self._assert_backend_key(present=False)

    def _assert_backend_key(self, present: bool) -> None:
        """`check()` du backend OpenCode avec l'environnement que llm.env donnerait au service."""
        code = textwrap.dedent('''\
            import sys, tempfile
            sys.path.insert(0, %r)
            from pathlib import Path
            from arc_chat_opencode import OpenCodeBackend
            with tempfile.TemporaryDirectory() as ws:
                backend = OpenCodeBackend(Path(ws), {"api_key_env": "OPENROUTER_API_KEY",
                                                     "opencode_bin": %r})
                ok, msg = backend.check()
            print("CHECK_OK" if ok else "CHECK_FAIL " + msg)
        ''' % (str(self.sb.repo / "scripts"), str(STUBS_DIR / "opencode")))
        env = {"OPENROUTER_API_KEY": ""}
        for line in self.env_file.read_text().splitlines():
            name, sep, value = line.partition("=")
            if sep and not line.lstrip().startswith("#"):
                env[name.strip()] = value.strip()
        proc = self.sb.run([sys.executable, "-c", code], timeout=60, **env)
        if present:
            self.assertIn("CHECK_OK", proc.stdout, proc.stderr)
        else:
            self.assertIn("CHECK_FAIL", proc.stdout, proc.stderr)
            self.assertIn("OPENROUTER_API_KEY", proc.stdout)


if __name__ == "__main__":
    unittest.main()
