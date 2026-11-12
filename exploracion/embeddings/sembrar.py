"""Siembra la caché de vectores con los que calculó Pixilate en lote (`vectorizar.py`).

Uso: uv run python exploracion/embeddings/sembrar.py data/embeddings/fragmentos_medio.jsonl data/embeddings/bge-m3__medio.npz
Los fragmentos de la variante "medio" son los de producción (`fragmentos.contexto` más
`fragmentos.partir(texto, vectores.FRAGMENTO)`), así que su hash es el que buscará `construir`.
"""
import hashlib
import json
import sqlite3
import sys

import numpy as np

from tabularium.construir import cache_dir
from tabularium.vectores import FRAGMENTO, MODELO, Cache

assert "medio" in sys.argv[1] and FRAGMENTO == 6000, "los fragmentos deben ser los de producción"
textos = [json.loads(l)["texto"] for l in open(sys.argv[1], encoding="utf-8")]
vectores = np.load(sys.argv[2])["fragmentos"].astype(np.float32)
assert len(textos) == len(vectores)
Cache().close()  # crea la tabla si no existe
con = sqlite3.connect(cache_dir() / "vectores.db")
with con:
    con.executemany("INSERT OR IGNORE INTO vectores VALUES (?, ?, ?)",
                    [(MODELO, hashlib.sha256(t.encode("utf-8")).hexdigest(), v.tobytes()) for t, v in zip(textos, vectores)])
print(con.execute("SELECT count(*) FROM vectores WHERE modelo = ?", (MODELO,)).fetchone()[0], "vectores en la caché")
