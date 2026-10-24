---
name: shoes
description: Commande courte /shoes [rôle] (#302) — choisir la prochaine paire de chaussures. Sans argument, prend le rôle de la paire en fin de vie (seuil franchi ou condition rouge) et demande s'il est ambigu ; avec un argument (trail_long, trail, road_easy, road_tempo, race, mixed_long, mixed, ou ses mots courants), le rapproche du vocabulaire sans jamais deviner. Annonce le rôle et la paire remplacée, puis charge shoe-selection (continuité d'abord, plages cibles, recherche sourcée, veto medical, tableau comparatif, persistance avec l'accord de l'athlète). Interactive uniquement, jamais en headless, ne propose jamais /coach-setup, aucun achat ni lien d'affiliation ni prix. Charger quand l'athlète tape /shoes ou dit vouloir remplacer ou choisir une paire.
gemini_command: "true"
---

# `/shoes [rôle]` — choisir la prochaine paire (#302)

Ce skill n'ajoute **aucune logique de choix** : il sert à **désigner le rôle** (et la paire remplacée), puis
passe la main au skill `shoe-selection` (continuité d'abord, plages cibles `shoe-needs`, recherche
sourcée, veto `medical`, restitution, persistance). Même schéma que `/inspection` → `gear-inspection`.

## Règles fixes

- **Interactive uniquement** : jamais en mode headless (`/garmin-daily-sync`), jamais depuis un cron —
  c'est une conversation (questions, recherche en ligne, accord de l'athlète).
- **Ne propose jamais `/coach-setup`**, même sur une installation neuve (règle des commandes
  courtes, `AGENTS.md` « Premier démarrage ») : cette commande répond à une demande précise.
- **Jamais de devinette** : rôle ou paire ambigus → on demande, avec les candidats à l'appui.
- **Aucun achat, aucun lien d'affiliation, aucun prix** ; jamais présenté comme une prévention de blessure
  (« ce n'est pas un avis médical », le confort décide).
- Respecter `[language].responses`. Aucune donnée de santé n'est lue ici : indépendant de
  `[health].morning_check` et de `[data].source`.

## Sans argument — `/shoes`

1. Lancer `python3 scripts/arc_index.py gear` et `python3 scripts/arc_index.py inspections` : les paires
   **non retirées** dont `alert` est vrai (seuil franchi) ou dont la dernière inspection est `red` sont en
   fin de vie ; `near_threshold` et `orange` sont à proposer en second.
2. **Une seule paire en fin de vie** : annoncer « Je pars de <paire> (<N> km, <raison>) » et lire son rôle
   (`python3 scripts/arc_index.py shoe-usage` → `role.role`). **Plusieurs**, rôle `insufficient_data` ou
   `mixed`, **ou aucune** : dire ce qui a été trouvé et **demander** quel rôle l'athlète veut couvrir (et
   quelle paire il remplace, s'il en remplace une) — jamais choisir à sa place.
3. **Aucune paire déclarée** (`### Chaussures` vide) : le dire en une ligne, renvoyer vers la syntaxe du
   profil (`planning/Runner_Profile.md`, « Matériel & lieux » → `### Chaussures`), et continuer quand même si
   l'athlète donne un rôle (chemin « recherche », sans continuité).

## Avec argument — `/shoes trail`

Rapprocher l'argument du vocabulaire de `shoe-needs` (casse et accents ignorés) : `trail_long` (« trail long »,
« ultra »), `trail`, `road_easy` (« route facile », « récup »), `road_tempo` (« route tempo », « vite »),
`race` (« course »), `mixed_long`, `mixed`. Un argument qui ne correspond à rien ou à plusieurs rôles →
**demander**, en listant les rôles. Un argument qui est un nom de paire (`/shoes pegasus`) désigne la
**paire à remplacer** : la résoudre contre les paires déclarées (`gear_id`, nom), puis lire son rôle.

## Puis

Charger le skill **`shoe-selection`** et suivre ses étapes : continuité d'abord (bilan et fiche de la paire
remplacée), sinon plages `arc_index.py shoe-needs` puis recherche de 3 à 5 modèles sourcés, veto `medical`
s'il est dans `[agents].enabled`, tableau comparatif, « essayer en magasin : le confort décide », rodage
30-50 km avant une course, rotation, et persistance de `gear/AAAA-MM-JJ_shoe_recommendation_<rôle>.md`
**seulement** avec l'accord de l'athlète.
