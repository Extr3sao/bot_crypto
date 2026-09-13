# H6 V4 — Mechanism evidence

**Checkpoint:** `H6-V4-AUTHORITY-CONTRACT-AND-RUNTIME-BINDING-REPAIR-01`
**Hypothesis ID:** `H6-OI-CONFIRMED-CONTINUATION-04`

## Scope

V4 introduces **no new economic claim**. The mechanism, its external evidence and its
citation set are carried forward unchanged from `H6_MECHANISM_EVIDENCE_V2.md`. Nothing
in this document inspects market returns.

```
NO RETURNS INSPECTED
NO PnL / Sharpe / PF / EXPECTANCY / WIN RATE COMPUTED
H6_BACKTESTS = 0 | H6_EXECUTIONS = 0 | PERFORMANCE_OBSERVED = false
```

## Mechanism (unchanged)

**`OI_CONFIRMED_CONTINUATION`** — family `position_stock_conditioning`.

> Significant new position-stock expansion confirms the immediately preceding price
> direction and predicts continuation in the next completed hour. The primary
> qualifying condition is OI expansion **only**: `delta_oi > 0` **AND**
> `robust_z_oi >= +1.0`. OI contraction and MAD-zero hours yield `NO_TRADE`. This
> explicitly prevents OI contraction (which can reach `z >= 1` because of a negative
> rolling median) from qualifying as expansion.

## External evidence (carried forward verbatim from V2)

| ID | Source | Class |
|----|--------|-------|
| E-1 | CME Group — open interest educational material | `OFFICIAL_EXCHANGE_DOC` |
| E-2 | Investopedia — open interest | `SECONDARY_REFERENCE` |
| E-3 | Shah (2026), *International Journal of Financial Studies* 14(7):178 | `PEER_REVIEWED` (corrected citation) |

Citation-collection rule applied and unchanged: evidence was gathered **before** any
H6 outcome was observable, and no E-x entry was selected or re-selected on the basis of
an H6 result.

## What V4 changes about this evidence: nothing

V4 re-validated that the mechanism statement in `H6_SPEC_V4.json` is **byte-identical**
to the V2 statement (`H6_V4_ECONOMIC_SEMANTIC_DIFF.json → mechanism.statement :
IDENTICAL`). The evidence therefore continues to support exactly the hypothesis it
supported in V2.

## Governance

* `H6_FAILED_MEMORY_COLLISION_REVIEW_V4.md` — collision review (carried forward).
* `H6_V3_FAILURE_RECORD.json` — why V3 never executed.
* V4 prereg is a **governance repair**, so a V4 execution cannot be interpreted as a
  second look at the same data under changed conditions.
