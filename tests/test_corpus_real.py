"""Pruebas sobre los documentos reales de la caché. Se saltan si la caché no está (no se versiona)."""
import html
import re
from contextlib import closing

import pytest

from tabularium import almacen, construir
from tabularium.doc import texto_doc
from tabularium.ley import segmentar
from tabularium.vigencias import INTERMEDIAS

LIVA_DOC = construir.ruta_cache(construir.LEYES_BIBLIO.format("LIVA"))
LIVA_PDF = construir.ruta_cache("https://www.diputados.gob.mx/LeyesBiblio/pdf/LIVA.pdf")
CFF_PDF = construir.ruta_cache("https://www.diputados.gob.mx/LeyesBiblio/pdf/CFF.pdf")
CFF_PDF_2025 = construir.ruta_cache(
    "https://web.archive.org/web/20250404183204id_/https://www.diputados.gob.mx/LeyesBiblio/pdf/CFF.pdf")
pytestmark = pytest.mark.skipif(not LIVA_DOC.exists(), reason="sin caché de documentos fuente")


def plano(s: str) -> str:
    """Sin espacios ni guiones, ni las fechas de notas que el PDF parte en dos renglones ("30-12-2024")."""
    return re.sub(r"[0-3]\d[01]\d(?:19|20)\d\d", "", re.sub(r"[\s\-‐\xad]", "", s))


def texto_pdf(ruta) -> str:
    pymupdf = pytest.importorskip("pymupdf")
    with pymupdf.open(ruta) as pdf:  # sin el encabezado "n de m" de cada página
        return "\n".join(re.sub(r"^[\s\S]{0,600}?\n\s*\d+ de \d+\s*\n", "", p.get_text(), count=1) for p in pdf)


def distintos_del_pdf(textos: dict[str, str], ruta) -> set[str]:
    """Artículos cuyo texto no coincide con el del PDF, una extracción independiente."""
    del_pdf = {u.id: u.texto for u in segmentar(texto_pdf(ruta)).articulos}
    assert textos.keys() == del_pdf.keys()
    return {i for i, t in textos.items() if plano(t) != plano(del_pdf[i])}


def vigente(con, documento: str, unidad: str, fecha: str) -> str:
    return almacen.articulo(con, documento, unidad, fecha)["texto"]


@pytest.fixture(scope="module")
def db(tmp_path_factory):
    ruta = tmp_path_factory.mktemp("real") / "tabularium.db"
    resumen = {r["documento"]: r for r in construir.construir(ruta)}
    assert resumen["LIVA"]["reformados_desde_corte"] == []
    assert resumen["LISR"]["reformados_desde_corte"] == ["79"]  # DOF 01-04-2024, ver plan.md sección 11
    assert len(resumen["CFF"]["reformados_desde_corte"]) == 54  # 50 reformados y 4 adicionados, sección 13
    return ruta


def test_rf02_conteos():
    for ley, n in (("LIVA", 79), ("LISR", 236), ("CFF", 421)):
        ids = [u.id for u in construir.leer(construir.LEYES_BIBLIO.format(ley)).articulos]
        assert len(ids) == len(set(ids)) == n


@pytest.mark.skipif(not LIVA_PDF.exists(), reason="sin el PDF de LIVA")
def test_rf02_liva_igual_al_pdf():
    distintos = distintos_del_pdf({u.id: u.texto for u in segmentar(texto_doc(LIVA_DOC)).articulos}, LIVA_PDF)
    # Defectos del PDF, no del .doc: notas de reforma partidas en dos renglones (que no se reconocen
    # como nota) y restos del encabezado de página. Revisados a mano el 2026-11-12.
    assert distintos <= {"4o.-B", "5o", "18-A", "32"}


@pytest.mark.skipif(not CFF_PDF.exists(), reason="sin el PDF del CFF")
def test_rf02_cff_igual_al_pdf():
    cff = construir.leer(construir.LEYES_BIBLIO.format("CFF"))
    # 20-Ter: la fórmula de la UDI es imagen en el .doc; el PDF la omite sin aviso.
    assert distintos_del_pdf({u.id: u.texto for u in cff.articulos}, CFF_PDF) <= {"20-Ter"}


@pytest.mark.skipif(not CFF_PDF_2025.exists(), reason="sin la copia del CFF de 2025")
def test_r10_cff_reconstruido_igual_a_la_copia_de_2025(db):
    """Todo el CFF vigente el 2025-04-04, versiones intermedias incluidas, contra la copia en PDF de
    esa fecha: una fuente que la construcción no usa."""
    with closing(almacen.abrir(db)) as con:
        textos = dict(con.execute(
            "SELECT unidad, texto FROM versiones WHERE documento = 'CFF' AND tipo = 'articulo' "
            "AND vigente_desde <= '2025-04-04' AND (vigente_hasta IS NULL OR vigente_hasta > '2025-04-04')").fetchall())
    # 20-Ter: fórmula en imagen. 17-F: la Cámara completó después la anotación de invalidez de la
    # SCJN ("y publicada DOF 04-03-2024"), que va dentro del texto y no como nota.
    assert distintos_del_pdf(textos, CFF_PDF_2025) <= {"20-Ter", "17-F"}


def test_intermedias_literales_en_su_fuente():
    for i in INTERMEDIAS:
        ruta = construir.ruta_cache(i.fuente_url)
        if not ruta.exists():
            pytest.skip(f"sin {ruta}")
        if i.fuente_url.endswith(".pdf"):
            fuente = texto_pdf(ruta)
        else:
            fuente = html.unescape(re.sub(r"<[^>]+>", " ", ruta.read_text(encoding="utf-8")))
        for _, viejo in i.cambios:
            assert plano(viejo) in plano(fuente), (i.unidad, viejo[:60])


def test_cff_versiones_por_fecha(db):
    """Preguntas temporales 13 a 25 del conjunto de prueba y casos límite A y B."""
    with closing(almacen.abrir(db)) as con:
        assert "existentes, verdaderas" not in vigente(con, "CFF", "29-A", "2025-06-01")
        assert "existentes, verdaderas" in vigente(con, "CFF", "29-A", "2026-03-01")
        assert "firmes" not in vigente(con, "CFF", "17-H Bis", "2025-06-01")
        assert "firmes" in vigente(con, "CFF", "17-H Bis", "2026-06-01")
        assert "$1,810.00 a $22,400.00" in vigente(con, "CFF", "82", "2025-06-01")
        en_2026 = almacen.articulo(con, "CFF", "82", "2026-06-01")
        assert "$2,050.00 a $25,360.00" in en_2026["texto"]
        # Dos reformas que rigen el mismo día (DOF 07-11-2025 y 28-12-2025) dan una sola versión.
        assert en_2026["cita"]["decreto_dof"] == "DOF-2025-12-28"
        assert len(almacen.versiones(con, "CFF", "82")) == 2
        # Caso B: tres textos del art. 141; el de enero a abril de 2026 se reconstruyó del decreto.
        assert "Depósito en dinero" in vigente(con, "CFF", "141", "2025-12-31")
        intermedia = almacen.articulo(con, "CFF", "141", "2026-02-01")
        assert "orden obligatorio" in intermedia["texto"]
        assert intermedia["cita"]["vigente_hasta"] == "2026-04-10"
        assert intermedia["notas"].startswith("Versión reconstruida")
        assert "en alguna de las formas siguientes" in vigente(con, "CFF", "141", "2026-04-10")
        # Caso A: el art. 30-B se publicó el 2025-11-07, pero rige desde el 2026-04-01.
        with pytest.raises(LookupError):
            almacen.articulo(con, "CFF", "30-B", "2026-03-31")
        assert almacen.articulo(con, "CFF", "30-B", "2026-04-01")["cita"]["decreto_dof"] == "DOF-2025-11-07"
        # Sin nota de reforma en la fuente, la cita no inventa la fecha de la última.
        assert "sin nota de reforma en la fuente" in almacen.articulo(con, "CFF", "146")["cita"]["texto"]


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


def test_rf08_exacta_primero(db):
    with closing(almacen.abrir(db)) as con:
        for consulta, doc, unidad in [("art. 27 fracción V LISR", "LISR", "27"), ("artículo 5o.-A del CFF", "CFF", "5o.-A")]:
            primero = almacen.buscar(con, consulta, "2026-11-10")[0]
            assert (primero["documento"], primero["unidad"], primero["puntaje"]) == (doc, unidad, None)
            assert all(primero["cita"][c] for c in ("documento", "unidad", "vigente_desde", "decreto_dof", "fuente_url"))
        r = almacen.buscar(con, "deducciones de personas morales", "2026-11-10")
        assert len(r) == 5 and all(x["fragmento"] and x["puntaje"] > 0 for x in r)
        assert "«" in r[0]["fragmento"]  # la raíz resalta la palabra completa en el texto literal
