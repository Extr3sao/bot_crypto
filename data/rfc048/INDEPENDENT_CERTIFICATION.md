# RFC-048V — Independent Certification

- Head: `081201f1eeaf` · baseline `19b1a0b`
- Status: **RFC048_OFFLINE_CERTIFIED** · FALSE_SUCCESS = 0

## Gates

| gate | result | evidence |
| --- | --- | --- |
| ruff check · ruff format · mypy strict | PASS | 14 delivered files: All checks passed!; 22 files already formatted; Success: no issues found in 22 source files |
| repo-wide suite (`pytest tests`) | PASS | 3210 passed, 78 warnings in 268.08s (0:04:28) |
| RFC-048 independent verifier | PASS | 31 decisions, 303 checks, 8/8 negative controls |
| adversarial falsification | PASS | 4000 random scenarios, 0 false approvals |
| runtime authority | PASS | 31 decisions through the real engine |
| tests | PASS | risk suite: 119 passed in 6.23s; unit suite: 3163 passed in 270.21s (0:04:30) |
| economic integrity | PASS | 41 re-derived checks |
| point-in-time funding | PASS | 4 probes |
| governance | PASS | protected paths untouched: True |

## Manifest

- 50 delivered files hashed (digest `4ee673cc040a7ded…`)

## Attack family coverage (§03)

| family | evidence | outcome |
| --- | --- | --- |
| equity near zero | `S07`, `S16` | S07=NO_TRADE; S16=NO_TRADE |
| margin nearly exhausted | `S08` | S08=NO_TRADE |
| stop too close | `S09`, `S10` | S09=RISK_VETO; S10=RISK_VETO |
| stops with gaps | `S12`, `S24`, `S27` | S12=RISK_VETO; S24=RISK_VETO; S27=RISK_VETO |
| leverage above the admissible level | `S23`, `S31` | S23=REDUCE_SIMULATED_SIZE; S31=RISK_VETO |
| stale or future data | `S18`, `S19` | S18=DATA_INVALID; S19=DATA_INVALID |
| funding absent or adverse | `S14`, `S13` | S14=NO_TRADE; S13=REDUCE_SIMULATED_SIZE |
| commissions omitted or unknown | `S21`, `S15` | S21=NO_TRADE; S15=NO_TRADE |
| liquidation before the stop | `S11` | S11=RISK_VETO |
| maintenance bracket change | `S12`, `S24`, `S31` | S12=RISK_VETO; S24=RISK_VETO; S31=RISK_VETO |
| quantity rounding | `I10_ROUNDING_REDUCES` | I10_ROUNDING_REDUCES=HELD |
| non-finite, overflow and infinities | `DEF-048V-01`, `DEF-048V-02`, `DEF-048V-05` | DEF-048V-01=FIXED; DEF-048V-02=FIXED; DEF-048V-05=FIXED |
| adverse mark price | `S12`, `S24`, `S25` | S12=RISK_VETO; S24=RISK_VETO; S25=RISK_VETO |
| long and short | `S01`, `S02`, `S24`, `S31` | S01=REDUCE_SIMULATED_SIZE; S02=REDUCE_SIMULATED_SIZE; S24=RISK_VETO; S31=RISK_VETO |
| several correlated assets | `S22` | S22=NO_TRADE |
| double concurrent reserve | `simultaneous_reserve`, `reserve_release_storm` | simultaneous_reserve=invariants_hold; reserve_release_storm=invariants_hold |
| repeated decision id | `retry_same_decision`, `DEF-048V-03` | retry_same_decision=invariants_hold; DEF-048V-03=FIXED |
| portfolio snapshot skew | `snapshot_skew` | snapshot_skew=invariants_hold |

## Repo-wide suite and hermeticity

- verdict: **PASS** — 3210 passed, 78 warnings in 268.08s (0:04:28)
- hermeticity probe: 6769 files under `reports/` sampled over 30.0s with no local test running; 0 changed ()

## Estado anterior vs corregido

- `RUNTIME_EXECUTION_REPORT.json`: 9 fields changed (the concurrency probe only — see below)
- concurrency before: {'probe': '8 concurrent decisions on one equity pool of 200 USDT', 'approved_count': 8, 'refused_count': 0, 'sum_approved_margin': 132.000078771, 'ledger_reserved': 132.000078771, 'ledger_free': 67.999921229, 'equity': 200.0, 'invariant_holds': True, 'refusal_reasons': []}
- concurrency after: {'probe': '8 concurrent decisions on one equity pool of 200 USDT', 'approved_count': 6, 'refused_count': 2, 'sum_approved_margin': 99.0000590783, 'ledger_reserved': 99.0000590783, 'ledger_free': 100.9999409217, 'equity': 200.0, 'invariant_holds': True, 'refusal_reasons': ['MARGIN_UTILIZATION_LIMIT']}
- `INDEPENDENT_VERIFICATION.json`: 1 field(s) changed; decision-level result unchanged = True

the concurrency probe runs 8 simultaneous decisions on one equity pool; before the aggregate ceiling was enforced on the live reservation all 8 were approved (132 USDT reserved), after it 6 are approved and 2 are refused by MARGIN_UTILIZATION_LIMIT (99 USDT reserved). The refusals are the fix, not a regression.

only the generation timestamp moved: the RFC-048 verifier returned VERIFIED against the pre-fix engine too, because it re-derives the recorded decision catalogue and that catalogue never stepped on a non-finite input, a repeated decision id or an aggregate ceiling. That is a coverage limitation of the RFC-048 verification, and it is why RFC-048V adds a generative falsifier and a runtime-authority probe instead of re-running the verifier alone.

## Notes

- the certification is generated against the working tree that is then committed; --verify-commit re-checks the delivered blobs read-only
- FALSE_SUCCESS counts every false approval across the independent verifier, the adversarial campaign and the verifier's exit code
- the repo-wide suite is recorded with the ownership of every failure: a failure that disappears in isolation and whose observation window is provably written by foreign processes is reported as EXTERNAL_NON_HERMETIC, never silently excluded and never counted as a pass
