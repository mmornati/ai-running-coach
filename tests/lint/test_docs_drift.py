"""Palier B — dérive documentaire : comptages skills/agents et affirmations Garmin.

Ce module ne duplique pas `test_prompt_lint.py` (qui vérifie déjà que chaque
agent/skill a une page `docs/` et une entrée `mkdocs.yml`). Il couvre deux
classes de dérive distinctes, toutes deux responsables du bug d'origine
(issue #30) :

1. **Comptages obsolètes** (« 9 skills » alors qu'il y en a 12). Un regex nu sur
   « (\\d+)\\s+skills? » dans tout le texte produit trop de faux positifs — une
   phrase comme « Les 2 skills gpx et météo » n'est pas une affirmation de
   total — et rate les nombres en toutes lettres (« Neuf », « Douze ») ainsi
   que les fichiers qui ne sont pas passés en revue. On ne valide donc que les
   affirmations qui se présentent comme des **titres de section** (une ligne
   commençant par `#`), du **texte en gras** (`**...**`, le style utilisé par
   toutes les affirmations de comptage existantes), ou une ligne explicitement
   annotée par un marqueur HTML `<!-- count:skills -->` / `<!-- count:agents -->`
   pour les phrases qui ne sont ni un titre ni en gras (ex. la phrase d'intro
   de `docs/index.md`). Chiffres et nombres français de 1 à 20 sont acceptés.
2. **Affirmations « Garmin seulement »** qui ne reflètent plus le statut
   secondaire d'Intervals.icu. Le bug d'origine (« ne supporte que **Garmin**
   ») passait au travers d'un regex naïf à cause du markdown (`**`) inséré au
   milieu de la phrase : on retire donc `*`/`_` avant de chercher. Contrairement
   à la première version de ce test, aucune fenêtre de contexte ne vient
   « excuser » l'affirmation si Intervals.icu est mentionné à proximité — la
   phrase interdite doit être corrigée, point final. `ALLOWED_GARMIN_CLAIM_FILES`
   ci-dessous documente l'unique mécanisme d'exception, à n'utiliser qu'en
   dernier recours et avec une justification en commentaire.

Les vérifications sont écrites comme des fonctions pures (`root: Path` →
`list[str]` de problèmes) pour pouvoir être testées sur un dépôt jetable
(`TestFailureDetection`), sans dépendre de l'état actuel du dépôt réel.
"""

from __future__ import annotations

import re
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent

# --- Nombres en toutes lettres (français, 1 à 20) -----------------------------

FRENCH_NUMBERS = {
    # « un »/« une » sont délibérément exclus : dans une phrase du type
    # « Structure d'un skill », ce sont des articles indéfinis, pas un
    # comptage — et aucune affirmation réelle du projet n'annonce « 1 skill ».
    "deux": 2, "trois": 3, "quatre": 4, "cinq": 5,
    "six": 6, "sept": 7, "huit": 8, "neuf": 9, "dix": 10, "onze": 11,
    "douze": 12, "treize": 13, "quatorze": 14, "quinze": 15, "seize": 16,
    "dix-sept": 17, "dix-huit": 18, "dix-neuf": 19, "vingt": 20,
}

# Les formes composées (« dix-sept ») doivent être testées avant leurs
# préfixes (« dix ») dans l'alternative regex, d'où le tri par longueur.
_NUMBER_WORD_ALT = "|".join(re.escape(w) for w in sorted(FRENCH_NUMBERS, key=len, reverse=True))
_NUMBER_TOKEN = rf"(?:\d+|{_NUMBER_WORD_ALT})"


def _parse_number(token: str) -> int:
    return int(token) if token.isdigit() else FRENCH_NUMBERS[token.lower()]


# Une affirmation de comptage lie explicitement le nombre au nom qu'il qualifie
# (« 12 skills », « Quatre agents », « Neuf compétences ») — pas n'importe quel
# nombre présent sur la ligne.
_SKILL_NOUNS = r"skills?|comp[ée]tences?"
_AGENT_NOUNS = r"agents?|sp[ée]cialistes?|sp[ée]cialis[ée]s?"

COUNT_CLAIM = {
    "skills": re.compile(rf"\b(?P<num>{_NUMBER_TOKEN})\b\s+(?:{_SKILL_NOUNS})", re.IGNORECASE),
    "agents": re.compile(rf"\b(?P<num>{_NUMBER_TOKEN})\b\s+(?:{_AGENT_NOUNS})", re.IGNORECASE),
}

BOLD_SPAN = re.compile(r"\*\*([^*\n]+)\*\*")
COUNT_MARKER = re.compile(r"<!--\s*count:(skills|agents)\s*-->", re.IGNORECASE)

# Fichiers vivants passés en revue pour les comptages skills/agents. PRODUCT.md
# est délibérément exclu : c'est un instantané daté (voir la note ajoutée en
# tête du fichier), pas une source tenue à jour en continu.
DOC_FILES_FOR_COUNTS = ("README.md",) + tuple(f"docs/{p}" for p in ("index.md", "agents.md", "skills.md"))

# Fichiers passés en revue pour les affirmations « Garmin seulement ».
DOC_GLOB_FOR_GARMIN = ("README.md", "PRODUCT.md")


def _doc_files_for_counts(root: Path) -> list[Path]:
    return [root / rel for rel in DOC_FILES_FOR_COUNTS if (root / rel).exists()]


def _doc_files_for_garmin(root: Path) -> list[Path]:
    files = [root / rel for rel in DOC_GLOB_FOR_GARMIN if (root / rel).exists()]
    files.extend(sorted((root / "docs").rglob("*.md")) if (root / "docs").is_dir() else [])
    return files


def count_skills(root: Path) -> int:
    """Compte les dossiers skills/*/SKILL.md."""
    return len(list((root / "skills").glob("*/SKILL.md")))


def count_agents(root: Path) -> int:
    """Compte les fichiers agents/*.md."""
    return len(list((root / "agents").glob("*.md")))


def get_skill_names(root: Path) -> set:
    return {p.parent.name for p in (root / "skills").glob("*/SKILL.md")}


def _extract_count_claims(text: str):
    """Renvoie (type, valeur, numéro de ligne, ligne) pour chaque affirmation.

    Une ligne n'est examinée que si elle est un titre, contient un passage en
    gras, ou porte un marqueur `<!-- count:... -->` — voir le docstring du
    module pour la justification.
    """
    claims = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        candidates = []
        if stripped.startswith("#"):
            candidates.append(stripped)
        candidates.extend(BOLD_SPAN.findall(line))
        if COUNT_MARKER.search(line):
            candidates.append(line)
        for candidate in candidates:
            for kind, pattern in COUNT_CLAIM.items():
                match = pattern.search(candidate)
                if match:
                    claims.append((kind, _parse_number(match.group("num")), lineno, stripped))
    return claims


def check_skill_agent_counts(root: Path) -> list:
    """Palier B — les comptages annoncés dans les docs vivantes correspondent à la réalité."""
    problems = []
    actual = {"skills": count_skills(root), "agents": count_agents(root)}
    seen = set()
    for path in _doc_files_for_counts(root):
        text = path.read_text(encoding="utf-8")
        for kind, value, lineno, line in _extract_count_claims(text):
            key = (path, lineno, kind)
            if key in seen:
                continue
            seen.add(key)
            if value != actual[kind]:
                problems.append(
                    f"{path.relative_to(root)}:{lineno} annonce {value} {kind}, "
                    f"trouvé {actual[kind]} réellement : « {line} »"
                )
    return problems


def check_all_skills_documented(root: Path) -> list:
    """Palier B — chaque skill du répertoire est bien listé dans docs/skills.md."""
    docs_skills = root / "docs" / "skills.md"
    if not docs_skills.exists():
        return ["docs/skills.md est introuvable"]
    text = docs_skills.read_text(encoding="utf-8")
    listed = set(re.findall(r"skills/([a-z0-9-]+)\.md", text))
    missing = get_skill_names(root) - listed
    if not missing:
        return []
    return [f"skills absents de docs/skills.md : {', '.join(sorted(missing))}"]


# --- Affirmations « Garmin seulement » ----------------------------------------

_STRIP_EMPHASIS = re.compile(r"[*_`]")

# Chaque motif capture une manière différente d'affirmer, à tort, que Garmin
# est le seul backend supporté. Le texte est débarrassé de `*`/`_`/`` ` ``
# avant la recherche, pour ne pas laisser un `**Garmin**` au milieu de la
# phrase désamorcer le motif — c'est exactement ce qui a permis à la
# formulation d'origine (« ne supporte que **Garmin** ») de passer inaperçue.
FORBIDDEN_GARMIN_PATTERNS = [
    re.compile(r"ne\s+supporte\s+que\s+garmin", re.IGNORECASE),
    re.compile(r"garmin\s+(?:seulement|uniquement|exclusivement)", re.IGNORECASE),
    re.compile(r"garmin\s+only", re.IGNORECASE),
    re.compile(r"seul\w*\s+garmin\s+(?:est\s+)?support\w*", re.IGNORECASE),
    re.compile(r"garmin\s+(?:est\s+)?le\s+seul", re.IGNORECASE),
    re.compile(r"seule\s+source\s+de\s+donn[ée]es\s+support[ée]e", re.IGNORECASE),
]

# Mécanisme d'exception documenté (finding #2 de la revue) : un fichier listé
# ici échappe à `check_garmin_only_claims`. Vide par défaut — à ne remplir
# qu'avec une justification en commentaire au-dessus de l'entrée.
ALLOWED_GARMIN_CLAIM_FILES: set = set()


def check_garmin_only_claims(root: Path) -> list:
    """Palier B — aucune doc n'affirme que Garmin est le seul backend supporté."""
    problems = []
    for path in _doc_files_for_garmin(root):
        rel = path.relative_to(root).as_posix()
        if rel in ALLOWED_GARMIN_CLAIM_FILES:
            continue
        text = path.read_text(encoding="utf-8")
        for lineno, line in enumerate(text.splitlines(), start=1):
            cleaned = _STRIP_EMPHASIS.sub("", line)
            for pattern in FORBIDDEN_GARMIN_PATTERNS:
                if pattern.search(cleaned):
                    problems.append(f"{rel}:{lineno} affirmation « Garmin seulement » : « {line.strip()} »")
                    break
    return problems


# --- Tests sur le dépôt réel ---------------------------------------------------


class TestSkillAgentCounts(unittest.TestCase):
    def test_counts_match_reality(self):
        problems = check_skill_agent_counts(REPO)
        self.assertFalse(problems, "\n" + "\n".join(problems))


class TestSkillDocumentation(unittest.TestCase):
    def test_all_skills_listed_in_docs(self):
        problems = check_all_skills_documented(REPO)
        self.assertFalse(problems, "\n" + "\n".join(problems))


class TestGarminOnlyClaims(unittest.TestCase):
    def test_no_garmin_only_claims(self):
        problems = check_garmin_only_claims(REPO)
        self.assertFalse(problems, "\n" + "\n".join(problems))


# --- Détection des régressions sur un dépôt jetable ---------------------------


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _make_minimal_repo(root: Path) -> None:
    """Construit un dépôt minimal, cohérent, à deux skills et deux agents.

    Chaque test de `TestFailureDetection` part de cette base saine puis
    introduit une seule dérive, pour prouver que c'est bien elle qui est
    détectée (et rien d'autre).
    """
    for skill in ("gpx-analysis", "weather-forecast"):
        _write(root / "skills" / skill / "SKILL.md", f"---\nname: {skill}\n---\n# {skill}\n")
    for agent in ("coach", "medical"):
        _write(root / "agents" / f"{agent}.md", f"---\nname: {agent}\n---\n# {agent}\n")
    _write(
        root / "README.md",
        "# Projet\n\n"
        "| 🧠 **2 agents spécialisés** | coach, medical |\n"
        "| 🛠️ **2 skills** | gpx-analysis, weather-forecast |\n",
    )
    _write(
        root / "docs" / "skills.md",
        "# Skills\n\n"
        "Fournit **2 skills**.\n\n"
        '<div class="arc-skill"><a href="skills/gpx-analysis.md">GPX</a></div>\n'
        '<div class="arc-skill"><a href="skills/weather-forecast.md">Météo</a></div>\n',
    )


class TestFailureDetection(unittest.TestCase):
    """Prouve que chaque fonction pure détecte bien la dérive qu'elle prétend attraper."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        _make_minimal_repo(self.root)

    def test_healthy_repo_has_no_problems(self):
        """Garde-fou : le dépôt de base ne doit lui-même déclencher aucun test."""
        self.assertFalse(check_skill_agent_counts(self.root))
        self.assertFalse(check_all_skills_documented(self.root))
        self.assertFalse(check_garmin_only_claims(self.root))

    def test_extra_skill_dir_breaks_readme_count(self):
        _write(self.root / "skills" / "new-skill" / "SKILL.md", "---\nname: new-skill\n---\n# new-skill\n")
        problems = check_skill_agent_counts(self.root)
        self.assertTrue(any("2 skills" in p and "3" in p for p in problems), problems)

    def test_extra_skill_dir_also_missing_from_docs(self):
        _write(self.root / "skills" / "new-skill" / "SKILL.md", "---\nname: new-skill\n---\n# new-skill\n")
        problems = check_all_skills_documented(self.root)
        self.assertTrue(any("new-skill" in p for p in problems), problems)

    def test_wrong_count_in_readme(self):
        readme = self.root / "README.md"
        readme.write_text(
            readme.read_text(encoding="utf-8").replace("**2 skills**", "**5 skills**"),
            encoding="utf-8",
        )
        problems = check_skill_agent_counts(self.root)
        self.assertTrue(any("annonce 5 skills" in p for p in problems), problems)

    def test_wrong_agent_count(self):
        readme = self.root / "README.md"
        readme.write_text(
            readme.read_text(encoding="utf-8").replace("**2 agents spécialisés**", "**4 agents spécialisés**"),
            encoding="utf-8",
        )
        problems = check_skill_agent_counts(self.root)
        self.assertTrue(any("annonce 4 agents" in p for p in problems), problems)

    def test_skill_missing_from_docs(self):
        docs = self.root / "docs" / "skills.md"
        docs.write_text(
            docs.read_text(encoding="utf-8").replace(
                '<div class="arc-skill"><a href="skills/weather-forecast.md">Météo</a></div>\n', ""
            ),
            encoding="utf-8",
        )
        problems = check_all_skills_documented(self.root)
        self.assertTrue(any("weather-forecast" in p for p in problems), problems)

    def test_neuf_skills_word_count_mismatch(self):
        """Le nombre en toutes lettres doit aussi être vérifié, pas seulement les chiffres."""
        docs = self.root / "docs" / "skills.md"
        docs.write_text(
            docs.read_text(encoding="utf-8") + "\n## Neuf skills, prêts à l'emploi\n",
            encoding="utf-8",
        )
        problems = check_skill_agent_counts(self.root)
        self.assertTrue(any("annonce 9 skills" in p for p in problems), problems)

    def test_garmin_only_claim_detected_despite_bold_markdown(self):
        """Reproduit le bug d'origine : le markdown au milieu de la phrase ne doit plus l'excuser."""
        _write(self.root / "README.md", (self.root / "README.md").read_text(encoding="utf-8")
               + "\nLe projet ne supporte que **Garmin** dans cette version.\n")
        problems = check_garmin_only_claims(self.root)
        self.assertTrue(any("ne supporte que" in p or "Garmin" in p for p in problems), problems)

    def test_garmin_only_claim_not_excused_by_nearby_context(self):
        """Contrairement à la version précédente du test, mentionner Intervals.icu à proximité
        ne doit plus dispenser de corriger l'affirmation."""
        _write(
            self.root / "README.md",
            (self.root / "README.md").read_text(encoding="utf-8")
            + "\nLe projet ne supporte que **Garmin** dans cette version. "
            + "Intervals.icu est un service secondaire optionnel.\n",
        )
        problems = check_garmin_only_claims(self.root)
        self.assertTrue(problems, "l'affirmation doit rester détectée malgré le contexte")


if __name__ == "__main__":
    unittest.main()
