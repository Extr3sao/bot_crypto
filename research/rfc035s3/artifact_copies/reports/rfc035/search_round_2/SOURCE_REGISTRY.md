# RFC-035S2 — external strategy source registry (round 2)

- retrieved_at_utc: 2026-10-08T00:00:00Z
- sources reviewed this round: 44
- registry_hash (sha256): `5a32da456f021c2b63459edddd501a590ff4985058e371e424d8ba5f647543ae`

Evidence scale: E5 verified live execution > E4 independently verified forward/paper > E3 independent historical replication > E2 author OOS/backtest with reproducible code > E1 author backtest only > E0 unsupported claim.

`read` says how much of the source was actually read: `full_text` = fetched and used, `abstract_snippet` = only a summary was visible, `listing` = only a search-result listing/snippet was seen. Nothing below was inferred beyond the read level stated.

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

## S2-01 — freqtrade-strategies — free buy/sell strategies for the Freqtrade bot

- URL: https://github.com/freqtrade/freqtrade-strategies
- class / read / grade: PRIMARY_SOURCE · full_text · E1 (AUTHOR_BACKTEST)
- publisher / date / version: Freqtrade project / contributors · 2026 (rolling main branch) · UNKNOWN
- market / assets / timeframe: crypto spot pairs · USER_SELECTED pairlist (40-80 pairs recommended in NFI; repo leaves it to the user) · 5m-1h per strategy
- strategy family: technical entry/exit, hyperopt-tuned parameters
- claimed edge: each strategy ships minimal_roi, stoploss, buy/sell signals and indicators; the README declares results depend on the user's pairs, timeframe and timerange
- claimed return: UNKNOWN (README presents results as links/images, no numbers in the text)
- trades / period: UNKNOWN · user-chosen timerange
- costs included: NO (strategy files carry no cost model) · code: YES · forward: NO · live: NO
- limitations: repo states the strategies are starting points, not ready-to-use systems; 'further optimization to the exchange and pairs used will usually result in better outcomes'
- status: REFERENCED_BY_C-02

## S2-02 — Freqtrade documentation — strategy customization and backtesting

- URL: https://www.freqtrade.io/en/stable/strategy-customization/
- class / read / grade: PRIMARY_SOURCE · listing · E1 (AUTHOR_BACKTEST)
- publisher / date / version: Freqtrade project · UNKNOWN · UNKNOWN
- market / assets / timeframe: crypto spot/futures · user-selected · any supported timeframe
- strategy family: framework documentation
- claimed edge: defines the semantics of entry/exit signals, ROI, stoploss and callbacks
- claimed return: UNKNOWN
- trades / period: UNKNOWN · UNKNOWN
- costs included: UNKNOWN · code: NO · forward: NO · live: NO
- limitations: framework, not a strategy
- status: SUPPORT_SOURCE_FOR_C-02

## S2-03 — Strategy001.py — EMA20/50 cross with Heikin-Ashi confirmation (5m)

- URL: https://raw.githubusercontent.com/freqtrade/freqtrade-strategies/main/user_data/strategies/Strategy001.py
- class / read / grade: DERIVED_SOURCE · full_text · E1 (AUTHOR_BACKTEST)
- publisher / date / version: Gerald Lonlas (freqtrade-strategies) · repo main branch · UNKNOWN
- market / assets / timeframe: crypto spot · USER_SELECTED (strategy declares none) · 5m
- strategy family: trend-following moving-average cross
- claimed edge: enter on qtpylib.crossed_above(ema20, ema50) with heikin-ashi green bar and ha_close > ema20; exit on crossed_above(ema50, ema100) with ha_close < ema20 and red bar; minimal_roi {60:0.01,30:0.03,20:0.04,0:0.05}, stoploss -0.10, order_types entry/exit limit, stoploss market
- claimed return: UNKNOWN (no backtest numbers in the file)
- trades / period: UNKNOWN · UNKNOWN (nothing is published)
- costs included: NO · code: YES · forward: NO · live: NO
- limitations: the file itself notes results are overridden by the user's config (minimal_roi/stoploss) and that the pairlist is the user's choice
- status: REFERENCED_BY_C-02

## S2-04 — NostalgiaForInfinity — Freqtrade strategy (multi-pair, 5m)

- URL: https://github.com/iterativv/NostalgiaForInfinity
- class / read / grade: PRIMARY_SOURCE · full_text · E1 (AUTHOR_BACKTEST)
- publisher / date / version: iterativv · rolling (releases + main commits) · releases / main commits
- market / assets / timeframe: crypto spot pairs (USDT/USDC preferred by the author) · 40-80 pairs, user-selected ('a pairlist with 40 to 80 pairs. Volume pairlist works well') · 5m (the README says the timeframe must not be overridden)
- strategy family: multi-condition long/short entry ladder with ROI/stoploss exit ladders
- claimed edge: the README states the strategy's rules live in code and that backtesting results are in the comments of individual commit pages; no summary metric is published in the README
- claimed return: UNKNOWN in the README
- trades / period: UNKNOWN in the README · UNKNOWN (per commit comment)
- costs included: NO (not stated) · code: YES · forward: NO · live: NO
- limitations: README: 'use between 6 and 12 open trades, with unlimited stake' (a range, not a fixed size); the repository ships an auto-updater that keeps changing the strategy, so a replication must pin a commit or release tag
- status: REFERENCED_BY_C-01

## S2-05 — Quant League (QuantConnect) — strategy entries with cloneable code

- URL: https://www.quantconnect.com/league/
- class / read / grade: PRIMARY_SOURCE · listing · E1 (AUTHOR_BACKTEST)
- publisher / date / version: QuantConnect community · quarterly, Q4-2025 last Quant League · UNKNOWN
- market / assets / timeframe: multi-asset incl. crypto · author-selected · author-selected
- strategy family: competition strategies (varied)
- claimed edge: QuantConnect's own page: 'Quant League is an open-source research platform'; strategies can be cloned and backtested, community upvotes gate publication of research posts
- claimed return: UNKNOWN
- trades / period: UNKNOWN · UNKNOWN
- costs included: UNKNOWN · code: NO · forward: NO · live: NO
- limitations: the league is being replaced by 'Strategies'; entries can be drafts (the crypto momentum entry read for C-03 is marked 'pending review') and no result was readable without an account
- status: SOURCE_HUB_FOR_C-03

## S2-06 — Crypto and Stock Momentum — Quant League 2024-Q4 entry (EMA100 + RSI10 + dual Supertrend + TWAP)

- URL: https://www.quantconnect.com/league/18106/2024-q4/crypto-and-stock-momentum/
- class / read / grade: PRIMARY_SOURCE · full_text · E1 (AUTHOR_BACKTEST)
- publisher / date / version: Archit singh (QuantConnect community) · 2024-10-01 · UNKNOWN
- market / assets / timeframe: BTC, ETH and US large-cap equities · 'Bitcoin, Ethereum, selected stocks among the top 1000 companies ... based on best-fitted market structure for our strategy' (self-selected) · daily decisions, end-of-day execution
- strategy family: momentum with trend/RSI/TWAP confirmation
- claimed edge: buy requires price > 100-day EMA, 10-day RSI > 50, both Supertrend indicators (10-day, multipliers 2.5 and 3) flipped up, and price > 20% below the weekly TWAP for BTC/ETH (4% for stocks); exit on the Supertrend bend
- claimed return: UNKNOWN (page exposes an 'Update Backtest' widget, no numbers were readable)
- trades / period: UNKNOWN · UNKNOWN
- costs included: UNKNOWN · code: YES (clone in QuantConnect) · forward: NO · live: NO
- limitations: marked 'pending review'; 5.6k views but no published metrics; the stock sleeve is outside this project's crypto universe
- status: REFERENCED_BY_C-03

## S2-07 — Quantiacs — exposure-based backtester, contests and platform documentation

- URL: https://quantiacs.com/documentation/en/quick_start/quick_start.html
- class / read / grade: PRIMARY_SOURCE · full_text · E1 (AUTHOR_BACKTEST)
- publisher / date / version: Quantiacs · rolling (Q24 contest cycle) · UNKNOWN
- market / assets / timeframe: futures, stocks, crypto daily · platform universe (crypto top-10 by liquidity for the crypto contest) · daily
- strategy family: platform / contest rules
- claimed edge: the documentation describes an allocation-weights interface: 'allocate weights according to the price change of the asset relative to the day before'; strategies are submitted, backtested and can enter daily live paper trading
- claimed return: UNKNOWN (per-strategy results live in the user area)
- trades / period: UNKNOWN · 2016-01-01 in-sample start for the crypto contest
- costs included: UNKNOWN (platform stats) · code: YES (examples and toolbox) · forward: NO · live: NO
- limitations: the contest requires platform data only; public per-strategy live results are not readable without an account
- status: SOURCE_HUB_FOR_C-07

## S2-08 — Q24 Crypto Guide Strategy — Quantiacs crypto contest example (complete code)

- URL: https://quantiacs.com/documentation/en/examples/q24_crypto_guide.html
- class / read / grade: PRIMARY_SOURCE · full_text · E1 (AUTHOR_BACKTEST)
- publisher / date / version: Quantiacs · Q24 contest cycle · UNKNOWN
- market / assets / timeframe: crypto daily spot (long only) · top 10 crypto by market capitalisation, redefined monthly from coinmarketcap data, stablecoins excluded ('is_liquid' field) · daily
- strategy family: dual-SMA trend filter with RSI confirmation, equal-weight long-only
- claimed edge: signal = 1 where SMA15 > SMA34 and is_liquid, multiplied by (RSI14 < 34 or RSI14 > 68); weights are cleaned/normalised by qnout.clean into long-only crypto daily allocation; no stop, no target, exit is the signal flipping to 0
- claimed return: UNKNOWN (the page shows the backtest call, not the numbers)
- trades / period: UNKNOWN · in-sample from 2016-01-01; minimum in-sample Sharpe 1.0 required to be valid
- costs included: UNKNOWN (the platform's calc_stat decides) · code: YES · forward: YES for the contest as a whole (strategies above Sharpe 1 enter daily live paper trading) · live: NO (no public per-strategy track record)
- limitations: long-only by contest rule; benchmark is the platform's CRYPTO10 cap-weighted index; the example page shows a download error for the index weights, so the benchmark call could not be reproduced while reading
- status: REFERENCED_BY_C-07

## S2-09 — quantiacs/toolbox — open-source backtester and evaluation code

- URL: https://github.com/quantiacs/toolbox
- class / read / grade: PRIMARY_SOURCE · listing · E1 (AUTHOR_BACKTEST)
- publisher / date / version: Quantiacs · UNKNOWN · UNKNOWN
- market / assets / timeframe: multi-asset · platform universe · daily
- strategy family: engine / statistics
- claimed edge: the toolbox contains the backtester and the statistics the contest ranks on (Sharpe-based filters)
- claimed return: UNKNOWN
- trades / period: UNKNOWN · UNKNOWN
- costs included: UNKNOWN · code: NO · forward: NO · live: NO
- limitations: engine, not a strategy
- status: SUPPORT_SOURCE_FOR_C-07

## S2-10 — Revisiting Trend-following and Mean-reversion Strategies in Bitcoin (Quantpedia, 2024)

- URL: https://quantpedia.com/revisiting-trend-following-and-mean-reversion-strategies-in-bitcoin/
- class / read / grade: PRIMARY_SOURCE · full_text · E1 (AUTHOR_BACKTEST)
- publisher / date / version: Quantpedia · 2024-09-12 · UNKNOWN
- market / assets / timeframe: BTC daily spot · BTC · daily
- strategy family: breakout (MAX) and mean-reversion (MIN) on rolling lookbacks
- claimed edge: MAX: buy BTC when it prints the maximum price of the previous x days; MIN: buy at the x-day minimum; x = 10/20/30/40/50 evaluated, 10 nominated as most effective. In-sample 2015-11-11..2024-08-20 shows both remain effective; the article's own out-of-sample 2022-02-04..2024-08-20 keeps MAX alive and says buying at MIN 'has not performed well'
- claimed return: UNKNOWN (tables/graphs were not captured numerically while reading)
- trades / period: UNKNOWN · 2015-11-11..2024-08-20 in sample; 2022-02-04..2024-08-20 out of sample
- costs included: NO (no cost model is mentioned) · code: NO · forward: NO · live: NO
- limitations: no holding/exit rule, no position sizing, no fees or slippage; the nominated x=10 is the best of five lookbacks tested, so the parameter choice carries selection risk; the OOS test is run by the same author
- status: REFERENCED_BY_C-04

## S2-11 — Trend-following and Mean-reversion in Bitcoin (Quantpedia, 2022) — the article the 2024 note revisits

- URL: https://quantpedia.com/trend-following-and-mean-reversion-in-bitcoin/
- class / read / grade: DERIVED_SOURCE · listing · E1 (AUTHOR_BACKTEST)
- publisher / date / version: Quantpedia · 2022-03-15 · UNKNOWN
- market / assets / timeframe: BTC daily spot · BTC · daily
- strategy family: breakout / mean-reversion on rolling lookbacks
- claimed edge: original study of moving averages, time-series and cross-sectional momentum and mean reversion in Bitcoin over 2015-11..2022-02; the 2024 note states the strategies are 'slightly less effective' over the longer sample
- claimed return: UNKNOWN
- trades / period: UNKNOWN · UNKNOWN
- costs included: NO · code: NO · forward: NO · live: NO
- limitations: only the search-result summary was read; not used on its own
- status: SUPERSEDED_BY_S2-10

## S2-12 — Trend Following and Momentum Strategies on Bitcoin (QuantifiedStrategies)

- URL: https://www.quantifiedstrategies.com/trend-following-and-momentum-strategies-on-bitcoin/
- class / read / grade: PRIMARY_SOURCE · listing · E1 (AUTHOR_BACKTEST)
- publisher / date / version: QuantifiedStrategies · rolling · UNKNOWN
- market / assets / timeframe: BTC · BTC · daily/long-term
- strategy family: trend following / momentum
- claimed edge: search-result summary describes a long-term backtest of trend and momentum rules on Bitcoin with 127 trades and exponential equity growth; the page itself refused to serve content to this host ('Bot Verification')
- claimed return: UNKNOWN
- trades / period: 127 (per the search snippet only) · UNKNOWN
- costs included: UNKNOWN · code: NO · forward: NO · live: NO
- limitations: fetch blocked by bot verification; nothing beyond the snippet is claimed
- status: CONTRIBUTES_COUNTER_EVIDENCE

## S2-13 — Systematic Trading: Resources (Robert Carver) — pysystemtrade and the book's rule set

- URL: https://www.systematicmoney.org/systematic-trading-resources
- class / read / grade: PRIMARY_SOURCE · listing · E1 (AUTHOR_BACKTEST)
- publisher / date / version: Robert Carver · UNKNOWN · UNKNOWN
- market / assets / timeframe: futures (multi-market) · futures portfolio · daily
- strategy family: diversified trend following with volatility targeting
- claimed edge: points to pysystemtrade and the book's framework: EWMAC-style trend forecasts, forecast scaling, volatility targeting, and explicit cost accounting
- claimed return: UNKNOWN
- trades / period: UNKNOWN · UNKNOWN
- costs included: UNKNOWN · code: NO · forward: NO · live: NO
- limitations: futures universe with leverage and shorting; the page itself was only read at listing level
- status: SOURCE_HUB_FOR_C-06

## S2-14 — pst-group/pysystemtrade — Systematic Trading in python

- URL: https://github.com/pst-group/pysystemtrade
- class / read / grade: PRIMARY_SOURCE · listing · E1 (AUTHOR_BACKTEST)
- publisher / date / version: Robert Carver / pst-group · UNKNOWN · UNKNOWN
- market / assets / timeframe: futures, ~100 markets · configured instrument list (no crypto by default) · daily
- strategy family: diversified trend following (EWMAC + carry + breakout) with volatility targeting
- claimed edge: a complete, production-grade implementation of the book's system including forecast combination and cost/slippage modelling
- claimed return: UNKNOWN
- trades / period: UNKNOWN · UNKNOWN
- costs included: YES (the system models costs and turnover) · code: YES · forward: NO · live: NO
- limitations: not a crypto strategy; a long/cash spot BTC version would be our own design, not an external replication
- status: REFERENCED_BY_C-06

## S2-15 — Explore GitHub topic listing for freqtrade strategies

- URL: https://github.com/topics/freqtrade-strategies
- class / read / grade: COMMENTARY · listing · E1 (AUTHOR_BACKTEST)
- publisher / date / version: GitHub · UNKNOWN · UNKNOWN
- market / assets / timeframe: crypto · UNKNOWN · UNKNOWN
- strategy family: not a strategy source
- claimed edge: index of third-party strategy repositories (one of the places a complete external strategy could appear)
- claimed return: UNKNOWN
- trades / period: UNKNOWN · UNKNOWN
- costs included: UNKNOWN · code: NO · forward: NO · live: NO
- limitations: index only; individual repositories carry their own evidence quality
- status: SEARCH_VENUE

## S2-16 — Exploration of Algorithmic Trading Strategies for the Bitcoin Market (Crone, Brophy, Ward)

- URL: https://arxiv.org/html/2110.14936v1
- class / read / grade: PRIMARY_SOURCE · full_text · E1 (AUTHOR_BACKTEST)
- publisher / date / version: N. Crone, E. Brophy, T. Ward (Dublin City University) · 2021-09 · UNKNOWN
- market / assets / timeframe: BTC daily · BTC · daily
- strategy family: machine-learning direction classification with a risk-tolerance trading rule
- claimed edge: next-day direction classifiers; a binary long/cash rule and a risk-tolerance variant are traded on unseen Q1-2021 data: an average profit of 86% matching buy-and-hold, +12.5% over buy-and-hold with the confidence-based rule
- claimed return: +86% over three months (Q1-2021) versus buy-and-hold; +12.5% relative with the risk-tolerance rule
- trades / period: UNKNOWN · training periods up to 2019; unseen test Q1-2021
- costs included: NO (no fee or slippage model is mentioned) · code: PARTIAL (the reproduced benchmark's code is on GitHub; the paper's own models are not published) · forward: NO · live: NO
- limitations: documents that a prior benchmark (Mudassir et al. 2020) trained on its test data and mis-applied PCA — useful as counter-evidence about the literature's quality; no cost model
- status: REFERENCED_BY_C-13

## S2-17 — Agent-Based Genetic Algorithm for Crypto Trading Strategy Optimization (CGA-Agent)

- URL: https://arxiv.org/html/2510.07943v1
- class / read / grade: PRIMARY_SOURCE · full_text · E1 (AUTHOR_BACKTEST)
- publisher / date / version: Q. Tian, C. Liang, K. Hong, R. Li · 2025-10-09 · UNKNOWN
- market / assets / timeframe: crypto (BTC, ETH, BNB) · BTC, ETH, BNB · UNKNOWN
- strategy family: genetic-algorithm parameter optimisation of trading strategies
- claimed edge: claims total-return improvements of 29%, 550% and 169% on the three assets versus baselines through adaptive parameter optimisation
- claimed return: +29% / +550% / +169% total return (author-reported, no cost model read)
- trades / period: UNKNOWN · UNKNOWN
- costs included: UNKNOWN · code: NO · forward: NO · live: NO
- limitations: parameter search by construction: the result is a search procedure, not a fixed rule set; no out-of-sample protocol was visible in the part read
- status: REFERENCED_BY_C-12

## S2-18 — An Adaptive Multi-Agent Bitcoin Trading System (LLM-driven)

- URL: https://arxiv.org/html/2510.08068v2
- class / read / grade: PRIMARY_SOURCE · listing · E1 (AUTHOR_BACKTEST)
- publisher / date / version: UNKNOWN (preprint) · 2025-11-14 · UNKNOWN
- market / assets / timeframe: BTC · BTC · UNKNOWN
- strategy family: LLM multi-agent alpha generation and portfolio construction
- claimed edge: uses LLMs for alpha generation and portfolio decisions
- claimed return: UNKNOWN
- trades / period: UNKNOWN · UNKNOWN
- costs included: UNKNOWN · code: NO · forward: NO · live: NO
- limitations: only the abstract was read; nothing about a fixed rule set
- status: REFERENCED_BY_C-17

## S2-19 — A Reflective LLM-based Agent to Guide Zero-shot Cryptocurrency Trading

- URL: https://arxiv.org/pdf/2407.09546
- class / read / grade: PRIMARY_SOURCE · listing · E1 (AUTHOR_BACKTEST)
- publisher / date / version: Y. Li et al. · 2024 · UNKNOWN
- market / assets / timeframe: crypto (multiple coins) · crypto portfolio · UNKNOWN
- strategy family: LLM zero-shot trading agent
- claimed edge: an LLM agent that trades crypto zero-shot, benchmarked against baselines
- claimed return: UNKNOWN
- trades / period: UNKNOWN · UNKNOWN
- costs included: UNKNOWN · code: NO · forward: NO · live: NO
- limitations: abstract-level read; not reproducible as a fixed rule set
- status: REFERENCED_BY_C-11

## S2-20 — Cross-sectional Momentum in Cryptocurrency Markets (Drogen)

- URL: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4322637
- class / read / grade: PRIMARY_SOURCE · listing · E1 (AUTHOR_BACKTEST)
- publisher / date / version: L. Drogen · 2023 · UNKNOWN
- market / assets / timeframe: crypto cross-section · multi-coin universe · weekly/monthly (not read in detail)
- strategy family: cross-sectional momentum with several construction variants
- claimed edge: reviews the evidence for price momentum in crypto and builds applicable long/short strategies from it
- claimed return: UNKNOWN
- trades / period: UNKNOWN · UNKNOWN
- costs included: UNKNOWN · code: NO · forward: NO · live: NO
- limitations: abstract-level read; long/short construction is outside the long/cash spot runtime
- status: CONTRIBUTES_COUNTER_EVIDENCE

## S2-21 — High frequency momentum trading with cryptocurrencies (Chu, Chan, Zhang)

- URL: https://ideas.repec.org/a/eee/riibaf/v52y2020ics0275531919308062.html
- class / read / grade: PRIMARY_SOURCE · listing · E1 (AUTHOR_BACKTEST)
- publisher / date / version: J. Chu et al. · 2020 · UNKNOWN
- market / assets / timeframe: crypto (liquid majors) · multiple coins · high frequency (minutes to hours)
- strategy family: high-frequency momentum
- claimed edge: implements two variations of a high-frequency momentum strategy on cryptocurrencies and reports profitability in 2017-2018
- claimed return: UNKNOWN
- trades / period: UNKNOWN · UNKNOWN
- costs included: UNKNOWN at this read level · code: NO · forward: NO · live: NO
- limitations: index/abstract only; the 2017-2018 crypto microstructure is not representative of a 200 USDT spot venue today
- status: CONTRIBUTES_COUNTER_EVIDENCE

## S2-22 — Deep Learning for Time Series Prediction & Decision Making (Lim, thesis) — Deep Momentum Networks

- URL: https://www.robots.ox.ac.uk/~sjrob/Theses/bryanLim.pdf
- class / read / grade: PRIMARY_SOURCE · listing · E1 (AUTHOR_BACKTEST)
- publisher / date / version: Bryan Lim (supervisors Zohren, Roberts) · UNKNOWN (thesis) · UNKNOWN
- market / assets / timeframe: futures and ETF universes · multi-asset · daily
- strategy family: deep momentum networks: NN-based trading rules inside volatility-scaled time-series momentum
- claimed edge: DMNs improve on standard time-series momentum signals; the framework is stated in the paper/thesis
- claimed return: UNKNOWN
- trades / period: UNKNOWN · UNKNOWN
- costs included: PARTIAL (the literature reports spread/turnover assumptions, not read here) · code: NO · forward: NO · live: NO
- limitations: listing-level read; training-dependent strategy with no repository located
- status: REFERENCED_BY_C-16

## S2-23 — Deep momentum networks with market trend dynamics (Song et al., PMC full text)

- URL: https://pmc.ncbi.nlm.nih.gov/articles/PMC12404547/
- class / read / grade: PRIMARY_SOURCE · listing · E1 (AUTHOR_BACKTEST)
- publisher / date / version: J. Song et al. · 2025 · UNKNOWN
- market / assets / timeframe: futures / equity indices · multi-asset · daily
- strategy family: deep momentum networks with trend dynamics
- claimed edge: extends Lim/Zohren/Roberts DMNs by modelling market trend dynamics
- claimed return: UNKNOWN
- trades / period: UNKNOWN · UNKNOWN
- costs included: UNKNOWN · code: NO · forward: NO · live: NO
- limitations: listing-level read; no code
- status: REFERENCED_BY_C-16

## S2-24 — jesse-ai/jesse — advanced crypto trading framework

- URL: https://github.com/jesse-ai/jesse
- class / read / grade: PRIMARY_SOURCE · listing · E1 (AUTHOR_BACKTEST)
- publisher / date / version: Jesse AI · UNKNOWN · UNKNOWN
- market / assets / timeframe: crypto (spot/futures) · user-selected · any
- strategy family: framework for user strategies
- claimed edge: framework with backtesting, optimisation and live trading; ships example strategies, not a canonical externally-tested system
- claimed return: UNKNOWN
- trades / period: UNKNOWN · UNKNOWN
- costs included: UNKNOWN · code: YES · forward: NO · live: NO
- limitations: no canonical strategy with a fixed period and published metrics was found in it
- status: SEARCH_VENUE

## S2-25 — Hummingbot — open-source market-making framework

- URL: https://hummingbot.org/
- class / read / grade: PRIMARY_SOURCE · listing · E1 (AUTHOR_BACKTEST)
- publisher / date / version: Hummingbot Foundation · UNKNOWN · UNKNOWN
- market / assets / timeframe: crypto CEX/DEX · user-selected · tick/minute
- strategy family: market making / liquidity provision controllers
- claimed edge: documented controllers (e.g. pure market making) with parameters and a backtesting dashboard
- claimed return: UNKNOWN
- trades / period: UNKNOWN · UNKNOWN
- costs included: PARTIAL (fees are modelled in its dashboard backtests) · code: YES · forward: NO · live: NO
- limitations: listing-level read; the strategies are liquidity provision, not directional signals
- status: REVIEWED_NOT_SHORTLISTED

## S2-26 — OctoBot — open-source crypto trading bot and strategy catalogue

- URL: https://www.octobot.cloud/
- class / read / grade: PRIMARY_SOURCE · listing · E1 (AUTHOR_BACKTEST)
- publisher / date / version: Drakkar-Software · UNKNOWN · UNKNOWN
- market / assets / timeframe: crypto · user-selected · any
- strategy family: grid/DCA/technical strategies
- claimed edge: offers ready-made strategies with visual configuration (grid, DCA, TA)
- claimed return: UNKNOWN
- trades / period: UNKNOWN · UNKNOWN
- costs included: PARTIAL (exchange fees configurable) · code: YES · forward: NO · live: NO
- limitations: listing-level read; no published track record
- status: SEARCH_VENUE

## S2-27 — Karaptic Research — backtesting of published crypto strategies net of costs

- URL: https://karaptic.com/research/
- class / read / grade: INDEPENDENT_REPLICATION · abstract_snippet · E1 (AUTHOR_BACKTEST)
- publisher / date / version: Karaptic · rolling · UNKNOWN
- market / assets / timeframe: crypto (Binance spot) · various · varies per note
- strategy family: replication series: literature review -> gross -> net-of-costs
- claimed edge: the site describes itself as 'quantitative research and backtesting of published crypto trading strategies on real Binance data, net of fees, slippage, and execution costs'; the published note summarised on the index reports an 'ALIVE' tier with an 85% win rate and a narrower tier at 100% over eleven weekly cohorts on the pre-patch walk-forward sample, and 63% once detection timestamps were made honest
- claimed return: win rates 85%/100% (pre-patch walk-forward) and 63% (honest timestamps), as summarised on the index page
- trades / period: UNKNOWN · UNKNOWN
- costs included: YES (net of fees, slippage and execution costs, per the site's own description) · code: NO (notes, not repositories) · forward: NO · live: NO
- limitations: only the index/summary was read; the underlying notes and the full rule sets were not fetched, so no candidate is built on it here
- status: WATCHED_SOURCE_FOR_ROUND_3

## S2-28 — G-Research Crypto Forecasting — Kaggle competition (solutions and discussion)

- URL: https://www.kaggle.com/c/g-research-crypto-forecasting/discussion/327751
- class / read / grade: PRIMARY_SOURCE · listing · E1 (AUTHOR_BACKTEST)
- publisher / date / version: G-Research / Kaggle community · 2022 · UNKNOWN
- market / assets / timeframe: 14 crypto assets · 14 crypto assets · minute bars, short-term return forecast
- strategy family: forecasting competition (not a trading strategy)
- claimed edge: predict short-term returns; scored by correlation on a held-out period
- claimed return: UNKNOWN
- trades / period: UNKNOWN · UNKNOWN
- costs included: NO (no trading simulation) · code: YES for winner write-ups · forward: NO · live: NO
- limitations: forecast-only; the competition's own metric is correlation, not PnL
- status: REFERENCED_BY_C-08

## S2-29 — Wrapping up the G-Research Crypto Forecasting Competition

- URL: https://www.gresearch.com/news/wrapping-up-the-g-research-crypto-forecasting-competition/
- class / read / grade: COMMENTARY · listing · E1 (AUTHOR_BACKTEST)
- publisher / date / version: G-Research · 2022-05-30 · UNKNOWN
- market / assets / timeframe: crypto · UNKNOWN · UNKNOWN
- strategy family: not a strategy source
- claimed edge: organiser summary of the 2022 competition and its outcomes
- claimed return: UNKNOWN
- trades / period: UNKNOWN · UNKNOWN
- costs included: UNKNOWN · code: NO · forward: NO · live: NO
- limitations: context only
- status: CONTEXT

## S2-30 — Kaggle Solutions index — G-Research Crypto Forecasting

- URL: https://kaggle.curtischong.me/competitions/G-Research-Crypto-Forecasting
- class / read / grade: DERIVED_SOURCE · listing · E1 (AUTHOR_BACKTEST)
- publisher / date / version: Curtis Chong · UNKNOWN · UNKNOWN
- market / assets / timeframe: UNKNOWN · UNKNOWN · UNKNOWN
- strategy family: not a strategy source
- claimed edge: collects winner notebooks and code links for the competition
- claimed return: UNKNOWN
- trades / period: UNKNOWN · UNKNOWN
- costs included: UNKNOWN · code: NO · forward: NO · live: NO
- limitations: index of derived work
- status: SEARCH_VENUE

## S2-31 — SanchitAjmera/G-Research-Crypto-Forecasting — competitor implementation

- URL: https://github.com/SanchitAjmera/G-Research-Crypto-Forecasting
- class / read / grade: DERIVED_SOURCE · listing · E1 (AUTHOR_BACKTEST)
- publisher / date / version: S. Ajmera · UNKNOWN · UNKNOWN
- market / assets / timeframe: crypto · UNKNOWN · UNKNOWN
- strategy family: not a strategy source
- claimed edge: ML pipeline reproducing a competition submission
- claimed return: UNKNOWN
- trades / period: UNKNOWN · UNKNOWN
- costs included: UNKNOWN · code: NO · forward: NO · live: NO
- limitations: forecasting code without a trading layer
- status: SEARCH_VENUE

## S2-32 — qAp/gresearch_crypto_forecasting_kaggle — transformer solution

- URL: https://github.com/qAp/gresearch_crypto_forecasting_kaggle
- class / read / grade: DERIVED_SOURCE · listing · E1 (AUTHOR_BACKTEST)
- publisher / date / version: qAp · UNKNOWN · UNKNOWN
- market / assets / timeframe: crypto · UNKNOWN · UNKNOWN
- strategy family: not a strategy source
- claimed edge: Spacetimeformer-based forecasting solution
- claimed return: UNKNOWN
- trades / period: UNKNOWN · UNKNOWN
- costs included: UNKNOWN · code: NO · forward: NO · live: NO
- limitations: forecasting only; heavy training requirement
- status: SEARCH_VENUE

## S2-33 — coderback/drw-crypto-market-prediction — competition solution

- URL: https://github.com/coderback/drw-crypto-market-prediction
- class / read / grade: DERIVED_SOURCE · listing · E1 (AUTHOR_BACKTEST)
- publisher / date / version: coderback · UNKNOWN · UNKNOWN
- market / assets / timeframe: crypto · UNKNOWN · UNKNOWN
- strategy family: not a strategy source
- claimed edge: feature engineering and modelling for a crypto prediction competition
- claimed return: UNKNOWN
- trades / period: UNKNOWN · UNKNOWN
- costs included: UNKNOWN · code: NO · forward: NO · live: NO
- limitations: forecasting only; no trading rules
- status: SEARCH_VENUE

## S2-34 — anthonymakarewicz/bitcoin-momentum-trading — 5-minute momentum direction model

- URL: https://github.com/anthonymakarewicz/bitcoin-momentum-trading
- class / read / grade: PRIMARY_SOURCE · listing · E1 (AUTHOR_BACKTEST)
- publisher / date / version: A. Makarewicz · UNKNOWN · UNKNOWN
- market / assets / timeframe: BTC · BTC · 5-minute bars
- strategy family: ML classification of short-horizon momentum
- claimed edge: predicts the direction of BTC momentum at a 5-minute interval from OHLCV features, then trades the prediction
- claimed return: UNKNOWN
- trades / period: UNKNOWN · UNKNOWN
- costs included: UNKNOWN · code: YES · forward: NO · live: NO
- limitations: listing-level read; training-dependent model; no cost model seen
- status: REFERENCED_BY_C-09

## S2-35 — Adaptive Regime-Based Trading on Bitcoin: Backtesting and Walk-Forward Evaluation

- URL: https://www.researchgate.net/publication/395401021_Adaptive_Regime-Based_Trading_on_Bitcoin_Backtesting_and_Walk-Forward_Evaluation
- class / read / grade: PRIMARY_SOURCE · listing · E1 (AUTHOR_BACKTEST)
- publisher / date / version: UNKNOWN (record) · 2025-09-10 · UNKNOWN
- market / assets / timeframe: BTC · BTC · 15-minute bars, January 2021 to August 2025
- strategy family: regime-adaptive technical strategy with walk-forward evaluation
- claimed edge: abstract claims consistent profitability under walk-forward evaluation on 15-minute Bitcoin data
- claimed return: UNKNOWN
- trades / period: UNKNOWN · UNKNOWN
- costs included: UNKNOWN · code: NO · forward: NO · live: NO
- limitations: record/abstract only; no rule text and no code were read
- status: REFERENCED_BY_C-10

## S2-36 — Momentum Trading in Cryptocurrencies: A Comparative Study of Time-Series and Cross-Sectional Strategies

- URL: https://www.researchgate.net/publication/406476873_Momentum_Trading_in_Cryptocurrencies_A_Comparative_Study_of_Time-Series_and_Cross-Sectional_Strategies
- class / read / grade: PRIMARY_SOURCE · listing · E1 (AUTHOR_BACKTEST)
- publisher / date / version: UNKNOWN (record) · UNKNOWN · UNKNOWN
- market / assets / timeframe: crypto · multi-coin · multi-horizon EMA
- strategy family: time-series vs cross-sectional momentum comparison
- claimed edge: examines the profitability of momentum strategies with a multi-horizon EMA design
- claimed return: UNKNOWN
- trades / period: UNKNOWN · UNKNOWN
- costs included: UNKNOWN · code: NO · forward: NO · live: NO
- limitations: abstract-level only
- status: REVIEWED_NOT_SHORTLISTED

## S2-37 — Multi-Band Comparison Strategy (CRYPTO) — published Pine Script strategy

- URL: https://www.tradingview.com/script/bq0ELG1b-Multi-Band-Comparison-Strategy-CRYPTO/
- class / read / grade: PRIMARY_SOURCE · listing · E1 (AUTHOR_BACKTEST)
- publisher / date / version: TradingView community · 2025-01-20 · UNKNOWN
- market / assets / timeframe: crypto · user-selected symbol · chart timeframe
- strategy family: band-confluence volatility strategy
- claimed edge: open Pine source built for crypto volatility with a confluence of bands; TradingView strategy properties fix the parameters and its tester reports metrics (commission/slippage are user settings with a default)
- claimed return: UNKNOWN
- trades / period: UNKNOWN · UNKNOWN
- costs included: PARTIAL (TradingView tester settings, not read) · code: YES · forward: NO · live: NO
- limitations: listing-level read; TradingView paywalls the strategy tester for most users
- status: REFERENCED_BY_C-15

## S2-38 — chibui191/bitcoin_volatility_forecasting — 7-day realised-volatility forecast

- URL: https://github.com/chibui191/bitcoin_volatility_forecasting
- class / read / grade: PRIMARY_SOURCE · listing · E1 (AUTHOR_BACKTEST)
- publisher / date / version: chibui191 · UNKNOWN · UNKNOWN
- market / assets / timeframe: BTC-USD · BTC · daily, 7-day horizon
- strategy family: volatility forecasting (GARCH + LSTM)
- claimed edge: forecasts realised volatility rather than direction; useful as a risk overlay, not as an entry/exit rule
- claimed return: UNKNOWN
- trades / period: UNKNOWN · UNKNOWN
- costs included: UNKNOWN · code: YES · forward: NO · live: NO
- limitations: not a trading strategy
- status: REVIEWED_NOT_SHORTLISTED

## S2-39 — awesome-systematic-trading — curated list of strategies, libraries and papers

- URL: https://pypi.org/project/awesome-systematic-trading/
- class / read / grade: COMMENTARY · listing · E1 (AUTHOR_BACKTEST)
- publisher / date / version: paperswithbacktest · UNKNOWN · UNKNOWN
- market / assets / timeframe: UNKNOWN · UNKNOWN · UNKNOWN
- strategy family: not a strategy source
- claimed edge: a curated map of systematic strategies and replication repositories
- claimed return: UNKNOWN
- trades / period: UNKNOWN · UNKNOWN
- costs included: UNKNOWN · code: NO · forward: NO · live: NO
- limitations: index only; used to widen the search, never as evidence
- status: SEARCH_VENUE

## S2-40 — QuantConnect Live Trading documentation (how live/paper evidence is produced)

- URL: https://www.quantconnect.com/docs/v2/cloud-platform/live-trading
- class / read / grade: PRIMARY_SOURCE · listing · E1 (AUTHOR_BACKTEST)
- publisher / date / version: QuantConnect · UNKNOWN · UNKNOWN
- market / assets / timeframe: multi-asset · UNKNOWN · UNKNOWN
- strategy family: not a strategy source
- claimed edge: documents that deployed algorithms run in live/paper mode with public results pages for their authors
- claimed return: UNKNOWN
- trades / period: UNKNOWN · UNKNOWN
- costs included: UNKNOWN · code: NO · forward: NO · live: NO
- limitations: no public per-strategy track record was reachable this round without an account
- status: CONTEXT

## S2-41 — Quantiacs competition filters and FAQ (live paper gate)

- URL: https://quantiacs.com/documentation/en/user_guide/passFilters.html
- class / read / grade: PRIMARY_SOURCE · listing · E1 (AUTHOR_BACKTEST)
- publisher / date / version: Quantiacs · UNKNOWN · UNKNOWN
- market / assets / timeframe: futures and crypto contests · UNKNOWN · UNKNOWN
- strategy family: not a strategy source
- claimed edge: search summary of the filter rules: a strategy whose in-sample Sharpe exceeds 1 enters daily live paper trading; crypto contests run on a top-10 long-only universe
- claimed return: UNKNOWN
- trades / period: UNKNOWN · UNKNOWN
- costs included: UNKNOWN · code: NO · forward: NO · live: NO
- limitations: listing-level read of the filter documentation
- status: CONTEXT

## S2-42 — vectorbt — vectorised backtesting with research-backed examples

- URL: https://github.com/polakowo/vectorbt
- class / read / grade: PRIMARY_SOURCE · listing · E1 (AUTHOR_BACKTEST)
- publisher / date / version: Oleg Polakow · UNKNOWN · UNKNOWN
- market / assets / timeframe: multi-asset incl. crypto · user-selected · any
- strategy family: framework and example notebooks
- claimed edge: fast vectorised backtesting with published example notebooks; the examples illustrate methods rather than a tested external system
- claimed return: UNKNOWN
- trades / period: UNKNOWN · UNKNOWN
- costs included: UNKNOWN · code: YES · forward: NO · live: NO
- limitations: reviewed as a search venue: no canonical externally-tested strategy with a fixed period was found in it this round
- status: SEARCH_VENUE_NO_CANDIDATE

## S2-43 — backtrader — event-driven backtesting framework and strategy gallery

- URL: https://github.com/mementum/backtrader
- class / read / grade: PRIMARY_SOURCE · listing · E1 (AUTHOR_BACKTEST)
- publisher / date / version: Daniel Rodriguez · UNKNOWN · UNKNOWN
- market / assets / timeframe: multi-asset incl. crypto · user-selected · any
- strategy family: framework plus community strategies
- claimed edge: framework for implementing strategies; community strategies live in separate repositories without canonical results
- claimed return: UNKNOWN
- trades / period: UNKNOWN · UNKNOWN
- costs included: UNKNOWN · code: YES · forward: NO · live: NO
- limitations: reviewed as a search venue only
- status: SEARCH_VENUE_NO_CANDIDATE

## S2-44 — QuantConnect Strategies — the successor venue to Quant League

- URL: https://www.quantconnect.com/strategies/
- class / read / grade: PRIMARY_SOURCE · listing · E1 (AUTHOR_BACKTEST)
- publisher / date / version: QuantConnect · UNKNOWN · UNKNOWN
- market / assets / timeframe: multi-asset incl. crypto · author-selected · author-selected
- strategy family: community strategy catalogue
- claimed edge: the Quant League page read for C-03 states that Quant League evolves into 'Strategies', 'with improved organization and a better overall experience'
- claimed return: UNKNOWN
- trades / period: UNKNOWN · UNKNOWN
- costs included: UNKNOWN · code: NO · forward: NO · live: NO
- limitations: not read beyond the listing; no candidate was built on it this round
- status: SEARCH_VENUE_NO_CANDIDATE
