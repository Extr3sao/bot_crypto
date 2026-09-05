# DEMO-PAPER-01 Runtime Authority Map

Audit basis: current repository `a38e11eb7f894df2df27630a3ab7673b40a82f0a`, with MA-4 runtime authority reachable through `b730ede14b4e925978cd8790da2bafb58a11876f`.

| Component | Current implementation | Classification | Authority notes |
| --- | --- | --- | --- |
| Paper entrypoint | `scripts/start_paper_trading.py` | RUNTIME_AUTHORITATIVE / RUNTIME_REACHABLE | PAPER-only composition root; fake provider default; refuses non-paper mode. |
| PaperSessionRunner | `src/trading_bot/paper/harness.py` | RUNTIME_AUTHORITATIVE / RUNTIME_REACHABLE | Owns scanner session, optional canonical cycle, broker reconciliation, reports. |
| PaperOrchestrator | `src/trading_bot/paper/paper_orchestrator.py` | RUNTIME_AUTHORITATIVE / RUNTIME_REACHABLE | Owns repeated paper sessions and lifecycle gates. |
| Market snapshots/provider | `src/trading_bot/scanner/scanner.py`, `src/trading_bot/market_data/fake.py`, scanner protocols | RUNTIME_AUTHORITATIVE / RUNTIME_REACHABLE | Fake source is deterministic demo/test provider; CCXT path is public-read configuration-dependent. |
| AssetContext | `src/trading_bot/research/asset_intelligence/registry.py` and agents | RUNTIME_AUTHORITATIVE / RUNTIME_REACHABLE | Builds and validates PIT context. |
| SpecialistSwarm | `src/trading_bot/multi_agent/swarm.py` | RUNTIME_AUTHORITATIVE / TESTED | Certified MA-2 runtime path; no execution authority. |
| OpportunityBoard / MetaRanker | `src/trading_bot/multi_agent/opportunity.py` | RUNTIME_AUTHORITATIVE / TESTED | Certified MA-2 ranking and conflict artifacts. |
| DebateRouter / DebateSession | `src/trading_bot/multi_agent/debate.py` | RUNTIME_AUTHORITATIVE / TESTED | Certified MA-3 structured debate and revisions. |
| DecisionEngine | `src/trading_bot/multi_agent/decision.py` | RUNTIME_AUTHORITATIVE / TESTED | Certified MA-4 selection; no sizing or execution authority. |
| DecisionPackageVerifier-v3 | `src/trading_bot/multi_agent/decision.py` | RUNTIME_AUTHORITATIVE / TESTED | Mandatory independent verification boundary. |
| CandidatePortfolio | `src/trading_bot/paper/candidate_portfolio.py` | RUNTIME_AUTHORITATIVE / RUNTIME_REACHABLE | Neutral pre-risk candidate consolidation; no sizing. |
| RiskManager | `src/trading_bot/risk/manager.py` | RUNTIME_AUTHORITATIVE / RUNTIME_REACHABLE | Sole paper sizing/admissibility authority. |
| PaperBroker | `src/trading_bot/paper/broker.py` | RUNTIME_AUTHORITATIVE / RUNTIME_REACHABLE | Simulated fill/position/PnL engine; no exchange calls. |
| Reconciliation | `PaperBroker.reconcile_session`, `src/trading_bot/paper/reconciliation.py` | RUNTIME_AUTHORITATIVE / RUNTIME_REACHABLE | Existing broker reconciliation and startup reconciler. |
| PnL/accounting | `PaperBroker`, `ClosedTrade`, `PaperExecutionSummary`, `TradeJournal` | RUNTIME_AUTHORITATIVE / RUNTIME_REACHABLE | Demo consumes broker/accounting values; no second calculator. |
| Run reports | `src/trading_bot/paper/reporting.py` | RUNTIME_REACHABLE / LEGACY-MINIMAL | Existing session report is minimal; DEMO-PAPER-01 adds a separate run report schema. |
| Dashboard server | No existing reachable server under `src/trading_bot/paper_dashboard` or `src/trading_bot/web` | ORPHAN / NOT_IMPLEMENTED | A small read-only stdlib dashboard is added for this demo; no execution/control endpoints. |
| Existing dashboard artifacts | `scripts/` and historical docs only | LEGACY / TEST_ONLY | No current runtime authority found. |

## Integration decision

Use the existing paper authorities for broker, risk, accounting, and lifecycle. Add only:

1. a strict verified-only MA-4 candidate adapter;
2. a deterministic multi-agent paper demo runner for fixture and public-data provider modes;
3. a read-only state/dashboard surface and independent validator.

The demo runner must not replace `PaperSessionRunner`, `PaperCycleEngine`, `RiskManager`, or `PaperBroker`, and must never enable live execution.
