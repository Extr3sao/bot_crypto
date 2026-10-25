# WP-EDGE-016 — final report

## What was wrong

100% of the 7081 exits in the WP-EDGE-015 experiments were filled at the open of the very bar whose close decided them. That price had already happened when the decision was taken, so the exit was not executable and the PnL was not admissible. The second defect was the lane's: it carried complete entry/exit pairs, including the realised gross, inside the entry proposal.

## What was repaired

- **Ordering.** Decisions are taken once per closed bar; a rule read off bar *t* fills at the open of bar *t+1*. A position still open at the last bar is **marked**, flagged `is_mark`, and excluded from anything that counts real exits.
- **No future in a proposal.** The lane drives incremental machines that see only an as-of prefix; proposals carry the rule and the signal bar and nothing that happened later.
- **One risk engine.** Entries are approved and sized by the runtime's own `RiskManager.check_signal`, with every close fed back through `record_trade_result` and `sync_open_positions`.
- **One portfolio.** A single 10 000 USDT book across the three symbols, so the position and exposure clamps bind across them; the 015 lane's three books are relabelled as three independent simulations whose balances are not capital.
- **Ambiguity resolved against the position.** When a stop and a target are both touched in one bar the broker's `stop_first` policy decides, and the lane does not override it.
- **Out-of-order bars refused.** The machines raise rather than decide on a bar older than one they have already seen.

## What the numbers say now

| lane | trades | 1x | 2x | 3x |
| --- | --- | --- | --- | --- |
| mean_reversion_vol_liq (restated research) | 947 | -240.86 | -1150.32 | -2059.78 |
| trend_pullback (restated research) | 860 | -1954.84 | -2775.1 | -3595.35 |
| vol_regime_breakout (restated research) | 242 | -187.08 | -418.33 | -649.58 |
| experimental paper lane (USDT) | 146 | -239.7503 | -426.1162 | -612.482 |

The current runtime is flat by design: 0 trades and 0.0 USDT. Nothing in this package promotes a strategy, and the restated verdict is **NO_RESTATED_EDGE_SURVIVES**.

## What could not be established

- the disk guard reports INSUFFICIENT_FREE_SPACE for the declared collection window: no new collector is started
- a scheduled collector needs a governance decision and free space before it exists
- 7/7 trading conflicts with blocks.weekend_trading=false and needs an ADR
- 5 policy fields are declared in config/risk.yaml and read by no runtime component
- the prospective sample is empty, so no strategy can be adopted on it

The honest status is therefore: integrity repaired and independently verified; economics restated and negative after costs; prospective evidence insufficient and its collector blocked by the disk guard. Any further step needs the missing resource or a governance decision, not more code.

## Independent verification

VERIFIED

21/21 injected causal scenarios were caught on the real holdout tapes (CAUSALITY_ADVERSARIAL.json), and the verifier that signs this report imports none of the modules that produced it.
