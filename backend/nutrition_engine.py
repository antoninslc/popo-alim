from datetime import date, datetime, timedelta
import math
import re
from typing import Any, Dict, List, Optional, Tuple

NUTRIENT_KEYS = [
    "calories",
    "proteins",
    "carbs",
    "lipids",
    "fiber",
    "omega3",
    "iron",
    "magnesium",
    "calcium",
]

NUTRIENT_METADATA: Dict[str, Dict[str, Any]] = {
    "calories": {
        "label": "Énergie",
        "unit": "kcal",
        "group": "macro",
        "eq_min": 0.92,
        "eq_max": 1.08,
        "decimals": 0,
    },
    "proteins": {
        "label": "Protéines",
        "unit": "g",
        "group": "macro",
        "eq_min": 0.90,
        "eq_max": 1.18,
        "decimals": 0,
    },
    "carbs": {
        "label": "Glucides",
        "unit": "g",
        "group": "macro",
        "eq_min": 0.88,
        "eq_max": 1.12,
        "decimals": 0,
    },
    "lipids": {
        "label": "Lipides",
        "unit": "g",
        "group": "macro",
        "eq_min": 0.88,
        "eq_max": 1.12,
        "decimals": 0,
    },
    "fiber": {
        "label": "Fibres",
        "unit": "g",
        "group": "micro",
        "eq_min": 0.90,
        "eq_max": 1.35,
        "decimals": 1,
    },
    "omega3": {
        "label": "Oméga-3",
        "unit": "g",
        "group": "micro",
        "eq_min": 0.90,
        "eq_max": 1.50,
        "decimals": 2,
    },
    "iron": {
        "label": "Fer",
        "unit": "mg",
        "group": "micro",
        "eq_min": 0.90,
        "eq_max": 1.40,
        "decimals": 1,
    },
    "magnesium": {
        "label": "Magnésium",
        "unit": "mg",
        "group": "micro",
        "eq_min": 0.90,
        "eq_max": 1.35,
        "decimals": 0,
    },
    "calcium": {
        "label": "Calcium",
        "unit": "mg",
        "group": "micro",
        "eq_min": 0.90,
        "eq_max": 1.35,
        "decimals": 0,
    },
}

PORTION_MULTIPLIERS = {
    "leger": 0.75,
    "normal": 1.00,
    "copieux": 1.30,
}

MEAL_SLOT_WEIGHTS = {
    "petit_dejeuner": 0.22,
    "dejeuner": 0.38,
    "collation": 0.10,
    "diner": 0.35,
}

# Catalogue de peripheriques rapides (1 clic) avec profil nutritionnel precis
PERIPHERALS_CATALOG: List[Dict[str, Any]] = [
    {
        "id": "pain_levain",
        "label": "Pain au levain / complet",
        "portion_label": "2 tranches (60g)",
        "category": "accompagnement",
        "nutrients": {
            "calories": 155, "proteins": 5.4, "carbs": 30.0, "lipids": 1.1,
            "fiber": 3.8, "omega3": 0.05, "iron": 1.4, "magnesium": 38, "calcium": 22, "water_ml": 20
        },
    },
    {
        "id": "pain_blanc",
        "label": "Baguette tradition",
        "portion_label": "1/4 baguette (60g)",
        "category": "accompagnement",
        "nutrients": {
            "calories": 165, "proteins": 5.2, "carbs": 34.0, "lipids": 0.8,
            "fiber": 1.8, "omega3": 0.02, "iron": 0.9, "magnesium": 16, "calcium": 18, "water_ml": 18
        },
    },
    {
        "id": "comte_fromage",
        "label": "Fromage affiné (Comté / Tomme)",
        "portion_label": "Portion standard (35g)",
        "category": "fromage_laitage",
        "nutrients": {
            "calories": 145, "proteins": 9.8, "carbs": 0.2, "lipids": 11.8,
            "fiber": 0.0, "omega3": 0.12, "iron": 0.2, "magnesium": 12, "calcium": 330, "water_ml": 12
        },
    },
    {
        "id": "fromage_blanc",
        "label": "Fromage blanc / Skyr",
        "portion_label": "1 bol (150g)",
        "category": "fromage_laitage",
        "nutrients": {
            "calories": 110, "proteins": 13.5, "carbs": 6.0, "lipids": 3.0,
            "fiber": 0.0, "omega3": 0.04, "iron": 0.1, "magnesium": 18, "calcium": 195, "water_ml": 120
        },
    },
    {
        "id": "yaourt_nature",
        "label": "Yaourt nature",
        "portion_label": "1 pot (125g)",
        "category": "fromage_laitage",
        "nutrients": {
            "calories": 72, "proteins": 5.0, "carbs": 6.2, "lipids": 2.8,
            "fiber": 0.0, "omega3": 0.03, "iron": 0.1, "magnesium": 15, "calcium": 170, "water_ml": 105
        },
    },
    {
        "id": "fruit_saison",
        "label": "Fruit frais (Pomme / Poire / Orange)",
        "portion_label": "1 fruit moyen (160g)",
        "category": "fruit_dessert",
        "nutrients": {
            "calories": 82, "proteins": 0.6, "carbs": 19.0, "lipids": 0.3,
            "fiber": 3.6, "omega3": 0.02, "iron": 0.3, "magnesium": 14, "calcium": 24, "water_ml": 135
        },
    },
    {
        "id": "banane",
        "label": "Banane",
        "portion_label": "1 banane (120g)",
        "category": "fruit_dessert",
        "nutrients": {
            "calories": 108, "proteins": 1.4, "carbs": 25.0, "lipids": 0.4,
            "fiber": 3.1, "omega3": 0.03, "iron": 0.4, "magnesium": 34, "calcium": 8, "water_ml": 90
        },
    },
    {
        "id": "poignee_oleagineux",
        "label": "Poignée d'amandes et noix",
        "portion_label": "1 poignée (30g)",
        "category": "collation_sante",
        "nutrients": {
            "calories": 185, "proteins": 5.6, "carbs": 3.2, "lipids": 16.8,
            "fiber": 3.2, "omega3": 1.15, "iron": 1.1, "magnesium": 76, "calcium": 65, "water_ml": 2
        },
    },
    {
        "id": "chocolat_noir",
        "label": "Chocolat noir 85%",
        "portion_label": "2 grands carrés (20g)",
        "category": "fruit_dessert",
        "nutrients": {
            "calories": 118, "proteins": 2.4, "carbs": 4.2, "lipids": 9.8,
            "fiber": 2.8, "omega3": 0.02, "iron": 2.4, "magnesium": 46, "calcium": 16, "water_ml": 1
        },
    },
    {
        "id": "crudites_olive",
        "label": "Salade / Crudités huile colza-olive",
        "portion_label": "1 assiette annexe",
        "category": "accompagnement",
        "nutrients": {
            "calories": 115, "proteins": 1.5, "carbs": 4.5, "lipids": 10.0,
            "fiber": 2.5, "omega3": 0.65, "iron": 0.9, "magnesium": 22, "calcium": 35, "water_ml": 140
        },
    },
    {
        "id": "dessert_sucre",
        "label": "Dessert pâtissier / Biscuit",
        "portion_label": "1 part individuelle",
        "category": "fruit_dessert",
        "nutrients": {
            "calories": 260, "proteins": 3.8, "carbs": 34.0, "lipids": 12.0,
            "fiber": 1.0, "omega3": 0.05, "iron": 0.8, "magnesium": 15, "calcium": 35, "water_ml": 25
        },
    },
    {
        "id": "grand_verre_eau",
        "label": "Eau / Tisane (350 ml)",
        "portion_label": "1 grand verre (350ml)",
        "category": "boisson",
        "nutrients": {
            "calories": 0, "proteins": 0.0, "carbs": 0.0, "lipids": 0.0,
            "fiber": 0.0, "omega3": 0.0, "iron": 0.0, "magnesium": 18, "calcium": 45, "water_ml": 350
        },
    },
    {
        "id": "gourde_eau",
        "label": "Gourde d'eau (600 ml)",
        "portion_label": "1 gourde (600ml)",
        "category": "boisson",
        "nutrients": {
            "calories": 0, "proteins": 0.0, "carbs": 0.0, "lipids": 0.0,
            "fiber": 0.0, "omega3": 0.0, "iron": 0.0, "magnesium": 30, "calcium": 75, "water_ml": 600
        },
    },
    {
        "id": "cafe_the",
        "label": "Café ou Thé sans sucre",
        "portion_label": "1 tasse (180ml)",
        "category": "boisson",
        "nutrients": {
            "calories": 4, "proteins": 0.2, "carbs": 0.5, "lipids": 0.0,
            "fiber": 0.0, "omega3": 0.0, "iron": 0.1, "magnesium": 8, "calcium": 5, "water_ml": 180
        },
    },
    {
        "id": "verre_vin_biere",
        "label": "Verre de vin ou Demi de bière",
        "portion_label": "1 verre standard",
        "category": "boisson",
        "nutrients": {
            "calories": 125, "proteins": 0.5, "carbs": 6.5, "lipids": 0.0,
            "fiber": 0.0, "omega3": 0.0, "iron": 0.4, "magnesium": 14, "calcium": 10, "water_ml": 150
        },
    },
]

PERIPHERALS_BY_ID = {item["id"]: item for item in PERIPHERALS_CATALOG}


def empty_nutrients() -> Dict[str, float]:
    return {k: 0.0 for k in NUTRIENT_KEYS}


def scale_nutrients(nutrients: Dict[str, float], factor: float) -> Dict[str, float]:
    return {k: round(float(nutrients.get(k, 0.0)) * factor, 2) for k in NUTRIENT_KEYS}


def sum_nutrients(items: List[Dict[str, float]]) -> Dict[str, float]:
    total = empty_nutrients()
    for item in items:
        for k in NUTRIENT_KEYS:
            total[k] += float(item.get(k, 0.0))
    return {k: round(total[k], 2) for k in NUTRIENT_KEYS}


def calculate_baseline_targets(profile: Dict[str, Any]) -> Dict[str, float]:
    """Calcule les besoins quotidiens de base (hors seances de sport ponctuelles)."""
    if profile.get("custom_targets_enabled") and profile.get("custom_targets"):
        custom = profile["custom_targets"]
        return {k: float(custom.get(k, 0.0)) for k in NUTRIENT_KEYS}

    sex = profile.get("sex", "H")
    age = int(profile.get("age", 30))
    height_cm = float(profile.get("height_cm", 178.0))
    weight_kg = float(profile.get("weight_kg", 74.0))
    activity_level = profile.get("activity_level", "modere")
    goal = profile.get("goal", "performance")

    # Formule de Mifflin-St Jeor (MB)
    if sex == "F":
        bmr = 10.0 * weight_kg + 6.25 * height_cm - 5.0 * age - 161.0
    else:
        bmr = 10.0 * weight_kg + 6.25 * height_cm - 5.0 * age + 5.0

    # Multiplicateur d'activite quotidienne hors séances de sport saisies
    pal_map = {
        "sedentaire": 1.30,
        "modere": 1.42,
        "actif": 1.55,
        "tres_actif": 1.68,
    }
    tdee_base = bmr * pal_map.get(activity_level, 1.42)

    # Ajustement selon l'objectif
    goal_kcal_factor = {
        "maintien": 1.00,
        "performance": 1.04,
        "prise_masse": 1.12,
        "seche": 0.86,
    }.get(goal, 1.00)

    target_calories = round(tdee_base * goal_kcal_factor / 10.0) * 10.0

    # Repartition physiologique en g/kg
    prot_per_kg = {
        "maintien": 1.6,
        "performance": 1.8,
        "prise_masse": 2.0,
        "seche": 2.1,
    }.get(goal, 1.8)

    lipids_per_kg = {
        "maintien": 1.05,
        "performance": 1.05,
        "prise_masse": 1.15,
        "seche": 0.90,
    }.get(goal, 1.05)

    target_proteins = round(weight_kg * prot_per_kg)
    target_lipids = round(weight_kg * lipids_per_kg)
    remaining_kcal = max(600.0, target_calories - (target_proteins * 4.0 + target_lipids * 9.0))
    target_carbs = round(remaining_kcal / 4.0)

    # Micronutriments de reference (adaptes au profil sportif)
    target_fiber = 30.0 if sex == "H" else 26.0
    target_omega3 = round(max(1.8, target_calories / 1150.0), 1)
    target_iron = 11.0 if sex == "H" else 16.0
    target_magnesium = round(weight_kg * 5.2)
    target_calcium = 950.0
    target_water_ml = round((weight_kg * 32.0) / 50.0) * 50.0

    return {
        "calories": float(target_calories),
        "proteins": float(target_proteins),
        "carbs": float(target_carbs),
        "lipids": float(target_lipids),
        "fiber": float(target_fiber),
        "omega3": float(target_omega3),
        "iron": float(target_iron),
        "magnesium": float(target_magnesium),
        "calcium": float(target_calcium),
        "water_ml": float(target_water_ml),
    }


def calculate_workout_expenditure(
    category: str,
    duration_min: int,
    intensity: str,
    weight_kg: float = 74.0,
) -> Dict[str, float]:
    """Calcule le besoin nutritionnel additionnel engendre par une seance de sport."""
    hours = max(0.1, float(duration_min) / 60.0)

    # METs approximatifs par categorie et intensite
    met_table = {
        "endurance": {"douce": 6.5, "moderee": 9.2, "intense": 11.8},
        "force": {"douce": 4.0, "moderee": 5.8, "intense": 7.5},
        "hiit_sport_co": {"douce": 6.0, "moderee": 8.8, "intense": 11.2},
        "velo_natation": {"douce": 5.8, "moderee": 8.2, "intense": 10.8},
        "mobilite_marche": {"douce": 2.8, "moderee": 3.8, "intense": 4.8},
    }
    cat_mets = met_table.get(category, met_table["endurance"])
    met = cat_mets.get(intensity, 7.0)

    # Dépense nette au-dessus du repos (MET - 1.2)
    net_kcal = round((met - 1.2) * weight_kg * hours)

    # Repartition des substrats selon le type d'effort
    if category in ("endurance", "velo_natation"):
        carb_share = 0.72 if intensity != "douce" else 0.58
        prot_share = 0.12
        lip_share = 1.0 - carb_share - prot_share
        extra_iron = 1.6 * hours if intensity == "intense" else 1.0 * hours
    elif category == "force":
        carb_share = 0.52
        prot_share = 0.28
        lip_share = 0.20
        extra_iron = 0.8 * hours
    elif category == "hiit_sport_co":
        carb_share = 0.68
        prot_share = 0.18
        lip_share = 0.14
        extra_iron = 1.4 * hours
    else:
        carb_share = 0.50
        prot_share = 0.15
        lip_share = 0.35
        extra_iron = 0.3 * hours

    extra_carbs = round((net_kcal * carb_share) / 4.0, 1)
    extra_proteins = round((net_kcal * prot_share) / 4.0, 1)
    extra_lipids = round((net_kcal * lip_share) / 9.0, 1)

    sweat_rate_ml_h = {"douce": 420.0, "moderee": 650.0, "intense": 900.0}.get(intensity, 600.0)
    extra_water = round((sweat_rate_ml_h * hours) / 25.0) * 25.0
    extra_magnesium = round(hours * (35.0 if intensity == "intense" else 22.0), 1)

    return {
        "calories": float(net_kcal),
        "proteins": float(extra_proteins),
        "carbs": float(extra_carbs),
        "lipids": float(extra_lipids),
        "fiber": 0.0,
        "omega3": round(0.15 * hours, 2),
        "iron": round(extra_iron, 2),
        "magnesium": float(extra_magnesium),
        "calcium": round(25.0 * hours, 1),
        "water_ml": float(extra_water),
    }


# Base de connaissances culinaires locale pour l'approche hybride deterministe / hors-ligne
CULINARY_COMPONENTS_DB: List[Dict[str, Any]] = [
    # Plats complets courants
    {
        "keywords": ["poulet curry", "curry de poulet", "tikka masala"],
        "name": "Filet de poulet au curry, lait de coco et riz basmati (portion standard 380g)",
        "role": "plat_complet",
        "nutrients": {
            "calories": 610, "proteins": 38.0, "carbs": 66.0, "lipids": 20.0,
            "fiber": 4.2, "omega3": 0.25, "iron": 2.6, "magnesium": 68, "calcium": 55, "water_ml": 220
        },
    },
    {
        "keywords": ["saumon lentille", "pave de saumon lentille", "saumon riz"],
        "name": "Pavé de saumon grillé et accompagnement féculents/légumineuses (360g)",
        "role": "plat_complet",
        "nutrients": {
            "calories": 640, "proteins": 41.0, "carbs": 52.0, "lipids": 28.0,
            "fiber": 7.5, "omega3": 2.45, "iron": 4.2, "magnesium": 92, "calcium": 65, "water_ml": 230
        },
    },
    {
        "keywords": ["lasagne", "bolognaise", "pates bolo", "spaghetti bolognaise"],
        "name": "Lasagnes ou pâtes à la bolognaise maison (380g)",
        "role": "plat_complet",
        "nutrients": {
            "calories": 660, "proteins": 34.0, "carbs": 68.0, "lipids": 26.0,
            "fiber": 4.8, "omega3": 0.22, "iron": 3.8, "magnesium": 62, "calcium": 240, "water_ml": 240
        },
    },
    {
        "keywords": ["carbonara", "pates carbo"],
        "name": "Assiette de pâtes à la carbonara (350g)",
        "role": "plat_complet",
        "nutrients": {
            "calories": 720, "proteins": 29.0, "carbs": 74.0, "lipids": 33.0,
            "fiber": 3.2, "omega3": 0.18, "iron": 2.4, "magnesium": 52, "calcium": 210, "water_ml": 180
        },
    },
    {
        "keywords": ["ramen", "soupe pho", "bo bun", "nouilles saut"],
        "name": "Grand bol de ramen / nouilles asiatiques garnies (bouillon, protéine, œuf, légumes)",
        "role": "plat_complet",
        "nutrients": {
            "calories": 590, "proteins": 32.0, "carbs": 68.0, "lipids": 19.0,
            "fiber": 4.5, "omega3": 0.30, "iron": 3.4, "magnesium": 64, "calcium": 75, "water_ml": 420
        },
    },
    {
        "keywords": ["poke bowl", "chirashi", "sushi", "maki"],
        "name": "Poke bowl / Assortiment japonais riz vinaigré, poisson cru et avocat",
        "role": "plat_complet",
        "nutrients": {
            "calories": 620, "proteins": 33.0, "carbs": 72.0, "lipids": 21.0,
            "fiber": 6.2, "omega3": 1.85, "iron": 2.8, "magnesium": 84, "calcium": 58, "water_ml": 240
        },
    },
    {
        "keywords": ["salade cesar", "salade composee", "salade poulet"],
        "name": "Grande salade composée avec volaille, croûtons, parmesan et sauce",
        "role": "plat_complet",
        "nutrients": {
            "calories": 510, "proteins": 34.0, "carbs": 26.0, "lipids": 29.0,
            "fiber": 5.2, "omega3": 0.45, "iron": 2.5, "magnesium": 56, "calcium": 260, "water_ml": 280
        },
    },
    {
        "keywords": ["couscous", "tajine"],
        "name": "Couscous / Tajine semoule, pois chiches, légumes et viande",
        "role": "plat_complet",
        "nutrients": {
            "calories": 680, "proteins": 36.0, "carbs": 82.0, "lipids": 21.0,
            "fiber": 8.4, "omega3": 0.25, "iron": 4.1, "magnesium": 88, "calcium": 85, "water_ml": 290
        },
    },
    {
        "keywords": ["chili con carne", "chili sin carne", "haricots rouges"],
        "name": "Chili (haricots rouges, bœuf ou soja, maïs, tomates et riz)",
        "role": "plat_complet",
        "nutrients": {
            "calories": 630, "proteins": 37.0, "carbs": 74.0, "lipids": 18.0,
            "fiber": 11.5, "omega3": 0.28, "iron": 5.2, "magnesium": 105, "calcium": 90, "water_ml": 270
        },
    },
    {
        "keywords": ["dahl", "dal de lentilles", "curry de pois chiches"],
        "name": "Dahl de lentilles corail au lait de coco, épinards et riz basmati",
        "role": "plat_complet",
        "nutrients": {
            "calories": 570, "proteins": 24.0, "carbs": 78.0, "lipids": 16.0,
            "fiber": 10.8, "omega3": 0.32, "iron": 5.4, "magnesium": 98, "calcium": 110, "water_ml": 260
        },
    },
    {
        "keywords": ["burger", "hamburger", "cheeseburger"],
        "name": "Burger complet avec accompagnement (frites ou pommes de terre)",
        "role": "plat_complet",
        "nutrients": {
            "calories": 820, "proteins": 38.0, "carbs": 76.0, "lipids": 39.0,
            "fiber": 5.4, "omega3": 0.22, "iron": 4.2, "magnesium": 68, "calcium": 220, "water_ml": 170
        },
    },
    {
        "keywords": ["pizza"],
        "name": "Pizza artisanale individuelle (pâte fine, tomate, mozzarella, garniture)",
        "role": "plat_complet",
        "nutrients": {
            "calories": 760, "proteins": 32.0, "carbs": 88.0, "lipids": 29.0,
            "fiber": 4.6, "omega3": 0.20, "iron": 3.1, "magnesium": 58, "calcium": 380, "water_ml": 160
        },
    },
    {
        "keywords": ["quiche", "tarte salee"],
        "name": "Part de quiche / tarte salée et salade verte",
        "role": "plat_complet",
        "nutrients": {
            "calories": 540, "proteins": 21.0, "carbs": 38.0, "lipids": 33.0,
            "fiber": 3.4, "omega3": 0.35, "iron": 2.2, "magnesium": 42, "calcium": 260, "water_ml": 190
        },
    },
    {
        "keywords": ["sandwich", "bagel", "panini", "wrap"],
        "name": "Sandwich / Wrap garni (pain, protéine, crudités)",
        "role": "plat_complet",
        "nutrients": {
            "calories": 490, "proteins": 26.0, "carbs": 54.0, "lipids": 18.0,
            "fiber": 4.2, "omega3": 0.25, "iron": 2.4, "magnesium": 52, "calcium": 160, "water_ml": 140
        },
    },
    {
        "keywords": ["flocons d'avoine", "porridge", "muesli", "granola", "bowl avoine"],
        "name": "Bol de flocons d'avoine / Muesli avec lait ou yaourt et fruits",
        "role": "plat_complet",
        "nutrients": {
            "calories": 460, "proteins": 18.0, "carbs": 64.0, "lipids": 13.0,
            "fiber": 7.8, "omega3": 0.45, "iron": 3.2, "magnesium": 115, "calcium": 240, "water_ml": 210
        },
    },
    {
        "keywords": ["tartines", "pain beurre", "petit dejeuner classique", "brioche"],
        "name": "Tartines de pain avec beurre/confiture ou purée d'oléagineux",
        "role": "plat_complet",
        "nutrients": {
            "calories": 380, "proteins": 9.0, "carbs": 56.0, "lipids": 13.0,
            "fiber": 4.2, "omega3": 0.15, "iron": 1.8, "magnesium": 48, "calcium": 65, "water_ml": 60
        },
    },
    # Briques modulaires (Proteines, Feculents, Legumes) pour recomposition intelligente
    {
        "keywords": ["poulet", "dinde", "volaille", "escalope"],
        "name": "Filet de volaille grillé (150g)",
        "role": "proteine",
        "nutrients": {
            "calories": 245, "proteins": 36.0, "carbs": 0.0, "lipids": 10.5,
            "fiber": 0.0, "omega3": 0.12, "iron": 1.4, "magnesium": 42, "calcium": 18, "water_ml": 95
        },
    },
    {
        "keywords": ["boeuf", "steak", "bavette", "entrecote", "viande rouge", "tartare"],
        "name": "Pièce de bœuf / Steak (150g)",
        "role": "proteine",
        "nutrients": {
            "calories": 295, "proteins": 37.0, "carbs": 0.0, "lipids": 16.0,
            "fiber": 0.0, "omega3": 0.18, "iron": 4.1, "magnesium": 38, "calcium": 15, "water_ml": 90
        },
    },
    {
        "keywords": ["saumon", "maquereau", "sardine", "truite", "hareng", "poisson gras"],
        "name": "Poisson gras (Saumon / Maquereau / Sardines - 140g)",
        "role": "proteine",
        "nutrients": {
            "calories": 310, "proteins": 31.0, "carbs": 0.0, "lipids": 20.0,
            "fiber": 0.0, "omega3": 2.35, "iron": 1.8, "magnesium": 46, "calcium": 85, "water_ml": 88
        },
    },
    {
        "keywords": ["cabillaud", "colin", "merlu", "daurade", "thon", "poisson blanc", "crevette"],
        "name": "Poisson blanc / Thon / Crevettes (150g)",
        "role": "proteine",
        "nutrients": {
            "calories": 185, "proteins": 34.0, "carbs": 0.0, "lipids": 4.8,
            "fiber": 0.0, "omega3": 0.55, "iron": 1.5, "magnesium": 48, "calcium": 35, "water_ml": 110
        },
    },
    {
        "keywords": ["oeuf", "oeufs", "omelette", "oeufs brouilles", "oeuf au plat"],
        "name": "Œufs / Omelette (2 à 3 œufs)",
        "role": "proteine",
        "nutrients": {
            "calories": 230, "proteins": 18.5, "carbs": 1.2, "lipids": 16.5,
            "fiber": 0.0, "omega3": 0.25, "iron": 2.7, "magnesium": 20, "calcium": 80, "water_ml": 110
        },
    },
    {
        "keywords": ["tofu", "tempeh", "seitan", "galette vegetale"],
        "name": "Tofu / Tempeh sauté aux épices (150g)",
        "role": "proteine",
        "nutrients": {
            "calories": 225, "proteins": 22.0, "carbs": 5.0, "lipids": 13.0,
            "fiber": 3.2, "omega3": 0.40, "iron": 3.6, "magnesium": 82, "calcium": 290, "water_ml": 95
        },
    },
    {
        "keywords": ["jambon", "blanc de dinde", "blanc de poulet"],
        "name": "Jambon blanc / Volaille en tranches (2 tranches - 90g)",
        "role": "proteine",
        "nutrients": {
            "calories": 115, "proteins": 19.5, "carbs": 1.0, "lipids": 3.5,
            "fiber": 0.0, "omega3": 0.05, "iron": 1.1, "magnesium": 24, "calcium": 12, "water_ml": 62
        },
    },
    {
        "keywords": ["riz", "basmati", "risotto"],
        "name": "Riz cuit (portion standard 180g cuit)",
        "role": "feculent",
        "nutrients": {
            "calories": 240, "proteins": 5.2, "carbs": 51.0, "lipids": 1.6,
            "fiber": 1.8, "omega3": 0.04, "iron": 0.8, "magnesium": 32, "calcium": 18, "water_ml": 115
        },
    },
    {
        "keywords": ["pates", "spaghetti", "penne", "tagliatelle", "coquillette", "gnocchi", "semoule", "quinoa", "boulgour", "ebli"],
        "name": "Pâtes / Quinoa / Semoule cuits (portion 190g cuit)",
        "role": "feculent",
        "nutrients": {
            "calories": 265, "proteins": 9.2, "carbs": 52.0, "lipids": 2.4,
            "fiber": 3.8, "omega3": 0.08, "iron": 1.9, "magnesium": 54, "calcium": 28, "water_ml": 120
        },
    },
    {
        "keywords": ["lentilles", "pois chiches", "haricots", "feves", "petits pois"],
        "name": "Légumineuses cuites (Lentilles / Pois chiches - 170g)",
        "role": "feculent",
        "nutrients": {
            "calories": 215, "proteins": 14.5, "carbs": 34.0, "lipids": 2.2,
            "fiber": 8.6, "omega3": 0.12, "iron": 4.2, "magnesium": 64, "calcium": 48, "water_ml": 115
        },
    },
    {
        "keywords": ["patate douce", "pomme de terre", "patates", "puree", "pommes grenailles"],
        "name": "Pommes de terre / Patate douce au four ou vapeur (220g)",
        "role": "feculent",
        "nutrients": {
            "calories": 210, "proteins": 4.4, "carbs": 44.0, "lipids": 1.8,
            "fiber": 4.8, "omega3": 0.05, "iron": 1.6, "magnesium": 52, "calcium": 36, "water_ml": 155
        },
    },
    {
        "keywords": ["frites"],
        "name": "Portion de frites (150g)",
        "role": "feculent",
        "nutrients": {
            "calories": 410, "proteins": 5.0, "carbs": 50.0, "lipids": 21.0,
            "fiber": 4.2, "omega3": 0.15, "iron": 1.2, "magnesium": 42, "calcium": 20, "water_ml": 65
        },
    },
    {
        "keywords": ["brocoli", "epinard", "haricots verts", "courgette", "ratatouille", "legumes", "poelee", "chou", "carotte", "champignon", "asperge", "aubergine", "tomate"],
        "name": "Portion de légumes cuits ou poêlés à l'huile d'olive (180g)",
        "role": "legume",
        "nutrients": {
            "calories": 105, "proteins": 3.6, "carbs": 9.5, "lipids": 6.0,
            "fiber": 4.8, "omega3": 0.22, "iron": 1.8, "magnesium": 44, "calcium": 72, "water_ml": 155
        },
    },
    {
        "keywords": ["avocat", "guacamole"],
        "name": "Demi-avocat (80g)",
        "role": "accompagnement_lipide",
        "nutrients": {
            "calories": 135, "proteins": 1.6, "carbs": 3.0, "lipids": 13.2,
            "fiber": 5.2, "omega3": 0.12, "iron": 0.6, "magnesium": 26, "calcium": 12, "water_ml": 58
        },
    },
    {
        "keywords": ["soupe", "veloute", "potage", "bouillon"],
        "name": "Bol de soupe / Velouté de légumes maison (300ml)",
        "role": "legume",
        "nutrients": {
            "calories": 130, "proteins": 3.2, "carbs": 16.0, "lipids": 5.8,
            "fiber": 4.2, "omega3": 0.15, "iron": 1.2, "magnesium": 36, "calcium": 55, "water_ml": 265
        },
    },
]


def normalize_dish_key(dish_text: str) -> str:
    cleaned = dish_text.strip().lower()
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned


def evaluate_dish_locally(dish_text: str) -> Dict[str, Any]:
    """
    Analyse deterministe d'un texte libre de plat en composantes nutritionnelles
    (utilisee en fallback immediat ou pour completer le moteur hybride).
    """
    text_lower = normalize_dish_key(dish_text)
    if not text_lower:
        return {
            "nutrients": empty_nutrients(),
            "components": [],
            "eval_source": "moteur_culinaire",
        }

    matched_complete = []
    matched_modular = []

    for entry in CULINARY_COMPONENTS_DB:
        if any(kw in text_lower for kw in entry["keywords"]):
            if entry["role"] == "plat_complet":
                matched_complete.append(entry)
            else:
                matched_modular.append(entry)

    selected_components = []
    if matched_complete:
        # On prend le plat complet principal identifie
        primary = matched_complete[0]
        selected_components.append({
            "name": primary["name"],
            "nutrients": dict(primary["nutrients"]),
        })
        # Si l'utilisateur a mentionne explicitement un supplement non inclus (ex: avocat, soupe)
        for mod in matched_modular:
            if mod["role"] in ("accompagnement_lipide",) and mod["name"] != primary["name"]:
                selected_components.append({
                    "name": mod["name"],
                    "nutrients": dict(mod["nutrients"]),
                })
    elif matched_modular:
        seen_roles = set()
        for mod in matched_modular:
            # Permet de combiner Proteine + Feculent + Legume + Avocat
            role_key = mod["role"]
            if role_key not in seen_roles or role_key in ("legume", "accompagnement_lipide"):
                selected_components.append({
                    "name": mod["name"],
                    "nutrients": dict(mod["nutrients"]),
                })
                seen_roles.add(role_key)
    else:
        # Estimation intelligente d'une assiette equilibree standard si aucun mot-cle exact n'est trouve
        selected_components.append({
            "name": f"Assiette estimée : {dish_text.strip().capitalize()} (portion standard)",
            "nutrients": {
                "calories": 560, "proteins": 28.0, "carbs": 58.0, "lipids": 22.0,
                "fiber": 4.8, "omega3": 0.35, "iron": 2.8, "magnesium": 64, "calcium": 95, "water_ml": 220
            },
        })

    total_nutrients = sum_nutrients([c["nutrients"] for c in selected_components])
    return {
        "nutrients": total_nutrients,
        "components": selected_components,
        "eval_source": "moteur_culinaire",
    }


def assemble_meal_evaluation(
    dish_eval: Dict[str, Any],
    peripheral_ids: List[str],
    portion_size: str = "normal",
) -> Dict[str, Any]:
    """Combine le plat (ajuste a la portion) et les peripheriques rapides selectionnes."""
    multiplier = PORTION_MULTIPLIERS.get(portion_size, 1.0)
    scaled_dish_nutrients = scale_nutrients(dish_eval["nutrients"], multiplier)

    breakdown = []
    for comp in dish_eval.get("components", []):
        portion_suffix = ""
        if portion_size == "leger":
            portion_suffix = " [Portion légère x0.75]"
        elif portion_size == "copieux":
            portion_suffix = " [Portion copieuse x1.30]"
        breakdown.append({
            "name": f"{comp['name']}{portion_suffix}",
            "type": "plat",
            "nutrients": scale_nutrients(comp["nutrients"], multiplier),
        })

    peripheral_nutrients_list = []
    for pid in peripheral_ids:
        p_item = PERIPHERALS_BY_ID.get(pid)
        if p_item:
            peripheral_nutrients_list.append(p_item["nutrients"])
            breakdown.append({
                "name": f"{p_item['label']} ({p_item['portion_label']})",
                "type": "peripherique",
                "nutrients": dict(p_item["nutrients"]),
            })

    total_nutrients = sum_nutrients([scaled_dish_nutrients] + peripheral_nutrients_list)

    # Generation d'un commentaire factuel court sur l'apport du repas
    highlights = []
    if total_nutrients["proteins"] >= 35:
        highlights.append(f"apport protéique solide ({int(total_nutrients['proteins'])}g)")
    if total_nutrients["carbs"] >= 65:
        highlights.append(f"bonne recharge glucidique ({int(total_nutrients['carbs'])}g)")
    if total_nutrients["omega3"] >= 1.2:
        highlights.append(f"excellent apport en Oméga-3 ({total_nutrients['omega3']:.1f}g)")
    if total_nutrients["fiber"] >= 8.0:
        highlights.append(f"riche en fibres ({total_nutrients['fiber']:.1f}g)")
    if total_nutrients["magnesium"] >= 100:
        highlights.append(f"dense en magnésium ({int(total_nutrients['magnesium'])}mg)")
    if total_nutrients["iron"] >= 4.0:
        highlights.append(f"source notable de fer ({total_nutrients['iron']:.1f}mg)")

    if highlights:
        note = "Repas équilibré avec " + ", ".join(highlights[:3]) + "."
    else:
        note = f"Apport estimé à {int(total_nutrients['calories'])} kcal ({int(total_nutrients['proteins'])}g P / {int(total_nutrients['carbs'])}g G / {int(total_nutrients['lipids'])}g L)."

    return {
        "nutrients": total_nutrients,
        "components_breakdown": breakdown,
        "analysis_note": note,
        "eval_source": dish_eval.get("eval_source", "moteur_culinaire"),
    }


# Catalogue de recommandations ciblant les lacunes et le contexte sportif
RECOMMENDED_DISHES_CATALOG: List[Dict[str, Any]] = [
    {
        "id": "rec_saumon_lentilles",
        "title": "Pavé de saumon sauvage, lentilles vertes du Puy et épinards tombés",
        "prep_time": "20 min",
        "tags": ["omega3", "iron", "proteins", "magnesium", "fiber"],
        "diet_incompatible": ["vegetarien", "vegan", "sans_poisson"],
        "keywords": ["saumon", "lentilles", "epinards", "poisson"],
        "macros_summary": "640 kcal · 42g Prot · 48g Gluc · 2.5g Oméga-3 · 5.1mg Fer",
        "why_template": "Corrige simultanément les apports en Oméga-3, Fer et Protéines avec un index glycémique bas.",
    },
    {
        "id": "rec_dahl_corail_oeuf",
        "title": "Dahl de lentilles corail au lait de coco, pousses d'épinards, riz basmati et œuf mollet",
        "prep_time": "22 min",
        "tags": ["fiber", "iron", "magnesium", "carbs", "proteins"],
        "diet_incompatible": ["vegan"],
        "keywords": ["lentilles", "coco", "epinards", "riz", "oeuf"],
        "macros_summary": "610 kcal · 29g Prot · 76g Gluc · 11g Fibres · 5.6mg Fer · 115mg Mg",
        "why_template": "Idéal pour recharger les réserves de glycogène et remonter le Fer, le Magnésium et les Fibres.",
    },
    {
        "id": "rec_poulet_quinoa_brocoli",
        "title": "Bowl volaille marinée citron-herbes, quinoa, brocoli croquant, avocat et graines de courge",
        "prep_time": "18 min",
        "tags": ["proteins", "magnesium", "fiber", "carbs"],
        "diet_incompatible": ["vegetarien", "vegan"],
        "keywords": ["poulet", "volaille", "quinoa", "brocoli", "avocat"],
        "macros_summary": "630 kcal · 44g Prot · 56g Gluc · 8.5g Fibres · 135mg Mg",
        "why_template": "Soutient la reconstruction musculaire post-séance tout en apportant Magnésium et Fibres.",
    },
    {
        "id": "rec_maquereau_patate_douce",
        "title": "Filets de maquereaux au four, patate douce rôtie et salade de roquette aux noix",
        "prep_time": "25 min",
        "tags": ["omega3", "carbs", "proteins", "calcium", "magnesium"],
        "diet_incompatible": ["vegetarien", "vegan", "sans_poisson"],
        "keywords": ["maquereau", "poisson", "patate douce", "noix"],
        "macros_summary": "620 kcal · 34g Prot · 54g Gluc · 3.1g Oméga-3 · 95mg Mg",
        "why_template": "Densité maximale en Oméga-3 anti-inflammatoires et glucides complexes pour l'endurance.",
    },
    {
        "id": "rec_chili_boeuf_haricots",
        "title": "Chili maison au bœuf maigre, haricots rouges, poivrons et riz complet",
        "prep_time": "25 min",
        "tags": ["iron", "proteins", "fiber", "carbs", "magnesium"],
        "diet_incompatible": ["vegetarien", "vegan", "sans_boeuf"],
        "keywords": ["boeuf", "haricots rouges", "riz", "chili"],
        "macros_summary": "660 kcal · 41g Prot · 74g Gluc · 12g Fibres · 5.8mg Fer",
        "why_template": "Apport synergique en Fer héminique, Protéines et Glucides lents pour les semaines à forte charge.",
    },
    {
        "id": "rec_tofu_soba_edamame",
        "title": "Nouilles Soba au sarrasin, tofu laqué au sésame, edamame et brocolis sautés",
        "prep_time": "15 min",
        "tags": ["calcium", "magnesium", "proteins", "carbs", "iron", "fiber"],
        "diet_incompatible": [],
        "keywords": ["tofu", "soja", "sarrasin", "brocoli", "sesame"],
        "macros_summary": "580 kcal · 31g Prot · 68g Gluc · 340mg Calcium · 140mg Mg",
        "why_template": "Excellente source végétale de Calcium, Magnésium, Fer et Glucides complexes.",
    },
    {
        "id": "rec_porridge_sportif",
        "title": "Porridge flocons d'avoine, skyr/fromage blanc, banane, graines de chia et amandes",
        "prep_time": "5 min",
        "tags": ["calcium", "magnesium", "fiber", "omega3", "carbs", "proteins"],
        "diet_incompatible": ["sans_lactose", "vegan"],
        "keywords": ["avoine", "fromage blanc", "skyr", "banane", "chia", "amandes"],
        "macros_summary": "520 kcal · 26g Prot · 62g Gluc · 9.5g Fibres · 1.8g Oméga-3 · 310mg Ca",
        "why_template": "Petit-déjeuner ou collation haute densité couvrant Calcium, Oméga-3, Magnésium et Fibres.",
    },
]

CORRECTIVE_PERIPHERALS_CATALOG: List[Dict[str, Any]] = [
    {
        "peripheral_id": "poignee_oleagineux",
        "title": "1 poignée de noix & amandes (30g)",
        "targets": ["omega3", "magnesium", "fiber", "lipids", "calories"],
        "impact": "+1.15g Oméga-3 · +76mg Magnésium · +3.2g Fibres",
    },
    {
        "peripheral_id": "fromage_blanc",
        "title": "1 bol de Skyr ou Fromage blanc (150g)",
        "targets": ["proteins", "calcium"],
        "impact": "+13.5g Protéines · +195mg Calcium",
    },
    {
        "peripheral_id": "comte_fromage",
        "title": "1 portion de Comté ou Tomme (35g)",
        "targets": ["calcium", "proteins", "lipids", "calories"],
        "impact": "+330mg Calcium · +9.8g Protéines",
    },
    {
        "peripheral_id": "chocolat_noir",
        "title": "2 grands carrés de chocolat noir 85% (20g)",
        "targets": ["iron", "magnesium", "fiber"],
        "impact": "+2.4mg Fer · +46mg Magnésium · +2.8g Fibres",
    },
    {
        "peripheral_id": "crudites_olive",
        "title": "Assiette de crudités + 1 c.a.s huile de colza/noix",
        "targets": ["omega3", "fiber"],
        "impact": "+0.65g Oméga-3 · +2.5g Fibres",
    },
    {
        "peripheral_id": "banane",
        "title": "1 banane + 2 tranches de pain au levain",
        "targets": ["carbs", "calories", "fiber", "magnesium"],
        "impact": "+55g Glucides · +6.9g Fibres · +72mg Magnésium",
    },
]


def compute_day_weight(
    day_date_str: str,
    today_str: str,
    day_meals: List[Dict[str, Any]],
    is_marked_complete: bool,
) -> Tuple[float, str]:
    """
    Calcule le poids (0.0 a 1.0) d'une journee dans la moyenne glissante sur 7 jours.
    - Jour passe sans aucun repas (oubli) : poids 0.0 (exclu du diviseur).
    - Jour passe avec repas : poids 1.0 (ou proportionnel si un seul petit repas isole, sauf si marque complet).
    - Aujourd'hui : somme des poids des creneaux remplis (ou 1.0 si diner saisi ou marque complet).
    """
    if not day_meals:
        return 0.0, "vide"

    if is_marked_complete:
        return 1.0, "complet"

    slots_present = {m.get("meal_type", "dejeuner") for m in day_meals}

    if day_date_str < today_str:
        # Jour passe : si au moins 2 repas ou >= 1100 kcal, considere comme journée complete (1.0)
        day_kcal = sum(float(m.get("nutrients", {}).get("calories", 0.0)) for m in day_meals)
        if len(day_meals) >= 2 or day_kcal >= 1100 or "diner" in slots_present:
            return 1.0, "complet"
        # Sinon pondere selon les creneaux reellement saisis pour ne pas plomber la semaine
        w = sum(MEAL_SLOT_WEIGHTS.get(s, 0.30) for s in slots_present)
        return min(1.0, max(0.35, round(w, 2))), "partiel"

    # Aujourd'hui (journee en cours)
    if "diner" in slots_present and len(slots_present) >= 2:
        return 1.0, "complet"

    w = sum(MEAL_SLOT_WEIGHTS.get(s, 0.30) for s in slots_present)
    # Si plusieurs entrées sur le meme creneau, on assure un minimum coherent
    w = max(w, min(1.0, len(day_meals) * 0.28))
    return min(1.0, round(w, 2)), "en_cours"


def compute_rolling_dashboard(
    meals: List[Dict[str, Any]],
    workouts: List[Dict[str, Any]],
    profile: Dict[str, Any],
    day_statuses: Dict[str, bool],
    reference_date: Optional[date] = None,
) -> Dict[str, Any]:
    if reference_date is None:
        reference_date = date.today()

    today_str = reference_date.isoformat()
    start_7d_date = reference_date - timedelta(days=6)
    end_next_7d_date = reference_date + timedelta(days=7)

    baseline_targets = calculate_baseline_targets(profile)
    weight_kg = float(profile.get("weight_kg", 74.0))

    # Grouper les repas par date sur la fenetre [J-6 .. Aujourd'hui]
    meals_by_date: Dict[str, List[Dict[str, Any]]] = {}
    for m in meals:
        d_str = m["meal_date"]
        meals_by_date.setdefault(d_str, []).append(m)

    # Grouper les seances de sport
    past_window_workouts: List[Dict[str, Any]] = []
    upcoming_workouts: List[Dict[str, Any]] = []
    workouts_by_date: Dict[str, List[Dict[str, Any]]] = {}

    for w in workouts:
        w_date_str = w["workout_date"]
        workouts_by_date.setdefault(w_date_str, []).append(w)
        w_date = date.fromisoformat(w_date_str)
        if start_7d_date <= w_date <= reference_date and w.get("status") == "realisee":
            past_window_workouts.append(w)
        elif reference_date <= w_date <= end_next_7d_date and w.get("status") == "prevue":
            upcoming_workouts.append(w)

    # Calcul des apports et poids jour par jour sur les 7 derniers jours
    daily_history = []
    weighted_sum = empty_nutrients()
    total_effective_days = 0.0

    for offset in range(6, -1, -1):
        d_obj = reference_date - timedelta(days=offset)
        d_str = d_obj.isoformat()
        d_meals = meals_by_date.get(d_str, [])
        is_complete = bool(day_statuses.get(d_str, False))
        day_weight, day_state = compute_day_weight(d_str, today_str, d_meals, is_complete)

        day_nutrients = sum_nutrients([m["nutrients"] for m in d_meals])
        day_workouts = [
            w for w in workouts_by_date.get(d_str, []) if w.get("status") == "realisee"
        ]
        day_sport_Burn = sum_nutrients([w["expenditure"] for w in day_workouts])

        if day_weight > 0:
            for k in NUTRIENT_KEYS:
                weighted_sum[k] += day_nutrients[k]
            total_effective_days += day_weight

        daily_history.append({
            "date": d_str,
            "is_today": d_str == today_str,
            "day_weight": day_weight,
            "day_state": day_state,
            "marked_complete": is_complete,
            "meals_count": len(d_meals),
            "nutrients": day_nutrients,
            "sport_expenditure": day_sport_Burn,
            "workouts": day_workouts,
        })

    # Depense sportive quotidienne moyenne sur les 7 derniers jours
    total_sport_7d = sum_nutrients([w["expenditure"] for w in past_window_workouts])
    avg_daily_sport_7d = scale_nutrients(total_sport_7d, 1.0 / 7.0)

    # Bonus d'anticipation si une seance intense/longue est prevue aujourd'hui ou demain (J0 / J+1)
    tomorrow_str = (reference_date + timedelta(days=1)).isoformat()
    imminent_workouts = [
        w for w in upcoming_workouts if w["workout_date"] in (today_str, tomorrow_str)
    ]
    anticipation_bonus = empty_nutrients()
    if imminent_workouts:
        # On ajoute 35% des glucides et du magnesium de la seance imminente aux cibles pour preparer l'organisme
        imminent_exp = sum_nutrients([w["expenditure"] for w in imminent_workouts])
        anticipation_bonus["carbs"] = round(imminent_exp["carbs"] * 0.35, 1)
        anticipation_bonus["calories"] = round(anticipation_bonus["carbs"] * 4.0, 0)
        anticipation_bonus["magnesium"] = round(imminent_exp["magnesium"] * 0.30, 1)

    # Cibles quotidiennes ajustées (Base + Sport moyen 7j + Anticipation J+1)
    adjusted_targets = sum_nutrients([baseline_targets, avg_daily_sport_7d, anticipation_bonus])

    # Moyenne glissante sur 7 jours ponderee
    divisor = total_effective_days if total_effective_days > 0 else 1.0
    rolling_averages = {
        k: round(weighted_sum[k] / divisor, NUTRIENT_METADATA[k]["decimals"])
        for k in NUTRIENT_KEYS
    }

    # Evaluation de chaque nutriment par rapport a sa zone d'equilibre
    gauges = []
    deficiencies = []
    surpluses = []

    for k in NUTRIENT_KEYS:
        meta = NUTRIENT_METADATA[k]
        target_val = max(0.1, adjusted_targets[k])
        avg_val = rolling_averages[k]
        ratio = round(avg_val / target_val, 3) if total_effective_days > 0 else 0.0
        pct = round(ratio * 100.0)

        if total_effective_days == 0:
            status = "attente"
            status_label = "Aucune saisie"
        elif ratio < meta["eq_min"]:
            status = "lacune"
            deficit_pct = round((1.0 - ratio) * 100.0)
            status_label = f"-{deficit_pct}% sous la cible"
            deficiencies.append({
                "key": k,
                "label": meta["label"],
                "unit": meta["unit"],
                "avg": avg_val,
                "target": round(target_val, meta["decimals"]),
                "ratio": ratio,
                "pct": pct,
                "deficit_amount": round(target_val - avg_val, meta["decimals"]),
            })
        elif ratio > meta["eq_max"]:
            status = "surplus"
            surplus_pct = round((ratio - 1.0) * 100.0)
            status_label = f"+{surplus_pct}% au-dessus"
            surpluses.append({
                "key": k,
                "label": meta["label"],
                "pct": pct,
            })
        else:
            status = "equilibre"
            status_label = "Zone d'équilibre"

        gauges.append({
            "key": k,
            "label": meta["label"],
            "unit": meta["unit"],
            "group": meta["group"],
            "decimals": meta["decimals"],
            "average": avg_val,
            "baseline_target": round(baseline_targets[k], meta["decimals"]),
            "sport_bonus": round(avg_daily_sport_7d[k] + anticipation_bonus[k], meta["decimals"]),
            "adjusted_target": round(target_val, meta["decimals"]),
            "ratio": ratio,
            "percentage": pct,
            "eq_min_pct": round(meta["eq_min"] * 100),
            "eq_max_pct": round(meta["eq_max"] * 100),
            "status": status,
            "status_label": status_label,
        })

    # Trier les lacunes de la plus prononcee a la plus legere
    deficiencies.sort(key=lambda x: x["ratio"])

    # Generation des recommandations de plats et peripheriques et du bilan editorial
    recommendations = build_recommendations_and_editorial(
        deficiencies=deficiencies,
        surpluses=surpluses,
        gauges=gauges,
        past_workouts=past_window_workouts,
        upcoming_workouts=upcoming_workouts,
        imminent_workouts=imminent_workouts,
        profile=profile,
        total_effective_days=total_effective_days,
    )

    return {
        "reference_date": today_str,
        "window_start": start_7d_date.isoformat(),
        "effective_days_count": round(total_effective_days, 2),
        "baseline_targets": baseline_targets,
        "avg_daily_sport_bonus": avg_daily_sport_7d,
        "anticipation_bonus": anticipation_bonus,
        "adjusted_targets": adjusted_targets,
        "rolling_averages": rolling_averages,
        "gauges": gauges,
        "deficiencies": deficiencies,
        "daily_history": daily_history,
        "past_workouts_count": len(past_window_workouts),
        "upcoming_workouts": upcoming_workouts,
        "editorial": recommendations["editorial"],
        "sport_context_banner": recommendations["sport_context_banner"],
        "recommended_dishes": recommendations["recommended_dishes"],
        "corrective_peripherals": recommendations["corrective_peripherals"],
    }


def build_recommendations_and_editorial(
    deficiencies: List[Dict[str, Any]],
    surpluses: List[Dict[str, Any]],
    gauges: List[Dict[str, Any]],
    past_workouts: List[Dict[str, Any]],
    upcoming_workouts: List[Dict[str, Any]],
    imminent_workouts: List[Dict[str, Any]],
    profile: Dict[str, Any],
    total_effective_days: float,
) -> Dict[str, Any]:
    dietary_tags = set(profile.get("dietary_tags", []) or [])
    excluded_raw = (profile.get("excluded_foods") or "").lower()
    excluded_words = [w.strip() for w in excluded_raw.split(",") if w.strip()]

    deficit_keys = [d["key"] for d in deficiencies]

    # 1. Encart d'adaptation sportive (J-7 / J+7)
    total_past_min = sum(int(w.get("duration_min", 0)) for w in past_workouts)
    total_upcoming_min = sum(int(w.get("duration_min", 0)) for w in upcoming_workouts)

    if imminent_workouts:
        next_w = imminent_workouts[0]
        when_label = "aujourd'hui" if next_w["workout_date"] == date.today().isoformat() else "demain"
        sport_banner = {
            "headline": f"Anticipation : {next_w['title']} ({next_w['duration_min']} min, intensité {next_w['intensity']}) prévue {when_label}",
            "detail": (
                f"La cible de glucides (+{int(next_w['expenditure']['carbs'] * 0.35)}g/j) "
                f"est rehaussée par anticipation. "
                f"Sur les 7 derniers jours, {len(past_workouts)} séance(s) réalisée(s) ({total_past_min} min cumulées) "
                f"sont intégrées à votre besoin moyen."
            ),
        }
    elif upcoming_workouts:
        next_w = upcoming_workouts[0]
        sport_banner = {
            "headline": f"Charge sportive : {len(past_workouts)} séance(s) réalisée(s) (7j) · {len(upcoming_workouts)} séance(s) planifiée(s) ({total_upcoming_min} min)",
            "detail": (
                f"Prochaine échéance le {next_w['workout_date']} ({next_w['title']}, {next_w['duration_min']} min). "
                "Les objectifs de la semaine glissante incluent automatiquement la dépense de vos séances passées."
            ),
        }
    else:
        sport_banner = {
            "headline": f"Charge sportive sur 7 jours : {len(past_workouts)} séance(s) réalisée(s) ({total_past_min} min)",
            "detail": "Aucune séance planifiée sur les 7 prochains jours. Ajoutez vos prochaines séances pour anticiper vos besoins en glycogène et récupération.",
        }

    # 2. Note de synthese editoriale (ton sobre, précis, humain)
    if total_effective_days == 0:
        editorial = {
            "status_badge": "En attente de données",
            "title": "Renseignez votre premier repas pour initialiser la moyenne glissante.",
            "body": (
                "Le tableau de bord calcule vos apports sur une fenêtre glissante de 7 jours pondérée selon "
                "l'avancement de la journée, sans pénaliser les jours non saisis."
            ),
        }
    elif not deficiencies:
        editorial = {
            "status_badge": "Équilibre atteint",
            "title": "Vos apports sur 7 jours glissants sont parfaitement alignés avec votre charge d'entraînement.",
            "body": (
                "Sur la semaine glissante, l'ensemble des macronutriments et "
                "micronutriments suivis se situe dans la zone d'équilibre cible. Maintenez cette structure de repas."
            ),
        }
    else:
        top_def_labels = [d["label"] for d in deficiencies[:3]]
        joined_labels = ", ".join(top_def_labels)
        primary = deficiencies[0]

        body_parts = [
            f"Sur la semaine glissante, le suivi met en évidence "
            f"un retrait sur : {joined_labels} (notamment {primary['label']} à {primary['pct']}% de la cible, "
            f"soit un écart moyen de -{primary['deficit_amount']}{primary['unit']}/j)."
        ]
        if imminent_workouts:
            body_parts.append(
                f"Avec la séance prévue ({imminent_workouts[0]['title']}), veillez particulièrement aux apports "
                "glucidiques et minéraux lors des deux prochains repas."
            )
        else:
            body_parts.append(
                "Inutile de peser vos portions : l'ajout d'un plat dense ou d'un périphérique ciblé sur les 2 à 3 "
                "prochains repas suffira à ramener la moyenne hebdomadaire dans la zone d'équilibre."
            )

        editorial = {
            "status_badge": f"{len(deficiencies)} point(s) d'attention sur 7j",
            "title": f"Ajustement prioritaire : {joined_labels}",
            "body": " ".join(body_parts),
        }

    # 3. Selection des plats complets recommandes (filtres selon exclusions et lacunes)
    scored_dishes = []
    for dish in RECOMMENDED_DISHES_CATALOG:
        # Filtre regime alimentaire
        if dietary_tags.intersection(set(dish["diet_incompatible"])):
            continue
        # Filtre mots exclus par l'utilisateur
        if any(ex in " ".join(dish["keywords"]).lower() or ex in dish["title"].lower() for ex in excluded_words):
            continue

        matching_deficits = [d["label"] for d in deficiencies if d["key"] in dish["tags"]]
        score = len(matching_deficits) * 10
        # Bonus si seance imminente et plat riche en glucides/proteines
        if imminent_workouts and "carbs" in dish["tags"]:
            score += 4

        scored_dishes.append((score, matching_deficits, dish))

    scored_dishes.sort(key=lambda x: x[0], reverse=True)
    recommended_dishes = []
    for score, matched_labels, dish in scored_dishes[:3]:
        covered_str = ", ".join(matched_labels) if matched_labels else "Équilibre général & récupération"
        recommended_dishes.append({
            "id": dish["id"],
            "title": dish["title"],
            "prep_time": dish["prep_time"],
            "macros_summary": dish["macros_summary"],
            "covered_deficits": covered_str,
            "why": dish["why_template"],
        })

    # 4. Selection des peripheriques correcteurs rapides
    scored_peripherals = []
    for p_rec in CORRECTIVE_PERIPHERALS_CATALOG:
        matched_defs = [d["label"] for d in deficiencies if d["key"] in p_rec["targets"]]
        score = len(matched_defs) * 10
        if score > 0 or not deficiencies:
            scored_peripherals.append((score, matched_defs, p_rec))

    scored_peripherals.sort(key=lambda x: x[0], reverse=True)
    corrective_peripherals = []
    for score, matched_defs, p_rec in scored_peripherals[:4]:
        corrective_peripherals.append({
            "peripheral_id": p_rec["peripheral_id"],
            "title": p_rec["title"],
            "impact": p_rec["impact"],
            "targets_covered": ", ".join(matched_defs) if matched_defs else "Maintien quotidien",
        })

    return {
        "editorial": editorial,
        "sport_context_banner": sport_banner,
        "recommended_dishes": recommended_dishes,
        "corrective_peripherals": corrective_peripherals,
    }
