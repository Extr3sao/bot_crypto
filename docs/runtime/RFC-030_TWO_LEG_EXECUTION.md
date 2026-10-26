# RFC-030 — Two-Leg / Market-Neutral Execution & Accounting Contract

Status: **IMPLEMENTED (infrastructure) — EXP-ARP-023 BLOCKED_SHORT_DATA**
Scope: research / PAPER only. No LIVE, no capital, no credentials, no OOS.

## Why

A market-neutral result is not valid merely because `long_pnl + short_pnl > 0`. The
programme lacked any two-leg execution or accounting contract: `src/trading_bot/`
had single-leg execution (`execution/`), a single-position `PaperBroker`, and an
*empty* `portfolio/` package. `WP-PAIR-INFRA-001` recorded the gap.

RFC-030 builds the minimum contracts so a pair economic result can only exist when
its legs, costs and accounting all reconcile — and so that a short leg whose
borrow/funding economics are unobservable **blocks** rather than silently costing
zero.

## Package

`src/trading_bot/research/pair/` (9 modules):

| module | contract |
| --- | --- |
| `instruments.py` | `LegInstrumentContract`, `InstrumentType`, `Side`, `require_same_instrument` |
| `proposal.py` | `PairTradeProposal`, `PairExecutionPlan`, `PairExecutionStatus`, `LegImbalance`, `FailurePolicy` |
| `costs.py` | `ShortLegCost`, `PairCostModelV1`, `PAIR_COST_MODEL_V1`, `CostKnowledge` |
| `simulator.py` | `PairSimulator`, `FillConfig`, `LegFill`, `PairExecutionResult` |
| `ledger.py` | `PairLedger`, `PairLedgerEntry`, `PortfolioState` |
| `beta.py` | `through_origin_beta`, `beta_book`, `beta_gate`, `beta_diagnostic` |
| `metrics.py` | `equity_metrics`, `max_drawdown`, `EquityMetrics` |
| `verifier.py` | `verify_ledger`, `RawLedgerEntry`, `PairLedgerVerification` |

## Invariants (enforced, not assumed)

1. **Leg independence.** A pair is `BOTH_FILLED` only when both legs satisfy the
   execution contract; a one-leg/partial fill is `PAIR_FAILED`/`*_PENDING` and
   **never** enters the ledger (§26/§29).
2. **No zero-borrow default.** A borrow-required short with no borrow evidence is
   `UNKNOWN`, `economically_executable = False`, `blocked_reason =
   SHORT_LEG_UNCOSTED` — never `0` (§13).
3. **PIT costs.** A cost whose `availability_timestamp > decision_time` is refused
   (§14/§41).
4. **Pair-PnL identity.** `pair_net = long_gross + short_gross - long_cost -
   short_cost - borrow - funding + basis`, stored and re-checked on construction
   (§30/§31).
5. **Equity identity.** `equity = initial_capital + realized(gross) +
   unrealized - costs` (§19/§30).
6. **Fail-closed beta gate.** `|β_book| > 0.10` ⇒ FLAT; an undefined beta ⇒ FLAT
   (`BETA_UNDEFINED_FAIL_CLOSED`); the tolerance is never optimised (§23).
7. **Builder ≠ verifier.** `verifier.py` recomputes every component from raw leg
   fields and ignores the ledger's aggregates (§40).

## Reachability

Nothing in the shipped runtime imports this package; it can neither size, risk-check
nor execute a live strategy. `tests/unit/test_dependency_closure_guard.py` confirms
every committed `src/trading_bot/**/*.py` imports cleanly.
