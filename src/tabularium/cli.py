"""Línea de comandos: `tabularium construir` y `tabularium servir`."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> None:
    p = argparse.ArgumentParser(prog="tabularium")
    sub = p.add_subparsers(dest="orden", required=True)
    c = sub.add_parser("construir", help="regenera la base desde la caché de documentos fuente")
    c.add_argument("--db", type=Path, help="ruta de la base (por defecto TABULARIUM_DB o data/tabularium.db)")
    sub.add_parser("servir", help="levanta el servidor MCP (TABULARIUM_HOST, TABULARIUM_PUERTO)")
    args = p.parse_args()

    if args.orden == "construir":
        from .construir import construir
        from .servidor import ruta_db
        destino = args.db or ruta_db()
        print(json.dumps(construir(destino), ensure_ascii=False, indent=2))
        print(f"base lista en {destino}")
    else:
        from .servidor import servir
        servir()


if __name__ == "__main__":
    main()
