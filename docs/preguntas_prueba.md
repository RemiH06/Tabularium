# Preguntas de prueba (borrador)

Conjunto para RNF-06: recall@5 de al menos 0.85 sobre 54 preguntas con unidad esperada y fecha, medido contra la unidad y contra la versión (el umbral se exige contra la versión). Las 40 primeras son el borrador de la iteración 0 (2026-11-10); las 12 siguientes salen de la lista de Remi del 2026-11-12, y las 2 últimas, del Anexo 8 (iteración 3).

## Cómo se armó

- Cada unidad esperada se comprobó contra el corpus segmentado en `exploracion/`: la unidad existe en la versión que corresponde a la fecha y su texto contiene lo que se pregunta. Las 40 pasan.
- **Fecha** es la fecha de consulta (`buscar(consulta, fecha)`). El sistema debe devolver la versión vigente ese día.
- **Versión esperada** es la fecha del DOF de la última reforma de esa unidad dentro de la versión que debe devolverse, tomada de las notas de la Cámara ("Párrafo reformado DOF ..."). "Sin nota de reforma" significa que el texto no trae ninguna nota. Para la RMF es la fecha de publicación de la resolución del año; ninguna de las seis reglas elegidas trae marca de modificación.
- Tipos: **exacta** (se pide por número, prueba BM25), **conceptual** (lenguaje natural, prueba embeddings) y **temporal** (la misma unidad en dos fechas con textos distintos, prueba RF-04).
- Reparto de las 40: 12 de LISR, 14 de CFF, 6 de LIVA, 6 de RMF y 2 del Anexo 20 (estándar y guía de llenado del CFDI). Once temporales.

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
| 39 | conceptual | ¿Es obligatorio el código postal del domicilio fiscal del receptor en el CFDI 4.0? | RMF2022-A20 | sección I.A Receptor (atributo DomicilioFiscalReceptor) | 2026-11-10 | 2022-01-13 |
| 40 | conceptual | ¿Qué clave de forma de pago lleva un CFDI con método de pago PPD? | GUIA-A20 | sección I Comprobante (campo FormaPago) | 2026-11-10 | 2026-01-17 (Portal del SAT, Last-Modified) |

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
| C | ¿Cuál es la tarifa anual del ISR de personas físicas en 2026? | 2026-04-30 | El art. 152 de la LISR en LeyesBiblio no trae la tarifa (es imagen). Desde la iteración 3 está en el Anexo 8 de la RMF 2026, sección C.II, y el art. 152 la enlaza por el grafo. Pasó al recall como pregunta 53. |
| D | ¿Cuántos días de vacaciones me corresponden por ley? | 2026-11-10 | Callar: la LFT está fuera del corpus de la v1. |
| E | ¿Qué decía la regla 2.4.10 de la RMF sobre la constancia de situación fiscal? | 2026-03-01 | En la RMF 2026 ese tema es la regla 2.4.9. Buscar por número sin el año devuelve otra regla. |

## Preguntas de Remi (2026-11-12)

Remi propuso 40 preguntas de consulta legal y fiscal general. La mayoría usa términos de España (Hacienda, autónomo, SL, Impuesto sobre Sociedades, Seguridad Social, cláusula suelo, Ley de Segunda Oportunidad) o cae fuera de la v1. Se repartieron así: 12 entran al recall, reformuladas para México; 18 son casos de callar; 10 se descartan.

### Entran al recall

Fraseadas como las haría una persona física con actividad profesional en México. La versión esperada es la vigente en la fecha; el script la comprueba con `vigente_desde` y `vigente_hasta`, sin columna aparte. Las unidades del CFF se verifican al ingerirlo.

| # | Original | Tipo | Pregunta | Documento | Unidad esperada | Fecha |
|---|---|---|---|---|---|---|
| 41 | 11 | conceptual | ¿Puedo tributar en el RESICO si empiezo a dar servicios profesionales? | LISR | art. 113-E (también vale art. 100) | 2026-11-10 |
| 42 | 12 | conceptual | ¿Qué gastos puedo deducir como persona física con servicios profesionales? | LISR | art. 103 | 2026-11-10 |
| 43 | 13 | conceptual | El SAT me requirió una declaración que no presenté, ¿qué puede hacer? | CFF | art. 41 | 2026-11-10 |
| 44 | 14 | conceptual | ¿Qué hago con un saldo a favor de IVA: lo acredito o pido la devolución? | LIVA | art. 6o | 2026-11-10 |
| 45 | 15 | conceptual | ¿Qué pasa si mi opinión de cumplimiento sale negativa? | CFF | art. 32-D | 2026-11-10 |
| 46 | 16 | conceptual | ¿Qué obligaciones tiene una persona física con actividad empresarial o profesional? | LISR | art. 110 | 2026-11-10 |
| 47 | 17 | conceptual | ¿Cuánto se paga de recargos si pago tarde un impuesto? | CFF | art. 21 | 2026-11-10 |
| 48 | 19 | conceptual | Voy a contratar a mi primer empleado, ¿qué tengo que retener y declarar? | LISR | art. 99 | 2026-11-10 |
| 49 | 20 | conceptual | ¿Cómo empieza el SAT una revisión o visita domiciliaria? | CFF | art. 42 | 2026-11-10 |
| 50 | 27 | conceptual | ¿Qué es la defraudación fiscal y qué pena tiene? | CFF | art. 108 | 2026-11-10 |
| 51 | 31 | conceptual | Si presento tarde mis declaraciones sin que el SAT me lo pida, ¿me multan? | CFF | art. 73 | 2026-11-10 |
| 52 | 34 | conceptual | Voy a constituir una sociedad, ¿cuándo tengo que inscribirla en el RFC? | CFF | art. 27 | 2026-11-10 |

### Anexo 8 (iteración 3, 2026-11-12)

Las tarifas que la LISR trae como imagen (R-03). Cada año es un documento propio (`RMF2026-A8`).

| # | Tipo | Pregunta | Documento | Unidad esperada | Fecha | Versión esperada (DOF) |
|---|---|---|---|---|---|---|
| 53 | conceptual | ¿Cuál es la tarifa anual del ISR de personas físicas en 2026? | RMF2026-A8 | sección C.II | 2026-04-30 | 2025-12-28 |
| 54 | temporal | ¿Qué tarifa mensual se usaba en 2025 para retener ISR por salarios? | RMF2025-A8 | sección B.V | 2025-06-01 | 2024-12-30 |

Lo que se quitó al adaptarlas: "carta invitación" (43) no aparece en el CFF; "Impuesto sobre Sociedades" (44) es de España; la Seguridad Social (48) es el IMSS, fuera de la v1; los pasos mercantiles de la sociedad (52) son de la Ley General de Sociedades Mercantiles, fuera de la v1.

### Casos de callar (no cuentan para el recall)

Materias fuera del corpus de la v1. Sirven para medir la regla de citar o callar: el sistema no debe responder como si el corpus las cubriera. Números de la lista original:

| Materia | Preguntas | Ley mexicana que haría falta |
|---|---|---|
| Laboral | 1 (excedencia o reducción de jornada), 2 (despido e indemnización) | LFT |
| Familiar y civil | 3 (pensión alimenticia), 5 (vecinos y condominio), 8 (depósito y renta) | Códigos civiles estatales, ley de condominios |
| Bancario y consumo | 4 (cláusula suelo, figura de España), 6 (cobros de luz, agua o teléfono), 7 (devoluciones y garantía), 9 (insolvencia; la Ley de Segunda Oportunidad es de España) | LFPC, Ley de Concursos Mercantiles |
| Administrativo | 10 (multa de tránsito) | Reglamentos estatales y municipales |
| Penal | 21 a 26, 28 | CNPP, Código Penal Federal |
| Datos personales | 35 (confidencialidad de una gestoría) | LFPDPPP |

Consultas que corre el script de evaluación (2026-11-12). El texto original de Remi no quedó guardado; estas son reformulaciones para México a partir de la materia. **Decisión de Remi (2026-11-12):** se quedan así, en espera, como no respondibles. También son la lista de lo que falta descargar: cada materia dice qué ley haría falta para responderlas (tabla de arriba).

| Original | Materia | Pregunta (callar) |
|---|---|---|
| 1 | Laboral | ¿Puedo pedir que me reduzcan la jornada laboral para cuidar a mi hijo? |
| 2 | Laboral | Me despidieron sin causa, ¿cuánto me tienen que pagar de indemnización? |
| 3 | Familiar | ¿Cuánto debe pagar de pensión alimenticia el padre de mis hijos? |
| 4 | Bancario | Mi crédito hipotecario tiene una tasa mínima que no baja aunque bajen las tasas, ¿es legal? |
| 5 | Civil | Mi vecino hace ruido toda la noche en el condominio, ¿qué puedo hacer? |
| 6 | Consumo | Me cobraron de más en el recibo de luz, ¿cómo reclamo? |
| 7 | Consumo | La tienda no me quiere cambiar un producto defectuoso con garantía, ¿qué hago? |
| 8 | Civil | El dueño no me devuelve el depósito al terminar el contrato de arrendamiento, ¿qué hago? |
| 9 | Concursal | No puedo pagar mis deudas, ¿puedo declararme en quiebra como persona? |
| 10 | Administrativo | ¿Cómo impugno una multa de tránsito? |
| 21 | Penal | Me detuvo la policía, ¿qué derechos tengo? |
| 22 | Penal | ¿Cómo presento una denuncia ante el Ministerio Público? |
| 23 | Penal | ¿Cuánto tiempo puede durar la prisión preventiva? |
| 24 | Penal | ¿Qué pena tiene el robo a casa habitación? |
| 25 | Penal | ¿Puedo llegar a un acuerdo reparatorio con la víctima para no ir a juicio? |
| 26 | Penal | Me acusan de un delito, ¿tengo derecho a un defensor público? |
| 28 | Penal | ¿Qué hago si alguien me amenaza por mensajes? |
| 35 | Datos personales | ¿La gestoría puede compartir mis datos personales con otras empresas sin mi permiso? |

### Descartadas

18, 29, 30, 32, 33, 36, 37, 38, 39 y 40 se le hacen a un despacho o gestoría (honorarios, plataforma, experiencia, duración, estrategia), no a un corpus de normas. La 18 (¿un asesor puede reducir mi carga legalmente?) pide una opinión: a lo más se citaría la razón de negocios del art. 5o.-A del CFF, que ya prueba la 26.
