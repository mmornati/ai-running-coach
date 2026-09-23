# 📊 Tableau de bord

Vos séances, vos nuits et l'avis du coach sont dans des fichiers Markdown. Le
tableau de bord les met en graphiques : courbe de forme, bilan du matin, semaine
planifiée, séances avec leurs splits, prédictions, calendrier — et le texte du
coach à côté des chiffres.

```bash
scripts/dashboard.sh
```

Le navigateur s'ouvre sur `http://127.0.0.1:8765/`. `Ctrl+C` arrête le serveur.

## Ce qu'il affiche

| Vue | Contenu |
|---|---|
| **Aujourd'hui** | Verdict du coach (maintenir, alléger, repos), bilan du matin situé par rapport à vos références, séance du jour, météo et créneau, forme |
| **Forme & charge** | Condition (CTL 42 j), fatigue (ATL 7 j), forme (TSB), ratio aigu/chronique, volume hebdomadaire — en heures et D+ sur trail, en kilomètres sur route |
| **Santé** | HRV et sa bande de référence, FC de repos avec sa médiane 7 j et les seuils +5 / +7, readiness, sommeil, et la frise des verdicts du coach |
| **Semaine** | Séances planifiées face aux séances réalisées, météo et créneau par jour |
| **Séances** | Tableau triable ; chaque séance ouvre ses splits et l'analyse du coach |
| **Performance** | VO2max effective, prédictions (VDOT et Riegel), records |
| **Calendrier** | Année en carte de chaleur, distance cumulée comparée d'une année à l'autre |
| **Rapports** | Les rapports du coach, rendus |
| **Nutrition** | Poids et apports — seulement si le nutritionniste fait partie du staff |

Il suit votre [configuration](configuration.md) : discipline (le D+ disparaît sur
route), bilan matinal (`off` : la vue Santé l'indique au lieu d'afficher des trous),
staff, unités.

## D'où viennent les chiffres

Les agents écrivent chaque fichier avec un bloc de données en tête — le
[contrat de données](skills/workspace-data-contract.md). Le tableau de bord lit ces
blocs, jamais la prose, et les range dans une base SQLite **dérivée** :
`.arc/coach.db` dans votre workspace. Elle est jetable : la supprimer ne perd rien,
elle se reconstruit depuis vos fichiers. Elle est ignorée par git.

Les indicateurs de forme sont **calculés**, pas demandés au modèle :

- charge d'une séance : TRIMP de Banister (FC moyenne, FC max et FC de repos de
  votre profil), ou effort perçu faute de fréquence cardiaque ;
- condition, fatigue et forme : moyennes exponentielles sur 42 et 7 jours ;
- VO2max effective et prédictions : estimées à partir de l'allure et de la FC
  **moyennes** de chaque séance. Ce sont des ordres de grandeur ; la vue
  Performance liste toutes les hypothèses.

!!! tip "Renseignez votre profil"
    Sans FC max ni FC de repos dans `planning/Runner_Profile.md`, la charge est
    estimée d'après l'effort perçu. Ajoutez-les (et la FC au seuil si vous la
    connaissez) : toutes les courbes en profitent.

## Sécurité

- Le serveur n'écoute **que sur `127.0.0.1`** : rien n'est visible depuis le
  réseau. L'adresse n'est pas configurable.
- Lecture seule : il n'écrit que sa propre base, dans `.arc/`.
- Une page tierce qui tenterait de l'atteindre en se faisant passer pour
  `localhost` est refusée.

Pour le consulter depuis une autre machine (la machine coach par exemple), passez
par un tunnel SSH plutôt que d'ouvrir un port :

```bash
ssh -L 8765:127.0.0.1:8765 machine-coach
```

## Options

```bash
scripts/dashboard.sh --port 9000   # autre port ([dashboard].port par défaut)
scripts/dashboard.sh --no-open     # sans ouvrir le navigateur
scripts/dashboard.sh --memory      # base en mémoire : aucun fichier écrit
scripts/dashboard.sh --rebuild     # reconstruit l'index de zéro
```

L'index se met à jour tout seul : un fichier écrit par un agent apparaît à la
requête suivante (au plus toutes les 30 secondes), sans relancer le serveur.

## Fichiers écrits avant le contrat

Ils restent lus, au mieux, et comptent dans les courbes. Le lien
« fichiers hors contrat » du menu les liste ; [`/arc-backfill`](skills/arc-backfill.md)
les met au contrat, par lots, sans rien inventer.
