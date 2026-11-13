"""Página pública de Tabularium (RF-12): las Novellae en HTML generado del lado del servidor.

Proceso aparte del MCP (RNF-07): escucha en 127.0.0.1 y lo publica Cloudflare Tunnel; el MCP se
queda en la tailnet. Solo lectura, sin cuentas ni datos de quien visita. Todo texto de la base
pasa por `escape`: el corpus viene de fuentes externas.
"""
from __future__ import annotations

import ipaddress
import mimetypes
import os
import re
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
from starlette.responses import HTMLResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from . import almacen
from . import preguntar as pg
from .almacen import documento_de
from .glosas import BakerCaido
from .novellae import novellae
from .servidor import ruta_db

# Sin scripts de terceros ni estilos en línea: la política de contenido solo deja lo propio. Las
# fuentes también se sirven desde aquí: pedirlas a otro sitio le daría la IP de quien visita.
CABECERAS = {
    "Content-Security-Policy": "default-src 'none'; style-src 'self'; img-src 'self'; script-src 'self'; "
                               "font-src 'self'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    # Por HTTP local el navegador la ignora; por el túnel (HTTPS) obliga a no volver a HTTP.
    "Strict-Transport-Security": "max-age=31536000",
}
AVISO = ("Tabularium no sustituye a un abogado o contador que firme. El diff es el texto literal de cada versión; "
         "las etiquetas ▲ ▼ ◆ y los resúmenes marcados como generados los escribe un modelo y pueden equivocarse.")
OCUPADO = "el modelo está atendiendo otra pregunta; intenta en un minuto"
SIMBOLOS = {"▲": "amplía", "▼": "restringe", "◆": "aclara", "✚": "nueva", "✖": "derogada"}



# Con nosniff, un tipo equivocado deja la imagen o la fuente sin cargar; no depender del sistema.
for _tipo, _ext in (("image/webp", ".webp"), ("font/woff2", ".woff2"), ("image/svg+xml", ".svg"), ("text/javascript", ".js")):
    mimetypes.add_type(_tipo, _ext)
CLASES = {"▲": "amplia", "▼": "restringe", "◆": "aclara", "✚": "nueva", "✖": "derogada"}
ESTATICO = Path(__file__).parent / "estatico"
# Piezas CC0 del Musée Saint-Raymond (Toulouse), renderizadas con `portada/render_estatuas.py`.
PIEZAS = [  # (archivo, ancho, alto de la textura, pie, texto alternativo)
    ("augusto", 930, 1400, "Busto de Augusto con corona de encino",
     "Busto de mármol de Augusto, con corona de hojas de encino, impreso en tinta roja con trama de puntos."),
    ("septimio", 901, 1400, "Busto de Septimio Severo con corona de encino",
     "Busto de mármol de Septimio Severo, con barba y toga, impreso en tinta roja con trama de puntos."),
    ("hercules", 930, 1400, "Hércules mata a Gerión, relieve de la villa de Chiragan",
     "Relieve de mármol de Hércules luchando contra Gerión, impreso en tinta roja con trama de puntos."),
]
MONEDAS = [("aureo-augusto", "Áureo de Augusto", "Moneda de oro con el perfil de Augusto, en tinta ocre."),
           ("sestercio-trajano", "Sestercio de Trajano", "Moneda de bronce con el busto de Trajano, en tinta ocre.")]
CREDITO = ("Las piezas son escaneos del Musée Saint-Raymond de Toulouse, publicados en dominio público (CC0) "
           "e impresos aquí con un shader propio.")


def _efecto(simbolo: str | None, generado: bool = True) -> str:
    if not simbolo:
        return '<span class="efecto pendiente" title="sin etiqueta todavía" aria-label="sin etiqueta todavía">·</span>'
    nombre = SIMBOLOS.get(simbolo, "")
    detalle = f"{nombre} (generado)" if generado else nombre
    return f'<span class="efecto {CLASES.get(simbolo, "")}" title="{detalle}" aria-label="{detalle}">{simbolo}</span>'


def _cambio(c: dict) -> str:
    marca = ' <span class="generado">generado</span>' if c["efecto_generado"] else ""
    partes = [f'<h4>{_efecto(c["efecto"], c["efecto_generado"])} {escape(c["unidad"])}{marca}</h4>']
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


def _ancla(n: dict) -> str:
    """Estable entre visitas y filtros: el código de la nota del DOF; si no, el decreto o la fecha."""
    cod = re.search(r"codigo=(\d+)", n["fuente_url"] or "")
    return f"dof-{cod.group(1)}" if cod else re.sub(r"[^A-Za-z0-9-]", "-", n["decreto_dof"] or f"dof-{n['publicado_dof']}")


def _novella(n: dict) -> str:
    titulo = escape(n["titulo"] or n["decreto_dof"] or "Publicación del DOF")
    fuente = f' <a href="{escape(n["fuente_url"])}">DOF</a>' if n["fuente_url"] else ""
    vigor = f', en vigor desde {escape(n["entrada_en_vigor"])}' if n["entrada_en_vigor"] else ""
    partes = [f'<article class="novella" id="{_ancla(n)}"><h2>{titulo}</h2>'
              f'<p class="suave">Publicado el {escape(n["publicado_dof"])}{vigor}.{fuente}</p>']
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


def _pagina(titulo: str, cuerpo: str, actual: str = "", descripcion: str = "", script: bool = False) -> str:
    actual_attr = ' aria-current="page"'
    nav = "".join(f'<a href="{ruta}"{actual_attr if ruta == actual else ""}>{nombre}</a>'
                  for ruta, nombre in (("/novellae", "Novellae"), ("/preguntar", "Preguntar"), ("/#corpus", "Corpus")))
    meta = f'<meta name="description" content="{escape(descripcion)}">' if descripcion else ""
    js = '<script type="module" src="/estatico/portada.js"></script>' if script else ""
    return (f'<!doctype html><html lang="es-MX"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width, initial-scale=1">{meta}'
            f'<meta name="color-scheme" content="light dark">'
            f'<title>{escape(titulo)}</title><link rel="stylesheet" href="/estatico/estilo.css">'
            f'<link rel="icon" href="/estatico/sello.svg" type="image/svg+xml">{js}</head><body>'
            f'<a class="salto" href="#contenido">Saltar al contenido</a>'
            f'<header class="barra"><a class="sello" href="/" aria-label="Tabularium, inicio">TABVLARIVM<span>·</span></a>'
            f'<nav aria-label="Secciones">{nav}</nav></header>'
            f'<main id="contenido">{cuerpo}</main>'
            f'<footer><p>{escape(AVISO)}</p><p>{escape(CREDITO)}</p></footer></body></html>')


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
                    (i, n) for i, n in con.execute("SELECT id, nombre FROM documentos WHERE tipo != 'decreto' ORDER BY id")],
                    cifras=con.execute(
                        "SELECT (SELECT COUNT(*) FROM documentos WHERE tipo != 'decreto'), "
                        "(SELECT COUNT(DISTINCT documento || ' ' || clave) FROM versiones), (SELECT COUNT(*) FROM versiones), "
                        "(SELECT MAX(publicado_dof) FROM decretos)").fetchone())
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


MESES = "ene feb mar abr may jun jul ago sep oct nov dic".split()


def _fecha_corta(iso: str) -> str:
    a, m, d = iso.split("-")
    return f"{int(d)} {MESES[int(m) - 1]} {a}"


def _oracion(texto: str) -> str:
    """La primera oración del resumen: lo que cabe en un renglón de la portada."""
    texto = " ".join(texto.split())
    m = re.match(r"(.+?\.)(\s|$)", texto)
    return m.group(1) if m else texto.rstrip(";,") + "."


def _novedad(n: dict) -> str:
    """Una publicación en un renglón: sus cambios, cada uno en una oración (hasta tres)."""
    enlace = f'/novellae?desde={n["publicado_dof"]}&amp;hasta={n["publicado_dof"]}#{_ancla(n)}'
    cambios = [(d, c) for d in n["documentos"] for c in d.get("cambios", [])]
    renglones = []
    if n["pendiente"]:
        docs = ", ".join(d["documento"] for d in n["documentos"])
        renglones.append(f'<li>{_efecto(None)}<span>Ya salió en el DOF; el texto entra al corpus ({escape(docs)}) '
                         f'cuando la fuente oficial lo publique.</span></li>')
    for d, c in cambios[:3]:
        if c["resumen"]:
            frase = escape(_oracion(c["resumen"]))
        else:
            frase = "Cambió el texto; la glosa todavía no está." if c["diff"] is not None else "Unidad nueva."
        renglones.append(f'<li>{_efecto(c["efecto"], c["efecto_generado"])}<span><b>{escape(d["documento"])} '
                         f'{escape(c["unidad"])}.</b> {frase}</span></li>')
    for d in [d for d in n["documentos"] if d.get("nuevo")][:1]:
        renglones.append(f'<li>{_efecto("✚", False)}<span><b>{escape(d["documento"])}.</b> Documento nuevo con '
                         f'{d["unidades"]} unidades.</span></li>')
    if not renglones:
        renglones.append(f'<li>{_efecto(None)}<span>Solo transitorios.</span></li>')
    resto = len(cambios) - 3
    mas = f'<p class="mas"><a href="{enlace}">y {resto} cambio{"s" if resto > 1 else ""} más</a></p>' if resto > 0 else ""
    titulo = escape(n["titulo"] or n["decreto_dof"] or "Publicación del DOF")
    return (f'<li class="novedad revela"><time datetime="{n["publicado_dof"]}">{_fecha_corta(n["publicado_dof"])}</time>'
            f'<div><h3><a href="{enlace}">{titulo}</a></h3><ul>{"".join(renglones)}</ul>{mas}</div></li>')


def _lienzo(archivo: str, ancho: int, alto: int, alt: str, tinta: str = "--rubrica", celda: float = 4.5) -> str:
    """La pieza: el script la imprime con WebGL; sin script, la imagen fija del modo claro."""
    ruta = f"/estatico/piezas/{archivo}"
    # Sin style en línea (la CSP lo bloquea): el script pone la proporción exacta desde la textura.
    return (f'<div class="lienzo" data-textura="{ruta}.webp" '
            f'data-fija-claro="{ruta}-claro.webp" data-fija-oscuro="{ruta}-oscuro.webp" data-tinta="{tinta}" '
            f'data-celda="{celda}" data-alt="{escape(alt)}" role="img" aria-label="{escape(alt)}">'
            f'<noscript><img src="{ruta}-claro.webp" alt="" width="{ancho}" height="{alto}"></noscript></div>')


def portada(request: Request) -> HTMLResponse:
    lista, documentos = _todas(request.app.state.db)
    n_docs, n_unidades, n_versiones, ultima = _cache["cifras"]
    archivo, ancho, alto, pie, alt = PIEZAS[date.today().toordinal() % len(PIEZAS)]
    recientes = sorted(lista, key=lambda n: n["publicado_dof"], reverse=True)[:6]
    novedades = "".join(_novedad(n) for n in recientes) or "<li>Todavía no hay publicaciones.</li>"
    monedas = "".join(f'<figure class="moneda">{_lienzo(a, 512, 512, alt_m, "--ocre", 2.5)}<figcaption>{p}</figcaption></figure>'
                      for a, p, alt_m in MONEDAS)
    docs = "".join(f"<li><b>{escape(i)}</b><span>{escape(n)}</span></li>" for i, n in documentos)
    cuerpo = (
        f'<section class="portada"><div class="lema">'
        f'<h1 class="marca" aria-label="Tabularium">TABVLARIVM<span class="punto" aria-hidden="true">·</span></h1>'
        f'<p class="bajada">Las leyes fiscales de México con cada versión guardada desde 2024, y cada reforma '
        f'del DOF anunciada <em>artículo por artículo</em>.</p>'
        f'{_formulario(compacto=True)}</div>'
        f'<figure class="pieza">{_lienzo(archivo, ancho, alto, alt)}<figcaption>{escape(pie)}</figcaption></figure></section>'
        f'<section aria-labelledby="ultimo"><h2 id="ultimo">Lo último en el DOF</h2>'
        f'<ol class="novedades">{novedades}</ol>'
        f'<p><a href="/novellae">Todas las Novellae, con el texto literal de cada cambio</a></p></section>'
        f'<section id="corpus" aria-labelledby="titulo-corpus" class="erario"><div>'
        f'<h2 id="titulo-corpus">El corpus</h2><dl class="cifras">'
        f'<div><dt>documentos</dt><dd>{n_docs}</dd></div><div><dt>artículos, reglas y secciones</dt><dd>{n_unidades:,}</dd></div>'
        f'<div><dt>versiones guardadas</dt><dd>{n_versiones:,}</dd></div></dl>'
        f'<p class="suave">Última publicación incorporada: {_fecha_corta(ultima) if ultima else "ninguna"}. '
        f'Nada se sobrescribe: cada versión queda con su vigencia y el decreto que la reformó.</p>'
        f'<ul class="documentos">{docs}</ul></div><div class="monedas">{monedas}</div></section>')
    return _respuesta(_pagina("Tabularium", cuerpo, "/", script=True, descripcion=(
        "Leyes fiscales de México versionadas (LISR, CFF, LIVA, RMF y anexos), con las reformas del DOF "
        "anunciadas artículo por artículo y respuestas que citan su fuente.")))


def novellae_pagina(request: Request) -> HTMLResponse:
    q = request.query_params
    documento, desde, hasta = (q.get(k) or None for k in ("documento", "desde", "hasta"))
    try:
        fin = date.fromisoformat(hasta) if hasta else date.today()
        inicio = date.fromisoformat(desde) if desde else fin - timedelta(90)
    except (ValueError, OverflowError):  # OverflowError: "0001-01-01" menos 90 días
        return _respuesta(_pagina("Tabularium", "<h1>Novellae</h1><p>Fecha inválida: usa AAAA-MM-DD.</p>", "/novellae"), 400)
    lista, documentos = _todas(request.app.state.db)
    elegido = documento_de(documento, fin.isoformat()) if documento else None
    lista = _filtrar(lista, inicio.isoformat(), fin.isoformat(), elegido)
    opciones = "".join(f'<option value="{escape(i)}"{" selected" if i == elegido else ""}>{escape(i)}: {escape(n)}</option>'
                       for i, n in documentos)
    filtro = (f'<form class="filtro" method="get" action="/novellae"><label>Documento<select name="documento">'
              f'<option value="">Todos</option>{opciones}</select></label>'
              f'<label>Desde<input type="date" name="desde" min="2024-01-01" value="{escape(desde or "")}"></label>'
              f'<label>Hasta<input type="date" name="hasta" min="2024-01-01" value="{escape(hasta or "")}"></label>'
              f'<button type="submit">Filtrar</button></form>')
    rango = "" if desde or hasta else '<p class="suave">Últimos 90 días.</p>'
    cuerpo = "".join(_novella(n) for n in lista) or "<p>No hay publicaciones en ese rango.</p>"
    intro = ('<h1 class="marca chica-marca">Novellae</h1><p class="bajada">Cada publicación del DOF que toca el corpus, con el '
             'texto literal que se quitó y el que entró. Las etiquetas y los resúmenes los escribe un modelo y van marcados.</p>')
    return _respuesta(_pagina("Tabularium: Novellae", intro + filtro + rango + cuerpo, "/novellae",
                              descripcion="Las reformas fiscales del DOF, artículo por artículo, con el diff literal."))


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


ALCANCE = ("Responde solo con LISR, CFF, LIVA, la RMF y sus anexos, y cita cada pasaje. Si no lo puede citar, "
           "no responde. La pregunta no se guarda.")


def _formulario(pregunta: str = "", fecha: str = "", compacto: bool = False) -> str:
    filas = 2 if compacto else 4
    return (f'<form class="preguntar" method="post" action="/preguntar"><label>Pregunta a la ley<textarea name="pregunta" '
            f'rows="{filas}" maxlength="{pg.LARGO_MAXIMO}" required placeholder="¿Qué porcentaje de una computadora se puede deducir?">'
            f'{escape(pregunta)}</textarea></label><div class="fila">'
            f'<label>Fecha del ejercicio<input type="date" name="fecha" min="2024-01-01" value="{escape(fecha)}"></label>'
            f'<button type="submit">Preguntar</button></div>'
            f'<p class="suave chica">{"Cita cada pasaje o no responde. Tu pregunta no se guarda." if compacto else ALCANCE}</p></form>')


def _cita(c: dict) -> str:
    return f'{escape(c["texto"])}. <a href="{escape(c["fuente_url"])}">Fuente</a>'


def _resultado(r: pg.Respuesta) -> str:
    if r.texto:
        citas = "".join(f'<li><blockquote>{escape(c.texto)}</blockquote><p class="cita">{_cita(c.cita)}</p></li>'
                        for c in r.citas)
        return (f'<section class="respuesta"><p>{escape(r.texto)} <span class="generado">generado</span></p>'
                f'<p class="suave">Redactado por un modelo local. Cada cita se verificó letra por letra contra el texto '
                f'vigente en la fecha.</p><ol>{citas}</ol></section>')
    if r.fallo:
        # El detalle (stderr del Baker, rutas) va a journald, no a quien visita.
        motivo = OCUPADO if r.fallo == OCUPADO else "el modelo no está disponible"
        lista = "".join(f'<li class="cita">{_cita(p["cita"])}</li>' for p in r.pasajes)
        return (f'<section class="respuesta"><p>No hay respuesta redactada ahora: {motivo}.</p>'
                f'<p>Estos son los artículos y reglas que encontró la búsqueda:</p><ol>{lista}</ol></section>')
    return ('<section class="respuesta"><p>El corpus no responde esto con citas verificables, así que Tabularium '
            'no responde.</p></section>')


CABEZA_PREGUNTAR = ('<h1 class="marca chica-marca">Preguntar</h1><p class="bajada">Una pregunta general sobre la ley '
                    'fiscal federal. La respuesta cita cada pasaje en la versión vigente en la fecha que elijas.</p>')


def _preguntar(cuerpo: str, estado: int = 200) -> HTMLResponse:
    return _respuesta(_pagina("Tabularium: Preguntar", CABEZA_PREGUNTAR + cuerpo, "/preguntar"), estado)


def preguntar_get(request: Request) -> HTMLResponse:
    return _preguntar(_formulario())


async def preguntar_post(request: Request) -> HTMLResponse:
    cuerpo = b""
    async for trozo in request.stream():
        cuerpo += trozo
        if len(cuerpo) > CUERPO_MAXIMO:
            return _preguntar("<p>La pregunta es demasiado larga.</p>", 413)
    datos = parse_qs(cuerpo.decode("utf-8", "replace"))
    pregunta, fecha = (datos.get(k, [""])[0].strip() for k in ("pregunta", "fecha"))
    if not 0 < len(" ".join(pregunta.split())) <= pg.LARGO_MAXIMO:
        return _preguntar(_formulario(pregunta[:pg.LARGO_MAXIMO], fecha)
                          + f"<p>La pregunta debe tener entre 1 y {pg.LARGO_MAXIMO} caracteres.</p>", 400)
    if not _mismo_sitio(request):
        return _preguntar("<p>La pregunta debe enviarse desde esta página.</p>", 403)
    ip = request.headers.get("cf-connecting-ip") or (request.client.host if request.client else "")
    if not request.app.state.limite.permitir(_llave(ip)):
        return _preguntar(_formulario(pregunta, fecha)
                          + "<p>Demasiadas preguntas por ahora; intenta en unos minutos.</p>", 429)

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
            return _preguntar(_formulario(pregunta, fecha)
                              + "<p>Hay muchas preguntas en este momento; intenta en un momento.</p>", 503)
    except ValueError as e:
        return _preguntar(_formulario(pregunta, fecha) + f"<p>{escape(str(e))}.</p>", 400)
    return _preguntar(_formulario(pregunta, fecha) + _resultado(r))


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
                if scope["path"].startswith("/estatico/"):  # cambian poco; la validación por ETag sigue
                    h.setdefault("Cache-Control", "public, max-age=86400")
            await send(mensaje)
        await self.app(scope, receive, enviar)


def crear_app(db: Path | None = None, llamar=pg._bake) -> Cabeceras:
    app = Starlette(routes=[Route("/", portada), Route("/novellae", novellae_pagina),
                            Route("/preguntar", preguntar_get, methods=["GET"]),
                            Route("/preguntar", preguntar_post, methods=["POST"]),
                            Mount("/estatico", StaticFiles(directory=ESTATICO), name="estatico")])
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
