"""Glosas generadas de las Novellae (RF-11): Baker falso por la misma CLI que usa `glosar`."""
import sys
from contextlib import closing

import pytest

from tabularium import almacen, construir, glosas
from tabularium.novellae import novellae

from test_construir import FUENTE, db  # noqa: F401 (fixture: ley de prueba con el art. 2o reformado)

BAKER_FALSO = '''
import json, os, sys
sys.stderr.reconfigure(encoding="utf-8")  # como la CLI real
if os.environ.get("BAKER_CAIDO"):
    sys.exit("baker: Ningún modelo cabe ahora en Pixilate")
if sys.argv[1] == "status":
    print(json.dumps({"bakers": {"glosador": "falso"}}))
else:
    entrada = open(sys.argv[sys.argv.index("-f") + 1], encoding="utf-8").read()
    assert "[-viejo.-]{+nuevo.+}" in entrada and "Unidad: 2o" in entrada
    print(json.dumps({"resumen": " Cambia viejo por nuevo. ", "efecto": "restringe"}))
'''


@pytest.fixture(autouse=True)
def baker_falso(tmp_path, monkeypatch):
    """Caché propia (antes que `db`, que construye) y `TABULARIUM_BAKER` apuntando al script."""
    monkeypatch.setenv("TABULARIUM_CACHE", str(tmp_path / "cache"))
    script = tmp_path / "baker_falso.py"
    script.write_text(BAKER_FALSO, encoding="utf-8")
    monkeypatch.setenv("TABULARIUM_BAKER", f'"{sys.executable.replace(chr(92), "/")}" "{script.as_posix()}"')


def cambio(ruta):
    with closing(almacen.abrir(ruta)) as con:
        [n] = [x for x in novellae(con, "2024-01-01", "2024-12-31") if x["decreto_dof"] == "DOF-2024-04-01"]
    return n["documentos"][0]["cambios"][0]


def test_sin_glosa_queda_en_null(db):
    c = cambio(db)
    assert (c["efecto"], c["efecto_generado"], c["resumen"]) == (None, None, None)


def test_glosar_y_reconstruir(db, tmp_path):
    with closing(almacen.abrir(db)) as con:
        assert glosas.glosar(con, "2024-01-01") == {"pendientes": 1, "hechas": 1, "modelo": "falso", "error": None}
        assert glosas.glosar(con, "2024-01-01")["pendientes"] == 0  # ya está en la caché: no se pide otra vez
    otra = tmp_path / "otra.db"
    assert {"documento": "glosas", "copiadas": 1} in construir.construir(otra, [FUENTE], resoluciones=[])
    c = cambio(otra)
    assert (c["efecto"], c["efecto_generado"], c["resumen"], c["modelo"]) == ("▼", True, "Cambia viejo por nuevo.", "falso")


def test_baker_caido_deja_todo_en_null(db, monkeypatch):
    monkeypatch.setenv("BAKER_CAIDO", "1")
    with closing(almacen.abrir(db)) as con:
        r = glosas.glosar(con, "2024-01-01")
    assert r["hechas"] == 0 and "Ningún modelo cabe" in r["error"]
    cache = glosas.Cache()
    assert cache.filas() == []
    cache.close()


def test_entrada_sin_saltos_de_renglon():
    """El PDF original y la compilada cortan renglones distinto: el Baker no ve esos cambios."""
    n = {"titulo": "Decreto", "publicado_dof": "2024-04-01"}
    e = glosas.entrada(n, {"documento": "X", "nombre": "Ley X"}, "1o", "uno dos\ntres cuatro", "uno dos tres\ncinco")
    assert "uno dos tres [-cuatro-]{+cinco+}" in e
