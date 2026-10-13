# EDGE-03 forward observation — cumulative

Run `FWD-EDGE03-20261013T053048Z` at 2026-10-13T05:31:12Z; market instant 2026-10-13T05:30:48Z.

**OBSERVATION_AVAILABLE** — 226 independent observation day(s) accumulated; the lane still promotes nothing (the forward pipeline does not read an admission criterion)

Promotion: **NONE**. Risk parity: **PARITY_PASS**.

## What was observed

| series | bars | first bar (UTC) | last bar (UTC) | observation days | gaps | duplicates |
| --- | ---: | --- | --- | ---: | ---: | ---: |
| `15m:BTC` | 551 | 2026-10-07T11:45:00Z | 2026-10-13T05:15:00Z | 5 | 0 | 0 |
| `15m:ETH` | 551 | 2026-10-07T11:45:00Z | 2026-10-13T05:15:00Z | 5 | 0 | 0 |
| `15m:SOL` | 551 | 2026-10-07T11:45:00Z | 2026-10-13T05:15:00Z | 5 | 0 | 0 |
| `1h:BTC` | 5429 | 2026-03-01T00:00:00Z | 2026-10-13T04:00:00Z | 226 | 0 | 0 |
| `1h:ETH` | 5429 | 2026-03-01T00:00:00Z | 2026-10-13T04:00:00Z | 226 | 0 | 0 |
| `1h:SOL` | 5429 | 2026-03-01T00:00:00Z | 2026-10-13T04:00:00Z | 226 | 0 | 0 |

Total independent observation days (densest 1h series): **226** of a declared floor of 60.

## Ingest ledger

Observation pass: **6** series attempted; outcomes: `ingested` 3, `no_new_data` 3.

Ledger rows on file: **60** (6 from the observation pass, 54 from the restart pass at the same instant).

## Ingestion latency of the bars this run pulled (bar close → store)

| series | bars pulled | min s | median s | max s |
| --- | ---: | ---: | ---: | ---: |
| `15m:BTC` | 1 | 49 | 49 | 49 |
| `15m:ETH` | 1 | 49 | 49 | 49 |
| `15m:SOL` | 1 | 49 | 49 | 49 |

These are the bars stamped with this run's fetch instant — the lag a scheduled reader meets, measured from each bar's close to the moment it reached the store.

## Window latency over every stored bar (backfill included)

| series | samples | fetches | min s | median s | max s |
| --- | ---: | ---: | ---: | ---: | ---: |
| `15m:BTC` | 551 | 4 | 49 | 226,491 | 473,991 |
| `15m:ETH` | 551 | 4 | 49 | 226,491 | 473,991 |
| `15m:SOL` | 551 | 4 | 49 | 226,491 | 473,991 |
| `1h:BTC` | 5429 | 2 | 53 | 9,751,191 | 19,521,591 |
| `1h:ETH` | 5429 | 2 | 53 | 9,751,191 | 19,521,591 |
| `1h:SOL` | 5429 | 2 | 53 | 9,751,191 | 19,521,591 |

The first run fetched the whole window in one pass, so this table is the **backfill** distance (each bar's close to that run's instant), not a property of the feed. The table above is the one that answers "how fresh is the store".

## Restart and duplicate proof

- A second ingest at the same instant produced `['no_new_data']` for every series and appended **0** bar(s).
- Store digests identical before and after the second run: **yes**.
- Duplicate timestamps anywhere in the store: **0**.
- Duplicate (asset, instant, reason) refusals in the primary arm: **0**.

## Frozen rulesets, read forward

| arm | timeframe | scenario | window bars | signals | hypothetical fills | net USDT | max DD % | exposure % |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `edge_intra_01:2X_FEES` | 15m | 2X_FEES | 1653 | 0 | 0 | 0 | 0.00 | 0.00 |
| `edge_intra_01:ADVERSE` | 15m | ADVERSE | 1653 | 0 | 0 | 0 | 0.00 | 0.00 |
| `edge_intra_01:BASE` | 15m | BASE | 1653 | 0 | 0 | 0 | 0.00 | 0.00 |
| `edge_intra_01r_limit:BASE` | 15m | BASE | 1653 | 0 | 0 | 0 | 0.00 | 0.00 |
| `edge_intra_01r_market:2X_FEES` | 15m | 2X_FEES | 1653 | 0 | 0 | 0 | 0.00 | 0.00 |
| `edge_intra_01r_market:ADVERSE` | 15m | ADVERSE | 1653 | 0 | 0 | 0 | 0.00 | 0.00 |
| `edge_intra_01r_market:BASE` | 15m | BASE | 1653 | 0 | 0 | 0 | 0.00 | 0.00 |
| `edge_intra_02:2X_FEES` | 15m | 2X_FEES | 1653 | 0 | 0 | 0 | 0.00 | 0.00 |
| `edge_intra_02:ADVERSE` | 15m | ADVERSE | 1653 | 0 | 0 | 0 | 0.00 | 0.00 |
| `edge_intra_02:BASE` | 15m | BASE | 1653 | 0 | 0 | 0 | 0.00 | 0.00 |
| `edge_trend_01_1d:2X_FEES` | 1d | 2X_FEES | 678 | 5 | 3 | -56.01 | 0.67 | 8.70 |
| `edge_trend_01_1d:ADVERSE` | 1d | ADVERSE | 678 | 5 | 3 | -56.23 | 0.67 | 8.70 |
| `edge_trend_01_1d:BASE` | 1d | BASE | 678 | 5 | 3 | -54.66 | 0.66 | 8.70 |
| `edge_trend_01_4h:2X_FEES` | 4h | 2X_FEES | 4071 | 103 | 31 | -73.77 | 2.94 | 28.86 |
| `edge_trend_01_4h:ADVERSE` | 4h | ADVERSE | 4071 | 103 | 30 | -69.69 | 2.92 | 30.16 |
| `edge_trend_01_4h:BASE` | 4h | BASE | 4071 | 103 | 31 | -44.31 | 2.78 | 28.86 |

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
