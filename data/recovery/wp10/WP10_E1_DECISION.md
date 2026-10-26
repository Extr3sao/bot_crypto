# WP-10 E-1 — DECISIÓN ECONÓMICA

> `2026-10-12T06:10:29Z` · head `90ed615b1b2514682bbf9a85834fdd81c45f0774` · modo `OFFLINE READ-ONLY — no process, no order, no key, no network, no capital`

PARTIAL — the plane's non-fee allowance is conservative at the median (measured, not asserted) and is not the binding constraint: the KNOWN fee legs alone exceed the best gross edge in the register, so no execution improvement available in this capture can admit any of the 24 cells

## 0. Las tres planicies que no deben confundirse

| planicie | round trip bps | fees bps | no-fee bps | conocimiento |
| --- | ---: | ---: | ---: | --- |
| `frozen_admission` | 23.353553 | 20.000000 | 3.353554 | fees KNOWN (published schedule) + non-fee ESTIMATED (heuristic) |
| `measured` | 20.024697 | 20.000000 | 0.024697 | fees KNOWN + non-fee OBSERVED_FORWARD (this seal, BTC/ETH, 50-2000 USDT) |
| `measured_worst_tail` | 24.586320 | 20.000000 | 4.586320 | fees KNOWN + non-fee OBSERVED_FORWARD p95 of the worst book's realised round trip |
| `baseline_arm` | 12.000000 | 10.000000 | 2.000000 | ASSUMED (documented execution contract of the baseline backtest) |
| `discounted_fee_tier` | 15.024697 | 15.000000 | 0.024697 | fees KNOWN (published alternative tier) + non-fee OBSERVED_FORWARD |

La planicie de admisión congelada es contra la que se tomaron los 24 veredictos; la medida describe lo que el libro capturado cobró; la del *baseline arm* es con la que se calculó la expectancy neta publicada de cada celda. Ninguna se sustituye por otra aquí.

## 1. ¿Sobreestima, infraestima o representa razonablemente los costes observables?

It overstates the *centre* of observable execution cost and sits near the tail: at the median the measured non-fee cost is 0.024697 bps against the plane's 3.353554 bps ESTIMATED non-fee allowance (136x), but the plane's allowance is *below* the p95 of realised taker cost on the worst book (4.5863 bps). It is conservative as a median estimate and roughly a p95-p99 allowance, so it is not uniformly generous and the difference is not free budget.

* observado: round trip microstructure median across four books 0.024697 bps; realised aggressor round trips {'spot/BTCUSDT': 0.065705, 'spot/ETHUSDT': 0.487184}; worst book p95 4.5863 bps; worst single checkpoint 0.3680 bps
* supuesto: that the plane's non-fee terms were ever intended as a median rather than as a conservative allowance — the artefacts do not say which

## 2. ¿En qué condiciones aparecen costes materialmente menores?

Only in the fee schedule, and only by a factor of ~2.3 bps: the non-fee component measured at or near its floor (0.024697 bps median, 0.0 bps of book walk at every size up to 2000 USDT), so no re-optimisation of order placement can move a round trip by more than ~3.35 bps. The published token-discounted tier moves it by 5.0 bps, and that is an account/tier decision, not an execution-skill finding.

* observado: fees are 20 of the 23.3536 bps and are KNOWN from the schedule; measured walk beyond best 0.0 bps at every size on all four books
* supuesto: that any future order would in fact receive the tier the schedule publishes — no account statement exists in this repository

## 3. ¿Son frecuentes y ejecutables esas condiciones?

The fee tier is available on essentially every taker order and therefore frequent and executable; the measured cheap execution is *evidence about a book state*, not about a fill. Nothing in the capture records order lifecycle, queue position or partial fills, so maker execution cannot be claimed as available at all.

* observado: the measured window is one 4.1 h session of a single regime; 496 checkpoints; no order was placed
* supuesto: nothing: the maker question is reported INSUFFICIENT_EVIDENCE rather than assumed away

## 4. ¿Qué factores explican la mayor parte del coste?

The fee schedule: 85.64 % of the plane is two KNOWN exchange fee legs, which no market condition in this capture could change. Everything the venue's book contributed, at the median, is 0.11 % of the plane.

* observado: plane decomposition rebuilt in-process; measured non-fee cost across four books and a 50-2000 USDT size ladder
* supuesto: the published fee schedule applies (a documented policy, not a measurement)

## 5. ¿Hay activos o modalidades que merezcan más investigación?

No asset in this seal offers a materially better net condition: the difference between the best and worst book's realised round trip (0.0657 vs 0.4872 bps) is two orders of magnitude below the fee floor, so asset selection is not where the economics are decided. The only modality that could change the answer is maker execution priced from order-level evidence, which requires a capture this campaign does not have; it is recorded as a gap, not recommended as a result.

## 6. ¿Qué parte se basa en datos observados y qué parte en supuestos?

The measured layer is OBSERVED_FORWARD and cannot promote anything: the best gross edge in the register is 8.912 bps and the KNOWN fee legs alone are 20.0 bps, so even a hypothetically free non-fee component leaves 0 of the 24 cells net positive (none). The fee level, the tiers and any change to the plane are governance assumptions, not measurements.

## 7. Re-adjudicación aritmética: ninguna planicie admite nada

Se recalcula cada celda contra cada planicie usando la ventaja bruta a coste cero que la fase 1 reconstruyó a partir de las fuentes primarias. Esto **no** reabre ninguna estrategia: es aritmética sobre decisiones ya tomadas.

| planicie | admitidas |
| --- | ---: |
| `frozen_admission` | 0 |
| `measured` | 0 |
| `measured_worst_tail` | 0 |
| `baseline_arm` | 0 |
| `discounted_fee_tier` | 0 |

* mejor celda del registro: `volatility@30m` con 8.912 bps a coste cero
* planicie que haría falta para admitirla: **< 8.912 bps** por round trip, es decir un coste por lado de 4.443652 bps frente a los 10 bps publicados (7.5 bps con descuento de token)
* ventaja bruta necesaria para superar la planicie medida: 20.0247 bps = 2.2469x la mejor observada

the plane is not the binding constraint: no plane at or above the best cell's own gross edge admits anything, and the best cell's gross edge is the number that has to move

### El registro completo

| estrategia | familia | tf | estado | gross bps | net @ congelada | net @ medida | net @ medida-p95 | net @ baseline arm | CI95 ± bps |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| volatility@30m | volatility | 30m | COST_KILLED | 8.912 | -14.441553 | -11.112697 | -15.67432 | -3.088 | 12.009576 |
| volatility@1h | volatility | 1h | COST_KILLED | 6.276 | -17.077553 | -13.748697 | -18.31032 | -5.724 | 18.564808 |
| mean_reversion@30m | mean_reversion | 30m | COST_KILLED | 5.472 | -17.881553 | -14.552697 | -19.11432 | -6.528 | 5.272215 |
| mean_reversion@15m | mean_reversion | 15m | COST_KILLED | 2.714 | -20.639553 | -17.310697 | -21.87232 | -9.286 | 3.591391 |
| trend@30m | trend | 30m | COST_KILLED | 2.206 | -21.147553 | -17.818697 | -22.38032 | -9.794 | 4.771974 |
| mean_reversion@5m | mean_reversion | 5m | COST_KILLED | 1.485392 | -21.868161 | -18.539305 | -23.100928 | -10.514608 | — |
| trend@15m | trend | 15m | COST_KILLED | 1.284 | -22.069553 | -18.740697 | -23.30232 | -10.716 | 4.52761 |
| breakout@5m | breakout | 5m | NO_GROSS_EDGE | -0.084007 | -23.43756 | -20.108704 | -24.670327 | -12.084007 | — |
| breakout@1h | breakout | 1h | NO_GROSS_EDGE | -0.222 | -23.575553 | -20.246697 | -24.80832 | -12.222 | 6.444677 |
| ema_crossover@30m | ema_crossover | 30m | NO_GROSS_EDGE | -0.726 | -24.079553 | -20.750697 | -25.31232 | -12.726 | 2.685637 |
| ema_crossover@1h | ema_crossover | 1h | NO_GROSS_EDGE | -0.964 | -24.317553 | -20.988697 | -25.55032 | -12.964 | 3.279934 |
| ema_crossover@15m | ema_crossover | 15m | NO_GROSS_EDGE | -1.122 | -24.475553 | -21.146697 | -25.70832 | -13.122 | 2.367062 |
| trend@1h | trend | 1h | NO_GROSS_EDGE | -1.252 | -24.605553 | -21.276697 | -25.83832 | -13.252 | 5.370709 |
| trend@5m | trend | 5m | NO_GROSS_EDGE | -1.644771 | -24.998324 | -21.669468 | -26.231091 | -13.644771 | — |
| breakout@30m | breakout | 30m | NO_GROSS_EDGE | -1.792 | -25.145553 | -21.816697 | -26.37832 | -13.792 | 4.430577 |
| breakout@15m | breakout | 15m | NO_GROSS_EDGE | -1.822 | -25.175553 | -21.846697 | -26.40832 | -13.822 | 3.168101 |
| momentum@5m | momentum | 5m | NO_GROSS_EDGE | -1.883531 | -25.237084 | -21.908228 | -26.469851 | -13.883531 | — |
| mean_reversion@1h | mean_reversion | 1h | NO_GROSS_EDGE | -2.226 | -25.579553 | -22.250697 | -26.81232 | -14.226 | 8.692807 |
| momentum@1h | momentum | 1h | NO_GROSS_EDGE | -2.334 | -25.687553 | -22.358697 | -26.92032 | -14.334 | 3.674085 |
| momentum@30m | momentum | 30m | NO_GROSS_EDGE | -2.612 | -25.965553 | -22.636697 | -27.19832 | -14.612 | 2.931925 |
| momentum@15m | momentum | 15m | NO_GROSS_EDGE | -3.972 | -27.325553 | -23.996697 | -28.55832 | -15.972 | 2.593819 |
| ema_crossover@5m | ema_crossover | 5m | NO_GROSS_EDGE | -4.560812 | -27.914365 | -24.585509 | -29.147132 | -16.560812 | — |
| volatility@5m | volatility | 5m | NO_GROSS_EDGE | -4.735385 | -28.088938 | -24.760082 | -29.321705 | -16.735385 | — |
| volatility@15m | volatility | 15m | NO_GROSS_EDGE | -7.064 | -30.417553 | -27.088697 | -31.65032 | -19.064 | 9.374829 |

## 8. Incertidumbre de las ventajas brutas

* celdas con ventaja bruta positiva: 7
* celdas positivas con intervalo estimable: 6
* celdas positivas cuyo intervalo excluye el cero: 1
* intervalo de la mejor celda: ±12.009576 bps (95 %)

the best gross edge is quoted from 196 trades and its own 95 % envelope is ±12.009576 bps, so an E-1 improvement of ~3 bps is two orders of magnitude smaller than the uncertainty in the quantity it would have to rescue

## 9. Funding

* mediana observada: 0.5985 bps por intervalo de 3/día = 1.7955 bps/día
* a position that spans a funding stamp pays the measured median; at a 30 min horizon the expected drag is a small fraction of one stamp, and it never favours the strategy because the sign is not controlled

## 10. Limitaciones

* one sealed window of 4.159301 h in one session regime, stopped by the run's own disk valve rather than by a measurement boundary
* BTC and ETH only; the register's SOL arm is not covered by this seal
* the size ladder is a static book walk; a real order arrives at a moving book, and the measured receive-clock latency (median ~187 ms on the busiest perp stream) is the size of that motion
* no order was ever placed, so every number here is an estimate of what an order would have paid, never a fill
* maker execution, queue position, partial fills and fill probability are not measurable from this capture: INSUFFICIENT_EVIDENCE
* the per-cell gross edges the re-adjudication uses are themselves unresolved at the published sample sizes, which is a limitation of the register and not of E-1
* this is a RESEARCH_RESULT about cost. It is not a PROFITABILITY_VERIFIED claim and it authorises no campaign

## 11. Controles

* [x] the register holds 24 cells and every one is re-adjudicated at every plane
* [x] the plane under test re-derives to the frozen value
* [x] the KNOWN fee legs are carried as KNOWN and the measured layer as OBSERVED
* [x] no strategy is admitted, promoted or re-classified by this decision
* [x] no threshold, criterion or cost model is modified
* [x] the measured layer is used to describe cost, never to declare edge
* [x] every answer separates the observed part from the assumed part

## 12. Lo que esta decisión NO hace

* no admite, promueve ni reabre ninguna estrategia;
* no modifica la planicie congelada, los criterios ni el modelo de coste;
* no declara ventaja explotable a partir de un libro barato;
* no convierte una estimación de coste en un resultado de profitability.

