# FORWARD DATA QUALITY REPORT — `forward-1790610007-9d07f3df`

Machine-readable companion: [`FORWARD_DATA_QUALITY_REPORT.json`](FORWARD_DATA_QUALITY_REPORT.json).
Raw evidence: `reports/microstructure-forward/`.

This document describes **one** capture — the official 60-minute forward run of
2026-09-28 — and says only what that capture's own bytes support. It is a
data-quality record, not a result: no strategy, admission or edge claim appears
here, and none can be made from one hour.

Authority: RESEARCH_ONLY. The collector is a read-only public-market-data writer
(§3, §4) and never enters the trading decision path; `docs/runtime_authority_map.md`
records that boundary and a unit test enforces it by import graph.

---

## 1. Capture identity

| Field | Value |
| --- | --- |
| Run id | `forward-1790610007-9d07f3df` |
| Runtime commit | `7fb9429e765dbf0d520e6a58df3dabacc05dbbde` |
| Started (UTC) | 2026-09-28T15:40:07.810 |
| Ended (UTC) | 2026-09-28T16:43:11.151 |
| Duration | **3783.341 s = 63.06 min** (target 3600 s) |
| Continuity | `INCOMPLETE_DATA` (declared holes; see §6–§7) |
| Provider | Binance — `https://api.binance.com` (spot), `https://fapi.binance.com` (perp) |
| Markets / assets | spot, perp / BTCUSDT, ETHUSDT, SOLUSDT |
| Collector / contract / schema | `FORWARD-WS-COLLECTOR-V1` / `FORWARD-DATA-CONTRACT-V1` / `forward-event-v1` |
| Segments | 78 `.jsonl.gz`, all sealed, **0 partial tails** |
| Rows | 5,481,951 |
| Bytes on disk | 376,477,867 (0.376 GB) |

The capture was not stopped, restarted or edited: `reports/microstructure-forward/writer_code_equivalence.json`
records the mechanical comparison of the code at the capture commit against the
final HEAD (§24), and the independent verifier re-runs that comparison.

---

## 2. Streams, transports and volume

| Stream | Transport | Events (spot / perp) | Lossless/stream |
| --- | --- | --- | --- |
| `book_ticker` | WebSocket | 5,194,953 (1,659,064 / 3,535,889) | yes |
| `depth_diff` | WebSocket | 160,219 (93,649 / 66,570) | yes |
| `agg_trade` | WebSocket | 124,232 (124,232 / 0) | yes |
| `book_checkpoint` | WebSocket (writer) | 708 (354 / 354) | state sample |
| `depth_snapshot` | REST (reconcile/resnapshot) | 254 (21 / 233) | no |
| `open_interest` | REST poll | 174 (0 / 174) | no |
| `funding` | REST poll | 174 (0 / 174) | no |
| `mark_price` | REST poll | 174 (0 / 174) | no |

Plus the run's own bookkeeping rows, written as ordinary contract rows so the
capture is self-describing: 58 `heartbeat`, 166 `lifecycle`, 839 `gap`.

The 254 `depth_snapshot` rows are exactly the 254 resnapshots: reconciliation and
resynchronisation are visible in the data rather than implied by a counter.

Total: **5,481,951** rows, **0** malformed, **0** clock violations,
`max_clock_skew_ms` 0.

One feed property that would otherwise be discovered by a user later is reported
rather than smoothed over: `spot/*/book_ticker` carries **no exchange event time**
in the venue's payload (1,659,064 rows, `event_time_coverage = 0.0`), which is why
latency is reported per stream instead of as one number.

## 3. Provider capability matrix (§7)

Measured on this run, in this environment — not read from documentation:

| Capability | Verdict | Evidence |
| --- | --- | --- |
| spot `aggTrade` / `depth` / `bookTicker` | **AVAILABLE** | 124,232 / 93,649 / 1,659,064 rows |
| perp `bookTicker` / `depth` | **AVAILABLE** | 3,535,889 / 66,570 rows |
| perp `aggTrade` | **UNAVAILABLE_IN_CURRENT_ENVIRONMENT** | 0 rows in 63 min at `perp/*/agg_trade` |
| perp `markPrice` (WS) | **UNAVAILABLE_IN_CURRENT_ENVIRONMENT** | 0 rows over WebSocket |
| perp `markPrice` (REST) | **ALTERNATIVE_SOURCE_AVAILABLE** | 174 rows via `rest_poll` |
| perp `openInterest` / `funding` | **ALTERNATIVE_SOURCE_AVAILABLE** | 174 rows each via `rest_poll`, sampled, not event time |
| perp klines as mark/index proxy | **ALTERNATIVE_SOURCE_AVAILABLE** | documented in `docs/source_registry.md` |

The futures endpoint of this venue closed sockets repeatedly and did not deliver
futures trade or mark-price streams, while delivering futures depth and book
ticker normally. That is recorded as an observed capability of the environment.
It does **not** invalidate spot collection: spot streams are complete, lossless
and externally cross-checked (§9), and futures book data is present. It does mean
this hour cannot support any futures-trade microstructure question, and no
coverage for those streams is claimed anywhere in the artifacts.

## 4. Duplicates, ordering and de-duplication

| Quantity | Value | Meaning |
| --- | --- | --- |
| Duplicate id observations | 554 | a repeated aggregate-trade or update id was seen |
| **Duplicate rows persisted** | **0** | nothing was written twice |
| Out-of-order ids | 645 | observed out of order; the stream's own id chain was restored |
| Sequence gaps detected | 74 | per-stream id-chain breaks |

De-duplication is applied at the ingest boundary, before the row reaches the
segment writer, so the dataset contains one row per logical event. 554 duplicate
observations produced **zero** duplicate rows: the count is reported as an
observation about the feed, not as residue in the data.

## 5. Gap lifecycle

Every hole is a first-class record with `gap_id`, asset, stream, cause, window,
expected id/event span, recovered count, remaining missing, status, transport and
a human-readable `detail`. Nothing is hidden behind de-duplication or smoothing.

Reason × status over the whole run:

| Reason | RECOVERED_COMPLETE | RECOVERED_PARTIAL | UNRECOVERABLE | Total |
| --- | --- | --- | --- | --- |
| `AGG_TRADE_ID_JUMP` | 18 | 0 | 0 | 18 |
| `DEPTH_SEQUENCE_BREAK` | 0 | 0 | 56 | 56 |
| `WS_DISCONNECT` | 18 | 0 | 711 | 729 |
| **Total** | **36** | **0** | **767** | **803** |

* `gaps_accounted` 767 + `gaps_empty_window` 243 = 803, and
  `gaps_accounting_is_complete = true`: every hole is either recovered, carries
  loss, or is a zero-length window that had nothing in it.
* **Every aggregate-trade hole was closed.** All 18 `AGG_TRADE_ID_JUMP` gaps
  reached `RECOVERED_COMPLETE` through the public REST trade index, so the
  lossless trade stream has **no remaining hole** in this capture.
* 243 gaps cover an empty window: they name ids that had no time in which to
  arrive. They are counted, not silently dropped.
* 524 gaps carry real loss. Total wall-clock time in which no stream delivered
  anything is **1.755 s** across 63.06 min (0.047% of the capture).

### REST backfill and its boundary

| Quantity | Value |
| --- | --- |
| Backfilled events persisted | 15,969 |
| Gaps closed by backfill | 36 |
| Backfill partial | 0 |
| Backfill failures | 0 |
| Backfill deferred | 0 |

Backfill is labelled, never disguised: recovered rows keep their stream identity
and carry `detail.origin = REST_RECOVERED_EVENT`, while live rows carry
`LIVE_WS_EVENT`. Latency statistics described as latency cover live rows only;
recovered rows are counted as recovered volume instead of being reported as
delivery latency.

A page fetched from the backfill index must not itself schedule another walk of
that index; the guard is exercised by
`test_a_hole_inside_a_recovered_page_never_restarts_recovery` and re-probed
independently by the verifier.

### Loss accounting, and what the estimate can mean

`estimated_lost_events` is the writer's arithmetic over the id space it held. It
is a count for aggregate trades (one id is one trade) and it is a **sequence
span** for depth updates (an update id is a position, not an event). This run
therefore reports the two quantities separately rather than summing them:

| Quantity | Value |
| --- | --- |
| Id steps that are an event count (`agg_trade`) | 0 — all recovered |
| Id steps that are a sequence span only (`depth_diff`) | 159,109,856 |
| Lost wall-clock seconds (physical) | 1.755 |

Quoting 159,109,856 as missing events would describe more loss than the capture
contains rows. The physical loss is the 1.755 s, and a broken depth chain is
resolved by invalidation plus resnapshot (§18 of the run rules), not by
attributing counts to it.

## 6. Health accounting

Derived read-side from the same gap and lifecycle rows the writer persisted, so
it cannot be inflated by the writer's own opinion of itself.

| State | Seconds | Share |
| --- | --- | --- |
| HEALTHY | 3636.691 | 96.12% |
| DEGRADED | 146.650 | 3.88% |
| FAILED | 0.0 | 0.0% |

* 132 degraded episodes, **132 returned to HEALTHY** (100%).
* Longest single degraded episode: 3252 ms.
* 48 episodes cost permanent loss, 6 partial loss, 76 no data loss.
* 56 loss events have zero wall-clock length; they are counted as instantaneous
  loss rather than as healthy time.
* Collector's own sticky timeline is reported separately in the JSON
  (`health.collector_state`): it entered DEGRADED once and never left, because
  the last reconnect was still unresolved when the clock ran out. The read-side
  accounting above is the one used for percentages, and the reason is stated in
  the artifact.

Classification rule, demonstrated by tests: a recoverable disconnect is
**DEGRADED** and returns to HEALTHY after reconnect + reconcile/backfill; only an
unrecoverable hole, book corruption, storage failure or a timestamp-invariant
violation produces **FAILED**. This run produced none of the latter.

Disconnects 81, reconnects 81, resnapshots 254 (0 failed).

## 7. Order-book validation

| Book | Checkpoints | HEALTHY | STALE | RECOVERING | INVALID | Usable ratio |
| --- | --- | --- | --- | --- | --- | --- |
| `perp/BTCUSDT` | 118 | 114 | 2 | 2 | 0 | 96.61% |
| `perp/ETHUSDT` | 118 | 111 | 3 | 3 | 1 | 94.07% |
| `perp/SOLUSDT` | 118 | 110 | 3 | 4 | 1 | 93.22% |
| spot books | 118 each | see JSON | — | — | — | ≥93% |

* Crossed books recorded: **0**.
* Snapshot mismatches: **1** (perp ETHUSDT) — a resnapshot whose sequence did not
  bridge the live buffer; the book was invalidated and resnapshotted again.
* Per-book update counters: ~22,200 applied updates, 14 depth-chain gaps, 76
  resnapshots per perp symbol.
* Post-reconnect behaviour is the re-synchronisation path working: buffer the
  diffs, discard the stale book, take a fresh REST snapshot, align the snapshot
  id to the buffered diffs, then resume; 254 resnapshots with 0 failures and 0
  crossed books is the evidence.
* Final states are STALE for every book because the capture stopped seconds after
  the last websocket close. This is a property of the last seconds, not of the
  hour: 110–114 of 118 checkpoints per book were HEALTHY. Both numbers are
  reported, and readiness uses the checkpoint tally.

## 8. Delivery latency (live rows only)

| Stream family | p50 | p95 | p99 |
| --- | --- | --- | --- |
| spot `agg_trade` | 0.42 s | 7.7 s | 69.1 s |
| spot `depth_diff` | 0.07 s | 7.4 s | 69.1 s |
| spot `book_checkpoint` | 0.22 s | 47.5 s | 75.8 s |
| perp `book_ticker` | 3.8 s | 32.2 s | 62.2 s |
| perp `depth_diff` | 2.8 s | 34.4 s | 61.8 s |
| perp `depth_snapshot` (REST) | 0.05 s | 0.13 s | 0.17 s |
| perp `funding` / `mark_price` (REST) | 0.6 s | 1.0 s | 1.1 s |
| overall (3,805,824 rows) | 3.435 s | 32.011 s | 62.308 s |

This is a finding, not a footnote. The multi-second overall figure is
**structural to the markets, not a clock offset**: futures REST responses served
through the same local clock land in 50–600 ms, and spot websocket streams land
in 74–424 ms, so the host clock is not skewed by seconds. The futures websocket
feed in this environment is simply delivered with a p50 of ~3.4 s and a p95 of
~32 s. Consequences, stated rather than discovered later by a user of this data:

* this hour supports **sequence and level reconstruction** on both markets;
* it supports **sub-second latency work on spot only**;
* it does **not** support sub-second latency claims on perp, and any perp
  microstructure question must be asked at a horizon above the p95.
* the p95/p99 tails line up with the reconnect episodes, so they are an outage
  signature, not steady-state jitter.

## 9. External cross-check

75 completed minutes of captured `aggTrade` quantity were compared against the
venue's own public 1-minute kline volume for the same minutes
(`docs/FORWARD_DATA_KLINE_CROSSCHECK.json`): **median ratio 1.0, worst deviation
0.0, 0 buckets excluded**. The persisted trades are the venue's trades for those
minutes. This is a data-quality check only; it carries no information about edge.

Internal exactness against replay is a separate, stronger comparison and lives in
[`FORWARD_DATA_REPLAY_VALIDATION.md`](FORWARD_DATA_REPLAY_VALIDATION.md).

## 10. Storage

| Quantity | Value |
| --- | --- |
| Raw-equivalent | 6,593,584,165 bytes = 6.274 GB/h |
| Compressed on disk | 376,477,867 bytes = 0.358 GB/h |
| Compression ratio | **17.514×** |
| Estimated compressed | **8.598 GB/day** |

Details, capacity math and the disk-guard test: [`FORWARD_DATA_RESOURCE_REPORT.md`](FORWARD_DATA_RESOURCE_REPORT.md).

## 11. Readiness — infrastructure vs sample

Kept apart deliberately: infrastructure capability is not statistical sample, and
one hour is not a history.

| Gate | Infrastructure | Phase readiness | Blocking |
| --- | --- | --- | --- |
| M-03 order-book imbalance | ready — 160,219 book updates, 708 checkpoints, every book HEALTHY at 93–97% of checkpoints | `TECHNICALLY_READY_NEEDS_HISTORY` | 56 depth-chain gaps in this hour; 63.1 min vs the 24 h minimum |
| M-07 open interest × price | ready — OI/funding/mark sampled continuously from REST | `TECHNICALLY_READY_NEEDS_HISTORY` | forward OI spans 0.06 day vs the multi-day DEV/VAL/OOS split |

**No admission run was performed on this hour and none should be**: 63 minutes
cannot separate a microstructure effect from its own noise, and the earlier
`MICROSTRUCTURE_NO_EDGE_FOUND` result is unchanged by this data.

## 12. Limitations of this hour (stated, not hidden)

1. Futures trade and mark-price websocket streams delivered nothing in this
   environment (§3). Futures-trade microstructure questions are out of scope for
   this capture.
2. 1.755 s of wall-clock delivery was lost across 63 min, in 524 holes, all
   recorded with ids and windows.
3. Perp delivery latency p50 ≈ 3.4 s (§8) rules out sub-second perp work on this
   data.
4. Spot book ticker carries no exchange event time; it is sequenced by receive
   time and flagged (`event_time_coverage = 0.0`).
5. The writer's sampled memory grew monotonically to its maximum by the last
   sample (281.6 MB peak). The cause is identified and quantified
   (`network_delays` is appended per event and never read); it is recorded as an
   **open P1** in the resource report because fixing it would change the writer
   that produced this capture and invalidate the capture-code equality this phase
   certifies. It bounds continuous collection and is a blocker for 24/7 until
   fixed.
