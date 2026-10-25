# WP-003-07 — Run report

**Objective:** mechanical sanitation of the trunk — apply the project formatter, prove it is
representational, and change nothing else.

**Mode:** offline. No network, no credentials, no trading, no `main` write, no merge, no rebase,
no force-push, no coverage/lint/type threshold touched.

**Result in one line:** 409 files reformatted and proven equivalent; 24 files deliberately left
byte-identical because committed certification records pin them; suite identical to base at
node level; CI not run.

---

## 1. State measured before any write

| ref | sha | published |
| --- | --- | --- |
| `origin/main` | `5e6f9632` | yes |
| `main` | `1d2192b0` | **no** (259 commits ahead) |
| `recovery/trunk-sync` | `1d2192b0` | yes |
| `origin/recovery/trunk-sync` | `1d2192b0` | yes |
| `recovery/wp00303` | `08c5d9d2` | yes |
| `fix/ci-smoke-pwsh` | `9682ee1b` | yes |
| `wp/isolation-005` | `fbcadc30` | yes |

`git merge-base --is-ancestor 1d2192b0 <any recovery branch>` → true on every one, and
`git merge-base 1d2192b0 wp/isolation-005` is `1d2192b0` itself. History is linear with zero
merge commits, so `1d2192b0` is the whole trunk and no reconciliation was needed. Base chosen:
`1d2192b0`.

Environment: Windows 11, Python 3.11.15, repo `.venv` (`ruff 0.15.20`, `mypy 2.1.0`), 30+
worktrees present, 4.0 GB free on `C:`. `ff-wt-trunk` and `ff-wt-trunk-ops` both carry a
modified `data/st6/RFC047_RUNTIME_VERIFICATION.json`; neither was touched. A fresh worktree
`ff-wt-trunkfmt` was created from `1d2192b0` on branch `recovery/trunk-format-001`.

## 2. Sequence, with exit codes

| # | command | exit | result |
| --- | --- | --- | --- |
| 1 | `ruff format --check .` @ `1d2192b0` | 1 | `433 would be reformatted, 374 already formatted` — reproduces the recorded baseline |
| 2 | `ruff format .` | 0 | `433 files reformatted` |
| 3 | `ruff format --check .` | 0 | 807 already formatted |
| 4 | `verify_trunk_format.py --base 1d2192b0 --head HEAD` | 1 → fixed → 0 | first run reported `432/433` AST equality and 19 files with “string content changed” |
| 5 | `ruff check .` | 1 | 100 errors — unchanged |
| 6 | `mypy .` (the CI command) | 1 | 253 errors / 29 files / 801 checked — unchanged |
| 7 | `pytest -m "not slow and not market"` @ base | 1 | **81 failed, 3213 passed, 31 skipped, 14 errors, 558 s** |
| 8 | same @ head (433 formatted) | 1 | **87 failed, 3207 passed** — 6 new red nodes |
| 9 | node-id diff of 7 vs 8 | 1 | `REGRESSION`: 6 new, 0 fixed |
| 10 | six pin tests after exempting 12 + 12 files | 0 | `6 passed` |
| 11 | same @ head (409 formatted) | 1 | **81 failed, 3213 passed, 31 skipped, 14 errors, 552 s** |
| 12 | node-id diff of 7 vs 11 | 0 | `NO_NEW_FAILURES`: 0 new, 0 fixed, 95 identical red nodes |
| 13 | `verify_trunk_format.py --expect-files 409` | 0 | `PASS_WITH_DECLARED_RESIDUAL`, 408/409 strict AST |
| 14 | `verify_trunk_format.py --self-test` | 0 | 6/6 negative controls rejected |

## 3. Two defects in my own work, found and fixed

**The verifier was wrong before it was right.** The first version compared string tokens
pairwise by index and evaluated them with `ast.parse(..., mode="eval")` expecting a
`Constant`. That misclassified 19 files: f-strings parse to `JoinedStr` (not `Constant`), and
RUFF **joins implicit string concatenation**, so the token *count* changes and pairwise
comparison stops meaning anything. Both are representation, not content. The fix merges
adjacent literals before comparing and fingerprints the evaluated expression instead of the
token. After the fix: 152 representation-only rewrites, 0 content changes.

**A shell slip with a real consequence.** To revert the pinned files I built the path list with
a Python one-liner that received a `msys` path Windows could not open; it failed, `$LOCKED` was
empty, and `git checkout 1d2192b0 --` with an empty pathspec behaved as a *branch switch*,
leaving `HEAD` detached at `1d2192b0` where the following `git commit --amend` rewrote that
commit into a new dangling sha `e040da23`. Recovery was immediate and verified:
`git checkout recovery/trunk-format-001`, branch back at its pre-slip sha, `main` still
`1d2192b0`, `origin/main` still `5e6f9632`, no ref pushed, `e040da23` unreferenced. The redo
used a file-based list, `tr -d '\r'`, a non-empty guard and a branch guard. Nothing about the
delivered commit comes from the detached state.

## 4. An inherited claim that does not hold

`wp00305` recorded **4 collection errors at `1d2192b0`**, attributed to four tests importing
`trading_bot.ops`. It does not reproduce:

- `git grep -n "trading_bot\.ops|from \.ops|import ops" 1d2192b0 -- src tests` → **no match**;
- `pytest --collect-only` at `1d2192b0` → exit 0, **3339 tests, 0 errors**;
- the four named modules (`test_lab_ops_hardening`, `test_pid_identity`, `test_supervisor`,
  `test_forward_exit_contract`) run **73 passed** at that sha.

The `ops` reference exists only on the branch (`supervisor.py` and `tests/unit/ops/`). So the
trunk could already collect, and the `ops` port that WP-003-03 made for this reason was
unnecessary *for collection* — the port is still the right call for other reasons, but not this
one. Recorded in `INTEGRATION_BASELINE.json → gates.collection.corrects_inherited_claim`.

The other inherited number, **428 vs 433**, does hold and is now fully explained: `ff-wt-min`
at `baf5b560` prints 433 for the whole tree and has 5 untracked `.py` files under `.tmp/`, so
tracked = 428.

## 5. What the 6 regressions actually were

Not logic. **Content pins.** Six tests certify that the bytes of specific producer scripts are
the bytes that produced a committed evidence artefact. Formatting those scripts invalidates the
certification, and the tests say so with unusual clarity
(`“the artefact must be regenerated and re-verified”`). The remedy is to re-certify — a
decision that rewrites committed evidence — so this work package exempts the pinned files
instead and reports the gate at 24 rather than pretending it is 0.

## 6. CI

`NOT_PERFORMED`. `.github/workflows/ci.yml` triggers on `push: [main]` and
`pull_request: [main]` only; this branch is published without a PR on purpose (promoting to
`main` is a later decision), and there is no `gh` CLI or token on this host. No run was started,
so no run is claimed.

## 7. Deliverables

`reports/ai-bots/WP-PAPER-QUOTE-GAP-002/wp00307/`: `INTEGRATION_BASELINE.json`,
`FORMAT_CHANGE_REPORT.md`, `FORMAT_EVIDENCE.json`, `REGRESSION_COMPARISON.json`,
`EXEMPTIONS.json`, `PYTHON_PINS.json`, `TRUNK_SANITATION_PLAN.md`, and this report with its
`RUN_REPORT.json` / `FINAL_REPORT.md` / `FINAL_REPORT.json` siblings. Tooling:
`scripts/verify_trunk_format.py`, `scripts/find_python_pins.py`.
