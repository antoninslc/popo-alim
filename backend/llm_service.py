from datetime import date, timedelta
import json
import os
import re
from typing import Any, Dict, List, Optional, Tuple
import httpx

from backend.nutrition_engine import (
    NUTRIENT_KEYS,
    PERIPHERALS_CATALOG,
    empty_nutrients,
    evaluate_dish_locally,
    normalize_dish_key,
    sum_nutrients,
)


SYSTEM_PROMPT_DISH_PARSER = """Tu es un nutritionniste du sport francophone expert en estimation de portions standards.
L'utilisateur saisit l'intitulé d'un plat sans grammage précis.
Décomposition attendue :
- Identifie les composantes probables du plat pour une portion adulte standard (1.0x).
- Estime les 10 indicateurs nutritionnels suivants pour chacune des composantes :
  calories (kcal), proteins (g), carbs (g), lipids (g), fiber (g), omega3 (g), iron (mg), magnesium (mg), calcium (mg), water_ml (ml).
Reponds UNIQUEMENT avec un objet JSON valide respectant strictement ce format :
{
  "components": [
    {
      "name": "Nom de la composante et portion estimée en g",
      "nutrients": {
        "calories": 0, "proteins": 0, "carbs": 0, "lipids": 0,
        "fiber": 0, "omega3": 0, "iron": 0, "magnesium": 0, "calcium": 0, "water_ml": 0
      }
    }
  ]
}
Aucun markdown, aucun commentaire autour du JSON."""


SYSTEM_PROMPT_CHAT_AGENT = """Tu es l'assistant nutritionnel et sportif qui pilote intégralement le site de suivi de l'utilisateur.
Tu dois analyser le message de l'utilisateur et retourner un objet JSON contenant :
1. "actions" : liste d'opérations à exécuter sur la base de données (peut être vide si l'utilisateur pose seulement une question).
   Types d'actions possibles :
   - {"type": "add_meal", "meal_date": "YYYY-MM-DD", "meal_type": "petit_dejeuner|dejeuner|collation|diner", "dish_text": "intitulé du plat sans les périphériques déjà listés", "peripherals": ["id_peripherique"], "portion_size": "leger|normal|copieux"}
   - {"type": "update_meal", "meal_id": 12, "dish_text": "nouveau texte", "peripherals": ["id_peripherique"], "portion_size": "leger|normal|copieux"}
   - {"type": "delete_meal", "meal_id": 12}
   - {"type": "add_workout", "workout_date": "YYYY-MM-DD", "category": "endurance|force|hiit_sport_co|velo_natation|mobilite_marche", "title": "Titre propre", "duration_min": 60, "intensity": "douce|moderee|intense", "status": "realisee|prevue"}
   - {"type": "update_workout_status", "workout_id": 5, "status": "realisee|prevue"}
   - {"type": "delete_workout", "workout_id": 5}
   - {"type": "update_profile", "weight_kg": 74.0, "goal": "maintien|performance|prise_masse|seche"}
2. "reply" : ta réponse directe à l'utilisateur en français (2 à 4 phrases maximum, ton sobre, précis, sans aucun emoji ni jargon IA). Confirme ce que tu viens d'enregistrer/modifier, commente son positionnement sur la moyenne glissante de 7 jours et propose des exemples concrets de plats ou d'aliments pour combler ses lacunes ou préparer ses séances prévues.

IDs des périphériques disponibles :
pain_levain, pain_blanc, comte_fromage, fromage_blanc, yaourt_nature, fruit_saison, banane, poignee_oleagineux, chocolat_noir, crudites_olive, dessert_sucre, grand_verre_eau, gourde_eau, cafe_the, verre_vin_biere.

Reponds UNIQUEMENT en JSON valide : {"actions": [...], "reply": "..."}."""


def _sanitize_llm_payload(raw_data: Dict[str, Any], fallback_text: str) -> Dict[str, Any]:
    components_in = raw_data.get("components", [])
    clean_components = []
    for comp in components_in:
        if not isinstance(comp, dict):
            continue
        name = str(comp.get("name", fallback_text)).strip()
        raw_nutr = comp.get("nutrients", {}) or {}
        clean_nutr = {
            k: round(max(0.0, float(raw_nutr.get(k, 0.0))), 2)
            for k in NUTRIENT_KEYS
        }
        clean_components.append({"name": name, "nutrients": clean_nutr})

    if not clean_components:
        return evaluate_dish_locally(fallback_text)

    total = sum_nutrients([c["nutrients"] for c in clean_components])
    return {
        "nutrients": total,
        "components": clean_components,
        "eval_source": "api_llm",
    }


def _extract_json_object(raw_text: str) -> Dict[str, Any]:
    cleaned = (raw_text or "").strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start != -1 and end != -1 and end > start:
        cleaned = cleaned[start : end + 1]
    return json.loads(cleaned)


def _load_dotenv_if_present() -> None:
    root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    env_path = os.path.join(root_dir, ".env")
    if not os.path.isfile(env_path):
        return
    try:
        with open(env_path, "r", encoding="utf-8") as f:
            for raw_line in f:
                line = raw_line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                key = k.strip()
                val = v.strip().strip('"').strip("'")
                if key and key not in os.environ:
                    os.environ[key] = val
    except Exception:
        pass


_load_dotenv_if_present()


OPENAI_COMPATIBLE_PROVIDERS: Dict[str, Tuple[str, str]] = {
    "opencode": ("https://opencode.ai/inference/openai/v1/chat/completions", "glm-5.3-flash-free"),
    "groq": ("https://api.groq.com/openai/v1/chat/completions", "llama-3.3-70b-versatile"),
    "openrouter": ("https://openrouter.ai/api/v1/chat/completions", "meta-llama/llama-3.3-70b-instruct:free"),
    "openai": ("https://api.openai.com/v1/chat/completions", "gpt-4o-mini"),
}


def has_env_gemini_key() -> bool:
    _load_dotenv_if_present()
    return bool((os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY") or "").strip())


def _resolve_provider_and_key(profile_settings: Dict[str, Any]) -> Tuple[str, str, str]:
    _load_dotenv_if_present()
    provider = (profile_settings.get("llm_provider") or "auto").lower().strip()
    api_key = (profile_settings.get("api_key") or "").strip()
    model_name = (profile_settings.get("llm_model") or os.environ.get("GEMINI_MODEL") or "").strip()

    if not api_key:
        env_gemini = (os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY") or "").strip()
        if env_gemini and provider in ("auto", "gemini"):
            api_key = env_gemini
            provider = "gemini"
        else:
            api_key = (
                env_gemini
                or os.environ.get("GROQ_API_KEY", "")
                or os.environ.get("OPENROUTER_API_KEY", "")
                or os.environ.get("OPENAI_API_KEY", "")
                or os.environ.get("OPENCODE_API_KEY", "")
            ).strip()

    if provider == "auto" and api_key:
        if api_key.startswith("gsk_"):
            provider = "groq"
        elif api_key.startswith("sk-or-"):
            provider = "openrouter"
        elif api_key.startswith(("AIza", "AQ.")):
            provider = "gemini"
        elif api_key.startswith("sk-"):
            provider = "openai"
        else:
            provider = "gemini"

    return provider, api_key, model_name


def _call_gemini_api(dish_text: str, api_key: str, model: str = "gemini-2.0-flash") -> Optional[Dict[str, Any]]:
    models_to_try = [model] if model == "gemini-2.0-flash" else [model, "gemini-2.0-flash"]
    payload = {
        "contents": [
            {
                "role": "user",
                "parts": [{"text": f"{SYSTEM_PROMPT_DISH_PARSER}\n\nPlat saisi : {dish_text}"}],
            }
        ],
        "generationConfig": {"temperature": 0.1, "responseMimeType": "application/json"},
    }
    with httpx.Client(timeout=12.0) as client:
        for candidate_model in models_to_try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{candidate_model}:generateContent?key={api_key}"
            resp = client.post(url, json=payload)
            if resp.status_code == 404 and candidate_model != "gemini-2.0-flash":
                continue
            resp.raise_for_status()
            data = resp.json()
            candidates = data.get("candidates", [])
            if not candidates:
                return None
            text_out = candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "")
            parsed = _extract_json_object(text_out)
            return _sanitize_llm_payload(parsed, dish_text)
    return None


def _call_openai_compatible_json(
    url: str,
    api_key: str,
    model: str,
    system_prompt: str,
    user_prompt: str,
    temperature: float = 0.1,
) -> Optional[Dict[str, Any]]:
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    base_payload: Dict[str, Any] = {
        "model": model,
        "temperature": temperature,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    }
    with httpx.Client(timeout=14.0) as client:
        payload_with_fmt = dict(base_payload, response_format={"type": "json_object"})
        resp = client.post(url, headers=headers, json=payload_with_fmt)
        if resp.status_code >= 400:
            resp = client.post(url, headers=headers, json=base_payload)
        resp.raise_for_status()
        data = resp.json()
        text_out = data["choices"][0]["message"]["content"]
        return _extract_json_object(text_out)


def verify_llm_connection(profile_settings: Dict[str, Any]) -> Dict[str, Any]:
    provider, api_key, model_name = _resolve_provider_and_key(profile_settings)
    if provider == "local_hybrid" or not api_key:
        return {
            "ok": True,
            "mode": "local",
            "message": "Réglages enregistrés. Mode hybride local actif (aucune clé API).",
        }

    try:
        if provider in OPENAI_COMPATIBLE_PROVIDERS:
            endpoint_url, default_model = OPENAI_COMPATIBLE_PROVIDERS[provider]
            target_model = model_name if model_name else default_model
            headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
            payload = {
                "model": target_model,
                "messages": [{"role": "user", "content": "Reponds uniquement par: {\"ok\": true}"}],
            }
            with httpx.Client(timeout=8.0) as client:
                resp = client.post(endpoint_url, headers=headers, json=payload)
                if resp.status_code == 200:
                    return {
                        "ok": True,
                        "mode": provider,
                        "message": f"Clé API enregistrée et validée avec succès ({provider} / {target_model}).",
                    }
                if resp.status_code == 403 and "FreeTierError" in resp.text:
                    return {
                        "ok": False,
                        "mode": provider,
                        "message": "Clé bien enregistrée, mais OpenCode bloque l'accès gratuit aux applications tierces (FreeTierError). Utilisez une clé Google Gemini Studio (AIza...) ou Groq (gsk_...) pour un accès 100% gratuit sans blocage.",
                    }
                if resp.status_code == 402:
                    return {
                        "ok": False,
                        "mode": provider,
                        "message": "Clé bien enregistrée, mais solde insuffisant ($0.00) sur ce modèle payant.",
                    }
                return {
                    "ok": False,
                    "mode": provider,
                    "message": f"Clé enregistrée, mais le serveur {provider} a répondu HTTP {resp.status_code}.",
                }
        else:
            target_model = model_name if model_name else "gemini-2.0-flash"
            models_to_try = [target_model] if target_model == "gemini-2.0-flash" else [target_model, "gemini-2.0-flash"]
            payload = {"contents": [{"role": "user", "parts": [{"text": "Ok"}]}]}
            with httpx.Client(timeout=8.0) as client:
                last_status = 0
                for candidate_model in models_to_try:
                    url = f"https://generativelanguage.googleapis.com/v1beta/models/{candidate_model}:generateContent?key={api_key}"
                    resp = client.post(url, json=payload)
                    last_status = resp.status_code
                    if resp.status_code == 200:
                        return {
                            "ok": True,
                            "mode": "gemini",
                            "resolved_model": candidate_model,
                            "message": f"Cle API Gemini enregistree et validee avec succes ({candidate_model}).",
                        }
                    if resp.status_code == 404 and candidate_model != "gemini-2.0-flash":
                        continue
                return {
                    "ok": False,
                    "mode": "gemini",
                    "message": f"Cle enregistree, mais Google Gemini a repondu HTTP {last_status}.",
                }
    except Exception as exc:
        return {
            "ok": False,
            "mode": provider,
            "message": f"Clé enregistrée localement, mais erreur réseau lors du test ({str(exc)[:60]}).",
        }


def evaluate_dish_hybrid(
    dish_text: str,
    cached_entry: Optional[Dict[str, Any]],
    profile_settings: Dict[str, Any],
) -> Dict[str, Any]:
    norm_key = normalize_dish_key(dish_text)
    if not norm_key:
        return {
            "nutrients": empty_nutrients(),
            "components": [],
            "eval_source": "peripheriques_seuls",
        }

    if cached_entry is not None:
        return {
            "nutrients": cached_entry["nutrients"],
            "components": cached_entry["components"],
            "eval_source": "cache_hybride",
        }

    provider, api_key, model_name = _resolve_provider_and_key(profile_settings)

    if api_key and provider != "local_hybrid":
        try:
            if provider in OPENAI_COMPATIBLE_PROVIDERS:
                endpoint_url, default_model = OPENAI_COMPATIBLE_PROVIDERS[provider]
                target_model = model_name if model_name else default_model
                parsed = _call_openai_compatible_json(
                    endpoint_url,
                    api_key,
                    target_model,
                    SYSTEM_PROMPT_DISH_PARSER,
                    f"Plat saisi : {dish_text}",
                    temperature=0.1,
                )
                if parsed:
                    return _sanitize_llm_payload(parsed, dish_text)
            else:
                target_model = model_name if model_name else "gemini-2.0-flash"
                res = _call_gemini_api(dish_text, api_key, target_model)
                if res:
                    return res
        except Exception:
            pass

    return evaluate_dish_locally(dish_text)


# ============================================================================
# MOTEUR D'AGENT CONVERSATIONNEL (PILOTAGE INTEGRAL DU SITE PAR LE CHAT)
# ============================================================================

PERIPHERAL_KEYWORDS_MAP: List[Tuple[List[str], str]] = [
    (["pain complet", "pain au levain", "pain levain", "tranche de pain", "bout de pain", "du pain"], "pain_levain"),
    (["baguette"], "pain_blanc"),
    (["comte", "tomme", "fromage affine", "morceau de fromage", "bout de fromage"], "comte_fromage"),
    (["fromage blanc", "skyr", "petit suisse"], "fromage_blanc"),
    (["yaourt"], "yaourt_nature"),
    (["banane"], "banane"),
    (["pomme", "poire", "orange", "kiwi", "clémentine", "clementine", "fruit", "abricot", "peche", "fraise"], "fruit_saison"),
    (["amande", "noix", "noisette", "oleagineux", "poignee de noix", "poignee d'amandes", "cajou"], "poignee_oleagineux"),
    (["chocolat noir", "carre de chocolat", "carres de chocolat", "chocolat"], "chocolat_noir"),
    (["crudite", "salade verte", "petite salade"], "crudites_olive"),
    (["gateau", "patisserie", "biscuit", "cookie", "tarte sucr", "mousse au chocolat", "dessert"], "dessert_sucre"),
    (["gourde", "600ml", "600 ml", "bouteille d'eau"], "gourde_eau"),
    (["verre d'eau", "tisane", "de l'eau"], "grand_verre_eau"),
    (["cafe", "expresso", "the vert", "un the"], "cafe_the"),
    (["verre de vin", "biere", "demi de biere", "pinte"], "verre_vin_biere"),
]


def _extract_relative_date(text_lower: str, today: date) -> Tuple[str, bool]:
    """Retourne (iso_date, is_future)."""
    if "avant-hier" in text_lower or "avant hier" in text_lower:
        return (today - timedelta(days=2)).isoformat(), False
    if "apres-demain" in text_lower or "apres demain" in text_lower:
        return (today + timedelta(days=2)).isoformat(), True
    if "demain" in text_lower:
        return (today + timedelta(days=1)).isoformat(), True
    if "hier" in text_lower:
        return (today - timedelta(days=1)).isoformat(), False

    m_in_days = re.search(r"dans\s+(\d+)\s+jour", text_lower)
    if m_in_days:
        d_plus = min(7, max(1, int(m_in_days.group(1))))
        return (today + timedelta(days=d_plus)).isoformat(), True

    m_ago_days = re.search(r"il y a\s+(\d+)\s+jour", text_lower)
    if m_ago_days:
        d_minus = min(7, max(1, int(m_ago_days.group(1))))
        return (today - timedelta(days=d_minus)).isoformat(), False

    weekdays = {
        "lundi": 0, "mardi": 1, "mercredi": 2, "jeudi": 3,
        "vendredi": 4, "samedi": 5, "dimanche": 6,
    }
    for w_name, w_idx in weekdays.items():
        if re.search(rf"\b{w_name}\b", text_lower):
            current_w = today.weekday()
            # Si futur mentionne ("je vais", "prevu", "prochain", "demain")
            is_future_hint = any(
                k in text_lower for k in ["prevu", "prevois", "vais", "prochain", "planifie", "ferai"]
            )
            if is_future_hint:
                days_ahead = (w_idx - current_w) % 7
                if days_ahead == 0:
                    days_ahead = 7
                return (today + timedelta(days=days_ahead)).isoformat(), True
            else:
                days_back = (current_w - w_idx) % 7
                return (today - timedelta(days=days_back)).isoformat(), False

    return today.isoformat(), False


def _extract_meal_slot(text_lower: str) -> str:
    if any(k in text_lower for k in ["petit-dej", "petit dej", "ce matin", "matin", "breakfast"]):
        return "petit_dejeuner"
    if any(k in text_lower for k in ["gouter", "collation", "cet apres-midi", "apres-midi", "16h"]):
        return "collation"
    if any(k in text_lower for k in ["diner", "ce soir", "hier soir", "soir", "souper"]):
        return "diner"
    return "dejeuner"


def _extract_portion(text_lower: str) -> str:
    if any(k in text_lower for k in ["grosse portion", "copieux", "beaucoup", "double portion", "bien mange", "grand bol", "grande assiette"]):
        return "copieux"
    if any(k in text_lower for k in ["petite portion", "leger", "un peu", "demi portion", "petit bol"]):
        return "leger"
    return "normal"


def _extract_peripherals_and_clean_dish(segment_text: str) -> Tuple[str, List[str]]:
    text_lower = segment_text.lower()
    found_periphs: List[str] = []
    cleaned = segment_text

    for kw_list, pid in PERIPHERAL_KEYWORDS_MAP:
        for kw in kw_list:
            if kw in text_lower:
                if pid not in found_periphs:
                    found_periphs.append(pid)
                # Retirer proprement le peripherique du texte du plat principal s'il est introduit par "avec / et / +"
                cleaned = re.sub(rf"(?i)\b(avec|et|\+)\s+(un|une|du|de la|des|deux|2|1)?\s*{re.escape(kw)}s?\b", "", cleaned)
                break

    # Nettoyer les prefixes conversationnels et temporels en boucle
    for _ in range(3):
        cleaned = re.sub(
            r"(?i)^(j'ai mange|j ai mange|je viens de manger|au dejeuner|au diner|au petit-dejeuner|au petit dejeuner|ce midi|ce matin|ce soir|hier soir|hier midi|aujourd'hui|hier|j'ai pris|j ai pris|ajoute|enregistre|un|une|du|de la|des)\s*(:|,|-)?\s*",
            "",
            cleaned.strip(),
        )
    cleaned = re.sub(
        r"(?i)\b(ce midi|ce matin|ce soir|hier soir|hier midi|aujourd'hui|hier|en grosse portion|en petite portion|portion normale|copieux|leger)\b",
        "",
        cleaned,
    )
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" ,.-+:")
    if cleaned:
        cleaned = cleaned[0].upper() + cleaned[1:]
    return cleaned, found_periphs


def _detect_workout_in_segment(segment_text: str, today: date) -> Optional[Dict[str, Any]]:
    text_lower = segment_text.lower()
    sport_triggers = [
        "course", "couru", "courir", "footing", "run", "seuil", "fractionne", "vma", "trail",
        "muscu", "musculation", "renfo", "renforcement", "salle", "jambes", "haut du corps", "force", "crossfit",
        "velo", "cyclisme", "natation", "nage", "piscine",
        "foot", "basket", "tennis", "padel", "badminton", "hiit", "cardio", "boxe",
        "marche", "randonnee", "yoga", "mobilite", "pilates",
        "seance", "entrainement", "sport",
    ]
    if not any(re.search(rf"\b{t}", text_lower) for t in sport_triggers):
        return None

    w_date, is_future_date = _extract_relative_date(text_lower, today)
    is_planned = is_future_date or any(
        k in text_lower for k in ["prevu", "prevois", "vais", "demain", "apres-demain", "prochain", "planifie", "ferai", "programme"]
    )
    status = "prevue" if is_planned else "realisee"

    # Categorie et titre
    if any(k in text_lower for k in ["muscu", "renfo", "force", "salle", "jambes", "haut du corps", "haltere"]):
        category = "force"
        default_title = "Musculation / Renforcement"
        if "jambe" in text_lower or "bas du corps" in text_lower:
            default_title = "Musculation Bas du corps"
        elif "haut" in text_lower:
            default_title = "Musculation Haut du corps"
    elif any(k in text_lower for k in ["velo", "cyclisme", "natation", "nage", "piscine"]):
        category = "velo_natation"
        default_title = "Sortie Vélo" if "velo" in text_lower or "cyclisme" in text_lower else "Séance Natation"
    elif any(k in text_lower for k in ["hiit", "fractionne", "vma", "football", "tennis", "padel", "basket", "boxe", "crossfit"]) or re.search(r"\bfoot\b", text_lower):
        category = "hiit_sport_co"
        if "fractionne" in text_lower or "vma" in text_lower:
            default_title = "Fractionné / VMA"
        elif "padel" in text_lower or "tennis" in text_lower:
            default_title = "Tennis / Padel"
        elif re.search(r"\b(foot|football)\b", text_lower):
            default_title = "Football"
        else:
            default_title = "Séance HIIT / Cardio"
    elif any(k in text_lower for k in ["marche", "yoga", "mobilite", "pilates", "etirement", "randonnee"]):
        category = "mobilite_marche"
        default_title = "Mobilité / Marche active"
    else:
        category = "endurance"
        default_title = "Sortie Course à pied"
        if "longue" in text_lower:
            default_title = "Sortie longue Course à pied"
        elif "footing" in text_lower:
            default_title = "Footing endurance"

    # Duree en minutes
    duration_min = 50
    m_hm = re.search(r"(\d+)\s*h\s*(\d+)?", text_lower)
    m_min = re.search(r"(\d+)\s*(?:min|mn|minutes|m\b)", text_lower)
    if m_hm:
        h = int(m_hm.group(1))
        mins = int(m_hm.group(2)) if m_hm.group(2) else 0
        duration_min = h * 60 + mins
    elif m_min:
        duration_min = int(m_min.group(1))

    # Intensite
    intensity = "moderee"
    if any(k in text_lower for k in ["intense", "dur", "seuil", "vma", "fractionne", "grosse", "fond", "max", "soutenue"]):
        intensity = "intense"
    elif any(k in text_lower for k in ["douce", "doux", "tranquille", "cool", "leger", "legere", "souple", "recup"]):
        intensity = "douce"

    return {
        "type": "add_workout",
        "workout_date": w_date,
        "category": category,
        "title": default_title,
        "duration_min": max(10, min(360, duration_min)),
        "intensity": intensity,
        "status": status,
    }


def interpret_chat_locally(
    user_message: str,
    meals: List[Dict[str, Any]],
    workouts: List[Dict[str, Any]],
    today: Optional[date] = None,
) -> List[Dict[str, Any]]:
    """
    Analyseur conversationnel local francophone capable de traduire un message libre
    en actions sur la base de donnees (repas, sport, profil, suppressions, modifications).
    """
    if today is None:
        today = date.today()

    text = user_message.strip()
    text_lower = text.lower()
    actions: List[Dict[str, Any]] = []

    # 1. Mise a jour du poids ou de l'objectif
    m_weight = re.search(r"(?:je pese|mon poids est de|poids a|poids :|descendu a|monte a)\s*(\d+(?:[.,]\d+)?)\s*kg", text_lower)
    if m_weight:
        w_val = float(m_weight.group(1).replace(",", "."))
        actions.append({"type": "update_profile", "weight_kg": w_val})

    if any(k in text_lower for k in ["objectif seche", "passer en seche", "objectif perte"]):
        actions.append({"type": "update_profile", "goal": "seche"})
    elif any(k in text_lower for k in ["objectif prise de masse", "prise de muscle"]):
        actions.append({"type": "update_profile", "goal": "prise_masse"})
    elif any(k in text_lower for k in ["objectif maintien"]):
        actions.append({"type": "update_profile", "goal": "maintien"})

    # 2. Suppression d'un repas ou d'une seance
    if any(k in text_lower for k in ["supprime", "enleve", "efface", "retire", "annule"]):
        target_date, _ = _extract_relative_date(text_lower, today)
        if any(k in text_lower for k in ["seance", "sport", "course", "muscu", "entrainement", "footing", "velo"]):
            # Chercher la seance correspondante
            candidates = [w for w in workouts if w["workout_date"] == target_date] or workouts
            if candidates:
                actions.append({"type": "delete_workout", "workout_id": candidates[0]["id"]})
                return actions
        elif any(k in text_lower for k in ["repas", "dejeuner", "diner", "petit-dejeuner", "petit dej", "collation", "plat", "dernier"]):
            if "dernier" in text_lower and meals:
                actions.append({"type": "delete_meal", "meal_id": meals[0]["id"]})
                return actions
            slot = _extract_meal_slot(text_lower)
            candidates = [m for m in meals if m["meal_date"] == target_date and m["meal_type"] == slot]
            if not candidates:
                candidates = [m for m in meals if m["meal_date"] == target_date] or meals
            if candidates:
                actions.append({"type": "delete_meal", "meal_id": candidates[0]["id"]})
                return actions

    # 3. Validation d'une seance prevue ("j'ai fait ma seance", "seance faite", "valide ma seance")
    if any(k in text_lower for k in ["fait ma seance", "seance faite", "valide ma seance", "valider la seance", "fait mon sport"]):
        planned = [w for w in workouts if w["status"] == "prevue"]
        if planned:
            # Prendre la plus proche
            planned.sort(key=lambda x: x["workout_date"])
            actions.append({"type": "update_workout_status", "workout_id": planned[0]["id"], "status": "realisee"})
            return actions

    # 4. Modification d'un repas existant ("ajoute une pomme a mon dejeuner", "finalement grosse portion")
    is_modification = any(
        k in text_lower
        for k in ["ajoute a mon", "rajoute a mon", "a mon dejeuner", "a mon diner", "a mon petit", "finalement"]
    )
    if is_modification and meals:
        target_date, _ = _extract_relative_date(text_lower, today)
        slot = _extract_meal_slot(text_lower)
        candidates = [m for m in meals if m["meal_date"] == target_date and m["meal_type"] == slot] or [meals[0]]
        target_meal = candidates[0]
        _, new_periphs = _extract_peripherals_and_clean_dish(text)
        merged_periphs = list(dict.fromkeys((target_meal.get("peripherals") or []) + new_periphs))
        new_portion = _extract_portion(text_lower) if any(p in text_lower for p in ["portion", "copieux", "leger", "grosse", "petite"]) else target_meal["portion_size"]
        actions.append({
            "type": "update_meal",
            "meal_id": target_meal["id"],
            "dish_text": target_meal["dish_text"],
            "peripherals": merged_periphs,
            "portion_size": new_portion,
        })
        return actions

    # 5. Si c'est uniquement une question de bilan / conseil sans saisie d'aliment ni sport
    question_only_patterns = [
        "ou j'en suis", "ou en suis-je", "bilan", "lacune", "que manger", "quoi manger",
        "conseil", "recommand", "idee de plat", "idees de plat", "prochain repas",
        "comment combler", "qu'est-ce que je", "que dois-je",
    ]
    is_question = "?" in text or any(q in text_lower for q in question_only_patterns)

    # Decouper la phrase si l'utilisateur combine repas ET sport (ex: "Ce midi j'ai mange X et demain je cours 1h")
    clauses = re.split(r"\b(?:et sinon|et demain|et hier|et aujourd'hui|et je prevois|et j'ai couru|et j'ai fait|;\s*)\b", text, flags=re.IGNORECASE)
    if len(clauses) == 1:
        clauses = [text]
    else:
        # Reconstruire proprement les connecteurs coupes si besoin
        clauses = [c.strip() for c in re.split(r"[.;]|(?=\bdemain\b|\bhier\b|\bje prevois\b|\bj'ai couru\b)", text, flags=re.IGNORECASE) if c.strip()]

    for clause in clauses:
        clause_lower = clause.lower()
        w_action = _detect_workout_in_segment(clause, today)
        if w_action and not any(q in clause_lower for q in ["que manger", "quoi manger", "bilan", "conseil"]):
            actions.append(w_action)
            continue

        # Verifier si la clause decrit un repas
        meal_indicators = [
            "mange", "pris", "dejeuner", "diner", "petit-dej", "petit dej", "ce midi", "ce matin", "ce soir",
            "hier soir", "hier midi", "collation", "gouter", "assiette", "bol", "plat",
            "poulet", "saumon", "boeuf", "steak", "pates", "riz", "lasagne", "pizza", "burger", "salade",
            "omelette", "oeuf", "flocons", "avoine", "tartine", "soupe", "sandwich", "poke", "ramen",
            "dahl", "lentilles", "chili", "couscous", "quiche", "tofu", "maquereau", "cabillaud", "thon",
        ]
        _, detected_periphs = _extract_peripherals_and_clean_dish(clause)
        has_food = any(k in clause_lower for k in meal_indicators) or len(detected_periphs) > 0

        if has_food and not is_question:
            m_date, _ = _extract_relative_date(clause_lower, today)
            m_slot = _extract_meal_slot(clause_lower)
            m_portion = _extract_portion(clause_lower)
            cleaned_dish, periphs = _extract_peripherals_and_clean_dish(clause)
            if cleaned_dish or periphs:
                actions.append({
                    "type": "add_meal",
                    "meal_date": m_date,
                    "meal_type": m_slot,
                    "dish_text": cleaned_dish,
                    "peripherals": periphs,
                    "portion_size": m_portion,
                })

    return actions


def call_llm_chat_agent(
    user_message: str,
    context_summary: str,
    profile_settings: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    provider, api_key, model_name = _resolve_provider_and_key(profile_settings)

    if not api_key or provider == "local_hybrid":
        return None

    full_user_prompt = f"Contexte actuel du suivi :\n{context_summary}\n\nMessage de l'utilisateur : {user_message}"

    try:
        if provider in OPENAI_COMPATIBLE_PROVIDERS:
            endpoint_url, default_model = OPENAI_COMPATIBLE_PROVIDERS[provider]
            target_model = model_name if model_name else default_model
            return _call_openai_compatible_json(
                endpoint_url,
                api_key,
                target_model,
                SYSTEM_PROMPT_CHAT_AGENT,
                full_user_prompt,
                temperature=0.2,
            )
        else:
            target_model = model_name if model_name else "gemini-2.0-flash"
            models_to_try = [target_model] if target_model == "gemini-2.0-flash" else [target_model, "gemini-2.0-flash"]
            payload = {
                "contents": [
                    {
                        "role": "user",
                        "parts": [{"text": f"{SYSTEM_PROMPT_CHAT_AGENT}\n\n{full_user_prompt}"}],
                    }
                ],
                "generationConfig": {"temperature": 0.2, "responseMimeType": "application/json"},
            }
            with httpx.Client(timeout=14.0) as client:
                for candidate_model in models_to_try:
                    url = f"https://generativelanguage.googleapis.com/v1beta/models/{candidate_model}:generateContent?key={api_key}"
                    resp = client.post(url, json=payload)
                    if resp.status_code == 404 and candidate_model != "gemini-2.0-flash":
                        continue
                    resp.raise_for_status()
                    data = resp.json()
                    candidates = data.get("candidates", [])
                    if not candidates:
                        return None
                    text_out = candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "")
                    return _extract_json_object(text_out)
            return None
    except Exception:
        return None


def compose_contextual_reply(
    user_message: str,
    executed_summaries: List[str],
    dashboard: Dict[str, Any],
) -> str:
    """
    Genere une reponse sobre, humaine et directement utile apres execution des actions
    ou en reponse a une question de l'utilisateur.
    """
    msg_lower = user_message.lower()
    deficiencies = dashboard.get("deficiencies", [])
    rec_dishes = dashboard.get("recommended_dishes", [])
    rec_periphs = dashboard.get("corrective_peripherals", [])
    upcoming = dashboard.get("upcoming_workouts", [])

    parts: List[str] = []

    if executed_summaries:
        parts.append("Enregistré : " + " ; ".join(executed_summaries) + ".")

    # Point sur les lacunes et l'objectif
    if not deficiencies:
        parts.append(
            "Sur votre moyenne glissante de 7 jours, tous vos indicateurs (macros, minéraux et hydratation) sont dans la zone d'équilibre."
        )
    else:
        top_defs = [f"{d['label']} ({d['pct']}%)" for d in deficiencies[:3]]
        parts.append(
            f"Sur la semaine glissante, vos principaux points à rehausser sont : {', '.join(top_defs)}."
        )

    # Si l'utilisateur demande quoi manger, des idees, ou s'il y a des lacunes
    wants_periphs = any(k in msg_lower for k in ["petit ajout", "peripherique", "collation", "sans cuisiner", "aliments"])
    if wants_periphs and rec_periphs:
        p_texts = [f"{p['title']} ({p['impact']})" for p in rec_periphs[:3]]
        parts.append("Pour corriger cela facilement sans cuisiner, ajoutez : " + " ou ".join(p_texts) + ".")
    elif rec_dishes and deficiencies:
        d1 = rec_dishes[0]
        d2 = rec_dishes[1] if len(rec_dishes) > 1 else None
        suggestion = f"Pour votre prochain repas, je vous suggère : {d1['title']}"
        if d2:
            suggestion += f", ou {d2['title']}"
        if rec_periphs:
            suggestion += f" (ou en ajout simple : {rec_periphs[0]['title'].lower()})."
        else:
            suggestion += "."
        parts.append(suggestion)

    if upcoming and any(k in msg_lower for k in ["sport", "seance", "bilan", "semaine", "demain", "prevu", "que manger"]):
        next_w = upcoming[0]
        parts.append(
            f"Note sport : {next_w['title']} ({next_w['duration_min']} min, {next_w['intensity']}) prévue le {next_w['workout_date']} — vos cibles glucidiques et hydriques en tiennent compte."
        )

    return " ".join(parts)
