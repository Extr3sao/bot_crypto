# OI FULL-HISTORY DATA QUALITY REPORT — OI-FULL-HISTORY-FREEZE-01

**OI_FULL_HISTORY_QUALITY: `PASS_WITH_EXPLICIT_GAPS`** · Dataset SHA256: `16779b7d2eff0dc9e56015c444c2dbe7b67ef083e6cf1877a024a6de74098d99` · Source: official data.binance.vision USD-M metrics archive · Native cadence **5m** · Schema 2.0.1 / Normalizer 2.1.0

## Totals

| Metric | Value |
| --- | --- |
| Files (zip, checksum-verified) | **5,691** |
| Valid days | **5,596** (98.3%) |
| Invalid days | **95** (1.7%) — all classified, none dropped silently |
| Rows (valid days) | **1,611,648** |
| Checksum failures | **0** |
| Schema drift | **0** |
| Invalid values | **0** |
| Missing dates (download) | **0** |

## Per asset

| Asset | Files | Valid | Invalid | Rows | Range (UTC) | Gap character |
| --- | --- | --- | --- | --- | --- | --- |
| BTCUSDT | 2,201 | 2,129 | 72 | 613,152 | 2020-09-01 → 2026-09-10 23:55 | isolated single days (4–17 missing 5m intervals each) |
| ETHUSDT | 1,745 | 1,735 | 10 | 499,680 | 2021-12-01 → 2026-09-10 23:55 | isolated single days |
| SOLUSDT | 1,745 | 1,732 | 13 | 498,816 | 2021-12-01 → 2026-09-10 23:55 | 12 gap days + 1 grid-shift day (2024-04-02) |

## Gap structure and research impact (no future knowledge used)

- Inside the **common research window (2021-12-01 → 2026-09-10)**: **zero multi-day gap runs**; every invalid day is isolated (BTC 10, ETH 10, SOL 13).
- **1,732 / 1,745 days (99.3%) are valid for all three symbols simultaneously.**
- Exclusion policy: H6 uses the day-level validity ledger (`OI_DAY_VALIDITY_LEDGER.jsonl`), computed from same-day data only. No synthesis, no interpolation, no forward-fill, no backfill from future samples.

## Provider-format findings (registered)

- `DEF-DATA-OI-002`: files from **2020-09 → 2021-05 emit every row exactly twice** (576 = 2×288, byte-identical payloads). Schema 2.0.1 collapses *exact* duplicates deterministically; a timestamp repeating with a different payload would invalidate the day. Raw files untouched.
- `create_time` is a UTC string `"YYYY-MM-DD HH:MM:SS"` in **all** eras (the earlier epoch-ms reading was a normalizer defect, corrected before freeze; the corrected parser re-derives the already-validated 2026-09-01..07 sample days identically).
- Provider files are **not row-sorted** in any era; deterministic sort is part of normalization (order inversions counted per file in the ledger).

Machine-readable: `OI_FULL_HISTORY_DATA_QUALITY_REPORT.json` · Day-level evidence: `OI_DAY_VALIDITY_LEDGER.jsonl` (in `data/processed/oi_full_history/`).
