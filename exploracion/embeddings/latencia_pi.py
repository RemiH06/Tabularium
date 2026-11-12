"""Latencia de embeber una consulta en la CPU de la Pi con ONNX int8 (RNF-04: buscar en menos de 2 s).

Uso (en frambuesa-yi, venv con onnxruntime, tokenizers, huggingface_hub y numpy):
    python latencia_pi.py consultas.jsonl salida/
Escribe <modelo>.npy con los vectores de las consultas (para compararlos con los de la GPU) e
imprime p50, p95, carga y memoria residente por modelo.
"""
import json
import resource
import statistics
import sys
import time
from pathlib import Path

import numpy as np
import onnxruntime as ort
from huggingface_hub import hf_hub_download
from tokenizers import Tokenizer

MODELOS = [  # (repo con ONNX, nombre corto, prefijo de consulta, agregación)
    ("Xenova/multilingual-e5-small", "multilingual-e5-small", "query: ", "media"),
    ("Xenova/multilingual-e5-base", "multilingual-e5-base", "query: ", "media"),
    ("Xenova/multilingual-e5-large", "multilingual-e5-large", "query: ", "media"),
    ("Xenova/bge-m3", "bge-m3", "", "cls"),
]

consultas = [json.loads(l)["texto"] for l in open(sys.argv[1], encoding="utf-8")]
salida = Path(sys.argv[2])
salida.mkdir(exist_ok=True)
solo = sys.argv[3:]  # nombres cortos, opcional

for repo, corto, prefijo, agregacion in MODELOS:
    if solo and corto not in solo:
        continue
    onnx = hf_hub_download(repo, "onnx/model_quantized.onnx")
    tok = Tokenizer.from_file(hf_hub_download(repo, "tokenizer.json"))
    tok.enable_truncation(512)
    opciones = ort.SessionOptions()
    opciones.intra_op_num_threads = 4
    t0 = time.perf_counter()
    sesion = ort.InferenceSession(onnx, opciones, providers=["CPUExecutionProvider"])
    carga = time.perf_counter() - t0
    entradas = {i.name for i in sesion.get_inputs()}

    def embeber(texto: str) -> np.ndarray:
        e = tok.encode(prefijo + texto)
        ids = np.array([e.ids], dtype=np.int64)
        mascara = np.array([e.attention_mask], dtype=np.int64)
        feed = {"input_ids": ids, "attention_mask": mascara}
        if "token_type_ids" in entradas:
            feed["token_type_ids"] = np.zeros_like(ids)
        h = sesion.run(None, feed)[0][0]  # last_hidden_state: (tokens, dim)
        v = h[0] if agregacion == "cls" else h.mean(axis=0)
        return v / np.linalg.norm(v)

    embeber("calentamiento")
    tiempos, vectores = [], []
    for c in consultas:
        t = time.perf_counter()
        vectores.append(embeber(c))
        tiempos.append(time.perf_counter() - t)
    np.save(salida / f"{corto}.npy", np.array(vectores, dtype=np.float32))
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
    print(f"{corto}: p50 {statistics.median(tiempos) * 1000:.0f} ms, "
          f"p95 {statistics.quantiles(tiempos, n=20)[-1] * 1000:.0f} ms, carga {carga:.1f} s, "
          f"RSS máx. acumulado {rss:.0f} MB", flush=True)
    del sesion
