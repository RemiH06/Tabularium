"""Tiempo y memoria de embeber textos largos con bge-m3 int8 en la Pi (actualización diaria sin Pixilate).

Uso: python largo_pi.py fragmentos_unidad.jsonl <tokens máximos> [<tokens máximos> ...]
"""
import json
import resource
import sys
import time

import numpy as np
import onnxruntime as ort
from huggingface_hub import hf_hub_download
from tokenizers import Tokenizer

textos = sorted((json.loads(l)["texto"] for l in open(sys.argv[1], encoding="utf-8")), key=len)
tok = Tokenizer.from_file(hf_hub_download("Xenova/bge-m3", "tokenizer.json"))
op = ort.SessionOptions()
op.intra_op_num_threads = 4
s = ort.InferenceSession(hf_hub_download("Xenova/bge-m3", "onnx/model_quantized.onnx"), op, providers=["CPUExecutionProvider"])
for maximo in map(int, sys.argv[2:]):
    tok.enable_truncation(maximo)
    for t in (textos[len(textos) // 2], textos[-10]):
        e = tok.encode(t)
        ids = np.array([e.ids], dtype=np.int64)
        t0 = time.perf_counter()
        s.run(None, {"input_ids": ids, "attention_mask": np.ones_like(ids)})
        rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
        print(f"máx {maximo}: {len(e.ids)} tokens en {time.perf_counter() - t0:.1f} s, RSS máx. {rss:.0f} MB", flush=True)
