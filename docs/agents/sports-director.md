# Agent Directeur sportif

> **Description** : Sports Director — trouve des courses organisées (trail ou route) adaptées à la demande et à l'historique de l'athlète, et conseille sur le prochain objectif et le calendrier de saison (objectif principal, courses de préparation et courses plaisir). Chaque course vient du web, jamais inventée.

## Rôle

Le staff prépare très bien un objectif **déjà choisi** : le coach construit
l'entraînement, le stratège de course prépare le jour J. L'agent
**sports-director** s'occupe de l'étape d'avant : **quelle course, et quand ?**

| Agent | Décide |
|---|---|
| `sports-director` | *Quelle* course et *quand* |
| `coach` | *Comment* s'entraîner pour y arriver |
| `course-strategist` | *Comment* la courir le jour J |

Exemples de demandes :

- « Tu me conseilles quoi comme prochain objectif ? »
- « Je cherche un trail à faire entre amis en juin, 80 km et 1500 D+. »
- « Aide-moi à planifier ma fin de saison. »

## Responsabilités

### Prochain objectif

L'agent lit d'abord ce que vous avez **réellement** couru : plus longue sortie,
plus gros D+, débriefs de course, charge récente (`scripts/arc_index.py status`),
score Trail Shape, blessures en cours. Il propose ensuite une **marche suivante
réaliste**, souvent en deux options (« consolider » ou « monter d'une marche »),
avec le nombre de semaines de préparation nécessaire. La recherche de courses ne
vient qu'après.

### Recherche sous contraintes

- Extrait la période, la zone (par défaut le lieu du profil), la distance, le D+.
- **Faisabilité d'abord** : si la distance demandée est hors de portée à la
  date visée, il le dit clairement dès les premières lignes, faits à l'appui,
  avec l'horizon où elle deviendrait réaliste. Il ne refuse pas pour autant :
  pour une sortie entre amis, il cherche le **même événement** avec un format
  adapté (même jour, même arrivée).
- Le format proposé à la place passe la même vérification : si c'est une vraie
  marche à franchir, il dit laquelle (souvent le D+), à quelle condition
  d'entraînement, et quel format de repli.
- Il remet en question une demande incohérente, une seule fois (ex. 1500 m D+
  sur 80 km, c'est un trail très roulant).

### Rôles des courses

| Rôle | Sens |
|---|---|
| **Objectif principal** | La course pour laquelle tout le plan est construit, avec un affûtage ; candidate pour `planning/active_objective.md` |
| **Préparation** | Une course qui sert l'objectif principal (terrain, durée, ravitaillement, premier dossard), placée hors de l'affûtage |
| **Plaisir** | Course pour l'ambiance ou sortie entre amis, courue sous l'effort de course |

Les écarts entre courses sont **calculés par un script Python**, jamais de tête.
Les règles de récupération et d'affûtage sont pour l'instant des règles
provisoires, annoncées comme telles.

## Sources et garde-fous

Il n'existe **pas d'API publique** de calendrier de courses. L'agent utilise la
recherche web de l'environnement (WebSearch / WebFetch sous Claude Code,
`webfetch` sous opencode), comme vous le feriez vous-même.

- **Aucune course inventée** : chaque course vient d'une page consultée pendant
  la session.
- **Date vérifiée sur le site officiel** de l'organisateur, pour l'édition à
  venir ; sinon « à confirmer », avec la date de l'édition précédente.
- Une valeur lue sur un agrégateur est **étiquetée avec sa source**
  (« calendrier Finishers »), jamais présentée comme officielle.
- Distance, D+, prix ou état des inscriptions absents : « non trouvé », jamais
  complétés de mémoire. Un bouton « S'inscrire » visible ne prouve pas que les
  inscriptions sont ouvertes.
- **Recherche web indisponible** : l'agent le dit et vous demande des noms ou
  des liens de courses.

## Consultation du staff

L'agent peut consulter un autre agent **avant** de recommander, dans trois cas
seulement, et uniquement si cet agent est dans `[agents].enabled` :

- **`medical`** : blessure en cours ou zone fragile concernée par une course
  plus ambitieuse. Son avis l'emporte.
- **`coach`** : quand la recommandation dépend d'une condition d'entraînement
  (« 3 séances par semaine dès l'hiver »), pour la course finale seulement.
- **`course-strategist`** : quand vous hésitez entre une ou deux finalistes dont
  le parcours est disponible.

Lancé lui-même comme sous-agent, il ne peut pas en lancer d'autres : il note
alors la question (« À valider avec le coach : … ») pour la session principale.

## Ce qu'il ne fait pas

- Il **ne modifie jamais** `planning/active_objective.md` ni
  `planning/Runner_Profile.md` : il propose les valeurs à reporter.
- Il **ne persiste rien** pour l'instant : le contrat de données n'a pas encore
  de type pour une sélection de courses.
- Il ne pousse rien vers Garmin ou intervals.icu.
- Il ne tourne jamais en headless (`garmin-daily-sync` ne l'appelle pas).

## Fichier source

`agents/sports-director.md`
