# HYPOTHESIS REGISTRY

| HYPOTHESIS_ID | SOURCE | TYPE | ASSET | TIMEFRAME | MECHANISM | DATA | TESTABLE | EXPERIMENT | STATUS | RESULT |
|---|---|---|---|---|---|---|---|---|---|---|
| HYP-001 | SRC-BOOK-001 | STRATEGY | multi-asset | configurable | MA20/40 trend pullback | OHLCV | YES | EXP-001 | PROPOSED |  |
| HYP-002 | SRC-BOOK-001 | ROUTER_FILTER | multi-asset | multi-timeframe | higher-timeframe alignment reduces false entries | OHLCV multi-TF | YES | EXP-003 | PROPOSED |  |
| HYP-003 | SRC-BOOK-001 | STRATEGY | multi-asset | configurable | MACD zero-regime crossover + 3-bar persistence | OHLCV | YES | EXP-002 | PROPOSED |  |
| HYP-004 | SRC-BOOK-001 | STRATEGY | multi-asset | configurable | MACD divergence + structure break predicts reversal | OHLCV | YES | EXP-004 | PROPOSED |  |
| HYP-005 | SRC-BOOK-001 | STRATEGY | multi-asset | configurable | 3-6 candle pullback into MA20-40 resumes trend | OHLCV | YES | EXP-005 | PROPOSED |  |
| HYP-006 | SRC-BOOK-001 | STRATEGY | multi-asset | configurable | S/R pullback + Fibonacci filter improves trend entries | OHLCV | YES | EXP-006 | PROPOSED |  |
| HYP-007 | SRC-BOOK-001 | STRATEGY | multi-asset | configurable | range S/R + RSI/Stoch/CCI consensus mean-reverts | OHLCV | YES | EXP-007 | PROPOSED |  |
| HYP-008 | SRC-BOOK-001 | STRATEGY | multi-asset | configurable | H&S neckline breakout + volume has reversal edge | OHLCV | YES after deterministic pattern definition | EXP-008 | PROPOSED |  |
| HYP-009 | SRC-BOOK-001 | SENTIMENT_ALPHA | US index/options | daily or source-defined | put/call extremes have contrarian value | option put/call series + price | YES | EXP-009 | PROPOSED |  |
| HYP-010 | SRC-BOOK-001 | STRATEGY | pairs | configurable | divergent related assets reconverge | paired prices + costs | PARTIAL; source underspecified | EXP-011 | PROPOSED |  |
| HYP-011 | SRC-BOOK-001 | RISK | portfolio | all | source exposure caps address concentration but must be calibrated | portfolio/risk history | YES | EXP-012 | PROPOSED |  |
| HYP-012 | SRC-BOOK-001 | RISK | leveraged assets | all | deterministic leverage stress gates reduce ruin/margin-call risk | positions/margin/volatility | YES | EXP-013 | PROPOSED |  |
| HYP-013 | SRC-BOOK-001 | PORTFOLIO_RISK | hedged portfolios | all | explicit basis/cost-aware hedge model improves residual-risk control | positions/derivatives/basis/costs | YES | EXP-014 | PROPOSED |  |
| HYP-014 | SRC-BOOK-001 | PROCESS | all | all | process-conformance score predicts avoidable failure independent of PnL | DecisionTrace/Outcome | YES | EXP-015 | PROPOSED |  |
| HYP-015 | SRC-BOOK-001 | RESEARCH_PROCESS | all | all | external fixed thresholds are less portable than validated volatility/quantile-normalized alternatives | historical data + source rules | YES | EXP-016 | PROPOSED |  || HYP-016 | SRC-MANUAL-001 | RESEARCH_PROCESS | all | all | freezing labels at decision_time reduces hindsight contamination | DecisionTrace/pattern labels | YES | EXP-017 | PROPOSED |  |
| HYP-017 | SRC-MANUAL-001 | RESEARCH_PROCESS | all | all | separating observable pattern from causal narrative reduces unsupported mechanism adoption | claims/specs | YES | EXP-018 | PROPOSED |  |
| HYP-018 | SRC-MANUAL-001 | STRATEGY | FX | HTF + intraday | Order Block + OTE + sweep/session confluence has incremental pullback edge | PIT FX OHLCV | YES after rule freeze | EXP-019 | PROPOSED |  |
| HYP-019 | SRC-MANUAL-001 | STRATEGY | FX/DXY | M15 source preference | cross-pair/DXY divergence predicts subsequent relative-strength resolution | synchronized FX/DXY | PARTIAL | EXP-020 | PROPOSED |  |
| HYP-020 | SRC-MANUAL-001 | STRATEGY | FX | M15/intraday | abrupt counter-premise session sweep predicts reversal toward HTF premise | FX OHLCV + sessions | PARTIAL | EXP-021 | PROPOSED |  |
| HYP-021 | SRC-MANUAL-001 | STRATEGY | FX | intraday | Asian range sweep before London/NY move has conditional directional edge | FX OHLCV + sessions | PARTIAL | EXP-022 | PROPOSED |  |
| HYP-022 | SRC-MANUAL-001 | STRATEGY | multi-asset candidate | intraday | range excursions mean-revert toward 50% midpoint more than trend-regime controls | OHLCV | PARTIAL | EXP-023 | PROPOSED |  |
| HYP-023 | SRC-MANUAL-001 | STRATEGY | FX | multi-TF | objectively defined liquidity voids are revisited more than matched impulses | OHLCV | PARTIAL | EXP-024 | PROPOSED |  |
| HYP-024 | SRC-MANUAL-001 | ROUTER_FILTER | FX | intraday | high-impact event filter reduces failure of technical intraday setups | OHLCV + PIT event calendar | YES with data | EXP-025 | PROPOSED |  |
| HYP-025 | SRC-MANUAL-002 | STRATEGY | Mini S&P futures | 3m/open | S1 opening false-break fade has edge under source context | Mini S&P + Speed | BLOCKED | EXP-026 | PROPOSED |  |
| HYP-026 | SRC-MANUAL-002 | STRATEGY | Mini S&P futures | intraday | S2 directional pullback after breakout has edge | Mini S&P OHLCV | PARTIAL | EXP-027 | PROPOSED |  |
| HYP-027 | SRC-MANUAL-002 | STRATEGY | multi-asset | intraday | first-touch pivot fade has short-horizon mean-reversion edge | OHLCV prior-day HLC | PARTIAL | EXP-028 | PROPOSED |  |
| HYP-028 | SRC-MANUAL-002 | STRATEGY | multi-asset | intraday | confirmed pivot breakout predicts continuation toward next level | OHLCV prior-day HLC | PARTIAL | EXP-029 | PROPOSED |  |
| HYP-029 | SRC-MANUAL-002 | ROUTER_FILTER | Mini S&P futures | opening | NO_TRADE in deterministic Batidora/range regime improves trend strategy | OHLCV | PARTIAL | EXP-030 | PROPOSED |  |
| HYP-030 | SRC-MANUAL-002 | RISK/STRATEGY | multi-asset | all | volatility-normalized distances outperform fixed display-specific distances | OHLCV/volatility | YES | EXP-031 | PROPOSED |  |
| HYP-031 | SRC-MANUAL-002 | RISK | portfolio | daily | deterministic daily-loss breaker reduces tail loss at acceptable opportunity cost | portfolio PnL | YES | EXP-032 | PROPOSED |  |
| HYP-032 | SRC-MANUAL-002 | RISK | portfolio | multi-session | drawdown state machine with deleveraging/halt improves capital preservation | portfolio PnL | YES | EXP-033 | PROPOSED |  |
| HYP-033 | SRC-MANUAL-002 | EXECUTION | multi-asset | order lifecycle | atomic/compensating OCO protection reduces unprotected-position states | execution events | YES | EXP-034 | PROPOSED |  |
| HYP-034 | SRC-CHEATSHEET-001 | STRATEGY | unknown | 1m/2m | seven visual S/R patterns may encode repeatable microstructure entries | unknown | NO; underspecified | EXP-035 | NEEDS_SPEC |  |
