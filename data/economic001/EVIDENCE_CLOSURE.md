# ECONOMIC-001 — COST EVIDENCE CLOSURE & EXECUTION REALITY

generated_at_utc = 2026-10-08T15:39:55Z (computed, not authored)
current_head = 8e0a4b5f805d93eedd5218b10657a37652c0fb5d
false_success = 0

> This gate adds no strategy and opens no campaign. It consolidates the economic evidence,
> re-derives the horizons at a resolution that can certify them, separates known fees from
> estimated execution costs, and measures the parts of execution reality that can be measured
> without sending an order.

## 1. Evidence preservation

- delivery commit: `0f8292651ce3cd3ae113c0229de1b7487a00f472` — feat(research): price a 200 USDT cost profile and bound it by horizon
- files in that commit: **6** (the six economic deliverables, plus 0 other paths)
- foreign files left in the working tree untouched: **35**
- report bytes equal the hash the verifier recorded: **True**
- non-circularity (the named commit must not contain this artefact): **True**

| file | working tree sha256 | git blob sha256 |
| --- | --- | --- |
| `scripts/rfc046_economic_gate.py` | `a79c7bde12224be5…` | `a79c7bde12224be5…` |
| `scripts/rfc046_economic_gate_verify.py` | `621a99e832f5fa83…` | `621a99e832f5fa83…` |
| `tests/unit/research/test_rfc046_economic_gate.py` | `dc74af62c347d372…` | `dc74af62c347d372…` |
| `data/rfc046/ECONOMIC_FEASIBILITY.json` | `35a0a0f28b7fca29…` | `0a2ac9ca7d03d215…` |
| `data/rfc046/ECONOMIC_FEASIBILITY.md` | `4b9de3fdeb85ba34…` | `55cbbcc63a593d96…` |
| `data/rfc046/ECONOMIC_FEASIBILITY_VERIFICATION.json` | `ecf21cd948c617c5…` | `e75fbad18107ce1f…` |

the working tree carries CRLF for the report artefacts and LF for the scripts; git stores LF.  Both hashes are recorded: working_tree_sha256 is what a reader of this checkout verifies, git_blob_sha256 is what the repository stores.

## 2. Horizon verification (native resolution per horizon)

each horizon is measured on the *native series of that horizon* (the 15-minute file for 15m, the hourly file for the multi-hour horizons); no short horizon is certified from a longer bar.  The window convention differs from the already-verified report on purpose: aligned, shifted and exhaustive windows are all computed and compared.

| horizon | series | bars/window | windows | median bps | shifted | exhaustive | reported bps | delta |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 5m | 5m bars | 1 | 848433 | 8.588957 | 8.588957 | 8.588957 | 8.588957 | 0.00% |
| 15m | 15m bars | 1 | 282808 | 15.08965 | 15.089515 | 15.08965 | 15.08965 | 0.00% |
| 1h | 1h bars | 1 | 70700 | 29.381129 | 29.380563 | 29.381129 | 29.381129 | 0.00% |
| 4h | 1h bars | 4 | 17672 | 60.466783 | 60.103563 | 59.763016 | 60.466783 | 0.00% |
| 8h | 1h bars | 8 | 8836 | 89.265721 | 86.720039 | 88.981485 | 89.265721 | 0.00% |
| 24h | 1h bars | 24 | 2944 | 164.801314 | 166.359931 | 169.211848 | 164.801314 | 0.00% |
| 72h | 1h bars | 72 | 980 | 309.317526 | 285.843064 | 306.642462 | 309.317526 | 0.00% |
| 168h | 1h bars | 168 | 420 | 496.629154 | 401.325706 | 460.34763 | 496.629154 | 0.00% |

All horizons certifiable at their own resolution: **True**; all agree with the already-verified report within 0.00%: **True**; monotonic and gapless: **True**.

Windows are disjoint by construction at every horizon (step equals the window length, so no two windows share a bar) and the count is the number of disjoint windows the series admits per asset.  The shifted and exhaustive conventions are reported beside the aligned one as a robustness check, not as the primary measurement.  The agreement with the already-verified report is *exact* rather than approximate, and that is information: a coarser bar opens where its first finer bar opens, so the aligned native window compares the same two prices as the report's k-bar window on the 5-minute series — the one-timeline identity re-checked in the next table, not a coincidence.

### Series integrity and one timeline

| series | bars | gaps | duplicates | covers | aligned to UTC grid |
| --- | --- | --- | --- | --- | --- |
| 5m | 212109 | 0 | 0 | 2024-10-01T00:00:00Z → 2026-10-07T11:40:00Z | True |
| 15m | 70703 | 0 | 0 | 2024-10-01T00:00:00Z → 2026-10-07T11:30:00Z | True |
| 1h | 17676 | 0 | 0 | 2024-10-01T00:00:00Z → 2026-10-07T11:00:00Z | True |

The coarser series must be the exact aggregate of the finer one (open where the first fine bar opens, close where the last one closes). Assets with a mismatch: **none**.

## 3. Cost-model verification

`COST_MODEL_V3` reused, not rebuilt (`docs\COST_MODEL_V3.json`, `2f0e62d2408e6cc5…`).

| component | bps | class | source |
| --- | --- | --- | --- |
| exchange_fee_entry | 10.0 | KNOWN | SRC-01 |
| exchange_fee_exit | 10.0 | KNOWN | SRC-01 |
| spread | 1.0 | ESTIMATED | SRC-07 |
| slippage | 2.632456 | ESTIMATED | MODEL-V3 |
| market_impact | 0.158114 | ESTIMATED | MODEL-V3 |

Known exchange fees: **20.0 bps**; estimated execution terms: **3.79057 bps** (84.1% of the toll is the published schedule).

- historical evaluation (the rejected strategies): **23.7906 bps**
- posterior evaluation at 200 USDT: **23.353553391 bps**
- rejected candidates recomputed: **False** — the 23.353553 bps figure is a *posterior* economic evaluation at the account size we actually hold; the rejected strategies were judged against the frozen 23.7906 bps and must not be recalculated against a smaller toll
- maker path: 41.25 bps, admissible: **False**

Independent recomputation from the frozen constants: 23.790569415 bps at 1,000 USD and 23.353553391 bps at 200 USDT (stressed 1.5x: 35.030330086 and 35.685854123 bps); frozen record of the historical toll: 23.7906 bps; library cross-check ran: **True**.

## 4. Read-only execution reality

Source `data\economic001\READ_ONLY_SNAPSHOT.json` (`30b9817039843502…`), 5 rounds, 30 requests, 32.36s, orders sent **0**, credentials used **0**.

| symbol | median spread bps | min | max | round-trip spread cost bps | vs modelled 1.0 | quote changes |
| --- | --- | --- | --- | --- | --- | --- |
| BTCUSDT | 0.001211 | 0.001211 | 0.001211 | 0.001211 | MODEL_CONSERVATIVE | 4/4 |
| ETHUSDT | 0.03955 | 0.039541 | 0.039557 | 0.03955 | MODEL_CONSERVATIVE | 4/4 |
| SOLUSDT | 0.89075 | 0.890353 | 0.890829 | 0.89075 | MODEL_CONSERVATIVE | 3/4 |
| XRPUSDT | 0.713445 | 0.71319 | 0.713445 | 0.713445 | MODEL_CONSERVATIVE | 1/4 |

Pooled median spread over the four instruments: **0.376374 bps** against a modelled 1.0 bps (MODEL_CONSERVATIVE); the widest single observation of any instrument was **0.890829 bps** (MODEL_CONSERVATIVE even then, on SOLUSDT). the model's spread term is the round-trip cost (2 legs x half-spread), which equals the full bid/ask spread, so the comparison against the measured full spread is like for like. one bounded window of a few seconds across four instruments is a spot reading, not a regime: it cannot certify a past period and does not replace a forward campaign.

Observation latency (round trip of the observation path): bookTicker median 276.084 ms, depth median 276.698 ms, time median 288.011 ms. Clock skew: -255.412 ms — local clock minus venue clock after removing half the round trip; every timestamp in this programme is therefore trustworthy to about a third of a second, which matters for latency reasoning and for nothing else.

### Depth-based impact estimate (taker walk, one instant)

| symbol | top level notional USDT | order size | buy cost bps | sell cost bps | levels consumed (buy) |
| --- | --- | --- | --- | --- | --- |
| BTCUSDT | 48555.52 | 25 USDT | 0.000000 | 0.000000 | 1 |
| BTCUSDT | 48555.52 | 50 USDT | 0.000000 | 0.000000 | 1 |
| BTCUSDT | 48555.52 | 100 USDT | 0.000000 | 0.000000 | 1 |
| BTCUSDT | 48555.52 | 200 USDT | 0.000000 | 0.000000 | 1 |
| BTCUSDT | 48555.52 | 500 USDT | 0.000000 | 0.000000 | 1 |
| BTCUSDT | 48555.52 | 2000 USDT | 0.000000 | 0.000000 | 1 |
| BTCUSDT | 48555.52 | 20000 USDT | 0.000000 | 0.000000 | 1 |
| ETHUSDT | 43608.81 | 25 USDT | 0.000000 | 0.000000 | 1 |
| ETHUSDT | 43608.81 | 50 USDT | 0.000000 | 0.000000 | 1 |
| ETHUSDT | 43608.81 | 100 USDT | 0.000000 | 0.000000 | 1 |
| ETHUSDT | 43608.81 | 200 USDT | 0.000000 | 0.000000 | 1 |
| ETHUSDT | 43608.81 | 500 USDT | 0.000000 | 0.000000 | 1 |
| ETHUSDT | 43608.81 | 2000 USDT | 0.000000 | 0.000000 | 1 |
| ETHUSDT | 43608.81 | 20000 USDT | 0.000000 | 0.000000 | 1 |
| SOLUSDT | 18007.37 | 25 USDT | 0.000000 | 0.000000 | 1 |
| SOLUSDT | 18007.37 | 50 USDT | 0.000000 | 0.000000 | 1 |
| SOLUSDT | 18007.37 | 100 USDT | 0.000000 | 0.000000 | 1 |
| SOLUSDT | 18007.37 | 200 USDT | 0.000000 | 0.000000 | 1 |
| SOLUSDT | 18007.37 | 500 USDT | 0.000000 | 0.000000 | 1 |
| SOLUSDT | 18007.37 | 2000 USDT | 0.000000 | 0.000000 | 1 |
| SOLUSDT | 18007.37 | 20000 USDT | 0.169344 | 0.000000 | 3 |
| XRPUSDT | 28077.79 | 25 USDT | 0.000000 | 0.000000 | 1 |
| XRPUSDT | 28077.79 | 50 USDT | 0.000000 | 0.000000 | 1 |
| XRPUSDT | 28077.79 | 100 USDT | 0.000000 | 0.000000 | 1 |
| XRPUSDT | 28077.79 | 200 USDT | 0.000000 | 0.000000 | 1 |
| XRPUSDT | 28077.79 | 500 USDT | 0.000000 | 0.000000 | 1 |
| XRPUSDT | 28077.79 | 2000 USDT | 0.000000 | 0.000000 | 1 |
| XRPUSDT | 28077.79 | 20000 USDT | 0.000000 | 0.000000 | 1 |

static L2 depth walk at the sampled instant: the market-order cost a taker of that size would face *if the book stayed still*.  The largest measured walk across the four instruments and both sides is 0.000000 bps at the account size and 0.169344 bps at a hundred times the account, i.e. the book absorbs our size inside its best price.  It is a snapshot estimate, not realised slippage: no order was sent and no fill was observed.

Measured now: live best bid/ask spread, observation-path latency, clock skew, depth available per side, depth-based impact estimate per order size. Still estimated: base slippage as a modelling constant: the measured depth walk at account scale is inside one tick, so this term is a conservative penalty rather than a depth effect, volatility regime scaling, maker adverse selection and fill probability. Unknown and stated: maker queue position, fill probability, realised slippage, fill quality / price improvement, historical spread for any past period (no endpoint exists).

Realised slippage measured: **False**; fill quality measured: **False**; a simulator was used as a measurement: **False**.

### Forward windows collected since the gate ran (ECO-1, partially closed)

Instrument `scripts/cost_drift_monitor.py` — `data\economic001\COST_DRIFT_HISTORY.jsonl` (`3f920db0d89e6236…`), judged in `data\economic001\COST_DRIFT_STATUS.json`. Verdict **INSUFFICIENT_EVIDENCE** (provisional) over **2** window(s); the assumption holds in every window so far: **True**.

| window | provenance | collected | pooled median spread bps | worst spread bps | walk at 200 USDT bps | depth covers | raw sha256 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 20261008T144202Z | ECONOMIC-001 read-only probe (5 rounds, 30 requests, 32.36 s) | 2026-10-08T14:42:02.940539Z | 0.376374 | 0.890829 | 0.0 | True | `30b981703984…` |
| 20261008T153205Z | cost_drift_monitor | 2026-10-08T15:32:05Z | 0.433917 | 0.918147 | 0.0 | True | `48e753ffee2f…` |

2 forward window(s) collected without a key, a signature or an order; the verdict is INSUFFICIENT_EVIDENCE (provisional: the declared minimum is not reached).  The comparison is against the frozen model's own terms: 1.0 bps of round-trip spread and 0.25 bps of base impact.  This is forward evidence about the assumption, not about any edge: the modelled spread is the conservative case in every window so far, which clears the assumption without validating any strategy.

## 5. Economic decision

Rule: movement margin is sufficient at a horizon when the measured median absolute move is at least 5x the toll the strategy would pay to trade it.

| family | horizon | median bps | x frozen toll | x posterior toll | margin sufficient |
| --- | --- | --- | --- | --- | --- |
| scalping | 5m | 8.588957 | 0.361023 | 0.367779 | False |
| intraday | 1h | 29.381129 | 1.234989 | 1.258101 | False |
| mean_reversion | 4h | 60.466783 | 2.541625 | 2.58919 | False |
| momentum | 24h | 164.801314 | 6.927161 | 7.056798 | True |
| swing_trading | 72h | 309.317526 | 13.00167 | 13.244988 | True |
| trend_following | 168h | 496.629154 | 20.875016 | 21.265678 | True |

**MOVEMENT_MARGIN_SUFFICIENT_FOR_FURTHER_RESEARCH** — the long-horizon region clears the toll by a wide margin, so a mechanism there could *pay for itself*; that is an arithmetic statement about the venue's take, not evidence that any mechanism can take the move.  The three tested mechanisms produced no demonstrated gross edge, so the margin stays unclaimed.

The three rejected candidates stay as they were recorded (recomputed here: 0); new hypotheses: 0; new strategies recommended: **0**.

## 6. Standing state and absence of real trades

```text
CAMPAIGN_STATUS = DISCOVERY_CAMPAIGN_FAILED
NEXT_CAMPAIGN = NOT_AUTHORIZED
LIVE_TRADING = False
LIVE_TRADING_FLAG_LITERAL = false
RUNTIME_MODE = paper
EXCHANGE_SANDBOX = True
TRADES_AUTHORIZED = 0
REAL_ORDERS = REFUSED_BY_POLICY
RFC_LIVE_TRADING = DISABLED
RFC_G_BUSINESS_REENTRY = NOT_PASS
FORENSICS_TRADES_AUTHORIZED = 0
FORENSICS_LIVE_TRADING = DISABLED
CAMPAIGN_STATUS_FROM_FORENSICS = DISCOVERY_CAMPAIGN_FAILED
PROFITABILITY_VERIFIED = False
G_BUSINESS_REENTRY = NOT_PASS
RISK_ENGINE = DETERMINISTIC
REENTRY_POLICY_AUTHORIZES_CAPITAL = False
FREEZE_STILL_GOVERNS = True
FALSE_SUCCESS = 0
```

there is no order archive at all: the storage directory holds state journals, not an order book, and the sealed real-decision records carry no order id and no fill.  Nothing in this programme has been executed against a venue.

## 7. Final report

| field | value |
| --- | --- |
| CURRENT_HEAD | 8e0a4b5f805d93eedd5218b10657a37652c0fb5d |
| FALSE_SUCCESS | 0 |
| FILES_COMMITTED | 6 files at `0f8292651ce3cd3ae113c0229de1b7487a00f472`; 8 pending in this gate; 35 foreign files excluded |
| DATASET_HASHES | 12 series hashed (`data/raw/alpha003/price/*.json`) |
| TIMEFRAME_VERIFICATION | certifiable True, agrees with the verified report True (max delta 0.00%) |
| COST_MODEL_STATUS | COST_MODEL_V3 reused; historical 23.7906 bps; posterior 23.353553391 bps; rejected candidates recomputed False |
| READ_ONLY_MARKET_DATA_STATUS | 32.36s window, orders sent 0, credentials 0, complete True; drift monitor INSUFFICIENT_EVIDENCE over 2 window(s) |
| ESTIMATED_VS_MEASURED_COSTS | measured pooled spread 0.376374 bps, worst observed 0.890829 bps, vs modelled 1.0 bps (MODEL_CONSERVATIVE / MODEL_CONSERVATIVE) |
| INDEPENDENT_VERIFICATION | scripts/economic001_closure_verify.py → data/economic001/EVIDENCE_CLOSURE_VERIFICATION.json |
| OPEN_DEFECTS | 4 recorded |
| NEXT_GATE | MOVEMENT_MARGIN_SUFFICIENT_FOR_FURTHER_RESEARCH; campaign NOT_AUTHORIZED; trades authorized 0 |

This artefact does not license: a new campaign, a new hypothesis or a new strategy; paper or live trading, or any deployment of capital; any recalculated verdict for a rejected candidate; any claim that an edge, a profit or a production capability exists.

### Open defects

| id | status | scope |
| --- | --- | --- |
| TD-1 | OPEN_NOT_REPAIRED | repo-wide mypy over another workstream's analyse script |
| TD-2 | OPEN_NOT_REPAIRED | RFC-035E verifier raises on absent inputs |
| ECO-1 | OPEN_PARTIALLY_CLOSED | the gate's own read-only snapshot is one bounded window: spread, latency and depth are measured for a few seconds, not across regimes.  The ST-6 monitor now accumulates further windows (2 collected, verdict INSUFFICIENT_EVIDENCE), which reduces the defect without closing it: windows are still counted in units, not in regimes |
| ECO-2 | UNKNOWN_NOT_RESOLVABLE_OFFLINE | maker queue position, fill probability, realised slippage, fill quality |
