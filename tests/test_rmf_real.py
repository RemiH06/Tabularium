"""RMF 2024 a 2026 sobre los PDF reales de la caché (RF-03 y RF-04 para reglas). Se saltan sin caché."""
import collections
import re
from contextlib import closing

import pytest

from tabularium import almacen, construir, rmf

pytestmark = pytest.mark.skipif(not all(construir.ruta_cache(f.original).exists() for f in rmf.FUENTES_RMF),
                                reason="sin los PDF de la RMF en la caché")


@pytest.fixture(scope="module")
def db(tmp_path_factory):
    ruta = tmp_path_factory.mktemp("rmf") / "rmf.db"
    resumen = {r["documento"]: r for r in construir.construir(ruta)}  # con las leyes: las aristas las necesitan
    # Ruido: reglas cuyo texto cambia entre el original y una compilada sin marca de reforma (diferencias
    # de formato que quedan, plan.md sección 14). Se queda con el texto anterior; aquí solo se acota.
    for doc, tope in (("RMF2024", 40), ("RMF2025", 60), ("RMF2026", 10)):
        assert len({e.split("@")[0] for e in resumen[doc]["ruido"]}) <= tope, doc
    assert resumen["RMF2025"]["nuevas_sin_marca"] == ["2.8.3.7@2", "2.12.12@6"]
    return ruta


def test_rf03_sin_huecos_en_la_numeracion(db):
    """Dentro de cada capítulo o sección las reglas van de 1 a n sin saltos: no se perdió ninguna."""
    with closing(almacen.abrir(db)) as con:
        for doc, n in (("RMF2024", 1149), ("RMF2025", 1173), ("RMF2026", 1191)):
            ids = {u for (u,) in con.execute("SELECT DISTINCT unidad FROM versiones WHERE documento = ? AND tipo = 'regla'", (doc,))}
            assert len(ids) == n
            grupos = collections.defaultdict(set)
            for i in ids:
                padre, num = i.rsplit(".", 1)
                grupos[padre].add(int(num))
            assert all(ns == set(range(1, max(ns) + 1)) for ns in grupos.values()), doc


def test_rf03_muestra_igual_al_pdf(db):
    """20 reglas de la versión base de 2026 contra el texto plano del PDF original, extraído sin
    estilos ni segmentación (una extracción independiente)."""
    pymupdf = pytest.importorskip("pymupdf")
    f = rmf.FUENTES_RMF[2]
    with pymupdf.open(construir.ruta_cache(f.original)) as pdf:
        plano_pdf = construir._plano("\n".join(l for p in pdf for l in p.get_text().split("\n")
                                               if not rmf.ENCABEZADO_DOF.match(l.strip())))
    with closing(almacen.abrir(db)) as con:
        filas = con.execute("SELECT unidad, texto FROM versiones WHERE documento = 'RMF2026' AND tipo = 'regla' "
                            "AND vigente_desde = '2026-01-01' ORDER BY id").fetchall()
    muestra = filas[::len(filas) // 20][:20]
    assert len(muestra) == 20
    assert [u for u, t in muestra if construir._plano(t) not in plano_pdf] == []


def test_rf04_regla_por_modificacion(db):
    with closing(almacen.abrir(db)) as con:
        # 2026: la Primera RMRMF corrigió la fracción "II." repetida del original.
        antes = almacen.articulo(con, "RMF", "2.1.6", "2026-07-09")
        despues = almacen.articulo(con, "RMF", "2.1.6", "2026-07-10")
        assert antes["documento"] == despues["documento"] == "RMF2026"
        assert antes["texto"] != despues["texto"]
        assert despues["cita"]["decreto_dof"] == "DOF-2026-07-09-RMF2026"
        assert "Reformada en la Primera RMRMF" in despues["notas"]
        # 2024: tres versiones; la de la Segunda no tiene compilada y sale de su publicación en el DOF.
        v = almacen.versiones(con, "RMF2024", "2.1.6")
        assert [x["cita"]["vigente_desde"] for x in v] == ["2024-01-01", "2024-10-12", "2024-12-13"]
        assert v[1]["cita"]["fuente_url"] == rmf.FUENTES_RMF[0].publicadas[1]
        assert "transmisión del Poder Ejecutivo" in v[1]["texto"] and not v[1]["texto"].startswith("“")
        assert v[-1]["cita"]["vigente_hasta"] == "2025-01-01"


def test_regla_es_de_su_anio(db):
    """Pregunta 35: la cancelación de CFDI es la 2.7.1.47 en 2024 y la 2.7.1.46 en 2025."""
    with closing(almacen.abrir(db)) as con:
        assert "Plazo" in almacen.articulo(con, "RMF", "2.7.1.47", "2024-06-01")["texto"][:80]
        assert "Plazo" in almacen.articulo(con, "RMF", "2.7.1.46", "2025-06-01")["texto"][:80]
        primero = almacen.buscar(con, "regla 3.13.2 RMF 2026", "2026-11-10")[0]
        assert (primero["documento"], primero["unidad"], primero["puntaje"]) == ("RMF2026", "3.13.2", None)
        assert re.search(r"RMF2026, regla 3\.13\.2, vigente desde 2026-01-01 hasta 2027-01-01; Resolución",
                         primero["cita"]["texto"])


def test_rf10_reglas_con_cita(db):
    with closing(almacen.abrir(db)) as con:
        filas = con.execute(f"SELECT {almacen._COLUMNAS} FROM {almacen._JOIN}").fetchall()
    assert len(filas) > 4500
    for f in filas:
        assert all(almacen.cita(f)[c] for c in ("documento", "unidad", "vigente_desde", "decreto_dof", "fuente_url"))


def test_rf07_rf08_grafo(db):
    """La regla 2.7.1.25 reglamenta el art. 29-A del CFF; desde el artículo se ven las reglas de la RMF
    del año de la fecha, no las de otro año."""
    with closing(almacen.abrir(db)) as con:
        regla = almacen.articulo(con, "RMF", "2.7.1.25", "2026-06-01")
        assert {"relacion": "REGLAMENTA", "documento": "CFF", "unidad": "29-A"} in regla["relacionadas"]
        art = almacen.articulo(con, "CFF", "29-A", "2026-06-01")
        por = {(r["documento"], r["unidad"]) for r in art["relacionadas"] if r["relacion"] == "REGLAMENTADA_POR"}
        assert por and all(d == "RMF2026" for d, _ in por)
        # La ley no queda enterrada bajo sus reglas (pregunta 13 del conjunto de prueba).
        r = almacen.buscar(con, "¿Qué requisitos debía reunir un CFDI en 2025?", "2025-06-01")
        assert ("CFF", "29-A") in {(x["documento"], x["unidad"]) for x in r}
        assert all("relacionadas" in x for x in r)


def test_anexo_8_tarifas(db):
    """Las tarifas del ISR que la LISR trae como imagen (R-03) están en el Anexo 8 de cada año, y el
    artículo las ve por el grafo."""
    with closing(almacen.abrir(db)) as con:
        n = dict(con.execute("SELECT documento, count(DISTINCT unidad) FROM versiones WHERE documento LIKE '%-A8' GROUP BY 1"))
        assert n == {"RMF2024-A8": 41, "RMF2025-A8": 31, "RMF2026-A8": 31}  # 2024 trae las del subsidio para el empleo
        tarifa = almacen.articulo(con, "Anexo 8", "C.II", "2026-04-30")
        assert tarifa["texto"].splitlines()[2] == "0.01 | 10,135.11 | 0 | 1.92"
        assert tarifa["texto"].splitlines()[-1] == "5,107,703.93 | En adelante | 1,601,862.46 | 35.00"
        assert tarifa["cita"]["texto"].startswith("RMF2026-A8, sección C.II, vigente desde 2026-01-01 hasta 2027-01-01; "
                                                  "Anexo 8 de la Resolución Miscelánea Fiscal para 2026, publicado")
        art = almacen.articulo(con, "LISR", "152", "2026-04-30")
        assert {"relacion": "REGLAMENTADA_POR", "documento": "RMF2026-A8", "unidad": "C.II"} in art["relacionadas"]
        # 2025 no actualizó la tarifa anual; 2026 sí.
        assert almacen.articulo(con, "Anexo 8", "C.II", "2025-04-30")["texto"].splitlines()[2] == "0.01 | 8,952.49 | 0.00 | 1.92"


def test_anexo_29_versiones(db):
    """Cada año rige desde el día siguiente a su publicación y el anterior sigue hasta entonces
    (RMF 2026, Transitorio Segundo); cada modificación da versión nueva solo a lo que marca."""
    with closing(almacen.abrir(db)) as con:
        v = almacen.versiones(con, "RMF2026-A29", "VI.1")
        assert [(x["cita"]["vigente_desde"], x["cita"]["vigente_hasta"]) for x in v] == \
            [("2026-01-10", "2026-07-18"), ("2026-07-18", "2027-01-01")]
        assert v[1]["cita"]["decreto_dof"] == "DOF-2026-07-17-RMF2026-A29"
        assert "Atributo: “TipoDeComprobante”" in v[1]["texto"] and "Atributo: “TipoDeComprobante”" not in v[0]["texto"]
        assert "- Adicionado" not in v[1]["texto"]  # las marcas no son texto de la norma
        assert len(almacen.versiones(con, "RMF2026-A29", "VI.2")) == 1
        assert almacen.articulo(con, "Anexo 29", "VI.1", "2026-01-05")["documento"] == "RMF2025-A29"
        assert [x["cita"]["vigente_desde"] for x in almacen.versiones(con, "RMF2024-A29", "III.2")] == \
            ["2024-01-23", "2024-06-05", "2024-12-13"]


def test_anexo_20(db):
    """Preguntas 39 y 40: el estándar del CFDI es el Anexo 20 de la RMF 2022, prorrogado cada año; la
    guía de llenado sale del Portal del SAT y su cita lo dice."""
    with closing(almacen.abrir(db)) as con:
        receptor = almacen.articulo(con, "Anexo 20", "I.A Receptor", "2026-11-10")
        assert receptor["documento"] == "RMF2022-A20"
        assert "DomicilioFiscalReceptor" in receptor["texto"] and "[0-9]{5}" in receptor["texto"]
        assert receptor["cita"]["vigente_desde"] == "2022-01-14" and receptor["cita"]["vigente_hasta"] is None
        guia = almacen.articulo(con, "GUIA-A20", "I Comprobante", "2026-11-10")
        assert "FormaPago" in guia["texto"]
        assert guia["cita"]["texto"].endswith("versión del Portal del SAT del 2026-01-17 (no se publica en el DOF)")
        assert "sha256" in guia["notas"]
