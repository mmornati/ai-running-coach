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
| `week` | `planning/Semaine_YYYY-MM-DD.md` (lundi de la semaine) | coach |
| `nutrition` | `nutrition/YYYY-MM-DD_nutrition.md` | nutritionist |
| `report` | `rapports/YYYY-MM-DD_rapport.md`, `rapports/YYYY-MM-DD_comparaison_<lieu>.md` | coach |
| `course_eval` | `planning/YYYY-MM-DD_evaluation_parcours_<lieu>.md` | skill `gpx-analysis` |
| `race_plan` | plan de course dans `planning/` | course-strategist |

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
| `garmin_activity_id` | entier | identifiant Garmin — clé de jointure, à toujours renseigner après un sync |
| `name` | texte | nom Garmin de l'activité |
| `location` | texte | lieu / parcours (sert à la comparaison de parcours) |
| `start_time` | date-heure | |
| `distance_m` | nombre | |
| `moving_duration_s` | nombre | ≤ `duration_s` |
| `elevation_gain_m`, `elevation_loss_m` | nombre | D+ / D- |
| `avg_hr_bpm`, `max_hr_bpm` | 20-250 | |
| `recovery_hr_bpm` | entier | HRR à 2 min ; absent = non mesuré, pas un signal |
| `avg_cadence_spm` | nombre | |
| `calories_kcal` | nombre | |
| `training_effect_aerobic`, `training_effect_anaerobic` | nombre | 0-5 |
| `rpe` | 0-10 | effort perçu déclaré — indispensable si la séance n'a pas de FC |
| `splits_cols` | liste | en-tête des splits, voir ci-dessous |
| `splits` | liste | une ligne par km, dans l'ordre de `splits_cols` |
| `gear_id` | texte | identifiant matériel (slug), voir ci-dessous |
| `carbs_g` | nombre | glucides ingérés pendant l'effort, 0-1000 g |
| `fluid_intake_ml` | nombre | liquide ingéré pendant l'effort, 0-10 000 ml |
| `weight_pre_kg`, `weight_post_kg` | nombre | pesée avant / après effort, 30-200 kg |
| `missing_reason` | objet | clé absente → cause |

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
- Nike Pegasus (retirée)
```

Une puce de **premier niveau** par paire — une puce indentée en dessous n'est
jamais une chaussure à part, elle est repliée dans les segments de la
chaussure précédente. Segments séparés par un tiret cadratin/demi-cadratin
(`—`/`–`, espaces autour optionnels), par un simple tiret **entouré
d'espaces** (` - ` : un nom de modèle peut légitimement contenir un trait
d'union SANS espaces, ex. « Salomon S/Lab Ultra-Trail », qui reste intact),
ou par un deux-points suivi d'un mot-clé reconnu : `depuis AAAA-MM-JJ` (ou
« mars 2026 »/« 03/2026 », 1er du mois — date d'achat), `alerte N km` (ou
`N miles`/`N mi`, convertis), `id: <texte>` (identifiant explicite, passé par
`gear_slug` comme n'importe quel `gear_id`). `(par défaut)` et `(retirée)`
peuvent être accolés n'importe où sur la ligne. `arc_legacy.parse_gear` lit
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
- Deux puces qui dérivent le même `gear_id` (même modèle racheté sans `id:`
  pour les distinguer) : la première garde le slug nu, les suivantes reçoivent
  `-2`, `-3`… et une collision signalée dans `gear_mileage().warnings` — pour
  l'éviter, donnez un `id:` explicite à chaque paire du même modèle.

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
  "calories_kcal": 912, "training_effect_aerobic": 3.8, "training_effect_anaerobic": 1.2, "rpe": 6,
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
| `weight_kg` | nombre | |
| `verdict` | `green` `amber` `red` | disponibilité du jour : maintenir / alléger / repos |
| `verdict_reason` | texte | obligatoire avec `verdict` |
| `missing_reason` | objet | |

```arc
{
  "arc": 1, "kind": "health", "date": "2026-09-20", "morning_check": "full",
  "sleep_total_s": 27720, "sleep_deep_s": 5400, "sleep_light_s": 15000, "sleep_rem_s": 6000,
  "sleep_awake_s": 1320, "sleep_score": 81,
  "sleep_start": "2026-09-19T23:12:00+02:00", "sleep_end": "2026-09-20T06:54:00+02:00",
  "hrv_overnight_ms": 62, "hrv_baseline_low_ms": 58, "hrv_baseline_high_ms": 66, "hrv_status": "balanced",
  "resting_hr_bpm": 47, "readiness_score": 74,
  "readiness_factors": {"sleep": 62, "sleep_history": 70, "hrv": 80, "acute_load": 75},
  "body_battery_high": 88, "body_battery_low": 24, "stress_avg": 31, "weight_kg": 68.4,
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

Chaque séance : **`date`** (date), **`sport`** (comme `activity`), **`title`**
(texte), et `planned_duration_s`, `planned_distance_m`, `planned_elevation_m`
(nombres), `intensity` (`rest` `recovery` `endurance` `tempo` `threshold`
`vo2max` `race` `strength`), `outdoor` (booléen), `garmin_workout_id`
(entier, après le push), `status` (`planned` `done` `missed` `moved`
`cancelled`), `weather_category` et `best_slot` (comme `weather`).

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

### `nutrition`

| Clé | Type |
|---|---|
| **`date`** | date |
| `intake_kcal`, `burned_kcal` | nombre (apport déclaré, dépense Garmin) |
| `carbs_g`, `protein_g`, `fat_g` | nombre |
| `hydration_ml` | nombre |
| `weight_kg`, `target_weight_kg` | nombre |

```arc
{"arc": 1, "kind": "nutrition", "date": "2026-09-20", "intake_kcal": 2650, "burned_kcal": 2900, "carbs_g": 360, "protein_g": 120, "fat_g": 80, "hydration_ml": 2500, "weight_kg": 68.4, "target_weight_kg": 67.5}
```

### `report`

| Clé | Type |
|---|---|
| **`date`** | date |
| **`report_type`** | `weekly` `monthly` `comparison` `race` `adhoc` |
| **`title`** | texte |
| `period_start`, `period_end` | date |
| `location` | texte (comparaison de parcours) |

Le rapport lui-même est le texte sous le bloc : le tableau de bord l'affiche tel quel.

```arc
{"arc": 1, "kind": "report", "date": "2026-09-21", "report_type": "weekly", "title": "Bilan de la semaine 38", "period_start": "2026-09-15", "period_end": "2026-09-21"}
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
| `scenarios` | objet | `{"ambitious": s, "realistic": s, "safe": s}` en secondes |
| `aid_stations` | liste d'objets | **`km`**, **`name`**, `services` (liste), `cutoff` (`HH:MM`) |
| `water_points` | liste d'objets | **`km`**, **`source`** (`officiel` `osm_drinking_water` `osm_spring` `osm_cafe`), `name` |
| `gear` | liste | matériel obligatoire et conseillé |

```arc
{
  "arc": 1, "kind": "race_plan", "date": "2026-09-20", "race_name": "Trail des Collines",
  "race_date": "2026-11-15", "distance_m": 52000, "elevation_gain_m": 2400,
  "start_time": "2026-11-15T07:30:00+01:00", "target_time_s": 25200,
  "scenarios": {"ambitious": 23400, "realistic": 25200, "safe": 27900},
  "aid_stations": [{"km": 14.5, "name": "Mont-Saint-Aubert", "services": ["eau", "solide"], "cutoff": "10:30"}],
  "water_points": [{"km": 22.0, "source": "osm_drinking_water", "name": "Fontaine du village"}],
  "gear": ["frontale", "couverture de survie", "gobelet"]
}
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
