"""Palier B — cohérence du schéma de configuration.

`config/workspace.toml` est la référence : toute valeur qu'il propose doit
exister quelque part (un profil de sport, une entrée du catalogue de styles, un
agent réel), et tout ce que l'onboarding demande doit correspondre à une clé
réelle.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
WORKSPACE_TOML = REPO / "config/workspace.toml"
STYLES_DOC = REPO / "config/coaching-styles.md"


def load_toml(path: Path) -> dict:
    """Charge un TOML avec tomllib si disponible, sinon un repli minimal.

    Le repli existe pour que le lint tourne aussi sous un Python < 3.11.
    """
    text = path.read_text(encoding="utf-8")
    try:
        import tomllib

        return tomllib.loads(text)
    except ImportError:
        pass
    data, section = {}, None
    for line in text.splitlines():
        line = line.split("#")[0].strip() if not line.strip().startswith("#") else ""
        if not line:
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1]
            data[section] = {}
        elif "=" in line and section:
            key, _, raw = line.partition("=")
            raw = raw.strip()
            if raw.startswith("[") and raw.endswith("]"):
                value = [v.strip().strip('"') for v in raw[1:-1].split(",") if v.strip()]
            else:
                value = raw.strip('"')
            data[section][key.strip()] = value
    return data


CONFIG = load_toml(WORKSPACE_TOML)

# Valeurs admises, telles qu'annoncées par les commentaires du fichier.
ENUMS = {
    ("athlete", "units"): {"metric", "imperial"},
    ("coaching", "intensity"): {"gentle", "balanced", "strong"},
    ("coaching", "verbosity"): {"brief", "standard", "detailed"},
    ("health", "morning_check"): {"full", "minimal", "off"},
}


class TestSchemaShape(unittest.TestCase):
    def test_expected_sections_exist(self):
        for section in ("language", "notifications", "sync", "athlete", "sport", "agents", "coaching", "health"):
            with self.subTest(section=section):
                self.assertIn(section, CONFIG, f"[{section}] absent de config/workspace.toml")

    def test_enum_defaults_are_valid(self):
        for (section, key), allowed in ENUMS.items():
            with self.subTest(key=f"{section}.{key}"):
                value = CONFIG.get(section, {}).get(key)
                self.assertIn(value, allowed, f"[{section}].{key} = {value!r} hors de {sorted(allowed)}")


class TestCoachingStyles(unittest.TestCase):
    def _catalogue_ids(self) -> set:
        text = STYLES_DOC.read_text(encoding="utf-8")
        section = text.split("## `style`")[1].split("## `intensity`")[0]
        return set(re.findall(r"^\|\s*`([a-z]+)`\s*\|", section, re.MULTILINE))

    def test_default_style_is_in_the_catalogue(self):
        self.assertIn(
            CONFIG["coaching"]["style"],
            self._catalogue_ids(),
            f"[coaching].style absent de {STYLES_DOC.name}",
        )

    def test_catalogue_documents_every_dial(self):
        text = STYLES_DOC.read_text(encoding="utf-8")
        for (section, key), allowed in ENUMS.items():
            if section != "coaching":
                continue
            for value in allowed:
                with self.subTest(dial=key, value=value):
                    self.assertIn(f"`{value}`", text, f"{key} = {value} non documenté")

    def test_catalogue_states_the_style_never_changes_the_verdict(self):
        """Garde-fou de sécurité : le ton ne doit jamais annuler une décision médicale."""
        text = STYLES_DOC.read_text(encoding="utf-8")
        self.assertIn("jamais du verdict", text, "la règle « le style ne change pas le fond » a disparu")


class TestAgentsSection(unittest.TestCase):
    def test_enabled_agents_exist(self):
        real = {p.stem for p in (REPO / "agents").glob("*.md")}
        declared = set(CONFIG["agents"]["enabled"])
        self.assertFalse(declared - real, f"agents déclarés mais inexistants : {sorted(declared - real)}")

    def test_default_enables_every_agent(self):
        """Le défaut versionné ne doit rien retirer : la sélection est un choix utilisateur."""
        real = {p.stem for p in (REPO / "agents").glob("*.md")}
        self.assertEqual(set(CONFIG["agents"]["enabled"]), real)


class TestAthleteProfile(unittest.TestCase):
    def test_profile_path_has_a_template(self):
        profile = CONFIG["athlete"]["profile"]
        template = REPO / "templates" / (Path(profile).stem + ".template.md")
        self.assertTrue(template.exists(), f"[athlete].profile = {profile} sans modèle : {template}")

    def test_profile_lives_in_a_gitignored_folder(self):
        profile = CONFIG["athlete"]["profile"]
        gitignore = (REPO / ".gitignore").read_text(encoding="utf-8")
        folder = profile.split("/")[0] + "/"
        self.assertIn(folder, gitignore, f"{folder} n'est pas gitignoré — le profil serait versionné")
