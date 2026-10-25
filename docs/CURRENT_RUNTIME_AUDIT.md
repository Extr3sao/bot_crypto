# CURRENT_RUNTIME_AUDIT — 2026-09-25

> HEAD: `5e6f963` (main). Worktree: CLEAN (porcelain = 0). Branch: main.
> Auditor: this session. Method: authority ranking REAL_RUNTIME > EXECUTION_EVIDENCE > TESTS > SOURCE.

## 1. Reality of the baseline

- Single commit `5e6f963` = origin/main. No WIP, no stashes, no extra worktrees (`git worktree list`: only the primary checkout).
- The critical historical defect (CERT-PO-L5-001: "clean snapshot does not run — 84 untracked files missing from commit") is **resolved**: `git status --porcelain` = 0 on the whole tree ⇒ every file physically present is tracked ⇒ the dependency closure of `src/` is committed. Demonstrated by execution, not assumption:
  - `uv run python scripts/verify_l5_independent.py` → **11/11 PASS** on this clean HEAD (it failed at import time on `2632c8d`).
  - `uv run pytest tests -m "not slow and not market"` → **582 passed, 0 failed, 0 skipped**.
  - `ruff format --check` 239 files OK · `ruff check` 0 findings · `mypy` strict 0 issues / 233 files.
- Orphaned v031–v033 integration tests are excluded by documented collection policy (`tests/integration/conftest.py`), not deleted — classified ORPHAN in the authority map.

## 2. Canonical path — verified by execution

`start_paper_trading.py → PaperOrchestrator → PaperSessionRunner → UniverseScanner → FetcherBarReader(PIT) → CryptoAssetAgentRegistry → StrategyRouter → AlphaFamily → SignalAdapter → CandidatePortfolio → RiskManager → PaperBroker → reconcile_session → reporting`.

Two executed demonstrations on this HEAD:

1. **DEMO-PAPER-01 NO_TRADE leg** (`reports/runs/DEMO-PAPER-01-stdout.log`): 2 sessions, exit 0. Cycle counters: contexts_built=3, router_invocations=3, strategy_invocations=3, signals_generated=0, orders_created=0, rejections=`no_alpha_in_direction:ANY` per symbol. NO_TRADE traversed as a first-class outcome with observable reason (flat synthetic data ⇒ families fail closed).
2. **TRADE leg** (`scripts/verify_l5_independent.py`, 11/11 PASS): composed strictly from canonical components (same `PaperCycleEngine`, same entrypoint composition functions) with deterministic data. Evidence: contexts_built=3, signals=3, risk_accepted=3, **orders_created=3**, lifecycle open → reconcile → SL/TP close → realized_pnl=-1492.02, risk feedback (consecutive_losses=3), idempotency duplicate → 1 execution, PIT future-bar rejection, stale-data rejection, and the full negative matrix (router no-strategy / strategy exception / invalid context / risk reject / risk exception / broker exception → all `orders_created=0` with recorded reason).

## 3. Independent Verifier position (audit item #4)

- **Runtime fact**: there is no `IndependentVerifier` object in the runtime. The verifier exists as `scripts/verify_l5_independent.py` — an **offline certification harness** (BUILDER != VERIFIER satisfied at the phase level: code committed at `5e6f963` was written by a different work session and validated here).
- **Interpretation A vs B**: neither. The runtime implements pre-execution verification as **deterministic gates** inside the decision path (context validation → PIT validation → router validation → adapter validation → mandatory RiskManager approval → broker-only execution), and post-execution verification as **reconciliation** (`broker.reconcile_session`: order→fill accounting, SL/TP exits, equity identity `equity == initial + Σ pnl`, risk PnL feedback) plus startup reconciliation policy (currently ORPHAN — GAP-R1).
- **Decision**: DO NOT insert an LLM/agent verifier between Decision and Risk. For capital-touching flows the current design (deterministic pre-execution gates + deterministic risk veto + post-trade reconciliation) is the correct interpretation. An agent-critic layer, if adopted later, must sit **before** TradeProposal finalization and must never be able to approve size/leverage/limits (deterministic-only domain). Recorded as RFC-PO-002 (deferred, not implemented).

## 4. Temporal integrity

- Single-feeder architecture: scanner and decision cycle read the SAME source (one provider, one quota). `FetcherBarReader` reads `timestamp <= as_of`; `trim_to_pit` enforces it again (defence in depth); `BaseCryptoAssetAgent.build_context` slices a third time and validates `window_end_ts <= context.ts` (raises on violation).
- Future-data, stale-data, and empty-history adversarial cases are executed by the verifier (PASS on clean HEAD).
- HTF: the `htf_pit` helper exists in market-data (`b88217c`); the **canonical paper path does not consume HTF features today** (single-timeframe universe). No look-ahead surface exists in the executed path because no HTF input is read. The prompt's HTF-future-close adversarial test is therefore NOT APPLICABLE to the current runtime path (not skipped — absent input). Classified as `N/A (no HTF consumer in canonical path)` in gap analysis.
- Outcome/memory leakage: the canonical cycle has **no outcome memory input** (no prior-trade results enter the context). GAP-R3 requests adding outcome memory + availability test as P1, before any memory feature is adopted.

## 5. Deterministic risk — bypass attempt audit

- Single call-site of `PaperBroker.execute_signal` outside the broker itself: `paper/paper_cycle.py:338`, **after** `RiskManager.check_signal().approved` with `position_size` present. Grep evidence in authority map.
- The broker does not compute size: it consumes `metadata["notional_usdt"]` set by risk (fallback 1% equity exists — DEF-3, fixed this session).
- Hard veto paths proven by execution: kill switch, daily trade limit, max positions, consecutive-loss cooldown, daily loss limit, max drawdown, sizing bounds, exposure clamp. Negative matrix: risk exception ⇒ 0 orders.
- `RISK_BYPASS = NOT FOUND` in the paper runtime (structurally and by execution).

## 6. Reconciliation status

- In-session: REACHABLE + TESTED + EXECUTED (verifier + DEMO-PAPER-01 logs).
- Startup: `paper/reconciliation.py` + `paper/startup_recovery.py` are **ORPHAN** (no runtime caller, no tests). GAP-R1 records the decision: adopt V3 policy (RESTORE_FROM_JOURNAL / conservative fee-aware close; `pnl=0` fake closes forbidden) wired into the paper entrypoint, with tests — P1, separate work package. Not implemented this session (runtime-correctness risk is low for stateless fresh-start paper runs, but the gap is real for resumed sessions).

## 7. Defects found (and fixes applied this session)

| ID | Defect | Severity | Fix |
| --- | --- | --- | --- |
| DEF-3 | Broker silently sized orders at 1% equity when risk-approved `notional_usdt` metadata missing — a signal that bypassed the RiskManager rebuild would still execute with invented sizing | MEDIUM (pipeline integrity) | `paper/broker.py` — explicit `BrokerOrderError`; the broker never invents sizing. Cycle engine catches it as a broker-stage rejection with recorded reason (0 orders) |
| DEF-4 | No engine-level test pinned the broker-failure path nor the unsized-signal rejection | MEDIUM | `tests/unit/paper/test_paper_cycle.py` — `test_broker_exception_zero_orders` + `test_broker_rejects_signal_without_risk_notional` (zero side effects asserted) |
| DEF-5 | `paper/reconciliation.py` orphan uses `pnl=0` breakeven fill (anti-pattern) | LOW (orphan) | Not fixed in place; GAP-R1 (replace with V3 policy when adopted) |

Audit corrections (FALSE_SUCCESS applies to this audit too): initial reading
flagged "hidden session-summary gate" and "session counted as success on broker
crash" as DEF-1/DEF-2. Full-code review disproved both: `reconcile_session`
catches only `ExpectationError` from the expectation gate (an evaluation
policy, whose failure must not mask trading results — fail-loud by design) and
any other exception propagates, failing the session visibly. No code change was
needed there; recording the correction instead of shipping a speculative
"fix".

Post-fix gates: ruff format/check clean, mypy clean, **584/584 tests pass**(incl. the 2 new adversarial tests), verifier 11/11 re-executed, DEMO-PAPER-01 re-executed (exit 0).

## 8. Blockers

- None for `PAPER_OPERATIONAL_VERIFIED` on the current scope.
- External dependencies remain unavailable in-sandbox: no network CCXT run (fake provider used, consistent with paper definition), no LLM providers (none required — the canonical path is deterministic; agent layer is research-side today).
- GATE-L5-16-strict note: this session's runtime validation was executed on the primary clean checkout of `5e6f963` (porcelain = 0), which satisfies the clean-snapshot requirement; an isolated-worktree re-run is the recertification protocol of record and can be repeated verbatim.
