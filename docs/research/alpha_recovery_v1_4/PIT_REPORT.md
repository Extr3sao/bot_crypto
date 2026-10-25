# ARP-005 — PIT / LOOK-AHEAD REPORT (§11)

Invariant enforced for every mechanism: **`data_time <= decision_time <= fill_time`.**
Any violation invalidates the experiment. `TEST_TARGET == RUNTIME_TARGET`: the modules
under test are exactly those the driver imports.

## Adversarial tests (all passing)

| requirement | test | mechanism |
| --- | --- | --- |
| future bar inaccessible | `test_rank_is_pit_safe_to_future_bars` | xsec ranker |
| future cross-sectional member inaccessible | same (appending a future member's wild bars cannot move the decision at `t`) | xsec |
| future rank inaccessible | `test_rank_is_pit_safe_to_future_bars` (`as_of <= t`) | xsec |
| stale member rejected | `test_stale_and_missing_symbols_are_excluded_not_ranked` | xsec |
| misaligned / non-contiguous window rejected | `test_non_contiguous_window_is_rejected`, `test_trailing_return_requires_full_contiguous_window` | xsec |
| deterministic tie handling | `test_deterministic_tie_break_by_symbol` | xsec |
| cross-sectional portfolio determinism | `test_xsec_is_deterministic` | xsec portfolio |
| future bar inaccessible (daily strategy) | `test_exp006_detects_void_and_is_pit_invariant`, `test_exp011_breakout_requires_vol_expansion_and_is_pit_safe` | 006/011 |
| next-open fill (not signal close) | `test_daily_entry_fills_at_next_open_not_signal_close` | simulator |
| stop-first on intra-bar ambiguity | `test_daily_stop_first_on_intrabar_ambiguity` | simulator |
| hold-limit force exit | `test_daily_max_hold_forces_exit` | simulator |
| simulation determinism | `test_daily_simulation_is_deterministic` | simulator |
| duplicate timestamps / missing days | ARP-004 `test_a_day_with_a_gap_is_not_treated_as_complete` (unchanged) | derivation |

## Completeness of the daily derivation

`daily_bars_from_5m` emits a day only when it carries exactly **288** 5-minute bars,
the first at the exact UTC boundary and the last 287×5m later. A partially-formed
(current) day can never become a daily bar, and a day with any hole is dropped, not
patched. This applies identically to the extended corpus.

## Provider-failure surfacing

The extended-corpus fetcher raises after 4 attempts (`urllib` exception propagates),
so a provider failure aborts the fetch rather than yielding a silent partial file. The
committed corpus is content-addressed; a partial/corrupt file changes the digest and
fails `test_extended_manifest_and_digest_are_reproducible`.

## Result

**No PIT violation detected in any executed mechanism.** All 22 ARP-005 tests pass.
