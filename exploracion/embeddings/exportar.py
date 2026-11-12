"""Exporta fragmentos y consultas para vectorizarlos en Pixilate (experimento de la iteración 2).

Uso: uv run python exploracion/embeddings/exportar.py data/embeddings
Escribe fragmentos_<variante>.jsonl (version_id, texto) y consultas.jsonl (n, texto).
"""
import json
import sqlite3
import sys
from pathlib import Path

from tabularium import evaluacion
from tabularium.fragmentos import contexto, partir

# Variante -> largo máximo del cuerpo de cada fragmento (el contexto va aparte).
VARIANTES = {"parrafos": 1500, "medio": 6000, "unidad": 24000}  # ≈ 512, 2k y 8k tokens con el contexto

salida = Path(sys.argv[1])
salida.mkdir(parents=True, exist_ok=True)
con = sqlite3.connect("data/tabularium.db")
filas = con.execute("SELECT v.id, d.nombre, v.jerarquia, v.unidad, v.tipo, v.texto FROM versiones v "
                    "JOIN documentos d ON d.id = v.documento ORDER BY v.id").fetchall()
for variante, maximo in VARIANTES.items():
    n = 0
    with (salida / f"fragmentos_{variante}.jsonl").open("w", encoding="utf-8") as f:
        for id_, nombre, jer, unidad, tipo, texto in filas:
            ctx = contexto(nombre, jer, unidad, tipo)
            for parte in partir(texto, maximo):
                f.write(json.dumps({"version": id_, "texto": ctx + parte}, ensure_ascii=False) + "\n")
                n += 1
    print(variante, n, "fragmentos")

preguntas, callar = evaluacion.leer()
with (salida / "consultas.jsonl").open("w", encoding="utf-8") as f:
    for p in preguntas:
        f.write(json.dumps({"n": p.n, "texto": p.texto}, ensure_ascii=False) + "\n")
    for c in callar:
        f.write(json.dumps({"n": "c" + c["Original"], "texto": c["Pregunta (callar)"]}, ensure_ascii=False) + "\n")
print(len(preguntas) + len(callar), "consultas")
