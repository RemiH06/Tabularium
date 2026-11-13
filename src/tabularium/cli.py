"""Línea de comandos: `tabularium descargar`, `revisar`, `construir`, `glosar`, `evaluar`, `novellae` y `servir`."""
from __future__ import annotations

import argparse
import json
from datetime import date, timedelta
from pathlib import Path


def main() -> None:
    p = argparse.ArgumentParser(prog="tabularium")
    sub = p.add_subparsers(dest="orden", required=True)
    d = sub.add_parser("descargar", help="revisa el DOF de los últimos días (RF-06) y baja las leyes que cambiaron (RF-01)")
    d.add_argument("--construir", action="store_true", help="regenera la base si bajó algo o hay publicaciones nuevas")
    d.add_argument("--dias", type=int, default=7, help="días hacia atrás que se revisan en el SIDOF (por defecto 7)")
    r = sub.add_parser("revisar", help="detecta en el SIDOF las publicaciones que tocan el corpus (RF-06)")
    r.add_argument("--desde", type=date.fromisoformat, help="AAAA-MM-DD; por defecto, hace 6 días")
    r.add_argument("--hasta", type=date.fromisoformat, help="AAAA-MM-DD; por defecto, hoy")
    nv = sub.add_parser("novellae", help="notas de parche de las publicaciones entre dos fechas (RF-11)")
    nv.add_argument("--db", type=Path)
    nv.add_argument("--desde")
    nv.add_argument("--hasta")
    nv.add_argument("--documento")
    g = sub.add_parser("glosar", help="etiqueta y resumen de cada cambio con el Baker glosador (RF-11); pide Pixilate")
    g.add_argument("--desde", help="AAAA-MM-DD; por defecto, todos los cambios desde el corte")
    g.add_argument("--hasta")
    g.add_argument("--limite", type=int, help="cuántos cambios pedir como máximo")
    g.add_argument("--construir", action="store_true", help="regenera la base si generó alguna glosa")
    c = sub.add_parser("construir", help="regenera la base desde la caché de documentos fuente")
    for s in (d, c, g):
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

    if args.orden == "revisar":
        from . import dof
        hasta = args.hasta or date.today()
        print(json.dumps(dof.revisar(dof.dias(args.desde or hasta - timedelta(6), hasta)), ensure_ascii=False, indent=2))
    elif args.orden == "novellae":
        from contextlib import closing
        from . import almacen
        from .novellae import novellae
        from .servidor import ruta_db
        with closing(almacen.abrir(args.db or ruta_db())) as con:
            print(json.dumps(novellae(con, args.desde, args.hasta, args.documento), ensure_ascii=False, indent=2))
    elif args.orden == "glosar":
        from contextlib import closing
        from . import almacen
        from .almacen import CORTE
        from .glosas import glosar
        from .servidor import ruta_db
        with closing(almacen.abrir(args.db or ruta_db())) as con:
            r = glosar(con, args.desde or CORTE.isoformat(), args.hasta, args.limite)
        print(json.dumps(r, ensure_ascii=False, indent=2))
        if args.construir and r["hechas"]:
            _construir(args.db, not args.sin_vectores)
        if r["error"]:
            raise SystemExit(f"glosar se detuvo: {r['error']}")
    elif args.orden == "descargar":
        from . import dof
        from . import minisitio
        from .descarga import Cliente, actualizar, fijos
        cliente = Cliente()
        hoy = date.today()
        revision = dof.revisar(dof.dias(hoy - timedelta(max(args.dias, 1) - 1), hoy), cliente)
        resultado = actualizar(cliente=cliente)
        resultado["documentos"] = [u for u in resultado["documentos"] if "sidof.segob.gob.mx" not in u]
        resultado["publicaciones"] = revision["publicaciones"]
        # Las páginas del minisitio dicen qué hay; los PDF no cambian una vez publicados: solo se bajan
        # los que faltan, y un PDF nuevo (una compilada, la RMF del año siguiente) pide reconstruir.
        minisitio.refrescar(cliente, hoy)
        antes = len(cliente.bajados)
        resoluciones, anexos = minisitio.fuentes()
        fijos([u for f in resoluciones for u in (f.original, *f.compiladas, *f.publicadas.values()) if u]
              + [u for f in anexos for u in (f.url, *(c for _, c in f.modificaciones))], cliente)
        resultado["documentos"] += cliente.bajados[antes:]
        nuevas = _publicaciones_nuevas(args.db, {p["cod_nota"] for p in revision["publicaciones"]})
        resultado["reconstruir"] = resultado["reconstruir"] or len(cliente.bajados) > antes or bool(nuevas)
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


def _publicaciones_nuevas(db: Path | None, detectadas: set[int]) -> set[int]:
    """Las detectadas que la base aún no registra: hay que reconstruir para que salgan como Novella."""
    import sqlite3
    from .servidor import ruta_db
    ruta = db or ruta_db()
    if not ruta.exists():
        return detectadas
    con = sqlite3.connect(f"file:{ruta.as_posix()}?mode=ro", uri=True)
    try:
        return detectadas - {c for (c,) in con.execute("SELECT cod_nota FROM publicaciones")}
    except sqlite3.OperationalError:  # base de antes de RF-06, sin la tabla
        return detectadas
    finally:
        con.close()


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
