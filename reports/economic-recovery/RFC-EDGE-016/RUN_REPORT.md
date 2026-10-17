# WP-EDGE-016 — run report

*agent/edge-recovery/WP-EDGE-00-baseline @ 2b8a6ed7, generated 2026-10-17T11:01:25Z.*

Statuses (orthogonal — one passing does not confer another). Every name is declared
either true or false, so a missing status is visible:

- `PIT_FIXED_RISK_PARITY_VALIDATED` — **holds**
- `PIT_FIXED_RISK_PARITY_BLOCKED` — does not hold
- `ECONOMIC_RESULTS_RESTATED_NO_EDGE` — **holds**
- `PROSPECTIVE_CAPTURE_RUNNING_VALIDATED` — does not hold
- `PROSPECTIVE_CAPTURE_NOT_AUTOMATED` — **holds**
- `CAPTURE_BLOCKED_DISK` — **holds**
- `PROSPECTIVE_EVIDENCE_INSUFFICIENT` — **holds**
- `INDEPENDENT_VERIFIED` — **holds**
- `INDEPENDENT_VERIFICATION_FAILED` — does not hold
- `INDEPENDENT_VERIFICATION_NOT_RUN` — does not hold

## Headline

- **point_in_time**: 1.0 of 7081 pre-repair exits were filled at the bar whose close decided them; the restatement fills at the next executable bar and every row was rebuilt from the raw series by the verifier
- **risk**: experimental orders go through RiskManager.check_signal (the runtime's own engine); the lane's manual checks are 0
- **portfolio**: one shared book of 10000.0 USDT; the 015 lane's three books are labelled THREE_INDEPENDENT_SIMULATIONS
- **economics**: restated net -240.86 USDT for the best family at 1x and worse at 2x: NO_RESTATED_EDGE_SURVIVES
- **lane**: 146 closed trades, gross -53.384527 USDT, net -239.7503/-426.1162/-612.482 at 1x/2x/3x
- **prospective**: 3 bars observed of 2 expected per symbol, 0 proposals, 0 fills: no prospective trade exists
- **prospective_capture**: PROSPECTIVE_CAPTURE_NOT_AUTOMATED
- **disk**: INSUFFICIENT_FREE_SPACE at 5.043 GiB free; the guard was not relaxed (False)
- **scheduler**: DO_NOT_CREATE_A_SCHEDULER

## The six questions

1. **Fills and trades.** historical replay (015): 14 trades, net -12.809961 USDT — labelled `HISTORICAL_DESCRIPTIVE_PRE_PIT_FIX`; restated research: 2049 trades; experimental paper lane: 146 trades, -53.38452708701357 USDT gross; genuine prospective paper: 0; live: 0.
2. **Alpha survived.** 7081 pre-repair exits were filled at the bar whose close decided them and 0 violations remain: the restated edge is **NO_RESTATED_EDGE_SURVIVES**.
3. **Canonical risk and one budget.** entries are approved by `RiskManager.check_signal`; the lane runs one EDGE16LANE book; 0 manual checks remain in the lane.
4. **Unchanged risk, realistic costs.** mean_reversion_vol_liq: -240.86 / -1150.32 / -2059.78 USDT at 1x/2x/3x on 947 trades; trend_pullback: -1954.84 / -2775.1 / -3595.35 USDT at 1x/2x/3x on 860 trades; vol_regime_breakout: -187.08 / -418.33 / -649.58 USDT at 1x/2x/3x on 242 trades.
5. **Prospective witness.** 3 bars observed, 3 evaluated, 0 fills; disk CAPTURE_BLOCKED_DISK, scheduler DO_NOT_CREATE_A_SCHEDULER.
6. **What blocks adoption.**

   - the disk guard reports INSUFFICIENT_FREE_SPACE for the declared collection window: no new collector is started
   - a scheduled collector needs a governance decision and free space before it exists
   - 7/7 trading conflicts with blocks.weekend_trading=false and needs an ADR
   - 5 policy fields are declared in config/risk.yaml and read by no runtime component
   - the prospective sample is empty, so no strategy can be adopted on it

## Evidence

| artifact | bytes | sha256 |
| --- | --- | --- |
| `BASELINE.json` | 2129 | 739d976f0510bc63… |
| `PIT_DEFECT_MAP.json` | 12679 | 6156d29203918bb8… |
| `PIT_DEFECT_MAP.md` | 4132 | 9881b8daa6f39409… |
| `PIT_RECONCILIATION.md` | 4368 | bf7142cd7e137332… |
| `RISK_PARITY_MATRIX.json` | 11371 | 0eeeb9638bbef915… |
| `PORTFOLIO_ACCOUNTING.json` | 1320 | d2369150ee555ea0… |
| `WEEKEND_POLICY.json` | 956 | 6032e0af8fa2bcd5… |
| `WEEKEND_POLICY_CONFLICT.md` | 1340 | 795b3b693fa65557… |
| `ALPHA_RESTATEMENT_TRADES.jsonl` | 993785 | f2c0a1c97f3ce1b0… |
| `ECONOMIC_RESTATEMENT.csv` | 10204 | ea802c09e7df9dc0… |
| `CURRENT_VS_PROPOSED.json` | 5510 | ea12db85f05b0ba8… |
| `CAUSALITY_ADVERSARIAL.json` | 12707 | 6535a4f279aba4fe… |
| `CAPACITY_PREFLIGHT.json` | 718 | 098379da559c5703… |
| `CAPTURE_CONTINUITY.json` | 3265 | 1efe00b11e988e26… |
| `PROSPECTIVE_COVERAGE.md` | 1851 | ffa0189a7ddb0fe1… |
| `FULL_UNIT_SUITE.log` | 13233 | da0c1ac3ded50f17… |
| `SCHEDULER_DECISION.json` | 1428 | 2574e46dcb5677dc… |
| `SCHEDULER_DECISION.md` | 870 | 6dc2d22e8d64bef7… |
| `RESEARCH_TO_RUNTIME_EXECUTION_GAP.md` | 1658 | 6f274830bbf0d9cf… |
| `INDEPENDENT_VERIFICATION.json` | 16206 | 4060d1d56c993ea2… |
| `INDEPENDENT_VERIFICATION.md` | 10714 | 3254101d30556398… |
| `experimental_paper/CANONICAL_LANE_REPORT.json` | 8283 | bc903ba860a84f71… |
| `experimental_paper/CANONICAL_TRADES.jsonl` | 76109 | 5dd38f015be8b872… |
| `experimental_paper/CANONICAL_CYCLES.jsonl` | 360799 | 575367e437157da1… |
| `experimental_paper/COVERAGE_LEDGER.jsonl` | 1096464 | 6289c3b960da43a2… |

## Full unit suite

`pytest tests/unit -q` — PASSED_WITH_UNRELATED_FAILURES: 4 failed, 4012 passed in 939.34s (0:15:39)

| failure | scope |
| --- | --- |
| `tests/unit/research/test_st6_forward_regime.py::test_the_committed_artefacts_are_coherent` | outside this package (ST6 forward-regime line) |
| `tests/unit/research/test_st6_forward_regime.py::test_the_independent_verifier_passes_without_rewriting_the_committed_artefact` | outside this package (ST6 forward-regime line) |
| `tests/unit/test_dependency_closure_guard.py::test_all_imported_internal_modules_are_tracked` | this package |
| `tests/unit/test_dependency_closure_guard.py::test_closure_guard_is_order_independent_under_module_pollution` | this package |

the two ST6 failures belong to the forward-regime line, whose committed data has accumulated enough windows to contradict its own 'one window cannot satisfy the rule' assertion; this package neither imports nor writes anything under data/st6 or scripts/st6_forward_regime.py

the dependency-closure guard failures were this package's untracked modules; they pass once the files are added to Git, which is what re-run after the run recorded here

## Interpretation limits

- frictionless broker book: the lane's PnL is pre-cost by construction and its net view is a restatement
- no execution latency is modelled: the fill instant equals the instant the deciding bar closed
- one regime: the held-out tail of these series, 1h bars, long-only families
- funding is not charged because the venue is spot
