"""RF-06: detección en el SIDOF de las publicaciones que tocan el corpus."""
import json
from datetime import date

import pytest

from tabularium import dof

TITULOS = [  # títulos reales del SIDOF (y tres hipotéticos al final) con lo que deben tocar
    ("Decreto por el que se reforman, adicionan y derogan diversas disposiciones del Código Fiscal de la Federación.", ("CFF",)),
    ("Decreto por el que se reforman y adicionan diversas disposiciones a la Ley de Amparo, Reglamentaria de los "
     "artículos 103 y 107 de la Constitución Política de los Estados Unidos Mexicanos, al Código Fiscal de la "
     "Federación y a la Ley Orgánica del Tribunal Federal de Justicia Administrativa.", ("CFF",)),
    ("Resolución Miscelánea Fiscal para 2024 y sus anexos 1, 5, 8, 15, 19 y 27.", ("RMF2024", "RMF2024-A8")),
    ("Anexos 4, 5, 6, 8, 15 y 25 de la Resolución Miscelánea Fiscal para 2026.", ("RMF2026-A8",)),
    ("Anexos 23, 24, 25, 25-Bis, 28, 29, 30, 31 y 32 de la Resolución Miscelánea Fiscal para 2024, publicada el "
     "29 de diciembre de 2023.", ("RMF2024-A29",)),
    ("Tercera Resolución de Modificaciones a la Resolución Miscelánea Fiscal para 2024 y anexos 1, 1-A, 14, 15 y 29.",
     ("RMF2024", "RMF2024-A29")),
    ("Anexo 1 de la Resolución Miscelánea Fiscal para 2026.", ()),
    ("Reglas Generales de Comercio Exterior para 2025 y su Anexo 13.", ()),
    ("Acuerdo por el que se dan a conocer los montos de los estímulos fiscales aplicables a la enajenación de "
     "gasolinas en la región fronteriza con Guatemala, correspondientes al periodo que se especifica.", ()),
    ("Decreto por el que se reforman diversos ordenamientos en materia de pueblos y comunidades indígenas y "
     "afromexicanas.", ()),  # sin el texto de la nota no se sabe; ver test_omnibus
    ("Primera Modificación al Anexo 29 de la Resolución Miscelánea Fiscal para 2026.", ("RMF2026-A29",)),
    ("Decreto por el que se otorgan estímulos fiscales en materia del impuesto sobre la renta.", ()),
    ("ACLARACIÓN a la Resolución Miscelánea Fiscal para 2026.", ("RMF2026",)),
]


@pytest.mark.parametrize("titulo, esperado", TITULOS)
def test_toca(titulo, esperado):
    assert dof.toca(titulo) == esperado


def test_omnibus():
    titulo = "Decreto por el que se reforman diversos ordenamientos en materia de pueblos indígenas."
    cuerpo = ("<p>ARTÍCULO PRIMERO.- Se reforma el artículo 2 de la Ley General de Educación.</p>"
              "<p>ARTÍCULO DÉCIMO.- Se reforma el artículo 79, fracción VI de la Ley del Impuesto sobre la Renta.</p>"
              "<p>Transitorio. Para efectos del Código Fiscal de la Federación ...</p>")
    assert dof.omnibus(titulo)
    # El CFF solo se menciona lejos de un "se reforma": no cuenta.
    assert dof.toca(titulo, cuerpo.replace("Transitorio.", "Transitorio. " + "x" * 1600)) == ("LISR",)


def _dia(**ediciones):
    return json.dumps({"messageCode": 200, "response": "OK", "NotasMatutinas": [], "NotasVespertinas": [],
                       "NotasExtraordinarias": [], **ediciones}).encode()


def test_leer_dia():
    notas = [{"codNota": 1, "titulo": None}, {"codNota": 2, "titulo": "Resolución Miscelánea Fiscal para 2027."},
             {"codNota": 3, "titulo": "Decreto por el que se reforman diversas leyes en materia de salud."}]
    leidas = []
    pubs = dof.leer_dia(_dia(NotasVespertinas=notas), date(2026, 12, 28),
                        lambda cod: leidas.append(cod) or "Se adiciona un párrafo a la Ley del Impuesto al Valor Agregado")
    assert [(p.cod_nota, p.edicion, p.documentos) for p in pubs] == [(2, "vespertina", ("RMF2027",)), (3, "vespertina", ("LIVA",))]
    assert leidas == [3]  # solo el decreto de diversas leyes pide el texto de la nota
    assert pubs[0].url == "https://dof.gob.mx/nota_detalle.php?codigo=2&fecha=28/12/2026"


def test_respuesta_rara_falla_en_voz_alta():
    with pytest.raises(ValueError, match="respuesta inesperada"):
        dof.leer_dia(b'{"messageCode": 500, "response": "ERROR"}', date(2026, 1, 1))


@pytest.mark.parametrize("dia, esperado", [
    (date(2025, 11, 7), [(5772358, ("CFF",))]),  # paquete económico 2026: el criterio de RF-06
    (date(2025, 11, 5), []),  # sin reformas al corpus: sin falsos positivos
    (date(2025, 11, 8), []),  # sábado
    (date(2024, 4, 1), [(5721949, ("LISR",))]),  # de diversos ordenamientos: lee la nota
    (date(2025, 12, 28), [(5777217, ("RMF2026",)), (5777219, ("RMF2026-A8",))]),
])
def test_rf06_dias_reales(dia, esperado):
    ruta = dof._ruta(dia)
    if not ruta.exists():
        pytest.skip("sin ese día del SIDOF en la caché")
    try:
        pubs = dof.leer_dia(ruta.read_bytes(), dia, dof._nota)
    except FileNotFoundError:
        pytest.skip("sin la nota en la caché")
    assert [(p.cod_nota, p.documentos) for p in pubs] == esperado
