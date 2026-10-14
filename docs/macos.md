# Application macOS

<!-- arc-video:sans-terminal -->
<div class="arc-video-card" markdown>

[![Sans terminal](video/sans-terminal/poster.jpg)](video/sans-terminal/index.html)

<div markdown>

<span class="arc-video__meta">En vidéo · Étape 18 · 1 min 39</span>

**[Sans terminal](video/sans-terminal/index.html)** — L'application macOS : un questionnaire à la place des lignes de commande, le chat intégré ou votre assistant habituel, des données qui restent chez vous, une synchronisation qui n'écrit jamais chez Garmin, et la pesée du matin lue en lecture seule.

[Regarder](video/sans-terminal/index.html) · [English](video/sans-terminal/index.html?lang=en) · [Toutes les vidéos](videos.md)

</div>

</div>
<!-- /arc-video -->

L'application **AI Running Coach** évite le clonage Git, les options de ligne de commande et le lancement manuel du tableau de bord.

## Installer

1. Téléchargez `AI-Running-Coach-<version>-unsigned.dmg` depuis la [page des versions](https://github.com/mmornati/ai-running-coach/releases/latest). Une seule image sert aux Mac Apple Silicon et Intel (macOS 13 ou plus récent).
2. Ouvrez le DMG et glissez **AI Running Coach** dans **Applications**.
3. Lancez l'application. Elle n'est pas signée par Apple : la première fois, macOS la bloque. Fermez l'alerte, ouvrez **Réglages Système → Confidentialité et sécurité**, puis cliquez sur **Ouvrir quand même** (une seule fois). En Terminal, `xattr -dr com.apple.quarantine "/Applications/AI Running Coach.app"` produit le même effet.
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

Quel que soit l'assistant, la synchronisation en arrière-plan n'écrit **jamais** côté Garmin, Intervals.icu ou Strava : les outils d'écriture de la source sont refusés un par un (Copilot : `--deny-tool` ; Gemini : `excludeTools` ; Cursor : règles `Mcp(serveur:outil)` de `.cursor/cli.json`, vérifiées avant chaque run). Avec Cursor, ces refus valent aussi en session interactive : pousser une séance vers la montre se fait alors avec un autre assistant. Le mode passerelle (`--use-leanproxy`) n'est pas pris en charge par ces assistants pour la synchronisation : utilisez le mode direct.

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

Le bouton **Synchroniser maintenant** de l'écran principal lance exactement la même opération sans attendre la prochaine heure programmée. L'application affiche son avancement puis indique si les données sont à jour ou si une connexion demande votre attention.

## Lancer le coach au quotidien

Ouvrez **AI Running Coach** depuis Applications, Spotlight ou le Dock, puis cliquez sur **Parler au coach** ou **Tableau de bord**. L'application démarre l'interface locale et ouvre le navigateur. Le serveur reste limité à `127.0.0.1` : il n'est pas exposé sur le réseau.

L'écran d'accueil permet aussi de :

- retrouver le dossier de données dans le Finder ;
- compléter plus tard le profil, l'objectif et les chaussures depuis le même questionnaire graphique ;
- relancer le diagnostic d'installation ;
- reconnecter le compte lorsque son accès expire ;
- réessayer la mise à jour du moteur si une installation a été interrompue.

## Mises à jour

L'application recherche automatiquement les nouvelles **versions publiées**.
Le menu **AI Running Coach → Rechercher une mise à jour…** permet aussi une
vérification immédiate. Dans les réglages, vous pouvez désactiver cette recherche
ou activer le téléchargement et l'installation automatiques.

Après remplacement et relancement de l'app, son moteur est mis à jour automatiquement.
Si une synchronisation est en cours, l'app attend sa fin et réessaie toutes les
30 secondes. En cas d'échec de configuration, les fichiers de l'ancien moteur sont
restaurés et un bouton permet de réessayer. Vos données personnelles restent dans
leur dossier séparé.

Les modifications de `main` arrivent à la prochaine version publiée ; elles ne
sont pas installées individuellement. Une dernière installation manuelle du DMG
est nécessaire pour passer d'une ancienne app sans ce mécanisme à la première
version qui l'intègre. Les builds de développement sans configuration de signature
Sparkle n'effectuent pas de recherche de mise à jour.
Le DMG `-unsigned` publié aujourd'hui (sans signature Apple) n'embarque pas
non plus de flux de mises à jour : installez chaque nouvelle version à la main.

## Pour les mainteneurs

Le DMG se construit sur macOS avec :

```bash
scripts/build-macos-dmg.sh
```

Voir [`macos/AI-Running-Coach/README.md`](https://github.com/mmornati/ai-running-coach/tree/main/macos/AI-Running-Coach) pour la signature Developer ID et la notarisation Apple. Le projet n'a pas de compte Apple Developer : le workflow publie donc un DMG signé ad hoc, nommé `…-unsigned.dmg`, accompagné de son empreinte `.sha256`, et ajoute aux notes de la release la marche à suivre pour l'ouvrir. Si les secrets `MACOS_CERTIFICATE_P12`, `MACOS_CERTIFICATE_PASSWORD`, `MACOS_SIGNING_IDENTITY`, `APPLE_ID`, `APPLE_TEAM_ID` et `APPLE_APP_PASSWORD` sont un jour ajoutés, le même workflow signe, notarise et publie le DMG sous son nom normal.

Sur GitHub, ces jobs sont **désactivés par défaut** : le workflow macOS (`macos-dmg.yml`) et les jobs macOS des tests ne tournent que si la variable de dépôt `ARC_MACOS_ON_GITHUB` vaut `true` (`gh variable set ARC_MACOS_ON_GITHUB --body true`). Le DMG se construit alors sur CircleCI.

Pour joindre le DMG à une release existante : onglet Actions → **Application macOS** → Run workflow, avec le tag dans le champ « tag ».

Le workflow **Tag a release** écrit le numéro dans le fichier `VERSION` (commit `chore(release)` sur `main`, qui porte le tag), d'où le DMG tire son numéro. Il crée ensuite la release officielle. Le DMG n'est construit que si le champ **« build_dmg »** est coché au lancement (il coûte des minutes macOS, facturées 10× le Linux) ; il est alors signé si les secrets Apple existent, puis joint à la release. Un tag poussé manuellement crée la release, mais **pas** le DMG, et ne réécrit pas `VERSION` : le mettre à jour soi-même avant de taguer. Pour joindre un DMG plus tard, lancez **Application macOS** avec le tag ; le workflow attend alors que la release existe.
