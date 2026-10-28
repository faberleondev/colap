"""Acceso a datos de Colap: SQLite con ajustes y tareas."""
import os
import sqlite3
import threading
from datetime import datetime, timezone

DATA_DIR = os.environ.get("DATA_DIR", os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data"))
os.makedirs(DATA_DIR, exist_ok=True)
DB_PATH = os.path.join(DATA_DIR, "despachapp.db")

_conn: sqlite3.Connection | None = None
_write_lock = threading.Lock()

DEFAULT_SETTINGS = {
    "mode": "lifo",
    "auto_triage": "1",
    "stt_model": "base",       # tiny | base | small (dictado local)
    "glosario": (              # correcciones del dictado (GUI ⚙ Ajustes)
        "# Una corrección por línea: mal entendido => corrección\n"
        "open media vowel=>OpenMediaVault\n"
        "media vowel=>OpenMediaVault\n"
        "open media vault=>OpenMediaVault\n"
        "promox=>Proxmox\n"
        "optiplex=>OptiPlex\n"),
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    title         TEXT NOT NULL,
    description   TEXT NOT NULL DEFAULT '',
    category      TEXT NOT NULL DEFAULT '',
    est_minutes   INTEGER NOT NULL DEFAULT 30,
    spent_minutes INTEGER NOT NULL DEFAULT 0,   -- trabajo ya acreditado (SRTF)
    priority      INTEGER NOT NULL DEFAULT 2,   -- 1 alta, 2 media, 3 baja
    status        TEXT NOT NULL DEFAULT 'queued'
                  CHECK (status IN ('queued', 'in_progress', 'done')),
    source        TEXT NOT NULL DEFAULT 'manual', -- manual | ia | heuristica
    created_at    TEXT NOT NULL,
    started_at    TEXT,                          -- cuando quedó 'en curso'
    done_at       TEXT
);
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def _migrate(conn: sqlite3.Connection) -> None:
    """Columnas nuevas en bases creadas con versiones anteriores."""
    cols = {r[1] for r in conn.execute("PRAGMA table_info(tasks)")}
    if "spent_minutes" not in cols:
        conn.execute(
            "ALTER TABLE tasks ADD COLUMN spent_minutes INTEGER NOT NULL DEFAULT 0")
    if "started_at" not in cols:
        conn.execute("ALTER TABLE tasks ADD COLUMN started_at TEXT")


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
        _migrate(_conn)
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


# --------------------------------------------------------- SRTF: en curso ---

def set_running(tid: int) -> None:
    """Pone una tarea 'en curso' (solo puede existir una)."""
    with _write_lock:
        _check().execute("UPDATE tasks SET started_at = ? WHERE id = ?",
                         (now_iso(), tid))
        _conn.commit()


def get_in_progress() -> dict | None:
    row = _check().execute(
        "SELECT * FROM tasks WHERE status = 'in_progress' LIMIT 1").fetchone()
    return dict(row) if row else None


def accrue(tid: int) -> None:
    """Acredita en spent_minutes el tiempo trabajado desde started_at."""
    t = get_task(tid)
    if t is None or not t["started_at"]:
        return
    inicio = datetime.fromisoformat(t["started_at"])
    minutos = int((datetime.now(inicio.tzinfo) - inicio).total_seconds() // 60)
    with _write_lock:
        _check().execute(
            "UPDATE tasks SET spent_minutes = spent_minutes + ?,"
            " started_at = NULL WHERE id = ?",
            (max(0, minutos), tid))
        _conn.commit()


# ---------------------------------------------------------- avisos (UI) ----

def set_notice(texto: str) -> None:
    set_setting("notice", texto)


def pop_notice() -> str | None:
    n = get_settings().get("notice") or None
    if n:
        set_notice("")
    return n


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
