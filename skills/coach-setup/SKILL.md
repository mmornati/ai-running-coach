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
