"""RF-01: con dos corridas seguidas sin reformas de por medio, la segunda no baja ningún documento.

El sitio se simula con los archivos reales de la caché, copiados a una caché temporal."""
import shutil

import pytest

from tabularium import construir, descarga

REAL = {u: construir.ruta_cache(u) for f in construir.FUENTES for u in (f.base_url, f.actual_url)}
REAL[descarga.INDICE] = construir.ruta_cache(descarga.INDICE)
pytestmark = pytest.mark.skipif(not all(r.exists() for r in REAL.values()), reason="sin caché de documentos fuente")


class SitioFalso(descarga.Cliente):
    """Sirve los archivos de la caché real; `indice` permite simular una reforma nueva."""

    def __init__(self, indice: bytes | None = None):
        super().__init__(pausa=0)
        self.indice = indice

    def bajar(self, url):
        ruta = construir.ruta_cache(url)
        ruta.parent.mkdir(parents=True, exist_ok=True)
        if url == descarga.INDICE and self.indice is not None:
            ruta.write_bytes(self.indice)
        else:
            shutil.copyfile(REAL[url], ruta)
        self.bajados.append(url)
        return ruta


@pytest.fixture
def cache_vacia(tmp_path, monkeypatch):
    monkeypatch.setenv("TABULARIUM_CACHE", str(tmp_path))


def test_indice_real():
    html = REAL[descarga.INDICE].read_bytes().decode("iso-8859-1")
    fechas = descarga.ultimas_reformas(html, ["LIVA", "LISR", "CFF"])
    assert fechas["LIVA"].isoformat() == "2021-11-12"
    assert fechas["CFF"].isoformat() == "2026-04-09"


def test_rf01_segunda_corrida_sin_descargas(cache_vacia):
    primera = descarga.actualizar(cliente=SitioFalso())
    assert len(primera["documentos"]) == 5  # tres leyes y dos copias base
    assert primera["reconstruir"]
    segunda = descarga.actualizar(cliente=SitioFalso())
    assert segunda["documentos"] == [] and not segunda["reconstruir"]


def test_rf01_baja_solo_la_reformada(cache_vacia):
    descarga.actualizar(cliente=SitioFalso())
    html = REAL[descarga.INDICE].read_bytes().decode("iso-8859-1")
    # El índice anuncia una reforma nueva a la LISR que el documento todavía no trae.
    i = html.index('href="ref/lisr.htm"')
    fila = html[i:html.index('href="doc/LISR.doc"', i)]
    otro = html.replace(fila, fila.replace("DOF 01/04/2024", "DOF 02/01/2027"), 1).encode("iso-8859-1")
    r = descarga.actualizar(cliente=SitioFalso(otro))
    assert r["documentos"] == [construir.LEYES_BIBLIO.format("LISR")]
    assert r["leyes"]["LISR"]["aviso"]  # el documento bajado sigue en la fecha vieja
