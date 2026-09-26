#!/usr/bin/env python3
"""Moteur de garde-fous déterministe (#52, épopée #22).

Contexte (issue #52) : la progression d'entraînement est aujourd'hui confiée au
LLM. Principale critique adressée aux coachs IA : une progression trop agressive
(des blessures ont été rapportées avec des outils comparables comme Runna).
Ce module fournit un second avis PUREMENT calculé, déterministe et testable,
que l'agent `coach` doit consulter avant d'écrire une semaine et avant de la
pousser au calendrier Garmin (câblage : #53, hors périmètre de ce module).

Deux fonctions, deux régimes :
- `build_context(...)` — LIT l'index dérivé (`scripts/arc_index.py`) : charge
  passée réelle, semaine(s) précédente(s), dernier verdict santé, objectif
  actif. Impure (ouvre la base SQLite), jamais appelée par les tests unitaires.
- `evaluate(proposed_week, context, config)` — PURE, stdlib seule, déterministe.
  Prend la semaine proposée (dict du bloc ```arc `kind: "week"``), le contexte
  ci-dessus et la configuration résolue (`guardrail_settings`), rend le
  verdict. C'est la fonction couverte par les tests du palier D (un cas par
  règle, juste sous/juste au-dessus du seuil).

Règles (id stable, sévérité configurable `info` | `warn` | `block`, seuils
dans `[guardrails]` de `config/workspace.toml`) :

| id | ce qu'elle vérifie | sévérité par défaut |
|---|---|---|
| `r1_acwr_projected` | ACWR (charge aiguë/chronique) PROJETÉ, maximum sur la semaine proposée | `warn` |
| `r2_weekly_volume_jump` | hausse de la durée (+ distance en `road`) hebdomadaire | `warn` |
| `r3_weekly_elevation_jump` | hausse du D+ hebdomadaire (trail seulement) | `warn` |
| `r4_monotony_projected` | monotonie de Foster PROJETÉE sur la semaine proposée | `warn` |
| `r5_quality_after_red` | séance de qualité le jour même ou le lendemain d'un verdict santé rouge | `block` |
| `r6_long_run_share` | part de la plus longue sortie dans le volume hebdomadaire | `warn` |
| `r7_consecutive_quality` | deux séances de qualité sur deux jours consécutifs | `warn` |

Toutes les règles qui ont besoin d'historique rendent `skipped_rules` avec
`reason_code: "insufficient_history"` plutôt que de bloquer sur un calcul
bruité (première semaine d'un nouveau workspace, ACWR non significatif tant
que `arc_metrics.ACWR_MIN_FITNESS` n'est pas atteint…). La semaine de course
(objectif actif, `race_date` dans les 7 jours de `week_start`) désactive les
règles de charge (R1-R4, R6-R7) : voir `ASSUMPTIONS["race_week"]`.

Sortie JSON (consommée par #53 pour le câblage agent, #54 pour le futur bloc
`decision.rule_ids`, #57 pour le drapeau composite de risque de blessure) :

```json
{
  "ok": true,
  "violations": [
    {"rule_id": "r1_acwr_projected", "severity": "warn",
     "message": "ACWR projeté 1.42, au-delà de 1.3.", "message_en": "...",
     "values": {"observed": 1.42, "threshold": 1.3},
     "session_dates": ["2026-09-24"], "source": "..."}
  ],
  "checked_rules": ["r1_acwr_projected", "..."],
  "skipped_rules": [{"rule_id": "r3_weekly_elevation_jump",
                      "reason_code": "not_applicable_sport",
                      "reason": "R3 ne s'applique qu'en trail ([sport].primary)."}],
  "context": {"week_start": "2026-09-21", "is_race_week": false, "...": "..."}
}
```

CLI, DEUX usages (agents en headless, avant écriture ET sur fichier déjà écrit) :

```bash
python3 scripts/arc_guardrails.py check --week planning/2026-09-21_semaine.md
python3 scripts/arc_guardrails.py check --week -              # stdin (JSON ou markdown ```arc)
echo '{"week_start": "...", "sessions": [...]}' | python3 scripts/arc_guardrails.py check --week -
python3 scripts/arc_guardrails.py check --week /tmp/proposed.json --workspace . --today 2026-09-20
```

Choix : script DÉDIÉ plutôt qu'une sous-commande de `arc_index.py` (déjà
2300+ lignes, focalisé sur l'indexation et les métriques dérivées). Les
garde-fous sont un CONSOMMATEUR de l'index (comme le sont déjà les agents),
pas une nouvelle table ni un nouveau calcul dérivé à réindexer — un module à
part, qui importe `arc_index`/`arc_metrics`, garde cette frontière nette et
évite d'alourdir encore `arc_index.py`. Le sous-schéma `check` (plutôt qu'un
verbe unique) laisse la porte ouverte à une future sous-commande sans
rétrocompatibilité à casser (ex. une commande d'explication des seuils actifs).

Bibliothèque standard uniquement (CONTRIBUTING.md).
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))

import arc_contract as C  # noqa: E402
import arc_index as I  # noqa: E402
import arc_metrics as M  # noqa: E402
from coach_config import ConfigError  # noqa: E402
from coach_setup import workspace_root  # noqa: E402

# ---------------------------------------------------------------------------
# Règles, seuils par défaut, sévérités
# ---------------------------------------------------------------------------

SEVERITIES = ("info", "warn", "block")

# Seuils par défaut — documentés à nouveau, avec la même valeur, dans
# `config/workspace.toml` sous `[guardrails]` (source de vérité pour un
# utilisateur du workspace ; ces constantes sont le filet de sécurité quand la
# section est absente du workspace, comme partout ailleurs dans le moteur —
# voir `arc_index.py::_heat_threshold_c` pour la même discipline).
DEFAULT_ACWR_MAX = 1.3
DEFAULT_VOLUME_INCREASE_MAX_PCT = 10.0
# Défaut "mean4" (pas "previous_week") depuis la revue de code #98, blocker 8 :
# comparer à la seule semaine précédente déclenche une fausse alerte à +100 %
# après une semaine de récupération (deload) suivie d'un retour à la normale —
# la moyenne des 4 dernières semaines lisse ce genre d'à-coup. Encore
# configurable en "previous_week" pour qui préfère la sensibilité immédiate.
DEFAULT_VOLUME_REFERENCE = "mean4"       # "previous_week" | "mean4"
DEFAULT_ELEVATION_INCREASE_MAX_PCT = 10.0
DEFAULT_MONOTONY_MAX = 2.0
DEFAULT_LONG_RUN_SHARE_MAX_PCT = 35.0
# Nombre minimal de séances de la famille course à pied dans la semaine avant
# que R6 (part de la plus longue sortie) soit un repère fiable — voir revue de
# code #98, should-fix 9 : sous ce seuil (ex. 3 séances 60/60/120 min), la plus
# longue séance dépasse presque toujours 35 % par construction (peu de séances
# parmi lesquelles se répartir), sans que ce soit un signal de charge excessive.
R6_MIN_SESSIONS = 4
# Fenêtre de calcul de l'allure course RÉCENTE (voir `_recent_run_pace_s_km`,
# ASSUMPTIONS["distance_only_estimate"]) : les 90 jours qui précèdent
# `week_start`, jamais tout l'historique (une allure d'il y a deux ans ne
# reflète pas la forme actuelle).
RECENT_PACE_WINDOW_DAYS = 90
# Historique réel minimal (en jours, écart entre la plus ancienne charge
# indexée et `week_start`) avant qu'une projection ACWR/monotonie (R1/R4) soit
# considérée fiable — voir revue de code #98, blocker 1, et
# ASSUMPTIONS["acwr_projection"]. `arc_metrics.daily_series` initialise la
# condition (moyenne mobile exponentielle 42 j) à ZÉRO au premier jour connu :
# avec moins de deux fois cette fenêtre d'historique réel, la condition reste
# artificiellement sous-estimée par ce démarrage à froid et l'ACWR (fatigue /
# condition) se retrouve mécaniquement gonflé, QUELLE QUE SOIT la semaine
# proposée — un nouvel utilisateur avec seulement 1 à 8 semaines d'historique
# lirait un ACWR de 3,18 à 1,34 sur une semaine pourtant parfaitement stable.
MIN_HISTORY_DAYS_FOR_PROJECTION = 2 * M.FITNESS_DAYS   # 84 jours

DEFAULT_SEVERITY: Dict[str, str] = {
    # R1 passé de "block" à "warn" en revue de code #98 (should-fix 7) : les
    # seuils de Gabbett viennent de sports collectifs avec des moyennes
    # glissantes 7/28 j, pas du modèle impulsion-réponse de Banister (7/42 j)
    # évalué en fin de semaine que ce moteur utilise — voir
    # ASSUMPTIONS["acwr_projection"] pour le détail des réserves scientifiques.
    # Un utilisateur qui veut la fermeté d'un blocage peut le remettre à
    # "block" via `[guardrails].severity_r1_acwr_projected`.
    "r1_acwr_projected": "warn",
    "r2_weekly_volume_jump": "warn",
    "r3_weekly_elevation_jump": "warn",
    "r4_monotony_projected": "warn",
    "r5_quality_after_red": "block",
    "r6_long_run_share": "warn",
    "r7_consecutive_quality": "warn",
}
RULE_IDS: Tuple[str, ...] = tuple(sorted(DEFAULT_SEVERITY))

# Statuts de séance qui sortent une séance du calcul (charge, volume, D+,
# sortie longue, qualité consécutive…) — voir AGENTS.md « cas limites » de
# l'issue #52. `rest` est exclu séparément (sport/intensité "rest", jamais un
# statut). `missed` ajouté en revue de code #98 (should-fix 4) : une séance
# déjà constatée manquée ne doit pas peser comme si elle allait avoir lieu,
# exactement comme `cancelled`/`moved` — le contrat n'a pas de motif distinct.
_EXCLUDED_STATUSES = ("cancelled", "moved", "missed")


def _is_excluded(session: dict) -> bool:
    """Une séance annulée, déplacée, manquée ou de repos ne compte dans AUCUNE
    règle de charge/volume/qualité — voir `ASSUMPTIONS["excluded_sessions"]`."""
    return session.get("status") in _EXCLUDED_STATUSES or session.get("sport") == "rest" \
        or session.get("intensity") == "rest"


def _is_quality(session: dict) -> bool:
    return session.get("intensity") in M.QUALITY_INTENSITIES


# Charge PROJETÉE d'une séance planifiée (R1/R4) : voir ASSUMPTIONS["projected_load"].
INTENSITY_RPE: Dict[str, float] = {
    "rest": 0, "recovery": 3, "endurance": 4, "tempo": 6, "threshold": 7,
    "vo2max": 9, "race": 10, "strength": M.DEFAULT_RPE["strength"],
}
INTENSITY_RPE_DEFAULT = 5.0     # intensité absente/inconnue : milieu d'échelle, ni facile ni dur


def _effective_planned_duration_s(session: dict, recent_pace_s_km: Optional[float]) -> Tuple[Optional[float], bool]:
    """Durée planifiée EFFECTIVE d'une séance : `planned_duration_s` si renseignée
    (rendue TELLE QUELLE, jamais estimée), sinon ESTIMÉE depuis `planned_distance_m`
    (+ équivalence D+ plat, `arc_metrics.TRAIL_FLAT_M_PER_M_DPLUS`) à l'allure course
    RÉCENTE de l'athlète (`recent_pace_s_km`, voir `_recent_run_pace_s_km` et
    `ASSUMPTIONS["distance_only_estimate"]`) — revue de code #98, blocker 3.

    Rend `(durée_s, estimée)`. `(None, False)` si ni la durée ni la distance ne sont
    renseignées, OU si la distance est renseignée mais qu'aucune allure récente
    n'est disponible pour l'estimer (jamais une estimation inventée sans donnée)."""
    duration_s = session.get("planned_duration_s")
    if duration_s:
        return duration_s, False
    distance_m = session.get("planned_distance_m")
    if not distance_m or not recent_pace_s_km:
        return None, False
    elevation_m = session.get("planned_elevation_m") or 0.0
    flat_equivalent_m = distance_m + elevation_m * M.TRAIL_FLAT_M_PER_M_DPLUS
    return (flat_equivalent_m / 1000.0) * recent_pace_s_km, True


def projected_session_load(session: dict, recent_pace_s_km: Optional[float] = None) -> float:
    """Charge PROJETÉE d'une séance planifiée, sur la MÊME échelle que
    `arc_metrics.session_load` (TRIMP/sRPE) — voir `ASSUMPTIONS["projected_load"]`
    pour la justification complète. Rend 0.0 pour une séance sans durée planifiée
    NI durée estimable (jamais une charge inventée depuis rien) ou explicitement
    exclue (voir `_is_excluded`)."""
    if _is_excluded(session):
        return 0.0
    duration_s, _estimated = _effective_planned_duration_s(session, recent_pace_s_km)
    if not duration_s:
        return 0.0
    rpe = INTENSITY_RPE.get(session.get("intensity"), INTENSITY_RPE_DEFAULT)
    return (duration_s / 60.0) * rpe * M.RPE_TO_TRIMP


ASSUMPTIONS: Dict[str, str] = {
    "projected_load": (
        "Charge d'une séance PLANIFIÉE (sans FC, donc sans TRIMP réel possible, "
        "arc_metrics.trimp_banister) : (minutes planifiées × RPE attendu selon "
        "l'intensité prescrite) × arc_metrics.RPE_TO_TRIMP — EXACTEMENT la même "
        "formule que arc_metrics.session_load pour une séance réelle sans FC "
        "(repli session-RPE de Foster), pour rester sur la même échelle et pouvoir "
        "mélanger charge réelle indexée et charge projetée dans arc_metrics.daily_series. "
        "Le RPE attendu par intensité (INTENSITY_RPE) est une approximation MAISON, "
        "calibrée pour rester cohérente avec arc_metrics.DEFAULT_RPE (renforcement : "
        "même valeur, 5) plutôt que tirée d'une source publiée — c'est une "
        "approximation du projet, jamais présentée comme mesurée."
    ),
    "acwr_projection": (
        "R1 : la charge réelle déjà indexée (table `activity`, sommée par jour si "
        "plusieurs séances) alimente arc_metrics.daily_series depuis la date de la "
        "plus ancienne activité connue jusqu'au dernier jour de la semaine proposée "
        "(dimanche). Pour les jours DE LA SEMAINE PROPOSÉE : chaque séance non "
        "exclue est appariée à une activité réelle (arc_metrics._resolve_sessions, "
        "même logique que arc_metrics.week_compliance — statut `done` explicite, ou "
        "appariement automatique date+sport/famille) et compte sa charge RÉELLE si "
        "appariée ; sinon, un jour STRICTEMENT AVANT `context['today']` compte 0 "
        "(jamais le bénéfice d'une charge qui n'a peut-être jamais eu lieu, revue "
        "de code #98, blocker/should-fix 5), et un jour à `today` ou après compte la "
        "charge PROJETÉE (`projected_session_load`). Plusieurs séances le même jour "
        "sont SOMMÉES (revue de code #98, blocker 2 : jamais la charge agrégée déjà "
        "indexée écrasée par une seule séance restante). "
        "`acwr_projected` = MAXIMUM de l'ACWR sur les 7 jours de la semaine proposée "
        "(`_max_week_acwr`, revue de code #98, should-fix 7 — pas seulement le "
        "dimanche : sinon une semaine régulière avec une longue sortie le dimanche "
        "se lit artificiellement autour de 1,12 du seul fait du jour d'évaluation, un "
        "biais de motif hebdomadaire indépendant de la charge réelle). La monotonie/"
        "condition/fatigue PROJETÉES restent la valeur du DERNIER jour (dimanche) — "
        "voir ASSUMPTIONS['monotony_projection']. `acwr_baseline` (scénario « repos "
        "complet » cette semaine-là, `zero_proposed=True`) : R1 ne bloque QUE si la "
        "semaine proposée AGGRAVE le ratio par rapport à ce scénario — voir "
        "ASSUMPTIONS['race_week'] (should-fix 6). "
        "Historique minimal : `MIN_HISTORY_DAYS_FOR_PROJECTION` (84 j, 2× "
        "`arc_metrics.FITNESS_DAYS`) — `arc_metrics.daily_series` initialise la "
        "condition (moyenne mobile exponentielle 42 j) à ZÉRO au premier jour connu ; "
        "avec moins de deux fois cette fenêtre, la condition reste sous-estimée par "
        "ce démarrage à froid et l'ACWR se retrouve mécaniquement gonflé quelle que "
        "soit la semaine proposée (revue de code #98, blocker 1, repro : 3,18 à 1,34 "
        "d'ACWR sur une semaine identique et parfaitement stable, selon que "
        "l'historique compte 1 ou 8 semaines) — sous ce seuil, R1/R4 sont SAUTÉES "
        "avec `reason_code: \"insufficient_history\"`, jamais évaluées sur un "
        "démarrage à froid. "
        "Repère indicatif de la littérature sur le ratio de charge aiguë/chronique "
        "(« acute:chronic workload ratio »), pas un seuil de blessure prouvé : "
        "Gabbett T.J. (2016), « The training-injury prevention paradox: should "
        "athletes be training smarter and harder? », British Journal of Sports "
        "Medicine, 50(5), 273-280 — la zone 0,8-1,3 y est documentée comme associée "
        "à un risque de blessure plus faible qu'au-delà de 1,5 ; c'est aussi le "
        "repère déjà partagé par `arc_metrics.ACWR_SAFE` dans ce projet. RÉSERVES "
        "SCIENTIFIQUES IMPORTANTES (revue de code #98, should-fix 7), en plus du "
        "biais de motif hebdomadaire ci-dessus : (1) les seuils de Gabbett viennent "
        "d'études en SPORTS COLLECTIFS (rugby, football australien), avec des "
        "moyennes glissantes SIMPLES sur 7 j (aigu) et 28 j (chronique) — ce moteur "
        "utilise le modèle impulsion-réponse de Banister (moyennes mobiles "
        "EXPONENTIELLES 7 j/42 j), une définition mathématiquement DIFFÉRENTE de "
        "l'ACWR, jamais validée par les mêmes études ; (2) la preuve elle-même est "
        "CONTESTÉE dans la littérature de course à pied — voir Impellizzeri F.M. "
        "et al. (2020), citée dans `docs/marques.md` (« ACWR : la zone 0,8-1,3 est "
        "un repère indicatif [...] discuté dans la littérature »). C'est pourquoi "
        "R1 est `warn` par défaut (pas `block`, voir DEFAULT_SEVERITY) — configurable "
        "en `block` par qui veut la fermeté. `resources/` ne contient pas ces "
        "références (dossier propre au workspace de l'utilisateur, hors du dépôt "
        "public) : citées ici depuis la littérature, comme le fait déjà "
        "`arc_metrics.ASSUMPTIONS`."
    ),
    "distance_only_estimate": (
        "Séance planifiée en DISTANCE seule (`planned_distance_m`, sans "
        "`planned_duration_s`) : revue de code #98, blocker 3 — une telle séance ne "
        "doit jamais compter une charge/durée de ZÉRO (elle a bien une charge "
        "réelle, seulement pas encore chiffrée en temps). Durée ESTIMÉE = "
        "(distance_m + élévation_m × arc_metrics.TRAIL_FLAT_M_PER_M_DPLUS) / 1000 × "
        "allure course RÉCENTE (médiane, s/km, familles course à pied, "
        "`_recent_run_pace_s_km`, fenêtre `RECENT_PACE_WINDOW_DAYS` = 90 j avant "
        "`week_start`) — la même équivalence D+/plat que "
        "`arc_metrics.ASSUMPTIONS['trail_equivalence']`, réutilisée pour rester "
        "cohérente avec le reste du projet. Une APPROXIMATION D'UNE APPROXIMATION "
        "(l'allure récente n'est pas l'allure de CETTE séance), signalée "
        "explicitement dans `context['distance_only_sessions_estimated']` (dates). "
        "Aucune activité de la famille course avec durée ET distance sur la fenêtre "
        "récente : `recent_run_pace_s_km` est `None`, et toute séance de la famille "
        "course prescrite en distance seule rend alors R1/R2/R4 SAUTÉES avec "
        "`reason_code: \"missing_planned_duration\"` — jamais un 0 silencieux, "
        "jamais une estimation inventée sans donnée. R3 (D+) et R6 (part de la "
        "sortie la plus longue) restent traitées séparément — R3 utilise "
        "`planned_elevation_m` directement (aucune durée en jeu), R6 utilise cette "
        "même estimation (voir ASSUMPTIONS['long_run_share'])."
    ),
    "volume_and_elevation": (
        "R2/R3 : comparaison au choix (`[guardrails].r2_volume_reference`) à la "
        "semaine PRÉCÉDENTE (les 7 jours immédiatement avant week_start) ou à la "
        "MOYENNE des 4 semaines précédentes (`\"mean4\"`, DÉFAUT depuis la revue de "
        "code #98, should-fix 8 : comparer à la seule semaine précédente déclenche "
        "une fausse alerte à +100 % après une semaine de récupération suivie d'un "
        "retour à la normale — la moyenne 4 semaines lisse cet à-coup) — seule la "
        "famille course à pied (arc_metrics.sport_family == \"run\" : course, "
        "trail, randonnée, marche) compte, jamais le vélo/renforcement/natation "
        "d'une semaine multi-sport (cohérent avec `arc_metrics.GEAR_WEAR_SPORTS`/"
        "`FUELING_SPORTS`, mêmes raisons) — `_run_family_totals.has_any_activity` "
        "ne compte QUE cette famille (revue de code #98, should-fix 10 : une "
        "semaine 100 % vélo n'est PAS une référence valide, même si `activity` a "
        "bien des lignes ce jour-là). R2 compare la durée planifiée totale "
        "(toujours, durée EFFECTIVE — voir ASSUMPTIONS['distance_only_estimate']) "
        "et la distance planifiée totale (seulement si [sport].primary == \"road\" "
        ": le D+ n'a pas de sens sur route). R3 compare le D+ planifié total, "
        "seulement si [sport].primary == \"trail\". Référence sans AUCUNE activité "
        "de la famille course sur la fenêtre : la règle est SAUTÉE avec "
        "`reason_code: \"no_reference\"` (distinct de `\"insufficient_history\"`, "
        "réservé à R1/R4/R6 : ici, il existe peut-être un historique, juste pas de "
        "la bonne famille), jamais un pourcentage infini ou une division par zéro. "
        "Séance(s) prescrite(s) en distance sans allure récente pour estimer la "
        "durée : R2 est SAUTÉE avec `reason_code: \"missing_planned_duration\"` "
        "(voir ASSUMPTIONS['distance_only_estimate']). Seule une HAUSSE déclenche "
        "la règle : une semaine de récupération (deload) ou d'affûtage, qui réduit "
        "le volume, ne peut jamais être signalée par R2/R3 (le calcul du "
        "pourcentage de variation n'est comparé au seuil que s'il est strictement "
        "positif). « Règle des 10 % » : convention très répandue dans le coaching "
        "course à pied (programmes pour débutants, littérature grand public), "
        "jamais validée par un essai contrôlé dédié à ma connaissance — traitée ici "
        "comme une APPROXIMATION DU PROJET, pas une référence bibliographique "
        "vérifiée, contrairement à R1/R4."
    ),
    "monotony_projection": (
        "R4 : monotonie de Foster PROJETÉE, même série que R1 (arc_metrics."
        "daily_series), valeur du dernier jour (dimanche) de la semaine proposée — "
        "moyenne / écart-type de la charge quotidienne sur les 7 jours qui "
        "coïncident exactement avec la semaine proposée (voir ASSUMPTIONS"
        "[\"acwr_projection\"]). `None` si la fenêtre glissante ne couvre pas "
        "encore 7 jours d'historique (workspace trop jeune) OU si l'écart-type est "
        "nul (charge quotidienne identique tous les jours, y compris tout à zéro) "
        "— dans les deux cas, `reason_code: \"insufficient_history\"`, jamais un "
        "seuil évalué sur une valeur non significative. Comme R1 (voir "
        "ASSUMPTIONS['acwr_projection']), R4 est aussi SAUTÉE sous "
        "`MIN_HISTORY_DAYS_FOR_PROJECTION` (84 j) — par la même discipline de "
        "prudence, même si la fenêtre glissante de la monotonie (7 j de charge "
        "brute, pas une moyenne mobile exponentielle) n'a pas le même biais de "
        "démarrage à froid que l'ACWR. Source : Foster C. (1998), "
        "« Monitoring training in athletes with reference to overtraining "
        "syndrome », Medicine & Science in Sports & Exercise, 30(7), 1164-1168 — "
        "seuil de 2,0 couramment cité dans la littérature sur le monitoring de "
        "charge comme repère associé à un risque accru (surcharge/monotonie "
        "d'entraînement), pas une valeur validée sur CE workspace. Même remarque "
        "que R1 sur `resources/` (dossier privé de l'utilisateur, hors dépôt)."
    ),
    "quality_after_red": (
        "R5 : séance de qualité (arc_metrics.QUALITY_INTENSITIES) le JOUR MÊME "
        "d'un verdict santé rouge, ou le LENDEMAIN d'un verdict rouge — le verdict "
        "est celui déjà persisté dans `medical/*_health.md` (`health.verdict`), "
        "jamais recalculé ici. Respecte `[health].morning_check` — voir AGENTS.md, "
        "« une séance annulée pour raison médicale reste annulée quel que soit le "
        "ton » : à `off`, AUCUNE donnée de santé n'est récupérée par construction, "
        "la règle est donc explicitement SAUTÉE avec `reason_code: "
        "\"health_check_disabled\"` plutôt que de dépendre d'un fichier santé "
        "fantôme laissé par un ancien réglage. À `minimal`, le verdict persisté "
        "peut ne refléter QUE la readiness (pas de HRV/FC de repos à ce niveau, "
        "voir `arc_metrics.ASSUMPTIONS[\"hrv_baseline\"]`) — la règle utilise ce "
        "verdict TEL QUEL, quelle que soit sa base de calcul : elle ne recalcule "
        "jamais un verdict, elle consulte celui que l'agent a posé le jour même. "
        "À `full`, le verdict reflète le triptyque complet. Aucune activation en "
        "l'absence de verdict connu pour la date concernée (jamais un rouge "
        "supposé par défaut). Semaine de course : voir ASSUMPTIONS[\"race_week\"] "
        "— R5 reste ACTIVE même en semaine de course (une alerte santé reste "
        "pertinente juste avant une course), contrairement à R1-R4/R6-R7."
    ),
    "long_run_share": (
        "R6 : part de la plus longue sortie planifiée (famille course à pied) "
        "dans le volume hebdomadaire planifié TOTAL de cette même famille "
        "(durée EFFECTIVE, estimée depuis la distance si besoin — voir "
        "ASSUMPTIONS['distance_only_estimate']). Séances annulées/déplacées/"
        "manquées/repos exclues des deux termes. Aucune sortie de la famille "
        "course cette semaine, ou volume total nul : `reason_code: "
        "\"insufficient_history\"` (rien à comparer). MOINS de `R6_MIN_SESSIONS` "
        "(4) séances de la famille course cette semaine : `reason_code: "
        "\"too_few_sessions\"` (revue de code #98, should-fix 9 — avec 3 séances "
        "ou moins, ex. 60/60/120 min, la plus longue dépasse presque toujours "
        "35 % par pure construction arithmétique, jamais un signal de charge "
        "excessive). Plus longue sortie sans durée NI distance+allure estimable : "
        "`reason_code: \"missing_planned_duration\"` plutôt qu'un partage "
        "silencieusement sous-estimé. Part plafonnée à 100 % par construction "
        "(le maximum d'un sous-ensemble ne peut pas dépasser la somme ; garde "
        "défensive contre l'imprécision flottante, revue de code #98, "
        "should-fix 12). Seuil par défaut 35 % : convention du projet (repère "
        "courant en coaching course à pied selon lequel une seule sortie ne "
        "devrait pas dominer la semaine, popularisé sous des formes voisines — "
        "ex. « pas plus de 25-30 % du volume hebdomadaire » — sans source unique, "
        "vérifiable et consensuelle identifiée), pas une valeur tirée d'un essai "
        "contrôlé publié."
    ),
    "consecutive_quality": (
        "R7 : deux séances de qualité (arc_metrics.QUALITY_INTENSITIES) le MÊME "
        "jour, ou sur deux jours consécutifs (écart d'exactement 1 jour), séances "
        "annulées/déplacées/manquées exclues. Principe de l'entraînement polarisé "
        "(alterner franchement facile et difficile, jamais du difficile deux "
        "jours de suite sans jour plus facile entre les deux) documenté par "
        "Seiler S. & Kjerland G.Ø. (2006), « Quantifying training intensity "
        "distribution in elite endurance athletes: is there evidence for an "
        "\"optimal\" distribution? », Scandinavian Journal of Medicine & Science "
        "in Sports, 16(1), 49-56 — déjà cité par `arc_metrics.HR_ZONE_SEILER_PCT_"
        "MAX` pour la polarisation 80/20. Le seuil précis « jamais deux jours "
        "consécutifs » (plutôt qu'un espacement plus long) reste une "
        "APPROXIMATION DU PROJET : Seiler documente une distribution d'intensité "
        "globale, pas une règle d'espacement jour par jour. LIMITES ASSUMÉES "
        "(revue de code #98, nit) : (1) ne regarde QUE les séances de la semaine "
        "PROPOSÉE — une séance de qualité le dimanche de la semaine PRÉCÉDENTE "
        "déjà persistée, suivie d'une séance de qualité le lundi proposé, n'est "
        "PAS détectée (`build_context` ne fournit pas la semaine précédente déjà "
        "écrite, hors périmètre de #52, raffinable par #53 qui a accès au fichier "
        "précédent) ; (2) deux séances de qualité LE MÊME JOUR SONT détectées "
        "depuis la revue de code #98 (comptage par date, pas seulement l'écart "
        "entre dates distinctes)."
    ),
    "race_week": (
        "Semaine de course : `race_date` de l'objectif actif (`planning/"
        "active_objective.md`, table `objective`) tombe dans les 7 jours de "
        "`week_start` à `week_start + 6` inclus. Dans ce cas, R1/R2/R3/R4/R6/R7 "
        "sont SAUTÉES avec `reason_code: \"race_week\"` — l'objectif de #52 est "
        "d'éviter une progression trop agressive à l'entraînement, jamais de "
        "bloquer la course elle-même (volume/D+/intensité d'une course dépassent "
        "presque toujours les repères hebdomadaires habituels par construction). "
        "R5 reste active (voir ASSUMPTIONS[\"quality_after_red\"]). Limite "
        "assumée : seule la semaine qui CONTIENT la date de course est concernée, "
        "pas les semaines d'affûtage qui la précèdent (hors périmètre de #52, "
        "raffinable plus tard si besoin s'en fait sentir). "
        "SEMAINE APRÈS UNE COURSE (récupération) — revue de code #98, should-fix "
        "6 : la semaine qui SUIT une course n'est PAS traitée comme une semaine "
        "de course par cette logique (`race_date` n'y tombe plus), et pourrait "
        "donc en théorie voir R1 se déclencher sur la fatigue résiduelle de la "
        "course (ACWR élevé alors même que la semaine proposée est un repos "
        "actif à charge minimale). C'est pour EXACTEMENT ce cas que R1 compare "
        "`acwr_projected` à `acwr_baseline` (le même calcul avec les séances "
        "proposées mises à zéro, `_project_series(zero_proposed=True)`) : si la "
        "semaine proposée n'aggrave pas le ratio par rapport à un repos complet, "
        "R1 ne bloque PAS (`reason_code: \"acwr_elevated_by_recent_load\"`), "
        "quelle que soit la valeur absolue de l'ACWR — solution PRÉFÉRÉE à un "
        "simple « saute R1/R2 la semaine suivant la course », qui aurait dû "
        "deviner arbitrairement combien de semaines de répit accorder après "
        "quelle taille de course."
    ),
    "excluded_sessions": (
        "Une séance `status: \"cancelled\"`, `\"moved\"` ou `\"missed\"` "
        "(ajoutée en revue de code #98, should-fix 4 — une séance déjà constatée "
        "manquée ne doit pas peser comme si elle allait avoir lieu), ou de repos "
        "(`sport: \"rest\"` ou `intensity: \"rest\"`), ne compte dans AUCUNE règle "
        "(charge projetée R1/R4, volume/D+ R2/R3/R6, qualité R5/R7) — le contrat "
        "n'a pas de motif d'annulation distinct médical/autre (même limite que "
        "`arc_metrics.week_compliance`), donc aucune séance annulée n'est jamais "
        "traitée comme si elle allait avoir lieu."
    ),
}


# ---------------------------------------------------------------------------
# Configuration — jamais en levant, avertit et retombe sur le défaut (même
# discipline que `arc_index.py::_heat_threshold_c`/`_hr_zone_method`).
# ---------------------------------------------------------------------------


def _warn(message: str) -> None:
    print(f"avertissement : {message}", file=sys.stderr)


def _positive_float_setting(section: dict, key: str, default: float) -> float:
    raw = section.get(key)
    if raw in (None, ""):
        return default
    value = None
    if not isinstance(raw, bool):
        if isinstance(raw, (int, float)):
            value = float(raw)
        elif isinstance(raw, str):
            try:
                value = float(raw.strip().replace(",", "."))
            except ValueError:
                value = None
    # `math.isfinite` (revue de code #98, should-fix 12) : sans ce garde-fou,
    # `float("nan")`/`float("inf")` passeraient `value <= 0` (False pour les
    # deux) et désactiveraient silencieusement la règle (`nan > seuil` est
    # toujours False, `inf > seuil` bloquerait tout — ni l'un ni l'autre n'est
    # une configuration valide).
    if value is None or not math.isfinite(value) or value <= 0:
        _warn(f"[guardrails].{key} = {raw!r} n'est pas un nombre strictement positif valide — "
              f"défaut {default:g} appliqué.")
        return default
    return value


def _bool_setting(section: dict, key: str, default: bool) -> bool:
    raw = section.get(key)
    if raw in (None, ""):
        return default
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, str):
        normalised = raw.strip().lower()
        if normalised in ("true", "1"):
            return True
        if normalised in ("false", "0"):
            return False
    _warn(f"[guardrails].{key} = {raw!r} n'est pas un booléen valide — défaut {default} appliqué.")
    return default


def _enum_setting(section: dict, key: str, allowed: Sequence[str], default: str) -> str:
    raw = section.get(key)
    if raw in (None, ""):
        return default
    if isinstance(raw, str) and raw.strip().lower() in allowed:
        return raw.strip().lower()
    _warn(f"[guardrails].{key} = {raw!r} hors de {allowed} — défaut « {default} » appliqué.")
    return default


def guardrail_settings(config: Dict[str, dict]) -> dict:
    """Résout `[guardrails]` de la configuration fusionnée (`arc_index.load_config`),
    jamais en levant — une valeur absente ou invalide retombe sur son défaut avec un
    avertissement sur stderr (voir les seuils `DEFAULT_*` en tête de module, qui font
    foi si `config/workspace.toml` ne porte pas encore de section `[guardrails]`,
    ex. workspace installé avant #52)."""
    section = config.get("guardrails", {}) or {}
    severities: Dict[str, str] = {}
    for rule_id, default_severity in DEFAULT_SEVERITY.items():
        severities[rule_id] = _enum_setting(section, f"severity_{rule_id}", SEVERITIES, default_severity)
    return {
        "enabled": _bool_setting(section, "enabled", True),
        "r1_acwr_max": _positive_float_setting(section, "r1_acwr_max", DEFAULT_ACWR_MAX),
        "r2_volume_increase_max_pct": _positive_float_setting(
            section, "r2_volume_increase_max_pct", DEFAULT_VOLUME_INCREASE_MAX_PCT),
        "r2_volume_reference": _enum_setting(
            section, "r2_volume_reference", ("previous_week", "mean4"), DEFAULT_VOLUME_REFERENCE),
        "r3_elevation_increase_max_pct": _positive_float_setting(
            section, "r3_elevation_increase_max_pct", DEFAULT_ELEVATION_INCREASE_MAX_PCT),
        "r4_monotony_max": _positive_float_setting(section, "r4_monotony_max", DEFAULT_MONOTONY_MAX),
        "r6_long_run_share_max_pct": _positive_float_setting(
            section, "r6_long_run_share_max_pct", DEFAULT_LONG_RUN_SHARE_MAX_PCT),
        "severity": severities,
    }


# ---------------------------------------------------------------------------
# Contexte — lecture de l'index dérivé (impur, jamais appelé par les tests
# unitaires de `evaluate`, qui reçoivent un contexte déjà construit à la main).
# ---------------------------------------------------------------------------


def _monday(day: date) -> date:
    return day - timedelta(days=day.weekday())


def _run_family_totals(conn, start: date, end: date) -> dict:
    """Somme, sur `[start, end]` inclus, `duration_s`/`distance_m`/`elevation_gain_m`
    des activités de la famille course à pied (arc_metrics.sport_family == "run") —
    voir ASSUMPTIONS["volume_and_elevation"]. Rend aussi `has_any_activity`, VRAI
    seulement s'il existe une activité de CETTE famille sur la fenêtre (revue de
    code #98, should-fix 10 : une semaine 100 % vélo n'est PAS une référence pour
    R2/R3, même si `activity` a bien des lignes ce jour-là — sans cette
    distinction, R2/R3 étaient déclarées « vérifiées » alors qu'aucune comparaison
    n'était réellement possible, la référence retombant silencieusement à zéro)."""
    rows = conn.execute(
        "SELECT sport, duration_s, distance_m, elevation_gain_m FROM activity "
        "WHERE date >= ? AND date <= ?", (start.isoformat(), end.isoformat())).fetchall()
    duration_s = distance_m = elevation_m = 0.0
    has_run_activity = False
    for sport, dur, dist, elev in rows:
        if M.sport_family(sport) != "run":
            continue
        has_run_activity = True
        duration_s += dur or 0.0
        distance_m += dist or 0.0
        elevation_m += elev or 0.0
    return {"duration_s": duration_s, "distance_m": distance_m, "elevation_gain_m": elevation_m,
            "has_any_activity": has_run_activity}


def _recent_run_pace_s_km(conn, week_start: date) -> Optional[float]:
    """Allure course RÉCENTE (médiane, s/km) sur les `RECENT_PACE_WINDOW_DAYS`
    jours précédant `week_start`, famille course à pied seulement — voir
    `ASSUMPTIONS["distance_only_estimate"]`. `None` si aucune activité de cette
    fenêtre n'a à la fois une durée ET une distance (jamais une allure inventée)."""
    start = (week_start - timedelta(days=RECENT_PACE_WINDOW_DAYS)).isoformat()
    end = (week_start - timedelta(days=1)).isoformat()
    rows = conn.execute(
        "SELECT sport, duration_s, distance_m FROM activity WHERE date >= ? AND date <= ?",
        (start, end)).fetchall()
    paces = [
        duration_s / (distance_m / 1000.0)
        for sport, duration_s, distance_m in rows
        if M.sport_family(sport) == "run" and duration_s and distance_m
    ]
    return statistics.median(paces) if paces else None


def _week_activities(conn, week_start: date, week_end: date) -> List[dict]:
    """Activités réelles indexées dans `[week_start, week_end]` — utilisées par
    `_week_loads_by_date` pour apparier chaque séance proposée à une activité
    réelle (revue de code #98, blocker 2), au lieu de la charge agrégée par jour
    (`loads_by_date`) qui masquait un second entraînement du jour ou une séance
    encore prévue le jour d'une activité réelle déjà indexée."""
    rows = conn.execute(
        "SELECT date, sport, load FROM activity WHERE date >= ? AND date <= ?",
        (week_start.isoformat(), week_end.isoformat())).fetchall()
    return [{"date": d, "sport": sport, "load": load or 0.0} for d, sport, load in rows]


def _reference_totals(conn, week_start: date, reference: str) -> dict:
    """Totaux de référence pour R2/R3, selon `reference` ("previous_week" | "mean4").
    `mean4` moyenne les 4 semaines calendaires précédentes (chacune Lun-Dim), qu'elles
    aient ou non des activités — une semaine sans activité dans la fenêtre compte pour
    0, pas comme absente, SAUF si AUCUNE des 4 n'a la moindre activité (voir
    `has_any_activity`), auquel cas la référence est déclarée sans historique."""
    if reference == "previous_week":
        prev_start = week_start - timedelta(days=7)
        prev_end = week_start - timedelta(days=1)
        return _run_family_totals(conn, prev_start, prev_end)
    totals = {"duration_s": 0.0, "distance_m": 0.0, "elevation_gain_m": 0.0}
    has_any = False
    for i in range(1, 5):
        w_start = week_start - timedelta(days=7 * i)
        w_end = w_start + timedelta(days=6)
        week_totals = _run_family_totals(conn, w_start, w_end)
        has_any = has_any or week_totals["has_any_activity"]
        for key in totals:
            totals[key] += week_totals[key]
    for key in totals:
        totals[key] /= 4.0
    totals["has_any_activity"] = has_any
    return totals


def _health_verdicts(conn, start: date, end: date) -> Dict[str, Optional[str]]:
    rows = conn.execute(
        "SELECT date, verdict FROM health_day WHERE date >= ? AND date <= ?",
        (start.isoformat(), end.isoformat())).fetchall()
    return {d: v for d, v in rows}


def _active_objective_race_date(conn) -> Optional[str]:
    row = conn.execute("SELECT race_date FROM objective WHERE race_date IS NOT NULL "
                        "ORDER BY source_path LIMIT 1").fetchone()
    return row[0] if row else None


def build_context(conn, config: Dict[str, dict], gconf: dict, week_start: date,
                   today: Optional[date] = None) -> dict:
    """Construit le `context` consommé par `evaluate`, en lisant l'index dérivé
    (`conn`, ouvert par `arc_index.open_db`/`index_workspace`) et la configuration
    déjà résolue par `arc_index.settings`/`guardrail_settings`.

    `week_start` : lundi de la semaine PROPOSÉE (pas forcément déjà écrite). `today`
    (défaut : `date.today()`) sert de repère à DEUX endroits (revue de code #98,
    nit — corrige une affirmation devenue fausse : `today` gouvernait déjà, avant
    cette PR, uniquement R5) :
    - R5 (qualité après un verdict rouge) : bilan matinal, sans dépendance à
      `today` en tant que telle (`health_by_date` couvre la semaine entière).
    - R1/R4 (`evaluate`/`_project_series`) : un jour de la semaine proposée
      STRICTEMENT AVANT `today` sans activité réelle indexée compte une charge de
      0, jamais la charge PROJETÉE de la séance planifiée (revue de code #98,
      blocker/should-fix 5) — un jour déjà passé sans donnée ne doit jamais
      recevoir le bénéfice d'une charge qui n'a peut-être jamais eu lieu. Un jour
      ≥ `today` (aujourd'hui inclus) reçoit la charge projetée comme avant :
      c'est le sens même d'une valeur « projetée ».
    Voir ASSUMPTIONS pour la méthode complète.
    """
    today = today or date.today()
    settings = I.settings(config)
    week_end = week_start + timedelta(days=6)

    # --- Charge réelle déjà indexée (R1/R4) — la PROJECTION elle-même (fusion
    # avec la charge estimée des séances proposées) est faite par `evaluate`,
    # jamais ici : `build_context` ne connaît pas encore la semaine proposée,
    # et une même charge réelle doit pouvoir être réutilisée pour évaluer
    # plusieurs propositions successives sans reformuler une requête SQL à
    # chaque fois. Voir ASSUMPTIONS["acwr_projection"].
    rows = conn.execute("SELECT date, load FROM activity WHERE load IS NOT NULL").fetchall()
    loads_by_date: Dict[str, float] = {}
    for d, load in rows:
        loads_by_date[d] = loads_by_date.get(d, 0.0) + (load or 0.0)

    # --- Semaine de référence / moyenne 4 semaines (R2/R3) -----------------
    previous_week = _run_family_totals(conn, week_start - timedelta(days=7), week_start - timedelta(days=1))
    mean4 = _reference_totals(conn, week_start, "mean4")

    # --- Verdicts santé (R5), un jour avant la semaine jusqu'à son dernier jour ---
    health_by_date = _health_verdicts(conn, week_start - timedelta(days=1), week_end)

    # --- Objectif actif / semaine de course (voir ASSUMPTIONS["race_week"]) ---
    race_date_iso = _active_objective_race_date(conn)
    is_race_week = bool(race_date_iso) and week_start.isoformat() <= race_date_iso <= week_end.isoformat()

    return {
        "week_start": week_start.isoformat(),
        "week_end": week_end.isoformat(),
        "today": today.isoformat(),
        "sport_primary": settings["sport"],
        "morning_check": settings["morning_check"],
        "race_date": race_date_iso,
        "is_race_week": is_race_week,
        "has_load_history": bool(loads_by_date),
        "loads_by_date": loads_by_date,
        "week_activities": _week_activities(conn, week_start, week_end),
        "recent_run_pace_s_km": _recent_run_pace_s_km(conn, week_start),
        "previous_week": previous_week,
        "mean4_weeks": mean4,
        "health_by_date": health_by_date,
    }


# ---------------------------------------------------------------------------
# evaluate() — cœur PUR, aucune E/S, entièrement déterministe (palier D).
# ---------------------------------------------------------------------------


def _skip(rule_id: str, reason_code: str, reason: str) -> dict:
    return {"rule_id": rule_id, "reason_code": reason_code, "reason": reason}


def _violation(rule_id: str, severity: str, message: str, message_en: str,
               observed, threshold, source: str, session_dates: Optional[List[str]] = None) -> dict:
    return {
        "rule_id": rule_id,
        "severity": severity,
        "message": message,
        "message_en": message_en,
        "values": {"observed": observed, "threshold": threshold},
        "session_dates": sorted(session_dates) if session_dates else [],
        "source": source,
    }


def _week_sessions(proposed_week: dict) -> List[dict]:
    return [s for s in (proposed_week.get("sessions") or []) if isinstance(s, dict)]


def _run_family_sessions(sessions: List[dict]) -> List[dict]:
    return [s for s in sessions if not _is_excluded(s) and M.sport_family(s.get("sport")) == "run"]


def _sum(sessions: List[dict], key: str) -> float:
    return sum((s.get(key) or 0.0) for s in sessions)


def _sum_effective_duration(sessions: List[dict], recent_pace_s_km: Optional[float]) -> float:
    """Comme `_sum(sessions, "planned_duration_s")`, mais utilise la durée
    EFFECTIVE (`_effective_planned_duration_s`, estimée depuis la distance quand
    la durée manque) — voir `ASSUMPTIONS["distance_only_estimate"]`."""
    total = 0.0
    for s in sessions:
        duration_s, _estimated = _effective_planned_duration_s(s, recent_pace_s_km)
        total += duration_s or 0.0
    return total


def _unresolved_duration_dates(sessions: List[dict], recent_pace_s_km: Optional[float]) -> List[str]:
    """Dates (triées, sans doublon) des séances de la famille course à pied, non
    exclues, prescrites en distance (`planned_distance_m`) mais SANS
    `planned_duration_s` NI allure récente disponible pour l'estimer — revue de
    code #98, blocker 3 : ces séances rendent la charge/le volume PROJETÉS de
    toute la semaine non fiables (R1/R2/R4), pas seulement leur propre part."""
    dates = set()
    for s in sessions:
        if _is_excluded(s) or M.sport_family(s.get("sport")) != "run":
            continue
        if s.get("planned_duration_s") or not s.get("planned_distance_m"):
            continue
        duration_s, _estimated = _effective_planned_duration_s(s, recent_pace_s_km)
        if duration_s is None and s.get("date"):
            dates.add(s["date"])
    return sorted(dates)


def _estimated_duration_dates(sessions: List[dict], recent_pace_s_km: Optional[float]) -> List[str]:
    """Dates des séances dont la durée a été ESTIMÉE depuis la distance (pas
    renseignée telle quelle) — exposé dans `context` pour transparence (revue de
    code #98, blocker 3 : « flagged as estimated in context »)."""
    dates = set()
    for s in sessions:
        if _is_excluded(s):
            continue
        duration_s, estimated = _effective_planned_duration_s(s, recent_pace_s_km)
        if estimated and duration_s and s.get("date"):
            dates.add(s["date"])
    return sorted(dates)


def _pct_increase(observed: float, reference: float) -> Optional[float]:
    if reference <= 0:
        return None
    return round(100.0 * (observed - reference) / reference, 1)


def _week_loads_by_date(context: dict, sessions: List[dict], week_start: date, week_end: date,
                         today: date, zero_proposed: bool) -> Dict[str, float]:
    """Charge quotidienne de la semaine proposée, séance par séance — revue de
    code #98, blocker 2 : jamais la charge déjà agrégée par jour dans
    `context["loads_by_date"]` pour les dates de CETTE semaine (qui masquerait un
    second entraînement du jour, ou effacerait une séance encore prévue le jour
    d'une activité réelle déjà indexée). Chaque séance non exclue de la semaine
    est appariée à une activité réelle (`arc_metrics._resolve_sessions`, même
    logique que `arc_metrics.week_compliance` : statut `done` explicite, ou
    appariement automatique date+sport/famille) ; les charges de PLUSIEURS
    séances le même jour sont SOMMÉES, jamais l'une écrasant l'autre.

    Une séance NON appariée à une activité réelle compte :
    - sa charge RÉELLE si elle est appariée (`week_compliance` l'aurait
      appariée aussi) ;
    - 0 si sa date est STRICTEMENT avant `today` (revue de code #98, blocker/
      should-fix 5 : un jour déjà passé sans activité indexée ne doit jamais
      recevoir le bénéfice d'une charge projetée qui n'a peut-être jamais eu
      lieu — voir `ASSUMPTIONS["acwr_projection"]`) ;
    - sa charge PROJETÉE sinon (`projected_session_load`), sauf si
      `zero_proposed` (calcul du scénario « repos complet » de R1, voir
      `ASSUMPTIONS["race_week"]`), auquel cas elle compte aussi 0.
    """
    activities_by_date: Dict[str, List[dict]] = {}
    for act in context.get("week_activities") or []:
        activities_by_date.setdefault(act["date"], []).append({**act, "_used": False})
    # Triées par date (même convention que `arc_metrics.week_compliance`) : le
    # résultat (charge par date, sommée) doit être identique quel que soit
    # l'ordre des séances dans `proposed_week["sessions"]` — revue de code #98,
    # blocker 2 ("tests both orders").
    non_excluded = sorted((s for s in sessions if not _is_excluded(s)), key=lambda s: s.get("date") or "")
    resolved = M._resolve_sessions(non_excluded, activities_by_date, week_end.isoformat())
    recent_pace = context.get("recent_run_pace_s_km")
    loads: Dict[str, float] = {}
    for r in resolved:
        day_iso = r["session"].get("date")
        if not day_iso:
            continue
        if r["actual"]:
            load = r["actual"].get("load") or 0.0
        elif date.fromisoformat(day_iso) < today:
            load = 0.0
        elif zero_proposed:
            load = 0.0
        else:
            load = projected_session_load(r["session"], recent_pace)
        loads[day_iso] = loads.get(day_iso, 0.0) + load
    return loads


def _max_week_acwr(series: List[dict]) -> Optional[float]:
    """Maximum de l'ACWR sur les 7 DERNIERS points de la série — qui coïncident
    exactement avec la semaine proposée (`week_start` est toujours un lundi,
    `week_end = week_start + 6`), voir `ASSUMPTIONS["acwr_projection"]` (revue de
    code #98, should-fix 7 : évaluer le pic de la semaine plutôt que le seul
    dimanche, moins sensible au motif hebdomadaire — une longue sortie le
    dimanche gonfle artificiellement l'ACWR du seul dernier jour)."""
    week_points = series[-7:] if len(series) >= 7 else series
    values = [p["acwr"] for p in week_points if p.get("acwr") is not None]
    return max(values) if values else None


def _project_series(context: dict, sessions: List[dict], week_start: date, week_end: date,
                     zero_proposed: bool = False) -> dict:
    """Fusionne la charge réelle déjà indexée (`context["loads_by_date"]`, jours
    STRICTEMENT avant `week_start`) avec la charge de la semaine proposée
    (`_week_loads_by_date`), puis rend l'ACWR (maximum sur la semaine, voir
    `_max_week_acwr`) et la monotonie/condition/fatigue (valeur du dernier jour,
    dimanche) — voir `ASSUMPTIONS["acwr_projection"]`.

    `zero_proposed` : calcule le scénario « repos complet » (aucune séance
    projetée ne compte, seule la charge déjà réelle de la semaine est gardée) —
    utilisé par R1 pour ne bloquer QUE si la semaine proposée AGGRAVE le ratio
    par rapport à ce scénario (revue de code #98, should-fix 6).
    """
    today = date.fromisoformat(context["today"]) if context.get("today") else week_start
    loads_by_date: Dict[str, float] = {
        d: v for d, v in (context.get("loads_by_date") or {}).items()
        if date.fromisoformat(d) < week_start
    }
    loads_by_date.update(_week_loads_by_date(context, sessions, week_start, week_end, today, zero_proposed))

    known_dates = [date.fromisoformat(d) for d in loads_by_date] or [week_start]
    series_start = min(known_dates + [week_start])
    series = M.daily_series(loads_by_date, series_start, week_end)
    last = series[-1] if series else {}

    real_loads = context.get("loads_by_date") or {}
    if real_loads:
        first_real_date = min(date.fromisoformat(d) for d in real_loads)
        history_span_days = (week_start - first_real_date).days
    else:
        history_span_days = 0
    history_sufficient = history_span_days >= MIN_HISTORY_DAYS_FOR_PROJECTION

    return {
        "acwr_projected": _max_week_acwr(series) if history_sufficient else None,
        "monotony_projected": last.get("monotony") if history_sufficient else None,
        "fitness_projected": last.get("fitness"),
        "fatigue_projected": last.get("fatigue"),
        "history_days": len(loads_by_date),
        "history_span_days": history_span_days,
        "history_sufficient": history_sufficient,
    }


def _eval_r1(context: dict, gconf: dict) -> Tuple[Optional[dict], Optional[dict]]:
    rule_id = "r1_acwr_projected"
    acwr = context.get("acwr_projected")
    if acwr is None:
        return None, _skip(rule_id, "insufficient_history",
                            "condition (fitness) trop faible, ou historique réel trop court "
                            f"(< {MIN_HISTORY_DAYS_FOR_PROJECTION} j), pour un ACWR projeté "
                            "significatif — voir arc_metrics.ACWR_MIN_FITNESS et "
                            "arc_guardrails.MIN_HISTORY_DAYS_FOR_PROJECTION.")
    threshold = gconf["r1_acwr_max"]
    if acwr <= threshold:
        return None, None
    baseline = context.get("acwr_baseline")
    if baseline is not None and acwr <= baseline:
        # La semaine proposée n'AGGRAVE pas le ratio par rapport à un scénario de
        # repos complet cette semaine-là (`acwr_baseline`, voir `_project_series`,
        # `zero_proposed=True`) : l'ACWR élevé vient de la charge RÉELLE déjà
        # indexée (ex. course récente dont la fatigue ne s'est pas encore
        # résorbée), pas de ce qui est proposé — bloquer la semaine proposée n'y
        # changerait rien. Revue de code #98, should-fix 6.
        return None, _skip(rule_id, "acwr_elevated_by_recent_load",
                            f"ACWR projeté ({acwr:.2f}) dépasse le seuil ({threshold:g}) mais la "
                            "semaine proposée ne l'aggrave pas par rapport à une semaine de repos "
                            "complet (charge résiduelle d'un effort récent) — non bloqué.")
    return _violation(
        rule_id, gconf["severity"][rule_id],
        f"ACWR projeté (maximum sur la semaine) : {acwr:.2f}, au-delà du seuil {threshold:g}.",
        f"Projected ACWR (weekly maximum): {acwr:.2f}, above the {threshold:g} threshold.",
        acwr, threshold, ASSUMPTIONS["acwr_projection"]), None


def _eval_r2(context: dict, gconf: dict, sessions: List[dict], sport_primary: str) -> Tuple[Optional[dict], Optional[dict]]:
    rule_id = "r2_weekly_volume_jump"
    reference_name = gconf["r2_volume_reference"]
    reference = context["previous_week"] if reference_name == "previous_week" else context["mean4_weeks"]
    if not reference.get("has_any_activity"):
        # `has_any_activity` ne compte QUE la famille course à pied (revue de
        # code #98, should-fix 10) : une semaine 100 % vélo n'est pas un
        # historique de référence pour la durée/distance de COURSE — code
        # `no_reference`, distinct de `insufficient_history` (qui, lui, signale
        # l'absence de toute donnée, pas juste l'absence de la bonne famille).
        return None, _skip(rule_id, "no_reference",
                            "aucune activité de la famille course à pied sur la fenêtre de "
                            f"référence ({reference_name}) — rien à comparer.")
    run_sessions = _run_family_sessions(sessions)
    recent_pace = context.get("recent_run_pace_s_km")
    unresolved = _unresolved_duration_dates(sessions, recent_pace)
    if unresolved:
        return None, _skip(rule_id, "missing_planned_duration",
                            "séance(s) prescrite(s) en distance sans allure récente pour estimer "
                            "la durée, et donc le volume hebdomadaire planifié : "
                            + ", ".join(unresolved) + ".")
    proposed_duration = _sum_effective_duration(run_sessions, recent_pace)
    threshold = gconf["r2_volume_increase_max_pct"]
    duration_pct = _pct_increase(proposed_duration, reference["duration_s"])
    if duration_pct is not None and duration_pct > threshold:
        return _violation(
            rule_id, gconf["severity"][rule_id],
            f"Durée hebdomadaire planifiée en hausse de {duration_pct:g} % vs {reference_name} "
            f"(seuil {threshold:g} %).",
            f"Planned weekly duration up {duration_pct:g} % vs {reference_name} (threshold {threshold:g} %).",
            duration_pct, threshold, ASSUMPTIONS["volume_and_elevation"]), None
    if sport_primary == "road":
        proposed_distance = _sum(run_sessions, "planned_distance_m")
        distance_pct = _pct_increase(proposed_distance, reference["distance_m"])
        if distance_pct is not None and distance_pct > threshold:
            return _violation(
                rule_id, gconf["severity"][rule_id],
                f"Distance hebdomadaire planifiée en hausse de {distance_pct:g} % vs {reference_name} "
                f"(seuil {threshold:g} %).",
                f"Planned weekly distance up {distance_pct:g} % vs {reference_name} (threshold {threshold:g} %).",
                distance_pct, threshold, ASSUMPTIONS["volume_and_elevation"]), None
    return None, None


def _eval_r3(context: dict, gconf: dict, sessions: List[dict], sport_primary: str) -> Tuple[Optional[dict], Optional[dict]]:
    rule_id = "r3_weekly_elevation_jump"
    if sport_primary != "trail":
        return None, _skip(rule_id, "not_applicable_sport",
                            "R3 ne s'applique qu'en trail ([sport].primary).")
    reference_name = gconf["r2_volume_reference"]
    reference = context["previous_week"] if reference_name == "previous_week" else context["mean4_weeks"]
    if not reference.get("has_any_activity"):
        return None, _skip(rule_id, "no_reference",
                            "aucune activité de la famille course à pied sur la fenêtre de "
                            f"référence ({reference_name}) — rien à comparer.")
    run_sessions = _run_family_sessions(sessions)
    proposed_elevation = _sum(run_sessions, "planned_elevation_m")
    threshold = gconf["r3_elevation_increase_max_pct"]
    elevation_pct = _pct_increase(proposed_elevation, reference["elevation_gain_m"])
    if elevation_pct is not None and elevation_pct > threshold:
        return _violation(
            rule_id, gconf["severity"][rule_id],
            f"D+ hebdomadaire planifié en hausse de {elevation_pct:g} % vs {reference_name} "
            f"(seuil {threshold:g} %).",
            f"Planned weekly elevation gain up {elevation_pct:g} % vs {reference_name} (threshold {threshold:g} %).",
            elevation_pct, threshold, ASSUMPTIONS["volume_and_elevation"]), None
    return None, None


def _eval_r4(context: dict, gconf: dict) -> Tuple[Optional[dict], Optional[dict]]:
    rule_id = "r4_monotony_projected"
    monotony = context.get("monotony_projected")
    if monotony is None:
        return None, _skip(rule_id, "insufficient_history",
                            "monotonie non calculable (moins de 7 jours d'historique, charge "
                            "quotidienne constante sur la fenêtre, ou historique réel trop court — "
                            f"< {MIN_HISTORY_DAYS_FOR_PROJECTION} j, voir "
                            "arc_guardrails.MIN_HISTORY_DAYS_FOR_PROJECTION) — historique insuffisant.")
    threshold = gconf["r4_monotony_max"]
    if monotony > threshold:
        return _violation(
            rule_id, gconf["severity"][rule_id],
            f"Monotonie projetée : {monotony:.2f}, au-delà du seuil {threshold:g}.",
            f"Projected monotony: {monotony:.2f}, above the {threshold:g} threshold.",
            monotony, threshold, ASSUMPTIONS["monotony_projection"]), None
    return None, None


def _eval_r5(context: dict, sessions: List[dict], gconf: dict) -> Tuple[Optional[dict], Optional[dict]]:
    rule_id = "r5_quality_after_red"
    if context.get("morning_check") == "off":
        return None, _skip(rule_id, "health_check_disabled",
                            'bilan matinal désactivé ([health].morning_check = "off") — '
                            "aucune donnée de santé n'est récupérée.")
    health_by_date = context.get("health_by_date") or {}
    flagged_dates: List[str] = []
    for session in sessions:
        if _is_excluded(session) or not _is_quality(session):
            continue
        day = session.get("date")
        if not day:
            continue
        prev_day = (date.fromisoformat(day) - timedelta(days=1)).isoformat()
        if health_by_date.get(day) == "red" or health_by_date.get(prev_day) == "red":
            flagged_dates.append(day)
    if not flagged_dates:
        return None, None
    return _violation(
        rule_id, gconf["severity"][rule_id],
        "Séance(s) de qualité prévue(s) le jour même ou le lendemain d'un verdict santé rouge : "
        + ", ".join(sorted(flagged_dates)) + ".",
        "Quality session(s) planned on, or the day after, a red health verdict: "
        + ", ".join(sorted(flagged_dates)) + ".",
        sorted(flagged_dates), "red", ASSUMPTIONS["quality_after_red"], flagged_dates), None


def _eval_r6(sessions: List[dict], gconf: dict, recent_pace_s_km: Optional[float]) -> Tuple[Optional[dict], Optional[dict]]:
    rule_id = "r6_long_run_share"
    run_sessions = _run_family_sessions(sessions)
    if not run_sessions:
        return None, _skip(rule_id, "insufficient_history",
                            "aucune séance de la famille course à pied cette semaine — rien à comparer.")
    if len(run_sessions) < R6_MIN_SESSIONS:
        # Revue de code #98, should-fix 9 : avec très peu de séances (ex. 3 :
        # 60/60/120 min), la plus longue dépasse presque toujours 35 % par pure
        # construction arithmétique (peu de séances parmi lesquelles répartir le
        # volume) — pas un signal de charge excessive.
        return None, _skip(rule_id, "too_few_sessions",
                            f"moins de {R6_MIN_SESSIONS} séances de la famille course à pied cette "
                            "semaine — la part de la plus longue sortie n'est pas un repère fiable "
                            "avec aussi peu de séances.")
    durations = [(s, _effective_planned_duration_s(s, recent_pace_s_km)[0]) for s in run_sessions]
    if any(d is None for _, d in durations):
        # Impossible d'identifier la plus longue sortie avec certitude si au moins
        # une séance de la famille course n'a ni durée planifiée NI durée
        # estimable depuis sa distance (pas d'allure récente disponible) : mieux
        # vaut sauter la règle que de calculer une part sous-estimée qui
        # masquerait une sortie réellement dominante — voir
        # ASSUMPTIONS["long_run_share"]/["distance_only_estimate"].
        return None, _skip(rule_id, "missing_planned_duration",
                            "au moins une séance de la famille course à pied n'a ni "
                            "planned_duration_s ni durée estimable depuis sa distance — la plus "
                            "longue sortie ne peut pas être identifiée de façon fiable.")
    total_duration = sum(d for _, d in durations)
    if total_duration <= 0:
        return None, _skip(rule_id, "insufficient_history",
                            "durée planifiée totale nulle sur la famille course à pied cette "
                            "semaine — rien à comparer.")
    longest_session, longest_duration = max(durations, key=lambda pair: pair[1] or 0.0)
    # Plafonné à 100 % (revue de code #98, should-fix 12) : par construction le
    # maximum d'un sous-ensemble ne peut pas dépasser la somme, mais une garde
    # défensive contre un dépassement par imprécision flottante ne coûte rien.
    share = min(round(100.0 * longest_duration / total_duration, 1), 100.0)
    threshold = gconf["r6_long_run_share_max_pct"]
    if share > threshold:
        return _violation(
            rule_id, gconf["severity"][rule_id],
            f"La plus longue sortie ({longest_session.get('date')}) représente {share:g} % du volume "
            f"hebdomadaire (seuil {threshold:g} %).",
            f"The longest run ({longest_session.get('date')}) is {share:g} % of the weekly volume "
            f"(threshold {threshold:g} %).",
            share, threshold, ASSUMPTIONS["long_run_share"], [longest_session.get("date")]), None
    return None, None


def _eval_r7(sessions: List[dict], gconf: dict) -> Tuple[Optional[dict], Optional[dict]]:
    """Voir `ASSUMPTIONS["consecutive_quality"]` pour deux limites documentées et
    assumées (revue de code #98, nit) : cette règle ne regarde QUE les séances de
    la semaine proposée (une séance de qualité le dimanche de la semaine
    PRÉCÉDENTE suivie d'une séance de qualité le lundi proposé n'est pas
    détectée) — `build_context` ne fournit pas la semaine précédente déjà
    persistée, hors périmètre de #52."""
    rule_id = "r7_consecutive_quality"
    quality_dates_all = [
        s["date"] for s in sessions
        if not _is_excluded(s) and _is_quality(s) and s.get("date")
    ]
    flagged: set = set()
    # Deux séances de qualité le MÊME jour (revue de code #98, nit) : au moins
    # aussi préoccupant que deux jours consécutifs, détecté séparément puisque
    # `set(quality_dates_all)` en dessous ne verrait qu'une seule date.
    for d, n in {d: quality_dates_all.count(d) for d in set(quality_dates_all)}.items():
        if n > 1:
            flagged.add(d)
    quality_dates = sorted(set(quality_dates_all))
    for i in range(len(quality_dates) - 1):
        d1, d2 = date.fromisoformat(quality_dates[i]), date.fromisoformat(quality_dates[i + 1])
        if (d2 - d1).days == 1:
            flagged.add(quality_dates[i])
            flagged.add(quality_dates[i + 1])
    if not flagged:
        return None, None
    dates = sorted(flagged)
    return _violation(
        rule_id, gconf["severity"][rule_id],
        "Séances de qualité le même jour ou sur deux jours consécutifs : " + ", ".join(dates) + ".",
        "Quality sessions on the same day, or on consecutive days: " + ", ".join(dates) + ".",
        dates, 1, ASSUMPTIONS["consecutive_quality"], dates), None


# Règles désactivées en semaine de course (voir ASSUMPTIONS["race_week"]) — R5
# reste volontairement hors de cette liste.
_RACE_WEEK_SKIPPED = ("r1_acwr_projected", "r2_weekly_volume_jump", "r3_weekly_elevation_jump",
                      "r4_monotony_projected", "r6_long_run_share", "r7_consecutive_quality")


def evaluate(proposed_week: dict, context: dict, gconf: dict) -> dict:
    """Cœur PUR du moteur de garde-fous (#52) : aucune E/S, entièrement
    déterministe pour un triplet `(proposed_week, context, gconf)` donné —
    voir le docstring de tête de module pour la forme exacte de chaque
    paramètre et de la sortie.

    `proposed_week` : dict du bloc ```arc `kind: "week"`` (voir `arc_contract.
    SCHEMA["week"]`/`SUBSCHEMA["session"]`) — PEUT ne pas encore être persisté
    (c'est le point même du garde-fou : évaluer AVANT écriture). `context` :
    voir `build_context`. `gconf` : voir `guardrail_settings`.
    """
    _internal_only_keys = ("loads_by_date", "week_activities")
    output_context = {k: v for k, v in context.items() if k not in _internal_only_keys}
    if not gconf.get("enabled", True):
        return {
            "ok": True, "violations": [], "checked_rules": [],
            "skipped_rules": [_skip(rid, "guardrails_disabled",
                                     "[guardrails].enabled = false — moteur désactivé.")
                               for rid in RULE_IDS],
            "context": output_context,
        }

    sessions = _week_sessions(proposed_week)
    sport_primary = context.get("sport_primary", "trail")
    is_race_week = bool(context.get("is_race_week"))
    week_start = date.fromisoformat(context["week_start"])
    week_end = date.fromisoformat(context["week_end"])

    # `work_context` : le contexte reçu, ENRICHI de la projection ACWR/monotonie
    # (qui a besoin de la semaine proposée, donc calculée ici, pas dans
    # `build_context`) — voir `_project_series`. La sortie `context` du résultat
    # (`output_context`, défini plus haut) reste la vue COURTE sans `loads_by_date`
    # ni la projection (ajoutée séparément ci-dessous) : jamais des années de
    # charge quotidienne recopiées dans chaque appel JSON. `baseline` (scénario
    # « repos complet », voir `_project_series(zero_proposed=True)`) alimente
    # UNIQUEMENT R1 (`acwr_baseline`, should-fix 6) — jamais exposé pour la
    # monotonie/condition/fatigue, hors périmètre de ce garde-fou précis.
    projected = _project_series(context, sessions, week_start, week_end)
    baseline = _project_series(context, sessions, week_start, week_end, zero_proposed=True)
    projected["acwr_baseline"] = baseline["acwr_projected"]
    recent_pace = context.get("recent_run_pace_s_km")
    work_context = {**context, **projected}
    output_context.update(projected)
    output_context["distance_only_sessions_estimated"] = _estimated_duration_dates(sessions, recent_pace)

    violations: List[dict] = []
    skipped: List[dict] = []
    checked: List[str] = []

    evaluators = {
        "r1_acwr_projected": lambda: _eval_r1(work_context, gconf),
        "r2_weekly_volume_jump": lambda: _eval_r2(work_context, gconf, sessions, sport_primary),
        "r3_weekly_elevation_jump": lambda: _eval_r3(work_context, gconf, sessions, sport_primary),
        "r4_monotony_projected": lambda: _eval_r4(work_context, gconf),
        "r5_quality_after_red": lambda: _eval_r5(work_context, sessions, gconf),
        "r6_long_run_share": lambda: _eval_r6(sessions, gconf, recent_pace),
        "r7_consecutive_quality": lambda: _eval_r7(sessions, gconf),
    }

    for rule_id in RULE_IDS:
        if is_race_week and rule_id in _RACE_WEEK_SKIPPED:
            skipped.append(_skip(rule_id, "race_week",
                                  "semaine de course (objectif actif) — repères de charge non "
                                  "pertinents, voir ASSUMPTIONS['race_week']."))
            continue
        checked.append(rule_id)
        violation, skip = evaluators[rule_id]()
        if violation:
            violations.append(violation)
        elif skip:
            checked.pop()
            skipped.append(skip)

    violations.sort(key=lambda v: v["rule_id"])
    skipped.sort(key=lambda s: s["rule_id"])
    checked.sort()
    ok = not any(v["severity"] == "block" for v in violations)
    return {"ok": ok, "violations": violations, "checked_rules": checked,
            "skipped_rules": skipped, "context": output_context}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _read_week_argument(value: str) -> dict:
    """Lit `--week` : `-` pour stdin, sinon un chemin de fichier. Le texte est
    d'abord essayé comme un fichier Markdown contractuel (bloc ```arc, ce que
    porte un fichier déjà écrit dans `planning/`), puis, si aucun bloc n'est
    trouvé, comme du JSON brut (ce que produit un agent qui n'a PAS encore
    persisté la semaine — fichier temporaire ou flux stdin)."""
    text = sys.stdin.read() if value == "-" else Path(value).read_text(encoding="utf-8")
    try:
        block = C.extract_block(text)
    except C.ContractError as exc:
        raise ConfigError(f"--week : {exc}") from exc
    if block is not None:
        return block
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ConfigError(
            f"--week : ni bloc ```arc, ni JSON valide (ligne {exc.lineno}, colonne {exc.colno}) : {exc.msg}"
        ) from exc
    if not isinstance(data, dict):
        raise ConfigError(f"--week : objet JSON attendu, {type(data).__name__} trouvé.")
    return data


# Codes de sortie (revue de code #98, should-fix 11) — documentés ici ET dans
# `--help` : un agent en headless (câblage #53) doit pouvoir les distinguer sans
# ambiguïté.
#   0 : ok — aucune violation de sévérité "block" (des "warn"/"info" peuvent exister).
#   1 : au moins une violation de sévérité "block".
#   2 : erreur (fichier introuvable, JSON/semaine invalide, date malformée…) —
#       jamais confondu avec 1 : une erreur d'entrée n'est PAS un verdict de garde-fou.
EXIT_CODES_HELP = (
    "Codes de sortie : 0 = ok (aucune violation « block »), "
    "1 = au moins une violation « block », 2 = erreur (entrée invalide)."
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0], epilog=EXIT_CODES_HELP)
    parser.add_argument("command", nargs="?", default="check", choices=("check",))
    parser.add_argument("--week", required=True, metavar="FICHIER|-",
                        help="semaine proposée : chemin d'un fichier (Markdown ```arc ou JSON brut) "
                             "ou « - » pour lire le JSON/Markdown depuis stdin.")
    parser.add_argument("--workspace")
    parser.add_argument("--db")
    parser.add_argument("--memory", action="store_true")
    parser.add_argument("--today", help="date de référence (AAAA-MM-JJ), défaut aujourd'hui")
    return parser


def _validate_proposed_week(proposed_week: dict, week_start: date) -> None:
    """Valide la semaine proposée AVANT tout calcul (revue de code #98,
    should-fix 11) : contrat `arc_contract` (kind "week", champs requis/types de
    chaque séance — attrape par exemple un `planned_duration_s` non numérique
    avant qu'il ne fasse planter une opération arithmétique plus loin) et
    `week_start` sur un LUNDI (le moteur suppose partout que la semaine est
    Lundi-Dimanche, voir `ASSUMPTIONS["acwr_projection"]`). Lève `ConfigError`
    avec un message clair — jamais une exception qui remonterait telle quelle."""
    if week_start.weekday() != 0:
        raise ConfigError(
            f"--week : week_start « {week_start.isoformat()} » n'est pas un lundi "
            "(le moteur suppose des semaines Lundi-Dimanche)."
        )
    data = {"arc": C.ARC_VERSION, "kind": "week", **proposed_week}
    errors, _warnings = C.validate(data)
    if errors:
        raise ConfigError("--week : semaine non conforme au contrat :\n  " + "\n  ".join(errors))


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    if args.today:
        try:
            date.fromisoformat(args.today)
        except ValueError:
            raise ConfigError(f"--today : date AAAA-MM-JJ attendue, « {args.today} » reçue.")

    proposed_week = _read_week_argument(args.week)
    week_start_raw = proposed_week.get("week_start")
    if not week_start_raw:
        raise ConfigError("--week : « week_start » (AAAA-MM-JJ) obligatoire dans la semaine proposée.")
    try:
        week_start = date.fromisoformat(week_start_raw)
    except ValueError as exc:
        raise ConfigError(f"--week : week_start « {week_start_raw} » n'est pas une date AAAA-MM-JJ.") from exc
    if not isinstance(proposed_week.get("sessions"), list):
        raise ConfigError("--week : « sessions » (liste) obligatoire dans la semaine proposée.")
    _validate_proposed_week(proposed_week, week_start)

    workspace = workspace_root(args.workspace)
    conn = I.open_db(workspace, args.db, args.memory)
    today = date.fromisoformat(args.today) if args.today else date.today()
    I.index_workspace(conn, workspace, today.isoformat())
    config = I.load_config(workspace)
    gconf = guardrail_settings(config)
    context = build_context(conn, config, gconf, week_start, today)
    result = evaluate(proposed_week, context, gconf)
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except ConfigError as exc:
        print(f"erreur : {exc}", file=sys.stderr)
        sys.exit(2)
    except (OSError, ValueError, TypeError) as exc:
        # Revue de code #98, should-fix 11 : un fichier introuvable, une donnée
        # numérique en réalité une chaîne, une date malformée ailleurs que
        # --today/--week ne doivent JAMAIS remonter comme un code 1 (qui
        # signifierait « violation bloquante » aux yeux d'un agent en headless)
        # — code 2, comme toute autre erreur de configuration/entrée.
        print(f"erreur : {exc}", file=sys.stderr)
        sys.exit(2)
