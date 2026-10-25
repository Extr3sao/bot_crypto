# ARP-004 — BASELINE (§0)

## Repository state at start

* branch: `main`
* **HEAD = `d4cd26da3e77ad508e3f50b0cb5a74bdc3815c5f`** — matches the expected ARP-003
  END_SHA (`ARP-004 START_SHA = d4cd26d…`).
* `git diff --cached` — **empty** (nothing staged).
* `git diff` — only the pre-existing, unrelated working-tree modifications
  (`FINAL_REPORT.md`, `RUN_REPORT.json`, `RUN_REPORT.md`).
* Untracked pre-existing items preserved **untouched** (not part of ARP-004):
  `PAPER_DATA_24H_REPORT.{json,md}`, `docs/research/runtime_reconciliation/`,
  `docs/research/experiment_specs/EXP-CAND-001-…`, the `docs/research/work_packages/WP-*`
  set, `scripts/source_candidate_experiment.py`, `src/trading_bot/research/experimental/`
  (must stay untracked), `tests/unit/research/test_experimental_candidates_pit.py`.

## Frozen manifest verification (STOP-on-mismatch)

All checks pass — `MANIFEST_VALIDATION.json` → `all_valid: true`, `problems: []`.

| item | EXP-ARP-007 | EXP-ARP-010 |
| --- | --- | --- |
| manifest sha256 | `b338beeea154df1c8a304e913e03bfe61f7371617ecc4739cad134734e48c642` | `d8dc71a32daab27e11455ecf94181ae724e4c541c6c839c1d487b6261821eb07` |
| spec sha256 | `12683477107cc02f3a9c1c7ec1399b95754741096f08478b5ed2b9c3f60b1719` | `cfa05ec491e3d38918b2e82391ac736f5497044d3ee2a17dcb59af350e285303` |
| strategy_id match | ✅ | ✅ |
| config hash match | ✅ `6c4dd0be1fc2fff24920c9f9226c7f81f8d3d4dc80671b5a424721da497f7db1` | ✅ |
| dataset fingerprint match | ✅ `9d51385d570b8ff4ba1af22c3d4491f78c36111ec7383173e7d0351d5ee21658` | ✅ |
| cost model match | ✅ `23.559016994374947` bps | ✅ |
| splits match (DEV/VALIDATION/OOS) | ✅ | ✅ |
| OOS locked (`oos_opened: false`) | ✅ | ✅ |

The frozen manifests were **not** regenerated. No mismatch was found, so execution
proceeded.

## Environment

* `code_hash` = `39fd35e638bdde6e1fbcfb59e8e1f582d0792a4ecc28d97181619e3f61c2afa7`
  (over the tracked ARP-004 code files listed in `ENVIRONMENT.json`; LF-normalised).
* runner: CPython 3.11.15 (`/.venv`), deterministic, no network, no wall-clock.
* `FALSE_SUCCESS = 0`. No LIVE, no capital, no credentials, no threshold loosening,
  no risk-sizing or lifecycle change.
