# Le brief Horae

[Horae](https://github.com/horae-dev/horae) prépare une note du matin à partir de plusieurs
services. Son plugin [`mcp-brief`](https://github.com/horae-dev/plugin-mcp-brief) appelle un outil
MCP nommé `brief` sur chaque service et en tire **une section de la note**, des **tâches** et, pour
les seules alertes critiques, **une notification**.

Le tableau de bord expose cet outil sur `https://<votre-hôte>/mcp`. Le coach apparaît alors dans la
note du matin : séance du jour, feu du bilan matinal, chaussures à surveiller, ressenti à noter,
semaine à planifier, plan de course à relire. Rien d'autre ne change : le tableau de bord reste en
lecture seule et le reste du site reste derrière votre SSO.

## Ce que contient le brief

Le document suit le contrat **brief v1** de Horae
([`brief-contract.md`](https://github.com/horae-dev/plugin-mcp-brief/blob/main/docs/brief-contract.md)).
Il est rédigé dans la langue de vos documents (`[language].documents`, français par défaut).

**Titre** : « Aujourd'hui : Trail endurance 1 h 10 · 12 km · 450 m D+ · feu vert, readiness 72 ».
La séance est décrite par son sport, son intensité, sa durée, sa distance et son D+, jamais par son
titre. Le feu et la readiness viennent du bilan matinal du jour (« bilan matinal pas encore fait »
sinon, rien du tout si `[health].morning_check = "off"`). Une consigne du bilan sur la séance
(alléger, remplacer, annuler) est ajoutée, ainsi que la prochaine course si elle a lieu dans 14 jours
ou moins.

**État** : `ok`, ou `degraded` quand la synchronisation automatique est en retard, en échec ou n'a
jamais tourné (vue [Synchro](views.md)). Horae affiche alors la raison à côté du titre.

**Alertes** (clés stables, Horae dédoublonne dessus) :

| Clé | Gravité | Quand |
|---|---|---|
| `sync.failing` | **crit** | La synchronisation est en retard ou en échec **et** le dernier run réussi (ou le dernier sondage, en mode surveillance) date de plus de 24 h. C'est la seule alerte poussée sur le téléphone. |
| `sync.late` | warn | Synchronisation en retard ou en échec depuis moins de 24 h, ou sondage en pause. |
| `sync.never` | warn | Aucune synchronisation dans les 14 derniers jours. |
| `readiness.low` | warn | Bilan du jour rouge, ou readiness sous 30. |
| `hrv.below_baseline` | warn | Moyenne HRV des 7 dernières nuits sous votre bande personnelle de 60 jours. |
| `rhr.elevated` | warn | FC de repos 7 bpm ou plus au-dessus de la médiane des 7 jours précédents (le seuil « alerte » de la vue Santé). |
| `shoe.<id>.retire` | warn | Paire active au-delà de son seuil d'usure. |
| `shoe.<id>.near` | warn | Paire active à 90 % de son seuil, avec la date prévue quand elle est calculable. |

Les alertes de santé sont des **constats chiffrés**, pas des avis : la décision de séance reste celle
du coach et des [garde-fous](../guardrails.md).

**Tâches** (identifiants stables : une tâche n'est créée qu'une fois) :

| Identifiant | Quand | Échéance |
|---|---|---|
| `feedback.<date>` | Une séance d'hier ou d'aujourd'hui (hors repos et marche) n'a pas de RPE : « Noter le ressenti de la séance du 24/11 (/log) ». | aujourd'hui |
| `plan.week.<lundi>` | Du vendredi au dimanche, si rien n'est planifié la semaine suivante. | le dimanche |
| `race.review.<date>` | Course dans 14 jours ou moins, plan de course présent : le relire. | 3 jours avant |
| `race.plan.<date>` | Même chose sans plan de course : le préparer. | 3 jours avant |

**Liens** : tableau de bord, Semaine, Santé, Synchro (quand elle pose problème). Ils pointent vers
`https://<ARC_DASHBOARD_HOST>/` (ou `HORAE_BRIEF_BASE_URL`), à déclarer comme `link_prefix` dans
Horae.

Le brief est valable jusqu'à minuit (au plus 12 h). Exemple produit par les tests :

```json
{
  "schema_version": 1,
  "service": {"id": "ai-running-coach", "name": "Coach running"},
  "generated_at": "2026-11-27T06:30:00+01:00",
  "valid_until": "2026-11-27T18:30:00+01:00",
  "status": {"state": "ok"},
  "headline": "Aujourd'hui : Trail endurance 1 h 10 · 12 km · 450 m D+ · feu vert, readiness 72 · Trail des Collines dans 9 j",
  "alerts": [
    {"key": "shoe.speedgoat.retire", "severity": "warn", "title": "Chaussures à remplacer : Hoka Speedgoat 5",
     "body": "712 km pour un seuil de 700 km.", "link": "https://coach.example.org/#/materiel"}
  ],
  "tasks": [
    {"id": "feedback.2026-11-26", "title": "Noter le ressenti de la séance du 26/11 (/log)",
     "due": "2026-11-27", "link": "https://coach.example.org/#/seances"},
    {"id": "race.review.2026-12-06", "title": "Relire le plan de course : Trail des Collines (06/12)",
     "due": "2026-12-03", "link": "https://coach.example.org/#/roadbook"}
  ],
  "links": [
    {"label": "Tableau de bord", "url": "https://coach.example.org/"},
    {"label": "Semaine", "url": "https://coach.example.org/#/semaine"},
    {"label": "Santé", "url": "https://coach.example.org/#/sante"}
  ]
}
```

## Ce qui n'en sort jamais

Seulement des agrégats et des libellés fixes. Ne sortent **pas** : traces GPS, échantillons, valeurs
brutes de HRV ou de sommeil, titres et notes de séance, motif du verdict, notes médicales, journaux
de synchronisation, chemins de fichiers. Les seuls noms repris tels quels sont ceux que vous avez
donnés à une paire de chaussures et à une course. La note de Horae peut être synchronisée et
sauvegardée : c'est pour cela que le brief reste aussi pauvre.

## Mise en route (Docker, derrière Traefik)

1. **Créez le jeton** sur l'hôte, lisible par le seul propriétaire du workspace :

    ```bash
    umask 077
    openssl rand -hex 32 > ~/.config/ai-running-coach/horae-brief.token
    ```

    32 caractères au moins (lettres, chiffres, `. _ ~ + / = -`) ; un jeton plus court désactive le
    point d'entrée, avec un avertissement dans les journaux du conteneur.

2. **Activez le complément** dans `deploy/dashboard/.env` :

    ```bash
    COMPOSE_FILE=compose.yaml:compose.authentik.yaml:compose.brief.yaml
    HORAE_BRIEF_TOKEN_FILE_HOST=/home/moi/.config/ai-running-coach/horae-brief.token
    ```

    puis `scripts/update-docker.sh` (ou redéployez depuis votre outil, Coolify par exemple, en y
    ajoutant `compose.brief.yaml`).

3. **Déclarez le service dans Horae** : le même jeton dans un secret `MCP_BRIEF_TOKEN_1`, puis :

    ```yaml
    - mcp-brief.collect:
        services:
          - id: coach
            url: https://coach.example.org/mcp
            token_secret: MCP_BRIEF_TOKEN_1
            link_prefix:
              - https://coach.example.org/
    ```

    Approuvez l'hôte dans `horae.lock`, et listez `https://coach.example.org/` dans le `link_prefix`
    des entrées `tasks` et `notify` du pipeline.

Sans Docker (`arc_serve.py` lancé à la main ou par `install.sh`), les mêmes variables suffisent :
`HORAE_BRIEF_TOKEN_FILE=<fichier>` (ou `HORAE_BRIEF_TOKEN=<jeton>`), et `HORAE_BRIEF_BASE_URL` si
les liens doivent pointer ailleurs que vers le premier nom déclaré par `--allowed-host`. Horae
n'accepte que du `https` avec un nom DNS : il faut donc un reverse proxy devant.

## Ce que fait le déploiement

`compose.brief.yaml` ajoute un seul routeur Traefik, `arc-dashboard-mcp` :

| Règle | SSO | Protection |
|---|---|---|
| `Host(<ARC_DASHBOARD_HOST>) && Path(/mcp) && Method(POST)` | **non** | jeton porteur, débit limité (30 requêtes/min, rafale 10), priorité 300 |

Tout le reste, `/mcp` en GET compris, reste sur le routeur `arc-dashboard` et donc derrière le
middleware d'authentification. Même schéma que le routeur `arc-chat-approve` du chat
([Chat derrière Traefik](https://github.com/mmornati/ai-running-coach/blob/main/deploy/chat/traefik/README.md)).

## Sécurité

- **Jeton obligatoire.** Sans jeton configuré, `/mcp` n'existe pas (404). Avec un jeton, toute
  requête sans `Authorization: Bearer <jeton>` exact reçoit 401. La comparaison se fait en temps
  constant (empreintes SHA-256 comparées par `hmac.compare_digest`).
- **Rien dans les journaux.** Le serveur ne journalise aucune requête ; ni le jeton, ni le corps ne
  sont écrits nulle part, et un message d'erreur ne cite jamais une donnée.
- **Surface minimale.** Un seul outil (`brief`), en lecture seule ; aucune ressource, aucun prompt.
  POST seulement (405 sinon), JSON seulement (415), corps de 64 Kio au plus (413), pas de lot,
  pas de session. `Host` doit être le nom déclaré ; un en-tête `Origin` d'une autre origine est
  refusé (403).
- **Réponse bornée.** Le document fait au plus 24 Kio (10 alertes, 10 tâches, 5 liens), bien sous la
  limite de 64 Kio de Horae, et n'est jamais compressé.
- **Lecture seule.** Le brief lit l'index en mémoire et les journaux de synchronisation, comme les
  autres vues ; le conteneur garde son système de fichiers et son workspace en lecture seule.
- **Mode famille** : le brief n'est pas disponible (un document par athlète demanderait un jeton par
  membre) ; le point d'entrée reste désactivé.

Changer de jeton : remplacez le fichier, redémarrez le conteneur, mettez à jour le secret dans Horae.

## Vérifier

```bash
TOKEN=$(cat ~/.config/ai-running-coach/horae-brief.token)
curl -s https://coach.example.org/mcp \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"brief","arguments":{"schema_version":1}}}'
```

Sans l'en-tête `Authorization`, la réponse doit être `401`. Une redirection vers la page de connexion
du SSO veut dire que le routeur `arc-dashboard-mcp` n'est pas actif (fichier absent de
`COMPOSE_FILE`, ou méthode autre que POST) ; un `404` que le conteneur n'a pas trouvé de jeton
(`docker logs ai-running-coach-dashboard` le dit, sans l'afficher).

Côté code : `scripts/arc_brief.py` (document et protocole), `brief_facts` et `POST /mcp` dans
`scripts/arc_serve.py`, tests dans `tests/data/test_arc_brief.py` (schéma v1 copié dans
`tests/data/fixtures/horae_brief/`).
