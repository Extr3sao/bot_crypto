# WP-EDGE-14R/P3 — prospective holdout preregistration

*Frozen at `2026-10-16T20:01:44Z`, before any row of the holdout was
captured. Its sha256 is `ea332d4ee11a4b42dd2c586eb51fde59f177dba18280a1cea63cdae3bc2d79bc`.*

## Why a new slice

The frozen corpus (`sha256:d79ed2c56bf50226…`, 2026-09-05T00:00:00Z →
2026-10-16T15:00:00Z) has been read by the candidate experiments and by the
engine comparison. Any further scoring on it is in-sample. Mechanical parity between
engines can and has been tested on historical bars; **economic inference needs a slice no
decision has touched**.

## Frozen now

| axis | value |
| --- | --- |
| family | `ema_crossover` |
| parameters | fast=12, slow=26 |
| parameter source | frozen before capture; no fitting, no search, no walk-forward |
| instruments | BTC/USDT, ETH/USDT |
| timeframe | 1h |
| fees | 10.0 bps per side |
| spread | 0.0 bps per round trip |
| slippage | 0.0 bps per side |
| entry | long while ema(12) > ema(26) on the previous closed 1h bar; fill at the open of the next bar |
| exit | flat when ema(12) < ema(26) on a closed bar; fill at the open of the next bar |
| hypothesis | H0: this rule's net expectancy per trade is <= 0 after the declared costs. H1: it is > 0. The measurement window is exhausted at 2026-10-16T15:00:00Z, so every bar at or after that instant is prospective with respect to it |
| comparator | the runtime as it stands: no strategy admitted, no trades, flat equity. A candidate must beat that flat line net of the declared costs, not merely exist |

## Acceptance thresholds, frozen before the data exists

| threshold | value |
| --- | ---: |
| closed trades per strategy | >= 200 |
| net expectancy | > 0.0 bps per trade |
| profit factor | >= 1.2 |
| max drawdown | <= 2000.0 bps |
| cost sensitivity | stays positive at 15.0 bps per side |

## Reservation

The holdout is `OOS_RESERVED`: **selection never reads it**. Until it reaches the
thresholds above it is `OOS_ACCRUING`, and a slice that has not reached them cannot accept
or reject anything.
