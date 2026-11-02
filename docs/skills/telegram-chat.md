# 💬 Skill : Coach sur Telegram (abonnement, expérimental)

> **Description** : Forme des échanges et garde-fous quand l'athlète écrit au coach depuis Telegram dans une session Claude Code *Channels* sur abonnement claude.ai (`scripts/coach-telegram-chat.sh`, **expérimental**). Réponses courtes via l'outil `reply`, **aucune écriture Garmin / COROS / intervals.icu sans « OK » explicite dans un message suivant ni approbation de la permission**, aucune suppression depuis Telegram.

## Quand l'utiliser

À chaque message reçu par le canal Telegram de la session Channels. La session est rappelée à
l'ordre par `--append-system-prompt` au démarrage. Mise en route, bot distinct et confidentialité :
[niveau 3 de la page Telegram](../telegram.md#niveau-3-conversation-sur-abonnement-claude-code-channels-experimental).
Ce skill ne concerne pas le bot `arc_telegram` (boutons sans modèle).

## Comportement

| Sujet | Règle |
|---|---|
| Réponse | Uniquement par l'outil `reply` du canal : le texte du terminal n'arrive pas sur le téléphone |
| Forme | Courte, lisible sur mobile, sans tableau large ni JSON ; renvoi au fichier MD pour le détail |
| Tâche longue | « ⏳ … » d'abord, puis `edit_message` avec le résultat |
| Questions | Posées dans Telegram, jamais par une invite du terminal (personne ne la verrait) |
| Écriture distante | Présenter la séance, demander « OK ? », n'envoyer qu'après un « OK » dans un message **suivant** ; la permission reste de plus soumise à approbation (`ask`) |
| Suppression | Interdite depuis Telegram (permissions `deny`) : Garmin Connect, Remote Control ou terminal |
| Photos | Lues depuis `~/.claude/channels/telegram/inbox/` (repas → nutritionniste) |

Toutes les règles d'`AGENTS.md` restent valables : bilan matinal selon
`[health].morning_check`, météo, fraîcheur des données, contrat `arc`, délégation limitée à
`[agents].enabled`.

## Permissions

`coach-telegram-chat.sh install` écrit `.claude/telegram-chat.settings.json` (modèle
`templates/settings.telegram.json`), passé par `claude --settings` à cette session seulement, avec un hook
`PreToolUse` en échec fermé. Il suit `config/chat-policy.toml` et `scripts/lib/sync_tools.sh` : lectures et
écritures de données (dossiers `activities/`, `medical/`, `nutrition/`, `planning/`, `rapports/`, `gear/`)
autorisées ; écritures Garmin, COROS, Strava et intervals.icu en `ask` ; suppressions, secrets et
modification des réglages en `deny`. Un `ask` est relayé à Telegram mais n'arrête pas un compte autorisé
compromis : seul `deny` tient. Détail : [niveau 3 de la page Telegram](../telegram.md#niveau-3-conversation-sur-abonnement-claude-code-channels-experimental).

## Fichier source

`skills/telegram-chat/SKILL.md`
