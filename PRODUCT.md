# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Coureurs de trail et d'ultra-trail (francophones) qui préparent un objectif de course
(50 km, 100 km, D+ important) et utilisent un assistant IA dans leur IDE (Claude Code,
OpenCode, Gemini CLI, Cursor, Windsurf). Ils possèdent un appareil Garmin et un compte
Garmin Connect. Le visiteur du site de documentation est un coureur qui cherche à
comprendre ce que le projet apporte et à démarrer rapidement.

> **INFÉRÉ (utilisateur indisponible)** : profil déduit du brief initial (« aider les
> coureurs à préparer un objectif ») et du contenu du projet (agents coach/medical/
> nutritionist/course-strategist, Garmin uniquement).

## Product Purpose

Fournir un écosystème open-source d'agents IA et de skills qui aident un coureur à
préparer un objectif de trail : planification d'entraînement, analyse de séances Garmin,
stratégie de course, suivi santé/nutrition — le tout piloté depuis son IDE, en français,
connecté à Garmin Connect.

## Positioning

Le seul projet open-source qui transforme un IDE en staff d'entraînement complet
(coach + médecin + nutritionniste + stratège de course) connecté en direct aux données
Garmin de l'athlète, avec une installation en une commande. La documentation est le
point d'entrée : elle doit donner envie de l'essayer.

## Operating Context

- Installation via `./install.sh` (uv, garmin-mcp, garmin-mcp-auth, leanproxy-mcp, config IDE).
- Les agents persistent des fichiers Markdown en français dans des dossiers de travail
  (`activities/`, `medical/`, `nutrition/`, `planning/`, `rapports/`, `resources/`).
- Garmin Connect est la seule source de données supportée (v1).
- Documentation construite avec MkDocs + thème Material, déployée sur GitHub Pages.

## Capabilities and Constraints

- 4 agents : `coach`, `course-strategist`, `medical`, `nutritionist`.
- 8 skills : analyse GPX, comparaison de parcours, planification Garmin, météo,
  analyse de séances, Intervals.icu (secondaire), téléchargement FIT, sync Garmin.
- 100 % en français. Garmin uniquement (v1).
- Contraintes techniques : MkDocs Material, GitHub Pages, pas de backend.
- **INFÉRÉ** : le site doit rester statique (MkDocs), sans JavaScript lourd.

## Brand Commitments

- Nom : `ai-running-coach`.
- Langue : français.
- **INFÉRÉ (utilisateur indisponible)** : le brief demande un effet « wow », un site qui
  ressemble à une page marketing plutôt qu'à une simple documentation, avec des images
  libres de droits. Aucune palette ni police n'a été imposée.

## Evidence on Hand

- Contenu réel : 4 agents, 8 skills, script d'installation, docs existantes (index,
  quickstart, garmin-setup, ides, agents, skills, resources, troubleshooting, faq).
- Aucun témoignage, benchmark, prix ou donnée de démonstration réelle. Ne pas inventer
  de chiffres de performance, de témoignages ou de clients.

## Product Principles

1. La documentation est une porte d'entrée qui donne envie d'essayer, pas un manuel.
2. L'athlète et la montagne sont au centre : le design doit évoquer le trail, pas un
   produit SaaS générique.
3. La clarté d'installation et de démarrage prime sur l'expression.
4. Tout reste en français, y compris le langage visuel (pas de jargon technique gratuit).
5. Le site reste statique, rapide et accessible.

## Accessibility & Inclusion

- **INFÉRÉ** : contraste suffisant, navigation clavier, texte lisible. Aucune exigence
  spécifique confirmée.