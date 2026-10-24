# RISK CONTRACT DELTA — what the slice changes about money

**Sign-off owed by: risk-manager.** This document exists because G1 was described in
`TAP-SUPERVISOR-INTEGRATION-001` as "`risk/manager.py` breaks two inherited tests". That
description is wrong, and the correction matters more than the fix:

> On **unmodified `main`** (`e67194e7`), `pytest tests/unit/paper tests/unit/risk` is
> already **6 failed / 170 passed**. The two `test_futures_independent_verifier.py`
> failures are not caused by `manager.py`, by the lane, or by this migration: they are
> caused by stale hashes in `data/rfc048/PROVENANCE.json`, measured below.

## 1. Baseline, measured twice

| Tree | `pytest tests/unit/paper tests/unit/risk` |
| --- | --- |
| `main` `e67194e7`, clean worktree | **6 failed, 170 passed** (`evidence/PYTEST_paper_risk_main_baseline.log`) |
| `integ/supervisor-002` (this branch) | **2 failed, 220 passed** (`evidence/PYTEST_paper_risk_after_tests.log`) |

The 2 remaining failures are a subset of main's 6. **No test that passes on `main` fails
here**, and 50 tests that were red are green.

## 2. The two pre-existing failures (not this slice's)

`bracket_provenance` fails for 28 decisions because `INSTRUMENTS.json` and
`PROVENANCE.json` record `sha256=07c298…`, `bytes=4248` for
`data/rfc048/raw/binance_usdm_leverage_brackets_btcusdt.json`, while the committed file is
`f38d9d…`, `4123` bytes. Re-running `scripts/rfc048_derive_instruments.py` reproduces the
*content* exactly (12 brackets identical; `INSTRUMENTS.json` differs only in 3 hash
leaves) and records the hash of the file that is actually committed. The same drift
affects **six of the seven** raw sources (`depth 9920→9112`, `exchange_info
1961235→1881990`, …; only the ESMA HTML still matches), so this is a
delivery-provenance defect of RFC-048, not a risk defect:

* status: **OPEN, PRE-EXISTING ON `main`**;
* not fixed here: rewriting the recorded hashes to match the files would bless a
  provenance chain that never existed;
* evidence: `evidence/MAIN_rfc048_provenance_drift.txt`.

## 3. What the migrated code changes, exhaustively

Nothing below edits a threshold, a notional cap, an exposure cap or a leverage. The
limits are the same objects, read from the same policy fields.

### Delta A — a signal with no stop is refused by the broker (was: default 1 %/2 %)

`paper/broker.py` now rejects `stop_loss_pct is None` instead of inventing a protective
distance. **Tightening.** A position can no longer exist with a stop the strategy did not
choose. Pinned by the lane's `test_broker_identity.py` / `test_paper_recovery.py` fixtures,
which now declare their stops explicitly.

### Delta B — an unusable stop is refused, not clamped (was: clamp to the band)

`risk/manager.py::resolve_stop` rejects non-finite, `<= 0`, `>= 100 %` stops and
`<= 0`/`>= 100 %` targets. `main` did `signal.stop_loss_pct or default` (so `0.0` silently
became the policy default) and clamped out-of-band values. **Tightening.** A 150 % stop
stop is no longer "clamped into" a trade; the trade does not happen.
Pinned by `tests/unit/risk/test_risk_contract_014.py`.

### Delta C — a stop shorter than its round trip can be refused (was: no concept)

`cost_bps_for` + `stop_cost_policy` (`OFF` default, `REPORT`, `REJECT`). `OFF` preserves
`main`'s behaviour exactly and does not even measure. **Opt-in tightening.**

### Delta D — the weekly loss veto lifts at UTC Monday 00:00 (was: never)

`main` accumulated `weekly_pnl` and **nothing ever reset it** — its own docstring said the
reset was deliberately avoided, so one bad week vetoed every signal for the rest of the
process. The slice rolls the window at the UTC Monday boundary, driven by the injectable
clock. **This is the only change that loosens anything**: across a week boundary a veto
that `main` would have kept is lifted.

* Named defect: `WP-EDGE-017F/P0.1` in the lane's own test docstring.
* Within a week, behaviour is identical.
* Threshold unchanged (`max_weekly_loss_pct`, read from `Risk`).
* A backwards-moving clock never clears the week.
* Pinned by `test_risk_contract_014.py` (boundary, mid-week, backwards clock, state
  round-trip).

**This is the item that needs your signature.** The integration does not edit it, does
not hide it, and does not enable it conditionally: it arrives with the lane's
`manager.py`. Rejecting it means either (a) accepting a supervisor that stops trading
forever after one bad week, or (b) a separate patch that reverts `roll_week` — which the
supervisor's long sessions would then need re-authorized.

## 4. Parity evidence (no silent arithmetic drift)

`test_sizing_is_identical_to_main_for_every_accepted_stop` compares the migrated sizing
against a literal copy of `main`'s formula for stops `{0.1 … 5.0}` × prices
`{0.5, 100, 84 000}`: notional, quantity, stop, target and risk amount are equal. The
notional ceiling binds in the same place (`MAX_ORDER_NOTIONAL_CLAMP`).

## 5. What is *not* claimed

* No statement about profitability, sizing quality or strategy behaviour.
* No statement that the weekly roll is *desirable* — only that it is deliberate,
  tested and disclosed.
* `data/rfc048` remains red: 2 failures, pre-existing, with root cause above.
