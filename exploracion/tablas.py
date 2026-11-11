"""Documentos medidos en la iteración 0 y las tablas que arma el notebook.

Exploración, no código del producto. La segmentación vive en `medicion.py`.
"""
from __future__ import annotations

import re

import pymupdf

from medicion import (comparar, normalizar, segmentar_ley, segmentar_rmf, texto_doc, texto_pdf,
                      texto_rmf, tocados_desde)

LB = "https://www.diputados.gob.mx/LeyesBiblio"
WB = "https://web.archive.org/web"
SAT = "https://www.sat.gob.mx/minisitio/NormatividadRMFyRGCE"
OMA = "http://omawww.sat.gob.mx/tramitesyservicios/Paginas/documentos"
CORTE = "2024-01-01"
LEYES = {  # ley: (texto vigente, copia fechada que sirve de línea base al 2024-01-01)
    "LIVA": (f"{LB}/doc/LIVA.doc", None),  # sin reformas desde el 12-11-2021
    "LISR": (f"{LB}/doc/LISR.doc", f"{WB}/20220404202127id_/{LB}/doc/LISR.doc"),
    "CFF": (f"{LB}/doc/CFF.doc", f"{WB}/20240405093745id_/{LB}/doc/CFF.doc"),
}
RMF = {  # año: (original del DOF, última versión compilada por el SAT)
    2024: (f"{SAT}/documentos2024/rmf/rmf/RMF_2024-29122023.pdf",
           f"{SAT}/documentos2024/rmf/compiladas/"
           "Compilado_Segunda_Modificacion_de_la_Resolucion_Miscelanea_Fiscal_para_2024.pdf"),
    2025: (f"{SAT}/documentos2025/rmf/rmf/RMF_2025-30122024.pdf",
           f"{SAT}/documentos2025/rmf/compiladas/Compilado_6a_Modificacion_RMF2025-17122025.pdf"),
    2026: (f"{SAT}/documentos2026/rmf/rmf/RMF_2026-DOF-28122025.pdf",
           f"{SAT}/documentos2026/rmf/compiladas/"
           "Compilado_Tercera_Modificacion_a_la-Resolucion_Miscelanea_Fiscal_para_2026.pdf"),
}
ANEXOS = {
    "Anexo 20, estándar CFDI 4.0": f"{OMA}/Anexo20_2022.pdf",
    "Anexo 20, guía de llenado": f"{OMA}/Anexo_20_Guia_de_llenado_CFDI.pdf",
    "Anexo 29 de la RMF 2026": f"{SAT}/documentos2026/rmf/anexos/Anexo_29_RMF2026-09012026.pdf",
    "Anexo 5 de la RMF 2026 (cantidades del CFF)": f"{SAT}/documentos2026/rmf/anexos/Anexo-5-RMF-2026_DOF-28122025.pdf",
    "Anexo 8 de la RMF 2026 (tarifas del ISR)": f"{SAT}/documentos2026/rmf/anexos/Anexo-8-RMF-2026_DOF-28122025.pdf",
}
# "- Reformada en la Primera RMRMF para 2026, publicada en el DOF el 09 de julio de 2026."
MARCA_RMF = re.compile(
    r"(Reformad|Adicionad|Derogad)[oa]s? en la (\w+) (?:RMRMF|Resoluci.n de Modificaciones)"
    r"[^\n]*?(?:DOF|Federaci.n) el\s+(\d{1,2} de \w+ de\s+\d{4})", re.I)


def urls() -> list[str]:
    """Todo lo que el notebook necesita tener en la caché."""
    pares = list(LEYES.values()) + list(RMF.values())
    return [u for par in pares for u in par if u] + list(ANEXOS.values()) + [pdf_de(v) for v, _ in LEYES.values()]


def pdf_de(url_doc: str) -> str:
    return url_doc.replace("/doc/", "/pdf/").replace(".doc", ".pdf")


def tabla_pdf_contra_doc(ruta_de) -> list[dict]:
    """Artículos cuyo texto cambia si la ley se parte desde el PDF en vez del `.doc` (R-04)."""
    filas = []
    for ley, (vigente, _) in LEYES.items():
        del_doc = segmentar_ley(texto_doc(ruta_de(vigente)))[0]
        del_pdf = segmentar_ley(texto_pdf(ruta_de(pdf_de(vigente))))[0]
        d = comparar(del_doc, del_pdf)
        filas.append({"ley": ley, "artículos (.doc)": len(del_doc), "artículos (PDF)": len(del_pdf),
                      "con texto distinto": len(d["cambiados"]),
                      "solo en uno de los dos": len(d["nuevos"]) + len(d["quitados"])})
    return filas


def leyes(ruta_de) -> dict[str, dict]:
    """Segmenta las tres leyes. `ruta_de` convierte una URL en su ruta local (`descarga.ruta_cache`)."""
    salida = {}
    for ley, (vigente, base) in LEYES.items():
        articulos, transitorios = segmentar_ley(texto_doc(ruta_de(vigente)))
        salida[ley] = {"articulos": articulos, "transitorios": normalizar(transitorios),
                       "base": segmentar_ley(texto_doc(ruta_de(base)))[0] if base else articulos}
    return salida


def tabla_leyes(seg: dict[str, dict]) -> list[dict]:
    filas = []
    for ley, s in seg.items():
        arts = s["articulos"]
        largos = sorted(len(u.texto) for u in arts)
        filas.append({
            "ley": ley, "artículos": len(arts),
            "derogados": sum(1 for u in arts if len(u.texto) < 70 and "derog" in u.texto.lower()),
            "notas de reforma": sum(len(u.notas) for u in arts),
            "caracteres del cuerpo": sum(largos), "caracteres de transitorios": len(s["transitorios"]),
            "mediana por artículo": largos[len(largos) // 2], "artículo más largo": largos[-1],
        })
    return filas


def tabla_linea_base(seg: dict[str, dict]) -> list[dict]:
    """Artículos que cambiaron después del corte, medidos de dos formas que deben coincidir."""
    filas = []
    for ley, s in seg.items():
        por_nota = tocados_desde(s["articulos"], CORTE)
        todas = tocados_desde(s["articulos"], CORTE, compilaciones=True)
        d = comparar(s["base"], s["articulos"])
        por_diff = set(d["cambiados"]) | set(d["nuevos"]) | set(d["quitados"])
        base = {u.id: u for u in s["base"]}
        filas.append({
            "ley": ley, "artículos": len(s["articulos"]),
            "con nota de cambio posterior al corte": len(por_nota),
            "distintos de la línea base": len(por_diff),
            "nuevos": len(d["nuevos"]),
            "solo compilación de cantidades": len(set(todas) - set(por_nota)),
            "coinciden nota y diff": set(por_nota) == por_diff,
            "publicaciones del DOF": len({f for fs in por_nota.values() for f in fs}),
            "caracteres de las versiones base que cambian": sum(len(base[k].texto) for k in d["cambiados"]),
        })
    return filas


def tabla_decretos(seg: dict[str, dict]) -> list[dict]:
    filas = []
    for ley, s in seg.items():
        por_nota = tocados_desde(s["articulos"], CORTE)
        for fecha in sorted({f for fs in por_nota.values() for f in fs}):
            arts = sorted(k for k, fs in por_nota.items() if fecha in fs)
            filas.append({"ley": ley, "DOF": fecha, "artículos": len(arts), "cuáles": ", ".join(arts)})
    return filas


def rmf(ruta_de) -> dict[int, dict]:
    salida = {}
    for anio, (original, compilada) in RMF.items():
        reglas, resto = segmentar_rmf(texto_rmf(ruta_de(compilada)))
        salida[anio] = {"reglas": reglas, "resto": normalizar(resto),
                        "original": segmentar_rmf(texto_rmf(ruta_de(original)))[0]}
    return salida


def tabla_rmf(seg: dict[int, dict]) -> list[dict]:
    filas = []
    for anio, s in seg.items():
        largos = sorted(len(r.texto) for r in s["reglas"])
        filas.append({
            "RMF": anio, "reglas (original)": len(s["original"]), "reglas (última compilada)": len(largos),
            "reglas con marca de cambio": sum(1 for r in s["reglas"] if MARCA_RMF.search(" ".join(r.lineas))),
            "caracteres de las reglas": sum(largos), "caracteres de transitorios": len(s["resto"]),
            "mediana por regla": largos[len(largos) // 2], "regla más larga": largos[-1],
        })
    return filas


def tabla_modificaciones(seg: dict[int, dict]) -> list[dict]:
    cuenta: dict[tuple, int] = {}
    for anio, s in seg.items():
        for r in s["reglas"]:
            for verbo, cual, fecha in MARCA_RMF.findall(" ".join(r.lineas)):
                clave = (anio, cual.lower(), normalizar(fecha), verbo.lower() + "a")
                cuenta[clave] = cuenta.get(clave, 0) + 1
    return [{"RMF": a, "modificación": c, "DOF": f, "efecto": v, "reglas": n}
            for (a, c, f, v), n in cuenta.items()]


def tabla_anexos(ruta_de) -> list[dict]:
    filas = []
    for nombre, url in ANEXOS.items():
        with pymupdf.open(ruta_de(url)) as pdf:
            textos = [p.get_text() for p in pdf]
        filas.append({"documento": nombre, "páginas": len(textos),
                      "páginas sin texto": sum(1 for t in textos if len(t.strip()) < 50),
                      "caracteres": len(normalizar(" ".join(textos)))})
    return filas


def tabla_corpus(t_leyes: list[dict], t_base: list[dict], t_rmf: list[dict], t_anexos: list[dict]) -> list[dict]:
    """Tamaño del texto del corpus de la v1. Los MB suponen 3 % de caracteres de dos bytes en UTF-8."""
    partes = {
        "Leyes vigentes (cuerpo y transitorios)":
            sum(f["caracteres del cuerpo"] + f["caracteres de transitorios"] for f in t_leyes),
        "Versiones base de los artículos reformados":
            sum(f["caracteres de las versiones base que cambian"] for f in t_base),
        "RMF 2024 a 2026 (última compilada de cada año)":
            sum(f["caracteres de las reglas"] + f["caracteres de transitorios"] for f in t_rmf),
        "Anexos (20, 29, 5 y 8)": sum(f["caracteres"] for f in t_anexos),
    }
    partes["Total"] = sum(partes.values())
    return [{"parte": k, "caracteres": v, "MB aprox.": round(v * 1.03 / 1e6, 2)} for k, v in partes.items()]


def largos_unidades(seg_leyes: dict[str, dict], seg_rmf: dict[int, dict]) -> list[dict]:
    """Largo de cada unidad vigente, para decidir cómo partir el texto al embeber."""
    filas = [{"documento": ley, "unidad": u.id, "caracteres": len(u.texto)}
             for ley, s in seg_leyes.items() for u in s["articulos"]]
    ultimo = max(seg_rmf)
    return filas + [{"documento": f"RMF {ultimo}", "unidad": r.id, "caracteres": len(r.texto)}
                    for r in seg_rmf[ultimo]["reglas"]]


def figura_largos(filas: list[dict]):
    """Distribución del largo de las unidades por documento, en escala logarítmica."""
    import plotly.express as px

    fig = px.box(filas, x="documento", y="caracteres", color="documento", log_y=True, points=False,
                 template="plotly_white", title="Largo de las unidades vigentes por documento",
                 color_discrete_sequence=["#2a78d6", "#1baf7c", "#c98500", "#8356d6"])
    fig.add_hline(y=2000, line_dash="dot", annotation_text="ventana de 512 tokens (unos 2,000 caracteres)")
    fig.update_layout(showlegend=False, yaxis_title="caracteres por unidad (escala log)", xaxis_title="")
    return fig
