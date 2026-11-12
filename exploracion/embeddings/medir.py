"""Recall@5 con vectores solos y con la búsqueda híbrida (fusión por rango con BM25), por modelo.

Uso: uv run python exploracion/embeddings/medir.py data/embeddings [carpeta con vectores de la Pi]
Con la segunda carpeta, las consultas se embeben con el ONNX int8 de la Pi (lo que haría producción)
en vez de con el modelo de la GPU.
"""
import json
import sqlite3
import statistics
import sys
from contextlib import closing
from pathlib import Path

import numpy as np

from tabularium import almacen, evaluacion

carpeta = Path(sys.argv[1])
pi = Path(sys.argv[2]) if len(sys.argv) > 2 else None
consultas = [json.loads(l) for l in (carpeta / "consultas.jsonl").open(encoding="utf-8")]
indice = {c["texto"]: i for i, c in enumerate(consultas)}
RRF = 60


def version_de(variante: str) -> np.ndarray:
    return np.array([json.loads(l)["version"] for l in (carpeta / f"fragmentos_{variante}.jsonl").open(encoding="utf-8")])


def buscadores(frag: np.ndarray, qv: np.ndarray, versiones: np.ndarray):
    tope = versiones.max() + 1

    def por_vector(con, consulta, fecha, n):
        sims = frag @ qv[indice[consulta]]
        mejor = np.full(tope, -1.0)
        np.maximum.at(mejor, versiones, sims)  # una versión vale lo que su mejor fragmento
        f = almacen._fecha(fecha)
        filas = {r["id"]: r for r in con.execute(
            f"SELECT {almacen._COLUMNAS}, v.id FROM {almacen._JOIN} WHERE {almacen._VIGENTE}", {"fecha": f})}
        orden = sorted(filas, key=lambda i: -mejor[i])[:n]
        return [almacen._salida(filas[i], puntaje=float(mejor[i]), id=i) for i in orden]

    def hibrido(con, consulta, fecha, n):
        lexicos = almacen.buscar(con, consulta, fecha, 20)
        exactos = [h for h in lexicos if h["puntaje"] is None]
        clave = lambda h: (h["documento"], h["unidad"])
        puntos, por_clave = {}, {}
        for lista in ([h for h in lexicos if h["puntaje"] is not None], por_vector(con, consulta, fecha, 20)):
            for rango, h in enumerate(lista, 1):
                puntos[clave(h)] = puntos.get(clave(h), 0) + 1 / (RRF + rango)
                por_clave.setdefault(clave(h), h)
        vistos = {clave(h) for h in exactos}
        resto = [por_clave[c] for c in sorted(puntos, key=lambda c: -puntos[c]) if c not in vistos]
        return (exactos + resto)[:n]

    return por_vector, hibrido


def callar(con, por_vector) -> str:
    """¿La similitud del mejor resultado separa las preguntas fuera del corpus?"""
    preguntas, fuera = evaluacion.leer()
    dentro = [por_vector(con, p.texto, p.fecha, 1)[0]["puntaje"] for p in preguntas if p.documento in ("LISR", "CFF", "LIVA")]
    afuera = [por_vector(con, f["Pregunta (callar)"], None, 1)[0]["puntaje"] for f in fuera]
    return (f"similitud máx.: dentro min {min(dentro):.3f} mediana {statistics.median(dentro):.3f} | "
            f"callar mediana {statistics.median(afuera):.3f} máx {max(afuera):.3f}")


with closing(almacen.abrir(Path("data/tabularium.db"))) as con:
    base = evaluacion.evaluar(con)
    print(f"{'BM25 solo':<34} recall {base['recall_version']}")
    for npz in sorted(carpeta.glob("*__*.npz")):
        modelo, variante = npz.stem.split("__")
        datos = np.load(npz)
        qv = datos["consultas"]
        if pi:
            ruta = pi / f"{modelo}.npy"
            if not ruta.exists():
                continue
            qpi = np.load(ruta)
            print(f"  {modelo}: coseno consulta GPU contra Pi int8, mediana "
                  f"{statistics.median((qv * qpi).sum(1)):.4f}")
            qv = qpi
        por_vector, hibrido = buscadores(datos["fragmentos"], qv, version_de(variante))
        rv = evaluacion.evaluar(con, buscador=por_vector)
        rh = evaluacion.evaluar(con, buscador=hibrido)
        fallan = [f["n"] for f in rh["preguntas"] if not f["version"]]
        print(f"{modelo + ' / ' + variante:<34} vectores {rv['recall_version']:.3f}  híbrido {rh['recall_version']:.3f} "
              f"{rh['recall_version_por_tipo']}  fallan {fallan}")
        print("   ", callar(con, por_vector))
