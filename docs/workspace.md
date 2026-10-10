# Votre workspace privé

`ai-running-coach` est un **moteur** : agents, skills, scripts, installation. Vos données —
séances, santé, plans, rapports, ressources — sont votre **workspace**. Par défaut les deux
vivent dans le même dossier (les dossiers de données sont exclus du dépôt). Dès que vous
voulez **versionner vos données dans votre propre dépôt privé** et **suivre les mises à
jour du moteur sans rien copier**, séparez-les avec `--workspace`.

<!-- arc-video:donnees -->
<div class="arc-video-card" markdown>

[![Vos données, votre sentier](video/donnees/poster.jpg)](video/donnees/index.html)

<div markdown>

<span class="arc-video__meta">En vidéo · Étape 12 · 1 min 42</span>

**[Vos données, votre sentier](video/donnees/index.html)** — Vos données restent des fichiers Markdown chez vous : un bloc validé, un index jetable, un tableau de bord local, et ce qui quitte la machine.

[Regarder](video/donnees/index.html) · [English](video/donnees/index.html?lang=en) · [Toutes les vidéos](videos.md)

</div>

</div>
<!-- /arc-video -->


## Le principe

```
~/ai-running-coach/          moteur (ce dépôt, public)        → git pull pour les nouveautés
~/mon-workspace/             workspace (VOTRE dépôt privé)
├── activities/ medical/ nutrition/ planning/ rapports/ gear/ resources/   ← versionnés
├── local/agents/  local/skills/    ← vos agents/skills privés, versionnés
├── config/workspace.user.toml      ← vos réglages (langue, notifications, sync), versionné
│
│   généré par install.sh, ignoré par git (bloc ajouté à .gitignore) :
├── agents/  skills/                ← catalogues de liens : moteur + local/
├── AGENTS.md  config/workspace.toml  scripts/ → liens vers le moteur
├── config/coaching-styles.md  config/sports/  → liens vers le moteur (lus par les agents)
├── .mcp.json  .claude/  .opencode/  .gemini/  .cursor/  .windsurf/  .github/agents|skills
├── .arc/                           ← index du tableau de bord (dérivé, jetable)
└── logs/
```

- **`.arc/`** contient l'index du [tableau de bord](dashboard/index.md) : dérivé de vos fichiers,
  jetable, ignoré par git.
- **Rien n'est copié** : `agents/` et `skills/` du workspace ne contiennent que des liens.
  Un `git pull` dans le moteur met à jour tous les skills instantanément ; relancez
  `./install.sh --workspace …` seulement si un skill a été **ajouté ou supprimé** (le
  catalogue est recréé, idempotent).
- **Vos skills privés** vont dans `local/skills/<nom>/SKILL.md` (idem `local/agents/`) :
  ils apparaissent dans le catalogue à côté de ceux du moteur, avec priorité en cas
  d'homonyme. Candidats à une contribution upstream quand ils sont génériques.
- **La diff de votre dépôt privé = vos données**, rien d'autre.
- L'IDE, le cron et Remote Control travaillent **dans le workspace** (`cwd`), jamais dans
  le moteur.

!!! note "Pourquoi pas un fork ou un sous-module ?"
    Un fork du moteur contenant vos données oblige à modifier son `.gitignore` et à
    résoudre ce conflit à chaque synchronisation. Un sous-module fonctionne (il fige la
    version du moteur) mais ajoute de la cérémonie ; `--workspace` accepte aussi un moteur
    cloné en sous-module de votre workspace si vous tenez à ce figeage.

## Mise en place

```bash
# 1. le moteur
git clone https://github.com/mmornati/ai-running-coach.git ~/ai-running-coach

# 2. votre dépôt privé (nouveau ou existant)
git clone git@github.com:vous/mon-workspace.git ~/mon-workspace   # ou : mkdir + git init

# 3. installation : configs IDE, dossiers et liens dans le workspace
cd ~/ai-running-coach
./install.sh --ide claude --workspace ~/mon-workspace
```

Le chemin du workspace est mémorisé dans `~/.config/ai-running-coach/workspace` : les
scripts (`daily-sync.sh`, `coach-remote.sh`, `setup-ntfy.sh`) l'utilisent automatiquement
(variable `ARC_WORKSPACE` pour forcer). Les options `--daily-sync` et `--remote-control`
(voir [Le coach dans la poche](mobile.md)) s'appliquent au workspace.

Ouvrez ensuite votre IDE **dans `~/mon-workspace`**.

## Migrer un workspace existant

Si votre dépôt privé contient déjà des **copies** d'agents/skills (`.opencode/skills/…`,
`AGENTS.md` maison…), supprimez-les de l'index avant l'installation — sinon `install.sh`
refuse d'écraser un vrai dossier par un lien :

```bash
cd ~/mon-workspace
git rm -r --cached .opencode/agents .opencode/skills .gemini/commands AGENTS.md
rm -rf .opencode/agents .opencode/skills .gemini/commands AGENTS.md
# skills privés (absents du moteur) → local/
mkdir -p local/skills && git mv .opencode/skills/mon-skill local/skills/mon-skill   # avant le rm ci-dessus
```

Puis `./install.sh --ide claude --workspace ~/mon-workspace`, vérifiez `git status` (seuls
vos données, `local/`, `config/workspace.user.toml` et `.gitignore` doivent apparaître) et
committez.

## Versionner automatiquement depuis la machine coach

Avec `git_autocommit = true` dans `config/workspace.user.toml` (section `[sync]`), chaque
run de `scripts/daily-sync.sh` :

1. **tire** d'abord le dépôt (`git pull --rebase --autostash`) : ce que vous avez poussé
   depuis le portable est pris en compte par l'agent ;
2. synchronise Garmin ;
3. termine par `git add -A && git commit`, **re-tire** en rebase ce qui aurait été poussé
   pendant le run, puis `git push`.

Les fichiers de la synchronisation **et** ceux créés entre-temps par vos sessions mobiles
(plans, rapports) arrivent dans votre dépôt privé sans intervention, et les deux machines
restent synchronisées dans les deux sens. Un conflit (même fichier modifié des deux côtés)
annule le rebase et est signalé dans la notification, sans bloquer la synchronisation. Le
push suppose une clé SSH sur la machine coach autorisée sur votre dépôt.

!!! note "Échantillons FIT (#42) : jamais dans le `git add -A`"
    `daily-sync` peut aussi télécharger le FIT de chaque nouvelle séance
    ([mode headless](dashboard/headless.md)) : `activities/<id>.fit` et
    `activities/<id>.records.json` (pistes GPS complètes, plusieurs centaines de Ko par
    séance) et leur copie normalisée `activities/fit/<id>.json`. Les trois sont des
    données **brutes et jetables**, reconstruites depuis Garmin à tout moment — jamais
    versionnées, même ici, même avec `git_autocommit = true`. `download_fit.py` dépose
    un `.gitignore` (`*.fit`, `*.records.json` dans `activities/`, un blanket-ignore dans
    `activities/fit/`) dès son premier téléchargement dans le workspace : rien à faire
    de votre côté, ce marqueur suffit à les exclure du `git add -A` de `daily-sync`
    comme d'un `git add` manuel.

Sur le portable : `git pull` avant de travailler, `git push` après.

## Suivre les mises à jour du moteur

```bash
cd ~/ai-running-coach && git pull --ff-only
./install.sh --ide claude --workspace ~/mon-workspace --no-auth   # catalogue de skills, .mcp.json, .gitignore
```

Le cron relit les skills à chaque run. Sur la machine coach, relancez Remote Control
(`scripts/coach-remote.sh restart`) si `.mcp.json` a changé. Procédure complète, retour
arrière compris : [Mettre à jour](update.md).

## Ce qui reste hors des deux dépôts

- `~/.garminconnect/` — tokens Garmin
- `~/.config/ai-running-coach/ntfy.token` — token de notification
- `~/.config/ai-running-coach/workspace` — chemin du workspace
- `~/.claude.json` — approbation du serveur MCP pour le workspace

## Votre profil d'athlète

`/coach-setup` installe deux fichiers dans `planning/` depuis `templates/` :

| Fichier | Contenu |
|---|---|
| `Runner_Profile.md` | Physiologie, historique de blessures, indices de performance ITRA/UTMB (facultatif, jamais récupérés automatiquement), matériel, lieu par défaut, créneau habituel, préférences de coaching |
| `active_objective.md` | La course visée, l'objectif de performance, les contraintes connues |

Les deux vivent dans `planning/`, gitignoré dans le dépôt public et **versionné
dans votre dépôt privé** si vous utilisez `--workspace`. Les agents les lisent
avant toute planification ; aucun des deux n'est jamais écrasé une fois créé.

**Profil existant, section manquante.** `/coach-setup` ne réécrit jamais une
réponse déjà là — un profil installé avant l'ajout d'une nouvelle section au
modèle (ex. « Indices de performance (ITRA / UTMB) ») ne la reçoit donc pas
automatiquement. Deux façons de la rattraper : copier la section depuis
`templates/Runner_Profile.template.md` dans votre propre `planning/
Runner_Profile.md`, ou simplement le demander à l'agent `coach`, qui propose
de l'ajouter (vide) à votre confirmation. Voir la FAQ pour le détail.

### Déclarer vos chaussures (#40)

Dans la section « Matériel & lieux » du profil, sous-section « Chaussures » :
une puce de **premier niveau** par paire (jamais de puce indentée dessous —
elle serait ignorée), tout facultatif sauf le nom :

```
- <nom> — depuis <AAAA-MM-JJ> — alerte <N> km — départ <N> km — usage: <rôle> — id: <identifiant> — garmin: <uuid> (par défaut)
```

| Segment | Rôle |
|---|---|
| `depuis <date>` | Date d'achat (`AAAA-MM-JJ`, ou « mars 2026 » = 1er du mois). Filtre l'attribution automatique des séances sans matériel précisé à la paire « (par défaut) » — une séance antérieure n'y est pas rattachée. |
| `alerte <N> km` | Seuil d'usure propre à cette paire (accepte aussi « N miles »/« N mi », converti). Sans lui : **700 km par défaut**. |
| `départ <N> km` | Kilomètres déjà parcourus **avant** le suivi (paire d'occasion, usage antérieur à l'installation) ; accepte aussi « N mi »/« N miles », converti. Ajouté au kilométrage cumulé : il compte dans l'alerte et dans la prévision de retraite, y compris pour une paire retirée. `départ 0 km` est valide. |
| `usage: <rôle>` | Facultatif — rôle de la paire (`course`, `trail`, `route`, `récup`), texte libre. Le coach s'en sert pour suggérer une paire, aucun calcul n'en dépend. |
| `id: <identifiant>` | Identifiant explicite — **obligatoire** si vous rachetez le même modèle (sinon un id `-2`/`-3` est dérivé automatiquement, avec un avertissement au tableau de bord). |
| `garmin: <uuid>` | Facultatif (#133) — identifiant du matériel dans Garmin Connect (sans effet avec la source intervals.icu), pour rattacher le matériel que la montre attache à une séance. Ajouté par le coach après votre accord, jamais deviné. Voir [Synchronisation du matériel Garmin](garmin-setup.md#synchronisation-du-materiel-garmin). L'historique existant se rattrape avec `scripts/garmin_gear_backfill.py` (simulation puis `--apply`, puces ajoutées sans toucher aux existantes : [Rattraper le matériel de l'historique](garmin-setup.md#rattraper-le-materiel-de-lhistorique)). |
| `(par défaut)` | Chaussure attribuée aux séances sans matériel précisé. |
| `(retirée)` | Sortie de rotation — kilométrage conservé, plus jamais d'alerte. |

```
- Hoka Speedgoat 5 (bleues) — depuis 2026-03-01 — alerte 700 km — id: speedgoat-bleues (par défaut)
- Hoka Speedgoat 5 (grises) — depuis 2026-09-01 — id: speedgoat-grises
- Salomon S/Lab Ultra — usage: course — départ 20 km
- Nike Pegasus — départ 300 km (retirée)
```

Le coach nomme, dans ses rapports hebdomadaires, toute paire non retirée
ayant atteint son seuil (`python3 scripts/arc_index.py gear`).

**Corriger un kilométrage en discutant (#132).** « Mes Pegasus ont en fait ~300
km » : le coach ne réécrit que le segment `départ` de la puce concernée
(départ = total déclaré − kilomètres déjà comptés par vos séances, jamais
négatif) et le confirme en une ligne ; vos séances passées ne sont jamais
modifiées. Si la paire est ambiguë, il vous demande laquelle.

**Prévision de retraite (#132).** À partir du rythme des 28 derniers jours, le
tableau de bord et `arc_index.py gear` affichent « ≈ 6 sem. » — le temps restant
avant le seuil **à ce rythme**, une approximation linéaire (elle ignore un bloc
de repos ou un changement de rotation). Aucune prévision sans séance sur 28
jours, ni pour une paire retirée ; une paire au-dessus de son seuil affiche
« seuil dépassé ».

**Alertes visibles (#132).** Le résumé du `garmin-daily-sync` ajoute une ligne
quand une séance synchronisée fait franchir son seuil à une paire (une seule
fois par franchissement, sans fichier d'état) ; le retour de séance du coach
ajoute « Chaussures : … » quand la paire portée est à 90 % de son seuil ou à
moins de 4 semaines de la retraite ; `/week` signale les paires au seuil ou
proches.

**Suggestion de paire (#132).** Dès **deux paires actives** (non retirées) ou
plus, la validation quotidienne et hebdomadaire du coach ajoute, par séance en
extérieur, une ligne « Chaussures : … » : paire plus légère pour une séance de
qualité, paire d'accroche par temps boueux ou pluvieux, ménagement d'une paire
proche de son seuil. Le budget de rodage de la paire de course (environ 30 à
50 km avant le jour J, puis préservée) est une **approximation du projet**, pas
un standard publié. C'est une suggestion, jamais une consigne ; avec une seule
paire déclarée, rien n'est suggéré.

**Synchronisation du matériel Garmin (#133).** Avec la source Garmin, le coach
lit le matériel que la montre attache à chaque **nouvelle** séance
(`get_activity_gear`) et l'inscrit dans `gear_id` quand une puce porte le
`garmin: <uuid>` correspondant. Priorité : ce que vous déclarez en discutant >
matériel attaché par Garmin > `(par défaut)` — en cas de désaccord (Garmin dit A, vous dites B),
c'est vous qui gagnez, et le coach le signale une fois. Un
matériel Garmin sans puce n'est jamais attribué en silence (la séance n'est pas non plus créditée à
la paire par défaut) : le coach vous propose une fois de l'associer à une puce existante ou d'en
créer une ; si vous refusez, une puce `- <nom Garmin> — garmin: <uuid> (ignorée)` fait taire
propositions et alertes. Voir
[Synchronisation du matériel Garmin](garmin-setup.md#synchronisation-du-materiel-garmin)
(y compris la source intervals.icu, où l'attribution par séance reste
manuelle).
### Déclarer le reste du matériel (#134)

Bâtons, gilet, poche à eau, flasques, frontale, ceinture cardio, veste, semelles,
lacets : sous-section « Matériel » (`### Matériel`, à côté de « Chaussures », qu'elle ne
touche pas — aucun profil existant n'a à changer). Même principe : une puce de
**premier niveau** par objet, tout facultatif sauf le nom.

```
- <nom> — catégorie: <bâtons|gilet|poche|flasques|frontale|ceinture|veste|semelles|lacets|autre> — depuis <date> — alerte <déclencheurs> — entretien <date> — kit: <nom> — id: <identifiant>
```

| Segment | Rôle |
|---|---|
| `catégorie: <mot>` | Seule façon de classer l'objet (jamais devinée du nom). Décide des sports qui comptent (voir plus bas). Valeur non reconnue : objet suivi, aucune alerte inventée. |
| `alerte …` | Déclencheurs typés, combinables — **le premier atteint déclenche** : `N km`, `N h`, `N séances`, `N jours` (`alerte 30 jours ou 40 h`). Aucun seuil par défaut : sans `alerte`, jamais d'alerte. Une unité est obligatoire. |
| `depuis <date>` | Date d'achat ; les jours se comptent depuis cette date. |
| `entretien <date>` (ou `révisé`) | Dernier entretien (nettoyage, réimperméabilisation, pile…) : les jours se comptent depuis cette date et **tous les compteurs repartent de zéro** (séances datées jusqu'à cette date incluse exclues, celles d'après comptent). Écrivez-y la date de **la dernière séance faite avant l'entretien** : le coach le fait pour vous. Sans `depuis` ni `entretien`, un déclencheur en jours ne peut pas jouer (dit explicitement). |
| `départ N km/h/séances` | Usage avant le suivi, ajouté aux compteurs tant qu'aucun entretien n'existe. |
| `kit: <nom>` | Regroupe les objets portés ensemble (plusieurs kits possibles, séparés par des virgules). |
| `id: <identifiant>`, `(retirée)` | Comme pour les chaussures. |

**Sports par catégorie** (approximation du projet, pas une norme fabricant) : les bâtons
ne comptent qu'en trail et randonnée (jamais sur route) ; gilet, poche, flasques, veste,
semelles et lacets en course, trail et randonnée ; frontale et ceinture cardio sur tout
sport (la frontale compte ses heures).

**Attribution.** Une séance compte pour un objet seulement si son bloc `arc` le cite
dans `gear_ids` (liste ; `gear_id` reste la chaussure) — jamais deviné. Le plus simple :
dire au coach « kit trail long » (ou « avec les bâtons ») après la séance ; il écrit
`gear_ids` avec les objets du kit qui portent ce sport (les bâtons d'un kit sont écartés
d'une sortie sur route, et il vous le dit). Dites « j'ai nettoyé la poche » : il note
l'`entretien` du jour sur la puce.

**Alertes.** Objet sous alerte ou à 90 % d'un déclencheur : ligne « Matériel : … » dans
le rapport hebdomadaire, `/week` et le retour de séance ; alerte du `garmin-daily-sync`
une seule fois par franchissement (déclencheurs en jours : au premier passage du jour) ;
avant une séance de nuit ou une sortie longue, le coach rappelle un contrôle (frontale :
batterie ; poche et flasques : hygiène). Ligne de commande :
`python3 scripts/arc_index.py equipment` (`--kit`, `--race-plan`, `--activities`, `--last-pass`). Unités d'`alerte` : km, h (ou `1h30`), séances, jours, semaines, mois, ans (1 mois = 30 j, 1 an = 365 j, approximation du projet) ; un segment illisible produit un avertissement, jamais un silence. Marche (nordique) comprise pour bâtons, gilet, poche, flasques, veste. Le `garmin-daily-sync` n'alerte que sur les km/h/séances ; les déclencheurs en jours se lisent dans le tableau de bord, `/week`, le rapport hebdomadaire et les rappels du coach. Le matériel Garmin hors chaussures n'est pas rattaché (pas de segment `garmin:` sous `### Matériel`).

**Avant la course.** Le `course-strategist` croise le matériel obligatoire de son plan avec
cet inventaire : **manquant** (non retrouvé), **à vérifier** (seule la catégorie correspond : à confirmer sur la spécification du règlement), **jamais utilisé à l'entraînement** (« rien de
nouveau le jour J ») ou **sous alerte** — jamais inventé.
### Le dossier `gear/` : inspections photo (#135)

`gear/` reçoit les inspections photo de vos chaussures (skill
[`gear-inspection`](skills/gear-inspection.md)) : un fichier
`gear/AAAA-MM-JJ_<gear_id>_inspection.md` par inspection (bloc `arc` de type
`gear_inspection`), et les photos dans `gear/photos/`. Comme les autres dossiers de
données, il est **exclu du dépôt public** (`/gear/` dans `.gitignore`), créé par
`install.sh` et `/coach-setup`, et versionné dans **votre** dépôt privé quand vous
séparez le workspace. Attention : avec `git_autocommit`, les photos partent alors dans
ce dépôt privé — des images redimensionnées (~1 Mo) suffisent.

```
gear/
├── 2026-09-24_pegasus-41_inspection.md
├── 2026-08-02_pegasus-41_inspection.md
└── photos/2026-09-24_pegasus-41_semelles.jpg
```

Le coach propose une inspection environ tous les 200 km d'une paire (approximation du
projet), à l'alerte de seuil, ou sur demande — jamais imposée. Ce que vous retrouvez :
`python3 scripts/arc_index.py inspections [--gear ID]` (rappel `due`, historique, comparaison
des deux dernières), le tableau de bord (carte « Inspections photo », vignettes comprises), et,
quand une paire passe en `(retirée)`, `python3 scripts/arc_index.py gear-career --gear ID`
(km, séances, courses, meilleurs efforts quand des splits existent, dernière inspection). L'usure
d'une semelle est un signal faible : les indices de foulée qu'on en tire ne sont jamais un diagnostic.

## Les décisions tracées

Chaque fois qu'une séance est changée, remplacée ou annulée par un garde-fou,
le bilan matinal ou une donnée médicale, l'agent responsable écrit un fichier
`planning/YYYY-MM-DD_decision_<slug>.md` — la trace de **pourquoi**, lisible
par `/why` et par le [tableau de bord](dashboard/index.md). Il porte son
propre bloc ```arc (`trigger`, `rule_ids`, `before`/`after`, `outcome`) au
même contrat de données que le reste du workspace — voir [le skill
`workspace-data-contract`](skills/workspace-data-contract.md).
