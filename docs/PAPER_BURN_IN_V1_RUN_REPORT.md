# PAPER-BURN-IN-V1 — RUN REPORT

Status: **BURN_IN_V1_PASS_WITH_ONE_FIXED_P1** (exit criteria met; the single P1 was found, fixed, regression-tested, and re-validated)
Commits: baseline `cfadc73` · instrumentation `0d0b76e` · DEF-101 fix `d370638`
Evidence dir: `reports/paper-burn-in/PAPER-BURN-IN-V1/` (gitignored raw logs; docs + metrics committed)

## Configuration

- Provider: Binance **testnet** spot (read-only, no credentials, no order API) via `config/realdata` (paper, sandbox, CL-4 no-fallback).
- Assets: BTC, ETH, SOL · timeframe 5m · PaperBroker balance 10000 USDT.
- Runtime: canonical `scripts/start_paper_trading.py` with durable state (`--state-path`), StartupReconcilerV4, burn-in JSONL events (`--burnin-events`).
- Baseline gates at `cfadc73`: 607 tests passed, mypy 0/238, ruff clean.

## Execution stages (all real market data)

| Stage | Cycles | Errors | Notes |
| --- | --- | --- | --- |
| STAGE 1 (~4 min) | 45 | 0 | all HEALTHY; 3 orders opened; then risk vetoes dominate |
| Restart test (§21) | 10 | 0 | `RECOVERED`; 0 post-restart orders; exposure veto intact |
| STAGE 2 (~36 min) | 365 | 0 | 4 process segments (shell tool timeout kills — orchestrator stopped cleanly each time, 0 tracebacks; each restart `RECOVERED`) |
| Post-fix validation | 55 | 0 | fresh book after DEF-101 fix; CONSISTENT → RECOVERED |
| **TOTAL** | **475** | **0** | ~57 min uptime; **0 FAILED cycles; 0 temporal-integrity violations; 0 duplicated economic effects; 0 corrupted state** |

Note (honest accounting): STAGE 2 was requested as a continuous 30–60 min run. The shell tool's 600 s limit killed the PROCESS four times; because the durable-state design persists per session, every restart reconciled (`RECOVERED`) and continued without human intervention — which is itself the operational recovery property this phase tests, but the runtime was NOT one continuous process. Documented, not inflated.

## DEFECTS

### DEF-101 (P1 — FOUND BY THE BURN-IN, FIXED)

- **Symptom**: `risk_state.trades_today=278`, `daily_pnl=+980.46` with only 4 real fills; `764` intents vetoed by `Daily trade limit reached (20)`; risk-side equity drift vs broker equity.
- **Reproduction**: any multi-session run with ≥1 closed trade (observed live in STAGE 2; deterministically reproduced in test).
- **Root cause**: `PaperBroker.reconcile_session()` returned the **full** `closed_trades` ledger every session; `PaperSessionRunner._record_closed_trades_in_risk()` re-fed the whole ledger into `RiskManager.record_trade_result()` each session → cumulative double-counting.
- **Fix** (`d370638`): `PaperExecutionSummary.new_closed_trades` = delta since previous reconcile (report cursor; restored ledgers pre-marked as already-reported after restart); the runner forwards only the delta.
- **Regression test**: `test_reconcile_session_feeds_only_delta_to_risk` — 5 repeated reconciles leave `trades_today==1`.
- **Re-run**: 55 fresh cycles → `trades_today=3` == 3 real fills; cooldown (3 consecutive losses) engaged legitimately; restart → `RECOVERED`, no re-feed, 0 re-executions.
- **Classification**: P1 (incorrect risk accounting; would have blocked all trading after 20 reported trades and corrupted any risk-based analysis). P0 checklist run: no execution corruption, no bypass, no look-ahead, no state corruption.

- DEF-100 (P2, instrument-time, fixed pre-burn-in in `0d0b76e`): local `UnboundLocalError` while wiring the burn-in hook — caught by existing tests before commit, never ran in a live cycle.
- Open P0/P1/P2 from burn-in: **none**. P3 deferred: per-stage latency breakdown, CPU/memory sampling.

## Strategy behavior observation (§14 — observe only, no tuning)

- Router+cycle selected across the map; the binding behavior is risk-side: with `max_trades_per_day=20`, `max_open_positions=3` and 3 one-position-per-asset entries, the system enters a steady state of **NO_TRADE by risk policy** (`Max open positions (3)`, then `Daily trade limit (20)` after DEF-101 double-count) and **idempotent duplicate suppression** of the same bar-intents (98 in STAGE 1-2).
- Post-fix: `Consecutive loss cooldown (3 losses)` engaged after 3 legitimate SL losses — risk acting as designed; also shows the current families trade frequently when not capped (3 fills in 45 cycles ≈ 4 fills/h across 3 assets).
- `broker_returned_no_fill` ×2 in STAGE 1-2 (same-side duplicate at broker) — consistent with engine duplicate layer, observable, zero economic effect.
- **INSUFFICIENT_SAMPLE** on everything economic: 4 closed trades total.

## Risk observation (§18)

- Veto totals: 1156 STAGE-1/2 + 70 post-fix. Top: `Daily trade limit (20)` (pre-fix artifact), `Max open positions (3)`, `Consecutive loss cooldown (3)`.
- Risk blocked correctly (each veto reason verified against policy) — but pre-fix it was blocking on CORRUPTED counters; post-fix counters match reality. No risk rule was relaxed.

## Latency & resources (§19-20)

- Full-cycle latency: median ≈ 3.9 s, max 7.1 s (market-data bound; acceptable for 5m cadence — no optimization).
- State file bounded: 1181→1509 bytes over 475 cycles (closed-trade rows grow slowly; no leak). Logs grow linearly (expected; retention policy exists).

## Exit criteria (§28)

Runtime real ✓ · real market data ✓ · PaperBroker ✓ · state persistence ✓ · startup reconciliation ✓ · stage 1+2 completed (≥ requested stage 1, stage 2 completed in segments) ✓ · **0 unresolved P0/P1** ✓ · no temporal violations ✓ · no duplicated economic effects ✓ · no corrupted state ✓ · restart recovery successful ✓ · metrics captured ✓ · evidence generated ✓ → **PASS (with the P1 fixed mid-phase, per defect-loop protocol)**.

## Next recommended run (§29)

`STRATEGY-BEHAVIOR-AUDIT-V1` first (the system's natural behavior under current policy is cap-dominated; understand NO_TRADE composition and the 1-trade/asset-per-bar signal pattern before longer windows), then `PAPER-BURN-IN-V2` (12h) with the process supervised outside the shell-tool timeout (e.g. detached scheduler or terminal multiplexer).
