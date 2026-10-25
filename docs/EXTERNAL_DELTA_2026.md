# EXTERNAL_DELTA_2026

> Limited external review (sandbox: search-result level, no repo clones). Authority: official sources > papers > experiments. Nothing copied without a demonstrated gap.

## Sources consulted

| SOURCE_ID | URL | TYPE | VERSION/COMMIT | PATTERN | EVIDENCE | RELIABILITY | DECISION |
| --- | --- | --- | --- | --- | --- | --- | --- |
| EXT-001 | https://github.com/langchain-ai/langchain (issues #14947; `handle_parsing_errors` reference docs) | official code/docs | current (2026) | FAIL-CLOSED-01: unparseable agent output must not become a silent HOLD/valid signal | search snippets + official docs pages | HIGH (official) | Pattern already satisfied: no LLM output enters the decision path; deterministic components raise → recorded rejection. Guardrail recorded if LLM phases are added |
| EXT-002 | https://arxiv.org/html/2606.29771v1 (CLQT: Closed-Loop Cost-Aware Time-Gated) | paper | 2026-06 | Profit-mirage / time-gating; market-regime dependence of LLM-agent evaluation | abstract via search | MEDIUM | Confirms PIT + cost-aware gating direction the repo already enforces; no new implementation triggered |
| EXT-003 | https://papers.ssrn.com/sol3/Delivery.cfm/7262158.pdf?abstractid=7262158 (OpenPM: auditable point-in-time evaluation for LLM trading agents) | paper | 2026 | PIT evaluation as engineering artifact; reproducible eval failures (data leakage, cost omission) | search snippet | MEDIUM | Aligns with existing fingerprint + PIT gates; DEFER — adopt its eval-audit checklist when research evals are rerun |
| EXT-004 | TradingAgents / LangGraph / Microsoft Agent Framework | official repos | current | Agent orchestration, checkpoint resume, bounded execution | not directly fetched in-sandbox (network-limited) | LOW-MEDIUM this session | No code copied. Patterns extracted only where a measured repo gap exists (see gap analysis). BUDGET-01 + RESUME-01 recorded as preconditions for any future agent phase |

## Conclusions

1. No external pattern justifies adding agents, frameworks, or a second orchestrator to the current runtime (§18 respected).
2. The two patterns that map to real code today (PIT-01, FAIL-CLOSED-01) are already satisfied and executed-evidenced on clean HEAD.
3. The two patterns that map to planned code (BUDGET-01, MEMORY-TIME-01) are recorded as adoption preconditions (GAP-R4/GAP-R3) — adopting the guardrail BEFORE building the feature, not after an incident.
4. RESUME-01's execution-boundary half is already idempotent; the process-restart half is GAP-R1.

`source_registry.md` consolidated here as the canonical registry (single-doc policy; no duplication).
