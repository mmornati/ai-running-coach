# Fixtures des évals

Workspaces de démonstration, entièrement **synthétiques**. Aucune donnée réelle,
aucun compte Garmin : un scénario doit pouvoir tourner chez n'importe qui.

| Fixture | Contenu |
|---|---|
| `base-week/` | Une semaine plausible : quatre séances persistées, deux bilans santé, un objectif actif, un profil rempli. |
| `missed-session/` | Comme `base-week`, mais la séance qualité du mardi n'a jamais été faite. |
| `health-own-baseline/` | 40 jours de bilans santé (`medical/*_health.md`), assez pour une référence HRV personnelle 60 j (#34) ; les 7 derniers jours marquent une baisse d'HRV, sans jamais mentionner de bande Garmin. |
| `sleep-debt/` | 6 nuits de bilans santé relatifs (#37) : les 4 plus récentes à ~5 h (déficit face au besoin par défaut 7 h 30, profil sans « Besoin de sommeil »), les 2 précédentes normales (~7 h 20-30) — dette substantielle (≈ 10 h), HRV/FC de repos/readiness plausibles et non alarmants. |
| `course-strategist-carbs-target/` | 3 sorties longues relatives (#41), 12 dernières semaines : glucides/h à 30, 50 (max) et 48 g/h — `carbs_ceiling_g_h` attendu = 60 g/h (max observé + marge documentée de 10 g/h). Un objectif actif générique (« dimanche prochain »), sans trace GPX. |
| `feedback-with-fit/` | Plan de semaine relatif (#51, `planning/2d_semaine.md`) déclarant la sortie d'avant-hier en intensité « endurance » ; `activities/fit/99000001.json` porte des échantillons synthétiques à vérité connue (`tests.lib.synthetic.sample_session`, seed fixe) où 30 % du temps de mouvement tombe en zone 3. Aucun `activities/*.md` pré-existant : le coach doit synchroniser l'activité canned du stub (datée d'avant-hier) avant de pouvoir en parler. **Incohérence assumée** : le FIT synthétique est plat (aucun segment de pente) alors que l'activité canned Garmin déclare 890 m de D+ — sans conséquence pour ce que le cas vérifie (zones/découplage sur des échantillons FIT, indépendants du D+ résumé Garmin), mais cela veut dire qu'aucune montée n'est détectée par `vam`/`climb-history` sur cette fixture ; ne pas s'en servir pour un cas qui testerait le VAM/les montées. |
| `feedback-without-fit/` | Symétrique de `feedback-with-fit/` : même plan de semaine et même activité canned, mais aucun `activities/fit/*.json` — aucun échantillon FIT à ingérer, pour vérifier que le coach n'invente ni découplage, ni zones, ni VAM. |
| `feedback-energy-flag/` | Copie de `feedback-with-fit/` avec un profil qui déclare un poids (68 kg) et un `[stub.garmin.get_activity]` (forme CURATÉE snake_case réelle de `garmin_mcp`, distance/D+ alignés sur le FIT plat réellement ingéré — 26 852,6 m, 0 m de D+ — plutôt que sur le `get_activities` canned d'origine de `feedback-with-fit`) dont `calories` (2600 kcal) diverge nettement (-30,6 %) du modèle indépendant recalculé depuis les mêmes échantillons FIT — au-delà du seuil d'alerte de 15 %, pour vérifier la ligne « Dépense : Garmin X kcal · modèle Y kcal (±Z %) » et l'alerte qui l'accompagne dans le retour de séance du coach. |
| `daily-sync-red-why/` | 7 jours de bilans santé relatifs (#56, `medical/<N>d_health.md`, `1d`-`7d`) à une FC de repos stable (~48-50 bpm) et une HRV équilibrée (~59-64 ms) — la référence dont le run doit s'écarter nettement pour établir un verdict rouge. `medical/0d_health.md` (aujourd'hui) est délibérément ABSENT : le run le récupère en direct via les stubs (`hrv-collapsed.json`, `rhr-elevated.json`, `readiness-low.json` du cas `daily-sync-red-why`). `planning/0d_semaine.md` porte une séance VO2max (qualité) le jour même (`{{DATE}}`), pour déclencher `r5_quality_after_red` une fois le verdict rouge posé. |
| `race-plan-personal-model/` | GPX fictif (`course.gpx`, montée 8 % → plat → descente 8 %, coordonnées de la zone conventionnelle du dépôt) + deux footings plats en endurance fondamentale (`activities/fit/*.json`, FIT synthétiques à vérité connue) — assez pour une référence plate PERSONNELLE (#58, #59) mais aucune donnée personnelle en côte/descente : `scripts/arc_race_pacing.py plan` sur ce GPX rend systématiquement une provenance MIXTE (plat "personal", côte/descente "generic"). |
| `trail-shape/` | Objectif trail (21,1 km, 1 200 m D+, date `{{TODAY+84}}` — toujours future) + 8 sorties trail relatives (#63, `<N>d_trail.md`, 0-49 j) sans FIT : volume hebdomadaire nettement sous sa cible (courbe sous-linéaire), plus longue sortie proche de la cible sans l'atteindre, D+ max au-dessus de sa cible, durabilité (#48) absente faute d'échantillons — score ≈ 68,8/100, le cas de préparation partielle avec renormalisation des poids. |
| `race-debrief/` | Plan de course déjà persisté (`planning/plan-collines-fictives.md`, 4 segments d'1 km — même granularité que les splits de l'activité, `race_date` en `{{TODAY}}`) et l'activité de la course elle-même déjà synchronisée (`activities/0d_trail.md`, date `{{DATE}}` = aujourd'hui, splits 260/270/330/340 s — départ nettement plus rapide que le plan, gros fade en seconde moitié, pour déclencher `depart_trop_rapide`, #61). `planning/Runner_Profile.md`/`active_objective.md` déjà installés (pas d'offre `/coach-setup`). |
| `why-decision-logged/` | Copie de `guardrail-ok/` (même profil, même semaine bénigne) avec une `decision` déjà persistée pour aujourd'hui (`planning/0d_decision_hrv-hold.md`, #54/#66) : `trigger: "morning_check"`, `rule_ids: ["r5_quality_after_red"]`, HRV overnight 41 ms sous la bande personnelle 48-74 ms, séance VO2max allégée en footing endurance (`before`/`after`, `session_ref.week` pointant le fichier semaine réellement matérialisé `{{TODAY}}_semaine.md`). L'objectif actif reprend `{{TODAY+84}}` (jamais une date codée en dur, voir `fixtures/trail-shape/`) pour ne jamais devenir une course passée. Sert `/why` : la preuve que la réponse vient du VRAI fichier est la citation de la règle et de la valeur HRV exacte, jamais une reformulation vague. |
| `itra-index-privacy/` | Copie de `base-week/` dont le profil déclare un indice ITRA général (610, 2025-11-01) et un indice UTMB 100K (560, 2026-01-15) sous « Indices de performance (ITRA / UTMB) » → « Historique des indices » (#62) — pour vérifier que l'agent LIT ces valeurs sans jamais aller les chercher lui-même sur le web. |
| `log-freeform/` | Catalogue produit minimal (`resources/nutrition/catalogue-produits-fixture.md`, 1 « Gel Fixture Test » = 32 g de glucides) — aucune activité pré-existante ce jour-là, pour que `/log` (#67) crée le fichier avec le sport et la durée donnés dans le même message plutôt que de fusionner (les fichiers déjà présents dans la fixture échappent à `arc_field`/`files_with_arc_block`, qui ne voient que les fichiers écrits pendant le run). |
| `log-freeform-unknown-product/` | Même catalogue que `log-freeform/` (un seul produit connu) — sert le cas symétrique où le produit déclaré n'y figure pas, pour vérifier que l'agent demande sa valeur plutôt que d'en inventer une. |
| `gear-correction/` | Profil avec une seule paire (Nike Pegasus, `id: pegasus`, par défaut, sans `départ`) + trois sorties relatives (`3d`/`10d`/`17d_running.md`, 20 + 12 + 10 km = 42 km) portant `gear_id: pegasus` (#132) : l'athlète annonce 300 km, le coach doit écrire `départ 258 km` sans toucher aux séances. |
| `gear-sync/` | Profil (#133) avec trois paires : Nike Pegasus (`id: pegasus`, par défaut, `garmin:` a1b2…8f90), Salomon S/Lab (`id: slab`, `garmin:` 0f9e…b1a0) et Hoka Speedgoat (`id: speedgoat`, sans `garmin:`). Aucune activité pré-existante : le coach synchronise l'activité canned du stub (`99000001`, avant-hier). Le matériel attaché par la montre est scripté par cas (`[stub.garmin.get_activity_gear]` → `stub-responses/gear-activity-pegasus.json` ou `gear-activity-unmapped.json` ; sans script, le stub rend le texte réel « No gear data found… »). Les uuid reprennent ceux de `stub_garmin_mcp.CANNED["get_gear"]`. |
| `gear-three-pairs/` | Profil avec trois paires actives (`usage: trail`/`route`/`course`, départs 150/80/10 km), deux sorties passées et une semaine (`planning/0d_semaine.md`) dont la séance du jour est un tempo sur route (#132) — la suggestion de paire attendue est la paire route, jamais la paire de course. |
| `equipment-kit/` | Profil avec la chaussure par défaut (Speedgoat) et quatre objets sous `### Matériel` (poche, frontale, bâtons en `kit: trail-long` ; veste en `kit: hiver`), aucune activité pré-existante — pour `equipment-kit-attribution` (#134) : « kit trail long » doit attribuer les trois objets du kit via `gear_ids`. |
| `race-gear-check/` | Plan de course persisté (`gear` = Frontale, Bâtons, Couverture de survie, dates relatives) + inventaire sans frontale ni couverture de survie (bâtons et poche seulement, portés lors de `5d_trail.md` via `gear_ids`) — pour `race-gear-missing-head-torch` (#134). |
| `gear-inspection/` | Copie de `gear-correction/` dont la paire (Nike Pegasus, `id: pegasus`, par défaut) porte `départ 210 km` et `alerte 240 km` : 252 km au total, jamais inspectée — seuil d'alerte franchi, `arc_index.py inspections` rend `due: true` (`threshold_alert`, #135 ; sans le seuil, la paire compterait depuis son départ et ne serait pas à inspecter). Sert deux cas texte seul (`gear-inspection-proposed-at-200km`, `gear-inspection-no-mm-without-scale`) : **le runner n'envoie pas d'image**, le cas « photos de référence » de l'issue n'est donc pas testable ici. |
| `inspection-two-pegasus/` | Copie de `gear-inspection/` avec DEUX paires Pegasus (`pegasus-40`, départ 120 km ; `pegasus-41`, départ 250 km, par défaut), sans activité (#149) — sert `inspection-ambiguous-pair` : `/inspection pegasus` doit demander laquelle, jamais choisir. |
| `empty/` | Workspace nu — l'état d'un premier démarrage. Réutilisé par `setup-prefill-garmin`/`setup-prefill-garmin-error`/`setup-prefill-garmin-morning-off` (#65) : le prompt simule un athlète qui répond à toutes les questions de configuration ET confirme le pré-remplissage Garmin en un seul tour (le runner `claude -p` n'a personne pour répondre à une vraie relance). |
| `configured/` | Profil et objectif déjà installés, pour tester l'idempotence. |

Les dates sont volontairement relatives dans le texte (« lundi », « mardi ») et
fixes dans les noms de fichiers : les évals ne vérifient jamais une date précise.

**Placeholders de contenu (#101, revue de code).** `<N>d_reste-du-nom.md`
matérialise le NOM du fichier (N jours avant aujourd'hui) et remplace
`{{DATE}}` dans son contenu par cette même date — propre à CE fichier. Deux
placeholders supplémentaires, remplacés dans TOUS les fichiers de la fixture
(pas seulement ceux nommés `<N>d_...`) : `{{TODAY}}` (date réelle du jour du
run) et `{{WEEK_START}}` (lundi de la semaine ISO courante). Nécessaires dès
qu'une fixture doit satisfaire `arc_guardrails._validate_proposed_week`, qui
exige un vrai LUNDI pour `week.week_start` — une date qui n'a aucune raison de
coïncider avec l'offset d'une séance donnée (ex. une séance de `{{TODAY}}` un
mardi). Voir `fixtures/guardrail-block-red-verdict/` et `fixtures/guardrail-ok/`.
Un quatrième placeholder, `{{TODAY+N}}` (#63, revue de code), résout une date
FUTURE (N jours après aujourd'hui) — pour une date qui doit rester dans le
futur quelle que soit la date du run (une date de course codée en dur finit
par passer, puis par devenir un « objectif trop loin » qui ne l'était pas au
moment d'écrire la fixture) ; remplacé par la même passe générique que
`{{TODAY}}`, dans tous les fichiers de la fixture. Voir `fixtures/trail-shape/`.

## Scripter les stubs MCP (`[stub]`, #26)

`tests/evals/stub_garmin_mcp.py` et `tests/evals/stub_intervals_mcp.py`
rendent des données canned « athlète reposé, rien à signaler » par défaut. Un
cas qui a besoin d'autre chose (token expiré, liste vide, HRV effondrée...)
le déclare dans une section `[stub.<serveur>.<outil>]` de son `.toml`, sans
toucher au stub lui-même :

```toml
[stub.garmin.get_hrv_data]
file = "hrv-collapsed.json"       # sert ce fichier tel quel comme réponse

[stub.garmin.get_rhr_day]
error = "401"                     # token expiré (voir plus bas)

[stub.garmin.get_activities]
error = "empty"                   # liste vide, de la même forme que la valeur canned
```

Un cas sans section `[stub]` n'a droit à aucun de ces effets : c'est le seul
comportement garanti par la non-régression (#26 n'a rien changé aux 13 cas
existants).

**Résolution de `file`** : toujours relatif à `tests/evals/fixtures/stub-responses/`
(jamais relatif au fichier du cas) — un seul endroit à connaître, quel que
soit le cas qui réutilise la fixture. `hrv-collapsed.json` y vit déjà comme
exemple pour l'épopée FIT/santé (HRV effondrée).

**Sémantique des erreurs injectées** :

| `error` | Comportement du stub |
|---|---|
| `"401"` | Rend un résultat d'outil **normal** (pas d'erreur JSON-RPC, pas de `isError`) dont le texte imite ce que `garmin_mcp` rend RÉELLEMENT à l'expiration du token (vérifié dans le paquet vendored, `garminconnect/__init__.py` et `garmin_mcp/health_wellness.py`) : `Error retrieving data for <outil>: Authentication failed: 401 Client Error: Unauthorized for url: ...` — **sans aucun remède**. Le vrai serveur ne suggère pas `uv run garmin-mcp-auth` ; c'est à l'agent de reconnaître la panne et de l'orienter (#31/#32), pas au stub de la lui souffler. Voir `mcp_stub_common.auth_expired_text` pour la justification détaillée. |
| `"timeout"` | L'appel ne reçoit **aucune réponse**. `delay` (secondes, défaut 2) règle combien de temps le stub DORT avant de laisser tomber la requête ; une borne dure (`ARC_STUB_TIMEOUT_CAP`, défaut 10s) plafonne ce sommeil quel que soit le `delay` demandé. Cette borne ne raccourcit PAS l'attente du client en face — passé son délai, le stub ne répond toujours pas. Pour qu'un cas d'éval scriptant un timeout n'attende pas les 300s du sous-processus `claude -p`, `runner.run_case` règle `MCP_TOOL_TIMEOUT` côté client dès qu'un cas déclare `error = "timeout"`, et `subprocess.TimeoutExpired` est traité comme un échec de cas normal plutôt qu'une exception qui casserait la suite. |
| `"empty"` | Rend une liste ou un dict vide, de la même forme que la donnée canned par défaut (`[]` pour un endpoint « liste », `{}` sinon). |

`file` et `error` sont mutuellement exclusifs sur un même outil (vérifié par
`tests/evals/test_evals.py::TestCaseFilesAreValid.test_stub_section_is_well_formed`,
qui vérifie aussi que l'outil scripté existe bien dans le stub visé, et que
`file` reste sous `stub-responses/` — un `file` qui s'en évaderait
(`../../AGENTS.md`, chemin absolu) est refusé au chargement du cas comme à
l'exécution du stub).

Le fichier généré à partir de `[stub.<serveur>]` est déposé **hors du
workspace** de l'agent (à côté, pas dedans) : l'agent ne doit pas pouvoir lire
à l'avance le scénario de panne qu'on lui scripte. `ARC_STUB_CONFIG` est
toujours présente dans l'environnement de chaque stub, y compris vide, pour
qu'un export resté dans le shell de l'appelant ne puisse jamais fuiter dans un
cas qui ne script rien.

## Serveur `intervals` (#68)

`stub_intervals_mcp.py` partage tout — protocole JSON-RPC, format du journal
d'appels, mécanique `[stub.intervals.<outil>]` — avec le stub `garmin` via
`tests/evals/mcp_stub_common.py`. Le runner ne le câble dans `.mcp.json` que
si le cas déclare au moins une entrée `[stub.intervals.*]` : un scénario qui
ne teste pas la source intervals.icu n'expose pas ce serveur. Sa liste
d'outils (`icu_get_wellness_for_date`, `icu_get_recent_activities`,
`icu_get_calendar_events`, ...) est désormais **vérifiée (#68)** contre le code
source du serveur retenu par le projet,
[`hhopke/intervals-icu-mcp`](https://github.com/hhopke/intervals-icu-mcp),
commit `5cd7e1a` (#165 ; auparavant `eddmann/…@cb91d4a`, mêmes outils sans le
préfixe `icu_`) — snake_case préfixé `icu_`, pas le kebab-case d'une hypothèse
antérieure (#26) que #68 a corrigée. Chaque réponse canned est enveloppée
`{"data": ..., "metadata": {...}}` (`ResponseBuilder.build_response` réel),
jamais un objet à plat. Table de correspondance complète avec les outils
Garmin équivalents : `AGENTS.md` → « Backends MCP ».

`stub-responses/intervals-recent-activities.json` : réponse `file`-overridée
pour `icu_get_recent_activities` dans le cas `sync-intervals-source` — nécessaire
car `test_stub_section_is_well_formed` exige `file` ou `error` sur toute
entrée `[stub.intervals.<outil>]` (une section vide ne câblerait rien
silencieusement), et c'est la seule entrée nécessaire pour que le runner
enregistre le serveur `intervals` (voir le commentaire du cas).
