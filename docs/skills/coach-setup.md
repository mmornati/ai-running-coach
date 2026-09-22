# Premier démarrage (`coach-setup`)

Au premier lancement, aucun agent ne sait qui vous êtes. `/coach-setup` mène un
entretien court et écrit le résultat au bon endroit.

## Lancer

```bash
/coach-setup
```

Depuis n'importe quel IDE supporté. Les agents le proposent aussi d'eux-mêmes
tant qu'aucune configuration n'existe — ils le proposent, ils ne l'imposent pas.

## Ce qui est demandé

| Question | Ce qu'elle règle |
|---|---|
| Style de coaching | Comment le coach vous parle — voir [Styles de coaching](../configuration.md#styles-de-coaching) |
| Fermeté | Avec quelle force le style s'applique |
| Longueur | Taille des retours de séance et des rapports |
| Discipline | Trail/ultra ou route — charge le profil de sport correspondant |
| Sports croisés | Pris en compte dans la planification hebdomadaire |
| Staff | Quels agents installer ; seuls ceux-là sont joignables |
| Bilan matinal | Si l'entraînement dépend de la HRV, de la FC de repos et de la readiness |
| Langues | Langue des documents, langue des réponses |
| Unités | Métriques ou impériales |

## Où vont les réponses

| Destination | Contenu |
|---|---|
| `config/workspace.user.toml` | Les réglages ci-dessus. Gitignoré. |
| `planning/Runner_Profile.md` | Votre profil : physiologie, blessures, matériel, préférences. Installé depuis un modèle, rempli en conversation. |
| `planning/active_objective.md` | L'objectif en cours, installé depuis un modèle. |

## Relancer

Sans risque : `/coach-setup` ne pose que les questions **sans réponse** et ne
remplace jamais une valeur existante. Pour changer un réglage déjà pris,
dites-le en clair au coach (« passe en style factuel »), ou éditez
`config/workspace.user.toml`.

!!! note "Changer le staff"
    Modifier `[agents].enabled` met à jour ce que le coach considère joignable,
    mais n'installe ni ne retire les fichiers d'agents. Pour cela :
    `./install.sh --agents coach,nutritionist` ou `./install.sh --no-medical`.

## En cas de doute

```bash
python3 scripts/coach_setup.py --status
```

Affiche le workspace détecté, les questions en attente, les fichiers installés
et si votre configuration personnelle est bien exclue de git.
