# WP-EDGE-14C — benchmark parity report

**State: pins verified, no engine executed.** each directory holds exactly one fetched commit and no working tree; nothing was installed, imported or run

## Neutral strategy

| id | rule | why neutral |
| --- | --- | --- |
| NEUTRAL_MA_CROSS_1H | long when ema(12) > ema(26) on closed 1h bars, flat otherwise | one plain rule, no fitted parameters, so a divergence is a model bug not a tuning choice |

## Preregistered tolerance

| measure | max difference |
| --- | --- |
| equity relative | 0.02 |
| trade count | 1 |
| per-trade net bps | 1.0 |

Declared before the run: **True**. On exceed: quantify and explain the model difference; never adjust the output by hand

## Engine states

| engine | state |
| --- | --- |
| trading_agentic | EXECUTED |
| jesse(SRC-02) | NOT_EXECUTED (fetched only) |
