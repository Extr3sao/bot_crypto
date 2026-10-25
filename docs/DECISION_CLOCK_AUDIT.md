# DECISION_CLOCK_AUDIT — STRATEGY-BEHAVIOR-AUDIT-V1

## Trigger chain (verified in code + live run)

| Component | Trigger | Frequency (observed) | Same-candle reevaluation | Intended? | Evidence |
| --- | --- | ---: | --- | --- | --- |
| PaperOrchestrator loop | wall-clock polling (`interval_seconds`) | ~5.5 s/cycle (median; interval=0 → back-to-back) | n/a (orchestration layer) | YES (polling orchestrator by design) | `paper_orchestrator.run()`; RUN-01: 342 cycles / 31.3 min |
| UniverseScanner | every orchestrator session | 1 scan/cycle | scans fresh snapshot each cycle | YES | `paper.session.started` ×342 |
| FetcherBarReader / candle gate | every decision-cycle build | per asset per cycle | **YES — re-reads the same closed candles while the 5m bar stays current** | PARTIALLY — see verdict | closed-candle filter re-applied per cycle |
| AssetContext builder | per asset per cycle | 1/cycle/asset | **YES — rebuilds context from the same window** | SAME | `contexts_built=3` per cycle |
| StrategyRouter | per asset per cycle | 1/cycle/asset | **YES — same inputs ⇒ same decision** | SAME | `strategy_invocations=3` per cycle |
| AlphaFamily.generate | per routed asset per cycle | 1/cycle/asset | **YES — deterministic ⇒ same alphas from same bars** | SAME | `signals_generated=3` per cycle (constant min=med=max=3) |
| SignalAdapter/CandidatePortfolio | per alpha per cycle | 3/cycle | YES | SAME | — |
| RiskManager.check_signal | per proposal per cycle | up to 3/cycle | **YES — repeats while position open** | SAME | 790 `Max open positions` rejections |
| IdempotencyGuard | per proposal per cycle | — | **YES — collapses same (symbol,strategy,direction,bar)** | YES (last-defence, correct) | 191 duplicates, **7 unique intent ids** |
| PaperBroker | only on new bar-intent | — | NO (same-side skip) | YES | 7 orders / 7 unique intents |

## Verdict

```
POLLING FREQUENCY  = ~5.5 s (orchestration cadence, observed)
STRATEGY DECISION FREQUENCY (economic) = 1 per (asset, strategy, direction, bar_ts)
```

The separation EXISTS at the execution boundary: economic decisions are keyed
by the closed bar (`intent_cloid`), so polling faster than the bar does NOT
produce duplicate orders (7 orders == 7 unique intents in RUN-01; 191
duplicate submissions suppressed).

**Same-candle reevaluation IS real upstream** (context → router → family
re-run every ~5.5 s on the same closed candle) but it is currently
**EXPECTED-BY-DESIGN** with two honest caveats:

1. It is wasted computation (3 deterministic re-evaluations per candle per
   asset) — an efficiency concern, not a correctness one.
2. It creates repeated identical risk calls (the `Max open positions` ×790
   rejections are mostly the SAME already-open positions re-proposed, not new
   ideas) — Risk spam, not Risk pathology.

**Pathology check (prompt §4)**: NOT a defect for correctness — no duplicate
orders/fills/accounting ever escaped (idempotency + broker same-side skip
held across 342 cycles). Classified as `EFFICIENCY_DEBT (P3-observation)`: a
future `BAR_CLOSE evaluation_mode` could evaluate once per new closed candle.
NOT implemented in this phase (§7: no blind gating; families have no explicit
evaluation contract yet).

## Candle identity (RUN-01, 342 cycles, 31.3 min)

- Unique closed candles consumed per asset ≈ 31.3 min / 5 min ≈ 6.3.
- Evaluations per candle per asset: ~342 cycles / 6.3 candles ≈ **54×**.
- Signals per candle: 3 alphas per evaluation, but economically unique
  signals per candle = 1 per (asset, direction) — enforced downstream.
- Orders per candle: bounded by position limits; 7 unique intents total.
