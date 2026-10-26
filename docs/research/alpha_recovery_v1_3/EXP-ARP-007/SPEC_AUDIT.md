# EXP-ARP-007 — PRE-EXECUTION SPEC AUDIT (§1, §3)

## Identity

* experiment: `EXP-ARP-007`
* strategy_id: `STRAT-CAND-019-VARIANT-B`
* arm: **`PROJECT_DERIVED_VARIANT`** — source attribution **`NONE`**
* mechanism: level reaction (fade first contact with a daily pivot band)
* **This is NOT a source-faithful test of `STRAT-CAND-019`.** The source
  reconstruction is `BLOCKED_NEEDS_SPEC`; no result may be attributed to the source
  hypothesis. Prior art `EXP-ARP-005` (`-VARIANT-A`, 5m) was `REJECT_COSTS` — a
  different experiment, not a re-reading.
* frozen manifest: `MANIFEST.json` sha256 `b338beeea154df1c8a304e913e03bfe61f7371617ecc4739cad134734e48c642`
  (validated against config `6c4dd0be…`, dataset `9d51385d…`, cost `23.559 bps` — all match).

## Deterministic rule set

| element | frozen definition |
| --- | --- |
| bars / timeframe | 1-day bars from the frozen 5m corpus via **complete UTC epoch buckets**; incomplete days dropped, never synthesised |
| pivot source | prior completed UTC day's `H`,`L`,`C` only |
| pivot formula | `PP = (H+L+C)/3`, `R1 = 2·PP − L`, `S1 = 2·PP − H` |
| signal | a daily bar with `high ≥ R1` → fade **short**; `low ≤ S1` → fade **long** |
| entry | **next daily bar's open** (`open[i+1]`), in the fade direction |
| stop | `1.0 × ATR(14)` **beyond the level** (`R1 + 1·ATR` short / `S1 − 1·ATR` long) |
| target | `PP` (central pivot) |
| max hold | `3` days |
| position | one at a time per symbol; fixed 500 USD notional; no compounding |
| cost | single round-trip `COST_MODEL_V3` figure applied to notional |

## Ambiguities resolved to remove all discretion (frozen before results)

1. **Dual-touch day skipped.** A day whose bar touches **both** `R1` and `S1` produces
   **no** trade: the intraday contact order is unknowable from daily OHLC, and picking
   one would be discretionary. (Conservative; removes a look-ahead temptation.)
2. **`max_hold_days` semantics.** The position may span at most 3 daily bars *counting
   the entry bar*; it is force-closed at the close of the 3rd bar if neither stop nor
   target is hit. (`simulate_daily`, `window_expiry`.)
3. **Next-open fill.** `simulate_daily` fills at `open[i+1]`, matching the frozen
   "entry: next daily bar's open" wording (the 5m simulator fills at `close[i]`; the
   daily horizon requires the next-open contract).
4. **Stop-first on intra-bar ambiguity** (stop and target spanned in one bar ⇒ stop),
   so the simulator can never flatter the strategy.

No discretionary rule remains.
**Verdict: `EXPERIMENT_READY` (no `NEEDS_SPEC`).**
