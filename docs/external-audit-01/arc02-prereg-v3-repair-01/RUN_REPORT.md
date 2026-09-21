# RUN_REPORT — ARC02 Prereg V3 Minimal Repair (import authority only)

## Summary

Repaired ONLY the independently demonstrated import-authority failure of ARC-02
preregistration V2. No economics, no retune, no strategy changes, no Track B
expansion. Builder-side work returned as `PENDING_INDEPENDENT_PREREG_VERIFICATION_V3`.

## Authority chain

- Base (V2 repair commit): `6df96c66ac4ea2fe5413cf896befc1ce997cd6e5`
- V2 verifier evidence commit (READ-ONLY evidence):
  `00063237de21e3ed9273d84293f129f75003f126`
- V2 effective verdict (evidence overrides self-reported PASS):
  `FAIL_INDEPENDENT_PREREG_VERIFICATION_V2`
  (`V2_CONTAMINATION_DEFENCE = FAIL`, `PYTHON_IMPORT_AUTHORITY = FAIL`)
- SOURCE_FILES_MODIFIED_BY_VERIFIER = 0, TEST_FILES_MODIFIED_BY_VERIFIER = 0,
  TARGET_ECONOMIC_DRIFT = 0

## Defect reproduction (pre-repair, at base commit)

`ARC02_V3_IMPORT_DEFECT_REPRODUCTION.json` — DEFECT_REPRODUCED = true:

- F1/F1b: plain python under ambient contamination (editable `.pth` +
  `PYTHONPATH` = main `src`) imports `trading_bot` from the MAIN checkout, from
  any cwd.
- F2: the V2 bootstrap SILENTLY REPLACES an already-imported wrong first-party
  module and returns PASS (`silently_replaced_wrong_preload = true`).
- F3: V2 path-identity comparison defect — evidence emitted with forward
  slashes recomputes as "outside target" under naive `startswith(Path.resolve())`
  (`v2_style_startswith = false`, `v3_style_pathlib_is_relative_to = true` for
  the same target-resident file), exactly matching the committed verifier
  contradiction `authority_package_within_target = false`.

## Root cause (mechanism-level)

`ARC02_V3_IMPORT_ROOT_CAUSE.md` — ROOT_CAUSE_IDENTIFIED = true. Five
compounding mechanisms (RC-1..RC-5): non-canonical path identity; silent
replace of wrong preloaded modules; `sys.path` authority by ordering instead
of by absence; pytest guard at the wrong lifecycle point with a tautological
test; subprocess contamination re-inheritance with no authority channel.

## Repair (V3)

- `src/trading_bot/research/import_authority.py`: canonical path identity
  (`Path.resolve()` + separator-aware containment only), fail-closed
  `PRELOADED_WRONG_FIRST_PARTY_MODULE` audit, purge of all resolvable
  first-party contaminants from `sys.path` (nonexistent entries kept for
  auditor visibility), explicit `verify_commit_identity()`, explicit
  subprocess authority env (`ARC02_TARGET_ROOT`, `ARC02_EXPECTED_COMMIT`),
  `verify_loaded_state()` for session-drift re-checks.
- `scripts/arc02_import_bootstrap.py`: V3 bootstrap — must run before any
  first-party import; derives target from script location (never cwd); fail
  closed on missing contract, wrong preload, commit mismatch, wrong resolution.
- `conftest.py`: establishes authority at session start (preload audit + purge
  + commit identity), re-verifies loaded first-party modules during collection
  (`pytest_collection`, `pytest_collection_modifyitems`); on violation raises
  `PYTEST_AUTHORITY_FAIL_CLOSED` before any evidence-producing test.
- `scripts/verify_arc02_data_authority.py`: portable data verifier now
  establishes V3 import authority via the bootstrap before importing
  first-party modules.
- `tests/unit/research/test_arc02_import_authority_v3.py`: 19 adversarial
  tests, cases A–K of work order §19 (all pass under real ambient
  contamination; no skips).

## Frozen economic identity (programmatic V1 → V2 → V3 comparison)

- `SPEC_SHA256_V3_EFFECTIVE` =
  `ef5d76196943b7498f2ed70757e0405acc2a07a4c80a66b71eaba548950afc40` (required: identical)
- `MANIFEST_SHA256_V3_EFFECTIVE` =
  `9a7499813bde088ebde517e77bf9089148d0c4c875d1d719fd4f8c0754827e88` (required: identical)
- `DATASET_SHA256` =
  `03f227d0ae18efdc8e3d84831283c4e3f7a333bf0fea8b944f55a9144cc164d5` (recomputed from the
  certified explicit data root `.research/arc02-candidate-design-01`; frozen manifest
  binding reproduced)
- Frozen economic constant digest identical across V1/V2/V3.
- `ECONOMIC_DIFF_COUNT = 0`

## Builder gates (§21 — builder crosscheck, NOT independent verification)

All PASS: PYTHON_IMPORT_AUTHORITY, TEST_TARGET_AUDITED_TARGET,
EDITABLE_PTH_ATTACK, PRELOADED_WRONG_MODULE_ATTACK, PYTEST_AUTHORITY,
PYTEST_WRONG_IMPORT_FAIL_CLOSED, SUBPROCESS_IMPORT_AUTHORITY, ARBITRARY_CWD,
WRONG_CHECKOUT_FAIL_CLOSED, WRONG_COMMIT_FAIL_CLOSED, PORTABILITY,
DATA_BINDING, WRONG_DATA_ROOT_FAIL_CLOSED, EMPTY_DATA_ROOT_FAIL_CLOSED,
PIT_TARGET_AUTHORITY, TRACK_B_REGRESSION (20 passed), ECONOMIC_DIFF_COUNT = 0.

## Research governance

- ARC02_BACKTESTS = 0, ARC02_EXECUTIONS = 0, ARC02_PERFORMANCE_OBSERVED = false
- FALSE_SUCCESS = 0
- No hypothesis outcome exists; ARC-02 is NOT killed; discovery NOT run.
- Certified data root used for evidence only (read-only verification); no
  runtime economics were executed.

## Status

FINAL_STATUS: PENDING_INDEPENDENT_PREREG_VERIFICATION_V3
NEXT: ARC02_INDEPENDENT_PREREG_VERIFICATION_V3

## Binding to V3_PREREG_COMMIT

- `V3_PREREG_COMMIT` = `66e1892ad848ebe0ba06386a603a2aa74a99ec7b`
- Every V3 builder evidence artifact in this directory is bound to that commit
  (`git_head` / `target_commit` / `expected_commit` = `66e1892…`), so the
  evidence is re-derivable from the committed state rather than only from the
  pre-commit working tree.
- `CLEAN_WORKTREE_BUILDER_CROSSCHECK` = `PASS` — validated in a brand-new
  **detached** worktree created at `V3_PREREG_COMMIT` with the contaminated
  environment intentionally present (editable `.pth` + `PYTHONPATH` = main
  `src`); `PLAIN_PYTHON_AUTHORITY`, `PYTEST_AUTHORITY_FRESH`,
  `SUBPROCESS_AUTHORITY_FRESH`, `DATA_BINDING_FRESH` all PASS. The temporary
  worktree was removed after the run
  (`ARC02_V3_POST_COMMIT_VALIDATION.json`).
- `POST_FREEZE_ARTIFACT_DRIFT` = `0` (SPEC/MANIFEST hashes recomputed on the
  fresh detached tree).
- Working tree left clean: `git status --porcelain` empty.

## Defects and limitations (builder-side)

- DEFECTS: none open. The V2 defects (RC-1…RC-5) are each reproduced pre-repair
  and covered by an asserting test in
  `tests/unit/research/test_arc02_import_authority_v3.py`.
- LIMITATIONS:
  - Builder crosscheck is **not** independent verification; V3 still requires
    `ARC02_INDEPENDENT_PREREG_VERIFICATION_V3`.
  - Authority is proven only for the process/entrypoint set exercised here
    (plain python, pytest, subprocess, PIT verifier, data verifier, portable
    verifier, clean-worktree validation). A future entrypoint that imports
    `trading_bot` without invoking the bootstrap is outside this guarantee.
  - Subprocess authority requires the child to call `bootstrap_arc02()` before
    importing first-party code or to receive
    `ARC02_TARGET_ROOT`/`ARC02_EXPECTED_COMMIT`; the contract is enforced in
    the shipped scripts and tests, not by the interpreter itself.
  - The certified data root is a sibling research worktree
    (`.research/arc02-candidate-design-01`); the data verifier is executed with
    `--skip-git` against the audited target, so dataset identity is bound by
    hash rather than by data-root git HEAD.
  - The main checkout's own untracked files (e.g. `his.zip`, `docs/audit/*`,
    `.agentic-backup/`) are pre-existing and untouched by this work package.
  - No ARC-02 economics were run: `ARC02_BACKTESTS = 0`,
    `ARC02_EXECUTIONS = 0`, `ARC02_PERFORMANCE_OBSERVED = false`.
