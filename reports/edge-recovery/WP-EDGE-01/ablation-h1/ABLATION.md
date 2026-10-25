# ABLATION H1 — EDGE-INTRA-01 sin el filtro de tendencia de 1h

- run_id: `wp-edge-01-ablation-h1`
- hipotesis: H1 (removed: `use_trend_filter`)
- ventana: DEV 2024-10-01..2025-06-30 (SOLO DEV: VAL y OOS no se leen)
- activos: BTC, ETH, SOL (spot, long only)
- escenario de coste: BASE
- params_hash (reglas congeladas): `d073a2d686b9b198c36c9a3c6009d36130577ba247a2016c3f791813cb749d77`
- huella del codigo medido: `b49a8ff224133534e1519aaa6b33de6f82f30317d580c6ef81dbca9005084376`
- commit: `ce42ca42c297fe2b6a6594a49b385ed811442666`

## Veredicto

**BREAKOUT_IS_THE_CAUSE** — the ablation's DEV gross is -128.96 USDT before costs, not positive: the entry rule loses without the filter's help, so the filter was not hiding an edge

Regla fijada antes de ejecutar:

> DEV gross (before costs) of the ablation versus 0, then its net: <= 0 -> BREAKOUT_IS_THE_CAUSE; > 0 with net <= 0 -> FILTER_SUPPRESSED_A_PRECOST_EDGE; > 0 with net > 0 -> FILTER_HARMS_EDGE; either arm below the minimum DEV trades -> INCONCLUSIVE.

## Bruto antes de costes (DEV)

| corrida | filtro 1h | operaciones | senales | bruto (mid-to-mid) | comisiones | coste de precio | neto | bruto/op |
|---|---|---|---|---|---|---|---|---|
| base | si | 290 | 860 | -151.71 | 289.79 | 54.92 | -496.43 | -0.52 |
| ablacion | no | 313 | 1528 | -128.96 | 312.81 | 59.29 | -501.06 | -0.41 |

El bruto es el resultado mid-to-mid de cada operacion ya ejecutada: aísla la direccion elegida de spread, slippage, impacto y comisiones.

## Embudo de rechazos (DEV)

| motivo (origen:razon) | base | ablacion | delta |
|---|---|---|---|
| candidate:level_already_traded | 584 | 983 | +399 |
| candidate:reward_below_cost | 9 | 13 | +4 |
| candidate:rr_below_minimum | 105 | 197 | +92 |
| candidate:stop_too_wide | 55 | 78 | +23 |
| candidate:trend_filter_fail | 1,097 | 0 | -1,097 |
| candidate:volume_filter_fail | 550 | 461 | -89 |
| risk:risk_drawdown_halt | 493 | 1,123 | +630 |
| risk:risk_loss_cooldown | 17 | 20 | +3 |

| barometro | base | ablacion |
|---|---|---|
| barras evaluadas | 78,279 | 78,279 |
| barras de warm-up | 60 | 60 |
| senales impresas | 860 | 1,528 |
| operaciones ejecutadas | 290 | 313 |

Multiplo de senales ablacion/base: 1.7767.

## Contexto de mercado de las operaciones (benchmark BTC, as-of la decision)

- base: BULL=290 (-496.43 USDT)
- ablacion: BULL=313 (-501.06 USDT)
- Las dos ramas operaron con el benchmark en **BULL** en el 100% de sus operaciones: la comparacion cae dentro de una sola etiqueta de mercado y no mezcla regimenes, asi que un bruto negativo aqui no se explica por haber medido en un mercado adverso.

## Artefactos de esta ablacion

- `ABLATION.json` — comparacion completa, regla congelada y veredicto
- `ABLATION_TRADES.csv` — operaciones de las dos corridas en DEV
- `ABLATION_REFUSALS.csv` — rechazos crudos (origen y motivo)
- `ABLATION_SIGNALS.csv` — senales impresas por el candidato, antes del riesgo
- `MARKET_CONTEXT.csv` — la serie de benchmark (BTC diario) con la que se etiqueta cada operacion, reproducida aqui para que el verificador la re-derive
- verificado por `scripts/edge01_ablation_verify.py` en un proceso aparte que solo lee estos ficheros

## Limitaciones de esta ablacion

- Medida SOLO en DEV: al haberse disenado despues de leer VAL y OOS, no puede usar esas ventanas sin volverlas in-sample.
- Un veredicto de filtro/breakout en DEV no es una conclusion de rentabilidad; cualquier variante que promueva tendria que pasar de nuevo el proceso pre-registrado (VAL congelado, luego OOS una sola vez).
- Sin libro de ordenes historico: el bruto mid-to-mid no incluye seleccion adversa; el coste de precio modelado cubre spread, slippage e impacto.
- Solo lado largo (spot).
