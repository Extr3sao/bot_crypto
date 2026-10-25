# WP-EDGE-09 — run report

*Run `EDGE09-REPORT-20261015T055625Z` at `2026-10-15T05:56:25Z`, branch `agent/edge-recovery/WP-EDGE-00-baseline`, head `d5c93bd9f724`. Verdict: **NO_ECONOMIC_EDGE_FOUND** — the forward quote data is real and usable, but no measured structure covers the 23-24 bps round trip: the best long-only gross is 1.582703 bps, the tape offers no barrier-clearing move at a 1 or 5 second horizon, and the cheapest registered venue still costs more than the measured gross*

## 1. Acceptance, row by row

| # | Requirement | Status | Evidence |
| --- | --- | --- | --- |
| A-1 | audit the repository, the runtime and the data held, before writing code | **PASS** | audit/ESTATE.json: 19 capture runs measured, 6 authoritative files digested, runtime mode paper |
| A-2 | data quality, provenance, coverage and point-in-time viability per source | **PASS** | 5 live probes; 10.14 h of forward capture over 21 runs; every source classified |
| A-3 | falsifiable economic hypotheses, registered before measuring | **PASS** | PREREGISTRATION.json binds 7 hypotheses to the digest of the code that obeys them; `edge09_preregister.py --check` re-renders it |
| A-4 | cost, liquidity, capacity and frequency evaluated before experiments | **PASS** | gates: 40 venue/asset barriers, 377 capacity snapshots, 50 frequency rows |
| A-5 | controlled experiments only where the gates allow, negatives included | **PASS** | 7 hypotheses classified; 4 ended with a measured non-positive or insufficient classification |
| A-6 | independent verification and adversarial tests | **PASS** | VERIFICATION.json: 18/18 checks; sabotage self-test PASS (18/18 tampered inputs detected) |
| A-7 | ACTIVE and QUALITY kept apart | **PASS** | two tracks with their own targets in PREREGISTRATION.json (ACTIVE 3.0/day, QUALITY 0.05/day); the ACTIVE experiments are the imbalance and frequency ones, the QUALITY hypothesis is the 5-minute open-interest one, and no reading pools them |
| A-8 | keep the ACTIVE objective of three executed trades a day, forcing nothing | **MEASURED** | the frequency bound is computed on the tape's own non-overlapping windows: {"1": 0.0, "5": 0.0, "60": 48.018, "900": 179.619, "3600": 11.553}; no trade was forced and none was taken |
| A-9 | do not reuse the holdouts consumed by EDGE-07 and EDGE-08 | **PASS** | the measured universe is BTC/ETH/SOL, which shares no symbol with the EDGE-08 cross-section; the EDGE-07 window is part of no criterion here; the overlap that does exist (calendar, different modality) is declared in the audit |
| A-10 | invent no order book, funding, open interest, liquidation or timestamp data | **PASS** | every quote in the panel comes from a captured row; missing seconds are counted and absent, never interpolated; the liquidation endpoint answered 404 and is reported unavailable rather than substituted |
| A-11 | change no risk limit, leverage, sizing or real execution | **PASS** | config/risk.yaml digest 3c27c866d5f11afe… unchanged since 10cdee2 chore: initial Phase 0 scaffolding for crypto-scalping-agentic-bot; runtime mode paper, live trading disabled; promotion NONE and order_sent false everywhere |
| A-12 | register rejected hypotheses and negative experiments | **PASS** | EXPERIMENT_REGISTRY.{json,md} carries every hypothesis with its classification and reason, including the negative control: ['COST_KILLED', 'INSUFFICIENT_SAMPLE', 'NO_GROSS_EDGE', 'OBSERVED'] |
| A-13 | FALSE_SUCCESS = 0 and BUILDER != VERIFIER | **PASS** | false_success = 0; the verifier is a separate script that re-derives samples from the raw segments and carries its own copy of the thresholds, which it compares with the registration |
| A-14 | declare no profitability and no paper or production readiness without evidence | **PASS** | no artifact of this package carries a promotion or a size; the closure status is NO_ECONOMIC_EDGE_FOUND, with PAPER_CANDIDATES = 0 |
| A-15 | deliver run report, final report, executive summary, economic matrix, source registry, tests and verification | **PASS** | RUN_REPORT.{json,md}, FINAL_REPORT.md, INFORME_EJECUTIVO.md, ECONOMIC_MATRIX.{json,md}, sources/SOURCE_VIABILITY.{json,md}, docs/source_registry.md extended, VERIFICATION.{json,md}, 27 artifact digests published |
| A-19 | deliver the artifact names the RFC asks for: baseline, capability and feasibility registries, plan, window and experiment ledgers, results matrix | **PASS** | BASELINE.json, DATA_CAPABILITY_REGISTRY.json, DATA_CAPABILITY_REGISTRY.md, DATA_FEASIBILITY_MATRIX.json, DATA_FEASIBILITY_MATRIX.md, HYPOTHESIS_REGISTRY.json, EXPERIMENT_PLAN.md, WINDOW_LEDGER.jsonl, ECONOMIC_FEASIBILITY_REPORT.json, ECONOMIC_FEASIBILITY_REPORT.md, COST_CAPACITY_FREQUENCY_MATRIX.json, COST_CAPACITY_FREQUENCY_MATRIX.md, EXPERIMENT_LEDGER.jsonl, RESULTS_MATRIX.json, RESULTS_MATRIX.md; rendered from the frozen payloads by scripts/edge09_deliverables.py with the digests they were rendered from, and re-checked by VERIFICATION.json C-15 to C-18 |
| A-16 | publish in isolated commits with a safe push | **PASS** | branch agent/edge-recovery/WP-EDGE-00-baseline, head d5c93bd, remote tip d5c93bd, matches head True, force push used False |
| A-17 | close with NO_VIABLE_DATA or NO_ECONOMIC_EDGE_FOUND when that is what the evidence says | **NO_ECONOMIC_EDGE_FOUND** | the forward quote data is real and usable, but no measured structure covers the 23-24 bps round trip: the best long-only gross is 1.582703 bps, the tape offers no barrier-clearing move at a 1 or 5 second horizon, and the cheapest registered venue still costs more than the measured gross |
| A-20 | run the wider research suite too, and declare what it finds instead of keeping it out of the package | **PASS** | RESEARCH_SUITE.{json,md}: 2296 passed, 1 failed, 1 of them inherited (outside every path this package commits to); nothing was suppressed to get that number |
| A-18 | owned tests, lint, format and types | **PASS** | owned: exit 0 (21 passed in 1.38s); lint: exit 0 (All checks passed!); format: exit 0 (18 files already formatted); types: exit 0 (Success: no issues found in 8 source files) |

## 2. What was measured, and where the evidence lives

- Forward capture folded into the panel: ['paper-lab-continuous-02', 'paper-strategy-lifecycle-shadow-02'] — 10 streams, 95913 seconds, 16626886 quote events, 287946 trades.
- Barriers (admission scenario, Binance spot taker): {"perp|BTCUSDT": 23.1104, "perp|ETHUSDT": 23.1512, "spot|BTCUSDT": 23.0968, "spot|ETHUSDT": 23.1508, "perp|SOLUSDT": 24.0731, "spot|SOLUSDT": 24.0813} bps.
- Best long-only gross measured: **1.582703 bps** (perp/SOLUSDT at 60s).
- Negative control: ['COST_KILLED', 'NO_GROSS_EDGE', 'NO_INFORMATION']; `false_success = 0`.
- Wider research suite: 2296 passed, 1 failed, 1 inherited (`RESEARCH_SUITE.md`).
- Baseline commit `ef5c8f2baa4a` is the tree this package found and audited; the reading above is taken at `d5c93bd9f724` on `agent/edge-recovery/WP-EDGE-00-baseline`, and the one-commit lag of GITHUB_STATE.json (written before the commit that carries it, then pushed) is stated there rather than hidden.

## 3. Verdicts per hypothesis

| Hypothesis | Track | Classification | Failed filter | Why |
| --- | --- | --- | --- | --- |
| `E-01` | ACTIVE | **COST_KILLED** | F2 | best measured cell perp/SOLUSDT h=60s gross 1.582703 bps vs 24.0731 bps barrier — gross 1.5827 bps is below the measured round trip 24.0731 bps (cells: {'COST_KILLED': 30}) |
| `E-02` | CROSS-VENUE | **COST_KILLED** | F2 | the cheapest registered schedule (MEXC_SPOT_TAKER at 12.9866 bps) still exceeds the best measured gross (1.582703 bps): the fee schedule is not the only constraint |
| `E-03` | ACTIVE | **OBSERVED** | F4 | spot depth snapshots are rare in this capture, so a spot capacity claim rests on a small number of observations and is reported as such |
| `E-04` | QUALITY | **INSUFFICIENT_SAMPLE** | — | PRICE_DOWN_OI_UP n=14 mean=-8.015351 bps against a barrier of 23.1512 bps |
| `E-05` | ACTIVE | **OBSERVED** | — | the tape clears the barrier at h=60s at 144.061 long-only opportunities/day (upper bound, long-only, extrapolated from 1.999-4.155 h of capture), so the ACTIVE frequency target is not what blocks the  |
| `E-06` | EXECUTION | **OBSERVED** | — | median measured taker shortfall 0.0187 bps against the modelled spread+impact components |
| `E-07` | GUARD | **NO_GROSS_EDGE** | — | negative control verdicts: ['COST_KILLED', 'NO_GROSS_EDGE', 'NO_INFORMATION'] |

## 4. Verification, tests and digests

- Independent verifier: **PASS** (18/18); sabotage self-test PASS.
- `owned`: exit `0` — 21 passed in 1.38s
- `lint`: exit `0` — All checks passed!
- `format`: exit `0` — 18 files already formatted
- `types`: exit `0` — Success: no issues found in 8 source files

| Artefact | Bytes | SHA-256 |
| --- | ---: | --- |
| `reports/edge-recovery/WP-EDGE-09/BASELINE.json` | 7886 | `e3bdc451e2afb20b…` |
| `reports/edge-recovery/WP-EDGE-09/COST_CAPACITY_FREQUENCY_MATRIX.json` | 15182 | `eb6950c64eb62c87…` |
| `reports/edge-recovery/WP-EDGE-09/COST_CAPACITY_FREQUENCY_MATRIX.md` | 1752 | `46b38aadfe7cb946…` |
| `reports/edge-recovery/WP-EDGE-09/DATA_CAPABILITY_REGISTRY.json` | 28576 | `11c3e56fe34098a6…` |
| `reports/edge-recovery/WP-EDGE-09/DATA_CAPABILITY_REGISTRY.md` | 3780 | `6c02e13521e66491…` |
| `reports/edge-recovery/WP-EDGE-09/DATA_FEASIBILITY_MATRIX.json` | 8986 | `3483c89361dde650…` |
| `reports/edge-recovery/WP-EDGE-09/DATA_FEASIBILITY_MATRIX.md` | 2342 | `1138a4b3fc2a1482…` |
| `reports/edge-recovery/WP-EDGE-09/DELIVERABLES.json` | 3683 | `749d084e17be4055…` |
| `reports/edge-recovery/WP-EDGE-09/ECONOMIC_FEASIBILITY_REPORT.json` | 10776 | `b403b9cff3fb275b…` |
| `reports/edge-recovery/WP-EDGE-09/ECONOMIC_FEASIBILITY_REPORT.md` | 2640 | `bf0d451438f83d69…` |
| `reports/edge-recovery/WP-EDGE-09/EXPERIMENT_LEDGER.jsonl` | 160839 | `5a1c2e495305d67a…` |
| `reports/edge-recovery/WP-EDGE-09/EXPERIMENT_PLAN.md` | 4131 | `bb8b8c420d51c847…` |
| `reports/edge-recovery/WP-EDGE-09/HYPOTHESIS_REGISTRY.json` | 13429 | `aadb7bd68df10da7…` |
| `reports/edge-recovery/WP-EDGE-09/PREREGISTRATION.json` | 9250 | `7e2acbddef8f45d5…` |
| `reports/edge-recovery/WP-EDGE-09/PREREGISTRATION.md` | 7524 | `b74f4a2b977d46d5…` |
| `reports/edge-recovery/WP-EDGE-09/RESEARCH_SUITE.json` | 1302 | `b37594ef414ed02c…` |
| `reports/edge-recovery/WP-EDGE-09/RESEARCH_SUITE.md` | 939 | `f53212761c3b0def…` |
| `reports/edge-recovery/WP-EDGE-09/RESULTS_MATRIX.json` | 6245 | `7949662ade411577…` |
| `reports/edge-recovery/WP-EDGE-09/RESULTS_MATRIX.md` | 2886 | `934db7c017cf319d…` |
| `reports/edge-recovery/WP-EDGE-09/VERIFICATION.json` | 7011 | `c1627eab80a5355b…` |
| `reports/edge-recovery/WP-EDGE-09/WINDOW_LEDGER.jsonl` | 7647 | `14188eaa892cfe6f…` |
| `reports/edge-recovery/WP-EDGE-09/audit/ESTATE.json` | 18391 | `f9a8356301386d21…` |
| `reports/edge-recovery/WP-EDGE-09/experiments/EXPERIMENTS.json` | 112659 | `bde376e5139b651b…` |
| `reports/edge-recovery/WP-EDGE-09/experiments/EXPERIMENT_REGISTRY.json` | 6625 | `52aebe35ad050939…` |
| `reports/edge-recovery/WP-EDGE-09/gates/COST_LIQUIDITY_CAPACITY.json` | 334011 | `a48e106e16b2346a…` |
| `reports/edge-recovery/WP-EDGE-09/panel/PANEL_SECONDS.csv` | 16729291 | `0f87b7baeb92f93d…` |
| `reports/edge-recovery/WP-EDGE-09/sources/SOURCE_VIABILITY.json` | 1827073 | `1292803907623c0a…` |

The files this script writes are excluded from the digest table by name: hashing a report before rewriting it produces a table that describes a version of itself that no longer exists.

## 5. Git

- Branch `agent/edge-recovery/WP-EDGE-00-baseline`, head `d5c93bd9f7246122792694cbfb86537637c00612`, remote `refs/heads/agent/edge-recovery/WP-EDGE-00-baseline`.
- Pushed range at the last push: `d5c93bd..d5c93bd (+0 ahead, 0 behind)`; remote tip read back: `d5c93bd9f7246122792694cbfb86537637c00612`; matches head: `True`; force push used: `False`.
- Package files still uncommitted at this reading: [' M scripts/edge09_report.py'].

## 6. What this run does not establish

- profitability of any book: promotion is NONE and no order is sent
- anything about liquidity outside the 4.16 h the forward capture covers
- anything about the perp trade flow: this environment delivered zero perp aggTrade messages (SRC-15/SRC-18) and the absence is declared, never substituted
- anything about realised maker fills: no venue in this project has a measured fill model
- anything about markets the runtime excludes (derivatives are information, not product)
- the capture spans hours across a handful of days, so a rate per day is an extrapolation from a short sample and is reported with its span
- no venue in this project has a measured maker fill model, so a passive product cannot be scored here at all

`promotion: NONE`, `order_sent: False`.
