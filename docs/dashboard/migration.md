# Migrer vos fichiers

Les fichiers écrits **avant** le [contrat de données](../skills/workspace-data-contract.md)
n'ont pas de bloc ```` ```arc ````. Le tableau de bord les lit quand même, au mieux :
tableaux et listes à la française (« 12,4 km », « 1 h 12 », « 2 400 m »), ancien bloc
YAML de la synchronisation. Mais ce qu'il en tire est partiel — souvent pas de splits,
pas d'identifiant Garmin, pas de verdict — et il les signale comme « hors contrat ».

Les migrer, c'est ajouter ce bloc **sous le titre** de chaque fichier, sans toucher au
reste. Deux chemins, selon le volume.

!!! note "Pourquoi un modèle et pas un script ?"
    Vos fichiers ont été écrits par un modèle, au fil des mois, dans des formats qui
    varient : listes en anglais au printemps, tableaux « Résumé » l'été, tableau
    « Données brutes Garmin » à l'automne ; deux séances dans un même tableau ; un plan
    de séance rangé parmi les activités. Un script en lit une partie et se trompe sur le
    reste (une ligne de comparaison 2024/2026 prise pour la durée du jour…). Un modèle
    lit ces fichiers comme vous : c'est lui qui doit écrire les blocs, avec des garde-fous.

## Quelques fichiers : `/arc-backfill`

Dans votre IDE, avec le coach :

```bash
/arc-backfill
```

Le skill récupère la liste des fichiers hors contrat
(`python3 scripts/arc_index.py backfill-plan`), en traite **au plus dix** par passe,
les plus récents d'abord — ce sont eux qui pèsent dans la courbe de forme —, valide
chacun, puis vous dit combien il en reste. Il n'enchaîne pas le lot suivant sans votre
accord. Voir la page du skill : [Backfill du contrat](../skills/arc-backfill.md).

## Tout un historique : migration assistée

Pour des centaines de fichiers, une session dédiée va plus vite. C'est ainsi qu'a été
migré le workspace des captures : 316 fichiers, 266 mis au contrat en une session,
**zéro ligne existante modifiée**.

### 1. Isoler le travail

```bash
cd ~/mon-workspace
git pull                                   # partir de l'état le plus récent
git switch -c arc-contract                 # tout se fait sur une branche
python3 scripts/arc_index.py backfill-plan # liste des fichiers à reprendre
```

Si une [machine coach](headless.md) synchronise ce workspace, ne touchez pas encore à
`main` : voir l'étape 5.

### 2. Lancer la session

Ouvrez votre IDE dans le workspace et donnez au modèle une consigne de ce type :

```text
Charge le skill workspace-data-contract. Pour chaque fichier listé dans
.arc/backfill.md, par lots d'une quinzaine, lis le fichier en entier et ajoute sous
son titre un bloc ```arc conforme au contrat, construit UNIQUEMENT avec ce que le
fichier dit. Règles :
- unités SI (12,4 km → 12400 ; 1 h 12 → 4320) ; RPE Garmin sur 100 → sur 10 ;
- une valeur absente reste absente ; si le fichier explique pourquoi (HRR « non
  fiable », altitude non enregistrée), mets-le dans missing_reason, jamais 0 ;
- verdict uniquement si le coach a écrit une décision explicite POUR CE JOUR-LÀ
  (« feu vert », « repos obligatoire ») — une recommandation pour le lendemain n'en
  est pas une ;
- ne modifie, ne supprime et ne traduis aucune ligne existante ;
- valide chaque fichier avec python3 scripts/arc_index.py --validate <fichier>.
Signale-moi, sans les convertir : les séances prescrites mais non réalisées, les
fichiers sans durée, les doublons, les fichiers qui regroupent plusieurs jours.
```

### 3. Les cas qui demandent une décision

La migration de référence en a rencontré plusieurs ; voici ce qui a été retenu.

| Cas | Décision |
|---|---|
| Même séance Garmin décrite dans deux fichiers (résumé + détail) | Même `garmin_activity_id` dans les deux blocs : l'index ne la compte qu'une fois |
| Un fichier pour plusieurs jours ou plusieurs séances | Un fichier compagnon par jour/séance, lignes recopiées telles quelles et renvoi vers l'original |
| Séance prescrite, jamais enregistrée | Pas de bloc : ce n'est pas une activité |
| « Aucune activité enregistrée ce jour » | Pas de bloc |
| Randonnées sans durée | Pas de bloc : la durée est obligatoire et ne s'invente pas |
| Analyse (strides, comparaison) rangée dans `activities/` | Pas de bloc : l'index ne la prend pas pour une séance |
| HRR « peu fiable » selon le coach (4 bpm, 1 bpm) | Clé omise + `missing_reason` |
| Profil d'altitude non enregistré | D+ omis, pas 0 |
| `planning/Runner_Profile.md` absent | Créé depuis le modèle avec les seules valeurs présentes dans vos fichiers (FC max, FC de repos, lieu, créneau) |

### 4. Vérifier avant de fusionner

```bash
git diff --stat                     # uniquement des insertions attendues
git diff --numstat | awk '{d+=$2} END {print d, "ligne(s) supprimée(s)"}'
python3 scripts/arc_index.py --rebuild status
scripts/dashboard.sh                # et regardez : forme, santé, séances, semaine
```

La migration de référence a ajouté un contrôle de plus : chaque nombre écrit dans un
bloc (distance, durée, FC, HRV…) devait se retrouver, sous une forme ou une autre,
dans le texte du fichier. Seules les sommes calculées par le modèle (deux randonnées
d'un même jour, une FC moyenne pondérée) y échappent — et se revérifient à la main.

Le lien « fichiers hors contrat » du tableau de bord doit ne plus lister que ce que
vous avez choisi de laisser de côté.

### 5. Fusionner, pousser — et la machine coach

```bash
git switch main
git merge --ff-only arc-contract
git push
```

Si une machine coach synchronise ce dépôt, faites-le **entre deux synchronisations**
(par défaut 07:15 et 14:15), puis tirez aussitôt sur la machine coach :

```bash
ssh machine-coach 'git -C ~/mon-workspace pull --ff-only'
```

Depuis cette version, `daily-sync.sh` tire lui-même avant chaque synchronisation et
avant de pousser — voir [Machine coach & mode headless](headless.md#deux-machines-un-depot).
Mettez la machine coach à jour du moteur pour en profiter : avant, elle poussait sans
jamais tirer, et un seul push venu du portable bloquait tous ses push suivants.

## Et ensuite ?

Une fois le moteur à jour, les agents écrivent le bloc eux-mêmes, et
`python3 scripts/arc_index.py --validate` le vérifie à chaque écriture : le travail
de migration ne se fait qu'une fois.
