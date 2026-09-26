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
| `r1_acwr_projected` | ACWR (charge aiguë/chronique) **projeté** en fin de semaine proposée | `block` |
| `r2_weekly_volume_jump` | hausse de la durée (+ distance en `road`) hebdomadaire planifiée | `warn` |
| `r3_weekly_elevation_jump` | hausse du D+ hebdomadaire planifié (trail seulement) | `warn` |
| `r4_monotony_projected` | monotonie de Foster **projetée** sur la semaine proposée | `warn` |
| `r5_quality_after_red` | séance de qualité le jour même ou le lendemain d'un verdict santé rouge | `block` |
| `r6_long_run_share` | part de la plus longue sortie dans le volume hebdomadaire | `warn` |
| `r7_consecutive_quality` | deux séances de qualité sur deux jours consécutifs | `warn` |

Seuils et sévérités : `[guardrails]` de `config/workspace.toml`, voir
[Configuration](configuration.md#les-garde-fous-guardrails).

## Ce qui n'est jamais bloqué

- **Historique insuffisant** (nouveau workspace, ACWR non significatif tant
  que la condition n'a pas atteint un plancher) : la règle est **sautée**
  (`skipped_rules`, `reason_code: "insufficient_history"`), jamais bloquée sur
  un calcul bruité.
- **Semaine de course** (date de `planning/active_objective.md` dans la
  semaine proposée) : R1, R2, R3, R4, R6 et R7 sont sautées
  (`reason_code: "race_week"`) — l'objectif est d'éviter une progression trop
  agressive à l'entraînement, jamais de bloquer la course elle-même. R5 reste
  active (une alerte santé reste pertinente juste avant une course).
- **Bilan matinal désactivé** (`[health].morning_check = "off"`) : R5 est
  sautée (`reason_code: "health_check_disabled"`) — aucune donnée de santé
  n'est de toute façon récupérée dans ce mode.
- **Séances annulées, déplacées ou de repos** : exclues de toutes les règles.
- **Semaine de récupération (deload)** : R2/R3 ne réagissent qu'à une
  **hausse** — une baisse de volume ne déclenche jamais rien.
- **Sport hors périmètre d'une règle** : R3 (D+) ne s'applique qu'en trail,
  la part distance de R2 qu'en route (`reason_code: "not_applicable_sport"`).

## Approximation de charge d'une séance planifiée

Une séance **planifiée** n'a pas de FC : impossible d'y calculer un vrai TRIMP
(`arc_metrics.trimp_banister`). R1/R4 projettent donc une charge à partir de
l'intensité prescrite (`rest` → 0 … `race` → 10 sur l'échelle RPE 0-10),
passée dans **exactement la même formule** que le repli session-RPE de
`arc_metrics.session_load`, pour rester sur la même échelle que la charge
réelle déjà indexée. C'est une approximation d'une approximation, jamais
présentée comme mesurée — voir `arc_guardrails.ASSUMPTIONS["projected_load"]`.

## Sources

Chaque règle cite sa source dans son champ `source` (littérature vérifiable
pour R1/R4/R7 — Gabbett 2016, Foster 1998, Seiler & Kjerland 2006 — ou
« convention du projet » explicite pour R2/R3/R6, faute de source unique et
consensuelle). Le détail complet est dans `scripts/arc_guardrails.py::ASSUMPTIONS`.

## CLI

```bash
# Sur un fichier semaine déjà écrit
python3 scripts/arc_guardrails.py check --week planning/2026-09-21_semaine.md

# AVANT d'écrire le fichier (fichier temporaire ou flux stdin, JSON ou Markdown ```arc)
echo '{"week_start": "2026-09-21", "sessions": [...]}' \
  | python3 scripts/arc_guardrails.py check --week -

python3 scripts/arc_guardrails.py check --week /tmp/proposed.json --workspace . --today 2026-09-20
```

Sortie JSON sur stdout, code de sortie `0` si `ok` (aucune violation `block`),
`1` sinon :

```json
{
  "ok": false,
  "violations": [
    {"rule_id": "r1_acwr_projected", "severity": "block",
     "message": "ACWR projeté en fin de semaine : 1.42, au-delà du seuil 1.3.",
     "message_en": "Projected end-of-week ACWR: 1.42, above the 1.3 threshold.",
     "values": {"observed": 1.42, "threshold": 1.3},
     "session_dates": [], "source": "..."}
  ],
  "checked_rules": ["r1_acwr_projected", "r2_weekly_volume_jump", "..."],
  "skipped_rules": [{"rule_id": "r3_weekly_elevation_jump",
                      "reason_code": "not_applicable_sport",
                      "reason": "R3 ne s'applique qu'en trail ([sport].primary)."}],
  "context": {"week_start": "2026-09-21", "is_race_week": false,
              "acwr_projected": 1.42, "monotony_projected": 1.6, "...": "..."}
}
```

`context.rule_ids` des violations et le format ci-dessus sont pensés pour
[#54](https://github.com/mmornati/ai-running-coach/issues/54) (bloc `decision`,
qui enregistrera `rule_ids`) et [#57](https://github.com/mmornati/ai-running-coach/issues/57)
(drapeau composite de risque de blessure, qui combine `acwr_projected`/
`monotony_projected` avec d'autres signaux).

## Pour aller plus loin

Fonction pure au cœur du moteur : `evaluate(proposed_week, context, config) ->
dict`, testée par `tests/data/test_arc_guardrails.py` (un cas par règle,
juste sous/juste au-dessus du seuil). `build_context(conn, config, gconf,
week_start, today)` lit l'index dérivé (charge réelle, semaine(s)
précédente(s), dernier verdict santé, objectif actif) — c'est la seule partie
du module qui touche à la base SQLite.
