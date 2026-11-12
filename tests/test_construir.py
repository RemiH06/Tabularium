"""Construcción de versiones, inmutabilidad (RF-04) y citas en las tres herramientas del MCP (RF-10)."""
import asyncio
import sqlite3
from contextlib import closing

import pytest
from mcp.client.client import Client

from tabularium import almacen, construir
from tabularium.ley import segmentar
from tabularium.servidor import crear_servidor

from test_ley import LEY

BASE = LEY.replace("Artículo 2o.- Texto nuevo.\nArtículo reformado DOF 01-04-2024", "Artículo 2o.- Texto viejo.")
FUENTE = construir.Fuente("LDP", "Ley de prueba", "https://ejemplo/base.doc", "https://ejemplo/actual.doc")
CAMPOS_RF10 = ("documento", "unidad", "vigente_desde", "decreto_dof", "fuente_url")


@pytest.fixture
def db(tmp_path, monkeypatch):
    textos = {FUENTE.base_url: BASE, FUENTE.actual_url: LEY}
    monkeypatch.setattr(construir, "leer", lambda url: segmentar(textos[url]))
    ruta = tmp_path / "t.db"
    resumen = construir.construir(ruta, [FUENTE])
    assert resumen[0]["reformados_desde_corte"] == ["2o"]
    return ruta


def test_rf04_dos_fechas_dos_textos(db):
    with closing(almacen.abrir(db)) as con:
        antes = almacen.articulo(con, "ldp", "Artículo 2o", "2024-04-01")
        despues = almacen.articulo(con, "LDP", "2o.", "2024-04-02")
        assert antes["texto"] == "Artículo 2o.- Texto viejo."
        assert despues["texto"] == "Artículo 2o.- Texto nuevo."
        assert antes["cita"]["vigente_hasta"] == despues["cita"]["vigente_desde"] == "2024-04-02"
        assert despues["cita"]["decreto_dof"] == "DOF-2024-04-01"
        assert despues["cita"]["publicado_dof"] == "2024-04-01"
        assert [v["cita"]["vigente_desde"] for v in almacen.versiones(con, "LDP", "2o")] == ["2024-01-01", "2024-04-02"]
        # Sin reformas, la base cita su última reforma anterior al corte.
        assert almacen.articulo(con, "LDP", "1o")["cita"]["decreto_dof"] == "DOF-1998-12-31"


def test_rf04_versiones_inmutables(db):
    with closing(sqlite3.connect(db)) as con:
        for orden in ("UPDATE versiones SET texto = 'x'", "DELETE FROM versiones",
                      "UPDATE versiones SET vigente_hasta = '2030-01-01' WHERE vigente_hasta IS NOT NULL"):
            with pytest.raises(sqlite3.IntegrityError):
                con.execute(orden)


def test_consultas_invalidas(db):
    with closing(almacen.abrir(db)) as con:
        with pytest.raises(ValueError, match="2024-01-01"):
            almacen.articulo(con, "LDP", "1o", "2023-12-31")
        with pytest.raises(LookupError):
            almacen.articulo(con, "LDP", "99")
        # Lo que escribe el usuario no se interpreta como sintaxis de FTS5.
        assert almacen.buscar(con, 'obligadas" OR NEAR(') != []


def test_rf10_cita_completa_en_las_tres_herramientas(db):
    llamadas = [("articulo", {"documento": "LDP", "unidad": "2o"}),
                ("articulo", {"documento": "DOF-2024-04-01", "unidad": "Transitorio Único"}),
                ("versiones", {"documento": "LDP", "unidad": "2o"}),
                ("buscar", {"consulta": "impuesto obligados"})]

    async def correr():
        async with Client(crear_servidor(db)) as cliente:
            return [await cliente.call_tool(n, a) for n, a in llamadas]

    for (nombre, _), r in zip(llamadas, asyncio.run(correr())):
        assert not r.is_error, (nombre, r.content)
        datos = r.structured_content
        resultados = datos["result"] if "result" in datos else [datos]
        assert resultados, nombre
        for res in resultados:
            assert all(res["cita"][c] for c in CAMPOS_RF10), (nombre, res["cita"])
