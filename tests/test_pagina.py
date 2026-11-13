"""RF-12: la página pública de Novellae."""
from starlette.testclient import TestClient

from tabularium.pagina import CABECERAS, crear_app

from test_construir import db  # noqa: F401 (fixture: ley de prueba con el art. 2o reformado)


def test_novella_con_diff_cita_y_aviso(db):
    r = TestClient(crear_app(db)).get("/", params={"desde": "2024-01-01", "hasta": "2024-12-31"})
    assert r.status_code == 200
    assert "<del>viejo.</del>" in r.text and "<ins>nuevo.</ins>" in r.text
    assert "LDP, art. 2o" in r.text and "no sustituye a un abogado" in r.text
    assert all(r.headers[k] == v for k, v in CABECERAS.items())


def test_filtro_por_documento(db):
    cliente = TestClient(crear_app(db))
    rango = {"desde": "2024-01-01", "hasta": "2024-12-31"}
    assert "<ins>nuevo.</ins>" in cliente.get("/", params={**rango, "documento": "LDP"}).text
    otro = cliente.get("/", params={**rango, "documento": "CFF"}).text
    assert "<ins>" not in otro and "No hay publicaciones" in otro


def test_fecha_invalida_y_texto_escapado(db):
    cliente = TestClient(crear_app(db))
    r = cliente.get("/", params={"desde": "<script>"})
    assert r.status_code == 400 and "<script>" not in r.text
    r = cliente.get("/", params={"documento": "<script>alert(1)</script>"})
    assert r.status_code == 200 and "<script>" not in r.text


def test_estilo(db):
    r = TestClient(crear_app(db)).get("/estilo.css")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/css")


def test_filtrar_da_lo_mismo_que_novellae(db):
    """La página filtra en memoria; debe coincidir con la consulta directa (la que usa el MCP)."""
    from contextlib import closing
    from tabularium import almacen
    from tabularium.novellae import novellae
    from tabularium.pagina import _filtrar, _todas
    todas, _ = _todas(db)
    with closing(almacen.abrir(db)) as con:
        for desde, hasta, doc in [("2024-01-01", "2024-12-31", None), ("2024-01-01", "2026-12-31", "LDP"),
                                  ("2025-01-01", "2025-12-31", None), ("2024-01-01", "2026-12-31", "CFF")]:
            assert _filtrar(todas, desde, hasta, doc) == novellae(con, desde, hasta, doc)
