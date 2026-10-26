# EXP-ARP-005 — Pivot-level fade

- source_strategy_id: `STRAT-CAND-019`
- family: level / price-action (reaction)
- mechanism: **level reaction** (fade at a computed level)

**Hypothesis:** the first contact with a standard floor-trader pivot level (P, R1,
S1) from the prior session/day produces a short-term fade.
**Null:** level contact has no expectancy beyond cost.

**Rules (deterministic):** pivots from the previous completed day (P = (H+L+C)/3;
R1 = 2P − L; S1 = 2P − H); **entry** on first touch of R1 (short) or S1 (long)
within the session; **exit** = fixed exit declared as "target = P, stop = 0.5×ATR";
one touch per level per day.
**Invalidation:** stop, target, or session end.
**Universe / TF:** BTC,ETH,SOL · 5m; session = UTC day (crypto is 24/7, so the
"session" is defined explicitly as the UTC calendar day).
**Cost / PIT / splits / baselines / robustness / promotion / kill:** shared contract.
**Note:** the source says "close quickly"; that is replaced by the explicit
target/stop above so no discretionary rule remains.
**Status:** SPEC'd + PRE-REGISTERED, **NOT RUN**.
