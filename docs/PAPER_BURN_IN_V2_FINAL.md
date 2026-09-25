# PAPER_BURN_IN_V2_FINAL — veredicto y decisión de roadmap

> INTERIM: sellado con la evidencia a ~6.5h de un run que continúa hasta su
> deadline de 12h (~03:09). La certificación final del escalón se regenera
> al cierre del loop con la evidencia completa (close_v2.py → RUN_SUMMARY).

## 1. Veredicto ENGINEERING HEALTH — SANO

- 4400+ ciclos 100% HEALTHY, 0 errores, 0 violaciones temporales
- 76+ restarts RECOVERED, 0 MISMATCH/FATAL, 0 duplicaciones económicas
- Bar-close gate: 95% churn eliminado, decisiones únicas preservadas
- MTM 100% disponible (PIT), reconciliación de identidad intacta
- El runtime sobrevivió colisión real de procesos (DEF-201) sin pérdida
- Runtime P0/P1 abiertos: **0** (DEF-205 fix commiteado y corriendo en vivo)

## 2. Veredicto TRADING PERFORMANCE — NEGATIVO PRELIMINAR Y CONFIRMADO OFFLINE

- Paper V2 (19 trades): net −524.55 (−19.85 ex-DEF-205), PF 0.05 (0.32 ex-DEF-205)
- Histórico (1723 trades, 7 ventanas, 3 activos): **PF 0.57, gross negativo**,
  negativo en DEV/VAL/OOS (0.63→0.47→0.41), en 4/4 variantes del vecindario
  y en 6/6 regímenes
- Causa estructural: TP 0.75% fijo vs stop 1.5×ATR (1-3.5%) — el sistema
  exige WR≥41% con payoff 1.43 y la señal entrega 28.6%
- STRATEGY_BASELINE_STATUS: `NEGATIVE_PRELIMINARY_EVIDENCE` (paper) +
  confirmación histórica ANALYZABLE_SAMPLE

## 3. DEF-205 — el hallazgo de mayor valor de V2

Snapshot inactivo (price=0.0) cerró una posición a precio 0 (−500.50,
−100% notional) → lockout diario en cascada. Fix fail-closed commiteado
(`51957e4`), tests de regresión, validación en runtime vivo en curso.
Sin este burn-in, el defecto habría llegado a producción con capital real.

## 4. Decisión de estrategia (§25)

`ema_crossover`: **REJECT_AS_CURRENT_PRODUCTION_CANDIDATE** (nivel
estrategia; el runtime queda intacto y validado). Justificado por 1723
trades históricos + consistencia paper — no por 19 trades.

## 5. Multi-strategy gap (§26) — sin cambios

momentum/breakout/trend/mean_reversion/volatility siguen
REACHABLE_NOT_SELECTABLE (map-order dominante). Razón exacta registrada en
STRATEGY_RUNTIME_INVENTORY.md. No se activan en este WP.

## 6. Próxima fase seleccionada (§14) — NO implementada todavía

**MULTI-STRATEGY-ENABLEMENT-V1** (PATH D): con ema_crossover rechazado
como production candidate y 5/6 familias no seleccionables, seguir
acumulando horas de una única estrategia sin edge no reduce riesgo de
estrategia ni de producción. Antes de eso, el cierre formal de V2 (12h)
queda como certificación de ingeniería del baseline determinista.

Bloqueos de producción restantes (§27): multi-strategy operacional,
robustez de al menos una estrategia con OOS positivo, paper long-run
de la cartera, shadow, canary, verificación independiente.

## 7. Evidencia

- docs/PAPER_BURN_IN_V2_RUN_REPORT.md + .json (interim @5.08h/@6h)
- docs/PAPER_BURN_IN_V2_ECONOMICS.md · docs/DEFECTS_BURN_IN_V2.md
- docs/EMA_CROSSOVER_PERFORMANCE_BASELINE.md + .json
- docs/STRATEGY_ROBUSTNESS.md + STRATEGY_ROBUSTNESS_VARIANTS.json
- docs/STRATEGY_PERFORMANCE_OOS.md
- docs/BAR_CLOSE_GATE_VALIDATION.md · docs/MTM_EQUITY_VALIDATION.md
- Crudos: reports/paper-burn-in/PAPER-BURN-IN-V2/ · reports/strategy-baseline/
