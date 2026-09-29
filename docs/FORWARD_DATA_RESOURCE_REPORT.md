# FORWARD DATA RESOURCE REPORT — `forward-1790610007-9d07f3df`

Machine-readable companion: [`FORWARD_DATA_RESOURCE_REPORT.json`](FORWARD_DATA_RESOURCE_REPORT.json).
Measured stream of every analysis path: [`FORWARD_DATA_STREAMING_MEMORY.json`](FORWARD_DATA_STREAMING_MEMORY.json).
Disk-guard test evidence: [`FORWARD_DATA_DISK_GUARD.json`](FORWARD_DATA_DISK_GUARD.json).

This report answers two separate questions and keeps them apart: what one hour of
forward capture costs (that is measured on the official run), and whether the
machine can run it continuously (that is capacity arithmetic, and here the answer
is no).

## 1. Footprint of the capture

| Quantity | Value |
| --- | --- |
| Segments | 78 `.jsonl.gz`, all sealed, 0 partial tails |
| Stored bytes | 376,477,867 (0.376 GB) |
| Raw-equivalent bytes | 6,593,584,165 (6.594 GB) |
| **Compression ratio** | **17.514×** |
| **RAW_EQUIVALENT_GB_H** | **6.274** |
| **COMPRESSED_GB_H** | **0.358** |
| **ESTIMATED_COMPRESSED_GB_DAY** | **8.598** |
| Duration | 3783.341 s (63.06 min) |

Measured from the files on disk (decompressed vs stored), not assumed from an
earlier smoke test. The 17.5× ratio comes from the payload's own redundancy: the
same price levels restated across depths and book tickers.

Raw data is never deleted in this phase. There is no retention policy that would
let a continuous run drop anything, which is deliberate: the phase's job is to
prove capture integrity, not to manage a data lake.

## 2. Disk capacity

| Quantity | Value |
| --- | --- |
| Free disk now | 6,603,862,016 bytes (6.604 GB) |
| Free disk at capture start | 6,980,339,883 bytes (6.980 GB) — **reconstruction** |
| Reconstruction basis | free-now plus the bytes this capture wrote |
| Capacity at the observed rate | **18.435 hours = 0.768 days** |
| Verdict | **`STORAGE_CAPACITY_BLOCKER`** |

Honesty note carried in the artifact: free disk was **not** sampled at capture
time, so the start figure is a reconstruction from bytes written and is labelled
as one rather than presented as a measurement. The host sits at ~97.5% disk
utilisation.

At the observed compressed rate the available volume holds **under a day** of
this capture. `STORAGE_CAPACITY_BLOCKER` therefore applies, and
`READY_FOR_CONTINUOUS_COLLECTION` is reported as **FALSE**. A 24/7 claim on this
volume would be false within a day, so it is not made.

## 3. Disk-guard test — controlled, and it behaves

The guard was exercised in a throwaway root; the real volume was never filled.
Two variants were run, because a guard that only works when the process is about
to exit anyway is not a guard.

| Variant | Setup | Result |
| --- | --- | --- |
| unbounded duration | `--max-total-bytes 200000`, no `--duration` | trip → intake halted → writer flushed → segment sealed → manifest finalised → clean exit (code 0) |
| bounded duration | same budget, `--duration 90` | trip at 2.75× budget (275,897 vs 200,000 bytes) while the process stayed alive | 

Both exited 0 with a finalised manifest, `CONTINUOUS_DATA` continuity and no
partial tail. In the bounded variant the socket receive loops poll the same stop
flag and stopped writing **26 ms** after the trip instant, so holding the process
open costs nothing further. The recorded recommendation is nevertheless to run the
continuous invocation **without** `--duration`: there is no reason to keep a
process alive after its own guard has fired.

Overshoot of 76,127 bytes above the 200,000-byte budget is expected and safe:
rotation and flush check the budget between segments, so the limit is a threshold
rather than a hard byte ceiling. With a 1.2 GB production budget the equivalent
margin is immaterial, and the important property — no unbounded write after the
trip — is the one measured.

## 4. What the capture itself cost

Sampled 59 times across the run by the collector's own sampler:

| Quantity | Value |
| --- | --- |
| CPU | 2832.4 s of CPU for 3783.4 s wall = **74.9% of one core** |
| Memory peak | **281.6 MB** (final sample was also the maximum) |
| Network decoded | 1,293,448,253 bytes = 1.231 GB/h |
| Disk written | 376,480,457 bytes |

About three quarters of one core to sustain ~1,480–1,966 events/s is consistent
with a single-threaded asyncio collector and leaves the remaining cores free.

## 5. Open P1 — writer state that grows with the capture

**This is a real, quantified defect and it is not fixed in this phase.**

`StreamStats.network_delays` (`src/trading_bot/research/forward/storage.py`) is a
`list[int]` to which `StreamStats.observe()` appends once per event that carries a
network delay. It is **never read**: no `as_dict()`, no manifest field, no report
touches it. It is dead state that nevertheless costs memory for the whole run.

Evidence:

* On the official run 3,805,824 of 5,481,951 rows carried a delay, so the list
  grew by ~3.8 million entries in 63 minutes.
* The writer's own sampling ended the capture at its **maximum** memory
  (281.6 MB final == 281.6 MB max; heartbeat series p95 263.4 MB), the signature
  of a monotonic per-event growth rather than a working set.
* A controlled measurement of the append alone (tracemalloc, 200,000 appended
  ints) puts the retained cost at ≥8.1 bytes/event, i.e. **≥44.5 MB/h ≈ ≥1.07 GB/day**
  at the observed event rate. The measured end-to-end gap above the bounded
  analysis baseline is larger, so 1.07 GB/day is a floor.

Why it is not fixed here: `storage.py` is one of the five paths in
`WRITER_PATHS`, and this phase certifies that the code that produced the capture
equals the code at the final HEAD (`CAPTURE_CODE_EQUIVALENT`). Editing
`StreamStats` would break that equality, and the capture cannot be re-run to
restore it without discarding the certified hour. The fix is small — replace the
list with a bounded histogram, or delete the field — but it belongs in the next
collection-generation commit, together with a short certification capture.

Consequence: this is the **second** blocker to continuous collection (the first is
disk capacity). It does not affect the validity of the hour that was captured: the
data is on disk and verifies; only the process's long-run footprint is affected.

## 6. Cost of analysing the capture (the P1 that *is* closed)

The original P1 was that the analysis path materialised the whole run, so
describing a forward hour required tens of gigabytes. Every path that touches the
dataset now streams, and streaming is measured rather than asserted:
[`FORWARD_DATA_STREAMING_MEMORY.json`](FORWARD_DATA_STREAMING_MEMORY.json) samples
the resident set every 0.25 s around each path over the real 5,481,951-row
capture and compares the worst growth against what holding the rows would cost.

Paths measured over the real capture, resident set sampled every 0.25 s:

| Path | Rows | Elapsed | RSS baseline | RSS peak | Growth |
| --- | --- | --- | --- | --- | --- |
| `replay` | 5,481,951 | 243.1 s | 103.3 MB | 123.3 MB | **+20.0 MB** |
| `aggregation` | 5,481,951 | 1328.5 s | 117.5 MB | 160.2 MB | **+42.6 MB** |
| `quality` | 5,481,951 | 273.8 s | 159.5 MB | 185.7 MB | **+26.2 MB** |
| `daily` | 5,481,951 | 256.6 s | 169.7 MB | 188.6 MB | **+18.9 MB** |
| `verifier` | 5,481,951 | 279.1 s | 181.9 MB | 206.8 MB | **+24.9 MB** |

* Worst growth across every path: **42.6 MB**.
* Materialised equivalent (deep size of one row, 20,004 bytes, × 5,481,951 rows):
  **109,660.9 MB ≈ 109.7 GB**.
* Ratio of worst growth to the materialised equivalent: **0.000389** — the growth
  is 0.04% of what holding the rows would cost.

`bounded = true`. Memory is a function of streams and intervals, not of row count,
which is the property the original P1 needed. The bar the benchmark uses is
deliberately loose (64 MB or 10% of the materialised equivalent, whichever is
larger) so that it separates *constant* from *proportional* rather than passing on
a threshold tuned to one capture; 42.6 MB against a 10,966 MB allowance is not
near the bar.

Regressions are locked by
`test_row_streaming_matches_a_materialised_load` and
`test_the_quality_report_is_produced_from_one_streaming_pass`, and the report
writer no longer rebuilds a section a caller already built (that alone was two
extra full scans per report).

## 7. Coexistence with the PAPER runtime

`docs/FORWARD_DATA_PAPER_COEXISTENCE.json` — the same PAPER smoke (6 cycles × 20 s,
BTC/ETH/SOL, 5m, real-data config) executed twice: once with the forward capture
live, once with nothing collecting.

| Quantity | With collector | Without collector | Delta |
| --- | --- | --- | --- |
| Decision cycles | 18 | 18 | 0 |
| Traces persisted | 18 | 18 | 0 |
| Orders created | 0 | 0 | 0 |
| Runtime failures | 0 | 0 | 0 |
| Cycle wall time | 21.992 s | 22.520 s | **−0.528 s** |
| Collector events during | 253,119 | — | — |

* Separate processes, no shared mutable state, and the collector can change no
  decision (enforced structurally: the forward package imports no trading-runtime
  module, checked by test).
* Collector reconnects during the smoke: 6 — the paper runtime continued through
  all of them.
* Decision-cycle impact: **none measurable**. The 0.53 s difference is noise in
  the PAPER cycle itself, and it is in the *faster* direction.
* CPU/RAM were **not** co-sampled per process during the smoke; the collector's
  own cost is the standalone figure in §4 (74.9% of one core, 281.6 MB peak).
  Both are separate processes, so the impact on PAPER is host resource
  contention, not interference.
* `risk_APPROVED` differed between arms (10 vs 18). That is PAPER reading live
  market data at different moments, not collector interference: the arms ran at
  different times, the collector touches no PAPER state, and no order was created
  in either arm. `NO_TRADE` remains a valid outcome; this smoke measures
  non-interference, not whether PAPER trades.

Impact classification: **NO_MATERIAL_IMPACT** on the decision path (measured), with
the CPU/RAM co-sampling noted as not performed rather than implied.

## 8. What continuous collection would need

Ordered by immediacy:

1. **Disk.** 8.6 GB/day compressed against ~6.6 GB free. Either a larger volume,
   or an explicit raw-short / aggregate-long retention policy, before any 24/7
   run. This is why `READY_FOR_CONTINUOUS_COLLECTION = FALSE`.
2. **The writer dead state** in §5, before the process runs for days.
3. A decision on futures coverage: the futures trade and mark-price streams do not
   arrive in this environment, so a futures microstructure programme needs either
   a different venue or a REST-sampled substitute, documented as different data.
