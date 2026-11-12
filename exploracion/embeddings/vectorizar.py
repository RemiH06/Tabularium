# /// script
# requires-python = ">=3.10"
# dependencies = ["torch", "sentence-transformers", "numpy"]
#
# [[tool.uv.index]]
# name = "pytorch"
# url = "https://download.pytorch.org/whl/cu128"
# explicit = true
#
# [tool.uv.sources]
# torch = { index = "pytorch" }
# ///
"""Vectoriza fragmentos y consultas con cada modelo candidato, en la GPU de Pixilate.

Uso: uv run --script vectorizar.py <carpeta>  (con fragmentos_*.jsonl y consultas.jsonl)
Escribe <modelo>__<variante>.npz con `fragmentos` y `consultas` (float32, normalizados). Reanudable:
si el .npz ya existe, salta esa combinación.
"""
import json
import sys
import time
from pathlib import Path

import numpy as np
import torch
from sentence_transformers import SentenceTransformer

CORRIDAS = [  # (modelo, variante de fragmentos, prefijo de consulta, prefijo de fragmento, ventana)
    ("intfloat/multilingual-e5-small", "parrafos", "query: ", "passage: ", 512),
    ("intfloat/multilingual-e5-base", "parrafos", "query: ", "passage: ", 512),
    ("intfloat/multilingual-e5-large", "parrafos", "query: ", "passage: ", 512),
    ("BAAI/bge-m3", "parrafos", "", "", 512),
    ("BAAI/bge-m3", "medio", "", "", 2048),
    ("BAAI/bge-m3", "unidad", "", "", 8192),
]

carpeta = Path(sys.argv[1])
assert torch.cuda.is_available(), "sin CUDA"
torch.cuda.set_per_process_memory_fraction(0.55)  # Pixilate también es la PC de juego: ~6.6 de 12 GB
consultas = [json.loads(l)["texto"] for l in (carpeta / "consultas.jsonl").open(encoding="utf-8")]

for modelo, variante, pq, pf, ventana in CORRIDAS:
    destino = carpeta / f"{modelo.split('/')[1]}__{variante}.npz"
    if destino.exists():
        print("ya está", destino.name, flush=True)
        continue
    textos = [json.loads(l)["texto"] for l in (carpeta / f"fragmentos_{variante}.jsonl").open(encoding="utf-8")]
    m = SentenceTransformer(modelo, device="cuda")
    m.max_seq_length = ventana
    m.half()
    t0 = time.time()
    lote = 2 if ventana > 512 else 32
    while True:
        try:
            frag = m.encode([pf + t for t in textos], batch_size=lote, normalize_embeddings=True, convert_to_numpy=True)
            break
        except torch.cuda.OutOfMemoryError:  # alguien abrió un juego: lote más chico y otra vez
            torch.cuda.empty_cache()
            if lote == 1:
                raise
            lote //= 2
            print("OOM, lote", lote, flush=True)
    cons = m.encode([pq + t for t in consultas], batch_size=32, normalize_embeddings=True, convert_to_numpy=True)
    temporal = destino.with_suffix(".tmp.npz")
    np.savez(temporal, fragmentos=frag.astype(np.float32), consultas=cons.astype(np.float32))
    temporal.replace(destino)
    print(f"{destino.name}: {len(textos)} fragmentos en {time.time() - t0:.0f} s", flush=True)
    del m
    torch.cuda.empty_cache()
