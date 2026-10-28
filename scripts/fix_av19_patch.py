"""Aplica el parche PyAV19↔faster-whisper 1.2.1 (idempotente).

PyAV 19 eliminó el argumento `metadata_errors` de av.open(), que
faster-whisper 1.2.1 todavía usa. El fix ya está en el master de upstream
(SYSTRAN/faster-whisper #1495) pero aún no publicado en PyPI. Este script
aplica el mismo cambio al paquete instalado y se puede correr tras cada
`pip install -r requirements.txt`.

Uso:  python scripts/fix_av19_patch.py
"""
import re
from pathlib import Path

import faster_whisper

audio_py = Path(faster_whisper.__file__).parent / "audio.py"
src = audio_py.read_text(encoding="utf-8")

if "_AV_OPEN_KWARGS" in src:
    print("El parche ya está aplicado — nada que hacer.")
elif 'metadata_errors="ignore"' not in src:
    print("faster-whisper actualizado (ya no usa metadata_errors) — nada que hacer.")
else:
    parche = '''import av
import numpy as np

# Parche local (fix upstream SYSTRAN/faster-whisper #1495, aún no publicado
# en PyPI a 1.2.1): PyAV 19 eliminó metadata_errors; solo existe en <19.
_AV_OPEN_KWARGS = (
    {"metadata_errors": "ignore"} if int(av.__version__.split(".")[0]) < 19 else {}
)
'''
    src = src.replace("import av\nimport numpy as np\n", parche, 1)
    src = src.replace(
        'with av.open(input_file, mode="r", metadata_errors="ignore") as container:',
        'with av.open(input_file, mode="r", **_AV_OPEN_KWARGS) as container:')
    audio_py.write_text(src, encoding="utf-8")
    print(f"Parche aplicado en {audio_py}")