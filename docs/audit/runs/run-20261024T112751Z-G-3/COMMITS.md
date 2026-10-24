# G-3 — commit chain

- **Checkout:** `C:/Users/GVLLFR0035/Downloads/ff-wt-mt0004`
- **Branch:** `audit/mt0004-negative-controls`
- **Parent:** `a072da90` (G-1 close-out)
- **Verified commit:** `9eeb8e87`

| # | Commit | Subject | What it changes |
|---|---|---|---|
| 1 | `1c46ce10` | Specify live stop coverage before touching the live paths | `docs/audit/G-3.md`: claim, preflight evidence, 14-row matrix, entry/reduction decision, ACC-G3-01…14 |
| 2 | `a126b88f` | Gate live order entry while leaving reduction free to flatten | `app.py` boundary + `--run-dir` on four commands, `test_live_hot_stop_coverage.py`, the offline probe, DEF-G3-01 |
| 3 | `c55a48b2` | Make the live coverage falsifiable from outside the suite | `g3_mutants.py` (6 mutants), `verify_g3.py` (V-1…V-13) |
| 4 | `823901cf` | Bind the mutation matrix to the code it actually mutated | V-12b: compare the exported `app.py` with the matrix's rev |
| 5 | `9eeb8e87` | Keep the probe and the verifier inside the project's own type gate | byte comparison for V-10 (the code-page defect), dirty-source identity, mypy/bugbear clean |
| 6 | _record_ | Record what the live stop was verified against, and where it stops | this run's reports and the backlog entry |

## What each commit does, and why in that order

1. **Contract first.** G-2 did the same, and it is what stops "done" from meaning
   "whatever got gated". The matrix in §5 is the artefact the rest has to fill.
2. **Code and its tests together.** The tests were written and run against an
   export of `a072da90` before the fix: 11 failed, 10 passed (COMMANDS.md §4).
   Commit 2 is the first commit where the whole file is green.
3. **Tools after the behaviour.** The mutants and the verifier are only useful
   once there is a stable target; they are separate so a reader can see that
   neither is needed for the production change to work.
4. **The matrix binding.** `c55a48b2` adds tooling to a tree whose `src/` is
   identical to `a126b88f`; V-12b proves that instead of asserting it.
5. **The verifier's own defects.** Its first run failed V-10 on a byte-identical
   file (UTF-8 decoded through the Windows code page) and V-12 because the matrix
   was not in the report it was given. Both are fixed here, not explained away.
6. **Record.** No code. The backlog entry and these reports.

## Diff shape, `a072da90..HEAD`

```
 docs/audit/AUDIT_BACKLOG.yaml             |  77 +++-
 docs/audit/G-3.md                         | 221 +++++++++++
 scripts/audit/g3_live_probe.py            | 362 ++++++++++++++++++
 scripts/audit/g3_mutants.py               | 389 +++++++++++++++++++
 scripts/audit/verify_g3.py                | 593 ++++++++++++++++++++++++
 src/trading_bot/app.py                    | 269 +++++++++++---
 tests/unit/test_app_demo.py               |  16 +-
 tests/unit/test_live_hot_stop_coverage.py | 382 +++++++++++++++++
 8 files changed, 2248 insertions(+), 61 deletions(-)
```

`src/trading_bot/autonomous/hot_stop.py` is **not** in the diff: G-3 reuses
G-1's gate and would rather fail its own V-10 than rewrite the thing both prior
gaps verified.

## Uncommitted, deliberately

`uv.lock`: `uv run` (without `--frozen`) rewrote it once during preflight
(+546 lines of new resolution data, no dependency change). It was restored with
`git checkout -- uv.lock`, and nothing in this run depends on it.
