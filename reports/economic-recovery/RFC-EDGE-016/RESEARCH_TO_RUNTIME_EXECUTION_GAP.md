# Research to runtime execution gap

Where the experimental lane and the live runtime still differ, stated rather than implied.

| dimension | runtime | experimental lane (016) | verdict |
| --- | --- | --- | --- |
| admission | authoritative ledger | bypassed by design, labelled EXPERIMENTAL | accepted gap |
| risk engine | RiskManager.check_signal | RiskManager.check_signal (same object) | parity |
| portfolio | one live book | one 10 000 USDT book | parity in shape |
| fills | venue | next bar open, no latency | optimistic in timing |
| costs | venue fees, real spread | frictionless book, cost applied in the restatement | restated, not executed |
| stops | exchange/venue orders | resting level tested on the bar's high/low, stop_first | optimistic for a gap through the level |
| weekend | nothing reads the flag | refuses Saturday and Sunday entries | gap is in the runtime, not the lane |

## Policy fields declared and read by nothing

- `blocks.excessive_spread_bps`
- `blocks.extreme_atr_pct`
- `blocks.high_latency_ms`
- `blocks.weekend_trading`
- `live_trading_enabled`

Those are findings about the runtime's own policy, not about this research lane. They are reported here because a policy that is declared and unenforced is exactly how a risk control becomes decorative.

## What a promotion would still have to show

1. A prospective sample with decisions, not just observed bars.
2. The same restated results under an unchanged risk policy, at 2x cost or worse.
3. A concentration and drawdown profile inside the frozen protocol's thresholds.
4. A governance decision for any change to the weekend rule.
