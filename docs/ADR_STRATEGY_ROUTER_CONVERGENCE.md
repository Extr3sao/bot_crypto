# ADR — StrategyRouter is the canonical strategy selector

Status: ACCEPTED (FASE 3, PAPER_OPERATIONAL program)
Date: 2026-09-01

## Context

Two selection engines exist:

- `research/strategy_router.py` → `StrategyRouter`: pure resolver,
  AssetContext + regime + strategy map → `RouterDecision` (strategy or
  NO_TRADE with reason + trace). Zero side effects. Tested (13 unit tests).
- `paper/strategy_selector.py` → `StrategySelector`: disk-backed CRUD of
  `StrategyConfig` JSON files. **Zero importers anywhere in src/ or tests/**
  (verified by grep). Duplicates `StrategyConfig` from `strategies/types.py`.

## Decision

1. `StrategyRouter` is the CANONICAL selection engine for the paper runtime.
2. `StrategySelector` is LEGACY. It is not deleted; it is simply never wired
   into the new runtime. `DEPRECATE_NEXT` once the paper runtime proves stable.
3. The paper orchestrator (FASE 5) calls `StrategyRouter.route()` only.
4. `Signal` (strategies/types.py) stays the only contract RiskManager and
   PaperBroker accept; the orchestrator adapts router/family output to it.

## Consequences

- One selection authority; no parallel engines.
- `StrategySelector` remains on disk untouched (no destructive migration).
- Legacy status recorded in docs/PAPER_OPERATIONAL_CONTRACT_CONVERGENCE.md.
