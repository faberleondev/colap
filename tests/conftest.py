"""Configuración de tests: base de datos aislada en temp + cliente HTTP.

DATA_DIR se define ANTES de importar app.db (lee la variable al importar),
así ningún test toca la base real de data/despachapp.db.
"""
import os
import sys
import tempfile
from pathlib import Path

_raiz = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_raiz))

os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="despachapp_tests_")
os.environ.setdefault("SKIP_STT", "0")

import pytest                         # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import app.db as db                   # noqa: E402
from app.main import app              # noqa: E402


@pytest.fixture(autouse=True)
def _db_limpia():
    """Base vacía y ajustes conocidos antes de cada test."""
    db.init_db()
    with db._write_lock:
        db._conn.execute("DELETE FROM tasks")
        db._conn.execute("DELETE FROM settings")
        db._conn.commit()
    db.set_setting("mode", "lifo")
    db.set_setting("auto_triage", "0")     # determinista: sin llamadas a Ollama
    yield


@pytest.fixture()
def cliente():
    with TestClient(app) as c:             # 'with' dispara el evento startup
        yield c


def _crear(cliente: TestClient, title: str, **extra) -> dict:
    r = cliente.post("/api/tasks", json={"title": title, "description": ""},
                     **({"params": extra} if extra else {}))
    assert r.status_code == 200, r.text
    return r.json()["tarea"]
