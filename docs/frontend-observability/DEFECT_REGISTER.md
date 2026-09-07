# FRONTEND-OBSERVABILITY — DEFECT REGISTER

Maintained on `feat/frontend-observability-v1`. Runtime authority is never
modified by these fixes (read-only projections/server only).

---

## DEF-FE-001 / DEF-FE-002 — PRE-EXISTING REFERENCES

**Status:** NOT_FOUND_IN_REPOSITORY (as of 2026-09-07).

A repo-wide and worktree-wide search found no prior registration of
DEF-FE-001 or DEF-FE-002 anywhere in `docs/`, `scripts/`, or `tests/`
(they are referenced only in the checkpoint instructions that introduced
DEF-FE-003). They are recorded here as `UNVERIFIED — origin external`;
no claims are made about their content or resolution.

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

**Status:** MITIGATED (2026-09-07, same commit).

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

**Residual limitation (documented, not hidden):** `--campaign-api` /
live-polling of the runtime's `/api/campaign` endpoint is NOT implemented
in this checkpoint. The frontend remains artifact-file-based (pull, not
push). A reader pointed at a live worktree still sees the last persisted
snapshot, not an in-memory live view. Deferred to a future checkpoint as
a non-authority observability improvement.

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
