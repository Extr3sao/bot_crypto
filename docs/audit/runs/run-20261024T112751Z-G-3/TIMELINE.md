# G-3 — timeline

All times local (UTC+2); the run id is the UTC stamp `20261024T112751Z`.

| Time | What happened | Result |
|---|---|---|
| 13:00 | Preflight at `a072da90`: branch, clean tree, `HotStopGate` import graph | gate only in `autonomous/runtime.py` |
| 13:05 | Baseline suite | **1 failed, 81 passed** — a stale G-2 test (DEF-G3-01) |
| 13:10 | Wrote `G-3.md` before touching code | contract committed (`1c46ce10`) |
| 13:12 | Probe v1, marker present, pre-fix code | **6/6 entrypoints reached the broker** |
| 13:14 | First G-3 tests run against an export of `a072da90` | **11 failed, 10 passed** — the intended reds |
| 13:18 | Implementation: boundary + `--run-dir` + entry/reduction split | beacon: 4 entrypoints 0 calls, 2 reduction paths 1 call |
| 13:22 | Focal suite green; app suites green; autonomous suites green | 21 / 70 / 360 |
| 13:19 → 13:26 | Mutation matrix, worktree rehearsal | 6/6 killed, 336 s |
| 13:30 | First verifier run at `823901cf` | **12/15 — G3_PARTIAL** |
| 13:32 | Diagnosed V-10: `git show` decoded as cp1252, arrows became two characters; file was byte-identical | verifier defect, not a code defect |
| 13:33 | Diagnosed V-12: the matrix had not been merged into `RUN_REPORT.json`; the verifier read `variants` from it | report defect |
| 13:35 | `uv run` had rewritten `uv.lock` (+546 lines, no dependency change) | restored with `git checkout -- uv.lock`; `--frozen` thereafter |
| 13:36 | Fixed the verifier: bytes instead of strings, dirty-source identity, V-12b binding; fixed probe mypy errors | `9eeb8e87` |
| 13:41 | Mutation matrix at `9eeb8e87` | 6/6 killed, 307.8 s |
| 13:44 | Evidence: before/after matrices, red focal run, stale-test run | `evidence/` |
| 13:49 | Final verifier at `9eeb8e87` | **15/15 — G3_VERIFIED_SCOPED**, 261.3 s |

## The two failures worth keeping

**The verifier failed first, and that is the point of having it.** V-10 reported
a modified gate on a file with an identical sha256; the cause was Python decoding
`git show` through the console code page. Had the verifier been written to read
the implementation's summary instead of re-deriving, the mismatch would never
have surfaced — and a genuinely modified `hot_stop.py` would have been just as
invisible.

**V-12 failed because the evidence was incomplete, not because the mutants
survived.** The matrix had been run and stored separately; the verifier was
pointed at a report that did not carry it. The fix was to merge the matrix into
the report, not to relax the check.

## What was deliberately not done

- No `hot_stop.py` edit (V-10 exists precisely to keep it that way).
- No `LiveTradingGate` activation (DEF-G3-03, admission policy).
- No `paper_cycle.py` change (G-4).
- No disarm path, no new network surface, no dependency.
