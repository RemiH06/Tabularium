"""Medición del corpus para la iteración 0. Exploración, no código del producto.

Lee los documentos ya bajados en `cache/` y los parte en unidades (artículos o
reglas) para contar, medir y comparar versiones. No descarga nada: eso lo hace
`descarga.py`.
"""
from __future__ import annotations

import re
import struct
from dataclasses import dataclass, field
from pathlib import Path

import olefile
import pymupdf

SUFIJOS = r"bis|ter|qu[aá]ter|quinquies|sexies|septies|octies|nonies|decies"
# "Artículo 1o.-", "Artículo 1o.-A.-", "Artículo 17-H Bis.-", "Artículo 113-A.", "Artículo 156-Bis.-"
ENCABEZADO = re.compile(
    rf"^Art[ií]culo\s+(\d+[oº]?(?:(?:\.-|-|\s)(?:[A-Z]{{1,2}}|(?i:{SUFIJOS})))*)\s*\.(?:-|\s|$)")
FIN_CUERPO = re.compile(r"^(ART[ÍI]CULOS?\s+)?TRANSITORI[OA]S?$|^DISPOSICI[OÓ]N(ES)?\s+TRANSITORIAS?\b", re.I)
JERARQUIA = re.compile(r"^(T[IÍ]TULO|CAP[IÍ]TULO|SECCI[OÓ]N)\s+\S+", re.I)
NIVELES = ("TITULO", "CAPITULO", "SECCION")
ACCION = re.compile(r"reformad|adicionad|derogad|actualizad|compilad|recorrid|reubicad|Fe de erratas|Reforma DOF", re.I)
# Recorre una nota en orden: cada fecha hereda el último verbo que la precede.
VERBO_O_FECHA = re.compile(
    r"(reformad|adicionad|derogad|actualizad|compilad|recorrid|reubicad|erratas)|(\d{2})-(\d{2})-(\d{4})", re.I)


@dataclass
class Unidad:
    id: str
    lineas: list[str] = field(default_factory=list)
    jerarquia: tuple[str, ...] = ()

    @property
    def notas(self) -> list[str]:
        """Notas editoriales de la Cámara ("Párrafo reformado DOF 12-11-2021")."""
        return [l for l in self.lineas if es_nota(l)]

    @property
    def eventos(self) -> set[tuple[str, str]]:
        """Pares (fecha AAAA-MM-DD, verbo) de las notas.

        "Compilada" no cambia el texto: el Anexo 5 de la RMF solo volvió a publicar la cantidad.
        """
        pares = set()
        for nota in self.notas:
            verbo = ""
            for m in VERBO_O_FECHA.finditer(nota):
                if m.group(1):
                    verbo = m.group(1).lower()
                else:
                    pares.add((f"{m.group(4)}-{m.group(3)}-{m.group(2)}", verbo))
        return pares

    @property
    def texto(self) -> str:
        """Texto de la norma sin las notas editoriales y con espacios normalizados."""
        return normalizar(" ".join(l for l in self.lineas if not es_nota(l)))


def es_nota(linea: str) -> bool:
    return "DOF" in linea and len(linea) < 400 and bool(ACCION.search(linea))


def normalizar(texto: str) -> str:
    """Solo toca espacios y marcas de control, como pide RNF-05."""
    return re.sub(r"\s+", " ", re.sub(r"[\x00-\x08\x0b-\x1f\xa0]", " ", texto)).strip()


def texto_doc(ruta: Path) -> str:
    """Texto principal de un .doc binario (Word 97 a 2003) leyendo su tabla de piezas.

    Evita depender de LibreOffice o de Word para explorar. Devuelve un párrafo por línea.
    """
    ole = olefile.OleFileIO(str(ruta))
    wd = ole.openstream("WordDocument").read()
    flags = struct.unpack_from("<H", wd, 0x0A)[0]
    tabla = ole.openstream("1Table" if flags & 0x0200 else "0Table").read()
    fc_clx, lcb_clx = struct.unpack_from("<II", wd, 0x01A2)
    clx = tabla[fc_clx:fc_clx + lcb_clx]
    i = 0
    while clx[i] == 0x01:  # bloques Prc, no llevan texto
        i += 3 + struct.unpack_from("<H", clx, i + 1)[0]
    lcb = struct.unpack_from("<I", clx, i + 1)[0]
    plc = clx[i + 5:i + 5 + lcb]
    n = (lcb - 4) // 12
    cps = struct.unpack_from(f"<{n + 1}I", plc, 0)
    partes = []
    for k in range(n):
        fc = struct.unpack_from("<I", plc, 4 * (n + 1) + 8 * k + 2)[0]
        largo = cps[k + 1] - cps[k]
        if fc & 0x40000000:  # pieza en cp1252, un byte por carácter
            ini = (fc & 0x3FFFFFFF) // 2
            partes.append(wd[ini:ini + largo].decode("cp1252", errors="replace"))
        else:  # pieza en UTF-16
            partes.append(wd[fc:fc + 2 * largo].decode("utf-16-le", errors="replace"))
    ccp_text = struct.unpack_from("<I", wd, 0x4C)[0]  # lo que sigue son notas al pie y encabezados
    texto = "".join(partes)[:ccp_text]
    # Campos de Word: \x13 instrucción \x14 resultado \x15. Se quita la instrucción (por ejemplo,
    # INCLUDEPICTURE de una fórmula pegada como imagen) y se conserva el resultado.
    previo = None
    while previo != texto:
        previo = texto
        texto = re.sub(r"\x13[^\x13\x14\x15]*(?:\x14|\x15)", "", texto)
    texto = texto.replace("\x15", "")
    return texto.replace("\r", "\n").replace("\x0c", "\n").replace("\x07", "\t")


def texto_pdf(ruta: Path) -> str:
    """Texto de un PDF de LeyesBiblio sin el encabezado que se repite en cada página."""
    paginas = []
    with pymupdf.open(ruta) as pdf:
        for pagina in pdf:
            t = pagina.get_text()
            m = re.search(r"\n\s*\d+ de \d+\s*\n", t[:600])
            paginas.append(t[m.end():] if m else t)
    return "\n".join(paginas)


def segmentar_ley(texto: str) -> tuple[list[Unidad], str]:
    """Parte una ley en artículos. Devuelve (artículos del cuerpo, texto de los transitorios)."""
    unidades: list[Unidad] = []
    jerarquia: dict[str, str] = {}
    lineas = [l.strip() for l in texto.split("\n")]
    sin_nombre = ""  # nivel cuyo nombre ("Disposiciones generales") viene en la línea siguiente
    for i, linea in enumerate(lineas):
        if unidades and FIN_CUERPO.match(linea):
            return unidades, "\n".join(lineas[i:])
        m = JERARQUIA.match(linea)
        if m and len(linea) < 80:
            nivel = m.group(1).upper().replace("Í", "I").replace("Ó", "O")
            jerarquia[nivel] = linea
            for inferior in NIVELES[NIVELES.index(nivel) + 1:]:
                jerarquia.pop(inferior, None)
            sin_nombre = nivel
            continue
        if sin_nombre and linea:
            nivel, sin_nombre = sin_nombre, ""
            if not ENCABEZADO.match(linea) and not es_nota(linea) and len(linea) < 200:
                jerarquia[nivel] += ": " + linea
                continue
        elif sin_nombre:
            continue
        m = ENCABEZADO.match(linea)
        if m:
            unidades.append(Unidad(id=normalizar(m.group(1)), jerarquia=tuple(jerarquia.values())))
        if unidades:
            unidades[-1].lineas.append(linea)
    return unidades, ""


REGLA = re.compile(r"^(\d{1,2}(?:\.\d{1,3}){1,3})\.$")  # "1.9.", "3.13.2.", "2.7.1.21."
PIE_COMPILADO = re.compile(r"NOTA: Este documento constituye una compilación.*?Página \d+ de \d+", re.S)


def texto_rmf(ruta: Path) -> str:
    """Texto de un PDF de la RMF del minisitio del SAT, sin la nota que repiten las compiladas."""
    with pymupdf.open(ruta) as pdf:
        return PIE_COMPILADO.sub("", "\n".join(p.get_text() for p in pdf))


def segmentar_rmf(texto: str) -> tuple[list[Unidad], str]:
    """Parte la RMF en reglas. Devuelve (reglas, texto de los transitorios).

    El encabezado de una regla es su número solo en una línea, con el título en la línea
    anterior. Una referencia cortada por el salto de línea se ve igual, así que de todos los
    candidatos se conserva la cadena creciente más larga: los números de regla van en orden.
    """
    lineas = [l.strip() for l in texto.split("\n")]
    cand = [(i, tuple(int(x) for x in m.group(1).split(".")))
            for i, l in enumerate(lineas) if (m := REGLA.match(l))]
    largo, previo = [1] * len(cand), [-1] * len(cand)
    for b in range(len(cand)):
        for a in range(b):
            if cand[a][1] < cand[b][1] and largo[a] + 1 > largo[b]:
                largo[b], previo[b] = largo[a] + 1, a
    k = max(range(len(cand)), key=largo.__getitem__) if cand else -1
    cadena = []
    while k != -1:
        cadena.append(cand[k])
        k = previo[k]
    cadena.reverse()
    fin = next((i for i in range(cadena[-1][0], len(lineas)) if FIN_CUERPO.match(lineas[i])), len(lineas))
    reglas = []
    for (i, num), sig in zip(cadena, [c[0] - 1 for c in cadena[1:]] + [fin]):
        reglas.append(Unidad(id=".".join(map(str, num)), lineas=[lineas[i - 1]] + lineas[i + 1:sig]))
    return reglas, "\n".join(lineas[fin:])


def comparar(base: list[Unidad], actual: list[Unidad]) -> dict[str, list[str]]:
    """Diferencias entre dos versiones de una ley, por id de artículo."""
    a, b = {u.id: u.texto for u in base}, {u.id: u.texto for u in actual}
    return {
        "cambiados": sorted(k for k in a.keys() & b.keys() if a[k] != b[k]),
        "nuevos": sorted(b.keys() - a.keys()),
        "quitados": sorted(a.keys() - b.keys()),
    }


def tocados_desde(unidades: list[Unidad], desde: str, compilaciones: bool = False) -> dict[str, set[str]]:
    """Artículos con alguna nota publicada después de `desde` (AAAA-MM-DD) y sus fechas.

    Sin `compilaciones`, solo cuentan las notas que cambian texto (reforma, adición,
    derogación, actualización de cantidades).
    """
    salida = {}
    for u in unidades:
        fechas = {f for f, verbo in u.eventos if f > desde and (compilaciones or verbo != "compilad")}
        if fechas:
            salida[u.id] = fechas
    return salida
