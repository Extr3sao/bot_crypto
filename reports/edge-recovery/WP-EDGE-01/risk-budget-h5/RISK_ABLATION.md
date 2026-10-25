# RIESGO H5 — EDGE-INTRA-01 con el kill switch de drawdown inerte (SOLO DEV)

- run_id: `wp-edge-01-risk-ablation-h5`
- candidato: `edge_intra_01` (reglas congeladas, sin cambios)
- presupuesto base: config/risk.yaml verbatim (the runtime's own authority)
- presupuesto variante: the same budget with the peak-to-trough drawdown halt made inert (drawdown_halt_pct=100), so the halt can never fire
- unico campo distinto: `drawdown_halt_pct` = 100.0
- ventana: DEV 2024-10-01..2025-06-30 (SOLO DEV: VAL y OOS no se leen)
- activos: BTC, ETH, SOL (spot, long only)
- escenario de coste: BASE
- config de riesgo leida tal cual: `config/risk.yaml` (sha256 `3c27c866d5f1`)
- params_hash de las reglas: `d073a2d686b9b198c36c9a3c6009d36130577ba247a2016c3f791813cb749d77`
- huella del codigo medido: `c40535be9c18179a`

## Veredicto

**RISK_NOT_BINDING_ON_PROFITABILITY** — the halt refused 493 entries in the base arm and releasing it added 380 trades worth -396.46 USDT net: the trades it refused were not worth taking, so the budget is not what makes intraday unprofitable

Regla fijada antes de ejecutar:

> extra_trades = variant.trades - base.trades. Fewer than min_extra_trades -> INCONCLUSIVE; else marginal_net = variant.net - base.net: <= 0 -> RISK_NOT_BINDING_ON_PROFITABILITY; > 0 with the variant still net <= 0 -> RISK_BUDGET_WAS_THE_CONSTRAINT; > 0 and the variant net > 0 -> FREQUENCY_VIABLE.

## Los dos presupuestos

| campo | base (config/risk.yaml) | variante |
|---|---|---|
| `consecutive_loss_cooldown_minutes` | 60.0 | 60.0 |
| `drawdown_halt_pct` | **5.0** | **100.0** |
| `max_asset_exposure_pct` | 10.0 | 10.0 |
| `max_consecutive_losses` | 3 | 3 |
| `max_notional_usdt` | 500.0 | 500.0 |
| `max_open_positions` | 3 | 3 |
| `max_total_exposure_pct` | 25.0 | 25.0 |
| `max_trades_per_day` | 20 | 20 |
| `min_notional_usdt` | 20.0 | 20.0 |
| `risk_per_trade_pct` | 0.25 | 0.25 |
| `start_equity` | 10000.0 | 10000.0 |

## Efecto sobre el embudo y sobre la cuenta (DEV)

| metrica | base | variante | delta |
|---|---|---|---|
| senales impresas | 860 | 860 | +0 |
| operaciones ejecutadas | 290 | 670 | +380 |
| bruto (mid-to-mid) | -151.71 | -96.18 | +55.54 |
| bruto por operacion | -0.52 | -0.14 | +0.38 |
| comisiones | 289.79 | 669.78 | +379.98 |
| coste de precio | 54.92 | 126.94 | +72.02 |
| neto | -496.43 | -892.89 | -396.46 |
| expectancy por operacion (neto/op) | -1.71 | -1.33 | +0.38 |
| max drawdown % | 5.04 | 9.15 | +4.11 |
| exposicion % del tiempo | 1.57 | 3.79 | +2.22 |
| rechazos por kill switch | 493 | 0 | -493 |
| dias con el kill switch activo | 86 | 0 | -86 |
| % de la ventana con el kill switch activo | 31.62 | 0 | -31.62 |

## Embudo de rechazos (DEV)

| motivo (origen:razon) | base | variante | delta |
|---|---|---|---|
| candidate:level_already_traded | 584 | 584 | +0 |
| candidate:reward_below_cost | 9 | 9 | +0 |
| candidate:rr_below_minimum | 105 | 105 | +0 |
| candidate:stop_too_wide | 55 | 55 | +0 |
| candidate:trend_filter_fail | 1,097 | 1,097 | +0 |
| candidate:volume_filter_fail | 550 | 550 | +0 |
| risk:risk_drawdown_halt | 493 | 0 | -493 |
| risk:risk_loss_cooldown | 17 | 37 | +20 |

## Lectura marginal

- operaciones extra: **380** (expectancy marginal -1.04 USDT/op)
- bruto marginal: 55.54 USDT sobre el neto marginal -396.46 USDT
- bruto por operacion: -0.52 -> -0.14 USDT (la entrada marginal elige direccion algo mejor, pero sigue sin pagar su coste de ida y vuelta)
- drawdown: 5.04% -> 9.15% (4.11 puntos)

Las dos ramas son **dos trayectorias de capital distintas**: el tamano de cada operacion se deriva del equity del momento, asi que la diferencia mide el efecto del presupuesto, no una atribucion operacion a operacion. Lo que si es una medida directa de si el riesgo dominaba el embudo es el ciclo de trabajo del kill switch (dias y rechazos) y la expectancy marginal de arriba.

## Contexto de mercado de las operaciones

- base: BULL=290 (-496.43 USDT)
- variant: BEAR=51 (-72.58 USDT), BULL=567 (-789.26 USDT), SIDEWAYS=52 (-31.05 USDT)
- etiquetas de benchmark presentes en la comparacion: BEAR=51, BULL=857, SIDEWAYS=52
- El kill switch **censuro la cobertura**: la variante opera en BEAR, SIDEWAYS, etiquetas que la corrida base no llega a tocar en toda la ventana. Un limite de riesgo que se dispara no solo reduce operaciones: cambia el mercado que se mide, asi que la muestra base no es una version mas pequena de la variante sino una muestra truncada.

## Artefactos de esta ablacion de riesgo

- `RISK_ABLATION.json` — comparacion completa, regla congelada y veredicto
- `RISK_TRADES.csv` — operaciones de las dos corridas
- `RISK_REFUSALS.csv` — rechazos crudos (origen y motivo)
- `RISK_SIGNALS.csv` — senales del candidato antes del riesgo
- `MARKET_CONTEXT.csv` — la serie de benchmark con la que se etiqueta cada operacion
- verificado por `scripts/edge01_risk_ablation_verify.py` en un proceso aparte

## Limites

- El presupuesto variante es un **instrumento de investigacion**, no una politica: `config/risk.yaml` se lee, nunca se escribe, y nada de esto se cablea en el runtime PAPER.
- Medido SOLO en DEV. El comportamiento del kill switch en VAL/OOS ya se observo en la corrida del WP, asi que volver a tocarlo ahi no seria fuera de muestra.
- Quitar el kill switch es quitar una proteccion, no solo un limite: el drawdown de la variante se publica arriba para que la comparacion no se lea como una mejora gratuita.
- Sin libro de ordenes historico y solo lado largo (spot).
