# Allure ajustée à la pente (GAP)

L'**allure ajustée à la pente** (GAP, *Grade Adjusted Pace*) est l'allure que vous
auriez tenue **sur du plat** pour le même effort de course. En montée elle est plus
rapide que votre allure réelle, en descente douce plus lente. Elle rend comparables
des séances et des portions de parcours au relief différent.

Cette page explique quel modèle le projet utilise pour la calculer, pourquoi il a
remplacé l'ancien, comment ce choix a été vérifié sur des données réelles, et ce
qu'il ne sait pas faire.

## Où la GAP intervient

Une seule formule, `arc_gap.gap_factor` (`scripts/arc_gap.py`), sert partout :

- l'allure GAP de la séance et de chaque split ;
- la carte et le profil de la page séance (mode « GAP », courbe en pointillés) ;
- le découplage aérobie et le facteur d'efficacité (EF) ;
- la durabilité (fade entre premier et dernier tiers) ;
- l'efficacité en descente ;
- la courbe allure-durée et la [vitesse critique](vitesse-critique.md) ;
- le repli générique du modèle personnel pente → allure, donc les plans de course
  quand votre historique manque sur une pente.

Changer de modèle change donc toutes ces valeurs d'un coup, y compris pour les
séances passées : l'index est recalculé à la prochaine indexation, aucun fichier de
séance n'est modifié.

## Le modèle retenu : Kay (2012)

Kay A. (2012), « Pace and critical gradient for hill runners: an analysis of race
records », *Journal of Quantitative Analysis in Sports* 8(4),
[doi:10.1515/1559-0410.1456](https://doi.org/10.1515/1559-0410.1456) (version
publiée en accès libre sur le
[dépôt de l'université de Loughborough](https://repository.lboro.ac.uk/articles/journal_contribution/Pace_and_critical_gradient_for_hill_runners_an_analysis_of_race_records/9387719)).

L'article ajuste l'allure en fonction de la pente sur les **records de 91 courses de
montée et 15 de descente**, plus le record du monde du 10 000 m pour le plat, en
neutralisant la durée de course (la fatigue). Parmi six formes de courbe comparées,
la meilleure est une quartique (R² ajusté 0,994), qui donne directement le rapport
entre l'allure sur une pente `m` (en fraction : 0,10 = 10 %) et l'allure sur le plat :

```
p(m) / p0 = 1 + 3,639 m + 17,757 m² − 3,100 m³ − 23,834 m⁴
```

Allure GAP = allure mesurée ÷ ce rapport (vitesse GAP = vitesse mesurée × ce rapport).

**Bornes.** La quartique a des points d'inflexion au-delà desquels elle deviendrait
irréaliste. Comme le propose l'article (section 4.3), elle est prolongée par sa
**tangente** au-delà de +32,1 % en montée et de −26,3 % en descente (la « pente
critique », où la vitesse verticale de descente est maximale). La pente est bornée à
±45 % : jamais d'extrapolation au-delà.

| Pente | −30 % | −20 % | −15 % | −10 % | −5 % | 0 | +5 % | +10 % | +15 % | +20 % | +30 % |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Rapport d'allure | 1,38 | 0,97 | 0,85 | **0,81** | 0,86 | 1 | 1,23 | 1,54 | 1,92 | 2,38 | 3,41 |

On va le plus vite vers **−10 %** (environ 23 % plus vite que sur le plat), on
revient à l'allure du plat vers −21 %, et au-delà, descendre est plus lent que le plat.

## Pourquoi pas Minetti (2002)

Jusqu'ici, le projet utilisait le coût énergétique de la course de Minetti AE *et al.*
(2002), « Energy cost of walking and running at extreme uphill and downhill slopes »,
*J Appl Physiol* 93:1039-1046 : dix coureurs mesurés **sur tapis roulant**, la GAP
étant l'allure plate de même coût métabolique par mètre.

| Pente | −20 % | −15 % | −10 % | −5 % | +5 % | +10 % | +20 % |
|---|---|---|---|---|---|---|---|
| Minetti | 0,50 | 0,51 | 0,60 | 0,76 | 1,30 | 1,66 | 2,50 |
| Kay | 0,97 | 0,85 | 0,81 | 0,86 | 1,23 | 1,54 | 2,38 |

Minetti suppose qu'à effort égal on pourrait courir **deux fois plus vite** sur une
descente à −20 % que sur le plat. Personne ne le fait : en descente, ce qui limite
n'est pas le cœur mais le freinage musculaire, les impacts et le contrôle des appuis,
qu'un modèle énergétique ne voit pas. L'article de Minetti le note lui-même : les
vitesses prédites en montée correspondent à celles des courses de montée, mais en
descente elles sont « bien au-dessus » de celles atteintes en compétition. La revue de
Vernillo *et al.* (2017, *Sports Medicine* 47(4):615-629) décrit les mécanismes.

En pratique, avec Minetti, la courbe GAP d'une sortie vallonnée **n'était pas plus
régulière que l'allure brute** : la GAP devenait nettement plus rapide en montée et
s'effondrait dans les descentes raides. L'efficacité en descente, calculée par rapport
à ce modèle, donnait des valeurs très basses difficiles à interpréter.

## Vérification sur des données réelles

### Des centaines de coureurs amateurs (FitRec)

Le jeu de données [FitRec](https://mcauleylab.ucsd.edu/public_datasets/gdrive/fitrec/FitRec-Project.html)
(Ni, Muhlstein & McAuley, « Modeling heart rate and activity data for personalized
fitness recommendation », WWW 2019) contient des séances Endomondo avec position,
altitude, temps et fréquence cardiaque. Nous en avons extrait les sorties de course
(96 139 sorties exploitables sur 117 902, de 513 à 661 coureurs selon la méthode), découpées en fenêtres de 2 minutes,
avec la pente calculée par le même code que le projet (`arc_elevation.grade_series`).

Deux méthodes indépendantes donnent la courbe « population » :

- **façon Strava** : pour chaque coureur, les fenêtres entre les 70e et 90e centiles
  de sa FC (efforts soutenus et comparables), allure divisée par sa médiane à plat,
  puis médiane par classe de pente (méthode décrite dans le brevet Strava
  US11623121B1) ;
- **à FC égale** : pour chaque coureur, la relation vitesse–FC sur ses fenêtres plates
  (FC de la fenêtre suivante, pour tenir compte du retard cardiaque), puis, pour
  chaque fenêtre en pente, sa vitesse comparée à celle qu'il aurait eue sur le plat à
  la même FC.

Seules les fenêtres situées dans **une pente continue d'environ 1 km** (ou du plat
continu) sont gardées : sur une pente mal mesurée, une partie des fenêtres « en
pente » serait du plat déguisé, ce qui tirerait toute la courbe vers 1 (et
favoriserait mécaniquement le modèle le plus plat).

| Pente | +4 % | +6 % | +8 % | +10 % | +12 % | +14 % |
|---|---|---|---|---|---|---|
| Population, façon Strava | 1,18 | 1,28 | 1,39 | 1,51 | 1,63 | 1,74 |
| Population, à FC égale | 1,17 | 1,26 | 1,37 | 1,50 | 1,59 | 1,74 |
| **Kay** | **1,17** | **1,28** | **1,40** | **1,54** | **1,68** | **1,84** |
| Minetti | 1,24 | 1,37 | 1,51 | 1,66 | 1,81 | 1,98 |

**En montée**, Kay décrit ces coureurs amateurs à 1–3 % près jusqu'à +12 % ; Minetti
surestime le coût de la montée de 7 à 15 %.

| Pente | −4 % | −6 % | −8 % | −10 % | −12 % | −16 % |
|---|---|---|---|---|---|---|
| Population, à FC égale | 0,96 | 0,96 | 0,96 | 0,96 | 1,02 | 1,09 |
| Kay | 0,88 | 0,85 | 0,82 | 0,81 | 0,82 | 0,87 |
| Minetti | 0,81 | 0,72 | 0,66 | 0,60 | 0,55 | 0,50 |

**En descente**, les deux modèles sont trop optimistes pour un coureur amateur moyen,
qui ne gagne qu'environ 4 % en descente douce et revient à l'allure du plat vers −12 % ;
Kay se trompe deux à trois fois moins que Minetti.

Limites de cette vérification : séances Endomondo des années 2010, majoritairement sur
route, altitude de qualité variable, échantillonnage d'environ 7 s. Le jeu de données
est réservé à un usage académique non commercial : il n'est ni redistribué ni versé
dans le dépôt, seules ces statistiques agrégées en sont tirées.

### Des sorties trail

Sur des sorties trail enregistrées au baromètre (partagées avec l'accord de leurs
auteurs, non publiées), le résultat va dans le même sens :

- chez un traileur solide (45 km, 2 550 m D+), la GAP de Kay reste presque constante
  d'une classe de pente à l'autre (5:25 à 6:02 min/km), là où celle de Minetti va de
  5:06 à 11:01 ; ce coureur descend environ 20 % plus vite que sur le plat, exactement
  ce que prévoit Kay ;
- chez un coureur qui marche la plupart des descentes raides, l'écart à Kay en
  descente reflète cette marche, pas une erreur de calcul.

### Ce qui ne départage pas les modèles

La corrélation entre la vitesse GAP et la fréquence cardiaque est à peu près la même
avec Minetti et avec Kay (et nettement meilleure qu'avec l'allure brute). Ce critère
semble naturel, mais il est biaisé : la plupart des coureurs forcent davantage en
montée et récupèrent en descente, si bien qu'un modèle qui **exagère** l'effet de la
pente suit mieux la FC, justement parce qu'il exagère. Les comparaisons à FC égale
ci-dessus évitent ce piège.

## Comment lire la GAP

- **En montée**, la GAP est une bonne mesure de l'effort de course pour la plupart des
  coureurs.
- **En descente**, Kay décrit un coureur de montagne entraîné. Si votre GAP est plus
  lente en descente que sur le plat, c'est surtout votre **niveau de descendeur** par
  rapport à cette référence (prudence, technique, terrain, portions marchées) — pas
  une erreur de calcul. C'est exactement ce que mesure l'**efficacité en descente** :
  1,00× = descendre comme ce coureur de référence ; une valeur en dessous est
  fréquente, et c'est sa **tendance dans le temps, à pente égale**, qui compte.
- **Sur une séance**, la courbe GAP est d'autant plus plate que votre effort était
  régulier. Elle n'est jamais parfaitement plate : la fréquence cardiaque et le
  ressenti restent les meilleurs juges de l'effort.

## Limites

- Le modèle vient de **coureurs d'élite masculins en course**, sur des sentiers de
  montagne bien tracés. Diviser par l'allure du plat retire en grande partie l'effet du
  niveau, mais la courbe d'un individu peut différer, surtout en descente.
- Il ne voit **pas la technicité** du terrain (racines, pierres, boue), ni la marche.
- Au-delà d'environ ±15 %, les données de vérification deviennent rares ; au-delà de
  −25 %, l'article lui-même juge son modèle peu fiable (d'où le prolongement par la
  tangente).
- Ce n'est **pas** une reproduction des calculs des marques Strava, COROS ou Suunto
  (Strava GAP, COROS Effort Pace, Suunto NGP), non publiés (voir [Marques et métriques](marques.md)) :
  les valeurs peuvent différer de celles de votre montre ou de votre application.

## Pistes écartées

- **Plafonner Minetti en descente** : corrige l'excès le plus visible, mais laisse la
  surestimation en montée et repose sur un seuil arbitraire.
- **Utiliser le modèle personnel pente → allure comme GAP** : il aplatit la courbe,
  mais, appris sur vous, il considère vos descentes comme « normales » par
  construction et ne peut donc plus révéler un point faible. Il reste utilisé pour ce
  qu'il fait bien : prévoir vos temps de course.
- **Construire une courbe « population » à partir de FitRec** : plus juste en descente
  pour un coureur moyen, mais elle reposerait sur des coefficients tirés d'un jeu de
  données à usage académique uniquement.
- **Reproduire la GAP de Strava** : ses coefficients ne sont pas publiés.
