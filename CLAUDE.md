# Développement du moteur

Ce fichier s'adresse aux agents qui modifient **ce dépôt** (le moteur). Il n'est pas lié dans
le workspace de l'athlète ; les règles de coaching restent dans `AGENTS.md`.

## Commits : traçabilité Graft

Les PR de ce dépôt sont lues par [Graft](https://github.com/mmornati/graft), qui identifie
l'auteur d'une PR par des trailers `Graft-*` dans le **dernier paragraphe** du message de commit.
Tout commit écrit par un agent se termine par :

```
Graft-Agent: claude-code
Graft-Model: <identifiant exact du modèle qui a écrit le commit, ex. claude-opus-5-5>
Graft-Task: #<numéro d'issue>
```

- `Graft-Model` : le modèle de l'agent qui commit (un sous-agent Sonnet écrit le sien).
- `Graft-Task` : seulement s'il y a une issue ; sinon la ligne est omise.
- Avec `git commit -m`, passer `--trailer "Graft-Agent: claude-code"` (etc.) plutôt que de les
  écrire dans le texte. Le hook `prepare-commit-msg` de Graft, s'il est installé, ajoute
  `Graft-Agent` sans jamais le doubler.
