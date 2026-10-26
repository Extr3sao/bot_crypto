# Alpha Recovery Programme — v1.3 (ARP-004)

**Campaign:** `ARP-004 — COST-COMPATIBLE EDGE CAMPAIGN`
**Scope executed:** `EXP-ARP-007` and `EXP-ARP-010` only.
**Started from:** `d4cd26da3e77ad508e3f50b0cb5a74bdc3815c5f` (ARP-003 END_SHA).

## What was run

Two pre-registered 1-day-horizon experiments were implemented (tracked code), PIT
audited, and run through `DEV → COST → VALIDATION → ROBUSTNESS → OOS gate`:

| experiment | strategy_id | arm | mechanism | timeframe |
| --- | --- | --- | --- | --- |
| `EXP-ARP-007` | `STRAT-CAND-019-VARIANT-B` | `PROJECT_DERIVED_VARIANT` | level reaction (daily pivot fade) | 1d |
| `EXP-ARP-010` | `H-VOLSPIKE-MR-001` | `PROJECT_DERIVED_VARIANT` | volatility-spike mean reversion | 1d |

Neither is a source-faithful test. `EXP-ARP-007` must never be attributed to the
`STRAT-CAND-019` source hypothesis (its reconstruction is `BLOCKED_NEEDS_SPEC`);
`EXP-ARP-010` is a new project hypothesis with no `STRAT-CAND` lineage.

## Headline result

**No edge survived the first gate. `FALSE_SUCCESS = 0`.**

* `EXP-ARP-007`: DEV **PASS** (153 trades, gross **+0.776 bps**) → COST **REJECT_COSTS**
  (net **−22.783 bps** at the canonical `COST_MODEL_V3`; break-even cost 0.776 bps).
  VALIDATION and OOS were **never opened**.
* `EXP-ARP-010`: DEV **INSUFFICIENT_EVIDENCE** (only 6 trades; the frozen 2σ spike
  threshold was **not** lowered). Gross **−75.059 bps**. Nothing downstream ran.

`OOS_OPENED = NO` for both. `PROMOTION_CANDIDATES = none`.

## Why slower horizons did not save the strategies

ARP-003 showed 1d opportunity/cost ≈ 8.2, i.e. the *available* daily move is ~8× the
round-trip cost. That is an **upper bound on what a perfect capture could earn**, not
evidence a mechanism captures it. `EXP-ARP-007` captured **0.39 %** of the available
daily move (capture ratio `0.0039`). The frontier ratio being favourable is necessary,
never sufficient.

## Evidence map

* `EXPERIMENT_SUMMARY.md` — stage-by-stage verdicts.
* `DATA_COVERAGE.md` — coverage and sample sufficiency.
* `COST_ANALYSIS.md` — `COST_MODEL_V3` stress for the DEV survivor.
* `VALIDATION_ANALYSIS.md` / `ROBUSTNESS_ANALYSIS.md` — recorded as `NOT_REACHED`.
* `DATA_GAPS.md` — `EXP-ARP-006` / `EXP-ARP-008` depth gaps (§24).
* `EXP-ARP-009_INFRA_AUDIT.md` — `CrossSectionalEngine` audit (`INFRASTRUCTURE_BLOCKED`) (§25).
* `INDEPENDENT_VERIFICATION.md` — why §26 independent verification was not triggered.
* `NEGATIVE_KNOWLEDGE.md` — every rejection persisted.
* `ENVIRONMENT.json` — code/config/data/cost hashes.

## Test gates

`pytest` 1503 passed · `ruff check .` clean · `mypy` clean (413 source files).
