👋 **Requesting review** from the owning teams per AGENTS.md § 2.

@Extr3sao/execution-engineer-team — primary reviewer. Scope of TSK-104 is the OHLCV on-demand scheduler that wraps the TSK-102 `OHLCVFetcher`. Key execution-adjacent decisions in this spec:
- `Scheduler.run_once()` async loop with `asyncio.Lock` for re-entrancy (CL-4)
- `kill_switch_enabled` check happens **before** any I/O (RF-3)
- Mode-aware sandbox flag: `paper|backtest|research` -> True, `live` -> False (RF-7)
- HTTP 429 backoff: 1s, 2s, 4s exponential, 3 retries before `pulls_failed+=1` (CL-9)
- Cross-layer enforcement via AST test (RF-8) — same pattern as TSK-103 RF-8, but for `src/trading_bot/scheduler/`

@Extr3sao/observability-engineer-team — secondary reviewer. The structlog contract for the scheduler mirrors the TSK-103 scanner contract with 4 counters (RF-6):
- `pulls_attempted` / `pulls_succeeded` / `pulls_failed` / `cache_hits`
- 3 events: `scheduler.pull.completed` / `skipped` / `failed` + 1 summary event `scheduler.iteration.completed`
- `scheduler_iteration_id` UUIDv4 per iteration (same `request_id` binding pattern as the scanner)
- Motivos normalizados: `off_hours`, `cache_fresh`, `timeout` (string Literal per ADR-lock pattern, mirroring TSK-103's `RejectionReason` Literal)

**Why a comment, not a formal reviewer slot?** The `POST /repos/.../pulls/N/requested_reviewers` returns 422 "teams not collaborators" (the two named teams are pending repo-collaborator grant per the TSK-009 governance workflow). Team subscribers get the @-mention notification as the documented workaround.

**What this PR does**: spec-only, no code. 3 new files (2 SDD docs + 1 Gherkin `.feature`). The next phase is `03-specify` + `04-plan` + `05-tasks` + implementation, which will be a separate PR.
