# OPPORTUNITY_REGISTRY.md — RFC-035 external opportunities

- active_rfc: RFC-035 (EXTERNAL PROFITABLE OPPORTUNITY DISCOVERY)
- sources_reviewed: 64
- opportunities_identified: 27
- disposition counts: {"INSUFFICIENT_EVIDENCE": 1, "REJECT": 5, "REPLICATE_P0": 0, "REPLICATE_P1": 1, "WATCH": 1} (round 1, kept as history) + round 2: {"INSUFFICIENT_EVIDENCE": 4, "REJECT": 7, "REPLICATE_P1": 2, "RESEARCH_HYPOTHESIS_P1": 3, "WATCH": 2}
- selected: **OPP-0001** — rank at selection REPLICATE_P0, corrected to RESEARCH_HYPOTHESIS_P0 by RFC-035E and then rejected there as EFFECT_NOT_REPRODUCED (history kept, not erased)
- validation: **EFFECT_NOT_REPRODUCED** (RFC-035E, independently verified PASS 107/107) -> OPP-0001 = REJECT
- selection_timestamp: 2026-10-07T21:20:00Z
- RULE_HASH (sha256): `afb82b7079143ade6aad1ceb5a759549d99d2904ba4eb32b08b912b0cfb73036`
- SOURCE_BUNDLE_HASH (sha256): `34ea7e3866f582fbdf2584fb946a55cf57693cbcb26647b71907e1af21c4b52e`

## Ranking

| OPPORTUNITY_ID | rank | score | family | sources | status |
| --- | --- | ---: | --- | --- | --- |
| [OPP-0001](opportunities/OPP-0001.md) | RESEARCH_HYPOTHESIS_P0 | 19 | Spot-BTC ETF net-flow continuation (structural creation demand) | S-01, S-02, S-03, S-04 | `RESEARCH_HYPOTHESIS_SELECTED_FOR_VALIDATION` |
| [OPP-0002](opportunities/OPP-0002.md) | RESEARCH_HYPOTHESIS_P1 | 22 | Token unlock / vesting supply events (scheduled forced supply) | S-09, S-10, S-11 | `NOT_SELECTED_DIRECTION_AND_FIDELITY` |
| [OPP-0003](opportunities/OPP-0003.md) | WATCH | 17 | USDT net inflows to exchanges predict BTC/ETH returns | S-07, S-17, S-16 | `BLOCKED_ON_DATA_AND_COST_HEADROOM` |
| [OPP-0004](opportunities/OPP-0004.md) | INSUFFICIENT_EVIDENCE | 13 | Liquidation-cascade reversal (forced selling exhaustion) | S-12, S-13 | `NOT_SELECTED_DATA_INTEGRITY_AND_SAMPLE` |
| [OPP-0005](opportunities/OPP-0005.md) | REJECT | 23 | Quarter-hour clock-boundary predictability (periodic algorithmic trading) | S-05 | `REJECTED_COST_HEADROOM_AND_CADENCE` |
| [OPP-0006](opportunities/OPP-0006.md) | REJECT | 19 | Turn-of-the-candle intraday anomaly in Bitcoin returns | S-06 | `REJECTED_COST_FLOOR` |
| [OPP-0007](opportunities/OPP-0007.md) | REJECT | 22 | Order-flow imbalance / world order flow predicts crypto returns | S-08 | `REJECTED_CLOSED_INTERNAL_FAMILY` |
| [OPP-0008](opportunities/OPP-0008.md) | REJECT | 27 | Perpetual funding carry (long spot / short perpetual) | S-14, S-15, S-19, S-20 | `REJECTED_INSTRUMENT_AND_CAPITAL_FIT` |
| [OPP-0009](opportunities/OPP-0009.md) | REJECT | 17 | Intraday/overnight seasonality in Bitcoin (hour-of-day windows) | S-18 | `REJECTED_MULTIPLE_TESTING_AND_COST` |

## Why OPP-0001 was selected

It is the only registered opportunity that satisfies every clause of the minimum-evidence filter at once:
a clear economic hypothesis (mechanical creation demand), an identifiable market (Binance spot BTC/USDT),
identifiable data (daily public ETF net flows + public OHLCV), logic that can be built into long/cash entry and exit,
and a measurable economic claim with a stated magnitude (about +1.2% impulse response per positive flow shock).
It is also the only one that is simultaneously (a) not a closed internal family, (b) expressible in a long/cash spot
runtime, and (c) larger per trade than the project's 23.791 bps round-trip cost floor.

Its score is deliberately modest (19/50) and its risks are explicit: SAMPLE_SIZE 1, OOS_EVIDENCE 2, no cost model in the
source, and a mechanism whose largest component may already be realised before the flow data is published. RFC-036 remains
entitled to fail: it did, and RFC-035E is the record of that.

## Selection order (anti-hindsight)

The candidate was selected and hashed at the timestamp above, before any backtest, parameter search or data sweep of our own.
No project backtest artifact for this line exists at selection time. The selection cannot be re-pointed at a candidate that
later looks better on our data.

## Builder != verifier

The selection above is not self-certifying. `scripts/rfc035_discovery_verify.py` independently re-checks source existence, source
fidelity, rules completeness, the economic claim, evidence classification, counter-evidence presence, the selection criteria
and the frozen hashes. Any discrepancy is reported as `RFC035 = FAIL/REWORK`, never smoothed over.

## Next gate

`CONTINUE_EXTERNAL_SEARCH`. RFC-036 is **not** opened for OPP-0001: RFC-035E returned `EFFECT_NOT_REPRODUCED`, so there is
no effect worth specifying. No implementation, no backtest and no live trading is authorized by this registry; the RFC-041
freeze stays in force.

## Correction recorded by RFC-035E (nothing erased)

```text
PREVIOUS_CLASSIFICATION  = REPLICATE_P0 (OPP-0001), REPLICATE_P1 (OPP-0002)
CORRECTED_CLASSIFICATION = RESEARCH_HYPOTHESIS_P0 (OPP-0001), RESEARCH_HYPOTHESIS_P1 (OPP-0002)
REASON                   = the source does not define a complete trading strategy;
                           entry/exit/threshold/lookback/aggregation/size are UNKNOWN
VALIDATION (RFC-035E)    = EFFECT_NOT_REPRODUCED -> OPP-0001 = REJECT
```

The original rank is kept in `OPP-0001.json` (`rank_history`, `classification_correction`) and in the RFC-035 final report.
The frozen selection and both hashes are untouched: reclassification is not permission to rewrite the evidence.

## Round 2 (RFC-035S2) — strategy-first candidates

- reviewed_at_utc: 2026-10-08T00:00:00Z
- sources reviewed: 44 new (34 of them primary information origins)
- candidates: 18
- REPLICATE_P0 selected: **NONE** (the round closes as CONTINUE_SEARCH)
- matrix_hash (sha256): `86eef61fbcc457ccc4146d6dfba45c9c6d7d75e3b20aa024a90d9890da3acb7f`
- source_registry_hash (sha256): `5a32da456f021c2b63459edddd501a590ff4985058e371e424d8ba5f647543ae`

| OPPORTUNITY_ID | rank | kind | rules | grade | title |
| --- | --- | --- | --- | --- | --- |
| [OPP-0010](opportunities/OPP-0010.md) | WATCH | EXTERNAL_STRATEGY | 6/21 | E1 | NostalgiaForInfinity — multi-pair 5m Freqtrade strategy |
| [OPP-0011](opportunities/OPP-0011.md) | REPLICATE_P1 | EXTERNAL_STRATEGY | 15/21 | E1 | Strategy001 (freqtrade-strategies) — EMA20/50 cross with Heikin-Ashi confirmation on 5m |
| [OPP-0012](opportunities/OPP-0012.md) | RESEARCH_HYPOTHESIS_P1 | EXTERNAL_STRATEGY | 10/21 | E1 | Crypto and Stock Momentum (QuantConnect Quant League 2024-Q4) |
| [OPP-0013](opportunities/OPP-0013.md) | RESEARCH_HYPOTHESIS_P1 | EXTERNAL_STRATEGY | 12/21 | E1 | Bitcoin MAX/Min breakout — Quantpedia's 2024 revisit (buy at the 10-day maximum) |
| [OPP-0014](opportunities/OPP-0014.md) | INSUFFICIENT_EVIDENCE | RESEARCH_HYPOTHESIS | 0/21 | E1 | Trend-following and Mean-reversion in Bitcoin (Quantpedia, 2022) — the earlier study |
| [OPP-0015](opportunities/OPP-0015.md) | REJECT | EXTERNAL_STRATEGY | 16/21 | E3 | pysystemtrade / Carver's diversified trend-following system |
| [OPP-0016](opportunities/OPP-0016.md) | REPLICATE_P1 | EXTERNAL_STRATEGY | 15/21 | E2 | Q24 Crypto Guide Strategy (Quantiacs) — SMA15/34 + RSI14 long-only crypto daily |
| [OPP-0017](opportunities/OPP-0017.md) | REJECT | RESEARCH_TASK | 9/21 | E3 | G-Research Crypto Forecasting (Kaggle 2022) — winning forecasting solutions |
| [OPP-0018](opportunities/OPP-0018.md) | REJECT | EXTERNAL_STRATEGY | 5/21 | E1 | bitcoin-momentum-trading — 5-minute ML momentum direction model |
| [OPP-0019](opportunities/OPP-0019.md) | INSUFFICIENT_EVIDENCE | RESEARCH_HYPOTHESIS | 4/21 | E1 | Adaptive Regime-Based Trading on Bitcoin (15-minute, walk-forward) |
| [OPP-0020](opportunities/OPP-0020.md) | REJECT | RESEARCH_HYPOTHESIS | 1/21 | E1 | Reflective LLM-based agent for zero-shot cryptocurrency trading |
| [OPP-0021](opportunities/OPP-0021.md) | REJECT | EXTERNAL_STRATEGY | 4/21 | E1 | CGA-Agent — genetic-algorithm optimisation of crypto strategy parameters |
| [OPP-0022](opportunities/OPP-0022.md) | RESEARCH_HYPOTHESIS_P1 | EXTERNAL_STRATEGY | 11/21 | E2 | Daily ML direction trading on Bitcoin with a real unseen-period test (Crone, Brophy, Ward) |
| [OPP-0023](opportunities/OPP-0023.md) | WATCH | RESEARCH_TASK | 5/21 | E3 | Karaptic Research — published-strategy replication series net of fees and slippage |
| [OPP-0024](opportunities/OPP-0024.md) | INSUFFICIENT_EVIDENCE | EXTERNAL_STRATEGY | 5/21 | E1 | Multi-Band Comparison Strategy (CRYPTO) — published Pine Script strategy |
| [OPP-0025](opportunities/OPP-0025.md) | REJECT | EXTERNAL_STRATEGY | 3/21 | E1 | Deep Momentum Networks (Lim/Zohren/Roberts and successors) |
| [OPP-0026](opportunities/OPP-0026.md) | REJECT | RESEARCH_HYPOTHESIS | 1/21 | E0 | An Adaptive Multi-Agent Bitcoin Trading System (LLM-driven) |
| [OPP-0027](opportunities/OPP-0027.md) | INSUFFICIENT_EVIDENCE | RESEARCH_HYPOTHESIS | 1/21 | E1 | Momentum Trading in Cryptocurrencies: time-series vs cross-sectional (comparative study) |

Round-2 detail: `reports/rfc035/search_round_2/` (sources, candidate matrix, rejection log, final report and the independent verification).

## Round 3 (RFC-035S3) — targeted evidence closure

- reviewed_at_utc: 2026-10-08T01:00:00Z
- new primary sources: 8 (capped at 10)
- REPLICATE_P0 selected: **NONE**
- final status: **NO_SUITABLE_EXTERNAL_STRATEGY**
- RFC-036: **BLOCKED**

| OPPORTUNITY_ID | rank | candidate | round-3 reason |
| --- | --- | --- | --- |
| [OPP-0028](opportunities/OPP-0028.md) | REJECT | K-02 Cross-sectional momentum on Binance perpetuals (Karaptic pre-registered replication) | the effect is not distinguishable from zero net of the author's own documented costs and is not stable to a pre-registered specification change |
| [OPP-0029](opportunities/OPP-0029.md) | REJECT | K-03 Time-series momentum in crypto (Grobys et al. 2025, via Karaptic Note 03) | the post-July-2020 regime a trader would trade today is negative and not significant |
| [OPP-0030](opportunities/OPP-0030.md) | REJECT | K-04 Perpetual funding carry on BTC/ETH (Karaptic Note 04) | gross annualised funding of +2.11%/yr BTC and +1.63%/yr ETH is too small to trade at the project's capital scale |
| [OPP-0031](opportunities/OPP-0031.md) | INSUFFICIENT_EVIDENCE | K-05 Short-horizon reversal after a de-trended-volume split (Bianchi, Babiak & Dickerson 2022) | the venue where the effect survives net of fees is not ours and the recipe is not executable as published |
| [OPP-0032](opportunities/OPP-0032.md) | REJECT | QC-01 Adaptive States for Crypto (QuantConnect Quant League 2025-Q2) | the state parameters live in unshared files, no costs are modelled, and the turnover measured by the author's own reviewers is expected to be fatal |
| [OPP-0033](opportunities/OPP-0033.md) | WATCH | K-01 Karaptic Research — pre-registered crypto strategy replication series | a venue and a protocol rather than a strategy; kept as a source of independent replication evidence |

Superseded in place (history kept, nothing erased). `rank` stays frozen as assigned by the round
that classified the candidate, and `current_rank` is the rank in force after RFC-035S3:

| OPPORTUNITY_ID | frozen rank | current rank | reason |
| --- | --- | --- | --- |
| OPP-0011 | REPLICATE_P1 | INSUFFICIENT_EVIDENCE | reglas incompletas (universo, sizing y warmup fuera de la fuente) y sin evidencia económica atribuible al código: por debajo de E2 aunque las reglas de entrada y salida estén completas |
| OPP-0016 | REPLICATE_P1 | INSUFFICIENT_EVIDENCE | no existing result attributable to the code (only the contest threshold), un coste no declarado y tres campos ejecutables sin fijar: la evidencia económica se reclasifica por debajo de E2 |

Round-3 detail: `reports/rfc035/search_round_3/`.
