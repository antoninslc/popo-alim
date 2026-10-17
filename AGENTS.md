# AGENTS.md - Guide d'architecture et conventions du projet Cadence

Ce fichier sert de reference rapide pour naviguer, maintenir et faire evoluer l'application **Cadence** (suivi nutritionnel et sportif sur 7 jours glissants, pilote par IA).

---

## 1. Regles strictes de developpement

1. **Aucun emoji dans le code** (HTML, CSS, JS, Python, SQL, documentation technique).
2. **Interdiction absolue d'executer du code inline via `python -c`** dans le terminal.
3. **Scripts et tests** : Toujours utiliser l'interpreteur virtuel `.\.venv\bin\python.exe`.
4. **Fichier de test unique** : Utiliser strictement et systematiquement `scratch\run_test.py` pour tous les tests ponctuels (ecraser son contenu a chaque fois, ne jamais creer `run_test_2.py`, etc.).

---

## 2. Demarrage du serveur

Pour lancer le serveur local FastAPI (port `8000`) :

```powershell
.\.venv\bin\python.exe run_server.py
```

- URL de l'application : `http://127.0.0.1:8000`
- Point d'entree serveur : `run_server.py` (charge `backend.main:app` via `uvicorn`).

---

## 3. Architecture des fichiers

```text
clever-hopper/
├── AGENTS.md                  # Ce guide d'architecture et conventions
├── requirements.txt           # Dependances Python (fastapi, uvicorn, pydantic, httpx)
├── run_server.py              # Script de lancement Uvicorn (127.0.0.1:8000)
├── nutrition.db               # Base SQLite locale (creee et peuplee automatiquement)
├── backend/
│   ├── __init__.py
│   ├── main.py                # Routes API FastAPI + montage statique du frontend
│   ├── database.py            # Schema SQLite, CRUD (repas, sport, profil, cache) et seed demo
│   ├── nutrition_engine.py    # Calculs metaboliques, 7j glissants, peripheriques, recommandations
│   └── llm_service.py         # Orchestrateur IA multi-fournisseurs + parseur local francais
├── frontend/
│   ├── index.html             # Structure 2 pages ("Aujourd'hui & 7j" et "Reglages")
│   ├── styles.css             # Design System style Apple (macOS Sonoma / iOS Health)
│   └── app.js                 # Logique UI, barre Spotlight IA, barres 7j, tiroirs par jour
└── scratch/
    └── run_test.py            # Fichier unique dedie aux tests automatises et verifications API
```

---

## 4. Fonctionnement metier et moteurs principaux

### 4.1 Moteur nutritionnel et metabolique (`backend/nutrition_engine.py`)
- **BMR & TDEE** : Formule de Mifflin-St Jeor + facteur d'activite hors-sport (`nef_factor`) + ajustement selon l'objectif (`maintien`, `seche`, `prise_masse`, `recomposition`, `performance`).
- **Lissage sportif sur 7 jours glissants** :
  - Fenetre d'analyse : `J-6` a `Aujourd'hui` pour les apports consolides.
  - Les seances realisees (`completed` sur `J-6..J0`) et les seances planifiees (`planned` sur `J0..J+6`) ajustent dynamiquement les cibles quotidiennes en Energie, Glucides, Proteines, Hydratation, Magnesium et Fer (`calculate_workout_expenditure`).
- **Logique Anti-Biais (Jours consolides)** :
  - Un jour est comptabilise dans le denominateur de la moyenne 7j s'il comporte au moins `2 repas` ou `>= 900 kcal`, ou s'il est explicitement cloture (`day_status.is_closed = 1`).
  - Les jours partiels en cours (ex: seulement le petit-dejeuner saisi aujourd'hui) sont visibles avec un coefficient proratise sans fausser la moyenne hebdomadaire.
- **Catalogue de peripheriques (`PERIPHERALS_CATALOG`)** :
  - 15 accompagnements standards pre-calibres (`pain_blanc`, `pain_complet`, `fromage`, `beurre`, `huile_olive`, `fruits_coque`, `fruit_frais`, `yaourt_nature`, `chocolat_noir`, `verre_vin`, `cafe_sucre`, `oeuf_extra`, `avocat_demi`, `legumineuses_side`, `soda_verre`).
- **10 Indicateurs suivis (`NUTRIENT_META`)** :
  - `kcal`, `protein_g`, `carbs_g`, `fat_g`, `fiber_g`, `omega3_g`, `iron_mg`, `magnesium_mg`, `calcium_mg`, `water_ml`.

### 4.2 Moteur IA Hybride et Multi-Fournisseurs (`backend/llm_service.py`)
- **3 niveaux de resolution** :
  1. **Cache SQLite (`dish_cache`)** : Evite les appels API redondants pour un meme plat + portion.
  2. **API Cloud LLM (`call_llm_chat_agent`, `evaluate_dish_hybrid`)** : Supporte plusieurs fournisseurs gratuits ou payants avec auto-detection par prefixe de cle :
     - `AIza...` -> **Google Gemini Studio** (`gemini-2.0-flash`, gratuit sans CB)
     - `gsk_...` -> **Groq Cloud** (`llama-3.3-70b-versatile`, gratuit sans CB)
     - `sk-or-...` -> **OpenRouter** (`meta-llama/llama-3.3-70b-instruct:free`)
     - `sk-...` -> **OpenAI** (`gpt-4o-mini`)
     - `oc_sk_...` -> **OpenCode** (Note : le tier gratuit OpenCode est restreint au client CLI interne OpenCode via `FreeTierError` ; necessite du credit ou l'usage de Gemini/Groq pour une web-app).
  3. **Moteur deterministe local (`interpret_chat_locally`, `estimate_dish_locally`)** :
     - Parseur francais complet capable de creer/modifier/supprimer des repas, ajouter/valider/annuler des seances de sport (passees ou prevues sur J+7), modifier le profil et repondre aux questions nutritionnelles 100% hors-ligne si aucune cle API active n'est disponible.
- **Verification en direct (`verify_llm_connection`)** :
  - Appelee lors de `PUT /api/profile` pour tester instantanement la cle API saisie dans la page `Reglages` et afficher un retour explicite a l'utilisateur.

### 4.3 Interface Utilisateur (`frontend/`)
- **Design System** : Style Apple (macOS Sonoma / iOS Health), typographie systeme SF Pro / Inter, surfaces translucides (`backdrop-filter`), aucune surcharge visuelle.
- **2 Pages uniquement** :
  1. `Aujourd'hui & 7j` (`#view-main`) :
     - **Haut** : Barre de commande IA universelle type Spotlight + puces de suggestions + bulle de reponse unique de l'assistant (avec historique depliable).
     - **Milieu** : Carte des 10 barres d'indicateurs sur 7 jours glissants avec zone d'equilibre `90% - 110%` et infobulle detaillee au survol.
     - **Bas** : 2 tiroirs repliables (**fermes par defaut**) : *Historique des repas* (gauche) et *Activites sportives J-7 / J+7* (droite), tries et groupes par jour.
  2. `Reglages` (`#view-settings`) :
     - Parametres biologiques, objectif, selecteur de fournisseur IA, cle API avec verification instantanee (`#settings-save-feedback`), et reinitialisation des donnees.

---

## 5. Endpoints API (`backend/main.py`)

- `GET /api/state` : Retourne l'etat complet (profil, repas 7j, seances J-7/J+7, bilan `rolling_7d`, historique `chat_messages`, catalogue de peripheriques).
- `POST /api/chat` : Point d'entree principal du chat IA. Execute les actions detectees (`log_meal`, `delete_meal`, `update_meal`, `log_workout`, `update_workout_status`, `delete_workout`, `update_profile`, `ask_analysis`) et retourne l'etat mis a jour.
- `PUT /api/profile` : Met a jour le profil + cle API et renvoie `llm_verification` (test de connexion en direct).
- `DELETE /api/meals/{meal_id}` : Supprime un repas.
- `PATCH /api/workouts/{workout_id}/status` : Bascule une seance entre `planned` et `completed`.
- `DELETE /api/workouts/{workout_id}` : Supprime une seance.
- `POST /api/demo/reset` : Reinitialise la base avec le jeu de donnees de demonstration sur 7 jours.
- `POST /api/demo/clear` : Vide tous les repas, seances et messages pour repartir de zero.
