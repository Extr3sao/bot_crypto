# ARP-005 — DATA GAP ANALYSIS (PATH A, §3)

## Exact current coverage

| split | windows | days/symbol |
| --- | --- | --- |
| DEV | W1_2026-03 … W4_2026-06 | **122** |
| VALIDATION | W5_2026-07, W6_2026-08 | 62 |
| OOS_LOCK | W7_2026-09 | 24 |

There are **21** 5m base files (3 symbols × 7 windows); total depth ≈ 209 days/symbol;
baseline fingerprint `9d51385d…`.

## Exact required coverage (arithmetic, stated before any result)

Adequacy band inherited from the ARP-003 horizon audit: **≈40–60 independent holding
windows**, where `independent ≈ evaluable_days / max_hold_days`. `max_hold_days` is an
*upper* bound, so real mean holding is shorter and true trade counts can be higher.

| experiment | max_hold | evaluable DEV today | independent today | min DEV depth | gap vs 122 |
| --- | --- | --- | --- | --- | --- |
| EXP-ARP-006 / 012 | 5 | ≈95 | ≈19 | **≈230–330** | ≈110–210 |
| EXP-ARP-008 | 20 | ≈92 | ≈4–5 | **≈830–1230** | ≈2–3 years |

## Provider capability

- Provider: **Binance public REST** `GET /api/v3/klines` (market data only, no
  credentials, no order API). The existing `scripts/fetch_baseline_data.py` already
  uses it.
- Capability probe: a bounded read-only request succeeded (`NETWORK_OK`), so the
  provider serves history aligned to this environment's clock.
- **Cost:** free; ≈ 0.5 MB per symbol-month of 5m JSON; six months × 3 symbols ≈
  **9 MB**. Download wall-clock ≈ 2 minutes (0.25 s pacing).

## PIT correctness

- Fetch is *market history only*; the derivation (`daily_bars_from_5m`) is unchanged:
  a day qualifies only as a complete 288-bar UTC bucket, otherwise it is **dropped**.
  No interpolation, no synthesis, no forward fill.
- The new windows are strictly *before* the frozen W1 window; the paper run
  (2026-09-25) and OOS `W7` remain out of every window.

## Survivorship

- Universe is the fixed 3-major set `BTC/ETH/SOL` — all three existed throughout
  2025-09 … 2026-06, so **no survivorship bias** is introduced by the extension.
  (The pre-existing fixed-universe limitation for any *new* asset still applies.)

## Symbol-history requirements

- Each symbol must have a full 5m month; the fetch reports `rows` per file and the
  derivation discards any day that is not exactly complete. Partial months are simply
  not usable days, never patched.

## Reproducibility

- Files are content-addressed by sha256; `extended.ext_corpus_digest()` =
  **`d3669d28de0014bf4299361adb9cca2c4d0de9a9b856077b8e1bff92260030e0`**; the per-file
  fingerprint is in `reports/alpha-recovery-v1-4/data/_FETCH_MANIFEST.json`.
- The baseline corpus digest is **provably unchanged** (`9d51385d…`), so the frozen
  ARP-003/004 manifests still validate (asserted by a regression test).

## Decision

**CLAIM** — the EXP-ARP-006 data deficit is closable safely and reproducibly.
**SOURCE** — `scripts/fetch_alpha_recovery_extended.py`, provider probe, derived
coverage measurement.
**EVIDENCE** — extended DEV = **303 days/symbol** (inside 230–330); baseline digest
byte-identical; extended digest recorded; 22 ARP-005 tests pass.
**DECISION** — `EXTEND_CORPUS` (isolated) and execute the frozen rules as
`EXP-ARP-012`. `EXP-ARP-008` remains `DATA_SHORT_FOR_HORIZON` (needs ≈2–3 years).
