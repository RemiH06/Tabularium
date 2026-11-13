"""RF-11 (lo objetivo de cada Novella) y la herramienta `novellae` del MCP (RF-09)."""
import asyncio
import sqlite3
from contextlib import closing

import pytest
from mcp.client.client import Client

from tabularium import almacen
from tabularium.novellae import diff, novellae, recortar
from tabularium.servidor import crear_servidor

from test_construir import CAMPOS_RF10, db  # noqa: F401 (fixture: ley de prueba con el art. 2o reformado)

CASOS = [
    ("", "Texto nuevo."),
    ("Texto viejo.", ""),
    ("Artículo 2o.- Texto viejo.", "Artículo 2o.- Texto nuevo."),
    ("I. Uno;\nII. Dos.", "I. Uno;\nII. Dos;\nIII. Tres."),
    ("a  b\tc ", "a b\tc"),  # solo cambian espacios
    ("la tasa es del 16%", "la tasa es del 16%"),
]


@pytest.mark.parametrize("viejo, nuevo", CASOS)
def test_diff_reproduce_las_dos_versiones(viejo, nuevo):
    d = diff(viejo, nuevo)
    assert "".join(t for op, t in d if op != "+") == viejo
    assert "".join(t for op, t in d if op != "-") == nuevo


def test_recortar_conserva_los_cambios():
    viejo = " ".join(f"p{i}" for i in range(100))
    d = diff(viejo, viejo.replace("p50", "q50"))
    corto = recortar(d, contexto=3)
    assert [x for x in corto if x[0] != "="] == [("-", "p50 "), ("+", "q50 ")]
    assert corto[0] == ("=", "[…] p47 p48 p49 ") and corto[-1][1].startswith("p51 p52 p53 […]")


def test_novella_de_la_ley_de_prueba(db):
    with closing(almacen.abrir(db)) as con:
        [n] = [x for x in novellae(con, "2024-01-01", "2024-12-31") if x["decreto_dof"] == "DOF-2024-04-01"]
    [documento] = n["documentos"]
    [cambio] = documento["cambios"]
    assert (documento["documento"], cambio["unidad"], cambio["efecto"]) == ("LDP", "2o", None)
    assert ("-", "viejo.") in cambio["diff"] and ("+", "nuevo.") in cambio["diff"]
    assert all(cambio["cita"][c] for c in CAMPOS_RF10) and all(cambio["anterior"][c] for c in CAMPOS_RF10)
    assert n["transitorios"] == ["Transitorio Único"] and not n["pendiente"]


def test_pendiente_hasta_que_llega_el_texto(db):
    con = sqlite3.connect(db)
    with con:
        con.execute("DELETE FROM publicaciones")
        con.executemany("INSERT INTO publicaciones VALUES (?, ?, 'matutina', ?, 'LDP', ?)", [
            (1, "2024-04-01", "Decreto que reforma la LDP", "https://dof/1"),  # ya tiene versiones
            (2, "2026-10-05", "Decreto que reforma otra vez la LDP", "https://dof/2")])
    con.close()
    with closing(almacen.abrir(db)) as con:
        todas = novellae(con, "2024-01-01", "2026-12-31")
        assert [(n["publicado_dof"], n["fuente_url"]) for n in todas if n["pendiente"]] == [("2026-10-05", "https://dof/2")]
        assert next(n for n in todas if n["decreto_dof"] == "DOF-2024-04-01")["fuente_url"] == "https://dof/1"
        assert novellae(con, "2026-01-01", "2026-12-31", "CFF") == []


def test_herramienta_mcp(db):
    async def correr():
        async with Client(crear_servidor(db)) as cliente:
            return (await cliente.call_tool("novellae", {"desde": "2024-01-01", "documento": "LDP"}),
                    await cliente.call_tool("novellae", {"desde": "ayer"}))

    bien, mal = asyncio.run(correr())
    assert not bien.is_error and bien.structured_content["result"][0]["decreto_dof"] == "DOF-2024-04-01"
    assert mal.is_error
