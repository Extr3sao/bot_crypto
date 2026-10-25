# PAPER DATA 24 H REPORT — `paper-lab-continuous-02`

**Phase:** PAPER-DATA-ACCUMULATION-V1 · **Mode:** PAPER / OFFLINE (read-only public data, no keys, no capital)
**HEAD start = end:** `929677c8034b72424c33930b59482b44350d7aa7` (branch `main`, tree clean)
**FALSE_SUCCESS:** 0

## FINAL STATUS

```text
PAPER_24H_DATA_FAILED
M03_RESEARCH_READY = FALSE
M07_RESEARCH_READY = FALSE
```

## 1. What happened

The campaign **did not reach 24 h of clean continuous data**. The collector ran **4.16 h**
(14 973 s) and then performed a **clean, self-initiated stop on its own disk budget**:

```json
{"status": "CONTROLLED_STOP", "stop_reason": "disk budget",
 "stopped_on_disk_budget": true, "exit_code": 0, "continuity": "INCOMPLETE_DATA",
 "max_total_bytes": 800000000, "bytes_written": 799632725}
```

The run was launched with `--collector-max-bytes 800000000` (the launcher default is
`1 100 000 000`). At the observed rate of **192 MB/h (≈ 4.62 GB/day)** the 800 MB valve fills in
**~4.2 h**, so 24 h was **mathematically impossible with this configuration**. This is a setup /
configuration defect, not a code defect: the guard did exactly what it was told, sealed all
segments, finalised the manifest and exited 0.

The supervisor correctly **did not restart it** — a controlled stop (`exit 0`) is not a crash.
PAPER kept running normally the whole time (isolation proven; see §6).

> The earlier expected state (`COLLECTOR: READY`) is **not** the real state at the moment of this
> verification. The real runtime state is `SYSTEM: DEGRADED` with `collector: STOPPED`.

## 2. Window and coverage

| | |
|---|---|
| Target | 24.0 h |
| System wall (launcher, run alive) | 21 321 s = **5.92 h** |
| Collector wall (usable) | 14 973 s = **4.16 h** |
| Coverage vs 24 h target | **17.33 %** |
| Coverage vs system wall | 70.25 % |
| Continuity flag | `INCOMPLETE_DATA` |

`4.16 h of data at 192 MB/h ≈ 0.80 GB.`

## 3. Host / sleep

`powercfg -a`: hibernation **not enabled**; only **S0 Modern Standby** is available (S1/S2/S3 are
unavailable on this host). No sleep was observed during the window — the collector reported
`clock_violations=0`, `max_clock_skew_ms=0`, and PAPER cycled at a steady ~60 s cadence with no gap.

**Residual risk to manage:** S0 Modern Standby is the only sleep state and can throttle background
work. Set the AC standby timeout to *Never* for the full campaign.

## 4. Paper runtime

| Metric | Value |
|---|---|
| Cycles | 337 |
| Asset evaluations / cycle | 2 (BTC, ETH) |
| Strategies evaluated / cycle | 12 |
| Decisions / cycle | 2 |
| **NO_TRADE / cycle** | **2 (`NO_TRADE_STRATEGIC`)** |
| **TRADES** | **0** |
| SHADOW | 0 |
| Risk vetoes | 0 |
| Runtime failures | 0 |
| PAPER_CANDIDATES | 0 |
| Open / closed positions | 0 / 0 |

`0 trades` with `0 PAPER_CANDIDATES` is the **correct** result, not a failure (§7).
Strategies: 24 total — `PAPER_ACTIVE=0`, `COST_KILLED=7`, `NO_GROSS_EDGE=17`; states unchanged.

## 5. Collector

| Metric | Value |
|---|---|
| Events (total) | 11 575 244 |
| aggTrades | 163 660 (spot BTC 91 391 + ETH 72 269; **perp 0 = known F4**) |
| depth_diff | 587 028 |
| book_ticker | 10 820 746 |
| book_checkpoint | 1 984 |
| **OI samples** | **488** (~1/min) |
| funding / mark_price | 488 / 488 |
| Reconnects | 9 |
| Resnapshots | 23 |
| Gaps (total) | 67 — **all UNRECOVERABLE** |
| Sequence gaps | 13 |
| Data-lost gaps | 13 (`data_lost_gap_seconds=0.0`) |

**Book quality:** 4 books; `crossed_book_events=0`; `invalidations=1`; `snapshot_mismatches=9`.
Spot books had **0 sequence gaps**; the sequence gaps are on perp `depth_diff` (BTC 6, ETH 7).
Final manifest state is `STALE` because the feeds stop at shutdown — not a live-quality verdict.

> **F3 (known, open, by design):** `remaining_missing_events` mixes depth update-id units into an
> "events" total; it is not an event-loss count and is not used as one here.

## 6. Isolation

The collector ceased at `03:08:51Z`; **PAPER kept cycling with 0 failures** through the end of
verification (`uptime 21 321 s > collector lifetime 14 973 s`). PAPER and the collector are
separate failure domains — the intended behaviour held.

## 7. Storage

| | |
|---|---|
| Raw generated | 0.800 GB (0.800 GB stored / 14.2 GB uncompressed, ratio 17.8×) |
| Compacted | 0.0 GB |
| Deleted | 0.0 GB |
| Free disk | 11.02 GB (`NORMAL`) |
| Deletion enabled | false (free disk stayed above the 3 GB delete threshold) |
| Estimated days at observed rate | ≈ 21.4 |

Retention compacted but **deleted nothing**; no required research data was removed. Raw is preserved.

## 8. Resources

CPU utilisation 35.1 %; memory max 303 MB (final 300.9 MB); 250 samples. No memory leak, disk
runaway or CPU runaway observed.

## 9. Supervisor

**0 restarts, 0 crash loops, 0 unexpected restarts.**

## 10. Pre-registered M-03 / M-07 readiness criteria (written before analysis)

**M-03 (order book / microstructure)** — all must hold over a ≥ 24 h window:
1. wall ≥ 24 h with **usable coverage ≥ 95 %**
2. **HEALTHY ≥ 90 %** of capture time; **INVALID ≤ 0.1 %**
3. sequence gaps losing data **== 0**; `crossed_book_events == 0`; unrecovered downtime ≤ 0.5 %
4. ≥ 24 h of `depth_diff` **and** `book_ticker` for BTC and ETH
5. offline replay **PASS** (100 % fingerprints, deterministic, `book_match`)
6. ≥ 3 non-overlapping segments for DEV/VAL/OOS

**M-07 (open interest + price)** — all must hold over a ≥ 24 h window:
1. OI sampled ≥ 1 per 60 s with ≤ 1 % missing for ≥ 24 h (≥ 1440/asset)
2. price/OI join coverage ≥ 95 % at 5/15/30 m
3. offline replay **PASS**
4. ≥ 3 non-overlapping segments for DEV/VAL/OOS

### Gate result

| | Coverage | Sample | Readiness |
|---|---|---|---|
| **M-03** | 17.33 % | 4.16 h depth/book_ticker (BTC+ETH) | **NOT_READY** |
| **M-07** | 17.33 % | 488 OI samples / 4.16 h (~1/min) | **NOT_READY** |

M-07's **cadence** already meets the bar (≈1/min); its blocker, like M-03's, is **history**, not
collection capability. 24 h is the minimum; it may still be insufficient for DEV/VAL/OOS.

## 11. §30 FALSE_SUCCESS audit

| Invalid-PASS condition | Occurred? |
|---|---|
| host slept | no |
| 24 h wall but much less usable data | yes — reported (17.3 %), **not** passed off as success |
| major gaps hidden | no |
| collector stopped silently | no — reported in heartbeat, status and this report |
| storage deleted required data | no |
| dashboard stale but claimed healthy | no |
| runtime changed during campaign | no (HEAD unchanged, tree clean) |
| 24 h data used to claim profitability | no |

## 12. Quality gate (§27)

Offline replay / fingerprint validation **PASSED** on the captured 4.16 h:

| Check | Result |
|---|---|
| `ok` | `true` |
| fingerprints | **411 / 411 matched**, 0 partial tails |
| `book_match` | `true` (4 books, 496/496 checkpoints each) |
| `deterministic` | `true` (second-pass digest == aggregation digest) |
| `internet_access` | `false` (fully offline) |
| event counts | manifest == replay (`event_count_match: true`) |
| `errors` | `[]` |

Artifact: `reports/microstructure-forward-continuous/reports/REPLAY_VERIFICATION.json`.
DecisionTrace / Outcome validation are not applicable to a 4.16 h all-`NO_TRADE` window.

### 12b. Recovery — fresh clean 24 h window (`paper-lab-continuous-03`)

On the operator's decision, window-1 was stopped and a **fresh, gap-free** window started
(2026-09-30 19:52 local):

- collector disk budget raised **800 MB → 7 GB** (`--collector-max-bytes 7000000000`); the run no
  longer trips its guard before 24 h (needs ~4.6 GB/day).
- host sleep prevented: `powercfg -change -standby-timeout-ac 0` (AC standby = Never, verified
  `0x0`).
- retention policy **unchanged** (raw-hot 0.25 h, delete-when-free-below 3 GB); no data deleted.
- run-03 came up **HEALTHY** — 4/4 children RUNNING, 0 restarts, collector events flowing, 0 gaps.

Window-1's lab verdict is **`FAILED`** because PAPER did not honor the graceful STOP within the
120 s grace and was force-terminated (exit 1); collector, retention and strategy-lab all exited 0.
That is a PAPER-stop-latency defect — real but **not data-threatening** (the collector, which
produces the market data, stops cleanly) — left unfixed during the window per §2.

## 12c. Window-2 status — `paper-lab-continuous-03` (IN PROGRESS)

GATE 0 (live state) and GATE 1 (self-policing) executed. The window is **not yet eligible** for
certification: wall-clock is < 24 h.

| | |
|---|---|
| Start (UTC) | ≈ `2026-09-30T17:53:01Z` |
| Expected eligible (UTC) | ≈ `2026-10-01T17:53:01Z` |
| State | `HEALTHY` — paper/collector/retention/strategy-lab all `RUNNING`, 0 restarts |
| Advancing proof | events **+118,667** and `last_receive` **+91,829 ms** over **94.9 s** wall; cycle 11→12 |
| Gaps / reconnects | 0 / 0 |
| Segments | 458 |
| Disk free | 26.35 GB (`NORMAL`) |
| Collector budget | 7,000,000,000 B |
| Monitor | `reports/paper-lab/run03_monitor.py` → `MONITOR.jsonl` every 300 s (read-only) |
| Eligibility | **INCOMPLETE** — GATES 3–9 pending |

No certification claim is made until wall-clock **and** data timestamps independently prove ≥ 24 h.

## 13. Evidence files

- [manifest](../reports/microstructure-forward-continuous/manifest/paper-lab-continuous-02.json)
- [collector resume state](../reports/microstructure-forward-continuous/state/paper-lab-continuous-02.json)
- [retention report](../reports/microstructure-forward-continuous/reports/RETENTION_REPORT.json)
- [system heartbeat](../reports/paper-lab/paper-lab-continuous-02/SYSTEM_HEARTBEAT.json)
- [lab plan](../reports/paper-lab/paper-lab-continuous-02/LAB_PLAN.json)
- [collector log](../reports/paper-lab/paper-lab-continuous-02/logs/collector.log)
- [RUN_REPORT.md](RUN_REPORT.md)
- [FINAL_REPORT.md](FINAL_REPORT.md)
