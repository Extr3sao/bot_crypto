# ARP-005 — RESEARCH PORTFOLIO TRIAGE

Primary objective: **discover strategy candidates whose signal magnitude is
economically capable of surviving realistic trading costs.** Not more trades, not
paper execution. Required relationship before expensive downstream work:
`gross_edge >> expected_cost`.

Authority order applied throughout: REAL_RUNTIME > EXECUTION_EVIDENCE > TESTS >
SOURCE_CODE > ARCH/RFC > EXTERNAL_SOURCE > ASSUMPTION. `FALSE_SUCCESS = 0`.

Three evidence-backed paths were evaluated independently.

## PATH A — EXP-ARP-006 / EXP-ARP-008 data deficit → **RESOLVED (safe+reproducible)**

Six earlier provider months (2025-09 … 2026-02) were fetched read-only into an
**isolated** corpus, raising DEV to **303 days/symbol** — inside the ARP-004
adequacy band (≈230–330) — **without moving the frozen baseline fingerprint**. The
resolved experiment is executed as `EXP-ARP-012`. Details: `DATA_GAP_ANALYSIS.md`.

## PATH B — cross-sectional infrastructure → **REIMPLEMENT_MINIMAL_PATTERN**

`CrossSectionalEngine` is `ORPHAN`. A new, minimal, tested, PIT-safe ranker
(`research/alpha_recovery/xsec.py`) was written instead of repairing the legacy
engine, unblocking `EXP-ARP-009`. Details: `CROSS_SECTIONAL_ENGINE_AUDIT.md`.

## PATH C — new cost-compatible candidates → **SMALL ORTHOGONAL PORTFOLIO**

Only three mechanisms were carried to a frozen experiment (no brute force):

| experiment | family | mechanism | dataset | status |
| --- | --- | --- | --- | --- |
| `EXP-ARP-009` | cross-sectional momentum | hold the top trailing-30d-return asset, rotate on rank loss | baseline | executed |
| `EXP-ARP-011` | breakout / vol expansion | Donchian-20 high **and** ATR-expansion gate, long | baseline | executed |
| `EXP-ARP-012` | mean reversion after displacement | fade a ≥3-day ≥2×ATR void after a band retest | extended | executed |

Deferred with explicit reasons (NOT executed):

| experiment | reason |
| --- | --- |
| `EXP-ARP-008` (`H-DAILY-TSMOM-001`, 20-day holds) | still `DATA_SHORT_FOR_HORIZON`: needs ≈830–1230 DEV days; the +6-month extension reaches 303, far short. A shorter sub-horizon would be a *different* experiment. |
| `EXP-ARP-006` (150-baseline) | superseded by `EXP-ARP-012` on the extended corpus (same rules, adequate sample). |
| `EXP-ARP-010` (`H-VOLSPIKE-MR-001`) | ARP-004 `INSUFFICIENT_EVIDENCE`; **frozen `vol_z_entry=2.0` not lowered** — trigger-starved at 1d, do not re-run. |

## Why these three are genuinely orthogonal (§16)

- 009 selects **across** assets (relative), long-only, driven by cross-sectional rank.
- 011 selects **within** an asset on range expansion (continuation).
- 012 selects **within** an asset on displacement (reversion).

Signal overlap, trade overlap and return-correlation measurement is reported in
`EXPERIMENT_REGISTRY.jsonl`; with 17/2/62 DEV trades and different universes the
measured overlaps are dominated by sample size and are reported as descriptive only.

## Frequency (§15)

Measured, never optimised. DEV trades/day: 009 ≈ 0.14, 011 ≈ 0.02, 012 ≈ 0.20.
All are far below the product-level ~3/day target — recorded as a product gap, **not**
used to relax any research threshold.
