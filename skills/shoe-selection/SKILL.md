---
name: shoe-selection
description: Choisir la prochaine paire de chaussures (#302), lancé par la commande courte /shoes [rôle] (skill shoes). Rôle par défaut = celui de la paire en fin de vie, sinon on demande. Continuité d'abord : would_rebuy = yes, confort >= 7 et aucun problème attribué → version actuelle du même modèle, specs comparées à l'ancienne ; yes_with_change → modèle le plus proche qui corrige ce point. Sinon plages cibles (arc_index.py shoe-needs) puis recherche web de 3 à 5 modèles, chaque spec sourcée et typée measured/manufacturer, jamais inventée. Veto de medical s'il est activé, sinon « ce n'est pas un avis médical ». Essayer en magasin (le confort décide), rodage 30-50 km, rotation. Aucun achat, lien d'affiliation ni prix ; jamais une prévention de blessure. Interactive uniquement, jamais en headless, ne propose jamais /coach-setup. Persiste gear/AAAA-MM-JJ_shoe_recommendation_<rôle>.md avec l'accord de l'athlète. Charger depuis /shoes ou quand l'athlète veut remplacer ou choisir une paire.
---

# Choisir la prochaine paire (#302) — lancé par `/shoes [rôle]`

Ce skill **assemble** les briques de l'épopée #297 : fiches de caractéristiques (`shoe-specs`), retours de
chaussant et bilan de retraite (`shoe-feedback`), profil d'usage (`shoe-usage`) et plages cibles fondées sur
les preuves (`shoe-needs`). Il ne calcule rien lui-même : **les nombres viennent des commandes**, il les lit
en JSON et mène la conversation. Ordre des critères : **confort → continuité → garde-fous blessures →
adéquation au terrain** ; les caractéristiques ne font que restreindre ou avertir. Il ne « déduit » jamais la
chaussure idéale de la foulée ni du type de pied.

## Règles fixes (à tenir sans exception)

- **Interactive uniquement** : jamais en mode headless (`/garmin-daily-sync`), jamais depuis un cron —
  c'est une conversation (questions, recherche en ligne, accord de l'athlète).
- **Ne propose jamais `/coach-setup`**, même sur une installation neuve (règle des commandes courtes,
  `AGENTS.md` « Premier démarrage ») : cette commande répond à une demande précise.
- **Aucun achat, aucun lien d'affiliation, aucun prix, aucune alerte de prix.** On cite des sources de
  caractéristiques (laboratoire, marque), jamais un lien de vente mis en avant ni un tarif.
- **Jamais une prévention de blessure.** Une recommandation n'« évite » rien : les plages restreignent ou
  avertissent, les études sont observationnelles (corrélation, pas causalité) et **le confort perçu décide**.
  Chaque restitution se termine par « ce n'est pas un avis médical ».
- **Aucune caractéristique inventée.** Chaque valeur d'un candidat a une URL consultée, une date
  (`retrieved`) et un type (`measured` laboratoire | `manufacturer` marque). Valeur introuvable = **absente**,
  dite « introuvable », jamais estimée ni reprise d'un modèle voisin ou d'une autre version.
- **Jamais de devinette** sur le rôle, la paire ou la version : ambigu → on demande.
- Aucune écriture dans `gear/` avant l'**accord explicite** de l'athlète sur la restitution montrée.
- Respecter `[language].responses` ; le fichier écrit reste en `[language].documents`.
- Aucune donnée de santé n'est lue pour cette commande, hors le contrôle de veto ci-dessous : indépendant de
  `[health].morning_check` et de `[data].source`.

## Les commandes qui donnent les faits

Toujours avec le JSON par défaut (ajouter `--text` pour montrer un résultat à l'athlète). Ne lire que les
clés citées ; si une clé manque, c'est une donnée absente, pas une erreur à contourner.

```bash
python3 scripts/arc_index.py gear                      # paires, kilométrage, alert / near_threshold, retired
python3 scripts/arc_index.py inspections               # dernière inspection de chaque paire (condition)
python3 scripts/arc_index.py shoe-usage                # rôle déduit de chaque paire (role.role), usage
python3 scripts/arc_index.py shoe-specs --gear ID      # fiche : fields (valeur, source_type, url, alternatives), brand, model, version
python3 scripts/arc_index.py shoe-feedback --gear ID   # verdict (would_rebuy, comfort_overall, change_wanted), comfort, issue_counts
python3 scripts/arc_index.py shoe-needs --role ROLE [--replace ID]   # plages cibles, règles, niveaux de preuve, avertissements
```

`shoe-needs` rend : `targets` (par caractéristique : `min`/`max` ou `allowed`, `rules`, `reasons`,
`confidence`, `references`), `options`, `reminders` (rotation), `warnings` (dont « données insuffisantes »),
`notes`, `disclaimer`, `insufficient_data`. Ses niveaux de preuve sont ceux de la sortie (`high`,
`moderate`, `low`, `expert_opinion`, `none` = approximation du projet) : les recopier tels quels, ne jamais
en citer d'autres, ne jamais citer une étude qui n'est pas dans ses `references`.

## 1. Le rôle

Rôles : `trail_long`, `trail`, `road_easy`, `road_tempo`, `race`, `mixed_long`, `mixed` (vocabulaire de
`shoe-usage` / `shoe-needs`).

1. **Argument donné** (`/shoes trail`) : le rapprocher du vocabulaire ci-dessus (« trail long » →
   `trail_long`, « route tempo » → `road_tempo`, « course » → `race`). Un terme qui ne correspond à rien
   ou à plusieurs rôles → **demander**, en listant les rôles.
2. **Sans argument** : le rôle de **la paire qui arrive en fin de vie**. Une paire non retirée y est si
   `gear` la marque `alert` (seuil franchi), ou si sa dernière inspection (`inspections`, `latest.condition`)
   est `red` ; `near_threshold` / `orange` la rendent candidates, à proposer en second. Son rôle est
   `shoe-usage` → `role.role` de cette paire.
3. **Plusieurs paires candidates, rôle `insufficient_data` ou `mixed`, ou aucune paire en fin de vie** →
   ne rien déduire : annoncer ce qui a été trouvé et **demander** quel rôle l'athlète veut couvrir (et
   quelle paire il remplace, s'il en remplace une).
4. Annoncer le rôle retenu et la paire remplacée (`gear_id`, nom, kilométrage) avant de continuer.

## 2. Continuité d'abord

Lire le bilan de la paire remplacée : `shoe-feedback --gear <ID>` (`verdict`, `comfort`, `issue_counts`) et sa
fiche `shoe-specs --gear <ID>` (marque, modèle, version, caractéristiques). Sans fiche ou sans bilan, il n'y a
pas de continuité à proposer : on passe au chemin « recherche » (§3) en disant pourquoi, et on **propose**
d'abord de compléter la fiche (`shoe-specs`) ou le bilan.

| Situation de la paire remplacée | Chemin |
|---|---|
| `would_rebuy = yes`, `comfort_overall >= 7` **et** aucun problème attribué (`issue_counts` vide) | **Continuité** : proposer **la version actuelle du même modèle** |
| `would_rebuy = yes_with_change` | **Continuité corrigée** : le modèle le plus proche qui corrige le point de `change_wanted` (ex. `wider_toe_box` → même famille avec avant-pied plus large) |
| `would_rebuy = no`, confort < 7, ou problèmes attribués | **Recherche** (§3) ; la paire remplacée n'est pas une référence de continuité |

**Même modèle, version actuelle.** Chercher la dernière version commercialisée (page de la marque, puis
laboratoire). Les marques changent le drop, la pile et le chaussant d'une version à l'autre (un avis
« UG2 → UG3 » sur le maintien du talon le montre) : **comparer toujours** les caractéristiques de la version
actuelle à celles de la fiche de l'ancienne, ligne à ligne, dans un tableau « ancienne / actuelle / écart ».
Un écart de drop de plus de ~4 mm ou un changement de largeur d'avant-pied est **signalé** : la continuité
n'est plus garantie, et on ne dit pas « même chaussure ». Si la version actuelle est la même que celle de la
fiche, le dire.

**`yes_with_change`.** Partir du modèle de la fiche, chercher dans la même famille (autre version, autre
largeur, modèle voisin de la marque) ce qui corrige le point demandé, sans écarter une autre caractéristique
de la plage `shoe-needs --role R --replace ID`. Si rien ne corrige le point avec certitude, le dire et
passer au chemin « recherche » avec la plage décalée par `change_wanted`.

**Antécédents pris en compte.** `shoe-needs` lit les antécédents de blessure du profil (puces
« Antécédents de blessure » / « Zones fragiles à surveiller ») et les douleurs déclarées, et indique
dans sa sortie quelles sources il a lues (`inputs.injury_history.sources`, avec le nombre d'entrées de chacune ; une note « aucun antécédent de blessure trouvé » quand il n'y en a pas). **Montrer à l'athlète
cette liste** avant les plages (« j'ai tenu compte de : … » ou « aucun antécédent trouvé : corrigez-moi
si j'en oublie »), pour qu'il complète ce que le profil ne dit pas ; ne jamais en supposer. Si `warnings`
signale que la paire remplacée a une fiche mais **aucun bilan de confort**, le dire et proposer de
renseigner le bilan avant de s'appuyer sur la continuité.

Toujours lancer `shoe-needs --role R --replace ID` : ses plages valident le candidat de continuité (une
caractéristique hors plage est signalée, pas cachée).

## 3. Sinon : plages cibles puis recherche en ligne

1. `python3 scripts/arc_index.py shoe-needs --role R [--replace ID] --text` : montrer à l'athlète les plages
   (drop, pile, souplesse, crampons, largeur, plaque, index minimaliste), la règle et le niveau de preuve de
   chacune. Si `insufficient_data` est vrai, le dire : plages larges, aucune continuité calculée.
2. **Trouver 3 à 5 modèles dont les caractéristiques tiennent dans les plages**, par recherche web à la
   demande (même méthode que `shoe-specs` : **laboratoire** RunRepeat / RTINGS d'abord → **page de la marque**
   → 1 à 2 revendeurs ; **jamais de scraping automatisé**, une page à la fois, valeurs factuelles et URL,
   jamais le texte d'un test). Sources qui se contredisent : montrer l'écart (marque 6 mm / labo 8,7 mm) et
   proposer la valeur retenue — **la mesure prime sur la marque** ; aberration (580 g face à 240-285 g)
   signalée, pas retenue.
3. Pour chaque modèle : la **version** (année de lancement, jamais devinée), les caractéristiques de la
   fiche (`drop_mm`, `stack_heel_mm`, `stack_forefoot_mm`, `weight_g`, `midsole_foam`, `midsole_softness`,
   `plate`, `lug_depth_mm`, `toe_box`) avec URL + date + type. Une caractéristique introuvable = « introuvable
   — absente ».
4. **Écarts aux plages signalés** : une valeur hors plage va dans `misses`, avec la règle et son niveau de
   preuve ; une valeur dans la plage va dans `fits`. Un candidat hors plage reste montré (c'est l'athlète
   qui décide) mais est dit hors plage ; ne jamais le présenter comme conforme.
5. Plaque / super-mousse : une **option de performance** (course, séances rapides), étiquetée comme telle ;
   aucune étude ne la relie aux blessures. Pas de prescription par type de pied ou pronation ; la stabilité
   n'est qu'une option si elle est confortable. Dynamiques de foulée : à **surveiller** après le
   changement, jamais un critère de choix.

## 4. Veto `medical`

Si `medical` figure dans `[agents].enabled` : **lui déléguer** le contrôle des candidats (antécédents
tendineux d'Achille / mollet, entorses de cheville, douleurs déclarées dans `medical/`), prompt de tâche en
anglais avec « Respond in <langue des documents> ». Un veto de `medical` est **respecté** : le candidat
est écarté (`vetoed: true`, gardé pour mémoire) et la raison est dite. Sans retour de `medical`, ne rien
affirmer sur sa décision.

Si `medical` n'est pas dans `[agents].enabled` : ne pas l'appeler ni le mentionner ; le coach applique lui-même
les règles de `shoe-needs` (ex. antécédent Achille/mollet → drop jamais abaissé, ≥ 2 épisodes de cheville →
pile plus basse et base large) et dit « **ce n'est pas un avis médical** » ; une douleur en cours ou
persistante renvoie à un professionnel de santé, sans diagnostic.

## 5. La restitution

Un **tableau comparatif**, un candidat par colonne (ou par ligne), à montrer avant toute écriture :

| Candidat (version) | Drop | Pile talon | Poids | Autres | Sources (type) | Règles satisfaites / non | Niveau de preuve |
|---|---|---|---|---|---|---|---|

- Chaque valeur : le chiffre, **la source (URL)** et le **type** `measured` / `manufacturer`, l'écart entre
  sources quand il y en a ; en chemin « continuité », une colonne « ancienne version » en regard.
- « Règles satisfaites / non » : l'identifiant de la règle de `shoe-needs`, et **son niveau de preuve**
  (recopié tel quel, `none` / approximation du projet dit comme tel). Le **confort passé** de l'athlète
  (bilan, retours) pèse plus que n'importe quelle colonne.
- Puis, en quelques lignes, toujours :
  1. **« Essayer en magasin : le confort décide. »** (confort perçu = le meilleur critère individuel connu ;
     aucune caractéristique ne le remplace) ;
  2. **Rodage 30 à 50 km** avant une course (« approximation du projet », pas un standard publié ; ne jamais en
     citer une source) — pour une paire de course, c'est un budget à prévoir avant le jour J ;
  3. **Rotation** : viser au moins 2 paires aux rôles distincts (`reminders` de `shoe-needs`, association
     observationnelle, pas causalité) ;
  4. Surveiller la foulée mesurée après le changement (`gait-summary`), sans en tirer de règle ;
  5. « **Ce n'est pas un avis médical** » et « une recommandation n'est pas une prévention de blessure ».
- Pas de prix, pas de bouton d'achat, pas de lien marchand mis en avant.

## 6. Persistance (seulement avec l'accord de l'athlète)

Demander : « je garde cette recommandation ? ». **Sans oui explicite, rien n'est écrit.** Avec l'accord,
charger `workspace-data-contract` puis écrire `gear/AAAA-MM-JJ_shoe_recommendation_<rôle>.md` (type
`shoe_recommendation`) :

- `date`, `role`, `path` (`continuity` | `search`), `replaced_gear_id` (obligatoire pour `continuity`),
  `athlete_validated: true` ;
- `targets` : copie des plages de `shoe-needs` (`ranges`), les identifiants de règle (`rule_ids`) et
  `insufficient_data` ;
- `candidates` : `brand`, `model`, `version`, `specs` (**même forme que `shoe_spec`** : `value`,
  `source_type`, `url`, `retrieved`, `alternatives`), `fits`, `misses`, `vetoed` le cas échéant ;
- `medical_veto` (`status`, `reviewer`, `reason`) quand le contrôle de §4 a eu lieu ;
- `notes` : version comparée, avertissements. Le texte libre dessous reprend le tableau montré.

Puis valider : `python3 scripts/arc_index.py --validate gear/AAAA-MM-JJ_shoe_recommendation_<rôle>.md`
et corriger avec l'athlète si une erreur remonte. Un fichier existant du même jour et du même rôle n'est pas
écrasé en silence : demander. Si l'athlète choisit une paire, **proposer** (sans l'imposer) d'enregistrer sa
fiche avec `shoe-specs` ; ne rien pousser vers Garmin, ne rien acheter.
