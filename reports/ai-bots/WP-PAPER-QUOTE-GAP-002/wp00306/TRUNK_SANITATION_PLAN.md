# Trunk sanitation plan (WP-003-06)

Every number below was measured in this session on the tree named next to it, with the
toolchain pinned by `uv.lock` (`ruff 0.15.20`, `mypy 2.1.0`, Python 3.11). Nothing here is
inherited from a previous report; where a value is inherited it says so and names the sha.

The point of the split is that **each package is independently reviewable and reversible**,
and none of them is "reformat the repository because the gate is red".

---

## A. Baseline red on `origin/main` (`5e6f9632`)

These three failures exist **before** any of this work. They block every PR, including the
trivial one.

| id | defect | measurement | package |
| -- | ------ | ----------- | ------- |
| A1 | `smoke-pr-pipeline` dies at `Set up job` | `uses: microsoft/powershell@v1.1.0` does not exist (tag and `action.yml` both 404) | **DONE** — `fix/ci-smoke-pwsh` = `9682ee1b`, one file, 8 lines. No CI run yet: the workflow triggers only on `push: main` / `pull_request: main`, and there is no `gh` CLI or token on this host. |
| A2 | `tests-and-coverage` red on threshold, not on tests | `582 passed`, **coverage 62.34 %** against `--cov-fail-under=90` | **DECISION REQUIRED**. Three options, all reversible: (a) raise coverage to 90 % (a real work package, weeks), (b) scope the gate to changed files, (c) lower the threshold *with a recorded ADR* explaining exactly what is not covered. Any of them is honest; leaving it red is not. |
| A3 | `pip-audit` red | **80 advisories in 9 packages** on the base | Triage per package: upgrade, pin a fixed version, or record an accepted risk with a date. Not mechanical; needs one pass over `uv.lock`. |

## B. Format debt — 433 files, all in the trunk

Measured with `ruff format --check .`:

| tree | unformatted |
| ---- | ----------- |
| `1d2192b0` (trunk) | **433** |
| `baf5b560` (trunk + WP-003-03 port) | **428** |

The difference is not noise and it is not a rounding error: the port reformatted **exactly 5**
trunk files and introduced **0** newly unformatted ones.

```
src/trading_bot/autonomous/contracts.py
src/trading_bot/autonomous/decision.py
src/trading_bot/autonomous/runtime.py
src/trading_bot/autonomous/supervisor.py
src/trading_bot/paper/reconciliation_v4.py
```

**B1 — one mechanical commit, owner-authorised.** This WP is forbidden to run
`ruff format .` and does not do it. What it does provide is the safety evidence that makes
the commit defensible: for the 9 files where the port and the branch tip differ, the AST is
identical (`ast.dump` with `annotate_fields=True, include_attributes=False`), except
`src/trading_bot/ops/windowless.py`, where the only difference is **the position of one
`from collections.abc import Sequence` import** — same import set, byte-identical
non-import body. So a formatter run is provably a byte change and not a semantic one, and
the same check can be run on all 433 files before the commit is made.

Measured size of that one commit, from `ruff format --diff` on `1d2192b0` (read-only, nothing
written): **+32 621 / −15 426 lines across 433 files**. One commit, one reviewer decision,
zero logic change. (The branch's 617 files are a different, larger number: `+37 469 /
−18 032`, from WP-003-04.)

## C. Lint — 100 errors, unchanged by the port

`ruff check .` on `1d2192b0` = 100; on `baf5b560` = 100. The port adds none.

- **C1 (auto):** `ruff check --fix .` for the safe rules; re-run and diff the count.
- **C2 (manual):** whatever C1 does not fix, grouped by rule so a reviewer sees one class of
  defect at a time instead of a 100-line wall.

## D. Types — 253 errors, unchanged by the port

`mypy .` = 253 on both trees. WP-003-03's own 11 errors were fixed in `e450a238` on the
branch; the port inherits none.

- **D1:** group by file; the largest files first. This is not mechanical: each error is a
  real annotation decision.

## E. Collection errors — the trunk cannot even collect

| tree | collection errors | cause |
| ---- | ----------------- | ----- |
| `1d2192b0` | **4** | four committed tests import `trading_bot.ops`, which did not exist at that sha |
| `baf5b560` | **0** | the port carries the two stdlib-only `ops` files |
| `wp/isolation-005` | **2** | `observability.vision_panel` and `alpha15.PRE_PIT_RUNNERS`, both from sibling branches |

**E1 (done):** the `ops` gap is closed by the port — 4 → 0 with two files that have no
third-party imports.

**E2:** `observability.vision_panel` — see `INTEGRATION_BASELINE.json`
`missing_dependencies.D2`. The module **is** committed, at `e90a8ad3` (172 lines) on
`wp003i/reproducibility` and `wp003j/runtime`, reformatted at `26fd3955`. The test that
imports it is `5fd791d8`, which is on the branch but **not** in the trunk and **not** in the
port, which is why the port collects cleanly. The tolerant version of the test already exists
at `a91cabea` on `exp/ai-bots/EXP-003I-THROUGHPUT-001`. Owner: the observability lane.

**E3:** `alpha15.PRE_PIT_RUNNERS` — exists only on four sibling branches, none an ancestor of
the branch. Owner: the research/edge lane. Do not port blind.

## F. Suite — 95 red nodes, none of them this work package's

`pytest -m "not slow and not market"` on the trunk plus `ops`: 81 failed, 14 errors (95 red
nodes), 3 213 passed. On the port: the same 95 nodes, 3 230 passed. The 17 extra passes are
the port's own tests.

All 95 live under `tests/unit/research/*` and read frozen research artefacts:

| file | failures |
| ---- | -------- |
| `tests/unit/research/test_rfc035s3_strategy_closure.py` | 16 |
| `tests/unit/research/test_cost_barrier_gate.py` | 11 |
| `tests/unit/research/test_st6_scheduler.py` | 9 |
| `tests/unit/research/test_profitability_gate035.py` | 8 |
| `tests/unit/research/test_sprint024_stats.py` | 7 |

**F1:** decide per file whether the artefact on disk is stale (regenerate) or the test is
wrong (fix the test). Both are legitimate; skipping them is not.

## G. Order of work

1. **A1** (done) — one line unblocks the smoke job for everyone.
2. **B1** — format, one commit, AST-proven. Without it nothing else can be green.
3. **E1** (done) — the trunk collects.
4. **C1/C2** — lint, auto then manual.
5. **D1** — types, per file.
6. **F1** — research artefacts.
7. **A2/A3** — the two gates that are policy questions, not code questions.

Until A2 and A3 are decided, `main` cannot be green no matter what happens to the code, and
that is why the promotion in this WP stays `BLOCKED` rather than "almost done".
