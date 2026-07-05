## TSK-200 — Fase 2 indicators interface (spec + F1 closed + F2-Protocol in progress)

Refs: TSK-200 in `tasks/roadmap.md` (Fase 2, Pri 5 in sprint-003), exit criterion from `config/indicators.yaml`, contract from `src/trading_bot/indicators/__init__.py`.

Branch: `feature/tsk-200-indicators-interface` — **11 commits ahead** of `origin/main` (rebased onto `origin/main` pre-rebase, with one local-only history cleanup that squashed a stranded retrieval-log reorder pair into a single docs-only commit). **F1 is closed** (all five F1 sub-steps landed: `.1.1` package baseline, `.1.2` IndicatorOutput+IndicatorParams, `.1.3` `__post_init__` finiteness, `.1.4` exception hierarchy, plus `F1.1.4 round-3 nits` after code-review). **F2 step 2 is in progress** (Protocol runtime_checkable + name attribute test); the remaining F2 step 2.3 (`compute_params_hash`) + F3 (registry + cache) + F4 (EmaIndicator + BDD) + F5 (wiring + ADR-0013 sign) land in follow-up PRs.

`gh pr create --title`: `feat(indicators): TSK-200 spec + F1 closed + F2.2 in progress`

### Commits in this PR

| #   | Commit       | Scope                                                                              |
| --- | ------------ | ---------------------------------------------------------------------------------- |
| 1   | `35f62218`   | Docs-only spec scaffold: 5 SDD docs under `docs/specs/TSK-200-indicators-interface/` (01-requirements, 02-bdd, 03-specify, 04-plan, 05-tasks) + sprint-003 status flip. |
| 2   | `5af4ad7d`   | F1 step **1.1** — docstring-only package baseline. Adds `tests/unit/indicators/__init__.py` (0 bytes, tests-as-package mirror of `src/`). Adds `pythonpath = ["src"]` to `[tool.pytest.ini_options]` in `pyproject.toml` so `uv run python -c` imports work cross-shell. Patches `docs/specs/TSK-200-indicators-interface/05-tasks.md` TSK-200.1.1 DoD cell to `uv run python -c "..."` (portable form). |
| 3   | `382b08a`   | F1 step **1.2** — public types. Adds `src/trading_bot/indicators/types.py` exporting `IndicatorParams = Mapping[str, Any]` (alias for `compute()` second arg) and `@dataclass(frozen=True)` `IndicatorOutput: __slots__ = ("values",); values: dict[str, float]`. Manual `__slots__` works around CPython 3.11 bpo-46268 (the synthetic `__slots__`-base class that `@dataclass(slots=True)` inserts breaks `frozen=True`'s `__setattr__` chain). Adds `tests/unit/indicators/test_types.py` with 2 spec-mapped tests (`test_indicator_output_frozen`, `test_indicator_output_frozen_slots`). |
| 4   | `690dde4`   | F1 round-3 review Issue 2 LOW cleanup — drops the SHA `f32d04c` reference from `docs/specs/TSK-200-indicators-interface/05-tasks.md` TSK-200.1.1 DoD cell, replacing with `per code-review de F1`. Avoids amend-coupling the spec doc to commit-hash noise. |
| 5   | `3eb81f5`   | F1 step **1.3** — `__post_init__` finiteness validator. Adds to `src/trading_bot/indicators/types.py` a `__post_init__` that rejects NaN/+inf/-inf via `math.isfinite` (ValueError) and non-`float` entries via `isinstance(value, float)` (TypeError). Defense-in-depth against mypy static checks passing for runtime-int entries. |
| 6   | `98d5aff`   | F1 step **1.3** round-2 cleanup — drops dead `# type: ignore[dict-item]` from `test_post_init_rejects_non_float` int case (mypy strict accepts int → float implicit promotion under PEP 484 argument-position typing; suppression was `[unused-ignore]` dead code). Str case keeps its suppression because `dict[str, str]` is rejected against `dict[str, float]`. |
| 7   | `4d2cf55c`   | F1 step **1.4** — exception hierarchy. Adds `src/trading_bot/indicators/exceptions.py` with `IndicatorError(Exception)` base (NOT `BaseException` — pine KeyboardInterrupt/SystemExit bypass) + `RegistryFrozenError` + `InsufficientHistoryError(required: int, got: int)` (with `.required` + `.got` attrs and stringified message for tracebacks) + `ParamsHashError` (CL-4 wraps `json.dumps` TypeError defensively). Adds 2 spec-mapped tests to `test_types.py`: `test_exceptions_inherit_indicator_error` + `test_insufficient_history_error_attributes_required_got`. |
| 8   | `5f2bf28`   | F2 step **2.1** — `Indicator` Protocol. Adds `src/trading_bot/indicators/protocols.py` with `@runtime_checkable class Indicator(Protocol): name: str; def compute(self, ohlcv: list[OHLCV], params: IndicatorParams) -> IndicatorOutput: ...` (idiomatic `...` Ellipsis body for mypy strict). PEP 544 caveat documented in class-level + module-level docstrings: `@runtime_checkable` only verifies method presence, NOT data attributes (mypy enforces `name: str` statically; F3 registry enforces it at runtime via duplicate-name check). Adds `tests/unit/indicators/test_protocols.py` with `FakeIndicator` mirror class + 1 spec-mapped test (`test_indicator_protocol_runtime_checkable`). Imports `OHLCV` from `trading_bot.market_data.types` (cross-layer to the data source is allowed per spec section 11; only `strategies/execution/risk/portfolio/exchange/scanner` are forbidden). |
| 9   | `270e6e15`   | F1 step **1.4** round-3 fix — `test_exceptions_inherit_indicator_error` now uses hard MRO walk (`__mro__[0] is IndicatorError` + `__mro__[1] is Exception`) instead of transitive `issubclass(IndicatorError, Exception)`. Pins the immediate parent as `Exception` directly (not `BaseException`), catching refactors that route the base through an intermediate. Also drops the redundant `with pytest.raises(...): raise ...` round-trip block from `test_insufficient_history_error_attributes_required_got` (zero coverage loss; constructor was already exercised). |
| 10  | `2c4c9fa`   | Docs-only — squashed recovery commit combining two earlier stranded reorders of `context/retrieval-log.md` (the F1.1.2 / F1.1.3 entries). Single clean commit; the intermediate SHAs (`0dbc54d`, `a7f3fd5`) are no longer reachable from this branch (they remain only as orphans in the local reflog until GC). Reviewers should not chain-search for them — they are functionally replaced by `2c4c9fa`. |
| 11  | `65add69`   | F2 step **2.2** — `name` attribute test. Extends `tests/unit/indicators/test_protocols.py` with `test_indicator_protocol_attr_name` (pines the literal "sin instanciar mypy" DoD via 4 assertions: class-level `FakeIndicator.name == "fake"`, `isinstance(..., str)`, `not callable(...)` regression-guard against future no-arg-method refactor, `'name' in Indicator.__annotations__` Protocol-class declaration lookup). The module docstring now covers both `.1` and `.2` DoDs. The `FakeIndicator` class docstring extends the deferred round-2 Q7 nit (Policy vs Structural boundary: Protocol does NOT enforce InsufficientHistoryError — that's a policy decision of real implementations, not of the Protocol itself). |

> **Resolution of the optional history cleanup**: `a7f3fd5` (the recovery commit referenced in earlier drafts) was squashed into `2c4c9fa` by `git reset --hard 270e6e15` + `cherry-pick 6c4b68b`, producing a clean 11-commit reachable chain. The retrieval-log.md's F1.1.2 (01:30) entry now precedes F1.1.3 (03:00) — verified at line 83 vs line 85. This is a **local-only rebase**; remote origin is still on the older `6c4b68b` head. **Push command** (informational): `git push --force-with-lease=origin/feature/tsk-200-indicators-interface:6c4b68b` will publish the cleaned history. The `:6c4b68b` lease guard fails safely if a teammate has pushed to the branch meanwhile.

### Definition of Done (exit criterion, restated)

> *Given an OHLCV, the motor returns all activated indicators without global mutable state.  A function `compute(ohlcv, params) -> DataFrame or scalar`.  Cache por `(indicator, params, last_candle_ts)`.  Property tests with `hypothesis`.*

### Archivos creados (5 spec docs, mirroring canonical TSK-103 SDD layout)

| #  | Spec                                       | Purpose                                |
| -- | ------------------------------------------ | -------------------------------------- |
| 01 | `docs/specs/TSK-200-indicators-interface/01-requirements.md` | User stories (`compute(ohlcv,params)`), acceptance criteria, exit criteria from `config/indicators.yaml`. |
| 02 | `docs/specs/TSK-200-indicators-interface/02-bdd.md` | BDD scenarios in Gherkin (snapshot shape, registry ordering, cache invalidation by `last_candle_ts`, hypothesis property tests as BDD examples). |
| 03 | `docs/specs/TSK-200-indicators-interface/03-specify.md` | Interface contract: `Indicator` Protocol (mirror of scanner's `Filter`), `IndicatorOutput` frozen+slotted dataclass, `IndicatorRegistry` registry pattern, `IndicatorCache` invalidation semantics. |
| 04 | `docs/specs/TSK-200-indicators-interface/04-plan.md` | File-level plan: 5 new modules (`types.py`, `protocols.py`, `registry.py`, `cache.py`, `__init__.py`), test layout, dependencies, ADRs. |
| 05 | `docs/specs/TSK-200-indicators-interface/05-tasks.md` | Atomic implementation steps for `06-implement-next.md` consumption: min 7 sub-tasks with verifiable DoD per task (now including the F1.1 DoD note re: uv run vs python -c). |

### Archivos creados (F1 + F2 commits — code)

| File                                                       | Purpose                                                                 |
| ---------------------------------------------------------- | ----------------------------------------------------------------------- |
| `src/trading_bot/indicators/types.py`                      | `IndicatorOutput` (frozen + manual `__slots__` for bpo-46268 compat) + `__post_init__` finiteness guard + `IndicatorParams = Mapping[str, Any]` alias. |
| `src/trading_bot/indicators/exceptions.py`                 | `IndicatorError(Exception)` base + `RegistryFrozenError` + `InsufficientHistoryError(required, got)` + `ParamsHashError`. |
| `src/trading_bot/indicators/protocols.py`                  | `@runtime_checkable class Indicator(Protocol)` with `name: str` + `compute(ohlcv, params) -> IndicatorOutput` method body `...` PEP 544 caveat documented. |
| `tests/unit/indicators/__init__.py`                        | Empty package marker (tests-as-package mirror of `src/`). |
| `tests/unit/indicators/test_types.py`                      | 7 tests: 2 frozen/slots + 3 `__post_init__` finiteness + 2 exception hierarchy. |
| `tests/unit/indicators/test_protocols.py`                  | 2 tests: `test_indicator_protocol_runtime_checkable` (PEPP 544 attribute caveat verified) + `test_indicator_protocol_attr_name` (class-level `name` access without instantiation). |
| `pyproject.toml`                                           | `pythonpath = ["src"]` under `[tool.pytest.ini_options]` for cross-shell `python -c` compatibility. |
| `docs/specs/TSK-200-indicators-interface/05-tasks.md`       | TSK-200.1.1 DoD cell rephrased (`uv run python -c` form); F-tier attribution convention (`per code-review de F1`, no SHA coupling). |
| `context/retrieval-log.md`                                 | Append-only entries for F1.1.x + F2.2.x commits, plus the recovery-squashed entry at `2c4c9fa`. |

### Decisiones arquitectónicas preview

- **ADR-0013** (to be signed pre-`06-implement-next` / final-F5 PR): `typing.Protocol` + `@runtime_checkable` for `Indicator` contract, **not** ABC — duck-typing for plugin-style indicators (e.g. third-party TA-Lib wrappers in TSK-206+).
- **`IndicatorOutput`** as frozen+slotted dataclass with `__post_init__` NaN/inf guard — `dict[str, float]` payload (multi-value indicators like MACD without changing the signature).
- **`IndicatorRegistry`** mirrors the F2 `FilterRegistry` pattern verbatim — `.freeze()` post-arranque, deterministic insertion order via `OrderedDict`, no implicit ordering by `compute` speed or name.
- **`IndicatorCache`** = LRU-256 + `threading.Lock` per-instance + **per-instance per-key invalidation** on `last_candle_ts` advance (no global purge to avoid backtest vs live trade collisions).
- **Exception hierarchy** rooted at `IndicatorError(Exception)` (NOT `BaseException`) — pine the bypass against silent `KeyboardInterrupt` / `SystemExit` absorption. `MRO[0:2]` walk in tests reinforces this contract.
- **`__slots__` workaround**: Manual `__slots__` declaration in `IndicatorOutput` class body works around `bpo-46268` (CPython 3.10-3.11 bug where `@dataclass(slots=True, frozen=True)` raises `TypeError: super(type, obj)` because the synthetic slots-base class isn't a valid supertype for the dataclass instance). Future-proofing target: re-test when Python 3.12 or 3.13 becomes the project's pinned interpreter; the bug may have been fixed.

### Quality gates (this PR)

- F1 + F2 commits (`35f62218` through `65add69`) add code under `src/trading_bot/indicators/` (`types.py`, `exceptions.py`, `protocols.py`) and `tests/unit/indicators/` (`__init__.py`, `test_types.py`, `test_protocols.py`). Validation passed:

  - `uv run ruff check src/trading_bot/indicators tests/unit/indicators` → **all checks passed**.
  - `uv run ruff format --check same` → **7 files already formatted**.
  - `uv run mypy --strict same` → **Success: no issues found** in 6 source files + 2 test files.
  - `uv run pytest tests/unit/indicators -v` → **9 tests passed** (2 frozen/slots + 3 `__post_init__` finiteness + 2 exception hierarchy + 1 Protocol runtime_checkable + 1 `name` attribute access).
  - `uv run pytest -m "not slow and not market" --co -q` → **387 tests collected** (no regressions across the project; the 9 new tests bring the indicators total from 378 baseline through 380 → 383 → 385 → 386 → 387 as each F1.x + F2.x lands).
  - Runtime introspection confirms defense-in-depth contracts:
    - `IndicatorError.__mro__[0] is IndicatorError` + `__mro__[1] is Exception` (hard MRO pin pines the BaseException bypass).
    - `except IndicatorError:` does NOT capture `KeyboardInterrupt` / `SystemExit` (verified live via `uv run python -c raise + try/except`).
    - `isinstance(GoodFake(), Indicator) is True` (DoD); `isinstance(NoCompute(), Indicator) is False` (PEP 544 contract); `isinstance(BadCompute(), Indicator) is True` (PEP 544 does NOT verify signature, only callable presence).
    - `'name' in Indicator.__annotations__` (Protocol declares the attribute without instantiation).
- The doc-spec files (`02-bdd.md` etc.) use plain Gherkin + Markdown with no executable code; they don't perturb the ruff/mypy/pytest gate surface.
- `pyproject.toml: pythonpath = ["src"]` is pytest-only; coverage, ruff, and mypy do not read it. Verified locally — the trio above confirms.

### Sprint + cross-links

- Sprint: `sprint-003` (`in_progress`).
- Roadmap: `tasks/roadmap.md` Fase 2 entry for TSK-200 stays `in_progress` until `06-implement-next.md` consumes the tasks file and ships the implementation PR (F3-F5).
- Related: TSK-110 (BDD wiring for scanner), TSK-104 (F2/F3 backtest) — both share the registry-pattern idiom.
- Changelog (this PR):
  - **F1.1.1** — package baseline (`5af4ad7d`).
  - **F1.1.2** — IndicatorOutput frozen+slots + IndicatorParams alias (`382b08a`).
  - **F1.1.3** — `__post_init__` finiteness (`3eb81f5` + `98d5aff`).
  - **F1.1.4** — exception hierarchy (`4d2cf55c` + `270e6e15`).
  - **F2.2.1** — Indicator Protocol (`5f2bf28`).
  - **F2.2.2** — name attribute test (`65add69`).
- **Upcoming follow-up PRs** (not in this one):
  - **F2.2.3** — `compute_params_hash` with `json.dumps(sort_keys=True, default=str)` (3 tests in `test_params_hash.py`). *Next step.* Per spec NOTA on row .3, `compute_params_hash` may live in `cache.py` (F3) — picking the standalone location here keeps the F2 gate clean; the F3 PR can re-export if convenient.
  - **F3** — `IndicatorRegistry` (OrderedDict-backed; freeze idempotent; `register` post-freeze → `RegistryFrozenError`; `get`/`__contains__`/`__len__`) + `IndicatorCache` (LRU-256 + `threading.Lock`; `get_or_compute` with post-compute race-stick; `invalidate_on_new_candle(ts)` purging entries with `ts < new_ts`; threading pool test).
  - **F4** — `EmaIndicator` (frozen dataclass with `name: str = "ema"`; EMA-9 formula; `InsufficientHistoryError` for `len(ohlcv) < period`; TypeError for non-Mapping params) + BDD pytest-bdd wiring (17 scenarios) + cross-layer AST enforcement.
  - **F5** — `__init__.py` explicit exports + ADR-0013-Fase2 sign-off + tasks/sprint-003 status flip + 6 quality gates wiring (`docs/ci.md` §3).
