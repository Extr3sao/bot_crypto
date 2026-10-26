# PAIR_ACCOUNTING_CONTRACT

Implemented in `src/trading_bot/research/pair/{ledger,metrics,verifier}.py`.

## Ledger entry (per closed pair)

`PairLedgerEntry` stores the raw leg fields **and** the two derived identities, so a
mutation or a fabricated aggregate is detected on construction:

```
long_gross_pnl  = (long_exit  - long_entry ) * long_qty
short_gross_pnl = (short_entry - short_exit) * short_qty     # short_qty is a positive magnitude
pair_gross_pnl  = long_gross_pnl + short_gross_pnl
pair_net_pnl    = pair_gross_pnl - long_cost - short_cost - borrow - funding + basis
gross_exposure  = long_qty*long_entry + short_qty*short_entry
net_exposure    = long_qty*long_entry - short_qty*short_entry
```

`pair_gross_pnl` and `pair_net_pnl` are **stored** fields, re-checked in
`__post_init__`; they are not silently recomputed properties.

`PairLedger.append` refuses any entry that is not `BOTH_FILLED`. Aggregates use
`math.fsum`.

## Portfolio state (§19)

`PortfolioState` exposes every required field explicitly:

`initial_capital, cash, long_notional, short_notional, gross_exposure, net_exposure,
realized_pnl (gross), unrealized_pnl, costs, net_pnl, equity`.

```
equity = initial_capital + realized_pnl(gross) + unrealized_pnl - costs
```

## True equity metrics (§32)

`metrics.equity_metrics` builds the equity curve
`equity_t = initial_capital + Σ pair_net_pnl` and reports `equity_return` and
`max_drawdown` as the peak-to-trough decline **of that equity curve**.

The ambiguous historical research metric `max_drawdown_bps` (a drawdown of a
*reference notional*) is deliberately **not** reused. A return/drawdown is reported
only when the capital model makes it valid (`initial_capital > 0`); otherwise the
field is `None`, never a fabricated `0`.

Also reported: `profit_factor`, `sharpe_per_period`, `sortino_per_period`,
`turnover_ratio`, `mean_gross_exposure`, `mean_net_exposure`, `mean_beta_before`,
`mean_beta_after`, `mean_holding_days`.

## Builder ≠ verifier (§40)

`verifier.verify_ledger` takes the **raw leg fields** only, ignores every stored
aggregate and every `PairLedger` summary, recomputes long/short PnL, transaction,
borrow, funding and basis costs, gross/net exposure, beta and final equity from first
principles, and reports the residual per field. Any residual above `1e-9` is a
verification failure.

## Reconciliation residuals (E2E fixture)

```
pnl_reconciliation_residual    = 0.0
equity_reconciliation_residual = 1.8189894035458565e-12   (float assoc. only)
```
