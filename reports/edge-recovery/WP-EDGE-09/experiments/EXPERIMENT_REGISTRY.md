# WP-EDGE-09E — experiment registry

- **E-01** (ACTIVE) — quote imbalance is big enough to pay a taker round trip: **COST_KILLED** — best measured cell perp/SOLUSDT h=60s gross 1.582703 bps vs 24.0731 bps barrier — gross 1.5827 bps is below the measured round trip 24.0731 bps (cells: {'COST_KILLED': 30})
- **E-02** (CROSS-VENUE) — the fee schedule is the binding constraint, not the signal: **COST_KILLED** — the cheapest registered schedule (MEXC_SPOT_TAKER at 12.9866 bps) still exceeds the best measured gross (1.582703 bps): the fee schedule is not the only constraint
- **E-03** (ACTIVE) — the measured book can absorb our order size inside the barrier: **OBSERVED** — spot depth snapshots are rare in this capture, so a spot capacity claim rests on a small number of observations and is reported as such
- **E-04** (QUALITY) — open interest with price is exploitable on a slower clock: **INSUFFICIENT_SAMPLE** — PRICE_DOWN_OI_UP n=14 mean=-8.015351 bps against a barrier of 23.1512 bps
- **E-05** (ACTIVE) — three executed trades a day is reachable by a positive structure: **OBSERVED** — the tape clears the barrier at h=60s at 144.061 long-only opportunities/day (upper bound, long-only, extrapolated from 1.999-4.155 h of capture), so the ACTIVE frequency target is not what blocks the book at those horizons
- **E-06** (EXECUTION) — a taker entry pays no more than the measured spread and impact: **OBSERVED** — median measured taker shortfall 0.0187 bps against the modelled spread+impact components
- **E-07** (GUARD) — negative control: the pipeline does not manufacture an edge: **NO_GROSS_EDGE** — negative control verdicts: ['COST_KILLED', 'NO_GROSS_EDGE', 'NO_INFORMATION']

Rejected hypotheses and the negative control are registered here too.
