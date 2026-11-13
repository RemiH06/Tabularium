"""Anexos 8 y 29 de la RMF con líneas sintéticas, como las entrega `anexos.lineas_pdf`."""
from datetime import date

import pytest

from tabularium import almacen, anexos
from tabularium.aristas import remisiones

ANEXO_8 = [
    "ANEXO 8 DE LA RESOLUCIÓN MISCELÁNEA FISCAL PARA 2026",
    "Contenido", "A.", "Tarifa aplicable a pagos provisionales", "I.", "Tarifa del índice, que no es tabla.",
    "C.", "Tarifa para el cálculo del impuesto correspondiente a los ejercicios 2025 y 2026",
    "A. Tarifa aplicable a pagos provisionales",
    "I.",
    "Tarifa para el cálculo de los pagos provisionales que se deban efectuar durante 2026, tratándose de la",
    "enajenación de inmuebles a que se refiere el artículo 126 de la Ley del ISR.",
    "Límite inferior", "Límite superior", "Cuota fija", "Por ciento para aplicarse", "sobre el excedente del límite", "inferior",
    "$", "$", "$", "%",
    "0.01", "10,135.11", "0", "1.92",
    "10,135.12", "En adelante", "194.59", "6.40",
    "VII.  Tarifa para el cálculo de pagos bimestrales definitivos de 2026, por parte de los contribuyentes",
    "del RIF.",
    "Límite inferior", "Límite superior", "Cuota fija", "Por ciento", "$", "$", "$", "%",
    "0.01", "1,689.18", "0.00", "1.92",
    "1,689.19", "En adelante", "32.44", "6.40",
    "Tabla del subsidio para el empleo aplicable a la tarifa de la fracción VII.",
    "Para Ingresos de", "Hasta Ingresos de", "Cantidad de subsidio", "$", "$", "$",
    "0.01", "58.19", "13.39",
    "58.20", "En adelante", "0.00",
    "C.",
    "Tarifa para el cálculo del impuesto correspondiente a los ejercicios 2025 y 2026",
    "II.",
    "Tarifa para el cálculo del impuesto correspondiente al ejercicio de 2026 a que se refieren los artículos 97",
    "y 152 de la Ley del ISR, así como la regla 3.17.1.",
    "Límite inferior", "Límite superior", "Cuota fija", "Por ciento", "$", "$", "$", "%",
    "0.01", "10,135.11", "0", "1.92",
    "10,135.12", "En adelante", "194.59", "6.40",
    "Atentamente.",
]


def test_tarifas():
    s = {x.id: x for x in anexos.tarifas(ANEXO_8)}
    # El índice no cuenta; con dos tablas en la fracción VII cada una lleva su número; "C." solo toma
    # su nombre del renglón siguiente; "VII.  Tarifa..." en un renglón.
    assert list(s) == ["A.I", "A.VII.1", "A.VII.2", "C.II"]
    assert s["C.II"].jerarquia == ("C. Tarifa para el cálculo del impuesto correspondiente a los ejercicios 2025 y 2026",
                                   "Fracción II")
    assert s["C.II"].lineas[0].endswith("artículos 97 y 152 de la Ley del ISR, así como la regla 3.17.1.")
    assert s["C.II"].lineas[2:] == ["0.01 | 10,135.11 | 0 | 1.92", "10,135.12 | En adelante | 194.59 | 6.40"]
    assert s["A.VII.2"].lineas[2:] == ["0.01 | 58.19 | 13.39", "58.20 | En adelante | 0.00"]


@pytest.mark.parametrize("cambio, error", [
    (("10,135.12", "10,135.13"), "no encadenan"),  # falta un centavo entre renglones: celda mal leída
    (("194.59", None), "celdas para 4 columnas"),  # una celda perdida
])
def test_tarifa_que_no_cuadra(cambio, error):
    viejo, nuevo = cambio
    i = ANEXO_8.index(viejo)
    lineas = ANEXO_8[:i] + ([nuevo] if nuevo else []) + ANEXO_8[i + 1:]
    with pytest.raises(ValueError, match=error):
        anexos.tarifas(lineas)


ANEXO_29 = [
    "Contenido", "I.", "Carta compromiso.", "II.", "Características de la aplicación gratuita.",
    "I. Carta compromiso de confidencialidad.",
    "Formato de carta para los PCCFDI, con fundamento en la fracción",
    "I del CFF y la regla 2.7.2.1.",
    "II.", "Características funcionales de la aplicación gratuita.",
    "II.1",
    "Requerimientos funcionales mínimos:",
    "Párrafo",
    "- Modificado por la Primera Modificación al Anexo 29 de la Resolución Miscelánea Fiscal para 2026, publicada en el DOF el",
    "17 de julio de 2026.",
    "Deberá aceptar la carga del CSD del contribuyente.",
    "II.2 Servicios generales mínimos.",
    "Ver la fracción IV. de la regla 2.7.2.8.",
    "Atentamente.",
    "Ciudad de México, a 3 de julio de 2026.",
]


def test_apartados():
    secciones, marcas = anexos.apartados(ANEXO_29)
    s = {x.id: x for x in secciones}
    # "I del CFF" y "IV." dentro del texto no abren sección; la fracción II, que solo trae su nombre
    # antes del primer apartado, no es sección propia.
    assert list(s) == ["I", "II.1", "II.2"]
    assert s["II.1"].jerarquia == ("II. Características funcionales de la aplicación gratuita.",)
    # La marca y su cabeza ("Párrafo") salen del texto y quedan como fecha de la sección.
    assert s["II.1"].lineas == ["II.1", "Requerimientos funcionales mínimos:", "Deberá aceptar la carga del CSD del contribuyente."]
    assert marcas == {"I": set(), "II.1": {date(2026, 7, 17)}, "II.2": set()}


def test_vigor():
    assert anexos.vigor(2026, date(2025, 12, 28)) == date(2026, 1, 1)  # sale antes: rige con la RMF
    assert anexos.vigor(2026, date(2026, 1, 9)) == date(2026, 1, 10)  # sale después: el día siguiente


def test_documento_de_un_anexo():
    assert [almacen.documento_de(d, "2026-03-01") for d in ("Anexo 8", "a29", "RMF-A8", "RMF2024-A8", "RMF")] == \
        ["RMF2026-A8", "RMF2026-A29", "RMF2026-A8", "RMF2024-A8", "RMF2026"]


def test_remisiones_de_un_anexo():
    """Las reglas que nombra un anexo son de la RMF de su año."""
    assert remisiones("a que se refieren los artículos 97 y 152 de la Ley del ISR, así como la regla 3.17.1.",
                      "RMF2026-A8") == {("LISR", "97"), ("LISR", "152"), ("RMF2026", "3.17.1")}


GUIA = [
    "1 / 9", "Contenido", "Introducción .... 3", "Glosario .... 5",
    "Introducción", "Los CFDI deben emitirse por los actos que se realicen.",
    "I. Guía de llenado del Comprobante Fiscal Digital por Internet (CFDI)",
    "Nodo:", "Comprobante", "Formato estándar del CFDI.", "FormaPago", "Se debe registrar la clave de la forma de pago.",
    "2 / 9",
    "Nodo:", "InformacionGlo", "bal", "En este nodo se puede expresar la información global.",
    "Nodo:", "Complemento", "Concepto", "En este nodo se puede expresar información adicional.",
    "Nodo:", "Impuestos", "Resumen de los impuestos.",
    "Nodo: Impuestos", "Los del comprobante.",
    "II. Guía de llenado del Comprobante Fiscal Digital por Internet que ampara",
    "Nodo:Emisor", "Datos del emisor de la retención.",
    "Glosario", "CFDI: Comprobante fiscal digital por Internet.",
    "Apéndice 1 Notas Generales", "Notas.",
    "Apéndice 3 Clasificación citada antes de tiempo: no abre sección.",
    "Apéndice 2 Clasificación de los tipos de CFDI", "Ingreso, egreso, traslado.",
    "Control de cambios de la Guía de llenado", "16 de enero 2026",
]


def test_guia():
    s = {x.id: x for x in anexos.guia(GUIA, {"Comprobante", "InformacionGlobal", "ComplementoConcepto", "Impuestos"})}
    # Nombres partidos en dos renglones se pegan si forman un nodo del estándar; un nodo repetido
    # (por concepto y por comprobante) lleva su número; los apéndices solo abren en orden. Una parte sin
    # texto antes de su primer nodo ("I", "II") no es sección propia.
    assert list(s) == ["Introducción", "I Comprobante", "I InformacionGlobal", "I ComplementoConcepto",
                       "I Impuestos", "I Impuestos (2)", "II Emisor", "Glosario", "Apéndice 1", "Apéndice 2",
                       "Control de cambios"]
    assert "2 / 9" not in s["I Comprobante"].lineas  # números de página fuera
    assert "Apéndice 3 Clasificación citada antes de tiempo: no abre sección." in s["Apéndice 1"].lineas
