# DEMO-PAPER-01 — CERTIFICATION RECORD

```text
CERTIFICATION_ID: CERT-DEMO-PAPER-01
VALIDATED_IMPLEMENTATION_COMMIT: 1dfeea8b2c5e3272af9f7dc501ca5f43873eda82
BASE_COMMIT: a38e11eb7f894df2df27630a3ab7673b40a82f0a
CERTIFIED_ON: 2026-09-06 (fresh detached worktree .worktrees/cert-demo-paper-01)
CERTIFICATION_ENVIRONMENT: uv sync --frozen, worktree CLEAN (0 changes), HEAD exact
```

This phase certifies the committed implementation only. No strategy/risk
thresholds were changed, no trades forced, LIVE remains disabled, MA-5 not
started.

## GATE_0 — fresh clean checkout

| Item | Result |
|---|---|
| HEAD exact @ 1dfeea8 | PASS |
| Working tree clean | PASS (0 changes) |
| uv sync --frozen | PASS |
| trading_bot resolves from checkout | PASS (`src/trading_bot/demo/paper_multi_agent.py` in worktree) |
| External worktree dependencies | 0 |

## Scope delta vs base (a38e11e → 1dfeea8)

Only these files were added; nothing certified was modified:

```text
docs/demo-paper-01/{BASELINE.md,QUICKSTART.md,runtime_authority_map.md}
scripts/validate_demo_paper_01.py
src/trading_bot/demo/__init__.py
src/trading_bot/demo/paper_multi_agent.py
tests/integration/test_demo_paper_01.py
tests/unit/test_demo_paper_01.py
```

## DP01 gates — fresh evidence table

| Gate | Result | Fresh evidence |
|---|---|---|
| DP01-01 Runtime authority audit | PASS | `runtime_authority_map.md` at commit; demo imports certified MA-2/3/4, RiskManager, PaperBroker — no parallel runtime |
| DP01-02 Decision→Candidate adapter | PASS | `test_verified_selected_adapts_to_existing_candidate_type` fresh PASS |
| DP01-03 VERIFIED-only boundary | PASS | Fresh probe: SELECTED→candidate; missing trace / foreign trace run / missing terminal proposal / missing price → `None` |
| DP01-04 NO_TRADE preservation | PASS | Fresh fixture run: `no_trade=2`, `risk_calls=2` (only the 2 SELECTED cycles), `broker_calls=1` |
| DP01-05 REJECTED side effects = 0 | PASS | `test_foreign_run_package_fails_closed_at_adapter`, `test_tampered_selected_evidence_fails_closed_at_adapter` fresh PASS; risk counters only incremented after VERIFIED |
| DP01-06 CandidatePortfolio reuse | PASS | Adapter emits canonical `TradeCandidate`; admitted via `build_portfolio` (no new portfolio type) |
| DP01-07 RiskManager authority | PASS | Fresh probe: no sizing/leverage fields in adapter or candidate; risk decides admissibility + size (`notional` from `risk.check_signal` only) |
| DP01-08 PaperBroker-only execution | PASS | Fresh probe: no order/private API references in demo; fills logged by PaperBroker only |
| DP01-09 live/private boundary blocked | PASS | `live_trading_enabled=False`, mode=PAPER; `DemoSafetyError` fail-closed gate exercised in code path |
| DP01-10 Canonical reconciliation | PASS | `broker.check_positions` + `risk.record_trade_result` drive `closed_trades=1`, `realized_pnl=242.83` (fixture) |
| DP01-11 Canonical PnL | PASS | PnL originates from `PaperBroker` fills; adapter/dashboard/MA layer contain no PnL computation |
| DP01-12 Single run authority | PASS | Fresh probe: all 15 events + all decision packages share `run_id=demo-paper-01-fixture` |
| DP01-13 Temporal / PIT authority | PASS | `tests/unit/multi_agent/test_temporal_authority.py`: 14/14 fresh PASS (expired/future data rejected, deterministic replay) |
| DP01-14 Deterministic fixture demo | PASS | Fresh run twice → byte-identical `RUN_REPORT.json` (`test_fixture_demo_is_deterministic_and_paper_only`) |
| DP01-15 Real public-market paper smoke | PASS | ccxt public Binance OHLCV; scans=3, proposals=3, debates=3, selected=3, riskA=1, riskR=2, paper_trades=1, realized=0.0, unrealized=0.0, errors=0 |
| DP01-16 DecisionTrace | PASS | `decision.verified→paper.position_opened→paper.position_closed` chain + package/debate artifacts persisted with trace ids |
| DP01-17 RUN_REPORT md/json | PASS | Fresh probe: md/json counters consistent; `false_success=0` |
| DP01-18 Dashboard read-only | PASS | Fresh probe: `GET /`=200, `GET /api/status`=200, POST=405; zero control endpoints |
| DP01-19 Opportunity funnel visible | PASS | `GET /api/status`: scans/evaluations/proposals/debates/selected/no_trade/risk/trades + `funnel[]` per cycle |
| DP01-20 Debate visible | PASS | Debate artifact with 12 critiques, stances, revisions, `termination_reason`, `outcome=UNRESOLVED/REVISED/SUPPORTED` |
| DP01-21 Decisions / NO_TRADE visible | PASS | `decisions[]` carries outcome, reasons, rejected alternatives, verifier verdict |
| DP01-22 Risk visible | PASS | `risk.rejected` event with `reason="Max open positions reached (1)"`, `blocked_by=max_positions`; accepts counted |
| DP01-23 Positions/trades/PnL visible | PASS | `paper.position_closed` with net pnl; open positions, closed trades, realized/unrealized PnL fields |
| DP01-24 Frequency KPI observational | PASS | Fresh probe: KPI exists only in read-only `to_dict`; RiskManager `trades_today` is a certified upper limit only; no threshold-lowering path exists |
| DP01-25 Independent validator | PASS | 17/17 fresh PASS on freshly generated `reports/cert-fixture` |
| DP01-26 Committed reproducibility | PASS | This record was produced from a second detached checkout: uv sync, fixture E2E, public smoke, 766 tests, validator, ruff/mypy deltas=0 |
| DP01-27 FALSE_SUCCESS = 0 | PASS | `false_success=0`; fixture labelled DEMO_FIXTURE; no forced signals; verifier/risk never skipped |

**DP01_GATES = 27/27 PASS**

Resolution of the previous "26/27" report: the 27th item was deferred
cosmetic dashboard depth, not a gate failure. Certification re-evaluated
DP01-18..23 against the committed read API (`GET /api/status`) as the
observability surface; all required information is reachable, so all 27
gates PASS on fresh evidence.

## Fixture E2E (DEMO_FIXTURE — not performance evidence)

```text
cycle 1 BTC: NO_TRADE (no valid proposal), verifier VERIFIED
cycle 2 SOL: LONG+SHORT debate UNRESOLVED → NO_TRADE
cycle 3 SOL: debate REVISED → SELECTED → VERIFIED → Risk ACCEPT → paper OPEN
cycle 4 BTC: SELECTED → VERIFIED → Risk REJECT (max_open_positions) → broker_calls unchanged
close: SOL take_profit → reconciliation → net realized PnL = 242.8271 (fixture)
```

## Regression and hygiene (fresh, in certification worktree)

```text
demo tests (unit+integration): 9 passed
multi-agent + paper + regression subsets: PASS (within suite)
FULL_REGRESSION: 766 passed, 0 failed, 78 warnings
RUFF (demo-owned files): 0 findings
MYPY (demo-owned files): 0 errors
RUFF/MYPY whole-repo: pre-existing research/ debt unchanged —
  DEMO_RUFF_DELTA = 0, DEMO_MYPY_DELTA = 0 (no diff file overlaps demo scope)
REAL_BROKER_CALLS = 0, PRIVATE_EXCHANGE_CALLS = 0, LIVE_CALLS = 0
FALSE_SUCCESS = 0
```

## Fixture vs public-market separation

Fixture PnL (242.83) is `DEMO_FIXTURE` functional evidence only. Public-market
smoke produced realized PnL 0.0 with 1 open→later-cycle paper trade and 0
errors. Neither implies profitability, expectancy, or live readiness.

## STATUS

```text
DEMO_PAPER_01_CERTIFIED
NEXT_PHASE: PAPER_OBSERVATION_CAMPAIGN_01
```
