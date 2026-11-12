![Made with Python](https://forthebadge.com/images/badges/made-with-python.svg)
![SQLite](https://img.shields.io/badge/-SQLite-003B57?style=for-the-badge&logo=sqlite&logoColor=white)

```ascii
████████╗ █████╗ ██████╗ ██╗   ██╗██╗      █████╗ ██████╗ ██╗██╗   ██╗███╗   ███╗
╚══██╔══╝██╔══██╗██╔══██╗██║   ██║██║     ██╔══██╗██╔══██╗██║██║   ██║████╗ ████║
   ██║   ███████║██████╔╝██║   ██║██║     ███████║██████╔╝██║██║   ██║██╔████╔██║
   ██║   ██╔══██║██╔══██╗██║   ██║██║     ██╔══██║██╔══██╗██║██║   ██║██║╚██╔╝██║
   ██║   ██║  ██║██████╔╝╚██████╔╝███████╗██║  ██║██║  ██║██║╚██████╔╝██║ ╚═╝ ██║
   ╚═╝   ╚═╝  ╚═╝╚═════╝  ╚═════╝ ╚══════╝╚═╝  ╚═╝╚═╝  ╚═╝╚═╝ ╚═════╝ ╚═╝     ╚═╝

       by RemLam (@RemiH06)          version 0.1.0
```

![AGPL-3.0](https://img.shields.io/badge/License-AGPL--3.0-blue.svg?style=for-the-badge)

### Descripción general

**Tabularium** junta en un solo corpus versionado las leyes fiscales de México y las sirve por MCP, con una regla: cada resultado lleva su cita (documento, artículo, fecha de vigencia, decreto del DOF y URL de la fuente), o no hay resultado. Cada artículo se guarda con su vigencia y el decreto que lo reformó, y una versión nunca se sobrescribe, porque las preguntas fiscales son por ejercicio.

El nombre viene del *Tabularium*, el archivo oficial de Roma en el Capitolio (78 a. C.), donde se guardaban leyes, decretos y registros del erario.

El repo no trae texto legal: los documentos se bajan de las fuentes oficiales (LeyesBiblio de la Cámara de Diputados, copias fechadas de archive.org) a una caché local, y la base se regenera desde ahí.

```diff
- En desarrollo: por ahora cubre la LIVA, la LISR y el CFF desde el 2024-01-01, con búsqueda solo por palabras.
- No sustituye a un abogado o contador que firme.
```

## Instalación

1. Instala [uv](https://docs.astral.sh/uv/).
2. Clona el repo y sincroniza el entorno:

```bash
cd Tabularium
uv sync
uv run pytest
```

3. Baja las leyes a la caché `cache/` y construye la base:

```bash
uv run tabularium descargar --construir
uv run tabularium servir
```

4. Registra el servidor en Claude Code:

```bash
claude mcp add --transport http tabularium http://127.0.0.1:8061/mcp
```

## Argumentos de ejecución

- `tabularium descargar [--construir] [--db RUTA]` revisa el índice de LeyesBiblio y baja solo las leyes cuya fecha de última reforma cambió (las copias base de archive.org, una sola vez). Con `--construir`, regenera la base si bajó algo.
- `tabularium construir [--db RUTA] [--sin-vectores]` regenera la base desde la caché. La construye en un archivo temporal y la cambia de golpe, así que el servidor nunca ve una base a medias.
- `tabularium evaluar [-k 5] [--json] [--db RUTA]` mide recall@k con las preguntas de `docs/preguntas_prueba.md`, contra la unidad y contra la versión vigente.
- `tabularium servir` levanta el servidor MCP (HTTP streamable) en `/mcp`.
- Variables de entorno: `TABULARIUM_DB` (por defecto `data/tabularium.db`), `TABULARIUM_CACHE` (`cache`), `TABULARIUM_HOST` (`127.0.0.1`) y `TABULARIUM_PUERTO` (`8061`).

## Funcionalidades

- Lectura directa del `.doc` de LeyesBiblio (tabla de piezas de Word 97), sin LibreOffice: párrafos enteros, sin los renglones cortados del PDF.
- Segmentación en artículos con su jerarquía (título, capítulo, sección). Las notas de reforma de la Cámara van como metadatos, no como texto de la norma.
- Transitorios como unidades propias: los de la ley original son de la ley; los de cada reforma, de su decreto (`DOF-2024-04-01`).
- Versiones por vigencia: la fecha de entrada en vigor sale del transitorio del decreto, no de su fecha de publicación, y las dos se guardan por separado. Las excepciones (un artículo que rige después que el resto del decreto) van en una tabla con su fuente.
- Versiones intermedias que ninguna copia conserva (el art. 141 del CFF de enero a abril de 2026), reconstruidas desde el decreto, marcadas como reconstruidas y verificadas contra una copia en PDF que la construcción no usa.
- Disparadores de SQLite que impiden sobrescribir o borrar una versión.
- Descarga respetuosa: un cliente, pausa de 2.5 s por host, User-Agent genérico, escritura atómica y registro de cada petición.
- Herramientas MCP: `articulo(documento, unidad, fecha)`, `versiones(documento, unidad)` y `buscar(consulta, fecha)`, híbrida: BM25 (FTS5) sobre raíces en español (Snowball), sin palabras vacías y con siglas (CFDI, RFC, RESICO), más embeddings de bge-m3 cuantizado a int8 (ONNX), fusionados por rango. Un artículo pedido por número y ley ("art. 27 LISR") sale primero. En una Raspberry Pi 5 responde en menos de 150 ms.
- Caché de vectores por hash del texto: reconstruir la base solo embebe lo que cambió.

## Funcionalidades futuras

- Resolución Miscelánea Fiscal, anexos de CFDI y grafo de referencias entre artículos.
- Revisión diaria del DOF y *Novellae*: notas de parche por reforma, con diff literal y etiquetas de efecto.

## Autoría

por RemLam ([@RemiH06](https://github.com/RemiH06))
