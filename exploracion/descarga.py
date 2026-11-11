"""Cliente único de la iteración 0: pausa por host, User-Agent genérico y caché local.

Exploración, no código del producto. Cada respuesta 200 se guarda en
`cache/<host>/<ruta saneada>` y cada petición se anota en `cache/_log.jsonl`.
Si el archivo ya está en la caché no se vuelve a pedir.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from urllib.parse import urlsplit

import httpx

CACHE = Path(__file__).resolve().parent.parent / "cache"
UA = "Mozilla/5.0 (compatible; legal-corpus-fetcher/0.1)"  # genérico: sin nombre ni correo
PAUSA = 2.5  # segundos entre peticiones a un mismo host (RNF-02 pide al menos 2)


def ruta_cache(url: str) -> Path:
    u = urlsplit(url)
    nombre = (u.path.strip("/") or "index") + ("__" + u.query if u.query else "")
    return CACHE / u.netloc.replace(":", "_") / re.sub(r"[^A-Za-z0-9._-]+", "_", nombre)[:160]


def get(url: str, forzar: bool = False, timeout: float = 240) -> dict:
    """Baja `url` (o la toma de la caché) y devuelve sus metadatos. No lanza errores de red."""
    ruta = ruta_cache(url)
    meta = ruta.with_name(ruta.name + ".meta.json")
    if ruta.exists() and meta.exists() and not forzar:
        return json.loads(meta.read_text()) | {"cache": True, "ruta": str(ruta)}
    CACHE.mkdir(exist_ok=True)
    estado_ruta = CACHE / "_ultimo.json"
    estado = json.loads(estado_ruta.read_text()) if estado_ruta.exists() else {}
    host = urlsplit(url).netloc
    time.sleep(max(0.0, PAUSA - (time.time() - estado.get(host, 0))))
    t0 = time.time()
    m = {"url": url, "ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "cache": False, "ruta": str(ruta)}
    try:
        with httpx.Client(headers={"User-Agent": UA}, follow_redirects=True, timeout=timeout) as cliente:
            r = cliente.get(url)
        m |= {"status": r.status_code, "ctype": r.headers.get("content-type", ""), "bytes": len(r.content),
              "last_modified": r.headers.get("last-modified", ""), "seg": round(time.time() - t0, 2)}
        if r.status_code == 200:
            ruta.parent.mkdir(parents=True, exist_ok=True)
            ruta.write_bytes(r.content)
            meta.write_text(json.dumps(m, ensure_ascii=False))
    except httpx.HTTPError as e:  # una fuente caída es un hallazgo, no un fallo del notebook
        m |= {"status": None, "error": f"{type(e).__name__}: {e}"[:300], "seg": round(time.time() - t0, 2)}
    estado[host] = time.time()
    estado_ruta.write_text(json.dumps(estado))
    with (CACHE / "_log.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(m, ensure_ascii=False) + "\n")
    return m
