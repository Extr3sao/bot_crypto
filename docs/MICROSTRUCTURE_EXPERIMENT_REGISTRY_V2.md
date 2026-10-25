# MICROSTRUCTURE_EXPERIMENT_REGISTRY_V2

> Máquina: `docs/MICROSTRUCTURE_EXPERIMENT_REGISTRY_V2.json`. Pre-registro:
> `docs/MICROSTRUCTURE_HYPOTHESES_V2.md`.

Fecha: 2026-09-28. Un registro por hipótesis, con su estado real: **medida**
(`NEWLY_TESTED` o `PREVIOUSLY_TESTED`), **no testeable** con los datos
disponibles, y su clasificación pre-registrada. Ninguna fila se marca como
validada por el hecho de estar en el registro.

## 1. Hipótesis medidas en esta fase (nuevas)

| ID | hipótesis | h primario | contexto | datos | clasificación | evidencia |
| --- | --- | :-: | --- | --- | --- | --- |
| M-02 | flow impulse (Δflujo, no nivel) | 5 | 1, 15 | aggTrades 14d | `COST_KILLED` x3 (BTC/ETH/SOL) | `MICROSTRUCTURE_RESULTS_V2.json` |
| M-07 | OI x precio, 4 cuadrantes | 15 | 5, 30 | OI 5m (sólo ~31d) | `LIMITED_HISTORY` x3 | idem |
| M-09 | lead/lag de flujo BTC→ETH/SOL | 5 | 1, 15 | aggTrades 14d | `COST_KILLED` x2 | idem |
| M-10 | cross-sectional flow (+dispersión) | 5 | 1, 15 | aggTrades 14d | `COST_KILLED` x2, `NO_INFORMATION` x2 | idem |

## 2. Hipótesis ya medidas antes (evidencia reutilizada, no re-ejecutada)

| ID | hipótesis | estado | evidencia |
| --- | --- | --- | --- |
| M-01 | aggressor flow imbalance | `PREVIOUSLY_TESTED` | `MICROSTRUCTURE_RESULTS_V1.json` (`flow_imbalance_z`, gross ≤ +2.36 bps), `AGGTRADES_RESULTS_V1.json` (A-01) |
| M-04 | flow + breakout | `PREVIOUSLY_TESTED` | `AGGTRADES_RESULTS_V1.json` (A-03, `COST_KILLED`) |
| M-05 | funding extremes | `PREVIOUSLY_TESTED` | `MICROSTRUCTURE_RESULTS_V1.json` (`funding_z`, `NO_GROSS_EDGE` OOS) |
| M-06 | premium/basis | `PREVIOUSLY_TESTED` | `MICROSTRUCTURE_RESULTS_V1.json` (`premium_z`, `NO_GROSS_EDGE`) |
| M-08 | funding + OI | `PREVIOUSLY_TESTED` | `MICROSTRUCTURE_RESULTS_V1.json` (S-07, `LIMITED_HISTORY`) |

## 3. Hipótesis no testeables con los datos actuales

| ID | hipótesis | estado | motivo |
| --- | --- | --- | --- |
| M-03 | book imbalance (spread, depth, microprice) | `FORWARD_COLLECTION_REQUIRED` | `bookTicker`/`depth` no tienen endpoint histórico (SRC-07, `LIVE_ONLY`). Prohibido sintetizar un libro desde OHLCV. |
| — | liquidaciones | `UNUSABLE_VIA_THIS_ENDPOINT` | `GET /fapi/v1/allForceOrders` devuelve **HTTP 404** en el sondeo real del 2026-09-28 (con y sin ventana); no hay fuente pública de liquidaciones disponible desde este entorno. |
| M-07 (DEV/VAL) | cuadrantes OI | `LIMITED_HISTORY` | Binance retiene ~30 días de OI de 5m: 8,928 puntos, todos post-2026-08-26 ⇒ DEV/VAL vacíos. |

## 4. Fuentes auditadas en esta fase

| source_id | fuente | profundidad | clasificación |
| --- | --- | --- | --- |
| SRC-04 | aggTrades bulk diario (spot) | histórico completo (muestra 14d) | `HISTORICAL_USABLE` |
| SRC-01 | klines 5m | 59,905 barras (2026-03-01..09-25) | `HISTORICAL_USABLE` |
| SRC-02 | fundingRate | 624 puntos | `HISTORICAL_USABLE` |
| SRC-03 | premiumIndexKlines 5m | 59,905 puntos | `HISTORICAL_USABLE` |
| SRC-05 | basis | ~30 días | `LIMITED_HISTORY` |
| SRC-06 | openInterestHist 5m | 8,928 puntos (~31 días) | `LIMITED_HISTORY` |
| SRC-07 | bookTicker / depth | sin histórico | `FORWARD_ONLY` (capturado en esta fase: 111 + 111 registros) |
| SRC-13 | liquidations (`allForceOrders`) | 404 | `UNUSABLE_VIA_THIS_ENDPOINT` |

## 5. Reglas del registro

* una hipótesis sin datos suficientes se registra como tal y **no** se declara
  resultado sobre datos que no existen;
* una hipótesis reutilizada apunta a la evidencia original en lugar de
  re-ejecutarse (evita inflar el recuento de experimentos);
* el estado `NEWLY_TESTED` no implica resultado positivo: 7 de 9 candidatas
  nuevas quedaron `COST_KILLED` y 2 `NO_INFORMATION`.
