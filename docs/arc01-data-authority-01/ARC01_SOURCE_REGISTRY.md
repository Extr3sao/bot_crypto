# ARC-01 Source Registry

| SOURCE_ID | Title | URL / Source | Type | Version / Date | Data semantics | Evidence | Reliability |
|---|---|---|---|---|---|---|---|
| `OFF-BINANCE-VISION-01` | Binance public data (data.binance.vision) | https://data.binance.vision/ | `OFFICIAL_DATA` | monthly archive 2020-01..2026-08 + daily metrics | `data/futures/um/monthly/fundingRate/<SYMBOL>/<SYMBOL>-fundingRate-YYYY-MM.zip` fields `calc_time,funding_interval_hours,last_funding_rate` (8h std; SOL 2022-11 tmp 2h/4h); `.CHECKSUM` sha256 per file | `data/raw/arc01_funding/vision_monthly/*/*.zip.CHECKSUM` verified; 232 zips verified | HIGH — official exchange archive, byte-verified |
| `OFF-BINANCE-FUTURES-API-01` | Binance USD-M futures `/fapi/v1/fundingRate` | https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Get-Funding-Rate-History | `OFFICIAL_DOC` + `OFFICIAL_DATA` | REST live 2026-09 tail (42 rows 2026-08-31..2026-09-14, limit=1000, startTime cursor) | `fundingTime (ms), fundingRate (decimal per interval), markPrice, rateType` | `data/raw/arc01_funding/rest_tail/*_rest_tail.jsonl` (fetched via `ccxt.binanceusdm.fetchFundingRateHistory`, enableRateLimit) | HIGH — official public market-data endpoint, no creds, PIT semantics verified |
| `OFF-BINANCE-DOC-01` | Binance USD-M futures market-data documentation | https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data | `OFFICIAL_DOC` | — | documents funding mechanism / settlement / availability semantics | referenced by program | HIGH |
| `SRC-ARC01-NORMALIZER-01` | ARC-01 funding normalizer | `scripts/normalize_arc01_funding.py` + `src/trading_bot/research/arc01/funding_reader.py` | `SOURCE_CODE` | `1.0.0` commit `e7f470d` | normalized schema: `symbol, funding_time_utc/ms, funding_rate (decimal per interval), funding_interval_hours, availability/settlement (=funding), next_funding derived, source, source_sha256, rateType`; contract `FUNDING-UNITS-CANONICAL-V1` (decimal_fraction_per_interval; LONG PAYS positive); PIT `data_time <= decision_time` | `docs/arc01-data-authority-01/ARC01_FUNDING_MANIFEST.json` (dataset_sha `5f4845f50...`, canonical_rows_sha `34f736b1...`) | FROZEN — deterministic A/B and mutation-sensitive, PIT-adversarial verified |
| `SRC-OI-V2-01` | H6 OI full-history V2 authority (reuse) | `docs/external-audit-01/oi-full-history-02/OI_FULL_HISTORY_DATASET_MANIFEST_V2.json` | `OFFICIAL_DATA` (Vision) + `SOURCE_CODE` | `2.1.0` | `metrics/daily` 5m OI (`sum_open_interest` BASE, `sum_open_interest_value` USDT) | 5691 ledger entries; dataset_sha `16779b7d2eff`, common window `2021-12-01..2026-09-10`, V2 PIT-true causal reader | RUNTIME_AUTHORITATIVE — reuse PASS |
| `SRC-PRICE-V2-01` | H1 + V2 price 1h authority (reuse) | `docs/external-audit-01/oi-full-history-02/PRICE_1H_AUTHORITY_V2_MANIFEST.json` | `OFFICIAL_DATA` + `SOURCE_CODE` | H1 `cb3de4f` + tail `build_price_authority_v2.py` | 1h klines 12-field; common window `2021-12-01..2026-09-10`, overlap PASS | price sha `e1c2462a6aa9`, 41880 hours, 47-hour Vision extension checksum-verified | RUNTIME_AUTHORITATIVE — reuse PASS |

## Licensing vs data terms

- Vision tooling on GitHub may be MIT, but the **data** itself is under Binance official public data terms (same distinction enforced in `docs/external-audit-01/data-admission-01/DATA_SOURCE_REGISTRY.json`).
- REST market-data is public, no credentials, within rate limits.

## Preference hierarchy satisfied

- `OFFICIAL_DATA` for funding (Vision archive + REST) preferred over third-party reconstructions; no third-party reconstruction used.
- `OFFICIAL_DOC` for mechanism/semantics.

## Per-symbol coverage actually admitted

- BTCUSDT: `2020-01-01T00:00:00Z` → `2026-09-14T16:00:00Z` (7347 settlements; 8h std)
- ETHUSDT: same
- SOLUSDT: `2020-09-13T16:00:00.004000Z` → `2026-09-14T16:00:00Z` (6652 settlements; 2h/4h change 2022-11 per `funding_interval_hours`)

## Reliability classifier

All three funding sources above are `OFFICIAL_DATA`/`OFFICIAL_DOC`/`SOURCE_CODE` tier (no assumptions-tier data admitted for funding rates).
