# Gabarits de périodisation (`arc_plan_templates.py`)

<!-- arc-video:bloc -->
<div class="arc-video-card" markdown>

[![Construire son bloc](video/bloc/poster.jpg)](video/bloc/index.html)

<div markdown>

<span class="arc-video__meta">En vidéo · Étape 15 · 1 min 48</span>

**[Construire son bloc](video/bloc/index.html)** — Un bloc d'entraînement qui ne s'invente plus : gabarits de périodisation, squelette semaine par semaine relu par les garde-fous, frise du bloc sur le tableau de bord, renforcement par phase et prévention ciblée.

[Regarder](video/bloc/index.html) · [English](video/bloc/index.html?lang=en) · [Toutes les vidéos](videos.md)

</div>

</div>
<!-- /arc-video -->

Jusqu'ici, le coach écrivait chaque bloc d'entraînement « à main levée » : la
périodisation et l'affûtage ne vivaient que dans son prompt. Les gabarits
rangent cette structure dans des **données** (`config/plans/*.json`, livrées
avec le moteur) et un script (`scripts/arc_plan_templates.py`) les **vérifie**
au lieu de se fier à de la prose.

!!! note "Un point de départ, jamais un plan imposé"
    Le profil de l'athlète, le bilan matinal et les [garde-fous](guardrails.md)
    priment toujours. Chaque semaine écrite à partir d'un gabarit repasse
    `arc_guardrails.py check` sur l'historique réel. Cette page décrit les
    gabarits et leur validation ; le squelette daté d'un bloc (date de course,
    disponibilité, historique) est décrit plus bas, section
    [Le squelette de bloc](#le-squelette-de-bloc-plan-skeleton).

## Les gabarits livrés

| Identifiant | Sport | Objectif visé (distance) | Durée du bloc | Pic hebdomadaire indicatif |
|---|---|---|---|---|
| `trail_court` | trail | jusqu'à 30 km | 8 à 16 semaines (défaut 12) | 4–7 h |
| `marathon_trail` | trail | 30 à 60 km (~42 km, ~2 000 m D+) | 12 à 20 semaines (défaut 16) | 6–10 h |
| `ultra_80_100` | trail | 60 à 130 km (cœur de cible : 80–100 km) | 16 à 24 semaines (défaut 20) | 8–13 h |
| `cent_miles` | trail | 130 km et plus (~160 km) | 20 à 29 semaines (défaut 24) | 10–16 h |
| `route_semi` | route | 15 à 30 km | 8 à 16 semaines (défaut 12) | 3–6 h |
| `route_marathon` | route | 30 à 60 km (~42 km) | 12 à 20 semaines (défaut 16) | 4–9 h |

Les bandes de distance ne se chevauchent pas pour un même sport (vérifié) : la
distance de l'objectif actif désigne au plus un gabarit (borne basse incluse,
borne haute exclue : 60 km → `ultra_80_100`, 59,9 km → `marathon_trail`). Une
course de 50 km tombe dans le gabarit « marathon trail », la plus proche : à
adapter, et le coach le dit. Le choix ne regarde que la distance : pour une
course très dénivelée en haut de bande (par exemple 55 km et 3 500 m D+), le
coach peut prendre le gabarit suivant avec `--format` et dit pourquoi. Sans
`--sport`, la commande prend `[sport].primary` du workspace : les gabarits
route servent donc d'eux-mêmes quand `[sport].primary = road` ; ils n'ont pas
de D+. Aucun gabarit sous 15 km sur route (10 km) : la commande le dit
(`matched: null`).

## Ce que contient un gabarit

Cinq phases, dans cet ordre : **base**, **développement**, **spécifique**,
**affûtage** (la semaine de course en est la dernière semaine), puis
**récupération**, qui suit la course et ne compte pas dans la durée du bloc.
Pour chacune :

- une **durée en semaines** (minimum–maximum) ;
- la progression du **volume** et du **D+** (trail), en pourcentage de la
  semaine pic (= 100) : une valeur de début et de fin de phase ;
- la **répartition d'intensité** facile / modérée / difficile, au moins ~75 %
  de facile (approche polarisée « 80/20 ») ;
- le **nombre maximal de séances de qualité** par semaine ;
- la part de la **sortie longue** dans le volume hebdomadaire et son plafond en
  minutes ;
- l'**accent de renforcement** (un nom seulement : force maximale, force
  d'endurance, pliométrie/excentrique, entretien, mobilité — la bibliothèque
  d'exercices est une autre étape de l'épopée) ;

et, pour le gabarit entier, une **semaine allégée** toutes les N semaines
(facteur de volume et de D+, une seule séance de qualité au plus).

Voir ce qu'un gabarit donne, semaine par semaine :

```bash
python3 scripts/arc_index.py plan-templates --text                # liste lisible
python3 scripts/arc_index.py plan-templates --distance-km 90      # choisi d'après l'objectif (JSON)
python3 scripts/arc_index.py plan-templates --format marathon_trail --weeks 14 --text
python3 scripts/arc_index.py plan-templates --format route_semi
```

La sortie par défaut est du JSON, comme les autres sous-commandes (gabarit,
répartition des semaines par phase, semaines résolues, `peak_from_current`,
problèmes de validation, remarques, seuils utilisés, hypothèses) ; `--text`
rend un tableau lisible. Lecture seule : aucun index ni fichier n'est créé.

## Étirer ou comprimer : règles déterministes

Pour un nombre de semaines donné, entre le minimum et le maximum du gabarit :

1. chaque phase démarre à son minimum ;
2. les semaines restantes sont distribuées **une par une**, en parcourant
   l'ordre d'étirement du gabarit (développement, spécifique, base, affûtage)
   en boucle, à chaque phase qui n'a pas atteint son maximum ;
3. dans une phase, le volume (et le D+) progresse **linéairement** du début à la
   fin ;
4. la semaine *w* est une **semaine allégée** si *w* est un multiple de N, si
   sa phase est base, développement ou spécifique, et si la semaine suivante
   n'est pas déjà l'affûtage (la semaine avant l'affûtage reste la semaine pic) ;
   son volume vaut le facteur du gabarit × la dernière semaine non allégée.

Mêmes entrées, mêmes sorties : aucun aléa. Hors des bornes du gabarit, la
commande refuse (« 99 semaines hors de 20–29 »).

## La validation, cœur du livrable

`validate_template` (et la commande `plan-templates`, qui affiche son verdict)
vérifie chaque gabarit, pas seulement sa forme :

- **schéma** : clés inconnues refusées, pourcentages dans leurs bornes,
  répartition d'intensité qui totalise 100, phases dans l'ordre, accent de
  renforcement connu, mention « approximation du projet » présente ;
- **durées** : la somme des minima de phases tient dans le minimum du bloc, la
  somme des maxima couvre son maximum — toute longueur du bloc est réalisable ;
- **garde-fous**, sur les semaines **résolues pour chaque longueur possible** du
  bloc, avec les seuils du workspace (`[guardrails]`) :
    - [R2](guardrails.md) : hausse du volume ≤ le seuil (10 % par défaut) face à
      la référence configurée (`r2_volume_reference` : `mean4`, défaut du
      moteur, somme des 4 semaines précédentes divisée par 4 ; ou
      `previous_week`), calculée par la fonction même d'`arc_guardrails` (même
      arrondi) — les semaines d'avant le bloc valent la semaine 1, le volume
      que l'athlète tient déjà — **et** face à la dernière semaine non allégée
      (contrôle du projet, plus strict) ; avec `previous_week`, la reprise qui
      suit chaque semaine allégée dépasse forcément le seuil face à la semaine
      précédente : ce n'est pas compté comme un problème du gabarit, mais la
      commande le signale dans ses `notes` (`arc_guardrails.py check`
      avertira sur ces semaines-là) ;
    - R3 : la même chose pour le D+ ;
    - R6 : part de la sortie longue ≤ le seuil (35 % par défaut) ;
    - R7 : pas plus de 3 séances de qualité par semaine (le gabarit ne place pas
      de jours : les espacer est l'affaire du squelette) ;
- **structure** : semaines allégées présentes dès que le bloc compte au moins
  deux cycles ; affûtage placé dans les dernières semaines, décroissant, sous le
  pic, avec au moins 25 % de réduction au final ; semaine pic à 100 %.
- **cohérence entre gabarits** : identifiants uniques, bandes de distance sans
  chevauchement.

!!! warning "Le pic se déduit du volume tenu, il ne se choisit pas"
    Avec le seuil R2 par défaut (+10 % face à la moyenne de 4 semaines, creusée
    par une semaine allégée toutes les 4), un cycle de 4 semaines ne gagne que
    quelques pourcents : une montée depuis un volume bas fait réagir le
    garde-fou. Les gabarits livrés démarrent donc à environ 83–92 % de la
    semaine pic (plus bas pour les blocs longs) : **ils décrivent la forme d'un
    bloc à partir du volume que l'athlète tient déjà**, pas une reprise depuis
    un volume bas.

    D'où la règle, calculée par la commande (`peak_from_current`, aussi
    affichée par `--text`) : **pic = volume hebdomadaire moyen des 4 dernières
    semaines × `volume_factor`** (et D+ × `elevation_factor` en trail), jamais
    plus ; la semaine *n* vaut ensuite pic × `volume_pct` / 100. Si ce pic est
    trop bas pour l'objectif, le coach le dit et propose un bloc de mise en
    route préalable (ou un objectif revu) au lieu d'étirer le gabarit. Ce choix
    garde les gabarits cohérents avec les garde-fous tels qu'ils sont et donne
    au [générateur de squelette](#le-squelette-de-bloc-plan-skeleton) une règle
    déterministe : il part de l'historique réel et de ce facteur.

!!! note "La semaine de course"
    Le `volume_pct` de la dernière semaine d'affûtage s'entend **hors course** :
    la course elle-même n'entre pas dans ce pourcentage (pour un 100 miles, elle
    dépasse à elle seule la semaine pic).

La validation porte sur les seuils, pas sur l'athlète : elle ne dit rien de
l'historique réel, que seul `arc_guardrails.py check` évalue.

## Le squelette de bloc (`plan-skeleton`)

`arc_index.py plan-skeleton` transforme un gabarit en **squelette daté**, de la
semaine en cours à la semaine de course (puis la récupération post-course).
C'est une **proposition** : un *dry run* par défaut, rien n'est écrit sans
`--write`.

```bash
python3 scripts/arc_index.py plan-skeleton --text                      # gabarit choisi d'après l'objectif actif
python3 scripts/arc_index.py plan-skeleton --format ultra_80_100 --race-date 2027-02-14
python3 scripts/arc_index.py plan-skeleton --held-hours 5 --held-elevation-m 1200   # volume déclaré
python3 scripts/arc_index.py plan-skeleton --lead-in-weeks 2           # 2 semaines de mise en route prises au gabarit
python3 scripts/arc_index.py plan-skeleton --lead-in flat              # mise en route au volume tenu (comportement #190)
python3 scripts/arc_index.py plan-skeleton --write                     # écrit planning/Semaine_<lundi>.md
```

Entrées : le gabarit (`--format`, sinon choisi d'après la distance de
l'objectif et `[sport].primary`), la date de course (objectif actif ou
`--race-date`), le **volume tenu** (moyenne des 4 dernières semaines complètes
de course à pied dans l'index : durée, D+, distance — ou `--held-hours` /
`--held-elevation-m` déclarés), et la disponibilité du profil
(« Disponibilité hebdomadaire » : nombre de séances et plus grande durée en
heures ; « Jours impossibles » ; « Sortie longue » facultatif ou
`--long-run-day`).

Chaque semaine porte : le début (lundi), la phase, le **type** (`build`,
`recovery`, `taper`, `race`, `lead_in`, `post_race`), la durée visée (le volume
se compte en **durée**, ce que compare R2) et le D+ visé, le nombre de séances
de qualité, la sortie longue visée, la répartition d'intensité, l'emphase de
renforcement et des **créneaux de séance** (`placeholder: true`) posés sur les
jours disponibles — pas des séances : le coach les habille.

- **Pic** = volume tenu × `peak_from_current`, jamais inventé ; si le pic
  dérivé est sous le pic indicatif du gabarit, un avertissement le dit (d'abord
  une mise en route qui fait réellement monter le volume tenu, puis relancer
  `plan-skeleton`, ou un objectif revu — jamais un gabarit étiré). Un plafond
  d'heures du profil ramène le pic à ce plafond, et le dit. Après une mise en
  route en rampe, le « volume tenu » de cette règle est le volume **atteint**
  en fin de mise en route (voir plus bas).
- **Trop court** (moins de semaines que le minimum du gabarit) :
  `status: "too_short"`, aucune semaine, options explicites (format plus court,
  date de course au plus tôt, bloc sans gabarit). **Trop long** (plus que le
  maximum) : des semaines de mise en route (`lead_in`), avec une semaine
  allégée tous les N, avant le gabarit. Elles **font monter le volume** (#204,
  voir [La mise en route qui construit](#la-mise-en-route-qui-construit)).
- **Pas d'historique** (moins d'1 h par semaine) : `status: "no_history"` — le
  coach demande le volume actuel de l'athlète, jamais inventé.
- **Départ** : le lundi de la semaine en cours si c'est aujourd'hui, sinon le
  lundi suivant (la semaine entamée n'est pas touchée).
- **Garde-fous** : chaque semaine passe `arc_guardrails.evaluate` (la fonction
  du moteur), avec pour référence R2/R3 les semaines déjà générées. Une
  violation R2/R3 réduit la semaine ; un `block` retire la qualité puis réduit ;
  s'il persiste, la semaine n'est **pas** émise (`unresolved`, statut
  `needs_review`). Un squelette ne contient jamais de semaine `block` ; les
  `warn`/`info` restants (ACWR projeté…) sont rendus tels quels, par semaine.
- **Semaine de course et récupération** : jusqu'à 3 footings avant la course,
  jamais la veille (laissée libre : repos ou déverrouillage court, au choix du
  coach), volume au prorata des jours avant la course (6/6 un dimanche, 1/6 un
  mardi). Aucun créneau de course à pied dans les 3 jours qui suivent la
  course ; la semaine concernée garde le volume du gabarit au prorata des jours
  restants.
- **Référence `previous_week`** : la reprise qui suit une semaine allégée (ou
  post-course) n'est pas réduite tant qu'elle reste sous la dernière semaine
  non allégée + seuil, comme pour la validation des gabarits ; le `warn` R2/R3
  reste affiché.
- **Vérifier une semaine écrite** : le verdict du squelette compare chaque
  semaine aux semaines générées avant elle. `arc_guardrails.py check --week`
  sur un fichier `Semaine_<lundi>.md`, lui, compare à l'historique **réel** :
  lancé sur une semaine lointaine, il voit des semaines intercalaires vides
  (R2/R3 et ACWR projeté sans objet). Le coach repasse donc `check` sur chaque
  semaine au moment où elle devient la **prochaine**, après l'avoir habillée.
- **Forme prévue le jour J** : le squelette est projeté par
  [`load-forecast`](guardrails.md) (estimation à partir de créneaux dont
  l'intensité est un placeholder : un ordre de grandeur, pas une mesure).
- **`--write`** : un fichier `planning/Semaine_<lundi>.md` par semaine (comme le
  coach le fait aujourd'hui), bloc `arc` validé par `arc_index.py --validate`.
  **Aucun écrasement** : si une semaine existe déjà (fichier du même nom ou
  entrée d'un plan multi-semaines), rien n'est écrit et les conflits sont
  listés. Le dry run les signale déjà (`conflicts`).

Les coefficients propres au squelette (poids des sorties faciles, durée du
créneau de renforcement, séances par défaut…) sont des « approximations du
projet », listés dans `ASSUMPTIONS` de `scripts/arc_plan_skeleton.py`.

### La mise en route qui construit

Un gabarit décrit la forme d'un bloc **à partir d'une base déjà construite** :
il démarre à 83–92 % de son pic, et sa règle (pic = volume tenu ×
`peak_from_current`) ne fait gagner qu’environ +9 à +21 % sur tout le bloc selon le format.
Construire cette base est le rôle de la mise en route (#204).

- **Quand** : les semaines au-delà du maximum du gabarit, ou
  `--lead-in-weeks K` pour en prendre K au gabarit (qui raccourcit alors, sans
  jamais descendre sous son minimum : la commande refuse et dit combien de
  semaines restent possibles). Plus de semaines que demandé ? L'excédent
  l'emporte.
- **Comment** (`--lead-in ramp`, défaut) : chaque semaine pleine vise
  **+4 %** face à la précédente, plafonnée **d'emblée** par le seuil R2 (durée)
  et R3 (D+) face à la référence configurée (`mean4` ou `previous_week`), et par
  le plafond d'heures du profil — une semaine plafonnée le dit. Une semaine
  allégée tous les N (facteur du gabarit × la dernière semaine pleine), jamais
  la dernière avant le gabarit. Chaque semaine repasse ensuite les garde-fous
  comme les autres : aucune semaine `block` n'est émise.
- **Puis** : le gabarit part du volume **atteint** en fin de mise en route
  (`peak.base`, `peak.lead_in_gain_pct`) et le pic vaut ce volume ×
  `peak_from_current` — la règle de #189 inchangée, appliquée à un volume tenu
  plus haut.
- **Ordres de grandeur** (seuil R2 par défaut, référence `mean4`) : environ
  +8 % en 2 semaines, +16 % en 6, +28 % en 12. Une course à 18 semaines d'un
  ultra (gabarit de 16 à 24 semaines) n'en laisse que 2 : la mise en route ne
  remplace pas une base construite plus tôt.
- **`--lead-in flat`** garde le comportement de #190 (mise en route au volume
  tenu, pic inchangé).

Le taux de +4 % est une approximation du projet (`LEAD_IN_RAMP_PCT`) ; les
garde-fous restent la référence.

### Le contrôle face aux exigences de la course (`race_demand`)

Un squelette peut passer tous les garde-fous et rester très en dessous de ce
que la course demande (une sortie longue de 2 h 40 pour un 85 km). Le
squelette le **dit** : `race_demand` compare le bloc aux cibles du
[score Trail Shape](agents/coach.md#score-trail-shape-63) — les mêmes
fonctions, aucune seconde formule :

| Composante | Squelette | Cible |
|---|---|---|
| Volume de la semaine pic | durée × allure tenue + D+/100 (km-effort) | `weekly_volume_target_km` (km-effort de la course) |
| D+ de la semaine pic (trail) | D+ visé le plus haut | cible de km-effort × part du D+ dans l'effort de la course |
| D+ max d'une séance (trail) | créneau le plus dénivelé | `min(50 % du D+ de la course, 2 500 m)` |
| Plus longue sortie | sortie longue visée × allure tenue | `longest_run_target_m` (60 % de la distance, entre 30 et 60 km) |
| Volume cible déclaré | pic (durée, distance) | « Volume hebdomadaire cible » de l'objectif actif, s'il est rempli |
| Sortie longue / temps de course | part en % | information seulement, sans seuil (plan de course, sinon temps visé) |

- Le D+ hebdomadaire n'ajoute aucun coefficient : la même densité de
  dénivelé que la course (pour 85 km / 4 500 m, environ 2 400 m la semaine pic).
- Le squelette se compte en durée : la distance vient de l'allure moyenne
  **tenue**. Sans distance tenue (volume déclaré en heures seules), les
  composantes en km sont dites **non évaluables**, jamais devinées ; de même
  sans D+ de course, ou si l'objectif actif vise une autre date que
  `--race-date`.
- Sous **75 %** de la cible (approximation du projet, `DEMAND_WARN_RATIO`),
  la composante est `short` et un avertissement l'explique, avec les options :
  mise en route plus longue (`--lead-in-weeks`), course plus tardive, objectif
  revu ou base construite d'abord. Le contrôle **n'écrit rien et ne modifie
  aucune semaine** : jamais un garde-fou forcé pour combler l'écart.

## D'où viennent les chiffres

Tous les nombres (durées de phase, pourcentages du pic, D+, répartition
d'intensité, plafonds de sortie longue, fréquence des semaines allégées,
affûtage, pics horaires) sont des **approximations du projet** : des points de
départ prudents, réglables en éditant les fichiers `config/plans/*.json` (la
validation dit aussitôt si le résultat reste cohérent avec les garde-fous).
Ils ne proviennent d'aucun protocole publié et aucun plan commercial n'est
reproduit.

Deux publications, vérifiées dans Crossref, orientent seulement la *direction*
de deux choix, jamais un chiffre :

- Mujika I., Padilla S., « Scientific bases for precompetition tapering
  strategies », *Medicine & Science in Sports & Exercise* 35(7):1182-1187, 2003,
  [doi:10.1249/01.MSS.0000074448.73931.11](https://doi.org/10.1249/01.MSS.0000074448.73931.11)
  — l'affûtage réduit le volume en conservant l'intensité ;
- Seiler S., « What is best practice for training intensity and duration
  distribution in endurance athletes? », *International Journal of Sports
  Physiology and Performance* 5(3):276-291, 2010,
  [doi:10.1123/ijspp.5.3.276](https://doi.org/10.1123/ijspp.5.3.276) — la
  distribution d'intensité polarisée.

## Dans le workflow du coach

Pour un nouveau bloc, le coach lance `plan-skeleton` (dry run), présente le
squelette à l'athlète, **n'écrit qu'après son accord** (`--write`), puis habille
lui-même les séances (contenu, allures, cibles), en adaptant au profil, au
bilan matinal et à l'historique. Sans
gabarit adapté, il construit le bloc comme avant et le dit. Les pourcentages
sont relatifs à une semaine pic que le coach dérive de l'historique réel — il
n'invente jamais de volumes absolus. Voir [Coach](agents/coach.md#gabarits-de-periodisation-189).
