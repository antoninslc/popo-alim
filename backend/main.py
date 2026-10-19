from datetime import date, timedelta
import os
from typing import Any, Dict, List, Optional
from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from backend.database import (
    clear_all_user_entries,
    compute_user_data_version,
    delete_meal,
    delete_workout,
    get_cached_dish,
    get_day_statuses,
    get_profile,
    init_db,
    insert_chat_message,
    insert_meal,
    insert_workout,
    is_postgres_mode,
    list_chat_messages,
    list_meals,
    list_workouts,
    normalize_user_id,
    save_cached_dish,
    seed_demo_data,
    update_meal_by_id,
    update_profile,
    update_workout_status,
)
from backend.llm_service import (
    DEFAULT_GEMINI_MODEL,
    _extract_peripherals_and_clean_dish,
    _sanitize_llm_payload,
    call_llm_chat_agent,
    compose_contextual_reply,
    evaluate_dish_hybrid,
    has_env_gemini_key,
    interpret_chat_locally,
    summarize_meal_title,
    verify_llm_connection,
)
from backend.nutrition_engine import (
    PERIPHERALS_BY_ID,
    PERIPHERALS_CATALOG,
    assemble_meal_evaluation,
    calculate_baseline_targets,
    calculate_workout_expenditure,
    compute_rolling_dashboard,
)

app = FastAPI(title="Cadence - Suivi Nutritionnel et Sportif Pilote par IA")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

FRONTEND_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "frontend")


@app.on_event("startup")
def on_startup() -> None:
    try:
        init_db("default")
    except Exception:
        pass


def _resolve_uid(x_user_id: Optional[str], query_user: Optional[str]) -> str:
    uid = normalize_user_id(x_user_id or query_user or "default")
    init_db(uid)
    return uid


class ChatInput(BaseModel):
    message: str


class ProfileUpdateInput(BaseModel):
    sex: str = "H"
    age: int = 29
    height_cm: float = 179.0
    weight_kg: float = 74.0
    activity_level: str = "modere"
    goal: str = "performance"
    dietary_tags: List[str] = Field(default_factory=list)
    excluded_foods: str = ""
    llm_provider: str = "auto"
    api_key: Optional[str] = None
    llm_model: str = DEFAULT_GEMINI_MODEL
    verify_llm: bool = True


class WorkoutStatusUpdate(BaseModel):
    status: str


def build_full_state(user_id: str = "default") -> Dict[str, Any]:
    uid = normalize_user_id(user_id)
    today = date.today()
    start_meals = (today - timedelta(days=6)).isoformat()
    end_meals = (today + timedelta(days=1)).isoformat()
    start_workouts = (today - timedelta(days=6)).isoformat()
    end_workouts = (today + timedelta(days=7)).isoformat()

    profile = get_profile(uid)
    meals = list_meals(start_meals, end_meals, user_id=uid)
    workouts = list_workouts(start_workouts, end_workouts, user_id=uid)
    day_statuses = get_day_statuses(user_id=uid)

    dashboard = compute_rolling_dashboard(
        meals=meals,
        workouts=workouts,
        profile=profile,
        day_statuses=day_statuses,
        reference_date=today,
    )

    safe_profile = dict(profile)
    safe_profile["user_id"] = uid
    safe_profile["api_key"] = profile.get("api_key", "")
    safe_profile["env_api_key_active"] = has_env_gemini_key()
    safe_profile["calculated_baseline"] = calculate_baseline_targets(
        {**profile, "custom_targets_enabled": False}
    )

    return {
        "user_id": uid,
        "version": compute_user_data_version(uid),
        "storage_mode": "postgres" if is_postgres_mode() else "sqlite",
        "dashboard": dashboard,
        "peripherals_catalog": PERIPHERALS_CATALOG,
        "meals": meals,
        "workouts": workouts,
        "profile": safe_profile,
        "chat_messages": list_chat_messages(limit=20, user_id=uid),
    }


def _execute_agent_actions(
    actions: List[Dict[str, Any]],
    profile: Dict[str, Any],
    existing_meals: List[Dict[str, Any]],
    user_id: str = "default",
) -> List[str]:
    uid = normalize_user_id(user_id)
    summaries: List[str] = []
    weight_kg = float(profile.get("weight_kg", 74.0))
    today_iso = date.today().isoformat()

    for act in actions:
        if not isinstance(act, dict):
            continue
        act_type = act.get("type", "")

        if act_type == "add_meal":
            m_date = act.get("meal_date") or today_iso
            m_type = act.get("meal_type") or "dejeuner"
            raw_dish_txt = str(act.get("dish_text") or "").strip()
            periphs = [p for p in (act.get("peripherals") or []) if p in PERIPHERALS_BY_ID]
            portion = act.get("portion_size") or "normal"

            # Si des peripheriques sont fournis (ou detectables dans dish_text), nettoyer dish_text pour eviter tout double comptage
            cleaned_dish_txt, extra_periphs = _extract_peripherals_and_clean_dish(raw_dish_txt)
            if periphs:
                dish_txt = cleaned_dish_txt
            else:
                dish_txt = cleaned_dish_txt
                periphs = [p for p in extra_periphs if p in PERIPHERALS_BY_ID]

            cached = get_cached_dish(dish_txt)
            inline_components = act.get("components")
            if cached is None and dish_txt and isinstance(inline_components, list) and len(inline_components) > 0:
                dish_eval = _sanitize_llm_payload(
                    {"components": inline_components},
                    dish_txt,
                    meal_type=m_type,
                    already_peripherals=periphs,
                )
            else:
                dish_eval = evaluate_dish_hybrid(
                    dish_txt,
                    cached,
                    profile,
                    meal_type=m_type,
                    already_peripherals=periphs,
                )
            if dish_txt and cached is None and dish_eval.get("eval_source") != "peripheriques_seuls":
                save_cached_dish(dish_txt, dish_eval)

            assembled = assemble_meal_evaluation(dish_eval, periphs, portion)
            p_names = [PERIPHERALS_BY_ID[pid]["label"] for pid in periphs]
            short_title = summarize_meal_title(dish_txt, dish_eval.get("components"), periphs)
            if short_title:
                stored_title = short_title
                summary_display = f"{short_title} + {', '.join(p_names)}" if p_names else short_title
            else:
                stored_title = ", ".join(p_names) if p_names else "Repas"
                summary_display = stored_title

            created = insert_meal(
                meal_date=m_date,
                meal_type=m_type,
                dish_text=stored_title,
                peripherals=periphs,
                portion_size=portion,
                assembled=assembled,
                user_id=uid,
            )
            kcal = round(created["nutrients"]["calories"])
            summaries.append(f"Repas ajoute ({summary_display}, {kcal} kcal)")

        elif act_type == "update_meal":
            meal_id = int(act.get("meal_id", 0))
            target = next((m for m in existing_meals if m["id"] == meal_id), None)
            if target:
                raw_dish_txt = str(act.get("dish_text") or target["dish_text"]).strip()
                periphs = [p for p in (act.get("peripherals") or target["peripherals"]) if p in PERIPHERALS_BY_ID]
                portion = act.get("portion_size") or target["portion_size"]
                m_type = target.get("meal_type") or "dejeuner"
                cleaned_dish_txt, _ = _extract_peripherals_and_clean_dish(raw_dish_txt)
                dish_txt = cleaned_dish_txt if periphs else raw_dish_txt
                cached = get_cached_dish(dish_txt)
                inline_components = act.get("components")
                if cached is None and dish_txt and isinstance(inline_components, list) and len(inline_components) > 0:
                    dish_eval = _sanitize_llm_payload(
                        {"components": inline_components},
                        dish_txt,
                        meal_type=m_type,
                        already_peripherals=periphs,
                    )
                else:
                    dish_eval = evaluate_dish_hybrid(
                        dish_txt,
                        cached,
                        profile,
                        meal_type=m_type,
                        already_peripherals=periphs,
                    )
                if dish_txt and cached is None and dish_eval.get("eval_source") != "peripheriques_seuls":
                    save_cached_dish(dish_txt, dish_eval)
                assembled = assemble_meal_evaluation(dish_eval, periphs, portion)
                p_names = [PERIPHERALS_BY_ID[pid]["label"] for pid in periphs]
                short_title = summarize_meal_title(dish_txt, dish_eval.get("components"), periphs)
                display_txt = short_title if short_title else (", ".join(p_names) if p_names else "Repas")
                update_meal_by_id(meal_id, display_txt, periphs, portion, assembled, user_id=uid)
                summaries.append(f"Repas #{meal_id} mis a jour ({round(assembled['nutrients']['calories'])} kcal)")

        elif act_type == "delete_meal":
            meal_id = int(act.get("meal_id", 0))
            if delete_meal(meal_id, user_id=uid):
                summaries.append("Repas supprime")

        elif act_type == "add_workout":
            w_date = act.get("workout_date") or today_iso
            cat = act.get("category") or "endurance"
            title = str(act.get("title") or "Seance de sport").strip()
            dur = max(10, int(act.get("duration_min") or 50))
            intensity = act.get("intensity") or "moderee"
            if w_date < today_iso:
                status = "realisee"
            elif w_date > today_iso:
                status = "prevue"
            else:
                status = act.get("status") or "realisee"
            exp = calculate_workout_expenditure(cat, dur, intensity, weight_kg)
            insert_workout(w_date, cat, title, dur, intensity, status, exp, user_id=uid)
            state_lbl = "prevue" if status == "prevue" else "realisee"
            summaries.append(f"Seance {state_lbl} ajoutee ({title}, {dur} min, +{round(exp['calories'])} kcal)")

        elif act_type == "update_workout_status":
            w_id = int(act.get("workout_id", 0))
            new_st = act.get("status") or "realisee"
            if update_workout_status(w_id, new_st, user_id=uid):
                st_disp = "realisee" if new_st == "realisee" else "prevue"
                summaries.append(f"Seance marquee comme {st_disp}")

        elif act_type == "delete_workout":
            w_id = int(act.get("workout_id", 0))
            if delete_workout(w_id, user_id=uid):
                summaries.append("Seance supprimee")

        elif act_type == "update_profile":
            updates: Dict[str, Any] = {}
            if "weight_kg" in act and act["weight_kg"]:
                updates["weight_kg"] = float(act["weight_kg"])
            if "goal" in act and act["goal"]:
                updates["goal"] = str(act["goal"])
            if updates:
                update_profile(updates, user_id=uid)
                summaries.append("Profil mis a jour")

    return summaries


@app.get("/api/version")
def api_get_version(
    x_user_id: Optional[str] = Header(default=None),
    user: Optional[str] = Query(default=None),
) -> Dict[str, Any]:
    uid = _resolve_uid(x_user_id, user)
    return {"user_id": uid, "version": compute_user_data_version(uid)}


@app.get("/api/state")
def api_get_state(
    x_user_id: Optional[str] = Header(default=None),
    user: Optional[str] = Query(default=None),
) -> Dict[str, Any]:
    uid = _resolve_uid(x_user_id, user)
    return build_full_state(uid)


@app.post("/api/chat")
def api_chat(
    payload: ChatInput,
    x_user_id: Optional[str] = Header(default=None),
    user: Optional[str] = Query(default=None),
) -> Dict[str, Any]:
    uid = _resolve_uid(x_user_id, user)
    user_msg = payload.message.strip()
    if not user_msg:
        raise HTTPException(status_code=400, detail="Message vide.")

    insert_chat_message("user", user_msg, user_id=uid)

    pre_state = build_full_state(uid)
    profile = pre_state["profile"]
    meals = pre_state["meals"]
    workouts = pre_state["workouts"]
    dash = pre_state["dashboard"]

    context_lines = [
        f"Date du jour : {date.today().isoformat()}",
        f"Lacunes actuelles sur 7j : {', '.join(d['label'] + ' (' + str(d['pct']) + '%)' for d in dash['deficiencies']) or 'Aucune'}",
        "Derniers repas (ID, date, creneau, plat) : "
        + "; ".join(f"#{m['id']} {m['meal_date']} {m['meal_type']}: {m['dish_text']}" for m in meals[:6]),
        "Seances (ID, date, statut, titre) : "
        + "; ".join(f"#{w['id']} {w['workout_date']} ({w['status']}): {w['title']} {w['duration_min']}m" for w in workouts[:6]),
    ]
    llm_result = call_llm_chat_agent(user_msg, "\n".join(context_lines), profile)

    if llm_result and isinstance(llm_result, dict):
        actions = llm_result.get("actions") or []
        executed_summaries = _execute_agent_actions(actions, profile, meals, user_id=uid)
        reply_text = str(llm_result.get("reply") or "").strip()
        if not reply_text:
            post_state = build_full_state(uid) if actions else pre_state
            reply_text = compose_contextual_reply(user_msg, executed_summaries, post_state["dashboard"])
    else:
        actions = interpret_chat_locally(user_msg, meals, workouts, date.today())
        executed_summaries = _execute_agent_actions(actions, profile, meals, user_id=uid)
        post_state = build_full_state(uid) if actions else pre_state
        reply_text = compose_contextual_reply(user_msg, executed_summaries, post_state["dashboard"])

    summary_badge = " · ".join(executed_summaries) if executed_summaries else "Analyse & Conseil 7j"
    insert_chat_message("assistant", reply_text, summary_badge, user_id=uid)

    return build_full_state(uid)


@app.delete("/api/meals/{meal_id}")
def api_delete_meal(
    meal_id: int,
    x_user_id: Optional[str] = Header(default=None),
    user: Optional[str] = Query(default=None),
) -> Dict[str, Any]:
    uid = _resolve_uid(x_user_id, user)
    delete_meal(meal_id, user_id=uid)
    return build_full_state(uid)


@app.patch("/api/workouts/{workout_id}/status")
def api_update_workout_status(
    workout_id: int,
    payload: WorkoutStatusUpdate,
    x_user_id: Optional[str] = Header(default=None),
    user: Optional[str] = Query(default=None),
) -> Dict[str, Any]:
    uid = _resolve_uid(x_user_id, user)
    update_workout_status(workout_id, payload.status, user_id=uid)
    return build_full_state(uid)


@app.delete("/api/workouts/{workout_id}")
def api_delete_workout(
    workout_id: int,
    x_user_id: Optional[str] = Header(default=None),
    user: Optional[str] = Query(default=None),
) -> Dict[str, Any]:
    uid = _resolve_uid(x_user_id, user)
    delete_workout(workout_id, user_id=uid)
    return build_full_state(uid)


@app.put("/api/profile")
def api_update_profile(
    payload: ProfileUpdateInput,
    x_user_id: Optional[str] = Header(default=None),
    user: Optional[str] = Query(default=None),
) -> Dict[str, Any]:
    uid = _resolve_uid(x_user_id, user)
    dump = payload.model_dump()
    verify_llm = dump.pop("verify_llm", True)
    updated_prof = update_profile(dump, user_id=uid)
    verif = None
    if verify_llm:
        verif = verify_llm_connection(updated_prof)
        if verif.get("resolved_model") and verif["resolved_model"] != updated_prof.get("llm_model"):
            update_profile({"llm_model": verif["resolved_model"]}, user_id=uid)
    state = build_full_state(uid)
    if verif is not None:
        state["llm_verification"] = verif
    return state


@app.post("/api/demo/reset")
def api_reset_demo(
    x_user_id: Optional[str] = Header(default=None),
    user: Optional[str] = Query(default=None),
) -> Dict[str, Any]:
    uid = _resolve_uid(x_user_id, user)
    seed_demo_data(user_id=uid)
    return build_full_state(uid)


@app.post("/api/demo/clear")
def api_clear_demo(
    x_user_id: Optional[str] = Header(default=None),
    user: Optional[str] = Query(default=None),
) -> Dict[str, Any]:
    uid = _resolve_uid(x_user_id, user)
    clear_all_user_entries(user_id=uid)
    return build_full_state(uid)


if os.path.isdir(FRONTEND_DIR):
    app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")


@app.get("/favicon.svg", include_in_schema=False)
def serve_favicon_svg() -> FileResponse:
    return FileResponse(os.path.join(FRONTEND_DIR, "favicon.svg"), media_type="image/svg+xml")


@app.get("/favicon.ico", include_in_schema=False)
def serve_favicon_ico() -> FileResponse:
    return FileResponse(os.path.join(FRONTEND_DIR, "icon-192.png"), media_type="image/png")


@app.get("/apple-touch-icon.png", include_in_schema=False)
@app.get("/apple-touch-icon-precomposed.png", include_in_schema=False)
def serve_apple_touch_icon() -> FileResponse:
    return FileResponse(os.path.join(FRONTEND_DIR, "apple-touch-icon.png"), media_type="image/png")


@app.get("/")
def serve_index() -> FileResponse:
    return FileResponse(os.path.join(FRONTEND_DIR, "index.html"))
