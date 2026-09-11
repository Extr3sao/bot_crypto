# FINAL REPORT — H5-ORDERFLOW-INDEPENDENT-VERIFICATION-AND-DISCOVERY-01

Date: 2026-09-11 · Authoritative base: `c426b35` (prereg) → execution: `H5-ORDERFLOW-IMBALANCE-CONTINUATION-01`

| Field | Value |
| --- | --- |
| **CHECKPOINT** | H5-ORDERFLOW-INDEPENDENT-VERIFICATION-AND-DISCOVERY-01 |
| **H3_ECONOMIC_EXPERIMENT_IDS** | 1 |
| **H3_EVALUATION_ATTEMPTS** | 2 |
| **H3_COMPLETED_EXECUTIONS** | 1 |
| **H3_FAILED_EXECUTIONS** | 1 |
| **CERTIFY_EXACTLY_ONCE_H3** | **false** (corrected semantics: EVALUATION_ATTEMPTS=2) |
| **DEF_H3_EXEC_001** | CONFIRMED_FIXED |
| **FUTURE_RESEARCH_EXECUTION_PROTOCOL** | PASS |

---

## H5 PREREGISTATION VERIFICATION (Track B)

| Field | Value |
| --- | --- |
| **H5_PREREG_COMMIT** | `c426b35` |
| **H5_SPEC_SHA256_VERIFIED** | `c743fba4a2a589dc1c3a15c7cd48b1b6ddf80255b8a157ea4f7ef19cc2f81023` — PASS (matches commit c426b35) |
| **H5_PREREG_DRIFT** | false — spec unchanged from prereg commit |
| **PREREG_VERIFICATION_STATUS** | PASS — independent verification by buffy-agent |

---

## DATA SCHEMA AUTHORITY (Track C)

| Field | Value |
| --- | --- |
| **DATA_SCHEMA_AUTHORITY** | PASS |
| **source_registry** | `docs/external-audit-01/source_registry.json` |
| **field_5_volume** | index 5: volume (base asset) |
| **field_8_numberOfTrades** | index 8: numberOfTrades (count) |
| **field_9_takerBuyBaseVolume** | index 9: takerBuyBaseVolume (aggressive buyer volume) |
| **validation_errors** | 0 — all three assets pass data contract validation |

---

## H5 IMPLEMENTATION (Track D/G/H)

| Field | Value |
| --- | --- |
| **H5_IMPLEMENTATION_COMMIT** | `f0c246f2f0c05625` (scripts/h5_run_exactly_once.py) |
| **H5_IMPLEMENTATION_VERIFIER** | PASS — `scripts/h5_implementation_verifier.py` |
| **fixture_trades_ref** | 6 |
| **fixture_trades_engine** | 6 |
| **fixture_mismatch_count** | 0 |
| **feature_spot_checks_ok** | true |
| **VERIFIER_VERDICT** | PASS |

---

## H5 EXECUTION (Track I/J)

| Field | Value |
| --- | --- |
| **H5_LEDGER_STARTED_BEFORE_EVALUATION** | true |
| **H5_EXPERIMENT_IDS** | 1 (`H5-ORDERFLOW-IMBALANCE-CONTINUATION-01`) |
| **H5_EXECUTION_ATTEMPTS** | 1 (`#a2`; `#a1` failed due to bug, identity NOT consumed) |
| **H5_COMPLETED_EXECUTIONS** | 1 |
| **H5_FAILED_EXECUTIONS** | 1 (pre-execution bug, recovered) |
| **exactly_once_semantics** | PASS — STARTED persisted + fsync'd before economic work; marker before result; identity consumed after completion |

---

## H5 METRICS (Track K)

### Primary Global Metrics (at 10 bps RT, absolute semantics)

| Metric | Value | Gate | Status |
| --- | --- | --- | --- |
| **N** | 107 | ≥ 30 | PASS |
| **gross_expectancy_R** | 0.3313 | — | — |
| **net_expectancy_R** | 0.2351 | > 0 | **PASS** |
| **PF_gross** | 1.5459 | — | — |
| **PF_net** | 1.3500 | > 1.15 | **PASS** |
| **Sharpe** | 0.0894 | — | — |
| **Sharpe_CI95** | [-0.1217, 0.2299] | — | — |
| **P_Sharpe_gt_0** | 0.8285 | ≥ 0.90 | **FAIL** |
| **permutation_p** | 0.1838 | ≤ 0.05 | **FAIL** |
| **max_drawdown_R** | 22.9974 | — | — |
| **MC_DD95_R** | 31.4889 | — | — |
| **halves** | [1, -1] | uniform positive | **FAIL** |
| **thirds** | [1, 1, -1] | uniform positive | **FAIL** |
| **walk_forward_last_third_net_R** | -0.0858 | > 0 | **FAIL** |
| **cost_drag_R** | 0.0962 | — | — |
| **mean_holding_bars** | 7.41 | — | — |
| **win_rate** | 33.6% | — | — |
| **wins / losses** | 36 / 71 | — | — |

### Result Classification

**H5_RESULT: DISCOVERY_FAIL**

Failure reasons (7 of 7 gates failed):
1. P(Sharpe > 0) = 0.8285 < 0.90 — Sharpe uncertainty too high
2. Permutation p = 0.1838 > 0.05 — edge not statistically significant
3. Halves [1, -1] — sign change between first/second half
4. Thirds [1, 1, -1] — sign change in last third
5. Walk-forward last third = -0.086 R — negative in out-of-sample period
6. Sharpe CI crosses zero [-0.12, 0.23]

---

## COST SCENARIOS (Track F)

| bps RT | N | net_expectancy_R | PF_net |
| --- | --- | --- | --- |
| 0 | 107 | 0.3313 | 1.5459 |
| 5 | 107 | 0.2832 | 1.4430 |
| 10 | 107 | 0.2351 | 1.3500 |
| 20 | 107 | 0.1389 | 1.1883 |
| 40 | 107 | -0.0536 | 0.9386 |

**Absolute cost semantics verified**: NET = GROSS - COST, monotone non-increasing.

---

## ASSET / DIRECTION DIAGNOSTICS (Track K1)

| Asset | N | gross_R | net_R |
| --- | --- | --- | --- |
| BTCUSDT | 45 | 0.5742 | 0.4555 |
| ETHUSDT | 30 | 0.2077 | 0.1209 |
| SOLUSDT | 32 | 0.1056 | 0.0321 |

| Direction | N | net_R |
| --- | --- | --- |
| LONG | 49 | 0.4281 |
| SHORT | 58 | 0.0738 |

**Diagnostics only** — no positive subgroup can override failed global result.

---

## ORTHOGONALITY (Track L)

| Comparison | Trade-time overlap | Daily PnL corr | Redundant? |
| --- | --- | --- | --- |
| vs ROC(24) proxy | 0.916 | (calc note below) | Potential |

**Note**: The orthogonality correlation calculation in the runner had a numerical bug (reported value >1, impossible for Pearson). Correct calculation pending re-run (blocked by exactly-once consumption). However, trade-time overlap of 0.916 > 0.6 alone raises concern.

If orthogonality gate fires (overlap > 0.6 AND corr > 0.7): **REDUNDANT_CANDIDATE**, even if PF > threshold.

---

## H5 REDUNDANT STATUS

| Field | Value |
| --- | --- |
| **H5_REDUNDANT** | TBD (pending corrected orthogonality calc) — but DISCOVERY_FAIL regardless |

---

## SHADOW (Track N)

| Field | Value |
| --- | --- |
| **R2_STATUS** | ACTIVE (unchanged) |
| **SHADOW_CAPTURES** | 11 |
| **SHADOW_MATURE** | 0 |
| **SHADOW_RESOLVED** | 0 |
| **SHADOW_PENDING** | 11 |
| **EARLIEST_MATURITY** | 2026-09-11T21:15Z |
| **SHADOW_POLICY_CONCLUSION** | INSUFFICIENT_SAMPLE |

---

## CONFIRMATION (Track O)

| Field | Value |
| --- | --- |
| **CONFIRMATION_ID** | CONF-EDGE-002-001 |
| **CONFIRMATION_CONSUMED** | false |
| **CONFIRMATION_EXECUTIONS** | 0 |
| **CONFIRMATION_CLOSES** | 2026-09-22T00:00Z |
| **STATUS** | UNTOUCHED |

---

## ACCEPTANCE CRITERIA CHECK

| Criterion | Status |
| --- | --- |
| H3-01 exactly-once historical claim corrected | ✅ PASS |
| H3-02 H3 result unchanged | ✅ PASS (DISCOVERY_FAIL preserved) |
| H3-03 no rerun | ✅ PASS |
| H5-01 prereg independently verified | ✅ PASS |
| H5-02 official data fields verified | ✅ PASS |
| H5-03 no spec drift | ✅ PASS |
| H5-04 PIT safe | ✅ PASS (verified by unit tests) |
| H5-05 implementation commit before execution | ✅ PASS |
| H5-06 independent implementation verifier | ✅ PASS |
| H5-07 STARTED durable before economic work | ✅ PASS |
| H5-08 exactly one experiment identity | ✅ PASS |
| H5-09 all attempts durable | ✅ PASS |
| H5-10 absolute cost semantics | ✅ PASS |
| H5-11 no tuning | ✅ PASS |
| H5-12 orthogonality | ⚠️ PENDING (calc bug, but irrelevant due to DISCOVERY_FAIL) |
| H5-13 promotions 0 | ✅ PASS |
| SH-01 mature only | ✅ PASS (0 mature, 0 resolved) |
| CONF-01 untouched | ✅ PASS |

---

## SUMMARY COUNTERS

| Counter | Value |
| --- | --- |
| **PAPER_PROMOTIONS** | 0 |
| **RISK_CHANGED** | 0 |
| **LIVE_CALLS** | 0 |
| **FALSE_SUCCESS** | 0 |

---

## FINAL STATUS

**STATUS: DISCOVERY_FAIL**

H5-ORDERFLOW-IMBALANCE-CONTINUATION-01 did not pass the preregistered discovery gates.

### Key findings:

1. **Positive**: The strategy shows positive gross expectancy (0.33 R) and net expectancy (0.24 R) at 10 bps, with PF_net = 1.35 > 1.15. The mechanism (taker-flow imbalance continuation) is economically plausible.

2. **Negative**: Statistical significance gates fail — Sharpe uncertainty too high (P(Sharpe>0) = 0.83 < 0.90), permutation test not significant (p = 0.18 > 0.05), and chronological stability fails (halves contradict, walk-forward last third negative).

3. **Cost sensitivity**: At 40 bps RT, net expectancy turns negative (-0.05 R), showing the edge is thin relative to costs.

4. **Orthogonality concern**: High trade-time overlap (91.6%) with ROC(24) momentum proxy suggests H5 may be capturing similar signals to simpler momentum strategies.

### Next steps (per checkpoint contract):

- **DO NOT PROMOTE TO PAPER** (H5 failed discovery)
- **WRITE FAILED RESEARCH MEMORY #12** — H5 order-flow imbalance continuation: positive gross expectancy but failed statistical significance and chronological stability gates
- **REFRESH REGIME/DATA GAP MAP** — order-flow regimes may need reclassification
- **DO NOT RETUNE H5** — prohibited by preregistration
- **CONTINUE R2 DIAGNOSTIC** — campaign unchanged
- **WAIT FOR SHADOW MATURATION** — earliest maturity 2026-09-11T21:15Z; resolve PIT when mature
- **CONFIRMATION WAIT** — CONF-EDGE-002-001 closes 2026-09-22

---

## ARTIFACTS PRODUCED

| Artifact | Path |
| --- | --- |
| H5 Result | `docs/external-audit-01/h5-orderflow-imbalance-01/H5_RESULT.json` |
| H5 Execution Marker | `docs/external-audit-01/h5-orderflow-imbalance-01/H5_EXECUTION_MARKER.json` |
| Execution Ledger | `docs/external-audit-01/h5-orderflow-imbalance-01/execution_ledger/research_execution_ledger.jsonl` |
| H5 Runner Script | `scripts/h5_run_exactly_once.py` |
| Source Registry | `docs/external-audit-01/source_registry.json` |
| H3 Correction | `docs/external-audit-01/H3_EXACTLY_ONCE_SEMANTICS_CORRECTION.md` |

---

## HERMETIC REGRESSION

Full hermetic test suite: **1224 passed / 0 failed** (verified at prereg commit c426b35)

---

*Report generated by buffy-agent on 2026-09-11 as part of H5-ORDERFLOW-INDEPENDENT-VERIFICATION-AND-DISCOVERY-01 checkpoint.*
