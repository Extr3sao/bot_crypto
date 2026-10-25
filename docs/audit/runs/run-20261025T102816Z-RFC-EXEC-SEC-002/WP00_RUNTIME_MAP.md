# WP-00 — read-only audit (RFC-TAP-EXEC-SEC-002)

Run: `run-20261025T102816Z-RFC-EXEC-SEC-002`
Captured: 2026-10-25T10:31:58Z
No source file was modified before this document was written.

## 1. Authoritative runtime

| Claim | Value | How it was checked |
|---|---|---|
| Branch under work | `audit/mt0004-negative-controls` | `git rev-parse --abbrev-ref HEAD` |
| HEAD at start | `43e1ce2c0308e4df341bc8232d402f096cbf53ee` | `git rev-parse HEAD` |
| Work tree at start | clean (only this run's documents untracked) | `git status --porcelain` |
| P0 export | `82e8b3ac13ebc9abe0a43c78174200d3db145764` | `git rev-parse` |
| P0 clean tree | `1b4e1896af3e02084813ab3d3e589e44db94be29` | `git rev-parse` |
| Ancestry | `82e8b3ac` → `1b4e1896` → `43e1ce2c` | `git merge-base --is-ancestor` (both true) |

The three commits the RFC declares are therefore a chain, not siblings: the
verified export is an ancestor of the reported clean tree, which is an ancestor
of the current HEAD. The RFC's "verify the real relation" step is satisfied.

Module under test: `src/trading_bot/app.py` (1809 lines at baseline). Gate:
`src/trading_bot/execution/live_gate.py` (410 lines). Stop:
`src/trading_bot/autonomous/hot_stop.py` (566 lines). Futures adapter:
`src/trading_bot/market_data/bitunix_futures.py` (621 lines).

Baseline SHA-256 is in `baseline/hashes-before.txt`; the full git state is in
`baseline/git-state.txt`.

## 2. Baseline tests (before any edit)

Command, with `pipefail` so a filtered pipeline cannot hide a failure:

```
uv run --frozen pytest tests/unit/test_live_gate_enforcement.py \
  tests/unit/test_live_hot_stop_coverage.py \
  tests/unit/test_app_cli_contract.py \
  tests/unit/test_app_demo.py -q
```

Result: **113 passed in 108.00 s**, exit 0. Log:
`baseline/pytest-baseline.txt`.

`uv run` without `--frozen` rewrote `uv.lock` during this baseline (it added
the matplotlib dependency tree that the committed lock omitted). That write was
incidental, not part of this RFC; it was reverted with `git checkout -- uv.lock`
and every later command uses `--frozen`.

## 3. Entrypoints and sinks actually reachable

There are **seven** calls that leave the process toward a broker. The count is
the one the G-3/P0 structural tests pin (`LIVE_SINKS`, seven boundary sites).

| # | CLI entrypoint | Code path | Broker sink | Payload shape |
|---|---|---|---|---|
| 1 | `run --auto-trade --market-kind futures` | `_maybe_execute_live_futures_trade` | `BitunixFuturesClient.place_order(trade_side="OPEN")` | symbol, side, qty, `tradeSide=OPEN`, `reduceOnly=false`, TP/SL |
| 2 | same | `_close_stale_futures_positions` | `BitunixFuturesClient.flash_close_position(position_id)` | `{positionId}` only |
| 3 | `run --auto-trade --market-kind spot` | `_maybe_execute_live_trade` | `MultiExchangeConnector.create_order(side="buy")` | connector-normalised spot order |
| 4 | `place-order --market-kind futures` | `_cmd_place_order` | `BitunixFuturesClient.place_order` | symbol, side, qty, `tradeSide`, `reduceOnly`, optional `positionId` |
| 5 | `place-order --market-kind spot` | `_cmd_place_order` | `BitunixSpotClient.place_spot_order` | symbol, side, qty, price |
| 6 | `close-position` | `_cmd_close_position` | `BitunixFuturesClient.flash_close_position` | `{positionId}` only |
| 7 | `set-tpsl` | `_cmd_set_tpsl` | `BitunixFuturesClient.place_position_tpsl` | symbol, `positionId`, tp/sl price and qty; **no** `reduceOnly`, **no** `tradeSide` |

No other module in `src/` imports `LiveTradingGate`; `app.py` is the only
consumer, and `_evaluate_live_gate` is its only caller.

## 4. Current `--confirm-live` contract

- `place-order` declares `--confirm-live` and refuses at `_cmd_place_order` when
  it is absent: `exit 2`, stderr, before `load_settings`.
- `run` does **not** declare the flag. `run --mode live --auto-trade` can place
  orders with no per-invocation consent (DEF-P0-04).
- `close-position` and `set-tpsl` have no flag and none is expected: they are
  operator repair commands.
- The flag is checked only in the CLI. Nothing at the sink re-reads it, so a
  direct call to `_live_order_boundary` cannot see whether the invocation was
  confirmed.

## 5. Current classification: a caller-supplied boolean

`_live_order_boundary(gate, *, opens_risk: bool, settings, run_id="")` yields
`True` immediately when `opens_risk` is `False`. The value is decided at each
call site:

| Call site | `opens_risk` today | Evidence behind it |
|---|---|---|
| `_maybe_execute_live_trade` (spot buy) | `True` | literal |
| `_close_stale_futures_positions` | `False` | literal + comment |
| `_maybe_execute_live_futures_trade` (OPEN) | `True` | literal |
| `_cmd_place_order` futures | `not (reduce_only or trade_side == "CLOSE")` | CLI flags |
| `_cmd_place_order` spot | `side == "buy"` | CLI side |
| `_cmd_close_position` | `False` | command name |
| `_cmd_set_tpsl` | `False` | command name |

`place-order --market-kind futures --side sell --trade-side OPEN` (a short
entry) is classified as opening because `trade_side` is `OPEN`, but
`--trade-side CLOSE` alone (without `--reduce-only`) is classified as a
reduction and skips the gate. `sell` on spot skips the gate. Neither decision
reads the position the order would act on.

## 6. What the adapter can actually prove

- **Futures `place_order`** always emits both `tradeSide` and
  `reduceOnly` (`bitunix_futures.py:280-291` at baseline), so a
  `tradeSide=CLOSE, reduceOnly=true` payload is a venue-enforced reduction
  primitive — *if* the caller supplied both and the final payload still carries
  them.
- **`flash_close_position`** emits only `{"positionId": ...}`. The endpoint
  closes the identified position; there is no side or size field that could be
  mutated into an opening order.
- **`place_position_tpsl`** has no `reduceOnly` and no side. `get_pending_positions`
  does not return the current TP/SL levels, so no code can prove that a TP/SL
  change tightens rather than removes protection. TP/SL is therefore not
  provably monotonic with this contract.
- **Spot** has no reduce-only flag and no position object. A spot `sell` can
  only sell held base inventory, but there is no broker-enforced primitive that
  says so, and the balance read is not part of the order payload. Under the RFC
  it cannot be proven, so it must not be exempt.

## 7. Gaps recorded before editing

| ID | Gap | Requirement |
|---|---|---|
| DEF-EXEC-001 | `run --auto-trade` has no `--confirm-live`; a live dispatch needs no per-invocation consent. | REQ-01 |
| DEF-EXEC-002 | The sink trusts `approved=True` derived from CLI flags; it never sees confirmation, intent or position. | REQ-02 |
| DEF-EXEC-003 | Reduction exemption is a caller boolean. `--trade-side CLOSE` without `--reduce-only`, `sell`, `close-position` and `set-tpsl` are all exempt by name/side. | REQ-03 |
| DEF-EXEC-004 | No payload-level revalidation: the exemption is decided before the adapter builds the wire payload, so a dropped `reduceOnly` would not be noticed. | REQ-03 / T07 |
| DEF-EXEC-005 | `set-tpsl` is exempt although moving or removing protection can increase risk. | REQ-04 |
| DEF-EXEC-006 | No per-decision authorization record; there is no trace tying run, entrypoint, rule and gate verdict together. | REQ-05 |

## 8. Frozen decisions for WP-01/02

1. `run --auto-trade` in `live` **or** `shadow_live` requires `--confirm-live`.
   `shadow_live` is included because the order functions key off
   `settings.runtime.mode`, not the CLI mode: a `shadow_live` process pointed at
   a live `.env` can dispatch. Paper/demo are not blocked by the flag.
2. `OrderCategory` is derived from `(primitive, tradeSide, reduceOnly,
   positionId, position state, venue capability)`, never from the command name.
3. Only two shapes can be `PROVEN_REDUCTION`:
   - futures `place_order` with `tradeSide=CLOSE`, `reduceOnly=true`, an open
     one-way position with the same id and symbol, the opposite side, and
     `0 < qty <= position.qty`;
   - `flash_close_position` for an open, fresh position.
4. Spot sells and TP/SL changes are `UNKNOWN`: they go through confirmation,
   the hot stop and all ten gate checks, exactly like an opening order.
5. A proven reduction is allowed while stopped — flattening must not be trapped
   (G-3), and it is exactly what the stop is for.
6. The final wire payload is revalidated by a guard invoked by the adapter
   immediately before the HTTP request. A reduction that loses `reduceOnly`, or
   whose payload gains a side/qty, is refused with zero broker calls.
7. `hot_stop.py` and `LiveTradingGate` are not modified.
