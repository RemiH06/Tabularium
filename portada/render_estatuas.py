"""Render de las piezas de la portada en Blender (Pixilate).

Uso, con Blender 4.3 sin interfaz:
  blender -b -P render_estatuas.py -- previa  <carpeta_gltf> <salida>
  blender -b -P render_estatuas.py -- final   <carpeta_gltf> <salida> <vista> [lado_px]
  blender -b -P render_estatuas.py -- empacar <salida_de_final> <estatico/piezas> <lado_px> <calidad> [pieza...]

`previa` dibuja la pieza desde seis direcciones con Workbench para elegir la vista.
`final` saca, con cámara ortográfica y Cycles en la GPU, tres imágenes de la misma
vista: color (pase de color difuso, sin luz), normales en espacio de cámara
(x a la derecha, y arriba, z hacia quien mira, codificadas 0..1) y oclusión
ambiental. El alfa va en las tres. La luz la pone el shader de la página.
`empacar` junta normal y oclusión en una textura WebP por pieza y saca con `tinta.py` la
imagen fija de respaldo (sin WebGL) en claro y oscuro.
"""
import math
import sys
from pathlib import Path

import bpy
import numpy as np
from mathutils import Vector

VISTAS = {  # dirección desde la que mira la cámara, en coordenadas de Blender
    "frente": Vector((0, -1, 0)), "atras": Vector((0, 1, 0)),
    "izq": Vector((-1, 0, 0)), "der": Vector((1, 0, 0)),
    "arriba": Vector((0, 0, 1)), "abajo": Vector((0, 0, -1)),
}


def cargar(carpeta: Path):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(carpeta / "scene.gltf"))
    bpy.context.view_layer.update()  # sin esto, matrix_world aún no trae la raíz del glTF
    mallas = [o for o in bpy.context.scene.objects if o.type == "MESH"]
    # los soportes del escaneo (el cubo de Septimio) son mallas diminutas al lado de la pieza
    mayor = max(len(o.data.polygons) for o in mallas)
    for o in [o for o in mallas if len(o.data.polygons) < mayor * 0.01]:
        mallas.remove(o)
        print("fuera", o.name, len(o.data.polygons))
        bpy.data.objects.remove(o)
    puntos = [o.matrix_world @ Vector(c) for o in mallas for c in o.bound_box]
    bajo = Vector(min(p[i] for p in puntos) for i in range(3))
    alto = Vector(max(p[i] for p in puntos) for i in range(3))
    return mallas, (bajo + alto) / 2, (alto - bajo)


def camara(centro: Vector, medida: Vector, vista: str):
    d = VISTAS[vista]
    cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam"))
    bpy.context.scene.collection.objects.link(cam)
    bpy.context.scene.camera = cam
    largo = medida.length
    cam.location = centro + d * largo * 2
    arriba = "Y" if vista in ("arriba", "abajo") else "Z"
    cam.rotation_euler = (-d).to_track_quat("-Z", arriba).to_euler()
    cam.data.type = "ORTHO"
    # ancho y alto proyectados de la caja, con 4 % de margen
    m = cam.rotation_euler.to_matrix().transposed()  # matrix_world aún no está al día
    ejes = [abs(v) for v in m @ medida]
    cam.data.ortho_scale = max(ejes[0], ejes[1]) * 1.04  # Blender lo aplica al lado mayor
    cam.data.clip_end = largo * 5
    return cam, ejes[0] / ejes[1]


def previa(carpeta: Path, salida: Path):
    _, centro, medida = cargar(carpeta)
    esc = bpy.context.scene
    esc.render.engine = "BLENDER_WORKBENCH"
    esc.display.shading.light = "MATCAP"
    esc.render.resolution_x = esc.render.resolution_y = 360
    for vista in VISTAS:
        cam, _ = camara(centro, medida, vista)
        esc.render.filepath = str(salida / f"{carpeta.name}-{vista}.png")
        bpy.ops.render.render(write_still=True)
        bpy.data.objects.remove(cam)


def _pixeles(ruta: Path) -> np.ndarray:
    img = bpy.data.images.load(str(ruta))
    a = np.array(img.pixels[:], dtype=np.float32).reshape(img.size[1], img.size[0], 4)
    bpy.data.images.remove(img)
    return a


def _guardar(a: np.ndarray, ruta: Path):
    alto, ancho = a.shape[:2]
    img = bpy.data.images.new(ruta.stem, ancho, alto, alpha=True)
    img.pixels[:] = np.clip(a, 0, 1).ravel()
    img.filepath_raw = str(ruta)
    img.file_format = "PNG"
    img.save()


def final(carpeta: Path, salida: Path, vista: str, lado: int):
    _, centro, medida = cargar(carpeta)
    esc = bpy.context.scene
    cam, aspecto = camara(centro, medida, vista)
    esc.render.engine = "CYCLES"
    esc.cycles.device = "GPU"
    prefs = bpy.context.preferences.addons["cycles"].preferences
    prefs.compute_device_type = "CUDA"
    prefs.get_devices()
    for d in prefs.devices:
        d.use = d.type == "CUDA"
    esc.cycles.samples = 64
    esc.render.film_transparent = True
    # el lado mayor mide `lado`; el otro, lo que pida la pieza (sin pixeles vacíos)
    esc.render.resolution_x = round(lado * min(1, aspecto))
    esc.render.resolution_y = round(lado * min(1, 1 / aspecto))
    esc.world = bpy.data.worlds.new("mundo")
    capa = esc.view_layers[0]
    capa.use_pass_diffuse_color = capa.use_pass_normal = capa.use_pass_ambient_occlusion = True

    esc.use_nodes = True
    arbol = esc.node_tree
    arbol.nodes.clear()
    rl = arbol.nodes.new("CompositorNodeRLayers")
    fo = arbol.nodes.new("CompositorNodeOutputFile")
    tmp = salida / "_exr"
    fo.base_path = str(tmp)
    fo.format.file_format = "OPEN_EXR"
    fo.format.color_depth = "32"
    fo.file_slots.clear()
    for nombre, salida_rl in (("color", "DiffCol"), ("normal", "Normal"), ("ao", "AO"), ("alfa", "Alpha")):
        fo.file_slots.new(nombre)
        arbol.links.new(rl.outputs[salida_rl], fo.inputs[nombre])
    esc.render.filepath = str(tmp / "combinado.png")
    bpy.ops.render.render(write_still=True)

    def pase(nombre):
        return _pixeles(next(tmp.glob(f"{nombre}*.exr")))

    alfa = pase("alfa")[..., :1]
    color, ao = pase("color"), pase("ao")
    n = pase("normal")[..., :3]
    # de mundo a cámara: N_cam = R^T · N_mundo, con R la rotación de la cámara
    r = np.array(cam.rotation_euler.to_matrix(), dtype=np.float32)
    n = n @ r  # equivale a (R^T n) por fila
    n /= np.maximum(np.linalg.norm(n, axis=-1, keepdims=True), 1e-6)
    base = f"{carpeta.name}"
    # el color difuso es lineal; la página lo usa en sRGB
    srgb = np.where(color[..., :3] <= 0.0031308, color[..., :3] * 12.92,
                    1.055 * np.power(np.maximum(color[..., :3], 0), 1 / 2.4) - 0.055)
    _guardar(np.concatenate([srgb, alfa], -1), salida / f"{base}-color.png")
    _guardar(np.concatenate([n * 0.5 + 0.5, alfa], -1), salida / f"{base}-normal.png")
    _guardar(np.concatenate([ao[..., :1].repeat(3, -1), alfa], -1), salida / f"{base}-ao.png")
    for f in tmp.glob("*"):
        f.unlink()
    tmp.rmdir()


def _cargar_a(ruta: Path, lado: int) -> np.ndarray:
    """PNG sin conversión de color, con el lado mayor a `lado`, fila 0 arriba."""
    img = bpy.data.images.load(str(ruta))
    img.colorspace_settings.name = "Non-Color"
    f = lado / max(img.size)
    img.scale(round(img.size[0] * f), round(img.size[1] * f))
    a = np.array(img.pixels[:], dtype=np.float32).reshape(img.size[1], img.size[0], 4)[::-1]
    bpy.data.images.remove(img)
    return a


def _webp(a: np.ndarray, ruta: Path, calidad: int) -> float:
    """Guarda RGBA (fila 0 arriba) en WebP y devuelve el error máximo al releerlo, en niveles de 0 a 255."""
    alto, ancho = a.shape[:2]
    img = bpy.data.images.new(ruta.stem, ancho, alto, alpha=True)
    img.colorspace_settings.name = "Non-Color"
    img.pixels[:] = np.clip(a[::-1], 0, 1).ravel()
    img.filepath_raw = str(ruta)
    img.file_format = "WEBP"
    img.save(quality=calidad)
    bpy.data.images.remove(img)
    leida = bpy.data.images.load(str(ruta))
    leida.colorspace_settings.name = "Non-Color"
    b = np.array(leida.pixels[:], dtype=np.float32).reshape(alto, ancho, 4)[::-1]
    bpy.data.images.remove(leida)
    visible = a[..., 3] > 0.5
    return float(np.abs(b - a)[visible].max() * 255)


def empacar(final_dir: Path, salida: Path, lado: int, calidad: int, piezas: list[str]):
    """Por pieza: la textura del shader y las dos imágenes fijas de respaldo (claro y oscuro)."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import tinta
    for ruta in sorted(final_dir.glob("*-normal.png")):
        pieza = ruta.name.removesuffix("-normal.png")
        if piezas and pieza not in piezas:
            continue
        normal = _cargar_a(ruta, lado)
        ao = _cargar_a(final_dir / f"{pieza}-ao.png", lado)
        alfa = normal[..., 3]
        textura = tinta.empacar(normal, ao[..., 0], alfa)
        textura[alfa < 0.01, :3] = (0.5, 0.5, 1.0)  # fuera de la pieza: plano y sin oclusión
        error = _webp(textura, salida / f"{pieza}.webp", calidad)
        print("textura", pieza, textura.shape[1], "x", textura.shape[0], "error máx.", round(error, 1))
        for modo in tinta.MODOS:
            rgb = tinta.sombrear(textura, modo)
            _webp(np.dstack([rgb, np.ones(rgb.shape[:2], np.float32)]), salida / f"{pieza}-{modo}.webp", 82)


if __name__ == "__main__":
    args = sys.argv[sys.argv.index("--") + 1:]
    # absolutas: Blender resuelve las relativas contra el .blend, que aquí no existe
    modo, carpeta, salida = args[0], Path(args[1]).resolve(), Path(args[2]).resolve()
    salida.mkdir(parents=True, exist_ok=True)
    if modo == "previa":
        previa(carpeta, salida)
    elif modo == "empacar":  # carpeta: la salida de `final`; lado, calidad WebP y, si se quiere, piezas
        empacar(carpeta, salida, int(args[3]), int(args[4]), args[5:])
    else:
        final(carpeta, salida, args[3], int(args[4]) if len(args) > 4 else 2048)
