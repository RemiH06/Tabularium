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
"""Embebe por lote, en la GPU de Pixilate, los fragmentos que exporta `tabularium pendientes`.

Uso: uv run --script vectorizar_gpu.py pendientes.jsonl vectores.npz
Después, en la máquina de la base: `tabularium importar vectores.npz` y `tabularium construir`.

Mismo modelo y ventana que producción (bge-m3, 2,048 tokens, vector normalizado), en fp16: coseno de
0.99 contra el int8 de la Pi (plan.md, sección 13). Reanudable: guarda un tramo cada 256 fragmentos en
<salida>.partes/ y al relanzar salta los tramos hechos (apagones y juegos, ver la skill `bakery`).
"""
import json
import sys
import time
from pathlib import Path

import numpy as np
import torch
from sentence_transformers import SentenceTransformer

MODELO, VENTANA, TRAMO = "BAAI/bge-m3", 2048, 256

entrada, salida = Path(sys.argv[1]), Path(sys.argv[2])
filas = [json.loads(l) for l in entrada.open(encoding="utf-8")]
assert torch.cuda.is_available(), "sin CUDA"
torch.cuda.set_per_process_memory_fraction(0.55)  # Pixilate también es la PC de juego: ~6.6 de 12 GB
m = SentenceTransformer(MODELO, device="cuda")
m.max_seq_length = VENTANA
m.half()

partes = salida.with_suffix(".partes")
partes.mkdir(exist_ok=True)
t0 = time.time()
for inicio in range(0, len(filas), TRAMO):
    destino = partes / f"{inicio:06d}.npy"
    if destino.exists():
        continue
    textos, lote = [f["texto"] for f in filas[inicio:inicio + TRAMO]], 4
    while True:
        try:
            v = m.encode(textos, batch_size=lote, normalize_embeddings=True, convert_to_numpy=True)
            break
        except torch.cuda.OutOfMemoryError:  # alguien abrió un juego: lote más chico y otra vez
            torch.cuda.empty_cache()
            if lote == 1:
                raise
            lote //= 2
            print("OOM, lote", lote, flush=True)
    temporal = destino.with_suffix(".tmp.npy")
    np.save(temporal, v.astype(np.float32))
    temporal.replace(destino)
    print(f"{min(inicio + TRAMO, len(filas))}/{len(filas)} en {time.time() - t0:.0f} s", flush=True)

vectores = np.concatenate([np.load(partes / f"{i:06d}.npy") for i in range(0, len(filas), TRAMO)])
temporal = salida.with_suffix(".tmp.npz")
np.savez(temporal, hashes=np.array([f["hash"] for f in filas]), vectores=vectores)
temporal.replace(salida)
print(f"listo: {len(filas)} vectores en {salida}", flush=True)
