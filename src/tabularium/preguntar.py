"""`preguntar` (RF-15): respuesta en lenguaje natural con citas verificadas por código, al estilo de Doll.

`buscar` recupera las unidades vigentes en la fecha; de cada una se toma el pasaje que más raíces
de la pregunta tiene. El Baker `tabularium` (Pixilate) redacta con ellos y copia sus citas; el
código busca cada cita, literal, en los pasajes, y de ahí sale su (documento, unidad, versión): el
modelo nunca dice qué cita, solo qué copió. Citar o callar: si una sola cita no aparece después del
reintento, no hay respuesta redactada (R-12). Con el Baker caído, quedan los resultados de `buscar`.
"""
from __future__ import annotations

import logging
import math
import sqlite3
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from . import almacen, lexico
from .fragmentos import partir
from .glosas import BakerCaido, baker

BAKER = "tabularium"
K = 5
PASAJE = 3000  # caracteres por trozo
TROZOS = 2  # por unidad: cinco unidades de 6,000 caracteres caben de sobra en los 32k de contexto del Baker
INTENTOS = 2
MIN_CITA = 12  # "la tasa" aparece en cualquier artículo y no prueba nada
LARGO_MAXIMO = 500  # de la pregunta (RNF-10)
TIEMPO = 180  # segundos de espera al Baker; la primera llamada puede cargar el modelo

registro = logging.getLogger("tabularium.preguntar")


@dataclass(frozen=True)
class Cita:
    texto: str  # lo que copió el modelo
    cita: dict  # la de la unidad donde aparece (RF-10)


@dataclass
class Respuesta:
    texto: str = ""
    citas: list[Cita] = field(default_factory=list)
    callar: bool = False
    descartadas: list[str] = field(default_factory=list)
    intentos: int = 0
    fallo: str | None = None
    pasajes: list[dict] = field(default_factory=list)  # lo recuperado, se muestra siempre


def _plano(texto: str) -> str:
    return " ".join(texto.replace("*", "").split())


def pesos(textos: list[str], terminos: set[str]) -> dict[str, float]:
    """Cuánto vale cada raíz de la pregunta: más mientras menos trozos de lo recuperado la traen.
    "deduccion" sale en casi todos y no distingue; "comput" sí."""
    trozos = [set(lexico.raices(t)) for texto in textos for t in partir(texto, PASAJE)]
    # IDF clásico: una raíz que sale en todos los trozos vale cero.
    return {r: math.log(len(trozos) / df) for r in terminos if (df := sum(r in t for t in trozos))}


def pasaje(texto: str, peso: dict[str, float]) -> str:
    """Los `TROZOS` trozos de la unidad que más pesan por las raíces de la pregunta, en su orden; la
    unidad completa si cabe. Entre trozos no contiguos va "[…]", así que una cita no puede unirlos."""
    if len(texto) <= PASAJE * TROZOS:
        return texto
    trozos = partir(texto, PASAJE)
    mejores = sorted(sorted(range(len(trozos)), key=lambda i: -sum(peso.get(r, 0.0) for r in set(lexico.raices(trozos[i]))))[:TROZOS])
    salida = trozos[mejores[0]]
    for antes, i in zip(mejores, mejores[1:]):
        salida += ("\n" if i == antes + 1 else "\n[…]\n") + trozos[i]
    return salida


def recuperar(con: sqlite3.Connection, consulta: str, fecha: str | None) -> list[dict]:
    unidades = [almacen.articulo(con, r["documento"], r["unidad"], fecha) for r in almacen.buscar(con, consulta, fecha, K)]
    peso = pesos([a["texto"] for a in unidades], set(lexico.consulta(consulta)))
    return [{"cita": a["cita"], "nombre": a["nombre_documento"], "jerarquia": a["jerarquia"],
             "pasaje": pasaje(a["texto"], peso)} for a in unidades]


def contexto(pasajes: list[dict]) -> str:
    return "\n\n".join(f"[Fragmento {i}] {p['cita']['texto']}\n{p['nombre']} > {p['jerarquia']}\n{p['pasaje']}"
                       for i, p in enumerate(pasajes, 1))


def verificar(citas: list[str], pasajes: list[dict]) -> tuple[list[Cita], list[str]]:
    """Cada cita, literal (salvo espacios), en algún pasaje; de ese pasaje sale su unidad y versión."""
    buenas, malas = [], []
    planos = [(_plano(p["pasaje"]), p) for p in pasajes]
    for c in citas:
        buscada = _plano(c)
        origen = next((p for plano, p in planos if buscada in plano), None) if len(buscada) >= MIN_CITA else None
        if origen is None:
            malas.append(c)
        else:
            buenas.append(Cita(c, origen["cita"]))
    return buenas, malas


def _redactar(r: Respuesta, consulta: str, fecha: str, llamar) -> None:
    tarea = f"Fecha de la pregunta: {fecha}\nPregunta: {consulta}"
    with tempfile.TemporaryDirectory(prefix="tabularium-") as carpeta:
        archivo = Path(carpeta) / "fragmentos.txt"  # el Baker lee archivos, nunca contenido pegado
        archivo.write_text(contexto(r.pasajes), encoding="utf-8")
        for r.intentos in range(1, INTENTOS + 1):
            salida = llamar(tarea, str(archivo))
            if not isinstance(salida.get("citas"), list) or not isinstance(salida.get("respuesta"), str):
                raise BakerCaido(f"respuesta fuera de esquema: {sorted(salida)}")
            if salida.get("no_encontrado") or not salida["citas"]:
                r.citas, r.descartadas = [], []
                break
            r.citas, r.descartadas = verificar(salida["citas"], r.pasajes)
            r.texto = salida["respuesta"].strip()
            if r.citas and not r.descartadas and r.texto:
                return
            tarea = (f"Fecha de la pregunta: {fecha}\nPregunta: {consulta}\nEstas citas no aparecen textuales en los "
                     f"fragmentos: {r.descartadas}. Copia cada cita carácter por carácter o marca no_encontrado.")
    r.callar, r.texto, r.citas = True, "", []


def _bake(tarea: str, archivo: str) -> dict:
    return baker("run", BAKER, "-t", tarea, "-f", archivo, timeout=TIEMPO)


def preguntar(con: sqlite3.Connection, consulta: str, fecha: str | None = None, llamar=_bake) -> Respuesta:
    """Lanza ValueError si la pregunta está vacía, es muy larga o la fecha no es válida."""
    consulta = " ".join(consulta.split())
    if not consulta or len(consulta) > LARGO_MAXIMO:
        raise ValueError(f"la pregunta debe tener entre 1 y {LARGO_MAXIMO} caracteres")
    fecha = almacen._fecha(fecha)
    r = Respuesta(pasajes=recuperar(con, consulta, fecha))
    if not r.pasajes:
        r.callar = True
    else:
        try:
            _redactar(r, consulta, fecha, llamar)
        except BakerCaido as e:
            r.fallo = str(e)
    # Solo conteos: la pregunta no se guarda (RNF-10).
    registro.info("preguntar pasajes=%d citas=%d descartadas=%d intentos=%d callar=%s fallo=%s",
                  len(r.pasajes), len(r.citas), len(r.descartadas), r.intentos, r.callar, r.fallo is not None)
    return r


def vigente(con: sqlite3.Connection, c: dict, fecha: str) -> bool:
    """Comprobación independiente de una cita: es la versión vigente de su unidad en la fecha."""
    return con.execute("SELECT 1 FROM versiones WHERE documento = ? AND unidad = ? AND vigente_desde = ? "
                       "AND vigente_desde <= ? AND (vigente_hasta IS NULL OR vigente_hasta > ?)",
                       (c["documento"], c["unidad"], c["vigente_desde"], fecha, fecha)).fetchone() is not None


def evaluar(con: sqlite3.Connection, respondibles: int = 12, callar: int = 8, llamar=_bake) -> dict:
    """Criterio de RF-15 con el conjunto de `docs/preguntas_prueba.md`: ninguna cita inexistente o
    fuera de vigencia, y ningún caso de callar con respuesta redactada."""
    from .evaluacion import leer
    preguntas, casos = leer()
    filas = []
    for texto, fecha, debe_callar in ([(p.texto, p.fecha, False) for p in preguntas[:respondibles]]
                                      + [(c["Pregunta (callar)"], None, True) for c in casos[:callar]]):
        f = almacen._fecha(fecha)
        r = preguntar(con, texto, f, llamar)
        textos = {p["cita"]["documento"] + "\0" + p["cita"]["unidad"]: _plano(p["pasaje"]) for p in r.pasajes}
        malas = [c.texto for c in r.citas if not vigente(con, c.cita, f)
                 or _plano(c.texto) not in textos.get(c.cita["documento"] + "\0" + c.cita["unidad"], "")]
        filas.append({"pregunta": texto, "fecha": f, "debe_callar": debe_callar, "respondio": bool(r.texto),
                      "callo": r.callar, "fallo": r.fallo, "citas": [c.cita["texto"] for c in r.citas],
                      "citas_malas": malas, "descartadas": len(r.descartadas), "respuesta": r.texto})
    return {"filas": filas,
            "citas_malas": sum(len(f["citas_malas"]) for f in filas),
            "callar_con_respuesta": sum(f["debe_callar"] and f["respondio"] for f in filas),
            "respondidas": sum(not f["debe_callar"] and f["respondio"] for f in filas),
            "fallos": sum(f["fallo"] is not None for f in filas)}


def _ok(r: dict) -> bool:
    return r["citas_malas"] == 0 and r["callar_con_respuesta"] == 0 and r["fallos"] == 0


def reporte(r: dict) -> str:
    lineas = [f"{'CALLAR' if f['debe_callar'] else 'RESP.':6} {'respondió' if f['respondio'] else ('falló' if f['fallo'] else 'calló'):9} "
              f"citas={len(f['citas'])} malas={len(f['citas_malas'])} desc={f['descartadas']}  {f['pregunta'][:70]}"
              for f in r["filas"]]
    lineas.append(f"\nRespondidas {r['respondidas']} de {sum(not f['debe_callar'] for f in r['filas'])}; "
                  f"citas inexistentes o fuera de vigencia: {r['citas_malas']}; callar con respuesta: "
                  f"{r['callar_con_respuesta']}; fallos del Baker: {r['fallos']}. RF-15: {'pasa' if _ok(r) else 'NO pasa'}.")
    return "\n".join(lineas)
