"""Texto para BM25 (raíces, vacías, siglas, años) y lectura del conjunto de evaluación."""
from tabularium import almacen, evaluacion, lexico


def test_consulta_raices_sin_vacias_ni_anos():
    assert lexico.consulta("¿Qué deducciones puedo aplicar en 2025?") == ["deduccion", "aplic"]
    assert lexico.raices("Las DEDUCCIONES autorizadas") == lexico.raices("deducciones autorizadas")


def test_siglas():
    assert {"comprob", "digital"} <= set(lexico.consulta("requisitos del CFDI"))
    assert lexico.mencionados("¿Cuándo se retiene el IVA?") == {"LIVA"}
    assert lexico.mencionados("ISR e IVA") == {"LISR", "LIVA"}
    assert lexico.mencionados("la ivabilidad") == set()


def test_referencias_exactas():
    assert lexico.referencias("art. 27 fracción V LISR") == [("LISR", "27")]
    assert [(d, almacen.clave(u)) for d, u in lexico.referencias("artículo 5o.-A del CFF")] == [("CFF", "5a")]
    assert lexico.referencias("Artículo 17-H Bis del Código Fiscal de la Federación") == [("CFF", "17-H Bis")]
    assert lexico.referencias("art. 27") == []  # sin ley: el número existe en las tres
    assert lexico.referencias("artículo 1 de la LIVA y del ISR") == []


def test_conjunto_de_evaluacion():
    preguntas, callar = evaluacion.leer()
    assert len(preguntas) == 55 and len(callar) == 18
    p = {q.n: q for q in preguntas}
    assert p["39"].claves == {"iareceptor"} and p["53"].documento == "RMF2026-A8" and p["53"].claves == {"cii"}
    assert p["41"].claves == {"113e", "100"}
    assert p["19"].claves == {"17hbis"} and p["24"].version == "sin nota" and p["22"].version == "2023-12-29"
    hit = {"titulo_decreto": "x", "cita": {"vigente_desde": "2024-01-01", "vigente_hasta": None,
                                           "publicado_dof": "2023-12-30"}}
    assert not evaluacion.version_correcta(hit, p["22"])  # otra reforma
    hit["cita"]["publicado_dof"] = "2023-12-29"
    assert evaluacion.version_correcta(hit, p["22"])


def test_expandir_siglas():
    assert lexico.expandir("¿Cuál es la tasa general del IVA?") == "¿Cuál es la tasa general del IVA? (impuesto valor agregado)"
    assert lexico.expandir("tasa del 16%") == "tasa del 16%"
    assert {"impuest", "valor", "agreg", "iva"} <= set(lexico.consulta("tasa del IVA"))
