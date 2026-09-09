# FUNDING HISTORY SOURCE PROPOSAL (§15 — SOURCE only, NO execution)

| Field | Value |
| --- | --- |
| checkpoint | POC02-OBSERVATION-AND-ALPHA-DIAGNOSIS-01 |
| status | **SOURCE_PROPOSAL — NOT EXECUTED** |
| date | 2026-09-09 |
| motivation | carry_funding 1h cells were `INSUFFICIENT_SAMPLE` (public depth ≈ 30 d assumed) |

## What was verified (live, read-only public probes, 2026-09-09)

| Probe | Result |
| --- | --- |
| `fetchFundingRateHistory(BTC/USDT:USDT, limit=1000)` default | 500 obs → 166.3 d (page cap, **not** total depth) |
| same, `since=2020-01-01` | 1000 obs from 2020-01-01T00:00Z — page returns full 1000 |
| same, `since=2019-01-01` | first obs **2019-09-10T08:00:00Z** (BTC perp listing-adjacent) |
| raw `fapiPublicGetFundingRate({startTime, limit:1000})` | identical payload — authoritative endpoint `/fapi/v1/fundingRate` |
| observed interval | 8h funding settlements (epoch ms) |
| credentials | none used (public market data only) |

## Conclusion

- TRUE depth ≈ **2019-09-10 → present** (≥ 1000 obs/symbol/page, paginated
  by `startTime`; ~6 years of 8h settlements ≈ 6,500+ obs/symbol).
- Batch-02's `INSUFFICIENT_SAMPLE` was an artifact of the fetch (default
  `limit` behavior = most-recent page only), **not** a data-availability
  ceiling.

## Proposed source contract (to validate BEFORE any research execution)

1. **source**: `binanceusdm` public `/fapi/v1/fundingRate` via ccxt
   `fetchFundingRateHistory(since=<deep start>, limit=1000)` + `startTime`
   pagination until `endTime` coverage.
2. **schema**: `{symbol, fundingTime(epoch ms), fundingRate(decimal)}` —
   canonicalized under `FUNDING-UNITS-CANONICAL-V1` (ms spacing, decimal
   per-8h rate).
3. **timestamp semantics**: `fundingTime` = settlement instant; rate applies
   AT settlement, not before.
4. **PIT semantics**: a decision at `t` may only use rates with
   `fundingTime <= t` (existing `restrict_to_window` contract).
5. **cost semantics**: carry PnL accrues per holding period between
   settlements the position is held through; taker entry/exit costs from the
   frozen `ExecutionCostModel` (4–5 bps + slippage) — unchanged.

## Required validations before DISCOVERY research may execute

- [ ] per-symbol full-depth backfill with per-page gap detection
      (monotonic `fundingTime`, no duplicates, expected 8h cadence)
- [ ] fingerprint each symbol's dataset (`FundingDataset.fingerprint`)
- [ ] cross-check overlap region against batch-02's 90-obs fetch (must
      match exactly — no silent revision)
- [ ] window/asset matrix preregistered BEFORE execution (same frozen
      protocol as batch-02; no threshold changes)

## Explicitly NOT done here

- No new research executed; no candidate spec written; no thresholds touched.
- Discovery Batch 03 remains NOT_STARTED (§13: only a validated coverage gap
  plus this validated source would justify preregistration).
