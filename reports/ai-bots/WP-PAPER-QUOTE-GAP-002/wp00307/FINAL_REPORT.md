# WP-003-07 — Final report (trunk sanitation, phase 1)

## Status

| field | value |
| --- | --- |
| `WP_STATUS` | **PASS** — mechanical, proven, published on an isolated branch |
| `TRUNK_STATUS` | **PARTIAL** — format 433 → 24 (all pinned), lint 100 and mypy 253 unchanged, collection already 0 |
| `CI_STATUS` | **NOT_PERFORMED** |
| `RUNTIME_STATUS` | **PASS** — suite identical to base at node level |
| `FALSE_SUCCESS` | **0** |

A completed work package is not a sanitised trunk. The trunk is measurably better and provably
unchanged in behaviour; it is not green, and two of its red gates are policy questions rather
than code questions.

---

## 1. Commits and branches, real

| ref | sha | note |
| --- | --- | --- |
| base | `1d2192b0` | `main` = `recovery/trunk-sync` = `origin/recovery/trunk-sync` |
| `recovery/trunk-format-001` | `026ea574` (format) + evidence commit | created from `1d2192b0`, published |
| `main` | `1d2192b0` | untouched |
| `origin/main` | `5e6f9632` | untouched |

Two commits: one mechanical (`026ea574`, 409 files, `+29 793 / −13 943`), one evidence commit
carrying this bundle and the two tools. No merge, no rebase, no force-push, no amend of any
shared branch. The evidence commit cannot name its own sha — resolve it with
`git log -1 --format=%H -- reports/ai-bots/WP-PAPER-QUOTE-GAP-002/wp00307` — and it verifies
the *format* commit, which is the only thing it can honestly speak about.

## 2. What is integrated and what is not

**Integrated (on the branch only):** `ruff format` applied to 409 Python files, with AST,
comment-token and literal-value equality proven from git objects, plus the verifier and the pin
scanner.

**Not integrated:** the 24 files whose bytes a committed record certifies. They are listed
with their pinning artefact in [`EXEMPTIONS.json`](EXEMPTIONS.json) and explained in
[`FORMAT_CHANGE_REPORT.md`](FORMAT_CHANGE_REPORT.md) §5. Also untouched: the 95 red research
nodes, the coverage threshold, `pip-audit`, `main` itself.

## 3. Tests and CI actually executed

| run | result |
| --- | --- |
| `pytest -m "not slow and not market"` @ `1d2192b0` | 81 failed, 3213 passed, 31 skipped, 14 errors, 558 s |
| same @ `026ea574` | **81 failed, 3213 passed, 31 skipped, 14 errors, 552 s** |
| node-id comparison | **0 new red nodes, 0 fixed, 95 identical** |
| the six pin tests that the first attempt broke | 6 passed after the exemptions |
| `verify_trunk_format.py` | PASS with one declared residual, 8 checks, 6/6 negative controls |
| GitHub Actions | **NOT_PERFORMED** — workflow triggers on `main` only, no CLI or token |

## 4. State of the controls

The eight verifier checks, measured from git objects:

| check | result |
| --- | --- |
| only Python changed | 409/409 |
| no file added, deleted or renamed | pass |
| AST identical (strict) | 408/409 |
| AST identical modulo docstring whitespace | 409/409, 1 residual, whitespace-only |
| comment tokens identical | 7 305 tokens |
| control comments preserved | 151 files, 327 `noqa` / 72 `pragma` / 39 `type: ignore` |
| literals representation-only | 152 representation, 0 content changes |
| changed-file count vs inventory | 409 = 409 |

Plus the invariant that justifies the exemptions: `ruff format --check .` flags **24 files and
they are exactly the 24 declared exemptions** (`EXEMPTIONS.json → identical: true`).

## 5. Remaining blockers

1. **24 pinned files cannot be formatted** while `PRODUCER_PINS.json`,
   `COST_BARRIER_CERTIFICATION.evidence_digests`, the active-economic-audit entrypoints and the
   `st6` / `rfc048` bundles certify their bytes. This is the real reason the format gate cannot
   reach zero, and it is structural, not cosmetic.
2. **Coverage** 62.34 % against `--cov-fail-under=90` needs an owner decision (raise, scope to
   changed files, or lower with an ADR).
3. **`pip-audit`**: 80 advisories on the base, needing per-package triage.
4. **95 red research nodes**, pre-existing, all under `tests/unit/research/*`, untouched here.
5. **No CI run** for this branch, by construction of the workflow.
6. One inherited claim in `wp00305` is **refuted**: the trunk has 0 collection errors, not 4,
   and no test references `trading_bot.ops` at this sha.

## 6. Paper

Unchanged. No runtime module, configuration, risk rule, sizing rule, execution path, accounting
rule or dataset was modified: 408 of 409 files are byte-identical after `ast.dump`, and the
ninth differs by one trailing space inside a docstring. The suite result is identical at node
level, which is the strongest statement available without a market session.

## 7. Minimum next step

Decide the pin question, because it gates the format job either way:

- **re-certify** — regenerate `PRODUCER_PINS.json`, the cost-barrier certification and
  `ACTIVE_ECONOMIC_AUDIT.json` from the formatted tree, then format the last 24 files in one
  follow-up commit; or
- **declare the pins permanent** — add the 24 paths to a documented exclude list next to the
  formatter configuration so `ruff format --check .` can be a required green check.

Both are small and reversible. What is not acceptable is formatting the 24 and letting six
certification tests stay red, which is precisely what the first attempt measured.
