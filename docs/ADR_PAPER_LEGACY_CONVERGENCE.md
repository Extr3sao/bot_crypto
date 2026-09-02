# ADR — Paper Legacy Convergence (FASE 10 / CP-PO-002)

Status: ACCEPTED
Date: 2026-09-02
Scope: designation of canonical vs legacy paper components. No code deleted.

## Context

The repository accumulated parallel implementations of the same responsibilities
across phases (v031–v033 efforts, orchestrator work). The canonical paper runtime
(`paper_orchestrator.py`, `paper_cycle.py`, `harness.py`, `broker.py`) must use
exactly one implementation of each responsibility.

Verified usage (import graph inspected 2026-09-02 on commit `5804dfd`):

| Component | Real users outside itself | Verdict |
| --- | --- | --- |
| `paper/strategy_router.py` (research) | canonical runtime, ADR-001 | **CANONICAL router** |
| `paper/strategy_selector.py` | only `test_v03_components.py`, `test_rfc_architecture.py` | LEGACY — DEPRECATE_NEXT |
| `paper/kill_switch.py` | config/risk semantics; runtime reads `risk.kill_switch_enabled` | **CANONICAL kill switch** |
| `paper/kill_switch_v2.py` | only `test_rfc_architecture.py` | LEGACY — DEPRECATE_NEXT |
| `paper/trade_journal.py` + `observability/journal.py` | `paper/reconciliation.py`, `bot.py`, `web/server.py` | **CANONICAL journaling** |
| `observability/journal_v3.py` | zero importers | LEGACY — DEPRECATE_NEXT |
| `paper/candidate_portfolio.py` | canonical runtime (FASE 4 promotion) | **CANONICAL portfolio contract** |
| `paper/portfolio_manager.py` | only `test_v03_components.py` | LEGACY — DEPRECATE_NEXT |
| `paper/canonical_strategy.py`, `paper/strategy_evaluator.py`, `paper/parity_gate.py` | only orphaned v031–v033 tests (excluded from collection) | LEGACY — DEPRECATE_NEXT |

## Decision

1. **StrategyRouter is the only routing authority.** `StrategySelector` is legacy;
   the canonical cycle never imports it.
2. **Kill switch semantics stay with `RiskManager` + `risk.kill_switch_enabled`**
   (`paper/kill_switch.py`). `kill_switch_v2.py` is not used by the runtime.
   Known pre-existing semantic tension (scanner treats `kill_switch_enabled=True`
   as "engaged" and pauses; RiskManager treats it as "armed" for approval gates)
   is documented tech debt (RF-4) and is handled at composition level with a
   scan-safe settings view — not by adding a third kill-switch implementation.
3. **Journaling stays on `paper/trade_journal.py` + `observability/journal.py`**
   (the path used by reconciliation and reporting). `observability/journal_v3.py`
   has no importers and is slated for deletion after the independent audit.
4. **CandidatePortfolio (paper/candidate_portfolio.py) is the only portfolio
   contract** consumed between SignalAdapter and RiskManager.

## Consequences

- The canonical runtime imports none of the legacy modules (verified by grep:
  zero hits for `kill_switch|selector|portfolio_manager|journal_v3` imports in
  `paper_orchestrator.py / paper_cycle.py / harness.py / broker.py`).
- Nothing is deleted in this phase (non-destructive convergence); deletions
  require a dedicated, migration-proven phase after independent validation.
- `tests/unit/paper/test_v03_components.py` and `tests/unit/test_rfc_architecture.py`
  still pin legacy behaviour and are the only reason legacy modules remain green.
