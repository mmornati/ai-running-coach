# Agent Stratège de course

> **Description** : Course Strategy Specialist — analyse les parcours GPX ou les URL de course, construit des plans de course détaillés avec allure, nutrition, météo, matériel, et téléverse le GPX enrichi dans Garmin avec les points d'eau.

<!-- arc-video:jour-de-course -->
<div class="arc-video-card" markdown>

[![La course, segment par segment](../video/jour-de-course/poster.jpg)](../video/jour-de-course/index.html)

<div markdown>

<span class="arc-video__meta">En vidéo · Étape 06 · 1 min 43</span>

**[La course, segment par segment](../video/jour-de-course/index.html)** — Du GPX au plan de course : allures par segment, énergie, matériel obligatoire, montre, puis débrief plan contre réalisé.

[Regarder](../video/jour-de-course/index.html) · [English](../video/jour-de-course/index.html?lang=en) · [Toutes les vidéos](../videos.md)

</div>

</div>
<!-- /arc-video -->


## Rôle

L'agent **course-strategist** transforme un fichier GPX ou une URL de course en un plan de course complet et actionnable.

## Workflow — 8 étapes

L'agent suit un workflow structuré en 8 étapes pour construire la stratégie de course :

1. **Analyse d'entrée** — GPX (analyse générique via le skill `gpx-analysis`) ou URL de course (extraction via `webfetch`)
2. **Points d'eau et ravitaillement** — points officiels + enrichissement OpenStreetMap (Overpass), alertes sur les écarts > 8 km / > 15 km
3. **Vérification et questions utilisateur** — comble les informations critiques manquantes (barrières horaires, terrain, points d'eau proposés) avant de continuer
4. **Synthèse allures et temps de passage** — 3 scénarios (ambitieux, réaliste, sécurité), par segment depuis le modèle personnel pente → allure quand un GPX est fourni (`scripts/arc_race_pacing.py`, #59) ; règles génériques en repli (URL seule, sans GPX)
5. **Plan de nutrition** — objectif glucides/h (plafonné au débit toléré à l'entraînement, #41), hydratation, produits réels si un catalogue est fourni
6. **Météo** — si la course est à ≤ 14 jours, ajustements automatiques et acclimatation à la chaleur (#38)
7. **Équipement et vêtements** — checklist détaillée (lampe frontale, chaussures, hydratation, matériel obligatoire), puis **contrôle du matériel de course** (#134) : la liste `gear` du plan est croisée avec l'inventaire du profil (`arc_index.py equipment --race-plan`) — objets **manquants** (« non retrouvé dans votre inventaire »), **à vérifier** (seule la catégorie correspond — jamais donné pour conforme), **jamais utilisés à l'entraînement** (« rien de nouveau le jour J ») ou **sous alerte** ; le rapprochement est textuel strict et rien n'est jamais inventé (inventaire non déclaré = dit tel quel)
8. **Upload Garmin** — GPX enrichi (waypoints des ravitaillements) téléversé via `upload_course`

## Alignement avec l'objectif

- **Contexte** : aligne toujours la stratégie de course avec l'objectif actif dans `planning/active_objective.md`
- **Mise à jour** : propose de mettre à jour `planning/active_objective.md` si la course devient le nouvel objectif principal

## Gestion des données

- **Rafraîchissement contextuel** : vérifie `planning/`, `activities/`, `medical/` et `resources/` avant d'analyser
- **Persistance** : stocke chaque plan de course dans `planning/` et le plan nutritionnel dans `nutrition/`
- **Langue** : les fichiers MD utilisent la langue configurée dans `config/workspace.toml` (`[language].documents`, défaut : français)
- **Indice de performance (#62)** : peut citer l'indice ITRA/UTMB déclaré dans le profil comme un repère qualitatif parmi d'autres pour choisir un scénario d'allure — jamais de conversion inventée indice → allure, et jamais de recherche automatique sur `itra.run`/`utmb.world` (uniquement sur demande explicite, voir l'agent `coach`)

## Skills utilisés

| Skill | Quand |
|---|---|
| `gpx-analysis` | analyse du parcours GPX (étape 1) |
| `weather-forecast` | préparation météo (étape 6, course à ≤ 14 jours) |
| `workspace-data-contract` | avant d'écrire un plan de course dans `planning/` ou un plan nutrition dans `nutrition/` |

## Allures par segment (#59)

Quand un GPX est fourni, l'agent délègue le calcul des allures à
`scripts/arc_race_pacing.py plan` plutôt que d'estimer à la main : découpage du
parcours en segments (distance cible fusionnée par pente similaire), intégré
point par point (pas la seule pente moyenne — un aller-retour compte plus
qu'un plat) pour prédire le temps de chaque segment depuis le modèle personnel
pente → allure (`scripts/arc_slope_model.py`, #58), mis à l'échelle de
l'intensité de COURSE visée — Riegel depuis un effort RÉCENT et DUR (tempo/
seuil/VO2max/course, jamais un simple footing) converti en équivalent plat des
deux côtés, VDOT en repli (`scripts/arc_metrics.py`, #33 — `arc_slope_model`
ne connaît que l'allure d'ENDURANCE d'entraînement), calculée sur le GPX
analysé, jamais sur `planning/active_objective.md`. Fade de fin de course
depuis la durabilité récente (`scripts/arc_durability.py`, #48, rendu NEUTRE
en temps total quand Riegel/VDOT s'applique déjà — jamais une double
dégradation d'endurance — ou un repli générique signalé comme tel, échelonné à
la durée réelle de la course), ajustement chaleur/acclimatation (#38), pénalité de nuit (#184) et d'altitude (#185), voir ci-dessous, et
vérification des barrières
horaires (formats `HH:MM`, `+HH:MM` élapsé ou date-heure ISO 8601 pour un
ultra multi-jours). Chaque segment porte sa **provenance**
(`personal`/`generic`/`mixed`) — le plan la cite explicitement, jamais un
scénario qui prétendrait à une précision que l'historique ne permet pas ; un
GPX sans altitude exploitable déclenche un avertissement explicite (`warnings`)
plutôt qu'un plan silencieusement faux. Persisté dans le champ `segments` du
bloc ```arc `race_plan` (voir
[le skill `workspace-data-contract`](../skills/workspace-data-contract.md)) —
socle du débrief post-course segment par segment (`scripts/arc_race_debrief.py`,
#61 : voir [l'agent Coach](coach.md)).

## Pénalité de nuit (#184)

Sur un ultra, une partie de la course se court de nuit. Avec `--race-date`, un
`--start` explicite et `--tz` (fuseau IANA, ex. `Europe/Paris`),
`scripts/arc_race_pacing.py plan` calcule **localement, sans réseau**
(`scripts/arc_solar.py`, algorithme NOAA — approximation de l'ordre de la
minute) le crépuscule civil du lieu (premier point du GPX) et la **fraction de
nuit** de chaque section, scénario par scénario, d'après son heure d'horloge
réelle (départ, temps de section déjà pénalisés, arrêts ravito). Le temps de la
section est multiplié par `night_factor` = 1 + fraction de nuit × pénalité :
**5 %** à pleine nuit à plat/en montée, jusqu'à **+8 points** en descente
(0,6 point par % de pente au-delà de 2 %) — des **approximations du projet**,
aucune source vérifiée ne les chiffre pour un athlète donné ; réglables
(`--night-penalty-pct`, `--night-descent-extra-max-pct`) ou désactivables
(`--no-night`), et à recalibrer au débrief (#188). Le calcul itère (la pénalité
décale les sections suivantes) jusqu'à convergence, bornée à 8 passes, et garde
toujours `prudent ≥ réaliste ≥ ambitieux` section par section.

La sortie ajoute `night_fraction`/`night_factor` par section et par scénario,
et un objet `night` : `status` (`night`, `daylight`, `unavailable`,
`disabled`), `scenarios[...].summary` (« 6,8 h de nuit, frontale requise de
17:32 à 00:18 (J+1) ») et `gear_hint`. **Si la date, l'heure de départ
explicite ou le fuseau manquent, aucun facteur de nuit n'est appliqué, la sortie
reste identique à celle d'avant et `night.reason` le dit** — jamais une nuit
supposée. Une course entièrement de jour n'ajoute aucun champ par section. Le
contrôle de la frontale dans le matériel obligatoire reste celui de
`arc_index.py equipment --race-plan` (#134).

**Fuseau.** La bibliothèque standard n'offre aucune correspondance hors ligne
lieu → fuseau : le fuseau reste une entrée. L'agent le reprend du champ
`timezone` d'un plan déjà persisté, sinon le déduit du lieu quand il est sans
ambiguïté (pays à fuseau unique) en le disant, et ne le demande qu'en cas
d'ambiguïté ; il le persiste ensuite dans `timezone` du bloc ```arc. Le script
contrôle grossièrement sa vraisemblance (écart de plus de 3,5 h entre le
décalage UTC du fuseau et l'heure solaire de la longitude du départ →
`night.timezone_warning`). Le temps écoulé est compté en UTC : une course qui
traverse le passage à l'heure d'hiver reste juste, l'affichage suit l'heure
locale du moment.

## Roadbook imprimable (#187)

Une fois le plan écrit ou mis à jour, l'agent mentionne le **roadbook** : la vue
`#/roadbook` du [tableau de bord](../dashboard/views.md#roadbook) (adresse locale
du tableau de bord, `scripts/dashboard.sh`) en tire une feuille A4 par scénario
— profil, sections, heures de passage, barrières et marges, ravitos avec ce
qu'on y prend, matériel obligatoire, urgence — à imprimer ou enregistrer en PDF
depuis le navigateur. Rien n'est recalculé : la page lit le plan persisté, donc
**ce que le plan ne contient pas manque aussi sur la feuille** (et l'encart
« À compléter » le dit).

Pour que la feuille soit complète, l'agent écrit dans le bloc ```arc du plan :
`start_time` (date-heure ISO du départ, sans quoi pas d'heures de passage à
l'horloge), `cutoff` des ravitos qui en ont, **`take`** de chaque ravito (liste
courte de ce que le plan nutrition y fait prendre — il ne l'invente pas : il le
recopie du fichier `nutrition/`), `gear` (le contrôle contre l'inventaire est
celui de `arc_index.py equipment --race-plan`), `emergency` (organisation,
points d'abandon) et `notes`. `nutrition_plan` pointe vers le fichier du plan
de ravitaillement.

## Altitude corrigée par MNT (#176)

Sur demande (ou avec `[elevation].dem = "auto"`), `analyze_gpx.py --dem` et
`arc_race_pacing.py plan --dem` rééchantillonnent l'altitude du GPX sur un modèle
numérique de terrain (IGN RGE ALTI en France, Copernicus GLO-90 via Open-Meteo
ailleurs). Le **D+ MNT devient la référence** de l'évaluation de parcours et du
plan (segments, allures, énergie) ; l'agent présente toujours « D+ fichier / D+ MNT »
avec l'écart, cite l'attribution et relaie l'avertissement si le service est
indisponible (altitude du fichier conservée, jamais de valeur inventée). Seules des
coordonnées amincies sont envoyées, jamais par défaut : voir
[la page Correction altimétrique](../elevation.md).

## Technicité du terrain (#186)

Un sentier de randonnée alpine ne se court pas comme une piste forestière :
avec `--technicity`, `arc_race_pacing.py plan` multiplie le temps de chaque
section par un coefficient de technicité, **en plus** du modèle pente → allure,
de la chaleur et de la nuit. Deux sources, combinables (la déclaration gagne,
section par section) :

- **déclarée** : `--technicity technicite.json`, avec
  `{"sections": [{"km_start": 12, "km_end": 18, "coef": 1.25, "note": "pierriers"}]}`
  (1,0 = « comme à l'entraînement », 1,25 = très technique ; bornes 0,8 à 1,8) ;
- **dérivée d'OpenStreetMap** : `--technicity osm` interroge Overpass (les mêmes
  serveurs que les points d'eau) pour les chemins proches de la trace, apparie
  chaque point au chemin le plus proche à moins de 20 m et traduit `sac_scale`,
  `trail_visibility`, `surface`, `tracktype` et `highway` en coefficient. **Opt-in,
  réseau** : seul le GPX de la course part (boîtes englobantes arrondies, jamais une
  trace d'activité personnelle), une requête à la fois, réponses en cache dans
  `<workspace>/.arc/overpass/`. Hors ligne : aucun coefficient OSM, une note
  explicite, jamais d'échec.

La table tags → coefficient (par exemple `sac_scale=mountain_hiking` +6 %,
`alpine_hiking` +30 %, `surface=rock` +12 %, `trail_visibility=bad` +12 %,
dominant + moitié du deuxième, plafond 1,8, jamais sous 1,0 côté OSM) et la
pondération par la pente (×0,7 en montée, ×1,0 à plat, jusqu'à ×1,5 en descente
raide) sont des **approximations du projet** (`assumptions.technicity`), pas des
mesures. Le facteur est le même pour les trois scénarios (l'ordre
`prudent ≥ réaliste ≥ ambitieux` est donc conservé) et s'applique avant la nuit.
Attention : le modèle personnel a appris sur ton terrain habituel — un
coefficient déclaré exprime l'écart avec CE terrain. La table OSM, elle, part
d'un chemin facile : indique ton terrain d'entraînement habituel avec
`--technicity-baseline` (ex. `mountain_hiking` si tu t'entraînes déjà sur
sentiers de montagne, ou un nombre de 1,0 à 1,8) pour que seul l'écart soit
compté ; sans elle, un avertissement rappelle que la pénalité est surestimée.
Les km déclarés sont des km officiels, rééchelonnés comme les ravitos avec
`--official-distance-m`. Overpass occupé (429/504) : deux nouvelles tentatives
espacées, puis « indisponible » ; le cache `.arc/overpass/` n'expire pas
(le supprimer pour rafraîchir). OSM décrit le chemin, pas son état du jour.

La sortie ajoute `technicity` par section (`coef`, `effective_factor`, `source`,
`tags`) et un résumé au niveau du plan. Sans `--technicity`, rien ne change.

## Pénalité d'altitude (#185)

Au-dessus d'un seuil de **1 500 m** (choix du projet), `arc_race_pacing.py plan` majore le
temps de chaque section d'un facteur qui croît avec son **excédent moyen au-dessus du seuil**,
pondéré par la distance (une section qui franchit le seuil, col de 1 200 à 2 800 m, n'est
pénalisée que pour sa partie haute). Altitudes du GPX, ou du MNT quand la correction
`elevation_dem` du plan est présente (#176 : `altitude.elevation_source` le dit). La pente vient
de Wehrlin & Hallén 2006 (*Eur J Appl Physiol* 96:404-412, doi:10.1007/s00421-005-0081-9) : la
VO2max baisse de **6,3 % par 1 000 m** (plage individuelle 4,6-7,5 %, linéaire de 300 à 2 800 m,
8 athlètes d'endurance en chambre hypobare, exposition aiguë).
**La traduction de cette perte de VO2max en perte de vitesse d'ultra est une approximation du
projet**, pas un résultat de l'étude : à fraction constante de la VO2max la vitesse baisserait
d'autant, mais une allure d'ultra (environ 50-70 % de la VO2max) dépend aussi de la fatigue
musculaire, de l'alimentation et du terrain. Le modèle **atténue** donc la pente en ne comptant
la perte qu'au-dessus de 1 500 m (l'étude part de 300 m) : il applique environ 30 % de la perte de
VO2max de l'étude à 2 000 m, 45 % à 2 500 m, 50 % à 2 800 m — atténuation choisie, non mesurée
(facteur de temps = 1/(1 − perte)). Le critère de performance de l'étude (temps jusqu'à
épuisement à 107 % de la VO2max, −14,5 % par 1 000 m) n'est pas repris : effort supra-maximal.
Au-delà de 2 800 m, hors de la plage mesurée, la pénalité est extrapolée (avertissement) et
l'altitude est plafonnée à 4 500 m pour le calcul.

**Acclimatation.** Sans information, l'athlète est supposé non acclimaté (pénalité pleine).
`--altitude-acclimated-days N` (jours déjà passés en altitude) et l'exposition mesurée à
l'entraînement (`arc_index.py altitude-exposure`, 28 derniers jours, résolue par le script) réduisent la
perte, jamais à zéro : crédit plafonné à 50 % (déclaré : jusqu'à 14 jours ; entraînement :
jusqu'à 25 %, à 10 h au-dessus de 1 500 m) — approximations du projet, `assumptions.altitude`.
L'exposition mesurée n'est créditée que si la course a lieu **14 jours au plus** après la fin de
la fenêtre mesurée (`--race-date` requis, `altitude.acclimation.training_credited`) : un plan
calculé des semaines à l'avance est à recalculer dans les deux dernières semaines.
Réglages : `--altitude-threshold-m`, `--altitude-loss-pct`, `--no-altitude`. Le coefficient
personnel `[pacing.personal].altitude_scale` (#188, recalibré au débrief) multiplie le **surcoût**
de chaque section (facteur − 1, après le crédit d'acclimatation) ; `--altitude-loss-pct` en ligne
de commande prime sur lui. Quand il joue, il figure dans `altitude.parameters.personal_scale` et
dans `pacing_personal` du plan.

**Changement de comportement pour les plans existants.** La pénalité est active par défaut : un
plan de course dont une section dépasse 1 500 m, recalculé après #185, donne des temps plus longs
qu'avant (par exemple environ +8 % sur une section courue autour de 2 700 m, sans acclimatation).
L'avertissement du plan le dit ; `--no-altitude` redonne exactement l'ancien calcul. Les plans
déjà persistés ne changent pas tant qu'ils ne sont pas recalculés, et les champs ajoutés
(`altitude_m`, `altitude_factor`) sont optionnels dans le contrat `race_plan`.

**Composition.** Le facteur (`altitude_m`, `altitude_factor` par section) est identique pour
les trois scénarios, se compose par multiplication avec la chaleur, la technicité et la nuit
(ordre du calcul : correction MNT éventuelle → modèle pente → allure, avec la chaleur → fade →
technicité → altitude → nuit ; une seule étape du calcul) et conserve `prudent ≥ réaliste ≥ ambitieux`. **Si aucune
section ne dépasse le seuil, les temps et les sections sont identiques à ceux d'avant** : seul
l'objet `altitude` (`status` : `applied`, `below_threshold`, `no_elevation`, `disabled`) s'ajoute.

## Recalibrage des coefficients au débrief (#188)

Nuit, technicité, chaleur et altitude sont des **hypothèses du projet**
(`ASSUMPTIONS`). Après la course, `scripts/arc_race_debrief.py debrief --plan …
--activity … --calibrate --workspace <workspace>` mesure l'erreur qui revient à
chaque facteur et **propose** des coefficients personnels (JSON par défaut,
`--text` pour lire). Rien n'est jamais appliqué seul.

- **Méthode simple et transparente** : rapport des médianes (pondérées par le
  temps prévu) des ratios réalisé/prévu entre segments *exposés* (nuit, terrain
  technique, altitude) et segments de *référence* (jour, roulant, basse altitude),
  **dans la même cellule** des autres facteurs — jamais une section de nuit
  technique contre une section de jour roulante — et dans une fenêtre de position
  autour de l'exposition (pour ne pas confondre « de nuit » et « tard dans la
  course »). Le biais commun (allure de base, durabilité) s'annule dans le rapport.
  Pas de régression : avec quelques dizaines de segments corrélés, elle sur-ajusterait.
- **Refus argumentés** : trop peu de segments (4 minimum par groupe et par
  cellule), facteur **confondu** (toutes les sections techniques sont aussi de
  nuit, par exemple), écart dans le bruit. Le facteur dit pourquoi, il ne
  propose rien. Un débrief « dans le bruit » laisse quand même sa preuve, pour
  que le cumul ne retienne pas que les courses à gros écart.
- **Fatigue et course anormale** : quand l'exposition occupe la fin de la course
  (nuit tombante), toute la référence est plus tôt ; l'écart de position est
  publié (`position_gap`) et, au-delà de 15 % de la distance, la confiance est
  plafonnée à « faible ». Une fin de course anormale (dernier quart 1,5 × plus
  lent que la première moitié, par rapport au plan : blessure, fin marchée) fait
  tout refuser (`abnormal_fade`) ; `--exclude-from-km KM` écarte la partie
  touchée par un incident déclaré par l'athlète.
- **Nuit** : la pénalité calibrée est la pénalité de **base** ; le supplément de
  descente du plan est retranché de l'observé, jamais ré-attribué à la base.
- **Attrition vers le défaut** : `nouveau = défaut + w × (observé − défaut)`,
  `w = n / (n + 20)` (n = segments exposés cumulés ; approximation du projet).
  Un seul débrief ne déplace donc jamais le coefficient jusqu'à l'observation brute.
- **Cumul** : chaque débrief laisse une preuve (course, facteur, n, valeur
  absolue) dans `[pacing.personal].evidence` ; les suivants se **combinent**,
  rejouer le même débrief ne le compte pas deux fois.
- **Chaleur** : un seul facteur pour toute la course, donc pas de contraste
  interne ; estimée **entre** courses, et **aucune proposition avant deux courses
  chaudes** et une sans correction météo débriefées, confiance faible. **Altitude** : seulement si le plan porte `altitude_factor` ; le
  `altitude_scale` proposé est l'échelle du surcoût d'altitude, appliquée par
  `arc_race_pacing.py` aux plans suivants.
- **Écriture après accord** : après confirmation explicite de l'athlète,
  `… --calibrate --apply` écrit `[pacing.personal]` dans
  `config/workspace.user.toml` ; `arc_race_pacing.py` le relit aux plans
  suivants, les drapeaux CLI (`--night-penalty-pct`, `--altitude-loss-pct`) gardant la priorité.
  Voir [la configuration](../configuration.md#les-coefficients-de-pacing-personnels-pacingpersonal).

## Dépense énergétique prévue par section

La sortie de `scripts/arc_race_pacing.py plan` porte aussi `energy` (kcal,
kcal/h et cumul par segment, pour chacun des trois scénarios) — un contrôle/
outil de PRÉVISION indépendant, calculé depuis le même moteur RE3 + Minetti
que le contrôle post-séance de l'agent `coach` (`scripts/arc_energy.py`).
`--pack-kg` (poids du sac/flasques/matériel porté) est nécessaire pour
un résultat fidèle — l'agent le demande à l'athlète, ou dit explicitement
qu'il l'estime faute de réponse ; sans lui, le calcul suppose 0 kg et le
signale dans `warnings`. Un poids d'athlète introuvable
(`energy.available == false`) n'invalide jamais le reste du plan. L'agent met
le kcal/h prévu par section en regard du plan de ravitaillement (étape 5) pour
signaler un déficit horaire/cumulé, sans jamais prétendre qu'il doit être
comblé intégralement — qualitatif faute d'une source vérifiable sur la part
couverte par les réserves de l'athlète. `energy` reste un KPI DÉRIVÉ exposé
par la CLI, jamais une clé du contrat `race_plan` persisté (même statut que
`scripts/arc_index.py fueling`).

**Calibration personnelle** : chaque scénario, et chaque section à
l'intérieur de ce scénario, porte à côté des valeurs brutes
(`kcal`/`kcal_per_h`/`cumulative_kcal`) leurs équivalents
`kcal_calibrated`/`kcal_per_h_calibrated`/`cumulative_kcal_calibrated` — un
facteur personnel (`energy.calibration`, `{"band", "band_source", "n",
"ratio_median", "ratio_iqr", "status", "factor"}`) appris sur l'écart
Garmin/modèle mesuré de l'athlète. Le panier (route ou trail) est choisi
depuis le D+/km réel du GPX analysé (`band_source == "gpx"`), ou forcé
explicitement par `--terrain road|trail` (`band_source == "option"`) — jamais
depuis le profil général de l'athlète, voir [Dépense énergétique — la
calibration personnelle](../energie.md#la-calibration-personnelle). L'agent
utilise TOUTES les valeurs calibrées (jamais un mélange avec les brutes)
uniquement quand `status == "applied"` (échantillon suffisant, écart non
négligeable) ; sinon toutes les valeurs brutes — jamais présentées comme une
mesure quand calibrées.

## Fichier source

`agents/course-strategist.md` · moteur : `scripts/arc_race_pacing.py`
