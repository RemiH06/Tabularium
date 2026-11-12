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

CORTE = date(2024, 1, 1)  # inicio del corpus: la línea base es el texto vigente a esta fecha

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
    return {
        "documento": fila["documento"],
        "unidad": fila["unidad"],
        "vigente_desde": fila["vigente_desde"],
        "vigente_hasta": fila["vigente_hasta"],
        "decreto_dof": fila["decreto"],
        "publicado_dof": fila["publicado_dof"],
        "fuente_url": fila["fuente_url"],
        "texto": f"{fila['documento']}, {prefijo}{fila['unidad']}, {desde}{hasta}; "
                 f"{'última reforma publicada' if base else 'decreto publicado'} en el DOF el {fila['publicado_dof']}",
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


def buscar(con: sqlite3.Connection, consulta: str, fecha: str | None = None, limite: int = 5) -> list[dict]:
    """BM25 sobre las versiones vigentes en `fecha`. Devuelve un fragmento; el texto completo, con `articulo`."""
    terminos = re.findall(r"\w+", consulta)
    if not terminos:
        raise ValueError("la consulta no tiene palabras")
    # shortcut: sin palabras vacías ni raíces; "de" y "del" pesan. Se mide y se ajusta con el recall de la iteración 2.
    expresion = " OR ".join(f'"{t}"' for t in terminos)  # entre comillas: nada de la consulta es sintaxis FTS5
    filas = con.execute(
        f"SELECT {_COLUMNAS}, snippet(versiones_fts, 1, '«', '»', ' … ', 40) AS fragmento "
        f"FROM versiones_fts JOIN {_JOIN.replace('versiones v', 'versiones v ON v.id = versiones_fts.rowid', 1)} "
        f"WHERE versiones_fts MATCH :expr AND {_VIGENTE} ORDER BY bm25(versiones_fts) LIMIT :limite",
        {"expr": expresion, "fecha": _fecha(fecha), "limite": max(1, min(limite, 20))}).fetchall()
    return [_salida(f, fragmento=f["fragmento"]) for f in filas]
