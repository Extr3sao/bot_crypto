# MISSING MODULE AUDIT — CERT-PO-L5-001 repair candidate

Audit date: 2026-09-02
Base commit audited: `05fca62dd686c9f327aa01c39c5a2a0b4e91da09`
Method: runtime import scan of every tracked `src/trading_bot/*.py` module under
the hermetic environment, plus repo-wide reference graph (source, tests,
scripts, docs) and git history (`git log --all`) for each missing module.

Runtime scan result at `05fca62`:

```text
TRACKED_NON_INIT= 126   IMPORTED_OK= 120   FAILED= 6
FAILED trading_bot.market_data.htf_pit         :: no module 'candle_filter'
FAILED trading_bot.paper.canonical_strategy    :: no module 'signal_types'
FAILED trading_bot.paper.kill_switch_v2        :: no module 'domain.enums'
FAILED trading_bot.paper.reconciliation        :: no module 'observability.journal'
FAILED trading_bot.paper.startup_recovery      :: no module 'execution.cost_model'
FAILED trading_bot.paper.strategy_evaluator    :: no module 'signal_types'
```

The six authoritative missing modules from the certification failure resolve
to five legitimate untracked product sources plus one genuinely dead binding,
detailed per module below.

---

## 1. trading_bot.execution.cost_model

MODULE = `trading_bot.execution.cost_model`
SOURCE_FOUND = YES — `src/trading_bot/execution/cost_model.py` in the primary
worktree (`bot freebuff`), 41 lines, stdlib-only (math/dataclasses), no
internal imports.
SOURCE_PROVENANCE = Legitimate untracked project code owned by the FASE-2
execution layer (never committed on any branch; absent from `05fca62` tree).
STATUS = A (legitimate untracked product code).
TRACKED_IMPORTERS = `src/trading_bot/paper/startup_recovery.py:29`
(`from trading_bot.execution.cost_model import ExecutionCostModel`, top-level).
INTENDED_CURRENT_LOCATION = `src/trading_bot/execution/cost_model.py`
ACTION = COMMIT the existing source verbatim.
RATIONALE = Real, self-contained product module with a tracked importer; the
import fails on the clean snapshot. Smallest correct repair is to track it.

## 2. trading_bot.market_data.candle_filter

MODULE = `trading_bot.market_data.candle_filter`
SOURCE_FOUND = YES — `src/trading_bot/market_data/candle_filter.py` in the
primary worktree (PIT candle-completeness policy, FAIL-CLOSED timeframe
resolution).
SOURCE_PROVENANCE = Legitimate untracked product code (market-data layer).
STATUS = A.
TRACKED_IMPORTERS = `src/trading_bot/market_data/htf_pit.py:22`
(`from trading_bot.market_data.candle_filter import timeframe_seconds_or_raise`,
top-level).
TRANSITIVE_GAP = imports `trading_bot.market_data.timeframe`
(`TIMEFRAME_SECONDS`) — ALSO untracked at `05fca62` (new finding, not in the
6). `trading_bot.market_data.types` is tracked.
INTENDED_CURRENT_LOCATION = `src/trading_bot/market_data/candle_filter.py` +
`src/trading_bot/market_data/timeframe.py` (small, stdlib-friendly module).
ACTION = COMMIT both `candle_filter.py` and its transitive dep `timeframe.py`
from the primary tree.
RATIONALE = Real module with a tracked top-level importer; closure requires the
transitive module too.

## 3. trading_bot.market_data.scanner_bridge

MODULE = `trading_bot.market_data.scanner_bridge`
SOURCE_FOUND = YES — `src/trading_bot/market_data/scanner_bridge.py`
(`HubMarketDataSource`, asyncio-based), present in the primary worktree.
SOURCE_PROVENANCE = Legitimate untracked product code (market-data wiring).
STATUS = A.
TRACKED_IMPORTERS = `src/trading_bot/market_data/wiring.py` — tracked; committed
by `d06c09d` (the CP-PO-003 closure commit) which imported `scanner_bridge` in
a function body (line 345) without tracking the module. Classification D seen
in reverse: the importer was committed, the dependency was left out.
INTENDED_CURRENT_LOCATION = `src/trading_bot/market_data/scanner_bridge.py`
ACTION = COMMIT the existing source verbatim.
RATIONALE = Function-body import in tracked `wiring.py` fails at call time on a
clean checkout; the source exists and is product code.

## 4. trading_bot.observability.journal

MODULE = `trading_bot.observability.journal`
SOURCE_FOUND = YES — `src/trading_bot/observability/journal.py` (TradeJournal,
SQLite-backed) in the primary worktree.
SOURCE_PROVENANCE = Legitimate untracked product code; the repo ADR
(`docs/ADR_PAPER_LEGACY_CONVERGENCE.md`) classes
`observability/journal.py` CANONICAL journaling.
STATUS = A.
TRACKED_IMPORTERS =
- `src/trading_bot/observability/__init__.py:3` (`from .journal import TradeJournal`)
- `src/trading_bot/paper/reconciliation.py:19`
Both are top-level imports that make package import fail.
TRANSITIVE_GAP = `observability/__init__.py` ALSO imports
`observability/metrics.py` (`MetricPoint, MetricsCollector`) — untracked at
`05fca62` (new finding; metrics.py is stdlib-only).
INTENDED_CURRENT_LOCATION = `src/trading_bot/observability/journal.py` +
`src/trading_bot/observability/metrics.py`
ACTION = COMMIT both from the primary tree.
RATIONALE = Tracked `observability/__init__.py` cannot import without them;
both are real canonical product code.

## 5. trading_bot.paper.signal_types

MODULE = `trading_bot.paper.signal_types`
SOURCE_FOUND = NO — present in NO worktree (primary, repair, cert) and NEVER
committed on any branch (`git log --all` empty; `tests/integration/conftest.py`
documents it as a never-committed orphan). The data model its consumers use
(fields `version`, `signal_timestamp`, `planned_risk`, `planned_rr`,
`planned_net_rr`) matches NO type in the repository (`domain/models/signal.py`
`SignalCandidate` does NOT expose those fields → repointing is NOT semantic).
SOURCE_PROVENANCE = None (ghost dependency).
STATUS = B/E — stale/dead import of a never-implemented module; consumers are
legacy.
TRACKED_IMPORTERS =
- `src/trading_bot/paper/canonical_strategy.py:24`
- `src/trading_bot/paper/strategy_evaluator.py:14`
Both importers: ZERO live importers repo-wide (src + tests + scripts; only the
excluded orphaned `test_v031/v032/v033_*` integration tests reference them, and
those are `collect_ignore_glob`'d). Repo ADR classes both files
LEGACY — DEPRECATE_NEXT ("only orphaned v031–v033 tests (excluded from
collection)").
INTENDED_CURRENT_LOCATION = None — code path is obsolete.
ACTION = REMOVE the two dead legacy modules (`paper/canonical_strategy.py` and
`paper/strategy_evaluator.py`) and their references in the excluded orphaned
integration tests stay excluded. Do NOT create `signal_types.py` (that would be
a fake implementation created solely to satisfy import closure — forbidden).
RATIONALE = ADR + conftest prove obsolescence: no live imports, no live tests,
referenced module never existed. Keeping husk files with broken imports, or
creating a placeholder module, would both be fabrication.

## 6. trading_bot.domain.enums.kill_switch

MODULE = `trading_bot.domain.enums.kill_switch`
SOURCE_FOUND = YES — `src/trading_bot/domain/enums/kill_switch.py`
(5-state `KillSwitchState`/`KillSwitchAction`, RFC §16) plus the whole
`domain/enums/` package (signal, trade, health, desk, risk, execution) in the
primary worktree — all stdlib-only (enum/typing).
SOURCE_PROVENANCE = Legitimate untracked domain-enums package.
STATUS = A.
TRACKED_IMPORTERS = `src/trading_bot/paper/kill_switch_v2.py:17`
(`from trading_bot.domain.enums.kill_switch import ...`) — top-level; imports
the package, so `domain/enums/__init__.py` must be present too (it re-exports
all eight enum modules).
INTENDED_CURRENT_LOCATION = `src/trading_bot/domain/enums/*` (package restore).
ACTION = COMMIT the `domain/enums/` package from the primary tree (all 8 .py
files, stdlib-only, self-contained).
RATIONALE = Real RFC-mandated enums with a tracked importer; package marker
(`__init__.py`) required, restoring it is legitimate.

---

## Consolidated repair set

COMMIT (from primary tree, verbatim):
1. src/trading_bot/execution/cost_model.py
2. src/trading_bot/market_data/candle_filter.py
3. src/trading_bot/market_data/timeframe.py          (transitive of #2)
4. src/trading_bot/market_data/scanner_bridge.py
5. src/trading_bot/observability/journal.py
6. src/trading_bot/observability/metrics.py          (transitive of #5)
7. src/trading_bot/domain/enums/{__init__,signal,trade,health,kill_switch,desk,risk,execution}.py

REMOVE (dead legacy, documented obsolete):
8. src/trading_bot/paper/canonical_strategy.py
9. src/trading_bot/paper/strategy_evaluator.py

Permanent guard: extend the closure test to import every tracked
`src/trading_bot/*.py` module via the Python runtime and fail on any
ModuleNotFoundError (replaces naive path-string mapping).

No placeholder modules. No fake implementations. No changes to runtime
behavior of the canonical L5 cycle.
## Lint status of restored modules (candidate-owned ruff scope)

- All restored modules pass mypy strict (14 source files, 0 errors).
- Ruff on candidate-owned closure files (non-enum): 0 findings — fixed
  2×F401 (unused `math` import in cost_model.py, unused `pathlib` import in
  the closure test), unused noqa, and import/`__all__` sorting in
  `domain/enums/__init__.py`. All fixes are behavior-neutral.
- 18 UP042 findings remain ONLY in the restored `domain/enums/*` package:
  `class X(str, Enum)`. This is the repository's established convention —
  the tracked tree already carries 8 UP042 findings in
  `research/canonical_accounting.py`, `research/evidence.py`,
  `research/gates.py` (etc.) and 10 tracked F401s. Converting `(str, Enum)`
  → `StrEnum` changes `str()`/`repr()` semantics of enum members (a runtime
  behavior change), which is explicitly out of scope for a smallest-correct
  closure repair. These files are restored verbatim from the legitimate
  primary-tree product sources; a repo-wide StrEnum migration is the correct
  future task, tracked as convention debt, identical in class to the 568
  pre-existing baseline findings the certification already excludes.

## Post-repair validation (all hermetic, via scripts/cert_env.sh)

- Runtime closure scan: 124/124 tracked modules import cleanly (0 failures;
  was 6 failures / 126 modules at 05fca62; 2 dead legacy modules removed).
- Permanent closure test `test_every_tracked_module_imports_under_declared_environment`
  added to tests/unit/test_dependency_closure_guard.py: 3/3 PASS.
- pytest collection: 538 collected, 0 errors.
- tests/unit: 493 passed. tests/bdd + tests/integration: 45 passed.
- Focused paper + cert guard: 33 passed. Integration E2E: 18 passed.
- Independent verifier: 11/11 PASS. PAPER runtime smoke (fake): PASS.
