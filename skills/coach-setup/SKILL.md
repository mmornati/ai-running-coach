---
name: coach-setup
description: Premier démarrage — configure le staff d'agents, le sport, le style de coaching et le profil de l'athlète, puis écrit le tout dans config/workspace.user.toml et planning/Runner_Profile.md. Charger quand l'utilisateur lance /coach-setup, quand il demande à changer la façon dont le coach lui parle, quels agents sont actifs, sa discipline ou son bilan santé matinal, ou quand un agent constate qu'aucune configuration n'existe encore.
---

# Premier démarrage

Vous menez l'entretien. `scripts/coach_setup.py` sait ce qui manque et sait
écrire — ne devinez jamais à sa place, et n'écrivez jamais
`config/workspace.user.toml` à la main.

Le script ne remplace jamais une valeur déjà donnée. Relancer `/coach-setup`
est donc sans effet : c'est voulu, ne cherchez pas à le contourner.

## 1. Regarder ce qui manque

```bash
python3 scripts/coach_setup.py --status
python3 scripts/coach_setup.py --list-questions
```

`--list-questions` rend du JSON : `pending` contient **uniquement** les questions
sans réponse, dans l'ordre où les poser, chacune avec son `prompt`, son `help`,
son `default` et, le cas échéant, ses `choices` (`value` + `label`).

Si `pending` est vide, ne posez rien. Dites en une ligne que tout est déjà
configuré, résumez le style en vigueur, et proposez soit de changer un réglage
précis, soit de passer à l'objectif.

## 2. Mener l'entretien

Règles, dans l'ordre d'importance :

- **Une question à la fois.** Attendez la réponse avant la suivante.
- **Toujours montrer le défaut** et dire qu'un simple « / » le retient.
- Pour un `select` ou un `multi`, **listez les libellés**, pas les valeurs
  techniques. L'athlète répond en français ; c'est à vous de traduire vers la
  `value` correspondante.
- **Ne reformulez pas les questions** : elles sont écrites pour être posées
  telles quelles. Le `help` se donne seulement si l'athlète hésite.
- Dites que ces réponses vont dans un fichier **gitignoré**, sur sa machine.
- L'athlète peut s'arrêter en route : ce qui est répondu est écrit, le reste
  sera redemandé au prochain `/coach-setup`.

Deux questions méritent un mot de contexte si l'athlète hésite :

| Question | Ce qu'il faut savoir |
|---|---|
| `agents` | `coach` est indispensable : c'est lui qui planifie et pousse vers Garmin. Les trois autres sont optionnels. Retirer `medical` **ne désactive pas** le bilan santé matinal — c'est la question suivante qui le fait. |
| `morning_check` | `off` convient à une montre sans HRV, ou à quelqu'un qui ne veut pas que son entraînement dépende de ces données. Le coach planifie alors sur la charge et le ressenti déclaré. |

## 3. Écrire

Composez un JSON `{"<key>": <réponse>}` en reprenant les `key` du JSON de
l'étape 1, écrivez-le dans un fichier temporaire, puis :

```bash
python3 scripts/coach_setup.py --apply /tmp/reponses-coach.json
```

Le script valide chaque valeur contre son catalogue, écrit uniquement ce qui
manquait, et installe `planning/Runner_Profile.md` et
`planning/active_objective.md` depuis `templates/` s'ils n'existent pas encore.
Il rend un JSON : `written`, `skipped`, `scaffolded`, `still_pending`. Si une
valeur est refusée, corrigez-la avec l'athlète et relancez — n'écrivez pas le
fichier vous-même.

## 4. Le profil de l'athlète

`planning/Runner_Profile.md` vient d'être installé et n'est qu'un squelette. Ce
fichier-là, c'est **vous** qui l'éditez, avec l'athlète, en conversation — il est
libre par nature et ne rentre pas dans une clé de configuration.

### 4.a Pré-remplissage Garmin (story #65, si le serveur MCP répond)

Avant de poser les questions physiologiques classiques, essayez de récupérer
ce que Garmin sait déjà. **Uniquement si `[data].source = "garmin"` (défaut) —
#68** : à `"intervals"` ou `"strava"`, le serveur MCP `garmin` n'est ni installé ni
enregistré, sautez directement à la section suivante, sans tenter le moindre
appel. Le déclencheur, à `"garmin"`, est le serveur MCP `garmin` qui
**répond réellement** à un appel — `[agents].enabled` ne liste QUE les agents
joignables, ce n'est pas un indicateur de disponibilité MCP ; ne vous fiez
jamais à cette clé pour décider si Garmin est là.

**Ne devinez jamais un nom de champ non vérifié** : tout ce qui suit vient du
paquet `garmin_mcp` réellement installé (0.1.0), jamais d'une supposition.

| Champ du profil | Outil MCP | Champ de la réponse |
|---|---|---|
| FC max | `get_activities_by_date(start_date=J-180, end_date=aujourd'hui)`, paginé (`next_page` tant que `has_more`) | `max(max_hr_bpm)` sur les activités dont `type` CONTIENT « run » |
| FC de repos de référence | `get_stats(date=aujourd'hui)` — **uniquement si `[health].morning_check` ≠ `"off"`** | `last_7_days_avg_resting_hr` (moyenne 7 j — **jamais** `resting_heart_rate_bpm`, qui est la valeur DU JOUR) |
| FC au seuil (LTHR) | `get_lactate_threshold()` (sans dates → dernier relevé) | `lactate_threshold_heart_rate_bpm` |
| VO2max (Garmin) | `get_training_status(date=aujourd'hui)` | `vo2_max` |

**Pourquoi pas `get_user_profile()` pour tout regrouper en un seul appel ?**
Le vrai Garmin Connect expose probablement la LTHR/le VO2max/le sexe/la date
de naissance dans `userData`, mais `garmin_mcp` ne le CURATE PAS — l'outil
`get_user_profile()` retourne le JSON brut de l'endpoint `user-settings`
(`garminconnect/__init__.py::get_user_profile`), et le SEUL champ de cette
réponse dont ce dépôt ait jamais vérifié le nom (`userData.measurementSystem`,
pour l'unité de mesure) n'a rien à voir avec la physiologie. Écrire
`lactateThresholdHeartRate`/`vo2MaxRunning` sans les avoir vus dans le paquet
vendored serait deviner un nom de champ — interdit par ce même paragraphe.
`get_lactate_threshold()`/`get_training_status()` restent le choix,
précisément parce qu'ils SONT curatés avec des noms de champs vérifiés.

**FC max — jamais depuis `get_stats`.** `get_stats().max_heart_rate_bpm` est la
FC max mesurée **aujourd'hui** (souvent 110-130 bpm au réveil) : l'écrire comme
FC max corromprait silencieusement les zones Karvonen/%FCmax, le TRIMP et les
cibles poussées sur la montre. `garmin_mcp` n'expose aucun outil pour une « FC
max configurée/de test » — la meilleure approximation vérifiable est le
maximum observé sur les séances course à pied récentes, et ce n'est qu'un
PLANCHER, jamais une vraie FC max testée :

- Parcourez `get_activities_by_date` sur les 180 derniers jours (paginez avec
  `next_page` tant que `has_more` est vrai), filtrez toute activité dont
  `type` CONTIENT la sous-chaîne « run » (`running`, `trail_running`,
  `treadmill_running`, `track_running`, `ultra_run`, etc. — jamais un
  ensemble figé de deux valeurs : un nouveau `typeKey` Garmin contenant
  « run » doit être reconnu sans mise à jour du skill), à l'exclusion de tout
  ce qui n'en contient pas (`cycling`, `hiking`, `walking`...), prenez le
  maximum de `max_hr_bpm` sur ce qui reste.
- **N < 5 séances filtrées → n'affichez rien, repli sur la question classique.**
  Une poignée de séances ne dit rien d'une vraie FC max.
- Présentez-la EXPLICITEMENT comme une borne basse, jamais comme une FC max
  testée : « FC max observée sur N séances (valeur plancher, pas un test) ».

**FC de repos — jamais la valeur du jour, et jamais si le bilan matinal est
coupé.** Le modèle le dit lui-même (« votre ligne de base, pas la valeur du
jour ») : n'utilisez QUE `last_7_days_avg_resting_hr` de `get_stats`, jamais
`resting_heart_rate_bpm` (aujourd'hui) ni `get_rhr_day` (aussi une valeur
quotidienne). Si `[health].morning_check = "off"`, l'athlète a explicitement
choisi de ne pas faire dépendre l'entraînement de données de santé
matinales : **n'appelez pas `get_stats` du tout** pour ce champ — ignorez-le
silencieusement, comme un Garmin indisponible (la FC max et la LTHR viennent
d'activités/de biométrie d'effort, pas du bilan matinal : elles restent
récupérées normalement). Ne réactivez jamais un niveau plus strict que celui
configuré (voir AGENTS.md § Bilan matinal).

- **Hors ligne, outil absent de la liste blanche, erreur (401/timeout/etc.),
  ou champ manquant dans la réponse** : ignorez silencieusement ce point et
  repli sur la question classique du modèle — jamais d'échec visible, jamais
  de valeur inventée à sa place.
- Un appel qui réussit ne s'écrit **jamais** directement : proposez la valeur
  trouvée avec sa source et la date (« Ta montre Garmin indique une FC max
  observée de 182 sur tes 12 dernières séances — je le note ? »), et
  n'écrivez que ce que l'athlète confirme ou corrige. Une valeur corrigée par
  l'athlète prime toujours sur celle de Garmin. Pour la LTHR, montrez aussi
  `speed_hr_date` (date du relevé) si présent. **`is_stale` ne concerne PAS
  la LTHR** : dans `get_lactate_threshold()` (module `training.py` de
  `garmin_mcp`), ce champ vient de `power.get("isStale")`, la section
  puissance/FTP — pas la FC/vitesse au seuil — ne l'affichez pas pour ce champ
  (revue de code #112).
- Écrivez les valeurs confirmées avec :

  ```bash
  python3 scripts/coach_setup.py --apply-profile "$(mktemp -t coach-setup-profil)"
  ```

  où le fichier JSON associe le libellé EXACT du modèle à la valeur
  confirmée, avec la provenance en `source` (affichée en commentaire HTML dans
  le fichier, invisible pour le parseur — ni `value` ni `source` ne peuvent
  contenir de retour à la ligne, et `source` ne peut pas contenir `--`, qui
  refermerait ce commentaire prématurément) :

  ```json
  {
    "FC max": {"value": "182", "source": "Garmin (get_activities_by_date, max sur 12 séances/180 j), 2026-09-27"},
    "FC de repos de référence": {"value": "47", "source": "Garmin (get_stats, moyenne 7 j), 2026-09-27"}
  }
  ```

  Comme `--apply`, cette commande **n'écrase jamais** un champ déjà rempli —
  y compris un champ rempli via une sous-liste indentée en dessous du libellé
  (rendu dans `skipped`) — et refuse tout libellé qui n'existe pas déjà dans
  le modèle — un champ qui manque au modèle s'ajoute à
  `templates/Runner_Profile.template.md`, jamais improvisé à la volée.
- Si le champ est déjà rempli (athlète qui relance `/coach-setup`, ou qui
  vient de le renseigner à la main), ne proposez rien pour ce champ : la
  valeur existante prime, sans exception.

Une fois ce pré-remplissage traité (ou ignoré si Garmin n'est pas disponible),
enchaînez normalement sur les champs restants en conversation libre.

#### Mode passerelle (leanproxy)

Si l'installation utilise `--use-leanproxy`, appelez ces trois outils via
`leanproxy_invoke_tool(server="garmin", tool="get_activities_by_date", …)`
(idem pour `get_stats`/`get_lactate_threshold`/`get_training_status`) plutôt
que directement — voir `skills/garmin-sync-efficiency/SKILL.md`. Une
installation leanproxy déjà en place AVANT cette story n'a pas régénéré
`~/.config/leanproxy_servers.yaml` : si ces outils manquent côté passerelle,
éditez sa liste `GARMIN_ENABLED_TOOLS` à la main (voir
`docs/garmin-setup.md` § Mode passerelle) plutôt que de réinstaller.

Proposez-le, n'imposez pas : « on remplit votre profil maintenant, ou plus
tard ? ». Si c'est maintenant, suivez l'ordre du modèle et laissez vide tout ce
qu'il ne sait pas — un champ vide est ignoré, une valeur inventée fausse tout
le raisonnement d'entraînement.

Deux champs comptent plus que les autres, dites-le :

- **Lieu par défaut** — sans lui, le skill `weather-forecast` devra demander la
  ville à chaque validation.
- **Créneau habituel** — sans lui, le coach suppose une sortie le midi.

La section « Préférences de coaching » du profil **prime** sur le style choisi à
l'étape 2 : c'est là que vont « ce qui me motive », « ne me parle jamais de mon
poids », et la tolérance au risque.

## 5. Conclure

Terminez en cinq lignes maximum :

1. le style retenu, en une phrase, dans ses mots à lui ;
2. les agents installés ;
3. l'état du bilan matinal ;
4. ce qui reste à remplir dans le profil, s'il reste quelque chose ;
5. la suite : définir l'objectif dans `planning/active_objective.md` — proposez
   d'enchaîner.

Si les agents choisis diffèrent de ceux réellement installés, signalez-le :
`config/workspace.user.toml` est à jour, mais les fichiers d'agents ne le seront
qu'après `./install.sh --agents <liste>`.
