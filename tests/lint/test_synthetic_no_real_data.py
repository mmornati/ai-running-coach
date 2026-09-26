"""Palier B — le générateur d'échantillons synthétiques (story #25) ne doit
jamais produire de donnée qui ressemble à une vraie séance Garmin.

Aucun modèle, aucun réseau : appelle directement les fonctions pures de
`tests.lib.synthetic`, ne lance aucun sous-processus.

`TestNoRealCoordinatesInTests` (#49, revue de code) étend cette discipline à TOUTE
coordonnée GPS littérale des tests eux-mêmes (`tests/**/*.py`, story de l'identité de
montée entre séances) : aucune trace de test ne doit ressembler à un lieu réellement
enregistré (ex. les coordonnées d'un vrai col alpin) — voir `SAFE_LAT_RANGE`/
`SAFE_LON_RANGE` pour la zone fictive conventionnelle (Pacifique Sud, loin de toute
côte) que tout test GPS de ce dépôt doit utiliser.
"""

from __future__ import annotations

import re
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO))

from tests.lib.synthetic import FAKE_ACTIVITY_ID_BASE, build, sample_session  # noqa: E402


class TestNoRealisticGarminId(unittest.TestCase):
    def test_fit_samples_use_the_obviously_fake_id_range(self):
        """Même convention que `build()` : les ID Garmin réels (≈ 1,8-2,1 × 10¹⁰ en
        2025-2026) n'approchent jamais `FAKE_ACTIVITY_ID_BASE` (9 × 10¹⁰)."""
        with tempfile.TemporaryDirectory() as tmp:
            root = build(Path(tmp), days=6, sport="trail", seed=1, with_samples=True)
            files = list((root / "activities/fit").glob("*.json"))
            self.assertGreater(len(files), 0)
            import json
            for f in files:
                payload = json.loads(f.read_text(encoding="utf-8"))
                self.assertGreaterEqual(payload["activity_id"], FAKE_ACTIVITY_ID_BASE)


class TestNoGpsCoordinates(unittest.TestCase):
    def test_no_lat_lon_in_generated_records(self):
        """Pas de coordonnées GPS : ni domicile, ni lieu réel, ne peuvent y fuiter."""
        recs, _ = sample_session(seed=1, duration_s=30)
        for record in recs:
            self.assertNotIn("lat", record)
            self.assertNotIn("lon", record)


# ---------------------------------------------------------------------------
# #49 — aucune coordonnée GPS réelle dans les tests eux-mêmes
# ---------------------------------------------------------------------------

# Zone FICTIVE conventionnelle pour toute coordonnée de test de ce dépôt (#49, revue de
# code) : Pacifique Sud, largement au large de toute côte connue — assez vaste pour les
# petits décalages qu'un test applique autour d'un point de base (montées, quadrillage de
# bucketing), jamais assez pour ressembler à un lieu réellement enregistré.
SAFE_LAT_RANGE = (-46.0, -34.0)
SAFE_LON_RANGE = (-146.0, -124.0)

# Identifiants EXACTS reconnus comme une coordonnée (`\b...\b`, jamais une sous-chaîne :
# "plateau"/"PLATEAU_SPLIT_MAX_GRADE" (arc_climb.py) ou "escalate" contiennent la
# sous-chaîne "lat" sans être une coordonnée — une correspondance par sous-chaîne
# produirait des faux positifs sur ce dépôt précis). Couvre les conventions de nommage
# réellement utilisées ici : `arc_samples.py` (`lat_deg`/`lon_deg`), `arc_climb_match.py`
# (`start_lat`/`end_lat`/`summit_lat`, idem `lon`), FIT brut (`position_lat`/
# `position_long`), et les variables de conversion des tests eux-mêmes
# (`lat_semicircles`/`lon_semicircles`).
_LAT_NAMES = ("lat", "lat_deg", "start_lat", "end_lat", "summit_lat", "lat_semicircles", "position_lat")
_LON_NAMES = ("lon", "lon_deg", "start_lon", "end_lon", "summit_lon", "lon_semicircles", "position_long")

_NUMBER = r"-?\d+(?:\.\d+)?"


def _literal_assignment_pattern(names: tuple) -> "re.Pattern":
    """`identifiant [:=] littéral_numérique` (dict Python `"clé": valeur` OU affectation
    `nom = valeur`), `identifiant` matché en mot ENTIER — voir le commentaire de
    `_LAT_NAMES`/`_LON_NAMES`. `round(NUMBER ...)` (idiome de conversion semi-cercles →
    degrés utilisé par les tests de `arc_samples.py`) est reconnu explicitement en plus
    d'un littéral nu : sans quoi `lat_semicircles = round(-40.0 / 180.0 * ...)` échapperait
    à la détection."""
    alt = "|".join(re.escape(n) for n in names)
    return re.compile(rf"\b(?:{alt})\b\s*[:=]\s*(?:round\()?\s*({_NUMBER})")


_LAT_PATTERN = _literal_assignment_pattern(_LAT_NAMES)
_LON_PATTERN = _literal_assignment_pattern(_LON_NAMES)


class TestNoRealCoordinatesInTests(unittest.TestCase):
    """#49, revue de code : aucun test de ce dépôt ne doit utiliser une coordonnée GPS
    littérale hors de `SAFE_LAT_RANGE`/`SAFE_LON_RANGE` — même à titre d'exemple ou de
    fixture, une coordonnée réaliste pourrait être confondue avec un vrai lieu enregistré
    (domicile de l'auteur, parcours réel). Scan STATIQUE (regex sur le texte source, jamais
    une exécution) : précis sur les conventions de nommage réellement utilisées par ce
    dépôt (voir `_LAT_NAMES`/`_LON_NAMES`), volontairement SANS prétention à analyser une
    expression Python arbitraire (un faux négatif sur une coordonnée calculée de façon
    inhabituelle reste possible ; un faux positif sur un identifiant sans rapport,
    lui, est ce que ce test évite en priorité — voir le commentaire de `_LAT_NAMES`)."""

    def test_no_out_of_range_coordinate_literal_in_any_test_file(self):
        offenders = []
        for path in sorted((REPO / "tests").rglob("*.py")):
            if path.name == Path(__file__).name:
                continue  # ce fichier cite lui-même la plage sûre dans ses commentaires
            lines = path.read_text(encoding="utf-8").splitlines()
            text = "\n".join(lines)
            for pattern, (lo, hi), axis in (
                (_LAT_PATTERN, SAFE_LAT_RANGE, "lat"), (_LON_PATTERN, SAFE_LON_RANGE, "lon"),
            ):
                for match in pattern.finditer(text):
                    value = float(match.group(1))
                    if lo <= value <= hi:
                        continue
                    line_no = text.count("\n", 0, match.start()) + 1
                    # `# coord-lint: ...` (revue de code #49) : échappatoire EXPLICITE et
                    # visible dans le diff, pour une valeur délibérément HORS PLAGE (ex. un
                    # test qui vérifie qu'une latitude de 150° — physiquement impossible —
                    # est bien rejetée) — jamais une vraie coordonnée de trace.
                    if "coord-lint:" in lines[line_no - 1]:
                        continue
                    offenders.append(f"{path.relative_to(REPO)}:{line_no}: {axis}={value} hors de "
                                     f"[{lo}, {hi}] ({match.group(0)!r})")
        self.assertEqual(offenders, [],
                         "coordonnée(s) hors de la zone fictive conventionnelle (voir "
                         "SAFE_LAT_RANGE/SAFE_LON_RANGE) :\n" + "\n".join(offenders))

    def test_the_pattern_itself_does_not_false_positive_on_known_non_coordinate_identifiers(self):
        """Garde-fou du lint lui-même (#49, revue de code) : des identifiants réels de ce
        dépôt qui CONTIENNENT la sous-chaîne « lat »/« lon » sans être des coordonnées ne
        doivent jamais déclencher — sinon le lint serait trop bruyant pour rester utile."""
        safe_snippets = [
            "PLATEAU_SPLIT_MAX_GRADE = 0.02",
            "plateau_split_max_grade: float = 0.02",
            "def _split_flat_plateaus(a, b):",
            "translation_table = 1",
            "escalate_priority = 3",
            "isolation_level = 2",
        ]
        for snippet in safe_snippets:
            self.assertIsNone(_LAT_PATTERN.search(snippet), snippet)
            self.assertIsNone(_LON_PATTERN.search(snippet), snippet)

    def test_the_pattern_does_catch_a_real_looking_coordinate(self):
        """Contre-épreuve (#49, revue de code) : le motif DOIT repérer une coordonnée
        réelle typique (ex. les coordonnées d'un vrai lieu alpin utilisées avant ce
        correctif) — sans quoi le lint serait précis mais inutile."""
        snippet = "start_lat=46.0, start_lon=7.0"
        lat_match = _LAT_PATTERN.search(snippet)
        lon_match = _LON_PATTERN.search(snippet)
        self.assertIsNotNone(lat_match)
        self.assertIsNotNone(lon_match)
        self.assertFalse(SAFE_LAT_RANGE[0] <= float(lat_match.group(1)) <= SAFE_LAT_RANGE[1])
        self.assertFalse(SAFE_LON_RANGE[0] <= float(lon_match.group(1)) <= SAFE_LON_RANGE[1])


if __name__ == "__main__":
    unittest.main()
