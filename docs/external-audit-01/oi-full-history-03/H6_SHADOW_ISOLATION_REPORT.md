# H6 / Shadow Isolation Report

**Verdict:** `PASS — H6_SHADOW_ISOLATION = PASS`

- H6 V3 dataset authority: `OI_FULL_HISTORY_V2` (`16779b7d...`) + `PRICE_1H_AUTHORITY_V2` (`e1c2462a...`) only.
- H6 spec/mechanism (`OI_CONFIRMED_CONTINUATION`, `delta_oi > 0 AND z >= 1.0`, 1h holding) — no Shadow candidate/decision/outcome import.
- Static scan `test_h6_shadow_isolation.py` proves `feature_engine.py` contains no `Shadow` or `confirmation` consumption.
- Retroactive Shadow outcome change therefore cannot alter H6 specification or backtest labeling.
