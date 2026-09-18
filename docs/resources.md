# 📚 Ressources

Le dossier `resources/` est votre **base de connaissances personnelle** que les agents consultent pour fournir des conseils fondés sur des preuves.

!!! warning "Important"
    Ce dossier est **exclu du dépôt** (voir `.gitignore`). Il est **strictement personnel** :
    - Ne versionnez jamais de données personnelles
    - Ne copiez pas de contenu protégé par le droit d'auteur (articles scrapés, livres, etc.)
    - Utilisez uniquement vos propres documents ou des contenus que vous avez le droit de partager

## 📁 Structure recommandée

```
resources/
├── nutrition/          # Nutrition sportive, hydratation, compléments
│   └── catalogue-produits-*.md   # Catalogues produits (format spécial, voir plus bas)
├── running/            # Technique de course, entraînement, blessures
├── recovery/           # Récupération, étirements, mobilité
├── health/             # Santé, sommeil, HRV, anti-inflammatoires
└── trainings/          # Plans d'entraînement (optionnel)
```

## ➕ Comment ajouter des ressources

### 1. Créez le dossier (si absent)

Le script d'installation crée automatiquement `resources/` avec un `README.md`. Si vous l'avez supprimé :

```bash
mkdir -p resources/{nutrition,running,recovery,health}
```

### 2. Ajoutez vos documents

Placez vos fichiers **Markdown** (`.md`) dans le sous-dossier correspondant :

```bash
# Exemple : un article sur l'hydratation
cp ~/Documents/hydratation-course.md resources/nutrition/hydratation-course-a-pied.md
```

**Conventions de nommage :**

- **Français** : `alimentation-avant-trail.md`, `etirements-course-a-pied.md`
- **Descriptif** : le nom doit refléter le contenu (les agents le recherchent par nom)
- **Un sujet par fichier** : plus facile à retrouver et à citer

### 3. Structurez vos documents

Les agents lisent les fichiers Markdown directement. Pour de meilleurs résultats :

```markdown
# Titre du document

Résumé en 1-2 phrases du sujet traité.

## Section 1
Contenu...

## Section 2
Contenu...
```

!!! tip "Conseil"
    Commencez chaque fichier par un **résumé court**. Les agents l'utilisent pour décider si le document est pertinent avant de le lire en entier.

## 🏷️ Catalogues produits (format spécial)

Les **catalogues produits** dans `resources/nutrition/catalogue-produits-*.md` ont un format spécial utilisé par les agents pour dimensionner les plans nutritionnels avec des **valeurs produit réelles**.

### Format attendu

```markdown
# Catalogue produits <Marque> — valeurs nutritionnelles

Catalogue de référence des produits nutrition **<Marque>**. Utilisé par les agents
pour dimensionner les plans nutritionnels avec les valeurs produit réelles
(glucides, sodium, électrolytes, BCAA, caféine) au lieu de valeurs génériques.

## Tableau récapitulatif (valeurs par unité)

| Produit | Format | Calories (kcal) | Glucides (g) | Sucres (g) | Protéines (g) | Lipides (g) | Sel (g) | Sodium (mg) | Électrolytes (mg) | Particularité |
|---|---|---|---|---|---|---|---|---|---|---|
| Gel poche 85 g | 85 g | 157 | 32 | 29 | 0.2 | 3.2 | 0.01 | 2 | 59 | IG bas, sans sucres ajoutés |
| Barre énergétique | 50 g | 201 | 24.7 | 21.1 | 5.4 | 8.1 | 0.84 | 333 | 600 | BCAA 175 mg |
| Pastille électrolytes | 5 g | 11 | 1.5 | 0.03 | 7.1 mg | 0 | 0.758 | 300 | 706 | Na 300, K 300, Mg 56 |

## <Produit> (détail)

- **Valeurs** : 157 kcal, glucides 32 g (sucres 29 g), sodium 2 mg, électrolytes 59 mg.
- **Ingrédients** : ...
- **Usage** : 1 gel/30-45 min pendant l'effort.
```

### Colonnes recommandées

| Colonne | Description |
|---|---|
| `Produit` | Nom exact du produit |
| `Format` | Poids/volume par unité |
| `Calories (kcal)` | Énergie par unité |
| `Glucides (g)` | Glucides par unité |
| `Sucres (g)` | Sucres simples |
| `Protéines (g)` | Protéines |
| `Lipides (g)` | Lipides |
| `Sel (g)` / `Sodium (mg)` | Sodium |
| `Électrolytes (mg)` | Électrolytes totaux |
| `Particularité` | BCAA, caféine, IG bas, etc. |

### Exemples fournis

- `catalogue-produits-baouw.md` — produits Baouw (gels, purées, barres, pastilles)
- `catalogue-produits-decathlon-aptonia.md` — produits Aptonia

## 🤖 Comment les agents utilisent les ressources

### Le mécanisme

1. **Rafraîchissement contextuel** : avant de répondre, chaque agent vérifie le contenu de `resources/`
2. **Recherche par nom** : les agents identifient les documents pertinents par leur nom de fichier
3. **Lecture ciblée** : ils lisent le document complet pour extraire les informations
4. **Citation** : ils basent leurs recommandations sur le contenu des documents

### Par agent

| Agent | Ressources utilisées | Usage |
|---|---|---|
| **Coach** | `resources/running/`, `resources/nutrition/`, `resources/recovery/`, `resources/health/` | Conseils d'entraînement fondés sur des preuves ; catalogues produits pour les discussions nutrition |
| **Stratège de course** | `resources/nutrition/` (incl. catalogues), `resources/running/`, `resources/recovery/` | Plan nutrition de course avec valeurs produit réelles ; recommandations matériel |
| **Médecin** | `resources/health/`, `resources/recovery/` | Protocoles de récupération, prévention des blessures |
| **Nutritionniste** | `resources/nutrition/` (incl. catalogues) | Plans nutritionnels, macros, ravitaillement avec valeurs produit réelles |

### Exemple concret : plan de ravitaillement

L'agent **nutritionniste** (ou **course-strategist**) qui prépare un plan de ravitaillement pour un trail de 50 km :

1. **Détecte** les catalogues : `catalogue-produits-baouw.md`, `catalogue-produits-decathlon-aptonia.md`
2. **Calcule** les besoins : ~60 g de glucides/heure, ~500 mg de sodium/heure
3. **Dimensionne** avec les valeurs réelles :
   - 1 gel poche 85 g Baouw = 32 g glucides → 2 gels/heure
   - 1 pastille électrolytes = 300 mg sodium → 1 pastille/30 min
4. **Produit** un plan précis : *« 2 gels poche Baouw par heure + 1 pastille électrolytes toutes les 30 min »*

Sans catalogue, l'agent utiliserait des **valeurs génériques** clairement étiquetées comme telles.

### Règle de cohérence

L'agent **nutritionniste** doit garder des valeurs **cohérentes** avec les journaux précédents dans `nutrition/` (même produit, même quantité). Si vous signalez un produit absent des catalogues, il vous demandera les valeurs de l'étiquette plutôt que d'inventer.

## ❓ FAQ

### Puis-je ajouter des fichiers PDF ?

Les agents lisent principalement du **Markdown**. Convertissez vos PDF en Markdown pour de meilleurs résultats.

### Puis-je ajouter des images ?

Oui, mais les agents ne peuvent pas les lire directement. Ajoutez une **description textuelle** à côté.

### Les ressources sont-elles partagées avec le dépôt public ?

**Non.** Le dossier `resources/` est exclu du dépôt via `.gitignore`. Il reste strictement local à votre machine.

### Que se passe-t-il si je n'ai pas de ressources ?

Les agents fonctionnent sans ressources, mais utilisent alors des **valeurs génériques** et des conseils moins précis. Ajouter vos documents améliore significativement la qualité des recommandations.
