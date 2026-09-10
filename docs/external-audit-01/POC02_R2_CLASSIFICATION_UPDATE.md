# CAMPAIGN CLASSIFICATION UPDATE — POC-02-R2-direction-arbitration-01
# (POC02-R2-GOVERNANCE-RECONCILIATION-AND-ALPHA-SEARCH-01, TRACK B/B1)

Retains and supersedes the classification evidence of
`POC02_CAMPAIGN_CLASSIFICATION.md` (predecessor) with the R2-specific record.

## TRACK B — Classification (multiple labels retained, none deleted)

| Class | Applies | Evidence |
| --- | --- | --- |
| CLEAN_OBSERVATIONAL_CAMPAIGN | NO | Coverage: day 1 = 0.0028 vs ≥ 0.80 contract; observation time is a tiny fraction of the window |
| DEGRADED_OBSERVATIONAL_CAMPAIGN | **YES** | DEF-R2-001 (21 accepts failed execution silently pre-repair), DEF-R2-003 (validity contract bypass, amended INVALID), one pre-enforcement duplicate intent (2 economic orders) — campaign continues with degraded observation quality |
| DIAGNOSTIC_CAMPAIGN | **YES** | Primary value delivered: direction-arbitration deadlock gone (telemetry), Risk behavior diagnostics (10 raw rejects incl. max_positions), Shadow mechanics armed (10 captures), regime attribution labels recorded |
| INVALID_FOR_PERFORMANCE_CERTIFICATION | **YES** | Zero valid counted days under the enforced ≥ 0.80 contract → no frequency, no profitability, no edge claims possible |

## B1 — Certification authority

| Claim | R2 may certify? | Scope detail |
| --- | --- | --- |
| runtime reachability (candidate→arbitration→critique→decision→verifier→Risk→PaperBroker) | **YES (post-repair)** | 4 natural executions post-`007b691`; pre-repair path was broken (DEF-R2-001) |
| direction arbitration | **YES (composition, whole campaign)** | Deterministic arbiter active every window; no structural deadlock recurrence; adversarial suite frozen (ADR-DIR-0001) |
| Risk behavior | **DIAGNOSTIC ONLY** | 10 raw rejects (max_positions), accepts/opens reconciliation complete; NOT a certification of risk policy optimality |
| Shadow mechanics | **YES (mechanics)** | 10 captures, 0 resolved (48h horizon not yet reached), isolation counters 0 — mechanics proven, outcomes pending |
| execution exactly-once | whole campaign: **NO** — post-arm: **YES** | Pre-enforcement duplicate (BTC-LONG ×2 on 09-10) vs `R2_INTENT_LEDGER` enforcement (max=1 post-arm) |
| frequency KPI | **NO** | COMPLETED_VALID_DAYS = 0 under enforced contract; FREQUENCY_DAY1 = NOT_EVALUABLE_INVALID_DAY |
| profitability | **NO** | 4 opens, 0 closes, zero valid days |
| strategy edge | **NO** | Momentum LEGACY_CURRENT_CAMPAIGN_ONLY; retro cells FAILED/INSUFFICIENT; FUTURE_PAPER_ELIGIBLE = NONE |

Historical campaign-wide claims remain bounded by the three registered defects
(DEF-R2-001, DEF-R2-002 telemetry components, DEF-R2-003); post-arm claims are
limited to exactly-once enforcement, execution reachability, and arbitration stability.
