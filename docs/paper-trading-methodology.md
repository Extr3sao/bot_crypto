# Paper Trading Methodology

> Como se hace paper trading, que metricas se exigen y como se compara
> contra backtests antes de promover una estrategia.

---

## 1. Principios

1. **Paper NO es backtest.** El paper ejecuta contra el mercado real (sandbox
   del exchange) y no contra data historica.
2. **La comision y el slippage se aplican igual** que en live.
3. **El paper se compara contra el backtest** como sistema de calibracion.
4. **Sin suficiente muestra el paper no prueba nada.** Minimo de trades o de
   sesiones.

## 2. Setup

- Modo: `TRADING_MODE=paper`.
- `LIVE_TRADING_ENABLED=false`.
- `EXCHANGE_SANDBOX=true`.
- Capital inicial simulado: `PAPER_INITIAL_BALANCE_USDT=10000`.
- Estrategias activas: `state in {paper}` en `config/strategies.yaml`.

## 3. Metricas

- Win rate, profit factor, expectancy, max drawdown (igual que backtest).
- **Desviacion paper vs backtest**:
  - Diferencia de fill (bps).
  - Diferencia de slippage (bps).
  - Diferencia de frecuencia de senales.
- **Disponibilidad**: latencia y uptime reales.

## 4. Minimo exigido para promocion

Considerar promover una estrategia de `paper` a `live_candidate` cuando:

- Minimo **20 sesiones de operacion** o **300 trades** (lo que llegue antes).
- Profit factor >= 1.1 y dentro de banda aceptable vs backtest.
- Max drawdown <= 2.5% del capital.
- Latencia mediana <= `high_latency_ms` (ver `config/risk.yaml`).
- Sin errores `execution_error_definitive` en las ultimas N sesiones.

## 5. Comparacion con backtest

Cada dia se genera `reports/paper/<YYYY-MM-DD>.md` con:

- Metricas del dia.
- Comparacion vs expectativas del backtest.
- Artefacto gemelo en JSON para archivado y automatizacion.
- Alertas si:
  - Frecuencia de snapshots activos diverge > 50% del backtest.
  - Spread mediano activo > 2x el estimado.
  - Active ratio cae por debajo del umbral minimo esperado.
  - Mas de 3 errores definidos en una sesion.

### Estado actual de implementacion (TSK-105)

- El informe diario se escribe automaticamente desde `PaperSessionRunner` en
  `runtime.reports.output_dir/paper/` cuando `paper_report=true`.
- `PaperSessionRunner` ya puede construirse desde `BacktestResult` o
  `FoldReport`, traduciendo la actividad del backtest a una expectativa paper
  basada en proxies.
- Existe un `PaperBroker` minimo persistente en SQLite: abre posiciones cuando
  un simbolo pasa a `active`, las mantiene mientras siga activo y las cierra
  cuando deja de estarlo, registrando fills, posiciones abiertas, trades
  cerrados, caja y equity de la sesion.
- La comparacion actual usa proxies observables ya disponibles en el scanner
  (`active_snapshots`, `median_spread_bps_active`, `scanner_errors`) porque la
  simulacion actual sigue siendo una politica minima basada en snapshots, no un
  motor de execution completo.
- Cuando exista source-of-truth de fills paper, esta seccion volvera a
  incorporar PnL, slippage real y win rate contra el backtest.

## 6. Lo que el paper no puede probar

- Latencia en produccion (puede ser peor).
- Slippage en produccion (puede ser peor).
- Errores operativos durante crisis.
- Impacto emocional en operadores humanos (si los hubiera).
- Privacidad de API keys en escenarios reales.

Por eso el paper se complementa con `11-release-live.md`.
