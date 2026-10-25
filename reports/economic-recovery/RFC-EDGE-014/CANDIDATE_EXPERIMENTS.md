# WP-EDGE-14D — candidate experiments

*Round trip charged per trade: `22.9866` bps. OOS class `TEMPORAL_WITHIN_A_CONSUMED_CORPUS`, fresh: False.*

**Verdict `INSUFFICIENT_SAMPLE_FOR_FRESH_OOS`.**

| arm | trades | days | zero days | mean gross (bps) | mean net (bps) |
| --- | --- | --- | --- | --- | --- |
| E14-04_LEAD_LAG::UNI->AAVEUSDT | 534 | 2113 | 1690 | -0.787586 | -23.774186 |
| E14-04_LEAD_LAG::UNI->CRVUSDT | 739 | 2113 | 1553 | -2.818763 | -25.805363 |
| E14-04_LEAD_LAG::UNI->KSMUSDT | 508 | 2113 | 1713 | -5.444085 | -28.430685 |
| E14-04_LEAD_LAG::UNI->SUSHIUSDT | 508 | 2113 | 1705 | 2.860899 | -20.125701 |
| NEUTRAL_MA_CROSS_1H::BTCUSDT | 98 | 228 | 142 | 21.975396 | -1.011204 |
| NEUTRAL_MA_CROSS_1H::ETHUSDT | 107 | 228 | 134 | 16.494155 | -6.492445 |

Arms net-positive: **0**.

- the split is temporal inside a corpus another work package already measured on, so no arm here can be promoted or inferred from
- the lead-lag signal asset is UNIUSDT because BTC is not in the EDGE-08 universe; the relationship is declared, not assumed
- fees are the admission schedule; a cheaper venue would change the sign only if the gross move were already near the barrier, which it is not
