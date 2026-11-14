"""Página pública de Tabularium (RF-12): las Novellae en HTML generado del lado del servidor.

Proceso aparte del MCP (RNF-07): escucha en 127.0.0.1 y lo publica Cloudflare Tunnel; el MCP se
queda en la tailnet. Solo lectura, sin cuentas ni datos de quien visita. Todo texto de la base
pasa por `escape`: el corpus viene de fuentes externas.
"""
from __future__ import annotations

import functools
import hashlib
import ipaddress
import logging
import secrets
import json
import mimetypes
import os
import re
import threading
import time
from collections import deque
from contextlib import closing
from dataclasses import dataclass, field
from datetime import date, timedelta
from html import escape
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import MutableHeaders
from starlette.requests import Request
from starlette.responses import HTMLResponse, RedirectResponse, Response
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from . import almacen
from . import preguntar as pg
from .almacen import documento_de
from .glosas import BakerCaido
from .novellae import novellae
from .construir import cache_dir
from .materias import MATERIAS, materia
from .servidor import ruta_db

# Sin scripts de terceros ni estilos en línea: la política de contenido solo deja lo propio. Las
# fuentes también se sirven desde aquí: pedirlas a otro sitio le daría la IP de quien visita.
CABECERAS = {
    "Content-Security-Policy": "default-src 'none'; style-src 'self'; img-src 'self'; script-src 'self'; "
                               "font-src 'self'; connect-src 'self'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'",
    "X-Content-Type-Options": "nosniff",
    # same-origin: nada sale hacia otros sitios. Con no-referrer el navegador manda "Origin: null" en
    # los POST del propio sitio y la revisión de abajo rechazaba toda consulta real (2026-11-14).
    "Referrer-Policy": "same-origin",
    # Por HTTP local el navegador la ignora; por el túnel (HTTPS) obliga a no volver a HTTP.
    "Strict-Transport-Security": "max-age=31536000",
}
AVISO = ("Tabularium es una herramienta de consulta y no sustituye la asesoría de un abogado o de un contador "
         "público. Los cambios se presentan con el texto literal de cada versión; las etiquetas ▲ ▼ ◆ y los resúmenes "
         "señalados como generados son elaborados por un modelo de lenguaje y pueden contener errores.")
OCUPADO = "Gayo está atendiendo otra consulta y no se liberó a tiempo; intente de nuevo en unos minutos"
SIMBOLOS = {"▲": "amplía", "▼": "restringe", "◆": "aclara", "✚": "nueva", "✖": "derogada"}

# Con nosniff, un tipo equivocado deja la imagen o la fuente sin cargar; no depender del sistema.
for _tipo, _ext in (("image/webp", ".webp"), ("font/woff2", ".woff2"), ("image/svg+xml", ".svg"),
                    ("text/javascript", ".js"), ("application/octet-stream", ".malla")):
    mimetypes.add_type(_tipo, _ext)
registro = logging.getLogger("tabularium.pagina")  # solo conteos y motivos, nunca la consulta
CLASES = {"▲": "amplia", "▼": "restringe", "◆": "aclara", "✚": "nueva", "✖": "derogada"}
ESTATICO = Path(__file__).parent / "estatico"
# Escaneos CC0 del Musée Saint-Raymond (Toulouse), reducidos con `portada/render_estatuas.py`.
ESTATUAS = [  # (archivo, pie)
    ("augusto", "Busto de Augusto con corona de encino"),
    ("septimio", "Busto de Septimio Severo con corona de encino"),
    ("hercules", "Hércules mata a Gerión, relieve de la villa de Chiragan"),
]
CREDITO = ("Las esculturas reproducidas son digitalizaciones del Musée Saint-Raymond de Toulouse, de dominio "
           "público (CC0).")
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


def _sello(documento: str, unidad: str | None = None) -> str:
    m = materia(documento, unidad)
    return f'<abbr class="sello" title="{MATERIAS[m]}">{m}</abbr>' if m else ""


def _cambio(c: dict, documento: str) -> str:
    marca = ' <span class="generado">generado</span>' if c["efecto_generado"] else ""
    partes = [f'<h4>{_efecto(c["efecto"], c["efecto_generado"])} {escape(c["unidad"])} {_sello(documento, c["unidad"])}{marca}</h4>']
    if c["resumen"]:
        partes.append(f'<p>{escape(c["resumen"])} <span class="generado">generado por {escape(c["modelo"] or "un modelo")}</span></p>')
    if c["diff"] is not None:
        tramos = {"=": "{}", "-": "<del>{}</del>", "+": "<ins>{}</ins>"}
        partes.append('<p class="diff">' + "".join(tramos[op].format(escape(t)) for op, t in c["diff"]) + "</p>")
    elif c["texto"]:
        partes.append(f'<details><summary>Texto de la disposición nueva</summary><p class="texto">{escape(c["texto"])}</p></details>')
    if c["junta"]:
        partes.append(f'<p class="suave">Esta versión incorpora también: {escape(", ".join(c["junta"]))}.</p>')
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
        partes.append(f"<p>Publicado en el DOF; el texto aún no se incorpora al corpus ({escape(docs)}).</p>")
    for d in [] if n["pendiente"] else n["documentos"]:
        partes.append(f'<section><h3>{escape(d["nombre"])} ({escape(d["documento"])})</h3>')
        if d["nuevo"]:
            partes.append(f'<p>Documento nuevo: {d["unidades"]} disposiciones, vigente desde {escape(d["vigente_desde"])}.</p>')
        else:
            partes.extend(_cambio(c, d["documento"]) for c in d["cambios"])
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


def _pagina(titulo: str, cuerpo: str, actual: str = "", descripcion: str = "", portada: bool = False,
            refrescar: int = 0, scripts: tuple[str, ...] = ()) -> str:
    """La portada trae su propio encabezado (logo y enlaces dentro de la composición); las demás, la barra."""
    meta = f'<meta name="description" content="{escape(descripcion)}">' if descripcion else ""
    if refrescar:  # sin JavaScript: la página de una consulta en curso se vuelve a pedir sola
        meta += f'<meta http-equiv="refresh" content="{refrescar}">'
    js = "".join(f'<script type="module" src="{_e(n)}"></script>' for n in (("portada.js",) if portada else ()) + scripts)
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
MESES_LARGOS = ("enero febrero marzo abril mayo junio julio agosto septiembre octubre noviembre diciembre").split()


def _fecha_larga(d: date) -> str:
    return f"{d.day} de {MESES_LARGOS[d.month - 1]} de {d.year}"


def _revision(db: Path) -> date:
    """Cuándo se revisaron las fuentes por última vez: la corrida diaria deja cada petición en el registro
    de descargas aunque no haya nada nuevo; la base solo cambia cuando lo hay."""
    rutas = [db, cache_dir() / "_log.jsonl"]
    return date.fromtimestamp(max(r.stat().st_mtime for r in rutas if r.exists()))


METODO = (
    ("Leyes", "Ley del Impuesto sobre la Renta, Código Fiscal de la Federación y Ley del Impuesto al Valor Agregado, "
     "tomadas del portal de leyes federales vigentes de la Cámara de Diputados. La versión al 1 de enero de 2024 se "
     "contrastó con copias fechadas de esa época.", "https://www.diputados.gob.mx/LeyesBiblio/index.htm"),
    ("Resolución Miscelánea Fiscal", "Ediciones de 2024 a 2026, con sus modificaciones y los anexos 8, 20 y 29, a partir "
     "de las versiones compiladas que publica el Servicio de Administración Tributaria.", "https://www.sat.gob.mx"),
    ("Diario Oficial de la Federación", "Revisión diaria mediante el servicio de datos abiertos del DOF. Cada publicación "
     "que modifica el corpus genera una Novella; mientras su texto no se incorpora, figura como pendiente.",
     "https://www.dof.gob.mx"),
    ("Vigencia", "Se determina conforme a los artículos transitorios de cada decreto y no por la fecha de publicación. "
     "Las notas de reforma que la Cámara intercala en el texto se conservan como datos de la versión, no como texto "
     "normativo.", None),
    ("Citas", "Cada resultado indica el ordenamiento, el artículo o la regla, la fecha de inicio de vigencia, el decreto "
     "que dio origen a la versión y el vínculo a la fuente oficial.", None),
    ("Interpretación", "Las etiquetas de efecto (▲ amplía, ▼ restringe, ◆ aclara) y los resúmenes se generan con un modelo "
     "de lenguaje desde la perspectiva del contribuyente y se señalan como tales. El texto comparado siempre es literal.",
     None),
)


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
            renglones.append({**base, "efecto": None, "generado": False, "donde": f"{docs}: publicado en el DOF",
                              "frase": n["titulo"] or "Publicación del DOF",
                              "sello": _sello(n["documentos"][0]["documento"]) if n["documentos"] else ""})
        for d in [] if n["pendiente"] else n["documentos"]:
            if d.get("nuevo"):
                renglones.append({**base, "efecto": "✚", "generado": False, "donde": d["documento"],
                                  "frase": f'Documento nuevo con {d["unidades"]} disposiciones.', "sello": _sello(d["documento"])})
            for c in d.get("cambios", []):
                frase = (_oracion(c["resumen"]) if c["resumen"] else
                         "Texto modificado; resumen pendiente." if c["diff"] is not None else "Disposición nueva.")
                renglones.append({**base, "efecto": c["efecto"], "generado": c["efecto_generado"],
                                  "donde": ", ".join(c["cita"]["texto"].split(", ")[:2]), "frase": frase,
                                  "sello": _sello(d["documento"], c["unidad"])})
        if len(renglones) >= cuantos:
            break
    return renglones[:cuantos]


def _renglon(r: dict) -> str:
    return (f'<li class="revela">{_efecto(r["efecto"], r["generado"])}<a class="que" href="{escape(r["enlace"])}">'
            f'<span class="donde">{escape(r["donde"])} {r["sello"]}</span><span class="frase">{escape(r["frase"])}</span></a>'
            f'<time datetime="{r["fecha"]}">{_fecha_corta(r["fecha"])}</time></li>')


def _escena() -> str:
    """La estatua que gira: el script carga las mallas en orden; sin script, la imagen fija de la primera."""
    hoy = date.today().toordinal() % len(ESTATUAS)
    orden = ESTATUAS[hoy:] + ESTATUAS[:hoy]
    mallas = " ".join(_e(f"piezas/{a}.malla") for a, _ in orden)
    pies = escape(json.dumps([p for _, p in orden], ensure_ascii=False))
    primera = f"piezas/{orden[0][0]}"
    alt = "Escultura romana de mármol, reproducida con trama de puntos, que gira lentamente y cambia cada diez segundos."
    return (f'<figure class="escena"><div class="lienzo" data-mallas="{mallas}" data-pies="{pies}" '
            f'data-fija-claro="{_e(primera + "-claro.webp")}" data-fija-oscuro="{_e(primera + "-oscuro.webp")}" data-celda="3.6" '
            f'role="img" aria-label="{alt}"><noscript><img src="{_e(primera + "-claro.webp")}" alt=""></noscript></div>'
            f'<figcaption><span>{escape(orden[0][1])}</span>'
            f'<button class="pausa discreto" type="button" aria-pressed="false" hidden>Detener el giro</button></figcaption></figure>')


def _por_materia(lista: list[dict], sigla: str | None) -> list[dict]:
    """Solo los cambios de esa materia; una publicación sin ninguno sale de la lista. Las pendientes y los
    documentos nuevos cuentan por la materia de su documento."""
    if not sigla:
        return lista
    salida = []
    for n in lista:
        docs = []
        for d in n["documentos"]:
            if n["pendiente"] or d.get("nuevo"):
                if materia(d["documento"]) == sigla:
                    docs.append(d)
            elif cambios := [c for c in d["cambios"] if materia(d["documento"], c["unidad"]) == sigla]:
                docs.append({**d, "cambios": cambios})
        if docs:
            salida.append({**n, "documentos": docs})
    return salida


def portada(request: Request) -> HTMLResponse:
    lista, documentos = _todas(request.app.state.db)
    n_docs, n_unidades, n_versiones, ultima = _cache["cifras"]
    revision = _fecha_larga(_revision(request.app.state.db))
    enlace = ' <a href="{}">Fuente oficial</a>'
    metodo = "".join(f'<div><dt>{t}</dt><dd>{escape(d)}{enlace.format(u) if u else ""}</dd></div>' for t, d, u in METODO)
    renglones = "".join(_renglon(r) for r in _recientes(lista)) or "<li>Sin publicaciones registradas.</li>"
    docs = "".join(f'<li><a href="/documento/{escape(i)}"><b>{escape(i)}</b><span>{escape(n)}</span></a></li>'
                   for i, n in documentos)
    cuerpo = (
        f'<section class="portada">{_logo()}{_enlaces("/")}'
        f'<div class="encabezado"><h1 class="titulo">Tabularium</h1><hr class="filete">'
        f'<p class="bajada">Legislación fiscal federal de México, con cada versión conservada desde el 1 de enero de '
        f'2024 y su vigencia acreditada por el decreto que la reformó.</p></div>'
        f'<div class="recientes"><h2>Publicaciones recientes en el DOF</h2>'
        f'<p class="revision">Fuentes revisadas el {revision}.</p><ol class="cambios">{renglones}</ol>'
        f'<a class="todas" href="/novellae">Consultar todas las Novellae, con el texto suprimido y el incorporado</a></div>'
        f'{_escena()}</section>'
        f'<section class="seccion gayo" aria-labelledby="titulo-gayo"><div><h2 id="titulo-gayo">Consultas a Gayo</h2>'
        f'<p>Gayo responde consultas generales sobre la legislación fiscal federal. Cada afirmación se sustenta en una '
        f'cita textual (ordenamiento, artículo y versión vigente en la fecha de referencia), verificada contra el corpus '
        f'antes de mostrarse. Cuando no encuentra fundamento citable, se abstiene de responder.</p>'
        f'<p class="chica">Su nombre alude al jurista romano autor de las <i>Instituciones</i>.</p></div>{_formulario()}</section>'
        f'<section id="corpus" class="seccion erario" aria-labelledby="titulo-corpus">'
        f'<h2 id="titulo-corpus">Contenido del corpus</h2><dl class="cifras">'
        f'<div><dt>documentos</dt><dd>{n_docs}</dd></div><div><dt>artículos, reglas y apartados</dt><dd>{n_unidades:,}</dd></div>'
        f'<div><dt>versiones guardadas</dt><dd>{n_versiones:,}</dd></div></dl>'
        f'<p class="suave">Ninguna versión se sobrescribe: cada una conserva su periodo de vigencia y el decreto que la '
        f'modificó, de modo que una consulta referida a 2024 se responde con el texto vigente en 2024. Última '
        f'publicación incorporada: '
        f'{_fecha_corta(ultima) if ultima else "ninguna"}.</p>'
        f'<p class="suave">Cada documento enlaza a su fuente oficial y permite descargar el texto vigente en cualquier fecha.</p>'
        f'<ul class="documentos">{docs}</ul></section>'
        f'<section id="metodo" class="seccion metodo" aria-labelledby="titulo-metodo"><h2 id="titulo-metodo">Fuentes y '
        f'método</h2><dl>{metodo}</dl></section>')
    return _respuesta(_pagina("Tabularium", cuerpo, "/", portada=True, scripts=("consulta.js",), descripcion=(
        "Legislación fiscal federal de México versionada desde 2024 (LISR, CFF, LIVA, RMF y anexos), con las reformas "
        "publicadas en el DOF y consultas respondidas con citas textuales.")))


def novellae_pagina(request: Request) -> HTMLResponse:
    q = request.query_params
    documento, desde, hasta = (q.get(k) or None for k in ("documento", "desde", "hasta"))
    sigla = q.get("materia") if q.get("materia") in MATERIAS else None
    try:
        fin = date.fromisoformat(hasta) if hasta else date.today()
        inicio = date.fromisoformat(desde) if desde else fin - timedelta(90)
    except (ValueError, OverflowError):  # OverflowError: "0001-01-01" menos 90 días
        return _respuesta(_pagina("Tabularium", "<h1>Novellae</h1><p>Fecha no válida; use el formato AAAA-MM-DD.</p>", "/novellae"), 400)
    lista, documentos = _todas(request.app.state.db)
    elegido = documento_de(documento, fin.isoformat()) if documento else None
    lista = _por_materia(_filtrar(lista, inicio.isoformat(), fin.isoformat(), elegido), sigla)
    opciones = "".join(f'<option value="{escape(i)}"{" selected" if i == elegido else ""}>{escape(i)}: {escape(n)}</option>'
                       for i, n in documentos)
    filtro = (f'<form class="filtro" method="get" action="/novellae"><label>Documento<select name="documento">'
              f'<option value="">Todos</option>{opciones}</select></label>'
              f'<label>Materia<select name="materia"><option value="">Todas</option>'
              + "".join(f'<option value="{m}"{" selected" if m == sigla else ""}>{m}: {n}</option>' for m, n in MATERIAS.items())
              + '</select></label>'
              f'<label>Desde<input type="date" name="desde" min="2024-01-01" value="{escape(desde or "")}"></label>'
              f'<label>Hasta<input type="date" name="hasta" min="2024-01-01" value="{escape(hasta or "")}"></label>'
              f'<button type="submit">Filtrar</button></form>')
    rango = "" if desde or hasta else '<p class="suave">Publicaciones de los últimos 90 días.</p>'
    cuerpo = "".join(_novella(n) for n in lista) or "<p>No hay publicaciones en el periodo seleccionado.</p>"
    intro = ('<h1>Novellae</h1><p class="bajada">Cada publicación del DOF que modifica el corpus, con el texto literal '
             'suprimido y el incorporado. Las etiquetas y los resúmenes son generados por un modelo de lenguaje y se '
             'identifican como tales.</p>')
    return _respuesta(_pagina("Tabularium: Novellae", intro + filtro + rango + cuerpo, "/novellae",
                              descripcion="Las reformas fiscales del DOF, artículo por artículo, con el diff literal."))


def _documento(request: Request) -> tuple[str, str] | None:
    """(id, nombre) del documento de la ruta, si existe en el corpus."""
    _, documentos = _todas(request.app.state.db)
    return next(((i, n) for i, n in documentos if i == request.path_params["documento"]), None)


def documento_pagina(request: Request) -> HTMLResponse:
    doc = _documento(request)
    if doc is None:
        return _respuesta(_pagina("Tabularium", "<h1>Documento no encontrado</h1><p>El corpus no contiene ese documento. "
                                  '<a href="/#corpus">Consultar la lista de documentos</a>.</p>', "/#corpus"), 404)
    ident, nombre = doc
    with closing(almacen.abrir(request.app.state.db)) as con:
        fechas = almacen.fechas_documento(con, ident)
        fuente = con.execute("SELECT fuente_url FROM versiones WHERE documento = ? ORDER BY id DESC LIMIT 1",
                             (ident,)).fetchone()
    renglones = []
    for f in fechas:
        origen = "; ".join(
            "Texto base del corpus" if f["vigente_desde"] == almacen.CORTE.isoformat() and d["publicado_dof"] < f["vigente_desde"]
            else f'{escape(d["titulo"] or d["id"])} (DOF del {_fecha_larga(date.fromisoformat(d["publicado_dof"]))})'
            for d in f["decretos"])
        renglones.append(
            f'<li><span class="fecha">{_fecha_larga(date.fromisoformat(f["vigente_desde"]))}</span>'
            f'<span class="origen">{origen}<span class="suave chica"> · {f["unidades"]:,} '
            f'{"disposición" if f["unidades"] == 1 else "disposiciones"}</span></span>'
            f'<a class="bajar" href="/documento/{escape(ident)}/texto?fecha={f["vigente_desde"]}">Texto vigente (.txt)</a></li>')
    fuente_html = f'<p><a href="{escape(fuente["fuente_url"])}">Fuente oficial</a></p>' if fuente else ""
    sello = _sello(ident) if materia(ident) != ident else ""
    cuerpo = (f'<h1>{escape(nombre)}</h1><p class="suave">{escape(ident)} {sello}</p><p class="bajada">Versiones conservadas en '
              f'el corpus, con la fecha en que cada una entró en vigor y la publicación que le dio origen.</p>{fuente_html}'
              f'<form class="filtro" method="get" action="/documento/{escape(ident)}/texto"><label>Texto vigente en la fecha'
              f'<input type="date" name="fecha" min="{almacen.CORTE.isoformat()}" required></label>'
              f'<button type="submit">Descargar (.txt)</button></form>'
              f'<h2>Versiones</h2><ol class="versiones">{"".join(renglones)}</ol>'
              f'<p class="suave chica">Cada archivo reúne las disposiciones vigentes en la fecha indicada, tal como constan en '
              f'el corpus. No sustituye la publicación oficial en el Diario Oficial de la Federación.</p>')
    return _respuesta(_pagina(f"Tabularium: {nombre}", cuerpo, "/#corpus",
                              descripcion=f"{nombre}: versiones desde 2024 y texto vigente en cualquier fecha."))


def documento_texto(request: Request) -> Response:
    """El documento completo vigente en una fecha, en texto plano: lo que un despacho guarda en su expediente."""
    doc = _documento(request)
    try:
        fecha = date.fromisoformat(request.query_params.get("fecha", ""))
    except ValueError:
        fecha = None
    if doc is None or fecha is None or fecha < almacen.CORTE:
        return _respuesta(_pagina("Tabularium", "<h1>Texto no disponible</h1><p>Indique un documento del corpus y una fecha "
                                  "a partir del 1 de enero de 2024, en formato AAAA-MM-DD.</p>", "/#corpus"), 400)
    ident, nombre = doc
    with closing(almacen.abrir(request.app.state.db)) as con:
        unidades = almacen.texto_documento(con, ident, fecha.isoformat())
    if not unidades:
        return _respuesta(_pagina("Tabularium", f"<h1>Texto no disponible</h1><p>{escape(nombre)} no tiene disposiciones "
                                  f"vigentes el {_fecha_larga(fecha)}.</p>", "/#corpus"), 404)
    lineas = [f"{nombre} ({ident})", f"Texto vigente al {_fecha_larga(fecha)}, reunido por Tabularium a partir de las "
              "versiones de su corpus.", "No sustituye la publicación oficial en el Diario Oficial de la Federación.",
              f"Fuente oficial: {unidades[-1]['fuente_url']}", f"Generado el {_fecha_larga(date.today())}.", ""]
    previa: list[str] = []
    transitorios = False
    for u in unidades:
        if u["unidad"].startswith("Transitorio") and not transitorios:
            lineas += ["", "TRANSITORIOS", ""]
            transitorios, previa = True, []
        niveles = [n for n in u["jerarquia"].split(" > ") if n]
        nuevos = [n for k, n in enumerate(niveles) if niveles[:k + 1] != previa[:k + 1]]
        if nuevos:
            lineas += ["", *nuevos, ""]
        previa = niveles
        lineas += [u["texto"].strip(), ""]
    nombre_archivo = f"{ident}_{fecha.isoformat()}.txt"
    return Response("\n".join(lineas), media_type="text/plain; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{nombre_archivo}"'})


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
ESPERA_MODELO = 240  # segundos que una consulta hace fila para redactar; corre aparte, nadie espera en el POST
# Búsquedas a la vez: cada una embebe la consulta en la CPU de la Pi. El turno se suelta al terminar la
# búsqueda, no la redacción.
_en_proceso = threading.BoundedSemaphore(2)
ESPERA = 30  # segundos que una consulta espera turno de búsqueda antes de recibir 503


def _un_turno(llamar):
    def turno(tarea: str, archivo: str) -> dict:
        if not _modelo.acquire(timeout=ESPERA_MODELO):
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
    """Otro sitio no puede mandar consultas en nombre de quien lo visita (gastaría su cuota y le
    mostraría un texto dictado). Sec-Fetch-Site, que mandan todos los navegadores actuales, decide; si
    falta, se compara Origin con Host. "Origin: null" (iframes aislados, o una política no-referrer)
    no prueba nada y solo pasa si Sec-Fetch-Site dice que es el mismo sitio."""
    sitio, origen = request.headers.get("sec-fetch-site"), request.headers.get("origin")
    if sitio:
        return sitio in ("same-origin", "none")
    if not origen:
        return True
    return origen != "null" and urlsplit(origen).netloc == request.headers.get("host")


ALCANCE = ("Gayo responde únicamente con base en la LISR, el CFF, la LIVA, la RMF y sus anexos, y cita cada pasaje. "
           "Sin fundamento citable, no emite respuesta. Las consultas no se almacenan.")


def _formulario(pregunta: str = "", fecha: str = "") -> str:
    return (f'<form class="preguntar" method="post" action="/preguntar"><label>Consulta<textarea name="pregunta" '
            f'rows="4" maxlength="{pg.LARGO_MAXIMO}" required placeholder="¿Qué porcentaje de deducción corresponde al equipo de cómputo?">'
            f'{escape(pregunta)}</textarea></label><div class="fila">'
            f'<label>Fecha de referencia<input type="date" name="fecha" min="2024-01-01" value="{escape(fecha)}"></label>'
            f'<button type="submit">Consultar</button><span class="atajo chica suave" hidden>Enter envía la consulta; '
            f'Mayús + Enter inserta un salto de línea.</span></div><p class="suave chica">{ALCANCE}</p></form>')


def _cita(c: dict) -> str:
    return f'{escape(c["texto"])}. <a href="{escape(c["fuente_url"])}">Fuente</a>'


def _resultado(r: pg.Respuesta) -> str:
    if r.texto:
        citas = "".join(f'<li><blockquote>{escape(c.texto)}</blockquote><p class="cita">{_cita(c.cita)}</p></li>'
                        for c in r.citas)
        return (f'<section class="respuesta"><p>{escape(r.texto)} <span class="generado">generado</span></p>'
                f'<p class="suave">Respuesta redactada por Gayo, un modelo de lenguaje ejecutado localmente. Cada cita '
                f'fue verificada textualmente contra la versión vigente en la fecha de referencia.</p><ol>{citas}</ol></section>')
    if r.fallo:
        # El detalle (stderr del Baker, rutas) va a journald, no a quien visita.
        motivo = OCUPADO if r.fallo == OCUPADO else "Gayo no está disponible en este momento"
        return (f'<section class="respuesta"><p>No fue posible redactar una respuesta: {motivo}.</p>'
                f'{_pasajes(r)}</section>')
    return ('<section class="respuesta"><p>No se encontró fundamento citable en el corpus para esta consulta; '
            'Gayo se abstiene de responder.</p></section>')


def _pasajes(r: pg.Respuesta) -> str:
    if not r.pasajes:
        return ""
    lista = "".join(f'<li class="cita">{_cita(p["cita"])}</li>' for p in r.pasajes)
    return f'<p>Disposiciones localizadas por la búsqueda:</p><ol>{lista}</ol>'


CABEZA_PREGUNTAR = ('<h1>Consultas a Gayo</h1><p class="bajada">Consultas generales sobre la legislación fiscal federal, '
                    'respondidas con citas textuales de la versión vigente en la fecha de referencia. Cuando no '
                    'encuentra fundamento citable, Gayo se abstiene de responder.</p>')


def _preguntar(cuerpo: str, estado: int = 200, refrescar: int = 0) -> HTMLResponse:
    return _respuesta(_pagina("Tabularium: Gayo", CABEZA_PREGUNTAR + cuerpo, "/preguntar", refrescar=refrescar,
                              scripts=("consulta.js",)), estado)


def preguntar_get(request: Request) -> HTMLResponse:
    return _preguntar(_formulario())


# Una consulta tarda de segundos a un par de minutos (el modelo corre en Pixilate), y Cloudflare corta
# toda petición a los 100 s. Por eso la consulta corre aparte y tiene su propia página, que se recarga
# sola hasta que hay respuesta. La pregunta vive solo en memoria y solo mientras dura (RNF-10).
VIDA = 900  # segundos que se conserva una consulta terminada
MAXIMO_TRABAJOS = 200
ESPERA_INICIAL = 4.0  # lo que el POST espera antes de redirigir: lo rápido (callar, Baker caído) sale directo


@dataclass
class Trabajo:
    pregunta: str
    fecha: str
    creado: float = field(default_factory=time.monotonic)
    respuesta: pg.Respuesta | None = None  # con pasajes en cuanto los hay
    listo: threading.Event = field(default_factory=threading.Event)


class Trabajos:
    def __init__(self):
        self.todos: dict[str, Trabajo] = {}
        self.candado = threading.Lock()

    def nuevo(self, pregunta: str, fecha: str) -> tuple[str, Trabajo]:
        with self.candado:
            ahora = time.monotonic()
            self.todos = {k: t for k, t in self.todos.items() if ahora - t.creado < VIDA}
            while len(self.todos) >= MAXIMO_TRABAJOS:  # el más viejo primero
                self.todos.pop(next(iter(self.todos)))
            clave = secrets.token_urlsafe(16)  # imposible de adivinar: solo quien preguntó ve su consulta
            self.todos[clave] = t = Trabajo(pregunta, fecha)
            return clave, t

    def ver(self, clave: str) -> Trabajo | None:
        with self.candado:
            t = self.todos.get(clave)
            return t if t and time.monotonic() - t.creado < VIDA else None


def _trabajar(app_state, t: Trabajo) -> None:
    turno = [True]  # el de búsqueda, que tomó el POST

    def soltar():
        if turno.pop() if turno else False:
            _en_proceso.release()

    def avisar(r):
        t.respuesta = r
        soltar()  # la búsqueda terminó; la redacción hace su propia fila
    try:
        with closing(almacen.abrir(app_state.db)) as con:
            t.respuesta = pg.preguntar(con, t.pregunta, t.fecha or None, _un_turno(app_state.llamar), avisar=avisar)
    except Exception:  # noqa: BLE001 (un hilo sin manejo deja la página esperando para siempre)
        registro.exception("consulta fallida")
        t.respuesta = pg.Respuesta(fallo="error interno", pasajes=t.respuesta.pasajes if t.respuesta else [])
    finally:
        soltar()
        t.listo.set()


async def preguntar_post(request: Request) -> Response:
    cuerpo = b""
    async for trozo in request.stream():
        cuerpo += trozo
        if len(cuerpo) > CUERPO_MAXIMO:
            registro.info("consulta rechazada motivo=larga")
            return _preguntar("<p>La consulta excede la extensión permitida.</p>", 413)
    datos = parse_qs(cuerpo.decode("utf-8", "replace"))
    pregunta, fecha = (datos.get(k, [""])[0].strip() for k in ("pregunta", "fecha"))
    try:
        pg.normalizar(pregunta, fecha or None)
    except ValueError as e:
        registro.info("consulta rechazada motivo=invalida")
        return _preguntar(_formulario(pregunta[:pg.LARGO_MAXIMO], fecha) + f"<p>{escape(str(e)).capitalize()}.</p>", 400)
    if not _mismo_sitio(request):
        registro.info("consulta rechazada motivo=otro_sitio")
        return _preguntar("<p>La consulta debe enviarse desde este sitio.</p>", 403)
    ip = request.headers.get("cf-connecting-ip") or (request.client.host if request.client else "")
    if not request.app.state.limite.permitir(_llave(ip)):
        registro.info("consulta rechazada motivo=limite")
        return _preguntar(_formulario(pregunta, fecha)
                          + "<p>Se alcanzó el límite de consultas; intente de nuevo en unos minutos.</p>", 429)
    if not await run_in_threadpool(_en_proceso.acquire, True, ESPERA):
        registro.info("consulta rechazada motivo=ocupado")
        return _preguntar(_formulario(pregunta, fecha)
                          + "<p>Hay demasiadas consultas en curso; intente de nuevo en un momento.</p>", 503)
    clave, t = request.app.state.trabajos.nuevo(pregunta, fecha)
    threading.Thread(target=_trabajar, args=(request.app.state, t), daemon=True).start()
    await run_in_threadpool(t.listo.wait, request.app.state.espera_inicial)
    return RedirectResponse(f"/preguntar/{clave}", status_code=303)


def consulta_get(request: Request) -> HTMLResponse:
    t = request.app.state.trabajos.ver(request.path_params["clave"])
    if t is None:
        return _preguntar('<p>Esta consulta ya no está disponible: las consultas se conservan quince minutos y no '
                          'se almacenan. Puede formularla de nuevo.</p>' + _formulario(), 404)
    pregunta = f'<p class="suave">Consulta: «{escape(t.pregunta)}»{" (referida al " + escape(t.fecha) + ")" if t.fecha else ""}</p>'
    if t.listo.is_set():
        return _preguntar(pregunta + _resultado(t.respuesta) + _formulario(t.pregunta, t.fecha))
    espera = int(time.monotonic() - t.creado)
    aviso = ("Gayo está redactando la respuesta; esta página se actualiza sola." if espera < 60 else
             "La redacción está tardando más de lo habitual; esta página se sigue actualizando.")
    avance = _pasajes(t.respuesta) if t.respuesta else '<p class="suave">Buscando en el corpus…</p>'
    return _preguntar(f'{pregunta}<section class="respuesta" aria-live="polite"><p>{aviso}</p>{avance}</section>',
                      refrescar=4)


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
                            Route("/preguntar/{clave}", consulta_get),
                            Route("/documento/{documento}", documento_pagina),
                            Route("/documento/{documento}/texto", documento_texto),
                            Mount("/estatico", StaticFiles(directory=ESTATICO), name="estatico")])
    app.state.db, app.state.llamar, app.state.limite = db or ruta_db(), llamar, Limite()
    app.state.trabajos, app.state.espera_inicial = Trabajos(), ESPERA_INICIAL
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
