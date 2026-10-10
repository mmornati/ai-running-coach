---
name: mywhoosh-route
description: Use ONLY when `[home_trainer].platform = "mywhoosh"` and a home trainer / indoor cycling session is planned, validated or pushed — picks MyWhoosh free-ride routes whose predicted riding time fits the session duration, at the power the athlete actually holds in the target HR zone (calibrated from their own FIT power and HR by `scripts/arc_index.py power-hr`), and returns the Garmin workout name and the `virtual_route` trace for the week file. Runs skills/mywhoosh-route/scripts/mywhoosh_route.py (fetch the route catalogue once with the athlete's MyWhoosh login in a terminal, suggest offline, optionally schedule the ride in the MyWhoosh calendar after an explicit yes). Estimates only (±10 %), never a measurement; never overrides the morning check, a medical decision or the planned intensity.
---

# Skill: mywhoosh-route

Propose un parcours MyWhoosh **qui tient dans la durée** d'une séance home trainer
planifiée (ex. « Home trainer Z2 70 min »), à partir :

1. du **catalogue des parcours MyWhoosh** (nom, monde, km, D+, difficulté 1-5, boucle
   ou point à point), récupéré une fois par l'API non officielle de MyWhoosh avec le
   compte de l'athlète ;
2. de la **puissance que l'athlète tient réellement** dans la plage FC de la séance :
   `python3 scripts/arc_index.py power-hr` (relation puissance ↔ FC calibrée sur ses
   échantillons FIT vélo/home trainer, puissance par zone FC du profil, équipement et
   poids) ;
3. d'un **modèle physique** (traînée, roulement, gravité) qui convertit puissance +
   poids + masse du vélo + km + D+ en temps de parcours.

## Quand l'utiliser

- **Uniquement si `[home_trainer].platform = "mywhoosh"`** (règle de résolution habituelle :
  `config/workspace.user.toml` prime). À `off` : ne jamais parler de parcours virtuel.
- Une séance `home_trainer` / `indoor_cycling` est validée ou poussée (semaine ou jour), ou
  l'athlète demande « quel parcours MyWhoosh pour ma séance ? ».
- **Jamais** pour décider *si* la séance a lieu ni à quelle intensité : le bilan matinal
  (`[health].morning_check`), `medical` et la semaine planifiée priment. Ce skill ne
  choisit que le décor.

## Workflow

1. **Séance** : durée (`planned_duration_s`) et `intensity` dans `planning/Semaine_<lundi>.md`.
2. **Calibration** (lecture seule, hors ligne) :
   ```bash
   python3 scripts/arc_index.py power-hr > /tmp/power-hr.json      # --text pour lire
   ```
   `status` ≠ `ok` → le dire en une phrase (`reason`) : pas de puissance dans les
   échantillons (FIT téléchargés avant que la puissance soit extraite → proposer
   `python3 skills/fit-download/scripts/download_fit.py --refresh-dynamics`, ou un
   re-téléchargement `--json --overwrite` des séances vélo), ou trop peu de fenêtres
   stables. Sans calibration, seule une puissance **déclarée** par l'athlète
   (`--target-w`) est acceptable ; jamais la FTP Garmin recalculée sur une séance de
   récupération, jamais un chiffre deviné. Les zones Z4/Z5 marquées `extrapolated` sont
   hors de la plage de FC observée : moins fiables, le dire.
3. **Suggestion** (hors ligne, utilisable en headless) :
   ```bash
   python3 skills/mywhoosh-route/scripts/mywhoosh_route.py suggest \
     --duration-min 70 --intensity endurance --calibration /tmp/power-hr.json [--low-half] --text
   ```
   `--intensity` (intensité planifiée) choisit la zone FC du profil et les filtres :
   `recovery` → Z1, difficulté ≤ 1, ≤ 5 m/km ; `endurance` → Z2, difficulté ≤ 2,
   ≤ 12 m/km ; `tempo` → Z3, ≤ 3, ≤ 15 m/km ; `threshold`/`vo2max` → sans filtre.
   `--low-half` quand le bilan matinal demande le bas de la plage. `--max-m-per-km 5`
   quand une douleur ou le plan interdit la force / la danseuse. Poids et masse du vélo
   viennent de la calibration (dernière pesée, profil), surchargeables
   (`--weight-kg`, `--bike-kg`). Plusieurs tours seulement sur une boucle (`E_Circuit`) ;
   les parcours d'événement (difficulté 0) sont écartés. JSON par défaut : chaque
   parcours porte `app_path` (où le trouver : `Free Ride > Switzerland > Limmat Loop`),
   `map_url` (carte OpenStreetMap de la position indiquée par MyWhoosh, quand elle existe),
   `garmin_workout_name`, `garmin_description` et `virtual_route`.
4. **Réponse à l'athlète** (langue des réponses) : 2-3 parcours au plus, chacun avec **où
   le trouver** (`app_path` : monde puis parcours, boucle ou point à point), km, D+, tours,
   temps prévu **et sa bande ±10 %**, puissance cible ; le lien de carte (`map_url`) est un
   repère : c'est la position que MyWhoosh indique, le plus souvent le lieu réel du parcours
   mais pas toujours (ne jamais l'affirmer exacte). Puis la consigne : **la FC
   commande, pas la puissance ni le parcours** — si la FC sort de la plage, baisser la
   puissance, quitte à ne pas finir le parcours. Rappeler les consignes d'arrêt de la
   séance telles qu'écrites dans le fichier semaine, sans les assouplir. En headless,
   retenir le premier et le dire dans le résumé.
5. **Calendrier Garmin** (skill `garmin-workout-scheduling`, section « Home trainer
   route ») : `workoutName` = `garmin_workout_name` (parcours, tours et monde) ;
   `description` = `garmin_description` tel quel (où le trouver, tours, distance, temps
   prévu et bande, repère de puissance, « la FC commande », lien de carte). La cible de
   l'étape reste la plage FC (`arc_workout_targets.py`).
6. **Trace** : recopier `virtual_route` du parcours choisi dans la séance du bloc `arc`
   de la semaine (`workspace-data-contract`), puis
   `python3 scripts/arc_index.py --validate <fichier>`.
7. **Calendrier MyWhoosh** — seulement si `[home_trainer].mywhoosh_calendar = "ask"` :
   **proposer**, jamais imposer. Simulation d'abord (montre le corps exact), écriture
   seulement après un « oui » explicite, jamais en headless :
   ```bash
   python3 skills/mywhoosh-route/scripts/mywhoosh_route.py schedule --route-id 120 \
     --date 2026-10-11 --start 10:00 --duration-min 70 --name "HT Z2 70min - Limmat Loop x2"
   # puis, après le « oui » : la même commande avec --yes
   ```
   Le script vérifie d'abord le calendrier du jour (pas de doublon), écrit, puis relit.
   Le format d'une **sortie libre** n'est pas documenté (seuls ceux d'un événement et
   d'un workout le sont) : `TaskTypeId` = parcours et `MapId` = monde sont une hypothèse —
   montrer la relecture à l'athlète et lui demander de confirmer dans l'application.
   Reporter l'identifiant renvoyé dans `virtual_route.mywhoosh_task_id`.

## Connexion et catalogue

```bash
python3 skills/mywhoosh-route/scripts/mywhoosh_route.py fetch       # session interactive
python3 skills/mywhoosh-route/scripts/mywhoosh_route.py tasks 2026-10-10 2026-10-16   # lecture seule
```

- `fetch` : **interactif uniquement**, l'athlète tape lui-même son mot de passe
  (`getpass`) dans un terminal. Ne **jamais** demander le mot de passe dans le chat, ni
  le passer en argument. Jamais en headless. Le jeton d'accès est gardé en mode 600
  (`~/.config/ai-running-coach/mywhoosh-token.json`, jamais affiché) ; le catalogue est
  mis en cache (`~/.cache/ai-running-coach/mywhoosh_routes.json`). À relancer si
  MyWhoosh ajoute des parcours, ou quand le jeton a expiré (`tasks`/`schedule` le disent).
- **Une seule session par compte** : MyWhoosh refuse une connexion « depuis un autre
  appareil » tant qu'une session est active. Se connecter sur la machine qui fait tourner
  le coach, ou y copier le fichier du jeton (`scp -p`, mode 600) depuis celle déjà
  connectée. L'identifiant d'appareil est gardé dans ce fichier et réutilisé à chaque
  reconnexion : relancer `fetch` à l'échéance ne crée pas de nouvel appareil.
- Un catalogue récupéré avant l'ajout des positions n'a pas de `map_url` : relancer
  `fetch` (sans mot de passe tant que le jeton est valide).
- Les comptes MyWhoosh sans mot de passe (connexion Google / Apple) ne peuvent pas
  utiliser cette API : le dire, ne pas chercher de contournement.

## Règles

- **Estimation, jamais mesure** : toujours « temps prévu ~X (bande Y–Z) », approximation
  du projet (recoupée sur les temps publiés par mywhooshinfo.com, Alula Adventure Loop,
  1,6 à 4,0 W/kg : −6,5 % à +3,6 %).
- **Le relief change la séance** : en mode SIM, une montée fait monter puissance et FC. La
  difficulté du home trainer (*trainer difficulty*) réduit la résistance ressentie, pas le
  temps prévu. Le **drafting** (groupe, bots) accélère : le temps prévu suppose une sortie
  en solo.
- **API non officielle** (`services.mywhoosh.com`, documentée par
  https://github.com/mywhoosh-community/mywhoosh-api) : peut changer sans préavis. Une
  réponse vide ou inattendue ne remplace jamais le cache existant ; le dire.
- Aucune écriture MyWhoosh sans `[home_trainer].mywhoosh_calendar = "ask"` ET « oui »
  explicite ; jamais de suppression de tâche.

## Limites connues

- Le parcours est réduit à une montée régulière (30 % de la distance) + descente : un
  parcours très irrégulier (un col puis du plat) s'écarte davantage du modèle.
- Les séances enregistrées par la montre avec le home trainer comme capteur ont une
  « distance » propre au home trainer, sans relief MyWhoosh : elles calibrent la relation
  puissance ↔ FC, **pas** le modèle de vitesse.
- La dérive cardiaque sur une longue séance fait baisser la puissance à FC égale : la
  cible est une moyenne ; en fin de séance, la FC commande.
