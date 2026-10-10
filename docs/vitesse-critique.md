# Vitesse critique et courbe allure-durée

<!-- arc-video:allure-juste -->
<div class="arc-video-card" markdown>

[![L'allure juste](video/allure-juste/poster.jpg)](video/allure-juste/index.html)

<div markdown>

<span class="arc-video__meta">En vidéo · Étape 16 · 1 min 48</span>

**[L'allure juste](video/allure-juste/index.html)** — La pente, la durée et la chaleur ramenées à une allure juste : modèle de Kay et carte GAP, courbe allure-durée et vitesse critique, cibles de séance en pourcentage de cette vitesse, puis ralenties par la chaleur, FC inchangée.

[Regarder](video/allure-juste/index.html) · [English](video/allure-juste/index.html?lang=en) · [Toutes les vidéos](videos.md)

</div>

</div>
<!-- /arc-video -->

Le tableau de bord (vue [Performance](dashboard/views.md#performance)) et le
coach estiment votre **vitesse critique** (CS) et votre **réserve anaérobie D′**
à partir de vos propres séances, sans test à l'épuisement. Cette page explique ce
que ces deux chiffres veulent dire, comment ils sont calculés, ce qu'ils valent,
et quand le projet refuse de les donner.

## Le principe

La vitesse critique est l'équivalent en course à pied de la **puissance critique**
(et de son W′) du cyclisme : au-dessus de cette vitesse, l'effort n'est plus
soutenable indéfiniment et une réserve finie — D′, en mètres — s'épuise. En
dessous, l'intensité reste tenable longtemps. Le modèle est une droite :

```
distance tenue à fond sur une durée t  =  CS × t  +  D′
```

**Vitesse critique** (en allure, min/km) = la pente de cette droite. **Réserve
anaérobie D′** (en mètres) = son ordonnée à l'origine : la distance que vous
pouvez courir « au-dessus » de la vitesse critique avant d'être au bout.

Références (vérifiées via Crossref) : Jones AM & Vanhatalo A (2017), « The
'Critical Power' Concept: Applications to Sports Performance with a Focus on
Intermittent High-Intensity Exercise », *Sports Medicine* 47(Suppl 1):65-78,
[doi:10.1007/s40279-017-0688-0](https://doi.org/10.1007/s40279-017-0688-0) ;
Poole DC, Burnley M, Vanhatalo A, Rossiter HB & Jones AM (2016), « Critical
Power », *Medicine & Science in Sports & Exercise* 48(11):2320-2334,
[doi:10.1249/mss.0000000000000939](https://doi.org/10.1249/mss.0000000000000939).
Ces articles décrivent le concept de puissance critique ; son **transfert à la
vitesse critique en course, et tous les seuils de validité ci-dessous, sont des
approximations du projet**, pas des valeurs publiées.

## La courbe allure-durée

`python3 scripts/arc_index.py pace-curve [--days N] [--lt-speed-ms V]` (et
`/api/pace-curve`) calcule, pour chaque durée standard de 30 s à 2 h, la
**meilleure allure moyenne** que vous avez tenue, à partir des échantillons FIT
(regroupés par pas de 5 s à l'indexation) :

- en **GAP** (allure ajustée à la pente, [modèle de Kay](gap.md)) : une
  côte et un plat de même effort de course se valent. La vitesse critique est donc
  une vitesse « équivalent plat » ; sur une pente réelle, l'allure à tenir est plus
  lente. Les limites du GAP (bruit de pente, descentes) s'appliquent ;
- sur des **fenêtres glissantes de temps écoulé** : un effort « de 10 min » qui
  contient 90 s d'arrêt n'est pas un effort de 10 min. Une fenêtre n'est retenue
  que si les échantillons couvrent au moins 95 % de sa durée — un trou de signal
  ou une pause automatique de la montre la disqualifie, il n'est jamais interpolé.
  Un arrêt enregistré (ravitaillement en trail, feu rouge) compte comme du temps à
  vitesse nulle : un meilleur effort qui l'enjambe est pénalisé. C'est voulu : sur
  le temps de *mouvement*, les morceaux de part et d'autre de l'arrêt seraient
  recollés alors que D′ se reconstitue pendant l'arrêt — un effort intermittent
  passerait pour un effort continu et gonflerait CS et D′. Sur le temps écoulé,
  l'erreur va dans le sens prudent (vitesse critique basse) ;
- sur trois périodes : **42 jours**, **90 jours**, **365 jours** (le meilleur de
  toutes les séances de la période). Une séance sans altitude exploitable (tapis,
  capteur barométrique absent) est écartée et comptée à part — jamais supposée plate.

## L'ajustement CS / D′

Régression linéaire des moindres carrés sur les meilleurs efforts de **3 à
20 minutes** de la fenêtre de 90 jours. Pour ne jamais extrapoler en silence, le
calcul **refuse** de répondre — et dit pourquoi — quand :

| Motif (`reason_code`) | Condition |
|---|---|
| `insufficient_points` | moins de 3 durées disponibles entre 3 et 20 min |
| `single_source` | tous les points viennent d'une seule séance (une séance longue fournit toute une courbe par dilution ; cela imiterait un ajustement sans en être un) |
| `insufficient_span` | rapport durée max / durée min inférieur à 3 : CS et D′ ne sont pas séparables |
| `d_prime_out_of_range` | D′ hors de 30–1 000 m : courbe plate (efforts non maximaux) ou ajustement incohérent |
| `non_positive_cs` | vitesse critique nulle ou négative |
| `poor_fit` | R² inférieur à 0,95 : efforts hétérogènes |

Un ajustement accepté rend sa **qualité** : nombre de points, R², erreur standard
de l'estimation (en mètres), erreur standard de la vitesse critique et de D′ (en
valeur et en %), et un niveau « bonne » (au moins 4 points, vitesse critique à
± 2 % et D′ à ± 10 %), « moyenne » (± 5 % et ± 25 %) ou « faible ». Le R² n'entre
pas dans ce niveau : la distance croissant presque proportionnellement à la durée,
il dépasse 0,99 même pour des efforts peu cohérents — il ne sert que de garde-fou
grossier (refus sous 0,95). Ces seuils sont une approximation du projet.

La **tendance** refait l'ajustement tous les 28 jours, chacun sur le meilleur de
90 jours se terminant à ce point ; un point sans ajustement valide reste vide, jamais
reporté depuis le précédent.

## Ce que ça vaut — et ce que ça ne vaut pas

- Ce sont des **meilleurs efforts d'entraînement et de course, pas un test**. Si
  vous n'avez jamais couru à fond sur une durée, le meilleur effort sous-estime votre
  capacité : la vitesse critique ressort **basse**, pas haute.
- Les points viennent de séances **différentes** (jusqu'à 90 jours d'écart) : une
  forme qui évolue brouille l'ajustement. La qualité affichée dit à quel point.
- Même à plusieurs séances, une durée courte peut être « héritée » d'un effort plus
  long (son meilleur 3 min est au moins sa vitesse moyenne) : ces points restent des
  bornes basses.
- Ni la vitesse critique ni D′ ne sont des mesures de laboratoire, ni un diagnostic.

## Utilisation par le coach

Pour les séances `tempo`, `threshold` et `vo2max`, `arc_workout_targets.py` ajoute
une cible `cs_target` **en complément** de la zone FC (jamais à sa place), et
**seulement si l'ajustement est valide** :

| Intensité | Plage (% de la vitesse critique) |
|---|---|
| `tempo` | 88–95 % |
| `threshold` | 95–100 % |
| `vo2max` | 102–110 % |

Par la chaleur (`targets --heat`, voir [Météo](skills/weather-forecast.md)), ces vitesses sont
ralenties du même facteur que les autres cibles d'allure (`cs_target.adjusted`) :
la vitesse critique vient de meilleurs efforts courus surtout par temps tempéré.
Le budget D′ n'est pas recalculé (effet de la chaleur sur D′ non modélisé) ; en
🔴, l'intensité n'est pas maintenue et aucune cible ajustée n'est rendue.

Ces pourcentages sont une **approximation du projet**. Pour `vo2max`,
`d_prime_budget_s` donne la durée cumulée tenable au-dessus de la vitesse critique
à la borne haute (D′ / (v − CS)) : une répétition plus longue la dépasserait.

**Contrôle avec le seuil lactique Garmin.** Quand l'athlète dispose d'un seuil
lactique estimé par sa montre, le coach le passe en `--lt-speed-ms` (m/s) et un
écart de plus de 5 % est **signalé avec les deux valeurs, jamais arbitré** (une
vitesse hors de 1,5–7 m/s est refusée : unité probablement mal convertie) : ce
sont deux estimations par des méthodes différentes (vos meilleurs efforts d'un côté,
un algorithme propriétaire non documenté publiquement dans le détail de l'autre), et
elles ne désignent pas exactement la même intensité.

## Noms des métriques

« Vitesse critique » (CS) et « réserve anaérobie D′ » sont des termes génériques de
la physiologie de l'effort, pas des marques ; la courbe est notre propre calcul
([marques et métriques](marques.md)). Toutes les hypothèses et leurs limites sont
réunies dans la vue Hypothèses du tableau de bord (famille « Vitesse critique et
D′ ») et dans `scripts/arc_cs.py` (`ASSUMPTIONS`).
