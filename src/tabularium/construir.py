"""Construye la base versionada desde la caché de documentos fuente.

Por cada ley: la línea base (texto vigente al corte) y el texto vigente de hoy. Un artículo que
cambió entre las dos recibe una versión nueva, con la vigencia que fija el transitorio de su
decreto, y la versión base se cierra ese mismo día.
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


def decreto_id(publicado: date) -> str:
    # shortcut: un decreto por fecha de publicación; dos decretos del mismo día que toquen el
    # corpus chocarían. Cambiar a la clave del SIDOF cuando llegue RF-06 (iteración 4).
    return f"DOF-{publicado.isoformat()}"


class Construccion:
    def __init__(self, con: sqlite3.Connection):
        self.con = con

    def documento(self, id_: str, nombre: str, tipo: str) -> None:
        self.con.execute("INSERT OR IGNORE INTO documentos VALUES (?, ?, ?)", (id_, nombre, tipo))

    def decreto(self, publicado: date, titulo: str | None, vigor: date | None = None) -> str:
        id_ = decreto_id(publicado)
        self.documento(id_, titulo or f"Decreto publicado en el DOF el {publicado.isoformat()}", "decreto")
        self.con.execute("INSERT OR IGNORE INTO decretos VALUES (?, ?, ?, ?)",
                         (id_, publicado.isoformat(), titulo, vigor.isoformat() if vigor else None))
        if titulo:  # un decreto visto primero solo en una nota no tiene título; se completa al encontrarlo
            self.con.execute("UPDATE decretos SET titulo = ? WHERE id = ? AND titulo IS NULL", (titulo, id_))
            self.con.execute("UPDATE documentos SET nombre = ? WHERE id = ?", (titulo, id_))
        return id_

    def version(self, documento: str, u: Unidad, desde: date, decreto: str, url: str) -> None:
        self.con.execute(
            "INSERT INTO versiones (documento, unidad, clave, tipo, jerarquia, vigente_desde, decreto, texto, "
            "notas, fuente_url) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (documento, u.id, almacen.clave(u.id), u.tipo, " > ".join(u.jerarquia), desde.isoformat(), decreto,
             u.texto, "\n".join(u.notas), url))

    def transitorios_de(self, d: Decreto, url: str) -> None:
        """Los transitorios son del decreto: un decreto que reforma varias leyes aparece en el
        documento de cada una, así que la segunda vez se ignora."""
        vigor, _ = d.entrada_en_vigor()
        id_ = self.decreto(d.publicado, d.titulo, vigor)
        for u in d.transitorios:
            existe = self.con.execute("SELECT 1 FROM versiones WHERE documento = ? AND clave = ?",
                                      (id_, almacen.clave(u.id))).fetchone()
            if not existe:
                self.version(id_, u, d.publicado, id_, url)

    def ley(self, f: Fuente) -> dict:
        actual = leer(f.actual_url)
        base = actual if f.base_url == f.actual_url else leer(f.base_url)
        self.documento(f.documento, f.nombre, "ley")
        expedicion = self.decreto(actual.expedicion, f"Expedición de la {f.nombre}")
        for d in actual.decretos:
            self.transitorios_de(d, f.actual_url)
        for u in actual.transitorios:
            self.version(f.documento, u, CORTE, expedicion, f.actual_url)

        for u in base.articulos:
            ultima = max(u.reformas(hasta=CORTE), default=None)
            decreto = self.decreto(ultima, None) if ultima else expedicion
            self.version(f.documento, u, CORTE, decreto, f.base_url)

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
            if len(posteriores) != 1:
                # shortcut: solo una reforma por artículo después del corte. Las versiones intermedias
                # (R-10, el CFF tuvo 6 publicaciones) se reconstruyen desde el decreto en la iteración 2.
                raise NotImplementedError(f"{f.documento} art. {u.id}: {len(posteriores)} reformas después del corte")
            publicado = posteriores.pop()
            if publicado not in decretos:
                raise ValueError(f"{f.documento} art. {u.id}: no está el decreto del DOF {publicado} en el documento")
            vigor, excepciones = decretos[publicado].entrada_en_vigor()
            if vigor is None or excepciones:
                # shortcut: sin tabla manual de vigencias; llega con las excepciones del CFF (iteración 2).
                raise NotImplementedError(f"DOF {publicado}: vigencia no reconocida o con excepciones")
            if anterior:
                self.con.execute(
                    "UPDATE versiones SET vigente_hasta = ? WHERE documento = ? AND clave = ? AND vigente_hasta IS NULL",
                    (vigor.isoformat(), f.documento, almacen.clave(u.id)))
            self.version(f.documento, u, vigor, decreto_id(publicado), f.actual_url)
            cambiados.append(u.id)
        return {"documento": f.documento, "articulos": len(actual.articulos), "transitorios": len(actual.transitorios),
                "decretos": len(actual.decretos), "reformados_desde_corte": cambiados}


def construir(destino: Path, fuentes: list[Fuente] = FUENTES) -> list[dict]:
    """Construye en un archivo temporal y lo cambia de golpe: el servidor nunca ve una base a medias."""
    destino.parent.mkdir(parents=True, exist_ok=True)
    temporal = destino.with_suffix(".construyendo")
    temporal.unlink(missing_ok=True)
    con = almacen.crear(temporal)
    try:
        with con:
            c = Construccion(con)
            resumen = [c.ley(f) for f in fuentes]
            con.execute("INSERT INTO versiones_fts(versiones_fts) VALUES ('rebuild')")
    except BaseException:
        con.close()
        temporal.unlink(missing_ok=True)
        raise
    con.close()
    os.replace(temporal, destino)
    return resumen
