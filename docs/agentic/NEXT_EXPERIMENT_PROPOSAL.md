# NEXT_EXPERIMENT_PROPOSAL — `EXP-004A`, and why it is a cost measurement rather than a strategy

**Date:** 2026-10-21 · **Status:** `PROPOSED, NOT AUTHORISED` · **Economic executions:** 0
**Identifier checked:** `EXP-004A` → `discover_existing_runs()` returns `[]` (unspent); `EXP-004` also unspent.

---

## 1. The answer to "is there a next experiment?"

**Not one that can be executed today.** The three requirements in the mission — preregistration before
results, data independence, and no retrospective threshold adjustment — cannot all hold for any strategy
experiment in this checkout, for a reason that is arithmetic rather than procedural:

| Requirement | State today | Verdict |
| --- | --- | --- |
| Untouched confirmatory data | **5 prospectively observed days**, 1h bars, BTC/ETH/SOL (2026-10-15/16/17/19/20); 229 of 235 forward days are `DENSE_BUT_BACKFILLED` | **fails** |
| A family not already falsified | 9 families in `NEGATIVE_ALPHA_REGISTRY`; every one whose reopen condition is met-by-effort remains closed | **fails** |
| Gross edge above the toll | best measured **14.80 bps vs 27.31 bps**; five independent measurements at 0.08×–0.67× | **fails** |
| Preregistration can be frozen first | yes, for *any* hypothesis — but a prereg on data that does not exist cannot carry dataset digests (§4) | **partially** |

So the proposal is not "the next strategy". It is the one measurement that can change the arithmetic, using
data that has never been used for an economic decision.

## 2. Which hypothesis the evidence leaves standing

| Candidate | Why it is not the next experiment |
| --- | --- |
| trend / 4h on majors | measured: `lane_a::trend::4h::48`, BH survivor, **14.80 bps vs 27.31** → −12.51 bps/signal |
| 5m mean reversion | measured twice: 003L (−0.84 USDT/close) and 003M (−0.4831 USDT/fill) |
| cross-sectional momentum / reversal | `NEG-A1-03/04`; best gross +15.71 vs 23.56 toll |
| funding / basis carry | `NEG-A1-06`, `G_CARRY_2 FAIL`; reopen needs a **new data window**, not a new idea |
| TSMOM, indicator variants, lead-lag, regime router | `NEG-A1-01/02/08`, `ALPHA-002/003`; 0 BH survivors of 106 variants |
| daily trend / cross-section on alts | `WP-EDGE-07` (−140.30 over 65 trades on a **new** window) and `WP-EDGE-08` (−166.61) |
| **order flow (liquidations / OI / book)** | `NEG-A1-07`: **`DATA_BLOCKED / FORWARD_ONLY`** — the only family whose failure was *data absence*. Reopen requires **PIT HISTORY EXISTS** |

Two survive as *questions*: cost (never measured as a hypothesis — always assumed) and order flow (measured
as blocked, never as economics). Order flow needs a multi-month PIT history that does not exist; cost can be
measured with what is already being collected.

**The strongest remaining testable hypothesis is therefore about the toll, not the signal:**

> At the intended size (500 USDT notional, spot, the fee tier actually reachable), the realised round-trip
> cost is **not** 24.79–27.31 bps; it is ≤ 20 bps, and the gap between that and the frozen model is a
> modelling pessimism, not a market fact.

If true, `EXP-003N`'s surviving cell moves from 0.54× to 0.74× of the toll — still not profitable, but the
barrier becomes a known distance rather than an assumption. If false, the barrier is a *measured* fact and no
further signal work is justified. Either answer is decision-grade, and neither can promote a strategy.

## 3. `EXP-004A` — definition

| Field | Value |
| --- | --- |
| Identifier | `EXP-004A` (unspent, verified against `reports/ai-bots/`) |
| Title | **COST-CONFIRM: measured round-trip cost versus the frozen model, on prospectively observed quotes** |
| Question | Is the realised round-trip cost at 500 USDT ≤ 20 bps, and where in the distribution does it sit relative to the 24.79/27.31 bps the model charges? |
| Assets | BTCUSDT, ETHUSDT, SOLUSDT — spot |
| Instruments | venue `bookTicker` + `depth` (limit 100), plus aggTrade for the traded-spread cross-check |
| Data source | the ST-6 collector (`data/st6/`, 75 of 84 windows at the time of writing) extended to a declared cadence, plus `src/trading_bot/research/forward/collector.py` for the continuous 1m book capture |
| Window | **prospective only**: from `2026-10-22T16:21:20Z` (ST-6 period close) to the declared end, minimum **90 days**; every bar must carry `prospectively_observed: true` |
| Why untouched | `data/st6/` has never been used for an economic decision; no run directory, ledger entry or PnL artefact references it |
| Fee model | `spot_vip0_bnb`, 10 bps taker / 7.5 bps maker per side, read from the frozen schedule, not assumed |
| Slippage model | measured: half-spread from `bookTicker`, impact from `depth` at 500 USDT, no fitted parameter |
| Statistic | median and p90 of *measured* round-trip cost per asset per day; compared to the frozen 24.786 / 27.310 bps |
| Decision rule (frozen now) | **`COST_LOWER`** if median ≤ 20.0 bps **and** p90 ≤ 27.31 bps on all three assets; **`COST_CONFIRMED`** if median > 24.786 bps on any asset; **`INSUFFICIENT_EVIDENCE`** if fewer than 60 prospectively observed days or if coverage < 0.90 |
| What it may authorise | a re-frozen toll for a *future* signal experiment — nothing else |
| What it may not authorise | any strategy, any paper run, any promotion, any live trading, any change to a historical verdict |
| Verifier | a separate program that re-reads the raw window bytes and recomputes the cost distribution; `builder_identity != independent_verifier_identity` is enforced by the gate |
| Proof of independence | every raw window carries its own sha256 and a `prospectively_observed` flag computed from ingest time, not from a backfilled file mtime |

**Why this is not "just another data task".** It has a falsifiable number, a decision rule fixed before the
first window is read, a defined failure mode, and it closes `ECO-1` — the one open defect in `ECONOMIC-001`
that says the cost snapshot is "a few seconds, not regimes".

## 4. The prerequisite the gate cannot yet express

`prereg_gate.evaluate()` requires `raw_sha256` / `normalized_sha256` for every registered dataset. A
preregistration frozen **before** the data exists cannot satisfy that, and lowering the requirement to "hash it
later" is exactly how a holdout stops being a holdout.

The gate therefore needs a declared **two-phase freeze**, and it does not have one today:

1. **Phase 1 — `PROTOCOL_FROZEN`.** Manifest, splits, costs, acceptance and decision rule are committed. The
   registry may declare datasets with `raw_sha256: null` **only** under a new status and a new field
   (`data_capture_not_started: true`), and `authorize` must still refuse.
2. **Phase 2 — `REGISTRY_FROZEN`.** After collection closes and before any measurement, a second commit fills
   the digests. Only then can `authorize` return `0`, and the ledger must record both commit hashes.

Until that exists, `EXP-004A` cannot be authorised by this component — which is the correct behaviour, and is
recorded here rather than worked around by weakening the digest check for everybody.

## 5. Authorisation checklist (all must hold on the day)

- [ ] `EXP-004A` still returns `[]` from `discover_existing_runs()`.
- [ ] Phase 1 commit exists and precedes the first collected window by commit order and by timestamp.
- [ ] Phase 2 commit fills every digest **after** collection closed and **before** any statistic is computed.
- [ ] ≥ 90 prospectively observed days, coverage ≥ 0.90 on all three assets.
- [ ] `builder_identity != independent_verifier_identity`, `execution_mode == OFFLINE_ONLY`.
- [ ] `prior_runs_ledger` completed with `EXP-004A: 0` and the five `EXP-003/EDGE` windows recorded as
      consumed.
- [ ] `prereg_gate --mode authorize` returns **exit 0** — the only legitimate way to start.
- [ ] `ECONOMIC-001` standing unchanged: `LIVE_TRADING=DISABLED`, `TRADES_AUTHORIZED=0`.

## 6. Kill criteria — when to stop instead

- **`COST_CONFIRMED`** → stop signal research on spot majors at this fee tier. The repository's answer becomes
  "no measurable edge is available at 20 bps of round-trip cost", written once, and no further indicator
  search is funded. This is a legitimate outcome, not a failure of the mission.
- **Coverage < 0.90 at day 90** → do not measure around it (that is how `EDGE-04` produced
  `DENSE_BUT_BACKFILLED` days that looked dense and were not prospective).
- **The fee tier cannot be reached at 500 USDT** → the hypothesis was never testable; record `NOT_TESTABLE`
  rather than fitting the model to what is available.
- **Anyone proposes a signal experiment while this is running** → refuse: nothing in this checkout licenses it.

## 7. Second-ranked option, for the record

**Order flow** (`NEG-A1-07`). It is the only honestly *unmeasured* family, and the collector that would
produce it already exists (`src/trading_bot/research/forward/collector.py`, aggTrade + bookTicker with gap
detection on `previous_id + 1`). But a PIT history usable for an economic test is a **six-month** programme at
minimum, the repo currently has **5 prospective days** of 1h bars, and proposing it now would repeat the
mistake of promising a measurement that the data cannot support. It becomes the natural `EXP-004B` *after*
`EXP-004A` answers the cost question — because if the toll is real, order flow has to clear it too.

## 8. What is explicitly **not** proposed

- No re-run of `EXP-003N`, no new cell on its dataset, no reuse of `2026-08-06 → 2026-08-20`.
- No re-parameterisation of a rejected arm ("the same book with a different ATR").
- No paper-trading campaign as a substitute for evidence: paper PnL has already been shown to be
  cost-dominated, and running one would produce a number that looks like evidence and is not.
- No promotion, no live trading, no capital.
