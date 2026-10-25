# ARP-005 — BASELINE / LINEAGE (§0)

**Verdict: baseline VERIFIED by independent re-execution. No drift from ARP-004.**

## Lineage

| item | expected | observed | status |
| --- | --- | --- | --- |
| branch | `main` | `main` | OK |
| HEAD (ARP-004 final) | `eae4c27e8254303c30ddf42abebb4ddaecf10716` | `eae4c27e8254303c30ddf42abebb4ddaecf10716` | OK |
| commit `c4f82a0` (ARP-004 code+evidence) | present | present | OK |
| commit `eae4c27` (ARP-004 END_SHA stamp) | present | present (HEAD) | OK |
| staged changes (`git diff --cached`) | none | none | OK |
| working tree | pre-existing unrelated dirt only | identical to ARP-004 end | OK |

**START_SHA = `eae4c27e8254303c30ddf42abebb4ddaecf10716`.**

The dirty set is byte-for-byte the pre-existing, unrelated ARP-004-end set
(`FINAL_REPORT.md`, `RUN_REPORT.*`, `PAPER_DATA_24H_REPORT.*`,
`docs/research/work_packages/*`, `docs/research/runtime_reconciliation/`,
`docs/research/experiment_specs/EXP-CAND-001-*`, `scripts/source_candidate_experiment.py`,
`src/trading_bot/research/experimental/`, `tests/unit/research/test_experimental_candidates_pit.py`).
**None of these were touched, staged or committed.** `src/trading_bot/research/experimental/`
remains **untracked** by hard constraint.

## Independent re-verification (do NOT trust FINAL_REPORT)

Every ARP-004 claim was re-derived from source, not read from `FINAL_REPORT.md`:

| check | method | result |
| --- | --- | --- |
| EXP-ARP-007 = `REJECT_COSTS` | re-ran the deterministic ARP-004 driver and diffed the run dir | byte-identical `DECISION.json` / `DEV.json` / `COST_STRESS.json`; DEV 153 trades, gross **+0.776 bps**, net **−22.783 bps** |
| EXP-ARP-010 = `INSUFFICIENT_EVIDENCE` | same re-run | byte-identical; DEV **6** trades, gross **−75.059 bps** |
| W7 / OOS unopened | `DECISION.json` `oos_opened=false`; no `OOS.json`; driver short-circuits before OOS | **unopened** |
| pytest | full suite | **1503 passed / 0 failed / 0 skipped** (111 s) |
| ruff | `ruff check .` | **clean** |
| mypy | `mypy . --exclude "reports"` | **Success: no issues found in 413 source files** |

The two ARP-004 run outputs differ from the committed run copies in exactly two
non-substantive ways: `ENVIRONMENT.json.branch_head` (HEAD moved `d4cd26d → eae4c27`)
and a richer hand-finalised `RUN_REPORT.json`. Every experiment artifact is identical,
which is the determinism proof.

## Frozen inputs (unchanged)

- `config/strategy_admission.json` = `6c4dd0be1fc2fff24920c9f9226c7f81f8d3d4dc80671b5a424721da497f7db1` (all 6 runtime families `admitted_for_paper=false`).
- Canonical cost = `COST_MODEL_V3` / `BINANCE_SPOT_STANDARD_TAKER` = **23.559016994374947 bps** (live `CostEngine`, never hardcoded).
- Baseline corpus: 21 × 5m files, `reports/strategy-baseline/data/`, fingerprint **`9d51385d570b8ff4ba1af22c3d4491f78c36111ec7383173e7d0351d5ee21658`** (untouched by ARP-005).
- Derived daily coverage: DEV 122, VALIDATION 62, OOS 24 days/symbol.

See `BASELINE.json` for the machine-readable record.

## Running processes

No test/experiment process was left running; the ARP-005 fetch ran detached and
terminated cleanly (see `DATA_GAP_ANALYSIS.md`).
