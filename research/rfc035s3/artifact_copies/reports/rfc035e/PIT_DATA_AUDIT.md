# RFC-035E — PIT_DATA_AUDIT

What the data is, where it came from, and what can honestly be said about availability time.

```json
{
  "artifact": "PIT_DATA_AUDIT",
  "dataset_hash": "b58adaa74e7c73f93d6c4270eba673b88216727e4ee0c133de5334a354134900",
  "pit_convention": {
    "exact_publication_timestamps": "UNKNOWN",
    "conservative_availability_rule": "flow_date + 1 calendar day at 00:00:00Z",
    "aggressive_rule": "flow_date at 00:00:00Z (contrast only, never used for conclusions)",
    "invariant": "available_to_strategy_at <= decision_time"
  },
  "pit_status": "UNKNOWN (exact historical publication timestamps are not published by the provider)",
  "calendar": {
    "sessions": 703,
    "first": "2024-01-11",
    "last": "2026-10-07",
    "btc_close_join_nulls": 0
  },
  "flow_series": {
    "mean_usd_m": 82.34082503556186,
    "sd_usd_m": 336.02272015318755,
    "min_usd_m": -1113.7,
    "max_usd_m": 1373.8,
    "zero_days": 17,
    "cumulative_usd_m": 57885.59999999999
  },
  "record_contract": {
    "fields": {
      "flow_date": "the provider's session date as published (column header of the flow table)",
      "flow_value": "the provider's net flow for that session, US$ millions, blank read as zero",
      "source": "RF-01 Farside Investors, US spot BTC ETF flow table (see raw_source_manifest.json)",
      "source_observed_at": "the retrieval timestamp of the raw artifact, recorded in raw_source_manifest.json",
      "source_published_at": "UNKNOWN: the provider does not publish a per-day publication timestamp",
      "available_to_strategy_at": "flow_date + 1 calendar day at 00:00:00Z (conservative declared rule)",
      "retrieved_at": "2026-10-07T22:07:29Z (raw_source_manifest.json: retrieved_at_utc)",
      "raw_artifact_hash": "SHA-256 of the raw HTML artifact, recorded per source in raw_source_manifest.json",
      "normalized_record_hash": "SHA-256 of the canonical triple (flow_date, flow_value, conservative available_to_strategy_at), recomputable from the raw artifact by the derived layer"
    },
    "unknown_fields": [
      "source_published_at"
    ],
    "records_with_unknown_publication_ts": 703,
    "invariant": "available_to_strategy_at <= decision_time; never the flow_date itself",
    "example_records": [
      {
        "flow_date": "2024-01-11",
        "flow_value_usd_m": 655.3,
        "available_to_strategy_at": "2024-01-12T00:00:00Z",
        "source_published_at": "UNKNOWN",
        "normalized_record_hash": "77299384fafebc8f3442ee93d232998046cb9b9e2ef751e903ff987a395b2357"
      },
      {
        "flow_date": "2025-05-16",
        "flow_value_usd_m": 260.2,
        "available_to_strategy_at": "2025-05-17T00:00:00Z",
        "source_published_at": "UNKNOWN",
        "normalized_record_hash": "ca9cc64d0b35df3d7ec2cff9796ab4fb37629b18ad1840d7847066572747900c"
      }
    ]
  },
  "raw_manifests": {
    "manifest_version": "RFC035E_RAW_SOURCE_MANIFEST_V1",
    "retrieved_at_utc": "2026-10-07T22:07:29Z",
    "offline_rederivation": false,
    "sources": [
      {
        "source_id": "RF-01",
        "provider": "Farside Investors (farside.co.uk)",
        "url": "https://farside.co.uk/bitcoin-etf-flow-all-data/",
        "object": "raw html of the all-data flow page",
        "path": "data\\rfc035e\\raw\\farside_btc_etf_flow_all_data.html",
        "sha256": "2e532435486112465a5ba09b3203585219343bcd5b6c8531e6a46ca339bae588",
        "bytes": 823991,
        "schema": "html table, US$m",
        "timezone": "flow_date is the US cash session date",
        "coverage": "2024-01-11..2026-10-07",
        "rows": 703,
        "blank_cells": 905,
        "transformations": "none applied at fetch time; parsing happens in the derived layer"
      },
      {
        "source_id": "RF-02",
        "provider": "Binance public REST",
        "url": "api/v3/klines BTCUSDT 1d",
        "object": "daily kline array",
        "path": "data\\rfc035e\\raw\\binance_btcusdt_1d_klines.json",
        "sha256": "47b9e0c96f8588e792d062f77339f858a8a350328c1e18ff7df6fa58e5582531",
        "bytes": 195214,
        "schema": "Binance kline: [openTime, o, h, l, close, volume, closeTime, ...]",
        "timezone": "UTC (openTime)",
        "coverage": "2024-01-11..2026-10-07",
        "rows": 1042,
        "blank_cells": 0,
        "transformations": "none applied at fetch time"
      }
    ]
  },
  "known_limits": [
    "the provider's table is final-data only: revisions to a day, if any, are not observable",
    "blank cells are read as zero flow and counted (see the raw manifest)",
    "the conservative availability rule (flow_date + 1 day at 00:00Z) is a declared convention, not a claim that the number was published at that instant",
    "BTC closes come from Binance spot 1d klines, while the source's price side is not identified"
  ]
}
```
