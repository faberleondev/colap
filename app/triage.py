"""Triage de tareas con LLM local (Ollama). Con respaldo heurístico.

Si OLLAMA_URL no responde, se usa `core.triage_heuristico` y la app sigue
funcionando; el campo `source` indica qué mecanismoBild produjo el triage.
"""
import json
import logging

import httpx

from .core import triage_heuristico
import os

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "llama3.2:3b")
TIMEOUT = float(os.environ.get("OLLAMA_TIMEOUT", "60"))

log = logging.getLogger("colap.triage")

PROMPT_SISTEMA = (
    "Eres un asistente de triage de tareas para una persona sola. "
    "Analizas una tarea pendiente y devuelves un estimado profesional. "
    "Responde ÚNICAMENTE con un JSON válido, sin texto extra, con estas "
    "claves: "
    'est_minutes: entero entre 5 y 480 (minutos para completar la tarea), '
    "priority: 1 (alta: urgente/plazo) / 2 (media) / 3 (baja: puede esperar), "
    "category: una frase de máximo 2 palabras_lowercase entre: trabajo, "
    "personal, hogar, compras, admin, salud, estudio, comunicacion, otro."
)

PROMPT_TAREA = "Tarea: {title}\nDetalles: {details}"


def _clamp(n: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, n))


def _validar(d: dict) -> dict | None:
    try:
        minutes = _clamp(int(d["est_minutes"]), 5, 480)
        priority = _clamp(int(d["priority"]), 1, 3)
        category = str(d.get("category", "otro")).strip().lower()[:24]
        if not category:
            category = "otro"
        return {"est_minutes": minutes, "priority": priority,
                "category": category}
    except (KeyError, ValueError, TypeError):
        return None


async def triar(title: str, description: str) -> dict:
    """Devuelve {est_minutes, priority, category, source}."""
    payload = {
        "model": OLLAMA_MODEL,
        "format": "json",
        "stream": False,
        "options": {"temperature": 0},
        "messages": [
            {"role": "system", "content": PROMPT_SISTEMA},
            {"role": "user", "content": PROMPT_TAREA.format(
                title=title, details=description or "—")},
        ],
    }
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            r = await client.post(f"{OLLAMA_URL}/api/chat", json=payload)
            r.raise_for_status()
            contenido = r.json().get("message", {}).get("content", "")
            resp = json.loads(contenido)
        data = _validar(resp)
        if data is None:
            raise ValueError(f"JSON inválido del LLM: {resp!r}")
        data["source"] = "ia"
        return data
    except Exception as e:  # noqa: BLE001 — el respaldo es parte del diseño
        log.warning("Triage con Ollama falló (%s: %s); uso heurística",
                    type(e).__name__, e)
        data = triage_heuristico(title, description)
        data["source"] = "heuristica"
        return data


async def estado_ollama() -> str:
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.get(f"{OLLAMA_URL}/api/tags")
            r.raise_for_status()
            nombres = [m.get("name", "") for m in r.json().get("models", [])]
            if any(n.startswith(OLLAMA_MODEL.split(":")[0]) for n in nombres):
                return "ok"
            return f"falta-modelo:{OLLAMA_MODEL}"
    except Exception:  # noqa: BLE001
        return "indisponible"
