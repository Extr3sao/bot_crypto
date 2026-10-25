# EXP-ARP-010 — PIT REPORT (§4)

Contract: `data_time <= decision_time <= fill_time`.

## Construction guarantees

* **Daily bar = complete UTC bucket** (288 contiguous 5m bars; partial days dropped).
* **Realized vol is contemporaneous, not forward.** `sqrt(sum(r_5m²))` uses the day's
  **own** closed 5m bars, which are only complete at that day's close — it is a
  `data_time <= decision_time` statistic, never a future bar.
* **Vol z-score is prior-only.** The z-score compares day `D`'s vol against the
  **previous 60 contiguous days** (current day excluded); it is `None` until the window
  is full and is `None` if the window is not day-contiguous.
* **ATR(14)** uses only closed daily bars `<= i`.
* **Fill after decision.** A signal on the closed day `D` is filled at **open of `D+1`**;
  the stop/target ATR distances are resolved against that fill price.
* No normalisation, no forward membership, no HTF helper. `htf_pit.py` is not imported.

## Adversarial tests (`tests/unit/research/test_alpha_recovery_daily.py`)

| test | what it proves |
| --- | --- |
| `test_exp010_signal_and_pit_invariance` | `entry(4)` is unchanged when later days are truncated or replaced with wildly different future bars/vols |
| `test_exp010_zscore_window_requires_day_contiguity` | a contiguous window fires; a one-day hole in the trailing window ⇒ no signal |
| `test_realized_daily_vol_matches_definition` | realized vol equals `sqrt(287 · r²)` for a known constant-return day |
| `test_daily_bars_use_complete_days_only_and_aggregate_correctly` | incomplete day dropped; no bar straddles a UTC day |
| `test_daily_entry_fills_at_next_open_not_signal_close` | fill price is `open[i+1]` |
| `test_daily_stop_first_on_intrabar_ambiguity` | ambiguous bar resolves to the stop |
| `test_daily_simulation_is_deterministic` | byte-identical trades across runs |

## Result

**PIT PASS** — no look-ahead found; no `REJECT_PIT`.
