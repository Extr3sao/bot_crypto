# H6 PREREG CONSISTENCY AUDIT V2 — H6-PREREG-REPAIR-01 + OI-DATASET-REFREEZE-02

**Result: `PASS` — `UNRESOLVED_FIELDS = []` (60/60 resolved, commit_allowed=True)**

spec: `docs/external-audit-01/oi-full-history-02/H6_SPEC_V2.json` sha=221cfa1d6eb3dae3...
manifest: `docs/external-audit-01/oi-full-history-02/H6_MANIFEST_V2.json` sha=5f9aba446686a32b...

## Dimensions

| Dimension | Canonical | Value | Resolved |
| --- | --- | --- | --- |
| hypothesis_id | `H6-OI-CONFIRMED-CONTINUATION-02` | `H6-OI-CONFIRMED-CONTINUATION-02` | True |
| manifest hypothesis matches spec | `H6-OI-CONFIRMED-CONTINUATION-02` | `H6-OI-CONFIRMED-CONTINUATION-02` | True |
| spec_version | `2` | `2` | True |
| manifest spec_version | `2` | `2` | True |
| mechanism.name | `OI_CONFIRMED_CONTINUATION` | `OI_CONFIRMED_CONTINUATION` | True |
| mechanism family | `position_stock_conditioning` | `position_stock_conditioning` | True |
| assets | `['BTCUSDT', 'ETHUSDT', 'SOLUSDT']` | `['BTCUSDT', 'ETHUSDT', 'SOLUSDT']` | True |
| manifest assets match spec | `['BTCUSDT', 'ETHUSDT', 'SOLUSDT']` | `['BTCUSDT', 'ETHUSDT', 'SOLUSDT']` | True |
| window start | `2021-12-01T00:00:00Z` | `2021-12-01T00:00:00Z` | True |
| manifest window start | `2021-12-01T00:00:00Z` | `2021-12-01T00:00:00Z` | True |
| window end | `2026-09-10T23:59:59Z` | `2026-09-10T23:59:59Z` | True |
| decision_timeframe.bucket | `1h` | `1h` | True |
| manifest decision_timeframe | `1h` | `1h` | True |
| primary_holding_horizon | `1` | `1` | True |
| entry_timing | `next 1h bar OPEN (the bar immediately after the decision hour)` | `next 1h bar OPEN (the bar immediately after the decision hour)` | True |
| manifest entry | `True` | `True` | True |
| exit_timing | `same next 1h bar CLOSE` | `same next 1h bar CLOSE` | True |
| stop | `NONE in the primary H6 discovery test (no ATR stop, no signal-flip exit; trade m` | `NONE in the primary H6 discovery test (no ATR stop, no signal-flip exit; trade m` | True |
| manifest stop | `NONE` | `NONE` | True |
| cooldown | `NONE required: fixed 1h non-overlapping per-asset outcome definition (entry at n` | `NONE required: fixed 1h non-overlapping per-asset outcome definition (entry at n` | True |
| manifest cooldown | `NONE` | `NONE` | True |
| decision_spacing | `NO COOLDOWN / ONE DECISION PER COMPLETED ASSET-HOUR` | `NO COOLDOWN / ONE DECISION PER COMPLETED ASSET-HOUR` | True |
| cost canonical | `10` | `10` | True |
| manifest cost | `10` | `10` | True |
| cost definition single | `10 bps is the TOTAL modeled round-trip trading friction (single canonical number` | `10 bps is the TOTAL modeled round-trip trading friction (single canonical number` | True |
| cost sensitivity | `[0, 10, 20, 40]` | `[0, 10, 20, 40]` | True |
| funding policy | `EXCLUDED_WITH_LIMITATION` | `EXCLUDED_WITH_LIMITATION` | True |
| funding gate | `True` | `True` | True |
| orthogonality threshold | `0.5` | `0.5` | True |
| manifest orthogonality | `0.5` | `0.5` | True |
| z window | `720` | `720` | True |
| z min obs | `336` | `336` | True |
| z center | `median` | `median` | True |
| z scale | `1.4826*MAD` | `1.4826*MAD` | True |
| expansion requires delta>0 AND z>=1 | `delta_oi > 0 AND z_oi >= +1.0` | `delta_oi > 0 AND z_oi >= +1.0` | True |
| manifest threshold_rule contains delta_oi | `True` | `True` | True |
| LONG direction | `price UP (close > open) AND delta_oi > 0 AND z_oi >= +1.0` | `price UP (close > open) AND delta_oi > 0 AND z_oi >= +1.0` | True |
| SHORT direction | `price DOWN (close < open) AND delta_oi > 0 AND z_oi >= +1.0` | `price DOWN (close < open) AND delta_oi > 0 AND z_oi >= +1.0` | True |
| NO_TRADE | `delta_oi <= 0, or z_oi < +1.0, or price close == open, or any NO_SIGNAL conditio` | `delta_oi <= 0, or z_oi < +1.0, or price close == open, or any NO_SIGNAL conditio` | True |
| H6_EXECUTIONS | `0` | `0` | True |
| manifest H6_EXECUTIONS | `0` | `0` | True |
| H6_BACKTESTS | `0` | `0` | True |
| PERFORMANCE_OBSERVED | `False` | `False` | True |
| oi dataset path V2 | `data/processed/oi_full_history_v2/` | `data/processed/oi_full_history_v2/` | True |
| price authority template V2 | `data/processed/price_1h_v2/{ASSET}_1h.jsonl` | `data/processed/price_1h_v2/{ASSET}_1h.jsonl` | True |
| price covers window | `True` | `True` | True |
| whitelist fields subset of spec oi whitelist | `['sum_open_interest', 'sum_open_interest_value']` | `['sum_open_interest', 'sum_open_interest_value']` | True |
| spec sha in manifest matches current spec bytes | `221cfa1d6eb3dae30948e9605f258075c0cd69e8f38187da4959c3e696b8b000` | `221cfa1d6eb3dae30948e9605f258075c0cd69e8f38187da4959c3e696b8b000` | True |
| rationale cost 10 bps | `True` | `True` | True |
| rationale orthogonality 0.50 | `True` | `True` | True |
| rationale normalization median/MAD | `True` | `True` | True |
| rationale cooldown NONE | `True` | `True` | True |
| rationale V2 ledger | `True` | `True` | True |
| rationale raw-sign rule | `True` | `True` | True |
| failed review cooldown NONE | `True` | `True` | True |
| failed review archive forensic | `True` | `True` | True |
| failed review normalization | `True` | `True` | True |
| failed review funding | `True` | `True` | True |
| failed review cost 10 | `True` | `True` | True |
| H5_RESULT_SHA256 | `2427310dbed8445b1e39b1feaba7a8289918ab79a258f66b065da7cf2b7fe60f` | `2427310dbed8445b1e39b1feaba7a8289918ab79a258f66b065da7cf2b7fe60f` | True |
