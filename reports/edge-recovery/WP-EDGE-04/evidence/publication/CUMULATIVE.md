# EDGE-03 forward observation — cumulative

Run `FWD-EDGE03-20261015T151637Z` at 2026-10-15T15:17:18Z; market instant 2026-10-15T15:16:37Z.

**OBSERVATION_AVAILABLE** — 228 independent observation day(s) accumulated; the lane still promotes nothing (the forward pipeline does not read an admission criterion)

Promotion: **NONE**. Risk parity: **PARITY_PASS**.

## What was observed

| series | bars | first bar (UTC) | last bar (UTC) | observation days | gaps | duplicates |
| --- | ---: | --- | --- | ---: | ---: | ---: |
| `15m:BTC` | 782 | 2026-10-07T11:45:00Z | 2026-10-15T15:00:00Z | 7 | 0 | 0 |
| `15m:ETH` | 782 | 2026-10-07T11:45:00Z | 2026-10-15T15:00:00Z | 7 | 0 | 0 |
| `15m:SOL` | 782 | 2026-10-07T11:45:00Z | 2026-10-15T15:00:00Z | 7 | 0 | 0 |
| `1h:BTC` | 5487 | 2026-03-01T00:00:00Z | 2026-10-15T14:00:00Z | 228 | 0 | 0 |
| `1h:ETH` | 5487 | 2026-03-01T00:00:00Z | 2026-10-15T14:00:00Z | 228 | 0 | 0 |
| `1h:SOL` | 5487 | 2026-03-01T00:00:00Z | 2026-10-15T14:00:00Z | 228 | 0 | 0 |

Total independent observation days (densest 1h series): **228** of a declared floor of 60.

## Ingest ledger

Observation pass: **6** series attempted; outcomes: `ingested` 3, `no_new_data` 3.

Ledger rows on file: **1716** (6 from the observation pass, 1710 from the restart pass at the same instant).

## Ingestion latency of the bars this run pulled (bar close → store)

| series | bars pulled | min s | median s | max s |
| --- | ---: | ---: | ---: | ---: |
| `15m:BTC` | 1 | 98 | 98 | 98 |
| `15m:ETH` | 1 | 98 | 98 | 98 |
| `15m:SOL` | 1 | 98 | 98 | 98 |

These are the bars stamped with this run's fetch instant — the lag a scheduled reader meets, measured from each bar's close to the moment it reached the store.

## Window latency over every stored bar (backfill included)

| series | samples | fetches | min s | median s | max s |
| --- | ---: | ---: | ---: | ---: | ---: |
| `15m:BTC` | 782 | 145 | 4 | 122,541 | 473,991 |
| `15m:ETH` | 782 | 145 | 4 | 122,541 | 473,991 |
| `15m:SOL` | 782 | 145 | 4 | 122,541 | 473,991 |
| `1h:BTC` | 5487 | 43 | 4 | 9,646,791 | 19,521,591 |
| `1h:ETH` | 5487 | 43 | 4 | 9,646,791 | 19,521,591 |
| `1h:SOL` | 5487 | 43 | 4 | 9,646,791 | 19,521,591 |

The first run fetched the whole window in one pass, so this table is the **backfill** distance (each bar's close to that run's instant), not a property of the feed. The table above is the one that answers "how fresh is the store".

## Restart and duplicate proof

- A second ingest at the same instant produced `['no_new_data']` for every series and appended **0** bar(s).
- Store digests identical before and after the second run: **yes**.
- Duplicate timestamps anywhere in the store: **0**.
- Duplicate (asset, instant, reason) refusals in the primary arm: **0**.

## Frozen rulesets, read forward

| arm | timeframe | scenario | window bars | signals | hypothetical fills | net USDT | max DD % | exposure % |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `edge_intra_01:2X_FEES` | 15m | 2X_FEES | 2346 | 0 | 0 | 0 | 0.00 | 0.00 |
| `edge_intra_01:ADVERSE` | 15m | ADVERSE | 2346 | 0 | 0 | 0 | 0.00 | 0.00 |
| `edge_intra_01:BASE` | 15m | BASE | 2346 | 0 | 0 | 0 | 0.00 | 0.00 |
| `edge_intra_01r_limit:BASE` | 15m | BASE | 2346 | 0 | 0 | 0 | 0.00 | 0.00 |
| `edge_intra_01r_market:2X_FEES` | 15m | 2X_FEES | 2346 | 0 | 0 | 0 | 0.00 | 0.00 |
| `edge_intra_01r_market:ADVERSE` | 15m | ADVERSE | 2346 | 0 | 0 | 0 | 0.00 | 0.00 |
| `edge_intra_01r_market:BASE` | 15m | BASE | 2346 | 0 | 0 | 0 | 0.00 | 0.00 |
| `edge_intra_02:2X_FEES` | 15m | 2X_FEES | 2346 | 0 | 0 | 0 | 0.00 | 0.00 |
| `edge_intra_02:ADVERSE` | 15m | ADVERSE | 2346 | 0 | 0 | 0 | 0.00 | 0.00 |
| `edge_intra_02:BASE` | 15m | BASE | 2346 | 0 | 0 | 0 | 0.00 | 0.00 |
| `edge_trend_01_1d:2X_FEES` | 1d | 2X_FEES | 684 | 5 | 3 | -59.09 | 0.70 | 9.21 |
| `edge_trend_01_1d:ADVERSE` | 1d | ADVERSE | 684 | 5 | 3 | -59.31 | 0.70 | 9.21 |
| `edge_trend_01_1d:BASE` | 1d | BASE | 684 | 5 | 3 | -57.75 | 0.69 | 9.21 |
| `edge_trend_01_4h:2X_FEES` | 4h | 2X_FEES | 4113 | 103 | 31 | -73.77 | 2.94 | 28.57 |
| `edge_trend_01_4h:ADVERSE` | 4h | ADVERSE | 4113 | 103 | 30 | -69.69 | 2.92 | 29.86 |
| `edge_trend_01_4h:BASE` | 4h | BASE | 4113 | 103 | 31 | -44.31 | 2.78 | 28.57 |

Every fill in that table is hypothetical (no order was sent, no capital moved). The metrics are a reading of what the frozen rules printed on the new bars, not a claim about the future and not an admission criterion.

## Refusal funnel (primary arm)

| refusal | count |
| --- | ---: |
| `candidate:trend_filter_fail` | 86 |

## Risk parity with the runtime engine

Verdict: **PARITY_PASS** over 544 classified comparison(s) `AGREE_APPROVED` 79, `AGREE_REFUSED_SAME_RULE` 155, `RESEARCH_ONLY_REFUSAL` 9, `RULE_NOT_MODELLED_BY_RESEARCH` 72, `RULE_ORDER_DIFFERS` 194, `SIZING_ROUNDING_ONLY` 35.

## Limitations

- The forward window is short by construction. Nothing here is a profitability claim.
- The intraday arms read BTC's 1h series as context, exactly as the frozen campaign did, extended with the forward 1h bars so the context covers the window.
- The shadow runs the arm's declared execution (market, or resting limit for the `_limit` arm). It never sends an order and it never contacts a private endpoint.
- Risk parity compares two engines on identical inputs; it says nothing about which limits are *right*, only about whether the two implementations agree.
