# Skill : Parcours MyWhoosh

> **Description** : propose un parcours MyWhoosh (free ride) **qui tient dans la durée** d'une séance home trainer planifiée, à la puissance que vous tenez réellement dans la plage de fréquence cardiaque de la séance.

## Pourquoi ce skill existe

Une séance « home trainer Z2 70 min » laisse un choix : quel parcours rouler ? Trop court, on tourne en rond ; trop long, on ne le finit pas ; trop vallonné, la FC sort de la zone. Ce skill croise trois choses :

1. le **catalogue des parcours MyWhoosh** (km, D+, difficulté), récupéré une fois avec votre compte ;
2. **votre** relation puissance ↔ FC, calibrée sur vos séances home trainer passées (puissance et FC des fichiers FIT) ;
3. un **modèle physique** (traînée, roulement, gravité) qui convertit puissance, poids, km et D+ en temps.

## Quand l'utiliser

- Une séance home trainer est planifiée et vous roulez sur MyWhoosh.
- Jamais pour décider *si* la séance a lieu ni à quelle intensité : le bilan matinal et l'agent `medical` priment. Le skill ne choisit que le décor.

## Activer

Dans `config/workspace.user.toml` :

```toml
[home_trainer]
platform = "mywhoosh"
mywhoosh_calendar = "ask"   # facultatif : proposer aussi l'inscription au calendrier MyWhoosh
```

Renseignez votre équipement dans le profil, section « ### Vélo & home trainer » (home trainer, vélo,
masse du vélo, FTP déclarée). Le coach s'en charge ensuite à chaque séance home trainer : il propose
deux ou trois parcours, écrit celui que vous choisissez dans le nom et la description de la séance
poussée sur votre montre Garmin, et le trace dans la semaine.

## Utilisation manuelle

```bash
# 1. Catalogue (une fois, dans un terminal : vous tapez vous-même le mot de passe)
python3 skills/mywhoosh-route/scripts/mywhoosh_route.py fetch

# 2. Puissance tenue par zone FC, calibrée sur vos séances (aussi visible dans la vue Matériel)
python3 scripts/arc_index.py power-hr --text
python3 scripts/arc_index.py power-hr > /tmp/power-hr.json

# 3. Suggestion
python3 skills/mywhoosh-route/scripts/mywhoosh_route.py suggest \
  --duration-min 70 --intensity endurance --calibration /tmp/power-hr.json --text

# 4. (facultatif) Calendrier MyWhoosh : simulation, puis --yes
python3 skills/mywhoosh-route/scripts/mywhoosh_route.py schedule --route-id 120 \
  --date 2026-10-11 --start 10:00 --duration-min 70
```

`--intensity` choisit la zone FC et la sévérité du parcours (`recovery` : plat et facile ;
`endurance` : difficulté MyWhoosh ≤ 2 ; …). `--low-half` vise le bas de la zone. `--max-m-per-km 5`
quand une douleur interdit de forcer.

## Puissance des séances passées

La puissance n'est extraite des fichiers FIT que depuis cette fonctionnalité. Pour les séances déjà
téléchargées : `python3 skills/fit-download/scripts/download_fit.py --refresh-dynamics` (fichiers
`.fit` présents) ou re-téléchargement `--json --overwrite` des séances vélo, puis
`python3 scripts/arc_index.py`.

## Confidentialité et limites

- Le mot de passe MyWhoosh est lu au terminal (`getpass`), jamais écrit ni transmis à l'assistant ; seul le jeton d'accès est gardé, en mode 600 (`~/.config/ai-running-coach/mywhoosh-token.json`) ; le catalogue des parcours est mis en cache (`~/.cache/ai-running-coach/mywhoosh_routes.json`). L'inscription au calendrier MyWhoosh n'a lieu qu'avec `mywhoosh_calendar = "ask"` et votre « oui » explicite.
- L'API utilisée n'est **pas officielle** (documentée par la communauté : [mywhoosh-api](https://github.com/mywhoosh-community/mywhoosh-api)) et peut changer sans préavis. Les comptes sans mot de passe (connexion Google / Apple) ne peuvent pas l'utiliser.
- Les temps sont des **estimations à ±10 %** (approximation du projet), recoupées sur les temps publiés par mywhooshinfo.com pour un parcours de référence. Le drafting (groupe, bots) accélère : le temps prévu suppose une sortie en solo.
- Pendant la séance, **la FC commande** : si elle sort de la plage, baissez la puissance, quitte à ne pas finir le parcours.
