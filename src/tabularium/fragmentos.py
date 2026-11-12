"""Fragmentos de una versión para embeberla: párrafos agrupados hasta un largo máximo, cada uno con
su contexto (ley, jerarquía y unidad) al frente, porque un párrafo suelto no dice de qué ley es."""
from __future__ import annotations

import re


def contexto(nombre_documento: str, jerarquia: str, unidad: str, tipo: str) -> str:
    etiqueta = {"articulo": f"Artículo {unidad}", "regla": f"Regla {unidad}"}.get(tipo, unidad)
    return " > ".join(p for p in (nombre_documento, jerarquia, etiqueta) if p) + "\n"


def partir(texto: str, maximo: int) -> list[str]:
    """Agrupa párrafos sin pasar de `maximo` caracteres. Un párrafo más largo se corta por oraciones
    y, si una oración sola no cabe, por caracteres."""
    piezas: list[str] = []
    for parrafo in texto.split("\n"):
        if len(parrafo) <= maximo:
            piezas.append(parrafo)
            continue
        for oracion in re.split(r"(?<=[.;:])\s+", parrafo):
            piezas += [oracion[i:i + maximo] for i in range(0, len(oracion), maximo)]
    grupos, actual = [], ""
    for p in piezas:
        if actual and len(actual) + 1 + len(p) > maximo:
            grupos.append(actual)
            actual = p
        else:
            actual = f"{actual}\n{p}" if actual else p
    return grupos + ([actual] if actual else [])
