from datetime import date, datetime, timedelta
import json
import os
import re
import sqlite3
import tempfile
from typing import Any, Dict, List, Optional, Tuple

from backend.nutrition_engine import (
    assemble_meal_evaluation,
    calculate_workout_expenditure,
    evaluate_dish_locally,
    normalize_dish_key,
)

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_SQLITE_PATH = os.path.join(ROOT_DIR, "nutrition.db")


def _resolve_postgres_url() -> str:
    for env_key in (
        "POSTGRES_URL",
        "DATABASE_URL",
        "STORAGE_URL",
        "STORAGE_POSTGRES_URL",
        " STORAGE_DATABASE_URL",
        "POSTGRES_PRISMA_URL",
        "NEON_DATABASE_URL",
    ):
        val = (os.environ.get(env_key.strip()) or "").strip()
        if val:
            if val.startswith("postgres://"):
                val = "postgresql://" + val[len("postgres://"):]
            return val
    return ""


def _resolve_sqlite_path() -> str:
    custom = (os.environ.get("SQLITE_DB_PATH") or "").strip()
    if custom:
        return custom
    if os.path.exists(DEFAULT_SQLITE_PATH) and os.access(DEFAULT_SQLITE_PATH, os.W_OK):
        return DEFAULT_SQLITE_PATH
    if os.access(ROOT_DIR, os.W_OK):
        return DEFAULT_SQLITE_PATH
    return os.path.join(tempfile.gettempdir(), "cadence_nutrition.db")


def is_postgres_mode() -> bool:
    return bool(_resolve_postgres_url())


def normalize_user_id(raw_user_id: Optional[str]) -> str:
    if not raw_user_id:
        return "default"
    cleaned = re.sub(r"[^a-z0-9_-]", "", str(raw_user_id).strip().lower())
    return cleaned[:32] if cleaned else "default"


class DBWrapper:
    def __init__(self) -> None:
        self.pg_url = _resolve_postgres_url()
        self.is_pg = bool(self.pg_url)
        if self.is_pg:
            import psycopg2
            import psycopg2.extras

            self.conn = psycopg2.connect(self.pg_url)
            self.cur = self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        else:
            db_path = _resolve_sqlite_path()
            self.conn = sqlite3.connect(db_path)
            self.conn.row_factory = sqlite3.Row
            self.cur = self.conn.cursor()

    def _adapt_sql(self, sql: str) -> str:
        if self.is_pg:
            return sql.replace("?", "%s")
        return sql

    def execute(self, sql: str, params: Tuple[Any, ...] | List[Any] = ()) -> Any:
        adapted = self._adapt_sql(sql)
        self.cur.execute(adapted, tuple(params))
        return self.cur

    def execute_insert_id(self, sql: str, params: Tuple[Any, ...] | List[Any] = ()) -> int:
        if self.is_pg:
            adapted = self._adapt_sql(sql.rstrip().rstrip(";") + " RETURNING id")
            self.cur.execute(adapted, tuple(params))
            row = self.cur.fetchone()
            return int(row["id"]) if row else 0
        else:
            self.cur.execute(sql, tuple(params))
            return int(self.cur.lastrowid or 0)

    def fetchone(self) -> Optional[Dict[str, Any]]:
        row = self.cur.fetchone()
        return dict(row) if row is not None else None

    def fetchall(self) -> List[Dict[str, Any]]:
        rows = self.cur.fetchall()
        return [dict(r) for r in rows]

    @property
    def rowcount(self) -> int:
        return int(self.cur.rowcount or 0)

    def commit(self) -> None:
        self.conn.commit()

    def close(self) -> None:
        try:
            self.cur.close()
        except Exception:
            pass
        self.conn.close()


def get_connection() -> DBWrapper:
    return DBWrapper()


def _migrate_sqlite_columns_if_needed(db: DBWrapper) -> None:
    if db.is_pg:
        return

    for table_name in ("meals", "workouts", "chat_messages"):
        db.execute(f"PRAGMA table_info({table_name})")
        cols = [r["name"] for r in db.fetchall()]
        if cols and "user_id" not in cols:
            db.execute(f"ALTER TABLE {table_name} ADD COLUMN user_id TEXT NOT NULL DEFAULT 'default'")

    db.execute("PRAGMA table_info(day_status)")
    ds_cols = [r["name"] for r in db.fetchall()]
    if ds_cols and "user_id" not in ds_cols:
        db.execute("ALTER TABLE day_status RENAME TO day_status_legacy")
        db.execute(
            """
            CREATE TABLE day_status (
                user_id TEXT NOT NULL DEFAULT 'default',
                day_date TEXT NOT NULL,
                marked_complete INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (user_id, day_date)
            )
            """
        )
        db.execute(
            """
            INSERT INTO day_status (user_id, day_date, marked_complete)
            SELECT 'default', day_date, marked_complete FROM day_status_legacy
            """
        )
        db.execute("DROP TABLE day_status_legacy")

    db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='profile'")
    has_old_profile = db.fetchone() is not None
    if has_old_profile:
        db.execute("SELECT COUNT(*) AS cnt FROM user_profiles WHERE user_id = 'default'")
        cnt_row = db.fetchone()
        if not cnt_row or int(cnt_row["cnt"]) == 0:
            db.execute("SELECT * FROM profile WHERE id = 1")
            old_prof = db.fetchone()
            if old_prof:
                db.execute(
                    """
                    INSERT INTO user_profiles (
                        user_id, sex, age, height_cm, weight_kg, activity_level, goal,
                        dietary_tags_json, excluded_foods, custom_targets_enabled,
                        custom_targets_json, llm_provider, api_key, llm_model
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "default",
                        old_prof["sex"],
                        old_prof["age"],
                        old_prof["height_cm"],
                        old_prof["weight_kg"],
                        old_prof["activity_level"],
                        old_prof["goal"],
                        old_prof["dietary_tags_json"],
                        old_prof["excluded_foods"],
                        old_prof["custom_targets_enabled"],
                        old_prof["custom_targets_json"],
                        old_prof.get("llm_provider", "auto"),
                        old_prof.get("api_key", ""),
                        old_prof.get("llm_model", "gemini-2.0-flash"),
                    ),
                )


_SCHEMA_INITIALIZED = False


def init_db(user_id: str = "default") -> None:
    global _SCHEMA_INITIALIZED
    uid = normalize_user_id(user_id)
    db = get_connection()

    if not _SCHEMA_INITIALIZED:
        id_col_def = "SERIAL PRIMARY KEY" if db.is_pg else "INTEGER PRIMARY KEY AUTOINCREMENT"

        db.execute(
            """
            CREATE TABLE IF NOT EXISTS user_profiles (
                user_id TEXT PRIMARY KEY,
                sex TEXT NOT NULL DEFAULT 'H',
                age INTEGER NOT NULL DEFAULT 29,
                height_cm REAL NOT NULL DEFAULT 179.0,
                weight_kg REAL NOT NULL DEFAULT 74.0,
                activity_level TEXT NOT NULL DEFAULT 'modere',
                goal TEXT NOT NULL DEFAULT 'performance',
                dietary_tags_json TEXT NOT NULL DEFAULT '[]',
                excluded_foods TEXT NOT NULL DEFAULT '',
                custom_targets_enabled INTEGER NOT NULL DEFAULT 0,
                custom_targets_json TEXT NOT NULL DEFAULT '{}',
                llm_provider TEXT NOT NULL DEFAULT 'auto',
                api_key TEXT NOT NULL DEFAULT '',
                llm_model TEXT NOT NULL DEFAULT 'gemini-2.0-flash'
            )
            """
        )

        db.execute(
            """
            CREATE TABLE IF NOT EXISTS dish_cache (
                normalized_key TEXT PRIMARY KEY,
                display_name TEXT NOT NULL,
                nutrients_json TEXT NOT NULL,
                components_json TEXT NOT NULL,
                eval_source TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )

        db.execute(
            f"""
            CREATE TABLE IF NOT EXISTS meals (
                id {id_col_def},
                user_id TEXT NOT NULL DEFAULT 'default',
                meal_date TEXT NOT NULL,
                meal_type TEXT NOT NULL,
                dish_text TEXT NOT NULL,
                peripherals_json TEXT NOT NULL,
                portion_size TEXT NOT NULL DEFAULT 'normal',
                nutrients_json TEXT NOT NULL,
                components_breakdown_json TEXT NOT NULL,
                analysis_note TEXT NOT NULL,
                eval_source TEXT NOT NULL,
                is_favorite INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            )
            """
        )

        db.execute(
            f"""
            CREATE TABLE IF NOT EXISTS workouts (
                id {id_col_def},
                user_id TEXT NOT NULL DEFAULT 'default',
                workout_date TEXT NOT NULL,
                category TEXT NOT NULL,
                title TEXT NOT NULL,
                duration_min INTEGER NOT NULL,
                intensity TEXT NOT NULL,
                status TEXT NOT NULL,
                expenditure_json TEXT NOT NULL,
                notes TEXT NOT NULL DEFAULT ''
            )
            """
        )

        db.execute(
            """
            CREATE TABLE IF NOT EXISTS day_status (
                user_id TEXT NOT NULL DEFAULT 'default',
                day_date TEXT NOT NULL,
                marked_complete INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (user_id, day_date)
            )
            """
        )

        db.execute(
            f"""
            CREATE TABLE IF NOT EXISTS chat_messages (
                id {id_col_def},
                user_id TEXT NOT NULL DEFAULT 'default',
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                actions_summary TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            )
            """
        )

        _migrate_sqlite_columns_if_needed(db)
        db.commit()
        _SCHEMA_INITIALIZED = True

    ensure_user_initialized(uid, db)
    db.close()


def ensure_user_initialized(user_id: str = "default", db: Optional[DBWrapper] = None) -> None:
    uid = normalize_user_id(user_id)
    should_close = False
    if db is None:
        db = get_connection()
        should_close = True

    db.execute("SELECT COUNT(*) AS cnt FROM user_profiles WHERE user_id = ?", (uid,))
    row = db.fetchone()
    exists = bool(row and int(row["cnt"]) > 0)

    if not exists:
        db.execute(
            """
            INSERT INTO user_profiles (
                user_id, sex, age, height_cm, weight_kg, activity_level, goal,
                dietary_tags_json, excluded_foods, custom_targets_enabled,
                custom_targets_json, llm_provider, api_key, llm_model
            ) VALUES (?, 'H', 29, 179.0, 74.0, 'modere', 'performance', '[]', '', 0, '{}', 'auto', '', 'gemini-2.0-flash')
            """,
            (uid,),
        )
        db.commit()

        db.execute("SELECT COUNT(*) AS cnt FROM meals WHERE user_id = ?", (uid,))
        meals_cnt = int((db.fetchone() or {}).get("cnt", 0))
        if meals_cnt == 0:
            if uid == "default":
                seed_demo_data(db, user_id=uid)
            else:
                db.execute(
                    """
                    INSERT INTO chat_messages (user_id, role, content, actions_summary, created_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        uid,
                        "assistant",
                        f"Bienvenue sur votre espace personnel ({uid}). Ouvrez l'onglet Reglages pour renseigner votre profil et votre cle API gratuite, ou commencez directement a noter vos repas et seances ici.",
                        "Nouvel espace",
                        datetime.now().isoformat(),
                    ),
                )
                db.commit()
    else:
        db.execute("SELECT COUNT(*) AS cnt FROM chat_messages WHERE user_id = ?", (uid,))
        msg_cnt = int((db.fetchone() or {}).get("cnt", 0))
        if msg_cnt == 0:
            db.execute(
                """
                INSERT INTO chat_messages (user_id, role, content, actions_summary, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    uid,
                    "assistant",
                    "Sur vos 7 derniers jours glissants, vos apports en Calcium, Fer et Magnesium sont a l'equilibre, mais vous etes en retrait sur les Glucides, les Omega-3 et les Fibres. Indiquez un repas ou posez une question pour mettre a jour votre suivi.",
                    "Synthese initiale 7j",
                    datetime.now().isoformat(),
                ),
            )
            db.commit()

    if should_close:
        db.close()


def seed_demo_data(conn: Optional[DBWrapper] = None, user_id: str = "default") -> None:
    """Insere un jeu de donnees realiste sur la semaine glissante + seances J-7/J+7 pour l'utilisateur."""
    uid = normalize_user_id(user_id)
    should_close = False
    if conn is None:
        conn = get_connection()
        should_close = True

    conn.execute("DELETE FROM meals WHERE user_id = ?", (uid,))
    conn.execute("DELETE FROM workouts WHERE user_id = ?", (uid,))
    conn.execute("DELETE FROM day_status WHERE user_id = ?", (uid,))
    conn.execute("DELETE FROM chat_messages WHERE user_id = ?", (uid,))

    today = date.today()
    weight_kg = 74.0

    sample_meals = [
        (-5, "petit_dejeuner", "Flocons d'avoine lait et banane", ["cafe_the", "grand_verre_eau"], "normal", 1),
        (-5, "dejeuner", "Poulet curry et riz basmati", ["pain_levain", "fruit_saison", "gourde_eau"], "normal", 1),
        (-5, "diner", "Omelette aux champignons et salade verte", ["pain_levain", "comte_fromage", "grand_verre_eau"], "normal", 0),
        (-4, "petit_dejeuner", "Tartines pain au levain beurre et oeufs brouilles", ["cafe_the", "grand_verre_eau"], "normal", 0),
        (-4, "dejeuner", "Lasagnes a la bolognaise", ["crudites_olive", "yaourt_nature", "gourde_eau"], "copieux", 0),
        (-4, "diner", "Soupe de legumes maison et jambon blanc", ["pain_levain", "fromage_blanc", "grand_verre_eau"], "leger", 0),
        (-2, "petit_dejeuner", "Flocons d'avoine lait et banane", ["cafe_the", "grand_verre_eau"], "normal", 0),
        (-2, "dejeuner", "Poke bowl au saumon avocat et riz", ["fruit_saison", "gourde_eau"], "normal", 1),
        (-2, "diner", "Pates a la carbonara", ["grand_verre_eau", "fruit_saison"], "normal", 0),
        (-1, "petit_dejeuner", "Tartines pain beurre confiture", ["fromage_blanc", "cafe_the", "grand_verre_eau"], "normal", 0),
        (-1, "dejeuner", "Filet de poulet grille, quinoa et brocolis", ["pain_levain", "chocolat_noir", "gourde_eau"], "normal", 0),
        (-1, "diner", "Pizza artisanale mozzarella", ["crudites_olive", "grand_verre_eau"], "normal", 0),
        (0, "petit_dejeuner", "Flocons d'avoine lait et banane", ["cafe_the", "grand_verre_eau"], "normal", 0),
        (0, "dejeuner", "Sandwich poulet crudites", ["fruit_saison", "gourde_eau"], "normal", 0),
    ]

    now_iso = datetime.now().isoformat()
    for day_offset, m_type, dish_txt, periphs, portion, fav in sample_meals:
        m_date = (today + timedelta(days=day_offset)).isoformat()
        dish_eval = evaluate_dish_locally(dish_txt)
        assembled = assemble_meal_evaluation(dish_eval, periphs, portion)

        norm_key = normalize_dish_key(dish_txt)
        conn.execute(
            """
            INSERT INTO dish_cache (normalized_key, display_name, nutrients_json, components_json, eval_source, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT (normalized_key) DO UPDATE SET
                display_name = EXCLUDED.display_name,
                nutrients_json = EXCLUDED.nutrients_json,
                components_json = EXCLUDED.components_json,
                eval_source = EXCLUDED.eval_source,
                updated_at = EXCLUDED.updated_at
            """,
            (
                norm_key,
                dish_txt,
                json.dumps(dish_eval["nutrients"]),
                json.dumps(dish_eval["components"]),
                dish_eval["eval_source"],
                now_iso,
            ),
        )

        conn.execute(
            """
            INSERT INTO meals (
                user_id, meal_date, meal_type, dish_text, peripherals_json, portion_size,
                nutrients_json, components_breakdown_json, analysis_note, eval_source, is_favorite, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                uid,
                m_date,
                m_type,
                dish_txt,
                json.dumps(periphs),
                portion,
                json.dumps(assembled["nutrients"]),
                json.dumps(assembled["components_breakdown"]),
                assembled["analysis_note"],
                assembled["eval_source"],
                fav,
                now_iso,
            ),
        )

    sample_workouts = [
        (-5, "force", "Renforcement Haut du corps", 50, "moderee", "realisee", ""),
        (-3, "endurance", "Footing endurance fondamentale", 45, "douce", "realisee", ""),
        (-1, "hiit_sport_co", "Fractionne VMA sur piste", 55, "intense", "realisee", ""),
        (1, "endurance", "Sortie longue course a pied (Seuil)", 70, "intense", "prevue", ""),
        (3, "force", "Musculation Bas du corps", 60, "moderee", "prevue", ""),
        (5, "velo_natation", "Sortie velo endurance", 90, "moderee", "prevue", ""),
    ]

    for day_offset, cat, title, dur, intensity, status, notes in sample_workouts:
        w_date = (today + timedelta(days=day_offset)).isoformat()
        exp = calculate_workout_expenditure(cat, dur, intensity, weight_kg)
        conn.execute(
            """
            INSERT INTO workouts (
                user_id, workout_date, category, title, duration_min, intensity, status, expenditure_json, notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (uid, w_date, cat, title, dur, intensity, status, json.dumps(exp), notes),
        )

    conn.execute(
        """
        INSERT INTO chat_messages (user_id, role, content, actions_summary, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            uid,
            "assistant",
            "Sur vos 7 derniers jours glissants, vos apports en Calcium, Fer et Magnesium sont bien places, mais vous accusez un leger retard en Glucides, Omega-3 et Fibres avant votre sortie longue de 70 min prevue demain. Ce soir, privilegiez par exemple un pave de saumon aux lentilles ou un dahl de lentilles corail avec du riz basmati et une poignee de noix.",
            "Bilan 7j & Anticipation J+1",
            now_iso,
        ),
    )

    conn.commit()
    if should_close:
        conn.close()


def clear_all_user_entries(user_id: str = "default") -> None:
    uid = normalize_user_id(user_id)
    conn = get_connection()
    conn.execute("DELETE FROM meals WHERE user_id = ?", (uid,))
    conn.execute("DELETE FROM workouts WHERE user_id = ?", (uid,))
    conn.execute("DELETE FROM day_status WHERE user_id = ?", (uid,))
    conn.execute("DELETE FROM chat_messages WHERE user_id = ?", (uid,))
    conn.execute(
        """
        INSERT INTO chat_messages (user_id, role, content, actions_summary, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            uid,
            "assistant",
            "Journal remis a zero. Dites-moi simplement ce que vous avez mange ou vos seances de sport faites et prevues.",
            "Reinitialisation",
            datetime.now().isoformat(),
        ),
    )
    conn.commit()
    conn.close()


def get_profile(user_id: str = "default") -> Dict[str, Any]:
    uid = normalize_user_id(user_id)
    conn = get_connection()
    ensure_user_initialized(uid, conn)
    conn.execute("SELECT * FROM user_profiles WHERE user_id = ?", (uid,))
    row = conn.fetchone()
    conn.close()
    if not row:
        return {}
    return {
        "user_id": uid,
        "sex": row["sex"],
        "age": row["age"],
        "height_cm": row["height_cm"],
        "weight_kg": row["weight_kg"],
        "activity_level": row["activity_level"],
        "goal": row["goal"],
        "dietary_tags": json.loads(row["dietary_tags_json"] or "[]"),
        "excluded_foods": row["excluded_foods"] or "",
        "custom_targets_enabled": bool(row["custom_targets_enabled"]),
        "custom_targets": json.loads(row["custom_targets_json"] or "{}"),
        "llm_provider": row["llm_provider"] or "auto",
        "api_key_configured": bool((row["api_key"] or "").strip()),
        "api_key": row["api_key"] or "",
        "llm_model": row["llm_model"] or "gemini-2.0-flash",
    }


def update_profile(data: Dict[str, Any], user_id: str = "default") -> Dict[str, Any]:
    uid = normalize_user_id(user_id)
    current = get_profile(uid)
    sex = data.get("sex", current.get("sex", "H"))
    age = int(data.get("age", current.get("age", 29)))
    height_cm = float(data.get("height_cm", current.get("height_cm", 179.0)))
    weight_kg = float(data.get("weight_kg", current.get("weight_kg", 74.0)))
    activity_level = data.get("activity_level", current.get("activity_level", "modere"))
    goal = data.get("goal", current.get("goal", "performance"))
    dietary_tags = data.get("dietary_tags", current.get("dietary_tags", []))
    excluded_foods = data.get("excluded_foods", current.get("excluded_foods", ""))
    custom_targets_enabled = 1 if data.get("custom_targets_enabled", current.get("custom_targets_enabled", False)) else 0
    custom_targets = data.get("custom_targets", current.get("custom_targets", {}))
    llm_provider = data.get("llm_provider", current.get("llm_provider", "auto"))
    llm_model = data.get("llm_model", current.get("llm_model", "gemini-2.0-flash"))

    api_key = current.get("api_key", "")
    if "api_key" in data and data["api_key"] is not None:
        incoming_key = str(data["api_key"]).strip()
        if incoming_key != "***":
            api_key = incoming_key

    conn = get_connection()
    conn.execute(
        """
        UPDATE user_profiles SET
            sex = ?, age = ?, height_cm = ?, weight_kg = ?,
            activity_level = ?, goal = ?, dietary_tags_json = ?,
            excluded_foods = ?, custom_targets_enabled = ?, custom_targets_json = ?,
            llm_provider = ?, api_key = ?, llm_model = ?
        WHERE user_id = ?
        """,
        (
            sex, age, height_cm, weight_kg,
            activity_level, goal, json.dumps(dietary_tags),
            excluded_foods, custom_targets_enabled, json.dumps(custom_targets),
            llm_provider, api_key, llm_model, uid,
        ),
    )
    conn.commit()
    conn.close()
    return get_profile(uid)


def get_cached_dish(dish_text: str) -> Optional[Dict[str, Any]]:
    norm_key = normalize_dish_key(dish_text)
    if not norm_key:
        return None
    conn = get_connection()
    conn.execute("SELECT * FROM dish_cache WHERE normalized_key = ?", (norm_key,))
    row = conn.fetchone()
    conn.close()
    if not row:
        return None
    return {
        "normalized_key": row["normalized_key"],
        "display_name": row["display_name"],
        "nutrients": json.loads(row["nutrients_json"]),
        "components": json.loads(row["components_json"]),
        "eval_source": row["eval_source"],
    }


def save_cached_dish(dish_text: str, dish_eval: Dict[str, Any]) -> None:
    norm_key = normalize_dish_key(dish_text)
    if not norm_key:
        return
    conn = get_connection()
    conn.execute(
        """
        INSERT INTO dish_cache (normalized_key, display_name, nutrients_json, components_json, eval_source, updated_at)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT (normalized_key) DO UPDATE SET
            display_name = EXCLUDED.display_name,
            nutrients_json = EXCLUDED.nutrients_json,
            components_json = EXCLUDED.components_json,
            eval_source = EXCLUDED.eval_source,
            updated_at = EXCLUDED.updated_at
        """,
        (
            norm_key,
            dish_text.strip(),
            json.dumps(dish_eval["nutrients"]),
            json.dumps(dish_eval.get("components", [])),
            dish_eval.get("eval_source", "moteur_culinaire"),
            datetime.now().isoformat(),
        ),
    )
    conn.commit()
    conn.close()


def list_meals(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    user_id: str = "default",
) -> List[Dict[str, Any]]:
    uid = normalize_user_id(user_id)
    conn = get_connection()
    query = "SELECT * FROM meals WHERE user_id = ?"
    params: List[Any] = [uid]
    if start_date and end_date:
        query += " AND meal_date >= ? AND meal_date <= ?"
        params.extend([start_date, end_date])
    elif start_date:
        query += " AND meal_date >= ?"
        params.append(start_date)
    query += " ORDER BY meal_date DESC, id DESC"
    conn.execute(query, params)
    rows = conn.fetchall()
    conn.close()

    result = []
    for r in rows:
        result.append({
            "id": r["id"],
            "meal_date": r["meal_date"],
            "meal_type": r["meal_type"],
            "dish_text": r["dish_text"],
            "peripherals": json.loads(r["peripherals_json"] or "[]"),
            "portion_size": r["portion_size"],
            "nutrients": json.loads(r["nutrients_json"] or "{}"),
            "components_breakdown": json.loads(r["components_breakdown_json"] or "[]"),
            "analysis_note": r["analysis_note"],
            "eval_source": r["eval_source"],
            "is_favorite": bool(r["is_favorite"]),
            "created_at": r["created_at"],
        })
    return result


def insert_meal(
    meal_date: str,
    meal_type: str,
    dish_text: str,
    peripherals: List[str],
    portion_size: str,
    assembled: Dict[str, Any],
    is_favorite: bool = False,
    user_id: str = "default",
) -> Dict[str, Any]:
    uid = normalize_user_id(user_id)
    conn = get_connection()
    now_iso = datetime.now().isoformat()
    new_id = conn.execute_insert_id(
        """
        INSERT INTO meals (
            user_id, meal_date, meal_type, dish_text, peripherals_json, portion_size,
            nutrients_json, components_breakdown_json, analysis_note, eval_source, is_favorite, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            uid,
            meal_date,
            meal_type,
            dish_text.strip(),
            json.dumps(peripherals),
            portion_size,
            json.dumps(assembled["nutrients"]),
            json.dumps(assembled["components_breakdown"]),
            assembled["analysis_note"],
            assembled["eval_source"],
            1 if is_favorite else 0,
            now_iso,
        ),
    )
    conn.commit()
    conn.close()
    return {
        "id": new_id,
        "meal_date": meal_date,
        "meal_type": meal_type,
        "dish_text": dish_text.strip(),
        "peripherals": peripherals,
        "portion_size": portion_size,
        "nutrients": assembled["nutrients"],
        "components_breakdown": assembled["components_breakdown"],
        "analysis_note": assembled["analysis_note"],
        "eval_source": assembled["eval_source"],
        "is_favorite": is_favorite,
        "created_at": now_iso,
    }


def update_meal_by_id(
    meal_id: int,
    dish_text: str,
    peripherals: List[str],
    portion_size: str,
    assembled: Dict[str, Any],
    user_id: str = "default",
) -> bool:
    uid = normalize_user_id(user_id)
    conn = get_connection()
    conn.execute(
        """
        UPDATE meals SET
            dish_text = ?,
            peripherals_json = ?,
            portion_size = ?,
            nutrients_json = ?,
            components_breakdown_json = ?,
            analysis_note = ?,
            eval_source = ?
        WHERE id = ? AND user_id = ?
        """,
        (
            dish_text.strip(),
            json.dumps(peripherals),
            portion_size,
            json.dumps(assembled["nutrients"]),
            json.dumps(assembled["components_breakdown"]),
            assembled["analysis_note"],
            assembled["eval_source"],
            meal_id,
            uid,
        ),
    )
    ok = conn.rowcount > 0
    conn.commit()
    conn.close()
    return ok


def delete_meal(meal_id: int, user_id: str = "default") -> bool:
    uid = normalize_user_id(user_id)
    conn = get_connection()
    conn.execute("DELETE FROM meals WHERE id = ? AND user_id = ?", (meal_id, uid))
    deleted = conn.rowcount > 0
    conn.commit()
    conn.close()
    return deleted


def list_workouts(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    user_id: str = "default",
) -> List[Dict[str, Any]]:
    uid = normalize_user_id(user_id)
    conn = get_connection()
    query = "SELECT * FROM workouts WHERE user_id = ?"
    params: List[Any] = [uid]
    if start_date and end_date:
        query += " AND workout_date >= ? AND workout_date <= ?"
        params.extend([start_date, end_date])
    query += " ORDER BY workout_date DESC, id DESC"
    conn.execute(query, params)
    rows = conn.fetchall()
    conn.close()

    return [
        {
            "id": r["id"],
            "workout_date": r["workout_date"],
            "category": r["category"],
            "title": r["title"],
            "duration_min": r["duration_min"],
            "intensity": r["intensity"],
            "status": r["status"],
            "expenditure": json.loads(r["expenditure_json"] or "{}"),
            "notes": r["notes"] or "",
        }
        for r in rows
    ]


def insert_workout(
    workout_date: str,
    category: str,
    title: str,
    duration_min: int,
    intensity: str,
    status: str,
    expenditure: Dict[str, float],
    notes: str = "",
    user_id: str = "default",
) -> Dict[str, Any]:
    uid = normalize_user_id(user_id)
    conn = get_connection()
    new_id = conn.execute_insert_id(
        """
        INSERT INTO workouts (
            user_id, workout_date, category, title, duration_min, intensity, status, expenditure_json, notes
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (uid, workout_date, category, title.strip(), duration_min, intensity, status, json.dumps(expenditure), notes.strip()),
    )
    conn.commit()
    conn.close()
    return {
        "id": new_id,
        "workout_date": workout_date,
        "category": category,
        "title": title.strip(),
        "duration_min": duration_min,
        "intensity": intensity,
        "status": status,
        "expenditure": expenditure,
        "notes": notes.strip(),
    }


def update_workout_status(workout_id: int, new_status: str, user_id: str = "default") -> bool:
    uid = normalize_user_id(user_id)
    conn = get_connection()
    conn.execute("UPDATE workouts SET status = ? WHERE id = ? AND user_id = ?", (new_status, workout_id, uid))
    ok = conn.rowcount > 0
    conn.commit()
    conn.close()
    return ok


def delete_workout(workout_id: int, user_id: str = "default") -> bool:
    uid = normalize_user_id(user_id)
    conn = get_connection()
    conn.execute("DELETE FROM workouts WHERE id = ? AND user_id = ?", (workout_id, uid))
    ok = conn.rowcount > 0
    conn.commit()
    conn.close()
    return ok


def get_day_statuses(user_id: str = "default") -> Dict[str, bool]:
    uid = normalize_user_id(user_id)
    conn = get_connection()
    conn.execute("SELECT day_date, marked_complete FROM day_status WHERE user_id = ?", (uid,))
    rows = conn.fetchall()
    conn.close()
    return {r["day_date"]: bool(r["marked_complete"]) for r in rows}


def set_day_complete_status(day_date: str, marked_complete: bool, user_id: str = "default") -> None:
    uid = normalize_user_id(user_id)
    conn = get_connection()
    conn.execute(
        """
        INSERT INTO day_status (user_id, day_date, marked_complete)
        VALUES (?, ?, ?)
        ON CONFLICT (user_id, day_date) DO UPDATE SET
            marked_complete = EXCLUDED.marked_complete
        """,
        (uid, day_date, 1 if marked_complete else 0),
    )
    conn.commit()
    conn.close()


def list_chat_messages(limit: int = 20, user_id: str = "default") -> List[Dict[str, Any]]:
    uid = normalize_user_id(user_id)
    conn = get_connection()
    conn.execute(
        "SELECT * FROM chat_messages WHERE user_id = ? ORDER BY id DESC LIMIT ?",
        (uid, limit),
    )
    rows = conn.fetchall()
    conn.close()
    out = [
        {
            "id": r["id"],
            "role": r["role"],
            "content": r["content"],
            "actions_summary": r["actions_summary"],
            "created_at": r["created_at"],
        }
        for r in rows
    ]
    out.reverse()
    return out


def insert_chat_message(
    role: str,
    content: str,
    actions_summary: str = "",
    user_id: str = "default",
) -> Dict[str, Any]:
    uid = normalize_user_id(user_id)
    conn = get_connection()
    now_iso = datetime.now().isoformat()
    new_id = conn.execute_insert_id(
        """
        INSERT INTO chat_messages (user_id, role, content, actions_summary, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (uid, role, content.strip(), actions_summary.strip(), now_iso),
    )
    conn.commit()
    conn.close()
    return {
        "id": new_id,
        "role": role,
        "content": content.strip(),
        "actions_summary": actions_summary.strip(),
        "created_at": now_iso,
    }
