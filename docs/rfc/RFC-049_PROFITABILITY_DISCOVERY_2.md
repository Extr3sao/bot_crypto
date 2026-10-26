# RFC-049 — PROFITABILITY DISCOVERY 2 (Evidence-Driven Economic Alpha Research)

| field | value |
| --- | --- |
| rfc | **RFC-049** |
| status | **PREPARED — AWAITING CAMPAIGN AUTHORIZATION** (`RFC049_PREPARED_AWAITING_CAMPAIGN_AUTHORIZATION`) |
| phase completed | **PHASE A — PREPARATION** |
| phase not started | PHASE B — ECONOMIC CAMPAIGN (`WP-049-06..10` blocked by the activation gate) |
| baseline | `cba8a337e802e66941a7ba72af71c499322bd2fa` (RFC-048V delivery) |
| reference | RFC-035 / RFC-041 / RFC-046 / RFC-048V / ALPHA-001..003 |
| capital scope | 200 USDT experimental, offline only |
| campaign authorization | `NEXT_CAMPAIGN = NOT_AUTHORIZED` — **no economic experiment has been executed** |
| trades authorized | 0 · live trading DISABLED · profitability NOT verified |

> This document is the repository record of the RFC-049 programme.  Phase A is
> complete; Phase B requires a governance decision that changes `NEXT_CAMPAIGN`.
> Nothing here is a profitability claim: the four result contracts
> (`ECONOMIC_RESULTS`, `ROBUSTNESS_REPORT`) are explicit `NOT_RUN` documents.

## 1. Mission

Find and validate an economic edge that could become a profitable strategy for
this project, under the order of priority fixed by the brief:

```text
MEASURABLE NET EDGE > NUMBER OF STRATEGIES > TRADING FREQUENCY > INFRASTRUCTURE EXPANSION
```

Phase A answers three questions with evidence: *is the runtime ready*, *what can
be tested that is not already closed*, and *what would a legitimate test look like
before any data is consulted for a result*.  It executes no economic evaluation.

## 2. Baseline audit (WP-049-01 — PASS)

`data/rfc049/BASELINE_AUDIT.json` records, re-derived at build time:

- HEAD `cba8a337…`, branch `main`; the working tree carries uncommitted changes owned
  by other agents (ST-6 observability, CAP-004, paper reports); this RFC neither
  stages nor touches them;
- RFC-048V offline certification intact (`RFC048_OFFLINE_CERTIFIED`, FALSE_SUCCESS 0),
  with the risk plane's live path advisory and no order authorization;
- governance flags exactly as required: `DISCOVERY_CAMPAIGN_FAILED`, `NEXT_CAMPAIGN =
  NOT_AUTHORIZED`, `LIVE_TRADING = DISABLED`, `TRADES_AUTHORIZED = 0`,
  `PROFITABILITY_VERIFIED = FALSE`;
- cost model re-derived from `docs/COST_MODEL_V3.json` at the runtime's own sizes:
  **23.353553391 bps** round trip at 200 USDT and **23.790569415 bps** at 1000 USDT
  (fees KNOWN, execution terms ESTIMATED, no account-verified schedule);
- futures scope: only `LINEAR_PERPETUAL` instruments in `ISOLATED` mode are
  certified offline (BTCUSDT listed, minimum notional 50 USDT); no admitted
  hypothesis requires futures, so the experimental futures cost plane is not
  consumed by this RFC;
- datasets inventoried with spans and roles (`data/raw/alpha001..003`,
  `data/rfc035e`, `data/rfc048/raw`);
- **closed lines** enumerated with evidence pointers: funding carry, ETF-flow
  continuation, time-series and cross-sectional momentum/reversal/low-vol, funding
  capitulation / settlement dip / weekend rebound, derivatives-positioning
  confirmation, cross-asset lead-lag, intraday seasonality, order-flow /
  microstructure, token unlocks, liquidation cascades (see §4);
- an RFC-number collision audit confirms no prior RFC-049 artefact existed.

## 3. Research universe, timeframes and costs

- Spot long/cash: BTCUSDT primary, ETHUSDT replication, SOL/XRP available.
- Linear perps offline: available but not used by any admitted hypothesis.
- Timeframes: 1d bars with weekly decisions (multi-day holding); the economic
  audit recorded in `data/economic001/EVIDENCE_CLOSURE.md` is why: median absolute
  moves are 60.5 bps at 4h, 89.3 bps at 8h and 164.8 bps at 24h against a
  23.35–23.79 bps round trip, so longer horizons are the only ones with structural
  cost headroom.
- Cost floor: the frozen spot model only.  No candidate is measured against a
  cheaper scenario, and `ZERO_COST` remains diagnostic-only.

## 4. Hypotheses (WP-049-02/03)

The full registry, including everything rejected before admission, is
`docs/research/RFC049_HYPOTHESIS_REGISTRY.md` and
`data/rfc049/HYPOTHESIS_REGISTRY.json`.  Summary:

| id | mechanism | status | note |
| --- | --- | --- | --- |
| H-049-001 | stablecoin primary issuance → crypto liquidity impulse | **ADMITTED, SPEC FROZEN** | free vendor series (DefiLlama), 3,238 daily points since 2017-11 |
| H-049-002 | USD net liquidity regime (Fed balance sheet − RRP − TGA) | **ADMITTED, SPEC FROZEN** | free official series (FRED), weekly Wednesday grid |
| H-049-003 | miner supply stress (hash-ribbon recovery) | RESEARCH_CANDIDATE (deferred) | event frequency 1–4/yr cannot support the 20-trip sample floor in 24 months |
| R-049-001..006 | search attention, exchange-flow 1-2h, MVRV, DVOL, quarterly basis, network adoption | rejected before admission | reasons recorded per item |

Both admitted hypotheses are long/cash spot state machines with frozen rules,
one parameter set each (`parameter_searches: 0`), a 1.5x cost stress, a
block-bootstrap LCB floor, and **incremental controls** against buy-and-hold, a
200-day price-trend baseline and each other.  That last control exists because
both sit in a `liquidity → risk appetite` family: if either merely replicates the
other or the price trend, it is rejected as a re-description, not renamed.

## 5. Data provenance and PIT (WP-049-04 — PASS, plan level)

`data/rfc049/vendor/VENDOR_MANIFEST.json` records nine new series retrieved and
hashed in Phase A:

| series | rows | span | PIT convention |
| --- | ---: | --- | --- |
| stablecoin USD supply (DefiLlama) | 3,238 | 2017-11-29 → 2026-10-10 | value dated t available at 00:00 UTC of t+1 |
| BTC hashrate (daily, 8y) | 2,917 | 2018-10-12 → 2026-10-09 | t+1 availability (deferred hypothesis) |
| miners revenue | 1,619 | 2009-01-17 → 2026-10-07 | comparator only |
| WALCL | 1,243 | 2002-12-18 → 2026-10-07 | H.4.1 Thursday release, ≥1 day after the Wednesday reference |
| RRPONTSYD | 6,176 | 2003-02-07 → 2026-10-09 | next business day |
| WTREGEN | 1,243 | 2002-12-18 → 2026-10-07 | DTS next business day |
| DFII10 / DTWEXBGS / DFF | 6,201 / 5,415 / 26,398 | 2003 → 2026 | comparators only |

Every series is stored as raw bytes with a SHA-256, and every decision rule
consumes only values whose declared availability precedes the decision instant.
The executable PIT audit (incremental reconstruction at each decision) is a
Phase B gate, marked `BLOCKED` in the acceptance table until a campaign runs.

## 6. OOS integrity (WP-049-04)

`data/rfc049/DATA_EXPOSURE_AUDIT.json` applies the three-class policy:

- `RESEARCH_EXPOSED`: every historical window in this repository, including the
  RFC-046 partition (its final OOS was opened and consumed), the RFC-035E ETF
  windows, the ALPHA-001/003 panels and the series retrieved in Phase A;
- `VALIDATION_CONTROLLED`: not used by this RFC — no historical block can
  honestly carry that label for these data;
- `SEALED_OOS`: forward observations collected strictly after the freeze
  timestamp recorded in `data/rfc049/PREREGISTRATION_MANIFEST.json`, opened once,
  after 20 closed round trips or 24 months, whichever comes first; fewer than 20
  trips at 24 months yields `INSUFFICIENT_OOS_SAMPLE`, never PASS and never
  REJECT on power alone.

## 7. Campaign activation gate (WP-049-05 — STOP)

`NEXT_CAMPAIGN = NOT_AUTHORIZED`.  The consequence is recorded in
`data/rfc049/ECONOMIC_RESULTS.json` (`status: NOT_RUN`, consolidated state
`DISCOVERY2_NOT_AUTHORIZED`) and in the run report: WP-049-06..10 are not
executed, no experiment budget is consumed, and no file in this RFC contains a
signal, a return, a PnL or a trade count for any candidate.

## 8. Work packages

| wp | title | status |
| --- | --- | --- |
| WP-049-01 | runtime & evidence audit | **PASS** |
| WP-049-02 | economic hypothesis sourcing (≤3, with verifiable sources) | **PASS** — 2 admitted + 1 deferred + 6 rejected pre-admission |
| WP-049-03 | preregistration (rules, sources, costs, partitions, criteria frozen) | **PASS** |
| WP-049-04 | data integrity (coverage, PIT conventions, exposure classes) | **PASS at plan level; executable PIT audit BLOCKED until a campaign** |
| WP-049-05 | campaign activation gate | **PASS — stopped as required** |
| WP-049-06 | strategy runtime implementation | BLOCKED (gate) |
| WP-049-07 | economic experiments | BLOCKED (gate) |
| WP-049-08 | robustness & falsification | BLOCKED (gate) |
| WP-049-09 | independent reproduction | BLOCKED (gate) |
| WP-049-10 | final economic decision | BLOCKED (gate) |

## 9. Stop rules (unchanged, binding)

The campaign stops, and writes up the result whether positive or negative, when
any of the following fires: the hypothesis budget is consumed; irreversible
look-ahead is found; a risk violation occurs; OOS is contaminated; data is
unrecoverably invalid; the cost contract cannot evaluate a candidate;
independent verification fails; or a governance rule is breached.  A failed
candidate is closed, never re-tuned; a legitimate revision must enter as a new
hypothesis with new experimental budget.

## 10. Deliverables

Documents: this file (and its `.json`), `docs/research/RFC049_HYPOTHESIS_REGISTRY.md`,
`docs/research/RFC049_SOURCE_REGISTRY.md`, `docs/architecture/RFC049_RUNTIME_FLOW.md`,
`docs/governance/RFC049_DISCOVERY_ADMISSION.md`.
Evidence: `data/rfc049/` — `BASELINE_AUDIT`, `HYPOTHESIS_REGISTRY`,
`PREREGISTRATION_MANIFEST`, `DATA_EXPOSURE_AUDIT`, `ECONOMIC_RESULTS` (NOT_RUN),
`ROBUSTNESS_REPORT` (NOT_RUN), `INDEPENDENT_VERIFICATION`, `RUN_REPORT.{md,json}`,
`FINAL_REPORT.{md,json}`, plus `specs/` and `vendor/`.

## 11. Governance (unchanged)

```text
DISCOVERY_CAMPAIGN_FAILED
NEXT_CAMPAIGN = NOT_AUTHORIZED
LIVE_TRADING = DISABLED
TRADES_AUTHORIZED = 0
PROFITABILITY_VERIFIED = FALSE
```

No ST-6 intervention, no COST_MODEL_V3 change, no strategy campaign.  Nothing in
this RFC authorizes capital, paper promotion or live execution.
