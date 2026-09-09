# FINAL REPORT — ALPHA-DISCOVERY-AND-SHADOW-V2-01

CHECKPOINT: ALPHA-DISCOVERY-AND-SHADOW-V2-01
BASE: f155a69 (+ POC01 evidence lineage)
DATE: 2026-09-09 (UTC)

## POC01

| Field | Value |
| --- | --- |
| POC01_STATUS | ACTIVE / RESUMED (not restarted this checkpoint) |
| POC01_CLASSIFICATION | **DEGRADED_OBSERVATIONAL_CAMPAIGN** (coverage 0.717 best day; 15.25h outage) — not usable for production-ready/profitability/frequency certification |
| POC01_COMPLETED_VALID_DAYS | 1 (2026-09-08, zero-trade VALID day) |
| POC01_DAYS_GE_3 | 0 · PERCENT_DAYS_GE_3 = 0.0 |
| PRIMARY_FUNNEL_LOSS | **NO_SIGNAL** (both observed days collapse at the PROPOSAL gate; SIGNAL/VERIFIED gates NOT_RECORDED by runtime — reported, not inferred) |
| PRIMARY_RISK_REASON | none recorded (0 risk evaluations to date) |

Daily canonical evidence (A1): 09-06 BURN_IN(excluded) · 09-07 NOT_OBSERVED · 09-08 FINALIZED/VALID/coverage 0.717 (scans 1, proposals 0, funnel loss NO_SIGNAL) · 09-09 PARTIAL (same shape). No zero-trade day removed from any denominator.

## Legacy diagnosis (LG-01/LG-02 — analysis only, no rerun/retune)

Source: `LEGACY_RETRO_EXECUTION_RESULTS.json` (fingerprint `d2f17f91…`). Output: `LEGACY_FAILURE_DIAGNOSIS.json`.

- LEGACY_VALIDATED = 0 · LEGACY_FAILED = 14 · LEGACY_INSUFFICIENT = 16
- All 14 failed cells fail **significance** (permutation p ≥ 0.05); 9 also negative net expectancy; 5 also PF < 1; 7 have Sharpe CI entirely below 0.
- Uniform cost drag 0.0012/trade (0.0004 commission + 2bps slippage × both sides) — 5m cells die primarily on costs, 1h cells on sign/instability.
- 16 INSUFFICIENT cells: binding constraint is preregistered n ≥ 15.
- Classification standstill: momentum/breakout/mean_reversion FAIL · trend/volatility INSUFFICIENT_EVIDENCE (unchanged; no POC01 authority change).

## Discovery Batch 01 (DS-01..DS-10)

Preregistration: frozen manifest sha256 `e8d5aa62…` verified byte-identical to creation commit `f155a69` BEFORE execution; six eval specs fingerprinted in `DISCOVERY_EVAL_SPECS`; harness = frozen LegacyRetroHarness (identical gates — **no per-track lowering**). Data: real public binanceusdm PIT OHLCV + funding history.

| Candidate | Result |
| --- | --- |
| carry_funding | **INSUFFICIENT_SAMPLE (n=0)** — funding-window unit ambiguity in the spec produced 0 qualifying signals. Registered **DEF-DISCOVERY-001**; repair requires a NEW fingerprinted batch, no post-hoc retune |
| cross_sectional | NOT_APPLICABLE-level n=11 → below minimum (1h cell PF 1.616 recorded as lead, not pass) |
| session_time | INSUFFICIENT vs minimum (n=12–82; consistently negative net expectancy — costs dominate) |
| liquidity_flow | below minimum (n=11–13, negative) |
| volatility_structure | below minimum (n=8–11); BTC 1h PF 2.526, ETH 1h PF 3.042 recorded as leads, NOT passes |
| regime_transition_defense | below minimum (n=3–9, negative) |

- DISCOVERY_PASSERS: **0** · DISCOVERY_FAILURES: 0 (no cell reached gateable n) · INSUFFICIENT_SAMPLE: 8 · NOT_APPLICABLE/below-min: 24
- INCREMENTAL_OPPORTUNITIES_PER_DAY (C6, natural frequency, NOT tuned): session_time 6.71 · liquidity_flow 1.71 · volatility_structure 1.36 · regime_transition_defense 0.88 · cross_sectional 0.52 · carry_funding 0.00
- PAPER_PROMOTIONS: **0** — all results persisted to `DISCOVERY_BATCH_01_RESULTS.json` including failures.

## Shadow Campaign V2 (SH-01..SH-04)

- `RiskGateRouter`: single decision routing point — ACCEPT → PAPER (runtime unchanged), REJECT → immutable `ShadowCandidateCapture` → PIT resolution → `ShadowTrade`. Router itself performs zero PaperBroker/portfolio/Risk calls.
- `ConditionedShadowMetrics`: per-reason counterfactuals conditioned by strategy × asset × timeframe × regime × health (wins/losses/expectancy/PF/DD/R-multiples).
- `ShadowCounters`: read-only projection (captures/resolved/pending/by-reason, `paper_contamination: 0`).
- SHADOW_PAPERBROKER_CALLS = 0 · SHADOW_RISK_MUTATIONS = 0 · SHADOW_ACCOUNTING_CONTAMINATION = 0 (structural + AST-checked import surface).
- Integration into the running campaign: NEXT campaign only (POC02 manifest below) — POC01 untouched.

## POC02 preregistration (P2-01..P2-05)

`POC02_MANIFEST.md` — PREREGISTERED, **NOT LAUNCHED** (awaiting governance authorization).
- POC02_MARKET_DATA_PROVIDER: `binanceusdm` (public) — EXECUTION_MODE `PAPER` — EXECUTION_VENUE_MODEL `PaperBroker` (three fields must be displayed separately by any UI)
- POC02_COVERAGE_CONTRACT: ≥ 0.80 observed/expected minutes per counted day, declared ex ante; validity semantics unchanged from canonical contract; DEF-POC01-OBS-006 metrics reused
- Shadow enabled: `RiskGateRouter` wired at Risk-REJECT; PAPER decisions unchanged

## Confirmation lock (Track F)

`CONF-EDGE-002-001`: window 2026-09-08→2026-09-22, **consumed = false**, **CONFIRMATION_EXECUTIONS = 0**; manifest verified immutable (exists only in committed evidence tree at `39578a6` + `bb46c92`; no mutable worktree copy).

## Track G

`discovery_view.py`: read-only RESEARCH (discovery lab + legacy matrix), SHADOW (counters) and PAPER (coverage rows) surfaces; empty evidence renders INSUFFICIENT_EVIDENCE/NOT_OBSERVED; no controls.

## GOV + regression

| Field | Value |
| --- | --- |
| POC01_RUNTIME_CHANGED | 0 |
| POC01_TRADING_BEHAVIOR_CHANGED | 0 |
| LIVE_CALLS | 0 |
| FALSE_SUCCESS | 0 |
| NEW_TESTS (this checkpoint) | **4 files / 36 functions / 36 collected** (funnel 7, discovery-exec 14, view 6, router 9) |
| FULL_REGRESSION (hermetic, exit 0) | **collected=1052, passed=1052, failed=0, skipped=0, xfailed=0, errors=0** |
| Scope reconciliation | tests/unit=1000 (964 base + 36 new, matching all prior checkpoint counts exactly) + tests/bdd=23 + tests/integration=29. Prior hermetic reports (837→964) were unit-scope; this is the first full-`tests/` run — recorded, not silently corrected |
| Ruff / Mypy (checkpoint files) | CLEAN / CLEAN |
| Dependency closure | PASS (closure guard green after staging all new modules) |

STATUS: **PASS**

NEXT:
- CONTINUE_POC01_TO_END (observation only; classification stands)
- REVIEW_DISCOVERY_PASSERS — none this batch; DEF-DISCOVERY-001 repair batch + volatility_structure/cross_sectional leads require deeper-window preregistered batches
- PREPARE_POC02_LAUNCH (manifest frozen; awaiting authorization)
- CONFIRMATION_WAIT (2026-09-22)
