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
  (défaut : 2), `[health].morning_check` (voir ci-dessous).
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
- **Matériel, glucides, hydratation, pesées (#39)** : `gear_id`, `carbs_g`, `fluid_intake_ml`,
  `weight_pre_kg`, `weight_post_kg` ne viennent JAMAIS de Garmin — seule une déclaration de
  l'athlète les remplit (voir `agents/coach.md`). Ce skill tourne sans personne pour répondre :
  ne JAMAIS les demander, ne JAMAIS les deviner. Les laisser absents du bloc ```arc est le
  comportement normal d'une synchronisation headless, pas un manque à signaler.

## Déroulé

1. Déléguer à l'agent **`coach`** (outil `task`, prompt en anglais + « Respond in <langue des
   documents> ») la tâche suivante :
   > Load the `garmin-sync-efficiency` skill. For each of the last `lookback_days` days
   > (today included), check whether `activities/YYYY-MM-DD_<type>.md` and
   > `medical/YYYY-MM-DD_health.md` exist. For missing dates only, fetch from the `garmin` MCP
   > server: activities (with splits and `recovery_hr_bpm`), sleep, HRV, training readiness,
   > resting HR / body battery. Persist each file immediately using the workspace conventions
   > (`AGENTS.md`: file names; load the `workspace-data-contract` skill and open every file
   > with its ```arc JSON block — `kind: activity` with `garmin_activity_id`, `location` and
   > `splits`, `kind: health` with `morning_check` set to the configured mode. For TODAY's
   > `medical/YYYY-MM-DD_health.md`, when `morning_check` is `full` or `minimal`, record the
   > gatekeeper `verdict` (`green`/`amber`/`red`) and `verdict_reason` per the morning-check
   > rules (`agents/medical.md`) — never leave it to chance, step 4 below depends on it; document
   > language from `config/workspace.toml` for the prose below the block). Validate each file
   > with `python3 scripts/arc_index.py --validate <file>` and fix what it reports. Never dump
   > raw JSON into the conversation. Do not ask questions. Do not push anything
   > to the Garmin calendar. Reply with: the list of files created, and a 5-line maximum
   > summary (new activities: type/distance/D+/HR avg/HRR; sleep score; HRV status vs
   > baseline; readiness score; any alert such as low HRV, poor sleep, HRR missing).
2. **Échantillons FIT (#42, best-effort)** : pour chaque activité running/trail dont un
   fichier a été créé à l'étape 1, télécharger son FIT : `python3
   skills/fit-download/scripts/download_fit.py <garmin_activity_id> --json` (sans
   `--output-dir` : la copie normalisée canonique doit atterrir dans `activities/fit/`
   du workspace pour être ingérée à l'étape suivante). **Best-effort et non bloquant** :
   un échec (tokens `garminconnect` absents/expirés, `fitparse` non installé, FIT
   indisponible côté Garmin) ne doit **jamais** faire échouer la synchronisation ni
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
alertes s'appliquent en même temps (FIT non téléchargé, fichier hors contrat…),
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
