"""Página pública de Tabularium (RF-12): las Novellae en HTML generado del lado del servidor.

Proceso aparte del MCP (RNF-07): escucha en 127.0.0.1 y lo publica Cloudflare Tunnel; el MCP se
queda en la tailnet. Solo lectura, sin cuentas ni datos de quien visita. Todo texto de la base
pasa por `escape`: el corpus viene de fuentes externas.
"""
from __future__ import annotations

import ipaddress
import os
import threading
import time
from collections import deque
from contextlib import closing
from datetime import date, timedelta
from html import escape
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import MutableHeaders
from starlette.requests import Request
from starlette.responses import HTMLResponse, Response
from starlette.routing import Route

from . import almacen
from . import preguntar as pg
from .almacen import documento_de
from .glosas import BakerCaido
from .novellae import novellae
from .servidor import ruta_db

# Sin scripts de terceros ni estilos en línea: la política de contenido solo deja lo propio.
CABECERAS = {
    "Content-Security-Policy": "default-src 'none'; style-src 'self'; img-src 'self'; form-action 'self'; "
                               "base-uri 'none'; frame-ancestors 'none'",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    # Por HTTP local el navegador la ignora; por el túnel (HTTPS) obliga a no volver a HTTP.
    "Strict-Transport-Security": "max-age=31536000",
}
AVISO = ("Tabularium no sustituye a un abogado o contador que firme. El diff es el texto literal de cada versión; "
         "las etiquetas ▲ ▼ ◆ y los resúmenes marcados como generados los escribe un modelo y pueden equivocarse.")
OCUPADO = "el modelo está atendiendo otra pregunta; intenta en un minuto"
SIMBOLOS = {"▲": "amplía", "▼": "restringe", "◆": "aclara", "✚": "nueva", "✖": "derogada"}

ESTILO = """
:root { --tinta: #1d1b18; --fondo: #f6f3ec; --suave: #6b655b; --quita: #9b2c2c; --agrega: #23613a; --linea: #d8d2c4; }
@media (prefers-color-scheme: dark) {
  :root { --tinta: #ece7dc; --fondo: #191816; --suave: #a59e91; --quita: #f2a1a1; --agrega: #9fdcb0; --linea: #3a3732; }
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--fondo); color: var(--tinta); font: 1rem/1.55 Georgia, "Times New Roman", serif; }
main, header, footer { max-width: 52rem; margin: 0 auto; padding: 0 1rem; }
h1 { margin: 1.5rem 0 .25rem; letter-spacing: .04em; }
h2 { margin: 2rem 0 .25rem; font-size: 1.2rem; }
h3 { margin: 1rem 0 .25rem; font-size: 1.05rem; }
.suave, .cita { color: var(--suave); font-size: .9rem; }
form { display: flex; flex-wrap: wrap; gap: .75rem; align-items: end; margin: 1rem 0; }
label { display: flex; flex-direction: column; font-size: .85rem; flex: 1 1 auto; }
input, select, button { font: inherit; padding: .25rem .4rem; }
article { border-top: 1px solid var(--linea); padding-bottom: .5rem; }
.cambio { margin: .75rem 0 1rem; }
.diff, .texto { white-space: pre-wrap; overflow-wrap: anywhere; }
del { color: var(--quita); }
ins { color: var(--agrega); text-decoration-thickness: 2px; }
.generado { font-size: .8rem; border: 1px solid var(--linea); padding: 0 .3rem; border-radius: .2rem; }
a { color: inherit; }
footer { margin: 2rem auto; color: var(--suave); font-size: .85rem; }
textarea { font: inherit; width: 100%; max-width: 40rem; }
blockquote { margin: .5rem 0; padding-left: .75rem; border-left: 3px solid var(--linea); white-space: pre-wrap; }
"""


def _cambio(c: dict) -> str:
    efecto = c["efecto"] or "·"
    nombre = SIMBOLOS.get(c["efecto"], "sin etiqueta todavía")
    marca = ' <span class="generado">generado</span>' if c["efecto_generado"] else ""
    partes = [f'<h3><span title="{nombre}" aria-label="{nombre}">{efecto}</span> {escape(c["unidad"])}{marca}</h3>']
    if c["resumen"]:
        partes.append(f'<p>{escape(c["resumen"])} <span class="generado">generado por {escape(c["modelo"] or "un modelo")}</span></p>')
    if c["diff"] is not None:
        tramos = {"=": "{}", "-": "<del>{}</del>", "+": "<ins>{}</ins>"}
        partes.append('<p class="diff">' + "".join(tramos[op].format(escape(t)) for op, t in c["diff"]) + "</p>")
    elif c["texto"]:
        partes.append(f'<details><summary>Texto de la unidad nueva</summary><p class="texto">{escape(c["texto"])}</p></details>')
    if c["junta"]:
        partes.append(f'<p class="suave">El cambio junta también: {escape(", ".join(c["junta"]))}.</p>')
    partes.append(f'<p class="cita">{escape(c["cita"]["texto"])}. <a href="{escape(c["cita"]["fuente_url"])}">Fuente</a></p>')
    return '<div class="cambio">' + "".join(partes) + "</div>"


def _novella(n: dict) -> str:
    titulo = escape(n["titulo"] or n["decreto_dof"] or "Publicación del DOF")
    fuente = f' <a href="{escape(n["fuente_url"])}">DOF</a>' if n["fuente_url"] else ""
    vigor = f', en vigor desde {escape(n["entrada_en_vigor"])}' if n["entrada_en_vigor"] else ""
    partes = [f'<article><h2>{titulo}</h2><p class="suave">Publicado el {escape(n["publicado_dof"])}{vigor}.{fuente}</p>']
    if n["pendiente"]:
        docs = ", ".join(d["documento"] for d in n["documentos"])
        partes.append(f"<p>El DOF ya lo publicó y el texto todavía no está en el corpus ({escape(docs)}).</p>")
    for d in [] if n["pendiente"] else n["documentos"]:
        partes.append(f'<section><h3>{escape(d["nombre"])} ({escape(d["documento"])})</h3>')
        if d["nuevo"]:
            partes.append(f'<p>Documento nuevo: {d["unidades"]} unidades, vigente desde {escape(d["vigente_desde"])}.</p>')
        else:
            partes.extend(_cambio(c) for c in d["cambios"])
        partes.append("</section>")
    if n["transitorios"]:
        partes.append(f'<p class="suave">Transitorios: {escape(", ".join(n["transitorios"]))}.</p>')
    return "".join(partes) + "</article>"


def _pagina(titulo: str, cuerpo: str) -> str:
    return (f'<!doctype html><html lang="es"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width, initial-scale=1">'
            f'<title>{escape(titulo)}</title><link rel="stylesheet" href="/estilo.css"></head><body>'
            f'<header><h1>Tabularium</h1><p class="suave">Leyes fiscales de México versionadas, con cita de cada artículo.</p>'
            f'<nav><a href="/">Novellae</a> · <a href="/preguntar">Preguntar</a></nav></header><main>{cuerpo}</main><footer><p>{escape(AVISO)}</p></footer></body></html>')


def _respuesta(html: str, estado: int = 200) -> HTMLResponse:
    return HTMLResponse(html, status_code=estado)


_cache: dict = {}
_candado = threading.Lock()


def _todas(db: Path) -> tuple[list[dict], list[tuple[str, str]]]:
    """Todas las Novellae desde el inicio del corpus (antes solo hay línea base, no reformas),
    calculadas una vez por versión de la base: cambia una vez al día y el cálculo completo tarda
    segundos, así que ningún rango que pida un visitante lo repite."""
    clave = (str(db), db.stat().st_mtime_ns)
    with _candado:
        if _cache.get("clave") != clave:
            with closing(almacen.abrir(db)) as con:
                _cache.update(clave=clave, novellae=novellae(con, almacen.CORTE.isoformat(), "9999-12-31"), documentos=[
                    (i, n) for i, n in con.execute("SELECT id, nombre FROM documentos WHERE tipo != 'decreto' ORDER BY id")])
        return _cache["novellae"], _cache["documentos"]


def _filtrar(lista: list[dict], desde: str, hasta: str, documento: str | None) -> list[dict]:
    """Lo mismo que `novellae(con, desde, hasta, documento)`, sobre la lista ya calculada."""
    salida = []
    for n in lista:
        if not desde <= n["publicado_dof"] <= hasta:
            continue
        if documento:
            documentos = [d for d in n["documentos"] if d["documento"] == documento]
            if not documentos:
                continue
            n = {**n, "documentos": documentos}
        salida.append(n)
    return salida


def portada(request: Request) -> HTMLResponse:
    q = request.query_params
    documento, desde, hasta = (q.get(k) or None for k in ("documento", "desde", "hasta"))
    try:
        fin = date.fromisoformat(hasta) if hasta else date.today()
        inicio = date.fromisoformat(desde) if desde else fin - timedelta(90)
    except (ValueError, OverflowError):  # OverflowError: "0001-01-01" menos 90 días
        return _respuesta(_pagina("Tabularium", "<p>Fecha inválida: usa AAAA-MM-DD.</p>"), 400)
    lista, documentos = _todas(request.app.state.db)
    elegido = documento_de(documento, fin.isoformat()) if documento else None
    lista = _filtrar(lista, inicio.isoformat(), fin.isoformat(), elegido)
    opciones = "".join(f'<option value="{escape(i)}"{" selected" if i == elegido else ""}>{escape(i)}: {escape(n)}</option>'
                       for i, n in documentos)
    filtro = (f'<form method="get" action="/"><label>Documento<select name="documento"><option value="">Todos</option>'
              f'{opciones}</select></label><label>Desde<input type="date" name="desde" min="2024-01-01" value="{escape(desde or "")}"></label>'
              f'<label>Hasta<input type="date" name="hasta" min="2024-01-01" value="{escape(hasta or "")}"></label>'
              f'<button type="submit">Filtrar</button></form>')
    rango = "" if desde or hasta else '<p class="suave">Últimos 90 días.</p>'
    cuerpo = "".join(_novella(n) for n in lista) or "<p>No hay publicaciones en ese rango.</p>"
    return _respuesta(_pagina("Tabularium: Novellae", filtro + rango + cuerpo))


# RNF-10: por IP y global, en memoria (no se guarda nada). La IP la pone Cloudflare: la página solo
# escucha en loopback, así que toda petición llega por el túnel, que sobrescribe esa cabecera.
POR_IP, VENTANA_IP = 5, 600
GLOBAL, VENTANA_GLOBAL = 60, 3600
CUERPO_MAXIMO = 4096


class Limite:
    def __init__(self):
        self.ips: dict[str, deque] = {}
        self.todas: deque = deque()
        self.candado = threading.Lock()

    def permitir(self, ip: str, ahora: float | None = None) -> bool:
        ahora = time.monotonic() if ahora is None else ahora
        with self.candado:
            for cola, ventana in ((self.todas, VENTANA_GLOBAL), *((c, VENTANA_IP) for c in self.ips.values())):
                while cola and cola[0] <= ahora - ventana:
                    cola.popleft()
            self.ips = {k: c for k, c in self.ips.items() if c}
            mia = self.ips.setdefault(ip, deque())
            if len(mia) >= POR_IP or len(self.todas) >= GLOBAL:
                return False
            mia.append(ahora)
            self.todas.append(ahora)
            return True


_modelo = threading.Semaphore(1)  # una redacción a la vez: la GPU de Pixilate no es de la página
# Preguntas en proceso a la vez, búsqueda incluida: cada una embebe la consulta en la CPU de la Pi.
_en_proceso = threading.BoundedSemaphore(2)
ESPERA = 30  # segundos que una pregunta espera turno antes de recibir 503


def _un_turno(llamar):
    def turno(tarea: str, archivo: str) -> dict:
        if not _modelo.acquire(blocking=False):
            raise BakerCaido(OCUPADO)
        try:
            return llamar(tarea, archivo)
        finally:
            _modelo.release()
    return turno


def _llave(ip: str) -> str:
    """De quién cuenta el límite: una IPv6 por su /64, que es lo que suele tener una sola casa o máquina."""
    try:
        d = ipaddress.ip_address(ip)
    except ValueError:
        return ip
    return str(ipaddress.ip_network(f"{d}/64", strict=False)) if d.version == 6 else str(d)


def _mismo_sitio(request: Request) -> bool:
    """Otro sitio no puede mandar preguntas en nombre de quien lo visita (gastaría su cuota y le
    mostraría un texto dictado). Los navegadores mandan Sec-Fetch-Site u Origin; sin ninguno, pasa."""
    sitio, origen = request.headers.get("sec-fetch-site"), request.headers.get("origin")
    if sitio and sitio not in ("same-origin", "none"):
        return False
    return not origen or urlsplit(origen).netloc == request.headers.get("host")


def _formulario(pregunta: str = "", fecha: str = "") -> str:
    return (f'<form method="post" action="/preguntar"><label>Pregunta<textarea name="pregunta" rows="3" cols="60" '
            f'maxlength="{pg.LARGO_MAXIMO}" required>{escape(pregunta)}</textarea></label>'
            f'<label>Fecha (ejercicio)<input type="date" name="fecha" min="2024-01-01" value="{escape(fecha)}"></label>'
            f'<button type="submit">Preguntar</button></form>'
            f'<p class="suave">Responde solo con LISR, CFF, LIVA, la RMF y sus anexos, y cita cada pasaje. Si no lo '
            f'puede citar, no responde. La pregunta no se guarda.</p>')


def _cita(c: dict) -> str:
    return f'{escape(c["texto"])}. <a href="{escape(c["fuente_url"])}">Fuente</a>'


def _resultado(r: pg.Respuesta) -> str:
    if r.texto:
        citas = "".join(f'<li><blockquote>{escape(c.texto)}</blockquote><p class="cita">{_cita(c.cita)}</p></li>'
                        for c in r.citas)
        return (f'<section><p>{escape(r.texto)} <span class="generado">generado</span></p>'
                f'<p class="suave">Redactado por un modelo local. Cada cita se verificó letra por letra contra el texto '
                f'vigente en la fecha.</p><ol>{citas}</ol></section>')
    if r.fallo:
        # El detalle (stderr del Baker, rutas) va a journald, no a quien visita.
        motivo = OCUPADO if r.fallo == OCUPADO else "el modelo no está disponible"
        lista = "".join(f'<li class="cita">{_cita(p["cita"])}</li>' for p in r.pasajes)
        return (f'<section><p>No hay respuesta redactada ahora: {motivo}.</p>'
                f'<p>Estos son los artículos y reglas que encontró la búsqueda:</p><ol>{lista}</ol></section>')
    return "<section><p>El corpus no responde esto con citas verificables, así que Tabularium no responde.</p></section>"


def preguntar_get(request: Request) -> HTMLResponse:
    return _respuesta(_pagina("Tabularium: Preguntar", _formulario()))


async def preguntar_post(request: Request) -> HTMLResponse:
    cuerpo = b""
    async for trozo in request.stream():
        cuerpo += trozo
        if len(cuerpo) > CUERPO_MAXIMO:
            return _respuesta(_pagina("Tabularium", "<p>La pregunta es demasiado larga.</p>"), 413)
    datos = parse_qs(cuerpo.decode("utf-8", "replace"))
    pregunta, fecha = (datos.get(k, [""])[0].strip() for k in ("pregunta", "fecha"))
    if not 0 < len(" ".join(pregunta.split())) <= pg.LARGO_MAXIMO:
        return _respuesta(_pagina("Tabularium", _formulario(pregunta[:pg.LARGO_MAXIMO], fecha)
                                  + f"<p>La pregunta debe tener entre 1 y {pg.LARGO_MAXIMO} caracteres.</p>"), 400)
    if not _mismo_sitio(request):
        return _respuesta(_pagina("Tabularium", "<p>La pregunta debe enviarse desde esta página.</p>"), 403)
    ip = request.headers.get("cf-connecting-ip") or (request.client.host if request.client else "")
    if not request.app.state.limite.permitir(_llave(ip)):
        return _respuesta(_pagina("Tabularium", _formulario(pregunta, fecha)
                                  + "<p>Demasiadas preguntas por ahora; intenta en unos minutos.</p>"), 429)

    def responder() -> pg.Respuesta | None:
        if not _en_proceso.acquire(timeout=ESPERA):
            return None
        try:
            with closing(almacen.abrir(request.app.state.db)) as con:
                return pg.preguntar(con, pregunta, fecha or None, _un_turno(request.app.state.llamar))
        finally:
            _en_proceso.release()
    try:
        r = await run_in_threadpool(responder)
        if r is None:
            return _respuesta(_pagina("Tabularium", _formulario(pregunta, fecha)
                                      + "<p>Hay muchas preguntas en este momento; intenta en un momento.</p>"), 503)
    except ValueError as e:
        return _respuesta(_pagina("Tabularium", _formulario(pregunta, fecha) + f"<p>{escape(str(e))}.</p>"), 400)
    return _respuesta(_pagina("Tabularium: Preguntar", _formulario(pregunta, fecha) + _resultado(r)))


def estilo(request: Request) -> Response:
    return Response(ESTILO, media_type="text/css", headers={"Cache-Control": "public, max-age=3600"})


class Cabeceras:
    """Las cabeceras de seguridad en toda respuesta, también los 404, 405 y 500 de Starlette: envuelve
    la app completa, por fuera de su manejo de errores."""

    def __init__(self, app: Starlette):
        self.app, self.state = app, app.state

    async def __call__(self, scope, receive, send):
        async def enviar(mensaje):
            if mensaje["type"] == "http.response.start":
                h = MutableHeaders(scope=mensaje)
                for k, v in CABECERAS.items():
                    h.setdefault(k, v)
            await send(mensaje)
        await self.app(scope, receive, enviar)


def crear_app(db: Path | None = None, llamar=pg._bake) -> Cabeceras:
    app = Starlette(routes=[Route("/", portada), Route("/estilo.css", estilo),
                            Route("/preguntar", preguntar_get, methods=["GET"]),
                            Route("/preguntar", preguntar_post, methods=["POST"])])
    app.state.db, app.state.llamar, app.state.limite = db or ruta_db(), llamar, Limite()
    return Cabeceras(app)


def servir() -> None:
    import logging
    import uvicorn
    # El contador de `preguntar` (solo conteos, nunca la pregunta) va a stderr y de ahí a journald.
    logging.basicConfig(level=logging.INFO, format="%(name)s %(message)s")
    app = crear_app()
    _todas(app.state.db)  # la primera visita no paga el cálculo; tras la reconstrucción diaria, sí (una vez)
    with closing(almacen.abrir(app.state.db)) as con:
        if con.execute("SELECT 1 FROM fragmentos LIMIT 1").fetchone():
            from .vectores import modelo
            modelo()  # al arrancar y no con la primera pregunta (como el MCP)
    # Solo loopback: la publica el túnel de Cloudflare, nunca un puerto abierto (RNF-07).
    # Fijo en loopback, sin variable: en otra interfaz, CF-Connecting-IP se podría falsificar desde la LAN.
    uvicorn.run(app, host="127.0.0.1",
                port=int(os.environ.get("TABULARIUM_PAGINA_PUERTO", "8062")), proxy_headers=False,
                access_log=False)  # sin IP ni consulta de quien visita (RNF-07, RNF-10)
