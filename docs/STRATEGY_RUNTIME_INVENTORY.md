# STRATEGY_RUNTIME_INVENTORY — verified from source + RUN-01 (not from old docs)

Runtime composition: `start_paper_trading.build_cycle_engine` wires exactly
6 families in a deterministic map (`status=CONFIRMED`, `regimes=[]` = eligible
in ANY regime, `direction=BOTH`, `priority=0`). The router picks the best by
score — with all-equal entries the FIRST in dict order wins: `ema_crossover`.

| strategy_id | family | Implementation | Reachable | Bars needed | Regimes | evaluation_mode | Directions | RUN-01 evidence | Classification |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| ema_crossover | ema_crossover | `families/ema_crossover_family.py` (EMA9/21 + RSI50 + ATR stop) | YES (map position 1) | ≥22 | ANY (empty list) | IMPLICIT_BAR_CLOSE (deterministic fn of closed bars) | LONG/SHORT | **7/7 orders; 4/4 closed trades; DOMINANT** | RUNTIME_ACTIVE (sole selector) |
| momentum | momentum | `families/momentum_family.py` (MACD hist ± momentum 0.5%/10 bars) | reachable-in-map, **never selected** (map order) | MIN_CANDLES | ANY | IMPLICIT_BAR_CLOSE | LONG/SHORT | 0 proposals reaching alpha stage | RUNTIME_REACHABLE_NOT_SELECTED |
| breakout | breakout | `families/breakout_family.py` | same | — | ANY | IMPLICIT_BAR_CLOSE | BOTH | never selected | RUNTIME_REACHABLE_NOT_SELECTED |
| trend | trend | `families/trend_family.py` | same | — | ANY | IMPLICIT_BAR_CLOSE | BOTH | never selected | RUNTIME_REACHABLE_NOT_SELECTED |
| mean_reversion | mean_reversion | `families/mean_reversion_family.py` | same | — | ANY | IMPLICIT_BAR_CLOSE | BOTH | never selected | RUNTIME_REACHABLE_NOT_SELECTED |
| volatility | volatility | `families/volatility_family.py` | same | — | ANY | IMPLICIT_BAR_CLOSE | BOTH | never selected | RUNTIME_REACHABLE_NOT_SELECTED |
| StrategySelector (legacy) | — | `paper/strategy_selector.py` | NO (superseded by router ADR) | — | — | — | — | absent from cycle | LEGACY |
| Other config strategies (`config/strategies.yaml`, 5 entries) | — | YAML catalog | NOT in the paper map (entrypoint composes its own deterministic map) | — | — | — | — | not consumed by paper cycle | CONFIGURED_NOT_PAPER_RUNTIME |

## Router health answers (evidence)

- **Selects more than one strategy?** NO — single best per (asset, cycle);
  with the equal-priority map it is always `ema_crossover` (first, score 1.0
  ties broken by insertion order — router code `score > best_score`).
- **Runtime-reachable strategies that can never be selected?** YES — the
  other 5 families: reachable in the map but structurally unpickable while
  `ema_crossover` holds position 1 with equal score. `CONFIGURED != SELECTABLE`.
- **Impossible conditions?** None found (gates: freshness, data-quality,
  enabled, confirmed, regime-list membership — all satisfiable; regime gate
  passes because entries declare `regimes=[]`).
- **Does regime change routing?** NO with the current map (empty regime lists
  ⇒ regime gate never excludes; regime only appears in trace). The regime
  VALUE is recorded in the context trace but has zero selection effect today.
- **Does asset change routing?** NO (same map for every asset).
- **Does timeframe change routing?** NO (no timeframe field in map entries).
- **Does StrategyPerformance participate?** NO — router consults only the
  static map + context quality/freshness.
- **StrategyPerformanceGate / performance evidence?** Not consulted in the
  paper path (research-side only).

## NO_TRADE taxonomy mapping (observed stages → taxonomy)

| Runtime stage:reason | Taxonomy bucket |
| --- | --- |
| router:empty_strategy_map / no_strategy_passed_gates / stale_context / low_data_quality | STRATEGY_NOT_APPLICABLE / REGIME_FILTER / DATA_INVALID |
| strategy:no_alpha_in_direction | NO_SIGNAL |
| strategy:family_not_found / exception | DATA_INVALID (defect if persistent) |
| idempotency:duplicate_intent | DUPLICATE_SIGNAL |
| risk:Max open positions | POSITION_LIMIT |
| risk:Consecutive loss cooldown | COOLDOWN |
| risk:Daily trade limit | DAILY_LIMIT |
| risk:Daily loss / drawdown / kill switch | RISK_VETO |
| broker:broker_returned_no_fill (same-side) | DUPLICATE_SIGNAL (position already held) |
| adapter/candidate/context errors | DATA_INVALID (fail-closed; NOT a NO_TRADE decision) |
