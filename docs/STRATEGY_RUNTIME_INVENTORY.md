# STRATEGY_RUNTIME_INVENTORY — actualizado (MULTI-STRATEGY-ENABLEMENT-V1)

> Fuente: código real + ejecución offline con las clases productivas.
> Sustituye al inventario anterior (solo enrutaba ema_crossover).

## Inventario por familia

| Family | Impl (productive) | Min bars | Indicators propios | ATR stop | Señales/5m | Estado |
| --- | --- | ---: | --- | ---: | ---: | --- |
| ema_crossover | families/ema_crossover_family.py | 22 | ema9/21, rsi14, atr14 | 1.5× | sí | REJECTED (baseline propio PF 0.57) |
| momentum | families/momentum_family.py | 36 | macd(12/26/9), momentum(10), atr | 2.0× | sí | REJECT (PF 0.65) |
| breakout | families/breakout_family.py | 21 | volume_relative(donchian20), atr | 1.5× | sí | REJECT (PF 0.66) |
| trend | families/trend_family.py | 56 | ema8/21/55(+prev), atr | 2.5× | sí | REJECT (PF 0.72) |
| mean_reversion | families/mean_reversion_family.py | 22 | bollinger(20,2), atr | 1.5× | sí | REJECT (PF 0.67) |
| volatility | families/volatility_family.py | 33 | bollinger(20,2), keltner, atr | box | sí | REJECT (PF 0.62) |

## Estados de wiring (runtime actual)

- **ema_crossover**: ACTIVE (única ejecutada en paper; mapa primero +
  regimes [] + correlation-group=1)
- **Las 5 restantes**: REACHABLE_NOT_SELECTABLE por triple causa
  (MULTI_STRATEGY_ROUTING_AUDIT.md) + **DEF-206 inanición de indicadores**:
  `_default_indicators` no provee sus claves → generate()=[] siempre.
- Señales demostradas en evaluación offline con su propio precompute —
  la lógica productiva funciona; el wiring del runner no las alimenta.

## Parity (§14)

- Motor offline usa las clases runtime + `_compute_indicators` propios +
  semántica del adapter (incl. quirk SHORT-stop→1%) y exits del PaperBroker.
- ema_crossover: dos motores independientes (backtest dedicado 1723 trades
  vs parity engine 1561) → mismo veredicto (PF 0.57 / 0.50). PARITY OK.
