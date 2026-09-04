# MA-0 Foundation Validation Run

## Result

```text
RESULT: PASS
MA_0_FOUNDATION: REPRODUCIBLE_FOUNDATION_READY
MODE: PAPER_OFFLINE_ONLY
RUN_ID: ma0-smoke-run
FALSE_SUCCESS: 0
LIVE_ACTIONS: 0
PRODUCTION_ACTIONS: 0
RISK_OVERRIDES: 0
NEW_RUNTIME_DEPENDENCIES: 0
```

## Commits and tracking

- MA-0 foundation commit: `6573215adad29247914c07d5a2eb302582d41292`
- Final MA-1 verification commit: `53bc66679e6418ac7bc8fce742910525d81567dc`
- All MA-0 source, tests, RFC/evidence artifacts, and validator tracked.
- `INTERNAL_IMPORTED_MODULES_UNTRACKED = 0`
- `EXTERNAL_WORKTREE_DEPENDENCIES = 0`

## Fresh clean-checkout verification

A detached checkout was created directly from the MA-0 foundation commit and
ran:

| Command | Result |
|---|---|
| `uv run pytest tests/unit/multi_agent -q` | PASS — 19 passed |
| `uv run pytest tests/unit/scanner tests/unit/paper tests/unit/research/test_strategy_router.py -q` | PASS — 165 passed |
| `uv run pytest tests/unit/test_dependency_closure_guard.py -q` | PASS — 3 passed |
| `uv run ruff check src/trading_bot/multi_agent tests/unit/multi_agent scripts/validate_multi_agent_foundation.py` | PASS |
| `uv run mypy src/trading_bot/multi_agent tests/unit/multi_agent scripts/validate_multi_agent_foundation.py` | PASS — 18 source files |
| `uv run python scripts/validate_multi_agent_foundation.py` | PASS |

The final detached checkout from the MA-1 commit additionally passed MA-1
focused tests, closure, affected runtime tests, scoped Ruff, and scoped Mypy.

## Baseline debt

A full fresh regression from the final detached MA-1 checkout reports:

```text
609 passed, 1 failed
```

`tests/unit/config/test_settings.py::test_load_settings_happy_path` expects
`binance`, while current settings resolution returns `bybit`. This is
independently reproduced baseline debt outside MA-0/MA-1. No configuration or
trading-runtime code was changed to force a green result.
