"""RF-15: `preguntar` cita o calla, verificado por código (R-12)."""
from contextlib import closing

import pytest

from tabularium import almacen
from tabularium.glosas import BakerCaido
from tabularium.preguntar import LARGO_MAXIMO, PASAJE, TROZOS, pasaje, pesos, preguntar, vigente, verificar

from test_construir import db  # noqa: F401 (fixture: ley de prueba con el art. 2o reformado el 2024-04-02)

NUEVO = "Artículo 2o.- Texto nuevo."


def _baker(*salidas):
    """Baker falso: devuelve las salidas en orden y guarda lo que leyó."""
    vistas = []

    def llamar(tarea, archivo):
        vistas.append((tarea, open(archivo, encoding="utf-8").read()))
        return salidas[min(len(vistas), len(salidas)) - 1]
    llamar.vistas = vistas
    return llamar


def _r(citas, respuesta="El artículo 2o de la LDP dice texto nuevo.", no_encontrado=False):
    return {"citas": citas, "no_encontrado": no_encontrado, "respuesta": respuesta}


def test_responde_con_la_cita_de_la_version_vigente(db):
    llamar = _baker(_r(["Artículo 2o.-  Texto\nnuevo."]))  # solo cambian espacios
    with closing(almacen.abrir(db)) as con:
        r = preguntar(con, "texto nuevo", "2024-05-01", llamar)
        [c] = r.citas
        assert r.texto and not r.callar and r.intentos == 1
        assert (c.cita["documento"], c.cita["unidad"], c.cita["vigente_desde"]) == ("LDP", "2o", "2024-04-02")
        assert vigente(con, c.cita, "2024-05-01") and not vigente(con, c.cita, "2024-03-01")
    tarea, contexto = llamar.vistas[0]
    assert "2024-05-01" in tarea and NUEVO in contexto and "LDP, art. 2o" in contexto


def test_la_fecha_elige_la_version(db):
    llamar = _baker(_r([NUEVO]))
    with closing(almacen.abrir(db)) as con:
        r = preguntar(con, "texto nuevo", "2024-03-01", llamar)
    # El 2024-03-01 rige "Texto viejo.": la cita del texto nuevo no aparece y no hay respuesta.
    assert r.callar and not r.texto and not r.citas and r.intentos == 2


def test_reintenta_y_si_corrige_responde(db):
    llamar = _baker(_r(["Artículo 2o.- Texto inventado."]), _r([NUEVO]))
    with closing(almacen.abrir(db)) as con:
        r = preguntar(con, "texto nuevo", "2024-05-01", llamar)
    assert r.texto and r.intentos == 2 and "Texto inventado" in llamar.vistas[1][0]


def test_una_cita_mala_basta_para_callar(db):
    llamar = _baker(_r([NUEVO, "una frase que no está en la ley"]))
    with closing(almacen.abrir(db)) as con:
        r = preguntar(con, "texto nuevo", "2024-05-01", llamar)
    assert r.callar and not r.texto and not r.citas


@pytest.mark.parametrize("salida", [_r([], "", True), _r([], "Sí, puedes."), _r([NUEVO], "")])
def test_sin_citas_o_sin_texto_calla(db, salida):
    with closing(almacen.abrir(db)) as con:
        r = preguntar(con, "texto nuevo", "2024-05-01", _baker(salida))
    assert r.callar and not r.texto


def test_baker_caido_deja_los_resultados_de_buscar(db):
    def caido(tarea, archivo):
        raise BakerCaido("Pixilate apagada")
    with closing(almacen.abrir(db)) as con:
        r = preguntar(con, "texto nuevo", "2024-05-01", caido)
    assert r.fallo == "Pixilate apagada" and not r.texto and r.pasajes
    assert all(p["cita"]["fuente_url"] for p in r.pasajes)


def test_fuera_de_esquema_es_fallo(db):
    with closing(almacen.abrir(db)) as con:
        r = preguntar(con, "texto nuevo", "2024-05-01", _baker({"otra": 1}))
    assert r.fallo and not r.texto


def test_largo_de_la_pregunta(db):
    with closing(almacen.abrir(db)) as con, pytest.raises(ValueError):
        preguntar(con, "x" * (LARGO_MAXIMO + 1), None, _baker(_r([NUEVO])))
    with closing(almacen.abrir(db)) as con, pytest.raises(ValueError):
        preguntar(con, "   ", None, _baker(_r([NUEVO])))


def test_verificar_rechaza_citas_cortas_e_inventadas():
    cita = {"documento": "LDP", "unidad": "2o"}
    pasajes = [{"pasaje": "La tasa del impuesto será del 16% sobre el valor.", "cita": cita}]
    buenas, malas = verificar(["del impuesto será del 16%", "la tasa", "del impuesto será del 15%"], pasajes)
    assert [b.texto for b in buenas] == ["del impuesto será del 16%"] and buenas[0].cita is cita
    assert malas == ["la tasa", "del impuesto será del 15%"]


def test_pasaje_elige_el_trozo_con_la_raiz_rara():
    """El caso del art. 34 LISR: el trozo con "computadoras" debe ganarle al que solo trae palabras comunes."""
    comun = "Se aplica la deducción conforme a este artículo.\n"
    texto = "Párrafo de computadoras personales al 30%.\n" + comun * (3 * PASAJE // len(comun))
    otros = ["Se aplica la deducción en este otro artículo."] * 3
    peso = pesos([texto, *otros], {"comput", "aplic", "deduccion"})
    assert peso["comput"] > peso["deduccion"]
    elegido = pasaje(texto, peso)
    assert elegido.startswith("Párrafo de computadoras") and len(elegido) <= TROZOS * (PASAJE + 5)
    assert pasaje("Corto.", {}) == "Corto."


def test_una_cita_no_une_trozos_separados():
    cita = {"documento": "LDP", "unidad": "2o"}
    unido = "Primer trozo termina aquí.\n[…]\nSegundo trozo empieza aquí."
    buenas, malas = verificar(["termina aquí. Segundo trozo"], [{"pasaje": unido, "cita": cita}])
    assert not buenas and malas
