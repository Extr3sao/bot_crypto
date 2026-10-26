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

---

# UPDATE — RFC-TDM-015 (live signal plane, paper operations, dashboard)

> Audited on: HEAD `3be8e5bd` (branch `feat/wp-signal-001-003`), re-verified by
> execution on 2026-10-26, run `tdm15-live-02`. Evidence:
> `evidence/tdm/wp-tdm-15/`. Classification is re-derived from the code paths the
> run actually executed, not from the module's name.

| Plane | Implementation | Classification | Evidence of reachability |
| --- | --- | --- | --- |
| PAPER loop (bar-close) | `scripts/autonomous_paper.py` | RUNTIME_AUTHORITATIVE | 7 bar closes, 21 decisions, all `NO_TRADE_STRATEGIC` on a negative gross edge; `logs/paper.log` |
| Decision trace | `src/trading_bot/autonomous/trace.py` | RUNTIME_AUTHORITATIVE | 21 hash-chained traces; `traces.hash_chain_intact` in the verifier |
| Signal projection | `src/trading_bot/autonomous/signals.py` | RUNTIME_AUTHORITATIVE | 21 `SignalEvent` rows, 21/21 linked to their trace by hash |
| AI analyst sidecar | `scripts/ai_signal_analyst.py` + `autonomous/analysis.py` | RUNTIME_REACHABLE (no provider configured) | 6 `NOT_CONFIGURED` rows; `authority_over_orders=false`; no order import |
| Dashboard | `scripts/paper_lab_dashboard.py` | RUNTIME_AUTHORITATIVE (read-only, loopback) | `GET /`, `/api/signals`, `/api/analysis`, `/api/status`, `/healthz` measured; `POST` → 405 |
| Supervisor | `scripts/start_paper_lab.py` + `autonomous/supervisor.py` | RUNTIME_AUTHORITATIVE | 5 children started, one clean stop (`verdict CLEAN`, all exit 0), one `--restart` that resumed the same run id |
| Forward capture | `scripts/forward_collector.py` | RUNTIME_REACHABLE, separate failure domain | 310 889 events on the resumed window; 34 gaps declared in its own state |
| Admission ledger | `config/strategy_admission.json` | RUNTIME_AUTHORITATIVE (refusal) | 24 strategies, 0 admitted → `PAPER_ORDER: BLOCKED` |
| Paper broker | `src/trading_bot/paper/broker.py` | RUNTIME_REACHABLE — no eligible strategy | 0 orders, 0 fills, equity 10 000 unchanged; not exercised with a live order by design |

## What the run proved and what it did not

* The signal plane is real: signals come from the persisted decision traces of a
  live provider (`ccxt`, `source=REAL`), one row per asset per closed bar, with the
  engine's own numbers (gross, cost, net) and its own refusal reason.
* `EXPERIMENTAL_PAPER` has no eligible strategy: the ledger admits none of the 24,
  so the honest state is `BLOCKED` with zero simulated orders — not "no trades
  because nothing happened".
* Live trading is `DISABLED`: no child holds execution credentials and no live
  order was created (0 in the ledger, 0 in the broker).
* The AI plane is `UNAVAILABLE` on this host (no `SIGNAL_ANALYST_API_KEY`); it
  records the absence per signal instead of inventing analysis.
