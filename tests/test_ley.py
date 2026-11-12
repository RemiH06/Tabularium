from datetime import date

from tabularium.ley import Decreto, Unidad, fecha_es, ordinal, segmentar

LEY = """LEY DE PRUEBA
Nueva Ley publicada en el Diario Oficial de la Federación el 29 de diciembre de 1978
TEXTO VIGENTE
CAPITULO I
Disposiciones generales
Artículo 1o.- Están obligadas al pago del impuesto
las personas físicas.
Párrafo reformado DOF 30-12-1980, 31-12-1998
Artículo 1o.-A.- Están obligados a retener.
Artículo 2o.- Texto nuevo.
Artículo reformado DOF 01-04-2024
CAPITULO II
De la enajenación
Artículo 17-H Bis.- Con sufijo.
TRANSITORIOS
Artículo Primero.- Esta Ley entrará en vigor el día primero de enero de 1980.
Artículo Segundo.- Se abrogan las leyes anteriores.
México, D. F., a 22 de diciembre de 1978.- Firmas.
ARTÍCULOS TRANSITORIOS DE DECRETOS DE REFORMA

DECRETO por el que se reforma la Ley de prueba.
Publicado en el Diario Oficial de la Federación el 1 de abril de 2024
Artículo Único.- Se reforma el artículo 2o. de la Ley de prueba.
..........
Transitorio
Único.- El presente Decreto entrará en vigor el día siguiente al de su publicación en el Diario Oficial de la Federación.
Ciudad de México, a 13 de febrero de 2024.- Firmas.
"""


def test_segmenta_cuerpo_jerarquia_y_notas():
    ley = segmentar(LEY)
    assert ley.expedicion == date(1978, 12, 29)
    assert [u.id for u in ley.articulos] == ["1o", "1o.-A", "2o", "17-H Bis"]
    art1 = ley.articulos[0]
    assert art1.texto == "Artículo 1o.- Están obligadas al pago del impuesto las personas físicas."
    assert art1.notas == ["Párrafo reformado DOF 30-12-1980, 31-12-1998"]
    assert art1.reformas() == {date(1980, 12, 30), date(1998, 12, 31)}
    assert art1.jerarquia == ("CAPITULO I: Disposiciones generales",)
    assert ley.articulos[3].jerarquia == ("CAPITULO II: De la enajenación",)


def test_transitorios_de_la_ley_y_del_decreto_por_separado():
    ley = segmentar(LEY)
    assert [u.id for u in ley.transitorios] == ["Transitorio Primero", "Transitorio Segundo"]
    assert "Firmas" not in ley.transitorios[-1].texto
    (decreto,) = ley.decretos
    assert decreto.titulo == "DECRETO por el que se reforma la Ley de prueba."
    assert decreto.publicado == date(2024, 4, 1)
    # El extracto del decreto ("Artículo Único.- Se reforma...") no es transitorio.
    assert [u.id for u in decreto.transitorios] == ["Transitorio Único"]
    assert decreto.entrada_en_vigor() == (date(2024, 4, 2), False)


def _decreto(*textos: str) -> Decreto:
    return Decreto("D", date(2025, 11, 7), [Unidad(f"Transitorio {i}", "transitorio", [t]) for i, t in enumerate(textos)])


def test_entrada_en_vigor():
    assert _decreto("Único. El presente Decreto entrará en vigor el 1o. de enero de 2026.").entrada_en_vigor() == (
        date(2026, 1, 1), False)
    con_salvedad = _decreto("Primero. Entrará en vigor el 1 de enero de 2026, salvo el artículo 30-B.")
    assert con_salvedad.entrada_en_vigor() == (date(2026, 1, 1), True)
    dos = _decreto("Primero. Entrará en vigor el 1 de enero de 2026.", "Segundo. El 30-B entrará en vigor el 1 de abril de 2026.")
    assert dos.entrada_en_vigor() == (date(2026, 1, 1), True)
    assert _decreto("Único. Sin fecha reconocible.").entrada_en_vigor() == (None, False)


def test_fechas_y_ordinales():
    assert fecha_es("el día 1o. de enero del año 2000") == date(2000, 1, 1)
    assert fecha_es("el día primero de enero de 1980") == date(1980, 1, 1)
    assert fecha_es("sin fecha") is None
    assert ordinal("DECIMO PRIMERO") == "Décimo Primero"
    assert ordinal("UNICO") == "Único"
