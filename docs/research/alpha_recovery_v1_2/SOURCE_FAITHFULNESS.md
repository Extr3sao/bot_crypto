# ARP-003 — SOURCE FAITHFULNESS (§3–§6)

## Verdict

| candidate | source | source-faithful status | prior project test |
| --- | --- | --- | --- |
| `STRAT-CAND-016` liquidity-void retest | SRC-MANUAL-001 pp.95-101 | **`BLOCKED_NEEDS_SPEC`** | `EXP-ARP-002` = `PROJECT_DERIVED_VARIANT` |
| `STRAT-CAND-012` SMT relative strength | SRC-MANUAL-001 pp.3-8;120-123 | **`BLOCKED_NEEDS_SPEC`** | `EXP-ARP-003` = `PROJECT_DERIVED_VARIANT` |
| `STRAT-CAND-019` pivot level fade | SRC-MANUAL-002 pp.32-33 | **`BLOCKED_NEEDS_SPEC`** | `EXP-ARP-005` = `PROJECT_DERIVED_VARIANT` |

Full per-rule tables: `source-faithful/STRAT-CAND-016.md`, `…-012.md`, `…-019.md`.

## What each is missing (the reason it stays blocked)

| candidate | source gives | source does **not** give |
| --- | --- | --- |
| 016 | "fast one-sided void revisited/rebalanced"; FX; multi-TF | void definition/threshold; entry trigger; stop; target; horizon |
| 012 | compare related pairs/DXY; divergent peaks/troughs; M15 preference | divergence window; leader/follower map; entry timing; stop; target; correlation filter; the FX universe itself |
| 019 | standard pivot formula; fade first contact; close quickly; intraday | contact tolerance; confirmation; stop; target; the meaning of "quickly" |

In every case the missing pieces are exactly the ones a deterministic, PIT-safe test
requires. Supplying any of them converts the test into a `PROJECT_DERIVED_VARIANT`;
it does **not** make it source-faithful.

## The consequential correction carried over from ARP-002

ARP-002's `REJECT_COSTS` verdicts for 016/012/019 reject a **project variant's
parameter set**, not the source hypothesis. This is required by `NEG-020` ("Do not
claim source failure from a test whose entry/exit/regime rules materially differ from
the source."). The vocabulary is therefore:

- `TESTED_CONFIGURATION_REJECTED` — the project variant failed;
- `SOURCE_HYPOTHESIS_UNRESOLVED` — the source claim is neither proved nor refuted.

## Source vs project identity (§6) — never merged

| candidate | source-faithful identity | project variant identity |
| --- | --- | --- |
| 016 | `STRAT-CAND-016-SOURCE` (**BLOCKED**) | `STRAT-CAND-016-VARIANT-A` (EXP-ARP-002, 5m) · `STRAT-CAND-016-VARIANT-B` (EXP-ARP-006, daily) |
| 012 | `STRAT-CAND-012-SOURCE` (**BLOCKED**) | `STRAT-CAND-012-VARIANT-A` (EXP-ARP-003, 5m pair) · `H-XSEC-RELSTR-001` (EXP-ARP-009 — **new id**, no CAND-012 lineage) |
| 019 | `STRAT-CAND-019-SOURCE` (**BLOCKED**) | `STRAT-CAND-019-VARIANT-A` (EXP-ARP-005, 5m) · `STRAT-CAND-019-VARIANT-B` (EXP-ARP-007, daily) |

A failed project variant does not reject the source hypothesis, and no project
variant result may be reported as source-attributed. Conversely, a source hypothesis
may not be claimed to work on the strength of a project variant.

## Registry status is unchanged

No spec was rewritten. The three candidate specs already declare
`SOURCE_FAITHFUL_EXPERIMENT = FALSE` and status
`STRATEGY_CANDIDATE — NEEDS_SPEC_BEFORE_SOURCE_FAITHFUL_TEST`; ARP-003 confirms that
declaration is correct and adds the *field-level* reconstruction above.
