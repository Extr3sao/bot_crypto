# ABLACION DE MECANISMO - H6 (entrada por retest en el nivel)

| | |
|---|---|
| experimento | `ABL-EDGE01-H6` |
| responde a | `H2` |
| pregunta | H2 measured the intraday book paying for the extension: 236 of 290 DEV fills landed at or past 0.25 ATR above the broken level and only the fills closest to the level carried positive gross. Does entering on a resting limit AT the level — same signals, same stop, same target, same risk budget, same costs — improve the net expectancy, and are the orders actually filled? |
| candidato congelado | `edge_intra_01` |
| variante | `edge_intra_01r` (solo cambia la EJECUCION) |
| split / ventana primaria | `intraday` / `DEV` |
| ventanas de confirmacion | VAL, OOS |
| escenarios | DEV y OOS con `BASE` + `2X_FEES`; VAL con `BASE` |
| desde / hasta (primaria) | `2024-10-01T00:00:00+00:00` .. `2025-06-30T00:00:00+00:00` |
| dias | 272.0 |
| HEAD al ejecutar | `ce42ca42c297fe2b6a6594a49b385ed811442666` |
| huella del codigo ejecutado (sha256) | `616a86fa7258fa9efe2faf1d3b333a87722944aef9796bfa228417014c178c5a` |
| params_hash (candidato congelado) | `d073a2d686b9b198c36c9a3c6009d36130577ba247a2016c3f791813cb749d77` |
| veredicto economico | **`RETEST_IMPROVES_NET`** |
| lectura de ejecucion | **`VIABLE`** |

Las tres ramas son el MISMO presupuesto de riesgo, los MISMOS costes y el MISMO
corpus. `edge_intra_01` cruza al open de la barra siguiente;
`edge_intra_01r` deja una orden limite en el nivel roto y solo se
ejecuta si el precio vuelve. El ruleset congelado no se toca: `params_delta` de
las tres ramas es el mismo diccionario vacio.

## Veredicto

- `RETEST_IMPROVES_NET`: net -495.88 vs -496.43 USDT (+0.55) and expectancy -1.3330 vs -1.7118 (+0.3788) | 372/686 orders filled (54.23%) against the declared floor 40% -> VIABLE | same plans crossed at market: net -496.43 USDT, expectancy -1.7118
- regla congelada: {'RETEST_UNPOWERED': 'fewer orders placed or fills than the declared floors', 'RETEST_IMPROVES_NET': 'net AND expectancy per trade both better than the baseline', 'RETEST_IMPROVES_EXPECTANCY_ONLY': 'expectancy per trade better, net not better', 'RETEST_DOES_NOT_HELP': 'neither net nor expectancy better than the baseline'}
- lectura de ejecucion: {'VIABLE': 'at least the declared share of the placed orders was filled', 'STARVED': 'the plan cannot be executed often enough to matter, whatever its P&L'}
- no reclamado: a favourable economic reading is a hypothesis for a new pre-registered run, not a promotion: nothing is wired into the PAPER runtime and the ruleset in candidates.FROZEN_PARAMS is unchanged

## Ventana primaria (DEV, `BASE`)

| rama | operaciones | neto | expectativa | profit factor | drawdown | exposicion |
|---|---|---|---|---|---|---|
| `frozen_market` | 290 | -496.43 | -1.71 | 0.3224 | 5.0427% | 1.5714% |
| `plan_market` | 290 | -496.43 | -1.71 | 0.3224 | 5.0427% | 1.5714% |
| `plan_limit` | 372 | -495.88 | -1.33 | 0.2912 | 5.0041% | 0.9932% |

| rama | senales | senales con limite | ordenes | rellenos | fill rate | descuento mediano (bps) | barras en reposo (mediana) |
|---|---|---|---|---|---|---|---|
| `frozen_market` | 860 | 0 | 0 | 0 | n/a | n/a | n/a |
| `plan_market` | 860 | 860 | 0 | 0 | n/a | n/a | n/a |
| `plan_limit` | 860 | 860 | 686 | 372 | 54.23% | 0.0000 | 1.0000 |

### Destino de cada orden planificada

| desenlace | ordenes |
|---|---|
| `cancelled_window_end` | 3 |
| `expired` | 128 |
| `filled` | 372 |
| `refused_by_risk_budget` | 183 |

- `discount_bps` es lo que el plan se ahorra comprando en el nivel en vez de en
  el cierre de ruptura; su mediana es el tamano de la apuesta que hace H6.

## Confirmacion fuera de la ventana de diseno

| ventana | neto baseline | neto plan_limit | delta | expectativa baseline | expectativa plan_limit | fill rate |
|---|---|---|---|---|---|---|
| `VAL` | -479.18 | -357.44 | 121.74 | -1.39 | -1.33 | 76.86% |
| `OOS` | -94.81 | -55.71 | 39.10 | -1.50 | -1.03 | 81.82% |

- estres de coste `2X_FEES` en OOS: baseline -133.20 / plan_limit -87.95 USDT

Cada ventana de confirmacion lleva la misma nota que el JSON: las reglas del plan
se congelaron antes de correr ninguna de las tres ventanas y no se re-ajusto nada
despues, pero el diagnostico que motivo el plan sale de DEV, asi que DEV es su
ventana de diseno y las otras dos son evidencia, no decision.

## Artefactos de este experimento

- `RETEST.json` — las tres ramas, el destino de cada orden y el veredicto
- `RETEST_TRADES.csv` — operaciones ejecutadas por rama, ventana y escenario
- `RETEST_ORDERS.csv` — una fila por orden planificada, con su desenlace
- `RETEST_SIGNALS.csv` — senales del candidato con el plan de entrada
- `RETEST_REFUSALS.csv` — rechazos por origen y motivo
- `MARKET_CONTEXT.csv` — la serie de benchmark con la que se etiqueta cada operacion
- verificado por `scripts/edge01_closure_verify.py --experiment h6` en un proceso aparte

## Limites

- the signals are the frozen candidate's, so this experiment cannot be better than the signals it inherits: it isolates the entry price, not the setup
- a limit that fills only when price comes back is filled precisely when the breakout is failing — adverse selection. Without a historical order book the model cannot charge for it, so the fill is charged the SAME spread, slippage, impact and fee as a market entry and the limit is always filled at the level, never better
- queue position is not modelled: a bar that merely touches the level is treated as a fill. That is the optimistic side of the fill rule, and it is why the fill rate is published per order rather than assumed
- the expiry (8 bars of 15m) is declared here and was not tuned: a longer window would fill more orders at prices further from the diagnosis
- the risk budget is consulted at the moment of the touch, so an order can be cancelled by a refusal the market arm would never have met; those orders are published with the refusal reason
- single corpus window per split; no historical order book; long side only (spot)
