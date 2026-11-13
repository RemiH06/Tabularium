"""Novellae (RF-11): una nota de parche por publicación del DOF, sacada de la base versionada.

Lo objetivo sale de las versiones: qué unidades cambió cada decreto y el diff literal, por
palabras, entre la versión anterior y la nueva. ✚ (nueva) y ✖ (derogada) también son objetivas.
▲ ▼ ◆ y el resumen son interpretación de un modelo (`glosas.py`) y se marcan como generados.
Una publicación que el SIDOF detectó (`dof.py`) y cuyo texto aún no está en el corpus sale como
Novella pendiente, con su enlace al DOF: así se cumple RNF-03 aunque la fuente tarde.
"""
from __future__ import annotations

import difflib
import hashlib
import re
import sqlite3
from datetime import date, timedelta

from .almacen import _COLUMNAS, _JOIN, cita, documento_de

EFECTOS = {"amplia": "▲", "restringe": "▼", "aclara": "◆"}  # lo que genera el Baker (`glosas.py`)
DEROGADA = re.compile(r"\(\s*se deroga\s*\)|^\W*derogad[ao]\W*$", re.I)
Diff = list[tuple[str, str]]  # ("=" | "-" | "+", texto)


def diff(viejo: str, nuevo: str) -> Diff:
    """Diff por palabras. Cada palabra lleva su espacio, así que unir los "=" y "-" da el texto
    viejo y unir los "=" y "+" da el nuevo, carácter por carácter (criterio de RF-11)."""
    a, b = (re.findall(r"\S+\s*|\s+", t) for t in (viejo, nuevo))
    salida: Diff = []
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if op == "equal":
            salida.append(("=", "".join(a[i1:i2])))
            continue
        if i2 > i1:
            salida.append(("-", "".join(a[i1:i2])))
        if j2 > j1:
            salida.append(("+", "".join(b[j1:j2])))
    return salida


def llave(anterior: str, nuevo: str) -> str:
    """De un cambio, para su glosa generada (`glosas.py`)."""
    return hashlib.sha256(f"{anterior}\0{nuevo}".encode("utf-8")).hexdigest()


def recortar(d: Diff, contexto: int = 12) -> Diff:
    """Para mostrar: cada tramo igual se queda con `contexto` palabras a cada lado del cambio."""
    salida: Diff = []
    for k, (op, texto) in enumerate(d):
        palabras = re.findall(r"\S+\s*|\s+", texto)
        if op != "=" or len(palabras) <= 2 * contexto:
            salida.append((op, texto))
            continue
        antes = "".join(palabras[:contexto]) if k > 0 else ""
        despues = "".join(palabras[-contexto:]) if k < len(d) - 1 else ""
        salida.append(("=", f"{antes}[…] {despues}".strip() + (" " if despues else "")))
    return salida


def _anterior(con: sqlite3.Connection, documento: str, clave: str, desde: str):
    return con.execute(
        f"SELECT {_COLUMNAS}, v.texto FROM {_JOIN} WHERE v.documento = ? AND v.clave = ? AND v.vigente_desde < ? "
        "ORDER BY v.vigente_desde DESC LIMIT 1", (documento, clave, desde)).fetchone()


def _cambio(con: sqlite3.Connection, fila: sqlite3.Row, decreto: str, contexto: int | None) -> dict:
    previa = _anterior(con, fila["documento"], fila["clave"], fila["vigente_desde"])
    if previa is None:
        efecto, d = "✚", None
    elif DEROGADA.search(fila["texto"]) and not DEROGADA.search(previa["texto"]):
        efecto, d = "✖", diff(previa["texto"], fila["texto"])
    else:
        efecto, d = None, diff(previa["texto"], fila["texto"])
    glosa = con.execute("SELECT efecto, resumen, modelo FROM glosas WHERE llave = ?",
                        (llave(previa["texto"], fila["texto"]),)).fetchone() if previa and efecto is None else None
    if d is not None and contexto is not None:
        d = recortar(d, contexto)
    return {"unidad": fila["unidad"], "efecto": efecto or (EFECTOS[glosa["efecto"]] if glosa else None),
            # Generado: lo dice un modelo (R-05) y el diff es la verdad. None: todavía sin glosa.
            "efecto_generado": False if efecto else (True if glosa else None),
            "resumen": glosa["resumen"] if glosa else None, "modelo": glosa["modelo"] if glosa else None,
            "cita": cita(fila), "anterior": cita(previa) if previa else None,
            "texto": fila["texto"] if previa is None else None, "diff": d,
            # Otras publicaciones que rigen el mismo día: el diff es de todas juntas.
            "junta": [x for (x,) in con.execute("SELECT ? UNION SELECT decreto FROM versiones_decretos WHERE version = ?",
                                                (fila["decreto"], fila["id"])) if x != decreto]}


def novellae(con: sqlite3.Connection, desde: str | None = None, hasta: str | None = None,
             documento: str | None = None, contexto: int | None = 12) -> list[dict]:
    """Novellae de las publicaciones del DOF entre `desde` y `hasta` (por fecha de publicación; por
    omisión, los últimos 90 días), de la más nueva a la más vieja. `documento` filtra ("CFF",
    "RMF2026", "Anexo 8"). `contexto`: palabras alrededor de cada cambio; None da el diff completo."""
    try:
        hasta = date.fromisoformat(hasta).isoformat() if hasta else date.today().isoformat()
        desde = date.fromisoformat(desde).isoformat() if desde else (date.fromisoformat(hasta) - timedelta(90)).isoformat()
    except ValueError as e:
        raise ValueError(f"fecha inválida: usa AAAA-MM-DD ({e})") from e
    doc = documento_de(documento, hasta) if documento else None
    salida = []
    for d in con.execute("SELECT * FROM decretos WHERE publicado_dof BETWEEN ? AND ? ORDER BY publicado_dof DESC, id",
                         (desde, hasta)).fetchall():
        filas = con.execute(
            f"SELECT {_COLUMNAS}, v.id, v.clave, v.texto FROM {_JOIN} WHERE (v.decreto = :d OR v.id IN "
            "(SELECT version FROM versiones_decretos WHERE decreto = :d)) AND v.documento != :d "
            "AND (:doc IS NULL OR v.documento = :doc) ORDER BY v.documento, v.id", {"d": d["id"], "doc": doc}).fetchall()
        transitorios = [u for (u,) in con.execute("SELECT unidad FROM versiones WHERE documento = ? ORDER BY id", (d["id"],))]
        if not filas and (doc or not transitorios):
            continue  # la Tercera RMRMF 2026 solo modificó el Anexo 7: sale, con sus transitorios y sin cambios
        documentos = []
        for nombre in dict.fromkeys(f["documento"] for f in filas):
            propias = [f for f in filas if f["documento"] == nombre]
            primera = con.execute("SELECT MIN(vigente_desde) FROM versiones WHERE documento = ?", (nombre,)).fetchone()[0]
            if all(f["vigente_desde"] == primera for f in propias):
                # Documento nuevo (la RMF de un año, un anexo): no tiene versión anterior con qué compararse.
                documentos.append({"documento": nombre, "nombre": propias[0]["nombre"], "nuevo": True,
                                   "unidades": len(propias), "vigente_desde": primera})
            else:
                documentos.append({"documento": nombre, "nombre": propias[0]["nombre"], "nuevo": False,
                                   "cambios": [_cambio(con, f, d["id"], contexto) for f in propias]})
        salida.append({"decreto_dof": d["id"], "titulo": d["titulo"], "publicado_dof": d["publicado_dof"],
                       "entrada_en_vigor": d["entrada_en_vigor"], "fuente_url": _url(con, d, [x["documento"] for x in documentos]
                                                                           + d["id"].split("-", 4)[4:]),
                       "pendiente": False, "documentos": documentos, "transitorios": transitorios})
    return sorted(salida + pendientes(con, desde, hasta, doc), key=lambda n: n["publicado_dof"], reverse=True)


def _url(con: sqlite3.Connection, d: sqlite3.Row, documentos: list[str]) -> str | None:
    """Enlace al DOF de la publicación: misma fecha y mismo título o algún documento en común (los
    de sus cambios y el del id del decreto: "DOF-2026-10-02-RMF2026" -> "RMF2026")."""
    for p in con.execute("SELECT * FROM publicaciones WHERE publicado_dof = ?", (d["publicado_dof"],)):
        if (p["titulo"] or "").casefold().rstrip(".") == (d["titulo"] or "").casefold().rstrip(".") \
                or set(p["documentos"].split()) & set(documentos):
            return p["url"]
    return None


def pendientes(con: sqlite3.Connection, desde: str, hasta: str, documento: str | None = None) -> list[dict]:
    """Publicaciones detectadas en el DOF que tocan un documento del corpus sin versiones de ese
    día en ese documento ni decreto registrado para él: el texto todavía no llega (LeyesBiblio o el
    SAT tardan; una modificación de la RMF o de un anexo entra cuando el minisitio lista su compilada)."""
    salida = []
    for p in con.execute("SELECT * FROM publicaciones WHERE publicado_dof BETWEEN ? AND ? ORDER BY publicado_dof",
                         (desde, hasta)):
        faltan = [x for x in p["documentos"].split() if (documento is None or x == documento) and not con.execute(
            "SELECT 1 FROM versiones v JOIN decretos dc ON dc.id = v.decreto WHERE v.documento = :doc "
            "AND dc.publicado_dof = :dia UNION ALL SELECT 1 FROM decretos WHERE id = 'DOF-' || :dia || '-' || :doc",
            {"doc": x, "dia": p["publicado_dof"]}).fetchone()]
        if faltan:
            salida.append({"decreto_dof": None, "titulo": p["titulo"], "publicado_dof": p["publicado_dof"],
                           "entrada_en_vigor": None, "fuente_url": p["url"], "pendiente": True,
                           "documentos": [{"documento": x, "cambios": []} for x in faltan], "transitorios": []})
    return salida
