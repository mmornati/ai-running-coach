# Aujourd'hui (`/today`)

`/today` répond en une ligne à « qu'est-ce que je fais aujourd'hui ? » — la
séance du jour, le bilan matinal au niveau configuré (`[health].morning_check`),
et le créneau météo si la séance est en extérieur. Il ne valide rien, ne
propose rien, et n'écrit ni ne modifie jamais un fichier **plan, semaine,
décision ou plan de course**, et ne pousse jamais rien vers Garmin — mais il
**persiste** le bilan santé et la météo du jour (`medical/YYYY-MM-DD_health.md`,
`medical/YYYY-MM-DD_meteo.md`) quand les règles de fraîcheur habituelles
l'exigent : cette donnée n'existe pas autrement, et la re-récupérer à chaque
appel irait à l'encontre de ces mêmes règles.

<!-- arc-video:bilan-matinal -->
<div class="arc-video-card" markdown>

[![Le réveil du traileur](../video/bilan-matinal/poster.jpg)](../video/bilan-matinal/index.html)

<div markdown>

<span class="arc-video__meta">En vidéo · Étape 02 · 1 min 19</span>

**[Le réveil du traileur](../video/bilan-matinal/index.html)** — HRV, FC de repos et readiness lues ensemble chaque matin : le verdict, sa raison, et comment régler le bilan.

[Regarder](../video/bilan-matinal/index.html) · [English](../video/bilan-matinal/index.html?lang=en) · [Toutes les vidéos](../videos.md)

</div>

</div>
<!-- /arc-video -->


## Lancer

```
/today
```

## Ce qui est répondu

- Une **première ligne fixe**, verdict d'abord : `Aujourd'hui — <séance prévue / repos / à ajuster>`.
- La séance du jour (type, durée/distance, intensité) telle qu'elle figure
  dans le fichier semaine courant — trouvé par `kind: "week"`, jamais par le
  nom du fichier (un plan multi-semaines, #113, peut nommer son fichier
  d'après son premier lundi tout en couvrant des semaines suivantes).
- Le bilan matinal au niveau configuré :
  - `full` (défaut) : HRV + FC de repos + readiness, les trois ensemble.
  - `minimal` : readiness seule, en une ligne — jamais de HRV ni de FC de repos.
  - `off` : aucune donnée de santé n'est récupérée.
- Le créneau météo optimal (matin tôt / midi / soir), uniquement si la séance
  du jour est en extérieur — « lieu inconnu » si le lieu ne se résout pas,
  jamais une question.

La longueur de la réponse suit `[coaching].verbosity` (`brief`/`standard`/`detailed`).

## Ce qu'il ne fait jamais

- Il ne pose jamais de question, y compris pour résoudre le lieu météo.
- Il n'écrit ni ne modifie jamais un fichier plan, semaine, décision ou plan
  de course.
- Il n'appelle jamais `schedule_workouts`/`schedule_week`/`upload_workout`/
  `unschedule_workout`/`upload_course`.
- Il ne propose pas `/coach-setup`, même sur une installation neuve — c'est une
  question factuelle, pas un premier démarrage (exception documentée dans
  `AGENTS.md`).

## Fichier source

`skills/today/SKILL.md`
