# PC2 PORTABILITY REPORT — Trading Agentic Portable

**Date:** 2026-09-22
**Repository:** https://github.com/Extr3sao/bot_crypto.git
**Validation context:** clean clone into a fresh, isolated directory (`%TEMP%\pc2_validation\bot_crypto`) with a freshly created `uv` venv. No PC1 source tree, `.venv`, `.worktrees`, `.research`, datasets, caches or configuration were used or copied. A final confirmation on distinct PC2 hardware is listed under NEXT (network/credentials/PATH being the remaining host-level variables).

## Summary

| Key | Result |
| --- | --- |
| CLONE | PASS |
| REMOTE | `https://github.com/Extr3sao/bot_crypto.git` |
| CLONE_HEAD | `767462c` (`main`) |
| PYTHON | 3.11.15 (uv-managed venv; `requires-python >= 3.11`) |
| UV | 0.11.26 |
| ENVIRONMENT | PASS (`uv sync --frozen`, lock respected, 105+ packages) |
| IMPORT_AUTHORITY | PASS — `trading_bot.__file__` → clone path; zero PC1 path references |
| TESTS | main: **582 passed / 0 failed** (`pytest -m "not slow and not market"`, 309.8s); ARC branch: 283 passed / 3 failed / 10 skipped (data-dependent, see DATA_PORTABILITY); ma-2 runtime subset: 207 passed |
| LINT | DEBT (environment executes `ruff` correctly; repo state has 190 `ruff check` findings and 79 files needing `ruff format` — concentrated in `tests/integration` v02x/v03x certification suites) |
| TYPECHECK | BLOCKED-PARTIAL (`mypy .` reports 8 module-resolution errors in 7 files — duplicate modules without `__init__.py`; pre-existing repo debt) |
| BRANCH_RECOVERY | PASS — `git switch --track` verified for `main`, `feat/ma-2-specialist-opportunity-swarm`, `repair/arc02-prereg-v3-repair-01`; all required active branches exist in origin |
| DATA_PORTABILITY | PASS_WITH_EXTERNAL_DATA_REQUIREMENT |
| GITHUB_READ | PASS (`git fetch --all --prune` + 57 remote branches) |
| GITHUB_WRITE | PASS — this branch `test/pc2-portability-validation` pushed from the clean clone and verified via `git ls-remote` |
| SECRET_SCAN | PASS — no secrets in working tree; pattern scan over **all commits in history** clean; only `.env.example` with placeholders; no `.env` ever added |
| PC1_PATH_DEPENDENCIES | NONE detected |
| BLOCKERS | None blocking portability. Non-blocking: (1) lint/typecheck debt on `main`; (2) research-governance tests require the external OI dataset |
| FINAL_STATUS | **PORTABILITY_PASS_WITH_EXTERNAL_DATA_REQUIREMENT** |

## Environment reconstruction

Authority: `pyproject.toml` + `uv.lock` (repository-defined). `uv sync --frozen` succeeded (exit 0) on Python 3.11.15, creating `.venv` from the lock without resolution drift. No manual `pip install` was needed.

## Import authority

`import trading_bot` resolves to `...\pc2_validation\bot_crypto\src\trading_bot\__init__.py` — inside the clean clone. No reference to `C:\Users\GVLLFR0035\Downloads\bot freebuff` or any PC1 path.

## Data portability

- `data/` ships empty by design (`.gitkeep` only); OHLCV/OI datasets are intentionally NOT in GitHub.
- Reconstruction authority IS present: `scripts/download_oi_full_history.py` (source: `data.binance.vision` official USD-M daily metrics archive + official `.CHECKSUM` sha256 sidecars), `scripts/normalize_oi_full_history.py` (v1/v2), and manifests (`docs/external-audit-01/oi-full-history-01/DOWNLOAD_SUMMARY.json`: 5,691 files, BTCUSDT/ETHUSDT/SOLUSDT, retrieval 2026-09-11).
- Consequence: 3 research-governance tests fail until the OI dataset is re-downloaded on PC2 (`test_oi_full_history.py::test_h5_frozen_anchors_unchanged`, `test_oi_full_history_v2_pit.py::test_2024_06_05_contamination_never_reaches_canonical` + 1 more). They assert frozen anchor hashes over real downloaded data — expected failure without the external dataset, NOT a portability defect.

## Active work recovery

On `feat/ma-2-specialist-opportunity-swarm` (authoritative development branch): checkout + tracking OK, `uv sync --frozen` re-verified the lock, 207 runtime tests passed (market_data + paper), harmless file modification → `git checkout --` restore → branch switch main↔ma-2 all clean. No test modifications committed.

## GitHub round-trip

This report was committed on `test/pc2-portability-validation` **from the clean clone** and pushed to origin; read+write capability proven. Per protocol, the branch is NOT merged automatically.

## NEXT

1. On real PC2 hardware: repeat `git clone` → `uv sync --frozen` → `pytest -m "not slow and not market"` (remaining variables: OS PATH, GitHub credentials, network).
2. Re-download the OI full-history archive on PC2 via `scripts/download_oi_full_history.py` before running research-governance data tests. Do not copy datasets from PC1.
3. On PC1 (pre-merge debt): fix the 190 `ruff` findings and the 8 `mypy` module-resolution errors in `main`, so future PC2 clones pass all CI gates out of the box.
4. Publish/refresh any active branches worked on after 2026-09-22 before switching machines.
