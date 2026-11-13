# Fuentes de Tabularium

Una ficha por fuente, verificada en la iteración 0 (del 10 al 11 de noviembre de 2026). Todo lo que se cita aquí está en `cache/`; la medición se reproduce con `exploracion/medir_corpus.ipynb`.

Cómo se probó: un solo cliente, 2.5 s entre peticiones al mismo host, User-Agent genérico (`Mozilla/5.0 (compatible; legal-corpus-fetcher/0.1)`) y caché local. Fueron 67 peticiones registradas en `cache/_log.jsonl`, con al menos 3 s de separación por host, más un intento por HTTPS al portal del Anexo 20 que no contestó. Ninguna fuente bloqueó ese User-Agent ni pidió autenticación.

| Fuente | Para qué sirve en la v1 | Formato | Estado |
|---|---|---|---|
| [SIDOF](#1-sidof-web-services-del-dof) | Detectar cada día lo que toca el corpus y bajar el texto de decretos y modificaciones | JSON | Funciona, con documentación |
| [DOF, sitio público](#2-dof-sitio-público) | URL de cita y plan B del R-01 | HTML, PDF | Funciona sin `www` |
| [LeyesBiblio](#3-leyesbiblio-cámara-de-diputados) | Texto vigente de LISR, CFF y LIVA, con notas de reforma | DOC, PDF | Funciona |
| [archive.org](#4-archiveorg-wayback-machine) | Línea base al 2024-01-01 | DOC, PDF | Funciona |
| [SAT, minisitio de normatividad](#5-sat-minisitio-de-normatividad-rmf) | RMF de cada año, modificaciones, compiladas y anexos | PDF | Funciona |
| [SAT, portal técnico del Anexo 20](#6-sat-portal-técnico-del-anexo-20) | Estándar, guía de llenado, esquema y catálogos de CFDI | PDF, XSD, XLS | Funciona, solo por HTTP |

Fuera de la v1 y sin verificar en esta iteración: SCJN (Semanario Judicial), INEGI y Banxico, CONASAMI y Congreso de Jalisco.

## 1. SIDOF (web services del DOF)

- **URL base:** `https://sidof.segob.gob.mx/dof/sidof`
- **Documentación:** sí existe. La página `https://sidof.segob.gob.mx/datos_abiertos` enlaza un PDF por servicio (`/datos_abiertos/getPDF/57` notas, `/65` diarios, `/43` documentos, `/61` indicadores). Son la versión 1.0, de diciembre de 2018, y sus ejemplos apuntan al host de pruebas `sidofqa`; el de producción es el de arriba.
- **Formato:** JSON en UTF-8. Todos los métodos son GET.
- **Autenticación:** ninguna.
- **Límites:** no hay ninguno documentado ni se encontró alguno con 24 peticiones. Latencia típica de 0.2 a 5 s.

| Método | Ruta | Devuelve |
|---|---|---|
| Notas por fecha | `/notas/{DD-MM-AAAA}` | Lista de notas del día, separadas por edición |
| Nota por código | `/notas/nota/{codNota}` | La nota con su texto en HTML (`cadenaContenido`) |
| Notas por diario | `/notas/obtenerNotasPorDiario/{codDiario}` | Notas de una edición (no se probó) |
| Diarios por fecha | `/diarios/porFecha/{DD-MM-AAAA}` | Ediciones del día con su `codDiario` y número de páginas |
| Documento Word | `/documentos/doc/{codNota}` | El `.doc` de la nota |
| PDF del diario | `/documentos/pdf/{codDiario}` | La edición completa (no se probó) |

**Ejemplo** (`/notas/07-11-2025`, recortado):

```json
{"messageCode": 200, "response": "OK",
 "NotasMatutinas": [], "NotasExtraordinarias": [],
 "NotasVespertinas": [
  {"codNota": 5772358,
   "titulo": "Decreto por el que se reforman, adicionan y derogan diversas disposiciones del Código Fiscal de la Federación.",
   "fecha": "07-11-2025", "codDiario": 324023, "codSeccion": "UNICA", "pagina": 47,
   "codOrgaUno": "PODER EJECUTIVO", "codOrgaDos": "PRESIDENCIA DE LA REPUBLICA",
   "existeHtml": "S", "existeDoc": "S", "existePdf": "S"}]}
```

**Cómo detectar cambios:** una petición diaria a `/notas/{fecha}` y un filtro sobre `titulo`. La expresión que se probó (sin acentos ni mayúsculas): `impuesto sobre la renta|codigo fiscal de la federacion|impuesto al valor agregado|miscelanea fiscal`.

| Fecha probada | Notas | Coincidencias |
|---|---|---|
| 07-11-2025 (paquete económico 2026) | 125 | Decreto del CFF, en la edición vespertina |
| 05-11-2025 (sin reformas al corpus) | 128 | Ninguna |
| 08-11-2025 (sábado) | 0 | Respuesta 200 con las listas vacías |
| 29-12-2023, 30-12-2024 y 28-12-2025 | 154, 65 y 4 | RMF 2024, 2025 y 2026 con sus anexos |
| 09-07-2026 y 02-10-2026 | 144 y 82 | Primera y tercera modificaciones a la RMF 2026 |
| 09-04-2026 | 92 | Decreto que reforma el art. 141 del CFF |
| 10-11-2026 (el día de la prueba) | 186 | Ninguna; la edición del día ya estaba disponible |

**Hallazgos:**

- Hay que revisar las tres ediciones (matutina, vespertina y extraordinaria). El decreto del CFF y la tercera modificación a la RMF 2026 salieron en la vespertina.
- Algunas notas vienen sin `titulo` (son encabezados de sección). El filtro debe tolerarlo.
- Una fecha inválida devuelve HTTP 500 con un JSON de error, no un 400.
- Para decretos y modificaciones a la RMF, `cadenaContenido` trae el texto completo (150 mil caracteres el decreto del CFF, 47 mil la primera modificación a la RMF 2026).
- Para la RMF anual, `cadenaContenido` es solo un enlace a un PDF en `dof.gob.mx` (`https://dof.gob.mx/2025/SHCP/SHCP_281225_01.pdf`) y el `.doc` trae 213 caracteres. El texto de la RMF hay que tomarlo del SAT o de ese PDF.
- El transitorio con la entrada en vigor viene en el texto: "entrará en vigor el 1 de enero de 2026, salvo lo dispuesto en el artículo 30-B [...] el 1 de abril de 2026". La fecha de la nota es la de publicación, no la de vigencia.

## 2. DOF, sitio público

- **URL:** `https://dof.gob.mx/nota_detalle.php?codigo={codNota}&fecha={DD/MM/AAAA}` para una nota e `https://dof.gob.mx/index.php?year=AAAA&month=MM&day=DD` para el índice del día.
- **Formato:** HTML. **Autenticación:** ninguna. **Límites:** sin datos (2 peticiones).
- **Uso en la v1:** es la URL de la fuente que pide RF-10 en cada cita, porque usa el mismo `codNota` que el SIDOF. También es el plan B del R-01 si el SIDOF deja de responder.
- **Hallazgo:** con `www.dof.gob.mx` falla la verificación TLS (el certificado no corresponde a ese nombre). Hay que usar `dof.gob.mx` sin `www`. No se desactivó la verificación.
- **Ejemplo:** `nota_detalle.php?codigo=5772358&fecha=07/11/2025` devuelve el decreto del CFF (206 KB de HTML, 46 mil caracteres de texto).

## 3. LeyesBiblio (Cámara de Diputados)

- **URL base:** `https://www.diputados.gob.mx/LeyesBiblio`
- **Formato:** HTML en ISO-8859-1 para el índice y las páginas de reformas; cada ley en `.doc` (Word 97 a 2003, binario) y en PDF con texto, generado con Word, a una columna.
- **Autenticación:** ninguna. **Límites:** sin datos (10 peticiones, de 0.6 a 9.5 s).

| Recurso | Ruta | Contenido |
|---|---|---|
| Índice | `/index.htm` | Una fila por ley con su fecha de publicación y la de su última reforma |
| Ley en Word | `/doc/LISR.doc`, `/doc/CFF.doc`, `/doc/LIVA.doc` | Texto vigente, un párrafo por línea |
| Ley en PDF | `/pdf/LISR.pdf`, `/pdf/CFF.pdf`, `/pdf/LIVA.pdf` | El mismo texto, con encabezado en cada página |
| Reformas | `/ref/lisr.htm`, `/ref/cff.htm`, `/ref/liva.htm` | Cada decreto de reforma en PDF y Word |

**Ejemplo** (fila del índice):

```
006 CÓDIGO Fiscal de la Federación   DOF 31/12/1981   DOF 09/04/2026
    ref/cff.htm   pdf/CFF.pdf   doc/CFF.doc   pdf_mov/Codigo_Fiscal_de_la_Federacion.pdf
```

**Estado al 2026-11-10:**

| Ley | Última reforma | Artículos | Derogados | Texto del cuerpo | Transitorios |
|---|---|---|---|---|---|
| LIVA | DOF 12-11-2021 | 79 | 15 | 151 mil caracteres | 171 mil |
| LISR | DOF 01-04-2024 | 236 | 12 | 891 mil | 174 mil |
| CFF | DOF 09-04-2026 | 421 | 84 | 783 mil | 310 mil |

**Cómo detectar cambios:** una sola petición a `/index.htm` y comparar la columna de última reforma de las tres leyes (RF-01). Como respaldo, el encabezado `Last-Modified` de cada `.doc` (el del CFF dice 18 de abril de 2026). La primera página de cada ley repite "Última reforma publicada DOF dd-mm-aaaa".

**Hallazgos:**

- Las notas de reforma vienen dentro del texto, en su propio párrafo: "Párrafo reformado DOF 12-11-2021", "Artículo adicionado DOF 07-11-2025", "Fracción derogada DOF ...". Son anotaciones de la Cámara, no texto de la norma: se guardan como metadatos y se quitan del texto.
- En el CFF hay notas de cantidades con dos verbos: "Actualizada DOF 29-12-2023" cambia el monto; "Compilada DOF 30-12-2024" solo dice que el Anexo 5 de la RMF volvió a publicar la misma cantidad. Diez artículos tienen notas posteriores a 2024 que son solo compilaciones y su texto no cambió.
- **El `.doc` es mejor fuente que el PDF.** Partiendo los dos, los artículos coinciden en número (79, 236 y 421), pero el texto difiere en 5, 23 y 6 artículos (LIVA, LISR y CFF) por culpa del PDF. Los renglones cortados hacen que una nota quede partida en dos líneas, que un renglón que empieza con "Sección", "Capítulo II," o "Título II de esta Ley" parezca un encabezado, que el nombre largo de un capítulo se cuele en el artículo anterior, o que "32-A" salga como "32- A".
- El `.doc` se lee sin LibreOffice ni Word: su tabla de piezas se recorre con `olefile` (unas 40 líneas en `exploracion/medicion.py`). Hay que quitar los campos de Word (`INCLUDEPICTURE`).
- Algunas fórmulas son imágenes pegadas (por ejemplo, en el art. 20-Ter del CFF) y se pierden en cualquier extracción de texto.
- LeyesBiblio no anota todas las reformas viejas: el art. 141 del CFF no traía ninguna nota antes de 2025.
- La página de reformas del CFF lista también las "Actualizaciones de cantidades" (Anexo 5 de la RMF) como entradas propias, con su PDF y Word.
- El texto de la LISR no integra la tarifa actualizada del art. 152; esa vive en el Anexo 8 de la RMF.

## 4. archive.org (Wayback Machine)

- **URL de consulta (API CDX):** `https://web.archive.org/cdx/search/cdx?url=diputados.gob.mx/LeyesBiblio/doc/CFF.doc&output=json&from=2021&filter=statuscode:200&collapse=digest&fl=timestamp,digest,length,mimetype`
- **URL de una captura sin modificar:** `https://web.archive.org/web/{timestamp}id_/{url original}`
- **Formato:** JSON (lista de listas) para el CDX; el archivo original para la captura.
- **Autenticación:** ninguna. **Límites:** archive.org pide moderación sin dar una cifra; se hicieron 9 peticiones.

**Ejemplo** (CDX de `doc/CFF.doc`):

```json
[["timestamp", "digest", "length", "mimetype"],
 ["20220404202138", "52BZEGKREL6B466LJH7B4FAW56QUBX5T", "362759", "application/msword"],
 ["20230307183930", "KK7Y7RNYHS3SYGIFR3AZBJQ4CVWXUNMA", "441115", "application/msword"],
 ["20240405093745", "4EYRJEH2XTGKCCPFWZRUY6ILL5EJ4NWU", "398284", "application/msword"]]
```

**Capturas útiles para la línea base:**

| Ley | Captura | Qué contiene | Uso |
|---|---|---|---|
| LIVA | No hace falta | El texto vigente es el del 12-11-2021 | Línea base igual al vigente |
| LISR | `doc/LISR.doc` del 2022-04-04 | Última reforma DOF 12-11-2021 | Línea base (no hubo reformas entre esa fecha y el 01-04-2024) |
| CFF | `doc/CFF.doc` del 2024-04-05 | Última reforma DOF 12-11-2021 y cantidades DOF 29-12-2023 | Línea base |
| CFF | `pdf/CFF.pdf` de 2025-04-04, 2025-10-18, 2025-11-26, 2026-01-30 y 2026-04-20 | Una versión después de casi cada publicación | Verificar las versiones intermedias |
| LISR | `pdf/LISR.pdf` del 2023-10-10 y del 2024-06-17 | Antes y después de la reforma del 01-04-2024 | Respaldo |

**Cómo detectar cambios:** no aplica; es un archivo histórico. Las capturas se bajan una vez y se guardan en la caché, que es la fuente de verdad.

**Hallazgo:** del `.doc` hay pocas capturas (3 del CFF, 1 de LISR y 1 de LIVA); del PDF hay muchas más (16 del CFF). Comparar un PDF contra un `.doc` mete ruido (ver ficha 3), así que las versiones intermedias conviene compararlas PDF contra PDF.

## 5. SAT, minisitio de normatividad (RMF)

- **URL base:** `https://www.sat.gob.mx/minisitio/NormatividadRMFyRGCE/`
- **Páginas:** `normatividad_rmf_rgce2026.html`, `...2025.html`, `...2024.html` y `...2023.html`. Son HTML estático con unos 280 enlaces cada una; `index.html` redirige al año en curso.
- **Formato:** PDF con texto (generado con Word, a una columna) y algunos ZIP. No hay Word.
- **Autenticación:** ninguna. **Límites:** sin datos (16 peticiones). Los archivos son grandes: la RMF 2024 compilada pesa 171 MB y tardó 158 s.

| Qué | Ruta de ejemplo |
|---|---|
| RMF original | `documentos2026/rmf/rmf/RMF_2026-DOF-28122025.pdf` |
| Modificación | `documentos2025/rmf/rmf/5a_RMRMF_2025-22102025-DOF.pdf` |
| Compilada tras cada modificación | `documentos2026/rmf/compiladas/Compilado_Tercera_Modificacion_a_la-Resolucion_Miscelanea_Fiscal_para_2026.pdf` |
| Anexo | `documentos2026/rmf/anexos/Anexo-8-RMF-2026_DOF-28122025.pdf` |
| Versión anticipada (aún no publicada en el DOF) | `documentos2026/rmf/anticipadas/5aRM_RMF2026-Primera_version_anticipada-05112026.pdf` |

Los nombres de archivo no siguen un patrón fijo: hay que leerlos del HTML de cada año, no construirlos.

**Ejemplo** (regla en la versión compilada de 2026):

```
Reanudación y actualización para tributar en el Régimen Simplificado de Confianza
3.13.2.
Para los efectos de los artículos 113-E y 113-H, fracción II de la Ley del ISR y 29, fracción VI
del Reglamento del CFF, los contribuyentes personas físicas que reanuden actividades, podrán [...]
```

**Medición:**

| RMF | Publicada | Modificaciones | Reglas (original) | Reglas (última compilada) | Reglas con marca de cambio | Texto |
|---|---|---|---|---|---|---|
| 2024 | DOF 29-12-2023 | 3 (compiladas la 1a y la 2a) | 1,122 | 1,110 | 49 | 2.4 millones de caracteres |
| 2025 | DOF 30-12-2024 | 6 (falta la compilada de la 5a) | 1,150 | 1,173 | 128 | 2.4 millones |
| 2026 | DOF 28-12-2025 | 3 publicadas; 4a y 5a en versión anticipada | 1,184 | 1,191 | 38 | 2.5 millones |

**Cómo detectar cambios:** el DOF avisa (ficha 1: el título dice "Resolución de Modificaciones a la Resolución Miscelánea Fiscal"). Después se relee el HTML del año y se compara la lista de enlaces; la página y cada PDF traen `Last-Modified`. Desde el 2026-11-12 lo hace `minisitio.py`: `tabularium descargar` baja la página del año en curso y la del anterior (en diciembre, también la del siguiente) y las fuentes de la RMF y de los anexos 8 y 29 salen del texto de cada enlace, que trae el ordinal y la fecha: "Compilado 3a. RM RMF 2026 (publicado el 02 de octubre de 2026)".

**Hallazgos:**

- La compilada marca cada cambio dentro del texto: "- Reformada en la Primera RMRMF para 2026, publicada en el DOF el 09 de julio de 2026." Con esas marcas se sabe qué reglas tocó cada modificación sin comparar textos.
- **La numeración de las reglas no es estable entre años.** "Plazos para la cancelación de CFDI" es la 2.7.1.47 en 2024 y la 2.7.1.46 en 2025; la constancia de situación fiscal es la 2.4.10 en 2024 y 2025 y la 2.4.9 en 2026. La unidad tiene que ser (RMF del año, regla).
- Las reglas tienen de 2 a 4 niveles ("1.9.", "3.13.2." y "2.7.1.21."). El número va solo en una línea, con el título en la anterior. Una referencia cortada por el salto de renglón se ve igual que un encabezado.
- El PDF original (formato del DOF) y el compilado no coinciden carácter por carácter: cambian los encabezados de página y el corte de renglones. Para comparar versiones hay que limpiar eso primero; en la iteración 0 no se hizo.
- La tercera modificación de 2024 (DOF 12-12-2024) nunca se compiló y la quinta de 2025 solo aparece dentro de la compilada de la sexta.
- En la compilada de 2024 el título de una regla sale pegado a las referencias de la anterior ("CFF 27, RCFF 28Cédula de identificación fiscal...").
- El Anexo 20 de CFDI no está aquí: el "Anexo 20" que lista el minisitio es el de las Reglas de Comercio Exterior. El anexo de CFDI que sí se publica cada año es el 29 ("Disposiciones complementarias para los PCCFDI y los CFDI", 76 mil caracteres en 2026).
- Anexo 5 (cantidades del CFF, 46 mil caracteres) y Anexo 8 (tarifas del ISR, 40 mil) se publican con la RMF.
- **El texto del enlace puede mentir** (2026-11-12): en la página de 2024 la compilada de la 1a modificación del Anexo 30 dice "Compilado 1a. Modificación Anexo 29 RMF 2024". `minisitio.py` pide que el nombre del archivo también diga el número del anexo, y dos enlaces distintos para la misma pieza fallan en voz alta.
- La página es UTF-8, sin `charset` declarado.
- Una modificación sale primero en versiones anticipadas (`anticipadas/`), luego publicada (`rmf/rmf/`) y días o semanas después compilada. Al 2026-11-12, la Cuarta RMRMF 2026 (DOF 30-10-2026) solo tiene sus anticipadas, y la Segunda modificación del Anexo 29 (DOF 06-11-2026) no aparece.

## 6. SAT, portal técnico del Anexo 20

- **URL:** `http://omawww.sat.gob.mx/tramitesyservicios/Paginas/anexo_20.htm`
- **Formato:** HTML con enlaces a PDF, XSD, XSLT y XLS.
- **Autenticación:** ninguna. **Límites:** sin datos (4 peticiones).

| Documento | Ruta | Tamaño |
|---|---|---|
| Estándar del CFDI 4.0 (Anexo 20, DOF 13-01-2022) | `.../Paginas/documentos/Anexo20_2022.pdf` | 6.7 MB, 131 páginas, 210 mil caracteres; 6 páginas sin texto |
| Guía de llenado | `.../Paginas/documentos/Anexo_20_Guia_de_llenado_CFDI.pdf` | 1.5 MB, 123 páginas, 183 mil caracteres |
| Esquema | `http://www.sat.gob.mx/sitio_internet/cfd/4/cfdv40.xsd` | 51 KB |
| Catálogos | `.../Paginas/documentos/catCFDI_V_4_20261106.xls` | 48.8 MB |
| Matriz de errores | `.../Paginas/documentos/MatrizDeErrores_CFDI_v40_20260325.xls` | No se bajó |

**Ejemplo** (estándar, nodo Receptor):

```
DomicilioFiscalReceptor
Descripción  Atributo requerido para registrar el código postal del domicilio fiscal del receptor del comprobante.
Uso requerido   Tipo Base xs:string   Longitud 5   Patrón [0-9]{5}
```

**Cómo detectar cambios:** `Last-Modified` de la página (6 de noviembre de 2026) y de cada documento. Los catálogos y la matriz de errores llevan la fecha en el nombre del archivo, así que un nombre nuevo en el HTML ya es un cambio.

**Hallazgos:**

- **Solo responde por HTTP.** La versión HTTPS no contestó (tiempo de espera agotado). Sin TLS no hay garantía de integridad: conviene guardar el hash de cada descarga y revisarlo con `ciberseguridad` antes de automatizar.
- El Anexo 20 no se vuelve a publicar cada año: el estándar vigente es el del DOF del 13 de enero de 2022. Lo que sí cambia seguido son la guía de llenado (enero de 2026) y los catálogos (noviembre de 2026).
- Los catálogos son tablas (claves de producto, códigos postales), no texto normativo. No conviene meterlos al corpus de búsqueda.
