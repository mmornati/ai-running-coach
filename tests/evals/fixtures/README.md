# Fixtures des évals

Workspaces de démonstration, entièrement **synthétiques**. Aucune donnée réelle,
aucun compte Garmin : un scénario doit pouvoir tourner chez n'importe qui.

| Fixture | Contenu |
|---|---|
| `base-week/` | Une semaine plausible : quatre séances persistées, deux bilans santé, un objectif actif, un profil rempli. |
| `missed-session/` | Comme `base-week`, mais la séance qualité du mardi n'a jamais été faite. |
| `empty/` | Workspace nu — l'état d'un premier démarrage. |
| `configured/` | Profil et objectif déjà installés, pour tester l'idempotence. |

Les dates sont volontairement relatives dans le texte (« lundi », « mardi ») et
fixes dans les noms de fichiers : les évals ne vérifient jamais une date précise.
