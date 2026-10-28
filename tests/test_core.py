"""Tests del corazón del despachador: orden de cola y SRTF (sin red, sin DB)."""
from app.core import MODES, debe_preeemptir, order_queue, restante
from app.core import triage_heuristico


def _tarea(tid, est=30, prio=2, spent=0):
    return {"id": tid, "est_minutes": est, "priority": prio,
            "spent_minutes": spent}


# ------------------------------------------------------------------ restante

def test_restante_basico():
    assert restante(_tarea(1, est=100, spent=30)) == 70


def test_restante_nunca_negativo():
    assert restante(_tarea(1, est=10, spent=50)) == 0


# --------------------------------------------------------------- LIFO (pila)

def test_lifo_ultimo_en_llegar_primero():
    cola = order_queue([_tarea(1), _tarea(2), _tarea(3)], "lifo")
    assert [t["id"] for t in cola] == [3, 2, 1]


# ----------------------------------------------------------------- SJF

def test_sjf_menor_duracion_primero():
    cola = order_queue([_tarea(1, est=60), _tarea(2, est=15),
                        _tarea(3, est=30)], "sjf")
    assert [t["id"] for t in cola] == [2, 3, 1]


def test_sjf_empate_por_prioridad_luego_ultimo_id():
    # mismo est: desempata prioridad (1 < 2) y después el más nuevo (-id)
    cola = order_queue([_tarea(1, est=30, prio=2), _tarea(2, est=30, prio=1),
                        _tarea(3, est=30, prio=2)], "sjf")
    assert [t["id"] for t in cola] == [2, 3, 1]


# ---------------------------------------------------------------- SRTF

def test_srtf_usa_tiempo_restante_no_el_estimado():
    # A trabajó 90 de 100 (restan 10); B recién llega con 15 → A primero
    a = _tarea(1, est=100, spent=90)
    b = _tarea(2, est=15)
    cola = order_queue([b, a], "srtf")
    assert [t["id"] for t in cola] == [1, 2]
    # y en SJF puro B iría primero (15 < 100) — así se nota lo preemptivo
    cola_sjf = order_queue([b, a], "sjf")
    assert [t["id"] for t in cola_sjf] == [2, 1]


def test_srtf_empate_desempata_por_prioridad():
    a = _tarea(1, est=30, prio=2, spent=10)   # restan 20
    b = _tarea(2, est=20, prio=1)             # restan 20
    cola = order_queue([a, b], "srtf")
    assert [t["id"] for t in cola] == [2, 1]


# --------------------------------------------------- SRTF: ¿preeempte o no?

def test_no_preeempte_sin_tarea_en_curso():
    assert debe_preeemptir(None, 5) is False


def test_preeempte_si_la_nueva_es_mas_corta_que_lo_restante():
    actual = _tarea(1, est=120, spent=0)      # restan 120
    assert debe_preeemptir(actual, 90) is True


def test_no_preeempte_si_es_igual_o_mas_larga():
    actual = _tarea(1, est=120, spent=30)     # restan 90
    assert debe_preeemptir(actual, 90) is False   # empate: no roba
    assert debe_preeemptir(actual, 120) is False


# ------------------------------------------------------------- prioridad

def test_prioridad_antes_que_nada_ultimo_id_primero():
    cola = order_queue([_tarea(1, prio=3), _tarea(2, prio=1),
                        _tarea(3, prio=2)], "prioridad")
    assert [t["id"] for t in cola] == [2, 3, 1]


# ------------------------------------------------------------------ modos

def test_modos_conocidos():
    assert MODES == {"lifo", "sjf", "srtf", "prioridad"}


# ------------------------------------------------------- triage heurístico

def test_heuristica_larga_media_corta():
    assert triage_heuristico("Documentar el informe anual", "")["est_minutes"] == 120
    assert triage_heuristico("Revisar el código", "")["est_minutes"] == 45
    assert triage_heuristico("Comprar sacos de maíz", "")["est_minutes"] == 15


def test_heuristica_sin_palabra_clave_usa_default():
    t = triage_heuristico("Misterio sin pistas", "")
    assert t == {"est_minutes": 30, "priority": 2, "category": "otro"}


def test_heuristica_urgencia_sube_prioridad():
    t = triage_heuristico("Comprar", "es urgente, vence hoy")
    assert t["priority"] == 1
