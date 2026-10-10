# RFC-049B — FINAL ADMISSION REPORT

- CURRENT_HEAD: `b295dc81be8ea9044d453f3ed34279d302cf850c` · generated `2026-10-10T13:15:31Z`
- H-049-001 admission: **READY_FOR_AUTHORIZED_TEST**
- H-049-002 admission: **READY_FOR_AUTHORIZED_TEST**
- campaign authorization: **NOT_AUTHORIZED** · experiments executed **0** · OOS opened **no** · trades authorized **0**
- independent verification: **PASS** (66 checks, 0 failed; 12 negative controls, 0 missed; FALSE_SUCCESS = 0)
- checks: 43 (0 failed, 2 blocked)

## PIT

- H-049-001: `PIT_CONSERVATIVE_PROXY`
- H-049-002: `PIT_VERIFIED`

## Source evidence

- SRC-049-001: FULL_PAYLOAD_AND_HASH
- SRC-049-002: ABSTRACT_ONLY
- SRC-049-003: FULL_TEXT_VERIFIED
- SRC-049-004: FULL_TEXT_VERIFIED
- SRC-049-005: ABSTRACT_ONLY
- SRC-049-006: CLAIM_ONLY
- SRC-049-007: ABSTRACT_ONLY
- SRC-049-008: FULL_TEXT_VERIFIED

## Independence and sample feasibility

- state agreement rate 0.49382716049382713 over 405 weeks; Spearman 0.08748981630511161
- expected sealed-window round trips: H-049-001 5.9 (INSUFFICIENT_OOS_SAMPLE_BY_CONSTRUCTION), H-049-002 12.4 (INSUFFICIENT_OOS_SAMPLE_BY_CONSTRUCTION)

## Defects (none changes a frozen rule)

- RFC049B-DEF-01 (documentation): the frozen H-049-002 text attributes WTREGEN's availability to the Daily Treasury Statement, while the FRED series is the weekly-average General Account figure published inside H.4.1 on the Thursday after the reference Wednesday
- RFC049B-DEF-02 (contract-interpretation): the frozen H-049-002 development period starts on the first decidable week on or after 2004-01-01, but the price history the rules execute against starts in 2017
- RFC049B-DEF-03 (units): the WTREGEN series definition changed across FRED vintages: the 2019 vintage is expressed in billions and begins in 1986, the current vintage in millions and begins in 2002
- RFC049B-DEF-04 (data-revision): the RRPONTSYD series is backfilled on rare dates, including one Wednesday grid point
- RFC049B-DEF-05 (source-direction): read in full, SRC-049-004 does not support the directional claim registered for it: it reports a more muted, stabilizing USDT role for Bitcoin and flight-to-safety behaviour during stress
- RFC049B-DEF-06 (citation): the Phase A registry cites SRC-049-005 to the wrong journal and with an inexact title
- RFC049B-DEF-07 (vendor-semantics): the vendor payload has no publication timestamp and its current day is still forming (it moved intraday between two retrievals)
- RFC049B-DEF-08 (signal-attribution): the frozen H-049-001 field is a USD valuation of circulating supply, so a depeg moves the signal without any dollar entering or leaving
- RFC049B-DEF-09 (power): the frozen 20-round-trip floor may not be reachable inside the 24-month sealed window at the measured exposed-history turnover

## Plain-language conclusion

- the two candidates are buildable on verified inputs: the stablecoin series is confirmed to be a USD valuation of circulating supply (not a dollar flow), and every Federal Reserve and Treasury input matches its primary source exactly, with decision-time availability proven for every decision instant on the grid
- nothing here says either candidate makes money. No return, no PnL and no profit factor was computed, and the sealed window has not been opened
- the external evidence for the stablecoin candidate is weaker than Phase A recorded: the one source read in full points at a flight-to-safety, muted-for-Bitcoin role, and the peer-reviewed source is counter-evidence. That is a reason for the test to exist, not a verdict
- the honest risks are a vendor series without publication timestamps, a rare-backfill macro series, and a 20-trade floor that the measured turnover may not reach inside 24 months

## Next gate

operator decision: authorize Discovery 2 for the candidates listed READY_FOR_AUTHORIZED_TEST
