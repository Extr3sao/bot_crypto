# STRATEGY_BEHAVIOR_AUDIT_V1 — synthesis

Status: **STRATEGY_BEHAVIOR_BASELINE_VERIFIED** · Commits: `23985f1`, `af9bebc`, `8175e7d`, docs commit · HEAD at close: see git log

## What this phase established (evidence-indexed)

1. **Single-path routing is structurally dominant**: the deterministic paper
   map (6 families, all `CONFIRMED`, empty regimes, priority 0) makes
   `ema_crossover` (first entry) the permanent router winner — the other 5
   families are reachable-in-map but NOT selectable (`docs/STRATEGY_RUNTIME_INVENTORY.md`).
2. **Decision clock**: polling ~5.5 s; economic decisions keyed by closed bar;
   same-candle re-evaluation is real (54×/candle/asset) and by-design-expected
   with efficiency debt — no correctness impact (7 orders == 7 unique intents)
   (`docs/DECISION_CLOCK_AUDIT.md`).
3. **Funnel & churn**: 1026 evaluations → 1026 deterministic signals → 7
   unique economic intents → 7 orders/fills → 4 closed trades. Downstream
   idempotency is the collapse point and held 100%.
4. **NO_TRADE taxonomy**: POSITION_LIMIT > DUPLICATE_SIGNAL > NO_SIGNAL;
   provider/data errors never appeared as NO_TRADE (0 in RUN-01).
5. **Risk funnel (post-DEF-101)**: all 790 vetoes are `Max open positions (3)`
   — the same 3 open positions re-proposed every ~5.5 s. Risk is protecting
   capital correctly while absorbing upstream churn; counters now match fills.
6. **Attribution gap CLOSED**: strategy provenance now travels
   signal→position→closed-trade→durable rows; PnL-by-strategy/asset computed
   (ema_crossover +15.15; SOL +8.65, ETH +6.49 — OBSERVED, INSUFFICIENT_SAMPLE).
7. **MTM**: `unrealized_pnl`/`mark_to_market_equity` implemented (PIT-price,
   skip-without-price); per-cycle price history for MTM drawdown series is
   the remaining P3 instrumentation gap (documented, not hidden).

## Defects

- None P0/P1 this phase. P3 registered: (a) BAR_CLOSE evaluation-mode +
  once-per-closed-candle evaluation (efficiency, needs per-strategy contract
  first); (b) MTM drawdown series needs per-cycle price snapshot persistence;
  (c) router map-order dominance makes 5/6 families decorative in paper
  runtime (design observation for the next phase, not a runtime bug).

## Tests

608 passed / 0 failed / 0 skipped (provenance and MTM additions covered by
existing broker suites; no new-test gaps beyond P3 instrumentation items).
ruff clean · mypy 0/239.

## Next-phase decision inputs (§31)

- The system is a **1-strategy, 3-asset, capacity-capped** runtime today.
- `PAPER-BURN-IN-V2` (12h) now measures REAL strategy performance of
  ema_crossover (TP/SL churn, MTM drawdown) rather than cap artifacts.
- `STRATEGY-PERFORMANCE-BASELINE-V1` should precede any multi-family or
  multi-agent work: with the current map, agent critique would critique ONE
  strategy — measuring `AGENTIC > BASELINE` needs a baseline with more than
  one live decision source first.
