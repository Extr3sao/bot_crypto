👋 **Round-4 self-review fixup** landed (`feature/tsk-104-scheduler-spec` @ `<new-sha>`).

Added `03-specify.md` (652 lines, 12 sections matching TSK-103 template) and applied the 5 round-1 code-reviewer fixes. No code yet; spec phase.

---

## 03-specify.md at a glance

12 sections: layout de archivos → tipos publicos (SchedulerResult + PullOutcome + CacheHitDecision + CacheState + 2 Literals) → protocolos (OHLCVSourceProtocol + ConnectorFactory + PullMetricsSink) → CacheHitPredicate pure function (RF-4) → filtros pre-batch (KillSwitch + ActiveHours) → OHLCVScheduler orquestador (run/run_once/connector_reinjector) → errores custom → configuracion afectada (YAML `runtime.scheduler.*`) → metricas observables (7 structlog events + single-emission point) → dependencias nuevas (cero) → anti-patrones evitados (8) → handoff a 04-plan.md.

## 5 round-1 fixes applied

1. **Missing `primary_timeframe` in YAML (§8)** — the cache-hit predicate needs `primary_timeframe` to evaluate RF-4. Added `runtime.scheduler.primary_timeframe: "5m"` with comment cross-referencing §4 boundary case.

2. **Phantom `connector_injected` early_exit state (§9.1)** — this state was invented. The `iteration.completed` table now has only 3 real rows (`None` / `kill_switch` / `empty_universe`); added explicit NOTE explaining that mode-flip via `connector_reinjector(new_mode)` is async to the pull cycle and does NOT abort the current `run_once()`.

3. **`FakeOHLCVSource` terminology leak (§6.1 table)** — `FakeOHLCVSource` is a TSK-103 *test scaffolding* name. Renamed to `DeterministicOHLCVSource` (production abstraction). Scheduler must never import from `market_data/fake.py` (test-only).

4. **Internal `D-TSK104-1` / `D-TSK104-2` cross-refs** — replaced the fake "decision IDs" with prose ("decision documentada en §3" + "cambio requiere ADR firmada"). These IDs were not ADRs and would have been confusing.

5. **`shadow_live` row in §6.1** — not explicitly mentioned in 01-requirements.md. Added a footnote [^1] explaining that shadow_live is treated identically to live in the scheduler (sandbox=False), with cross-link to `UniverseScanner._SCANNER_MODE_MAP` (TSK-103 spec section 7.1) which establishes the same convention.

## What was already approved in round-1

- §1 layout, §2 types (6-field SchedulerResult + frozen + slots + invariante), §3 protocols (DI via Callable + Protocol with runtime_checkable), §4 CacheHitPredicate formula (boundary case correct: TF=1m, freshness=1m, current=12:01, last=12:00 → `should_pull=True` per strict `<`), §5 filtros pre-batch, §7 errores custom, §10 deps (cero), §11 anti-patrones, §12 handoff.
- Sequential-pulls decision in §6.2 (D-TSK104-2 → now prose) is well-reasoned: rate limit + determinismo + RNF-1 P95 ≤ 6s.
- Mode-handling table in §6.1 (sans FakeOHLCVSource leak) is consistent with `01-requirements.md` RF-7 / RF-7b.
- Cross-layer enforcement via AST test pattern from TSK-103 (scheduler only imports `market_data` + `config`).

## Validation

- Docs-only edit (markdown, no Python source touched)
- 03-specify.md cross-references 01-requirements.md RF-1..RF-7b + RNF-1..RNF-6 + CL-1..CL-9 + the 2.3 SchedulerResult contract
- 03-specify.md cross-references 02-bdd.md (17 Gherkin scenarios)
- 03-specify.md is consistent with TSK-103's 03-specify (same section structure, same template, same anti-patterns)
- Force-pushed with `--force-with-lease` (preserves 1-commit-per-PR invariant)

## Next phase

Once the spec merges: `04-plan.md` (5-phase incremental implementation plan) → `05-tasks.md` (atomic sub-tickets) → implementation.

Reviewer verdict from round-1: **"No blockers for `04-plan.md` after items 1-3 are fixed."** Items 1-3 + the 2 nits are now fixed.
