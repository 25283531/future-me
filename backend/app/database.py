"""SQLite storage (stdlib sqlite3, no ORM — keeps the image small)."""
import sqlite3
from datetime import date
from pathlib import Path

from .config import settings

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
"""


def connect() -> sqlite3.Connection:
    settings.DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(settings.DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db() -> None:
    with connect() as conn:
        conn.executescript(SCHEMA)


def _today() -> str:
    return date.today().isoformat()


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
    with connect() as conn:
        cur = conn.execute(
            "INSERT INTO wishes (device_id, text, category, days, created_at)"
            " VALUES (?, ?, ?, ?, datetime('now'))",
            (device_id, text, category, days),
        )
        wish_id = cur.lastrowid
    # read back on a fresh connection (the insert is committed above)
    return get_wish(device_id, wish_id)


def list_wishes(device_id: str) -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT id, device_id, text, category, days, created_at FROM wishes"
            " WHERE device_id = ? ORDER BY id DESC",
            (device_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def get_wish(device_id: str, wish_id: int) -> dict | None:
    with connect() as conn:
        row = conn.execute(
            "SELECT id, device_id, text, category, days, created_at FROM wishes"
            " WHERE device_id = ? AND id = ?",
            (device_id, wish_id),
        ).fetchone()
        return dict(row) if row else None


# ---- letters ----

def create_letter(
    device_id: str, wish_id: int, voice_id: str | None, text: str, target_date: str
) -> dict:
    with connect() as conn:
        cur = conn.execute(
            "INSERT INTO letters (device_id, wish_id, voice_id, text, target_date, created_at)"
            " VALUES (?, ?, ?, ?, ?, datetime('now'))",
            (device_id, wish_id, voice_id, text, target_date),
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
        return [dict(r) for r in rows]


def get_letter(device_id: str, letter_id: int) -> dict | None:
    with connect() as conn:
        row = conn.execute(
            "SELECT id, device_id, wish_id, voice_id, text, target_date, created_at"
            " FROM letters WHERE device_id = ? AND id = ?",
            (device_id, letter_id),
        ).fetchone()
        return dict(row) if row else None


# ---- check-ins ----

def checkin_today(device_id: str) -> None:
    with connect() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO checkins (device_id, checkin_date) VALUES (?, ?)",
            (device_id, _today()),
        )


def checkin_status(device_id: str) -> dict:
    with connect() as conn:
        rows = conn.execute(
            "SELECT checkin_date FROM checkins WHERE device_id = ? ORDER BY checkin_date DESC",
            (device_id,),
        ).fetchall()
    dates = {r["checkin_date"] for r in rows}
    today = date.today()
    streak = 0
    d = today
    if d.isoformat() not in dates:
        # streak counts up to yesterday if today not yet checked in
        from datetime import timedelta

        d = today - timedelta(days=1)
    from datetime import timedelta

    while d.isoformat() in dates:
        streak += 1
        d -= timedelta(days=1)
    return {
        "streak_days": streak,
        "total_days": len(dates),
        "checked_in_today": today.isoformat() in dates,
    }
