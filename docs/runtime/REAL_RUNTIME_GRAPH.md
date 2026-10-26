# REAL RUNTIME GRAPH — RFC-000

> The graph that actually runs, derived from the import graph, the call sites and one
> real execution (HEAD `df95974`, `RFC000-AUDIT-01`). Not the desired architecture.

## What starts the system

```
python scripts/autonomous_paper.py --provider {ccxt|fake} --cycles N|--continuous
```

This is the **only** primary PAPER entrypoint. `scripts/start_paper_trading.py`
(legacy loop) and `scripts/start_paper_lab.py` (supervisor) exist but the autonomous
runtime is the canonical one exercised here.

## Executed graph (per cycle)

```
autonomous_paper.py::main
│  load_settings(config/realdata) ─────────────── Settings(universe, risk, runtime)
│  AdmissionLedger.load(config/strategy_admission.json)
│  StrategyRegistry.from_ledger(...) ──────────── gates PAPER by lifecycle status
│  build_scanner_factory(settings, provider) ──── ccxt | fake
│  preflight_run_universe(...) ────────────────── configured ∩ provider ∩ strategy
│  FetcherBarReader(source, timeframe)
│  PaperBroker(equity=10_000)                     ← execution boundary
│  RiskManager(settings.risk, equity)
│  IdempotencyGuard()
│  PaperStateStore(data/storage/...json)
│  StartupReconcilerV4(...).reconcile() ───────── RECOVERED
│  AutonomousPaperRuntime(...)
│
└─ for cycle in cycles:
     for asset in assets:                 # BTC, ETH, SOL
       UniverseScanner.scan_iteration() ── scanner.pair.processed (3)
       FetcherBarReader.get_ohlcv(as_of) ─ candle_filter.filtered (95/100 completed)
       CryptoAssetAgentRegistry.build_context ─ regime=RANGE, PIT window
       StrategyRouter.route(context, regime, strategy_map)   [runtime.py:773]
       AlphaFamilies.generate(...) ──────── _generate_alpha [runtime.py:802]
       _build_proposal(...) ─────────────── TradeProposal [runtime.py:918]
       SpecialistAgent.review ×5 ────────── _agents.review [runtime.py:952]
       IndependentVerifier.verify(...) ──── [runtime.py:1005]
       DecisionEngine.decide(...) ───────── classification NO_ALPHA / NO_TRADE_*
       _risk_review → RiskManager.check_signal [runtime.py:1346]
       if executable:
         _execute_paper → RiskManager.check_signal [runtime.py:1405]
                        → PaperBroker.execute_signal [runtime.py:1422]
       _reconcile(session) / _process_outcomes(...)
       DecisionTraceStore.append(...) ───── traces.jsonl
     HeartbeatWriter.write() / daily report / RUN_REPORT
```

## Executed result (`RFC000-AUDIT-01`, provider=fake, 2 cycles)

| metric | value |
| --- | --- |
| asset_cycle_evaluations | 6 |
| decisions | 6 |
| no_trades | 6 (`NO_TRADE_STRATEGIC`) |
| shadow_trades / paper_trades | 0 / 0 |
| orders_created | 0 |
| runtime_failures | 0 |
| traces_persisted | 6 |
| risk_NOT_APPLICABLE | 6 (no executable proposal → risk not invoked) |
| strategies in registry | 24 declared, 18 at 5m, 0 paper-executable (COST_KILLED=7, NO_GROSS_EDGE=17) |
| agents | `data-integrity, cost-economics, evidence-provenance, regime-alignment, risk-adversary` |

`NO_TRADE` is a valid outcome: the full runtime executed end to end and fail-closed
before any broker call (no strategy authorised for PAPER at 5m).

## Nodes that do NOT exist on the runtime path

| desired node | reality |
| --- | --- |
| `MasterOrchestrator` | absent (no such runtime symbol) |
| `StrategyPod` as a runtime actor | not constructed on the runtime path (lifecycle package only) |
| per-strategy dedicated agents | absent — 5 shared decision-layer reviewers only |
| `StrategyRouter.select_eligible_strategies` in hot path | only under routing-mode LIFECYCLE (default LEGACY) |
| PortfolioManager / parity_gate / strategy_selector | ORPHAN (no runtime caller) |
| dashboard as trading authority | N/A — read-only observability only |

## Dashboard independence

The dashboard is a separate process (`scripts/strategy_ecosystem_dashboard.py`) that
only reads artifacts (`DecisionTrace`, performance, routing comparisons, heartbeat,
admission registry) through `trading_bot.observability`. Killing it does not stop the
runtime and it exposes no mutating endpoint (all non-GET → 405). `dashboard down !=
runtime down`.
