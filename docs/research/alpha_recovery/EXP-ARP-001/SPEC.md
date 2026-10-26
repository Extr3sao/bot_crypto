# EXP-ARP-001 — MA20/40/200 pullback continuation, source-faithful exit

- source_strategy_id: `STRAT-CAND-001` (SRC-BOOK-001 pp.99–105)
- family: trend / continuation
- reference: `docs/research/experiment_specs/EXP-CAND-001-SOURCE-FAITHFUL-EXIT.md`

**Hypothesis:** in an established uptrend, a pullback to the 20/40 MA that resumes
(the 20 over 40 over 200 stack) continues to a measured-move target.
**Null:** the continuation expectancy is ≤ 0 after the runtime cost.

**Rules (deterministic):** SMA20/40/200 on closed bars; trend = SMA20 > SMA40 >
SMA200; entry on a strict break of the prior pullback candle's high after price
touches SMA20/40; **stop and target from the source geometry** (swing stop +
measured move), NOT the harness 0.75 % TP.
**Invalidation:** stop hit, source target hit, or opposite stack.
**Universe / TF:** BTC,ETH,SOL · 5m (15m robustness axis).
**Cost:** runtime `COST_MODEL_V3` 23.25 bps RT.
**PIT:** closed-bar slice; no HTF read before its own close.
**DEV** W1–W4 · **VALIDATION** W5–W6 · **OOS_LOCK** W7 (sealed).
**Baselines:** NO_TRADE, buy-and-hold, runtime `trend`/`ema_crossover`, naive random entry.
**Robustness:** MA lengths 18/22 around 20/40/200; cost 1.0–2.0×; W-shift; regime/asset split.
**Promotion:** DEV gross ≥ 25 bps/trade, VAL net > 0, n ≥ 100, PIT clean.
**Kill:** DEV gross < 25 bps/trade, or n < 100, or PIT fail, or VAL PF ≤ 1, or single-point.
**Status:** SPEC'd + PRE-REGISTERED, **NOT RUN**.
