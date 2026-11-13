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

from . import almacen, aristas
from .almacen import CORTE
from .doc import texto_doc
from .ley import Decreto, Ley, Unidad, fecha_es, segmentar
from .anexos import FuenteAnexo
from .anexos import vigor as vigor_anexo
from .rmf import FuenteRmf
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
    # El id es la fecha (con el documento en la RMF y sus anexos); un segundo decreto del mismo día recibe
    # sufijo (`decreto`). La clave del SIDOF no lo reemplaza: se enlaza por fecha y documento con la
    # tabla `publicaciones` (`novellae._url`), que existe aunque el SIDOF no tenga el día en caché.
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
                hasta: date | None = None, texto: str | None = None, notas: str | None = None) -> int:
        return self.con.execute(
            "INSERT INTO versiones (documento, unidad, clave, tipo, jerarquia, vigente_desde, vigente_hasta, decreto, "
            "texto, notas, fuente_url) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (documento, u.id, almacen.clave(u.id), u.tipo, " > ".join(u.jerarquia), desde.isoformat(),
             hasta.isoformat() if hasta else None, decreto, u.texto if texto is None else texto,
             "\n".join(u.notas) if notas is None else notas, url)).lastrowid

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
            # Las demás publicaciones que rigen ese mismo día van en `versiones_decretos`: el CFF del
            # 07-11-2025 y el Anexo 5 del 28-12-2025 rigen los dos desde el 2026-01-01 y no hay texto intermedio.
            por_vigor: dict[date, date] = {}
            juntas: dict[date, list[date]] = {}
            for publicado in sorted(set(posteriores)):
                vigor = self.vigor(f.documento, u.id, publicado, decretos)
                por_vigor[vigor] = publicado
                juntas.setdefault(vigor, []).append(publicado)
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
            for publicado in set(posteriores):  # publicaciones que LeyesBiblio no trae como bloque
                if (p := PUBLICACIONES.get(publicado)) and p.titulo:
                    self.decreto(publicado, p.titulo, p.vigor)
            if anterior:
                self.con.execute(
                    "UPDATE versiones SET vigente_hasta = ? WHERE documento = ? AND clave = ? AND vigente_hasta IS NULL",
                    (fechas[0].isoformat(), f.documento, almacen.clave(u.id)))
            for k, desde in enumerate(fechas):
                hasta = fechas[k + 1] if k + 1 < len(fechas) else None
                version = self.version(f.documento, u, desde, self.citado(por_vigor[desde]), urls[k], hasta, textos[k], notas[k])
                self.con.executemany("INSERT INTO versiones_decretos VALUES (?, ?)",
                                     [(version, self.citado(p)) for p in juntas[desde][:-1]])
            cambiados.append(u.id)
        return {"documento": f.documento, "articulos": len(actual.articulos), "transitorios": len(actual.transitorios),
                "decretos": len(actual.decretos), "reformados_desde_corte": cambiados}


    def rmf(self, f: FuenteRmf) -> dict:
        """Una RMF: versión base de cada regla desde el original y una versión nueva en cada
        modificación cuya marca trae la regla en la compilada correspondiente (ver `rmf.py`)."""
        from . import rmf
        original = rmf.segmentar(rmf.texto_pdf(_en_cache(f.original)))
        compiladas = [rmf.segmentar(rmf.texto_pdf(_en_cache(u))) if u else None for u in f.compiladas]
        if compiladas and compiladas[-1] is None:
            raise ValueError(f"{f.documento}: la última compilada hace falta, trae los transitorios de cada modificación")
        mods = compiladas[-1].modificaciones if compiladas else []
        if len(mods) != len(f.compiladas):
            raise ValueError(f"{f.documento}: {len(f.compiladas)} compiladas y {len(mods)} modificaciones en la última")

        # Solo el Primero: los demás transitorios de la RMF fijan vigencias de anexos o de reglas sueltas.
        primero = [u for u in original.transitorios if u.id == "Transitorio Primero"]
        vigor, excepciones = Decreto(f.nombre, f.publicado, primero).entrada_en_vigor()
        if vigor is None or excepciones:
            raise ValueError(f"{f.documento}: vigencia no reconocida en su Transitorio Primero")
        fin = date(f.anio + 1, 1, 1)  # "estará vigente hasta el 31 de diciembre"
        self.documento(f.documento, f.nombre, "resolucion")
        id_rmf = self.decreto(f.publicado, f.nombre, vigor, ley=f.documento)
        for u in original.transitorios:
            # shortcut: los transitorios de la RMF se toman del original; los que reforma una modificación
            # (hay marcas "Transitorio Vigésimo Tercero") no tienen versión nueva todavía.
            self.version(f.documento, u, vigor, id_rmf, f.original, hasta=fin)

        ids_mod = []
        for k, d in enumerate(mods):
            url = f.compiladas[-1]
            if not d.transitorios and k in f.publicadas:  # la compilada lo omitió
                url = f.publicadas[k]
                d.transitorios = rmf.transitorios(rmf.texto_pdf(_en_cache(url)))
            v, exc = d.entrada_en_vigor()
            id_ = self.decreto(d.publicado, f"{d.titulo} para {f.anio}", v if not exc else None, ley=f.documento)
            ids_mod.append((id_, v, exc))
            for u in d.transitorios:
                self.version(id_, u, d.publicado, id_, url)

        # Por regla: [(desde, texto, decreto, url, notas, jerarquía, líneas de referencias)]
        historia = {r.id: [(vigor, r.texto, id_rmf, f.original, "", r.jerarquia, r.referencias)] for r in original.reglas}
        ruido, sin_cambio, nuevas_sin_marca = [], [], []
        for k, (comp, url, (id_mod, v, exc)) in enumerate(zip(compiladas, f.compiladas, ids_mod)):
            if (v is None or exc) and any(fecha == mods[k].publicado for c in compiladas[k:] if c
                                          for r in c.reglas for _, fecha in r.marcas):
                raise ValueError(f"{f.documento}: la modificación del DOF {mods[k].publicado} tiene vigencia "
                                 "no reconocida o con excepciones; anótala en vigencias.PUBLICACIONES")
            if comp is None:  # sin compilada: las reglas marcadas salen de la siguiente que sí hay
                j = next(i for i in range(k + 1, len(compiladas)) if compiladas[i])
                comp, url = compiladas[j], f.compiladas[j]
                despues = {m.publicado for m in mods[k + 1:j + 1]}
                publicada = None
                for r in comp.reglas:
                    if not any(fecha == mods[k].publicado for _, fecha in r.marcas):
                        continue
                    texto, fuente, refs = r.texto, url, r.referencias
                    if despues & {fecha for _, fecha in r.marcas}:  # la volvió a tocar otra: texto de la publicación
                        publicada = publicada or {x.id: x for x in rmf.segmentar(
                            rmf.texto_pdf(_en_cache(f.publicadas[k])), minimo=1).reglas}
                        if r.id not in publicada or re.search(r"(?:\.\s*){3}|…", publicada[r.id].texto):
                            raise ValueError(f"{f.documento} regla {r.id}: la modificación {k + 1} no tiene compilada "
                                             "y su publicación no trae la regla completa")
                        texto, fuente, refs = publicada[r.id].texto.strip("“”\" "), f.publicadas[k], publicada[r.id].referencias
                    notas = [n for n in r.notas if (fn := fecha_es(n)) and fn <= mods[k].publicado]
                    historia.setdefault(r.id, []).append((v, texto, id_mod, fuente, "\n".join(notas), r.jerarquia, refs))
                continue
            for r in comp.reglas:
                marcada = any(fecha == mods[k].publicado for _, fecha in r.marcas)
                previo = historia.get(r.id)
                if not marcada and previo is None:
                    # Regla nueva sin marca (el SAT la omitió: 2.8.3.7 y 2.12.12 de 2025): rige desde esta modificación.
                    if v is None or exc:
                        raise ValueError(f"{f.documento} regla {r.id}: nueva en la compilada {k + 1}, sin vigencia legible")
                    nuevas_sin_marca.append(f"{r.id}@{k + 1}")
                    historia[r.id] = [(v, r.texto, id_mod, url, "", r.jerarquia, r.referencias)]
                    continue
                if not marcada:
                    if _plano(previo[-1][1]) != _plano(r.texto):
                        ruido.append(f"{r.id}@{k + 1}")
                    continue
                if previo and _plano(previo[-1][1]) == _plano(r.texto):
                    sin_cambio.append(f"{r.id}@{k + 1}")
                historia.setdefault(r.id, []).append((v, r.texto, id_mod, url, "\n".join(r.notas), r.jerarquia,
                                                      r.referencias))

        for id_, versiones in historia.items():
            for j, (desde, texto, decreto, url, notas, jerarquia, refs) in enumerate(versiones):
                hasta = versiones[j + 1][0] if j + 1 < len(versiones) else fin
                if hasta <= desde:  # dos modificaciones que rigen el mismo día: queda la última
                    continue
                version = self.version(f.documento, Unidad(id_, "regla", jerarquia=jerarquia), desde, decreto, url,
                                       hasta, texto, notas)
                self.con.executemany("INSERT OR IGNORE INTO aristas VALUES (?, ?, ?, ?)",
                                     [(version, *a) for a in aristas.referencias_de_regla(refs, f.anio)])
        return {"documento": f.documento, "reglas": len(historia), "transitorios": len(original.transitorios),
                "modificaciones": len(mods),
                "reformadas": sum(1 for v in historia.values() if len(v) > 1 or v[0][2] != id_rmf),
                # Texto distinto sin marca: diferencias de formato entre el original y la compilada (RF-03).
                "ruido": ruido, "marcadas_sin_cambio": sin_cambio, "nuevas_sin_marca": nuevas_sin_marca}


    def anexo(self, f: FuenteAnexo, fin: date | None) -> dict:
        """Un anexo: versión base de cada sección desde la publicación en el DOF y una versión nueva
        en cada modificación cuya marca trae la sección en la compilada correspondiente, como en la
        RMF. `fin`: cuando empieza a regir el del año siguiente; None si se prorroga (el 20)."""
        from . import anexos
        from .rmf import ORDINALES
        desde = anexos.vigor(f.anio, f.publicado)
        self.documento(f.documento, f.nombre, "anexo")
        id_base = self.decreto(f.publicado, f.nombre, desde, ley=f.documento)
        base, _ = anexos.leer(f.numero, anexos.lineas_pdf(_en_cache(f.url)))
        historia = {s.id: [(desde, s, id_base, f.url)] for s in base}
        publicaciones = {p for p, _ in f.modificaciones}
        ruido, nuevas_sin_marca = [], []
        for k, (publicado, url) in enumerate(f.modificaciones):
            v = anexos.vigor(f.anio, publicado)
            id_mod = self.decreto(publicado, f"{ORDINALES[k]} Modificación al {f.nombre}", v, ley=f.documento)
            secciones, marcas = anexos.leer(f.numero, anexos.lineas_pdf(_en_cache(url)))
            if extrañas := {x for m in marcas.values() for x in m} - publicaciones:
                raise ValueError(f"{f.documento}: marcas de modificaciones que no están en la fuente: {sorted(extrañas)}")
            for s in secciones:
                previo = historia.get(s.id)
                if publicado in marcas.get(s.id, ()) or previo is None:
                    if previo is None and publicado not in marcas.get(s.id, ()):
                        nuevas_sin_marca.append(f"{s.id}@{k + 1}")
                    historia.setdefault(s.id, []).append((v, s, id_mod, url))
                elif _plano(previo[-1][1].texto) != _plano(s.texto):
                    ruido.append(f"{s.id}@{k + 1}")  # sin marca: se conserva el texto anterior
        for id_, versiones in historia.items():
            for j, (d, s, decreto, url) in enumerate(versiones):
                hasta = versiones[j + 1][0] if j + 1 < len(versiones) else fin
                if hasta is not None and hasta <= d:
                    continue
                version = self.version(f.documento, Unidad(id_, "seccion", jerarquia=s.jerarquia), d, decreto, url,
                                       hasta, s.texto, "")
                if f.numero == 8:  # cada tarifa reglamenta los artículos de ley que nombra su título
                    self.con.executemany("INSERT OR IGNORE INTO aristas VALUES (?, 'REGLAMENTA', ?, ?)",
                                         [(version, doc, cl) for doc, cl in aristas.remisiones(s.lineas[0], f.documento)
                                          if not doc.startswith("RMF")])
        return {"documento": f.documento, "secciones": len(historia), "modificaciones": len(f.modificaciones),
                "vigente_desde": desde.isoformat(), "vigente_hasta": fin.isoformat() if fin else None,
                "reformadas": sorted(i for i, v in historia.items() if len(v) > 1),
                "ruido": ruido, "nuevas_sin_marca": nuevas_sin_marca}


    def anexo_20(self) -> list[dict]:
        """Estándar del CFDI 4.0 (Anexo 20 de la RMF 2022, prorrogado cada año) y su guía de
        llenado. La guía no sale en el DOF: su fecha es la del Portal del SAT (Last-Modified) y su
        versión se identifica por el hash del PDF (R-09). Sin los PDF en la caché se omiten: el
        portal solo responde por HTTP y se bajan a mano hasta pasar por `ciberseguridad`."""
        import hashlib
        import json
        from email.utils import parsedate_to_datetime

        from . import anexos
        faltan = [u for u in (anexos.ANEXO_20.url, anexos.GUIA_20) if not ruta_cache(u).exists()]
        if faltan:
            return [{"documento": "RMF2022-A20", "omitido": f"faltan en la caché, se bajan a mano (R-09): {faltan}"}]
        resumen = [self.anexo(anexos.ANEXO_20, None)]
        nodos = {u.split(" ", 1)[1].split(" (")[0] for (u,) in self.con.execute(
            "SELECT unidad FROM versiones WHERE documento = ? AND unidad LIKE '% %'", (anexos.ANEXO_20.documento,))}
        ruta = ruta_cache(anexos.GUIA_20)
        meta = json.loads(ruta.with_name(ruta.name + ".meta.json").read_text(encoding="utf-8"))
        publicada = parsedate_to_datetime(meta["last_modified"]).date()
        huella = hashlib.sha256(ruta.read_bytes()).hexdigest()
        titulo = "Guía de llenado de los comprobantes fiscales digitales por Internet (Anexo 20)"
        id_ = f"{almacen.PORTAL}{publicada.isoformat()}-GUIA-A20"
        self.documento("GUIA-A20", titulo, "anexo")
        self.documento(id_, titulo, "decreto")
        self.con.execute("INSERT OR IGNORE INTO decretos VALUES (?, ?, ?, ?)",
                         (id_, publicada.isoformat(), titulo, publicada.isoformat()))
        secciones = anexos.guia(anexos.lineas_pdf(ruta), nodos)
        for s in secciones:
            self.version("GUIA-A20", Unidad(s.id, "seccion", jerarquia=s.jerarquia), publicada, id_, anexos.GUIA_20,
                         None, s.texto, f"Publicada en el Portal del SAT, no en el DOF; sha256 del PDF {huella}.")
        return resumen + [{"documento": "GUIA-A20", "secciones": len(secciones), "vigente_desde": publicada.isoformat(),
                           "sha256": huella}]


def _en_cache(url: str) -> Path:
    ruta = ruta_cache(url)
    if not ruta.exists():
        raise FileNotFoundError(f"falta {ruta} en la caché (fuente: {url}); bájala con `tabularium descargar`")
    return ruta


def _plano(texto: str) -> str:
    """Para comparar versiones de formatos distintos: sin espacios ni guiones de corte."""
    return re.sub(r"[\s\-‐\xad]", "", texto)


def construir(destino: Path, fuentes: list[Fuente] = FUENTES, vectores=None,
              resoluciones: list[FuenteRmf] | None = None, anexos: list[FuenteAnexo] | None = None) -> list[dict]:
    """Construye en un archivo temporal y lo cambia de golpe: el servidor nunca ve una base a medias.
    `vectores`: una `vectores.Cache` para llenar los embeddings; sin ella, la base queda solo con BM25.
    `resoluciones`: por omisión, las del minisitio del SAT (`minisitio.fuentes`). `anexos`: por
    omisión, los de los años de `resoluciones`."""
    if resoluciones is None or (anexos is None and resoluciones):
        from . import minisitio  # minisitio importa de este módulo
        del_sat, anexos_sat = minisitio.fuentes()
        resoluciones = del_sat if resoluciones is None else resoluciones
        anexos = [a for a in anexos_sat if a.anio in {r.anio for r in resoluciones}] if anexos is None else anexos
    anexos = anexos or []
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
            resumen = [c.ley(*ley) for ley in leyes] + [c.rmf(f) for f in resoluciones]
            for f in anexos:  # el de cada año rige hasta que rige el del siguiente (`anexos.vigor`)
                sig = min((a for a in anexos if a.numero == f.numero and a.anio > f.anio), key=lambda a: a.anio, default=None)
                resumen.append(c.anexo(f, vigor_anexo(sig.anio, sig.publicado) if sig else date(f.anio + 1, 1, 1)))
            if resoluciones:
                resumen += c.anexo_20()
            resumen.append({"documento": "grafo", **aristas.enlazar(con)})
            from .dof import publicaciones  # dof importa de este módulo
            detectadas = publicaciones()
            con.executemany("INSERT INTO publicaciones VALUES (?, ?, ?, ?, ?, ?)",
                            [(p.cod_nota, p.publicado_dof, p.edicion, p.titulo, " ".join(p.documentos), p.url)
                             for p in detectadas])
            resumen.append({"documento": "publicaciones del DOF", "detectadas": len(detectadas)})
            from .glosas import copiar  # glosas importa novellae, que importa almacen
            resumen.append({"documento": "glosas", "copiadas": copiar(con)})
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
