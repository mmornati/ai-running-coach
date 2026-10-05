# Semaine (`/week`)

`/week` donne le statut compact de la semaine en cours — réalisé, prévu,
restant, et le verdict des garde-fous — sous forme de tableau court. Il
n'écrit ni ne modifie jamais un fichier plan/semaine/décision, et ne pousse
rien vers Garmin.

<!-- arc-video:garde-fous -->
<div class="arc-video-card" markdown>

[![Le plan qui sait dire non](../video/garde-fous/poster.jpg)](../video/garde-fous/index.html)

<div markdown>

<span class="arc-video__meta">En vidéo · Étape 03 · 1 min 46</span>

**[Le plan qui sait dire non](../video/garde-fous/index.html)** — Sept garde-fous calculés relisent la semaine avant son écriture et son envoi au calendrier Garmin : un second avis déterministe et testé.

[Regarder](../video/garde-fous/index.html) · [English](../video/garde-fous/index.html?lang=en) · [Toutes les vidéos](../videos.md)

</div>

</div>
<!-- /arc-video -->


## Lancer

```
/week
```

## Ce qui est répondu

- Première ligne fixe : `Semaine — <réalisé>/<prévu>, garde-fous : <ok|bloqué|à surveiller|entrée invalide>`.
- Un tableau compact, une ligne par séance : date, type, statut (les valeurs
  du contrat — `planned`/`done`/`missed`/`moved`/`cancelled`, jamais un autre
  mot), charge.
- Le verdict `scripts/arc_guardrails.py check --week <fichier> [--week-start <date>]`
  en un mot — pour l'explication complète d'un blocage, utiliser
  [`/why`](why.md).

Le fichier semaine est trouvé par `kind: "week"` dans `planning/*.md`, jamais
par son nom : un plan multi-semaines (#113) peut nommer son fichier d'après
son premier lundi tout en couvrant des semaines suivantes dans un tableau
`weeks` — `--week-start` cible alors explicitement le lundi de la semaine du
jour.

## Ce qu'il ne fait jamais

- Il ne modifie ni ne réécrit aucun fichier plan/semaine/décision.
- Il ne pousse rien vers le calendrier Garmin.
- Il ne propose pas d'ajustement — c'est le rôle de l'agent `coach` en session
  normale.

## Fichier source

`skills/week/SKILL.md`
