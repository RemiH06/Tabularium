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

from . import lexico

CORTE = date(2024, 1, 1)  # inicio del corpus: la línea base es el texto vigente a esta fecha
EXPEDICION = "Expedición: "  # prefijo del título del decreto que expide una ley

ESQUEMA = """
CREATE TABLE documentos (
    id TEXT PRIMARY KEY,
    nombre TEXT NOT NULL,
    tipo TEXT NOT NULL CHECK (tipo IN ('ley', 'decreto'))
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
    tipo TEXT NOT NULL CHECK (tipo IN ('articulo', 'transitorio')),
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
"""

_COLUMNAS = """v.documento, d.nombre, v.unidad, v.tipo, v.jerarquia, v.vigente_desde, v.vigente_hasta,
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
    base = fila["vigente_desde"] == CORTE.isoformat() and fila["publicado_dof"] < CORTE.isoformat()
    desde = (f"vigente al {CORTE.isoformat()} (inicio del corpus)" if base
             else f"vigente desde {fila['vigente_desde']}")
    hasta = f" hasta {fila['vigente_hasta']}" if fila["vigente_hasta"] else ""
    prefijo = "art. " if fila["tipo"] == "articulo" else ""
    if base and (fila["titulo"] or "").startswith(EXPEDICION):
        # Sin nota no hay fecha de última reforma: LeyesBiblio solo anota las del CFF desde 2021.
        origen = f"sin nota de reforma en la fuente; ley publicada en el DOF el {fila['publicado_dof']}"
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


def articulo(con: sqlite3.Connection, documento: str, unidad: str, fecha: str | None = None) -> dict:
    f = _fecha(fecha)
    fila = con.execute(
        f"SELECT {_COLUMNAS}, v.texto, v.notas FROM {_JOIN} "
        f"WHERE v.documento = :doc AND v.clave = :clave AND {_VIGENTE}",
        {"doc": documento.strip().upper(), "clave": clave(unidad), "fecha": f}).fetchone()
    if fila is None:
        raise LookupError(f"no hay {unidad!r} de {documento!r} vigente el {f}")
    return _salida(fila, fecha_consulta=f, texto=fila["texto"], notas=fila["notas"])


def versiones(con: sqlite3.Connection, documento: str, unidad: str) -> list[dict]:
    filas = con.execute(
        f"SELECT {_COLUMNAS}, v.texto FROM {_JOIN} WHERE v.documento = ? AND v.clave = ? ORDER BY v.vigente_desde",
        (documento.strip().upper(), clave(unidad))).fetchall()
    if not filas:
        raise LookupError(f"no hay {unidad!r} en {documento!r}")
    return [_salida(f, texto=f["texto"]) for f in filas]


def indexar(con: sqlite3.Connection) -> None:
    """Llena las dos tablas de búsqueda. Va al final de la construcción, con todas las versiones."""
    con.execute("INSERT INTO versiones_fts(versiones_fts) VALUES ('rebuild')")
    con.executemany("INSERT INTO busqueda (rowid, unidad, texto) VALUES (?, ?, ?)",
                    ((i, " ".join(lexico.raices(u)), " ".join(lexico.raices(t)))
                     for i, u, t in con.execute("SELECT id, unidad, texto FROM versiones").fetchall()))


PREFERENCIA = 1.5  # multiplica el puntaje de los artículos de una ley que la consulta nombra


def buscar(con: sqlite3.Connection, consulta: str, fecha: str | None = None, limite: int = 5) -> list[dict]:
    """BM25 sobre raíces de las versiones vigentes en `fecha`. Un artículo citado por número y ley
    ("art. 27 fracción V LISR") sale primero. Devuelve un fragmento; el texto completo, con `articulo`."""
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
    if terminos:
        leyes = sorted(lexico.mencionados(consulta))
        filas = con.execute(
            f"SELECT {_COLUMNAS}, v.id, -bm25(busqueda) * (CASE WHEN v.documento IN "
            f"({','.join('?' * len(leyes)) or 'NULL'}) THEN {PREFERENCIA} ELSE 1 END) AS puntaje "
            f"FROM busqueda JOIN {_JOIN.replace('versiones v', 'versiones v ON v.id = busqueda.rowid', 1)} "
            f"WHERE busqueda MATCH ? AND {_VIGENTE.replace(':fecha', '?')} ORDER BY puntaje DESC LIMIT ?",
            (*leyes, " OR ".join(f'"{t}"' for t in terminos), f, f, limite + len(salida))).fetchall()
        # Fragmento del texto literal: cada raíz como prefijo ("deduc"* resalta "deducciones").
        ids = [r["id"] for r in filas]
        fragmentos = dict(con.execute(
            f"SELECT rowid, snippet(versiones_fts, 1, '«', '»', ' … ', 40) FROM versiones_fts "
            f"WHERE versiones_fts MATCH ? AND rowid IN ({','.join('?' * len(ids)) or 'NULL'})",
            (" OR ".join(f'"{t}"*' for t in terminos), *ids)).fetchall())
        vistos = {(s["documento"], s["unidad"]) for s in salida}
        salida += [_salida(r, fragmento=fragmentos.get(r["id"], ""), puntaje=round(r["puntaje"], 3))
                   for r in filas if (r["documento"], r["unidad"]) not in vistos]
    # puntaje: BM25 positivo (más alto, más relevante); solo se compara dentro de una consulta.
    # None: el artículo se pidió por número.
    return salida[:limite]
