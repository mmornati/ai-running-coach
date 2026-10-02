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
