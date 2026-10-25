# EMA_CROSSOVER_PERFORMANCE_BASELINE — STRATEGY-PERFORMANCE-BASELINE-V1

> PATH C seleccionado tras el defecto DEF-205 y con evidencia económica
> preliminar negativa en V2. Análisis OFFLINE sobre datos reales de Binance
> (público, read-only), fiel al contrato del runtime paper.
> BASELINE_RESULTS.json (machine-readable) en docs/.

## Contrato auditado (runtime real, no asumido)

- Señal: EMA9>EMA21 & RSI14>50 → LONG; inversa → SHORT (vela cerrada)
- Stop: 1.5×ATR14 (estructural, adaptativo) · TP: +0.75% (default risk.yaml)
- Sizing: 0.25% equity / stop_pct, clamp [25, 500] USDT
- Fees 5bps/lado, slippage 1bp/lado, cooldown 3 pérdidas, daily −1%, cap 20/día
- Ambigua (SL+TP misma vela): stop_first (conservador)

## Datos

- 7 ventanas mensuales (2026-03 → 2026-09-24) × BTC/ETH/SOL, 5m
- 187k+ barras · el día del paper run (09-25) queda FUERA de todas las
  ventanas → separación limpia paper/histórico

## Resultado total — 1723 trades (ANALYZABLE_SAMPLE)

| Métrica | Valor |
| --- | ---: |
| Net PnL | **−1177.61** (gross −316.18, fees 861.40) |
| Win rate | 28.61% (493W/1230L) |
| Avg win / loss | +3.20 / −2.24 |
| Payoff | 1.43 |
| Expectancy | **−0.68/trade** |
| Profit factor | **0.57** |
| Exit mix | 1230 stops / 493 TPs (71.4% muere en stop) |

Breakeven con payoff 1.43 exige WR ≥ 41.2% — el real es 28.6%.

## Split temporal (sin optimización)

| Split | Ventanas | Trades | Net | PF | WR |
| --- | --- | ---: | ---: | ---: | ---: |
| DEV | W1-W4 | 1151 | −691.99 | 0.63 | 31.97% |
| VAL | W5-W6 | 404 | −333.01 | 0.47 | 22.77% |
| OOS | W7 | 168 | −152.60 | 0.41 | 19.64% |

Deterioro monótono DEV→VAL→OOS. La señal no persiste; empeora fuera de muestra.

## Hallazgo estructural

**El gross YA es negativo (−316)**: la asimetría TP 0.75% vs stop 1.5×ATR
(típicamente 1-3%+ en crypto 5m) hace que el sistema necesite una tasa de
aciertos que la señal EMA/RSI en 5m no proporciona. Los fees (861) triplican
el daño, pero no son la causa primaria.

## Clasificación (§25)

`REJECT_AS_CURRENT_PRODUCTION_CANDIDATE` — para la ESTRATEGIA, no para el runtime.
