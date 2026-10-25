# WP-EDGE-09B — source viability, coverage and point-in-time

*Measured at `2026-10-15T05:13:47Z`. Probes: 5. `promotion: NONE`.*

## 1. What the providers answer, today

| Probe | What it establishes | Status | Seconds | Reachable |
| --- | --- | ---: | ---: | :-: |
| P-01 | funding history reach (alternatives: none for a perp-only series) | 200 | 0.309 | True |
| P-02 | open-interest retention: the newest window the endpoint will serve | 200 | 0.408 | True |
| P-03 | liquidation prints: does a public endpoint exist at all | 404 | 0.266 | False |
| P-04 | order-book history: the endpoint answers with the current book only | 200 | 0.293 | True |
| P-05 | bulk archive reach for aggressor flow (monthly klines) | 200 | 0.758 | True |

A probe that does not answer is recorded as such: the package does not replace a missing series with a different one, and it does not model what it cannot measure.

## 2. What this repository already holds

| | |
| --- | --- |
| Capture roots with a manifest or segments | 21 |
| Total captured span | 10.14 h (36502.21 s) |
| Longest single capture | 14973.49 s |
| Runs declaring CONTINUOUS_DATA | 8 |
| Runs declaring INCOMPLETE_DATA | 10 |
| Markets covered | perp, spot |
| Symbols covered | BTCUSDT, ETHUSDT, SOLUSDT, _GLOBAL |
| Streams covered | agg_trade, book_checkpoint, book_ticker, depth_diff, depth_snapshot, funding, gap, heartbeat, lifecycle, mark_price, open_interest, violation |

most captures declare INCOMPLETE_DATA: the loss is quantified in their own manifests (gaps, reconnects, resnapshots), and this package reads the declared loss instead of assuming a clean stream

### Per run

| Root | Run | Duration (s) | Continuity | Markets | Segments | Reconnects | Resnapshots |
| --- | --- | ---: | --- | --- | ---: | ---: | ---: |
| `reports/microstructure-forward` | `forward-1790610007-9d07f3df` | 3783.341 | INCOMPLETE_DATA | ['spot', 'perp'] | 78 | 81 | 254 |
| `reports/microstructure-forward-cert01` | `paper-lab-cert-01` | 719.055 | CONTINUOUS_DATA | ['spot', 'perp'] | 89 | 0 | 4 |
| `reports/microstructure-forward-continuous` | `paper-lab-continuous-02` | 14973.485 | INCOMPLETE_DATA | ['spot', 'perp'] | 1009 | 9 | 23 |
| `reports/microstructure-forward-headcert` | `headcert-3d3be37` | 1000.913 | INCOMPLETE_DATA | ['spot', 'perp'] | 211 | 5 | 7 |
| `reports/microstructure-forward-headcert-222078b` | `headcert-222078b` | 782.278 | INCOMPLETE_DATA | ['spot', 'perp'] | 297 | 1 | 6 |
| `reports/microstructure-forward-lab` | `paper-strategy-lifecycle-shadow-02` | 7220.595 | INCOMPLETE_DATA | ['spot', 'perp'] | 409 | 113 | 354 |
| `reports/microstructure-forward-lab-03` | `None` | None | None | None | 36 | None | None |
| `reports/microstructure-forward-lab-04` | `None` | None | None | None | 10 | None | None |
| `reports/microstructure-forward-lab-05` | `paper-lab-stoprestart-02` | 94.049 | INCOMPLETE_DATA | ['spot', 'perp'] | 49 | 58 | 60 |
| `reports/microstructure-forward-lab-06` | `paper-lab-integrated-04` | 1295.996 | INCOMPLETE_DATA | ['spot', 'perp'] | 143 | 3 | 5 |
| `reports/microstructure-forward-lab-07` | `paper-lab-final-head-01` | 179.687 | CONTINUOUS_DATA | ['spot', 'perp'] | 40 | 0 | 2 |
| `reports/microstructure-forward-lab-08` | `paper-lab-continuous-01` | 3307.894 | INCOMPLETE_DATA | ['spot', 'perp'] | 69 | 5 | 10 |
| `reports/microstructure-forward-lab-smoke-cert` | `smoke-cert` | 20.887 | CONTINUOUS_DATA | ['spot', 'perp'] | 38 | 0 | 6 |
| `reports/microstructure-forward-lab-smoke-cert2` | `smoke-cert2` | 20.913 | CONTINUOUS_DATA | ['spot', 'perp'] | 38 | 0 | 6 |
| `reports/microstructure-forward-lab-smoke-cert3` | `smoke-cert3` | 20.867 | CONTINUOUS_DATA | ['spot', 'perp'] | 38 | 0 | 6 |
| `reports/microstructure-forward-lab-smoke-cert4` | `smoke-cert4` | 20.659 | CONTINUOUS_DATA | ['spot', 'perp'] | 59 | 0 | 6 |
| `reports/microstructure-forward-ops01` | `paper-lab-ops-hardened-01` | 1368.912 | INCOMPLETE_DATA | ['spot', 'perp'] | 115 | 1 | 7 |
| `reports/microstructure-forward-preservation-check` | `None` | None | None | None | 0 | None | None |
| `reports/microstructure-forward-recert-7b14297` | `recert-7b14297` | 662.709 | CONTINUOUS_DATA | ['spot', 'perp'] | 249 | 0 | 4 |
| `reports/microstructure-forward-smoke` | `forward-1790606407-7308fd49` | 23.262 | CONTINUOUS_DATA | ['spot', 'perp'] | 38 | 0 | 6 |
| `reports/microstructure-forward-writercert` | `writercert-v1` | 1006.71 | INCOMPLETE_DATA | ['spot', 'perp'] | 0 | 4 | 18 |

## 3. Verdict per source

| Source | Name | Depth | Point-in-time | Classification | Why |
| --- | --- | --- | --- | --- | --- |
| `SRC-19` | forward microstructure capture (this repository) | hours, not weeks: see the measured spans in this artifact | yes — every row carries event/available/receive clocks and the panel uses receive | **FORWARD_ONLY** | order book and quote state exist only forward; the capture is what makes M-03 measurable |
| `SRC-20` | spot aggressor flow from klines (taker buy fields) | complete history, aggregated per bar | bar close only | **HISTORICAL_USABLE** | already used by the microstructure phase; unchanged here |
| `SRC-21` | perp funding and premium index | complete history | publication instant | **HISTORICAL_USABLE** | re-probed here; the depth is measured, not assumed |
| `SRC-22` | perp open interest | ~30 days retained | publication instant | **LIMITED_HISTORY** | cannot cover a decisive window; measured again here rather than remembered |
| `SRC-23` | liquidation prints | none from this environment | n/a | **UNAVAILABLE_IN_CURRENT_ENVIRONMENT** | the public endpoint that once served them does not answer; no substitute is used |
| `SRC-24` | venue fee schedules (Binance/OKX/Kraken/MEXC) already registered | published headline rates | n/a | **HISTORICAL_USABLE** | the barrier this package measures against is built from these, not from assumptions |
