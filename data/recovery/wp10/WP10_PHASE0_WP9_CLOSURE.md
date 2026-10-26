# WP-10 phase 0 — controlled close of WP-9

> `2026-10-11T23:12:19Z` · **PARTIAL/FAIL — exit 4; producers failed: disk-audit, readiness, verifier; artefacts that did not match the commit: WP9_ACTIVE_ECONOMIC_BLOCKERS.json; inputs the commit does not carry: 1 named in this file**

* HEAD `90ed615b1b2514682bbf9a85834fdd81c45f0774` on `main`
* lane commit `90ed615b1b2514682bbf9a85834fdd81c45f0774` — Close WP-9 on its own files: the disk defect, the rehearsal, and the register.

## 1. Scope of the commit

* files touched: **73**
* owned: **71**
* declared exceptions: **2**
* other lanes' paths: **0**
* undeclared paths: **0**

* `scripts/start_paper_lab.py` — the enforcement point of the disk valve: the preflight that refuses an unaffordable window lives in the launcher, and WP-9's defect is only closed if the launcher refuses
* `src/trading_bot/research/disk_budget.py` — the disk valve itself: the measured-rate budget WP-9 introduced

## 2. Credentials

* files scanned: **73**, hits: **0**
* scanner canary detected: **True**

## 3. Clean checkout

* `C:\Users\GVLLFR~1\AppData\Local\Temp\wp10-phase0-90ed615b` at `90ed615b1b2514682bbf9a85834fdd81c45f0774` (is the requested commit: **True**)
* `trading_bot` resolved to `C:\Users\GVLLFR~1\AppData\Local\Temp\wp10-phase0-90ed615b\src\trading_bot\__init__.py` — inside the checkout: **True**
* dirty before the run: **no**

## 4. What ran in it

| id | exit | expected | result | seconds | what |
| --- | ---: | ---: | --- | ---: | --- |
| `disk-audit` | 2 | 0 | FAIL | 0.094 | the disk budget audit (the defect) |
| `readiness` | 1 | 0 | FAIL | 0.11 | M-03 / M-07 readiness |
| `economics` | 0 | 0 | PASS | 0.25 | ACTIVE economic blockers |
| `preflight-refusal` | 4 | 4 | PASS | 1.859 | the launcher refuses a 24 h window its collector budget cannot pay for |
| `preflight-refusal-default` | 4 | 4 | PASS | 1.656 | the same refusal on the default budget, with the run named |
| `preflight-autoscale` | 0 | 0 | PASS | 1.578 | the same window, with the collector budget autoscaled, is accepted |
| `focused-tests` | 0 | 0 | PASS | 2.438 | the WP-9 focused test file |
| `verifier` | 1 | 0 | FAIL | 0.125 | the independent verifier, after the artefacts it checks exist |
| `run-report` | 0 | 0 | PASS | 0.109 | the run report, folded from the regenerated artefacts |

## 5. Reproduction against the committed artefacts

compared **5**, mismatches **1**, not reproduced **5**

| artefact | producer | comparison | committed | regenerated | identical |
| --- | --- | --- | --- | --- | --- |
| `INDEPENDENT_VERIFICATION.json` | `verifier` | NOT_REPRODUCED | `—` | `—` | None |
| `RUN_REPORT.json` | `run-report` | full document, volatile keys excluded | `74167a8818485a67` | `74167a8818485a67` | True |
| `WP9_ACTIVE_ECONOMIC_BLOCKERS.json` | `economics` | full document, volatile keys excluded | `78632b74e3702f16` | `2522a22f3a88e819` | False |
| `WP9_CI_EXECUTION_REPORT.json` | `ci-audit` | NOT_REPRODUCED | `—` | `—` | None |
| `WP9_DISK_BUDGET_AUDIT.json` | `disk-audit` | NOT_REPRODUCED | `—` | `—` | None |
| `WP9_M03_M07_READINESS.json` | `readiness` | NOT_REPRODUCED | `—` | `—` | None |
| `WP9_RUNTIME_24H_REPORT.json` | `runtime-legs` | NOT_REPRODUCED | `—` | `—` | None |
| `evidence/preflight_autoscale.out` | `preflight-autoscale` | projection(disk, duration_hours, processes, verdict) | `82e3ea840f9a6bf4` | `82e3ea840f9a6bf4` | True |
| `evidence/preflight_refusal.out` | `preflight-refusal` | projection(disk, duration_hours, processes, verdict) | `82e3ea840f9a6bf4` | `82e3ea840f9a6bf4` | True |
| `evidence/preflight_refusal_default.out` | `preflight-refusal-default` | projection(disk, duration_hours, processes, verdict) | `82e3ea840f9a6bf4` | `82e3ea840f9a6bf4` | True |

Inputs a producer said it could not find in the clean checkout:

* `C:\\Users\\GVLLFR0035\\AppData\\Local\\Temp\\wp10-phase0-90ed615b\\reports\\microstructure-forward-continuous\\manifest\\paper-lab-continuous-02.json`

## 6. Controls

| id | what | detected |
| --- | --- | --- |
| `control-classifier` | a foreign lane's path and an undeclared path are both reported | **True** |
| `control-secret-canary` | the secret scanner sees a synthetic credential | **True** |
| `control-reproduction` | a comparison against a mutated reference is flagged | **True** |
| `control-nothing-ran` | an artefact whose producer did not run is excluded from the identity claim | **True** |

## 7. Not exercised

* the four runtime legs: they start the real launcher and a scheduler, so the closure runs them only when asked for explicitly (--run-runtime-legs)
* the CI execution report: regenerating it re-runs two other lanes' workflow sequences (~9 min) and does not verify WP-9's own claims, which wp9_verify.py re-derives from the workflow text instead

