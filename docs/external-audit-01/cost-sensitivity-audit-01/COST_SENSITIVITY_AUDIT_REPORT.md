# COST SENSITIVITY AUDIT REPORT — H1-EVIDENCE-INTEGRITY-AND-H3-RELATIVE-VALUE-PREREG-01

Date: 2026-09-10 · Evidence artifact: `COST_SENSITIVITY_AUDIT.json` (same directory)
Defect classification: **FORMULA_DEFECT — display-only** · Defect ID: **DEF-RESEARCH-COST-001** (registered, FIXED)

## A1 — Formula trace (exact sources and units)

| Metric | Source module | Function | Formula | Units |
| --- | --- | --- | --- | --- |
| gross expectancy | `src/trading_bot/research/h1_regime_transition.py` | `compute_trade_metrics` | `mean(t.gross_r)`, where `gross_r = (exit−entry)/ATR14` (LONG) or `(entry−exit)/ATR14` (SHORT) | R multiple, per trade |
| net expectancy (baseline) | same | same | `mean(t.net_r)`, where `net_r = gross_r − (10/10000)/(ATR14/entry)` (frozen in `_simulate`) | R multiple, per trade |
| cost sensitivity (0/5/10/20 bps) | same | same (sensitivity branch) | **DEFECTIVE (before repair):** `gross_r − ((cost_bps − 10)/10000)/risk_frac` — a *delta vs the 10 bps baseline* subtracted from the **gross** series. **Repaired:** `gross_r − (cost_bps/10000)/risk_frac` — absolute scenario cost. | R multiple, per trade |
| basis-point conversion | same | `_simulate`, sensitivity branch | `bps / 10_000.0` → price fraction of entry | bps → fraction |
| R conversion | same | `_simulate` | `cost_r = price_fraction / risk_frac`, `risk_frac = ATR14/entry` | fraction → R |
| fees + slippage | same | `_simulate` | modeled jointly as one round-trip cost in bps (frozen spec `cost_model.round_trip_bps = 10.0`; `cost_basis`: 5 bps/side, identical to CARRY-FUNDING-DEEP-01) | bps per round trip |

There are no implicit conversions: every quantity above is an R multiple per trade; `cost_drag_R = gross_expectancy − net_expectancy` (R/trade).

## A2 — Trade-set identity (COST-03)

The trade set **cannot** change with the cost scenario: costs are applied *after* the frozen entry/exit simulation and no entry/exit rule consumes any cost scenario. Proven empirically: all four scenarios recomputed over the identical frozen trade list.

- `N = 10,193` identical across 0/5/10/20 bps (asset split 3,519/3,546/3,128, matching the economic run exactly)
- `TRADE_SET_SHA256` (sha256 over canonical identity fields — asset, direction, entry_ts, exit_ts, entry_price, stop_price, exit_price, risk_frac, gross_r, transition_label, kind — in trade order): recorded in `COST_SENSITIVITY_AUDIT.json` and identical for every scenario by construction
- trade-set drift: **false** (and cost-conditioned trade-set changes were never preregistered)
- dataset integrity: row counts and manifest sha256 match `H1_EXECUTION_MARKER.json`; no synthetic rows

## A3 — Monotonicity (COST-04): recomputed from the immutable trade set

| COST_BPS | GROSS_TOTAL_R | COST_TOTAL_R | NET_TOTAL_R | GROSS_EXPECTANCY_R | COST_PER_TRADE_R | NET_EXPECTANCY_R | N |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | −30.929733 | 0.000000 | −30.929733 | −0.003034 | 0.000000 | **−0.003034** | 10,193 |
| 5 | −30.929733 | 634.350995 | −665.280728 | −0.003034 | 0.062234 | **−0.065268** | 10,193 |
| 10 | −30.929733 | 1,268.701989 | −1,299.631723 | −0.003034 | 0.124468 | **−0.127502** | 10,193 |
| 20 | −30.929733 | 2,537.403978 | −2,568.333712 | −0.003034 | 0.248936 | **−0.251970** | 10,193 |

Invariants verified: `NET_R = GROSS_R − COST_R` (≤1e-12) and monotone non-increasing net in cost (≤1e-12). `COST_R ≥ 0` at every level. No candidate logic changed.

**Zero BPS expectancy = −0.003034 R** (equals the reported gross expectancy — the gross series was never in doubt).

## A4 — Classification (COST-06): FORMULA_DEFECT — exact origin proven

Legacy values reproduced to machine precision by the defective formula, from raw immutable trades:

| Scenario | Reported | Recomputed (defective formula) | Match |
| --- | --- | --- | --- |
| 5 bps | +0.05919957433988362 | +0.05919957433988384 | exact (≤1e-12) |
| 20 bps | −0.1275023763892236 | −0.12750237638922243 | exact (≤1e-12) |

Root cause: the sensitivity branch subtracted `((cost_bps − 10)/10000)/risk_frac` — a *delta vs the 10 bps baseline* — from the **gross** series. At 5 bps the delta is **negative** and *adds back* the 10 bps cost, producing +0.0592, an arithmetically impossible value **above gross** (−0.0030). At 20 bps the delta coincides exactly with the 10 bps cost, so the "20 bps" value is a duplicate of the 10 bps baseline (−0.1275). Correct values: 5 bps → **−0.0653**, 20 bps → **−0.2520**.

Not REPORT_LABEL_ERROR (formula itself was wrong), not SIGN_ERROR, not BPS_UNIT_ERROR, not R_NORMALIZATION_ERROR, not TRADE_SET_DRIFT.

## A5 — Impact analysis (COST-05)

`compute_trade_metrics` is referenced only by the H1 runner (`scripts/h1_regime_transition_discovery.py`) and its unit tests. The defective branch executed only when `cost_bps ≠ 10`, i.e. only for the `slippage_sensitivity_net_R` report field. The B4 classification consumed the precomputed 10 bps net series (`t.net_r`), which is arithmetically independent of that branch.

| Research result | Uses the defective component? | Gate depended on sensitivity? | Classification |
| --- | --- | --- | --- |
| Legacy retro validation (momentum/trend/breakout/MR/volatility cells) | No — independent cost engine (0.0004 commission + 2 bps slippage/side) | No | UNAFFECTED |
| volatility_structure (Batch 01, memory #6) | No — separate pipeline | No | UNAFFECTED |
| cross_sectional (Batch 01, memory #7) | No — separate pipeline | No | UNAFFECTED |
| carry_funding (Batch 02 + CARRY-FUNDING-DEEP-01, memory #8) | No — independent preregistered cost model (5 bps/side) | No | UNAFFECTED |
| H1-REGIME-TRANSITION-DISCOVERY-01 | Yes (runner) | **No** — B4 gates used the 10 bps net series; sensitivity is report-only | METRIC_AFFECTED (display field only); RESULT NOT INVALID |
| Strategy Lab (lab_intake / strategy_lab) | No — no sensitivity/cost_sensitivity reference | No | UNAFFECTED (DISPLAY_ONLY elsewhere) |
| R2 campaign / Shadow / Risk | No — no cost-sensitivity component | No | UNAFFECTED |

GATE_AFFECTED_RESULTS: **none**. No historical PASS/FAIL status depended on a miscomputed sensitivity value; nothing to re-run. H1's DISCOVERY_FAIL is restated below on cost-independent grounds.

## Track B — H1 final disposition (independent of the defective metric)

H1 remains **DISCOVERY_FAIL** on evidence that never touches the defective branch:

- gross expectancy **−0.003034 R ≈ 0** and gross PF **0.995 < 1** (no edge exists before any cost is applied; verified by recomputation from raw data, `TRADE_SET_SHA256` in the audit JSON)
- Sharpe CI [−0.0876, −0.0445] entirely < 0; P(Sharpe>0) = 0.0; permutation p = 1.0 (all computed on the *net* 10 bps series, independent of the sensitivity branch)
- halves [−1, −1]; thirds [−1, −1, −1]; walk-forward last third −0.0884 R
- corrected sensitivity *strengthens* the failure: monotone −0.003 → −0.252 R across 0→20 bps

**H1_FINAL_STATUS: DISCOVERY_FAIL.** The reclassification to REQUIRES_REASSESSMENT is rejected.

## Track B1 — Failed-research memory (H1-02, H1-03)

Updated in `docs/external-audit-01/FAILED_RESEARCH_MEMORY.md` (entry #10 amendment): dominant loss mechanism SHORT_ON_SHOCK (N=10,058) inside the structural uptrend; tiny post-hoc cells NORMAL→HIGH (N=11) and BULL|RANGE→NEUTRAL|TRANSITION (N=20) recorded as `POST_HOC_LEAD_ONLY / INSUFFICIENT_SAMPLE / DO_NOT_RETEST_WITHOUT_NEW_EX_ANTE_HYPOTHESIS` — never promoted.

## Repair record

- `compute_trade_metrics` sensitivity branch repaired to absolute-cost semantics (docstring documents DEF-RESEARCH-COST-001); default 10 bps path numerically unchanged (`t.net_r` == absolute formula at 10 bps), so all committed 10 bps metrics remain valid without touching frozen artifacts.
- Regression test `test_cost_sensitivity_absolute_cost_monotone_non_increasing` added (NET=GROSS−COST, monotone non-increasing, exact 5/20 bps arithmetic, default-path equivalence). H1 suite: 21/21 pass.
- The committed `H1_RESULT.json` is intentionally **not** rewritten: the anomaly is documented forensically (consistent with the marker-timestamp precedent); corrected values live in this audit.
