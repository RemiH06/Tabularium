"""Base de SQLite del corpus: esquema, consultas por vigencia y citas.

Una versión nunca se sobrescribe ni se borra (RF-04): los disparadores lo impiden. La base se
regenera completa desde la caché de documentos fuente, así que no hace falta editarla en sitio.
"""
from __future__ import annotations

import re
import sqlite3
import unicodedata
from datetime import date
from pathlib import Path

import numpy as np

from . import lexico

CORTE = date(2024, 1, 1)  # inicio del corpus: la línea base es el texto vigente a esta fecha
EXPEDICION = "Expedición: "  # prefijo del título del decreto que expide una ley
RESOLUCION = "Resolución Miscelánea Fiscal"  # título de la RMF de cada año; el de sus modificaciones lo contiene
PORTAL = "SAT-"  # prefijo del id de lo que el SAT publica solo en su portal (guía de llenado del Anexo 20)

ESQUEMA = """
CREATE TABLE documentos (
    id TEXT PRIMARY KEY,
    nombre TEXT NOT NULL,
    tipo TEXT NOT NULL CHECK (tipo IN ('ley', 'resolucion', 'anexo', 'decreto'))
);
CREATE TABLE decretos (
    id TEXT PRIMARY KEY REFERENCES documentos(id),
    publicado_dof TEXT NOT NULL,
    titulo TEXT,
    entrada_en_vigor TEXT
);
CREATE TABLE versiones (
    id INTEGER PRIMARY KEY,
    documento TEXT NOT NULL REFERENCES documentos(id),
    unidad TEXT NOT NULL,
    clave TEXT NOT NULL,
    tipo TEXT NOT NULL CHECK (tipo IN ('articulo', 'regla', 'seccion', 'transitorio')),
    jerarquia TEXT NOT NULL DEFAULT '',
    vigente_desde TEXT NOT NULL,
    vigente_hasta TEXT,
    decreto TEXT NOT NULL REFERENCES decretos(id),
    texto TEXT NOT NULL,
    notas TEXT NOT NULL DEFAULT '',
    fuente_url TEXT NOT NULL,
    UNIQUE (documento, clave, vigente_desde),
    CHECK (vigente_hasta IS NULL OR vigente_hasta > vigente_desde)
);
CREATE INDEX versiones_vigencia ON versiones (documento, clave, vigente_desde);
CREATE TRIGGER versiones_inmutables BEFORE UPDATE OF documento, unidad, clave, tipo, vigente_desde,
    decreto, texto, notas, fuente_url ON versiones
BEGIN SELECT RAISE(ABORT, 'una versión no se sobrescribe: se agrega otra'); END;
CREATE TRIGGER versiones_cierre_unico BEFORE UPDATE OF vigente_hasta ON versiones
    WHEN OLD.vigente_hasta IS NOT NULL
BEGIN SELECT RAISE(ABORT, 'la versión ya estaba cerrada'); END;
CREATE TRIGGER versiones_sin_borrado BEFORE DELETE ON versiones
BEGIN SELECT RAISE(ABORT, 'una versión no se borra'); END;
CREATE VIRTUAL TABLE versiones_fts USING fts5(
    unidad, texto, content='versiones', content_rowid='id', tokenize='unicode61 remove_diacritics 2'
);
-- Raíces sin palabras vacías (`lexico.raices`), con rowid = versiones.id. Ordena `buscar`;
-- versiones_fts queda para los fragmentos, que se muestran con el texto literal.
CREATE VIRTUAL TABLE busqueda USING fts5(unidad, texto, content='');
-- Grafo estructural (`aristas.py`): de una versión a una unidad (documento, clave), que en cada
-- fecha resuelve a su versión vigente. Solo destinos que existen en el corpus.
CREATE TABLE aristas (
    version INTEGER NOT NULL REFERENCES versiones(id),
    tipo TEXT NOT NULL CHECK (tipo IN ('REMITE_A', 'REGLAMENTA')),
    documento TEXT NOT NULL,
    clave TEXT NOT NULL,
    UNIQUE (version, tipo, documento, clave)
);
CREATE INDEX aristas_destino ON aristas (documento, clave);
-- Otras publicaciones que una versión junta, además de `versiones.decreto` (la última): rigen el
-- mismo día y no hay texto intermedio entre ellas. Las Novellae de cada una muestran el cambio.
CREATE TABLE versiones_decretos (
    version INTEGER NOT NULL REFERENCES versiones(id),
    decreto TEXT NOT NULL REFERENCES decretos(id),
    UNIQUE (version, decreto)
);
-- Publicaciones del DOF que tocan el corpus, detectadas en el SIDOF (`dof.py`, RF-06). Una
-- publicación sin versiones de su fecha en alguno de sus documentos es una Novella pendiente.
CREATE TABLE publicaciones (
    cod_nota INTEGER PRIMARY KEY,
    publicado_dof TEXT NOT NULL,
    edicion TEXT NOT NULL,
    titulo TEXT NOT NULL,
    documentos TEXT NOT NULL,  -- ids separados por espacio: "RMF2026 RMF2026-A29"
    url TEXT NOT NULL
);
-- Un vector por fragmento de cada versión (`vectores.py`); vacía si la base se construyó sin vectores.
CREATE TABLE fragmentos (
    version INTEGER NOT NULL REFERENCES versiones(id),
    vector BLOB NOT NULL
);
"""

_COLUMNAS = """v.documento, d.nombre, d.tipo AS tipo_documento, v.unidad, v.tipo, v.jerarquia, v.vigente_desde, v.vigente_hasta,
    v.decreto, dc.publicado_dof, dc.titulo, v.fuente_url"""
_JOIN = "versiones v JOIN documentos d ON d.id = v.documento JOIN decretos dc ON dc.id = v.decreto"
_VIGENTE = "v.vigente_desde <= :fecha AND (v.vigente_hasta IS NULL OR v.vigente_hasta > :fecha)"


def crear(ruta: Path) -> sqlite3.Connection:
    con = sqlite3.connect(ruta)
    con.executescript(ESQUEMA)
    return con


def abrir(ruta: Path) -> sqlite3.Connection:
    """Conexión de solo lectura: el servidor nunca escribe."""
    if not ruta.exists():
        raise FileNotFoundError(f"no existe la base {ruta}; constrúyela con `tabularium construir`")
    con = sqlite3.connect(f"file:{ruta.as_posix()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def clave(unidad: str) -> str:
    """Forma de búsqueda de una unidad: "Artículo 1o.-A" -> "1a", "Transitorio Único" -> "transitoriounico"."""
    s = unicodedata.normalize("NFKD", unidad).encode("ascii", "ignore").decode().lower().strip()
    if m := re.fullmatch(r"(?:regla\s*)?(\d+(?:\.\d+)+)\.?", s):  # regla de la RMF: "2.1.6" no es "21.6"
        return m.group(1)
    s = re.sub(r"^art(?:iculo|\.)?\s*(?=\d)", "", s)
    s = re.sub(r"(?<=\d)o(?![a-z])", "", s)  # "1o." -> "1"
    return re.sub(r"[^a-z0-9]", "", s)


def _fecha(fecha: str | None) -> str:
    if fecha is None:
        return date.today().isoformat()
    try:
        f = date.fromisoformat(fecha)
    except ValueError as e:
        raise ValueError(f"fecha inválida {fecha!r}: usa AAAA-MM-DD") from e
    if f < CORTE:
        raise ValueError(f"el corpus empieza el {CORTE.isoformat()}; no hay versiones anteriores a esa fecha")
    return f.isoformat()


def cita(fila: sqlite3.Row) -> dict:
    """Los cinco campos de RF-10 más una frase lista para pegar en una respuesta."""
    base = (fila["tipo_documento"] == "ley" and fila["vigente_desde"] == CORTE.isoformat()
            and fila["publicado_dof"] < CORTE.isoformat())
    desde = (f"vigente al {CORTE.isoformat()} (inicio del corpus)" if base
             else f"vigente desde {fila['vigente_desde']}")
    hasta = f" hasta {fila['vigente_hasta']}" if fila["vigente_hasta"] else ""
    prefijo = {"articulo": "art. ", "regla": "regla ", "seccion": "sección "}.get(fila["tipo"], "")
    if base and (fila["titulo"] or "").startswith(EXPEDICION):
        # Sin nota no hay fecha de última reforma: LeyesBiblio solo anota las del CFF desde 2021.
        origen = f"sin nota de reforma en la fuente; ley publicada en el DOF el {fila['publicado_dof']}"
    elif fila["decreto"].startswith(PORTAL):
        origen = f"{fila['titulo']}, versión del Portal del SAT del {fila['publicado_dof']} (no se publica en el DOF)"
    elif RESOLUCION in (fila["titulo"] or ""):
        genero = "o" if fila["titulo"].startswith("Anexo") else "a"  # "Anexo 8 ..., publicado"; "Primera Modificación ..., publicada"
        origen = f"{fila['titulo']}, publicad{genero} en el DOF el {fila['publicado_dof']}"
    else:
        origen = f"{'última reforma publicada' if base else 'decreto publicado'} en el DOF el {fila['publicado_dof']}"
    return {
        "documento": fila["documento"],
        "unidad": fila["unidad"],
        "vigente_desde": fila["vigente_desde"],
        "vigente_hasta": fila["vigente_hasta"],
        "decreto_dof": fila["decreto"],
        "publicado_dof": fila["publicado_dof"],
        "fuente_url": fila["fuente_url"],
        "texto": f"{fila['documento']}, {prefijo}{fila['unidad']}, {desde}{hasta}; {origen}",
    }


def _salida(fila: sqlite3.Row, **extra) -> dict:
    return {"documento": fila["documento"], "nombre_documento": fila["nombre"], "unidad": fila["unidad"],
            "jerarquia": fila["jerarquia"], "titulo_decreto": fila["titulo"], **extra, "cita": cita(fila)}


def documento_de(documento: str, fecha: str) -> str:
    """"RMF" es la del año de la fecha: cada RMF rige del 1 de enero al 31 de diciembre. Lo mismo
    con sus anexos: "Anexo 8", "A8" o "RMF-A8" -> "RMF2026-A8"."""
    d = re.sub(r"\s+", "", documento).upper()
    if m := re.fullmatch(r"(?:RMF(\d{4})?-?)?(?:ANEXO|A)(\d+(?:-[A-Z])?)", d):
        return f"RMF{m.group(1) or fecha[:4]}-A{m.group(2)}"
    return f"RMF{fecha[:4]}" if d == "RMF" else d


def articulo(con: sqlite3.Connection, documento: str, unidad: str, fecha: str | None = None) -> dict:
    f = _fecha(fecha)
    pedido, documento = documento, documento_de(documento, f)
    candidatos = [documento]
    if "-A" in documento and not re.search(r"\d{4}", pedido):
        # Un anexo sin año: el del año anterior rige hasta que se publica el nuevo (`anexos.vigor`), y
        # el 20 es el de la RMF 2022, prorrogado cada año. La vigencia escoge entre los de todos los años.
        candidatos += [d for (d,) in con.execute("SELECT id FROM documentos WHERE id GLOB ? ORDER BY id DESC",
                                                 ("RMF[0-9][0-9][0-9][0-9]" + documento[7:],)) if d != documento]
    fila = None
    for documento in candidatos:
        fila = con.execute(
            f"SELECT {_COLUMNAS}, v.id, v.texto, v.notas FROM {_JOIN} "
            f"WHERE v.documento = :doc AND v.clave = :clave AND {_VIGENTE}",
            {"doc": documento, "clave": clave(unidad), "fecha": f}).fetchone()
        if fila:
            break
    if fila is None:
        raise LookupError(f"no hay {unidad!r} de {documento!r} vigente el {f}")
    return _salida(fila, fecha_consulta=f, texto=fila["texto"], notas=fila["notas"],
                   relacionadas=relacionadas(con, fila["id"], f))


def versiones(con: sqlite3.Connection, documento: str, unidad: str) -> list[dict]:
    filas = con.execute(
        f"SELECT {_COLUMNAS}, v.texto FROM {_JOIN} WHERE v.documento = ? AND v.clave = ? ORDER BY v.vigente_desde",
        (documento_de(documento, date.today().isoformat()), clave(unidad))).fetchall()
    if not filas:
        raise LookupError(f"no hay {unidad!r} en {documento!r}")
    return [_salida(f, texto=f["texto"]) for f in filas]


def indexar(con: sqlite3.Connection) -> None:
    """Llena las dos tablas de búsqueda. Va al final de la construcción, con todas las versiones."""
    con.execute("INSERT INTO versiones_fts(versiones_fts) VALUES ('rebuild')")
    con.executemany("INSERT INTO busqueda (rowid, unidad, texto) VALUES (?, ?, ?)",
                    ((i, " ".join(lexico.raices(u)), " ".join(lexico.raices(t)))
                     for i, u, t in con.execute("SELECT id, unidad, texto FROM versiones").fetchall()))


def fragmentos(con: sqlite3.Connection):
    """(id de versión, texto a embeber) de cada fragmento, con su contexto al frente."""
    from .fragmentos import contexto, partir
    from .vectores import FRAGMENTO
    filas = con.execute("SELECT v.id, d.nombre, v.jerarquia, v.unidad, v.tipo, v.texto FROM versiones v "
                        "JOIN documentos d ON d.id = v.documento ORDER BY v.id").fetchall()
    for id_, nombre, jerarquia, unidad, tipo, texto in filas:
        ctx = contexto(nombre, jerarquia, unidad, tipo)
        yield from ((id_, ctx + parte) for parte in partir(texto, FRAGMENTO))


def vectorizar(con: sqlite3.Connection, cache) -> None:
    """Llena `fragmentos` con los vectores de `cache` (`vectores.Cache`), que embebe lo que no tenga."""
    con.executemany("INSERT INTO fragmentos (version, vector) VALUES (?, ?)",
                    [(id_, cache.vector(t)) for id_, t in list(fragmentos(con))])


PREFERENCIA = 1.5  # multiplica el puntaje BM25 de los artículos de una ley que la consulta nombra
CANDIDATOS = 20  # de cada lista antes de fusionar
RRF, PESO_VECTORES = 60, 2.0  # fusión por rango; con peso de 1.5 a 3 el recall no cambió (plan.md, sección 13)
# Parte del puntaje de una regla que pasa a cada artículo candidato que reglamenta. De 0.5 a 1.0 el
# recall va de 0.84 a 0.86 y desde 1.5 baja a 0.82 (plan.md, sección 14).
PROPAGACION = 0.75


def _por_bm25(con: sqlite3.Connection, consulta: str, terminos: list[str], fecha: str) -> list[int]:
    leyes = sorted(documento_de(d, fecha) for d in lexico.mencionados(consulta))
    return [r[0] for r in con.execute(
        f"SELECT v.id, -bm25(busqueda) * (CASE WHEN v.documento IN ({','.join('?' * len(leyes)) or 'NULL'}) "
        f"THEN {PREFERENCIA} ELSE 1 END) AS puntaje FROM busqueda JOIN versiones v ON v.id = busqueda.rowid "
        f"WHERE busqueda MATCH ? AND {_VIGENTE.replace(':fecha', '?')} ORDER BY puntaje DESC LIMIT ?",
        (*leyes, " OR ".join(f'"{t}"' for t in terminos), fecha, fecha, CANDIDATOS))]


def _por_vector(con: sqlite3.Connection, consulta: str, fecha: str) -> list[int]:
    """Versiones vigentes ordenadas por su fragmento más parecido. Fuerza bruta: ~5,300 vectores en total."""
    filas = con.execute(f"SELECT v.id, f.vector FROM fragmentos f JOIN versiones v ON v.id = f.version "
                        f"WHERE {_VIGENTE}", {"fecha": fecha}).fetchall()
    if not filas:
        return []
    from .vectores import modelo
    matriz = np.frombuffer(b"".join(r[1] for r in filas), dtype=np.float32).reshape(len(filas), -1)
    mejor: dict[int, float] = {}
    for (version, _), s in zip(filas, (matriz @ modelo().embeber(consulta)).tolist()):
        mejor[version] = max(mejor.get(version, -1.0), s)
    return sorted(mejor, key=mejor.__getitem__, reverse=True)[:CANDIDATOS]


def _propagar(con: sqlite3.Connection, puntos: dict[int, float], fecha: str) -> None:
    """Una regla candidata pasa parte de su puntaje a los artículos que reglamenta (un salto por el
    grafo): la ley no queda enterrada bajo las reglas que la detallan. Solo a artículos que ya son
    candidatos: si no, uno que reglamentan cientos de reglas (CFF 27) subiría en cualquier consulta."""
    if not PROPAGACION or not puntos:
        return
    marcas = ",".join("?" * len(puntos))
    extra: dict[int, float] = {}
    for origen, destino in con.execute(
            f"SELECT a.version, v.id FROM aristas a JOIN versiones v ON v.documento = a.documento AND v.clave = a.clave "
            f"WHERE a.tipo = 'REGLAMENTA' AND a.version IN ({marcas}) AND {_VIGENTE.replace(':fecha', '?')}",
            (*puntos, fecha, fecha)):
        extra[destino] = max(extra.get(destino, 0.0), PROPAGACION * puntos[origen])
    for destino, s in extra.items():
        if destino in puntos:
            puntos[destino] += s


def _con_tarifa(con: sqlite3.Connection, ids: list[int], puntos: dict[int, float], fecha: str, limite: int) -> list[int]:
    """Una tarifa del Anexo 8 casi no se encuentra por sí sola (es toda números y las 31 de un año se
    parecen), pero el artículo que la pide sí. Si entre los primeros `limite` hay un artículo y alguna
    sección de anexo candidata lo reglamenta, una tarifa de ese artículo ocupa el último lugar. Se
    toma el artículo mejor colocado que tenga alguna, así que la tarifa es la suya, no cualquiera.
    Entre las suyas gana la que nombra el año de la fecha (el anexo de 2026 trae la tarifa anual de
    2025 y la de 2026, y las dos reglamentan el art. 152), como "RMF" es la del año de la fecha; luego,
    la de mejor puntaje."""
    if limite < 2:
        return ids
    arriba, resto = ids[:limite], ids[limite:]
    marcas = ",".join("?" * len(arriba))
    if con.execute(f"SELECT 1 FROM versiones WHERE id IN ({marcas}) AND documento GLOB 'RMF*-A*'", arriba).fetchone():
        return ids  # ya hay una sección de anexo arriba
    filas = con.execute(
        f"SELECT v.id, o.id, instr(substr(o.texto, 1, instr(o.texto || char(10), char(10))), ?) > 0 FROM versiones v "
        f"JOIN aristas a ON a.documento = v.documento AND a.clave = v.clave JOIN versiones o ON o.id = a.version "
        f"WHERE a.tipo = 'REGLAMENTA' AND v.id IN ({marcas}) AND o.documento GLOB 'RMF*-A*' "
        f"AND {_VIGENTE.replace('v.', 'o.').replace(':fecha', '?')}", (fecha[:4], *arriba, fecha, fecha)).fetchall()
    por_articulo: dict[int, list[tuple[int, int]]] = {}
    for articulo_, seccion, del_anio in filas:
        por_articulo.setdefault(articulo_, []).append((seccion, del_anio))
    con_candidata = [a for a, ss in por_articulo.items() if any(s in puntos for s, _ in ss)]
    if not con_candidata:
        return ids  # el artículo no tiene tarifa entre las candidatas: la consulta no es de tarifas
    primero = min(con_candidata, key=arriba.index)
    elegida = max(por_articulo[primero], key=lambda x: (x[1], puntos.get(x[0], 0.0)))[0]
    puntos.setdefault(elegida, 0.0)  # puntaje 0: llegó por el grafo, no por la búsqueda
    return arriba[:-1] + [elegida] + [i for i in [arriba[-1]] + resto if i != elegida]


def relacionadas(con: sqlite3.Connection, version: int, fecha: str, limite: int = 10) -> list[dict]:
    """Vecinos a un salto vigentes en `fecha`: lo que la unidad remite o reglamenta, y las reglas que
    la reglamentan a ella."""
    vigente = _VIGENTE.replace(":fecha", "?")
    filas = con.execute(
        f"SELECT a.tipo, v.documento, v.unidad FROM aristas a JOIN versiones v ON v.documento = a.documento "
        f"AND v.clave = a.clave WHERE a.version = ? AND {vigente} "
        f"UNION SELECT 'REGLAMENTADA_POR', v.documento, v.unidad FROM aristas a JOIN versiones v ON v.id = a.version "
        f"JOIN versiones o ON o.documento = a.documento AND o.clave = a.clave "
        f"WHERE o.id = ? AND a.tipo = 'REGLAMENTA' AND {vigente} LIMIT ?",
        (version, fecha, fecha, version, fecha, fecha, limite * 2)).fetchall()
    por_tipo: dict[str, list[dict]] = {}
    for tipo, doc, unidad in filas:
        if len(por_tipo.setdefault(tipo, [])) < limite:
            por_tipo[tipo].append({"documento": doc, "unidad": unidad})
    return [{"relacion": t, **u} for t, us in por_tipo.items() for u in us]


def buscar(con: sqlite3.Connection, consulta: str, fecha: str | None = None, limite: int = 5) -> list[dict]:
    """Búsqueda híbrida sobre las versiones vigentes en `fecha`: BM25 sobre raíces y embeddings,
    fusionados por rango, y un salto por el grafo (`_propagar`). Sin vectores en la base, solo BM25.
    Un artículo o regla citado por número ("art. 27 fracción V LISR", "regla 2.1.6") sale primero.
    Devuelve un fragmento y las unidades relacionadas; el texto completo, con `articulo`."""
    f, limite = _fecha(fecha), max(1, min(limite, 20))
    salida = []
    for doc, unidad in lexico.referencias(consulta):
        try:
            a = articulo(con, doc, unidad, f)
        except LookupError:
            continue
        salida.append({k: v for k, v in a.items() if k not in ("texto", "notas", "fecha_consulta")}
                      | {"fragmento": a["texto"][:300], "puntaje": None})
    terminos = lexico.consulta(consulta)
    if not terminos and not salida:
        raise ValueError("la consulta no tiene palabras que buscar")
    puntos: dict[int, float] = {}
    for peso, lista in ((1.0, _por_bm25(con, consulta, terminos, f) if terminos else []),
                        (PESO_VECTORES, _por_vector(con, consulta, f))):
        for rango, i in enumerate(lista, 1):
            puntos[i] = puntos.get(i, 0.0) + peso / (RRF + rango)
    _propagar(con, puntos, f)
    ids = sorted(puntos, key=puntos.__getitem__, reverse=True)[:max(limite, CANDIDATOS)]
    ids = _con_tarifa(con, ids, puntos, f, limite - len(salida))
    marcas = ",".join("?" * len(ids)) or "NULL"
    filas = {r["id"]: r for r in con.execute(f"SELECT {_COLUMNAS}, v.id, substr(v.texto, 1, 300) AS inicio "
                                             f"FROM {_JOIN} WHERE v.id IN ({marcas})", ids)}
    # Fragmento del texto literal: cada raíz como prefijo ("deduc"* resalta "deducciones").
    fragmentos = dict(con.execute(
        f"SELECT rowid, snippet(versiones_fts, 1, '«', '»', ' … ', 40) FROM versiones_fts "
        f"WHERE versiones_fts MATCH ? AND rowid IN ({marcas})",
        (" OR ".join(f'"{t}"*' for t in terminos), *ids)).fetchall()) if terminos else {}
    vistos = {(s["documento"], s["unidad"]) for s in salida}
    salida += [_salida(r, fragmento=fragmentos.get(i) or r["inicio"], puntaje=round(puntos[i] * 1000, 2), version=i)
               for i in ids if (r := filas[i]) and (r["documento"], r["unidad"]) not in vistos]
    # puntaje: fusión por rango ×1000 (más alto, más relevante); solo se compara dentro de una consulta.
    # None: el artículo se pidió por número.
    salida = salida[:limite]
    for s in salida:
        if "version" in s:  # las pedidas por número ya traen sus relacionadas de `articulo`
            s["relacionadas"] = relacionadas(con, s.pop("version"), f)
    return salida
