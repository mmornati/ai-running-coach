#!/usr/bin/env python3
"""Vitesse ascensionnelle moyenne (VAM, m/h) sur les montées détectées — #46,
épopée #21.

## Qu'est-ce que la VAM

La VAM (« Vitesse Ascensionnelle Moyenne », parfois VAM en anglais aussi —
« Vertical Ascent rate ») est le gain d'altitude divisé par le temps :

    VAM (m/h) = gain_m / (durée_h)

Terminologie d'origine cycliste (montées chronométrées sur route), souvent
associée dans la culture du cyclisme au préparateur italien Michele Ferrari —
**aucune publication scientifique vérifiable identifiée par ce projet pour
cette attribution précise** : elle est mentionnée ici comme repère historique
informel, jamais comme une source citée (voir CONTRIBUTING.md, « citer
uniquement ce qui est vérifiable »). Le calcul lui-même est une simple
division (gain d'altitude / temps), pas un modèle propriétaire : rien à
reproduire ni à approximer, contrairement au GAP (`arc_gap.py`, #44, modèle de
Minetti). Des fonctionnalités de segmentation de montée existent chez
plusieurs marques (segments de montée de la marque Strava, ClimbPro de la
marque Garmin) : ce module s'en inspire pour le principe (détecter des
montées, mesurer leur VAM) mais n'en reproduit aucun calcul propriétaire —
voir `docs/marques.md`.

## Détection des montées — REUSE partiel, pas une troisième copie complète

Deux détecteurs de montées existaient déjà dans le projet avant #46:
`skills/gpx-analysis/scripts/analyze_gpx.py::detect_climbs` (points GPS bruts,
suivi de pic simple, sans fusion de creux ni notion de trou de signal
temporel — un fichier GPX n'a pas de temps fiable point par point) et
`skills/session-parts-analyzer/scripts/analyze_session_parts.py::detect_climbs`
(pente instantanée ≥ seuil, sans fusion de creux non plus). Aucun des deux ne
couvre l'hystérésis (fusion de montées séparées par un petit creux) ni le
respect des trous de signal EXIGÉS par le critère d'acceptation de #46 — les
étendre sur place aurait risqué de changer leur sortie (contrat de #46 :
« comportement inchangé, sortie identique octet pour octet sur un GPX de
test » si on les touche). Ce module RÉUTILISE en revanche leurs briques
communes déjà factorisées par #44 : le lissage d'altitude
(`arc_elevation.smooth_moving_average`, déjà partagé par `analyze_gpx.py`) et
la segmentation par trou de signal (`arc_elevation.segments_by_gap`, alias
public ajouté par #46 sur la fonction déjà utilisée en interne par
`arc_elevation.grade_series`). L'algorithme de détection proprement dit
(zigzag à hystérésis + fusion de creux, voir plus bas) est neuf : aucun des
deux détecteurs existants ne l'implémentait, et c'est précisément ce que #46
demande en plus (montée minimale configurable, fusion de creux, trous de
signal jamais franchis — voir `ASSUMPTIONS`). #49 (progression sur une même
montée) pourra réutiliser `detect_climbs`/`climb_report` tels quels plutôt que
réinventer une quatrième détection.

## Algorithme de détection

1. **Segmentation par trou de signal** (`arc_elevation.segments_by_gap`,
   `MAX_GAP_S`, 30 s comme le GAP/#44) : une montée n'est jamais détectée ni
   fusionnée à travers une pause GPS/altimètre.
2. **Lissage** de l'altitude (`arc_elevation.smooth_moving_average`,
   `SMOOTH_TAPS`, 3 points — même lissage que le GAP) pour ne pas confondre
   bruit barométrique et vrai changement de pente.
3. **Simplification en zigzag à hystérésis** (`_zigzag_extrema`,
   `SWING_NOISE_FLOOR_M`) : algorithme standard à extremum courant confirmé —
   un extremum candidat (le plus haut/bas point vu depuis le dernier extremum
   confirmé) n'est confirmé, et un nouveau candidat de sens opposé démarré,
   que lorsque le signal RETRACE d'au moins `SWING_NOISE_FLOOR_M` depuis ce
   candidat (jamais une élimination a posteriori de petits segments, qui peut
   effacer un vrai sommet intermédiaire — voir ASSUMPTIONS["zigzag"] pour le
   bug que cela évite, revue de code #46).
4. **Montées brutes** : chaque paire (creux, sommet) consécutive dans le
   zigzag dont l'altitude progresse.
5. **Rognage de chaque montée brute AUX EXTRÉMITÉS** (`_trim_rise`, tolérance =
   `max(TRIM_TOLERANCE_M, TRIM_TOLERANCE_NOISE_K × bruit mesuré)`, voir
   `_robust_noise_sigma`) : un creux/sommet du zigzag peut se retrouver très
   loin de la vraie montée quand une longue approche plate (ou un long replat
   de sortie) ne crée elle-même aucun extremum — voir ASSUMPTIONS["trim"] pour
   le bug corrigé (revue de code #46, BLOQUANT) et la méthode complète.
6. **Découpage des plateaux INTERNES** (`_split_flat_plateaus`), sur le
   résultat DÉJÀ ROGNÉ du point précédent : un plateau interne dont la pente
   moyenne reste sous `PLATEAU_SPLIT_MAX_GRADE` sur au moins
   `MERGE_MAX_DIP_DIST_M` de distance est retiré — un tel plateau ne crée
   jamais lui-même d'extremum au zigzag (aucune vraie retombée n'y dépasse
   `SWING_NOISE_FLOOR_M`) et ne pourrait de toute façon jamais être fusionné
   ensuite. Chaque nouveau morceau produit par un découpage est alors rogné À
   SON TOUR (jamais un morceau que le découpage aurait laissé intact, déjà
   rogné à l'étape précédente — voir ASSUMPTIONS["trim"] pour le bug de
   double-rognage que cet ordre évite, revue de code #46, BLOQUANT 2e passe).
7. **Fusion des montées (rognées) séparées par un petit creux** (`_merge_climbs`,
   `MERGE_MAX_DIP_LOSS_M`/`MERGE_DIP_RELATIVE_FRAC`/`MERGE_MAX_DIP_DIST_M`) :
   deux montées consécutives sont fusionnées en une seule si le creux qui les
   sépare perd moins que le seuil (le plus GRAND de l'absolu et du relatif aux
   gains adjacents, voir ASSUMPTIONS["merge"]) sur moins de
   `MERGE_MAX_DIP_DIST_M` de distance horizontale — un replat ou un petit
   passage en faux plat au milieu d'une montée ne doit pas la couper en deux
   montées artificielles.
8. **Filtre final** : gain net ≥ `MIN_CLIMB_GAIN_M` ET pente moyenne (gain /
   distance) ≥ `MIN_CLIMB_AVG_GRADE`, sur la montée (rognée puis) éventuellement
   fusionnée.

Voir `ASSUMPTIONS` pour la justification complète de chaque seuil.

## VAM : temps écoulé vs temps de mouvement — DEUX métriques, jamais une seule

Un arrêt prolongé au milieu d'une montée (ravitaillement, photo, pause) fait
chuter la VAM « temps écoulé » sans que l'effort d'ascension réel n'ait
changé. Ce module calcule et expose **les deux** plutôt que de trancher :
`vam_elapsed_m_h` (gain / durée ÉCOULÉE, arrêts compris — c'est la définition
usuelle et la plus simple à interpréter : « à quelle vitesse ai-je gravi cette
montée, du premier au dernier pas ») et `vam_moving_m_h` (gain / durée de
MOUVEMENT seulement, arrêts exclus — reflète l'effort ascensionnel réel,
insensible à une pause). `vam_elapsed_m_h` est la valeur mise en avant par
défaut (tableau de bord, tri des montées) car c'est la question que se pose
spontanément l'athlète ; `vam_moving_m_h` reste disponible à côté pour
détecter une pause qui aurait plombé la VAM apparente. Voir
`ASSUMPTIONS["vam_basis"]`.

## API réutilisable, pure (sans SQLite ni disque) — pour #49 (progression sur
une même montée) et #58 (modèle pente→allure)

- `detect_climbs(samples, ...)` : montées détectées sur des échantillons
  normalisés (`arc_index.samples`), chacune avec ses bornes, son gain, sa
  distance, sa pente moyenne, sa classe de pente et ses deux VAM.
- `best_vam_windows(samples, climbs, ...)` : meilleure VAM sur des fenêtres
  glissantes de 10/20 minutes PENDANT les montées détectées (« courbe de
  puissance verticale », voir `ASSUMPTIONS["best_window"]`).
- `vam_by_grade_class(climbs)` : VAM moyenne par classe de pente.
- `climb_report(samples, sport, ...)` : rapport complet, restreint à la
  famille course à pied (course, trail, randonnée, marche — la marche compte,
  la VAM en randonnée/power-hiking est parfaitement valide en trail), TOUJOURS
  un dict avec une `reason` explicite en cas d'échec, jamais une exception.

Stdlib uniquement (CONTRIBUTING.md).
"""

from __future__ import annotations

import bisect
import statistics
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
import arc_elevation as E  # noqa: E402
import arc_gap as G  # noqa: E402
import arc_metrics as M  # noqa: E402

DEFAULT_RESOLUTION_S = G.DEFAULT_RESOLUTION_S

# Seuils de détection (#46, critère d'acceptation : « montée minimale
# configurable (D+, pente) ») — valeurs rondes documentées, pas calibrées sur
# un jeu de séances étiquetées : à ajuster si l'usage réel le justifie.
MIN_CLIMB_GAIN_M = 50.0
MIN_CLIMB_AVG_GRADE = 0.05  # 5 % — aligné sur la première classe de pente ci-dessous

# Fusion de deux montées séparées par un petit creux (replat, faux plat) — voir
# ASSUMPTIONS["merge"]. Le seuil de PERTE est le plus GRAND des deux :
# `MERGE_MAX_DIP_LOSS_M` (plancher absolu, utile sur une petite montée trail) et
# `MERGE_DIP_RELATIVE_FRAC` × le plus petit des deux gains adjacents (pour une
# grosse montée alpine, un creux de 15 m est anecdotique face à 800 m de D+,
# mais dépasserait un plancher absolu de 10 m — revue de code #46). Le seuil de
# DISTANCE, lui, reste un plancher ABSOLU (`MERGE_MAX_DIP_DIST_M`) : un plateau
# de 2 km, même sans perte d'altitude notable, n'est jamais une simple
# respiration au milieu d'une montée continue — mais une MARGE DE BRUIT (voir
# `_merge_climbs`, `noise_tol_m`) s'y ajoute quand le rognage a dû être élargi
# au bruit mesuré (ASSUMPTIONS["trim"]) : un rognage plus large déplace aussi la
# distance de creux MESURÉE entre deux montées, et sans compenser, une grosse
# montée alpine se scindait à tort plus souvent qu'avant l'ajout du rognage
# adaptatif au bruit (revue de code #46, 3e passe, should-fix 1 — mesuré :
# 17/20 tirages à σ ≈ 2 m scindaient à tort une montée alpine à deux creux de
# 15 m, contre une poignée avant l'ajout de cette marge). Plafonnée à
# `MERGE_DIST_MARGIN_CAP_FRAC` × `MERGE_MAX_DIP_DIST_M` pour qu'une montée à
# pente proche du seuil minimal (`MIN_CLIMB_AVG_GRADE`) ne fasse pas diverger
# la marge.
MERGE_MAX_DIP_LOSS_M = 10.0
MERGE_DIP_RELATIVE_FRAC = 0.125  # 12,5 %, milieu de la fourchette 10-15 % (revue de code #46)
MERGE_MAX_DIP_DIST_M = 200.0
MERGE_DIST_MARGIN_CAP_FRAC = 0.5

# Seuil de bruit de la simplification en zigzag (#46) — nettement sous
# `MIN_CLIMB_GAIN_M` : ne sert qu'à ignorer le bruit résiduel post-lissage,
# jamais à filtrer une vraie petite montée (le filtre final s'en charge).
SWING_NOISE_FLOOR_M = 5.0

# Tolérance de rognage (#46, revue de code, BLOQUANT) : après le zigzag, chaque
# montée brute est rognée à son véritable début/fin AVANT toute fusion — voir
# `_trim_rise` et ASSUMPTIONS["trim"]. Nettement sous `SWING_NOISE_FLOOR_M` :
# sert à coller au plus près du vrai bas/haut de la montée, pas à filtrer du
# bruit d'extrema. Plancher seulement : la tolérance EFFECTIVEMENT appliquée
# est `max(TRIM_TOLERANCE_M, TRIM_TOLERANCE_NOISE_K × sigma_bruit)`, où
# `sigma_bruit` est estimé sur l'altitude déjà lissée du segment (revue de
# code #46, 2e passe, should-fix 2) — voir `_robust_noise_sigma` et
# ASSUMPTIONS["trim"] : un bruit résiduel plus fort que le cas nominal
# (ex. σ ≈ 2 m après lissage) rognerait sinon bien plus que prévu (jusqu'à
# plusieurs centaines de mètres de vraie montée perdus).
TRIM_TOLERANCE_M = 2.0
TRIM_TOLERANCE_NOISE_K = 3.0

# Un plateau interne à une montée brute dont la PENTE MOYENNE (pas la simple
# variation absolue d'altitude — voir `_split_flat_plateaus`, un plateau de
# 2 km avec 3-4 m de faux plat dépasse largement `TRIM_TOLERANCE_M` mais reste
# à une pente dérisoire) reste sous ce seuil sur au moins `MERGE_MAX_DIP_DIST_M`
# de distance ne peut de toute façon JAMAIS être fusionné (`_merge_climbs` le
# refuserait sur le seul critère de distance) — `_split_flat_plateaus` le
# retire donc de la montée brute (déjà rognée à ses extrémités), plutôt que
# d'attendre (en vain) que le zigzag y détecte un extremum (BLOQUANT, revue de
# code #46, 2e passe : un plateau sans vraie retombée ≥ `SWING_NOISE_FLOOR_M`
# ne crée JAMAIS d'extremum, donc restait auparavant à l'intérieur d'une seule
# « montée » brute continue, quelle que soit sa longueur — voir
# ASSUMPTIONS["trim"]). Valeur ronde (~1/5 du seuil de détection le plus bas,
# `MIN_CLIMB_AVG_GRADE` à 5 %) : nettement sous la pente de n'importe quelle
# vraie montée trail, jamais calibrée sur un jeu de séances étiquetées.
PLATEAU_SPLIT_MAX_GRADE = 0.02

# Même lissage et même segmentation par trou de signal que le GAP (#44,
# `arc_gap.py`/`arc_elevation.py`) — cohérence des KPI dérivés des mêmes
# échantillons.
SMOOTH_TAPS = E.DEFAULT_SMOOTH_TAPS
MAX_GAP_S = E.DEFAULT_MAX_GAP_S

# Fenêtres de la « courbe de puissance verticale » (#46, critère d'acceptation :
# « tendance : meilleure VAM sur 10/20 min ») — mêmes noms que les colonnes
# `activity.best_vam_10min_m_h`/`best_vam_20min_m_h` (arc_index.py).
BEST_WINDOWS_S = {"vam_best_10min_m_h": 600.0, "vam_best_20min_m_h": 1200.0}

# Classes de pente (#46, critère d'acceptation : « VAM ... par pente »).
# `MIN_CLIMB_AVG_GRADE` coïncide avec la borne basse de "5-10%" : une montée
# tout juste détectée tombe donc toujours dans la première classe non vide.
GRADE_CLASSES: Tuple[Tuple[float, float, str], ...] = (
    (0.00, 0.05, "<5%"),
    (0.05, 0.10, "5-10%"),
    (0.10, 0.15, "10-15%"),
    (0.15, 0.20, "15-20%"),
    (0.20, float("inf"), ">20%"),
)

ASSUMPTIONS = {
    "model": (
        "VAM (Vitesse Ascensionnelle Moyenne) = gain d'altitude (m) / durée (h), sur une montée "
        "détectée. Terminologie d'origine cycliste, souvent associée informellement au préparateur "
        "Michele Ferrari dans la culture du cyclisme — AUCUNE publication vérifiable identifiée pour "
        "cette attribution précise, mentionnée uniquement comme repère historique, jamais comme une "
        "source citée. Le calcul lui-même (une division) n'est pas un modèle propriétaire : rien à "
        "approximer ni à reproduire, à la différence du GAP (arc_gap.py, Minetti et al. 2002)."
    ),
    "restricted_to_run_family": (
        "Calculé UNIQUEMENT pour les séances de la famille course à pied (arc_metrics.sport_family == "
        "\"run\" : course, trail, randonnée, marche) avec des échantillons FIT ingérés — la randonnée "
        "et la marche (power-hiking) y ont toute leur place : la VAM en montée est un indicateur "
        "trail/montagne classique aussi bien en courant qu'en marchant vite."
    ),
    "detection": (
        f"Une montée est détectée sur l'altitude LISSÉE (moyenne glissante {SMOOTH_TAPS} points, même "
        "lissage que le GAP/#44) simplifiée en zigzag à hystérésis (creux/sommets séparés d'au moins "
        f"{SWING_NOISE_FLOOR_M:.0f} m, pour ignorer le bruit résiduel post-lissage — voir "
        "ASSUMPTIONS[\"zigzag\"]), rognée à son véritable début/fin (voir ASSUMPTIONS[\"trim\"]), puis "
        f"retenue seulement si son gain net atteint {MIN_CLIMB_GAIN_M:.0f} m ET sa pente moyenne (gain / "
        f"distance) atteint {MIN_CLIMB_AVG_GRADE * 100:.0f} % — les DEUX critères, jamais un seul (un "
        "faux plat de 200 m de D+ sur 10 km ne doit pas compter comme une montée trail, et un mur de "
        "20 m à 30 % non plus si le critère de D+ minimal existe pour écarter le bruit très local). "
        "Valeurs rondes documentées, pas calibrées sur un jeu de séances étiquetées trail/montagne — un "
        "réglage futur resterait localisé à ces deux constantes. Configurables par le workspace, voir "
        "`[metrics].climb_min_gain_m`/`climb_min_grade_pct` dans `config/workspace.toml`."
    ),
    "zigzag": (
        "La simplification en zigzag suit l'algorithme standard « extremum courant confirmé » (pas une "
        "élimination a posteriori de petits segments) : un candidat (le point le plus haut/bas vu depuis "
        "le dernier extremum CONFIRMÉ) n'est confirmé comme extremum, et un nouveau candidat de sens "
        f"opposé démarré, que lorsque le signal retrace d'au moins {SWING_NOISE_FLOOR_M:.0f} m depuis ce "
        "candidat. Une PREMIÈRE VERSION de #46 (revue de code, BLOQUANT) éliminait après coup les petits "
        "segments d'un passage en revue des extrema locaux bruts, en reconsidérant à chaque suppression "
        "les swings des segments restants CONTRE des voisins différents de ceux d'origine — un vrai "
        "sommet intermédiaire pouvait alors être supprimé à tort (exemple qui casse cette version : "
        "altitudes [0, 100, 98, 103, 60] avec un seuil de 5 m rend [0, 1, 4] au lieu de [0, 1, 3, 4] — le "
        "sommet réel à 103 disparaît). L'algorithme courant ne présente pas ce défaut : chaque extremum "
        "confirmé l'est par une seule comparaison locale (retracement depuis le candidat courant), jamais "
        "reconsidéré ensuite."
    ),
    "trim": (
        "BLOQUANT (revue de code #46) : un extremum du zigzag peut se retrouver TRÈS loin de la vraie "
        "montée quand une longue approche plate (ou un long replat de sortie) ne crée elle-même aucun "
        f"extremum — ex. 3 km plats + 100 m de montée + 3 km plats : le « creux » retenu par le zigzag "
        "reste au tout début des 3 km plats (rien n'y dépasse le seuil de bruit), ce qui dilue "
        "artificiellement la distance et donc la pente moyenne calculée (montée non détectée du tout, "
        "ou VAM faussée). `_trim_rise` corrige cela EN ROGNANT chaque montée brute AVANT toute fusion : "
        "sur l'intervalle du zigzag brut, le début est déplacé au DERNIER point encore à `tol` du "
        "minimum de l'intervalle, et la fin au PREMIER point déjà à `tol` du maximum — ce qui élimine "
        "toute approche plate en amont et tout replat en aval, sans dépendre de la position réelle de "
        "l'extremum détecté par le zigzag. `tol` est un PLANCHER "
        f"({TRIM_TOLERANCE_M:.0f} m, `TRIM_TOLERANCE_M`), volontairement plus petit que "
        "`SWING_NOISE_FLOOR_M` (sert à coller au plus près du vrai bas/haut de la montée, pas à filtrer "
        "du bruit d'extrema, rôle déjà tenu par le zigzag) — MAIS élargi au bruit réellement mesuré "
        f"(`max(TRIM_TOLERANCE_M, {TRIM_TOLERANCE_NOISE_K:.0f} × sigma_bruit)`, `_robust_noise_sigma`, "
        "estimateur MAD sur la dérivée seconde de l'altitude déjà lissée) si besoin (revue de code #46, "
        "2e passe, should-fix 2) : un plancher fixe de 2 m rognerait BIEN TROP sur un signal plus "
        "bruité que le cas nominal (mesuré : jusqu'à 1 350 m de vraie montée perdus et -20 % de VAM à "
        "σ ≈ 2 m après lissage) — le seuil s'adapte donc au bruit réel de CHAQUE segment plutôt que de "
        "supposer un bruit nominal universel. Rogner AVANT la fusion (jamais après) est essentiel : "
        "c'est ce qui permet à `MERGE_MAX_DIP_DIST_M` de mesurer la VRAIE distance du replat entre deux "
        "montées plutôt qu'une distance gonflée par des bouts de plat encore attachés aux deux montées.\n\n"
        "SECONDE LIMITE, également BLOQUANTE et corrigée en 2e passe de revue : un plateau interne SANS "
        "aucune vraie retombée d'altitude ≥ `SWING_NOISE_FLOOR_M` (ex. un plateau parfaitement plat, ou un "
        "faux plat de seulement quelques mètres sur plusieurs kilomètres) ne crée JAMAIS d'extremum au "
        "zigzag — deux montées séparées par un tel plateau restaient donc, avant cette correction, une "
        "SEULE montée brute continue, même sur un plateau de plusieurs kilomètres (le rognage seul coupe "
        "les DEUX EXTRÉMITÉS d'une montée brute, jamais un plateau interne). `_split_flat_plateaus` "
        "corrige ce cas, sur la montée DÉJÀ ROGNÉE à ses extrémités : tout intervalle interne dont la "
        f"PENTE MOYENNE (pas la simple variation absolue d'altitude — voir plus bas pourquoi) reste sous "
        f"`PLATEAU_SPLIT_MAX_GRADE` ({PLATEAU_SPLIT_MAX_GRADE * 100:.0f} %) sur AU MOINS "
        f"`MERGE_MAX_DIP_DIST_M` ({MERGE_MAX_DIP_DIST_M:.0f} m) de distance horizontale est retiré, "
        "coupant la montée en plusieurs morceaux — un tel plateau ne pourrait de toute façon jamais être "
        "fusionné ensuite (son étendue dépasse justement le seuil de fusion par distance). Un critère de "
        "PENTE (et non de variation absolue bornée par `TRIM_TOLERANCE_M`, comme le rognage lui-même) est "
        "nécessaire ici : un plateau de 2 km avec 3-4 m de faux plat dépasse la tolérance de rognage "
        "(2 m par défaut) mais reste à une pente dérisoire (0,15-0,2 %) — un critère absolu aurait soit "
        "raté ce cas, soit (avec un seuil plus généreux) redoublé le rognage déjà appliqué et rogné "
        "excessivement une vraie montée sans aucun plateau (bug corrigé lors de cette même revue : "
        "appliquer le rognage une SECONDE fois sur un segment déjà rogné, avec le même seuil, double-rogne "
        "d'environ `TRIM_TOLERANCE_M` de chaque côté). Ordre d'exécution donc IMPORTANT : rognage des "
        "extrémités D'ABORD, découpage des plateaux internes ENSUITE sur le résultat déjà rogné, puis un "
        "second rognage UNIQUEMENT sur les nouveaux morceaux effectivement produits par un découpage "
        "(jamais sur une montée que le découpage aurait laissée intacte, déjà rognée à l'étape "
        "précédente).\n\n"
        "MARGE DE BORD, documentée honnêtement : une fenêtre de découpage de longueur "
        f"`MERGE_MAX_DIP_DIST_M` peut englober jusqu'à `PLATEAU_SPLIT_MAX_GRADE × MERGE_MAX_DIP_DIST_M "
        "/ pente_réelle_de_la_montée` de VRAIE montée à son bord côté plateau (ex. à 10 % de pente "
        "réelle, jusqu'à 40 m de distance / 4 m de D+) avant que la fenêtre ne dépasse le seuil de pente "
        "et cesse d'être jugée « plate » — le D+ d'une montée immédiatement adjacente à un plateau "
        "découpé peut donc être conservativement sous-estimé de quelques mètres. La VAM, elle, reste "
        "exacte sur une pente constante (le rognage/découpage affecte gain ET distance dans la même "
        "proportion), donc bien plus fiable que le D+ absolu dans ce cas précis.\n\n"
        "LIMITES CONNUES SUPPLÉMENTAIRES, documentées honnêtement (revue de code #46, 3e passe, "
        "should-fix 2) : un tronçon dont la pente RÉELLE est très proche de `PLATEAU_SPLIT_MAX_GRADE` "
        "peut basculer d'un côté ou de l'autre du seuil selon le bruit du tirage — coupé (traité comme "
        "un plateau) sur une exécution, fusionné dans la montée sur une autre, sans que rien de mal ne se "
        "passe dans les deux cas (les deux comportements restent défendables pour un tronçon à la limite "
        "de ce qui compte comme « plat »), mais le résultat exact n'est pas garanti reproductible à 100 % "
        "d'une séance par ailleurs identique à l'autre en présence de bruit. De même, à un bruit "
        "important (σ ≥ 2 m environ après lissage), le début mesuré d'une montée peut occasionnellement "
        "glisser de quelques dizaines de mètres sur une approche plate malgré le rognage adaptatif "
        "(`TRIM_TOLERANCE_NOISE_K × sigma_bruit`) : la marge s'adapte à l'écart-type mesuré, pas à "
        "chaque tirage individuel, donc un tirage particulièrement défavorable peut ponctuellement "
        "dépasser la marge type. Aucun des deux cas n'a été observé produire un résultat GROSSIÈREMENT "
        "faux (montée manquée, fusion à tort) dans les tests de cette histoire ; seule la précision fine "
        "des bornes peut varier."
    ),
    "merge": (
        f"Deux montées (déjà rognées, voir ASSUMPTIONS[\"trim\"]) consécutives séparées par un creux "
        "(replat, faux plat, courte descente) sont fusionnées en une seule si CE creux perd moins que le "
        f"seuil applicable — le plus GRAND de {MERGE_MAX_DIP_LOSS_M:.0f} m (plancher absolu) et "
        f"{MERGE_DIP_RELATIVE_FRAC * 100:.1f} % du plus petit des deux gains adjacents (`MERGE_DIP_"
        "RELATIVE_FRAC`) — sur moins de "
        f"{MERGE_MAX_DIP_DIST_M:.0f} m de distance horizontale (plancher ABSOLU — voir plus bas pour la "
        "marge de bruit qui s'y ajoute) : même un creux minuscule sur un long plateau de plusieurs "
        "centaines de mètres n'est jamais une simple respiration au milieu d'une montée continue. Le "
        "plancher de PERTE purement absolu (revue de code #46) coupait à tort une grosse montée alpine "
        "en plusieurs tronçons dès qu'un creux de 15 m interrompait ses 800 m de D+ — anecdotique à cette "
        "échelle, mais dépassant le plancher fixe de 10 m ; le seuil relatif corrige ce cas sans changer "
        "le comportement sur une montée trail modeste (où le plancher absolu reste généralement le plus "
        "grand des deux). Sans fusion, une montée réelle avec un replat au milieu (très courant en trail : "
        "plateau avant un dernier raidillon) serait artificiellement coupée en plusieurs montées plus "
        "courtes, chacune sous-estimant le vrai effort ascensionnel continu perçu par le coureur.\n\n"
        f"MARGE DE BRUIT sur le seuil de DISTANCE ({MERGE_MAX_DIP_DIST_M:.0f} m, `_merge_climbs`, "
        "`noise_tol_m`) — revue de code #46, 3e passe, should-fix 1, corrigeant une régression introduite "
        "par le rognage adaptatif au bruit (ASSUMPTIONS[\"trim\"]) : un rognage plus large (bruit plus "
        "fort) déplace aussi le bord de CHAQUE montée d'environ `noise_tol_m` en altitude, donc d'environ "
        "`noise_tol_m / pente` en distance — deux bords, d'où une marge de "
        "`2 × noise_tol_m / pente_la_plus_faible_des_deux_montées`, plafonnée à "
        f"{MERGE_DIST_MARGIN_CAP_FRAC * 100:.0f} % de `MERGE_MAX_DIP_DIST_M` pour qu'une montée à pente "
        "proche du seuil minimal (`MIN_CLIMB_AVG_GRADE`) ne fasse pas diverger la marge. Sans cette "
        "correction, la distance de creux MESURÉE entre deux montées était élargie par le rognage "
        "adaptatif lui-même : mesuré sur un scénario de test dédié (montée alpine à deux creux de 15 m), "
        "17 tirages sur 20 à σ ≈ 2 m de bruit scindaient À TORT la montée en 2 ou 3, contre un "
        "comportement stable (toujours fusionnée) avec la marge — #49 (progression sur une même montée) a "
        "besoin d'une identification de montée stable d'une exécution à l'autre pour la même séance."
    ),
    "gap_segmentation": (
        "Une montée n'est JAMAIS détectée ni fusionnée à travers un trou de signal (montre en veille, "
        f"perte GPS/altimètre — {MAX_GAP_S:.0f} s, même segmentation que le GAP/#44, "
        "`arc_elevation.segments_by_gap`) : deux morceaux de montée de part et d'autre d'une pause "
        "totale du capteur ne sont jamais recollés, même s'ils appartiennent visuellement à la même "
        "vraie montée — mieux vaut deux montées détectées séparément qu'une VAM faussée par un temps "
        "écoulé qui inclurait une pause dont la durée réelle est inconnue. Conséquence assumée : une "
        "montée coupée en deux par un trou de signal peut voir chacune de ses deux moitiés ÉCHOUER "
        "individuellement le filtre de D+/pente minimal (ASSUMPTIONS[\"detection\"]) alors que la montée "
        "entière, reconstituée, l'aurait franchi — deux montées manquées valent mieux qu'une VAM "
        "silencieusement faussée par une pause de durée inconnue."
    ),
    "vam_basis": (
        "DEUX VAM sont calculées et exposées pour chaque montée, jamais une seule : `vam_elapsed_m_h` "
        "(gain / durée ÉCOULÉE de la montée, arrêts compris — la définition usuelle, la plus simple à "
        "interpréter) et `vam_moving_m_h` (gain / durée de MOUVEMENT seulement, échantillons sous "
        "`arc_gap.STOPPED_SPEED_MS` exclus — insensible à une pause). Un long arrêt au milieu d'une "
        "montée (ravitaillement, photo) écrase `vam_elapsed_m_h` sans changer `vam_moving_m_h` : "
        "recommandation du projet — `vam_elapsed_m_h` reste la valeur mise en avant par défaut (c'est "
        "la question spontanée de l'athlète), `vam_moving_m_h` sert à comprendre un écart inattendu "
        "entre deux montées sinon comparables, jamais l'inverse (l'effort perçu du coureur inclut ses "
        "propres pauses, contrairement à un chronométrage de segment qui les exclurait)."
    ),
    "grade_classes": (
        f"Classes de pente moyenne (par montée) : {', '.join(label for _, _, label in GRADE_CLASSES)} "
        f"— la borne basse de la première classe non triviale ({GRADE_CLASSES[1][2]}) coïncide avec "
        "`MIN_CLIMB_AVG_GRADE`, donc une montée tout juste détectée n'est jamais classée « <5 % » (ce "
        "libellé ne peut apparaître que si le seuil de détection est abaissé manuellement). Classement "
        "par montée, jamais par échantillon isolé : une montée fusionnée avec un replat interne garde "
        "une seule classe, celle de sa pente moyenne globale. La pente est ARRONDIE (0,1 point de "
        "pourcentage, la même précision que l'affichage) avant classement — une valeur brute juste sous "
        "une borne (ex. 9,98 %) qui s'affiche arrondie à « 10,0 % » doit tomber dans la classe « 10-15 % "
        "», pas dans « 5-10 % », pour ne jamais afficher un pourcentage et une classe visuellement "
        "incohérents. Classes en valeur absolue, symétriques : #47 (descente) pourra les réutiliser "
        "telles quelles pour ses propres classes de pente descendante si besoin — aucune classe dédiée à "
        "la descente n'est définie ici, ce choix reviendra à #47."
    ),
    "best_window": (
        "Comme une courbe de puissance en cyclisme (meilleure puissance moyenne sur des durées "
        "fixes), `best_vam_windows` cherche le plus grand gain net d'altitude sur une fenêtre d'AU "
        f"MOINS {BEST_WINDOWS_S['vam_best_10min_m_h'] / 60:.0f} puis "
        f"{BEST_WINDOWS_S['vam_best_20min_m_h'] / 60:.0f} minutes (approximativement — voir plus bas), "
        "glissée uniquement À L'INTÉRIEUR d'une montée détectée (jamais à travers une descente ou un "
        "plat entre deux montées, qui gonflerait artificiellement le gain sur la durée). Une montée plus "
        "courte que la fenêtre ne contribue à aucun des deux best (`None` si aucune montée de l'activité "
        "n'atteint la durée). Approximation liée à la résolution des échantillons (5 s par défaut) : le "
        "point de fin de fenêtre est le premier point dont l'écart au départ ATTEINT la durée demandée, "
        "jamais strictement plus court — la fenêtre réellement mesurée peut donc dépasser légèrement la "
        "durée nominale (jamais lui être inférieure), et la VAM est divisée par cette durée RÉELLEMENT "
        "mesurée (jamais par la durée nominale demandée), pour ne jamais surestimer le résultat d'un "
        "écart de résolution."
    ),
}


# ---------------------------------------------------------------------------
# Zigzag à hystérésis
# ---------------------------------------------------------------------------


def _zigzag_extrema(altitudes: Sequence[float], min_swing_m: float) -> List[int]:
    """Indices (dans `altitudes`) des extrema alternés (creux/sommet) d'une
    simplification en zigzag à hystérésis `min_swing_m` — algorithme standard
    « extremum courant confirmé », voir ASSUMPTIONS["zigzag"] pour le défaut
    d'une première version (élimination a posteriori) que celui-ci corrige
    (BLOQUANT, revue de code #46) : un candidat (le point le plus haut/bas vu
    depuis le dernier extremum CONFIRMÉ) n'est confirmé, et un nouveau candidat
    de sens opposé démarré, que lorsque le signal retrace d'au moins
    `min_swing_m` depuis ce candidat — jamais de reconsidération a posteriori
    d'un extremum déjà confirmé. Le premier et le dernier point sont toujours
    conservés (bornes du segment de temps sans trou de signal, voir
    `arc_elevation.segments_by_gap`)."""
    n = len(altitudes)
    if n <= 1:
        return list(range(n))
    pivots = [0]
    trend = 0  # 0 = sens pas encore déterminé ; 1 = candidat = sommet ; -1 = candidat = creux
    ext_idx, ext_val = 0, altitudes[0]
    for i in range(1, n):
        v = altitudes[i]
        if trend == 0 and abs(v - ext_val) >= min_swing_m:
            trend = 1 if v > ext_val else -1
        if trend == 1:
            if v >= ext_val:
                ext_val, ext_idx = v, i
            elif ext_val - v >= min_swing_m:
                pivots.append(ext_idx)
                trend = -1
                ext_val, ext_idx = v, i
        elif trend == -1:
            if v <= ext_val:
                ext_val, ext_idx = v, i
            elif v - ext_val >= min_swing_m:
                pivots.append(ext_idx)
                trend = 1
                ext_val, ext_idx = v, i
    if pivots[-1] != n - 1:
        pivots.append(n - 1)
    return pivots


def _raw_rises(extrema: Sequence[int], altitudes: Sequence[float]) -> List[List[int]]:
    """Paires (creux, sommet) CONSÉCUTIVES dans `extrema` dont l'altitude
    progresse — les montées brutes, avant rognage (`_trim_rise`) puis fusion
    des petits creux intermédiaires (`_merge_climbs`)."""
    rises = []
    for i in range(len(extrema) - 1):
        a, b = extrema[i], extrema[i + 1]
        if altitudes[b] > altitudes[a]:
            rises.append([a, b])
    return rises


def _robust_noise_sigma(altitudes: Sequence[float]) -> float:
    """Estimateur robuste (MAD, écart absolu médian × 1,4826, approximation de
    l'écart-type pour un bruit gaussien) du bruit résiduel d'une série DÉJÀ
    LISSÉE, à partir de sa dérivée SECONDE discrète — voir ASSUMPTIONS["trim"]
    (revue de code #46, 2e passe, should-fix 2). La dérivée seconde annule une
    tendance/pente réelle (constante ou lentement variable), ne laissant que le
    bruit résiduel : `alt[i+1] - 2*alt[i] + alt[i-1]` est nul sur une rampe
    parfaitement linéaire, quelle que soit sa pente. La médiane (jamais une
    moyenne) rend l'estimateur insensible à quelques vrais changements de pente
    ponctuels (sommet, replat) qui produiraient sinon des valeurs aberrantes.
    `0.0` si la série est trop courte pour être exploitable (< 3 points)."""
    n = len(altitudes)
    if n < 3:
        return 0.0
    diffs2 = [altitudes[i + 1] - 2 * altitudes[i] + altitudes[i - 1] for i in range(1, n - 1)]
    med = statistics.median(diffs2)
    mad = statistics.median([abs(d - med) for d in diffs2])
    return 1.4826 * mad


def _split_flat_plateaus(a: int, b: int, altitudes: Sequence[float], distances: Sequence[float], *,
                          max_gap_dist_m: float, max_grade: float) -> List[List[int]]:
    """Découpe la montée brute `[a, b]` (indices, DÉJÀ rognée à ses extrémités
    par `_trim_rise` — voir l'appelant) en plusieurs segments partout où un
    plateau INTERNE s'étend sur AU MOINS `max_gap_dist_m` de distance
    horizontale avec une pente moyenne sous `max_grade` sur cette distance —
    voir ASSUMPTIONS["trim"] (BLOQUANT, revue de code #46, 2e passe) : un tel
    plateau ne crée jamais lui-même d'extremum au zigzag (aucune vraie
    retombée n'y dépasse `SWING_NOISE_FLOOR_M`), et ne pourrait de toute façon
    jamais être fusionné ensuite (son étendue dépasse justement le seuil de
    fusion par distance, `_merge_climbs`) — sans ce découpage, deux montées
    séparées par un tel plateau restent une SEULE montée brute continue, quelle
    que soit la longueur du plateau, MÊME si l'altitude y varie de plus que la
    tolérance de rognage (`TRIM_TOLERANCE_M`) : un critère de PENTE (et non de
    variation absolue d'altitude) est nécessaire ici — un plateau de 2 km avec
    3-4 m de faux plat dépasse la tolérance de rognage (2 m) mais reste à une
    pente dérisoire (0,15-0,2 %), bien sous `max_grade`.

    Technique : pour chaque point de départ `i`, la fenêtre `[i, j]` de
    longueur horizontale FIXE (au moins `max_gap_dist_m`, `j` avançant
    uniquement — deux pointeurs classiques, la distance cumulée étant
    croissante) est jugée « plate » si (max − min) de l'altitude sur cette
    fenêtre reste sous `max_grade × max_gap_dist_m`. Une fenêtre à LONGUEUR
    FIXE (pas une fenêtre à portée d'altitude bornée comme `_trim_rise`) est
    essentielle : le critère devient alors une vraie PENTE MOYENNE sur une
    distance de référence constante, jamais une simple variation absolue qui
    dépendrait de la longueur du plateau. Rend `[[a, b]]` inchangé si aucun
    plateau qualifiant n'est trouvé."""
    if b <= a or distances[b] - distances[a] < max_gap_dist_m:
        return [[a, b]]
    max_span = max_grade * max_gap_dist_m
    # `j` DÉMARRE À `a` (jamais `a - 1` : revue de code #46, 3e passe, BLOQUANT —
    # `a` peut valoir 0 pour une montée qui commence au tout premier échantillon
    # d'un segment sans trou de signal, ex. début d'activité ou juste après un
    # trou ; `a - 1` valait alors -1, un index Python VALIDE mais qui pointe sur
    # le DERNIER élément du tableau par indexation négative, jamais sur « rien »
    # comme l'intention le supposait — la fenêtre de départ [i, j] se retrouvait
    # ainsi accidentellement immense (de `i` jusqu'à la fin du tableau), la
    # boucle d'extension ne s'exécutait jamais faute d'en avoir besoin, les
    # files restaient VIDES, et `altitudes[max_dq[0]]` levait `IndexError` dès
    # que la condition de distance était malgré tout satisfaite). Les files sont
    # initialisées ICI avec `a` lui-même, jamais par extension depuis un index
    # hors bornes.
    j = a
    min_dq: List[int] = [a]
    max_dq: List[int] = [a]
    flat_ranges: List[Tuple[int, int]] = []
    for i in range(a, b + 1):
        if i > a:
            # La fenêtre glisse d'un cran : retirer `i - 1` (maintenant hors
            # bornes) des DEUX files s'il y figure encore en tête.
            while min_dq and min_dq[0] < i:
                min_dq.pop(0)
            while max_dq and max_dq[0] < i:
                max_dq.pop(0)
        # Étend `j` jusqu'à ce que la fenêtre [i, j] ATTEIGNE (ou dépasse)
        # `max_gap_dist_m` — la condition porte sur `j` (déjà inclus), pas sur
        # `j + 1` en anticipation : sinon la boucle s'arrête UN CRAN TROP TÔT,
        # `distances[j] - distances[i]` restant perpétuellement sous le seuil
        # (bug corrigé en 2e passe de revue : la fenêtre ne dépassait jamais
        # `max_gap_dist_m` faute d'inclure le point qui la franchit réellement).
        while j < b and distances[j] - distances[i] < max_gap_dist_m:
            j += 1
            while min_dq and altitudes[min_dq[-1]] >= altitudes[j]:
                min_dq.pop()
            min_dq.append(j)
            while max_dq and altitudes[max_dq[-1]] <= altitudes[j]:
                max_dq.pop()
            max_dq.append(j)
        if not min_dq or not max_dq:
            # Filet de sécurité (ne devrait plus se produire avec l'initialisation
            # ci-dessus, gardé en défense en profondeur — jamais d'IndexError ici).
            continue
        if distances[j] - distances[i] >= max_gap_dist_m:
            span = altitudes[max_dq[0]] - altitudes[min_dq[0]]
            if span <= max_span:
                flat_ranges.append((i, j))
    if not flat_ranges:
        return [[a, b]]
    merged_flats: List[List[int]] = []
    for lo, hi in flat_ranges:
        if merged_flats and lo <= merged_flats[-1][1]:
            merged_flats[-1][1] = max(merged_flats[-1][1], hi)
        else:
            merged_flats.append([lo, hi])
    segments: List[List[int]] = []
    cursor = a
    for lo, hi in merged_flats:
        if lo > cursor:
            segments.append([cursor, lo])
        cursor = hi
    if cursor < b:
        segments.append([cursor, b])
    return segments if segments else [[a, b]]


def _trim_rise(a: int, b: int, altitudes: Sequence[float], tol: float) -> List[int]:
    """Rogne une montée brute `[a, b]` (indices dans `altitudes`) à son
    intervalle le plus étroit qui couvre encore (min, max) de `altitudes[a:b+1]`
    à `tol` près — voir ASSUMPTIONS["trim"] (BLOQUANT, revue de code #46) pour
    le défaut que ceci corrige (une longue approche plate en amont, ou un long
    replat en aval, jamais eux-mêmes détectés comme extremum, gonflent sinon la
    distance de la montée bien au-delà de sa vraie étendue). Le début devient
    le DERNIER index encore à `tol` du minimum de l'intervalle (élimine toute
    approche plate), la fin le PREMIER index déjà à `tol` du maximum de
    l'intervalle à partir de ce nouveau début (élimine tout replat de sortie).
    Rend `[a, b]` inchangé si l'intervalle est trop court pour être rogné
    utilement (amplitude ≤ 2×`tol`)."""
    leg_min = min(altitudes[a:b + 1])
    leg_max = max(altitudes[a:b + 1])
    if leg_max - leg_min <= 2 * tol:
        return [a, b]
    start = a
    for j in range(a, b + 1):
        if altitudes[j] <= leg_min + tol:
            start = j
    end = b
    for k in range(start, b + 1):
        if altitudes[k] >= leg_max - tol:
            end = k
            break
    if end <= start:
        end = b
    return [start, end]


def _merge_climbs(rises: Sequence[Sequence[int]], altitudes: Sequence[float],
                   distances: Sequence[float], *,
                   max_dip_loss_m: float = MERGE_MAX_DIP_LOSS_M,
                   dip_relative_frac: float = MERGE_DIP_RELATIVE_FRAC,
                   max_dip_dist_m: float = MERGE_MAX_DIP_DIST_M,
                   noise_tol_m: float = 0.0) -> List[List[int]]:
    """Fusionne deux montées (déjà ROGNÉES par `_trim_rise`) CONSÉCUTIVES
    (séparées par exactement un creux, garanti par l'alternance du zigzag) si
    ce creux perd moins que le seuil applicable — le plus GRAND de
    `max_dip_loss_m` (absolu) et `dip_relative_frac` × le plus petit des deux
    gains adjacents (relatif, pour une grosse montée alpine) — sur moins que le
    seuil de DISTANCE applicable (`max_dip_dist_m` + une marge de bruit, voir
    `noise_tol_m` et ASSUMPTIONS["merge"]). Itératif jusqu'à stabilité (une
    fusion peut rapprocher deux autres montées d'un creux qui, cumulé,
    dépasserait quand même le seuil — non : le creux entre deux montées non
    adjacentes n'est jamais reconsidéré après une fusion ailleurs, seule la
    liste se raccourcit).

    `noise_tol_m` (0 par défaut — aucune marge) : la tolérance de rognage
    EFFECTIVE du segment (`detect_climbs`, déjà élargie au bruit mesuré, voir
    ASSUMPTIONS["trim"]) — revue de code #46, 3e passe, should-fix 1 : un bruit
    plus fort élargit `TRIM_TOLERANCE_M` effective, qui élargit à son tour la
    distance du creux MESURÉE entre deux montées rognées plus largement à leurs
    bords ; sans compenser le seuil de distance en conséquence, une grosse
    montée alpine à petits creux se scinde à tort plus souvent que sans bruit.
    La marge ajoutée est `2 × noise_tol_m / pente_la_plus_faible_des_deux_montées`
    (le rognage déplace chaque bord d'environ `noise_tol_m` en ALTITUDE, donc
    d'environ `noise_tol_m / pente` en DISTANCE — deux bords, d'où le facteur 2),
    plafonnée à la moitié de `max_dip_dist_m` pour qu'une montée à pente proche
    du seuil minimal (`MIN_CLIMB_AVG_GRADE`) ne voie pas ce plafond diverger."""
    merged = [list(r) for r in rises]
    changed = True
    while changed and len(merged) > 1:
        changed = False
        i = 0
        while i < len(merged) - 1:
            start_a, end_a = merged[i]
            start_b, end_b = merged[i + 1]
            dip_loss = altitudes[end_a] - altitudes[start_b]
            dip_dist = distances[start_b] - distances[end_a]
            gain_a = altitudes[end_a] - altitudes[start_a]
            gain_b = altitudes[end_b] - altitudes[start_b]
            allowed_loss = max(max_dip_loss_m, dip_relative_frac * min(gain_a, gain_b))
            allowed_dist = max_dip_dist_m
            if noise_tol_m > 0:
                dist_a = distances[end_a] - distances[start_a]
                dist_b = distances[end_b] - distances[start_b]
                grades = [g for g, d in ((gain_a / dist_a if dist_a > 0 else None, dist_a),
                                          (gain_b / dist_b if dist_b > 0 else None, dist_b))
                          if g is not None and g > 0]
                if grades:
                    margin = min(2 * noise_tol_m / min(grades), max_dip_dist_m * MERGE_DIST_MARGIN_CAP_FRAC)
                    allowed_dist = max_dip_dist_m + margin
            if dip_loss <= allowed_loss and dip_dist <= allowed_dist:
                merged[i][1] = merged[i + 1][1]
                del merged[i + 1]
                changed = True
            else:
                i += 1
    return merged


def grade_class(avg_grade: Optional[float]) -> Optional[str]:
    """Classe de pente (voir `GRADE_CLASSES`) d'une pente moyenne signée ou
    non (valeur absolue utilisée) — `None` si `avg_grade` est `None`. La pente
    est ARRONDIE au dixième de point de pourcentage (même précision que
    l'affichage) AVANT classement — voir ASSUMPTIONS["grade_classes"] : une
    valeur brute juste sous une borne (ex. 9,98 %, affichée arrondie « 10,0 %
    ») doit tomber dans la classe supérieure, jamais afficher un pourcentage
    et une classe visuellement incohérents."""
    if avg_grade is None:
        return None
    g = round(abs(avg_grade), 3)
    for lo, hi, label in GRADE_CLASSES:
        if lo <= g < hi:
            return label
    return GRADE_CLASSES[-1][2]


# ---------------------------------------------------------------------------
# Détection des montées
# ---------------------------------------------------------------------------


def detect_climbs(samples: Sequence[dict], *,
                   min_gain_m: float = MIN_CLIMB_GAIN_M,
                   min_avg_grade: float = MIN_CLIMB_AVG_GRADE,
                   merge_max_dip_loss_m: float = MERGE_MAX_DIP_LOSS_M,
                   merge_dip_relative_frac: float = MERGE_DIP_RELATIVE_FRAC,
                   merge_max_dip_dist_m: float = MERGE_MAX_DIP_DIST_M,
                   swing_noise_floor_m: float = SWING_NOISE_FLOOR_M,
                   trim_tolerance_m: float = TRIM_TOLERANCE_M,
                   trim_tolerance_noise_k: float = TRIM_TOLERANCE_NOISE_K,
                   plateau_split_max_grade: float = PLATEAU_SPLIT_MAX_GRADE,
                   smooth_taps: int = SMOOTH_TAPS,
                   max_gap_s: float = MAX_GAP_S,
                   resolution_s: float = DEFAULT_RESOLUTION_S) -> List[dict]:
    """Montées détectées sur des échantillons normalisés (`t_s, distance_m,
    altitude_m, speed_ms, ...`, triés ou non — voir `arc_samples.NORMALISED_KEYS`).
    Voir la docstring du module pour l'algorithme complet et `ASSUMPTIONS` pour
    la justification de chaque seuil.

    Rend une liste de dicts triés par `start_t_s`, chacun numéroté `index`
    (1-based) : `start_t_s`, `end_t_s`, `start_km`, `end_km`, `distance_m`,
    `gain_m`, `avg_grade` (fraction), `grade_class`, `duration_elapsed_s`,
    `duration_moving_s`, `vam_elapsed_m_h`, `vam_moving_m_h` (`None` si la
    durée correspondante est nulle). Liste vide si aucune montée ne satisfait
    les seuils — jamais une exception."""
    ordered = sorted((s for s in samples if s.get("t_s") is not None), key=lambda s: s["t_s"])
    if len(ordered) < 2:
        return []
    t_values = [s["t_s"] for s in ordered]
    climbs_out: List[dict] = []
    for segment in E.segments_by_gap(t_values, max_gap_s):
        if len(segment) < 2:
            continue
        raw_alt = [ordered[i].get("altitude_m") for i in segment]
        smoothed_alt = E.smooth_moving_average(raw_alt, smooth_taps)
        raw_dist = [ordered[i].get("distance_m") for i in segment]
        valid = [j for j in range(len(segment)) if smoothed_alt[j] is not None and raw_dist[j] is not None]
        if len(valid) < 2:
            continue
        alt_v = [smoothed_alt[j] for j in valid]
        dist_v = [raw_dist[j] for j in valid]
        idx_v = [segment[j] for j in valid]  # indices globaux dans `ordered`

        # Tolérance EFFECTIVE de rognage/découpage (revue de code #46, 2e passe,
        # should-fix 2) : plancher `trim_tolerance_m`, élargi au bruit RÉELLEMENT
        # mesuré sur l'altitude déjà lissée de CE segment — voir
        # `_robust_noise_sigma` et ASSUMPTIONS["trim"].
        effective_tol = max(trim_tolerance_m, trim_tolerance_noise_k * _robust_noise_sigma(alt_v))

        extrema = _zigzag_extrema(alt_v, swing_noise_floor_m)
        rises = _raw_rises(extrema, alt_v)
        # Rognage des EXTRÉMITÉS d'abord (BLOQUANT, revue de code #46, voir
        # ASSUMPTIONS["trim"]) : sans cela, une approche plate ou un replat de sortie
        # jamais eux-mêmes détectés comme extremum resteraient attachés à la montée
        # et fausseraient sa distance — ET fausseraient la distance du CREUX entre
        # deux montées consécutives, sur laquelle `_merge_climbs` s'appuie pour
        # décider de fusionner ou non.
        trimmed_rises = [_trim_rise(a, b, alt_v, effective_tol) for a, b in rises]
        # Découpage des plateaux INTERNES ENSUITE, sur le résultat déjà rogné
        # (BLOQUANT, revue de code #46, 2e passe, voir ASSUMPTIONS["trim"]) : un
        # plateau interne (jamais détecté par le zigzag, faute de vraie retombée)
        # est retiré s'il excède `merge_max_dip_dist_m` à pente quasi nulle — il ne
        # pourrait de toute façon jamais être fusionné ensuite. Un morceau que le
        # découpage laisse INTACT est déjà rogné (étape précédente) : ne JAMAIS le
        # rogner une seconde fois (double-rognage, même bug que le premier —
        # ASSUMPTIONS["trim"]), seuls les NOUVEAUX morceaux introduits par un
        # découpage effectif ont besoin d'un second rognage sur leurs propres bords.
        split_rises: List[List[int]] = []
        for a, b in trimmed_rises:
            pieces = _split_flat_plateaus(
                a, b, alt_v, dist_v, max_gap_dist_m=merge_max_dip_dist_m, max_grade=plateau_split_max_grade)
            if len(pieces) == 1 and pieces[0] == [a, b]:
                split_rises.append([a, b])
            else:
                split_rises.extend(_trim_rise(pa, pb, alt_v, effective_tol) for pa, pb in pieces)
        merged = _merge_climbs(split_rises, alt_v, dist_v,
                                max_dip_loss_m=merge_max_dip_loss_m,
                                dip_relative_frac=merge_dip_relative_frac,
                                max_dip_dist_m=merge_max_dip_dist_m,
                                noise_tol_m=effective_tol)

        for start_local, end_local in merged:
            gain = alt_v[end_local] - alt_v[start_local]
            distance = dist_v[end_local] - dist_v[start_local]
            if gain < min_gain_m or not distance or distance <= 0:
                continue
            avg_grade = round(gain / distance, 3)
            if avg_grade < min_avg_grade:
                continue
            gi, gj = idx_v[start_local], idx_v[end_local]
            climb_samples = ordered[gi:gj + 1]
            start_t = climb_samples[0]["t_s"]
            end_t = climb_samples[-1]["t_s"]
            duration_elapsed_s = end_t - start_t
            # Temps de mouvement (#46, revue de code) : SEULEMENT les intervalles
            # ENTRE deux échantillons de la montée — le dernier échantillon n'a pas de
            # « suivant » à l'intérieur de la montée, donc ne lui attribue aucun
            # intervalle (jamais `resolution_s` par défaut, qui ferait dépasser
            # `duration_moving_s` au-delà de `duration_elapsed_s`, la montée n'ayant
            # par définition aucun instant après son propre dernier échantillon).
            moving_s = 0.0
            n_climb = len(climb_samples)
            for k in range(n_climb - 1):
                dt = max(0.0, min(climb_samples[k + 1]["t_s"] - climb_samples[k]["t_s"], resolution_s))
                speed = climb_samples[k].get("speed_ms")
                if speed is not None and speed >= G.STOPPED_SPEED_MS:
                    moving_s += dt
            moving_s = min(moving_s, duration_elapsed_s)
            vam_elapsed = (gain / (duration_elapsed_s / 3600.0)) if duration_elapsed_s > 0 else None
            vam_moving = (gain / (moving_s / 3600.0)) if moving_s > 0 else None
            climbs_out.append({
                "start_t_s": start_t,
                "end_t_s": end_t,
                "start_km": round(dist_v[start_local] / 1000.0, 3),
                "end_km": round(dist_v[end_local] / 1000.0, 3),
                "distance_m": round(distance, 1),
                "gain_m": round(gain, 1),
                "avg_grade": avg_grade,
                "grade_class": grade_class(avg_grade),
                "duration_elapsed_s": round(duration_elapsed_s, 1),
                "duration_moving_s": round(moving_s, 1),
                "vam_elapsed_m_h": round(vam_elapsed, 1) if vam_elapsed is not None else None,
                "vam_moving_m_h": round(vam_moving, 1) if vam_moving is not None else None,
            })
    climbs_out.sort(key=lambda c: c["start_t_s"])
    for i, c in enumerate(climbs_out, start=1):
        c["index"] = i
    return climbs_out


# ---------------------------------------------------------------------------
# Courbe de puissance verticale — meilleure VAM sur fenêtres 10/20 min
# ---------------------------------------------------------------------------


def _best_window_gain(times: Sequence[float], altitudes: Sequence[float],
                       window_s: float) -> Optional[Tuple[float, float]]:
    """Plus grand gain net d'altitude sur une fenêtre d'AU MOINS `window_s`
    secondes glissée sur `times`/`altitudes` (triés par temps croissant, DÉJÀ
    limités à une seule montée) — voir ASSUMPTIONS["best_window"]. Rend
    `(gain_m, span_s)` — `span_s` est la durée RÉELLEMENT mesurée (≥
    `window_s`, jamais < : voir ASSUMPTIONS["best_window"] pour pourquoi la
    VAM doit être divisée par `span_s`, pas par `window_s`), ou `None` si la
    montée est plus courte que `window_s`."""
    n = len(times)
    if n < 2 or times[-1] - times[0] < window_s:
        return None
    best = None
    for i in range(n):
        j = bisect.bisect_left(times, times[i] + window_s, i)
        if j >= n:
            continue
        gain = altitudes[j] - altitudes[i]
        if best is None or gain > best[0]:
            best = (gain, times[j] - times[i])
    return best


def best_vam_windows(samples: Sequence[dict], climbs: Sequence[dict], *,
                      windows_s: Dict[str, float] = BEST_WINDOWS_S,
                      smooth_taps: int = SMOOTH_TAPS) -> Dict[str, Optional[float]]:
    """Meilleure VAM (m/h) sur des fenêtres d'AU MOINS `windows_s` secondes,
    glissées uniquement À L'INTÉRIEUR de chaque montée de `climbs` (voir
    `detect_climbs` et ASSUMPTIONS["best_window"]) — une « courbe de puissance
    verticale » façon courbe de puissance cycliste. Rend un dict aux mêmes clés
    que `windows_s` (défaut `BEST_WINDOWS_S`), valeurs `None` si aucune montée
    de l'activité n'atteint la durée correspondante."""
    ordered = sorted((s for s in samples if s.get("t_s") is not None), key=lambda s: s["t_s"])
    out: Dict[str, Optional[float]] = {key: None for key in windows_s}
    for climb in climbs:
        climb_samples = [s for s in ordered if climb["start_t_s"] <= s["t_s"] <= climb["end_t_s"]]
        if len(climb_samples) < 2:
            continue
        smoothed = E.smooth_moving_average([s.get("altitude_m") for s in climb_samples], smooth_taps)
        pairs = [(s["t_s"], a) for s, a in zip(climb_samples, smoothed) if a is not None]
        if len(pairs) < 2:
            continue
        times = [p[0] for p in pairs]
        altitudes = [p[1] for p in pairs]
        for key, window_s in windows_s.items():
            result = _best_window_gain(times, altitudes, window_s)
            if result is None:
                continue
            gain, span_s = result
            # Divisé par la durée RÉELLEMENT mesurée (`span_s`, ≥ `window_s` du fait de
            # la résolution des échantillons), jamais par `window_s` nominal — sinon un
            # écart de résolution surestimerait légèrement la VAM (#46, revue de code).
            vam = gain / (span_s / 3600.0) if span_s > 0 else None
            if vam is not None and (out[key] is None or vam > out[key]):
                out[key] = vam
    return {key: (round(v, 1) if v is not None else None) for key, v in out.items()}


def vam_by_grade_class(climbs: Sequence[dict]) -> Dict[str, dict]:
    """VAM (temps écoulé) moyenne par classe de pente (#46, critère
    d'acceptation) — seulement les classes réellement représentées dans
    `climbs`. `{"5-10%": {"count": N, "avg_vam_elapsed_m_h": ...}, ...}`."""
    buckets: Dict[str, List[float]] = {}
    for c in climbs:
        cls = c.get("grade_class")
        vam = c.get("vam_elapsed_m_h")
        if cls is None or vam is None:
            continue
        buckets.setdefault(cls, []).append(vam)
    return {
        cls: {"count": len(vals), "avg_vam_elapsed_m_h": round(sum(vals) / len(vals), 1)}
        for cls, vals in buckets.items()
    }


# ---------------------------------------------------------------------------
# Rapport complet
# ---------------------------------------------------------------------------


def climb_report(samples: Sequence[dict], sport: Optional[str], **kwargs) -> dict:
    """Rapport complet des montées d'une séance (#46), à partir de ses
    échantillons normalisés et de son sport — API autonome, restreinte à la
    famille course à pied (voir ASSUMPTIONS["restricted_to_run_family"]).

    Rend TOUJOURS `{"climbs", "vam_best_10min_m_h", "vam_best_20min_m_h",
    "vam_by_grade_class", "best_climb_vam_elapsed_m_h", "reason", "reason_code",
    "applicable"}` — `reason` explique un rapport vide/`None` en français,
    jamais une exception ni un échec muet (même discipline que
    `arc_decoupling.decoupling_report`). Une séance éligible sans aucune montée
    détectée (parcours plat) rend `climbs: []` avec `reason: None` — absence de
    montée n'est jamais une erreur. `reason_code`/`applicable` (#47, revue de
    code, nit) : contrepartie stable et non localisée de `reason` — voir
    `arc_descent.descent_report` pour la même discipline — `applicable` vaut
    `False` UNIQUEMENT hors de la famille course à pied (l'UI masque alors la
    section plutôt que de la présenter avec un message, jamais en testant le
    texte français de `reason`)."""
    empty = {"climbs": [], "vam_best_10min_m_h": None, "vam_best_20min_m_h": None,
              "vam_by_grade_class": {}, "best_climb_vam_elapsed_m_h": None}
    if M.sport_family(sport) != "run":
        return {**empty, "reason": "hors de la famille course à pied (arc_metrics.sport_family), "
                                    "voir ASSUMPTIONS[\"restricted_to_run_family\"]",
                "reason_code": "not_run_family", "applicable": False}
    if not samples:
        return {**empty, "reason": "aucun échantillon FIT ingéré pour cette séance",
                "reason_code": "no_samples", "applicable": True}
    climbs = detect_climbs(samples, **kwargs)
    windows = best_vam_windows(samples, climbs)
    best_climb_vam = max(
        (c["vam_elapsed_m_h"] for c in climbs if c["vam_elapsed_m_h"] is not None), default=None)
    return {
        "climbs": climbs,
        "vam_best_10min_m_h": windows["vam_best_10min_m_h"],
        "vam_best_20min_m_h": windows["vam_best_20min_m_h"],
        "vam_by_grade_class": vam_by_grade_class(climbs),
        "best_climb_vam_elapsed_m_h": best_climb_vam,
        "reason": None,
        "reason_code": None,
        "applicable": True,
    }
