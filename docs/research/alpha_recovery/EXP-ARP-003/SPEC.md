# EXP-ARP-003 — Cross-sectional relative-strength divergence

- source_strategy_id: `STRAT-CAND-012` (SMT relative strength)
- family: cross-sectional / relative value
- mechanism: **cross-instrument** (the only such mechanism in the selection)

**Hypothesis:** when two correlated instruments (BTC, ETH — and SOL vs BTC) make
divergent extremes at the same time, the laggard resolves toward the leader.
**Null:** the divergence has no directional information beyond the common factor.

**Rules (deterministic):** over a declared window (W=24 bars), flag divergence when
instrument A makes a higher high while B does not (or symmetric); **direction** =
toward A (the leader); entry at the close of the confirming bar; **stop** = the
diverge bar extreme; **target** = fixed 1×ATR.
**Invalidation:** stop, target, or window expiry.
**Universe / TF:** (BTC,ETH) and (SOL,BTC) pairs · 5m.
**Cost / PIT:** shared contract; the pair must be sampled at the same closed bar
(`data_time <= decision_time` for BOTH legs).
**Splits / baselines / robustness / promotion / kill:** shared contract; extra
baseline = "campaign beta" (both legs held, no divergence) to separate the common factor.
**Status:** SPEC'd + PRE-REGISTERED, **NOT RUN**.
