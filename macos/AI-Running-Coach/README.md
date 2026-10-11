# Application macOS

L'application a deux rôles :

1. au premier lancement, elle installe le moteur et recueille les préférences sans demander de Terminal ;
2. ensuite, elle sert de lanceur pour le chat, le tableau de bord, le diagnostic et le dossier de données ;
3. elle permet de compléter plus tard le profil, l'objectif et les chaussures sans revenir au Terminal.

En mode « assistant IA habituel », l'application télécharge l'installateur
officiel de l'assistant sélectionné, puis le bouton quotidien ouvre Terminal au
bon emplacement et lance directement l'assistant. Gemini utilise un runtime
Node privé à l'application afin de ne pas imposer Homebrew ou Node à l'utilisateur.

Le compte Garmin ou Intervals.icu est connecté dans une fenêtre Terminal séparée. C'est volontaire : les identifiants et le code MFA restent saisis directement dans l'outil d'authentification d'origine.

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

Le profil de notarisation se crée une fois avec `xcrun notarytool store-credentials`. Sans ces variables, le script produit une version ad hoc adaptée au développement local.

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

Configuration initiale du dépôt GitHub, en plus des secrets Apple existants :

- variable `SPARKLE_PUBLIC_KEY` : clé publique Ed25519 ;
- secret `SPARKLE_PRIVATE_KEY` : clé privée correspondante, au format exporté par
  `generate_keys` ; elle est transmise sur l'entrée standard de `generate_appcast`,
  jamais en argument ni dans l'app.

Générer et exporter ces clés avec les outils officiels de Sparkle :
[`generate_keys`](https://sparkle-project.org/documentation/). Conserver une copie
privée sécurisée : les versions déjà distribuées font confiance à cette clé.
Une publication par tag échoue explicitement si la signature Apple ou les clés
Sparkle manquent. Le déclenchement manuel sans tag reste utilisable pour un DMG local.
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
Il ne remplace aucune application installée et n'utilise ni le trousseau ni les
préférences de l'application réelle. Il tourne dans le job macOS de la CI.
La notarisation et le remplacement final d'une app Developer ID doivent également
être vérifiés lors de la première publication signée sur un Mac de recette.
