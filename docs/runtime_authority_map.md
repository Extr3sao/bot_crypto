# Runtime Authority Map

> Audited on: HEAD `5e6f963` (main, clean worktree, porcelain = 0). Date: 2026-09-25.
> Method: import-following from entrypoints + execution evidence (verifier 11/11, paper run, pytest 582).
> Reachability is demonstrated, not assumed: a class existing on disk does NOT imply reachability.

## Runtime entrypoints (demonstrated)

| Entrypoint | Path | Reachability evidence |
| --- | --- | --- |
| Paper loop (canonical) | `scripts/start_paper_trading.py` | Executed in this audit: DEMO-PAPER-01, exit 0, session + cycle counters emitted |
| Independent verifier | `scripts/verify_l5_independent.py` | Executed in this audit: 11/11 PASS on clean HEAD |
| CLI `trading-bot` | `src/trading_bot/app.py::main` | `config-check` + `scan --demo` executed; `--mode live` exists but is env-gated (out of scope of paper phase) |

## Canonical paper pipeline (RUNTIME_AUTHORITATIVE)

| Stage | Implementation | Runtime reachable | Authoritative | Tested | Real execution evidence | Gap |
| --- | --- | --- | --- | --- | --- | --- |
| Orchestration loop | `paper/paper_orchestrator.py` (PaperOrchestrator) | YES | YES (single authority, ADR-documented) | unit + e2e-001 | DEMO-PAPER-01: 2 sessions, gates re-checked each session | none |
| Session runner | `paper/harness.py` (PaperSessionRunner) | YES | YES | unit + e2e-002/003 | DEMO-PAPER-01 + verifier runs | none |
| Market scan | `scanner/scanner.py` (UniverseScanner) | YES | YES | 39 BDD + unit | DEMO-PAPER-01 (3 snapshots, 0 errors) | none |
| PIT history read | `paper/snapshot_history.py` (FetcherBarReader) | YES | YES | verifier GATE-L5-09 (future-bar rejection) | verifier 11/11 on clean HEAD | none |
| PIT trim (defence in depth) | `paper/snapshot_context.py::trim_to_pit` | YES | YES | unit + verifier | verifier | none |
| Context/agent | `research/asset_intelligence/` (CryptoAssetAgentRegistry, BaseCryptoAssetAgent) | YES | YES (single classifier, no second regime source) | unit/research + verifier | verifier: contexts_built=3, context_errors=0 | none |
| Regime | inside `BaseCryptoAssetAgent.build_context` (point-in-time) | YES | YES | unit | verifier | none |
| Router | `research/strategy_router.py` (StrategyRouter) | YES | YES (single router, ADR_STRATEGY_ROUTER_CONVERGENCE) | unit + e2e | verifier + DEMO-PAPER-01 (router_invocations=3) | none |
| Alpha families | `research/families/*.py` (6 families) | YES | YES (only families wired in entrypoint map) | unit | verifier: 3 alphas generated; DEMO-PAPER-01: 0 alphas (flat synthetic data → NO_TRADE, fail-closed) | none |
| Signal adapter | `paper/signal_adapter.py` | YES | YES (single conversion point) | unit + e2e | verifier (alphas → signals) | none |
| Candidate consolidation | `paper/candidate_portfolio.py` (build_portfolio) | YES | YES | unit + e2e | verifier | none |
| Risk engine | `risk/manager.py` (RiskManager) — deterministic | YES | YES (single sizing authority; broker does NOT size) | unit + e2e + verifier negative matrix | verifier: risk reject → 0 orders | none (hard-veto proven) |
| Idempotency | `execution/idempotency.py` (IdempotencyGuard) | YES | YES (neutral, reused) | verifier GATE-L5-08 + e2e | verifier: duplicate intent → exactly 1 execution | none |
| Execution (paper) | `paper/broker.py` (PaperBroker) — the ONLY execution boundary | YES | YES | unit + e2e + verifier | verifier GATE-L5-10: open → reconcile → SL/TP close → realized PnL | none |
| In-session reconciliation | `broker.reconcile_session` (SL/TP + summary + equity invariant) | YES | YES | e2e-002 + verifier | verifier: lifecycle + equity identity | none |
| Durable state store (GAP-R1) | `paper/paper_state_store.py` (atomic JSON, corrupt ⇒ fail closed) | YES | YES | `test_paper_recovery.py` (9 crash cases) | RUN-C: restart → RECOVERED on real book | none |
| Startup reconciliation V4 | `paper/reconciliation_v4.py` (StartupReconcilerV4) | YES (wired in `start_paper_trading.py`) | YES | crash matrix + RUN-C live | restart real-data run: 3 positions + 3 intents + equity identity restored | none |
| Session state snapshot | `paper/paper_runtime_state.py` (save per session) | YES | YES | crash matrix | `paper.state.saved` events in all runs | none |
| Closed-candle gate + provider sanitization | `paper/snapshot_history.py` (V3 filter + dedup/sort/reject) | YES | YES | `test_provider_failures.py` (13 policy cases) | REAL-DATA-PIT-CAPTURE: forming candle excluded on binance testnet | none |
| Session reporting | `paper/reporting.py` + `paper/archive.py` | YES | YES | unit | DEMO-PAPER-01: report.json/md written | none |
| Orchestrator status | `PaperOrchestrator.status()` (JSON) | YES | YES | unit | DEMO-PAPER-01 output | none |
| Risk feedback loop | `harness._record_closed_trades_in_risk` → `RiskManager.record_trade_result` | YES | YES | e2e + verifier | verifier: consecutive_losses incremented | none |

## Legacy / superseded (classified, NOT authoritative)

| Component | Path | Classification | Notes |
| --- | --- | --- | --- |
| StartupReconciler V1 (broker-vs-journal) | `paper/reconciliation.py` | **ORPHAN** | Superseded by V4 (`reconciliation_v4.py`, RUNTIME_AUTHORITATIVE via entrypoint). V1's `pnl=0` breakeven-fill anti-pattern retires with it (deletion in a later cleanup phase) |
| Startup recovery V3 | `paper/startup_recovery.py` | ORPHAN | RESTORE_FROM_JOURNAL/ORPHAN_RECONCILIATION_CLOSE policy is the desired semantics; never wired. See gap analysis GAP-R1 |
| KillSwitch V2 (5-state) | `paper/kill_switch_v2.py` | **LEGACY** (superseded by ADR_PAPER_LEGACY_CONVERGENCE) | Canonical runtime uses RiskManager kill switch + broker kill_switch; v2 not reachable |
| StrategySelector | `paper/strategy_selector.py` | **LEGACY** | Router is canonical (ADR) |
| Parity gate | `paper/parity_gate.py` | ORPHAN | design-only, no runtime caller, no tests |
| PortfolioManager (paper) | `paper/portfolio_manager.py` | ORPHAN | superseded by PaperBroker equity accounting |
| Paper trade journal | `paper/trade_journal.py` | ORPHAN | observability journal (`observability/journal.py`) is the wired one via reporting/reconciliation paths |
| `paper/validation.py` | `paper/validation.py` | ORPHAN | no runtime caller found |
| CLI live paths (`app.py run --mode live`, place-order, Bitunix futures) | `app.py`, `market_data/bitunix*.py`, `execution/live_gate.py` | RUNTIME_REACHABLE (via CLI) | LIVE-capable, env-gated, **out of scope** for paper phase; audited only for accidental reachability from paper path (none: grep clean) |

## Research-only (not paper-runtime)

`research/` beyond the components above (qualification, gates, campaign, cross_sectional, canonical_accounting, portfolio_backtest, quant_auditor_v021, strategy_engineer, marginal, stability, confirmation, cost_integrity, data_integrity, market_provenance, calendar, historical_data, admission, equity_reconstruction, backtest_evidence, code_path, llm_safety, router_gates, strategy_sandbox): RESEARCH_ONLY — used by research/certification campaigns, not by the paper loop. `research/event_store.py` (BlockedEventStore): TEST_ONLY/ORPHAN in paper runtime.

`backtesting/` engine + walk-forward: TEST_ONLY + research tooling (TSK-104 done, coverage 97.69%); not part of the paper decision loop.

## Explicit NON-goals found and rejected in this audit

- No second orchestrator, second router, or second sizing path exists (grep + import audit).
- No exchange/credential import in the canonical paper cycle modules (verifier GATE-L5-17).
- `agent_id/capability/permissions` registries, `AgentMessage` contracts, debate/critic loops, blackboard shared state, memory stores, DecisionTrace objects, `replay(run_id)` API: **ABSENT** from the codebase — classified as NOT IMPLEMENTED (not LEGACY). See gap analysis; do not confuse VNext naming with code.

---

# UPDATE — AUTONOMOUS-PAPER-RUNTIME-V1

> Audited on: HEAD `65b3821` (+ this phase). Method: the same authority ranking,
> but every classification below was re-derived by reading the code and by
> grepping the actual importers in `src/`, `scripts/` and `tests/`.
> The section above is kept verbatim: it is the record of the previous audit.

## 1. New authoritative entrypoint

| Entrypoint | Path | What it actually runs |
| --- | --- | --- |
| Autonomous PAPER/SHADOW loop | `scripts/autonomous_paper.py` | scanner (read-only public data) → PIT reader → context → router (per candidate) → families → `TradeProposal` → agent reviews → `IndependentVerifier` → `DecisionEngine` → deterministic `RiskManager` → `PaperBroker` (only for TRADE_PAPER) → `DecisionTrace` → reconcile → `OutcomeEvaluator` → `StrategyPerformanceStore`. ONE_SHOT (`--cycles 1`) or bounded loop. Refuses to start unless `runtime.mode == paper`. |

`scripts/start_paper_trading.py` remains authoritative for the legacy paper loop and is **untouched** this phase.

## 2. Components added and wired (all RUNTIME_AUTHORITATIVE)

| Component | Path | Role | Evidence of reachability |
| --- | --- | --- | --- |
| `AdmissionLedger` | `autonomous/admission_ledger.py` | only authority for "may this strategy run PAPER" | called by the runtime per candidate; `AdmissionLedger.load` in the entrypoint |
| `TradeProposal` / `ShadowTradeDecision` / `DecisionTrace` / `OutcomeRecord` / `StrategyPerformance` | `autonomous/contracts.py` | frozen contracts with structural invariants | constructed by the runtime; validated by tests |
| `AgentRegistry` (+5 specialists) | `autonomous/agents.py` | structured deterministic reviews | invoked every candidate; agent ids printed by the entrypoint |
| `CostEngine` | `autonomous/costs.py` | COST_MODEL_V3 evaluated with the OBSERVED spread | called per proposal; version recorded in every trace |
| `DecisionEngine` | `autonomous/decision.py` | `intend` + `decide` → TRADE_PAPER / SHADOW_TRADE / NO_TRADE | called twice per candidate (intent, then final) |
| `IndependentVerifier` | `autonomous/verifier.py` | re-derives PIT slice, cost, arithmetic, admission, shadow purity | called for every proposal; verdict recorded in the trace |
| `DecisionTraceStore` (+ replay) | `autonomous/trace.py` | append-only hash-chained ledger | written every cycle; `verify_chain()` in the run report |
| `OutcomeEvaluator` | `autonomous/outcomes.py` | PIT-safe outcome + MFE/MAE, else PENDING_OUTCOME | called at the end of every cycle |
| `StrategyPerformanceStore` | `autonomous/experience.py` | outcome-driven memory (selection only) | updated on every resolved outcome |
| `AutonomousPaperRuntime` | `autonomous/runtime.py` | the cycle/loop itself | entrypoint `await runtime.run(...)` |
| run report writer | `autonomous/reporting.py` | `RUN_REPORT.{md,json}` from one object | written at the end of every run |

## 3. Re-classified by this audit

| Component | Previous | Now | Reason |
| --- | --- | --- | --- |
| `research/admission.py` (`AdmissionController`) | RESEARCH_ONLY | **DEAD_CODE** | zero importers in `src/` + `scripts/` (grep). Name collision: it gates *signals*, not *strategies* |
| `feedback/evaluator.py` | (unclassified) | IMPLEMENTED_NOT_WIRED | imported only by `feedback/__init__.py` + its own test |
| `paper/reconciliation.py`, `paper/startup_recovery.py` | ORPHAN | ORPHAN (confirmed) | the only grep hits were prefix matches of `reconciliation_v4` in the entrypoints |
| `paper/validation.py` | ORPHAN | PARTIAL / TEST_ONLY | one importer: `tests/unit/cert/test_canonical_core_lint_guard.py` |
| legacy `strategy_map` in `start_paper_trading.build_cycle_engine` | RUNTIME_AUTHORITATIVE | RUNTIME_AUTHORITATIVE but **not admission-gated** | it still writes `status="CONFIRMED"` for all six families (DEF-AUTO-4) |

## 4. Still missing / defects (evidence-backed)

| ID | Item | Severity | Evidence |
| --- | --- | --- | --- |
| DEF-AUTO-2 | Universe not pre-validated against `CryptoAssetAgentRegistry` | LOW-MEDIUM | real run: BNB/XRP/ADA/DOGE/AVAX produce `CONTEXT_ERROR: no AssetAgent registered for asset: <X>` every cycle instead of a fail-fast startup message |
| DEF-AUTO-3 | `RouterGates.require_fresh_context` is a fixed 15-minute wall-clock lag | MEDIUM | a 30m run makes every candidate `stale_context` (the last closed 30m bar is ≥15 min old by construction). Effective timeframe ceiling ≈ 5m-15m |
| DEF-AUTO-4 | `start_paper_trading.py` still marks every family `status="CONFIRMED"` | MEDIUM (integrity) | that map is not admission-gated; the autonomous entrypoint uses the ledger instead |
| DEF-AUTO-5 | `paper/reconciliation.py`, `paper/startup_recovery.py`, `research/admission.py`, `feedback/evaluator.py` remain orphan | LOW | zero importers (grep) |
| DEF-AUTO-6 | `RouterGates(require_confirmed=False)` in the autonomous composition | ACCEPTED by design | the router must be able to *select* research candidates so they can be observed in SHADOW; PAPER authority moved to the ledger + verifier + DecisionEngine (defence in depth, three independent gates) |
| — | LLM/agent reasoning layer | NOT REQUIRED | no credentials in this environment; the deterministic review layer is replayable, which an LLM layer would not be |

## 5. UPDATE — RISK-IN-SHADOW + BAR-CLOSE AVAILABILITY (this phase)

> Audited on: HEAD `ddaf14d`. Method: same authority ranking; the runtime,
> verifier, outcome evaluator and ledger generator were re-read, and the
> behaviour was re-derived from the tests that exercise it.

### 5.1 Authority changes

| Item | Before | Now | Evidence |
| --- | --- | --- | --- |
| deterministic risk in SHADOW / NO_TRADE | not invoked (`NOT_APPLICABLE` always) | **the same canonical `RiskManager.check_signal` is invoked for every decision that carries a proposal**, recorded as `advisory=true` | `test_shadow_decision_is_risk_reviewed_advisory`, `test_admitted_and_unadmitted_paths_share_one_risk_engine` |
| availability instant for a bar | bar OPEN timestamp | **bar CLOSE** (`pit.availability_ms`) for the consumed PIT slice, the verifier slice check and the outcome | `test_the_forming_bar_is_not_usable_at_the_decision_time`, `test_outcome_instant_is_the_close_of_the_bar_not_its_open` |
| outcome identity | decision id only | **`OutcomeKey = decision_id + horizon`**, idempotent append | `test_appending_the_same_outcome_twice_creates_one_record` |
| replay coverage | boolean ok | honest **FULL / PARTIAL / NOT_AVAILABLE** | `test_replay_status_is_partial_without_an_outcome` |
| edge prior provenance | source + metric + sample + knowledge | + **`evidence_class=HISTORICAL_ESTIMATE`, `period`, `timeframe`, `status`** | `test_expected_edge_carries_historical_estimate_provenance` |

New module: `autonomous/pit.py` (bar-close availability). New enums:
`RiskState`, `NoTradeKind`, `RuntimeFailureKind`, `ReplayStatus`.

### 5.2 Defect found and fixed in this phase

| ID | Observation | Root cause | Fix | Test |
| --- | --- | --- | --- | --- |
| DEF-AUTO-7 | the 5m outcome for a decision at instant `T` was priced with the close of the bar opened at `T + 5m`, i.e. the price of `T + 10m`, and its `outcome_time_ms` was that bar's OPEN | the evaluator selected the first bar with `timestamp > decision_time` and stamped the outcome with `bar.timestamp` | the evaluator now selects the first bar whose CLOSE reaches the horizon and stamps the outcome with that CLOSE; `reference_price_time_ms` (also a close) was added so the whole record satisfies `reference_price_time <= decision_time < future_price_time` | `test_outcome_instant_is_the_close_of_the_bar_not_its_open`, `test_outcome_contract_temporal_ordering` |
| DEF-AUTO-8 | a provider outage surfaced as a `NO_TRADE` row, indistinguishable from a real decision not to trade | the terminal path only carried `classification` | rows now carry `no_trade_kind` (STRATEGIC/RISK/DATA/CONFLICT) OR `failure_kind`, never both; `totals.no_trades` excludes operational failures, which are counted in `totals.runtime_failures` | `test_a_provider_outage_is_a_runtime_failure_not_a_no_trade` |
| DEF-AUTO-9 | a `RiskReview(verdict=PASS)` that no engine produced could be read as an approval | `RiskReview` had no notion of "was it actually run" | `evaluated` + `rule` are mandatory for an evaluated review; `state` degrades an unevaluated PASS to `NOT_EVALUATED` | `test_a_pass_nobody_produced_is_not_evaluated_never_approved` |

### 5.3 Still open

DEF-AUTO-2, DEF-AUTO-3, DEF-AUTO-4, DEF-AUTO-5 remain open and unchanged; they are
outside this phase's scope (evidence gathering for a future edge phase, not runtime
correctness).
