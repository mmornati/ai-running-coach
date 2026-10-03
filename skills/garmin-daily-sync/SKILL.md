---
name: garmin-daily-sync
description: Use for the unattended (headless/cron) Garmin synchronisation — invoked as /garmin-daily-sync by scripts/daily-sync.sh, from the phone (Remote Control) or from the IDE. Orchestrates the coach agent + garmin-sync-efficiency to persist the last days of activities/sleep/HRV/readiness as Markdown, then emits a short ```resume``` block for the notification. Never asks questions.
---

# Garmin Daily Sync — Skill (orchestration headless)

Ce skill **n'ajoute aucune logique de synchronisation** : c'est le prompt versionné que le
cron (`scripts/daily-sync.sh`), le téléphone (`/garmin-daily-sync` dans une session
Remote Control) et l'IDE partagent. Il délègue tout à l'agent `coach` et au skill
`garmin-sync-efficiency`.

## Contexte d'exécution

- **Mode sans surveillance** : personne ne lit la conversation en direct. Ne JAMAIS poser de
  question (`question`, `AskUserQuestion`) ni attendre une validation. En cas de doute,
  choisir l'option conservatrice (ne rien écrire) et le signaler dans le résumé.
- **Configuration** : lire `config/workspace.toml` puis `config/workspace.user.toml`
  (ses valeurs priment) — `[language].documents` (langue des MD), `[sync].lookback_days`
  (défaut : 2), `[health].morning_check` (voir ci-dessous), `[data].source`
  (voir ci-dessous, #68).
- **Source de données (#68)** : ce skill est décrit ci-dessous pour
  `[data].source = "garmin"` (défaut) — rien ne change tant que cette clé vaut
  `garmin` ou est absente. À `intervals`, chaque outil `garmin` cité plus bas
  (activités, wellness/HRV/FC de repos/sommeil) est remplacé par son
  équivalent intervals.icu (table de correspondance dans `AGENTS.md`) : un
  seul appel `get_wellness_for_date` couvre HRV + FC de repos + sommeil. Le
  readiness Garmin n'a pas d'équivalent : à `full`, dire "readiness
  indisponible — source intervals.icu" au lieu d'un score ; ne jamais
  substituer le champ `subjective.readiness` (une valeur manuelle du jour,
  pas un score calculé — voir AGENTS.md). Le serveur MCP interrogé est alors
  `intervals`, pas `garmin` ; l'activité persistée porte `intervals_activity_id`
  (chaîne) au lieu de `garmin_activity_id` (entier), et omet HRR/`splits`
  (aucun équivalent). L'étape 2 (échantillons FIT) s'applique aussi, avec
  l'`intervals_activity_id` de la séance (`download_fit.py` lit la source dans
  `[data].source`) ; une activité importée depuis Strava y sort `INDISPONIBLE` —
  ni un échec ni une alerte, juste une séance sans KPI fins. **Marqueur « pas encore
  synchronisé » (`garmin-sync-efficiency`, règle 1a) : c'est l'absence de
  `intervals_activity_id`, pas de `garmin_activity_id`, qui compte ici** — un
  fichier `/log` déjà présent pour une date, sans cet identifiant, reste « pas
  encore synchronisé » et doit être fusionné à l'étape 1 ci-dessous, jamais
  pris pour une séance déjà traitée.
- **Source Strava (#164, `[data].source = "strava"`)** : mêmes règles, avec le serveur MCP
  `strava` (communautaire `strava-mcp` de r-huijts, outils à tirets : `get-recent-activities`,
  `get-activity-details`… — table « Garmin ↔ Strava » de `AGENTS.md`, jamais d'outil deviné).
  **Lecture seule, strictement** : ne jamais appeler `connect-strava`, `disconnect-strava` ni
  `star-segment` (interdits par `daily-sync.sh`) ; si Strava répond « Missing refresh credentials »
  ou un 401, écrire `ERREUR : jetons Strava absents ou expirés — relancer connect-strava dans
  une session interactive` et s'arrêter. Aucune donnée de santé (HRV, FC de repos, sommeil,
  readiness) : le bilan matinal est dit « indisponible — source Strava », jamais rempli. L'activité
  persistée porte `strava_activity_id` (`"s<ID>"`, préfixe du projet) et omet HRR/`splits`/D−.
  Marqueur « pas encore synchronisé » : l'absence de `strava_activity_id`. L'étape 2 s'applique
  avec cet identifiant (`download_fit.py --source strava`, flux par seconde, pas de `.fit`).
  Un « 429 » (limite de l'API Strava) n'est pas une erreur d'authentification : le noter dans
  `Alerte :` et s'arrêter proprement.
- **Pas de contrôle de premier démarrage** : le coach propose `/coach-setup` quand aucune
  configuration n'existe. **Ici, ne jamais le proposer** : personne ne peut répondre, et la
  proposition finirait dans la notification push. Travailler avec les défauts et le signaler
  en une ligne du résumé si la configuration manque.
- **Bilan matinal** : respecter `[health].morning_check`. À `off`, ne récupérer ni HRV, ni FC
  de repos, ni readiness — les fichiers correspondants ne sont alors pas attendus dans
  `medical/` et leur absence n'est pas un manque.
- **Idempotence** : ne récupérer que les dates dont le fichier MD manque dans `activities/`
  ou `medical/` (règle 1 de `garmin-sync-efficiency`). Une date déjà persistée n'est jamais
  re-synchronisée.
- **Glucides, hydratation, pesées (#39)** : `carbs_g`, `fluid_intake_ml`, `weight_pre_kg`,
  `weight_post_kg` ne viennent JAMAIS de Garmin — seule une déclaration de l'athlète les
  remplit (voir `agents/coach.md`). Ce skill tourne sans personne pour répondre : ne JAMAIS les
  demander, ne JAMAIS les deviner. Les laisser absents du bloc ```arc est le comportement
  normal d'une synchronisation headless, pas un manque à signaler.
- **Matériel (#133, source `garmin` uniquement)** : `gear_id` peut venir du matériel que la
  montre a attaché à la séance (`get_activity_gear`), et seulement si une puce du profil porte
  le `garmin: <uuid>` correspondant. Priorité : `gear_id` déjà déclaré par l'athlète (`/log`, chat) >
  matériel attaché par Garmin > paire `(par défaut)` calculée à la lecture. **Un `gear_id` déjà
  présent dans un fichier à fusionner est conservé tel quel** ; si Garmin indique une autre
  paire, le signaler dans la ligne `Alerte :`. Un matériel Garmin sans puce (ou ambigu, ou
  `(ignorée)`) n'est JAMAIS attribué (ni deviné, ni créé en headless) : `gear_id` reste absent,
  `gear_source: "garmin_unmapped"` est écrit (la séance n'est alors jamais créditée à la paire par
  défaut) et le résumé le mentionne — sauf s'il est `(ignorée)` : aucune alerte. Une seule mention
  par matériel et par run ; pour ne plus être alerté, l'athlète associe ou marque `(ignorée)` (le
  coach le propose en session interactive). **Aucune écriture côté Garmin en headless** : `add_gear_to_activity` ne
  s'appelle jamais ici, personne ne peut confirmer. Avec `[data].source = "intervals"`, aucun
  matériel par séance n'est lisible (voir `AGENTS.md`) : `gear_id` reste absent, jamais deviné.

- **Déclencheurs (`trigger=…`, facultatif)** : posés par `scripts/garmin_watch.py` quand la
  surveillance (`[sync].mode = "watch"`) a vu du neuf chez Garmin — `morning` (sommeil du
  jour calculé, bilan de santé absent) et/ou `activity:<id>` (séance dont aucun
  `activities/*.md` ne porte ce `garmin_activity_id`). C'est un **indice de priorité, pas
  une restriction** : la règle d'idempotence ci-dessus s'applique toujours à la fenêtre.
  Exception unique : une date déjà persistée **n'exclut pas** une séance `activity:<id>`
  désignée — une deuxième séance du même jour et du même type va dans
  `activities/YYYY-MM-DD_<type>_2.md` (puis `_3`…), jamais par-dessus la première. Sans
  cela la surveillance reverrait la même séance manquante à chaque passage.

## Déroulé

1. Déléguer à l'agent **`coach`** (outil `task`, prompt en anglais + « Respond in <langue des
   documents> ») la tâche suivante :
   > Load the `garmin-sync-efficiency` skill. For each of the last `lookback_days` days
   > (today included) — and, first, for every `activity:<id>` listed in `trigger` (if any),
   > even when its date already has a file: a second same-type session that day goes to
   > `activities/YYYY-MM-DD_<type>_2.md` — check whether `activities/YYYY-MM-DD_<type>.md` and
   > `medical/YYYY-MM-DD_health.md` exist AND are already synced — **not just present**
   > (`/log`, #67, may have created either file earlier the same day with only
   > athlete-declared fields, before any sync ran: see `garmin-sync-efficiency`'s "not yet
   > synced" marker). For each date that is missing OR not yet synced, fetch from the `garmin`
   > MCP server: activities (with splits and `recovery_hr_bpm`), sleep, HRV, training
   > readiness, resting HR / body battery. If a not-yet-synced file already exists for that
   > date, MERGE the fetched Garmin fields into it — same file, never a second one for the
   > same session — preserving every athlete-declared key it already carries (`carbs_g`,
   > `fluid_intake_ml`, `rpe`, `gear_id`, `gear_ids`, `weight_pre_kg`, `weight_post_kg` on an activity;
   > `pain` on a health file) exactly as declared. Persist each file immediately using the
   > workspace conventions (`AGENTS.md`: file names; load the `workspace-data-contract` skill
   > and open every file with its ```arc JSON block — `kind: activity` with
   > `garmin_activity_id`, `location` and `splits`, `kind: health` with `morning_check` set to
   > the configured mode. **Gear (#133, `[data].source = "garmin"` only):** for each activity
   > that is NEW in this run (never for a file that already carried its Garmin data —
   > `garmin-sync-efficiency`, one `get_activity_gear(activity_id)` call per new activity, no
   > more), pass the `uuid` values of its shoes (`gearTypeName` shoes only; ignore other gear types) to
   > `python3 scripts/arc_index.py gear-attribution --garmin-gear <uuid1,uuid2>` (add
   > `--chat-gear <gear_id>` when the file being merged already carries an athlete-declared
   > `gear_id`) and write the returned `gear_id` + `gear_source` into the block **as returned**
   > (when `gear_id` is null but `gear_source` is `garmin_unmapped`, write only `gear_source`; otherwise omit both). Never re-derive the rule yourself. The tool answers
   > "No gear data found…" when nothing is attached: then write nothing. Report a non-empty
   > `conflict` (Garmin says A, athlete says B — athlete kept) and any `unmapped_garmin` /
   > `ambiguous` result (NOT `ignored_garmin`: those stay silent) in your summary, once per gear, by gear NAME (from `get_activity_gear`'s `displayName`,
   > never a raw uuid), never attribute them. NEVER call `add_gear_to_activity` here. For TODAY's `medical/YYYY-MM-DD_health.md`, when `morning_check` is
   > `full` or `minimal`, record the gatekeeper `verdict` (`green`/`amber`/`red`) and
   > `verdict_reason` per the morning-check rules (`agents/medical.md`) — never leave it to
   > chance, step 4 below depends on it; document language from `config/workspace.toml` for
   > the prose below the block). Validate each file with `python3 scripts/arc_index.py
   > --validate <file>` and fix what it reports. Never dump raw JSON into the conversation.
   > Do not ask questions. Do not push anything to the Garmin calendar. Reply with: the list
   > of files created or merged, and a 5-line maximum summary (new activities:
   > type/distance/D+/HR avg/HRR; sleep score; HRV status vs baseline; readiness score; any
   > alert such as low HRV, poor sleep, HRR missing).
2. **Échantillons FIT (#42, best-effort)** : pour chaque activité running/trail dont un
   fichier a été créé à l'étape 1, télécharger son FIT : `python3
   skills/fit-download/scripts/download_fit.py <garmin_activity_id | intervals_activity_id | s<strava_activity_id>> --json` (sans
   `--output-dir` : la copie normalisée canonique doit atterrir dans `activities/fit/`
   du workspace pour être ingérée à l'étape suivante). **Best-effort et non bloquant** :
   un échec (tokens `garminconnect` absents/expirés, clé API intervals.icu refusée,
   `fitparse` non installé, FIT indisponible côté source) ne doit **jamais** faire échouer la synchronisation ni
   apparaître comme `ERREUR :` — seulement contribuer au segment « FIT non téléchargé
   (n séance(s)) » de la ligne `Alerte :` unique (voir plus bas) si au moins un
   téléchargement a échoué. Ignorer silencieusement les sports sans profil FIT utile
   (renforcement, vélo d'appartement…).
3. Réindexer le workspace pour le tableau de bord : `python3 scripts/arc_index.py`. La base
   est dérivée ; un échec ici ne bloque rien, mais contribue un segment à la ligne
   `Alerte :` unique. Un fichier resté `NON CONFORME` à la validation contribue de la même
   façon (« 1 fichier hors contrat — medical/2026-09-20_health.md »). Cette même commande
   ingère aussi les échantillons FIT déposés à l'étape 2 (`activity_sample`, aucune action
   supplémentaire requise).
3b. **Alerte d'usure des chaussures (#132) — une seule fois par franchissement, sans état.**
   Dresser la liste des séances running/trail/hiking **synchronisées pour la première fois dans
   CE run** : fichier d'activité créé à l'étape 1, ou fichier « pas encore synchronisé »
   (`/log`, #67) qui reçoit ses premiers champs Garmin. Une séance dont le fichier portait déjà
   ses données Garmin (simple re-fusion, second passage le même jour) n'en fait **jamais** partie.
   Lancer `python3 scripts/arc_index.py gear --activities <id1>,<id2>,…` avec, pour chacune, son
   `garmin_activity_id` (ou `intervals_activity_id`, `strava_activity_id`, ou à défaut le chemin `activities/….md`).
   Pour chaque paire du JSON qui porte `crossed_in_run: true`, ajouter le segment
   « Chaussures : <nom> a atteint son seuil (<distance_m/1000> km) » à la ligne `Alerte :`
   unique (concaténé avec ` ; `, jamais une ligne de plus). Méthode : `crossed_in_run` n'est vrai
   que si le cumul HORS ces séances était encore SOUS le seuil et que le cumul avec elles
   l'atteint — le franchissement est identifié par la séance, pas par une date : un second
   passage (le soir, ou une re-fusion) ne repasse pas ces identifiants et ne ré-émet rien, sans
   fichier d'état. Aucune séance de ce type, ou aucune paire franchie = rien à ajouter. Échec de
   la commande : ignorer silencieusement (non bloquant, jamais `ERREUR :`).
3c. **Alerte matériel hors chaussures (#134) — une seule fois par franchissement, sans état.**
   Dresser la liste des séances **de tout sport** (un vélo ou un renforcement comptent pour une
   frontale ou une ceinture cardio) **synchronisées pour la première fois dans CE run** — même critère
   qu'en 3b. **Aucune séance nouvelle = ne PAS lancer la commande et ne rien ajouter** (sans
   `--activities`, la sortie ne porte aucun `crossed_in_run` : rien n'est jamais ré-émis).
   Sinon lancer `python3 scripts/arc_index.py equipment --activities <id1>,<id2>,…` (mêmes
   identifiants qu'en 3b) et, pour chaque objet portant `crossed_in_run: true` (déclencheur km/h/séances
   franchi par ces séances), ajouter « Matériel : <nom> a atteint son seuil (<déclencheur franchi>) » à
   la ligne `Alerte :` unique (` ; `, jamais une ligne de plus). **Les déclencheurs en jours ne
   produisent AUCUNE alerte ici** : ils ne dépendent d'aucune séance et aucun horodatage fiable du
   dernier passage réussi n'existe (`daily-sync.sh` n'écrit que des journaux quotidiens, pas un
   marqueur de succès ; l'absence de fichier du jour ne prouve rien avec `morning_check = "off"` ni
   quand `/log` a déjà créé le fichier) — sans cela ils seraient ré-émis à chaque passage ou perdus.
   Ils apparaissent dans le tableau de bord, `/week`, le rapport hebdomadaire et les contrôles
   avant séance du coach. N'utiliser jamais `--last-pass` ici. Sans état persistant, sans fichier
   écrit ; les objets sans déclencheur ne remontent jamais (aucun seuil inventé). Aucune donnée de
   santé ; non soumis à `[health].morning_check`. Échec de la commande : ignorer silencieusement.
4. **Garde-fou r5, bilan rouge (#52/#53) — jamais d'écriture de plan ni de push ici.** Si
   un `medical/YYYY-MM-DD_health.md` persisté à l'étape 1 porte `verdict: "red"`, chercher
   dans `planning/` une semaine (`kind: week`) dont une séance de qualité (intensité
   `tempo`/`threshold`/`vo2max`/`race`) tombe ce jour-là ou le lendemain. Si oui, lancer
   `python3 scripts/arc_guardrails.py check --week <fichier> --today <date>` pour confirmer
   `r5_quality_after_red`. Ce skill ne modifie **jamais** le plan ni le calendrier Garmin
   (règle inchangée, voir étape 1) : écrire à la place une `decision`
   (`workspace-data-contract` skill) avec `outcome: "proposed"` — jamais `applied`, aucune
   décision n'a été appliquée en headless — `trigger: "guardrail"`,
   `rule_ids: ["r5_quality_after_red"]`, `session_ref`, puis la valider
   (`python3 scripts/arc_index.py --validate <fichier decision>`). `date` du fichier `decision`
   = le jour auquel elle s'applique (celui de la séance flaguée, donc potentiellement DEMAIN
   quand la séance de qualité tombe le lendemain plutôt qu'aujourd'hui même — voir ci-dessus).
   Ne rien ajouter à la ligne `Alerte :` pour cette raison précise : l'étape 5 la reprendra dans
   la ligne `Pourquoi :`, jamais les deux à la fois (une même information ne doit apparaître
   qu'une fois dans la sortie obligatoire). Si une session interactive ultérieure confirme ou
   change l'alternative, elle écrit une NOUVELLE `decision` (`outcome: "applied"`,
   `supersedes: <chemin de la decision proposed ci-dessus>`) — ce skill headless ne le fait
   jamais lui-même.
5. **Raison de l'ajustement pour la notification (#56).** Interroger le journal des décisions
   pour AUJOURD'HUI **et** DEMAIN — `date` d'une `decision` de l'étape 4 est celle de la séance
   qu'elle concerne, pas forcément celle du run :
   `python3 scripts/arc_index.py decisions --date <date du jour> --active`
   `python3 scripts/arc_index.py decisions --date <date du lendemain> --active`
   (chaque appel à `decisions` réindexe le workspace lui-même avant de répondre — inutile
   d'attendre l'étape 3 pour que `decision`/`decision_rule` soient à jour ; l'étape 3 reste utile
   pour le tableau de bord, pas un préalable à celle-ci). Un résultat non vide sur L'UNE OU
   L'AUTRE requête (`outcome` `"proposed"` ou `"applied"`, que la décision vienne d'être écrite à
   l'étape 4 ou d'une session interactive plus tôt dans la journée) alimente la ligne
   `Pourquoi :` de la sortie obligatoire ci-dessous, à partir de son champ `summary` — s'il y a un
   résultat sur les deux requêtes, prendre la décision la plus récente (`created_at`) entre les
   deux. **Jamais l'inverse** : pas de décision trouvée ni aujourd'hui ni demain = pas de ligne
   `Pourquoi :`, ne jamais en inventer une à partir d'une simple impression ou d'une alerte non
   tracée en `decision`. Un échec de ces commandes (index absent, erreur) ne bloque rien :
   traiter comme « aucune décision trouvée ».
6. Si l'agent `coach` échoue (MCP indisponible, tokens Garmin expirés…), ne rien inventer :
   le résumé doit contenir `ERREUR : <cause>` (ex. « tokens Garmin expirés — relancer
   `uv run garmin-mcp-auth` »).

## Sortie OBLIGATOIRE (dernier élément de la réponse)

Terminer la réponse par un bloc de code clôturé avec le langage `resume`, **5 lignes maximum**,
dans la langue des documents, sans Markdown à l'intérieur. C'est ce bloc que
`scripts/daily-sync.sh` extrait mot pour mot pour la notification push.

**Une seule ligne `Alerte :` au total**, jamais une par source : si plusieurs
alertes s'appliquent en même temps (FIT non téléchargé, fichier hors contrat, chaussure
ayant atteint son seuil — étape 3b, matériel Garmin non associé ou en désaccord avec la
déclaration de l'athlète, #133 — « Matériel : Brooks Ghost non associée (à lier via le coach) »
ou « Matériel : Garmin indique Nike Pegasus, ta déclaration (Salomon S/Lab) est conservée »…),
les concaténer sur cette même ligne, séparées par ` ; ` — le budget de 5
lignes ne laisse la place à aucune ligne `Alerte :` supplémentaire. `Alerte :
aucune` seulement quand aucune des sources ci-dessus n'a de signal à ce
moment-là. **La séance de qualité à revoir après un verdict rouge (étape 4)
n'est PAS une source de cette ligne** — elle est portée par la ligne
`Pourquoi :` ci-dessous (son `summary`), jamais dupliquée ici.

````
```resume
Séances : 1 nouvelle — trail 12,3 km / 480 m D+ / FC moy 148 / HRR 28 bpm (2026-09-20)
Sommeil : 7 h 42, score 81
HRV : 62 ms — équilibré (baseline 58-66)
Readiness : 74
Alerte : aucune
```
````

**Ligne `Pourquoi :` (#56) — remplace la ligne `Alerte :`, ne s'y ajoute jamais.**
Le budget reste à 5 lignes : quand l'étape 5 a trouvé une `decision` active
(`outcome` `"proposed"` ou `"applied"`) pour aujourd'hui OU pour demain, la
5<sup>e</sup> ligne change d'étiquette — `Pourquoi :` au lieu d'`Alerte :` —
plutôt que d'en ajouter une sixième. Contenu : le champ `summary` de cette
décision, tronqué à environ 12 mots en gardant la règle ou la métrique qu'il
cite (`rule_ids`/le chiffre qui a déclenché la décision) ; s'il y a des
décisions actives sur les deux dates, prendre la plus récente (`created_at`).
Si d'autres alertes s'appliquaient par ailleurs (FIT non téléchargé, fichier
hors contrat…), les concaténer à la suite, séparées par ` ; `, exactement
comme elles l'auraient été derrière `Alerte :` — cette ligne ne perd aucune
information, elle change seulement d'étiquette et gagne la raison en tête.
Aucune décision active ni aujourd'hui ni demain = ligne `Alerte :` inchangée,
jamais de `Pourquoi :` inventée à partir d'une simple alerte ou d'une
impression non tracée en `decision` (étape 5).

````
```resume
Séances : à jour
Sommeil : 5 h 10, score 41
HRV : 31 ms — effondrée (baseline 48-74)
Readiness : 22
Pourquoi : verdict rouge (HRV effondrée) — séance VO2max à revoir (r5_quality_after_red)
```
````

Si aucune date ne manquait : `À jour — aucune nouvelle donnée Garmin (dernière séance : YYYY-MM-DD)`
en ligne unique — SAUF si l'étape 5 a trouvé une décision active : la ligne `Pourquoi :`
s'ajoute alors en 2<sup>e</sup> ligne (toujours ≤ 5 au total), elle n'est jamais perdue
faute de nouvelles données Garmin.
Si une étape a échoué : première ligne `ERREUR : <cause courte>`.
