#!/usr/bin/env python3
"""Cibles personnelles d'une séance structurée — zones FC, allure GAP, D+ de
côte (#60, épopée #23).

## Pourquoi (vs pousser une séance « à l'aveugle »)

`skills/garmin-workout-scheduling` sait déjà construire le DTO Garmin d'une
séance ; ce module lui fournit les CIBLES à y mettre — celles de l'ATHLÈTE,
jamais des bornes génériques inventées :

- **Zones FC** (#43, `arc_metrics.hr_zone_resolution`) : bornes bpm par
  méthode réellement calculable pour le profil (LTHR -> Karvonen -> %FCmax),
  mappées depuis l'INTENSITÉ planifiée de la séance (`arc_contract.INTENSITY`).
- **Allure GAP plate** (#44/#58, `arc_slope_model.predict_speed`) : référence
  plate personnelle (ou générique, provenance explicite) pour un pas de plat
  en endurance/récupération.
- **Répétitions de côte** : durée + D+ ATTENDU (jamais mesuré à l'avance,
  toujours une PRÉVISION) à partir de la vitesse personnelle prédite à la
  pente demandée × la durée du répétitif.

Aucune cible n'est jamais inventée : quand le profil ou le modèle ne permet
pas de la calculer, la sortie porte `reason`/`reason_code` et le champ cible
reste `None` — jamais une valeur par défaut générique présentée comme
personnelle (même discipline que #43/#58/#59).

## Mapping intensité -> zone FC

`INTENSITY_TO_ZONE` : `recovery` -> Z1, `endurance` -> Z2, `tempo` -> Z3,
`threshold` -> Z4, `vo2max` -> Z5 — cohérent avec le nombre de zones rendues
par `arc_metrics.hr_zone_bounds` (6 bornes pour 5 zones, quelle que soit la
méthode). `race`, `rest`, `strength` n'ont PAS de mapping zone FC ici (une
course a son propre plan d'allure, #59 ; le repos et le renforcement n'ont pas
de zone FC de course à pied pertinente) : `reason_code="unmapped_intensity"`.

## Allure plate — pourquoi seulement recovery/endurance

`arc_slope_model` n'ajuste aujourd'hui qu'une courbe pente -> allure pour la
bande `"endurance"` (voir `arc_slope_model.BANDS`) : c'est la SEULE référence
de vitesse à effort constant que le projet peut calculer avec confiance pour
CET athlète. Un pas de tempo/seuil/VO2max demanderait de mettre cette
référence à l'échelle d'un effort plus dur — le projet n'a PAS de modèle
personnel validé pour cette mise à l'échelle sur une séance d'ENTRAÎNEMENT
(à la différence de #59, qui la dérive d'un OBJECTIF DE COURSE avec une
référence dure choisie et un exposant de Riegel/VDOT — un calcul spécifique à
une distance de course, pas transposable tel quel à « le pas de 6 min à
allure seuil d'une séance de fractionné »). Plutôt que d'inventer un facteur
d'échelle non validé, ce module ne rend PAS de cible d'allure plate pour
`tempo`/`threshold`/`vo2max`/`race`/`rest`/`strength`
(`reason_code="no_personal_pace_scaling_for_intensity"`) : ces séances-là se
pilotent par zone FC ou par ressenti, jamais par une allure GAP inventée.
Documenté honnêtement comme une limite du projet, pas un oubli — à lever si
une future story ajuste un modèle personnel effort par effort.

## Répétitions de côte — méthode, et pourquoi c'est une BORNE BASSE

`hill_repeat_targets(structure, bins, band=...)` : `structure` = `{"reps",
"rep_duration_s", "grade_pct", "recovery_s"?}`. Pour chaque répétition :
vitesse prédite à cette pente (`arc_slope_model.predict_speed(grade_pct/100,
bins)`, `bins` déjà résolus par l'appelant pour `band`) x durée du répétitif
= distance parcourue ; D+ attendu = distance x pente (seulement si
`grade_pct > 0` — un « répétitif de côte » suppose une montée ; une pente
nulle ou négative rend `reason_code="grade_not_positive"`, jamais un D+
négatif présenté comme un D+ de montée). Le D+ est une PRÉVISION à effort
constant (personnel ou générique selon la pente, voir
`arc_slope_model.ASSUMPTIONS['fallback']`), pas une promesse — les paniers de
forte pente sont souvent en repli générique faute d'historique suffisant :
`source`/`reason_code` par répétitif le disent explicitement.

**`basis` (`HILL_BAND_BASIS`) — cette prévision est une BORNE BASSE, pas une
prévision centrée** (revue de code #107, point 6) : avec `band="endurance"`
(le défaut), la vitesse prédite est celle de l'athlète à effort D'ENDURANCE
sur cette pente — or un répétitif de côte se court quasi-systématiquement
PLUS DUR qu'une sortie d'endurance à pente égale, donc plus vite. Le D+
attendu ici est donc probablement SOUS-estimé, jamais surestimé :
`basis="endurance_pace_lower_bound"` le documente explicitement, pour que
l'appelant phrase le D+ en « ≥ X m », jamais « ≈ X m ». `band="all"` (mélange
tous les efforts déjà observés à cette pente, y compris les plus durs) réduit
ce biais systématique sans le supprimer : `basis="mixed_effort_estimate"`.
Aucun modèle « effort de répétitif dédié » n'existe (#58 n'ajuste que
`"endurance"`/`"all"`, voir `arc_slope_model.BANDS`) — documenté honnêtement
plutôt que fabriqué.

**`reason`/`reason_code` racine reflètent TOUJOURS ceux du calcul de vitesse
sous-jacent, y compris en cas de succès** (revue de code #107, point 5) : un
`reason_code="extrapolated"` (pente au-delà du panier extrême fitté) est
INFORMATIF, pas un échec — `per_rep`/`total_elevation_gain_m` restent
renseignés. Seule une valeur `None` (pas de vitesse prédite du tout) signifie
« pas de cible ». Ne jamais confondre les deux : un appelant qui abandonnerait
la cible dès que `reason_code` est non `None` jetterait aussi les cibles
extrapolées, pourtant valides.

## Répétitif de côte sans clé `structure` — repli sur le titre de la séance

`arc_contract.SUBSCHEMA["session"]` n'a PAS de clé `structure` (l'ajouter à un
VRAI bloc ```arc ne ferait que produire un avertissement « clé inconnue »,
`arc_contract.py::_check_object`) : une séance lue depuis un fichier réel
(`--session Semaine.md#date`) n'en porte donc jamais. `build_session_targets`
retombe alors sur `parse_structure_text` appliqué à `structure_text` (passé
explicitement, ex. `--structure-text`) ou, à défaut, au `title` de la séance
— sans quoi un répétitif de côte planifié dans une semaine réelle serait
tout simplement INATTEIGNABLE par ce module (revue de code #107, point 7).

## Cibles en % de la vitesse critique (#169) — SEULEMENT si l'ajustement est valide

`cs_target_for_intensity(intensity, cs_fit)` : pour `tempo`/`threshold`/`vo2max`,
une plage de vitesse GAP en % de la vitesse critique (`arc_cs`, `CS_INTENSITY_PCT`)
**en complément** des zones FC, jamais à leur place. `cs_fit` = `arc_cs.fit_cs` (ou
`arc_index.pace_curve(...)["current"]`) ; un ajustement refusé, absent ou une
intensité sans mapping rend `reason_code` et AUCUNE vitesse — jamais une CS
supposée. Au-dessus de la CS (vo2max), `d_prime_budget_s` donne la durée cumulée
tenable à la borne haute (D′ / (v − CS)) : une répétition plus longue la dépasserait.
Les pourcentages sont une **approximation du projet** (`arc_cs.ASSUMPTIONS["targets"]`).
La cible est en vitesse GAP (« équivalent plat ») : sur une pente, la vitesse
réelle est plus basse (voir `arc_gap`). Contrôle de cohérence avec le seuil lactique
Garmin : `arc_cs.compare_threshold` (signalé, jamais arbitré).

## Unités du DTO Garmin (skills/garmin-workout-scheduling/SKILL.md)

- **FC** (`targetType: heart.rate.zone`, bornes personnalisées) :
  `targetValueOne`/`targetValueTwo` en **bpm**, entiers (arrondis) — la borne
  basse d'abord (`targetValueOne`), la borne haute ensuite
  (`targetValueTwo`), même convention que l'exemple du skill.
- **Allure** (`targetType: pace.zone`) : `targetValueOne`/`targetValueTwo` en
  **mètres par seconde**, PAS en s/km — confirmé sur le schéma Garmin
  reverse-engineered utilisé par `python-garminconnect` (PR #440, classe
  `PaceTarget`, « upper and lower limits in m/s » ; `targetValueOne` =
  `lower_limit`, c-à-d la vitesse la plus FAIBLE = l'allure la plus LENTE,
  `targetValueTwo` = `upper_limit` = la vitesse la plus ÉLEVÉE = l'allure la
  plus RAPIDE — jamais l'inverse). Ce module calcule tout en m/s en interne
  (comme `arc_gap`/`arc_slope_model`) : AUCUNE conversion s/km -> m/s n'est
  donc nécessaire côté DTO, seul le sens des bornes (lente -> rapide) compte.
  `pace_s_km_to_speed_ms`/`speed_ms_to_pace_s_km` ci-dessous restent exposées
  pour l'affichage humain (jamais pour le DTO).
- **Durée** (`endCondition: time`) : `endConditionValue` en **secondes**,
  jamais en minutes — `hill_repeat_targets` prend déjà `rep_duration_s` en
  secondes en entrée, aucune conversion à faire par l'appelant.
- **D+ attendu** : mètres — Garmin n'a PAS de champ DTO pour un dénivelé
  cible sur un pas d'entraînement (seule `endCondition`/`targetType`
  existent) : c'est une information de PROVENANCE/PRÉVISION à afficher dans
  la description du pas ou au coureur, jamais un champ du DTO.

## Ajustement à la chaleur prévue — `targets --heat` (#171)

`apply_heat(result, session, …)` (logique pure dans `arc_heat.py`, mêmes
coefficients que le pacing de course) ajoute au résultat : `heat_adjustment`
(facteur, action, motif, rappels hydratation), un `pace_target.adjusted` (m/s,
bornes ralenties) quand une allure plate existe, un `declared_pace` ralenti
quand `--pace-s-km` est fourni, et `trace` = le fragment `heat_adjustment` du
contrat `arc` (clé optionnelle d'une séance de semaine). La cible FC
(`hr_target`) n'est JAMAIS modifiée (la FC prime). C'est `pace_target.adjusted`
(et non `pace_target`) qu'il faut pousser dans le DTO quand
`heat_adjustment.applies` est vrai. Voir `arc_heat.ASSUMPTIONS`. Une cible en %
de la vitesse critique (`cs_target`, #169) est ralentie du même facteur
(`cs_target.adjusted`, même règle : seulement si l'intensité est maintenue) ;
`d_prime_budget_s` n'est pas recalculé (effet de la chaleur sur D′ non modélisé).

Stdlib uniquement (CONTRIBUTING.md).
"""

from __future__ import annotations

import sys
from pathlib import Path
from datetime import date
from typing import Dict, List, Optional, Sequence, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
import arc_cs as CS  # noqa: E402
import arc_heat as H  # noqa: E402
import arc_metrics as M  # noqa: E402
import arc_slope_model as SL  # noqa: E402
from coach_setup import workspace_root  # noqa: E402 (même résolution que arc_index.py/arc_guardrails.py)

# Intensité planifiée (`arc_contract.INTENSITY`) -> numéro de zone FC (1..5).
# `race`/`rest`/`strength` volontairement ABSENTS (voir docstring du module).
INTENSITY_TO_ZONE: Dict[str, int] = {
    "recovery": 1,
    "endurance": 2,
    "tempo": 3,
    "threshold": 4,
    "vo2max": 5,
}

# Intensités pour lesquelles une cible d'allure PLATE personnelle a un sens
# (voir docstring « Allure plate — pourquoi seulement recovery/endurance »).
FLAT_PACE_INTENSITIES = ("recovery", "endurance")

# Bande du modèle pente -> allure utilisée par défaut pour tout ce module —
# seule bande dont #58 documente la provenance personnelle/générique par
# panier (voir `arc_slope_model.BANDS`).
DEFAULT_BAND = "endurance"

# Méthodes de zones dont les bornes Z1/Z5 sont des SENTINELLES ouvertes plutôt
# que de vraies bornes physiologiques (revue de code #107, point 3) :
# `arc_metrics.HR_ZONE_LTHR_PCT` = (0.0, ..., 1.5) et `HR_ZONE_PCT_MAX` =
# (0.0, ..., 1.5) — Z1 démarre à 0 % de LTHR/FCmax (= 0 bpm littéralement) et
# Z5 monte jusqu'à 150 % de LTHR/FCmax (largement au-dessus de la FC max
# physiologique) : ces deux multiplicateurs signifient « zone ouverte vers le
# bas/le haut », jamais une vraie limite à pousser telle quelle dans un DTO
# Garmin. Karvonen (`HR_ZONE_KARVONEN_HRR_PCT`, 0,50..1,00 de la réserve) n'a
# PAS ce problème : ses deux bornes extrêmes sont déjà des valeurs réelles.
OPEN_ENDED_HR_METHODS = ("lthr", "percent_max")


def _clamp_open_ended_zone(zone: int, method: Optional[str], low: float, high: float,
                            athlete: dict) -> tuple:
    """Remplace une borne SENTINELLE (voir `OPEN_ENDED_HR_METHODS`) par une
    borne physiologique réelle avant de la pousser comme plage FC
    personnalisée sur Garmin : Z1 démarre à la FC de repos (le vrai plancher
    « récupération »), Z5 est plafonnée à la FC max. Rend `(low, high,
    reason, reason_code)` — `reason_code` non `None` signifie qu'AUCUNE borne
    fiable n'existe (profil sans la donnée nécessaire) : l'appelant abandonne
    alors la cible plutôt que de pousser la sentinelle brute (0 bpm, ou
    150 % de LTHR/FCmax, jamais vus sur un athlète réel)."""
    if method not in OPEN_ENDED_HR_METHODS:
        return low, high, None, None
    if zone == 1:
        hr_rest = athlete.get("hr_rest_bpm")
        if hr_rest is None:
            return None, None, ("zone 1 ouverte à 0 bpm par la méthode « " + method + " » : la FC de repos, "
                                 "seul plancher physiologique disponible, manque au profil"), "open_zone_floor_unknown"
        low = round(hr_rest)
    if zone == 5:
        hr_max = athlete.get("hr_max_bpm")
        if hr_max is None:
            return None, None, ("zone 5 ouverte au-delà de la FC max par la méthode « " + method + " » : la FC "
                                 "max, seul plafond physiologique disponible, manque au profil"), "open_zone_ceiling_unknown"
        high = min(high, round(hr_max))
    return low, high, None, None


# Tolérance appliquée de part et d'autre de la référence plate personnelle
# pour construire une PLAGE d'allure (le DTO Garmin `pace.zone` attend deux
# bornes, jamais une valeur unique) — choix de projet documenté (pas une
# mesure), volontairement modeste : la référence plate elle-même est déjà une
# médiane pondérée par le temps (#58), l'élargir de trop diluerait son
# utilité comme cible.
FLAT_PACE_TOLERANCE_PCT = 0.05


def pace_s_km_to_speed_ms(pace_s_km: Optional[float]) -> Optional[float]:
    """Allure (s/km) -> vitesse (m/s). `None`/valeur non positive -> `None`,
    jamais une division par zéro ni une vitesse infinie."""
    if not pace_s_km or pace_s_km <= 0:
        return None
    return 1000.0 / pace_s_km


def speed_ms_to_pace_s_km(speed_ms: Optional[float]) -> Optional[float]:
    """Vitesse (m/s) -> allure (s/km). `None`/valeur non positive -> `None`."""
    if not speed_ms or speed_ms <= 0:
        return None
    return 1000.0 / speed_ms


def hr_target_for_intensity(intensity: Optional[str], athlete: dict,
                             hr_zones_method: Optional[str] = None) -> dict:
    """Cible FC (bpm) pour une intensité planifiée, à partir des zones DE CET
    ATHLÈTE (`arc_metrics.hr_zone_resolution`, #43).

    Rend TOUJOURS `{"bounds_bpm": [low, high] | None, "zone": int | None,
    "method": str | None, "reason": str | None, "reason_code": str | None}` —
    jamais d'exception. `bounds_bpm` est `None` (jamais des bornes inventées)
    dès que l'intensité n'a pas de mapping zone FC, ou que le profil ne permet
    de calculer aucune méthode de zones."""
    if intensity not in INTENSITY_TO_ZONE:
        known = ", ".join(INTENSITY_TO_ZONE)
        return {
            "bounds_bpm": None, "zone": None, "method": None,
            "reason": f"intensité « {intensity} » sans zone FC de course à pied associée "
                      f"(mapping défini pour : {known})",
            "reason_code": "unmapped_intensity",
        }
    resolution = M.hr_zone_resolution(athlete, hr_zones_method)
    if resolution["bounds_bpm"] is None:
        return {
            "bounds_bpm": None, "zone": INTENSITY_TO_ZONE[intensity], "method": resolution["method"],
            "reason": resolution["reason"], "reason_code": "no_zone_data",
        }
    zone = INTENSITY_TO_ZONE[intensity]
    bounds = resolution["bounds_bpm"]
    low, high = bounds[zone - 1], bounds[zone]
    low, high, reason, reason_code = _clamp_open_ended_zone(zone, resolution["method"], low, high, athlete)
    if reason_code:
        return {"bounds_bpm": None, "zone": zone, "method": resolution["method"],
                "reason": reason, "reason_code": reason_code}
    return {
        "bounds_bpm": [round(low), round(high)], "zone": zone, "method": resolution["method"],
        "reason": None, "reason_code": None,
    }


def flat_pace_target_for_intensity(intensity: Optional[str], bins: Sequence[dict],
                                    *, tolerance_pct: float = FLAT_PACE_TOLERANCE_PCT) -> dict:
    """Cible d'allure GAP PLATE (m/s, bornes basse/haute) pour un pas de route
    d'une séance d'intensité `intensity` — voir docstring du module pour la
    restriction aux intensités `recovery`/`endurance`.

    Rend TOUJOURS `{"speed_low_ms", "speed_high_ms", "pace_low_s_km",
    "pace_high_s_km", "source", "reason", "reason_code"}` — jamais
    d'exception ; les 4 premières clés valent `None` sans cible calculable."""
    empty = {"speed_low_ms": None, "speed_high_ms": None, "pace_low_s_km": None,
              "pace_high_s_km": None, "source": None}
    if intensity not in FLAT_PACE_INTENSITIES:
        known = ", ".join(FLAT_PACE_INTENSITIES)
        return {**empty,
                "reason": f"pas de mise à l'échelle personnelle validée d'une allure plate pour l'intensité "
                          f"« {intensity} » (seules {known} ont une référence plate directement exploitable, "
                          "voir docstring du module) : piloter ce pas par zone FC plutôt que par allure",
                "reason_code": "no_personal_pace_scaling_for_intensity"}
    prediction = SL.predict_speed(0.0, bins)
    if prediction["speed_ms"] is None:
        return {**empty, "reason": prediction["reason"], "reason_code": prediction["reason_code"] or "no_model"}
    base = prediction["speed_ms"]
    low = base * (1.0 - tolerance_pct)
    high = base * (1.0 + tolerance_pct)
    return {
        "speed_low_ms": low, "speed_high_ms": high,
        "pace_low_s_km": speed_ms_to_pace_s_km(high),   # allure la plus RAPIDE = vitesse la plus haute
        "pace_high_s_km": speed_ms_to_pace_s_km(low),   # allure la plus LENTE = vitesse la plus basse
        "source": prediction["source"], "reason": prediction["reason"], "reason_code": prediction["reason_code"],
    }


def _validate_hill_structure(structure: dict) -> Optional[str]:
    reps = structure.get("reps")
    rep_duration_s = structure.get("rep_duration_s")
    grade_pct = structure.get("grade_pct")
    if not isinstance(reps, int) or reps < 1:
        return "« reps » attendu : entier >= 1"
    if not isinstance(rep_duration_s, (int, float)) or rep_duration_s <= 0:
        return "« rep_duration_s » attendu : nombre > 0 (secondes)"
    if not isinstance(grade_pct, (int, float)):
        return "« grade_pct » attendu : nombre (pourcentage, ex. 8 pour 8 %)"
    return None


# `hill_repeat_targets.basis` (revue de code #107, point 6) : la vitesse
# prédite vient TOUJOURS du modèle pente -> allure de la bande `band`, jamais
# d'un modèle « effort de répétitif de côte » dédié (qui n'existe pas — #58
# n'ajuste que `"endurance"`/`"all"`, voir `arc_slope_model.BANDS`). Un
# répétitif de côte se court quasi-systématiquement PLUS DUR qu'une sortie
# d'endurance sur la même pente : la bande `"endurance"` (le défaut) sous-estime
# donc plutôt qu'elle ne surestime la vitesse réelle, ce qui fait du D+
# attendu une BORNE BASSE plausible, jamais une prévision centrée — documenté
# explicitement pour que l'appelant phrase le D+ en "≥ X m", jamais "≈ X m".
# `band="all"` (mélange tous les efforts, y compris les plus durs déjà
# observés à cette pente) est une estimation moins systématiquement biaisée
# mais toujours pas garantie représentative d'un effort de répétitif.
HILL_BAND_BASIS = {
    "endurance": "endurance_pace_lower_bound",
    "all": "mixed_effort_estimate",
}


def hill_repeat_targets(structure: dict, bins: Sequence[dict], *, band: str = DEFAULT_BAND) -> dict:
    """Cibles durée/D+ d'un répétitif de côte — voir docstring du module.

    `structure` : `{"reps": int, "rep_duration_s": num, "grade_pct": num,
    "recovery_s": num?}`. Rend TOUJOURS un dict avec `reps`, `rep_duration_s`,
    `grade_pct`, `recovery_s`, `basis` (voir `HILL_BAND_BASIS` — une borne
    basse par défaut, jamais une prévision centrée), `per_rep` (`speed_ms`,
    `distance_m`, `elevation_gain_m`, `source`, `reason`, `reason_code`),
    `total_elevation_gain_m`, `total_work_duration_s`, `reason`, `reason_code`
    — jamais d'exception. `reason`/`reason_code` au niveau racine reflètent
    TOUJOURS ceux de `per_rep` (y compris quand `per_rep` est calculé avec
    succès : `reason_code="extrapolated"` est INFORMATIF, pas un échec — voir
    `arc_slope_model.predict_speed` — et doit rester visible sans avoir à
    creuser dans `per_rep`). `per_rep`/`total_elevation_gain_m` restent `None`
    UNIQUEMENT quand le D+ n'est pas calculable du tout."""
    error = _validate_hill_structure(structure)
    reps = structure.get("reps")
    rep_duration_s = structure.get("rep_duration_s")
    grade_pct = structure.get("grade_pct")
    recovery_s = structure.get("recovery_s")
    base = {
        "reps": reps, "rep_duration_s": rep_duration_s, "grade_pct": grade_pct, "recovery_s": recovery_s,
        "total_work_duration_s": (reps * rep_duration_s) if isinstance(reps, int) and
                                   isinstance(rep_duration_s, (int, float)) else None,
        "basis": HILL_BAND_BASIS.get(band),
    }
    if error:
        return {**base, "per_rep": None, "total_elevation_gain_m": None,
                "reason": error, "reason_code": "invalid_structure"}
    if grade_pct <= 0:
        return {**base, "per_rep": None, "total_elevation_gain_m": None,
                "reason": f"pente non positive ({grade_pct:g} %) : un répétitif de côte suppose une pente "
                          "montante, D+ non calculé (jamais un D+ négatif présenté comme un dénivelé de montée)",
                "reason_code": "grade_not_positive"}
    grade = grade_pct / 100.0
    prediction = SL.predict_speed(grade, bins)
    if prediction["speed_ms"] is None:
        return {**base, "per_rep": {
                    "speed_ms": None, "distance_m": None, "elevation_gain_m": None, "source": None,
                    "reason": prediction["reason"], "reason_code": prediction["reason_code"] or "no_model"},
                "total_elevation_gain_m": None,
                "reason": prediction["reason"], "reason_code": prediction["reason_code"] or "no_model"}
    speed = prediction["speed_ms"]
    distance_m = speed * rep_duration_s
    elevation_gain_m = distance_m * grade
    per_rep = {
        "speed_ms": speed, "distance_m": distance_m, "elevation_gain_m": elevation_gain_m,
        "source": prediction["source"], "reason": prediction["reason"], "reason_code": prediction["reason_code"],
    }
    # `reason`/`reason_code` racine reflètent ceux de `per_rep` même en succès
    # (ex. "extrapolated") — voir docstring, point 5 de la revue de code #107 :
    # jamais forcés à `None` alors qu'une information existe.
    return {**base, "per_rep": per_rep, "total_elevation_gain_m": elevation_gain_m * reps,
            "reason": prediction["reason"], "reason_code": prediction["reason_code"]}


# Plages de vitesse en fraction de la CS, par intensité planifiée — approximation du projet
# (voir `arc_cs.ASSUMPTIONS["targets"]`) ; recovery/endurance restent pilotées par FC/allure plate.
CS_INTENSITY_PCT = {"tempo": (0.88, 0.95), "threshold": (0.95, 1.00), "vo2max": (1.02, 1.10)}


def cs_target_for_intensity(intensity: Optional[str], cs_fit: Optional[dict]) -> dict:
    """Cible de vitesse GAP en % de la vitesse critique (#169) — voir la section du docstring de module.
    Rend toujours un dict ; `speed_low_ms`/`speed_high_ms` valent `None` (avec `reason_code`) quand
    l'ajustement n'est pas valide ou que l'intensité n'a pas de mapping."""
    base = {"source": "critical_speed", "intensity": intensity, "pct_low": None, "pct_high": None,
            "speed_low_ms": None, "speed_high_ms": None, "pace_slow_s_km": None, "pace_fast_s_km": None,
            "d_prime_budget_s": None, "cs_ms": None, "quality": None, "reason": None, "reason_code": None}
    if intensity not in CS_INTENSITY_PCT:
        return {**base, "reason": f"intensité « {intensity} » sans cible en % de la vitesse critique",
                "reason_code": "unmapped_intensity"}
    if not cs_fit or not cs_fit.get("valid"):
        why = (cs_fit or {}).get("reason") or "vitesse critique non calculée"
        return {**base, "reason": f"vitesse critique indisponible : {why}",
                "reason_code": (cs_fit or {}).get("reason_code") or "no_cs_fit"}
    lo, hi = CS_INTENSITY_PCT[intensity]
    cs = cs_fit["cs_ms"]
    v_lo, v_hi = cs * lo, cs * hi
    return {**base, "pct_low": lo, "pct_high": hi, "speed_low_ms": round(v_lo, 3), "speed_high_ms": round(v_hi, 3),
            "pace_slow_s_km": speed_ms_to_pace_s_km(v_lo), "pace_fast_s_km": speed_ms_to_pace_s_km(v_hi),
            "d_prime_budget_s": (round(b, 1) if (b := CS.d_prime_budget_s(cs_fit, v_hi)) is not None else None),
            "cs_ms": cs, "quality": cs_fit.get("quality")}


def build_session_targets(session: dict, *, athlete: dict, bins: Sequence[dict],
                           hr_zones_method: Optional[str] = None, band: str = DEFAULT_BAND,
                           structure_text: Optional[str] = None, cs_fit: Optional[dict] = None) -> dict:
    """Point d'entrée unique : `session` (voir `arc_contract.SUBSCHEMA["session"]`,
    plus une clé `structure` optionnelle, HORS contrat `arc` — `arc_contract`
    n'a pas de clé dédiée pour un répétitif de côte, l'ajouter au bloc ```arc
    d'une VRAIE semaine ne ferait que produire un avertissement « clé inconnue »
    sans utilité, voir `scripts/arc_contract.py::_check_object`).

    Une séance lue depuis un fichier réel (`--session Semaine.md#date`, voir
    `_load_session_arg`) n'a donc JAMAIS de clé `structure` : à défaut, ce
    point d'entrée essaie `parse_structure_text` sur `structure_text` (passé
    explicitement, ex. `--structure-text`) OU, à défaut, sur le `title` de la
    séance (revue de code #107, point 7 — sans quoi un répétitif de côte
    planifié dans une semaine réelle serait tout simplement INATTEIGNABLE par
    ce module, faute de champ `structure` dans le contrat).

    Rend `{"intensity", "sport", "hr_target", "pace_target", "hill_repeats", "cs_target"}` —
    `cs_target` (#169) : cible en % de la vitesse critique (`cs_target_for_intensity`), `None`
    quand `cs_fit` n'est pas fourni ou pour un répétitif de côte ;
    `pace_target` est `None` quand une structure de côte a été reconnue
    (explicite ou depuis le texte) ; `hill_repeats` est `None` sinon."""
    intensity = session.get("intensity")
    structure = session.get("structure") or parse_structure_text(structure_text or session.get("title"))
    hr_target = hr_target_for_intensity(intensity, athlete, hr_zones_method)
    if structure:
        return {
            "intensity": intensity, "sport": session.get("sport"),
            "hr_target": hr_target, "pace_target": None,
            "hill_repeats": hill_repeat_targets(structure, bins, band=band), "cs_target": None,
        }
    return {
        "intensity": intensity, "sport": session.get("sport"),
        "hr_target": hr_target, "pace_target": flat_pace_target_for_intensity(intensity, bins),
        "hill_repeats": None,
        "cs_target": cs_target_for_intensity(intensity, cs_fit) if cs_fit is not None else None,
    }


def apply_heat(result: dict, session: dict, *, temp_c: Optional[float], feels_like_c: Optional[float] = None,
               humidity_pct: Optional[float] = None, category: Optional[str] = None,
               acclimated: Optional[bool] = None, slot: Optional[str] = None,
               sweat_rate_l_h: Optional[float] = None, declared_pace_s_km: Optional[float] = None) -> dict:
    """Complète `result` (sortie de `build_session_targets`) avec l'ajustement
    chaleur (#171) — voir docstring du module. Ne touche jamais `hr_target`."""
    adj = H.heat_adjustment(H.classify_session(session), temp_c=temp_c, feels_like_c=feels_like_c,
                            humidity_pct=humidity_pct, category=category, acclimated=acclimated,
                            slot=slot, sweat_rate_l_h=sweat_rate_l_h)
    result["heat_adjustment"] = adj
    keep = adj["applies"] and adj["intensity_maintained"]
    factor = adj["factor"] if keep else 1.0
    pace = result.get("pace_target")
    if keep and pace and pace.get("speed_low_ms") is not None:
        low, high = H.slow_speed_ms(pace["speed_low_ms"], factor), H.slow_speed_ms(pace["speed_high_ms"], factor)
        pace["adjusted"] = {
            "speed_low_ms": low, "speed_high_ms": high,
            "pace_low_s_km": speed_ms_to_pace_s_km(high), "pace_high_s_km": speed_ms_to_pace_s_km(low),
            "factor": factor,
        }
    # #169 × #171 : une cible en % de la vitesse critique est ralentie du MÊME facteur que `pace_target`
    # (la CS vient de meilleurs efforts courus surtout par temps tempéré : par la chaleur, la vitesse tenable
    # à une même intensité baisse de la même façon). `cs_target` d'origine intact (non ajusté), comme
    # `pace_target`. `d_prime_budget_s` n'est PAS recalculé : l'effet de la chaleur sur D′ n'est pas
    # modélisé — le budget non ajusté reste la borne à ne pas dépasser. Rien en 🔴 (intensité non maintenue).
    cs = result.get("cs_target")
    if keep and cs and cs.get("speed_low_ms") is not None:
        low, high = H.slow_speed_ms(cs["speed_low_ms"], factor), H.slow_speed_ms(cs["speed_high_ms"], factor)
        cs["adjusted"] = {
            "speed_low_ms": low, "speed_high_ms": high,
            "pace_slow_s_km": speed_ms_to_pace_s_km(low), "pace_fast_s_km": speed_ms_to_pace_s_km(high),
            "factor": factor,
        }
    if declared_pace_s_km is not None:
        result["declared_pace"] = {
            "pace_s_km": declared_pace_s_km,
            "adjusted_pace_s_km": round(H.slow_pace_s_km(declared_pace_s_km, factor), 1) if keep else None,
            "factor": factor if keep else None,
        }
    if adj["applies"]:
        # Mesure absente = clé omise (contrat `arc`) : jamais de `temp_c` fictif quand le 🔴 vient
        # du vent/de la pluie/de l'orage sans température connue.
        trace = {"factor": adj["factor"], "action": adj["action"], "category": adj["category"],
                 "reason": adj["reason"]}
        for key in ("temp_c", "temp_basis", "acclimated", "slot", "dew_point_c"):
            if adj.get(key) is not None:
                trace[key] = adj[key]
        result["trace"] = {"heat_adjustment": trace}
    return result


def slot_temperature(weather: Optional[dict], slot: Optional[str]) -> Tuple[Optional[float], Optional[str]]:
    """Température du créneau depuis un bloc météo : `temp_min_c` pour `morning`,
    `temp_max_c` sinon (borne prudente, voir `arc_heat.ASSUMPTIONS`). Rend
    `(température, note)`."""
    if not weather:
        return None, "aucun fichier météo indexé pour ce jour : fournir --temp-c ou persister la météo"
    tmin, tmax = weather.get("temp_min_c"), weather.get("temp_max_c")
    if slot == "morning" and tmin is not None:
        return tmin, "température du créneau matin = temp_min_c du jour"
    if tmax is not None:
        return tmax, "température = temp_max_c du jour (borne prudente, pas de température horaire)"
    return tmin, "température = temp_min_c du jour (temp_max_c absent)"


# ---------------------------------------------------------------------------
# Analyseur best-effort d'une structure en texte libre — ex. « 6×3 min côte 8 % »
# ---------------------------------------------------------------------------

import re  # noqa: E402

# `6x3min côte 8%`. Volontairement ÉTROIT : un texte qui ne correspond pas à
# ce gabarit (reps x durée ... côte ... grade %) rend `None` plutôt qu'un
# résultat partiel deviné — l'appelant fournit alors `structure` explicitement
# (JSON), ou `--structure-text` (revue de code #107, point 7).
_REPS_RE = re.compile(r"(?P<reps>\d+)\s*[x×]\s*")

# Formats de DURÉE d'un répétitif reconnus, dans cet ordre (le premier qui
# matche au tout début du texte restant, immédiatement après `reps x`,
# l'emporte) — revue de code #107, point 4 :
#   "3 min", "3min", "3 minutes"  -> 180 s
#   "1min30"                       -> 90 s (minutes ET secondes concaténées —
#                                     PAS juste "1 min" en ignorant le "30" :
#                                     bug corrigé ici, silencieusement faux
#                                     avant cette revue)
#   "3'"                            -> 180 s (apostrophe = minutes, notation chrono)
#   "90s", "90\""                   -> 90 s (secondes)
#   "30 sec", "30 secondes"         -> 30 s
_DURATION_RE = re.compile(
    r"""^(?:
        (?P<min>\d+(?:[.,]\d+)?)\s*min(?:ute)?s?\s*(?P<min_sec>\d{1,2})?
      | (?P<apos_min>\d+(?:[.,]\d+)?)\s*'
      | (?P<sec>\d+(?:[.,]\d+)?)\s*(?:sec(?:onde)?s?|s|")
    )""",
    re.IGNORECASE | re.VERBOSE,
)

# Pente cible d'un répétitif de côte : nombre suivi de `%`, immédiatement (au
# plus 10 caractères) après le mot « côte »/« cote ». Exclusion explicite
# (revue de code #107, point 4, BLOQUANT) : un pourcentage suivi de FC/FCmax/
# FCM/VMA est une intensité de FRÉQUENCE CARDIAQUE ou de VITESSE MAXIMALE
# AÉROBIE, jamais une pente — "6x3min côte à 85% FCmax" ne doit PAS rendre un
# grade de 85 %, même quand ce pourcentage suit littéralement le mot « côte ».
_GRADE_RE = re.compile(
    r"c[oô]te.{0,10}?(?P<grade>\d+(?:[.,]\d+)?)\s*%(?!\s*(?:FC(?:max)?|FCM|VMA)\b)",
    re.IGNORECASE,
)

# Pente maximale plausible pour un répétitif de côte routier/trail (revue de
# code #107, point 4) : au-delà, un nombre suivi de `%` accolé à « côte » est
# plus probablement une faute de saisie, une confusion d'unité, ou un
# pourcentage d'intensité non reconnu par `_GRADE_RE` (ex. un gabarit de FC/VMA
# non encore listé) qu'une vraie pente — jamais une structure inventée sur une
# valeur invraisemblable.
MAX_PLAUSIBLE_GRADE_PCT = 40.0


def _parse_duration_s(text: str) -> Optional[float]:
    """Durée (secondes) au tout début de `text` (déjà dépouillé des espaces de
    tête) — voir `_DURATION_RE` pour les gabarits reconnus. `None` si aucun ne
    matche (jamais une durée devinée)."""
    m = _DURATION_RE.match(text.strip())
    if not m:
        return None
    if m.group("min") is not None:
        minutes = float(m.group("min").replace(",", "."))
        seconds = float(m.group("min_sec")) if m.group("min_sec") else 0.0
        return minutes * 60.0 + seconds
    if m.group("apos_min") is not None:
        return float(m.group("apos_min").replace(",", ".")) * 60.0
    return float(m.group("sec").replace(",", "."))


def parse_structure_text(text: Optional[str]) -> Optional[dict]:
    """Best-effort : `"6×3 min côte 8 %"` -> `{"reps": 6, "rep_duration_s": 180,
    "grade_pct": 8.0}` (jamais de `recovery_s`, pas dans ce gabarit). Accepte
    aussi `"6x1min30 côte 8%"` (90 s), `"6x3' côte 8%"`, `"6x90s côte 8%"`,
    `"6x30 sec côte 8%"` — voir `_DURATION_RE`. `None` si `text` ne correspond
    pas, si la pente est accolée à un pourcentage de FC/VMA plutôt qu'une
    pente, ou si la pente dépasse `MAX_PLAUSIBLE_GRADE_PCT` — jamais une
    structure devinée partiellement ou invraisemblable.

    **Ancrage au groupe `reps x durée` le plus proche AVANT la côte** (revue de
    code #107, 2ᵉ tour, should-fix) : un texte comme `"2x20 min tempo, puis
    6x1 min côte 8%"` décrit DEUX blocs (un tempo plat, puis des répétitifs de
    côte) — prendre le PREMIER `reps x durée` du texte (`2x20 min`) rendrait un
    répétitif de côte de 20 minutes, une confusion silencieuse avec le bloc
    tempo qui n'a rien à voir avec la côte. Ce module cherche donc la pente
    D'ABORD, puis retient, parmi TOUS les `reps x durée` qui la PRÉCÈDENT, le
    DERNIER (le plus proche de « côte ») — jamais le premier trouvé dans tout
    le texte. Aucun `reps x durée` valide avant la pente -> `None` (jamais une
    structure devinée depuis un texte ambigu)."""
    if not text:
        return None
    grade_m = _GRADE_RE.search(text)
    if not grade_m:
        return None
    grade = float(grade_m.group("grade").replace(",", "."))
    if grade <= 0 or grade > MAX_PLAUSIBLE_GRADE_PCT:
        return None
    best = None  # (position du groupe "reps x", reps, rep_duration_s)
    for reps_m in _REPS_RE.finditer(text):
        if reps_m.start() >= grade_m.start():
            continue  # un "reps x" APRÈS la côte ne la décrit pas, jamais retenu
        duration_s = _parse_duration_s(text[reps_m.end():])
        if duration_s is None:
            continue
        if best is None or reps_m.start() > best[0]:
            best = (reps_m.start(), int(reps_m.group("reps")), duration_s)
    if best is None:
        return None
    _, reps, duration_s = best
    return {"reps": reps, "rep_duration_s": duration_s, "grade_pct": grade}


# ---------------------------------------------------------------------------
# Validation minimale d'un pas de DTO Garmin (skills/garmin-workout-scheduling)
# ---------------------------------------------------------------------------

_STEP_TYPE_IDS = {1: "warmup", 2: "cooldown", 3: "interval", 4: "recovery", 5: "rest", 6: "repeat"}
_END_CONDITION_IDS = {1: "lap.button", 2: "time", 3: "distance", 7: "iterations", 10: "reps"}
_TARGET_TYPE_IDS = {1: "no.target", 4: "heart.rate.zone", 6: "pace.zone"}


def validate_workout_step_dto(step: dict) -> List[str]:
    """Valide un pas `ExecutableStepDTO` contre le schéma documenté par
    `skills/garmin-workout-scheduling/SKILL.md` — vérification de FORME
    minimale (clés/ids/cohérence), jamais un appel réseau. Rend une liste
    d'erreurs (vide = valide)."""
    errors: List[str] = []
    if step.get("type") != "ExecutableStepDTO":
        errors.append(f"type attendu 'ExecutableStepDTO', reçu {step.get('type')!r}")
    if not isinstance(step.get("stepOrder"), int) or step["stepOrder"] < 1:
        errors.append("stepOrder attendu : entier >= 1")
    step_type = step.get("stepType") or {}
    if step_type.get("stepTypeId") not in _STEP_TYPE_IDS:
        errors.append(f"stepType.stepTypeId inconnu : {step_type.get('stepTypeId')!r}")
    elif step_type.get("stepTypeKey") != _STEP_TYPE_IDS[step_type["stepTypeId"]]:
        errors.append(f"stepType.stepTypeKey incohérent avec stepTypeId {step_type['stepTypeId']}")
    end_cond = step.get("endCondition") or {}
    cond_id = end_cond.get("conditionTypeId")
    if cond_id not in _END_CONDITION_IDS:
        errors.append(f"endCondition.conditionTypeId inconnu : {cond_id!r}")
    elif end_cond.get("conditionTypeKey") != _END_CONDITION_IDS[cond_id]:
        errors.append(f"endCondition.conditionTypeKey incohérent avec conditionTypeId {cond_id}")
    if cond_id != 1 and "endConditionValue" not in step:
        errors.append("endConditionValue manquant (obligatoire sauf endCondition lap.button)")
    target_type = step.get("targetType") or {}
    target_id = target_type.get("workoutTargetTypeId")
    if target_id not in _TARGET_TYPE_IDS:
        errors.append(f"targetType.workoutTargetTypeId inconnu : {target_id!r}")
    elif target_type.get("workoutTargetTypeKey") != _TARGET_TYPE_IDS[target_id]:
        errors.append(f"targetType.workoutTargetTypeKey incohérent avec workoutTargetTypeId {target_id}")
    if target_id == 4:  # heart.rate.zone
        has_zone = "zoneNumber" in step
        has_range = "targetValueOne" in step and "targetValueTwo" in step
        if has_zone == has_range:
            errors.append("cible heart.rate.zone : soit zoneNumber SEUL, soit targetValueOne+targetValueTwo, "
                           "jamais les deux ni aucun")
        elif has_range and step["targetValueOne"] > step["targetValueTwo"]:
            errors.append("heart.rate.zone : targetValueOne (borne basse) doit être <= targetValueTwo "
                           "(borne haute) — jamais une plage FC inversée")
    elif target_id == 6:  # pace.zone
        if "targetValueOne" not in step or "targetValueTwo" not in step:
            errors.append("cible pace.zone : targetValueOne ET targetValueTwo (m/s) attendus")
        elif step["targetValueOne"] > step["targetValueTwo"]:
            errors.append("pace.zone : targetValueOne (vitesse basse = allure lente) doit être <= targetValueTwo "
                           "(vitesse haute = allure rapide)")
    return errors


def dto_hr_step(step_order: int, *, description: str, duration_s: float, bounds_bpm: Sequence[float],
                 step_type_id: int = 3) -> dict:
    """Construit un `ExecutableStepDTO` de durée `duration_s` (secondes) ciblant
    une plage FC personnalisée `bounds_bpm` (`[low, high]`, bpm, arrondis à
    l'entier) — voir docstring du module pour la provenance des unités."""
    step_type_key = _STEP_TYPE_IDS[step_type_id]
    low, high = bounds_bpm
    return {
        "type": "ExecutableStepDTO", "stepOrder": step_order,
        "stepType": {"stepTypeId": step_type_id, "stepTypeKey": step_type_key},
        "description": description,
        "endCondition": {"conditionTypeId": 2, "conditionTypeKey": "time"},
        "endConditionValue": round(duration_s),
        "targetType": {"workoutTargetTypeId": 4, "workoutTargetTypeKey": "heart.rate.zone"},
        "targetValueOne": round(low), "targetValueTwo": round(high),
    }


def dto_pace_step(step_order: int, *, description: str, duration_s: float, speed_low_ms: float,
                   speed_high_ms: float, step_type_id: int = 3) -> dict:
    """Construit un `ExecutableStepDTO` de durée `duration_s` (secondes) ciblant
    une plage d'allure `[speed_low_ms, speed_high_ms]` (m/s — PAS de conversion
    depuis s/km, voir docstring du module)."""
    step_type_key = _STEP_TYPE_IDS[step_type_id]
    return {
        "type": "ExecutableStepDTO", "stepOrder": step_order,
        "stepType": {"stepTypeId": step_type_id, "stepTypeKey": step_type_key},
        "description": description,
        "endCondition": {"conditionTypeId": 2, "conditionTypeKey": "time"},
        "endConditionValue": round(duration_s),
        "targetType": {"workoutTargetTypeId": 6, "workoutTargetTypeKey": "pace.zone"},
        "targetValueOne": speed_low_ms, "targetValueTwo": speed_high_ms,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


_SESSION_SELECTOR_RE = re.compile(
    r"^(?P<date>\d{4}-\d{2}-\d{2})(?:@(?P<index>\d+)|:(?P<title>.+))?$"
)


def _load_session_arg(value: str, workspace: Path) -> Tuple[dict, Optional[dict]]:
    """`--session` : soit un JSON inline (`{"intensity": "endurance", ...}`),
    soit `chemin/vers/Semaine.md#SÉLECTEUR` (une séance du bloc ```arc
    `week.sessions[]` de ce fichier). Un JSON inline commençant par `{` est
    reconnu comme tel MÊME s'il contient un `#` (ex. dans un `title` ou une
    `description` — revue de code #107, nit) : seule une valeur qui ne
    commence PAS par `{` est traitée comme `chemin#sélecteur`.

    `SÉLECTEUR` = `AAAA-MM-JJ` (la date seule, valable seulement si UNE SEULE
    séance porte cette date dans le fichier), `AAAA-MM-JJ@INDEX` (index 0-based
    parmi les séances de cette date, dans l'ORDRE du fichier) ou
    `AAAA-MM-JJ:TITRE` (titre exact). Plusieurs séances à la même date sans
    qualifiant lève une erreur explicite plutôt que de silencieusement
    retourner la première (revue de code #107, point 2, BLOQUANT — un lundi où
    `{{TODAY}} == {{WEEK_START}}`, une séance déjà réalisée ce jour-là et une
    séance encore planifiée ce même jour partagent la même date : prendre « la
    première » aurait pu rendre la MAUVAISE séance, silencieusement, aussi bien
    dans un test que dans un usage réel).

    Rend `(session, source)` — `source` est `None` pour un JSON inline (aucun
    fichier, jamais de semaine à vérifier), sinon `{"path": <chemin relatif au
    workspace si possible>, "week_start": <lundi de la semaine qui porte cette
    séance>}` (#69, revue de code should-fix 5) : `main()` s'en sert pour
    avertir si cette semaine précise est éclipsée par une collision
    (`arc_index.week_collisions`) — un fichier valide au contrat peut quand
    même être ignoré du tableau de bord/des autres CLI pour cette semaine."""
    import json
    if value.lstrip().startswith("{"):
        return json.loads(value), None
    if "#" not in value:
        return json.loads(value), None
    file_part, _, selector = value.rpartition("#")
    m = _SESSION_SELECTOR_RE.match(selector)
    if not m:
        raise ValueError(
            f"--session : sélecteur invalide après '#' : {selector!r} "
            "(attendu AAAA-MM-JJ, AAAA-MM-JJ@index ou AAAA-MM-JJ:titre)")
    date_part, index_part, title_part = m.group("date"), m.group("index"), m.group("title")
    path = Path(file_part)
    if not path.is_absolute():
        path = workspace / path
    text = path.read_text(encoding="utf-8")
    start = text.find("```arc")
    if start == -1:
        raise ValueError(f"{path} : aucun bloc ```arc trouvé")
    start = text.find("\n", start) + 1
    end = text.find("```", start)
    block = json.loads(text[start:end])
    # #69 : un fichier PLAN MULTI-SEMAINES (`weeks[]`) n'a pas de `sessions` au
    # premier niveau — ses séances sont réparties dans `weeks[].sessions`. On les
    # rassemble toutes avant de filtrer par date, chacune associée au
    # `week_start` de SA propre entrée (pour l'avertissement de collision
    # ci-dessus) : le sélecteur reste `AAAA-MM-JJ` (`@index`/`:titre`), inchangé,
    # la bonne semaine étant déjà déterminée par la date de la séance elle-même,
    # jamais par un `week_start` à choisir à part.
    weeks = block.get("weeks")
    if isinstance(weeks, list):
        all_sessions = [(sess, w.get("week_start")) for w in weeks if isinstance(w, dict)
                         for sess in (w.get("sessions") or []) if isinstance(sess, dict)]
    else:
        all_sessions = [(sess, block.get("week_start"))
                         for sess in block.get("sessions", []) if isinstance(sess, dict)]
    try:
        rel_path = str(path.resolve().relative_to(workspace.resolve()).as_posix())
    except ValueError:
        rel_path = str(path)   # hors du workspace (rare, ex. fichier temporaire de test) : chemin tel quel

    def _found(sess: dict, week_start) -> Tuple[dict, dict]:
        return sess, {"path": rel_path, "week_start": week_start}

    candidates = [pair for pair in all_sessions if pair[0].get("date") == date_part]
    if not candidates:
        raise ValueError(f"{path} : aucune séance datée {date_part} dans sessions[]")
    if index_part is not None:
        idx = int(index_part)
        if idx >= len(candidates):
            raise ValueError(
                f"{path} : index @{idx} hors limites pour {date_part} ({len(candidates)} séance(s) à cette date)")
        return _found(*candidates[idx])
    if title_part is not None:
        matches = [pair for pair in candidates if pair[0].get("title") == title_part]
        if not matches:
            raise ValueError(f"{path} : aucune séance datée {date_part} de titre {title_part!r}")
        if len(matches) > 1:
            raise ValueError(
                f"{path} : plusieurs séances datées {date_part} de titre {title_part!r} : ambigu, précisez @index")
        return _found(*matches[0])
    if len(candidates) > 1:
        titles = ", ".join(repr(pair[0].get("title")) for pair in candidates)
        raise ValueError(
            f"{path} : {len(candidates)} séances datées {date_part} ({titles}) : ambigu, précisez "
            f"#{date_part}@index ou #{date_part}:titre")
    return _found(*candidates[0])


def build_arg_parser():
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("command", choices=("targets",))
    ap.add_argument("--session", required=True,
                     help="séance en JSON inline, ou chemin/Semaine.md#SÉLECTEUR "
                          "(AAAA-MM-JJ, AAAA-MM-JJ@index ou AAAA-MM-JJ:titre)")
    ap.add_argument("--structure-text", dest="structure_text",
                     help="texte libre décrivant un répétitif de côte (ex. « 6x3 min côte 8%% »), "
                          "utilisé quand la séance sélectionnée n'a pas de clé structure explicite — "
                          "voir parse_structure_text")
    ap.add_argument("--workspace", help="racine du workspace (défaut : ARC_WORKSPACE, "
                                          "pointeur ~/.config/ai-running-coach/workspace, sinon répertoire courant)")
    ap.add_argument("--db", help="chemin de l'index SQLite (défaut : <workspace>/.arc/coach.db)")
    ap.add_argument("--memory", action="store_true", help="index en mémoire (tests)")
    ap.add_argument("--band", choices=SL.BANDS, default=DEFAULT_BAND,
                     help="bande du modèle pente -> allure (défaut : endurance)")
    ap.add_argument("--today", metavar="AAAA-MM-JJ")
    ap.add_argument("--lt-speed-ms", type=float, dest="lt_speed_ms", metavar="V",
                     help="vitesse (m/s) au seuil lactique Garmin : ajoute `cs_target.threshold_check` "
                          "(divergence signalée avec la CS, jamais arbitrée)")
    ap.add_argument("--heat", action="store_true",
                     help="ajuster les cibles d'allure à la chaleur prévue (#171) : météo du jour de la séance "
                          "lue dans l'index, ou --temp-c")
    ap.add_argument("--temp-c", dest="temp_c", type=float, help="température du créneau (°C), prime sur la météo indexée")
    ap.add_argument("--feels-like-c", dest="feels_like_c", type=float, help="ressenti (°C)")
    ap.add_argument("--humidity-pct", dest="humidity_pct", type=float, help="humidité relative (%%)")
    ap.add_argument("--category", choices=H.WEATHER_ORDER,
                     help="catégorie météo du créneau retenu (green/yellow/orange/red) ; défaut : composantes non thermiques "
                          "(vent/pluie/UV/orage) du fichier météo, la chaleur étant déduite de la température du créneau")
    ap.add_argument("--slot", choices=("morning", "midday", "evening", "none"),
                     help="créneau retenu (défaut : best_slot de la séance, sinon du fichier météo)")
    ap.add_argument("--pace-s-km", dest="pace_s_km", type=float,
                     help="allure cible déclarée (s/km) à ralentir selon la chaleur (séances de qualité)")
    return ap


def _load_weather(conn, day: Optional[str]) -> Tuple[Optional[dict], Optional[str]]:
    """Fichier météo indexé du jour (`weather_day`) ; plusieurs lieux le même
    jour -> `None` + note (jamais un choix arbitraire : fournir --temp-c)."""
    import json
    if not day:
        return None, "séance sans date : météo introuvable"
    rows = [dict(r) for r in conn.execute("SELECT * FROM weather_day WHERE date = ?", (day,)).fetchall()]
    if not rows:
        return None, None
    if len(rows) > 1:
        return None, f"plusieurs fichiers météo le {day} (lieux différents) : fournir --temp-c"
    row = rows[0]
    try:
        extra = json.loads(row.get("data_json") or "{}")
    except ValueError:
        extra = {}
    row["humidity_pct"] = extra.get("humidity_pct")
    row["thunderstorm"] = extra.get("thunderstorm")
    return row, None


def _heat_from_cli(args, conn, conf: dict, session: dict, result: dict) -> None:
    """Résout les entrées de `apply_heat` depuis les options et l'index (météo
    du jour, acclimatation #38, taux de sudation `fueling`)."""
    from datetime import date as _date
    import arc_index as IDX  # noqa: E402
    today = _date.fromisoformat(args.today) if args.today else _date.today()
    weather, wnote = _load_weather(conn, session.get("date"))
    slot = args.slot or session.get("best_slot") or (weather or {}).get("best_slot")
    if args.temp_c is not None:
        temp_c, tnote = args.temp_c, "température fournie par --temp-c"
    else:
        temp_c, tnote = slot_temperature(weather, slot)
    feels = args.feels_like_c
    fnote = None
    if feels is None and (weather or {}).get("feels_like_c") is not None:
        if args.temp_c is None and slot == "morning" and (weather or {}).get("temp_min_c") is not None:
            # Le ressenti du fichier est une valeur JOURNALIÈRE (proche du pic de chaleur) : l'appliquer
            # au créneau matin, évalué sur `temp_min_c`, annulerait le bénéfice du créneau frais.
            fnote = "ressenti du jour non appliqué au créneau matin (valeur journalière, pas celle du créneau)"
        else:
            feels = weather["feels_like_c"]
    humidity = args.humidity_pct if args.humidity_pct is not None else (weather or {}).get("humidity_pct")
    # Catégorie : --category (créneau retenu, évalué par le coach) ; sinon composantes NON thermiques du
    # fichier météo (vent/pluie/UV/orage) — jamais la catégorie « du jour », calculée sur la température
    # max, qui s'appliquerait à tort à un créneau frais (la chaleur est déduite de la température du créneau).
    category = H.worst_category(args.category, H.category_from_other(weather))
    if category is None:
        category = session.get("weather_category")
    temps = [t for t in (temp_c, feels) if t is not None]
    acclimated, anote = H.resolve_acclimated(conn, conf, today, max(temps) if temps else None)
    sweat = IDX.fueling_trend(conn, today).get("median_sweat_rate_l_h")
    apply_heat(result, session, temp_c=temp_c, feels_like_c=feels, humidity_pct=humidity, category=category,
               acclimated=acclimated, slot=slot, sweat_rate_l_h=sweat, declared_pace_s_km=args.pace_s_km)
    notes = result["heat_adjustment"]["notes"]
    for extra in (wnote, tnote, fnote, anote):
        if extra:
            notes.append(extra)


def main(argv: Optional[Sequence[str]] = None) -> int:
    import json
    args = build_arg_parser().parse_args(argv)
    workspace = workspace_root(args.workspace)
    try:
        session, source = _load_session_arg(args.session, workspace)
    except (ValueError, FileNotFoundError, json.JSONDecodeError) as exc:
        print(f"erreur : {exc}", file=sys.stderr)
        return 1

    import arc_index as IDX  # noqa: E402 (import tardif, comme arc_race_pacing)
    conn = IDX.open_db(workspace, args.db, args.memory)
    IDX.index_workspace(conn, workspace, args.today)
    conf = IDX.settings(IDX.load_config(workspace))
    athlete_row = conn.execute("SELECT * FROM athlete LIMIT 1").fetchone()
    athlete = dict(athlete_row) if athlete_row else {}
    report = IDX.slope_model_report(conn, args.band)
    bins = report.get("bins") or []

    # #69, revue de code should-fix 5 : la séance vient d'une semaine ÉCLIPSÉE par
    # une collision de `week_start` (fichier dédié vs plan multi-semaines) — les
    # cibles restent calculées sur son propre contenu, mais un avertissement
    # évite de pousser une séance d'un plan que le tableau de bord/les autres CLI
    # ignorent déjà (voir `arc_index.week_collisions`).
    if source and source.get("week_start"):
        row = conn.execute(
            "SELECT shadowed FROM week WHERE source_path = ? AND week_start = ?",
            (source["path"], source["week_start"])).fetchone()
        if row and row["shadowed"]:
            winner = next((c["winner"] for c in IDX.week_collisions(conn)
                           if c["week_start"] == source["week_start"]), None)
            print(
                f"avertissement : la semaine {source['week_start']} de {source['path']} est "
                f"éclipsée par {winner} (#69, collision de week_start) — le tableau de bord et "
                "les autres CLI ignorent ce fichier pour cette semaine ; les cibles ci-dessous "
                "restent calculées, mais corrigez la collision avant de pousser ce plan.",
                file=sys.stderr)

    # #169 : la CS n'est calculée que pour une intensité qui en a besoin (coût : lecture des échantillons).
    cs_fit = None
    if session.get("intensity") in CS_INTENSITY_PCT:
        today_date = date.fromisoformat(args.today) if args.today else date.today()
        cs_fit = IDX.pace_curve(conn, today_date)["current"] or {}
    result = build_session_targets(session, athlete=athlete, bins=bins,
                                    hr_zones_method=conf.get("hr_zones"), band=args.band,
                                    structure_text=args.structure_text, cs_fit=cs_fit)
    if args.lt_speed_ms is not None and result.get("cs_target") is not None:
        result["cs_target"]["threshold_check"] = CS.compare_threshold(cs_fit, args.lt_speed_ms)
    if args.heat:
        _heat_from_cli(args, conn, conf, session, result)
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
