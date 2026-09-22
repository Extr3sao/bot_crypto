# MA2_QUALITY_BASELINE_PORT_01 — Report

Work package: port the clean CI baseline established by `main` quality commit
`5e6f963` to the active MA-2 lineage **without touching the dirty PC1 checkout**
containing current H6 work.

## Identification

| Field | Value |
|---|---|
| MA2_BASE_COMMIT | `894d2aa` (committed tip of `feat/ma-2-specialist-opportunity-swarm` at WP start) |
| MAIN_QUALITY_COMMIT | `5e6f963` (`fix/pc1-lint-mypy-baseline` on `main`) |
| QUALITY_PORT_COMMIT | `1269ba8` (merge of `5e6f963` into MA-2 + quality debt fixes; created in the isolated clean clone `%TEMP%\pc2_validation\bot_crypto` on branch `align/ma-2-on-main`, then pushed to origin as `align/ma-2-on-main` and fast-forward of `feat/ma-2-specialist-opportunity-swarm`) |
| WORKTREE | `.worktrees/ma2-quality-baseline-01` (created from `1269ba8`; PC1 dirty checkout never used as implementation workspace) |
| BRANCH | `repair/ma2-quality-baseline-01` |

Provenance note: the quality port itself was materialized in a prior step as an
explicit merge commit (`1269ba8`) — MA-2 is a strict descendant of `894d2aa`
(pre-port) and of `5e6f963` (main quality source). This WP validates, audits and
documents that state; the only changes made on top are the two files of this
report and one restored formatting fix in
`docs/paper-observation-01/evidence/concurrent_wip_validator.py` (a doc-tree
format fix that had been lost by re-materializing `docs/` from HEAD during CRLF
remediation; no test or script references that file).

## Quality gates (baseline measured in detached worktree at `894d2aa`)

| Gate | BEFORE (894d2aa) | AFTER (this branch) |
|---|---|---|
| `ruff check .` | ❌ 387 errors (242 fixable) | ✅ All checks passed |
| `ruff format --check .` | ❌ 209 files would be reformatted (227 OK) | ✅ 436 files already formatted |
| `mypy .` | ❌ 8 resolution errors in 7 files (blocked further checking; underlying debt 428 errors once unblocked) | ✅ Success: no issues found in 429 source files |
| `pytest -m "not slow and not market"` | 1292 passed / 1 failed / 6 skipped | ✅ **1292 passed / 1 failed / 6 skipped** (identical) |

The single remaining failure at both BEFORE and AFTER is
`tests/unit/research/test_oi_full_history_v2_pit.py::test_2024_06_05_contamination_never_reaches_canonical`
— it requires the external OI dataset (`data/processed/oi_full_history_v2/...`)
which is intentionally not stored in Git and is reconstructed via
`scripts/download_oi_full_history.py` (official binance.vision archives +
`.CHECKSUM` sha256 sidecars). This is the documented DATA_PORTABILITY external
requirement, not a port defect.

`POST_TEST_COUNT (1292) >= PRE_TEST_COUNT (1292)` — no collection-policy change
was made; MA-2's full test population is preserved.

## Config changes carried/justified (each validated against MA-2, not blind-copied)

1. `pyproject.toml` — `mypy_path = "src"`, `explicit_package_bases`, orphan
   exclusion regex (aligns mypy discovery with the already-documented pytest
   collection policy in `tests/integration/conftest.py`).
2. `pyproject.toml` — `tests.*` mypy override extended with
   `no-untyped-call`, `dict-item`, `list-item`, `no-redef` (fixture/mock
   patterns; extends the repo's own documented "Strategy B" per-module
   relaxation philosophy).
3. `pyproject.toml` — `scripts.*` override `ignore_missing_imports`
   (operational tooling directory: 296 latent resolution errors; zero runtime
   impact — scripts are executed, never imported by the package).
4. `pyproject.toml` — `trading_agent.*` override `ignore_missing_imports`
   (audit §6 below).
5. `pyproject.toml` — pytest `pythonpath = ["."]` (tests/unit/research import
   `scripts.*` relative to repo root; previously only worked under
   `python -m pytest`).
6. `.gitattributes` (new) — `* text=auto eol=lf`. Root-cause fix: Windows
   checkouts under `core.autocrlf=true` materialized LF blobs as CRLF, and
   byte-frozen hash anchors (POC02 launch gate, H5/H3/H6 frozen-file anchors)
   failed on any Windows PC even though the committed blobs were identical.
   10 POC02 gate tests + 1 H5 anchor test now pass on Windows. Detection of
   real content manipulation is not weakened: blobs are LF-canonical and the
   gates remain byte-exact against the canonical checkout.

## TRADING_AGENT_OVERRIDE_AUDIT — PASS (variant A)

- `src/trading_agent/` does not exist in MA-2; no `models_v02*` file exists
  anywhere in the tree.
- Occurrences (5): `src/trading_bot/research/confirmation.py`,
  `execution_assumptions.py`, `quant_auditor_v021.py`, `strategy_engineer.py`,
  `tests/integration/test_v021_real_pipeline.py`.
- Every occurrence is the same pattern: `try: import trading_agent... except
  ImportError:` followed by a complete in-file fallback implementation. The
  fallback is the only runtime path that has ever executed; the override
  documents reality instead of hiding an import. **The module remains genuinely
  absent; the override is ported with evidence.**

## ORPHAN_TEST_POLICY_VALIDATED — PASS

- Orphan files present in MA-2: 6 (`test_v031_dst_journal_reconstruction.py`,
  `test_v031_full_replay_trades.py`, `test_v031_paper_replay_certification.py`,
  `test_v032_real_market_parity.py`, `test_v033_real_replay_certification.py`,
  `test_v033_trade_lifecycle.py`).
- pytest excludes them via `tests/integration/conftest.py`
  `collect_ignore_glob` (lines 11–15) — pre-existing, documented policy.
- Their targets (`trading_bot.demo.pipeline_v03x`,
  `trading_bot.research.autopilot_v03x`) were never committed on any branch;
  no MA-2 implementation makes them valid.
- `mypy tests/integration` is clean with the exclusion carried — verified
  independently on MA-2, not copied from main.

## STRENUM_SEMANTIC_COMPATIBILITY — PASS

- 26 enum classes converted `(str, Enum) -> StrEnum` (main lineage); 33 source
  files now use `StrEnum`.
- Exhaustive grep evidence: **0** consumers call `str(ENUM_VALUE)` and **0**
  string literals of the form `"ClassName.MEMBER"` exist in `src` or `tests`
  — nobody depends on the old representation.
- Semantic deltas and their disposition:
  - `str(X.VALUE)`: `"X.VALUE"` → `"value"` — no consumers found.
  - Hashing: `StrEnum` hashes by value; the `(str, Enum)` mixin hashed by
    identity. This is a strict improvement (enum instances now work as dict
    keys against raw strings); full suite green.
  - Plain `Enum` classes intentionally left as-is where no string contract
    exists (e.g. `execution/feed_guard.py::FeedGuardAction`,
    `execution/intent.py::AckQueryResult`, `RecoveryDecision`).
- New targeted tests: not required (zero consumers found by exhaustive grep);
  the existing 1292-test suite covers the converted enums' runtime behavior,
  including the multi-agent contracts and paper certification tests.

## IMPORT AUTHORITY — PASS

`trading_bot.__file__` resolves to
`.worktrees/ma2-quality-baseline-01/src/trading_bot/__init__.py` inside the
isolated worktree. No first-party module is supplied by the main checkout or
the dirty MA-2 checkout. The package imports zero `scripts.*` modules.

## ECONOMIC_SEMANTIC_DIFF = 0

Method: `git diff 894d2aa..HEAD` restricted to economic files
(`src/trading_bot/research/h6/**`, `h1_regime_transition.py`,
`h3_relative_value.py`, `h5_orderflow.py`) filtered to +/- lines containing
numeric literals: only formatter whitespace (e.g. `net[2 * (len(net) // 3) :]`)
and removed `# type: ignore` comments matched. Zero numeric literals changed.
`docs/external-audit-01/` specs: untouched (0 files). Runtime proofs: full
suite identical to baseline, targeted 421-test regression green.

## Targeted regression (§15)

`421 passed / 1 skipped` across `multi_agent`, `paper`, `risk`, `shadow`,
`portfolio`, `demo` and research governance
(`test_execution_ledger`, `test_data_admission` [1 env-external skip],
`test_regime_eligibility`, `test_regime_v2`). No economic experiments were run.

## WIP integrity — PC1_H6_WIP_CHANGED_BY_THIS_WP = false

Independent verification before/after the entire WP: `git status --porcelain
-uall` (82 files) and per-file sha256 of every WIP file in the PC1 dirty
checkout (`conf_lock.py`, `whitelist.py`, `confirmation_state.py`,
`hash_validator.py`, 7 new H6 test files, `docs/audit/*`, H6 external
verification evidence, `context/retrieval-log.md`). **0 differences.**

## FALSE_SUCCESS = 0

Every gate was re-measured in the worktree itself; the pytest and mypy results
are from full runs inside the isolated environment; the WIP integrity check is
an independent content-hash diff, not a status shortcut.

## Defects / limitations

- The external OI dataset dependency (1 test) is unchanged by design; it is the
  documented DATA_PORTABILITY requirement, not a defect of this WP.
- The 1-skip in targeted regression is environmental (ingestion not run in this
  environment).
- StrEnum identity→value hashing is a behavior improvement with no consumer
  impact found; flagged here for traceability.

## RESULT

**MA2_QUALITY_BASELINE_READY_FOR_INTEGRATION**

NEXT: checkpoint/finish current H6 WIP → integrate
`repair/ma2-quality-baseline-01` (= `1269ba8` + report) → clean-clone PC2
portability validation on the integrated line.
