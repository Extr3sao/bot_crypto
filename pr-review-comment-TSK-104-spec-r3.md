👋 **Round-2 + round-3 self-review fixup** landed (`feature/tsk-104-scheduler-spec` @ `<new-sha>`).

Applied the 4 substantive fixes + 3 new BDD scenarios from the round-1 code-reviewer, then the 3 round-3 fixes (SchedulerResult contract, Criterio 6 count ref, CL-ext wart), then the round-3 reviewer's 1-line invariante clarification. No code yet; spec-only PR.

---

## Round-1 → Round-2 substantive fixes (`docs/specs/TSK-104-scheduler/01-requirements.md`)

1. **RF-4 cache-hit predicate** — tightened to respect the `primary_timeframe` boundary:
   - OLD: `last_candle_age < freshness_window_min`
   - NEW: `last_candle_ts >= current_ts - primary_timeframe AND current_ts - last_candle_ts < freshness_window_min`
   - Reason: a 4-min-old candle is "fresh" by a 5-min window but is from the previous 5-min period. The old predicate would skip the current period's pull and the new candle wouldn't be in the store.

2. **RF-7 split** — the old `paper|backtest|research -> sandbox=True` conflated the connector-sandbox axis with the source-selection axis. For `backtest|research`, the source is a `MarketDataSourceProtocol` synthetic impl, NOT the connector at all:
   - NEW **RF-7**: `live` uses connector with sandbox=False; `paper` uses connector with sandbox=True (2 modes, not 4).
   - NEW **RF-7b**: `backtest|research` uses `MarketDataSourceProtocol` synthetic impl (no connector, no sandbox flag).
   - Reason: backtest uses a historical fixture, not the live exchange — `sandbox=True` is meaningless noise.
   - Also: explicit note that **runtime mode-flip requires connector re-injection via DI** — `sandbox` is set in `__init__` before `load_markets` per TSK-101, NOT mutated in place.

3. **CL-1 wording fix** — "exit code 0" is meaningless for an asyncio task:
   - OLD: "Log warn, return sin pull, exit code 0"
   - NEW: "Log warn `scheduler.universe.empty`, retorna `SchedulerResult(pulls_attempted=0)` sin pull, no exception"
   - Same wording fix applied to RNF-4 ("exit 2s" -> "shuts down within 2s").

4. **CL-9 HTTP 429 backoff** — now respects the `Retry-After` response header (Binance/CCXT standard) + adds jitter:
   - OLD: "Backoff exponencial (1s, 2s, 4s); reintentar 3 veces antes de fail"
   - NEW: "Respetar header `Retry-After` si presente (1-60s); si no, backoff jittered (1s, 2s, 4s +/- 25%); reintentar 3 veces antes de fail"
   - Reason: ignoring `Retry-After` is non-standard and would still get the requester rate-limited.

5. **RNF-4 CancelledError propagation** — the 2s SLO is fine, but the spec didn't say what happens to `CancelledError` from the inner `await`. Now explicit: "CancelledError del inner `await run_once()` propaga al caller sin ser tragado".

## Round-2 → 3 new BDD scenarios (`bdd/features/ohlcv_scheduler.feature`)

6. **`HTTP 429 con 3 reintentos agotados reporta pull_failed`** (CL-9 negative) — 1 + 3 retries, all 429, ends in `pulls_failed=1` + log `scheduler.pull.failed` motivo `rate_limit_exhausted`.

7. **`Batch mixto cache_hit + cache_miss + timeout`** — 25-pair batch with BTC=cache_hit + ETH=cache_miss + SOL=timeout all in one iteration; verifies all 3 counters + 3 distinct structlog events.

8. **`Cambio de modo en runtime de paper a live`** — verifies that flipping `runtime.mode` mid-process is picked up by the next `run_once()` and the new mode is reflected in the `sandbox` flag (via connector re-injection, NOT in-place mutation).

## Round-2 sandbox scenario split (`bdd/features/ohlcv_scheduler.feature`)

The old "Sandbox flag correcto por modo" scenario conflated the same axes. Split into 3:
- `Connector sandbox flag correcto (live vs paper)` — 2 modos, verifies the `sandbox` flag
- `Backtest usa source synthetic sin connector` — verifies NO connector is invoked
- `Research usa source synthetic sin connector` — same

---

## Round-3 fixes (3 docs + 1 invariante clarification)

9. **New section 2.3 `SchedulerResult` contract** (`01-requirements.md`) — the dataclass was referenced by 8+ BDD scenarios but never defined. Added a 1-page contract with 6 fields: `pulls_attempted`, `pulls_succeeded`, `pulls_failed`, `cache_hits`, `duration_ms`, `scheduler_iteration_id` (frozen + slots). Includes the invariante:
   - `pulls_attempted == pulls_succeeded + pulls_failed + cache_hits`
   - Updated to: invariante covers the **post-filter batch** (post `active_hours` and post `kill_switch`); filtered pairs don't appear in counters.

10. **Criterio 6 count ref** (`01-requirements.md`) — "BDD 10-12 escenarios" → "BDD 17 escenarios" (matches the actual count after round-2 added 3 net-new scenarios).

11. **Section 8 handoff cleanup** (`01-requirements.md`) — removed stale " + CL-ext" suffix; handoff now reads "RF-1..RF-7b (11 functional reqs) y CL-1..CL-9 se traducen a escenarios Gherkin".

12. **Invariante clarification** (`01-requirements.md` section 2.3) — flagged by the round-3 reviewer: the invariante didn't account for `active_hours` skips (RF-2) or `kill_switch` blocks (RF-3). Tightened the invariante note to: "covers the subset that passes `active_hours` and `kill_switch` filters; filtered pairs do not appear in counters".

---

## `02-bdd.md` updates

Mapping table reflects:
- RF-7 split (3 scenarios: Connector live+paper, Backtest synthetic, Research synthetic)
- CL-1/4/5/9 rows updated; CL-9 negative + Batch mixto + Mode switch added
- "Crear" line now says "17 escenarios" (was "12 escenarios" pre-round-2)

## Validation

- All changes are docs-only (markdown + Gherkin); no Python source touched
- `02-bdd.md` mapping table is consistent with the 17 BDD scenarios
- `01-requirements.md` RF-4 / RF-7 / RF-7b / CL-1 / CL-9 / RNF-4 / 2.3 / Criterio 6 / Section 8 changes are byte-precise
- Force-pushed with `--force-with-lease` (preserves 1-commit-PR invariant)

## Next phase

Once the spec merges: `03-specify.md` + `04-plan.md` + `05-tasks.md` → implementation.
