# Skill : `/shoes` — choisir la prochaine paire

> **Description** : Commande courte pour choisir la prochaine paire de chaussures : désigner le rôle (et la paire remplacée), puis laisser [`shoe-selection`](shoe-selection.md) mener la continuité, la recherche sourcée, le veto médical et la restitution.

## Comment la lancer

| Vous écrivez | Ce qui se passe |
|---|---|
| `/shoes` | Le coach prend le rôle de la paire en fin de vie (seuil d'alerte franchi ou dernière inspection 🔴) ; s'il y en a plusieurs, ou aucune, il vous demande |
| `/shoes trail` | Un rôle précis : `trail_long`, `trail`, `road_easy`, `road_tempo`, `race`, `mixed_long`, `mixed` (ou leurs mots courants : « route tempo », « course »…) |
| `/shoes pegasus` | Le nom d'une paire à remplacer : le coach la retrouve parmi vos paires déclarées et lit son rôle |
| « Je dois remplacer mes Speedgoat » | Même chose en langage naturel |

Un argument ambigu ou inconnu : le coach **demande**, il ne devine jamais.

## Garde-fous

- Commande **interactive** : jamais lancée en mode headless, jamais proposée par `/garmin-daily-sync`.
- Comme les autres commandes courtes, elle ne propose **jamais** `/coach-setup`.
- Aucun achat, aucun lien d'affiliation, aucun prix ; jamais une prévention de blessure.
- Aucune donnée de santé lue ici : indépendante de `[health].morning_check` et de `[data].source`.

Le déroulé complet est dans [`shoe-selection`](shoe-selection.md) et [Choisir ses chaussures](../shoes.md#choisir-la-prochaine-paire-shoes).

## Fichier source

`skills/shoes/SKILL.md`
