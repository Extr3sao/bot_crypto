# PAPER_OPERATIONAL_GAP_ANALYSIS

> HEAD `5e6f963` audit. Each gap: CLAIM + SOURCE + EVIDENCE + DECISION. No speculative RFCs.

## GAP-R1 — Startup reconciliation is runtime-unreachable (ORPHAN)

- **CLAIM**: broker-vs-journal startup alignment exists only as dead code; a resumed paper session cannot guarantee position consistency.
- **SOURCE**: `src/trading_bot/paper/reconciliation.py` (StartupReconciler, policy CLOSE_ORPHANED with `pnl=0` breakeven fill), `src/trading_bot/paper/startup_recovery.py` (V3: RESTORE_FROM_JOURNAL / fee-aware conservative close, explicitly forbids fake `pnl=0`).
- **EVIDENCE**: zero imports in runtime or tests (grep `from trading_bot.paper.reconciliation import` → none; `startup_recovery` → none).
- **DECISION**: ADOPT P1 as its own work package: wire the V3 policy into `start_paper_trading.py` (before the loop), add unit tests (restore path, orphan-close path, mismatch path), delete/retire the V1 module. NOT implemented this session to keep work packages atomic; in-session reconciliation (the hot path) is already authoritative and executed.

## GAP-R2 — Independent verifier: pre-execution agent-critic layer (design)

- **CLAIM**: no runtime object verifies decisions pre-execution beyond the deterministic gate chain; historical docs left Interpretation A/B ambiguity.
- **SOURCE**: `docs/PAPER_L5_CERTIFICATION.md` (gate chain), `scripts/verify_l5_independent.py` (offline verifier).
- **EVIDENCE**: audit section 3 of CURRENT_RUNTIME_AUDIT.md — single execute_signal call-site gated by RiskManager; reconciliation covers post-execution.
- **DECISION**: REJECT Interpretation B (agent verifier between Decision and Risk — would put a non-deterministic component on the capital path). REJECT immediate Interpretation A adoption. RECORD `docs/RFC_PO_002_VERIFIER_POSITION.md`: deterministic gates = pre-execution verification; agent critique (if adopted) pre-proposal only; independent verifier stays a phase-level harness. Status: ACCEPTED (design), no code change required.

## GAP-R3 — Outcome-memory availability (MEMORY-TIME-01) — not yet applicable

- **CLAIM**: pattern requires that any prior-trade outcome used as context be observable at decision time.
- **SOURCE**: external pattern (TradingAgents-style experience memory); prompt section 8.
- **EVIDENCE**: the canonical cycle consumes NO outcome memory (context = PIT bars + derived features only). Nothing to leak today.
- **DECISION**: DEFER with guardrail: when outcome memory is introduced, it MUST be joined by (a) `outcome_available_at` stamping, (b) an adversarial test injecting an outcome whose result is only observable after decision_time, expecting NO_TRADE/context without that outcome. Registered before implementation, preventing the historical leak class by construction.

## GAP-R4 — BUDGET-01 bounded agent execution — not yet applicable

- **CLAIM**: agentic phases need timeout/max-rounds/retry/termination budgets.
- **EVIDENCE**: the canonical decision path contains ZERO LLM/agent calls (verifier GATE-L5-17: no network/LLM/credential surface). Deterministic components terminate by construction (single pass per symbol).
- **DECISION**: DEFER — becomes ADOPT_P0 the day an LLM phase enters the decision path. The budget contract is recorded here as a precondition of that adoption.

## GAP-R5 — RESUME-01 idempotent checkpoint resume — partially covered

- **CLAIM**: interrupt+resume must not duplicate side effects.
- **EVIDENCE**: covered for the execution boundary by `IdempotencyGuard` + stable `intent_cloid` (verifier GATE-L5-08: duplicate intent → exactly one execution). NOT covered for sessions/processes: a restarted orchestrator re-scans and may re-propose the same intent in a later cycle only if the same (symbol, strategy, direction, bar) recurs — the guard already collapses that; broker additionally refuses same-symbol same-side duplicates. Open remainder = GAP-R1 (journal restore on restart), which is the only true resume hole.
- **DECISION**: NO additional work beyond GAP-R1 for the current runtime shape.

## External pattern adoption matrix (EXTERNAL_DELTA_2026 summary)

| Pattern | Project today | Verdict |
| --- | --- | --- |
| PIT-01 point-in-time everywhere | Enforced 3× on the only dated path (bars); no other dated inputs exist | ALREADY_SATISFIED (executed evidence) |
| MEMORY-TIME-01 | No memory inputs | DEFER + guardrail (GAP-R3) |
| FAIL-CLOSED-01 ambiguous output | No LLM outputs to parse; deterministic components raise → reject+record | ALREADY_SATISFIED by construction |
| RESUME-01 | Execution boundary idempotent; process resume = GAP-R1 | PARTIAL → GAP-R1 P1 |
| BUDGET-01 | No agent phases | DEFER (GAP-R4) |
| PORTFOLIO-CONTEXT-01 | Risk consumes live broker equity/positions each check (`equity` synced from broker; exposure computed from `open_positions`) | ALREADY_SATISFIED for the executed path (single-cycle portfolio) |
| Agent registry/AgentMessage/blackboard/debate | Absent | DO_NOT_ADOPT now (no measured gap; §18 forbids adding agents without one) |
| Replay by run_id | Deterministic engine + fingerprints + verifier; no run_id replay API | DEFER P2 (recorded, not promised) |

## Sizing determinism note (DEF-3 follow-up)

`_compute_position_size` clamps `max_remaining` without re-checking the minimum — an exposure-capped notional below `min_order_notional_usdt` can still be approved. Conservative direction (smaller risk), deterministic, no action this session; recorded as P2 hygiene with a suggested explicit early-return for readability.
