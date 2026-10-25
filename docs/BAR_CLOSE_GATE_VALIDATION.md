# BAR_CLOSE_GATE_VALIDATION — BURN-IN V2

## Contrato demostrado

`ema_crossover` es contractualmente BAR_CLOSE: sus inputs relevantes (OHLCV
cerrado, régimen, parámetros EMA) son invariantes dentro de una misma vela
cerrada. Lo que SÍ puede justificar re-evaluación intra-vela: cambio de estado
de portfolio/risk (cierre de posición, cooldown, reconciliación).

## Implementación (mínima, sin duplicar idempotencia)

- `PaperCycleEngine` compara por asset: `(latest_closed_bar_ts, state_version)`
  contra la última decisión; skip temprano ANTES de router/strategy/risk/broker.
- `state_version` se incrementa en cada cierre de trade y en cada restauración
  del reconciliador → una re-evaluación legítima nunca se bloquea.
- La idempotencia de ejecución (cloids) NO se toca: sigue siendo la última
  barrera (duplicate_intents=20 en el run lo demuestran operando).
- Rejections registradas como stage `bar_gate`, reason `same_bar_unchanged_state`
  — observable, nunca silencioso.

## A/B de equivalencia (§8)

| Métrica | BEFORE (pre-gate) | AFTER (gated) |
| --- | ---: | ---: |
| decisiones económicas únicas | 6 | 6 |
| evaluaciones | 135 | 9 |
| risk spam | 77 | 3 |

Mismos datos, mismo entrypoint, mismo estado inicial. Únicas decisiones
económicas = INVARIANTES. Trabajo redundante −93%.

## Evidencia del run V2 (en curso)

- 4356 gate-skips vs 213 evaluaciones reales (~95% del churn eliminado upstream).
- Ciclos: 1523+ 100% HEALTHY; 0 errores; 0 violaciones temporales.
- `bar_close_gate_skips` y `duplicate_intents` trazables por ciclo en
  events.jsonl y en `paper.cycle.completed`.

## Target §9

~54 evaluaciones/candle → 1 evaluación significativa por (asset, vela, estado).
Alcanzado: 1 evaluación por vela nueva; re-evaluaciones solo por cambio de
estado (fill/cierre/reconciliación) o vela nueva.
