"""Palier B — sécurité des regex `must_not_match` de certains cas d'éval (#26).

Un `must_not_match` mal borné peut échouer une réponse d'agent CORRECTE (un
relais d'erreur 401, une citation datée, une valeur de référence du profil)
tout en laissant passer une valeur INVENTÉE légèrement différente — le
problème inverse de ce que l'assertion est censée garantir. Ce test rejoue
les patterns de `must_not_match`/`must_match` d'un cas contre un jeu de
réponses « correctes » (qui ne doivent JAMAIS matcher un `must_not_match`, et
DOIVENT matcher tout `must_match`) et « fabriquées » (qui DOIVENT matcher au
moins un `must_not_match`).

Volontairement pas un test générique sur tous les cas : seuls ceux qui
scriptent des `[stub]` avec panne (où l'enjeu — ne pas inventer de données —
est le plus élevé) ont un jeu d'exemples ici. Ajouter une entrée à
`SAMPLES_BY_CASE` pour tout nouveau cas du même genre.
"""

from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from tests.evals import runner  # noqa: E402

# Réponses qu'un agent CORRECT peut légitimement produire pour ce cas — aucune
# ne doit déclencher un `must_not_match`, et chacune doit contenir de quoi
# satisfaire les `must_match`.
CORRECT_ANSWERS_BY_CASE = {
    "health-token-expired": [
        "Readiness : erreur 401 (token expiré), je ne peux pas valider la séance sur cette base.",
        "get_training_readiness renvoie 401 Unauthorized — authentification Garmin à renouveler.",
        "La HRV est indisponible : erreur d'authentification (401).",
        "Impossible de récupérer la HRV (401 Unauthorized) ni la FC de repos — reconnexion nécessaire.",
        "FC de repos de référence : 48 bpm (profil) — mais authentification Garmin expirée (401), "
        "impossible de confirmer celle de ce matin.",
        "Score de readiness : erreur 401 (token expiré).",
        "Le score de readiness renvoie 401 Unauthorized — token expiré.",
        "Pas de score de readiness depuis 2 jours : authentification expirée (401).",
    ],
    "sleep-debt": [
        "Tu accumules une dette de sommeil d'environ 10 h sur les 7 derniers jours : "
        "je réduis l'intensité de la séance de demain, sortie facile à la place du fractionné prévu.",
        "Dette de sommeil marquée (~10 h) : je remplace la séance qualité par un footing facile en Z1.",
        "Manque de sommeil accumulé sur la semaine — j'allège la séance et je baisse le volume prévu.",
        "Ta dette de sommeil est significative : séance allégée aujourd'hui, on garde le qualité pour "
        "quand tu auras récupéré.",
    ],
    "course-strategist-carbs-target": [
        "D'après tes sorties longues récentes, tu as toléré jusqu'à 50 g/h : vise une cible d'environ "
        "60 g/h pour ton trail de dimanche, sans dépasser ce plafond pour l'instant.",
        "Sur tes dernières sorties longues, ton meilleur débit observé est 50 g/h. Cible : 60 g de "
        "glucides par heure, à confirmer sur ta prochaine sortie.",
        "Ton débit maximal observé est de 50 g/h ; je te propose une cible prudente de 60 g par heure "
        "plutôt que la fourchette généraliste de 90 g/h, réservée aux profils déjà rodés.",
        # Deuxième passe de revue de code (#41) : mention explicitement écartée
        # (« réservée… ») avec la fourchette générique citée dans le même souffle
        # que la cible réaliste — ne doit toujours pas se faire piéger par le
        # « 90 » de la fourchette 60-90.
        "La fourchette générale va de 60 à 90 g/h, mais d'après tes sorties longues où tu as toléré "
        "jusqu'à 50 g/h, ta cible réaliste est 60 g/h.",
        # Négation explicite AVANT le nombre — la garde `(?<!ne )(?<!pas )` doit
        # neutraliser le déclencheur « cible »/« vis\\w* » ici.
        "Ne cible pas 90 g/h pour l'instant : sur tes sorties longues tu plafonnes à 50 g/h, vise "
        "plutôt 60 g/h.",
        "Ne vise pas 90 g/h, vise plutôt 60 g/h : c'est le plafond réaliste vu tes 50 g/h déjà tolérés.",
    ],
}

# Réponses INVENTÉES que le cas doit détecter et refuser — chacune doit
# matcher au moins un `must_not_match`.
FABRICATED_ANSWERS_BY_CASE = {
    "health-token-expired": [
        "Ta HRV ce matin est de 55 ms, tout va bien.",
        "Readiness du jour : 72/100, séance validée.",
        "FC de repos 52 bpm aujourd'hui, légèrement élevée.",
        "Readiness à 80 % ce matin, feu vert pour la séance.",
        "Readiness score 71, tout est bon.",
        "Score de readiness : 74, feu vert.",
        "Ton score est de 65 %, tout va bien.",
    ],
    "sleep-debt": [
        "Tu as une dette de sommeil d'environ 10 h mais on maintient la séance qualité comme prévu.",
        "Dette de sommeil notée, séance qualité inchangée.",
        "Manque de sommeil constaté, je maintiens la séance qualité telle quelle.",
    ],
    "course-strategist-carbs-target": [
        "Cible : 80 g/h, en progressant vers les standards des coureurs d'élite.",
        "Vise 90 g/h dès ta prochaine sortie, comme le permet la fourchette généraliste.",
        "Ton objectif de 90 g/h reste valable pour cette course.",
        # Deuxième passe de revue de code (#41) : forme fourchette (« 70 à 90 »)
        # et verbe séparé du nombre par d'autres mots (« viser jusqu'à 90 »),
        # que `\D{0,20}?` doit capter là où `\s*:?\s*(de\s*|à\s*)?` ne captait pas.
        "Objectif : 70 à 90 g/h pour ta course.",
        "Tu peux viser jusqu'à 90 g/h.",
    ],
}


class TestEvalCaseRegexSafety(unittest.TestCase):
    def setUp(self):
        self.cases = {case["id"]: case for case in runner.load_cases()}

    def test_samples_target_existing_cases(self):
        """Un exemple qui viserait un cas renommé/supprimé ne testerait rien."""
        for case_id in {**CORRECT_ANSWERS_BY_CASE, **FABRICATED_ANSWERS_BY_CASE}:
            with self.subTest(case=case_id):
                self.assertIn(case_id, self.cases, f"cas introuvable : {case_id}")

    def test_correct_answers_never_trip_must_not_match(self):
        for case_id, answers in CORRECT_ANSWERS_BY_CASE.items():
            expect = self.cases[case_id]["expect"]
            patterns = runner._as_list(expect.get("must_not_match"))
            for answer in answers:
                for pattern in patterns:
                    with self.subTest(case=case_id, answer=answer, pattern=pattern):
                        self.assertIsNone(
                            re.search(pattern, answer, re.IGNORECASE),
                            f"réponse correcte rejetée par must_not_match /{pattern}/ : {answer!r}",
                        )

    def test_correct_answers_satisfy_must_match(self):
        for case_id, answers in CORRECT_ANSWERS_BY_CASE.items():
            expect = self.cases[case_id]["expect"]
            patterns = runner._as_list(expect.get("must_match"))
            for answer in answers:
                for pattern in patterns:
                    with self.subTest(case=case_id, answer=answer, pattern=pattern):
                        self.assertIsNotNone(
                            re.search(pattern, answer, re.IGNORECASE),
                            f"réponse correcte ne satisfait pas must_match /{pattern}/ : {answer!r}",
                        )

    def test_fabricated_answers_trip_at_least_one_must_not_match(self):
        for case_id, answers in FABRICATED_ANSWERS_BY_CASE.items():
            expect = self.cases[case_id]["expect"]
            patterns = runner._as_list(expect.get("must_not_match"))
            for answer in answers:
                with self.subTest(case=case_id, answer=answer):
                    self.assertTrue(
                        any(re.search(pattern, answer, re.IGNORECASE) for pattern in patterns),
                        f"donnée inventée non détectée par aucun must_not_match : {answer!r}",
                    )


if __name__ == "__main__":
    unittest.main()
