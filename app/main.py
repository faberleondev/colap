"""Colap — organizador de pendientes LIFO/SJF/prioridad con triage IA local."""
import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from . import db, triage
from .core import MODES, order_queue

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(name)s %(levelname)s %(message)s")

app = FastAPI(title="Colap", version="0.1.0")
STATIC_DIR = Path(__file__).parent / "static"


@app.on_event("startup")
def _startup() -> None:
    db.init_db()


# ---------------------------------------------------------------- modelos ---
class TareaIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str = ""


class TareaPatch(BaseModel):
    title: str | None = None
    description: str | None = None
    est_minutes: int | None = Field(default=None, ge=5, le=480)
    priority: int | None = Field(default=None, ge=1, le=3)
    category: str | None = None


class ConfigIn(BaseModel):
    mode: str | None = None
    auto_triage: bool | None = None


# -------------------------------------------------------------------- API ---

@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/state")
async def estado():
    settings = db.get_settings()
    mode = settings["mode"]
    return {
        "settings": settings,
        "queue": order_queue(db.queued_tasks(), mode),
        "done": db.done_tasks(),
        "stats": db.stats(),
        "ollama": await triage.estado_ollama(),
    }


@app.post("/api/tasks")
async def crear(t: TareaIn):
    settings = db.get_settings()
    triaged: dict | None = None
    source = "manual"
    if settings.get("auto_triage") == "1":
        triaged = await triage.triar(t.title, t.description)
        source = triaged.get("source", "manual")
    tid = db.insert_task(
        t.title, t.description,
        category=(triaged or {}).get("category", ""),
        est_minutes=(triaged or {}).get("est_minutes", 30),
        priority=(triaged or {}).get("priority", 2),
        source=source)
    return db.get_task(tid)


@app.patch("/api/tasks/{tid}")
async def editar(tid: int, patch: TareaPatch):
    if db.get_task(tid) is None:
        raise HTTPException(404, "Tarea no existe")
    db.update_task(tid, patch.model_dump(exclude_none=True))
    return db.get_task(tid)


@app.post("/api/tasks/{tid}/triage")
async def retriajar(tid: int):
    t = db.get_task(tid)
    if t is None:
        raise HTTPException(404, "Tarea no existe")
    r = await triage.triar(t["title"], t["description"])
    db.update_task(tid, r)
    db.set_source(tid, r["source"])
    return db.get_task(tid)


@app.post("/api/tasks/{tid}/complete")
async def completar(tid: int):
    if db.get_task(tid) is None:
        raise HTTPException(404, "Tarea no existe")
    db.set_status(tid, "done")
    return db.get_task(tid)


@app.delete("/api/tasks/{tid}")
async def eliminar(tid: int):
    if db.get_task(tid) is None:
        raise HTTPException(404, "Tarea no existe")
    db.delete_task(tid)
    return {"ok": True}


@app.post("/api/settings")
async def config(cfg: ConfigIn):
    if cfg.mode is not None:
        if cfg.mode not in MODES:
            raise HTTPException(400, f"modos válidos: {sorted(MODES)}")
        db.set_setting("mode", cfg.mode)
    if cfg.auto_triage is not None:
        db.set_setting("auto_triage", "1" if cfg.auto_triage else "0")
    return db.get_settings()
