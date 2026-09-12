# 13 — EXISTING PAPER COST DIAGNOSTIC — EXECUTION-REALISM-AND-COST-AUTHORITY-01

Machine: `13_EXISTING_PAPER_COST_DIAGNOSTIC.json` · §28 — **DIAGNOSTIC_ONLY, do NOT alter stored official PnL, do NOT include DEMO trades as performance evidence** (§29)

## Scope

| Campaign | Classification | May use for `diagnostic`? | May certify profitability? |
|---|---|---|---|
| `POC01` | `DEGRADED_OBSERVATIONAL_CAMPAIGN` (coverage 0.717 best day; bottleneck `NO_SIGNAL`) | **YES** — mechanical | **NO** |
| `POC-02-R2-direction-arbitration-01` | `DIAGNOSTIC_CAMPAIGN + DEGRADED_OBSERVATIONAL (coverage 0.002-0.003, 4-5 min/day)` | **YES** — mechanical | **NO** (contradictory definition: diag + degraded; never cert) |
| `H1 / H3 / H5` | `DISCOVERY_FAIL` already (gross negative) | synthetic historical via `FalseProfitabilityDetector` only | — |

## What authoritative PAPER trades exist

- **Real PAPER trades (R2 runtime):** `R2_INTENT_LEDGER 3` paper intents (`2026-09-10 BTC buy/sell, ETH sell`) with `intent_cloid` dedup; corresponding `ClosedTrade` exists only if position closed (none in the sampled `R2_CYCLE_LEDGER 0 closed_trades` snapshot). No higher-N history — insufficient for PnL certification.
- **Shadow captures (not trades):** `shadow_captures 11`, `SHADOW_RESOLUTION 11/11 PROFITABLE_REJECT mean 0.39R`. These are **Risk REJECT** shadows, never traded (`SHADOW_PAPERBROKER_CALLS 0`) — cannot be re-accounted as PnL.
- **Cost non-interference verified (R2):** `LIVE 0, real_broker 0, private 0` kept; `R2_CYCLE_LEDGER accumulated stats: {paper_trades total 0...0, shadow_captures_total 0..11}` shows shadow is separate ledger.

## Diagnostic re-accounting (parallel fields — do NOT rewrite history)

For each authoritative `ClosedTrade` (where evidence includes `entry_price, exit_price, qty, notional, side, opened_at, closed_at`), we compute a parallel `execution_realism_adjusted_estimate` (bps) without touching `reported_net`:

| Reported (stored, official) | Diagnostic (parallel) | How |
|---|---|---|
| `ClosedTrade.pnl` (true net) = `gross(after synthetic 1bp slippage each leg) - 5bp entry - 5bp exit` | `execution_realism_adjusted_bps = (exit - entry)/entry*10000` gross minus realism `ExecutionRealismEstimate` (`fee+spread+slippage_real+impact+funding` where known; else `None→INSUFFICIENT`) | `ExecutionCostModel.compute_costs()` for fee/slip; `spread` from `05`; `funding_events_in_holding(entry_ms, exit_ms)*funding_rate*dirSign` |

Where no `ClosedTrade` is available to re-account (current R2 state), diagnostic output is `INSUFFICIENT_EXECUTION_EVIDENCE` — this is **correct**.

## Concrete diagnostic run (historical strategy evidence only, already authorized — H1 synthetic sanity)

`cost_sensitivity-audit-01` provides a **real** cost-materiality provenance for H1 `DISCOVERY_FAIL` (gross `-0.003034 R ≈ 0`, gross PF `0.995<1`, net `-0.1275R @10bps`, halves/thirds negative). Using `FalseProfitabilityDetector`:

| Hypo | gross_edge (from persisted result) | vs execution realism | Classification |
|---|---|---|---|
| H1 (regime transition) | `GROSS_NEGATIVE` (gross PF `0.995`, Sharpe CI `<0`) | `GROSS_NEGATIVE` → `NEGATIVE_AFTER_COSTS` (worse) | **GROSS_NEGATIVE / NEGATIVE_AFTER_COSTS** |
| H3 (relative value) | `GROSS_NEGATIVE` (gross `-0.3674 R`, PF `0.492`) | same | **GROSS_NEGATIVE** |
| H5 (orderflow) | `DISCOVERY_FAIL` gross negative | same (gross failure, cost cannot rescue) | **GROSS_NEGATIVE** |
| carry_funding deep (769 trades, PF `1.062` gross >1 but halves/thirds `INCONSISTENT`, `p=0.283`) | `gross PF 1.062>1` but non-robust | needs `FalseProfitabilityDetector` with real cost `10-11 bps` → even if cost-robust, robustness gates block | **COST_SENSITIVE or FAIL (robustness)** |

No failed strategy was reinterpreted as viable (§33). Cost realism makes failures **UNCHANGED or WORSE**, never rescued.

## R2 cost non-interference note

`R2` execution numbers were never profitability; the only money numbers are **paper fills at 12 bps RT** (worsened). The upcoming `paper` certification must use the `12_EXECUTION_REALISM_GATE NET>0` on future real `BASE/STRESSED` totals — not this diagnostic's `synthetic 2bp slippage` placeholder.

## Gate note for future promotions

Any future campaign that reaches `PAPER` with `BASE` profitability must clear `12` with **evidence-backed** `spread P50→P99` + measured `slippage`, not with `SYNTHETIC 1bp`. DEMO trades (`POC01/POC02 pre-realism`) remain **INVALID_FOR_PERFORMANCE_CERTIFICATION** per `§29`.
