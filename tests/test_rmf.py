"""Segmentación de la RMF con líneas sintéticas (texto, estilo), como las entrega `rmf.texto_pdf`."""
from datetime import date

from tabularium import almacen, lexico, rmf

B, I, N = "b", "i", ""

COMPILADA = [
    ("RESOLUCIÓN MISCELÁNEA FISCAL PARA 2026", B),
    ("Título 2. Código Fiscal de la Federación", B),
    ("Capítulo 2.6. De los controles volumétricos, de los certificados y de los dictámenes de", B),
    ("laboratorio aplicables a hidrocarburos y petrolíferos", B),
    ("Días inhábiles", B),
    ("2.6.1.", B),
    ("Para los efectos del artículo 12 del CFF, se estará a lo siguiente:", N),
    ("CFF 12, 13, LA 18, LCF 13,", I),
    ("14", I),
    ("", N),
    ("Regla 2.6.2.", B),
    ("- Reformada en la Primera RMRMF para 2026, publicada en el DOF el 09 de julio de 2026, dada a conocer", I),
    ("de manera anticipada en el Portal del SAT el 14 de abril de 2026.", I),
    ("Procedimiento para determinar la pérdida del derecho de ejercer la opción relativa a", B),
    ("la emisión de CFDI globales", B),
    ("2.6.2.", B),
    ("Para los efectos de la regla 2.6.1., cuando la autoridad detecte que el contribuyente", N),
    ("no cumple, lo notificará.", N),
    ("CFF 29, RMF 2.6.1.", I),
    ("", N),
    ("Capítulo 2.7. De los CFDI", B),
    ("", N),
    ("Capítulo 2.7.", B),
    ("- Adicionado en la Primera RMRMF para 2026, publicada en el DOF el 09 de julio de 2026.", I),
    ("", N),
    ("Plazo para cancelar", B),
    ("2.7.1.", B),
    ("Se podrá cancelar a más tardar en el mes de la declaración anual.", N),
    ("Transitorios", N),
    ("Primero.", N),
    ("La presente Resolución entrará en vigor el 1o. de enero de 2026 y estará vigente hasta el 31", N),
    ("de diciembre de 2026.", N),
    ("Décimo", N),
    ("Primero. Otro transitorio.", N),
    ("Primera Modificación de la Resolución Miscelánea Fiscal para 2026, publicada en el DOF el 09 de", N),
    ("julio de 2026.", N),
    ("Transitorio", N),
    ("Único.", N),
    ("La presente resolución entrará en vigor a partir del día siguiente al de su publicación en el DOF.", N),
]


def test_segmentar_compilada():
    r = rmf.segmentar(COMPILADA, minimo=1)
    reglas = {x.id: x for x in r.reglas}
    assert list(reglas) == ["2.6.1", "2.6.2", "2.7.1"]
    a, b, c = reglas.values()
    # El nombre largo del capítulo no se pega al epígrafe ni al cuerpo de la regla anterior.
    assert a.titulo == ["Días inhábiles"]
    assert a.jerarquia[-1].endswith("aplicables a hidrocarburos y petrolíferos")
    assert a.referencias == ["CFF 12, 13, LA 18, LCF 13,", "14"]
    assert a.texto.startswith("Días inhábiles 2.6.1. Para los efectos") and a.texto.endswith("LCF 13, 14")
    # Epígrafe de dos renglones; la marca larga sigue en el renglón siguiente y su fecha es la del DOF.
    assert b.titulo == ["Procedimiento para determinar la pérdida del derecho de ejercer la opción relativa a",
                        "la emisión de CFDI globales"]
    assert b.marcas == [("reformad", date(2026, 7, 9))]
    assert b.notas[0].endswith("14 de abril de 2026.")
    # Una regla de un capítulo adicionado hereda la marca del capítulo.
    assert c.marcas == [("adicionad", date(2026, 7, 9))]
    assert [u.id for u in r.transitorios] == ["Transitorio Primero", "Transitorio Décimo Primero"]
    (mod,) = r.modificaciones
    assert mod.publicado == date(2026, 7, 9) and mod.entrada_en_vigor() == (date(2026, 7, 10), False)


def test_referencia_en_un_renglon_con_el_epigrafe():
    """La compilada de 2024 pega las referencias de una regla y el epígrafe de la siguiente en un renglón;
    `texto_pdf` los parte. Aquí se prueba que, ya partidos, el epígrafe queda en su regla."""
    lineas = [("Uno", B), ("1.1.", B), ("Texto.", N), ("CFF 27", I), ("Cédula de identificación", B), ("1.2.", B),
              ("Otro texto.", N), ("Transitorios", N)]
    r = rmf.segmentar(lineas, minimo=1)
    assert [x.titulo for x in r.reglas] == [["Uno"], ["Cédula de identificación"]]
    assert r.reglas[0].referencias == ["CFF 27"]


def test_numero_suelto_no_es_regla():
    """Un "3.13.2." en el texto (referencia cortada por el renglón) no rompe la cadena de reglas."""
    lineas = [("A", B), ("3.13.1.", B), ("Ver la regla", N), ("3.13.9.", B), ("B", B), ("3.13.2.", B), ("x", N),
              ("C", B), ("3.13.3.", B), ("y", N), ("Transitorios", N)]
    assert [x.id for x in rmf.segmentar(lineas, minimo=1).reglas] == ["3.13.1", "3.13.2", "3.13.3"]


def test_clave_y_referencias_de_reglas():
    assert almacen.clave("2.1.6") == almacen.clave("regla 2.1.6.") == "2.1.6"
    assert almacen.clave("2.1.6") != almacen.clave("2.16")
    assert almacen.clave("1o.-A") == "1a"  # los artículos no cambian
    assert almacen.documento_de("RMF", "2025-06-01") == "RMF2025"
    assert almacen.documento_de("rmf 2024", "2026-06-01") == "RMF2024"
    assert lexico.referencias("regla 3.13.2 RMF 2026") == [("RMF", "3.13.2")]
    assert lexico.referencias("regla 2.7.1.21 y art. 29-A del CFF") == [("RMF", "2.7.1.21"), ("CFF", "29-A")]
