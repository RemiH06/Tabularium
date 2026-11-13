"""Página pública de Tabularium (RF-12): las Novellae en HTML generado del lado del servidor.

Proceso aparte del MCP (RNF-07): escucha en 127.0.0.1 y lo publica Cloudflare Tunnel; el MCP se
queda en la tailnet. Solo lectura, sin cuentas ni datos de quien visita. Todo texto de la base
pasa por `escape`: el corpus viene de fuentes externas.
"""
from __future__ import annotations

import os
import threading
from contextlib import closing
from datetime import date, timedelta
from html import escape
from pathlib import Path

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, Response
from starlette.routing import Route

from . import almacen
from .almacen import documento_de
from .novellae import novellae
from .servidor import ruta_db

# Sin scripts de terceros ni estilos en línea: la política de contenido solo deja lo propio.
CABECERAS = {
    "Content-Security-Policy": "default-src 'none'; style-src 'self'; img-src 'self'; form-action 'self'; "
                               "base-uri 'none'; frame-ancestors 'none'",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
}
AVISO = ("Tabularium no sustituye a un abogado o contador que firme. El diff es el texto literal de cada versión; "
         "las etiquetas ▲ ▼ ◆ y los resúmenes marcados como generados los escribe un modelo y pueden equivocarse.")
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
label { display: flex; flex-direction: column; font-size: .85rem; }
input, select, button { font: inherit; padding: .25rem .4rem; }
article { border-top: 1px solid var(--linea); padding-bottom: .5rem; }
.cambio { margin: .75rem 0 1rem; }
.diff, .texto { white-space: pre-wrap; overflow-wrap: anywhere; }
del { color: var(--quita); }
ins { color: var(--agrega); text-decoration-thickness: 2px; }
.generado { font-size: .8rem; border: 1px solid var(--linea); padding: 0 .3rem; border-radius: .2rem; }
a { color: inherit; }
footer { margin: 2rem auto; color: var(--suave); font-size: .85rem; }
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
            f'<header><h1>Tabularium</h1><p class="suave">Novellae: qué cambió en las leyes fiscales de México '
            f'con cada publicación del DOF.</p></header><main>{cuerpo}</main><footer><p>{escape(AVISO)}</p></footer></body></html>')


def _respuesta(html: str, estado: int = 200) -> HTMLResponse:
    return HTMLResponse(html, status_code=estado, headers=CABECERAS)


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
    except ValueError:
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


def estilo(request: Request) -> Response:
    return Response(ESTILO, media_type="text/css", headers={**CABECERAS, "Cache-Control": "public, max-age=3600"})


def crear_app(db: Path | None = None) -> Starlette:
    app = Starlette(routes=[Route("/", portada), Route("/estilo.css", estilo)])
    app.state.db = db or ruta_db()
    return app


def servir() -> None:
    import uvicorn
    app = crear_app()
    _todas(app.state.db)  # la primera visita no paga el cálculo; tras la reconstrucción diaria, sí (una vez)
    # Solo loopback: la publica el túnel de Cloudflare, nunca un puerto abierto (RNF-07).
    uvicorn.run(app, host=os.environ.get("TABULARIUM_PAGINA_HOST", "127.0.0.1"),
                port=int(os.environ.get("TABULARIUM_PAGINA_PUERTO", "8062")), proxy_headers=False,
                access_log=False)  # sin IP ni consulta de quien visita (RNF-07, RNF-10)
