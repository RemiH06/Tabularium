"""Construye la base versionada desde la caché de documentos fuente.

Por cada ley: la línea base (texto vigente al corte) y el texto vigente de hoy. Un artículo que
cambió entre las dos recibe una versión por cada fecha de vigencia de sus reformas, con la que fija
el transitorio de cada decreto (o `vigencias.PUBLICACIONES`), y la versión base se cierra el día de
la primera. Las versiones intermedias salen de `vigencias.INTERMEDIAS`.
"""
from __future__ import annotations

import os
import re
import sqlite3
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit

from . import almacen
from .almacen import CORTE
from .doc import texto_doc
from .ley import Decreto, Ley, Unidad, segmentar
from .vigencias import MISMO_DIA, PUBLICACIONES, deshacer, intermedia


@dataclass(frozen=True)
class Fuente:
    documento: str
    nombre: str
    base_url: str  # copia fechada vigente al corte
    actual_url: str


LEYES_BIBLIO = "https://www.diputados.gob.mx/LeyesBiblio/doc/{}.doc"
FUENTES = [
    # LIVA no se reforma desde el DOF 12-11-2021: su texto vigente es su línea base.
    Fuente("LIVA", "Ley del Impuesto al Valor Agregado", LEYES_BIBLIO.format("LIVA"), LEYES_BIBLIO.format("LIVA")),
    # Copia de archive.org del 2022-04-04: la LISR no se reformó entre esa fecha y el corte.
    Fuente("LISR", "Ley del Impuesto sobre la Renta",
           "https://web.archive.org/web/20220404202127id_/" + LEYES_BIBLIO.format("LISR"), LEYES_BIBLIO.format("LISR")),
    # Copia de archive.org del 2024-04-05: entre el corte y esa fecha no hay notas de reforma.
    Fuente("CFF", "Código Fiscal de la Federación",
           "https://web.archive.org/web/20240405093745id_/" + LEYES_BIBLIO.format("CFF"), LEYES_BIBLIO.format("CFF")),
]


def cache_dir() -> Path:
    return Path(os.environ.get("TABULARIUM_CACHE", "cache"))


def ruta_cache(url: str) -> Path:
    """Misma convención que el cliente de la iteración 0: cache/<host>/<ruta saneada>."""
    u = urlsplit(url)
    nombre = (u.path.strip("/") or "index") + ("__" + u.query if u.query else "")
    return cache_dir() / u.netloc.replace(":", "_") / re.sub(r"[^A-Za-z0-9._-]+", "_", nombre)[:160]


def leer(url: str) -> Ley:
    ruta = ruta_cache(url)
    if not ruta.exists():
        raise FileNotFoundError(f"falta {ruta} en la caché (fuente: {url})")
    return segmentar(texto_doc(ruta))


def decreto_id(publicado: date, ley: str | None = None) -> str:
    """La expedición de una ley lleva la ley en el id: el CFF y una reforma a LIVA salieron el
    mismo día (DOF 31-12-1981)."""
    # shortcut: el id es la fecha; un segundo decreto del mismo día recibe sufijo (`decreto`).
    # Cambiar a la clave del SIDOF cuando llegue RF-06 (iteración 4).
    return f"DOF-{publicado.isoformat()}" + (f"-{ley}" if ley else "")


class Construccion:
    def __init__(self, con: sqlite3.Connection):
        self.con = con
        self.ambiguas: set[date] = set()  # fechas con más de un decreto

    def documento(self, id_: str, nombre: str, tipo: str) -> None:
        self.con.execute("INSERT OR IGNORE INTO documentos VALUES (?, ?, ?)", (id_, nombre, tipo))

    def decreto(self, publicado: date, titulo: str | None, vigor: date | None = None, ley: str | None = None) -> str:
        """Registra un decreto y devuelve su id. Si el id ya es de otro decreto (otro título), este
        recibe sufijo: LIVA tiene dos decretos del DOF 30-12-2002."""
        primero = id_ = decreto_id(publicado, ley)
        n = 1
        while titulo and (previo := self.con.execute("SELECT titulo FROM decretos WHERE id = ?", (id_,)).fetchone()) \
                and previo[0] and previo[0].casefold() != titulo.casefold():
            self.ambiguas.add(publicado)
            n += 1
            id_ = f"{primero}-{n}"
        self.documento(id_, titulo or f"Decreto publicado en el DOF el {publicado.isoformat()}", "decreto")
        self.con.execute("INSERT OR IGNORE INTO decretos VALUES (?, ?, ?, ?)",
                         (id_, publicado.isoformat(), titulo, vigor.isoformat() if vigor else None))
        if titulo:  # un decreto visto primero solo en una nota no tiene título; se completa al encontrarlo
            self.con.execute("UPDATE decretos SET titulo = ? WHERE id = ? AND titulo IS NULL", (titulo, id_))
            self.con.execute("UPDATE documentos SET nombre = ? WHERE id = ?", (titulo, id_))
        return id_

    def version(self, documento: str, u: Unidad, desde: date, decreto: str, url: str,
                hasta: date | None = None, texto: str | None = None, notas: str | None = None) -> None:
        self.con.execute(
            "INSERT INTO versiones (documento, unidad, clave, tipo, jerarquia, vigente_desde, vigente_hasta, decreto, "
            "texto, notas, fuente_url) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (documento, u.id, almacen.clave(u.id), u.tipo, " > ".join(u.jerarquia), desde.isoformat(),
             hasta.isoformat() if hasta else None, decreto, u.texto if texto is None else texto,
             "\n".join(u.notas) if notas is None else notas, url))

    @staticmethod
    def vigor(documento: str, unidad: str, publicado: date, decretos: dict[date, Decreto]) -> date:
        if p := PUBLICACIONES.get(publicado):
            return p.vigor_de(unidad)
        if publicado not in decretos:
            raise ValueError(f"{documento} art. {unidad}: el decreto del DOF {publicado} no está en el documento "
                             "ni en vigencias.PUBLICACIONES")
        vigor, excepciones = decretos[publicado].entrada_en_vigor()
        if vigor is None or excepciones:
            raise ValueError(f"DOF {publicado}: vigencia no reconocida o con excepciones; "
                             "agrégala a vigencias.PUBLICACIONES")
        return vigor

    def citado(self, publicado: date) -> str:
        """Id del decreto al que remite una nota por su fecha. Si ese día hubo dos, la nota no dice
        cuál: hace falta revisarlo a mano y anotarlo en `vigencias.MISMO_DIA`."""
        self.decreto(publicado, None)  # una nota puede ser la única huella del decreto
        if publicado in self.ambiguas and publicado not in MISMO_DIA:
            raise ValueError(f"una nota cita el DOF {publicado}, que publicó dos decretos del corpus; "
                             "revisa a cuál remite y anótalo en vigencias.MISMO_DIA")
        return decreto_id(publicado)

    def transitorios_de(self, d: Decreto, url: str) -> None:
        """Los transitorios son del decreto: un decreto que reforma varias leyes aparece en el
        documento de cada una, así que la segunda vez se ignora."""
        vigor = p.vigor if (p := PUBLICACIONES.get(d.publicado)) else d.entrada_en_vigor()[0]
        id_ = self.decreto(d.publicado, d.titulo, vigor)
        for u in d.transitorios:
            existe = self.con.execute("SELECT 1 FROM versiones WHERE documento = ? AND clave = ?",
                                      (id_, almacen.clave(u.id))).fetchone()
            if not existe:
                self.version(id_, u, d.publicado, id_, url)

    def decretos_de(self, f: Fuente, actual: Ley) -> None:
        """Primero los decretos de todas las leyes: así un choque de fechas se ve antes de citar."""
        self.documento(f.documento, f.nombre, "ley")
        self.decreto(actual.expedicion, almacen.EXPEDICION + f.nombre, ley=f.documento)
        for d in actual.decretos:
            self.transitorios_de(d, f.actual_url)

    def ley(self, f: Fuente, actual: Ley, base: Ley) -> dict:
        expedicion = decreto_id(actual.expedicion, f.documento)
        for u in actual.transitorios:
            self.version(f.documento, u, CORTE, expedicion, f.actual_url)

        for u in base.articulos:
            if despues := u.reformas(desde=CORTE):
                raise ValueError(f"{f.documento} art. {u.id}: la copia base ya trae reformas posteriores al corte {despues}")
            ultima = max(u.reformas(hasta=CORTE), default=None)
            self.version(f.documento, u, CORTE, self.citado(ultima) if ultima else expedicion, f.base_url)

        por_id = {u.id: u for u in base.articulos}
        if faltan := por_id.keys() - {u.id for u in actual.articulos}:
            raise ValueError(f"{f.documento}: artículos que desaparecieron del texto vigente: {sorted(faltan)}")
        decretos = {d.publicado: d for d in actual.decretos}
        cambiados = []
        for u in actual.articulos:
            anterior = por_id.get(u.id)
            posteriores = u.reformas(desde=CORTE)
            if anterior and anterior.texto == u.texto:
                if posteriores:
                    raise ValueError(f"{f.documento} art. {u.id}: nota de reforma {posteriores} sin cambio de texto")
                continue
            if not posteriores:
                raise ValueError(f"{f.documento} art. {u.id}: el texto cambió sin nota de reforma después del corte")
            # Una versión por fecha de vigencia, citando la última publicación que rige ese día.
            por_vigor: dict[date, date] = {}
            for publicado in sorted(posteriores):
                por_vigor[self.vigor(f.documento, u.id, publicado, decretos)] = publicado
            fechas = sorted(por_vigor)
            textos, notas, urls = [u.texto], [None], [f.actual_url]
            for desde, siguiente in zip(reversed(fechas[:-1]), reversed(fechas[1:])):
                i = intermedia(f.documento, u.id, desde)
                if i is None:
                    raise ValueError(f"{f.documento} art. {u.id}: falta en vigencias.INTERMEDIAS la versión vigente "
                                     f"desde {desde}")
                textos.insert(0, deshacer(textos[0], i))
                notas.insert(0, f"Versión reconstruida: deshace la reforma del DOF {por_vigor[siguiente]}.")
                urls.insert(0, i.fuente_url)
            for publicado in por_vigor.values():  # publicaciones que LeyesBiblio no trae como bloque
                if (p := PUBLICACIONES.get(publicado)) and p.titulo:
                    self.decreto(publicado, p.titulo, p.vigor)
            if anterior:
                self.con.execute(
                    "UPDATE versiones SET vigente_hasta = ? WHERE documento = ? AND clave = ? AND vigente_hasta IS NULL",
                    (fechas[0].isoformat(), f.documento, almacen.clave(u.id)))
            for k, desde in enumerate(fechas):
                hasta = fechas[k + 1] if k + 1 < len(fechas) else None
                self.version(f.documento, u, desde, self.citado(por_vigor[desde]), urls[k], hasta, textos[k], notas[k])
            cambiados.append(u.id)
        return {"documento": f.documento, "articulos": len(actual.articulos), "transitorios": len(actual.transitorios),
                "decretos": len(actual.decretos), "reformados_desde_corte": cambiados}


def construir(destino: Path, fuentes: list[Fuente] = FUENTES, vectores=None) -> list[dict]:
    """Construye en un archivo temporal y lo cambia de golpe: el servidor nunca ve una base a medias.
    `vectores`: una `vectores.Cache` para llenar los embeddings; sin ella, la base queda solo con BM25."""
    destino.parent.mkdir(parents=True, exist_ok=True)
    temporal = destino.with_suffix(".construyendo")
    temporal.unlink(missing_ok=True)
    con = almacen.crear(temporal)
    try:
        with con:
            c = Construccion(con)
            leyes = []
            for f in fuentes:
                actual = leer(f.actual_url)
                leyes.append((f, actual, actual if f.base_url == f.actual_url else leer(f.base_url)))
                c.decretos_de(f, actual)
            resumen = [c.ley(*ley) for ley in leyes]
            almacen.indexar(con)
            if vectores is not None:
                almacen.vectorizar(con, vectores)
    except BaseException:
        con.close()
        temporal.unlink(missing_ok=True)
        raise
    con.close()
    os.replace(temporal, destino)
    return resumen
