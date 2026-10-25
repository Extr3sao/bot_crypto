# WP-9D — M-03 / M-07 readiness

> generated `2026-10-11T20:53:14Z` · OFFLINE READ-ONLY AUDIT — nothing started, no threshold changed, config/ read only

## 1. Verdict

`M-03 = NOT_READY` · `M-07 = NOT_READY` · `RESEARCH_READY = False`

the infrastructure works and the cadence meets the bar; the history does not exist yet, and no sample may be synthesised to fill it

## 2. The history that exists

* sealed: **4.1593 h** (0.1733 days, 0 whole-day segment(s)) from 1 manifest(s)
* pairs captured: BTCUSDT, ETHUSDT (assets BTC, ETH)
* book checkpoints: 1984 · OI samples: 488 · crossed books: 0 · longest unrecovered gap: 0.0 s
* collected but **not** history: `paper-lab-continuous-03` (5.8868 h, 1.74 GB, manifest published: False) — excluded because it has no contract artefact

## 3. What each gate demands, and what is missing

### M-03 — order book imbalance

`3 met / 2 not met / 1 not measurable` of 6 criteria. Cost to close: **72.0 h** (3.00 days) = 13.84 GB at the measured rate, 20.76 GB at 1.5x — **does not fit** this volume (17.70 GB free).

| criterion | requirement | observed | result | shortfall |
| --- | --- | --- | --- | --- |
| `forward_book_hours` | >= 24.0 h of forward book | 4.159301 | `NOT_MET` | 19.8407 |
| `min_book_checkpoints` | >= 1000 book checkpoints | 1984 | `MET` | 0 |
| `max_unrecovered_gap_seconds` | <= 300.0 s for any unrecovered gap | 0.0 | `MET` | — |
| `book_health_at_checkpoints_pct` | >= 90.0 % of checkpoints with a healthy book | None | `NOT_MEASURABLE` | — |
| `assets` | captured: BTC, ETH, SOL | ['BTC', 'ETH'] | `NOT_MET` | ['SOL'] |
| `timeframes_minutes` | measurable at: [1, 5] minutes | None | `MET` | — |

the book window is the binding criterion at 24 h, but DEV/VAL/OOS needs three non-overlapping segments, so 72 h of capture is the floor for a research-ready M-03 rather than 24 h

* `min_book_checkpoints`: the rate already clears this bar; the window is what is missing
* `book_health_at_checkpoints_pct`: the sealed manifest publishes the books' state at shutdown (STALE, because the feeds stop) and not the fraction of the window they were healthy; the campaign report says the same in its own words. A number here would be invented
* `assets`: SOL was never captured, and the two windows that exist cover BTC and ETH
* `timeframes_minutes`: the retention policy's aggregate tiers are 1/5/15/30 minutes, so 1 and 5 exist; this is capability, not history

_the history this hypothesis needs cannot be accumulated on this volume at the stress rate without either another volume (--data-root) or authorised deletion of raw that compaction has already replaced_

### M-07 — open interest x price

`2 met / 4 not met / 0 not measurable` of 6 criteria. Cost to close: **168.0 h** (7.00 days) = 32.30 GB at the measured rate, 48.45 GB at 1.5x — **does not fit** this volume (17.70 GB free).

| criterion | requirement | observed | result | shortfall |
| --- | --- | --- | --- | --- |
| `open_interest_days` | >= 7.0 days of open interest | 0.173304 | `NOT_MET` | 6.826696 |
| `min_oi_samples` | >= 10000 open-interest samples | 488 | `NOT_MET` | 9512 |
| `oi_sample_interval_seconds_max` | <= 120.0 s between samples | 61.367 | `MET` | — |
| `disjoint_periods_required` | 3 disjoint periods, each >= 1 day | 0 | `NOT_MET` | 3 |
| `assets` | captured: BTC, ETH, SOL | ['BTC', 'ETH'] | `NOT_MET` | ['SOL'] |
| `timeframes_minutes` | measurable at: [5, 15, 30] minutes | None | `MET` | — |

the pre-registration asks for 7 days of open interest, and three disjoint periods each of at least a day cannot be cut from less

* `disjoint_periods_required`: a DEV/VAL/OOS split needs three windows that do not overlap, so the floor is three days of capture however the 24 h window is read
* `timeframes_minutes`: the retention policy's aggregate tiers are 1/5/15/30 minutes, so 5/15/30 exist; this is capability, not history

_the history this hypothesis needs cannot be accumulated on this volume at the stress rate without either another volume (--data-root) or authorised deletion of raw that compaction has already replaced_

## 4. Two pre-registrations that do not agree

**TWO_PRE_REGISTRATIONS_NOT_RECONCILED** — the campaign asks M-07 for >= 24 h and 1440 samples/asset; the machine-readable pre-registration (M-PREREG-V1) asks for 7 days, 10000 samples and three disjoint day-plus periods. Both are on the record, both matter, and M-07 is NOT_READY under either — but the shortfall is 24 h under one reading and 7 days under the other, which is a 7x difference in the resources the operator would have to commit

| reading | M-07 window | M-07 samples | observed | shortfall |
| --- | ---: | ---: | ---: | ---: |
| `PAPER_DATA_24H_REPORT.json` | 24 h | 1440 | 4.16 h | 19.84 h |
| `config/microstructure_preregistration.json` | 168 h | 10000 | 4.16 h | 163.84 h |

Binding reading: the pre-registration: it is machine-readable, it is the one the lane's own verification reads, and by its own rule a threshold cannot be lowered after the fact

## 5. What is *not* missing

* the shared replay gate: `411/411 fingerprints`, book_match=True, deterministic=True, internet_access=False;
* the cadence: OI is sampled at ~1/min, comfortably inside the 120 s bar;
* the aggregate tiers that make a long capture affordable: [1, 5, 15, 30] minutes, with the preservation policy holding raw until M-03 and M-07 survive compaction.

## 6. What the runtime must generate, and how it is now protected

* collector: `scripts/forward_collector.py (started by scripts/start_paper_lab.py)`
* cost: 192.42 MB/h at the measured rate, 0.80 GB for 4.16 h
* preflight: scripts/start_paper_lab.py now refuses a window its valve cannot pay for, so the accumulation can be started with the window it actually needs
* automatic: yes, and it already is: the collector samples OI/funding/mark from REST at ~1/min and writes depth/book_ticker continuously; what has never happened is a sealed window long enough

## 7. Checks

| check | result |
| --- | --- |
| only sealed windows are counted as history | `PASS` |
| the unsealed window is reported and excluded | `PASS` |
| no threshold was changed by this audit | `PASS` |
| a criterion the evidence cannot answer is NOT_MEASURABLE, not MET | `PASS` |
| the two pre-registrations are reported separately, not merged | `PASS` |
| each hypothesis's missing history is costed in hours and bytes | `PASS` |

