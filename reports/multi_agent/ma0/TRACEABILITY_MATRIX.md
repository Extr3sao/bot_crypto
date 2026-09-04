# MA-0 Traceability Matrix

No row is marked PASS without an executed test or smoke artifact.

| REQ | ACC | RFC/WP | Implementation | Test | Execution | Evidence |
|---|---|---|---|---|---|---|
| Strict models | MA0A-001/003 | MA-001 / 0A-01 | `contracts/*.py` | `test_manifest_is_strict_frozen_and_versioned` | `pytest tests/unit/multi_agent -q` | 19 passed |
| Immutable models | MA0A-002 | MA-001 / 0A-01 | `ConfigDict(frozen=True)` | manifest/proposal round-trip tests | focused pytest | PASS |
| Confidence bounds | MA0A-004 | MA-001 / 0A-01 | `AgentMessage.confidence` | confidence unit/property tests | focused pytest | PASS |
| Aware timestamps | MA0A-005 | MA-001 / 0A-01 | message/evidence/proposal validators | naive timestamp tests | focused pytest | PASS |
| PIT ordering | MA0A-006 | MA-001 / 0A-01 | temporal validators and `is_valid_at` | evidence/message/proposal tests | focused pytest | PASS |
| Explicit NO_TRADE | MA0A-007 | MA-001 / 0A-01 | `TradeDirection.NO_TRADE` | proposal round-trip test | focused pytest + smoke | PASS |
| Safe capability representation | MA0A-008 | MA-001 / 0A-01 | declaration and policy restrictions | forbidden capability tests | focused pytest + smoke | PASS |
| Single proposal vocabulary | MA0A-009 | MA-0001 / 0A-01 | `TradeProposal`; existing research `Proposal` retained as distinct codegen input | RFC and requirements review | source audit | PASS / no duplicate runtime contract |
| No dependency addition | MA0A-010 | MA-001 / 0A-01 | stdlib + existing Pydantic only | import architecture test | Ruff/Mypy | PASS |
| Exact version registration | MA0B-001/005 | MA-002 / 0B-01 | `AgentRegistry` | version/duplicate test | focused pytest + smoke | PASS |
| Lifecycle transitions | MA0B-003/004 | MA-002 / 0B-01 | `_ALLOWED_TRANSITIONS` | lifecycle test | focused pytest | PASS |
| Default deny | MA0B-007/008/009 | MA-002 / 0B-02 | `CapabilityRegistry` | unknown/default-deny tests | focused pytest | PASS |
| Deny precedence | MA0B-010 | MA-002 / 0B-02 | `denials` checked before grants | deny-wins test | focused pytest | PASS |
| Permanent restrictions | MA0B-011/012/013 | MA-002 / 0B-02 | `_ALWAYS_DENIED` | direct and registry grant tests | focused pytest + smoke | PASS |
| Builder/verifier separation | MA0B-014/015 | MA-002 / 0B-03 | `VerificationMetadata` | identity collision test | focused pytest + smoke | PASS |
| Runtime boundary | MA0A/0B architectural | MA-001/002 | no forbidden imports | architecture test | focused pytest + Ruff/Mypy | PASS |
| Real new-code execution | MA0 definition of done | MA-001/002 | `validate_multi_agent_foundation.py` | deterministic smoke | `uv run python scripts/validate_multi_agent_foundation.py` | `RUN_REPORT.json`, PASS |
| Affected runtime regression | quality gate | MA-001/002 | unchanged scanner/paper path | 165 focused tests | `uv run pytest ...` | PASS |
| Full regression | quality gate | MA-001/002 | repository-wide | full pytest | `uv run pytest -q` | INCOMPLETE/FAIL: 599 passed, 2 unrelated/tracking failures |
