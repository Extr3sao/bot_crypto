## TSK-104 spec: OHLCV Scheduler requirements + BDD scenarios

Adds the SDD spec pack for `src/trading_bot/scheduler/` — the OHLCV scheduler that wraps the TSK-102 `OHLCVFetcher` to keep the `OHLCVStore` fresh.

### What this PR adds

7 new files, no code yet (spec phase per `.ai/commands/01-02`):

1. **`docs/specs/TSK-104-scheduler/01-requirements.md`** (~200 lines)
   - 11 RFs (RF-1..RF-10 + RF-7b) + 6 RNFs + 9 CLs + `SchedulerResult` contract (§2.3)
   - Cross-links: TSK-099 (config tipada), TSK-101 (CCXT connector), TSK-102 (OHLCVStore + fetcher), TSK-103 (scanner is read-only on the store)
   - ADRs: 0006 (Binance+CCXT sandbox), 0012 (gate-recovery), 0013 (TSK-102/103 scope reconciliation), 0014 (forward-ref concurrencia secuencial)
   - 9 acceptance criteria; 6 quality gates per `docs/ci.md` sec 3

2. **`docs/specs/TSK-104-scheduler/02-bdd.md`** (~150 lines)
   - Maps 100% of RFs to Gherkin scenarios
   - 17 scenarios covering happy path, kill-switch, off-hours skip, cache hit/miss, transient error, mode-aware sandbox, empty universe, idempotent re-run, HTTP 429 backoff, mixed-batch, runtime mode-flip
   - Cross-link to the new `.feature` file

3. **`bdd/features/ohlcv_scheduler.feature`** (NEW, ~180 lines)
   - The 17 Gherkin scenarios
   - Independent of `market_scanner.feature` (different scope: scheduler WRITES to `OHLCVStore`; scanner READS from it)

4. **`docs/specs/TSK-104-scheduler/03-specify.md`** (~440 lines)
   - Pure-function `evaluate_cache_hit` with strict `<` boundary (RF-4)
   - 6 dataclasses frozen+slots (`SchedulerResult`, `PullOutcome`, `CacheHitDecision`, `CacheState`, 2 Literals)
   - `OHLCVSourceProtocol` + `ConnectorFactory` + `PullMetricsSink` Protocols
   - `connector_reinjector` R1 opcion b (§6.3, ConfigurationError if factory None + mode needs connector)
   - Writer-via-WAL + reader-after-writer + asyncio-scheduling-invariant (§6.4, R7)
   - Concurrencia secuencial pineada en §6.2 (ADR-0014 forward-ref)

5. **`docs/specs/TSK-104-scheduler/04-plan.md`** (~330 lines)
   - 5 macro-tickets: F1 (TSK-104.1) + F2 (TSK-104.2) + F3a (TSK-104.3a) + F3b (TSK-104.3b) + F4 (TSK-104.4)
   - 17 atomic stubs distributed: F1=3, F2=2, F3a=3, F3b=5, F4=4
   - 7 risks del plan (R1 connector_factory=None, R2 reentrancy deadlock, R3 cache boundary, R4 cobertura, R5 AST fragile, R6 freshness_consistency, R7 race condition scheduler-vs-scanner)
   - Pre-merge-gates: (a) PR #7 merged, (b) ADR-0014 firmada en `tasks/decisions.md`, (c) cross-layer AST verde al final de F3b

6. **`docs/specs/TSK-104-scheduler/05-tasks.md`** (~250 lines)
   - 17 atomic sub-tickets with archivos exactos + tests esperados + dep + P + DoD
   - Cobertura target: ~50 unit + 17 BDD = 67 verde
   - Notas operativas (Literal extension ADR-locked, cross-layer AST bloqueante, R1 opcion b defence, ADR-0014 forward-ref)

7. **Tracker rebadge** (`tasks/sprint-002.md` + `tasks/backlog.md`)
   - TSK-104 row rebadged from "Backtest engine minimo + comisiones + slippage" (PR #3 SQ-MERGE) to **"OHLCV Scheduler: pull periodico..."** in_progress @ `f400c1c`
   - Rebadge history block en `sprint-002.md` preserva el backtest engine como completion historico
   - `backlog.md` TSK-104 entry actualizada con description + 5 docs cross-link + 17 stubs dependency

### Why this PR is spec-only

Per `.ai/methodology-hybrid.md` + `.ai/commands/01-05`, the spec phase is the gating step before implementation. This PR delivers the requirements + BDD scenarios (commands 01 + 02). The next phase is `03-specify.md` (technical specification) + `04-plan.md` (implementation plan) + `05-tasks.md` (task breakdown) followed by the actual implementation in `src/trading_bot/scheduler/`.

### Reviewer focus

- `@Extr3sao/execution-engineer-team` (primary): scheduler semantics, retry/backoff, mode-aware sandbox flag, kill-switch integration with `risk.kill_switch_enabled`
- `@Extr3sao/observability-engineer-team` (secondary): structlog event contract (`scheduler.pull.completed` / `skipped` / `failed` + `scheduler.iteration.completed`), 4 counters binding pattern

### Cross-links

- TSK-103 spec: `docs/specs/TSK-103-universe-scanner/` (twin, scanner reads what the scheduler writes)
- TSK-102 spec: `src/trading_bot/market_data/ohlcv_fetcher.py` (the wrapped component)
- ADR-0006 (Binance+CCXT), ADR-0012 (gate-recovery), ADR-0013 (scope reconciliation)
- `docs/ci.md` seccion 3 (6 quality gates)

### Next steps (in subsequent PRs)

1. Implementation in `src/trading_bot/scheduler/` per TSK-104.1..104.4 (17 stubs)
2. Unit tests (~50 senteinels) + BDD step definitions (17 scenarios) per TSK-104.5
3. Quality gates (ruff + mypy + pytest --cov-fail-under=90 + safety + pip-audit) per TSK-104.4.4
4. Sign ADR-0014 in `tasks/decisions.md` BEFORE merge of TSK-104.4 (concurrency sequential decision)
5. Open PR F-spec-implementation targeting `main`
6. Tag `v0.6.0-rc.1` post-merge
