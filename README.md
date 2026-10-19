# Colap — cola + pila de pendientes LIFO/SJF/SRTF con triage IA local

Organizador de tareas diarias inspirado en estructuras de datos y algoritmos
de planificación de Sistemas Operativos:

- **Pila LIFO** — llega un pendiente y se apila; lo último que llegó es lo
  primero que se suelta (`push` / `pop`).
- **SJF (Shortest Job First)** — la cola se reordena y primero se ejecuta el
  pendiente con menor duración estimada (mínimo tiempo de espera promedio).
- **SRTF (Shortest Remaining Time First, preeemptivo)** — eliges una tarea
  "⚔ en curso"; si llega un pendiente más corto que lo restante del actual,
  lo interrumpe automáticamente: el interrumpido vuelve a la cola conservando
  su tiempo restante (`estimado − trabajado`, acreditado al pausar o terminar).
- **Prioridad** — urgencias al tope; dentro del mismo nivel, LIFO.
- **Repositorio de tareas listas** — al completarse, el pendiente sale de la
  cola y se archiva con su marca de tiempo.
- **Triage con IA local** — [Ollama](https://ollama.com) con `llama3.2:3b`
  estima la duración, la prioridad y la categoría de cada tarea. Si Ollama no
  responde, un triage heurístico integrado mantiene la app funcionando.

Todo corre en local (o autohosteado con Docker). Datos en un único SQLite.

## Uso rápido

### Opción A — Docker (app + Ollama, todo incluido)

```bash
docker compose up -d --build
# primera vez: descargar el modelo de triage
docker compose exec ollama ollama pull llama3.2:3b
```

Abre **http://localhost:8000**.

> ¿Ya tienes Ollama en tu máquina? Edita `docker-compose.yml`, usa
> `OLLAMA_URL=http://host.docker.internal:11434` y elimina el servicio `ollama`.

### Opción B — Local sin Docker

```bash
cd colap
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt      # Windows
# .venv/bin/pip install -r requirements.txt          # Linux/macOS
.venv\Scripts\uvicorn app.main:app --port 8000
```

Si tienes Ollama corriendo (`ollama serve` con `ollama pull llama3.2:3b`),
el triage IA funciona de inmediato. Si no, la app usa el triaje heurístico.

## Variables de entorno

| Variable         | Predeterminada          | Descripción                       |
|------------------|-------------------------|-----------------------------------|
| `DATA_DIR`       | `./data`                | Carpeta del SQLite (`colap.db`).  |
| `OLLAMA_URL`     | `http://localhost:11434`| Endpoint de Ollama.               |
| `OLLAMA_MODEL`   | `llama3.2:3b`           | Modelo usado para el triage.      |
| `OLLAMA_TIMEOUT` | `60`                    | Segundos máximos por triage.      |

## Cómo funciona el triage

Cada tarea nueva (o el botón **✦ Triar**) envía el título/detalles al LLM, que
devuelve JSON con:

- `est_minutes`: 5–480 min — alimenta el modo SJF,
- `priority`: 1 alta / 2 media / 3 baja — alimenta el modo Prioridad,
- `category`: trabajo, hogar, compras, etc.

El origen del triage queda etiquetado en la tarjeta: **IA** (Ollama),
**est. heurística** (respaldo sin LLM) o **manual** (tú la ajustaste).

## API (para scripts o automatización)

| Método | Ruta                      | Acción                              |
|--------|---------------------------|-------------------------------------|
| `GET`  | `/api/state`              | Estado completo (config, cola, etc.)|
| `POST` | `/api/tasks`              | Apilar tarea `{title, description}` |
| `PATCH`| `/api/tasks/{id}`         | Editar estimación/prioridad/etc.    |
| `POST` | `/api/tasks/{id}/complete`| Moverla al repositorio de listas.   |
| `POST` | `/api/tasks/{id}/start`   | Ponerla ⚔ en curso (interrumpe otra). |
| `POST` | `/api/tasks/{id}/pause`   | Volverla a la cola con su restante.  |
| `POST` | `/api/tasks/{id}/triage`  | Recalcular con IA.                  |
| `DELETE`| `/api/tasks/{id}`        | Eliminar.                           |
| `POST` | `/api/settings`           | `{mode: lifo\|sjf\|prioridad}` o `{auto_triage: bool}` |

## Notas de diseño

- **¿Por qué SJF funciona?** Minimiza el tiempo de espera promedio de la cola;
  despejar pendientes cortos libera espacio mental rápido.
- **¿Por qué LIFO?** Las tareas recientes suelen tener contexto fresco; la
  filosofía "push/pop" desalienta el acumular sin procesar.
- **¿Por qué SRTF preeemptivo?** Interrumpir el "trabajo largo en curso" por
  pendientes cortos minimiza el tiempo de espera total — pero tú decides
  arrancar cada tarea; la preención solo reordena, jamás descarta trabajo
  (el interrumpido conserva su tiempo restante).
- Un solo archivo de datos, sin cuentas, sin nube. Backups = copiar `data/`.
