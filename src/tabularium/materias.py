"""Materia de cada unidad, para los sellos y el filtro de la página.

Sale de la estructura del corpus, sin modelo: la ley es su materia; en la RMF, el título de la regla
(su primer número) dice la materia; los anexos 8 (tarifas) son del ISR y los 20 y 29, de CFDI.
Hoy todo el corpus es del área fiscal; cuando entren otras áreas (laboral, datos personales), el área
va como nivel de arriba de la materia.
"""
from __future__ import annotations

import re

MATERIAS = {  # sigla: nombre, en el orden en que se muestran
    "ISR": "Impuesto sobre la renta",
    "IVA": "Impuesto al valor agregado",
    "IEPS": "Impuesto especial sobre producción y servicios",
    "CFF": "Código Fiscal de la Federación",
    "CFDI": "Comprobantes fiscales digitales",
    "ISAN": "Impuesto sobre automóviles nuevos",
    "LIF": "Ley de Ingresos de la Federación",
    "LISH": "Ley de Ingresos sobre Hidrocarburos",
    "DER": "Derechos y contribuciones de mejoras",
    "DIG": "Servicios digitales",
    "DEC": "Decretos, circulares y convenios",
    "GEN": "Disposiciones generales de la RMF",
}
POR_LEY = {"LISR": "ISR", "LIVA": "IVA", "CFF": "CFF"}
# Títulos de la RMF (iguales de 2024 a 2026).
POR_TITULO = {1: "GEN", 2: "CFF", 3: "ISR", 4: "IVA", 5: "IEPS", 6: "DER", 7: "DER", 8: "ISAN", 9: "LIF",
              10: "LISH", 11: "DEC", 12: "DIG"}


def materia(documento: str, clave: str | None = None) -> str | None:
    """Sigla de la materia, o None si no se puede decir (una RMF sin regla: una publicación pendiente)."""
    if documento in POR_LEY:
        return POR_LEY[documento]
    if re.fullmatch(r"RMF\d{4}-A8", documento):
        return "ISR"
    if re.fullmatch(r"(RMF\d{4}-A(20|29)|GUIA-A20)", documento):
        return "CFDI"
    if re.fullmatch(r"RMF\d{4}", documento) and clave and (m := re.match(r"(\d+)\.", clave)):
        return POR_TITULO.get(int(m.group(1)))
    return None
