#!/usr/bin/env python3
"""Identité de montée entre séances (#49, épopée #21) : « même montée » gravie
plusieurs fois, avec progression (temps, VAM, FC) d'une occurrence à l'autre.

## Pourquoi un module dédié, séparé de `arc_climb.py`

`arc_climb.py` (#46) DÉTECTE les montées d'UNE séance (bornes, gain, VAM) — il ne sait
rien des autres séances. Ce module RÉUTILISE ses montées détectées telles quelles (voir
`arc_climb.ASSUMPTIONS`, note de #49 : « #49 pourra réutiliser `detect_climbs`/
`climb_report` tels quels plutôt que réinventer une quatrième détection ») et ajoute la
couche suivante : reconnaître qu'une montée détectée sur la séance du jour est LA MÊME
que celle détectée sur une séance précédente, malgré de petites variations de trace
(bruit GPS/altimétrique, bornes qui glissent — voir `arc_climb.ASSUMPTIONS["trim"]`).

## Deux méthodes d'appariement — GPS d'abord, repli sans GPS ensuite

**Avec GPS** (positions de départ/sommet connues des deux côtés, `arc_samples.GPS_KEYS`,
#49) : deux montées sont LA MÊME si leur point de départ ET leur sommet sont chacun à
moins de `CLIMB_MATCH_POSITION_TOLERANCE_M` l'un de l'autre (`haversine_m`), ET que leur
profil (gain, longueur) reste proche (`_profile_close`). Comparer le DÉPART au départ et
le SOMMET au sommet (jamais départ↔sommet ou l'inverse) est ce qui exclut naturellement
une même trace parcourue en SENS INVERSE : `arc_climb.detect_climbs` ne détecte que des
montées (gain net positif) — descendre un versant précédemment gravi n'y apparaît jamais
comme une « montée » à apparier, et gravir l'AUTRE versant d'un aller-retour a un départ
proche du sommet enregistré (et réciproquement) : aucune des deux comparaisons dans le
bon sens ne passe, donc aucun appariement — un nouveau segment distinct est créé, ce qui
est le comportement voulu (monter par l'autre face n'est pas « la même montée »).

**Sans GPS** (repli, séance sans échantillons FIT géolocalisés — la quasi-totalité du
parc actuel, voir `arc_samples.ASSUMPTIONS["gps"]`) : appariement sur le LIEU (`location`
du bloc ```arc```, comparaison exacte après normalisation casse/espaces) ET la
« signature » de profil (gain, longueur, classe de pente) — voir ASSUMPTIONS["fallback"]
pour ses limites assumées, documentées honnêtement plutôt que cachées : sans géométrie,
impossible de distinguer une montée d'un aller-retour parcouru en sens inverse (le
« repli » ne détecte alors JAMAIS ce cas, contrairement au chemin GPS) ni deux montées
distinctes mais de profil proche au même lieu déclaré (ex. deux sentiers voisins sur la
même montagne) — le repli est donc délibérément CONSERVATEUR : toute ambiguïté (plusieurs
segments existants satisfont à la fois lieu et profil) annule l'appariement plutôt que de
deviner, préférant un doublon de segment (progression perdue une fois) à un faux
rapprochement (progression fausse, potentiellement pour toujours).

## Passage à l'échelle — bucketing spatial, jamais un balayage complet

`ClimbSegmentIndex` n'compare jamais une montée candidate à TOUS les segments connus : un
quadrillage grossier (`GRID_CELL_DEG`, la position de départ arrondie à la cellule, plus
les 8 cellules voisines pour ne jamais rater un segment proche d'un bord de cellule) sert
de clé de recherche côté GPS, un lieu normalisé côté repli — voir `ClimbSegmentIndex._candidates`.
Coût par montée candidate : O(nombre de segments dans quelques cellules/ce lieu), pas
O(nombre total de segments du workspace) — voir ASSUMPTIONS["bucketing"] pour la mesure.

## FC × dénivelé — dérive au sein d'une montée

`hr_drift_bpm_per_100m` (critère d'acceptation de #49) : FC moyenne du DERNIER tiers
temporel de la montée moins FC moyenne du PREMIER tiers, divisée par le gain (m) / 100 —
même découpage « tiers temporels » que `arc_durability.durability_report_from_series`
(cohérence des KPI dérivés). Voir ASSUMPTIONS["hr_drift"] pour la définition complète et
son honnêteté (dérive de dérive cardiaque, pas de « décrochage » au sens Pa:HR/#45).

## Confidentialité — jamais une coordonnée brute hors de ce module

Les positions GPS (`lat_deg`/`lon_deg`) ne servent QU'à comparer deux montées entre elles,
en mémoire, dans ce module : aucune fonction ici ne rend une coordonnée dans son résultat
public (`ClimbSegmentIndex.add`/`match` gardent les positions en interne pour les
comparaisons futures, mais `arc_index.py`/`arc_serve.py` n'exposent jamais ces champs par
l'API ou le CLI — voir ASSUMPTIONS["privacy"]).

Stdlib uniquement (CONTRIBUTING.md).
"""

from __future__ import annotations

import math
from typing import Dict, List, Optional, Sequence, Tuple

# Tolérance de position (#49, critère d'acceptation : « robuste aux petites variations de
# trace ») : englobe le bruit GPS ordinaire (quelques dizaines de mètres) ET le glissement
# de bord documenté par #46 à fort bruit altimétrique (`arc_climb.ASSUMPTIONS["trim"]`,
# « le début mesuré d'une montée peut occasionnellement glisser de quelques dizaines de
# mètres sur une approche plate malgré le rognage adaptatif ») — valeur ronde au milieu de
# la fourchette 100-150 m suggérée par #49, pas calibrée sur un jeu de traces étiquetées.
CLIMB_MATCH_POSITION_TOLERANCE_M = 150.0

# Tolérance de profil (gain, longueur) — le plus GRAND d'un plancher absolu et d'une
# fraction relative, même discipline que `arc_climb.MERGE_MAX_DIP_LOSS_M`/
# `MERGE_DIP_RELATIVE_FRAC` (#46) : un plancher purement relatif serait trop strict sur une
# petite montée, un plancher purement absolu trop laxiste sur une montée alpine.
CLIMB_MATCH_GAIN_TOLERANCE_FRAC = 0.20
CLIMB_MATCH_GAIN_TOLERANCE_FLOOR_M = 15.0
CLIMB_MATCH_LENGTH_TOLERANCE_FRAC = 0.25
CLIMB_MATCH_LENGTH_TOLERANCE_FLOOR_M = 150.0

# Taille de cellule du quadrillage spatial — délibérément PLUS GRANDE que
# `CLIMB_MATCH_POSITION_TOLERANCE_M` (≈550 m à l'équateur contre 150 m de tolérance) :
# la recherche examine la cellule du candidat ET ses 8 voisines (`_grid_cells`), ce qui
# couvre toujours un rayon d'au moins une cellule autour du candidat — largement assez
# pour ne jamais rater un segment à moins de `CLIMB_MATCH_POSITION_TOLERANCE_M`, y compris
# tout près d'un bord de cellule.
GRID_CELL_DEG = 0.005

EARTH_RADIUS_M = 6371000.0

ASSUMPTIONS = {
    "reuse": (
        "Ce module réutilise `arc_climb.detect_climbs` tel quel (montées déjà détectées, "
        "bornes/gain/VAM déjà calculés) : il n'implémente AUCUNE détection de montée, "
        "uniquement l'appariement entre séances et les métriques de progression — voir la "
        "note de #46, ASSUMPTIONS['merge'], dernière phrase."
    ),
    "gps_matching": (
        "Avec position de départ ET de sommet connues des deux côtés : appariement si "
        f"`haversine_m(départs) <= {CLIMB_MATCH_POSITION_TOLERANCE_M:.0f} m` ET "
        f"`haversine_m(sommets) <= {CLIMB_MATCH_POSITION_TOLERANCE_M:.0f} m` ET profil "
        "proche (gain/longueur, voir `_profile_close`) — comparaison APPARIÉE (départ à "
        "départ, sommet à sommet), jamais croisée : c'est ce qui exclut une même trace "
        "parcourue en sens inverse (voir docstring du module). Quand plusieurs segments "
        "connus satisfont ce critère (rare, deux montées très proches), celui dont la "
        "somme des deux distances est la plus petite est retenu."
    ),
    "fallback_matching": (
        "Sans position exploitable d'un des deux côtés : appariement par LIEU (`location`, "
        "normalisé casse/espaces, comparaison EXACTE — jamais une distance textuelle "
        "floue) ET profil proche (gain, longueur, ET classe de pente — un critère "
        "supplémentaire par rapport au chemin GPS, pour compenser l'absence de géométrie). "
        "DÉLIBÉRÉMENT CONSERVATEUR (#49, critère d'acceptation « comportement documenté ») : "
        "si plusieurs segments déjà connus au même lieu satisfont le profil, AUCUN n'est "
        "retenu (ambiguïté) plutôt qu'un choix arbitraire — un nouveau segment distinct est "
        "créé, au prix d'une progression non détectée une fois, jamais au prix d'un "
        "rapprochement erroné. LIMITE ASSUMÉE, honnêtement documentée : sans géométrie, ce "
        "repli ne peut PAS détecter une même trace parcourue en sens inverse (aucune notion "
        "de départ/sommet géographique à comparer) — une montée et la descente symétrique "
        "d'un aller-retour, si un jour toutes deux dépassaient le seuil de détection dans "
        "les deux sens (rare : l'une des deux est presque toujours une descente au sens de "
        "`arc_climb.detect_climbs`), pourraient être confondues à tort. Ce cas n'a pas de "
        "solution sans coordonnées : documenté plutôt que caché."
    ),
    "bucketing": (
        "`ClimbSegmentIndex` n'examine jamais l'ensemble des segments connus : un "
        f"quadrillage de {GRID_CELL_DEG:.3f}° (`_grid_cells`, cellule du candidat + ses 8 "
        "voisines) restreint la recherche aux segments GÉOGRAPHIQUEMENT PROCHES côté GPS ; "
        "un dictionnaire par lieu normalisé restreint la recherche au même lieu côté "
        "repli. Coût par montée candidate proportionnel au nombre de segments DANS CES "
        "quelques cellules/ce lieu, pas au nombre total de segments du workspace — "
        "`tests/data/test_arc_climb_match.py::TestPerformance` mesure ce coût sur un grand "
        "nombre de lieux distincts."
    ),
    "direction": (
        "Une montée gravie dans l'autre sens (sommet→départ) n'est PAS une descente au "
        "sens de `arc_climb.detect_climbs` que sur le même GPX — parcourir la MÊME trace "
        "en sens inverse produit une VRAIE montée détectée (gain net positif, l'autre "
        "sens), mais avec un départ proche de l'ancien SOMMET et un sommet proche de "
        "l'ancien DÉPART : la comparaison appariée (voir ASSUMPTIONS['gps_matching']) ne "
        "matche ni dans un sens ni dans l'autre, donc un nouveau segment distinct est créé "
        "— comportement voulu (#49, critère d'acceptation « la descendre n'est pas la même "
        "montée — ascension uniquement »)."
    ),
    "hr_drift": (
        "`hr_drift_bpm_per_100m` = (FC moyenne du DERNIER tiers temporel de la montée − FC "
        "moyenne du PREMIER tiers temporel) / (gain_m / 100) — même découpage en tiers "
        "temporels que `arc_durability.durability_report_from_series` (#48, cohérence des "
        "KPI dérivés d'une même séance). Une valeur POSITIVE signifie que la FC dérive VERS "
        "LE HAUT au fil de la montée (fatigue/chaleur/pente qui s'accentue) pour un même "
        "effort perçu ; ce n'est PAS le découplage Pa:HR de #45 (qui compare la puissance/"
        "l'allure à la FC), ici seule la FC elle-même est suivie le long d'une SEULE "
        "montée. `None` (avec `reason`) si le gain est trop faible pour que la division par "
        "100 m reste significative (< 20 m — sous ce seuil, une petite dérive de FC produit "
        "une valeur par 100 m démesurée) ou si la FC manque sur l'un des deux tiers."
    ),
    "progression": (
        "`vs_previous_pct`/`vs_best_pct` (critère d'acceptation de #49 : « deuxième "
        "occurrence 5 % plus rapide → affiché ») comparent le temps ÉCOULÉ "
        "(`duration_elapsed_s`, jamais le temps de mouvement — la question de l'athlète est "
        "« ai-je mis moins de temps », arrêts compris, même discipline que "
        "`arc_climb.ASSUMPTIONS['vam_basis']` pour la VAM mise en avant) de l'occurrence "
        "COURANTE à celui de l'occurrence PRÉCÉDENTE (`vs_previous_pct`) et à la MEILLEURE "
        "occurrence ANTÉRIEURE (`vs_best_pct`, jamais la courante elle-même) du même "
        "segment. Positif = plus rapide (temps réduit). `None` pour la toute première "
        "occurrence d'un segment (rien à comparer)."
    ),
    "privacy": (
        "Les positions GPS ne quittent jamais ce module ni la base dérivée locale "
        "(`.arc/coach.db`, jamais versionnée) : `arc_index.py` les stocke pour "
        "l'appariement (mêmes colonnes `lat`/`lon` réservées par #42) mais aucune route de "
        "`arc_serve.py` ni sortie du CLI `climb-history` ne les inclut — seuls un "
        "`segment_id` (identifiant opaque) et le `location` déjà déclaré par l'athlète dans "
        "le Markdown de la séance (jamais une coordonnée) sont exposés."
    ),
}


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distance en mètres entre deux points (degrés décimaux) — formule standard de la
    haversine, précision largement suffisante (~m) pour une tolérance d'appariement de
    l'ordre de la centaine de mètres."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(min(1.0, math.sqrt(a)))


def climb_endpoints(act_samples: Sequence[dict], climb: dict) -> Optional[dict]:
    """Position de départ et de sommet d'une montée détectée (`arc_climb.detect_climbs`),
    à partir des échantillons de l'activité (`t_s`, `lat_deg`, `lon_deg`) — `None` si l'un
    des deux (départ ou sommet) n'a aucune position exploitable dans la fenêtre de la
    montée (séance sans GPS, ou trou de signal GPS aux deux bornes)."""
    window = [s for s in act_samples
              if s.get("t_s") is not None and climb["start_t_s"] <= s["t_s"] <= climb["end_t_s"]]
    if not window:
        return None
    ordered = sorted(window, key=lambda s: s["t_s"])
    start = next((s for s in ordered if s.get("lat_deg") is not None and s.get("lon_deg") is not None), None)
    end = next((s for s in reversed(ordered) if s.get("lat_deg") is not None and s.get("lon_deg") is not None), None)
    if start is None or end is None:
        return None
    return {"start_lat": start["lat_deg"], "start_lon": start["lon_deg"],
            "end_lat": end["lat_deg"], "end_lon": end["lon_deg"]}


def hr_drift_bpm_per_100m(act_samples: Sequence[dict], climb: dict) -> dict:
    """Voir ASSUMPTIONS["hr_drift"]. Rend TOUJOURS `{'hr_first_third_bpm',
    'hr_last_third_bpm', 'hr_drift_bpm_per_100m'}` — `None` partout avec `None` si le gain
    est trop faible ou la FC insuffisante, jamais une exception."""
    empty = {"hr_first_third_bpm": None, "hr_last_third_bpm": None, "hr_drift_bpm_per_100m": None}
    gain = climb.get("gain_m")
    if gain is None or gain < 20.0:
        return empty
    window = [s for s in act_samples
              if s.get("t_s") is not None and climb["start_t_s"] <= s["t_s"] <= climb["end_t_s"]]
    if len(window) < 2:
        return empty
    ordered = sorted(window, key=lambda s: s["t_s"])
    t0, t1 = ordered[0]["t_s"], ordered[-1]["t_s"]
    span = t1 - t0
    if span <= 0:
        return empty
    third = span / 3.0
    first = [s["hr_bpm"] for s in ordered if s["t_s"] <= t0 + third and s.get("hr_bpm") is not None]
    last = [s["hr_bpm"] for s in ordered if s["t_s"] >= t1 - third and s.get("hr_bpm") is not None]
    if not first or not last:
        return empty
    hr_first = sum(first) / len(first)
    hr_last = sum(last) / len(last)
    drift = (hr_last - hr_first) / (gain / 100.0)
    return {"hr_first_third_bpm": round(hr_first, 1), "hr_last_third_bpm": round(hr_last, 1),
            "hr_drift_bpm_per_100m": round(drift, 2)}


def _norm_location(location: Optional[str]) -> Optional[str]:
    if not location:
        return None
    norm = " ".join(location.strip().lower().split())
    return norm or None


def _close(a: Optional[float], b: Optional[float], frac: float, floor: float) -> bool:
    if a is None or b is None:
        return False
    tol = max(floor, frac * max(abs(a), abs(b)))
    return abs(a - b) <= tol


def _profile_close(candidate: dict, segment: dict, *, require_grade_class: bool = False) -> bool:
    if not _close(candidate.get("gain_m"), segment.get("gain_m"),
                  CLIMB_MATCH_GAIN_TOLERANCE_FRAC, CLIMB_MATCH_GAIN_TOLERANCE_FLOOR_M):
        return False
    if not _close(candidate.get("distance_m"), segment.get("distance_m"),
                  CLIMB_MATCH_LENGTH_TOLERANCE_FRAC, CLIMB_MATCH_LENGTH_TOLERANCE_FLOOR_M):
        return False
    if require_grade_class and candidate.get("grade_class") != segment.get("grade_class"):
        return False
    return True


class ClimbSegmentIndex:
    """Registre en mémoire des `climb_segment` connus, avec appariement bucketé (voir
    ASSUMPTIONS["bucketing"]) — reconstruit à chaque `compute_metrics` (même discipline
    que les autres tables dérivées intégralement recalculées, `arc_index.compute_metrics`),
    jamais persisté tel quel entre deux exécutions : les LIGNES `climb_segment` le sont,
    en SQLite, par l'appelant."""

    def __init__(self) -> None:
        self.segments: List[dict] = []
        self._by_grid: Dict[Tuple[int, int], List[int]] = {}
        self._by_location: Dict[str, List[int]] = {}

    def _grid_cells(self, lat: float, lon: float) -> List[Tuple[int, int]]:
        cx = math.floor(lat / GRID_CELL_DEG)
        cy = math.floor(lon / GRID_CELL_DEG)
        return [(cx + dx, cy + dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1)]

    def _candidate_indices(self, candidate: dict) -> List[int]:
        if candidate.get("start_lat") is not None and candidate.get("start_lon") is not None:
            seen: List[int] = []
            for key in self._grid_cells(candidate["start_lat"], candidate["start_lon"]):
                for i in self._by_grid.get(key, []):
                    if i not in seen:
                        seen.append(i)
            return seen
        loc = _norm_location(candidate.get("location"))
        if loc is None:
            return []
        return list(self._by_location.get(loc, []))

    def match(self, candidate: dict) -> Optional[dict]:
        """Rend le segment déjà connu qui correspond le mieux à `candidate`, ou `None` —
        voir ASSUMPTIONS["gps_matching"]/["fallback_matching"]. `candidate` : "
        `{'start_lat','start_lon','end_lat','end_lon','gain_m','distance_m','grade_class','location'}`
        (positions à `None` si inconnues)."""
        has_gps = all(candidate.get(k) is not None for k in ("start_lat", "start_lon", "end_lat", "end_lon"))
        indices = self._candidate_indices(candidate)
        if has_gps:
            best, best_score = None, None
            for i in indices:
                seg = self.segments[i]
                if seg.get("start_lat") is None or seg.get("summit_lat") is None:
                    continue  # segment sans position connue : incomparable côté GPS (ASSUMPTIONS)
                d_start = haversine_m(candidate["start_lat"], candidate["start_lon"],
                                       seg["start_lat"], seg["start_lon"])
                d_summit = haversine_m(candidate["end_lat"], candidate["end_lon"],
                                        seg["summit_lat"], seg["summit_lon"])
                if d_start > CLIMB_MATCH_POSITION_TOLERANCE_M or d_summit > CLIMB_MATCH_POSITION_TOLERANCE_M:
                    continue
                if not _profile_close(candidate, seg):
                    continue
                score = d_start + d_summit
                if best is None or score < best_score:
                    best, best_score = seg, score
            return best
        # Repli sans GPS (ASSUMPTIONS["fallback_matching"]) : conservateur, une ambiguïté
        # (plusieurs segments du même lieu au profil proche) annule le match.
        matches = [self.segments[i] for i in indices
                   if _profile_close(candidate, self.segments[i], require_grade_class=True)]
        return matches[0] if len(matches) == 1 else None

    def add(self, candidate: dict) -> dict:
        """Enregistre `candidate` comme un NOUVEAU segment (aucun appariement trouvé) et le
        rend, `id` (1-based, interne à CETTE passe — l'appelant SQLite lui donne son id
        définitif de ligne) inclus."""
        segment = {
            "id": len(self.segments) + 1,
            "start_lat": candidate.get("start_lat"), "start_lon": candidate.get("start_lon"),
            "summit_lat": candidate.get("end_lat"), "summit_lon": candidate.get("end_lon"),
            "gain_m": candidate.get("gain_m"), "distance_m": candidate.get("distance_m"),
            "avg_grade": candidate.get("avg_grade"), "grade_class": candidate.get("grade_class"),
            "location": candidate.get("location"),
        }
        idx = len(self.segments)
        self.segments.append(segment)
        if segment["start_lat"] is not None and segment["start_lon"] is not None:
            for key in self._grid_cells(segment["start_lat"], segment["start_lon"]):
                self._by_grid.setdefault(key, []).append(idx)
        loc = _norm_location(segment["location"])
        if loc is not None:
            self._by_location.setdefault(loc, []).append(idx)
        return segment


def progression_pct(previous_time_elapsed_s: Optional[float], current_time_elapsed_s: Optional[float]) -> Optional[float]:
    """Voir ASSUMPTIONS["progression"]. Positif = l'occurrence courante est plus RAPIDE.
    `None` si l'une des deux durées manque ou que la durée de référence est nulle."""
    if previous_time_elapsed_s is None or current_time_elapsed_s is None or previous_time_elapsed_s <= 0:
        return None
    return round((previous_time_elapsed_s - current_time_elapsed_s) / previous_time_elapsed_s * 100.0, 1)
