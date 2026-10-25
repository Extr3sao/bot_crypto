# STRATEGY_ADMISSION_CRITERIA — pre-registrados (§23)

> Comprometidos ANTES de ejecutar los baselines de las 5 familias restantes.
> Ningún umbral se ajusta después de ver resultados. Estados posibles (§24):
> REJECT / RESEARCH_REQUIRED / PAPER_CANDIDATE / PAPER_SHADOW_CANDIDATE.
> (No existen PRODUCTION/LIVE en esta fase.)

## Criterios de admission — PAPER_CANDIDATE (todos obligatorios)

1. Muestra: ≥ 100 trades totales y ≥ 30 en OOS (W7)
2. Rentabilidad tras costes BASE: net > 0 y expectancy/trade > 0
3. Profit factor BASE > 1.0 (realizado, fees+slippage incluidos)
4. OOS: net > 0 y PF_OOS > 1.0 — la evidencia fuera de muestra no puede ser negativa
5. Consistencia DEV: PF_DEV > 0.8 (sin contradicción con el resultado agregado)
6. Drawdown máximo ≤ 10% de la equity inicial en la simulación
7. Costes: PF con 2X_COST > 0.9 — sobrevive al doble de costes sin colapsar
8. No-dominancia: ninguna ventana aporta > 60% del net positivo total
9. Robustness del vecindario: no NEGATIVE_ROBUST (evaluado solo si 1-8 pasan)

## Estados intermedios

- **PAPER_SHADOW_CANDIDATE**: pasa 1,2,3,6,9 pero OOS delgado (15-29 trades)
  o PF entre 0.9-1.0 — observa en shadow, no ejecuta paper
- **RESEARCH_REQUIRED**: evidencia mixta (p.ej. positivo DEV, negativo OOS, o
  muestra insuficiente con expectancy positivo) — no ejecuta
- **REJECT**: net total ≤ 0 tras costes BASE, o PF < 0.9, o NEGATIVE_ROBUST

## Concentración y redundancia (§38-40)

- Strategy concentration: ninguna estrategia admitida puede aportar > 80% del
  net del portfolio multi-strategy (sería single-strategy disfrazado)
- REDUNDANT: overlap de trades > 70% entre dos estrategias admitidas ⇒ se
  marca la de menor robustez como redundante (no suma diversificación)

## Nota de contexto

ema_crossover ya está REJECT_AS_CURRENT_PRODUCTION_CANDIDATE (baseline
propio: PF 0.57, OOS 0.41, negativo en 4/4 variantes y 6/6 regímenes).
Estos criterios se aplican idénticos a las 5 familias candidatas.
