---
name: workspace-data-contract
description: Contrat de données des fichiers persistés — chaque fichier écrit dans activities/, medical/, nutrition/, planning/ (semaines, évaluations, plans de course) ou rapports/ s'ouvre par un bloc ```arc de JSON typé, en unités SI, validé par scripts/arc_index.py --validate. Charger AVANT d'écrire ou de réécrire un de ces fichiers, et pour le backfill des fichiers anciens.
---

# Contrat de données du workspace

Le Markdown reste la source de vérité. Mais un tableau, un titre ou une puce ne
se calculent pas : la langue des documents est configurable, les libellés
varient, les colonnes bougent. Tout ce qui doit être **compté, tracé ou comparé**
va donc dans un bloc structuré, en tête de fichier. Le texte du coach reste
libre, en dessous.

Le tableau de bord (`scripts/dashboard.sh`) et la comparaison de parcours lisent
ce bloc — jamais la prose.

## La forme

Juste après le titre `# …`, un seul bloc clos étiqueté `arc`, contenant **un
objet JSON** :

````markdown
# Séance du 2026-09-20 — Trail de Tournai

```arc
{"arc": 1, "kind": "activity", "date": "2026-09-20", "sport": "trail", "duration_s": 5218}
```

Analyse du coach, en français (ou dans la langue des documents), libre.
````

- `arc` vaut toujours `1` (version du contrat) ; `kind` dit le type de fichier.
- Les **clés sont en anglais et ne se traduisent jamais**, quelle que soit la
  langue des documents. Les valeurs textuelles (`name`, `verdict_reason`,
  `title`…) suivent la langue des documents.
- Un seul bloc ```arc par fichier.

## Règles

1. **Toujours en SI, sans unité dans la valeur** : mètres, secondes, kg, bpm,
   °C, km/h, mm. `"distance_m": 12400`, jamais `"12,4 km"`. Vrai **même si**
   `[athlete].units = "imperial"` : la conversion en miles est une affaire
   d'affichage et de réponse, pas de stockage.
2. **Une mesure absente est absente** : omettez la clé (ou `null`). Jamais `0`
   pour « pas mesuré ». Si l'absence a une cause connue, dites-la dans
   `missing_reason` : `{"recovery_hr_bpm": "activité validée avant 2 min"}`.
3. **Les nombres sont des nombres** : `148`, pas `"148"` ; `3.8`, pas `"3,8"`.
4. **Pas de clé inventée.** Une clé hors contrat est signalée par le
   validateur : c'est presque toujours une faute de frappe qui ferait perdre la
   valeur. Ce qui n'a pas de clé va dans le texte, sous le bloc.
5. **Le bilan matinal module la santé** (`[health].morning_check`) : en
   `minimal`, seul `readiness_score` est attendu ; en `off`, n'écrivez **pas**
   de fichier `medical/YYYY-MM-DD_health.md` pour un bilan — son absence n'est
   pas un manque. Recopiez le mode en vigueur dans `morning_check`.
6. **Le verdict ne dépend pas du style.** `verdict` (`green` / `amber` / `red`)
   est la décision de disponibilité du jour ; `[coaching].style` change la
   façon de la dire, jamais la valeur. Un verdict s'accompagne toujours de
   `verdict_reason` (une phrase).
7. **Noms de métriques génériques.** Ni clé ni texte ne reprend les sigles
   déposés ou revendiqués par TrainingPeaks — marques : TSS, NP, IF, rTSS, hrTSS, NGP, CTL, ATL, TSB.
   Écrivez *charge* (TRIMP), *condition*, *fatigue*, *forme*. Équivalences
   dans `docs/marques.md`.

## Valider après chaque écriture

```bash
python3 scripts/arc_index.py --validate medical/2026-09-20_health.md
```

Code 0 et `ok` : conforme. `NON CONFORME` : corrigez les erreurs listées (elles
nomment la clé) et revalidez. Les lignes `attention` (clé inconnue, type
inattendu pour le dossier) se corrigent aussi.

## Les types

| `kind` | Fichier | Écrit par |
|---|---|---|
| `activity` | `activities/YYYY-MM-DD_<type>.md` | coach (sync Garmin) |
| `health` | `medical/YYYY-MM-DD_health.md` | coach (sync), medical |
| `weather` | `medical/YYYY-MM-DD_meteo.md` | coach (skill `weather-forecast`) |
| `week` | `planning/Semaine_YYYY-MM-DD.md` (lundi de la semaine, ou de la première semaine — plan multi-semaines, #69) | coach |
| `nutrition` | `nutrition/YYYY-MM-DD_nutrition.md` | nutritionist |
| `report` | `rapports/YYYY-MM-DD_rapport.md`, `rapports/YYYY-MM-DD_comparaison_<lieu>.md`, `rapports/YYYY-MM-DD_debrief_<course>.md` | coach |
| `course_eval` | `planning/YYYY-MM-DD_evaluation_parcours_<lieu>.md` | skill `gpx-analysis` |
| `race_plan` | plan de course dans `planning/` | course-strategist |
| `decision` | `planning/YYYY-MM-DD_decision_<slug>.md` | coach, medical (garde-fous, bilan matinal, blessure) |
| `gear_inspection` | `gear/YYYY-MM-DD_<gear_id>_inspection.md` (photos dans `gear/photos/`) | coach (skill `gear-inspection`) |

`planning/Runner_Profile.md` et `planning/active_objective.md` **n'ont pas de
bloc** : l'athlète les édite à la main. Remplissez leurs puces
`- **Libellé** : valeur` sans changer les libellés du modèle — c'est ce qui les
rend lisibles par la machine.

Types de valeurs ci-dessous : *entier*, *nombre* (≥ 0 sauf mention), *texte*,
*date* `AAAA-MM-JJ`, *date-heure* ISO 8601 avec fuseau, *booléen*, *objet*,
*liste*. En **gras** : obligatoire.

### `activity`

| Clé | Type | Notes |
|---|---|---|
| **`date`** | date | jour de la séance (celui du nom de fichier) |
| **`sport`** | `running` `trail` `strength` `indoor_cycling` `home_trainer` `hiking` `walking` `elliptical` `rest` `cycling` `swimming` `rowing` | = le `<type>` du nom de fichier |
| **`duration_s`** | nombre | durée totale |
| `garmin_activity_id` | entier | identifiant Garmin — clé de jointure, à toujours renseigner après un sync `[data].source = "garmin"` |
| `intervals_activity_id` | texte | identifiant Intervals.icu (#68, ex. `"i12345678"`) — CHAÎNE, jamais confondue avec `garmin_activity_id` (entier). À renseigner à la place de `garmin_activity_id`, jamais en plus, après un sync `[data].source = "intervals"` |
| `strava_activity_id` | texte | identifiant Strava (#164) **préfixé `s`**, ex. `"s12345678901"` — l'API Strava rend un entier sans préfixe, indiscernable d'un `garmin_activity_id` ; le préfixe est la convention du projet (jamais le nombre seul : la validation le refuse). À renseigner à la place de `garmin_activity_id`, jamais en plus, après un sync `[data].source = "strava"` |
| `name` | texte | nom de l'activité (Garmin, Intervals.icu ou Strava selon la source) |
| `location` | texte | lieu / parcours (sert à la comparaison de parcours) |
| `start_time` | date-heure | |
| `distance_m` | nombre | |
| `moving_duration_s` | nombre | ≤ `duration_s` |
| `elevation_gain_m`, `elevation_loss_m` | nombre | D+ / D- |
| `avg_hr_bpm`, `max_hr_bpm` | 20-250 | |
| `recovery_hr_bpm` | entier | HRR à 2 min ; absent = non mesuré, pas un signal |
| `avg_cadence_spm` | nombre | |
| `calories_kcal` | nombre | |
| `calories_bmr_kcal` | nombre | part métabolisme de base — copie déclarative du champ `bmr_calories` de `get_activity` (Garmin), jamais recalculée ; voir `skills/garmin-sync-efficiency/SKILL.md`. Ne peut dépasser `calories_kcal` quand les deux sont connues. Sert à un NET Garmin (`calories_kcal − calories_bmr_kcal`), comparable au NET rendu par `scripts/arc_index.py energy` — celui-là recalcule sa PROPRE dépense depuis les échantillons FIT, indépendamment de cette clé |
| `training_effect_aerobic`, `training_effect_anaerobic` | nombre | 0-5 |
| `rpe` | 0-10 | effort perçu déclaré — indispensable si la séance n'a pas de FC |
| `splits_cols` | liste | en-tête des splits, voir ci-dessous |
| `splits` | liste | une ligne par km, dans l'ordre de `splits_cols` |
| `gear_id` | texte | identifiant matériel (slug), voir ci-dessous |
| `gear_source` | `garmin` \| `chat` \| `garmin_unmapped` | (#133) provenance du `gear_id` : matériel attaché par la montre (`get_activity_gear`, rattaché à la puce par son segment `garmin:`) ou déclaré par l'athlète en chat. `garmin` et `chat` exigent un `gear_id` ; `garmin_unmapped` l'EXCLUT : la montre a attaché un matériel sans puce correspondante (non associé, ambigu ou `(ignorée)`) — la séance n'est alors jamais créditée à la paire `(par défaut)` ; jamais `default` — sans `gear_id`, la paire `(par défaut)` est calculée à la lecture, pas écrite. Clé omise = provenance inconnue (séances antérieures à #133) |
| `carbs_g` | nombre | glucides ingérés pendant l'effort, 0-1000 g |
| `fluid_intake_ml` | nombre | liquide ingéré pendant l'effort, 0-10 000 ml |
| `weight_pre_kg`, `weight_post_kg` | nombre | pesée avant / après effort, 30-200 kg |
| `gear_ids` | liste de textes | matériel hors chaussures porté sur la séance (slugs, mêmes règles que `gear_id`, 30 max, sans doublon) — voir « Matériel hors chaussures » ci-dessous |
| `garmin_pushed` | liste d'objets | apport `/log` poussé vers Garmin Connect après un « oui » (#167, opt-in `[nutrition].garmin_sync`) — mêmes entrées que `nutrition.garmin_pushed` (section `nutrition`) ; sert l'idempotence, jamais écrite en headless |
| `missing_reason` | objet | clé absente → cause |
| `gap_pace_s_km` | nombre | GAP global de la séance, s/km — voir « Champs KPI FIT » |
| `decoupling_pct` | nombre (signe libre) | découplage aérobie Pa:HR, % — voir « Champs KPI FIT » |
| `ef_whole` | nombre | facteur d'efficacité séance entière — voir « Champs KPI FIT » |
| `time_in_zone_s` | objet | temps en zone FC, secondes, clés `z1`…`z5` — voir « Champs KPI FIT » |
| `best_climb_vam_m_h` | nombre | meilleure VAM observée sur une montée de la séance, m/h — voir « Champs KPI FIT » |
| `avg_ground_contact_s`, `avg_vertical_oscillation_m`, `avg_step_length_m` | nombre | dynamique de course Garmin (#151), moyennes de séance en secondes / mètres — voir « Dynamique de course » |
| `avg_stance_balance_pct`, `avg_vertical_ratio_pct` | nombre (0-100 exclus) | balance du temps de contact et ratio vertical, % — voir « Dynamique de course » |

**Matériel, sudation, glucides.** `gear_id` référence la section « Matériel &
lieux » du profil athlète (`planning/Runner_Profile.md`) : un identifiant
stable au format **slug** — minuscules, chiffres, tirets simples, 40
caractères maximum (ex. `hoka-speedgoat-5-bleue`). Deux séances avec le même
`gear_id` sont la même paire de chaussures pour le kilométrage cumulé.

Cette section du profil reste du texte libre écrit par l'athlète (un modèle,
une date d'achat, éventuellement un identifiant explicite qu'il choisit
lui-même) : `arc_contract.gear_slug(label)` est la règle PARTAGÉE qui dérive un
slug d'un libellé quand aucun identifiant explicite n'est donné — décomposition
Unicode et suppression des accents, minuscules, tout ce qui n'est pas
alphanumérique devient un tiret, tirets de tête/fin retirés, coupé à 40
caractères. Le coach applique la même règle sur le nom de modèle cité par
l'athlète pour choisir le `gear_id` d'une activité — et **omet** la clé plutôt
que de deviner si la référence est trop ambiguë (plusieurs paires possibles,
modèle non reconnu).

**Kilométrage chaussures et alerte d'usure (#40).** La sous-section `### Chaussures`
sous `## Matériel & lieux` du profil (voir `templates/Runner_Profile.template.md`)
déclare les chaussures de l'athlète, une puce par paire, en langage libre —
seul le nom est obligatoire :

```markdown
### Chaussures

- Hoka Speedgoat 5 (bleues) — depuis 2026-03-01 — alerte 700 km — id: speedgoat-bleues (par défaut)
- Adidas Adizero SL — alerte 500 km
- Nike Pegasus — départ 300 km (retirée)
- Salomon S/Lab Ultra — usage: course — départ 20 km
```

Une puce de **premier niveau** par paire — une puce indentée en dessous n'est
jamais une chaussure à part, elle est repliée dans les segments de la
chaussure précédente. Segments séparés par un tiret cadratin/demi-cadratin
(`—`/`–`, espaces autour optionnels), par un simple tiret **entouré
d'espaces** (` - ` : un nom de modèle peut légitimement contenir un trait
d'union SANS espaces, ex. « Salomon S/Lab Ultra-Trail », qui reste intact),
ou par un deux-points suivi d'un mot-clé reconnu : `depuis AAAA-MM-JJ` (ou
« mars 2026 »/« 03/2026 », 1er du mois — date d'achat), `alerte N km` (ou
`N miles`/`N mi`, convertis), `départ N km` (ou `N mi`, converti — #132 : kilométrage
déjà parcouru AVANT le suivi, voir plus bas), `usage: <texte libre>` (#132,
facultatif : `course`, `trail`, `route`, `récup`… — rôle de la paire, lu par le
coach pour suggérer une paire, jamais par un KPI), `id: <texte>` (identifiant explicite, passé par
`gear_slug` comme n'importe quel `gear_id`), `garmin: <uuid>` (#133, facultatif :
identifiant du matériel côté Garmin Connect, recopié de `get_gear` → `uuid`, jeton
alphanumérique/tirets de 8 à 64 caractères, comparé sans casse ; sert à rattacher le
matériel attaché par la montre à une activité à CETTE puce — jamais deviné, voir
« Priorité d'attribution » ci-dessous). `(par défaut)`, `(retirée)` et
`(ignorée)` (#133, matériel Garmin non suivi) peuvent être accolés n'importe où sur la ligne. `arc_legacy.parse_gear` lit
cette sous-section ; `scripts/arc_index.py` l'indexe dans la table dérivée
`gear` (une ligne par chaussure) ; `arc_metrics.gear_mileage` calcule le
kilométrage cumulé — voir `arc_metrics.ASSUMPTIONS["gear_mileage"]` pour la
méthode complète. En résumé :

- Kilométrage = somme de `distance_m` des activités de sport course/randonnée
  (`arc_metrics.GEAR_WEAR_SPORTS` : course, trail, randonnée — PAS la marche)
  portant ce `gear_id` — vélo, natation, renforcement… n'usent jamais une
  paire de chaussures de course, même avec un `gear_id` renseigné par erreur.
- Séance sans `gear_id` → attribuée à la chaussure `(par défaut)` si une seule
  est déclarée, sinon **ignorée** (ni comptée, ni signalée).
- `gear_id` explicite absent du profil (faute de frappe, paire jamais
  déclarée) → jamais éliminé silencieusement, regroupé à part (« inconnue »
  côté tableau de bord) avec son propre kilométrage.
- `depuis` filtre **seulement** l'attribution PAR DÉFAUT : une séance sans
  `gear_id` datée avant le `depuis` de la chaussure `(par défaut)` n'y est pas
  rattachée (sinon tout un historique d'avant #39, sans `gear_id` au contrat,
  se retrouverait crédité à une paire achetée hier). Une séance portant un
  `gear_id` EXPLICITE compte quel que soit son rapport à `depuis` : l'explicite
  prime toujours sur une date de début possiblement approximative.
- Seuil d'alerte : celui de la puce si renseigné, sinon
  `arc_metrics.GEAR_ALERT_THRESHOLD_M_DEFAULT` (700 km).
- `(retirée)` : kilométrage toujours affiché (historique), jamais d'alerte,
  jamais candidate à l'attribution par défaut (priorité retraite avant
  défaut, même si `(par défaut)` est aussi coché sur la même puce).
- `départ N km` (#132) : ajouté au cumul (`start_m` dans la table `gear`,
  `distance_m` de `gear_mileage` = activités + départ), donc compté dans le
  seuil d'alerte, la prévision et `near_threshold` ; conservé pour une paire
  `(retirée)`. Seule la forme `[~]N [km|mi]` est lue (« départ usine 2025 » ou une
  valeur négative restent du texte libre ignoré) ; point et virgule sont toujours
  décimaux (`1.200 km` = 1,2 km), l'espace sépare les milliers ; l'unité peut être
  collée (`186mi`) ;
  `départ 0 km` est valide. Le corriger par chat (« mes Pegasus ont en fait ~300
  km ») = réécrire ce SEUL segment de la puce (départ = total déclaré − km déjà
  comptés par les activités, plancher 0), jamais les activités passées.
- Priorité d'attribution (#133) : déclaration de l'athlète (`gear_id` cité en chat) >
  matériel attaché par Garmin à l'activité (`get_activity_gear`, puce reconnue par
  `garmin: <uuid>`) > paire `(par défaut)`. Résolue par `python3 scripts/arc_index.py
  gear-attribution --garmin-gear UUID[,UUID…] [--chat-gear GEAR_ID]`
  (`arc_metrics.resolve_gear_attribution`) qui rend `{gear_id, gear_source,
  conflict, unmapped_garmin, ignored_garmin, ambiguous}` — le coach écrit
  `gear_id` et `gear_source` tels quels, sans refaire la règle. Conflit (Garmin dit A,
  l'athlète dit B) : l'athlète gagne (`gear_source: "chat"`), `conflict` est
  signalé une fois. Uuid Garmin sans puce, ambigu ou `(ignorée)` : `gear_id` omis et
  `gear_source: "garmin_unmapped"` — jamais attribué en silence, et jamais crédité à la paire
  `(par défaut)` (`arc_metrics.gear_mileage`, y compris `--activities`/`crossed_in_run`). Le
  segment `(ignorée)` (puce `- <nom Garmin> — garmin: <uuid> (ignorée)`) fait taire les
  propositions et alertes pour ce matériel ; ces puces ne sont pas des chaussures suivies
  (colonne `gear.ignored`). Déclaration en chat sur une séance DÉJÀ synchronisée : le côté Garmin
  est son `gear_id` stocké quand `gear_source` vaut `garmin` (passer l'uuid de cette puce à
  `--garmin-gear`, sans nouvel appel Garmin) ; `chat-gear` est normalisé (id du profil, nom, ou slug
  valide au contrat) et toute valeur `--garmin-gear` qui n'a pas la forme d'un uuid est ignorée.
  Seule la paire `(par défaut)` reste calculée à la lecture.
- Prévision de retraite (#132) : `arc_index.py gear` (et `/api/summary.gear`)
  ajoute par paire non retirée et sous son seuil, si elle a roulé dans les 28
  derniers jours (borne `--today`, sinon aujourd'hui) : `recent_28d_m`,
  `retire_forecast_weeks` (semaines, 0,1 près) et `retire_forecast_date`
  (toujours future). Clés OMISES sans usage sur 28 jours, pour une paire retirée
  ou déjà au seuil (`alert` : « seuil dépassé »). `near_threshold: true` dès 90 %
  du seuil. `arc_index.py gear --activities ID[,ID…]` (garmin_activity_id,
  intervals_activity_id, strava_activity_id ou chemin du fichier des séances synchronisées dans CE run) ajoute
  `crossed_in_run: true` à la paire dont elles font franchir le seuil — base de
  l'alerte unique du `garmin-daily-sync` (par séance, pas par date : un second
  passage le même jour ne ré-émet rien), sans fichier d'état. Avec `--today`
  dans le passé, le cumul ignore les séances postérieures. Méthode et limites :
  `arc_metrics.ASSUMPTIONS["gear_mileage"]`.
- Deux puces qui dérivent le même `gear_id` (même modèle racheté sans `id:`
  pour les distinguer) : la première garde le slug nu, les suivantes reçoivent
  `-2`, `-3`… et une collision signalée dans `gear_mileage().warnings` — pour
  l'éviter, donnez un `id:` explicite à chaque paire du même modèle.

**Matériel hors chaussures (#134).** La sous-section `### Matériel` (sous `## Matériel &
lieux`, à côté de `### Chaussures`, qu'elle ne modifie en rien) déclare bâtons, gilet,
poche à eau, flasques, frontale, ceinture cardio, veste, semelles, lacets… Une puce de
premier niveau par objet, langage libre, mêmes séparateurs que les chaussures :

```markdown
### Matériel

- Poche à eau 2 L — catégorie: poche — depuis 2026-03-01 — alerte 30 jours — kit: trail-long
- Frontale Petzl — catégorie: frontale — alerte 100 h — id: frontale-nuit — kit: nuit
- Bâtons Leki — catégorie: bâtons — alerte 800 km — kit: trail-long
- Veste imperméable — catégorie: veste — alerte 40 h ou 180 jours — entretien 2026-05-10
```

Segments, tous facultatifs sauf le nom : `depuis <date>`, `catégorie: <mot>`, `alerte <déclencheurs>`,
`départ <N km|N h|N séances>`, `entretien <date>` (ou `révisé <date>`), `kit: <slug>[, <slug>…]`,
`id: <texte>`, `(retirée)`. La **catégorie** n'est lue que du segment `catégorie:` — jamais
devinée du nom — parmi `bâtons`, `gilet`, `poche`, `flasques`, `frontale`, `ceinture`, `veste`,
`semelles`, `lacets`, `autre` (accents, singulier/pluriel et quelques synonymes acceptés,
`arc_legacy.EQUIPMENT_CATEGORIES`) ; une autre valeur est gardée telle quelle : objet indexé, aucune
alerte inventée.

- **Déclencheurs typés** (`alerte`) : `N km` (ou `N mi`), `N h` (ou `NhMM` : `1h30`), `N séances`,
  `N jours`, `N semaines`, `N mois`, `N ans`, combinables dans un segment (`alerte 30 jours ou 40 h`) ou en
  plusieurs segments — le premier atteint (valeur ≥ seuil) déclenche. Les durées calendaires sont
  converties en jours : 1 semaine = 7 j, 1 mois = 30 j, 1 an = 365 j (approximation du projet). Seule une
  unité explicite compte : un nombre nu (`alerte 800`) n'est jamais interprété (aucun type deviné) et un
  segment `alerte`/`départ` dont rien n'est lisible produit un **avertissement** (index, `equipment`,
  tableau de bord), jamais un silence. Il n'existe aucun seuil par défaut pour le matériel.
- **Jours** : comptés depuis la date de référence = `entretien`/`révisé` le plus récent, sinon `depuis`.
  Sans aucune des deux, un déclencheur en jours ne peut pas jouer (avertissement, jamais 0). **Remise à
  zéro après entretien** : quand l'athlète dit « j'ai nettoyé la poche » ou « j'ai réimperméabilisé la
  veste », le coach réécrit ou ajoute le segment `entretien <date>` sur la puce (jamais le reste de la puce) avec
  **la date de la dernière séance faite AVANT l'entretien** (cherchée dans `activities/`, à défaut la
  veille de l'entretien). Règle de comptage : les séances datées jusqu'à cette date incluse sont
  exclues, celles datées **strictement après** comptent — une séance faite après l'entretien le même
  jour reste ainsi comptée. Conséquence assumée (approximation du projet) : la date de référence des
  jours peut précéder l'entretien réel de quelques jours, l'alerte arrive plutôt plus tôt que trop tard.
  Le `départ` est alors ignoré ; les cumuls à vie restent visibles (`lifetime`).
- **Heures** = somme de `duration_s` des séances comptées (durée totale, pas le temps en mouvement).
- **Attribution explicite uniquement** : une séance compte pour un objet si son `gear_ids` le cite ;
  aucun objet par défaut (une ceinture cardio portée à chaque séance se met dans un kit).
  Compatibilité : `gear_id` reste LA chaussure (inchangé, un seul slug) ; `gear_ids` est facultatif —
  toute activité écrite avant #134 reste valide et compte pour aucun objet. **Déclarer un kit ou des
  objets n'écrit, ne modifie et ne supprime JAMAIS `gear_id` ni `gear_source`** (#133 : chaussure et
  provenance Garmin/chat) ; un slug de chaussure dans `gear_ids` est ignoré avec un avertissement.
  **Matériel Garmin hors chaussures** : `### Matériel` n'a ni segment `garmin:` ni `(ignorée)` — le
  rattachement du matériel Garmin non-chaussure n'est pas pris en charge (hors périmètre de #134) ; un
  `(ignorée)` écrit sur une puce de `### Matériel` est retiré (avertissement), jamais laissé dans l'id.
- **Sports par catégorie** (`arc_metrics.EQUIPMENT_CATEGORY_SPORTS`, approximation du projet) : bâtons =
  trail/randonnée/marche (marche nordique) ; gilet, poche, flasques, veste = course/trail/randonnée/marche ;
  semelles, lacets = course/trail/randonnée ; frontale,
  ceinture, autre = tout sport. Catégorie inconnue ou absente : compté sur toute séance qui cite l'objet,
  aucune alerte hors de ses déclencheurs déclarés.
- **Kits** : `kit: trail-long` sur les objets qui le composent. Quand l'athlète dit « kit trail long » pour
  une séance, le coach exécute `python3 scripts/arc_index.py equipment --kit trail-long --sport <sport>`
  et écrit la liste `gear_ids` rendue (objets non retirés dont la catégorie porte le sport ; les autres
  sont listés dans `skipped` avec leur raison, à dire à l'athlète) — jamais un objet de son cru. Kit
  inconnu (`known: false`) : le dire, ne rien écrire.
- **Lecture** : `arc_index.py equipment` (et `/api/summary.equipment`) rend, par objet, `usage`
  (`distance_m`, `duration_s`, `sessions`, `days`), `lifetime`, `triggers` (valeur, seuil, `reached`),
  `alert`, `near_threshold` (≥ 90 %), `pre_session_check` (frontale : batterie avant une séance de nuit ;
  poche/flasques : hygiène avant une sortie longue), plus `kits`, `unknown` (`gear_ids` cité mais absent du
  profil) et `warnings`. `arc_index.py gear` (chaussures) est inchangé. **Alerte une seule fois, sans
  fichier d'état** : `equipment --activities ID[,ID…] [--last-pass AAAA-MM-JJ]` ajoute `crossed_in_run` (par
  objet et par déclencheur) — km/h/séances : le cumul hors les séances désignées était sous le seuil ;
  jours : seuil franchi entre `--last-pass` (jour du dernier passage, **exclu** — à l'inverse de `--since`
  de `energy`, inclus) et aujourd'hui ; sans `--last-pass`, un déclencheur en jours ne marque jamais de
  franchissement. Le `garmin-daily-sync` n'émet donc aucune alerte en jours (pas d'horodatage fiable du
  dernier passage réussi).
- **Contrôle du matériel de course** : `equipment --race-plan [FICHIER]` croise le `gear` d'un plan de
  course avec l'inventaire : `missing` (non retrouvé), `category_match` (« à vérifier : spécification » —
  seul le nom commun de tête de la ligne rejoint la catégorie d'un objet, jamais `ok` : une ceinture
  porte-dossard n'est pas une ceinture cardio), `never_used` (aucune séance ne cite l'objet), `alert`, `ok`
  (nom ou identifiant de l'objet trouvé dans la ligne). Rapprochement textuel strict par mots entiers,
  accents et ponctuation ignorés, jamais flou ; le chemin passé à `--race-plan` peut être absolu, `./…` ou
  relatif au workspace. `--sport` de `--kit` est normalisé (casse) et validé (sport inconnu : erreur).
- Méthode et limites : `arc_metrics.ASSUMPTIONS["equipment_usage"]`.

**Indices de performance ITRA/UTMB (#62).** La section `## Indices de
performance (ITRA / UTMB)` du profil (voir `templates/
Runner_Profile.template.md`) déclare des relevés datés, un par puce de
premier niveau, en langage libre — même principe que `### Chaussures`
ci-dessus. Les puces peuvent vivre directement sous ce titre, ou sous sa
propre sous-section `### Historique des indices` (les deux sont lues pareil —
un profil installé avant l'ajout de cette sous-section, ou un athlète qui
colle simplement ses relevés sous le titre principal, n'a rien à changer). Le
titre lui-même est reconnu même renommé/simplifié SANS mention ITRA/UTMB (ex.
« ## Indices de performance » nu, ou suivi d'une seule parenthèse comme
« (facultatif) ») — accepté quand même, avec un avertissement (revue de code
#109, 3e tour) plutôt que de perdre la section en silence ; un titre qui
continue en texte libre SANS parenthèses (ex. « Indice de performance VO2 »,
la vue Performance du tableau de bord) reste, lui, exclu.

```markdown
## Indices de performance (ITRA / UTMB)

### Historique des indices

- 2025-11-01 — itra : 610
- 2025-11-01 — itra L : 600
- 2026-02-15 — utmb 100k : 560
- 2026-03-01 — utmb Général : 580
```

Format d'une puce : `AAAA-MM-JJ — itra|utmb [catégorie] : valeur`. La
catégorie est facultative (indice général si omise, ainsi que pour tout
synonyme de « général » — `général`/`general`/`global`/`index`, accents et
casse ignorés, ex. « UTMB Index ») ; pour l'UTMB, seules `20k`/`50k`/`100k`/
`100m` sont reconnues (nomenclature vérifiée, unité collée ou espacée —
« 100k » et « 100 k » sont équivalents), toute autre valeur — comme une valeur
hors de la plage `]0, 1000]`, une date illisible, ou une ligne qui ne respecte
pas ce format — est **ignorée avec un avertissement**, jamais silencieusement
ni acceptée telle quelle ; un doublon EXACT (même date/type/catégorie) garde
la DERNIÈRE ligne du fichier, avec un avertissement sur les précédentes. La
nomenclature des catégories ITRA (ex. `L`, `M`) n'a **pas** pu être vérifiée
depuis cet environnement : la catégorie ITRA reste donc du texte libre (y
compris multi-mots), non validée contre une liste fermée. `arc_legacy.
parse_performance_index` lit cette section ; `scripts/arc_index.py` l'indexe
dans la table dérivée `performance_index` (une ligne par relevé, plus
`performance_index_warning` pour les avertissements de lecture) ;
`arc_index.performance_index` (CLI `performance-index`, JSON) rend `history`
(tous les relevés, triés par date puis par ordre d'apparition dans le
fichier), `current` (le relevé le plus RÉCENT pour chaque couple
type/catégorie — c'est la seule notion de « valeur actuelle », il n'y a pas de
champ dupliqué ailleurs dans le profil) et `warnings` (les avertissements
persistés, PLUS un avertissement de date future recalculé à CHAQUE appel
contre le jour courant — jamais stocké, pour ne jamais rester périmé si le
fichier ne change pas alors que la date, elle, a fini par passer).

**Vie privée (critère d'acceptation #62) : aucune récupération automatique.**
Ces valeurs ne viennent QUE de ce que l'athlète a écrit lui-même. Aucun script
de ce dépôt ne fait de requête vers `itra.run`/`utmb.world` (verrouillé par un
test de palier B dédié), et un agent ne peut les chercher sur le web que sur
demande EXPLICITE de l'athlète — voir le mandat de vie privée d'`agents/
coach.md` (« PERFORMANCE INDEX MANDATE »).

`carbs_g` et `fluid_intake_ml` viennent d'une déclaration de l'athlète (gels,
barres, boisson…) pendant ou juste après la séance — jamais une valeur
inventée : sans déclaration, la clé est omise. Convertissez un produit du
catalogue (`resources/nutrition/catalogue-produits-*.md`, voir `nutritionist`)
en grammes/millilitres avant d'écrire le bloc.

`weight_pre_kg`/`weight_post_kg` sont les pesées avant et après l'effort
(protocole classique de mesure du taux de sudation). `weight_post_kg`
supérieur à `weight_pre_kg` de plus de 1 kg déclenche un avertissement (pesée à
vérifier), pas une erreur — la balance ou les vêtements peuvent expliquer un
petit écart. Le taux de sudation lui-même (`sweat_rate_l_h`) n'est **pas**
écrit par l'agent : c'est un champ **dérivé**, voir « Champ dérivé »
juste après l'exemple ci-dessous.

**Splits.** `splits_cols` déclare les colonnes, `splits` donne une liste de
valeurs par km dans cet ordre. `km` et `duration_s` sont obligatoires ; les
autres sont facultatives : `distance_m` (dernier split partiel),
`elev_gain_m`, `elev_loss_m`, `avg_hr_bpm`, `max_hr_bpm`, `max_speed_kmh`,
`cadence_spm`, `label` (lecture courte : « Échauffement », « Montée »).

```arc
{
  "arc": 1, "kind": "activity", "date": "2026-09-20", "sport": "trail",
  "garmin_activity_id": 20174839201, "name": "Tournai Trail", "location": "Tournai",
  "start_time": "2026-09-20T12:05:00+02:00",
  "distance_m": 12300, "duration_s": 5218, "moving_duration_s": 5100,
  "elevation_gain_m": 480, "elevation_loss_m": 476,
  "avg_hr_bpm": 148, "max_hr_bpm": 171, "recovery_hr_bpm": 28, "avg_cadence_spm": 168,
  "calories_kcal": 912, "calories_bmr_kcal": 95, "training_effect_aerobic": 3.8, "training_effect_anaerobic": 1.2, "rpe": 6,
  "splits_cols": ["km", "duration_s", "elev_gain_m", "elev_loss_m", "avg_hr_bpm", "max_speed_kmh", "cadence_spm", "label"],
  "splits": [[1, 358, 3, 36, 120, 11.2, 166, "Échauffement"], [2, 372, 41, 2, 139, 10.4, 164, "Montée"]]
}
```

Séance sans FC (renforcement) : pas de `avg_hr_bpm`, mais un `rpe` — c'est lui
qui porte la charge.

```arc
{"arc": 1, "kind": "activity", "date": "2026-09-18", "sport": "strength", "duration_s": 2400, "rpe": 6, "missing_reason": {"avg_hr_bpm": "pas de ceinture cardio"}}
```

Sortie longue avec matériel, ravitaillement déclaré et pesées avant/après
(entraînement digestif, #41 en tirera glucides/h et taux de sudation) :

```arc
{
  "arc": 1, "kind": "activity", "date": "2026-09-21", "sport": "trail", "duration_s": 9000,
  "moving_duration_s": 8820, "distance_m": 22000, "avg_hr_bpm": 138,
  "gear_id": "hoka-speedgoat-5-bleue", "carbs_g": 72, "fluid_intake_ml": 900,
  "weight_pre_kg": 70.2, "weight_post_kg": 69.1
}
```

Ici, `scripts/arc_index.py` dérive `sweat_rate_l_h` à l'indexation : ni cette
clé ni sa formule ne s'écrivent dans le bloc — voir juste en dessous.

#### Champ dérivé : `sweat_rate_l_h`

Ne s'écrit **jamais** dans un bloc ```arc — c'est `scripts/arc_index.py`
(fonction `arc_metrics.sweat_rate_l_h`) qui le calcule à l'indexation, à partir
des seules clés `activity` ci-dessus, et l'expose dans la table dérivée
(`activity.sweat_rate_l_h`), pour un futur suivi glucides/h et taux de
sudation.

Formule : `((weight_pre_kg − weight_post_kg) + fluid_intake_ml / 1000) / durée_h`,
avec :

- **durée** = `duration_s` (durée TOTALE de la sortie), **jamais**
  `moving_duration_s` : la pesée encadre la sortie entière (avant le départ,
  après le retour), et la transpiration comme l'ingestion continuent pendant
  les arrêts (ravitaillement, photo, pause à un point d'eau) — utiliser la
  seule durée de mouvement sous-estimerait le temps réel d'exposition ;
- **sous 45 minutes**, `null` : l'imprécision d'une pesée maison (résolution
  de la balance, habits, passage aux toilettes) domine le signal sur une
  sortie courte ;
- calculé **seulement** si `weight_pre_kg` **et** `weight_post_kg` **et**
  `duration_s` (≥ 45 min) sont tous présents — sinon `null`, jamais une valeur
  devinée ;
- `fluid_intake_ml` absent → traité comme `0` dans le calcul : le taux devient
  alors une **borne basse** (l'athlète a pu boire sans le déclarer) ;
- ce chiffre reste une **approximation dans les deux sens**, jamais une
  mesure : la perte urinaire (non soustraite) et la perte d'eau
  respiratoire/métabolique (comptée à tort comme de la sueur) le
  **surestiment** ; la masse des aliments solides ingérés (non retranchée du
  poids « après ») le **sous-estime** légèrement ;
- résultat négatif — dès que `(weight_pre_kg − weight_post_kg) + fluid_intake_ml / 1000 < 0`,
  y compris sans franchir l'avertissement ci-dessus (ex. 70 → 70,5 kg sans
  liquide déclaré) — ou hors plage plausible (0-4 l/h) → `null`, pas une
  valeur aberrante affichée.

Détails et justification complète : `arc_metrics.ASSUMPTIONS["sweat_rate"]`.

#### Champ dérivé : `carbs_per_hour_g` (#41, entraînement digestif)

Comme `sweat_rate_l_h` ci-dessus, ne s'écrit **jamais** dans un bloc ```arc.
`carbs_per_hour_g` (fonction `arc_metrics.carbs_per_hour_g`) = `carbs_g` / durée en
heures (`duration_s`, la même durée totale que `sweat_rate_l_h`), calculé
**seulement** pour les sorties **longues** (`duration_s` **strictement** supérieure
à 90 min, `arc_metrics.LONG_RUN_MIN_DURATION_S`) et **seulement** si `carbs_g` est
renseigné — sinon `null`, jamais 0 par défaut (un `carbs_g` explicitement à `0` reste
un 0 g/h légitime, une absence de déclaration n'en est pas un).

`python3 scripts/arc_index.py fueling` agrège les sorties longues **running/trail
seulement** (`arc_metrics.FUELING_SPORTS` — ni la randonnée, ni le vélo : allure/FC/
digestion trop différentes d'un effort de course pour plafonner sa cible glucides/h)
des 12 dernières semaines glissantes (`FUELING_TREND_WEEKS`) : `long_runs` (nombre
total), le meilleur débit observé (`max_carbs_per_hour_g`, avec son effectif
`carbs_per_hour_n` — **moins de 3**, le plafond repose sur trop peu de données pour
être présenté comme fiable, à signaler et confirmer à la prochaine sortie longue),
la médiane du taux de sudation sur la même fenêtre (`median_sweat_rate_l_h`,
`sweat_rate_n`), et `carbs_ceiling_g_h` (entier) — le meilleur débit observé + une
marge de progression documentée (`FUELING_MAX_MARGIN_G_H`, 10 g/h), plafonné à son
tour au haut du repère généraliste (90 g/h) sauf si l'athlète l'a déjà personnellement
dépassé — plafond réaliste proposé à `course-strategist` pour un plan de course.
`null` sans aucune sortie longue chiffrée : le repère générique reste 60-90 g/h
(`FUELING_TARGET_BAND_G_H`). Le
workspace n'a **aucun** champ de trouble digestif déclaré : « toléré » veut
seulement dire « ingéré sans incident signalé ailleurs », jamais une mesure de
tolérance — à confirmer par l'athlète avant d'en faire un plafond dur. Détails :
`arc_metrics.ASSUMPTIONS["fueling"]`.

#### Champs KPI FIT : `gap_pace_s_km`, `decoupling_pct`, `ef_whole`, `time_in_zone_s`, `best_climb_vam_m_h` (#51, épopée #21)

Contrairement à `sweat_rate_l_h`/`carbs_per_hour_g` ci-dessus (jamais écrits
par l'agent), ces cinq clés **sont** écrites dans le bloc — mais **jamais
inventées ni recalculées à la main** : le coach les recopie de la sortie JSON
des CLI dédiées, après les avoir lues pour construire le retour de séance
(voir `agents/coach.md`, section KPI FIT). **Attention aux clés qui NE
reprennent PAS le nom du champ source telles quelles** (colonne « Champ de la
sortie JSON » ci-dessous) — ne devinez jamais le mapping à partir du seul nom
de la clé du bloc :

| Clé | Source (CLI) | Champ de la sortie JSON |
|---|---|---|
| `gap_pace_s_km` | `scripts/arc_index.py gap --activity ID` | `gap_pace_s_km` (même nom) |
| `decoupling_pct` | `scripts/arc_index.py decoupling --activity ID` | `decoupling_pct` (même nom) |
| `ef_whole` | `scripts/arc_index.py decoupling --activity ID` | `ef_whole` (même nom) |
| `time_in_zone_s` | `scripts/arc_index.py zones --activity ID` | `zone_seconds` — clés `"1"`…`"5"` dans la sortie, **renommées** `z1`…`z5` dans le bloc (jamais les buckets de polarisation `low`/`moderate`/`high`, un champ différent) |
| `best_climb_vam_m_h` | `scripts/arc_index.py vam --activity ID` | `best_climb_vam_elapsed_m_h` — la meilleure VAM d'UNE montée gravie pendant la séance, temps écoulé. **PAS** `best_vam_10min_m_h`/`best_vam_20min_m_h` : ce sont deux fenêtres glissantes indépendantes des montées détectées, un chiffre différent qu'il ne faut pas confondre avec celui-ci |

**Cette copie Markdown est un instantané narratif, jamais la source de
vérité.** `scripts/arc_index.py` calcule sa PROPRE version de ces mêmes
grandeurs à chaque passage (`index_workspace`), directement depuis les
échantillons FIT ingérés (`activities/fit/<garmin_activity_id | intervals_activity_id | strava_activity_id>.json`) — dans
les colonnes dérivées `activity.gap_pace_s_km`/`decoupling_pct`/`ef_whole`/
`best_climb_vam_elapsed_m_h` et la table `hr_zone_time`. **La valeur de
l'index fait TOUJOURS foi** pour le tableau de bord, `arc_index.py` et toute
requête SQL — jamais cette copie, qui peut dater d'avant un `--rebuild`, un
changement de profil (FC max/repos) ou une nouvelle ingestion FIT. N'écrivez
ces clés que si la CLI correspondante a rendu une valeur (jamais `reason`
non nul, ni `null` avec un `reason` vide) — sinon omettez la clé, exactement
comme une mesure absente.

Validation (`scripts/arc_contract.py`) : `time_in_zone_s` n'accepte que les
clés `z1`…`z5`, une clé inconnue est un avertissement, et une valeur négative
ou supérieure à `duration_s` de la même activité est une erreur (une seconde
en zone ne peut pas dépasser la durée totale de la séance). `decoupling_pct`
hors de -50 à 100 % déclenche un avertissement (à vérifier), pas un rejet :
une dérive négative franche ou un découplage élevé restent physiologiquement
possibles.

```arc
{
  "arc": 1, "kind": "activity", "date": "2026-09-24", "sport": "running", "duration_s": 4200,
  "moving_duration_s": 4200, "garmin_activity_id": 99000042, "distance_m": 11674, "avg_hr_bpm": 138,
  "gap_pace_s_km": 359.8, "decoupling_pct": 11.2, "ef_whole": 1.19,
  "time_in_zone_s": {"z1": 1470, "z2": 1470, "z3": 1260},
  "best_climb_vam_m_h": 620
}
```

#### Dynamique de course : `avg_ground_contact_s`, `avg_stance_balance_pct`, `avg_vertical_oscillation_m`, `avg_vertical_ratio_pct`, `avg_step_length_m` (#151)

Moyennes de séance de la **dynamique de course** mesurée par la montre Garmin
(champs FIT `avg_stance_time` ms, `avg_stance_time_balance` %, `avg_vertical_oscillation` mm,
`avg_vertical_ratio` %, `avg_step_length` mm), **en unités SI** : secondes et mètres (ms ÷ 1000,
mm ÷ 1000), pourcentages inchangés. Toutes optionnelles :

- **Clé absente = grandeur non mesurée.** Jamais `0`, et surtout jamais `50` pour une balance
  absente : un capteur qui ne fournit pas la balance (15 séances de course sur 80 sur l'installation
  observée) laisse la clé omise.
- **Aucun writer automatique** : ni le coach ni un script n'écrivent ces clés d'office ; elles servent de
  repli pour des valeurs saisies à la main ou héritées de fichiers anciens. `avg_stance_balance_pct` hors
  de 30-70 % → avertissement du validateur (et valeur ignorée par `gait-summary`).
- **Repli seulement.** Quand les échantillons FIT de la séance sont ingérés
  (`activities/fit/<id>.json`, colonnes `activity_sample.ground_contact_s`… — extraites par
  `download_fit.py`, re-extractibles avec `--refresh-dynamics`), `scripts/arc_index.py gait-summary`
  calcule sa PROPRE moyenne et c'est elle qui fait foi ; ces clés ne servent que sans échantillons.
  N'écrivez rien qui ne vienne pas du FIT/du MCP (jamais une valeur estimée).
- **La balance est un écart à 50 %.** Le côté que porte le pourcentage (gauche ou droite) n'est pas
  établi par le profil FIT : ne l'écrivez jamais dans la prose comme « pied gauche/droit ».
- Validation : `avg_stance_balance_pct` et `avg_vertical_ratio_pct` strictement entre 0 et 100 ; les
  autres sont des nombres positifs.

### `health`

| Clé | Type | Notes |
|---|---|---|
| **`date`** | date | |
| **`morning_check`** | `full` `minimal` `off` | mode en vigueur (`[health].morning_check`) |
| `sleep_total_s`, `sleep_deep_s`, `sleep_light_s`, `sleep_rem_s`, `sleep_awake_s` | nombre | |
| `sleep_score` | 0-100 | |
| `sleep_start`, `sleep_end` | date-heure | fenêtre enregistrée — à comparer à l'heure de coucher déclarée |
| `hrv_overnight_ms` | nombre | moyenne nocturne |
| `hrv_baseline_low_ms`, `hrv_baseline_high_ms` | nombre | bande de référence Garmin |
| `hrv_status` | `balanced` `unbalanced` `low` `poor` `no_status` | statut Garmin (moyenne 7 j) |
| `hrv_personal_low_ms`, `hrv_personal_high_ms` | nombre | bande de référence PERSONNELLE (#34) — moyenne 7 j de ln(HRV) vs référence 60 j ± 0,5 ET, calculée par `scripts/arc_index.py hrv-baseline`. À renseigner surtout quand `hrv_baseline_low_ms`/`high_ms` (Garmin) sont absents : c'est alors la seule bande disponible. |
| `hrv_personal_status` | `sous` `dans_la_norme` `au_dessus` `en_construction` | statut personnel rendu par cette même commande (`en_construction` : historique de référence encore trop court) |
| `resting_hr_bpm` | 20-250 | `get_rhr_day` |
| `readiness_score` | 0-100 | |
| `readiness_factors` | objet | facteurs Garmin, ex. `{"sleep": 62, "hrv": 80}` |
| `body_battery_high`, `body_battery_low` | 0-100 | |
| `stress_avg` | 0-100 | |
| `weight_kg` | nombre | poids du jour : pesée Garmin (`get_daily_weigh_ins`, #222) ou valeur déclarée par l'athlète — voir « Poids du jour » ci-dessous |
| `weight_origin` | `garmin` `chat` | provenance de `weight_kg` (#222) ; absente = fichier d'avant #222, lu comme déclaré |
| `weight_garmin_kg` | 30-200 | pesée Garmin ÉCARTÉE au profit de la valeur déclarée, écart > 1 kg (#222) — signalé une seule fois |
| `verdict` | `green` `amber` `red` | disponibilité du jour : maintenir / alléger / repos |
| `verdict_reason` | texte | obligatoire avec `verdict` |
| `missing_reason` | objet | |
| `pain` | liste d'objets | douleur STRUCTURÉE déclarée ce jour-là (#57) — voir ci-dessous |
| `cycle_phase` | `menstrual` `follicular` `ovulation` `luteal` | **opt-in** (#166) : phase du cycle du jour, voir « Contexte du cycle » ci-dessous |
| `cycle_day` | entier 1-60 | jour du cycle, si la source le donne |
| `cycle_source` | `garmin` `intervals` `manual` | d'où vient la phase (`manual` = déclarée par l'athlète via `/log`) |

**Douleur déclarée (`pain`, #57).** Une liste d'objets, un par zone douloureuse
signalée le jour du fichier (`health.date` fait foi comme date — pas de `date`
propre à chaque entrée) : **`location`** (texte libre, ex. « genou droit »),
**`score`** (0-10, sévérité perçue — même échelle que `activity.rpe`, mais un
champ distinct : de la douleur, jamais de l'effort). Lu par
`scripts/arc_guardrails.py injury-risk` (drapeau composite de risque de
blessure) pour repérer une douleur récente au-delà d'un seuil — voir
`arc_guardrails.ASSUMPTIONS_INJURY_RISK["pain"]`. Le texte libre sous le bloc
reste la SEULE description narrative (protocole, évolution) : ce champ est
volontairement minimal, jamais un remplacement du récit médical. Clé absente
= douleur non demandée/non renseignée ce jour-là ; `"pain": []` = douleur
explicitement demandée, aucune signalée — les deux se lisent comme « pas de
douleur » côté drapeau de risque de blessure (`observed: 0`), la distinction
n'existe que pour l'agent qui écrit le fichier. Plus de
`arc_contract.PAIN_MAX_ENTRIES` (10) entrées déclenche un avertissement
(doublon probable), jamais une erreur.

```arc
{"arc": 1, "kind": "health", "date": "2026-09-24", "morning_check": "full",
 "pain": [{"location": "genou droit", "score": 6}],
 "verdict": "amber", "verdict_reason": "Douleur au genou signalée : séance de qualité annulée par prudence."}
```

**Poids du jour (`weight_kg`, `weight_origin`, `weight_garmin_kg`, #222).** Avec
`[data].source = "garmin"`, la pesée est lue dans Garmin Connect
(`get_daily_weigh_ins(date)` ; rattrapage : un seul `get_weigh_ins(start, end)`) et la
réponse BRUTE passée à `python3 scripts/arc_weight_sync.py plan --garmin '<réponse>'
--date <date>` (ou sur l'entrée standard : `echo '<réponse>' | python3 scripts/arc_weight_sync.py
plan --date <date>`, la forme qu'accepte le chat ; ajouter `--existing-only` pour un rattrapage) : il dit quelles clés poser
(`set`), retirer (`remove`) et s'il faut signaler un écart (`flag`). Règles, jamais à
refaire à la main : la pesée la plus ancienne du jour est retenue ; un jour sans pesée
Garmin n'a PAS de `weight_kg` (jamais la valeur de la veille recopiée — la lecture prend
déjà la dernière pesée connue) ; une valeur déclarée par l'athlète le même jour
(`weight_origin: "chat"`, ou clé absente) prime toujours, la pesée Garmin écartée allant
dans `weight_garmin_kg` quand l'écart dépasse 1 kg (signalé une seule fois). Quand
l'athlète DÉCLARE son poids : `arc_weight_sync.py plan --date <date> --declared-kg <kg>`.
`weight_origin` exige `weight_kg` ; `weight_garmin_kg` est refusé avec
`weight_origin: "garmin"`. Ne concerne ni `weight_pre_kg` ni `weight_post_kg` (pesées
autour de l'effort, déclaratives).

```arc
{"arc": 1, "kind": "health", "date": "2026-09-25", "morning_check": "full",
 "weight_kg": 68.2, "weight_origin": "garmin"}
```

**Contexte du cycle (`cycle_phase`, `cycle_day`, `cycle_source`, #166).** Ces
trois clés n'existent QUE si `[health].cycle_tracking` n'est pas `"off"`
(défaut) : à `"off"`, ne jamais les écrire ni les demander — zéro mention. Elles
portent un CONTEXTE de lecture du bilan matinal (HRV, FC de repos), jamais une
règle de décision ni un diagnostic. Phase/jour absents (source muette, pas
d'entrée du jour) = clés omises, jamais devinées ni reportées de la veille.
Valeurs d'une source ou dites par l'athlète : normalisées par
`scripts/arc_cycle.py` (`normalize_phase`/`normalize_day`) ou, pour une saisie
`/log`, par `scripts/arc_log.py`.

```arc
{"arc": 1, "kind": "health", "date": "2026-09-23", "morning_check": "full",
 "hrv_overnight_ms": 41, "resting_hr_bpm": 52,
 "cycle_phase": "luteal", "cycle_day": 22, "cycle_source": "manual",
 "verdict": "green", "verdict_reason": "HRV un peu basse, cohérente avec la phase lutéale (contexte) ; aucun autre signal : séance maintenue."}
```

```arc
{
  "arc": 1, "kind": "health", "date": "2026-09-20", "morning_check": "full",
  "sleep_total_s": 27720, "sleep_deep_s": 5400, "sleep_light_s": 15000, "sleep_rem_s": 6000,
  "sleep_awake_s": 1320, "sleep_score": 81,
  "sleep_start": "2026-09-19T23:12:00+02:00", "sleep_end": "2026-09-20T06:54:00+02:00",
  "hrv_overnight_ms": 62, "hrv_baseline_low_ms": 58, "hrv_baseline_high_ms": 66, "hrv_status": "balanced",
  "resting_hr_bpm": 47, "readiness_score": 74,
  "readiness_factors": {"sleep": 62, "sleep_history": 70, "hrv": 80, "acute_load": 75},
  "body_battery_high": 88, "body_battery_low": 24, "stress_avg": 31, "weight_kg": 68.4, "weight_origin": "garmin",
  "verdict": "amber",
  "verdict_reason": "HRV bas, FC de repos stable : stress autonome, garder l'aérobie et couper l'intensité."
}
```

En `morning_check = "minimal"` :

```arc
{"arc": 1, "kind": "health", "date": "2026-09-21", "morning_check": "minimal", "readiness_score": 68, "verdict": "green", "verdict_reason": "Readiness correcte : séance maintenue."}
```

Bande Garmin absente (`get_hrv_data` sans `baseline` — watch récente, historique Garmin
encore court) : la ligne de base personnelle (`python3 scripts/arc_index.py hrv-baseline`,
voir plus bas) prend sa place, jamais un statut Garmin inventé.

```arc
{
  "arc": 1, "kind": "health", "date": "2026-09-22", "morning_check": "full",
  "hrv_overnight_ms": 47, "resting_hr_bpm": 51, "readiness_score": 60,
  "hrv_personal_low_ms": 56.2, "hrv_personal_high_ms": 59.4, "hrv_personal_status": "sous",
  "verdict": "amber",
  "verdict_reason": "Pas de bande Garmin disponible ; sous la référence personnelle (56-59 ms) : garder l'aérobie, couper l'intensité."
}
```

### `weather`

| Clé | Type | Notes |
|---|---|---|
| **`date`** | date | |
| **`location`** | texte | lieu résolu (voir `weather-forecast`) |
| **`category`** | `green` `yellow` `orange` `red` | 🟢 / 🟡 / 🟠 / 🔴 selon les seuils du skill |
| `temp_min_c`, `temp_max_c`, `feels_like_c` | nombre (négatif admis) | |
| `humidity_pct`, `chance_of_rain_pct` | 0-100 | |
| `wind_kmh`, `gust_kmh`, `wind_dir_deg` | nombre | |
| `precip_mm`, `uv_index` | nombre | |
| `thunderstorm` | booléen | |
| `sunrise`, `sunset` | texte | `HH:MM` local |
| `best_slot` | `morning` `midday` `evening` `none` | 🌅 / ☀️ / 🌇 / aucun (indoor) |
| `slot_reason` | texte | une phrase |
| `source`, `fetched_at` | texte, date-heure | |

```arc
{
  "arc": 1, "kind": "weather", "date": "2026-09-21", "location": "Tournai", "category": "yellow",
  "temp_min_c": 14, "temp_max_c": 26, "feels_like_c": 27, "humidity_pct": 60,
  "wind_kmh": 18, "gust_kmh": 32, "wind_dir_deg": 240, "precip_mm": 0.4, "chance_of_rain_pct": 20,
  "uv_index": 6, "thunderstorm": false, "sunrise": "07:38", "sunset": "19:52",
  "best_slot": "morning", "slot_reason": "26 °C à midi avec UV 6 : sortir avant 9 h.",
  "source": "wttr.in/Tournai?format=j1", "fetched_at": "2026-09-20T18:02:00+02:00"
}
```

### `week`

| Clé | Type | Notes |
|---|---|---|
| **`week_start`** | date | lundi de la semaine (= nom de fichier) |
| **`location`** | texte | lieu d'entraînement de la semaine (lu par `weather-forecast`) |
| **`sessions`** | liste d'objets | une séance par entrée, voir ci-dessous |
| `phase` | texte | phase du plan (« Base », « Spécifique », « Affûtage »…) |
| `target_duration_s`, `target_distance_m`, `target_elevation_m` | nombre | volume visé |
| `week_type`, `quality_sessions`, `long_run_target_s`, `strength_emphasis` | `build` `recovery` `taper` `race` `lead_in` `post_race` ; entier ; nombre (s) ; texte | squelette de bloc (#190, `arc_index.py plan-skeleton`) — facultatifs, jamais requis d'une semaine écrite à la main |

Chaque séance : **`date`** (date), **`sport`** (comme `activity`), **`title`**
(texte), et `planned_duration_s`, `planned_distance_m`, `planned_elevation_m`
(nombres), `intensity` (`rest` `recovery` `endurance` `tempo` `threshold`
`vo2max` `race` `strength`), `placeholder` (booléen, #190 : créneau posé par `plan-skeleton`, à habiller par le coach, qui retire le drapeau), `outdoor` (booléen), `garmin_workout_id`
(entier, après le push), `status` (`planned` `done` `missed` `moved`
`cancelled`), `weather_category` et `best_slot` (comme `weather`), et
`heat_adjustment` (#171, objet optionnel : trace de l'ajustement des cibles à
la chaleur, à recopier telle que produite par `arc_workout_targets.py targets
--heat` → `trace.heat_adjustment` — `factor` (facteur sur l'allure, FC
inchangée) obligatoire ; `temp_c` (omis si aucune température connue, ex. 🔴
dû au seul vent/orage), `temp_basis` (`temperature` `feels_like`), `action`,
`category`, `acclimated`, `slot`, `dew_point_c`, `reason` facultatifs). Jamais
calculé à la main.

Tenez `status` à jour quand une séance est réalisée, manquée ou déplacée.

```arc
{
  "arc": 1, "kind": "week", "week_start": "2026-09-21", "location": "Tournai", "phase": "Spécifique",
  "target_duration_s": 28800, "target_distance_m": 62000, "target_elevation_m": 1500,
  "sessions": [
    {"date": "2026-09-22", "sport": "running", "title": "Endurance fondamentale 50 min", "planned_duration_s": 3000, "intensity": "endurance", "outdoor": true, "status": "done", "weather_category": "green", "best_slot": "midday"},
    {"date": "2026-09-24", "sport": "trail", "title": "Côtes 8 × 90 s", "planned_duration_s": 4200, "planned_elevation_m": 450, "intensity": "vo2max", "outdoor": true, "garmin_workout_id": 998877, "status": "planned"},
    {"date": "2026-09-25", "sport": "strength", "title": "Renforcement 40 min", "planned_duration_s": 2400, "intensity": "strength", "outdoor": false, "status": "planned"},
    {"date": "2026-09-27", "sport": "trail", "title": "Sortie longue 25 km / 900 m D+", "planned_distance_m": 25000, "planned_elevation_m": 900, "intensity": "endurance", "outdoor": true, "status": "planned"}
  ]
}
```

**Plan multi-semaines (#69).** Un fichier peut porter **plusieurs semaines** au
lieu d'une seule : `weeks`, une liste d'objets ayant chacun exactement la forme
ci-dessus (`week_start`/`location`/`sessions` obligatoires par entrée, le reste
facultatif). Les deux formats sont **mutuellement exclusifs** dans un même
fichier — `weeks` ET `week_start`/`location`/`sessions`/`phase`/`target_*` au
premier niveau ensemble est une erreur de contrat (« ne mélangez pas… »). Un
fichier à une seule semaine reste écrit exactement comme avant #69 (format du
premier exemple ci-dessus) : `weeks` est un AJOUT, jamais une obligation.

Chaque semaine de `weeks` est validée **individuellement**, avec les mêmes
règles qu'une semaine unique, plus trois vérifications propres au format
multi-semaines : `week_start` doit tomber un **lundi** (message nommant le jour
trouvé), aucune séance de `sessions` ne peut porter une `date` en dehors de sa
propre semaine (lundi à dimanche), et deux entrées de `weeks` ne peuvent pas
partager le même `week_start` (doublon signalé avec l'index de la première
occurrence). Un chevauchement plus large (deux lundis distincts dont les
plages de 7 jours se recouvriraient) ne peut pas se produire tant que chaque
`week_start` est lui-même un lundi valide — la vérification de lundi couvre
donc déjà ce cas, le doublon exact restant le seul autre à contrôler.

```arc
{
  "arc": 1, "kind": "week",
  "weeks": [
    {"week_start": "2026-09-21", "location": "Tournai", "phase": "Spécifique",
     "sessions": [
       {"date": "2026-09-22", "sport": "running", "title": "Endurance fondamentale 50 min", "planned_duration_s": 3000, "intensity": "endurance", "outdoor": true, "status": "planned"},
       {"date": "2026-09-24", "sport": "trail", "title": "Côtes 8 × 90 s", "planned_duration_s": 4200, "planned_elevation_m": 450, "intensity": "vo2max", "outdoor": true, "status": "planned"}
     ]},
    {"week_start": "2026-09-28", "location": "Tournai", "phase": "Spécifique",
     "sessions": [
       {"date": "2026-09-30", "sport": "trail", "title": "Sortie longue 28 km / 1000 m D+", "planned_distance_m": 28000, "planned_elevation_m": 1000, "intensity": "endurance", "outdoor": true, "status": "planned"}
     ]}
  ]
}
```

**Nom de fichier.** Comme pour une semaine unique, le fichier vit dans
`planning/`, nommé `Semaine_<lundi>.md` — pour un plan multi-semaines, le lundi
de la **première** semaine du fichier (`weeks[0].week_start`). L'index
(`scripts/arc_index.py`) éclate un fichier `weeks` en autant de lignes que de
semaines dans la table dérivée `week` (une ligne par `week_start`, toutes
partageant le même `source_path`) — le tableau de bord (vue Semaine) retrouve
chaque semaine par sa propre date sans distinguer les deux formats. La purge
par fichier (une écriture qui change le fichier) retire bien TOUTES ses
semaines à la fois, comme avant #69 pour une semaine unique.

**`scripts/arc_guardrails.py check --week`** ne peut pas deviner tout seul
*laquelle* des semaines d'un fichier `weeks[]` vérifier : par défaut, il prend
la **première dont le lundi tombe le jour de `--today` ou après** — ce qui
couvre le cas courant (vérifier la semaine en cours, ou la prochaine si le
fichier ne contient plus que des semaines à venir) sans qu'il soit nécessaire
de faux-dater `--today` (qui fausserait par ailleurs la projection ACWR).
Précisez `--week-start AAAA-MM-JJ` pour vérifier une AUTRE semaine du fichier
explicitement (ex. la semaine d'après, ou une semaine déjà passée) :

```bash
python3 scripts/arc_guardrails.py check --week planning/Semaine_2026-09-21.md --week-start 2026-10-05
```

**`scripts/arc_workout_targets.py --session <path>#<date>`**, lui, n'a pas ce
problème : le sélecteur porte déjà une date de séance précise, qui suffit à
retrouver la bonne semaine (`weeks[].sessions[]` parcourues toutes ensemble)
sans argument supplémentaire.

**Le format historique (une semaine au premier niveau) garde ses contrôles
d'AVANT #69, inchangés** : ni le contrôle de lundi, ni celui de la fenêtre de
séances (ajoutés SEULEMENT pour chaque entrée de `weeks[]`) ne s'appliquent à
lui — un fichier à une seule semaine déjà écrit ne peut donc jamais devenir non
conforme à cause de cette histoire (voir `arc_contract._validate_week`).
`--week-start` reste utilisable sur un tel fichier, mais seulement pour
VÉRIFIER qu'il désigne bien sa seule semaine (erreur explicite sinon) — il n'a
qu'une semaine à choisir.

**Collision entre un fichier dédié et une entrée multi-semaines.** Rien
n'empêche un fichier dédié `planning/Semaine_2026-09-28.md` (une semaine) et un
fichier multi-semaines `planning/Semaine_2026-09-21.md` (`weeks` couvrant
21 et 28) de décrire tous les deux la semaine du 28 septembre. L'index tranche
par **priorité au fichier dédié** — celui dont le nom porte exactement ce
lundi (`Semaine_<week_start>.md`) — et, à défaut d'un tel fichier (deux
fichiers multi-semaines qui se recouvrent sans qu'aucun ne soit le fichier
dédié de cette semaine), au fichier dont le **chemin est le plus petit par
ordre alphabétique** (jamais la date de dernière modification — voir
`arc_index.week_collisions` pour pourquoi : `mtime` n'est pas reconstituée par
un `git clone`/`checkout`, un départage par mtime redeviendrait arbitraire dès
qu'un workspace versionné change de machine). La semaine écartée n'est pas
hors contrat pour autant (elle a été validée comme les autres) : elle est
seulement retirée des tables dérivées lues par le tableau de bord et les CLI
(colonne `shadowed`) — `scripts/arc_guardrails.py check --week` et
`scripts/arc_workout_targets.py --session` continuent de fonctionner sur son
propre contenu, mais impriment un avertissement (`shadowed_warning`/stderr)
quand la semaine sélectionnée est justement celle-là. L'écart apparaît aussi
dans les `issues` du fichier perdant, dans une section **séparée** de
`.arc/backfill.md` (« Collisions de semaine », jamais mélangée aux fichiers
réellement hors contrat — voir le skill `arc-backfill`).

Évitez la collision plutôt que d'en dépendre comme mécanisme de remplacement :
**quand un nouveau plan reprend des semaines déjà écrites ailleurs** (ancien
plan multi-semaines, ou fichiers dédiés qu'on réorganise), retirez ou
supprimez vous-même les semaines qui se chevauchent dans l'ANCIEN fichier —
n'écrivez jamais un nouveau fichier en laissant le doublon au hasard du
départage. `weeks` doit rester une liste NON VIDE d'objets, jamais `null` :
`{"weeks": null}` est une erreur de contrat explicite (`week.weeks : liste
attendue`), jamais une clé silencieusement ignorée comme une clé inconnue
ordinaire.

### `nutrition`

| Clé | Type |
|---|---|
| **`date`** | date |
| `intake_kcal`, `burned_kcal` | nombre (apport déclaré, dépense Garmin) |
| `carbs_g`, `protein_g`, `fat_g` | nombre |
| `hydration_ml` | nombre |
| `weight_kg`, `target_weight_kg` | nombre |
| `intake_source` | `manual` (défaut implicite : déclaré par l'athlète) `garmin` (journal alimentaire Garmin importé, #167) — une seule source de vérité par jour |
| `garmin_pushed` | liste `{key, kind, name?, qty?, ml?, food_id?, serving_id?, log_id?, at?}` — écritures confirmées vers Garmin Connect (#167) ; `key` = empreinte de `scripts/arc_nutrition_sync.py`, une clé déjà présente n'est jamais repoussée ; `kind` = `create_custom_food` `log_custom_food` `log_food` `add_hydration_data`. Même clé acceptée sur `activity` pour un apport `/log` en cours d'effort |

```arc
{"arc": 1, "kind": "nutrition", "date": "2026-09-20", "intake_kcal": 2650, "burned_kcal": 2900, "carbs_g": 360, "protein_g": 120, "fat_g": 80, "hydration_ml": 2500, "weight_kg": 68.4, "target_weight_kg": 67.5}
```

#### Entrée de `garmin_pushed` (#167)

Une entrée par écriture confirmée vers Garmin Connect, produite par `scripts/arc_nutrition_sync.py record`
(jamais composée à la main) : **`key`** (empreinte, ce qui rend la relance idempotente), **`kind`**,
et selon la nature `name`, `qty` (portions), `ml` (hydratation), `food_id`, `serving_id`, `log_id`
(seulement s'il a été relu sans ambiguïté), `at` (horodatage ISO de la poussée).

### `report`

| Clé | Type |
|---|---|
| **`date`** | date |
| **`report_type`** | `weekly` `monthly` `comparison` `race` `race_debrief` `adhoc` |
| **`title`** | texte |
| `period_start`, `period_end` | date |
| `location` | texte (comparaison de parcours, nom de la course pour `race_debrief`) |

Le rapport lui-même est le texte sous le bloc : le tableau de bord l'affiche tel quel.

```arc
{"arc": 1, "kind": "report", "date": "2026-09-21", "report_type": "weekly", "title": "Bilan de la semaine 38", "period_start": "2026-09-15", "period_end": "2026-09-21"}
```

**`race_debrief` (#61, épopée #23) : plan de course vs réalisé, PAR SEGMENT.**
Fichier `rapports/YYYY-MM-DD_debrief_<course>.md`, comme `comparison`
(`course-comparison`) : le bloc ```arc reste le schéma `report` générique
ci-dessus (`period_start`/`period_end` = date de la course, `location` = nom
de la course) — la comparaison chiffrée elle-même n'est PAS un nouveau champ
du contrat, c'est la sortie JSON de `python3 scripts/arc_race_debrief.py
debrief --plan <plan> --activity <activité de la course>` (mêmes conventions
que `compare_course.py`/`analyze_gpx.py` : script combine deux fichiers déjà
persistés, jamais une seconde implémentation dans l'agent). Le coach recopie
dans le texte libre, sous le bloc, au minimum : l'écart de temps total,
l'écart par segment (citer les identifiants `s01`, `s02`… du plan — stables
d'un appel à l'autre, #59), le fade mesuré vs prévu, et les `findings` du
script (ex. `depart_trop_rapide`, `glucides_sous_objectif`). **Un segment (ou
le bloc `fade`) marqué `resolution: "low"` n'est PAS un fait** : son delta
individuel est une interpolation, pas une mesure — ne le citez jamais tel
quel, regroupez ces segments (« résolution insuffisante sur s03-s06, non
exploitables individuellement ») ou omettez-les, et appuyez-vous sur les
totaux et les `findings` (qui n'utilisent déjà que les segments
`resolution: "high"`). Aligne les
splits kilométriques de l'activité sur les bornes du plan par mise à l'échelle
PROPORTIONNELLE de la distance cumulée (jamais du temps) quand les deux
mesures totales diffèrent — voir `scripts/arc_race_debrief.py::ASSUMPTIONS`
pour la méthode complète. `suggested_profile_updates` (glucides/h, tendance à
partir trop vite…) est une liste de PROPOSITIONS : présentez-les à l'athlète,
**n'écrivez jamais** vous-même `planning/Runner_Profile.md` à partir d'un
débrief — ce fichier reste édité par l'athlète (voir plus bas). **`date` est
le jour d'ÉCRITURE du rapport** (souvent J+1, le lendemain de la course),
**`period_start`/`period_end` sont le jour de la course elle-même** — les deux
diffèrent presque toujours, exactement comme dans l'exemple ci-dessous.

```arc
{"arc": 1, "kind": "report", "date": "2026-09-28", "report_type": "race_debrief", "title": "Débrief Trail des Collines", "period_start": "2026-09-27", "period_end": "2026-09-27", "location": "Trail des Collines"}
```

### `course_eval`

Reprend la sortie `--json` de `analyze_gpx.py` (skill `gpx-analysis`).

| Clé | Type |
|---|---|
| **`date`** | date |
| **`name`** | texte |
| `distance_m`, `elevation_gain_m`, `elevation_loss_m` | nombre |
| `is_loop` | booléen |
| `target_distance_m`, `target_elevation_m` | nombre (la cible évaluée) |
| `verdict` | `compatible` `partial` `incompatible` |
| `km_profile`, `climbs` | liste (telles que sorties par le script) |

```arc
{"arc": 1, "kind": "course_eval", "date": "2026-09-19", "name": "Boucle des Monts", "distance_m": 18400, "elevation_gain_m": 620, "elevation_loss_m": 615, "is_loop": true, "target_distance_m": 18000, "target_elevation_m": 600, "verdict": "compatible"}
```

### `race_plan`

| Clé | Type | Notes |
|---|---|---|
| **`date`** | date | date d'écriture du plan |
| **`race_name`** | texte | |
| **`race_date`** | date | |
| `distance_m`, `elevation_gain_m`, `target_time_s` | nombre | |
| `start_time` | date-heure | départ |
| `timezone` | texte | fuseau IANA de la course (ex. Europe/Paris, #184) — l'entrée `--tz` de la pénalité de nuit de `arc_race_pacing.py`, persistée pour ne pas la redemander au recalcul |
| `scenarios` | objet | `{"ambitious": s, "realistic": s, "safe": s}` en secondes |
| `heat_factor`, `heat_notes`, `pacing_personal` | nombre, liste, objet | sortie de `arc_race_pacing.py` : facteur de chaleur du plan et ses notes, coefficients personnels `[pacing.personal]` réellement appliqués (#188) — recopiés tels quels, lus par `arc_race_debrief.py --calibrate` pour recalibrer ; absents sur un plan ancien |
| `aid_stations` | liste d'objets | **`km`**, **`name`**, `services` (liste), `cutoff` (`HH:MM`, `+HH:MM` élapsé, ou date-heure ISO 8601, avec ou sans décalage `+01:00`/`Z` — barrière du surlendemain d'un ultra, #59/#205 ; heures murales lues dans le fuseau `timezone` du plan quand il est connu), `cutoff_day` (entier, avec `cutoff` en `HH:MM` seulement), `stop_s` (nombre, secondes — temps d'arrêt PRÉVU à ce ravito, #61 : repris par `arc_race_pacing.py`/`arc_race_debrief.py` au lieu du défaut générique (90 s) dès qu'il est renseigné ; à ne persister que pour un ravito dont l'arrêt attendu diffère vraiment du défaut, ex. repas chaud ou drop bag) |
| `water_points` | liste d'objets | **`km`**, **`source`** (`officiel` `osm_drinking_water` `osm_spring` `osm_cafe`), `name` |
| `gear` | liste | matériel obligatoire et conseillé |
| `notes`, `emergency` | liste | consignes de course et urgence (organisation, points d'abandon) imprimées telles quelles par le roadbook (#187) — absentes = dites absentes, jamais inventées |
| `nutrition_plan` | chemin du workspace | fichier `nutrition/…` du plan de ravitaillement (#187) |
| `segments` | liste d'objets | allures par segment depuis le modèle personnel (#59) — voir ci-dessous |

`take` d'un ravito (`aid_stations[]`, #187) : liste de textes courts — ce que le plan nutrition fait
**prendre** à ce ravito (« 2 gels », « 500 ml »), recopié du fichier `nutrition/`, jamais
déduit ; distinct de `services` (ce que le ravito sert). Le roadbook du tableau de bord
(vue « Roadbook », `/api/roadbook`) l'imprime à côté du ravito.

**`segments` (#59, `scripts/arc_race_pacing.py`).** Un segment par pièce de course
(découpage par distance cible + fusion des pentes similaires, voir la docstring
du module), pour que le stratège cite la **provenance par segment** (critère
d'acceptation #59) et que #61 (débrief post-course) puisse comparer plan vs
réalisé segment par segment sans recalculer sa propre segmentation.

| Clé | Type | Notes |
|---|---|---|
| **`id`** | texte | stable pour un même GPX et un même découpage (`s01`, `s02`…) |
| **`km_start`**, **`km_end`** | nombre | bornes kilométriques du segment |
| `distance_m` | nombre | longueur du segment, en mètres |
| `grade_mean_pct` | nombre (signe libre) | pente moyenne, en % — repère d'AFFICHAGE seulement, le temps prédit intègre la pente point par point (terrain vallonné) |
| `elevation_gain_m`, `elevation_loss_m` | nombre | D+ / D- du segment |
| `source` | `personal` `generic` `mixed` | provenance de la prédiction (`arc_slope_model.predict_speed`) |
| `reason_code` | `extrapolated` `no_model` `missing_elevation` | raison informative attachée à la prédiction, voir `notes` |
| `predicted_time_s` | objet | temps prédit par scénario, secondes — **mêmes clés que `scenarios` ci-dessus** (`ambitious`/`realistic`/`safe`) |
| `pace_s_km` | objet | allure prédite par scénario, s/km, mêmes clés |
| `night_fraction`, `night_factor` | objet | pénalité de nuit (#184) : part du temps de la section courue de nuit, et multiplicateur de temps appliqué, par scénario (mêmes clés) — présents seulement si le plan comporte de la nuit (`--race-date`, `--start` et `--tz` fournis) |
| `technicity` | objet | coefficient de technicité du terrain (#186) : `{coef, effective_factor, source (declared/osm/none), tags, coverage_pct, osm_coef?}` — présent seulement si `--technicity` a été demandé ; `effective_factor` est le multiplicateur de temps réellement appliqué (même pour les trois scénarios) |
| `altitude_m`, `altitude_factor` | nombre | pénalité d'altitude (#185) : altitude moyenne de la section (m) et multiplicateur de temps appliqué (le même pour les trois scénarios) — présents seulement si une section dépasse le seuil (1 500 m) |
| `notes` | liste | avertissements courts (ex. extrapolation hors plage du modèle, altitude GPX manquante) |

```arc
{
  "arc": 1, "kind": "race_plan", "date": "2026-09-20", "race_name": "Trail des Collines",
  "race_date": "2026-11-15", "distance_m": 52000, "elevation_gain_m": 2400,
  "start_time": "2026-11-15T07:30:00+01:00", "timezone": "Europe/Paris", "target_time_s": 25200,
  "scenarios": {"ambitious": 23400, "realistic": 25200, "safe": 27900},
  "aid_stations": [{"km": 14.5, "name": "Mont-Saint-Aubert", "services": ["eau", "solide"], "cutoff": "10:30"}],
  "water_points": [{"km": 22.0, "source": "osm_drinking_water", "name": "Fontaine du village"}],
  "gear": ["frontale", "couverture de survie", "gobelet"],
  "segments": [
    {"id": "s01", "km_start": 0.0, "km_end": 0.75, "distance_m": 750.0, "grade_mean_pct": 5.2,
     "elevation_gain_m": 39.0, "elevation_loss_m": 0.0, "source": "personal",
     "predicted_time_s": {"safe": 320, "realistic": 300, "ambitious": 280},
     "pace_s_km": {"safe": 426, "realistic": 400, "ambitious": 373}, "notes": []}
  ]
}
```

### `decision`

Traçabilité d'un ajustement du coach (#54, épopée #22) : ce qui a changé, ce qui
l'a justifié, avec quelle donnée à l'appui — pour que « pourquoi cette séance a
changé » se lise dans un fichier plutôt que dans la prose d'une conversation
disparue. Écrit par `coach` (garde-fous #52/#53, bilan matinal, météo,
changement de plan de course) et par `medical` (blessure, disponibilité) dès
qu'une séance est proposée, allégée, annulée ou déplacée — jamais pour une
séance qui se déroule comme prévu.

**Un fichier par décision** : `planning/AAAA-MM-JJ_decision_<slug>.md`, `<slug>`
un court résumé en kebab-case du sujet (ex. `hrv-hold`, `annulation-cotes`).
Plusieurs décisions le même jour → plusieurs fichiers, un `<slug>` différent
pour chacun. Choix retenu plutôt qu'un tableau `decisions` dans le fichier
semaine :

- **une lecture reste indépendante d'une autre** — un backfill (jamais
  nécessaire ici, voir plus bas), une réindexation partielle ou un lien direct
  (`sources`, resume #56) n'ont pas besoin de charger ni de réécrire tout le
  fichier semaine ;
- **la cardinalité ne correspond pas** : une décision peut concerner une séance
  qui n'existe dans AUCUN fichier semaine (annulation d'un bilan matinal avant
  toute planification, ajustement d'un plan de course) — la forcer dans
  `week.sessions` demanderait une séance fictive ou un schéma à deux formes ;
  un fichier séparé n'a pas cette contrainte, `session_ref` (optionnel)
  suffit à pointer vers une séance existante quand il y en a une ;
- **cohérent avec le reste du contrat** : chaque `kind` déjà présent est
  « un fichier, un objet » (`report`, `course_eval`…) — aucun autre type
  n'imbrique une collection versionnée séparément dans un fichier qu'un autre
  agent réécrit par ailleurs (le fichier semaine change à chaque sync/statut de
  séance, ce qui aurait fait courir un risque de conflit d'écriture inutile) ;
- coût accepté : une décision qui modifie une séance planifiée cite cette
  séance par référence (`session_ref`) plutôt que par un lien de base de
  données — c'est `scripts/arc_index.py decisions` qui assemble la vue, pas le
  Markdown.

| Clé | Type | Notes |
|---|---|---|
| **`date`** | date | jour auquel la décision s'applique (= date du nom de fichier) |
| **`created_at`** | date-heure **avec fuseau obligatoire** | horodatage d'écriture (`Z` ou `+HH:MM`, jamais naïf) — départage plusieurs décisions du même `date`, voir note ci-dessous |
| **`trigger`** | `morning_check` `guardrail` `athlete_request` `medical` `weather` `race` `other` | ce qui a déclenché la décision |
| **`summary`** | texte | une phrase, dans la langue des documents — c'est elle qu'affichent l'encart « Pourquoi aujourd'hui ? » (#55) et la ligne « Pourquoi » du `resume` (#56) |
| **`outcome`** | `applied` `proposed` `rejected_by_athlete` `superseded` | ce qu'il est advenu de la décision |
| `inputs` | objet | valeurs clés qui l'ont justifiée, ex. `{"hrv_personal_status": "sous", "acwr_projected": 1.42}` — clés libres, en anglais, SI |
| `rule_ids` | liste | `rule_id` de `scripts/arc_guardrails.py` concernés (`r1_acwr_projected` … `r7_consecutive_quality`, voir `RULE_IDS`) — format `rN_nom_de_regle` validé, pas la liste vivante des règles (voir note ci-dessous) |
| `sources` | liste | chemins **relatifs au workspace** ayant justifié la décision, ex. `resources/running/acwr.md`, `medical/2026-09-20_health.md` — voir « chemins relatifs au workspace » ci-dessous pour ce qui est refusé |
| `before` | objet | ce qui change dans la séance concernée, état AVANT — voir ci-dessous |
| `after` | objet | même chose, état APRÈS — pour une annulation sans remplacement, écrivez `"after": {"status": "cancelled"}` explicitement (jamais une clé absente pour dire « annulé » : l'absence de `after` veut dire « pas encore de remplacement connu », pas « annulé ») |
| `session_ref` | objet | **`week`** (chemin du fichier semaine), **`date`** (date de la séance) — quand la décision touche une séance déjà planifiée |
| `garmin_workout_id` | entier | si un push Garmin a changé suite à la décision |
| `supersedes` | texte | chemin **relatif au workspace** de la décision que celle-ci remplace — voir « Remplacer une décision » ci-dessous |

`before`/`after` ne sont **pas** un objet `session` complet (voir `week`
ci-dessus) : seuls les champs qui **changent** sont recopiés, tous facultatifs
— `date`, `sport`, `title`, `intensity`, `planned_duration_s`, `status`. L'état
COURANT complet de la séance reste dans le fichier semaine (`session_ref` pour
le retrouver) ; dupliquer ici les champs inchangés créerait deux sources de
vérité pour la même valeur.

**Chemins relatifs au workspace** (`sources`, `supersedes`, `session_ref.week`) :
un simple chemin POSIX depuis la racine du workspace, ex.
`medical/2026-09-20_health.md`. Sont **refusés** : une URL (`https://…`,
`mailto:…`, `file:…` — tout `:` dans la valeur), un chemin Windows
(`C:\Users\...`), un antislash comme séparateur, un chemin qui commence par
`~` (répertoire personnel) ou par `/` (absolu), et tout segment vide, `.` ou
`..` (`resources//x.md`, ou une remontée du type `..` répétée) — jamais de
remontée hors du workspace ni de racine déguisée.

**`rule_ids` n'est pas vérifié contre la liste vivante des règles.**
`scripts/arc_contract.py` ne peut pas importer `scripts/arc_guardrails.py`
(qui importe déjà `arc_index`, lui-même dépendant de `arc_contract` : un
import dans l'autre sens créerait un cycle) — la forme `rN_nom_de_regle` est
donc validée par un **motif**, jamais contre `arc_guardrails.RULE_IDS`. Un
`rule_id` qui ne correspond à AUCUNE règle connue (faute de frappe, règle
retirée) n'est donc pas rejeté par le contrat lui-même ; recopiez le `rule_id`
exact rendu par `scripts/arc_guardrails.py` (jamais un libellé inventé). Un
test dédié de la suite du contrat vérifie que chaque `arc_guardrails.RULE_IDS`
correspond bien au motif `arc_contract.RULE_ID_RE`, pour que les deux ne
divergent jamais silencieusement.

**`created_at` exige un fuseau explicite, et ne s'écarte pas de `date`.** Une
date-heure NAÏVE (sans `Z` ni `+HH:MM`) est rejetée : le journal des décisions
(`scripts/arc_index.py decisions`) trie plusieurs décisions du même jour par
`created_at`, et comparer des horodatages sans savoir de quel fuseau ils
viennent donnerait un ordre faux dès que deux décisions sont écrites depuis des
fuseaux différents (l'index normalise en UTC pour ce tri, voir
`arc_contract.decision_created_at_utc`). Au-delà d'un jour d'avance sur `date`
(une décision du 20 septembre datée du 25), le validateur la rejette aussi —
sentant la faute de frappe plutôt qu'un cas légitime ; cette comparaison se
fait dans le fuseau PROPRE de `created_at`, tel qu'écrit, pas en UTC. Une
décision écrite la veille au soir pour le lendemain (`created_at` antérieur à
`date`) reste normale, sans aucune borne basse.

**Jamais de dette de backfill.** `decision` est un type NEUF : aucun fichier
écrit avant #54 ne peut en porter un. `scripts/arc_index.py backfill-plan`
l'exclut explicitement, au même titre que `Runner_Profile.md`/
`active_objective.md` — son absence pour une date donnée n'est jamais un
manque à signaler, seulement l'absence de toute décision ce jour-là.

**Ordre d'écriture.** Quand la décision modifie une séance planifiée : réécrire
d'abord le fichier semaine (`week`, nouvel état de la séance), PUIS écrire le
fichier `decision` qui la référence par `session_ref` — jamais l'inverse, pour
qu'une décision publiée ne pointe jamais vers une séance qui ne reflète pas
encore le changement. Valider les DEUX fichiers ensuite :

```bash
python3 scripts/arc_index.py --validate planning/Semaine_2026-09-21.md planning/2026-09-22_decision_hrv-hold.md
```

**Remplacer une décision (`supersedes`).** Une décision ne se réécrit jamais
sur place une fois `outcome` posé à autre chose que `proposed` — un bloc
`decision` est un instantané daté (`created_at`), pas un document qu'on
corrige. Pour une décision qui change d'avis (ré-évaluation, nouvelle donnée) :

1. écrire un NOUVEAU fichier `decision` avec `supersedes` pointant vers le
   chemin de l'ancien ;
2. puis rouvrir l'ANCIEN fichier et poser son `outcome` à `"superseded"`
   (le seul champ qu'on réécrit sur un fichier `decision` déjà publié).

`scripts/arc_index.py decisions --active` exclut alors `superseded` (et
`rejected_by_athlete`) du journal courant, tout en gardant les deux fichiers
pour l'historique complet.

Bilan matinal qui bascule le plan en repos (garde-fou santé, #53) :

```arc
{
  "arc": 1, "kind": "decision", "date": "2026-09-22", "created_at": "2026-09-22T07:10:00+02:00",
  "trigger": "morning_check", "summary": "HRV sous la référence personnelle : séance de qualité reportée en récupération.",
  "outcome": "applied",
  "inputs": {"hrv_personal_status": "sous", "readiness_score": 52},
  "sources": ["medical/2026-09-22_health.md"],
  "before": {"date": "2026-09-22", "sport": "trail", "title": "Côtes 8 × 90 s", "intensity": "vo2max", "planned_duration_s": 4200},
  "after": {"intensity": "recovery", "planned_duration_s": 2400, "title": "Footing de récupération 40 min"},
  "session_ref": {"week": "planning/Semaine_2026-09-21.md", "date": "2026-09-22"}
}
```

Garde-fou `block` (#53) qui bloque une séance de qualité proposée le lendemain
d'un verdict rouge — session interactive, `outcome: "proposed"` : l'athlète
n'a pas encore confirmé l'alternative, la séance flaguée n'est donc ni
réécrite dans le fichier semaine ni poussée sur Garmin :

```arc
{
  "arc": 1, "kind": "decision", "date": "2026-09-24", "created_at": "2026-09-23T19:40:00+02:00",
  "trigger": "guardrail", "summary": "Séance de qualité proposée en alternative : verdict rouge la veille (r5_quality_after_red).",
  "outcome": "proposed", "rule_ids": ["r5_quality_after_red"],
  "inputs": {"verdict_previous_day": "red"},
  "sources": ["medical/2026-09-23_health.md"],
  "before": {"date": "2026-09-24", "sport": "trail", "title": "Seuil 3 × 10 min", "intensity": "threshold"},
  "after": {"intensity": "recovery", "title": "Footing de récupération 35 min"},
  "session_ref": {"week": "planning/Semaine_2026-09-21.md", "date": "2026-09-24"}
}
```

Même garde-fou, une fois que l'athlète a confirmé l'alternative : NOUVEAU
fichier `decision` (`outcome: "applied"`, `supersedes` vers celui ci-dessus),
puis le fichier `proposed` ci-dessus est rouvert pour poser son propre
`outcome` à `"superseded"` (protocole « Remplacer une décision » ci-dessous) —
c'est SEULEMENT à ce moment que le fichier semaine est réécrit et la séance
poussée sur Garmin :

```arc
{
  "arc": 1, "kind": "decision", "date": "2026-09-24", "created_at": "2026-09-24T07:15:00+02:00",
  "trigger": "guardrail", "summary": "Alternative confirmée par l'athlète : séance allégée en récupération.",
  "outcome": "applied", "rule_ids": ["r5_quality_after_red"],
  "supersedes": "planning/2026-09-23_decision_seance-qualite-bloquee.md",
  "sources": ["medical/2026-09-23_health.md"],
  "before": {"date": "2026-09-24", "sport": "trail", "title": "Seuil 3 × 10 min", "intensity": "threshold"},
  "after": {"intensity": "recovery", "title": "Footing de récupération 35 min"},
  "session_ref": {"week": "planning/Semaine_2026-09-21.md", "date": "2026-09-24"}
}
```

Décision qui en remplace une autre (`supersedes`) — la précédente restait
`"proposed"`, une nouvelle donnée arrive avant qu'elle soit appliquée :

```arc
{
  "arc": 1, "kind": "decision", "date": "2026-09-24", "created_at": "2026-09-24T06:30:00+02:00",
  "trigger": "medical", "summary": "Douleur signalée : séance de qualité annulée plutôt qu'allégée.",
  "outcome": "applied", "supersedes": "planning/2026-09-23_decision_allegement-qualite.md",
  "sources": ["medical/2026-09-24_health.md"],
  "after": {"status": "cancelled"},
  "session_ref": {"week": "planning/Semaine_2026-09-21.md", "date": "2026-09-24"}
}
```

### `gear_inspection`

Inspection photo d'une paire de chaussures (#135, skill `gear-inspection`) : un fichier
par inspection, `gear/YYYY-MM-DD_<gear_id>_inspection.md`. Le nom porte la date et le
`gear_id` (avertissement à la validation s'ils contredisent le bloc). Le texte libre sous
le bloc porte la justification visuelle, les indices de foulée en clair et la comparaison
avec l'inspection précédente. Dossier `gear/` : gitignoré, données personnelles — les
photos vivent dans `gear/photos/`, **jamais dans le dépôt public**.

| Clé | Type | Notes |
|---|---|---|
| **`date`** | date | jour de l'inspection |
| **`gear_id`** | slug | la paire, comme dans `activities` / `### Chaussures` du profil |
| **`condition`** | `green` `yellow` `orange` `red` | verdict 🟢🟡🟠🔴, justifié visuellement sous le bloc |
| `distance_m` | nombre | kilométrage de la paire AU MOMENT de l'inspection (lu dans `python3 scripts/arc_index.py gear`, jamais deviné ; clé omise si inconnu) |
| `wear_zones` | liste d'objets | **`side`** (`left` `right`), **`zone`** (`heel_posterolateral` `heel_lateral` `heel_medial` `heel_central` `midfoot_lateral` `midfoot_medial` `midfoot_central` `forefoot_lateral` `forefoot_medial` `forefoot_central` `toe`), `severity` (`light` `moderate` `marked`) |
| `asymmetry` | objet | **`level`** (`none` `mild` `marked`), `side` (`left` `right`, le côté le PLUS usé — obligatoire dès que `level` vaut `mild`/`marked`) |
| `gait_hints` | liste | `heel_strike` `midfoot_forefoot_strike` `pronation_hint` `supination_hint` — un INDICE, jamais un diagnostic |
| `photos` | liste de chemins | sous `gear/photos/`, `.jpg` `.jpeg` `.png` `.webp` seulement |
| `previous` | chemin | inspection précédente de la MÊME paire (`gear/…_inspection.md`) : la comparaison est le signal le plus fiable |
| `scale_reference` | booléen | `true` si une pièce ou une règle est visible dans le cadre |
| `lug_depth_mm` | nombre | profondeur de crampon en mm — **interdite** sans `scale_reference: true` (aucune mesure sans échelle) |

Mesure absente = clé omise. `asymmetry.side` sur `none` est ignoré (avertissement) ; une
seule semelle documentée dans `wear_zones` est signalée (le protocole demande les deux).

```arc
{"arc": 1, "kind": "gear_inspection", "date": "2026-09-24", "gear_id": "pegasus-41", "condition": "yellow", "distance_m": 412000, "wear_zones": [{"side": "left", "zone": "heel_posterolateral", "severity": "moderate"}, {"side": "right", "zone": "heel_posterolateral", "severity": "light"}], "asymmetry": {"level": "mild", "side": "left"}, "gait_hints": ["heel_strike"], "photos": ["gear/photos/2026-09-24_pegasus-41_semelles.jpg"], "previous": "gear/2026-08-02_pegasus-41_inspection.md", "scale_reference": true, "lug_depth_mm": 2.5}
```

## Réécrire un fichier ancien (backfill)

Un fichier écrit avant ce contrat n'a pas de bloc. Pour le mettre au contrat :

1. Lisez-le en entier.
2. Construisez le bloc avec **ce que le fichier dit** — ne devinez pas une
   valeur absente, et ne refaites un appel Garmin que si la valeur manque et
   que la date le justifie (règles de `garmin-sync-efficiency`).
3. Insérez le bloc sous le titre ; **conservez tout le texte existant**.
4. Validez avec `scripts/arc_index.py --validate`.

La liste des fichiers à reprendre est produite par
`python3 scripts/arc_index.py backfill-plan`, dans `.arc/backfill.md`.
