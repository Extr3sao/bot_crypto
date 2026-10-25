# WP-9 — RUN REPORT

> `2026-10-11T21:11:16Z` · **PARTIAL — every capability claim is verified and every missing one is named; CI_CERTIFIED and a 24 h stability verdict are both withheld by their own criteria**

## 1. What ran

| step | what it establishes | command | verdict | file |
| --- | --- | --- | --- | --- |
| `WP9-B1` | disk budget audit: why the 24 h window stopped, and what 24/48/72 h cost | `uv run python scripts/wp9_disk_budget_audit.py` | DISK_BUDGET_MEASURED | `data/recovery/wp9/WP9_DISK_BUDGET_AUDIT.json` |
| `WP9-B2` | disk budget preflight: the launcher refuses a window its valve cannot pay for | `uv run python scripts/start_paper_lab.py --duration-hours 24 --dry-run` | — | `data/recovery/wp9/evidence/preflight_refusal.out` |
| `WP9-C1` | runtime rehearsal: the real entrypoint, four legs, a controlled stop and a resume | `uv run python scripts/wp9_runtime_rehearsal.py --run-id wp9-runtime-legs --interval 20 --cycles 3 --bar-close-cycles 1 --stop-after-seconds 45` | WINDOW_INCOMPLETE | `data/recovery/wp9/WP9_RUNTIME_24H_REPORT.json` |
| `WP9-D1` | M-03 / M-07 readiness against the machine-readable pre-registration | `uv run python scripts/wp9_m03_m07_readiness.py` | — | `data/recovery/wp9/WP9_M03_M07_READINESS.json` |
| `WP9-E1` | ACTIVE economic blockers, classification and the cost/entry RFC draft | `uv run python scripts/wp9_economic_blockers.py` | strategies_total=24 | `data/recovery/wp9/WP9_ACTIVE_ECONOMIC_BLOCKERS.json` |
| `WP9-A1` | CI runtime certification: the workflows audited, the sequence executed locally | `uv run python scripts/wp9_ci_audit.py` | BLOCKED | `data/recovery/wp9/WP9_CI_EXECUTION_REPORT.json` |
| `WP9-F1` | independent verification of every headline claim, with negative controls | `uv run python scripts/wp9_verify.py` | PASS | `data/recovery/wp9/INDEPENDENT_VERIFICATION.json` |

## 2. The state the reports describe

* disk: planning rate **192.252 MB/h**; findings WP9-DISK-01, WP9-DISK-02, WP9-DISK-03

| horizon | required (mean) | required (1.5x) | fits | fits at 1.5x |
| --- | ---: | ---: | --- | --- |
| 24 h | 4.62 GB | 6.93 GB | True | True |
| 48 h | 9.24 GB | 13.85 GB | True | True |
| 72 h | 13.85 GB | 20.78 GB | True | False |

* M-03: `NOT_READY` (2 criteria unmet, 72.0 h to close)
* M-07: `NOT_READY` (4 criteria unmet, 168.0 h to close)
* economics: EXECUTION_COSTS (primary for 7, flagged for 24) on top of NO_ECONOMIC_ADVANTAGE (primary for 17) — 0 strategies with demonstrable net advantage, next experiment: E-1 — measure the cost plane; then E-2 — the 30m entry screen
* runtime: `WINDOW_INCOMPLETE` — 0.06209 h of 24.0 h, window_complete=False, 4 checks not exercised
* CI: `BLOCKED` — ci_certified=False, runner=LOCAL, sequence 12 steps, 0 failed, 3 blocking reason(s)

## 3. Legs of the runtime rehearsal

| leg | exit | seconds | traces added |
| --- | ---: | ---: | ---: |
| 1-interval-cadence | 0 | 51.953 | 6 |
| 2-bar-close-cadence | 0 | 69.157 | 2 |
| 3-controlled-stop | 0 | 49.375 | 4 |
| 4-resume-after-stop | 0 | 53.031 | 6 |

## 4. Governance

* `LIVE_TRADING = DISABLED`
* `TRADES_AUTHORIZED = 0`
* `PROFITABILITY_VERIFIED = False`
* `FALSE_SUCCESS = 0`
* `admitted_strategies = 0`

## 5. Not proven by this work package

* that either workflow has ever run on a GitHub runner (no credential, no registration, and the commit that carries them is not published)
* that the runtime is stable over 24 h (a fraction of a day was executed and the report says WINDOW_INCOMPLETE)
* that any strategy is profitable (0 admitted, 0 net-positive, best gross 8.912 bps against a 23.354 bps plane)
* that M-03 or M-07 can be researched yet (both NOT_READY with their shortfall stated)

