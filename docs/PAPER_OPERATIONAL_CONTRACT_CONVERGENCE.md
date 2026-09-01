# PAPER OPERATIONAL — Contract Convergence (FASE 2)

Baseline: `fad3fb1`. Audit date: 2026-09-01.
Source of truth: code + imports, not docs.

## 1. Contract inventory

| Contract | Location | Consumed by | Verdict |
|---|---|---|---|
| `AssetContext` | `research/asset_intelligence/models.py` | StrategyRouter, families (via StrategyInput) | **CANONICAL** context |
| `RouterDecision` | `research/strategy_router.py` | (new) paper orchestrator | **CANONICAL** router output |
| `RouterGates` | `research/strategy_router.py` + `router_gates.py` | StrategyRouter | CANONICAL gates |
| `AlphaFamily` (Protocol) | `research/alpha.py` | AlphaRegistry, 6 families | **CANONICAL** family contract |
| `AlphaSignal` | `research/types.py` | families → research pipeline | research-side signal |
| `Signal` | `strategies/types.py` | RiskManager.check_signal, PaperBroker.execute_signal | **CANONICAL** execution signal |
| `SignalCandidate` | `domain/models/signal.py` | research signal registry | research-side candidate (immutable) |
| `StrategySelector` | `paper/strategy_selector.py` | **ZERO importers** | **LEGACY — superseded by StrategyRouter** |
| `StrategyConfig` (paper) | `paper/strategy_selector.py` | none | LEGACY (dup of `strategies/types.py` StrategyConfig) |
| `StrategyConfig` (runtime) | `strategies/types.py` | strategy engine | CANONICAL runtime config |
| `CandidatePortfolio` | `research/robustness.py` | research only, `execution_wired=false` | research artifact → needs neutral promotion (FASE 4) |
| `PortfolioManager` | `paper/portfolio_manager.py` | paper agents | exposure/capital tracking (global) |
| `RiskManager` | `risk/manager.py` | paper loop, execution | **CANONICAL** risk authority |
| `RiskCheck` / `PositionSize` | `risk/manager.py` | broker, orchestrator | CANONICAL risk decision |
| `PaperBroker` | `paper/broker.py` | harness, evaluator | **CANONICAL** paper execution |
| `PaperPosition` / `ClosedTrade` | `paper/broker.py` | journal, reporting | CANONICAL position/fill |
| `TradeJournal` (paper) | `paper/trade_journal.py` | harness | paper-side journal |
| `TradeJournal` (observability) | `observability/journal.py` | legacy sessions | LEGACY |
| `TradeJournalV3` | `observability/journal_v3.py` | V3 sessions | **CANONICAL** journal |
| `KillSwitch` | `paper/kill_switch.py` | app.py, orchestrator | in use |
| `KillSwitchV2` | `paper/kill_switch_v2.py` | **ZERO importers** | LEGACY — keep, do not wire |
| `Signal` | `strategies/types.py` | RiskManager, PaperBroker | **THE adapter target** |

## 2. Key incompatibilities

1. **Research → execution gap**: `AlphaSignal` (family output) ≠ `Signal` (broker input).
   Adapter needed: AlphaSignal → Signal (symbol, side LONG→buy, entry_reference→price,
   effective_stop → stop_loss_pct, metadata.notional_usdt from risk sizing).
2. **Two selection engines**: `StrategyRouter` (pure, regime-aware) vs `StrategySelector`
   (disk-backed CRUD, zero importers). Router is canonical; Selector is legacy CRUD only.
3. **Three journals**: paper-side, observability V1, V3. V3 canonical.
4. **Two kill switches**: v1 wired into app/orchestrator; v2 unwired. v1 canonical.

## 3. Decisions (binding for FASE 3–15)

- D1: `StrategyRouter` = canonical selection. `StrategySelector` = LEGACY (no runtime use).
- D2: Adapter `alphaSignalToSignal()` converts family output → `strategies/types.Signal`
  so RiskManager + PaperBroker work unchanged.
- D3: `CandidatePortfolio` (robustness) stays research-only. The paper runtime gets a
  lightweight `CandidateSet` (asset, strategy, direction, score, regime, timestamp)
  defined FASE 4 — no capital allocation, no research-object reuse.
- D4: `PaperBroker.execute_signal` stays the ONLY execution path. Orchestrator must call
  `RiskManager.check_signal` first and record rejections.
- D5: `TradeJournalV3` = canonical journal; older ones untouched (legacy).
- D6: `KillSwitch` (v1) = canonical; v2 stays legacy/unwired.
- D7: No big-bang refactor — the orchestrator composes existing components as-is.

## 4. What is NOT touched

- `execution/gateway.py`, `live_gate.py` — outside paper runtime.
- Any exchange adapter write path — market data stays read-only.
- Legacy modules (selector, kill_switch_v2, old journals) — left in place.
