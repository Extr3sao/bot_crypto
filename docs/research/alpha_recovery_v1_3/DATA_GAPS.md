# ARP-004 — DATA GAPS: EXP-ARP-006 / EXP-ARP-008 (§24)

**Neither experiment was executed** (not authorized in ARP-004). Both were
pre-registered in ARP-003 as `DATA_SHORT_FOR_HORIZON`; this section quantifies the gap.

## Method (stated before numbers)

The only depth metric this project has already established is **independent holding
windows** (`independent ≈ evaluable_days / max_hold_days`), with an adequacy band of
**≈40–60** windows inherited from the ARP-003 horizon audit (≈18–24 and ≈4–5 were
called `DATA_SHORT_FOR_HORIZON`). These are order-of-magnitude targets, not a
statistically-derived minimum: `max_hold_days` is an *upper* bound on holding, so real
mean holding is shorter and the true trade count could be higher. Where the methodology
cannot support a precise figure, a range is given instead.

Current depth: corpus ≈209 days/symbol total; **DEV = 122 days/symbol**, VALIDATION 62,
OOS 24.

## EXP-ARP-006 — `STRAT-CAND-016-VARIANT-B`, liquidity-void reversal

| quantity | value |
| --- | --- |
| pre-registered `max_hold_days` | **5** |
| warmup (ATR-14 + 3-day void + 10-day retest) | ≈27 days |
| evaluable DEV days | ≈95 |
| independent windows today | ≈19 |
| **target** independent windows | ≈40–60 |
| **minimum DEV depth implied** | **≈230–330 days/symbol** |
| **gap vs current DEV (122)** | **≈110–210 days** |

## EXP-ARP-008 — `H-DAILY-TSMOM-001`, daily time-series momentum

| quantity | value |
| --- | --- |
| pre-registered `max_hold_days` | **20** |
| warmup (`lookback_days`) | 30 days |
| evaluable DEV days | ≈92 |
| independent windows today | ≈4–5 |
| **target** independent windows | ≈40–60 |
| **minimum DEV depth implied** | **≈830–1230 days/symbol** |
| **gap vs current DEV (122)** | **≈2 to 3 years of additional daily history** |

## Conclusion

`EXP-ARP-006` needs roughly **+4–7 months** of additional daily history per symbol to
reach the adequacy band; `EXP-ARP-008` needs roughly **+2–3 years**. A DEV *fail* on the
current corpus would still be informative today, but ARP-004 did not authorize either
run, so no result is reported for them and no data was fetched to compensate.
