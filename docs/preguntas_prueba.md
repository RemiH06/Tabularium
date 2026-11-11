# Preguntas de prueba (borrador)

Conjunto para RNF-06: recall@5 de al menos 0.85 sobre 40 preguntas con unidad esperada y fecha. Borrador de la iteración 0 (2026-11-10); Remi lo revisa antes de usarlo en la iteración 2.

## Cómo se armó

- Cada unidad esperada se comprobó contra el corpus segmentado en `exploracion/`: la unidad existe en la versión que corresponde a la fecha y su texto contiene lo que se pregunta. Las 40 pasan.
- **Fecha** es la fecha de consulta (`buscar(consulta, fecha)`). El sistema debe devolver la versión vigente ese día.
- **Versión esperada** es la fecha del DOF de la última reforma de esa unidad dentro de la versión que debe devolverse, tomada de las notas de la Cámara ("Párrafo reformado DOF ..."). "Sin nota de reforma" significa que el texto no trae ninguna nota. Para la RMF es la fecha de publicación de la resolución del año; ninguna de las seis reglas elegidas trae marca de modificación.
- Tipos: **exacta** (se pide por número, prueba BM25), **conceptual** (lenguaje natural, prueba embeddings) y **temporal** (la misma unidad en dos fechas con textos distintos, prueba RF-04).
- Reparto: 12 de LISR, 14 de CFF, 6 de LIVA, 6 de RMF y 2 de anexos de CFDI. Once temporales.

## Las 40 preguntas

| # | Tipo | Pregunta | Documento | Unidad esperada | Fecha | Versión esperada (DOF) |
|---|---|---|---|---|---|---|
| 1 | conceptual | ¿Qué tasa de ISR pagan las personas morales sobre su resultado fiscal? | LISR | art. 9 | 2026-11-10 | sin nota de reforma |
| 2 | exacta | art. 27 fracción V LISR | LISR | art. 27 | 2026-11-10 | 2021-11-12 |
| 3 | conceptual | ¿Qué gastos no puede deducir una persona moral? | LISR | art. 28 | 2025-03-15 | 2021-11-12 |
| 4 | conceptual | ¿Qué deducciones personales puede aplicar una persona física en su declaración anual? | LISR | art. 151 | 2026-04-30 | 2021-11-12 |
| 5 | conceptual | ¿Hasta qué monto de ingresos puede una persona física tributar en el Régimen Simplificado de Confianza? | LISR | art. 113-E | 2026-11-10 | 2021-11-12 |
| 6 | conceptual | ¿Una persona física en RESICO tiene que presentar declaración anual? | LISR | art. 113-F | 2025-04-01 | 2021-11-12 |
| 7 | conceptual | ¿Qué parte del aguinaldo está exenta de ISR? | LISR | art. 93 | 2025-12-01 | 2015-11-18 |
| 8 | conceptual | ¿Cómo calcula sus pagos provisionales una persona física con actividad profesional? | LISR | art. 106 | 2026-11-10 | 2021-11-12 |
| 9 | conceptual | ¿Qué porcentaje máximo de deducción anual aplica a una computadora? | LISR | art. 34 | 2026-11-10 | 2021-11-12 |
| 10 | conceptual | ¿Hasta qué monto es deducible la compra de un automóvil? | LISR | art. 36 | 2024-08-01 | 2016-11-30 |
| 11 | temporal | ¿Qué decía el artículo 79 de la LISR sobre las comunidades indígenas antes de la reforma de abril de 2024? | LISR | art. 79 | 2024-02-01 | 2020-12-08 |
| 12 | temporal | ¿Qué dice hoy el artículo 79 de la LISR sobre los pueblos y comunidades indígenas y afromexicanas? | LISR | art. 79 | 2026-11-10 | 2024-04-01 |
| 13 | temporal | ¿Qué requisitos debía reunir un CFDI en 2025? | CFF | art. 29-A | 2025-06-01 | 2021-11-12 |
| 14 | temporal | ¿Qué requisitos debe reunir un CFDI en 2026? | CFF | art. 29-A | 2026-03-01 | 2025-11-07 |
| 15 | conceptual | ¿Cuánto tiempo hay que conservar la contabilidad? | CFF | art. 30 | 2026-11-10 | 2021-11-12 |
| 16 | conceptual | ¿En cuánto tiempo caducan las facultades de comprobación del SAT? | CFF | art. 67 | 2026-11-10 | 2021-11-12 |
| 17 | conceptual | ¿Cuándo prescribe un crédito fiscal? | CFF | art. 146 | 2026-11-10 | sin nota de reforma |
| 18 | conceptual | ¿Qué pasa si un proveedor aparece en la lista de operaciones inexistentes (EFOS)? | CFF | art. 69-B | 2024-09-01 | 2021-11-12 |
| 19 | temporal | ¿Por qué causas podía el SAT restringir temporalmente el sello digital en 2025? | CFF | art. 17-H Bis | 2025-06-01 | 2021-11-12 |
| 20 | temporal | ¿Por qué causas puede el SAT restringir temporalmente el sello digital en 2026? | CFF | art. 17-H Bis | 2026-06-01 | 2025-11-07 |
| 21 | conceptual | ¿Qué plazo tiene el SAT para devolver un saldo a favor? | CFF | art. 22 | 2026-11-10 | 2021-11-12 |
| 22 | temporal | ¿De cuánto era la multa por no presentar una declaración en 2025? | CFF | art. 82 | 2025-06-01 | 2023-12-29 |
| 23 | temporal | ¿De cuánto es la multa por no presentar una declaración en 2026? | CFF | art. 82 | 2026-06-01 | 2025-12-28 |
| 24 | temporal | ¿Qué formas de garantía del interés fiscal aceptaba el CFF en 2025? | CFF | art. 141 | 2025-06-01 | sin nota de reforma |
| 25 | temporal | ¿Qué formas de garantía del interés fiscal acepta el CFF desde abril de 2026? | CFF | art. 141 | 2026-06-01 | 2026-04-09 |
| 26 | exacta | artículo 5o.-A del CFF | CFF | art. 5o.-A | 2026-11-10 | sin nota de reforma |
| 27 | conceptual | ¿Cuál es la tasa general del IVA? | LIVA | art. 1o | 2026-11-10 | 2019-12-09 |
| 28 | conceptual | ¿Qué alimentos y medicinas están gravados a la tasa del 0%? | LIVA | art. 2o.-A | 2024-05-01 | 2021-11-12 |
| 29 | conceptual | ¿Qué requisitos debe cumplir el IVA para ser acreditable? | LIVA | art. 5o | 2026-11-10 | 2021-11-12 |
| 30 | conceptual | ¿Cuándo debe una persona moral retener el IVA a una persona física? | LIVA | art. 1o.-A | 2026-11-10 | 2021-04-23 |
| 31 | conceptual | ¿Los servicios médicos causan IVA? | LIVA | art. 15 | 2026-11-10 | 2020-12-08 |
| 32 | conceptual | ¿Qué obligaciones de IVA tienen las plataformas digitales extranjeras sin establecimiento en México? | LIVA | art. 18-D | 2025-09-01 | 2021-11-12 |
| 33 | conceptual | ¿Qué días son inhábiles para el SAT en 2026? | RMF 2026 | regla 2.1.6 | 2026-06-01 | 2025-12-28 |
| 34 | conceptual | ¿Cómo se obtiene la opinión del cumplimiento de obligaciones fiscales? | RMF 2025 | regla 2.1.37 | 2025-06-01 | 2024-12-30 |
| 35 | temporal | ¿Hasta cuándo se podía cancelar un CFDI en 2024? | RMF 2024 | regla 2.7.1.47 | 2024-06-01 | 2023-12-29 |
| 36 | conceptual | ¿Cómo se factura al público en general con un CFDI global? | RMF 2026 | regla 2.7.1.21 | 2026-06-01 | 2025-12-28 |
| 37 | conceptual | ¿Cuándo hay que emitir el CFDI con complemento de pagos? | RMF 2025 | regla 2.7.1.32 | 2025-09-01 | 2024-12-30 |
| 38 | exacta | regla 3.13.2 RMF 2026 | RMF 2026 | regla 3.13.2 | 2026-11-10 | 2025-12-28 |
| 39 | conceptual | ¿Es obligatorio el código postal del domicilio fiscal del receptor en el CFDI 4.0? | Anexo 20, estándar CFDI 4.0 | Nodo Receptor, atributo DomicilioFiscalReceptor | 2026-11-10 | 2022-01-13 |
| 40 | conceptual | ¿Qué clave de forma de pago lleva un CFDI con método de pago PPD? | Anexo 20, guía de llenado | Nodo Comprobante, campo FormaPago | 2026-11-10 | vigente al bajar (Last-Modified 2026-01-17) |

## Qué distingue a cada versión en las temporales

| # | Unidad | Antes | Después |
|---|---|---|---|
| 11 y 12 | LISR art. 79 | "comunidades indígenas" | "pueblos y comunidades indígenas y afromexicanas" (DOF 01-04-2024) |
| 13 y 14 | CFF art. 29-A | Sin el requisito de operaciones reales | "Amparar operaciones existentes, verdaderas o actos jurídicos reales" (DOF 07-11-2025, en vigor el 2026-01-01) |
| 19 y 20 | CFF art. 17-H Bis | Hasta la fracción XI | Fracciones XII a XIV, entre ellas "créditos fiscales firmes no pagados" (DOF 07-11-2025) |
| 22 y 23 | CFF art. 82 | Multa de $1,810.00 a $22,400.00 (cantidades DOF 29-12-2023) | Multa de $2,050.00 a $25,360.00 (cantidades DOF 28-12-2025) |
| 24 y 25 | CFF art. 141 | "Depósito en dinero, carta de crédito..." | "Billete de depósito, emitido por institución autorizada" (DOF 07-11-2025 y 09-04-2026) |
| 35 | RMF 2024, regla 2.7.1.47 | En la RMF 2025 la misma regla ("Plazos para la cancelación de CFDI") es la 2.7.1.46 | La numeración cambia de un año a otro |

## Casos límite (no cuentan para el recall)

Sirven para probar la regla de citar o callar y los bordes del versionado. No tienen una unidad esperada simple.

| Caso | Consulta | Fecha | Qué debe pasar |
|---|---|---|---|
| A | ¿Qué dice el artículo 30-B del CFF? | 2026-02-01 | No devolverlo como vigente: se adicionó con el decreto del DOF 07-11-2025, pero entró en vigor el 2026-04-01. |
| B | ¿Qué formas de garantía acepta el CFF? | 2026-02-01 | Devolver la versión intermedia del art. 141 (vigente del 2026-01-01 al 2026-04-09). No está en ninguna copia fechada: hay que reconstruirla con el decreto del 07-11-2025. |
| C | ¿Cuál es la tarifa anual del ISR de personas físicas en 2026? | 2026-04-30 | El art. 152 de la LISR en LeyesBiblio no trae la tarifa actualizada; la vigente está en el Anexo 8 de la RMF. Mientras el Anexo 8 no esté en el corpus, la respuesta debe advertirlo. |
| D | ¿Cuántos días de vacaciones me corresponden por ley? | 2026-11-10 | Callar: la LFT está fuera del corpus de la v1. |
| E | ¿Qué decía la regla 2.4.10 de la RMF sobre la constancia de situación fiscal? | 2026-03-01 | En la RMF 2026 ese tema es la regla 2.4.9. Buscar por número sin el año devuelve otra regla. |

## Pendiente para la iteración 2

- Que Remi revise el fraseo y agregue preguntas de su caso real (persona física con actividad profesional).
- Decidir si el recall se mide contra la unidad (artículo o regla) o contra la versión exacta. Con las temporales conviene la versión.
