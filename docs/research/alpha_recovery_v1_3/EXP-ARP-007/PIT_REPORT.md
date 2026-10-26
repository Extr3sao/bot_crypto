# EXP-ARP-007 — PIT REPORT (§4)

Contract: `data_time <= decision_time <= fill_time`.

## Construction guarantees

* **Daily bar = complete UTC bucket.** A day becomes a bar only if it carries all 288
  contiguous 5m bars starting exactly at the UTC day boundary and ending 287×5m later.
  The current, partially-formed day can never become a bar.
* **Pivot look-ahead absent.** The pivot for day `D` is built from **day `D−1`'s** OHLC
  only (`self._pivot[i]` reads `bars[i-1]`).
* **Fill after decision.** A signal on the *closed* day `D` (pivot known, `ATR(14)` known)
  is filled at the **open of day `D+1`**; `data_time(D) <= decision(close D) <= fill(open D+1)`.
* **No future rolling statistic.** `ATR(14)` uses only closed bars `<= i`.
* No normalisation, no asset-membership, no HTF helper is used. `htf_pit.py` is **not**
  imported (the `DEF-HTF-PIT-001` orphan path is avoided entirely).

## Adversarial tests (`tests/unit/research/test_alpha_recovery_daily.py`)

| test | what it proves |
| --- | --- |
| `test_daily_bars_use_complete_days_only_and_aggregate_correctly` | incomplete trailing day is dropped; daily bar never straddles a UTC day |
| `test_a_day_with_a_gap_is_not_treated_as_complete` | a missing 5m bar ⇒ no daily bar |
| `test_exp007_entry_is_pit_invariant_to_future_days` | `entry(i)` is identical when later days are truncated/appended |
| `test_exp007_uses_only_the_prior_day_pivot` | pivot levels derive from day `D−1`; dual-touch day yields no signal |
| `test_daily_entry_fills_at_next_open_not_signal_close` | fill price is `open[i+1]`, not `close[i]` |
| `test_daily_stop_first_on_intrabar_ambiguity` | ambiguous bar resolves to the stop |
| `test_daily_max_hold_forces_exit` | force-exit on the hold limit |
| `test_daily_simulation_is_deterministic` | byte-identical trades across runs |

## Result

**PIT PASS** — no look-ahead found; no `REJECT_PIT`.
