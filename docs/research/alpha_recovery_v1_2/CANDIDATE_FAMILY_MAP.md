# ARP-003 — CANDIDATE FAMILY MAP (§22) + RESEARCH PRIORITY (§23)

This is the Alpha Research backlog. Turnover is expressed as the natural holding
horizon of the mechanism; cost-sensitivity uses the frozen
`COST_FEASIBILITY.json` frontier (mean |move| ÷ 23.559 bps round trip).

**Cost-compatibility rule of thumb.** A real mechanism captures only a fraction
`f` of the typical move. It clears cost when `f × OPPORTUNITY_TO_COST_RATIO > 1`.
Reading the frontier at `f ≈ 0.25–0.35` (a generous capture for a clean rule):

| holding horizon | mean \|move\| (bps) | ratio | plausible with f≈0.30? |
| --- | --- | --- | --- |
| 30m | 25.44 | 1.08 | **no** (needs f ≈ 0.93) |
| 1h | 36.15 | 1.53 | **no** (needs f ≈ 0.65) |
| 2h | 51.37 | 2.18 | **no** (needs f ≈ 0.46) |
| 4h | 72.53 | 3.08 | **borderline** (needs f ≈ 0.32) |
| 8h | 104.03 | 4.42 | **yes** (needs f ≈ 0.23) |
| 1d | 193.13 | 8.20 | **yes** (needs f ≈ 0.12) |
| 7d | 525.75 | 22.32 | **yes** (needs f ≈ 0.045) |

So the **cost-compatible region begins at ≈ 4–8 h** and is comfortable at ≥ 1 day.
Every 5-minute mechanism the project has tested lives at ratio ≈ 1.0–1.5, i.e. deep
inside the cost-dominated region. This is the quantitative core of ARP-003.

## Family map

| candidate / hypothesis | source | family | mechanism | timeframe | turnover | cost sensitivity | PIT complexity | data requirements | status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 001 / 002 / 005 / 020 | SRC-BOOK-001 | trend / continuation | MA-stack pullback + break | 5m | very high | **extreme** (ratio 1.1) | medium | OHLCV | tested variant rejected; SF resolvable |
| 003 | SRC-BOOK-001 | momentum | MACD regime crossover | 5m | very high | extreme | low | OHLCV | semantic duplicate of runtime `momentum` |
| 004 / 008 | SRC-BOOK-001 | pattern / reversal | divergence, H&S | 5m | high | extreme | **high** | OHLCV + pivot geometry | NEEDS_SPEC |
| 006 / 021 | SRC-BOOK-001 / CHEATSHEET | level / price-action | S/R, Fibonacci, micro entries | 5m/1m | very high | extreme | high | OHLCV + S/R | NEEDS_SPEC |
| 007 / 015 | SRC-BOOK-001 | mean reversion | range RSI/Stoch/CCI, fair-value | 5m | very high | extreme | medium | OHLCV + RSI/Stoch/CCI | NEEDS_SPEC |
| 009 | SRC-BOOK-001 | sentiment | put/call contrarian | daily | low | n/a | high | options PIT series | **DATA_BLOCKED** |
| 010 | SRC-BOOK-001 | relative value | pair spread mean reversion | 5m | high | extreme | high | two-leg execution | **INFRASTRUCTURE_BLOCKED** |
| 011 | SRC-MANUAL-001 | continuation | order-block OTE (FX) | intraday | high | extreme | high | PIT FX + sweeps | NEEDS_SPEC + asset mismatch |
| 012 | SRC-MANUAL-001 | cross-instrument | SMT divergence | M15 | high | extreme | high | synchronized FX/DXY | **SF BLOCKED_NEEDS_SPEC** |
| 013 / 014 | SRC-MANUAL-001 | liquidity reversal | Judas / Asian-range sweep | intraday | high | extreme | high | PIT FX + sessions | NEEDS_SPEC |
| 016 | SRC-MANUAL-001 | liquidity reversal | liquidity-void retest | multi-TF | high | extreme | medium | OHLCV | **SF BLOCKED_NEEDS_SPEC** |
| 017 / 018 | SRC-MANUAL-002 | index intraday | mini-SPX S1/S2 | 3m/open | very high | extreme | high | index + Speed | **DATA_BLOCKED** |
| 019 | SRC-MANUAL-002 | level reaction | pivot fade | intraday | high | extreme | low–medium | prior-day HLC | **SF BLOCKED_NEEDS_SPEC** |
| D-02 | discovery | mean reversion | vol-z short-term reversal | 15m | very high | extreme | low | OHLCV | REJECTED (unmerged) |
| D-03 | discovery | breakout | squeeze breakout | 30m | very high | extreme | low | OHLCV | INTESTABLE (unmerged) |
| D-04 | discovery | momentum | relative momentum | 1h | high | high | low | OHLCV | REJECTED (unmerged) |

## Selected lower-turnover experiments (§13)

| id | mechanism | family | horizon | why cost-compatible |
| --- | --- | --- | --- | --- |
| `EXP-ARP-006` | liquidity-void retest, daily | reversal | 1d | frontier ratio 8.2; needs f ≈ 0.12 |
| `EXP-ARP-007` | pivot fade, daily | level reaction | 1d–2d | ratio 8.2; deterministic pivot formula exists |
| `EXP-ARP-008` | daily time-series trend | continuation | 2d–5d | ratio 12–16 |
| `EXP-ARP-009` | cross-sectional relative strength | cross-instrument | 1d rebalance | ratio 8.2; only cross-instrument mechanism |
| `EXP-ARP-010` | volatility-spike mean reversion | mean reversion | 4h–8h | ratio 3.1–4.4; grounded in the ledger's largest gross |

All five are labeled `PROJECT_DERIVED_VARIANT` or `NEW_HYPOTHESIS`; **none** is
source-faithful.

## Research priority (§23) — separated, not one opaque number

Each axis is classified independently. No numeric composite is produced.

| candidate / hypothesis | SOURCE_QUALITY | SPEC_COMPLETENESS | ECONOMIC_FEASIBILITY | DATA_READINESS | PIT_RISK | COST_SENSITIVITY | ORTHOGONALITY | IMPLEMENTATION_COMPLEXITY | EXPERIMENT_READINESS |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 001–005, 020 | MEDIUM | HIGH (001) / LOW (others) | LOW | READY | LOW | EXTREME | LOW (one mechanism) | LOW | PARTIAL |
| 006–008, 021 | LOW | LOW | LOW | PARTIAL | HIGH | EXTREME | MEDIUM | HIGH | NOT_READY |
| 009, 017, 018 | LOW | MEDIUM | UNKNOWN | **BLOCKED** | n/a | n/a | MEDIUM | HIGH | BLOCKED |
| 010 | LOW | LOW | UNKNOWN | PARTIAL | HIGH | EXTREME | HIGH | HIGH | BLOCKED |
| 011, 013, 014 | LOW | LOW | LOW | PARTIAL (asset mismatch) | HIGH | EXTREME | MEDIUM | HIGH | NOT_READY |
| 012 | LOW | **BLOCKED** | LOW | PARTIAL | HIGH | EXTREME | HIGH | HIGH | BLOCKED |
| 016 | LOW | **BLOCKED** | LOW (intraday) / MEDIUM (daily variant) | READY | MEDIUM | EXTREME→HIGH | MEDIUM | MEDIUM | READY as variant |
| 019 | MEDIUM | **BLOCKED** | LOW (intraday) / MEDIUM (daily variant) | READY | LOW | EXTREME→HIGH | MEDIUM | MEDIUM | READY as variant |
| `EXP-ARP-008` | PROJECT | HIGH | MEDIUM | READY | LOW | HIGH | MEDIUM | LOW | READY |
| `EXP-ARP-009` | PROJECT | MEDIUM | MEDIUM | READY | MEDIUM | HIGH | **HIGH** | MEDIUM | PARTIAL (infra) |
| `EXP-ARP-010` | PROJECT | MEDIUM | MEDIUM | READY | MEDIUM | HIGH | MEDIUM | MEDIUM | READY |
| D-02/03/04 | LOW | MEDIUM | LOW | READY | LOW | EXTREME | MEDIUM | LOW | REJECTED |

Legend: SOURCE_QUALITY ∈ {LOW, MEDIUM, HIGH} from the source review reliability
classes; the rest are the axis labels the mission names.
