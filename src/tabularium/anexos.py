"""Anexos de la RMF: el 8 (tarifas del ISR) y el 29 (disposiciones para los PCCFDI) (RF-03).

Cada anexo es un documento por año ("RMF2026-A8"), como la RMF: rige del 1 de enero al 1 de enero
siguiente, o desde su publicación si sale después (el 29 de 2026 salió el 9 de enero).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

from .ley import fecha_es
from .rmf import AVISO, ENCABEZADO_DOF, ORDINALES, SAT


@dataclass(frozen=True)
class FuenteAnexo:
    numero: int
    anio: int
    publicado: date  # en el DOF
    url: str
    # (publicación en el DOF, compilada del SAT) de cada modificación, en orden.
    modificaciones: tuple[tuple[date, str], ...] = ()

    @property
    def documento(self) -> str:
        return f"RMF{self.anio}-A{self.numero}"

    @property
    def nombre(self) -> str:
        return f"Anexo {self.numero} de la Resolución Miscelánea Fiscal para {self.anio}"


# Nombres de archivo del HTML de cada año (docs/fuentes.md, ficha 5). shortcut: lista fija hasta RF-06.
FUENTES_ANEXOS = [
    FuenteAnexo(8, 2024, date(2023, 12, 29), SAT + "documentos2024/rmf/anexos/Anexo_8_RMF2024-29122023.pdf"),
    FuenteAnexo(8, 2025, date(2024, 12, 30), SAT + "documentos2025/rmf/anexos/Anexo8_RMF2025-30122024.pdf"),
    FuenteAnexo(8, 2026, date(2025, 12, 28), SAT + "documentos2026/rmf/anexos/Anexo-8-RMF-2026_DOF-28122025.pdf"),
    FuenteAnexo(29, 2024, date(2024, 1, 22), SAT + "documentos2024/rmf/anexos/Anexo_29_RMF2024-22012024.pdf", (
        (date(2024, 6, 4), SAT + "documentos2024/rmf/compiladas/Compilado_Primera_Modificacion_Anexo_29_de_la-RMF_2024-07062024.pdf"),
        (date(2024, 12, 12), SAT + "documentos2024/rmf/compiladas/Compilado_Segunda_Modificacion_Anexo_29_de_la-RMF_2024-12122024.pdf"))),
    FuenteAnexo(29, 2025, date(2025, 1, 3), SAT + "documentos2025/rmf/anexos/Anexo29_RMF2025_03012025.pdf", (
        (date(2025, 11, 3), SAT + "documentos2025/rmf/compiladas/Compilado_Primera_Modificacion_Anexo_29_RMF2025-03112025.pdf"),)),
    FuenteAnexo(29, 2026, date(2026, 1, 9), SAT + "documentos2026/rmf/anexos/Anexo_29_RMF2026-09012026.pdf", (
        (date(2026, 7, 17), SAT + "documentos2026/rmf/compiladas/Compilado_PrimeraModificacion_Anexo29_RMF2026-17072026.pdf"),)),
]


PAGINA = re.compile(r"^P[aá]gina \d+ de \d+$")


@dataclass
class Seccion:
    """Unidad de un anexo: una tarifa o tabla del 8, un apartado del 29."""
    id: str  # "B.VI.3", "C.II"; en el 29, "VI"
    jerarquia: tuple[str, ...]
    lineas: list[str] = field(default_factory=list)

    @property
    def texto(self) -> str:
        return "\n".join(self.lineas)


def lineas_pdf(ruta: Path) -> list[str]:
    """Texto plano del PDF por renglón, sin el ruido de página: encabezados del DOF, el aviso de las
    compiladas (un bloque propio, partido distinto en cada una) y su "Página n de m"."""
    import pymupdf  # solo la construcción lo necesita
    banderas = pymupdf.TEXTFLAGS_TEXT & ~pymupdf.TEXT_MEDIABOX_CLIP  # sin recortar al borde (rmf.texto_pdf)
    crudas = []
    with pymupdf.open(ruta) as pdf:
        for pagina in pdf:
            for bloque in pagina.get_text("blocks", flags=banderas):
                texto = " ".join(bloque[4].split())
                # El aviso puede venir partido en dos bloques: el segundo empieza a media frase.
                if bloque[6] == 0 and not texto.startswith(AVISO) and "conocer el texto actualizado de la Resoluci" not in texto:
                    crudas += [l.strip() for l in bloque[4].splitlines()]
    return [l for l in crudas if l and not ENCABEZADO_DOF.match(l) and not PAGINA.match(l)]


# --- Anexo 8: tarifas -------------------------------------------------------------------------------

APARTADO = re.compile(r"^([A-Z])\.\s*(.*)$")  # "A. Tarifa aplicable a pagos provisionales"; "C." solo
FRACCION = re.compile(r"^([IVX]+)\.\s*(.*)$")  # "VI."; "VII.  Tarifa para el cálculo..."
INICIO_TABLA = re.compile(r"^(Tarifa|Tabla)\b")
UNIDADES_TABLA = re.compile(r"^[$%]$")  # el renglón "$ $ $ %" bajo los encabezados, uno por columna
CELDA = re.compile(r"^(\d{1,3}(?:,\d{3})*\.\d{2}|0|En adelante)$")


def _numero(celda: str) -> float | None:
    return None if celda == "En adelante" else float(celda.replace(",", ""))


def _tabla(lineas: list[str], i: int) -> tuple[list[str], int]:
    """Lee la tabla que empieza en `i` (título, encabezados, renglón de unidades y celdas). Devuelve
    sus líneas ya formadas (título, encabezados y un renglón por fila, celdas separadas por " | ") y
    el índice siguiente. Comprueba que los renglones encadenen: el límite inferior de cada uno es el
    superior del anterior más un centavo."""
    j = i
    while not lineas[j].rstrip().endswith("."):  # el título acaba en punto: "... así como la regla 3.12.2."
        j += 1
    titulo = " ".join(lineas[i:j + 1])
    k = j + 1
    while not UNIDADES_TABLA.match(lineas[k]):
        k += 1
    encabezado = " ".join(lineas[j + 1:k])
    n = 0
    while UNIDADES_TABLA.match(lineas[k + n]):
        n += 1
    celdas, m = [], k + n
    while m < len(lineas) and CELDA.match(lineas[m]):
        celdas.append(lineas[m])
        m += 1
    if not celdas or len(celdas) % n:
        raise ValueError(f"tabla {titulo[:60]!r}: {len(celdas)} celdas para {n} columnas")
    filas = [celdas[x:x + n] for x in range(0, len(celdas), n)]
    # Columnas de límites: inferior y superior en las de 3 y 4; en la de 6 (con subsidio), la 2 y la 3.
    inf, sup = {3: (0, 1), 4: (0, 1), 6: (1, 2)}.get(n, (None, None))
    if inf is None:
        raise ValueError(f"tabla {titulo[:60]!r}: {n} columnas, forma no conocida")
    for a, b in zip(filas, filas[1:]):
        if round(_numero(a[sup]) + 0.01, 2) != _numero(b[inf]):
            raise ValueError(f"tabla {titulo[:60]!r}: los renglones no encadenan ({a[sup]} -> {b[inf]})")
    if filas[-1][sup] != "En adelante":
        raise ValueError(f"tabla {titulo[:60]!r}: el último renglón no es 'En adelante'")
    return [titulo, encabezado] + [" | ".join(f) for f in filas], m


def tarifas(lineas: list[str]) -> list[Seccion]:
    """Una sección por tabla. El cuerpo empieza en el último apartado "A." antes de la primera tabla
    (el anterior es el índice) y acaba en "Atentamente.". Con más de una tabla en una fracción, cada
    una lleva su número de orden ("B.VI.3", la tarifa de marzo); con una sola, no ("C.II")."""
    primera = next(i for i, l in enumerate(lineas) if UNIDADES_TABLA.match(l))
    inicio = max(i for i in range(primera) if (m := APARTADO.match(lineas[i])) and m.group(1) == "A")
    fin = next(i for i in range(inicio, len(lineas)) if lineas[i].startswith("Atentamente"))
    apartado, fraccion, por_fraccion = None, None, {}
    i = inicio
    while i < fin:
        l = lineas[i]
        if (m := APARTADO.match(l)) and m.group(1) in "ABCDEF":
            nombre = m.group(2) or lineas[i + 1]  # "C." solo: el nombre va en el renglón siguiente
            apartado, fraccion = f"{m.group(1)}. {nombre}", None
            i += 1 if m.group(2) else 2
        elif m := FRACCION.match(l):
            fraccion = m.group(1)
            por_fraccion.setdefault((apartado, fraccion), [])
            if m.group(2):  # "VII.  Tarifa para..." en un renglón
                lineas = lineas[:i] + [m.group(2)] + lineas[i + 1:]
            else:
                i += 1
        elif INICIO_TABLA.match(l):
            if fraccion is None:
                raise ValueError(f"tabla fuera de una fracción: {l[:60]!r}")
            formadas, i = _tabla(lineas, i)
            por_fraccion[(apartado, fraccion)].append(formadas)
        else:
            raise ValueError(f"renglón inesperado en el Anexo 8: {l[:80]!r}")
    salida = []
    for (apartado, fraccion), tablas in por_fraccion.items():
        if not tablas:
            raise ValueError(f"fracción {fraccion} de {apartado!r} sin tablas")
        base = f"{apartado[0]}.{fraccion}"
        for k, t in enumerate(tablas, 1):
            salida.append(Seccion(base if len(tablas) == 1 else f"{base}.{k}", (apartado, f"Fracción {fraccion}"), t))
    return salida


# --- Anexo 29: apartados ----------------------------------------------------------------------------

ROMANOS = ["I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X"]
# "III.", "III.1", "III.2.  Lista de...", "VII.1. Logotipo...": el número y, a veces, el nombre.
ENCABEZADO = re.compile(r"^([IVX]+)\.(?:(\d+)\.?)?(?:\s+(\S.*))?$")
MARCA = re.compile(r"^- (Modificad|Reformad|Adicionad|Derogad)[oa]s?\b", re.I)
# Lo que el SAT pone sobre cada marca para decir qué tocó: "Párrafo", "Numeral 6", "Título de la fracción VII.1."
CABEZA_MARCA = re.compile(r"^(P[aá]rrafos?|Numerale?s?|N[uú]mero|T[ií]tulo|Fracci[oó]n|Apartado|Inciso|Tabla)\b.{0,50}$", re.I)


def _sin_marcas(lineas: list[str]) -> tuple[list[str], list[tuple[int, str, date]]]:
    """Quita las marcas de modificación ("- Modificado por la Primera Modificación al Anexo 29 ...,
    publicada en el DOF el 17 de julio de 2026.") con la línea que dice qué tocaron. Devuelve las
    líneas limpias y, por marca, (posición en las limpias, verbo, fecha de publicación)."""
    salida, marcas, i = [], [], 0
    while i < len(lineas):
        if not MARCA.match(lineas[i]):
            salida.append(lineas[i])
            i += 1
            continue
        nota, j = lineas[i], i + 1
        while fecha_es(nota) is None and j < len(lineas) and j - i < 4:  # una marca larga sigue abajo
            nota += " " + lineas[j]
            j += 1
        if (f := fecha_es(nota)) is None:
            raise ValueError(f"marca sin fecha legible: {nota[:120]!r}")
        if salida and CABEZA_MARCA.match(salida[-1]):
            salida.pop()
        marcas.append((len(salida), MARCA.match(nota).group(1).lower(), f))
        i = j
    return salida, marcas


def apartados(lineas: list[str]) -> tuple[list[Seccion], dict[str, set[date]]]:
    """Una sección por apartado numerado ("II.1", "VI.2") y una por fracción sin apartados, o por el
    texto que va antes del primero ("III", si lo hay). Los encabezados se aceptan solo en orden (el
    siguiente apartado de la fracción, o la siguiente fracción): "I del CFF" o una cita de "IV."
    dentro del texto no abren sección. El cuerpo empieza en la segunda "I." (la primera es el
    índice) y acaba en "Atentamente.". Devuelve también, por sección, las fechas de sus marcas."""
    lineas, marcas = _sin_marcas(lineas)
    primeras = [i for i, l in enumerate(lineas) if (m := ENCABEZADO.match(l)) and m.group(1) == "I" and not m.group(2)]
    if len(primeras) < 2:
        raise ValueError("no se encontró el índice y el cuerpo del Anexo 29")
    inicio = primeras[1]
    fin = next(i for i in range(inicio, len(lineas)) if lineas[i].startswith("Atentamente"))
    cortes = []  # (línea, fracción, apartado o None)
    fraccion, apartado = 0, 0
    for i in range(inicio, fin):
        m = ENCABEZADO.match(lineas[i])
        if not m or m.group(1) not in ROMANOS:
            continue
        f, a = ROMANOS.index(m.group(1)) + 1, int(m.group(2)) if m.group(2) else None
        if (f == fraccion + 1 and a in (None, 1)) or (f == fraccion and a == apartado + 1):
            if f == fraccion + 1 and a == 1:  # "IV.1" sin "IV." antes: no pasa, pero no se pierde la fracción
                cortes.append((i, f, None))
            cortes.append((i, f, a))
            fraccion, apartado = f, a or 0
    secciones, por_seccion = [], {}
    nombres: dict[int, str] = {}
    for k, (i, f, a) in enumerate(cortes):
        sig = cortes[k + 1][0] if k + 1 < len(cortes) else fin
        if a is None:
            nombres[f] = " ".join(lineas[i:i + 2]) if not ENCABEZADO.match(lineas[i]).group(3) else lineas[i]
        cuerpo = lineas[i:sig]
        if a is None and k + 1 < len(cortes) and cortes[k + 1][1] == f and len(cuerpo) <= 2:
            continue  # la fracción solo trae su nombre antes del primer apartado
        id_ = ROMANOS[f - 1] + (f".{a}" if a else "")
        secciones.append(Seccion(id_, (nombres[f],), cuerpo))
        por_seccion[id_] = {fecha for pos, _, fecha in marcas if i <= pos < sig}
    return secciones, por_seccion


def vigor(anio: int, publicado: date) -> date:
    """Un anexo rige con la RMF de su año (1 de enero) o, si se publica después, desde el día
    siguiente a su publicación; mientras tanto sigue el del año anterior (RMF 2026, Transitorio
    Segundo; CFF art. 7). Lo mismo vale para cada modificación, que no trae transitorios propios."""
    return max(date(anio, 1, 1), publicado + timedelta(days=1))


def leer(numero: int, lineas: list[str]) -> tuple[list[Seccion], dict[str, set[date]]]:
    """Secciones del anexo y, por sección, las fechas de sus marcas de modificación."""
    if numero == 8:
        return tarifas(lineas), {}
    if numero == 29:
        return apartados(lineas)
    if numero == 20:
        return estandar(lineas), {}
    raise ValueError(f"no hay segmentador para el Anexo {numero}")


# --- Anexo 20: estándar del CFDI 4.0 y guía de llenado ----------------------------------------------

# Portal técnico del Anexo 20: solo responde por HTTP (R-09). Sus documentos se leen de la caché y
# `tabularium descargar` no los baja hasta pasar por `ciberseguridad`.
PORTAL_20 = "http://omawww.sat.gob.mx/tramitesyservicios/Paginas/documentos/"
# El estándar se publicó con la RMF 2022 (DOF 13-01-2022) y cada RMF prorroga su vigencia (RMF 2024,
# Transitorio Segundo: "Se prorroga la vigencia de [...] los Anexos 15 y 20 de la RMF para 2022").
ANEXO_20 = FuenteAnexo(20, 2022, date(2022, 1, 13), PORTAL_20 + "Anexo20_2022.pdf")
GUIA_20 = PORTAL_20 + "Anexo_20_Guia_de_llenado_CFDI.pdf"

MARCADOR = re.compile(r"^([IVX]+|[A-Z])\.$")
ELEMENTO = re.compile(r"^Elemento:\s*(\S*)")


def _repetidos(nombres: list[str]) -> list[str]:
    """"Impuestos", "Impuestos (2)": el mismo nodo aparece por concepto y por comprobante."""
    vistos: dict[str, int] = {}
    salida = []
    for n in nombres:
        vistos[n] = vistos.get(n, 0) + 1
        salida.append(n if vistos[n] == 1 else f"{n} ({vistos[n]})")
    return salida


def _por_nodo(id_: str, jerarquia: tuple[str, ...], lineas: list[str], cabezas: list[tuple[int, str]]) -> list[Seccion]:
    """Parte un tramo en una sección por nodo (`cabezas`: posición y nombre) más la introducción."""
    if not cabezas:
        return [Seccion(id_, jerarquia, lineas)]
    salida = [Seccion(id_, jerarquia, lineas[:cabezas[0][0]])] if cabezas[0][0] > 1 else []
    nombres = _repetidos([n for _, n in cabezas])
    for k, ((i, _), nombre) in enumerate(zip(cabezas, nombres)):
        fin = cabezas[k + 1][0] if k + 1 < len(cabezas) else len(lineas)
        salida.append(Seccion(f"{id_} {nombre}", jerarquia, lineas[i:fin]))
    return salida


def estandar(lineas: list[str]) -> list[Seccion]:
    """Estándar del CFDI: una sección por fracción y apartado del índice ("I.C", "IV.A", "V"), y en
    los estándares de comprobante ("I.A", "II.A") una por elemento ("I.A Receptor"). El índice va al
    principio; cada entrada se busca en el cuerpo por su título, en orden."""
    i = lineas.index("Contenido") + 1
    entradas, romano = [], None  # (id, título)
    while True:
        m = MARCADOR.match(lineas[i])
        if not m:  # renglón de un título largo o un "a." de tercer nivel: no es entrada
            i += 1
            continue
        j = i + 1
        while j < len(lineas) and not MARCADOR.match(lineas[j]) and not re.match(r"^[a-z]\.$", lineas[j]):
            j += 1
        titulo = " ".join(lineas[i + 1:j])
        if m.group(1) in ROMANOS:
            if entradas and titulo == entradas[0][1]:
                break  # el cuerpo empieza: la primera fracción otra vez
            romano = m.group(1)
            entradas.append((romano, titulo))
        else:
            entradas.append((f"{romano}.{m.group(1)}", titulo))
        i = j
    def plano(t: str) -> str:
        return " ".join(t.split()).casefold()

    def abre(k: int, marca: str, titulo: str) -> bool:
        """El renglón `k` abre la entrada: su marca sola o con el título en el mismo renglón
        ("IV.  Generalidades"), y el título después. El cuerpo cambia mayúsculas ("Comprobantes")."""
        if lineas[k] != marca and not lineas[k].startswith(marca + " "):
            return False
        return plano(" ".join([lineas[k][len(marca):]] + lineas[k + 1:k + 3])).startswith(plano(titulo).rstrip(".")[:40])

    inicio, cortes = i, []
    for id_, titulo in entradas:
        marca = id_.split(".")[-1] + "."
        k = next((k for k in range(inicio, len(lineas)) if abre(k, marca, titulo)), None)
        if k is None:  # el cuerpo retitula alguno ("código de barras" en el índice, "QR" en II.D): la marca sola
            k = next((k for k in range(inicio, len(lineas)) if lineas[k] == marca), None)
        if k is None:
            raise ValueError(f"Anexo 20: no se encontró en el cuerpo {id_} {titulo[:50]!r}")
        cortes.append((k, id_, titulo))
        inicio = k + 1
    fin = next(k for k in range(inicio, len(lineas)) if lineas[k].startswith("Atentamente"))
    salida = []
    for n, (k, id_, titulo) in enumerate(cortes):
        tramo = lineas[k:cortes[n + 1][0] if n + 1 < len(cortes) else fin]
        jerarquia = tuple(f"{c[1]}. {c[2]}" for c in cortes if c[1] == id_.split(".")[0] and c[1] != id_)
        # El esquema XSD completo ("Código Fuente") va después del último elemento: sección aparte.
        cabezas = [(x, m.group(1) if m else "Código fuente") for x, l in enumerate(tramo)
                   if ((m := ELEMENTO.match(l)) and m.group(1)) or l == "Código Fuente"] if id_.endswith(".A") else []
        salida += _por_nodo(id_, jerarquia + (f"{id_}. {titulo}",), tramo, cabezas)
    return salida


PAGINA_GUIA = re.compile(r"^\d+ / \d+$")
NODO = re.compile(r"^Nodo:\s*(\S*)")


def guia(lineas: list[str], nodos: set[str]) -> list[Seccion]:
    """Guía de llenado: "Introducción", las guías del CFDI ("I") y de retenciones ("II") partidas por
    nodo ("I Receptor"), "Glosario", cada apéndice y el control de cambios. `nodos`: los nombres de
    elemento del estándar, para pegar los que la guía parte en dos renglones ("InformacionGlo" + "bal")."""
    lineas = [l for l in lineas if not PAGINA_GUIA.match(l)]
    inicio = next(k for k, l in enumerate(lineas) if l == "Introducción")
    cortes, apendice = [(inicio, "Introducción")], 0
    for k in range(inicio + 1, len(lineas)):
        l = lineas[k]
        if l.startswith("I. Guía de llenado") and len(cortes) == 1:
            cortes.append((k, "I"))
        elif l.startswith("II. Guía de llenado") and len(cortes) == 2:
            cortes.append((k, "II"))
        elif l == "Glosario" and len(cortes) == 3:
            cortes.append((k, "Glosario"))
        elif (m := re.match(r"^Apéndice (\d+)\b", l)) and int(m.group(1)) == apendice + 1 and len(cortes) >= 4:
            apendice += 1  # solo en orden: "Apéndice 6" citado dentro del 7 no abre sección
            cortes.append((k, f"Apéndice {apendice}"))
        elif l.startswith("Control de cambios") and apendice:
            cortes.append((k, "Control de cambios"))
            break
    if [c for _, c in cortes][:4] != ["Introducción", "I", "II", "Glosario"] or cortes[-1][1] != "Control de cambios":
        raise ValueError(f"la guía de llenado cambió de forma: {[c for _, c in cortes]}")
    salida = []
    for n, (k, id_) in enumerate(cortes):
        tramo = lineas[k:cortes[n + 1][0] if n + 1 < len(cortes) else len(lineas)]
        cabezas = []
        if id_ in ("I", "II"):
            for x, l in enumerate(tramo):
                if not (m := NODO.match(l)):
                    continue
                if m.group(1):  # "Nodo: Emisor", "Nodo:Traslados", "Nodo: Receptor En este nodo..."
                    nombre = m.group(1)
                else:
                    sig, otro = tramo[x + 1], tramo[x + 2] if x + 2 < len(tramo) else ""
                    nombre = (sig + otro if sig + otro in nodos else sig.split()[0] if sig.split()[0] in nodos
                              else sig + otro if re.fullmatch(r"[a-z]{1,4}", otro) else sig.split()[0])
                cabezas.append((x, nombre))
        salida += _por_nodo(id_, (tramo[0],), tramo, cabezas)
    return salida
