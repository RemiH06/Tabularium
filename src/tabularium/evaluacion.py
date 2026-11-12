"""Evaluación de la recuperación (RNF-06) con el conjunto de `docs/preguntas_prueba.md`.

Lee las preguntas de las tablas del documento (una sola fuente) y reporta recall@k de dos formas:
- contra la unidad: la unidad esperada sale entre los k primeros;
- contra la versión: además, la versión que salió es la vigente en la fecha de la pregunta y cita
  la reforma esperada (columna "Versión esperada (DOF)", cuando existe). El umbral va contra esta.
Las preguntas de documentos que aún no están en la base (RMF, anexos) se cuentan como pendientes.
Los casos de callar se reportan aparte con el puntaje del primer resultado.
"""
from __future__ import annotations

import re
import sqlite3
import statistics
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from . import almacen

PREGUNTAS = Path("docs/preguntas_prueba.md")
UMBRAL = 0.85


@dataclass
class Pregunta:
    n: str
    tipo: str
    texto: str
    documento: str
    claves: set[str]  # unidades aceptadas, en forma de búsqueda
    fecha: str
    version: str | None  # fecha DOF, "sin nota" o None si la tabla no la trae


def tablas(md: str) -> list[list[dict[str, str]]]:
    """Cada tabla de Markdown como lista de filas {encabezado: celda}."""
    salida, actual = [], []
    for linea in md.splitlines() + [""]:
        if linea.startswith("|"):
            actual.append([c.strip() for c in linea.strip().strip("|").split("|")])
        elif actual:
            enc, *filas = [f for f in actual if not re.fullmatch(r"[\s:-]*", "".join(f))]
            salida.append([dict(zip(enc, f)) for f in filas])
            actual = []
    return salida


def leer(ruta: Path = PREGUNTAS) -> tuple[list[Pregunta], list[dict[str, str]]]:
    preguntas, callar = [], []
    for t in tablas(ruta.read_text(encoding="utf-8")):
        for f in t:
            if "Pregunta (callar)" in f:
                callar.append(f)
            elif {"Pregunta", "Documento", "Unidad esperada", "Fecha"} <= f.keys():
                v = f.get("Versión esperada (DOF)")
                version = "sin nota" if v and v.startswith("sin nota") else (
                    m.group(0) if v and (m := re.match(r"\d{4}-\d{2}-\d{2}", v)) else None)
                claves = {almacen.clave(u) for u in re.findall(r"(?:art\.|regla)\s*([^(),]+)", f["Unidad esperada"])}
                documento = re.sub(r"^RMF\s+(\d{4})$", r"RMF\1", f["Documento"])  # "RMF 2026" -> "RMF2026"
                preguntas.append(Pregunta(f["#"], f["Tipo"], f["Pregunta"], documento, claves, f["Fecha"], version))
    return preguntas, callar


def version_correcta(h: dict, p: Pregunta) -> bool:
    c = h["cita"]
    if not (c["vigente_desde"] <= p.fecha and (c["vigente_hasta"] is None or p.fecha < c["vigente_hasta"])):
        return False
    if p.version == "sin nota":
        return (h["titulo_decreto"] or "").startswith(almacen.EXPEDICION)
    return p.version is None or c["publicado_dof"] == p.version


def evaluar(con: sqlite3.Connection, ruta: Path = PREGUNTAS, k: int = 5, buscador=None) -> dict:
    """`buscador(con, consulta, fecha, limite)`: por defecto `almacen.buscar`; los experimentos pasan otro."""
    buscador = buscador or almacen.buscar
    preguntas, callar = leer(ruta)
    en_base = {r[0] for r in con.execute("SELECT id FROM documentos WHERE tipo IN ('ley', 'resolucion')")}
    filas, pendientes, tiempos = [], [], []
    for p in preguntas:
        if p.documento not in en_base:
            pendientes.append(p.n)
            continue
        t0 = time.perf_counter()
        hits = buscador(con, p.texto, p.fecha, k)
        tiempos.append(time.perf_counter() - t0)
        rango = next((i for i, h in enumerate(hits, 1)
                      if h["documento"] == p.documento and almacen.clave(h["unidad"]) in p.claves), None)
        filas.append({"n": p.n, "tipo": p.tipo, "documento": p.documento, "esperada": sorted(p.claves),
                      "rango": rango, "version": bool(rango and version_correcta(hits[rango - 1], p)),
                      "primero": f"{hits[0]['documento']} {hits[0]['unidad']}" if hits else None})
    casos = []
    for f in callar:
        hits = buscador(con, f["Pregunta (callar)"], None, 1)
        casos.append({"original": f["Original"], "materia": f["Materia"],
                      "primero": f"{hits[0]['documento']} {hits[0]['unidad']}" if hits else None,
                      "puntaje": hits[0]["puntaje"] if hits else None})
    n = len(filas)
    por_tipo = {t: round(sum(1 for f in filas if f["tipo"] == t and f["version"]) /
                         max(1, sum(1 for f in filas if f["tipo"] == t)), 3) for t in sorted({f["tipo"] for f in filas})}
    return {
        "fecha": date.today().isoformat(), "k": k, "evaluables": n, "pendientes": pendientes,
        "recall_unidad": round(sum(1 for f in filas if f["rango"]) / n, 3) if n else None,
        "recall_version": round(sum(1 for f in filas if f["version"]) / n, 3) if n else None,
        "recall_version_por_tipo": por_tipo,
        "exactas_en_primero": [f["n"] for f in filas if f["tipo"] == "exacta" and f["rango"] == 1],
        "p95_ms": round(statistics.quantiles(tiempos, n=20)[-1] * 1000, 1) if len(tiempos) > 1 else None,
        "preguntas": filas, "callar": casos,
    }


def reporte(r: dict) -> str:
    lineas = [f"{'#':>3}  {'tipo':<10} {'esperada':<14} {'rango':>5}  versión  primer resultado"]
    for f in r["preguntas"]:
        esperada = f"{f['documento']} {'/'.join(f['esperada'])}"
        lineas.append(f"{f['n']:>3}  {f['tipo']:<10} {esperada:<14} {f['rango'] or '-':>5}  "
                      f"{'sí' if f['version'] else 'no':<7}  {f['primero']}")
    ok = "cumple" if (r["recall_version"] or 0) >= UMBRAL else "no cumple"
    lineas += [
        "",
        f"recall@{r['k']} contra la unidad:  {r['recall_unidad']}  ({r['evaluables']} preguntas)",
        f"recall@{r['k']} contra la versión: {r['recall_version']}  ({ok} el umbral de {UMBRAL}, RNF-06)",
        f"por tipo (versión): {r['recall_version_por_tipo']}",
        f"exactas en primer lugar (RF-08): {r['exactas_en_primero']}",
        f"latencia p95: {r['p95_ms']} ms (RNF-04 pide menos de 2000)",
        f"pendientes, documento aún fuera de la base: {', '.join(r['pendientes']) or 'ninguna'}",
        "",
        "Casos de callar (primer resultado y su puntaje BM25):",
    ]
    lineas += [f"  {c['original']:>3}  {c['materia']:<17} {c['puntaje']!s:>8}  {c['primero']}" for c in r["callar"]]
    return "\n".join(lineas)
