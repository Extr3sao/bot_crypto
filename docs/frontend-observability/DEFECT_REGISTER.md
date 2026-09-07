# FRONTEND-OBSERVABILITY — DEFECT REGISTER

Maintained on `feat/frontend-observability-v1`. Runtime authority is never
modified by these fixes (read-only projections/server only).

---

## DEF-FE-001 — SPA_HASH_ROUTER_NOT_RENDERING

**Status:** FIXED (2026-09-07, V1.2-R2).

**Reproduction (real Chrome, before fix):**

```text
URL = http://127.0.0.1:8767/#trades
active_tab  = overview      (WRONG)
visible     = [s-overview]  (WRONG)
console     = pageerror: Identifier 'rp' has already been declared
            = Failed to load resource: ... 404 (favicon)
```

**Root causes (two independent defects):**

1. **Script-killing SyntaxError:** the V1.1 `loadAll()` declared `const rp`
   (reports payload) while a module-scope `const rp` also existed —
   `Identifier 'rp' has already been declared` aborted the entire script
   at parse time, so the router, data loading and rendering never ran. The
   static `class="on"` Overview markup was all the user ever saw.
2. **Router never wired to initial load correctly:** `route()` delegated to
   synthetic `a.click()` and the click handler only toggled classes; on a
   direct hash load the hashchange event never fires, and back/forward
   navigation depended on the same fragile path.

**Fix:** SPA rewritten (V1.2) with an explicit hash router: `TABS`
registry, `activate(tab)` toggling exactly one tab + one panel,
`route()` resolving `location.hash` (unknown hash → `location.replace
('#overview')` safe fallback), `hashchange` listener, and `route()` called
on load. Click handlers removed entirely — anchors keep their native hash
behaviour, which is what makes back/forward work. The `rp`/`re` collisions
renamed (`rpEl`, `reEl`). Favicon served as 204 (no console noise).

**Verified (real Chrome, after fix):** direct `#trades` → tab=trades,
panel=s-trades only, 3 real campaign trade rows; click → `#funnel`; back →
`#trades`; forward → `#funnel`; reload → stays `#funnel`; manual Refresh →
stays; auto-refresh (30 s) → stays; console errors = 0. Browser E2E suite
`tests/e2e/test_browser_v1_2.py` = 5/5.

---

## DEF-FE-002 — PRE-EXISTING REFERENCE

**Status:** NOT_FOUND_IN_REPOSITORY (as of 2026-09-07).

A repo-wide and worktree-wide search found no prior registration of
DEF-FE-002 anywhere in `docs/`, `scripts/`, or `tests/` (it is referenced
only in the checkpoint instructions). Recorded as `UNVERIFIED — origin
external`; no claims are made about its content or resolution.

---

## DEF-FE-003 — PREMATURE_SERVER_IMPORT

**Status:** FIXED (2026-09-07, commit on `feat/frontend-observability-v1`).

**Evidence (reproduced before fix):**

```text
$ uv run python -m trading_bot.frontend_observability.server --help
<frozen runpy>:128: RuntimeWarning: 'trading_bot.frontend_observability.server'
found in sys.modules after import of package
'trading_bot.frontend_observability', but prior to execution of
'trading_bot.frontend_observability.server'; this may result in
unpredictable behaviour
```

**Root cause:** `src/trading_bot/frontend_observability/__init__.py`
eagerly imported `server` (for `create_server, main`) and every
`projections` function. When runpy executes `python -m
trading_bot.frontend_observability.server`, the parent package is imported
first; the eager import put `...server` into `sys.modules` before runpy
executed it — exactly the premature-import condition runpy warns about.

**Fix:** package `__init__` is now side-effect free; public re-exports
(`create_server`, `main`, all projection functions) are resolved lazily
via PEP 562 `__getattr__` with first-access caching. `dir()` stays
accurate via `__dir__`.

**Required gate (met):** `python -m trading_bot.frontend_observability.server
--help` → no RuntimeWarning.

**Tests:** `test_package_import_is_side_effect_free`,
`test_module_execution_no_runtime_warning`,
`test_lazy_package_reexports_resolve`.
**Validator:** checks `no_premature_server_import` and
`module_help_warning_free` (18/18).

**Scope guard:** no runtime-authority module was touched; the fix is
confined to the read-only observability package.

---

## DEF-FE-004 — POSITIONAL_ARTIFACT_DISCOVERY (found during this investigation)

**Status:** FIXED (2026-09-07, V1.2-R2; was MITIGATED in V1.1).

**Problem:** `projections.py` discovered campaign artifacts purely
positionally: `REPO_ROOT = Path(__file__).parents[3]` → `<worktree>/reports`.
A server running from worktree A silently read whatever stale copies
happened to sit in worktree A's `reports/` — no error, no staleness marker.

**Evidence (empirical, before fix):** the frontend worktree held a mirror
of `CAMPAIGN_STATE.json` copied during an earlier smoke test:
`MARKET_SCANS=330`, heartbeat `last_scan_time=2026-09-07T06:28Z`, while the
live campaign worktree (`.worktrees/poc01-execution`) had already advanced
to `MARKET_SCANS=429`, heartbeat `09:16Z` — a silent ~2.5 h staleness.

**Fix:** `--reports-root` / `--campaign-root` CLI flag (aliased, single
`dest`) plus `projections.set_reports_root()` / `reports_root()`. The
`overview` payload now always carries `reports_root` so a reader can see
exactly which artifact root is being served. Discovery remains read-only;
when no explicit root is given, the positional default is unchanged
(backwards compatible).

**Cross-worktree proof (after fix):** server started from
`feat/frontend-observability-v1` with
`--reports-root <poc01-execution>/reports` served the LIVE state:
`campaign_id=poc01-paper-observation-01-001`,
`MARKET_SCANS=459` (≥ live 429 and advancing), equity/realized PnL
matching the campaign worktree byte-for-byte, POST→405 everywhere, and the
campaign's own dashboard on 8766 stayed 200 throughout.

**V1.2-R2 completion:** full source-authority model implemented —
1. explicit `--reports-root`
2. explicit `--campaign-api` (POC01 `/api/campaign` summary overlay;
   artifacts stay authoritative for detail views and canonical PnL)
3. unambiguous worktree discovery via `git worktree list --porcelain`
   (exactly one root with campaign state → auto-bind)
4. fail loud: `SOURCE_NOT_CONFIGURED` (HTTP 503) when nothing is found,
   `FAIL_AMBIGUOUS_SOURCE` (HTTP 503) when several roots hold campaign
   state — never a positional pick.

Staleness is always visible: header shows `DATA_SOURCE`,
`REPORTS_ROOT`, `CAMPAIGN_API`, `LAST_PERSISTED_AT`, `STALE_AGE` and a
red `STALE_DATA` banner appears past the committed 900 s threshold.

**Live acceptance (2026-09-07):** server bound to
`.worktrees/poc01-execution/reports` + `--campaign-api
http://127.0.0.1:8766/api/campaign` serves `DATA_SOURCE:
POC01_API+ARTIFACTS`, campaign `poc01-paper-observation-01-001`, state
ACTIVE, canonical realized PnL −19.17547331 == closed-trades PnL sum,
MARKET_SCANS advancing (483+), STALE_AGE 0 s.

**Residual limitation (documented, not hidden):** the campaign API is a
summary overlay; per-event agent messages and per-decision detail remain
`NOT_PERSISTED` by the runtime and are shown as such (never invented).

**Tests:** `test_set_reports_root_redirects_projections`.
**Validator:** `overview` payload assertions plus the live-root smoke
documented above.

---

## Known pre-existing cosmetic defect (unfixed here, out of scope)

`server.py`'s legacy HTML `render_reports_html` builds links with
`escape(r['path'], quote=True)` — correct — but `report_content`'s
`+`-decoding of query params is naive (`urllib.parse.parse_qs` would be
more robust for paths containing `+` or `%` outside the jail's
charset). Not exploitable across the jail boundary; recorded for a
future hygiene pass. No runtime authority involved.

---

## DEF-POC01-OBS-005 — VALID_DAY_SEMANTICS

**Status:** REGISTERED 2026-09-07 · repaired in observation plane only (commit on
`feat/frontend-observability-v1`); runtime untouched (frozen).

**Evidence (live, 2026-09-07T16:10Z):** `/api/campaign` reports
`valid_days=2` and `frequency.days_ge_3=1` (`trades_by_day={'2026-09-06': 3,
'2026-09-07': 0}`) while:
- `2026-09-06` is the BURN_IN launch day (never counts toward the KPI);
- `2026-09-07` (D1) had not rolled over at observation time (partial day);
- the campaign window starts 2026-09-07, so **COMPLETED_VALID_DAYS = 0**.

**Root cause (runtime, read-only audit):**
`src/trading_bot/paper_observation/runtime.py:969` —
`valid_days = [d for d, e in state.daily.items() if e.get("valid", True)]`
counts every observed calendar date with a non-False flag; no finalization
check (day < today), no counted-window check (burn-in exclusion). The daily
entry for the partial day is also marked `valid: True` with
`valid_duration_hours: 0.0`.

**Classification:** observation/reporting defect. Raw daily observations
remain immutable and correct; only the aggregation semantics are wrong.

**Repair scope (allowed):** frontend projection `completed_valid_days()` —
COMPLETED_VALID_DAYS = count(finalized counted UTC days passing the validity
contract); burn-in excluded; partial day excluded; runtime's own values
echoed side-by-side so the mismatch stays visible. Runtime repair deferred to
an authorized POC01 maintenance checkpoint (must not touch the frozen
campaign mid-window).
