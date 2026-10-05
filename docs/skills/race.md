# Course (`/race`)

`/race` donne le compte à rebours de votre objectif actif, le score Trail
Shape (#63, un indicateur parmi d'autres) et le plan de course (#59) s'il en
existe un. Il n'écrit ni ne modifie jamais un plan/plan de course, et ne
pousse rien vers Garmin.

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


## Lancer

```
/race
```

## Ce qui est répondu

Le compte à rebours (`objective.days_left`) et le score viennent de
`python3 scripts/arc_index.py trail-shape`, dont **chaque** valeur de
`status` est gérée explicitement :

| `status` | Réponse |
|---|---|
| `no_objective` | `Course — aucun objectif actif (planning/active_objective.md absent ou incomplet).` |
| `incomplete_objective` | Compte à rebours si connu, score indisponible (distance/dénivelé manquant — jamais deviné) |
| `race_past` | `Course — la course est passée (J+<jours>) : voir un débrief plutôt qu'une préparation.` — voir [le débrief post-course](../agents/coach.md#debrief-post-course-61) |
| `race_too_short` | Compte à rebours conservé, score non applicable à cette distance |
| `ok` | Première ligne fixe : `Course — J-<objective.days_left> <nom de la course>, Trail Shape <score>` |

- Le détail de l'objectif (distance, dénivelé) et, selon `[coaching].verbosity`,
  les composantes du score Trail Shape — avec un `data_confidence` `"low"`
  toujours signalé explicitement, jamais présenté comme un verdict certain.
- Le plan de course existant (`kind: "race_plan"`), s'il y en a un — nommé,
  jamais recalculé ici.
- Une ligne **« Forme prévue le jour J »** (#172) tirée de
  `python3 scripts/arc_index.py load-forecast` : l'**estimation** de votre
  forme à la date de la course d'après les séances planifiées (jamais une mesure),
  avec le nombre de semaines non planifiées s'il y en a (charge nulle supposée, donc
  forme optimiste). Si la projection est indisponible, une ligne dit pourquoi
  (`no_plan`, `insufficient_history`). Indicateur distinct du score Trail Shape,
  jamais mélangé avec lui ; ignoré en verbosité `brief`.

## Ce qu'il ne fait jamais

- Il n'écrit ni ne modifie aucun plan/plan de course — c'est le rôle de
  l'agent `course-strategist`.
- Il ne pousse rien vers Garmin.
- Il ne présente jamais un score Trail Shape de faible confiance comme un
  verdict certain.

## Fichier source

`skills/race/SKILL.md`
