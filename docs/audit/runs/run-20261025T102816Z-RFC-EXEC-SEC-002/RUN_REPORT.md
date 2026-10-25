# RUN_REPORT — RFC-TAP-EXEC-SEC-002

- **Run id:** `run-20261025T102816Z-RFC-EXEC-SEC-002`
- **Branch:** `audit/mt0004-negative-controls`
- **Started:** 2026-10-25T10:28:16Z
- **Verdict:** `P0_ORDER_AUTHORIZATION_VERIFIED_SCOPED`
- **Production state:** `LIVE_NO_GO`, `PRODUCTION_READY = false`
- **Real trading:** none. No exchange was contacted. No credentials were used.
- **Push / deploy:** none.

## 1. Commits

| WP | Commit | Subject |
|---|---|---|
| WP-00 | `368bfcc9` | Record the entrypoints, payloads and gaps this RFC has to close |
| WP-01 + WP-02 | `de72ad2a` | Derive live order authorisation from the order, not its name |
| WP-03 | `2d512920` | Verify the order authorisation from a clean export, not from its tests |
| Evidence | `09a44c21` | Report the verified order authorisation and keep live trading closed |
| Final export | `f4cc048d` | Write the hash manifest with LF so sha256sum -c can verify it |

WP-01 and WP-02 share one commit. The typed sink context is the seam both need:
a confirmation check at the sink requires the intent and the category, and a
category without the confirmation check would leave `run --auto-trade`
unconsented. Splitting it would have produced a commit that cannot pass its own
tests. This is a documented deviation from "commits separados por WP"; the
acceptance criteria do not depend on commit granularity.

The final verification ran on `f4cc048d`, which contains `2d512920`, the first
copy of these reports and the LF fix for the hash manifest. Its code is
identical to `2d512920` for every file the verifier checks, and those hashes
match `de72ad2a` (`ARTIFACTS.sha256`, verified with `sha256sum -c` on a Windows
checkout). The evidence commit after `f4cc048d` only updates the reports and
their hashes; no source file changes.

## 2. WP-00 — read-only audit

`WP00_RUNTIME_MAP.md` records:

- the three RFC reference commits are a chain:
  `82e8b3ac` → `1b4e1896` → `43e1ce2c`;
- the **seven** live sinks and their real payloads;
- the P0 classification table: `opens_risk` was a caller boolean, and
  `close-position`, `set-tpsl`, futures `CLOSE` and spot `sell` were exempt;
- the adapter contract: `place_order` always sends `tradeSide`/`reduceOnly`,
  `flash_close_position` sends only `positionId`, `place_position_tpsl` has no
  side and no `reduceOnly`, and `get_pending_positions` does not return TP/SL
  levels;
- the six gaps `DEF-EXEC-001..006`;
- the baseline suite: **113 passed in 108.00 s**, exit 0.

An incidental `uv run` refreshed `uv.lock` during the baseline. The write was
not part of the RFC and was reverted with `git checkout -- uv.lock`; every later
command used `uv run --frozen`.

## 3. WP-01 — explicit confirmation

- `run` declares `--confirm-live`.
- `_cmd_run` refuses when `--auto-trade` is combined with `live` **or**
  `shadow_live` and the flag is absent: stderr, `exit 2`, before the hot stop is
  built, before the scanner runs and before an exchange client exists.
  `shadow_live` is included because the order functions read
  `settings.runtime.mode`, not the CLI mode.
- The sink re-checks `intent.requires_confirmation` against `confirm_live`; a
  direct call that skipped the CLI check is still denied.
- Paper/demo are not blocked by the flag.

## 4. WP-02 — provable reductions

New module `src/trading_bot/execution/order_authorization.py`:

- `OrderIntent`, `OrderPrimitive`, `PositionState`, `VenueCapabilities`;
- `classify_order` → `OPEN_OR_INCREASE` / `PROVEN_REDUCTION` / `UNKNOWN` with a
  named rule (`R-REDUCE-ONLY`, `R-FLASH-CLOSE`, `R-CLOSE-QTY-EXCESS`,
  `R-CLOSE-HEDGE-AMBIGUOUS`, `R-CLOSE-STALE`, `R-SPOT-SELL-NO-VENUE-PROOF`,
  `R-TPSL-NOT-MONOTONIC`, …);
- `reduction_payload_violations` and `build_reduction_payload_guard`.

`_live_order_boundary` now takes a required typed context — `intent`, `position`,
`capabilities`, `settings`, `confirm_live` — and has no defaults for them. The
order is:

1. classify (a classifier exception denies outright);
2. `PROVEN_REDUCTION` → yield, no gate, no stop;
3. confirmation (when the entrypoint requires it);
4. hot stop (marker, then process switch);
5. `_evaluate_live_gate` (all ten checks);
6. `HotStopGate.order_boundary` (lock);
7. append the decision to `live_order_authorizations.jsonl`.

`BitunixFuturesClient.place_order` and `flash_close_position` accept a
`payload_guard` invoked immediately before `_request`; a violation raises
`LiveOrderAuthorizationError` and the CLI returns 2 with zero calls.

`set-tpsl` is `UNKNOWN` because the positions endpoint does not return the live
TP/SL levels, so "this change tightens protection" is not checkable. A spot
`sell` is `UNKNOWN` because no broker-enforced reduce-only primitive exists for
spot in this adapter.

The ten gate checks, `hot_stop.py` and the gate module are unchanged.
`hot_stop.py` is byte-identical to `76cfca23…`.

## 5. Tests

| Suite | Where | Result |
|---|---|---|
| Baseline before any edit | worktree `43e1ce2c` | **113 passed** in 108.00 s |
| New classifier + boundary + payload unit tests | `tests/unit/test_order_authorization.py` | **43 passed** |
| Program cases T01-T11 | `tests/unit/test_exec_sec_process.py` | **20 passed** |
| P0 gate enforcement + G-3 hot-stop coverage + CLI + demo + journal + audit guard | worktree | **190 passed** in 148.70 s |
| Affected suite on the export | verifier V-20 | **182 passed** in 111.43 s |
| Mutation matrix | verifier V-21 on `2d512920` | **14/14 killed** |

The unit count includes one test added after the first mutation run: M12 (stale
flash-close) survived because only the place-order staleness branch was tested.
The missing case was added, not the mutant removed.

## 6. Separate verification

`scripts/audit/verify_exec_sec.py` exports the commit with `git archive`, runs
each of its own 23 scenarios in a fresh process, performs nine AST checks,
re-runs the affected suite and the mutation matrix.

| Revision | Checks | Verdict |
|---|---|---|
| `43e1ce2c` (before) | 8/21 | `NOT_VERIFIED` |
| `2d512920` (code + verifier) | 21/21 | `P0_ORDER_AUTHORIZATION_VERIFIED_SCOPED` |
| `f4cc048d` (final export) | **21/21** | `P0_ORDER_AUTHORIZATION_VERIFIED_SCOPED` |

The before run is real, not reconstructed:
[`verification-before.json`](verification-before.json). On the before tree the
`run --confirm-live` scenarios exit 2 because argparse does not know the flag,
not because the gate refuses; V-12 (positive control) is red for that reason.
The meaningful before evidence is in the place-order rows: no position, excess
quantity, hedge mode, wrong side, spot `sell`, `set-tpsl`, a dropped
`reduceOnly` and an injected flash-close side each produced **one broker call**.

Independence is **procedural**: a different artefact with its own scenarios,
written by the same author. It is not a second-person audit.

## 7. Failures found during the run

| ID | Failure | Resolution |
|---|---|---|
| EXEC-F-01 | M12 (stale flash-close) survived the first matrix: only the place-order staleness branch had a test. | Added `test_flash_close_with_a_stale_position_is_unknown`; 14/14 killed. |
| EXEC-F-02 | The first verifier draft shared one process across scenarios. `run_hot_stop` engaged the module-singleton kill switch and every later scenario was refused by the stop, producing three false failures. | One subprocess per scenario. This is also a stronger independence property. |
| EXEC-F-03 | The first verifier draft did not apply `GATE-001..008` breaks to settings; only `GATE-009/010` and `gate_crash` had an effect. | Added `_break_settings` with the eight configuration breaks. |
| EXEC-F-04 | P0/G-3 tests asserted that `set-tpsl` and spot `sell` reach the broker with a rejecting gate — the exact behaviour REQ-03/REQ-04 removes. | Those rows moved to `UNKNOWN_POINTS`; the new expectation is 0 calls. Documented in BEFORE_AFTER §4. |
| EXEC-F-05 | The G-3/P0 probes closed a LONG position with `--side buy`. The classifier correctly refused it (wrong side). | The probe now closes a long with `sell` and supplies a matching position. |
| EXEC-F-06 | `uv run` rewrote `uv.lock` during the baseline. | Reverted; `--frozen` thereafter. |
| EXEC-F-07 | `ARTIFACTS.sha256` was written with the platform newline; on Windows `sha256sum -c` read a trailing CR in every path and verified nothing. | The manifest is now written with LF and `sha256sum -c` reports ten OK lines. |

No failing check was weakened. The two P0/G-3 expectation changes are required
by the RFC and are tested in both directions (proven close still 1 call,
unproven close 0).

## 8. Defects

Closed by this RFC:

- **DEF-P0-04** — `run --auto-trade` had no `--confirm-live`.
- **DEF-EXEC-001** — live dispatch had no per-invocation consent.
- **DEF-EXEC-002** — the sink trusted an `approved` derived from CLI flags.
- **DEF-EXEC-003** — reduction exemption was a caller boolean based on a name.
- **DEF-EXEC-004** — no payload-level revalidation.
- **DEF-EXEC-005** — `set-tpsl` was exempt although protection can be weakened.
- **DEF-EXEC-006** — no per-decision authorization trace.

Still open, out of scope:

- **DEF-P0-03** — `LiveTradingGate._data_dir` is stored and unused; GATE-006
  resolves the SQLite path against the cwd.
- **G-4** — `run --demo` → `paper_cycle.py` has its own broker call and still
  has neither the gate nor the stop.
- **GATE-009/010** cannot fail through configuration; they are only exercised by
  a forced check failure.
- **Hedge mode** is refused as `UNKNOWN`; no hedge-mode venue was exercised.

## 9. Limitations

1. **No exchange accepted a payload.** Every sink is a recorder. The proof is
   about the payload the process would send, not about Bitunix's acceptance.
2. **Same author.** Procedural separation, not an organisational one.
3. **One process per scenario** is stronger for isolation but does not reproduce
   a long-lived process's scanner cadence.
4. **The position snapshot is not the guarantee.** The exemption rests on the
   venue primitive (`reduceOnly` / close-by-id); the snapshot is a precondition.
   A race between read and send cannot turn a `reduceOnly` close into an
   opening order, but it can make the order fail at the venue.
5. **`run --demo` (G-4)** remains the largest uncovered route.

## 10. Evidence

| Artefact | Path |
|---|---|
| Runtime map (WP-00) | [`WP00_RUNTIME_MAP.md`](WP00_RUNTIME_MAP.md) |
| Coverage matrix | [`COVERAGE_MATRIX.md`](COVERAGE_MATRIX.md) |
| Before / after | [`BEFORE_AFTER.md`](BEFORE_AFTER.md) |
| Verification (after) | [`verification.json`](verification.json) |
| Verification (before) | [`verification-before.json`](verification-before.json) |
| Mutation matrix | [`mutations.json`](mutations.json) |
| Artifact hashes | [`ARTIFACTS.sha256`](ARTIFACTS.sha256) |
| Baseline | [`baseline/`](baseline/) |
| Final report | [`FINAL_REPORT.md`](FINAL_REPORT.md) |

`ARTIFACTS.sha256` is produced by the verifier and covers the source, tests,
scripts and RFC at `2d512920`. `EVIDENCE.sha256` covers the run directory.
