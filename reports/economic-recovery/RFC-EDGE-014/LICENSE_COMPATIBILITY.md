# WP-EDGE-14C — licence compatibility

no GPL/AGPL code is copied into this project by default; a clone that is studied stays outside the checkout and never becomes a runtime component

| id | repo | declared | classification | may copy | copy rule |
| --- | --- | --- | --- | --- | --- |
| SRC-01 | freqtrade/freqtrade | GPL-3.0 | ADOPT_P0 | False | NO_COPY |
| SRC-02 | jesse-ai/jesse | MIT | ADOPT_P0 | True | COPY_WITH_ATTRIBUTION |
| SRC-03 | vnpy/vnpy_ctastrategy | MIT | ADOPT_P0 | True | COPY_WITH_ATTRIBUTION |
| SRC-04 | hummingbot/hummingbot | Apache-2.0 | ADOPT_P1_EXPERIMENT | True | COPY_WITH_NOTICE |
| SRC-05 | nautechsystems/nautilus_trader | LGPL-3.0 | EXPERIMENT | False | LINK_ONLY_NO_VENDOR |
| SRC-06 | ccxt/ccxt | MIT | REUSE_CURRENT | True | COPY_WITH_ATTRIBUTION |
| SRC-09 | bmoscon/cryptofeed | AGC-3.0? (README says AGPL; validate the LICENSE file) | EXPERIMENT_CONDITIONAL | False | NO_COPY_UNTIL_LICENCE_READ |
| SRC-12 | TauricResearch/TradingAgents | Apache-2.0 | DEFER | True | COPY_WITH_NOTICE |

Not copyable: `SRC-01, SRC-05, SRC-09`.
