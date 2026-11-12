"""Construcción de versiones, inmutabilidad (RF-04) y citas en las tres herramientas del MCP (RF-10)."""
import asyncio
import sqlite3
from contextlib import closing
from datetime import date

import pytest
from mcp.client.client import Client

from tabularium import almacen, construir
from tabularium.ley import segmentar
from tabularium.servidor import crear_servidor
from tabularium.vigencias import Intermedia

from test_ley import LEY

BASE = LEY.replace("Artículo 2o.- Texto nuevo.\nArtículo reformado DOF 01-04-2024", "Artículo 2o.- Texto viejo.")
FUENTE = construir.Fuente("LDP", "Ley de prueba", "https://ejemplo/base.doc", "https://ejemplo/actual.doc")
CAMPOS_RF10 = ("documento", "unidad", "vigente_desde", "decreto_dof", "fuente_url")


@pytest.fixture
def db(tmp_path, monkeypatch):
    textos = {FUENTE.base_url: BASE, FUENTE.actual_url: LEY}
    monkeypatch.setattr(construir, "leer", lambda url: segmentar(textos[url]))
    ruta = tmp_path / "t.db"
    resumen = construir.construir(ruta, [FUENTE], resoluciones=[])
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


SEGUNDA = """
DECRETO por el que se reforma otra vez la Ley de prueba.
Publicado en el Diario Oficial de la Federación el 1 de julio de 2024
Transitorio
Único.- El presente Decreto entrará en vigor el día siguiente al de su publicación en el Diario Oficial de la Federación.
Ciudad de México, a 20 de junio de 2024.- Firmas.
"""
DOS_REFORMAS = LEY.replace("Texto nuevo.\nArtículo reformado DOF 01-04-2024",
                           "Texto final.\nArtículo reformado DOF 01-04-2024, 01-07-2024") + SEGUNDA


def _construir(tmp_path, monkeypatch, actual: str):
    textos = {FUENTE.base_url: BASE, FUENTE.actual_url: actual}
    monkeypatch.setattr(construir, "leer", lambda url: segmentar(textos[url]))
    construir.construir(tmp_path / "t.db", [FUENTE], resoluciones=[])
    return tmp_path / "t.db"


def test_r10_version_intermedia(tmp_path, monkeypatch):
    with pytest.raises(ValueError, match="INTERMEDIAS"):  # sin reconstrucción no se adivina el texto intermedio
        _construir(tmp_path, monkeypatch, DOS_REFORMAS)
    i = Intermedia("LDP", "2o", date(2024, 4, 2), (("Texto final.", "Texto nuevo."),), "https://ejemplo/dof")
    monkeypatch.setattr(construir, "intermedia", lambda d, u, desde: i if (d, u, desde) == ("LDP", "2o", i.desde) else None)
    with closing(almacen.abrir(_construir(tmp_path, monkeypatch, DOS_REFORMAS))) as con:
        vs = almacen.versiones(con, "LDP", "2o")
    assert [(v["texto"], v["cita"]["vigente_desde"], v["cita"]["vigente_hasta"]) for v in vs] == [
        ("Artículo 2o.- Texto viejo.", "2024-01-01", "2024-04-02"),
        ("Artículo 2o.- Texto nuevo.", "2024-04-02", "2024-07-02"),
        ("Artículo 2o.- Texto final.", "2024-07-02", None)]
    assert vs[1]["cita"]["fuente_url"] == "https://ejemplo/dof"


def test_dos_decretos_el_mismo_dia(tmp_path, monkeypatch):
    mismo_dia = LEY + SEGUNDA.replace("1 de julio de 2024", "1 de abril de 2024")
    with pytest.raises(ValueError, match="MISMO_DIA"):  # la nota "DOF 01-04-2024" ya no dice a cuál remite
        _construir(tmp_path, monkeypatch, mismo_dia)
    monkeypatch.setattr(construir, "MISMO_DIA", {date(2024, 4, 1): "revisado"})
    with closing(almacen.abrir(_construir(tmp_path, monkeypatch, mismo_dia))) as con:
        assert almacen.articulo(con, "LDP", "2o")["cita"]["decreto_dof"] == "DOF-2024-04-01"
        # Los transitorios del segundo no se pierden: van a su propio id.
        assert almacen.articulo(con, "DOF-2024-04-01-2", "Transitorio Único")["unidad"] == "Transitorio Único"


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


class ModeloFalso:
    """Vector por conceptos: "descuenta" y "retener" caen en la misma dimensión sin compartir raíz."""
    CONCEPTOS = [("retener", "retienen", "descuenta"), ("impuesto", "pago"), ("sufijo",)]
    llamadas = 0

    def embeber(self, texto):
        import numpy as np
        ModeloFalso.llamadas += 1
        t = texto.lower()
        v = np.array([sum(t.count(p) for p in c) for c in self.CONCEPTOS] + [0.01], dtype=np.float32)
        return v / np.linalg.norm(v)


def test_busqueda_hibrida_y_cache_de_vectores(tmp_path, monkeypatch):
    from tabularium import vectores
    monkeypatch.setenv("TABULARIUM_CACHE", str(tmp_path / "cache"))
    monkeypatch.setattr(vectores, "modelo", lambda: ModeloFalso())
    textos = {FUENTE.base_url: BASE, FUENTE.actual_url: LEY}
    monkeypatch.setattr(construir, "leer", lambda url: segmentar(textos[url]))
    cache = vectores.Cache()
    construir.construir(tmp_path / "a.db", [FUENTE], resoluciones=[], vectores=cache)
    assert cache.nuevos > 0
    nuevos, cache.nuevos = cache.nuevos, 0
    construir.construir(tmp_path / "b.db", [FUENTE], resoluciones=[], vectores=cache)
    assert cache.nuevos == 0  # reconstruir no vuelve a embeber lo que ya está en la caché
    cache.close()
    with closing(almacen.abrir(tmp_path / "b.db")) as con:
        assert con.execute("SELECT count(*) FROM fragmentos").fetchone()[0] == nuevos
        # Sin ninguna palabra en común con el artículo: solo lo encuentran los vectores.
        r = almacen.buscar(con, "agente que descuenta", "2024-06-01")
        assert r[0]["unidad"] == "1o.-A" and r[0]["puntaje"] > 0
        assert all(x["cita"]["fuente_url"] for x in r)
