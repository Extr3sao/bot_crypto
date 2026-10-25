# ST-6 — independent verification

Generated 2026-10-08T17:26:36Z. Verifier `scripts/st6_forward_regime_verify.py`, builder `scripts/st6_forward_regime.py`.

**PASS** — 290/290 checks, 0 mismatches, FALSE_SUCCESS = 0. Verdict **ST6_FORWARD_EVIDENCE_VERIFIED**.

## What was re-derived

spread and depth recomputed from the raw window bytes through a cumulative-capacity walk; statistics, coverage, thresholds, the ST-6 verdict and the breach list re-derived independently; governance re-read from configuration and from the builder's syntax tree.

Raw windows verified: 1.

## Artefact hashes verified as bytes

| artefact | sha256 |
| --- | --- |
| `ST6_PERIOD.json` | `5dd14bc8eac887786129d06e5aafed3d…` |
| `ST6_WINDOWS.jsonl` | `4153f5920c8d514001ae9bc2bc2c4d4f…` |
| `ST6_OBSERVATIONS.jsonl` | `2b1fb3c756191334d4e73f953335ebc1…` |
| `ST6_REGIME_COVERAGE.json` | `7f521147dc9bd1a867f02652dfad2077…` |
| `ST6_MODEL_DRIFT.json` | `96e2d6ec9c4f2efff51ba157c3eaf6a3…` |
| `ST6_FORWARD_REGIME_REPORT.json` | `1bd5fea6009c43c85d4d5bd1c0d45056…` |

Builder outcome corroborated: **INSUFFICIENT_REGIME_COVERAGE**; coverage token corroborated: **REGIME_COVERAGE_INSUFFICIENT**.

## Failures

None. Every recomputation agreed with the builder's artefact.
