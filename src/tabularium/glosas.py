"""Etiqueta (▲ ▼ ◆) y resumen de cada cambio de una Novella, generados por el Baker `glosador` (RF-11).

Como los glosadores de Bolonia, que anotaban al margen del texto sin tocarlo: el diff literal es la
verdad y la glosa se muestra como generada (R-05).

Lo generado vive fuera de la base, que se regenera: `cache/glosas.db`, con llave en el texto
anterior y el nuevo, así que un cambio no se pide dos veces. `construir` copia la caché a la tabla
`glosas`. Con Pixilate apagada, `glosar` se detiene y las Novellae siguen con efecto y resumen en null.

El Baker se llama por su CLI (`baker run`, de 29.Bakery) en un proceso aparte, no como librería:
`bakers` pide Python 3.13 y este proyecto corre en 3.12 en la Pi. El comando sale de la variable
`TABULARIUM_BAKER` (por omisión, `baker` en el PATH).
"""
from __future__ import annotations

import json
import os
import shlex
import sqlite3
import subprocess
import tempfile
from pathlib import Path

from .novellae import Diff, diff, llave, novellae, recortar

BAKER = "glosador"
CONTEXTO = 30  # palabras alrededor de cada cambio en lo que lee el Baker
TAREA = "Describe this change and choose its effect for the taxpayer."


class BakerCaido(Exception):
    """El gateway no respondió o respondió fuera de esquema: se detiene y lo demás queda en null."""


def baker(*args: str) -> dict:
    comando = shlex.split(os.environ.get("TABULARIUM_BAKER", "baker")) + list(args)
    try:
        # Tope de 15 min: la primera llamada puede esperar a que llama-swap cargue el modelo.
        r = subprocess.run(comando, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=900)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise BakerCaido(f"no se pudo correr {comando[0]}: {e}") from e
    if r.returncode:
        raise BakerCaido((r.stderr.strip().splitlines() or [f"{comando[0]} salió con {r.returncode}"])[-1])
    return json.loads(r.stdout)


def textos(d: Diff) -> tuple[str, str]:
    """(anterior, nuevo) desde el diff completo: unir "=" y "-" da uno y "=" y "+", el otro (RF-11)."""
    return "".join(t for op, t in d if op != "+"), "".join(t for op, t in d if op != "-")


class Cache:
    """llave -> glosa, en un SQLite aparte que sobrevive a cada reconstrucción (como `vectores.Cache`)."""

    def __init__(self):
        from .construir import cache_dir  # construir importa este módulo
        cache_dir().mkdir(parents=True, exist_ok=True)
        self.con = sqlite3.connect(cache_dir() / "glosas.db")
        self.con.execute("CREATE TABLE IF NOT EXISTS glosas (llave TEXT PRIMARY KEY, efecto TEXT NOT NULL, "
                         "resumen TEXT NOT NULL, modelo TEXT, generado TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)")

    def __contains__(self, k: str) -> bool:
        return self.con.execute("SELECT 1 FROM glosas WHERE llave = ?", (k,)).fetchone() is not None

    def poner(self, k: str, efecto: str, resumen: str, modelo: str | None) -> None:
        with self.con:
            self.con.execute("INSERT OR REPLACE INTO glosas (llave, efecto, resumen, modelo) VALUES (?, ?, ?, ?)",
                             (k, efecto, resumen, modelo))

    def filas(self) -> list[tuple]:
        return self.con.execute("SELECT llave, efecto, resumen, modelo, generado FROM glosas").fetchall()

    def close(self) -> None:
        self.con.close()


def plano(texto: str) -> str:
    return " ".join(texto.split())


def entrada(novella: dict, documento: dict, unidad: str, anterior: str, nuevo: str) -> str:
    """Lo que lee el Baker: de dónde es el cambio y el diff con contexto, marcado como en `git diff --word-diff`.
    El diff es de los textos sin saltos de renglón: en los anexos, el PDF original y la compilada cortan
    los renglones en otro lugar, y el diff literal marca cada palabra que cambió de renglón."""
    marcas = {"=": "{}", "-": "[-{}-]", "+": "{{+{}+}}"}
    cambios = "".join(marcas[op].format(t) for op, t in recortar(diff(plano(anterior), plano(nuevo)), CONTEXTO))
    return (f"Norma: {documento['nombre']} ({documento['documento']})\nUnidad: {unidad}\n"
            f"Publicación: {novella['titulo']}, DOF {novella['publicado_dof']}\n\n"
            "Cambios (texto quitado entre [- -], texto agregado entre {+ +}; […] marca "
            f"texto sin cambios que se omitió):\n\n{cambios}\n")


def por_glosar(con: sqlite3.Connection, desde: str | None, hasta: str | None, cache: Cache) -> list[tuple[str, str]]:
    """(llave, entrada) de los cambios sin etiqueta objetiva (ni ✚ ni ✖) que la caché no tiene. Un cambio
    que solo mueve espacios o saltos de renglón no se glosa."""
    salida: dict[str, str] = {}
    for n in novellae(con, desde, hasta, contexto=None):
        for doc in n["documentos"]:
            for c in doc.get("cambios", []):
                if c["efecto"] is None and c["diff"]:
                    anterior, nuevo = textos(c["diff"])
                    k = llave(anterior, nuevo)
                    if plano(anterior) != plano(nuevo) and k not in cache and k not in salida:
                        salida[k] = entrada(n, doc, c["unidad"], anterior, nuevo)
    return list(salida.items())


def glosar(con: sqlite3.Connection, desde: str | None = None, hasta: str | None = None,
           limite: int | None = None) -> dict:
    """Pide al Baker la glosa de cada cambio pendiente. Si el gateway falla (Pixilate apagada, marcha
    `ninguna`), se detiene: lo hecho queda en la caché y lo demás, en null hasta la siguiente corrida."""
    cache = Cache()
    try:
        pendientes = por_glosar(con, desde, hasta, cache)
        hechas, modelo = 0, None
        try:
            if pendientes:
                modelo = baker("status")["bakers"][BAKER]  # el de la marcha activa, para medir R-05 por modelo
            with tempfile.TemporaryDirectory() as tmp:
                archivo = Path(tmp) / "cambio.txt"
                for k, texto in pendientes[:limite]:
                    archivo.write_text(texto, encoding="utf-8")
                    r = baker("run", BAKER, "-t", TAREA, "-f", str(archivo))
                    if r.get("efecto") not in ("amplia", "restringe", "aclara") or not str(r.get("resumen", "")).strip():
                        raise BakerCaido(f"respuesta fuera de esquema: {sorted(r)}")
                    cache.poner(k, r["efecto"], r["resumen"].strip(), modelo)
                    hechas += 1
        except BakerCaido as e:
            return {"pendientes": len(pendientes), "hechas": hechas, "modelo": modelo, "error": str(e)}
        return {"pendientes": len(pendientes), "hechas": hechas, "modelo": modelo, "error": None}
    finally:
        cache.close()


def copiar(con: sqlite3.Connection) -> int:
    """De la caché a la tabla `glosas` de la base que se construye."""
    from .construir import cache_dir
    if not (cache_dir() / "glosas.db").exists():
        return 0
    cache = Cache()
    try:
        filas = cache.filas()
    finally:
        cache.close()
    con.executemany("INSERT INTO glosas VALUES (?, ?, ?, ?, ?)", filas)
    return len(filas)
