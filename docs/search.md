# Recherche dans l'historique

Au fil des mois, le workspace accumule des centaines de fichiers : séances, bilans santé, décisions,
rapports, articles de `resources/`, conversations avec le coach. Pour le travail du jour, les agents
n'ont besoin de rien de plus que la date (`medical/2026-10-28_health.md`). Mais pour une question sur le
passé (« pourquoi la séance de seuil avait-elle été annulée ? », « qu'avais-je dit de mes ampoules ? »), il
leur faut retrouver le bon passage sans relire tout l'historique.

C'est le rôle de la commande `search` de l'index :

```bash
python3 scripts/arc_index.py search "douleur genou" --text
```

```text
3 résultat(s) pour « douleur genou »

## planning/2026-03-02_decision_genou-repos.md — Décision (2026-03-02 · decision)
- **Déclencheur :** médical. Douleur au genou droit à **4/10** après la sortie longue …
```

## Ce qui est cherché

| Source (`--source`) | Contenu | Type (`--kind`) |
|---|---|---|
| `workspace` | `activities/`, `medical/`, `nutrition/`, `planning/`, `rapports/`, `gear/` | le type du contrat (`activity`, `health`, `decision`, `report`, `week`…), `other` pour un fichier hors contrat |
| `resources` | votre base de connaissances `resources/` | `resource` |
| `chat` | les conversations du chat (`.arc/chat/sessions/`) : votre message et la réponse écrite du coach | `chat` |

Les fichiers sont découpés en passages (une section Markdown, coupée aux paragraphes au-delà de
1 200 caractères). La commande rend le **meilleur passage de chaque fichier**, classé par pertinence,
avec un extrait : l'agent n'ouvre le fichier que si l'extrait ne suffit pas.

## Options

| Option | Effet |
|---|---|
| `--kind activity,health` | ne garde que ces types |
| `--source workspace` | ne cherche que dans une source |
| `--since 2026-09-01` / `--until 2026-10-31` | date du fichier (nom `AAAA-MM-JJ_…`) ou de l'échange ; un passage sans date (un article de `resources/`) est alors exclu |
| `--limit N` | nombre de fichiers rendus (8 par défaut, 30 au plus) |
| `--text` | rendu lisible ; JSON par défaut, comme les autres commandes |

La question s'écrit en mots-clés plutôt qu'en phrase : les mots vides (« le », « pourquoi », « the »…)
sont ignorés, les accents aussi, et un mot long est cherché par son début (`tendinite` trouve
`tendinites`). Une expression entre guillemets reste exacte (`"côtes courtes"`). Le chat refuse `?` et `!`
dans une commande : les agents ne les écrivent pas.

## Ce que la recherche ne fait pas

- **Elle ne remplace pas les analyses.** « Depuis quand ai-je mal au genou ? » se lit dans les douleurs
  déclarées (`prevention`, tableau de bord), pas dans un extrait. Une date ou une valeur citée par un
  agent vient d'une commande d'analyse, jamais d'un extrait seul.
- **Elle ne comprend pas les synonymes.** Elle cherche des mots : « mal sous le pied le matin » ne
  trouve pas « aponévrosite ». Les agents traduisent eux-mêmes la question en mots du domaine, ce qu'ils font
  bien.
- **Rien ne quitte la machine.** L'index est dans `.arc/coach.db` (jamais versionné), reconstruit depuis
  les fichiers ; aucun service ni modèle externe n'est appelé.

## Pourquoi un index plein texte (et pas des embeddings ni un graphe)

Le choix a été mesuré sur un vrai workspace (≈ 920 documents, ≈ 0,9 million de jetons, 31 questions avec
leur fichier attendu) sur un mini-PC Intel N100 :

| Méthode | Bon fichier en tête | Dans les 5 premiers | Texte rendu à l'agent |
|---|---|---|---|
| grep sur le mot-clé qu'un agent choisirait | 39 % | 71 % | ≈ 24 000 jetons (fichiers entiers) |
| **Recherche plein texte (`search`)** | **58 %** | **77 %** | **≈ 1 000 à 2 000 jetons** |
| Embeddings multilingues légers seuls | 35 % | 55 % | ≈ 1 000 jetons |
| Hybride plein texte + embeddings | 58 % | 77 % | ≈ 1 000 jetons |

- La recherche plein texte trouve au moins aussi bien que grep et rend environ **25 fois moins de
  texte** à lire.
- Les embeddings n'aidaient que sur les questions reformulées, coûtaient 7 minutes de calcul sur ce
  matériel, une dépendance hors bibliothèque standard et un modèle de 200 Mo à 2 Go (le plus gros a
  épuisé la mémoire du serveur de test). Ils pourront être ajoutés en option si des questions réelles
  montrent qu'il en manque.
- Un graphe de connaissances ferait double emploi : les relations utiles (séance ↔ chaussure, décision
  ↔ séance, santé ↔ douleur) sont déjà dans les tables de l'index, interrogées par les commandes
  d'analyse.
