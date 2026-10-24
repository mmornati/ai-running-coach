# Application macOS

L'application a deux rôles :

1. au premier lancement, elle installe le moteur et recueille les préférences sans demander de Terminal ;
2. ensuite, elle sert de lanceur pour le chat, le tableau de bord, le diagnostic et le dossier de données ;
3. elle permet de compléter plus tard le profil, l'objectif et les chaussures sans revenir au Terminal.

En mode « assistant IA habituel », l'application télécharge l'installateur
officiel de l'assistant sélectionné, puis le bouton quotidien ouvre Terminal au
bon emplacement et lance directement l'assistant. Gemini utilise un runtime
Node privé à l'application afin de ne pas imposer Homebrew ou Node à l'utilisateur.

Pour le chat intégré, « Connecter OpenRouter » (choix par défaut) lance
`scripts/arc_llm.py connect openrouter --json` juste après l'extraction du moteur : une page
OpenRouter s'ouvre dans le navigateur (OAuth PKCE), la clé est écrite dans
`~/.config/ai-running-coach/llm.env` sans jamais passer par l'application. L'écran d'installation
affiche l'adresse d'autorisation si le navigateur ne s'est pas ouvert et un bouton « Annuler la
connexion ». Un échec propose de réessayer, de coller une clé (« J'ai déjà une clé ») ou de
continuer sans le chat ; une clé déjà présente dans `llm.env` n'est jamais redemandée. Gemini CLI
est présenté avec la mention « clé API ou licence payante » (voir `docs/choisir-son-ia.md`).

Le compte Garmin ou Intervals.icu est connecté dans une fenêtre Terminal séparée. C'est volontaire : les identifiants et le code MFA restent saisis directement dans l'outil d'authentification d'origine. L'application n'utilise que les emplacements par défaut (`~/.garminconnect`, dossier Intervals.icu par défaut) : `--garmin-tokens` et `--intervals-dir` ne sont pas pris en charge sur son workspace.

## Construire le DMG

Depuis un Mac :

```bash
scripts/build-macos-dmg.sh
```

Le résultat est écrit dans `dist/AI-Running-Coach-<version>.dmg`. Le script compile une application universelle quand les SDK nécessaires sont disponibles, embarque uniquement les fichiers suivis nécessaires au moteur et crée un DMG avec un raccourci vers Applications.

Pour une distribution publique sans alerte Gatekeeper, configurez une identité Developer ID et un profil `notarytool` :

```bash
ARC_CODESIGN_IDENTITY="Developer ID Application: …" \
ARC_NOTARY_PROFILE="ai-running-coach" \
scripts/build-macos-dmg.sh
```

Le profil de notarisation se crée une fois avec `xcrun notarytool store-credentials`. Sans ces variables, le script produit une version signée ad hoc : c'est elle que le workflow de release publie aujourd'hui sous le nom `AI-Running-Coach-<version>-unsigned.dmg` (le projet n'a pas de compte Apple Developer), avec son empreinte SHA-256 et les instructions d'ouverture dans les notes de la release.

## Mises à jour automatiques

L'app embarque Sparkle 2.10.0 (archive officielle et SHA-256 épinglés dans
`scripts/fetch-sparkle.sh`). Le framework et ses services sont signés avant l'app.
Le menu **Rechercher une mise à jour…** et les réglages permettent la vérification
périodique et l'installation automatique facultative. Les builds locaux sans flux
ni clé publique désactivent ces actions.

La distribution suit les **releases stables**, jamais la tête de `main`. Le workflow
macOS utilise le tag pour la version visible et le numéro de workflow/tentative
comme suffixe du numéro de construction. Il publie ensemble le DMG et `appcast.xml` ;
le flux est accessible via `releases/latest/download/appcast.xml`. Les préversions
ne deviennent pas la release « Latest » et ne sont donc pas proposées sur ce canal.

Configuration du contexte CircleCI `ai-running-coach-release` :

- variable `SPARKLE_PUBLIC_KEY` : clé publique Ed25519 ;
- variable sensible `SPARKLE_PRIVATE_KEY` : clé privée correspondante, au format exporté par
  `generate_keys` ; elle est transmise sur l'entrée standard de `generate_appcast`,
  jamais en argument ni dans l'app.

Générer et exporter ces clés avec les outils officiels de Sparkle :
[`generate_keys`](https://sparkle-project.org/documentation/). Conserver une copie
privée sécurisée : les versions déjà distribuées font confiance à cette clé.
Chaque release utilise les clés Sparkle pour signer le DMG et publier le flux,
même sans compte Apple Developer. Elle échoue explicitement si une clé manque.
Le suffixe `-unsigned` indique seulement l'absence de signature Apple Developer ID ;
le DMG reste authentifié par sa signature Sparkle Ed25519. Le nom définitif du
DMG est fixé avant de générer le flux, pour que son URL pointe sur le bon fichier.
Le déclenchement manuel GitHub sans tag reste utilisable pour un DMG local.

Dans CircleCI : **Organization Settings → Contexts → ai-running-coach-release →
Add Environment Variable**. Ajouter les deux valeurs dans ce contexte de
publication, avec le jeton `GH_TOKEN` existant. Les secrets GitHub ne sont pas
transmis à CircleCI ; reprendre la même paire de clés, jamais une paire par CI.
Conserver la clé privée dans une sauvegarde sécurisée hors dépôt.

Le workflow GitHub facultatif utilise toujours la variable de dépôt
`SPARKLE_PUBLIC_KEY` et le secret `SPARKLE_PRIVATE_KEY` ; il fonctionne aussi sans
signature Apple quand `ARC_MACOS_ON_GITHUB` est activé.
Les forks utilisent automatiquement leur propre URL GitHub de distribution.

Pour un build local avec mises à jour configurées, fournir `ARC_SPARKLE_PUBLIC_KEY`
et `ARC_UPDATE_FEED_URL` (HTTPS), avec éventuellement `ARC_APP_VERSION=X.Y.Z`.
La configuration incomplète ou invalide est refusée avant signature.

Au lancement, un moteur différent est installé automatiquement par le helper
embarqué `arc_engine_update.py`. Un verrou exclusif attend la fin des synchronisations
(verrou partagé dans `daily-sync.sh`, ancien verrou PID également respecté). Un
échec de configuration restaure les fichiers de l'ancien moteur et affiche une
possibilité de réessayer. Les modifications externes déjà effectuées par
`install.sh` (services, composants installés) ne sont pas annulées. Le workspace
personnel doit rester séparé du moteur ; les préférences de version ne sont avancées
qu'après succès. La restauration ne touche pas aux journaux ni au profil de l'athlète.

### Vérification locale et CI

```bash
python3 -m unittest tests.install.test_engine_update tests.lint.test_macos_updates
scripts/test-macos-update.sh
```

Le second test construit deux vrais DMG universels avec une clé Ed25519 éphémère,
crée un flux signé, fait découvrir la nouvelle version par Sparkle sur un serveur
HTTP de boucle locale, vérifie les signatures puis vérifie le refus d'un DMG altéré.
Il lance aussi le véritable exécutable avec `--smoke-test` : toutes ses bibliothèques
sont chargées par macOS avant de quitter, sans initialiser le modèle ni lire de données.
Les builds ad hoc n'activent pas le hardened runtime (absence de Team ID) ; les
builds Developer ID le conservent. Ce test détecte les refus de chargement de Sparkle
que la compilation seule ne voit pas.
Il ne remplace aucune application installée et n'utilise ni le trousseau ni les
préférences de l'application réelle. Il tourne dans le job macOS de la CI.
La notarisation et le remplacement final d'une app Developer ID doivent également
être vérifiés lors de la première publication signée sur un Mac de recette.
