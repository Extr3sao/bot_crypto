# RFC-049 HYPOTHESIS REGISTRY

- campaign: **RFC-049 DISCOVERY 2 — Phase A**
- machine-readable twin: `data/rfc049/HYPOTHESIS_REGISTRY.json`
- budgets: ≤ 3 admitted · 1 candidate each · 0 parameter searches · 1 OOS opening
- states: `RESEARCH_CANDIDATE → RESEARCH_REJECTED → ADMITTED_FOR_PREREGISTRATION → SPEC_FROZEN → ECONOMIC_TEST_AUTHORIZED → EVALUATED → REJECTED / INSUFFICIENT_EVIDENCE → ELIGIBLE_FOR_INDEPENDENT_REVIEW`

> Admission is not validation and not a profitability claim.  Economic-test
> authorization has not been granted to anything: `NEXT_CAMPAIGN = NOT_AUTHORIZED`.

## 1. Admitted, specification frozen

### H-049-001 — STABLE_LIQUIDITY_IMPULSE (`S-049-001`)

- **mechanism**: stablecoins are the settlement rail of crypto; primary-market
  issuance is new dollar purchasing power entering the system, and aggregate
  USD-pegged supply growth is a direct measure of net fiat inflow.  Inflows are
  autocorrelated while they are being deployed, so supply growth above its own
  norm should be followed by positive net spot returns at the multi-day horizon.
- **rule (frozen)**: `r30 = D_t/D_{t-30} − 1` (total USD-pegged stablecoin
  circulating value); LONG when `r30 > median(previous 365 daily r30)`, else FLAT;
  weekly decision (Sunday 23:00 UTC, inputs ≤ Saturday 23:59 UTC); next-open
  execution; warmup 395 days.
- **assets**: BTCUSDT primary, ETHUSDT replication · **instrument**: spot long/cash
- **sources**: SRC-049-001 (data), 002 (academic), 003 (FEDS), 004/005 (event study + counter-evidence)
- **invalidation**: any frozen threshold fails on sealed OOS; LCB ≤ 0; 1.5x
  stress ≤ 0; incremental over buy-and-hold or 200d trend ≤ 0; PIT revision
- **spec**: `data/rfc049/specs/H-049-001.json`

### H-049-002 — MACRO_NET_LIQUIDITY_REGIME (`S-049-002`)

- **mechanism**: BTC trades as a long-duration, dollar-liquidity-sensitive risk
  asset; net liquidity (`WALCL − RRP − TGA`) expanding means looser dollar funding
  and a lower market price of risk.
- **rule (frozen)**: weekly Wednesday grid; LONG when the 4-week change of net
  liquidity is positive; FLAT otherwise; Sunday decision with declared release
  lags (H.4.1/DTS/RRP ≥ 1 day); next-open execution.
- **assets**: BTCUSDT primary, ETHUSDT replication · **instrument**: spot long/cash
- **sources**: SRC-049-006 (academic), 007 (framework), 008 (official series + releases)
- **invalidation**: same battery as H-049-001 plus a PIT audit failure
- **spec**: `data/rfc049/specs/H-049-002.json`

**Cross-control (declared before measurement)**: both hypotheses live in a
`liquidity → risk appetite` family.  Each must beat, in addition to its other
baselines, **the other hypothesis's state** on identical windows and costs.  If
one merely replicates the other, it is rejected as a re-description, not renamed.

## 2. Deferred (registered, not admitted)

### H-049-003 — MINER_SUPPLY_STRESS (`S-049-003`) — `RESEARCH_CANDIDATE`

- **mechanism**: miners are structurally forced sellers; hashrate contraction
  marks capitulation, and the recovery crossover marks the end of the forced
  selling — a supply-side observable price alone does not contain.
- **why not admitted now**: event frequency 1–4 round trips/year cannot support the
  preregistered sample floor (20 sealed round trips within 24 months), so the
  campaign could not reach a PASS or a FAIL verdict; the daily hashrate record
  covers only two cycles.  Admitting it would spend a budget slot on a design that
  is foreknown to return INSUFFICIENT_OOS_SAMPLE.
- **disposition**: retained with its rule and observation policy so a future
  campaign with a feasible design (more forward history, or a broader sample)
  can propose it as a new hypothesis.
- **spec record**: `data/rfc049/specs/H-049-003.json`

## 3. Reviewed and rejected before admission

Recorded so the selection process is visible, not only the survivors (RFC-049 §4).
These consume no budget.

| id | mechanism | reason for rejection |
| --- | --- | --- |
| R-049-001 | Google Trends attention factor | the index is recomputed retroactively; historical values are not PIT-reproducible |
| R-049-002 | stablecoin exchange net-inflows at 1–2h (OPP-0003) | labelled flow history is commercial; the source's horizon is below the cost floor |
| R-049-003 | MVRV / realized-cap valuation | realized cap needs a paid provider; no free PIT-verifiable series found |
| R-049-004 | Deribit DVOL volatility risk premium | the options expression is outside the runtime; the spot-only version reduces to a closed vol-shock family |
| R-049-005 | quarterly futures roll / expiry basis | same basis-carry family already rejected (OPP-0008/0030); no verified free series |
| R-049-006 | network adoption / NVT valuation | address heuristics and vendor revisions; no versioned PIT-pinned series; overlaps unfalsifiable Metcalfe claims |

## 4. Closed lines checked against every admission (A-5)

| closed line | closed by | evidence |
| --- | --- | --- |
| perpetual funding carry | RFC-028/029, RFC-035 | `OPP-0008`, `OPP-0030` |
| spot-BTC ETF net-flow continuation | RFC-035E | `OPP-0001`, `data/rfc035e` |
| time-series momentum / trend | RFC-041/046, ALPHA-001/003 | `CANDIDATE_ARCHIVE`, ALPHA closures |
| cross-sectional momentum / reversal / low-vol | RFC-041, ARP-005, ALPHA-001 | `CANDIDATE_ARCHIVE`, `ALPHA001_CLOSURE` |
| funding capitulation / settlement dip / weekend rebound | RFC-046 | `data/rfc046/RUN_REPORT.json` |
| derivatives-positioning confirmation | ALPHA-002 | `ALPHA002_CLOSURE` |
| cross-asset lead-lag / relative strength | ALPHA-001/003 | `ALPHA001_CLOSURE`, `ALPHA003_CLOSURE` |
| intraday seasonality / clock boundaries | RFC-035 | `OPP-0005/0006/0009` |
| order-flow / microstructure | RFC-035, microstructure V1–V2 | `OPP-0007` |
| token unlocks | RFC-035 | `OPP-0002` |
| liquidation-cascade reversal | RFC-035/046 data audit | `OPP-0004` |
| stablecoin exchange-flow prediction (OPP-0003) | not closed — WATCH, blocked on data and cost headroom | `OPP-0003` |

H-049-001 is **not** the OPP-0003 construction: it uses a free aggregate supply
series at a cost-compatible horizon and declares the relationship explicitly.
H-049-002's nearest closed line is trend/momentum, which its frozen 200-day
baseline control is designed to detect.

## 5. State of the campaign

```text
admitted, spec frozen            : H-049-001, H-049-002
deferred candidate               : H-049-003
rejected before admission        : R-049-001 .. R-049-006
economic tests authorized        : NONE (NEXT_CAMPAIGN = NOT_AUTHORIZED)
evaluated                        : NONE
eligible for independent review  : NONE
```
