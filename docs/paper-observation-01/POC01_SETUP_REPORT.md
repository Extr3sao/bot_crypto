# PAPER-OBSERVATION-CAMPAIGN-01 — SETUP REPORT

```text
CHECKPOINT_ID: PAPER-OBSERVATION-CAMPAIGN-01-SETUP
BASE_IMPLEMENTATION: 1dfeea8b2c5e3272af9f7dc501ca5f43873eda82 (DEMO_PAPER_01 CERTIFIED, 27/27)
DEMO_CERTIFICATION_RECORD: a282fcc
IMPLEMENTATION_COMMIT: 11e76cc (branch feat/poc01-setup, worktree .worktrees/poc01-setup)
SECOND_CLEAN_CHECKOUT: .worktrees/poc01-verify (detached @ 11e76cc)
CERTIFIED MODULES UNTOUCHED: demo/multi_agent/risk/broker — verified by git diff vs 1dfeea8
STATUS: POC01_INFRA_READY
NEXT_PHASE: POC01_7DAY_EXECUTION
```

## §0 — Concurrent change audit

PASS — see `CONCURRENT_CHANGE_AUDIT.md` (fingerprints sha256 recorded, 438
lines inventoried, classified 5 ADAPT / 3 REJECT / 1 REPLACE /
1 ALREADY_IMPLEMENTED). The user's original worktree was not modified; all
work happened in a new isolated worktree/branch.

## POC01-01..30 gates

| Gate | Result | Evidence |
|---|---|---|
| POC01-01 certified DEMO-PAPER path reused | PASS | `CampaignRuntime` imports frozen `DecisionEngine`, verifier-v3, certified `DecisionToCandidateAdapter`, `RiskManager`, `PaperBroker`; validator check 01 proves no parallel classes |
| POC01-02 real public market mode | PASS | `provider=ccxt` → `_public_bars` (public Binance OHLCV, no keys); report `data_tag=REAL_PUBLIC_MARKET` |
| POC01-03 PAPER-only boundary | PASS | `_require_paper` safety gate (`CampaignSafetyError`); `live_calls=0`, `real_broker_calls=0`, `private_exchange_calls=0` in all runs |
| POC01-04 durable campaign state | PASS | `poc01-state-v1` full schema (§5 fields) in `CAMPAIGN_STATE.json` |
| POC01-05 atomic persistence | PASS | `CampaignStateStore.save`: temp + `os.replace`; no `.tmp` residue (test_atomic_write_leaves_no_tmp_and_valid_json) |
| POC01-06 safe stop | PASS | SIGINT/SIGTERM handlers + `request_stop`; stop before cycle → `STOPPED`, reports written (test_safe_stop_mid_session); CLI `stop` verified on real campaign |
| POC01-07 safe resume | PASS | identity validation (campaign/assets/strategies/commit/status) + `_rehydrate` recovers RiskManager counters, open positions, equity |
| POC01-08 duplicate prevention | PASS | decision-id + market-fingerprint dedup: same cycle re-run → `DUPLICATE_DECISION_SKIPPED`/`DUPLICATE_MARKET_EVENT_SKIPPED`, zero extra orders (2 tests) |
| POC01-09 campaign/run authority | PASS | campaign_id ⊃ run_id ⊃ trace_id ⊃ decision/trade artifacts; restart-stable identity |
| POC01-10 PIT/freshness authority | PASS | future → `FUTURE_DATA_REJECTED`, stale (ccxt) → `STALE_DATA_NO_TRADE`, zero orders (2 tests); context validated via frozen `AssetContext.validate` |
| POC01-11 DecisionTrace | PASS | every closed trade carries decision_id/strategy/regime/asset; processed decision ids persisted |
| POC01-12 canonical accounting | PASS | equity == initial + realized_pnl (validator check 13); closes only via `PaperBroker.check_positions` → `risk.record_trade_result` |
| POC01-13 daily reporting | PASS | `DAILY_REPORT.{json,md}` per day incl. trades/day, DAY_GE_3, drawdown fields, data-health and error counts |
| POC01-14 campaign reporting | PASS | `CAMPAIGN_REPORT.{json,md}` continuously rewritten per cycle |
| POC01-15 funnel metrics | PASS | all §12 counters bumped from certified-runtime outcomes; persisted in state + reports |
| POC01-16 frequency metrics | PASS | per-day trades/day + DAY_GE_3; campaign VALID_DAYS / DAYS_GE_3 / PERCENT_DAYS_GE_3; note "average≥3 does NOT imply target PASS" |
| POC01-17 asset attribution | PASS | per BTC/ETH/SOL assessments/proposals/selected/risk/trades/wins/losses/net_pnl |
| POC01-18 strategy attribution | PASS | per frozen strategy evaluations/proposals/outcomes via `_TrackedFamilies` (no behavior change) |
| POC01-19 regime attribution | PASS | reuses canonical regime from AssetAssessment; no new regime engine |
| POC01-20 debate utility metrics | PASS | critiques, revisions, resolved/unresolved, counter-evidence, material dissent (§21 set) |
| POC01-21 decision metrics | PASS | candidate count, SELECTED/REJECTED/NO_TRADE, verifier VERIFIED/REJECTED (+natural-rejection defect surfacing) |
| POC01-22 risk metrics | PASS | accepts/rejects, rejection rate, reason distribution, max simultaneous positions, asset exposure; RiskManager untouched |
| POC01-23 dashboard campaign visibility | PASS | read-only `/api/campaign` (campaign header, today, funnel, frequency, attribution, risk reasons); GET 200, POST 405, control endpoints 404 |
| POC01-24 watchdog/health | PASS | heartbeat: last_scan, last decision cycle, provider status, last persistence, last reconciliation; provider failure → `provider_status=STALE` + failure counter, session survives |
| POC01-25 bounded real-market validation | PASS | public campaign run: scans=3 (2 cycles: 3+0-dedup), proposals=1, debates=1, selected=1, NO_TRADE=2, risk rejects=0, paper trades=0, PnL=0.0, errors recorded; state + reports persisted; resume + safe stop exercised via CLI; dashboard reads campaign state |
| POC01-26 independent validator | PASS | **25/25** (`scripts/validate_paper_observation_campaign_01.py`, REPLACE of concurrent stub) |
| POC01-27 clean committed reproducibility | PASS | second detached checkout @ 11e76cc: HEAD exact, clean, uv sync --frozen, 257 scoped tests, validator 25/25, closure guard, ruff+mypy scoped clean, fixture campaign run, FULL REGRESSION 801/801 |
| POC01-28 credentials not consumed | PASS | provider config hardcodes `apiKey=""`/`secret=""` (unit-tested with host-secret env set + stub capture); validator check 22 statically audits the provider source; no secret values in any report |
| POC01-29 real broker/live calls = 0 | PASS | all campaigns + validator checks 23/24 |
| POC01-30 FALSE_SUCCESS = 0 | PASS | `_false_success_audit` invariants (opens≤risk-accepts, risk-accepts≤admitted, realized⇒closed trades); validator check 25 |

## Regression (§40, fresh)

```text
campaign tests:              35 passed (28 unit + 7 integration)
DEMO-PAPER regression:       9 passed (unit + integration) — included in full suite
MA-4 / MA-3 / MA-2 / MA-1:   tests/unit/multi_agent — included in full suite
paper regression:            tests/unit/paper + paper-e2e — included in full suite
dependency closure:          tests/unit/test_dependency_closure_guard.py 3 passed (both checkouts)
independent campaign validator: 25/25 PASS (both checkouts)
Ruff scoped:                 0 findings (paper_observation + poc01 tests + validator)
Mypy scoped:                 0 errors (paper_observation + validator)
FULL_REGRESSION:             801 passed, 0 failed, 78 warnings
                             (766 pre-existing + 35 new; baseline env-dependent
                              EXCHANGE_ID failure excluded per certified
                              classification — passes with override unset)
```

## Second clean checkout (§41)

```text
worktree: .worktrees/poc01-verify, detached @ 11e76cc, tree clean
uv sync --frozen: PASS
dependency closure: PASS
campaign tests + demo + multi-agent + paper subsets: 257 passed
bounded fixture campaign: PASS (2 cycles, deterministic)
resume test: PASS (covered in suite; identity + rehydration)
validator: 25/25 PASS
demo/multi-agent/paper regression: PASS
Ruff scoped: PASS   Mypy scoped: PASS
FULL_REGRESSION: 801 passed, 0 failed
EXTERNAL_WORKTREE_DEPENDENCIES: 0 (editable .pth → own src only)
```

## Operational defect surfaced (§22 — NOT repaired, modules frozen)

`selected_evidence_binding` (verifier-v3) rejects naturally generated
multi-proposal agreement output: with two same-direction proposals
(e.g. momentum+trend both LONG on real BTC data), the MA-4 engine unions
debate-derived supporting evidence into `DecisionCandidate.supporting_evidence_refs`,
while the verifier requires candidate evidence ⊆ terminal-proposal evidence.
The campaign stays **fail-closed** (no candidate, no risk call, no order) and
records `verifier_rejected_natural_output` as an operational defect with the
failed check names. Observed in both fixture and real-public-market bounded
runs. Upstream repair belongs to MA-3/MA-4/verifier owners; POC01 will
measure its frequency (bottleneck analysis already points at it).

## Campaign results are not certification of profitability (§36)

The bounded run produced PnL 0.0 with 0 trades — recorded as observations
only. No claim of PROFITABLE / ALPHA_VALIDATED / LIVE_READY is made or
permitted from this phase.

## Exact commands (§32/§42)

```bash
# START NEW CAMPAIGN (real public market, 7-day observation)
python -m trading_bot.paper_observation.runtime run --provider ccxt --assets BTC,ETH,SOL --campaign-name paper-observation-01

# OPEN DASHBOARD (read-only, alongside the running campaign)
python -m trading_bot.paper_observation.runtime run --provider ccxt --campaign-name paper-observation-01 --dashboard
#   → http://127.0.0.1:8766/api/campaign

# CHECK STATUS
python -m trading_bot.paper_observation.runtime status --provider ccxt

# STOP SAFELY (also: Ctrl+C in the running process)
python -m trading_bot.paper_observation.runtime stop --provider ccxt

# RESUME
python -m trading_bot.paper_observation.runtime resume --provider ccxt --cycles N

# GENERATE REPORT
python -m trading_bot.paper_observation.runtime report --provider ccxt
```

## Boundaries honored

No MA-5 started. LIVE not enabled. No strategy/ranking/debate/decision/verifier/
risk threshold changed. No trades forced. 7-day campaign NOT claimed complete —
`CAMPAIGN_COMPLETE` requires 7 valid complete calendar days (§35).
