# Price Authority V2 Report — PRICE-AUTHORITY-REPAIR-01

## Verdict: PASS

- **Common window**: `2021-12-01T00:00:00Z → 2026-09-10T23:00:00Z` (H6 V2 spec `2021-12-01T00:00:00Z → 2026-09-10T23:59:59Z`; price bars are hourly openTime buckets, last open `2026-09-10T23:00Z` covers window end).
- **Expected hours per asset**: `41880`
- **Missing / duplicate / conflicting**: `0 / 0 / 0` for all three assets.

| Asset | V2 rows total | H1 base rows | Extension rows | Missing added | Covers window | V2 sha256 |
|-------|---------------|--------------|----------------|---------------|---------------|-----------|
| BTCUSDT | 58680 | 58633 | 48 (2026-09-09+10) | 47 | true | 41e9238666a0b98c02cffd19d36a590b8463f6556e215c49f068452674ef9027 |
| ETHUSDT | 58680 | 58633 | 48 | 47 | true | 7c72c0bb55d4aac9460dde54eb73305b5d30bdec99ea4b500eac9e1319ddd7ba |
| SOLUSDT | 52505 | 52458 | 48 | 47 | true | 6f147463b504f5026d887e77306cfa629ee5feb8cbdb01923643133091da03ff |

- **Authority SHA256 V2**: `e1c2462a6aa9ba0c921154d259a28c49be1e2fc58a544dbd97af8ecabef52168` (sha256 of canonical JSON `{sorted symbol → v2_sha256}`).

## Source authority

- Frozen H1 klines at `cb3de4f` (`docs/external-audit-01/h1-regime-transition-01/dataset/*_1h.jsonl`) as base — byte-identical check PASS.
- Missing 47 hours (2026-09-09T01:00Z → 2026-09-10T23:00Z) repaired from official `data/raw/binance_um/klines_1h_ext/` daily zip archives (official data.binance.vision).
- Overlap at `2026-09-09T00:00Z` byte/economic equality PASS for all three assets; no `PRICE_AUTHORITY_CONFLICT`.

## Continuity

- Every required 1h bucket from `1638316800000` to `1789081200000` inclusive hourly is present, sequential, no gaps, no duplicate openTime, no non-hourly transition.
- Price fields used: `openTime`, `open`, `close` (H6 V2 spec).

## Evidence

- `PRICE_1H_AUTHORITY_V2_MANIFEST.json` with per-asset continuity metadata.
- V2 files: `data/processed/price_1h_v2/*_1h.jsonl` (copies in `docs/external-audit-01/oi-full-history-02/*_1h_v2.jsonl` for evidence).

## Status

`PRICE_AUTHORITY_V2 = PASS` — window fully covered; no H6 price gap remains.
