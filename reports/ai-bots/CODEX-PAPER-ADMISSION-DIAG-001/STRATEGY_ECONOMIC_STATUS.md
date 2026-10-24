# STRATEGY_ECONOMIC_STATUS — ¿hay alguna ventaja económica demostrada?

> Todo lo que sigue sale de artefactos ya commiteados. No hay backtest nuevo en este documento.
> Fecha: 2026-10-23 · HEAD auditado: `3b758e22` (+ `main` @ `47ca8dac`, ver OPERATIONAL_BLOCKERS §B5).

---

## 1. Respuesta

**No.** Ninguna estrategia del repositorio tiene evidencia de ventaja económica **después de
costes**. Sí existe señal bruta positiva en 7 de 24 celdas, con un techo de **+8.91 bps/trade**,
pero ese techo está **3.26 bps por debajo** del taker más barato modelado y **14.44 bps por
debajo** de la línea con la que el runtime decide la admisión.

| Medida | Valor | Fuente |
| --- | ---: | --- |
| Celdas evaluadas | 24 | `COST_BARRIER_EXPLORER.json` → `cells` |
| Celdas con gross > 0 | **7** | ídem |
| Gross máximo por trade | **+8.912 bps** (`volatility@30m`) | ídem |
| Línea taker más barata *observada* | **12.177 bps RT** (`BINANCE_USDM_PERP_TAKER`, 200 USD, deep) | `reachability.frontier.cheapest_line_taker` |
| Línea con la que el runtime admite | **23.354 bps RT** | `cells[].runtime_admission_rt_bps` |
| Línea más barata de todas | 1.25 bps RT (`MEXC_SPOT_TAKER`, modo maker) | `frontier.cheapest_line_any`; `rests_on_assumed_component: true` |
| Familias que superan admisión | **0/6** | `docs/STRATEGY_ADMISSION_MATRIX.md` |
| Estrategias admitidas | **0/24** | `config/strategy_admission.json` |

La única línea que hace «alcanzables» 7 celdas (1.25 bps) **depende de un componente asumido**:
el modelo no incluye tasa de llenado maker. Por eso el propio explorer se niega a llamarla
alcanzable sin esa salvedad, y el verificador independiente lo certifica:
`data/recovery/COST_BARRIER_VERIFICATION.json` → *«no cell clears a line priced without an
assumed maker-fill model, and the assumed lines are unmodelled»*, `status: PASS`, 13/13 controles,
`false_success: 0`.

---

## 2. Las 24 celdas (gross a coste cero, trades, estado)

| Celda | Trades | Gross bps | Estado | Distancia a 12.177 bps |
| --- | ---: | ---: | --- | ---: |
| `volatility@30m` | 194 | **+8.912** | COST_KILLED | −3.265 |
| `volatility@1h` | 96 | **+6.276** | COST_KILLED | −5.901 |
| `mean_reversion@30m` | 934 | **+5.472** | COST_KILLED | −6.705 |
| `mean_reversion@15m` | 1 579 | **+2.714** | COST_KILLED | −9.463 |
| `trend@30m` | 1 562 | **+2.206** | COST_KILLED | −9.971 |
| `mean_reversion@5m` | 3 190 | **+1.485** | COST_KILLED | −10.692 |
| `trend@15m` | 1 616 | **+1.284** | COST_KILLED | −10.893 |
| `breakout@5m` | 2 426 | −0.084 | NO_GROSS_EDGE | −12.261 |
| `breakout@1h` | 710 | −0.222 | NO_GROSS_EDGE | −12.399 |
| `ema_crossover@30m` | 3 214 | −0.726 | NO_GROSS_EDGE | −12.903 |
| `ema_crossover@1h` | 2 620 | −0.964 | NO_GROSS_EDGE | −13.141 |
| `ema_crossover@15m` | 2 913 | −1.122 | NO_GROSS_EDGE | −13.299 |
| `trend@1h` | 1 405 | −1.252 | NO_GROSS_EDGE | −13.429 |
| `trend@5m` | 1 291 | −1.645 | NO_GROSS_EDGE | −13.822 |
| `breakout@30m` | 1 281 | −1.792 | NO_GROSS_EDGE | −13.969 |
| `breakout@15m` | 2 042 | −1.822 | NO_GROSS_EDGE | −13.999 |
| `momentum@5m` | 2 526 | −1.884 | NO_GROSS_EDGE | −14.061 |
| `mean_reversion@1h` | 448 | −2.226 | NO_GROSS_EDGE | −14.403 |
| `momentum@1h` | 2 304 | −2.334 | NO_GROSS_EDGE | −14.511 |
| `momentum@30m` | 2 957 | −2.612 | NO_GROSS_EDGE | −14.789 |
| `momentum@15m` | 3 003 | −3.972 | NO_GROSS_EDGE | −16.149 |
| `ema_crossover@5m` | 1 725 | −4.561 | NO_GROSS_EDGE | −16.738 |
| `volatility@5m` | 520 | −4.735 | NO_GROSS_EDGE | −16.912 |
| `volatility@15m` | 277 | −7.064 | NO_GROSS_EDGE | −19.241 |

Fuente: `data/recovery/COST_BARRIER_EXPLORER.json` (`cells[]`), `data/recovery/ACTIVE_ECONOMIC_AUDIT.json`.
«Distancia» = `gross − 12.176776695296637`; negativa = no cubre ni el taker más barato.

**Lectura:** la señal no está uniformemente ausente. El gross mejora al alargar el horizonte de
5m a 30m en trend/mean_reversion/volatility, y se rompe otra vez en 1h (salvo volatility). Es
una mejora real de signal/noise, pero de 4–9 bps: pequeña frente a una línea de 12–23 bps.

---

## 3. Las 6 familias @5m con auditoría completa

| Familia | Trades | Net BASE | PF BASE | PF DEV | PF OOS | PF 2X | OOS net | Veredicto |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `ema_crossover` | 1 561 | −1 266.16 | 0.50 | — | 0.47 | <0.5 | −144.38 | REJECT |
| `momentum` | 2 436 | −1 679.33 | 0.65 | 0.66 | 0.63 | 0.47 | −205.41 | REJECT |
| `breakout` | 2 276 | −1 427.46 | 0.66 | 0.71 | 0.67 | 0.48 | −138.81 | REJECT |
| `trend` | 1 288 | −876.83 | 0.72 | 0.71 | 0.94 | 0.56 | −17.35 | REJECT |
| `mean_reversion` | 2 861 | −1 514.34 | 0.67 | 0.69 | 0.70 | 0.47 | −169.88 | REJECT |
| `volatility` | 519 | −428.79 | 0.62 | 0.65 | 0.60 | 0.46 | −52.11 | REJECT |

Fuente: `docs/STRATEGY_ADMISSION_MATRIX.md` (net/PF) y `rationale` del ledger (OOS net).
Ninguna familia es marginal: la mejor, `trend`, tiene PF 0.72 y OOS 0.94 (aún perdedor).

**Dos criterios nunca se evaluaron, en ninguna familia:** `c6_dd` (drawdown ≤ 10 %) y
`c8_no_window_dominance` (ninguna ventana > 60 % del net) figuran como `null` en las 6 entradas de
`docs/STRATEGY_ADMISSION_MATRIX.json` (`unknown_checks: ["c6_dd", "c8_no_window_dominance"]`).
El rechazo sigue siendo concluyente porque c2/c3/c4/c7 son `false`, pero una candidata futura
**deberá medirlos**: hoy no hay ni un solo drawdown auditado en el universo de familias.

**`trend` es la única con OOS casi breakeven (0.94)** y aun así pierde −17.35 en OOS. No es una
candidata: es la pista de que el problema está en el coste del mecanismo, no solo en la señal.

Robustez (solo medida para `ema_crossover`): 4/4 variantes negativas, PF 0.57–0.62, negativa en
6/6 regímenes y en 3/3 activos, PF DEV 0.63 → VAL 0.47 → OOS 0.41
(`docs/STRATEGY_ROBUSTNESS.md`, `docs/STRATEGY_PERFORMANCE_OOS.md`).

---

## 4. La prueba más dura que ya existe: fills maker medidos (EXP-003M)

Es el único experimento del repo que **mide** fills contra la cinta observada en vez de suponer
un toque, y el resultado cierra la puerta del «solo hay que ejecutar más barato»:

| Escenario | Llenadas | Bruto/cierre | Comisiones/cierre | Neto/cierre | Neto/señal |
| --- | ---: | ---: | ---: | ---: | ---: |
| `F0_touch_full` (techo teórico) | 44/47 | **0.266909** | **0.750000** | −0.483091 | −0.452255 |
| `F1_tape_base` (cola 1x, 400 ms) | 42/47 | 0.205964 | 0.740655 | −0.534691 | −0.477809 |
| `F2_tape_pessimistic` (cola 4x, 2 s) | 33/47 | 0.076738 | 1.000000 | −0.923262 | −0.648248 |
| `F3_tape_no_queue` | 44/47 | 0.267925 | 0.738865 | −0.470940 | −0.440880 |

- **Cobertura del suelo de comisiones por el techo de bruto: 0.356×.** El techo no cubre el
  suelo ni en el escenario más generoso (todo toque lleno al precio mejorado, cola cero).
- 0/24 puntos del barrido cola×latencia tienen neto positivo por cierre.
- Selección adversa medida: **+2.057 bps en contra** a 5 minutos del fill de cinta (frente a
  −1.780 bps en el conjunto que F0 habría llenado).
- Veredicto del paquete: `REJECT`; gates fallados `G4_economics_pessimistic`, `G5_optimistic_ceiling`,
  `G7_evidence_class`.

Fuente: `reports/ai-bots/EXP-003M-MAKER-FILL-REALITY-001/{FINAL_REPORT.md,ECONOMICS_COMPARISON.md,CANDIDATE_DECISION.md}`.
**Alcance:** 47 señales de `5m/mean_reversion`, 500 USD nocional, spot VIP0 (7.5 bps/lado con
descuento BNB), sobre cinta `aggTrades` de 42 pares (símbolo, día) de 2026-06. No es
directamente transferible a futuros (2/5 bps), pero fija el método y demuestra que existe un
techo económico medible, no una opinión.

---

## 5. La aritmética de la frecuencia objetivo

`COST_BARRIER_EXPLORER.json` → `frequency`: el objetivo de **3 operaciones/día** son 1 095
round-trips/año.

| Línea | RT bps | Coste anual sobre el stake |
| --- | ---: | ---: |
| Admisión del runtime | 23.354 | **255.7 %** |
| Research base | 12.000 | 131.4 % |
| Taker más barato observado | 12.177 | 133.3 % |
| Maker asumido (no modelado) | 1.250 | 13.7 % |

**Consecuencia:** a tarifas taker minoristas, la cadencia objetivo cuesta más que el stake en un
año antes de ganar un céntimo. Cualquier diseño que mantenga 3 ops/día **exige** una línea maker
real, no una estimada. Esto no es un detalle de configuración: es la condición de viabilidad del
objetivo declarado.

---

## 6. Estrategias realmente evaluadas vs sin datos suficientes

| Bloque | Veredicto | Qué falta para cambiar |
| --- | --- | --- |
| 6 familias @5m | **evaluadas y rechazadas** (net, PF, OOS, 2X, robustez) | nada: el signo no es ambiguo |
| 7 celdas @15m/30m/1h con gross > 0 | **parcialmente evaluadas** (gross + trades; sin OOS ni DD ni 2X) | OOS propio, DD, 2X y **una línea de coste ≤ gross** |
| 6 familias @5m — criterios c6/c8 | **no evaluados** (`null` en la matriz) | drawdown y dominancia por ventana, si alguna vez se mide una candidata |
| 11 celdas @15m/30m/1h con gross ≤ 0 | evaluadas y cerradas | nada |
| `ema_crossover` en PAPER real (V2, 19 trades) | ejecutada, PF 0.051 (0.32 ex-DEF-205) | nada: consistente con el histórico |
| `EXP-003M` (fills maker medidos) | medido y rechazado | un mecanismo con bruto > suelo de comisiones **antes** de discutir fills |

---

## 7. Veredicto económico

```
ECONOMIC_ADVANTAGE_DEMONSTRATED = false
BEST_MEASURED_GROSS_BPS          = 8.912
CHEAPEST_OBSERVED_TAKER_RT_BPS   = 12.176776695296637
RUNTIME_ADMISSION_RT_BPS         = 23.353553390593273
NET_POSITIVE_STRATEGIES          = 0
```

**Decisión:** `NO_GO` para admisión PAPER con la evidencia actual. La pregunta abierta no es
«¿qué indicador probamos ahora?» sino **«¿cuál es la línea de coste real, medida, para las dos
celdas de volatilidad?»**. Ese es el único hueco que puede mover el veredicto sin violar los
criterios pre-registrados, y es el objeto de `NEXT_EXPERIMENT.md`.
