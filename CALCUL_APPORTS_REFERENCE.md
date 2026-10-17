# Documentation Detaillee du Calcul des Apports Nutritionnels de Reference (Cadence)

Ce document recense de maniere exhaustive toutes les formules mathematiques, coefficients physiologiques, tables de depense energetique (METs) et regles de lissage sur 7 jours glissants actuellement implementes dans `backend/nutrition_engine.py` (mis a jour selon les recommandations ANSES 2021, EFSA, ISSN 2017, ACSM 2016 et Compendium 2024).

---

## 1. Vue d'ensemble de l'architecture d'un objectif quotidien

Dans l'application, la cible quotidienne ajustee (`adjusted_targets`) pour chaque nutriment est la somme de **3 composantes** :

$$\text{Cible Ajustee} = \text{Base Physiologique} + \text{Bonus Sportif Moyen (7j passes)} + \text{Bonus d'Anticipation (J0 / J+1)}$$

---

## 2. Etape 1 : Besoins de Base Hors-Sport (`calculate_baseline_targets`)

### 2.1 Parametres d'entree du profil utilisateur
- `sex` : `"H"` (Homme) ou `"F"` (Femme)
- `age` : Age en annees (entier, defaut : `30`)
- `height_cm` : Taille en cm (flottant, defaut : `178.0`)
- `weight_kg` : Poids corporel total en kg (flottant, defaut : `74.0`)
- `activity_level` : Niveau d'activite quotidienne **hors seances de sport saisies** (`"sedentaire"`, `"modere"`, `"actif"`, `"tres_actif"`)
- `goal` : Objectif physiologique (`"maintien"`, `"performance"`, `"prise_masse"`, `"seche"`)
- `dietary_tags` : Tags de regime alimentaire (notamment `"vegetarien"`, `"vegan"`)

---

### 2.2 Metabolisme de Base (BMR / MB)
Le calcul utilise l'equation predictive de **Mifflin-St Jeor (1990)** :

- **Homme (`sex == "H"`)** :
  $$\text{BMR} = (10 \times \text{poids\_kg}) + (6.25 \times \text{taille\_cm}) - (5 \times \text{age}) + 5$$

- **Femme (`sex == "F"`)** :
  $$\text{BMR} = (10 \times \text{poids\_kg}) + (6.25 \times \text{taille\_cm}) - (5 \times \text{age}) - 161$$

---

### 2.3 Depense Energetique Quotidienne Hors-Sport (`tdee_base`)
Multiplicateurs alignes sur les standards **EFSA / ANSES** pour l'activite quotidienne hors seances de sport enregistrees :

$$\text{TDEE}_{\text{base}} = \text{BMR} \times \text{PAL}_{\text{hors-sport}}$$

| Niveau (`activity_level`) | Coefficient (`pal_map`) | Signification implicite |
| :--- | :---: | :--- |
| `sedentaire` | **1.40** | Travail de bureau, peu de deplacements a pied |
| `modere` | **1.55** | Quotidien dynamique, debout regulierement |
| `actif` | **1.70** | Journee tres active ou travail physique modere |
| `tres_actif` | **1.85** | Travail physique soutenu ou mouvement quasi continu |

---

### 2.4 Ajustement Calorique selon l'Objectif (`target_calories`)
$$\text{Cible Calories Base} = \text{arrondi\_dizaine}(\text{TDEE}_{\text{base}} \times \text{Facteur}_{\text{objectif}})$$

| Objectif (`goal`) | Multiplicateur (`goal_kcal_factor`) | Ecart energetique |
| :--- | :---: | :--- |
| `maintien` | **1.00** | Equilibre isocalorique ($0\%$) |
| `performance` | **1.04** | Leger surplus de securite energetique ($+4\%$) |
| `prise_masse` | **1.12** | Surplus anabolique modere ($+12\%$) |
| `seche` | **0.85** | Deficit calorique controle ($-15\%$) |

---

### 2.5 Repartition des Macronutriments de Base

#### A. Proteines (`target_proteins`) — $1\text{ g} = 4\text{ kcal}$
$$\text{Proteines (g)} = \text{round}(\text{poids\_kg} \times \text{Ratio}_{\text{prot}})$$

| Objectif (`goal`) | Ratio (`prot_per_kg`) | Reference |
| :--- | :---: | :--- |
| `maintien` | **1.6 g/kg** | ISSN (1.4 - 2.0 g/kg) |
| `performance` | **1.8 g/kg** | Soutien accru a la recuperation |
| `prise_masse` | **2.0 g/kg** | Maximisation de la synthese proteique musculaire |
| `seche` | **2.1 g/kg** | Preservation de la masse maigre en deficit calorique |

#### B. Lipides (`target_lipids`) — $1\text{ g} = 9\text{ kcal}$
$$\text{Lipides (g)} = \text{round}\Big(\max(\text{poids\_kg} \times 0.85,\; \text{poids\_kg} \times \text{Ratio}_{\text{lip}})\Big)$$

| Objectif (`goal`) | Ratio (`lipids_per_kg`) | Justification |
| :--- | :---: | :--- |
| `maintien` / `performance` | **1.15 g/kg** | Rapprochement de la cible ANSES (30-35% AET) |
| `prise_masse` | **1.20 g/kg** | Densite energetique et soutien hormonal |
| `seche` | **0.90 g/kg** | Plancher de securite hormonale ($\ge 0.85\text{ g/kg}$) |

#### C. Glucides (`target_carbs`) — $1\text{ g} = 4\text{ kcal}$
$$\text{Kcal Restantes} = \max\Big(600.0,\; \text{Cible Calories Base} - (\text{Proteines} \times 4 + \text{Lipides} \times 9)\Big)$$
$$\text{Glucides (g)} = \text{round}\left(\frac{\text{Kcal Restantes}}{4.0}\right)$$

---

### 2.6 Micronutriments et Hydratation de Base (ANSES 2021 / EFSA / NIH)

| Indicateur | Cle code | Formule actuelle | Reference |
| :--- | :--- | :--- | :--- |
| **Fibres** | `fiber` | **30.0 g/j** pour tous les adultes (H et F) | ANSES / EFSA |
| **Omega-3** | `omega3` | $\text{round}\left(\frac{\text{target\_calories} \times 0.01}{9.0} + 0.5,\; 1\right)$ | ANSES (1% AET en ALA + 500 mg EPA/DHA) |
| **Fer** | `iron` | `11.0 mg` (H) / `16.0 mg` (F), **$\times 1.8$** si `vegetarien` ou `vegan` (`19.8 mg` H / `28.8 mg` F) | ANSES + NIH (biodisponibilite fer non-heminique) |
| **Magnesium** | `magnesium` | $\text{round}(\text{poids\_kg} \times 5.8)$ | ANSES (fourchette 5.5 - 6.0 mg/kg) |
| **Calcium** | `calcium` | **1000.0 mg** si $\text{age} \le 24$, **950.0 mg** si $\text{age} \ge 25$ | ANSES 2021 |
| **Eau** | `water_ml` | Arrondi au multiple de 50 ml de $(\text{poids\_kg} \times 35.0)$ | EFSA / ANSES (35 ml/kg/j hors sport) |

---

## 3. Etape 2 : Depense et Surcharge Sportive (`calculate_workout_expenditure`)

### 3.1 Table des METs (Compendium 2024)

| Categorie (`category`) | Intensite `douce` | Intensite `moderee` | Intensite `intense` |
| :--- | :---: | :---: | :---: |
| `endurance` | **6.5** | **9.2** | **11.8** |
| `force` | **4.5** | **5.8** | **7.5** |
| `hiit_sport_co` | **6.0** | **8.8** | **11.2** |
| `velo_natation` | **5.8** | **8.2** | **10.8** |
| `mobilite_marche` | **2.8** | **3.8** | **4.8** |

$$\text{Kcal Nettes} = \text{round}\Big((\text{MET} - 1.2) \times \text{poids\_kg} \times \text{heures}\Big)$$

### 3.2 Repartition des Macronutriments de la Seance

| Categorie (`category`) | Part Glucides (`carb_share`) | Part Proteines (`prot_share`) | Part Lipides (`lip_share`) |
| :--- | :---: | :---: | :---: |
| `endurance` ou `velo_natation` *(moderee/intense)* | **72 %** | **12 %** | **16 %** |
| `endurance` ou `velo_natation` *(douce)* | **58 %** | **12 %** | **30 %** |
| `force` *(toutes intensites)* | **58 %** | **22 %** | **20 %** |
| `hiit_sport_co` *(toutes intensites)* | **68 %** | **18 %** | **14 %** |
| `mobilite_marche` *(toutes intensites)* | **50 %** | **15 %** | **35 %** |

### 3.3 Besoins Micronutritionnels et Hydriques Additionnels par Heure de Sport

| Nutriment | Formule par heure d'effort (`hours`) | Justification physiologique |
| :--- | :--- | :--- |
| **Fer (`iron`)** | - `endurance` / `velo_natation` : **+0.8 mg/h** (`intense`) ou **+0.5 mg/h** (`douce`/`moderee`)<br>- `hiit_sport_co` : **+0.7 mg/h**<br>- `force` : **+0.4 mg/h**<br>- `mobilite_marche` : **+0.15 mg/h** | Pertes sudorales et hemolyse mesurees (~50% plus conservateur que la v1). |
| **Magnesium (`magnesium`)** | **+18.0 mg/h** si `intense`, sinon **+12.0 mg/h** | Pertes sudorales reelles (10-20 mg/h). |
| **Calcium (`calcium`)** | **+25.0 mg/h** | Pertes sudorales calciques. |
| **Omega-3 (`omega3`)** | **+0.15 g/h** | Modulation inflammatoire post-exercice. |
| **Eau (`water_ml`)** | **420 ml/h** (`douce`), **650 ml/h** (`moderee`), **900 ml/h** (`intense`) | Compensation sudorale (calculee en arriere-plan, non affichee dans les 9 barres). |

---

## 4. Etape 3 : Plafond Physiologique des Proteines et Lissage sur 7 Jours (`compute_rolling_dashboard`)

### 4.1 Plafond de Securite des Proteines Totales (`2.3 g/kg`)
Sur les semaines a fort volume d'entrainement, l'addition `Base + Sport` pourrait faire grimper les proteines au-dela du seuil utile pour la synthese proteique.
- Si `adjusted_targets["proteins"] > 2.3 * weight_kg`, la cible de proteines est plafonnee a **`2.3 g/kg`** (conformement a la fourchette haute ISSN : `2.2 - 2.4 g/kg`).
- L'integralite des grammes de proteines excedentaires issus du sport est **convertie iso-caloriquement en glucides** ($1\text{ g de proteine} = 4\text{ kcal} = 1\text{ g de glucide}$), garantissant une recharge glycogenique optimale tout en respectant exactement le budget calorique cible.

### 4.2 Notes d'architecture conservees pour evolutions futures
- **Formule BMR Katch-McArdle / Cunningham** (`BMR = 370 + 21.6 * masse_maigre_kg`) : Pertinente pour les profils tres muscles connaissant leur taux de masse grasse exact (DEXA / plis cutanes). Conservee en reserve tant que le champ `% masse grasse` n'est pas requis dans l'interface.
- **Indicateurs affiches** : Maintien volontaire a **9 indicateurs** (`calories`, `proteins`, `carbs`, `lipids`, `fiber`, `omega3`, `iron`, `magnesium`, `calcium`) pour ne pas fausser les alertes de carences lorsque l'utilisateur ne saisit pas chaque verre d'eau bu.
