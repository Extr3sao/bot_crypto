# EXP-ARP-010 — PRE-EXECUTION SPEC AUDIT (§2, §3)

## Identity

* experiment: `EXP-ARP-010`
* strategy_id: `H-VOLSPIKE-MR-001` — **new project hypothesis** (no `STRAT-CAND` lineage)
* arm: `PROJECT_DERIVED_VARIANT` — source attribution **`NONE`**
* mechanism: mean reversion after a volatility spike (multi-hour-to-daily horizon)
* grounding: in the admission ledger the `volatility` family had the largest gross
  (`volatility@30m` +8.91 bps, `@1h` +6.28), all `COST_KILLED` at 5m/30m/1h.
* frozen manifest: `MANIFEST.json` sha256 `d8dc71a32daab27e11455ecf94181ae724e4c541c6c839c1d487b6261821eb07`
  (validated against config `6c4dd0be…`, dataset `9d51385d…`, cost `23.559 bps` — all match).

## Deterministic rule set

| element | frozen definition |
| --- | --- |
| bars / timeframe | 1-day bars from the frozen 5m corpus via complete UTC epoch buckets |
| realized vol | `sqrt(sum(r_5m²))` over that day's own completed 5m returns |
| regime | daily-vol z-score vs the trailing `vol_lookback_days=60` window (population stdev; current day excluded; contiguous days; `None` until the window is full) |
| signal | `vol_z ≥ 2.0` **and** the day's price change `≤ −1.0 × ATR(14)` → **long** at the next open |
| entry | next daily bar's open |
| stop | `2.0 × ATR(14)` from entry |
| target | `1.0 × ATR(14)` from entry |
| max hold | `2` days |
| direction | **long-only** (spot corpus) |
| position | one at a time per symbol; fixed 500 USD notional |
| cost | single round-trip `COST_MODEL_V3` figure |

## Ambiguities resolved to remove all discretion (frozen before results)

1. **"day's return ≤ −1.0 × ATR(14)" is read dimensionally.** ATR is a price distance,
   so the day's *price change* `close[D] − close[D−1]` (same units) is compared to
   `−1.0 × ATR(14)`. (The literal phrase mixes a ratio with a price; the only
   consistent reading is used and recorded here.)
2. **Realized-vol window.** `sqrt(sum(r²))` over the **287 intra-day** 5m returns of the
   day (the day's own completed bars, available at that day's close) — no future bar.
3. **Z-score window excludes the current day** and requires day-contiguity; the trailing
   60 days must all be present, otherwise the z-score is undefined (no signal).
4. **`max_hold_days=2`** = the position may span at most 2 daily bars counting the entry
   bar. Stop/target are anchored to the **fill open** (resolved by `simulate_daily`).
5. **Stop-first on intra-bar ambiguity.**

No discretionary rule remains.
**Verdict: `EXPERIMENT_READY` (no `NEEDS_SPEC`).**

## Pre-declared testability caveat

60-day warmup + the rare `vol_z ≥ 2.0` trigger means DEV may yield < 10 trades →
`INSUFFICIENT_EVIDENCE`. The trigger threshold is **frozen** and must not be lowered
after seeing DEV. (It was not.)
