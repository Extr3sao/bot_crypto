# ARP-004 — RUN REPORT

## Environment

* START_SHA: `d4cd26da3e77ad508e3f50b0cb5a74bdc3815c5f`
* END_SHA: (stamped after commit)
* branch: `main`
* code_hash: `39fd35e638bdde6e1fbcfb59e8e1f582d0792a4ecc28d97181619e3f61c2afa7`
* config_hash: `6c4dd0be1fc2fff24920c9f9226c7f81f8d3d4dc80671b5a424721da497f7db1`
* dataset_fingerprint: `9d51385d570b8ff4ba1af22c3d4491f78c36111ec7383173e7d0351d5ee21658`
* cost: `COST_MODEL_V3` / `BINANCE_SPOT_STANDARD_TAKER` = `23.559016994374947` bps

## Commands

```
PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe scripts/alpha_recovery_v1_3.py
PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -m pytest -q
.venv/Scripts/python.exe -m ruff check .
.venv/Scripts/python.exe -m mypy . --exclude "reports"
```

The driver was executed twice; every generated JSON hashed identically (deterministic).

## Results

| experiment | DEV | COST | VALIDATION | ROBUSTNESS | OOS | FINAL |
| --- | --- | --- | --- | --- | --- | --- |
| `EXP-ARP-007` | PASS (153 trades, +0.776 bps gross) | **REJECT_COSTS** | NOT_REACHED | NOT_REACHED | NOT_OPENED | **REJECT_COSTS** |
| `EXP-ARP-010` | **INSUFFICIENT_EVIDENCE** (6 trades, −75.059 bps gross) | NOT_REACHED | NOT_REACHED | NOT_REACHED | NOT_OPENED | **INSUFFICIENT_EVIDENCE** |

* OOS opened: **NO** (both).
* Promotion candidates: **none**.
* `FALSE_SUCCESS`: **0**.

## Gates

| gate | result |
| --- | --- |
| pytest | **1503 passed**, 0 failed, 0 skipped (111 s) |
| ruff | `ruff check .` — clean |
| mypy | `Success: no issues found in 413 source files` |
| PIT tests | 11 tests in `tests/unit/research/test_alpha_recovery_daily.py` — pass |
| manifest tests | 7 tests in `tests/unit/research/test_alpha_recovery_manifests.py` + live `all_valid: true` |
| cost-model tests | cost from live `CostEngine`, never hardcoded |
| split-integrity | DEV/VALIDATION/OOS disjoint; OOS never read |
| diagnostic determinism | byte-identical JSON across two runs |

## Files written

Run root `reports/alpha-recovery-v1-3/`: `BASELINE.md`, `EXPERIMENT_SUMMARY.md`,
`DATA_COVERAGE.md`, `COST_ANALYSIS.md`, `VALIDATION_ANALYSIS.md`,
`ROBUSTNESS_ANALYSIS.md`, `EXP-ARP-009_INFRA_AUDIT.md`, `DATA_GAPS.md`,
`INDEPENDENT_VERIFICATION.md`, `ENVIRONMENT.json`, `MANIFEST_VALIDATION.json`,
`RUN_REPORT.{md,json}`, `FINAL_REPORT.md`, plus `EXP-ARP-00{7,10}/` (SPEC_AUDIT,
PIT_REPORT, DEV, COST_STRESS, DATA_COVERAGE, DECISION, MANIFEST_VALIDATION).

Tracked canonical evidence: `docs/research/alpha_recovery_v1_3/`.
