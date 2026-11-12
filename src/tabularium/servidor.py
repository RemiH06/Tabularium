"""Servidor MCP de Tabularium: consulta del corpus con cita obligatoria en cada resultado."""
from __future__ import annotations

import os
from contextlib import closing
from pathlib import Path
from typing import Any

from mcp.server.mcpserver import MCPServer

from . import almacen

INSTRUCCIONES = (
    "Corpus versionado de normas fiscales de México desde el 2024-01-01: LIVA, LISR, CFF y la Resolución "
    "Miscelánea Fiscal de cada año (RMF2024, RMF2025 y RMF2026, con sus modificaciones). "
    "Regla: cita documento, unidad y fecha de versión de cada resultado (campo `cita.texto`) o no respondas. "
    "Las preguntas fiscales son por ejercicio: pasa `fecha` (AAAA-MM-DD) cuando la pregunta sea sobre otro "
    "momento que hoy. No sustituye a un abogado o contador que firme."
)


def ruta_db() -> Path:
    return Path(os.environ.get("TABULARIUM_DB", "data/tabularium.db"))


def crear_servidor(db: Path | None = None) -> MCPServer:
    db = db or ruta_db()
    servidor = MCPServer("tabularium", instructions=INSTRUCCIONES, version="0.1.0")

    @servidor.tool()
    def articulo(documento: str, unidad: str, fecha: str | None = None) -> dict[str, Any]:
        """Texto de un artículo, regla o transitorio vigente en `fecha` (hoy si se omite), con su cita.

        documento: "LIVA", "LISR", "CFF", "RMF" (la del año de `fecha`), "RMF2025" o un decreto ("DOF-2024-04-01").
        unidad: "1o.-A", "79", "2.7.1.21" (regla), "Transitorio Único".
        """
        with closing(almacen.abrir(db)) as con:
            return almacen.articulo(con, documento, unidad, fecha)

    @servidor.tool()
    def versiones(documento: str, unidad: str) -> list[dict]:
        """Todas las versiones de una unidad, de la más vieja a la más nueva, cada una con su cita."""
        with closing(almacen.abrir(db)) as con:
            return almacen.versiones(con, documento, unidad)

    @servidor.tool()
    def buscar(consulta: str, fecha: str | None = None, limite: int = 5) -> list[dict]:
        """Búsqueda híbrida (BM25 sobre raíces y embeddings bge-m3) en lo vigente en `fecha`, con un
        salto por el grafo de referencias. Un artículo o regla citado por número ("art. 27 LISR",
        "regla 2.7.1.21") sale primero, con `puntaje` nulo. Devuelve fragmentos con cita y
        `relacionadas` (lo que la unidad remite o reglamenta y las reglas de la RMF que la
        reglamentan); el texto completo se pide con `articulo`. La ley prevalece sobre la RMF, que
        solo la detalla. Que salgan resultados no significa que el corpus cubra la pregunta: si
        ninguno trata el tema, no respondas."""
        with closing(almacen.abrir(db)) as con:
            return almacen.buscar(con, consulta, fecha, limite)

    return servidor


def servir() -> None:
    with closing(almacen.abrir(ruta_db())) as con:
        if con.execute("SELECT 1 FROM fragmentos LIMIT 1").fetchone():
            from .vectores import modelo
            modelo()  # se carga al arrancar y no en la primera consulta (1.4 s en la Pi)
    # Solo loopback por defecto. En frambuesa-yi se publica a la tailnet, nunca a internet (RNF-07).
    crear_servidor().run("streamable-http", host=os.environ.get("TABULARIUM_HOST", "127.0.0.1"),
                         port=int(os.environ.get("TABULARIUM_PUERTO", "8061")))
