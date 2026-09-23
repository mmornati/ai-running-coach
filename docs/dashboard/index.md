# 📊 Tableau de bord

Le coach écrit tout dans votre workspace : séances, nuits, météo, plans, rapports.
Le tableau de bord met ces fichiers **sous vos yeux** : courbe de forme, bilan du
matin, semaine planifiée face au réalisé, séances avec leurs splits, prédictions,
calendrier — et le texte du coach à côté des chiffres.

![Vue « Aujourd'hui » : verdict du coach, bilan du matin, séance du jour et forme](../assets/dashboard/aujourdhui.webp)

*Captures réalisées sur le workspace réel d'un athlète : la préparation et
l'ultra-trail de 110 km du 13 septembre 2026, puis la reprise.*

Il ne remplace pas la conversation avec le coach : il vous montre **ce qui est
stocké**, et c'est d'autant plus précieux quand le coach tourne sans vous — en
[mode headless](headless.md), la synchronisation de chaque matin alimente le tableau
sans que vous ouvriez une session.

## Lancer

```bash
scripts/dashboard.sh
```

Le navigateur s'ouvre sur `http://127.0.0.1:8765/`. `Ctrl+C` arrête le serveur.
Rien à installer : un serveur Python de la bibliothèque standard et une page
HTML/CSS/JS, sans npm ni étape de build.

```bash
scripts/dashboard.sh --port 9000   # autre port (défaut : [dashboard].port)
scripts/dashboard.sh --no-open     # sans ouvrir le navigateur
scripts/dashboard.sh --memory      # index en mémoire : aucun fichier écrit
scripts/dashboard.sh --rebuild     # reconstruit l'index de zéro
```

L'index se met à jour tout seul : un fichier écrit par un agent — la
synchronisation du matin, un rapport, un plan — apparaît à la requête suivante (au
plus 30 secondes), sans relancer le serveur.

## Ce qu'il vous montre

| Vue | Pour répondre à |
|---|---|
| [Aujourd'hui](views.md#aujourdhui) | Je cours, j'allège ou je me repose ? Comment était ma nuit ? |
| [Forme & charge](views.md#forme-charge) | Où en est ma condition, ma fatigue, ma fraîcheur ? Mon volume progresse-t-il raisonnablement ? |
| [Santé](views.md#sante) | HRV, FC de repos, readiness, sommeil — et les verdicts du coach jour par jour |
| [Semaine](views.md#semaine) | Qu'est-ce qui était prévu, qu'est-ce qui a été fait, avec quelle météo ? |
| [Séances](views.md#seances) | L'historique complet, trié comme je veux ; les splits et l'analyse du coach |
| [Performance](views.md#performance) | Ma VO2max estimée, mes temps prédits, mes records |
| [Calendrier](views.md#calendrier) | Ma régularité sur l'année, mon cumul comparé aux années précédentes |
| [Rapports](views.md#rapports) | Les bilans du coach, lisibles, sans ouvrir l'IDE |

Le détail de chaque vue, captures à l'appui : [Les vues](views.md).

Il suit votre [configuration](../configuration.md) : sur route, le dénivelé disparaît
et le volume se compte en kilomètres ; avec `[health].morning_check = "off"`, la vue
Santé l'indique au lieu d'afficher des trous ; sans nutritionniste dans le staff, la
vue Nutrition n'apparaît pas ; en unités impériales, tout s'affiche en miles.

## D'où viennent les chiffres

Les agents ouvrent chaque fichier par un petit bloc de données — le
[contrat de données](../skills/workspace-data-contract.md). Le tableau de bord lit
ces blocs, jamais la prose, et les range dans une base SQLite **dérivée** :
`.arc/coach.db` dans votre workspace. Elle est jetable : la supprimer ne perd rien,
elle se reconstruit depuis vos fichiers. Elle est ignorée par git.

Les indicateurs de forme sont **calculés**, pas demandés au modèle : le coach
observe et juge, le code compte.

- **Charge d'une séance** : TRIMP de Banister (FC moyenne, FC max et FC de repos du
  profil), ou effort perçu faute de fréquence cardiaque.
- **Condition, fatigue, forme** : moyennes exponentielles sur 42 et 7 jours.
- **VO2max effective et prédictions** : estimées à partir de l'allure et de la FC
  **moyennes** des séances de course. Des ordres de grandeur, pas des mesures ; la
  vue Performance liste toutes les hypothèses.

!!! tip "Renseignez votre profil"
    Sans **FC max** ni **FC de repos de référence** dans `planning/Runner_Profile.md`,
    la charge est estimée d'après l'effort perçu. Ajoutez-les (et la FC au seuil si
    vous la connaissez) : toutes les courbes en profitent.

## Vos fichiers d'avant

Si votre workspace existait avant le contrat, le tableau de bord lit déjà vos
anciens fichiers, au mieux, et signale ceux qu'il comprend mal (« fichiers hors
contrat » dans le menu). Pour tout remettre d'aplomb : [Migrer vos fichiers](migration.md).

## Sécurité

- Le serveur n'écoute **que sur `127.0.0.1`** : rien n'est visible depuis le réseau.
  L'adresse n'est volontairement pas configurable.
- Lecture seule : il n'écrit que sa propre base, dans `.arc/`.
- Une page tierce qui tenterait de l'atteindre en se faisant passer pour
  `localhost` est refusée (protection contre le *DNS rebinding*).

Pour le consulter depuis une autre machine, passez par un tunnel SSH plutôt que
d'ouvrir un port : voir [Machine coach & mode headless](headless.md).
