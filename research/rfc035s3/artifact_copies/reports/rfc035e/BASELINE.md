# RFC-035E — BASELINE

```text
RFC-035E  = INDEPENDENT_EXTERNAL_EFFECT_REPRODUCTION
COMMIT    = 7e21f7ca6dbf8816d83f2f8ab15aeb09310b878c (main)
RFC-036   = NOT_OPENED
RFC-041 FREEZE = ACTIVE (untouched)
```

## What was carried in

RFC-035 selected OPP-0001 with rank `REPLICATE_P0`, but its own record says the source defines no
entry, exit, threshold, lookback, aggregation or position size. That is a contract violation: the
RFC-035 minimum-evidence filter requires `REPLICABLE_ENTRY_EXIT_LOGIC`, and there is none to
replicate. The correction is applied in the RFC-035 artifacts (`PREVIOUS_CLASSIFICATION =
REPLICATE_P0` -> `CORRECTED_CLASSIFICATION = RESEARCH_HYPOTHESIS_P0`) and RFC-035 is **not** PASS.
Nothing previously recorded was erased.

This RFC then asks the only question that can be asked of a hypothesis: **does the external
statistical effect exist at all, on data reconstructed independently?**

## Data (real, fetched and hashed)

| id | provider | object | coverage |
| --- | --- | --- | --- |
| RF-01 | Farside Investors | daily US spot BTC ETF net flow table (US$m), 12 fund columns + Total | 2024-01-11 .. 2026-10-07, 703 sessions |
| RF-02 | Binance public REST | BTCUSDT 1d klines (UTC) | 1042 rows, no gaps in the join |

Raw bytes are stored under `data/rfc035e/raw/` with their SHA-256 in
`research/rfc035e/raw_source_manifest.json`; the derived daily table carries its own digest in
`data_manifest.json` / `dataset_hashes.json`. `scripts/rfc035e_fetch.py --offline` re-derives the
same dataset from the same bytes.

Sanity anchors: the first session (2024-01-11) shows +655.3 USD m, the cumulative net flow is
+57.9 USD bn, 17 sessions print exactly zero, and every session joins to a BTC close (0 nulls).

## Point-in-time status

The provider does not publish historical publication timestamps, so:

```text
PIT_STATUS = UNKNOWN
```

and no analysis assumes availability at market close. The strategy side (not used here) is given one
declared conservative rule, `available_to_strategy_at = flow_date + 1 day at 00:00Z`, with the
aggressive same-day rule recorded only for contrast. That is a convention, and it is labelled as one.

## Frozen specification

`reports/rfc035e/FALCONX_REPLICATION_SPEC.json` (spec digest embedded in every artifact) fixes the
windows, the three flow transforms, the return definitions, the VAR/impulse-response specification,
the significance threshold, the missing-data policy and the falsification battery **before** any
statistic was computed. The spec also states what is forbidden: entry/exit rules, thresholds, holding
periods, parameter search, any profitability claim.
