"""Preparación de texto para BM25: palabras vacías, raíces (Snowball en español), siglas y
referencias exactas a un artículo.

FTS5 no acepta tokenizadores escritos en Python, así que el texto se reduce a raíces aquí y se
guarda ya procesado en la tabla `busqueda`; la consulta pasa por la misma función.
"""
from __future__ import annotations

import re
import unicodedata
from functools import lru_cache

import snowballstemmer

_STEMMER = snowballstemmer.stemmer("spanish")

VACIAS = frozenset("""
a al algo algun alguna algunas alguno algunos ante antes aqui asi aun cada como con contra cual cuales cuando
cuanto cuanta cuantos cuantas de del desde donde dos durante e el ella ellas ellos en entre era es esa esas ese
eso esos esta estas este esto estos fue fueron ha han hasta hay la las le les lo los mas me mi mis mucho muy nada
ni no nos o otra otras otro otros para pero poco por porque puede pueden que quien quienes se sea segun ser si
sido sin sobre solo son su sus tal tambien tan tanto te tener tengo tiene tienen todo todos tu tus un una unas
uno unos y ya yo hago hacer hace debo debe deben puedo
""".split())

# Siglas de uso común que el texto de las leyes escribe completas. Se agregan a la consulta, no la
# reemplazan. ISR, IVA y SAT no: expandidas atraen transitorios de decretos, que sí nombran la ley
# completa, en vez de artículos ("este impuesto", "las autoridades fiscales"). ISR e IVA cuentan como
# mención de su ley (`DOCUMENTOS`).
SIGLAS = {
    "cfdi": "comprobante fiscal digital internet",
    "rfc": "registro federal contribuyentes",
    "ieps": "impuesto especial produccion servicios",
    "iva": "impuesto valor agregado",
    "resico": "regimen simplificado confianza",
    "uma": "unidad medida actualizacion",
}

_SUFIJOS = r"bis|ter|qu[aá]ter|quinquies|sexies|septies|octies|nonies|decies"
REFERENCIA = re.compile(
    rf"\bart(?:[ií]culo|\.)?\s*(\d+\s*[oº]?\.?(?:\s*-\s*[A-Z]{{1,2}}\b)?(?:[\s-]+(?:{_SUFIJOS})\b)?)", re.I)
DOCUMENTOS = {
    "LISR": re.compile(r"\bL?ISR\b|Impuesto sobre la Renta", re.I),
    "LIVA": re.compile(r"\bL?IVA\b|Impuesto al Valor Agregado", re.I),
    "CFF": re.compile(r"\bCFF\b|C[oó]digo Fiscal(?: de la Federaci[oó]n)?", re.I),
    "RMF": re.compile(r"\bRMF\b|\bmiscel[aá]nea\b", re.I),
}
REGLA = re.compile(r"\bregla\s+(\d{1,2}(?:\.\d{1,3}){1,3})\b", re.I)


def _plano(s: str) -> str:
    return unicodedata.normalize("NFKD", s.lower()).encode("ascii", "ignore").decode()


@lru_cache(maxsize=200_000)
def _raiz(palabra: str) -> str:
    return _STEMMER.stemWord(palabra)


def raices(texto: str) -> list[str]:
    """Palabras sin acentos, sin vacías y reducidas a su raíz. Los números se quedan como están."""
    return [_raiz(p) for p in re.findall(r"\w+", _plano(texto)) if p not in VACIAS]


def expandir(texto: str) -> str:
    """La consulta con sus siglas desarrolladas al final: "tasa del IVA" -> "tasa del IVA (impuesto
    valor agregado)". También para el embedding, que con la sigla sola no encuentra el artículo."""
    extra = ", ".join(dict.fromkeys(SIGLAS[p] for p in re.findall(r"\w+", _plano(texto)) if p in SIGLAS))
    return f"{texto} ({extra})" if extra else texto


def consulta(texto: str) -> list[str]:
    """Raíces de la consulta, con las siglas expandidas y sin repetir. Sin años: el momento lo
    fija `fecha`, y "2025" en la consulta solo atrae transitorios."""
    return [r for r in dict.fromkeys(raices(expandir(texto))) if not re.fullmatch(r"(?:19|20)\d\d", r)]


def mencionados(texto: str) -> set[str]:
    """Leyes que la consulta nombra (por sigla, nombre o el impuesto): sus artículos suben."""
    return {d for d, r in DOCUMENTOS.items() if r.search(texto)}


def referencias(texto: str) -> list[tuple[str, str]]:
    """Unidades citadas por número con su documento: "art. 27 fracción V LISR" -> [("LISR", "27")].
    Un artículo sin ley en la consulta no es referencia: el mismo número existe en las tres leyes.
    Una regla ("regla 3.13.2") es de la RMF del año de la fecha de la consulta."""
    reglas = [("RMF", m.group(1)) for m in REGLA.finditer(texto)]
    docs = mencionados(texto) - {"RMF"}
    if len(docs) != 1:
        return reglas
    return reglas + [(docs.pop(), m.group(1).strip()) for m in REFERENCIA.finditer(texto)]
