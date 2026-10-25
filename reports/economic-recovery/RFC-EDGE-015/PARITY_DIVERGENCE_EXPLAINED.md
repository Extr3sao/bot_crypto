# WP-EDGE-015/P0.5 — the two open parity divergences, resolved

*Jesse: **RESOLVED**. VeighNa: **RESOLVED**.*

## Jesse — the 7.02 bps residual

the 7.021359 bps residual is not an engine disagreement: it is 6.985523 bps of PRICE on the two trades still open when the window ends (this project closes at the final bar's open, Jesse at its close), plus 0.095587 bps of our own fee-convention gap, minus 0.059741 bps because the engine's realised charge is 19.940259 bps rather than the declared 20 bps — every term read from the published rows

- matched trades: 44
- materially different trades: [19, 43] (the forced exits: True)
- worst difference among the other trades: 0.080318 bps (tolerance 1.0 bps)
- decomposition error: 1.21e-07 bps

| index | our gross | engine gross | gross price effect | engine fee vs declared | fee-convention gap | observed | predicted | error |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 19 | -42.814968 | -49.800491 | 6.985523 | -0.059751 | 0.095587 | 7.021359 | 7.021359 | -0.0 |
| 43 | 24.216135 | 27.110767 | -2.894632 | 0.017084 | -0.038408 | -2.915956 | -2.915956 | 0.0 |

## VeighNa — the two unmatched trades

the two-trade gap is the window boundary, not the rule: VeighNa emitted 44 entries and 42 exits, this project's reader pairs fills in order, and the neutral rule's last two entries are exactly the two positions still open at the end of the window

- external fills: 44 open / 42 close → 2 unpaired
- matched trades: 42; only in this project: 2
- the unmatched ones are the last two entries: True
- forced closes in the rebuilt rule: 2

## Method

reconstruction from the published per-trade rows and the frozen bars; neither external engine was re-run, and no number was adjusted
