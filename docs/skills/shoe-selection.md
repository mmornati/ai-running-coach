# Skill : `shoe-selection` — choisir la prochaine paire

> **Description** : Choisir la prochaine paire de chaussures, lancé par la commande courte [`/shoes`](shoes.md). La continuité d'abord (la version actuelle du modèle qui vous a convenu, comparée à l'ancienne), sinon des plages cibles sourcées puis 3 à 5 modèles trouvés en ligne, chaque caractéristique avec sa source — jamais d'achat, jamais de prix, jamais une prévention de blessure.

## Quand l'utiliser

- Une paire arrive en fin de vie (seuil d'alerte franchi, ou dernière inspection 🔴) et vous voulez savoir par quoi la remplacer
- Vous tapez `/shoes` ou dites vouloir choisir ou remplacer une paire
- Une paire vient de passer à `(retirée)` et son bilan est écrit

## Le déroulé

1. **Le rôle** : celui de la paire en fin de vie, sinon le coach vous demande (route facile, route tempo, trail, trail long, course…).
2. **Continuité d'abord** : si la paire remplacée a `would_rebuy = yes`, un confort d'au moins 7 et aucun problème attribué, le coach propose **la version actuelle du même modèle** et la compare, ligne à ligne, à l'ancienne. Avec `yes_with_change`, c'est le modèle le plus proche qui corrige le point demandé.
3. **Sinon, la recherche** : plages cibles de `shoe-needs`, puis 3 à 5 modèles cherchés en ligne à la demande (laboratoire, marque, revendeurs ; jamais de scraping). Chaque valeur a son URL et son type (`measured` ou `manufacturer`) ; la mesure prime ; une valeur introuvable reste absente ; une valeur hors plage est signalée.
4. **Le veto médical** : l'agent `medical`, s'il est installé, peut écarter un candidat (antécédents tendineux, entorses) ; sinon le coach applique les règles et le dit : *ce n'est pas un avis médical*.
5. **Le tableau comparatif**, puis : essayer en magasin (le confort décide), rodage de 30 à 50 km avant une course, rotation d'au moins deux paires.
6. **La trace**, seulement avec votre accord : `gear/AAAA-MM-JJ_shoe_recommendation_<rôle>.md` (type `shoe_recommendation`).

Rien n'est proposé pendant la synchronisation automatique (`garmin-daily-sync`) : c'est une conversation.

## Garde-fous

- **Aucun achat, aucun lien d'affiliation, aucun prix.**
- **Jamais une prévention de blessure** : les études sont observationnelles, le confort perçu décide. Détail et niveaux de preuve : [Choisir ses chaussures](../shoes.md#ce-que-disent-les-preuves).
- **Aucune caractéristique inventée** ni reprise d'un modèle ou d'une version voisine.
- Le skill ne calcule rien : il lit `shoe-needs`, `shoe-specs`, `shoe-feedback` et `shoe-usage`.

## Fichier source

`skills/shoe-selection/SKILL.md`
