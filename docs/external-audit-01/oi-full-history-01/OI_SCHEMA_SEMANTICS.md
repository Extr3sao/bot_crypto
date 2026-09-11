# OI SCHEMA SEMANTICS — OI-FULL-HISTORY-FREEZE-01 (Track B)

Schema **2.0.1** · Normalizer **2.1.0**

Authority chain: **OFFICIAL_EXCHANGE_DOC** — Binance USDⓈ-M Futures `openInterestHist` documentation (field semantics of `sumOpenInterest` / `sumOpenInterestValue`) + the official `binance-public-data` archive schema for daily `metrics` files (data.binance.vision). No third-party source.

## Canonical field mapping (frozen for this checkpoint)

| Provider raw field | Canonical field | Unit | Timestamp semantics | Nullable | Validation rule | PIT interpretation |
| --- | --- | --- | --- | --- | --- | --- |
| `create_time` | `timestamp_ms` | UTC epoch milliseconds | Observation time of the 5m aggregate snapshot (end-of-interval semantics; the snapshot summarizes outstanding positions at that instant). NOT a trade time. | no | integer > 0; must land on the 5m UTC grid | `data_time`; usable for decisions at `decision_time >= timestamp_ms` only |
| `sum_open_interest` | `sum_open_interest` (alias `open_interest_base_units`) | **BASE-ASSET UNITS** (BTC for BTCUSDT, ETH for ETHUSDT, SOL for SOLUSDT) — per official docs, `sumOpenInterest` is total open interest in base asset units | snapshot at `create_time` | no | finite float > 0 (0 allowed only if provider emits it; recorded as `INVALID_VALUE` if null/negative) | value observed at `data_time`; no interpolation |
| `sum_open_interest_value` | `sum_open_interest_value` (alias `open_interest_quote_value`) | **USDT (quote/notional)** | snapshot at `create_time` | no | finite float > 0 | value observed at `data_time`; no interpolation |
| `symbol` | `symbol` | — | — | no | must equal the file's symbol (provider-mismatch guard) | — |

## Unit governance (OI-08)

- The two OI fields are **never** both called "contracts". `sum_open_interest` is base-asset units; `sum_open_interest_value` is USDT notional.
- Historical v1.0.0 persisted data used the name `open_interest_contracts` for `sum_open_interest`. That name is **deprecated but not silently renamed**: the v2.0.0 contract keeps a compatibility alias and mandates metadata `unit_semantics = BASE_ASSET_UNITS` wherever the deprecated name appears.
- Implied mark price (`sum_open_interest_value / sum_open_interest`) is **not** an admitted field; it may be computed only inside a preregistered feature definition, never as a new data column at admission time.

## Provider raw format (measured, all eras 2020-09 → 2026-09)

- `create_time` is a **string** `"YYYY-MM-DD HH:MM:SS"` in UTC (not epoch ms). The normalizer converts to UTC epoch ms deterministically.
- **DEF-DATA-OI-002 (provider emission artifact):** files from **2020-09 through 2021-05 emit every row exactly twice** (576 rows = 288 unique timestamps, byte-identical payloads). The v2.0.1 contract collapses **exact duplicate rows** deterministically; a timestamp repeating with a *different* payload invalidates the day (`INVALID_DUPLICATE`). Raw files are never modified.
- Sample-window files previously normalized under schema 1.0.0 (epoch-ms assumption) are superseded by schema 2.0.1; the 2026-09-01..07 sample days re-derive identically under the corrected parser (verified: string timestamps map to the same 5m grid).

## Cadence and valid-day semantics

- Native cadence: **5m** (`EXPECTED_INTERVAL_SECONDS=300`, `EXPECTED_ROWS_COMPLETE_UTC_DAY=288`), grid 00:00–23:55 UTC.
- Raw provider row order is **not authoritative** (files are not sorted); deterministic normalization sorts by `timestamp_ms`.
- A valid day is defined exactly in the Valid-Day Contract (Track E ledger: `OI_DAY_VALIDITY_LEDGER.jsonl`).

## Provenance invariants (every normalized file)

`RAW_SOURCE_SHA256` · `NORMALIZER_VERSION` · `NORMALIZER_COMMIT` · `NORMALIZED_SHA256` — raw provider originals are immutable under `data/raw/binance_um/metrics/<SYMBOL>/`.
