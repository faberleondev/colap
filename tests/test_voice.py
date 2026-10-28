"""Test E2E del dictado local (/api/voice) con el modelo whisper real.

Se ejecuta solo si existe el fixture de audio y SKIP_STT != "1" (en CI se
salta para no depender de la descarga del modelo — correrlo localmente:
    pytest -q tests/test_voice.py --override-ini="addopts="
).
"""
import os
from pathlib import Path

import pytest

FIXTURE = Path(__file__).parent / "fixtures" / "dictado_prueba.wav"

pytestmark = pytest.mark.skipif(
    os.environ.get("SKIP_STT") == "1" or not FIXTURE.exists(),
    reason="STT local deshabilitado (SKIP_STT=1) o fixture ausente")


def test_dictado_local_transcribe_la_frase_conocida(cliente):
    with FIXTURE.open("rb") as f:
        r = cliente.post(
            "/api/voice",
            files={"archivo": ("dictado_prueba.wav", f, "audio/wav")})
    assert r.status_code == 200, r.text
    texto = r.json()["texto"].lower()
    assert "sacos de maíz" in texto          # frase esperada del fixture
