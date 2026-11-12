"""Grafo estructural (RF-07): referencias explícitas extraídas con expresiones regulares, sin LLM.

- REGLAMENTA: de una regla a los artículos de ley que cita en la línea de referencias del final
  ("CFF 29, 29-A, LISR 27, RMF 2.7.1.21."). Las reglas que cita ahí son REMITE_A.
- REMITE_A: de un artículo o regla a otra unidad que nombra en su texto ("artículo 27 de esta Ley",
  "artículos 20 y 22-B del CFF", "la regla 2.1.6.").
- REFORMA no es una tabla: es `versiones.decreto` (cada versión dice qué decreto la publicó).

Solo se guardan aristas a unidades del corpus (LISR, LIVA, CFF y la RMF del año); lo de otras leyes
o reglamentos se descarta. Ante la duda (“de dicha Ley”, un artículo sin ley dentro de una regla) no
hay arista: el criterio de RF-07 pide precisión de 1.0.
"""
from __future__ import annotations

import re

from .almacen import clave

_SUFIJOS = r"Bis|Ter|Qu[aá]ter|Quinquies|Sexies|Septies|Octies"
# "27", "9o.", "29-A", "17-H Bis", "188-Bis". shortcut: una lista que sigue tras ";" ("102 y 105 [...]; 108
# y 109 [...] de este Código") pierde lo de después del punto y coma; medido en RF-07, recall 0.947.
NUM = rf"\d{{1,3}}(?:o\.?|º)?(?:\s*-\s*(?!(?:{_SUFIJOS})\b)[A-Z]{{1,2}}\b)?(?:(?:\s+|\s*-\s*)(?:{_SUFIJOS})\b)?"
REGLA_NUM = r"\d{1,2}(?:\.\d{1,3}){1,3}\.?"
SIGLAS = {"CFF": "CFF", "LISR": "LISR", "LIVA": "LIVA"}

# Designador de una lista de artículos en el texto: lo que sigue a los números.
DESIGNADORES = [
    (re.compile(r"^de\s+(?:esta|la\s+presente)\s+Ley\b|^de\s+este\s+(?:C[oó]digo|ordenamiento)\b"), "propio"),
    (re.compile(r"^del\s+(?:CFF\b|C[oó]digo\s+Fiscal\s+de\s+la\s+Federaci[oó]n\b|C[oó]digo\b(?!\s+(?:Civil|Nacional|Penal|de\s+Comercio)))"), "CFF"),
    (re.compile(r"^de\s+la\s+(?:LISR\b|Ley\s+del\s+(?:ISR|Impuesto\s+sobre\s+la\s+Renta)\b)"), "LISR"),
    (re.compile(r"^de\s+la\s+(?:LIVA\b|Ley\s+del\s+(?:IVA|Impuesto\s+al\s+Valor\s+Agregado)\b)"), "LIVA"),
    # Cualquier otra ley, reglamento o decreto, o una remisión ambigua: sin arista.
    (re.compile(r"^(?:de|del)\s+(?:la\s+|los\s+|las\s+|el\s+|su\s+|dicha\s+|dicho\s+|citad[oa]\s+|referid[oa]\s+)*"
                r"(?:[A-ZÁÉÍÓÚ]|citad|referid|dich|mencionad)"), None),
]
# Lo que puede ir entre dos números de una lista o entre el último y el designador:
# "20, séptimo párrafo y 22-B del CFF", "27, apartado C, fracción III de esta Ley".
CALIFICADOR = (r"(?:fracci[oó]n(?:es)?|p[aá]rrafos?|apartados?|incisos?|numerales?|primer[oa]?|segund[oa]|tercer[oa]?|"
               r"cuart[oa]|quint[oa]|sext[oa]|s[eé]ptim[oa]|octav[oa]|noven[oa]|d[eé]cim[oa]|[uú]ltim[oa]|"
               r"pen[uú]ltim[oa]|antepen[uú]ltim[oa]|oraci[oó]n|[IVXLC]+|[A-Z]|[a-z]\)|y|a|al)\b\.?")
SEPARADOR = rf"(?:\s*,\s*|\s+)(?:{CALIFICADOR}[\s,]*)*?(?:,\s*|y\s+|a\s+|\s)"
# La cola va en una búsqueda hacia adelante para no consumir el texto: en la misma oración puede venir
# otra lista ("del artículo 135 de la Ley del ISR, [...] el artículo 22-A del CFF").
LISTA_ARTICULOS = re.compile(rf"\b[Aa]rt[íi]culos?\s+((?:{NUM})(?:{SEPARADOR}(?:{NUM}))*)(?=([^;]{{0,160}}))", re.S)
LISTA_REGLAS = re.compile(rf"\breglas?\s+((?:{REGLA_NUM})(?:(?:\s*,\s*|\s+y\s+|\s+a\s+|\s*;\s*)(?:{REGLA_NUM}))*)")


def _numeros(lista: str) -> list[str]:
    """Números de artículo de una lista: los que abren la lista o siguen a una coma o a "y"/"a";
    así "15 días" o "de 2024" no cuentan."""
    return [m.group(1) for m in re.finditer(rf"(?:^|,\s*|\s+y\s+|\s+a\s+)({NUM})(?=\s*(?:,|\s+y\s|\s+a\s|\s+de\b|\s+del\b|$|\s+(?:fracci|p[aá]rrafo|primer|segund|tercer|cuart|quint|sext|[uú]ltim|pen[uú]ltim|apartado|inciso|numeral)))", lista)]


def remisiones(texto: str, documento: str) -> set[tuple[str, str]]:
    """(documento, clave) de las unidades del corpus que nombra `texto`, escrito en `documento`
    ("LISR", "RMF2026"...). Un artículo sin ley nombrada es de la misma ley si `documento` es ley."""
    es_rmf = documento.startswith("RMF")
    salida: set[tuple[str, str]] = set()
    for m in LISTA_ARTICULOS.finditer(texto):
        lista, resto = m.group(1), m.group(2)
        # Lo que sigue al último número: el designador está al inicio, pasadas las fracciones y párrafos.
        cola = re.sub(rf"^(?:\s*,?\s*(?:{CALIFICADOR}|del?\b(?=\s+(?:inciso|apartado)))\s*)+", "", resto).strip()
        destino = "propio"
        for patron, doc in DESIGNADORES:
            if patron.match(cola):
                destino = doc
                break
        else:
            if cola[:1].isalpha() and not re.match(r"^(?:de\s+este\s+art|y\s|o\s|que\s|en\s|se\s|para\s|cuando\s|a\s|del\s+presente)", cola):
                destino = "propio" if re.match(r"^[a-záéíóúñ]", cola) else None
        if destino == "propio":
            destino = None if es_rmf else documento
        if destino:
            salida |= {(destino, clave(n)) for n in _numeros(lista)}
    if es_rmf:
        for m in LISTA_REGLAS.finditer(texto):
            salida |= {(documento, clave(n)) for n in re.findall(REGLA_NUM, m.group(1))}
    return salida


def enlazar(con) -> dict[str, int]:
    """Agrega las REMITE_A del texto de cada artículo y regla (las de la línea de referencias de las
    reglas ya las puso la construcción) y quita las que apuntan fuera del corpus o a sí mismas."""
    filas = con.execute("SELECT v.id, v.documento, v.clave, v.texto FROM versiones v JOIN documentos d "
                        "ON d.id = v.documento WHERE d.tipo IN ('ley', 'resolucion')").fetchall()
    con.executemany("INSERT OR IGNORE INTO aristas VALUES (?, 'REMITE_A', ?, ?)",
                    [(id_, d, c) for id_, doc, propia, texto in filas for d, c in remisiones(texto, doc)
                     if (d, c) != (doc, propia)])
    fuera = con.execute("DELETE FROM aristas WHERE NOT EXISTS (SELECT 1 FROM versiones v WHERE "
                        "v.documento = aristas.documento AND v.clave = aristas.clave)").rowcount
    con.execute("DELETE FROM aristas WHERE EXISTS (SELECT 1 FROM versiones v WHERE v.id = aristas.version "
                "AND v.documento = aristas.documento AND v.clave = aristas.clave)")
    return {"aristas": con.execute("SELECT count(*) FROM aristas").fetchone()[0], "fuera_del_corpus": fuera}


def referencias_de_regla(lineas: list[str], anio: int) -> set[tuple[str, str, str]]:
    """(tipo, documento, clave) de la línea de referencias del final de una regla. Cada sigla abre un
    tramo; lo que no es CFF, LISR, LIVA ni RMF se descarta. "RMF 2024 2.1.39." es de otro año;
    "LISR 2013 53", de una ley abrogada."""
    texto = " ".join(lineas)
    tramos = re.split(r"(?:^|,\s*|\s)(?=[A-Z][A-Za-z]{1,12}\s+\d)", texto)
    salida = set()
    for tramo in tramos:
        m = re.match(r"([A-Z][A-Za-z]{1,12})\s+(.*)$", tramo.strip(), re.S)
        if not m:
            continue
        sigla, resto = m.groups()
        anio_explicito = re.match(r"(20\d\d)\s+(.*)$", resto, re.S)
        if sigla == "RMF":
            doc = f"RMF{anio_explicito.group(1) if anio_explicito else anio}"
            salida |= {("REMITE_A", doc, clave(n)) for n in re.findall(REGLA_NUM, resto)}
        elif sigla in SIGLAS and not anio_explicito:
            salida |= {("REGLAMENTA", SIGLAS[sigla], clave(n)) for n in _numeros(resto.strip())}
    return salida
