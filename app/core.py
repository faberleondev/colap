"""Ordenadores de cola (LIFO / SJF / Prioridad) y triage heurístico."""

# ------------------------------------------------------------ scheduling ----

def order_queue(tasks: list[dict], mode: str) -> list[dict]:
    """Devuelve la cola lista para visualizar.

    LIFO      : la última tarea en llegar es el tope de la pila (primero).
    SJF       : el pendiente con menor duración estimada va primero.
    prioridad : alfabético por urgencia; dentro de mismo nivel, LIFO.
    """
    if mode == "sjf":
        return sorted(
            tasks,
            key=lambda t: (t["est_minutes"], t["priority"], -t["id"]))
    if mode == "prioridad":
        return sorted(
            tasks,
            key=lambda t: (t["priority"], -t["id"]))
    # lifo (por defecto)
    return sorted(tasks, key=lambda t: -t["id"])


MODES = {"lifo", "sjf", "prioridad"}


# ------------------------------------------------------------ triage IA ----
# Respaldo sin red: palabras clave simples en español. Solo se usa si
# Ollama no responde, así la app nunca queda sin triage.

_LARGA = ("planificar", "diseñar", "investigar", "documentar", "escribir",
          "presupuesto", "proyecto", "migrar", "implementar", "informe",
          "presentación", "propuesta", "estudiar", "refactor")
_MEDIA = ("revisar", "actualizar", "limpiar", "listar", "analizar",
          "responder", "preparar", "comparar", "configurar", "ordenar")
_CORTA = ("enviar", "responder correo", "llamar", "comprar", "pagar",
          "agendar", "abonar", "avisar", "recordar", "imprimir", "firmar")
_URGENTE = ("urgente", "hoy", "ahora", "deadline", "fecha límite", "vence",
            "crítico", "bloquea")


def triage_heuristico(title: str, description: str) -> dict:
    text = f"{title} {description}".lower()
    minutes = 30
    if any(w in text for w in _LARGA):
        minutes = 120
    elif any(w in text for w in _MEDIA):
        minutes = 45
    elif any(w in text for w in _CORTA):
        minutes = 15
    priority = 1 if any(w in text for w in _URGENTE) else 2
    return {"est_minutes": minutes, "priority": priority, "category": "otro"}
