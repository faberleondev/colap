"""Tests del triage con LLM: validación de JSON y respaldo heurístico."""
import asyncio

import app.triage as triage


# ----------------------------------------------------------- _validar

def test_validar_recorta_valores_fuera_de_rango():
    d = triage._validar({"est_minutes": 9999, "priority": 0,
                         "category": "  TRABAJO "})
    assert d == {"est_minutes": 480, "priority": 1, "category": "trabajo"}


def test_validar_json_incompleto_devuelve_none():
    assert triage._validar({"est_minutes": "no soy número"}) is None
    assert triage._validar({}) is None


def test_validar_categoria_vacia_cae_en_otro():
    d = triage._validar({"est_minutes": 30, "priority": 2, "category": ""})
    assert d["category"] == "otro"


# ------------------------------------------------- respaldo (sin Ollama)

def test_triar_sin_ollama_cae_en_heuristica(monkeypatch):
    monkeypatch.setattr(triage, "OLLAMA_URL", "http://127.0.0.1:9")  # nada escucha
    monkeypatch.setattr(triage, "TIMEOUT", 0.2)
    r = asyncio.run(triage.triar("Documentar el plan", ""))
    assert r["source"] == "heuristica"
    assert 5 <= r["est_minutes"] <= 480
    assert r["priority"] in (1, 2, 3)


def test_estado_ollama_sin_servicio_devuelve_indisponible(monkeypatch):
    monkeypatch.setattr(triage, "OLLAMA_URL", "http://127.0.0.1:9")
    assert asyncio.run(triage.estado_ollama()) == "indisponible"
