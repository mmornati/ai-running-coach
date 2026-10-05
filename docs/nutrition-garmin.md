# Apports vers Garmin Connect (opt-in)

Les apports déclarés au coach (`/log`, rapports nutrition) vivent dans `activities/` et
`nutrition/`. Garmin Connect, lui, n'en sait rien : son journal alimentaire, son hydratation et
son bilan calorique restent incomplets. Cette fonctionnalité permet au coach de **proposer** de les
y pousser, jamais de le faire de lui-même.

!!! info "Opt-in strict, désactivé par défaut"
    Tant que `[nutrition].garmin_sync` vaut `"off"` (défaut, clé absente, vide ou invalide), **rien
    n'est jamais poussé, aucun outil n'est exposé et aucun agent n'en parle**. Les utilisateurs
    existants ne voient aucun changement : la liste blanche `GARMIN_ENABLED_TOOLS` reste identique
    à l'octet près.

## Activer

```bash
./install.sh --nutrition-sync ask     # écrit [nutrition].garmin_sync = "ask" et étend la liste blanche
./install.sh --nutrition-sync off     # revient au défaut et retire les outils
```

Ou posez `garmin_sync = "ask"` sous `[nutrition]` dans `config/workspace.user.toml`, puis relancez
`./install.sh` (une relance simple respecte la configuration et n'écrit rien).

!!! warning "Mode direct uniquement"
    En mode passerelle `leanproxy`, l'outil unique `invoke_tool` ne peut pas être filtré par nom de
    sous-outil : `scripts/daily-sync.sh` ne pourrait pas interdire ces écritures en headless.
    `./install.sh --nutrition-sync ask --use-leanproxy` est donc **refusé**, et un `ask` venu de la
    configuration est ignoré (avertissement, aucun outil exposé) quand la passerelle est active.
    N'ajoutez pas ces outils à la main dans `leanproxy_servers.yaml`.

Outils ajoutés (noms, paramètres et formes vérifiés dans `garmin-mcp` au commit épinglé par
`GARMIN_MCP_REF` d'`install.sh`) :

| Rôle | Outils |
|---|---|
| Lectures | `get_custom_foods`, `get_custom_food_serving_units`, `get_nutrition_daily_food_log`, `get_nutrition_daily_meals`, `get_hydration_data` |
| Écritures (« oui » explicite) | `create_custom_food`, `log_custom_food`, `log_food`, `add_hydration_data` |

`delete_food_log`, `update_custom_food` et `upsert_and_log` ne sont **pas** exposés : une écriture
irréversible, ou qui écraserait une entrée de l'athlète, se corrige dans Garmin Connect.

## Déroulé

1. Après un `/log` ou un rapport nutrition, le coach (ou le nutritionniste) construit le plan avec
   `python3 scripts/arc_nutrition_sync.py plan` : le script décide, le modèle n'appelle que les outils.
2. Il lit d'abord (`get_custom_foods`, journal du jour, hydratation) pour ne jamais doubler une entrée.
3. Un produit du catalogue (`resources/nutrition/catalogue-produits-*.md`) devient un **aliment
   personnalisé** Garmin, créé une seule fois puis réutilisé (retrouvé par son nom exact, jamais
   deviné). Un produit hors catalogue, des calories absentes ou une heure absente : le coach
   **demande**, il ne pousse jamais une valeur inventée.
4. Il **propose** en une question et attend un « oui » explicite pour cette poussée précise.
5. Après le « oui », il écrit **une étape à la fois** et trace chaque écriture réussie dans
   `garmin_pushed` (clé, aliment, quantité, `log_id` quand il est sans ambiguïté) du bloc `arc`
   **avant l'écriture suivante** : une relance ne rejoue jamais une clé déjà tracée.

`add_hydration_data` **ajoute** au total du jour côté Garmin : seule la trace `garmin_pushed`
empêche de compter deux fois le même volume. Limite assumée : une interruption entre une écriture
Garmin et sa trace (fenêtre d'un seul appel) laisse l'écriture non tracée. Pour un aliment, la
relance la retrouve dans le journal du jour et **demande** (`confirm_duplicates`) ; pour
l'hydratation, rien ne permet de la reconnaître côté Garmin (le total du jour est affiché quand il
est lisible) : vérifiez dans Garmin Connect et corrigez-y un éventuel doublon.

## Une seule source de vérité par jour

| Situation du jour | Source de vérité | Ce qui est permis |
|---|---|---|
| Apport déclaré au coach (`nutrition/*.md`, `/log`) | les fichiers du dépôt | pousser vers Garmin (miroir, trace `garmin_pushed`) ; ne **jamais** importer ce jour depuis Garmin |
| Apport saisi dans Garmin Connect | le journal Garmin | importer sur demande (`get_nutrition_daily_food_log`) dans `nutrition/*.md` avec `intake_source: "garmin"` ; ne **jamais** pousser ce jour |

Le script refuse le sens interdit (`blocked` / `refused`). Les calories brûlées Garmin restent la
référence de dépense, inchangées.

## Limites et points à vérifier

- **Indisponible avec `[data].source = "intervals"` ou `"strava"`** : ni intervals.icu ni Strava
  n'ont de journal alimentaire ni d'hydratation équivalents ; `install.sh` n'expose aucun outil,
  le coach le dit, il ne simule rien.
- Jamais en headless : `scripts/daily-sync.sh` retire explicitement ces outils d'écriture (mode
  direct ; la passerelle `leanproxy` est refusée, voir plus haut).
- Calories d'un produit sans colonne d'énergie : approximation de 4 kcal/g de glucides, seulement
  si l'athlète l'accepte, signalée comme estimée.
- La forme de la réponse de `get_hydration_data` et des totaux de `get_nutrition_daily_food_log`
  n'est pas documentée par `garmin-mcp` : le total d'hydratation du jour n'est lu que s'il porte
  `valueInML`, les totaux importés que s'ils portent `dailyNutritionContent` — sinon omis, jamais
  estimés (à vérifier sur un compte réel).
- Le repas Garmin (petit-déjeuner, snack…) est déduit par Garmin de l'heure fournie.
