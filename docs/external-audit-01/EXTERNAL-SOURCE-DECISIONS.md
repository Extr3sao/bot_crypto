# EXTERNAL SOURCE DECISIONS — EXTERNAL-AUDIT-RECONCILIATION-01

Checkpoint: EXTERNAL-AUDIT-RECONCILIATION-01
Directive 17: record decisions; no framework wholesale adoption.

| Source | Decision | Scope |
| --- | --- | --- |
| Vibe-Trading | **SELECTIVE_PATTERN_ONLY** | Prompt/pattern inspiration only; no code adoption |
| polybot-rewards | **SELECTIVE_EXECUTION_PATTERN_ONLY** | Execution reliability patterns (idempotent submit, reconciliation flow) as design reference for EXECUTION-RELIABILITY-01 |
| vn.py | **CONFORMANCE_PATTERN_ONLY** | Adapter contract taxonomy inspiration for RFC-EXCHANGE-CONFORMANCE-01; explicitly NOT imported |
| Fincept | **FUNCTIONAL_BENCHMARK_ONLY** | Functional comparison baseline only |
| ripwire | **TOOLING_PILOT_ONLY** | Possible dev-tooling pilot; no runtime adoption |
| polymarket_lp_tool | **DEFER_MAKER_ONLY** | Deferred; market-making patterns only, not applicable to current scope |
| AutoHedge | **REJECT** | No adoption |
| RuneDn bot | **REJECT** | No adoption |

## Enforcement

- No wholesale framework adoption of any source.
- All adopted ideas enter as patterns through the SDD command chain
  (`.ai/commands/`), never as direct code lifts.
- vn.py: contract vocabulary only — zero imports (verified: no `vnpy` in
  `pyproject.toml` dependencies).
