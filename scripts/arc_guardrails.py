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
| `r1_acwr_projected` | ACWR (charge aiguë/chronique) PROJETÉ en fin de semaine proposée | `block` |
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
    {"rule_id": "r1_acwr_projected", "severity": "block",
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
DEFAULT_VOLUME_REFERENCE = "previous_week"       # "previous_week" | "mean4"
DEFAULT_ELEVATION_INCREASE_MAX_PCT = 10.0
DEFAULT_MONOTONY_MAX = 2.0
DEFAULT_LONG_RUN_SHARE_MAX_PCT = 35.0

DEFAULT_SEVERITY: Dict[str, str] = {
    "r1_acwr_projected": "block",
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
# statut).
_EXCLUDED_STATUSES = ("cancelled", "moved")


def _is_excluded(session: dict) -> bool:
    """Une séance annulée, déplacée ou de repos ne compte dans AUCUNE règle de
    charge/volume/qualité — voir `ASSUMPTIONS["excluded_sessions"]`."""
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


def projected_session_load(session: dict) -> float:
    """Charge PROJETÉE d'une séance planifiée, sur la MÊME échelle que
    `arc_metrics.session_load` (TRIMP/sRPE) — voir `ASSUMPTIONS["projected_load"]`
    pour la justification complète. Rend 0.0 pour une séance sans durée planifiée
    (jamais estimée depuis rien) ou explicitement de repos."""
    if _is_excluded(session):
        return 0.0
    duration_s = session.get("planned_duration_s")
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
        "R1 : la charge réelle déjà indexée (table `activity`, une ligne par jour, "
        "sommée si plusieurs séances) alimente arc_metrics.daily_series depuis la "
        "date de la plus ancienne activité connue jusqu'au dernier jour de la "
        "semaine proposée (dimanche) ; les jours de la semaine proposée qui n'ont "
        "PAS déjà une activité réelle indexée à cette date reçoivent la charge "
        "PROJETÉE de leur séance planifiée (projected_session_load) — un jour qui a "
        "déjà une activité réelle garde TOUJOURS cette valeur réelle (jamais "
        "écrasée par une projection, pour ne jamais compter une même charge deux "
        "fois). L'ACWR/la monotonie « projetés » sont la valeur du DERNIER jour de "
        "la série (dimanche de la semaine proposée) — la fenêtre de monotonie 7 j "
        "d'arc_metrics.daily_series coïncide alors exactement avec les 7 jours de "
        "la semaine proposée, puisque week_start est toujours un lundi. Repère "
        "indicatif de la littérature sur le ratio de charge aiguë/chronique "
        "(« acute:chronic workload ratio »), pas un seuil de blessure prouvé : "
        "Gabbett T.J. (2016), « The training-injury prevention paradox: should "
        "athletes be training smarter and harder? », British Journal of Sports "
        "Medicine, 50(5), 273-280 — la zone 0,8-1,3 y est documentée comme associée "
        "à un risque de blessure plus faible qu'au-delà de 1,5 ; c'est aussi le "
        "repère déjà partagé par `arc_metrics.ACWR_SAFE` dans ce projet. `resources/` "
        "ne contient pas cette référence (dossier propre au workspace de "
        "l'utilisateur, hors du dépôt public) : citée ici depuis la littérature, "
        "comme le fait déjà `arc_metrics.ASSUMPTIONS`."
    ),
    "volume_and_elevation": (
        "R2/R3 : comparaison au choix (`[guardrails].r2_volume_reference`) à la "
        "semaine PRÉCÉDENTE (les 7 jours immédiatement avant week_start) ou à la "
        "MOYENNE des 4 semaines précédentes — seule la famille course à pied "
        "(arc_metrics.sport_family == \"run\" : course, trail, randonnée, marche) "
        "compte, jamais le vélo/renforcement/natation d'une semaine multi-sport "
        "(cohérent avec `arc_metrics.GEAR_WEAR_SPORTS`/`FUELING_SPORTS`, mêmes "
        "raisons). R2 compare la durée planifiée totale (toujours) et la distance "
        "planifiée totale (seulement si [sport].primary == \"road\" : le D+ n'a pas "
        "de sens sur route). R3 compare le D+ planifié total, seulement si "
        "[sport].primary == \"trail\". Référence nulle (aucune activité de la "
        "famille course sur la fenêtre de référence) : la règle est SAUTÉE avec "
        "`reason_code: \"insufficient_history\"`, jamais un pourcentage infini ou "
        "une division par zéro — c'est le cas normal des toutes premières semaines "
        "d'un workspace neuf. Seule une HAUSSE déclenche la règle : une semaine de "
        "récupération (deload) ou d'affûtage, qui réduit le volume, ne peut jamais "
        "être signalée par R2/R3 (le calcul du pourcentage de variation n'est "
        "comparé au seuil que s'il est strictement positif). « Règle des 10 % » : "
        "convention très répandue dans le coaching course à pied (programmes pour "
        "débutants, littérature grand public), jamais validée par un essai "
        "contrôlé dédié à ma connaissance — traitée ici comme une APPROXIMATION DU "
        "PROJET, pas une référence bibliographique vérifiée, contrairement à R1/R4."
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
        "seuil évalué sur une valeur non significative. Source : Foster C. (1998), "
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
        "(durée). Séances annulées/déplacées/repos exclues des deux termes. "
        "Aucune sortie de la famille course cette semaine, ou volume total nul : "
        "`reason_code: \"insufficient_history\"` (rien à comparer). Plus longue "
        "sortie sans `planned_duration_s` renseignée : `reason_code: "
        "\"missing_planned_duration\"` plutôt qu'un partage silencieusement à "
        "zéro. Seuil par défaut 35 % : convention du projet (repère courant en "
        "coaching course à pied selon lequel une seule sortie ne devrait pas "
        "dominer la semaine, popularisé sous des formes voisines — ex. « pas plus "
        "de 25-30 % du volume hebdomadaire » — sans source unique, vérifiable et "
        "consensuelle identifiée), pas une valeur tirée d'un essai contrôlé publié."
    ),
    "consecutive_quality": (
        "R7 : deux séances de qualité (arc_metrics.QUALITY_INTENSITIES) sur deux "
        "jours consécutifs (écart d'exactement 1 jour), séances annulées/"
        "déplacées exclues. Principe de l'entraînement polarisé (alterner "
        "franchement facile et difficile, jamais du difficile deux jours de "
        "suite sans jour plus facile entre les deux) documenté par Seiler S. & "
        "Kjerland G.Ø. (2006), « Quantifying training intensity distribution in "
        "elite endurance athletes: is there evidence for an \"optimal\" "
        "distribution? », Scandinavian Journal of Medicine & Science in Sports, "
        "16(1), 49-56 — déjà cité par `arc_metrics.HR_ZONE_SEILER_PCT_MAX` pour la "
        "polarisation 80/20. Le seuil précis « jamais deux jours consécutifs » "
        "(plutôt qu'un espacement plus long) reste une APPROXIMATION DU PROJET : "
        "Seiler documente une distribution d'intensité globale, pas une règle "
        "d'espacement jour par jour."
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
        "raffinable plus tard si besoin s'en fait sentir)."
    ),
    "excluded_sessions": (
        "Une séance `status: \"cancelled\"` ou `status: \"moved\"`, ou de repos "
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
    if value is None or value <= 0:
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
    voir ASSUMPTIONS["volume_and_elevation"]. Rend aussi `has_any_activity`, distinct
    de "totaux nuls" : une semaine à 0 avec des activités connues (repos complet,
    blessure) n'est pas la même chose qu'une fenêtre sans AUCUNE donnée."""
    rows = conn.execute(
        "SELECT sport, duration_s, distance_m, elevation_gain_m FROM activity "
        "WHERE date >= ? AND date <= ?", (start.isoformat(), end.isoformat())).fetchall()
    duration_s = distance_m = elevation_m = 0.0
    has_any = False
    for sport, dur, dist, elev in rows:
        has_any = True
        if M.sport_family(sport) != "run":
            continue
        duration_s += dur or 0.0
        distance_m += dist or 0.0
        elevation_m += elev or 0.0
    return {"duration_s": duration_s, "distance_m": distance_m, "elevation_gain_m": elevation_m,
            "has_any_activity": has_any}


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
    (défaut : `date.today()`) sert de repère pour le bilan santé (R5) uniquement
    quand la semaine proposée démarre dans le passé ou aujourd'hui — la projection
    ACWR/monotonie (R1/R4), elle, couvre TOUJOURS l'intégralité de la semaine (lundi
    à dimanche), y compris les jours encore à venir : c'est le sens même d'une
    valeur « projetée ». Voir ASSUMPTIONS pour la méthode complète.
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


def _pct_increase(observed: float, reference: float) -> Optional[float]:
    if reference <= 0:
        return None
    return round(100.0 * (observed - reference) / reference, 1)


def _project_series(context: dict, sessions: List[dict], week_start: date, week_end: date) -> dict:
    """Fusionne la charge réelle déjà indexée (`context["loads_by_date"]`) avec la
    charge PROJETÉE des séances proposées, puis rend l'ACWR/la monotonie/la
    condition/la fatigue du DERNIER jour de la semaine proposée — voir
    `ASSUMPTIONS["acwr_projection"]`. Un jour qui a déjà une charge réelle indexée
    garde TOUJOURS cette valeur (jamais écrasée par une projection)."""
    loads_by_date: Dict[str, float] = dict(context.get("loads_by_date") or {})
    for session in sessions:
        day = session.get("date")
        if not day or day in loads_by_date:
            continue
        loads_by_date[day] = projected_session_load(session)
    known_dates = [date.fromisoformat(d) for d in loads_by_date] or [week_start]
    series_start = min(known_dates + [week_start])
    series = M.daily_series(loads_by_date, series_start, week_end)
    last = series[-1] if series else {}
    return {
        "acwr_projected": last.get("acwr"),
        "monotony_projected": last.get("monotony"),
        "fitness_projected": last.get("fitness"),
        "fatigue_projected": last.get("fatigue"),
        "history_days": len(loads_by_date),
    }


def _eval_r1(context: dict, gconf: dict) -> Tuple[Optional[dict], Optional[dict]]:
    rule_id = "r1_acwr_projected"
    acwr = context.get("acwr_projected")
    if acwr is None:
        return None, _skip(rule_id, "insufficient_history",
                            "condition (fitness) trop faible pour un ACWR significatif — "
                            "historique insuffisant (voir arc_metrics.ACWR_MIN_FITNESS).")
    threshold = gconf["r1_acwr_max"]
    if acwr > threshold:
        return _violation(
            rule_id, gconf["severity"][rule_id],
            f"ACWR projeté en fin de semaine : {acwr:.2f}, au-delà du seuil {threshold:g}.",
            f"Projected end-of-week ACWR: {acwr:.2f}, above the {threshold:g} threshold.",
            acwr, threshold, ASSUMPTIONS["acwr_projection"]), None
    return None, None


def _eval_r2(context: dict, gconf: dict, sessions: List[dict], sport_primary: str) -> Tuple[Optional[dict], Optional[dict]]:
    rule_id = "r2_weekly_volume_jump"
    reference_name = gconf["r2_volume_reference"]
    reference = context["previous_week"] if reference_name == "previous_week" else context["mean4_weeks"]
    if not reference.get("has_any_activity"):
        return None, _skip(rule_id, "insufficient_history",
                            "aucune activité de la famille course à pied sur la fenêtre de "
                            f"référence ({reference_name}) — historique insuffisant.")
    run_sessions = _run_family_sessions(sessions)
    proposed_duration = _sum(run_sessions, "planned_duration_s")
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
        return None, _skip(rule_id, "insufficient_history",
                            "aucune activité de la famille course à pied sur la fenêtre de "
                            f"référence ({reference_name}) — historique insuffisant.")
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
                            "monotonie non calculable (moins de 7 jours d'historique, ou "
                            "charge quotidienne constante sur la fenêtre) — historique insuffisant.")
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


def _eval_r6(sessions: List[dict], gconf: dict) -> Tuple[Optional[dict], Optional[dict]]:
    rule_id = "r6_long_run_share"
    run_sessions = _run_family_sessions(sessions)
    if not run_sessions:
        return None, _skip(rule_id, "insufficient_history",
                            "aucune séance de la famille course à pied cette semaine — rien à comparer.")
    if any(s.get("planned_duration_s") is None for s in run_sessions):
        # Impossible d'identifier la plus longue sortie avec certitude si au moins
        # une séance de la famille course n'a pas de durée planifiée (ex. prescrite
        # en distance seule) : mieux vaut sauter la règle que de calculer une part
        # sous-estimée qui masquerait une sortie réellement dominante — voir
        # ASSUMPTIONS["long_run_share"].
        return None, _skip(rule_id, "missing_planned_duration",
                            "au moins une séance de la famille course à pied n'a pas de "
                            "planned_duration_s — la plus longue sortie ne peut pas être "
                            "identifiée de façon fiable.")
    total_duration = _sum(run_sessions, "planned_duration_s")
    if total_duration <= 0:
        return None, _skip(rule_id, "insufficient_history",
                            "durée planifiée totale nulle sur la famille course à pied cette "
                            "semaine — rien à comparer.")
    longest = max(run_sessions, key=lambda s: s.get("planned_duration_s") or 0.0)
    share = round(100.0 * longest["planned_duration_s"] / total_duration, 1)
    threshold = gconf["r6_long_run_share_max_pct"]
    if share > threshold:
        return _violation(
            rule_id, gconf["severity"][rule_id],
            f"La plus longue sortie ({longest.get('date')}) représente {share:g} % du volume "
            f"hebdomadaire (seuil {threshold:g} %).",
            f"The longest run ({longest.get('date')}) is {share:g} % of the weekly volume "
            f"(threshold {threshold:g} %).",
            share, threshold, ASSUMPTIONS["long_run_share"], [longest.get("date")]), None
    return None, None


def _eval_r7(sessions: List[dict], gconf: dict) -> Tuple[Optional[dict], Optional[dict]]:
    rule_id = "r7_consecutive_quality"
    quality_dates = sorted({
        s["date"] for s in sessions
        if not _is_excluded(s) and _is_quality(s) and s.get("date")
    })
    flagged: set = set()
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
        "Séances de qualité sur deux jours consécutifs : " + ", ".join(dates) + ".",
        "Quality sessions on consecutive days: " + ", ".join(dates) + ".",
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
    output_context = {k: v for k, v in context.items() if k != "loads_by_date"}
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
    # charge quotidienne recopiées dans chaque appel JSON.
    projected = _project_series(context, sessions, week_start, week_end)
    work_context = {**context, **projected}
    output_context.update(projected)

    violations: List[dict] = []
    skipped: List[dict] = []
    checked: List[str] = []

    evaluators = {
        "r1_acwr_projected": lambda: _eval_r1(work_context, gconf),
        "r2_weekly_volume_jump": lambda: _eval_r2(work_context, gconf, sessions, sport_primary),
        "r3_weekly_elevation_jump": lambda: _eval_r3(work_context, gconf, sessions, sport_primary),
        "r4_monotony_projected": lambda: _eval_r4(work_context, gconf),
        "r5_quality_after_red": lambda: _eval_r5(work_context, sessions, gconf),
        "r6_long_run_share": lambda: _eval_r6(sessions, gconf),
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("command", nargs="?", default="check", choices=("check",))
    parser.add_argument("--week", required=True, metavar="FICHIER|-",
                        help="semaine proposée : chemin d'un fichier (Markdown ```arc ou JSON brut) "
                             "ou « - » pour lire le JSON/Markdown depuis stdin.")
    parser.add_argument("--workspace")
    parser.add_argument("--db")
    parser.add_argument("--memory", action="store_true")
    parser.add_argument("--today", help="date de référence (AAAA-MM-JJ), défaut aujourd'hui")
    return parser


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
