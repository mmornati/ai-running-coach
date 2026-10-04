# Cycle menstruel (opt-in)

Le cycle menstruel influence la thermorégulation, la fréquence cardiaque de repos, la
HRV, le sommeil, la perception de l'effort et l'hydratation. Lire une HRV un peu basse en
phase lutéale comme une simple fatigue peut donc être un faux positif du bilan matinal.
Cette fonctionnalité permet au coach de **nuancer** une lecture, rien de plus.

!!! info "Opt-in strict, désactivé par défaut"
    Tant que `[health].cycle_tracking` vaut `"off"` (défaut), **aucune donnée de cycle n'est
    récupérée, aucun outil n'est exposé et aucun agent n'en parle** — jamais, nulle part.
    Rien n'est présumé : ni à partir du profil, ni du sexe, ni de l'âge.

## Activer

| Valeur | Effet |
|---|---|
| `off` (défaut) | Rien. Zéro mention. |
| `garmin` | Phase lue sur Garmin Connect (`[data].source = "garmin"`). Demande de relancer `./install.sh` : les deux outils `get_menstrual_data_for_date` et `get_menstrual_calendar_data` ne sont ajoutés à la liste blanche `GARMIN_ENABLED_TOOLS` **que dans ce mode**. |
| `intervals` | Phase lue dans le champ wellness `menstrualPhase` d'intervals.icu (`[data].source = "intervals"`), avec l'appel `icu_get_wellness_for_date` déjà fait pour la HRV et la FC de repos. Aucune installation à refaire. |
| `manual` | Phase déclarée par vous-même avec `/log` (« phase lutéale, jour 21 »). |

Dans `config/workspace.user.toml` :

```toml
[health]
cycle_tracking = "manual"   # off | garmin | intervals | manual
```

ou à l'installation : `./install.sh --cycle-tracking garmin`. `/coach-setup` pose la question
une seule fois, de façon neutre ; la passer (ou répondre « / ») retient `off`.

La casse et les espaces sont ignorés (`"Garmin"` vaut `"garmin"`). Une valeur invalide (faute
de frappe, type erroné) est traitée comme `off`, avec un avertissement : jamais une erreur,
jamais un suivi activé par accident. Un mode qui ne
correspond pas à la source de données (`garmin` avec intervals.icu, par exemple) retombe sur la
déclaration manuelle. Strava (`[data].source = "strava"`, #164) n'expose **aucune** donnée de
cycle : avec cette source, seul `manual` a un effet (`garmin` et `intervals` y retombent).

### Comment la liste blanche Garmin est gérée

`install.sh` part de la liste blanche habituelle (`GARMIN_TOOL_WHITELIST`, inchangée) et lui
ajoute `GARMIN_CYCLE_TOOLS` **uniquement** si le mode résolu est `garmin` avec la source Garmin.
Le mode est résolu ainsi : `--cycle-tracking` s'il est passé, sinon `[health].cycle_tracking`
de votre configuration, sinon `off`.

- Un simple `./install.sh` (sans option) relit votre configuration : il n'ajoute rien si vous
  n'avez pas activé le suivi, et ne retire rien si vous l'avez activé.
- Passer à `off` puis relancer `./install.sh` ramène la liste blanche à sa valeur par défaut :
  l'opt-in se retire comme il s'active.
- `--cycle-tracking` est la seule façon dont l'installeur écrit `[health].cycle_tracking`.
- `get_pregnancy_summary` (même module de `garmin-mcp`) n'est volontairement pas ajouté.
- Mode passerelle (`leanproxy`) : `leanproxy_servers.yaml` n'est réécrit que s'il est absent ;
  ajoutez les deux noms à la main à sa ligne `GARMIN_ENABLED_TOOLS` (voir
  [Configuration Garmin](garmin-setup.md)).

### Ce qui est vérifié, et ce qui ne l'est pas

- **Noms et paramètres des outils Garmin : vérifiés** dans le code de `garmin-mcp` au commit
  épinglé par `install.sh` (`src/garmin_mcp/womens_health.py`) : `get_menstrual_data_for_date(date)`
  et `get_menstrual_calendar_data(start_date, end_date)` (fenêtres de plus de 92 jours découpées
  par le serveur).
- **Forme de la réponse : non documentée.** Les deux outils renvoient le JSON brut de Garmin
  Connect, sans le structurer. Ni `garmin-mcp` ni `python-garminconnect` ne décrivent ses champs
  (le jeu d'essai de `garmin-mcp` est une simulation, pas une capture). Les agents ne retiennent
  donc une phase que si un champ la donne explicitement, et disent « phase indisponible »
  sinon — la forme réelle est à vérifier à la première utilisation.
- **intervals.icu : vérifié** dans le serveur MCP épinglé (fork `hhopke/intervals-icu-mcp` au
  commit `5cd7e1a`, #165 : `models.py`, `tools/wellness.py`) : le champ `menstrualPhase` du
  modèle wellness ressort dans `icu_get_wellness_for_date`, sous
  `other.menstrual_phase` (chaîne). Les valeurs possibles de cette chaîne ne sont pas définies
  par le serveur : à vérifier ; une valeur non reconnue est traitée comme inconnue.

## Ce que fait le coach

- **Bilan matinal** : à côté d'une HRV ou d'une FC de repos décalée, **une ligne de contexte**
  mentionne la phase (« HRV un peu basse — phase lutéale, jour 22 »). Une HRV basse avec une FC
  de repos stable en phase lutéale n'est alors pas, à elle seule, un motif d'annuler : on
  recontrôle le lendemain.
- **Agent `nutritionist`** et skill `weather-forecast` : un mot de contexte sur l'hydratation et
  la chaleur, jamais de calcul modifié, jamais de restriction calorique justifiée par le cycle.
- **Agent `medical`** : même contexte à côté de la HRV/FC de repos, et **veille RED-S** (voir
  ci-dessous).

### Ce que le cycle ne fait jamais

- Il n'est **pas une règle automatique** : aucun seuil, aucune règle de garde-fou n'en dépend.
- Il n'est **pas un diagnostic**, et les agents ne commentent ni la régularité, ni la fertilité,
  ni les hormones.
- Il ne **relâche jamais un verdict rouge** : un verdict rouge, un blocage de garde-fou, un
  signal de risque de blessure, une douleur au-dessus du seuil de consultation ou une FC de
  repos nettement élevée restent exactement ce qu'ils sont, quelle que soit la phase.
- Le style de coaching ne change pas ce fond (règle de `AGENTS.md`).

## Veille RED-S : une absence prolongée de règles

Un cycle qui disparaît chez une athlète d'endurance peut signaler un déficit énergétique
relatif (RED-S) : c'est un **signal de vigilance**, jamais un diagnostic. Quand le suivi est
activé, l'agent `medical` (ou le coach en son absence) invite à **consulter un professionnel de
santé** si l'athlète déclare ne pas avoir eu de règles depuis environ 3 mois, ou si les données
de cycle manquent depuis longtemps alors que la source devrait en fournir (une source muette ne
prouve rien : l'agent le dit).

Le seuil de 90 jours (`python3 scripts/arc_cycle.py gap --last-period AAAA-MM-JJ`) est un
repère indicatif du projet, inspiré de la définition usuelle de l'aménorrhée secondaire — une
approximation, pas un seuil diagnostique (`scripts/arc_cycle.py`, `ASSUMPTIONS`).

## Données

Les trois clés optionnelles du bloc `arc` du fichier santé (`medical/AAAA-MM-JJ_health.md`) :
`cycle_phase` (`menstrual`, `follicular`, `ovulation`, `luteal`), `cycle_day` (1 à 60) et
`cycle_source` (`garmin`, `intervals`, `manual`). Une donnée absente est une clé omise, jamais
devinée ni reportée de la veille. Ces fichiers restent dans votre workspace privé, hors du
dépôt ; aucune donnée réelle n'est jamais utilisée comme jeu d'essai du projet. Le tableau de
bord n'affiche aucune carte dédiée : l'index SQLite garde la phase dans `health_day`, et l'API
locale du tableau de bord (`/api/summary`) la retire de sa réponse.

## Sources

- Mountjoy M. et al., « 2023 International Olympic Committee's (IOC) consensus statement on
  Relative Energy Deficiency in Sport (REDs) », *British Journal of Sports Medicine*, 2023, 57,
  1073-1098. [doi:10.1136/bjsports-2023-106994](https://doi.org/10.1136/bjsports-2023-106994)
- McNulty K. L. et al., « The Effects of Menstrual Cycle Phase on Exercise Performance in
  Eumenorrheic Women: A Systematic Review and Meta-Analysis », *Sports Medicine*, 2020, 50,
  1813-1827. [doi:10.1007/s40279-020-01319-3](https://doi.org/10.1007/s40279-020-01319-3) — la
  méta-analyse trouve un effet trivial de la phase sur la performance (phase folliculaire précoce
  légèrement plus basse, taille d'effet médiane −0,06), avec des données hétérogènes : le projet
  en tire qu'il ne faut **pas** en faire une règle, seulement un contexte individuel.

Ce contenu est informatif et ne remplace pas un avis médical.
