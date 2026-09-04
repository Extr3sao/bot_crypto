# MA-0 Foundation Validation Run

## Result

```text
RESULT: PASS
MODE: PAPER_OFFLINE_ONLY
RUN_ID: ma0-smoke-run
FALSE_SUCCESS: 0
LIVE_ACTIONS: 0
PRODUCTION_ACTIONS: 0
RISK_OVERRIDES: 0
NEW_RUNTIME_DEPENDENCIES: 0
```

## Environment

- Repository commit before implementation: `a24da88445042a74de6ef3e5489446c2be1de61c`
- Validation checkout commit: `81670670711705b033fc429f62a4138504cdaf67`
- Python executable used by smoke: `Python 3.11.15` (project baseline shell reported `Python 3.14.3`)
- uv: `0.11.26`
- Runtime mode: offline foundation validation only
- No credentials, exchange clients, paper broker, risk manager, or live path invoked

## Contracts tested

- `AgentManifest`
- `DeclaredCapabilities`
- `AgentMessage`
- `AgentEvidence`
- `TradeProposal`
- `TraceContext`
- `VerificationMetadata`

## Registries tested

- `AgentRegistry`: registration, exact version resolution, probation transition
- `CapabilityRegistry`: explicit READ grant and production-action denial

## Smoke evidence

The validator created and round-tripped a `NO_TRADE` proposal, linked it to a
message and SHA-256 evidence, registered an agent version, granted only READ,
and rejected `PRODUCTION_ACTION`. Builder and verifier identities were distinct.
The machine-readable result is `RUN_REPORT.json`.

## Executed commands

| Command | Result |
|---|---|
| `uv run pytest tests/unit/multi_agent -q` | PASS — 19 passed |
| `uv run ruff check src/trading_bot/multi_agent tests/unit/multi_agent scripts/validate_multi_agent_foundation.py` | PASS |
| `uv run mypy src/trading_bot/multi_agent tests/unit/multi_agent scripts/validate_multi_agent_foundation.py` | PASS — 18 source files |
| `uv run pytest tests/unit/scanner tests/unit/paper tests/unit/research/test_strategy_router.py -q` | PASS — 165 passed |
| `uv run python scripts/validate_multi_agent_foundation.py` | PASS — JSON report written |
| `uv run pytest -q` | INCOMPLETE/FAIL — 599 passed, 2 unrelated/pre-existing failures |

## Full regression findings

1. `tests/unit/config/test_settings.py::test_load_settings_happy_path` expects
   `binance`, while the current repository configuration resolves `bybit`.
   This is outside MA-0 and no runtime/config behavior was changed.
2. `tests/unit/test_dependency_closure_guard.py::test_all_imported_internal_modules_are_tracked`
   reports the newly created MA-0 files as untracked. This is expected before
   the implementation is staged/committed and is a repository tracking gate,
   not a contract defect.

The full-repository Ruff/Mypy commands also remain non-clean in unrelated
existing files; scoped MA-0 Ruff/Mypy are clean. The smoke JSON records the
current commit, Python/uv environment, tested contracts, registry checks,
errors, and evidence paths. These findings are not converted into PASS claims.
MA-0 is not certified until a clean tracked snapshot reruns the full
regression and dependency-closure gate.
