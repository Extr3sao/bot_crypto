# ARC-01 PREREGISTRATION — RUN REPORT

**Checkpoint:** `ARC01-PREREG-001` · **Branch:** `research/arc01-data-authority-01`
**Hypothesis:** `ARC-01-FUNDING-CROWDING-UNWIND-01` · **Frozen:** 2026-09-15
**Final state:** `PENDING_INDEPENDENT_PREREG_VERIFICATION`
**Builder:** DeepSeek — `BUILDER_CROSSCHECK` only; **not** self-certified as independently verified.

---

## 1. What this checkpoint did

Completed and froze a **complete, deterministic, falsifiable** ARC-01 economic hypothesis
(`EXTREME FUNDING + CROWDED POSITIONING + CAUSAL CONTEXT → CONTRARIAN UNWIND`) **before any performance
observation**. No backtest, no execution, no signal set on real data.

Data foundation was **not** redone: this checkpoint binds to the certified authority
(`6e42dd9d4c19800925fd555999686d1e2b4ef47e`, dataset `5f4845f5…`, OI `16779b7d…`, price `e1c2462a…`).

## 2. Frozen economic decision set (one line each)

| Element | Frozen value |
| --- | --- |
| Assets / market | BTCUSDT, ETHUSDT, SOLUSDT · Binance USD-M USDT-margined perpetual |
| Common window | `2021-12-01T00:00:00Z → 2026-09-10T23:00:00Z`, closed on 1h bar open times |
| Decision cadence | one decision per **certified funding settlement instant** per asset |
| Funding extreme | robust z over trailing **60d** closed window, min **90** obs, **median** / **1.4826·MAD**, MAD=0 → sample stdev → else NO_SIGNAL; **z ≥ +2.0 → SHORT**, **z ≤ −2.0 → LONG** (inclusive) |
| OI confirmation | `oi_change_24h` (same 5m slot vs 24h earlier, staleness ≤ 600 s) **strictly > 0** |
| Price context | **NONE** (price read only at the entry/exit anchors) |
| Entry | first 1h bar **OPEN** strictly after `decision_time` |
| Exit / holding | 1h bar OPEN at `entry + 72h`, **unconditional**; exactly **72h (9 settlements)** |
| Stop / cooldown | `NONE` / `NONE` |
| Overlap | **SKIP** same-asset signals while open; assets independent; ≤ 3 concurrent |
| Cost model | **10 bps** round-trip total primary; frozen scenarios 0/10/20/40 bps |
| Funding cashflow | applied for settlements in `(entry_time, exit_time]`; information window ends at `decision_time` (disjoint, no double counting) |
| PIT | `funding_time ≤ T`, `availability ≤ T`, `oi_time ≤ T`, `price_time ≤ T`, completed windows only |
| Controls | `DIRECTION_CONTROL`, `TIMING_CONTROL`, `OI_CONTROL`, `NULL_CONTROL` |
| Critical gates | **11** (sample, net expectancy, ex-funding expectancy, PF, Sharpe, Sharpe CI, permutation, temporal stability, asset stability, concentration, cost sensitivity) |
| Robustness | R1–R7 frozen, **not executed**; primary parameters immutable |
| Orthogonality | H5 / H6 / ARC-02, Jaccard ≤ 0.5 and \|daily PnL ρ\| ≤ 0.5, later authorized experiment |
| Kill rule | one preregistration → one primary discovery; failure terminal; variants need a new hypothesis id |

## 3. Validation implemented at this checkpoint

- `scripts/verify_arc01_prereg.py` — read-only, portable validator with 20+ gates covering JSON validity,
  **ARC01_SPEC_COMPLETE** (every required economic field explicit; fails if any is missing), data-authority
  binding (recomputed funding partition hashes + OI/price authority records + certified fingerprint record),
  PIT contract, control plan, statistical gates, robustness plan, **NO_ECONOMIC_OBSERVATION** plus a scan that
  fails if any numeric performance value appears in any artifact, cross-artifact contradiction detection,
  manifest/package hash integrity and zero post-freeze drift.
- `src/trading_bot/research/arc01/prereg_reference.py` — pure, I/O-free reference implementation of the frozen
  decision rules (the later discovery run must use these definitions unchanged).
- `tests/unit/research/test_arc01_preregistration.py` — artifact presence, frozen parameters, binding values,
  rule semantics and the PIT adversarial battery on **synthetic fixtures only**.

### Adversarial PIT results (fixture-level, no dataset)

| Test | Result |
| --- | --- |
| Non-vacuous baseline (same inputs → same state) | PASS |
| Future mutation strictly after T invisible at T | PASS |
| Past **eligible** mutation detected at T | PASS |
| Inclusive threshold boundary (±2.0 fire; ±(2.0−ε) do not) | PASS |
| MAD = 0 → sample-stdev fallback; fully degenerate → `SCALE_NONPOSITIVE` | PASS |
| Insufficient funding history (< 90) fails closed | PASS |
| OI neutral / contraction / stale / invalid reference fail closed | PASS |
| `NO_SIGNAL` precedence is deterministic, first-match | PASS |
| Entry strictly after decision time (PIT violation rejected) | PASS |
| Forward-data guard suppresses signals in the final 72h | PASS |
| Funding cashflow sign convention + window disjointness | PASS |
| Null-control direction deterministic | PASS |

## 4. Gates

| Gate | Result |
| --- | --- |
| `ARC01_SPEC_COMPLETE` | **PASS** |
| `DATA_AUTHORITY_BOUND` | **PASS** |
| `ECONOMIC_PARAMETERS_FROZEN` | **true** |
| `PIT_CONTRACT` | **PASS** |
| `CONTROL_PLAN_FROZEN` | **true** |
| `STATISTICAL_GATES_FROZEN` | **true** |
| `ROBUSTNESS_PLAN_FROZEN` | **true** |
| `KILL_RULE_FROZEN` | **true** |
| `JSON_VALIDATION` | **PASS** |
| `NO_ECONOMIC_OBSERVATION` | **PASS** |
| `CONTRADICTIONS_FOUND` | **0** |
| `FALSE_SUCCESS` | **0** |

| Ledger | Value |
| --- | --- |
| `ARC01_BACKTESTS` | **0** |
| `ARC01_EXECUTIONS` | **0** |
| `ARC01_PERFORMANCE_OBSERVED` | **false** |
| `POST_FREEZE_ARTIFACT_DRIFT` | **0** |
| `WORKING_TREE_CLEAN` | **true** |

## 5. Commit and immutability semantics

One scoped commit: **`[ARC01-PREREG-001] freeze funding crowding unwind discovery`**.

`PREREG_COMMIT` is **not** embedded in any artifact (that would require a commit loop to embed its own SHA).
Artifacts use `authority_commit` (dataset authority), `generated_from_commit` (pre-freeze HEAD `367f58f1…`),
`report_commit = null`. `PREREG_COMMIT` is resolved externally as `git rev-parse HEAD` of the commit whose
message starts with `[ARC01-PREREG-001]`. After that commit the nine frozen content artifacts are immutable
and `POST_FREEZE_ARTIFACT_DRIFT = 0`.

## 6. Open limitations

1. Common window starts `2021-12-01` (OI/price bound); the 2020–2021 funding history is outside the window.
2. The final ~72h of the window emits no trades (frozen forward-data guard).
3. Funding cashflow is charged on the entry notional — frozen `O(1e-4)` simplification; the mark-price
   authority is not admitted.
4. OI authority has documented invalid days; gaps fail closed to `NO_SIGNAL`, so `INSUFFICIENT_SAMPLE` is a
   possible terminal outcome and can only be assessed at discovery.
5. `PRICE_CONTEXT = NONE` narrows the ARU candidate sketch (price-rejection leg removed), documented and
   justified pre-observation.
6. The carry leg is systematically favourable to a contrarian funding entry, which is why
   `G3_NET_EXPECTANCY_EX_FUNDING > 0` is a critical gate; the four controls detect mis-specification, not
   every alternative mechanism.
7. No drawdown gate was pre-specified for ARC-01 (diagnostic only, disclosed) — it cannot be converted into a
   gate after the fact.
8. **Binding granularity:** the funding partitions are present in this worktree and their SHA256 **is**
   recomputed here; the reused OI/price partitions live in the shared main data root, so they are bound to the
   certified manifest records (`OI_FULL_HISTORY_DATASET_MANIFEST_V2.json`, `PRICE_1H_AUTHORITY_V2_MANIFEST.json`)
   rather than re-hashed in place. The independent verifier must re-hash them from the shared data root.
9. **Pre-existing environmental failure (not caused by this checkpoint):**
   `tests/unit/research/test_oi_full_history_v2_pit.py::test_2024_06_05_contamination_never_reaches_canonical`
   fails in this worktree because `data/processed/oi_full_history_v2` is absent locally (it exists in the main
   data root). It is unrelated to this checkpoint: every artifact here is additive and no existing module was
   modified.

## 7. Next step

**`ARC01_INDEPENDENT_PREREG_VERIFICATION`** — an agent that did **not** author this preregistration must
reproduce the bindings, re-implement the transforms independently, re-run the adversarial PIT battery,
confirm no economic quantity was observed, and only then may any economic execution of ARC-01 be authorized.
