# WP-003-08 — Run report

**Objective:** make `ruff format --check .` exit 0 without touching a single certified byte,
and leave behind a guard that keeps the exemption list honest.

**Result in one line:** format gate `433 → 0` through 24 exact-path exclusions in
`[tool.ruff.format]` only; the 24 files are byte-identical to `1d2192b0`; the suite is
identical to base at node level (0 new, 0 fixed, 103 shared red nodes); lint and mypy
unchanged; CI not run.

**Mode:** offline apart from two read-only remote queries used to restore `origin`.
No trading, no `main` write, no merge, no rebase, no force-push, no threshold moved, no
certificate regenerated.

---

## 0. Workspace incident, before any work package step

This run began by finding the entire workspace emptied. The finding is part of the record
because it conditions every number below.

| observation | measurement |
| --- | --- |
| all working trees under `Downloads/bot*` | empty: 30+ worktrees plus the primary tree kept only their `.git` pointer file |
| primary `.git` | `HEAD`, `config`, `refs/`, `index`, `logs/`, `packed-refs` absent; only `objects/` survived |
| surviving objects | 147 MB — 1 219 commits, 7 812 trees, 10 832 blobs |
| integrity of those objects | `git fsck --connectivity-only` → exit 0, no missing or corrupt object, 294 dangling (normal) |
| deleted `.venv` | `python.exe` survived, `pyvenv.cfg` and every package did not |
| timestamp of the wipe | 19:26–19:27 local, ~16 minutes before this session resumed |

**Recovery, all reversible and all from the object database:**

1. `git init` in place (objects untouched), `core.autocrlf=false`;
2. refs rebuilt from the SHAs recorded in the WP-003-07 report and confirmed against the
   remote: `main=1d2192b0`, `recovery/trunk-format-001=89da583e`, `origin/main=5e6f9632`;
3. `git reset --hard main` restored 1 951 tracked files;
4. `git worktree add ../ff-wt-trunkfmt recovery/trunk-format-001` restored the branch tree
   (1 965 files, tip `89da583e`, its three commits intact);
5. `origin` re-added as `https://github.com/Extr3sao/bot_crypto.git` — verified rather than
   guessed: `git ls-remote` returns `main=5e6f9632` and
   `recovery/trunk-format-001=89da583e`, the exact SHAs this repository expects;
6. `uv sync --frozen --all-extras --dev` rebuilt the destroyed `.venv` from `uv.lock`
   (ruff 0.15.20, mypy 2.1.0, Python 3.11).

**What could not be recovered.** The wipe removed files Git never tracked: every gitignored
artifact (`reports/*`, `data/raw/*`, `data/st6/ST6_HEALTH_STATUS.json`) and any uncommitted
work that other lanes may have had in those trees. Committed work is intact — the branch
tip, its evidence bundle and the format commit all reproduce byte for byte. The loss of
ignored artifacts is why the *historical* suite counts no longer reproduce (§4).

## 1. State measured before any write

| ref | sha | note |
| --- | --- | --- |
| `origin/main` | `5e6f9632` | published |
| `main` | `1d2192b0` | untouched, 259 commits ahead of `origin/main` |
| `recovery/trunk-format-001` | `89da583e` | published by WP-003-07, unchanged |
| base commit for every comparison | `1d2192b0` | linear history, zero merge commits |

Gates on the branch tip before any change: format **24 files would be reformatted**
(exit 1), lint **100**, mypy **253 errors in 29 files**. The 24 flagged files are exactly the
24 declared in `wp00307/EXEMPTIONS.json` (`flagged_not_declared` and `declared_not_flagged`
both empty), and all 24 hash to their `1d2192b0` bytes — the pins were live before the
change, not inferred.

## 2. The change

One file: `pyproject.toml`, inside `[tool.ruff.format]` only.

- 24 exact file paths, sorted, generated from `EXEMPTIONS.json` by a script rather than
  typed by hand, so a transcription slip cannot exist;
- no directory, no glob, no `[tool.ruff.lint]` change, no top-level `exclude`;
- `extend-exclude = ["*.sh"]` and `force-exclude = true` untouched.

Plus two scripts and one test, all new files:

| file | purpose |
| --- | --- |
| `scripts/verify_format_exemptions.py` | the guard: 8 assertions, 11 negative controls |
| `scripts/make_format_gate_reports.py` | the comparison generator used for §4 and §5 |
| `tests/unit/test_format_exemption_guard.py` | runs the guard inside the ordinary suite |

No trading, risk, sizing, execution or accounting file is touched. No certificate, pin
record or historical hash is written.

## 3. Sequence, with exit codes

| # | command | exit | result |
| --- | --- | --- | --- |
| 1 | `ruff format --check .` @ `89da583e` | 1 | `24 files would be reformatted, 785 already formatted` — reproduces WP-003-07 |
| 2 | `ruff format --check .` @ base `1d2192b0` | 1 | `433 would be reformatted, 375 already formatted` — reproduces the trunk baseline |
| 3 | `ruff format --check .` after the change | **0** | `788 files already formatted` |
| 4 | `ruff format --check --config "format.exclude=[]" .` | 1 | `24 files would be reformatted` — clearing the exclusions flags exactly the 24, so no entry is decorative and nothing else is hidden |
| 5 | `ruff check .` | 1 | **100** errors, identical to base **100** |
| 6 | `mypy .` | 1 | **253** errors / 29 files / 806 checked; base **253** / 29 / 801 |
| 7 | `verify_format_exemptions.py --self-test --json` | **0** | 8/8 checks, 11/11 controls rejected |
| 8 | `pytest tests/unit/test_format_exemption_guard.py` | 0 | 2 passed |
| 9 | `pytest -m "not slow and not market"` @ base, path-matched worktree | 1 | `89 failed, 3205 passed, 31 skipped, 14 errors` in 703 s |
| 10 | same @ HEAD with the change | 1 | `89 failed, 3205 passed, 31 skipped, 14 errors` in 474 s |
| 11 | node-id diff of 9 vs 10 | **0** | 0 new, 0 fixed, **103 shared** red nodes, identical counts |

## 4. The suite, and an honest account of the baseline

The comparison is by node id, not by count, and both sides now run in **path-matched
trees** (`ff-wt-base` vs `ff-wt-trunkfmt`) with their own `uv sync` venv.

**Why path-matched matters.** The first base run happened in the recovered primary tree,
whose path is `…/bot freebuff`. That run produced 105 red nodes versus 103 at HEAD, and the
single "new" node was
`test_st6_scheduler::test_the_task_definition_matches_the_repository_and_the_host`, whose
failure message is `assert '…\ff-wt-trunkfmt' in '…\bot freebuff\.venv\scripts\python.exe'`.
That test compares the host's registered scheduled task with the repository path; it cannot
pass in any tree that is not the registered one, and the test source is one of the 24 pinned
files (byte-identical on both sides). Re-running base from a worktree at the same kind of
path removes the artefact: **0 new nodes, 0 fixed, 103 shared.**

**Why the historical 95 does not reproduce.** WP-003-07 recorded 95 red nodes; the same
commit now yields 103. The difference is the wipe: 44 of the red nodes fail with
`FileNotFoundError` for files that were never tracked —
`reports/profitability_gate035/*`, `reports/rfc035/search_round_3/*`,
`data/raw/alpha003/price/*`, `data/st6/ST6_HEALTH_STATUS.json` — each confirmed with
`git check-ignore -v` and `git ls-files` (empty). Those artifacts existed on disk during
WP-003-07 and cannot be recreated from Git. This WP therefore claims only what it can
prove: **the change adds no red node relative to base in one identical environment.** The
absolute distance to green still has to be closed by the lane that owns each artifact.

## 5. What the exemption actually buys

Measured, not asserted. A scratch worktree at HEAD had all 24 exempted files reformatted
with `ruff format --config "format.exclude=[]"`, and the suite was run again:

| run | red nodes | change |
| --- | --- | --- |
| base (`1d2192b0`, path-matched) | 103 | — |
| HEAD, exclusions active | 103 | 0 |
| HEAD, exclusions cleared, all 24 formatted | 106 | **+3** |

The three certification tests that turn red are
`test_forward_collector_replay::test_the_capture_code_still_matches_the_certified_commit`,
`test_cost_barrier_adversarial::test_the_certification_record_digests_content_not_a_checkout`
and `test_cost_barrier_gate::test_a_missing_required_input_blocks_rather_than_fails`.
Three more live outside the `not slow` filter and are marked `@pytest.mark.slow`
(`test_recovery_determinism::test_the_clean_checkout_rehearsal_passes_on_this_commit`,
`…::test_a_sabotaged_evidence_copy_is_detected`,
`…::test_a_sabotaged_committed_input_is_detected`); formatting the same files with the
filter removed turns all three red, which is the six WP-003-07 counted. The exemption is
therefore load-bearing for six tests, and the alternative to exempting is re-certifying six
records — a decision about other lanes' evidence, not a formatting decision.

## 6. The guard

`scripts/verify_format_exemptions.py` fails on each of these, and `--self-test` proves it
fails by mutating the configuration in memory and requiring rejection:

1. configured set ≠ declared set (extras, gaps, duplicates);
2. an entry that is a glob, a directory, a non-`.py` file, a missing file, or undeclared;
3. a top-level or `[tool.ruff.lint]` exclusion added to compensate;
4. `ruff format --check .` not green;
5. clearing the exclusions no longer flags exactly the 24 (decorative or hidden entries);
6. any exempted file whose SHA-256 differs from its `1d2192b0` bytes;
7. any exempted file missing from `ruff check --show-files` (linter still sees it);
8. any committed record under `data/` changed since the base commit.

Result: `8/8` checks pass, `11/11` controls rejected. `tests/unit/test_format_exemption_guard.py`
runs the same guard in the suite, so drift fails CI without anyone remembering to run a
script.

## 7. CI and delivery

`CI_STATUS = NOT_PERFORMED`. `.github/workflows/ci.yml` triggers on `push: [main]` and
`pull_request: [main]`; this branch is not a PR and no GitHub Actions run was started, so
no run is claimed.

The branch `recovery/trunk-format-001` is published to `origin` as a fast-forward from
`89da583e`. No force-push. `main` and `origin/main` are untouched at `1d2192b0` / `5e6f9632`.

## 8. Status

| field | value |
| --- | --- |
| `WP_STATUS` | **PASS** |
| `FORMAT_CHECK` | **PASS** (exit 0, 788 formatted, 24 justified exclusions) |
| `CONTENT_PINS` | **PASS** (24/24 SHA-256 equal to `1d2192b0`; six dependent tests identified) |
| `NEW_TEST_FAILURES` | **0** (node-id diff, path-matched runs) |
| `NEW_LINT_ERRORS` | **0** (100 → 100) |
| `NEW_MYPY_ERRORS` | **0** (253 → 253) |
| `CERTIFICATION_HISTORY` | **UNCHANGED** (`git diff 1d2192b0..HEAD -- data/` → 0 files) |
| `TRUNK_STATUS` | **PARTIAL** — format debt closed; lint 100, mypy 253, 103 red nodes, coverage and `pip-audit` still open |
| `CI_STATUS` | **NOT_PERFORMED** |
| `RUNTIME_STATUS` | **NOT_PERFORMED** — no paper runtime was started this WP |
| `FALSE_SUCCESS` | **0** |

## 9. Defects in this run

- **The workspace was empty at start** (§0). Recovered from objects; ignored artifacts and
  any uncommitted work in sibling trees are gone. Nothing in this report depends on them.
- **The first base comparison was path-confounded** (§4) and was discarded in favour of a
  path-matched base run rather than explained away.
- `git init` in place left `core.autocrlf` unset in the primary tree until it was set
  explicitly; no digest test depends on it (`-text` rules and `autocrlf=false` hold in every
  tree used here).
