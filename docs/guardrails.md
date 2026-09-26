# Les garde-fous (`arc_guardrails.py`)

La progression d'entraînement est confiée au LLM (l'agent `coach`). Principale
critique adressée aux coachs IA : une progression trop agressive — des
blessures ont été rapportées avec des outils comparables. `scripts/
arc_guardrails.py` est un second avis **purement calculé**, déterministe et
testé, que le coach consulte avant d'écrire une semaine et avant de la pousser
au calendrier Garmin (câblage dans l'agent : [#53](https://github.com/mmornati/ai-running-coach/issues/53),
suit ce moteur).

## Les sept règles

| id | vérifie | sévérité par défaut |
|---|---|---|
| `r1_acwr_projected` | ACWR (charge aiguë/chronique) **projeté**, maximum sur la semaine proposée | `warn` |
| `r2_weekly_volume_jump` | hausse de la durée (+ distance en `road`) hebdomadaire planifiée | `warn` |
| `r3_weekly_elevation_jump` | hausse du D+ hebdomadaire planifié (trail seulement) | `warn` |
| `r4_monotony_projected` | monotonie de Foster **projetée** sur la semaine proposée | `warn` |
| `r5_quality_after_red` | séance de qualité le jour même ou le lendemain d'un verdict santé rouge | `block` |
| `r6_long_run_share` | part de la plus longue sortie dans le volume hebdomadaire | `warn` |
| `r7_consecutive_quality` | deux séances de qualité le même jour ou sur deux jours consécutifs | `warn` |

Seuils et sévérités : `[guardrails]` de `config/workspace.toml`, voir
[Configuration](configuration.md#les-garde-fous-guardrails).

!!! warning "R1 (ACWR) est `warn`, pas `block`, par défaut"
    Voir [Sources](#sources) ci-dessous pour le détail des réserves
    scientifiques. Remettez `severity_r1_acwr_projected = "block"` dans
    `[guardrails]` si vous préférez la fermeté.

## Ce qui n'est jamais bloqué

- **Historique réel insuffisant** — deux gardes distinctes :
    - moins de **84 jours** d'historique réel avant `week_start`
      (`MIN_HISTORY_DAYS_FOR_PROJECTION`, 2× la fenêtre de condition de
      42 jours) : R1 et R4 sont **sautées** (`reason_code:
      "insufficient_history"`), jamais évaluées sur un démarrage à froid du
      modèle impulsion-réponse de Banister — sans cette garde, un nouvel
      utilisateur avec 1 à 8 semaines d'historique lirait un ACWR de 3,18 à
      1,34 sur une semaine pourtant parfaitement stable ;
    - moins de **4 séances** de la famille course dans la semaine proposée :
      R6 est sautée (`reason_code: "too_few_sessions"`) — avec 3 séances ou
      moins, la plus longue dépasse presque toujours 35 % par pure
      construction arithmétique.
- **Référence sans historique de la bonne famille** (R2/R3 : la fenêtre de
  référence n'a aucune activité de la famille course, ex. une semaine 100 %
  vélo) : sautées avec `reason_code: "no_reference"`.
- **Séance prescrite en distance sans allure récente pour estimer sa durée**
  (R1/R2/R4) : sautées avec `reason_code: "missing_planned_duration"` — voir
  [Séances prescrites en distance](#seances-prescrites-en-distance) ci-dessous.
- **Semaine de course** (date de `planning/active_objective.md` dans la
  semaine proposée) : R1, R2, R3, R4, R6 et R7 sont sautées
  (`reason_code: "race_week"`) — l'objectif est d'éviter une progression trop
  agressive à l'entraînement, jamais de bloquer la course elle-même. R5 reste
  active (une alerte santé reste pertinente juste avant une course).
- **Semaine qui SUIT une course** (récupération) : R1 ne compare pas l'ACWR
  projeté au seuil brut, mais à un scénario « repos complet » calculé sur la
  même semaine (mêmes séances mises à zéro) — elle ne bloque QUE si la semaine
  proposée aggrave le ratio par rapport à ce repos complet
  (`reason_code: "acwr_elevated_by_recent_load"` sinon). Une fatigue
  résiduelle de course, seule, ne bloque jamais une semaine de récupération.
- **Bilan matinal désactivé** (`[health].morning_check = "off"`) : R5 est
  sautée (`reason_code: "health_check_disabled"`) — aucune donnée de santé
  n'est de toute façon récupérée dans ce mode.
- **Séances annulées, déplacées ou manquées (`status`), ou de repos** :
  exclues de toutes les règles.
- **Semaine de récupération (deload)** : R2/R3 ne réagissent qu'à une
  **hausse** — une baisse de volume ne déclenche jamais rien.
- **Sport hors périmètre d'une règle** : R3 (D+) ne s'applique qu'en trail
  (`reason_code: "not_applicable_sport"`).

## Approximation de charge d'une séance planifiée

Une séance **planifiée** n'a pas de FC : impossible d'y calculer un vrai TRIMP
(`arc_metrics.trimp_banister`). R1/R4 projettent donc une charge à partir de
l'intensité prescrite (`rest` → 0 … `race` → 10 sur l'échelle RPE 0-10),
passée dans **exactement la même formule** que le repli session-RPE de
`arc_metrics.session_load`, pour rester sur la même échelle que la charge
réelle déjà indexée. C'est une approximation d'une approximation, jamais
présentée comme mesurée — voir `arc_guardrails.ASSUMPTIONS["projected_load"]`.

Chaque jour de la semaine proposée est apparié séance par séance à une
activité réelle déjà indexée (même logique que `arc_metrics.week_compliance`)
: une séance déjà réalisée compte sa charge RÉELLE, une séance encore prévue
compte sa charge PROJETÉE — plusieurs séances le même jour sont **sommées**,
jamais l'une écrasant l'autre. Un jour déjà **passé** (avant `--today`) sans
activité réelle appariée compte **0**, jamais la charge projetée : un jour
manqué sans donnée ne doit jamais recevoir le bénéfice d'une charge qui n'a
peut-être jamais eu lieu.

## Séances prescrites en distance

Une séance planifiée seulement en distance (`planned_distance_m`, sans
`planned_duration_s` — ex. « Sortie longue 25 km / 900 m D+ ») ne compte
jamais une durée/charge de zéro : sa durée est **estimée** depuis l'allure
course récente de l'athlète (médiane sur 90 jours, famille course à pied) et
l'équivalence D+/plat déjà utilisée pour les prédictions
(`arc_metrics.TRAIL_FLAT_M_PER_M_DPLUS`). Les dates estimées sont exposées
dans `context.distance_only_sessions_estimated`, pour transparence. Sans
aucune allure récente disponible, R1/R2/R4 sont sautées plutôt que d'inventer
une estimation sans donnée — voir
`arc_guardrails.ASSUMPTIONS["distance_only_estimate"]`.

## Sources

Chaque règle cite sa source dans son champ `source` (littérature vérifiable
pour R1/R4/R7 — Gabbett 2016, Foster 1998, Seiler & Kjerland 2006 — ou
« convention du projet » explicite pour R2/R3/R6, faute de source unique et
consensuelle). Le détail complet, avec les citations complètes, est dans
`scripts/arc_guardrails.py::ASSUMPTIONS`.

!!! warning "Réserves scientifiques sur R1 (ACWR)"
    Les seuils de Gabbett (2016) viennent d'études en **sports collectifs**
    (rugby, football australien), avec des moyennes glissantes **simples**
    sur 7 jours (aigu) et 28 jours (chronique). Ce moteur utilise le modèle
    impulsion-réponse de Banister (moyennes mobiles **exponentielles**
    7 j/42 j), une définition mathématiquement différente, jamais validée par
    les mêmes études — et évaluée au **maximum de la semaine proposée**
    plutôt qu'en fin de semaine, pour limiter (sans l'éliminer complètement)
    un biais de motif hebdomadaire (une longue sortie systématiquement le
    dimanche gonflerait sinon l'ACWR du seul dernier jour). La preuve
    elle-même est **contestée** dans la littérature de course à pied : voir
    Impellizzeri F.M. *et al.* (2020), déjà cité dans
    [`docs/marques.md`](marques.md) (« ACWR : la zone 0,8-1,3 est un repère
    indicatif [...] discuté dans la littérature »). C'est pourquoi R1 est
    `warn` par défaut, pas `block`.

!!! note "Pourquoi ces citations sont dans le code, pas dans `resources/`"
    `resources/` est un dossier **privé** du workspace de chaque utilisateur
    (gitignoré, créé par `install.sh`) : il n'existe pas dans ce dépôt public,
    et une règle ne peut donc pas y citer un fichier vérifiable. Les sources
    citées ici sont donc des références de littérature directement dans
    `arc_guardrails.ASSUMPTIONS` (même convention que `arc_metrics.ASSUMPTIONS`
    déjà dans ce projet), et les règles sans source unique et consensuelle
    (R2/R3/R6) sont explicitement étiquetées « convention du projet ».

## CLI

```bash
# Sur un fichier semaine déjà écrit
python3 scripts/arc_guardrails.py check --week planning/2026-09-21_semaine.md

# AVANT d'écrire le fichier (fichier temporaire ou flux stdin, JSON ou Markdown ```arc)
echo '{"week_start": "2026-09-21", "sessions": [...]}' \
  | python3 scripts/arc_guardrails.py check --week -

python3 scripts/arc_guardrails.py check --week /tmp/proposed.json --workspace . --today 2026-09-20
```

La semaine proposée est validée avant tout calcul : contrat `arc_contract`
(champs requis, types — un `planned_duration_s` non numérique est rejeté
avant de pouvoir faire planter un calcul) et `week_start` sur un **lundi**
(le moteur suppose partout des semaines Lundi-Dimanche).

Sortie JSON sur stdout. **Codes de sortie** — un agent en headless doit
pouvoir les distinguer sans ambiguïté :

| Code | Signification |
|---|---|
| `0` | ok — aucune violation de sévérité `block` (des `warn`/`info` peuvent exister) |
| `1` | au moins une violation de sévérité `block` |
| `2` | erreur (fichier introuvable, semaine non conforme au contrat, date malformée…) — **jamais** confondu avec `1` |

```json
{
  "ok": true,
  "violations": [
    {"rule_id": "r1_acwr_projected", "severity": "warn",
     "message": "ACWR projeté (maximum sur la semaine) : 1.42, au-delà du seuil 1.3.",
     "message_en": "Projected ACWR (weekly maximum): 1.42, above the 1.3 threshold.",
     "values": {"observed": 1.42, "threshold": 1.3},
     "session_dates": [], "source": "..."}
  ],
  "checked_rules": ["r1_acwr_projected", "r2_weekly_volume_jump", "..."],
  "skipped_rules": [{"rule_id": "r3_weekly_elevation_jump",
                      "reason_code": "not_applicable_sport",
                      "reason": "R3 ne s'applique qu'en trail ([sport].primary)."}],
  "context": {"week_start": "2026-09-21", "is_race_week": false,
              "acwr_projected": 1.42, "monotony_projected": 1.6,
              "distance_only_sessions_estimated": [], "...": "..."}
}
```

`violations[].rule_id` et le format ci-dessus sont pensés pour
[#54](https://github.com/mmornati/ai-running-coach/issues/54) (bloc `decision`,
qui enregistrera les `rule_id` déclenchés) et
[#57](https://github.com/mmornati/ai-running-coach/issues/57) (drapeau
composite de risque de blessure, qui combine `context.acwr_projected`/
`context.monotony_projected` avec d'autres signaux).

## Pour aller plus loin

Fonction pure au cœur du moteur : `evaluate(proposed_week, context, config) ->
dict`, testée par `tests/data/test_arc_guardrails.py` (un cas par règle,
juste sous/juste au-dessus du seuil, plus les cas limites : historique court,
séances le même jour, séances manquées, prescriptions en distance seule,
semaine de récupération après une course). `build_context(conn, config,
gconf, week_start, today)` lit l'index dérivé (charge réelle, activités de la
semaine, allure récente, semaine(s) précédente(s), dernier verdict santé,
objectif actif) — c'est la seule partie du module qui touche à la base
SQLite.
