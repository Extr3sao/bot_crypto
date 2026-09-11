# RUN REPORT — ALPHA-DATA-ADMISSION-01 (+ HERMETIC-BASELINE-RECONCILIATION-01 + H5-GOVERNANCE-FINAL-CLOSURE)

Date: 2026-09-11 · Actor: buffy-agent (Freebuff) · Branch `feat/ma-2-specialist-opportunity-swarm`
Baseline `cb3de4f` → commits **`692286b`** (hermetic fix) → **`ec2483f`** (data admission) · Machine-readable: `RUN_REPORT.json`

| Track | Outcome |
| --- | --- |
| A — clean baseline | **PASS** — disposable worktree @ `cb3de4f`; env recorded (Py 3.11.15 / pytest 9.1.1 / uv 0.11.26); host `EXCHANGE_ID=bybit` identified |
| A1 — settings | **PASS** — `HOST_ENVIRONMENT_CONTAMINATION` proven at clean baseline (bybit→FAIL, unset/binance→PASS, garbage→FAIL); test made hermetic; **26/26 under all 4 adversarial envs** |
| A2 — dependency closure | **PASS** — root cause `UNTRACKED_IMPORTED_H5_SOURCE` (guard correct, NOT ordering); H5 code family tracked @`692286b`; guard untouched |
| A3 — full hermetic | **PASS** — **1259 passed / 0 failed / 0 skipped** @ `ec2483f`, no exclusions |
| B1/B2 — H5 orthogonality | **PASS** — executed semantics PROVEN from execution-era pyc; `EXECUTED_SOURCE_TEXT_AUTHORITY=INCOMPLETE`; `DERIVED_CONDITIONAL_PEARSON = 0.6070166220125719` (`NOT_INDEPENDENT_RECOMPUTATION`) |
| C — registry | **PASS** — 6 official sources registered; legacy `source_registry.json` preserved (H5 evidence-chain reference) |
| D/D1 — trade flow | **PASS** — per-asset coverage proven (BTC/ETH 2019-12-31+, SOL 2020-09-14+; 0 missing); 7-day sample ingested; `FULL_BACKFILL=COST_REVIEW_REQUIRED` (~101 GB) |
| E — open interest | **PASS** — REST ~30d limit empirically verified (error `-1130`); archive BTC 2020-09-01+, ETH/SOL 2021-12-01+ |
| F/G — engine + separation | **PASS** — deterministic quality engine w/ adversarial tests; raw immutable; provenance complete |
| H — fingerprints | **PASS** — cross-run A==B on full sample (42/42), C≠A sensitivity, order independence |
| I — alpha leakage | **PASS** — `ALPHA_LEAKAGE=0` (sweep of all new code/reports) |
| J — distinctness | **PASS** — trade flow YES (event-level flow) · OI YES (position stock) — data-level only |
| K — admission | **PASS** — `TRADE_FLOW = ADMIT_WITH_LIMITATIONS` · `OPEN_INTEREST = ADMIT` |
| L/M — shadow/confirmation | **WAIT** — mature-only rule enforced (0 mature at check; earliest 2026-09-11T21:15Z); `CONF-EDGE-002-001` untouched (closes 2026-09-22) |
| N — tests | **PASS** — data-admission 22/22 · settings 26/26 ×4 · guard 3/3 · **full hermetic 1259/0** |
| O — evidence | **PASS** — full report set in `data-admission-01/` + H5 authority files |

**Defects:** `DEF-DATA-OI-001` (OI cadence 15m→**5m**, 288 rows/day) registered and corrected everywhere; previous checkpoint status corrected `PASS→REPAIR_REQUIRED`, then resolved.

**Invariants:** `H6_CREATED=false` · `H5_RERUNS=0` · `RISK_CHANGED=0` · `PAPER_PROMOTIONS=0` · `LIVE_TRADING_CALLS=0` · `CREDENTIALS_USED=0` · `FALSE_SUCCESS=0`.

**STATUS: `PASS`**
