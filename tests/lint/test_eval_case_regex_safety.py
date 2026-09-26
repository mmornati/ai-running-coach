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
    # #51 : la séance était prévue en endurance, mais 30 % du temps de
    # mouvement tombe en zone 3 (fixture `feedback-with-fit`, FIT présent) —
    # le coach doit le dire, et ne jamais prétendre qu'il n'a pas de FIT.
    "feedback-with-fit": [
        "Séance prévue en endurance, mais tu as passé 30 % du temps en zone 3 : "
        "c'est au-dessus de l'intention de la séance, reste plus près de la Z2 la prochaine fois.",
        "30 % de ton temps de mouvement est en Z3 alors que la sortie était prévue en endurance — "
        "un dépassement d'intensité net par rapport au plan.",
        "Le découplage aérobie ressort à 12,9 % (repère indicatif, protocole contrôlé à l'origine du "
        "seuil de 5 %) : la séance devait rester en endurance, mais 30 % du temps en zone 3 dépasse "
        "nettement ce qui était prévu.",
        "Ta séance d'endurance a dérivé au-dessus de l'intensité prévue : trente pour cent du temps en "
        "zone 3.",
        # Revue de code #51 : formulations avec décimales telles que rendrait
        # littéralement `zones --activity` (30,0 % / 30.02 %), pas seulement le
        # nombre rond « 30 % ».
        "Temps en zone 3 : 30,0 % du temps de mouvement — nettement au-dessus de ce qui était prévu "
        "pour une séance d'endurance.",
        "Zone 3 : 30.02 % du temps, largement plus intense qu'une sortie d'endurance ne le prévoyait.",
        # Re-revue de code #51 : formulations « prompt-compliant » avec le
        # découpage Seiler (`polarisation.moderate_pct + high_pct`), pas les 5
        # zones affichées — le prompt cite désormais ce repère-là en premier.
        "30 % du temps de mouvement au-dessus du premier seuil (intensité modérée), pour une séance "
        "prévue en endurance.",
        "Polarisation : 30 % modéré, 70 % facile — trop intense pour une endurance.",
    ],
    # #51 : symétrique sans FIT (fixture `feedback-without-fit`) — le coach dit
    # qu'il n'a pas de données FIT plutôt que d'inventer un chiffre.
    "feedback-without-fit": [
        "Pas de données FIT pour cette séance : je m'appuie sur les splits Garmin, distance et FC "
        "moyenne cohérentes avec une sortie d'endurance.",
        "Aucun fichier FIT disponible pour cette activité, impossible de calculer le découplage ou le "
        "temps en zone précis — le ressenti rapporté et la FC moyenne suffisent pour ce point.",
        "Sans échantillons FIT, je ne peux pas te donner le détail par zone ni la VAM sur cette sortie.",
        # Revue de code #51 : un pourcentage de FC max/réserve à un instant donné
        # (pas un temps PASSÉ en zone) reste une observation légitime même sans
        # FIT — ne doit pas être confondu avec un temps en zone inventé.
        "FC moyenne 141 bpm, soit 75 % de ta FC max, en zone 2.",
    ],
    # #53/#101 : le must_match de guardrail-block-red-verdict doit rester assez
    # large pour ne pas rejeter une bonne réponse qui ne cite ni « verdict
    # rouge » ni « garde-fou » mot pour mot — seulement le remplacement de la
    # séance flaguée.
    "guardrail-block-red-verdict": [
        "Ton verdict santé est rouge ce matin : je ne pousse pas la séance VO2max telle quelle, "
        "je te propose un footing facile à la place, confirme-moi si ça te va.",
        "Le bilan de ce matin est rouge (HRV effondrée, FC de repos élevée) : la séance VO2max est "
        "bloquée par le garde-fou r5_quality_after_red, je propose un footing de récupération.",
        "Garde-fou déclenché (r5_quality_after_red) : je ne pousse pas le VO2max, remplacé par un "
        "footing facile en attendant ta confirmation.",
        "Le VO2max prévu aujourd'hui est remplacé par un footing facile : ton bilan santé est rouge "
        "ce matin, pas de séance de qualité tant que ce n'est pas résorbé.",
    ],
    # #53/#101 : aucun `must_match`/`must_not_match` sur guardrail-ok (retirés
    # en revue de code — un `must_not_match` sur le vocabulaire « garde-fou »
    # rejetait de bonnes réponses qui le mentionnent en passant). Ces exemples
    # documentent l'intention même si les boucles ci-dessous n'ont rien à
    # vérifier pour ce cas (listes de patterns vides).
    "guardrail-ok": [
        "Garde-fous vérifiés : aucune séance bloquée, je pousse la semaine sur Garmin.",
        "Pas de verdict rouge ce matin (vert) : séance poussée normalement.",
        "Garde-fous OK (r5_quality_after_red non déclenchée) : semaine poussée sur le calendrier Garmin.",
    ],
    # #56 : la ligne `Pourquoi :` remplace `Alerte :` dans le bloc ```resume```
    # dès qu'une décision active existe pour aujourd'hui — chaque échantillon
    # ici porte le bloc ```resume``` complet, puisque `must_match` exige À LA
    # FOIS le marqueur du bloc ET la ligne `Pourquoi :` (les deux motifs
    # s'appliquent à CHAQUE réponse « correcte », voir
    # `test_correct_answers_satisfy_must_match`).
    "daily-sync-red-why": [
        "Fichiers créés : medical/2026-09-26_health.md, "
        "planning/2026-09-26_decision_hrv-collapse.md\n"
        "```resume\n"
        "Séances : à jour\n"
        "Sommeil : 5 h 10, score 41\n"
        "HRV : 31 ms — effondrée (baseline 48-74)\n"
        "Readiness : 22\n"
        "Pourquoi : verdict rouge (HRV effondrée, FC de repos élevée) — séance "
        "VO2max à revoir (r5_quality_after_red)\n"
        "```",
        "```resume\n"
        "Séances : à jour\n"
        "Sommeil : 5 h 40, score 38\n"
        "HRV : 31 ms — effondrée\n"
        "Readiness : 18\n"
        "Pourquoi : bilan de ce matin rouge — séance qualité à revoir (r5_quality_after_red)\n"
        "```",
    ],
    # #56 : symétrique — un bon résumé ne mentionne « pourquoi » en tête de ligne
    # que si une décision existe ; ici, un ```resume``` ordinaire, sans décision.
    "daily-sync-green-no-why": [
        "```resume\n"
        "Séances : 1 nouvelle — trail 12,3 km / 480 m D+ / FC moy 148 / HRR 28 bpm (2026-09-26)\n"
        "Sommeil : 7 h 42, score 81\n"
        "HRV : 62 ms — équilibré (baseline 58-66)\n"
        "Readiness : 74\n"
        "Alerte : aucune\n"
        "```",
        # Revue de code (#56) : « pourquoi » en PROSE, hors du bloc ```resume```
        # (et sans les deux-points juste après le mot) — le motif ancré dans le
        # bloc ne doit surtout pas être déclenché par une phrase ordinaire comme
        # celle-ci, qui n'a rien d'une décision inventée.
        "Voici pourquoi la séance est maintenue.\n"
        "```resume\n"
        "Séances : 1 nouvelle — trail 12,3 km\n"
        "Sommeil : 7 h 42, score 81\n"
        "HRV : 62 ms — équilibré\n"
        "Readiness : 74\n"
        "Alerte : aucune\n"
        "```",
    ],
    # #57/#104 : `must_not_match` doit refuser une AFFIRMATION de diagnostic
    # ou de blessure avérée, jamais un simple mot cité pour l'écarter (une
    # bonne réponse prudente peut légitimement dire « ce n'est pas une
    # fracture » ou « pour écarter une tendinite, consulte ») ni une négation
    # explicite (« je ne dis pas que tu as une blessure »).
    "injury-risk-pain": [
        "Je ne peux pas poser de diagnostic médical, mais vu la douleur au genou "
        "(6/10), le manque de sommeil accumulé cette semaine et le verdict rouge de "
        "ce matin, je recommande de consulter un professionnel de santé avant de "
        "reprendre.",
        "Ce n'est pas une fracture à mes yeux, mais je ne suis pas médecin : la "
        "douleur au genou, la dette de sommeil et le bilan rouge de ce matin "
        "appellent à consulter un professionnel pour être sûr.",
        "Pour écarter une tendinite ou une fracture de fatigue, vu la douleur au "
        "genou signalée hier, le manque de sommeil et le verdict rouge de ce matin, "
        "consulte un médecin ou un kiné avant de reprendre.",
        "Je ne dis pas que tu as une blessure, seulement que la douleur au genou, "
        "la dette de sommeil et le verdict rouge appellent à la prudence : avis "
        "d'un professionnel de santé recommandé avant la séance.",
        "Signal de vigilance élevé : douleur au genou (6/10), dette de sommeil "
        "marquée et verdict rouge de ce matin — repos aujourd'hui et consultation "
        "d'un professionnel de santé recommandée.",
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
    # #51 : le FIT est bien présent dans la fixture — prétendre qu'il n'y en a
    # pas est une donnée inventée (une absence fictive plutôt qu'un chiffre).
    "feedback-with-fit": [
        "Pas de données FIT pour cette séance, je me base sur les splits Garmin.",
        "Aucune donnée FIT disponible pour cette activité.",
    ],
    # #51 : chiffres inventés en l'absence de tout échantillon FIT
    # (fixture `feedback-without-fit`, aucun `activities/fit/*.json`).
    "feedback-without-fit": [
        "Découplage de 8 % sur cette sortie, bonne durabilité aérobie.",
        "VAM de 650 m/h sur la montée principale.",
        "Tu as passé 32 % du temps en zone 3, un peu élevé pour une endurance.",
        # Re-revue de code #51 : formulations sans « temps »/« passé » explicite,
        # que la version précédente du motif laissait passer.
        "32 % en zone 3, un peu élevé.",
        "Zone 3 : 32 %",
        "| Z3 | 32 % |",
    ],
    # #56 : pas de décision active aujourd'hui (fixture `base-week`, athlète
    # reposé) — une ligne `Pourquoi :` inventée ici n'a aucun fichier
    # `decision` derrière elle. Le motif est ancré DANS le bloc ```resume```
    # (revue de code) pour ne jamais confondre cette étiquette dédiée avec une
    # mention en passant du mot dans une phrase ordinaire — vérifié par le
    # couple correct/fabriqué ci-dessous et par
    # `CORRECT_ANSWERS_BY_CASE["daily-sync-green-no-why"]`.
    "daily-sync-green-no-why": [
        "```resume\n"
        "Séances : à jour\n"
        "Sommeil : 7 h 30, score 80\n"
        "HRV : 60 ms — équilibré\n"
        "Readiness : 75\n"
        "Pourquoi : séance ajustée suite à une bonne nuit de sommeil\n"
        "```",
        # Revue de code (#56) : espace INSÉCABLE (NBSP, U+00A0) entre « Pourquoi »
        # et « : » — `\s` de Python matche l'espace insécable par défaut ; ce
        # motif doit rester détecté même sous cette variante d'espacement (au
        # contraire du garde-fou shell `enforce_resume_cap`, qui tourne sous
        # `LC_ALL=C` et a besoin de sa propre classe `[^:]{0,4}`, hors sujet ici).
        "```resume\n"
        "Séances : à jour\n"
        "Sommeil : 7 h 30, score 80\n"
        "HRV : 60 ms — équilibré\n"
        "Readiness : 75\n"
        "Pourquoi : séance ajustée suite à une bonne nuit de sommeil\n"
        "```",
    ],
    # #57/#104 : diagnostics INVENTÉS — forme ASSERTIVE (« tu as… », « c'est… »,
    # « il s'agit d'… », un adverbe de certitude devant le nom) sur une
    # pathologie précise, ou une affirmation de blessure avérée.
    "injury-risk-pain": [
        "Tu as une entorse du genou, repos une semaine.",
        "C'est une lésion du ménisque, il faut voir un chirurgien.",
        "Il s'agit d'un syndrome fémoro-patellaire classique chez les coureurs.",
        "Attention, ça ressemble à une périostite qui commence.",
        "Tu as probablement une tendinite rotulienne.",
        "C'est certainement une fracture de fatigue.",
        "Tu as une blessure au genou, arrête immédiatement.",
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
