# Verification

Environment: isolated worktree `audit/profitability-diagnostics-01`, base `ee58c7a5a0a46cf6af17dc9606118ef0f1fcd335`, Python from the repository virtual environment.

| Criterion | Evidence | Result |
| --- | --- | --- |
| AC-001 | JSON validation checked all twelve numbered JSON artifacts plus the remaining required Markdown/JSON reports | PASS |
| AC-002 | Funnel encodes unrecorded signal/router/critic/metaranker counts and incomparable unit transitions as `UNKNOWN` | PASS |
| AC-003 | `test_generation_is_non_interfering_and_deterministic` snapshots campaign inputs before/after two runs | PASS |
| AC-004 | `pytest tests/unit/diagnostics/test_profitability_diagnostics.py -q`: 3 passed | PASS |
| AC-005 | This file, generated run report, and report input SHA-256 snapshots | PASS |

Commands run:

```text
PYTHONPATH=src ...python.exe -m pytest tests/unit/diagnostics/test_profitability_diagnostics.py -q
# 3 passed
...python.exe -m ruff check scripts/profitability_diagnostics tests/unit/diagnostics
# All checks passed
PYTHONPATH=src ...python.exe scripts/profitability_diagnostics/run.py
# state_before_equals_after=true
```

Residual risks: the R2 evidence persists no matched realized outcomes for 11 Shadow risk rejections, no closed trades, and no per-stage Critic/MetaRanker counters. This checkpoint therefore makes no profitability or overfiltering claim.
