# PAIR_RUNTIME_AUTHORITY_MAP

Which component is the authority for each RFC-030 concept, and what the shipped
runtime can and cannot do.

| concept | authority | notes |
| --- | --- | --- |
| cost of the long leg | `COST_MODEL_V3` / `BINANCE_SPOT_STANDARD_TAKER` (23.559016994374947 bps RT) | unchanged from admission config |
| cost of the short leg | `ShortLegCost` + `PairCostModelV1` | `EXTERNAL_DATA_REQUIRED`; zero forbidden |
| instrument identity | `LegInstrumentContract` + `require_same_instrument` | no substitution |
| execution outcome | `PairSimulator` | pure, deterministic, fail-closed |
| accounting | `PairLedger` / `PortfolioState` | identities enforced on construction |
| equity metrics | `metrics.equity_metrics` | true equity, not a notional proxy |
| independent verification | `verifier.verify_ledger` | recomputes from raw fields |
| beta neutrality gate | `beta.beta_gate` (tolerance 0.10) | fail-closed on undefined beta |
| beta feasibility evidence | `beta.beta_diagnostic` | evidence only; never a parameter search |

## Reachability

`src/trading_bot/research/pair/` is a **research/PAPER** package. Nothing in the
shipped runtime imports it, so it can neither size, risk-check nor execute a live
strategy. `tests/unit/test_dependency_closure_guard.py` confirms that every committed
`src/trading_bot/**/*.py` imports cleanly and that no tracked module reaches into the
untracked `research/experimental/` tree.

## What this does NOT authorise

- No LIVE execution, no capital, no credentials.
- No threshold loosening, no risk sizing, no auto-promotion.
- No EXP-ARP-023 DEV run and no OOS access from this contract.
- No economic result may be produced while the short-leg borrow/funding series is
  unobservable; the correct output in that case is `BLOCKED_SHORT_DATA`.
