# Application macOS

L'application **AI Running Coach** évite le clonage Git, les options de ligne de commande et le lancement manuel du tableau de bord.

## Installer

1. Téléchargez `AI-Running-Coach-<version>.dmg` depuis la page des versions.
2. Ouvrez le DMG et glissez **AI Running Coach** dans **Applications**.
3. Lancez l'application.
4. Renseignez votre prénom, votre année de naissance, votre expérience, vos disponibilités et votre lieu d'entraînement ; les blessures, données physiologiques et préférences personnelles sont proposées juste en dessous mais peuvent attendre.
5. Décrivez votre course et votre objectif. Si vous n'en avez pas encore, indiquez-le : la première conversation pourra servir à les définir.
6. Choisissez votre source sportive, votre pratique, vos sports croisés, le ton et la longueur des retours, les unités, votre équipe et la façon de parler au coach.
7. Cliquez sur **Installer mon coach**.

Sur un Mac neuf, macOS peut proposer une fois ses outils système gratuits (Git et Python). Acceptez leur installation, puis cliquez sur **Réessayer** dans AI Running Coach ; aucun réglage technique n'est demandé.

L'application place :

- le moteur dans `~/Library/Application Support/AI Running Coach/engine` ;
- vos données, par défaut, dans `~/Documents/AI Running Coach` ;
- les jetons Garmin dans `~/.garminconnect`, comme l'installation classique.

Vos séances, données de santé et plans ne sont donc jamais enfermés dans l'application. Une mise à jour ou une suppression de l'app ne supprime pas le dossier de données.

L'assistant remplit aussi `planning/Runner_Profile.md` et `planning/active_objective.md` avec les réponses fournies. Dans le volet facultatif, on peut saisir les performances, allures, VO2max, données physiologiques, blessures, motivations, sujets sensibles, sports croisés et plusieurs paires de chaussures avec leur date d'achat, kilométrage initial, usage et seuil d'usure. La première paire devient la paire par défaut si aucune ne l'était déjà.

L'application passe par le même moteur que `/coach-setup` : un champ déjà rempli n'est jamais remplacé silencieusement, une paire existante n'est pas dupliquée et les libellés officiels du profil ou de l'objectif ne sont jamais renommés.

## Parler au coach

Deux modes sont proposés pendant l'installation :

- **Chat intégré** : l'application installe le composant nécessaire et affiche ensuite **Parler au coach**. Il faut une clé OpenRouter, facturée à l'usage, et un plafond quotidien. La clé est conservée uniquement sur le Mac dans `~/.config/ai-running-coach/llm.env`, en mode privé ; elle n'est jamais placée dans le dossier de données ni affichée dans les journaux.
- **Assistant IA habituel** : choisissez Claude Code, GitHub Copilot, OpenCode, Gemini CLI ou Cursor Agent. L'application installe automatiquement l'outil et prépare ses agents et sa connexion aux données, sans activer OpenRouter.

La synchronisation Garmin ou Intervals.icu en arrière-plan est toujours activée. Avec le chat intégré, elle réutilise OpenCode, la même clé OpenRouter et le plafond quotidien de synchronisation. Avec un assistant habituel, elle utilise le mode non interactif de l'assistant choisi — Claude Code, Copilot, OpenCode, Gemini ou Cursor — et donc le même compte, sans installer ni facturer un second fournisseur en secret. Une seule connexion initiale à cet assistant peut être demandée ; il n'a ensuite pas besoin de rester ouvert.

Dans ce second mode, il n'y a aucune commande à recopier. Après l'installation,
**Parler au coach avec…** ouvre Terminal directement dans le dossier de données
et lance l'assistant choisi. Au premier lancement seulement, celui-ci affiche sa
propre connexion (compte Claude, GitHub, Google, etc.) ; les lancements suivants
arrivent directement dans la conversation. Le Terminal reste visible parce
qu'il constitue l'interface de ces assistants, mais l'utilisateur n'a ni `cd`
ni commande d'installation à saisir.

Le chat intégré envoie les messages et le contexte utile au fournisseur du modèle. Le compte Garmin ou Intervals.icu reste une connexion distincte.

## Connecter le compte sportif

Après l'installation, cliquez sur **Connecter mon compte**. Une fenêtre dédiée demande directement les informations Garmin Connect ou la clé Intervals.icu. Le mot de passe, la clé et le code MFA ne transitent pas par l'interface de l'application.

Revenez ensuite dans l'app : l'état de connexion est vérifié lorsqu'elle reprend le premier plan.

Une fois le compte connecté, le service de synchronisation installé par l'application récupère les nouvelles données aux heures configurées. Garmin et Intervals.icu utilisent la même source choisie pendant l'installation ; les données récupérées sont persistées dans le dossier de travail avant d'être affichées par le coach ou le tableau de bord.

## Lancer le coach au quotidien

Ouvrez **AI Running Coach** depuis Applications, Spotlight ou le Dock, puis cliquez sur **Parler au coach** ou **Tableau de bord**. L'application démarre l'interface locale et ouvre le navigateur. Le serveur reste limité à `127.0.0.1` : il n'est pas exposé sur le réseau.

L'écran d'accueil permet aussi de :

- retrouver le dossier de données dans le Finder ;
- compléter plus tard le profil, l'objectif et les chaussures depuis le même questionnaire graphique ;
- relancer le diagnostic d'installation ;
- reconnecter le compte lorsque son accès expire ;
- mettre à jour le moteur, lorsqu'une nouvelle version de l'application en contient un, sans effacer les données personnelles.

## Pour les mainteneurs

Le DMG se construit sur macOS avec :

```bash
scripts/build-macos-dmg.sh
```

Voir [`macos/AI-Running-Coach/README.md`](https://github.com/mmornati/ai-running-coach/tree/main/macos/AI-Running-Coach) pour la signature Developer ID et la notarisation Apple. Un DMG public doit être signé et notarié ; la signature ad hoc produite sans identité sert uniquement aux tests locaux.

Le workflow **Tag a release** crée d'abord la release officielle, puis appelle le workflow macOS qui construit, signe et ajoute le DMG. Un tag poussé manuellement déclenche les deux workflows séparément ; le workflow macOS attend alors que la release existe avant d'y joindre le fichier.
