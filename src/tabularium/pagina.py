"""Página pública de Tabularium (RF-12): las Novellae en HTML generado del lado del servidor.

Proceso aparte del MCP (RNF-07): escucha en 127.0.0.1 y lo publica Cloudflare Tunnel; el MCP se
queda en la tailnet. Solo lectura, sin cuentas ni datos de quien visita. Todo texto de la base
pasa por `escape`: el corpus viene de fuentes externas.
"""
from __future__ import annotations

import functools
import hashlib
import ipaddress
import json
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
                               "font-src 'self'; connect-src 'self'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    # Por HTTP local el navegador la ignora; por el túnel (HTTPS) obliga a no volver a HTTP.
    "Strict-Transport-Security": "max-age=31536000",
}
AVISO = ("Tabularium no sustituye a un abogado ni a un contador que firme. El diff es el texto literal de cada "
         "versión; las etiquetas ▲ ▼ ◆ y los resúmenes marcados como generados los escribe un modelo, y sí que "
         "pueden equivocarse.")
OCUPADO = "Gayo está atendiendo otra pregunta; intenta en un minuto"
SIMBOLOS = {"▲": "amplía", "▼": "restringe", "◆": "aclara", "✚": "nueva", "✖": "derogada"}

# Con nosniff, un tipo equivocado deja la imagen o la fuente sin cargar; no depender del sistema.
for _tipo, _ext in (("image/webp", ".webp"), ("font/woff2", ".woff2"), ("image/svg+xml", ".svg"),
                    ("text/javascript", ".js"), ("application/octet-stream", ".malla")):
    mimetypes.add_type(_tipo, _ext)
CLASES = {"▲": "amplia", "▼": "restringe", "◆": "aclara", "✚": "nueva", "✖": "derogada"}
ESTATICO = Path(__file__).parent / "estatico"
# Escaneos CC0 del Musée Saint-Raymond (Toulouse), reducidos con `portada/render_estatuas.py`.
ESTATUAS = [  # (archivo, pie)
    ("augusto", "Busto de Augusto con corona de encino"),
    ("septimio", "Busto de Septimio Severo con corona de encino"),
    ("hercules", "Hércules mata a Gerión, relieve de la villa de Chiragan"),
]
MONEDAS = [("aureo-augusto", "Áureo de Augusto", "Moneda de oro con el perfil de Augusto, impresa con trama de puntos."),
           ("sestercio-trajano", "Sestercio de Trajano", "Moneda de bronce con el busto de Trajano, impresa con trama de puntos.")]
CREDITO = ("Las estatuas y las monedas son escaneos del Musée Saint-Raymond de Toulouse, en dominio público (CC0), "
           "impresos aquí con un shader propio.")
# La T de la tablilla: el logo y el ícono de la pestaña.
LOGO = ('<svg viewBox="0 0 32 32" aria-hidden="true"><rect x="1.5" y="1.5" width="29" height="29" rx="2" fill="none" '
        'stroke="currentColor" stroke-width="1.4"/><path fill="currentColor" d="M8 8h16v5h-1.6c-.3-1.6-1-2.4-2.6-2.4h-1.6V22'
        'c0 1 .6 1.4 2 1.5V25h-8.4v-1.5c1.4-.1 2-.5 2-1.5V10.6h-1.6c-1.6 0-2.3.8-2.6 2.4H8z"/></svg>')
SECCIONES = (("/novellae", "Novellae"), ("/preguntar", "Gayo"), ("/#corpus", "Corpus"))


@functools.cache
def _version() -> str:
    """Huella de los estáticos: va en cada URL para que un cambio no espere a que caduque la caché (un día)."""
    h = hashlib.sha256()
    for f in sorted(ESTATICO.rglob("*")):
        if f.is_file():
            h.update(f.relative_to(ESTATICO).as_posix().encode() + f.read_bytes())
    return h.hexdigest()[:10]


def _e(ruta: str) -> str:
    """URL de un estático con su versión."""
    return f"/estatico/{ruta}?v={_version()}"


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


def _enlaces(actual: str) -> str:
    marca = ' aria-current="page"'
    return ('<nav class="enlaces" aria-label="Secciones">'
            + "".join(f'<a href="{r}"{marca if r == actual else ""}>{n}</a>' for r, n in SECCIONES) + "</nav>")


def _logo() -> str:
    return f'<a class="logo" href="/" aria-label="Tabularium, inicio">{LOGO}</a>'


def _pagina(titulo: str, cuerpo: str, actual: str = "", descripcion: str = "", portada: bool = False) -> str:
    """La portada trae su propio encabezado (logo y enlaces dentro de la composición); las demás, la barra."""
    meta = f'<meta name="description" content="{escape(descripcion)}">' if descripcion else ""
    js = f'<script type="module" src="{_e("portada.js")}"></script>' if portada else ""
    contenido = (f'<main id="contenido">{cuerpo}</main>' if portada else
                 f'<header class="barra">{_logo()}{_enlaces(actual)}</header><main id="contenido" class="interna">{cuerpo}</main>')
    return (f'<!doctype html><html lang="es-MX"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width, initial-scale=1">{meta}'
            f'<meta name="color-scheme" content="light dark">'
            f'<title>{escape(titulo)}</title><link rel="stylesheet" href="{_e("estilo.css")}">'
            f'<link rel="icon" href="{_e("sello.svg")}" type="image/svg+xml">{js}</head><body>'
            f'<a class="salto" href="#contenido">Saltar al contenido</a>{contenido}'
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


def _recientes(lista: list[dict], cuantos: int = 4) -> list[dict]:
    """Los últimos cambios, uno por renglón: primero lo que el DOF ya publicó y el corpus aún no tiene."""
    renglones = []
    for n in sorted(lista, key=lambda n: n["publicado_dof"], reverse=True):
        enlace = f'/novellae?desde={n["publicado_dof"]}&hasta={n["publicado_dof"]}#{_ancla(n)}'
        base = {"fecha": n["publicado_dof"], "enlace": enlace}
        if n["pendiente"]:
            docs = ", ".join(d["documento"] for d in n["documentos"])
            renglones.append({**base, "efecto": None, "generado": False, "donde": f"{docs}: ya salió en el DOF",
                              "frase": n["titulo"] or "Publicación del DOF"})
        for d in [] if n["pendiente"] else n["documentos"]:
            if d.get("nuevo"):
                renglones.append({**base, "efecto": "✚", "generado": False, "donde": d["documento"],
                                  "frase": f'Documento nuevo con {d["unidades"]} unidades.'})
            for c in d.get("cambios", []):
                frase = (_oracion(c["resumen"]) if c["resumen"] else
                         "Cambió el texto; la glosa todavía no está." if c["diff"] is not None else "Unidad nueva.")
                renglones.append({**base, "efecto": c["efecto"], "generado": c["efecto_generado"],
                                  "donde": ", ".join(c["cita"]["texto"].split(", ")[:2]), "frase": frase})
        if len(renglones) >= cuantos:
            break
    return renglones[:cuantos]


def _renglon(r: dict) -> str:
    return (f'<li class="revela">{_efecto(r["efecto"], r["generado"])}<a class="que" href="{escape(r["enlace"])}">'
            f'<span class="donde">{escape(r["donde"])}</span><span class="frase">{escape(r["frase"])}</span></a>'
            f'<time datetime="{r["fecha"]}">{_fecha_corta(r["fecha"])}</time></li>')


def _moneda(archivo: str, pie: str, alt: str) -> str:
    r = f"piezas/{archivo}"
    return (f'<figure class="moneda"><div class="lienzo" data-textura="{_e(r + ".webp")}" data-fija-claro="{_e(r + "-claro.webp")}" '
            f'data-fija-oscuro="{_e(r + "-oscuro.webp")}" data-tinta="--oro" data-celda="2.5" role="img" aria-label="{escape(alt)}">'
            f'<noscript><img src="{_e(r + "-claro.webp")}" alt="" width="512" height="512"></noscript></div>'
            f'<figcaption>{escape(pie)}</figcaption></figure>')


def _escena() -> str:
    """La estatua que gira: el script carga las mallas en orden; sin script, la imagen fija de la primera."""
    hoy = date.today().toordinal() % len(ESTATUAS)
    orden = ESTATUAS[hoy:] + ESTATUAS[:hoy]
    mallas = " ".join(_e(f"piezas/{a}.malla") for a, _ in orden)
    pies = escape(json.dumps([p for _, p in orden], ensure_ascii=False))
    primera = f"piezas/{orden[0][0]}"
    alt = "Estatua romana de mármol, impresa con trama de puntos, que gira despacio y cambia cada diez segundos."
    return (f'<figure class="escena"><div class="lienzo" data-mallas="{mallas}" data-pies="{pies}" '
            f'data-fija-claro="{_e(primera + "-claro.webp")}" data-fija-oscuro="{_e(primera + "-oscuro.webp")}" data-celda="3.6" '
            f'role="img" aria-label="{alt}"><noscript><img src="{_e(primera + "-claro.webp")}" alt=""></noscript></div>'
            f'<figcaption><span>{escape(orden[0][1])}</span>'
            f'<button class="pausa discreto" type="button" aria-pressed="false" hidden>Pausar el giro</button></figcaption></figure>')


def portada(request: Request) -> HTMLResponse:
    lista, documentos = _todas(request.app.state.db)
    n_docs, n_unidades, n_versiones, ultima = _cache["cifras"]
    renglones = "".join(_renglon(r) for r in _recientes(lista)) or "<li>Todavía no hay publicaciones.</li>"
    docs = "".join(f"<li><b>{escape(i)}</b><span>{escape(n)}</span></li>" for i, n in documentos)
    cuerpo = (
        f'<section class="portada">{_logo()}{_enlaces("/")}'
        f'<div class="encabezado"><h1 class="titulo">Tabularium</h1><hr class="filete">'
        f'<p class="bajada">Las leyes fiscales de México, versión por versión desde 2024 (porque lo que te toca pagar '
        f'depende del año, no de cómo amaneció la ley hoy).</p></div>'
        f'<div class="recientes"><h2>Lo que cambió hace poco</h2><ol class="cambios">{renglones}</ol>'
        f'<a class="todas" href="/novellae">Todas las Novellae, con el texto que se quitó y el que entró</a></div>'
        f'{_escena()}</section>'
        f'<section class="seccion gayo" aria-labelledby="titulo-gayo"><div><h2 id="titulo-gayo">Pregúntale a Gayo</h2>'
        f'<p>Gayo escribió el libro con que se enseñaba derecho en Roma. El de aquí es más modesto: contesta solo con lo '
        f'que puede citar (artículo, ley y la versión vigente en la fecha que elijas), y si no lo encuentra en el corpus, '
        f'prefiere callarse antes que inventar.</p></div>{_formulario()}</section>'
        f'<section id="corpus" class="seccion erario" aria-labelledby="titulo-corpus"><div>'
        f'<h2 id="titulo-corpus">Qué hay en el archivo</h2><dl class="cifras">'
        f'<div><dt>documentos</dt><dd>{n_docs}</dd></div><div><dt>artículos, reglas y secciones</dt><dd>{n_unidades:,}</dd></div>'
        f'<div><dt>versiones guardadas</dt><dd>{n_versiones:,}</dd></div></dl>'
        f'<p class="suave">Nada se sobrescribe: cada versión se queda con su vigencia y con el decreto que la cambió, así '
        f'que se puede preguntar por 2024 sin que conteste la ley de hoy. Última publicación incorporada: '
        f'{_fecha_corta(ultima) if ultima else "ninguna"}.</p>'
        f'<ul class="documentos">{docs}</ul></div>'
        f'<div class="monedas">{"".join(_moneda(*m) for m in MONEDAS)}</div></section>')
    return _respuesta(_pagina("Tabularium", cuerpo, "/", portada=True, descripcion=(
        "Las leyes fiscales de México versión por versión desde 2024, con cada reforma del DOF anunciada artículo por "
        "artículo y un asistente, Gayo, que solo responde con lo que puede citar.")))


def novellae_pagina(request: Request) -> HTMLResponse:
    q = request.query_params
    documento, desde, hasta = (q.get(k) or None for k in ("documento", "desde", "hasta"))
    try:
        fin = date.fromisoformat(hasta) if hasta else date.today()
        inicio = date.fromisoformat(desde) if desde else fin - timedelta(90)
    except (ValueError, OverflowError):  # OverflowError: "0001-01-01" menos 90 días
        return _respuesta(_pagina("Tabularium", "<h1>Novellae</h1><p>Esa fecha no es válida: usa AAAA-MM-DD.</p>", "/novellae"), 400)
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
    intro = ('<h1>Novellae</h1><p class="bajada">Cada publicación del DOF que toca el corpus, con el texto literal que '
             'se quitó y el que entró. Las etiquetas y los resúmenes los escribe un modelo (van marcados, por si acaso).</p>')
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


ALCANCE = ("Gayo responde solo con LISR, CFF, LIVA, la RMF y sus anexos, y cita cada pasaje. Si no lo puede citar, "
           "no responde. Tu pregunta no se guarda.")


def _formulario(pregunta: str = "", fecha: str = "") -> str:
    return (f'<form class="preguntar" method="post" action="/preguntar"><label>Tu pregunta<textarea name="pregunta" '
            f'rows="4" maxlength="{pg.LARGO_MAXIMO}" required placeholder="¿Qué porcentaje de una computadora se puede deducir?">'
            f'{escape(pregunta)}</textarea></label><div class="fila">'
            f'<label>Fecha del ejercicio<input type="date" name="fecha" min="2024-01-01" value="{escape(fecha)}"></label>'
            f'<button type="submit">Preguntar</button></div><p class="suave chica">{ALCANCE}</p></form>')


def _cita(c: dict) -> str:
    return f'{escape(c["texto"])}. <a href="{escape(c["fuente_url"])}">Fuente</a>'


def _resultado(r: pg.Respuesta) -> str:
    if r.texto:
        citas = "".join(f'<li><blockquote>{escape(c.texto)}</blockquote><p class="cita">{_cita(c.cita)}</p></li>'
                        for c in r.citas)
        return (f'<section class="respuesta"><p>{escape(r.texto)} <span class="generado">generado</span></p>'
                f'<p class="suave">Lo redactó Gayo, un modelo que corre en casa. Cada cita se verificó letra por letra '
                f'contra el texto vigente en la fecha.</p><ol>{citas}</ol></section>')
    if r.fallo:
        # El detalle (stderr del Baker, rutas) va a journald, no a quien visita.
        motivo = OCUPADO if r.fallo == OCUPADO else "Gayo no está disponible ahorita"
        lista = "".join(f'<li class="cita">{_cita(p["cita"])}</li>' for p in r.pasajes)
        return (f'<section class="respuesta"><p>No hay respuesta redactada ahora: {motivo}.</p>'
                f'<p>Estos son los artículos y reglas que encontró la búsqueda:</p><ol>{lista}</ol></section>')
    return ('<section class="respuesta"><p>El corpus no responde esto con citas que se puedan verificar, así que '
            'Gayo no contesta (callar es mejor que inventarse un artículo).</p></section>')


CABEZA_PREGUNTAR = ('<h1>Pregúntale a Gayo</h1><p class="bajada">Una pregunta general sobre la ley fiscal federal. '
                    'Gayo cita cada pasaje en la versión vigente en la fecha que elijas, y si no puede citarlo, no contesta.</p>')


def _preguntar(cuerpo: str, estado: int = 200) -> HTMLResponse:
    return _respuesta(_pagina("Tabularium: Gayo", CABEZA_PREGUNTAR + cuerpo, "/preguntar"), estado)


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
