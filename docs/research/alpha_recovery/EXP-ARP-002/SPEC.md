# EXP-ARP-002 — Liquidity-void retest (rebalancing reversal)

- source_strategy_id: `STRAT-CAND-016`
- family: liquidity / stop-hunt reversal
- mechanism: **reversal** (orthogonal to every continuation family)

**Hypothesis:** a fast, one-sided candle sequence (a "liquidity void") is revisited
and rebalanced; entering on the retest with a defined invalidation captures the
rebalancing move.
**Null:** retest expectancy ≤ 0 after cost.

**Rules (deterministic):** void = N consecutive bars whose combined range exceeds
`k × ATR(14)` with monotone closes in one direction (declare N=3, k=2.0 up front);
zone = the void's origin; entry on first retest into the zone; **stop** = zone
extreme; **target** = fixed 1×ATR (research-standardized, not optimized).
**Invalidation:** no retest inside H bars (declare H=48), or stop hit.
**Universe / TF:** BTC,ETH,SOL · 5m.
**Cost / PIT / splits / baselines / robustness / promotion / kill:** identical to
`EXP-ARP-001` (shared contract).
**Status:** SPEC'd + PRE-REGISTERED, **NOT RUN**.
