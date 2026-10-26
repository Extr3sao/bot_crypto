# RFC048_RUNTIME_AUTHORITY_MAP

Audit produced by **WP-048-01** before a single line of the futures engine was written.
Authority order used throughout: `REAL_RUNTIME > EXECUTION_EVIDENCE > TESTS > CODE > RFC > ASSUMPTION`.

| field | value |
| --- | --- |
| HEAD audited | `66cfe08` (branch `main`) |
| working tree at audit | shared checkout with other threads active (72 files belonging to other threads were present and were not touched) |
| method | reference scan of every `src/`, `scripts/` and `tests/` python file for each component, plus direct reads of the modules it located |
| conclusion | **no second Risk Engine was written.** The spot authority (`RiskManager`) is untouched and RFC-048 adds a *separate* futures plane that consumes the existing decision contracts |

## 1. Authority classes

`RUNTIME_AUTHORITATIVE` — reachable from a real entrypoint and produces the values the runtime acts on.
`RUNTIME_REACHABLE` — importable/instantiable from a real entrypoint but not on the current live path.
`TEST_ONLY` — referenced exclusively by tests.
`EXPERIMENTAL` — research code with its own report, not on the runtime path.
`LEGACY` — superseded, still importable.
`ORPHAN` — no importer anywhere.

## 2. Component map

| component | class | evidence | RFC-048 action |
| --- | --- | --- | --- |
| `src/trading_bot/app.py` | RUNTIME_AUTHORITATIVE | CLI entrypoint (`trading-bot = trading_bot.app:main`) | untouched |
| `scripts/autonomous_paper.py` | RUNTIME_AUTHORITATIVE | composes scanner → router → decision → PaperBroker; refuses to start outside `paper` mode | untouched |
| `scripts/start_paper_trading.py` | RUNTIME_AUTHORITATIVE | composes `PaperCycle` + `RiskManager` | untouched |
| `src/trading_bot/risk/manager.py` — `RiskManager` | RUNTIME_AUTHORITATIVE | imported by `paper/paper_cycle.py`, `paper/paper_runtime_state.py`, `paper/reconciliation_v4.py`, `strategies/pipeline.py` + 5 scripts | **reused, unmodified**: remains the single spot sizing authority |
| `src/trading_bot/paper/broker.py` — `PaperBroker` | RUNTIME_AUTHORITATIVE | 6 src importers, 5 scripts, 7 test files | untouched; RFC-048 adds **no** futures route to it |
| `src/trading_bot/paper/harness.py`, `paper_cycle.py`, `paper_orchestrator.py` | RUNTIME_AUTHORITATIVE | orchestration of the paper session | untouched |
| `src/trading_bot/autonomous/runtime.py` (1731 lines) | RUNTIME_AUTHORITATIVE | driven by `scripts/autonomous_paper.py` | untouched |
| `src/trading_bot/autonomous/decision.py` — `DecisionEngine` | RUNTIME_AUTHORITATIVE | the first-match decision authority (`TRADE_PAPER` / `SHADOW_TRADE` / `NO_TRADE`) | **consumed read-only** by the new adapter (`risk/futures/integration.py`) |
| `src/trading_bot/autonomous/contracts.py` — `RiskReview`, `TradeProposal`, `AdmissionEntry`, `VerificationResult` | RUNTIME_AUTHORITATIVE | the typed vocabulary the runtime stores in the trace | **reused unmodified**: the futures engine maps onto `RiskReview` |
| `src/trading_bot/execution/live_gate.py` | RUNTIME_AUTHORITATIVE | pre-flight gate for live mode; 0 src importers found, 1 test file | untouched; live remains `DISABLED` |
| `src/trading_bot/execution/cost_model.py` — `ExecutionCostModel` | RUNTIME_REACHABLE | imported by `paper/startup_recovery.py` | untouched; the futures plane does **not** reuse the spot bps |
| `src/trading_bot/research/microstructure/cost_model_v3.py` (23.7906 bps) | EXPERIMENTAL / frozen | `docs/COST_MODEL_V3.json`; cited by RFC-046 discovery | cited for the **spot** column only; not modified, not reused as a futures cost |
| `src/trading_bot/market_data/bitunix_futures.py` | RUNTIME_REACHABLE | imported by `app.py` and `market_data/wiring.py`; no sizing/margin logic | declared in the map, **unreachable** from RFC-048 (offline only) |
| `src/trading_bot/research/managed_futures_v1.py` (1151 lines) | EXPERIMENTAL | running under `scripts/rfc036_run.py`; no src/test importers | reviewed, not extended: it is a research experiment, not a risk plane |
| `src/trading_bot/paper/portfolio_manager.py` | ORPHAN | **0** importers in `src/`, `scripts/` or `tests/` | left alone (documented, not revived or deleted) |
| `src/trading_bot/research/equity_reconstruction.py` | TEST_ONLY | 1 integration test importer | left alone |
| `src/trading_bot/research/canonical_accounting.py`, `cost_integrity.py`, `portfolio_backtest.py`, `business_freeze.py`, `llm_safety.py` | TEST_ONLY / ORPHAN | 0–1 importers, never on the runtime path | left alone |
| `src/trading_bot/strategy_lifecycle/pods.py` | RUNTIME_REACHABLE | imported by `observability/topology.py` | left alone |

## 3. Gaps found

1. **No futures risk code existed.** The scan found zero occurrences of `leverage`, `liquidation`,
   `maintenance_margin` or `funding_rate` in any non-test, non-script python module. Every reference lived in
   research scripts, tests or the declared-but-unused `bitunix_futures` client. A new plane was therefore
   required — but it was built *next to* the spot authority, not in place of it.
2. **Position sizing was spot-only.** `RiskManager._compute_position_size` divides the risk budget by the stop
   distance and never charges costs, slippage or a gap reserve; that is exactly the pattern RFC-048 §5
   forbids for futures. It is left untouched for spot and not reused for futures.
3. **Two parallel cost models already existed** (`execution/cost_model.py` and
   `research/microstructure/cost_model_v3.py`) with different numbers. RFC-048 adds a third, explicitly
   futures-scoped model rather than silently widening either.
4. **The decision boundary already models risk as a three-valued review** (`PASS` / `ADJUST` / `VETO` plus
   `advisory`), which is a natural insertion point. RFC-048 integrates there instead of building a parallel
   decision engine.
5. **No IOC/venue restriction data existed in code**, so the jurisdictional gate is recorded as data
   (`regulatory_eligibility_status`) and enforced by the engine (`PRODUCT_NOT_AVAILABLE` → `DATA_INVALID`).

## 4. What RFC-048 owns

```text
src/trading_bot/risk/futures/            NEW   — instrument, margin, sizing, costs, portfolio, engine, adapter
src/trading_bot/risk/futures_verification.py NEW — independent verifier (imports no builder module)
tests/unit/risk/test_futures_*.py        NEW   — adversarial, invariant, integration tests
scripts/rfc048_{derive_instruments,run,verify,report}.py NEW
data/rfc048/**                           NEW   — raw venue payloads, fixtures, measured artefacts
docs/rfc/RFC-048_*.md|json, docs/architecture/RFC048_*.md, docs/research/RFC048_*.md NEW
```

Nothing else was modified. In particular `config/risk.yaml`, `config/runtime.yaml`,
`docs/COST_MODEL_V3.json`, the ST-6 scheduler and every other thread's files are untouched.
