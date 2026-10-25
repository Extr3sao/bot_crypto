# EXPERIENCE_LEARNING_V1 — aprender sin auto-modificarse

> Implementación: `src/trading_bot/autonomous/experience.py` +
> `src/trading_bot/autonomous/outcomes.py`. Fase AUTONOMOUS-PAPER-RUNTIME-V1.

## 1. Cadena de aprendizaje

```text
DECISION (DecisionTrace)
   → OUTCOME  (OutcomeRecord, sólo si el horizonte ya transcurrió)
   → ANALYSIS (agregado por estrategia × activo × régimen × timeframe)
   → LESSON   (StrategyPerformance)
   → futuras SELECCIONES del StrategyRouter
```

## 2. Qué se registra

Por cada outcome resuelto:

| Campo | Origen |
| --- | --- |
| `gross_return_bps` | movimiento de precio ajustado por dirección |
| `estimated_cost_bps` | el coste del **mismo** modelo que usó la propuesta |
| `net_hypothetical_bps` | `gross - cost` |
| `mfe_bps` / `mae_bps` | mejor/peor excursión dentro de la ventana |
| `direction_correct` | ¿el signo era correcto? |
| `mode` | TRADE_PAPER o SHADOW_TRADE (nunca se mezclan) |
| `data_complete`, `bars_observed` | trazabilidad de la muestra |

Agregado por celda `(strategy_id, asset, regime, timeframe)`:
`sample_size`, `shadow_sample_size`, `paper_sample_size`, `gross_expectancy_bps`,
`net_expectancy_bps`, `hit_rate`, `profit_factor`, `max_drawdown_bps`,
`recent_net_expectancy_bps` (últimas 20), `historical_net_expectancy_bps`,
`confidence` (`min(1, n/200)`), `last_updated_ms`.

## 3. Qué PUEDE hacer

Sólo una cosa: **reordenar la selección** de estrategias en el siguiente ciclo.

```python
priority = clamp(net_expectancy_bps / 10, -0.25, +0.25)   # 0.0 si n < 20
```

Ese `priority` entra en la clave de ordenación del mapa de estrategias
(`gross_edge_bps + priority`), de modo que una estrategia con resultados reales
mejores se evalúa antes. El router sigue siendo el único que selecciona.

## 4. Qué NO puede hacer (por estructura, no por convención)

| Prohibido | Cómo está impedido |
| --- | --- |
| Modificar límites de riesgo | el módulo no importa `RiskManager` ni `config.risk`; no existe API de escritura |
| Modificar sizing / leverage / capital | ídem; el sizing vive en `RiskManager._compute_position_size` |
| Modificar contabilidad | el único escritor del portfolio es `PaperBroker` |
| Cambiar umbrales de admisión | la admisión es `AdmissionLedger` (datos versionados), no experiencia |
| Promocionar una estrategia a PAPER | `admitted_for_paper` sólo puede venir del ledger; experiencia no lo toca |
| Parchear una estrategia en caliente | no hay API de mutación; una mejora debe ser `RESEARCH_HYPOTHESIS`/`STRATEGY_CANDIDATE` |

Test de frontera: `tests/unit/autonomous/test_trace_replay_outcomes.py::test_experience_module_exposes_no_policy_mutation_api`
afirma que la superficie pública del store no contiene ningún nombre con
`limit/leverage/capital/admission/risk/threshold/size`.

## 5. Integridad

- `OutcomeRecord.__post_init__` exige `outcome_time_ms > decision_time_ms`
  (anti-lookahead estructural).
- Sólo `status == RESOLVED` puede alimentar la performance
  (`test_performance_cannot_be_updated_by_an_unresolved_outcome`).
- Re-procesar el mismo `decision_id` es idempotente (no suma dos veces).
- El store es durable (`performance.json`) y auditable: guarda las muestras crudas y
  deriva los agregados en lectura, así que cada número se puede rastrear hasta el
  `decision_id` que lo produjo.
- `replay(decision_id)` reconstruye la decisión original sin consultar datos futuros.

## 6. Estado actual

Con `PAPER_CANDIDATES = 0`, la experiencia se alimenta **sólo** de observaciones
SHADOW (`shadow_sample_size`) y se marca como tal: no es evidencia de ejecución real y
no puede presentarse como resultado de trading. Cuando exista un `PAPER_CANDIDATE`
admitido, las muestras PAPER se contabilizan por separado y son las únicas que podrían
justificar una promoción (que, en cualquier caso, requiere un nuevo ciclo de admisión
con evidencia OOS).
