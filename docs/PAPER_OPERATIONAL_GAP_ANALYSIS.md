# PAPER_OPERATIONAL_GAP_ANALYSIS

> HEAD `5e6f963` audit. Each gap: CLAIM + SOURCE + EVIDENCE + DECISION. No speculative RFCs.

## GAP-R1 — Startup reconciliation is runtime-unreachable (ORPHAN)

> **RESOLVED (hardening phase, commit `daf54af` + `c21a44a`)**: durable
> state store + StartupReconcilerV4 wired into the paper entrypoint;
> RESTORE_EXACTLY policy with equity-identity check, fail-closed corrupt
> file handling, intent-ledger exactly-once across restarts, risk exposure
> sync. Contract: `docs/STARTUP_RECONCILIATION_CONTRACT.md`; evidence:
> `tests/unit/paper/test_paper_recovery.py` (10 cases) + live RUN-C on
> Binance testnet. V1/V3 orphan modules remain on disk (retire in cleanup).

Original finding (for the record):

- **CLAIM**: broker-vs-journal startup alignment existed only as dead code; a resumed paper session could not guarantee position consistency.
- **SOURCE**: `src/trading_bot/paper/reconciliation.py` (V1, CLOSE_ORPHANED with `pnl=0` breakeven fill), `src/trading_bot/paper/startup_recovery.py` (V3: RESTORE_FROM_JOURNAL / fee-aware conservative close).
- **EVIDENCE**: zero imports in runtime or tests (grep `from trading_bot.paper.reconciliation import` → none; `startup_recovery` → none).
- **DECISION**: superseded by the V4 implementation above (durable-state restore instead of journal-restore; V1's fake-`pnl=0` policy rejected).

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

## GAP-R5 — RESUME-01 idempotent checkpoint resume — RESOLVED (hardening phase)

- **EVIDENCE NOW**: execution boundary idempotent (verifier GATE-L5-08) AND process restart idempotent — the durable intent ledger restores `sent_cloids` before the first post-restart cycle; crash-before-fill retries are suppressed (unknown outcome fails closed); live proof on real data: RUN-B/RUN-D duplicate suppression, RUN-C post-restart zero re-execution.
- **DECISION**: closed by the same work package as GAP-R1 (V4).

## External pattern adoption matrix (EXTERNAL_DELTA_2026 summary)

| Pattern | Project today | Verdict |
| --- | --- | --- |
| PIT-01 point-in-time everywhere | Enforced 4× on the only dated path (sanitizer → closed-candle filter → trim → context validation); forming candles excluded on REAL data (PIT capture) | HARDENED (executed evidence, real feed) |
| MEMORY-TIME-01 | No memory inputs | DEFER + guardrail (GAP-R3) |
| FAIL-CLOSED-01 ambiguous output | No LLM outputs to parse; deterministic components raise → reject+record | ALREADY_SATISFIED by construction |
| RESUME-01 | Execution boundary + process restart idempotent (durable intent ledger) | RESOLVED (`daf54af`; RUN-C/D) |
| BUDGET-01 | No agent phases | DEFER (GAP-R4) |
| PORTFOLIO-CONTEXT-01 | Risk consumes restored/live broker equity AND position map each cycle | HARDENED (`c21a44a`; live veto on restored exposure) |
| Agent registry/AgentMessage/blackboard/debate | Absent | DO_NOT_ADOPT now (no measured gap; §18 forbids adding agents without one) |
| Replay by run_id | Deterministic engine + fingerprints + verifier; no run_id replay API | DEFER P2 (recorded, not promised) |

## Sizing determinism note (DEF-3 follow-up)

`_compute_position_size` clamps `max_remaining` without re-checking the minimum — an exposure-capped notional below `min_order_notional_usdt` can still be approved. Conservative direction (smaller risk), deterministic, no action this session; recorded as P2 hygiene with a suggested explicit early-return for readability.
