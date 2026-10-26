# RFC048_FUTURES_ECONOMIC_FEASIBILITY

Offline, synthetic-gross-move analysis of spot versus linear perpetual exposure under
**frozen** assumptions. Measured artefact: `data/rfc048/ECONOMIC_FEASIBILITY.json`.

> Nothing here is a profitability claim. The gross moves are hypothetical, applied to a
> frozen cost model; no rejected out-of-sample result was used as a selection input
> (`oos_reused = 0`), and no strategy was created or modified.

## 1. Frozen assumptions

| assumption | value | source |
| --- | --- | --- |
| gross moves tested | `+1 %`, `−1 %` | synthetic, applied identically to every leg |
| holding period | 60 minutes | one hour, inside a single funding window |
| equity context | 200 USDT | RFC-048 §5 experimental reference |
| comparison A reference size | `0.004 BTC` = 330.00 USDT | on the venue quantity grid (step 0.001) |
| comparison B allocated capital | `0.002 BTC` = 165.00 USDT | on the venue quantity grid |
| spot round trip | **23.7906 bps** | `docs/COST_MODEL_V3.json` (frozen, unmodified) |
| futures round trip (measured) | **12.02 bps**, `COST_ESTIMATED` | this RFC's futures cost model on the venue snapshot |
| funding | 0 bps in these legs | no settlement falls inside a 60-minute horizon (interval 28 800 000 ms) |
| matrix policy | `risk_budget_pct = 5 %`, caps 6× equity, max 5× | declared in the artefact; exists only to keep the two comparisons like-for-like |

The matrix policy is an **experimental assumption of the comparison**, not an approved limit:
under the engine's own 0.5 % / 1 % budgets the same exposures are *not* admissible, and the
scenario catalogue (31 cases) shows the engine shrinking or refusing them.

## 2. Comparison A — same notional, different leverage

Long, +1 % and −1 %, notional held at 330.00 USDT wherever capital allows.

| leg | notional | margin | gross PnL | net PnL | return on margin | liquidation buffer |
| --- | --- | --- | --- | --- | --- | --- |
| SPOT | 330.00 | 330.00 | +3.3000 | +2.5149 | 0.762 % | n/a |
| PERP 2x | 330.00 | 165.00 | +3.3000 | +2.9032 | 1.760 % | 4 854 bps |
| PERP 3x | 330.00 | 110.00 | +3.3000 | +2.9032 | 2.639 % | 3 181 bps |
| PERP 5x | 330.00 | 66.00 | +3.3000 | +2.9032 | 4.399 % | 1 842 bps |
| PERP 1x | 165.00 | 165.00 | +3.3000* | +3.1016* | 1.880 % | 9 874 bps |

`*` the 1x leg is the one case where "same notional" cannot hold: with 200 USDT of equity the
capital itself caps the position at 165.00 USDT. That is a finding, not an artefact — **at 1x,
capital is the binding constraint; above 1x, risk policy is.**

Adverse case (−1 %): gross `−3.3000` for every leg, net `−4.0851` (spot) versus `−3.6968`
(perp 2x/3x/5x) — the futures round trip is roughly half the spot round trip, so the perp
legs lose less on the identical move. **That difference comes from the cost model, not from
leverage**: net PnL is identical at 2x, 3x and 5x because exposure is identical.

## 3. Comparison B — same capital allocated, different exposure

165.00 USDT of margin allocated once, held across leverage. Here the notional scales 1:1
with leverage, which is the real difference the RFC asks to isolate.

| leg | notional | margin | gross PnL (+1 %) | net PnL (+1 %) | net PnL (−1 %) | return on margin | liquidation buffer |
| --- | --- | --- | --- | --- | --- | --- | --- |
| SPOT | 165.00 | 165.00 | +1.6500 | +1.2575 | −2.0425 | 0.762 % | n/a |
| PERP 1x | 165.00 | 165.00 | +1.6500 | +1.4516 | −1.8484 | 0.880 % | 9 874 bps |
| PERP 2x | 330.00 | 165.00 | +3.3000 | +2.9032 | −3.6968 | 1.760 % | 4 854 bps |
| PERP 3x | 495.00 | 165.00 | +4.9500 | +4.3548 | −5.5452 | 2.639 % | 3 181 bps |
| PERP 5x | 825.00 | 165.00 | +8.2500 | +7.2580 | −9.2420 | 4.399 % | 1 842 bps |

Read the two tails together: at 5x the favourable move returns 4.399 % on the allocated
margin while the adverse move returns −5.601 %. The asymmetry is the cost drag amplified by
the larger notional, and the liquidation buffer has shrunk from 9 874 bps to 1 842 bps for
the same capital. **Leverage does not create alpha; it multiplies both tails and shortens the
distance to liquidation.**

## 4. What the numbers prove and what they do not

Proven (mechanically, from the executed artefacts):

1. `leverage_creates_alpha = false` — gross PnL at a fixed notional is identical across
   1x…5x, and net PnL is identical once exposure is identical.
2. Return on the *allocated capital* rises with leverage while the *risk* rises at least as
   fast: modelled worst loss grows linearly with the notional, and the liquidation buffer
   shrinks by the same factor.
3. Futures costs are lower than the frozen spot round trip in this micro-example
   (12.02 bps vs 23.7906 bps), and both are dwarfed by any strategy edge that has to beat
   them before it is worth any capital.

Not proven, and not claimed:

- any expectation of return: the gross moves are synthetic and identical in both directions;
- any statement about a real venue's fill quality beyond the measured snapshot (depth
  impact was measured on 100 visible levels at one instant);
- that leverage is "safe" at any level: 4 of the 31 executed scenarios end in `RISK_VETO`
  precisely because the stop would be reached after liquidation.

## 5. Safe leverage ceiling

With a 50 bps stop, a 40 bps maintenance-margin rate, ~12 bps of round-trip cost and a
50 bps policy buffer, the leverage at which liquidation would land exactly on the stop is

```text
1 / (stop + maintenance_margin_rate + round_trip_cost + buffer)
= 1 / (0.0050 + 0.0040 + 0.0012 + 0.0050) ≈ 65.8x
```

This is an upper bound on *geometry*, not a recommendation: policy caps the case at 5x, and
everything above ~66x would be liquidated before the stop could protect anything. It also
shows why the binding constraints on 200 USDT of equity are exposure and capital, not the
venue's 150x ceiling.

## 6. Reproduce

```bash
uv run python scripts/rfc048_derive_instruments.py   # fixtures from the venue payloads
uv run python scripts/rfc048_run.py                  # execute the catalogue + the matrix
uv run python scripts/rfc048_verify.py               # independent verification
uv run python scripts/rfc048_report.py               # final report
```
