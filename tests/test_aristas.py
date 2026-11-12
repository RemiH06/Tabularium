"""Extracción de referencias (RF-07): frases reales del corpus, con lo que debe y no debe salir."""
import pytest

from tabularium.aristas import referencias_de_regla, remisiones

CASOS = [
    ("LISR", "a que se refiere el artículo 27 de esta Ley", {("LISR", "27")}),
    ("LISR", "en los términos del artículo 27, fracción V de esta Ley", {("LISR", "27")}),
    ("LISR", "conforme al artículo 32-D del Código Fiscal de la Federación", {("CFF", "32d")}),
    ("LISR", "lo dispuesto en el artículo 9o. de la Ley del Seguro Social", set()),
    ("RMF2026", "Para los efectos de los artículos 20, séptimo párrafo y 22-B del CFF, así como 27, fracción III de la Ley del ISR", {("CFF", "20"), ("CFF", "22b")}),
    ("RMF2026", "Para los efectos del artículo 12, primer y segundo párrafos del CFF, se estará", {("CFF", "12")}),
    ("RMF2026", "de conformidad con la regla 2.1.6., y las reglas 2.7.1.21. y 3.13.2.", {("RMF2026", "2.1.6"), ("RMF2026", "2.7.1.21"), ("RMF2026", "3.13.2")}),
    ("CFF", "en los artículos 17-H Bis y 69-B de este Código", {("CFF", "17hbis"), ("CFF", "69b")}),
    ("CFF", "dentro de los 15 días siguientes conforme al artículo 22", {("CFF", "22")}),
    ("CFF", "en el artículo 5o. de su Reglamento", set()),
    ("LIVA", "los actos a que se refiere el artículo 1o. de dicha Ley", set()),
    ("LISR", "los contribuyentes del Título II de esta Ley y del artículo 113-E de la misma", {("LISR", "113e")}),
    ("LISR", "en los términos del artículo 44 de esta Ley, considerarán como créditos, además de los señalados en el artículo 45 de la misma, los créditos", {("LISR", "44"), ("LISR", "45")}),
    ("CFF", "Artículo 169.- Sin perjuicio de lo dispuesto por el Artículo 166 de este Código, la asamblea", {("CFF", "169"), ("CFF", "166")}),
    ("RMF2026", "Para los efectos de los artículos 2 y 4 de la Ley del ISR y 6 de su Reglamento, las reaseguradoras", {("LISR", "2"), ("LISR", "4")}),
    ("RMF2026", "Para los efectos del artículo 27, apartados A, fracción III y B, fracción I del CFF, por representante", {("CFF", "27")}),
    ("RMF2026", "Para los efectos del artículo 135, primer párrafo de la Ley del ISR, cuando la autoridad fiscal realice el pago de intereses a que se refiere el artículo 22-A del CFF, a personas", {("LISR", "135"), ("CFF", "22a")}),
    ("RMF2026", "Para los efectos del artículo 3o., fracción IV de la Ley del IEPS, en relación con el artículo 26, fracción VIII del CFF, se entenderá", {("CFF", "26")}),
    ("RMF2025", "Para los efectos del artículo 188-Bis del CFF, la solicitud", {("CFF", "188bis")}),
    ("CFF", "los delitos previstos en los artículos 102 y 105 fracciones I a la IV, todos de este Código", {("CFF", "102"), ("CFF", "105")}),
]


@pytest.mark.parametrize("documento, texto, esperado", CASOS)
def test_remisiones(documento, texto, esperado):
    assert remisiones(texto, documento) == esperado


def test_linea_de_referencias():
    assert referencias_de_regla(["CFF 29, 29-A, RMF 2.6.1.2., 2.7.1.21., Décimo Primero"], 2026) == {
        ("REGLAMENTA", "CFF", "29"), ("REGLAMENTA", "CFF", "29a"),
        ("REMITE_A", "RMF2026", "2.6.1.2"), ("REMITE_A", "RMF2026", "2.7.1.21")}
    # Otras leyes y reglamentos fuera; "LISR 2013" es la ley abrogada; "RMF 2024" es de otro año.
    assert referencias_de_regla(["CFF 12, 13, LA 18, LCF 13, 14"], 2026) == {("REGLAMENTA", "CFF", "12"), ("REGLAMENTA", "CFF", "13")}
    assert referencias_de_regla(["LISR Disposiciones Transitorias para 2014, Noveno, LISR 2013 53, RMF 3.23.1."], 2026) == {
        ("REMITE_A", "RMF2026", "3.23.1")}
    assert ("REMITE_A", "RMF2024", "2.1.39") in referencias_de_regla(["CFF 4o., 17-H Bis, RMF 2024 2.1.39."], 2025)
    assert ("REGLAMENTA", "CFF", "17hbis") in referencias_de_regla(["CFF 4o., 17-H Bis, RMF 2024 2.1.39."], 2025)
