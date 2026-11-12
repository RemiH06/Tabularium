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
    d.add_argument("--db", type=Path)
    c = sub.add_parser("construir", help="regenera la base desde la caché de documentos fuente")
    c.add_argument("--db", type=Path, help="ruta de la base (por defecto TABULARIUM_DB o data/tabularium.db)")
    e = sub.add_parser("evaluar", help="recall@k con las preguntas de docs/preguntas_prueba.md (RNF-06)")
    e.add_argument("--db", type=Path)
    e.add_argument("-k", type=int, default=5)
    e.add_argument("--json", action="store_true", help="salida completa en JSON")
    sub.add_parser("servir", help="levanta el servidor MCP (TABULARIUM_HOST, TABULARIUM_PUERTO)")
    args = p.parse_args()

    if args.orden == "descargar":
        from .descarga import actualizar
        resultado = actualizar()
        print(json.dumps(resultado, ensure_ascii=False, indent=2))
        if args.construir and resultado["reconstruir"]:
            _construir(args.db)
    elif args.orden == "construir":
        _construir(args.db)
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


def _construir(db: Path | None) -> None:
    from .construir import construir
    from .servidor import ruta_db
    destino = db or ruta_db()
    print(json.dumps(construir(destino), ensure_ascii=False, indent=2))
    print(f"base lista en {destino}")


if __name__ == "__main__":
    main()
