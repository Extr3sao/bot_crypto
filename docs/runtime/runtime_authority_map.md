# RUNTIME AUTHORITY MAP — RFC-000

> Derived from the current HEAD `df95974` by reading the import graph, call sites
> and one real PAPER execution (see `reports/rfc000/RUNTIME_EXECUTION_REPORT.md`).
> Authority order: `REAL_RUNTIME > EXECUTION_EVIDENCE > TESTS > SOURCE_CODE > ARCH/RFC >
> EXTERNAL_SOURCE > ASSUMPTION`. A class on disk is NOT authority: reachability is
> demonstrated.

## Entrypoints

| id | path | kind | evidence |
| --- | --- | --- | --- |
| PRIMARY_RUNTIME_ENTRYPOINT | `scripts/autonomous_paper.py` | autonomous PAPER/SHADOW loop | executed: `--provider fake --cycles 2` → exit 0, 6 decisions, 6 traces |
| PRIMARY_PAPER_ENTRYPOINT | `scripts/autonomous_paper.py` | (same) | see above |
| PRIMARY_BACKTEST_ENTRYPOINT | `scripts/multi_family_backtest.py` | research backtest | static + tests |
| PRIMARY_RESEARCH_ENTRYPOINT | `scripts/paper_lab_research.py` | research | static |
| PRIMARY_DASHBOARD_ENTRYPOINT | `scripts/strategy_ecosystem_dashboard.py` | read-only observability | executed: HTTP 200 on `127.0.0.1:8790` |
| CLI | `trading-bot` → `trading_bot.app:main` | config-check / scan / run / place-order | static (live paths env-gated) |
| Legacy PAPER | `scripts/start_paper_trading.py` | earlier PAPER loop | static; superseded by autonomous runtime |
| Supervisor | `scripts/start_paper_lab.py` | campaign supervisor | static |

## Authoritative chain (PAPER)

```
scripts/autonomous_paper.py
  ├─ load_settings (config/realdata) + PairSpec universe
  ├─ AdmissionLedger.load(config/strategy_admission.json)      [fail-closed]
  ├─ StrategyRegistry.from_ledger                              [lifecycle states]
  ├─ build_scanner_factory → UniverseScanner (read-only market data)
  ├─ preflight_run_universe (configured ∩ provider ∩ strategy)
  ├─ FetcherBarReader (PIT history, closed-candle gate)
  ├─ PaperBroker(equity)  ← the ONLY execution boundary
  ├─ RiskManager(risk, equity)
  ├─ IdempotencyGuard + PaperStateStore + StartupReconcilerV4
  └─ AutonomousPaperRuntime(...)
        └─ per asset, per cycle:
             scanner snapshot → FetcherBarReader.get_ohlcv
             → CryptoAssetAgentRegistry.build_context (regime, PIT)
             → StrategyRouter.route(context, regime, strategy_map)
             → AlphaFamilies.generate (6 families)
             → _build_proposal (TradeProposal)
             → SpecialistAgent review (5 shared reviewers)
             → IndependentVerifier.verify (re-reads ledger)
             → DecisionEngine.decide
             → _risk_review  → RiskManager.check_signal   (risk #1)
             → _execute_paper → RiskManager.check_signal  (risk #2)
                              → PaperBroker.execute_signal
             → _reconcile / _process_outcomes
             → DecisionTraceStore.append + heartbeat + daily/RUN report
```

## Component classification

| component | path / symbol | classification | evidence |
| --- | --- | --- | --- |
| AutonomousPaperRuntime | `autonomous/runtime.py::AutonomousPaperRuntime` | RUNTIME_AUTHORITATIVE | executed (6 decisions) |
| UniverseScanner | `scanner/scanner.py` | RUNTIME_AUTHORITATIVE | executed (3 pairs/cycle) |
| FetcherBarReader | `paper/snapshot_history.py` | RUNTIME_AUTHORITATIVE | executed (candle_filter 95/100) |
| CryptoAssetAgentRegistry | `research/asset_intelligence/*` | RUNTIME_AUTHORITATIVE | executed (regime RANGE) |
| StrategyRouter.route | `research/strategy_router.py::StrategyRouter.route` | RUNTIME_AUTHORITATIVE | called at runtime.py:773 |
| AlphaFamilies (6) | `research/families/*` | RUNTIME_AUTHORITATIVE | constructed in entrypoint |
| StrategyRegistry | `autonomous/strategy_state.py::StrategyRegistry` | RUNTIME_AUTHORITATIVE | from_ledger, gates PAPER |
| AdmissionLedger | `autonomous/admission_ledger.py` | RUNTIME_AUTHORITATIVE | loaded at startup |
| SpecialistAgent review (5) | `autonomous/agents.py` | RUNTIME_AUTHORITATIVE | `_agents.review` at runtime.py:952; 5 agents printed |
| IndependentVerifier | `autonomous/verifier.py` | RUNTIME_AUTHORITATIVE | `_verifier.verify` at runtime.py:1005 |
| DecisionEngine | `autonomous/decision.py` | RUNTIME_AUTHORITATIVE | constructed at runtime.py:336 |
| RiskManager | `risk/manager.py` | RUNTIME_AUTHORITATIVE | check_signal ×2 (review + execute) |
| PaperBroker | `paper/broker.py` | RUNTIME_AUTHORITATIVE | only `execute_signal` boundary |
| IdempotencyGuard | `execution/idempotency.py` | RUNTIME_AUTHORITATIVE | wired in entrypoint |
| PaperStateStore | `paper/paper_state_store.py` | RUNTIME_AUTHORITATIVE | `paper_state.saved` emitted |
| StartupReconcilerV4 | `paper/reconciliation_v4.py` | RUNTIME_AUTHORITATIVE | `reconciliation=RECOVERED` |
| DecisionTraceStore | `autonomous/trace.py` | RUNTIME_AUTHORITATIVE | `traces.jsonl` (6 rows) |
| HeartbeatWriter / reporting | `autonomous/observability.py`, `reporting.py` | RUNTIME_AUTHORITATIVE | heartbeat + RUN_REPORT written |
| StrategyRouter.select_eligible_strategies | `research/strategy_router.py` | RUNTIME_REACHABLE | only under `--strategy-routing-mode LIFECYCLE` (default LEGACY) |
| StrategyRoutingMode (LEGACY/SHADOW/LIFECYCLE) | `strategy_lifecycle/runtime_bridge.py` | RUNTIME_REACHABLE | `--strategy-routing-mode` default LEGACY |
| strategy_lifecycle/** (pods, lifecycle, health, champion) | `strategy_lifecycle/*` | RESEARCH_ONLY / TEST_ONLY | no `StrategyPod(` construction in runtime path; imported by scripts/tests |
| StrategyEcosystemObservatory | `observability/ecosystem.py`, `topology.py` | OBSERVABILITY (read-only) | dashboard executed; not trading authority |
| Dashboard server | `scripts/strategy_ecosystem_dashboard.py` | OBSERVABILITY (read-only) | HTTP 200; GET-only |
| PaperCycleEngine (legacy) | `paper/paper_cycle.py` | LEGACY | used by `verify_l5_independent.py`, not by autonomous runtime |
| StartupReconciler V1 / recovery V3 / parity_gate / portfolio_manager / strategy_selector / trade_journal / validation | `paper/*` | ORPHAN | see `docs/runtime_authority_map.md` (2026-09-25) |
| `research/pair/*` (RFC-030) | `research/pair/*` | RESEARCH_ONLY | only self-imports + scripts + tests; `EXP-ARP-023 = BLOCKED_SHORT_DATA` |
| `research/experimental/*` | `research/experimental/*` | EXPERIMENTAL (untracked) | only `scripts/source_candidate_experiment.py` + tests |
| `market_data/htf_pit.py` | `market_data/htf_pit.py` | ORPHAN | zero `src/` importers; only untracked experimental + script |
| `market_data/bitunix*.py`, `app.py` live paths | CLI | RUNTIME_REACHABLE (env-gated) | out of PAPER scope |

## Risk unavoidability

There is **no** path `Strategy → Broker` or `Agent → Broker`. Every broker call site
outside tests is either the autonomous runtime (behind two `RiskManager.check_signal`
calls) or the legacy PAPER engine. `grep` for `.execute_signal` / `PaperBroker(` shows
only `autonomous/runtime.py:1422`, `paper/paper_cycle.py:425`, entrypoint
construction, and the L5 verifier script.
