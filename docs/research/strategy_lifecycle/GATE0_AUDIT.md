# GATE 0 — Audit, campaign status and defect re-check

Date: 2026-10-01. Repo: `bot freebuff`. Branch `main`. HEAD `929677c8034b72424c33930b59482b44350d7aa7` (unchanged; no commits made by this phase yet).

## 1. Campaign `paper-lab-continuous-03`

**STATUS: STOPPED (not healthy, not active).**

- Last `SYSTEM_HEARTBEAT.json` write: `timestamp_ms 1790812025143` (`≈2026-09-30T23:47Z`), age at audit ≈ 4.9 h.
- Last `MONITOR.jsonl` entry: `2026-09-30T23:41:13Z`, `state HEALTHY`, `uptime_s 20891`.
- `ps`/`tasklist`: **none** of the campaign PIDs (paper 30252, collector 6936, retention 23828, strategy_lab 26020) are alive; only unrelated Python processes remain.
- Cause: the Freebuff environment restarted and the detached supervisor died with it; the children were not re-launched.

**Consequence:** there is no live PAPER campaign to protect, so editing files it
loads (`risk/manager.py`, `autonomous/runtime.py`) is safe. The stoppage is a
pre-existing environment effect, NOT caused by this phase. The 24 h PAPER data
certification clock is therefore reset by an external event, not by this work.

## 2. Defect re-check (independently re-derived)

| Defect | Prior status | Re-checked | Still open? |
|---|---|---|---|
| DEF-RISK-EXPOSURE-001 (P0) | NOT_ENFORCED_RUNTIME_REACHABLE | `max_asset_exposure_pct` referenced only in `config/risk.py`, `market_data/fake.py`, `research/portfolio_backtest.py` | YES → **FIXED this phase** |
| DEF-RISK-INERT-002 (P1) | weekly/daily-dd/cooldown inert | `max_weekly_loss_pct`, `max_daily_drawdown_pct`, `consecutive_loss_cooldown_minutes` have no runtime reader | YES → **FIXED this phase** |
| DEF-PROV-001 (P1) | `strategy_version=str(entry.timeframe)` at `runtime.py:1053` | unchanged | YES → **FIXED this phase** |
| DEF-HTF-PIT-001 (P2) | ORPHAN | importers: `scripts/source_candidate_experiment.py`, `tests/.../test_experimental_candidates_pit.py` only; 0 `src/` callers | YES → **NOT elevated**, left ORPHAN (documented) |
| DEF-MYPY-STRICT-001 (P2) | `scripts/source_candidate_experiment.py:462` assignment error | unchanged (not re-run this phase) | YES → still open (outside scope) |
| 1 pytest failure (dependency-closure guard) | untracked research modules | new untracked `strategy_lifecycle` package widens it | resolved by committing (see §4) |

## 3. Component classification (real repo, not docs)

- **RUNTIME_AUTHORITATIVE**: `scripts/autonomous_paper.py`, `autonomous/runtime.py`,
  `autonomous/contracts.py`, `autonomous/decision.py`, `autonomous/trace.py`,
  `autonomous/outcomes.py`, `autonomous/experience.py`, `autonomous/admission_ledger.py`,
  `autonomous/strategy_state.py`, `autonomous/pit.py`, `risk/manager.py`,
  `research/strategy_router.py`, `research/router_gates.py`,
  `research/families/*` (6 admitted), `paper/broker.py`.
- **RUNTIME_REACHABLE**: `execution/live_gate.py` (blocked by design),
  `config/runtime.py::_check_live_gates`, `paper/reconciliation_v4.py`.
- **RESEARCH_ONLY**: `research/portfolio_backtest.py`, `research/experimental/*`,
  `research/regime.py`, `research/registry.py`, `research/validation.py`.
- **ORPHAN / DEAD_CODE** (0 callers): `research/regime.py::RegimeEngine`,
  `paper/portfolio_manager.py`, `paper/strategy_selector.py`,
  `market_data/htf_pit.py`.
- **TEST_ONLY**: `market_data/fake.py` fixtures.
- **NEW (this phase, EXPERIMENTAL→discovery plane)**: `src/trading_bot/strategy_lifecycle/*`.

## 4. GATE 0 decisions

1. Fix DEF-RISK-EXPOSURE-001 (P0) and DEF-RISK-INERT-002 before granting any
   automatic activation capability. **DONE** (see `RISK_FIX_RECORD.md`).
2. Fix DEF-PROV-001 while the tree is open. **DONE**.
3. Keep all new work additive and isolated on the discovery plane; the hot PAPER
   loop is not rewired in this phase (no live campaign, but router integration is
   phase G and must be independently verified before it hot-loads).
4. Commit the new modules so the dependency-closure guard is satisfied on a clean
   checkout (§30 asks for small logical commits).
