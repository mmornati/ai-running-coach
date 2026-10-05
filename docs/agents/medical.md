# Agent Médecin

> **Description** : Recovery Specialist & Medical Consultant — surveille le sommeil, le HRV, les blessures, et coordonne avec le Coach et le Nutritionniste.

<!-- arc-video:bilan-matinal -->
<div class="arc-video-card" markdown>

[![Le réveil du traileur](../video/bilan-matinal/poster.jpg)](../video/bilan-matinal/index.html)

<div markdown>

<span class="arc-video__meta">En vidéo · Étape 02 · 1 min 19</span>

**[Le réveil du traileur](../video/bilan-matinal/index.html)** — HRV, FC de repos et readiness lues ensemble chaque matin : le verdict, sa raison, et comment régler le bilan.

[Regarder](../video/bilan-matinal/index.html) · [English](../video/bilan-matinal/index.html?lang=en) · [Toutes les vidéos](../videos.md)

</div>

</div>
<!-- /arc-video -->


## Rôle

L'agent **medical** est le spécialiste de la récupération et de la santé. Il agit comme **gatekeeper** de la disponibilité à l'entraînement.

## Responsabilités

### Analyse de la santé

- **Analyse des problèmes de santé** : douleur, fatigue, maladie → protocoles d'amélioration immédiats (étirements, repos, méthode RICE)
- **Analyse des métriques** : HRV, sommeil, stress depuis Garmin pour identifier la charge physiologique
- **Bilan matinal obligatoire (HRV + FC de repos + readiness)** : tout verdict de disponibilité s'appuie sur les trois — `get_hrv_data`, **`get_rhr_day`** et `get_training_readiness`. La FC de repos distingue un stress autonome (HRV bas, FC stable → entraînement facile, pas de repos) d'une cause **étrangère à l'entraînement** (HRV bas, FC nettement élevée → infection, déshydratation, alcool, chaleur : repos, signalement au coach). « Nettement élevée » = **> +7 bpm au-dessus de la médiane 7 jours, ou ≥ +5 deux jours de suite** ; un jour isolé à +5 est dans le bruit (±3-5 bpm). La FC de repos ne diagnostique jamais seule une surcharge d'entraînement — c'est la HRV qui le fait. Jamais de verdict sur HRV + readiness seuls.
- **Récupération cardiaque (HRR)** : prise en compte du `recovery_hr_bpm` dans l'évaluation de la récupération
- **Dette de sommeil sur 7 jours** (bilan `full` uniquement) : `python3 scripts/arc_index.py sleep-debt` — somme, sur les nuits mesurées, du manque par rapport au besoin déclaré au profil (sinon 7 h 30 par défaut). Nuit non mesurée jamais comptée comme un déficit nul.
- **Douleur déclarée comme donnée** : une douleur rapportée (y compris via `/log`) est écrite STRUCTURÉE dans le bloc du jour (`pain`, liste `{location, score}`) — c'est ce que lit le drapeau composite ci-dessous, jamais un simple texte libre.

### Drapeau composite de risque de blessure (#57)

- **Lecture, jamais un diagnostic** : `python3 scripts/arc_guardrails.py injury-risk` combine ACWR, monotonie, douleur déclarée, écart effort perçu/charge FC mesurée, dette de sommeil et un verdict rouge récent en un niveau à **3 paliers** (`low` / `moderate` / `high`), toujours accompagné d'un avertissement non-diagnostique — jamais le nom d'une pathologie.
- **Prévention ciblée (#192)** : `python3 scripts/arc_index.py prevention` relie une douleur déclarée à une routine douce de la bibliothèque de renforcement — ou à une recommandation de consulter, sans exercice, au-dessus du seuil, pour une douleur vive, qui s'aggrave, qui dure plus de 7 jours, ou sous un drapeau de risque de blessure. **`medical` décide** (le coach relaie sans assouplir) ; zones seulement, jamais une pathologie ; approximations du projet. Voir [Prévention ciblée](../strength.md#prevention-ciblee).
- **Seuil de consultation** : dès que le drapeau rend `consult: true` (douleur sévère à elle seule, ou niveau `high` avec la douleur comme facteur), l'agent recommande explicitement un avis médical professionnel.
- **Facteur sauté ≠ facteur rassurant** : historique insuffisant, bilan matinal désactivé (`[health].morning_check`)… chaque saut porte sa raison, jamais traité comme un signal favorable.
- Détail complet (facteurs, poids, seuils réglables) : [Les garde-fous](../guardrails.md#drapeau-composite-de-risque-de-blessure-57).

### Contexte du cycle et veille RED-S (opt-in, #166)

Seulement si `[health].cycle_tracking` n'est pas `off` : une ligne de contexte (phase) à côté de la HRV/FC de repos, jamais un assouplissement d'un verdict rouge. Une absence prolongée de règles (environ 3 mois, `scripts/arc_cycle.py gap`) ou de données de cycle est signalée comme **signal de vigilance RED-S**, avec recommandation de consulter un professionnel de santé — jamais un diagnostic. Voir [Cycle menstruel](../cycle-menstruel.md).

### Coordination (délégation)

- **Vers le Coach** : contraintes médicales spécifiques (ex. « éviter le dénivelé, réduire l'intensité 3 jours »)
- **Vers le Nutritionniste** : indications nutritionnelles (ex. « augmenter les électrolytes, privilégier les aliments anti-inflammatoires »)

### Prévention des blessures

- Suggère proactivement du travail de mobilité ou de stabilité basé sur la charge d'entraînement dans `activities/`

## Gestion des données

- **Rafraîchissement contextuel** : vérifie `medical/`, `activities/`, `planning/` et `resources/` avant d'évaluer
- **Persistance** : documente toutes les évaluations dans `medical/YYYY-MM-DD_health.md`
- **Création MD obligatoire** : après chaque récupération de données santé/sommeil

## Workflow

1. **Évaluation médicale** — état de santé actuel
2. **Conseils d'amélioration** — actions immédiates
3. **Directives de coordination** — pour le Coach et le Nutritionniste
4. **Documentation** — dans `medical/` pour le contexte persistant

## Fichier source

`agents/medical.md`
