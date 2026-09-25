# Les vues

Chaque vue répond à une question précise. Pour chacune : ce qu'elle montre, comment
la lire, **d'où viennent ses données** — et que faire quand elle reste vide.

Les captures viennent d'un vrai workspace : deux ans de fichiers (août 2024 →
septembre 2026), la préparation et le déroulé d'un ultra-trail de 110 km le
13 septembre 2026, puis le premier bloc de reprise. Date de référence : mercredi
23 septembre, dix jours après la course.

!!! tip "Partout dans le tableau de bord"
    - **Le bandeau du haut** rappelle l'objectif de `planning/active_objective.md` :
      compte à rebours (J-45), puis « Terminé il y a 10 j » une fois la course passée.
    - **Survolez un graphique** (ou touchez-le, ou utilisez les flèches du clavier) :
      la ligne sous le graphique donne les valeurs exactes du point visé.
    - **Le bouton lune** force le thème clair ou sombre ; sinon, celui du système.
    - **Tout est un lien** : une séance ouvre son détail, un rapport son texte, une
      semaine son plan. L'adresse de chaque page se partage ou se met en favori.

## Aujourd'hui

**Je cours, j'allège ou je me repose ?**

![Aujourd'hui : verdict du coach, bilan du matin, séance du jour et forme](../assets/dashboard/aujourdhui.webp)

La page du matin, à ouvrir avant de lacer ses chaussures. De haut en bas :

1. **Le verdict du coach** — *Maintenir*, *Alléger* ou *Repos* — et sa raison en une
   phrase, tels qu'écrits dans le fichier santé du jour. Sans verdict ce jour-là, la
   vue rappelle le dernier, daté, plutôt que d'en inventer un.
2. **Le bilan du matin** : chaque mesure est placée sur **votre** référence, pas sur
   une norme générale — la HRV dans sa bande Garmin, la FC de repos face à sa médiane
   des 7 derniers jours (+5 bpm : à surveiller, +7 : nettement élevée, les règles
   mêmes du coach), la readiness, le sommeil et son score.
3. **Au programme** : la séance prévue par le plan de la semaine, ce qui a déjà été
   enregistré aujourd'hui, la météo du lieu d'entraînement et le créneau conseillé.
4. **Forme** : condition, fatigue, forme et ratio de charge, avec une phrase qui les
   lit pour vous (« la fatigue est sous la condition physique »), puis une **mini
   tendance de conformité sur 4 semaines** (une barre par semaine, hauteur = % de
   séances faites) — une semaine sans plan reste une barre grise plutôt que de
   disparaître silencieusement de la série. Détail complet dans **Semaine**.
5. **Le dernier rapport du coach**, en lien.

| Alimentée par | Écrit par |
|---|---|
| `medical/<date>_health.md` (mesures, verdict) | la synchronisation du matin ; le verdict, le coach |
| `medical/<date>_meteo.md` (catégorie, créneau) | le coach, skill `weather-forecast` |
| `planning/Semaine_<lundi>.md` (séance du jour) | le coach, quand il planifie |
| `activities/`, `rapports/` | la synchronisation, le coach |

**Si c'est vide** : pas de bilan avant la synchronisation du matin
([mode headless](headless.md)) ou avant d'avoir demandé au coach son bilan matinal.
Pas de verdict tant que le coach n'a pas tranché pour la journée — demandez-lui
« je cours aujourd'hui ? ». Avec `[health].morning_check = "minimal"`, seule la
readiness apparaît ; avec `"off"`, le bloc santé disparaît — c'est voulu.

## Forme & charge

**Où en est ma condition, ma fatigue, ma forme ?**

![Forme & charge : courbe de forme, ratio de charge et volume hebdomadaire](../assets/dashboard/forme.webp)

Trois graphiques, sur 3 mois, 6 mois ou un an :

- **La courbe de forme** met côte à côte votre **condition** (moyenne de charge sur
  42 jours), votre **fatigue** (7 jours) et votre **forme** (leur écart) — le modèle
  impulsion-réponse de Banister, calculé sur le TRIMP (voir
  [Marques et métriques](../marques.md)). Quand la fatigue passe sous la condition,
  la forme devient positive : vous êtes frais. Le jour de course est marqué ; on
  voit ici la fatigue bondir à plus de 200 le 13 septembre, puis la forme redevenir
  positive pendant la reprise.
- **Le ratio charge aiguë / chronique** (ACWR) et sa bande 0,8 – 1,3 — un repère
  indicatif, discuté dans la littérature, pas un seuil de blessure. Il n'est pas
  tracé tant que l'historique est trop mince pour avoir un sens.
- **Le volume hebdomadaire** : heures d'effort et D+ cumulé en trail, kilomètres sur
  route. En profil trail, la ligne affichée au survol ajoute le **km-effort ITRA**
  (km + D+/100 ; voir [Marques et métriques](../marques.md)) — à ne pas confondre
  avec l'« équivalence plat » utilisée ailleurs pour les prédictions VDOT/Riegel
  (D+ × 1,5 à 2 km). Contrairement aux heures, kilomètres et D+ affichés à côté, qui
  cumulent **toutes** les activités de la semaine, le km-effort ne compte que les
  activités de course (running, trail, randonnée, marche) : le vélo et les autres
  sports en sont exclus. Reste exprimé en kilomètres même en unités impériales
  (`[athlete].units = imperial`). En dessous, la monotonie et le *strain* de Foster
  sur 7 jours, et la charge du jour.

**Comment la lire** : une forme très négative plusieurs semaines de suite, c'est de
la fatigue accumulée ; une forme franchement positive avant une course, c'est
l'affûtage réussi. La tendance compte plus que le chiffre du jour. Il faut environ
six semaines d'historique pour que la condition ait un sens.

| Alimentée par | Calcul |
|---|---|
| `activities/*.md` (durée, FC moyenne, effort perçu) | `scripts/arc_metrics.py` : TRIMP, ou effort perçu sans FC |
| `planning/Runner_Profile.md` (FC max, FC de repos) | indispensables au TRIMP |

**Si les courbes sont plates ou bizarres** : renseignez la FC max et la FC de repos
de référence du profil. Sans elles, la charge vient de l'effort perçu seul.

## Santé

**Comment mon corps encaisse-t-il ?**

![Santé : HRV, FC de repos, readiness, sommeil et frise des verdicts](../assets/dashboard/sante.webp)

Les tendances du bilan matinal, sur 1, 3 ou 6 mois :

- **HRV nocturne** dans sa bande de référence Garmin (zone pleine), avec sa courbe
  lissée en tirets — moyenne glissante 7 jours de ln(HRV) comparée à une **référence
  personnelle** 60 jours ± 0,5 écart-type calculée localement (largeur de bande :
  Plews, Laursen & Buchheit 2013 ; passage au log et CV du lnRMSSD hebdomadaire :
  Plews et al. 2012 — Kiviniemi et al. 2007 n'est qu'un précédent de l'entraînement
  guidé par une bande individuelle, pas la source de cette largeur ni de ce CV ;
  détail complet dans `ASSUMPTIONS["hrv_baseline"]` de `scripts/arc_metrics.py`).
  Quand Garmin ne fournit pas de bande, cette référence personnelle prend sa place —
  y compris hors tableau de bord, via `python3 scripts/arc_index.py hrv-baseline`.
  Sous 30 jours d'historique de référence, le statut reste « en construction » plutôt
  que d'afficher une estimation bruitée. Uniquement calculé et affiché en
  `[health].morning_check = "full"` : en `minimal`, seule la readiness est exposée.
  Juste dessous, **la frise des verdicts du coach**, jour par
  jour (vert *Maintenir*, orange *Alléger*, rouge *Repos*). On y lit ici le repos
  imposé au lendemain de l'ultra, puis le feu vert de la reprise.
- **FC de repos**, avec sa médiane 7 jours et les seuils +5 / +7 qui la suivent : le
  pic post-course à 55 bpm les franchit nettement, puis la FC redescend.
- **Readiness**, colorée par niveau, et **sommeil** face aux 7 h 30 visées.

**Comment la lire** : un point isolé ne dit rien ; deux ou trois jours d'affilée
hors de la bande, ou au-dessus du seuil +5, oui. C'est exactement ce que le coach
regarde avant de poser son verdict.

| Alimentée par | Écrit par |
|---|---|
| `medical/<date>_health.md` | la synchronisation (bilan matinal) ; le verdict, le coach |

**Si c'est vide** : `[health].morning_check = "off"` désactive le bilan — la vue le
dit au lieu d'afficher des trous. Un jour sans verdict dans la frise est un jour où
le coach n'a pas tranché : rien n'est inventé.

## Semaine

**Qu'est-ce qui était prévu, qu'est-ce qui a été fait ?**

![Semaine : le plan du coach face au réalisé, jour par jour](../assets/dashboard/semaine.webp)

Le plan de la semaine face au réalisé. Pour chaque jour :

- **les séances prévues** et leur statut — *Prévue*, *Faite*, *Déplacée*, *Manquée*,
  *Annulée* ; ici, le footing du mardi a été couru le mercredi ;
- **la catégorie météo** du jour (*Optimal*, *Vigilance*…) quand une prévision existe ;
- **les séances réellement enregistrées**, sous le plan : un clic ouvre leur détail.

En dessous, **le réalisé face à la cible** de la semaine (18,2 km sur 40 visés), puis
**la conformité** — le KPI de l'épopée #20 (story #33) : % de séances faites, ratio
durée réalisée/planifiée, ratio D+ réalisé/planifié (route : ratio absent, pas de D+
significatif), le tout aussi par intensité (*Facile* : récupération, endurance ;
*Qualité* : tempo, seuil, VO2max, course ; *Autre* : renforcement et toute intensité
non classée, pour que Facile + Qualité + Autre reconstitue toujours le total). Les
séances de **repos**, **annulées** et **déplacées** sont retirées du calcul (elles ne
comptent ni en séance faite ni en manquée), les séances des jours pas encore passés
de la semaine en cours ne sont jamais comptées manquées, et une séance du jour même
sans activité encore enregistrée est **en attente**, pas manquée — le décompte ne se
fige qu'à la fin de la journée. Une semaine sans aucune séance planifiée (hors repos)
n'affiche aucun pourcentage plutôt qu'un 0 % trompeur. Puis **le texte du plan** tel
que le coach l'a écrit. *Précédente* / *Suivante* naviguent d'une semaine à l'autre ;
la liste **Plans** saute directement aux semaines qui ont un plan.

!!! note "Comment une séance prévue est rapprochée du réalisé"
    Une séance de repos (`sport` ou `intensity` valant `rest`) est hors sujet pour ce
    KPI et n'entre dans aucun calcul : sans cette exclusion, une semaine des plans
    hérités (qui classent chaque « Repos » du tableau en `sport = rest` sans statut)
    tombait à 50 % de conformité alors que tout avait été fait.

    Le statut écrit dans le plan (`done`, `missed`, `moved`, `cancelled`) prime
    toujours — et les séances `done` explicites réservent leur activité avant que les
    séances sans statut ne piochent dans ce qui reste, pour qu'une séance non
    résolue ne puisse jamais « voler » l'activité d'une séance déjà validée du même
    jour. Sans statut, ou avec `planned` sur une date déjà passée, la séance est
    comparée aux activités restantes du même jour de sport compatible (course sur
    route, trail, randonnée et marche interchangeables, de même pour les variantes de
    vélo) : une activité correspondante fait compter la séance comme faite, son
    absence comme manquée — sauf le jour même, où l'absence d'activité est encore
    « en attente », pas manquée.

    Une séance `cancelled` est exclue du calcul quel que soit le motif — le contrat
    de données n'a pas de champ pour distinguer une annulation médicale d'une autre
    (voir la docstring de `scripts/arc_metrics.py::week_compliance`). Une séance
    `moved` est également exclue : rien dans le contrat n'indique sa nouvelle date ;
    si le coach a écrit une séance distincte au jour réel, celle-ci compte pour
    elle-même. Une séance `done` explicite sans activité chiffrée en face (fichier
    pas encore synchronisé) compte comme faite, mais reste hors des ratios durée/D+
    des deux côtés — un ratio à 0 % serait aussi trompeur qu'optimiste.

La même vue montre les semaines à venir — ici un bloc de force planifié un mois plus
tard, avec les fiches de renforcement et le home trainer :

![Une semaine à venir : séances planifiées, poussées sur le calendrier Garmin](../assets/dashboard/semaine-bloc.webp)

| Alimentée par | Écrit par |
|---|---|
| `planning/Semaine_<lundi>.md` : **un fichier par semaine**, nommé d'après son lundi (`Semaine_2026-09-21.md`) | le coach, quand il planifie ou pousse le plan sur Garmin |
| `activities/*.md` (le réalisé) | la synchronisation |
| `medical/<date>_meteo.md` | le coach, skill `weather-forecast` |

!!! warning "« Pas de plan de semaine au contrat pour ces dates »"
    La vue ne lit que les fichiers `planning/Semaine_<lundi>.md`. Un plan de
    plusieurs semaines rangé dans un seul fichier (« plan de transition sur
    10 semaines ») reste invisible, et n'apparaît même pas dans les fichiers hors
    contrat. Demandez au coach d'en écrire **un fichier par semaine** — dix semaines,
    dix fichiers —, chacun avec son bloc de données : séances datées, et
    `garmin_workout_id` quand elles sont sur le calendrier Garmin. Le plan d'origine
    reste la référence ; chaque fichier semaine y renvoie.

## Séances

**Qu'est-ce que j'ai fait, et comment ça s'est passé ?**

![Séances : l'historique complet, triable et filtrable](../assets/dashboard/seances.webp)

Tout l'historique : date, distance, durée, D+ (ou allure sur route), FC moyenne, HRR
et charge. Chaque colonne se trie ; le filtre isole un sport. Une séance lue dans un
fichier antérieur au contrat porte la mention **approx.** ; une charge estimée faute
de fréquence cardiaque et d'effort perçu, un astérisque.

### Détail d'une séance

![Détail d'une séance : chiffres clés, météo, splits et analyse du coach](../assets/dashboard/seance.webp)

- **Les chiffres clés** : distance, durée, allure, D+ / D-, FC moyenne et max, **HRR**
  (récupération cardiaque — « non mesuré » avec sa raison quand Garmin ne l'a pas),
  effet d'entraînement, charge, VO2max estimée quand la séance s'y prête.
- **La météo du jour**, si une prévision a été enregistrée.
- **Les splits** : un graphique allure + FC, puis le tableau complet — temps, D+ / D-,
  FC, cadence et la lecture du coach pour chaque kilomètre quand il en a écrit une.
- **L'analyse complète du coach**, rendue telle qu'il l'a écrite, tableaux compris ;
  le chemin du fichier source est rappelé en bas.

Les splits sont les **tours Garmin**. En course libre, un tour = un kilomètre. Sur une
séance structurée, un tour suit les étapes de la séance : 500 m, 676 m… Le graphique
trace alors l'**allure** de chaque tour (le temps ramené au kilomètre), et le tableau
ajoute distance et allure. Le reliquat de quelques mètres à la fin d'une sortie n'est
pas tracé ; il reste dans le tableau.

![Tours d'une séance structurée : l'allure ramenée au kilomètre](../assets/dashboard/seance-tours.webp)

Sur une longue sortie, le graphique devient le profil de la course : ici les 110 km
de l'ultra, les ravitaillements lisibles en creux de FC et en pics d'allure.

![Splits d'un ultra-trail de 110 km](../assets/dashboard/seance-ultra.webp)

| Alimentée par | Écrit par |
|---|---|
| `activities/<date>_<sport>.md` : bloc de données (`splits`, `garmin_activity_id`) et analyse | la synchronisation |

**Pas de graphique ?** Le bloc de la séance n'a pas de splits : fichier ancien,
migré sans eux. Voir [Compléter les splits depuis Garmin](migration.md#completer-les-splits-depuis-garmin).
Le renforcement, le vélo d'intérieur ou l'elliptique n'ont pas de tours au
kilomètre : pas de graphique, c'est normal.

## Performance

**Quel est mon niveau, et que puis-je viser ?**

![Performance : VO2max estimée, prédictions et records](../assets/dashboard/performance.webp)

- **VO2max effective**, tendance sur 30 jours, estimée sur les séances de course
  qualifiantes (20 min à 3 h, au-dessus de 70 % de la FC max, sans marche).
- **Prédictions** du 5 km au marathon, et pour votre objectif : par le VDOT de
  Daniels et par la formule de Riegel. En trail, la distance « effort » ajoute le
  dénivelé (1 000 m D+ ≈ 1,75 km de plat).
- **Records** sur des fenêtres de kilomètres consécutifs (1, 5, 10, 21 km) : seuls
  les tours d'environ 1 km comptent.
- **Hypothèses** : toutes les formules et leurs limites, en clair.

**Comment la lire** : ce sont des ordres de grandeur, calculés sur l'allure et la FC
*moyennes* de chaque séance — pas une mesure de laboratoire. Deux estimations qui
divergent disent que le terrain ou la forme du jour pèsent.

| Alimentée par | Calcul |
|---|---|
| `activities/*.md` (course et trail : allure, FC, splits) | `scripts/arc_metrics.py` |
| `planning/Runner_Profile.md`, `planning/active_objective.md` | FC max ; distance et D+ de l'objectif |

## Calendrier

**Suis-je régulier ?**

![Calendrier : l'année en carte de chaleur et le cumul par année](../assets/dashboard/calendrier.webp)

L'année en carte de chaleur — plus la case est foncée, plus la durée d'effort du jour
est longue — et la **distance cumulée**, comparée d'une année à l'autre. Les boutons
d'année remontent l'historique.

## Rapports

**Qu'est-ce que le coach en a conclu ?**

![Rapports : la liste des bilans du coach](../assets/dashboard/rapports.webp)

Les rapports du coach — bilans hebdomadaires, validations du jour, comparaisons de
parcours, analyses de course —, du plus récent au plus ancien, avec leur type et leur
période. Un clic les rend lisibles, tableaux compris ; ici, la comparaison entre la
prévision et le déroulé réel de l'ultra :

![Un rapport du coach, rendu dans le tableau de bord](../assets/dashboard/rapport.webp)

| Alimentée par | Écrit par |
|---|---|
| `rapports/*.md` | le coach |

## Nutrition

**Mon poids et mes apports suivent-ils ?**

Un graphique de poids (#36) — points quotidiens, moyenne mobile 7 jours et cible — puis
un tableau jour par jour : poids et poids cible, apports déclarés, dépense Garmin,
glucides / protéines / lipides. Il n'y a pas de connexion MyFitnessPal : les apports
viennent de ce que vous dites au nutritionniste, qui les consigne.

Le poids affiché fusionne deux sources qui peuvent toutes deux exister le même jour :
`medical/<date>_health.md` (pesée du bilan matinal) et `nutrition/<date>_nutrition.md`
(sans garantie d'horaire). La mesure du matin gagne toujours ; jamais de moyenne entre
les deux. Sous trois jours pesés sur les sept derniers, la moyenne 7 j n'est pas affichée
plutôt que de montrer une valeur bruitée ; la pente sur 4 semaines (kg/semaine) demande de
son côté au moins cinq jours pesés dans la fenêtre. Ce sont des chiffres, jamais un avis
sur ce qu'il faudrait en faire.

| Alimentée par | Écrit par |
|---|---|
| `nutrition/<date>_nutrition.md` (valeurs chiffrées) | le nutritionniste |
| `medical/<date>_health.md` (poids du bilan matinal) | le coach / la synchronisation santé |

**Si c'est vide** — « Pas encore de suivi chiffré » : les fichiers `nutrition/` ne
contiennent pas encore de valeurs (une liste de courses ou un plan de ravitaillement
n'en contiennent pas). Sans `nutritionist` dans `[agents].enabled`, la vue
n'apparaît pas du tout.

## Fichiers hors contrat

**Qu'est-ce que le tableau de bord lit mal ?**

![Fichiers hors contrat : ce qui manque à chaque fichier](../assets/dashboard/fichiers.webp)

Les fichiers sans bloc de données, avec un bloc invalide, ou illisibles — chacun avec
ce qui lui manque. Le lien n'apparaît dans le menu que s'il en reste. Pour les
reprendre : [Migrer vos fichiers](migration.md). Les fichiers écartés à dessein (une
séance prescrite jamais courue, un doublon) peuvent y rester : c'est une liste de
contrôle, pas une erreur.

## En sombre, et sur le téléphone

![Forme & charge en thème sombre](../assets/dashboard/sombre-forme.webp)

Le tableau suit le thème clair ou sombre du système ; le bouton lune force l'un ou
l'autre, un lien avec `?theme=dark` ou `?theme=light` aussi. Sur un téléphone, le
menu se replie et les graphiques s'adaptent : c'est la vue à ouvrir le matin, depuis
la [machine coach](headless.md) ou [derrière votre reverse proxy](docker.md).

<div class="grid" markdown>

![Aujourd'hui sur téléphone](../assets/dashboard/mobile-aujourdhui.webp){ width="260" }
![Semaine sur téléphone](../assets/dashboard/mobile-semaine.webp){ width="260" }
![Détail d'une séance sur téléphone](../assets/dashboard/mobile-seance.webp){ width="260" }

</div>

## D'où vient chaque vue

Une vue vide ou incomplète se diagnostique presque toujours par le fichier qui la
nourrit :

| Vue | Fichiers lus | Écrits par |
|---|---|---|
| Aujourd'hui | `medical/<date>_health.md`, `medical/<date>_meteo.md`, `planning/Semaine_<lundi>.md` | synchronisation, coach |
| Forme & charge | `activities/*.md`, `planning/Runner_Profile.md` | synchronisation, vous |
| Santé | `medical/<date>_health.md` | synchronisation, coach |
| Semaine | `planning/Semaine_<lundi>.md`, `activities/*.md` | coach, synchronisation |
| Séances | `activities/<date>_<sport>.md` | synchronisation |
| Performance | `activities/*.md`, `planning/Runner_Profile.md`, `planning/active_objective.md` | synchronisation, vous |
| Calendrier | `activities/*.md` | synchronisation |
| Rapports | `rapports/*.md` | coach |
| Nutrition | `nutrition/<date>_nutrition.md` | nutritionniste |

Chacun de ces fichiers s'ouvre par un bloc de données décrit par le
[contrat de données](../skills/workspace-data-contract.md) : c'est ce bloc que le
tableau de bord lit, jamais la prose.
