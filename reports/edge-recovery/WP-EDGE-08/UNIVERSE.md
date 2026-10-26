# WP-EDGE-08A — the unread cross-section

*Read at `2026-10-14T20:34:47Z` (`EDGE08_V1`). Claim: these six symbols have never been the input of a committed measurement in this repository, so their history is an unread cross-section.*

## 1. The verdict of the disjointness check

**HOLDOUT_CLAIM_HOLDS** — 0 violation(s), allowed kinds: catalogue, fetch_or_list_script, test, documentation, this_work_package.

Method: git grep over TRACKED files (an untracked scratch file cannot argue a symbol is clean, and a committed shard cannot hide), classified by path; plus a glob for a shard of the symbol in every corpus this repository already holds.

| Symbol | Tracked files mentioning it | Kinds |
| --- | --- | --- |
| AAVEUSDT | 5 | catalogue, this_work_package |
| CRVUSDT | 5 | catalogue, this_work_package |
| KSMUSDT | 6 | catalogue, this_work_package |
| SNXUSDT | 5 | catalogue, this_work_package |
| SUSHIUSDT | 5 | catalogue, this_work_package |
| UNIUSDT | 5 | catalogue, this_work_package |

## 2. What was fetched, and how much of it is there

- Source: `BINANCE_PUBLIC_REST:/api/v3/klines`, fetched `2026-10-14T20:29:04Z`, range `{'start_utc': '2021-01-01T00:00:00Z', 'end_utc_exclusive': '2026-10-14T19:00:00Z'}`.
- Corpus digest (per-shard SHA-256, sorted by symbol): `fb32470f5bc6329eee558dfdbc436685ad4de91a7a7374ea329499c1c258735b`.
- Totals: {'symbols': 6, 'bars': 304158, 'bytes': 15687107, 'gaps': 42, 'failures': 0, 'symbols_below_coverage_floor': []}.

| Symbol | Bars | First | Last | Gaps | Coverage % | Shard bytes | SHA-256 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| AAVEUSDT | 50693 | 2021-01-01T00:00:00Z | 2026-10-14T18:00:00Z | 7 | 99.9724 | 2644159 | `e3d555cd638aa8bc…` |
| CRVUSDT | 50693 | 2021-01-01T00:00:00Z | 2026-10-14T18:00:00Z | 7 | 99.9724 | 2699802 | `37a5307f9421f2ad…` |
| KSMUSDT | 50693 | 2021-01-01T00:00:00Z | 2026-10-14T18:00:00Z | 7 | 99.9724 | 2549344 | `93cf90eb3db64261…` |
| SNXUSDT | 50693 | 2021-01-01T00:00:00Z | 2026-10-14T18:00:00Z | 7 | 99.9724 | 2571519 | `0de3844f4eb3cd55…` |
| SUSHIUSDT | 50693 | 2021-01-01T00:00:00Z | 2026-10-14T18:00:00Z | 7 | 99.9724 | 2620712 | `b2c3ab061509065d…` |
| UNIUSDT | 50693 | 2021-01-01T00:00:00Z | 2026-10-14T18:00:00Z | 7 | 99.9724 | 2601571 | `7d68f4d3f8291557…` |

## 3. Complete bars per window, per clock

A bar exists only where its whole bucket does: the 4h and 1d series are aggregated from the 1h shards by the campaign's own `resample`, which emits a bucket only when every source hour is present and contiguous. Below the declared floor the decisive window cannot carry a verdict for that clock.

### Clock `1h` (floor 8000 bars per asset on the decisive window)

| Window | DEV | OOS | VAL |
| --- | --- | --- | --- |
| `DEV` | 26266 | 26266 | 26266 | 26266 | 26266 | 26266 |
| `VAL` | 8784 | 8784 | 8784 | 8784 | 8784 | 8784 |
| `OOS` | 15633 | 15633 | 15633 | 15633 | 15633 | 15633 |

### Clock `4h` (floor 1500 bars per asset on the decisive window)

| Window | DEV | OOS | VAL |
| --- | --- | --- | --- |
| `DEV` | 6561 | 6561 | 6561 | 6561 | 6561 | 6561 |
| `VAL` | 2196 | 2196 | 2196 | 2196 | 2196 | 2196 |
| `OOS` | 3909 | 3909 | 3909 | 3909 | 3909 | 3909 |

### Clock `1d` (floor 400 bars per asset on the decisive window)

| Window | DEV | OOS | VAL |
| --- | --- | --- | --- |
| `DEV` | 1088 | 1088 | 1088 | 1088 | 1088 | 1088 |
| `VAL` | 366 | 366 | 366 | 366 | 366 | 366 |
| `OOS` | 651 | 651 | 651 | 651 | 651 | 651 |

## 4. What this does not say

- the corpus is one venue's public REST feed, 1h bars, capped at the last closed hour before the fetch; gaps are left absent and counted, never filled
- the cross-section has no BTC in it by construction: a benchmark series is built from the frozen BTC corpus, and the label it produces is read out of the run, never into a signal
- no order book is modelled per symbol: the cost plane is venue-level and the ADVERSE scenario is the sensitivity that speaks to thinner names
