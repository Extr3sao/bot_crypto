# STRATEGY RUNTIME AUTHORITY MAP — POC02-R2 (DEF-STRAT-RUNTIME-001)

Checkpoint: **POC02-R2-OBSERVATION-AND-STRATEGY-RUNTIME-01** (TRACK B / B1)
Evidence sources: source code (not tests), registry/export analysis, live
POC02-R2 attribution ledger (`reports/poc02-r2-direction-arbitration-01/cycles/POC02_ATTRIBUTION.jsonl`),
admission registry (`39578a6:docs/admission-foundation-01/evidence/STRATEGY_REGISTRY.json`),
`docs/strategy-design.md`.

## 1. The two runtimes (why "registered" ≠ "reachable")

There are **two distinct strategy runtimes** in the repository:

| Runtime | Composition | Who uses it |
| --- | --- | --- |
| **MA-2 swarm runtime** (multi-agent) | `register_swarm_agents` registers all 5 `StrategyExpert`s; `SpecialistSwarm.evaluate` invokes them | POC02/POC02-R2 bundle (`_proposal_set`) — **but the campaign composition bypasses the experts with `_FixtureFamily`** (momentum-echo) |
| **Canonical paper runtime** (CP-PO-002) | `PaperCycleEngine`: `StrategyRouter` + `strategy_map` + real `AlphaFamily` classes | `scripts/start_paper_trading.py` (legacy paper runtime); **NOT used by POC02-R2** |

## 2. Per-strategy authority map

`INVOCATION_EVIDENCE` = live POC02-R2 attribution rows for this family;
`ROUTER_STATE` = what `StrategyRouter.route()` would decide from the
admission registry under `require_confirmed=True` (its committed default).

| Strategy | SOURCE_MODULE | ENTRYPOINT (MA-2) | REGISTRY_STATE (admission) | ROUTER_STATE | RUNTIME_REACHABLE (POC02-R2) | INVOCATION_EVIDENCE | SIGNAL_EVIDENCE | PROPOSAL_EVIDENCE | CLASSIFICATION |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| momentum | `research/families/momentum_family.py` | `MomentumExpert` / `STRATEGY_EXPERT_FACTORIES["momentum"]` | `poc01-momentum`: LEGACY_PAPER_BASELINE (confirm=NOT_RUN) | REJECTED (needs CONFIRMED) | **NO** — family exists and is invoked as `_FixtureFamily` echo only; canonical `MomentumExpert` never called on campaign path | 0 canonical evaluations/cycle | fixture echo signal per direction | 2 candidates/cycle (1 LONG + 1 SHORT echo) | **LEGACY** (echo composition) — family code RUNTIME_REACHABLE in the canonical paper runtime only |
| trend | `research/families/trend_family.py` | `TrendExpert` | `poc01-trend`: LEGACY_PAPER_BASELINE | REJECTED | NO — registered+invoked only via swarm contract, which the campaign composition never calls | 0 | 0 | 0 | **LEGACY** |
| breakout | `research/families/breakout_family.py` | `BreakoutExpert` | `poc01-breakout` LEGACY_PAPER_BASELINE; `edge-002-ha-breakout` DISCOVERY_PASS (confirmation BLOCKED) | REJECTED | NO | 0 | 0 | 0 | **LEGACY** (canonical); discovery candidate in RESEARCH |
| mean_reversion | `research/families/mean_reversion_family.py` | `MeanReversionExpert` | `poc01-mean_reversion`: LEGACY_PAPER_BASELINE | REJECTED | NO | 0 | 0 | 0 | **LEGACY** |
| volatility | `research/families/volatility_family.py` | `VolatilityExpert` | `poc01-volatility`: LEGACY_PAPER_BASELINE | REJECTED | NO | 0 | 0 | 0 | **LEGACY** |
| ema_crossover | `research/families/ema_crossover_family.py` | (no MA-2 expert) | n/a (baseline family) | — | NO | 0 | 0 | 0 | **LEGACY_ONLY** (paper runtime baseline) |

## 3. Root-cause classification (per strategy)

All four unavailable strategies share ONE root cause:

**Root cause: `COMPOSITION_MISSING`** (with `LEGACY_ONLY` admission state).

Trace of the missing link, step by step (same for trend/breakout/
mean_reversion/volatility):

1. **definition** — canonical `AlphaFamily` implementation EXISTS and is
   preregistered (`research/families/<family>_family.py`).
2. **registration** — MA-2: registered (`STRATEGY_EXPERT_FACTORIES` +
   `register_swarm_agents`); paper runtime: registered in
   `start_paper_trading.py` strategy_map with `status: CONFIRMED` **hard-coded
   for the legacy demo runtime** (not derived from the admission registry).
3. **router eligibility** — the canonical `StrategyRouter`
   (`research/strategy_router.py`) defaults to `require_confirmed=True`;
   the admission registry (the authority per `docs/admission-foundation-01/`)
   holds all poc01-* families at `LEGACY_PAPER_BASELINE`
   (confirmation NOT_RUN) and the edge-002 candidates at `DISCOVERY_PASS`
   with confirmation BLOCKED. Under the honest admission state, the router
   would answer `REJECTED` for every family. The legacy demo bypasses this by
   hard-coding `status: CONFIRMED`.
4. **orchestrator invocation** — the POC02-R2 campaign composition
   (`_proposal_set`) does not consult the router or the experts at all: it
   instantiates `_FixtureFamily(direction)` (momentum-echo) directly.
5. **strategy expert / proposal construction** — experts are fully able to
   build proposals (`StrategyExpert.evaluate` → `_proposal_from_signal`).
6. **runtime composition** — MISSING LINK: no campaign composition wires
   `AssetContext → StrategyRouter → selected families → StrategyExpert →
   DirectionArbiter → board`. The swarm (`SpecialistSwarm.evaluate`) implements
   most of it but has no router stage and is not what the campaign calls.

Per-strategy classification tags (closed set from the checkpoint):
`trend/breakout/mean_reversion/volatility` = **COMPOSITION_MISSING** (root)
with admission state **LEGACY_ONLY** (poc01-*) / **RESEARCH_ONLY**
(edge-002 breakout/momentum candidates: DISCOVERY_PASS, confirmation locked
until 2026-09-22). `momentum` = **COMPOSITION_MISSING** for the canonical
family; what actually trades today is the deterministic fixture echo
(TEST_ONLY semantics elevated to campaign composition — the R2 manifest
freezes this honestly).

## 4. NO_BLIND_ACTIVATION check (B2) — per strategy verdicts

| Strategy | canonical impl | PIT safety | input compat | output contract | cost assumptions | admission authority | Verdict |
| --- | --- | --- | --- | --- | --- | --- | --- |
| trend | YES (preregistered params) | YES (family reads only past candles; `StrategyExpert.evaluate` filters `candle.timestamp <= context.timestamp`) | YES (OHLCV + AssetContext) | YES (AlphaSignal→TradeProposal) | YES (PaperBroker schedule) | **NO** — LEGACY_PAPER_BASELINE, confirmation NOT_RUN | **remain NOT_RUNTIME_REACHABLE** |
| breakout | YES | YES | YES | YES | YES | **NO** — poc01 legacy + edge-002 candidate confirmation BLOCKED (lock until 2026-09-22) | **remain NOT_RUNTIME_REACHABLE** |
| mean_reversion | YES | YES | YES | YES | YES | **NO** — LEGACY_PAPER_BASELINE | **remain NOT_RUNTIME_REACHABLE** |
| volatility | YES | YES | YES | YES | YES | **NO** — LEGACY_PAPER_BASELINE; DISCOVERY_FAIL (volatility_structure family, batch-02) | **remain NOT_RUNTIME_REACHABLE** |

**No strategy is blindly connected.** The four families stay
NOT_RUNTIME_REACHABLE in the campaign until their admission authority says
otherwise (confirmation/review evidence, not code plumbing).

## 5. SAFE future integration contract (B3) — prepared, not executed

For strategies that later acquire admission authority, the future runtime
composition (NEW campaign manifest required — no current POC02-R2 mutation):

```
AssetContext (PIT-trimmed)
  → StrategyRouter.route(context, regime, strategy_map)   # canonical router
  → RouterDecision: SELECTED | REJECTED | NOT_APPLICABLE | NOT_ADMITTED |
                    NOT_RUNTIME_REACHABLE | INSUFFICIENT_REGIME_EVIDENCE   (B4)
  → for each SELECTED family: StrategyExpert(family).evaluate(...)  # real family
  → DirectionArbiter.form_groups + select_direction             # per evaluation
  → OpportunityGroupVerifier.verify(...)                        # independent
  → board.add(selected side only) → DebateSession → DecisionEngine → Risk
```

Router reason semantics (B4): every non-selection is EXPLICIT and persisted
in `RouterDecision.trace` — `SELECTED`, `REJECTED` (failed gate), `NOT_APPLICABLE`
(family not defined for asset/timeframe), `NOT_ADMITTED` (admission state
below authority), `NOT_RUNTIME_REACHABLE` (no expert wiring), and
`INSUFFICIENT_REGIME_EVIDENCE` (regime map has no confident cell). No silent
omission: the router already appends a trace line per strategy it skips; the
future composition persists that trace in campaign telemetry.

## 6. MOMENTUM_RUNTIME corrected statement

The fixture echo produces proposals ONLY when the momentum-shaped fixture
family is instantiated per direction — i.e. momentum's *name* is
runtime-attributed, but the canonical `MomentumFamily` logic (MACD histogram
+ momentum threshold + ATR stop) never runs in the campaign path. The R2
manifest records this freeze explicitly; changing it is a NEW campaign
topology decision, not an in-place edit.
