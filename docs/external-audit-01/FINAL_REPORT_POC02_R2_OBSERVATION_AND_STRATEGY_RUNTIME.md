# FINAL REPORT — POC02-R2-OBSERVATION-AND-STRATEGY-RUNTIME-01 + CARRY-FUNDING-DEEP-01 + FRONTEND-UX-V2

| Field | Value |
| --- | --- |
| **CHECKPOINT** | POC02-R2-OBSERVATION-AND-STRATEGY-RUNTIME-01 (+ CARRY-FUNDING-DEEP-01 + FRONTEND-UX-V2) |
| **POC02_R2** | **ACTIVE — RUN_CLEAN** (daily ops live: gates, idempotent coverage, immutable receipts; no restart, no new identity) |
| **CAMPAIGN_ID** | `POC-02-R2-direction-arbitration-01` (launched 2026-09-09T20:39:22Z, commit `6f0513f…`; runtime commit at observation `618160b…`) |
| **COVERAGE** | NOT_YET_MEASURABLE (day 1 OPEN at checkpoint; closed-days-only authority; ≥ 0.80 contract unchanged) |
| **ARBITRATION_GROUPS** | 4 (all formed from one evaluation each: 1 LONG + 1 SHORT candidate) |
| **LONG_SELECTED / SHORT_SELECTED / NONE_SELECTED** | **0 / 4 / 0** (all by `HIGHER_EVIDENCE_SCORE`; 0 ties, 0 below-floor, 0 sole-candidate) |
| **TRUE_CONFLICTS** | 0 (arbitration is group-scoped by contract; no cross-strategy opposition occurred) |
| **UNRESOLVED_AFTER_ARBITRATION** | **0** — the 33/33 STRUCTURAL_AGENT_DIRECTION_CONFLICT deadlock is gone **naturally** (no threshold touched: `thresholds_optimized=false`) |
| **PAPER_TRADES** | 1 PAPER_OPEN (BTC SHORT, RISK_ACCEPT path); 0 closes yet |
| **RISK_ACCEPT / RISK_REJECT** | 10 / 4 (4× MAX_POSITIONS at preregistered max_open_positions=1; rejection rate computed = 4/14 = 28.6%) |
| **SHADOW_CAPTURES / RESOLVED** | 2 / 0 (48h maturity horizon; resolution pending — no fabricated outcomes) |
| **STRATEGY_RUNTIME_DEFECT** | **DEF-STRAT-RUNTIME-001 maintained** — root cause `COMPOSITION_MISSING` × admission `LEGACY_ONLY`; full map in `strategy_runtime_authority_map.md` |
| **MOMENTUM** | LEGACY (fixture-echo composition; canonical family not invoked on campaign path) |
| **TREND / BREAKOUT / MEAN_REVERSION / VOLATILITY** | NOT_RUNTIME_REACHABLE — COMPOSITION_MISSING (definition/registration/expert OK; router would REJECT: no CONFIRMED admission authority) |
| **STRATEGIES_SAFE_FOR_FUTURE_RUNTIME** | **None activated.** B2 audit passed for all 4 (PIT-safe, contract-compatible) but admission authority is missing → remain NOT_RUNTIME_REACHABLE; B3 composition contract + B4 explicit-router-reason contract prepared (NEW manifest required for any topology change) |
| **CARRY_FUNDING_DEEP** | **EXECUTED** per prereg (manifest immutable: `cfdeb6c9…`; pagination/units/timestamp/PIT/fingerprint/cost contracts verified pre-run) |
| **CARRY_RESULT** | **DISCOVERY_FAIL** — N=769 extreme-funding trades (2019-09→2026-09), net expectancy +0.085%/trade, PF 1.062, Sharpe 0.41, but halves INCONSISTENT, thirds INCONSISTENT, permutation p=0.283 (seed 20260910, N=1000) |
| **PAPER_PROMOTIONS** | **0** |
| **FRONTEND_V2** | **PASS** (`scripts/poc02_r2_dashboard.py`, port 8788; Spanish, human-readable, GET-only) |
| **FRONTEND_LANGUAGE** | **ES** |
| **FRONTEND_ACTIVE_CAMPAIGN** | `POC-02-R2-direction-arbitration-01` by default; selector ACTUAL vs HISTÓRICAS (POC02/POC01 clearly archived); DATOS DESACTUALIZADOS banner with human age (>90 min heartbeat) |
| **DEF_FE_DEC_001** | **FIXED** — rejection rate computed from accepts+rejects (old POC01 view showed 0 for 189/192; R2 view shows 28.6%) |
| **DEF_FE_STRAT_001** | **FIXED SEMANTICS** — strategy rows carry explanatory source semantics (fixture-echo momentum composition declared; no incompatible attribution displayed without provenance) |
| **ADR_TRACEABILITY** | **DUPLICATE_ID found and fixed** — appended decision collided with existing `ADR-0002 (Gestor de dependencias)`; renumbered to **ADR-0032** (next free); no historical evidence deleted |
| **CONFIRMATION_CONSUMED** | **false** |
| **CONFIRMATION_EXECUTIONS** | **0** (window closes 2026-09-22; carry result does NOT unlock anything early) |
| **RISK_CHANGED** | **0** |
| **CURRENT_CAMPAIGN_BEHAVIOR_CHANGED** | **0** (frozen POC02 byte-identical: frozen-hash invariant passes every daily gate; `arbitrate` defaults False) |
| **LIVE_CALLS** | **0** |
| **FALSE_SUCCESS** | **0** |
| **HERMETIC_REGRESSION** | **1182 passed / 0 failed** (includes 17 restored paper_dashboard tests) |
| **STATUS** | **PASS** |
| **NEXT** | **CONTINUE_CLEAN_CAMPAIGN** (daily R2 operation; first valid day closes 2026-09-10) **+ STRATEGY_RUNTIME_DECISION** (admission-gated; no blind activation) **+ SHADOW_ANALYSIS** (when captures resolve) **+ CONFIRMATION_WAIT** (2026-09-22) |

## Acceptance summary

| Group | Verdict |
| --- | --- |
| R2-01..04 (clean campaign, arbitration telemetry, no deadlock, shadow operational) | **PASS** — funnel counters persisted per cycle (A1), arbitration reasons per group (A2), shadow captures live with strict isolation |
| STR-01..04 (authority map, root causes, no blind activation, integration contract) | **PASS** — `strategy_runtime_authority_map.md`; root cause single and evidenced; nothing connected without admission authority |
| CF-01..06 (manifest immutable, depth validated, PIT, no synthetic, frozen execution, promotions 0) | **PASS** — fingerprint pinned pre-run and verified at run; 7670 real rows (2019-09-10→2026-09-09, monotonic, uniform 8h); DISCOVERY_FAIL recorded honestly; 0 promotions |
| UI-01..10 (Spanish, current campaign, historic separation, human funnel, correct rejection rate, consistent attribution, readable reports, read-only) | **PASS** — POST/PUT/PATCH/DELETE → 405; unknown paths → 404; stale banner live |
| GOV-01..05 (Risk unchanged, campaign behavior unchanged, confirmation untouched, LIVE 0, FALSE_SUCCESS 0) | **PASS** |

## Evidence notes

1. **Deadlock disappearance is natural, not engineered**: identical preregistered
   scoring produced SHORT selections on 4/4 groups (each window's downward side
   scored strictly higher); 0 ties, 0 below-floor, 0 forced directions.
2. **First paper trade of the campaign family reached the broker through the
   full repaired chain** (arbitration → critique → decision → verifier → Risk
   ACCEPT → PaperBroker) — the first in POC02/R2 history.
3. **Carry-funding executed exactly as preregistered** and failed its
   consistency/significance gates: recorded as DISCOVERY_FAIL with 0
   promotions; the deep dataset (7670 real funding rows) is persisted and
   fingerprinted for any future preregistration.
4. **Frontend rebuilt around the ACTIVE campaign** with the four home
   questions (¿ESTÁ FUNCIONANDO? ¿ESTÁ GANANDO? ¿ESTÁ OPERANDO SUFICIENTE?
   ¿QUÉ LO ESTÁ BLOQUEANDO?), Spanish funnel, translated risk reasons, human
   reports (date + Informe diario), Shadow explained in plain language, and a
   mandatory PAPER/simulación marker on every view.
