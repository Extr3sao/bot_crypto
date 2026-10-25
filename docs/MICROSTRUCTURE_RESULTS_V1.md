# MICROSTRUCTURE_RESULTS_V1 (§33-43, §54-57)

> Resultados de EXECUTION-COST & MICROSTRUCTURE-EDGE-V1. Máquina:
> `docs/MICROSTRUCTURE_RESULTS_V1.json`. Coste de admission: 23.5 bps RT.

Fecha: 2026-09-26. Datos: 59,905 barras 5m × 3 activos (2026-03..09), funding
y premium históricos completos, OI 30d.

## 1. Resumen ejecutivo

**0 de 12 experimentos admisibles.** Ninguna feature de microstructure
testeable históricamente produce un edge bruto que se acerque al coste
realista de 23.5 bps.

- Mejor edge bruto tradeable observado: **+2.36 bps/trade** (`S-01`
  flow_imbalance_z, horizonte 5).
- Techo bruto in-sample (Filter 0, no tradeable): ~24-31 bps en
  `funding_rate@h60` con IC ~0.03 (regime artifact).
- Coste realista: **23.5 bps**. Todo lo testeable → **COST_KILLED** o
  **NO_GROSS_EDGE**.

## 2. CANDIDATE TABLE (§55)

| Candidate | Data | Horizonte | Trades | Gross bps | Cost bps | Net bps | OOS net bps | DD bps | Status |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| S-01 flow_imbalance_z | klines+flow | 5 | 6,633 | **+2.36** | 23.5 | −21.14 | −10.12 | 856 | COST_KILLED |
| S-03 flow breakout | klines+flow | 5 | 36,145 | +0.94 | 23.5 | −22.56 | −16.88 | 3,480 | COST_KILLED |
| S-04 funding extremes | funding | 30 | 7,112 | +0.93 | 23.5 | −22.57 | −28.31 | 640 | NO_GROSS_EDGE |
| S-05 premium/basis | premium | 15 | 10,227 | −0.93 | 23.5 | −24.43 | −41.53 | 1,090 | NO_GROSS_EDGE |
| S-06 OI+price (BTC) | OI 30d | 15 | 8,486 | −2.16 | 23.5 | −25.66 | −25.39 | — | NO_GROSS_EDGE |
| S-06 OI+price (ETH) | OI 30d | 15 | 8,486 | −1.80 | 23.5 | −25.30 | −24.56 | — | NO_GROSS_EDGE |
| S-06 OI+price (SOL) | OI 30d | 15 | 8,486 | −1.88 | 23.5 | −25.38 | −25.90 | — | NO_GROSS_EDGE |
| S-07 funding+OI (BTC) | OI 30d | 30 | 80 | −5.60 | 23.5 | −29.10 | −28.41 | — | LIMITED_HISTORY |
| S-07 funding+OI (ETH) | OI 30d | 30 | 76 | +2.70 | 23.5 | −20.80 | −19.33 | — | LIMITED_HISTORY |
| S-07 funding+OI (SOL) | OI 30d | 30 | 63 | −36.57 | 23.5 | −60.07 | −59.01 | — | LIMITED_HISTORY |
| S-08 BTC lead/lag | klines | 1 | 119,443 | −0.19 | 23.5 | −23.69 | −24.56 | — | NO_GROSS_EDGE |
| S-02 book imbalance | order book | — | — | — | — | — | — | — | EXECUTION_MODEL_REQUIRED |

## 3. Split detail (§38)

| Candidate | DEV gross | VAL gross | OOS gross | Nota |
| --- | ---: | ---: | ---: | --- |
| S-01 | +0.81 | +1.17 | +13.38 | OOS mejor pero n pequeño y aun < coste |
| S-03 | +0.21 | +0.11 | +6.62 | ídem |
| S-04 | +1.03 | +3.02 | **−4.81** | no pasa split |
| S-05 | +2.28 | **−0.82** | **−18.03** | no pasa split |
| S-08 | −0.06 | −0.11 | −1.06 | negativo en todo |

S-01 y S-03 tienen un OOS "menos malo", pero el edge bruto OOS (+13.4 y
+6.6 bps) **sigue por debajo de 23.5 bps**. No hay margen. La aparente mejora
en OOS es un artefacto de régimen de septiembre, no una señal robusta, y en
cualquier caso no paga el coste.

## 4. Cost survival (§36, §40)

`net = gross − RT`. Con RT = 23.5 bps, **ninguna** candidata es positiva.
Stress 1.5X (35.25) y 2X (47.0) empeoran linealmente. No hay sorpresa: un
gross de +2.4 bps no puede sobrevivir un coste de 23.5 bps.

## 5. MFE/MAE e información direccional (§43)

En V3, MFE ≈ MAE en todas las celdas OHLCV. En microstructure, los IC casi
nulos (|IC| <= 0.06) y el hecho de que los gross edges sean de pocos bps
indican **ausencia de información direccional explotable**, no un problema de
exits. No se optimizan exits (§43: primero información, luego exits).

## 6. DATA SOURCE TABLE (§56)

| Source | Product | History | Resolution | PIT safe | Public | Status |
| --- | --- | --- | --- | --- | --- | --- |
| klines+flow | spot | full | 1m..1M | sí | sí | DATA_SUFFICIENT |
| aggTrades | spot | full | tick | sí | sí | DATA_SUFFICIENT |
| bookTicker | spot | none | live | sí | sí | LIVE_ONLY |
| depth | spot | none | live | sí | sí | LIVE_ONLY |
| funding | perp | full | 1h..8h | sí | sí | DATA_SUFFICIENT |
| premium index | perp | full | 1m..1d | sí | sí | DATA_SUFFICIENT |
| open interest | perp | 30d | 5m..1d | sí | sí | LIMITED_HISTORY |
| basis | perp | 30d | 5m..1d | sí | sí | LIMITED_HISTORY |

## 7. COST MODEL TABLE (§57)

| Scenario | Fee/side | Spread | Slip/side | Funding | Effective RT | Evidence |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| CURRENT_PROJECT | 5.0 | 0.0 | 1.0 | 0.0 | **12.0** | scripts `FEES/SLIP` |
| REALISTIC_RETAIL | 10.0 | 1.0 | 1.0 | 0.0 | **23.5** | SRC-01 + spread observado |
| REALISTIC_RETAIL_BNB | 7.5 | 1.0 | 1.0 | 0.0 | **18.5** | 25% BNB (no baseline) |
| REALISTIC_MAKER (theor.) | 10.0 | 0.0 | 0.0 | 0.0 | **21.0** | maker VIP0 = taker |
| STRESS | 10.0 | 2.0 | 3.0 | 0.0 | **30.0** | 2x slippage + spread |

## 8. Clasificación final (§54)

| clasificación | nº experimentos |
| --- | ---: |
| COST_KILLED | 3 |
| NO_GROSS_EDGE | 5 |
| LIMITED_HISTORY | 3 |
| EXECUTION_MODEL_REQUIRED | 1 |
| **PAPER_CANDIDATE** | **0** |

## 9. Lectura honesta

- Las features de **order flow agregado** (taker imbalance) muestran sólo
  reversión débil a 1-5 barras (IC ≈ −0.02), con gross de pocos bps. No hay
  evidencia de continuación explotable.
- **Funding/premium** muestran relación monotónica débil con el retorno a
  horizonte largo (h60), pero es un artefacto de régimen y su regla
  pre-registrada contraria falla en OOS.
- **OI/basis**: el histórico de 30 días impide DEV/VAL/OOS; no puede pasar
  Filter 3.
- **Order book**: sin histórico → no testeable → forward required.
- **BTC lead/lag**: sin información (gross ≈ 0, negativo).

Ninguna candidata reúne evidencia para admission. `FALSE_SUCCESS = 0`.
