# ARC02_MECHANISM_AUTHORITY.md

> What ARC-02 claims, who is on the other side, and what would refute it. No economic
> observation is recorded here; this document is the mechanism contract that the frozen
> spec is derived from.

## 1. Authority chain

| Link | Artifact |
| --- | --- |
| Candidate registry | `docs/alpha-research-universe-01/05_ALPHA_MECHANISM_CANDIDATES.json#ARC-02` — *"BTC-to-alt slow information transmission"*, data *"synchronized BTC/ETH/SOL OHLCV"*, PIT `PIT_SAFE_EASY`, collision `LOW`, class `ADOPT_P1` |
| Research queue | `docs/alpha-research-universe-01/09_NEXT_RESEARCH_QUEUE.json#rank-1` — *"3 assets; completed 5m BTC shock, fixed next-bar hold, 10bps; no grid"*; kill rule *"net expectancy<=0, PF<=1, or single-asset concentration"* |
| Collision matrix | `docs/alpha-research-universe-01/04_FAILED_MEMORY_COLLISION_MATRIX.json#ARC-02` — H1 `LOW`, H3 `MEDIUM`, H5 `LOW`, H6 `LOW` |
| Failed memory | `docs/external-audit-01/FAILED_RESEARCH_MEMORY.md` |
| Prior ARC-02 definition | `docs/arc02-candidate-design-01/*` — **DRAFT_ONLY**, never committed, never frozen |

## 2. Mechanism statement (frozen)

BTC is the information-leading instrument of the universe: it is the deepest, most liquid
and most arbitraged USDT perpetual, so macro and flow information is impounded into BTC
first. ETH and SOL are economically co-moving but segmented: their books are thinner, their
participant base is narrower, and part of their flow is routed through BTC as a proxy.

**Claim:** when a completed 5m BTC move is unusually large relative to BTC's own recent
behaviour (a *shock*), and a follower has already moved in the SAME direction but has not
yet responded proportionally, the follower is still mid-repricing. The remaining repricing
happens on the next bar, in the same direction.

```
BTC_SHOCK(t)  AND  FOLLOWER_UNDERREACTION(t, f)
        ->  FOLLOWER_CONTINUATION  ->  LONG f if r_btc(t) > 0 ; SHORT f if r_btc(t) < 0
```

## 3. Who is on the other side (who pays)

Latency-constrained and segmented participants: agents that cannot hedge ETH/SOL exposure
against BTC directly, or that only observe the leader with a lag. They buy (sell) the
follower after the leader has already moved, paying the continuation to whoever supplied
liquidity earlier. The claim requires the follower's *current* response to be incomplete —
not merely present — which is why the underreaction condition is part of the mechanism and
not a filter.

## 4. What is deliberately NOT part of the mechanism

* **No mean reversion.** ARC-02 trades WITH the leader's direction. A follower moving AGAINST
  the shock is `NO_SIGNAL`, never a reversal trade.
* **No order flow.** No taker-buy field, no trade count, no quote volume. The projection
  physically omits them (H5 territory).
* **No participation shock.** No volume record. Volume is the ARC-03 identifying field and is
  not present in the ARC-02 projection.
* **No open interest.** H6 territory; absent.
* **No funding signal.** Funding appears only as an execution cashflow leg.
* **No higher-timeframe regime, trend, volatility or breakout filter.** None is defined.
* **No cross-sectional or relative-value construction.** The two followers are evaluated
  independently against the SAME leader shock; they are never ranked, averaged or selected
  against each other, and the leader is never traded against a follower.

## 5. Why the frozen primitives take the form they do

| Choice | Why |
| --- | --- |
| Completed 5m bars | provider cadence is 5m; every component of the signal is a property of one completed bar |
| log return | scale-free by construction, symmetric under inversion, and the natural statement of "information transmission" |
| 288-bar trailing lookback | exactly one day of 5m slots: the shortest lookback spanning a full intraday cycle at this cadence |
| median of absolute returns (no centring) | 5m crypto returns are heavy-tailed; a single outlier would inflate a variance-based scale. Centring would add an estimated location parameter with no mechanism justification |
| strict `|z| > 3.0` | extreme-value convention for a robust standardised deviation, fixed from convention before any returns; equality is not a shock |
| strict `|r_f| < 0.5 * |r_btc|` | "has not yet responded proportionally"; equality means the follower has kept up and is not underreacting |
| same-sign required | the claim is continuation in the SHOCK direction; a counter-moving follower carries no continuation information |
| 1-bar (5-minute) holding | one step of information transmission at the 5m cadence. Longer holds would import a trend claim the mechanism does not make |
| open-anchored entry and exit | the project's frozen execution convention (clock arithmetic only, no intrabar price anywhere) |

## 6. Falsification surface

The mechanism is refuted if ANY of the following holds after the single authorized
econometric run:

1. the primary rule fails ANY critical gate G1–G11 (`DISCOVERY_FAIL`);
2. any of the four frozen controls satisfies ALL critical gates (`MECHANISM_NOT_IDENTIFIED`);
3. the DIRECTION control works (then the claim is a mean-reversion artifact, not continuation);
4. the TIMING control works (then the effect is not tied to the shock aftermath);
5. the LEADER control works (then BTC carries no identifying information and the claim is a
   follower-only continuation artifact);
6. the NULL control works (then the gate set is not discriminating).

No outcome of the above may be answered with a threshold, lookback, ratio, holding-period,
asset or cost change under this hypothesis id.
