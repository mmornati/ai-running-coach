# Contrat de données (`workspace-data-contract`)

Vos séances, vos nuits et vos plans restent des fichiers Markdown lisibles.
Mais chaque fichier écrit par un agent commence désormais par un **petit bloc de
données** : c'est lui que lisent le [tableau de bord](../dashboard/index.md) et la
comparaison de parcours, jamais la prose.

<!-- arc-video:donnees -->
<div class="arc-video-card" markdown>

[![Vos données, votre sentier](../video/donnees/poster.jpg)](../video/donnees/index.html)

<div markdown>

<span class="arc-video__meta">En vidéo · Étape 12 · 1 min 42</span>

**[Vos données, votre sentier](../video/donnees/index.html)** — Vos données restent des fichiers Markdown chez vous : un bloc validé, un index jetable, un tableau de bord local, et ce qui quitte la machine.

[Regarder](../video/donnees/index.html) · [English](../video/donnees/index.html?lang=en) · [Toutes les vidéos](../videos.md)

</div>

</div>
<!-- /arc-video -->


## À quoi ça ressemble

````markdown
# Séance du 2026-09-20 — Trail de Tournai

```arc
{"arc": 1, "kind": "activity", "date": "2026-09-20", "sport": "trail",
 "distance_m": 12300, "duration_s": 5218, "elevation_gain_m": 480, "avg_hr_bpm": 148}
```

L'analyse du coach, en français, comme avant.
````

Le bloc est du JSON. Ses clés sont en anglais et ne changent jamais, quelle que
soit la langue de vos documents ; ses valeurs sont en unités SI (mètres,
secondes, bpm), même si vous avez choisi les unités impériales — la conversion
se fait à l'affichage.

## Pourquoi

Avant ce contrat, les chiffres se lisaient dans des tableaux et des titres
français. Passer `[language].documents` à `"en"` suffisait à faire disparaître
toutes vos séances de la comparaison de parcours, sans le moindre message. Un
bloc typé ne dépend ni de la langue, ni de l'ordre des colonnes, ni de la
formulation du modèle.

## Les types de fichiers

| Type | Fichier |
|---|---|
| `activity` | `activities/AAAA-MM-JJ_<type>.md` |
| `health` | `medical/AAAA-MM-JJ_health.md` — sommeil, HRV, FC de repos, readiness, poids et sa provenance (`weight_origin`, #222), **verdict du jour**, contexte du cycle (opt-in, #166) |
| `weather` | `medical/AAAA-MM-JJ_meteo.md` |
| `week` | `planning/Semaine_AAAA-MM-JJ.md`, daté du **lundi** — un fichier par semaine, ou un seul fichier multi-semaines (bloc `weeks`, un plan de 10 semaines peut tenir dans 1 fichier) — séances datées, lieu de la semaine |
| `nutrition` | `nutrition/AAAA-MM-JJ_nutrition.md` |
| `report` | `rapports/…` |
| `gear_inspection` | `gear/AAAA-MM-JJ_<gear_id>_inspection.md` — inspection photo d'une paire de chaussures (#135), photos dans `gear/photos/` |
| `course_eval` | `planning/…_evaluation_parcours_<lieu>.md` |
| `race_plan` | plan de course dans `planning/` |
| `decision` | `planning/AAAA-MM-JJ_decision_<slug>.md` — traçabilité d'un ajustement (garde-fou, bilan matinal, blessure…), un fichier par décision |

Votre profil (`planning/Runner_Profile.md`) et votre objectif
(`planning/active_objective.md`) n'ont **pas** de bloc : vous les éditez à la
main, et leurs puces suffisent. Gardez simplement les libellés du modèle.

## Dynamique de course (clés optionnelles d'une séance)

Depuis #151, une séance de course peut porter les moyennes de la dynamique de course
Garmin, en unités SI : `avg_ground_contact_s` (temps de contact, secondes),
`avg_stance_balance_pct` (balance du temps de contact, %), `avg_vertical_oscillation_m`
(mètres), `avg_vertical_ratio_pct` (%) et `avg_step_length_m` (mètres). Une clé **absente**
veut dire « non mesuré » — jamais `0`, jamais `50` pour une balance. Ce n'est qu'un repli : quand les
échantillons FIT sont ingérés, `arc_index.py gait-summary` calcule sa propre moyenne et c'est elle
qui fait foi. **Aucun agent ni script n'écrit ces clés automatiquement** : elles servent de repli pour des
valeurs saisies à la main ou héritées d'anciens fichiers. Une balance hors de 30 à 70 % déclenche un
avertissement du validateur et est ignorée par la synthèse. Voir la carte [Foulée](../dashboard/views.md#foulee).

## Vérifier un fichier

```bash
python3 scripts/arc_index.py --validate medical/2026-09-20_health.md
```

Les agents le font après chaque écriture. Le schéma complet, clé par clé, est
dans `skills/workspace-data-contract/SKILL.md`.

## Et les fichiers écrits avant ?

Ils restent lus, au mieux, et le tableau de bord les signale comme
incomplets. [`/arc-backfill`](arc-backfill.md) les met au contrat, par lots.
