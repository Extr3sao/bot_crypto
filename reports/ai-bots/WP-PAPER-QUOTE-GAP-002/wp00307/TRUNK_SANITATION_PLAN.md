# Trunk sanitation plan — phase 1 (WP-003-07)

Supersedes `wp00306/TRUNK_SANITATION_PLAN.md`. Everything below was measured on
`1d2192b0` and on `026ea574` in this session with the pinned toolchain
(`ruff 0.15.20`, `mypy 2.1.0`, Python 3.11.15).

The grouping is by **cause**, because the defects in this trunk share causes and a package that
fixes a cause is reviewable while a package that fixes a symptom is not.

---

## Cause 1 — representation debt (closed, except where evidence pins bytes)

| id | state | evidence |
| --- | --- | --- |
| F1 format | **DONE 433 → 24** | one mechanical commit, AST-proven, `+29 793 / −13 943` |
| F2 pinned files | **OPEN — needs a decision** | 24 files; see below |

**F2 is the interesting one.** The trunk certifies the bytes of 24 of its own Python files
through committed records:

- `data/recovery/wp7/evidence/PRODUCER_PINS.json` (4 producers, three digest forms each),
- `data/recovery/wp7/COST_BARRIER_CERTIFICATION.json → evidence_digests` (5 scripts + inputs),
- `data/recovery/ACTIVE_ECONOMIC_AUDIT.json → payload_sha256` over 5 **certified entrypoints**,
- `data/st6/**` snapshots and `data/recovery/RUN_REPORT.json` pinning their own producers,
- `src/trading_bot/research/forward/collector.py` pinned by commit `f406a45`.

Reformatting one of them makes the record disagree with the tree, and the tests that guard it
fail with `“the artefact must be regenerated and re-verified”`. That is the mechanism working
as designed. Two honest ways out:

- **F2a (re-certify):** regenerate the four records from the formatted tree in one commit, so
  the bytes and the certification agree again. Cost: one producer run per record, plus review
  of the diffs, which should touch only digests. Then format the last 24.
- **F2b (permanent exemption):** add the 24 paths to a documented exclude list beside
  `[tool.ruff]` so `format --check` can be a green required check without pretending.

Recommendation: **F2a** for the three recovery records (they are recent and re-runnable) and
**F2b** for the `st6` bundle and the forward capture, whose authoring context no longer exists.
The scan that produces the list is `scripts/find_python_pins.py`; it is reproducible.

## Cause 2 — lint debt (100 errors, unchanged)

`ruff check .` = 100 on both sides. Grouped by rule: `UP017` ×40 (one mechanical change:
`datetime.timezone.utc` → `datetime.UTC`), `RUF100` and `F401` ×6 each, `BLE001` ×6, `F841` ×5,
then a long tail of ≤4. 64 are auto-fixable.

| id | package | risk |
| --- | --- | --- |
| L1 | `ruff check --fix` for the safe rules, then re-measure | low, but it rewrites 60+ files: do it in its own commit, never mixed with F1 |
| L2 | the `BLE001` (blind except) ×6 by hand | low, each is a real decision about what is being swallowed |
| L3 | the rest, one rule per commit | low |

Do **not** run `--unsafe-fixes` on this trunk: several `F841` sites are deliberate.

## Cause 3 — type debt (253 errors, 29 files)

`mypy .` = 253 on both sides. Same files, same errors; only one message's internal line
reference moved because the statement moved. This is not mechanical: 29 files, each a real
annotation decision.

| id | package |
| --- | --- |
| T1 | the three worst files first (largest error count), one commit each |
| T2 | the `unused-ignore` cluster (`cap004d_health_check.py` and neighbours): either the ignore is needed or it is not — decide per site |

## Cause 4 — environment and collection (nothing left at the trunk)

| id | state | evidence |
| --- | --- | --- |
| E1 | **CORRECTED** | WP-003-05 recorded 4 collection errors at `1d2192b0` from `trading_bot.ops`. Not reproducible: no reference to `trading_bot.ops` exists in `src/` or `tests/` at that sha, collection exits 0 with 3339 tests, and the four named modules pass 73 tests. The import exists only on the branch. |
| E2 | still branch-side | `observability.vision_panel` and `alpha15.PRE_PIT_RUNNERS` from sibling branches; irrelevant to a published trunk |

## Cause 5 — pre-existing test debt (95 red nodes)

81 failures + 14 errors, identical before and after this work package, all under
`tests/unit/research/*` and `tests/unit/forward/*`, all reading frozen research artefacts.

| id | package |
| --- | --- |
| R1 | for each file, decide whether the artefact on disk is stale (regenerate) or the test is wrong (fix the test) |
| R2 | two families are caused by *missing generated inputs* (`reports/strategy-baseline/COST_BARRIER.json`), not by code: materialise them or mark the tests `slow` |

## Cause 6 — gates that are policy, not code

| id | state |
| --- | --- |
| P1 coverage | 62.34 % against 90 %. Three options: raise, scope to changed files, or lower with an ADR |
| P2 `pip-audit` | 80 advisories on the base, 9 packages. Triage per package |
| P3 smoke job | fixed on `fix/ci-smoke-pwsh` (`9682ee1b`), never run because the workflow only fires on `main` |

## Order of work

1. **F2a / F2b** — decide the pin question. It is the only thing between the trunk and a green
   format check, and it is a one-hour job either way.
2. **L1** — the 64 auto-fixable lint errors, one commit.
3. **E2 / R2** — the blockers that stop a *published* trunk from collecting and running.
4. **T1 / T2** — types, per file.
5. **R1** — the research artefacts.
6. **P1 / P2** — the two decisions that make `main` green or explicitly accepted as red.

Until P1 and P2 are decided, `main` cannot be green regardless of the code, which is why the
promotion stays blocked in this work package rather than "almost done".
