# 12 — EXECUTION REALISM GATE — EXECUTION-REALISM-AND-COST-AUTHORITY-01

§30 · §34 — Architecture/report only; do **not** modify runtime pipeline (34)

## Pipeline position (proposed insertion point §34)

```
DISCOVERY (frozen prereg, gross ≥ 0)
  → ROBUSTNESS (halves/thirds/walk-forward)
  → OOS (holdout)
  → EXECUTION_REALISM_GATE  ← proposed new gate (this checkpoint's subject)
  → PAPER (multicycle live paper with real costs)
  → SHADOW (counterfactuals)
  → CANARY → LIMITED → PRODUCTION
```

Current pipeline after `0941082` is `DISCOVERY→...→PAPER` via `paper_cycle/Shadow`. This gate is **report-only**: no code wires it before the next RFC.

## Gate contract (`§30 ECONOMIC MATERIALITY GATE`)

```python
NET_EDGE = GROSS_EDGE - REALISTIC_EXECUTION_COST   # per-trade bps of notional
EDGE_TO_COST_RATIO = GROSS_EDGE / REALISTIC_EXECUTION_COST  (where cost > 0)

# where:
#   GROSS_EDGE = mean(trade.gross_return / entry_price * 10000) [bps]
#   REALISTIC_COST = ExecutionRealismEstimate.total_cost_bps for the trade's
#                    asset/direction/notional/holding (IDEALIZED/BASE/STRESSED)
```

**Invariant:** `NET_EDGE <= 0  ⇒  DO NOT PROMOTE` (no promotion under any circumstance).
`NET_EDGE > 0` is **necessary but not sufficient** — all other gates (robustness/OOS, funding materiality, `SHARPE/PF/N≥30/100`, halves/thirds, coverage) remain.

**Cost uncertainty:** represent cost as `LOW / MEDIAN / HIGH` (IDEALIZED/BASE/STRESSED). Promotion must be `BASE` positive **and** either `STRESSED` positive (ROBUST) or declared `COST_SENSITIVE` with an explicit monitoring plan. A point estimate alone is insufficient (31).

## H6 10 bps framing (§12 — DO NOT CHANGE H6)

- H6 discovery gate uses **10 bps TOTAL RT** (spec `cost_model`, diagnostic sens `0/10/20/40 bps`, gross reporting required). This gate **does NOT rewrite** `H6_SPEC_V2` (10 bps is frozen).
- Comparison vs realism (09): VIP0 taker fee `10 RT` is exact; H6 10 bps is **APPROXIMATELY_REALISTIC to OPTIMISTIC** once spread (`0.013-0.98 bps`) and real slippage replace synthetic `2 bps`. For `STRESSED` (P90/P99) the realistic RT may exceed `10` → a `10bps NET>0` that becomes `NET≤0 @ STRESSED` is `COST_SENSITIVE` and must not promote without a fee-reduction (maker) or spread-proof execution path.
- `FUNDING_EXCLUDED_WITH_LIMITATION` stays; 1h bars have `funding_events_in_holding(entry_ms, exit_ms)` `0` or `1` (`~12.5%` hit). A promotion's `FUNDING_MATERIALITY_GATE` (`08_H6 note`) evaluates this.

## This gate's dependents

- `ExecutionCostAuthority` (§24) provides `base/stressed` per asset.
- `ExecutionRealismEstimate.missing_components` must be `()` and `total_cost_bps` non-None to **pass** the gate; otherwise `INSUFFICIENT_EXECUTION_EVIDENCE` (fail-closed).
- `FalseProfitabilityDetector` (§32) is the offline classifier for already-authorized histories: `ROBUST_POSITIVE / COST_SENSITIVE / NEGATIVE_AFTER_COSTS / INSUFFICIENT_EXECUTION_EVIDENCE / GROSS_NEGATIVE`.

## Thresholds

No arbitrary pass thresholds beyond `NET>0` and `STRESSED>0` for robustness. Edge-to-cost ratio is **descriptive** (e.g. `1.5×` vs `0.8×`) for reporting — not a gate until project governance sets one.

## Prior hypotheses handling (§33)

If `GROSS_EDGE` already `≤0`, funding/spread realism cannot rescue it — status `GROSS_NEGATIVE` and `UNCHANGED / WORSE` after realistic costs (never viable).
