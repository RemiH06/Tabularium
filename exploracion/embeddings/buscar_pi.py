"""Latencia de `buscar` completo en la Pi (RNF-04) y recall con el modelo int8 de la Pi.

Uso (en frambuesa-yi, con src/ en PYTHONPATH): python buscar_pi.py tabularium.db preguntas_prueba.md
"""
import statistics
import sys
import time
from contextlib import closing
from pathlib import Path

from tabularium import almacen, evaluacion, vectores

t = time.perf_counter()
vectores.modelo()
print(f"carga del modelo: {time.perf_counter() - t:.1f} s")
with closing(almacen.abrir(Path(sys.argv[1]))) as con:
    r = evaluacion.evaluar(con, Path(sys.argv[2]))
print(f"recall@5 versión {r['recall_version']}, unidad {r['recall_unidad']}, p95 {r['p95_ms']} ms")
