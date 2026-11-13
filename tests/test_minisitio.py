"""Fuentes de la RMF y sus anexos desde las páginas del minisitio del SAT."""
from datetime import date
from urllib.error import HTTPError

import pytest

from tabularium import construir, minisitio
from tabularium.rmf import SAT


def li(url: str, texto: str, fecha: str) -> str:
    return f'<li class="contenido"><a href="{url}" target="_blank"><strong> {texto} </strong></a> (publicada el {fecha})</li>\n'


def pagina(tmp_path, monkeypatch, anio: int, html: str) -> None:
    monkeypatch.setenv("TABULARIUM_CACHE", str(tmp_path))
    ruta = construir.ruta_cache(minisitio.pagina(anio))
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(html, encoding="utf-8")


def test_anio_nuevo_y_modificacion_sin_compilada(tmp_path, monkeypatch):
    """La RMF de un año entra en cuanto la página la lista. Una modificación publicada sin compilada
    no entra (su Novella queda pendiente); la compilada de otro anexo mal etiquetada se ignora."""
    d = "documentos2027/rmf/"
    pagina(tmp_path, monkeypatch, 2027, "".join([
        li(d + "rmf/RMF_2027-DOF-28122026.pdf", "Resolución Miscelánea Fiscal para 2027", "28 de diciembre de 2026"),
        li(d + "rmf/1aRM_RMF2027.pdf", "1a Resolución de Modificaciones a la RMF para 2027", "09 de julio de 2027"),
        li(d + "rmf/2aRM_RMF2027.pdf", "2a Resolución de Modificaciones a la RMF para 2027", "01 de octubre de 2027"),
        li(d + "compiladas/Compilado_1a_RMF2027.pdf", "Compilado 1a. RM RMF 2027", "09 de julio de 2027"),
        li(d + "anexos/Anexo-8-RMF-2027.pdf", "Anexo 8 de la RMF 2027", "28 de diciembre de 2026"),
        li(d + "anexos/Anexo_29_RMF2027.pdf", "Anexo 29 de la RMF 2027", "08 de enero de 2027"),
        li(d + "compiladas/Compilado_1a_Anexo_30_RMF2027.pdf", "Compilado 1a. Modificación Anexo 29 RMF 2027", "17 de julio de 2027"),
        li(d + "compiladas/Compilado_2a_Anexo_29_RMF2027.pdf", "Compilado 2a. Modificación Anexo 29 RMF 2027", "17 de octubre de 2027"),
    ]))
    [r], anexos = minisitio.fuentes([2027])
    assert (r.anio, r.publicado, r.original) == (2027, date(2026, 12, 28), SAT + d + "rmf/RMF_2027-DOF-28122026.pdf")
    assert r.compiladas == (SAT + d + "compiladas/Compilado_1a_RMF2027.pdf",) and r.publicadas == {}
    assert [(a.numero, a.publicado) for a in anexos] == [(8, date(2026, 12, 28)), (29, date(2027, 1, 8))]
    assert anexos[1].modificaciones == ()  # la 1a es del 30 y la 2a no puede ir sin la 1a


def test_dos_enlaces_para_lo_mismo_fallan(tmp_path, monkeypatch):
    d = "documentos2027/rmf/"
    pagina(tmp_path, monkeypatch, 2027, li(d + "anexos/Anexo_29_a.pdf", "Anexo 29 de la RMF 2027", "08 de enero de 2027")
           + li(d + "anexos/Anexo_29_b.pdf", "Anexo 29 de la RMF 2027", "08 de enero de 2027"))
    with pytest.raises(ValueError, match="dos enlaces"):
        minisitio.fuentes([2027])


def test_sin_paginas_no_hay_fuentes(tmp_path, monkeypatch):
    monkeypatch.setenv("TABULARIUM_CACHE", str(tmp_path))
    assert minisitio.fuentes() == ([], [])


class Cliente:
    def __init__(self, faltan=()):
        self.faltan, self.pedidas = set(faltan), []

    def bajar(self, url):
        self.pedidas.append(url)
        if url in self.faltan:
            raise HTTPError(url, 404, "Not Found", {}, None)


def test_refrescar(tmp_path, monkeypatch):
    """En diciembre también se pide la página del año siguiente, que puede no existir aún; las de
    años viejos solo si faltan. Un 404 del año en curso no es normal: falla."""
    pagina(tmp_path, monkeypatch, 2024, "")
    c = Cliente(faltan={minisitio.pagina(2027)})
    assert minisitio.refrescar(c, date(2026, 12, 15)) == [2025, 2026]
    assert c.pedidas == [minisitio.pagina(a) for a in (2025, 2026, 2027)]
    assert minisitio.refrescar(Cliente(), date(2026, 11, 12)) == [2025, 2026]
    with pytest.raises(HTTPError):
        minisitio.refrescar(Cliente(faltan={minisitio.pagina(2026)}), date(2026, 11, 12))


REALES = [a for a in (2024, 2025, 2026) if construir.ruta_cache(minisitio.pagina(a)).exists()]


@pytest.mark.skipif(len(REALES) < 3, reason="sin las páginas del minisitio en la caché")
def test_paginas_reales():
    """Lo que antes era lista fija: excepciones aplicadas y la compilada del Anexo 30 de 2024 fuera."""
    rmf, anexos = minisitio.fuentes(REALES)
    r24, r25, r26 = rmf
    assert r24.compiladas[1] is None and len(r24.compiladas) == 3 and set(r24.publicadas) == {1}
    assert len(r25.compiladas) == 6 and None not in r25.compiladas and r25.publicadas == {}
    assert len(r26.compiladas) >= 3 and r26.publicadas == {1: SAT + "documentos2026/rmf/rmf/2aRM_RMF2026_01102026.pdf"}
    a29 = {a.anio: a for a in anexos if a.numero == 29}
    assert [p for p, _ in a29[2024].modificaciones] == [date(2024, 6, 4), date(2024, 12, 12)]
    assert all("Anexo_29" in u for _, u in a29[2024].modificaciones)
    assert sorted((a.numero, a.anio) for a in anexos) == [(8, 2024), (8, 2025), (8, 2026), (29, 2024), (29, 2025), (29, 2026)]
