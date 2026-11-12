"""Segmentación de una ley de LeyesBiblio en artículos, transitorios y decretos de reforma.

Un documento de LeyesBiblio trae, en orden: encabezado, cuerpo de la ley, transitorios de la
ley original y, después de "ARTÍCULOS TRANSITORIOS DE DECRETOS DE REFORMA", un bloque por
decreto (título, fecha de publicación, extracto y sus transitorios).

Decisión de Remi (2026-11-12): los transitorios de la ley original son unidades de la ley; los
de cada reforma son unidades de su decreto, porque ahí se define la vigencia de lo que reforman.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, timedelta

SUFIJOS = r"bis|ter|qu[aá]ter|quinquies|sexies|septies|octies|nonies|decies"
# "Artículo 1o.-", "Artículo 1o.-A.-", "Artículo 17-H Bis.-", "Artículo 113-A.", "Artículo 156-Bis.-"
ENCABEZADO = re.compile(
    rf"^Art[ií]culo\s+(\d+[oº]?(?:(?:\.-|-|\s)(?:[A-Z]{{1,2}}|(?i:{SUFIJOS})))*)\s*\.(?:-|\s|$)")
FIN_CUERPO = re.compile(r"^(ART[ÍI]CULOS?\s+)?TRANSITORI[OA]S?$|^DISPOSICI[OÓ]N(ES)?\s+TRANSITORIAS?\b", re.I)
JERARQUIA = re.compile(r"^(T[IÍ]TULO|CAP[IÍ]TULO|SECCI[OÓ]N)\s+\S+", re.I)
NIVELES = ("TITULO", "CAPITULO", "SECCION")
INICIO_DECRETOS = re.compile(r"^ART[ÍI]CULOS\s+TRANSITORIOS\s+DE\s+DECRETOS?\s+DE\s+REFORMA", re.I)
PUBLICADO = re.compile(r"^Publicad[oa] en el Diario Oficial de la Federaci[oó]n el\s+(.+)$", re.I)
EXPEDICION = re.compile(r"publicad[oa] en el Diario Oficial de la Federaci[oó]n el\s+(.+)$", re.I)
SECCION_TRANSITORIA = re.compile(
    r"^(TRANSITORI[OA]S?|DISPOSICI[OÓ]N(?:ES)?\s+(?:TRANSITORIAS?|DE\s+VIGENCIA)\b.*)$", re.I)
# Promulgación y firmas: cierran la última unidad del bloque.
FIRMA = re.compile(r"^(M[eé]xico,|Ciudad de M[eé]xico,|Dado en|En cumplimiento de lo dispuesto|Atentamente)", re.I)

_UNIDADES = ["Primero", "Segundo", "Tercero", "Cuarto", "Quinto", "Sexto", "Séptimo", "Octavo", "Noveno"]
_DECENAS = ["Décimo", "Vigésimo", "Trigésimo", "Cuadragésimo", "Quincuagésimo"]
_CANON = {unicodedata.normalize("NFKD", p).encode("ascii", "ignore").decode().lower(): p
          for p in _UNIDADES + _DECENAS + ["Único"]}
_U = "|".join(_UNIDADES).replace("é", "[eé]")
_D = "|".join(_DECENAS).replace("é", "[eé]")
ORDINAL = re.compile(
    rf"^(?:Art[ií]culo\s+)?((?:{_D})(?:\s+(?:{_U}))?|{_U}|[UÚ]nico)\s*(?:\.-|\.|-|:)", re.I)

ACCION = re.compile(r"reformad|adicionad|derogad|actualizad|compilad|recorrid|reubicad|Fe de erratas|Reforma DOF", re.I)
# Recorre una nota en orden: cada fecha hereda el último verbo que la precede.
VERBO_O_FECHA = re.compile(
    r"(reformad|adicionad|derogad|actualizad|compilad|recorrid|reubicad|erratas)|(\d{2})-(\d{2})-(\d{4})", re.I)
MESES = {m: i for i, m in enumerate(
    "enero febrero marzo abril mayo junio julio agosto septiembre octubre noviembre diciembre".split(), 1)}
FECHA = re.compile(
    r"(\d{1,2}|primero)\s*(?:o\.?|º)?\s+de\s+(" + "|".join(MESES) + r"|setiembre)\s+(?:de|del)\s+(?:a[ñn]o\s+)?(\d{4})",
    re.I)


@dataclass
class Unidad:
    """Artículo o transitorio. `lineas` incluye las notas de la Cámara; `texto` no."""

    id: str
    tipo: str  # "articulo" o "transitorio"
    lineas: list[str] = field(default_factory=list)
    jerarquia: tuple[str, ...] = ()

    @property
    def notas(self) -> list[str]:
        """Notas editoriales de la Cámara ("Párrafo reformado DOF 12-11-2021"): metadatos, no norma."""
        return [l for l in self.lineas if es_nota(l)]

    @property
    def eventos(self) -> set[tuple[date, str]]:
        """Pares (fecha de publicación, verbo) de las notas."""
        pares = set()
        for nota in self.notas:
            verbo = ""
            for m in VERBO_O_FECHA.finditer(nota):
                if m.group(1):
                    verbo = m.group(1).lower()
                else:
                    pares.add((date(int(m.group(4)), int(m.group(3)), int(m.group(2))), verbo))
        return pares

    def reformas(self, desde: date | None = None, hasta: date | None = None) -> set[date]:
        """Fechas de las notas que cambian texto. "Compilada" no: solo vuelve a publicar una cantidad."""
        return {f for f, verbo in self.eventos if verbo != "compilad"
                and (desde is None or f > desde) and (hasta is None or f <= hasta)}

    @property
    def texto(self) -> str:
        return normalizar(" ".join(l for l in self.lineas if not es_nota(l)))


@dataclass
class Decreto:
    titulo: str
    publicado: date
    transitorios: list[Unidad] = field(default_factory=list)

    def entrada_en_vigor(self) -> tuple[date | None, bool]:
        """(fecha general de entrada en vigor, hay excepciones). None si no se reconoce la redacción."""
        con_vigor = [u for u in self.transitorios if re.search(r"entrar[áa]n?\s+en\s+vigor|comenzar[áa]n? a regir", u.texto, re.I)]
        if not con_vigor:
            return None, False
        texto = con_vigor[0].texto
        # Hasta el siguiente punto seguido de mayúscula: "1o. de enero" no corta la oración.
        oracion = re.split(r"\.\s+(?=[A-ZÁÉÍÓÚÑ])", texto[texto.lower().find("vigor"):], maxsplit=1)[0]
        excepciones = len(con_vigor) > 1 or bool(re.search(r"\b(excepto|salvo|excepci[oó]n)\b", oracion, re.I))
        if re.search(r"d[ií]a siguiente", oracion, re.I):
            return self.publicado + timedelta(days=1), excepciones
        if re.search(r"(?:fecha|d[ií]a) de su publicaci[oó]n", oracion, re.I):  # Segunda RMRMF 2026
            return self.publicado, excepciones
        return fecha_es(oracion), excepciones


@dataclass
class Ley:
    expedicion: date
    articulos: list[Unidad]
    transitorios: list[Unidad]
    decretos: list[Decreto]


def es_nota(linea: str) -> bool:
    return "DOF" in linea and len(linea) < 400 and bool(ACCION.search(linea))


def normalizar(texto: str) -> str:
    """Solo toca espacios y marcas de control (RNF-05)."""
    return re.sub(r"\s+", " ", re.sub(r"[\x00-\x08\x0b-\x1f\xa0]", " ", texto)).strip()


def fecha_es(texto: str) -> date | None:
    """Primera fecha escrita en español ("1o. de enero de 2022", "29 de diciembre de 1978")."""
    m = FECHA.search(texto)
    if not m:
        return None
    dia = 1 if m.group(1).lower() == "primero" else int(m.group(1))
    mes = MESES.get(m.group(2).lower(), 9)  # "setiembre"
    return date(int(m.group(3)), mes, dia)


def ordinal(palabras: str) -> str:
    """Forma canónica de un ordinal ("DECIMO PRIMERO" -> "Décimo Primero")."""
    sin_acento = unicodedata.normalize("NFKD", palabras).encode("ascii", "ignore").decode().lower()
    return " ".join(_CANON[p] for p in sin_acento.split())


def segmentar(texto: str) -> Ley:
    lineas = [l.strip() for l in texto.split("\n")]
    expedicion = next((fecha_es(m.group(1)) for l in lineas[:15] if (m := EXPEDICION.search(l))), None)
    if expedicion is None:
        raise ValueError("no se encontró la fecha de publicación de la ley en el encabezado")
    articulos, fin = _cuerpo(lineas)
    if not articulos:
        raise ValueError("no se encontró ningún artículo")
    inicio_decretos = next((i for i in range(fin, len(lineas)) if INICIO_DECRETOS.match(lineas[i])), len(lineas))
    transitorios = _transitorios(lineas[fin:inicio_decretos], prefijo_sin_seccion="Transitorio")
    return Ley(expedicion, articulos, transitorios, _decretos(lineas[inicio_decretos + 1:]))


def _cuerpo(lineas: list[str]) -> tuple[list[Unidad], int]:
    """Artículos del cuerpo y la línea donde empiezan los transitorios."""
    unidades: list[Unidad] = []
    jerarquia: dict[str, str] = {}
    sin_nombre = ""  # nivel cuyo nombre ("Disposiciones generales") viene en la línea siguiente
    for i, linea in enumerate(lineas):
        if unidades and FIN_CUERPO.match(linea):
            return unidades, i
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
            unidades.append(Unidad(normalizar(m.group(1)), "articulo", jerarquia=tuple(jerarquia.values())))
        if unidades:
            unidades[-1].lineas.append(linea)
    return unidades, len(lineas)


def _transitorios(lineas: list[str], prefijo_sin_seccion: str) -> list[Unidad]:
    """Parte una zona de transitorios en unidades por ordinal ("Primero", "Único").

    Cada encabezado de sección ("TRANSITORIOS", "DISPOSICIONES TRANSITORIAS DE LA LEY ...") abre
    una sección; las líneas antes del primer ordinal de una sección forman su propia unidad.
    Las firmas cierran la sección. Fuera de una sección (el extracto del decreto) no se guarda nada.
    """
    unidades: list[Unidad] = []
    etiqueta = None  # None: fuera de una sección
    for linea in lineas:
        if not linea or set(linea) <= set(".…·¨"):  # renglones de puntos que marcan texto omitido
            continue
        if SECCION_TRANSITORIA.match(linea) and len(linea) < 200:
            plana = re.match(r"^TRANSITORI[OA]S?$", linea, re.I)
            etiqueta = prefijo_sin_seccion if plana else normalizar(linea).capitalize()
            unidades.append(Unidad(etiqueta, "transitorio"))
            continue
        if etiqueta is None:
            continue
        if FIRMA.match(linea):
            etiqueta = None
            continue
        m = ORDINAL.match(linea)
        if m:
            separador = " " if etiqueta == prefijo_sin_seccion else ", artículo "
            unidades.append(Unidad(f"{etiqueta}{separador}{ordinal(m.group(1))}", "transitorio"))
        unidades[-1].lineas.append(linea)
    unidades = [u for u in unidades if u.lineas]
    # shortcut: un decreto con dos secciones de mismo nombre y ordinal repetido recibe sufijo " (2)";
    # revisar si aparece en el CFF (iteración 2).
    vistos: dict[str, int] = {}
    for u in unidades:
        vistos[u.id] = vistos.get(u.id, 0) + 1
        if vistos[u.id] > 1:
            u.id = f"{u.id} ({vistos[u.id]})"
    return unidades


def _decretos(lineas: list[str]) -> list[Decreto]:
    """Un bloque por decreto: empieza en el título, la línea anterior a "Publicado en el DOF el ..."."""
    lineas = [l for l in lineas if l]
    inicios = [i - 1 for i, l in enumerate(lineas) if i > 0 and PUBLICADO.match(l)]
    decretos = []
    for ini, sig in zip(inicios, inicios[1:] + [len(lineas)]):
        publicado = fecha_es(PUBLICADO.match(lineas[ini + 1]).group(1))
        if publicado is None:
            raise ValueError(f"fecha ilegible en: {lineas[ini + 1]!r}")
        decretos.append(Decreto(normalizar(lineas[ini]), publicado,
                                _transitorios(lineas[ini + 2:sig], prefijo_sin_seccion="Transitorio")))
    return decretos
