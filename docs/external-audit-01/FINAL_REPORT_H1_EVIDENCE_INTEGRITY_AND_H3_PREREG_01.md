# FINAL REPORT — H1-EVIDENCE-INTEGRITY-AND-H3-RELATIVE-VALUE-PREREG-01 + POC02-R2 SHADOW CONTINUATION

Date: 2026-09-10 · Branch: `feat/ma-2-specialist-opportunity-swarm` · Prereg commit: `83b3acd`

## Headline

The H1 cost-sensitivity anomaly was **real and now proven**: `DEF-RESEARCH-COST-001`
(**FORMULA_DEFECT**, display-only). The defective branch applied a cost *delta vs the
10 bps baseline* to the **gross** series, producing an impossible +0.0592 at 5 bps and a
duplicated 10 bps value at "20 bps". The component is repaired with a monotonicity
regression test; the committed H1 result artifact was deliberately **not** rewritten.
H1 remains **DISCOVERY_FAIL** on cost-independent evidence. Exactly one H3 hypothesis
was selected **performance-blind** and preregistered (spec sha256 frozen); **H3 is not
executed**. STATUS: **PASS**.

## Required report block

| Field | Value |
| --- | --- |
| CHECKPOINT | H1-EVIDENCE-INTEGRITY-AND-H3-RELATIVE-VALUE-PREREG-01 |
| COST_SENSITIVITY_INTEGRITY | **FAIL** (component was defective) → repaired this checkpoint |
| DEF_RESEARCH_COST_001 | **CONFIRMED** (FORMULA_DEFECT, display-only; registered in DEFECT_REGISTER.md, FIXED) |
| ROOT_CAUSE | `compute_trade_metrics` sensitivity branch computed `gross_r − ((cost_bps−10)/10000)/risk_frac` — a delta vs the 10 bps baseline subtracted from **gross**; at 5 bps the negative delta *adds back* cost (→ +0.0592 > gross −0.0030, impossible); at 20 bps the delta equals the 10 bps cost (→ duplicate −0.1275). Legacy values reproduced to machine precision (≤1e-12). |
| ZERO_BPS_EXPECTANCY | −0.003034 R |
| FIVE_BPS_EXPECTANCY | **−0.065268 R** (reported +0.0592 was defective) |
| TEN_BPS_EXPECTANCY | −0.127502 R (matches committed H1 net — unchanged) |
| TWENTY_BPS_EXPECTANCY | **−0.251970 R** (reported −0.1275 was defective) |
| MONOTONICITY | **PASS** after absolute-cost recomputation (NET=GROSS−COST verified ≤1e-12; COST≥0) |
| TRADE_SET_IDENTICAL | **true** (N=10,193 in all scenarios; `TRADE_SET_SHA256` in COST_SENSITIVITY_AUDIT.json; no entry/exit rule consumes any cost scenario) |
| AFFECTED_RESEARCH_RESULTS | H1 `slippage_sensitivity_net_R` display field ONLY (METRIC_AFFECTED). Legacy retro, volatility_structure, cross_sectional, carry_funding, Strategy Lab, R2, Shadow: UNAFFECTED (independent cost engines) |
| GATE_AFFECTED_RESULTS | **none** — B4 classification consumed the precomputed 10 bps net series (`t.net_r`), arithmetically independent of the defective branch; no historical PASS/FAIL preserved on a miscomputed gate |
| H1_FINAL_STATUS | **DISCOVERY_FAIL** (final; rejection independent of the suspect metric: gross −0.0030 R, gross PF 0.995<1, Sharpe CI entirely <0, perm p=1.0, halves/thirds negative; corrected sensitivity strengthens it) |
| H1_FAILED_MEMORY | PASS — #10 amended (SHORT_ON_SHOCK mechanism, cost-independent rejection); NORMAL→HIGH (N=11) + BULL\|RANGE→NEUTRAL\|TRANSITION (N=20) = POST_HOC_LEAD_ONLY / INSUFFICIENT_SAMPLE / DO_NOT_RETEST_WITHOUT_NEW_EX_ANTE_HYPOTHESIS |
| H3_SELECTED_HYPOTHESIS | **BTC↔ETH beta-neutral log-price spread mean reversion** (`H3-RELVAL-BTCETH-BETANEUTRAL-SPREAD-01`) |
| H3_ECONOMIC_RATIONALE | Co-moving majors' temporary beta-adjusted log-spread divergences are relative mispricings that revert; monetizes relative displacement with no directional view. NOT momentum/trend under another name; gap authority LOW_VOL/RANGE ACTIVITY_WITHOUT_EDGE + absent cross-asset family; memory #7 orthogonality pre-declared, #1/#9/#10 cost lessons honored (sparse entries, two-leg costs), #8 not reused |
| H3_ASSETS | BTCUSDT (leg A) ↔ ETHUSDT (leg B), beta-weighted opposite legs |
| H3_TIMEFRAME | 1h (binanceusdm; frozen window 2020-01-01 → 2026-09-09, 58,633 rows/leg) |
| H3_EXPECTED_TARGET_REGIME | Co-moving regimes (rolling corr ≥ 0.60 gate); regime attribution recorded per trade; gap: LOW_VOL/RANGE ACTIVITY_WITHOUT_EDGE |
| H3_PREREG_COMMIT | `83b3acd` (manifest blob sha256 `66e7a2720a044c7c…`) |
| H3_SPEC_SHA256 | `90c566993b9cdd6b42b9eac5b482f8a96657728cbfd8c04a2df3567b23848d50` |
| H3_PROTOCOL_SHA256 | embedded in spec (`execution_protocol`), covered by H3_SPEC_SHA256 |
| H3_COST_MODEL_SHA256 | embedded in spec (`cost_model`: 2 legs × 5 bps/side on entry+exit = 4 executions/trade; funding N/A ex ante), covered by H3_SPEC_SHA256 |
| H3_EXECUTIONS | **0** (no backtest, no performance statistic computed or observed; selection performance-blind) |
| R2_STATUS | ACTIVE — POC-02-R2-direction-arbitration-01, 11 cycles, heartbeat 2026-09-10T11:28:51Z, unchanged (diagnostic classification retained) |
| SHADOW_CAPTURES / RESOLVED | 11 / 0 (earliest maturity 2026-09-11T21:15Z; nothing resolved early) |
| SHADOW_POLICY_CONCLUSION | INSUFFICIENT_SAMPLE |
| CONFIRMATION_CONSUMED / EXECUTIONS | false (`CONF-EDGE-002-001`, closes 2026-09-22, no early inspection) / 0 |
| RISK_CHANGED | 0 (src/trading_bot/risk/ + config/ untouched) |
| LIVE_CALLS / FALSE_SUCCESS | 0 / 0 (REAL_BROKER=0, PRIVATE_EXCHANGE=0, SHADOW_PAPERBROKER=0) |
| HERMETIC_REGRESSION | PASS — **1211 passed / 0 failed** (1210 prior + 1 new DEF-RESEARCH-COST-001 invariant test) |
| STATUS | **PASS** |

## Acceptance

- **COST-01..04** PASS — formula traced with exact units (audit report A1); identical trade set proven (A2 + TRADE_SET_SHA256); monotonicity verified from raw immutable trades (A3 table).
- **COST-05/06** PASS — impact report produced (A5); no false historical evidence preserved (defect registered, component fixed, defective values superseded; frozen H1 artifact preserved as-found by governance precedent).
- **H1-01/02/03** PASS — final rejection cost-independent; failed-memory updated; tiny post-hoc cells not promoted.
- **H3-01..09** PASS — exactly one hypothesis; economic rationale pre-result (selection record); PIT trailing windows + future-mutation invariant preregistered; synchronization contract (NO_SIGNAL on missing leg, no forward-fill); two-leg costs; structural market-neutrality gate (net beta exposure ≤ 0.10); orthogonality pre-declared (C8); spec committed with frozen hash; executions = 0.
- **R2-01 / SH-01 / CONF-01** PASS. **LIVE_CALLS=0, FALSE_SUCCESS=0.**

## NEXT

- COST engine is VALID after repair → next checkpoint: **VERIFY_H3_PREREG** (ordering:
  H3 execution commit strictly after `83b3acd`; spec sha256 unchanged) →
  **EXECUTE_H3_EXACTLY_ONCE** with the frozen exactly-once protocol, PIT tests, and the
  pre-declared orthogonality/redundancy rules. No parameter sweep, no peeking.
- CONTINUE_R2 (no restart) · MATURE_SHADOW (first capture matures 2026-09-11T21:15Z;
  aggregate Risk diagnostic only at ≥25 mature) · CONFIRMATION_WAIT (≤ 2026-09-22).
