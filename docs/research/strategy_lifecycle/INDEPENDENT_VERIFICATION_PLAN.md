# INDEPENDENT_VERIFICATION_PLAN — dynamic strategy ecosystem

BUILDER != VERIFIER. This plan is written by the builder; it must be EXECUTED by
a separate verifier. Until then the verdict ceiling is
`IMPLEMENTED_WITH_PENDING_VERIFICATION`. Reproduction commands assume Git Bash on
Windows and `.venv/Scripts/python.exe` (CPython 3.11).

```
REVIEWED SHA : bd9253d9c67339d4887f2f663314a826be4c4eda
BASELINE SHA : b0302d25b3cdd7962cacb121b9ff4a2b5d4565d6
GATE         : STRAT-ROUTER-005 (WP-STRAT-07 lifecycle-aware router runtime integration)
PRIOR GATE   : STRAT-GATE0-004 (GATE 0 re-audit + defect closure), END b0302d2
```

## Claims to verify (carried from prior gates)

| # | Claim | Command | Expected output |
|---|---|---|---|
| C1 | Risk P0 fixed: `max_asset_exposure_pct` is enforced | `python -m pytest -q tests/unit/strategy_lifecycle tests/unit/paper tests/unit/autonomous tests/unit/risk tests/integration` | all pass; probe below |
| C2 | Per-asset clamp binds | probe below | notional 500→100 when BTC has 900/1000 |
| C3 | Weekly/daily-dd/cooldown gates live | `pytest tests/unit/risk/test_risk_regression_matrix.py -q` | blocked_by ∈ {weekly_loss_limit, daily_drawdown, consecutive_loss_cooldown} |
| C4 | `strategy_version` provenance fixed | `grep -n "strategy_version" src/trading_bot/autonomous/runtime.py` | `f"{entry.family}@{entry.timeframe}"` |
| C5 | Lifecycle graph closed; PAUSED/CANDIDATE never reach ACTIVE | `python -m pytest -q tests/unit/strategy_lifecycle/test_contracts.py` | pass |
| C6 | No LIVE reachable | `grep -rn "LIVE" src/trading_bot/strategy_lifecycle` | only refusal guards |
| C7 | Promotion refuses "last N trades" | `pytest tests/unit/strategy_lifecycle/test_adversarial.py -k five_winning` | pass |
| C8 | Shadow cannot reach execution | `pytest tests/unit/strategy_lifecycle/test_pods.py::test_shadow_result_cannot_reach_execution` | pass (ShadowLeakError) |
| C9 | Router returns many eligible + verdicts | `pytest tests/unit/strategy_lifecycle/test_router_integration.py` | pass |
| C10 | Portfolio caps correlated exposure | `pytest tests/unit/strategy_lifecycle/test_portfolio.py` | pass |
| C11 | EXP-STRAT-DYNAMIC-001 reproduces | `python scripts/strategy_dynamic_experiment.py` | identical JSON net numbers, `DO_NOT_PROMOTE` |
| C12 | Types/lint clean | `python -m ruff check .` ; `python -m mypy --strict src/trading_bot/strategy_lifecycle` | clean |
| C13 | Full suite no NEW failures except the untracked-module guard | `python -m pytest -q` | 1433 passed / 1 failed (dependency-closure guard) |

## Claims added by GATE 0 (STRAT-GATE0-004)

| # | Claim | Command | Expected output |
|---|---|---|---|
| C14 | `DEF-VERIFY-006` closed: store memory is bounded | `pytest tests/unit/strategy_lifecycle/test_store_bounds_pit.py -q` | pass; default bound finite and > 250 |
| C15 | `DEF-VERIFY-007` closed: PIT guard enforced when a decision time is given | same file (`test_future_observation_is_refused...`) | `LifecycleStateError`, no trace recorded |
| C16 | `DEF-VERIFY-009` closed: an out-of-vocabulary verdict fails loudly | `pytest tests/unit/strategy_lifecycle/test_router_integration.py -k vocabulary` | `ValueError("router emitted an unknown verdict")` |
| C17 | `DEF-VERIFY-011` closed: `extract_state` carries the real book | `pytest tests/unit/risk/test_risk_regression_matrix.py -k extract_state` | pass; restored book still clamps |
| C18 | `DEF-VERIFY-012` closed: the book is re-adopted after a fill | `pytest tests/unit/autonomous/test_runtime_integration.py -k resynced` | ≥ 2 sync calls in one cycle |
| C19 | Campaign `paper-lab-continuous-03` is NOT active | `tasklist //FI "IMAGENAME eq python.exe"` + read `reports/paper-lab/paper-lab-continuous-03/MONITOR.jsonl` tail | no campaign python; last row stale |
| C20 | Source-ingestion batch 2 is intact | `cd reports/source-ingestion && sha256sum -c <(grep -v relative_path MANIFEST.sha256.tsv \| awk -F'\t' '{print $3"  "$1}')` | 142/142 OK |

## Claims added by WP-STRAT-07 (STRAT-ROUTER-005)

| # | Claim | Command | Expected output |
|---|---|---|---|
| C21 | LEGACY is the default and changes nothing | `pytest tests/unit/autonomous/test_routing_modes.py -k legacy` | pass; no comparisons written |
| C22 | SHADOW records a comparison and never affects execution | `pytest tests/unit/autonomous/test_routing_modes.py -k shadow` | legacy still trades; JSONL written |
| C23 | LIFECYCLE gates; a non-ACTIVE strategy cannot execute | `pytest tests/unit/autonomous/test_routing_modes.py -k blocks_a_non_active` | 0 paper trades; refusal named |
| C24 | only PAPER_ACTIVE maps to the one routable state | `pytest tests/unit/strategy_lifecycle/test_runtime_bridge.py -k only_paper_active` | pass |
| C25 | a bridge failure fails CLOSED in LIFECYCLE | `pytest tests/unit/autonomous/test_routing_modes.py -k fails_closed` | 0 paper trades |
| C26 | portfolio arbitration can only reduce | `pytest tests/unit/autonomous/test_routing_modes.py -k portfolio` | one drop, named |
| C27 | the runtime can now import the lifecycle plane | `grep -rln "strategy_lifecycle" src/trading_bot/autonomous` | `runtime.py` |

## Runtime path (reachability)

- `RiskManager.check_signal` ← `AutonomousRuntime._risk_review` and
  `AutonomousRuntime._execute_paper`; positions synced by
  `AutonomousRuntime._sync_risk_positions()` at the top of `run_cycle` **and
  after every fill** (C18).
- `StrategyRouter.route` is on the hot path (`runtime.py:668`, `paper_cycle.py`).
- As of `STRAT-ROUTER-005`, `strategy_lifecycle.runtime_bridge` and
  `StrategyRouter.select_eligible_strategies` **are called from the hot PAPER
  loop** (`runtime.py::_evaluate_asset`), under an explicit mode. The default is
  `LEGACY` (unchanged); `SHADOW` records only; `LIFECYCLE` gates execution.
- The registry / health monitor / lifecycle controller / pods are **still not
  driven by the runtime loop** (a supplied `lifecycle_ecosystem` can supply
  lifecycle states, but no promotion happens in the loop). That remains a
  further, separate step.
- Verifying "runtime reachability" now means: `grep -rln "strategy_lifecycle"
  src/trading_bot/autonomous` returns `runtime.py`, and the real
  `run_cycle` path is exercised by `tests/unit/autonomous/test_routing_modes.py`.

## Negative tests a verifier MUST run (must FAIL to promote/execute)

1. 5 winning trades → ACTIVE: `test_five_winning_trades_cannot_activate`.
2. insufficient sample → deny: `test_insufficient_sample_denies_promotion`.
3. high drawdown → no promotion: `test_high_drawdown_blocks_promotion`.
4. regime mismatch → not selected: `test_regime_mismatch_is_not_selected`.
5. challenger wins one window → no promotion: `test_challenger_winning_one_window_does_not_promote`.
6. champion loses one window → no demotion: `test_champion_losing_one_window_does_not_demote`.
7. correlated BUY cluster capped: `test_correlated_same_asset_buys_are_capped`.
8. paused + strong shadow → only SHADOW: `test_paused_strong_shadow_still_only_reaches_shadow`.
9. stale context rejected: `test_stale_context_is_rejected`.
10. future data rejected: `test_future_data_is_rejected` **and** C15.
11. shadow → execution: `test_shadow_result_cannot_reach_execution` (expect `ShadowLeakError`).
12. pod sets leverage: `test_pod_tries_to_set_leverage_is_forbidden`.
13. LLM proposed state ignored: `test_llm_proposed_state_change_is_ignored`.
14. missing evidence → no promotion: `test_missing_evidence_never_promotes`.

## Per-asset clamp probe (C2)

```
python -c "import sys;sys.path.insert(0,'src');
from trading_bot.risk.manager import RiskManager;from trading_bot.config.risk import Risk;
from trading_bot.strategies.types import Signal;
r=Risk(max_risk_per_trade_pct=0.25,max_daily_loss_pct=1.0,max_weekly_loss_pct=3.0,max_daily_drawdown_pct=2.0,max_total_drawdown_pct=5.0,max_open_positions=3,max_trades_per_day=20,max_consecutive_losses=3,consecutive_loss_cooldown_minutes=60,max_asset_exposure_pct=10,max_total_exposure_pct=25,min_order_notional_usdt=20,max_order_notional_usdt=500,default_stop_loss_pct=0.5,default_take_profit_pct=0.75);
rm=RiskManager(risk=r,equity=10000.0);
print(rm.check_signal(Signal(symbol='BTC/USDT',side='buy',strategy_name='x',timeframe='5m',confidence=.6,price=100.,stop_loss_pct=.5,take_profit_pct=.75)).position_size.notional_usdt);
rm.sync_open_positions({'BTC/USDT':{'notional_usdt':900.0}});
print(rm.check_signal(Signal(symbol='BTC/USDT',side='buy',strategy_name='x',timeframe='5m',confidence=.6,price=100.,stop_loss_pct=.5,take_profit_pct=.75)).position_size.notional_usdt)"
```

Expected: `500.0` then `100.0`.

## Known defects (not hidden)

- `DEF-HTF-PIT-001` (ORPHAN, P3) — escalate to P0 if `research/experimental/*`
  is tracked.
- `DEF-MYPY-STRICT-001` (P3) — `scripts/source_candidate_experiment.py:462`.
- The dependency-closure guard fails while untracked `research/experimental/*`
  exist; the guard is intentionally NOT disabled.

## What the verifier should NOT accept

- A PASS that never executed `RiskManager.check_signal` on a synced book.
- A PASS where the dynamic plane's shadow results influenced execution.
- A PASS that declares CERTIFIED/READY/PRODUCTION_READY without this plan being
  executed by a separate agent.
- A "PASS" that treated the dynamic plane as runtime-reachable: it is not wired.
