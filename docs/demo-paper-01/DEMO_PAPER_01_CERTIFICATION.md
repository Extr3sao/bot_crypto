# DEMO-PAPER-01 — CERTIFICATION RECORD (ROUND 2)

```text
CERTIFICATION_ID: CERT-DEMO-PAPER-01
VALIDATED_IMPLEMENTATION_COMMIT: 1dfeea8b2c5e3272af9f7dc501ca5f43873eda82
BASE_COMMIT: a38e11eb7f894df2df27630a3ab7673b40a82f0a
CERTIFIED_ON: 2026-09-06 (round 2, full re-verification)
CERTIFICATION_CHECKOUTS:
  .worktrees/cert-dp01-r2         (detached @ 1dfeea8, primary evidence)
  .worktrees/cert-dp01-r2-second  (detached @ 1dfeea8, reproducibility re-run)
ENVIRONMENT: uv sync --frozen; HEAD exact; worktree clean (0 changes); trading_bot resolves from checkout
```

Round 2 supersedes the round-1 record. No PASS was inherited: every gate was
re-run fresh from a new detached checkout of exactly `1dfeea8`. The validated
implementation was not modified during certification (this record and evidence
artifacts are the only changes, committed separately).

## Process finding (recorded, does not block certification)

Round-1 history shows commit `e5dda05` (timestamped 2026-09-06 00:00) modified
`src/trading_bot/demo/paper_multi_agent.py` (+61/−8: dashboard HTML render,
browser auto-open, console UX) *between* the validated implementation commit
and the round-1 record commit `fa1db04`. Round 2 therefore re-certified the
exact `1dfeea8` tree, and the diff was reviewed: it touches only dashboard
presentation and CLI; the adapter, verifier, risk, broker, PnL, and PIT paths
are unchanged between `1dfeea8` and `e5dda05`. Process rule going forward:
implementation freeze means implementation freeze.

## GATE_0 — fresh clean checkout (both checkouts)

| Item | Result |
|---|---|
| HEAD exact @ 1dfeea8 | PASS (both worktrees) |
| Working tree clean | PASS (0 changes, both) |
| uv sync --frozen | PASS |
| trading_bot resolves from checkout | PASS (editable .pth → own src only) |
| External worktree dependencies | 0 (demo import closure: 31 modules, all inside checkout) |

## DP01 gates — fresh evidence table

Evidence sources: probe suite `reports/cert-probes/evidence.json` (fixture,
adapter, dashboard, PIT probes), `reports/cert-probes/public_summary.json`
(public smoke), both fresh RUN_REPORTs, validator output, test-suite output.

| Gate | Result | Fresh evidence (round 2) |
|---|---|---|
| DP01-01 Runtime authority | PASS | Static AST audit of demo module: imports only certified MA-2/3/4 (swarm, opportunity, debate, decision), RiskManager, PaperBroker, CandidatePortfolio; zero parallel risk/broker/accounting classes; zero demo-owned PnL-computing functions; verifier-v3 dependency present |
| DP01-02 Decision→Candidate adapter | PASS | Fresh probe: SELECTED+VERIFIED → `AdaptedCandidate.candidate` is the canonical `TradeCandidate`; no sizing fields on candidate |
| DP01-03 VERIFIED-only boundary | PASS | Fresh negative probes, all emit `None`: NO_TRADE outcome, foreign-run package, tampered (stripped) selected evidence, missing terminal proposal, candidate with `trace=None` |
| DP01-04 NO_TRADE side effects = 0 | PASS | Fresh fixture run: `no_trade=2`, `risk_calls=2` (only the 2 SELECTED cycles), `broker_calls=1` == `paper_trades=1`; NO_TRADE visible in decisions, events (`decision.no_trade`), funnel, and dashboard payload |
| DP01-05 REJECTED side effects = 0 | PASS | Fresh fixture: risk reject at cycle 4 leaves `broker_calls == paper_trades`; adapter negative probes produce zero risk/broker calls (no portfolio admission) |
| DP01-06 CandidatePortfolio reuse | PASS | Fresh probe: adapter output admitted via `build_portfolio` → `CandidatePortfolio` (canonical type, 1/1 admitted) |
| DP01-07 RiskManager authority | PASS | Fresh probes: no size/leverage/risk fields on adapter or candidate; SELECTED→Risk REJECT (`blocked_by=max_positions`) → broker calls 0; SELECTED→Risk ACCEPT → notional 1000 USDT + SL/TP from `RiskCheck.position_size` → PaperBroker PAPER fill |
| DP01-08 PaperBroker-only execution | PASS | AST audit of `paper/broker.py`: zero network markers (ccxt/requests/socket/urllib/private endpoints); all fills from PaperBroker |
| DP01-09 live/private boundary blocked | PASS | Dynamic block probe: `ccxt.binance`, `requests.Session.send`, `http.client.HTTPConnection.request`, `socket.socket.connect` monkeypatched to raise; full fixture demo then completed on the paper path with REAL_BROKER_CALLS=0, PRIVATE_EXCHANGE_CALLS=0, LIVE_CALLS=0, paper_trades=1, realized=242.82705154. Safety gates also fail-closed (`DemoSafetyError` on non-paper config) |
| DP01-10 Canonical reconciliation | PASS | Fresh fixture: close via `broker.check_positions` → `risk.record_trade_result`; `closed_trades=1`; reconciliation-driven close events present |
| DP01-11 Canonical PnL | PASS | Fresh open→close lifecycle: realized 242.82705154 = sum of PaperBroker closed-trade pnl (`gross 243.827 − fees 1.0`); report rounds to 8dp; adapter/dashboard/MA layer compute no PnL |
| DP01-12 Single run / trace authority | PASS | Fresh fixture: all events + all decision packages share exactly `run_id=demo-paper-01-fixture`, `trace_id=trace-demo-paper-01-fixture` — no cross-run contamination |
| DP01-13 Temporal / PIT authority | PASS | Fresh negative probes fail-closed: stale context (`AssetContextError: stale ... (N5)`), future PIT window (`point-in-time violation`), cross-run artifact at construction (pydantic `ValidationError: trace.run_id must match evidence.run_id`) and at bus (`TraceMismatchError: evidence run does not match bus run`); future/stale proposal at verifier → adapter `None`. Plus committed `test_temporal_authority.py` 14/14 |
| DP01-14 Deterministic fixture demo | PASS | Fresh fixture run 3× (primary checkout) + 2× (second checkout) → byte-identical `RUN_REPORT.json` |
| DP01-15 Real public-market paper smoke | PASS | ccxt public Binance OHLCV, BTC/ETH/SOL: scans=3, proposals=3, debates=3, selected=3, NO_TRADE=0, riskA=1, riskR=2, paper_trades=1, closed=0, realized=0.0, unrealized=0.0, errors=0, live/private/real-broker=0, false_success=0 |
| DP01-16 DecisionTrace | PASS | Fresh fixture: success chain `decision.verified → paper.position_opened → paper.position_closed` (net 242.827) and reject chain `risk.rejected (blocked_by=max_positions)` both reconstructable from events + persisted package/debate artifacts |
| DP01-17 RUN_REPORT md/json | PASS | Fresh probe: all md funnel keys match json payload exactly (0 mismatches); `false_success=0` |
| DP01-18 Dashboard read-only | PASS | Fresh probes: `GET /`=200, `GET /api/status`=200; POST `/`, `/api/status`, `/api/order`, `/api/risk` → all 405; `GET /api/order` → 404; EXECUTION_CONTROL_ENDPOINTS=0, RISK_OVERRIDE_ENDPOINTS=0 |
| DP01-19 Opportunity funnel visible | PASS | Via committed dashboard `/api/status`: scans/evaluations/proposals/debates/selected/NO_TRADE/risk accepts+rejects/paper trades + per-cycle `funnel[]` (3 entries with proposal ids + debate outcomes) |
| DP01-20 Debate visible | PASS | Debate artifact in decisions payload: 12 critiques with stance, counter-evidence, revisions, `termination_reason`, outcome (UNRESOLVED/REVISED/SUPPORTED) |
| DP01-21 Decisions visible | PASS | `decisions[]` carries outcome (NO_TRADE/SELECTED), reasons (package.decision_reasons), rejected alternatives (present), verifier verdict per decision |
| DP01-22 Risk visible | PASS | `risk.rejected` event with `reason="Max open positions reached (1)"`, `blocked_by=max_positions`; accepts counter present |
| DP01-23 Positions/trades/PnL visible | PASS | Open positions, closed trades, realized 242.82705154, unrealized fields; `paper.position_opened/closed` events with prices and pnl |
| DP01-24 Frequency KPI observational | PASS | KPI exists only in read-only `to_dict` (`trades_per_day`, `days_ge_3_trades`); AST sweep of RiskManager: zero threshold-lowering lines; no runtime path lowers thresholds on low frequency |
| DP01-25 Independent validator | PASS | 17/17 PASS fresh in both checkouts (validator unchanged at `1dfeea8` — `git status` clean, file hash from committed tree) |
| DP01-26 Reproducibility (second checkout) | PASS | Second detached checkout: HEAD exact, clean, uv sync --frozen, 233 demo/multi-agent/paper tests PASS, fixture E2E deterministic ×2, dashboard smoke 200/200, validator 17/17, ruff+mypy demo scope clean, FULL REGRESSION 766/766 |
| DP01-27 FALSE_SUCCESS = 0 | PASS | `false_success=0` in fixture, public smoke, and bounded post-dashboard-kill run; fixture labelled `DEMO_FIXTURE` (dataset_id) and never mixed with public PnL; verifier + RiskManager never skipped in any observed path |

**DP01_GATES = 27/27 PASS**

Resolution of the historical "26/27": superseded by this fresh per-gate
verification — all 27 gates independently PASS at `1dfeea8`.

## Fixture E2E — exact recorded branches (DEMO_FIXTURE, not performance evidence)

```text
cycle 1 BTC (flat, no directions): NO_TRADE — verifier VERIFIED, zero risk/broker calls
cycle 2 SOL (flat, LONG+SHORT): debate UNRESOLVED → NO_TRADE
cycle 3 SOL (down, LONG): debate REVISED → SELECTED → VERIFIED → Risk ACCEPT → paper OPEN
cycle 4 BTC (up, LONG): SELECTED → VERIFIED → Risk REJECT (max_open_positions=1) → broker_calls unchanged
close: SOL take_profit → reconciliation → net realized PnL = 242.82705154 (DEMO_FIXTURE)
no_trade=2, debates=3 (incl. cycle-1), risk_calls=2, broker_calls=1, paper_trades=1, closed_trades=1, false_success=0
```

## Public market paper smoke (separate from fixture)

```text
provider: ccxt-public-binance (public OHLCV only, no credentials)
assets: BTC, ETH, SOL
PUBLIC_MARKET_SCANS=3, PUBLIC_PROPOSALS=3, PUBLIC_DEBATES=3, PUBLIC_SELECTED=3
PUBLIC_NO_TRADE=0, PUBLIC_RISK_ACCEPTS=1, PUBLIC_RISK_REJECTS=2
PUBLIC_PAPER_TRADES=1, PUBLIC_REALIZED_PNL=0.0, PUBLIC_UNREALIZED_PNL=0.0
errors=0; live/private/real-broker calls=0; false_success=0
Fixture PnL (242.83, DEMO_FIXTURE) and public PnL (0.0) recorded separately; never mixed.
Zero public trades is an accepted valid outcome; no signal was forced.
```

## Regression and hygiene (fresh, both checkouts)

```text
demo tests (unit+integration): 9 passed
demo+multi_agent+paper+paper-e2e subsets (second checkout): 233 passed
FULL_REGRESSION: 766 passed, 0 failed, 78 warnings (primary 5m33s; second checkout 3m52s)
  Note: with host env override EXCHANGE_ID=bybit present, one pre-existing
  environment-dependent failure appears
  (tests/unit/config/test_settings.py::test_load_settings_happy_path expects
  default 'binance'). Classified: unrelated to the demo commit (touches no
  config files); passes 26/26 with the override unset. No hidden failures.
RUFF demo-owned files: 0 findings (both checkouts)
MYPY demo-owned files: 0 errors (both checkouts)
Whole-repo baseline debt: ruff 190 findings / mypy 40 errors in 33 files —
  zero overlap with demo-owned files → DEMO_RUFF_DELTA = 0, DEMO_MYPY_DELTA = 0
REAL_BROKER_CALLS = 0, PRIVATE_EXCHANGE_CALLS = 0, LIVE_CALLS = 0
FALSE_SUCCESS = 0
```

## STATUS

```text
DEMO_PAPER_01_CERTIFIED
NEXT_PHASE: PAPER_OBSERVATION_CAMPAIGN_01
```

Stop after certification: MA-5 not started, LIVE not enabled, no strategy or
risk threshold changed, no trade forced.
