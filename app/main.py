"""DespachApp v0.2.1.1 — despachador de pendientes LIFO/SJF/SRTF con triage IA local.

Dictado: Web Speech API nativa del navegador con respaldo local — si falla
('network' o navegador sin soporte), el audio se graba y transcribe en el
servidor con faster-whisper (100% offline, sin servicios externos).
"""
import logging
import os
import re
import shutil
import tempfile
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from . import db, triage
from .core import MODES, debe_preeemptir, order_queue, restante

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(name)s %(levelname)s %(message)s")

STT_MODEL = os.environ.get("STT_MODEL", "base")   # faster-whisper: tiny|base|small
_whisper = None

app = FastAPI(title="DespachApp", version="0.2.1.2")
STATIC_DIR = Path(__file__).parent / "static"


def _whisper_cargar():
    """Carga diferida del modelo de transcripción (solo si hay dictado local)."""
    global _whisper
    if _whisper is None:
        from faster_whisper import WhisperModel
        _whisper = WhisperModel(STT_MODEL, device="cpu", compute_type="int8")
    return _whisper


@app.on_event("startup")
def _startup() -> None:
    db.init_db()


# ---------------------------------------------------------------- modelos ---
class TareaIn(BaseModel):
    title: str = Field(default="", max_length=10000)   # se sanea y recorta en el endpoint
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

MAX_TITLE = 200          # límite duro del modelo TareaIn (DB y UI)
MAX_DESC = 2000
ESPACIOS = re.compile(r"\s+")


def _sanear(texto: str, maximo: int) -> str:
    """Colapsa espacios/saltos de línea y corta al límite — nunca 422."""
    limpio = ESPACIOS.sub(" ", texto or "").strip()
    return limpio[:maximo].rstrip()


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/health")
def health():
    """Chequeo simple de vida (para monitores y para no ver 404s en devtools)."""
    return {"status": "ok", "version": "0.2.1.2"}


@app.get("/api/state")
async def estado():
    settings = db.get_settings()
    mode = settings["mode"]
    current = db.get_in_progress()
    if current:
        current["restante"] = restante(current)
    return {
        "settings": settings,
        "current": current,                                   # ⚔ en curso
        "queue": order_queue(db.queued_tasks(), mode),
        "done": db.done_tasks(),
        "stats": db.stats(),
        "ollama": await triage.estado_ollama(),
        "notice": db.pop_notice(),
    }


@app.post("/api/tasks")
async def crear(t: TareaIn):
    titulo = _sanear(t.title, MAX_TITLE)
    if not titulo:
        raise HTTPException(
            400, "La tarea no tiene título — revisá que el dictado haya "
            "capturado palabras y probá de nuevo el 🎤")
    settings = db.get_settings()
    triaged: dict | None = None
    source = "manual"
    if settings.get("auto_triage") == "1":
        triaged = await triage.triar(titulo, _sanear(t.description, MAX_DESC))
        source = triaged.get("source", "manual")
    est = (triaged or {}).get("est_minutes", 30)
    tid = db.insert_task(
        titulo, _sanear(t.description, MAX_DESC),
        category=(triaged or {}).get("category", ""),
        est_minutes=est,
        priority=(triaged or {}).get("priority", 2),
        source=source)
    # SRTF: si al llegar algo más corto que lo restante del actual, roba el CPU
    preempted = None
    if settings["mode"] == "srtf":
        current = db.get_in_progress()
        if debe_preeemptir(current, est):
            db.accrue(current["id"])
            db.set_status(current["id"], "queued")
            db.set_running(tid)
            preempted = {"id": current["id"], "title": current["title"]}
            db.set_notice(
                f"⚔ Preempted «{current['title']}» (quedan "
                f"{restante(current)} min) — en curso: «{t.title}»")
    return {"tarea": db.get_task(tid), "preempted": preempted}


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


@app.post("/api/tasks/{tid}/start")
async def empezar(tid: int):
    t = db.get_task(tid)
    if t is None:
        raise HTTPException(404, "Tarea no existe")
    if t["status"] == "done":
        raise HTTPException(400, "Esa tarea ya está lista")
    current = db.get_in_progress()
    if current and current["id"] != tid:      # solo una en curso
        db.accrue(current["id"])
        db.set_status(current["id"], "queued")
    if t["status"] != "in_progress":
        db.set_status(tid, "in_progress")
        db.set_running(tid)
    return db.get_task(tid)


@app.post("/api/tasks/{tid}/pause")
async def pausar(tid: int):
    t = db.get_task(tid)
    if t is None or t["status"] != "in_progress":
        raise HTTPException(400, "La tarea no está en curso")
    db.set_status(tid, "queued")
    db.accrue(tid)
    return db.get_task(tid)


@app.post("/api/tasks/{tid}/complete")
async def completar(tid: int):
    t = db.get_task(tid)
    if t is None:
        raise HTTPException(404, "Tarea no existe")
    if t["status"] == "in_progress":          # acredita el trabajo hecho
        db.accrue(tid)
    db.set_status(tid, "done")
    return db.get_task(tid)


@app.delete("/api/tasks/{tid}")
async def eliminar(tid: int):
    if db.get_task(tid) is None:
        raise HTTPException(404, "Tarea no existe")
    db.delete_task(tid)
    return {"ok": True}


@app.post("/api/voice")
async def voz(archivo: UploadFile = File(...)):
    """Dictado local: audio (webm/opus o wav) → texto con faster-whisper.

    Respaldo ante 'network' del dictado nativo del navegador, y para
    navegadores sin Web Speech API. Privacidad: nada sale del equipo.
    """
    ext = os.path.splitext(archivo.filename or "audio.webm")[1] or ".webm"
    tmp = tempfile.NamedTemporaryFile(suffix=ext, delete=False)
    try:
        shutil.copyfileobj(archivo.file, tmp)
        tmp.close()
        try:
            model = _whisper_cargar()
        except ImportError:
            raise HTTPException(
                503, "Dictado local no instalado. Actívalo con: "
                ".venv\\Scripts\\pip install faster-whisper  (o usa el dictado "
                "nativo en Edge/Chrome)")
        segmentos, _info = model.transcribe(tmp.name, language="es", beam_size=1)
        texto = " ".join(s.text for s in segmentos).strip()
        if not texto:
            raise HTTPException(422, "No se entendió nada del dictado")
        return {"texto": texto}
    finally:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass


@app.post("/api/settings")
async def config(cfg: ConfigIn):
    if cfg.mode is not None:
        if cfg.mode not in MODES:
            raise HTTPException(400, f"modos válidos: {sorted(MODES)}")
        db.set_setting("mode", cfg.mode)
    if cfg.auto_triage is not None:
        db.set_setting("auto_triage", "1" if cfg.auto_triage else "0")
    return db.get_settings()
