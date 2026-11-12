"""Lector de .doc binarios (Word 97 a 2003), el formato en que LeyesBiblio publica las leyes.

Recorre la tabla de piezas del documento en vez de convertirlo con LibreOffice: da párrafos
enteros (el PDF corta renglones) y no pide instalar nada pesado en la Pi.
"""
from __future__ import annotations

import re
import struct
from pathlib import Path

import olefile


# Tarifas y fórmulas que LeyesBiblio pega como imagen (R-03; ni el .doc ni el PDF traen su texto).
# Se marcan para que ninguna cita las omita en silencio.
MARCA_IMAGEN = "[imagen en la fuente: tabla o fórmula sin texto en este corpus]"


def texto_doc(ruta: Path) -> str:
    """Texto principal del documento, un párrafo por línea."""
    if not olefile.isOleFile(str(ruta)):
        raise ValueError(f"{ruta} no es un .doc de Word 97 a 2003")
    with olefile.OleFileIO(str(ruta)) as ole:
        try:
            wd = ole.openstream("WordDocument").read()
            flags = struct.unpack_from("<H", wd, 0x0A)[0]
            tabla = ole.openstream("1Table" if flags & 0x0200 else "0Table").read()
        except OSError as e:
            raise ValueError(f"{ruta}: falta un flujo de Word ({e})") from e
    try:
        texto = _piezas(wd, tabla)
    except (struct.error, IndexError) as e:
        raise ValueError(f"{ruta}: tabla de piezas ilegible ({e})") from e
    # Campos de Word: \x13 instrucción \x14 resultado \x15. Se quita la instrucción (por ejemplo,
    # INCLUDEPICTURE de una fórmula pegada como imagen) y se conserva el resultado.
    previo = None
    while previo != texto:
        previo = texto
        texto = re.sub(r"\x13[^\x13\x14\x15]*(?:\x14|\x15)", "", texto)
    texto = texto.replace("\x15", "").replace("\x01", MARCA_IMAGEN)  # \x01: objeto o imagen incrustada
    return texto.replace("\r", "\n").replace("\x0c", "\n").replace("\x07", "\t")


def _piezas(wd: bytes, tabla: bytes) -> str:
    fc_clx, lcb_clx = struct.unpack_from("<II", wd, 0x01A2)
    clx = tabla[fc_clx:fc_clx + lcb_clx]
    i = 0
    while clx[i] == 0x01:  # bloques Prc: formato, sin texto
        i += 3 + struct.unpack_from("<H", clx, i + 1)[0]
    if clx[i] != 0x02:
        raise ValueError("no se encontró la tabla de piezas (Pcdt)")
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
    return "".join(partes)[:ccp_text]
