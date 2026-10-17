# WP-EDGE-015 — run report

*Generated 2026-10-17T07:40Z against `a6943c4`. `FALSE_SUCCESS=0`, `BUILDER != VERIFIER`.*
*No real order, no credential, no leverage, no risk limit changed.*

## Execution classes, kept apart

| class | what it is | produced? |
| --- | --- | --- |
| `DEFECT_REPAIR` | certification defects closed with executed evidence | yes |
| `HISTORICAL_RESEARCH` | families measured on consumed 1h corpora, priced per venue | yes |
| `EXPERIMENTAL_PROSPECTIVE_PAPER` | new bars driven through the real broker and the real risk policy, in an isolated lane | yes |
| `PROSPECTIVE_HOLDOUT` | bars after the frozen protocol | **frozen, accruing, 0 bars so far** |

A historical measurement is never presented as prospective, and the lane's cycles are never
counted as an admitted strategy's operations.

## P0 — the certification defects

| # | defect | what was done | evidence |
| --- | --- | --- | --- |
| P0.1 | `order_check=false`: the 14R holdout could not show its freeze preceded its capture | a **two-phase** protocol: `--freeze` writes and commits, `--capture` runs later in another process; the check now has five clauses and a verdict | `OOS_PREREGISTRATION_V2.json`, `OOS_CAPTURE_MANIFEST_V2.json` |
| P0.2 | the 14R verifier imported the builder's `engine_parity` module | the import is **gone** (not narrowed): rule, indicator, fee conventions and equity path are re-implemented in the verifier; a structural check asserts no builder import | `edge15_verify.py` V31, `edge14r_verify.py` V32 |
| P0.3 | openings identified from outside by `(symbol, opened_at, entry_price)` | the broker mints `position_id`, `entry_order_id`, `exit_order_id`, `trade_id` per book; the sequence continues across `restore()` | `broker.py`, `test_broker_identity.py` |
| P0.4 | a single equity number could not say *which* quantity moved | `accounting_snapshot()` keeps realised, unrealised, cash and mark-to-market apart, returns the accrued entry commission as its own term, and checks four identities | `broker.py`, verifier V22-V23 |
| P0.5 | Jesse's 7.02 bps residual and VeighNa's 2 unmatched trades were quantified but not decomposed | both re-derived from the published rows: the residual is exactly three terms, and the two trades are the window's last two entries | `PARITY_DIVERGENCE_EXPLAINED.json/.md` |

### P0.1 — the ordering proof

| clause | value |
| --- | --- |
| frozen at | `2026-10-17T07:15:28Z` (`1792221328939466200` ns) |
| committed in | `b4ff58892263b44de122b8fe6b08239ffb831032`, commit time `1792221564` |
| captured at | `2026-10-17T07:20:21Z` (`1792221621701637600` ns), +292.8 s after the freeze |
| working file vs committed blob | sha256 equal after LF normalisation (`cea0be8934…`) — the disk copy is CRLF, which is why both forms are compared |
| prospective bars captured | **0** (the first hourly bar to open after the freeze has not closed yet) |
| descriptive bars captured | 0 new; the 14R slice is preserved and re-labelled descriptive |
| verdict | `ORDER_VERIFIED` |

The one assumption is stated in the artifact: the instants come from the same host clock read in
two processes, and what makes the order checkable from outside is the commit between them.

### P0.5 — the two divergences, decomposed

**Jesse.** The 7.021359 bps residual is not an engine disagreement. Each published row obeys

```
residual_compounded = gross_price_effect + (engine_realised_charge − 20 bps) + our_convention_gap
```

and at the material index 19 that reads `6.985523 + (−0.059751) + 0.095587 = 7.021359`, error 0.0.
The price term exists only on the two trades still open at the window's end, where this project
closes at the final bar's **open** and Jesse at its **close**; among the other 42 trades the worst
difference is **0.001251 bps**, inside the 1 bps tolerance frozen before the run.

**VeighNa.** 44 opens and 42 closes; the reader pairs fills in order, so an unclosed entry has a
testable consequence: the two unmatched trades must be the rule's last two entries. Rebuilding the
rule from the frozen bars shows exactly two forced closes, at exactly those two entry instants.

## P1 — the alpha search

Families are mechanically distinct, and the ones the campaign already rejected are named with their
measured edges in `ALPHA_RESULTS.json → rejected_family_audit`. No family is a rename: a rename
would share an entry condition, an exit condition or a conditioning variable, and these share none.

Held-out tail (last 30% of each series, parameters frozen beforehand, never fitted on it):

| family | trades | gross bps/trade | net 1x | net 2x | verdict |
| --- | ---: | ---: | ---: | ---: | --- |
| `mean_reversion_vol_liq` | 811 | +54.84 | +21 075 | −2 326 | `EXPERIMENT_COST_FRAGILE` |
| `vol_regime_breakout` | 171 | +223.79 | +33 367 | +28 465 | `REJECT_OUTLIER_DRIVEN` |
| `trend_pullback` | 895 | −37.04 | −58 809 | −84 464 | `REJECT` |
| `cross_sectional_rotation` | 355 | −35.63 | −11 465 | −16 605 | `REJECT` |
| `maker_only_spread_capture` | — | — | — | — | `DEFER_NO_FILL_MODEL` |

Two readings matter more than the signs.

* **The breakout family's mean is a lottery, not an edge.** Its top five trades are **1.31×** its
  entire gross: remove them and the family is net negative, and its median trade loses money. A
  mean that rests on five of 171 trades cannot be sized. It is rejected for that reason, on the
  number, not by taste.
* **The mean-reversion family is real but one cost-doubling away from zero.** Its gross per trade is
  identical in both segments (+54.84 / +54.76) — the structure repeats where it was not chosen — and
  its expectancy turns negative (−2.87 bps/trade) at 2× cost, i.e. before the tier's own 28.96 bps
  round trip is doubled. It is not an edge you can risk capital on yet.

The dilemma the search kept hitting is arithmetic: the alt tiers cost 25–29 bps a round trip at the
200 USDT stake, so a family has to earn ~30 bps gross per trade to survive the *central* model and
~58 bps to survive the adverse one.

## P2 — the cost model

Per venue and product, with the provenance of each component declared instead of implied:
`KNOWN` fee (10 bps a side, VIP0 spot) + `ESTIMATED` half spread + `HYPOTHESIS` slippage
(√size scaling) and impact (linear), by liquidity tier.

| pair | tier | per side | round trip |
| --- | --- | ---: | ---: |
| BTC/ETH | TIER1 | 11.6768 | **23.3536** |
| SOL | MAJOR | 12.65 | **25.30** |
| UNI | ALT | 14.48 | **28.96** |

Zero spread and zero slippage appear nowhere in the pricing: those were the 14R *parity* inputs for
comparing two engines, and the cost model says so in its own `not_used` field.

## P3 — the experimental prospective lane

| quantity | value |
| --- | --- |
| cycles | 210 (`NO_TRADE` 182, `FILL_OPENED` 14, `PROTECTIVE_EXIT` 14) |
| closed trades / realised PnL | 14 / **−12.8100 USDT** |
| accounting identities | all hold, in all three books |
| books | one per symbol (`EDGE15LANE-BTCUSDT`, …), so identifiers cannot collide |
| authoritative ledger | sha256 unchanged before and after; nothing admitted |
| rejected families | refused as `NO_TRADE` with the rejecting reason attached |
| exchange orders | 0 |

The lane's own result is a risk-policy finding rather than a strategy one: the runtime's default
protective stops (0.5 % / 0.75 %) are far tighter than the horizon the surviving family needs, so
every position was stopped out before its thesis could play out. Changing those limits is a
risk-manager decision with its own RFC, and this work package did not touch them.

The disk guard still reports `INSUFFICIENT_FREE_SPACE` (5.9 GiB free) and was not relaxed.

## P4 — verification

| artifact | result |
| --- | --- |
| `edge15_verify.py` (imports no builder module) | **32/32 checks, verdict VERIFIED** |
| `edge14r_verify.py` (re-run with the tightened holdout check) | **32/32 checks, VERIFIED** |
| broker behaviour tests | 7 new tests, all pass |
| family causality tests | 10 tests: truncated series reproduce the completed history exactly |

## Publication

`docs/agentic/EXECUTION_CHECKPOINT.md` carries the state, the pending items and the exact
reproduction commands; the package is committed and pushed on
`agent/edge-recovery/WP-EDGE-00-baseline`.
