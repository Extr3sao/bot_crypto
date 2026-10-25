# FINAL REPORT — EXP-003M

## Respuesta

**`REJECT`**. No hay evidencia de ventaja económica neta después de modelar fills maker realistas, y el candidato `5m/mean_reversion` debe descartarse.

La razón no es que el modelo de fills sea pesimista. Es que el **techo** de ingreso bruto por operación (`0.266909` USDT, con todo toque lleno al precio mejorado y cola cero) ya está por debajo del **suelo** de comisiones (`0.750000` USDT con el descuento BNB, `1.000000` sin él). Un fill más realista solo puede empeorar esa relación.

## Resultados cuantitativos

| escenario | llenadas | neto/cierre | neto/señal | IC95 % neto/señal |
| --- | ---: | ---: | ---: | --- |
| `F0_touch_full` | 44/47 | -0.483091 | -0.452255 | [-1.597596, 0.703727] |
| `F1_tape_base` | 42/47 | -0.534691 | -0.477809 | [-1.472685, 0.609189] |
| `F2_tape_pessimistic` | 33/47 | -0.923262 | -0.648248 | [-1.599922, 0.417521] |
| `F3_tape_no_queue` | 44/47 | -0.470940 | -0.440880 | [-1.533134, 0.704954] |

- La cinta observada reduce el llenado de 93.6 % (F0, por toque) a 89.4 % (F1, cola 1x y 400 ms) y a 70.2 % (F2, cola 4x y 2 s), con fracción media llenada `0.988`.
- Ningún punto del barrido de cola y latencia (24 puntos) tiene neto por cierre positivo: **0/24**.
- Selección adversa: el movimiento a 5 minutos posterior a un fill de cinta es `2.057490` bp en contra, frente a `-1.779905` bp en el conjunto que F0 habría llenado.

## Datos

- 42 pares `(símbolo, día)` de `aggTrades` spot, 680.484 operaciones conservadas de 27.887.409.
- Klines diarias descargadas del mismo archivo y comparadas barra a barra con el dataset congelado de EXP-003K: la procedencia queda comprobada contra una segunda fuente.
- No existe libro L2 spot histórico publicado; no se ha sintetizado ni sustituido por el de futuros.

## Pruebas

- 25 pasadas, 0 falladas, 0 saltadas. ¿Todo verde? **sí**.
- Verificación independiente: 13/14 PASS, 0 FAIL, 1 `NOT_EXECUTED`, controles negativos 8/8, `false_success=0`.

## Defectos encontrados

- `D1_TOQUE_NO_ES_FILL`: EXP-003L supone que cualquier toque del rango de un minuto nos llena enteros al precio mejorado. La cinta confirma que el supuesto no cambia el número de señales llenadas (44 de 47 con cola cero), pero sí el resultado por operación: el neto por cierre pasa de -0.4831 a -0.4709 con la misma tasa, y a -0.5347 cuando se exige una orden de cola. El daño no está en cuántas señales se llenan, sino en *cuándo*.
- `D2_BASE_FEE_WAS_THE_BNB_DISCOUNT`: El escenario maker base de EXP-003L valoraba spot VIP0 con el descuento del 25 % por pagar comisiones en BNB. Sin ese descuento cada operación cerrada cuesta más, y EXP-003L no separaba el descuento del mecanismo: el resultado base dependía de una condición de la cuenta que no se declaró como supuesto.
- `D3_LAS_UNIDADES_DE_TIEMPO_DISCREPAN`: El archivo diario de klines publica microsegundos mientras el dataset congelado (REST /api/v3/klines) está en milisegundos. Una comprobación de procedencia que asumiera una sola unidad habría comparado cero barras y habría pasado en vacío. Ahora se normaliza y falla ante cualquier diferencia: la comprobación compara barras de verdad, no la nada.
- `D4_LA_COLA_NO_ES_OBSERVABLE`: No existe libro L2 spot histórico publicado, así que la cola por delante de una orden en reposo no se puede medir. Se declara y se barre. Con una orden de 500 USDT la cola apenas muerde: solo 3 de 47 señales cambian de fracción entre cola 0 y cola 1. Lo que sí mueve el resultado es la selección adversa del momento del llenado, no el tamaño de la cola.
- `D5_EL_INDICE_DEL_FILL_ERA_EPOCA`: El primer motor de fills convertía el instante del llenado en un índice de barra dividiendo la época por 60 s, sin restarle el origen de la serie. Resultado: todas las posiciones de cinta salían `OPEN_AT_END`, y el informe habría dicho que ninguna llegó a su stop ni a su objetivo. Se detectó por la distribución de estados, no por un test, y ahora el índice se busca en el diccionario de barras con error explícito si el minuto no existe.

## Limitaciones

- no order was sent to an exchange: every fill here is inferred from published trades.
- the queue position at the limit is unobservable without a spot L2 feed; it is declared and swept, not measured.
- a trade at our price is not proof that our order was the one matched.
- cancel/replace traffic and hidden liquidity are not modelled.
- the holdout 2026-08-06 → 2026-08-20 stays closed; nothing here is out-of-sample in the forward sense.
- a moving-block bootstrap on 47 signals is a wide interval, not a proof of anything.

## Siguiente decisión

Descartar `5m/mean_reversion` como candidato económico en esta lane, no volver a presupuestarlo con fills más favorables, y mantener el holdout cerrado: no hay nada que validar fuera de muestra cuando la muestra ya rechaza el mecanismo. La siguiente línea con valor esperado no es otra búsqueda de señal sobre OHLCV, sino un mecanismo cuyo bruto por operación supere el suelo de comisiones **antes** de discutir fills.
