# RFC-035 — independent verification

- status: **FAIL**
- checks: 553/554
- mismatches: 1
- false success: 0
- selected opportunity: OPP-0001
- sources audited: 64

## Mismatches

- the baseline was taken on the current commit: 7e21f7ca6dbf vs fc78ce32bea4

## Limitations

- selected-candidate sources not reachable from this host (paywall or bot-block, not evidence of absence): ['S-02', 'S-04']
- source audit reachability 53/64; unreachable URLs are reported in source_audit, not silently treated as verified

## Notes

- source reachability is a liveness probe, not a content check: a 200 does not confirm the claim

## Source audit

| source | status | reachable | evidence source | url |
| --- | --- | --- | --- | --- |
| S-01 | 200 | True | True | https://www.falconx.io/newsroom/what-can-spot-etf-flows-tell-us-about-the-trajectory-of-bitcoin-prices-a-preliminary-statistical-investigation |
| S-02 | 403 | False | True | https://onlinelibrary.wiley.com/doi/10.1111/fire.70026 |
| S-03 | 200 | True | True | https://link.springer.com/article/10.1007/s10614-025-10998-x |
| S-04 | 403 | False | True | https://www.sciencedirect.com/science/article/pii/S106297692500047X |
| S-05 | 200 | True | False | https://arxiv.org/html/2607.09426v2 |
| S-06 | 200 | True | False | https://pmc.ncbi.nlm.nih.gov/articles/PMC10015199/ |
| S-07 | 200 | True | False | https://arxiv.org/pdf/2411.06327 |
| S-08 | None | False | False | https://www.efmaefm.org/0EFMAMEETINGS/EFMA%20ANNUAL%20MEETINGS/2025-Greece/papers/OrderFlowpaper.pdf |
| S-09 | 200 | True | False | https://keyrock.com/from-locked-to-liquidity-what-16000-token-unlocks-teach-us/ |
| S-10 | 200 | True | False | https://tokenomist.ai/research/do-token-unlocks-crash-prices |
| S-11 | 403 | False | False | https://papers.ssrn.com/sol3/papers.cfm?abstract_id=6632838 |
| S-12 | 403 | False | False | https://papers.ssrn.com/sol3/papers.cfm?abstract_id=6579278 |
| S-13 | 200 | True | False | https://www.tradingview.com/news/newsbtc:a8377b886094b:0-crypto-liquidation-data-rigged-by-exchanges-researcher-unveils-the-truth/ |
| S-14 | 200 | True | False | https://arxiv.org/html/2212.06888v7 |
| S-15 | 200 | True | False | https://gerbil.life/papers/CarryTrade.v1.2.pdf |
| S-16 | 403 | False | False | https://www.mdpi.com/2674-1032/5/3/68 |
| S-17 | 200 | True | False | https://www.federalreserve.gov/econres/notes/feds-notes/primary-and-secondary-markets-for-stablecoins-20240223.html |
| S-18 | 200 | True | False | https://quantpedia.com/are-there-seasonal-intraday-or-overnight-anomalies-in-bitcoin/ |
| S-19 | 403 | False | False | https://papers.ssrn.com/sol3/papers.cfm?abstract_id=5292305 |
| S-20 | 200 | True | False | https://www.cfbenchmarks.com/data/indices/KFRI |
| S2-01 | 200 | True | False | https://github.com/freqtrade/freqtrade-strategies |
| S2-02 | 200 | True | False | https://www.freqtrade.io/en/stable/strategy-customization/ |
| S2-03 | 200 | True | False | https://raw.githubusercontent.com/freqtrade/freqtrade-strategies/main/user_data/strategies/Strategy001.py |
| S2-04 | 200 | True | False | https://github.com/iterativv/NostalgiaForInfinity |
| S2-05 | 200 | True | False | https://www.quantconnect.com/league/ |
| S2-06 | 200 | True | False | https://www.quantconnect.com/league/18106/2024-q4/crypto-and-stock-momentum/ |
| S2-07 | 200 | True | False | https://quantiacs.com/documentation/en/quick_start/quick_start.html |
| S2-08 | 200 | True | False | https://quantiacs.com/documentation/en/examples/q24_crypto_guide.html |
| S2-09 | 200 | True | False | https://github.com/quantiacs/toolbox |
| S2-10 | 200 | True | False | https://quantpedia.com/revisiting-trend-following-and-mean-reversion-strategies-in-bitcoin/ |
| S2-11 | 200 | True | False | https://quantpedia.com/trend-following-and-mean-reversion-in-bitcoin/ |
| S2-12 | 200 | True | False | https://www.quantifiedstrategies.com/trend-following-and-momentum-strategies-on-bitcoin/ |
| S2-13 | 200 | True | False | https://www.systematicmoney.org/systematic-trading-resources |
| S2-14 | 200 | True | False | https://github.com/pst-group/pysystemtrade |
| S2-15 | 429 | False | False | https://github.com/topics/freqtrade-strategies |
| S2-16 | 200 | True | False | https://arxiv.org/html/2110.14936v1 |
| S2-17 | 200 | True | False | https://arxiv.org/html/2510.07943v1 |
| S2-18 | 200 | True | False | https://arxiv.org/html/2510.08068v2 |
| S2-19 | 200 | True | False | https://arxiv.org/pdf/2407.09546 |
| S2-20 | 403 | False | False | https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4322637 |
| S2-21 | 200 | True | False | https://ideas.repec.org/a/eee/riibaf/v52y2020ics0275531919308062.html |
| S2-22 | 200 | True | False | https://www.robots.ox.ac.uk/~sjrob/Theses/bryanLim.pdf |
| S2-23 | 200 | True | False | https://pmc.ncbi.nlm.nih.gov/articles/PMC12404547/ |
| S2-24 | 200 | True | False | https://github.com/jesse-ai/jesse |
| S2-25 | 200 | True | False | https://hummingbot.org/ |
| S2-26 | 200 | True | False | https://www.octobot.cloud/ |
| S2-27 | 200 | True | False | https://karaptic.com/research/ |
| S2-28 | 200 | True | False | https://www.kaggle.com/c/g-research-crypto-forecasting/discussion/327751 |
| S2-29 | 200 | True | False | https://www.gresearch.com/news/wrapping-up-the-g-research-crypto-forecasting-competition/ |
| S2-30 | 200 | True | False | https://kaggle.curtischong.me/competitions/G-Research-Crypto-Forecasting |
| S2-31 | 200 | True | False | https://github.com/SanchitAjmera/G-Research-Crypto-Forecasting |
| S2-32 | 200 | True | False | https://github.com/qAp/gresearch_crypto_forecasting_kaggle |
| S2-33 | 200 | True | False | https://github.com/coderback/drw-crypto-market-prediction |
| S2-34 | 200 | True | False | https://github.com/anthonymakarewicz/bitcoin-momentum-trading |
| S2-35 | 403 | False | False | https://www.researchgate.net/publication/395401021_Adaptive_Regime-Based_Trading_on_Bitcoin_Backtesting_and_Walk-Forward_Evaluation |
| S2-36 | 403 | False | False | https://www.researchgate.net/publication/406476873_Momentum_Trading_in_Cryptocurrencies_A_Comparative_Study_of_Time-Series_and_Cross-Sectional_Strategies |
| S2-37 | 200 | True | False | https://www.tradingview.com/script/bq0ELG1b-Multi-Band-Comparison-Strategy-CRYPTO/ |
| S2-38 | 200 | True | False | https://github.com/chibui191/bitcoin_volatility_forecasting |
| S2-39 | 200 | True | False | https://pypi.org/project/awesome-systematic-trading/ |
| S2-40 | 200 | True | False | https://www.quantconnect.com/docs/v2/cloud-platform/live-trading |
| S2-41 | 200 | True | False | https://quantiacs.com/documentation/en/user_guide/passFilters.html |
| S2-42 | 200 | True | False | https://github.com/polakowo/vectorbt |
| S2-43 | 200 | True | False | https://github.com/mementum/backtrader |
| S2-44 | 200 | True | False | https://www.quantconnect.com/strategies/ |
