"""Acceso a datos de Colap: SQLite con ajustes y tareas."""
import os
import sqlite3
import threading
from datetime import datetime, timezone

DATA_DIR = os.environ.get("DATA_DIR", os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data"))
os.makedirs(DATA_DIR, exist_ok=True)
DB_PATH = os.path.join(DATA_DIR, "colap.db")

_conn: sqlite3.Connection | None = None
_write_lock = threading.Lock()

DEFAULT_SETTINGS = {"mode": "lifo", "auto_triage": "1"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    title       TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    category    TEXT NOT NULL DEFAULT '',
    est_minutes INTEGER NOT NULL DEFAULT 30,
    priority    INTEGER NOT NULL DEFAULT 2,   -- 1 alta, 2 media, 3 baja
    status      TEXT NOT NULL DEFAULT 'queued' CHECK (status IN ('queued', 'done')),
    source      TEXT NOT NULL DEFAULT 'manual', -- manual | ia | heuristica
    created_at  TEXT NOT NULL,
    done_at     TEXT
);
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db() -> None:
    global _conn
    _conn = _connect()
    with _write_lock:
        _conn.executescript(SCHEMA)
        for k, v in DEFAULT_SETTINGS.items():
            _conn.execute(
                "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (k, v))
        _conn.commit()


def _check() -> sqlite3.Connection:
    if _conn is None:
        init_db()
    return _conn  # type: ignore[return-value]


# ---------------------------------------------------------------- tareas ----

def insert_task(title: str, description: str, category: str = "",
                est_minutes: int = 30, priority: int = 2,
                source: str = "manual") -> int:
    with _write_lock:
        cur = _check().execute(
            "INSERT INTO tasks (title, description, category, est_minutes,"
            " priority, source, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (title, description, category, est_minutes, priority,
             source, now_iso()))
        _conn.commit()
    return cur.lastrowid  # type: ignore[return-type]


def update_task(tid: int, fields: dict) -> None:
    allowed = {"title", "description", "category", "est_minutes", "priority"}
    sets = {k: v for k, v in fields.items() if k in allowed}
    if not sets:
        return
    cols = ", ".join(f"{k} = ?" for k in sets)
    with _write_lock:
        _check().execute(f"UPDATE tasks SET {cols} WHERE id = ?",
                         (*sets.values(), tid))
        _conn.commit()


def set_status(tid: int, status: str) -> None:
    with _write_lock:
        _check().execute(
            "UPDATE tasks SET status = ?, done_at = ? WHERE id = ?",
            (status, now_iso() if status == "done" else None, tid))
        _conn.commit()


def set_source(tid: int, source: str) -> None:
    with _write_lock:
        _check().execute("UPDATE tasks SET source = ? WHERE id = ?",
                         (source, tid))
        _conn.commit()


def delete_task(tid: int) -> None:
    with _write_lock:
        _check().execute("DELETE FROM tasks WHERE id = ?", (tid,))
        _conn.commit()


def queued_tasks() -> list[dict]:
    rows = _check().execute(
        "SELECT * FROM tasks WHERE status = 'queued'").fetchall()
    return [dict(r) for r in rows]


def done_tasks(limit: int = 100) -> list[dict]:
    rows = _check().execute(
        "SELECT * FROM tasks WHERE status = 'done'"
        " ORDER BY done_at DESC LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in rows]


def get_task(tid: int) -> dict | None:
    row = _check().execute("SELECT * FROM tasks WHERE id = ?", (tid,)).fetchone()
    return dict(row) if row else None


def stats() -> dict:
    c = _check()
    queued = c.execute(
        "SELECT COUNT(*) FROM tasks WHERE status = 'queued'").fetchone()[0]
    done_total = c.execute(
        "SELECT COUNT(*) FROM tasks WHERE status = 'done'").fetchone()[0]
    today = now_iso()[:10]
    done_today = c.execute(
        "SELECT COUNT(*) FROM tasks WHERE status = 'done'"
        " AND done_at LIKE ?", (f"{today}%",)).fetchone()[0]
    avg_est = c.execute(
        "SELECT AVG(est_minutes) FROM tasks WHERE status = 'queued'"
    ).fetchone()[0]
    return {"queued": queued, "done_total": done_total,
            "done_today": done_today, "avg_est": round(avg_est or 0)}


# ---------------------------------------------------------- configuración ---

def get_settings() -> dict:
    rows = _check().execute("SELECT key, value FROM settings").fetchall()
    s = dict(DEFAULT_SETTINGS)
    s.update({r["key"]: r["value"] for r in rows})
    return s


def set_setting(key: str, value: str) -> None:
    with _write_lock:
        _check().execute(
            "INSERT INTO settings (key, value) VALUES (?, ?)"
            " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value))
        _conn.commit()
