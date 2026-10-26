# RFC-049 RUNTIME FLOW — from a frozen spec to a decision, without inventing a second runtime

- scope: RFC-049 DISCOVERY 2 (Phase A design record; no execution yet)
- authority order (unchanged): `REAL_RUNTIME > EXECUTION_EVIDENCE > TESTS > CODE > RFC > EXTERNAL_SOURCE > ASSUMPTION`
- governing engines that already exist and must be reused:
  - strategy contracts: `src/trading_bot/strategies/` (pipeline, protocols, types)
  - resolver: `src/trading_bot/research/strategy_router.py` (pure resolver, may return NO_TRADE, never forces a trade)
  - decision authority: `src/trading_bot/autonomous/decision.py` (`NO_TRADE / SHADOW_TRADE / TRADE_PAPER`, fail-closed, admission-gated)
  - spot cost model: `src/trading_bot/research/microstructure/cost_model_v3.py`
  - futures risk plane (RFC-048V, advisory): `src/trading_bot/risk/futures/`

## 1. Target flow

```text
vendor/venue data ──▶ PIT-gated ingestion ──▶ frozen feature transform ──▶ strategy state machine
                                                                            │
                                                                            ▼
                                                                    TradeProposal
                                                                            │
                                                                            ▼
                                                     StrategyRouter (regime, gates, freshness)
                                                                            │
                                                                            ▼
                                                Risk engine (sizing, limits; futures advisory)
                                                                            │
                                                                            ▼
                                    DecisionEngine ──▶ NO_TRADE / SHADOW_TRADE / TRADE_PAPER
                                                                            │
                       (live order path disabled; TRADE_PAPER needs a formal admission)
```

Phase B adds no second backtester, router or decision engine. A candidate is a
new **strategy + feature transform** that emits `TradeProposal`s into this flow,
evaluated offline first in the project's research harness under the same
contracts.

## 2. Where the PIT gate lives (three enforcement points)

1. **Ingestion**: every observation carries `availability_time`.  A value whose
   availability is not declared is not ingested (the RFC-049 specs declare a
   per-series convention; the executable audit reconstructs each decision from
   data available at that instant, per the `DEF-HTF-PIT-001` precedent).
2. **Feature transform**: computed from the PIT-annotated series only; a
   transform that needs a bar must require the bar's close time and is refused
   otherwise.  Warmup is part of the frozen spec.
3. **Decision instant**: the strategy reads a snapshot at `decision_time` and the
   router's freshness gates re-check staleness; a missing or stale critical input
   produces NO_TRADE (fail-closed), never a default value.

## 3. Risk ownership

- sizing, leverage, margin, liquidation and capital accounting belong to the
  runtime plane; a strategy never sets them (RFC-049 §12).
- Both admitted hypotheses are long/cash spot at 1x; the futures plane is not
  used by them.  If a future hypothesis needs perps, the RFC-048V preconditions
  apply (isolated linear perpetuals only, advisory review today, a binding
  review gate required before any simulated futures order).
- `EXPECTED_STOP_LOSS_WITH_COSTS <= RISK_BUDGET` must hold under the documented
  adverse scenarios before any futures candidate is admitted to evaluation.

## 4. Decision authority and admission

`DecisionEngine` rule 7 — the only path that authorises an order — requires a
formal PAPER_CANDIDATE admission plus a verifier PASS.  RFC-049 candidates start
with no admission, so the best a candidate can reach while being evaluated is
`SHADOW_TRADE` (observed, not executed).  This is why "eligible for independent
review" in RFC-049 is a state before the *separate* paper-promotion gate, and why
no result in this RFC can place an order.

## 5. Verification path (builder != verifier)

- builder: the Phase B evaluation harness, which produces trades, metrics and
  artefacts;
- verifier: a separate program that re-derives rules, datasets, PIT, trade
  reconstruction, fees, funding, gross/net PnL, portfolio state, drawdown,
  bootstrap and multiplicity from primary observations, with negative controls
  (invented trade, lost trade, omitted fees, future funding, manipulated
  timestamp, re-opened OOS, stale data, omitted risk veto, modified parameters,
  inconsistent portfolio accounting);
- `FALSE_SUCCESS` counts every check that reports success without evidence; it
  must be 0.

## 6. Sealed out-of-sample accrual (the part that must be built in Phase B)

For the decisive test the campaign needs a small **forward collector** for the
vendor series (stablecoin supply daily, FRED weekly/daily), running after the
freeze, storing raw bytes with retrieval timestamps and hashes exactly as the
Phase A probe did.  It is a data collector, not a trader: no orders, no signals,
no strategy code.  A missed day is recoverable from the vendors (unlike the
30-day-retention derivatives series) but the retrieved value and its timestamp
must be recorded, because that is the seal.

## 7. What Phase A deliberately did not build

- no signal code, no backtest run, no collector, no agent, no daemon;
- no change to any risk engine, cost model, admission ledger or router;
- no futures work: no admitted hypothesis needs it and nothing here relaxes the
  RFC-048V gates.
