"""Línea de comandos: `tabularium descargar`, `construir`, `evaluar` y `servir`."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> None:
    p = argparse.ArgumentParser(prog="tabularium")
    sub = p.add_subparsers(dest="orden", required=True)
    d = sub.add_parser("descargar", help="baja las leyes que cambiaron en LeyesBiblio (RF-01)")
    d.add_argument("--construir", action="store_true", help="regenera la base si bajó algo")
    c = sub.add_parser("construir", help="regenera la base desde la caché de documentos fuente")
    for s in (d, c):
        s.add_argument("--db", type=Path, help="ruta de la base (por defecto TABULARIUM_DB o data/tabularium.db)")
        s.add_argument("--sin-vectores", action="store_true", help="solo BM25: no baja el modelo ni embebe")
    e = sub.add_parser("evaluar", help="recall@k con las preguntas de docs/preguntas_prueba.md (RNF-06)")
    e.add_argument("--db", type=Path)
    e.add_argument("-k", type=int, default=5)
    e.add_argument("--json", action="store_true", help="salida completa en JSON")
    sub.add_parser("servir", help="levanta el servidor MCP (TABULARIUM_HOST, TABULARIUM_PUERTO)")
    pe = sub.add_parser("pendientes", help="exporta los fragmentos sin vector en la caché, para la GPU")
    pe.add_argument("--db", type=Path)
    pe.add_argument("salida", type=Path, help="archivo .jsonl ({hash, texto} por línea)")
    im = sub.add_parser("importar", help="guarda en la caché los vectores calculados por lote")
    im.add_argument("vectores", type=Path, help=".npz de lotes/vectorizar_gpu.py (hashes y vectores)")
    args = p.parse_args()

    if args.orden in ("pendientes", "importar"):
        from contextlib import closing
        from .vectores import Cache
        with closing(Cache()) as cache:
            if args.orden == "pendientes":
                from . import almacen
                from .servidor import ruta_db
                with closing(almacen.abrir(args.db or ruta_db())) as con:
                    lote = cache.pendientes(t for _, t in almacen.fragmentos(con))
                with args.salida.open("w", encoding="utf-8") as f:
                    f.writelines(json.dumps({"hash": h, "texto": t}, ensure_ascii=False) + "\n" for h, t in lote.items())
                print(f"{len(lote)} fragmentos sin vector en {args.salida}")
            else:
                import numpy as np
                with np.load(args.vectores) as z:
                    print(f"{cache.importar(list(z['hashes']), z['vectores'])} vectores nuevos en la caché")
        return

    if args.orden == "descargar":
        from .descarga import Cliente, actualizar, fijos
        from .rmf import FUENTES_RMF
        cliente = Cliente()
        resultado = actualizar(cliente=cliente)
        # Los PDF de la RMF no cambian una vez publicados: solo se bajan los que faltan.
        antes = len(cliente.bajados)
        fijos([u for f in FUENTES_RMF for u in (f.original, *f.compiladas, *f.publicadas.values()) if u], cliente)
        resultado["documentos"] += cliente.bajados[antes:]
        resultado["reconstruir"] = resultado["reconstruir"] or len(cliente.bajados) > antes
        print(json.dumps(resultado, ensure_ascii=False, indent=2))
        if args.construir and resultado["reconstruir"]:
            _construir(args.db, not args.sin_vectores)
    elif args.orden == "construir":
        _construir(args.db, not args.sin_vectores)
    elif args.orden == "evaluar":
        from contextlib import closing
        from . import almacen
        from .evaluacion import evaluar, reporte
        from .servidor import ruta_db
        with closing(almacen.abrir(args.db or ruta_db())) as con:
            r = evaluar(con, k=args.k)
        print(json.dumps(r, ensure_ascii=False, indent=2) if args.json else reporte(r))
    else:
        from .servidor import servir
        servir()


def _construir(db: Path | None, con_vectores: bool) -> None:
    from .construir import construir
    from .servidor import ruta_db
    from .vectores import Cache
    destino = db or ruta_db()
    cache = Cache() if con_vectores else None
    try:
        print(json.dumps(construir(destino, vectores=cache), ensure_ascii=False, indent=2))
    finally:
        if cache:
            cache.close()
    print(f"base lista en {destino}" + (f"; {cache.nuevos} fragmentos embebidos" if cache else ", sin vectores"))


if __name__ == "__main__":
    main()
