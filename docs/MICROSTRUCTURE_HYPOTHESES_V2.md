# MICROSTRUCTURE_HYPOTHESES_V2 — pre-registro

> **Estado: PRE-REGISTRADO antes de ejecutar.** Reglas, umbrales, horizontes,
> coste y criterios quedan fijados aquí. Nada se re-optimiza tras ver
> resultados. Un fracaso se clasifica y se detiene la línea; no se invierte la
> dirección por split ni se ajusta un umbral para rescatarla.

Fase: **MICROSTRUCTURE-EDGE & FORWARD-DATA V1** (DISCOVERY PLANE).
HEAD base de la fase: `3896f4e`. Evidencia previa reutilizada (no re-ejecutada):
`MICROSTRUCTURE_RESULTS_V1.json`, `AGGTRADES_RESULTS.json`,
`EXECUTION_COST_MODEL_V3`, `VENUE_EXECUTION_MATRIX_V1.json`.

## 0. Qué es nuevo aquí y qué no

V1 y la fase aggTrades ya midieron, con datos reales:

| ID pedido | equivalente previo | estado |
| --- | --- | --- |
| M-01 aggressor flow | `flow_imbalance_z` (V1), `F1` (aggTrades A-01) | **YA TESTEADO** — evidencia V1 |
| M-03 book imbalance | — | **NO TESTEABLE** históricamente (`LIVE_ONLY`) |
| M-04 flow + breakout | `F1 + ret_mom` (A-03) | **YA TESTEADO** |
| M-05 funding | `funding_z` (V1) | **YA TESTEADO** |
| M-06 basis/premium | `premium_z` (V1) | **YA TESTEADO** |
| M-07 OI + precio (4 estados) | sólo IC de `oi_change_z` | **NUEVO en V2** |
| M-08 funding + OI | `S-07` (V1) | **YA TESTEADO** (LIMITED_HISTORY) |
| M-02 flow impulse | `F4/F6` eran **nivel**/volatilidad, no Δflujo | **NUEVO en V2** |
| M-09 BTC→ETH/SOL lead/lag de flujo | `F8`/A-06 sólo lag=1, dirección y horizonte únicos | **AMPLIADO en V2** |
| M-10 cross-sectional flow | — (sólo retorno, M-08 V1) | **NUEVO en V2** |

La conclusión honesta de V1 (`MICROSTRUCTURE_V1_NO_EDGE_FOUND`) se mantiene
hasta que una de estas cuatro hipótesis nuevas la contradiga con datos reales.

## 1. Datos (reales, read-only) y muestra

| item | valor |
| --- | --- |
| ticks | `data.binance.vision` spot daily **aggTrades**, SRC-04 |
| muestra | 14 días discontinuos: día 12 y 24 de 2026-03..2026-09 (42 ficheros) |
| splits | DEV = 2026-03..06 (8 días) · VAL = 2026-07..08 (4) · OOS = 2026-09 (2) |
| OHLCV / volatilidad | `KLINES_<SYM>_5m.json` (59,905 barras, 2026-03-01..09-25) |
| open interest | `OPENINTEREST_<SYM>.json` (8,928 puntos de 5m, ~31 días) |
| spread observado | captura forward propia, `reports/microstructure-v2/forward/*.jsonl` |

La muestra de aggTrades es **discontinua**; ninguna conclusión se extiende al
periodo completo. Un día ausente se registra como hueco, no se sustituye.

### Reglas duras de punto en el tiempo

```
event_time(barra)      = open_time de la barra de 5m (múltiplo exacto UTC)
available_at(barra)    = open_time + 5min + 1 ms        ← el CIERRE
decision_time(barra)   = available_at(barra)
regla                  available_at(feature) <= decision_time
```

El panel sólo existe en timestamps donde **los tres** activos tienen barra
completa en el mismo reloj. Una señal cross-asset se construye con
`pit_lead_lag`, que **rechaza `lag < 0`** (nunca una referencia al futuro) y
verifica `available_at(origen) <= decision_time(destino)` por par.

## 2. Coste de admission: `EXECUTION_COST_MODEL_V4`

`admission_scenario = BINANCE_SPOT_STANDARD_TAKER` (venue real del runtime),
`size = 1,000 USD`, `liquidity_regime = normal`, entrada y salida `market`,
`entry==exit` (round trip).

* **spread**: medido **por activo** en la captura forward V2 (media observada);
  se reporta también p50/p95 y el número de observaciones.
* **volatilidad**: medida **por activo** sobre klines reales de 5m.
* fee/slippage/impact/funding: aritmética de `COST_MODEL_V3`, sin cambios.
* `ADMISSION_SAFETY_MULTIPLE = 1.5` → `required_gross_edge_bps = 1.5 × RT`.
* stress: `1.25x`, `1.5x`, `2.0x` sobre el coste medido.

Asignación de coste por hipótesis (pre-registrada):

| hipótesis | coste aplicado |
| --- | --- |
| M-02, M-07 | coste del propio activo |
| M-09 | coste del **activo objetivo** (ETH o SOL) |
| M-10 (por activo) | coste del propio activo |
| M-10 (dispersión, panel) | **media** de los tres costes por activo |

`ZERO_COST` no se usa para admission. El maker **no** es admission
(`MAKER EDGE GATE = FAIL`: a VIP0 maker = taker y no hay `FillEvidence`).

## 3. Horizontes (label)

Label: forward return en bps del cierre de la barra `i` al cierre de `i+h`,
`h ∈ {1, 5, 15, 30, 60}` barras de 5m. Cada hipótesis tiene **un horizonte
primario** pre-registrado que decide; los demás se reportan como contexto y
**no** promocionan.

| hipótesis | primario | contexto |
| --- | --- | --- |
| M-02 flow impulse | 5 (25 min) | 1, 15 |
| M-07 OI 4 estados | 15 (75 min) | 5, 30 |
| M-09 lead/lag de flujo | 5 (25 min) | 1, 15 |
| M-10 cross-sectional flow | 5 (25 min) | 1, 15 |

## 4. Features y reglas (fijadas ahora)

### M-02 — FLOW IMPULSE
* feature: `flow_impulse_series(flow_imbalance, window = 20)` =
  z-score de la **primera diferencia** del flow, calculado **dentro del día**.
* Es explícitamente **no** el nivel: un nivel constante (aunque extremo) da
  impulso exactamente `0.0`.
* regla: `z >= +2.0` → largo; `z <= -2.0` → corto; `|z| < 2` → plano.
* dirección: determinada en DEV y **congelada** para VAL/OOS.

### M-07 — OI + PRECIO (4 estados)
* `price_change_bps` = cierre(i)/cierre(i-1) - 1, en bps.
* `oi_change_pct` = OI(i)/OI(i-1) - 1, con OI de 5m alineado por timestamp.
* estados: `PRICE_UP_OI_UP`, `PRICE_UP_OI_DOWN`, `PRICE_DOWN_OI_UP`,
  `PRICE_DOWN_OI_DOWN`; un cambio **exactamente cero** cae en `UNCHANGED` y se
  excluye de los cuatro cuadrantes.
* se reporta la **distribución futura** por estado (n, media, mediana, stdev,
  share positivo) y además una única celda tradeable elegida **solo con DEV**,
  con su dirección congelada desde DEV.
* limitación declarada: OI sólo cubre ~31 días (late-Aug..Sep), casi todo OOS.
  Si DEV/VAL no tienen OI suficiente, la hipótesis **no puede** pasar Filter 3
  y se clasifica `LIMITED_HISTORY`, no se declara edge.

### M-09 — LEAD/LAG DE FLUJO BTC → ETH/SOL
* señal: `flow_imbalance` de **BTC** en la barra `i-1` (lag = 1 barra = 5 min).
* objetivo: entrada al cierre de la barra `i` en ETH (y en SOL por separado).
* dirección: determinada en DEV por objetivo y **congelada**.
* PIT: `available_at(BTC, i-1) <= decision_time(objetivo, i)` verificado.

### M-10 — CROSS-SECTIONAL FLOW
* señal por activo: `flow_imbalance(activo, i) - media(flows del panel, i)`.
* variante de panel: **dispersión** cross-sectional (stdev de los tres flows) →
  retorno medio del panel (equiponderado), con coste = media de los tres costes.
* dirección: determinada en DEV por activo y **congelada**.

## 5. Escalera de filtros (pre-registrada)

```text
Filter 0  INFO CONTENT  — |IC Spearman| >= 0.01 con n >= 100 en DEV
Filter 1  GROSS EDGE    — expectancy bruta > 0 en DEV (si no -> NO_GROSS_EDGE)
Filter 2  COST SURVIVAL — gross - coste_V4(activo) > 0
Filter 3  SPLITS        — DEV > 0, VAL > 0, OOS > 0 (temporal stability)
Filter 4  COST STRESS   — sobrevive 1.25x y 1.5x con margen (net > 0.25 x coste)
Filter 5  ADMISSION     — n_total >= 100, n_OOS >= 30, PF_OOS > 1.0,
                          sin dependencia de un único activo, PIT sin violaciones
```

Early stop: si Filter 1 falla en DEV, la línea se cierra como `NO_GROSS_EDGE`.

Estados: `NO_INFORMATION`, `NO_GROSS_EDGE`, `COST_KILLED`, `OOS_FAILED`,
`COST_STRESS_FAILED`, `LIMITED_HISTORY`, `INSUFFICIENT_DATA`,
`RESEARCH_CANDIDATE`.

## 6. Criterios de admission

`PAPER_CANDIDATE` exige **todo** lo anterior **y** verificación independiente
posterior sobre el HEAD final. Ninguna candidata se autodeclara: el script
emite como máximo `RESEARCH_CANDIDATE`.

## 7. Qué NO se hace en esta fase

* No ML, no grids de parámetros, no búsqueda automática de features.
* No fabricar order book histórico desde OHLCV (M-03 sigue `FORWARD_REQUIRED`).
* No usar OOS para elegir dirección, umbral ni celda.
* No presentar gross como net, ni un `PASS` que nadie ejecutó.
* No declarar rentabilidad con muestra pequeña (`OBSERVED`/`INSUFFICIENT_SAMPLE`).
* No tocar el core runtime (§50): RiskManager, PaperBroker, StartupReconciler,
  DecisionTrace hashing, contratos de outcome, replay y PIT del runtime quedan
  intactos.

## 8. Errata

Sólo correcciones de **metodología**, fechadas, nunca de umbrales tras ver
resultados.

### 2026-09-28 — errata metodológica (pre-ejecución, sin ver resultados)

Se explicita la aggregación: sólo se emiten buckets de 5 min **completos** y
alineados al reloj UTC; un minuto ausente descarta el bucket entero (no se
extrapola). Se añade además una verificación externa de la agregación:
el volumen agregado por barra se contrasta con el volumen real de
`KLINES_<SYM>_5m.json` en los mismos buckets, y el ratio se publica.
