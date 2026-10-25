# CAP-005 — Baseline Ladder Spec (DESIGN ONLY)

Status: **design document, not executed.** Nothing in this file changes the
running campaign, and no baseline here is implemented yet.

## Why this exists

CAP-003 built the measurement instrument and CAP-004 makes it run without
supervision. Both keep a *single* deterministic comparator, **baseline B**,
frozen at `DETERMINISTIC_TREND_RULE_V1_1` (`close > SMA(200)` and
`MACD(12,26,9)` and `30 <= RSI(14) <= 70`). That is deliberate: changing B
mid-campaign would destroy comparability with every evaluation already sealed.

But one comparator answers only one question — *does the analyst beat this one
rule?* It cannot answer the question that actually decides the paradigm:

> At which **level of deterministic complexity** does `MARKET_ANALYST_V1.0`
> stop adding value?

CAP-005 is the design for that question. It adds comparators; it never edits the
existing ones, and it never rewrites the ledger.

## Hard constraints (inherited, non-negotiable)

- The CAP-003/CAP-004 baseline **B is frozen**. CAP-005 adds new rows; it does
  not move the old one.
- The ledger is **immutable and append-only**. A ladder level is a *re-scoring of
  the same sealed decisions and outcomes*, never a new outcome, never a
  backfilled decision.
- `MARKET_ANALYST_V1.0`, its prompt, its asset universe, its 24H horizon and its
  cost model are **unchanged**. CAP-005 is a comparator exercise, not a new
  analyst.
- Every ladder level is deterministic, derived only from point-in-time data
  available at the decision time (`data_time <= decision_time`), and produces the
  same number twice for the same inputs — the same reproducibility contract that
  forced `DETERMINISTIC_TREND_RULE_V1_1` (fixed input-bar tails, hashed inputs).
- No verdict word (`PROFITABLE`, `EDGE_CONFIRMED`, ...) may appear before the
  sample floor. The ladder is diagnostic until `G_AGENTIC_EDGE` is evaluable.

## The ladder

Each level is a strict superset of the previous level's information. The point
isn't to find a *better* rule — it is to find the rung where the analyst's
incremental edge, measured against that rung, disappears.

| level | name | information | deterministic inputs |
| --- | --- | --- | --- |
| `B0` | cash | none | always `NO_TRADE` (no exposure) |
| `B1` | buy-and-hold | price | always `LONG` for the window (= CAP-003 `C`) |
| `B2` | single trend filter | price, one indicator | `close > SMA(200)` only |
| `B3` | trend + momentum | price, two indicators | `SMA(200)` **and** `MACD(12,26,9)` |
| `B4` | trend + momentum + bound | + a range filter | `B3` and `30 <= RSI(14) <= 70` (**= frozen B**) |
| `B5` | `B4` + volatility regime | + realised vol | `B4` and regime from `VolatilityIndicator` |
| `B6` | `B5` + multi-timeframe | + 1h/4h/1D agreement | `B5` and HTF alignment, PIT-safe |

Notes:

- `B1` already exists as CAP-003 comparator **C** (`B_BUY_AND_HOLD`); the ladder
  will surface it instead of duplicating it.
- `B4` is byte-for-byte the frozen baseline **B**; the ladder must reproduce it
  exactly, which is a self-test in itself.
- `B5`/`B6` are where the ladder gets *interesting*: they are the rungs most
  likely to close the gap to the analyst, and therefore the rungs that most
  threaten the paradigm's claim. They must be built adversarially, not
  generously.

## Scoring on the same ledger

For a sealed decision set with settled outcomes, CAP-005 re-scores every rung
with the **existing** `DecisionOutcomeEvaluator` and `alpha_scorecard`:

- one `BaselineComparison` per rung, per evaluation, all carrying
  `rule_version` and `rule_input_hash`;
- one incremental edge `A - Bn` per rung;
- one *edge-vs-complexity curve*: `edge(B0) >= edge(B1) >= ... >= edge(B6)`
  is the honest shape to test, and any inversion is a result worth reporting.

The agent's decision is the same in every row. What moves is the comparator.

## What CAP-005 must not do

- Not promote any analyst output to a runtime.
- Not open the holdout.
- Not tune thresholds to make an edge appear; rungs are predeclared, and any
  parameter is frozen before scoring.
- Not replace `B` in the running CAP-004 campaign. The ladder is a **separate
  study over the same immutable ledger**.

## Acceptance for a future CAP-005 build

```
frozen B reproduced bit-for-bit by B4
every rung reproducible twice for identical inputs (input-hash pinned)
no new outcome written; only appended comparisons/scores
sample floor respected; no verdict below MIN_EVALUABLE_DECISIONS
CAP-003 and CAP-004 verifiers still PASS
```

## Next gate

Until CAP-004 has `>= 20` evaluated real decisions, the only correct next gate
is `ACCUMULATE_REAL_DECISIONS`. CAP-005 is written down now so the ladder is
predeclared, but it is **not** built until the campaign has enough real,
independently verifiable outcomes to compare against.
