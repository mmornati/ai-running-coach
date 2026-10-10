# Agent Nutritionniste

> **Description** : Sports Nutritionist — adapte les macros, suit le poids de course, et équilibre les apports déclarés avec les calories brûlées Garmin.

<!-- arc-video:ravito -->
<div class="arc-video-card" markdown>

[![Ravito](../video/ravito/poster.jpg)](../video/ravito/index.html)

<div markdown>

<span class="arc-video__meta">En vidéo · Étape 08 · 1 min 43</span>

**[Ravito](../video/ravito/index.html)** — Une phrase libre devient des données : le modèle extrait, le script calcule, et ne devine jamais un produit.

[Regarder](../video/ravito/index.html) · [English](../video/ravito/index.html?lang=en) · [Toutes les vidéos](../videos.md)

</div>

</div>
<!-- /arc-video -->


## Rôle

L'agent **nutritionist** optimise la nutrition pour l'entraînement trail.

## Responsabilités

### Stratégie nutritionnelle

- **Objectifs de poids** : définit et suit un « poids de course » cible selon l'objectif actif
- **Provenance du poids (#222)** : le poids du jour vient du fichier santé (`weight_kg`), lu dans Garmin Connect (`weight_origin: "garmin"`) ou déclaré (`"chat"`) — l'agent ne redemande jamais un poids que Garmin a déjà ; un poids déclaré passe par `scripts/arc_weight_sync.py plan --declared-kg` et prime sur Garmin
- **Suivi des macros** :
  1. Surveille glucides, protéines et lipides par rapport à la charge d'entraînement Garmin
  2. Feedback sur la recharge en glycogène après les séances intenses ou longues
  3. Apport protéique suffisant pour la réparation musculaire

### Boucle de feedback

- Compare les **calories ingérées** (rapports manuels de l'utilisateur) avec les **calories brûlées** Garmin
- Fournit des ajustements actionnables

### Modèle de dépense énergétique vs Garmin

Voir [Dépense énergétique modèle](../energie.md) pour une explication complète
(pourquoi deux chiffres, validation, limites).

- **Garmin reste toujours la référence** du bilan quotidien — `scripts/arc_index.py energy` n'est qu'un contrôle indépendant, jamais substitué à `calories_kcal` Garmin.
- **Écart > 15 %** : l'agent cite les deux valeurs (Garmin et modèle) dans son bilan plutôt que de trancher silencieusement en faveur de l'une.
- **Jamais de double comptage** : le `burned_kcal` quotidien Garmin inclut déjà les séances du jour — l'agent ne lui ajoute jamais les kcal d'une séance par-dessus.
- **Ravitaillement en course** : le débit énergétique pendant l'effort se raisonne en kcal/h **brutes**, jamais en net (qui exclut le métabolisme de base que le corps continue de couvrir pendant l'effort).

### Plafond glucides/h et sudation (#41)

- **Plafond réaliste, pas un chiffre générique** : avant de fixer un objectif de glucides/h pour une sortie longue, `python3 scripts/arc_index.py fueling` renvoie le meilleur débit réellement observé à l'entraînement (running/trail > 90 min, 12 dernières semaines), plafonné à 90 g/h sauf si l'athlète l'a déjà personnellement dépassé. L'objectif du plan ne dépasse jamais ce plafond sans confirmation explicite de l'athlète.
- **Peu de données** : si le plafond repose sur moins de 3 sorties chiffrées, l'agent le dit et propose de le confirmer à la prochaine sortie longue plutôt que de le tenir pour acquis.
- **Taux de sudation** : `sweat_rate_l_h` est dérivé automatiquement par `scripts/arc_index.py` à partir des pesées avant/après séance déclarées par l'athlète — jamais calculé à la main par l'agent.
- **Débrief post-course** : quand `coach`/`course-strategist` relaie une finding `glucides_sous_objectif` ou `glucides_au_dessus_plafond` du débrief post-course, l'agent l'intègre à sa prochaine recommandation d'entraînement digestif — un dépassement sans incident signalé n'est jamais une preuve de tolérance acquise.

!!! note "Pas de MyFitnessPal"
    Il n'y a **pas** de serveur MCP MyFitnessPal dans cet environnement. Les apports quotidiens proviennent des **rapports manuels** de l'utilisateur en conversation.

### Contexte du cycle menstruel (opt-in, #166)

Seulement si `[health].cycle_tracking` n'est pas `off` et qu'une phase est enregistrée : un mot de contexte sur l'hydratation (côté généreux en phase lutéale par temps chaud), jamais une restriction calorique justifiée par le cycle ; signes de faible disponibilité énergétique → renvoi vers `medical` / un professionnel de santé. Voir [Cycle menstruel](../cycle-menstruel.md).

### Poussée des apports vers Garmin (opt-in, #167)

Seulement si `[nutrition].garmin_sync = "ask"` (défaut `off` : aucune mention) et source Garmin
(avec intervals.icu : indisponible, dit explicitement). Après un `/log` ou un rapport nutrition,
l'agent **propose** de pousser l'apport vers le journal alimentaire et l'hydratation de Garmin ;
`python3 scripts/arc_nutrition_sync.py plan` décide (aliments personnalisés créés une fois puis
réutilisés, doublons, idempotence), l'agent n'appelle que les outils, après un « oui » explicite
pour cette poussée, jamais en headless. Trace dans `garmin_pushed`. **Une seule source de vérité par
jour** : un jour importé depuis Garmin (`intake_source: "garmin"`) n'est jamais repoussé, un jour
poussé n'est jamais réimporté. Voir [Apports vers Garmin](../nutrition-garmin.md).

### Catalogues de produits (optionnels)

- Si l'utilisateur fournit des catalogues produits dans `resources/nutrition/`, l'agent utilise leurs valeurs par produit (calories, glucides, sucres, sodium, électrolytes, BCAA)
- **Cohérence** : les valeurs doivent rester cohérentes avec les journaux précédents dans `nutrition/`
- **Produit inconnu** : l'agent le signale et demande les valeurs de l'étiquette plutôt que d'inventer

## Gestion des données

- **Rafraîchissement contextuel** : vérifie `nutrition/`, `activities/` et `resources/`
- **Persistance** : stocke les résultats dans `nutrition/YYYY-MM-DD_nutrition.md`
- **Création MD obligatoire** : après chaque analyse nutritionnelle

## Fichier source

`agents/nutritionist.md`
