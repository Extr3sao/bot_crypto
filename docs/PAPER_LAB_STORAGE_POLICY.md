# PAPER lab storage policy — tiers, preservation, data root

The research volume on this host is 238 GB and was at 100 % when this policy was
written. "Run continuously" is therefore a statement about the *policy*, not about
the disk: raw data is hot and bounded, derived data is small and kept, and nothing
is deleted until the thing that replaced it has been proven to exist **and** the
preregistered hypothesis has been proven measurable from it.

Everything below is implemented in
[retention.py](../src/trading_bot/research/forward/retention.py),
[preservation.py](../src/trading_bot/research/forward/preservation.py) and
[forward_retention.py](../scripts/forward_retention.py), and re-measured by
[paper_lab_verification.py](../scripts/paper_lab_verification.py).

## Tiers, and which of them are lossless

"Compressed" is not one thing. A tier that keeps every row and a tier that keeps a
per-minute mean are not interchangeable, so every tier is labelled.

| tier | layer | kind | resolution | retention | serves |
| --- | --- | --- | --- | --- | --- |
| TIER 0 | `segments/` | **LOSSLESS** | every event | `raw_hot_hours` behind the writer, then compacted | replay, M-03 at quote level, any hypothesis not yet preregistered |
| TIER 1 | `aggregated/` | **LOSSY** | 1 m buckets + 5/15/30 m roll-ups | indefinite (the long-term record) | M-03 at 1/5 m, M-07 at 5/15/30 m |
| TIER 2 | `lineage/` | **LOSSLESS** | one record per compacted window | indefinite | auditability of every deletion |
| TIER 3 | `reports/` | **LOSSY** | per run | indefinite | quality, readiness, capacity |

Measured, not assumed: on the head-certification capture the quote streams were
~70 % of written bytes (`book_ticker`) and ~27 % (`depth_diff`), while trades, open
interest and checkpoints together were under 2 %. Compaction of 37.21 MB of raw
segments produced 0.08 MB of aggregates (0.2 %), with lineage adding ~8 KB per
window. The expensive part of this capture is also the part that cannot be
regenerated.

## Preservation: the gate before any deletion

`apply_retention(..., preservation=PreservationPolicy())` re-derives the
hypothesis' feature series **twice** for every candidate window:

1. from the raw rows still on disk, with an implementation that does not call the
   aggregation module (agreement is evidence, not a shared bug);
2. from the compact artifact the retention pass just wrote.

They are then compared bucket by bucket. Expectations come from the
preregistration, not from taste: M-03 at 1/5 m over book checkpoints plus trade
flow, M-07 at 5/15/30 m with OI sampled at most every 120 s.

Verdicts:

* `PRESERVED_AT_PREREGISTERED_RESOLUTION` — deletion may proceed;
* `RAW_NOT_DELETABLE_FOR_M03` / `RAW_NOT_DELETABLE_FOR_M07` — the raw stays,
  the reason is written into `refused`, and the report names the mismatching
  feature, bucket and values;
* a window with nothing to compare refuses too: "no evidence" is not "no
  difference".

What is deliberately *not* preserved is named rather than implied:
`quote_level_spread_volatility` and `book_transition_count` need the raw quote
streams at every update, so they are listed as `not_covered_without_raw_quotes` in
every verdict. Asking for sub-minute M-03
(`--m03-min-resolution-minutes 0`) fails closed and keeps raw, because no compact
tier on this host can hold quote-level data for a week.

Every verdict is written to `preservation/<run-id>/<window>.json` next to the
lineage record it justifies, so a deletion can be audited years later without
rerunning anything.

## Capacity and the honest verdict

`CAPACITY_REPORT.json` (from [forward_storage_policy.py](../scripts/forward_storage_policy.py))
computes the steady state from the measured rate, the hot window and the reserve.
Policy `FORWARD-RETENTION-V1`: rotation 900 s, raw hot 2.0 h, reserve 384 MiB,
aggregates 0.751 MB/day, estimated operating days 285.5, verdict `VIABLE`.

Two things it does not hide:

* a probe at 6 h or more of hot raw returns `EXTERNAL_STORAGE_REQUIRED`;
* long-horizon *raw* retention (as opposed to long-horizon aggregates) is
  `EXTERNAL_STORAGE_REQUIRED` on this host, by arithmetic.

## Data root: moving the capture off this volume

Nothing requires the capture to write to the volume the code lives on.

```bash
# capture
python scripts/forward_collector.py --mode run --data-root D:/trading-capture ...
# retention (same root)
python scripts/forward_retention.py --data-root D:/trading-capture --run-id <id> ...
# whole lab
python scripts/start_paper_lab.py --data-root D:/trading-capture
```

`--data-root` is the root for segments, manifests, lineage, preservation records,
resume state and the stop file, so a moved capture keeps all of its audit trail in
one place and the stop file follows it. The lab plan records which root was used
(`configuration.forward_root`), and the dashboard shows it.

## Deleting less when you are unsure

```bash
# what would happen, touching nothing
python scripts/forward_retention.py --run-id <id> --dry-run

# compaction only: no deletion at all
python scripts/forward_retention.py --run-id <id> --delete-when-free-below 0

# delete only while the volume is genuinely short
python scripts/forward_retention.py --run-id <id> --delete-when-free-below 1500000000
```
