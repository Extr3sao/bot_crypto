# RFC-035S2 — independent verification

- status: **PASS**
- checks: 863/863
- mismatches: 0
- false success: 0
- candidates checked: 18
- REPLICATE_P0 selected: NONE
- REPLICATE_P1: C-02, C-07

Re-derived from the stored artifacts and the canonical registry; the round-1 sources and opportunity records were compared against `git HEAD` to prove history was not rewritten.

## Mismatches

- none

## Limitations

- the RFC-035 artifacts are not tracked in git at this commit, so history preservation is verified structurally (records intact, ranks and corrections kept, hashes re-derivable) instead of by comparison with an earlier revision
- sources not reachable from this host (bot-blocked, paywalled or transient), reported rather than treated as evidence of absence: ['S2-15', 'S2-20', 'S2-35', 'S2-36']
- source liveness 40/44; unreachable URLs are listed in the audit block, not silently marked verified

## Notes

- reachability is a liveness probe, not a content check: a 200 does not confirm the claim
- the final report's verification block was pending, so its self-consistency check is only evaluated from the next verification run onwards

## Source liveness

| source | status | reachable | promoted candidate | url |
| --- | --- | --- | --- | --- |
| S2-01 | 200 | True | True | https://github.com/freqtrade/freqtrade-strategies |
| S2-02 | 200 | True | False | https://www.freqtrade.io/en/stable/strategy-customization/ |
| S2-03 | 200 | True | True | https://raw.githubusercontent.com/freqtrade/freqtrade-strategies/main/user_data/strategies/Strategy001.py |
| S2-04 | 200 | True | False | https://github.com/iterativv/NostalgiaForInfinity |
| S2-05 | 200 | True | False | https://www.quantconnect.com/league/ |
| S2-06 | 200 | True | False | https://www.quantconnect.com/league/18106/2024-q4/crypto-and-stock-momentum/ |
| S2-07 | 200 | True | True | https://quantiacs.com/documentation/en/quick_start/quick_start.html |
| S2-08 | 200 | True | True | https://quantiacs.com/documentation/en/examples/q24_crypto_guide.html |
| S2-09 | 200 | True | True | https://github.com/quantiacs/toolbox |
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
| S2-41 | 200 | True | True | https://quantiacs.com/documentation/en/user_guide/passFilters.html |
| S2-42 | 200 | True | False | https://github.com/polakowo/vectorbt |
| S2-43 | 200 | True | False | https://github.com/mementum/backtrader |
| S2-44 | 200 | True | False | https://www.quantconnect.com/strategies/ |
