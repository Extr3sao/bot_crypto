# ARC03_SOURCE_REGISTRY.md

> Every official byte that ARC-03 depends on, with its provenance, binding and
> verification status. Machine-readable raw ledger: `ARC03_RAW_LEDGER.jsonl`
> (append-only, one JSON object per retrieved archive).
>
> **No credentials, no third-party reconstruction, no material cost.** All bytes come from
> the provider's own public archive at `https://data.binance.vision`.

---

## 1. Provider

| Property | Value |
| --- | --- |
| Provider | Binance (official public market-data archive) |
| Host | `data.binance.vision` |
| Family (primary) | `futures/um/monthly/klines` |
| Family (gap supplement) | `futures/um/daily/klines` |
| Market | Binance USD-M **perpetual** futures |
| Interval | `5m` |
| Symbols | `BTCUSDT`, `ETHUSDT`, `SOLUSDT` |
| Checksums | provider `.CHECKSUM` sidecar (SHA256) fetched for **every** archive |
| Credentials | none |
| Cost | none |

URL templates:

```
https://data.binance.vision/data/futures/um/monthly/klines/{SYMBOL}/5m/{SYMBOL}-5m-{YYYY-MM}.zip
https://data.binance.vision/data/futures/um/monthly/klines/{SYMBOL}/5m/{SYMBOL}-5m-{YYYY-MM}.zip.CHECKSUM
https://data.binance.vision/data/futures/um/daily/klines/{SYMBOL}/5m/{SYMBOL}-5m-{YYYY-MM-DD}.zip
https://data.binance.vision/data/futures/um/daily/klines/{SYMBOL}/5m/{SYMBOL}-5m-{YYYY-MM-DD}.zip.CHECKSUM
```

## 2. Raw layout (immutable)

```
data/raw/binance_um/arc03/{SYMBOL}/{YYYY-MM}/{SYMBOL}-5m-{YYYY-MM}.zip[.CHECKSUM]
data/raw/binance_um/arc03_daily/{SYMBOL}/{YYYY-MM-DD}/{SYMBOL}-5m-{YYYY-MM-DD}.zip[.CHECKSUM]
```

## 3. Provider row schema (as received)

12 comma-separated fields, **no header for monthly archives before 2022-01 and a header row
from 2022-01 onward** (a genuine provider schema change; `SOLUSDT-5m-2022-03` is an observed
exception that still has no header). Daily archives carry no header.

```
0 open_time (epoch ms, UTC)      6 close_time (epoch ms)
1 open                           7 quote_volume (USDT)
2 high                           8 count (number of trades)
3 low                            9 taker_buy_volume (base)
4 close                         10 taker_buy_quote_volume (USDT)
5 volume (base)                 11 ignore (never read)
```

## 4. Coverage (provider availability probed before any download)

`ARC03_PROVIDER_COVERAGE.json`:

| Symbol | Available months | First | Last | Internally missing |
| --- | --- | --- | --- | --- |
| BTCUSDT | 80 | 2020-01 | 2026-08 | none |
| ETHUSDT | 80 | 2020-01 | 2026-08 | none |
| SOLUSDT | 72 | 2020-09 | 2026-08 | none |

The probe is availability-only (HTTP HEAD); no data content was inspected to choose the
window. Window selection therefore depends **only** on provider availability and common
coverage — never on returns.

## 5. Coverage gaps found and how they were resolved

The monthly archives for `SOLUSDT` are internally incomplete in two months. This was found
by the data-quality contract, not assumed:

| Symbol | Month | Monthly rows | Expected rows | Missing days |
| --- | --- | --- | --- | --- |
| SOLUSDT | 2022-02 | 7,200 | 8,064 | 2022-02-26, 2022-02-27, 2022-02-28 |
| SOLUSDT | 2022-04 | 8,064 | 8,640 | 2022-04-01, 2022-04-02 |

Resolution: the **same provider's** official **daily** archives were retrieved for exactly
those five days, CHECKSUM-verified (288 contiguous rows each), and admitted as an explicit
supplementary source (`ARC03_PROVIDER_COVERAGE_SUPPLEMENT.json`, and the `daily_supplements`
registry inside `ARC03_DATA_MANIFEST.json`). No third-party or reconstructed data is used.

Deterministic rule (fail-closed):

* a month that already satisfies the authority contract is **never** supplemented (no
  duplicate dataset, no mixing);
* supplementation is attempted only for a month classified `INVALID_GAP`;
* every missing day must be present as a CHECKSUM-verified 288-row contiguous daily archive
  and the union must equal the calendar month with unbroken 5m cadence, otherwise the month
  is withheld entirely;
* for the **first** month of a symbol's history, days entirely before the month's first
  observed bar are never fabricated — a market-start partial month is admitted as
  `VALID_INITIAL_PARTIAL` only when it is a pure leading truncation that runs to month end.

## 6. Retrieval policy

* resumable and idempotent: an archive is re-downloaded only when its local SHA256 differs;
* every retrieved archive is bound in the append-only raw ledger with
  `source`, `symbol`, `month`/`date`, `url`, `size_bytes`, `provider_checksum_sha256`,
  `sha256`, `checksum_match`, `status`, `retrieved_utc`;
* `status` is `VERIFIED` only when the local SHA256 equals the provider's own CHECKSUM
  sidecar digest; `UNVERIFIED_NO_SIDECAR` and `CHECKSUM_MISMATCH` are recorded, never masked.

## 7. What is *not* a source

* no `aggTrades`, order book, OI, funding, mark price, index price or cross-asset series is
  used by ARC-03 (the reuse assessment in `ARC03_EXISTING_DATA_REUSE_ASSESSMENT.json`
  documents why existing authorities could not be reused);
* no provider field beyond `open_time/open/high/low/close/volume/close_time` is admitted
  into the strategy authority (`quote_volume`, `count`, `taker_buy_*` are carried as
  `OPTIONAL_RESEARCH_ONLY`; `ignore` is `REJECTED`).
