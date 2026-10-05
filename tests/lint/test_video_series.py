"""Palier B — la série vidéo « Le Sentier » (docs/video/) reste cohérente.

Aucune synthèse vocale ni navigateur ici : on vérifie seulement ce qui se lit
dans les fichiers versionnés.

- chaque épisode de `SERIES` (docs/video/engine/engine.js) a sa page, son script,
  ses scènes, et `ARC.episode({ n, slug })` y correspond ;
- le minutage (`timing.js`) et l'audio sont à jour du script et du lexique
  (`scripts/video_narration.py --check`) ;
- la galerie `docs/videos.md`, les cartes « En vidéo » et les vignettes sont à jour
  (`scripts/video_gallery.py --check`) ;
- chaque page de documentation visée existe ;
- les scènes sont des fonctions pures du temps : ni `Math.random`, ni `Date.now`,
  ni `new Date(` — sinon l'export image par image ne serait plus reproductible.
"""

from __future__ import annotations

import io
import json
import re
import sys
import unittest
from contextlib import redirect_stderr
from unittest import mock
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import video_gallery  # noqa: E402
import video_narration  # noqa: E402

VIDEO = REPO / "docs" / "video"


def episode_dirs() -> list[Path]:
    return [VIDEO / e["dir"] for e in video_gallery.series()]


class TestSeriesStructure(unittest.TestCase):
    def test_every_published_episode_is_complete(self):
        for ep in video_gallery.series():
            d = VIDEO / ep["dir"]
            if not d.exists():
                continue  # épisode annoncé, pas encore tourné
            with self.subTest(episode=ep["dir"]):
                for f in ("script.json", "scenes.js", "timing.js", "poster.jpg", "subs.fr.vtt", "subs.en.vtt",
                          "audio/fr.m4a", "audio/en.m4a"):
                    self.assertTrue((d / f).exists(), f"{d.name}/{f} absent")
                page = VIDEO / ep["page"].removeprefix("video/")
                self.assertTrue(page.exists(), f"page absente : {page}")

    def test_scenes_declare_their_series_number_and_slug(self):
        for ep in video_gallery.series():
            js = VIDEO / ep["dir"] / "scenes.js"
            if not js.exists():
                continue
            src = js.read_text(encoding="utf-8")
            with self.subTest(episode=ep["dir"]):
                m = re.search(r"ARC\.episode\(\{\s*n:\s*(\d+),\s*slug:\s*\"([^\"]+)\"", src)
                self.assertIsNotNone(m, "appel ARC.episode({ n, slug, … }) introuvable")
                self.assertEqual(int(m.group(1)), ep["n"])
                self.assertEqual(m.group(2), ep["dir"])

    def test_scripts_open_on_the_bib_and_close_on_the_finish_line(self):
        for d in episode_dirs():
            if d.name == "bande-annonce" or not (d / "script.json").exists():
                continue
            ids = [s["id"] for s in json.loads((d / "script.json").read_text(encoding="utf-8"))["scenes"]]
            with self.subTest(episode=d.name):
                self.assertEqual(ids[0], "bib")
                self.assertEqual(ids[-1], "finish")

    def test_every_scene_has_both_languages_or_neither(self):
        for d in episode_dirs():
            if not (d / "script.json").exists():
                continue
            for sc in json.loads((d / "script.json").read_text(encoding="utf-8"))["scenes"]:
                with self.subTest(episode=d.name, scene=sc["id"]):
                    self.assertEqual(bool(sc.get("fr")), bool(sc.get("en")), "réplique dans une seule langue")
                    if sc.get("chapter"):
                        self.assertEqual(set(sc["chapter"]), {"fr", "en"})

    def test_scenes_are_pure_functions_of_time(self):
        for d in episode_dirs():
            js = d / "scenes.js"
            if not js.exists():
                continue
            src = js.read_text(encoding="utf-8")
            with self.subTest(episode=d.name):
                for bad in ("Math.random", "Date.now", "new Date(", "performance.now"):
                    self.assertNotIn(bad, src, f"{d.name}/scenes.js : {bad} rend le rendu non reproductible")

    def test_documentation_targets_exist(self):
        docs = REPO / "docs"
        for ep in video_gallery.series():
            if not ep["docs"]:
                continue
            with self.subTest(episode=ep["dir"]):
                stem = docs / ep["docs"].rstrip("/")
                self.assertTrue(stem.with_suffix(".md").exists() or (stem / "index.md").exists(),
                                f"page de documentation absente : {ep['docs']}")


class TestGeneratedFilesAreFresh(unittest.TestCase):
    def test_narration_timing_matches_scripts(self):
        err = io.StringIO()
        with redirect_stderr(err):
            code = video_narration.main(["--check"])
        self.assertEqual(code, 0, err.getvalue())

    def test_gallery_cards_and_posters_are_up_to_date(self):
        err = io.StringIO()
        with redirect_stderr(err):
            code = video_gallery.main(["--check"])
        self.assertEqual(code, 0, err.getvalue())

    def test_lexicons_are_valid(self):
        for f in [VIDEO / "lexicon.json", *VIDEO.glob("*/lexicon.json")]:
            with self.subTest(file=f.name):
                data = json.loads(f.read_text(encoding="utf-8"))
                for lang in ("fr", "en"):
                    self.assertIsInstance(data.get(lang, {}), dict)


if __name__ == "__main__":
    unittest.main()


class TestNarrationEngines(unittest.TestCase):
    """Moteurs de voix : le lexique s'adapte au moteur, kokoro reste inchangé."""

    def setUp(self):
        self.ep = episode_dirs()[0]

    def test_ipa_entries_per_engine(self):
        text = "Le coach et Garmin."
        self.assertIn("[[kˈotʃ]]", video_narration.pronounce(text, "fr", self.ep, "kokoro"))
        self.assertIn("[[kˈotʃ|coach]]", video_narration.pronounce(text, "fr", self.ep, "azure"))
        self.assertEqual(video_narration.pronounce(text, "fr", self.ep, "kyutai"), text)

    def test_replacement_is_never_reread(self):
        # « coach » dans le remplacement `[[…|ai-running-coach]]` ne doit pas être resubstitué
        lex = {"ai-running-coach": "[[a i]]", "coach": "[[k]]"}
        with mock.patch.object(video_narration, "lexicon", return_value=lex):
            out = video_narration.pronounce("ai-running-coach", "fr", self.ep, "azure")
        self.assertEqual(out, "[[a i|ai-running-coach]]")

    def test_microsoft_family_lexicon(self):
        for engine in ("edge", "azure"):
            out = video_narration.pronounce("Tapez /why dans votre IDE.", "fr", self.ep, engine)
            self.assertEqual(out, "Tapez slash why dans votre I D E.", engine)
        self.assertNotIn("_doc", video_narration.lexicon(self.ep, "fr", "edge"))

    def test_azure_ssml_uses_phoneme_tags(self):
        eng = video_narration.make_engine("azure")
        ssml = eng.ssml("Le [[kˈotʃ|coach]] & moi", eng.voices["fr"])
        self.assertIn('<phoneme alphabet="ipa" ph="kˈotʃ">coach</phoneme>', ssml)
        self.assertIn("&amp; moi", ssml)

    def test_kokoro_digest_ignores_missing_engine_fields(self):
        data = video_narration.load_script(self.ep)
        self.assertEqual(video_narration.script_digest(self.ep, data, "fr"),
                         video_narration.script_digest(self.ep, data, "fr", "kokoro", None))
        self.assertNotEqual(video_narration.script_digest(self.ep, data, "fr"),
                            video_narration.script_digest(self.ep, data, "fr", "kyutai"))
