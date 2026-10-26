# RFC-037 — MANAGED FUTURES TREND ADVERSARIAL REFUTATION

Attempt to **falsify MF-TREND-001** (the RFC-036 candidate) before any paper trading,
by testing exact reproducibility, modern out-of-sample transportability, adversarial
robustness and practical capital executability. Frozen strategy; no tuning; no P2.

## Verdict

**Did MF-TREND-001 survive modern independent refutation? → NO (cannot be certified).**

| gate | result |
| --- | --- |
| G_REFUTE_0_RECONCILIATION | **PASS** |
| G_REFUTE_1_MODERN_DATA | **FAIL** |
| G_REFUTE_2_MODERN_EDGE | **BLOCKED** |
| G_REFUTE_3_ADVERSARIAL | **FAIL** |
| G_REFUTE_4_CAPITAL | **HIGH_CAPITAL_ONLY** |

FALSE_SUCCESS = **0**. INDEPENDENT VERIFICATION = **PASS**.

## 1. Reproduction reconciliation (blocker resolved)

RFC-036 reported a ~3% builder-vs-verifier validation gap and widened tolerance to 5%.
RFC-037 **root-caused** it instead: isolating per market, 25/26 matched exactly and the
entire gap came from **copper (`hg`)**. First divergence: **1995-12-15** — the verifier
held the far Dec-1997 contract while the frozen builder rolled off it. Cause: the
verifier initialised its roll-staleness bookkeeping as **empty**, so a freshly-held
contract with no print was never marked stale (the builder initialises it to 0).
Classification: **ROLL_SELECTION**. Fixed in the verifier to match the frozen policy;
now the two pipelines agree to **~1e-8** and the tolerance is a fixed numerical bound
(1e-5), **not** a post-hoc widening.

## 2. Modern data (blocker — unresolved)

No free, **independent**, individual-contract multi-asset futures dataset covering
**2000 → latest** exists: free sources either stop ~2000 (same source as RFC-036), serve
only currently-listed contracts (Yahoo → expired return NOT_FOUND), serve opaque
continuous series (stooq / Nasdaq CHRIS), or are paid (Databento, CME DataMine,
Algoseek from ~$2,500/mo). → `MODERN_VALIDATION_PAID_DATA_BLOCKED`;
**MODERN_RELEVANCE = UNRESOLVED; PAPER = BLOCKED.** No paid data was purchased.

## 3. Adversarial nulls (historical data)

| window | observed (return-space) | perm p(null≥obs) | sign p(null≥obs) |
| --- | --- | --- | --- |
| DISCOVERY | ~17.2M | **0.240** | 0.000 |
| VALIDATION | ~17.2M | **0.113** | 0.001 |

- **Sign randomisation** strongly rejects the null (p≈0): the trend *direction* carries
  real information.
- **Market-label permutation** does **not** reject at 5% (p≈0.11–0.24): the performance is
  not cleanly distinguishable from a random cross-market relabelling. This is a genuine
  weakness, not a pass.

## 4. Practical capital

Under a **pre-registered** rule (`active_markets ≥ 20 AND |tracking_error| ≤ 15%`) no
tested capital level qualifies: small capital zeroes high-notional markets, and large
capital *overshoots* notional through upward rounding (tracking error grows to +780% at
$100M). → **HIGH_CAPITAL_ONLY**; the fractional headline is not robustly reproducible
with integer contracts. `minimum_viable_capital = None`.

## PROJECT KPI (canonical)

```
Historical executable validated edges = 1 / 1
Modern validated edges                 = 0 / 1
Historical robust edges                = 1 / 1
Paper candidates                       = 0 / 1
Forward profitable                     = 0
Live profitable                        = 0
```

## Answer to the RFC-037 question

MF-TREND-001 is currently a **historically-validated edge with a modern blind spot and
practical-capital fragility**, not a modern, executable, practically-tradeable edge.
It is **NOT certified for paper trading**.

NEXT = **P2 FUTURES_CURVE_CARRY** (already authorised), or a human
**data-acquisition decision** to obtain an independent modern individual-contract
dataset for the transport test.
