# MA-1 Traceability Matrix

No gate is marked PASS without an executed test or independently reproduced
artifact.

| Gate | Requirement | Implementation | Verification | Result |
|---|---|---|---|---|
| MA1-01 | Typed AgentBus | `multi_agent/bus.py` accepts `AgentMessage` | direct route/subscription test | PASS |
| MA1-02 | Registered identity enforcement | enabled `AgentRegistry` lookup | unknown identity and handler tests | PASS |
| MA1-03 | Capability enforcement | `WRITE` sender and `READ` receiver/subscriber checks | unauthorized capability/topic tests | PASS |
| MA1-04 | Direct routing | `direct_route()` delegates to validated FIFO publish | direct route test | PASS |
| MA1-05 | Broadcast | deterministic sorted fan-out with receiver-specific IDs | broadcast test | PASS |
| MA1-06 | Reply correlation | pending request plus `causation_id`/receiver validation | request/reply test | PASS |
| MA1-07 | Evidence binding | same-run evidence required for proposal/critique/response | evidence tests and fixture E2E | PASS |
| MA1-08 | Trace propagation | message/evidence/artifact trace must match runtime trace | trace and artifact assertions | PASS |
| MA1-09 | Immutable blackboard history | append-only versions and defensive deep copies | mutation/idempotency test | PASS |
| MA1-10 | Deterministic replay | ordered messages rebuild session and blackboard state | replay equality test | PASS |
| MA1-11 | Duplicate protection | identical IDs idempotent; conflicting IDs rejected | duplicate message test | PASS |
| MA1-12 | Timeout | deadline transitions session to `TIMEOUT` | timeout test | PASS |
| MA1-13 | Max-round termination | bounded counter transitions to `MAX_ROUNDS` | max-round test | PASS |
| MA1-14 | Malformed fail-closed | non-`AgentMessage` rejected before append | malformed message test | PASS |
| MA1-15 | Unauthorized fail-closed | identity/topic/capability/evidence violations rejected | fail-closed matrix test | PASS |
| MA1-16 | Trading capability equals zero | no risk/broker/live imports or calls | architecture test and side-effect counters | PASS |
| MA1-17 | Committed reproducibility | MA-0 `6573215`; MA-1 `53bc666`; 32 artifacts tracked | clean checkout and closure guard | PASS |
| MA1-18 | Independent verification | detached checkout from final commit | fresh focused, affected, smoke, Ruff, Mypy checks | PASS |
| MA1-19 | FALSE_SUCCESS equals zero | baseline full-suite debt reported, not hidden | full-suite result | PASS |

## Executed evidence

- `uv run pytest tests/unit/multi_agent -q` — **28 passed**
- `uv run pytest tests/unit/test_dependency_closure_guard.py -q` — **3 passed**
- `uv run pytest tests/unit/scanner tests/unit/paper tests/unit/research/test_strategy_router.py -q` — **165 passed**
- `uv run ruff check src/trading_bot/multi_agent tests/unit/multi_agent scripts/validate_multi_agent_foundation.py` — **PASS**
- `uv run mypy src/trading_bot/multi_agent tests/unit/multi_agent scripts/validate_multi_agent_foundation.py` — **PASS**, 24 files
- `uv run python scripts/validate_multi_agent_foundation.py` — **PASS**
- `uv run pytest -q` in final detached checkout — **609 passed, 1 baseline failure**

## Baseline debt

`tests/unit/config/test_settings.py::test_load_settings_happy_path` expects
`settings.exchange.id == "binance"`, while the current repository resolves
`"bybit"`. This reproduced in the independent detached checkout and is outside
MA-0/MA-1. No configuration was changed.
