#!/usr/bin/env python3
"""Découplage aérobie (Pa:HR) et facteur d'efficacité — #45, épopée #21.

## Principe

Sur une séance longue à effort stable, la fréquence cardiaque nécessaire pour
tenir la même allure « plat équivalent » (GAP, `arc_gap.py`, #44) dérive
généralement à la hausse au fil du temps (fatigue, chaleur, déshydratation).
Cette dérive — désignée dans la littérature d'entraînement d'endurance sous le
nom **Pa:HR** (« Pace:HR », popularisé par la marque TrainingPeaks — voir
`docs/marques.md`, non reproduit ici, formule publique ; protocole de
référence : Uphill Athlete, « Aerobic Threshold HR Drift Test »,
https://uphillathlete.com/aerobic-training/heart-rate-drift/ — un test
CONTRÔLÉ, allure constante en laboratoire ou sur terrain plat connu, dont le
seuil de 5 % est issu ; notre calcul l'applique tel quel à une séance de
terrain ordinaire, jamais dans les mêmes conditions contrôlées) — se mesure en
comparant le **facteur d'efficacité** (EF = allure ajustée à la pente / FC) de
la première moitié de la séance (hors échauffement) à celui de la seconde :

    EF = moyenne(vitesse GAP, m/min) / moyenne(FC, bpm)         (pondérées par le temps)
    découplage % = (EF_première_moitié − EF_seconde_moitié) / EF_première_moitié × 100

Une valeur positive signale une dérive (efficacité qui se dégrade) ; une
valeur négative ou nulle signale une séance stable, voire un athlète qui
« monte en régime ». **Repère de coaching courant, jamais un seuil validé
cliniquement** : un découplage sous 5 % est habituellement considéré comme un
signe de bonne durabilité aérobie sur les sorties longues — mais ce seuil vient
d'un protocole CONTRÔLÉ (voir ci-dessus), pas d'une sortie de terrain
quelconque ; le présenter comme un simple repère indicatif, jamais une norme.

Le GAP (jamais la vitesse brute) est utilisé aux deux moitiés : sur un
parcours vallonné, une moitié plus pentue que l'autre fausserait sinon
totalement la comparaison (une côte fait naturellement monter la FC à allure
égale). Réutilise `arc_gap.gap_sample_series`/`weighted_average` telles
quelles (#44) — jamais un second calcul de pente/GAP.

## Éligibilité et règle d'« effort stable »

Voir `ASSUMPTIONS` ci-dessous pour le détail complet et sa justification :
famille course à pied, durée de mouvement ≥ 60 min, échauffement exclu EN
PREMIER puis moitiés égales du temps de mouvement restant (protocole standard,
voir `ASSUMPTIONS["warmup"]`), pentes fortes et marche/power-hiking exclues du
calcul d'EF et de la détection d'effort stable, couverture FC/GAP suffisante
par moitié, profil de pente comparable entre les deux moitiés, et effort jugé
stable sur des fenêtres glissantes de 30 s.

## API réutilisable, pure (sans SQLite ni disque) — pour #48 (durabilité, même
famille de calcul sur le dernier tiers plutôt que la seconde moitié)

- `decoupling_report(samples, sport, resolution_s=...)` : rapport complet à
  partir des échantillons normalisés (`arc_index.samples`) et du sport de
  l'activité — TOUJOURS un dict avec une `reason` explicite en cas d'échec,
  jamais une exception. Calcule sa propre série GAP.
- `decoupling_report_from_series(series, resolution_s=...)` : même rapport à
  partir d'une série DÉJÀ augmentée par `arc_gap.gap_sample_series` — évite un
  second calcul pente/GAP pour la même activité (ex. `arc_index.compute_metrics`,
  qui en a aussi besoin pour le GAP global/par split, #44) ; ASSUME que le
  sport est déjà restreint à la famille course à pied par l'appelant, comme
  `arc_gap.activity_gap_pace_from_series`.
- `steadiness_share_pct(series, resolution_s=...)` : part du temps de
  mouvement dont le GAP (moyenne glissante 30 s) reste à ±15 % de sa médiane —
  réutilisable pour toute autre détection de séance non stable.

Stdlib uniquement (CONTRIBUTING.md).
"""

from __future__ import annotations

import bisect
import statistics
import sys
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
import arc_gap as G  # noqa: E402
import arc_metrics as M  # noqa: E402

# Résolution nominale des échantillons sous-échantillonnés (alignée sur
# `arc_samples.DEFAULT_RESOLUTION_S` / `arc_gap.DEFAULT_RESOLUTION_S`).
DEFAULT_RESOLUTION_S = G.DEFAULT_RESOLUTION_S

# Seuil d'éligibilité (#45, critère d'acceptation) : séance de mouvement d'au
# moins 60 minutes (échauffement compris) — sous ce seuil, deux moitiés
# seraient trop courtes pour qu'une dérive de FC se distingue du bruit normal
# séance à séance.
MIN_MOVING_DURATION_S = 60 * 60.0

# Échauffement exclu EN PREMIER (10 premières minutes ÉCOULÉES depuis le
# premier échantillon, arrêts compris dans ce décompte), AVANT le découpage en
# deux moitiés — protocole standard (Uphill Athlete, Friel/TrainingPeaks, voir
# ASSUMPTIONS["warmup"]) : la FC met plusieurs minutes à atteindre son régime
# de croisière (retard cardiovasculaire) ; l'inclure grossirait artificiellement
# l'EF de la première moitié. Valeur ronde documentée, pas calibrée sur des
# données réelles (aucune source publiée retenue pour une valeur plus précise).
WARMUP_S = 10 * 60.0

# Chaque moitié (temps de mouvement, post-échauffement) doit couvrir au moins
# 10 minutes : sous ce seuil, la moyenne pondérée d'une moitié devient trop
# sensible à un seul échantillon bruité.
MIN_HALF_MOVING_S = 10 * 60.0

# Pentes fortes exclues du calcul d'EF ET de la détection d'effort stable
# (#45, revue de code) : au-delà d'environ 12 %, le modèle de Minetti (#44)
# est moins fiable (voir `arc_gap.ASSUMPTIONS["model"]`, sous-estimation du
# coût réel des fortes descentes) et ces portions sont, de toute façon, le
# plus souvent marchées plutôt que courues — les mélanger à l'EF d'une
# séance de course fausserait la comparaison entre moitiés bien plus qu'elle
# ne l'éclairerait. Un profil résiduellement asymétrique entre les deux
# moitiés (ex. un aller-retour avec un flanc raide d'un côté) reste détecté
# séparément par la vérification de pente moyenne (voir
# ASSUMPTIONS["grade_asymmetry"]) : cette exclusion réduit le problème sans
# le résoudre entièrement à elle seule.
STEEP_GRADE_FRACTION = 0.12

# Vitesse en dessous de laquelle un échantillon est traité comme de la marche
# ou du power-hiking plutôt que de la course (#45, revue de code) : régime
# physiologique différent (économie de marche, pas le modèle de course de
# Minetti), exclu de l'EF et de la détection d'effort stable pour la même
# raison que les pentes fortes ci-dessus — PAS de la séance dans son
# ensemble (voir ASSUMPTIONS["steep_grade_and_walking"] pour ce que cela
# implique sur un ultra couru en run/walk). Plus haut que
# `arc_gap.STOPPED_SPEED_MS` (arrêt net) : une marche soutenue reste un
# mouvement réel, pas une pause. Seuil de repli seulement (voir `_is_walking`
# pour la cadence et le GAP, préférés quand disponibles) : une vitesse BRUTE
# lente en forte montée est souvent de la course réelle (effort intense,
# cadence de course), pas de la marche — la confondre avec de la marche sur
# ce seul critère rejetterait à tort une grosse partie des sorties en
# montagne (revue de code #45).
WALKING_SPEED_MS = 1.4

# Cadence en dessous de laquelle un échantillon est traité comme de la marche
# (#45, revue de code) — PRÉFÉRÉE à la vitesse brute quand disponible : une
# foulée de course, même lente en forte montée, reste nettement au-dessus de
# la cadence de marche (typiquement ≥ 150-160 pas/min en course, quelle que
# soit l'allure), alors qu'une vitesse brute lente peut aussi bien être de la
# course en côte raide que de la marche. Valeur ronde, jugement d'ingénierie
# (pas calibrée sur un jeu de séances réelles étiquetées course/marche).
WALKING_CADENCE_SPM = 140.0

# Couverture FC minimale par moitié (part du temps de MOUVEMENT de la moitié
# — TOUT terrain confondu, pente forte et marche comprises — où la FC est
# présente) : sous ce seuil, un pan entier de la moitié (ex. un capteur FC
# décroché 13 minutes) pourrait fausser la moyenne sans qu'on le voie — voir
# ASSUMPTIONS["hr_coverage"]. Distincte de la couverture RÉELLEMENT UTILISABLE
# pour l'EF (hors pente forte/marche, voir MIN_HALF_MOVING_S ci-dessous et
# ASSUMPTIONS["usable_running"]) : une sortie en montagne avec une FC
# complète mais beaucoup de pente forte/marche a raison d'avoir une
# couverture FC à 100 % tout en manquant de portions courues exploitables —
# deux raisons d'échec bien distinctes (revue de code #45, corrige un bug où
# les deux étaient confondues et rejetaient à tort la plupart des sorties en
# montagne réelles).
MIN_HR_COVERAGE_FRAC = 0.8

# Écart de pente moyenne maximal toléré entre les deux moitiés (fraction,
# ex. 0.03 = 3 points de pourcentage) — voir ASSUMPTIONS["grade_asymmetry"].
GRADE_ASYMMETRY_MAX = 0.03

# Détection d'« effort stable » par fenêtres glissantes (#45, critère
# d'acceptation ; voir ASSUMPTIONS["steady_effort"]) : moyenne glissante du
# GAP sur une fenêtre CENTRÉE de `STEADY_WINDOW_S` secondes, part du temps de
# mouvement dont cette moyenne reste à `STEADY_BAND_PCT` % de la médiane de
# toutes les fenêtres. Sous `STEADY_MIN_SHARE_PCT`, l'activité est jugée non
# stable.
STEADY_WINDOW_S = 30.0
STEADY_BAND_PCT = 15.0
STEADY_MIN_SHARE_PCT = 60.0
STEADY_MIN_SAMPLES = 20  # sous ce nombre de points glissants, le jugement n'est pas fiable

ASSUMPTIONS = {
    "model": (
        "Découplage aérobie (Pa:HR) et facteur d'efficacité (EF), sur le modèle popularisé par la "
        "marque TrainingPeaks (voir docs/marques.md) : EF = vitesse GAP moyenne (m/min, pondérée par "
        "le temps) / FC moyenne (bpm) sur une moitié de séance (hors échauffement) ; découplage % = "
        "(EF première moitié − EF seconde moitié) / EF première moitié × 100. Le GAP (arc_gap.py, #44), "
        "jamais la vitesse brute, est utilisé aux deux moitiés pour qu'une côte ou une descente ne "
        "fausse pas la comparaison — un profil de pente trop différent entre les deux moitiés rend "
        "quand même l'activité inéligible (ASSUMPTIONS['grade_asymmetry']), le GAP ne corrigeant pas "
        "parfaitement ce cas. Un découplage sous 5 % est un repère de coaching courant pour une bonne "
        "durabilité aérobie — PAS un seuil validé cliniquement, issu d'un protocole CONTRÔLÉ (Uphill "
        "Athlete, allure constante en conditions maîtrisées, "
        "https://uphillathlete.com/aerobic-training/heart-rate-drift/), jamais présenté comme une "
        "norme applicable telle quelle à n'importe quelle sortie de terrain."
    ),
    "restricted_to_run_family": (
        "Calculé UNIQUEMENT pour les séances de la famille course à pied (arc_metrics.sport_family == "
        "\"run\") avec des échantillons FIT ingérés — même restriction et même raison que les zones FC "
        "(#43) et le GAP (#44) : une FC de renforcement ou de vélo n'a pas le même sens physiologique."
    ),
    "min_duration": (
        f"Séance de {MIN_MOVING_DURATION_S / 60:.0f} minutes de mouvement minimum (échauffement compris) "
        "— sous ce seuil, deux moitiés seraient trop courtes pour distinguer une vraie dérive cardiaque "
        "du bruit normal séance à séance."
    ),
    "warmup": (
        f"Les {WARMUP_S / 60:.0f} premières minutes ÉCOULÉES (depuis le premier échantillon, arrêts "
        "compris dans ce décompte) sont exclues EN PREMIER, puis les échantillons restants sont "
        "partagés en deux moitiés ÉGALES de temps de mouvement — c'est le protocole standard (Uphill "
        "Athlete ; Friel/TrainingPeaks), pas un choix du projet : sur une dérive purement linéaire, "
        "exclure d'abord ou fixer la frontière avant de retirer l'échauffement donnent le même "
        "résultat. La FC met plusieurs minutes à atteindre son régime de croisière (retard "
        "cardiovasculaire) ; l'inclure gonflerait artificiellement l'EF de la première moitié (FC "
        "encore basse pour l'allure déjà courue) et donc le découplage mesuré. Valeur ronde documentée, "
        "pas calibrée sur des données réelles. Le refroidissement (fin de séance) n'est volontairement "
        "PAS exclu séparément : le découpage en deux moitiés absorbe déjà une petite portion finale "
        "plus lente dans la seconde moitié, et une exclusion dédiée ajouterait un paramètre de plus "
        "sans justification aussi claire que l'échauffement."
    ),
    "stopped_samples": (
        "Les instants à l'arrêt (vitesse sous arc_gap.STOPPED_SPEED_MS — feu rouge, ravitaillement, "
        "pause) sont exclus du découpage en deux moitiés, qui se fait sur le TEMPS DE MOUVEMENT cumulé "
        "(jamais le temps écoulé) : une pause au milieu de la séance ne doit pas déplacer "
        "artificiellement la frontière entre les deux moitiés, ni peser dans la moyenne d'une moitié."
    ),
    "steep_grade_and_walking": (
        f"Les échantillons de pente forte (au-delà de ±{STEEP_GRADE_FRACTION * 100:.0f} %) et de marche/"
        f"power-hiking (vitesse sous {WALKING_SPEED_MS:.1f} m/s) sont exclus du calcul de l'EF ET de la "
        "détection d'effort stable, dans les DEUX moitiés — jamais de la séance dans son ensemble (elle "
        "reste éligible si le reste suffit). Au-delà du seuil de pente, le modèle de Minetti (#44) est "
        "moins fiable (voir arc_gap.ASSUMPTIONS) et ces portions sont le plus souvent marchées ; les "
        "mélanger à l'EF de la course fausserait la comparaison entre moitiés. Conséquence assumée pour "
        "un ultra couru en run/walk : le découplage porte alors UNIQUEMENT sur les portions courues, "
        "jamais sur la marche — une sortie très majoritairement marchée devient inéligible par manque "
        "de couverture (ASSUMPTIONS['hr_coverage']) plutôt que de mélanger deux régimes physiologiques "
        "différents dans une seule moyenne."
    ),
    "hr_coverage": (
        f"Chaque moitié doit avoir au moins {MIN_HR_COVERAGE_FRAC * 100:.0f} % de son temps de mouvement "
        "couvert par une FC présente — TOUT terrain confondu, pente forte et marche COMPRISES : sous ce "
        "seuil (capteur FC décroché sur une longue portion), la moyenne de cette moitié porterait sur "
        "une fraction non représentative de son temps réel, ce qui peut fausser le découplage mesuré "
        "dans un sens ou dans l'autre selon ce qui manque. Distinct d'une absence totale de FC (séance "
        "sans capteur), qui a sa propre raison plus tôt dans le pipeline, ET distinct de la couverture "
        "RÉELLEMENT UTILISABLE pour l'EF (voir ASSUMPTIONS['usable_running']) : une sortie en montagne "
        "peut avoir une FC complète (100 % de couverture ici) tout en manquant de portions courues "
        "exploitables (beaucoup de pente forte/marche) — mélanger les deux critères en un seul (revue de "
        "code #45, correction apportée) rejetait à tort la plupart des sorties de montagne réelles avec "
        "une FC pourtant complète (ex. mesuré sur des profils synthétiques : vallonné ±12 % à 64-86 % de "
        "« couverture » avant correction, ±15-25 % à 13-51 %, répétitions à allure adaptée ±10 % à 33 %, "
        "alors que la FC y était mesurée à 100 % du temps)."
    ),
    "usable_running": (
        f"Indépendamment de la couverture FC ci-dessus, chaque moitié doit conserver au moins "
        f"{MIN_HALF_MOVING_S / 60:.0f} minutes de temps RÉELLEMENT COURU exploitable (FC et GAP présents, "
        "hors pente forte et marche, voir ASSUMPTIONS['steep_grade_and_walking']) — une DURÉE ABSOLUE, "
        "jamais une part relative du temps de mouvement (une part minimale pénaliserait à tort les "
        "sorties de montagne où la pente forte/la marche occupent une portion importante mais où il "
        "reste largement assez de course exploitable en minutes). Sous ce seuil, l'activité est jugée "
        "inéligible : « trop peu de portions courues exploitables », distinct de « FC incomplète » "
        "ci-dessus — deux causes différentes du même symptôme (aucun chiffre affiché)."
    ),
    "grade_asymmetry": (
        f"Si la pente moyenne (pondérée par le temps, sur les échantillons utilisés pour l'EF) diffère "
        f"de plus de {GRADE_ASYMMETRY_MAX * 100:.0f} points entre les deux moitiés (ex. un aller-retour "
        "avec la montée dans une moitié et la descente dans l'autre), l'activité est jugée inéligible : "
        "le GAP corrige l'effet de la pente sur l'allure, mais pas parfaitement (biais connu du modèle "
        "de Minetti en forte descente, arc_gap.ASSUMPTIONS) — un profil trop différent entre les deux "
        "moitiés peut donc produire un découplage mesuré qui reflète surtout le relief, pas une vraie "
        "dérive cardiaque."
    ),
    "halves": (
        "Les deux moitiés (post-échauffement) sont découpées sur le TEMPS DE MOUVEMENT cumulé, jamais "
        "la distance ni le temps écoulé : une moitié plus lente (fatigue, montée) couvrirait sinon "
        "moins de distance mais devrait rester comparable en durée réelle d'effort. Chaque moitié doit "
        f"conserver au moins {MIN_HALF_MOVING_S / 60:.0f} minutes de mouvement, sinon l'activité est "
        "jugée inéligible (durée exploitable insuffisante après exclusion de l'échauffement)."
    ),
    "steady_effort": (
        "Règle d'« effort stable » (portions non stables exclues, critère d'acceptation #45) : moyenne "
        f"glissante du GAP sur une fenêtre CENTRÉE de {STEADY_WINDOW_S:.0f} secondes (moyenne simple, "
        "pas pondérée par le temps — une simplification raisonnable vu la résolution quasi uniforme des "
        "échantillons sous-échantillonnés), calculée échantillon par échantillon sur les portions "
        "utilisables (mouvement, hors pente forte/marche, voir ASSUMPTIONS['steep_grade_and_walking']). "
        f"Part du temps de mouvement dont cette moyenne glissante reste à {STEADY_BAND_PCT:.0f} % de la "
        f"médiane de toutes les fenêtres : sous {STEADY_MIN_SHARE_PCT:.0f} %, l'activité est jugée non "
        "stable (fractionné probable) et le découplage n'est pas calculé. Une fenêtre GLISSANTE et "
        "CENTRÉE (pas des seaux disjoints d'une minute) est nécessaire pour détecter un fractionné dont "
        "la période coïncide avec la taille du seau — un fractionné 30 s/30 s moyenné dans des seaux "
        "d'une minute contient toujours UN cycle complet effort/récupération par seau, ce qui annule "
        "artificiellement sa variabilité mesurée (piège corrigé lors de la revue de code de #45). Ni le "
        "titre/l'intensité déclarée de la séance, ni une détection d'intervalles plus sophistiquée "
        "(repérage de pics répétés) ne sont utilisés : cette règle statistique unique reste "
        "volontairement simple. Avec moins de "
        f"{STEADY_MIN_SAMPLES} points glissants exploitables, le jugement n'est pas fiable et cette "
        "règle est ignorée (pas assez de points pour distinguer un vrai fractionné d'un artefact). "
        "LIMITE CONNUE, documentée honnêtement (revue de code #45) : cette règle juge la dispersion "
        "autour d'une médiane UNIQUE pour toute la séance, elle ne distingue donc pas un vrai fractionné "
        "d'un bloc tempo unique et soutenu (ex. 20 minutes à allure seuil au milieu d'une sortie sinon "
        "facile) — selon sa durée relative au reste de la séance, un tel bloc peut soit être absorbé "
        "sans déclencher le seuil (la médiane glisse peu, l'essentiel du temps reste proche d'elle), "
        "soit déclencher à tort un verdict « non stable » alors qu'il s'agit d'un seul changement de "
        "régime contrôlé, pas d'une alternance répétée. Un test dédié (repérage d'un unique plateau "
        "soutenu plutôt qu'une alternance) pourrait affiner ce cas mais n'est pas fait ici, pour rester "
        "volontairement simple."
    ),
    "whole_activity_ef": (
        "Le facteur d'efficacité « séance entière » (ef_whole) est calculé sur TOUS les échantillons "
        "utilisables post-échauffement en mouvement (les deux moitiés réunies, mêmes exclusions que "
        "l'EF par moitié), pour une valeur unique comparable d'une séance à l'autre dans la tendance "
        "(indépendante du découpage en deux moitiés)."
    ),
}


def _dt_to_next(ordered: Sequence[dict], i: int, resolution_s: float) -> float:
    n = len(ordered)
    dt = ordered[i + 1]["t_s"] - ordered[i]["t_s"] if i + 1 < n else resolution_s
    return max(0.0, min(dt, resolution_s))


def _weighted_time(series: Sequence[dict], resolution_s: float) -> float:
    return sum(_dt_to_next(series, i, resolution_s) for i in range(len(series)))


def _is_moving(sample: dict) -> bool:
    return (sample.get("speed_ms") or 0.0) >= G.STOPPED_SPEED_MS


def _is_walking(sample: dict) -> bool:
    """Marche/power-hiking plutôt que course (#45, revue de code) : la cadence
    (`cadence_spm`), quand disponible, est préférée à toute mesure de vitesse
    (une foulée de course reste nettement au-dessus de la cadence de marche,
    même lente en forte montée — voir `WALKING_CADENCE_SPM`) ; à défaut, le
    GAP (vitesse « plat équivalent », déjà ajustée à la pente) est préféré à
    la vitesse BRUTE, qui confondrait une course lente en côte raide avec de
    la marche ; la vitesse brute n'est utilisée qu'en tout dernier recours,
    quand ni la cadence ni le GAP ne sont disponibles."""
    cadence = sample.get("cadence_spm")
    if cadence is not None:
        return cadence < WALKING_CADENCE_SPM
    gap_speed = sample.get("gap_speed_ms")
    if gap_speed is not None:
        return gap_speed < WALKING_SPEED_MS
    speed = sample.get("speed_ms")
    return speed is not None and speed < WALKING_SPEED_MS


def _is_steep(sample: dict) -> bool:
    grade = sample.get("grade")
    return grade is not None and abs(grade) > STEEP_GRADE_FRACTION


def _usable_for_ef(sample: dict) -> bool:
    """Échantillon utilisable pour l'EF et la détection d'effort stable (#45,
    revue de code) : en mouvement, ni trop pentu, ni à l'allure marche — voir
    ASSUMPTIONS["steep_grade_and_walking"]."""
    return _is_moving(sample) and not _is_steep(sample) and not _is_walking(sample)


def _rolling_gap_avgs(ordered: Sequence[dict], window_s: float) -> List[Optional[float]]:
    """Moyenne glissante CENTRÉE (fenêtre `[t - window_s/2, t + window_s/2]`,
    moyenne simple sur `gap_speed_ms`, voir ASSUMPTIONS["steady_effort"] pour
    pourquoi une fenêtre glissante plutôt que des seaux disjoints) par
    échantillon de `ordered` (triée par `t_s`, un seul régime physiologique
    déjà filtré par l'appelant). `None` pour un échantillon sans aucun voisin
    exploitable dans sa fenêtre."""
    times = [s["t_s"] for s in ordered]
    values = [s.get("gap_speed_ms") for s in ordered]
    half_w = window_s / 2.0
    out: List[Optional[float]] = [None] * len(ordered)
    for i, t in enumerate(times):
        lo = bisect.bisect_left(times, t - half_w)
        hi = bisect.bisect_right(times, t + half_w)
        vs = [v for v in values[lo:hi] if v is not None]
        if vs:
            out[i] = sum(vs) / len(vs)
    return out


def steadiness_share_pct(series: Sequence[dict], *, window_s: float = STEADY_WINDOW_S,
                          band_pct: float = STEADY_BAND_PCT,
                          resolution_s: float = DEFAULT_RESOLUTION_S) -> Optional[float]:
    """Part (%) du temps de mouvement de `series` (déjà filtrée : mouvement,
    hors pente forte/marche) dont la moyenne glissante du GAP (`_rolling_gap_avgs`)
    reste à `band_pct` % de sa médiane — voir ASSUMPTIONS["steady_effort"].
    `None` si moins de `STEADY_MIN_SAMPLES` fenêtres exploitables (pas assez de
    points pour juger, jamais une fausse alerte de fractionné)."""
    ordered = sorted((s for s in series if s.get("t_s") is not None), key=lambda s: s["t_s"])
    window_avgs = _rolling_gap_avgs(ordered, window_s)
    finite = [v for v in window_avgs if v is not None]
    if len(finite) < STEADY_MIN_SAMPLES:
        return None
    median_v = statistics.median(finite)
    if not median_v:
        return None
    band = band_pct / 100.0 * median_v
    in_band_w = 0.0
    total_w = 0.0
    n = len(ordered)
    for i in range(n):
        if window_avgs[i] is None:
            continue
        w = _dt_to_next(ordered, i, resolution_s)
        total_w += w
        if abs(window_avgs[i] - median_v) <= band:
            in_band_w += w
    return (in_band_w / total_w * 100.0) if total_w > 0 else None


def _split_by_moving_time_n(series: Sequence[dict], n_portions: int, *,
                             resolution_s: float = DEFAULT_RESOLUTION_S) -> List[List[dict]]:
    """Découpe `series` (déjà post-échauffement, triée ou non) en `n_portions`
    portions ÉGALES sur le temps de MOUVEMENT cumulé (généralisation partagée
    par `_split_by_moving_time`, deux portions/#45, et `arc_durability.py`,
    trois portions/#48 — voir `ASSUMPTIONS["halves"]`/`["stopped_samples"]`,
    valables pour n'importe quel nombre de portions égales). Rend une liste de
    `n_portions` listes — les échantillons à l'arrêt n'apparaissent dans
    AUCUNE portion ; les pentes fortes et la marche restent dans leur portion
    (exclues seulement de l'EF/de la détection d'effort stable, voir
    `_usable_for_ef`, pas du découpage temporel lui-même). Un échantillon est
    affecté à la première portion dont la borne haute (`total * (k+1) /
    n_portions`) n'est pas encore atteinte par le temps de mouvement cumulé
    ÉCOULÉ AVANT lui — même règle de frontière que l'ancien découpage en deux
    moitiés (`running < halfway`), généralisée à `n_portions` bornes."""
    ordered = sorted((s for s in series if s.get("t_s") is not None), key=lambda s: s["t_s"])
    moving = [(i, s) for i, s in enumerate(ordered) if _is_moving(s)]
    weights = {i: _dt_to_next(ordered, i, resolution_s) for i, _s in moving}
    total_moving_s = sum(weights.values())
    portions: List[List[dict]] = [[] for _ in range(n_portions)]
    boundaries = [total_moving_s * (k + 1) / n_portions for k in range(n_portions - 1)]
    running = 0.0
    for i, s in moving:
        portion_idx = n_portions - 1
        for k, boundary in enumerate(boundaries):
            if running < boundary:
                portion_idx = k
                break
        portions[portion_idx].append(s)
        running += weights[i]
    return portions


def _split_by_moving_time(series: Sequence[dict], *,
                           resolution_s: float = DEFAULT_RESOLUTION_S) -> Tuple[List[dict], List[dict]]:
    """Découpe `series` (déjà post-échauffement, triée ou non) en deux moitiés
    ÉGALES sur le temps de MOUVEMENT cumulé (voir `ASSUMPTIONS["halves"]`/
    `["stopped_samples"]`). Rend `(moitié_1, moitié_2)` — les échantillons à
    l'arrêt n'apparaissent dans AUCUNE des deux moitiés ; les pentes fortes et
    la marche restent dans leur moitié (exclues seulement de l'EF/de la
    détection d'effort stable, voir `_usable_for_ef`, pas du découpage
    temporel lui-même). Cas particulier (`n_portions=2`) de
    `_split_by_moving_time_n` — voir #48 (durabilité) pour la généralisation à
    trois portions, sans aucun changement de comportement ici."""
    half1, half2 = _split_by_moving_time_n(series, 2, resolution_s=resolution_s)
    return half1, half2


def _hr_coverage_frac(half_raw: Sequence[dict], resolution_s: float) -> float:
    """Part du temps de MOUVEMENT de `half_raw` (déjà en mouvement uniquement,
    voir `_split_by_moving_time`) où la FC est présente — TOUT terrain
    confondu, pente forte et marche COMPRISES (voir ASSUMPTIONS["hr_coverage"]
    pour pourquoi cette couverture est volontairement indépendante de la
    règle « portions courues exploitables » de `_usable_running_time`, revue
    de code #45 : mélanger les deux rejetait à tort la plupart des sorties en
    montagne réelles, où la FC est complète mais une bonne part du temps est
    en forte pente ou marchée)."""
    total = 0.0
    covered = 0.0
    n = len(half_raw)
    for i in range(n):
        w = _dt_to_next(half_raw, i, resolution_s)
        total += w
        if half_raw[i].get("hr_bpm") is not None:
            covered += w
    return (covered / total) if total > 0 else 0.0


def _ef(series: Sequence[dict], *, resolution_s: float = DEFAULT_RESOLUTION_S) -> Optional[float]:
    """Facteur d'efficacité (vitesse GAP moyenne en m/min / FC moyenne en bpm),
    pondéré par le temps, sur `series` — les deux moyennes DOIVENT porter sur
    le MÊME sous-ensemble d'échantillons (FC et GAP tous deux présents, voir
    l'appelant) : les calculer sur des sous-ensembles différents biaiserait le
    ratio dès qu'un trou de FC ne coïncide pas avec un trou de GAP (revue de
    code #45). `None` sans échantillon exploitable."""
    if not series:
        return None
    mean_gap_ms = G.weighted_average(series, "gap_speed_ms", resolution_s)
    mean_hr = G.weighted_average(series, "hr_bpm", resolution_s)
    if mean_gap_ms is None or not mean_hr:
        return None
    return (mean_gap_ms * 60.0) / mean_hr


def decoupling_report_from_series(series: Sequence[dict], *,
                                   resolution_s: float = DEFAULT_RESOLUTION_S) -> dict:
    """Rapport de découplage aérobie (#45) à partir d'une série DÉJÀ augmentée
    par `arc_gap.gap_sample_series` — évite un second calcul pente/GAP pour la
    même activité (voir `arc_gap.activity_gap_pace_from_series` pour la même
    discipline avec le GAP lui-même, #44). ASSUME que `series` est déjà
    restreinte à la famille course à pied par l'appelant (comme
    `activity_gap_pace_from_series`) — voir `decoupling_report` pour une API
    autonome qui vérifie le sport elle-même.

    Rend TOUJOURS `{"decoupling_pct", "ef_whole", "ef_first_half",
    "ef_second_half", "moving_duration_s", "eligible", "reason"}` — `reason`
    explique un `None`/`eligible: False`, jamais une exception ni un échec
    muet (même discipline que `arc_index.activity_gap_report`/
    `activity_zone_report`, #43/#44)."""
    empty = {"decoupling_pct": None, "ef_whole": None, "ef_first_half": None,
             "ef_second_half": None, "moving_duration_s": None, "eligible": False}
    ordered = sorted((s for s in series if s.get("t_s") is not None), key=lambda s: s["t_s"])
    if not ordered:
        return {**empty, "reason": "aucun échantillon exploitable (t_s manquant)"}

    whole_moving_s = sum(_dt_to_next(ordered, i, resolution_s) for i, s in enumerate(ordered) if _is_moving(s))
    if whole_moving_s < MIN_MOVING_DURATION_S:
        return {**empty, "moving_duration_s": round(whole_moving_s, 1),
                "reason": f"durée de mouvement insuffisante (< {MIN_MOVING_DURATION_S / 60:.0f} min), "
                          "voir ASSUMPTIONS[\"min_duration\"]"}

    # Échauffement exclu EN PREMIER (protocole standard, voir ASSUMPTIONS["warmup"]),
    # PUIS découpage du reste en deux moitiés ÉGALES de temps de mouvement.
    t0 = ordered[0]["t_s"]
    post_warmup = [s for s in ordered if s["t_s"] - t0 >= WARMUP_S]
    if not post_warmup:
        return {**empty, "moving_duration_s": round(whole_moving_s, 1),
                "reason": "aucun échantillon après exclusion de l'échauffement, "
                          "voir ASSUMPTIONS[\"warmup\"]"}

    half1_raw, half2_raw = _split_by_moving_time(post_warmup, resolution_s=resolution_s)
    half1_moving_s = _weighted_time(half1_raw, resolution_s)
    half2_moving_s = _weighted_time(half2_raw, resolution_s)
    if half1_moving_s < MIN_HALF_MOVING_S or half2_moving_s < MIN_HALF_MOVING_S:
        return {**empty, "moving_duration_s": round(whole_moving_s, 1),
                "reason": "durée exploitable insuffisante après exclusion de l'échauffement "
                          f"(< {MIN_HALF_MOVING_S / 60:.0f} min de mouvement sur au moins une moitié), "
                          "voir ASSUMPTIONS[\"halves\"]"}

    coverage1 = _hr_coverage_frac(half1_raw, resolution_s)
    coverage2 = _hr_coverage_frac(half2_raw, resolution_s)
    if coverage1 < MIN_HR_COVERAGE_FRAC or coverage2 < MIN_HR_COVERAGE_FRAC:
        return {**empty, "moving_duration_s": round(whole_moving_s, 1),
                "reason": f"FC incomplète sur au moins une moitié (couverture {coverage1 * 100:.0f} % / "
                          f"{coverage2 * 100:.0f} %, minimum {MIN_HR_COVERAGE_FRAC * 100:.0f} %), voir "
                          "ASSUMPTIONS[\"hr_coverage\"]"}

    usable1 = [s for s in half1_raw if _usable_for_ef(s) and s.get("hr_bpm") is not None
               and s.get("gap_speed_ms") is not None]
    usable2 = [s for s in half2_raw if _usable_for_ef(s) and s.get("hr_bpm") is not None
               and s.get("gap_speed_ms") is not None]
    usable1_s = _weighted_time(usable1, resolution_s)
    usable2_s = _weighted_time(usable2, resolution_s)
    if usable1_s < MIN_HALF_MOVING_S or usable2_s < MIN_HALF_MOVING_S:
        return {**empty, "moving_duration_s": round(whole_moving_s, 1),
                "reason": "trop peu de portions courues exploitables (hors pente forte/marche) sur au "
                          f"moins une moitié (< {MIN_HALF_MOVING_S / 60:.0f} min), voir "
                          "ASSUMPTIONS[\"usable_running\"]"}

    grade1 = G.weighted_average(usable1, "grade", resolution_s)
    grade2 = G.weighted_average(usable2, "grade", resolution_s)
    if grade1 is not None and grade2 is not None and abs(grade1 - grade2) > GRADE_ASYMMETRY_MAX:
        return {**empty, "moving_duration_s": round(whole_moving_s, 1),
                "reason": f"profil de pente trop différent entre les deux moitiés (pente moyenne "
                          f"{grade1 * 100:+.1f} % vs {grade2 * 100:+.1f} %), voir "
                          "ASSUMPTIONS[\"grade_asymmetry\"]"}

    share_pct = steadiness_share_pct(usable1 + usable2, resolution_s=resolution_s)
    if share_pct is not None and share_pct < STEADY_MIN_SHARE_PCT:
        return {**empty, "moving_duration_s": round(whole_moving_s, 1),
                "reason": f"effort jugé non stable ({share_pct:.0f} % du temps de mouvement seulement "
                          f"proche du GAP médian, minimum {STEADY_MIN_SHARE_PCT:.0f} %, fractionné "
                          "probable), voir ASSUMPTIONS[\"steady_effort\"]"}

    ef1 = _ef(usable1, resolution_s=resolution_s)
    ef2 = _ef(usable2, resolution_s=resolution_s)
    if ef1 is None or ef2 is None:
        return {**empty, "moving_duration_s": round(whole_moving_s, 1),
                "reason": "FC ou GAP insuffisant sur au moins une des deux moitiés"}

    ef_whole = _ef(usable1 + usable2, resolution_s=resolution_s)
    decoupling_pct = round((ef1 - ef2) / ef1 * 100.0, 2) if ef1 else None
    return {
        "decoupling_pct": decoupling_pct,
        "ef_whole": round(ef_whole, 4) if ef_whole is not None else None,
        "ef_first_half": round(ef1, 4),
        "ef_second_half": round(ef2, 4),
        "moving_duration_s": round(whole_moving_s, 1),
        "eligible": True,
        "reason": None,
    }


def decoupling_report(samples: Sequence[dict], sport: Optional[str], *,
                       resolution_s: float = DEFAULT_RESOLUTION_S, **grade_kwargs) -> dict:
    """Rapport de découplage aérobie (#45) d'une séance, à partir de ses
    échantillons normalisés (`arc_index.samples`/`samples_by_garmin_id`) et de
    son sport — API autonome qui calcule sa propre série GAP (voir
    `decoupling_report_from_series` pour réutiliser une série déjà calculée,
    ex. `arc_index.compute_metrics`, qui en a aussi besoin pour le GAP global/
    par split, #44)."""
    if M.sport_family(sport) != "run":
        return {"decoupling_pct": None, "ef_whole": None, "ef_first_half": None, "ef_second_half": None,
                "moving_duration_s": None, "eligible": False,
                "reason": "hors de la famille course à pied (arc_metrics.sport_family), "
                          "voir ASSUMPTIONS[\"restricted_to_run_family\"]"}
    if not samples:
        return {"decoupling_pct": None, "ef_whole": None, "ef_first_half": None, "ef_second_half": None,
                "moving_duration_s": None, "eligible": False,
                "reason": "aucun échantillon FIT ingéré pour cette séance"}
    series = G.gap_sample_series(samples, **grade_kwargs)
    return decoupling_report_from_series(series, resolution_s=resolution_s)
