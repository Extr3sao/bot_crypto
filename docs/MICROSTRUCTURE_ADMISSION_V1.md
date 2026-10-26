# MICROSTRUCTURE_ADMISSION_V1 (§41-42, §54-59)

> Aplicación de los criterios pre-registrados. Máquina:
> `docs/MICROSTRUCTURE_ADMISSION_V1.json`.

Fecha: 2026-09-26. Coste de admission: `REALISTIC_RETAIL_COST_MODEL` = 23.5 bps.
`REQUIRED_EDGE_BPS = 23.5 × 1.5 = 35.25`.

## 1. Criterios aplicados (§41)

Una candidata es `PAPER_CANDIDATE` solo si, con el coste realista:
1. edge bruto > 0 y net > 0 con margen (net > 0.25 × coste)
2. n total >= 100 y n OOS >= 30
3. PF_OOS > 1.0
4. DEV > 0, VAL > 0, OOS > 0
5. sin NEGATIVE_ROBUST
6. integridad PIT sin violaciones
7. coste entendido: sobrevive 1.5X con margen

Ninguna candidata satisface el criterio 1 (edge bruto > 0 **y** net con
margen): los gross positivos están 10x por debajo del coste; los demás son
negativos.

## 2. Matriz de admission

| Candidate | gross>0 | net>0 | margen | n>=100 | OOS>=30 | splits+ | stress1.5x | **Admitted** |
| --- | :-: | :-: | :-: | :-: | :-: | :-: | :-: | :-: |
| S-01 flow_imbalance_z | ✔ | ✘ | ✘ | ✔ | ✔ | ✔ | ✘ | **NO** |
| S-03 flow breakout | ✔ | ✘ | ✘ | ✔ | ✔ | ✔ | ✘ | **NO** |
| S-04 funding | ✔ | ✘ | ✘ | ✔ | ✔ | ✘ | ✘ | **NO** |
| S-05 premium | ✘ | ✘ | ✘ | ✔ | ✔ | ✘ | ✘ | **NO** |
| S-06 OI+price | ✘ | ✘ | ✘ | ✔ | ✔ | ✘ | ✘ | **NO** |
| S-07 funding+OI | ✘ | ✘ | ✘ | ✘ | ✔ | ✘ | ✘ | **NO** |
| S-08 BTC lead/lag | ✘ | ✘ | ✘ | ✔ | ✔ | ✘ | ✘ | **NO** |
| S-02 book imbalance | — | — | — | — | — | — | — | **NO (no testeable)** |

```text
ADMITTED = []
PAPER_CANDIDATES = 0
```

## 3. Decisión sobre SPOT (§58)

Para el tipo de estrategia investigado (intraday taker con entradas
market/limit), los datos muestran que el coste spot de Binance a nivel retail
VIP0 (≈23.5 bps RT) excede cualquier edge bruto observado en las fuentes
testeables (<= 2.4 bps tradeable).

```text
SPOT_INTRADAY_COST_BLOCKED
```

(No generalizable a todo trading; sí a las estrategias intradía taker sobre
estos activos y este timeframe. Maker no rescata porque a VIP0 no reduce fee.)

## 4. Decisión sobre DERIVADOS (§59)

Funding y premium histórico muestran relación débil con retornos a horizonte
largo (h60), pero (a) IC ~0.03, (b) confundido con régimen, (c) la regla
direccional pre-registrada no sobrevive OOS, y (d) el runtime **excluye**
derivados.

No hay evidencia suficiente para justificar construir ejecución de derivados
direccional.

```text
DERIVATIVES_NO_EVIDENCE
```

Nota: esto **no** descarta una estrategia *market-neutral de carry/funding*
(clase de mecanismo distinta, sin dirección; §49). Eso sería investigación
aparte, con su propio accounting y sin conectar al runtime spot actual.

## 5. Gate maker (§13)

```text
MAKER EDGE GATE = FAIL
```

No se reabre ninguna candidata OHLCV/microstructure rechazada por costes:
no hay fill model, y a VIP0 maker = taker en fee.

## 6. Estado final de la fase

```text
FINAL STATUS: MICROSTRUCTURE_V1_NO_EDGE_FOUND
```

Calificado: el no-edge aplica a las hipótesis **históricamente testeables**
(M-01, M-03, M-04, M-05, M-06, M-08). M-02 (order book) y la parte OI-based de
M-06/M-07 (más allá de 30d) **no son testeables** sin forward collection; no se
declara resultado sobre datos que no existen (§63).
