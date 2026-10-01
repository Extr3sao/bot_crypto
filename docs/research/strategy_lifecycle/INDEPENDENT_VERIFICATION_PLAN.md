# INDEPENDENT_VERIFICATION_PLAN — dynamic strategy ecosystem

BUILDER != VERIFIER. This plan is written by the builder; it must be EXECUTED by
a separate verifier. Until then the verdict ceiling is
`IMPLEMENTED_WITH_PENDING_VERIFICATION`. Reproduction commands assume Git Bash on
Windows and `.venv/Scripts/python.exe` (CPython 3.11.15).

## Claims to verify

| # | Claim | Command | Expected output |
|---|---|---|---|
| C1 | Risk P0 fixed: `max_asset_exposure_pct` is enforced | `python -m pytest -q tests/unit/strategy_lifecycle tests/unit/paper tests/unit/autonomous tests/integration` | all pass; probe below |
| C2 | Per-asset clamp binds | `python -c "<probe>"` (see negative tests) | notional 500→100 when BTC has 900/1000 |
| C3 | Weekly/daily-dd/cooldown gates live | probe | blocked_by ∈ {weekly_loss_limit, daily_drawdown, consecutive_loss_cooldown} |
| C4 | `strategy_version` provenance fixed | `grep -n "strategy_version" src/trading_bot/autonomous/runtime.py` | `f"{entry.family}@{entry.timeframe}"`, not `str(entry.timeframe)` |
| C5 | Lifecycle graph closed; PAUSED/CANDIDATE never reach ACTIVE | `python -m pytest -q tests/unit/strategy_lifecycle/test_contracts.py` | pass |
| C6 | No LIVE reachable | same + `grep -rn "LIVE" src/trading_bot/strategy_lifecycle` | only refusal guards |
| C7 | Promotion refuses "last N trades" | `pytest .../test_adversarial.py -k five_winning` | pass |
| C8 | Shadow cannot reach execution | `pytest .../test_pods.py::test_shadow_result_cannot_reach_execution` | pass (ShadowLeakError) |
| C9 | Router returns many eligible + verdicts | `pytest .../test_router_integration.py` | pass |
| C10 | Portfolio caps correlated exposure | `pytest .../test_portfolio.py` | pass |
| C11 | EXP-STRAT-DYNAMIC-001 reproduces | `python scripts/strategy_dynamic_experiment.py` | identical JSON net numbers |
| C12 | Types/lint clean | `python -m ruff check .` ; `python -m mypy src/trading_bot/strategy_lifecycle scripts/strategy_dynamic_experiment.py` | clean |
| C13 | Full suite no NEW failures except the known untracked-module guard | `python -m pytest -q -p no:cacheprovider` | see Known defects |

## Runtime path (reachability)

- `RiskManager.check_signal` ← `AutonomousRuntime._risk_review` (`runtime.py:1174`)
  and `AutonomousRuntime._execute_paper` (`:1233`); positions now synced by
  `AutonomousRuntime._sync_risk_positions()` at the top of `run_cycle`.
- `StrategyRouter.select_eligible_strategies` is **reachable but not yet called
  by the hot PAPER loop**. Verifying "runtime reachability" of the dynamic
  plane means: it is importable and callable on a real context; wiring it into
  the hot loop is a separate, explicitly deferred step (no live campaign exists
  and the change must be independently verified first).

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
10. future data rejected: `test_future_data_is_rejected`.
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

- `DEF-HTF-PIT-001` (ORPHAN, P2), `DEF-MYPY-STRICT-001` (P2, prior experimental
  driver), and any residual untracked-module dependency-closure failure are
  pre-existing and outside this phase.
- The offline experiment sets `independent_verification_required=False` (no
  verifier exists in a backtest); the runtime default stays True.

## What the verifier should NOT accept

- A PASS that never executed `RiskManager.check_signal` on a synced book.
- A PASS where the dynamic plane's shadow results influenced execution.
- A PASS that declares CERTIFIED/READY/PRODUCTION_READY without this plan being
  executed by a separate agent.
