# Dépense énergétique modèle

Le tableau de bord et les agents affichent parfois **deux chiffres de kcal**
pour une même séance : celui de Garmin, et celui d'un **modèle indépendant**
calculé par le projet. Cette page explique pourquoi, comment ce modèle
fonctionne, ce qu'il vaut, et ses limites.

<!-- arc-video:ravito -->
<div class="arc-video-card" markdown>

[![Ravito](video/ravito/poster.jpg)](video/ravito/index.html)

<div markdown>

<span class="arc-video__meta">En vidéo · Étape 08 · 1 min 43</span>

**[Ravito](video/ravito/index.html)** — Une phrase libre devient des données : le modèle extrait, le script calcule, et ne devine jamais un produit.

[Regarder](video/ravito/index.html) · [English](video/ravito/index.html?lang=en) · [Toutes les vidéos](videos.md)

</div>

</div>
<!-- /arc-video -->


## Pourquoi deux chiffres ?

**Garmin (`calories_kcal`) reste la référence par défaut, partout** : bilan
nutritionnel, rapports, comparaisons dans le temps. Le modèle du projet ne
remplace jamais cette valeur. Il sert à deux choses, bien distinctes :

1. **Un contrôle indépendant** de la séance déjà enregistrée : si l'écart
   entre les deux chiffres est important, c'est souvent le signe d'un capteur
   de fréquence cardiaque défaillant (optique au poignet, contact perdu) ou
   d'une séance mal taguée (mauvais sport sélectionné) — jamais la preuve que
   l'un des deux chiffres est « le bon » en particulier. Les deux restent des
   **estimations**.
2. **Un outil de prévision**, utilisé par l'agent stratège de course pour
   estimer, avant une course, la dépense énergétique attendue par section du
   parcours — utile pour caler un plan de ravitaillement, alors qu'aucune
   mesure Garmin n'existe encore puisque la course n'a pas eu lieu.

## Comment le modèle calcule

Le calcul distingue trois régimes selon la vitesse de déplacement, avec un
coefficient différent pour chacun :

- **Course** : l'équation RE3 (Looney, Hoogkamer & Kram, 2025), qui calcule
  une puissance métabolique à partir de la vitesse et de la pente — une pente
  en montée coûte plus cher, une descente peut réduire ce coût mais jamais le
  compenser exactement (dépenser dans une montée de 10 % n'est pas l'inverse
  de gagner dans une descente de 10 %).
- **Marche** : un polynôme dédié de Minetti *et al.* (2002), la même étude de
  référence que celle qui alimente l'allure ajustée à la pente (« GAP ») du
  tableau de bord.
- **Arrêt** (ravitaillement, feu rouge, pause) : le seul métabolisme « debout »
  continue de coûter de l'énergie, sans aucun coût de déplacement.

Le calcul se fait échantillon par échantillon depuis les données brutes du
fichier FIT (jamais sur une pente ou une vitesse moyennées sur toute la
séance, qui masqueraient les à-coups d'un parcours vallonné), puis les
contributions sont sommées. Les sources exactes (articles scientifiques, DOI)
sont listées dans [Marques et métriques — des formules publiques, des noms
génériques](marques.md#des-formules-publiques-des-noms-generiques).

## La validation

Le modèle a été comparé aux données Garmin sur **7 séances réelles** d'un
athlète (aucune donnée personnelle — ni poids, ni nom de séance, ni date —
n'est reproduite ici, seul le résultat statistique de la comparaison) :

- **Route** : écart d'environ ±6 % par rapport à Garmin.
- **Trail** : le modèle est systématiquement un peu au-dessus de Garmin, entre
  +3 % et +5 %.

Cette différence de biais entre route et trail est justement la raison pour
laquelle le tableau de bord (vue [Analyse](dashboard/views.md#analyse))
sépare les deux dans son suivi de fidélité du modèle dans le temps, plutôt que
de les mélanger dans une seule courbe.

## L'alerte à 15 %

Un écart de plus de 15 % entre Garmin et le modèle, sur une séance donnée,
déclenche un signalement (jamais silencieux) dans le retour de séance de
l'agent coach. Les causes les plus fréquentes, ni certaines ni exhaustives :

- un capteur de fréquence cardiaque optique qui a mal accroché (bras, poignet
  serré différemment, froid) ;
- une séance mal taguée (par exemple une randonnée enregistrée comme course) ;
- une forte chaleur, qui augmente le travail cardiovasculaire réel sans que le
  modèle du projet ne le compense (voir [Les limites](#les-limites)) ;
- un poids de référence périmé (le modèle a besoin du poids de l'athlète à la
  date de la séance).

Ce signalement est un point de vigilance, jamais un verdict sur la séance ni
sur la fiabilité de l'une ou l'autre source.

## Brut vs net

Le modèle rend toujours une valeur **brute**, métabolisme de base compris —
directement comparable à `calories_kcal` Garmin, qui est également une valeur
brute. Quand le métabolisme de base de la séance est connu (`bmr_calories`
côté Garmin), le tableau de bord affiche aussi une valeur **nette** (brute
moins métabolisme de base) des deux côtés, à titre indicatif.

Le débit énergétique pendant l'effort (kcal/h, utilisé pour le ravitaillement
en course) se raisonne toujours en **kcal/h bruts** — jamais en net, qui
exclurait à tort le métabolisme de base que le corps continue de couvrir
pendant l'effort. Et le modèle n'est jamais additionné une seconde fois à la
dépense énergétique **journalière** totale de Garmin (`burned_kcal`), qui
inclut déjà les séances du jour : l'ajouter par-dessus compterait deux fois la
même dépense.

## La prévision de course

Avant une course, l'agent stratège de course calcule une dépense énergétique
**prévue** par section du parcours, à partir du même moteur (voir [Stratège de
course — dépense énergétique prévue par section](agents/course-strategist.md#depense-energetique-prevue-par-section)).
Ce calcul a besoin du poids de l'athlète à la date de la course, et du poids
du sac/des flasques/du matériel porté (`--pack-kg`) pour être fidèle — sans
cette information, le calcul suppose 0 kg et le dit explicitement, jamais une
estimation inventée à sa place.

## La calibration personnelle

Une fois qu'un athlète a suffisamment de séances mesurées (Garmin **et**
modèle disponibles pour la même séance), le projet peut apprendre un facteur
de correction **personnel**, séparément pour la route et pour le trail — sur
l'écart médian réellement observé chez CET athlète, sur les 26 dernières
semaines glissantes. Une minorité de séances clairement aberrantes par
rapport au reste du panier (par exemple un capteur de fréquence cardiaque
manifestement défaillant, très éloigné de toutes les autres séances du même
panier) est exclue avant le calcul final, pour ne jamais fausser la
calibration des séances réellement comparables entre elles.

Trois statuts possibles :

- **Échantillon insuffisant** : moins de 15 séances retenues sur la fenêtre —
  aucun facteur n'est appliqué (facteur neutre).
- **Non nécessaire** : l'écart médian est déjà proche de zéro (5 % ou moins) —
  calibrer sur ce qui n'est que du bruit de mesure serait une fausse
  précision, aucun facteur n'est appliqué.
- **Appliquée** : l'écart médian est net et l'échantillon est suffisant — un
  facteur personnel est appliqué, toujours borné à une plage prudente (entre
  0,8 et 1,2 : un écart plus extrême signalerait plus probablement un problème
  de saisie qu'un vrai biais du modèle).

**Cette calibration ne s'applique JAMAIS aux séances déjà mesurées** — le
modèle affiché sur une fiche de séance passée, ou dans le graphique de
tendance de la vue Analyse, reste toujours le calcul **brut**, sans aucune
correction. Elle s'applique uniquement aux **prévisions** de future course
(voir [ci-dessus](#la-prevision-de-course)), au total prévu comme à chaque
section du parcours : quand elle est active, le stratège de course cite la
valeur calibrée en précisant sur combien de séances elle a été apprise et quel
facteur a été utilisé, jamais comme une mesure.

**Le panier (route ou trail) est choisi depuis le parcours de la course à
venir, pas depuis le profil habituel de l'athlète** : le D+ par kilomètre du
fichier GPX analysé détermine automatiquement le panier retenu (un parcours
avec peu de D+ au kilomètre est traité comme route, un parcours plus accidenté
comme trail). L'athlète peut aussi forcer ce choix explicitement — utile pour
un parcours dont le tracé seul ne dit pas tout (un sentier régulier peu
vallonné mais couru en conditions clairement « trail », par exemple).

Le statut de calibration par panier est visible en un coup d'œil dans la vue
[Analyse](dashboard/views.md#analyse) du tableau de bord, en bas du graphique
de dépense énergétique.

Exemple de sortie JSON (`python3 scripts/arc_index.py energy --calibration`),
sur un workspace synthétique, sans aucune donnée personnelle réelle :

```json
{
  "model_id": "re3-walk/2",
  "window_weeks": 26,
  "min_n": 15,
  "not_needed_band_pct": 5.0,
  "factor_min": 0.8,
  "factor_max": 1.2,
  "buckets": {
    "route": {"n": 18, "ratio_median": 1.062, "ratio_iqr": 0.041, "status": "applied", "factor": 1.062},
    "trail": {"n": 9, "ratio_median": 0.978, "ratio_iqr": 0.03, "status": "insufficient", "factor": 1.0}
  }
}
```

## Rattraper l'historique

Le modèle se calcule automatiquement pour toute séance dont le fichier FIT est
déjà présent dans le workspace. Il ne manque donc que sur les séances plus
anciennes dont le FIT n'a jamais été téléchargé — voir la procédure complète
dans [Téléchargement FIT — Rattraper l'historique pour la dépense énergétique
modèle](skills/fit-download.md#rattraper-lhistorique-pour-la-depense-energetique-modele).

Ceci est différent du [Backfill du contrat](skills/arc-backfill.md), qui
concerne les fichiers dont le bloc `arc` n'a pas encore de
`garmin_activity_id`/`calories_kcal` (un problème de fichier Markdown
incomplet, pas de fichier FIT manquant) — une séance peut avoir un bloc `arc`
parfaitement complet et valide, et pourtant toujours pas de FIT téléchargé.

## Les limites

Ce modèle est une **approximation**, jamais une mesure de calorimétrie
directe (qui exigerait un laboratoire). En particulier :

- **Pas de calorimétrie** : contrairement à un capteur métabolique dédié, rien
  ici ne mesure directement la consommation d'oxygène ou la production de
  chaleur de l'athlète — tout est déduit de la vitesse et de la pente.
- **Terrain technique** : sur un sentier très technique (rochers, racines,
  ajustements d'appui fréquents), le coût réel de la course dépasse
  probablement ce que le modèle calcule à partir de la seule vitesse et de la
  seule pente — le modèle ne voit ni les changements d'appui ni la prudence
  requise par le terrain. Cette limite est distincte du biais mesuré côté
  trail (voir [La validation](#la-validation), qui va dans l'autre sens : le
  modèle est déjà au-dessus de Garmin sur trail) — les deux ne doivent pas
  être confondus.
- **Chaleur** : le modèle ne majore jamais le coût énergétique d'un effort par
  forte chaleur (sudation accrue, travail cardiovasculaire supplémentaire de
  thermorégulation) — une prévision de course par forte chaleur reste donc une
  sous-estimation probable, jamais corrigée automatiquement.
- **Seuil marche/course fixe** : la bascule entre le régime « marche » et le
  régime « course » se fait à une vitesse fixe, identique pour tous les
  athlètes — une transition individuelle légèrement différente n'est pas prise
  en compte.

Ces limites sont documentées ici pour rester honnête sur ce que ce modèle sait
faire, et sur ce qu'il ne sait pas faire — jamais pour minimiser leur portée.
