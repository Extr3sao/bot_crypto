# RFC-049B — ADMISSION AUDIT

- generated: `2026-10-10T13:15:31Z` · HEAD `b295dc81be8ea9044d453f3ed34279d302cf850c`
- returns computed: **no** · PnL computed: **no** · OOS opened: **no** · experiments executed: **0**
- checks: 43 (0 failed, 2 blocked)

## 1. Baseline

- frozen specifications verified byte-identical (3 specs; 3 unchanged)
- frozen datasets verified unchanged (11)
- governance flags read: {"DISCOVERY_CAMPAIGN_FAILED": true, "LIVE_TRADING": "DISABLED", "NEXT_CAMPAIGN": "NOT_AUTHORIZED", "PROFITABILITY_VERIFIED": false, "TRADES_AUTHORIZED": 0}
- spot cost status (from the frozen manifest): 23.353553391 bps round trip at 200 USDT, 35.030330087 bps under the 1.5x stress

## 2. What the stablecoin variable actually is

- frozen field `totalCirculatingUSD.peggedUSD`: the circulating amount of every USD-pegged stablecoin multiplied by its own price and summed: a USD *valuation* of circulating supply, not a net mint/burn series and not a measured dollar flow
- payload also carries `totalCirculating.peggedUSD (amount-denominated; ~1:1 with USD at a 1.00 peg)`
- 3238 daily rows from 2017-11-29 to 2026-10-10, 0 missing days
- supply-weighted average peg price: min 0.974648, max 1.008596, largest daily move 0.024512
- 30-day growth computed on the USD valuation versus on the amount-denominated field: maximum divergence 0.025119759156405075, material days 158 of 3208
- revision exposure: 0 of 3238 settled days changed between the freeze and a fresh retrieval

## 3. Macro inputs, verified at their primary sources

| input | frozen units | verified units | observation | publication evidence |
| --- | --- | --- | --- | --- |
| WALCL | millions | Millions of U.S. Dollars , Not Seasonally Adjusted Frequency: Weekly, A | weekly Wednesday | H.4.1, Thursday |
| RRPONTSYD | billions | Billions of US Dollars , Not Seasonally Adjusted Frequency: Daily Fulls | daily business day | NY Fed operation API, same day |
| WTREGEN | millions | Millions of U.S. Dollars , Not Seasonally Adjusted Frequency: Weekly, E | weekly Wednesday | H.4.1, Thursday |

- H.4.1 total assets match the frozen WALCL value: **True**
- H.4.1 week-average General Account matches the frozen WTREGEN value: **True**
- H.4.1 Wednesday General Account versus the latest Treasury DTS closing balance: **{'h41_wednesday_level': 885783.0, 'latest_dts_date': '2026-10-06', 'latest_dts_closing_balance': 885414.0, 'relative_difference': 0.0004165805846352888, 'note': 'the DTS has not yet published the H.4.1 reference Wednesday, which is itself evidence of a next-business-day publication lag', 'matches_within_2pct': True}**
- Treasury DTS weekly means within 2% of the frozen WTREGEN series: **{'compared': 3, 'within': 2}**
- NY Fed operation results match the frozen RRP value exactly on every retrieved day: **True**

## 4. PIT

- composite classification: "PIT_CONSERVATIVE_PROXY" for H-049-001, "PIT_VERIFIED" for H-049-002
- decision-time availability violations: H-049-001 0, H-049-002 0
- incremental reconstruction: 40 sampled decisions recomputed from a truncated feed, 0 mismatches
- DEF-HTF-PIT-001 assessment: applies here = False

## 5. Hypothesis independence (structural, no returns)

- weeks on the common grid: 405
- both long / A only / B only / both flat: 93 / 85 / 120 / 107
- state agreement rate: 0.49382716049382713
- Jaccard on long weeks: 0.31208053691275167
- Spearman rank correlation of the two drivers: 0.08748981630511161

## 6. Sample feasibility (counts only)

- H-049-001: 2.96 round trips per year over 7.76 exposed years; expected in a 24-month sealed window: 5.9; INSUFFICIENT_OOS_SAMPLE_BY_CONSTRUCTION
- H-049-002: 6.18 round trips per year over 7.76 exposed years; expected in a 24-month sealed window: 12.4; INSUFFICIENT_OOS_SAMPLE_BY_CONSTRUCTION

## 7. Defects

- **RFC049B-DEF-01** (documentation) — the frozen H-049-002 text attributes WTREGEN's availability to the Daily Treasury Statement, while the FRED series is the weekly-average General Account figure published inside H.4.1 on the Thursday after the reference Wednesday
- **RFC049B-DEF-02** (contract-interpretation) — the frozen H-049-002 development period starts on the first decidable week on or after 2004-01-01, but the price history the rules execute against starts in 2017
- **RFC049B-DEF-03** (units) — the WTREGEN series definition changed across FRED vintages: the 2019 vintage is expressed in billions and begins in 1986, the current vintage in millions and begins in 2002
- **RFC049B-DEF-04** (data-revision) — the RRPONTSYD series is backfilled on rare dates, including one Wednesday grid point
- **RFC049B-DEF-05** (source-direction) — read in full, SRC-049-004 does not support the directional claim registered for it: it reports a more muted, stabilizing USDT role for Bitcoin and flight-to-safety behaviour during stress
- **RFC049B-DEF-06** (citation) — the Phase A registry cites SRC-049-005 to the wrong journal and with an inexact title
- **RFC049B-DEF-07** (vendor-semantics) — the vendor payload has no publication timestamp and its current day is still forming (it moved intraday between two retrievals)
- **RFC049B-DEF-08** (signal-attribution) — the frozen H-049-001 field is a USD valuation of circulating supply, so a depeg moves the signal without any dollar entering or leaving
- **RFC049B-DEF-09** (power) — the frozen 20-round-trip floor may not be reachable inside the 24-month sealed window at the measured exposed-history turnover

None of these defects changes a frozen rule; none of them was repaired by tuning anything.

## 8. Admission decisions

- **H-049-001**: `READY_FOR_AUTHORIZED_TEST` — variable semantics identified at the vendor payload, contiguous daily history with no gaps, conservative declared availability convention, and a frozen rule with two incremental controls. Its source evidence is weaker than Phase A claimed and is recorded as such, but nothing blocks a valid test.
- **H-049-002**: `READY_FOR_AUTHORIZED_TEST` — every traded input is verified against its primary source for value, units, observation dates and publication timing; decision-time availability is proven for every decision instant; the declared development start is wider than the available price history, which is recorded as an interpretation defect rather than a reason to touch the rule.

## 9. Limits of this audit

- it measures structure, turnover and provenance; it makes no statement about profitability
- full text could not be read for three sources; each is declared at the level actually read
- the re-fetch observation window is short, so vendor stability is bounded evidence, not proof
