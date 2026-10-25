# source_registry.md — RFC-035 external sources

- registry_version: RFC035_SOURCE_REGISTRY_V2
- retrieved_at_utc: 2026-10-07T21:10:00Z
- sources: 61 (round 1: 20, round 2: 41)
- evidence_hierarchy: REAL_EXECUTION > FORWARD_PAPER > INDEPENDENT_REPLICATION > REPRODUCIBLE_CODE > ACADEMIC_PAPER > AUTHOR_BACKTEST > UNVERIFIED_CLAIM

> Read level matters: `full_text` = the page text was fetched and used; `abstract_snippet` = only the search-result abstract/snippet was visible. Prices, statistics and dates below are quoted at the level actually read. `UNKNOWN` means the source does not state it — nothing here was filled in by us.

| SOURCE_ID | TYPE | READ | EVIDENCE_LEVEL | RELIABILITY | TITLE |
| --- | --- | --- | --- | --- | --- |
| S-01 | buy-side research note with own statistics | full_text | AUTHOR_BACKTEST | MEDIUM | [Spot ETF Flows & Bitcoin Price Trajectory (preliminary statistical investigation)](https://www.falconx.io/newsroom/what-can-spot-etf-flows-tell-us-about-the-trajectory-of-bitcoin-prices-a-preliminary-statistical-investigation) |
| S-02 | peer-reviewed journal article | abstract_snippet | ACADEMIC_PAPER | HIGH | [Price Discovery in Bitcoin ETF Market](https://onlinelibrary.wiley.com/doi/10.1111/fire.70026) |
| S-03 | peer-reviewed journal article | abstract_snippet | ACADEMIC_PAPER | HIGH | [Do Bitcoin ETFs Lead Price Discovery Following their Introduction?](https://link.springer.com/article/10.1007/s10614-025-10998-x) |
| S-04 | peer-reviewed journal article | abstract_snippet | ACADEMIC_PAPER | HIGH | [Does the introduction of US spot Bitcoin ETFs affect the returns and volatility of major cryptocurrencies?](https://www.sciencedirect.com/science/article/pii/S106297692500047X) |
| S-05 | working paper (arXiv, with an independent data-validation acknowledgement) | full_text | ACADEMIC_PAPER | HIGH | [The Quarter-Hour Effect: Periodic Algorithmic Trading and Return Predictability in Cryptocurrency Futures](https://arxiv.org/html/2607.09426v2) |
| S-06 | peer-reviewed journal article (PMC full text) | abstract_snippet | ACADEMIC_PAPER | HIGH | [Turn-of-the-candle effect in bitcoin returns](https://pmc.ncbi.nlm.nih.gov/articles/PMC10015199/) |
| S-07 | working paper (arXiv) | abstract_snippet | ACADEMIC_PAPER | MEDIUM-HIGH | [Return and Volatility Forecasting Using On-Chain Flows in Cryptocurrency Markets](https://arxiv.org/pdf/2411.06327) |
| S-08 | conference paper (EFMA 2025) | abstract_snippet | ACADEMIC_PAPER | MEDIUM-HIGH | [Order Flow and Cryptocurrency Returns](https://www.efmaefm.org/0EFMAMEETINGS/EFMA%20ANNUAL%20MEETINGS/2025-Greece/papers/OrderFlowpaper.pdf) |
| S-09 | vendor research (market maker, data-driven) | full_text | AUTHOR_BACKTEST | MEDIUM | [From Locked to Liquidity: What 16,000+ Token Unlocks Teach Us](https://keyrock.com/from-locked-to-liquidity-what-16000-token-unlocks-teach-us/) |
| S-10 | vendor research (tokenomics data provider) | full_text | AUTHOR_BACKTEST | MEDIUM | [When Token Unlocks Actually Move Price (236-event study)](https://tokenomist.ai/research/do-token-unlocks-crash-prices) |
| S-11 | SSRN working paper (preliminary) | abstract_snippet | ACADEMIC_PAPER | LOW-MEDIUM | [The 72-Hour Shock? Preliminary Evidence from 52 Token Unlocks](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=6632838) |
| S-12 | SSRN working paper | abstract_snippet | ACADEMIC_PAPER | MEDIUM | [Anatomy of a Crypto Cascade: Minute-Level Evidence (title truncated in the search result)](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=6579278) |
| S-13 | financial news reporting a researcher's finding | abstract_snippet | UNVERIFIED_CLAIM | MEDIUM | [Crypto Liquidation Data Rigged By Exchanges? Researcher Unveils The Truth](https://www.tradingview.com/news/newsbtc:a8377b886094b:0-crypto-liquidation-data-rigged-by-exchanges-researcher-unveils-the-truth/) |
| S-14 | working paper (arXiv, maintained v7) | abstract_snippet | ACADEMIC_PAPER | HIGH | [Fundamentals of Perpetual Futures](https://arxiv.org/html/2212.06888v7) |
| S-15 | working paper | abstract_snippet | ACADEMIC_PAPER | MEDIUM | [The Crypto Carry Trade](https://gerbil.life/papers/CarryTrade.v1.2.pdf) |
| S-16 | peer-reviewed journal article (MDPI journal of risk and financial management style series) | abstract_snippet | ACADEMIC_PAPER | HIGH | [The Predictive Relationship Between Stablecoin and Cryptocurrency Markets](https://www.mdpi.com/2674-1032/5/3/68) |
| S-17 | central bank research note (Federal Reserve Board) | abstract_snippet | ACADEMIC_PAPER | HIGH | [Primary and Secondary Markets for Stablecoins (FEDS Notes)](https://www.federalreserve.gov/econres/notes/feds-notes/primary-and-secondary-markets-for-stablecoins-20240223.html) |
| S-18 | strategy-research blog reproduction (with a companion backtest blog) | abstract_snippet | AUTHOR_BACKTEST | LOW-MEDIUM | [Are There Seasonal Intraday or Overnight Anomalies in Bitcoin?](https://quantpedia.com/are-there-seasonal-intraday-or-overnight-anomalies-in-bitcoin/) |
| S-19 | SSRN working paper | abstract_snippet | ACADEMIC_PAPER | MEDIUM | [Leveraged BTC Funding Carry Algorithm: A Delta-Neutral Model](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=5292305) |
| S-20 | index provider product page | abstract_snippet | UNVERIFIED_CLAIM | MEDIUM-HIGH | [CF Bitcoin Kraken Perpetual Funding Rate Index (KFRI)](https://www.cfbenchmarks.com/data/indices/KFRI) |

## S-01 — Spot ETF Flows & Bitcoin Price Trajectory (preliminary statistical investigation)

- URL: https://www.falconx.io/newsroom/what-can-spot-etf-flows-tell-us-about-the-trajectory-of-bitcoin-prices-a-preliminary-statistical-investigation
- author/date: David Lawant (FalconX Research) / 2024-10-11 (version UNKNOWN)
- family: structural demand / institutional flow continuation
- claim: VAR: previous-day ETF net inflow coefficient 0.027 on today's BTC return; ETF-flow persistence 0.533; Granger causality p=0.00406 (F=8.4767); orthogonalised impulse response peaks near +1.2% around days 3-4 and is non-negative
- claimed return: about +1.2% cumulative per positive flow shock (no cost model)
- trade count / period: UNKNOWN (daily series, Jan-Oct 2024) / 2024-01-11 to 2024-10-11
- costs included: NO · code available: NO · rules complete: PARTIAL (the statistical relation is stated; no trading rule, no cost model, no entry/exit thresholds)
- forward evidence: NO · live evidence: NO
- known limitations: author-declared: short sample, stationarity assumed, non-linearity possible; correlation only 0.30 (<10% of price variance); feedback loop from price to flows; bought-side research, not peer-reviewed
- status here: REFERENCED_BY_OPP-0001

## S-02 — Price Discovery in Bitcoin ETF Market

- URL: https://onlinelibrary.wiley.com/doi/10.1111/fire.70026
- author/date: Kia (Financial Review) / 2025-09 (version UNKNOWN)
- family: price discovery / market structure (not a strategy)
- claim: measures price discovery across spot, futures and ETF markets (no tradable edge claimed)
- claimed return: UNKNOWN
- trade count / period: UNKNOWN / UNKNOWN
- costs included: NO · code available: NO · rules complete: NO (not a strategy source)
- forward evidence: NO · live evidence: NO
- known limitations: paywalled; no rule set; supports mechanism, not implementation
- status here: REFERENCED_BY_OPP-0001

## S-03 — Do Bitcoin ETFs Lead Price Discovery Following their Introduction?

- URL: https://link.springer.com/article/10.1007/s10614-025-10998-x
- author/date: Mohamad et al. (Computational Economics) / 2025 (version UNKNOWN)
- family: price discovery / lead-lag (not a strategy)
- claim: analyses price discovery between BTC ETFs and the underlying spot after introduction
- claimed return: UNKNOWN
- trade count / period: UNKNOWN / UNKNOWN
- costs included: NO · code available: NO · rules complete: NO (not a strategy source)
- forward evidence: NO · live evidence: NO
- known limitations: lead-lag is not a rule set; contemporaneous effects dominate
- status here: REFERENCED_BY_OPP-0001

## S-04 — Does the introduction of US spot Bitcoin ETFs affect the returns and volatility of major cryptocurrencies?

- URL: https://www.sciencedirect.com/science/article/pii/S106297692500047X
- author/date: Babalos et al. (Quarterly Review of Economics and Finance) / 2025 (version UNKNOWN)
- family: event/market-structure effect (not a strategy)
- claim: first empirical evidence on whether the introduction of US spot BTC ETFs affected returns and volatility of major cryptocurrencies
- claimed return: UNKNOWN
- trade count / period: UNKNOWN / around ETF launch (2024)
- costs included: NO · code available: NO · rules complete: NO (not a strategy source)
- forward evidence: NO · live evidence: NO
- known limitations: one-off launch event; cannot be traded again
- status here: REFERENCED_BY_OPP-0001

## S-05 — The Quarter-Hour Effect: Periodic Algorithmic Trading and Return Predictability in Cryptocurrency Futures

- URL: https://arxiv.org/html/2607.09426v2
- author/date: Chan Kim, Peter Reinhard Hansen / 2026-08-24 (version v2)
- family: clock-boundary / order-imbalance predictability
- claim: quarter-hour opening returns predictable out of sample from boundary-aligned lags; quarter-hour opening order imbalance predicts returns over 4-12 hours
- claimed return: UNKNOWN (no net-of-cost strategy metric)
- trade count / period: UNKNOWN / 2021-01-01 to 2024-10-31
- costs included: NO · code available: NO · rules complete: PARTIAL (forecasting regressions, not an entry/exit rule set)
- forward evidence: NO · live evidence: NO
- known limitations: studies perpetual futures, not spot; the documented 10-second opening effect is far below any realistic cost floor
- status here: REFERENCED_BY_OPP-0005

## S-06 — Turn-of-the-candle effect in bitcoin returns

- URL: https://pmc.ncbi.nlm.nih.gov/articles/PMC10015199/
- author/date: Shanaev et al. / 2023 (version UNKNOWN)
- family: intraday calendar/microstructure anomaly
- claim: statistically and economically significant intraday turn-of-the-candle anomaly; positive returns of about 0.58 bps per minute
- claimed return: ~0.58 bps per minute around candle boundaries
- trade count / period: UNKNOWN / in-sample historical; out-of-sample Bitfinex January-August 2022
- costs included: NO · code available: NO · rules complete: PARTIAL (a window around the candle turn is defined; size depends on venue microsecond timing)
- forward evidence: NO · live evidence: NO
- known limitations: gross magnitude is a fraction of the project's 23.791 bps round-trip cost floor; effect closely tied to exchange-specific candle timing
- status here: REFERENCED_BY_OPP-0006

## S-07 — Return and Volatility Forecasting Using On-Chain Flows in Cryptocurrency Markets

- URL: https://arxiv.org/pdf/2411.06327
- author/date: Chi et al. / 2024 (version UNKNOWN)
- family: on-chain flow / structural liquidity
- claim: USDT net inflows into exchanges predict higher BTC and ETH returns (1 and 2 hours) and lower volatility (6-hour intervals)
- claimed return: UNKNOWN (predictive regressions, no net-of-cost metric)
- trade count / period: UNKNOWN / UNKNOWN (PDF not readable by the tool; abstract level only)
- costs included: NO · code available: NO · rules complete: PARTIAL
- forward evidence: NO · live evidence: NO
- known limitations: data-access risk; one-hour horizon vs 15-minute project cadence; no cost model
- status here: REFERENCED_BY_OPP-0003

## S-08 — Order Flow and Cryptocurrency Returns

- URL: https://www.efmaefm.org/0EFMAMEETINGS/EFMA%20ANNUAL%20MEETINGS/2025-Greece/papers/OrderFlowpaper.pdf
- author/date: Anastasopoulos et al. / 2024-2025 (version UNKNOWN)
- family: order-flow imbalance / flow-based return prediction
- claim: world order flow has strong explanatory and predictive power for cryptocurrency returns out of sample, beyond standard predictors
- claimed return: UNKNOWN
- trade count / period: UNKNOWN / UNKNOWN
- costs included: NO · code available: NO · rules complete: PARTIAL
- forward evidence: NO · live evidence: NO
- known limitations: the project has already tested tick-level flow imbalance internally and cost-killed it (gross +0.48 to +0.61 bps vs 23.791 bps round trip)
- status here: REFERENCED_BY_OPP-0007

## S-09 — From Locked to Liquidity: What 16,000+ Token Unlocks Teach Us

- URL: https://keyrock.com/from-locked-to-liquidity-what-16000-token-unlocks-teach-us/
- author/date: Keyrock / 2024 (version UNKNOWN)
- family: structural supply / forced flows (vesting unlocks)
- claim: 90% of unlock events create negative price pressure regardless of size or type; price impact often starts about 30 days before the unlock; bigger unlocks produce about 2.4x sharper drops; team unlocks about -25%; ecosystem-development unlocks +1.18% on average
- claimed return: negative drift of roughly -25% (team) to +1.18% (ecosystem) per event class
- trade count / period: 16,000+ unlock events / multi-year, UNKNOWN exact window
- costs included: NO · code available: NO · rules complete: PARTIAL (event categories and size bands defined; no tradable entry/exit rule, no cost model)
- forward evidence: NO · live evidence: NO
- known limitations: vendor research, no released sample or code; the direction of the effect is negative, so a long/cash spot runtime can only express it as avoidance
- status here: REFERENCED_BY_OPP-0002

## S-10 — When Token Unlocks Actually Move Price (236-event study)

- URL: https://tokenomist.ai/research/do-token-unlocks-crash-prices
- author/date: Chawapat Peechapat (Tokenomist) / 2026-06-29 (version UNKNOWN)
- family: counter-evidence to the vesting-unlock thesis
- claim: unlock price drops are real but conditional: concentrated in early-stage, thin-float tokens, and mostly priced in before the unlock
- claimed return: UNKNOWN
- trade count / period: 236 / UNKNOWN
- costs included: NO · code available: NO · rules complete: NO
- forward evidence: NO · live evidence: NO
- known limitations: counter-evidence source: the effect is conditional and largely anticipated
- status here: COUNTER_EVIDENCE_FOR_OPP-0002

## S-11 — The 72-Hour Shock? Preliminary Evidence from 52 Token Unlocks

- URL: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=6632838
- author/date: H. K. Kim / 2026 (version UNKNOWN)
- family: structural supply / vesting unlocks
- claim: preliminary evidence of a 72-hour post-unlock price effect over 52 events; cites Keyrock 2024 as the broad-sample antecedent
- claimed return: UNKNOWN
- trade count / period: 52 / UNKNOWN
- costs included: UNKNOWN · code available: NO · rules complete: NO
- forward evidence: NO · live evidence: NO
- known limitations: preliminary, 52 events, paywalled/unreadable full text
- status here: REFERENCED_BY_OPP-0002

## S-12 — Anatomy of a Crypto Cascade: Minute-Level Evidence (title truncated in the search result)

- URL: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=6579278
- author/date: B. C. Lim / 2026 (version UNKNOWN)
- family: liquidation cascades / forced selling
- claim: documents five stylised facts of liquidation cascades; example: BTC fell 12.6% in ten minutes on Binance with the basis swinging 1,367 USD
- claimed return: UNKNOWN (descriptive, no strategy metric)
- trade count / period: UNKNOWN / UNKNOWN
- costs included: NO · code available: NO · rules complete: NO (stylised facts, not rules)
- forward evidence: NO · live evidence: NO
- known limitations: descriptive paper; cascade events are rare; relies on liquidation feeds whose public completeness is contested (see S-13)
- status here: REFERENCED_BY_OPP-0004

## S-13 — Crypto Liquidation Data Rigged By Exchanges? Researcher Unveils The Truth

- URL: https://www.tradingview.com/news/newsbtc:a8377b886094b:0-crypto-liquidation-data-rigged-by-exchanges-researcher-unveils-the-truth/
- author/date: NewsBTC via TradingView / 2024-08-30 (version UNKNOWN)
- family: counter-evidence for liquidation-based signals
- claim: both Binance and Bybit adjusted their liquidation WebSocket APIs to report only one liquidation per second
- claimed return: n/a
- trade count / period: n/a / 2024
- costs included: NO · code available: NO · rules complete: NO
- forward evidence: NO · live evidence: NO
- known limitations: secondary source; MEDIUM reliability; directly undermines cascade measurement from public feeds
- status here: COUNTER_EVIDENCE_FOR_OPP-0004

## S-14 — Fundamentals of Perpetual Futures

- URL: https://arxiv.org/html/2212.06888v7
- author/date: He, Manela, Ross, von Beschwitz / 2026 (v7) (version v7)
- family: perpetual funding carry (long spot / short perp)
- claim: funding-rate carry strategy on Bitcoin perpetuals generates a Sharpe ratio of 3.35 even under high retail trading costs
- claimed return: UNKNOWN exact; Sharpe 3.35 under high cost assumptions
- trade count / period: UNKNOWN / UNKNOWN
- costs included: YES (high-cost retail scenario reported) · code available: NO · rules complete: PARTIAL (carry rule is simple, capital/venue plumbing is not)
- forward evidence: NO · live evidence: NO
- known limitations: requires shorting a perpetual, on margin, across two venues; the project runtime excludes derivatives and has 200 USDT of reference capital
- status here: REFERENCED_BY_OPP-0008

## S-15 — The Crypto Carry Trade

- URL: https://gerbil.life/papers/CarryTrade.v1.2.pdf
- author/date: UNKNOWN / 2023-08-18 (version v1.2)
- family: structural carry
- claim: a short-perpetual / long-spot crypto carry trade has a high Sharpe ratio
- claimed return: UNKNOWN
- trade count / period: UNKNOWN / UNKNOWN
- costs included: UNKNOWN · code available: NO · rules complete: PARTIAL
- forward evidence: NO · live evidence: NO
- known limitations: same instrument-incompatibility as S-14; also the project already measured that its own carry-adjacent line sits below cost
- status here: REFERENCED_BY_OPP-0008

## S-16 — The Predictive Relationship Between Stablecoin and Cryptocurrency Markets

- URL: https://www.mdpi.com/2674-1032/5/3/68
- author/date: C. Boido et al. / 2026 (version UNKNOWN)
- family: counter-evidence for stablecoin-signal lines
- claim: in the forward direction, evidence that stablecoin depegs predict cryptocurrency returns is weak and does not cohere into a systematic pattern
- claimed return: n/a (negative result)
- trade count / period: n/a / UNKNOWN
- costs included: NO · code available: NO · rules complete: NO
- forward evidence: NO (the paper tests forward predictability and finds it weak) · live evidence: NO
- known limitations: negative-result source; used here as counter-evidence, not as an opportunity
- status here: COUNTER_EVIDENCE_FOR_OPP-0003

## S-17 — Primary and Secondary Markets for Stablecoins (FEDS Notes)

- URL: https://www.federalreserve.gov/econres/notes/feds-notes/primary-and-secondary-markets-for-stablecoins-20240223.html
- author/date: C. Watsky et al. / 2024-02-23 (version UNKNOWN)
- family: structural liquidity / stablecoin issuance
- claim: discusses evidence that Tether minting events are associated with positive Bitcoin price responses; focuses on primary-market mechanics and secondary-market prices
- claimed return: UNKNOWN
- trade count / period: n/a / UNKNOWN
- costs included: NO · code available: NO · rules complete: NO
- forward evidence: NO · live evidence: NO
- known limitations: macro/structural note, not a strategy paper; mint events must be obtained on-chain
- status here: REFERENCED_BY_OPP-0003

## S-18 — Are There Seasonal Intraday or Overnight Anomalies in Bitcoin?

- URL: https://quantpedia.com/are-there-seasonal-intraday-or-overnight-anomalies-in-bitcoin/
- author/date: Quantpedia / QuantifiedStrategies / 2022-02-18 (version UNKNOWN)
- family: intraday/overnight seasonality
- claim: hour-of-day seasonality in BTC returns; 22:00 and 23:00 UTC described as the most economically significant hours, 04:00 the worst; companion backtest reports about 0.07% average return for the best hour
- claimed return: about 7 bps for the best single hour
- trade count / period: UNKNOWN / UNKNOWN
- costs included: NO · code available: NO · rules complete: PARTIAL (a fixed hour is named; selection of that hour is itself the mined parameter)
- forward evidence: NO · live evidence: NO
- known limitations: gross effect per trade is below the project's 23.791 bps round-trip cost floor; hour selection is a mined threshold
- status here: REFERENCED_BY_OPP-0009

## S-19 — Leveraged BTC Funding Carry Algorithm: A Delta-Neutral Model

- URL: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=5292305
- author/date: S. Chan / 2025 (version UNKNOWN)
- family: perpetual funding carry (delta-neutral, levered)
- claim: annualised return 16.0% with Sharpe 6.1 and a reported maximum drawdown over three years of tick-level data
- claimed return: 16.0% annualised
- trade count / period: UNKNOWN / three years
- costs included: UNKNOWN · code available: NO · rules complete: PARTIAL
- forward evidence: NO · live evidence: NO
- known limitations: delta-neutral by construction, therefore requires perpetual shorts and leverage; unrelated to a long-only spot runtime
- status here: REFERENCED_BY_OPP-0008

## S-20 — CF Bitcoin Kraken Perpetual Funding Rate Index (KFRI)

- URL: https://www.cfbenchmarks.com/data/indices/KFRI
- author/date: CF Benchmarks / launched 2025-03 (version UNKNOWN)
- family: structural carry (institutionalisation evidence)
- claim: a benchmark funding-rate index exists for BTC perpetuals, i.e. funding has become a benchmarked, institutionally tracked quantity
- claimed return: n/a
- trade count / period: n/a / from 2025-03
- costs included: NO · code available: NO · rules complete: NO
- forward evidence: NO · live evidence: NO
- known limitations: used only as crowding/institutionalisation evidence for the carry line
- status here: REFERENCED_BY_OPP-0008

## Round 2 (RFC-035S2) — strategy-first search

- reviewed_at_utc: 2026-10-08T00:00:00Z
- new sources: 44
- registry_hash (sha256): `5a32da456f021c2b63459edddd501a590ff4985058e371e424d8ba5f647543ae`
- evidence grades use the RFC-035S2 E0-E5 scale; the EVIDENCE_LEVEL column keeps the round-1 hierarchy so this file stays schema-compatible

| SOURCE_ID | CLASS | READ | GRADE | DEFINED | TITLE |
| --- | --- | --- | --- | --- | --- |
| S2-01 | PRIMARY_SOURCE | full_text | E1 | PARTIAL | [freqtrade-strategies — free buy/sell strategies for the Freqtrade bot](https://github.com/freqtrade/freqtrade-strategies) |
| S2-02 | PRIMARY_SOURCE | listing | E1 | NO | [Freqtrade documentation — strategy customization and backtesting](https://www.freqtrade.io/en/stable/strategy-customization/) |
| S2-03 | DERIVED_SOURCE | full_text | E1 | YES | [Strategy001.py — EMA20/50 cross with Heikin-Ashi confirmation (5m)](https://raw.githubusercontent.com/freqtrade/freqtrade-strategies/main/user_data/strategies/Strategy001.py) |
| S2-04 | PRIMARY_SOURCE | full_text | E1 | YES | [NostalgiaForInfinity — Freqtrade strategy (multi-pair, 5m)](https://github.com/iterativv/NostalgiaForInfinity) |
| S2-05 | PRIMARY_SOURCE | listing | E1 | PARTIAL | [Quant League (QuantConnect) — strategy entries with cloneable code](https://www.quantconnect.com/league/) |
| S2-06 | PRIMARY_SOURCE | full_text | E1 | PARTIAL | [Crypto and Stock Momentum — Quant League 2024-Q4 entry (EMA100 + RSI10 + dual Supertrend + TWAP)](https://www.quantconnect.com/league/18106/2024-q4/crypto-and-stock-momentum/) |
| S2-07 | PRIMARY_SOURCE | full_text | E1 | PARTIAL | [Quantiacs — exposure-based backtester, contests and platform documentation](https://quantiacs.com/documentation/en/quick_start/quick_start.html) |
| S2-08 | PRIMARY_SOURCE | full_text | E1 | YES | [Q24 Crypto Guide Strategy — Quantiacs crypto contest example (complete code)](https://quantiacs.com/documentation/en/examples/q24_crypto_guide.html) |
| S2-09 | PRIMARY_SOURCE | listing | E1 | NO | [quantiacs/toolbox — open-source backtester and evaluation code](https://github.com/quantiacs/toolbox) |
| S2-10 | PRIMARY_SOURCE | full_text | E1 | PARTIAL | [Revisiting Trend-following and Mean-reversion Strategies in Bitcoin (Quantpedia, 2024)](https://quantpedia.com/revisiting-trend-following-and-mean-reversion-strategies-in-bitcoin/) |
| S2-11 | DERIVED_SOURCE | listing | E1 | PARTIAL | [Trend-following and Mean-reversion in Bitcoin (Quantpedia, 2022) — the article the 2024 note revisits](https://quantpedia.com/trend-following-and-mean-reversion-in-bitcoin/) |
| S2-12 | PRIMARY_SOURCE | listing | E1 | PARTIAL | [Trend Following and Momentum Strategies on Bitcoin (QuantifiedStrategies)](https://www.quantifiedstrategies.com/trend-following-and-momentum-strategies-on-bitcoin/) |
| S2-13 | PRIMARY_SOURCE | listing | E1 | PARTIAL | [Systematic Trading: Resources (Robert Carver) — pysystemtrade and the book's rule set](https://www.systematicmoney.org/systematic-trading-resources) |
| S2-14 | PRIMARY_SOURCE | listing | E1 | YES | [pst-group/pysystemtrade — Systematic Trading in python](https://github.com/pst-group/pysystemtrade) |
| S2-15 | COMMENTARY | listing | E1 | NO | [Explore GitHub topic listing for freqtrade strategies](https://github.com/topics/freqtrade-strategies) |
| S2-16 | PRIMARY_SOURCE | full_text | E1 | PARTIAL | [Exploration of Algorithmic Trading Strategies for the Bitcoin Market (Crone, Brophy, Ward)](https://arxiv.org/html/2110.14936v1) |
| S2-17 | PRIMARY_SOURCE | full_text | E1 | NO | [Agent-Based Genetic Algorithm for Crypto Trading Strategy Optimization (CGA-Agent)](https://arxiv.org/html/2510.07943v1) |
| S2-18 | PRIMARY_SOURCE | listing | E1 | NO | [An Adaptive Multi-Agent Bitcoin Trading System (LLM-driven)](https://arxiv.org/html/2510.08068v2) |
| S2-19 | PRIMARY_SOURCE | listing | E1 | NO | [A Reflective LLM-based Agent to Guide Zero-shot Cryptocurrency Trading](https://arxiv.org/pdf/2407.09546) |
| S2-20 | PRIMARY_SOURCE | listing | E1 | PARTIAL | [Cross-sectional Momentum in Cryptocurrency Markets (Drogen)](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4322637) |
| S2-21 | PRIMARY_SOURCE | listing | E1 | PARTIAL | [High frequency momentum trading with cryptocurrencies (Chu, Chan, Zhang)](https://ideas.repec.org/a/eee/riibaf/v52y2020ics0275531919308062.html) |
| S2-22 | PRIMARY_SOURCE | listing | E1 | PARTIAL | [Deep Learning for Time Series Prediction & Decision Making (Lim, thesis) — Deep Momentum Networks](https://www.robots.ox.ac.uk/~sjrob/Theses/bryanLim.pdf) |
| S2-23 | PRIMARY_SOURCE | listing | E1 | PARTIAL | [Deep momentum networks with market trend dynamics (Song et al., PMC full text)](https://pmc.ncbi.nlm.nih.gov/articles/PMC12404547/) |
| S2-24 | PRIMARY_SOURCE | listing | E1 | NO | [jesse-ai/jesse — advanced crypto trading framework](https://github.com/jesse-ai/jesse) |
| S2-25 | PRIMARY_SOURCE | listing | E1 | PARTIAL | [Hummingbot — open-source market-making framework](https://hummingbot.org/) |
| S2-26 | PRIMARY_SOURCE | listing | E1 | PARTIAL | [OctoBot — open-source crypto trading bot and strategy catalogue](https://www.octobot.cloud/) |
| S2-27 | INDEPENDENT_REPLICATION | abstract_snippet | E1 | PARTIAL | [Karaptic Research — backtesting of published crypto strategies net of costs](https://karaptic.com/research/) |
| S2-28 | PRIMARY_SOURCE | listing | E1 | NO | [G-Research Crypto Forecasting — Kaggle competition (solutions and discussion)](https://www.kaggle.com/c/g-research-crypto-forecasting/discussion/327751) |
| S2-29 | COMMENTARY | listing | E1 | NO | [Wrapping up the G-Research Crypto Forecasting Competition](https://www.gresearch.com/news/wrapping-up-the-g-research-crypto-forecasting-competition/) |
| S2-30 | DERIVED_SOURCE | listing | E1 | NO | [Kaggle Solutions index — G-Research Crypto Forecasting](https://kaggle.curtischong.me/competitions/G-Research-Crypto-Forecasting) |
| S2-31 | DERIVED_SOURCE | listing | E1 | NO | [SanchitAjmera/G-Research-Crypto-Forecasting — competitor implementation](https://github.com/SanchitAjmera/G-Research-Crypto-Forecasting) |
| S2-32 | DERIVED_SOURCE | listing | E1 | NO | [qAp/gresearch_crypto_forecasting_kaggle — transformer solution](https://github.com/qAp/gresearch_crypto_forecasting_kaggle) |
| S2-33 | DERIVED_SOURCE | listing | E1 | NO | [coderback/drw-crypto-market-prediction — competition solution](https://github.com/coderback/drw-crypto-market-prediction) |
| S2-34 | PRIMARY_SOURCE | listing | E1 | PARTIAL | [anthonymakarewicz/bitcoin-momentum-trading — 5-minute momentum direction model](https://github.com/anthonymakarewicz/bitcoin-momentum-trading) |
| S2-35 | PRIMARY_SOURCE | listing | E1 | PARTIAL | [Adaptive Regime-Based Trading on Bitcoin: Backtesting and Walk-Forward Evaluation](https://www.researchgate.net/publication/395401021_Adaptive_Regime-Based_Trading_on_Bitcoin_Backtesting_and_Walk-Forward_Evaluation) |
| S2-36 | PRIMARY_SOURCE | listing | E1 | PARTIAL | [Momentum Trading in Cryptocurrencies: A Comparative Study of Time-Series and Cross-Sectional Strategies](https://www.researchgate.net/publication/406476873_Momentum_Trading_in_Cryptocurrencies_A_Comparative_Study_of_Time-Series_and_Cross-Sectional_Strategies) |
| S2-37 | PRIMARY_SOURCE | listing | E1 | PARTIAL | [Multi-Band Comparison Strategy (CRYPTO) — published Pine Script strategy](https://www.tradingview.com/script/bq0ELG1b-Multi-Band-Comparison-Strategy-CRYPTO/) |
| S2-38 | PRIMARY_SOURCE | listing | E1 | NO | [chibui191/bitcoin_volatility_forecasting — 7-day realised-volatility forecast](https://github.com/chibui191/bitcoin_volatility_forecasting) |
| S2-39 | COMMENTARY | listing | E1 | NO | [awesome-systematic-trading — curated list of strategies, libraries and papers](https://pypi.org/project/awesome-systematic-trading/) |
| S2-40 | PRIMARY_SOURCE | listing | E1 | NO | [QuantConnect Live Trading documentation (how live/paper evidence is produced)](https://www.quantconnect.com/docs/v2/cloud-platform/live-trading) |
| S2-41 | PRIMARY_SOURCE | listing | E1 | PARTIAL | [Quantiacs competition filters and FAQ (live paper gate)](https://quantiacs.com/documentation/en/user_guide/passFilters.html) |
| S2-42 | PRIMARY_SOURCE | listing | E1 | NO | [vectorbt — vectorised backtesting with research-backed examples](https://github.com/polakowo/vectorbt) |
| S2-43 | PRIMARY_SOURCE | listing | E1 | NO | [backtrader — event-driven backtesting framework and strategy gallery](https://github.com/mementum/backtrader) |
| S2-44 | PRIMARY_SOURCE | listing | E1 | PARTIAL | [QuantConnect Strategies — the successor venue to Quant League](https://www.quantconnect.com/strategies/) |

Round-2 detail, per-field status and the rejection log live in `reports/rfc035/search_round_2/`.
