# STRAT-CAND-012 — SOURCE RECONSTRUCTION (ARP-003 §4)

**Source-faithful status: `BLOCKED_NEEDS_SPEC`.** `UNKNOWN` stays `UNKNOWN`.

- Candidate id: `STRAT-CAND-012` (unrenumbered)
- Source: `SRC-MANUAL-001` "Market Makers Method (Order Blocks)"
- Source location: pp.3-8; 120-123
- Source claim: *divergence between related currency pairs or DXY may identify
  relative-strength dislocations that later resolve*
- Registry hypothesis: `HYP-019` (cross-pair/DXY divergence → subsequent
  relative-strength resolution)
- Experiment id: `EXP-020` (design-only; `NEEDS_SPEC`)
- Prior project implementation: `EXP-ARP-003` = **`PROJECT_DERIVED_VARIANT`** (not a
  source-faithful test)

## Rule table (every field classified)

| field | value from source | class |
| --- | --- | --- |
| market | FX, cross-instrument | `SOURCE_EXPLICIT` |
| asset | "related currency pairs or DXY" | `SOURCE_EXPLICIT` (concept) — the specific pairs are `UNKNOWN` |
| timeframe | M15 preferred "by author experience"; also higher-TF examples | `SOURCE_EXPLICIT` (`THR-M1-009`) |
| universe construction | correlated pairs / DXY | `SOURCE_IMPLIED` — correlation ranking method `UNKNOWN` |
| ranking window | — | `UNKNOWN` |
| rebalance interval | — | `UNKNOWN` |
| long / short or long-only | — | `UNKNOWN` |
| number of assets selected | — | `UNKNOWN` |
| weighting | — | `UNKNOWN` |
| turnover control | — | `UNKNOWN` |
| entry timing | "trade expected resolution" | `SOURCE_EXPLICIT` (concept) — trigger `UNKNOWN` |
| exit / rebalance timing | — | `UNKNOWN` |
| stop | — | `UNKNOWN` |
| target | — | `UNKNOWN` |
| liquidity filters | — | `UNKNOWN` |
| divergence detection | "compare related instruments; detect divergent peaks/troughs" | `SOURCE_EXPLICIT` (concept) — **pivot definition `UNKNOWN`** |
| correlation stability filter | — | `UNKNOWN` |

## PIT / leakage hazards that would have to be resolved (§4)

Even if a project variant is built, the following must be prevented explicitly:

- **survivorship bias** — only 3 assets (BTC/ETH/SOL) exist in the corpus; the
  source's FX universe is not present. A crypto cross-sectional test is a
  different universe, so it is a project variant by construction.
- **future membership / future liquidity / future ranking information** — the
  ranking must use only returns observable at the rebalance timestamp
  (`data_time <= decision_time`); a ranking computed on a window that ends after
  the decision bar is forbidden.
- **leader/follower mapping** — the source never fixes which instrument leads.

## Why the source-faithful experiment is blocked

The source supplies the *idea* (relative-strength divergence resolves) but none of
the deterministic machinery: no divergence window, no leader/follower map, no entry
timing, no stop, no target, no correlation-stability filter. Every one of these is a
required field of a testable spec (see the candidate spec's "Missing Rules"). For a
crypto corpus the asset class itself also differs (FX/DXY → USDT spot majors).

**Consequence:** `SOURCE_FAITHFUL_EXPERIMENT = BLOCKED_NEEDS_SPEC`. The prior
`EXP-ARP-003` result (`REJECT_COSTS`, DEV n 3872 gross +0.131 bps) **does not**
refute the source claim.

## Separation from the project variant (§6)

| identity | id | status |
| --- | --- | --- |
| source-faithful | `STRAT-CAND-012-SOURCE` | **BLOCKED_NEEDS_SPEC** (this file) |
| project variant | `STRAT-CAND-012-VARIANT-A` | earlier `EXP-ARP-003` (5m pair divergence) |
| new project variant | `H-XSEC-RELSTR-001` | a **new** cross-sectional daily hypothesis (`EXP-ARP-009`), NOT labeled CAND-012 — different universe, different mechanism |

Note: `H-XSEC-RELSTR-001` is deliberately **not** named `STRAT-CAND-012-*` because
the source's FX/DXY pair-divergence idea and a 3-asset crypto cross-sectional
momentum ranking are not the same mechanism. Naming them together would create a
false lineage.

## Cross-sectional infrastructure (§20)

`src/trading_bot/research/cross_sectional.py::CrossSectionalEngine` (391 lines,
"P19") already implements PIT-safe cross-sectional ranking, dispersion and
quantile selection — but it has **zero callers** in `src/`, `scripts/` or `tests/`
and no test. It is an orphan. See `../INFRASTRUCTURE_NOTES.md`.
