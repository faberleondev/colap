"""Tests de la API HTTP con base aislada (Triaje simulado: sin Ollama real)."""
import pytest

import app.triage as triage
from tests.conftest import _crear


@pytest.fixture()
def triage_falso(monkeypatch):
    """Triage determinista: 'corta'→5 min, 'larga'→120 min, resto→30."""
    async def _falso(title: str, description: str) -> dict:
        est = 5 if "corta" in title.lower() else \
            120 if "larga" in title.lower() else 30
        return {"est_minutes": est, "priority": 2, "category": "test",
                "source": "ia"}
    monkeypatch.setattr(triage, "triar", _falso)


# ------------------------------------------------------------- sanidad

def test_health(cliente):
    r = cliente.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_home_sirve_la_gui(cliente):
    r = cliente.get("/")
    assert r.status_code == 200
    assert "DESPACHAPP" in r.text


# ------------------------------------------------------------ crear tareas

def test_crear_tarea_manual_sin_triage(cliente):
    t = _crear(cliente, "Comprar sacos de maíz")
    assert t["est_minutes"] == 30          # default con auto_triage off
    assert t["source"] == "manual"
    assert t["status"] == "queued"


def test_titulo_largo_con_saltos_se_sanea_y_no_da_422(cliente):
    # reproducción del bug v0.2.1.2: dictado largo con saltos de línea
    titulo = ("Realizar soporte y mantenimiento\n del servidor de archivos "
              "\ry revisar los respaldos, además\r\n actualizar el firmware "
              "y documentar todo el proceso con capturas para el informe "
              "final de soporte técnico integral de la semana") * 2
    r = cliente.post("/api/tasks", json={"title": titulo, "description": ""})
    assert r.status_code == 200, r.text
    t = r.json()["tarea"]
    assert len(t["title"]) == 200          # recortado al límite
    assert "\n" not in t["title"] and "\r" not in t["title"]


def test_titulo_vacio_da_400_amigable(cliente):
    r = cliente.post("/api/tasks", json={"title": "   \n  ", "description": ""})
    assert r.status_code == 400
    assert "dictado" in r.json()["detail"]


# ------------------------------------------------------------- ajustes

def test_modo_invalido_rechazado(cliente):
    r = cliente.post("/api/settings", json={"mode": "fifo"})
    assert r.status_code == 400


def test_cambio_de_modo_y_auto_triage(cliente):
    assert cliente.post("/api/settings", json={"mode": "srtf"}).json()["mode"] == "srtf"
    s = cliente.post("/api/settings", json={"auto_triage": True}).json()
    assert s["auto_triage"] == "1"


# ------------------------------------------------- ciclo de vida de tarea

def test_start_pause_complete_flujo_completo(cliente):
    t = _crear(cliente, "Tarea del flujo")
    tid = t["id"]

    en_curso = cliente.post(f"/api/tasks/{tid}/start").json()
    assert en_curso["status"] == "in_progress"
    assert en_curso["started_at"] is not None

    pausada = cliente.post(f"/api/tasks/{tid}/pause").json()
    assert pausada["status"] == "queued"
    assert pausada["started_at"] is None   # el trabajo quedó acreditado

    lista = cliente.post(f"/api/tasks/{tid}/complete").json()
    assert lista["status"] == "done"
    assert lista["done_at"] is not None

    estado = cliente.get("/api/state").json()
    assert estado["stats"]["done_total"] == 1


def test_solo_una_tarea_en_curso(cliente):
    a = _crear(cliente, "Primera")
    b = _crear(cliente, "Segunda")
    cliente.post(f"/api/tasks/{a['id']}/start")
    cliente.post(f"/api/tasks/{b['id']}/start")   # roba el CPU (sin SRTF: manual)
    estado = cliente.get("/api/state").json()
    assert estado["current"]["id"] == b["id"]
    assert estado["current"]["status"] == "in_progress"
    a_de_nuevo = cliente.get("/api/state").json()["queue"]
    assert [t["id"] for t in a_de_nuevo] == [a["id"]]   # a volvió a la cola


# ------------------------------------------------ SRTF: preemción E2E

def test_srtf_preemption_end_to_end(cliente, triage_falso):
    cliente.post("/api/settings", json={"mode": "srtf", "auto_triage": True})

    larga = cliente.post(  # triage falso → est 120
        "/api/tasks", json={"title": "Tarea larga de migración",
                            "description": ""}).json()["tarea"]
    cliente.post(f"/api/tasks/{larga['id']}/start")

    corta = cliente.post(  # triage falso → est 5 → preeempte a la larga
        "/api/tasks", json={"title": "Tarea corta de envío",
                            "description": ""}).json()

    assert corta["preempted"]["id"] == larga["id"]
    estado = cliente.get("/api/state").json()
    assert estado["current"]["id"] == corta["tarea"]["id"]
    assert [t["id"] for t in estado["queue"]] == [larga["id"]]
    # y quedó el aviso para la UI
    estado2 = cliente.get("/api/state").json()
    assert estado2["notice"] is None      # el primer pop ya se lo llevó


# ------------------------------------------------------- errores y bordes

def test_patch_tarea_inexistente_404(cliente):
    assert cliente.patch("/api/tasks/999", json={"title": "x"}).status_code == 404


def test_delete_tarea(cliente):
    t = _crear(cliente, "Para borrar")
    assert cliente.delete(f"/api/tasks/{t['id']}").json() == {"ok": True}
    assert cliente.get("/api/state").json()["queue"] == []


def test_avisos_se_consumen_una_sola_vez(cliente):
    cliente.post("/api/settings", json={"mode": "srtf", "auto_triage": True})
    larga = cliente.post("/api/tasks", json={"title": "Larga", "description": ""}).json()["tarea"]
    cliente.post(f"/api/tasks/{larga['id']}/start")
    cliente.post("/api/tasks", json={"title": "corta", "description": ""})
    assert "Preempted" in cliente.get("/api/state").json()["notice"]
    assert cliente.get("/api/state").json()["notice"] is None
