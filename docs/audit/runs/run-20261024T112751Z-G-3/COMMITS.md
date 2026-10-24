# G-3 — commit chain

- **Checkout:** `C:/Users/GVLLFR0035/Downloads/ff-wt-mt0004`
- **Branch:** `audit/mt0004-negative-controls`
- **Parent:** `a072da90` (G-1 close-out)
- **Verified commit:** `823901cf`

| # | Commit | Subject | What it changes |
|---|---|---|---|
| 1 | `1c46ce10` | Specify live stop coverage before touching the live paths | `docs/audit/G-3.md`: claim, preflight evidence, 14-row matrix, entry/reduction decision, ACC-G3-01…14 |
| 2 | `a126b88f` | Gate live order entry while leaving reduction free to flatten | `app.py` boundary + `--run-dir` on four commands, `test_live_hot_stop_coverage.py`, the offline probe, DEF-G3-01 |
| 3 | `c55a48b2` | Make the live coverage falsifiable from outside the suite | `g3_mutants.py` (6 mutants), `verify_g3.py` (V-1…V-13) |
| 4 | `823901cf` | Bind the mutation matrix to the code it actually mutated | V-12b: compare the exported `app.py` with the matrix's rev |
| 5 | _record_ | Record what the live stop was verified against | this run's reports and the backlog entry |

## What each commit does, and why in that order

1. **Contract first.** G-2 did the same, and it is what stops "done" from meaning
   "whatever got gated". The matrix in §5 is the artefact the rest has to fill.
2. **Code and its tests together.** The tests were written and run against an
   export of `a072da90` before the fix: 10 failed, 11 passed (COMMANDS.md §5).
   Commit 2 is the first commit where the whole file is green.
3. **Tools after the behaviour.** The mutants and the verifier are only useful
   once there is a stable target; they are separate so a reader can see that
   neither is needed for the production change to work.
4. **The matrix binding.** `c55a48b2` adds tooling to a tree whose `src/` is
   identical to `a126b88f`; V-12b proves that instead of asserting it.
5. **Record.** No code. The backlog entry and these reports.

## Diff shape of the verified commit

```
 src/trading_bot/app.py                          | 269 ++++++++++++++++-----
 tests/unit/test_app_demo.py                     |  16 +-
 tests/unit/test_live_hot_stop_coverage.py       | 341 ++++++++++++++++++++++++
 scripts/audit/g3_live_probe.py                  | 354 ++++++++++++++++++++++++
 scripts/audit/g3_mutants.py                     | 413 +++++++++++++++++++++++
 scripts/audit/verify_g3.py                      | 528 +++++++++++++++++++++++
 docs/audit/G-3.md                               | 285 ++++++++++++++++++
 docs/audit/AUDIT_BACKLOG.yaml                   | G-3 entry, next_ready
```

`src/trading_bot/autonomous/hot_stop.py` is **not** in the diff: G-3 reuses
G-1's gate and would rather fail its own V-10 than rewrite the thing both prior
gaps verified.
