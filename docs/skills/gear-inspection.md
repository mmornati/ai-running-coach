# Skill : `gear-inspection` — inspection photo des chaussures

> **Description** : Analyse photo de l'usure d'une paire — état 🟢🟡🟠🔴, comparaison avec l'inspection précédente, indices de foulée — toujours formulés comme des indices, jamais comme un diagnostic.

<!-- arc-video:materiel -->
<div class="arc-video-card" markdown>

[![Usure](../video/materiel/poster.jpg)](../video/materiel/index.html)

<div markdown>

<span class="arc-video__meta">En vidéo · Étape 09 · 1 min 47</span>

**[Usure](../video/materiel/index.html)** — Du kilométrage à l'inspection photo : alerte de seuil, verdict en quatre couleurs, indices de foulée (jamais un diagnostic), foulée mesurée, kits et bilan de carrière.

[Regarder](../video/materiel/index.html) · [English](../video/materiel/index.html?lang=en) · [Toutes les vidéos](../videos.md)

</div>

</div>
<!-- /arc-video -->


## Quand l'utiliser

- Le coach **propose** une inspection (jamais imposée) environ **tous les 200 km** d'une paire, à l'**alerte de seuil**, ou vous la demandez
- Vous envoyez des photos de vos chaussures ou décrivez leur usure
- Une paire passe en **retirée** : bilan de carrière

Le rappel se calcule : `python3 scripts/arc_index.py inspections` (voir plus bas), et le
[tableau de bord](../dashboard/views.md) affiche « Inspection conseillée ». Rien n'est proposé
pendant la synchronisation automatique (`garmin-daily-sync`) : c'est une conversation.

!!! tip "Lancer une inspection"
    La commande courte `/inspection [paire]` désigne la paire et indique comment envoyer les
    photos : voir [Faire inspecter une paire](inspection.md).

## Protocole photo

1. Les **deux semelles à plat** (dessous)
2. Une **vue latérale à hauteur de semelle**, par chaussure — plis de la mousse
3. Une **vue arrière sur surface plane** — inclinaison du talon, contrefort
4. La **tige** (dessus)
5. Une **pièce ou une règle dans le cadre** — sans elle, aucune mesure en millimètres

Photo floue ou angle manquant → le coach **redemande l'angle** plutôt que de conclure.

## Ce que le coach produit

- Un **verdict** 🟢 `green` / 🟡 `yellow` / 🟠 `orange` / 🔴 `red`, **justifié visuellement** (gomme et crampons, mousse, contrefort, tige) et écrit en toutes lettres
- Une **comparaison explicite avec l'inspection précédente de la même paire** — le signal le plus fiable — dès la deuxième inspection
- Des **indices de foulée** depuis la zone d'usure, à prendre comme tels :

| Zone d'usure | Indice |
|---|---|
| Talon postéro-latéral | attaque talon (fréquent, normal) |
| Milieu du pied latéral | attaque médio/avant-pied |
| Talon médial | indice de pronation |
| Avant-pied latéral fort | supination à la propulsion |

Correspondances issues des sources citées plus bas, qui ne concordent pas toutes (l'usure
latérale du milieu du pied est lue comme une foulée neutre par l'une d'elles) : un indice,
jamais un diagnostic.

- Une **asymétrie gauche/droite** mise en avant (le côté le plus usé), rapprochée de votre
  historique de blessures et de douleurs (`medical/`)
- Un **relais** vers l'agent `medical` en cas d'asymétrie marquée ou de lien plausible avec une
  douleur — **uniquement s'il est activé** (`[agents].enabled`) ; sinon il suggère un kiné ou
  une analyse de foulée en laboratoire

Dans le tableau de bord, chaque inspection rejoint l'historique de sa paire (vue
[Matériel](../dashboard/views.md#materiel)) :

![Inspections photo dans le tableau de bord](../assets/dashboard/inspections.webp)

Chaque inspection s'affiche en lignes distinctes : état et kilométrage, badge d'asymétrie (neutre
si « aucune »), badge d'indice de foulée, puis les zones d'usure en petit tableau
gauche/droite. Les indices de toutes les inspections sont consolidés — et confrontés à la
dynamique de course mesurée par la montre — dans la carte [Foulée](../dashboard/views.md#foulee) de la vue Santé.

## Garde-fous

- **L'usure est un signal faible** : les chaussures modernes (pile haute, rocker, mousses) la déforment. Un indice n'est **jamais un diagnostic**.
- **Aucune mesure en mm sans référence d'échelle** dans la photo (le contrat refuse `lug_depth_mm` sans `scale_reference: true`).
- **Jamais de changement de technique de foulée recommandé sur une photo seule.**
- **Dynamique de course mesurée (temps de contact, balance, oscillation…)** : extraite du FIT depuis #151 et consolidée dans la carte [Foulée](../dashboard/views.md#foulee) du tableau de bord (`python3 scripts/arc_index.py gait-summary`). Le sens gauche/droite de la balance n'est pas établi : on parle d'écart à 50 %, jamais d'un pied. Les règles d'usage par le coach viennent avec une story ultérieure ; sans mesure (source intervals.icu, capteur sans balance), le coach le dit, ne l'invente pas.
- Les photos restent dans votre workspace (`gear/photos/`, gitignoré), jamais dans le dépôt public. Ce dossier sert aussi de **boîte de dépôt** : copiez-y vos photos sous n'importe quel nom, le coach rattache à une paire celles qu'aucune inspection ne cite et les renomme `AAAA-MM-JJ_<gear_id>_<vue>.<ext>` — sans jamais en supprimer.
- Envoyer des photos depuis le téléphone (Remote Control) n'est **pas validé** : voir [Le coach dans la poche](../mobile.md).

## Persistance

`gear/AAAA-MM-JJ_<gear_id>_inspection.md` avec un bloc `arc` `gear_inspection` (`condition`,
`distance_m` au moment de l'inspection, `wear_zones`, `asymmetry`, `gait_hints`, `photos`,
`previous`…) — voir [Contrat de données](workspace-data-contract.md) — puis le texte du coach
(justification, comparaison, indices). Validation :
`python3 scripts/arc_index.py --validate gear/AAAA-MM-JJ_<gear_id>_inspection.md`.

## Commandes

```bash
python3 scripts/arc_index.py inspections [--gear ID]   # historique, rappel « due », comparaison
python3 scripts/arc_index.py inspections --unreferenced-photos   # + images de gear/photos/ citées par aucune inspection
python3 scripts/arc_index.py gear-career --gear ID     # bilan de carrière (paire retirée)
```

`inspections` rend, par paire : `due` (`true`, `false`, ou `null` si la dernière inspection n'a
pas de kilométrage), `due_reason`, `km_since_inspection_m`, `condition_change` et l'historique.
`gear-career` rend km, séances, période, courses (intensité planifiée `race`), meilleurs efforts
(seulement si des splits existent), plus longue sortie et dernière inspection.

## Sources

- [Doctors of Running — Outsole Wear Patterns](https://www.doctorsofrunning.com/footwear-science-outsole-wear-patterns/)
- [Marathon Handbook — wear on running shoes](https://marathonhandbook.com/wear-on-running-shoes/)
- La cadence de 200 km, les seuils de couleur et la table d'indices simplifiée sont une **approximation du projet**, pas une norme.

## Fichier source

`skills/gear-inspection/SKILL.md`
