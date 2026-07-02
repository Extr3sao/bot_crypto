# Paper Trading Methodology

> Cómo se hace paper trading, qué métricas se exigen y cómo se compara
> contra backtests antes de promover una estrategia.

---

## 1. Principios

1. **Paper NO es backtest.** El paper ejecuta contra el mercado real (sandbox
   del exchange) — no contra data histórica.
2. **La comisión y el slippage se aplican igual** que en live.
3. **El paper se compara contra el backtest** como sistema de calibración.
4. **Sin suficiente muestra el paper no prueba nada.** Mínimo de trades o de
   sesiones.

## 2. Setup

- Modo: `TRADING_MODE=paper`.
- `LIVE_TRADING_ENABLED=false`.
- `EXCHANGE_SANDBOX=true`.
- Capital inicial simulado: `PAPER_INITIAL_BALANCE_USDT=10000`.
- Estrategias activas: `state ∈ {paper}` en `config/strategies.yaml`.

## 3. Métricas

- Win rate, profit factor, expectancy, max drawdown (igual que backtest).
- **Desviación paper vs backtest**:
  - Diferencia de fill (bps).
  - Diferencia de slippage (bps).
  - Diferencia de frecuencia de señales.
- **Disponibilidad**: latencia y uptime reales.

## 4. Mínimo exigido para promoción

Considerar promover una estrategia de `paper` → `live_candidate` cuando:

- Mínimo **20 sesiones de operación** o **300 trades** (lo que llegue antes).
- Profit factor ≥ 1.1 y dentro de banda aceptable vs backtest.
- Max drawdown ≤ 2.5% del capital.
- Latencia mediana ≤ `high_latency_ms` (ver `config/risk.yaml`).
- Sin errores `execution_error_definitive` en las últimas N sesiones.

## 5. Comparación con backtest

Cada día se genera `reports/paper/<YYYY-MM-DD>.md` con:

- Lista de fills (CSV/JSON).
- Métricas del día.
- Comparación vs expectativas del backtest.
- Alertas si:
  - PnL diario diverge > 50% del backtest.
  - Slippage real > 2× el estimado.
  - Win rate cae < 30%.
  - Más de 3 errores definidos en una sesión.

## 6. Lo que el paper no puede probar

- Latencia en producción (puede ser peor).
- Slippage en producción (puede ser peor).
- Errores operativos durante crisis.
- Impacto emocional en operadores humanos (si los hubiera).
- Privacidad de API keys en escenarios reales.

Por eso el paper se complementa con `11-release-live.md`.
