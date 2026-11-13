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


# RF-15 y RNF-10 en la página.
from tabularium.glosas import BakerCaido  # noqa: E402
from tabularium.pagina import GLOBAL, POR_IP, VENTANA_IP, Limite  # noqa: E402

NUEVO = "Artículo 2o.- Texto nuevo."


def _llamar(citas, respuesta="El artículo 2o de la LDP dice texto nuevo."):
    return lambda tarea, archivo: {"citas": citas, "no_encontrado": not citas, "respuesta": respuesta}


def _preguntar(cliente, pregunta="texto nuevo", fecha="2024-05-01", **cabeceras):
    return cliente.post("/preguntar", data={"pregunta": pregunta, "fecha": fecha}, headers=cabeceras)


def test_preguntar_responde_con_citas(db):
    r = _preguntar(TestClient(crear_app(db, _llamar([NUEVO]))))
    assert r.status_code == 200 and "<blockquote>Artículo 2o.- Texto nuevo.</blockquote>" in r.text
    assert "LDP, art. 2o, vigente desde 2024-04-02" in r.text and "generado" in r.text
    assert TestClient(crear_app(db)).get("/preguntar").status_code == 200


def test_preguntar_calla_sin_citas_validas(db):
    r = _preguntar(TestClient(crear_app(db, _llamar(["algo que la ley no dice"]))))
    assert "no responde" in r.text and "<blockquote>" not in r.text and "El artículo 2o" not in r.text


def test_preguntar_con_el_baker_caido_muestra_la_busqueda(db):
    def caido(tarea, archivo):
        raise BakerCaido("Pixilate apagada")
    r = _preguntar(TestClient(crear_app(db, caido)))
    assert "No hay respuesta redactada" in r.text and "LDP, art. 2o" in r.text


def test_preguntar_valida_la_entrada(db):
    cliente = TestClient(crear_app(db, _llamar([NUEVO])))
    assert _preguntar(cliente, pregunta="").status_code == 400
    assert _preguntar(cliente, pregunta="x" * 501).status_code == 400
    assert _preguntar(cliente, fecha="2020-01-01").status_code == 400  # antes del corpus
    assert cliente.post("/preguntar", content=b"pregunta=" + b"x" * 5000,
                        headers={"content-type": "application/x-www-form-urlencoded"}).status_code == 413
    r = _preguntar(cliente, pregunta="<script>alert(1)</script> texto nuevo")
    assert "<script>" not in r.text


def test_preguntar_limite_por_ip(db):
    cliente = TestClient(crear_app(db, _llamar([NUEVO])))
    estados = [_preguntar(cliente, **{"cf-connecting-ip": "1.1.1.1"}).status_code for _ in range(POR_IP + 1)]
    assert estados == [200] * POR_IP + [429]
    assert _preguntar(cliente, **{"cf-connecting-ip": "2.2.2.2"}).status_code == 200


def test_limite_ventanas():
    lim = Limite()
    assert all(lim.permitir("a", 0) for _ in range(POR_IP)) and not lim.permitir("a", 1)
    assert lim.permitir("a", VENTANA_IP + 1)  # pasó la ventana
    lim = Limite()
    assert all(lim.permitir(str(i), 0) for i in range(GLOBAL)) and not lim.permitir("nueva", 1)


def test_una_redaccion_a_la_vez(db):
    from tabularium import pagina
    pagina._modelo.acquire()  # otra pregunta ocupa el modelo
    try:
        r = _preguntar(TestClient(crear_app(db, _llamar([NUEVO]))))
    finally:
        pagina._modelo.release()
    assert "atendiendo otra pregunta" in r.text and "LDP, art. 2o" in r.text


# Auditoría de seguridad (2026-11-13).
def test_cabeceras_en_toda_respuesta(db):
    cliente = TestClient(crear_app(db), raise_server_exceptions=False)
    for r in (cliente.get("/no-existe"), cliente.delete("/"), cliente.get("/estilo.css")):
        assert all(r.headers.get(k) == v for k, v in CABECERAS.items())


def test_fecha_extrema_no_tumba_la_pagina(db):
    assert TestClient(crear_app(db)).get("/", params={"hasta": "0001-01-01"}).status_code == 400


def test_post_desde_otro_sitio(db):
    cliente = TestClient(crear_app(db, _llamar([NUEVO])))
    assert _preguntar(cliente, **{"sec-fetch-site": "cross-site"}).status_code == 403
    assert _preguntar(cliente, origin="https://malo.example").status_code == 403
    assert _preguntar(cliente, origin="http://testserver", **{"sec-fetch-site": "same-origin"}).status_code == 200


def test_ipv6_cuenta_por_su_64(db):
    cliente = TestClient(crear_app(db, _llamar([NUEVO])))
    estados = [_preguntar(cliente, **{"cf-connecting-ip": f"2001:db8:1:2::{i:x}"}).status_code for i in range(POR_IP + 1)]
    assert estados[-1] == 429
    assert _preguntar(cliente, **{"cf-connecting-ip": "2001:db8:1:3::1"}).status_code == 200


def test_el_fallo_del_baker_no_se_muestra(db):
    def caido(tarea, archivo):
        raise BakerCaido("http://100.64.0.1:8090 rechazó la llave")
    r = _preguntar(TestClient(crear_app(db, caido)))
    assert "el modelo no está disponible" in r.text and "100.64" not in r.text and "8090" not in r.text


def test_el_modelo_se_carga_una_vez_con_hilos(monkeypatch):
    """Diez preguntas a la vez cargaban diez copias del modelo y el kernel mataba la página."""
    import time
    from concurrent.futures import ThreadPoolExecutor
    from tabularium import vectores
    cargas = []

    class Lento:
        def __init__(self):
            cargas.append(1)
            time.sleep(0.2)
    monkeypatch.setattr(vectores, "Modelo", Lento)
    monkeypatch.setattr(vectores, "_modelo", None)
    with ThreadPoolExecutor(10) as ex:
        modelos = list(ex.map(lambda _: vectores.modelo(), range(10)))
    assert len(cargas) == 1 and all(m is modelos[0] for m in modelos)


def test_sin_turno_responde_503(db, monkeypatch):
    from tabularium import pagina
    monkeypatch.setattr(pagina, "ESPERA", 0.1)
    tomados = [pagina._en_proceso.acquire() for _ in range(2)]
    try:
        r = _preguntar(TestClient(crear_app(db, _llamar([NUEVO]))))
    finally:
        for _ in tomados:
            pagina._en_proceso.release()
    assert r.status_code == 503 and "intenta en un momento" in r.text
