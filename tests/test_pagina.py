"""RF-12: la página pública de Novellae."""
from starlette.testclient import TestClient

from tabularium.pagina import CABECERAS, crear_app

from test_construir import db  # noqa: F401 (fixture: ley de prueba con el art. 2o reformado)


def test_novella_con_diff_cita_y_aviso(db):
    r = TestClient(crear_app(db)).get("/novellae", params={"desde": "2024-01-01", "hasta": "2024-12-31"})
    assert r.status_code == 200
    assert "<del>viejo.</del>" in r.text and "<ins>nuevo.</ins>" in r.text
    assert "LDP, art. 2o" in r.text and "no sustituye la asesoría" in r.text
    assert all(r.headers[k] == v for k, v in CABECERAS.items())


def test_filtro_por_documento(db):
    cliente = TestClient(crear_app(db))
    rango = {"desde": "2024-01-01", "hasta": "2024-12-31"}
    assert "<ins>nuevo.</ins>" in cliente.get("/novellae", params={**rango, "documento": "LDP"}).text
    otro = cliente.get("/novellae", params={**rango, "documento": "CFF"}).text
    assert "<ins>" not in otro and "No hay publicaciones" in otro


def test_fecha_invalida_y_texto_escapado(db):
    cliente = TestClient(crear_app(db))
    r = cliente.get("/novellae", params={"desde": "<script>"})
    assert r.status_code == 400 and "<script>" not in r.text
    r = cliente.get("/novellae", params={"documento": "<script>alert(1)</script>"})
    assert r.status_code == 200 and "<script>" not in r.text


def test_estaticos(db):
    cliente = TestClient(crear_app(db))
    r = cliente.get("/estatico/estilo.css")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/css")
    assert "max-age" in r.headers["cache-control"]
    assert cliente.get("/estatico/portada.js").status_code == 200
    tipos = {"piezas/aureo-augusto.webp": "image/webp", "fuentes/public-sans-400-normal.woff2": "font/woff2",
             "sello.svg": "image/svg+xml", "piezas/augusto.malla": "application/octet-stream"}
    for ruta, tipo in tipos.items():  # con nosniff, un tipo equivocado no carga
        assert cliente.get(f"/estatico/{ruta}").headers["content-type"].startswith(tipo)
    assert cliente.get("/estatico/../pagina.py").status_code == 404


def test_portada(db):
    """La portada: la pieza con su respaldo, lo último en una oración por cambio y el script propio."""
    from tabularium.pagina import ESTATICO, ESTATUAS, MONEDAS
    r = TestClient(crear_app(db)).get("/")
    assert r.status_code == 200
    assert 'data-mallas="/estatico/piezas/' in r.text and 'data-textura="/estatico/piezas/' in r.text and "<noscript><img" in r.text
    csp = r.headers["content-security-policy"]
    assert 'src="/estatico/portada.js?v=' in r.text and "script-src 'self'" in csp and "connect-src 'self'" in csp
    assert ' style="' not in r.text  # la CSP bloquea los estilos en línea
    assert "Publicaciones recientes en el DOF" in r.text and '<li class="revela">' in r.text and "no sustituye la asesoría" in r.text
    assert "Consultas a Gayo" in r.text and 'class="pausa' in r.text
    assert "Fuentes y método" in r.text and "Fuentes revisadas el " in r.text  # WCAG 2.2.2: lo que se mueve solo se puede pausar
    for archivo, *_ in ESTATUAS + MONEDAS:  # toda pieza de la portada existe, con sus imágenes fijas de respaldo
        for sufijo in ("-claro", "-oscuro"):
            assert (ESTATICO / "piezas" / f"{archivo}{sufijo}.webp").exists()
    for archivo, _ in ESTATUAS:
        assert (ESTATICO / "piezas" / f"{archivo}.malla").read_bytes()[:4] == b"TAB1"
    for archivo, *_ in MONEDAS:
        assert (ESTATICO / "piezas" / f"{archivo}.webp").exists()


def test_cambio_en_una_oracion(db):
    """Cada cambio sale en un renglón: dónde, una oración, su etiqueta y el enlace a su Novella."""
    from tabularium.pagina import _ancla, _recientes, _renglon, _todas
    n = next(n for n in _todas(db)[0] if any(d["documento"] == "LDP" for d in n["documentos"]))
    renglones = _recientes([n])
    html = _renglon(renglones[0])
    assert "LDP, art. 2o" in html and f"#{_ancla(n)}" in html and f'datetime="{n["publicado_dof"]}"' in html
    assert len(_recientes(_todas(db)[0], 3)) <= 3


def test_oracion():
    from tabularium.pagina import _oracion
    assert _oracion("Se amplía el plazo. Además, se aclara la regla 2.1.") == "Se amplía el plazo."
    assert _oracion("Cambia la tasa del art. 2o.-A de 0% a 16%") == "Cambia la tasa del art."  # límite conocido
    assert _oracion("Sin punto final") == "Sin punto final."


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
    assert "se abstiene de responder" in r.text and "<blockquote>" not in r.text and "El artículo 2o" not in r.text


def test_preguntar_con_el_baker_caido_muestra_la_busqueda(db):
    def caido(tarea, archivo):
        raise BakerCaido("Pixilate apagada")
    r = _preguntar(TestClient(crear_app(db, caido)))
    assert "No fue posible redactar una respuesta" in r.text and "LDP, art. 2o" in r.text


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


def test_una_redaccion_a_la_vez(db, monkeypatch):
    from tabularium import pagina
    monkeypatch.setattr(pagina, "ESPERA_MODELO", 0.1)  # hace fila, pero no para siempre
    pagina._modelo.acquire()  # otra pregunta ocupa el modelo
    try:
        r = _preguntar(TestClient(crear_app(db, _llamar([NUEVO]))))
    finally:
        pagina._modelo.release()
    assert "atendiendo otra consulta" in r.text and "LDP, art. 2o" in r.text


# Auditoría de seguridad (2026-11-13).
def test_cabeceras_en_toda_respuesta(db):
    cliente = TestClient(crear_app(db), raise_server_exceptions=False)
    for r in (cliente.get("/no-existe"), cliente.delete("/"), cliente.get("/estatico/estilo.css")):
        assert all(r.headers.get(k) == v for k, v in CABECERAS.items())


def test_fecha_extrema_no_tumba_la_pagina(db):
    assert TestClient(crear_app(db)).get("/novellae", params={"hasta": "0001-01-01"}).status_code == 400


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
    assert "Gayo no está disponible" in r.text and "100.64" not in r.text and "8090" not in r.text


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
    assert r.status_code == 503 and "intente de nuevo en un momento" in r.text


# Consultas en segundo plano (2026-11-13): Cloudflare corta a los 100 s y el modelo puede tardar más.
def test_consulta_en_curso_se_actualiza_sola(db, caplog):
    import logging
    import threading
    from tabularium import pagina
    soltar = threading.Event()

    def lento(tarea, archivo):
        soltar.wait(10)
        return {"citas": [NUEVO], "no_encontrado": False, "respuesta": "El artículo 2o de la LDP dice texto nuevo."}
    app = crear_app(db, lento)
    app.state.espera_inicial = 0
    cliente = TestClient(app)
    caplog.set_level(logging.INFO)
    r = cliente.post("/preguntar", data={"pregunta": "texto nuevo, consulta 7319", "fecha": "2024-05-01"},
                     follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("/preguntar/")
    en_curso = cliente.get(r.headers["location"])
    assert en_curso.status_code == 200 and 'http-equiv="refresh"' in en_curso.text and "redactando" in en_curso.text
    soltar.set()
    clave = r.headers["location"].rsplit("/", 1)[1]
    assert app.state.trabajos.ver(clave).listo.wait(10)
    listo = cliente.get(r.headers["location"])
    assert "<blockquote>Artículo 2o.- Texto nuevo.</blockquote>" in listo.text and 'http-equiv="refresh"' not in listo.text
    assert "7319" not in caplog.text  # al registro van conteos, nunca la consulta
    assert pagina._en_proceso.acquire(blocking=False)  # el turno se devolvió
    pagina._en_proceso.release()


def test_consulta_desconocida(db):
    r = TestClient(crear_app(db)).get("/preguntar/no-existe")
    assert r.status_code == 404 and "ya no está disponible" in r.text


def test_la_redaccion_hace_fila_y_suelta_la_busqueda(db):
    """Con el modelo ocupado, la consulta espera su turno (no falla) y no retiene el turno de búsqueda."""
    from tabularium import pagina
    app = crear_app(db, _llamar([NUEVO]))
    app.state.espera_inicial = 0
    cliente = TestClient(app)
    pagina._modelo.acquire()  # otra consulta redactando
    try:
        r = _preguntar(cliente)
        clave = r.url.path.rsplit("/", 1)[1]
        t = app.state.trabajos.ver(clave)
        assert not t.listo.wait(0.5) and t.respuesta is not None  # ya buscó y espera turno
        assert pagina._en_proceso.acquire(blocking=False) and pagina._en_proceso.acquire(blocking=False)
        pagina._en_proceso.release()
        pagina._en_proceso.release()
    finally:
        pagina._modelo.release()
    assert t.listo.wait(10) and t.respuesta.citas
