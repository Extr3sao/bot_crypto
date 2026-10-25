# PAPER_BURN_IN_V2_FINAL — veredicto y decisión de roadmap

> CERRADO 2026-09-26 07:51:40 RDT: el loop v3 alcanzó su deadline ("12h target
> reached — stopping", seg=116, exit=0). Resumen final regenerado con
> close_v2.py → RUN_SUMMARY.json (evidencia completa, 6004 ciclos).

## 0. Certificación del escalón (cierre formal)

- **V2_12H_WALL_REACHED — ACTUAL_RUNTIME 9.29h** (NO certifica V2_12H_STABLE):
  el wall-clock del run fue 17.69h (25-09 14:10 → 26-09 07:51) pero el host
  estuvo suspendido 8.40h (23:27 → 07:51); el runtime real es 9.286h.
- El loop paró solo por deadline (no defecto). La reanudación tras la
  suspensión de 8.4h demuestra crash-recovery real: reconciliación RECOVERED,
  0 MISMATCH/FATAL, 0 duplicaciones económicas.
- 6004/6004 ciclos completados: 6003 HEALTHY + 1 DEGRADED (primer ciclo
  post-suspensión: 3 context_errors transitorios "insufficient history",
  siguiente ciclo HEALTHY). healthy_rate 99.98%.
- 133 restarts RECOVERED; bar-close gate 95.35% reducción de evaluaciones;
  MTM 6004/6004 OK; scanner_errors 0.
- Economics as-run (19 trades): net −524.55 (PF 0.05, DD 5.35%) — dominado
  por el trade DEF-205 (−500.50 a precio 0). Ex-DEF-205 (18 trades): net
  −24.05, PF 0.54, DD 0.30%, WR 44.4%. Consistente con el veredicto de
  estrategia: sin edge, runtime sano.
- DEF-205 validación post-fix (commit 51957e4, runner 20:15): 0 cierres a
  precio 0 desde el fix. La ventana post-reset-UTC (02:00) quedó consumida
  por la suspensión (23:27→07:51): 0 cierres nuevos post-fix — validación
  de ausencia de recurrencia, no de trading activo.
- Correcciones de tooling de cierre (no runtime): divisor ms→h de gaps
  (3.6e9→3.6e6) y renombrado temporal_violations→context_errors_transitional
  en close_v2.py; RUN_SUMMARY.json regenerado.

## 1. Veredicto ENGINEERING HEALTH — SANO

- 6004 ciclos (99.98% HEALTHY; 1 DEGRADED transitorio post-suspensión)
- 133 restarts RECOVERED, 0 MISMATCH/FATAL, 0 duplicaciones económicas
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
