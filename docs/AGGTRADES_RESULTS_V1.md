# AGGTRADES_RESULTS_V1 — resultados

Fecha: 2026-09-27. JSON: `docs/AGGTRADES_RESULTS_V1.json`.
Salida completa: `reports/microstructure-v1/AGGTRADES_RESULTS.json`.
Verificación: `docs/MICROSTRUCTURE_V1_INDEPENDENT_VERIFICATION.md` (Fase 7 **VERIFIED**).

Coste de admission: `BINANCE_SPOT_STANDARD_TAKER` = **23.791 bps** RT.
Umbral con margen ×1.5 = **35.69 bps**.

## 1. Tabla de candidatas (§55)

| Candidate | Data | Horizon | Trades | Gross Edge bps | Realistic Cost bps | Net Edge bps | Net PF | Net DD bps | Status |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| A-01 flow imbalance (tick) | aggTrades | 25 min | 4,420 | **+0.481** | 23.79 | −23.310 | 0.12 | 104,445 | COST_KILLED |
| A-02 large-clip imbalance | aggTrades | 25 min | 5,943 | +0.031 | 23.79 | −23.759 | 0.13 | 142,907 | COST_KILLED |
| A-03 flow + breakout | aggTrades | 25 min | 2,563 | **+0.614** | 23.79 | −23.177 | 0.13 | 61,270 | COST_KILLED |
| A-04 inter-arrival burst | aggTrades | 25 min | **0** | n/a | 23.79 | n/a | n/a | n/a | INSUFFICIENT_DATA |
| A-05 VWAP pressure reversal | aggTrades | 25 min | 279 | −6.253 | 23.79 | −30.044 | 0.33 | 6,702 | NO_GROSS_EDGE |
| A-06 BTC lead/lag (tick) | aggTrades | 5 min | 12,012 | +0.553 | 23.79 | −23.238 | 0.03 | 280,411 | COST_KILLED |

`PAPER_CANDIDATE`: **0**. `FALSE_SUCCESS`: **0**.

## 2. Filter 0 — contenido informativo

Medido antes de construir señales (§32), con Spearman sobre días DEV:

| feature | ρ̄ DEV | observaciones | informativo |
| --- | ---: | ---: | --- |
| `ret_mom_bps` | −0.0567 | 6,504 | sí |
| `F7_vwap_dislocation_bps` | −0.0503 | 6,792 | sí |
| `F4_trade_intensity_z` | +0.0359 | 6,336 | sí |
| `F2_trade_imbalance` | −0.0176 | 6,792 | sí |
| `F1_signed_flow_imbalance` | −0.0142 | 6,792 | sí |
| `F6_abs_flow_z` | +0.0126 | 6,336 | sí |
| `F3_large_trade_imbalance` | −0.0038 | 4,472 | no |

Lectura honesta: **todos** los |ρ| son < 0.06. Las features tick-level contienen
información del tipo correcto, pero de magnitud económicamente irrelevante. El
|ρ| más alto de toda la fase implica un edge por trade ~2 órdenes de magnitud
por debajo del coste. F3 (clips grandes) ni siquiera supera el mínimo.

## 3. Resultado central

```text
mejor gross DEV de la fase      = +0.614 bps  (A-03)
mejor gross de cualquier split  = +11.775 bps (A-05 en VAL)
mejor net de cualquier split    = -12.016 bps (A-05 en VAL)
coste de admission              =  23.791 bps
ninguna candidata con net > 0
```

El mejor gross de la fase queda **~39× por debajo** del coste. Ni siquiera la
celda más favorable de toda la matriz (A-05 en VAL: +11.78 bps brutos) alcanza
el coste; su net sigue siendo −12.02 bps.

## 4. Hallazgo incómodo: 4 de 6 candidatas cambian de signo entre splits

| candidata | signo gross DEV | VAL | OOS | flip |
| --- | ---: | ---: | ---: | --- |
| A-01 | + | + | **−** | sí |
| A-02 | + | **−** | **−** | sí |
| A-03 | + | **−** | **−** | sí |
| A-05 | **−** | **+** | **+** | sí |
| A-06 | + | + | + | no |

Esto importa mucho más de lo que parece: **A-05** tiene DEV negativo y
VAL/OOS positivos. Si la dirección o el período se eligieran después de ver los
datos, A-05 parecería una candidata de +8.6 a +11.8 bps brutos. La regla
pre-registrada (dirección congelada de DEV; Filter 1 sobre DEV) la rechaza, y se
mantiene el rechazo. Es exactamente la trampa contra la que existe el
pre-registro.

A-06 es la única con signo estable en los tres splits, y sigue estando ~43× por
debajo del coste.

## 5. Por qué esto NO contradice, sino que cierra, la línea tick-level

La fase V1 midió el flujo agresor **agregado por kline** y obtuvo el mejor gross
tradeable de +2.36 bps. La hipótesis de esta fase era que el tick real tenía
más información. Resultado medido:

```text
kline-aggregated flow (V1)     +2.36 bps
tick-level flow (A-01)         +0.48 bps
tick-level flow+breakout (A-03) +0.61 bps
BTC lead/lag tick (A-06)       +0.55 bps
```

**Más granularidad no añadió edge ejecutable: añadió ruido.** El agregado por
kline, al promediar, ya extraía la parte informativa del flujo; el tick
individual es mayoritariamente ruido de microestructura.

## 6. Cost stress

| candidata | gross | 1.0x (23.79) | 1.25x (29.74) | 1.5x (35.69) |
| --- | ---: | --- | --- | --- |
| A-01 | +0.481 | falla | falla | falla |
| A-03 | +0.614 | falla | falla | falla |
| A-06 | +0.553 | falla | falla | falla |

Ninguna sobrevive ni el caso base. El estrés es informativo solo para mostrar
que el margen no es delgado: es inexistente.

## 7. Interpretación de negocio

```text
BEST TRADEABLE GROSS EDGE (tick)    +0.61 bps
BINANCE SPOT VIP0 TAKER COST        23.79 bps
MEXC SPOT TAKER COST (contexto)     17.79 bps
```

Incluso en el venue spot más barato investigado, el mejor edge tick-level
medido queda **~29× por debajo** del coste. La conclusión de V1 se refuerza con
una fuente de datos nueva: **no es un problema de resolución de datos, es un
problema de escala de señal frente al fee del venue**.

## 8. Defectos

| id | severidad | estado |
| --- | --- | --- |
| `DEFECT-AG-01` | P2 | **corregido** — aggTrades en microsegundos; la primera ejecución produjo 62k filas/día; se borró y se añadió detección de unidad + fail-closed + test de regresión |
| `DEFECT-AG-02` | P3 | **declarado, no corregido por disciplina de pre-registro** — `F5_interarrival_accel` degenerado a resolución ms (97.7 % de minutos con min inter-arrival 0) → A-04 no testeable |

`P0` abiertos: 0. `P1` abiertos: 0.

## 9. Veredicto

```text
AGGTRADES_MICROSTRUCTURE_V1: NO_EDGE_FOUND
PAPER CANDIDATES: 0
FALSE_SUCCESS: 0
```

Ninguna hipótesis se promociona; ninguna se re-optimiza. `DO_NOT_ADOPT`.
