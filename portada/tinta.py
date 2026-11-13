"""Sombreado de la portada en numpy: la referencia del shader de `estatico/portada.js`.

La pieza se imprime en una tinta con trama de puntos a 15°. En claro la tinta es la sombra y el
papel es el fondo de la página; en oscuro la tinta es la luz. Sirve para la imagen fija de quien
no tiene WebGL y para comprobar que el shader dice lo mismo. Si cambia uno, cambia el otro.
"""
import numpy as np

MODOS = {
    "claro": {"papel": "#EEEBE4", "tinta": "#A54027", "hondo": "#1E1A17"},
    "oscuro": {"papel": "#171816", "tinta": "#D66C51", "hondo": "#ECE8DF"},
}
LUZ = (-0.55, 0.55, 0.62)  # arriba a la izquierda, hacia quien mira: la del respaldo


def hexa(c: str) -> np.ndarray:
    return np.array([int(c[i:i + 2], 16) / 255 for i in (1, 3, 5)], np.float32)


def empacar(normal: np.ndarray, ao: np.ndarray, alfa: np.ndarray) -> np.ndarray:
    """RGBA de la textura: normal x e y (z sale de ellas en el shader), oclusión y alfa, en 0..1."""
    return np.dstack([normal[..., 0], normal[..., 1], ao, alfa]).astype(np.float32)


def sombrear(textura: np.ndarray, modo: str, luz=LUZ, celda: float = 5.0) -> np.ndarray:
    """RGB de la pieza sobre el papel. `textura` como la deja `empacar`, fila 0 arriba."""
    nx, ny = textura[..., 0] * 2 - 1, textura[..., 1] * 2 - 1
    ao, alfa = textura[..., 2], textura[..., 3]
    n = np.dstack([nx, ny, np.sqrt(np.clip(1 - nx * nx - ny * ny, 0, 1))])
    luz = np.array(luz, np.float32) / np.linalg.norm(luz)
    lam = np.clip(n @ luz, 0, 1)
    v = (0.10 + 0.90 * lam) * (1 - 0.65 * (1 - ao))
    claro = modo == "claro"
    tono = np.clip((1 - v - 0.28) / 0.52, 0, 1) if claro else np.clip((v - 0.18) / 0.5, 0, 1)
    # trama a 15°, con y hacia arriba como en el shader
    yy, xx = np.mgrid[0:v.shape[0], 0:v.shape[1]].astype(np.float32)
    yy = v.shape[0] - 1 - yy
    a = np.deg2rad(15)
    u = (xx * np.cos(a) + yy * np.sin(a)) / celda
    w = (-xx * np.sin(a) + yy * np.cos(a)) / celda
    dist = np.hypot(u - np.round(u), w - np.round(w))
    punto = np.clip((np.sqrt(tono) * 0.75 - dist) * celda + 0.5, 0, 1)
    if claro:  # pliegues hondos en tinta negra
        hondo = np.clip((0.30 - ao) / 0.12, 0, 1) * np.clip((1 - v - 0.6) / 0.2, 0, 1)
    else:      # brillos en hueso
        hondo = np.clip((lam - 0.9) / 0.06, 0, 1) * np.clip((ao - 0.8) / 0.1, 0, 1)
    m = {k: hexa(c) for k, c in MODOS[modo].items()}
    c = m["papel"] + (m["tinta"] - m["papel"]) * punto[..., None]
    c = c + (m["hondo"] - c) * hondo[..., None]
    return m["papel"] + (c - m["papel"]) * alfa[..., None]
