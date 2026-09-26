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

## Deux méthodes d'appariement — GPS d'abord, repli sans GPS ensuite (+ adoption)

**Avec GPS** (positions de départ/sommet connues des deux côtés, `arc_samples.GPS_KEYS`,
#49) : deux montées sont LA MÊME si leur point de départ ET leur sommet sont chacun à
moins d'une tolérance qui s'élargit avec la longueur de la montée (`_position_tolerance_m`,
voir ASSUMPTIONS["gps_matching"] pour les taux mesurés qui justifient cette mise à
l'échelle) l'un de l'autre (`haversine_m`), ET que leur profil (gain, longueur) reste
proche (`_profile_close`). Comparer le DÉPART au départ et le SOMMET au sommet (jamais
départ↔sommet ou l'inverse) est ce qui exclut naturellement une même trace parcourue en
SENS INVERSE : `arc_climb.detect_climbs` ne détecte que des montées (gain net positif) —
descendre un versant précédemment gravi n'y apparaît jamais comme une « montée » à
apparier, et gravir l'AUTRE versant d'un aller-retour a un départ proche du sommet
enregistré (et réciproquement) : aucune des deux comparaisons dans le bon sens ne passe,
donc aucun appariement — un nouveau segment distinct est créé, ce qui est le comportement
voulu (monter par l'autre face n'est pas « la même montée »).

**Sans GPS** (repli, séance sans échantillons FIT géolocalisés — la quasi-totalité du
parc actuel, voir `arc_samples.ASSUMPTIONS["gps"]`) : appariement sur le LIEU (`location`
du bloc ```arc```, comparaison exacte après normalisation casse/espaces) ET la
« signature » de profil (gain, longueur, classe de pente) — voir ASSUMPTIONS["fallback_matching"]
pour ses limites assumées, documentées honnêtement plutôt que cachées : sans géométrie,
impossible de distinguer une montée d'un aller-retour parcouru en sens inverse (le
« repli » ne détecte alors JAMAIS ce cas, contrairement au chemin GPS) ni deux montées
distinctes mais de profil proche au même lieu déclaré (ex. deux sentiers voisins sur la
même montagne) — le repli est donc délibérément CONSERVATEUR : toute ambiguïté (plusieurs
segments existants satisfont à la fois lieu et profil) annule l'appariement plutôt que de
deviner, préférant un doublon de segment (progression perdue une fois) à un faux
rapprochement (progression fausse, potentiellement pour toujours).

**Adoption** (ce même repli, utilisé en dernier recours) : un candidat AVEC GPS qui ne
trouve aucun segment GPS compatible retente le repli par lieu, restreint aux segments SANS
position connue — un segment créé sans GPS par sa toute première occurrence (le cas
largement majoritaire sur un workspace existant avant #49) peut ainsi être retrouvé par une
occurrence ULTÉRIEURE avec GPS, qui lui fournit alors sa position pour la suite. Sans cette
adoption, la quasi-totalité des historiques de montée d'un workspace existant se
scinderaient artificiellement en deux segments à la première occurrence géolocalisée.

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
# trace ») — PLANCHER absolu, voir `_position_tolerance_m` ci-dessous pour la mise à
# l'échelle sur la longueur de la montée (revue de code #49, BLOQUANT) : un plancher fixe
# seul s'est révélé insuffisant sur une montée longue à fort bruit altimétrique — mesuré
# (`tests/data/test_arc_climb_match.py::TestPositionToleranceScalesWithClimbLength`, montée
# de 3 560 m/300 m, 200 paires de tirages indépendants) : à σ ≈ 2 m de bruit résiduel après
# lissage, un plancher fixe de 150 m n'appariait que 184/200 paires (glissement de sommet
# mesuré jusqu'à 256 m) ; à σ ≈ 4 m, seulement 100/200 (glissement jusqu'à 290 m). La mise à
# l'échelle ci-dessous (`_position_tolerance_m`) apparie 200/200 aux deux niveaux de bruit
# sur ce même jeu de mesures — voir ASSUMPTIONS["gps_matching"] pour la valeur relative
# retenue et son raisonnement.
CLIMB_MATCH_POSITION_TOLERANCE_M = 150.0

# Fraction de la longueur de la montée ajoutée au plancher ci-dessus (revue de code #49,
# BLOQUANT) : un glissement de bord (`arc_climb.ASSUMPTIONS["trim"]`) déplace le début/la
# fin MESURÉS d'une montée d'une quantité qui croît avec le bruit ET, à bruit égal, avec la
# longueur de la montée (un rognage à noise_tol_m fixe représente une fraction plus grande
# d'une petite montée) — un plancher fixe seul sous-estime donc le glissement possible sur
# une longue montée.
CLIMB_MATCH_POSITION_TOLERANCE_FRAC = 0.08

# PLAFOND de la tolérance mise à l'échelle ci-dessus (2e revue de code #49, BLOQUANT — should-
# fix) : SANS plafond, deux montées longues mais DISTINCTES (ex. deux montées de 5 km partant
# du même fond de vallée, sommets à ~500 m l'un de l'autre — ou deux montées de 20 km à
# 1,5 km d'écart) tombaient dans une tolérance devenue trop généreuse (8 % de 5 km = 400 m,
# 8 % de 20 km = 1,6 km) et fusionnaient à tort en un seul segment (fausse progression). Le
# plafond garde la tolérance sous la portée RÉELLE du quadrillage spatial (`GRID_CELL_DEG`,
# voisinage 3×3 ≈ 1,1-1,7 km selon la latitude — un plafond ≥ à cette portée risquerait de
# rater un vrai appariement dont la recherche par cellule n'aurait de toute façon pas ramené
# le candidat) ET reste au-dessus du pire glissement mesuré (`CLIMB_MATCH_POSITION_TOLERANCE_M`,
# jusqu'à 290 m à σ ≈ 4 m) avec une marge confortable.
CLIMB_MATCH_POSITION_TOLERANCE_CAP_M = 300.0

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

# Identifiant déterministe d'un segment (revue de code #49, BLOQUANT) : dérivé du
# `garmin_activity_id` ET de l'index (1-based) de la montée AU SEIN de cette activité — pas
# d'un compteur séquentiel (voir ASSUMPTIONS["segment_id"]). Marge large (une activité ne
# détecte jamais des milliers de montées : gain minimal 50 m, `arc_climb.MIN_CLIMB_GAIN_M`).
SEGMENT_ID_CLIMB_MULTIPLIER = 10_000

ASSUMPTIONS = {
    "reuse": (
        "Ce module réutilise `arc_climb.detect_climbs` tel quel (montées déjà détectées, "
        "bornes/gain/VAM déjà calculés) : il n'implémente AUCUNE détection de montée, "
        "uniquement l'appariement entre séances et les métriques de progression — voir la "
        "note de #46, ASSUMPTIONS['merge'], dernière phrase."
    ),
    "gps_matching": (
        "Avec position de départ ET de sommet connues des deux côtés : appariement si "
        "`haversine_m(départs) <= tol` ET `haversine_m(sommets) <= tol` ET (quand connu des "
        "deux côtés) `haversine_m(mi-parcours) <= tol` ET profil proche (gain/longueur, voir "
        "`_profile_close`), où `tol = _position_tolerance_m(...)` = le plus GRAND de "
        f"`CLIMB_MATCH_POSITION_TOLERANCE_M` ({CLIMB_MATCH_POSITION_TOLERANCE_M:.0f} m, "
        f"plancher) et `CLIMB_MATCH_POSITION_TOLERANCE_FRAC` ({CLIMB_MATCH_POSITION_TOLERANCE_FRAC * 100:.0f} %) "
        "× la longueur de la montée, PLAFONNÉ à `CLIMB_MATCH_POSITION_TOLERANCE_CAP_M` "
        f"({CLIMB_MATCH_POSITION_TOLERANCE_CAP_M:.0f} m) — voir le commentaire de ces trois "
        "constantes pour la mesure qui justifie la mise à l'échelle (un plancher fixe seul "
        "est insuffisant sur une longue montée à fort bruit) ET le plafond (2e revue de code "
        "#49, BLOQUANT : SANS lui, deux montées longues mais DISTINCTES — ex. deux montées "
        "de 5 km depuis le même fond de vallée vers des sommets à ~500 m l'un de l'autre, ou "
        "deux montées de 20 km à 1,5 km d'écart — fusionnaient à tort en un seul segment, "
        "produisant une fausse progression). Le CONTRÔLE DE MI-PARCOURS (même revue, "
        "BLOQUANT) complète le plafond : deux montées peuvent avoir un départ ET un sommet "
        "chacun sous tolérance sans être la même montée si leurs itinéraires divergent au "
        "milieu — la position à 50 % de la distance parcourue (`climb_endpoints`) doit AUSSI "
        "être sous tolérance quand elle est connue des deux côtés (jamais un rejet sur la "
        "seule absence ponctuelle de cette position — trou de signal possible exactement au "
        "milieu). Comparaison APPARIÉE (départ à départ, sommet à sommet, milieu à milieu), "
        "jamais croisée : c'est ce qui exclut une même trace parcourue en sens inverse (voir "
        "docstring du module et ASSUMPTIONS['direction']). Quand plusieurs segments connus "
        "satisfont ce critère (rare, deux montées très proches), celui dont la somme des "
        "deux distances (départ + sommet) est la plus petite est retenu. Un candidat GPS qui "
        "ne trouve AUCUN segment GPS compatible retente ensuite le repli sans GPS, restreint "
        "aux segments SANS position connue (voir ASSUMPTIONS['fallback_matching'], "
        "« adoption ») — sans quoi un segment créé par une toute première occurrence sans "
        "GPS ne pourrait plus jamais être retrouvé par une occurrence ultérieure AVEC GPS "
        "(revue de code #49, BLOQUANT : la quasi-totalité du parc existant avant #49 n'a "
        "aucune position enregistrée, voir `arc_samples.ASSUMPTIONS['gps']`)."
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
        "solution sans coordonnées : documenté plutôt que caché.\n\n"
        "ADOPTION (revue de code #49, BLOQUANT — corrige une asymétrie qui aurait scindé "
        "l'historique de PRESQUE TOUTES les montées existantes à la transition GPS) : ce "
        "même repli sert aussi de dernier recours pour un CANDIDAT AVEC GPS qui n'a trouvé "
        "aucun segment GPS compatible (voir ASSUMPTIONS['gps_matching']), restreint aux "
        "segments SANS position connue (jamais à un segment déjà positionné : deux positions "
        "connues et incompatibles ne doivent jamais être ignorées au profit du lieu seul) — "
        "même règle « exactement un candidat, sinon aucun ». En cas d'appariement, le "
        "segment ADOPTE la position du candidat (départ/sommet/mi-parcours) et rejoint le "
        "quadrillage spatial : les occurrences GPS suivantes le retrouveront directement, "
        "sans repasser par ce repli. L'adoption est journalisée (`ClimbSegmentIndex."
        "_adoptions`) pour que `rollback` puisse la défaire (restaurer l'ABSENCE de "
        "position, retirer les entrées du quadrillage) si l'activité qui l'a déclenchée "
        "échoue ensuite — sans ce journal, un `rollback` (voir `mark`/`rollback`) qui ne "
        "faisait que tronquer `self.segments` ratait totalement une adoption, celle-ci "
        "mutant un segment PLUS ANCIEN que le point de reprise, jamais un segment "
        "nouvellement ajouté (2e revue de code #49, BLOQUANT)."
    ),
    "segment_id": (
        "`climb_segment.id` (#49, revue de code, BLOQUANT) = "
        "`garmin_activity_id_de_la_première_occurrence × SEGMENT_ID_CLIMB_MULTIPLIER + "
        "index_de_la_montée_dans_cette_activité` (1-based, `arc_climb.detect_climbs` "
        "l'attribue déjà) — JAMAIS un compteur séquentiel assigné dans l'ordre de "
        "traitement des activités (bug corrigé : avec un compteur, indexer une activité "
        "plus ANCIENNE que celles déjà connues décalait l'id de TOUS les segments créés "
        "après elle dans l'ordre chronologique, même sans aucun rapport avec la nouvelle "
        "activité — un lien `#/montee/<id>`/une URL d'API mémorisée pointait alors "
        "silencieusement vers une autre montée après la prochaine indexation). Le "
        "`garmin_activity_id`/index de la PREMIÈRE occurrence effectivement rencontrée peut "
        "changer si une occurrence encore plus ancienne du même segment est découverte plus "
        "tard (un vrai « premier vu » plus ancien change légitimement l'identité), mais "
        "cela n'affecte alors QUE ce segment précis, jamais les autres."
    ),
    "bucketing": (
        "`ClimbSegmentIndex` n'examine jamais l'ensemble des segments connus : un "
        f"quadrillage de {GRID_CELL_DEG:.3f}° (`_grid_cells`, cellule du candidat + ses 8 "
        "voisines) restreint la recherche aux segments GÉOGRAPHIQUEMENT PROCHES côté GPS ; "
        "un dictionnaire par lieu normalisé restreint la recherche au même lieu côté "
        "repli. Coût par montée candidate proportionnel au nombre de segments DANS CES "
        "quelques cellules/ce lieu, pas au nombre total de segments du workspace — "
        "`tests/data/test_arc_climb_match.py::TestBucketingIsNotQuadratic` mesure ce coût "
        "sur un grand nombre de lieux distincts."
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
        "occurrence d'un segment (rien à comparer). Un équivalent en temps de MOUVEMENT "
        "(`duration_moving_s`) n'est délibérément PAS exposé séparément (nit, revue de code "
        "#49) : `vam_moving_m_h` existe déjà à côté de `vam_elapsed_m_h` sur la même ligne "
        "pour qui veut comparer les deux, et dupliquer aussi `vs_previous`/`vs_best` en "
        "version « mouvement » alourdirait l'API/l'UI pour un signal secondaire — à ajouter "
        "sans difficulté si l'usage le justifie (même calcul, base `duration_moving_s`).\n\n"
        "MÊME ACTIVITÉ, PLUSIEURS OCCURRENCES (nit, revue de code #49, documenté plutôt que "
        "surprenant) : deux montées détectées dans la MÊME activité (ex. un aller-retour "
        "avec la même côte gravie deux fois, ou des répétitions de côte) sont appariées au "
        "même `climb_segment` si leur géométrie/profil correspond, EXACTEMENT comme deux "
        "montées d'activités différentes — `climb_registry`/`segment_history` "
        "(`arc_index.compute_metrics`) sont mis à jour APRÈS CHAQUE montée traitée, dans "
        "l'ordre chronologique de la séance, jamais après la séance entière. La 2e "
        "répétition affiche donc `vs_previous_pct` face à la 1ʳᵉ de LA MÊME séance (pas "
        "face à la séance précédente) — comportement voulu : c'est la comparaison la plus "
        "récente disponible, cohérent avec la définition de `vs_previous_pct` ci-dessus."
    ),
    "frozen_first_occurrence": (
        "Le profil représentatif d'un segment (`gain_m`/`distance_m`/`avg_grade`/"
        "`grade_class`/`location`, plus la position quand connue) est celui de sa PREMIÈRE "
        "occurrence rencontrée — jamais mis à jour ensuite, même si des occurrences "
        "suivantes mesurent un gain/une longueur légèrement différents (bruit de mesure "
        "normal d'une séance à l'autre, voir `_close`/`CLIMB_MATCH_GAIN_TOLERANCE_FRAC`). "
        "Documenté honnêtement (nit, revue de code #49) : un repère STABLE (jamais dérivant "
        "d'une moyenne mobile qui bougerait à chaque nouvelle occurrence) est préférable "
        "pour l'appariement — chaque occurrence individuelle garde de toute façon SES "
        "propres `gain_m`/`distance_m`/etc. mesurés dans `activity_climb`, seul le REPÈRE de "
        "recherche (`climb_segment`) reste figé."
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
    """Position de départ, de sommet ET de MI-PARCOURS (50 % de la distance parcourue
    pendant la montée, #49 2e revue de code, BLOQUANT — voir ASSUMPTIONS["gps_matching"])
    d'une montée détectée (`arc_climb.detect_climbs`), à partir des échantillons de
    l'activité (`t_s`, `distance_m`, `lat_deg`, `lon_deg`) — `None` si le départ ou le
    sommet n'a aucune position exploitable dans la fenêtre de la montée (séance sans GPS,
    ou trou de signal GPS aux deux bornes) ; `mid_lat`/`mid_lon` peuvent rester `None`
    isolément (trou de signal ponctuel au milieu de la montée) sans invalider le reste."""
    window = [s for s in act_samples
              if s.get("t_s") is not None and climb["start_t_s"] <= s["t_s"] <= climb["end_t_s"]]
    if not window:
        return None
    ordered = sorted(window, key=lambda s: s["t_s"])
    start = next((s for s in ordered if s.get("lat_deg") is not None and s.get("lon_deg") is not None), None)
    end = next((s for s in reversed(ordered) if s.get("lat_deg") is not None and s.get("lon_deg") is not None), None)
    if start is None or end is None:
        return None
    mid_lat = mid_lon = None
    with_distance = [s for s in ordered if s.get("distance_m") is not None
                      and s.get("lat_deg") is not None and s.get("lon_deg") is not None]
    if with_distance:
        target = (with_distance[0]["distance_m"] + with_distance[-1]["distance_m"]) / 2.0
        nearest = min(with_distance, key=lambda s: abs(s["distance_m"] - target))
        mid_lat, mid_lon = nearest["lat_deg"], nearest["lon_deg"]
    return {"start_lat": start["lat_deg"], "start_lon": start["lon_deg"],
            "end_lat": end["lat_deg"], "end_lon": end["lon_deg"],
            "mid_lat": mid_lat, "mid_lon": mid_lon}


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


def _position_tolerance_m(candidate: dict, segment: dict) -> float:
    """Tolérance de position EFFECTIVE pour une paire (candidat, segment) — voir le
    commentaire de `CLIMB_MATCH_POSITION_TOLERANCE_M`/`CLIMB_MATCH_POSITION_TOLERANCE_FRAC`
    et ASSUMPTIONS["gps_matching"] pour la mesure qui justifie la mise à l'échelle. Basée
    sur la PLUS LONGUE des deux longueurs connues (candidat/segment) : un glissement de bord
    dépend de la longueur RÉELLE de la montée, dont on ne connaît a priori que ces deux
    mesures indépendantes, potentiellement toutes deux bruitées."""
    lengths = [v for v in (candidate.get("distance_m"), segment.get("distance_m")) if v]
    longest = max(lengths) if lengths else 0.0
    scaled = max(CLIMB_MATCH_POSITION_TOLERANCE_M, CLIMB_MATCH_POSITION_TOLERANCE_FRAC * longest)
    return min(scaled, CLIMB_MATCH_POSITION_TOLERANCE_CAP_M)


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
    en SQLite, par l'appelant.

    `mark()`/`rollback(mark)` (revue de code #49, BLOQUANT) permettent à l'appelant
    d'annuler proprement tout ce qu'une activité a enregistré ICI si son traitement échoue
    APRÈS l'appariement (ex. un calcul dérivé suivant lève) — voir
    `arc_index.compute_metrics` et ASSUMPTIONS d'`arc_index` sur la défense en profondeur :
    sans ce mécanisme, une activité en échec pouvait laisser une occurrence FANTÔME dans
    `segment_history`, faussant `vs_previous_pct`/`vs_best_pct` d'une activité SUIVANTE qui,
    elle, réussit."""

    def __init__(self) -> None:
        self.segments: List[dict] = []
        self._by_grid: Dict[Tuple[int, int], List[int]] = {}
        self._by_location: Dict[str, List[int]] = {}
        # Journal d'adoption (2e revue de code #49, BLOQUANT) : chaque entrée
        # `(idx, position_precedente)` enregistrée AVANT qu'une adoption (voir
        # `_match_fallback`) n'écrase la position d'un segment déjà existant — nécessaire
        # pour que `rollback` puisse défaire une adoption, pas seulement un `add` (un
        # `rollback` qui ne remettait la position à zéro que via la troncature de
        # `self.segments` ratait totalement les adoptions, qui mutent un segment
        # D'INDEX < mark, jamais ajouté depuis).
        self._adoptions: List[Tuple[int, dict]] = []

    def mark(self) -> Tuple[int, int]:
        """Point de reprise pour `rollback` — `(nombre de segments, nombre d'adoptions)`
        actuellement connus. Un simple entier ne suffit plus depuis l'ajout du journal
        d'adoption (voir `__init__`)."""
        return len(self.segments), len(self._adoptions)

    def rollback(self, mark: Tuple[int, int]) -> None:
        """Défait tout ce qui s'est produit depuis `mark` (voir `mark()`) : segments
        AJOUTÉS depuis (index/lieu compris) ET adoptions de position sur des segments
        PLUS ANCIENS (position restaurée, quadrillage spatial nettoyé) — sans effet si
        rien ne s'est produit depuis."""
        segments_mark, adoptions_mark = mark
        # Adoptions D'ABORD, en ordre INVERSE (dernière adoptée, première défaite) : une
        # adoption peut avoir eu lieu sur un segment plus ancien que `segments_mark`, donc
        # rien à voir avec la troncature de `self.segments` ci-dessous — les deux opérations
        # sont indépendantes, mais l'ordre (adoptions puis troncature) évite de manipuler un
        # index de segment déjà supprimé.
        while len(self._adoptions) > adoptions_mark:
            idx, previous = self._adoptions.pop()
            if idx >= segments_mark:
                continue  # ce segment sera de toute façon supprimé par la troncature ci-dessous
            seg = self.segments[idx]
            if seg.get("start_lat") is not None and seg.get("start_lon") is not None:
                self._deregister_position(idx, seg["start_lat"], seg["start_lon"])
            seg["start_lat"], seg["start_lon"] = previous["start_lat"], previous["start_lon"]
            seg["summit_lat"], seg["summit_lon"] = previous["summit_lat"], previous["summit_lon"]
            seg["mid_lat"], seg["mid_lon"] = previous["mid_lat"], previous["mid_lon"]
            # La position PRÉCÉDENTE d'une adoption est toujours `None` (seuls des segments
            # SANS position sont adoptés, voir `_match_fallback`) : rien à ré-enregistrer
            # dans le quadrillage spatial ici.
        if segments_mark < len(self.segments):
            del self.segments[segments_mark:]
            for key in list(self._by_grid):
                kept = [i for i in self._by_grid[key] if i < segments_mark]
                if kept:
                    self._by_grid[key] = kept
                else:
                    del self._by_grid[key]
            for key in list(self._by_location):
                kept = [i for i in self._by_location[key] if i < segments_mark]
                if kept:
                    self._by_location[key] = kept
                else:
                    del self._by_location[key]

    def _grid_cells(self, lat: float, lon: float) -> List[Tuple[int, int]]:
        cx = math.floor(lat / GRID_CELL_DEG)
        cy = math.floor(lon / GRID_CELL_DEG)
        return [(cx + dx, cy + dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1)]

    def _grid_indices(self, lat: float, lon: float) -> List[int]:
        seen: List[int] = []
        for key in self._grid_cells(lat, lon):
            for i in self._by_grid.get(key, []):
                if i not in seen:
                    seen.append(i)
        return seen

    def _location_indices(self, location: Optional[str]) -> List[int]:
        loc = _norm_location(location)
        return list(self._by_location.get(loc, [])) if loc is not None else []

    def _register_position(self, idx: int, lat: float, lon: float) -> None:
        for key in self._grid_cells(lat, lon):
            self._by_grid.setdefault(key, []).append(idx)

    def _deregister_position(self, idx: int, lat: float, lon: float) -> None:
        """Inverse de `_register_position` — utilisé UNIQUEMENT par `rollback` pour
        défaire une adoption (voir le journal `_adoptions`)."""
        for key in self._grid_cells(lat, lon):
            bucket = self._by_grid.get(key)
            if not bucket:
                continue
            if idx in bucket:
                bucket.remove(idx)
            if not bucket:
                del self._by_grid[key]

    def _match_gps(self, candidate: dict, indices: List[int]) -> Optional[dict]:
        best, best_score = None, None
        for i in indices:
            seg = self.segments[i]
            if seg.get("start_lat") is None or seg.get("summit_lat") is None:
                continue  # segment sans position connue : jamais comparé ici (voir _match_fallback)
            tol = _position_tolerance_m(candidate, seg)
            d_start = haversine_m(candidate["start_lat"], candidate["start_lon"],
                                   seg["start_lat"], seg["start_lon"])
            d_summit = haversine_m(candidate["end_lat"], candidate["end_lon"],
                                    seg["summit_lat"], seg["summit_lon"])
            if d_start > tol or d_summit > tol:
                continue
            # Contrôle de MI-PARCOURS (2e revue de code #49, BLOQUANT — should-fix) : deux
            # montées longues mais DISTINCTES peuvent avoir un départ ET un sommet chacun
            # sous tolérance (ex. deux montées de 5 km depuis le même fond de vallée, vers
            # deux sommets voisins) sans être la même montée — leur MILIEU, lui, diverge
            # nettement dès que les deux montées empruntent des itinéraires différents.
            # Comparé seulement quand connu des deux côtés (`None` d'un côté : trou de
            # signal ponctuel, jamais un candidat/segment rejeté sur cette seule absence).
            if (candidate.get("mid_lat") is not None and candidate.get("mid_lon") is not None
                    and seg.get("mid_lat") is not None and seg.get("mid_lon") is not None):
                d_mid = haversine_m(candidate["mid_lat"], candidate["mid_lon"], seg["mid_lat"], seg["mid_lon"])
                if d_mid > tol:
                    continue
            if not _profile_close(candidate, seg):
                continue
            score = d_start + d_summit
            if best is None or score < best_score:
                best, best_score = seg, score
        return best

    def _match_fallback(self, candidate: dict, indices: List[int], *, gps_only: bool) -> Optional[dict]:
        """Repli par lieu + profil (ASSUMPTIONS["fallback_matching"]) — `gps_only=True` :
        appelé pour un CANDIDAT AVEC GPS qui n'a trouvé aucun segment GPS compatible,
        restreint aux segments SANS position connue (« adoption », voir ASSUMPTIONS) ;
        `gps_only=False` : candidat sans GPS, restreint... à rien de plus (n'importe quel
        segment du même lieu, qu'il ait ou non une position, peut satisfaire un candidat qui
        n'a de toute façon pas de géométrie à comparer)."""
        pool = indices
        if gps_only:
            pool = [i for i in indices if self.segments[i].get("start_lat") is None]
        matches = [i for i in pool if _profile_close(candidate, self.segments[i], require_grade_class=True)]
        if len(matches) != 1:
            return None
        idx = matches[0]
        seg = self.segments[idx]
        if gps_only:
            # Adoption (ASSUMPTIONS["fallback_matching"]) : ce segment n'avait pas de
            # position, ce candidat en a une — il la prend, et rejoint le quadrillage
            # spatial pour que les occurrences GPS suivantes le retrouvent directement.
            # Journalisée AVANT mutation (voir `_adoptions`/`rollback`, 2e revue de code
            # #49, BLOQUANT) : un `rollback` ultérieur doit pouvoir restaurer l'ABSENCE de
            # position de ce segment, pas seulement défaire un `add`.
            self._adoptions.append((idx, {
                "start_lat": seg["start_lat"], "start_lon": seg["start_lon"],
                "summit_lat": seg["summit_lat"], "summit_lon": seg["summit_lon"],
                "mid_lat": seg.get("mid_lat"), "mid_lon": seg.get("mid_lon"),
            }))
            seg["start_lat"], seg["start_lon"] = candidate["start_lat"], candidate["start_lon"]
            seg["summit_lat"], seg["summit_lon"] = candidate["end_lat"], candidate["end_lon"]
            seg["mid_lat"], seg["mid_lon"] = candidate.get("mid_lat"), candidate.get("mid_lon")
            self._register_position(idx, seg["start_lat"], seg["start_lon"])
        return seg

    def match(self, candidate: dict) -> Optional[dict]:
        """Rend le segment déjà connu qui correspond le mieux à `candidate`, ou `None` —
        voir ASSUMPTIONS["gps_matching"]/["fallback_matching"]. `candidate` :
        `{'start_lat','start_lon','end_lat','end_lon','gain_m','distance_m','grade_class','location'}`
        (positions à `None` si inconnues)."""
        has_gps = all(candidate.get(k) is not None for k in ("start_lat", "start_lon", "end_lat", "end_lon"))
        if has_gps:
            gps_indices = self._grid_indices(candidate["start_lat"], candidate["start_lon"])
            found = self._match_gps(candidate, gps_indices)
            if found is not None:
                return found
            # Aucun segment GPS compatible : dernier recours par lieu, restreint aux
            # segments SANS position (adoption — voir ASSUMPTIONS["fallback_matching"]).
            return self._match_fallback(candidate, self._location_indices(candidate.get("location")),
                                         gps_only=True)
        return self._match_fallback(candidate, self._location_indices(candidate.get("location")), gps_only=False)

    def add(self, candidate: dict) -> dict:
        """Enregistre `candidate` comme un NOUVEAU segment (aucun appariement trouvé) et le
        rend. `id` déterministe (voir ASSUMPTIONS["segment_id"]) : `candidate` DOIT porter
        `garmin_activity_id` et `climb_idx` (index 1-based de cette montée dans son
        activité, `arc_climb.detect_climbs` l'attribue déjà) — jamais un compteur
        séquentiel."""
        segment = {
            "id": candidate["garmin_activity_id"] * SEGMENT_ID_CLIMB_MULTIPLIER + candidate["climb_idx"],
            "start_lat": candidate.get("start_lat"), "start_lon": candidate.get("start_lon"),
            "summit_lat": candidate.get("end_lat"), "summit_lon": candidate.get("end_lon"),
            "mid_lat": candidate.get("mid_lat"), "mid_lon": candidate.get("mid_lon"),
            "gain_m": candidate.get("gain_m"), "distance_m": candidate.get("distance_m"),
            "avg_grade": candidate.get("avg_grade"), "grade_class": candidate.get("grade_class"),
            "location": candidate.get("location"),
        }
        idx = len(self.segments)
        self.segments.append(segment)
        if segment["start_lat"] is not None and segment["start_lon"] is not None:
            self._register_position(idx, segment["start_lat"], segment["start_lon"])
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
