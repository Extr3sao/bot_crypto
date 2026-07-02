# Command 09 — Paper Trading

## Objetivo
Ejecutar o preparar **paper trading** y comparar resultados contra
backtests y expectativas.

## Agente(s) responsable(s)
- `observability-engineer` + `risk-manager` + `execution-engineer`.

## Entradas
- Estrategia que superó `08-backtest.md`.
- Modo `paper` (sin envío real de órdenes).

## Salidas
- Reporte diario en `reports/paper/<YYYY-MM-DD>.md`.
- Comparativa con backtest (desviaciones de fill, slippage real vs estimado).
- Métricas vivas: win rate, PnL simulado, drawdown, latencia.

## Pasos
1. Validar `TRADING_MODE=paper`.
2. Activar `I_UNDERSTAND_THE_RISKS=false` y `LIVE_TRADING_ENABLED=false`.
3. Activar `EXCHANGE_SANDBOX=true`.
4. Correr las señales aprobadas por backtest en tiempo real.
5. Comparar cada fill simulado con el precio real del mercado.
6. Calcular métricas y compararlas con backtests.

## Criterio de finalización
- Mínimo de N sesiones/días operativos sin riesgos críticos.
- Comparativa no muestra degradación extrema.
- Métricas mínimas alcanzadas (definidas en `docs/paper-trading-methodology.md`).

## NO
- No promover a live sin paper validado.
- No aceptar paper como prueba si usó una estrategia distinta a la candidata.
