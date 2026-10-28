"""Palier D — recherche plein texte dans l'historique (`arc_search.py`, `arc_index.py search`).

Workspace synthétique écrit à la main (aucune donnée réelle) : fichiers du contrat, fichier hors contrat,
article de `resources/`, session du chat.
"""

from __future__ import annotations

import contextlib
import io
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))
import arc_index as I  # noqa: E402
import arc_search as SE  # noqa: E402
from arc_chat_policy import Policy  # noqa: E402

DECISION = """# Décision du 2026-10-04 — Douleur tibiale : semaine sans impact

```arc
{"arc": 1, "kind": "decision", "date": "2026-10-04", "created_at": "2026-10-04T12:00:00+02:00",
 "trigger": "medical", "summary": "Douleur au bas du tibia : course remplacée par du home trainer.",
 "outcome": "applied", "inputs": {}, "before": {}, "after": {}}
```

## Décision
- Douleur au bas du tibia à 4,5/10, déclarée le 01/10, absente au repos.

## Suite
- Reprise de la course seulement après une semaine sans douleur.
"""

ACTIVITY = """# Activité – 2026-09-13

```arc
{"arc": 1, "kind": "activity", "date": "2026-09-13", "sport": "trail", "name": "Trail des Crêtes",
 "duration_s": 18000, "distance_m": 42000, "garmin_activity_id": 9100001}
```

## Analyse globale
Fin de course sur les crêtes : beaucoup de marche, ravitaillement en orange.
"""

LEGACY_PLAN = """# Plan nutrition sans gluten

Éviter les bananes pendant la course : mauvaise tolérance digestive.
"""

RESOURCE = """# Tendinite : chaud ou froid ?

## Phase aiguë
Le froid calme l'inflammation du tendon les premiers jours.
"""


def chat_session(path: Path, sid: str, title: str) -> None:
    events = [
        {"ts": "2026-10-27T06:46:52Z", "type": "user_message", "data": {"text": "J'avais mal à la gorge cette nuit"}},
        {"ts": "2026-10-27T06:46:54Z", "type": "tool_start", "data": {"id": "t1", "name": "fs.read", "summary": "Lecture"}},
        {"ts": "2026-10-27T06:46:55Z", "type": "tool_end", "data": {"id": "t1", "ok": True, "summary": "Terminé"}},
        {"ts": "2026-10-27T06:46:59Z", "type": "text_delta", "data": {"text": "Un rhume en approche ", "part": "p1"}},
        {"ts": "2026-10-27T06:47:00Z", "type": "text_delta", "data": {"text": "expliquerait la HRV basse.", "part": "p1"}},
        {"ts": "2026-10-27T06:47:02Z", "type": "text_delta", "data": {"text": "Séance remplacée par du repos.", "part": "p2"}},
        {"ts": "2026-10-27T06:47:03Z", "type": "done", "data": {}},
    ]
    path.mkdir(parents=True, exist_ok=True)
    (path / f"{sid}.jsonl").write_text("\n".join(json.dumps(e, ensure_ascii=False) for e in events) + "\n",
                                       encoding="utf-8")
    (path / f"{sid}.json").write_text(json.dumps({"id": sid, "title": title}), encoding="utf-8")


class TestChunking(unittest.TestCase):
    def test_sections_and_arc_block(self):
        title, chunks = SE.chunk_markdown(DECISION)
        self.assertTrue(title.startswith("Décision du 2026-10-04"))
        headings = [h for h, _ in chunks]
        self.assertIn("Décision", headings)
        self.assertIn("Suite", headings)
        top = dict(chunks)[title]
        self.assertIn("summary: Douleur au bas du tibia", top)     # valeurs scalaires du bloc arc
        self.assertNotIn("inputs", top)                              # jamais les objets du bloc
        self.assertNotIn("```", "".join(b for _, b in chunks))

    def test_long_paragraph_cut_on_whitespace_and_short_tail_merged(self):
        para = " ".join(f"mot{i:04d}" for i in range(400))            # ≈ 3 200 caractères, un seul paragraphe
        _, chunks = SE.chunk_markdown(f"# T\n\n{para}\n\nfin.")
        bodies = [b for _, b in chunks]
        self.assertTrue(all(len(b) <= SE.CHUNK_MAX_CHARS + SE.CHUNK_MIN_CHARS + 2 for b in bodies))
        words = " ".join(bodies).split()
        self.assertTrue(all(w.startswith("mot") or w == "fin." for w in words))   # aucun mot coupé
        self.assertTrue(bodies[-1].endswith("fin."))
        self.assertGreater(len(bodies[-1]), SE.CHUNK_MIN_CHARS)    # « fin. » rattaché, pas un passage seul

    def test_invalid_arc_block_dropped(self):
        _, chunks = SE.chunk_markdown("# T\n\n```arc\n{pas du json\n```\n\nTexte.")
        self.assertEqual("".join(b for _, b in chunks).strip(), "Texte.")


class TestChatTurns(unittest.TestCase):
    def test_exchange_joins_reply_parts_and_skips_tools(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp)
        chat_session(tmp, "abc", "gorge")
        turns = SE.chat_turns((tmp / "abc.jsonl").read_text(encoding="utf-8"))
        self.assertEqual(len(turns), 1)
        day, text = turns[0]
        self.assertEqual(day, "2026-10-27")
        self.assertIn("Athlète : J'avais mal à la gorge", text)
        self.assertIn("Coach : Un rhume en approche expliquerait la HRV basse.\n\nSéance remplacée", text)
        self.assertNotIn("Lecture", text)

    def test_garbage_lines_ignored(self):
        self.assertEqual(SE.chat_turns("pas du json\n[1, 2]\n"), [])


class TestBuildMatch(unittest.TestCase):
    def test_stopwords_accents_prefix(self):
        self.assertEqual(SE.build_match("Pourquoi le tendon était en irritation ?"),
                         '"tendon" OR "etait" OR "irrita"*')
        self.assertEqual(SE.build_match("aponévrosite"), '"aponev"*')

    def test_phrase_kept_exact(self):
        self.assertEqual(SE.build_match('séance "côtes courtes"'), '"cotes courtes" OR "seance"')

    def test_only_stopwords_is_empty(self):
        self.assertEqual(SE.build_match("pourquoi le la ?"), "")

    def test_fts_syntax_never_passed_through(self):
        match = SE.build_match('tibia" OR body:* NEAR(x')
        self.assertNotIn("body:", match)
        self.assertNotIn("NEAR(", match)
        self.assertTrue(all(t.startswith('"') for t in match.split(" OR ")))


class SearchWorkspace(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="arc-search-"))
        self.addCleanup(shutil.rmtree, self.tmp)
        self.ws = self.tmp / "ws"
        self.write("planning/2026-10-04_decision_tibia-zero-impact.md", DECISION)
        self.write("activities/2026-09-13_trail.md", ACTIVITY)
        self.write("nutrition/2026-09-13_plan_course.md", LEGACY_PLAN)
        self.write("resources/health/tendinite-chaud-froid.md", RESOURCE)
        chat_session(self.ws / ".arc/chat/sessions", "sessGorge01", "mal à la gorge")
        self.conn = I.open_db(self.ws, memory=True)
        self.index()

    def write(self, rel: str, text: str) -> None:
        path = self.ws / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def index(self) -> dict:
        return I.index_workspace(self.conn, self.ws, "2026-10-28")

    def paths(self, query: str, **kw) -> list:
        return [r["path"] for r in I.search(self.conn, query, **kw)["results"]]

    def test_finds_each_source(self):
        self.assertEqual(self.paths("douleur tibia")[0], "planning/2026-10-04_decision_tibia-zero-impact.md")
        self.assertEqual(self.paths("bananes digestive"), ["nutrition/2026-09-13_plan_course.md"])  # hors contrat
        self.assertEqual(self.paths("tendon froid")[0], "resources/health/tendinite-chaud-froid.md")
        self.assertEqual(self.paths("gorge rhume"), ["chat/sessGorge01"])

    def test_result_shape(self):
        result = I.search(self.conn, "douleur tibia")
        self.assertEqual(result["status"], "ok")
        hit = result["results"][0]
        self.assertEqual((hit["source"], hit["kind"], hit["date"]), ("workspace", "decision", "2026-10-04"))
        self.assertIn("tibia", hit["text"])
        self.assertLessEqual(len(hit["text"]), SE.RESULT_TEXT_CHARS + 2)
        chat = I.search(self.conn, "gorge")["results"][0]
        self.assertEqual((chat["kind"], chat["session_id"], chat["date"], chat["title"]),
                         ("chat", "sessGorge01", "2026-10-27", "mal à la gorge"))

    def test_one_result_per_file_with_matching_excerpt(self):
        paths = self.paths("tibia douleur semaine reprise")
        self.assertEqual(len(paths), len(set(paths)))
        hit = I.search(self.conn, "reprise semaine")["results"][0]
        self.assertEqual(hit["heading"], "Suite")                    # le passage qui parle de la question

    def test_filters(self):
        self.assertEqual(self.paths("tibia gorge tendon", kinds=["chat"]), ["chat/sessGorge01"])
        self.assertEqual(self.paths("tibia gorge tendon", source="resources"),
                         ["resources/health/tendinite-chaud-froid.md"])
        self.assertEqual(self.paths("tibia crêtes", since="2026-10-01"),
                         ["planning/2026-10-04_decision_tibia-zero-impact.md"])
        self.assertEqual(self.paths("tibia crêtes", until="2026-09-30"), ["activities/2026-09-13_trail.md"])
        self.assertEqual(self.paths("tendon", since="2000-01-01"), [])   # sans date : exclu d'un filtre de date

    def test_incremental_update_and_removal(self):
        self.assertEqual(self.index()["search"], {"indexed": 0, "unchanged": 5, "removed": 0})
        self.write("nutrition/2026-09-13_plan_course.md", "# Plan\n\nPommes et oranges seulement.\n")
        (self.ws / "resources/health/tendinite-chaud-froid.md").unlink()
        self.assertEqual(self.index()["search"], {"indexed": 1, "unchanged": 3, "removed": 1})
        self.assertEqual(self.paths("bananes"), [])
        self.assertEqual(self.paths("oranges pommes")[0], "nutrition/2026-09-13_plan_course.md")
        self.assertEqual(self.paths("froid"), [])

    def test_empty_query(self):
        result = I.search(self.conn, "pourquoi le")
        self.assertEqual((result["status"], result["results"]), ("empty_query", []))

    def test_without_fts_reports_unavailable(self):
        self.conn.execute("DROP TABLE doc_chunk")
        self.assertEqual(I.index_search(self.conn, self.ws), {"status": "unavailable"})
        self.assertEqual(I.search(self.conn, "tibia")["status"], "unavailable")

    def run_cli(self, *argv) -> tuple:
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = I.main(["search", *argv, "--workspace", str(self.ws), "--db", str(self.tmp / "c.db")])
        return code, out.getvalue()

    def test_cli(self):
        code, out = self.run_cli("douleur tibia", "--kind", "decision,report", "--limit", "3")
        self.assertEqual(code, 0)
        result = json.loads(out)
        self.assertEqual([r["path"] for r in result["results"]],
                         ["planning/2026-10-04_decision_tibia-zero-impact.md"])
        code, out = self.run_cli("gorge", "--source", "chat", "--text")
        self.assertEqual(code, 0)
        self.assertIn("## chat/sessGorge01", out)
        self.assertIn("1 résultat(s) pour « gorge »", out)
        # la recherche n'indexe que les passages : les autres tables restent vides
        conn = I.open_db(self.ws, str(self.tmp / "c.db"))
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM decision").fetchone()[0], 0)

    def test_cli_errors(self):
        for argv in ((), ("tibia", "--limit", "0"), ("tibia", "--limit", "31"), ("tibia", "--since", "hier")):
            with self.subTest(argv=argv), self.assertRaises(I.ConfigError):
                self.run_cli(*argv)


class TestChatPolicy(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.policy = Policy.load(REPO, Path(tmp.name).resolve())

    def shell(self, command: str) -> str:
        return self.policy.decide("shell", {"command": command})

    def test_search_allowed(self):
        self.assertEqual(self.shell('python3 scripts/arc_index.py search "douleur tibia" --kind decision,health '
                                    '--since 2026-09-01 --limit 5 --text'), "allow")
        self.assertEqual(self.shell("python3 scripts/arc_index.py search \"l'ultra des crêtes\" --source chat"),
                         "allow")

    def test_shell_metacharacters_still_refused(self):
        self.assertEqual(self.shell('python3 scripts/arc_index.py search "pourquoi ?"'), "deny")
        self.assertEqual(self.shell('python3 scripts/arc_index.py search "tibia" --db /tmp/x.db'), "deny")


if __name__ == "__main__":
    unittest.main()
