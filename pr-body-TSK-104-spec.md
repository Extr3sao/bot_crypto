## TSK-104 spec: OHLCV Scheduler requirements + BDD scenarios

Adds the SDD spec pack for `src/trading_bot/scheduler/` — the OHLCV scheduler that wraps the TSK-102 `OHLCVFetcher` to keep the `OHLCVStore` fresh.

### What this PR adds

3 new files, no code yet (spec phase per `.ai/commands/01-02`):

1. **`docs/specs/TSK-104-scheduler/01-requirements.md`** (~200 lines)
   - 10 RFs + 6 RNFs + 9 CLs
   - Cross-links: TSK-099 (config tipada), TSK-101 (CCXT connector), TSK-102 (OHLCVStore + fetcher), TSK-103 (scanner is read-only on the store)
   - ADRs: 0006 (Binance+CCXT sandbox), 0012 (gate-recovery), 0013 (TSK-102/103 scope reconciliation)
   - 7 acceptance criteria; 6 quality gates per `docs/ci.md` sec 3

2. **`docs/specs/TSK-104-scheduler/02-bdd.md`** (~120 lines)
   - Maps 100% of RFs to Gherkin scenarios
   - 12 scenarios covering happy path, kill-switch, off-hours skip, cache hit/miss, transient error, mode-aware sandbox, empty universe, idempotent re-run, HTTP 429 backoff
   - Cross-link to the new `.feature` file

3. **`bdd/features/ohlcv_scheduler.feature`** (NEW, ~150 lines)
   - The 12 Gherkin scenarios
   - Independent of `market_scanner.feature` (different scope: scheduler WRITES to `OHLCVStore`; scanner READS from it)

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

1. `03-specify.md` (technical design)
2. `04-plan.md` (implementation plan)
3. `05-tasks.md` (task breakdown, mirror of TSK-103 05-tasks)
4. Implementation in `src/trading_bot/scheduler/`
5. Unit tests + BDD step definitions
6. Quality gates (ruff + mypy + pytest --cov-fail-under=90)
7. Open PR F-spec-implementation
