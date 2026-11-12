"""Lo que el documento de LeyesBiblio no dice solo: vigencias que el segmentador no lee y textos
intermedios que ninguna copia fechada conserva.

Cada entrada cita su fuente. `tests/test_corpus_real.py` comprueba contra la caché que el texto
reconstruido aparece literal en esa fuente, así que una entrada mal copiada rompe una prueba.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date


@dataclass(frozen=True)
class Publicacion:
    """Vigencia de una publicación del DOF cuando su transitorio no se lee o tiene excepciones."""

    vigor: date
    motivo: str
    excepciones: dict[str, date] = field(default_factory=dict)  # unidad -> vigencia propia
    titulo: str | None = None  # solo si LeyesBiblio no trae el bloque del decreto

    def vigor_de(self, unidad: str) -> date:
        return self.excepciones.get(unidad, self.vigor)


ANEXO_5 = ("Cantidades actualizadas del Anexo 5 de la RMF: rigen desde el 1 de enero del ejercicio "
           "(art. 17-A del CFF).")

PUBLICACIONES: dict[date, Publicacion] = {
    date(2024, 12, 30): Publicacion(date(2025, 1, 1), ANEXO_5),
    date(2025, 11, 7): Publicacion(
        date(2026, 1, 1), "Transitorio Primero: en vigor el 1 de enero de 2026, salvo el art. 30-B.",
        excepciones={"30-B": date(2026, 4, 1)}),
    # El Transitorio Segundo difiere la *aplicación* a la declaratoria del Código Nacional de
    # Procedimientos Civiles y Familiares; la vigencia formal es la del Primero.
    date(2025, 11, 14): Publicacion(date(2025, 11, 15), "Transitorio Primero: día siguiente a la publicación."),
    date(2025, 12, 28): Publicacion(
        date(2026, 1, 1), ANEXO_5,
        titulo="Anexos 4, 5, 6, 8, 15 y 25 de la Resolución Miscelánea Fiscal para 2026"),
}


# Fechas con dos decretos del corpus. Una nota "reformado DOF dd-mm-aaaa" de esa fecha remite al
# primero del documento (sin sufijo); cada entrada dice por qué eso es correcto.
MISMO_DIA: dict[date, str] = {
    date(2002, 12, 30): "LIVA: el segundo decreto solo reformó el último párrafo del art. 2o., cuya última reforma "
                        "es posterior; las notas de esa fecha en la base (1o.-B, 12, 22 y 34) son del primero.",
}


@dataclass(frozen=True)
class Intermedia:
    """Versión que rigió entre dos reformas y que no está en ninguna copia fechada del `.doc`.

    Se reconstruye desde la versión siguiente deshaciendo, literal, lo que cambió la reforma
    posterior: cada par es (texto en la versión siguiente, texto que tenía esta).
    """

    documento: str
    unidad: str
    desde: date
    cambios: tuple[tuple[str, str], ...]
    fuente_url: str


PDF_CFF_2025 = "https://web.archive.org/web/20250404183204id_/https://www.diputados.gob.mx/LeyesBiblio/pdf/CFF.pdf"
DOF_2025_11_07 = "https://dof.gob.mx/nota_detalle.php?codigo=5772358&fecha=07/11/2025"

INTERMEDIAS = [
    Intermedia("CFF", "32-A", date(2025, 1, 1), (("$2,013,710,870.00", "$1,940,178,120.00"),), PDF_CFF_2025),
    Intermedia("CFF", "32-H", date(2025, 1, 1), (("$1,103,204,520.00", "$1,062,919,860.00"),), PDF_CFF_2025),
    # El decreto del DOF 09-04-2026 reformó dos párrafos; los dos se regresan al texto del 07-11-2025.
    Intermedia("CFF", "141", date(2026, 1, 1), (
        ("Las personas contribuyentes podrán garantizar el interés fiscal, cuando se actualice alguno de los "
         "supuestos establecidos en los artículos 74 y 142 de este Código, en alguna de las formas siguientes:",
         "Los contribuyentes podrán garantizar el interés fiscal, cuando se actualice alguno de los supuestos "
         "establecidos en los artículos 74 y 142 de este Código, conforme al siguiente orden obligatorio:"),
        ("La garantía deberá comprender, además de las contribuciones adeudadas actualizadas, los accesorios "
         "causados, así como de los que se causen en los doce meses siguientes a su otorgamiento. Al terminar "
         "este periodo",
         "Los contribuyentes deberán ofrecer como garantía, en todos los casos, la modalidad señalada en la "
         "fracción I, hasta por el importe máximo de su capacidad económica, aun y cuando no sea suficiente para "
         "garantizar el interés fiscal y, en la misma solicitud, combinarse con alguna de las formas y en el "
         "orden que al efecto establece este artículo, en ese caso, los contribuyentes deberán demostrar la "
         "imposibilidad para garantizar sus adeudos fiscales bajo las modalidades establecidas en las fracciones "
         "I, II, III, IV, V y VI, en ese orden, presentando la documentación que acredite dicha situación. La "
         "garantía deberá comprender, además de las contribuciones adeudadas actualizadas, los accesorios "
         "causados, así como de los que se causen en los doce meses siguientes a su otorgamiento. Al terminar "
         "este período"),
    ), DOF_2025_11_07),
]


def intermedia(documento: str, unidad: str, desde: date) -> Intermedia | None:
    return next((i for i in INTERMEDIAS if (i.documento, i.unidad, i.desde) == (documento, unidad, desde)), None)


def deshacer(texto: str, i: Intermedia) -> str:
    for nuevo, viejo in i.cambios:
        if texto.count(nuevo) != 1:
            raise ValueError(f"{i.documento} art. {i.unidad}: {nuevo[:60]!r} no aparece una sola vez en el texto")
        texto = texto.replace(nuevo, viejo)
    return texto
