# WP-EDGE-08 — informe ejecutivo

*Lectura única de `2026-10-14T21:41:37Z` (`EDGE08-REPORT-20261014T214137Z`), rama `agent/edge-recovery/WP-EDGE-00-baseline`, commit `a595cbf8cbfb`. Las cifras de este informe salen del mismo diccionario que RUN_REPORT y FINAL_REPORT; no hay una cuarta medición paralela.*

## 1. Veredicto

**`CLOSED_WITH_OPEN_ITEMS`**: la cross-section se leyó una sola vez, todas las estrategias que pasaron el filtro previo fueron **rechazadas** en ella, el estado de las compuertas queda publicado y el verificador independiente pasa 14/14 con 14 de 14 sabotajes detectados.

## 2. Qué recurso se ha leído, y por qué es nuevo

Todo lo que este proyecto podía leer en el tiempo ya estaba leído: la ventana OOS de WP-EDGE-01/02 y el holdout de WP-EDGE-07 estaban gastados. Lo que quedaba sin leer era la **dimensión de símbolo**: ['AAVEUSDT', 'UNIUSDT', 'KSMUSDT', 'SNXUSDT', 'CRVUSDT', 'SUSHIUSDT'] son seis activos líquidos cuya historia no había medido nunca ningún artefacto commiteado. Se descargaron una vez desde el REST público de Binance (digest de corpus `fb32470f5bc6329e…`, 304158 barras, huecos ausentes y contados) y se leyeron una sola vez.

## 3. Track B — validación económica

| Estrategia | Track | Criterios fallidos | Operaciones (cross-section) | Neto (USDT) | Ops/día |
| --- | --- | --- | --- | --- | --- |
| `edge08_quality_breakout_daily` | QUALITY | P2, P3, P4, P5, P6, R1, R2, S1, F2 | 30 | -166.6146 | 0.0461 |
| `edge08_quality_pullback_daily` | QUALITY | C0 | no leído | no leído | — |
| `edge08_quality_reversion_daily` | QUALITY | C0 | no leído | no leído | — |
| `edge08_active_daybreak_1h` | ACTIVE | P2, P3, P4, P5, P6, R1, R2, F1 | 103 | -474.0861 | 0.1581 |
| `edge08_active_multiday_range_1h` | ACTIVE | P2, P3, P4, P5, R1, R2, S1, F1 | 128 | -494.7063 | 0.1965 |
| `edge08_active_stretch_revert_1h` | ACTIVE | C0 | no leído | no leído | — |
| `edge06_trend_fixed` | CURRENT | — | 144 | -415.825 | 0.2211 |
| `edge07_active_thrust` | CURRENT | — | 196 | -350.7431 | 0.3009 |
| `edge_trend_01_4h` | CURRENT | — | 126 | -215.8994 | 0.1934 |

El caso más claro es el breakout diario: en el universo conocido (BTC/ETH/SOL) ganaba 924.1688 USDT en DEV, y sobre seis nombres que no había visto nunca **pierde antes de comisiones** (criterio S1). La cross-section no confirma nada que se hubiera medido antes en otro sitio: eso es exactamente lo que se pedía comprobar.

## 4. Track C — frecuencia y calidad, separados

- **QUALITY** (reloj diario, objetivo ≥ 0.05 operaciones/día): 0.046/día medido en la ventana decisiva; el libro que sobrevive al filtro pierde además dinero, así que su veredicto es `REJECT`.
- **ACTIVE** (entradas horarias con mantenimiento de días, objetivo ≥ 3.0 operaciones/día): 0.16 y 0.20/día medidos, y ambos pierden con potencia (103 y 128 operaciones). El objetivo de frecuencia sigue sin alcanzarse: no se forzó ninguna operación ni se relajó ningún filtro para acercarlo.

## 5. Comparación CURRENT vs PROPOSED

Los tres libros congelados de paquetes anteriores se leyeron sobre el mismo corpus y las mismas ventanas: también pierden, y en todas las ventanas. El resultado honesto de este paquete no es que una estrategia nueva supere a las viejas, sino que **ni las viejas ni las nuevas sobreviven a un universo en el que no fueron elegidas**.

## 6. Estado de las compuertas

`validation/GATE_STATUS.{json,md}` publica las 9 estrategias con su veredicto registrado junto al de la compuerta congelada. Ninguna es `ADMIT_PAPER`: nada se mueve hacia papel y nada se mueve hacia real.

## 7. Qué NO se declara

- Ni `PASS`, ni `PAPER_READY`, ni rentabilidad: `promotion: NONE`, `order_sent: False`.
- No se releyó ninguna ventana gastada: el holdout de WP-EDGE-07 no forma parte de ningún criterio de este paquete.
- No se modificó ningún límite de riesgo: `config/risk.yaml` (digest `3c27c866d5f11afe…`) se lee, nunca se escribe.
- Seis símbolos son seis símbolos: la transferencia medida es evidencia sobre ellos, no una ley general.

## 8. Verificación y reproducibilidad

| Comprobación | Resultado |
| --- | --- |
| Verificador independiente | **PASS**, 14/14 comprobaciones |
| Autoprueba por sabotaje | PASS: 14/14 |
| `owned` | exit `0` — 26 passed in 1.71s |
| `lint` | exit `0` — All checks passed! |
| `format` | exit `0` — 21 files already formatted |
| `types` | exit `0` — Success: no issues found in 12 source files |
| Digests | 13 artefactos publicados en RUN_REPORT.md |
| Commits y push | rama `agent/edge-recovery/WP-EDGE-00-baseline`, rango en el último push `9e2c04e..a595cbf (+5 ahead)`, remoto releído: `False` |

## 9. Decisiones abiertas

- no book transfers to the unread cross-section: the daily breakout is the sharpest case, positive on BTC/ETH/SOL and negative *gross* on six names it had never seen - a new registration, on a different structure, is the only honest way forward — *quant-researcher: a new pre-registration*
- the ACTIVE target of three trades a day is not reached by any registered book (0.16-0.20 a day measured): with the capture fraction the barrier table demands at 24 h, the frequency question is a strategy question on a slower clock, not a filter to loosen — *quant-researcher: a slower clock or a different universe*
- the quality reversion book is structurally empty on this tape: 66 dislocations on the screening ground, every one of them outside the range-bound regime it requires - the two conditions never co-occur — *quant-researcher: separate the regime and the dislocation, or drop it*
- the cross-section is six symbols: a transfer test across six names is evidence about those names, not a general law - a second cross-section, registered the same way, is the natural next step — *context-engineer then quant-researcher*
