# PAIR_EXECUTION_CONTRACT

Research/PAPER contract for executing one two-leg (long/short) trade.
Implemented in `src/trading_bot/research/pair/{instruments,proposal,simulator}.py`.

## Instrument contract (§7/§8)

Every leg declares: `instrument_id, asset, venue, instrument_type, side,
quote_currency, contract_multiplier, price_increment, quantity_increment,
minimum_notional, shortable, borrow_required, funding_applicable, basis_applicable,
data_source, cost_source`.

`require_same_instrument(frozen, candidate)` refuses a substitution: the *asset* and
*side* may differ between the two legs, the **instrument class and venue may not**.
Substituting a perpetual for a frozen margin-spot short is an `InstrumentSubstitutionError`,
not a modelling choice.

Frozen EXP-ARP-023 instruments:

| leg | instrument | type | shortable | borrow_required | cost_source |
| --- | --- | --- | --- | --- | --- |
| long | `BINANCE-SPOT-USDT-LONG` | SPOT | n/a | false | `COST_MODEL_V3/BINANCE_SPOT_STANDARD_TAKER` |
| short | `BINANCE-MARGIN-USDT-SHORT` | MARGIN_SPOT | true | true | `NONE` (EXTERNAL_DATA_REQUIRED) |

A shortable short without a declared borrow requirement is rejected at construction.

## Execution status (only legal states)

`PENDING`, `LONG_FILLED_SHORT_PENDING`, `SHORT_FILLED_LONG_PENDING`, `PARTIAL_LONG`,
`PARTIAL_SHORT`, `BOTH_FILLED`, `PAIR_FAILED`. `is_filled` is true **only** for
`BOTH_FILLED`.

## Determinism

The simulator is a pure function of `(plan, ref prices, FillConfig, ShortLegCost,
holding_days, horizon_minutes, beta_before, beta_after)`. No clock, no RNG. Two runs
over identical inputs produce byte-identical `as_dict()` output.

## Fill model

Fills are modelled at the next available open (PIT), with explicit per-leg slippage.
A buy (long entry / short exit) fills worse-high; a sell (short entry / long exit)
fills worse-low. Each leg has an independent fill ratio and availability flag.

## Temporary exposure (§25)

While the two legs are out of sync the book carries an interim one-leg exposure,
modelled explicitly rather than assuming simultaneity:

- long first (`long_delay < short_delay`) ⇒ `temporary_net = +long_notional`;
- short first ⇒ `temporary_net = -short_notional`;
- simultaneous ⇒ both legs present (`net ≈ 0`, `gross = long + short`);
- partial fill ⇒ the filled fraction only, and the pair is fail-closed.

`temporary_gross_exposure`, `temporary_net_exposure` and `temporary_beta_exposure` are
all reported together with `leg_delay_ms`.

## Failure semantics (§28)

`FailurePolicy` ∈ {`ABORT_PAIR`, `CLOSE_FILLED_LEG`, `RETRY_WITHIN_TIMEOUT`}. A pair is
`BOTH_FILLED` only when both legs satisfy the contract; anything else is
`PAIR_FAILED`/`*_PENDING` with `fail_closed = True` and **no** ledger entry.
