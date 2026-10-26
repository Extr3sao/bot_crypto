# FORWARD DATA REPLAY VALIDATION — `forward-1790610007-9d07f3df`

Machine-readable companion: [`FORWARD_DATA_REPLAY_VALIDATION.json`](FORWARD_DATA_REPLAY_VALIDATION.json).
Raw evidence: `reports/microstructure-forward/` (78 segments, 5,481,951 rows).
Reproduce with: `.venv/Scripts/python.exe scripts/forward_report.py --mode replay --offline --write-docs`.

This document reports what a **network-free replay of the finished capture**
proves about it, and what it does not. A dataset that cannot be rebuilt from its
own bytes is not evidence, so replay is the last check the capture has to pass
before the phase can be closed.

## 1. What replay is, and what it refuses to be

`replay_microstructure_dataset()` reads the sealed segments alone. It never opens
a socket — not REST, not WebSocket, not DNS — and the CLI that invokes it replaces
`socket.socket`, `socket.create_connection` and `socket.getaddrinfo` with raisers
for the duration of the run. `internet_access: false` in the artifact is therefore
a property of the process that produced it, not a promise written by hand.

Replay rebuilds the capture through the **same** `BookSyncer` the collector used,
with the book parameters taken from the manifest (`depth_n`, `stale_after_ms`) and
the sequence policy selected per market (spot `U`, futures `pu`). It then compares
what it reconstructed against what was persisted.

| Check | Result |
| --- | --- |
| Segments / rows | 78 / 5,481,951 |
| Rows replayed | 5,481,951 (exact, `event_count_match: true`, 0 differences) |
| Partial tails | 0 |
| Internet access | `false` (socket guard installed before any work) |
| Event count vs manifest | **EXACT** |
| Trade chain | **OK** — 0 violations (see §3) |
| Book checkpoints | **EXACT** — 708/708 matched (see §4) |
| Segment fingerprints | 78/78 recomputed from raw bytes and equal to the manifest |
| 1 m aggregation digest | `d14ef058e29279a6…` == the digest recorded at capture time |
| Feature match | `true` |
| Deterministic | `true` (a second independent pass reproduces digest, counters and books) |
| `ok` | **`true`** |

## 2. Why the previous run reported a failure, and what the defect was

An earlier pass of this same check reported `trade_sequence_ok: false` with
15,969 repaired rows and violations shaped like:

```text
spot/BTCUSDT: repaired aggTrade id 4075979775 is newer than the live stream (4075979774)
```

That message was produced by an invariant that compared a repaired row's id with
the highest **live** id seen so far *in write order*, and required the repair to
sit below it. The invariant was wrong, and the data was right.

Recovery has two shapes, and only one of them lands behind the live frontier:

* **hole behind the frontier** — the live stream jumps from `L` to `L'`; recovery
  walks `fromId = L + 1` and stops below `L'`. Those rows are written after the
  live row that revealed the jump, so write order is not id order.
* **socket outage** — the stream dies with no jump; recovery walks `fromId =
  last_known + 1` **forward to the head of the public index**, which is ahead of
  every live id persisted at that moment. The live rows for those ids arrive later
  and are suppressed by the collector's id window.

Requiring `repair_id < live_head_so_far` rejects the second shape, which is the
normal shape after a disconnect: this capture had 6 such episodes per spot symbol
(18 rows, 195–1,947 restored trades each), all recorded as `RECOVERED_COMPLETE`.

The invariant was restated in **id space** instead of write order (see §3). No
data was changed, re-written or re-captured to make the check pass: the capture
was completed at 18:43 and this replay ran afterwards against the same bytes.

## 3. The trade chain, verified in id space

For each `market/symbol`, replay tracks:

* `live_head` — the highest id the live stream delivered, which must be strictly
  increasing (a live row that regresses is still `not > previous`, i.e. corruption);
* `resolved_hi` — the highest id below which every id is *accounted for*: it was
  persisted, or it sits inside a tracked hole the live chain skipped and a repair
  may still fill;
* the set of open holes.

A repaired row is a violation only if it lands on an id that is already accounted
for and is not inside an open hole — that is a duplicate or a fabrication, and a
failed dedup. A repair that walks forward is the recovery path working.

| Symbol | Live rows | Repaired rows | `live_head` | `resolved_hi` | Unresolved holes | Violations |
| --- | --- | --- | --- | --- | --- | --- |
| `spot/BTCUSDT` | 53,199 | 8,272 | 4,076,035,325 | 4,076,035,325 | 0 | 0 |
| `spot/ETHUSDT` | 44,578 | 6,081 | 2,091,152,838 | 2,091,152,838 | 0 | 0 |
| `spot/SOLUSDT` | 10,486 | 1,616 | 675,665,605 | 675,665,605 | 0 | 0 |
| `perp/*` | 0 (`NO_DATA`) | 0 | — | — | 0 | 0 |

`resolved_hi == live_head` with **0 unresolved holes** for every symbol is the
stronger result: the persisted aggregate-trade ids form a **contiguous,
duplicate-free chain** from the first trade of the capture to the last. Every id
in that range appears exactly once, whether it arrived live or was restored from
the public index. That is §4's chain demonstrated on real market data:

```text
WS gap → REST recovery → persistence → later WS overlap → dedup → exactly one logical event
```

The overlap is not a claim: ids 103 in the fixture test, and the 15,969 repaired
rows here, are persisted once and the live duplicate is suppressed by the
collector's id window (per-stream `duplicates` counter in the manifest, and
`total_rows_on_disk` accounting in [`FORWARD_DATA_QUALITY_REPORT.md`](FORWARD_DATA_QUALITY_REPORT.md)).

## 4. Book reconstruction and exactness classification

Books are rebuilt by the same `BookSyncer` code path and compared field by field
against every persisted `book_checkpoint` (`last_update_id`, best bid/ask, mid,
spread bps, depth imbalance, microprice, best-level quantities, 10-level depth
notional, level counts, health label).

| Book | Checkpoints | Matched | Mismatches |
| --- | --- | --- | --- |
| `spot/BTCUSDT`, `spot/ETHUSDT`, `spot/SOLUSDT` | 118 each | 118 each | 0 |
| `perp/BTCUSDT`, `perp/ETHUSDT`, `perp/SOLUSDT` | 118 each | 118 each | 0 |

Exactness, classified as the phase requires — a `MISMATCH` cannot be hidden here,
because the artifact carries the mismatching rows themselves:

| Quantity | Classification | Basis |
| --- | --- | --- |
| Event count (42 streams) | **EXACT** | replayed counts equal manifest counts, 0 differences |
| aggTrade volume | **EXACT** | 1 m aggregation digest identical to the digest recorded at capture |
| Trade id range | **EXACT** | contiguous duplicate-free chain, `resolved_hi == live_head`, 0 holes |
| Best bid/ask checkpoints | **EXACT** | 708/708 field-by-field matches |
| Book depth checkpoints | **EXACT** | same comparison, 10-level depth included |
| 1 m aggregates | **EXACT** | `feature_match: true`, second pass identical |
| OI / funding / mark price series | **EXACT count** | 174 samples per perp symbol, 0 timestamp regressions |
| Latency / receipt timing | *not compared* | receive time is a host property, not reconstructible offline |

## 5. Cost of the replay, and its memory

Replay ran offline over the full capture: 78 segments, 5,481,951 rows, wall time
≈ 75 min on this host (two reconstruction passes, two aggregation passes, and the
fingerprint recomputation). It is **bounded-memory**, not proportional to the
dataset:

| Path | Rows | Elapsed | ΔRSS | Materialised equivalent |
| --- | --- | --- | --- | --- |
| replay | 5,481,951 | 243 s | +19.96 MB | 109,660.9 MB |
| aggregation | 5,481,951 | 1,328 s | +42.63 MB | 109,660.9 MB |
| quality report | 5,481,951 | 274 s | +26.19 MB | 109,660.9 MB |
| daily report | 5,481,951 | 257 s | +18.87 MB | 109,660.9 MB |
| independent verifier | 5,481,951 | 279 s | +24.86 MB | 109,660.9 MB |

Worst growth is 42.6 MB against a 109.7 GB materialised equivalent — ratio
**3.9 × 10⁻⁴**. The measurement method (RSS sampled every 0.25 s around each
path, rows counted by the path itself) is in
[`FORWARD_DATA_STREAMING_MEMORY.json`](FORWARD_DATA_STREAMING_MEMORY.json).

## 6. Standing limitations — not hidden by a PASS

* **One hour is not a research sample.** Nothing here says anything about edge,
  strategy quality, or admission. M-03 and M-07 remain `TECHNICALLY_READY_NEEDS_HISTORY`
  (see [`FORWARD_DATA_QUALITY_REPORT.md`](FORWARD_DATA_QUALITY_REPORT.md) §8).
* **Futures `aggTrade` and `markPrice` were never delivered by this environment.**
  `perp/*/agg_trade` is `NO_DATA` with 0 rows, so the `perp` rows of §3 are empty
  by absence of data, not by verification of data. What did arrive on the futures
  side (depth diffs, `bookTicker`, REST-polled OI/funding/mark price) is covered by
  the checks above.
* **The replay costs 75 minutes on this host.** It is a certification pass, not an
  interactive command; nothing in the live capture path depends on it.
* **Replay verifies the dataset, not the venue.** It proves the persisted bytes
  reconstruct into a self-consistent capture; it does not prove the venue told the
  truth, only that the record of it is intact and attributable.
* **The host has 1.9 GB free disk.** Collection can continue for roughly 5 hours
  at the observed rate, so `HOST_READY_FOR_LONG_TERM_24_7` is **false** unless
  retention or capacity changes — see
  [`FORWARD_DATA_RESOURCE_REPORT.md`](FORWARD_DATA_RESOURCE_REPORT.md).
