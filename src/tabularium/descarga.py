"""Cliente de descarga de las leyes (RF-01).

Baja el índice de LeyesBiblio en cada corrida y, por ley, compara su fecha de última reforma con
la que declara el `.doc` de la caché ("Última reforma publicada DOF dd-mm-aaaa"): solo baja las que
cambiaron. Las copias base de archive.org son fijas, así que se bajan una vez.

Scraping respetuoso (RNF-02): un cliente, pausa por host, User-Agent genérico (sin nombre ni
correo), caché local y una línea por petición en `cache/_log.jsonl`.
"""
from __future__ import annotations

import json
import os
import re
import ssl
import time
import urllib.request
from datetime import date
from pathlib import Path
from urllib.parse import quote, urlsplit

import certifi

from .construir import FUENTES, Fuente, cache_dir, ruta_cache
from .doc import texto_doc

UA = "Mozilla/5.0 (compatible; legal-corpus-fetcher/0.1)"
# El almacén de Windows no valida la cadena del SAT (2026-11-12); el de certifi sí.
TLS = ssl.create_default_context(cafile=certifi.where())
PAUSA = 2.5  # segundos entre peticiones a un mismo host (RNF-02 pide al menos 2)
INDICE = "https://www.diputados.gob.mx/LeyesBiblio/index.htm"
ULTIMA_REFORMA_DOC = re.compile(r"[ÚU]ltima reforma publicada DOF\s+(\d{2})-(\d{2})-(\d{4})")


class Cliente:
    def __init__(self, pausa: float = PAUSA):
        self.pausa = pausa
        self.ultimo: dict[str, float] = {}  # host -> momento de la última petición
        self.bajados: list[str] = []

    def bajar(self, url: str) -> Path:
        """Baja `url` a la caché aunque ya esté. Escribe en un temporal y lo cambia de golpe:
        una descarga cortada nunca deja un documento a medias."""
        host = urlsplit(url).netloc
        time.sleep(max(0.0, self.pausa - (time.time() - self.ultimo.get(host, 0.0))))
        ruta = ruta_cache(url)
        t0 = time.time()
        m = {"url": url, "ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "ruta": str(ruta)}
        try:
            with urllib.request.urlopen(urllib.request.Request(quote(url, safe=":/?&=%~"), headers={"User-Agent": UA}), timeout=240,
                                        context=TLS) as r:
                cuerpo = r.read()
                m |= {"status": r.status, "ctype": r.headers.get("content-type", ""), "bytes": len(cuerpo),
                      "last_modified": r.headers.get("last-modified", "")}
        except OSError as e:  # URLError y HTTPError heredan de OSError
            m |= {"status": getattr(e, "code", None), "error": f"{type(e).__name__}: {e}"[:300]}
            raise
        finally:
            self.ultimo[host] = time.time()
            m["seg"] = round(time.time() - t0, 2)
            cache_dir().mkdir(parents=True, exist_ok=True)
            with (cache_dir() / "_log.jsonl").open("a", encoding="utf-8") as f:
                f.write(json.dumps(m, ensure_ascii=False) + "\n")
        ruta.parent.mkdir(parents=True, exist_ok=True)
        temporal = ruta.with_name(ruta.name + ".bajando")
        temporal.write_bytes(cuerpo)
        os.replace(temporal, ruta)
        ruta.with_name(ruta.name + ".meta.json").write_text(json.dumps(m, ensure_ascii=False))
        self.bajados.append(url)
        return ruta


def codigo(f: Fuente) -> str:
    """Nombre del archivo en LeyesBiblio: `doc/CFF.doc` -> "CFF"."""
    return Path(urlsplit(f.actual_url).path).stem


def ultimas_reformas(indice_html: str, codigos: list[str]) -> dict[str, date]:
    """Fecha de última reforma de cada ley en el índice. La fila va de `ref/<ley>.htm` a
    `doc/<LEY>.doc` y trae dos fechas: publicación y última reforma, en ese orden."""
    salida = {}
    for c in codigos:
        fila = re.search(rf'href="ref/{c.lower()}\.htm"(.*?)href="doc/{c}\.doc"', indice_html, re.S | re.I)
        fechas = re.findall(r"DOF\s+(\d{2})/(\d{2})/(\d{4})", fila.group(1)) if fila else []
        if len(fechas) < 2:
            raise ValueError(f"el índice de LeyesBiblio cambió de forma: no encuentro la fila de {c}")
        d, m, a = fechas[-1]
        salida[c] = date(int(a), int(m), int(d))
    return salida


def ultima_reforma_en(ruta: Path) -> date | None:
    """La que declara el encabezado del `.doc`; None si no está en la caché."""
    if not ruta.exists():
        return None
    m = ULTIMA_REFORMA_DOC.search(texto_doc(ruta)[:5000])
    if m is None:
        raise ValueError(f"{ruta}: el encabezado no dice la fecha de última reforma")
    d, mes, a = m.groups()
    return date(int(a), int(mes), int(d))


def actualizar(fuentes: list[Fuente] = FUENTES, cliente: Cliente | None = None) -> dict:
    cliente = cliente or Cliente()
    for f in fuentes:  # copias fechadas: no cambian
        if f.base_url != f.actual_url and not ruta_cache(f.base_url).exists():
            cliente.bajar(f.base_url)
    indice = cliente.bajar(INDICE).read_bytes().decode("iso-8859-1")
    en_indice = ultimas_reformas(indice, [codigo(f) for f in fuentes])
    leyes = {}
    for f in fuentes:
        c = codigo(f)
        ruta = ruta_cache(f.actual_url)
        antes = ultima_reforma_en(ruta)
        estado = {"indice": en_indice[c].isoformat(), "cache": antes.isoformat() if antes else None, "bajada": False}
        if antes != en_indice[c]:
            cliente.bajar(f.actual_url)
            ahora = ultima_reforma_en(ruta)
            estado |= {"bajada": True, "cache": ahora.isoformat()}
            if ahora != en_indice[c]:  # el índice puede ir adelantado al documento
                estado["aviso"] = "el documento bajado no coincide con el índice; se vuelve a intentar en la siguiente corrida"
        leyes[c] = estado
    return {"leyes": leyes, "documentos": [u for u in cliente.bajados if u != INDICE], "reconstruir": any(e["bajada"] for e in leyes.values())}


def fijos(urls: list[str], cliente: Cliente | None = None) -> list[str]:
    """Baja los documentos que no cambian una vez publicados (RMF y compiladas) si faltan en la caché."""
    cliente = cliente or Cliente()
    for u in urls:
        if not ruta_cache(u).exists():
            cliente.bajar(u)
    return cliente.bajados
