# Command 08 — Backtest

## Objetivo
Ejecutar o preparar un **backtest reproducible** y producir un informe.

## Agente(s) responsable(s)
- `backtest-engineer` + `quant-researcher` + `risk-manager`.

## Entradas
- Estrategia activa (`config/strategies.yaml` con `state ∈ {paper, live_candidate}`).
- Datos OHLCV (`data/raw/` o descargados).
- `config/indicators.yaml`, `config/risk.yaml`.

## Salidas
- `reports/backtests/<estrategia>-<symbol>-<fecha>.md` con métricas.
- CSV/JSON con lista de trades.
- Comparación entre al menos 2 semillas distintas.
- Walk-forward logs (cuando aplique).

## Pasos
1. Validar modo (`TRADING_MODE=backtest`).
2. Verificar que la estrategia no está `live` (bloqueo).
3. Cargar/descargar datos limpios.
4. Calcular indicadores.
5. Generar señales.
6. Pasar señales por el risk manager.
7. Simular ejecución con comisiones y slippage configurable.
8. Calcular métricas.
9. Validar ausencia de lookahead bias.
10. Walk-forward sobre segmentos.
11. Sensibilidad de parámetros.

## Criterio de finalización
- Métricas mínimas alcanzadas (definidas en `docs/backtesting-methodology.md`).
- Informe firmado por `backtest-engineer`.
- Walk-forward válido.

## NO
- No usar la misma data para optimizar parámetros y validar.
- No declarar edge sin out-of-sample.
