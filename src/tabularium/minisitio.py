"""Fuentes de la RMF y sus anexos 8 y 29, leídas de la página de cada año en el minisitio del SAT.

Los nombres de archivo no siguen un patrón (docs/fuentes.md, ficha 5), pero el texto de cada enlace
sí: "Compilado 3a. RM RMF 2026 (publicado el 02 de octubre de 2026)". De ahí salen el ordinal y la
fecha de publicación en el DOF. Una modificación nueva entra al corpus cuando el SAT sube su
compilada; mientras, su Novella queda pendiente (`novellae.pendientes`).

Las páginas se leen de la caché, como todo lo que usa `construir`: `tabularium descargar` las
refresca (`refrescar`).
"""
from __future__ import annotations

import re
from collections import defaultdict
from datetime import date
from urllib.error import HTTPError

from .almacen import CORTE
from .anexos import FuenteAnexo
from .construir import ruta_cache
from .ley import fecha_es
from .rmf import SAT, FuenteRmf

ENLACE = re.compile(r'<a href="([^"]+\.pdf)"[^>]*>(.*?)</a>\s*\((publicad[oa] el [^)]+)\)', re.S | re.I)
ORIGINAL = re.compile(r"^Resoluci[oó]n Miscel[aá]nea Fiscal para (\d{4})$")
MOD_RMF = re.compile(r"^(\d+)a\.? Resoluci[oó]n de Modificaciones a la RMF para (\d{4})$")
COMPILADA_RMF = re.compile(r"^Compilado (\d+)a\.? RM RMF (\d{4})$")
ANEXO = re.compile(r"^Anexo (8|29) de la RMF (\d{4})$")
COMPILADA_ANEXO = re.compile(r"^Compilado (\d+)a\.? Modificaci[oó]n Anexo (8|29) RMF (\d{4})$")

# Excepciones, por año, con el índice de la modificación (0 es la primera):
# - La "compilada" de la Segunda de 2024 (171 MB) no es la RMF: 663 páginas de otro texto, sin estilos.
#   Sus reglas salen de la siguiente compilada o de su publicación.
SIN_COMPILADA = {2024: {1}}
# - Publicaciones que hacen falta: la de 2024 por la compilada que no sirve; la de 2026 porque la
#   compilada omite su transitorio.
PUBLICADAS = {2024: {1}, 2026: {1}}


def pagina(anio: int) -> str:
    return f"{SAT}normatividad_rmf_rgce{anio}.html"


def enlaces(html: str) -> list[tuple[str, date, str]]:
    """(texto del enlace, fecha de publicación, URL) de cada PDF con fecha."""
    salida = []
    for url, texto, fecha in ENLACE.findall(html):
        texto = " ".join(re.sub(r"<[^>]+>", "", texto).split())
        salida.append((texto, fecha_es(fecha), url if url.startswith("http") else SAT + url))
    return salida


def anios_en_cache() -> list[int]:
    return [a for a in range(CORTE.year, date.today().year + 2) if ruta_cache(pagina(a)).exists()]


def fuentes(anios: list[int] | None = None) -> tuple[list[FuenteRmf], list[FuenteAnexo]]:
    """Las RMF desde el corte y sus anexos 8 y 29, de las páginas en la caché. Un año entra cuando
    su página lista la RMF original. Una modificación de anexo sin compilada corta la lista ahí."""
    originales, mods, compiladas, anexos, comp_anexos = {}, defaultdict(dict), defaultdict(dict), {}, defaultdict(dict)
    for a in anios if anios is not None else anios_en_cache():
        html = ruta_cache(pagina(a)).read_text(encoding="utf-8")
        for texto, fecha, url in enlaces(html):
            if m := ORIGINAL.match(texto):
                originales[int(m[1])] = (fecha, url)
            elif m := MOD_RMF.match(texto):
                mods[int(m[2])][int(m[1]) - 1] = url
            elif m := COMPILADA_RMF.match(texto):
                compiladas[int(m[2])][int(m[1]) - 1] = url
            # El texto del enlace puede mentir: en 2024, la compilada del Anexo 30 dice "Anexo 29".
            # El número tiene que estar también en el nombre del archivo.
            elif (m := ANEXO.match(texto)) and _nombra(url, m[1]):
                _poner(anexos, (int(m[1]), int(m[2])), (fecha, url))
            elif (m := COMPILADA_ANEXO.match(texto)) and _nombra(url, m[2]):
                _poner(comp_anexos[int(m[2]), int(m[3])], int(m[1]) - 1, (fecha, url))

    resoluciones = []
    for anio, (publicado, url) in sorted(originales.items()):
        if anio < CORTE.year:
            continue
        n = max(compiladas[anio], default=-1) + 1
        comp = tuple(None if k in SIN_COMPILADA.get(anio, ()) else compiladas[anio].get(k) for k in range(n))
        try:
            publicadas = {k: mods[anio][k] for k in PUBLICADAS.get(anio, ())}
        except KeyError as e:
            raise ValueError(f"RMF {anio}: la página ya no lista la publicación de la modificación {e.args[0] + 1}") from None
        resoluciones.append(FuenteRmf(anio, publicado, url, comp, publicadas))

    con_rmf = {r.anio for r in resoluciones}
    lista = []
    for (numero, anio), (publicado, url) in sorted(anexos.items()):
        if anio in con_rmf:
            hay, seguidas = comp_anexos[numero, anio], []
            while len(seguidas) in hay:
                seguidas.append(hay[len(seguidas)])
            lista.append(FuenteAnexo(numero, anio, publicado, url, tuple(seguidas)))
    return resoluciones, lista


def _nombra(url: str, numero: str) -> bool:
    return re.search(rf"Anexo[_-]?{numero}(?!\d)", url.rsplit("/", 1)[-1]) is not None


def _poner(d: dict, llave, valor) -> None:
    """Dos enlaces distintos para la misma pieza: no hay cómo escoger, falla en voz alta."""
    if d.get(llave, valor) != valor:
        raise ValueError(f"minisitio del SAT: dos enlaces para {llave}: {d[llave]} y {valor}")
    d[llave] = valor


def refrescar(cliente, hoy: date | None = None) -> list[int]:
    """Baja la página del año en curso y la del anterior (una compilada de diciembre puede subir en
    enero); en diciembre, también la del siguiente, que lista la RMF nueva. Las de años viejos, solo
    si faltan. Una página que todavía no existe (404) se salta."""
    hoy = hoy or date.today()
    bajadas = []
    for a in range(CORTE.year, hoy.year + (2 if hoy.month == 12 else 1)):
        if a >= hoy.year - 1 or not ruta_cache(pagina(a)).exists():
            try:
                cliente.bajar(pagina(a))
                bajadas.append(a)
            except HTTPError as e:
                if e.code != 404 or a <= hoy.year:
                    raise
    return bajadas
