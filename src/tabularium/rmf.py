"""Resolución Miscelánea Fiscal: segmentación en reglas y versiones por modificación (RF-03).

La unidad es (RMF del año, regla), porque la numeración cambia de un año a otro (plan.md,
sección 11). Cada RMF rige del 1 de enero al 31 de diciembre de su año.

Fuentes, todas del minisitio del SAT: el PDF original (formato del DOF) y la compilada que el SAT
publica después de cada modificación. La compilada marca cada regla que tocó una modificación
("- Reformada en la Primera RMRMF para 2026, publicada en el DOF el 09 de julio de 2026.") y trae al
final los transitorios de cada modificación. Con esas marcas se sabe qué reglas cambiaron sin
comparar textos de formatos distintos: una regla recibe versión nueva en la compilada k solo si
trae la marca de la modificación k. La comparación de textos queda como verificación (`ruido`).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from .ley import Decreto, Unidad, _transitorios, fecha_es, normalizar

SAT = "https://www.sat.gob.mx/minisitio/NormatividadRMFyRGCE/"


@dataclass(frozen=True)
class FuenteRmf:
    anio: int
    publicado: date  # en el DOF; está en el nombre del archivo original y en la portada de cada compilada
    original: str
    # Una por modificación, en orden; la última trae los transitorios de todas. None: no hay compilada
    # que sirva y las reglas de esa modificación salen de la siguiente o de `publicadas`.
    compiladas: tuple[str | None, ...]
    publicadas: dict[int, str] = field(default_factory=dict)  # índice de modificación -> PDF publicado en el DOF

    @property
    def documento(self) -> str:
        return f"RMF{self.anio}"

    @property
    def nombre(self) -> str:
        return f"Resolución Miscelánea Fiscal para {self.anio}"


REGLA = re.compile(r"^(\d{1,2}(?:\.\d{1,3}){1,3})\.$")  # "1.9.", "3.13.2.", "2.7.1.21."
# Ruido de página: el aviso de las compiladas y el encabezado del DOF en el original.
AVISO = "NOTA: Este documento constituye una compilación"
PIE_COMPILADO = re.compile(
    r"^(NOTA: Este documento constituye una compilaci[oó]n|de dar a conocer el texto actualizado de la Resoluci[oó]n "
    r"Miscel[aá]nea Fiscal, de conformidad|del Contribuyente\. Para sustentar legalmente|P[aá]gina \d+ de \d+$)")
ENCABEZADO_DOF = re.compile(
    r"^(DIARIO OFICIAL|\((Primera|Segunda|Tercera|Cuarta|Quinta|Sexta) Secci[oó]n\)|\(Edici[oó]n Vespertina\)|"
    r"(Lunes|Martes|Mi[eé]rcoles|Jueves|Viernes|S[aá]bado|Domingo) \d{1,2} de \w+ de \d{4})$")
MARCA = re.compile(r"^- (Reformad|Adicionad|Derogad)[oa]s?\b", re.I)
JERARQUIA = re.compile(r"^(T[ií]tulo \d+|Cap[ií]tulo \d+\.\d+|Secci[oó]n \d+\.\d+\.\d+)\.\s+\S")
FIN_CUERPO = re.compile(r"^Transitorios?$")
MODIFICACION = re.compile(
    r"^(\w+) Modificaci[oó]n de la Resoluci[oó]n Miscel[aá]nea Fiscal para \d{4}, publicada en el DOF el (.+)$")
ORDINALES = ["Primera", "Segunda", "Tercera", "Cuarta", "Quinta", "Sexta", "Séptima", "Octava", "Novena", "Décima"]

Linea = tuple[str, str]  # (texto, estilo): "b" negritas, "i" cursivas, "" normal


def texto_pdf(ruta: Path) -> list[Linea]:
    """Líneas del PDF con su estilo. El epígrafe y el número de cada regla van en negritas y las
    referencias del final en cursivas, en el original y en las compiladas: el estilo los separa
    mejor que cualquier regla sobre el texto (un epígrafe puede ocupar tres renglones y una lista
    de referencias, dos)."""
    import pymupdf  # solo la construcción lo necesita; el servidor no
    salida: list[Linea] = []
    with pymupdf.open(ruta) as pdf:
        for pagina in pdf:
            # Sin imágenes (decodificarlas es lo lento) y sin recortar al borde de la página: en las
            # compiladas hay renglones que se salen y el recorte dejaba "comprend" por "comprende".
            banderas = pymupdf.TEXTFLAGS_DICT & ~pymupdf.TEXT_PRESERVE_IMAGES & ~pymupdf.TEXT_MEDIABOX_CLIP
            for bloque in pagina.get_text("dict", flags=banderas)["blocks"]:
                lineas = bloque.get("lines", [])
                if "".join(s["text"] for l in lineas[:3] for s in l["spans"]).strip().startswith(AVISO):
                    continue  # el aviso de las compiladas es un bloque propio, partido en renglones distintos cada año
                for l in lineas:
                    # Solo los spans con letras o números cuentan para el estilo: la compilada de 2024
                    # agrega tras "2.1.2." un span normal sin texto visible.
                    spans = [s for s in l["spans"] if any(c.isalnum() for c in s["text"])]
                    i = next((k for k, s in enumerate(spans) if s["flags"] & 16), len(spans))
                    if 0 < i and all(s["flags"] & 2 and not s["flags"] & 16 for s in spans[:i]) \
                            and all(s["flags"] & 16 for s in spans[i:]):
                        # Referencias y epígrafe de la siguiente en un renglón ("CFF 27, RCFF 28Cédula de..."),
                        # como sale en la compilada de 2024: se parten en dos líneas.
                        salida += [("".join(s["text"] for s in spans[:i]).strip(), "i"),
                                   ("".join(s["text"] for s in spans[i:]).strip(), "b")]
                        continue
                    texto = "".join(s["text"] for s in l["spans"]).strip()
                    estilo = ("b" if spans and all(s["flags"] & 16 for s in spans) else
                              "i" if spans and all(s["flags"] & 2 for s in spans) else "")
                    salida.append((texto, estilo))
            salida.append(("", ""))
    return salida


def lineas_limpias(lineas: list[Linea]) -> list[Linea]:
    """Sin el ruido de página. Las vacías se conservan: cierran los bloques de marcas."""
    return [(t, e) for t, e in lineas if not PIE_COMPILADO.match(t) and not ENCABEZADO_DOF.match(t)]


@dataclass
class Regla:
    id: str
    titulo: list[str]
    cuerpo: list[str]
    referencias: list[str]  # las líneas en cursivas del final ("CFF 12, 13, LA 18"); también van en `cuerpo`
    jerarquia: tuple[str, ...] = ()
    marcas: list[tuple[str, date]] = field(default_factory=list)  # (verbo, publicación de la modificación)
    notas: list[str] = field(default_factory=list)  # las marcas como las escribe el SAT

    @property
    def texto(self) -> str:
        """Literal en el orden de la fuente: epígrafe, número y cuerpo con las referencias del final."""
        return normalizar(" ".join(self.titulo + [self.id + "."] + self.cuerpo))


@dataclass
class Rmf:
    reglas: list[Regla]
    transitorios: list[Unidad]  # de la RMF del año
    modificaciones: list[Decreto]  # solo en las compiladas: título, publicación y transitorios


def _marcas(lineas: list[Linea]) -> tuple[list[Linea], dict[str, list[str]]]:
    """Quita los bloques de marcas ("Regla 2.1.6." y sus líneas "- Reformada ...", hasta la línea
    vacía) y los devuelve por cabeza de bloque. Una marca larga sigue en la línea siguiente.
    También quita las líneas vacías, que ya no hacen falta."""
    salida, marcas = [], {}
    i = 0
    while i < len(lineas):
        if i + 1 < len(lineas) and MARCA.match(lineas[i + 1][0]):
            cabeza, notas = lineas[i][0], []
            i += 1
            # La marca va en cursivas; el bloque acaba en la primera línea vacía o con otro estilo
            # (la compilada de 2024 pega el epígrafe en negritas sin línea vacía de por medio).
            while i < len(lineas) and lineas[i][0] and (MARCA.match(lineas[i][0]) or lineas[i][1] == lineas[i - 1][1]):
                if MARCA.match(lineas[i][0]):
                    notas.append(lineas[i][0])
                else:
                    notas[-1] += " " + lineas[i][0]
                i += 1
            marcas.setdefault(cabeza, []).extend(notas)
            continue
        if lineas[i][0]:
            salida.append(lineas[i])
        i += 1
    return salida, marcas


def _cadena(lineas: list[Linea]) -> list[tuple[int, tuple[int, ...]]]:
    """Líneas que son el número de una regla: en negritas y, de los candidatos, la cadena creciente
    más larga, porque las reglas van en orden (descarta números sueltos del índice o del texto)."""
    cand = [(i, tuple(int(x) for x in m.group(1).split("."))) for i, (t, e) in enumerate(lineas)
            if e == "b" and (m := REGLA.match(t))]
    largo, previo = [1] * len(cand), [-1] * len(cand)
    for b in range(len(cand)):
        for a in range(max(0, b - 60), b):  # un número suelto no salta más de 60 candidatos
            if cand[a][1] < cand[b][1] and largo[a] + 1 > largo[b]:
                largo[b], previo[b] = largo[a] + 1, a
    k = max(range(len(cand)), key=largo.__getitem__) if cand else -1
    cadena = []
    while k != -1:
        cadena.append(cand[k])
        k = previo[k]
    return cadena[::-1]


def _encabezados(lineas: list[Linea]) -> dict[int, int]:
    """Encabezados de título, capítulo o sección: línea de inicio -> línea siguiente al nombre. Un
    nombre largo sigue en negritas en renglones que no empiezan en mayúscula ("hidrocarburos y
    petrolíferos", "30 de diciembre de 2020"); un epígrafe de regla sí empieza en mayúscula."""
    salida = {}
    for a, (t, _) in enumerate(lineas):
        if JERARQUIA.match(t):
            b = a + 1
            while b < len(lineas) and lineas[b][1] == "b" and not lineas[b][0][:1].isupper():
                b += 1
            salida[a] = b
    return salida


def _titulo(lineas: list[Linea], i: int, limite: int, encabezado: set[int]) -> int:
    """Primera línea del epígrafe de la regla cuyo número está en `i`: las negritas de antes que no
    son encabezado. Un epígrafe justificado puede salir del PDF con una palabra por línea, de ahí el
    margen de 15."""
    j = i
    while j > limite + 1 and lineas[j - 1][1] == "b" and j - 1 not in encabezado and i - j < 15:
        j -= 1
    return j


def segmentar(fuente: list[Linea], minimo: int = 500) -> Rmf:
    """`minimo`: reglas esperadas como mínimo; una modificación publicada en el DOF trae pocas."""
    lineas, marcas = _marcas(lineas_limpias(fuente))
    cadena = _cadena(lineas)
    if len(cadena) < minimo:
        raise ValueError(f"solo {len(cadena)} reglas: el formato de la RMF cambió")
    fin = next((i for i in range(cadena[-1][0], len(lineas)) if FIN_CUERPO.match(lineas[i][0])), None)
    if fin is None:
        raise ValueError("no se encontró el inicio de los transitorios de la RMF")

    encabezados = _encabezados(lineas)
    encabezado = {x for a, b in encabezados.items() for x in range(a, b)}
    nombres: dict[str, str] = {}  # "2.1" -> "Capítulo 2.1. Disposiciones generales"
    for a, b in encabezados.items():
        if cadena[0][0] - 40 <= a < fin and (n := JERARQUIA.match(lineas[a][0]).group(1).split()[1]) not in nombres:
            nombres[n] = normalizar(" ".join(t for t, _ in lineas[a:b]))

    reglas = []
    inicios = [_titulo(lineas, i, cadena[k - 1][0] if k else -1, encabezado) for k, (i, _) in enumerate(cadena)]
    for k, (i, num) in enumerate(cadena):
        sig = inicios[k + 1] if k + 1 < len(cadena) else fin
        id_ = ".".join(map(str, num))
        cuerpo = [lineas[x] for x in range(i + 1, sig) if x not in encabezado]
        n_ref = next((n for n in range(len(cuerpo)) if cuerpo[len(cuerpo) - 1 - n][1] != "i"), len(cuerpo))
        jerarquia = tuple(nombres[p] for p in (".".join(map(str, num[:n])) for n in range(1, len(num))) if p in nombres)
        # Las marcas de su capítulo o sección también son suyas: un capítulo adicionado no marca cada regla.
        prefijos = [".".join(map(str, num[:n])) for n in range(2, len(num))]
        notas = [n for p in prefijos for cabeza in (f"Capítulo {p}.", f"Sección {p}.") for n in marcas.get(cabeza, [])]
        notas += marcas.get(f"Regla {id_}.", [])
        r = Regla(id_, [t for t, _ in lineas[inicios[k]:i]], [t for t, _ in cuerpo],
                  [t for t, _ in cuerpo[len(cuerpo) - n_ref:]], jerarquia, notas=notas)
        for n in notas:
            verbo = MARCA.match(n).group(1).lower()
            if (f := fecha_es(n)) is None:
                raise ValueError(f"regla {id_}: marca sin fecha legible: {n!r}")
            r.marcas.append((verbo, f))
        reglas.append(r)

    cola = []
    for t, _ in lineas[fin:]:  # "Décimo" y "Primero." en renglones distintos
        if cola and re.fullmatch(r"(D[eé]cimo|Vig[eé]simo|Trig[eé]simo)", cola[-1]) and t[:1].isupper():
            cola[-1] += " " + t
        else:
            cola.append(t)
    mods = [i for i, l in enumerate(cola) if MODIFICACION.match(l + " " + (cola[i + 1] if i + 1 < len(cola) else ""))]
    transitorios = _transitorios(cola[:mods[0] if mods else len(cola)], prefijo_sin_seccion="Transitorio")
    modificaciones = []
    for a, b in zip(mods, mods[1:] + [len(cola)]):
        m = MODIFICACION.match(cola[a] + " " + cola[a + 1])
        publicado = fecha_es(m.group(2))
        if m.group(1) not in ORDINALES or publicado is None:
            raise ValueError(f"encabezado de modificación ilegible: {cola[a]!r}")
        titulo = f"{m.group(1)} Resolución de Modificaciones a la Resolución Miscelánea Fiscal"
        modificaciones.append(Decreto(titulo, publicado, _transitorios(cola[a + 2:b], prefijo_sin_seccion="Transitorio")))
    return Rmf(reglas, transitorios, modificaciones)


def transitorios(fuente: list[Linea]) -> list[Unidad]:
    """Transitorios de una modificación publicada en el DOF: la sección "Transitorio(s)" del final."""
    return _transitorios([t for t, _ in lineas_limpias(fuente)], prefijo_sin_seccion="Transitorio")
