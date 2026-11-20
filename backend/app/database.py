"""SQLite storage (stdlib sqlite3, no ORM — keeps the image small).

Tables:
- devices / wishes / letters / checkins: app data (unchanged).
- settings: key-value store for ALL admin-editable config — LLM/TTS API keys,
  provider models, membership, daily-sentence generation settings, admin
  password hash. No API key lives in env vars anymore; the admin console
  (/admin) edits these.
- admin_sessions: admin login sessions (random token, HttpOnly cookie).
- admin_messages / admin_activities: content the admin manages in the
  console; the public /messages and /activities endpoints read from these
  tables (seeded from the JSON files on first init).
- memories: per-device facts the AI remembers (profile / preference /
  milestone / progress / note), used to build LLM context.
- daily_messages: one AI-generated personalized daily sentence per device
  per day (dedup + continuity); the public /daily-sentence endpoint reads
  from here. The built-in generic sentences live in code (catalog.py) as
  fallback only — never admin-managed.
"""
import json
import secrets
import sqlite3
from datetime import date
from pathlib import Path

from .config import settings
from .crypto import decrypt_or_keep, encrypt_text, is_encrypted

SCHEMA = """
CREATE TABLE IF NOT EXISTS devices (
    device_id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS wishes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id TEXT NOT NULL,
    text TEXT NOT NULL,
    category TEXT NOT NULL,
    days INTEGER NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS letters (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id TEXT NOT NULL,
    wish_id INTEGER NOT NULL,
    voice_id TEXT,
    text TEXT NOT NULL,
    target_date TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS checkins (
    device_id TEXT NOT NULL,
    checkin_date TEXT NOT NULL,
    PRIMARY KEY (device_id, checkin_date)
);
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS admin_sessions (
    token TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS admin_messages (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    audience TEXT NOT NULL DEFAULT 'all',
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS admin_activities (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    image_url TEXT,
    start_at TEXT,
    end_at TEXT,
    active INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS memories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    text TEXT NOT NULL,
    -- 0.0-1.0 float: how alive this memory is. Recalled memories gain
    -- importance; long-unrecalled ones decay (see evolution.py).
    importance REAL NOT NULL DEFAULT 0.5,
    emotion TEXT,
    recall_count INTEGER NOT NULL DEFAULT 0,
    last_recalled_at TEXT,
    faded INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
-- The "future self" persona, one row per device. `summary` is user
-- content (encrypted like memories.text); `traits` is a JSON object of
-- 0.0-1.0 numbers (warmth, pride, ...); `interaction_count` drives the
-- relationship stage (see evolution.py STAGE_THRESHOLDS).
CREATE TABLE IF NOT EXISTS persona (
    device_id TEXT PRIMARY KEY,
    relationship_stage TEXT NOT NULL DEFAULT '初识',
    summary TEXT NOT NULL DEFAULT '',
    traits TEXT NOT NULL DEFAULT '{"warmth": 0.5, "pride": 0.5}',
    interaction_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
-- Last consolidation run per device (evolution.py runs at most once a day).
CREATE TABLE IF NOT EXISTS consolidation_runs (
    device_id TEXT PRIMARY KEY,
    last_run_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS daily_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id TEXT NOT NULL,
    wish_id INTEGER,
    date TEXT NOT NULL,
    text TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (device_id, date)
);
-- Violation stats: TYPE + COUNT per day only. Never the offending text,
-- never the device/user it came from (privacy red line).
CREATE TABLE IF NOT EXISTS violation_stats (
    date TEXT NOT NULL,
    type TEXT NOT NULL,
    count INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (date, type)
);
"""

# Default values for every setting key. Secrets default to "" (unconfigured).
# Shared keys: DashScope serves both 千问 LLM and Qwen3-TTS; Zhipu serves
# both GLM LLM and GLM-TTS — one key each, exactly like the old env vars.
DEFAULT_SETTINGS: dict[str, str] = {
    "llm.default_provider": "qwen",
    "llm.qwen.model": "qwen-plus",
    "llm.qwen.enabled": "1",
    "llm.hunyuan.model": "hunyuan-turbos-latest",
    "llm.hunyuan.enabled": "1",
    "llm.siliconflow.model": "Qwen/Qwen3-8B",
    "llm.siliconflow.enabled": "1",
    "llm.zhipu.model": "glm-4-flash",
    "llm.zhipu.enabled": "1",
    "llm.generic.base_url": "",
    "llm.generic.model": "",
    "llm.generic.enabled": "1",
    "dashscope.api_key": "",
    "hunyuan.api_key": "",
    "siliconflow.api_key": "",
    "zhipu.api_key": "",
    "generic.api_key": "",
    "tencent.secret_id": "",
    "tencent.secret_key": "",
    "tencent.region": "ap-guangzhou",
    "tts.default_provider": "qwen",
    "membership.trial_days": "7",
    "membership.price_monthly_cny": "9.9",
    "membership.paywalled": "0",
    "daily.enabled": "1",
    "daily.max_chars": "60",
    "daily.fallback_mode": "generic",
    "daily.prompt_template": (
        "你是一位来自未来的“我”。请根据用户的目标和近况，写一句来自“目标实现后的自己”的鼓励话。"
        "要求：第一人称，温暖具体，和目标相关，{max_chars}字以内，不要玄学、不要承诺任何结果、"
        "不要出现“AI生成”等字样，只写那句话本身。\n\n"
        "用户背景：\n{context}\n\n"
        "请以你现在的身份——背景里介绍的那个未来的自己——和你对用户的了解说话，"
        "可以自然地提到你们之间的默契和共同经历，就像老朋友在说话。"
    ),
    # Memory evolution (see evolution.py). All three are admin-editable.
    "memory.evolution_enabled": "1",
    "memory.reflection_enabled": "1",
    "memory.consolidation_interval_days": "1",
    "admin.password_hash": "",
}

# Keys whose values are secrets: never returned in clear text by the admin API.
SECRET_SETTINGS = {
    "dashscope.api_key",
    "hunyuan.api_key",
    "siliconflow.api_key",
    "zhipu.api_key",
    "generic.api_key",
    "tencent.secret_id",
    "tencent.secret_key",
}

# Keys that must never leave the server at all (not even masked).
HIDDEN_SETTINGS = {"admin.password_hash", "auth.jwt_secret"}

SETTING_MASK = "********"


def connect() -> sqlite3.Connection:
    settings.DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(settings.DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db() -> None:
    with connect() as conn:
        conn.executescript(SCHEMA)
    _migrate_memory_columns()
    _migrate_importance_scale()
    _migrate_encryption()
    _seed_content()


def _migrate_memory_columns() -> None:
    """Add the evolution columns to `memories` on databases created before
    them (CREATE TABLE IF NOT EXISTS never alters an existing table)."""
    new_cols = {
        "emotion": "TEXT",
        "recall_count": "INTEGER NOT NULL DEFAULT 0",
        "last_recalled_at": "TEXT",
        "faded": "INTEGER NOT NULL DEFAULT 0",
    }
    with connect() as conn:
        existing = {r["name"] for r in conn.execute("PRAGMA table_info(memories)")}
        for name, ddl in new_cols.items():
            if name not in existing:
                conn.execute(f"ALTER TABLE memories ADD COLUMN {name} {ddl}")


def _migrate_importance_scale() -> None:
    """v1 stored importance as small ints (1 default, 2 progress, 3 wish).
    The evolution system uses a 0.0-1.0 float scale: map legacy ints once
    (3 -> 0.9, 2 -> 0.7, 1 -> 0.5). Only rows stored as INTEGER are
    touched — a REAL 1.0 (a memory recalled up to the cap) is already on
    the new scale and must not be demoted. Idempotent."""
    with connect() as conn:
        rows = conn.execute(
            "SELECT id, importance FROM memories"
            " WHERE typeof(importance) = 'integer' AND importance >= 1"
        ).fetchall()
        for r in rows:
            v = r["importance"]
            new = 0.9 if v >= 3 else (0.7 if v == 2 else 0.5)
            conn.execute(
                "UPDATE memories SET importance = ? WHERE id = ?", (new, r["id"])
            )


def _migrate_encryption() -> None:
    """Startup migration: encrypt any legacy plaintext rows in the user
    content tables. A row is treated as already encrypted when it decrypts
    cleanly with the current key; otherwise it is plaintext and gets
    encrypted in place. Idempotent — encrypted rows are skipped."""
    specs = [
        ("wishes", "id", "text"),
        ("letters", "id", "text"),
        ("daily_messages", "id", "text"),
        ("memories", "id", "text"),
        ("persona", "device_id", "summary"),
    ]
    with connect() as conn:
        for table, id_col, text_col in specs:
            rows = conn.execute(
                f"SELECT {id_col}, {text_col} FROM {table}"
            ).fetchall()
            for r in rows:
                val = r[text_col]
                if val and not is_encrypted(val):
                    conn.execute(
                        f"UPDATE {table} SET {text_col} = ? WHERE {id_col} = ?",
                        (encrypt_text(val), r[id_col]),
                    )


def _decrypt_row(row: dict | None, field: str = "text") -> dict | None:
    """Decrypt one text field of a fetched row (in memory only)."""
    if row is not None and row.get(field):
        row[field] = decrypt_or_keep(row[field])
    return row


def _decrypt_rows(rows: list[dict], field: str = "text") -> list[dict]:
    return [_decrypt_row(dict(r), field) for r in rows]


def _today() -> str:
    return date.today().isoformat()


# ---- settings (key-value store) ----

def get_setting(key: str, default: str = "") -> str:
    """Read one setting; falls back to DEFAULT_SETTINGS, then `default`."""
    with connect() as conn:
        row = conn.execute(
            "SELECT value FROM settings WHERE key = ?", (key,)
        ).fetchone()
    if row is not None:
        return row["value"]
    return DEFAULT_SETTINGS.get(key, default)


def get_all_settings() -> dict[str, str]:
    """All settings with defaults applied (including hidden ones — the caller
    decides what may leave the server)."""
    out = dict(DEFAULT_SETTINGS)
    with connect() as conn:
        rows = conn.execute("SELECT key, value FROM settings").fetchall()
    for r in rows:
        out[r["key"]] = r["value"]
    return out


def set_setting(key: str, value: str) -> None:
    with connect() as conn:
        conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?)"
            " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )


def set_settings(values: dict[str, str]) -> None:
    with connect() as conn:
        conn.executemany(
            "INSERT INTO settings (key, value) VALUES (?, ?)"
            " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            [(k, v) for k, v in values.items()],
        )


def get_or_create_jwt_secret() -> str:
    """Device-token signing secret. Auto-generated once and stored in the DB
    (no env var needed); a JWT_SECRET env var, when set, overrides it for
    backwards compatibility with existing deployments."""
    import os

    env_secret = os.environ.get("JWT_SECRET", "")
    if env_secret:
        return env_secret
    secret = get_setting("auth.jwt_secret", "")
    if not secret:
        secret = secrets.token_hex(32)
        set_setting("auth.jwt_secret", secret)
    return secret


# ---- admin sessions ----

SESSION_TTL_SECONDS = 7 * 24 * 3600


def create_admin_session() -> tuple[str, int]:
    """Create a session; returns (token, max_age_seconds)."""
    from datetime import datetime, timedelta, timezone

    token = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc)
    expires = now + timedelta(seconds=SESSION_TTL_SECONDS)
    with connect() as conn:
        conn.execute(
            "INSERT INTO admin_sessions (token, created_at, expires_at)"
            " VALUES (?, ?, ?)",
            (token, now.isoformat(), expires.isoformat()),
        )
    return token, SESSION_TTL_SECONDS


def admin_session_valid(token: str) -> bool:
    from datetime import datetime, timezone

    with connect() as conn:
        row = conn.execute(
            "SELECT expires_at FROM admin_sessions WHERE token = ?", (token,)
        ).fetchone()
    if not row:
        return False
    try:
        expires = datetime.fromisoformat(row["expires_at"])
    except ValueError:
        return False
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) < expires


def delete_admin_session(token: str) -> None:
    with connect() as conn:
        conn.execute("DELETE FROM admin_sessions WHERE token = ?", (token,))


# ---- content tables (messages / activities / sentences) ----

def _seed_content() -> None:
    """First-run seed from the JSON files. Only fills a table when it is
    completely empty, so admin edits are never clobbered."""
    with connect() as conn:
        msg_count = conn.execute("SELECT COUNT(*) FROM admin_messages").fetchone()[0]
        act_count = conn.execute("SELECT COUNT(*) FROM admin_activities").fetchone()[0]
        if msg_count == 0:
            for m in _load_seed_json("messages.json"):
                conn.execute(
                    "INSERT OR IGNORE INTO admin_messages"
                    " (id, title, body, audience, active, created_at)"
                    " VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        str(m.get("id", "")),
                        m.get("title", ""),
                        m.get("body", ""),
                        m.get("audience", "all"),
                        1 if m.get("active", True) else 0,
                        m.get("created_at", _today()),
                    ),
                )
        if act_count == 0:
            for a in _load_seed_json("activities.json"):
                conn.execute(
                    "INSERT OR IGNORE INTO admin_activities"
                    " (id, title, body, image_url, start_at, end_at, active)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        str(a.get("id", "")),
                        a.get("title", ""),
                        a.get("body", ""),
                        a.get("image_url"),
                        a.get("start_at"),
                        a.get("end_at"),
                        1 if a.get("active", True) else 0,
                    ),
                )


def _load_seed_json(name: str) -> list[dict]:
    path = settings.DATA_DIR / name
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (ValueError, OSError):
        return []


def list_messages(include_inactive: bool = False) -> list[dict]:
    with connect() as conn:
        q = "SELECT id, title, body, audience, active, created_at FROM admin_messages"
        if not include_inactive:
            q += " WHERE active = 1"
        q += " ORDER BY created_at DESC, id DESC"
        return [dict(r) for r in conn.execute(q).fetchall()]


def create_message(title: str, body: str, audience: str = "all") -> dict:
    msg_id = f"msg-{secrets.token_hex(4)}"
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).isoformat()
    with connect() as conn:
        conn.execute(
            "INSERT INTO admin_messages (id, title, body, audience, active, created_at)"
            " VALUES (?, ?, ?, ?, 1, ?)",
            (msg_id, title, body, audience, now),
        )
    return get_message(msg_id)


def get_message(msg_id: str) -> dict | None:
    with connect() as conn:
        row = conn.execute(
            "SELECT id, title, body, audience, active, created_at FROM admin_messages"
            " WHERE id = ?",
            (msg_id,),
        ).fetchone()
    return dict(row) if row else None


def update_message(msg_id: str, fields: dict) -> dict | None:
    allowed = {"title", "body", "audience", "active"}
    sets = {k: v for k, v in fields.items() if k in allowed}
    if not sets:
        return get_message(msg_id)
    sql = "UPDATE admin_messages SET " + ", ".join(f"{k} = ?" for k in sets) + " WHERE id = ?"
    with connect() as conn:
        conn.execute(sql, (*sets.values(), msg_id))
    return get_message(msg_id)


def delete_message(msg_id: str) -> bool:
    with connect() as conn:
        cur = conn.execute("DELETE FROM admin_messages WHERE id = ?", (msg_id,))
        return cur.rowcount > 0


def list_activities(include_inactive: bool = False) -> list[dict]:
    with connect() as conn:
        q = "SELECT id, title, body, image_url, start_at, end_at, active FROM admin_activities"
        if not include_inactive:
            q += " WHERE active = 1"
        q += " ORDER BY id"
        return [dict(r) for r in conn.execute(q).fetchall()]


def create_activity(fields: dict) -> dict:
    act_id = fields.get("id") or f"act-{secrets.token_hex(4)}"
    with connect() as conn:
        conn.execute(
            "INSERT INTO admin_activities (id, title, body, image_url, start_at, end_at, active)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                act_id,
                fields.get("title", ""),
                fields.get("body", ""),
                fields.get("image_url"),
                fields.get("start_at"),
                fields.get("end_at"),
                1 if fields.get("active", True) else 0,
            ),
        )
    return get_activity(act_id)


def get_activity(act_id: str) -> dict | None:
    with connect() as conn:
        row = conn.execute(
            "SELECT id, title, body, image_url, start_at, end_at, active FROM admin_activities"
            " WHERE id = ?",
            (act_id,),
        ).fetchone()
    return dict(row) if row else None


def update_activity(act_id: str, fields: dict) -> dict | None:
    allowed = {"title", "body", "image_url", "start_at", "end_at", "active"}
    sets = {k: v for k, v in fields.items() if k in allowed}
    if not sets:
        return get_activity(act_id)
    sql = "UPDATE admin_activities SET " + ", ".join(f"{k} = ?" for k in sets) + " WHERE id = ?"
    with connect() as conn:
        conn.execute(sql, (*sets.values(), act_id))
    return get_activity(act_id)


def delete_activity(act_id: str) -> bool:
    with connect() as conn:
        cur = conn.execute("DELETE FROM admin_activities WHERE id = ?", (act_id,))
        return cur.rowcount > 0


# ---- memories ----

# emotion: a hard day pushed through, a proud moment, ... (free-form label,
# usually one of 开心/低落/坚定/焦虑/自豪). insight: a pattern the future
# self formed about the user during consolidation (at most one per run).
MEMORY_KINDS = {
    "profile", "preference", "milestone", "progress", "note",
    "emotion", "insight",
}

MEMORY_COLUMNS = (
    "id, device_id, kind, text, importance, emotion, recall_count,"
    " last_recalled_at, faded, created_at, updated_at"
)


def normalize_importance(value) -> float:
    """Clamp to the 0.0-1.0 float scale. Legacy v1 callers pass ints
    (3 -> 0.9, 2 -> 0.7, 1 -> 0.5); new callers pass floats, clamped."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return 0.5
    if isinstance(value, int) and not isinstance(value, bool):
        return 0.9 if v >= 3 else (0.7 if v == 2 else 0.5)
    return max(0.1, min(1.0, v))


def list_memories(device_id: str, include_faded: bool = False) -> list[dict]:
    """Live memories, most important first. Faded memories are excluded
    by default — they are kept in the DB (never hard-deleted) but no
    longer enter the LLM context."""
    q = (
        f"SELECT {MEMORY_COLUMNS} FROM memories WHERE device_id = ?"
    )
    if not include_faded:
        q += " AND faded = 0"
    q += " ORDER BY importance DESC, created_at DESC"
    with connect() as conn:
        rows = conn.execute(q, (device_id,)).fetchall()
    return _decrypt_rows([dict(r) for r in rows])


def create_memory(
    device_id: str, kind: str, text: str, importance: float = 0.5,
    emotion: str | None = None,
) -> dict:
    if kind not in MEMORY_KINDS:
        raise ValueError(f"unknown memory kind: {kind}")
    now = _now_iso()
    with connect() as conn:
        cur = conn.execute(
            "INSERT INTO memories"
            " (device_id, kind, text, importance, emotion, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                device_id, kind, encrypt_text(text),
                normalize_importance(importance), emotion, now, now,
            ),
        )
        row_id = cur.lastrowid
    return get_memory(row_id)


def get_memory(row_id: int) -> dict | None:
    with connect() as conn:
        row = conn.execute(
            f"SELECT {MEMORY_COLUMNS} FROM memories WHERE id = ?",
            (row_id,),
        ).fetchone()
    return _decrypt_row(dict(row)) if row else None


def update_memory(row_id: int, fields: dict) -> dict | None:
    allowed = {"kind", "text", "importance", "emotion", "recall_count",
               "last_recalled_at", "faded"}
    sets = {k: v for k, v in fields.items() if k in allowed}
    if "kind" in sets and sets["kind"] not in MEMORY_KINDS:
        raise ValueError(f"unknown memory kind: {sets['kind']}")
    if not sets:
        return get_memory(row_id)
    if "text" in sets:
        sets["text"] = encrypt_text(sets["text"])
    if "importance" in sets:
        sets["importance"] = normalize_importance(sets["importance"])
    sets["updated_at"] = _now_iso()
    sql = "UPDATE memories SET " + ", ".join(f"{k} = ?" for k in sets) + " WHERE id = ?"
    with connect() as conn:
        conn.execute(sql, (*sets.values(), row_id))
    return get_memory(row_id)


def touch_memories(device_id: str, memory_ids: list[int]) -> None:
    """Recall bookkeeping (evolution.py): a memory used in an assembled
    context gains recall_count + 1, a fresh last_recalled_at and a small
    importance bump (capped at 1.0). No-op for an empty list."""
    if not memory_ids:
        return
    now = _now_iso()
    with connect() as conn:
        for mid in memory_ids:
            conn.execute(
                "UPDATE memories SET recall_count = recall_count + 1,"
                " last_recalled_at = ?,"
                " importance = MIN(1.0, importance + 0.05),"
                " updated_at = ? WHERE id = ? AND device_id = ?",
                (now, now, mid, device_id),
            )


def delete_memory(row_id: int) -> bool:
    with connect() as conn:
        cur = conn.execute("DELETE FROM memories WHERE id = ?", (row_id,))
        return cur.rowcount > 0


def _memory_exists(device_id: str, kind: str, text: str) -> bool:
    with connect() as conn:
        row = conn.execute(
            "SELECT 1 FROM memories WHERE device_id = ? AND kind = ? AND text = ?",
            (device_id, kind, text),
        ).fetchone()
    return row is not None


# ---- persona (the "future self" per device) ----

DEFAULT_TRAITS: dict[str, float] = {"warmth": 0.5, "pride": 0.5}


def _decode_persona(row: dict) -> dict:
    """Decrypt the summary (user content) and parse traits JSON."""
    row["summary"] = decrypt_or_keep(row.get("summary") or "")
    try:
        traits = json.loads(row.get("traits") or "{}")
        if not isinstance(traits, dict):
            traits = {}
    except ValueError:
        traits = {}
    merged = dict(DEFAULT_TRAITS)
    for k, v in traits.items():
        try:
            merged[k] = max(0.0, min(1.0, float(v)))
        except (TypeError, ValueError):
            continue
    row["traits"] = merged
    return row


def get_persona(device_id: str) -> dict:
    """Fetch the persona, creating a fresh one (stage 初识） on first use."""
    now = _now_iso()
    with connect() as conn:
        row = conn.execute(
            "SELECT device_id, relationship_stage, summary, traits,"
            " interaction_count, created_at, updated_at"
            " FROM persona WHERE device_id = ?",
            (device_id,),
        ).fetchone()
        if row is None:
            conn.execute(
                "INSERT INTO persona (device_id, relationship_stage, summary,"
                " traits, interaction_count, created_at, updated_at)"
                " VALUES (?, '初识', '', ?, 0, ?, ?)",
                (device_id, json.dumps(DEFAULT_TRAITS, ensure_ascii=False), now, now),
            )
            row = conn.execute(
                "SELECT device_id, relationship_stage, summary, traits,"
                " interaction_count, created_at, updated_at"
                " FROM persona WHERE device_id = ?",
                (device_id,),
            ).fetchone()
    return _decode_persona(dict(row))


def update_persona(device_id: str, fields: dict) -> dict:
    """Update persona fields. `summary` is encrypted before storage;
    `traits` is a dict of 0.0-1.0 numbers stored as JSON."""
    get_persona(device_id)  # ensure the row exists
    allowed = {"relationship_stage", "summary", "traits", "interaction_count"}
    sets = {k: v for k, v in fields.items() if k in allowed}
    if not sets:
        return get_persona(device_id)
    if "summary" in sets:
        sets["summary"] = encrypt_text(sets["summary"] or "")
    if "traits" in sets:
        traits = dict(DEFAULT_TRAITS)
        traits.update(sets["traits"] or {})
        sets["traits"] = json.dumps(
            {k: max(0.0, min(1.0, float(v))) for k, v in traits.items()},
            ensure_ascii=False,
        )
    sets["updated_at"] = _now_iso()
    sql = "UPDATE persona SET " + ", ".join(f"{k} = ?" for k in sets) + " WHERE device_id = ?"
    with connect() as conn:
        conn.execute(sql, (*sets.values(), device_id))
    return get_persona(device_id)


# ---- consolidation runs (at most once per device per interval) ----

def get_consolidation_last_run(device_id: str) -> str | None:
    """Last consolidation time ('YYYY-MM-DD HH:MM:SS' UTC) or None."""
    with connect() as conn:
        row = conn.execute(
            "SELECT last_run_at FROM consolidation_runs WHERE device_id = ?",
            (device_id,),
        ).fetchone()
    return row["last_run_at"] if row else None


def set_consolidation_last_run(device_id: str, when: str) -> None:
    with connect() as conn:
        conn.execute(
            "INSERT INTO consolidation_runs (device_id, last_run_at) VALUES (?, ?)"
            " ON CONFLICT(device_id) DO UPDATE SET last_run_at = excluded.last_run_at",
            (device_id, when),
        )


def events_since(device_id: str, since: str | None) -> dict:
    """Raw recent events for consolidation (decrypted in memory only):
    wishes, letters (first 60 chars), daily sentences and check-in count
    since `since` ('YYYY-MM-DD HH:MM:SS' UTC, None = everything).
    Used to build the consolidation prompt — never returned by any API."""
    since = since or "0000-00-00 00:00:00"
    with connect() as conn:
        wishes = [
            dict(r) for r in conn.execute(
                "SELECT id, text, category, days, created_at FROM wishes"
                " WHERE device_id = ? AND created_at >= ? ORDER BY id",
                (device_id, since),
            ).fetchall()
        ]
        letters = [
            dict(r) for r in conn.execute(
                "SELECT id, wish_id, text, created_at FROM letters"
                " WHERE device_id = ? AND created_at >= ? ORDER BY id",
                (device_id, since),
            ).fetchall()
        ]
        daily = [
            dict(r) for r in conn.execute(
                "SELECT id, wish_id, date, text, created_at FROM daily_messages"
                " WHERE device_id = ? AND created_at >= ? ORDER BY date",
                (device_id, since),
            ).fetchall()
        ]
        checkins = conn.execute(
            "SELECT COUNT(*) FROM checkins WHERE device_id = ? AND checkin_date >= ?",
            (device_id, since[:10]),
        ).fetchone()[0]
    letters = _decrypt_rows(letters)
    for r in letters:
        r["text"] = (r["text"] or "")[:60]
    return {
        "wishes": _decrypt_rows(wishes),
        "letters": letters,
        "daily": _decrypt_rows(daily),
        "checkins": checkins,
    }


# ---- daily messages (personalized, one per device per day) ----

def get_daily_message(device_id: str, day: str) -> dict | None:
    with connect() as conn:
        row = conn.execute(
            "SELECT id, device_id, wish_id, date, text, created_at FROM daily_messages"
            " WHERE device_id = ? AND date = ?",
            (device_id, day),
        ).fetchone()
    return _decrypt_row(dict(row)) if row else None


def create_daily_message(device_id: str, wish_id: int | None, day: str, text: str) -> dict:
    with connect() as conn:
        cur = conn.execute(
            "INSERT INTO daily_messages (device_id, wish_id, date, text, created_at)"
            " VALUES (?, ?, ?, ?, datetime('now'))",
            (device_id, wish_id, day, encrypt_text(text)),
        )
        row_id = cur.lastrowid
    return get_daily_message_by_id(row_id)


def get_daily_message_by_id(row_id: int) -> dict | None:
    with connect() as conn:
        row = conn.execute(
            "SELECT id, device_id, wish_id, date, text, created_at FROM daily_messages"
            " WHERE id = ?",
            (row_id,),
        ).fetchone()
    return _decrypt_row(dict(row)) if row else None


def list_daily_messages(device_id: str, limit: int = 30) -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT id, device_id, wish_id, date, text, created_at FROM daily_messages"
            " WHERE device_id = ? ORDER BY date DESC LIMIT ?",
            (device_id, limit),
        ).fetchall()
    return _decrypt_rows([dict(r) for r in rows])


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


# ---- dashboard: AGGREGATES ONLY (privacy red line) ----
# The admin console must never see any single user's content: no wish text,
# no letter text, no memory text, no daily-sentence text, no device list.
# Only counts and per-category / per-type distributions.

def record_violation(vtype: str, day: str | None = None) -> None:
    """Count one violation of a given type for a day. No text, no device."""
    day = day or _today()
    with connect() as conn:
        conn.execute(
            "INSERT INTO violation_stats (date, type, count) VALUES (?, ?, 1)"
            " ON CONFLICT(date, type) DO UPDATE SET count = count + 1",
            (day, vtype),
        )


def violation_summary(days: int = 30) -> list[dict]:
    """[{type, count}] summed over the last `days` days, most first."""
    from datetime import timedelta

    since = (date.today() - timedelta(days=days - 1)).isoformat()
    with connect() as conn:
        rows = conn.execute(
            "SELECT type, SUM(count) AS count FROM violation_stats"
            " WHERE date >= ? GROUP BY type ORDER BY count DESC",
            (since,),
        ).fetchall()
    return [{"type": r["type"], "count": r["count"]} for r in rows]


def topic_distribution() -> list[dict]:
    """Per wish category: how many wishes and how many distinct devices.
    Category only — no original text is ever read for this."""
    with connect() as conn:
        rows = conn.execute(
            "SELECT category, COUNT(*) AS wishes,"
            " COUNT(DISTINCT device_id) AS devices FROM wishes"
            " GROUP BY category ORDER BY wishes DESC"
        ).fetchall()
    return [dict(r) for r in rows]


def dashboard_stats() -> dict:
    """Aggregate numbers only: totals, today's active devices (deduped),
    topic distribution, violation-type counts. No user content anywhere."""
    today = _today()
    with connect() as conn:
        devices = conn.execute("SELECT COUNT(*) FROM devices").fetchone()[0]
        wishes = conn.execute("SELECT COUNT(*) FROM wishes").fetchone()[0]
        letters = conn.execute("SELECT COUNT(*) FROM letters").fetchone()[0]
        checkins = conn.execute("SELECT COUNT(*) FROM checkins").fetchone()[0]
        dau = conn.execute(
            "SELECT COUNT(DISTINCT device_id) FROM ("
            " SELECT device_id FROM checkins WHERE checkin_date = ?"
            " UNION SELECT device_id FROM wishes WHERE substr(created_at, 1, 10) = ?"
            " UNION SELECT device_id FROM letters WHERE substr(created_at, 1, 10) = ?"
            ")",
            (today, today, today),
        ).fetchone()[0]
    return {
        "devices": devices,
        "wishes": wishes,
        "letters": letters,
        "checkins": checkins,
        "dau_today": dau,
        "topics": topic_distribution(),
        "violations": violation_summary(),
    }


# ---- devices ----

def device_exists(device_id: str) -> bool:
    with connect() as conn:
        row = conn.execute(
            "SELECT 1 FROM devices WHERE device_id = ?", (device_id,)
        ).fetchone()
        return row is not None


def get_or_create_device(device_id: str) -> dict:
    with connect() as conn:
        row = conn.execute(
            "SELECT device_id, created_at FROM devices WHERE device_id = ?",
            (device_id,),
        ).fetchone()
        if row:
            return dict(row)
        now = _today()
        conn.execute(
            "INSERT INTO devices (device_id, created_at) VALUES (?, ?)",
            (device_id, now),
        )
        return {"device_id": device_id, "created_at": now}


# ---- wishes ----

def create_wish(device_id: str, text: str, category: str, days: int) -> dict:
    # User content is encrypted before it reaches SQLite (see crypto.py).
    with connect() as conn:
        cur = conn.execute(
            "INSERT INTO wishes (device_id, text, category, days, created_at)"
            " VALUES (?, ?, ?, ?, datetime('now'))",
            (device_id, encrypt_text(text), category, days),
        )
        wish_id = cur.lastrowid
    # read back on a fresh connection (the insert is committed above)
    wish = get_wish(device_id, wish_id)
    # v1 memory source: the wish itself is a milestone memory (content +
    # target date) so later AI messages stay tied to the user's goal.
    from datetime import timedelta

    target = (date.today() + timedelta(days=days)).isoformat()
    mem_text = f"愿望：{text}（{category}），目标 {days} 天，目标日 {target}"
    if not _memory_exists(device_id, "milestone", mem_text):
        create_memory(device_id, "milestone", mem_text, importance=0.9)
    # Compliance counting only: record violation TYPE counts, never the
    # text and never the device. The wish itself is still accepted.
    from .content_filter import classify_violation

    for vtype in classify_violation(text):
        record_violation(vtype)
    return wish


def list_wishes(device_id: str) -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT id, device_id, text, category, days, created_at FROM wishes"
            " WHERE device_id = ? ORDER BY id DESC",
            (device_id,),
        ).fetchall()
        return _decrypt_rows([dict(r) for r in rows])


def get_wish(device_id: str, wish_id: int) -> dict | None:
    with connect() as conn:
        row = conn.execute(
            "SELECT id, device_id, text, category, days, created_at FROM wishes"
            " WHERE device_id = ? AND id = ?",
            (device_id, wish_id),
        ).fetchone()
        return _decrypt_row(dict(row)) if row else None


# ---- letters ----

def create_letter(
    device_id: str, wish_id: int, voice_id: str | None, text: str, target_date: str
) -> dict:
    with connect() as conn:
        cur = conn.execute(
            "INSERT INTO letters (device_id, wish_id, voice_id, text, target_date, created_at)"
            " VALUES (?, ?, ?, ?, ?, datetime('now'))",
            (device_id, wish_id, voice_id, encrypt_text(text), target_date),
        )
        letter_id = cur.lastrowid
    # read back on a fresh connection (the insert is committed above)
    return get_letter(device_id, letter_id)


def list_letters(device_id: str) -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT id, device_id, wish_id, voice_id, text, target_date, created_at"
            " FROM letters WHERE device_id = ? ORDER BY id DESC",
            (device_id,),
        ).fetchall()
        return _decrypt_rows([dict(r) for r in rows])


def get_letter(device_id: str, letter_id: int) -> dict | None:
    with connect() as conn:
        row = conn.execute(
            "SELECT id, device_id, wish_id, voice_id, text, target_date, created_at"
            " FROM letters WHERE device_id = ? AND id = ?",
            (device_id, letter_id),
        ).fetchone()
        return _decrypt_row(dict(row)) if row else None


# ---- check-ins ----

def _streak_from_dates(dates: set[str]) -> int:
    """Consecutive-day streak ending today (or yesterday if not yet
    checked in today)."""
    from datetime import timedelta

    today = date.today()
    streak = 0
    d = today
    if d.isoformat() not in dates:
        d = today - timedelta(days=1)
    while d.isoformat() in dates:
        streak += 1
        d -= timedelta(days=1)
    return streak


def checkin_today(device_id: str) -> None:
    with connect() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO checkins (device_id, checkin_date) VALUES (?, ?)",
            (device_id, _today()),
        )
    # v1 memory source: every 7-day streak is a progress memory.
    status = checkin_status(device_id)
    streak = status["streak_days"]
    if streak > 0 and streak % 7 == 0:
        mem_text = f"连续打卡 {streak} 天"
        if not _memory_exists(device_id, "progress", mem_text):
            # A streak milestone is a proud moment — an emotion memory too.
            create_memory(
                device_id, "progress", mem_text, importance=0.7, emotion="自豪",
            )


def checkin_status(device_id: str) -> dict:
    with connect() as conn:
        rows = conn.execute(
            "SELECT checkin_date FROM checkins WHERE device_id = ? ORDER BY checkin_date DESC",
            (device_id,),
        ).fetchall()
    dates = {r["checkin_date"] for r in rows}
    today = date.today()
    return {
        "streak_days": _streak_from_dates(dates),
        "total_days": len(dates),
        "checked_in_today": today.isoformat() in dates,
    }
