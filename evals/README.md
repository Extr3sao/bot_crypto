# evals/

> Evaluaciones vivas del bot, separadas de los tests.

## Subcarpetas

- `strategy-evals/` — Evaluaciones cuantitativas de estrategias:
  walk-forward, análisis de sensibilidad, comparativas contra
  baseline. Diferente de `tests/regression/` porque aquí el resultado
  se interpreta, no se verifica.
- `risk-evals/` — Evaluaciones de la política de riesgo:
  simulaciones de escenarios (incluyendo crisis sintéticas) para
  validar que el sizing y los bloqueos se comportan como se espera.
- `execution-evals/` — Evaluaciones del motor de ejecución:
  fidelidad de la simulación (paper) frente al exchange real
  (sandbox), latencias, slippage.

## Estado

Vacío por diseño en la Fase 0. Los criterios de cada evaluación
viven en `quality/risk-quality-gates.md` y `docs/*.md`.
