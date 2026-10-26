# MULTI_STRATEGY_ROUTING_AUDIT — por qué 5/6 familias no son seleccionables

> Auditado desde código real + runtime evidence (no documentación histórica).
> Clasificación: CONFIGURATION + DESIGN (con un defecto de wiring: DEF-206).

## Cadena de decisión real (runtime, CP-PO-002)

```
AssetContext → StrategyRouter.route() → RouterDecision (UNA strategy)
→ family.generate(bars, indicator_fn(bars)) → AlphaSignal*
→ alpha_signal_to_signal → RiskManager → PaperBroker
```

## Causa 1 — Router single-select (DESIGN)

`StrategyRouter.route()` (research/strategy_router.py:162-190) itera el map,
aplica gates y elige **UN único best** por score. Nunca retorna N elegibles.
Con `regimes: []` (match universal) y score inicial 1.0, el primero del map
con prioridad ≥ empate gana SIEMPRE.

## Causa 2 — Map-order (CONFIGURATION)

El strategy_map del entrypoint declara ema_crossover primero con
`regimes: []` y las demás con `regimes: [...]`. En cualquier régimen, la
primera entrada puntúa ≥1.0+1.0 (universal) y las siguientes requieren match
explícito — no pueden superar el score del universal salvo prioridad > 1.0.
Resultado: selecciones 100% ema_crossover (evidencia: 1026/1026
selecciones en RUN-01; 0 efectos de régimen/asset/timeframe).

## Causa 3 — Correlation-group = 1 (CONFIGURATION)

Aunque varias familias generasen señal en el mismo ciclo,
`build_portfolio(max_per_correlation_group=1)` (paper/candidate_portfolio.py:84)
colapsa a **1 candidato por asset** — el de mayor score (empate ⇒ orden de
mapa). El plano multi-strategy no llega vivo a risk/broker.

## DEF-206 — Inanición de indicadores (wiring defect, paper runner)

`_default_indicators()` (start_paper_trading.py:167-179) solo computa
ema_fast/ema_slow/rsi/atr. Las familias momentum/breakout/trend/
mean_reversion/volatility exigen sus propias claves (macd{histogram},
volume_relative, ema_mid/ema_slow_prev, bollinger, ...). Con un dict
NO vacío que carece de ellas, `generate()` retorna [] SIEMPRE (el fallback
`if not indicators` no se dispara). **Incluso si el router las eligiera,
no producirían señal.** Doble muerte: map-order + inanición.

## Nota de parity (positiva)

Las claves SÍ son consistentes dentro de cada familia (su propio
`_compute_indicators` provee exactamente lo que `generate()` lee). El
defecto es solo del precompute compartido del entrypoint.

## Implicaciones para el enablement (no implementado aún)

1. FIX DEF-206: ampliar `_default_indicators` (o per-family precompute)
2. Router: soportar N elegibles (selected/rejected/not_applicable con razón)
3. Portfolio: política determinista para N señales por asset
   (agreement/conflict → NO_TRADE_CONFLICT si no hay política validada)
4. Estados de admission en el map: REJECTED/UNVALIDATED no pueden routear
   a ejecución (§10)
