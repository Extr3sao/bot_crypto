# WP-EDGE-14B — frequency definitions

**Verdict `FREQUENCY_RECONCILED_BY_WINDOW_RULE`.**

## The three numbers at 60 s, each with its rule

| name | window rule | direction | unit | is the ACTIVE denominator |
| --- | --- | --- | --- | --- |
| tape_bound_non_overlapping | non-overlapping | any | barrier-clearing windows per day, summed across streams | True |
| tape_any_overlapping | overlapping | any | barrier-clearing windows per day, per stream | False |
| selector_long_only_overlapping | overlapping | long_only | selector-conditioned long-only opportunities per day, summed across streams | False |

## The two published numbers

| measure | value per day |
| --- | --- |
| selector, long-only, overlapping | 144.061 |
| tape bound, non-overlapping | 48.018 |

Same metric: **False**. the selector counts overlapping 60s start points conditioned on extreme imbalance; the tape bound de-overlaps before counting. Only the non-overlapping bound maps to distinct trades.

The ACTIVE target (3.0/day) is measured against `tape_bound_non_overlapping_per_day`.
