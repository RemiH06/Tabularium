"""Pruebas sobre los documentos reales de la caché. Se saltan si la caché no está (no se versiona)."""
import re
from contextlib import closing

import pytest

from tabularium import almacen, construir
from tabularium.doc import texto_doc
from tabularium.ley import segmentar

LIVA_DOC = construir.ruta_cache(construir.LEYES_BIBLIO.format("LIVA"))
LIVA_PDF = construir.ruta_cache("https://www.diputados.gob.mx/LeyesBiblio/pdf/LIVA.pdf")
pytestmark = pytest.mark.skipif(not LIVA_DOC.exists(), reason="sin caché de documentos fuente")


@pytest.fixture(scope="module")
def db(tmp_path_factory):
    ruta = tmp_path_factory.mktemp("real") / "tabularium.db"
    resumen = {r["documento"]: r for r in construir.construir(ruta)}
    assert resumen["LIVA"]["reformados_desde_corte"] == []
    assert resumen["LISR"]["reformados_desde_corte"] == ["79"]  # DOF 01-04-2024, ver plan.md sección 11
    return ruta


def test_rf02_conteos():
    for ley, n in (("LIVA", 79), ("LISR", 236)):
        ids = [u.id for u in construir.leer(construir.LEYES_BIBLIO.format(ley)).articulos]
        assert len(ids) == len(set(ids)) == n


@pytest.mark.skipif(not LIVA_PDF.exists(), reason="sin el PDF de LIVA")
def test_rf02_liva_igual_al_pdf():
    """Los 79 artículos contra el PDF, una extracción independiente, sin contar espacios."""
    pymupdf = pytest.importorskip("pymupdf")
    with pymupdf.open(LIVA_PDF) as pdf:  # sin el encabezado "n de m" de cada página
        texto = "\n".join(re.sub(r"^[\s\S]{0,600}?\n\s*\d+ de \d+\s*\n", "", p.get_text(), count=1) for p in pdf)
    del_pdf = {u.id: u.texto for u in segmentar(texto).articulos}
    plano = lambda s: re.sub(r"[\s\-‐\xad]", "", s)  # noqa: E731
    distintos = {u.id for u in segmentar(texto_doc(LIVA_DOC)).articulos if plano(u.texto) != plano(del_pdf.get(u.id, ""))}
    # Defectos del PDF, no del .doc: notas de reforma partidas en dos renglones (que no se reconocen
    # como nota) y restos del encabezado de página. Revisados a mano el 2026-11-12.
    assert distintos <= {"4o.-B", "5o", "18-A", "32"}


def test_rf04_lisr_79(db):
    with closing(almacen.abrir(db)) as con:
        antes = almacen.articulo(con, "LISR", "79", "2024-04-01")
        despues = almacen.articulo(con, "LISR", "79", "2024-04-02")
    assert antes["texto"] != despues["texto"]
    assert "afromexicanas" in despues["texto"] and "afromexicanas" not in antes["texto"]
    assert despues["cita"]["decreto_dof"] == "DOF-2024-04-01"
    assert antes["cita"]["decreto_dof"] != despues["cita"]["decreto_dof"]


def test_r03_tarifas_en_imagen_quedan_marcadas(db):
    """La tarifa del art. 96 LISR es una imagen en el .doc y en el PDF: el texto debe decirlo."""
    from tabularium.doc import MARCA_IMAGEN
    with closing(almacen.abrir(db)) as con:
        texto = almacen.articulo(con, "LISR", "96")["texto"]
    assert f"la siguiente: {MARCA_IMAGEN}" in texto


def test_rf10_ninguna_version_sin_cita(db):
    with closing(almacen.abrir(db)) as con:
        filas = con.execute(f"SELECT {almacen._COLUMNAS} FROM {almacen._JOIN}").fetchall()
    assert len(filas) > 400
    for f in filas:
        assert all(almacen.cita(f)[c] for c in ("documento", "unidad", "vigente_desde", "decreto_dof", "fuente_url"))
