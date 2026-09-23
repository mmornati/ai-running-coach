# Configuration

Tout se règle dans deux fichiers TOML, et un profil en Markdown.

| Fichier | Rôle | Versionné ? |
|---|---|---|
| `config/workspace.toml` | Défauts partagés, livrés avec le projet | oui |
| `config/workspace.user.toml` | **Vos** réglages — ils priment, clé par clé | non (gitignoré) |
| `planning/Runner_Profile.md` | Votre profil : physiologie, blessures, matériel, préférences | non |

La façon normale de les remplir est [`/coach-setup`](skills/coach-setup.md).
Rien n'interdit de les éditer à la main ensuite.

!!! tip "Annuler un héritage"
    Une clé **présente mais vide** dans `workspace.user.toml` gagne sur la valeur
    partagée. C'est ainsi qu'on efface une valeur au lieu de la remplacer.

## Le staff — `[agents]`

```toml
[agents]
enabled = ["coach", "medical", "nutritionist", "course-strategist"]
```

Seuls les agents listés sont installés, et le coach ne délègue qu'à eux. `coach`
est indispensable : c'est lui qui planifie et pousse vers le calendrier Garmin.

```bash
./install.sh --no-medical                  # tout sauf le médecin
./install.sh --agents coach,nutritionist   # staff explicite
```

L'option écrit `[agents].enabled`, si bien qu'une réinstallation sans option
respecte votre choix. Réactiver un agent le réinstalle ; le désactiver le retire
pour de bon des dossiers `.claude/agents`, `.opencode/agents` et
`.github/agents`.

Ce que vous perdez en retirant un agent :

| Retiré | Conséquence |
|---|---|
| `medical` | Plus de gatekeeper ni de protocole blessure. Le coach applique lui-même `[health].morning_check` et vous renvoie vers un vrai médecin pour tout ce qui est clinique. |
| `nutritionist` | Plus de plan de macros ni de poids de forme. Le coach garde des conseils de ravitaillement génériques dans les notes de séance. |
| `course-strategist` | Plus de plan de course détaillé. Le coach analyse quand même un GPX avec le skill `gpx-analysis`. |

## Le bilan matinal — `[health]`

```toml
[health]
morning_check = "full"   # full | minimal | off
```

| Valeur | Ce que fait le coach |
|---|---|
| `full` | HRV + FC de repos + readiness avant toute décision de séance. Défaut, recommandé. |
| `minimal` | Readiness seule, en une ligne. Aucune annulation sur les seules données de santé. |
| `off` | Aucune donnée de santé récupérée. Planification sur la charge d'entraînement et votre ressenti. |

!!! warning "Ce n'est pas la même chose que retirer l'agent `medical`"
    Le bilan matinal est un mandat porté par le **coach**, pas par le médecin.
    Retirer l'agent `medical` ne le désactive pas — il faut `morning_check`.
    Inversement, `off` n'empêche pas le médecin de répondre à une question de
    santé que vous posez.

Passez à `minimal` ou `off` si votre montre ne mesure pas la HRV, ou si vous ne
souhaitez pas que votre entraînement dépende de ces données.

## Le style de coaching — `[coaching]`

```toml
[coaching]
style     = "bienveillant"   # bienveillant | exigeant | factuel | pedagogue
intensity = "balanced"       # gentle | balanced | strong
verbosity = "standard"       # brief | standard | detailed
```

### Styles de coaching

| Style | Ce que ça change |
|---|---|
| `bienveillant` | Chaleureux, valorise la régularité, explique le pourquoi. |
| `exigeant` | Direct, vous tient à vos engagements, nomme les séances manquées, ne console pas. |
| `factuel` | Verdict d'abord, chiffres, zéro remplissage motivationnel. |
| `pedagogue` | Développe la physiologie derrière chaque décision. |

`intensity` règle la fermeté (proposer / recommander / trancher), `verbosity` la
longueur. Le catalogue complet, avec les règles qui s'appliquent quel que soit le
style, est dans [`config/coaching-styles.md`](https://github.com/mmornati/ai-running-coach/blob/main/config/coaching-styles.md).

!!! note "Le style ne change jamais le fond"
    Une séance annulée pour raison médicale reste annulée en `bienveillant`
    comme en `exigeant`. Le ton décide de la formulation, jamais du verdict.

Ce qui ne rentre pas dans un identifiant — « ce qui me motive », « ne me parle
jamais de mon poids » — s'écrit dans la section « Préférences de coaching » de
votre profil, **qui prime sur le catalogue**.

## La discipline — `[sport]`

```toml
[sport]
primary     = "trail"    # trail | road
disciplines = ["cycling", "strength"]
```

`primary` charge un profil de sport qui définit l'unité de charge, le vocabulaire
des séances, les corrections de terrain et le matériel par défaut.

| Profil | Raisonne en |
|---|---|
| `trail` | Temps d'effort et D+ ; corrections de terrain ; marche rapide prescrite en forte pente. |
| `road` | Kilomètres et allures dérivées d'une performance récente ; pas d'objectif de D+. |

`disciplines` liste vos sports croisés : ce sont les seuls que le coach s'autorise
à programmer.

## L'athlète — `[athlete]`

```toml
[athlete]
profile = "planning/Runner_Profile.md"
units   = "metric"       # metric | imperial
```

Deux champs du profil changent le quotidien :

- **Lieu par défaut** — sans lui, la météo est redemandée à chaque validation.
- **Créneau habituel** — sans lui, le coach doit vous le demander avant de placer
  vos séances.

Deux champs de la section « Physiologie » alimentent le
[tableau de bord](dashboard/index.md) : **FC max** et **FC de repos de référence**
(la **FC au seuil** et le **sexe**, facultatifs, affinent le calcul de charge).

## Le tableau de bord — `[dashboard]`

```toml
[dashboard]
port = 8765
```

Port du [tableau de bord local](dashboard/index.md). S'il est pris, les 9 suivants sont
essayés. L'adresse d'écoute, elle, n'est pas réglable : `127.0.0.1` uniquement.

## Langue, notifications, synchronisation

`[language]`, `[notifications]` et `[sync]` sont décrits dans
[Votre workspace privé](workspace.md) et [Le coach dans la poche](mobile.md).

## Vérifier

```bash
python3 scripts/coach_setup.py --status
```

Affiche le workspace détecté, les questions restant à poser, les fichiers
installés et si votre configuration personnelle est bien exclue de git.
