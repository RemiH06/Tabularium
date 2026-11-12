"""Embeddings con bge-m3 cuantizado a int8 (ONNX), el mismo en la Pi y en cualquier otra máquina.

Elegido en la iteración 2 (plan.md, sección 13): con fragmentos de hasta 6,000 caracteres y fusión
por rango con BM25 da recall@5 de 0.886; en la CPU de la Pi embebe una consulta en 74 ms (p95) y un
fragmento de 2k tokens en 16 s con 1.7 GB de RAM.

Los vectores de los fragmentos se guardan en una caché por hash del texto (`cache/vectores.db`):
reconstruir la base solo embebe lo que cambió.
"""
from __future__ import annotations

import hashlib
import sqlite3
from functools import lru_cache

import numpy as np

REPO = "Xenova/bge-m3"
REVISION = "4de13258303883538bd53b696b452bf8099f0858"  # fijada: otro peso cambiaría los vectores en caché
# Clave del modelo en la caché. Los vectores por lote se calculan en la GPU de Pixilate (bge-m3 en fp16)
# y los nuevos, aquí en int8: coseno de 0.99 entre los dos, y el recall de 0.886 se midió así mezclado.
MODELO = "bge-m3"
MAXIMO_TOKENS = 2048  # 4k tokens toman 54 s y 3.7 GB en la Pi; los fragmentos están hechos para caber en 2k
FRAGMENTO = 6000  # caracteres del cuerpo de cada fragmento (más el contexto): unos 2k tokens
DIMENSION = 1024


def _hash(texto: str) -> str:
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()


class Modelo:
    def __init__(self):
        import onnxruntime as ort
        from huggingface_hub import hf_hub_download
        from tokenizers import Tokenizer

        self.tok = Tokenizer.from_file(hf_hub_download(REPO, "tokenizer.json", revision=REVISION))
        self.tok.enable_truncation(MAXIMO_TOKENS)
        opciones = ort.SessionOptions()
        opciones.intra_op_num_threads = 4
        self.sesion = ort.InferenceSession(hf_hub_download(REPO, "onnx/model_quantized.onnx", revision=REVISION),
                                           opciones, providers=["CPUExecutionProvider"])

    def embeber(self, texto: str) -> np.ndarray:
        """Vector normalizado del token CLS, como bge-m3 en modo denso."""
        ids = np.array([self.tok.encode(texto).ids], dtype=np.int64)
        v = self.sesion.run(None, {"input_ids": ids, "attention_mask": np.ones_like(ids)})[0][0, 0]
        return (v / np.linalg.norm(v)).astype(np.float32)


@lru_cache(maxsize=1)
def modelo() -> Modelo:
    """Se carga una vez por proceso (1.4 s en la Pi)."""
    return Modelo()


class Cache:
    """hash del texto -> vector, en un SQLite aparte que sobrevive a cada reconstrucción de la base."""

    def __init__(self):
        from .construir import cache_dir  # aquí y no arriba: construir importa almacen, que importa este módulo
        cache_dir().mkdir(parents=True, exist_ok=True)
        self.con = sqlite3.connect(cache_dir() / "vectores.db")
        self.con.execute("CREATE TABLE IF NOT EXISTS vectores (modelo TEXT, hash TEXT, vector BLOB NOT NULL, "
                         "PRIMARY KEY (modelo, hash))")
        self.nuevos = 0

    def pendientes(self, textos) -> dict[str, str]:
        """hash -> texto de los que no están en la caché: el lote para la GPU (`lotes/vectorizar_gpu.py`)."""
        hechos = {h for (h,) in self.con.execute("SELECT hash FROM vectores WHERE modelo = ?", (MODELO,))}
        return {h: t for t in textos if (h := _hash(t)) not in hechos}

    def importar(self, hashes: list[str], vectores: np.ndarray) -> int:
        """Guarda los vectores calculados por lote. Valida forma y norma: un archivo equivocado no entra."""
        if vectores.ndim != 2 or len(hashes) != len(vectores) or vectores.shape[1] != DIMENSION:
            raise ValueError(f"esperaba {len(hashes)} vectores de {DIMENSION}; llegó {vectores.shape}")
        if not np.allclose(np.linalg.norm(vectores, axis=1), 1, atol=1e-2):
            raise ValueError("los vectores no vienen normalizados")
        with self.con:
            cur = self.con.executemany("INSERT OR IGNORE INTO vectores VALUES (?, ?, ?)",
                                       [(MODELO, h, v.astype(np.float32).tobytes()) for h, v in zip(hashes, vectores)])
        return cur.rowcount

    def vector(self, texto: str) -> bytes:
        h = _hash(texto)
        fila = self.con.execute("SELECT vector FROM vectores WHERE modelo = ? AND hash = ?", (MODELO, h)).fetchone()
        if fila:
            return fila[0]
        v = modelo().embeber(texto).tobytes()
        with self.con:
            self.con.execute("INSERT INTO vectores VALUES (?, ?, ?)", (MODELO, h, v))
        self.nuevos += 1
        return v

    def close(self) -> None:
        self.con.close()
