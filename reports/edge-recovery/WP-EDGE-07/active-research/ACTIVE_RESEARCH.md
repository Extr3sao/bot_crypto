# WP-EDGE-07 Track C — an ACTIVE multi-asset book, and the wall it has to clear

*Run at `2026-10-14T09:11:24Z` (`EDGE07-ACTIVE-20261014T091124Z`), registered `2026-10-14T09:20:00Z` — before any candidate was measured, with a multiplicity of 2.*

## 1. The wall, first

`COST_MODEL_V3` at a one-hour horizon is **23.79 bps per round trip**. Three trades a day is therefore **71 bps a day** of cost before any edge exists, and a book at this frequency must earn more than that per trade, on average, in gross terms. Every candidate below carries `cost_margin: 1.25`, so the instrument refuses a setup whose own objective cannot pay for itself — the frequency target is never a reason to force a trade.

## 2. The verdicts

| Book | Verdict | Why |
| --- | --- | --- |
| `edge07_active_thrust` | **REJECT_NO_GROSS_EDGE** | the setup loses money before any fee on DEV (-0.2694 USDT/trade over 338 trades), which no cost change can repair |
| `edge07_active_fade` | **REJECT_NO_GROSS_EDGE** | the setup loses money before any fee on DEV (-0.788 USDT/trade over 255 trades), which no cost change can repair |

## 3. The cost screen (C0), on the development windows

| Book | Window | Trades | Per day | Gross/trade | Gross bps/trade | Net | Expectancy | PF |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `edge07_active_thrust` | DEV | 338 | 0.1852 | -0.2694 | -5.3873 | -492.9215 | -1.4583 | 0.6375 |
| `edge07_active_thrust` | VAL | 367 | 1.0055 | -0.1609 | -3.2178 | -495.4514 | -1.35 | 0.6493 |
| `edge07_active_fade` | DEV | 255 | 0.1397 | -0.788 | -15.761 | -503.9857 | -1.9764 | 0.6521 |
| `edge07_active_fade` | VAL | 363 | 0.9945 | -0.1688 | -3.376 | -492.9185 | -1.3579 | 0.7481 |

## 5. What this does not do

- It promotes nothing: `promotion: NONE`, `order_sent: false`, no capital, no orders.
- It tunes nothing: the parameters are the registered ones, screened in the registered
  order, and the independent window is read once. A candidate that fails is reported with
  its numbers and is not retried here.
- A candidate that cannot reach three trades a day has not answered this mission's
  question, and its verdict says so rather than passing on money alone.
