"""Detección diaria en el DOF (RF-06): qué publicaciones tocan el corpus.

Una petición por día al SIDOF (`/notas/{DD-MM-AAAA}`, las tres ediciones) y un filtro sobre el
título. La respuesta de cada día se guarda en la caché, así que la lista de publicaciones se
reconstruye desde ella como el resto de la base (`publicaciones`). La ficha de la fuente está en
`docs/fuentes.md`, sección 1.
"""
from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta

from .construir import ruta_cache

SIDOF = "https://sidof.segob.gob.mx/dof/sidof/notas/{}"
NOTA_SIDOF = "https://sidof.segob.gob.mx/dof/sidof/notas/nota/{}"
NOTA_DOF = "https://dof.gob.mx/nota_detalle.php?codigo={}&fecha={}"
EDICIONES = {"NotasMatutinas": "matutina", "NotasVespertinas": "vespertina", "NotasExtraordinarias": "extraordinaria"}
ANEXOS_CORPUS = {"8", "20", "29"}  # los demás anexos de la RMF no están en el corpus (plan.md, alcance)
LEYES = {"LISR": "ley del impuesto sobre la renta", "CFF": "codigo fiscal de la federacion",
         "LIVA": "ley del impuesto al valor agregado"}
# Solo decretos que cambian el texto de una ley; "se otorgan estímulos fiscales ... del ISR" no lo toca.
REFORMA = re.compile(r"^(?:(?:fe de erratas|aclaracion) al )?decreto por el que se (?:reforma|adiciona|deroga|expide|abroga)")
RMF = re.compile(r"miscelanea fiscal para (\d{4})")
# "Anexos 4, 5 ... de la RMF", "Primera Modificación al Anexo 29 de la RMF": solo anexos, no reglas.
SOLO_ANEXOS = re.compile(r"^(?:\w+ )?(?:modificacion(?:es)? (?:al|a los) )?anexos?\b")
ANEXO = r"\d+(?:-[a-z]+)?"  # "8", "1-A", "25-Bis"
# Decretos que reforman varias leyes sin nombrarlas en el título (DOF 01-04-2024 tocó el art. 79 de
# la LISR "en materia de pueblos y comunidades indígenas"): se lee el texto de la nota.
OMNIBUS = re.compile(r"diversos ordenamientos|diversas leyes|disposiciones de diversos")
VERBO = re.compile(r"se (?:reforma|adiciona|deroga)")


@dataclass(frozen=True)
class Publicacion:
    cod_nota: int
    publicado_dof: str  # AAAA-MM-DD
    edicion: str
    titulo: str
    documentos: tuple[str, ...]  # ids del corpus que toca: "CFF", "RMF2026", "RMF2026-A8"

    @property
    def url(self) -> str:
        return NOTA_DOF.format(self.cod_nota, date.fromisoformat(self.publicado_dof).strftime("%d/%m/%Y"))


def _plano(texto: str) -> str:
    s = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode().lower()
    return re.sub(r"\s+", " ", s).strip()


def toca(titulo: str, cuerpo: str | None = None) -> tuple[str, ...]:
    """Documentos del corpus que toca una publicación, según su título. Vacío si no toca ninguno.
    `cuerpo`: el texto de la nota, solo para los decretos de diversos ordenamientos (`omnibus`)."""
    t = _plano(titulo)
    if m := RMF.search(t):
        anio = m.group(1)
        documentos = [] if SOLO_ANEXOS.match(t) else [f"RMF{anio}"]
        for lista in re.findall(rf"\banexos? ((?:{ANEXO}(?:, | y |,? y sus? )?)+)", t):
            documentos += [f"RMF{anio}-A{n.upper()}" for n in re.findall(ANEXO, lista) if n in ANEXOS_CORPUS]
        return tuple(dict.fromkeys(documentos))
    if REFORMA.match(t):
        if omnibus(titulo) and cuerpo:
            c = _plano(re.sub(r"<[^>]+>", " ", cuerpo))
            # La ley cuenta si su nombre sigue, a menos de 1,500 caracteres, a un "se reforma(n)".
            return tuple(d for d, nombre in LEYES.items()
                         if any(VERBO.search(c, max(0, m.start() - 1500), m.start()) for m in re.finditer(nombre, c)))
        return tuple(d for d, nombre in LEYES.items() if nombre in t)
    return ()


def omnibus(titulo: str) -> bool:
    t = _plano(titulo)
    return bool(REFORMA.match(t) and OMNIBUS.search(t) and not any(n in t for n in LEYES.values()))


def leer_dia(cuerpo: bytes, fecha: date, nota=None) -> list[Publicacion]:
    """Todas las notas del día que tocan el corpus. Una respuesta sin `messageCode` 200 es un
    error en voz alta (R-07), no un día vacío. `nota(cod_nota)`: texto de una nota (`_nota`)."""
    datos = json.loads(cuerpo)
    if datos.get("messageCode") != 200 or not all(isinstance(datos.get(e), list) for e in EDICIONES):
        raise ValueError(f"SIDOF {fecha}: respuesta inesperada {str(datos)[:200]}")
    salida = []
    for clave, edicion in EDICIONES.items():
        for n in datos[clave]:
            titulo = (n.get("titulo") or "").strip()  # los encabezados de sección vienen sin título
            cuerpo = nota(int(n["codNota"])) if nota and omnibus(titulo) else None
            if titulo and (docs := toca(titulo, cuerpo)):
                salida.append(Publicacion(int(n["codNota"]), fecha.isoformat(), edicion, titulo, docs))
    return salida


def _nota(cod: int, cliente=None) -> str:
    """`cadenaContenido` de una nota; con `cliente`, la baja si no está en la caché."""
    ruta = ruta_cache(NOTA_SIDOF.format(cod))
    if not ruta.exists():
        if cliente is None:
            raise FileNotFoundError(f"falta la nota {cod} del SIDOF en la caché; bájala con `tabularium revisar`")
        cliente.bajar(NOTA_SIDOF.format(cod))
    datos = json.loads(ruta.read_bytes())
    if datos.get("messageCode") != 200 or not isinstance(datos.get("Nota"), dict):
        raise ValueError(f"SIDOF nota {cod}: respuesta inesperada {str(datos)[:200]}")
    return datos["Nota"].get("cadenaContenido") or ""


def _ruta(fecha: date):
    return ruta_cache(SIDOF.format(fecha.strftime("%d-%m-%Y")))


def _completo(fecha: date) -> bool:
    """La copia de la caché sirve si se bajó después de que terminó ese día: antes le pueden faltar
    la edición vespertina o la extraordinaria."""
    meta = _ruta(fecha).with_name(_ruta(fecha).name + ".meta.json")
    if not meta.exists():
        return False
    return datetime.fromisoformat(json.loads(meta.read_text(encoding="utf-8"))["ts"]).date() > fecha


def revisar(fechas: list[date], cliente=None) -> dict:
    """Revisa cada fecha en el SIDOF; las que ya están completas en la caché no se vuelven a pedir."""
    from .descarga import Cliente
    cliente = cliente or Cliente()
    publicaciones, pedidas = [], []
    for f in fechas:
        if not _completo(f):
            cliente.bajar(SIDOF.format(f.strftime("%d-%m-%Y")))
            pedidas.append(f.isoformat())
        publicaciones += leer_dia(_ruta(f).read_bytes(), f, lambda cod: _nota(cod, cliente))
    return {"fechas": len(fechas), "pedidas": pedidas, "publicaciones": [asdict(p) | {"url": p.url} for p in publicaciones]}


def publicaciones() -> list[Publicacion]:
    """Lo detectado en todos los días que hay en la caché, del más viejo al más nuevo."""
    salida = []
    carpeta = _ruta(date.today()).parent
    for ruta in sorted(carpeta.glob("dof_sidof_notas_[0-9][0-9]-[0-9][0-9]-[0-9][0-9][0-9][0-9]")) if carpeta.exists() else []:
        salida += leer_dia(ruta.read_bytes(), datetime.strptime(ruta.name[-10:], "%d-%m-%Y").date(), _nota)
    return sorted(salida, key=lambda p: (p.publicado_dof, p.cod_nota))


def dias(desde: date, hasta: date) -> list[date]:
    return [desde + timedelta(n) for n in range((hasta - desde).days + 1)]

