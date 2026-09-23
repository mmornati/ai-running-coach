"""Palier A — tableau de bord de bout en bout : index, serveur, lanceur, installation.

Le serveur tourne pour de vrai (port libre choisi par le système) sur un
workspace synthétique au contrat (`tests/lib/synthetic.py`).
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import urllib.error
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
        self.assertIsNotNone(form["series"][-1]["ctl"])

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
        after = [r["title"] for r in json.loads(self.server.get("/api/reports")[1])["reports"]]
        self.assertIn("Bilan test", after)


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

