"""Palier B — intégrité de la documentation, sans installer mkdocs.

`mkdocs build --strict` échoue sur un lien mort, mais il tourne uniquement en CI.
Ces contrôles attrapent la même chose en quelques millisecondes, partout.
"""

from __future__ import annotations

import re
import subprocess
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
DOCS = REPO / "docs"

MARKDOWN_LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
ATTR_LIST_ID = re.compile(r"\s*\{#([A-Za-z0-9_-]+)\}\s*$")
NAV_ENTRY = re.compile(r"^\s+-\s+[^:]+:\s*([A-Za-z0-9_./-]+\.md)\s*$", re.MULTILINE)


def doc_files() -> list:
    return sorted(DOCS.rglob("*.md"))


class TestInternalLinks(unittest.TestCase):
    def test_relative_links_resolve(self):
        broken = []
        for path in doc_files():
            for target in MARKDOWN_LINK.findall(path.read_text(encoding="utf-8")):
                if target.startswith(("http://", "https://", "mailto:", "#")):
                    continue
                file_part = target.split("#", 1)[0].split("?", 1)[0]  # ?lang=en : paramètre, pas un fichier
                if not file_part:
                    continue                       # ancre dans la même page
                if not (path.parent / file_part).resolve().exists():
                    broken.append(f"{path.relative_to(REPO)} → {target}")
        self.assertFalse(broken, "liens internes morts :\n  " + "\n  ".join(broken))

    def test_anchors_point_at_real_headings(self):
        broken = []
        for path in doc_files():
            for target in MARKDOWN_LINK.findall(path.read_text(encoding="utf-8")):
                if target.startswith(("http://", "https://", "mailto:")) or "#" not in target:
                    continue
                file_part, _, anchor = target.partition("#")
                page = (path.parent / file_part).resolve() if file_part else path
                if not page.exists():
                    continue                       # déjà signalé par le test précédent
                if anchor not in heading_anchors(page.read_text(encoding="utf-8")):
                    broken.append(f"{path.relative_to(REPO)} → {target}")
        self.assertFalse(broken, "ancres inexistantes :\n  " + "\n  ".join(broken))


def heading_anchors(text: str) -> set:
    """Ancres générées par mkdocs pour les titres de `text`. attr_list (mkdocs.yml) : pour
    `## Titre {#id-stable}`, seul l'id explicite existe — jamais aussi le slug automatique."""
    anchors = set()
    for line in text.splitlines():
        if not line.startswith("#"):
            continue
        heading = line.lstrip("#").strip()
        explicit = ATTR_LIST_ID.search(heading)
        if explicit:
            anchors.add(explicit.group(1))
            continue
        anchors.add(_slugify(heading))
    return anchors


class TestHeadingAnchors(unittest.TestCase):
    def test_explicit_id_replaces_the_automatic_slug(self):
        anchors = heading_anchors("## Les huit règles {#les-regles}\n\n## Autre titre\n")
        self.assertIn("les-regles", anchors)
        self.assertNotIn("les-huit-regles", anchors)
        self.assertIn("autre-titre", anchors)


def _slugify(heading: str) -> str:
    """Génération d'ancre mkdocs — l'implémentation réelle si disponible.

    `markdown.extensions.toc.slugify` est ce que mkdocs-material utilise
    vraiment (voir `mkdocs.yml` → `toc.permalink`) : on l'utilise quand le
    paquet est installé (CI docs, ou un `pip install -r requirements-docs.txt`
    local), pour ne jamais diverger de la sortie réelle. Le repli ci-dessous
    n'est qu'une approximation pour les environnements sans `markdown` — un
    point qui compte : `[-\\s]+` fusionne UN SEUL tiret entre deux mots
    (Python-Markdown ne préserve pas les tirets multiples d'une ponctuation
    retirée), contrairement à un `[\\s_]+` qui laisserait des tirets doubles.
    """
    try:
        from markdown.extensions.toc import slugify as _markdown_slugify

        return _markdown_slugify(heading, "-")
    except ImportError:
        pass

    return _slugify_fallback(heading)


def _slugify_fallback(heading: str) -> str:
    """Repli utilisé quand `markdown` n'est pas installé (le cas de la CI du
    palier B, qui n'installe pas les dépendances docs).

    Reproduit exactement l'approche de Python-Markdown
    (`markdown.extensions.toc.slugify`) : `encode("ascii", "ignore")` après la
    normalisation NFKD, PAS un simple retrait des diacritiques combinants. La
    différence compte pour une lettre sans décomposition ASCII : « œ », « ß »
    n'ont pas de forme NFKD qui isole un diacritique à retirer — un filtre par
    `unicodedata.combining()` les laisse tels quels (« cœur » → « cœur »),
    alors que l'encodage ASCII avec `errors="ignore"` les fait disparaître
    purement et simplement (« cœur » → « cur », comme le fait réellement
    Python-Markdown).
    """
    import unicodedata

    text = unicodedata.normalize("NFKD", heading).encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^\w\s-]", "", text).strip().lower()
    return re.sub(r"[-\s]+", "-", text)


# Titres qui exercent chacun un piège différent du slugifier — voir les deux
# classes de test ci-dessous. Une lettre sans décomposition ASCII (œ, ß) est
# le cas qui a fait dériver une version antérieure du repli (elle utilisait
# `unicodedata.combining()`, qui ne les touche pas, au lieu d'un encodage
# ASCII avec `errors="ignore"`, qui les supprime — comme Python-Markdown).
SLUGIFY_CASES = {
    "œ": "Cœur et œuvre",
    "ß": "Straße",
    "accents": "Préréglages — été, garçon",
    "underscores": "under_score_word",
    "backticks": "Préréglages (`--preset`)",
    "double_dash": "A -- B",
    "em_dash": "Em—dash here",
    "emoji": "Emoji 🚀 Test",
    "apostrophe": "L’apostrophe typographique",
}


class TestSlugifyFallbackMatchesRealMarkdown(unittest.TestCase):
    """Le repli (utilisé quand `markdown` n'est pas installé) doit produire
    EXACTEMENT la même ancre que `markdown.extensions.toc.slugify`, la vraie
    implémentation utilisée par mkdocs-material en production.

    Ignoré si `markdown` n'est pas disponible dans cet environnement (c'est le
    cas du palier B tel qu'exécuté en CI, qui n'installe pas les dépendances
    de `requirements-docs.txt`) — `test_slugify_fallback_hardcoded_expectations`
    ci-dessous verrouille ces mêmes cas sans dépendre du paquet.
    """

    def setUp(self):
        try:
            from markdown.extensions.toc import slugify  # noqa: F401
        except ImportError:
            self.skipTest("le paquet « markdown » n'est pas installé dans cet environnement")

    def test_fallback_matches_real_slugify(self):
        from markdown.extensions.toc import slugify as real_slugify

        mismatches = []
        for label, heading in SLUGIFY_CASES.items():
            expected = real_slugify(heading, "-")
            got = _slugify_fallback(heading)
            if got != expected:
                mismatches.append(f"{label} ({heading!r}) : repli={got!r} réel={expected!r}")
        self.assertFalse(mismatches, "repli divergent du vrai slugify mkdocs :\n  " + "\n  ".join(mismatches))


class TestSlugifyFallbackHardcodedExpectations(unittest.TestCase):
    """Verrouille le repli avec des valeurs figées — tourne dans TOUTE CI,
    avec ou sans `markdown` installé (contrairement au test ci-dessus)."""

    EXPECTED = {
        "Cœur et œuvre": "cur-et-uvre",
        "Straße": "strae",
        "Préréglages — été, garçon": "prereglages-ete-garcon",
        "under_score_word": "under_score_word",
        "Préréglages (`--preset`)": "prereglages-preset",
        "A -- B": "a-b",
        "Em—dash here": "emdash-here",
        "Emoji 🚀 Test": "emoji-test",
        "L’apostrophe typographique": "lapostrophe-typographique",
    }

    def test_fallback_hardcoded_expectations(self):
        mismatches = [
            f"{heading!r} : attendu {expected!r}, obtenu {_slugify_fallback(heading)!r}"
            for heading, expected in self.EXPECTED.items()
            if _slugify_fallback(heading) != expected
        ]
        self.assertFalse(mismatches, "repli du slugifier :\n  " + "\n  ".join(mismatches))


class TestNav(unittest.TestCase):
    def test_every_nav_entry_exists(self):
        nav = (REPO / "mkdocs.yml").read_text(encoding="utf-8")
        nav = nav.split("nav:", 1)[1]
        missing = [entry for entry in NAV_ENTRY.findall(nav) if not (DOCS / entry).is_file()]
        self.assertFalse(missing, f"entrées de navigation sans fichier : {missing}")

    def test_every_page_is_reachable(self):
        nav = (REPO / "mkdocs.yml").read_text(encoding="utf-8").split("nav:", 1)[1]
        listed = set(NAV_ENTRY.findall(nav))
        orphans = sorted(
            str(p.relative_to(DOCS)) for p in doc_files()
            if str(p.relative_to(DOCS)) not in listed
        )
        self.assertFalse(orphans, f"pages absentes de la navigation : {orphans}")


class TestFixturesAreTracked(unittest.TestCase):
    """Les fixtures des évals doivent être dans le dépôt.

    `.gitignore` excluait `activities/`, `planning/`… sans ancre, donc aussi
    `tests/evals/fixtures/*/activities/`. Les fixtures disparaissaient en
    silence : le palier C n'aurait rien eu à lire en CI.
    """

    FIXTURES = REPO / "tests/evals/fixtures"

    def test_no_fixture_file_is_gitignored(self):
        files = [p for p in self.FIXTURES.rglob("*") if p.is_file()]
        self.assertTrue(files, "aucune fixture trouvée")
        proc = subprocess.run(
            ["git", "check-ignore", "--stdin"],
            input="\n".join(str(p.relative_to(REPO)) for p in files),
            capture_output=True, text=True, cwd=str(REPO),
        )
        ignored = [line for line in proc.stdout.splitlines() if line.strip()]
        self.assertFalse(ignored, "fixtures exclues par .gitignore :\n  " + "\n  ".join(ignored))

    def test_work_directory_patterns_are_anchored(self):
        """Un motif non ancré s'applique à toute profondeur — jamais ce qu'on veut ici."""
        unanchored = []
        for line in (REPO / ".gitignore").read_text(encoding="utf-8").splitlines():
            entry = line.strip()
            if entry.rstrip("/") in ("activities", "medical", "nutrition", "planning",
                                     "rapports", "resources", "gear") and not entry.startswith("/"):
                unanchored.append(entry)
        self.assertFalse(
            unanchored,
            f"motifs de dossiers de travail non ancrés (ajoutez « / ») : {unanchored}",
        )
